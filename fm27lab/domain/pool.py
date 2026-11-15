"""Away tactic pool selection, schema normalization and match expansion.

This module owns weighted draws, rotation order, completed-draw accounting,
strict pool schema normalization and per-match application of pool tactics to
engine scenario teams.
"""

from __future__ import annotations

import copy
import json
import random
from collections.abc import Mapping, Sequence
from typing import Any

from .attributes import ATTRIBUTE_COUNT, VISIBLE_GROUPS, group_indices
from .roster import (
    BENCH,
    MATCH_ROSTER_SIZE,
    STARTERS,
    apply_roster_selection,
    apply_saved_roster,
    normalize_roster,
)

MAX_WEIGHT = 1000
MAX_ENTRIES = 128
MAX_ROUNDS = 1000
MAX_NAME = 80
MAX_ROSTER = 26
MAX_ROSTER_BYTES = 1_500_000
MAX_ROTATION_MATCHES = 10000
DEFAULT_ATTRIBUTE_VALUE = 15
POSITION_ATTRIBUTES = 15
POSITION_FAMILIARITY = 20
PROFILE = "away-tactic-pool-v1"

POSITION_ATTRIBUTE_INDEX = {
    "GK": 0,
    "SW": 1,
    "DL": 2,
    "DC": 3,
    "DCR": 3,
    "DCL": 3,
    "DR": 4,
    "DM": 5,
    "DMC": 5,
    "DMR": 5,
    "DML": 5,
    "ML": 6,
    "MC": 7,
    "MCL": 7,
    "MCR": 7,
    "MR": 8,
    "AML": 9,
    "AMC": 10,
    "AMCL": 10,
    "AMCR": 10,
    "AMR": 11,
    "ST": 12,
    "STR": 12,
    "STL": 12,
    "WBL": 13,
    "WBR": 14,
}

VISIBLE_ATTRIBUTE_INDICES = frozenset().union(*(group_indices(group) for group in VISIBLE_GROUPS))


def _integer(value: Any, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}必须为 {low}–{high} 的整数")
    return value


def probabilities(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, int | float]]:
    if not isinstance(entries, (list, tuple)) or not entries:
        raise ValueError("客队战术池没有可抽取的战术")
    if len(entries) > MAX_ENTRIES:
        raise ValueError("客队战术池最多允许 128 套战术")
    weights: list[int] = []
    for index, item in enumerate(entries, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"第 {index} 套客队战术格式无效")
        weights.append(_integer(item.get("weight", 1), 1, MAX_WEIGHT, f"第 {index} 套客队战术权重"))
    total = sum(weights)
    return [{"weight": weight, "probability": weight / total} for weight in weights]


def draw_index(entries: Sequence[Mapping[str, Any]], seed: int, salt: str) -> int:
    if type(seed) is not int:
        raise ValueError("随机种子必须为整数")
    rows = probabilities(entries)
    target = random.Random(f"{salt}:{seed}").random()
    cumulative = 0.0
    for index, row in enumerate(rows):
        cumulative += row["probability"]
        if target < cumulative:
            return index
    return len(rows) - 1


def rotation_matches(entry_count: int, rounds: int) -> int:
    count = _integer(entry_count, 0, MAX_ENTRIES, "客队战术数量")
    round_count = _integer(rounds, 1, 1000, "轮战轮数")
    total = count * round_count
    if total > MAX_ROTATION_MATCHES:
        raise ValueError(
            f"轮战每方案最多 {MAX_ROTATION_MATCHES} 场，当前 {count} 套 × {round_count} 轮 = {total} 场"
        )
    return total


def rotation_message(entry_count: int, rounds: int, count: int) -> str:
    return (
        f"轮战模式每方案需要 {entry_count} 套 × {rounds} 轮 = {entry_count * rounds} 场，当前种子数为 {count}"
    )


def draws(
    entries: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    salt: str,
    *,
    rotation_enabled: bool = False,
    rounds: int = 1,
) -> dict[int, int]:
    probabilities(entries)
    if not isinstance(seeds, (list, tuple)):
        raise ValueError("随机种子列表格式无效")
    if any(type(seed) is not int for seed in seeds):
        raise ValueError("随机种子必须为整数")
    if rotation_enabled:
        if len(set(seeds)) != len(seeds):
            raise ValueError("轮战模式的种子必须唯一")
        expected = rotation_matches(len(entries), rounds)
        if len(seeds) != expected:
            raise ValueError(rotation_message(len(entries), rounds, len(seeds)))
        return {seed: index % len(entries) for index, seed in enumerate(seeds)}
    return {seed: draw_index(entries, seed, salt) for seed in seeds}


def completed_draw_counts(runs: Sequence[Mapping[str, Any]], entry_count: int) -> dict[str, int]:
    entry_count = _integer(entry_count, 0, MAX_ENTRIES, "客队战术数量")
    counts = {str(index): 0 for index in range(entry_count)}
    by_seed: dict[int, int] = {}
    for run in runs:
        if not isinstance(run, Mapping):
            raise ValueError("比赛记录格式无效")
        entry = run.get("tactic_pool_entry")
        if entry is None:
            continue
        if not isinstance(entry, Mapping):
            raise ValueError("客队战术记录格式无效")
        index = _integer(entry.get("index"), 0, entry_count - 1, "客队战术序号")
        seed = run.get("seed")
        if type(seed) is not int:
            raise ValueError("比赛记录缺少整数种子")
        if seed in by_seed and by_seed[seed] != index:
            raise ValueError("同种子对照的客队战术不一致")
        by_seed[seed] = index
    for index in by_seed.values():
        counts[str(index)] += 1
    return counts


def _flag(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(label + "必须为布尔值")
    return value


def _mode_value(value: bool | Mapping[str, Any], key: str, label: str) -> tuple[bool, Any]:
    if isinstance(value, Mapping):
        return _flag(value.get("enabled", False), label), value.get(key)
    return _flag(value, label), None


def summary(
    entries: Sequence[Mapping[str, Any]],
    *,
    rotation: bool | Mapping[str, Any] = False,
    rounds: int = 1,
    uniform: Mapping[str, Any] | None = None,
    real: bool | Mapping[str, Any] = False,
    salt: str | None = None,
    profile: str = PROFILE,
    enabled: bool = False,
) -> dict[str, Any]:
    if profile != PROFILE:
        raise ValueError("客队战术池版本无效")
    rows = probabilities(entries)
    rotation_enabled, rotation_rounds = _mode_value(rotation, "rounds", "轮战模式开关")
    real_enabled, _ = _mode_value(real, "enabled", "真实名单开关")
    if rotation_rounds is not None:
        rounds = rotation_rounds
    rounds = _integer(rounds, 1, 1000, "轮战轮数")
    if rotation_enabled:
        rotation_matches(len(entries), rounds)
    raw_uniform = dict(uniform or {})
    uniform_value = {
        "enabled": _flag(raw_uniform.get("enabled", True), "统一属性开关"),
        "attribute_value": _integer(
            raw_uniform.get("attribute_value", DEFAULT_ATTRIBUTE_VALUE),
            1,
            20,
            "统一属性值",
        ),
    }
    value = {
        "profile": str(profile),
        "enabled": _flag(enabled, "客队战术池开关"),
        "mode": "rotation" if rotation_enabled else "random",
        "rounds": rounds,
        "players": "real" if real_enabled else "uniform",
        "uniform": uniform_value,
        "entries": [
            {
                "index": index,
                "name": _entry_name(item, index),
                "weight": row["weight"],
                "probability": None if rotation_enabled else row["probability"],
                "roster": item.get("roster") is not None,
            }
            for index, (item, row) in enumerate(zip(entries, rows, strict=False))
        ],
    }
    if salt is not None:
        value["salt"] = str(salt)
    return value


def _entry_name(item: Mapping[str, Any], index: int) -> str:
    name = item.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(char) < 32 for char in name):
        raise ValueError(f"第 {index + 1} 套客队战术名称无效")
    return name.strip()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= MAX_NAME or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label}须为1–{MAX_NAME}个可读字符")
    return value.strip()


def _instructions(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(label + "格式无效")
    result: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdigit():
            raise ValueError(label + "键必须为十进制数字")
        result[str(int(key))] = _integer(item, 0, 0xFFFFFFFF, label)
    return result


def _source_plan(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"value", "signature"} or not isinstance(value["value"], dict):
        raise ValueError(label + "原生方案来源无效")
    signature = value["signature"]
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(char not in "0123456789abcdef" for char in signature.lower())
    ):
        raise ValueError(label + "原生方案签名无效")
    return {"value": copy.deepcopy(value["value"]), "signature": signature}


def _cell(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(label + "位置格式无效")
    position = value.get("position")
    if not isinstance(position, str) or not 1 <= len(position) <= 16:
        raise ValueError(label + "位置名称无效")
    role = value.get("role")
    if not isinstance(role, str) or not 1 <= len(role) <= 40:
        raise ValueError(label + "角色名称无效")
    duty = value.get("duty")
    if not isinstance(duty, str) or not duty.isascii() or not duty.isdigit() or len(duty) > 20:
        raise ValueError(label + "职责位无效")
    return {
        "position": position,
        "role": role,
        "duty": str(int(duty)),
        "instructions": _instructions(value.get("instructions", {}), label + "个人指令"),
        "target_player": _integer(value.get("target_player", 255), 0, 255, label + "盯防球员"),
        "target_position": _integer(value.get("target_position", 0), 0, 0xFFFFFFFFFFFFFFFF, label + "盯防位置"),
    }


def _phases(value: Any, label: str) -> list[list[dict[str, Any]]]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(label + "必须包含有球和无球两个阶段")
    result: list[list[dict[str, Any]]] = []
    for phase_index, phase in enumerate(value, 1):
        if not isinstance(phase, list) or len(phase) != 11:
            raise ValueError(label + "每个阶段必须有11个位置")
        result.append(
            [
                _cell(cell_value, f"{label}第 {phase_index} 阶段第 {slot + 1} 个位置")
                for slot, cell_value in enumerate(phase)
            ]
        )
    return result


def _tactic(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(label + "战术格式无效")
    name = value.get("tactic_name", "")
    if not isinstance(name, str) or len(name) > 120 or any(ord(char) < 32 for char in name):
        raise ValueError(label + "战术名称无效")
    extra = value.get("native_extra_team_bits")
    if (
        not isinstance(extra, str)
        or not extra.isascii()
        or not extra.isdigit()
        or len(extra) > 39
        or int(extra) >= 1 << 128
    ):
        raise ValueError(label + "附加原生战术选项无效")
    tactic: dict[str, Any] = {
        "tactic_name": name,
        "mentality": _integer(value.get("mentality"), 1, 7, label + "比赛心态"),
        "instructions": _instructions(value.get("instructions"), label + "球队指令"),
        "native_extra_team_bits": str(int(extra)),
        "phases": _phases(value.get("phases"), label),
    }
    if value.get("native_source_plan") is not None:
        tactic["native_source_plan"] = _source_plan(value["native_source_plan"], label)
    return tactic


def _roster_name(value: Any, limit: int, label: str) -> str:
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label}须为不超过 {limit} 个可读字符")
    return value.strip()


def _roster_player(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"name", "source_uid", "attributes", "native_profile"}:
        raise ValueError(label + "格式无效")
    name = value.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 48 or any(ord(char) < 32 for char in name):
        raise ValueError(label + "球员名称须为1–48个可读字符")
    attributes = value.get("attributes")
    if not isinstance(attributes, list) or len(attributes) != ATTRIBUTE_COUNT:
        raise ValueError(label + "球员属性不完整")
    normalized: list[int] = []
    for index, item in enumerate(attributes):
        if index < POSITION_ATTRIBUTES:
            normalized.append(_integer(item, 0, 20, label + "属性"))
        else:
            normalized.append(_integer(item, 1, 100, label + "属性"))
    profile = value.get("native_profile", {})
    if not isinstance(profile, dict):
        raise ValueError(label + "球员扩展输入格式无效")
    return {
        "name": name.strip(),
        "source_uid": _integer(value.get("source_uid"), 0, 0xFFFFFFFF, label + "源球员UID"),
        "attributes": normalized,
        "native_profile": copy.deepcopy(profile),
    }


def _roster(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "club_uid",
        "club",
        "coach",
        "source",
        "roster_size",
        "lineup",
        "players",
    }:
        raise ValueError(label + "存档名单格式无效")
    players = value.get("players")
    if not isinstance(players, list) or not 11 <= len(players) <= MAX_ROSTER:
        raise ValueError(f"{label}存档名单须包含 11–{MAX_ROSTER} 名球员")
    normalized = [
        _roster_player(item, f"{label}存档名单第 {index + 1} 名球员") for index, item in enumerate(players)
    ]
    size = _integer(value.get("roster_size", len(normalized)), 11, len(normalized), label + "存档名单人数")
    if size != len(normalized):
        raise ValueError(label + "存档名单人数与球员数量不一致")
    if len({item["source_uid"] for item in normalized}) != len(normalized):
        raise ValueError(label + "存档名单包含重复球员")
    lineup = value.get("lineup")
    if not isinstance(lineup, list) or len(lineup) != 11:
        raise ValueError(label + "存档名单首发须为11名不同球员")
    try:
        distinct = len(set(lineup)) == 11
    except TypeError:
        distinct = False
    if not distinct:
        raise ValueError(label + "存档名单首发须为11名不同球员")
    source = value.get("source")
    if source not in ("real_ai", "coach_preset"):
        raise ValueError(label + "存档名单来源无效")
    return {
        "club_uid": _integer(value.get("club_uid"), 0, 0xFFFFFFFF, label + "存档球队编号"),
        "club": _roster_name(value.get("club"), 40, label + "存档球队名称"),
        "coach": _roster_name(value.get("coach"), 60, label + "存档主教练名称"),
        "source": source,
        "roster_size": size,
        "lineup": [_integer(item, 0, size - 1, label + "存档名单首发") for item in lineup],
        "players": normalized,
    }


def _entry(value: Any, index: int) -> dict[str, Any]:
    label = f"第 {index + 1} 套客队战术"
    if not isinstance(value, dict):
        raise ValueError(label + "格式无效")
    if set(value) - {"name", "weight", "tactic", "roster"}:
        raise ValueError(label + "包含未知字段")
    name = value.get("name")
    if not isinstance(name, str):
        raise ValueError(f"{label}名称须为1–{MAX_NAME}个可读字符")
    result = {
        "name": _text(name, label + "名称"),
        "weight": _integer(value.get("weight", 1), 1, MAX_WEIGHT, label + "权重"),
        "tactic": _tactic(value.get("tactic"), label),
    }
    if value.get("roster") is not None:
        result["roster"] = _roster(value["roster"], label)
    return result


def _uniform(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("统一属性设置格式无效")
    return {
        "enabled": _flag(value.get("enabled", True), "统一属性开关"),
        "attribute_value": _integer(
            value.get("attribute_value", DEFAULT_ATTRIBUTE_VALUE), 1, 20, "统一属性值"
        ),
    }


def _rotation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("轮战模式设置格式无效")
    if set(value) - {"enabled", "rounds"}:
        raise ValueError("轮战模式设置包含未知字段")
    return {
        "enabled": _flag(value.get("enabled", False), "轮战模式开关"),
        "rounds": _integer(value.get("rounds", 1), 1, MAX_ROUNDS, "轮战每套轮数"),
    }


def _real(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("真实名单设置格式无效")
    if set(value) - {"enabled"}:
        raise ValueError("真实名单设置包含未知字段")
    return {"enabled": _flag(value.get("enabled", False), "真实名单开关")}


def normalize_away_pool(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("客队战术池格式无效")
    if value.get("profile", PROFILE) != PROFILE:
        raise ValueError("客队战术池版本无效")
    entries = value.get("entries", [])
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise ValueError(f"客队战术池最多允许 {MAX_ENTRIES} 套战术")
    normalized = [_entry(item, index) for index, item in enumerate(entries)]
    enabled = _flag(value.get("enabled", False), "客队战术池开关")
    if enabled and not normalized:
        raise ValueError("启用客队战术池前请先导入客队战术")
    rotation = _rotation(value["rotation"] if "rotation" in value else {"enabled": False, "rounds": 1})
    uniform = _uniform(
        value["uniform"]
        if "uniform" in value
        else {"enabled": True, "attribute_value": DEFAULT_ATTRIBUTE_VALUE}
    )
    real = _real(value["real"] if "real" in value else {"enabled": False})
    if real["enabled"]:
        missing = [item["name"] for item in normalized if item.get("roster") is None]
        if missing:
            suffix = "等" if len(missing) > 3 else ""
            raise ValueError(
                "真实名单模式需要每套客队战术都带存档球员名单，缺少："
                + "、".join(missing[:3])
                + suffix
            )
    rosters = [item["roster"] for item in normalized if item.get("roster") is not None]
    if rosters:
        size = len(json.dumps(rosters, ensure_ascii=False, separators=(",", ":")).encode("utf8"))
        if size > MAX_ROSTER_BYTES:
            raise ValueError(
                f"带存档名单的候选战术合计约 {size / 1000000:.2f} MB，"
                f"超过 {MAX_ROSTER_BYTES / 1000000:.2f} MB 上限；请减少带名单的候选或清理条目"
            )
    if rotation["enabled"] and normalized and len(normalized) * rotation["rounds"] > MAX_ROTATION_MATCHES:
        raise ValueError(
            f"轮战每方案最多 {MAX_ROTATION_MATCHES} 场，"
            f"当前 {len(normalized)} 套 × {rotation['rounds']} 轮 = "
            f"{len(normalized) * rotation['rounds']} 场"
        )
    return {
        "profile": PROFILE,
        "enabled": enabled,
        "entries": normalized,
        "uniform": uniform,
        "rotation": rotation,
        "real": real,
    }


def _apply_uniform(team: dict[str, Any], attribute_value: int) -> None:
    players = team.get("players")
    if not isinstance(players, list):
        raise ValueError("客队球员属性不完整，无法统一为界面值")
    for player in players:
        if (
            not isinstance(player, dict)
            or not isinstance(player.get("attributes"), list)
            or len(player["attributes"]) != ATTRIBUTE_COUNT
        ):
            raise ValueError("客队球员属性不完整，无法统一为界面值")
        attributes = player["attributes"]
        for index in VISIBLE_ATTRIBUTE_INDICES:
            attributes[index] = attribute_value * 5
        attributes[0] = 1
    lineup = team.get("lineup")
    if not isinstance(lineup, list) or len(lineup) < STARTERS:
        raise ValueError("客队首发名单不完整，无法统一战术位置熟练度")
    phases = team.get("phases")
    if not isinstance(phases, list) or len(phases) != 2:
        raise ValueError("客队战术阶段不完整，无法统一战术位置熟练度")
    for phase in phases:
        if not isinstance(phase, list) or len(phase) != 11:
            raise ValueError("客队战术阶段不完整，无法统一战术位置熟练度")
        for slot, cell_value in enumerate(phase):
            if not isinstance(cell_value, dict):
                raise ValueError("客队战术位置格式无效")
            player_index = lineup[slot]
            if type(player_index) is not int or not 0 <= player_index < len(players):
                raise ValueError("客队首发名单包含无效球员序号")
            familiar = POSITION_ATTRIBUTE_INDEX.get(cell_value.get("position"))
            if familiar is None:
                raise ValueError("战术包含未知位置，无法统一熟练度：" + str(cell_value.get("position")))
            players[player_index]["attributes"][familiar] = POSITION_FAMILIARITY


def _apply_real_roster(team: dict[str, Any], real_roster: Any) -> dict[str, Any]:
    roster = _roster(real_roster, "")
    count = roster["roster_size"]
    if count > MATCH_ROSTER_SIZE:
        return _apply_trimmed_roster(team, roster)
    players = roster["players"]
    if count == MATCH_ROSTER_SIZE:
        return apply_saved_roster(
            team,
            {
                "players": players,
                "lineup": list(roster["lineup"]),
                "roster_size": MATCH_ROSTER_SIZE,
            },
        )
    starters = [players[index] for index in roster["lineup"]]
    starters_selection = set(roster["lineup"])
    bench = [item for index, item in enumerate(players) if index not in starters_selection]
    substitutes = [*bench, *([None] * (BENCH - len(bench)))]
    return apply_roster_selection(team, starters=starters, substitutes=substitutes)


def _apply_trimmed_roster(team: dict[str, Any], roster: dict[str, Any]) -> dict[str, Any]:
    try:
        normalized = normalize_roster(roster["players"], lineup=roster["lineup"])
    except ValueError as error:
        if str(error) != "roster_missing_goalkeeper":
            raise
        raise ValueError("客队存档名单缺少门将") from None
    if normalized.generated:
        starters = [
            None if normalized.players[index].get("generated") else normalized.players[index]
            for index in normalized.lineup
        ]
        substitutes = [
            None if normalized.players[index].get("generated") else normalized.players[index]
            for index in normalized.substitutes
        ]
        result = apply_roster_selection(team, starters=starters, substitutes=substitutes)
    else:
        result = apply_saved_roster(
            team,
            {
                "players": list(normalized.players),
                "lineup": list(normalized.lineup),
                "roster_size": MATCH_ROSTER_SIZE,
            },
        )
    result["roster_trim"] = normalized.roster_trim
    return result


def apply_away_entry(
    team: Any,
    entry: Any,
    *,
    uniform_enabled: bool,
    uniform_attribute_value: int = DEFAULT_ATTRIBUTE_VALUE,
    real_roster: Any = None,
) -> dict[str, Any]:
    if not isinstance(team, Mapping):
        raise ValueError("球队格式无效")
    normalized = _entry(entry, 0)
    tactic = normalized["tactic"]
    result = copy.deepcopy(dict(team))
    result["tactic_name"] = tactic["tactic_name"]
    result["mentality"] = tactic["mentality"]
    result["instructions"] = copy.deepcopy(tactic["instructions"])
    result["native_extra_team_bits"] = tactic["native_extra_team_bits"]
    result["phases"] = copy.deepcopy(tactic["phases"])
    result.pop("native_source_plan", None)
    if "native_source_plan" in tactic:
        result["native_source_plan"] = copy.deepcopy(tactic["native_source_plan"])
    enabled = _flag(uniform_enabled, "统一属性开关")
    attribute_value = _integer(uniform_attribute_value, 1, 20, "统一属性值")
    if real_roster:
        return _apply_real_roster(result, real_roster)
    if enabled:
        _apply_uniform(result, attribute_value)
    return result


def _validate_scenario(scenario: Any) -> None:
    if (
        not isinstance(scenario, Mapping)
        or not isinstance(scenario.get("teams"), list)
        or len(scenario["teams"]) != 2
    ):
        raise ValueError("方案必须包含两支球队")


def _expand_scenario_entry(scenario: Any, value: dict[str, Any], index: int) -> dict[str, Any]:
    selected = value["entries"][index]
    real_enabled = value["real"]["enabled"]
    real_roster = selected.get("roster")
    if real_enabled and real_roster is None:
        raise ValueError("真实名单模式缺少存档球员名单")
    result = copy.deepcopy(dict(scenario))
    result.pop("away_tactic_pool", None)
    result["teams"][1] = apply_away_entry(
        result["teams"][1],
        selected,
        uniform_enabled=value["uniform"]["enabled"],
        uniform_attribute_value=value["uniform"]["attribute_value"],
        real_roster=real_roster if real_enabled else None,
    )
    return result


def expand_away_scenarios(
    scenario: Any, pool: Any, seeds: Any, salt: str
) -> list[dict[str, Any]]:
    _validate_scenario(scenario)
    if not isinstance(seeds, (list, tuple)):
        raise ValueError("随机种子列表格式无效")
    if any(type(seed) is not int for seed in seeds):
        raise ValueError("随机种子必须为整数")
    source = _text(salt, "客队战术池抽取来源")
    value = normalize_away_pool(pool)
    if not value["enabled"] or not value["entries"]:
        return [copy.deepcopy(scenario) for _ in seeds]
    indices = draws(
        value["entries"],
        list(seeds),
        source,
        rotation_enabled=value["rotation"]["enabled"],
        rounds=value["rotation"]["rounds"],
    )
    return [_expand_scenario_entry(scenario, value, indices[seed]) for seed in seeds]


def expand_away_scenario(scenario: Any, pool: Any, seed: int, salt: str) -> dict[str, Any]:
    return expand_away_scenarios(scenario, pool, [seed], salt)[0]
