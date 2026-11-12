from __future__ import annotations

import json
import re
import secrets
import sqlite3
from collections.abc import Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.domain.pool import MAX_ENTRIES

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SettingsRepository:
    def __init__(self, database: Database):
        self.database = database

    def set(
        self,
        key: str,
        value: Any,
        connection: sqlite3.Connection | None = None,
        note: str | None = None,
    ) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        stamp = datetime.now(UTC).isoformat()
        statement = (
            "INSERT INTO settings(key, value_json, note, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
            "note=excluded.note, updated_at=excluded.updated_at"
        )
        if connection is None:
            with closing(self.database.connect()) as owned:
                owned.execute(statement, (key, payload, note, stamp))
                owned.commit()
        else:
            connection.execute(statement, (key, payload, note, stamp))

    def get(
        self,
        key: str,
        default: Any = None,
        connection: sqlite3.Connection | None = None,
    ) -> Any:
        statement = "SELECT value_json FROM settings WHERE key=?"
        if connection is None:
            with closing(self.database.connect()) as owned:
                row = owned.execute(statement, (key,)).fetchone()
        else:
            row = connection.execute(statement, (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def all(self) -> dict[str, Any]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute("SELECT key, value_json FROM settings")
            return {row[0]: json.loads(row[1]) for row in rows}


class PoolRepository:
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
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError("客队战术条目必须是对象")
        name = value.get("name")
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 80
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
        ):
            raise ValueError("客队战术名称无效")
        try:
            name.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("客队战术名称无效") from error
        weight = value.get("weight", 1)
        if type(weight) is not int or not 1 <= weight <= 1000:
            raise ValueError("客队战术权重无效")
        tactic = value.get("tactic")
        if not isinstance(tactic, Mapping):
            raise ValueError("客队战术内容必须是对象")
        roster = value.get("roster")
        if roster is not None and not isinstance(roster, Mapping):
            raise ValueError("客队战术名单必须是对象")
        entry_id = value.get("id")
        if entry_id is None:
            entry_id = secrets.token_hex(8)
        self._validate_id(entry_id)
        stamp = datetime.now(UTC).isoformat() if created_at is None else created_at
        if (
            not isinstance(stamp, str)
            or not 1 <= len(stamp) <= 64
            or any(ord(c) < 32 or ord(c) == 127 for c in stamp)
        ):
            raise ValueError("客队战术时间无效")
        try:
            datetime.fromisoformat(stamp)
        except ValueError as error:
            raise ValueError("客队战术时间无效") from error
        tactic_json = self._dump(tactic, "客队战术内容")
        roster_json = None if roster is None else self._dump(roster, "客队战术名单")
        statement = (
            "INSERT INTO pool_entries(id, name, weight, tactic_json, roster_json, created_at) "
            "SELECT ?, ?, ?, ?, ?, ? "
            "WHERE (SELECT COUNT(*) FROM pool_entries) < ?"
        )
        parameters = (entry_id, name.strip(), weight, tactic_json, roster_json, stamp, MAX_ENTRIES)
        with self._connection(connection) as (active, owned):
            if owned:
                active.execute("BEGIN IMMEDIATE")
            cursor = active.execute(statement, parameters)
            if cursor.rowcount == 0:
                if owned:
                    active.rollback()
                raise ValueError(f"客队战术池最多允许 {MAX_ENTRIES} 套战术")
            if owned:
                active.commit()
        return {
            "id": entry_id,
            "name": name.strip(),
            "weight": weight,
            "tactic": json.loads(tactic_json),
            "roster": None if roster_json is None else json.loads(roster_json),
            "created_at": stamp,
        }

    def get(
        self,
        entry_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        self._validate_id(entry_id)
        with self._connection(connection) as (active, _):
            row = active.execute(
                "SELECT id, name, weight, tactic_json, roster_json, created_at FROM pool_entries WHERE id=?",
                (entry_id,),
            ).fetchone()
        return None if row is None else self._row(row)

    def list(self, connection: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        with self._connection(connection) as (active, _):
            rows = active.execute(
                "SELECT id, name, weight, tactic_json, roster_json, created_at "
                "FROM pool_entries ORDER BY created_at, rowid"
            ).fetchall()
        return [self._row(row) for row in rows]

    def delete(
        self,
        entry_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        self._validate_id(entry_id)
        with self._connection(connection) as (active, owned):
            cursor = active.execute("DELETE FROM pool_entries WHERE id=?", (entry_id,))
            if owned:
                active.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _validate_id(entry_id: Any) -> None:
        if not isinstance(entry_id, str) or not ID_PATTERN.fullmatch(entry_id):
            raise ValueError("客队战术标识无效")

    @staticmethod
    def _dump(value: Mapping[str, Any], label: str) -> str:
        try:
            encoded = json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            encoded.encode("utf-8")
            return encoded
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise ValueError(label + "无法序列化为 JSON") from error

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "weight": row["weight"],
            "tactic": json.loads(row["tactic_json"]),
            "roster": None if row["roster_json"] is None else json.loads(row["roster_json"]),
            "created_at": row["created_at"],
        }
