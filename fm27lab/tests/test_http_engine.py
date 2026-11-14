from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository
from fm27lab.application.engine_config import ENGINE_KEY, GAME_KEY
from fm27lab.application.engine_diagnostics import EngineDiagnoseError, EngineDiagnosis
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import create_app
from fm27lab.interfaces.http.routes import engine as engine_routes

ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


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


def make_engine_app(
    tmp_path: Path,
    engine_root: Path | None = None,
    game_root: Path | None = None,
) -> tuple[TestClient, Settings, Database]:
    settings = Settings.create(
        data_dir=tmp_path,
        token="c" * 64,
        engine_root=engine_root,
        game_root=game_root,
        dev=True,
    )
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    return TestClient(create_app(settings, database)), settings, database


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def test_engine_status_requires_auth(tmp_path: Path):
    client, settings, _ = make_engine_app(tmp_path)
    response = client.get("/api/engine")
    assert response.status_code == 401
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_engine_status_reports_configured_roots(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    client, settings, _ = make_engine_app(tmp_path, engine, game)
    response = client.get("/api/engine", headers=auth(settings))
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine_root"] == str(engine.resolve())
    assert payload["game_root"] == str(game.resolve())
    assert payload["engine"] == {"available": True, "missing": []}
    assert payload["game"] == {"available": True, "missing": []}


def test_engine_status_reports_missing_configuration(tmp_path: Path):
    client, settings, _ = make_engine_app(tmp_path)
    response = client.get("/api/engine", headers=auth(settings))
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine_root"] is None
    assert payload["game_root"] is None
    assert payload["engine"] == {"available": False, "missing": []}
    assert payload["game"] == {"available": False, "missing": []}


def test_engine_status_lists_missing_files(tmp_path: Path):
    engine = tmp_path / "engine"
    engine.mkdir()
    game = tmp_path / "game"
    game.mkdir()
    client, settings, _ = make_engine_app(tmp_path, engine, game)
    payload = client.get("/api/engine", headers=auth(settings)).json()
    assert "fm27_native/FM27Simulator.exe" in payload["engine"]["missing"]
    assert payload["game"]["missing"] == ["fm_Data/Plugins/x86_64/game_plugin.dll"]


def test_engine_select_persists_both_roots(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    client, settings, database = make_engine_app(tmp_path)
    response = client.post(
        "/api/engine/select",
        json={"engine_root": str(engine), "game_root": str(game)},
        headers=auth(settings),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine_root"] == str(engine.resolve())
    assert payload["game_root"] == str(game.resolve())
    assert payload["engine"]["available"] is True
    assert payload["game"]["available"] is True
    repository = SettingsRepository(database)
    assert repository.get(ENGINE_KEY) == str(engine.resolve())
    assert repository.get(GAME_KEY) == str(game.resolve())


def test_engine_select_merges_runtime_root_and_keeps_get_unchanged(tmp_path: Path):
    runtime_engine = build_engine_root(tmp_path / "runtime-engine")
    runtime_game = build_game_root(tmp_path / "runtime-game")
    selected = build_engine_root(tmp_path / "selected-engine")
    client, settings, database = make_engine_app(tmp_path, runtime_engine, runtime_game)
    response = client.post(
        "/api/engine/select",
        json={"engine_root": str(selected)},
        headers=auth(settings),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine_root"] == str(selected.resolve())
    assert payload["game_root"] == str(runtime_game.resolve())
    assert SettingsRepository(database).get(GAME_KEY) is None
    current = client.get("/api/engine", headers=auth(settings)).json()
    assert current["engine_root"] == str(runtime_engine.resolve())


def test_engine_select_requires_a_root(tmp_path: Path):
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/select", json={}, headers=auth(settings))
    assert response.status_code == 400
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "validation_failed"
    assert "至少需要提供引擎目录或游戏目录" in error["message"]
    assert error["retriable"] is False


@pytest.mark.parametrize(
    ("payload_name", "value", "fragment"),
    [
        ("engine_root", "engine", "必须是绝对路径"),
        ("engine_root", "/definitely/missing/engine", "不存在或不是目录"),
        ("game_root", "game", "必须是绝对路径"),
        ("game_root", "/definitely/missing/game", "不存在或不是目录"),
    ],
)
def test_engine_select_rejects_invalid_roots(tmp_path: Path, payload_name: str, value: str, fragment: str):
    client, settings, database = make_engine_app(tmp_path)
    response = client.post("/api/engine/select", json={payload_name: value}, headers=auth(settings))
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert fragment in error["message"]
    assert SettingsRepository(database).get(ENGINE_KEY) is None
    assert SettingsRepository(database).get(GAME_KEY) is None


def test_engine_select_names_missing_engine_files(tmp_path: Path):
    engine = tmp_path / "engine"
    engine.mkdir()
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/select", json={"engine_root": str(engine)}, headers=auth(settings))
    assert response.status_code == 400
    assert "引擎目录缺少：" in response.json()["error"]["message"]


def test_engine_status_reports_missing_editor_advanced_snapshot(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    (engine / "fm27_native" / "editor_advanced_snapshot.json").unlink()
    game = build_game_root(tmp_path / "game")
    client, settings, _ = make_engine_app(tmp_path, engine, game)
    payload = client.get("/api/engine", headers=auth(settings)).json()
    assert payload["engine"]["available"] is False
    assert payload["engine"]["missing"] == ["fm27_native/editor_advanced_snapshot.json"]
    assert payload["game"]["available"] is True


def test_engine_select_names_missing_editor_setpieces_snapshot(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    (engine / "fm27_native" / "editor_setpieces_default.json").unlink()
    client, settings, database = make_engine_app(tmp_path)
    response = client.post("/api/engine/select", json={"engine_root": str(engine)}, headers=auth(settings))
    assert response.status_code == 400
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "validation_failed"
    assert error["message"].startswith("引擎目录缺少：")
    assert "fm27_native/editor_setpieces_default.json" in error["message"]
    assert SettingsRepository(database).get(ENGINE_KEY) is None


def test_engine_import_maps_missing_editor_advanced_snapshot_to_400(tmp_path: Path):
    source = build_import_source(tmp_path / "install")
    workspace = source / "releases" / "release-1" / "engine"
    (workspace / "fm27_native" / "editor_advanced_snapshot.json").unlink()
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/import", json={"source_path": str(source)}, headers=auth(settings))
    assert response.status_code == 400
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "engine_import_failed"
    assert "fm27_native/editor_advanced_snapshot.json" in error["message"]
    assert error["retriable"] is False


def test_engine_select_rejects_non_string_root(tmp_path: Path):
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/select", json={"engine_root": 5}, headers=auth(settings))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"


def test_engine_select_requires_auth(tmp_path: Path):
    client, _, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/select", json={"engine_root": "/tmp/engine"})
    assert response.status_code == 401
    assert set(response.json()["error"]) == ERROR_FIELDS


def test_engine_diagnose_returns_diagnosis(tmp_path: Path, monkeypatch):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    client, settings, _ = make_engine_app(tmp_path, engine, game)
    calls: list[tuple[Path, Path]] = []

    def fake(engine_root: Path, game_root: Path) -> EngineDiagnosis:
        calls.append((engine_root, game_root))
        return EngineDiagnosis(True, False, "镜像哈希匹配", "2.1.0", "a" * 64)

    monkeypatch.setattr(engine_routes, "diagnose_engine", fake)
    response = client.post("/api/engine/diagnose", headers=auth(settings))
    assert response.status_code == 200
    assert response.json() == {
        "compatible": True,
        "trial_allowed": False,
        "reason": "镜像哈希匹配",
        "adapter_version": "2.1.0",
        "image_sha256": "a" * 64,
    }
    assert calls == [(engine.resolve(), game.resolve())]


def test_engine_diagnose_requires_configured_roots(tmp_path: Path, monkeypatch):
    client, settings, _ = make_engine_app(tmp_path)

    def unexpected(*_args: object, **_kwargs: object) -> EngineDiagnosis:
        raise AssertionError("diagnose must not run without configured roots")

    monkeypatch.setattr(engine_routes, "diagnose_engine", unexpected)
    response = client.post("/api/engine/diagnose", headers=auth(settings))
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert "尚未配置引擎目录" in error["message"]


def test_engine_diagnose_maps_host_failure_to_503(tmp_path: Path, monkeypatch):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    client, settings, _ = make_engine_app(tmp_path, engine, game)

    def failing(_engine_root: Path, _game_root: Path) -> EngineDiagnosis:
        raise EngineDiagnoseError("引擎诊断超时：30 秒内未返回")

    monkeypatch.setattr(engine_routes, "diagnose_engine", failing)
    response = client.post("/api/engine/diagnose", headers=auth(settings))
    assert response.status_code == 503
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "engine_diagnose_failed"
    assert error["message"] == "引擎诊断超时：30 秒内未返回"
    assert error["retriable"] is True


def test_engine_diagnose_names_missing_game_plugin(tmp_path: Path, monkeypatch):
    engine = build_engine_root(tmp_path / "engine")
    game = tmp_path / "game"
    game.mkdir()
    client, settings, _ = make_engine_app(tmp_path, engine, game)
    monkeypatch.setattr(engine_routes, "diagnose_engine", lambda *_args: pytest.fail("must not run"))
    response = client.post("/api/engine/diagnose", headers=auth(settings))
    assert response.status_code == 400
    assert "fm_Data/Plugins/x86_64/game_plugin.dll" in response.json()["error"]["message"]


def test_engine_diagnose_requires_auth(tmp_path: Path):
    client, _, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/diagnose")
    assert response.status_code == 401
    assert set(response.json()["error"]) == ERROR_FIELDS


def test_engine_openapi_documents_paths_and_models(tmp_path: Path):
    client, _, _ = make_engine_app(tmp_path)
    document = client.get("/api/openapi.json").json()
    paths = document["paths"]
    assert paths["/api/engine"]["get"]["responses"]["401"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
    assert "422" not in paths["/api/engine"]["get"]
    select = paths["/api/engine/select"]["post"]
    assert "422" not in select
    for status in ("400", "401"):
        assert select["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorEnvelope"
        }
    diagnose = paths["/api/engine/diagnose"]["post"]
    assert "422" not in diagnose
    for status in ("400", "401", "503"):
        assert diagnose["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorEnvelope"
        }
    schemas = document["components"]["schemas"]
    assert set(schemas["EngineStatusOutput"]["properties"]) == {"engine_root", "game_root", "engine", "game"}
    assert set(schemas["EngineAvailabilityOutput"]["properties"]) == {"available", "missing"}
    assert set(schemas["EngineSelectInput"]["properties"]) == {"engine_root", "game_root"}
    assert set(schemas["EngineDiagnosisOutput"]["properties"]) == {
        "compatible",
        "trial_allowed",
        "reason",
        "adapter_version",
        "image_sha256",
    }
    assert set(schemas["EngineDiagnosisOutput"]["required"]) == {"compatible", "trial_allowed", "reason", "image_sha256"}
    imported = paths["/api/engine/import"]["post"]
    assert "422" not in imported
    for status in ("400", "401"):
        assert imported["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorEnvelope"
        }
    assert set(schemas["EngineImportInput"]["properties"]) == {"source_path"}
    assert set(schemas["EngineImportCopiedOutput"]["properties"]) == {"path", "bytes"}
    assert set(schemas["EngineImportOutput"]["properties"]) == {
        "target_root",
        "available",
        "missing",
        "matched",
        "adapter_version",
        "catalog_path",
        "copied",
        "total_bytes",
    }
    assert set(schemas["EngineImportOutput"]["required"]) == {
        "target_root",
        "available",
        "missing",
        "matched",
        "adapter_version",
        "catalog_path",
        "copied",
        "total_bytes",
    }


def build_import_source(path: Path) -> Path:
    workspace = build_engine_root(path / "releases" / "release-1" / "engine")
    fixtures = workspace / "fm27_native" / "fixtures"
    fixtures.mkdir()
    (fixtures / "match.pkm").write_bytes(b"match-fixture")
    (path / "catalog.json").write_bytes(b'{"catalog": true}')
    return path


def test_engine_import_assembles_engine_workspace(tmp_path: Path):
    source = build_import_source(tmp_path / "install")
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/import", json={"source_path": str(source)}, headers=auth(settings))
    assert response.status_code == 200
    payload = response.json()
    target = (tmp_path / "engine").resolve()
    assert payload["target_root"] == str(target)
    assert payload["available"] is True
    assert payload["missing"] == []
    assert payload["matched"] is False
    assert payload["adapter_version"] is None
    assert payload["catalog_path"] == str((source / "catalog.json").resolve())
    assert {item["path"] for item in payload["copied"]} == {
        "fm27_native/FM27Simulator.exe",
        "fm27_research/setpiece_enum_catalog.json",
        "fm27_native/editor_manual_default.json",
        "fm27_native/editor_advanced_snapshot.json",
        "fm27_native/editor_setpieces_default.json",
        "fm27_native/fixtures/match.pkm",
        "catalog.json",
    }
    assert payload["total_bytes"] == sum(item["bytes"] for item in payload["copied"])
    assert (target / "catalog.json").read_bytes() == b'{"catalog": true}'
    assert (target / "fm27_native" / "fixtures" / "match.pkm").read_bytes() == b"match-fixture"


def test_engine_import_reports_matching_game_plugin(tmp_path: Path):
    source = build_import_source(tmp_path / "install")
    game = build_game_root(tmp_path / "game")
    plugin = game / "fm_Data" / "Plugins" / "x86_64" / "game_plugin.dll"
    digest = hashlib.sha256(plugin.read_bytes()).hexdigest()
    workspace = source / "releases" / "release-1" / "engine"
    (workspace / "fm27_native" / "adapter_version.json").write_text(
        f'{{"version": "27.0.1+2503222", "reference_dll_sha256": "{digest}"}}',
        encoding="utf-8",
    )
    client, settings, _ = make_engine_app(tmp_path, game_root=game)
    response = client.post("/api/engine/import", json={"source_path": str(source)}, headers=auth(settings))
    assert response.status_code == 200
    payload = response.json()
    assert payload["matched"] is True
    assert payload["adapter_version"] == "27.0.1+2503222"
    assert payload["available"] is True


def test_engine_import_maps_missing_resources_to_400(tmp_path: Path):
    source = tmp_path / "install"
    source.mkdir()
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/import", json={"source_path": str(source)}, headers=auth(settings))
    assert response.status_code == 400
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "engine_import_failed"
    assert error["retriable"] is False


def test_engine_import_rejects_invalid_source_path(tmp_path: Path):
    client, settings, _ = make_engine_app(tmp_path)
    headers = auth(settings)
    empty = client.post("/api/engine/import", json={"source_path": ""}, headers=headers)
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "validation_failed"
    blank = client.post("/api/engine/import", json={"source_path": "   "}, headers=headers)
    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "validation_failed"
    assert "源目录不能为空" in blank.json()["error"]["message"]
    relative = client.post("/api/engine/import", json={"source_path": "install"}, headers=headers)
    assert relative.status_code == 400
    assert relative.json()["error"]["code"] == "validation_failed"
    assert "源目录必须是绝对路径" in relative.json()["error"]["message"]


def test_engine_import_requires_auth(tmp_path: Path):
    client, _, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/import", json={"source_path": str(tmp_path / "install")})
    assert response.status_code == 401
    assert set(response.json()["error"]) == ERROR_FIELDS


def test_engine_import_accepts_quoted_source_path(tmp_path: Path):
    source = build_import_source(tmp_path / "install")
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/import", json={"source_path": f'"{source}"'}, headers=auth(settings))
    assert response.status_code == 200
    payload = response.json()
    assert payload["target_root"] == str((tmp_path / "engine").resolve())
    assert (tmp_path / "engine" / "catalog.json").read_bytes() == b'{"catalog": true}'


def test_engine_import_prefers_tactics_catalog_over_root_catalog(tmp_path: Path):
    source = build_import_source(tmp_path / "install")
    (source / "catalog.json").write_bytes(b'{"root": true}')
    peer = source / "agent-runtime" / "source" / "peer" / "catalog.json"
    peer.parent.mkdir(parents=True)
    peer.write_bytes(b'{"peer": true}')
    tactics = source / "agent-runtime" / "source" / "tactics_ui" / "catalog.json"
    tactics.parent.mkdir(parents=True)
    tactics.write_bytes(b'{"tactics": true}')
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/import", json={"source_path": str(source)}, headers=auth(settings))
    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_path"] == str(tactics.resolve())
    assert (tmp_path / "engine" / "catalog.json").read_bytes() == b'{"tactics": true}'


def test_engine_import_uses_game_root_selected_in_same_process(tmp_path: Path):
    source = build_import_source(tmp_path / "install")
    game = build_game_root(tmp_path / "game")
    plugin = game / "fm_Data" / "Plugins" / "x86_64" / "game_plugin.dll"
    digest = hashlib.sha256(plugin.read_bytes()).hexdigest()
    workspace = source / "releases" / "release-1" / "engine"
    (workspace / "fm27_native" / "adapter_version.json").write_text(
        f'{{"version": "27.0.1+2503222", "reference_dll_sha256": "{digest}"}}',
        encoding="utf-8",
    )
    client, settings, _ = make_engine_app(tmp_path)
    selected = client.post("/api/engine/select", json={"game_root": str(game)}, headers=auth(settings))
    assert selected.status_code == 200
    response = client.post("/api/engine/import", json={"source_path": str(source)}, headers=auth(settings))
    assert response.status_code == 200
    assert response.json()["matched"] is True


def test_engine_import_rejects_symlinked_engine_directory(tmp_path: Path):
    source = build_import_source(tmp_path / "install")
    real_engine = tmp_path / "real-engine"
    real_engine.mkdir()
    (tmp_path / "engine").symlink_to(real_engine, target_is_directory=True)
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/import", json={"source_path": str(source)}, headers=auth(settings))
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "engine_import_failed"
    assert "符号链接" in error["message"]
    assert list(real_engine.iterdir()) == []


def test_engine_import_rejects_source_symlink_outside_workspace(tmp_path: Path):
    source = build_import_source(tmp_path / "install")
    outside = tmp_path / "outside-manual.json"
    outside.write_text('{"outside": true}', encoding="utf-8")
    manual = source / "releases" / "release-1" / "engine" / "fm27_native" / "editor_manual_default.json"
    manual.unlink()
    manual.symlink_to(outside)
    client, settings, _ = make_engine_app(tmp_path)
    response = client.post("/api/engine/import", json={"source_path": str(source)}, headers=auth(settings))
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "engine_import_failed"
    assert "越界的符号链接" in error["message"]
    assert not (tmp_path / "engine").exists()
