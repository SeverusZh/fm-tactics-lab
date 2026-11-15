"""存档战术库：列出存档内战术，并把选中的战术导入为草案。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets, load_scenario_assets
from fm27lab.adapters.engine_native.tactic_file import (
    UNCONFIGURED_ERROR,
    TacticFileError,
    TacticPlan,
    parse_tactic_stream,
)
from fm27lab.adapters.save_fmsave.tactics import StoredTactic, read_tactic_stream, read_tactics
from fm27lab.application.drafts import DraftService
from fm27lab.application.saves import SavesService
from fm27lab.application.source_paths import clean_path_text
from fm27lab.application.tactic_import import build_scenario
from fm27lab.config import Settings

SAVE_MISSING_ERROR = "存档文件不可用，请重新导入存档"
SAVE_UNREADABLE_ERROR = "存档无法读取"
TACTIC_MISSING_ERROR = "存档战术不存在"
TACTIC_TEAM_ERROR = "该战术不是一线队存储战术，不能导入"
TACTIC_STREAM_ERROR = "存档战术数据不完整，不能导入"
ENGINE_UNAVAILABLE_MESSAGE = "引擎资源未配置，无法导入存档战术；请在设置页配置引擎目录与游戏目录"
FIRST_TEAM_SLOT = 0
MAX_NAME_CHARS = 80
FALLBACK_NAME = "导入战术"
MAX_CACHE_ENTRIES = 8
SAVE_TACTIC_SOURCE = "save_tactic"

Reader = Callable[[Path], tuple[StoredTactic, ...]]
StreamReader = Callable[..., bytes | None]
Parser = Callable[..., TacticPlan]
AssetsLoader = Callable[[Path], ScenarioAssets]
Builder = Callable[..., dict[str, Any]]


class SaveTacticsService:
    """存档战术列表与导入；列表按存档大小与修改时间缓存。"""

    def __init__(
        self,
        saves: SavesService,
        drafts: DraftService,
        settings: Settings | None = None,
        *,
        reader: Reader = read_tactics,
        stream_reader: StreamReader = read_tactic_stream,
        parser: Parser = parse_tactic_stream,
        assets_loader: AssetsLoader = load_scenario_assets,
        builder: Builder = build_scenario,
    ) -> None:
        self.saves = saves
        self.drafts = drafts
        self.settings = settings
        self.reader = reader
        self.stream_reader = stream_reader
        self.parser = parser
        self.assets_loader = assets_loader
        self.builder = builder
        self._cache: dict[str, tuple[tuple[Any, ...], tuple[dict[str, Any], ...]]] = {}

    def engine_ready(self) -> bool:
        return (
            self.settings is not None
            and self.settings.engine_root is not None
            and self.settings.game_root is not None
        )

    def list_tactics(self, save_id: str) -> list[dict[str, Any]] | None:
        save = self.saves.get(save_id)
        if save is None:
            return None
        return self._items(save_id, self._source_path(save))

    def import_tactic(
        self,
        save_id: str,
        tactic_index: int,
        name: str | None = None,
    ) -> dict[str, Any] | None:
        save = self.saves.get(save_id)
        if save is None:
            return None
        path = self._source_path(save)
        items = self._items(save_id, path)
        item = next((entry for entry in items if entry["index"] == tactic_index), None)
        if item is None:
            raise ValueError(TACTIC_MISSING_ERROR)
        if item["team_slot"] != FIRST_TEAM_SLOT:
            raise ValueError(TACTIC_TEAM_ERROR)
        engine_root, game_root = self._roots()
        payload = self._stream(path, tactic_index)
        if not payload:
            raise ValueError(TACTIC_STREAM_ERROR)
        plan = self.parser(payload, name=item["name"], engine_root=engine_root, game_root=game_root)
        scenario = self.builder(
            self.assets_loader(engine_root),
            plan,
            tactic_name=item["name"],
        )
        source = {"kind": SAVE_TACTIC_SOURCE, "save_id": save_id, "tactic_index": tactic_index}
        return self.drafts.create(self._draft_name(name, item["name"]), scenario, source)

    def _items(self, save_id: str, path: Path) -> list[dict[str, Any]]:
        key = self._signature(path)
        ready = self.engine_ready()
        cached = self._cache.get(save_id)
        if cached is not None and cached[0] == (key, ready):
            return [dict(item) for item in cached[1]]
        items = tuple(self._load(path, ready))
        self._cache[save_id] = ((key, ready), items)
        self._trim()
        return [dict(item) for item in items]

    def _load(self, path: Path, ready: bool) -> list[dict[str, Any]]:
        try:
            rows = self.reader(path)
        except (OSError, RuntimeError) as error:
            raise ValueError(f"{SAVE_UNREADABLE_ERROR}：{error}") from error
        return [_item(row, ready) for row in rows]

    def _stream(self, path: Path, tactic_index: int) -> bytes | None:
        try:
            return self.stream_reader(path, tactic_index)
        except (OSError, RuntimeError) as error:
            raise ValueError(f"{SAVE_UNREADABLE_ERROR}：{error}") from error

    def _trim(self) -> None:
        while len(self._cache) > MAX_CACHE_ENTRIES:
            self._cache.pop(next(iter(self._cache)))

    def _source_path(self, save: Mapping[str, Any]) -> Path:
        text = clean_path_text(save.get("source_path"))
        if text is None:
            raise ValueError(SAVE_MISSING_ERROR)
        path = Path(text)
        if not path.is_file():
            raise ValueError(SAVE_MISSING_ERROR)
        return path

    def _signature(self, path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
        except OSError as error:
            raise ValueError(SAVE_MISSING_ERROR) from error
        return (stat.st_size, stat.st_mtime_ns)

    def _roots(self) -> tuple[Path, Path]:
        engine = self.settings.engine_root if self.settings is not None else None
        game = self.settings.game_root if self.settings is not None else None
        if engine is None or game is None:
            raise TacticFileError(UNCONFIGURED_ERROR)
        return engine, game

    def _draft_name(self, name: str | None, tactic_name: str) -> str:
        for candidate in (name, tactic_name):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()[:MAX_NAME_CHARS]
        return FALLBACK_NAME


def _item(row: StoredTactic, ready: bool) -> dict[str, Any]:
    return {
        "index": row.index,
        "name": row.name,
        "style": row.style,
        "mentality": row.mentality,
        "club_uid": row.club_uid,
        "club_name": row.club_name,
        "team_slot": row.team_slot,
        "importable": bool(ready and row.has_stream and row.team_slot == FIRST_TEAM_SLOT),
    }
