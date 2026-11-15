"""存档导入、名单读取与阵容同步 HTTP 路由。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from fm27lab.interfaces.http.common import ErrorEnvelope, _query_integer, require_token
from fm27lab.interfaces.http.routes.drafts import DraftSummary

CONFLICT_MESSAGES = frozenset({"存档内容重复"})
MAX_CLUB_UID = 2**31 - 1


class SaveFileImportInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    source_path: str
    replace: bool = False


class ImportedClubOutput(BaseModel):
    club_uid: int
    club_name: str | None
    players: int


class SaveFileImportOutput(BaseModel):
    save_id: str
    status: str
    managed_clubs: list[ImportedClubOutput]
    clubs: int


class SquadOutput(BaseModel):
    save_id: str
    club_uid: int
    club_name: str | None
    players: list[dict[str, Any]]
    selection: dict[str, Any] | None


class RosterApplyInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    save_id: str
    club_uid: int
    side: str
    scope: str


class RosterAppliedOutput(BaseModel):
    starters: int
    substitutes: int


class RosterApplyOutput(BaseModel):
    draft: DraftSummary
    applied: RosterAppliedOutput


class RosterUndoOutput(BaseModel):
    draft: DraftSummary


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": message, "retriable": False},
    )


def register(app: FastAPI) -> None:
    @app.post(
        "/api/saves/import",
        status_code=201,
        response_model=SaveFileImportOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def import_save_file(body: SaveFileImportInput, _: None = Depends(require_token)):
        try:
            return app.state.save_import.import_save(body.source_path, replace=body.replace)
        except ValueError as error:
            if str(error) in CONFLICT_MESSAGES:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "conflict", "message": str(error), "retriable": False},
                ) from error
            raise _validation_error(error) from error

    @app.get(
        "/api/saves/{save_id}/squad",
        response_model=SquadOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def read_save_squad(
        save_id: str,
        club_uid: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": MAX_CLUB_UID}),
        ],
        _: None = Depends(require_token),
    ):
        try:
            numeric_club_uid = _query_integer(club_uid, "club_uid", 1, MAX_CLUB_UID)
            value = app.state.save_import.get_squad(save_id, numeric_club_uid)
        except ValueError as error:
            raise _validation_error(error) from error
        if value is None:
            raise _not_found("存档球队不存在")
        return value

    @app.post(
        "/api/drafts/{draft_id}/apply-roster",
        response_model=RosterApplyOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def apply_draft_roster(
        draft_id: str,
        body: RosterApplyInput,
        _: None = Depends(require_token),
    ):
        try:
            value = app.state.save_import.apply_roster(
                draft_id,
                body.save_id,
                body.club_uid,
                body.side,
                body.scope,
            )
        except ValueError as error:
            raise _validation_error(error) from error
        if value is None:
            raise _not_found("草案或存档不存在")
        return value

    @app.post(
        "/api/drafts/{draft_id}/undo-roster",
        response_model=RosterUndoOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def undo_draft_roster(draft_id: str, _: None = Depends(require_token)):
        try:
            value = app.state.save_import.undo_roster(draft_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if value is None:
            raise _not_found("草案不存在")
        return value
