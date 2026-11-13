from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.domain.attributes import ATTRIBUTE_COUNT, VISIBLE_GROUPS, group_indices
from fm27lab.domain.roster import POSITION_INDEX
from fm27lab.tests.test_http_health import make_app

VISIBLE_INDICES = sorted(frozenset().union(*(group_indices(group) for group in VISIBLE_GROUPS)))
SUMMARY_KEYS = ("id", "name", "source", "created_at", "updated_at")
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


def auth(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def player(uid):
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[0 if uid == 100 else 7] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes}


def team(name="Home"):
    return {
        "name": name,
        "players": [player(100 + index) for index in range(23)],
        "roster_size": 23,
        "lineup": list(range(11)),
        "captains": [5],
        "takers": {"penalties": [6]},
        "setpieces": {"role_priorities": {"8": [8]}},
    }


def scenario():
    return {"schema": 4, "teams": [team("Home"), team("Away")]}


def create_draft(client, headers):
    response = client.post(
        "/api/drafts",
        json={"name": "Draft", "scenario": scenario(), "source": {"kind": "inline"}},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def apply_attributes(client, headers, draft_id, body):
    return client.post(f"/api/drafts/{draft_id}/attributes", json=body, headers=headers)


def test_http_draft_attributes_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    body = {"side": "home", "scope": "all", "operation": "bulk", "params": {"value": 12}}
    assert client.post("/api/drafts/x/attributes", json=body).status_code == 401
    wrong = client.post(
        "/api/drafts/x/attributes",
        json=body,
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401
    error = wrong.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "unauthorized"


def test_http_draft_attributes_apply_and_undo_round_trip(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    draft = create_draft(client, headers)
    response = apply_attributes(
        client,
        headers,
        draft["id"],
        {"side": "home", "scope": "all", "operation": "bulk", "params": {"value": 12}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"draft", "snapshot", "changed_players"}
    assert payload["changed_players"] == 23
    snapshot = payload["snapshot"]
    assert snapshot["side"] == "home"
    assert snapshot["scope"] == "all"
    assert snapshot["operation"] == "bulk"
    assert snapshot["indices"] == VISIBLE_INDICES
    refetched = client.get(f"/api/drafts/{draft['id']}", headers=headers).json()
    assert refetched["source"]["attribute_snapshot"] == snapshot
    assert payload["draft"] == {key: refetched[key] for key in SUMMARY_KEYS}
    home = refetched["scenario"]["teams"][0]["players"]
    assert all({entry["attributes"][index] for index in VISIBLE_INDICES} == {60} for entry in home)
    assert refetched["scenario"]["teams"][1]["players"] == draft["scenario"]["teams"][1]["players"]

    undone = apply_attributes(
        client,
        headers,
        draft["id"],
        {"side": "home", "scope": "all", "operation": "undo", "params": {}},
    )
    assert undone.status_code == 200
    assert undone.json()["snapshot"] is None
    assert undone.json()["changed_players"] == 23
    restored = client.get(f"/api/drafts/{draft['id']}", headers=headers).json()
    assert restored["scenario"] == draft["scenario"]
    assert restored["source"] == draft["source"]

    again = apply_attributes(
        client,
        headers,
        draft["id"],
        {"side": "home", "scope": "all", "operation": "undo", "params": {}},
    )
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "validation_failed"
    assert "没有可撤销的属性修改" in again.json()["error"]["message"]


def test_http_draft_attributes_player_scope_and_position_operation(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    draft = create_draft(client, headers)
    response = apply_attributes(
        client,
        headers,
        draft["id"],
        {
            "side": "away",
            "scope": "player",
            "player_index": 4,
            "operation": "position",
            "params": {"position": "ST", "value": 9},
        },
    )
    assert response.status_code == 200
    assert response.json()["changed_players"] == 1
    refetched = client.get(f"/api/drafts/{draft['id']}", headers=headers).json()
    assert refetched["scenario"]["teams"][1]["players"][4]["attributes"][POSITION_INDEX["ST"]] == 9
    assert refetched["scenario"]["teams"][0]["players"] == draft["scenario"]["teams"][0]["players"]


def test_http_draft_attributes_validation_and_missing_draft(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    draft = create_draft(client, headers)
    valid = {"side": "home", "scope": "all", "operation": "bulk", "params": {"value": 12}}

    missing = apply_attributes(client, headers, "missing", valid)
    assert missing.status_code == 404
    error = missing.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "not_found"

    for body, message in (
        ({**valid, "side": "both"}, "side"),
        ({**valid, "scope": "bench"}, "scope"),
        ({**valid, "scope": "player", "player_index": None}, "player_index"),
        ({**valid, "operation": "boost", "params": {}}, "操作"),
        ({**valid, "operation": "undo", "params": {}}, "没有可撤销的属性修改"),
        ({**valid, "params": {}}, "value"),
        ({**valid, "params": {"value": 21}}, "属性显示值"),
        ({**valid, "extra": 1}, "request body"),
        ({"side": "home", "scope": "all", "operation": "bulk"}, "request body"),
        ({**valid, "side": 0}, "request body"),
        ({**valid, "params": []}, "request body"),
        ({**valid, "operation": "copy", "params": {"source_uid": 999}}, "参考球员"),
    ):
        response = apply_attributes(client, headers, draft["id"], body)
        assert response.status_code == 400, body
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS, body
        assert error["code"] == "validation_failed", body
        assert message in error["message"], body
    unchanged = client.get(f"/api/drafts/{draft['id']}", headers=headers).json()
    assert unchanged == draft


def test_http_draft_attributes_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    path = "/api/drafts/{draft_id}/attributes"
    assert path in document["paths"]
    operation = document["paths"][path]["post"]
    assert "422" not in operation["responses"]
    for status in ("400", "401", "404"):
        reference = operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert reference.endswith("ErrorEnvelope"), status
    assert operation["security"] == [{"HTTPBearer": []}]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert request_schema.endswith("DraftAttributeInput")
    input_schema = document["components"]["schemas"]["DraftAttributeInput"]
    assert set(input_schema["required"]) == {"side", "scope", "operation", "params"}
    assert input_schema["additionalProperties"] is False
    output_schema = document["components"]["schemas"]["DraftAttributeOutput"]
    assert set(output_schema["required"]) == {"draft", "snapshot", "changed_players"}
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_http_draft_attributes_service_is_injectable(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    del app

    class FakeAttributes:
        def __init__(self):
            self.calls = []

        def apply(self, draft_id, *, side, scope, player_index, operation, params):
            self.calls.append((draft_id, side, scope, player_index, operation, params))
            return {
                "draft": {
                    "id": "fake",
                    "name": "Fake",
                    "source": {},
                    "created_at": "a",
                    "updated_at": "a",
                },
                "snapshot": None,
                "changed_players": 0,
            }

    from fm27lab.interfaces.http.app import create_app

    fake = FakeAttributes()
    second = create_app(settings, database, draft_attribute_service=fake)
    response = TestClient(second).post(
        "/api/drafts/draft-1/attributes",
        json={"side": "away", "scope": "starters", "operation": "undo", "params": {}},
        headers=auth(settings),
    )
    assert response.status_code == 200
    assert response.json()["draft"]["id"] == "fake"
    assert fake.calls == [("draft-1", "away", "starters", None, "undo", {})]
