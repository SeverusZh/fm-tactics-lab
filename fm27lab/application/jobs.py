"""Job application service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fm27lab.adapters.storage_sqlite.repositories import JobRepository


class JobService:
    TRANSITIONS: dict[str, set[str]] = {
        "queued": {"running", "cancelled", "error"},
        "running": {"completed", "error", "cancelled", "interrupted"},
        "interrupted": {"queued", "running", "cancelled"},
        "completed": set(),
        "error": set(),
        "cancelled": set(),
    }

    def __init__(self, repository: JobRepository):
        self.repository = repository

    def create(
        self,
        kind: str,
        name: str | None = None,
        config: Mapping[str, Any] | None = None,
        workers: int = 1,
        total: int = 0,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        return self.repository.add(
            {
                "id": job_id,
                "kind": kind,
                "status": "queued",
                "name": name,
                "config": {} if config is None else config,
                "workers": workers,
                "total": total,
            }
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.repository.get(job_id)

    def list(self, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("limit 必须为 1–256 的整数")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset 必须为非负整数")
        items = self.repository.list(status=status, limit=limit, offset=offset)
        total = self.repository.count(status=status)
        next_offset = offset + len(items)
        return {
            "items": items,
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
        }

    def update(self, job_id: str, changes: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(changes, Mapping) or not changes:
            raise ValueError("任务更新字段无效")
        if set(changes) - {"status", "completed", "summary", "name"}:
            raise ValueError("任务更新字段无效")
        with self.repository.database.transaction() as connection:
            current = self.repository.get(job_id, connection=connection)
            if current is None:
                return None
            target = dict(changes)
            if "status" in target:
                status = target["status"]
                if not isinstance(status, str) or status not in self.TRANSITIONS[current["status"]]:
                    raise ValueError("任务状态不允许该操作")
                if status == "running" and current["started_at"] is None:
                    target["started_at"] = datetime.now(UTC).isoformat()
                if status in {"completed", "error", "cancelled"}:
                    target.setdefault("finished_at", datetime.now(UTC).isoformat())
            if "completed" in target:
                completed = target["completed"]
                if type(completed) is not int or not 0 <= completed <= current["total"]:
                    raise ValueError("任务进度无效")
            return self.repository.update(job_id, target, connection=connection)

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        return self.update(job_id, {"status": "cancelled"})

    def append_run(self, job_id: str, run: Mapping[str, Any]) -> dict[str, Any]:
        with self.repository.database.transaction() as connection:
            current = self.repository.get(job_id, connection=connection)
            if current is None or current["status"] != "running":
                raise ValueError("任务状态不允许写入比赛记录")
            completed = current["completed"] + 1
            if completed > current["total"]:
                raise ValueError("任务进度无效")
            record = self.repository.add_run(job_id, run, connection=connection)
            self.repository.update(job_id, {"completed": completed}, connection=connection)
            return record

    def runs(self, job_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        items = self.repository.runs(job_id, limit=limit, offset=offset)
        total = self.repository.run_count(job_id)
        next_offset = offset + len(items)
        return {
            "items": items,
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
        }

    def delete(self, job_id: str) -> bool:
        return self.repository.delete(job_id)

    def batch_delete(self, ids: Sequence[str]) -> dict[str, Any]:
        deleted: list[str] = []
        failed: list[dict[str, str]] = []
        for job_id in ids:
            # 状态判定与删除共用 BEGIN IMMEDIATE 事务，避免判定后任务被恢复为 queued/running 仍被删除。
            with self.repository.database.transaction() as connection:
                current = self.repository.get(job_id, connection=connection)
                if current is None:
                    failed.append({"id": job_id, "error": "任务不存在"})
                    continue
                if current["status"] in {"queued", "running"}:
                    failed.append({"id": job_id, "error": "任务正在运行或排队"})
                    continue
                if not self.repository.delete(job_id, connection=connection):
                    failed.append({"id": job_id, "error": "任务不存在"})
                    continue
            deleted.append(job_id)
        return {"deleted": deleted, "failed": failed}
