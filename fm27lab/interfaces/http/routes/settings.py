"""HTTP routes for settings storage and the concurrency preflight."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict

from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository
from fm27lab.application.settings import SettingsService
from fm27lab.domain.concurrency import resource_check
from fm27lab.interfaces.http.common import ErrorEnvelope, require_token

WORKERS_ERROR = "并行数必须为 1–256 的整数"
CPU_ERROR = "CPU 数量必须为正整数"
MEMORY_ERROR = "可用内存必须为非负整数"
DISK_ERROR = "空闲磁盘必须为非负整数"
OVERRIDE_ERROR = "资源覆盖开关必须为 true 或 false"
NOT_FOUND_MESSAGE = "设置不存在"


class SettingOutput(BaseModel):
    key: str
    value: Any
    note: str | None
    updated_at: str


class SettingListOutput(BaseModel):
    items: list[SettingOutput]
    total: int


class SettingPutInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    value: Any
    note: str | None = None


class ConcurrencyCheckOutput(BaseModel):
    allowed: bool
    code: str | None
    recommended_workers: int
    warnings: list[str]
    memory_required_bytes: int
    disk_required_bytes: int


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": NOT_FOUND_MESSAGE, "retriable": False},
    )


def _parse_integer(value: str, message: str) -> int:
    if not value.isascii() or not value.isdigit():
        raise ValueError(message)
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(message) from error


def _parse_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(OVERRIDE_ERROR)


def register(app: FastAPI) -> None:
    service = SettingsService(SettingsRepository(app.state.database))
    app.state.settings_service = service

    def load_setting(key: str) -> dict[str, Any]:
        try:
            value = service.get(key)
        except ValueError as error:
            raise _validation_error(error) from error
        if value is None:
            raise _not_found()
        return value

    @app.get(
        "/api/settings",
        response_model=SettingListOutput,
        responses={401: {"model": ErrorEnvelope}},
    )
    def list_settings(_: None = Depends(require_token)):
        items = service.all()
        return {"items": items, "total": len(items)}

    @app.get(
        "/api/settings/{key}",
        response_model=SettingOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def get_setting(key: str, _: None = Depends(require_token)):
        return load_setting(key)

    @app.put(
        "/api/settings/{key}",
        response_model=SettingOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
        },
    )
    def put_setting(key: str, body: SettingPutInput, _: None = Depends(require_token)):
        try:
            return service.set(key, body.value, note=body.note)
        except ValueError as error:
            raise _validation_error(error) from error

    @app.delete(
        "/api/settings/{key}",
        status_code=204,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def delete_setting(key: str, _: None = Depends(require_token)):
        try:
            deleted = service.delete(key)
        except ValueError as error:
            raise _validation_error(error) from error
        if not deleted:
            raise _not_found()
        return Response(status_code=204)

    @app.get(
        "/api/concurrency/check",
        response_model=ConcurrencyCheckOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
        },
    )
    def concurrency_check(
        workers: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": 256}),
        ],
        cpu_count: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 1}),
        ],
        available_memory_bytes: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 0}),
        ],
        free_disk_bytes: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 0}),
        ],
        allow_oversubscription: Annotated[
            str,
            Query(json_schema_extra={"type": "boolean"}),
        ],
        _: None = Depends(require_token),
    ):
        try:
            return resource_check(
                _parse_integer(workers, WORKERS_ERROR),
                cpu_count=_parse_integer(cpu_count, CPU_ERROR),
                available_memory_bytes=_parse_integer(available_memory_bytes, MEMORY_ERROR),
                free_disk_bytes=_parse_integer(free_disk_bytes, DISK_ERROR),
                allow_oversubscription=_parse_bool(allow_oversubscription),
            )
        except ValueError as error:
            raise _validation_error(error) from error
