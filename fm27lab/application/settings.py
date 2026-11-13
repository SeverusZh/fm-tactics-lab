"""Settings application service: validated JSON values with notes and timestamps."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from typing import Any

from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
NOTE_MAX_LENGTH = 200
MAX_VALUE_DEPTH = 64
MAX_VALUE_BYTES = 65536
KEY_ERROR = "设置键无效"
VALUE_ERROR = "设置值无法序列化为 JSON"
DEPTH_ERROR = "设置值嵌套过深"
SIZE_ERROR = "设置值过大"
NOTE_ERROR = "设置备注无效"
STORE_ERROR = "设置保存失败"
CONTAINER_TYPES = (dict, list, tuple)

SELECT_ROW = "SELECT key, value_json, note, updated_at FROM settings"


class SettingsService:
    """Persist and read settings entries with their metadata.

    SettingsRepository serializes values but exposes neither notes nor timestamps,
    so row metadata is read through its database handle.
    """

    def __init__(self, repository: SettingsRepository):
        self.repository = repository

    def get(self, key: str) -> dict[str, Any] | None:
        self._validate_key(key)
        with closing(self.repository.database.connect()) as connection:
            row = connection.execute(SELECT_ROW + " WHERE key=?", (key,)).fetchone()
        return None if row is None else _entry(row)

    def set(self, key: str, value: Any, note: str | None = None) -> dict[str, Any]:
        self._validate_key(key)
        self._validate_value(value)
        self._validate_note(note)
        with self.repository.database.transaction() as connection:
            self.repository.set(key, value, connection=connection, note=note)
            row = connection.execute(SELECT_ROW + " WHERE key=?", (key,)).fetchone()
        if row is None:
            raise ValueError(STORE_ERROR)
        return _entry(row)

    def all(self) -> list[dict[str, Any]]:
        with closing(self.repository.database.connect()) as connection:
            rows = connection.execute(SELECT_ROW + " ORDER BY key").fetchall()
        return [_entry(row) for row in rows]

    def delete(self, key: str) -> bool:
        self._validate_key(key)
        with self.repository.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM settings WHERE key=?", (key,))
        return cursor.rowcount > 0

    @staticmethod
    def _validate_key(key: Any) -> None:
        if not isinstance(key, str) or KEY_PATTERN.fullmatch(key) is None:
            raise ValueError(KEY_ERROR)

    @staticmethod
    def _validate_value(value: Any) -> None:
        _validate_depth(value)
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                "utf-8"
            )
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as error:
            raise ValueError(VALUE_ERROR) from error
        if len(encoded) > MAX_VALUE_BYTES:
            raise ValueError(SIZE_ERROR)

    @staticmethod
    def _validate_note(note: Any) -> None:
        if note is None:
            return
        if (
            not isinstance(note, str)
            or not 1 <= len(note) <= NOTE_MAX_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in note)
        ):
            raise ValueError(NOTE_ERROR)
        try:
            note.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(NOTE_ERROR) from error


def _validate_depth(value: Any) -> None:
    stack: list[tuple[Any, int, bool]] = [(value, 0, False)]
    active: set[int] = set()
    while stack:
        current, depth, leaving = stack.pop()
        if leaving:
            active.discard(id(current))
            continue
        if not isinstance(current, CONTAINER_TYPES):
            continue
        if id(current) in active:
            raise ValueError(VALUE_ERROR)
        depth += 1
        if depth > MAX_VALUE_DEPTH:
            raise ValueError(DEPTH_ERROR)
        active.add(id(current))
        stack.append((current, depth, True))
        children = current.values() if isinstance(current, dict) else current
        for child in children:
            stack.append((child, depth, False))


def _entry(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "key": row["key"],
        "value": json.loads(row["value_json"]),
        "note": row["note"],
        "updated_at": row["updated_at"],
    }
