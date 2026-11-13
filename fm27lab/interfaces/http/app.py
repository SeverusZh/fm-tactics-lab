from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from fm27lab.adapters.catalog_native.catalog import CatalogRepository
from fm27lab.adapters.engine_native.capabilities import parse_capabilities, plan_runtime
from fm27lab.adapters.fmf import FmfCodec
from fm27lab.adapters.save_fmsave import FmsaveReader
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.idempotency import IdempotencyRepository
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository, JobRepository, PoolRepository
from fm27lab.adapters.storage_sqlite.saves import SavesRepository
from fm27lab.application.catalog import CatalogService
from fm27lab.application.draft_attributes import DraftAttributeService
from fm27lab.application.drafts import DraftService
from fm27lab.application.events import EventPublisher
from fm27lab.application.experiment_material import ExperimentMaterializer
from fm27lab.application.experiments import ExperimentService
from fm27lab.application.idempotency import IdempotencyService
from fm27lab.application.jobs import JobService
from fm27lab.application.pools import PoolService
from fm27lab.application.save_import import SaveImportService
from fm27lab.application.saves import SavesService
from fm27lab.config import Settings
from fm27lab.interfaces.http.common import (
    ID_PATTERN,
    SECURITY,
    ErrorBody,
    ErrorEnvelope,
    _query_integer,
    error_body,
    require_token,
)
from fm27lab.interfaces.http.idempotency import IdempotencyMiddleware
from fm27lab.interfaces.http.routes import register_routes
from fm27lab.interfaces.http.routes.fmf import FmfService
from fm27lab.ports.engine import EngineCapabilities

TAURI_ORIGINS = ("tauri://localhost", "http://tauri.localhost")
DEV_ORIGINS = ("http://localhost:1420",)
ENGINE_UNAVAILABLE_MESSAGE = "原生引擎未配置"
EXPERIMENT_RUNTIME_PLAN = plan_runtime(
    parse_capabilities(None),
    has_pool_variants=False,
    has_experimental_execution=False,
)
LOGGER = logging.getLogger(__name__)

__all__ = [
    "DEV_ORIGINS",
    "ErrorBody",
    "ErrorEnvelope",
    "ID_PATTERN",
    "MissingEngine",
    "SECURITY",
    "TAURI_ORIGINS",
    "_query_integer",
    "create_app",
    "error_body",
    "require_token",
]


class MissingEngine:
    """Engine port placeholder used until a native engine host is configured."""

    def capabilities(self) -> EngineCapabilities:
        return parse_capabilities(None)

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: Callable[[Mapping[str, Any]], None],
        on_progress: Callable[[Sequence[Mapping[str, Any]]], None],
    ) -> None:
        raise RuntimeError(ENGINE_UNAVAILABLE_MESSAGE)

    def cancel(self) -> None:
        return None


def create_app(
    settings: Settings,
    database: Database,
    shutdown: Callable[[], None] | None = None,
    pool_service: PoolService | None = None,
    draft_service: DraftService | None = None,
    draft_attribute_service: DraftAttributeService | None = None,
    fmf_service: FmfService | None = None,
    job_service: JobService | None = None,
    experiment_service: ExperimentService | None = None,
    experiment_materializer: ExperimentMaterializer | None = None,
    saves_service: SavesService | None = None,
    save_import_service: SaveImportService | None = None,
    idempotency_service: IdempotencyService | None = None,
    events: EventPublisher | None = None,
    catalog_service: CatalogService | None = None,
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
    app.state.events = events or EventPublisher()
    app.state.pools = pool_service or PoolService(PoolRepository(database))
    app.state.drafts = draft_service or DraftService(DraftRepository(database))
    app.state.draft_attributes = draft_attribute_service or DraftAttributeService(app.state.drafts)
    app.state.fmf_service = fmf_service or FmfService(FmfCodec(), app.state.drafts)
    app.state.jobs = job_service or JobService(JobRepository(database), publisher=app.state.events)
    if experiment_service is not None:
        app.state.experiments = experiment_service
    else:
        materializer = experiment_materializer or ExperimentMaterializer(
            app.state.drafts,
            settings,
        )
        app.state.experiments = ExperimentService(
            app.state.jobs,
            MissingEngine(),
            EXPERIMENT_RUNTIME_PLAN,
            publisher=app.state.events,
            materializer=materializer,
        )
        set_cleanup = getattr(app.state.jobs, "set_cleanup", None)
        if set_cleanup is not None:
            set_cleanup(materializer.discard)
    app.state.saves = saves_service or SavesService(SavesRepository(database))
    app.state.save_import = save_import_service or SaveImportService(
        app.state.saves,
        app.state.drafts,
        FmsaveReader,
    )
    app.state.catalog_service = catalog_service or CatalogService(
        CatalogRepository(settings.engine_root, settings.data_dir)
    )
    app.state.idempotency = idempotency_service or IdempotencyService(IdempotencyRepository(database))
    app.state.shutdown = shutdown

    origins = list(TAURI_ORIGINS + (DEV_ORIGINS if settings.dev else ()))
    app.add_middleware(IdempotencyMiddleware, service=app.state.idempotency)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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

    register_routes(app)
    return app
