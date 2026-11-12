from __future__ import annotations

import pytest

from fm27lab.domain.roster import (
    POSITION_ALIASES,
    canonical_position,
    is_goalkeeper,
    normalize_roster,
    player_ability,
)


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


def uid(value: int) -> int:
    return value


def test_26_player_roster_is_trimmed_with_source_identity():
    players = roster(26)
    result = normalize_roster(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 26)),
        captains=[uid(1)],
        takers={"penalties": [uid(1), uid(12)]},
        setpiece_priorities={"corners": [uid(3), uid(4)]},
    )
    assert len(result.players) == 23
    assert len(result.lineup) == 11
    assert len(result.substitutes) == 12
    assert result.source_size == 26
    assert [player["source_uid"] for player in result.removed] == [24, 25, 26]
    assert [result.players[index]["source_uid"] for index in result.lineup] == list(range(1, 12))
    assert [result.players[index]["source_uid"] for index in result.substitutes] == list(range(12, 24))
    assert result.captains == (0,)
    assert result.takers["penalties"] == (0, 11)
    assert result.setpiece_priorities["corners"] == (2, 3)
    assert result.roster_trim["removed"] == list(result.removed)


def test_23_player_roster_is_unchanged():
    players = roster(23)
    result = normalize_roster(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 23)),
        captains=[uid(1)],
        takers={"penalties": [uid(1)]},
        setpiece_priorities={},
    )
    assert len(result.players) == 23
    assert result.removed == ()
    assert result.players == tuple(players)


def test_short_roster_uses_marked_placeholders_with_neutral_profile():
    players = roster(20)
    result = normalize_roster(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 20)),
        captains=[uid(1)],
        takers={"penalties": [uid(1)]},
        setpiece_priorities={},
    )
    assert len(result.players) == 23
    assert len(result.generated) == 3
    for generated in result.generated:
        assert generated["generated"] is True
        assert is_goalkeeper(generated) is False
        assert generated["attributes"][7] == 15
        assert generated["attributes"][39] == 10
        assert generated["attributes"][40] == 10
        assert generated["attributes"][56] == 5
        assert generated["attributes"][63] == 5
    assert result.captains == (0,)


def test_roster_without_goalkeeper_is_rejected():
    players = [player(index + 1, 7, 15) for index in range(23)]
    with pytest.raises(ValueError, match="roster_missing_goalkeeper"):
        normalize_roster(players, list(range(11)), list(range(11, 23)), [], {}, {})


def test_empty_roster_is_rejected():
    with pytest.raises(ValueError, match="roster_empty"):
        normalize_roster([], [], [], [], {}, {})


def test_one_goalkeeper_is_allowed():
    players = [player(index + 1, 0 if index == 0 else 7, 15) for index in range(23)]
    result = normalize_roster(players, list(range(1, 12)), list(range(11, 23)), [], {}, {})
    assert sum(1 for item in result.players if is_goalkeeper(item)) == 1


def test_two_goalkeepers_never_both_start_and_best_familiarity_wins():
    players = [player(1, 0, 30), player(2, 0, 5)]
    players[0]["attributes"][0] = 18
    players[1]["attributes"][0] = 20
    players.extend(player(index + 3, 7, 10) for index in range(21))
    result = normalize_roster(players, list(range(2, 13)), [], [], {}, {})
    starters = result.players[:11]
    assert sum(1 for item in starters if is_goalkeeper(item)) == 1
    goalkeeper = next(item for item in starters if is_goalkeeper(item))
    assert goalkeeper["source_uid"] == 2


def test_removed_captain_and_taker_are_remapped_by_uid():
    players = roster(26)
    result = normalize_roster(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 26)),
        captains=[uid(26)],
        takers={"penalties": [uid(26)]},
        setpiece_priorities={"corners": [uid(26)]},
    )
    assert [item["source_uid"] for item in result.removed] == [24, 25, 26]
    assert result.captains == (0,)
    assert 25 not in [item["source_uid"] for item in result.players]
    assert result.takers["penalties"]
    assert result.setpiece_priorities["corners"]
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


def test_ability_fallback_uses_visible_41_and_ignores_hidden():
    player_with_hidden = player(1, 7, 0)
    player_with_hidden.pop("ability")
    player_with_hidden["attributes"][7] = 10
    player_with_hidden["attributes"][41] = 20
    for index in (39, 40, 56, 59, 62, 63, 64):
        player_with_hidden["attributes"][index] = 20
    assert player_ability(player_with_hidden) > 10.0
    hidden_only = player(2, 7, 0)
    hidden_only.pop("ability")
    hidden_only["attributes"][7] = 10
    for index in (39, 40, 56, 59, 62, 63, 64):
        hidden_only["attributes"][index] = 20
    assert player_ability(hidden_only) == 10.0


def test_missing_and_duplicate_source_uids_are_rejected():
    missing = player(1, 7, 10)
    missing.pop("source_uid")
    with pytest.raises(ValueError, match="roster_missing_source_uid"):
        normalize_roster([missing], [], [], [], {}, {})
    duplicate = [player(1, 0, 10), player(1, 7, 10)]
    with pytest.raises(ValueError, match="roster_duplicate_source_uid"):
        normalize_roster(duplicate, [], [], [], {}, {})


def test_non_identity_lineup_order_is_preserved():
    players = roster(23)
    order = [5, 6, 7, 8, 9, 10, 0, 1, 2, 3, 4]
    result = normalize_roster(players, order, list(range(11, 23)), [], {}, {})
    assert [result.players[index]["source_uid"] for index in result.lineup] == [
        players[index]["source_uid"] for index in order
    ]


def test_more_than_twelve_substitutes_are_truncated():
    players = roster(26)
    result = normalize_roster(players, list(range(11)), list(range(11, 26)), [], {}, {})
    assert len(result.substitutes) == 12
    assert len(result.removed) == 3


def test_normalization_is_deterministic():
    players = roster(26)
    arguments = dict(
        players=players,
        lineup=list(range(11)),
        substitutes=list(range(11, 26)),
        captains=[uid(1)],
        takers={"penalties": [uid(1), uid(12)]},
        setpiece_priorities={"corners": [uid(3), uid(4)]},
    )
    assert normalize_roster(**arguments) == normalize_roster(**arguments)


def _two_goalkeepers():
    players = [player(1, 0, 30), player(2, 0, 5)]
    players[0]["attributes"][0] = 18
    players[1]["attributes"][0] = 20
    players.extend(player(index + 3, 7, 10) for index in range(21))
    return players


def test_goalkeeper_fill_never_adds_two_starters_and_uses_familiarity():
    players = _two_goalkeepers()
    result = normalize_roster(players, [], [], [], {}, {})
    starters = result.players[:11]
    goalkeepers = [item for item in starters if is_goalkeeper(item)]
    assert len(goalkeepers) == 1
    assert goalkeepers[0]["source_uid"] == 2


def test_nine_outfield_starters_fill_one_goalkeeper():
    players = _two_goalkeepers()
    result = normalize_roster(players, list(range(2, 11)), [], [], {}, {})
    starters = result.players[:11]
    assert sum(1 for item in starters if is_goalkeeper(item)) == 1


def test_ten_outfield_starters_fill_one_goalkeeper_by_familiarity():
    players = _two_goalkeepers()
    result = normalize_roster(players, list(range(2, 12)), [], [], {}, {})
    starter = next(item for item in result.players[:11] if is_goalkeeper(item))
    assert starter["source_uid"] == 2


def test_visible_attribute_41_contributes_to_ability_fallback():
    visible = player(1, 7, 0)
    visible.pop("ability")
    visible["attributes"][7] = 10
    visible["attributes"][41] = 20
    hidden_only = player(2, 7, 0)
    hidden_only.pop("ability")
    hidden_only["attributes"][7] = 10
    for index in (39, 40, 56, 59, 62, 63, 64):
        hidden_only["attributes"][index] = 20
    assert player_ability(hidden_only) == 10.0
    assert player_ability(visible) > 10.0


def test_non_identity_uid_references_are_remapped():
    players = roster(23)
    order = [5, 6, 7, 8, 9, 10, 0, 1, 2, 3, 4]
    result = normalize_roster(
        players,
        order,
        list(range(11, 23)),
        captains=[players[5]["source_uid"]],
        takers={"penalties": [players[6]["source_uid"]]},
        setpiece_priorities={"corners": [players[7]["source_uid"]]},
    )
    assert result.captains == (0,)
    assert result.takers["penalties"] == (1,)
    assert result.setpiece_priorities["corners"] == (2,)


def test_invalid_indices_do_not_replace_valid_starters():
    players = roster(23)
    result = normalize_roster(players, [999, -1, 0, 0, 1, 2, 3, 4, 5, 6, 7], [], [], {}, {})
    assert [item["source_uid"] for item in result.players[:8]] == list(range(1, 9))


def test_default_corner_taker_prefers_wide_position():
    players = [player(1, 0, 10), player(2, 2, 10), player(3, 3, 20)]
    players.extend(player(index + 4, 7, 10) for index in range(20))
    result = normalize_roster(players, list(range(11)), list(range(11, 23)), [], {"corners": []}, {})
    first = result.players[result.takers["corners"][0]]
    assert first["source_uid"] == 2


def test_position_aliases_cover_all_composite_catalog_names():
    assert len(POSITION_ALIASES) == 11
    for alias, canonical in POSITION_ALIASES.items():
        assert canonical_position(alias) == canonical
        assert canonical in {
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
        }


def test_generated_uids_do_not_collide_with_source_uids():
    players = [player(1, 0, 10)]
    players.append({**player(99, 7, 10), "source_uid": "generated:1"})
    players.extend(player(index + 10, 7, 10) for index in range(20))
    result = normalize_roster(players, [0], [], [], {}, {})
    uids = [item["source_uid"] for item in result.players]
    assert len(uids) == len(set(uids))


def test_short_two_goalkeeper_roster_never_starts_two():
    players = [player(1, 0, 20), player(2, 0, 10)]
    players.extend(player(index + 3, 7, 10) for index in range(7))
    result = normalize_roster(players, [], [], [], {}, {})
    starters = result.players[:11]
    assert sum(1 for item in starters if is_goalkeeper(item)) == 1
    assert any(item.get("generated") for item in starters)


def test_short_three_goalkeeper_roster_never_starts_two():
    players = [player(1, 0, 20), player(2, 0, 10), player(3, 0, 5)]
    players.extend(player(index + 4, 7, 10) for index in range(7))
    result = normalize_roster(players, [], [], [], {}, {})
    starters = result.players[:11]
    assert sum(1 for item in starters if is_goalkeeper(item)) == 1


def test_second_goalkeeper_goes_to_bench_before_generated_padding():
    players = [player(1, 0, 20), player(2, 0, 10), player(3, 7, 10)]
    result = normalize_roster(players, [0], [1], [], {}, {})
    assert sum(1 for item in result.players[:11] if is_goalkeeper(item)) == 1
    assert result.players[11]["source_uid"] == 2
    assert result.players[11].get("generated") is not True


def test_roster_trim_includes_remapped_references():
    players = roster(26)
    result = normalize_roster(
        players,
        list(range(11)),
        list(range(11, 26)),
        captains=[players[0]["source_uid"]],
        takers={"penalties": [players[1]["source_uid"]]},
        setpiece_priorities={"corners": [players[2]["source_uid"]]},
    )
    assert result.roster_trim["captains"] == list(result.captains)
    assert result.roster_trim["takers"]["penalties"] == list(result.takers["penalties"])
    assert result.roster_trim["setpiece_priorities"]["corners"] == list(result.setpiece_priorities["corners"])
