"""草稿属性批量编辑 HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from fm27lab.interfaces.http.common import ErrorEnvelope, require_token
from fm27lab.interfaces.http.routes.drafts import DraftSummary


class DraftAttributeInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    side: str
    scope: str
    player_index: int | None = None
    operation: str
    params: dict[str, Any]


class DraftAttributeOutput(BaseModel):
    draft: DraftSummary
    snapshot: dict[str, Any] | None
    changed_players: int


def register(app: FastAPI) -> None:
    @app.post(
        "/api/drafts/{draft_id}/attributes",
        response_model=DraftAttributeOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def apply_draft_attributes(draft_id: str, body: DraftAttributeInput, _: None = Depends(require_token)):
        try:
            value = app.state.draft_attributes.apply(
                draft_id,
                side=body.side,
                scope=body.scope,
                player_index=body.player_index,
                operation=body.operation,
                params=body.params,
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
