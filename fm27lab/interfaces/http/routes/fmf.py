"""战术 FMF 导入导出 HTTP 接口。"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets, load_scenario_assets
from fm27lab.adapters.engine_native.tactic_file import (
    UNCONFIGURED_ERROR,
    TacticFileError,
    TacticPlan,
    is_afe_archive,
    read_tactic_file,
)
from fm27lab.application.drafts import DraftService
from fm27lab.application.source_paths import clean_path_text
from fm27lab.application.tactic_export import EngineUnavailableError, TacticExporter
from fm27lab.application.tactic_import import build_scenario
from fm27lab.config import Settings
from fm27lab.interfaces.http.common import ErrorEnvelope, require_token
from fm27lab.interfaces.http.routes.drafts import DraftOutput
from fm27lab.ports.fmf import FMF_MAGIC
from fm27lab.ports.fmf import FmfCodec as FmfCodecPort

MAX_FMF_BYTES = 4 * 1024 * 1024
MAX_FMF_BASE64_CHARS = (MAX_FMF_BYTES + 2) // 3 * 4
ENCODING_ERROR = "FMF 文件内容不是合法的 base64"
SIZE_ERROR = "FMF 文件超过 4 MiB 上限"
FILE_MISSING_ERROR = "战术文件不存在"
MAX_NAME_CHARS = 80
FALLBACK_NAME = "导入战术"
ENGINE_UNAVAILABLE_CODE = "engine_unavailable"
FMF_FORMAT_HEADER = "X-Fmf-Format"
FMF_V8_FORMAT = "fmfv8"


class FmfImportInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    content_base64: str
    source: dict[str, Any] | None = None


class FmfFileImportInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    source_path: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, min_length=1, max_length=80)


def _draft_name(name: str | None, path: Path, embedded: str = "") -> str:
    candidate = name.strip() if name is not None else ""
    if not candidate:
        candidate = embedded.strip()
    if not candidate:
        candidate = path.stem.strip()
    return (candidate or FALLBACK_NAME)[:MAX_NAME_CHARS]


class FmfService:
    """组合 FMF 编解码器与草案服务，供 HTTP 入口注入。"""

    def __init__(
        self,
        codec: FmfCodecPort,
        drafts: DraftService,
        settings: Settings | None = None,
        *,
        reader: Callable[..., TacticPlan] = read_tactic_file,
        assets_loader: Callable[[Path], ScenarioAssets] = load_scenario_assets,
        exporter: TacticExporter | None = None,
    ) -> None:
        self.codec = codec
        self.drafts = drafts
        self.settings = settings
        self.reader = reader
        self.assets_loader = assets_loader
        self.exporter = exporter if exporter is not None else TacticExporter(assets_loader=assets_loader)

    def export(self, draft_id: str) -> tuple[dict[str, Any], bytes] | None:
        draft = self.drafts.get(draft_id)
        if draft is None:
            return None
        settings = self.settings
        engine_root = settings.engine_root if settings is not None else None
        game_root = settings.game_root if settings is not None else None
        payload = self.exporter.export(
            name=str(draft["name"]),
            scenario=draft["scenario"],
            engine_root=engine_root,
            game_root=game_root,
        )
        return draft, payload

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

    def import_draft_file(self, name: str | None, source_path: str) -> dict[str, Any]:
        text = clean_path_text(source_path)
        if text is None:
            raise ValueError(FILE_MISSING_ERROR)
        path = Path(text)
        if not path.is_file():
            raise ValueError(FILE_MISSING_ERROR)
        if path.stat().st_size > MAX_FMF_BYTES:
            raise ValueError(SIZE_ERROR)
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ValueError(f"战术文件无法读取：{error}") from error
        source = {"kind": "fmf", "path": str(path)}
        if payload.startswith(FMF_MAGIC):
            return self.drafts.create(_draft_name(name, path), self.codec.decode(payload), source)
        if is_afe_archive(payload):
            plan = self.read_plan(path)
            scenario = build_scenario(self.load_assets(), plan)
            return self.drafts.create(_draft_name(name, path, plan.name), scenario, source)
        return self.drafts.create(_draft_name(name, path), self.codec.decode(payload), source)

    def read_plan(self, path: Path) -> TacticPlan:
        return self.reader(
            path,
            engine_root=self.engine_root(),
            game_root=self.game_root(),
        )

    def load_assets(self) -> ScenarioAssets:
        return self.assets_loader(self.engine_root())

    def engine_root(self) -> Path:
        if self.settings is None or self.settings.engine_root is None:
            raise TacticFileError(UNCONFIGURED_ERROR)
        return self.settings.engine_root

    def game_root(self) -> Path:
        if self.settings is None or self.settings.game_root is None:
            raise TacticFileError(UNCONFIGURED_ERROR)
        return self.settings.game_root


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _engine_unavailable(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": ENGINE_UNAVAILABLE_CODE, "message": str(error), "retriable": True},
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
            503: {"model": ErrorEnvelope},
        },
    )
    def export_draft_fmf(draft_id: str, _: None = Depends(require_token)):
        try:
            result = service().export(draft_id)
        except EngineUnavailableError as error:
            raise _engine_unavailable(error) from error
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
                FMF_FORMAT_HEADER: FMF_V8_FORMAT,
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

    @app.post(
        "/api/drafts/import-fmf-file",
        status_code=201,
        response_model=DraftOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
    )
    def import_draft_fmf_file(body: FmfFileImportInput, _: None = Depends(require_token)):
        try:
            return service().import_draft_file(body.name, body.source_path)
        except TacticFileError as error:
            if str(error) == UNCONFIGURED_ERROR:
                raise _engine_unavailable(error) from error
            raise _validation_error(error) from error
        except ValueError as error:
            raise _validation_error(error) from error
