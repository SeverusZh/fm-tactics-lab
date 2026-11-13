from __future__ import annotations

import copy

import pytest

from fm27lab.domain.attributes import VISIBLE_GROUPS, group_indices
from fm27lab.domain.pool import (
    DEFAULT_ATTRIBUTE_VALUE,
    MAX_ROSTER,
    POSITION_ATTRIBUTE_INDEX,
    POSITION_FAMILIARITY,
    apply_away_entry,
    draws,
    expand_away_scenario,
    expand_away_scenarios,
    normalize_away_pool,
)
from fm27lab.domain.roster import MATCH_ROSTER_SIZE, normalize_roster

# Legacy apply: src/fm27_tactic_pool.py:284-327 tactic fields and uniform, 330-364 real roster, 394-405 expand.
POSITION_CODES = ("GK", "SW", "DL", "DC", "DR", "DM", "ML", "MC", "MR", "AML", "ST")
VISIBLE_ATTRIBUTE_INDICES = frozenset().union(*(group_indices(group) for group in VISIBLE_GROUPS))


def cell(position, role="角色", duty="0"):
    return {"position": position, "role": role, "duty": duty}


def phase_cells():
    return [[cell(position) for position in POSITION_CODES] for _ in range(2)]


def tactic(**overrides):
    value = {
        "tactic_name": "客队战术",
        "mentality": 3,
        "instructions": {"1": 2},
        "native_extra_team_bits": "7",
        "phases": phase_cells(),
    }
    value.update(overrides)
    return value


def entry(name="客队战术一", **overrides):
    value = {"name": name, "weight": 1, "tactic": tactic()}
    value.update(overrides)
    return value


SQUAD_POSITIONS = (
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    12,
    3,
    3,
    7,
    7,
    12,
    2,
    4,
    0,
    5,
    6,
    8,
    9,
    10,
    3,
    7,
)


def saved_player(index=0, position=None, **overrides):
    attributes = [5] * 15 + [60] * 54
    if position is not None:
        attributes[position] = 20
    value = {
        "name": f"存档球员{index + 1}",
        "source_uid": 1000 + index,
        "attributes": attributes,
        "native_profile": {"slot": index},
    }
    value.update(overrides)
    return value


def saved_roster(count=12, positions=None, **overrides):
    players = [
        saved_player(index, None if positions is None else positions[index]) for index in range(count)
    ]
    value = {
        "club_uid": 7,
        "club": "存档客队",
        "coach": "存档教练",
        "source": "real_ai",
        "roster_size": count,
        "lineup": list(range(11)),
        "players": players,
    }
    value.update(overrides)
    return value


def positioned_roster(count):
    return saved_roster(count, positions=SQUAD_POSITIONS[:count])


def player(uid):
    return {
        "source_uid": uid,
        "name": f"P{uid}",
        "attributes": [5] * 15 + [50] * 54,
        "native_id": 5000 + uid - 100,
    }


def team(count=23):
    return {
        "name": "主队",
        "players": [player(100 + index) for index in range(count)],
        "roster_size": count,
        "lineup": list(range(11)),
        "captains": [],
        "takers": {},
        "setpieces": {},
    }


def expected_players(players, lineup, cells, value=DEFAULT_ATTRIBUTE_VALUE):
    expected = copy.deepcopy(players)
    for item in expected:
        attributes = item["attributes"]
        for index in VISIBLE_ATTRIBUTE_INDICES:
            attributes[index] = value * 5
        attributes[0] = 1
    for cells_row in cells:
        for slot, cell_value in enumerate(cells_row):
            index = POSITION_ATTRIBUTE_INDEX[cell_value["position"]]
            expected[lineup[slot]]["attributes"][index] = POSITION_FAMILIARITY
    return expected


def normalized_cells():
    return [
        [
            {
                "position": position,
                "role": "角色",
                "duty": "0",
                "instructions": {},
                "target_player": 255,
                "target_position": 0,
            }
            for position in POSITION_CODES
        ]
        for _ in range(2)
    ]


# Legacy tactic expansion: src/fm27_tactic_pool.py:288-296.
def test_tactic_fields_are_applied_to_the_team():
    source = team()
    source["tactic_name"] = "旧战术"
    source["native_source_plan"] = {"stale": True}
    snapshot = copy.deepcopy(source)
    result = apply_away_entry(source, entry(), uniform_enabled=False)
    assert result is not source
    assert result["tactic_name"] == "客队战术"
    assert result["mentality"] == 3
    assert result["instructions"] == {"1": 2}
    assert result["native_extra_team_bits"] == "7"
    assert result["phases"] == normalized_cells()
    assert "native_source_plan" not in result
    assert source == snapshot


def test_native_source_plan_is_copied_with_the_tactic():
    plan = {"value": {"team": 1}, "signature": "a" * 64}
    source = team()
    source["native_source_plan"] = {"stale": True}
    raw_entry = entry(tactic=tactic(native_source_plan=plan))
    snapshot = copy.deepcopy(raw_entry)
    result = apply_away_entry(source, raw_entry, uniform_enabled=False)
    assert result["native_source_plan"] == plan
    result["native_source_plan"]["value"]["team"] = 2
    assert raw_entry == snapshot


# Legacy uniform policy: src/fm27_tactic_pool.py:302-326.
def test_uniform_sets_visible_attributes_and_position_familiarity():
    source = team()
    snapshot = copy.deepcopy(source)
    result = apply_away_entry(source, entry(), uniform_enabled=True)
    expected = expected_players(source["players"], source["lineup"], phase_cells())
    assert result["players"] == expected
    assert result["players"][0]["attributes"][0] == POSITION_FAMILIARITY
    assert result["players"][11]["attributes"][0] == 1
    assert result["players"][11]["attributes"][next(iter(VISIBLE_ATTRIBUTE_INDICES))] == 75
    hidden = set(range(15, 69)) - VISIBLE_ATTRIBUTE_INDICES
    for index in hidden:
        assert result["players"][0]["attributes"][index] == 50
    assert source == snapshot


@pytest.mark.parametrize(("value", "expected"), ((1, 5), (15, 75), (20, 100)))
def test_uniform_attribute_value_is_scaled_to_panel_value(value, expected):
    result = apply_away_entry(team(), entry(), uniform_enabled=True, uniform_attribute_value=value)
    for item in result["players"]:
        for index in VISIBLE_ATTRIBUTE_INDICES:
            assert item["attributes"][index] == expected


def test_uniform_disabled_keeps_player_attributes():
    source = team()
    snapshot = copy.deepcopy(source)
    result = apply_away_entry(source, entry(), uniform_enabled=False)
    assert result["players"] == snapshot["players"]
    assert source == snapshot


def test_uniform_rejects_unknown_position():
    cells = phase_cells()
    cells[1][0] = cell("XX")
    with pytest.raises(ValueError, match="战术包含未知位置，无法统一熟练度：XX"):
        apply_away_entry(team(), entry(tactic=tactic(phases=cells)), uniform_enabled=True)


def test_uniform_requires_complete_player_attributes():
    source = team()
    source["players"][0].pop("attributes")
    with pytest.raises(ValueError, match="客队球员属性不完整，无法统一为界面值"):
        apply_away_entry(source, entry(), uniform_enabled=True)


def test_uniform_requires_complete_starting_lineup():
    source = team()
    source["lineup"] = list(range(10))
    with pytest.raises(ValueError, match="客队首发名单不完整，无法统一战术位置熟练度"):
        apply_away_entry(source, entry(), uniform_enabled=True)


def test_uniform_rejects_invalid_lineup_player_index():
    source = team()
    source["lineup"] = list(range(10)) + [99]
    with pytest.raises(ValueError, match="客队首发名单包含无效球员序号"):
        apply_away_entry(source, entry(), uniform_enabled=True)


# Legacy real roster replacement: src/fm27_tactic_pool.py:297-301, 330-364.
def test_real_roster_replaces_players_under_match_roster_rules():
    source = team()
    snapshot = copy.deepcopy(source)
    result = apply_away_entry(
        source,
        entry(),
        uniform_enabled=True,
        uniform_attribute_value=20,
        real_roster=saved_roster(12),
    )
    assert result["roster_size"] == 23
    assert result["lineup"] == list(range(11))
    assert [item["source_uid"] for item in result["players"][:12]] == list(range(1000, 1012))
    assert [item["source_uid"] for item in result["players"][12:]] == list(range(112, 123))
    assert result["players"][0]["name"] == "存档球员1"
    assert result["players"][0]["attributes"] == [5] * 15 + [60] * 54
    assert result["players"][0]["native_id"] == 5000
    assert result["players"][11]["native_id"] == 5011
    assert result["players"][12]["native_id"] == 5012
    assert result["players"][12]["attributes"] == source["players"][12]["attributes"]
    assert source == snapshot


def test_real_roster_with_23_players_replaces_full_squad():
    source = team()
    result = apply_away_entry(
        source,
        entry(),
        uniform_enabled=True,
        real_roster=saved_roster(23),
    )
    assert result["roster_size"] == 23
    assert result["lineup"] == list(range(11))
    assert [item["source_uid"] for item in result["players"]] == list(range(1000, 1023))
    assert [item["native_id"] for item in result["players"]] == list(range(5000, 5023))
    assert all(item["attributes"] == [5] * 15 + [60] * 54 for item in result["players"])


# ADR-0005: 24-26 player squads are trimmed to the 23-player match roster instead of rejected.
def test_real_roster_with_24_players_is_trimmed_to_match_roster():
    roster = positioned_roster(24)
    expected = normalize_roster(roster["players"], lineup=roster["lineup"])
    result = apply_away_entry(
        team(),
        entry(),
        uniform_enabled=True,
        uniform_attribute_value=20,
        real_roster=roster,
    )
    assert len(expected.removed) == 1
    assert not expected.generated
    assert result["roster_size"] == MATCH_ROSTER_SIZE
    assert result["lineup"] == list(range(11))
    assert [item["source_uid"] for item in result["players"]] == [
        item["source_uid"] for item in expected.players
    ]
    assert [item["native_id"] for item in result["players"]] == [
        5000 + index for index in range(MATCH_ROSTER_SIZE)
    ]
    assert result["roster_trim"]["source_size"] == 24
    assert result["roster_trim"]["removed"] == list(expected.removed)
    assert result["players"][0]["attributes"] == expected.players[0]["attributes"]
    assert result["players"][0]["attributes"][15] == 60


def test_real_roster_with_26_players_is_trimmed_to_match_roster():
    roster = positioned_roster(26)
    expected = normalize_roster(roster["players"], lineup=roster["lineup"])
    result = apply_away_entry(team(), entry(), uniform_enabled=False, real_roster=roster)
    assert len(expected.removed) == 3
    assert result["roster_size"] == MATCH_ROSTER_SIZE
    assert [item["source_uid"] for item in result["players"]] == [
        item["source_uid"] for item in expected.players
    ]
    assert result["roster_trim"]["source_size"] == 26
    removed_uids = {item["source_uid"] for item in result["roster_trim"]["removed"]}
    assert removed_uids == {item["source_uid"] for item in expected.removed}
    assert removed_uids.isdisjoint(item["source_uid"] for item in result["players"])


def test_real_roster_trim_requires_a_goalkeeper():
    roster = saved_roster(24, positions=(3,) * 24)
    with pytest.raises(ValueError, match="客队存档名单缺少门将"):
        apply_away_entry(team(), entry(), uniform_enabled=False, real_roster=roster)


def test_real_roster_with_ambiguous_positions_keeps_host_players_for_placeholders():
    roster = saved_roster(24)
    expected = normalize_roster(roster["players"], lineup=roster["lineup"])
    host = team()
    result = apply_away_entry(host, entry(), uniform_enabled=False, real_roster=roster)
    assert expected.generated
    assert result["roster_size"] == MATCH_ROSTER_SIZE
    assert result["roster_trim"]["generated"] == [
        player["source_uid"] for player in expected.generated
    ]
    for slot, item in enumerate(expected.players):
        if item.get("generated"):
            assert result["players"][slot]["source_uid"] == host["players"][slot]["source_uid"]
        else:
            assert result["players"][slot]["source_uid"] == item["source_uid"]


def test_real_roster_branch_validates_uniform_settings():
    with pytest.raises(ValueError, match="统一属性开关必须为布尔值"):
        apply_away_entry(team(), entry(), uniform_enabled="yes", real_roster=saved_roster(12))
    with pytest.raises(ValueError, match="统一属性值必须为 1–20 的整数"):
        apply_away_entry(
            team(),
            entry(),
            uniform_enabled=True,
            uniform_attribute_value=21,
            real_roster=saved_roster(12),
        )


def test_real_roster_over_max_roster_is_rejected():
    roster = saved_roster(MAX_ROSTER + 1, positions=SQUAD_POSITIONS + (3,))
    with pytest.raises(ValueError, match="存档名单须包含 11–26 名球员"):
        apply_away_entry(team(), entry(), uniform_enabled=False, real_roster=roster)


def test_real_roster_requires_match_team_capacity():
    with pytest.raises(ValueError, match="比赛球队至少需要 23 名球员"):
        apply_away_entry(team(11), entry(), uniform_enabled=True, real_roster=saved_roster(12))


def test_real_roster_rejects_duplicate_saved_players():
    roster = saved_roster(12)
    roster["players"][1]["source_uid"] = 1000
    with pytest.raises(ValueError, match="存档名单包含重复球员"):
        apply_away_entry(team(), entry(), uniform_enabled=True, real_roster=roster)


def test_empty_real_roster_uses_uniform_policy():
    result = apply_away_entry(team(), entry(), uniform_enabled=True, real_roster={})
    expected = expected_players(team()["players"], team()["lineup"], phase_cells())
    assert result["players"] == expected


def test_expand_returns_unchanged_copy_for_disabled_pool():
    scenario = {"teams": [team(), team()], "away_tactic_pool": {"enabled": False, "entries": [entry()]}}
    snapshot = copy.deepcopy(scenario)
    result = expand_away_scenario(scenario, scenario["away_tactic_pool"], 7, "job")
    assert result == snapshot
    assert result is not scenario
    assert scenario == snapshot


def test_expand_returns_unchanged_copy_for_empty_pool():
    scenario = {"teams": [team(), team()]}
    result = expand_away_scenario(scenario, {"entries": []}, 7, "job")
    assert result == scenario
    assert result is not scenario


# Legacy expand selects one entry and applies it to the away side: src/fm27_tactic_pool.py:394-405.
def test_expand_selects_draw_entry_and_applies_only_away():
    entries = [
        entry(name="A", tactic=tactic(tactic_name="A", mentality=1)),
        entry(name="B", tactic=tactic(tactic_name="B", mentality=7)),
        entry(name="C", tactic=tactic(tactic_name="C", mentality=5)),
    ]
    scenario = {"teams": [team(), team()]}
    scenario["teams"][1]["name"] = "客队"
    snapshot = copy.deepcopy(scenario)
    result = expand_away_scenario(scenario, {"enabled": True, "entries": entries}, 7, "job-a")
    index = draws(entries, [7], "job-a")[7]
    assert result["teams"][1]["tactic_name"] == entries[index]["tactic"]["tactic_name"]
    assert result["teams"][0] == snapshot["teams"][0]
    assert "away_tactic_pool" not in result
    assert scenario == snapshot


def test_expand_is_deterministic_and_matches_draws():
    entries = [entry(name=f"T{index}", tactic=tactic(tactic_name=f"T{index}")) for index in range(4)]
    scenario = {"teams": [team(), team()]}
    pool = {"enabled": True, "entries": entries}
    for seed in range(6):
        first = expand_away_scenario(scenario, pool, seed, "job-b")
        second = expand_away_scenario(scenario, pool, seed, "job-b")
        assert first == second
        index = draws(entries, [seed], "job-b")[seed]
        assert first["teams"][1]["tactic_name"] == f"T{index}"


def test_expand_applies_pool_uniform_settings():
    pool = {"enabled": True, "uniform": {"enabled": True, "attribute_value": 20}, "entries": [entry()]}
    result = expand_away_scenario({"teams": [team(), team()]}, pool, 3, "job-c")
    away = result["teams"][1]
    expected = expected_players(team()["players"], team()["lineup"], phase_cells(), value=20)
    assert away["players"] == expected
    assert away["players"][0]["attributes"][next(iter(VISIBLE_ATTRIBUTE_INDICES))] == 100


def test_expand_real_mode_replaces_away_players_and_skips_uniform():
    pool = {
        "enabled": True,
        "real": {"enabled": True},
        "uniform": {"enabled": True, "attribute_value": 20},
        "entries": [entry(roster=saved_roster(12))],
    }
    result = expand_away_scenario({"teams": [team(), team()]}, pool, 3, "job-d")
    away = result["teams"][1]
    assert away["roster_size"] == 23
    assert [item["source_uid"] for item in away["players"][:12]] == list(range(1000, 1012))
    assert away["players"][0]["attributes"] == [5] * 15 + [60] * 54


def test_expand_rotation_single_entry_is_supported():
    pool = {"enabled": True, "rotation": {"enabled": True, "rounds": 1}, "entries": [entry()]}
    result = expand_away_scenario({"teams": [team(), team()]}, pool, 5, "job-e")
    assert result["teams"][1]["tactic_name"] == "客队战术"


def test_expand_rotation_batch_mismatch_surfaces_rotation_message():
    pool = {
        "enabled": True,
        "rotation": {"enabled": True, "rounds": 1},
        "entries": [entry(name="A"), entry(name="B")],
    }
    with pytest.raises(ValueError, match="轮战模式每方案需要 2 套 × 1 轮 = 2 场，当前种子数为 1"):
        expand_away_scenario({"teams": [team(), team()]}, pool, 5, "job-f")


def test_expand_requires_two_teams():
    with pytest.raises(ValueError, match="方案必须包含两支球队"):
        expand_away_scenario({}, {"enabled": False}, 1, "job")
    with pytest.raises(ValueError, match="方案必须包含两支球队"):
        expand_away_scenario({"teams": [team()]}, {"enabled": False}, 1, "job")


def test_expand_validates_seed():
    scenario = {"teams": [team(), team()]}
    for seed in ("1", True, 1.5):
        with pytest.raises(ValueError, match="随机种子必须为整数"):
            expand_away_scenario(scenario, {"enabled": False}, seed, "job")


def test_expand_batch_rotation_maps_seeds_to_entries_in_order():
    entries = [
        entry(name="A", tactic=tactic(tactic_name="A", mentality=1)),
        entry(name="B", tactic=tactic(tactic_name="B", mentality=7)),
    ]
    scenario = {"teams": [team(), team()]}
    snapshot = copy.deepcopy(scenario)
    pool = {"enabled": True, "rotation": {"enabled": True, "rounds": 1}, "entries": entries}
    results = expand_away_scenarios(scenario, pool, [11, 12], "job")
    mapping = draws(entries, [11, 12], "job", rotation_enabled=True, rounds=1)
    assert mapping == {11: 0, 12: 1}
    assert [result["teams"][1]["tactic_name"] for result in results] == ["A", "B"]
    assert [result["teams"][1]["mentality"] for result in results] == [1, 7]
    assert all(result["teams"][0] == snapshot["teams"][0] for result in results)
    assert all("away_tactic_pool" not in result for result in results)
    assert scenario == snapshot
    assert results[0] is not results[1]


def test_expand_batch_rotation_repeats_entries_over_rounds():
    entries = [
        entry(name="A", tactic=tactic(tactic_name="A")),
        entry(name="B", tactic=tactic(tactic_name="B")),
    ]
    pool = {"enabled": True, "rotation": {"enabled": True, "rounds": 5}, "entries": entries}
    results = expand_away_scenarios({"teams": [team(), team()]}, pool, list(range(10)), "job")
    assert [result["teams"][1]["tactic_name"] for result in results] == ["A", "B"] * 5
    assert len({id(result) for result in results}) == 10


def test_expand_batch_random_mode_matches_single_seed_expansion():
    entries = [
        entry(name=f"T{index}", tactic=tactic(tactic_name=f"T{index}")) for index in range(4)
    ]
    scenario = {"teams": [team(), team()]}
    pool = {"enabled": True, "entries": entries}
    seeds = [3, 9, 15, 27]
    results = expand_away_scenarios(scenario, pool, seeds, "job")
    assert results == [expand_away_scenario(scenario, pool, seed, "job") for seed in seeds]


def test_expand_batch_is_deterministic_and_returns_independent_copies():
    entries = [
        entry(name=f"T{index}", tactic=tactic(tactic_name=f"T{index}")) for index in range(3)
    ]
    scenario = {"teams": [team(), team()]}
    pool = {"enabled": True, "entries": entries}
    first = expand_away_scenarios(scenario, pool, [4, 8], "job")
    second = expand_away_scenarios(scenario, pool, [4, 8], "job")
    assert first == second
    assert all(left is not right for left, right in zip(first, second, strict=True))
    first[0]["teams"][1]["mentality"] = 7
    assert second[0]["teams"][1]["mentality"] == 3


def test_expand_batch_disabled_pool_returns_one_copy_per_seed():
    pool = {"enabled": False, "entries": [entry()]}
    scenario = {"teams": [team(), team()], "away_tactic_pool": pool}
    snapshot = copy.deepcopy(scenario)
    results = expand_away_scenarios(scenario, pool, [1, 2], "job")
    assert results == [snapshot, snapshot]
    assert results[0] is not results[1]
    assert scenario == snapshot


def test_expand_batch_rotation_mismatch_raises_rotation_message():
    pool = {
        "enabled": True,
        "rotation": {"enabled": True, "rounds": 2},
        "entries": [entry(name="A"), entry(name="B")],
    }
    with pytest.raises(ValueError, match="轮战模式每方案需要 2 套 × 2 轮 = 4 场，当前种子数为 3"):
        expand_away_scenarios({"teams": [team(), team()]}, pool, [1, 2, 3], "job")


def test_expand_batch_validates_seed_list():
    scenario = {"teams": [team(), team()]}
    for seeds in ("1", 1, None):
        with pytest.raises(ValueError, match="随机种子列表格式无效"):
            expand_away_scenarios(scenario, {"enabled": False}, seeds, "job")
    for seeds in ([1, "2"], [True], [1.5]):
        with pytest.raises(ValueError, match="随机种子必须为整数"):
            expand_away_scenarios(scenario, {"enabled": False}, seeds, "job")


def test_expand_validates_salt():
    scenario = {"teams": [team(), team()]}
    for salt in (None, "", "   ", "x" * 81, "bad\nsalt", 7):
        with pytest.raises(ValueError, match="客队战术池抽取来源须为1–80个可读字符"):
            expand_away_scenario(scenario, {"enabled": False}, 1, salt)
        with pytest.raises(ValueError, match="客队战术池抽取来源须为1–80个可读字符"):
            expand_away_scenarios(scenario, {"enabled": False}, [1], salt)


def test_expand_real_mode_trims_24_player_roster():
    pool = {
        "enabled": True,
        "real": {"enabled": True},
        "entries": [entry(roster=positioned_roster(24))],
    }
    result = expand_away_scenario({"teams": [team(), team()]}, pool, 3, "job")
    away = result["teams"][1]
    assert away["roster_size"] == MATCH_ROSTER_SIZE
    assert away["roster_trim"]["source_size"] == 24
    assert away["tactic_name"] == "客队战术"


def test_expand_batch_real_mode_trims_each_roster():
    roster = positioned_roster(26)
    entries = [
        entry(name="A", tactic=tactic(tactic_name="A"), roster=roster),
        entry(name="B", tactic=tactic(tactic_name="B"), roster=roster),
    ]
    pool = {
        "enabled": True,
        "real": {"enabled": True},
        "rotation": {"enabled": True, "rounds": 1},
        "entries": entries,
    }
    results = expand_away_scenarios({"teams": [team(), team()]}, pool, [1, 2], "job")
    assert [result["teams"][1]["tactic_name"] for result in results] == ["A", "B"]
    assert all(result["teams"][1]["roster_trim"]["source_size"] == 26 for result in results)


def test_apply_accepts_raw_or_normalized_entry():
    normalized = normalize_away_pool({"entries": [entry()]})["entries"][0]
    for value in (entry(), normalized):
        result = apply_away_entry(team(), value, uniform_enabled=False)
        assert result["tactic_name"] == "客队战术"
