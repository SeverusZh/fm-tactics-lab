"""Sidecar startup settings resolution tests."""

from __future__ import annotations

from pathlib import Path

import fm27lab.sidecar as sidecar
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository
from fm27lab.config import Settings


def build_settings(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings.create(data_dir=tmp_path / "data", token="c" * 64)
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    return settings, database


def test_resolve_settings_prefers_explicit_roots(tmp_path: Path):
    settings, database = build_settings(tmp_path)
    engine = tmp_path / "explicit-engine"
    engine.mkdir()
    game = tmp_path / "explicit-game"
    game.mkdir()
    resolved = sidecar.resolve_settings(settings, database, engine_root=engine, game_root=game)
    assert resolved.engine_root == engine.resolve()
    assert resolved.game_root == game.resolve()
    assert resolved.token == settings.token
    assert resolved.data_dir == settings.data_dir


def test_resolve_settings_uses_persisted_roots(tmp_path: Path):
    settings, database = build_settings(tmp_path)
    engine = tmp_path / "stored-engine"
    engine.mkdir()
    game = tmp_path / "stored-game"
    game.mkdir()
    repository = SettingsRepository(database)
    repository.set("engine.root", str(engine))
    repository.set("game.root", str(game))
    resolved = sidecar.resolve_settings(settings, database)
    assert resolved.engine_root == engine.resolve()
    assert resolved.game_root == game.resolve()


def test_resolve_settings_falls_back_to_the_environment(tmp_path: Path, monkeypatch):
    settings, database = build_settings(tmp_path)
    engine = tmp_path / "env-engine"
    engine.mkdir()
    game = tmp_path / "env-game"
    game.mkdir()
    monkeypatch.setenv("FM27_ENGINE_ROOT", str(engine))
    monkeypatch.setenv("FM27_GAME_ROOT", str(game))
    resolved = sidecar.resolve_settings(settings, database)
    assert resolved.engine_root == engine.resolve()
    assert resolved.game_root == game.resolve()


class FakeServer:
    def __init__(self, config) -> None:
        self.config = config
        self.should_exit = False

    def run(self, sockets) -> None:
        return None


def test_run_resolves_roots_before_building_the_app(tmp_path: Path, monkeypatch):
    settings, _database = build_settings(tmp_path)
    engine = tmp_path / "engine-workspace"
    engine.mkdir()
    game = tmp_path / "game-install"
    game.mkdir()
    captured = {}
    original_create_app = sidecar.create_app

    def capture(settings_arg, database, **kwargs):
        captured["settings"] = settings_arg
        return original_create_app(settings_arg, database, **kwargs)

    monkeypatch.setattr(sidecar, "create_app", capture)
    monkeypatch.setattr(sidecar.uvicorn, "Server", FakeServer)
    assert sidecar.run(settings, engine_root=engine, game_root=game) == 0
    assert captured["settings"].engine_root == engine.resolve()
    assert captured["settings"].game_root == game.resolve()
    assert not settings.endpoint_path.exists()
