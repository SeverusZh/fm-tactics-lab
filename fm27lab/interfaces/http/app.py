from __future__ import annotations

import hmac
import logging
import sqlite3
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

import fm27lab
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository, PoolRepository
from fm27lab.application.drafts import DraftService
from fm27lab.application.pools import PoolService
from fm27lab.config import Settings

TAURI_ORIGINS = ("tauri://localhost", "http://tauri.localhost")
DEV_ORIGINS = ("http://localhost:1420",)
LOGGER = logging.getLogger(__name__)


ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
SECURITY = HTTPBearer(auto_error=False)


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


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None
    retriable: bool
    retry_after_seconds: int | float | None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


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


def error_body(code: str, message: str, status: int) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": None,
            "retriable": status >= 500 or status == 409,
            "retry_after_seconds": None,
        }
    }


def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(SECURITY)] = None,
) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "missing bearer token", "retriable": False},
            headers={"WWW-Authenticate": "Bearer"},
        )
    supplied = credentials.credentials.strip()
    expected = request.app.state.settings.token
    if not supplied or not supplied.isascii() or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "invalid bearer token", "retriable": False},
            headers={"WWW-Authenticate": "Bearer"},
        )


def _query_integer(value: str, name: str, low: int, high: int) -> int:
    if not value.isascii() or not value.isdigit():
        raise ValueError(f"{name} 必须为 {low}–{high} 的整数")
    number = int(value)
    if not low <= number <= high:
        raise ValueError(f"{name} 必须为 {low}–{high} 的整数")
    return number


def create_app(
    settings: Settings,
    database: Database,
    shutdown: Callable[[], None] | None = None,
    pool_service: PoolService | None = None,
    draft_service: DraftService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="FM Tactics Lab Sidecar",
        version=settings.version,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.pools = pool_service or PoolService(PoolRepository(database))
    app.state.drafts = draft_service or DraftService(DraftRepository(database))
    app.state.shutdown = shutdown

    origins = list(TAURI_ORIGINS + (DEV_ORIGINS if settings.dev else ()))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def enforce_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse(
                status_code=403,
                content=error_body("forbidden_origin", "origin is not allowed", 403),
            )
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            error = {
                "code": detail.get("code", "http_error"),
                "message": detail.get("message", str(exc.status_code)),
                "details": detail.get("details"),
                "retriable": detail.get("retriable", exc.status_code >= 500 or exc.status_code == 409),
                "retry_after_seconds": detail.get("retry_after_seconds"),
            }
            payload = {"error": error}
        else:
            status = exc.status_code
            code = "not_found" if status == 404 else "method_not_allowed" if status == 405 else "http_error"
            payload = error_body(code, str(detail), status)
        headers = dict(exc.headers or {})
        if exc.status_code == 405:
            allowed: set[str] = set()
            for route in app.router.routes:
                methods = getattr(route, "methods", None)
                pattern = getattr(route, "path_regex", None)
                if methods and pattern is not None and pattern.match(request.url.path):
                    allowed.update(method for method in methods if method != "HEAD")
            if allowed:
                headers["Allow"] = ", ".join(sorted(allowed))
        return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content=error_body("validation_failed", "request body or query is invalid", 400),
        )

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, exc: Exception):
        LOGGER.exception("unhandled sidecar error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "internal server error", 500),
        )

    @app.get("/api/health")
    def health():
        ready = database.health()
        if not ready:
            return JSONResponse(
                status_code=503,
                content=error_body("database_unavailable", "database is not ready", 503),
            )
        return {
            "status": "ok",
            "api": fm27lab.API_VERSION,
            "version": settings.version,
            "database": "ready",
        }

    @app.get(
        "/api/pools",
        response_model=PoolListOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def list_pools(
        limit: Annotated[
            str, Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": 128, "default": 128})
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

    @app.get(
        "/api/drafts",
        response_model=DraftListOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def list_drafts(
        limit: Annotated[
            str, Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": 128, "default": 128})
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

    @app.get("/api/version")
    def version():
        return {
            "api": fm27lab.API_VERSION,
            "version": settings.version,
            "capabilities": [],
            "limits": {"max_workers": 256, "max_seeds": 10000},
        }

    @app.post("/api/shutdown", status_code=202)
    def shutdown_sidecar(_: None = Depends(require_token)):
        if app.state.shutdown is not None:
            app.state.shutdown()
        return {"status": "shutting_down"}

    @app.get("/api/events")
    def events(
        _: None = Depends(require_token),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        async def stream():
            event_id = last_event_id or "0"
            yield f'id: {event_id}\nevent: ready\ndata: {{"status":"ok"}}\n\n'

        return StreamingResponse(stream(), media_type="text/event-stream")

    original_openapi = app.openapi

    def openapi_with_contract():
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = original_openapi()
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                responses = operation.get("responses", {})
                responses.pop("422", None)
                for status in ("400", "401", "404", "409"):
                    if status in responses:
                        responses[status]["content"] = {
                            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
                        }
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                if not isinstance(operation, dict):
                    continue
                for parameter in operation.get("parameters", []):
                    default = parameter.get("schema", {}).get("default")
                    if (
                        parameter.get("name") in ("limit", "offset")
                        and isinstance(default, str)
                        and default.isdigit()
                    ):
                        parameter["schema"]["default"] = int(default)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi_with_contract
    return app
