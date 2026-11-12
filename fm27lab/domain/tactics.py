"""Catalog snapshot and two-phase tactic validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PHASE_COUNT = 2
SLOTS = 11


@dataclass(frozen=True)
class Position:
    id: str
    mask: int
    x: float
    y: float


@dataclass(frozen=True)
class Role:
    id: str
    label: str
    phase: int
    flags: str


@dataclass(frozen=True)
class Catalog:
    positions: tuple[Position, ...]
    roles: tuple[Role, ...]
    duties: tuple[str, ...]
    eligibility: Mapping[tuple[str, int], frozenset[str]]
    eligibility_context: Mapping[tuple[str, str, int], frozenset[str]]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Catalog:
        if not isinstance(value, Mapping):
            raise ValueError("catalog 格式无效")
        raw_positions = value.get("positions")
        if not isinstance(raw_positions, list) or not raw_positions:
            raise ValueError("catalog 位置列表无效")
        positions: list[Position] = []
        seen_positions: set[str] = set()
        for item in raw_positions:
            if (
                not isinstance(item, Mapping)
                or not isinstance(item.get("id"), str)
                or "mask" not in item
                or "x" not in item
                or "y" not in item
            ):
                raise ValueError("catalog 位置格式无效")
            position_id = item["id"]
            if position_id in seen_positions:
                raise ValueError("catalog 位置重复")
            seen_positions.add(position_id)
            positions.append(
                Position(
                    position_id,
                    _integer(item["mask"], 0, 0xFFFFFFFF, "位置 mask"),
                    _number(item["x"], "位置 x"),
                    _number(item["y"], "位置 y"),
                )
            )
        raw_roles = value.get("roles")
        if not isinstance(raw_roles, list) or not raw_roles:
            raise ValueError("catalog 角色列表无效")
        roles: list[Role] = []
        seen_roles: set[str] = set()
        for item in raw_roles:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                raise ValueError("catalog 角色格式无效")
            role_id = item["id"]
            if role_id in seen_roles:
                raise ValueError("catalog 角色重复")
            seen_roles.add(role_id)
            phase = _integer(item.get("phase"), 0, PHASE_COUNT - 1, "角色阶段")
            flags = item.get("flags", "0")
            if not isinstance(flags, str) or not flags.isascii() or not flags.isdigit():
                raise ValueError("catalog 角色 flags 无效")
            roles.append(Role(role_id, str(item.get("label") or role_id), phase, flags))
        raw_duties = value.get("duties")
        if (
            not isinstance(raw_duties, list)
            or not raw_duties
            or any(
                not isinstance(item, str) or not item.isascii() or not item.isdigit() for item in raw_duties
            )
        ):
            raise ValueError("catalog 职责列表无效")
        duties = tuple(raw_duties)
        if len(set(duties)) != len(duties):
            raise ValueError("catalog 职责重复")
        raw_eligibility = value.get("role_eligibility")
        if not isinstance(raw_eligibility, Mapping) or not raw_eligibility:
            raise ValueError("catalog 角色资格无效")
        role_phases = {role.id: role.phase for role in roles}
        eligibility: dict[tuple[str, int], frozenset[str]] = {}
        for position_id, phases in raw_eligibility.items():
            if position_id not in seen_positions:
                raise ValueError("catalog 角色资格包含未知位置")
            if not isinstance(phases, (list, tuple)) or len(phases) != PHASE_COUNT:
                raise ValueError("catalog 角色资格必须包含两个阶段")
            for phase, role_ids in enumerate(phases):
                if not isinstance(role_ids, (list, tuple)):
                    raise ValueError("catalog 角色资格格式无效")
                for role_id in role_ids:
                    if not isinstance(role_id, str) or role_id not in role_phases:
                        raise ValueError("catalog 角色资格包含未知角色")
                    if role_phases[role_id] != phase:
                        raise ValueError("catalog 角色资格阶段不一致")
                eligibility[(position_id, phase)] = frozenset(role_ids)
        raw_context = value.get("role_eligibility_context", {})
        if not isinstance(raw_context, Mapping):
            raise ValueError("catalog 角色资格上下文无效")
        if raw_context:
            required_contexts = {"0:0", "0:1", "3:0", "3:1"}
            if set(raw_context) != required_contexts:
                raise ValueError("catalog 角色资格上下文必须包含四个桶")
            for positions_map in raw_context.values():
                if not isinstance(positions_map, Mapping) or set(positions_map) != seen_positions:
                    raise ValueError("catalog 角色资格上下文必须覆盖全部位置")
        context_eligibility: dict[tuple[str, str, int], frozenset[str]] = {}
        for context_key, positions_map in raw_context.items():
            if not isinstance(context_key, str) or not isinstance(positions_map, Mapping):
                raise ValueError("catalog 角色资格上下文无效")
            for position_id, phases in positions_map.items():
                if (
                    position_id not in seen_positions
                    or not isinstance(phases, (list, tuple))
                    or len(phases) != PHASE_COUNT
                ):
                    raise ValueError("catalog 角色资格上下文无效")
                for phase, role_ids in enumerate(phases):
                    if not isinstance(role_ids, (list, tuple)):
                        raise ValueError("catalog 角色资格上下文无效")
                    for role_id in role_ids:
                        if not isinstance(role_id, str) or role_id not in role_phases:
                            raise ValueError("catalog 角色资格上下文包含未知角色")
                        if role_phases[role_id] != phase:
                            raise ValueError("catalog 角色资格上下文阶段不一致")
                    context_eligibility[(context_key, position_id, phase)] = frozenset(role_ids)
        return cls(tuple(positions), tuple(roles), duties, eligibility, context_eligibility)

    def position(self, position_id: str) -> Position:
        for item in self.positions:
            if item.id == position_id:
                return item
        raise ValueError("未知位置：" + position_id)

    def role(self, role_id: str) -> Role:
        for item in self.roles:
            if item.id == role_id:
                return item
        raise ValueError("未知角色：" + role_id)

    def allowed(self, position_id: str, phase: int, role_id: str, context: str | None = None) -> bool:
        if self.eligibility_context:
            if context is None:
                raise ValueError("战术角色资格缺少上下文")
            return role_id in self.eligibility_context.get((context, position_id, phase), frozenset())
        return role_id in self.eligibility.get((position_id, phase), frozenset())


def _integer(value: Any, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(label + "无效")
    return value


def _number(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not 0 <= value <= 100:
        raise ValueError(label + "无效")
    return float(value)


def _instructions(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("个人指令格式无效")
    result: dict[str, int] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key.isascii()
            or not key.isdigit()
            or type(item) is not int
            or not 0 <= item <= 0xFFFFFFFF
        ):
            raise ValueError("个人指令格式无效")
        result[str(int(key))] = item
    return result


def _context(cells: Sequence[Any], catalog: Catalog) -> str:
    defenders = 0
    holding = 0
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise ValueError("战术位置格式无效")
        position = cell.get("position")
        if not isinstance(position, str):
            raise ValueError("战术位置名称无效")
        value = catalog.position(position)
        if value.mask & 16:
            defenders += 1
        if value.mask & 128:
            holding += 1
    return f"{3 if defenders >= 3 else 0}:{1 if holding == 1 else 0}"


def _cell(value: Any, phase: int, catalog: Catalog, context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("战术位置格式无效")
    position = value.get("position")
    role = value.get("role")
    duty = value.get("duty")
    if not isinstance(position, str):
        raise ValueError("战术位置名称无效")
    catalog.position(position)
    if not isinstance(role, str):
        raise ValueError("战术角色名称无效")
    role_value = catalog.role(role)
    if role_value.phase != phase:
        raise ValueError("战术角色与阶段不一致")
    if not catalog.allowed(position, phase, role, context):
        raise ValueError("战术角色不具备该位置资格")
    if not isinstance(duty, str) or duty not in catalog.duties:
        raise ValueError("战术职责无效")
    target_player = _integer(value.get("target_player", 255), 0, 255, "盯防球员")
    target_position = _integer(value.get("target_position", 0), 0, 0xFFFFFFFFFFFFFFFF, "盯防位置")
    return {
        "position": position,
        "role": role,
        "duty": duty,
        "instructions": _instructions(value.get("instructions", {})),
        "target_player": target_player,
        "target_position": target_position,
    }


def validate_phases(value: Any, catalog: Catalog) -> tuple[tuple[dict[str, Any], ...], ...]:
    if not isinstance(value, (list, tuple)) or len(value) != PHASE_COUNT:
        raise ValueError("战术必须包含两个阶段")
    result: list[tuple[dict[str, Any], ...]] = []
    for phase, cells in enumerate(value):
        if not isinstance(cells, (list, tuple)) or len(cells) != SLOTS:
            raise ValueError("每个战术阶段必须有 11 个位置")
        context = _context(cells, catalog)
        result.append(tuple(_cell(cell, phase, catalog, context) for cell in cells))
    return tuple(result)
