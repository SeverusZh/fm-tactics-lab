"""存档战术库 HTTP 接口契约测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.adapters.engine_native.tactic_file import UNCONFIGURED_ERROR, TacticFileError, TacticPlan
from fm27lab.adapters.save_fmsave.tactics import StoredTactic
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository
from fm27lab.application.drafts import DraftService
from fm27lab.application.save_tactics import (
    ENGINE_UNAVAILABLE_MESSAGE,
    SAVE_MISSING_ERROR,
    TACTIC_MISSING_ERROR,
    TACTIC_TEAM_ERROR,
    SaveTacticsService,
)
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import create_app
from fm27lab.tests.test_http_drafts import auth
from fm27lab.tests.test_http_drafts import scenario as draft_scenario
from fm27lab.tests.test_http_health import make_app

LIST_PATH = "/api/saves/{save_id}/tactics"
IMPORT_PATH = "/api/saves/{save_id}/tactics/{tactic_index}/import"
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
ITEMS = [
    {
        "index": 0,
        "name": "Tactic",
        "style": "Control",
        "mentality": 5,
        "club_uid": 7,
        "club_name": "Sev",
        "team_slot": 0,
        "importable": True,
    }
]
DRAFT = {
    "id": "draft-1",
    "name": "Tactic",
    "source": {"kind": "save_tactic"},
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "scenario": {"schema": 4, "teams": []},
}
PLAN = TacticPlan(name="native", mentality=4, team_bits=0, mapping=tuple(range(11)), phases=((), ()))
ROW = StoredTactic(
    index=0,
    name="Direct",
    style="Control",
    mentality=5,
    club_uid=7,
    club_name="Sev",
    team_slot=0,
    has_stream=True,
)


class FakeService:
    def __init__(self, *, items=None, draft=None, error=None):
        self.items = items
        self.draft = draft
        self.error = error
        self.calls = []

    def list_tactics(self, save_id):
        self.calls.append(("list", save_id))
        if self.error is not None:
            raise self.error
        return self.items

    def import_tactic(self, save_id, tactic_index, name=None):
        self.calls.append(("import", save_id, tactic_index, name))
        if self.error is not None:
            raise self.error
        return self.draft


def make_client(tmp_path: Path, service=None):
    app, settings, _, _ = make_app(tmp_path)
    if service is not None:
        app.state.save_tactics = service
    return TestClient(app), settings


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == code
    return error


def make_integration_client(tmp_path: Path, *, engine: bool = True):
    settings = Settings.create(
        data_dir=tmp_path / "data",
        token="c" * 64,
        engine_root=(tmp_path / "engine") if engine else None,
        game_root=(tmp_path / "game") if engine else None,
        dev=True,
    )
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    app = create_app(settings, database, draft_service=DraftService(DraftRepository(database)))
    client = TestClient(app)
    service = SaveTacticsService(
        app.state.saves,
        app.state.drafts,
        settings,
        reader=lambda path: (ROW,),
        stream_reader=lambda path, index: b"raw-stream",
        parser=lambda payload, **kwargs: PLAN,
        assets_loader=lambda root: object(),
        builder=lambda assets, plan, tactic_name=None: draft_scenario(),
    )
    app.state.save_tactics = service
    return client, settings


def create_save(client: TestClient, settings: Settings, source: Path) -> dict:
    payload = {
        "source_path": str(source),
        "source_sha256": hashlib.sha256(str(source).encode("utf-8")).hexdigest(),
    }
    response = client.post("/api/saves", json=payload, headers=auth(settings))
    assert response.status_code == 201, response.text
    return response.json()


def test_save_tactics_http_requires_token(tmp_path: Path):
    client, _ = make_client(tmp_path)

    for response in (
        client.get(LIST_PATH.format(save_id="save-1")),
        client.post(IMPORT_PATH.format(save_id="save-1", tactic_index=0)),
    ):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_save_tactics_http_returns_not_found_for_unknown_save(tmp_path: Path):
    service = FakeService(items=None, draft=None)
    client, settings = make_client(tmp_path, service)

    error = assert_error(client.get(LIST_PATH.format(save_id="missing"), headers=auth(settings)), 404, "not_found")
    assert error["message"] == "存档不存在"

    error = assert_error(
        client.post(IMPORT_PATH.format(save_id="missing", tactic_index=0), headers=auth(settings)),
        404,
        "not_found",
    )
    assert error["message"] == "存档不存在"


def test_save_tactics_http_lists_items(tmp_path: Path):
    service = FakeService(items=ITEMS)
    client, settings = make_client(tmp_path, service)

    response = client.get(LIST_PATH.format(save_id="save-1"), headers=auth(settings))

    assert response.status_code == 200
    assert response.json() == {"items": ITEMS}
    assert service.calls == [("list", "save-1")]


def test_save_tactics_http_imports_draft(tmp_path: Path):
    service = FakeService(draft=DRAFT)
    client, settings = make_client(tmp_path, service)

    response = client.post(IMPORT_PATH.format(save_id="save-1", tactic_index=0), headers=auth(settings))

    assert response.status_code == 201
    assert response.json() == {"draft": DRAFT}
    assert service.calls == [("import", "save-1", 0, None)]


def test_save_tactics_http_import_passes_requested_name(tmp_path: Path):
    service = FakeService(draft=DRAFT)
    client, settings = make_client(tmp_path, service)

    response = client.post(
        IMPORT_PATH.format(save_id="save-1", tactic_index=0),
        json={"name": "我的战术"},
        headers=auth(settings),
    )

    assert response.status_code == 201
    assert service.calls == [("import", "save-1", 0, "我的战术")]


def test_save_tactics_http_import_accepts_eighty_character_name(tmp_path: Path):
    service = FakeService(draft=DRAFT)
    client, settings = make_client(tmp_path, service)

    response = client.post(
        IMPORT_PATH.format(save_id="save-1", tactic_index=0),
        json={"name": "x" * 80},
        headers=auth(settings),
    )

    assert response.status_code == 201
    assert service.calls == [("import", "save-1", 0, "x" * 80)]


def test_save_tactics_http_import_rejects_too_long_name(tmp_path: Path):
    service = FakeService(draft=DRAFT)
    client, settings = make_client(tmp_path, service)

    response = client.post(
        IMPORT_PATH.format(save_id="save-1", tactic_index=0),
        json={"name": "x" * 81},
        headers=auth(settings),
    )

    error = assert_error(response, 400, "validation_failed")
    assert error["retriable"] is False
    assert service.calls == []


def test_save_tactics_http_import_rejects_blank_name(tmp_path: Path):
    service = FakeService(draft=DRAFT)
    client, settings = make_client(tmp_path, service)

    response = client.post(
        IMPORT_PATH.format(save_id="save-1", tactic_index=0),
        json={"name": ""},
        headers=auth(settings),
    )

    assert_error(response, 400, "validation_failed")
    assert service.calls == []


def test_save_tactics_http_import_trims_requested_name(tmp_path: Path):
    service = FakeService(draft=DRAFT)
    client, settings = make_client(tmp_path, service)

    response = client.post(
        IMPORT_PATH.format(save_id="save-1", tactic_index=0),
        json={"name": "  我的战术  "},
        headers=auth(settings),
    )

    assert response.status_code == 201
    assert service.calls == [("import", "save-1", 0, "我的战术")]


def test_save_tactics_http_import_rejects_whitespace_name(tmp_path: Path):
    service = FakeService(draft=DRAFT)
    client, settings = make_client(tmp_path, service)

    response = client.post(
        IMPORT_PATH.format(save_id="save-1", tactic_index=0),
        json={"name": "   "},
        headers=auth(settings),
    )

    error = assert_error(response, 400, "validation_failed")
    assert error["message"] == "战术名称不能为空白"
    assert service.calls == []


def test_save_tactics_http_import_rejects_unknown_body_field(tmp_path: Path):
    service = FakeService(draft=DRAFT)
    client, settings = make_client(tmp_path, service)

    response = client.post(
        IMPORT_PATH.format(save_id="save-1", tactic_index=0),
        json={"name": "Tactic", "source": "save"},
        headers=auth(settings),
    )

    error = assert_error(response, 400, "validation_failed")
    assert error["details"] is None
    assert service.calls == []


def test_save_tactics_http_maps_missing_tactic_to_not_found(tmp_path: Path):
    service = FakeService(error=ValueError(TACTIC_MISSING_ERROR))
    client, settings = make_client(tmp_path, service)

    error = assert_error(
        client.post(IMPORT_PATH.format(save_id="save-1", tactic_index=3), headers=auth(settings)),
        404,
        "not_found",
    )

    assert error["message"] == TACTIC_MISSING_ERROR


def test_save_tactics_http_reports_non_first_team_tactic(tmp_path: Path):
    service = FakeService(error=ValueError(TACTIC_TEAM_ERROR))
    client, settings = make_client(tmp_path, service)

    error = assert_error(
        client.post(IMPORT_PATH.format(save_id="save-1", tactic_index=1), headers=auth(settings)),
        400,
        "validation_failed",
    )

    assert error["message"] == TACTIC_TEAM_ERROR
    assert error["retriable"] is False


def test_save_tactics_http_reports_missing_save_file(tmp_path: Path):
    service = FakeService(error=ValueError(SAVE_MISSING_ERROR))
    client, settings = make_client(tmp_path, service)

    error = assert_error(
        client.post(IMPORT_PATH.format(save_id="save-1", tactic_index=0), headers=auth(settings)),
        400,
        "validation_failed",
    )

    assert error["message"] == SAVE_MISSING_ERROR


def test_save_tactics_http_reports_unconfigured_engine(tmp_path: Path):
    service = FakeService(error=TacticFileError(UNCONFIGURED_ERROR))
    client, settings = make_client(tmp_path, service)

    response = client.post(IMPORT_PATH.format(save_id="save-1", tactic_index=0), headers=auth(settings))

    error = assert_error(response, 503, "engine_unavailable")
    assert error["message"] == ENGINE_UNAVAILABLE_MESSAGE
    assert error["details"] is None
    assert error["retriable"] is True
    assert str(tmp_path) not in response.text


def test_save_tactics_http_rejects_negative_index(tmp_path: Path):
    service = FakeService(items=ITEMS)
    client, settings = make_client(tmp_path, service)

    response = client.post(IMPORT_PATH.format(save_id="save-1", tactic_index=-1), headers=auth(settings))

    assert_error(response, 400, "validation_failed")
    assert service.calls == []


def test_save_tactics_http_openapi_documents_paths(tmp_path: Path):
    client, _ = make_client(tmp_path)

    document = client.get("/api/openapi.json").json()

    assert LIST_PATH in document["paths"]
    assert IMPORT_PATH in document["paths"]
    schemas = document["components"]["schemas"]
    for name in (
        "SaveTacticImportInput",
        "SaveTacticOutput",
        "SaveTacticListOutput",
        "SaveTacticImportOutput",
    ):
        assert name in schemas
    operation = document["paths"][IMPORT_PATH]["post"]
    assert "required" not in operation["requestBody"]
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body["anyOf"] == [
        {"$ref": "#/components/schemas/SaveTacticImportInput"},
        {"type": "null"},
    ]
    for status in ("400", "401", "404", "503"):
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorEnvelope"
        }
    model = schemas["SaveTacticImportInput"]
    assert model["additionalProperties"] is False
    assert set(model["properties"]) == {"name"}


def test_save_tactics_http_round_trip_with_real_services(tmp_path: Path):
    client, settings = make_integration_client(tmp_path)
    source = tmp_path / "save.fm"
    source.write_bytes(b"save-bytes")
    save = create_save(client, settings, source)

    listed = client.get(LIST_PATH.format(save_id=save["id"]), headers=auth(settings))
    assert listed.status_code == 200
    assert listed.json()["items"] == [
        {
            "index": 0,
            "name": "Direct",
            "style": "Control",
            "mentality": 5,
            "club_uid": 7,
            "club_name": "Sev",
            "team_slot": 0,
            "importable": True,
        }
    ]

    imported = client.post(IMPORT_PATH.format(save_id=save["id"], tactic_index=0), headers=auth(settings))
    assert imported.status_code == 201
    draft = imported.json()["draft"]
    assert draft["name"] == "Direct"
    assert draft["source"] == {"kind": "save_tactic", "save_id": save["id"], "tactic_index": 0}

    fetched = client.get(f"/api/drafts/{draft['id']}", headers=auth(settings))
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Direct"


def test_save_tactics_http_import_uses_requested_name_end_to_end(tmp_path: Path):
    client, settings = make_integration_client(tmp_path)
    source = tmp_path / "save.fm"
    source.write_bytes(b"save-bytes")
    save = create_save(client, settings, source)

    response = client.post(
        IMPORT_PATH.format(save_id=save["id"], tactic_index=0),
        json={"name": "  自定义战术  "},
        headers=auth(settings),
    )

    assert response.status_code == 201, response.text
    draft = response.json()["draft"]
    assert draft["name"] == "自定义战术"
    assert draft["source"] == {"kind": "save_tactic", "save_id": save["id"], "tactic_index": 0}


def test_save_tactics_http_without_engine_lists_but_blocks_import(tmp_path: Path):
    client, settings = make_integration_client(tmp_path, engine=False)
    source = tmp_path / "save.fm"
    source.write_bytes(b"save-bytes")
    save = create_save(client, settings, source)

    listed = client.get(LIST_PATH.format(save_id=save["id"]), headers=auth(settings))
    assert listed.status_code == 200
    assert listed.json()["items"][0]["importable"] is False

    response = client.post(IMPORT_PATH.format(save_id=save["id"], tactic_index=0), headers=auth(settings))
    error = assert_error(response, 503, "engine_unavailable")
    assert error["message"] == ENGINE_UNAVAILABLE_MESSAGE


def test_save_tactics_http_reports_missing_save_file_integration(tmp_path: Path):
    client, settings = make_integration_client(tmp_path)
    save = create_save(client, settings, tmp_path / "missing.fm")

    response = client.get(LIST_PATH.format(save_id=save["id"]), headers=auth(settings))

    error = assert_error(response, 400, "validation_failed")
    assert error["message"] == SAVE_MISSING_ERROR
