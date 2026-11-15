from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MATCH_ROSTER_SIZE = 23
STARTERS = 11
BENCH = MATCH_ROSTER_SIZE - STARTERS

POSITION_SLOTS: tuple[str, ...] = (
    "GK",
    "SW",
    "DL",
    "DC",
    "DR",
    "DM",
    "ML",
    "MC",
    "MR",
    "AML",
    "AMC",
    "AMR",
    "ST",
    "WBL",
    "WBR",
)
POSITION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("GK",),
    ("SW", "DC"),
    ("DL", "DR", "WBL", "WBR"),
    ("DM",),
    ("ML", "MC", "MR"),
    ("AML", "AMR", "AMC"),
    ("ST",),
)
POSITION_INDEX = {name: index for index, name in enumerate(POSITION_SLOTS)}
POSITION_ALIASES: dict[str, str] = {
    "DCR": "DC",
    "DCL": "DC",
    "DMC": "DM",
    "DML": "DM",
    "DMR": "DM",
    "MCL": "MC",
    "MCR": "MC",
    "AMCL": "AMC",
    "AMCR": "AMC",
    "STL": "ST",
    "STR": "ST",
}
VISIBLE_ATTRIBUTES = frozenset(
    {
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        57,
        58,
        60,
        61,
        65,
        66,
        67,
        68,
    }
)
TAKER_PREFERENCES: dict[str, tuple[str, ...]] = {
    "penalties": ("AMC", "ST", "AML", "AMR", "MC"),
    "corners": ("DL", "DR", "WBL", "WBR", "ML", "MR", "AML", "AMR"),
    "direct_free_kicks": ("AMC", "AML", "AMR", "MC", "ST"),
    "wide_free_kicks": ("DL", "DR", "WBL", "WBR", "AML", "AMR"),
    "deep_free_kicks": ("DC", "SW", "DM", "MC"),
    "throw_ins": ("DL", "DR", "WBL", "WBR", "ML", "MR"),
}


@dataclass(frozen=True)
class RosterResult:
    players: tuple[dict[str, Any], ...]
    lineup: tuple[int, ...]
    substitutes: tuple[int, ...]
    captains: tuple[int, ...]
    takers: dict[str, tuple[int, ...]]
    setpiece_priorities: dict[str, tuple[int, ...]]
    removed: tuple[dict[str, Any], ...]
    generated: tuple[dict[str, Any], ...]
    source_size: int

    @property
    def roster_trim(self) -> dict[str, Any]:
        return {
            "source_size": self.source_size,
            "removed": list(self.removed),
            "generated": [player["source_uid"] for player in self.generated],
            "captains": list(self.captains),
            "takers": {key: list(values) for key, values in self.takers.items()},
            "setpiece_priorities": {key: list(values) for key, values in self.setpiece_priorities.items()},
        }


def canonical_position(name: str) -> str:
    return POSITION_ALIASES.get(name, name)


def player_position(player: Mapping[str, Any]) -> int:
    attributes = player.get("attributes") or []
    if len(attributes) < 15:
        return POSITION_INDEX["MC"]
    return max(range(15), key=lambda index: (attributes[index], -index))


def player_ability(player: Mapping[str, Any]) -> float:
    value = player.get("ability")
    if isinstance(value, Mapping):
        value = value.get("current")
    if isinstance(value, (int, float)):
        return float(value)
    attributes = player.get("attributes") or []
    visible = [attributes[index] for index in sorted(VISIBLE_ATTRIBUTES) if index < len(attributes)]
    return float(sum(visible) / len(visible)) if visible else 0.0


def is_goalkeeper(player: Mapping[str, Any]) -> bool:
    return player_position(player) == POSITION_INDEX["GK"]


def _valid_uid(uid: Any) -> bool:
    if type(uid) not in (int, str):
        return False
    if isinstance(uid, str):
        return bool(uid.strip()) and uid == uid.strip() and not any(ord(char) < 32 for char in uid)
    return True


def _uid_key(player: Mapping[str, Any]) -> tuple[int, Any]:
    uid = player.get("source_uid")
    if isinstance(uid, int):
        return (0, uid)
    return (1, str(uid))


def _sort_key(item: tuple[int, Mapping[str, Any]]) -> tuple[float, tuple[int, Any], int]:
    index, player = item
    return (-player_ability(player), _uid_key(player), index)


def _gk_key(item: tuple[int, Mapping[str, Any]]) -> tuple[float, float, tuple[int, Any], int]:
    index, player = item
    attributes = player.get("attributes") or []
    familiarity = attributes[0] if len(attributes) > 0 else 0
    return (-familiarity, -player_ability(player), _uid_key(player), index)


def _unique_indices(values: Iterable[int], size: int) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if type(value) is not int:
            continue
        if 0 <= value < size and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _validate_uids(source: Sequence[Mapping[str, Any]]) -> dict[Any, int]:
    mapping: dict[Any, int] = {}
    for index, player in enumerate(source):
        uid = player.get("source_uid")
        if uid is None or uid == "":
            raise ValueError("roster_missing_source_uid")
        if not _valid_uid(uid):
            raise ValueError("roster_invalid_source_uid")
        if uid in mapping:
            raise ValueError("roster_duplicate_source_uid")
        mapping[uid] = index
    return mapping


def _fill(
    candidates: list[int],
    players: Sequence[Mapping[str, Any]],
    count: int,
    allow_goalkeeper: bool,
    max_goalkeepers: int | None = 1,
) -> list[int]:
    chosen: list[int] = []
    remaining = list(candidates)
    chosen_goalkeepers = 0
    for group in POSITION_GROUPS:
        slots = {POSITION_INDEX[name] for name in group}
        if not allow_goalkeeper and slots == {POSITION_INDEX["GK"]}:
            continue
        matched = [index for index in remaining if player_position(players[index]) in slots]
        if group == ("GK",):
            matched.sort(key=lambda index: _gk_key((index, players[index])))
            if max_goalkeepers is not None:
                matched = matched[: max(0, max_goalkeepers - chosen_goalkeepers)]
        else:
            matched.sort(key=lambda index: _sort_key((index, players[index])))
        for index in matched:
            if len(chosen) >= count:
                break
            chosen.append(index)
            remaining.remove(index)
            if group == ("GK",):
                chosen_goalkeepers += 1
        if len(chosen) >= count:
            break
    for index in sorted(remaining, key=lambda index: _sort_key((index, players[index]))):
        if len(chosen) >= count:
            break
        goalkeeper = is_goalkeeper(players[index])
        if goalkeeper and not allow_goalkeeper:
            continue
        if goalkeeper and max_goalkeepers is not None and chosen_goalkeepers >= max_goalkeepers:
            continue
        chosen.append(index)
        if goalkeeper:
            chosen_goalkeepers += 1
    return chosen


def _generated(index: int, used: set[Any]) -> dict[str, Any]:
    attributes = [10] * 69
    attributes[POSITION_INDEX["MC"]] = 15
    attributes[56] = 5
    attributes[63] = 5
    uid = f"generated:{index}"
    while uid in used:
        index += 1
        uid = f"generated:{index}"
    used.add(uid)
    return {
        "source_uid": uid,
        "name": f"占位球员 {index}",
        "attributes": attributes,
        "ability": 10,
        "generated": True,
    }


def _default_references(selected: Sequence[Mapping[str, Any]], key: str) -> tuple[int, ...]:
    preferred_slots = {POSITION_INDEX[name] for name in TAKER_PREFERENCES.get(key, ())}
    candidates = [
        index
        for index, player in enumerate(selected)
        if not player.get("generated") and not is_goalkeeper(player)
    ]
    preferred = [index for index in candidates if player_position(selected[index]) in preferred_slots]
    pool = preferred or candidates
    pool.sort(key=lambda index: _sort_key((index, selected[index])))
    return tuple(pool[:3])


def _remap_references(
    values: Any,
    old_uids: Sequence[Any],
    uid_to_new: Mapping[Any, int],
) -> list[int]:
    if not isinstance(values, (list, tuple)):
        return []
    mapped: list[int] = []
    for old_index in values:
        if type(old_index) is not int or not 0 <= old_index < len(old_uids):
            continue
        new_index = uid_to_new.get(old_uids[old_index])
        if new_index is not None and new_index not in mapped:
            mapped.append(new_index)
    return mapped


def normalize_roster(
    players: Sequence[Mapping[str, Any]],
    lineup: Sequence[int] = (),
    substitutes: Sequence[int] = (),
    captains: Sequence[Any] = (),
    takers: Mapping[str, Sequence[Any]] | None = None,
    setpiece_priorities: Mapping[str, Sequence[Any]] | None = None,
) -> RosterResult:
    """Trim a source squad to 23 players.

    lineup/substitutes are source indices. captains/takers/setpiece_priorities
    are source_uid values, remapped to indices in the returned 23-player roster.
    """
    source = [dict(player) for player in players]
    if not source:
        raise ValueError("roster_empty")
    _validate_uids(source)
    if not any(is_goalkeeper(player) for player in source):
        raise ValueError("roster_missing_goalkeeper")
    takers = {key: list(values) for key, values in (takers or {}).items()}
    setpiece_priorities = {key: list(values) for key, values in (setpiece_priorities or {}).items()}

    starters = _unique_indices(lineup, len(source))[:STARTERS]
    remaining = [index for index in range(len(source)) if index not in set(starters)]
    starters.extend(
        _fill(
            remaining,
            source,
            STARTERS - len(starters),
            allow_goalkeeper=not any(is_goalkeeper(source[index]) for index in starters),
            max_goalkeepers=1,
        )
    )

    forced_bench: list[int] = []
    starters_goalkeepers = [index for index in starters if is_goalkeeper(source[index])]
    if len(starters_goalkeepers) > 1:
        keeper = min(starters_goalkeepers, key=lambda index: _gk_key((index, source[index])))
        forced_bench = [index for index in starters_goalkeepers if index != keeper]
        starters = [index for index in starters if index not in set(forced_bench)]
        remaining = [
            index
            for index in range(len(source))
            if index not in set(starters) and index not in set(forced_bench)
        ]
        starters.extend(
            _fill(
                remaining,
                source,
                STARTERS - len(starters),
                allow_goalkeeper=False,
                max_goalkeepers=0,
            )
        )

    if not any(is_goalkeeper(source[index]) for index in starters):
        goalkeepers = [index for index in range(len(source)) if is_goalkeeper(source[index])]
        replacement = min(goalkeepers, key=lambda index: _gk_key((index, source[index])))
        replace_at = next(
            (
                position
                for position in range(len(starters) - 1, -1, -1)
                if not is_goalkeeper(source[starters[position]])
            ),
            None,
        )
        if replace_at is None:
            raise ValueError("roster_missing_goalkeeper")
        starters[replace_at] = replacement

    used_uids = set(_validate_uids(source))
    generated_count = 0
    starter_entries: list[tuple[int | None, dict[str, Any]]] = [(index, source[index]) for index in starters]
    while len(starter_entries) < STARTERS:
        generated_count += 1
        starter_entries.append((None, _generated(generated_count, used_uids)))

    bench = list(forced_bench)
    bench.extend(
        index
        for index in _unique_indices(substitutes, len(source))
        if index not in set(starters) and index not in set(bench)
    )
    remaining = [
        index for index in range(len(source)) if index not in set(starters) and index not in set(bench)
    ]
    bench.extend(
        _fill(
            remaining,
            source,
            BENCH - len(bench),
            allow_goalkeeper=True,
            max_goalkeepers=None,
        )
    )
    bench_entries: list[tuple[int | None, dict[str, Any]]] = [(index, source[index]) for index in bench][
        :BENCH
    ]
    while len(bench_entries) < BENCH:
        generated_count += 1
        bench_entries.append((None, _generated(generated_count, used_uids)))
    selected_entries = starter_entries + bench_entries
    selected = [player for _, player in selected_entries]
    index_to_new = {
        original: new for new, (original, _) in enumerate(selected_entries) if original is not None
    }
    uid_to_new = {
        player["source_uid"]: new for new, player in enumerate(selected) if not player.get("generated")
    }
    removed = tuple(
        {
            "source_uid": player["source_uid"],
            "name": player.get("name", f"P{index + 1}"),
        }
        for index, player in enumerate(source)
        if index not in index_to_new
    )
    generated = tuple(player for player in selected if player.get("generated"))

    mapped_captains = tuple(
        uid_to_new[uid]
        for uid in captains
        if uid in uid_to_new and not selected[uid_to_new[uid]].get("generated")
    )
    if not mapped_captains:
        mapped_captains = tuple(
            index for index, player in enumerate(selected) if index < STARTERS and not player.get("generated")
        )[:1]
    mapped_takers = {
        key: tuple(
            uid_to_new[uid]
            for uid in values
            if uid in uid_to_new and not selected[uid_to_new[uid]].get("generated")
        )
        for key, values in takers.items()
    }
    for key, values in mapped_takers.items():
        if not values:
            mapped_takers[key] = _default_references(selected, key)
    mapped_setpieces = {
        key: tuple(
            uid_to_new[uid]
            for uid in values
            if uid in uid_to_new and not selected[uid_to_new[uid]].get("generated")
        )
        for key, values in setpiece_priorities.items()
    }
    for key, values in mapped_setpieces.items():
        if not values:
            mapped_setpieces[key] = _default_references(selected, key)

    return RosterResult(
        players=tuple(selected),
        lineup=tuple(range(STARTERS)),
        substitutes=tuple(range(STARTERS, MATCH_ROSTER_SIZE)),
        captains=mapped_captains,
        takers=mapped_takers,
        setpiece_priorities=mapped_setpieces,
        removed=removed,
        generated=generated,
        source_size=len(source),
    )


def _validate_saved_player(player: Mapping[str, Any], index: int) -> None:
    label = f"真实名单第 {index + 1} 名球员"
    if not isinstance(player, Mapping):
        raise ValueError(label + "格式无效")
    if player.get("generated"):
        raise ValueError(label + "不能是 generated 占位球员")
    uid = player.get("source_uid")
    if not _valid_uid(uid):
        raise ValueError(label + "缺少有效的 source_uid")
    name = player.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 48 or any(ord(char) < 32 for char in name):
        raise ValueError(label + "名称无效")
    profile = player.get("native_profile")
    if profile is not None and not isinstance(profile, Mapping):
        raise ValueError(label + "扩展输入格式无效")
    ability = player.get("ability")
    if ability is not None and (type(ability) is bool or not isinstance(ability, (int, float, Mapping))):
        raise ValueError(label + "能力值格式无效")
    attributes = player.get("attributes")
    if not isinstance(attributes, list) or len(attributes) != 69:
        raise ValueError(label + "属性必须为 69 项")
    if any(type(value) is not int for value in attributes):
        raise ValueError(label + "属性必须为整数")
    if any(not 0 <= value <= 20 for value in attributes[:15]):
        raise ValueError(label + "位置熟练度超出范围")
    if any(not 1 <= value <= 100 for value in attributes[15:]):
        raise ValueError(label + "属性超出范围")


def apply_saved_roster(
    team: Mapping[str, Any],
    roster: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply an already-selected 23-player saved roster to a match team.

    The returned team is a new object. Native IDs stay tied to host slots;
    player identity, attributes and lineup come from the saved roster.
    Captain, taker and set-piece indices are remapped by source_uid.
    """
    if not isinstance(team, Mapping) or not isinstance(roster, Mapping):
        raise ValueError("球队或真实名单格式无效")
    team_players = team.get("players")
    if not isinstance(team_players, list) or len(team_players) < MATCH_ROSTER_SIZE:
        raise ValueError("比赛球队至少需要 23 名球员")
    if any(not isinstance(item, Mapping) for item in team_players[:MATCH_ROSTER_SIZE]):
        raise ValueError("比赛球队球员格式无效")
    old_uids = [item.get("source_uid") for item in team_players[:MATCH_ROSTER_SIZE]]
    if any(not _valid_uid(uid) for uid in old_uids) or len(set(old_uids)) != MATCH_ROSTER_SIZE:
        raise ValueError("比赛球队球员 source_uid 必须唯一")
    saved_players = roster.get("players")
    if not isinstance(saved_players, list) or len(saved_players) != MATCH_ROSTER_SIZE:
        raise ValueError("真实名单必须为 23 人")
    if roster.get("roster_size", MATCH_ROSTER_SIZE) != MATCH_ROSTER_SIZE:
        raise ValueError("真实名单人数必须为 23")
    for index, player in enumerate(saved_players):
        _validate_saved_player(player, index)
    if len({player["source_uid"] for player in saved_players}) != MATCH_ROSTER_SIZE:
        raise ValueError("真实名单包含重复球员")
    if not any(is_goalkeeper(player) for player in saved_players):
        raise ValueError("真实名单缺少门将")
    lineup = roster.get("lineup")
    if not isinstance(lineup, list) or len(lineup) != STARTERS:
        raise ValueError("真实名单首发必须为 11 名不同球员")
    if any(type(index) is not int or not 0 <= index < MATCH_ROSTER_SIZE for index in lineup):
        raise ValueError("真实名单首发必须为 11 名不同球员")
    if len(set(lineup)) != STARTERS:
        raise ValueError("真实名单首发必须为 11 名不同球员")

    result = copy.deepcopy(dict(team))
    old_players = list(team_players[:MATCH_ROSTER_SIZE])
    new_players: list[dict[str, Any]] = []
    for index, saved in enumerate(saved_players):
        target = copy.deepcopy(dict(saved))
        target.pop("generated", None)
        target["name"] = saved["name"].strip()
        if "native_id" in old_players[index]:
            target["native_id"] = old_players[index]["native_id"]
        else:
            target.pop("native_id", None)
        new_players.append(target)
    result["players"] = new_players
    result["roster_size"] = MATCH_ROSTER_SIZE
    result["lineup"] = list(lineup)
    result.pop("squad", None)

    uid_to_new = {player["source_uid"]: index for index, player in enumerate(new_players)}

    result["captains"] = _remap_references(team.get("captains", []), old_uids, uid_to_new)
    takers = team.get("takers") or {}
    if not isinstance(takers, Mapping):
        raise ValueError("主罚名单格式无效")
    result["takers"] = {
        key: _remap_references(values, old_uids, uid_to_new) for key, values in takers.items()
    }
    raw_setpieces = team.get("setpieces") or {}
    if not isinstance(raw_setpieces, Mapping):
        raise ValueError("定位球配置格式无效")
    setpieces = copy.deepcopy(dict(raw_setpieces))
    priorities = setpieces.get("role_priorities")
    if isinstance(priorities, Mapping):
        setpieces["role_priorities"] = {
            key: _remap_references(values, old_uids, uid_to_new) for key, values in priorities.items()
        }
    result["setpieces"] = setpieces
    return result


def apply_roster_selection(
    team: Mapping[str, Any],
    *,
    starters: Sequence[Mapping[str, Any] | None],
    substitutes: Sequence[Mapping[str, Any] | None],
) -> dict[str, Any]:
    """Apply a partial saved selection to a match team.

    starters and substitutes map one-to-one onto slots 0-10 and 11-22. None or
    the player already occupying the target slot keeps that slot; every other
    entry is validated as a new real player. Native IDs stay tied to the target
    slots and captain/taker/set-piece indices are remapped by source_uid.
    """
    if not isinstance(team, Mapping):
        raise ValueError("球队格式无效")
    team_players = team.get("players")
    if not isinstance(team_players, list) or len(team_players) < MATCH_ROSTER_SIZE:
        raise ValueError("比赛球队至少需要 23 名球员")
    old_players = list(team_players[:MATCH_ROSTER_SIZE])
    if any(not isinstance(item, Mapping) for item in old_players):
        raise ValueError("比赛球队球员格式无效")
    old_uids = [item.get("source_uid") for item in old_players]
    if any(not _valid_uid(uid) for uid in old_uids) or len(set(old_uids)) != MATCH_ROSTER_SIZE:
        raise ValueError("比赛球队球员 source_uid 必须唯一")
    new_players = [copy.deepcopy(dict(item)) for item in old_players]
    for values, offset, count, label in (
        (starters, 0, STARTERS, "首发"),
        (substitutes, STARTERS, BENCH, "替补"),
    ):
        if not isinstance(values, (list, tuple)) or len(values) != count:
            raise ValueError(f"{label}必须恰好 {count} 名球员")
        for position, entry in enumerate(values):
            slot = offset + position
            if entry is None:
                continue
            if not isinstance(entry, Mapping):
                raise ValueError(f"{label}第 {position + 1} 名球员格式无效")
            if entry.get("source_uid") == old_uids[slot]:
                continue
            _validate_saved_player(entry, slot)
            target = copy.deepcopy(dict(entry))
            target.pop("generated", None)
            target["name"] = entry["name"].strip()
            if "native_id" in old_players[slot]:
                target["native_id"] = old_players[slot]["native_id"]
            else:
                target.pop("native_id", None)
            new_players[slot] = target
    new_uids = [item.get("source_uid") for item in new_players]
    if any(not _valid_uid(uid) for uid in new_uids) or len(set(new_uids)) != MATCH_ROSTER_SIZE:
        raise ValueError("阵容球员 source_uid 必须唯一")

    result = copy.deepcopy(dict(team))
    result["players"] = new_players
    result["roster_size"] = MATCH_ROSTER_SIZE
    result["lineup"] = list(range(STARTERS))
    if "substitutes" in result:
        result["substitutes"] = list(range(STARTERS, MATCH_ROSTER_SIZE))
    result.pop("squad", None)

    uid_to_new = {player["source_uid"]: index for index, player in enumerate(new_players)}
    captains = _remap_references(team.get("captains", []), old_uids, uid_to_new)
    result["captains"] = (
        captains or [index for index in range(STARTERS) if not new_players[index].get("generated")][:1]
    )
    raw_takers = team.get("takers") or {}
    if not isinstance(raw_takers, Mapping):
        raise ValueError("主罚名单格式无效")
    result["takers"] = {
        key: _remap_references(values, old_uids, uid_to_new) or list(_default_references(new_players, key))
        for key, values in raw_takers.items()
    }
    raw_setpieces = team.get("setpieces") or {}
    if not isinstance(raw_setpieces, Mapping):
        raise ValueError("定位球配置格式无效")
    setpieces = copy.deepcopy(dict(raw_setpieces))
    priorities = setpieces.get("role_priorities")
    if isinstance(priorities, Mapping):
        setpieces["role_priorities"] = {
            key: _remap_references(values, old_uids, uid_to_new)
            or list(_default_references(new_players, key))
            for key, values in priorities.items()
        }
    result["setpieces"] = setpieces
    return result
