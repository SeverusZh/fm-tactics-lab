"""场景与名单归一化性质测试。"""

from __future__ import annotations

import copy

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fm27lab.domain.roster import (
    MATCH_ROSTER_SIZE,
    POSITION_SLOTS,
    STARTERS,
    is_goalkeeper,
    player_position,
)
from fm27lab.domain.scenario import normalize_scenario

ATTRIBUTE_COUNT = 69
GOALKEEPER = 0
MIDFIELDER = 7


def player(uid: int, position: int = MIDFIELDER) -> dict:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[position] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes, "ability": 10}


def team(players: list[dict], lineup: list[int] | None = None) -> dict:
    return {
        "name": "Home",
        "players": players,
        "roster_size": len(players),
        "lineup": list(range(STARTERS)) if lineup is None else list(lineup),
        "substitutes": list(range(STARTERS, len(players))),
        "captains": [],
        "takers": {},
        "setpieces": {},
        "phases": [[], []],
    }


def scenario(teams: list[dict]) -> dict:
    return {"schema": 4, "teams": teams, "away_tactic_pool": {"enabled": False, "entries": []}}


def roster(count: int, *, goalkeepers: int = 1, offset: int = 100) -> list[dict]:
    return [
        player(offset + index, GOALKEEPER if index < goalkeepers else MIDFIELDER)
        for index in range(count)
    ]


def normalize(players: list[dict], lineup: list[int] | None = None) -> dict:
    teams = [team(players, lineup), team(roster(MATCH_ROSTER_SIZE))]
    return normalize_scenario(scenario(teams))["teams"][0]


def shuffled(players: list[dict], data) -> list[dict]:
    order = data.draw(st.permutations(range(len(players))))
    return [players[index] for index in order]


def assert_complete_roster(side: dict) -> None:
    players = side["players"]
    assert len(players) == MATCH_ROSTER_SIZE
    assert len({item["source_uid"] for item in players}) == MATCH_ROSTER_SIZE
    assert side["roster_size"] == MATCH_ROSTER_SIZE
    lineup = side["lineup"]
    substitutes = side["substitutes"]
    assert len(lineup) == STARTERS
    assert len(substitutes) == MATCH_ROSTER_SIZE - STARTERS
    assert set(lineup).isdisjoint(substitutes)
    assert set(lineup) | set(substitutes) == set(range(MATCH_ROSTER_SIZE))
    for item in players:
        position = player_position(item)
        assert 0 <= position < len(POSITION_SLOTS)


@settings(max_examples=40, deadline=None, derandomize=True)
@given(st.integers(1, 34), st.integers(0, 10_000), st.data())
def test_normalization_completes_any_roster_size_in_any_order(count, offset, data):
    players = shuffled(roster(count, offset=offset), data)
    side = normalize(players)
    assert_complete_roster(side)
    kept = {item["source_uid"] for item in side["players"]}
    source = {item["source_uid"] for item in players}
    if count <= MATCH_ROSTER_SIZE:
        assert source <= kept
    else:
        assert kept <= source


@settings(max_examples=30, deadline=None, derandomize=True)
@given(st.integers(1, 34), st.data())
def test_second_normalization_is_a_fixed_point(count, data):
    players = shuffled(roster(count), data)
    first = normalize_scenario(scenario([team(players), team(roster(MATCH_ROSTER_SIZE))]))
    second = normalize_scenario(first)
    third = normalize_scenario(second)
    assert second == third
    for before, after in zip(first["teams"], second["teams"], strict=True):
        assert after["roster_size"] == before["roster_size"]
        for key in ("players", "lineup", "substitutes", "captains", "takers", "setpieces"):
            assert after[key] == before[key]


@settings(max_examples=30, deadline=None, derandomize=True)
@given(st.integers(1, 20), st.integers(1, 3), st.data())
def test_starting_lineup_holds_exactly_one_goalkeeper(count, requested, data):
    goalkeepers = min(count, requested)
    players = shuffled(roster(count, goalkeepers=goalkeepers), data)
    side = normalize(players)
    starters = [side["players"][index] for index in side["lineup"]]
    assert sum(1 for item in starters if is_goalkeeper(item)) == 1
    assert any(is_goalkeeper(item) for item in side["players"])


@settings(max_examples=20, deadline=None, derandomize=True)
@given(st.integers(12, 30))
def test_lineup_without_goalkeeper_is_repaired(count):
    side = normalize(roster(count), list(range(1, STARTERS + 1)))
    starters = [side["players"][index] for index in side["lineup"]]
    assert sum(1 for item in starters if is_goalkeeper(item)) == 1


@settings(max_examples=25, deadline=None, derandomize=True)
@given(st.integers(1, MATCH_ROSTER_SIZE - 1))
def test_short_rosters_are_completed_with_generated_placeholders(count):
    side = normalize(roster(count))
    generated = [item for item in side["players"] if item.get("generated")]
    assert len(generated) == MATCH_ROSTER_SIZE - count
    generated_uids = {item["source_uid"] for item in generated}
    source_uids = {item["source_uid"] for item in side["players"] if not item.get("generated")}
    assert generated_uids.isdisjoint(source_uids)


@settings(max_examples=20, deadline=None, derandomize=True)
@given(st.integers(MATCH_ROSTER_SIZE + 1, 40), st.integers(0, 10_000))
def test_oversized_rosters_report_trimmed_players(count, offset):
    players = roster(count, offset=offset)
    side = normalize(players)
    assert_complete_roster(side)
    trim = side["roster_trim"]
    assert trim["source_size"] == count
    assert len(trim["removed"]) == count - MATCH_ROSTER_SIZE
    kept = {item["source_uid"] for item in side["players"]}
    removed = {row["source_uid"] for row in trim["removed"]}
    assert removed.isdisjoint(kept)
    assert kept | removed == {item["source_uid"] for item in players}


@settings(max_examples=20, deadline=None, derandomize=True)
@given(st.integers(2, 30), st.integers(0, 10_000))
def test_duplicate_source_uids_are_rejected(count, offset):
    players = roster(count, offset=offset)
    players.append(copy.deepcopy(players[1]))
    with pytest.raises(ValueError, match="source_uid 重复"):
        normalize(players)


@settings(max_examples=20, deadline=None, derandomize=True)
@given(st.integers(1, 30))
def test_rosters_without_goalkeeper_are_rejected(count):
    with pytest.raises(ValueError, match="门将"):
        normalize(roster(count, goalkeepers=0))


def test_empty_roster_is_rejected():
    with pytest.raises(ValueError, match="球员列表"):
        normalize([])


@pytest.mark.parametrize("count", [0, 1, 3])
def test_scenario_requires_two_teams(count):
    teams = [team(roster(MATCH_ROSTER_SIZE)) for _ in range(count)]
    with pytest.raises(ValueError, match="两支球队"):
        normalize_scenario({"schema": 4, "teams": teams})


@settings(max_examples=20, deadline=None, derandomize=True)
@given(st.integers(1, 34), st.data())
def test_normalization_does_not_mutate_input(count, data):
    players = shuffled(roster(count), data)
    value = scenario([team(players), team(roster(MATCH_ROSTER_SIZE, offset=500))])
    snapshot = copy.deepcopy(value)
    normalize_scenario(value)
    assert value == snapshot
