from __future__ import annotations

import hmac
import logging
from collections.abc import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import fm27lab
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.config import Settings

TAURI_ORIGINS = ("tauri://localhost", "http://tauri.localhost")
DEV_ORIGINS = ("http://localhost:1420",)
LOGGER = logging.getLogger(__name__)


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
    authorization: str | None = Header(default=None),
) -> None:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "missing bearer token", "retriable": False},
        )
    supplied = authorization.removeprefix("Bearer ").strip()
    expected = request.app.state.settings.token
    if not supplied or not supplied.isascii() or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "invalid bearer token", "retriable": False},
        )


def create_app(
    settings: Settings,
    database: Database,
    shutdown: Callable[[], None] | None = None,
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
    app.state.shutdown = shutdown

    origins = list(TAURI_ORIGINS + (DEV_ORIGINS if settings.dev else ()))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
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
    async def http_error(_request: Request, exc: StarletteHTTPException):
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
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content=error_body("validation_failed", str(exc), 400),
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

    return app
