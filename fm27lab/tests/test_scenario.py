from __future__ import annotations

import copy

import pytest

from fm27lab.domain.scenario import normalize_scenario


def player(uid, position=7):
    attributes = [10] * 69
    attributes[position] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes, "ability": 10}


def team(count=26):
    players = [player(100 + index, 0 if index == 0 else 7) for index in range(count)]
    return {
        "name": "Home",
        "players": players,
        "roster_size": count,
        "lineup": list(range(11)),
        "captains": [5, 99],
        "takers": {"penalties": [6, 99]},
        "setpieces": {"role_priorities": {"8": [8, 99]}, "routines": {}},
        "phases": [[], []],
    }


def scenario(count=26):
    return {
        "schema": 4,
        "teams": [team(count), team(count)],
        "away_tactic_pool": {"enabled": False, "entries": []},
    }


def test_normalize_scenario_trims_both_teams_to_23_and_remaps_references():
    original = scenario()
    snapshot = copy.deepcopy(original)
    result = normalize_scenario(original)
    assert original == snapshot
    for side in result["teams"]:
        assert len(side["players"]) == 23
        assert side["roster_size"] == 23
        assert side["lineup"] == list(range(11))
        assert [p["source_uid"] for p in side["players"]] == list(range(100, 123))
        assert side["captains"] == [5]
        assert side["takers"]["penalties"] == [6]
        assert side["setpieces"]["role_priorities"]["8"] == [8]
        assert side["name"] == "Home"
        assert side["phases"] == [[], []]
    assert result["schema"] == 4
    assert result["away_tactic_pool"] == original["away_tactic_pool"]


def test_23_player_scenario_is_unchanged():
    result = normalize_scenario(scenario(23))
    assert [p["source_uid"] for p in result["teams"][0]["players"]] == list(range(100, 123))
    assert result["teams"][0]["roster_size"] == 23


def test_short_scenario_gets_generated_placeholders():
    result = normalize_scenario(scenario(20))
    team = result["teams"][0]
    assert len(team["players"]) == 23
    assert len([p for p in team["players"] if p.get("generated")]) == 3


def test_scenario_without_goalkeeper_is_rejected():
    value = scenario(23)
    for side in value["teams"]:
        for item in side["players"]:
            item["attributes"][0] = 1
            item["attributes"][7] = 18
    with pytest.raises(ValueError, match="门将"):
        normalize_scenario(value)


def test_duplicate_uids_and_invalid_teams_are_rejected():
    duplicate = scenario(23)
    duplicate["teams"][0]["players"][1]["source_uid"] = 100
    with pytest.raises(ValueError, match="重复"):
        normalize_scenario(duplicate)
    with pytest.raises(ValueError, match="两支"):
        normalize_scenario({"teams": [team()]})
    with pytest.raises(ValueError, match="场景"):
        normalize_scenario([])
    with pytest.raises(ValueError, match="球队"):
        normalize_scenario({"teams": [{}, team()]})


def test_missing_reference_groups_are_safe():
    value = scenario(23)
    for side in value["teams"]:
        side.pop("captains")
        side.pop("takers")
        side.pop("setpieces")
    result = normalize_scenario(value)
    assert result["teams"][0]["captains"] == [0]
    assert result["teams"][0]["takers"] == {}
    assert "setpieces" not in result["teams"][0]


def test_non_identity_lineup_and_removed_references_are_remapped():
    value = scenario(26)
    side = value["teams"][0]
    side["lineup"] = [25, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    side["captains"] = [25]
    side["takers"] = {"penalties": [25]}
    side["setpieces"]["role_priorities"]["8"] = [25]
    result = normalize_scenario(value)["teams"][0]
    assert result["players"][0]["source_uid"] == 125
    assert result["captains"] == [0]
    assert result["takers"]["penalties"] == [0]
    assert result["setpieces"]["role_priorities"]["8"] == [0]
    removed = scenario(26)
    removed["teams"][0]["captains"] = [25]
    removed["teams"][0]["takers"] = {"penalties": [25]}
    result = normalize_scenario(removed)["teams"][0]
    assert result["captains"] == [0]
    assert result["takers"]["penalties"] != [25]


def test_output_is_fully_detached_and_trim_summary_is_exposed():
    value = scenario(26)
    value["teams"][0]["players"][0]["native_profile"] = {"current_ability": 120}
    value["teams"][0]["squad"] = [{"name": "kept"}]
    result = normalize_scenario(value)
    output = result["teams"][0]
    assert output["players"][0]["attributes"] is not value["teams"][0]["players"][0]["attributes"]
    output["players"][0]["attributes"][1] = 99
    output["players"][0]["native_profile"]["current_ability"] = 1
    assert value["teams"][0]["players"][0]["attributes"][1] != 99
    assert value["teams"][0]["players"][0]["native_profile"]["current_ability"] == 120
    assert output["squad"] == [{"name": "kept"}]
    assert output["squad"] is not value["teams"][0]["squad"]
    assert output["roster_trim"]["source_size"] == 26
    assert len(output["roster_trim"]["removed"]) == 3


def test_substitutes_are_updated_and_illegal_falsy_groups_are_rejected():
    value = scenario(26)
    value["teams"][0]["substitutes"] = [20, 21]
    result = normalize_scenario(value)["teams"][0]
    assert result["substitutes"] == list(range(11, 23))
    for key, bad in (("takers", []), ("setpieces", []), ("captains", {})):
        broken = scenario(26)
        broken["teams"][0][key] = bad
        with pytest.raises(ValueError, match="格式"):
            normalize_scenario(broken)
    broken_players = scenario(26)
    broken_players["teams"][0]["players"][3] = None
    with pytest.raises(ValueError, match="球员条目"):
        normalize_scenario(broken_players)
