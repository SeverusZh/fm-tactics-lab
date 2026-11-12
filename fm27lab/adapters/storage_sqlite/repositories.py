from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from fm27lab.adapters.storage_sqlite.db import Database


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
