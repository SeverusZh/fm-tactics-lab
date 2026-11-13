"""Set-piece domain tests driven by synthetic enum catalogs and snapshots."""

from __future__ import annotations

import copy
import re

import pytest

from fm27lab.domain.setpieces import (
    TYPE_NAMES,
    build_catalog,
    defaults,
    encode_records,
    normalize,
)

ROUTINE_VALUES = [[1, 2, 3, 4, 5, 6], [7], [8, 9, 10], [], [], [], [], []]
ROUTINE_PRIORITY = [0, 2, 1]
FOOT_TYPES = (5, 7)
STRATEGY_KIND_BY_TYPE = {
    2: "defensive_line",
    3: "defensive_line",
    5: "corner_target",
    6: "free_kick_risk",
    7: "free_kick_risk",
    8: "free_kick_risk",
}


def make_enums() -> dict:
    return {
        "allowed": {str(group): list(range(1, 16)) for group in range(8)},
        "attack": [{"id": 1, "label": "进攻任务"}],
        "defend": [{"id": 1, "label": "防守任务"}],
        "categories": [{"id": 1, "label": "角色类别"}],
        "corner_target": [{"id": 1, "label": "角球目标"}],
        "free_kick_risk": [{"id": 1, "label": "任意球风险"}],
        "swing": [{"id": 0, "label": "内旋"}, {"id": 1, "label": "外旋"}],
        "defensive_line": [{"id": 1, "label": "防线"}],
    }


def make_routine(kind: int, *, frequency: int = None) -> dict:
    groups = [{"id": group, "values": list(tasks)} for group, tasks in enumerate(ROUTINE_VALUES)]
    return {
        "type": kind,
        "frequency": kind % 3 if frequency is None else frequency,
        "strategy": 255,
        "swing": 255,
        "priority": list(ROUTINE_PRIORITY),
        "groups": groups,
        "backups": [],
    }


def make_snapshot_team(*, variants: int = 1) -> dict:
    manager = bytearray(0x1CDF)
    manager[0x1410:0x1413] = bytes([0, 1, 0])
    return {
        "routine_variants": [[make_routine(kind) for _ in range(variants)] for kind in range(10)],
        "manager_tactical_hex": bytes(manager).hex(),
    }


def make_value() -> dict:
    return copy.deepcopy(defaults(make_snapshot_team()))


def raise_for(function, value, expected_message, **kwargs):
    with pytest.raises(ValueError, match=re.escape(expected_message)):
        function(value, **kwargs)


def test_type_names_follow_native_numeric_order():
    assert TYPE_NAMES == [
        "防守角球",
        "防守直接任意球",
        "防守边路任意球",
        "防守远距离任意球",
        "防守界外球",
        "进攻角球",
        "进攻直接任意球",
        "进攻边路任意球",
        "进攻远距离任意球",
        "进攻界外球",
    ]


def test_build_catalog_extends_enum_payload_with_types_and_frequencies():
    source = make_enums()
    catalog = build_catalog(source)
    assert catalog["allowed"] == source["allowed"]
    assert "types" not in source
    assert [entry["id"] for entry in catalog["types"]] == list(range(10))
    assert [entry["label"] for entry in catalog["types"]] == TYPE_NAMES
    assert [entry["strategy_kind"] for entry in catalog["types"]] == [
        STRATEGY_KIND_BY_TYPE.get(kind) for kind in range(10)
    ]
    assert [entry["swing"] for entry in catalog["types"]] == [kind in FOOT_TYPES for kind in range(10)]
    assert [entry["label"] for entry in catalog["frequencies"]] == [
        "较少 · 权重2",
        "正常 · 权重5",
        "较多 · 权重8",
    ]


def test_defaults_ports_routine_variants_into_complete_structure():
    result = defaults(make_snapshot_team())
    assert set(result) == {"routines", "throw_styles", "role_priorities"}
    assert set(result["routines"]) == {str(kind) for kind in range(10)}
    assert result["throw_styles"] == [0, 1, 0]
    assert result["role_priorities"] == {str(group): [] for group in range(8)}
    record = result["routines"]["0"][0]
    assert set(record) == {
        "name",
        "opaque_flags",
        "frequency",
        "strategy",
        "swing",
        "groups",
        "backups",
        "priority",
    }
    assert record["name"] == f"{TYPE_NAMES[0]} 1"
    assert record["opaque_flags"] == 0
    assert record["frequency"] == 0
    assert record["strategy"] == 255
    assert record["swing"] == 255
    assert record["priority"] == ROUTINE_PRIORITY
    assert record["groups"] == ROUTINE_VALUES
    assert record["backups"] == [[0] * len(tasks) for tasks in ROUTINE_VALUES]


def test_defaults_places_backups_by_group_and_slot():
    team = make_snapshot_team()
    team["routine_variants"][0][0]["backups"] = [[0, 1, 9], [2, 0, 3]]
    record = defaults(team)["routines"]["0"][0]
    assert record["backups"][0][1] == 9
    assert record["backups"][2][0] == 3
    assert record["backups"][0][0] == 0


def test_defaults_names_variants_in_native_order():
    result = defaults(make_snapshot_team(variants=2))
    assert [record["name"] for record in result["routines"]["0"]] == [
        f"{TYPE_NAMES[0]} 1",
        f"{TYPE_NAMES[0]} 2",
    ]


def test_defaults_rejects_snapshot_with_missing_variants():
    team = make_snapshot_team()
    team["routine_variants"] = team["routine_variants"][:9]
    with pytest.raises(ValueError, match=re.escape("定位球快照格式无效")):
        defaults(team)


def test_normalize_returns_complete_value_for_unchanged_payload():
    base = make_value()
    assert normalize(copy.deepcopy(base), 0, 23, enums=make_enums(), default_value=base) == base


def test_normalize_applies_throw_styles_and_role_priorities():
    base = make_value()
    value = copy.deepcopy(base)
    value["throw_styles"] = [1, 0, 1]
    value["role_priorities"]["3"] = [5, 2]
    result = normalize(value, 0, 23, enums=make_enums(), default_value=base)
    assert result["throw_styles"] == [1, 0, 1]
    assert result["role_priorities"]["3"] == [5, 2]
    assert result["role_priorities"]["0"] == []


def test_normalize_truncates_routine_names_and_fills_defaults():
    base = make_value()
    value = copy.deepcopy(base)
    row = value["routines"]["0"][0]
    row["name"] = "长" * 80
    row.pop("opaque_flags")
    result = normalize(value, 0, 23, enums=make_enums(), default_value=base)
    assert result["routines"]["0"][0]["name"] == "长" * 64
    assert result["routines"]["0"][0]["opaque_flags"] == 0


def test_normalize_accepts_roster_size_boundary():
    base = make_value()
    value = copy.deepcopy(base)
    value["role_priorities"]["7"] = [22]
    result = normalize(value, 1, 23, enums=make_enums(), default_value=base)
    assert result["role_priorities"]["7"] == [22]


def test_normalize_rejects_malformed_payloads():
    base = make_value()

    def broken(mutate):
        value = copy.deepcopy(base)
        mutate(value)
        return value

    cases = [
        ([(1,), 0, 23], "定位球设置格式错误", None),
        (broken(lambda value: value.__setitem__("throw_styles", [0, 1])), "界外球必须包含后场、中场和前场三种策略", None),
        (broken(lambda value: value["throw_styles"].__setitem__(0, 2)), "定位球设置数值无效", None),
        (broken(lambda value: value["role_priorities"].__setitem__("0", [1, 1])), "定位球角色球员顺序无效", None),
        (broken(lambda value: value["role_priorities"].__setitem__("0", [23])), "定位球设置数值无效", None),
        (broken(lambda value: value["role_priorities"].__setitem__("0", "1")), "定位球角色球员顺序无效", None),
        (broken(lambda value: value["routines"].__setitem__("0", [])), "每种定位球保留1–3套套路", None),
        (broken(lambda value: value["routines"].__setitem__("0", [make_routine(0)] * 4)), "每种定位球保留1–3套套路", None),
        (
            broken(lambda value: value["routines"]["0"][0].__setitem__("priority", [0, 1, 3])),
            "定位球分配顺序必须保留原版角色类别",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0].__setitem__("priority", [0, 2, 2])),
            "定位球分配顺序必须保留原版角色类别",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0].__setitem__("groups", ROUTINE_VALUES[:7])),
            "定位球任务组不完整",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0].__setitem__("backups", [[0] * 6] + [[0]] * 7)),
            "定位球任务与备用任务不匹配",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0]["groups"][0].__setitem__(0, 0)),
            "该定位球角色不能使用所选任务",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0]["groups"][0].__setitem__(0, 16)),
            "定位球设置数值无效",
            None,
        ),
        (
            broken(
                lambda value: (
                    value["routines"]["0"][0]["groups"][5].append(1),
                    value["routines"]["0"][0]["backups"][5].append(0),
                )
            ),
            "该定位球不使用此角色类别",
            None,
        ),
        (
            broken(
                lambda value: (
                    value["routines"]["0"][0]["groups"][0].pop(),
                    value["routines"]["0"][0]["backups"][0].pop(),
                )
            ),
            f"{TYPE_NAMES[0]}需要分配10项任务；先移除旧任务再添加新任务",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0].__setitem__("strategy", 0)),
            "该类型定位球不使用此发球策略",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0].__setitem__("swing", 2)),
            "该类型定位球不使用此发球策略",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0].__setitem__("frequency", 3)),
            "定位球设置数值无效",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0].__setitem__("opaque_flags", 256)),
            "定位球设置数值无效",
            None,
        ),
        (
            broken(lambda value: value["routines"]["0"][0]["groups"].pop()),
            "定位球任务组不完整",
            None,
        ),
    ]
    for payload, message, _ in cases:
        if isinstance(payload, tuple):
            argument = payload[0]
        else:
            argument = payload
        with pytest.raises(ValueError, match=re.escape(message)):
            normalize(argument, 0, 23, enums=make_enums(), default_value=base)


def test_normalize_rejects_task_outside_enum_allowed_group():
    base = make_value()
    value = copy.deepcopy(base)
    value["routines"]["0"][0]["groups"][0][0] = 6
    allowed_enums = make_enums()
    allowed_enums["allowed"]["0"] = [1, 2, 3, 4, 5]
    with pytest.raises(ValueError, match=re.escape("该定位球角色不能使用所选任务")):
        normalize(value, 0, 23, enums=allowed_enums, default_value=base)


def test_encode_records_returns_empty_for_unchanged_payload():
    base = make_value()
    assert encode_records(copy.deepcopy(base), 0, base) == []


def test_encode_records_emits_throw_style_changes_with_side():
    base = make_value()
    value = copy.deepcopy(base)
    value["throw_styles"] = [0, 1, 1]
    assert encode_records(value, 1, base) == [(46, 1, 2, 0, 1)]


def test_encode_records_emits_role_priority_lists():
    base = make_value()
    value = copy.deepcopy(base)
    value["role_priorities"]["2"] = [7, 3]
    records = encode_records(value, 0, base)
    assert records == [(30, 0, 14, 0xFFFFFFFF, 0), (30, 0, 14, 0, 7), (30, 0, 14, 1, 3)]


def test_encode_records_emits_full_routine_replacement():
    base = make_value()
    value = copy.deepcopy(base)
    value["routines"]["0"][0]["frequency"] = 2
    expected = [
        (40, 0, 0, 0, 1),
        (41, 0, 0, 0, 2),
        (47, 0, 0, 0, 0),
        (42, 0, 0, 0, 0),
        (43, 0, 0, 0, 1),
        (43, 0, 0, 0, 2),
        (43, 0, 0, 0, 3),
        (43, 0, 0, 0, 4),
        (43, 0, 0, 0, 5),
        (43, 0, 0, 0, 6),
        (43, 0, 0, 2, 8),
        (43, 0, 0, 2, 9),
        (43, 0, 0, 2, 10),
        (43, 0, 0, 1, 7),
        (44, 0, 0, 0, 0),
        (44, 0, 0, 1, 2),
        (44, 0, 0, 2, 1),
        (45, 0, 0, 0, 0),
        (45, 0, 0, 1, 0),
        (45, 0, 0, 2, 0),
        (45, 0, 0, 3, 0),
        (45, 0, 0, 4, 0),
        (45, 0, 0, 5, 0),
        (45, 0, 0, 32, 0),
        (45, 0, 0, 64, 0),
        (45, 0, 0, 65, 0),
        (45, 0, 0, 66, 0),
    ]
    assert encode_records(value, 0, base) == expected


def test_encode_records_emits_strategy_and_swing_overrides():
    base = make_value()
    value = copy.deepcopy(base)
    row = value["routines"]["0"][0]
    row["strategy"] = 1
    row["swing"] = 0
    records = encode_records(value, 0, base)
    assert records[:6] == [
        (40, 0, 0, 0, 1),
        (41, 0, 0, 0, 0),
        (47, 0, 0, 0, 0),
        (41, 0, 0, 1, 1),
        (41, 0, 0, 2, 0),
        (42, 0, 0, 0, 0),
    ]


def test_encode_records_uses_distinct_slots_for_multiple_variants():
    base = make_value()
    value = copy.deepcopy(base)
    value["routines"]["3"] = [copy.deepcopy(value["routines"]["3"][0]), copy.deepcopy(value["routines"]["3"][0])]
    value["routines"]["3"][0]["frequency"] = 1
    value["routines"]["3"][1]["frequency"] = 2
    records = encode_records(value, 1, base)
    assert records[0] == (40, 1, 3, 0, 2)
    assert (41, 1, 3 * 16, 0, 1) in records
    assert (41, 1, 3 * 16 + 1, 0, 2) in records


def test_encode_records_is_deterministic():
    base = make_value()
    value = copy.deepcopy(base)
    value["throw_styles"] = [1, 1, 0]
    first = encode_records(value, 0, base)
    second = encode_records(value, 0, base)
    assert first == second
