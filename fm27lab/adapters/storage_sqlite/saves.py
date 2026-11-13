from __future__ import annotations

import json
import re
import secrets
import sqlite3
import unicodedata
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any

from fm27lab.adapters.storage_sqlite.db import Database

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
SAVE_COLUMNS = "id, source_path, source_sha256, status, stage, metadata_json, created_at, updated_at"
MAX_SOURCE_PATH = 4096
MAX_STAGE = 200
MAX_LEAGUE_KEY = 64


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _validate_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or _has_control_characters(value):
        raise ValueError(label + "无效")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(label + "无效") from error
    return value


def _validate_stamp(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or _has_control_characters(value):
        raise ValueError("存档时间无效")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("存档时间无效") from error
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).isoformat()


def _dump(value: Mapping[str, Any], label: str) -> str:
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError(label + "无法序列化为 JSON") from error
    return encoded


def _validate_id(value: Any) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise ValueError("存档标识无效")
    return value


def _validate_sha256(value: Any) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("存档哈希无效")
    return value.lower()


class SavesRepository:
    """SQLite 存档仓储。

    传入 connection 的调用方必须已开启写事务；仓储不会自行提交或回滚。
    """

    SAVE_STATUSES = frozenset({"pending", "reading", "ready", "error", "cancelled"})

    def __init__(self, database: Database):
        self.database = database

    @contextmanager
    def _read(self, connection: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
        if connection is not None:
            yield connection
        else:
            with closing(self.database.connect()) as owned:
                yield owned

    @contextmanager
    def _write(self, connection: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
        if connection is not None:
            yield connection
        else:
            with self.database.transaction() as owned:
                yield owned

    def add(
        self,
        value: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError("存档必须是对象")
        save_id = value.get("id")
        if save_id is None:
            save_id = secrets.token_hex(8)
        save_id = _validate_id(save_id)
        source_path = _validate_text(value.get("source_path"), "存档路径", MAX_SOURCE_PATH)
        source_sha256 = _validate_sha256(value.get("source_sha256"))
        status = value.get("status", "pending")
        self._validate_status(status)
        stage = value.get("stage")
        if stage is not None:
            stage = _validate_text(stage, "存档阶段", MAX_STAGE)
        metadata = value.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("存档元数据必须是对象")
        metadata_json = _dump(metadata, "存档元数据")
        created_at = value.get("created_at")
        created_at = datetime.now(UTC).isoformat() if created_at is None else _validate_stamp(created_at)
        updated_at = value.get("updated_at")
        updated_at = datetime.now(UTC).isoformat() if updated_at is None else _validate_stamp(updated_at)
        with self._write(connection) as active:
            if active.execute("SELECT id FROM saves WHERE id=?", (save_id,)).fetchone() is not None:
                raise ValueError("存档已存在")
            duplicate_sha = active.execute(
                "SELECT id FROM saves WHERE source_sha256=?", (source_sha256,)
            ).fetchone()
            if duplicate_sha is not None:
                raise ValueError("存档内容重复")
            try:
                active.execute(
                    "INSERT INTO saves(id, source_path, source_sha256, status, stage, metadata_json, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        save_id,
                        source_path,
                        source_sha256,
                        status,
                        stage,
                        metadata_json,
                        created_at,
                        updated_at,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise self._duplicate_error(error) from error
        return self._entry(
            save_id,
            source_path,
            source_sha256,
            status,
            stage,
            metadata_json,
            created_at,
            updated_at,
        )

    def get(
        self,
        save_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        _validate_id(save_id)
        with self._read(connection) as active:
            row = active.execute(f"SELECT {SAVE_COLUMNS} FROM saves WHERE id=?", (save_id,)).fetchone()
        return None if row is None else self._row(row)

    def list(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("存档分页大小无效")
        if type(offset) is not int or offset < 0:
            raise ValueError("存档分页偏移无效")
        if status is not None:
            self._validate_status(status)
        statement = f"SELECT {SAVE_COLUMNS} FROM saves"
        parameters: list[Any] = []
        if status is not None:
            statement += " WHERE status=?"
            parameters.append(status)
        statement += " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
        with self._read(connection) as active:
            rows = active.execute(statement, parameters).fetchall()
        return [self._row(row) for row in rows]

    def count(self, status: str | None = None, connection: sqlite3.Connection | None = None) -> int:
        if status is not None:
            self._validate_status(status)
        statement = "SELECT COUNT(*) FROM saves"
        parameters: list[Any] = []
        if status is not None:
            statement += " WHERE status=?"
            parameters.append(status)
        with self._read(connection) as active:
            row = active.execute(statement, parameters).fetchone()
        return int(row[0])

    def update(
        self,
        save_id: str,
        changes: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        _validate_id(save_id)
        if not isinstance(changes, Mapping) or not changes:
            raise ValueError("存档更新字段无效")
        if set(changes) - {"status", "stage", "metadata"}:
            raise ValueError("存档更新字段无效")
        prepared: dict[str, Any] = {}
        if "status" in changes:
            self._validate_status(changes["status"])
            prepared["status"] = changes["status"]
        if "stage" in changes:
            stage = changes["stage"]
            prepared["stage"] = None if stage is None else _validate_text(stage, "存档阶段", MAX_STAGE)
        if "metadata" in changes:
            metadata = changes["metadata"]
            if not isinstance(metadata, Mapping):
                raise ValueError("存档元数据必须是对象")
            prepared["metadata_json"] = _dump(metadata, "存档元数据")
        with self._write(connection) as active:
            row = active.execute(f"SELECT {SAVE_COLUMNS} FROM saves WHERE id=?", (save_id,)).fetchone()
            if row is None:
                return None
            status = prepared.get("status", row["status"])
            stage = prepared["stage"] if "stage" in prepared else row["stage"]
            metadata_json = prepared.get("metadata_json", row["metadata_json"])
            updated_at = datetime.now(UTC).isoformat()
            active.execute(
                "UPDATE saves SET status=?, stage=?, metadata_json=?, updated_at=? WHERE id=?",
                (status, stage, metadata_json, updated_at, save_id),
            )
            return self._entry(
                save_id,
                row["source_path"],
                row["source_sha256"],
                status,
                stage,
                metadata_json,
                row["created_at"],
                updated_at,
            )

    def delete(
        self,
        save_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        _validate_id(save_id)
        with self._write(connection) as active:
            cursor = active.execute("DELETE FROM saves WHERE id=?", (save_id,))
            return cursor.rowcount > 0

    def set_league(
        self,
        save_id: str,
        league_key: str,
        payload: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        _validate_id(save_id)
        normalized_key = _validate_text(league_key, "联赛标识", MAX_LEAGUE_KEY)
        if not isinstance(payload, Mapping):
            raise ValueError("联赛数据必须是对象")
        payload_json = _dump(payload, "联赛数据")
        with self._write(connection) as active:
            if active.execute("SELECT id FROM saves WHERE id=?", (save_id,)).fetchone() is None:
                raise ValueError("存档不存在")
            try:
                active.execute(
                    "INSERT INTO save_leagues(save_id, league_key, payload_json) VALUES (?, ?, ?) "
                    "ON CONFLICT(save_id, league_key) DO UPDATE SET payload_json=excluded.payload_json",
                    (save_id, normalized_key, payload_json),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("存档不存在") from error
        return {
            "save_id": save_id,
            "league_key": normalized_key,
            "payload": json.loads(payload_json),
        }

    def leagues(
        self,
        save_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        _validate_id(save_id)
        with self._read(connection) as active:
            rows = active.execute(
                "SELECT save_id, league_key, payload_json FROM save_leagues "
                "WHERE save_id=? ORDER BY league_key ASC",
                (save_id,),
            ).fetchall()
        return [
            {
                "save_id": row["save_id"],
                "league_key": row["league_key"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def remove_league(
        self,
        save_id: str,
        league_key: str,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        _validate_id(save_id)
        normalized_key = _validate_text(league_key, "联赛标识", MAX_LEAGUE_KEY)
        with self._write(connection) as active:
            cursor = active.execute(
                "DELETE FROM save_leagues WHERE save_id=? AND league_key=?",
                (save_id, normalized_key),
            )
            return cursor.rowcount > 0

    def set_club(
        self,
        save_id: str,
        club_uid: int,
        payload: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        _validate_id(save_id)
        if type(club_uid) is not int or not club_uid > 0:
            raise ValueError("俱乐部标识无效")
        if not isinstance(payload, Mapping):
            raise ValueError("俱乐部数据必须是对象")
        payload_json = _dump(payload, "俱乐部数据")
        with self._write(connection) as active:
            if active.execute("SELECT id FROM saves WHERE id=?", (save_id,)).fetchone() is None:
                raise ValueError("存档不存在")
            try:
                active.execute(
                    "INSERT INTO save_clubs(save_id, club_uid, payload_json) VALUES (?, ?, ?) "
                    "ON CONFLICT(save_id, club_uid) DO UPDATE SET payload_json=excluded.payload_json",
                    (save_id, club_uid, payload_json),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("存档不存在") from error
        return {
            "save_id": save_id,
            "club_uid": club_uid,
            "payload": json.loads(payload_json),
        }

    def clubs(
        self,
        save_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        _validate_id(save_id)
        with self._read(connection) as active:
            rows = active.execute(
                "SELECT save_id, club_uid, payload_json FROM save_clubs "
                "WHERE save_id=? ORDER BY club_uid ASC",
                (save_id,),
            ).fetchall()
        return [
            {
                "save_id": row["save_id"],
                "club_uid": row["club_uid"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def replace_children(
        self,
        save_id: str,
        leagues: Mapping[str, Mapping],
        clubs: Mapping[int, Mapping],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, int]:
        _validate_id(save_id)
        if not isinstance(leagues, Mapping):
            raise ValueError("联赛数据必须是对象")
        if not isinstance(clubs, Mapping):
            raise ValueError("俱乐部数据必须是对象")
        league_items = list(leagues.items())
        club_items = list(clubs.items())
        with self._write(connection) as active:
            if active.execute("SELECT id FROM saves WHERE id=?", (save_id,)).fetchone() is None:
                raise ValueError("存档不存在")
            league_rows = []
            for key, payload in league_items:
                normalized_key = _validate_text(key, "联赛标识", MAX_LEAGUE_KEY)
                if not isinstance(payload, Mapping):
                    raise ValueError("联赛数据必须是对象")
                league_rows.append((save_id, normalized_key, _dump(payload, "联赛数据")))
            club_rows = []
            for club_uid, payload in club_items:
                if type(club_uid) is not int or not club_uid > 0:
                    raise ValueError("俱乐部标识无效")
                if not isinstance(payload, Mapping):
                    raise ValueError("俱乐部数据必须是对象")
                club_rows.append((save_id, club_uid, _dump(payload, "俱乐部数据")))
            active.execute("DELETE FROM save_leagues WHERE save_id=?", (save_id,))
            active.execute("DELETE FROM save_clubs WHERE save_id=?", (save_id,))
            if league_rows:
                active.executemany(
                    "INSERT INTO save_leagues(save_id, league_key, payload_json) VALUES (?, ?, ?)",
                    league_rows,
                )
            if club_rows:
                active.executemany(
                    "INSERT INTO save_clubs(save_id, club_uid, payload_json) VALUES (?, ?, ?)",
                    club_rows,
                )
        return {"leagues": len(league_rows), "clubs": len(club_rows)}

    @classmethod
    def _validate_status(cls, value: Any) -> None:
        if not isinstance(value, str) or value not in cls.SAVE_STATUSES:
            raise ValueError("存档状态无效")

    @staticmethod
    def _duplicate_error(error: sqlite3.IntegrityError) -> ValueError:
        message = str(error)
        if "saves.id" in message:
            return ValueError("存档已存在")
        if "saves.source_sha256" in message:
            return ValueError("存档内容重复")
        return ValueError("存档写入失败")

    @staticmethod
    def _entry(
        save_id: str,
        source_path: str,
        source_sha256: str,
        status: str,
        stage: str | None,
        metadata_json: str,
        created_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        return {
            "id": save_id,
            "source_path": source_path,
            "source_sha256": source_sha256,
            "status": status,
            "stage": stage,
            "metadata": json.loads(metadata_json),
            "created_at": created_at,
            "updated_at": updated_at,
        }

    @classmethod
    def _row(cls, row: sqlite3.Row) -> dict[str, Any]:
        return cls._entry(
            row["id"],
            row["source_path"],
            row["source_sha256"],
            row["status"],
            row["stage"],
            row["metadata_json"],
            row["created_at"],
            row["updated_at"],
        )
