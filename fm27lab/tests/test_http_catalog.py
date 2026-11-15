from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.application.catalog import CatalogService
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import create_app
from fm27lab.tests.test_http_health import make_app

ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
TRIMMED_SECTIONS = (
    "positions",
    "roles",
    "team_instructions",
    "mentalities",
    "attributes",
    "player_instructions",
)
CATALOG_FIXTURE: dict[str, Any] = {
    "schema_version": 3,
    "positions": [{"id": "GK", "mask": 1, "x": 50, "y": 92}],
    "roles": [{"id": "GK_D", "label": "门将", "phase": 0, "flags": "0"}],
    "team_instructions": [{"id": 1, "label": "宽度", "options": [{"id": 1, "native_bit": 0}]}],
    "mentalities": [{"id": 1, "label": "极度防守"}],
    "attributes": [{"index": 0, "label": "速度"}],
    "player_instructions": [{"id": 1, "label": "贴身盯防"}],
    "policy_versions": ["1a080000"],
}


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def assert_error(response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == code
    return error


def write_data_catalog(settings: Settings, payload: dict[str, Any]) -> Path:
    path = settings.data_dir / "catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def build_app(tmp_path: Path, *, engine_root: Path | None = None, catalog_service: Any = None):
    settings = Settings.create(
        data_dir=tmp_path / "data",
        token="c" * 64,
        engine_root=engine_root,
        dev=True,
    )
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    app = create_app(settings, database, shutdown=lambda: None, catalog_service=catalog_service)
    return app, settings


class _StubCatalogService:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value
        self.calls = 0

    def snapshot(self) -> dict[str, Any]:
        self.calls += 1
        return self.value


def test_catalog_http_returns_snapshot_when_available(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    write_data_catalog(settings, CATALOG_FIXTURE)
    response = TestClient(app).get("/api/catalog", headers=auth(settings))
    assert response.status_code == 200, response.text
    expected_catalog = {section: CATALOG_FIXTURE[section] for section in TRIMMED_SECTIONS}
    assert response.json() == {"available": True, "catalog": expected_catalog}


def test_catalog_http_reports_unavailable_without_catalog(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    response = TestClient(app).get("/api/catalog", headers=auth(settings))
    assert response.status_code == 200, response.text
    assert response.json() == {"available": False, "catalog": None}


def test_catalog_http_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    assert_error(client.get("/api/catalog"), 401, "unauthorized")
    assert_error(
        client.get("/api/catalog", headers={"Authorization": "Bearer wrong"}),
        401,
        "unauthorized",
    )
    response = client.get("/api/catalog", headers={"Authorization": f"bearer {settings.token}"})
    assert response.status_code == 200


def test_catalog_http_reads_engine_workspace(tmp_path: Path):
    engine_root = tmp_path / "engine"
    native = engine_root / "fm27_native" / "catalog.json"
    native.parent.mkdir(parents=True)
    native.write_text(json.dumps(CATALOG_FIXTURE, ensure_ascii=False), encoding="utf-8")
    app, settings = build_app(tmp_path, engine_root=engine_root)
    response = TestClient(app).get("/api/catalog", headers=auth(settings))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is True
    assert body["catalog"]["positions"] == CATALOG_FIXTURE["positions"]


def test_catalog_http_uses_injected_service(tmp_path: Path):
    stub = _StubCatalogService(
        {
            "available": True,
            "catalog": {
                "positions": [{"id": "STUB"}],
                "roles": [],
                "team_instructions": [],
                "mentalities": [],
            },
        }
    )
    app, settings = build_app(tmp_path, catalog_service=stub)
    assert app.state.catalog_service is stub
    response = TestClient(app).get("/api/catalog", headers=auth(settings))
    assert response.status_code == 200, response.text
    assert response.json() == stub.value
    assert stub.calls == 1


def test_catalog_http_builds_default_service_from_settings(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    assert isinstance(app.state.catalog_service, CatalogService)


def test_catalog_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    assert "/api/catalog" in document["paths"]
    operation = document["paths"]["/api/catalog"]["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "422" not in operation["responses"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("CatalogSnapshotOutput")
    error_schema = operation["responses"]["401"]["content"]["application/json"]["schema"]
    assert error_schema["$ref"].endswith("ErrorEnvelope")


def test_catalog_http_keeps_existing_routes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    paths = client.get("/api/openapi.json").json()["paths"]
    for path in (
        "/api/health",
        "/api/version",
        "/api/pools",
        "/api/drafts",
        "/api/jobs",
        "/api/saves",
        "/api/artifacts",
        "/api/settings",
        "/api/experiments",
        "/api/events",
        "/api/catalog",
    ):
        assert path in paths, path
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/pools", headers=auth(settings)).status_code == 200
    assert client.get("/api/catalog", headers=auth(settings)).status_code == 200
