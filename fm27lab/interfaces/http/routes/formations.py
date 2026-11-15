"""阵型模板 HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from fm27lab.interfaces.http.common import ErrorEnvelope, require_token


class FormationCellOutput(BaseModel):
    position: str
    role: str
    x: float
    y: float


class FormationOutput(BaseModel):
    id: str
    name: str
    phases: list[list[FormationCellOutput]]


class FormationListOutput(BaseModel):
    formations: list[FormationOutput]
    editing: dict[str, Any] | None


class FormationApplyInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    formation_id: str = Field(min_length=1, max_length=32)
    overwrite: bool = False
    scenario: dict[str, Any] | None = None


class FormationApplyOutput(BaseModel):
    formation_id: str
    scenario: dict[str, Any]
    notes: list[str]


def register(app: FastAPI) -> None:
    @app.get(
        "/api/formations",
        response_model=FormationListOutput,
        responses={401: {"model": ErrorEnvelope}},
    )
    def list_formations(_: None = Depends(require_token)):
        return app.state.formations.list()

    @app.post(
        "/api/drafts/{draft_id}/formation",
        response_model=FormationApplyOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def apply_formation(draft_id: str, body: FormationApplyInput, _: None = Depends(require_token)):
        try:
            value = app.state.formations.apply(
                draft_id,
                body.formation_id,
                overwrite=body.overwrite,
                scenario=body.scenario,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error
        if value is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "draft not found", "retriable": False},
            )
        return value
