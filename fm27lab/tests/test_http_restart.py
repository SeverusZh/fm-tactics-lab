from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import create_app

ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


def make_app(tmp_path: Path) -> tuple[TestClient, Settings, list[bool]]:
    settings = Settings.create(data_dir=tmp_path, token="c" * 64, dev=True)
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    stopped: list[bool] = []
    app = create_app(settings, database, shutdown=lambda: stopped.append(True))
    return TestClient(app), settings, stopped


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def test_restart_returns_202_and_triggers_shutdown(tmp_path: Path):
    client, settings, stopped = make_app(tmp_path)
    response = client.post("/api/system/restart", headers=auth(settings))
    assert response.status_code == 202
    assert response.json() == {"status": "restarting"}
    assert stopped == [True]


def test_restart_requires_auth(tmp_path: Path):
    client, _, stopped = make_app(tmp_path)
    response = client.post("/api/system/restart")
    assert response.status_code == 401
    assert set(response.json()["error"]) == ERROR_FIELDS
    assert stopped == []


def test_restart_is_documented_in_openapi(tmp_path: Path):
    client, _, _ = make_app(tmp_path)
    operation = client.get("/api/openapi.json").json()["paths"]["/api/system/restart"]["post"]
    assert "422" not in operation
    assert operation["responses"]["401"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
