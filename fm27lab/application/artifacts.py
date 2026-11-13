"""Artifact application service."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fm27lab.adapters.storage_sqlite.artifacts import ArtifactRepository

FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
KIND_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PAGE_SIZE = 256


class ArtifactService:
    def __init__(self, repository: ArtifactRepository, root: Path):
        self.repository = repository
        self.root = Path(root)

    def register_bytes(
        self,
        *,
        kind: str,
        filename: str,
        content: bytes,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_kind(kind)
        self._validate_filename(filename)
        if not isinstance(content, bytes):
            raise ValueError("产物内容必须为字节")
        directory = self.root / kind
        if directory.is_symlink():
            raise ValueError("产物路径无效")
        directory.mkdir(parents=True, exist_ok=True)
        root_base = self.root.resolve()
        base = directory.resolve()
        if not base.is_relative_to(root_base):
            raise ValueError("产物路径无效")
        target = (base / filename).resolve()
        if target.parent != base:
            raise ValueError("产物路径无效")
        self._ensure_unique(kind, target)
        temporary = self._write_temporary(base, content)
        try:
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        try:
            return self.repository.add(
                {
                    "kind": kind,
                    "path": str(target),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                    "job_id": job_id,
                }
            )
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def register_text(
        self,
        *,
        kind: str,
        filename: str,
        text: str,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(text, str):
            raise ValueError("产物内容必须为文本")
        try:
            content = text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("产物内容无法编码为 UTF-8") from error
        return self.register_bytes(
            kind=kind,
            filename=filename,
            content=content,
            job_id=job_id,
        )

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        return self.repository.get(artifact_id)

    def list(
        self,
        kind: str | None = None,
        job_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= PAGE_SIZE:
            raise ValueError("limit 必须为 1–256 的整数")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset 必须为非负整数")
        items = self.repository.list(kind=kind, job_id=job_id, limit=limit, offset=offset)
        total = self._count(kind, job_id)
        next_offset = offset + len(items)
        return {
            "items": items,
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
        }

    def delete(self, artifact_id: str) -> bool:
        record = self.repository.get(artifact_id)
        if not self.repository.delete(artifact_id):
            return False
        if record is not None:
            self._remove_file(record["path"])
        return True

    def _count(self, kind: str | None, job_id: str | None) -> int:
        total = 0
        offset = 0
        while True:
            page = self.repository.list(kind=kind, job_id=job_id, limit=PAGE_SIZE, offset=offset)
            total += len(page)
            if len(page) < PAGE_SIZE:
                return total
            offset += len(page)

    def _ensure_unique(self, kind: str, target: Path) -> None:
        if target.exists():
            raise ValueError("产物文件已存在")
        resolved = str(target)
        offset = 0
        while True:
            page = self.repository.list(kind=kind, limit=PAGE_SIZE, offset=offset)
            if any(item["path"] == resolved for item in page):
                raise ValueError("产物文件已存在")
            if len(page) < PAGE_SIZE:
                return
            offset += len(page)

    @staticmethod
    def _write_temporary(directory: Path, content: bytes) -> Path:
        descriptor, path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            Path(path).unlink(missing_ok=True)
            raise
        return Path(path)

    def _remove_file(self, stored_path: str) -> None:
        try:
            root = self.root.resolve()
            candidate = Path(stored_path)
            if not candidate.is_absolute():
                candidate = root / candidate
            parent = candidate.parent.resolve()
            if not parent.is_relative_to(root):
                return
            (parent / candidate.name).unlink()
        except (OSError, RuntimeError):
            return

    @staticmethod
    def _validate_kind(kind: Any) -> None:
        if not isinstance(kind, str) or not KIND_PATTERN.fullmatch(kind) or kind in {".", ".."}:
            raise ValueError("产物类型无效")

    @staticmethod
    def _validate_filename(filename: Any) -> None:
        if (
            not isinstance(filename, str)
            or not FILENAME_PATTERN.fullmatch(filename)
            or filename in {".", ".."}
        ):
            raise ValueError("产物文件名无效")
