from __future__ import annotations

import copy

import pytest

from fm27lab.domain.tactics import Catalog, validate_phases


def catalog_data():
    return {
        "positions": [
            {"id": "GK", "mask": 1, "x": 50, "y": 92},
            {"id": "DC", "mask": 16, "x": 50, "y": 76},
            {"id": "ST", "mask": 128, "x": 50, "y": 20},
        ],
        "roles": [
            {"id": "Goalkeeper", "label": "门将", "phase": 0, "flags": "1", "defaults": []},
            {"id": "CentreBack", "label": "中后卫", "phase": 0, "flags": "2", "defaults": []},
            {"id": "Overlap", "label": "套边中卫", "phase": 0, "flags": "3", "defaults": []},
            {"id": "Sweeper", "label": "清道夫", "phase": 0, "flags": "5", "defaults": []},
            {"id": "Striker", "label": "中锋", "phase": 0, "flags": "4", "defaults": []},
            {"id": "OPGoalkeeper", "label": "防守门将", "phase": 1, "flags": "8", "defaults": []},
            {"id": "OPCentreBack", "label": "防守中卫", "phase": 1, "flags": "16", "defaults": []},
            {"id": "OPStriker", "label": "防守中锋", "phase": 1, "flags": "32", "defaults": []},
        ],
        "duties": ["0", "2097152"],
        "role_eligibility": {
            "GK": [["Goalkeeper"], ["OPGoalkeeper"]],
            "DC": [["CentreBack", "Overlap", "Sweeper"], ["OPCentreBack"]],
            "ST": [["Striker"], ["OPStriker"]],
        },
        "role_eligibility_context": {
            f"{cb}:{dm}": {
                "GK": [["Goalkeeper"], ["OPGoalkeeper"]],
                "DC": [
                    ["CentreBack", "Sweeper"] if cb == 0 and dm == 0 else ["CentreBack"],
                    ["OPCentreBack"],
                ],
                "ST": [["Striker"], ["OPStriker"]],
            }
            for cb in (0, 3)
            for dm in (0, 1)
        },
    }


def cell(position="DC", role="CentreBack", duty="0", **extra):
    value = {
        "position": position,
        "role": role,
        "duty": duty,
        "instructions": {},
        "target_player": 255,
        "target_position": 0,
    }
    value.update(extra)
    return value


def phases():
    first = [cell() for _ in range(11)]
    second = [cell(role="OPCentreBack") for _ in range(11)]
    return [first, second]


def test_context_table_is_authoritative_over_flat_eligibility():
    catalog = Catalog.from_mapping(catalog_data())
    false_accept = [[cell(role="Overlap") for _ in range(11)], phases()[1]]
    with pytest.raises(ValueError, match="资格"):
        validate_phases(false_accept, catalog)


def test_valid_catalog_and_two_phase_plan():
    catalog = Catalog.from_mapping(catalog_data())
    assert catalog.position("GK").mask == 1
    assert catalog.role("CentreBack").phase == 0
    result = validate_phases(phases(), catalog)
    assert len(result) == 2
    assert len(result[0]) == 11
    assert result[0][0]["role"] == "CentreBack"


def test_catalog_rejects_duplicate_and_unknown_ids():
    duplicate = catalog_data()
    duplicate["positions"].append({"id": "GK", "mask": 3, "x": 1, "y": 1})
    with pytest.raises(ValueError, match="位置"):
        Catalog.from_mapping(duplicate)
    unknown = catalog_data()
    unknown["role_eligibility"]["DC"][0].append("MissingRole")
    with pytest.raises(ValueError, match="角色资格"):
        Catalog.from_mapping(unknown)


def test_invalid_phase_and_slot_counts_are_rejected():
    catalog = Catalog.from_mapping(catalog_data())
    with pytest.raises(ValueError, match="两个阶段"):
        validate_phases(phases()[:1], catalog)
    with pytest.raises(ValueError, match="11"):
        validate_phases([phases()[0][:10], phases()[1]], catalog)


def test_unknown_position_and_role_are_rejected():
    catalog = Catalog.from_mapping(catalog_data())
    with pytest.raises(ValueError, match="位置"):
        validate_phases([[cell(position="XX") for _ in range(11)], phases()[1]], catalog)
    with pytest.raises(ValueError, match="角色"):
        validate_phases([[cell(role="Missing") for _ in range(11)], phases()[1]], catalog)


def test_role_phase_and_eligibility_are_enforced():
    catalog = Catalog.from_mapping(catalog_data())
    wrong_phase = [[cell(role="OPCentreBack") for _ in range(11)], phases()[1]]
    with pytest.raises(ValueError, match="阶段"):
        validate_phases(wrong_phase, catalog)
    wrong_position = [[cell(position="ST", role="CentreBack") for _ in range(11)], phases()[1]]
    with pytest.raises(ValueError, match="资格"):
        validate_phases(wrong_position, catalog)


def test_duty_and_instruction_boundaries_are_enforced():
    catalog = Catalog.from_mapping(catalog_data())
    bad_duty = [[cell(duty="999") for _ in range(11)], phases()[1]]
    with pytest.raises(ValueError, match="职责"):
        validate_phases(bad_duty, catalog)
    bad_key = [[cell(instructions={"x": 1}) for _ in range(11)], phases()[1]]
    with pytest.raises(ValueError, match="指令"):
        validate_phases(bad_key, catalog)
    bad_value = [[cell(instructions={"2": 2**32}) for _ in range(11)], phases()[1]]
    with pytest.raises(ValueError, match="指令"):
        validate_phases(bad_value, catalog)


def test_target_boundaries_are_enforced():
    catalog = Catalog.from_mapping(catalog_data())
    bad_player = [[cell(target_player=256) for _ in range(11)], phases()[1]]
    with pytest.raises(ValueError, match="盯防"):
        validate_phases(bad_player, catalog)
    bad_position = [[cell(target_position=-1) for _ in range(11)], phases()[1]]
    with pytest.raises(ValueError, match="盯防"):
        validate_phases(bad_position, catalog)


def test_malformed_catalog_always_raises_value_error():
    duplicate_role = catalog_data()
    duplicate_role["roles"].append({"id": "CentreBack", "label": "x", "phase": 0, "flags": "1"})
    with pytest.raises(ValueError, match="角色"):
        Catalog.from_mapping(duplicate_role)
    duplicate_duty = catalog_data()
    duplicate_duty["duties"].append("0")
    with pytest.raises(ValueError, match="职责"):
        Catalog.from_mapping(duplicate_duty)
    missing_mask = catalog_data()
    missing_mask["positions"][0].pop("mask")
    with pytest.raises(ValueError, match="位置"):
        Catalog.from_mapping(missing_mask)
    bad_duty = catalog_data()
    bad_duty["duties"] = [0, None]
    with pytest.raises(ValueError, match="职责"):
        Catalog.from_mapping(bad_duty)
    empty_eligibility = catalog_data()
    empty_eligibility["role_eligibility"] = {}
    with pytest.raises(ValueError, match="资格"):
        Catalog.from_mapping(empty_eligibility)
    unhashable = catalog_data()
    unhashable["role_eligibility"]["DC"][0].append([])
    with pytest.raises(ValueError, match="角色资格"):
        Catalog.from_mapping(unhashable)


def test_normalized_output_defaults_and_input_are_stable():
    catalog = Catalog.from_mapping(catalog_data())
    value = phases()
    value[0][0]["instructions"] = {"01": 7}
    value[0][0]["target_player"] = 0
    value[1][0]["target_position"] = 2**64 - 1
    snapshot = copy.deepcopy(value)
    result = validate_phases(value, catalog)
    assert result[0][0]["instructions"] == {"1": 7}
    assert result[0][0]["target_player"] == 0
    assert result[0][0]["target_position"] == 0
    assert result[1][0]["target_position"] == 2**64 - 1
    assert result[0][1]["instructions"] == {}
    assert result[0][1]["target_player"] == 255
    assert value == snapshot


def test_context_bucket_changes_eligibility():
    catalog = Catalog.from_mapping(catalog_data())
    two_cb = [cell(role="Sweeper"), cell(role="Sweeper")] + [
        cell(position="GK", role="Goalkeeper") for _ in range(9)
    ]
    second = [cell(position="GK", role="OPGoalkeeper") for _ in range(11)]
    assert len(validate_phases([two_cb, second], catalog)) == 2
    three_cb = [cell(role="Sweeper") for _ in range(3)] + [
        cell(position="GK", role="Goalkeeper") for _ in range(8)
    ]
    with pytest.raises(ValueError, match="资格"):
        validate_phases([three_cb, second], catalog)


def test_context_must_cover_four_buckets_and_all_positions():
    missing_bucket = catalog_data()
    missing_bucket["role_eligibility_context"].pop("0:1")
    with pytest.raises(ValueError, match="四个桶"):
        Catalog.from_mapping(missing_bucket)
    missing_position = catalog_data()
    missing_position["role_eligibility_context"]["3:0"].pop("ST")
    with pytest.raises(ValueError, match="全部位置"):
        Catalog.from_mapping(missing_position)


def test_missing_cell_fields_use_documented_defaults():
    catalog = Catalog.from_mapping(catalog_data())
    value = phases()
    for key in ("instructions", "target_player", "target_position"):
        value[0][0].pop(key)
    result = validate_phases(value, catalog)
    assert result[0][0]["instructions"] == {}
    assert result[0][0]["target_player"] == 255
    assert result[0][0]["target_position"] == 0
