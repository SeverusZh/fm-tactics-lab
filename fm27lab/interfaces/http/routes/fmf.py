"""战术 FMF 导入导出 HTTP 接口。"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from fm27lab.application.drafts import DraftService
from fm27lab.interfaces.http.common import ErrorEnvelope, require_token
from fm27lab.interfaces.http.routes.drafts import DraftOutput
from fm27lab.ports.fmf import FmfCodec as FmfCodecPort

MAX_FMF_BYTES = 4 * 1024 * 1024
MAX_FMF_BASE64_CHARS = (MAX_FMF_BYTES + 2) // 3 * 4
ENCODING_ERROR = "FMF 文件内容不是合法的 base64"
SIZE_ERROR = "FMF 文件超过 4 MiB 上限"


class FmfImportInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    content_base64: str
    source: dict[str, Any] | None = None


class FmfService:
    """组合 FMF 编解码器与草案服务，供 HTTP 入口注入。"""

    def __init__(self, codec: FmfCodecPort, drafts: DraftService) -> None:
        self.codec = codec
        self.drafts = drafts

    def export(self, draft_id: str) -> tuple[dict[str, Any], bytes] | None:
        draft = self.drafts.get(draft_id)
        if draft is None:
            return None
        return draft, self.codec.encode(draft["scenario"])

    def import_draft(
        self,
        name: str,
        content_base64: str,
        source: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if len(content_base64) > MAX_FMF_BASE64_CHARS:
            raise ValueError(SIZE_ERROR)
        try:
            payload = base64.b64decode(content_base64, validate=True)
        except (TypeError, ValueError) as error:
            raise ValueError(ENCODING_ERROR) from error
        if len(payload) > MAX_FMF_BYTES:
            raise ValueError(SIZE_ERROR)
        return self.drafts.create(name, self.codec.decode(payload), source)


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": "草案不存在", "retriable": False},
    )


def _filename(name: str) -> str:
    cleaned = "".join(char for char in name if char.isprintable() and char not in '\\/:*?"<>|').strip(" .")
    return (cleaned or "draft") + ".fmf"


def _content_disposition(name: str) -> str:
    filename = _filename(name)
    if filename.isascii() and '"' not in filename and "\\" not in filename:
        return f'attachment; filename="{filename}"'
    return "attachment; filename=\"draft.fmf\"; filename*=UTF-8''" + quote(filename, safe="")


def register(app: FastAPI) -> None:
    def service() -> FmfService:
        return app.state.fmf_service

    @app.get(
        "/api/drafts/{draft_id}/export.fmf",
        responses={
            200: {
                "description": "战术 FMF 文件",
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            },
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def export_draft_fmf(draft_id: str, _: None = Depends(require_token)):
        try:
            result = service().export(draft_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if result is None:
            raise _not_found()
        draft, payload = result
        digest = hashlib.sha256(payload).hexdigest()
        return Response(
            content=payload,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": _content_disposition(str(draft["name"])),
                "ETag": f'"{digest}"',
            },
        )

    @app.post(
        "/api/drafts/import-fmf",
        status_code=201,
        response_model=DraftOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def import_draft_fmf(body: FmfImportInput, _: None = Depends(require_token)):
        try:
            return service().import_draft(body.name, body.content_base64, body.source)
        except ValueError as error:
            raise _validation_error(error) from error
