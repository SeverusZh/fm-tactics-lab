import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.adapters.catalog_native.catalog import CatalogRepository
from fm27lab.application.tactics_validation import TacticalValidator
from fm27lab.interfaces.http.app import create_app
from fm27lab.tests.test_http_health import make_app
from fm27lab.tests.test_tactics_validation import catalog_document, invalid_plan, phases


def auth(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def player(uid):
    attributes = [10] * 69
    attributes[0 if uid == 100 else 7] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes}


def team(count=26):
    return {
        "name": "Home",
        "players": [player(100 + index) for index in range(count)],
        "roster_size": count,
        "lineup": list(range(11)),
        "captains": [5],
        "takers": {"penalties": [6]},
        "setpieces": {"role_priorities": {"8": [8]}},
    }


def scenario(count=26):
    return {"schema": 4, "teams": [team(count), team(count)]}


def body(name="Draft", count=26):
    return {"name": name, "scenario": scenario(count), "source": {"kind": "inline"}}


def test_draft_http_requires_token(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.get("/api/drafts").status_code == 401
    assert client.post("/api/drafts", json=body()).status_code == 401
    assert client.get("/api/drafts/none").status_code == 401
    assert client.patch("/api/drafts/none", json={"name": "x"}).status_code == 401
    assert client.delete("/api/drafts/none").status_code == 401


def test_draft_http_round_trip_and_normalization(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = client.post("/api/drafts", json=body(), headers=headers)
    assert created.status_code == 201
    draft = created.json()
    assert len(draft["scenario"]["teams"][0]["players"]) == 23
    assert draft["scenario"]["teams"][0]["roster_trim"]["source_size"] == 26
    listed = client.get("/api/drafts", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["items"] == [
        {
            "id": draft["id"],
            "name": "Draft",
            "source": {"kind": "inline"},
            "created_at": draft["created_at"],
            "updated_at": draft["updated_at"],
        }
    ]
    assert listed.json()["total"] == 1
    fetched = client.get(f"/api/drafts/{draft['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == draft
    updated = client.patch(f"/api/drafts/{draft['id']}", json={"name": "Renamed"}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert client.get(f"/api/drafts/{draft['id']}", headers=headers).json()["name"] == "Renamed"
    removed = client.delete(f"/api/drafts/{draft['id']}", headers=headers)
    assert removed.status_code == 204
    assert removed.content == b""
    assert client.get(f"/api/drafts/{draft['id']}", headers=headers).status_code == 404


def test_draft_http_validation_missing_and_pagination(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    for payload in (
        {"name": "", "scenario": scenario(23)},
        {"name": "x", "scenario": []},
        {"name": "x", "scenario": scenario(23), "source": []},
        {"name": "x", "scenario": scenario(23), "unknown": True},
    ):
        response = client.post("/api/drafts", json=payload, headers=headers)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_failed"
    assert client.get("/api/drafts/missing", headers=headers).status_code == 404
    assert client.patch("/api/drafts/missing", json={"name": "x"}, headers=headers).status_code == 404
    assert client.delete("/api/drafts/missing", headers=headers).status_code == 404
    assert client.patch("/api/drafts/missing", json={}, headers=headers).status_code == 400
    for index in range(3):
        assert client.post("/api/drafts", json=body(f"D{index}", 23), headers=headers).status_code == 201
    page = client.get("/api/drafts?limit=2&offset=0", headers=headers).json()
    assert len(page["items"]) == 2
    assert page["total"] == 3
    assert page["next_offset"] == 2
    for query in ("limit=1.0", "limit=abc", "limit=0", "limit=129", "offset=-1"):
        assert client.get(f"/api/drafts?{query}", headers=headers).status_code == 400


def test_draft_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    assert "/api/drafts" in document["paths"]
    assert "/api/drafts/{draft_id}" in document["paths"]
    for operation in document["paths"]["/api/drafts"].values():
        assert "422" not in operation["responses"]
    get_operation = document["paths"]["/api/drafts/{draft_id}"]["get"]
    assert get_operation["responses"]["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorEnvelope"
    )
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    for path, operations in document["paths"].items():
        if path.startswith("/api/drafts"):
            for operation in operations.values():
                assert operation["security"] == [{"HTTPBearer": []}]
    params = {item["name"]: item["schema"] for item in document["paths"]["/api/drafts"]["get"]["parameters"]}
    assert params["limit"]["type"] == "integer"
    assert params["limit"]["default"] == 128
    assert params["offset"]["default"] == 0


def test_draft_http_cors_patch_and_injection(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    client = TestClient(app)
    preflight = client.options(
        "/api/drafts/x",
        headers={"Origin": "tauri://localhost", "Access-Control-Request-Method": "PATCH"},
    )
    assert preflight.status_code == 200
    assert "PATCH" in preflight.headers["access-control-allow-methods"]

    class FakeDrafts:
        def list(self, limit=128, offset=0):
            return {"items": [], "total": 0, "next_offset": None}

        def create(self, name, scenario, source=None):
            return {
                "id": "fake",
                "name": name,
                "source": source or {},
                "scenario": scenario,
                "created_at": "a",
                "updated_at": "a",
            }

        def get(self, draft_id):
            return None

        def update(self, draft_id, **changes):
            return None

        def delete(self, draft_id):
            return False

    from fm27lab.interfaces.http.app import create_app

    second = create_app(settings, database, draft_service=FakeDrafts())
    assert TestClient(second).get("/api/drafts", headers=auth(settings)).json()["items"] == []


def test_draft_patch_normalizes_scenario_and_keeps_created_at(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = client.post("/api/drafts", json=body(), headers=headers).json()
    patched = client.patch(
        f"/api/drafts/{created['id']}",
        json={"scenario": scenario(30)},
        headers=headers,
    )
    assert patched.status_code == 200
    value = patched.json()
    assert len(value["scenario"]["teams"][0]["players"]) == 23
    assert value["created_at"] == created["created_at"]
    assert value["updated_at"] >= created["updated_at"]
    assert client.get(f"/api/drafts/{created['id']}", headers=headers).json() == value


def write_validation_catalog(tmp_path: Path) -> None:
    (tmp_path / "catalog.json").write_text(json.dumps(catalog_document()), encoding="utf-8")


def tactic_scenario(plan):
    value = scenario(26)
    for side in value["teams"]:
        side["phases"] = copy.deepcopy(plan)
    return value


def test_draft_http_rejects_invalid_tactics_when_catalog_available(tmp_path: Path):
    write_validation_catalog(tmp_path)
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    rejected = client.post(
        "/api/drafts",
        json={"name": "Bad", "scenario": tactic_scenario(invalid_plan())},
        headers=headers,
    )
    assert rejected.status_code == 400
    error = rejected.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["message"] == "战术角色不具备该位置资格"
    listing = client.get("/api/drafts", headers=headers)
    assert listing.json()["total"] == 0
    created = client.post(
        "/api/drafts",
        json={"name": "Good", "scenario": tactic_scenario(phases())},
        headers=headers,
    )
    assert created.status_code == 201
    assert len(created.json()["scenario"]["teams"][1]["phases"]) == 2


def test_draft_http_rejects_invalid_tactics_on_update(tmp_path: Path):
    write_validation_catalog(tmp_path)
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    draft = client.post(
        "/api/drafts",
        json={"name": "Good", "scenario": tactic_scenario(phases())},
        headers=headers,
    ).json()
    before = client.get(f"/api/drafts/{draft['id']}", headers=headers).json()
    rejected = client.patch(
        f"/api/drafts/{draft['id']}",
        json={"scenario": tactic_scenario(invalid_plan())},
        headers=headers,
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["message"] == "战术角色不具备该位置资格"
    after = client.get(f"/api/drafts/{draft['id']}", headers=headers).json()
    assert after["scenario"] == before["scenario"]
    accepted = client.patch(
        f"/api/drafts/{draft['id']}",
        json={"scenario": tactic_scenario(phases())},
        headers=headers,
    )
    assert accepted.status_code == 200
    assert len(accepted.json()["scenario"]["teams"][0]["phases"]) == 2


def test_draft_http_update_without_scenario_skips_tactics_validation(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = client.post(
        "/api/drafts",
        json={"name": "Draft", "scenario": tactic_scenario(invalid_plan())},
        headers=headers,
    )
    assert created.status_code == 201
    write_validation_catalog(tmp_path)
    patched = client.patch(
        f"/api/drafts/{created.json()['id']}",
        json={"name": "Renamed"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"


def test_draft_http_skips_tactics_validation_without_catalog(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = client.post(
        "/api/drafts",
        json={"name": "Bad", "scenario": tactic_scenario(invalid_plan())},
        headers=headers,
    )
    assert created.status_code == 201
    patched = client.patch(
        f"/api/drafts/{created.json()['id']}",
        json={"scenario": tactic_scenario(invalid_plan())},
        headers=headers,
    )
    assert patched.status_code == 200


@pytest.mark.parametrize("content", ["{", "[]"])
def test_draft_http_skips_tactics_validation_with_invalid_catalog(tmp_path: Path, content: str):
    (tmp_path / "catalog.json").write_text(content, encoding="utf-8")
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/drafts",
        json={"name": "Bad", "scenario": tactic_scenario(invalid_plan())},
        headers=auth(settings),
    )
    assert created.status_code == 201


class _StubCatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def snapshot(self):
        return {"available": False, "catalog": None}


def test_draft_http_reuses_injected_catalog_repository(tmp_path: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "catalog.json").write_text(json.dumps(catalog_document()), encoding="utf-8")
    _, settings, _, database = make_app(tmp_path)
    app = create_app(
        settings,
        database,
        catalog_service=_StubCatalogService(CatalogRepository(None, shared)),
    )
    response = TestClient(app).post(
        "/api/drafts",
        json={"name": "Bad", "scenario": tactic_scenario(invalid_plan())},
        headers=auth(settings),
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "战术角色不具备该位置资格"


class _FakeDraftService:
    def __init__(self) -> None:
        self.created = 0

    def list(self, limit=128, offset=0):
        return {"items": [], "total": 0, "next_offset": None}

    def create(self, name, scenario, source=None):
        self.created += 1
        return {
            "id": "fake",
            "name": name,
            "source": source or {},
            "scenario": scenario,
            "created_at": "a",
            "updated_at": "a",
        }

    def get(self, draft_id):
        return None

    def update(self, draft_id, **changes):
        return None

    def delete(self, draft_id):
        return False


def test_draft_http_does_not_wrap_injected_draft_service(tmp_path: Path):
    write_validation_catalog(tmp_path)
    _, settings, _, database = make_app(tmp_path)
    fake = _FakeDraftService()
    app = create_app(settings, database, draft_service=fake)
    assert app.state.drafts is fake
    response = TestClient(app).post(
        "/api/drafts",
        json={"name": "Bad", "scenario": tactic_scenario(invalid_plan())},
        headers=auth(settings),
    )
    assert response.status_code == 201
    assert fake.created == 1


class _RejectingValidator:
    def validate(self, scenario):
        raise ValueError("自定义战术校验失败")


def test_create_app_uses_injected_tactics_validator(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    assert isinstance(app.state.tactics_validator, TacticalValidator)
    second = create_app(settings, database, tactics_validator=_RejectingValidator())
    response = TestClient(second).post("/api/drafts", json=body(), headers=auth(settings))
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "自定义战术校验失败"


def test_create_app_shares_catalog_repository_with_catalog_service(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    assert app.state.catalog_service.repository is app.state.tactics_validator.repository
