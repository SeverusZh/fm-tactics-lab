from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

import fm27lab
from fm27lab.application.events import (
    KEEPALIVE_COMMENT,
    KEEPALIVE_INTERVAL_SECONDS,
    EventPublisher,
    format_event,
)
from fm27lab.interfaces.http.common import error_body, require_token

ERROR_RESPONSE_STATUSES = ("400", "401", "404", "409")
PAGINATION_PARAMETERS = ("limit", "offset")
INVALID_LAST_EVENT_ID_CODE = "invalid_last_event_id"


def register(app: FastAPI) -> None:
    settings = app.state.settings
    database = app.state.database
    event_publisher(app)

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
    async def events(
        request: Request,
        _: None = Depends(require_token),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        try:
            after_id = parse_last_event_id(last_event_id)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content=error_body(
                    INVALID_LAST_EVENT_ID_CODE,
                    "Last-Event-ID 必须为非负整数",
                    400,
                ),
            )
        return StreamingResponse(
            stream_events(
                event_publisher(request.app),
                after_id,
                api=fm27lab.API_VERSION,
                version=settings.version,
                keepalive_seconds=_keepalive_seconds(request.app),
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    install_openapi_contract(app)


def event_publisher(app: FastAPI) -> EventPublisher:
    publisher = getattr(app.state, "events", None)
    if publisher is None:
        publisher = EventPublisher()
        app.state.events = publisher
    return publisher


def parse_last_event_id(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if not text.isascii() or not text.isdigit():
        raise ValueError("Last-Event-ID 必须为非负整数")
    return int(text)


def _keepalive_seconds(app: FastAPI) -> float:
    value = getattr(app.state, "event_keepalive_seconds", KEEPALIVE_INTERVAL_SECONDS)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return KEEPALIVE_INTERVAL_SECONDS
    return float(value)


async def stream_events(
    publisher: EventPublisher,
    after_id: int | None,
    *,
    api: str,
    version: str,
    keepalive_seconds: float,
) -> AsyncIterator[str]:
    with publisher.subscriber() as subscription:
        last_id = publisher.last_id
        cursor = last_id if after_id is None else min(after_id, last_id)
        yield format_event({"id": cursor, "event": "ready", "data": {"api": api, "version": version}})
        high_watermark = cursor
        if after_id is not None:
            # after_id 早于保留窗口时只能重放仍保留的事件，客户端游标会跳变。
            replayed = publisher.replay(after_id)
            for event in replayed:
                yield format_event(event)
            if replayed:
                high_watermark = replayed[-1]["id"]
        while True:
            try:
                # 阻塞读取交给线程池，等待期间占用一个工作线程；并发流数量受默认线程池上限约束。
                event = await asyncio.to_thread(subscription.get, True, keepalive_seconds)
            except queue.Empty:
                yield KEEPALIVE_COMMENT
                continue
            if event is None:
                return
            if event["id"] <= high_watermark:
                continue
            yield format_event(event)


def install_openapi_contract(app: FastAPI) -> None:
    original_openapi = app.openapi

    def openapi_with_contract():
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = original_openapi()
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                responses = operation.get("responses", {})
                responses.pop("422", None)
                for status in ERROR_RESPONSE_STATUSES:
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
                        parameter.get("name") in PAGINATION_PARAMETERS
                        and isinstance(default, str)
                        and default.isdigit()
                    ):
                        parameter["schema"]["default"] = int(default)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi_with_contract
