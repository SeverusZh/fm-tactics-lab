"""Set-piece domain model ported from the legacy native scenario encoder."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

TYPE_NAMES = [
    "防守角球",
    "防守直接任意球",
    "防守边路任意球",
    "防守远距离任意球",
    "防守界外球",
    "进攻角球",
    "进攻直接任意球",
    "进攻边路任意球",
    "进攻远距离任意球",
    "进攻界外球",
]
ROUTINE_TYPE_COUNT = 10
ROLE_GROUP_COUNT = 8
MAX_ROUTINE_VARIANTS = 3
MAX_GROUP_TASKS = 10
THROW_STYLE_OFFSET = 0x16F0 - 0x2E0
SPECIAL_STRATEGY_PAIRS = {(5, 3), (7, 3), (7, 4), (7, 6), (8, 3), (8, 4)}
ROLE_PRIORITY_RECORD = 30
ROUTINE_RECORD = 40
ROUTINE_FIELD_RECORD = 41
ROUTINE_COMMIT_RECORD = 42
ROUTINE_TASK_RECORD = 43
ROUTINE_PRIORITY_RECORD = 44
ROUTINE_BACKUP_RECORD = 45
THROW_STYLE_RECORD = 46
ROUTINE_OPAQUE_RECORD = 47


def build_catalog(enums: Mapping[str, Any]) -> dict[str, Any]:
    """Extend the native set-piece enum catalog with UI types and frequencies."""
    catalog = {key: copy.deepcopy(value) for key, value in enums.items()}
    catalog["types"] = [
        {
            "id": kind,
            "label": name,
            "strategy_kind": (
                "corner_target"
                if kind == 5
                else "free_kick_risk"
                if kind in (6, 7, 8)
                else "defensive_line"
                if kind in (2, 3)
                else None
            ),
            "swing": kind in (5, 7),
        }
        for kind, name in enumerate(TYPE_NAMES)
    ]
    catalog["frequencies"] = [
        {"id": 0, "label": "较少 · 权重2"},
        {"id": 1, "label": "正常 · 权重5"},
        {"id": 2, "label": "较多 · 权重8"},
    ]
    return catalog


def _snapshot_hex(value: Any) -> bytes:
    try:
        return bytes.fromhex(str(value))
    except (TypeError, ValueError):
        raise ValueError("定位球快照格式无效") from None


def defaults(snapshot_team: Mapping[str, Any]) -> dict[str, Any]:
    """Build the editable set-piece structure from a native snapshot team."""
    if not isinstance(snapshot_team, Mapping):
        raise ValueError("定位球快照格式无效")
    manager = _snapshot_hex(snapshot_team.get("manager_tactical_hex"))
    if len(manager) < THROW_STYLE_OFFSET + 3:
        raise ValueError("定位球快照格式无效")
    variants = snapshot_team.get("routine_variants")
    if not isinstance(variants, list) or len(variants) != ROUTINE_TYPE_COUNT:
        raise ValueError("定位球快照格式无效")
    routines: dict[str, list[dict[str, Any]]] = {}
    for variant_group in variants:
        if not isinstance(variant_group, list) or not variant_group:
            raise ValueError("定位球快照格式无效")
        records: list[dict[str, Any]] = []
        kind: int | None = None
        for routine in variant_group:
            if not isinstance(routine, Mapping):
                raise ValueError("定位球快照格式无效")
            routine_type = routine.get("type")
            if type(routine_type) is not int or not 0 <= routine_type < ROUTINE_TYPE_COUNT:
                raise ValueError("定位球快照格式无效")
            if kind is None:
                kind = routine_type
            elif routine_type != kind:
                raise ValueError("定位球快照格式无效")
            groups: list[list[int]] = [[] for _ in range(ROLE_GROUP_COUNT)]
            try:
                for group in routine["groups"]:
                    groups[group["id"]] = list(group["values"])
                backups = [[0] * len(tasks) for tasks in groups]
                for group_id, slot, value in routine.get("backups", []):
                    backups[group_id][slot] = value
                records.append(
                    {
                        "name": f"{TYPE_NAMES[kind]} {len(records) + 1}",
                        "opaque_flags": 0,
                        "frequency": routine["frequency"],
                        "strategy": routine["strategy"],
                        "swing": routine["swing"],
                        "groups": groups,
                        "backups": backups,
                        "priority": routine["priority"],
                    }
                )
            except (KeyError, IndexError, TypeError):
                raise ValueError("定位球快照格式无效") from None
        assert kind is not None
        routines[str(kind)] = records
    if set(routines) != {str(kind) for kind in range(ROUTINE_TYPE_COUNT)}:
        raise ValueError("定位球快照格式无效")
    return {
        "routines": routines,
        "throw_styles": list(manager[THROW_STYLE_OFFSET : THROW_STYLE_OFFSET + 3]),
        "role_priorities": {str(group): [] for group in range(ROLE_GROUP_COUNT)},
    }


def _integer(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("定位球设置数值无效")
    return value


def normalize(
    value: Any,
    side: int,
    roster_size: int,
    *,
    enums: Mapping[str, Any],
    default_value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an edited set-piece document against a default snapshot value."""
    if not isinstance(value, Mapping):
        raise ValueError("定位球设置格式错误")
    allowed = enums.get("allowed") if isinstance(enums, Mapping) else None
    if not isinstance(allowed, Mapping):
        raise ValueError("定位球枚举目录无效")
    out = copy.deepcopy(dict(default_value))
    throw_styles = value.get("throw_styles")
    if not isinstance(throw_styles, list) or len(throw_styles) != 3:
        raise ValueError("界外球必须包含后场、中场和前场三种策略")
    out["throw_styles"] = [_integer(style, 0, 1) for style in throw_styles]
    priorities = value.get("role_priorities")
    if not isinstance(priorities, Mapping):
        raise ValueError("定位球设置格式错误")
    for group in range(ROLE_GROUP_COUNT):
        rows = priorities.get(str(group))
        if (
            not isinstance(rows, list)
            or len(rows) > roster_size
            or any(type(row) is not int for row in rows)
            or len(set(rows)) != len(rows)
        ):
            raise ValueError("定位球角色球员顺序无效")
        out["role_priorities"][str(group)] = [_integer(row, 0, roster_size - 1) for row in rows]
    routines = value.get("routines")
    if not isinstance(routines, Mapping):
        raise ValueError("定位球设置格式错误")
    defaults_by_kind = default_value["routines"]
    for kind in range(ROUTINE_TYPE_COUNT):
        base = defaults_by_kind[str(kind)][0]
        rows = routines.get(str(kind))
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROUTINE_VARIANTS:
            raise ValueError("每种定位球保留1–3套套路")
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping) or "name" not in row:
                raise ValueError("定位球设置格式错误")
            record: dict[str, Any] = {
                "name": str(row["name"])[:64],
                "opaque_flags": _integer(row.get("opaque_flags", 0), 0, 255),
                "frequency": _integer(row.get("frequency"), 0, 2),
            }
            for key in ("strategy", "swing"):
                if key not in row:
                    raise ValueError("定位球设置格式错误")
                candidate = row[key]
                if base[key] == 255:
                    if candidate != 255:
                        raise ValueError("该类型定位球不使用此发球策略")
                    record[key] = 255
                elif key == "strategy" and (kind, candidate) in SPECIAL_STRATEGY_PAIRS:
                    record[key] = candidate
                else:
                    record[key] = _integer(candidate, 0, 1 if key == "swing" else 2)
            priority = row.get("priority")
            if (
                not isinstance(priority, list)
                or any(type(item) is not int for item in priority)
                or sorted(priority) != sorted(base["priority"])
            ):
                raise ValueError("定位球分配顺序必须保留原版角色类别")
            record["priority"] = list(priority)
            row_groups = row.get("groups")
            row_backups = row.get("backups")
            if not isinstance(row_groups, list) or len(row_groups) != ROLE_GROUP_COUNT:
                raise ValueError("定位球任务组不完整")
            if not isinstance(row_backups, list) or len(row_backups) != ROLE_GROUP_COUNT:
                raise ValueError("定位球任务组不完整")
            record["groups"] = []
            record["backups"] = []
            for group in range(ROLE_GROUP_COUNT):
                tasks = row_groups[group]
                backups = row_backups[group]
                if not isinstance(tasks, list) or len(tasks) > MAX_GROUP_TASKS:
                    raise ValueError("定位球任务与备用任务不匹配")
                if not isinstance(backups, list) or len(backups) != len(tasks):
                    raise ValueError("定位球任务与备用任务不匹配")
                if tasks and group not in priority:
                    raise ValueError("该定位球不使用此角色类别")
                group_allowed = allowed.get(str(group))
                for task in tasks:
                    _integer(task, 0, 15)
                    if not isinstance(group_allowed, list) or task not in group_allowed:
                        raise ValueError("该定位球角色不能使用所选任务")
                record["groups"].append(list(tasks))
                record["backups"].append([_integer(backup, 0, 15) for backup in backups])
            expected = sum(len(group) for group in base["groups"])
            if sum(len(group) for group in record["groups"]) != expected:
                raise ValueError(f"{TYPE_NAMES[kind]}需要分配{expected}项任务；先移除旧任务再添加新任务")
            result.append(record)
        out["routines"][str(kind)] = result
    return out


def encode_records(
    value: Mapping[str, Any],
    side: int,
    default_value: Mapping[str, Any],
) -> list[tuple[int, int, int, int, int]]:
    """Translate an edited set-piece document into native record tuples."""
    records: list[tuple[int, int, int, int, int]] = []
    for index, style in enumerate(value["throw_styles"]):
        if style != default_value["throw_styles"][index]:
            records.append((THROW_STYLE_RECORD, side, index, 0, style))
    for group in range(ROLE_GROUP_COUNT):
        rows = value["role_priorities"][str(group)]
        if rows != default_value["role_priorities"][str(group)]:
            records.append((ROLE_PRIORITY_RECORD, side, 12 + group, 0xFFFFFFFF, 0))
            records.extend((ROLE_PRIORITY_RECORD, side, 12 + group, index, value) for index, value in enumerate(rows))
    for kind in range(ROUTINE_TYPE_COUNT):
        rows = value["routines"][str(kind)]
        if rows == default_value["routines"][str(kind)]:
            continue
        records.append((ROUTINE_RECORD, side, kind, 0, len(rows)))
        for index, row in enumerate(rows):
            slot = kind * 16 + index
            records.append((ROUTINE_FIELD_RECORD, side, slot, 0, row["frequency"]))
            records.append((ROUTINE_OPAQUE_RECORD, side, slot, 0, row.get("opaque_flags", 0)))
            if row["strategy"] != 255:
                records.append((ROUTINE_FIELD_RECORD, side, slot, 1, row["strategy"]))
            if row["swing"] != 255:
                records.append((ROUTINE_FIELD_RECORD, side, slot, 2, row["swing"]))
            records.append((ROUTINE_COMMIT_RECORD, side, slot, 0, 0))
            for group in row["priority"]:
                records.extend(
                    (ROUTINE_TASK_RECORD, side, slot, group, task) for task in row["groups"][group]
                )
            records.extend(
                (ROUTINE_PRIORITY_RECORD, side, slot, index, group)
                for index, group in enumerate(row["priority"])
            )
            for group, tasks in enumerate(row["groups"]):
                records.extend(
                    (ROUTINE_BACKUP_RECORD, side, slot, group * 32 + index, row["backups"][group][index])
                    for index in range(len(tasks))
                )
    return records
