"""Scenario normalization around the 23-player match roster."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .roster import MATCH_ROSTER_SIZE, normalize_roster


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
    teams = value.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        raise ValueError("场景必须包含两支球队")
    result = copy.deepcopy(dict(value))
    result["teams"] = [_normalize_team(team) for team in teams]
    return result
