from __future__ import annotations

import copy

import pytest

from fm27lab.domain.roster import apply_roster_selection, apply_saved_roster


def player(uid, position=7, ability=10, name=None):
    attributes = [10] * 69
    attributes[position] = 18
    return {
        "source_uid": uid,
        "name": name or f"P{uid}",
        "attributes": attributes,
        "ability": ability,
    }


def team(count=23):
    players = [player(100 + index, 0 if index == 0 else 7) for index in range(count)]
    for index, item in enumerate(players):
        item["native_id"] = 5000 + index
    return {
        "name": "Home",
        "players": players,
        "roster_size": count,
        "lineup": list(range(11)),
        "captains": [5, 99],
        "takers": {"penalties": [6, 99], "corners": [7]},
        "setpieces": {"role_priorities": {"8": [8, 99]}, "routines": {}},
    }


def roster(count=23, order=None):
    players = [player(100 + index, 0 if index == 0 else 7) for index in range(count)]
    order = order or list(range(count))
    return {
        "club_uid": 7,
        "club": "Away",
        "coach": "Coach",
        "source": "real_ai",
        "roster_size": count,
        "lineup": list(range(11)),
        "players": [players[index] for index in order],
    }


def test_apply_saved_roster_replaces_23_and_remaps_references_by_uid():
    original = team()
    snapshot = copy.deepcopy(original)
    result = apply_saved_roster(original, roster())
    assert original == snapshot
    assert len(result["players"]) == 23
    assert [p["source_uid"] for p in result["players"]] == list(range(100, 123))
    assert result["players"][0]["native_id"] == 5000
    assert result["roster_size"] == 23
    assert result["lineup"] == list(range(11))
    assert result["captains"] == [5]
    assert result["takers"]["penalties"] == [6]
    assert result["takers"]["corners"] == [7]
    assert result["setpieces"]["role_priorities"]["8"] == [8]


def test_reordered_roster_moves_references_to_new_index():
    original = team()
    order = [5, 6, 7, 8, 9, 10, 0, 1, 2, 3, 4, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
    saved = roster(order=order)
    result = apply_saved_roster(original, saved)
    new_index = {100 + old: new for new, old in enumerate(order)}
    assert result["captains"] == [new_index[105]]
    assert result["takers"]["penalties"] == [new_index[106]]
    assert result["takers"]["corners"] == [new_index[107]]
    assert result["setpieces"]["role_priorities"]["8"] == [new_index[108]]


def test_apply_saved_roster_rejects_non_23_or_duplicate_or_invalid_lineup():
    with pytest.raises(ValueError, match="23"):
        apply_saved_roster(team(), roster(22))
    with pytest.raises(ValueError, match="23"):
        apply_saved_roster(team(), roster(24))
    duplicate = roster()
    duplicate["players"][1] = copy.deepcopy(duplicate["players"][0])
    with pytest.raises(ValueError, match="重复"):
        apply_saved_roster(team(), duplicate)
    bad_lineup = roster()
    bad_lineup["lineup"] = [0] * 11
    with pytest.raises(ValueError, match="首发"):
        apply_saved_roster(team(), bad_lineup)
    out_of_range = roster()
    out_of_range["lineup"] = list(range(10)) + [23]
    with pytest.raises(ValueError, match="首发"):
        apply_saved_roster(team(), out_of_range)


def test_apply_saved_roster_requires_a_goalkeeper():
    saved = roster()
    for item in saved["players"]:
        item["attributes"][0] = 1
        item["attributes"][7] = 18
    with pytest.raises(ValueError, match="门将"):
        apply_saved_roster(team(), saved)


def test_apply_saved_roster_requires_23_team_players():
    with pytest.raises(ValueError, match="23"):
        apply_saved_roster(team(22), roster())


def test_apply_saved_roster_rejects_generated_players_and_bad_attributes():
    saved = roster()
    saved["players"][0]["generated"] = True
    with pytest.raises(ValueError, match="generated"):
        apply_saved_roster(team(), saved)
    bad = roster()
    bad["players"][0]["attributes"] = [10] * 68
    with pytest.raises(ValueError, match="69"):
        apply_saved_roster(team(), bad)


def test_apply_saved_roster_accepts_missing_reference_groups():
    original = team()
    original.pop("captains")
    original.pop("takers")
    original.pop("setpieces")
    result = apply_saved_roster(original, roster())
    assert result["captains"] == []
    assert result["takers"] == {}
    assert result["setpieces"] == {}


def test_apply_saved_roster_rejects_invalid_uid_name_profile_and_team_duplicates():
    bad_uid = roster()
    bad_uid["players"][0]["source_uid"] = ["not", "hashable"]
    with pytest.raises(ValueError, match="source_uid"):
        apply_saved_roster(team(), bad_uid)
    bad_name = roster()
    bad_name["players"][0]["name"] = "a\nb"
    with pytest.raises(ValueError, match="名称"):
        apply_saved_roster(team(), bad_name)
    bad_profile = roster()
    bad_profile["players"][0]["native_profile"] = "bad"
    with pytest.raises(ValueError, match="扩展"):
        apply_saved_roster(team(), bad_profile)
    duplicate_team = team()
    duplicate_team["players"][1]["source_uid"] = duplicate_team["players"][0]["source_uid"]
    with pytest.raises(ValueError, match="唯一"):
        apply_saved_roster(duplicate_team, roster())


def test_output_uses_saved_ability_and_does_not_inherit_host_generated_or_extras():
    original = team()
    original["players"][0]["generated"] = True
    original["players"][0]["old_extra"] = "host-only"
    saved = roster()
    saved["players"][0]["ability"] = 99
    saved["players"][0]["saved_extra"] = "saved-only"
    result = apply_saved_roster(original, saved)
    player = result["players"][0]
    assert player["ability"] == 99
    assert "generated" not in player
    assert "old_extra" not in player
    assert player["saved_extra"] == "saved-only"
    assert player["native_id"] == 5000


def test_team_with_26_players_is_trimmed_and_native_ids_are_preserved():
    result = apply_saved_roster(team(26), roster())
    assert len(result["players"]) == 23
    assert [item["native_id"] for item in result["players"]] == list(range(5000, 5023))


def test_apply_saved_roster_rejects_truthy_generated_and_invalid_uid_shapes():
    for marker in (1, "yes"):
        saved = roster()
        saved["players"][0]["generated"] = marker
        with pytest.raises(ValueError, match="generated"):
            apply_saved_roster(team(), saved)
    for uid in ("bad\nuid", "   "):
        saved = roster()
        saved["players"][0]["source_uid"] = uid
        with pytest.raises(ValueError, match="source_uid"):
            apply_saved_roster(team(), saved)
    broken_team = team()
    broken_team["players"][0]["source_uid"] = ["x"]
    with pytest.raises(ValueError, match="source_uid"):
        apply_saved_roster(broken_team, roster())


def test_unhashable_lineup_and_invalid_attribute_types_are_value_errors():
    saved = roster()
    saved["lineup"] = [[]] + list(range(1, 11))
    with pytest.raises(ValueError, match="首发"):
        apply_saved_roster(team(), saved)
    bad_type = roster()
    bad_type["players"][0]["attributes"][15] = "10"
    with pytest.raises(ValueError, match="整数"):
        apply_saved_roster(team(), bad_type)
    bad_range = roster()
    bad_range["players"][0]["attributes"][0] = 21
    with pytest.raises(ValueError, match="熟练度"):
        apply_saved_roster(team(), bad_range)


def test_native_profile_is_copied_or_removed_and_roster_is_not_mutated():
    original = team()
    original["players"][0]["native_profile"] = {"current_ability": 1}
    saved = roster()
    saved["players"][0]["native_profile"] = {"current_ability": 150}
    snapshot = copy.deepcopy(saved)
    result = apply_saved_roster(original, saved)
    assert result["players"][0]["native_profile"] == {"current_ability": 150}
    assert saved == snapshot
    saved["players"][0].pop("native_profile")
    result = apply_saved_roster(original, saved)
    assert "native_profile" not in result["players"][0]


def test_native_id_only_comes_from_host_and_name_is_stripped():
    original = team()
    original["players"][0].pop("native_id")
    saved = roster()
    saved["players"][0]["native_id"] = 9999
    saved["players"][0]["name"] = "  Alice  "
    result = apply_saved_roster(original, saved)
    assert "native_id" not in result["players"][0]
    assert result["players"][0]["name"] == "Alice"


def test_invalid_ability_and_reference_group_types_are_value_errors():
    saved = roster()
    saved["players"][0]["ability"] = "99"
    with pytest.raises(ValueError, match="能力"):
        apply_saved_roster(team(), saved)
    bad_takers = team()
    bad_takers["takers"] = [1]
    with pytest.raises(ValueError, match="主罚"):
        apply_saved_roster(bad_takers, roster())
    bad_setpieces = team()
    bad_setpieces["setpieces"] = [1]
    with pytest.raises(ValueError, match="定位球"):
        apply_saved_roster(bad_setpieces, roster())


def test_setpiece_routines_without_role_priorities_are_preserved():
    original = team()
    original["setpieces"] = {"routines": {"1": [{"name": "corner"}]}}
    result = apply_saved_roster(original, roster())
    assert result["setpieces"] == original["setpieces"]


def generated(uid):
    attributes = [10] * 69
    attributes[7] = 15
    return {
        "source_uid": uid,
        "name": f"占位 {uid}",
        "attributes": attributes,
        "ability": 10,
        "generated": True,
    }


def selection_players(base, count):
    return [player(base + index, 0 if index == 0 else 12, ability=12) for index in range(count)]


def test_apply_roster_selection_writes_starters_and_keeps_bench_placeholders():
    original = team()
    original["players"][11:] = [generated(f"generated:{index}") for index in range(1, 13)]
    snapshot = copy.deepcopy(original)

    result = apply_roster_selection(
        original,
        starters=selection_players(300, 11),
        substitutes=snapshot["players"][11:],
    )

    assert original == snapshot
    assert [item["source_uid"] for item in result["players"][:11]] == list(range(300, 311))
    assert [item["native_id"] for item in result["players"][:11]] == list(range(5000, 5011))
    assert result["players"][11:] == snapshot["players"][11:]
    assert all(item["generated"] is True for item in result["players"][11:])
    assert result["lineup"] == list(range(11))
    assert result["roster_size"] == 23
    assert result["captains"] == [0]
    assert result["takers"]["penalties"] == [1, 2, 3]
    assert result["takers"]["corners"] == [1, 2, 3]
    assert result["setpieces"]["role_priorities"]["8"] == [1, 2, 3]
    assert result["setpieces"]["routines"] == {}


def test_apply_roster_selection_writes_bench_and_keeps_placeholder_starters():
    original = team()
    original["players"][:11] = [generated(f"generated:{index}") for index in range(1, 12)]
    snapshot = copy.deepcopy(original)

    result = apply_roster_selection(
        original,
        starters=snapshot["players"][:11],
        substitutes=[player(400 + index, 7, ability=12) for index in range(12)],
    )

    assert original == snapshot
    assert result["players"][:11] == snapshot["players"][:11]
    assert [item["source_uid"] for item in result["players"][11:]] == list(range(400, 412))
    assert [item["native_id"] for item in result["players"][11:]] == list(range(5011, 5023))
    assert result["lineup"] == list(range(11))
    assert result["captains"] == [5]
    assert result["takers"]["penalties"] == [6]
    assert result["takers"]["corners"] == [7]
    assert result["setpieces"]["role_priorities"]["8"] == [8]


def test_apply_roster_selection_keeps_unprovided_slots():
    original = team()
    snapshot = copy.deepcopy(original)
    starters = [player(300 + index) if index % 2 == 0 else None for index in range(11)]

    result = apply_roster_selection(original, starters=starters, substitutes=[None] * 12)

    assert original == snapshot
    assert [item["source_uid"] for item in result["players"][:11]] == [
        300 + index if index % 2 == 0 else 100 + index for index in range(11)
    ]
    assert result["players"][11:] == snapshot["players"][11:]


def test_apply_roster_selection_requires_eleven_starters_and_twelve_substitutes():
    starters = selection_players(300, 11)
    substitutes = [player(400 + index) for index in range(12)]
    for value in (starters[:10], starters + [player(999)], None, "bad"):
        with pytest.raises(ValueError, match="11"):
            apply_roster_selection(team(), starters=value, substitutes=substitutes)
    for value in (substitutes[:11], substitutes + [player(999)], None, "bad"):
        with pytest.raises(ValueError, match="12"):
            apply_roster_selection(team(), starters=starters, substitutes=value)


def test_apply_roster_selection_rejects_duplicate_source_uids():
    starters = selection_players(300, 11)
    substitutes = [player(400 + index) for index in range(12)]
    duplicated = [copy.deepcopy(item) for item in starters]
    duplicated[1] = copy.deepcopy(duplicated[0])
    with pytest.raises(ValueError, match="唯一"):
        apply_roster_selection(team(), starters=duplicated, substitutes=substitutes)
    colliding = [copy.deepcopy(item) for item in substitutes]
    colliding[0]["source_uid"] = 300
    with pytest.raises(ValueError, match="唯一"):
        apply_roster_selection(team(), starters=starters, substitutes=colliding)


def test_apply_roster_selection_rejects_generated_placeholders_as_new_players():
    starters = selection_players(300, 11)
    substitutes = [player(400 + index) for index in range(12)]
    replaced_starter = list(starters)
    replaced_starter[2] = generated("generated:99")
    with pytest.raises(ValueError, match="generated"):
        apply_roster_selection(team(), starters=replaced_starter, substitutes=substitutes)
    replaced_substitute = list(substitutes)
    replaced_substitute[0] = generated("generated:98")
    with pytest.raises(ValueError, match="generated"):
        apply_roster_selection(team(), starters=starters, substitutes=replaced_substitute)


def test_apply_roster_selection_falls_back_references_removed_from_selection():
    starters = [
        player(300, 0, ability=1),
        player(301, 12, ability=20),
        player(302, 10, ability=15),
        player(303, 7, ability=5),
        player(304, 2, ability=18),
        player(305, 8, ability=14),
        player(306, 9, ability=12),
        player(307, 12, ability=4),
        player(308, 12, ability=3),
        player(309, 12, ability=2),
        player(310, 12, ability=1),
    ]
    substitutes = [player(400 + index, 7, ability=1) for index in range(12)]

    result = apply_roster_selection(team(), starters=starters, substitutes=substitutes)

    assert result["captains"] == [0]
    assert result["takers"]["penalties"] == [1, 2, 6]
    assert result["takers"]["corners"] == [4, 5, 6]
    assert result["setpieces"]["role_priorities"]["8"] == [1, 4, 2]
    assert result["setpieces"]["routines"] == {}


def test_apply_roster_selection_keeps_native_id_by_target_slot():
    original = team()
    original["players"][3].pop("native_id")
    starters = selection_players(300, 11)
    starters[3]["native_id"] = 9999
    starters[4]["name"] = "  New Name  "

    result = apply_roster_selection(original, starters=starters, substitutes=[None] * 12)

    assert "native_id" not in result["players"][3]
    assert result["players"][4]["native_id"] == 5004
    assert result["players"][4]["name"] == "New Name"
    assert "generated" not in result["players"][0]
    assert [item["native_id"] for item in result["players"][:11] if "native_id" in item] == [
        5000,
        5001,
        5002,
        5004,
        5005,
        5006,
        5007,
        5008,
        5009,
        5010,
    ]


def test_apply_roster_selection_rejects_invalid_team_and_selection_entries():
    starters = selection_players(300, 11)
    substitutes = [player(400 + index) for index in range(12)]
    with pytest.raises(ValueError, match="23"):
        apply_roster_selection(team(22), starters=starters, substitutes=substitutes)
    duplicate_team = team()
    duplicate_team["players"][1]["source_uid"] = duplicate_team["players"][0]["source_uid"]
    with pytest.raises(ValueError, match="唯一"):
        apply_roster_selection(duplicate_team, starters=starters, substitutes=substitutes)
    bad_entry = list(starters)
    bad_entry[0] = "not-a-player"
    with pytest.raises(ValueError, match="格式"):
        apply_roster_selection(team(), starters=bad_entry, substitutes=substitutes)
    bad_player = [copy.deepcopy(item) for item in starters]
    bad_player[0]["attributes"] = [10] * 68
    with pytest.raises(ValueError, match="69"):
        apply_roster_selection(team(), starters=bad_player, substitutes=substitutes)


def test_apply_roster_selection_returns_new_team_and_drops_squad():
    original = team()
    original["phases"] = [{"phase": 0}]
    original["squad"] = ["stale"]
    snapshot = copy.deepcopy(original)
    starters = selection_players(300, 11)

    result = apply_roster_selection(original, starters=starters, substitutes=[None] * 12)

    assert original == snapshot
    assert result is not original
    assert result["name"] == "Home"
    assert result["phases"] == [{"phase": 0}]
    assert "squad" not in result
    assert result["players"][0] == {
        **starters[0],
        "name": starters[0]["name"].strip(),
        "native_id": 5000,
    }
