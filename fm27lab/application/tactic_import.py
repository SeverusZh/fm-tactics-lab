"""原生战术解析结果到场景文档的映射。"""

from __future__ import annotations

from typing import Any

from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets
from fm27lab.adapters.engine_native.scenario_codec import defaults, validate_scenario
from fm27lab.adapters.engine_native.tactic_file import TacticCell, TacticPlan

GROUP_CONFLICT_ERROR = "源战术含不能无损表示的同组指令"
MAPPING_ERROR = "源战术双阶段对应关系无效"
UNMAPPED_ERROR = "源战术包含尚未映射的位置或角色"
PERSONAL_UNKNOWN_ERROR = "源战术包含尚未映射的个人指令，不静默丢弃"
PERSONAL_CONFLICT_ERROR = "源战术含不能无损表示的同组个人指令"
MAX_TACTIC_NAME_CHARS = 120
PHASE_COUNT = 2
SLOTS = 11

__all__ = ["build_scenario"]


def build_scenario(
    assets: ScenarioAssets,
    plan: TacticPlan,
    *,
    tactic_name: str | None = None,
) -> dict[str, Any]:
    scenario = defaults(assets)
    team = scenario["teams"][0]
    team["mentality"] = plan.mentality
    team["native_extra_team_bits"] = str(plan.team_bits & ~assets.team_known_mask)
    team["instructions"] = _team_instructions(assets, plan.team_bits)
    team["phases"] = _phases(assets, plan)
    name = plan.name if tactic_name is None else tactic_name
    team["tactic_name"] = name[:MAX_TACTIC_NAME_CHARS]
    for squad in scenario["teams"]:
        for player in squad["players"]:
            player["source_uid"] = player["native_id"]
    validate_scenario(assets, scenario)
    return scenario


def _team_instructions(assets: ScenarioAssets, bits: int) -> dict[str, int]:
    instructions: dict[str, int] = {}
    for group in assets.groups.values():
        options = group["options"]
        active = [
            option["id"]
            for option in options
            if option.get("native_bit") and bits >> option["native_bit"] & 1
        ]
        if len(active) > 1:
            raise ValueError(GROUP_CONFLICT_ERROR)
        if active:
            instructions[str(group["id"])] = active[0]
            continue
        fallback = next((option["id"] for option in options if not option.get("native_bit")), None)
        instructions[str(group["id"])] = fallback if fallback is not None else options[0]["id"]
    return instructions


def _phases(assets: ScenarioAssets, plan: TacticPlan) -> list[list[dict[str, Any]]]:
    mapping = [index if value == 255 else value for index, value in enumerate(plan.mapping)]
    if sorted(mapping) != list(range(SLOTS)):
        raise ValueError(MAPPING_ERROR)
    known = _known_personal_bits(assets)
    phases: list[list[dict[str, Any]]] = []
    for phase in range(PHASE_COUNT):
        cells = [
            _cell(assets, phase, plan.phases[phase][mapping[index] if phase else index], known)
            for index in range(SLOTS)
        ]
        phases.append(cells)
    return phases


def _cell(
    assets: ScenarioAssets,
    phase: int,
    cell: TacticCell,
    known: int,
) -> dict[str, Any]:
    position = next(
        (item["id"] for item in assets.positions.values() if item["mask"] == cell.position),
        None,
    )
    role = next(
        (
            item["id"]
            for item in assets.roles.values()
            if item["phase"] == phase and int(item["flags"]) == cell.role_flags & assets.role_mask
        ),
        None,
    )
    if position is None or role is None:
        raise ValueError(UNMAPPED_ERROR)
    if cell.pi_flags & ~known:
        raise ValueError(PERSONAL_UNKNOWN_ERROR)
    if _personal_conflict(assets, cell.pi_flags):
        raise ValueError(PERSONAL_CONFLICT_ERROR)
    return {
        "position": position,
        "role": role,
        "duty": str(cell.role_flags & ~assets.role_mask),
        "instructions": _personal_instructions(assets, cell.pi_flags),
        "target_player": cell.target_player,
        "target_position": cell.target_position,
    }


def _known_personal_bits(assets: ScenarioAssets) -> int:
    return sum(
        1 << option_id
        for option_id in {
            option["id"] for group in assets.pis.values() for option in group["options"] if option["id"]
        }
    )


def _personal_conflict(assets: ScenarioAssets, flags: int) -> bool:
    for group in assets.pis.values():
        hits = sum(1 for option in group["options"] if option["id"] and flags >> option["id"] & 1)
        if hits > 1:
            return True
    return False


def _personal_instructions(assets: ScenarioAssets, flags: int) -> dict[str, int]:
    return {
        str(group["id"]): next(
            (option["id"] for option in group["options"] if option["id"] and flags >> option["id"] & 1),
            0,
        )
        for group in assets.pis.values()
    }
