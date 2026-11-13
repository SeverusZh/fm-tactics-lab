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


class DraftRepository:
    @staticmethod
    def _validate_name(name: Any) -> str:
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 80
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
        ):
            raise ValueError("草案名称无效")
        try:
            name.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("草案名称无效") from error
        return name.strip()

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
        name, scenario_json, source_json, entry_id, stamp = self._parts(value, created_at)
        with self._connection(connection) as (active, owned):
            active.execute(
                "INSERT INTO drafts(id, name, scenario_json, source_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entry_id, name, scenario_json, source_json, stamp, stamp),
            )
            if owned:
                active.commit()
        return self._entry(entry_id, name, scenario_json, source_json, stamp, stamp)

    def get(
        self,
        entry_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        PoolRepository._validate_id(entry_id)
        with self._connection(connection) as (active, _):
            row = active.execute(
                "SELECT id, name, scenario_json, source_json, created_at, updated_at FROM drafts WHERE id=?",
                (entry_id,),
            ).fetchone()
        return None if row is None else self._row(row)

    def list(self, connection: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        with self._connection(connection) as (active, _):
            rows = active.execute(
                "SELECT id, name, scenario_json, source_json, created_at, updated_at "
                "FROM drafts ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [self._row(row) for row in rows]

    def update(
        self,
        entry_id: str,
        changes: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        PoolRepository._validate_id(entry_id)
        if not isinstance(changes, Mapping):
            raise ValueError("草案更新必须是对象")
        allowed = {"name", "scenario", "source"}
        if not changes or set(changes) - allowed:
            raise ValueError("草案更新字段无效")
        with self._connection(connection) as (active, owned):
            if owned:
                active.execute("BEGIN IMMEDIATE")
            row = active.execute(
                "SELECT id, name, scenario_json, source_json, created_at, updated_at FROM drafts WHERE id=?",
                (entry_id,),
            ).fetchone()
            if row is None:
                if owned:
                    active.rollback()
                return None
            current = self._row(row)
            name = self._validate_name(changes.get("name", current["name"]))
            scenario = changes.get("scenario", current["scenario"])
            source = changes.get("source", current["source"])
            if not isinstance(scenario, Mapping):
                raise ValueError("草案场景必须是对象")
            if not isinstance(source, Mapping):
                raise ValueError("草案来源必须是对象")
            scenario_json = PoolRepository._dump(scenario, "草案场景")
            source_json = PoolRepository._dump(source, "草案来源")
            stamp = datetime.now(UTC).isoformat()
            cursor = active.execute(
                "UPDATE drafts SET name=?, scenario_json=?, source_json=?, updated_at=? WHERE id=?",
                (name, scenario_json, source_json, stamp, entry_id),
            )
            if cursor.rowcount == 0:
                if owned:
                    active.rollback()
                return None
            if owned:
                active.commit()
        return self._entry(entry_id, name, scenario_json, source_json, current["created_at"], stamp)

    def delete(
        self,
        entry_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        PoolRepository._validate_id(entry_id)
        with self._connection(connection) as (active, owned):
            cursor = active.execute("DELETE FROM drafts WHERE id=?", (entry_id,))
            if owned:
                active.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _parts(value: Mapping[str, Any], created_at: str | None):
        if not isinstance(value, Mapping):
            raise ValueError("草案必须是对象")
        name = DraftRepository._validate_name(value.get("name"))
        scenario = value.get("scenario")
        source = value.get("source", {})
        if not isinstance(scenario, Mapping):
            raise ValueError("草案场景必须是对象")
        if not isinstance(source, Mapping):
            raise ValueError("草案来源必须是对象")
        entry_id = value.get("id")
        if entry_id is None:
            entry_id = secrets.token_hex(8)
        PoolRepository._validate_id(entry_id)
        stamp = datetime.now(UTC).isoformat() if created_at is None else created_at
        if (
            not isinstance(stamp, str)
            or not 1 <= len(stamp) <= 64
            or any(ord(c) < 32 or ord(c) == 127 for c in stamp)
        ):
            raise ValueError("草案时间无效")
        try:
            datetime.fromisoformat(stamp)
        except ValueError as error:
            raise ValueError("草案时间无效") from error
        return (
            name,
            PoolRepository._dump(scenario, "草案场景"),
            PoolRepository._dump(source, "草案来源"),
            entry_id,
            stamp,
        )

    @staticmethod
    def _entry(entry_id, name, scenario_json, source_json, created_at, updated_at):
        return {
            "id": entry_id,
            "name": name,
            "scenario": json.loads(scenario_json),
            "source": json.loads(source_json),
            "created_at": created_at,
            "updated_at": updated_at,
        }

    @classmethod
    def _row(cls, row: sqlite3.Row) -> dict[str, Any]:
        return cls._entry(
            row["id"],
            row["name"],
            row["scenario_json"],
            row["source_json"],
            row["created_at"],
            row["updated_at"],
        )


class JobRepository:
    """SQLite job storage.

    Caller-provided connections must already hold a write transaction when used for
    update() or add_run(); otherwise the read-modify-write is not atomic.
    """

    STATUSES = frozenset({"queued", "running", "completed", "error", "cancelled", "interrupted"})

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
        normalized = self._validate_job(value)
        with self._connection(connection) as (active, owned):
            active.execute(
                "INSERT INTO jobs(id, kind, status, name, config_json, summary_json, workers, "
                "total, completed, created_at, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                normalized,
            )
            if owned:
                active.commit()
        return self._job_from_tuple(normalized)

    def get(
        self,
        job_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        PoolRepository._validate_id(job_id)
        with self._connection(connection) as (active, _):
            row = active.execute(
                "SELECT id, kind, status, name, config_json, summary_json, workers, total, "
                "completed, created_at, started_at, finished_at FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        return None if row is None else self._row(row)

    def list(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("任务分页大小无效")
        if type(offset) is not int or offset < 0:
            raise ValueError("任务分页偏移无效")
        if status is not None and (not isinstance(status, str) or status not in self.STATUSES):
            raise ValueError("任务状态无效")
        statement = (
            "SELECT id, kind, status, name, config_json, summary_json, workers, total, "
            "completed, created_at, started_at, finished_at FROM jobs"
        )
        parameters: list[Any] = []
        if status is not None:
            statement += " WHERE status=?"
            parameters.append(status)
        statement += " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
        parameters.extend([limit, offset])
        with self._connection(connection) as (active, _):
            rows = active.execute(statement, parameters).fetchall()
        return [self._row(row) for row in rows]

    def count(self, status: str | None = None, connection: sqlite3.Connection | None = None) -> int:
        if status is not None and (not isinstance(status, str) or status not in self.STATUSES):
            raise ValueError("任务状态无效")
        statement = "SELECT COUNT(*) FROM jobs"
        parameters: list[Any] = []
        if status is not None:
            statement += " WHERE status=?"
            parameters.append(status)
        with self._connection(connection) as (active, _):
            row = active.execute(statement, parameters).fetchone()
        return int(row[0])

    def update(
        self,
        job_id: str,
        changes: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        PoolRepository._validate_id(job_id)
        if not isinstance(changes, Mapping) or not changes:
            raise ValueError("任务更新字段无效")
        allowed = {
            "status",
            "name",
            "config",
            "summary",
            "workers",
            "total",
            "completed",
            "started_at",
            "finished_at",
        }
        if set(changes) - allowed:
            raise ValueError("任务更新字段无效")
        with self._connection(connection) as (active, owned):
            if owned:
                active.execute("BEGIN IMMEDIATE")
            row = active.execute(
                "SELECT id, kind, status, name, config_json, summary_json, workers, total, "
                "completed, created_at, started_at, finished_at FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                if owned:
                    active.rollback()
                return None
            current = self._row(row)
            normalized = self._validate_job({**current, **dict(changes)})
            cursor = active.execute(
                "UPDATE jobs SET status=?, name=?, config_json=?, summary_json=?, workers=?, "
                "total=?, completed=?, created_at=?, started_at=?, finished_at=? WHERE id=?",
                (
                    normalized[2],
                    normalized[3],
                    normalized[4],
                    normalized[5],
                    normalized[6],
                    normalized[7],
                    normalized[8],
                    normalized[9],
                    normalized[10],
                    normalized[11],
                    job_id,
                ),
            )
            if cursor.rowcount == 0:
                if owned:
                    active.rollback()
                return None
            if owned:
                active.commit()
        return self._job_from_tuple(normalized)

    def delete(
        self,
        job_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        PoolRepository._validate_id(job_id)
        with self._connection(connection) as (active, owned):
            cursor = active.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            if owned:
                active.commit()
            return cursor.rowcount > 0

    def add_run(
        self,
        job_id: str,
        value: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        PoolRepository._validate_id(job_id)
        with self._connection(connection) as (active, owned):
            if owned:
                active.execute("BEGIN IMMEDIATE")
            if not isinstance(value, Mapping):
                raise ValueError("任务比赛记录必须是对象")
            sequence = value.get("sequence")
            if sequence is None:
                sequence = active.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM job_runs WHERE job_id=?",
                    (job_id,),
                ).fetchone()[0]
            if type(sequence) is not int or not 1 <= sequence <= 1_000_000:
                raise ValueError("比赛序号无效")
            variant = value.get("variant")
            if (
                not isinstance(variant, str)
                or not 1 <= len(variant) <= 64
                or any(ord(c) < 32 or ord(c) == 127 for c in variant)
            ):
                raise ValueError("比赛变体无效")
            seed = value.get("seed")
            if type(seed) is not int or not 0 <= seed <= 0xFFFFFFFF:
                raise ValueError("比赛种子无效")
            score_home = value.get("score_home")
            score_away = value.get("score_away")
            if (score_home is None) != (score_away is None):
                raise ValueError("比赛比分必须同时提供或同时为空")
            for score in (score_home, score_away):
                if score is not None and (type(score) is not int or score < 0):
                    raise ValueError("比赛比分无效")
            verified = value.get("verified", False)
            if type(verified) is not bool:
                raise ValueError("比赛核验标记无效")
            stats = value.get("stats", {})
            events = value.get("events")
            log_path = value.get("log_path")
            if not isinstance(stats, Mapping):
                raise ValueError("比赛统计必须是对象")
            if events is not None and not isinstance(events, Mapping):
                raise ValueError("比赛事件必须是对象")
            if log_path is not None and (not isinstance(log_path, str) or len(log_path) > 512):
                raise ValueError("比赛日志路径无效")
            stats_json = PoolRepository._dump(stats, "比赛统计")
            events_json = None if events is None else PoolRepository._dump(events, "比赛事件")
            stamp = datetime.now(UTC).isoformat()
            active.execute(
                "INSERT INTO job_runs(job_id, sequence, variant, seed, score_home, score_away, "
                "verified, stats_json, events_json, log_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    sequence,
                    variant,
                    seed,
                    score_home,
                    score_away,
                    int(verified),
                    stats_json,
                    events_json,
                    log_path,
                    stamp,
                ),
            )
            if owned:
                active.commit()
        return self._run_entry(
            job_id,
            sequence,
            variant,
            seed,
            score_home,
            score_away,
            verified,
            stats_json,
            events_json,
            log_path,
            stamp,
        )

    def runs(
        self,
        job_id: str,
        limit: int = 50,
        offset: int = 0,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        PoolRepository._validate_id(job_id)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("比赛分页大小无效")
        if type(offset) is not int or offset < 0:
            raise ValueError("比赛分页偏移无效")
        with self._connection(connection) as (active, _):
            rows = active.execute(
                "SELECT job_id, sequence, variant, seed, score_home, score_away, verified, "
                "stats_json, events_json, log_path, created_at FROM job_runs "
                "WHERE job_id=? ORDER BY sequence LIMIT ? OFFSET ?",
                (job_id, limit, offset),
            ).fetchall()
        return [self._run_row(row) for row in rows]

    def run_count(self, job_id: str, connection: sqlite3.Connection | None = None) -> int:
        PoolRepository._validate_id(job_id)
        with self._connection(connection) as (active, _):
            row = active.execute("SELECT COUNT(*) FROM job_runs WHERE job_id=?", (job_id,)).fetchone()
        return int(row[0])

    def get_run(
        self,
        job_id: str,
        sequence: int,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        PoolRepository._validate_id(job_id)
        if type(sequence) is not int or sequence < 1:
            raise ValueError("比赛序号无效")
        with self._connection(connection) as (active, _):
            row = active.execute(
                "SELECT job_id, sequence, variant, seed, score_home, score_away, verified, "
                "stats_json, events_json, log_path, created_at FROM job_runs "
                "WHERE job_id=? AND sequence=?",
                (job_id, sequence),
            ).fetchone()
        return None if row is None else self._run_row(row)

    @classmethod
    def _validate_job(cls, value: Mapping[str, Any]) -> tuple:
        if not isinstance(value, Mapping):
            raise ValueError("任务必须是对象")
        job_id = value.get("id")
        if job_id is None:
            job_id = secrets.token_hex(8)
        PoolRepository._validate_id(job_id)
        kind = value.get("kind")
        if (
            not isinstance(kind, str)
            or not 1 <= len(kind) <= 64
            or any(ord(c) < 32 or ord(c) == 127 for c in kind)
        ):
            raise ValueError("任务类型无效")
        status = value.get("status")
        if not isinstance(status, str) or status not in cls.STATUSES:
            raise ValueError("任务状态无效")
        name = value.get("name")
        if name is not None:
            if (
                not isinstance(name, str)
                or not 1 <= len(name.strip()) <= 100
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
            ):
                raise ValueError("任务名称无效")
            try:
                name.encode("utf-8")
            except UnicodeEncodeError as error:
                raise ValueError("任务名称无效") from error
            name = name.strip()
        config = value.get("config", {})
        summary = value.get("summary", {})
        if not isinstance(config, Mapping) or not isinstance(summary, Mapping):
            raise ValueError("任务配置必须是对象")
        workers = value.get("workers", 1)
        if type(workers) is not int or not 1 <= workers <= 256:
            raise ValueError("任务并行数无效")
        total = value.get("total", 0)
        completed = value.get("completed", 0)
        if type(total) is not int or total < 0 or type(completed) is not int or completed < 0:
            raise ValueError("任务进度无效")
        if completed > total:
            raise ValueError("任务进度无效")
        created_at = value.get("created_at")
        if created_at is None:
            created_at = datetime.now(UTC).isoformat()
        started_at = value.get("started_at")
        finished_at = value.get("finished_at")
        for stamp in (created_at, started_at, finished_at):
            if stamp is None:
                continue
            if (
                not isinstance(stamp, str)
                or not 1 <= len(stamp) <= 64
                or any(ord(c) < 32 or ord(c) == 127 for c in stamp)
            ):
                raise ValueError("任务时间无效")
            try:
                datetime.fromisoformat(stamp)
            except ValueError as error:
                raise ValueError("任务时间无效") from error
        return (
            job_id,
            kind,
            status,
            name,
            PoolRepository._dump(config, "任务配置"),
            PoolRepository._dump(summary, "任务摘要"),
            workers,
            total,
            completed,
            created_at,
            started_at,
            finished_at,
        )

    @staticmethod
    def _job_from_tuple(value: tuple) -> dict[str, Any]:
        return {
            "id": value[0],
            "kind": value[1],
            "status": value[2],
            "name": value[3],
            "config": json.loads(value[4]),
            "summary": json.loads(value[5]),
            "workers": value[6],
            "total": value[7],
            "completed": value[8],
            "created_at": value[9],
            "started_at": value[10],
            "finished_at": value[11],
        }

    @classmethod
    def _row(cls, row: sqlite3.Row) -> dict[str, Any]:
        return cls._job_from_tuple(tuple(row))

    @staticmethod
    def _run_entry(
        job_id, sequence, variant, seed, home, away, verified, stats_json, events_json, log_path, created_at
    ):
        return {
            "job_id": job_id,
            "sequence": sequence,
            "variant": variant,
            "seed": seed,
            "score": None if home is None or away is None else [home, away],
            "verified": bool(verified),
            "stats": json.loads(stats_json),
            "events": None if events_json is None else json.loads(events_json),
            "log_path": log_path,
            "created_at": created_at,
        }

    @classmethod
    def _run_row(cls, row: sqlite3.Row) -> dict[str, Any]:
        return cls._run_entry(
            row["job_id"],
            row["sequence"],
            row["variant"],
            row["seed"],
            row["score_home"],
            row["score_away"],
            row["verified"],
            row["stats_json"],
            row["events_json"],
            row["log_path"],
            row["created_at"],
        )
