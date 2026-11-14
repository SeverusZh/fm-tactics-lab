"""Scenario codec contract tests driven by synthetic engine resources."""

from __future__ import annotations

import copy
import struct
from collections import Counter

import pytest

from fm27lab.adapters.engine_native.scenario_codec import (
    CONTROLLED_START,
    FIELDS,
    defaults,
    encode_scenario,
    normalize_profile,
)
from fm27lab.tests.test_scenario_assets import (
    OOP_MAPS,
    ROLE_FLAGS,
    load_fixture_assets,
    make_catalog,
    pack_oi,
    write_json,
)

MAGIC = b"FM27CFG1"
PROFILE_RECORDS = (
    (15, 10000),
    (16, 10000),
    (17, 10000),
    (18, 0),
    (20, 80),
    (21, 100),
    (22, 20),
)


@pytest.fixture()
def assets(tmp_path):
    return load_fixture_assets(tmp_path)


def make_scenario(assets) -> dict:
    return {
        "schema": 3,
        "rules": "game",
        "fixture": "bundled_match_pkm",
        "teams": copy.deepcopy(assets.default_teams),
    }


def parse_config(data: bytes) -> list[tuple[int, int, int, int, int]]:
    assert data[:8] == MAGIC
    count = struct.unpack_from("<I", data, 8)[0]
    assert len(data) == 12 + count * 20
    return [struct.unpack_from("<5I", data, 12 + index * 20) for index in range(count)]


def baseline_records() -> list[tuple[int, int, int, int, int]]:
    records: list[tuple[int, int, int, int, int]] = []
    for side in range(2):
        records.append((10, side, 0, 0, 1))
        records.append((13, side, 0, 0, 1))
        records.extend((12, side, slot, 0, native) for slot, native in enumerate(OOP_MAPS[side]))
        for player in range(23):
            records.extend((15, side, player, field_id, value) for field_id, value in PROFILE_RECORDS)
    return records


TEAM_BASELINE_RECORDS = 174
TEAM_PREFIX_RECORDS = 13
PLAYER_PROFILE_RECORDS = 7
BASE_OPPOSITION = {"press": 0, "mark": 0, "tackle": 0, "foot": 0, "personal": True}


def relative_records(assets, scenario) -> list[tuple[int, int, int, int, int]]:
    return parse_config(encode_scenario(assets, scenario, absolute=False))


def absolute_records(assets, scenario) -> list[tuple[int, int, int, int, int]]:
    return parse_config(encode_scenario(assets, scenario, absolute=True))


def player_record_position(side: int, player: int) -> int:
    return TEAM_BASELINE_RECORDS * side + TEAM_PREFIX_RECORDS + PLAYER_PROFILE_RECORDS * (player + 1)


def team_delta_position(side: int) -> int:
    return TEAM_BASELINE_RECORDS * (side + 1)


def insert_records(
    records: list[tuple[int, int, int, int, int]],
    insertions: dict[int, list[tuple[int, int, int, int, int]]],
) -> list[tuple[int, int, int, int, int]]:
    expected = list(records)
    for position in sorted(insertions, reverse=True):
        expected[position:position] = insertions[position]
    return expected


def test_defaults_returns_complete_scenario(assets):
    scenario = defaults(assets)
    assert scenario["schema"] == 3
    assert scenario["rules"] == "game"
    assert scenario["fixture"] == "bundled_match_pkm"
    assert scenario["teams"] == assets.default_teams
    assert len(scenario["teams"]) == 2


def test_relative_encoding_emits_only_native_baseline(assets):
    data = encode_scenario(assets, make_scenario(assets), absolute=False)
    assert parse_config(data) == baseline_records()


def test_absolute_encoding_emits_complete_record_set(assets):
    data = encode_scenario(assets, make_scenario(assets), absolute=True)
    records = parse_config(data)
    assert Counter(record[0] for record in records) == {
        10: 2,
        13: 2,
        12: 22,
        15: 322,
        1: 3174,
        2: 6,
        60: 252,
        3: 2,
        4: 44,
        5: 44,
        14: 44,
        18: 44,
        6: 88,
        7: 88,
        11: 22,
    }
    assert records[0] == (10, 0, 0, 0, 1)
    assert (5, 0, 16 + OOP_MAPS[0][0], 0, 1) in records
    assert (4, 0, 16 + OOP_MAPS[0][1], 0, ROLE_FLAGS[1]["FIELD"]) in records
    assert (11, 0, 10, 0, 10) in records
    assert all(record[0] not in (17, 20, 21, 30, 31) for record in records)


def test_absolute_encoding_includes_relative_baseline(assets):
    relative = set(parse_config(encode_scenario(assets, make_scenario(assets), absolute=False)))
    absolute = set(parse_config(encode_scenario(assets, make_scenario(assets), absolute=True)))
    assert relative <= absolute


def test_relative_player_attribute_delta_emits_changed_attribute_only(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["players"][0]["attributes"][0] = 11
    scenario["teams"][0]["players"][5]["attributes"][68] = 51
    scenario["teams"][1]["players"][22]["attributes"][68] = 52

    records = relative_records(assets, scenario)
    assert [record for record in records if record[0] == 1] == [
        (1, 0, 0, 0, 11),
        (1, 0, 5, 68, 51),
        (1, 1, 22, 68, 52),
    ]
    expected = insert_records(
        baseline_records(),
        {
            player_record_position(0, 0): [(1, 0, 0, 0, 11)],
            player_record_position(0, 5): [(1, 0, 5, 68, 51)],
            player_record_position(1, 22): [(1, 1, 22, 68, 52)],
        },
    )
    assert records == expected

    absolute = absolute_records(assets, scenario)
    assert Counter(record[0] for record in absolute)[1] == 2 * 23 * 69
    assert [record for record in absolute if record[0] == 1 and record[4] in (11, 51, 52)] == [
        (1, 0, 0, 0, 11),
        (1, 0, 5, 68, 51),
        (1, 1, 22, 68, 52),
    ]


def test_relative_team_instruction_delta_emits_changed_instruction_only(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["instructions"]["2"] = 1
    scenario["teams"][1]["instructions"]["2"] = 1

    records = relative_records(assets, scenario)
    assert [record for record in records if record[0] == 2] == [(2, 0, 2, 0, 1), (2, 1, 2, 0, 1)]
    expected = insert_records(
        baseline_records(),
        {
            team_delta_position(0): [(2, 0, 2, 0, 1)],
            team_delta_position(1): [(2, 1, 2, 0, 1)],
        },
    )
    assert records == expected


def test_relative_extra_bit_delta_emits_only_changed_native_bits(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["native_extra_team_bits"] = str((1 << 0) | (1 << 1))
    scenario["teams"][1]["native_extra_team_bits"] = str(1 << 127)

    records = relative_records(assets, scenario)
    assert [record for record in records if record[0] == 60] == [
        (60, 0, 0, 0, 1),
        (60, 0, 1, 0, 1),
        (60, 1, 127, 0, 1),
    ]
    expected = insert_records(
        baseline_records(),
        {
            team_delta_position(0): [(60, 0, 0, 0, 1), (60, 0, 1, 0, 1)],
            team_delta_position(1): [(60, 1, 127, 0, 1)],
        },
    )
    assert records == expected

    absolute = absolute_records(assets, scenario)
    assert Counter(record[0] for record in absolute)[60] == 2 * (128 - 2)


def test_relative_player_instruction_delta_emits_changed_instruction_only(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["phases"][0][1]["instructions"]["0"] = 1
    scenario["teams"][0]["phases"][1][0]["instructions"]["1"] = 2

    records = relative_records(assets, scenario)
    assert [record for record in records if record[0] == 6] == [
        (6, 0, 1, 0, 1),
        (6, 0, 16 + OOP_MAPS[0][0], 1, 2),
    ]
    expected = insert_records(
        baseline_records(),
        {team_delta_position(0): [(6, 0, 1, 0, 1), (6, 0, 16 + OOP_MAPS[0][0], 1, 2)]},
    )
    assert records == expected


def test_relative_target_delta_emits_marking_records(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["phases"][0][2]["target_player"] = 7
    scenario["teams"][0]["phases"][0][2]["target_position"] = 16
    scenario["teams"][0]["phases"][1][1]["target_player"] = 3

    records = relative_records(assets, scenario)
    deltas = [
        (7, 0, 2, 0, 7),
        (7, 0, 2, 1, 16),
        (7, 0, 16 + OOP_MAPS[0][1], 0, 3),
    ]
    assert [record for record in records if record[0] == 7] == deltas
    expected = insert_records(baseline_records(), {team_delta_position(0): deltas})
    assert records == expected


def test_relative_duty_delta_emits_split_duty_word(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["phases"][0][1]["duty"] = "17179869184"
    scenario["teams"][0]["phases"][1][0]["duty"] = "2097152"

    records = relative_records(assets, scenario)
    deltas = [
        (14, 0, 1, 4, 0),
        (14, 0, 16 + OOP_MAPS[0][0], 0, 2097152),
    ]
    assert [record for record in records if record[0] == 14] == deltas
    expected = insert_records(baseline_records(), {team_delta_position(0): deltas})
    assert records == expected


def test_relative_lineup_delta_emits_full_lineup(assets):
    scenario = make_scenario(assets)
    lineup = [1, 0, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    scenario["teams"][0]["lineup"] = lineup

    records = relative_records(assets, scenario)
    deltas = [(11, 0, index, 0, player) for index, player in enumerate(lineup)]
    assert [record for record in records if record[0] == 11] == deltas
    expected = insert_records(baseline_records(), {team_delta_position(0): deltas})
    assert records == expected


def test_relative_role_change_carries_edited_player_settings(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["phases"][0][0]["role"] = "FIELD_ROLE_0"

    records = relative_records(assets, scenario)
    deltas = [
        (4, 0, 0, 0, ROLE_FLAGS[0]["FIELD"]),
        (6, 0, 0, 0, 1),
        (7, 0, 0, 0, 5),
        (7, 0, 0, 1, 1),
    ]
    assert [record for record in records if record[0] in (4, 6, 7)] == deltas
    expected = insert_records(baseline_records(), {team_delta_position(0): deltas})
    assert records == expected


def test_relative_opposition_player_delta_emits_remapped_rows(assets):
    scenario = make_scenario(assets)
    home_row = {**BASE_OPPOSITION, "press": 2}
    away_row = {**BASE_OPPOSITION, "tackle": 2}
    scenario["teams"][0]["opposition"]["players"][3] = home_row
    scenario["teams"][1]["opposition"]["players"][7] = away_row
    home = (20, 0, 3, 0, pack_oi(home_row))
    away = (20, 1, 7, 0, pack_oi(away_row))

    records = relative_records(assets, scenario)
    assert [record for record in records if record[0] == 20] == [home, away]
    expected = insert_records(
        baseline_records(), {team_delta_position(0): [home], team_delta_position(1): [away]}
    )
    assert records == expected

    absolute = absolute_records(assets, scenario)
    assert [record for record in absolute if record[0] == 20] == [home, away]
    assert [record for record in absolute if record[0] == 21] == []


def test_relative_opposition_position_delta_emits_changed_positions(assets):
    scenario = make_scenario(assets)
    goalkeeper = {"press": 0, "mark": 0, "tackle": 1, "foot": 0, "personal": False}
    striker = {**BASE_OPPOSITION, "mark": 1}
    scenario["teams"][0]["opposition"]["positions"]["GK"] = goalkeeper
    scenario["teams"][0]["opposition"]["positions"]["ST"] = striker
    gk = (21, 0, 1, 0, pack_oi(goalkeeper))
    st = (21, 0, 16384, 0, pack_oi(striker))

    records = relative_records(assets, scenario)
    assert [record for record in records if record[0] == 21] == [gk, st]
    expected = insert_records(baseline_records(), {team_delta_position(0): [gk, st]})
    assert records == expected

    absolute = absolute_records(assets, scenario)
    assert [record for record in absolute if record[0] == 21] == [gk, st]
    assert [record for record in absolute if record[0] == 20] == []


def test_relative_opposition_rows_follow_opponent_lineup_order(assets):
    scenario = make_scenario(assets)
    away_lineup = [5, 0, 1, 2, 3, 4, 6, 7, 8, 9, 10]
    row = {**BASE_OPPOSITION, "press": 2}
    scenario["teams"][1]["lineup"] = away_lineup
    scenario["teams"][0]["opposition"]["players"][3] = row
    marking = (20, 0, away_lineup.index(3), 0, pack_oi(row))

    records = relative_records(assets, scenario)
    assert [record for record in records if record[0] == 20] == [marking]
    expected = insert_records(
        baseline_records(),
        {
            team_delta_position(0): [marking],
            team_delta_position(1): [
                (11, 1, index, 0, player) for index, player in enumerate(away_lineup)
            ],
        },
    )
    assert records == expected

    absolute = absolute_records(assets, scenario)
    assert [record for record in absolute if record[0] == 20] == [marking]


def test_unchanged_opposition_tables_emit_no_records_in_either_mode(assets):
    scenario = make_scenario(assets)
    assert [record for record in relative_records(assets, scenario) if record[0] in (20, 21)] == []
    assert [record for record in absolute_records(assets, scenario) if record[0] in (20, 21)] == []


def test_phase_one_slots_follow_oop_map(assets):
    scenario = make_scenario(assets)
    cells = scenario["teams"][0]["phases"][1]
    cells[1]["position"], cells[2]["position"] = cells[2]["position"], cells[1]["position"]
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    assert [record for record in records if record[0] == 5] == [
        (5, 0, 16 + OOP_MAPS[0][1], 0, 8),
        (5, 0, 16 + OOP_MAPS[0][2], 0, 4),
    ]


def test_role_change_emits_split_role_flags(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["phases"][0][1]["role"] = "GK_ROLE_0"
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    assert [record for record in records if record[0] == 4] == [(4, 0, 1, 0, ROLE_FLAGS[0]["GK"])]


def test_mentality_change_emits_single_record(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["mentality"] = 5
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    baseline = baseline_records()
    assert records[:174] == baseline[:174]
    assert records[174] == (3, 0, 0, 0, 5)
    assert records[175:] == baseline[174:]
    assert len(records) == len(baseline) + 1


def test_rule_lab_encodes_zero_flag(assets):
    scenario = make_scenario(assets)
    scenario["rules"] = "lab"
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    assert records[1] == (13, 0, 0, 0, 0)


def test_roster_size_emits_marker_and_limits_players(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["roster_size"] = 11
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    assert records[0:2] == [(10, 0, 0, 0, 1), (17, 0, 0, 0, 11)]
    profile = [record for record in records if record[0] == 15 and record[1] == 0]
    assert len(profile) == 11 * 7
    assert max(record[2] for record in profile) == 10


def test_takers_reset_emits_clear_and_rows(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["takers"]["penalties"] = [3, 5]
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    baseline = baseline_records()
    assert records[174:177] == [
        (30, 0, 1, 0xFFFFFFFF, 0),
        (30, 0, 1, 0, 3),
        (30, 0, 1, 1, 5),
    ]
    assert records[177:] == baseline[174:]
    assert len(records) == len(baseline) + 3


def test_captains_emit_reset_order_and_armband(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["captains"] = [3, 1]
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    assert records[174:178] == [
        (30, 0, 0, 0xFFFFFFFF, 0),
        (30, 0, 0, 0, 3),
        (30, 0, 0, 1, 1),
        (31, 0, 0, 0, 3),
    ]


def test_setpiece_throw_style_record_precedes_team_block(assets):
    scenario = make_scenario(assets)
    scenario["teams"][0]["setpieces"]["throw_styles"][0] = 1
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    assert records[:3] == [(10, 0, 0, 0, 1), (46, 0, 0, 0, 1), (13, 0, 0, 0, 1)]


def test_experimental_execution_encodes_before_teams(assets):
    scenario = make_scenario(assets)
    scenario["experimental_execution"] = [
        {"understanding": 50, "buy_in": 60, "opposition": 70},
        42,
    ]
    records = parse_config(encode_scenario(assets, scenario, absolute=False))
    assert records[:5] == [
        (61, 0, 1, 0, 50),
        (61, 0, 2, 0, 60),
        (61, 0, 3, 0, 70),
        (61, 1, 0, 0, 42),
        (10, 0, 0, 0, 1),
    ]


def test_encoding_is_deterministic(assets):
    scenario = make_scenario(assets)
    assert encode_scenario(assets, scenario) == encode_scenario(assets, scenario)
    assert encode_scenario(assets, scenario, absolute=False) == encode_scenario(
        assets, scenario, absolute=False
    )


def shift_players(team: dict, order: list[int]) -> list[int]:
    """Reorder the player list and remap every player index reference."""
    players = team["players"]
    team["players"] = [players[index] for index in order]
    position = [0] * len(order)
    for new_index, old_index in enumerate(order):
        position[old_index] = new_index
    team["lineup"] = [position[index] for index in team["lineup"]]
    team["captains"] = [position[index] for index in team["captains"]]
    team["takers"] = {
        key: [position[index] for index in values] for key, values in team["takers"].items()
    }
    for priorities in team["setpieces"]["role_priorities"].values():
        priorities[:] = [position[index] for index in priorities]
    return position


def test_player_permutation_encodes_as_the_canonical_scenario(assets):
    canonical = make_scenario(assets)
    shuffled = make_scenario(assets)
    canonical["teams"][0]["setpieces"]["role_priorities"]["0"] = [0, 5, 3]
    shuffled["teams"][0]["setpieces"]["role_priorities"]["0"] = [0, 5, 3]
    order = list(range(23))
    order = order[7:] + order[:7]
    shift_players(shuffled["teams"][0], order)
    shift_players(shuffled["teams"][1], order[::-1])
    assert absolute_records(assets, shuffled) == absolute_records(assets, canonical)
    assert relative_records(assets, shuffled) == relative_records(assets, canonical)


def test_player_permutation_keeps_edits_on_the_same_player(assets):
    canonical = make_scenario(assets)
    canonical["teams"][0]["players"][3]["attributes"][20] = 7
    canonical["teams"][0]["players"][4]["native_profile"]["condition"] = 9000
    shuffled = make_scenario(assets)
    order = list(range(23))
    order = order[5:] + order[:5]
    position = shift_players(shuffled["teams"][0], order)
    shuffled["teams"][0]["players"][position[3]]["attributes"][20] = 7
    shuffled["teams"][0]["players"][position[4]]["native_profile"]["condition"] = 9000
    assert absolute_records(assets, shuffled) == absolute_records(assets, canonical)


def test_duplicate_native_ids_are_rejected(assets):
    scenario = make_scenario(assets)
    players = scenario["teams"][0]["players"]
    players[1]["native_id"] = players[0]["native_id"]
    with pytest.raises(ValueError, match="球员顺序或标识不匹配"):
        encode_scenario(assets, scenario)

def test_profiles_fields_and_normalization():
    assert FIELDS["age"] == (1, 14, 60)
    assert FIELDS["condition"] == (15, 0, 10000)
    assert CONTROLLED_START["morale"] == 20
    assert normalize_profile({"age": 15, "condition": 500}) == {"age": 15, "condition": 500}
    with pytest.raises(ValueError, match="未知球员扩展输入"):
        normalize_profile({"unknown": 1})
    with pytest.raises(ValueError, match="球员扩展输入范围无效: age"):
        normalize_profile({"age": 13})
    with pytest.raises(ValueError, match="球员扩展输入范围无效: age"):
        normalize_profile({"age": True})


def test_specified_marking_validation_rejects_incomplete_selection(tmp_path):
    root = tmp_path / "engine"
    from fm27lab.tests.test_scenario_assets import write_engine_root

    write_engine_root(tmp_path)
    catalog = make_catalog("native")
    catalog["player_instructions"].append(
        {
            "id": 14,
            "label": "指定盯防",
            "phase": 1,
            "options": [{"id": 0, "label": "默认"}, {"id": 34, "label": "盯人"}, {"id": 35, "label": "盯位"}],
        }
    )
    write_json(root / "fm27_native" / "catalog.json", catalog)
    from fm27lab.adapters.engine_native.scenario_assets import load_scenario_assets

    local = load_scenario_assets(root)
    scenario = make_scenario(local)
    cell = scenario["teams"][0]["phases"][0][0]
    cell["instructions"]["14"] = 34
    cell["target_player"] = 255
    with pytest.raises(ValueError, match="指定盯防需要选择对方名单序号"):
        encode_scenario(local, scenario, absolute=False)
    cell["instructions"]["14"] = 35
    cell["target_position"] = 0
    with pytest.raises(ValueError, match="指定盯防需要选择位置"):
        encode_scenario(local, scenario, absolute=False)


def test_native_generation_input_is_rejected(assets):
    scenario = make_scenario(assets)
    scenario["native_generation"] = {}
    with pytest.raises(ValueError, match="暂不支持电脑球队生成输入"):
        encode_scenario(assets, scenario)


def test_invalid_scenarios_raise_chinese_errors(assets):
    def mutate(function):
        scenario = make_scenario(assets)
        function(scenario)
        return scenario

    def set_team(key, value):
        return lambda scenario: scenario["teams"][0].__setitem__(key, value)

    def set_attribute(index, value):
        def function(scenario):
            scenario["teams"][0]["players"][0]["attributes"][index] = value

        return function

    cases = [
        (lambda scenario: None, "not-a-scenario", "方案格式或比赛样本不匹配"),
        (lambda scenario: scenario.__setitem__("schema", 2), None, "方案格式或比赛样本不匹配"),
        (lambda scenario: scenario.__setitem__("fixture", "other"), None, "方案格式或比赛样本不匹配"),
        (lambda scenario: scenario.__setitem__("rules", "x"), None, "未知角色限制模式"),
        (lambda scenario: scenario.__setitem__("teams", scenario["teams"][:1]), None, "必须包含两支球队"),
        (set_team("mentality", 8), None, "比赛心态必须为 1–7 的整数"),
        (set_team("roster_size", 24), None, "比赛名单人数必须为 11–23 的整数"),
        (set_team("roster_size", 10), None, "比赛名单人数必须为 11–23 的整数"),
        (lambda scenario: scenario["teams"][0]["players"].pop(), None, "名单长度不匹配"),
        (
            lambda scenario: scenario["teams"][0]["players"][0]["attributes"].pop(),
            None,
            "每名球员必须包含69项原生输入",
        ),
        (set_attribute(0, 21), None, "属性必须为 0–20 的整数"),
        (set_attribute(20, 0), None, "属性必须为 1–100 的整数"),
        (
            lambda scenario: scenario["teams"][0]["players"][0].__setitem__("native_id", 999),
            None,
            "球员顺序或标识不匹配",
        ),
        (
            lambda scenario: scenario["teams"][0]["instructions"].__setitem__("1", 9),
            None,
            "未知球队指令选项",
        ),
        (set_team("native_extra_team_bits", "16"), None, "附加原生选项越界或与已命名指令重复"),
        (set_team("native_extra_team_bits", "abc"), None, "附加原生战术选项格式无效"),
        (set_team("lineup", [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10]), None, "首发必须是11名不同球员"),
        (set_team("captains", [3, 3]), None, "队长优先顺序无效"),
        (set_team("takers", {"penalties": []}), None, "定位球主罚名单分类不符"),
        (
            lambda scenario: scenario["teams"][0]["takers"].__setitem__("penalties", [1, 1]),
            None,
            "定位球主罚顺序无效",
        ),
        (
            lambda scenario: scenario["teams"][0]["opposition"]["players"].pop(),
            None,
            "针对性指令的对方名单长度不符",
        ),
        (
            lambda scenario: scenario["teams"][0]["opposition"]["players"][0].__setitem__("press", 3),
            None,
            "针对性指令必须为 0–2 的整数",
        ),
        (
            lambda scenario: scenario["teams"][0]["opposition"]["players"][0].__setitem__("personal", 1),
            None,
            "针对性指令模式无效",
        ),
        (lambda scenario: scenario["teams"][0]["phases"].pop(), None, "必须配置有球和无球阶段"),
        (lambda scenario: scenario["teams"][0]["phases"][0].pop(), None, "每个阶段必须有11个位置"),
        (
            lambda scenario: scenario["teams"][0]["phases"][0][0].__setitem__("position", "ST"),
            None,
            "每个阶段必须有一名门将且位置不能重复；0号位置为门将",
        ),
        (
            lambda scenario: scenario["teams"][0]["phases"][0][0].__setitem__("role", "NOPE"),
            None,
            "未知位置或阶段角色",
        ),
        (
            lambda scenario: scenario["teams"][0]["phases"][0][0].__setitem__("duty", "1"),
            None,
            "未知角色职责位",
        ),
        (
            lambda scenario: scenario["teams"][0]["phases"][0][0]["instructions"].__setitem__("0", 5),
            None,
            "未知个人指令选项",
        ),
        (
            lambda scenario: scenario["teams"][0]["phases"][0][0].__setitem__("target_player", 256),
            None,
            "盯防球员必须为 0–255 的整数",
        ),
        (
            lambda scenario: scenario["teams"][0]["phases"][0][0].__setitem__("target_player", 23),
            None,
            "盯防球员不存在",
        ),
        (
            lambda scenario: scenario["teams"][0]["phases"][0][0].__setitem__("target_position", 3),
            None,
            "盯防位置不存在",
        ),
        (
            lambda scenario: scenario["teams"][0]["setpieces"].__setitem__("throw_styles", [0, 1]),
            None,
            "界外球必须包含后场、中场和前场三种策略",
        ),
        (
            lambda scenario: scenario.__setitem__("experimental_execution", [42]),
            None,
            "请分别设置两队的实验执行力",
        ),
        (
            lambda scenario: scenario.__setitem__("experimental_execution", [42, 101]),
            None,
            "实验执行力必须为 0–100 的整数",
        ),
        (
            lambda scenario: scenario.__setitem__(
                "experimental_execution", [{"understanding": 1}, 42]
            ),
            None,
            "请填写战术理解、教练认可和对手情报",
        ),
    ]
    for mutate_function, replacement, message in cases:
        if replacement is not None:
            scenario = replacement
        else:
            scenario = mutate(mutate_function)
        with pytest.raises(ValueError, match=message):
            encode_scenario(assets, scenario)


def extend_away_squad(assets) -> None:
    assets.default_teams[1]["players"].append(
        {
            "name": "客队球员 24",
            "native_id": 999,
            "attributes": [10] * 15 + [50] * 54,
            "native_profile": dict(CONTROLLED_START),
        }
    )


def test_roster_may_cover_only_the_leading_match_squad(assets):
    extend_away_squad(assets)
    scenario = make_scenario(assets)
    players = scenario["teams"][1]["players"]
    scenario["teams"][1]["players"] = players[:23]
    scenario["teams"][1]["roster_size"] = 23
    records = absolute_records(assets, scenario)
    assert (17, 1, 0, 0, 23) in records
    assert not [record for record in records if record[0] in (1, 15) and record[1] == 1 and record[2] == 23]


def test_shorter_roster_without_roster_size_is_rejected(assets):
    extend_away_squad(assets)
    scenario = make_scenario(assets)
    scenario["teams"][1]["players"] = scenario["teams"][1]["players"][:23]
    with pytest.raises(ValueError, match="名单长度不匹配"):
        encode_scenario(assets, scenario)


def test_roster_must_map_onto_the_leading_match_squad(assets):
    extend_away_squad(assets)
    scenario = make_scenario(assets)
    players = scenario["teams"][1]["players"]
    scenario["teams"][1]["players"] = [player for index, player in enumerate(players) if index != 22]
    scenario["teams"][1]["roster_size"] = 23
    with pytest.raises(ValueError, match="球员顺序或标识不匹配"):
        encode_scenario(assets, scenario)
