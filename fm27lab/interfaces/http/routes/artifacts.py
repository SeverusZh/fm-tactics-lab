from __future__ import annotations

import base64
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict

from fm27lab.adapters.storage_sqlite.artifacts import ArtifactRepository
from fm27lab.application.artifacts import ArtifactService
from fm27lab.interfaces.http.common import ErrorEnvelope, _query_integer, require_token

MAX_CONTENT_BYTES = 16 * 1024 * 1024


class ArtifactRegisterInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: str
    filename: str
    content_base64: str
    job_id: str | None = None


class ArtifactOutput(BaseModel):
    id: str
    job_id: str | None
    kind: str
    path: str
    sha256: str
    bytes: int
    created_at: str


class ArtifactListOutput(BaseModel):
    items: list[ArtifactOutput]
    total: int
    next_offset: int | None


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _not_found(message: str = "产物不存在") -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": message, "retriable": False},
    )


def _decode_base64(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ValueError("产物内容不是合法的 base64") from error


def register(app: FastAPI) -> None:
    def artifacts() -> ArtifactService:
        service = getattr(app.state, "artifacts", None)
        if service is None:
            service = ArtifactService(
                ArtifactRepository(app.state.database),
                app.state.settings.data_dir / "agent" / "artifacts",
            )
            app.state.artifacts = service
        return service

    def load_artifact(artifact_id: str) -> dict:
        try:
            record = artifacts().get(artifact_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if record is None:
            raise _not_found()
        return record

    def read_content(record: dict) -> bytes:
        stored = Path(record["path"])
        if not stored.is_absolute() or stored.is_symlink():
            raise _not_found("产物文件不存在")
        try:
            root = artifacts().root.resolve()
            resolved = stored.resolve()
        except (OSError, RuntimeError) as error:
            raise _not_found("产物文件不存在") from error
        if not resolved.is_relative_to(root):
            raise _not_found("产物文件不存在")
        try:
            return resolved.read_bytes()
        except OSError as error:
            raise _not_found("产物文件不存在") from error

    @app.get(
        "/api/artifacts",
        response_model=ArtifactListOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def list_artifacts(
        kind: Annotated[str | None, Query()] = None,
        job_id: Annotated[str | None, Query()] = None,
        limit: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": 256, "default": 50}),
        ] = "50",
        offset: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 0, "maximum": 2**31 - 1, "default": 0}),
        ] = "0",
        _: None = Depends(require_token),
    ):
        try:
            return artifacts().list(
                kind=kind,
                job_id=job_id,
                limit=_query_integer(limit, "limit", 1, 256),
                offset=_query_integer(offset, "offset", 0, 2**31 - 1),
            )
        except ValueError as error:
            raise _validation_error(error) from error

    @app.post(
        "/api/artifacts",
        status_code=201,
        response_model=ArtifactOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            413: {"model": ErrorEnvelope},
        },
    )
    def register_artifact(body: ArtifactRegisterInput, _: None = Depends(require_token)):
        try:
            content = _decode_base64(body.content_base64)
        except ValueError as error:
            raise _validation_error(error) from error
        if len(content) > MAX_CONTENT_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "payload_too_large",
                    "message": "产物内容超过 16 MiB 上限",
                    "retriable": False,
                },
            )
        try:
            return artifacts().register_bytes(
                kind=body.kind,
                filename=body.filename,
                content=content,
                job_id=body.job_id,
            )
        except ValueError as error:
            raise _validation_error(error) from error

    @app.get(
        "/api/artifacts/{artifact_id}",
        response_model=ArtifactOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def get_artifact(artifact_id: str, _: None = Depends(require_token)):
        return load_artifact(artifact_id)

    @app.get(
        "/api/artifacts/{artifact_id}/content",
        responses={
            200: {
                "description": "产物文件内容",
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            },
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def download_artifact(artifact_id: str, _: None = Depends(require_token)):
        record = load_artifact(artifact_id)
        content = read_content(record)
        filename = Path(record["path"]).name.replace("\\", "\\\\").replace('"', '\\"')
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={
                "ETag": f'"{record["sha256"]}"',
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.delete(
        "/api/artifacts/{artifact_id}",
        status_code=204,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def delete_artifact(artifact_id: str, _: None = Depends(require_token)):
        try:
            deleted = artifacts().delete(artifact_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if not deleted:
            raise _not_found()
        return Response(status_code=204)
