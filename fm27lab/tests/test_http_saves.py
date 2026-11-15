from __future__ import annotations

import hashlib
import urllib.parse
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.application.saves import SavesService
from fm27lab.interfaces.http.app import create_app
from fm27lab.tests.test_http_health import make_app

SAVE_FIELDS = {
    "id",
    "source_path",
    "source_sha256",
    "status",
    "stage",
    "metadata",
    "created_at",
    "updated_at",
}
HTTP_METHODS = {"get", "post", "patch", "put", "delete", "options", "head"}
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


def auth(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def sha(index: int) -> str:
    return hashlib.sha256(str(index).encode("utf-8")).hexdigest()


def save_payload(index: int = 1, **overrides):
    value = {
        "source_path": f"/saves/season-{index}.fm",
        "source_sha256": sha(index),
    }
    value.update(overrides)
    return value


def create_save(client: TestClient, headers: dict, index: int = 1, **overrides) -> dict:
    response = client.post("/api/saves", json=save_payload(index, **overrides), headers=headers)
    assert response.status_code == 201
    return response.json()


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == code
    return error


def test_save_http_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    responses = (
        client.get("/api/saves"),
        client.post("/api/saves", json=save_payload()),
        client.get("/api/saves/none"),
        client.patch("/api/saves/none", json={"stage": "leagues"}),
        client.delete("/api/saves/none"),
        client.post("/api/saves/none/import", json={"leagues": {}, "clubs": {}}),
    )
    for response in responses:
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    wrong = client.get("/api/saves", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"


def test_save_http_create_list_get_delete_round_trip(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = create_save(client, headers)
    assert set(created) == SAVE_FIELDS
    assert created["id"]
    assert created["source_path"] == "/saves/season-1.fm"
    assert created["source_sha256"] == sha(1)
    assert created["status"] == "pending"
    assert created["stage"] is None
    assert created["metadata"] == {}
    for field in ("created_at", "updated_at"):
        assert created[field].endswith("+00:00")
        datetime.fromisoformat(created[field])

    listed = client.get("/api/saves", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"items": [created], "total": 1, "next_offset": None}
    fetched = client.get(f"/api/saves/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == created

    removed = client.delete(f"/api/saves/{created['id']}", headers=headers)
    assert removed.status_code == 204
    assert removed.content == b""
    assert "content-type" not in removed.headers
    assert_error(client.get(f"/api/saves/{created['id']}", headers=headers), 404, "not_found")
    assert_error(client.delete(f"/api/saves/{created['id']}", headers=headers), 404, "not_found")


def test_save_http_list_status_filter_and_pagination_boundaries(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    pending = create_save(client, headers, 1)
    reading = create_save(client, headers, 2, status="reading")
    ready = create_save(client, headers, 3, status="ready")

    filtered = client.get("/api/saves?status=reading", headers=headers).json()
    assert [item["id"] for item in filtered["items"]] == [reading["id"]]
    assert filtered["total"] == 1
    assert filtered["next_offset"] is None
    empty = client.get("/api/saves?status=cancelled", headers=headers).json()
    assert empty == {"items": [], "total": 0, "next_offset": None}
    assert_error(client.get("/api/saves?status=bogus", headers=headers), 400, "validation_failed")

    page = client.get("/api/saves?limit=2&offset=0", headers=headers).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["next_offset"] == 2
    tail = client.get("/api/saves?limit=2&offset=2", headers=headers).json()
    assert tail["total"] == 3
    assert len(tail["items"]) == 1
    assert tail["next_offset"] is None
    identifiers = {item["id"] for item in page["items"] + tail["items"]}
    assert identifiers == {pending["id"], reading["id"], ready["id"]}
    beyond = client.get("/api/saves?limit=2&offset=99", headers=headers).json()
    assert beyond == {"items": [], "total": 3, "next_offset": None}
    assert client.get("/api/saves?limit=256", headers=headers).status_code == 200
    assert client.get("/api/saves?offset=2147483647", headers=headers).status_code == 200
    for query in ("limit=1.0", "limit=0", "limit=257", "limit=abc", "offset=-1", "offset=abc"):
        assert client.get(f"/api/saves?{query}", headers=headers).status_code == 400, query


def test_save_http_create_validation_failures(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    invalid = (
        {},
        {"source_path": "", "source_sha256": sha(9)},
        {"source_path": "/saves/x.fm"},
        {"source_path": "/saves/x.fm", "source_sha256": "not-a-hash"},
        {"source_path": "/saves/x.fm", "source_sha256": sha(9), "status": "unknown"},
        {"source_path": "/saves/x.fm", "source_sha256": sha(9), "status": None},
        {"source_path": "/saves/x.fm", "source_sha256": sha(9), "stage": ""},
        {"source_path": "/saves/x.fm", "source_sha256": sha(9), "stage": 5},
        {"source_path": "/saves/x.fm", "source_sha256": sha(9), "metadata": []},
        {"source_path": 5, "source_sha256": sha(9)},
        {"source_path": "/saves/x.fm", "source_sha256": 5},
        {"source_path": "/saves/x.fm", "source_sha256": sha(9), "unknown": True},
    )
    for payload in invalid:
        assert_error(client.post("/api/saves", json=payload, headers=headers), 400, "validation_failed")
    assert client.get("/api/saves", headers=headers).json()["total"] == 0


def test_save_http_duplicate_sha_conflicts_without_writes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = create_save(client, headers, 1)
    duplicate = client.post(
        "/api/saves",
        json=save_payload(2, source_sha256=created["source_sha256"]),
        headers=headers,
    )
    assert_error(duplicate, 409, "conflict")
    assert client.get("/api/saves", headers=headers).json()["items"] == [created]


def test_save_http_patch_transitions_and_validation_keeps_state(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = create_save(client, headers)
    save_id = created["id"]
    snapshot = created

    conflict = client.patch(f"/api/saves/{save_id}", json={"status": "ready"}, headers=headers)
    assert_error(conflict, 409, "invalid_transition")
    assert client.get(f"/api/saves/{save_id}", headers=headers).json() == snapshot

    invalid = (
        {},
        {"status": "bogus"},
        {"status": None},
        {"status": 5},
        {"stage": 5},
        {"metadata": None},
        {"metadata": []},
        {"source_path": "/saves/other.fm"},
        {"unknown": True},
    )
    for payload in invalid:
        response = client.patch(f"/api/saves/{save_id}", json=payload, headers=headers)
        assert_error(response, 400, "validation_failed")
        assert client.get(f"/api/saves/{save_id}", headers=headers).json() == snapshot
    nan = client.patch(
        f"/api/saves/{save_id}",
        content=b'{"metadata": {"bad": NaN}}',
        headers={**headers, "Content-Type": "application/json"},
    )
    assert_error(nan, 400, "validation_failed")
    assert client.get(f"/api/saves/{save_id}", headers=headers).json() == snapshot

    reading = client.patch(f"/api/saves/{save_id}", json={"status": "reading"}, headers=headers)
    assert reading.status_code == 200
    assert reading.json()["status"] == "reading"
    detailed = client.patch(
        f"/api/saves/{save_id}",
        json={"stage": "leagues", "metadata": {"联赛": "英超"}},
        headers=headers,
    )
    assert detailed.status_code == 200
    assert detailed.json()["status"] == "reading"
    assert detailed.json()["stage"] == "leagues"
    assert detailed.json()["metadata"] == {"联赛": "英超"}
    assert detailed.json()["created_at"] == created["created_at"]
    ready = client.patch(f"/api/saves/{save_id}", json={"status": "ready"}, headers=headers)
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    terminal = client.patch(f"/api/saves/{save_id}", json={"status": "reading"}, headers=headers)
    assert_error(terminal, 409, "invalid_transition")
    assert client.get(f"/api/saves/{save_id}", headers=headers).json() == ready.json()

    assert_error(
        client.patch("/api/saves/missing", json={"stage": "leagues"}, headers=headers),
        404,
        "not_found",
    )
    assert_error(client.patch("/api/saves/missing", json={}, headers=headers), 400, "validation_failed")


def test_save_http_import_replaces_children_and_marks_ready(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = create_save(client, headers, status="reading", stage="old", metadata={"来源": "手动"})
    save_id = created["id"]
    response = client.post(
        f"/api/saves/{save_id}/import",
        json={
            "leagues": {"premier": {"clubs": [1, 2]}, "la-liga": {"clubs": [3]}},
            "clubs": {"10": {"name": "甲"}, "2": {"name": "乙"}},
            "stage": "leagues",
        },
        headers=headers,
    )
    assert response.status_code == 200
    imported = response.json()
    assert set(imported) == SAVE_FIELDS
    assert imported["id"] == save_id
    assert imported["status"] == "ready"
    assert imported["stage"] == "leagues"
    assert imported["metadata"] == {"来源": "手动"}
    assert imported["source_path"] == created["source_path"]
    assert imported["source_sha256"] == created["source_sha256"]
    assert imported["created_at"] == created["created_at"]
    assert client.get(f"/api/saves/{save_id}", headers=headers).json() == imported
    assert [row["league_key"] for row in app.state.saves.leagues(save_id)] == ["la-liga", "premier"]
    assert [row["club_uid"] for row in app.state.saves.clubs(save_id)] == [2, 10]

    cleared = client.post(
        f"/api/saves/{save_id}/import",
        json={"leagues": {}, "clubs": {}},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "ready"
    assert cleared.json()["stage"] is None
    assert app.state.saves.leagues(save_id) == []
    assert app.state.saves.clubs(save_id) == []


def test_save_http_import_missing_save_is_not_found(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    response = client.post("/api/saves/missing/import", json={"leagues": {}, "clubs": {}}, headers=headers)
    assert_error(response, 404, "not_found")
    assert client.get("/api/saves", headers=headers).json()["total"] == 0


def test_save_http_import_invalid_payload_keeps_state(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = create_save(client, headers, status="reading", stage="old", metadata={"a": 1})
    save_id = created["id"]
    app.state.saves.set_league(save_id, "keep", {"v": 1})
    app.state.saves.set_club(save_id, 7, {"v": 1})
    before = client.get(f"/api/saves/{save_id}", headers=headers).json()

    invalid = (
        {"leagues": {"premier": {"v": 1}, "": {}}, "clubs": {}},
        {"leagues": {}, "clubs": {"abc": {}}},
        {"leagues": {}, "clubs": {"-1": {}}},
        {"leagues": {}, "clubs": {"1.5": {}}},
        {"leagues": {}, "clubs": {"": {}}},
        {"leagues": {}, "clubs": {"0": {}}},
        {"leagues": {"premier": {"v": 1}}, "clubs": {}, "stage": ""},
        {"leagues": [], "clubs": {}},
        {"leagues": {}, "clubs": []},
        {"leagues": {}, "clubs": {}, "unknown": True},
    )
    for payload in invalid:
        response = client.post(f"/api/saves/{save_id}/import", json=payload, headers=headers)
        assert_error(response, 400, "validation_failed")
        assert client.get(f"/api/saves/{save_id}", headers=headers).json() == before
        assert [row["league_key"] for row in app.state.saves.leagues(save_id)] == ["keep"]
        assert [row["club_uid"] for row in app.state.saves.clubs(save_id)] == [7]
    nan = client.post(
        f"/api/saves/{save_id}/import",
        content=b'{"leagues": {"premier": {"bad": NaN}}, "clubs": {}}',
        headers={**headers, "Content-Type": "application/json"},
    )
    assert_error(nan, 400, "validation_failed")
    assert client.get(f"/api/saves/{save_id}", headers=headers).json() == before
    assert [row["league_key"] for row in app.state.saves.leagues(save_id)] == ["keep"]
    assert [row["club_uid"] for row in app.state.saves.clubs(save_id)] == [7]


def test_save_http_invalid_identifiers_are_validation_errors(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    for identifier in ("存档", "a b", "x" * 65):
        quoted = urllib.parse.quote(identifier, safe="")
        assert_error(client.get(f"/api/saves/{quoted}", headers=headers), 400, "validation_failed")
        assert_error(client.delete(f"/api/saves/{quoted}", headers=headers), 400, "validation_failed")
        assert_error(
            client.patch(f"/api/saves/{quoted}", json={"stage": "leagues"}, headers=headers),
            400,
            "validation_failed",
        )
        assert_error(
            client.post(f"/api/saves/{quoted}/import", json={"leagues": {}, "clubs": {}}, headers=headers),
            400,
            "validation_failed",
        )


def test_save_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    paths = document["paths"]
    for path in ("/api/saves", "/api/saves/{save_id}", "/api/saves/{save_id}/import"):
        assert path in paths
    for path, operations in paths.items():
        if not path.startswith("/api/saves"):
            continue
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            assert operation["security"] == [{"HTTPBearer": []}], (path, method)
            assert "422" not in operation["responses"], (path, method)
            for status in ("400", "401"):
                assert status in operation["responses"], (path, method)
                schema = operation["responses"][status]["content"]["application/json"]["schema"]
                assert schema["$ref"].endswith("ErrorEnvelope"), (path, method, status)

    list_operation = paths["/api/saves"]["get"]
    assert list_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "SaveListOutput"
    )
    assert paths["/api/saves"]["post"]["responses"]["201"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("SaveOutput")
    member_operations = paths["/api/saves/{save_id}"]
    for method in ("get", "patch"):
        assert member_operations[method]["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("SaveOutput")
    for status in ("404",):
        for method in ("get", "patch", "delete"):
            schema = member_operations[method]["responses"][status]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("ErrorEnvelope")
    assert member_operations["patch"]["responses"]["409"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("ErrorEnvelope")
    import_operation = paths["/api/saves/{save_id}/import"]["post"]
    assert import_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "SaveOutput"
    )
    assert import_operation["responses"]["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorEnvelope"
    )

    components = document["components"]["schemas"]
    output_schema = components["SaveOutput"]
    assert set(output_schema["properties"]) == SAVE_FIELDS
    assert set(output_schema["required"]) == SAVE_FIELDS
    create_input = components["SaveCreateInput"]
    assert set(create_input["properties"]) == {
        "source_path",
        "source_sha256",
        "status",
        "stage",
        "metadata",
    }
    assert create_input["additionalProperties"] is False
    update_input = components["SaveUpdateInput"]
    assert set(update_input["properties"]) == {"status", "stage", "metadata"}
    assert update_input["additionalProperties"] is False
    import_input = components["SaveImportInput"]
    assert set(import_input["properties"]) == {"leagues", "clubs", "stage"}
    assert import_input["additionalProperties"] is False

    parameters = {item["name"]: item["schema"] for item in list_operation["parameters"]}
    assert "status" in parameters
    assert parameters["limit"]["type"] == "integer"
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 256
    assert parameters["limit"]["default"] == 50
    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["default"] == 0
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_save_http_cors_405_and_existing_routes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    preflight = client.options(
        "/api/saves/x",
        headers={"Origin": "tauri://localhost", "Access-Control-Request-Method": "PATCH"},
    )
    assert preflight.status_code == 200
    assert "PATCH" in preflight.headers["access-control-allow-methods"]

    wrong = client.put("/api/saves", headers=headers)
    assert wrong.status_code == 405
    assert "GET" in wrong.headers["allow"] and "POST" in wrong.headers["allow"]
    wrong_member = client.put("/api/saves/x", headers=headers)
    assert wrong_member.status_code == 405
    member_methods = {item.strip() for item in wrong_member.headers["allow"].split(",")}
    assert {"GET", "PATCH", "DELETE"} <= member_methods
    wrong_import = client.put("/api/saves/x/import", headers=headers)
    assert wrong_import.status_code == 405
    assert "POST" in wrong_import.headers["allow"]

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/version").status_code == 200
    assert client.get("/api/pools", headers=headers).json()["items"] == []
    assert client.get("/api/drafts", headers=headers).json()["items"] == []
    assert client.get("/api/jobs", headers=headers).json()["items"] == []


def test_save_http_service_injection_and_duplicate_id_conflict(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    headers = auth(settings)
    assert isinstance(app.state.saves, SavesService)

    class FakeSaves:
        def list(self, status=None, limit=50, offset=0):
            return {"items": [], "total": 0, "next_offset": None}

        def create(self, source_path, source_sha256, *, status="pending", stage=None, metadata=None):
            raise ValueError("存档已存在")

        def get(self, save_id):
            return None

        def update(self, save_id, changes):
            return None

        def delete(self, save_id):
            return False

        def import_payload(self, save_id, leagues, clubs, *, stage=None):
            raise ValueError("存档不存在")

    second = create_app(settings, database, saves_service=FakeSaves())
    fake_client = TestClient(second)
    assert fake_client.get("/api/saves", headers=headers).json() == {
        "items": [],
        "total": 0,
        "next_offset": None,
    }
    conflict = fake_client.post("/api/saves", json=save_payload(), headers=headers)
    assert_error(conflict, 409, "conflict")
    assert_error(fake_client.get("/api/saves/none", headers=headers), 404, "not_found")
