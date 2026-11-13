from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from fm27lab.interfaces.http.common import ErrorEnvelope, _query_integer, require_token


class DraftCreateInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    scenario: dict[str, Any]
    source: dict[str, Any] | None = None


class DraftUpdateInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    scenario: dict[str, Any] | None = None
    source: dict[str, Any] | None = None


class DraftSummary(BaseModel):
    id: str
    name: str
    source: dict[str, Any]
    created_at: str
    updated_at: str


class DraftOutput(DraftSummary):
    scenario: dict[str, Any]


class DraftListOutput(BaseModel):
    items: list[DraftSummary]
    total: int
    next_offset: int | None


def register(app: FastAPI) -> None:
    @app.get(
        "/api/drafts",
        response_model=DraftListOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def list_drafts(
        limit: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": 128, "default": 128}),
        ] = "128",
        offset: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 0, "maximum": 2**31 - 1, "default": 0}),
        ] = "0",
        _: None = Depends(require_token),
    ):
        try:
            return app.state.drafts.list(
                limit=_query_integer(limit, "limit", 1, 128),
                offset=_query_integer(offset, "offset", 0, 2**31 - 1),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error

    @app.post(
        "/api/drafts",
        status_code=201,
        response_model=DraftOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def create_draft(body: DraftCreateInput, _: None = Depends(require_token)):
        try:
            return app.state.drafts.create(body.name, body.scenario, body.source)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error

    @app.get(
        "/api/drafts/{draft_id}",
        response_model=DraftOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def get_draft(draft_id: str, _: None = Depends(require_token)):
        try:
            value = app.state.drafts.get(draft_id)
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

    @app.patch(
        "/api/drafts/{draft_id}",
        response_model=DraftOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def update_draft(draft_id: str, body: DraftUpdateInput, _: None = Depends(require_token)):
        try:
            value = app.state.drafts.update(draft_id, **body.model_dump(exclude_unset=True))
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

    @app.delete(
        "/api/drafts/{draft_id}",
        status_code=204,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def delete_draft(draft_id: str, _: None = Depends(require_token)):
        try:
            deleted = app.state.drafts.delete(draft_id)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "draft not found", "retriable": False},
            )
        return Response(status_code=204)
