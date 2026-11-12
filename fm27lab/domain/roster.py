from __future__ import annotations

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
            "setpiece_priorities": {
                key: list(values) for key, values in self.setpiece_priorities.items()
            },
        }


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
        if uid in mapping:
            raise ValueError("roster_duplicate_source_uid")
        mapping[uid] = index
    return mapping


def _fill(
    candidates: list[int],
    players: Sequence[Mapping[str, Any]],
    count: int,
    allow_goalkeeper: bool,
) -> list[int]:
    chosen: list[int] = []
    remaining = list(candidates)
    for group in POSITION_GROUPS:
        slots = {POSITION_INDEX[name] for name in group}
        if not allow_goalkeeper and slots == {POSITION_INDEX["GK"]}:
            continue
        matched = [index for index in remaining if player_position(players[index]) in slots]
        if group == ("GK",):
            matched.sort(key=lambda index: _gk_key((index, players[index])))
            matched = matched[:1]
        else:
            matched.sort(key=lambda index: _sort_key((index, players[index])))
        for index in matched:
            if len(chosen) >= count:
                break
            chosen.append(index)
            remaining.remove(index)
        if len(chosen) >= count:
            break
    for index in sorted(remaining, key=lambda index: _sort_key((index, players[index]))):
        if len(chosen) >= count:
            break
        if not allow_goalkeeper and is_goalkeeper(players[index]):
            continue
        chosen.append(index)
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
    starter_entries: list[tuple[int | None, dict[str, Any]]] = [
        (index, source[index]) for index in starters
    ]
    while len(starter_entries) < STARTERS:
        generated_count += 1
        starter_entries.append((None, _generated(generated_count, used_uids)))

    bench = [index for index in _unique_indices(substitutes, len(source)) if index not in set(starters)]
    remaining = [
        index for index in range(len(source)) if index not in set(starters) and index not in set(bench)
    ]
    bench.extend(_fill(remaining, source, BENCH - len(bench), allow_goalkeeper=True))
    bench_entries: list[tuple[int | None, dict[str, Any]]] = [
        (index, source[index]) for index in bench
    ][:BENCH]
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
