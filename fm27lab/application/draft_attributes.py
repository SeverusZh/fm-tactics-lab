"""Draft attribute batch editing service."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from fm27lab.application.drafts import DraftService
from fm27lab.domain.attributes import (
    ATTRIBUTE_COUNT,
    apply_attribute_cells,
    apply_bulk_attributes,
    apply_position_attributes,
    copy_player_profile,
    pair_feet,
    undo_bulk,
)

SIDES: dict[str, int] = {"home": 0, "away": 1}
SCOPES: tuple[str, ...] = ("all", "starters", "player", "squad")
OPERATIONS: tuple[str, ...] = ("bulk", "position", "cells", "copy", "pair_feet", "undo")
SNAPSHOT_KEY = "attribute_snapshot"


def _valid_uid(uid: Any) -> bool:
    if type(uid) not in (int, str):
        return False
    if isinstance(uid, str):
        return bool(uid.strip()) and uid == uid.strip() and not any(ord(char) < 32 for char in uid)
    return True


_PARAMETERS: dict[str, frozenset[str]] = {
    "bulk": frozenset({"value", "groups", "include_personality"}),
    "position": frozenset({"position", "value"}),
    "cells": frozenset({"values"}),
    "copy": frozenset({"source_uid", "source_index", "groups", "copy_personality"}),
    "pair_feet": frozenset({"left_index", "right_index", "preferred", "preferred_value", "weaker_value"}),
}
_REQUIRED: dict[str, tuple[str, ...]] = {
    "bulk": ("value",),
    "position": ("position", "value"),
    "cells": ("values",),
    "pair_feet": ("left_index", "right_index", "preferred", "preferred_value", "weaker_value"),
}


class DraftAttributeService:
    def __init__(self, drafts: DraftService):
        self.drafts = drafts

    def apply(
        self,
        draft_id: str,
        *,
        side: str,
        scope: str,
        player_index: int | None,
        operation: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        draft = self.drafts.get(draft_id)
        if draft is None:
            return None
        self._validate_operation(operation)
        if not isinstance(params, Mapping):
            raise ValueError("属性参数必须是对象")
        team = self._team(draft["scenario"], side)
        all_players = self._team_players(team)
        if operation == "undo":
            return self._undo(draft_id, draft, side, all_players, params)
        selected = self._select(team, all_players, scope, player_index)
        snapshot, changed = self._apply_operation(operation, all_players, selected, params)
        snapshot = {"side": side, "scope": scope, "operation": operation, **snapshot}
        source = dict(draft["source"])
        source[SNAPSHOT_KEY] = snapshot
        updated = self.drafts.update(draft_id, scenario=draft["scenario"], source=source)
        if updated is None:
            return None
        return {
            "draft": self._summary(updated),
            "snapshot": copy.deepcopy(snapshot),
            "changed_players": changed,
        }

    def _apply_operation(
        self,
        operation: str,
        all_players: Sequence[dict[str, Any]],
        selected: list[dict[str, Any]],
        params: Mapping[str, Any],
    ) -> tuple[dict[str, Any], int]:
        if operation == "bulk":
            kwargs = self._operation_params(operation, params)
            return self._bulk(selected, kwargs)
        if operation == "position":
            kwargs = self._operation_params(operation, params)
            return self._position(selected, kwargs)
        if operation == "cells":
            kwargs = self._operation_params(operation, params)
            return self._cells(selected, kwargs)
        if operation == "copy":
            return self._copy(all_players, selected, params)
        return self._pair_feet(selected, params)

    @staticmethod
    def _bulk(
        selected: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        before = copy.deepcopy(selected)
        snapshot = apply_bulk_attributes(selected, **kwargs)
        return snapshot, _changed_count(before, selected)

    @staticmethod
    def _position(
        selected: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        before = copy.deepcopy(selected)
        snapshot = apply_position_attributes(selected, **kwargs)
        return snapshot, _changed_count(before, selected)

    @staticmethod
    def _cells(
        selected: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        values = _cell_values(kwargs["values"])
        before = copy.deepcopy(selected)
        snapshot = apply_attribute_cells(selected, values=values)
        return snapshot, _changed_count(before, selected)

    def _copy(
        self,
        all_players: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        params: Mapping[str, Any],
    ) -> tuple[dict[str, Any], int]:
        kwargs = self._operation_params("copy", params)
        source = self._reference_player(all_players, kwargs)
        before = copy.deepcopy(selected)
        snapshots = [copy_player_profile(source, target, **kwargs) for target in selected]
        snapshot = {
            "indices": snapshots[0]["indices"],
            "include_personality": snapshots[0]["include_personality"],
            "players": [entry for item in snapshots for entry in item["players"]],
        }
        return snapshot, _changed_count(before, selected)

    @staticmethod
    def _reference_player(
        all_players: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        has_uid = "source_uid" in kwargs
        has_index = "source_index" in kwargs
        if has_uid and has_index:
            raise ValueError("source_uid 与 source_index 只能提供其一")
        if has_index:
            index = kwargs.pop("source_index")
            if type(index) is not int or not 0 <= index < len(all_players):
                raise ValueError(f"参考球员索引必须是 0–{len(all_players) - 1} 的整数")
            return all_players[index]
        if not has_uid:
            raise ValueError("copy 操作必须提供 source_uid 或 source_index")
        source_uid = kwargs.pop("source_uid")
        if not _valid_uid(source_uid):
            raise ValueError("参考球员标识无效")
        for player in all_players:
            if player.get("source_uid") == source_uid:
                return player
        raise ValueError("参考球员不存在")

    @staticmethod
    def _pair_feet(
        selected: list[dict[str, Any]],
        params: Mapping[str, Any],
    ) -> tuple[dict[str, Any], int]:
        kwargs = DraftAttributeService._operation_params("pair_feet", params)
        # 先逐名球员试运行，确保参数与所有目标球员在写入快照前就通过领域校验。
        for target in selected:
            pair_feet(copy.deepcopy(target), **kwargs)
        indices = sorted({kwargs["left_index"], kwargs["right_index"]})
        before = copy.deepcopy(selected)
        players = [
            {
                "source_uid": target.get("source_uid"),
                "profile_present": target.get("native_profile") is not None,
                "attributes": [target["attributes"][index] for index in indices],
                "personality": {},
            }
            for target in before
        ]
        for target in selected:
            pair_feet(target, **kwargs)
        snapshot = {"indices": indices, "include_personality": False, "players": players}
        return snapshot, _changed_count(before, selected)

    def _undo(
        self,
        draft_id: str,
        draft: dict[str, Any],
        side: str,
        all_players: list[dict[str, Any]],
        params: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if params:
            raise ValueError("undo 操作不接受参数")
        snapshot = dict(draft["source"]).get(SNAPSHOT_KEY)
        if not isinstance(snapshot, Mapping):
            raise ValueError("没有可撤销的属性修改")
        if snapshot.get("side") != side:
            raise ValueError("撤销记录的队伍与请求不一致")
        entries = snapshot.get("players")
        if not isinstance(entries, list) or any(not isinstance(entry, Mapping) for entry in entries):
            raise ValueError("撤销记录格式无效")
        mapping: dict[int | str, dict[str, Any]] = {}
        for player in all_players:
            uid = player.get("source_uid")
            if type(uid) in (int, str):
                mapping[uid] = player
        restored: list[dict[str, Any]] = []
        for entry in entries:
            uid = entry.get("source_uid")
            if type(uid) not in (int, str) or uid not in mapping:
                raise ValueError("名单已变化，无法撤销")
            restored.append(mapping[uid])
        before = copy.deepcopy(restored)
        undo_bulk(restored, snapshot)
        source = dict(draft["source"])
        source.pop(SNAPSHOT_KEY, None)
        updated = self.drafts.update(draft_id, scenario=draft["scenario"], source=source)
        if updated is None:
            return None
        return {
            "draft": self._summary(updated),
            "snapshot": None,
            "changed_players": _changed_count(before, restored),
        }

    @staticmethod
    def _operation_params(operation: str, params: Mapping[str, Any]) -> dict[str, Any]:
        allowed = _PARAMETERS[operation]
        unknown = set(params) - allowed
        if unknown:
            raise ValueError("不支持的参数：" + "、".join(sorted(str(name) for name in unknown)))
        for name in _REQUIRED.get(operation, ()):
            if name not in params:
                raise ValueError(f"{operation} 操作缺少 {name}")
        return {name: params[name] for name in allowed if name in params}

    @staticmethod
    def _validate_operation(operation: str) -> None:
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise ValueError("未知属性操作")

    @staticmethod
    def _team(scenario: Any, side: str) -> dict[str, Any]:
        teams = scenario.get("teams") if isinstance(scenario, Mapping) else None
        if (
            not isinstance(teams, list)
            or len(teams) != 2
            or any(not isinstance(team, Mapping) for team in teams)
        ):
            raise ValueError("草稿场景无效")
        if not isinstance(side, str) or side not in SIDES:
            raise ValueError("side 必须是 home 或 away")
        return teams[SIDES[side]]

    @staticmethod
    def _team_players(team: Mapping[str, Any]) -> list[dict[str, Any]]:
        players = team.get("players")
        if not isinstance(players, list) or any(not isinstance(player, Mapping) for player in players):
            raise ValueError("草稿球队球员名单无效")
        return players

    def _select(
        self,
        team: Mapping[str, Any],
        all_players: list[dict[str, Any]],
        scope: str,
        player_index: int | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(scope, str) or scope not in SCOPES:
            raise ValueError("scope 必须是 all、starters、player 或 squad")
        if scope == "player":
            if player_index is None:
                raise ValueError("player 范围必须提供 player_index")
            if type(player_index) is not int or not 0 <= player_index < len(all_players):
                raise ValueError(f"球员索引必须是 0–{len(all_players) - 1} 的整数")
            selected = [all_players[player_index]]
        elif player_index is not None:
            raise ValueError("player_index 仅用于 player 范围")
        elif scope == "all":
            selected = list(all_players)
        elif scope == "squad":
            selected = [player for player in all_players if "attributes" in player] or list(all_players)
        else:
            selected = self._starters(team, all_players)
        if not selected:
            raise ValueError("没有可编辑的球员")
        return selected

    @staticmethod
    def _starters(team: Mapping[str, Any], all_players: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lineup = team.get("lineup")
        if not isinstance(lineup, list):
            raise ValueError("球队首发列表格式无效")
        selected: list[dict[str, Any]] = []
        for index in lineup:
            if type(index) is not int or not 0 <= index < len(all_players):
                raise ValueError("首发名单索引无效")
            selected.append(all_players[index])
        return selected

    @staticmethod
    def _summary(draft: Mapping[str, Any]) -> dict[str, Any]:
        return {key: draft[key] for key in ("id", "name", "source", "created_at", "updated_at")}


def _changed_count(before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for old, new in zip(before, after, strict=True) if old != new)


def _cell_values(raw: Any) -> dict[int, float]:
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Mapping):
        raise ValueError("values 必须是属性索引到显示值的对象")
    values: dict[int, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not (key.isascii() and key.isdigit()):
            raise ValueError("values 的键必须是 0–68 的规范十进制字符串")
        index = int(key)
        if not 0 <= index < ATTRIBUTE_COUNT or key != str(index):
            raise ValueError("values 的键必须是 0–68 的规范十进制字符串")
        values[index] = value
    return values
