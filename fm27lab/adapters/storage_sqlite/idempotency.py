from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any

from fm27lab.adapters.storage_sqlite.db import Database

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_RESPONSE_BYTES = 1_048_576
COLUMNS = "key, request_hash, response_json, created_at"


class IdempotencyConflict(ValueError):
    pass


class IdempotencyRepository:
    def __init__(self, database: Database):
        self.database = database

    @contextmanager
    def _connection(self, connection: sqlite3.Connection | None):
        if connection is not None:
            yield connection, False
        else:
            with closing(self.database.connect()) as owned:
                yield owned, True

    def get(
        self,
        key: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        self._validate_key(key)
        with self._connection(connection) as (active, _):
            row = active.execute(
                f"SELECT {COLUMNS} FROM idempotency WHERE key=?",
                (key,),
            ).fetchone()
        return None if row is None else self._row(row)

    def record(
        self,
        key: str,
        request_hash: str,
        response: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        self._validate_key(key)
        digest = self._validate_hash(request_hash)
        response_json = self._dump_response(response)
        created_at = datetime.now(UTC).isoformat()
        if connection is not None:
            return self._record(connection, key, digest, response_json, created_at)
        with self.database.transaction() as active:
            return self._record(active, key, digest, response_json, created_at)

    def delete(self, key: str) -> bool:
        self._validate_key(key)
        with closing(self.database.connect()) as connection:
            cursor = connection.execute("DELETE FROM idempotency WHERE key=?", (key,))
            connection.commit()
            return cursor.rowcount > 0

    def prune(self, before: str) -> int:
        cutoff = self._normalize_cutoff(before)
        with closing(self.database.connect()) as connection:
            cursor = connection.execute("DELETE FROM idempotency WHERE created_at < ?", (cutoff,))
            connection.commit()
            return cursor.rowcount

    def count(self, connection: sqlite3.Connection | None = None) -> int:
        with self._connection(connection) as (active, _):
            row = active.execute("SELECT COUNT(*) FROM idempotency").fetchone()
        return int(row[0])

    def _record(
        self,
        connection: sqlite3.Connection,
        key: str,
        digest: str,
        response_json: str,
        created_at: str,
    ) -> dict[str, Any]:
        row = self._select(connection, key)
        if row is not None:
            return self._replay(row, digest)
        try:
            connection.execute(
                "INSERT INTO idempotency(key, request_hash, response_json, created_at) VALUES (?, ?, ?, ?)",
                (key, digest, response_json, created_at),
            )
        except sqlite3.IntegrityError:
            row = self._select(connection, key)
            if row is None:
                raise
            return self._replay(row, digest)
        return {
            "key": key,
            "request_hash": digest,
            "response": json.loads(response_json),
            "created_at": created_at,
        }

    @staticmethod
    def _select(connection: sqlite3.Connection, key: str) -> sqlite3.Row | None:
        return connection.execute(
            f"SELECT {COLUMNS} FROM idempotency WHERE key=?",
            (key,),
        ).fetchone()

    @classmethod
    def _replay(cls, row: sqlite3.Row, digest: str) -> dict[str, Any]:
        if row["request_hash"] != digest:
            raise IdempotencyConflict("幂等键已被不同载荷使用")
        return cls._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "key": row["key"],
            "request_hash": row["request_hash"],
            "response": json.loads(row["response_json"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _validate_key(key: Any) -> None:
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError("幂等键无效")

    @staticmethod
    def _validate_hash(request_hash: Any) -> str:
        if not isinstance(request_hash, str) or not HASH_PATTERN.fullmatch(request_hash):
            raise ValueError("幂等请求哈希无效")
        return request_hash.lower()

    @staticmethod
    def _dump_response(response: Any) -> str:
        if not isinstance(response, Mapping):
            raise ValueError("幂等响应必须是对象")
        try:
            encoded = json.dumps(
                dict(response),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            payload = encoded.encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise ValueError("幂等响应无法序列化为 JSON") from error
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("幂等响应过大")
        return encoded

    @staticmethod
    def _normalize_cutoff(before: Any) -> str:
        if not isinstance(before, str) or not 1 <= len(before) <= 64:
            raise ValueError("幂等截止时间无效")
        try:
            parsed = datetime.fromisoformat(before)
        except ValueError as error:
            raise ValueError("幂等截止时间无效") from error
        if parsed.utcoffset() is None:
            raise ValueError("幂等截止时间无效")
        return parsed.astimezone(UTC).isoformat()
