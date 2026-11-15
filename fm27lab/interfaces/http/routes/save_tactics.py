"""存档战术库 HTTP 接口：列出存档战术并导入为草案。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi import Path as PathParameter
from pydantic import BaseModel, ConfigDict, Field

from fm27lab.adapters.engine_native.tactic_file import UNCONFIGURED_ERROR, TacticFileError
from fm27lab.application.save_tactics import (
    ENGINE_UNAVAILABLE_MESSAGE,
    TACTIC_MISSING_ERROR,
    SaveTacticsService,
)
from fm27lab.interfaces.http.common import ErrorEnvelope, require_token
from fm27lab.interfaces.http.routes.drafts import DraftOutput

ENGINE_UNAVAILABLE_CODE = "engine_unavailable"
VALIDATION_FAILED_CODE = "validation_failed"
NOT_FOUND_CODE = "not_found"
SAVE_NOT_FOUND_MESSAGE = "存档不存在"

__all__ = [
    "SaveTacticImportInput",
    "SaveTacticImportOutput",
    "SaveTacticListOutput",
    "SaveTacticOutput",
    "register",
]


class SaveTacticOutput(BaseModel):
    index: int
    name: str
    style: str
    mentality: int | None
    club_uid: int | None
    club_name: str | None
    team_slot: int | None
    importable: bool


class SaveTacticListOutput(BaseModel):
    items: list[SaveTacticOutput]


class SaveTacticImportOutput(BaseModel):
    draft: DraftOutput


class SaveTacticImportInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": VALIDATION_FAILED_CODE, "message": str(error), "retriable": False},
    )


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": NOT_FOUND_CODE, "message": message, "retriable": False},
    )


def _engine_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": ENGINE_UNAVAILABLE_CODE, "message": ENGINE_UNAVAILABLE_MESSAGE, "retriable": True},
    )


def _service(app: FastAPI) -> SaveTacticsService:
    service = getattr(app.state, "save_tactics", None)
    if service is None:
        service = SaveTacticsService(app.state.saves, app.state.drafts, app.state.settings)
        app.state.save_tactics = service
    return service


def register(app: FastAPI) -> None:
    @app.get(
        "/api/saves/{save_id}/tactics",
        response_model=SaveTacticListOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def list_save_tactics(save_id: str, _: None = Depends(require_token)):
        try:
            items = _service(app).list_tactics(save_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if items is None:
            raise _not_found(SAVE_NOT_FOUND_MESSAGE)
        return {"items": items}

    @app.post(
        "/api/saves/{save_id}/tactics/{tactic_index}/import",
        status_code=201,
        response_model=SaveTacticImportOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
    )
    def import_save_tactic(
        save_id: str,
        tactic_index: Annotated[int, PathParameter(ge=0)],
        body: SaveTacticImportInput | None = None,
        _: None = Depends(require_token),
    ):
        name = body.name.strip() if body is not None and body.name is not None else None
        if body is not None and body.name is not None and not name:
            raise _validation_error(ValueError("战术名称不能为空白"))
        try:
            draft = _service(app).import_tactic(save_id, tactic_index, name)
        except TacticFileError as error:
            if str(error) == UNCONFIGURED_ERROR:
                raise _engine_unavailable() from error
            raise _validation_error(error) from error
        except ValueError as error:
            if str(error) == TACTIC_MISSING_ERROR:
                raise _not_found(TACTIC_MISSING_ERROR) from error
            raise _validation_error(error) from error
        if draft is None:
            raise _not_found(SAVE_NOT_FOUND_MESSAGE)
        return {"draft": draft}
