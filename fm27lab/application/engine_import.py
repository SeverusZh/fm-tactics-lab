"""Assemble a local engine workspace by importing resources from an existing installation."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from fm27lab.application.engine_config import (
    DEFAULT_ENGINE_DIRECTORY,
    ENGINE_REQUIRED_FILES,
    GAME_REQUIRED_FILES,
    missing_engine_files,
)

HOST_RELATIVE = "fm27_native/FM27Simulator.exe"
RESEARCH_CATALOG_RELATIVE = "fm27_research/setpiece_enum_catalog.json"
ADAPTER_VERSION_RELATIVE = "fm27_native/adapter_version.json"
FIXTURES_RELATIVE = "fm27_native/fixtures"
MATCH_FIXTURE_RELATIVE = f"{FIXTURES_RELATIVE}/match.pkm"
CATALOG_NAME = "catalog.json"
TACTICS_CATALOG_PARENT = "tactics_ui"
RELEASE_DIRECTORY = "releases"
GAME_PLUGIN_RELATIVE = GAME_REQUIRED_FILES[0]
IMPORT_REQUIRED_FILES = (*ENGINE_REQUIRED_FILES, MATCH_FIXTURE_RELATIVE)
OPTIONAL_FILES = (
    ADAPTER_VERSION_RELATIVE,
    "fm27_native/engine_compat_profile.json",
)
DISCOVERY_MARKERS = (HOST_RELATIVE, RESEARCH_CATALOG_RELATIVE)
CATALOG_SEARCH_DEPTH = 4
HOST_NAME = Path(HOST_RELATIVE).name
BUSY_ENGINE_MESSAGE = "引擎文件被占用，可能正在运行比赛，请等待任务结束或重启应用"
SYMLINK_TARGET_MESSAGE = "引擎目录不能是符号链接"
_IMPORT_LOCK = threading.Lock()
_BUSY_ERRNOS = frozenset({errno.EACCES, errno.EBUSY})
_BUSY_WINERRORS = frozenset({32, 33})
_VERSION_NUMBER = re.compile(r"\d+")


class EngineImportError(ValueError):
    """Raised when the source directory cannot provide a complete engine workspace."""


@dataclass(frozen=True, slots=True)
class EngineSource:
    root: Path
    adapter_version: str | None
    reference_dll_sha256: str | None
    version_key: tuple[int, ...]
    modified_at: float
    matched: bool


@dataclass(frozen=True, slots=True)
class EngineDiscovery:
    source_root: Path
    workspaces: tuple[EngineSource, ...]
    catalogs: tuple[Path, ...]
    incomplete: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class CopiedFile:
    path: str
    bytes: int


@dataclass(frozen=True, slots=True)
class EngineImportResult:
    target_root: Path
    available: bool
    missing: tuple[str, ...]
    matched: bool
    adapter_version: str | None
    catalog_path: Path | None
    copied: tuple[CopiedFile, ...]
    total_bytes: int


def discover_engine_sources(
    source_root: str | Path,
    *,
    reference_dll_sha256: str | None = None,
) -> EngineDiscovery:
    root = _validated_source(source_root)
    workspaces: list[EngineSource] = []
    incomplete: list[Path] = []
    for candidate in _engine_candidates(root):
        if _has_discovery_markers(candidate):
            workspaces.append(_engine_source(candidate, reference_dll_sha256))
        else:
            incomplete.append(candidate)
    workspaces.sort(key=lambda item: (item.matched, item.version_key, item.modified_at), reverse=True)
    return EngineDiscovery(
        source_root=root,
        workspaces=tuple(workspaces),
        catalogs=_catalog_candidates(root),
        incomplete=tuple(incomplete),
    )


def import_engine_workspace(
    source_root: str | Path,
    target_root: str | Path,
    *,
    game_root: str | Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    data_dir: str | Path | None = None,
) -> EngineImportResult:
    with _IMPORT_LOCK:
        return _import_workspace(
            source_root,
            target_root,
            game_root=game_root,
            on_progress=on_progress,
            data_dir=data_dir,
        )


def _import_workspace(
    source_root: str | Path,
    target_root: str | Path,
    *,
    game_root: str | Path | None,
    on_progress: Callable[[str], None] | None,
    data_dir: str | Path | None,
) -> EngineImportResult:
    source = _validated_source(source_root)
    target = _validated_target(target_root)
    if data_dir is not None:
        _ensure_target_within(target, data_dir)
    _ensure_separate_target(source, target)
    discovery = discover_engine_sources(source, reference_dll_sha256=_reference_dll_sha256(game_root))
    selected = _select_workspace(discovery)
    catalog = _select_catalog(discovery)
    plan = _copy_plan(selected.root, catalog)
    _preflight_plan(plan, workspace_root=selected.root, source_root=discovery.source_root)
    _create_target(target)
    copied: list[CopiedFile] = []
    for relative, origin in plan.items():
        copied.append(CopiedFile(relative, _copy_file(origin, target / relative, target)))
        if on_progress is not None:
            on_progress(relative)
    missing = missing_engine_files(target)
    return EngineImportResult(
        target_root=target,
        available=not missing,
        missing=missing,
        matched=selected.matched,
        adapter_version=selected.adapter_version,
        catalog_path=catalog,
        copied=tuple(copied),
        total_bytes=sum(item.bytes for item in copied),
    )


def _engine_candidates(root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = [root]
    for child in _subdirectories(root):
        candidates.append(child)
        candidates.append(child / DEFAULT_ENGINE_DIRECTORY)
    for release in _subdirectories(root / RELEASE_DIRECTORY):
        candidates.append(release)
        candidates.append(release / DEFAULT_ENGINE_DIRECTORY)
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.is_dir():
            continue
        seen.add(candidate)
        unique.append(candidate)
    return tuple(unique)


def _engine_source(root: Path, reference_dll_sha256: str | None) -> EngineSource:
    version, reference = _adapter_metadata(root)
    matched = (
        reference is not None
        and reference_dll_sha256 is not None
        and reference.lower() == reference_dll_sha256.lower()
    )
    return EngineSource(
        root=root,
        adapter_version=version,
        reference_dll_sha256=reference,
        version_key=_version_key(version),
        modified_at=_adapter_modified_at(root),
        matched=matched,
    )


def _adapter_metadata(root: Path) -> tuple[str | None, str | None]:
    try:
        payload = json.loads((root / ADAPTER_VERSION_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    version = payload.get("version")
    reference = payload.get("reference_dll_sha256")
    return (
        version if isinstance(version, str) and version.strip() else None,
        reference if isinstance(reference, str) and reference.strip() else None,
    )


def _adapter_modified_at(root: Path) -> float:
    try:
        return (root / ADAPTER_VERSION_RELATIVE).stat().st_mtime
    except OSError:
        try:
            return root.stat().st_mtime
        except OSError:
            return 0.0


def _version_key(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    return tuple(int(part) for part in _VERSION_NUMBER.findall(version))


def _has_discovery_markers(root: Path) -> bool:
    return all((root / relative).is_file() for relative in DISCOVERY_MARKERS)


def _missing_markers(root: Path) -> tuple[str, ...]:
    return tuple(relative for relative in DISCOVERY_MARKERS if not (root / relative).is_file())


def _catalog_candidates(root: Path) -> tuple[Path, ...]:
    found = [directory / CATALOG_NAME for directory, _depth in _walk_tree(root, CATALOG_SEARCH_DEPTH)]
    catalogs = [candidate for candidate in found if candidate.is_file()]
    catalogs.sort(key=lambda path: _catalog_rank(root, path))
    return tuple(catalogs)


def _walk_tree(root: Path, max_depth: int) -> Iterator[tuple[Path, int]]:
    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        yield directory, depth
        if depth >= max_depth:
            continue
        pending.extend((child, depth + 1) for child in _subdirectories(directory))


def _subdirectories(root: Path) -> tuple[Path, ...]:
    try:
        entries = sorted(root.iterdir(), key=lambda entry: entry.name)
    except OSError:
        return ()
    return tuple(
        entry
        for entry in entries
        if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith(".")
    )


def _catalog_rank(source_root: Path, catalog: Path) -> tuple[int, int, float, str]:
    relative_parent = catalog.parent.relative_to(source_root)
    depth = len(relative_parent.parts)
    if catalog.parent.name == TACTICS_CATALOG_PARENT:
        group = 0
    elif depth == 0:
        group = 1
    else:
        group = 2
    try:
        modified_at = -catalog.stat().st_mtime
    except OSError:
        modified_at = 0.0
    return (group, depth, modified_at, str(catalog))


def _select_workspace(discovery: EngineDiscovery) -> EngineSource:
    for workspace in discovery.workspaces:
        if not _missing_import_files(workspace.root):
            return workspace
    if not discovery.workspaces:
        raise EngineImportError(_missing_workspace_message(discovery))
    closest = discovery.workspaces[0]
    missing = _missing_import_files(closest.root)
    raise EngineImportError(f"源引擎工作区缺少必需文件：{closest.root}；缺少：{'、'.join(missing)}")


def _missing_workspace_message(discovery: EngineDiscovery) -> str:
    candidates = discovery.incomplete or (discovery.source_root,)
    closest = min(candidates, key=lambda candidate: (len(_missing_markers(candidate)), str(candidate)))
    missing = _missing_markers(closest)
    return f"未从源目录发现可用的引擎工作区：{discovery.source_root}；缺少：{'、'.join(missing)}"


def _missing_import_files(root: Path) -> tuple[str, ...]:
    return tuple(relative for relative in IMPORT_REQUIRED_FILES if not (root / relative).is_file())


def _select_catalog(discovery: EngineDiscovery) -> Path:
    if not discovery.catalogs:
        raise EngineImportError(f"源目录缺少运行时目录 catalog.json：{discovery.source_root}")
    return discovery.catalogs[0]


def _copy_plan(workspace_root: Path, catalog: Path) -> dict[str, Path]:
    plan: dict[str, Path] = {relative: workspace_root / relative for relative in IMPORT_REQUIRED_FILES}
    for relative in OPTIONAL_FILES:
        candidate = workspace_root / relative
        if candidate.is_file():
            plan[relative] = candidate
    for fixture in sorted((workspace_root / FIXTURES_RELATIVE).glob("*.pkm")):
        if fixture.is_file():
            plan[f"{FIXTURES_RELATIVE}/{fixture.name}"] = fixture
    plan[CATALOG_NAME] = catalog
    return plan


def _preflight_plan(plan: dict[str, Path], *, workspace_root: Path, source_root: Path) -> None:
    for relative, origin in plan.items():
        boundary = source_root if relative == CATALOG_NAME else workspace_root
        try:
            resolved = origin.resolve()
        except (OSError, RuntimeError) as error:
            raise EngineImportError(f"源文件不可读取：{relative}；{error}") from error
        if not resolved.is_relative_to(boundary):
            raise EngineImportError(f"源目录包含越界的符号链接：{origin}")
        if not resolved.is_file():
            raise EngineImportError(f"源文件不存在或不是文件：{origin}")
        try:
            with resolved.open("rb") as stream:
                stream.read(1)
        except OSError as error:
            raise EngineImportError(f"源文件不可读取：{relative}；{error}") from error


def _create_target(target: Path) -> None:
    if target.is_symlink():
        raise EngineImportError(SYMLINK_TARGET_MESSAGE)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise EngineImportError(f"无法创建目标引擎目录：{target}；{error}") from error


def _copy_file(origin: Path, destination: Path, target_root: Path) -> int:
    parent = destination.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = parent.resolve()
    except (OSError, RuntimeError) as error:
        raise EngineImportError(f"无法创建目标引擎目录：{parent}；{error}") from error
    if not resolved_parent.is_relative_to(target_root):
        raise EngineImportError(f"目标引擎目录包含越界的符号链接：{parent}")
    temporary = parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    try:
        size = origin.stat().st_size
        shutil.copyfile(origin, temporary)
        os.replace(temporary, destination)
    except OSError as error:
        _discard(temporary)
        raise EngineImportError(_write_failure_message(destination, error)) from error
    return size


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_failure_message(destination: Path, error: OSError) -> str:
    if _is_busy_error(error):
        return BUSY_ENGINE_MESSAGE
    return f"写入引擎文件失败：{destination}；{error}"


def _is_busy_error(error: OSError) -> bool:
    if error.errno in _BUSY_ERRNOS:
        return True
    return getattr(error, "winerror", None) in _BUSY_WINERRORS


def _ensure_target_within(target: Path, data_dir: str | Path) -> None:
    try:
        boundary = Path(data_dir).resolve()
    except (OSError, RuntimeError) as error:
        raise EngineImportError(f"无法解析数据目录：{data_dir}；{error}") from error
    if not target.is_relative_to(boundary):
        raise EngineImportError(f"引擎目录不能位于数据目录之外：{target}")


def _reference_dll_sha256(game_root: str | Path | None) -> str | None:
    if game_root is None:
        return None
    plugin = Path(game_root) / GAME_PLUGIN_RELATIVE
    if not plugin.is_file():
        return None
    try:
        digest = hashlib.sha256()
        with plugin.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _validated_source(value: str | Path) -> Path:
    path = _validated_directory(value, "源目录")
    if not path.is_dir():
        raise ValueError(f"源目录不存在或不是目录：{path}")
    return path.resolve()


def _validated_target(value: str | Path) -> Path:
    path = _validated_directory(value, "目标目录")
    if path.is_symlink():
        raise EngineImportError(SYMLINK_TARGET_MESSAGE)
    return path.resolve()


def _validated_directory(value: str | Path, label: str) -> Path:
    if isinstance(value, Path):
        path = value
    else:
        text = value.strip()
        if not text:
            raise ValueError(f"{label}不能为空")
        path = Path(text)
    if not path.is_absolute():
        raise ValueError(f"{label}必须是绝对路径：{path}")
    return path


def _ensure_separate_target(source: Path, target: Path) -> None:
    if target == source or source in target.parents:
        raise EngineImportError(f"目标引擎目录不能位于源目录内部：{target}")
