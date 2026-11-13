from __future__ import annotations

from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse

import fm27lab
from fm27lab.interfaces.http.common import error_body, require_token

ERROR_RESPONSE_STATUSES = ("400", "401", "404", "409")
PAGINATION_PARAMETERS = ("limit", "offset")


def register(app: FastAPI) -> None:
    settings = app.state.settings
    database = app.state.database

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

    install_openapi_contract(app)


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
