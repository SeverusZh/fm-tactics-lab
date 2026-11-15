"""战术阶段校验性质测试。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fm27lab.domain.tactics import Catalog, validate_phases

FAST = dict(max_examples=15, deadline=None, derandomize=True)


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


CATALOG = Catalog.from_mapping(catalog_data())


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


def phases(first=None, second=None):
    first = [cell() for _ in range(11)] if first is None else first
    second = [cell(role="OPCentreBack") for _ in range(11)] if second is None else second
    return [first, second]


@settings(**FAST)
@given(st.data())
def test_validated_phases_are_a_fixed_point(data):
    duty = data.draw(st.sampled_from(list(CATALOG.duties)))
    raw_instructions = data.draw(
        st.dictionaries(st.integers(0, 500), st.integers(0, 0xFFFFFFFF), max_size=4)
    )
    instructions = {str(key): value for key, value in raw_instructions.items()}
    target_player = data.draw(st.integers(0, 255))
    target_position = data.draw(st.integers(0, 0xFFFFFFFF))
    shared = dict(
        duty=duty,
        instructions=instructions,
        target_player=target_player,
        target_position=target_position,
    )
    value = [ [cell(**shared) for _ in range(11)], [cell(role="OPCentreBack", **shared) for _ in range(11)] ]

    validated = validate_phases(value, CATALOG)

    assert validated == validate_phases(validated, CATALOG)
    assert len(validated) == 2
    for phase_index, phase in enumerate(validated):
        assert len(phase) == 11
        for item in phase:
            assert item["duty"] == duty
            assert item["instructions"] == instructions
            assert item["target_player"] == target_player
            assert item["target_position"] == target_position
            assert CATALOG.role(item["role"]).phase == phase_index


def test_instruction_keys_are_normalized_to_decimal_strings():
    instructions = {"007": 5, "3": 4294967295, "0": 0}
    value = phases(first=[cell(instructions=instructions) for _ in range(11)])

    validated = validate_phases(value, CATALOG)

    assert validated[0][0]["instructions"] == {"7": 5, "3": 4294967295, "0": 0}


@pytest.mark.parametrize("target", [-1, 256, 1000])
def test_target_player_out_of_range_is_rejected(target):
    value = phases(first=[cell(target_player=target) for _ in range(11)])

    with pytest.raises(ValueError, match="盯防球员"):
        validate_phases(value, CATALOG)


@pytest.mark.parametrize("target", [-1, 2**64])
def test_target_position_out_of_range_is_rejected(target):
    value = phases(first=[cell(target_position=target) for _ in range(11)])

    with pytest.raises(ValueError, match="盯防位置"):
        validate_phases(value, CATALOG)


@pytest.mark.parametrize("phase_index", [0, 1])
def test_role_must_belong_to_its_phase(phase_index):
    value = phases()
    other = "OPCentreBack" if phase_index == 0 else "CentreBack"
    value[phase_index] = [cell(role=other) for _ in range(11)]

    with pytest.raises(ValueError, match="阶段不一致"):
        validate_phases(value, CATALOG)


@pytest.mark.parametrize("value", [[], [phases()[0]], phases() + [phases()[0]]])
def test_exactly_two_phases_are_required(value):
    with pytest.raises(ValueError, match="两个阶段"):
        validate_phases(value, CATALOG)


@pytest.mark.parametrize("count", [0, 10, 12])
def test_each_phase_requires_eleven_slots(count):
    value = phases(first=[cell() for _ in range(count)])

    with pytest.raises(ValueError, match="11 个位置"):
        validate_phases(value, CATALOG)
