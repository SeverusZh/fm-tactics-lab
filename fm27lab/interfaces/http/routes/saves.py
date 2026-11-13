from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict

from fm27lab.application.saves import SavesService
from fm27lab.interfaces.http.common import ErrorEnvelope, _query_integer, require_token

CLUB_IDENTIFIER = re.compile(r"^[0-9]+$")
CONFLICT_MESSAGES = frozenset({"存档已存在", "存档内容重复"})


class SaveCreateInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    source_path: str
    source_sha256: str
    status: str = "pending"
    stage: str | None = None
    metadata: dict[str, Any] | None = None


class SaveUpdateInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    status: str | None = None
    stage: str | None = None
    metadata: dict[str, Any] | None = None


class SaveImportInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    leagues: dict[str, dict[str, Any]]
    clubs: dict[str, dict[str, Any]]
    stage: str | None = None


class SaveOutput(BaseModel):
    id: str
    source_path: str
    source_sha256: str
    status: str
    stage: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class SaveListOutput(BaseModel):
    items: list[SaveOutput]
    total: int
    next_offset: int | None


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": "存档不存在", "retriable": False},
    )


def _club_identifiers(clubs: dict[str, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    converted: dict[int, dict[str, Any]] = {}
    for key, payload in clubs.items():
        if CLUB_IDENTIFIER.fullmatch(key) is None:
            raise ValueError("俱乐部标识无效")
        converted[int(key)] = payload
    return converted


def register(app: FastAPI) -> None:
    def load_save(save_id: str) -> dict[str, Any]:
        try:
            value = app.state.saves.get(save_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if value is None:
            raise _not_found()
        return value

    @app.get(
        "/api/saves",
        response_model=SaveListOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def list_saves(
        status: Annotated[str | None, Query()] = None,
        limit: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": 256, "default": 50}),
        ] = "50",
        offset: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 0, "maximum": 2**31 - 1, "default": 0}),
        ] = "0",
        _: None = Depends(require_token),
    ):
        try:
            return app.state.saves.list(
                status=status,
                limit=_query_integer(limit, "limit", 1, 256),
                offset=_query_integer(offset, "offset", 0, 2**31 - 1),
            )
        except ValueError as error:
            raise _validation_error(error) from error

    @app.post(
        "/api/saves",
        status_code=201,
        response_model=SaveOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def create_save(body: SaveCreateInput, _: None = Depends(require_token)):
        try:
            return app.state.saves.create(
                body.source_path,
                body.source_sha256,
                status=body.status,
                stage=body.stage,
                metadata=body.metadata,
            )
        except ValueError as error:
            if str(error) in CONFLICT_MESSAGES:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "conflict", "message": str(error), "retriable": False},
                ) from error
            raise _validation_error(error) from error

    @app.get(
        "/api/saves/{save_id}",
        response_model=SaveOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def get_save(save_id: str, _: None = Depends(require_token)):
        return load_save(save_id)

    @app.patch(
        "/api/saves/{save_id}",
        response_model=SaveOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def update_save(save_id: str, body: SaveUpdateInput, _: None = Depends(require_token)):
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "validation_failed",
                    "message": "存档更新至少需要一项字段",
                    "retriable": False,
                },
            )
        if "status" in changes:
            status = changes["status"]
            if not isinstance(status, str) or status not in SavesService.TRANSITIONS:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "validation_failed", "message": "存档状态无效", "retriable": False},
                )
        current = load_save(save_id)
        if "status" in changes and changes["status"] not in SavesService.TRANSITIONS[current["status"]]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "invalid_transition",
                    "message": "存档状态不允许该流转",
                    "retriable": False,
                },
            )
        try:
            value = app.state.saves.update(save_id, changes)
        except ValueError as error:
            raise _validation_error(error) from error
        if value is None:
            raise _not_found()
        return value

    @app.delete(
        "/api/saves/{save_id}",
        status_code=204,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def delete_save(save_id: str, _: None = Depends(require_token)):
        try:
            deleted = app.state.saves.delete(save_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if not deleted:
            raise _not_found()
        return Response(status_code=204)

    @app.post(
        "/api/saves/{save_id}/import",
        response_model=SaveOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def import_save(save_id: str, body: SaveImportInput, _: None = Depends(require_token)):
        try:
            clubs = _club_identifiers(body.clubs)
        except ValueError as error:
            raise _validation_error(error) from error
        load_save(save_id)
        try:
            return app.state.saves.import_payload(save_id, body.leagues, clubs, stage=body.stage)
        except ValueError as error:
            if str(error) == "存档不存在":
                raise _not_found() from error
            raise _validation_error(error) from error
