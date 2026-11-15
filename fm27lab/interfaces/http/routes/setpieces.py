"""定位球 HTTP 路由。"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Response
from fastapi import Path as PathParameter

from fm27lab.application.setpieces import (
    DOCUMENT_SIZE_ERROR,
    ENGINE_UNAVAILABLE_CODE,
    ENGINE_UNAVAILABLE_MESSAGE,
    MAX_DOCUMENT_BYTES,
    UNKNOWN_SETPIECE_MESSAGE,
    SetpiecesService,
    SetpiecesUnavailable,
    UnknownSetpiece,
)
from fm27lab.application.source_paths import clean_path_text
from fm27lab.interfaces.http.common import ID_PATTERN, ErrorEnvelope, attachment_disposition, require_token

MAX_DOCUMENT_BASE64_CHARS = (MAX_DOCUMENT_BYTES + 2) // 3 * 4
ENCODING_ERROR = "定位球文档内容不是合法的 base64"
FILE_MISSING_ERROR = "定位球文档文件不存在"
FILE_READ_ERROR = "定位球文档文件无法读取"
IMPORT_FIELDS = frozenset({"content_base64", "source_path"})
UPDATE_FIELDS = frozenset({"value"})
SetpieceId = Annotated[str, PathParameter(pattern=ID_PATTERN, description="定位球条目：home 或 away")]


def _validation_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _engine_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": ENGINE_UNAVAILABLE_CODE, "message": ENGINE_UNAVAILABLE_MESSAGE, "retriable": True},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": UNKNOWN_SETPIECE_MESSAGE, "retriable": False},
    )


def _unknown_fields_error(fields: list[str], label: str) -> ValueError:
    return ValueError(f"{label}包含未知字段：{'、'.join(fields)}")


def _update_value(body: Mapping[str, Any]) -> Any:
    if "value" not in body:
        raise ValueError("定位球更新请求缺少 value 字段")
    unknown = sorted(str(key) for key in body if key not in UPDATE_FIELDS)
    if unknown:
        raise _unknown_fields_error(unknown, "定位球更新请求")
    return body["value"]


def _import_payload(body: Mapping[str, Any]) -> bytes:
    unknown = sorted(str(key) for key in body if key not in IMPORT_FIELDS)
    if unknown:
        raise _unknown_fields_error(unknown, "定位球导入请求")
    encoded = body.get("content_base64")
    source_path = body.get("source_path")
    if encoded is None and source_path is None:
        raise ValueError("定位球导入请求必须提供 content_base64 或 source_path 之一")
    if encoded is not None and source_path is not None:
        raise ValueError("定位球导入请求只能提供 content_base64 或 source_path 之一")
    if encoded is not None:
        if not isinstance(encoded, str) or len(encoded) > MAX_DOCUMENT_BASE64_CHARS:
            raise ValueError(DOCUMENT_SIZE_ERROR if isinstance(encoded, str) else ENCODING_ERROR)
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(ENCODING_ERROR) from None
    text = clean_path_text(source_path)
    if text is None:
        raise ValueError(FILE_MISSING_ERROR)
    path = Path(text)
    if not path.is_file():
        raise ValueError(FILE_MISSING_ERROR)
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ValueError(DOCUMENT_SIZE_ERROR)
        return path.read_bytes()
    except OSError as error:
        raise ValueError(f"{FILE_READ_ERROR}：{error}") from error


def register(app: FastAPI) -> None:
    def service() -> SetpiecesService:
        return app.state.setpieces

    @app.get(
        "/api/setpieces",
        responses={
            401: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope, "description": "引擎资源不可用"},
        },
    )
    def list_setpieces(_: None = Depends(require_token)) -> dict[str, Any]:
        try:
            return service().list()
        except SetpiecesUnavailable as error:
            raise _engine_unavailable() from error

    @app.get(
        "/api/setpieces/{setpiece_id}",
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope, "description": "引擎资源不可用"},
        },
    )
    def get_setpiece(setpiece_id: SetpieceId, _: None = Depends(require_token)) -> dict[str, Any]:
        try:
            return service().get(setpiece_id)
        except UnknownSetpiece as error:
            raise _not_found() from error
        except SetpiecesUnavailable as error:
            raise _engine_unavailable() from error
        except ValueError as error:
            raise _validation_error(error) from error

    @app.patch(
        "/api/setpieces/{setpiece_id}",
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope, "description": "引擎资源不可用"},
        },
    )
    def update_setpiece(
        setpiece_id: SetpieceId,
        body: Annotated[dict[str, Any], Body()],
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            value = _update_value(body)
            return service().save(setpiece_id, value)
        except UnknownSetpiece as error:
            raise _not_found() from error
        except SetpiecesUnavailable as error:
            raise _engine_unavailable() from error
        except ValueError as error:
            raise _validation_error(error) from error

    @app.post(
        "/api/setpieces/{setpiece_id}/import-file",
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope, "description": "引擎资源不可用"},
        },
    )
    def import_setpiece_file(
        setpiece_id: SetpieceId,
        body: Annotated[dict[str, Any], Body()],
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            payload = _import_payload(body)
            return service().import_document(setpiece_id, payload)
        except UnknownSetpiece as error:
            raise _not_found() from error
        except SetpiecesUnavailable as error:
            raise _engine_unavailable() from error
        except ValueError as error:
            raise _validation_error(error) from error

    @app.get(
        "/api/setpieces/{setpiece_id}/export-file",
        responses={
            200: {
                "description": "定位球 JSON 文档",
                "content": {"application/json": {"schema": {"type": "string"}}},
            },
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope, "description": "引擎资源不可用"},
        },
    )
    def export_setpiece_file(setpiece_id: SetpieceId, _: None = Depends(require_token)):
        try:
            payload, filename = service().export_document(setpiece_id)
        except UnknownSetpiece as error:
            raise _not_found() from error
        except SetpiecesUnavailable as error:
            raise _engine_unavailable() from error
        except ValueError as error:
            raise _validation_error(error) from error
        digest = hashlib.sha256(payload).hexdigest()
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Content-Disposition": attachment_disposition(filename, "setpieces", ".json"),
                "ETag": f'"{digest}"',
            },
        )
