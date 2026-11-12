from __future__ import annotations

import pytest

from fm27lab.domain.roster import is_goalkeeper, normalize_roster


def player(uid: int, position: int, ability: int, name: str | None = None):
    attributes = [10] * 69
    attributes[position] = 18
    return {
        "source_uid": uid,
        "name": name or f"P{uid}",
        "attributes": attributes,
        "ability": ability,
    }


def roster(count: int = 26):
    positions = [0, 3, 3, 4, 2, 5, 7, 7, 8, 9, 11, 12, 12, 2, 4, 6, 6, 8, 8, 9, 11, 12, 12, 13, 14, 10]
    return [player(index + 1, positions[index % len(positions)], 20 - index % 12) for index in range(count)]


def test_26_player_roster_is_trimmed_to_23_with_stable_lineup():
    players = roster(26)
    result = normalize_roster(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 26)),
        captains=[0],
        takers={"penalties": [0, 11]},
        setpiece_priorities={"corners": [2, 3]},
    )
    assert len(result.players) == 23
    assert len(result.lineup) == 11
    assert len(result.substitutes) == 12
    assert result.source_size == 26
    assert len(result.removed) == 3
    assert result.captains == (0,)
    assert set(range(23)) >= set(result.lineup) | set(result.substitutes)


def test_23_player_roster_is_unchanged():
    players = roster(23)
    result = normalize_roster(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 23)),
        captains=[0],
        takers={"penalties": [0]},
        setpiece_priorities={},
    )
    assert len(result.players) == 23
    assert result.removed == ()
    assert result.players == tuple(players)


def test_short_roster_uses_marked_placeholders():
    players = roster(20)
    result = normalize_roster(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 20)),
        captains=[0],
        takers={"penalties": [0]},
        setpiece_priorities={},
    )
    assert len(result.players) == 23
    assert len(result.generated) == 3
    assert all(item.get("generated") is True for item in result.generated)
    assert result.captains == (0,)


def test_roster_without_goalkeeper_is_rejected():
    players = [player(index + 1, 7, 15) for index in range(23)]
    with pytest.raises(ValueError, match="roster_missing_goalkeeper"):
        normalize_roster(players, list(range(11)), list(range(11, 23)), [], {}, {})


def test_one_goalkeeper_is_allowed():
    players = [player(index + 1, 0 if index == 0 else 7, 15) for index in range(23)]
    result = normalize_roster(players, list(range(11)), list(range(11, 23)), [], {}, {})
    assert sum(1 for item in result.players if is_goalkeeper(item)) == 1


def test_removed_captain_and_taker_are_remapped():
    players = roster(26)
    result = normalize_roster(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 26)),
        captains=[25],
        takers={"penalties": [25]},
        setpiece_priorities={"corners": [25]},
    )
    assert 25 not in result.players
    assert result.captains
    assert result.captains[0] < 23
    assert result.takers["penalties"]
    assert all(index < 23 for index in result.takers["penalties"])


def test_generated_players_are_not_captain_or_first_taker():
    players = roster(10)
    result = normalize_roster(
        players=players,
        lineup=list(range(10)),
        substitutes=[],
        captains=[],
        takers={"penalties": []},
        setpiece_priorities={},
    )
    generated_indices = {index for index, item in enumerate(result.players) if item.get("generated")}
    assert result.captains
    assert set(result.captains).isdisjoint(generated_indices)
    assert result.takers["penalties"]
    assert result.takers["penalties"][0] not in generated_indices


def test_normalization_is_deterministic():
    players = roster(26)
    arguments = dict(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 26)),
        captains=[0],
        takers={"penalties": [0, 11]},
        setpiece_priorities={"corners": [2, 3]},
    )
    first = normalize_roster(**arguments)
    second = normalize_roster(**arguments)
    assert first == second
