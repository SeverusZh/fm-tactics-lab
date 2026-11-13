from __future__ import annotations

import copy

import pytest

from fm27lab.domain.pool import (
    DEFAULT_ATTRIBUTE_VALUE,
    MAX_ENTRIES,
    MAX_NAME,
    MAX_ROSTER,
    PROFILE,
    normalize_away_pool,
)

# Legacy schema: src/fm27_tactic_pool.py:6-16 constants, 37-166 validators, 168-192 normalize.
POSITION_CODES = ("GK", "SW", "DL", "DC", "DR", "DM", "ML", "MC", "MR", "AML", "ST")


def cell(position="GK", role="门将", duty="0"):
    return {"position": position, "role": role, "duty": duty}


def phases():
    return [[cell(position) for position in POSITION_CODES] for _ in range(2)]


def tactic(**overrides):
    value = {
        "tactic_name": "客队战术",
        "mentality": 3,
        "instructions": {"1": 2},
        "native_extra_team_bits": "0",
        "phases": phases(),
    }
    value.update(overrides)
    return value


def entry(name="战术一", **overrides):
    value = {"name": name, "weight": 1, "tactic": tactic()}
    value.update(overrides)
    return value


def roster_player(index=0, **overrides):
    value = {
        "name": f"存档球员{index + 1}",
        "source_uid": 1000 + index,
        "attributes": [10] * 15 + [50] * 54,
        "native_profile": {"engine_id": index},
    }
    value.update(overrides)
    return value


def roster(count=12, **overrides):
    value = {
        "club_uid": 7,
        "club": "存档客队",
        "coach": "存档教练",
        "source": "real_ai",
        "roster_size": count,
        "lineup": list(range(11)),
        "players": [roster_player(index) for index in range(count)],
    }
    value.update(overrides)
    return value


# Legacy defaults: src/fm27_tactic_pool.py:22-24.
def test_missing_sections_are_filled_with_legacy_defaults():
    assert normalize_away_pool({}) == {
        "profile": PROFILE,
        "enabled": False,
        "entries": [],
        "uniform": {"enabled": True, "attribute_value": DEFAULT_ATTRIBUTE_VALUE},
        "rotation": {"enabled": False, "rounds": 1},
        "real": {"enabled": False},
    }
    assert DEFAULT_ATTRIBUTE_VALUE == 15


def test_minimal_entry_normalizes_optional_fields():
    raw = {
        "name": "  战术一  ",
        "tactic": {
            "mentality": 1,
            "instructions": {},
            "native_extra_team_bits": "0",
            "phases": [
                [{"position": "GK", "role": "门将", "duty": "007"} for _ in range(11)],
                [{"position": "GK", "role": "门将", "duty": "0"} for _ in range(11)],
            ],
        },
    }
    normalized = normalize_away_pool({"entries": [raw]})["entries"][0]
    assert normalized["name"] == "战术一"
    assert normalized["weight"] == 1
    assert "roster" not in normalized
    assert normalized["tactic"] == {
        "tactic_name": "",
        "mentality": 1,
        "instructions": {},
        "native_extra_team_bits": "0",
        "phases": [
            [
                {
                    "position": "GK",
                    "role": "门将",
                    "duty": "7",
                    "instructions": {},
                    "target_player": 255,
                    "target_position": 0,
                }
                for _ in range(11)
            ],
            [
                {
                    "position": "GK",
                    "role": "门将",
                    "duty": "0",
                    "instructions": {},
                    "target_player": 255,
                    "target_position": 0,
                }
                for _ in range(11)
            ],
        ],
    }


def test_instruction_keys_and_extra_bits_are_normalized():
    raw = entry(
        tactic=tactic(instructions={"01": 5, "0": 0}, native_extra_team_bits="0007"),
    )
    normalized = normalize_away_pool({"entries": [raw]})["entries"][0]["tactic"]
    assert normalized["instructions"] == {"1": 5, "0": 0}
    assert normalized["native_extra_team_bits"] == "7"


def test_entry_roster_is_normalized_with_legacy_defaults():
    saved = roster()
    saved.pop("roster_size")
    normalized = normalize_away_pool({"entries": [entry(roster=saved)]})["entries"][0]["roster"]
    assert normalized == {
        "club_uid": 7,
        "club": "存档客队",
        "coach": "存档教练",
        "source": "real_ai",
        "roster_size": 12,
        "lineup": list(range(11)),
        "players": [roster_player(index) for index in range(12)],
    }
    assert normalize_away_pool({"entries": [entry(roster=roster())]})["entries"][0]["roster"]["roster_size"] == 12


def test_optional_native_source_plan_is_validated_and_copied():
    plan = {"value": {"team": 1}, "signature": "a" * 64}
    normalized = normalize_away_pool({"entries": [entry(tactic=tactic(native_source_plan=plan))]})
    assert normalized["entries"][0]["tactic"]["native_source_plan"] == plan
    with pytest.raises(ValueError, match="原生方案来源无效"):
        normalize_away_pool({"entries": [entry(tactic=tactic(native_source_plan={"value": 1, "signature": "a" * 64}))]})
    with pytest.raises(ValueError, match="原生方案签名无效"):
        normalize_away_pool(
            {"entries": [entry(tactic=tactic(native_source_plan={"value": {}, "signature": "Z" * 64}))]}
        )


def test_normalization_does_not_mutate_or_alias_input():
    raw = {"entries": [entry(roster=roster())], "uniform": {"enabled": True, "attribute_value": 10}}
    snapshot = copy.deepcopy(raw)
    value = normalize_away_pool(raw)
    assert raw == snapshot
    value["entries"][0]["tactic"]["phases"][0][0]["position"] = "XX"
    value["entries"][0]["roster"]["players"][0]["attributes"][0] = 20
    value["uniform"]["attribute_value"] = 20
    assert raw == snapshot
    assert normalize_away_pool(raw)["uniform"] == {"enabled": True, "attribute_value": 10}


def test_unknown_top_level_fields_are_ignored():
    value = normalize_away_pool({"entries": [entry()], "salt": "job-a", "mode": "random"})
    assert value["profile"] == PROFILE
    assert set(value) == {"profile", "enabled", "entries", "uniform", "rotation", "real"}


def test_pool_level_errors_keep_legacy_texts():
    with pytest.raises(ValueError, match="客队战术池格式无效"):
        normalize_away_pool(None)
    with pytest.raises(ValueError, match="客队战术池版本无效"):
        normalize_away_pool({"profile": "other"})
    with pytest.raises(ValueError, match="最多允许 128 套战术"):
        normalize_away_pool({"entries": [entry() for _ in range(MAX_ENTRIES + 1)]})
    with pytest.raises(ValueError, match="最多允许 128 套战术"):
        normalize_away_pool({"entries": (entry(),)})
    with pytest.raises(ValueError, match="客队战术池开关必须为布尔值"):
        normalize_away_pool({"enabled": 1})
    with pytest.raises(ValueError, match="请先导入客队战术"):
        normalize_away_pool({"enabled": True})
    assert normalize_away_pool({"enabled": True, "entries": [entry()]})["enabled"] is True


def test_entry_validation_errors_keep_legacy_texts():
    with pytest.raises(ValueError, match="第 1 套客队战术格式无效"):
        normalize_away_pool({"entries": ["无效"]})
    with pytest.raises(ValueError, match="第 2 套客队战术包含未知字段"):
        normalize_away_pool({"entries": [entry(), entry(extra=1)]})
    with pytest.raises(ValueError, match="名称须为1–80个可读字符"):
        normalize_away_pool({"entries": [entry(name=5)]})
    for name in ("", "   ", "长" * (MAX_NAME + 1)):
        with pytest.raises(ValueError, match="名称须为1–80个可读字符"):
            normalize_away_pool({"entries": [entry(name=name)]})
    for weight in (0, 1001, True, "1", 1.5):
        with pytest.raises(ValueError, match="权重必须为 1–1000 的整数"):
            normalize_away_pool({"entries": [entry(weight=weight)]})


def test_tactic_validation_errors_keep_legacy_texts():
    with pytest.raises(ValueError, match="第 1 套客队战术战术格式无效"):
        normalize_away_pool({"entries": [entry(tactic=None)]})
    with pytest.raises(ValueError, match="战术名称无效"):
        normalize_away_pool({"entries": [entry(tactic=tactic(tactic_name="长" * 121))]})
    with pytest.raises(ValueError, match="战术名称无效"):
        normalize_away_pool({"entries": [entry(tactic=tactic(tactic_name="a\nb"))]})
    for mentality in (0, 8, True, "3"):
        with pytest.raises(ValueError, match="比赛心态必须为 1–7 的整数"):
            normalize_away_pool({"entries": [entry(tactic=tactic(mentality=mentality))]})
    value = normalize_away_pool({"entries": [entry(tactic=tactic(tactic_name="", native_source_plan=None))]})
    assert value["entries"][0]["tactic"]["tactic_name"] == ""
    assert "native_source_plan" not in value["entries"][0]["tactic"]


def test_instruction_validation_errors_keep_legacy_texts():
    cases = (
        (None, "球队指令格式无效"),
        ({"x": 1}, "球队指令键必须为十进制数字"),
        ({"-1": 1}, "球队指令键必须为十进制数字"),
        ({"1": 2**32}, "球队指令必须为 0–4294967295 的整数"),
        ({"1": True}, "球队指令必须为 0–4294967295 的整数"),
    )
    for instructions, message in cases:
        with pytest.raises(ValueError, match=message):
            normalize_away_pool({"entries": [entry(tactic=tactic(instructions=instructions))]})


def test_extra_team_bits_validation_errors_keep_legacy_texts():
    for extra in (1, "abc", "1.0", str(2**128), "9" * 40, None):
        with pytest.raises(ValueError, match="附加原生战术选项无效"):
            normalize_away_pool({"entries": [entry(tactic=tactic(native_extra_team_bits=extra))]})
    raw = tactic()
    raw.pop("native_extra_team_bits")
    with pytest.raises(ValueError, match="附加原生战术选项无效"):
        normalize_away_pool({"entries": [entry(tactic=raw)]})


def test_phase_and_cell_validation_keeps_legacy_texts():
    with pytest.raises(ValueError, match="必须包含有球和无球两个阶段"):
        normalize_away_pool({"entries": [entry(tactic=tactic(phases=phases()[:1]))]})
    with pytest.raises(ValueError, match="每个阶段必须有11个位置"):
        normalize_away_pool(
            {"entries": [entry(tactic=tactic(phases=[phases()[0][:10], phases()[1]]))]}
        )
    with pytest.raises(ValueError, match="位置格式无效"):
        normalize_away_pool({"entries": [entry(tactic=tactic(phases=[[None] * 11, phases()[1]]))]})

    def broken_cell(overrides):
        rows = [cell() for _ in range(11)]
        rows[0].update(overrides)
        return [rows, phases()[1]]

    cases = (
        ({"position": ""}, "位置名称无效"),
        ({"position": "长" * 17}, "位置名称无效"),
        ({"role": ""}, "角色名称无效"),
        ({"role": "长" * 41}, "角色名称无效"),
        ({"duty": "x"}, "职责位无效"),
        ({"duty": 1}, "职责位无效"),
        ({"duty": "1" * 21}, "职责位无效"),
        ({"target_player": 256}, "盯防球员必须为 0–255 的整数"),
        ({"target_player": -1}, "盯防球员必须为 0–255 的整数"),
        ({"target_position": 2**64}, "盯防位置必须为 0–18446744073709551615 的整数"),
        ({"target_position": True}, "盯防位置必须为 0–18446744073709551615 的整数"),
        ({"instructions": {"x": 1}}, "个人指令键必须为十进制数字"),
        ({"instructions": None}, "个人指令格式无效"),
    )
    for overrides, message in cases:
        with pytest.raises(ValueError, match=message):
            normalize_away_pool({"entries": [entry(tactic=tactic(phases=broken_cell(overrides)))]})


def test_roster_shape_errors_keep_legacy_texts():
    with pytest.raises(ValueError, match="第 1 套客队战术存档名单格式无效"):
        normalize_away_pool({"entries": [entry(roster=[])]})
    with pytest.raises(ValueError, match="存档名单格式无效"):
        normalize_away_pool({"entries": [entry(roster=roster(extra=1))]})
    with pytest.raises(ValueError, match="须包含 11–26 名球员"):
        normalize_away_pool({"entries": [entry(roster=roster(count=10))]})
    with pytest.raises(ValueError, match="须包含 11–26 名球员"):
        normalize_away_pool({"entries": [entry(roster=roster(count=MAX_ROSTER + 1))]})
    with pytest.raises(ValueError, match="第 1 套客队战术存档名单第 1 名球员格式无效"):
        normalize_away_pool({"entries": [entry(roster=roster(players=[None] * 11))]})


@pytest.mark.parametrize("count", (24, 26))
def test_roster_sizes_up_to_max_are_accepted(count):
    value = normalize_away_pool({"entries": [entry(roster=roster(count))]})
    assert value["entries"][0]["roster"]["roster_size"] == count


def test_roster_player_errors_keep_legacy_texts():
    def broken(overrides):
        saved = roster()
        saved["players"][0].update(overrides)
        return saved

    cases = (
        ({"name": ""}, "球员名称须为1–48个可读字符"),
        ({"name": "长" * 49}, "球员名称须为1–48个可读字符"),
        ({"attributes": [10] * 68}, "球员属性不完整"),
        ({"attributes": [21] + [10] * 14 + [50] * 54}, "属性必须为 0–20 的整数"),
        ({"attributes": [10] * 15 + [0] * 54}, "属性必须为 1–100 的整数"),
        ({"native_profile": "x"}, "球员扩展输入格式无效"),
        ({"source_uid": 2**32}, "源球员UID必须为 0–4294967295 的整数"),
        ({"source_uid": -1}, "源球员UID必须为 0–4294967295 的整数"),
    )
    for overrides, message in cases:
        with pytest.raises(ValueError, match=message):
            normalize_away_pool({"entries": [entry(roster=broken(overrides))]})


def test_roster_aggregate_errors_keep_legacy_texts():
    saved = roster()
    saved["roster_size"] = 13
    with pytest.raises(ValueError, match="存档名单人数必须为 11–12 的整数"):
        normalize_away_pool({"entries": [entry(roster=saved)]})

    saved = roster()
    saved["roster_size"] = 11
    with pytest.raises(ValueError, match="存档名单人数与球员数量不一致"):
        normalize_away_pool({"entries": [entry(roster=saved)]})

    saved = roster()
    saved["players"][1]["source_uid"] = 1000
    with pytest.raises(ValueError, match="存档名单包含重复球员"):
        normalize_away_pool({"entries": [entry(roster=saved)]})

    for lineup in (list(range(10)), [0] * 11):
        saved = roster()
        saved["lineup"] = lineup
        with pytest.raises(ValueError, match="存档名单首发须为11名不同球员"):
            normalize_away_pool({"entries": [entry(roster=saved)]})

    saved = roster()
    saved["lineup"] = list(range(10)) + [12]
    with pytest.raises(ValueError, match="存档名单首发必须为 0–11 的整数"):
        normalize_away_pool({"entries": [entry(roster=saved)]})

    saved = roster()
    saved["source"] = "manual"
    with pytest.raises(ValueError, match="存档名单来源无效"):
        normalize_away_pool({"entries": [entry(roster=saved)]})

    saved = roster()
    saved["club"] = "长" * 41
    with pytest.raises(ValueError, match="存档球队名称须为不超过 40 个可读字符"):
        normalize_away_pool({"entries": [entry(roster=saved)]})

    saved = roster()
    saved["coach"] = "长" * 61
    with pytest.raises(ValueError, match="存档主教练名称须为不超过 60 个可读字符"):
        normalize_away_pool({"entries": [entry(roster=saved)]})

    saved = roster()
    saved["club_uid"] = -1
    with pytest.raises(ValueError, match="存档球队编号必须为 0–4294967295 的整数"):
        normalize_away_pool({"entries": [entry(roster=saved)]})

    saved = roster()
    saved["club"] = " 存档客队 "
    assert normalize_away_pool({"entries": [entry(roster=saved)]})["entries"][0]["roster"]["club"] == "存档客队"


def test_real_mode_requires_roster_on_every_entry():
    with pytest.raises(ValueError, match="缺少：战术一、战术二"):
        normalize_away_pool({"real": {"enabled": True}, "entries": [entry(name="战术一"), entry(name="战术二")]})
    many = [entry(name=f"战术{index}") for index in range(1, 5)]
    with pytest.raises(ValueError, match="缺少：战术1、战术2、战术3等"):
        normalize_away_pool({"real": {"enabled": True}, "entries": many})
    value = normalize_away_pool({"real": {"enabled": True}, "entries": [entry(roster=roster())]})
    assert value["real"]["enabled"] is True


def test_real_mode_rejects_oversized_roster_payload():
    saved = roster()
    for player in saved["players"]:
        player["native_profile"] = {"blob": "x" * 130_000}
    with pytest.raises(ValueError, match="超过 1.50 MB 上限"):
        normalize_away_pool({"entries": [entry(roster=saved)]})


def test_rotation_settings_validate_and_enforce_match_cap():
    assert normalize_away_pool({})["rotation"] == {"enabled": False, "rounds": 1}
    assert normalize_away_pool({"rotation": {"enabled": True, "rounds": 2}})["rotation"] == {
        "enabled": True,
        "rounds": 2,
    }
    with pytest.raises(ValueError, match="轮战模式设置格式无效"):
        normalize_away_pool({"rotation": []})
    with pytest.raises(ValueError, match="轮战模式设置包含未知字段"):
        normalize_away_pool({"rotation": {"enabled": False, "rounds": 1, "extra": 1}})
    for rounds in (0, 1001, True, "1"):
        with pytest.raises(ValueError, match="轮战每套轮数必须为 1–1000 的整数"):
            normalize_away_pool({"rotation": {"enabled": False, "rounds": rounds}})
    entries = [entry(name=f"战术{index}") for index in range(11)]
    with pytest.raises(ValueError, match="轮战每方案最多 10000 场"):
        normalize_away_pool({"entries": entries, "rotation": {"enabled": True, "rounds": 1000}})


def test_uniform_settings_validate_and_default():
    assert normalize_away_pool({})["uniform"] == {"enabled": True, "attribute_value": DEFAULT_ATTRIBUTE_VALUE}
    assert normalize_away_pool({"uniform": {"enabled": False}})["uniform"] == {
        "enabled": False,
        "attribute_value": DEFAULT_ATTRIBUTE_VALUE,
    }
    with pytest.raises(ValueError, match="统一属性设置格式无效"):
        normalize_away_pool({"uniform": True})
    with pytest.raises(ValueError, match="统一属性开关必须为布尔值"):
        normalize_away_pool({"uniform": {"enabled": 1}})
    for value in (0, 21, True, "15"):
        with pytest.raises(ValueError, match="统一属性值必须为 1–20 的整数"):
            normalize_away_pool({"uniform": {"attribute_value": value}})


def test_real_settings_validate():
    assert normalize_away_pool({})["real"] == {"enabled": False}
    with pytest.raises(ValueError, match="真实名单设置格式无效"):
        normalize_away_pool({"real": []})
    with pytest.raises(ValueError, match="真实名单设置包含未知字段"):
        normalize_away_pool({"real": {"enabled": False, "extra": 1}})
    with pytest.raises(ValueError, match="真实名单开关必须为布尔值"):
        normalize_away_pool({"real": {"enabled": "yes"}})
