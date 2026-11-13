"""运行时目录快照 HTTP 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from fm27lab.interfaces.http.common import ErrorEnvelope, require_token


class CatalogSnapshotOutput(BaseModel):
    available: bool
    catalog: dict[str, Any] | None


def register(app: FastAPI) -> None:
    @app.get(
        "/api/catalog",
        response_model=CatalogSnapshotOutput,
        responses={401: {"model": ErrorEnvelope}},
    )
    def catalog_snapshot(_: None = Depends(require_token)):
        return app.state.catalog_service.snapshot()
