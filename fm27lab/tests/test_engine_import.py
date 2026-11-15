from __future__ import annotations

import errno
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest

from fm27lab.application import engine_import
from fm27lab.application.engine_import import (
    BUSY_ENGINE_MESSAGE,
    EngineImportError,
    EngineImportResult,
    discover_engine_sources,
    import_engine_workspace,
)

HOST_RELATIVE = "fm27_native/FM27Simulator.exe"
MANUAL_RELATIVE = "fm27_native/editor_manual_default.json"
RESEARCH_RELATIVE = "fm27_research/setpiece_enum_catalog.json"
MATCH_FIXTURE_RELATIVE = "fm27_native/fixtures/match.pkm"
DEFAULT_CATALOG_RELATIVE = "agent-runtime/source/tactics_ui/catalog.json"


def make_workspace(
    root: Path,
    *,
    host: bytes = b"host-binary",
    version: str | None = "27.0.1+2503222",
    reference: str | None = None,
    match_fixture: bytes | None = b"match-fixture",
    fixtures: dict[str, bytes] | None = None,
    include_host: bool = True,
    include_manual: bool = True,
    include_advanced: bool = True,
    include_setpieces: bool = True,
    include_research: bool = True,
) -> Path:
    native = root / "fm27_native"
    native.mkdir(parents=True)
    if include_host:
        (native / "FM27Simulator.exe").write_bytes(host)
    if include_manual:
        (native / "editor_manual_default.json").write_text('{"editor": true}', encoding="utf-8")
    if include_advanced:
        (native / "editor_advanced_snapshot.json").write_text('{"editor": true}', encoding="utf-8")
    if include_setpieces:
        (native / "editor_setpieces_default.json").write_text('{"editor": true}', encoding="utf-8")
    if version is not None or reference is not None:
        payload: dict[str, str] = {}
        if version is not None:
            payload["version"] = version
        if reference is not None:
            payload["reference_dll_sha256"] = reference
        (native / "adapter_version.json").write_text(json.dumps(payload), encoding="utf-8")
    fixture_dir = native / "fixtures"
    if match_fixture is not None:
        fixture_dir.mkdir(exist_ok=True)
        (fixture_dir / "match.pkm").write_bytes(match_fixture)
    for name, payload in (fixtures or {}).items():
        fixture_dir.mkdir(exist_ok=True)
        (fixture_dir / name).write_bytes(payload)
    if include_research:
        research = root / "fm27_research"
        research.mkdir()
        (research / "setpiece_enum_catalog.json").write_text('{"pieces": []}', encoding="utf-8")
    return root


def write_catalog(root: Path, relative: str = DEFAULT_CATALOG_RELATIVE, payload: bytes = b'{"catalog": true}') -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def build_install(root: Path, *, host: bytes = b"host-binary", version: str = "27.0.1+2503222") -> Path:
    workspace = make_workspace(root / "releases" / "release-1" / "engine", host=host, version=version)
    write_catalog(root)
    return workspace


def test_imports_workspace_from_release_directory(tmp_path: Path):
    source = tmp_path / "install"
    build_install(source)
    target = tmp_path / "data" / "engine"
    result = import_engine_workspace(source, target)
    assert result.target_root == target.resolve()
    assert result.available is True
    assert result.missing == ()
    assert result.matched is False
    assert result.adapter_version == "27.0.1+2503222"
    assert result.catalog_path == (source / DEFAULT_CATALOG_RELATIVE).resolve()
    assert (target / HOST_RELATIVE).read_bytes() == b"host-binary"
    assert (target / "catalog.json").read_bytes() == b'{"catalog": true}'
    assert result.total_bytes == sum(item.bytes for item in result.copied)


def test_prefers_workspace_with_newer_adapter_version(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "old" / "engine", host=b"old-host", version="27.0.1+111")
    make_workspace(source / "releases" / "new" / "engine", host=b"new-host", version="27.0.2+222")
    write_catalog(source)
    result = import_engine_workspace(source, tmp_path / "engine")
    assert result.adapter_version == "27.0.2+222"
    assert (result.target_root / HOST_RELATIVE).read_bytes() == b"new-host"


def test_prefers_workspace_matching_game_plugin_sha256(tmp_path: Path):
    source = tmp_path / "install"
    plugin_image = b"game-plugin-image"
    reference = hashlib.sha256(plugin_image).hexdigest()
    make_workspace(source / "releases" / "old" / "engine", host=b"old-host", version="27.0.1+111", reference=reference)
    make_workspace(source / "releases" / "new" / "engine", host=b"new-host", version="27.0.2+222", reference="f" * 64)
    write_catalog(source)
    game = tmp_path / "game"
    plugins = game / "fm_Data" / "Plugins" / "x86_64"
    plugins.mkdir(parents=True)
    (plugins / "game_plugin.dll").write_bytes(plugin_image)
    matched = import_engine_workspace(source, tmp_path / "engine", game_root=game)
    assert matched.matched is True
    assert matched.adapter_version == "27.0.1+111"
    assert (matched.target_root / HOST_RELATIVE).read_bytes() == b"old-host"
    unmatched = import_engine_workspace(source, tmp_path / "engine-without-game")
    assert unmatched.matched is False
    assert unmatched.adapter_version == "27.0.2+222"


def test_finds_catalog_in_nested_tactics_source(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine")
    catalog = write_catalog(source, "agent-runtime/source/tactics_ui/catalog.json", b'{"nested": true}')
    result = import_engine_workspace(source, tmp_path / "engine")
    assert result.catalog_path == catalog.resolve()
    assert (result.target_root / "catalog.json").read_bytes() == b'{"nested": true}'


def test_prefers_tactics_catalog_over_nested_runtime_catalog(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine")
    write_catalog(source, "releases/release-1/engine/fm27_native/catalog.json", b'{"runtime": true}')
    preferred = write_catalog(source, "tactics_ui/catalog.json", b'{"preferred": true}')
    result = import_engine_workspace(source, tmp_path / "engine")
    assert result.catalog_path == preferred.resolve()
    assert (result.target_root / "catalog.json").read_bytes() == b'{"preferred": true}'


def test_missing_host_reports_missing_file(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine", include_host=False)
    write_catalog(source)
    with pytest.raises(EngineImportError, match="FM27Simulator.exe"):
        import_engine_workspace(source, tmp_path / "engine")
    assert not (tmp_path / "engine" / "fm27_native").exists()


def test_missing_research_catalog_reports_missing_file(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine", include_research=False)
    write_catalog(source)
    with pytest.raises(EngineImportError, match="setpiece_enum_catalog.json"):
        import_engine_workspace(source, tmp_path / "engine")


def test_missing_editor_manual_reports_missing_file(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine", include_manual=False)
    write_catalog(source)
    with pytest.raises(EngineImportError, match="editor_manual_default.json"):
        import_engine_workspace(source, tmp_path / "engine")


def test_missing_editor_advanced_snapshot_reports_missing_file(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine", include_advanced=False)
    write_catalog(source)
    with pytest.raises(EngineImportError, match="editor_advanced_snapshot.json"):
        import_engine_workspace(source, tmp_path / "engine")


def test_missing_editor_setpieces_snapshot_reports_missing_file(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine", include_setpieces=False)
    write_catalog(source)
    with pytest.raises(EngineImportError, match="editor_setpieces_default.json"):
        import_engine_workspace(source, tmp_path / "engine")


def test_requires_match_fixture(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine", match_fixture=None)
    write_catalog(source)
    with pytest.raises(EngineImportError, match="fm27_native/fixtures/match.pkm"):
        import_engine_workspace(source, tmp_path / "engine")


def test_requires_runtime_catalog(tmp_path: Path):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine")
    with pytest.raises(EngineImportError, match="catalog.json"):
        import_engine_workspace(source, tmp_path / "engine")


def test_rejects_target_inside_source(tmp_path: Path):
    source = tmp_path / "install"
    build_install(source)
    with pytest.raises(EngineImportError, match="不能位于源目录内部"):
        import_engine_workspace(source, source / "engine")
    with pytest.raises(EngineImportError, match="不能位于源目录内部"):
        import_engine_workspace(source, source)
    assert not (source / "engine").exists()


def test_overwrites_existing_files_and_keeps_unrelated_files(tmp_path: Path):
    source = tmp_path / "install"
    build_install(source, host=b"fresh-host")
    target = tmp_path / "engine"
    (target / "fm27_native").mkdir(parents=True)
    (target / HOST_RELATIVE).write_bytes(b"stale-host")
    (target / "notes.txt").write_text("keep", encoding="utf-8")
    first = import_engine_workspace(source, target)
    second = import_engine_workspace(source, target)
    assert (target / HOST_RELATIVE).read_bytes() == b"fresh-host"
    assert (target / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert first.copied == second.copied
    assert first.total_bytes == second.total_bytes


def test_reports_copied_manifest_and_total_bytes(tmp_path: Path):
    source = tmp_path / "install"
    workspace = make_workspace(
        source / "releases" / "release-1" / "engine",
        host=b"host-bytes",
        match_fixture=b"match-bytes",
        fixtures={"extra.pkm": b"extra-bytes"},
    )
    (workspace / "fm27_native" / "editor_advanced_snapshot.json").write_bytes(b"advanced")
    (workspace / "fm27_native" / "editor_setpieces_default.json").write_bytes(b"setpieces")
    (workspace / "fm27_native" / "engine_compat_profile.json").write_bytes(b"profile")
    write_catalog(source, payload=b"catalog-bytes")
    target = tmp_path / "engine"
    result = import_engine_workspace(source, target)
    copied = {item.path: item.bytes for item in result.copied}
    assert set(copied) == {
        HOST_RELATIVE,
        MANUAL_RELATIVE,
        RESEARCH_RELATIVE,
        MATCH_FIXTURE_RELATIVE,
        "fm27_native/fixtures/extra.pkm",
        "fm27_native/adapter_version.json",
        "fm27_native/editor_advanced_snapshot.json",
        "fm27_native/editor_setpieces_default.json",
        "fm27_native/engine_compat_profile.json",
        "catalog.json",
    }
    actual = {
        path.relative_to(target).as_posix(): path.stat().st_size
        for path in target.rglob("*")
        if path.is_file()
    }
    assert copied == actual
    assert result.total_bytes == sum(actual.values())
    assert result.available is True
    assert result.missing == ()


def test_reports_progress_for_each_copied_file(tmp_path: Path):
    source = tmp_path / "install"
    build_install(source)
    seen: list[str] = []
    result = import_engine_workspace(source, tmp_path / "engine", on_progress=seen.append)
    assert seen == [item.path for item in result.copied]


def test_reports_busy_host_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "install"
    build_install(source)
    copy_file = engine_import.shutil.copyfile

    def busy_copy(origin: str, destination: str) -> str:
        if Path(destination).name.startswith(".FM27Simulator.exe.tmp-"):
            raise PermissionError(errno.EACCES, "file is in use")
        return copy_file(origin, destination)

    monkeypatch.setattr(engine_import.shutil, "copyfile", busy_copy)
    with pytest.raises(EngineImportError) as raised:
        import_engine_workspace(source, tmp_path / "engine")
    assert str(raised.value) == BUSY_ENGINE_MESSAGE


def test_discovery_ranks_workspaces_and_catalogs(tmp_path: Path):
    source = tmp_path / "install"
    older = make_workspace(source / "releases" / "a" / "engine", version="27.0.1+1")
    newer = make_workspace(source / "releases" / "b" / "engine", version="27.0.2+2")
    catalog = write_catalog(source)
    discovery = discover_engine_sources(source)
    assert [item.root for item in discovery.workspaces] == [newer.resolve(), older.resolve()]
    assert discovery.catalogs == (catalog.resolve(),)


def test_discovery_falls_back_to_adapter_mtime(tmp_path: Path):
    source = tmp_path / "install"
    first = make_workspace(source / "releases" / "a" / "engine", version="27.0.1+1")
    second = make_workspace(source / "releases" / "b" / "engine", version="27.0.1+1")
    write_catalog(source)
    os.utime(first / "fm27_native" / "adapter_version.json", (1_000, 1_000))
    os.utime(second / "fm27_native" / "adapter_version.json", (2_000, 2_000))
    discovery = discover_engine_sources(source)
    assert [item.root for item in discovery.workspaces] == [second.resolve(), first.resolve()]


def test_imports_workspace_at_source_root(tmp_path: Path):
    source = tmp_path / "engine-source"
    make_workspace(source)
    write_catalog(source, "tactics_ui/catalog.json", b'{"root": true}')
    result = import_engine_workspace(source, tmp_path / "engine")
    assert result.adapter_version == "27.0.1+2503222"
    assert (result.target_root / HOST_RELATIVE).is_file()
    assert (result.target_root / "catalog.json").read_bytes() == b'{"root": true}'


def test_availability_uses_engine_missing_criteria(tmp_path: Path, monkeypatch):
    source = tmp_path / "install"
    make_workspace(source / "releases" / "release-1" / "engine")
    write_catalog(source)
    monkeypatch.setattr(engine_import, "missing_engine_files", lambda _root: ("fm27_native/catalog.json",))
    result = import_engine_workspace(source, tmp_path / "engine")
    assert result.available is False
    assert result.missing == ("fm27_native/catalog.json",)


def test_rejects_relative_and_missing_source(tmp_path: Path):
    with pytest.raises(ValueError, match="必须是绝对路径"):
        import_engine_workspace("install", tmp_path / "engine")
    with pytest.raises(ValueError, match="不存在或不是目录"):
        import_engine_workspace(tmp_path / "missing", tmp_path / "engine")
    with pytest.raises(ValueError, match="不能为空"):
        import_engine_workspace("   ", tmp_path / "engine")


def _winerror(code: int) -> OSError:
    error = OSError("operation would block")
    error.winerror = code
    return error


def test_rejects_symlinked_target_directory(tmp_path: Path):
    source = tmp_path / "install"
    build_install(source)
    real_target = tmp_path / "real-engine"
    real_target.mkdir()
    link_target = tmp_path / "engine"
    link_target.symlink_to(real_target, target_is_directory=True)
    with pytest.raises(EngineImportError, match="引擎目录不能是符号链接"):
        import_engine_workspace(source, link_target)
    assert list(real_target.iterdir()) == []


def test_rejects_source_symlink_escaping_workspace(tmp_path: Path):
    source = tmp_path / "install"
    workspace = build_install(source)
    outside = tmp_path / "outside-manual.json"
    outside.write_text('{"outside": true}', encoding="utf-8")
    manual = workspace / MANUAL_RELATIVE
    manual.unlink()
    manual.symlink_to(outside)
    target = tmp_path / "engine"
    with pytest.raises(EngineImportError, match="越界的符号链接"):
        import_engine_workspace(source, target)
    assert not target.exists()


def test_allows_source_symlink_within_workspace(tmp_path: Path):
    source = tmp_path / "install"
    workspace = build_install(source)
    manual = workspace / MANUAL_RELATIVE
    manual.unlink()
    manual.symlink_to(workspace / "fm27_research" / "setpiece_enum_catalog.json")
    result = import_engine_workspace(source, tmp_path / "engine")
    assert (result.target_root / MANUAL_RELATIVE).read_bytes() == b'{"pieces": []}'


def test_rejects_target_outside_data_directory(tmp_path: Path):
    source = tmp_path / "install"
    build_install(source)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(EngineImportError, match="数据目录之外"):
        import_engine_workspace(source, outside / "engine", data_dir=data_dir)
    assert not (outside / "engine").exists()
    (data_dir / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(EngineImportError, match="数据目录之外"):
        import_engine_workspace(source, data_dir / "escape" / "engine", data_dir=data_dir)
    assert not (outside / "engine").exists()


def test_preflight_failure_leaves_target_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "install"
    build_install(source)
    target = tmp_path / "engine"
    target.mkdir()
    sentinel = target / "sentinel.txt"
    sentinel.write_text("original", encoding="utf-8")
    build_plan = engine_import._copy_plan

    def drop_fixture(workspace_root: Path, catalog: Path) -> dict[str, Path]:
        plan = build_plan(workspace_root, catalog)
        plan[MATCH_FIXTURE_RELATIVE].unlink()
        return plan

    monkeypatch.setattr(engine_import, "_copy_plan", drop_fixture)
    with pytest.raises(EngineImportError, match="源文件不存在或不是文件"):
        import_engine_workspace(source, target)
    assert sentinel.read_text(encoding="utf-8") == "original"
    assert not (target / HOST_RELATIVE).exists()


def test_failed_copy_keeps_previous_content_and_cleans_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "install"
    build_install(source)
    target = tmp_path / "engine"
    import_engine_workspace(source, target)
    previous = (target / "catalog.json").read_bytes()
    copy_file = engine_import.shutil.copyfile

    def failing_copy(origin: str, destination: str) -> str:
        if Path(destination).name.startswith(".catalog.json.tmp-"):
            Path(destination).write_bytes(b"partial")
            raise OSError(errno.EIO, "input/output error")
        return copy_file(origin, destination)

    monkeypatch.setattr(engine_import.shutil, "copyfile", failing_copy)
    with pytest.raises(EngineImportError) as raised:
        import_engine_workspace(source, target)
    assert str(raised.value).startswith("写入引擎文件失败：")
    assert (target / "catalog.json").read_bytes() == previous
    assert [path.name for path in target.iterdir() if ".tmp-" in path.name] == []


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(errno.EACCES, "permission denied"),
        OSError(errno.EBUSY, "device or resource busy"),
        _winerror(32),
        _winerror(33),
    ],
    ids=["eacces", "ebusy", "winerror-32", "winerror-33"],
)
def test_maps_busy_write_errors_to_busy_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: OSError,
):
    source = tmp_path / "install"
    build_install(source)
    copy_file = engine_import.shutil.copyfile

    def busy_copy(origin: str, destination: str) -> str:
        if Path(destination).name.startswith(".catalog.json.tmp-"):
            raise error
        return copy_file(origin, destination)

    monkeypatch.setattr(engine_import.shutil, "copyfile", busy_copy)
    with pytest.raises(EngineImportError) as raised:
        import_engine_workspace(source, tmp_path / "engine")
    assert str(raised.value) == BUSY_ENGINE_MESSAGE


@pytest.mark.parametrize("code", [errno.EIO, errno.ENOSPC], ids=["eio", "enospc"])
def test_reports_generic_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int):
    source = tmp_path / "install"
    build_install(source)
    copy_file = engine_import.shutil.copyfile

    def failing_copy(origin: str, destination: str) -> str:
        if Path(destination).name.startswith(".catalog.json.tmp-"):
            raise OSError(code, "write failed")
        return copy_file(origin, destination)

    monkeypatch.setattr(engine_import.shutil, "copyfile", failing_copy)
    with pytest.raises(EngineImportError) as raised:
        import_engine_workspace(source, tmp_path / "engine")
    assert str(raised.value).startswith("写入引擎文件失败：")
    assert BUSY_ENGINE_MESSAGE not in str(raised.value)


def test_concurrent_imports_stay_consistent(tmp_path: Path):
    source = tmp_path / "install"
    build_install(source, host=b"concurrent-host")
    target = tmp_path / "engine"
    barrier = threading.Barrier(2)
    results: list[EngineImportResult] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            results.append(import_engine_workspace(source, target))
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    assert len(results) == 2
    assert results[0] == results[1]
    assert (target / HOST_RELATIVE).read_bytes() == b"concurrent-host"
    assert [path for path in target.rglob("*.tmp-*")] == []


def test_import_lock_serializes_concurrent_imports(tmp_path: Path):
    source = tmp_path / "install"
    build_install(source)
    first_holds_lock = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_progress: list[str] = []
    outcomes: list[EngineImportResult] = []
    failures: list[Exception] = []
    paused = [True]

    def pause_once(_relative: str) -> None:
        if paused[0]:
            paused[0] = False
            first_holds_lock.set()
            release_first.wait(timeout=10)

    def run_first() -> None:
        try:
            outcomes.append(import_engine_workspace(source, tmp_path / "engine-a", on_progress=pause_once))
        except Exception as error:
            failures.append(error)

    def run_second() -> None:
        second_started.set()
        try:
            target = tmp_path / "engine-b"
            outcomes.append(import_engine_workspace(source, target, on_progress=second_progress.append))
        except Exception as error:
            failures.append(error)

    first_thread = threading.Thread(target=run_first)
    first_thread.start()
    assert first_holds_lock.wait(timeout=5)
    second_thread = threading.Thread(target=run_second)
    second_thread.start()
    assert second_started.wait(timeout=5)
    time.sleep(0.5)
    blocked_while_first_holds_lock = second_progress == []
    release_first.set()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)
    assert blocked_while_first_holds_lock is True
    assert failures == []
    assert len(outcomes) == 2
