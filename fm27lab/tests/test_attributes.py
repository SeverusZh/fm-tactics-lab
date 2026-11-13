from __future__ import annotations

import copy

import pytest

from fm27lab.domain.attributes import (
    ATTRIBUTE_COUNT,
    GOALKEEPING,
    GROUP_ORDER,
    HIDDEN,
    MENTAL,
    PERSONALITY_KEYS,
    PHYSICAL,
    POSITION,
    POSITION_ATTRIBUTE_COUNT,
    TECHNICAL,
    VISIBLE_GROUPS,
    apply_bulk_attributes,
    apply_position_attributes,
    attribute_group,
    copy_player_profile,
    group_indices,
    pair_feet,
    undo_bulk,
)
from fm27lab.domain.roster import POSITION_INDEX, VISIBLE_ATTRIBUTES


def make_player(uid: int = 100, profile: dict | None = None) -> dict:
    player = {"source_uid": uid, "name": f"P{uid}", "attributes": [10] * ATTRIBUTE_COUNT}
    if profile is not None:
        player["native_profile"] = copy.deepcopy(profile)
    return player


def attrs(player: dict) -> list[int]:
    return player["attributes"]


def test_public_contract_constants():
    assert ATTRIBUTE_COUNT == 69
    assert POSITION_ATTRIBUTE_COUNT == 15
    assert VISIBLE_GROUPS == ("technical", "mental", "physical", "goalkeeping")
    assert GROUP_ORDER == ("technical", "mental", "physical", "goalkeeping", "hidden", "position")
    assert PERSONALITY_KEYS == (
        "professionalism",
        "loyalty",
        "sportsmanship",
        "temperament",
        "pressure",
        "ambition",
        "adaptability",
    )
    assert len(POSITION_INDEX) == POSITION_ATTRIBUTE_COUNT


def test_upstream_group_mapping_matches_issue_definition():
    assert TECHNICAL == frozenset({15, 16, 17, 18, 19, 20, 22, 23, 24, 37, 38, 42, 45, 50})
    assert MENTAL == frozenset({21, 25, 32, 33, 35, 41, 43, 44, 55, 58, 60, 66, 67, 68})
    assert PHYSICAL == frozenset({49, 51, 52, 53, 54, 57, 61, 65})
    assert GOALKEEPING == frozenset({26, 27, 28, 29, 30, 31, 34, 36, 46, 47, 48})
    assert POSITION == frozenset(range(15))
    assert HIDDEN == frozenset({39, 40, 56, 59, 62, 63, 64})


def test_groups_partition_all_69_indices_without_overlap():
    seen: set[int] = set()
    for group in GROUP_ORDER:
        indices = group_indices(group)
        assert isinstance(indices, frozenset)
        assert not seen & indices
        seen |= indices
    assert seen == frozenset(range(ATTRIBUTE_COUNT))
    assert frozenset(range(POSITION_ATTRIBUTE_COUNT, ATTRIBUTE_COUNT)) == (
        group_indices("technical")
        | group_indices("mental")
        | group_indices("physical")
        | group_indices("goalkeeping")
        | group_indices("hidden")
    )


def test_visible_groups_match_roster_visible_attributes():
    visible = frozenset().union(*(group_indices(group) for group in VISIBLE_GROUPS))
    assert visible == VISIBLE_ATTRIBUTES
    assert HIDDEN == frozenset(range(POSITION_ATTRIBUTE_COUNT, ATTRIBUTE_COUNT)) - visible
    assert not visible & HIDDEN
    assert not POSITION & (visible | HIDDEN)
    assert len(visible) == 47
    assert len(HIDDEN) == 7


def test_each_index_maps_to_exactly_one_group():
    for group in GROUP_ORDER:
        for index in group_indices(group):
            assert attribute_group(index) == group
    mapped = {attribute_group(index) for index in range(ATTRIBUTE_COUNT)}
    assert mapped == set(GROUP_ORDER)


def test_attribute_group_and_group_indices_reject_invalid_input():
    for index in (-1, ATTRIBUTE_COUNT, True, 1.0, "15"):
        with pytest.raises(ValueError, match="索引"):
            attribute_group(index)
    for group in ("unknown", "", True, None):
        with pytest.raises(ValueError, match="分组"):
            group_indices(group)


def test_bulk_attributes_only_edits_selected_visible_groups_by_default():
    player = make_player(100, profile={"current_ability": 150, "professionalism": 12, "loyalty": 8})
    original = copy.deepcopy(player)
    snapshot = apply_bulk_attributes([player], value=12)
    assert snapshot["indices"] == sorted(VISIBLE_ATTRIBUTES)
    assert snapshot["include_personality"] is False
    entry = snapshot["players"][0]
    assert entry["source_uid"] == 100
    assert entry["profile_present"] is True
    assert entry["attributes"] == [original["attributes"][index] for index in snapshot["indices"]]
    assert entry["personality"] == {}
    for index in VISIBLE_ATTRIBUTES:
        assert attrs(player)[index] == 60
    for index in HIDDEN:
        assert attrs(player)[index] == original["attributes"][index] == 10
    for index in POSITION:
        assert attrs(player)[index] == original["attributes"][index]
    assert player["native_profile"] == original["native_profile"]


def test_bulk_attributes_keeps_unselected_groups_untouched():
    player = make_player(100, profile={"professionalism": 12})
    player["attributes"][39] = 77
    player["attributes"][7] = 18
    apply_bulk_attributes([player], value=9.6, groups=("technical", "mental"))
    expected = 48
    for index in TECHNICAL | MENTAL:
        assert attrs(player)[index] == expected
    for index in (PHYSICAL | GOALKEEPING | HIDDEN) - {39}:
        assert attrs(player)[index] == 10
    assert attrs(player)[39] == 77
    assert attrs(player)[7] == 18
    assert player["native_profile"] == {"professionalism": 12}


def test_bulk_attributes_can_target_hidden_group_explicitly():
    player = make_player(100)
    snapshot = apply_bulk_attributes([player], value=7.4, groups=("hidden",))
    assert snapshot["indices"] == sorted(HIDDEN)
    expected = 37
    for index in HIDDEN:
        assert attrs(player)[index] == expected
    for index in VISIBLE_ATTRIBUTES | POSITION:
        assert attrs(player)[index] == 10


def test_bulk_attributes_personality_switch_writes_rounded_values():
    player = make_player(100, profile={"current_ability": 150, "professionalism": 3})
    snapshot = apply_bulk_attributes([player], value=12.6, include_personality=True)
    assert round(12.6) == 13
    for key in PERSONALITY_KEYS:
        assert player["native_profile"][key] == 13
    assert player["native_profile"]["current_ability"] == 150
    personality = snapshot["players"][0]["personality"]
    assert set(personality) == set(PERSONALITY_KEYS)
    assert personality["professionalism"] == {"present": True, "value": 3}
    assert personality["loyalty"] == {"present": False, "value": None}
    assert snapshot["include_personality"] is True


def test_bulk_attributes_creates_missing_native_profile_for_personality():
    player = make_player(100)
    assert "native_profile" not in player
    snapshot = apply_bulk_attributes([player], value=20, include_personality=True)
    assert player["native_profile"] == {key: 20 for key in PERSONALITY_KEYS}
    assert all(entry["present"] is False for entry in snapshot["players"][0]["personality"].values())
    assert snapshot["players"][0]["profile_present"] is False
    assert snapshot["players"][0]["attributes"] == [10] * len(VISIBLE_ATTRIBUTES)


def test_bulk_attributes_converts_display_value_to_internal_scale():
    low = make_player(100)
    high = make_player(101)
    middle = make_player(102)
    apply_bulk_attributes([low], value=1)
    apply_bulk_attributes([high], value=20)
    apply_bulk_attributes([middle], value=13.4)
    assert {attrs(low)[index] for index in VISIBLE_ATTRIBUTES} == {5}
    assert {attrs(high)[index] for index in VISIBLE_ATTRIBUTES} == {100}
    assert {attrs(middle)[index] for index in VISIBLE_ATTRIBUTES} == {67}
    assert all(1 <= value <= 100 for value in attrs(low)[POSITION_ATTRIBUTE_COUNT:])
    assert all(1 <= value <= 100 for value in attrs(high)[POSITION_ATTRIBUTE_COUNT:])


def test_bulk_attributes_snapshot_tracks_each_player_source_uid():
    players = [make_player(101), make_player(100)]
    snapshot = apply_bulk_attributes(players, value=10)
    assert [entry["source_uid"] for entry in snapshot["players"]] == [101, 100]


def test_bulk_attributes_rejects_invalid_group_and_value_arguments():
    player = make_player(100)
    with pytest.raises(ValueError, match="位置"):
        apply_bulk_attributes([player], value=10, groups=("position",))
    with pytest.raises(ValueError, match="分组"):
        apply_bulk_attributes([player], value=10, groups=("unknown",))
    with pytest.raises(ValueError, match="分组"):
        apply_bulk_attributes([player], value=10, groups="technical")
    with pytest.raises(ValueError, match="布尔"):
        apply_bulk_attributes([player], value=10, include_personality=1)
    for value in (0.9, 20.1, True, "10", None, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="属性显示值"):
            apply_bulk_attributes([player], value=value)
    assert attrs(player) == [10] * ATTRIBUTE_COUNT


def test_bulk_attributes_validates_players_before_mutation():
    good = make_player(100)
    bad = make_player(101)
    bad["attributes"] = bad["attributes"][:-1]
    with pytest.raises(ValueError, match="69"):
        apply_bulk_attributes([good, bad], value=15)
    assert attrs(good) == [10] * ATTRIBUTE_COUNT

    with pytest.raises(ValueError, match="source_uid"):
        apply_bulk_attributes([{"attributes": [10] * ATTRIBUTE_COUNT}], value=15)
    with pytest.raises(ValueError, match="source_uid"):
        apply_bulk_attributes([make_player(True)], value=15)
    with pytest.raises(ValueError, match="source_uid"):
        apply_bulk_attributes([make_player(100), make_player(100)], value=15)

    broken_type = make_player(102)
    broken_type["attributes"][15] = "10"
    with pytest.raises(ValueError, match="整数"):
        apply_bulk_attributes([broken_type], value=15)
    broken_position = make_player(103)
    broken_position["attributes"][0] = 21
    with pytest.raises(ValueError, match="范围"):
        apply_bulk_attributes([broken_position], value=15)
    broken_hidden = make_player(104)
    broken_hidden["attributes"][15] = 0
    with pytest.raises(ValueError, match="范围"):
        apply_bulk_attributes([broken_hidden], value=15)
    broken_profile = make_player(105)
    broken_profile["native_profile"] = "bad"
    with pytest.raises(ValueError, match="扩展"):
        apply_bulk_attributes([broken_profile], value=15)
    with pytest.raises(ValueError, match="格式"):
        apply_bulk_attributes(["bad"], value=15)


def test_position_bulk_by_index_only_changes_that_position():
    player = make_player(100)
    original = copy.deepcopy(player)
    snapshot = apply_position_attributes([player], position=7, value=18)
    assert attrs(player)[7] == 18
    for index in range(ATTRIBUTE_COUNT):
        if index != 7:
            assert attrs(player)[index] == original["attributes"][index]
    assert snapshot["indices"] == [7]
    assert snapshot["include_personality"] is False
    assert snapshot["players"][0] == {
        "source_uid": 100,
        "profile_present": False,
        "attributes": [10],
        "personality": {},
    }


def test_position_bulk_by_name_and_alias():
    player = make_player(100)
    apply_position_attributes([player], position="GK", value=20)
    assert attrs(player)[POSITION_INDEX["GK"]] == 20
    apply_position_attributes([player], position="DCR", value=3)
    assert attrs(player)[POSITION_INDEX["DC"]] == 3
    apply_position_attributes([player], position="ST", value=0)
    assert attrs(player)[POSITION_INDEX["ST"]] == 0


def test_position_bulk_rejects_invalid_position_or_value():
    player = make_player(100)
    for position in (-1, 15, True, "XYZ", 7.0, None):
        with pytest.raises(ValueError, match="位置"):
            apply_position_attributes([player], position=position, value=10)
    for value in (-1, 21, True, 7.5, "10", None):
        with pytest.raises(ValueError, match="0–20"):
            apply_position_attributes([player], position=7, value=value)
    assert attrs(player) == [10] * ATTRIBUTE_COUNT


def test_undo_restores_bulk_attributes_and_personality_exactly():
    player = make_player(100, profile={"current_ability": 150, "professionalism": 12, "loyalty": 8})
    player["attributes"][15] = 1
    player["attributes"][39] = 5
    original = copy.deepcopy(player)
    snapshot = apply_bulk_attributes([player], value=16.6, include_personality=True)
    assert player != original
    undo_bulk([player], snapshot)
    assert player == original


def test_undo_removes_personality_keys_absent_before():
    player = make_player(100, profile={"current_ability": 150})
    snapshot = apply_bulk_attributes([player], value=10, include_personality=True)
    assert player["native_profile"]["professionalism"] == 10
    undo_bulk([player], snapshot)
    assert player["native_profile"] == {"current_ability": 150}

    fresh = make_player(101)
    fresh_original = copy.deepcopy(fresh)
    snapshot = apply_bulk_attributes([fresh], value=10, include_personality=True)
    undo_bulk([fresh], snapshot)
    assert fresh == fresh_original
    assert "native_profile" not in fresh


def test_undo_position_snapshot_restores_previous_familiarity():
    player = make_player(100)
    player["attributes"][3] = 17
    original = copy.deepcopy(player)
    snapshot = apply_position_attributes([player], position="DC", value=4)
    assert attrs(player)[3] == 4
    undo_bulk([player], snapshot)
    assert player == original


def test_undo_rejects_changed_roster_without_mutation():
    first = make_player(100)
    second = make_player(101)
    snapshot = apply_bulk_attributes([first, second], value=15)
    reordered = [second, first]
    current = copy.deepcopy(reordered)
    with pytest.raises(ValueError, match="名单已变化，无法撤销"):
        undo_bulk(reordered, snapshot)
    assert reordered == current
    with pytest.raises(ValueError, match="名单已变化，无法撤销"):
        undo_bulk([first], snapshot)
    with pytest.raises(ValueError, match="名单已变化，无法撤销"):
        undo_bulk([first, make_player(999)], snapshot)
    assert attrs(first)[15] == 75
    assert attrs(second)[15] == 75


def test_undo_rejects_malformed_snapshot():
    player = make_player(100)
    snapshot = apply_bulk_attributes([player], value=10)
    broken: list[object] = [None, [], "snapshot"]
    missing_players = {key: value for key, value in snapshot.items() if key != "players"}
    broken.append(missing_players)
    bad_indices = copy.deepcopy(snapshot)
    bad_indices["indices"] = [0, ATTRIBUTE_COUNT]
    broken.append(bad_indices)
    bad_flag = copy.deepcopy(snapshot)
    bad_flag["include_personality"] = 1
    broken.append(bad_flag)
    bad_entry = copy.deepcopy(snapshot)
    bad_entry["players"] = ["bad"]
    broken.append(bad_entry)
    bad_attribute = copy.deepcopy(snapshot)
    bad_attribute["players"][0]["attributes"] = []
    broken.append(bad_attribute)
    bad_personality = copy.deepcopy(snapshot)
    bad_personality["players"][0]["personality"] = {"professionalism": "bad"}
    broken.append(bad_personality)
    bad_profile_present = copy.deepcopy(snapshot)
    bad_profile_present["players"][0]["profile_present"] = 1
    broken.append(bad_profile_present)
    for value in broken:
        with pytest.raises(ValueError, match="撤销记录格式无效"):
            undo_bulk([player], value)


def test_copy_profile_copies_visible_and_hidden_without_touching_position():
    source = make_player(200)
    target = make_player(300)
    for index in range(POSITION_ATTRIBUTE_COUNT):
        source["attributes"][index] = (index * 3) % 21
    for index in range(POSITION_ATTRIBUTE_COUNT, ATTRIBUTE_COUNT):
        source["attributes"][index] = 100 - index
    target["attributes"][3] = 9
    source_before = copy.deepcopy(source)
    target_before = copy.deepcopy(target)
    snapshot = copy_player_profile(source, target)
    expected_indices = sorted(VISIBLE_ATTRIBUTES | HIDDEN)
    assert snapshot["indices"] == expected_indices
    assert snapshot["include_personality"] is True
    assert snapshot["players"][0]["source_uid"] == 300
    for index in expected_indices:
        assert attrs(target)[index] == source["attributes"][index]
    for index in POSITION:
        assert attrs(target)[index] == target_before["attributes"][index]
    assert source == source_before
    undo_bulk([target], snapshot)
    assert target == target_before


def test_copy_profile_respects_selected_groups():
    source = make_player(200)
    target = make_player(300)
    source["attributes"][15] = 18
    source["attributes"][49] = 2
    source["attributes"][39] = 20
    snapshot = copy_player_profile(source, target, groups=("physical",))
    assert snapshot["indices"] == sorted(PHYSICAL)
    assert attrs(target)[49] == 2
    assert attrs(target)[15] == 10
    assert attrs(target)[39] == 10


def test_copy_profile_can_copy_position_familiarity_when_explicit():
    source = make_player(200)
    target = make_player(300)
    source["attributes"][0] = 20
    source["attributes"][7] = 12
    snapshot = copy_player_profile(source, target, groups=("position",), copy_personality=False)
    assert snapshot["indices"] == sorted(POSITION)
    assert attrs(target)[0] == 20
    assert attrs(target)[7] == 12


def test_copy_profile_personality_mirrors_source_keys():
    source = make_player(200, profile={"professionalism": 15, "loyalty": 5, "current_ability": 120})
    target = make_player(300, profile={"professionalism": 1, "temperament": 9, "current_ability": 100})
    snapshot = copy_player_profile(source, target)
    profile = target["native_profile"]
    assert profile["professionalism"] == 15
    assert profile["loyalty"] == 5
    assert "temperament" not in profile
    assert "sportsmanship" not in profile
    assert profile["current_ability"] == 100
    assert source["native_profile"] == {"professionalism": 15, "loyalty": 5, "current_ability": 120}
    undo_bulk([target], snapshot)
    assert target["native_profile"] == {"professionalism": 1, "temperament": 9, "current_ability": 100}


def test_copy_profile_can_skip_personality():
    source = make_player(200, profile={"professionalism": 15})
    target = make_player(300, profile={"professionalism": 1})
    snapshot = copy_player_profile(source, target, groups=("technical",), copy_personality=False)
    assert snapshot["include_personality"] is False
    assert target["native_profile"] == {"professionalism": 1}
    assert set(snapshot["indices"]) == set(TECHNICAL)


def test_copy_profile_rejects_invalid_arguments():
    source = make_player(200)
    target = make_player(300)
    with pytest.raises(ValueError, match="分组"):
        copy_player_profile(source, target, groups=("unknown",))
    with pytest.raises(ValueError, match="分组"):
        copy_player_profile(source, target, groups="technical")
    with pytest.raises(ValueError, match="布尔"):
        copy_player_profile(source, target, copy_personality=1)
    broken_target = make_player(301)
    broken_target["attributes"] = [10] * 68
    with pytest.raises(ValueError, match="69"):
        copy_player_profile(source, broken_target)
    broken_source = make_player(201)
    broken_source["native_profile"] = "bad"
    with pytest.raises(ValueError, match="扩展"):
        copy_player_profile(broken_source, make_player(302))
    with pytest.raises(ValueError, match="格式"):
        copy_player_profile(source, "bad")


def test_pair_feet_writes_preferred_left_foot():
    player = make_player(100)
    pair_feet(player, left_index=39, right_index=40, preferred="left", preferred_value=18, weaker_value=8)
    assert attrs(player)[39] == 18
    assert attrs(player)[40] == 8
    assert all(attrs(player)[index] == 10 for index in range(ATTRIBUTE_COUNT) if index not in {39, 40})


def test_pair_feet_writes_preferred_right_foot():
    player = make_player(100)
    pair_feet(player, left_index=39, right_index=40, preferred="right", preferred_value=18, weaker_value=8)
    assert attrs(player)[39] == 8
    assert attrs(player)[40] == 18


def test_pair_feet_uses_supplied_indices_not_fixed_slots():
    player = make_player(100)
    pair_feet(player, left_index=56, right_index=63, preferred="right", preferred_value=17, weaker_value=5)
    assert attrs(player)[56] == 5
    assert attrs(player)[63] == 17


def test_pair_feet_rejects_invalid_indices_direction_and_values():
    player = make_player(100)
    before = copy.deepcopy(player["attributes"])
    with pytest.raises(ValueError, match="相同"):
        pair_feet(player, left_index=39, right_index=39, preferred="left", preferred_value=18, weaker_value=8)
    for index in (14, 69, True):
        with pytest.raises(ValueError, match="15–68"):
            pair_feet(
                player, left_index=index, right_index=40, preferred="left", preferred_value=18, weaker_value=8
            )
    with pytest.raises(ValueError, match="惯用脚"):
        pair_feet(player, left_index=39, right_index=40, preferred="both", preferred_value=18, weaker_value=8)
    for value in (0, 21, True, 7.5, "18"):
        with pytest.raises(ValueError, match="1–20"):
            pair_feet(
                player, left_index=39, right_index=40, preferred="left", preferred_value=value, weaker_value=8
            )
        with pytest.raises(ValueError, match="1–20"):
            pair_feet(
                player,
                left_index=39,
                right_index=40,
                preferred="left",
                preferred_value=18,
                weaker_value=value,
            )
    for preferred_value, weaker_value in ((10, 10), (8, 9)):
        with pytest.raises(ValueError, match="左右脚配对值无效"):
            pair_feet(
                player,
                left_index=39,
                right_index=40,
                preferred="left",
                preferred_value=preferred_value,
                weaker_value=weaker_value,
            )
    assert player["attributes"] == before


def test_pair_feet_validates_target_player():
    with pytest.raises(ValueError, match="69"):
        pair_feet(
            {"attributes": [10] * 68},
            left_index=39,
            right_index=40,
            preferred="left",
            preferred_value=18,
            weaker_value=8,
        )
    with pytest.raises(ValueError, match="格式"):
        pair_feet("bad", left_index=39, right_index=40, preferred="left", preferred_value=18, weaker_value=8)


def test_snapshots_keep_old_values_after_players_change():
    player = make_player(100, profile={"professionalism": 3})
    snapshot = apply_bulk_attributes([player], value=15, include_personality=True)
    expected = copy.deepcopy(snapshot)
    attrs(player)[15] = 90
    player["native_profile"]["professionalism"] = 20
    assert snapshot == expected
    undo_bulk([player], snapshot)
    assert attrs(player)[15] == 10
    assert player["native_profile"]["professionalism"] == 3


def test_group_sets_are_immutable_frozen_sets():
    for group_set in (TECHNICAL, MENTAL, PHYSICAL, GOALKEEPING, POSITION, HIDDEN):
        assert isinstance(group_set, frozenset)
    assert group_indices("technical") is TECHNICAL


def test_half_values_use_half_up_rounding():
    player = make_player(100)
    apply_bulk_attributes([player], value=9.7, include_personality=True)
    assert {attrs(player)[index] for index in VISIBLE_ATTRIBUTES} == {49}
    assert player["native_profile"]["professionalism"] == 10

    half = make_player(101)
    apply_bulk_attributes([half], value=2.5, include_personality=True)
    assert {attrs(half)[index] for index in VISIBLE_ATTRIBUTES} == {13}
    assert half["native_profile"]["professionalism"] == 3

    teen = make_player(102)
    apply_bulk_attributes([teen], value=12.5, include_personality=True)
    assert {attrs(teen)[index] for index in VISIBLE_ATTRIBUTES} == {63}
    assert teen["native_profile"]["professionalism"] == 13

    low = make_player(103)
    apply_bulk_attributes([low], value=1.7, include_personality=True)
    assert {attrs(low)[index] for index in VISIBLE_ATTRIBUTES} == {9}
    assert low["native_profile"]["professionalism"] == 2

    high = make_player(104)
    apply_bulk_attributes([high], value=19.9, include_personality=True)
    assert {attrs(high)[index] for index in VISIBLE_ATTRIBUTES} == {100}
    assert high["native_profile"]["professionalism"] == 20


def test_undo_restores_absent_native_profile_exactly():
    player = make_player(100)
    original = copy.deepcopy(player)
    snapshot = apply_bulk_attributes([player], value=11, include_personality=True)
    assert snapshot["players"][0]["profile_present"] is False
    assert "native_profile" in player
    undo_bulk([player], snapshot)
    assert player == original
    assert "native_profile" not in player


def test_undo_restores_absent_profile_after_copy():
    source = make_player(200, profile={key: 14 for key in PERSONALITY_KEYS})
    target = make_player(300)
    original = copy.deepcopy(target)
    snapshot = copy_player_profile(source, target)
    assert snapshot["players"][0]["profile_present"] is False
    assert target["native_profile"] == {key: 14 for key in PERSONALITY_KEYS}
    undo_bulk([target], snapshot)
    assert target == original
    assert "native_profile" not in target


def test_undo_rejects_out_of_range_snapshot_values():
    player = make_player(100, profile={"professionalism": 5})
    bulk = apply_bulk_attributes([player], value=10)
    position = apply_position_attributes([player], position=3, value=14)
    personality_snapshot = apply_bulk_attributes([player], value=10, include_personality=True)
    cases: list[dict] = []
    bad_position = copy.deepcopy(position)
    bad_position["players"][0]["attributes"] = [21]
    cases.append(bad_position)
    for bad_value in (0, 101):
        bad_attributes = copy.deepcopy(bulk)
        bad_attributes["players"][0]["attributes"][0] = bad_value
        cases.append(bad_attributes)
    for bad_value in (0, 21, True, 1.5):
        bad_personality = copy.deepcopy(personality_snapshot)
        bad_personality["players"][0]["personality"]["professionalism"] = {
            "present": True,
            "value": bad_value,
        }
        cases.append(bad_personality)
    bad_presence = copy.deepcopy(personality_snapshot)
    bad_presence["players"][0]["profile_present"] = 1
    cases.append(bad_presence)
    for case in cases:
        with pytest.raises(ValueError, match="撤销记录格式无效"):
            undo_bulk([player], case)
    assert attrs(player)[15] == 50
    assert attrs(player)[3] == 14


def test_bulk_attributes_empty_group_selection_is_noop():
    player = make_player(100, profile={"professionalism": 5})
    original = copy.deepcopy(player)
    snapshot = apply_bulk_attributes([player], value=12, groups=())
    assert snapshot["indices"] == []
    assert snapshot["players"][0]["attributes"] == []
    assert snapshot["players"][0]["profile_present"] is True
    assert player == original
    undo_bulk([player], snapshot)
    assert player == original


def test_bulk_attributes_deduplicates_repeated_groups():
    player = make_player(100)
    snapshot = apply_bulk_attributes([player], value=6, groups=("technical", "technical", "mental"))
    assert snapshot["indices"] == sorted(TECHNICAL | MENTAL)
    assert len(snapshot["indices"]) == len(set(snapshot["indices"]))
    for index in TECHNICAL | MENTAL:
        assert attrs(player)[index] == 30


def test_hidden_group_snapshot_undo_restores_values():
    player = make_player(100)
    for index in HIDDEN:
        attrs(player)[index] = index % 90 + 1
    original = copy.deepcopy(player)
    snapshot = apply_bulk_attributes([player], value=3.2, groups=("hidden",))
    assert {attrs(player)[index] for index in HIDDEN} == {16}
    undo_bulk([player], snapshot)
    assert player == original


def test_copy_position_snapshot_undo_restores_target():
    source = make_player(200)
    target = make_player(300)
    source["attributes"][0] = 20
    source["attributes"][7] = 12
    original = copy.deepcopy(target)
    snapshot = copy_player_profile(source, target, groups=("position",), copy_personality=False)
    assert attrs(target)[0] == 20
    assert attrs(target)[7] == 12
    undo_bulk([target], snapshot)
    assert target == original


def test_undo_rejects_boolean_or_duplicate_indices():
    player = make_player(100)
    snapshot = apply_bulk_attributes([player], value=10)
    for indices in ([True], [15, 15]):
        broken = copy.deepcopy(snapshot)
        broken["indices"] = indices
        with pytest.raises(ValueError, match="撤销记录格式无效"):
            undo_bulk([player], broken)


def test_pair_feet_accepts_boundary_values():
    player = make_player(100)
    pair_feet(player, left_index=39, right_index=40, preferred="left", preferred_value=20, weaker_value=1)
    assert attrs(player)[39] == 20
    assert attrs(player)[40] == 1
    pair_feet(player, left_index=39, right_index=40, preferred="right", preferred_value=20, weaker_value=1)
    assert attrs(player)[39] == 1
    assert attrs(player)[40] == 20


def test_invalid_personality_values_in_profile_are_rejected():
    for bad_value in (99, 0, "x", True, 1.5):
        player = make_player(100, profile={"professionalism": bad_value})
        original = copy.deepcopy(player)
        with pytest.raises(ValueError, match="球员性格值无效"):
            apply_bulk_attributes([player], value=10, include_personality=True)
        with pytest.raises(ValueError, match="球员性格值无效"):
            apply_bulk_attributes([player], value=10)
        with pytest.raises(ValueError, match="球员性格值无效"):
            apply_position_attributes([player], position=7, value=10)
        assert player == original

    source = make_player(200)
    target = make_player(300, profile={"loyalty": 99})
    target_original = copy.deepcopy(target)
    with pytest.raises(ValueError, match="球员性格值无效"):
        copy_player_profile(source, target)
    assert target == target_original

    bad_source = make_player(201, profile={"professionalism": True})
    clean_target = make_player(301)
    clean_original = copy.deepcopy(clean_target)
    with pytest.raises(ValueError, match="球员性格值无效"):
        copy_player_profile(bad_source, clean_target)
    assert clean_target == clean_original


def test_valid_boundary_personality_profiles_roundtrip_undo():
    player = make_player(100, profile={"professionalism": 1, "loyalty": 20, "current_ability": 150})
    original = copy.deepcopy(player)
    snapshot = apply_bulk_attributes([player], value=10, include_personality=True)
    undo_bulk([player], snapshot)
    assert player == original

    source = make_player(200, profile={"professionalism": 1, "loyalty": 20})
    target = make_player(300, profile={"temperament": 20, "professionalism": 1})
    target_original = copy.deepcopy(target)
    snapshot = copy_player_profile(source, target)
    undo_bulk([target], snapshot)
    assert target == target_original


def test_undo_rejects_personality_presence_without_profile():
    player = make_player(100)
    snapshot = apply_bulk_attributes([player], value=10)
    forged = copy.deepcopy(snapshot)
    forged["players"][0]["personality"] = {"professionalism": {"present": True, "value": 10}}
    with pytest.raises(ValueError, match="撤销记录格式无效"):
        undo_bulk([player], forged)
    assert "native_profile" not in player


def test_undo_corrupt_second_entry_has_no_partial_write():
    first = make_player(100, profile={"professionalism": 5})
    second = make_player(101, profile={"loyalty": 6})
    snapshot = apply_bulk_attributes([first, second], value=10, include_personality=True)
    before = copy.deepcopy([first, second])
    corrupt = copy.deepcopy(snapshot)
    corrupt["players"][1]["attributes"][0] = 0
    with pytest.raises(ValueError, match="撤销记录格式无效"):
        undo_bulk([first, second], corrupt)
    assert [first, second] == before


def test_undo_accepts_boundary_old_values():
    hidden_low = make_player(100)
    for index in HIDDEN:
        attrs(hidden_low)[index] = 1
    low_original = copy.deepcopy(hidden_low)
    low_snapshot = apply_bulk_attributes([hidden_low], value=3, groups=("hidden",))
    undo_bulk([hidden_low], low_snapshot)
    assert hidden_low == low_original

    hidden_high = make_player(101)
    for index in HIDDEN:
        attrs(hidden_high)[index] = 100
    high_original = copy.deepcopy(hidden_high)
    high_snapshot = apply_bulk_attributes([hidden_high], value=3, groups=("hidden",))
    undo_bulk([hidden_high], high_snapshot)
    assert hidden_high == high_original

    position = make_player(102)
    attrs(position)[0] = 0
    attrs(position)[7] = 20
    position_original = copy.deepcopy(position)
    zero_snapshot = apply_position_attributes([position], position=0, value=20)
    twenty_snapshot = apply_position_attributes([position], position=7, value=0)
    undo_bulk([position], twenty_snapshot)
    undo_bulk([position], zero_snapshot)
    assert position == position_original
