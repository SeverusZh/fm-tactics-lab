from __future__ import annotations

from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository
from fm27lab.application.engine_config import (
    ENGINE_KEY,
    GAME_KEY,
    EngineConfig,
    EngineConfigService,
    validate_engine_root,
    validate_game_root,
)


def build_engine_root(path: Path) -> Path:
    native = path / "fm27_native"
    native.mkdir(parents=True)
    (native / "FM27Simulator.exe").write_bytes(b"")
    (native / "catalog.json").write_text("{}", encoding="utf-8")
    (native / "editor_manual_default.json").write_text("{}", encoding="utf-8")
    (native / "editor_advanced_snapshot.json").write_text("{}", encoding="utf-8")
    (native / "editor_setpieces_default.json").write_text("{}", encoding="utf-8")
    research = path / "fm27_research"
    research.mkdir()
    (research / "setpiece_enum_catalog.json").write_text("{}", encoding="utf-8")
    return path


def build_game_root(path: Path) -> Path:
    plugins = path / "fm_Data" / "Plugins" / "x86_64"
    plugins.mkdir(parents=True)
    (plugins / "game_plugin.dll").write_bytes(b"")
    return path


def build_service(
    tmp_path: Path,
    environment: dict[str, str] | None = None,
    runtime: EngineConfig | None = None,
) -> tuple[EngineConfigService, SettingsRepository]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    database = Database(data_dir / "fm27lab.db")
    database.initialize()
    repository = SettingsRepository(database)
    service = EngineConfigService(
        repository,
        data_dir,
        environment={} if environment is None else environment,
        runtime=runtime,
    )
    return service, repository


def test_validate_engine_root_accepts_complete_workspace(tmp_path: Path):
    root = build_engine_root(tmp_path / "engine")
    assert validate_engine_root(str(root)) == root.resolve()


def test_validate_engine_root_accepts_catalog_at_workspace_root(tmp_path: Path):
    root = build_engine_root(tmp_path / "engine")
    (root / "fm27_native" / "catalog.json").unlink()
    (root / "catalog.json").write_text("{}", encoding="utf-8")
    assert validate_engine_root(root) == root.resolve()


def test_validate_engine_root_names_missing_files(tmp_path: Path):
    root = tmp_path / "engine"
    root.mkdir()
    with pytest.raises(ValueError) as caught:
        validate_engine_root(root)
    message = str(caught.value)
    assert message.startswith("引擎目录缺少：")
    assert set(message.removeprefix("引擎目录缺少：").split("、")) == {
        "fm27_native/FM27Simulator.exe",
        "catalog.json",
        "fm27_research/setpiece_enum_catalog.json",
        "fm27_native/editor_manual_default.json",
        "fm27_native/editor_advanced_snapshot.json",
        "fm27_native/editor_setpieces_default.json",
    }


def test_validate_engine_root_requires_editor_snapshots(tmp_path: Path):
    root = build_engine_root(tmp_path / "engine")
    (root / "fm27_native" / "editor_advanced_snapshot.json").unlink()
    (root / "fm27_native" / "editor_setpieces_default.json").unlink()
    with pytest.raises(ValueError) as caught:
        validate_engine_root(root)
    message = str(caught.value)
    assert "fm27_native/editor_advanced_snapshot.json" in message
    assert "fm27_native/editor_setpieces_default.json" in message
    assert "FM27Simulator.exe" not in message


def test_validate_engine_root_rejects_relative_empty_and_missing_directory(tmp_path: Path):
    with pytest.raises(ValueError) as relative:
        validate_engine_root("engine")
    assert "必须是绝对路径" in str(relative.value)
    with pytest.raises(ValueError) as empty:
        validate_engine_root("")
    assert "不能为空" in str(empty.value)
    with pytest.raises(ValueError) as absent:
        validate_engine_root(tmp_path / "engine")
    assert "不存在或不是目录" in str(absent.value)


def test_validate_game_root_accepts_plugin_and_names_missing_file(tmp_path: Path):
    root = build_game_root(tmp_path / "game")
    assert validate_game_root(root) == root.resolve()
    broken = tmp_path / "broken-game"
    broken.mkdir()
    with pytest.raises(ValueError) as caught:
        validate_game_root(broken)
    message = str(caught.value)
    assert message.startswith("游戏目录缺少：")
    assert "fm_Data/Plugins/x86_64/game_plugin.dll" in message
    with pytest.raises(ValueError) as relative:
        validate_game_root("game")
    assert "必须是绝对路径" in str(relative.value)


def test_resolve_prefers_explicit_roots(tmp_path: Path):
    explicit_engine = build_engine_root(tmp_path / "explicit-engine")
    explicit_game = build_game_root(tmp_path / "explicit-game")
    stored_engine = build_engine_root(tmp_path / "stored-engine")
    environment = {
        "FM27_ENGINE_ROOT": str(build_engine_root(tmp_path / "env-engine")),
        "FM27_GAME_ROOT": str(build_game_root(tmp_path / "env-game")),
    }
    service, repository = build_service(tmp_path, environment=environment)
    repository.set(ENGINE_KEY, str(stored_engine))
    resolved = service.resolve(engine_root=explicit_engine, game_root=explicit_game)
    assert resolved.engine_root == explicit_engine.resolve()
    assert resolved.game_root == explicit_game.resolve()


def test_resolve_prefers_stored_roots_over_environment(tmp_path: Path):
    stored_engine = build_engine_root(tmp_path / "stored-engine")
    stored_game = build_game_root(tmp_path / "stored-game")
    environment = {
        "FM27_ENGINE_ROOT": str(build_engine_root(tmp_path / "env-engine")),
        "FM27_GAME_ROOT": str(build_game_root(tmp_path / "env-game")),
    }
    service, repository = build_service(tmp_path, environment=environment)
    repository.set(ENGINE_KEY, str(stored_engine))
    repository.set(GAME_KEY, str(stored_game))
    resolved = service.resolve()
    assert resolved.engine_root == stored_engine.resolve()
    assert resolved.game_root == stored_game.resolve()


def test_resolve_prefers_environment_over_default_engine_directory(tmp_path: Path):
    env_engine = build_engine_root(tmp_path / "env-engine")
    build_engine_root(tmp_path / "data" / "engine")
    service, _ = build_service(tmp_path, environment={"FM27_ENGINE_ROOT": str(env_engine)})
    resolved = service.resolve()
    assert resolved.engine_root == env_engine.resolve()
    assert resolved.game_root is None


def test_resolve_falls_back_to_default_engine_directory(tmp_path: Path):
    default_engine = build_engine_root(tmp_path / "data" / "engine")
    service, _ = build_service(tmp_path)
    resolved = service.resolve()
    assert resolved.engine_root == default_engine.resolve()


def test_resolve_skips_candidates_that_are_not_directories(tmp_path: Path):
    env_engine = build_engine_root(tmp_path / "env-engine")
    service, repository = build_service(tmp_path, environment={"FM27_ENGINE_ROOT": str(env_engine)})
    repository.set(ENGINE_KEY, str(tmp_path / "missing-engine"))
    resolved = service.resolve(engine_root=tmp_path / "missing-explicit")
    assert resolved.engine_root == env_engine.resolve()


def test_resolve_returns_none_when_no_candidate_exists(tmp_path: Path):
    service, _ = build_service(tmp_path)
    resolved = service.resolve()
    assert resolved.engine_root is None
    assert resolved.game_root is None


def test_resolve_uses_default_data_directory_engine(tmp_path: Path):
    build_engine_root(tmp_path / "data" / "engine")
    service, _ = build_service(tmp_path)
    assert service.resolve().engine_root == (tmp_path / "data" / "engine").resolve()


def test_status_reports_availability_and_missing_items(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    service, _ = build_service(tmp_path, runtime=EngineConfig(engine, game))
    status = service.status()
    assert status.engine_root == engine.resolve() or status.engine_root == engine
    assert status.engine_available is True
    assert status.game_available is True
    assert status.engine_missing == ()
    assert status.game_missing == ()


def test_status_names_missing_items_for_broken_roots(tmp_path: Path):
    engine = tmp_path / "engine"
    engine.mkdir()
    game = tmp_path / "game"
    game.mkdir()
    service, _ = build_service(tmp_path, runtime=EngineConfig(engine, game))
    status = service.status()
    assert status.engine_available is False
    assert status.game_available is False
    assert "fm27_native/FM27Simulator.exe" in status.engine_missing
    assert status.game_missing == ("fm_Data/Plugins/x86_64/game_plugin.dll",)


def test_status_without_roots_reports_unavailable(tmp_path: Path):
    service, _ = build_service(tmp_path)
    status = service.status()
    assert status.engine_root is None
    assert status.game_root is None
    assert status.engine_available is False
    assert status.game_available is False
    assert status.engine_missing == ()
    assert status.game_missing == ()


def test_select_validates_and_persists_both_roots(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    service, repository = build_service(tmp_path)
    status = service.select(engine_root=engine, game_root=game)
    assert status.engine_available is True
    assert status.game_available is True
    assert repository.get(ENGINE_KEY) == str(engine.resolve())
    assert repository.get(GAME_KEY) == str(game.resolve())


def test_select_merges_unspecified_root_with_runtime(tmp_path: Path):
    runtime_game = build_game_root(tmp_path / "runtime-game")
    engine = build_engine_root(tmp_path / "engine")
    service, repository = build_service(tmp_path, runtime=EngineConfig(None, runtime_game))
    status = service.select(engine_root=str(engine))
    assert status.engine_root == engine.resolve()
    assert status.game_root == runtime_game
    assert repository.get(ENGINE_KEY) == str(engine.resolve())
    assert repository.get(GAME_KEY) is None


def test_select_requires_at_least_one_root(tmp_path: Path):
    service, _ = build_service(tmp_path)
    with pytest.raises(ValueError) as caught:
        service.select()
    assert "至少需要提供引擎目录或游戏目录" in str(caught.value)


def test_select_rejects_invalid_root_without_persisting(tmp_path: Path):
    broken = tmp_path / "broken-engine"
    broken.mkdir()
    service, repository = build_service(tmp_path)
    with pytest.raises(ValueError) as caught:
        service.select(engine_root=broken)
    assert "引擎目录缺少：" in str(caught.value)
    assert repository.get(ENGINE_KEY) is None
