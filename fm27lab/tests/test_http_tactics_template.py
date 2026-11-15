"""HTTP contract tests for the tactics template endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.adapters.engine_native.scenario_assets import load_scenario_assets
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import create_app
from fm27lab.interfaces.http.routes import tactics as tactics_routes
from fm27lab.tests.test_scenario_assets import write_engine_root
from fm27lab.tests.test_tactics_template import write_catalog_with_rules

ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
TEMPLATE_PATH = "/api/tactics/template"


def make_app(tmp_path: Path, engine_root: Path | None) -> tuple[TestClient, Settings]:
    settings = Settings.create(
        data_dir=tmp_path / "data",
        token="c" * 64,
        engine_root=engine_root,
        dev=True,
    )
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    return TestClient(create_app(settings, database)), settings


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def make_engine(tmp_path: Path) -> Path:
    root = write_engine_root(tmp_path / "engine")
    write_catalog_with_rules(root)
    return root


def assert_unavailable(response) -> None:
    assert response.status_code == 503
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == tactics_routes.ENGINE_UNAVAILABLE_CODE
    assert error["message"] == tactics_routes.ENGINE_UNAVAILABLE_MESSAGE
    assert error["details"] is None
    assert error["retriable"] is True


def test_tactics_template_requires_auth(tmp_path: Path):
    client, _ = make_app(tmp_path, make_engine(tmp_path))
    response = client.get(TEMPLATE_PATH)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"


def test_tactics_template_returns_two_full_rosters(tmp_path: Path):
    client, settings = make_app(tmp_path, make_engine(tmp_path))
    response = client.get(TEMPLATE_PATH, headers=auth(settings))
    assert response.status_code == 200, response.text
    scenario = response.json()["scenario"]
    assert scenario["schema"] == 3
    assert len(scenario["teams"]) == 2
    for team in scenario["teams"]:
        assert team["roster_size"] == 23
        assert len(team["players"]) == 23
        assert team["lineup"] == list(range(11))
        assert len({player["source_uid"] for player in team["players"]}) == 23
        duties = [cell["duty"] for phase in team["phases"] for cell in phase]
        assert all(duty.isascii() and duty.isdigit() for duty in duties)
        assert team["phases"][1][0]["role"] == "GK_ROLE_1"


def test_tactics_template_scenario_creates_draft(tmp_path: Path):
    client, settings = make_app(tmp_path, make_engine(tmp_path))
    headers = auth(settings)
    template = client.get(TEMPLATE_PATH, headers=headers).json()["scenario"]
    response = client.post(
        "/api/drafts",
        headers=headers,
        json={"name": "模板战术", "scenario": template},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "模板战术"
    assert created["scenario"]["teams"][0]["roster_size"] == 23
    detail = client.get(f"/api/drafts/{created['id']}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["scenario"]["teams"][0]["players"]) == 23


def test_tactics_template_without_engine_root_is_unavailable(tmp_path: Path):
    client, settings = make_app(tmp_path, None)
    response = client.get(TEMPLATE_PATH, headers=auth(settings))
    assert_unavailable(response)
    assert str(tmp_path) not in response.text


def test_tactics_template_with_broken_engine_root_is_unavailable(tmp_path: Path):
    broken = tmp_path / "empty-engine"
    broken.mkdir()
    client, settings = make_app(tmp_path, broken)
    response = client.get(TEMPLATE_PATH, headers=auth(settings))
    assert_unavailable(response)
    assert str(broken) not in response.text


def test_tactics_template_loads_assets_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client, settings = make_app(tmp_path, make_engine(tmp_path))
    headers = auth(settings)
    calls = {"count": 0}
    original = tactics_routes.load_scenario_assets

    def counting(engine_root: Path):
        calls["count"] += 1
        return original(engine_root)

    monkeypatch.setattr(tactics_routes, "load_scenario_assets", counting)
    assert client.get(TEMPLATE_PATH, headers=headers).status_code == 200
    assert client.get(TEMPLATE_PATH, headers=headers).status_code == 200
    assert calls["count"] == 1


def test_tactics_template_uses_injected_assets(tmp_path: Path):
    client, settings = make_app(tmp_path, None)
    client.app.state.tactics_template_assets = load_scenario_assets(
        write_engine_root(tmp_path / "engine")
    )
    response = client.get(TEMPLATE_PATH, headers=auth(settings))
    assert response.status_code == 200, response.text
    assert len(response.json()["scenario"]["teams"]) == 2
