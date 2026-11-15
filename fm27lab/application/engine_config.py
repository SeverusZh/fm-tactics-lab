"""Engine and game directory configuration: validation, resolution and persistence."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository

ENGINE_KEY = "engine.root"
GAME_KEY = "game.root"
DEFAULT_ENGINE_DIRECTORY = "engine"
CATALOG_CANDIDATES = ("fm27_native/catalog.json", "catalog.json")
ENGINE_REQUIRED_FILES = (
    "fm27_native/FM27Simulator.exe",
    "fm27_research/setpiece_enum_catalog.json",
    "fm27_native/editor_manual_default.json",
    "fm27_native/editor_advanced_snapshot.json",
    "fm27_native/editor_setpieces_default.json",
)
GAME_REQUIRED_FILES = ("fm_Data/Plugins/x86_64/game_plugin.dll",)


@dataclass(frozen=True, slots=True)
class EngineConfig:
    engine_root: Path | None = None
    game_root: Path | None = None


@dataclass(frozen=True, slots=True)
class EngineStatus:
    engine_root: Path | None
    game_root: Path | None
    engine_missing: tuple[str, ...]
    game_missing: tuple[str, ...]

    @property
    def engine_available(self) -> bool:
        return self.engine_root is not None and not self.engine_missing

    @property
    def game_available(self) -> bool:
        return self.game_root is not None and not self.game_missing


def missing_engine_files(root: Path) -> tuple[str, ...]:
    missing = [relative for relative in ENGINE_REQUIRED_FILES if not (root / relative).is_file()]
    if not any((root / candidate).is_file() for candidate in CATALOG_CANDIDATES):
        missing.append("catalog.json")
    return tuple(missing)


def missing_game_files(root: Path) -> tuple[str, ...]:
    return tuple(relative for relative in GAME_REQUIRED_FILES if not (root / relative).is_file())


def validate_engine_root(value: str | Path) -> Path:
    root = _validated_directory(value, "引擎目录")
    missing = missing_engine_files(root)
    if missing:
        raise ValueError("引擎目录缺少：" + "、".join(missing))
    return root


def validate_game_root(value: str | Path) -> Path:
    root = _validated_directory(value, "游戏目录")
    missing = missing_game_files(root)
    if missing:
        raise ValueError("游戏目录缺少：" + "、".join(missing))
    return root


def describe_engine_config(config: EngineConfig) -> EngineStatus:
    engine_missing = missing_engine_files(config.engine_root) if config.engine_root is not None else ()
    game_missing = missing_game_files(config.game_root) if config.game_root is not None else ()
    return EngineStatus(config.engine_root, config.game_root, engine_missing, game_missing)


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
    if not path.is_dir():
        raise ValueError(f"{label}不存在或不是目录：{path}")
    return path.resolve()


def _existing_directory(candidate: str | Path | None) -> Path | None:
    if candidate is None:
        return None
    path = Path(candidate).expanduser()
    if not path.is_dir():
        return None
    return path.resolve()


def _stored_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _first_existing(*candidates: str | Path | None) -> Path | None:
    for candidate in candidates:
        found = _existing_directory(candidate)
        if found is not None:
            return found
    return None


class EngineConfigService:
    """Resolve the effective engine configuration and persist explicit selections."""

    def __init__(
        self,
        repository: SettingsRepository,
        data_dir: Path,
        *,
        environment: Mapping[str, str] | None = None,
        runtime: EngineConfig | None = None,
    ) -> None:
        self._repository = repository
        self._data_dir = Path(data_dir)
        self._environment = os.environ if environment is None else environment
        self._runtime = EngineConfig() if runtime is None else runtime

    @property
    def runtime(self) -> EngineConfig:
        return self._runtime

    def stored(self) -> EngineConfig:
        return EngineConfig(
            engine_root=_stored_path(self._repository.get(ENGINE_KEY)),
            game_root=_stored_path(self._repository.get(GAME_KEY)),
        )

    def resolve(
        self,
        *,
        engine_root: str | Path | None = None,
        game_root: str | Path | None = None,
    ) -> EngineConfig:
        stored = self.stored()
        return EngineConfig(
            engine_root=_first_existing(
                engine_root,
                stored.engine_root,
                self._environment.get("FM27_ENGINE_ROOT"),
                self._data_dir / DEFAULT_ENGINE_DIRECTORY,
            ),
            game_root=_first_existing(
                game_root,
                stored.game_root,
                self._environment.get("FM27_GAME_ROOT"),
            ),
        )

    def status(self) -> EngineStatus:
        return describe_engine_config(self._runtime)

    def select(
        self,
        *,
        engine_root: str | Path | None = None,
        game_root: str | Path | None = None,
    ) -> EngineStatus:
        if engine_root is None and game_root is None:
            raise ValueError("至少需要提供引擎目录或游戏目录")
        selected_engine = validate_engine_root(engine_root) if engine_root is not None else self._runtime.engine_root
        selected_game = validate_game_root(game_root) if game_root is not None else self._runtime.game_root
        with self._repository.database.transaction() as connection:
            if engine_root is not None:
                self._repository.set(ENGINE_KEY, str(selected_engine), connection=connection, note="引擎目录")
            if game_root is not None:
                self._repository.set(GAME_KEY, str(selected_game), connection=connection, note="游戏目录")
        return describe_engine_config(EngineConfig(selected_engine, selected_game))
