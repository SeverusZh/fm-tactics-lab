"""原生战术解析结果到场景文档的映射测试。"""

from __future__ import annotations

import copy
import dataclasses
from pathlib import Path

import pytest

from fm27lab.adapters.engine_native import scenario_codec
from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets
from fm27lab.adapters.engine_native.tactic_file import TacticCell, TacticPlan
from fm27lab.application.tactic_import import (
    GROUP_CONFLICT_ERROR,
    MAPPING_ERROR,
    PERSONAL_CONFLICT_ERROR,
    PERSONAL_UNKNOWN_ERROR,
    UNMAPPED_ERROR,
    build_scenario,
)
from fm27lab.domain.scenario import normalize_scenario
from fm27lab.domain.tactics import Catalog, validate_phases
from fm27lab.tests.test_scenario_assets import ROLE_FLAGS, load_fixture_assets

NAME = "主场战术"
DUTY_BIT = 1 << 21


def _plan_cell(assets: ScenarioAssets, cell: dict) -> TacticCell:
    pi_flags = 0
    for value in cell["instructions"].values():
        if value:
            pi_flags |= 1 << int(value)
    return TacticCell(
        position=assets.positions[cell["position"]]["mask"],
        role_flags=int(assets.roles[cell["role"]]["flags"]) | int(cell["duty"]) | DUTY_BIT,
        pi_flags=pi_flags,
        target_player=cell["target_player"],
        target_position=cell["target_position"],
    )


def plan_from_defaults(assets: ScenarioAssets, **overrides) -> TacticPlan:
    base = scenario_codec.defaults(assets)["teams"][0]
    creator = bytes.fromhex(assets.snapshot["teams"][0]["creator_hex"])[:16]
    mapping = list(overrides.pop("mapping", assets.oop_map[0]))
    phase_zero = [_plan_cell(assets, cell) for cell in base["phases"][0]]
    phase_one: list[TacticCell | None] = [None] * 11
    for index, cell in enumerate(base["phases"][1]):
        slot = index if mapping[index] == 255 else mapping[index]
        phase_one[slot] = _plan_cell(assets, cell)
    plan = TacticPlan(
        name=NAME,
        mentality=base["mentality"],
        team_bits=int.from_bytes(creator, "little"),
        mapping=tuple(mapping),
        phases=(tuple(phase_zero), tuple(phase_one)),
    )
    return dataclasses.replace(plan, **overrides) if overrides else plan


def replace_cell(plan: TacticPlan, phase: int, slot: int, **changes) -> TacticPlan:
    phases = [list(cells) for cells in plan.phases]
    phases[phase][slot] = dataclasses.replace(phases[phase][slot], **changes)
    return dataclasses.replace(plan, phases=tuple(tuple(cells) for cells in phases))


def native_plan_events(plan: TacticPlan, *, name_hex: str | None = None) -> list[dict]:
    return [
        {
            "event": "native_fmf_decoded",
            "accepted": True,
            "bytes": 8,
            "name_utf8_hex": plan.name.encode("utf-8").hex() if name_hex is None else name_hex,
            "setpiece_type": -1,
            "stream_revision": 60,
        },
        {
            "event": "native_tactic_file_parsed",
            "accepted": True,
            "stream_error": 0,
            "consumed": 8,
            "size": 8,
            "mentality": plan.mentality,
            "team_bits": plan.team_bits.to_bytes(16, "little").hex(),
            "mapping": list(plan.mapping),
            "phases": [
                [
                    {
                        "position": cell.position,
                        "role_flags": str(cell.role_flags),
                        "pi_flags": str(cell.pi_flags),
                        "target_player": cell.target_player,
                        "target_position": cell.target_position,
                    }
                    for cell in phase
                ]
                for phase in plan.phases
            ],
        },
    ]


def without_source_uid(team: dict) -> dict:
    stripped = copy.deepcopy(team)
    for player in stripped["players"]:
        player.pop("source_uid", None)
    return stripped


def fixture_duty_phases(phases: list[list[dict]]) -> list[list[dict]]:
    return [[{**cell, "duty": str(DUTY_BIT)} for cell in phase] for phase in phases]


def plan_duty(assets: ScenarioAssets, plan: TacticPlan, phase: int, index: int) -> str:
    slot = plan.mapping[index] if phase else index
    return str(plan.phases[phase][slot].role_flags & ~assets.role_mask)


def test_build_scenario_maps_native_plan_onto_home_team(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    base = scenario_codec.defaults(assets)
    plan = plan_from_defaults(assets)
    scenario = build_scenario(assets, plan)
    assert scenario["schema"] == scenario_codec.SCHEMA
    assert scenario["fixture"] == scenario_codec.FIXTURE
    home, away = scenario["teams"]
    assert home["mentality"] == base["teams"][0]["mentality"] == 4
    assert home["native_extra_team_bits"] == "0"
    assert home["instructions"] == base["teams"][0]["instructions"]
    assert home["phases"] == fixture_duty_phases(base["teams"][0]["phases"])
    for phase in range(2):
        for index in range(11):
            assert home["phases"][phase][index]["duty"] == plan_duty(assets, plan, phase, index)
    assert home["tactic_name"] == NAME
    assert away["tactic_name"] == ""
    validate_scenario = scenario_codec.validate_scenario
    validate_scenario(assets, scenario)


def test_build_scenario_keeps_away_team_defaults(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    base = scenario_codec.defaults(assets)
    scenario = build_scenario(assets, plan_from_defaults(assets))
    assert without_source_uid(scenario["teams"][1]) == without_source_uid(base["teams"][1])


def test_build_scenario_adds_source_uids_to_both_squads(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    scenario = build_scenario(assets, plan_from_defaults(assets))
    for squad in scenario["teams"]:
        assert [player["source_uid"] for player in squad["players"]] == [
            player["native_id"] for player in squad["players"]
        ]
        assert [player["source_uid"] for player in squad["players"]] == [
            100 + index for index in range(23)
        ]


def test_build_scenario_is_domain_normalizable(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    scenario = build_scenario(assets, plan_from_defaults(assets))
    normalized = normalize_scenario(scenario)
    assert len(normalized["teams"]) == 2
    assert normalized["teams"][0]["players"]


def test_build_scenario_derives_team_instructions_and_extra_bits(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    plan = plan_from_defaults(assets, team_bits=(1 << 4) | (1 << 3))
    home = build_scenario(assets, plan)["teams"][0]
    assert home["instructions"] == {"1": 1, "2": 1, "4": 0}
    assert home["native_extra_team_bits"] == "0"
    high = 1 << 40
    plan = plan_from_defaults(assets, team_bits=(1 << 4) | high)
    home = build_scenario(assets, plan)["teams"][0]
    assert home["native_extra_team_bits"] == str(high)


def test_build_scenario_rejects_conflicting_team_instructions(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    group = dict(assets.groups[1])
    group["options"] = [{"id": 0, "native_bit": 3}, {"id": 1, "native_bit": 4}]
    groups = {**assets.groups, 1: group}
    conflicted = dataclasses.replace(assets, groups=groups)
    plan = plan_from_defaults(assets, team_bits=(1 << 3) | (1 << 4))
    with pytest.raises(ValueError, match=GROUP_CONFLICT_ERROR):
        build_scenario(conflicted, plan)


def test_build_scenario_rejects_invalid_mapping(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    with pytest.raises(ValueError, match=MAPPING_ERROR):
        build_scenario(assets, plan_from_defaults(assets, mapping=(0,) * 11))


def test_build_scenario_rejects_unmapped_position(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    plan = replace_cell(plan_from_defaults(assets), 0, 0, position=0xFFFF)
    with pytest.raises(ValueError, match=UNMAPPED_ERROR):
        build_scenario(assets, plan)


def test_build_scenario_rejects_unmapped_role(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    plan = replace_cell(plan_from_defaults(assets), 0, 0, role_flags=0)
    with pytest.raises(ValueError, match=UNMAPPED_ERROR):
        build_scenario(assets, plan)


def test_build_scenario_rejects_unknown_personal_instruction(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    plan = replace_cell(plan_from_defaults(assets), 0, 0, pi_flags=1 << 40)
    with pytest.raises(ValueError, match=PERSONAL_UNKNOWN_ERROR):
        build_scenario(assets, plan)


def test_build_scenario_rejects_conflicting_personal_instructions(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    pis = {0: {"id": 0, "options": [{"id": 1}, {"id": 2}]}}
    conflicted = dataclasses.replace(assets, pis=pis)
    plan = replace_cell(plan_from_defaults(assets), 0, 0, pi_flags=(1 << 1) | (1 << 2))
    with pytest.raises(ValueError, match=PERSONAL_CONFLICT_ERROR):
        build_scenario(conflicted, plan)


def test_build_scenario_maps_role_duty_bits(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    duty_bit = 1 << 21
    flags = int(assets.roles["GK_ROLE_0"]["flags"]) | duty_bit
    plan = replace_cell(plan_from_defaults(assets), 0, 0, role_flags=flags)
    cell = build_scenario(assets, plan)["teams"][0]["phases"][0][0]
    assert cell["duty"] == str(duty_bit)
    assert cell["role"] == "GK_ROLE_0"


def _role_id(assets: ScenarioAssets, position_id: str, phase: int) -> str:
    mask = assets.positions[position_id]["mask"]
    kind = "GK" if mask & 1 else "FIELD"
    flags = ROLE_FLAGS[phase][kind]
    return next(
        role["id"]
        for role in assets.roles.values()
        if role["phase"] == phase and int(role["flags"]) == flags
    )


def catalog_payload(assets: ScenarioAssets) -> dict:
    payload = copy.deepcopy(assets.catalog)
    payload["duties"] = list(scenario_codec.DUTIES)
    payload["role_eligibility"] = {
        position_id: [
            [_role_id(assets, position_id, 0)],
            [_role_id(assets, position_id, 1)],
        ]
        for position_id in assets.positions
    }
    return payload


def test_build_scenario_passes_catalog_phase_validation(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    scenario = build_scenario(assets, plan_from_defaults(assets))
    catalog = Catalog.from_mapping(catalog_payload(assets))
    for team in scenario["teams"]:
        validate_phases(team["phases"], catalog)
    broken = copy.deepcopy(scenario)
    broken["teams"][0]["phases"][0][0]["duty"] = "1"
    with pytest.raises(ValueError, match="战术职责无效"):
        validate_phases(broken["teams"][0]["phases"], catalog)


def test_build_scenario_honours_tactic_name(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    plan = plan_from_defaults(assets)
    assert build_scenario(assets, plan)["teams"][0]["tactic_name"] == NAME
    assert build_scenario(assets, plan, tactic_name="自定名称")["teams"][0]["tactic_name"] == "自定名称"
    long_name = build_scenario(assets, plan, tactic_name="长" * 200)["teams"][0]["tactic_name"]
    assert long_name == "长" * 120


def _group_with_options(
    assets: ScenarioAssets, group_id: int, options: list[dict]
) -> ScenarioAssets:
    group = {**assets.groups[group_id], "options": options}
    return dataclasses.replace(assets, groups={**assets.groups, group_id: group})


def test_build_scenario_treats_mapping_255_as_identity_slot(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    base = scenario_codec.defaults(assets)["teams"][0]
    identity = build_scenario(assets, plan_from_defaults(assets, mapping=tuple(range(11))))
    unmapped = build_scenario(assets, plan_from_defaults(assets, mapping=(255, *range(1, 11))))
    assert unmapped == identity
    assert identity["teams"][0]["phases"] == fixture_duty_phases(base["phases"])


def test_build_scenario_falls_back_to_first_option_without_group_default(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    without_default = _group_with_options(
        assets,
        4,
        [{"id": 3, "label": "甲", "native_bit": 9}, {"id": 4, "label": "乙", "native_bit": 10}],
    )
    home = build_scenario(without_default, plan_from_defaults(assets))["teams"][0]
    assert home["instructions"]["4"] == 3


def test_build_scenario_prefers_group_option_without_native_bit(tmp_path: Path):
    assets = load_fixture_assets(tmp_path)
    reordered = _group_with_options(
        assets,
        4,
        [{"id": 9, "label": "带位", "native_bit": 9}, {"id": 6, "label": "默认"}],
    )
    home = build_scenario(reordered, plan_from_defaults(assets))["teams"][0]
    assert home["instructions"]["4"] == 6
