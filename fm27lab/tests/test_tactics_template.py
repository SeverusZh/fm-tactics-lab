"""Tests for the native-asset draft template builder."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets, load_scenario_assets
from fm27lab.application.tactics_template import TEMPLATE_NAME, build_template
from fm27lab.domain.tactics import Catalog, validate_phases
from fm27lab.tests.test_scenario_assets import POSITION_ORDER, make_catalog, write_engine_root


def write_catalog_with_rules(root: Path) -> None:
    catalog = make_catalog()
    catalog["duties"] = ["0"]
    catalog["role_eligibility"] = {
        position: [
            ["GK_ROLE_0"] if position == "GK" else ["FIELD_ROLE_0"],
            ["GK_ROLE_1"] if position == "GK" else ["FIELD_ROLE_1"],
        ]
        for position in POSITION_ORDER
    }
    path = root / "fm27_native" / "catalog.json"
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def assets(tmp_path: Path) -> ScenarioAssets:
    root = write_engine_root(tmp_path)
    write_catalog_with_rules(root)
    return load_scenario_assets(root)


def test_template_has_two_full_rosters(assets: ScenarioAssets):
    template = build_template(assets)
    assert template["schema"] == 3
    assert len(template["teams"]) == 2
    for team in template["teams"]:
        assert team["roster_size"] == 23
        assert len(team["players"]) == 23
        assert team["lineup"] == list(range(11))
        assert team["tactic_name"] == TEMPLATE_NAME
        assert "phase_plans" not in team


def test_template_players_have_unique_source_uids(assets: ScenarioAssets):
    template = build_template(assets)
    for team in template["teams"]:
        uids = [player["source_uid"] for player in team["players"]]
        assert all(uid is not None and uid != "" for uid in uids)
        assert len(set(uids)) == 23


def test_template_phases_pass_catalog_validation(assets: ScenarioAssets):
    template = build_template(assets)
    catalog = Catalog.from_mapping(assets.catalog)
    for team in template["teams"]:
        assert len(team["phases"]) == 2
        validate_phases(team["phases"], catalog)
        duties = [cell["duty"] for phase in team["phases"] for cell in phase]
        assert all(duty.isascii() and duty.isdigit() for duty in duties)
        assert team["phases"][1][0]["role"] == "GK_ROLE_1"


def test_template_generation_failure_is_reported(tmp_path: Path):
    assets = load_scenario_assets(write_engine_root(tmp_path))
    empty_snapshot = {
        "teams": [{**team, "players": [], "count": 0} for team in assets.snapshot["teams"]]
    }
    broken = replace(assets, snapshot=empty_snapshot)
    with pytest.raises(ValueError, match="^战术模板生成失败："):
        build_template(broken)
