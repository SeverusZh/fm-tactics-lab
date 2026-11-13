from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from fm27lab.interfaces.http.common import ID_PATTERN, ErrorEnvelope, _query_integer, require_token


class PoolEntryInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    weight: int = Field(default=1, ge=1, le=1000)
    tactic: dict[str, Any]
    roster: dict[str, Any] | None = None
    id: str | None = Field(default=None, pattern=ID_PATTERN)


class PoolEntryOutput(BaseModel):
    id: str
    name: str
    weight: int
    tactic: dict[str, Any]
    roster: dict[str, Any] | None
    created_at: str


class PoolListOutput(BaseModel):
    items: list[PoolEntryOutput]
    total: int
    next_offset: int | None


def register(app: FastAPI) -> None:
    @app.get(
        "/api/pools",
        response_model=PoolListOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def list_pools(
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
            return app.state.pools.list(
                limit=_query_integer(limit, "limit", 1, 128),
                offset=_query_integer(offset, "offset", 0, 2**31 - 1),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error

    @app.post(
        "/api/pools",
        status_code=201,
        response_model=PoolEntryOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def create_pool(body: PoolEntryInput, _: None = Depends(require_token)):
        try:
            return app.state.pools.create(body.model_dump())
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "conflict", "message": "pool entry already exists", "retriable": False},
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error

    @app.get(
        "/api/pools/{entry_id}",
        response_model=PoolEntryOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def get_pool(entry_id: str, _: None = Depends(require_token)):
        try:
            value = app.state.pools.get(entry_id)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error
        if value is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "pool entry not found", "retriable": False},
            )
        return value

    @app.delete(
        "/api/pools/{entry_id}",
        status_code=204,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def delete_pool(entry_id: str, _: None = Depends(require_token)):
        try:
            deleted = app.state.pools.delete(entry_id)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "pool entry not found", "retriable": False},
            )
        return Response(status_code=204)
