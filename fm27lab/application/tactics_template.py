"""Generate a validated draft template from native engine assets."""

from __future__ import annotations

import copy
from typing import Any

from fm27lab.adapters.engine_native import scenario_codec
from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets
from fm27lab.domain.scenario import normalize_scenario

TEMPLATE_NAME = "新战术"
UID_BASE = 100


def build_template(assets: ScenarioAssets) -> dict[str, Any]:
    scenario = copy.deepcopy(scenario_codec.defaults(assets))
    for side, team in enumerate(scenario["teams"]):
        team["tactic_name"] = TEMPLATE_NAME
        for index, player in enumerate(team["players"]):
            player["source_uid"] = (side + 1) * UID_BASE + index
    try:
        return normalize_scenario(scenario)
    except ValueError as error:
        raise ValueError(f"战术模板生成失败：{error}") from error
