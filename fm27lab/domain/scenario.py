"""Scenario normalization and legacy phase plan upgrades."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .roster import MATCH_ROSTER_SIZE, normalize_roster

NATIVE_SCHEMA = 3
PHASE_NAMES = ("in_possession", "out_of_possession")
PLAN_ERROR = "需要有球和无球两套阶段方案"
MIXED_PHASE_ERROR = "双阶段格式不可同时包含旧版战术字段"
ASSIGNMENT_ERROR = "位置方案格式无效"
POSITION_ERROR = "位置名称无效"
TEAM_INSTRUCTIONS_ERROR = "球队指令格式无效"
TEAM_ERROR = "球队格式无效"


def _is_legacy_scenario(value: Mapping[str, Any]) -> bool:
    teams = value.get("teams")
    return isinstance(teams, list) and any(
        isinstance(team, Mapping) and "phase_plans" in team for team in teams
    )


def upgrade_legacy_scenario(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not _is_legacy_scenario(value):
        return value
    upgraded = copy.deepcopy(dict(value))
    upgraded["schema"] = NATIVE_SCHEMA
    upgraded["teams"] = [_upgrade_legacy_team(team) for team in upgraded["teams"]]
    return upgraded


def _upgrade_legacy_team(team: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(team, Mapping):
        raise ValueError(TEAM_ERROR)
    in_possession, out_of_possession = _phase_plans(team)
    if "phases" in team or "instructions" in team:
        raise ValueError(MIXED_PHASE_ERROR)
    instructions: dict[str, Any] = {}
    instructions.update(_team_instructions(in_possession))
    instructions.update(_team_instructions(out_of_possession))
    converted = copy.deepcopy(dict(team))
    del converted["phase_plans"]
    converted["instructions"] = instructions
    converted["phases"] = [
        _assignment_cells(in_possession),
        _assignment_cells(out_of_possession),
    ]
    return converted


def _phase_plans(team: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    plans = team.get("phase_plans")
    if not isinstance(plans, list) or len(plans) != 2:
        raise ValueError(PLAN_ERROR)
    mapped: dict[str, Mapping[str, Any]] = {}
    for plan in plans:
        if not isinstance(plan, Mapping):
            raise ValueError(PLAN_ERROR)
        phase = plan.get("phase")
        if phase not in PHASE_NAMES or phase in mapped:
            raise ValueError(PLAN_ERROR)
        mapped[phase] = plan
    if len(mapped) != 2:
        raise ValueError(PLAN_ERROR)
    return mapped["in_possession"], mapped["out_of_possession"]


def _team_instructions(plan: Mapping[str, Any]) -> dict[str, Any]:
    value = plan.get("team_instructions", {})
    if not isinstance(value, Mapping):
        raise ValueError(TEAM_INSTRUCTIONS_ERROR)
    return copy.deepcopy(dict(value))


def _assignment_cells(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    assignments = plan.get("assignments")
    if not isinstance(assignments, list) or len(assignments) != 11:
        raise ValueError(ASSIGNMENT_ERROR)
    cells: list[dict[str, Any]] = []
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            raise ValueError(ASSIGNMENT_ERROR)
        position = assignment.get("position")
        if not isinstance(position, str) or not position:
            raise ValueError(POSITION_ERROR)
        cell = copy.deepcopy(dict(assignment))
        if not isinstance(cell.get("role"), str):
            cell["role"] = ""
        cells.append(cell)
    return cells


def _reference_uids(players: Sequence[Mapping[str, Any]], values: Any) -> list[Any]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[Any] = []
    for index in values:
        if type(index) is not int or not 0 <= index < len(players):
            continue
        uid = players[index].get("source_uid")
        if uid is not None:
            result.append(uid)
    return result


def _normalize_team(team: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(team, Mapping):
        raise ValueError("球队格式无效")
    players = team.get("players")
    if not isinstance(players, list) or not players:
        raise ValueError("球队球员列表格式无效")
    if any(not isinstance(player, Mapping) for player in players):
        raise ValueError("球队球员条目格式无效")
    lineup = team.get("lineup", [])
    if not isinstance(lineup, list):
        raise ValueError("球队首发列表格式无效")
    substitutes = team.get("substitutes")
    if not isinstance(substitutes, list):
        starters = {index for index in lineup if type(index) is int}
        substitutes = [index for index in range(len(players)) if index not in starters]
    captains = _reference_uids(players, team.get("captains", []))
    if "captains" in team and not isinstance(team.get("captains"), (list, tuple)):
        raise ValueError("队长名单格式无效")
    raw_takers = team.get("takers", {})
    if not isinstance(raw_takers, Mapping):
        raise ValueError("主罚名单格式无效")
    takers = {key: _reference_uids(players, values) for key, values in raw_takers.items()}
    raw_setpieces = team.get("setpieces", {})
    if not isinstance(raw_setpieces, Mapping):
        raise ValueError("定位球配置格式无效")
    priorities = raw_setpieces.get("role_priorities", {})
    if not isinstance(priorities, Mapping):
        raise ValueError("定位球优先级格式无效")
    setpiece_priorities = {key: _reference_uids(players, values) for key, values in priorities.items()}
    try:
        roster = normalize_roster(
            players,
            lineup=lineup,
            substitutes=substitutes,
            captains=captains,
            takers=takers,
            setpiece_priorities=setpiece_priorities,
        )
    except ValueError as error:
        message = str(error)
        if message == "roster_duplicate_source_uid":
            raise ValueError("球队球员 source_uid 重复") from None
        if message == "roster_missing_goalkeeper":
            raise ValueError("球队缺少门将") from None
        if message == "roster_empty":
            raise ValueError("球队球员列表为空") from None
        if message == "roster_missing_source_uid":
            raise ValueError("球队球员缺少 source_uid") from None
        if message == "roster_invalid_source_uid":
            raise ValueError("球队球员 source_uid 无效") from None
        raise

    result = copy.deepcopy(dict(team))
    result["players"] = copy.deepcopy(list(roster.players))
    result["roster_size"] = MATCH_ROSTER_SIZE
    result["lineup"] = list(roster.lineup)
    result["captains"] = list(roster.captains)
    result["takers"] = {key: list(values) for key, values in roster.takers.items()}
    if "substitutes" in team:
        result["substitutes"] = list(roster.substitutes)
    if isinstance(team.get("setpieces"), Mapping):
        setpieces = copy.deepcopy(dict(team["setpieces"]))
        setpieces["role_priorities"] = {
            key: list(values) for key, values in roster.setpiece_priorities.items()
        }
        result["setpieces"] = setpieces
    result["roster_trim"] = roster.roster_trim
    return result


def normalize_scenario(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("场景必须是对象")
    upgraded = upgrade_legacy_scenario(value)
    teams = upgraded.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        raise ValueError("场景必须包含两支球队")
    result = copy.deepcopy(dict(upgraded))
    result["teams"] = [_normalize_team(team) for team in teams]
    return result
