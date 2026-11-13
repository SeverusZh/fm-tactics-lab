from __future__ import annotations

import re
import secrets
import sqlite3
import unicodedata
from collections.abc import Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any

from fm27lab.adapters.storage_sqlite.db import Database

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_PAGE_SIZE = 256
MAX_PATH_LENGTH = 4096
COLUMNS = "id, job_id, kind, path, sha256, bytes, created_at"


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _is_foreign_key_violation(error: sqlite3.IntegrityError) -> bool:
    if getattr(error, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_FOREIGNKEY":
        return True
    return "FOREIGN KEY" in str(error)


class ArtifactRepository:
    def __init__(self, database: Database):
        self.database = database

    @contextmanager
    def _connection(self, connection: sqlite3.Connection | None):
        if connection is not None:
            yield connection, False
        else:
            with closing(self.database.connect()) as owned:
                yield owned, True

    def add(
        self,
        value: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError("产物必须是对象")
        artifact_id = value.get("id")
        if artifact_id is None:
            artifact_id = secrets.token_hex(8)
        self._validate_identifier(artifact_id, "产物标识无效")
        job_id = value.get("job_id")
        if job_id is not None:
            self._validate_identifier(job_id, "任务标识无效")
        kind = self._validate_kind(value.get("kind"))
        path = self._validate_path(value.get("path"))
        sha256 = self._validate_sha256(value.get("sha256"))
        byte_count = value.get("bytes")
        if type(byte_count) is not int or byte_count < 0:
            raise ValueError("产物字节数无效")
        created_at = value.get("created_at")
        if created_at is None:
            created_at = datetime.now(UTC).isoformat()
        else:
            created_at = self._normalize_timestamp(created_at)
        statement = (
            "INSERT INTO artifacts(id, job_id, kind, path, sha256, bytes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        with self._connection(connection) as (active, owned):
            try:
                active.execute(
                    statement,
                    (artifact_id, job_id, kind, path, sha256, byte_count, created_at),
                )
            except sqlite3.IntegrityError as error:
                if _is_foreign_key_violation(error):
                    raise ValueError("任务不存在") from error
                raise ValueError("产物已存在") from error
            if owned:
                active.commit()
        return {
            "id": artifact_id,
            "job_id": job_id,
            "kind": kind,
            "path": path,
            "sha256": sha256,
            "bytes": byte_count,
            "created_at": created_at,
        }

    def get(
        self,
        artifact_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        self._validate_identifier(artifact_id, "产物标识无效")
        with self._connection(connection) as (active, _):
            row = active.execute(
                f"SELECT {COLUMNS} FROM artifacts WHERE id=?",
                (artifact_id,),
            ).fetchone()
        return None if row is None else self._row(row)

    def list(
        self,
        kind: str | None = None,
        job_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError("产物分页大小无效")
        if type(offset) is not int or offset < 0:
            raise ValueError("产物分页偏移无效")
        conditions: list[str] = []
        parameters: list[Any] = []
        if kind is not None:
            conditions.append("kind=?")
            parameters.append(self._validate_kind(kind))
        if job_id is not None:
            self._validate_identifier(job_id, "任务标识无效")
            conditions.append("job_id=?")
            parameters.append(job_id)
        statement = f"SELECT {COLUMNS} FROM artifacts"
        if conditions:
            statement += " WHERE " + " AND ".join(conditions)
        statement += " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
        parameters.extend([limit, offset])
        with self._connection(connection) as (active, _):
            rows = active.execute(statement, parameters).fetchall()
        return [self._row(row) for row in rows]

    def delete(
        self,
        artifact_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        self._validate_identifier(artifact_id, "产物标识无效")
        with self._connection(connection) as (active, owned):
            cursor = active.execute("DELETE FROM artifacts WHERE id=?", (artifact_id,))
            if owned:
                active.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _validate_identifier(value: Any, message: str) -> None:
        if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
            raise ValueError(message)

    @staticmethod
    def _validate_kind(kind: Any) -> str:
        if not isinstance(kind, str) or not 1 <= len(kind) <= 64 or _has_control_characters(kind):
            raise ValueError("产物类型无效")
        try:
            kind.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("产物类型无效") from error
        return kind

    @staticmethod
    def _validate_path(path: Any) -> str:
        if (
            not isinstance(path, str)
            or not 1 <= len(path) <= MAX_PATH_LENGTH
            or _has_control_characters(path)
        ):
            raise ValueError("产物路径无效")
        try:
            path.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("产物路径无效") from error
        return path

    @staticmethod
    def _validate_sha256(sha256: Any) -> str:
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            raise ValueError("产物校验和无效")
        return sha256.lower()

    @staticmethod
    def _normalize_timestamp(value: Any) -> str:
        if not isinstance(value, str) or not 1 <= len(value) <= 64 or _has_control_characters(value):
            raise ValueError("产物时间无效")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("产物时间无效") from error
        if parsed.utcoffset() is None:
            raise ValueError("产物时间无效")
        return parsed.astimezone(UTC).isoformat()

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "kind": row["kind"],
            "path": row["path"],
            "sha256": row["sha256"],
            "bytes": row["bytes"],
            "created_at": row["created_at"],
        }
