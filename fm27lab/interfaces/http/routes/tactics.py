"""战术模板 HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets, load_scenario_assets
from fm27lab.application.tactics_template import build_template
from fm27lab.interfaces.http.common import ErrorEnvelope, error_body, require_token

ENGINE_UNAVAILABLE_CODE = "engine_unavailable"
ENGINE_UNAVAILABLE_MESSAGE = "引擎资源未配置，无法生成战术模板；请在设置页配置引擎目录与游戏目录"
ASSETS_STATE_ATTRIBUTE = "tactics_template_assets"


class TacticsTemplateOutput(BaseModel):
    scenario: dict[str, Any]


def load_assets(app: FastAPI) -> ScenarioAssets | None:
    cached = getattr(app.state, ASSETS_STATE_ATTRIBUTE, None)
    if cached is not None:
        return cached
    engine_root = app.state.settings.engine_root
    if engine_root is None:
        return None
    try:
        assets = load_scenario_assets(engine_root)
    except (ValueError, OSError):
        return None
    setattr(app.state, ASSETS_STATE_ATTRIBUTE, assets)
    return assets


def unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=error_body(ENGINE_UNAVAILABLE_CODE, ENGINE_UNAVAILABLE_MESSAGE, 503),
    )


def register(app: FastAPI) -> None:
    @app.get(
        "/api/tactics/template",
        response_model=TacticsTemplateOutput,
        responses={
            401: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope, "description": "引擎资源不可用"},
        },
    )
    def tactics_template(_: None = Depends(require_token)) -> TacticsTemplateOutput | JSONResponse:
        assets = load_assets(app)
        if assets is None:
            return unavailable()
        try:
            scenario = build_template(assets)
        except ValueError:
            return unavailable()
        return TacticsTemplateOutput(scenario=scenario)
