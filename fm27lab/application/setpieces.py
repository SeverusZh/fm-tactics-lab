"""定位球应用服务：目录、编辑值校验、持久化与 JSON 文档导入导出。"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets, load_scenario_assets
from fm27lab.application.settings import SettingsService
from fm27lab.config import Settings
from fm27lab.domain import setpieces as domain

SETPIECE_IDS: tuple[str, ...] = ("home", "away")
SIDE_BY_ID: dict[str, int] = {"home": 0, "away": 1}
TEAM_BY_SIDE: dict[int, str] = {0: "主队", 1: "客队"}
SETTING_KEY_PREFIX = "setpieces."
DOCUMENT_SCHEMA = "fm27-setpiece-document-v1"
MAX_DOCUMENT_BYTES = 256 * 1024
DOCUMENT_FIELDS = frozenset({"schema", "setpiece_id", "value"})
ENGINE_UNAVAILABLE_CODE = "engine_unavailable"
ENGINE_UNAVAILABLE_MESSAGE = "引擎资源未配置，无法编辑定位球；请在设置页配置引擎目录与游戏目录"
UNKNOWN_SETPIECE_MESSAGE = "定位球条目不存在"
DOCUMENT_TEXT_ERROR = "定位球文档不是合法的 UTF-8 文本"
DOCUMENT_JSON_ERROR = "定位球文档不是合法的 JSON"
DOCUMENT_FORMAT_ERROR = "定位球文档格式错误"
DOCUMENT_SCHEMA_ERROR = "定位球文档版本不受支持"
DOCUMENT_TARGET_ERROR = "定位球文档的 setpiece_id 与目标不一致"
DOCUMENT_VALUE_ERROR = "定位球文档缺少 value 字段"
DOCUMENT_FIELDS_ERROR = "定位球文档包含未知字段"
DOCUMENT_SIZE_ERROR = "定位球文档超过 256 KiB 上限"


class SetpiecesUnavailable(RuntimeError):
    """原生引擎资源不可用，无法读取定位球目录。"""


class UnknownSetpiece(LookupError):
    """请求的定位球条目不在 home 与 away 之内。"""


def setting_key(setpiece_id: str) -> str:
    return SETTING_KEY_PREFIX + setpiece_id


class SetpiecesService:
    """读取、校验并使用设置键空间保存定位球配置，同时交换 JSON 文档。"""

    def __init__(
        self,
        settings_service: SettingsService,
        settings: Settings | None = None,
        *,
        assets: ScenarioAssets | None = None,
        assets_loader: Callable[[Path], ScenarioAssets] = load_scenario_assets,
    ) -> None:
        self.settings_service = settings_service
        self.settings = settings
        self._assets = assets
        self._assets_loader = assets_loader
        self._unavailable = False

    def assets(self) -> ScenarioAssets:
        if self._assets is not None:
            return self._assets
        if self._unavailable or self.settings is None or self.settings.engine_root is None:
            raise SetpiecesUnavailable(ENGINE_UNAVAILABLE_MESSAGE)
        try:
            self._assets = self._assets_loader(self.settings.engine_root)
        except (ValueError, OSError) as error:
            self._unavailable = True
            raise SetpiecesUnavailable(ENGINE_UNAVAILABLE_MESSAGE) from error
        return self._assets

    def catalog(self) -> dict[str, Any]:
        return copy.deepcopy(self.assets().setpiece_catalog)

    def default_value(self, setpiece_id: str) -> dict[str, Any]:
        side = self._require_side(setpiece_id)
        return copy.deepcopy(self.assets().setpiece_defaults[side])

    def list(self) -> dict[str, Any]:
        assets = self.assets()
        items: list[dict[str, Any]] = []
        for setpiece_id in SETPIECE_IDS:
            entry = self.settings_service.get(setting_key(setpiece_id))
            items.append(
                {
                    "setpiece_id": setpiece_id,
                    "team": TEAM_BY_SIDE[SIDE_BY_ID[setpiece_id]],
                    "side": SIDE_BY_ID[setpiece_id],
                    "configured": entry is not None,
                    "updated_at": None if entry is None else entry["updated_at"],
                }
            )
        return {"catalog": copy.deepcopy(assets.setpiece_catalog), "setpieces": items}

    def get(self, setpiece_id: str) -> dict[str, Any]:
        side = self._require_side(setpiece_id)
        assets = self.assets()
        default = copy.deepcopy(assets.setpiece_defaults[side])
        entry = self.settings_service.get(setting_key(setpiece_id))
        value = default if entry is None else self._normalized(setpiece_id, entry["value"], default)
        return {
            "setpiece_id": setpiece_id,
            "team": TEAM_BY_SIDE[side],
            "side": side,
            "configured": entry is not None,
            "updated_at": None if entry is None else entry["updated_at"],
            "roster_size": self.roster_size(side),
            "players": self.players(side),
            "value": copy.deepcopy(value),
            "default": copy.deepcopy(default),
        }

    def save(self, setpiece_id: str, value: Any) -> dict[str, Any]:
        default = self.default_value(setpiece_id)
        normalized = self._normalized(setpiece_id, value, default)
        self.settings_service.set(setting_key(setpiece_id), normalized)
        return self.get(setpiece_id)

    def export_document(self, setpiece_id: str) -> tuple[bytes, str]:
        detail = self.get(setpiece_id)
        document = {
            "schema": DOCUMENT_SCHEMA,
            "setpiece_id": setpiece_id,
            "value": detail["value"],
        }
        payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return payload, f"setpieces-{setpiece_id}.json"

    def import_document(self, setpiece_id: str, payload: bytes) -> dict[str, Any]:
        document = parse_document(payload)
        target = document.get("setpiece_id")
        if target is not None and target != setpiece_id:
            raise ValueError(DOCUMENT_TARGET_ERROR)
        return self.save(setpiece_id, document["value"])

    def roster_size(self, side: int) -> int:
        return len(self.assets().default_teams[side]["players"])

    def players(self, side: int) -> list[dict[str, Any]]:
        rows = self.assets().default_teams[side]["players"]
        return [
            {"index": index, "name": str(player.get("name") or f"球员 {index + 1}")}
            for index, player in enumerate(rows)
        ]

    def _normalized(self, setpiece_id: str, value: Any, default: Mapping[str, Any]) -> dict[str, Any]:
        side = self._require_side(setpiece_id)
        assets = self.assets()
        return domain.normalize(
            value,
            side,
            self.roster_size(side),
            enums=assets.setpiece_enums,
            default_value=default,
        )

    def _require_side(self, setpiece_id: str) -> int:
        side = SIDE_BY_ID.get(setpiece_id)
        if side is None:
            raise UnknownSetpiece(UNKNOWN_SETPIECE_MESSAGE)
        return side


def parse_document(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ValueError(DOCUMENT_SIZE_ERROR)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(DOCUMENT_TEXT_ERROR) from None
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(DOCUMENT_JSON_ERROR) from None
    if not isinstance(document, Mapping):
        raise ValueError(DOCUMENT_FORMAT_ERROR)
    unknown = sorted({str(key) for key in document} - DOCUMENT_FIELDS)
    if unknown:
        raise ValueError(f"{DOCUMENT_FIELDS_ERROR}：{'、'.join(unknown)}")
    schema = document.get("schema")
    if schema is not None and schema != DOCUMENT_SCHEMA:
        raise ValueError(DOCUMENT_SCHEMA_ERROR)
    target = document.get("setpiece_id")
    if target is not None and not isinstance(target, str):
        raise ValueError(DOCUMENT_FORMAT_ERROR)
    if "value" not in document:
        raise ValueError(DOCUMENT_VALUE_ERROR)
    return dict(document)
