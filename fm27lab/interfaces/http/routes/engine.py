"""HTTP routes for engine and game directory configuration and diagnostics."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository
from fm27lab.application.engine_config import (
    DEFAULT_ENGINE_DIRECTORY,
    EngineConfig,
    EngineConfigService,
    EngineStatus,
    validate_engine_root,
    validate_game_root,
)
from fm27lab.application.engine_diagnostics import EngineDiagnoseError, EngineDiagnosis, diagnose_engine
from fm27lab.application.engine_import import EngineImportError, EngineImportResult, import_engine_workspace
from fm27lab.application.source_paths import clean_path_text
from fm27lab.interfaces.http.common import ErrorEnvelope, error_body, require_token

DIAGNOSE_ERROR_CODE = "engine_diagnose_failed"
IMPORT_ERROR_CODE = "engine_import_failed"
IMPORT_SOURCE_MESSAGE = "源目录不能为空"
MISSING_ENGINE_MESSAGE = "尚未配置引擎目录"
MISSING_GAME_MESSAGE = "尚未配置游戏目录"


class EngineAvailabilityOutput(BaseModel):
    available: bool
    missing: list[str]


class EngineStatusOutput(BaseModel):
    engine_root: str | None
    game_root: str | None
    engine: EngineAvailabilityOutput
    game: EngineAvailabilityOutput


class EngineSelectInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    engine_root: str | None = None
    game_root: str | None = None


class EngineDiagnosisOutput(BaseModel):
    compatible: bool
    trial_allowed: bool
    reason: str | None
    adapter_version: str | None = None
    image_sha256: str | None


class EngineImportCopiedOutput(BaseModel):
    path: str
    bytes: int


class EngineImportInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    source_path: str = Field(min_length=1, max_length=4096)


class EngineImportOutput(BaseModel):
    target_root: str
    available: bool
    missing: list[str]
    matched: bool
    adapter_version: str | None
    catalog_path: str | None
    copied: list[EngineImportCopiedOutput]
    total_bytes: int


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _status_output(status: EngineStatus) -> EngineStatusOutput:
    return EngineStatusOutput(
        engine_root=None if status.engine_root is None else str(status.engine_root),
        game_root=None if status.game_root is None else str(status.game_root),
        engine=EngineAvailabilityOutput(available=status.engine_available, missing=list(status.engine_missing)),
        game=EngineAvailabilityOutput(available=status.game_available, missing=list(status.game_missing)),
    )


def _diagnosis_output(diagnosis: EngineDiagnosis) -> EngineDiagnosisOutput:
    return EngineDiagnosisOutput(
        compatible=diagnosis.compatible,
        trial_allowed=diagnosis.trial_allowed,
        reason=diagnosis.reason,
        adapter_version=diagnosis.adapter_version,
        image_sha256=diagnosis.image_sha256,
    )


def _import_output(result: EngineImportResult) -> EngineImportOutput:
    return EngineImportOutput(
        target_root=str(result.target_root),
        available=result.available,
        missing=list(result.missing),
        matched=result.matched,
        adapter_version=result.adapter_version,
        catalog_path=None if result.catalog_path is None else str(result.catalog_path),
        copied=[EngineImportCopiedOutput(path=item.path, bytes=item.bytes) for item in result.copied],
        total_bytes=result.total_bytes,
    )


def _configured_engine_root(service: EngineConfigService) -> object:
    engine_root = service.runtime.engine_root
    if engine_root is None:
        raise ValueError(MISSING_ENGINE_MESSAGE)
    return validate_engine_root(engine_root)


def _current_game_root(service: EngineConfigService) -> Path | str | None:
    return service.resolve().game_root or service.runtime.game_root


def _configured_game_root(service: EngineConfigService) -> object:
    game_root = _current_game_root(service)
    if game_root is None:
        raise ValueError(MISSING_GAME_MESSAGE)
    return validate_game_root(game_root)


def register(app: FastAPI) -> None:
    settings = app.state.settings
    service = EngineConfigService(
        SettingsRepository(app.state.database),
        settings.data_dir,
        runtime=EngineConfig(settings.engine_root, settings.game_root),
    )

    @app.get("/api/engine", response_model=EngineStatusOutput, responses={401: {"model": ErrorEnvelope}})
    def engine_status(_: None = Depends(require_token)) -> EngineStatusOutput:
        return _status_output(service.status())

    @app.post(
        "/api/engine/select",
        response_model=EngineStatusOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def engine_select(payload: EngineSelectInput, _: None = Depends(require_token)) -> EngineStatusOutput:
        try:
            status = service.select(engine_root=payload.engine_root, game_root=payload.game_root)
        except ValueError as error:
            raise _validation_error(error) from error
        return _status_output(status)

    @app.post(
        "/api/engine/diagnose",
        response_model=EngineDiagnosisOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
    )
    def engine_diagnose(_: None = Depends(require_token)) -> EngineDiagnosisOutput | JSONResponse:
        try:
            engine_root = _configured_engine_root(service)
            game_root = _configured_game_root(service)
        except ValueError as error:
            raise _validation_error(error) from error
        try:
            diagnosis = diagnose_engine(engine_root, game_root)
        except EngineDiagnoseError as error:
            return JSONResponse(status_code=503, content=error_body(DIAGNOSE_ERROR_CODE, str(error), 503))
        return _diagnosis_output(diagnosis)

    @app.post(
        "/api/engine/import",
        response_model=EngineImportOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def engine_import(
        payload: EngineImportInput,
        _: None = Depends(require_token),
    ) -> EngineImportOutput | JSONResponse:
        source_path = clean_path_text(payload.source_path)
        if source_path is None:
            raise _validation_error(ValueError(IMPORT_SOURCE_MESSAGE))
        try:
            result = import_engine_workspace(
                source_path,
                settings.data_dir / DEFAULT_ENGINE_DIRECTORY,
                game_root=_current_game_root(service),
                data_dir=settings.data_dir,
            )
        except EngineImportError as error:
            return JSONResponse(status_code=400, content=error_body(IMPORT_ERROR_CODE, str(error), 400))
        except ValueError as error:
            raise _validation_error(error) from error
        return _import_output(result)
