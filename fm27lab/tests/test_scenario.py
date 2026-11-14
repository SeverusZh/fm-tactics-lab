from __future__ import annotations

import copy

import pytest

from fm27lab.domain.scenario import normalize_scenario, upgrade_legacy_scenario


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


POSITIONS = ("GK", "DR", "DL", "DC", "DC", "DMC", "MC", "MC", "AMR", "AML", "ST")
PHASE_NAMES = ("in_possession", "out_of_possession")


def assignment(position, phase):
    return {
        "position": position,
        "role": f"{phase}-{position}",
        "duty": "0",
        "instructions": {"0": 1, "1": 0},
        "target_player": 255,
        "target_position": 0,
    }


def phase_cells(phase):
    return [assignment(position, phase) for position in POSITIONS]


def legacy_team(order=PHASE_NAMES, count=26):
    value = team(count)
    del value["phases"]
    plans = {
        "in_possession": {
            "phase": "in_possession",
            "team_instructions": {"1": 1, "2": 3},
            "assignments": phase_cells("in_possession"),
        },
        "out_of_possession": {
            "phase": "out_of_possession",
            "team_instructions": {"2": 8, "4": 2},
            "assignments": phase_cells("out_of_possession"),
        },
    }
    value["phase_plans"] = [plans[name] for name in order]
    return value


def legacy_scenario(order=PHASE_NAMES, count=26):
    value = scenario(count)
    value["rules"] = "lab"
    value["fixture"] = "bundled_match_pkm"
    value["native_generation"] = {"seed": 9}
    value["teams"] = [legacy_team(order, count), legacy_team(order, count)]
    return value


def native_scenario(count=26):
    value = scenario(count)
    value["schema"] = 3
    value["rules"] = "lab"
    value["fixture"] = "bundled_match_pkm"
    return value


def test_upgrade_legacy_scenario_converts_phase_plans_to_native_shape():
    value = legacy_scenario()
    upgraded = upgrade_legacy_scenario(value)
    assert upgraded["schema"] == 3
    assert upgraded["rules"] == "lab"
    assert upgraded["fixture"] == "bundled_match_pkm"
    assert upgraded["native_generation"] == {"seed": 9}
    assert upgraded["away_tactic_pool"] == {"enabled": False, "entries": []}
    team_value = upgraded["teams"][0]
    assert "phase_plans" not in team_value
    assert team_value["instructions"] == {"1": 1, "2": 8, "4": 2}
    assert team_value["phases"] == [phase_cells("in_possession"), phase_cells("out_of_possession")]
    assert [cell["role"] for cell in team_value["phases"][0]] == [
        f"in_possession-{position}" for position in POSITIONS
    ]
    assert [cell["role"] for cell in team_value["phases"][1]] == [
        f"out_of_possession-{position}" for position in POSITIONS
    ]
    assert team_value["phases"][0][0] is not value["teams"][0]["phase_plans"][0]["assignments"][0]


def test_upgrade_maps_plans_by_phase_name_not_list_order():
    normal = upgrade_legacy_scenario(legacy_scenario())
    reversed_order = upgrade_legacy_scenario(
        legacy_scenario(order=("out_of_possession", "in_possession"))
    )
    assert reversed_order["teams"] == normal["teams"]
    team_value = reversed_order["teams"][0]
    assert team_value["instructions"] == {"1": 1, "2": 8, "4": 2}
    assert team_value["phases"][0][0]["role"] == "in_possession-GK"
    assert team_value["phases"][1][0]["role"] == "out_of_possession-GK"


def test_upgrade_returns_native_scenario_without_copying():
    value = native_scenario()
    assert upgrade_legacy_scenario(value) is value
    assert copy.deepcopy(upgrade_legacy_scenario(value)) == value


def test_upgrade_passes_schema_four_scenario_without_phase_plans():
    value = scenario()
    assert upgrade_legacy_scenario(value) is value
    original = copy.deepcopy(value)
    result = normalize_scenario(value)
    assert result["schema"] == 4
    assert result["teams"][0]["phases"] == [[], []]
    assert "instructions" not in result["teams"][0]
    assert value == original


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda team: team.__setitem__("phase_plans", []), id="empty"),
        pytest.param(
            lambda team: team.__setitem__("phase_plans", team["phase_plans"][:1]), id="one_plan"
        ),
        pytest.param(
            lambda team: team.__setitem__(
                "phase_plans",
                [team["phase_plans"][0], team["phase_plans"][1], team["phase_plans"][0]],
            ),
            id="three_plans",
        ),
        pytest.param(
            lambda team: team["phase_plans"][0].__setitem__("phase", "build_up"),
            id="unknown_name",
        ),
        pytest.param(
            lambda team: team["phase_plans"][1].__setitem__("phase", "in_possession"),
            id="duplicate_name",
        ),
        pytest.param(
            lambda team: team.__setitem__(
                "phase_plans", {"in_possession": team["phase_plans"][0]}
            ),
            id="mapping_plans",
        ),
        pytest.param(
            lambda team: team.__setitem__(
                "phase_plans", [["in_possession"], team["phase_plans"][1]]
            ),
            id="plan_not_mapping",
        ),
        pytest.param(lambda team: team.pop("phase_plans"), id="missing_phase_plans"),
    ],
)
def test_upgrade_rejects_invalid_phase_plans(mutate):
    value = legacy_scenario()
    mutate(value["teams"][0])
    with pytest.raises(ValueError, match="需要有球和无球两套阶段方案"):
        upgrade_legacy_scenario(value)


@pytest.mark.parametrize(
    "field",
    [pytest.param("phases", id="phases"), pytest.param("instructions", id="instructions")],
)
def test_upgrade_rejects_phase_plans_mixed_with_legacy_fields(field):
    value = legacy_scenario()
    value["teams"][1][field] = [[], []] if field == "phases" else {}
    with pytest.raises(ValueError, match="双阶段格式不可同时包含旧版战术字段"):
        upgrade_legacy_scenario(value)


@pytest.mark.parametrize(
    "plans",
    [
        pytest.param([], id="empty_plans"),
        pytest.param([{"phase": "in_possession"}], id="single_plan"),
    ],
)
@pytest.mark.parametrize(
    "field",
    [pytest.param("phases", id="phases"), pytest.param("instructions", id="instructions")],
)
def test_upgrade_validates_phase_plans_before_mixed_field_detection(plans, field):
    value = legacy_scenario()
    team = value["teams"][0]
    team["phase_plans"] = plans
    team[field] = [[], []] if field == "phases" else {}
    with pytest.raises(ValueError, match="需要有球和无球两套阶段方案"):
        upgrade_legacy_scenario(value)


def test_upgrade_converts_phase_plans_when_schema_already_native():
    value = legacy_scenario()
    value["schema"] = 3
    original = copy.deepcopy(value)
    upgraded = upgrade_legacy_scenario(value)
    assert upgraded["schema"] == 3
    assert upgraded is not value
    team = upgraded["teams"][0]
    assert "phase_plans" not in team
    assert team["instructions"] == {"1": 1, "2": 8, "4": 2}
    assert team["phases"][0][0]["role"] == "in_possession-GK"
    assert team["phases"][1][0]["role"] == "out_of_possession-GK"
    assert value == original


def test_upgrade_rejects_non_mapping_team_when_legacy_detected():
    value = legacy_scenario()
    value["teams"][0] = "not a team"
    with pytest.raises(ValueError, match="球队格式无效"):
        upgrade_legacy_scenario(value)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda plan: plan.pop("assignments"), id="missing"),
        pytest.param(
            lambda plan: plan.__setitem__("assignments", plan["assignments"][:10]), id="ten_cells"
        ),
        pytest.param(
            lambda plan: plan.__setitem__(
                "assignments", [*plan["assignments"], plan["assignments"][0]]
            ),
            id="twelve_cells",
        ),
        pytest.param(
            lambda plan: plan.__setitem__("assignments", {"cells": plan["assignments"]}),
            id="mapping",
        ),
        pytest.param(
            lambda plan: plan.__setitem__("assignments", ["GK", *plan["assignments"][1:]]),
            id="cell_not_mapping",
        ),
    ],
)
def test_upgrade_rejects_invalid_assignments(mutate):
    value = legacy_scenario()
    mutate(value["teams"][0]["phase_plans"][1])
    with pytest.raises(ValueError, match="位置方案格式无效"):
        upgrade_legacy_scenario(value)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda cell: cell.pop("position"), id="missing"),
        pytest.param(lambda cell: cell.__setitem__("position", ""), id="empty"),
        pytest.param(lambda cell: cell.__setitem__("position", 7), id="not_string"),
    ],
)
def test_upgrade_rejects_invalid_position_names(mutate):
    value = legacy_scenario()
    mutate(value["teams"][0]["phase_plans"][0]["assignments"][4])
    with pytest.raises(ValueError, match="位置名称无效"):
        upgrade_legacy_scenario(value)


def test_upgrade_defaults_missing_role_and_preserves_optional_cell_fields():
    value = legacy_scenario()
    grid = value["teams"][0]["phase_plans"][0]["assignments"]
    del grid[0]["role"]
    grid[1]["role"] = 7
    for key in ("duty", "instructions", "target_player", "target_position"):
        del grid[2][key]
    grid[3]["custom"] = {"mark": 5}
    upgraded = upgrade_legacy_scenario(value)
    cells = upgraded["teams"][0]["phases"][0]
    assert cells[0]["role"] == ""
    assert cells[1]["role"] == ""
    for key in ("duty", "instructions", "target_player", "target_position"):
        assert key not in cells[2]
    assert cells[3]["custom"] == {"mark": 5}
    assert cells[3]["custom"] is not grid[3]["custom"]
    cells[3]["custom"]["mark"] = 9
    assert grid[3]["custom"] == {"mark": 5}


def test_upgrade_reads_team_instructions_and_defaults_to_empty_mapping():
    value = legacy_scenario()
    for plan in value["teams"][0]["phase_plans"]:
        plan.pop("team_instructions")
    assert upgrade_legacy_scenario(value)["teams"][0]["instructions"] == {}

    broken = legacy_scenario()
    broken["teams"][0]["phase_plans"][0]["team_instructions"] = ["not", "mapping"]
    with pytest.raises(ValueError, match="球队指令格式无效"):
        upgrade_legacy_scenario(broken)


def test_upgrade_is_idempotent_and_never_mutates_input():
    value = legacy_scenario()
    original = copy.deepcopy(value)
    upgraded = upgrade_legacy_scenario(value)
    assert value == original
    assert upgrade_legacy_scenario(upgraded) is upgraded
    assert upgrade_legacy_scenario(legacy_scenario()) == upgrade_legacy_scenario(legacy_scenario())

    broken = legacy_scenario()
    broken["teams"][1]["phase_plans"] = []
    broken_original = copy.deepcopy(broken)
    with pytest.raises(ValueError, match="需要有球和无球两套阶段方案"):
        upgrade_legacy_scenario(broken)
    assert broken == broken_original


def test_normalize_scenario_upgrades_legacy_shape_before_roster_normalization():
    value = legacy_scenario()
    original = copy.deepcopy(value)
    result = normalize_scenario(value)
    assert result["schema"] == 3
    assert result["away_tactic_pool"] == {"enabled": False, "entries": []}
    team_value = result["teams"][0]
    assert "phase_plans" not in team_value
    assert len(team_value["players"]) == 23
    assert team_value["roster_trim"]["source_size"] == 26
    assert team_value["captains"] == [5]
    assert team_value["instructions"] == {"1": 1, "2": 8, "4": 2}
    assert team_value["phases"][0][0]["role"] == "in_possession-GK"
    assert team_value["phases"][1][0]["role"] == "out_of_possession-GK"
    assert value == original
