from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

POSITION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("GK",),
    ("SW",),
    ("DL", "DC", "DR"),
    ("DM",),
    ("ML", "MC", "MR"),
    ("AML", "AMC", "AMR"),
    ("ST",),
    ("WBL", "WBR"),
)
POSITION_INDEX = {
    name: index
    for index, name in enumerate(
        ("GK", "SW", "DL", "DC", "DR", "DM", "ML", "MC", "MR", "AML", "AMC", "AMR", "ST", "WBL", "WBR")
    )
}
MATCH_ROSTER_SIZE = 23
STARTERS = 11
BENCH = MATCH_ROSTER_SIZE - STARTERS


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
    visible = attributes[15:] or attributes
    return float(sum(visible) / len(visible)) if visible else 0.0


def is_goalkeeper(player: Mapping[str, Any]) -> bool:
    return player_position(player) == POSITION_INDEX["GK"]


def _sort_key(item: tuple[int, Mapping[str, Any]]) -> tuple[float, str, int]:
    index, player = item
    return (-player_ability(player), str(player.get("source_uid", index)), index)


def _unique_indices(values: Iterable[int], size: int) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if isinstance(value, int) and 0 <= value < size and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _fill(
    candidates: list[int],
    players: Sequence[Mapping[str, Any]],
    count: int,
) -> list[int]:
    chosen: list[int] = []
    remaining = list(candidates)
    for group in POSITION_GROUPS:
        matched = [
            index
            for index in remaining
            if player_position(players[index]) in {POSITION_INDEX[name] for name in group}
        ]
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
        chosen.append(index)
    return chosen


def _generated(index: int) -> dict[str, Any]:
    attributes = [10] * 69
    for position in range(15):
        attributes[position] = 15
    return {
        "source_uid": f"generated:{index}",
        "name": f"占位球员 {index}",
        "attributes": attributes,
        "ability": 10,
        "generated": True,
    }


def _default_references(selected: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    candidates = [
        index
        for index, player in enumerate(selected)
        if not player.get("generated") and not is_goalkeeper(player)
    ]
    candidates.sort(key=lambda index: _sort_key((index, selected[index])))
    return tuple(candidates[:3])


def normalize_roster(
    players: Sequence[Mapping[str, Any]],
    lineup: Sequence[int] = (),
    substitutes: Sequence[int] = (),
    captains: Sequence[int] = (),
    takers: Mapping[str, Sequence[int]] | None = None,
    setpiece_priorities: Mapping[str, Sequence[int]] | None = None,
) -> RosterResult:
    source = [dict(player) for player in players]
    if not source:
        raise ValueError("roster_empty")
    if not any(is_goalkeeper(player) for player in source):
        raise ValueError("roster_missing_goalkeeper")
    takers = {key: list(values) for key, values in (takers or {}).items()}
    setpiece_priorities = {key: list(values) for key, values in (setpiece_priorities or {}).items()}

    starters = _unique_indices(lineup, len(source))[:STARTERS]
    remaining = [index for index in range(len(source)) if index not in set(starters)]
    starters.extend(_fill(remaining, source, STARTERS - len(starters)))

    selected_orig = list(starters)
    if not any(is_goalkeeper(source[index]) for index in selected_orig):
        goalkeepers = [index for index in range(len(source)) if is_goalkeeper(source[index])]
        replacement = min(goalkeepers, key=lambda index: _sort_key((index, source[index])))
        replace_at = next(
            (
                position
                for position in range(len(selected_orig) - 1, -1, -1)
                if not is_goalkeeper(source[selected_orig[position]])
            ),
            None,
        )
        if replace_at is None:
            raise ValueError("roster_missing_goalkeeper")
        selected_orig[replace_at] = replacement

    bench = [index for index in _unique_indices(substitutes, len(source)) if index not in set(selected_orig)]
    remaining = [
        index for index in range(len(source)) if index not in set(selected_orig) and index not in set(bench)
    ]
    bench.extend(_fill(remaining, source, BENCH - len(bench)))
    selected_entries: list[tuple[int | None, dict[str, Any]]] = [
        (index, source[index]) for index in selected_orig
    ]
    selected_entries.extend((index, source[index]) for index in bench)

    generated_count = 0
    while len(selected_entries) < MATCH_ROSTER_SIZE:
        generated_count += 1
        selected_entries.append((None, _generated(generated_count)))

    selected_entries = selected_entries[:MATCH_ROSTER_SIZE]
    selected = [player for _, player in selected_entries]
    source_to_new = {
        original: new for new, (original, _) in enumerate(selected_entries) if original is not None
    }
    removed = tuple(
        {
            "source_uid": player.get("source_uid", index),
            "name": player.get("name", f"P{index + 1}"),
        }
        for index, player in enumerate(source)
        if index not in source_to_new
    )
    generated = tuple(player for player in selected if player.get("generated"))

    mapped_captains = tuple(
        source_to_new[index] for index in _unique_indices(captains, len(source)) if index in source_to_new
    )
    if not mapped_captains:
        mapped_captains = tuple(
            index for index, player in enumerate(selected) if index < STARTERS and not player.get("generated")
        )[:1]
    default = _default_references(selected)
    mapped_takers = {
        key: tuple(source_to_new[index] for index in values if index in source_to_new)
        for key, values in takers.items()
    }
    for key, values in mapped_takers.items():
        if not values:
            mapped_takers[key] = default
    mapped_setpieces = {
        key: tuple(source_to_new[index] for index in values if index in source_to_new)
        for key, values in setpiece_priorities.items()
    }
    for key, values in mapped_setpieces.items():
        if not values:
            mapped_setpieces[key] = default

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
