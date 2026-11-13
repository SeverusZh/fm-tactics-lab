"""Results application service."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.domain.pool import completed_draw_counts
from fm27lab.domain.pool import summary as summarize_pool
from fm27lab.domain.results import paired_goal_difference, summarize_runs

RUN_PAGE_SIZE = 200
MATCH_PAGE_SIZE = 200
CSV_COLUMNS = (
    "job_id",
    "sequence",
    "variant",
    "seed",
    "score_home",
    "score_away",
    "verified",
    "created_at",
    "stats_json",
    "events_json",
)


def _json_column(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _domain_run(run: Mapping[str, Any]) -> dict[str, Any]:
    score = run.get("score")
    adapted: dict[str, Any] = {
        "seed": run.get("seed"),
        "variant": run.get("variant"),
        "score": score,
    }
    if score is not None:
        adapted["result"] = {"score": score}
    stats = run.get("stats")
    if isinstance(stats, Mapping):
        adapted["statistics"] = stats
    return adapted


def _complete_runs(runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_domain_run(run) for run in runs if run.get("score") is not None]


def _disabled_pool_summary(entry_count: int = 0) -> dict[str, Any]:
    return {"enabled": False, "entry_count": entry_count, "mode": None, "players": None, "draws": {}}


def _job_pool_config(job: Mapping[str, Any]) -> Mapping[str, Any] | None:
    config = job.get("config")
    if config is None:
        return None
    if not isinstance(config, Mapping):
        raise ValueError("任务配置必须是对象")
    for key in ("away_tactic_pool", "tactic_pool"):
        value = config.get(key)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            raise ValueError("客队战术池配置必须是对象")
        return value
    return None


class ResultsService:
    def __init__(self, repository: JobRepository):
        self.repository = repository

    def all_runs(self, job_id: str) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.repository.runs(job_id, limit=RUN_PAGE_SIZE, offset=offset)
            runs.extend(page)
            if len(page) < RUN_PAGE_SIZE:
                return runs
            offset += len(page)

    def summary(self, job_id: str, side: int = 0) -> dict[str, Any] | None:
        job = self.repository.get(job_id)
        if job is None:
            return None
        runs = _complete_runs(self.all_runs(job_id))
        return {
            "job": job,
            "metrics": summarize_runs(runs, side),
            "paired": paired_goal_difference(runs, side),
        }

    def pool_summary(self, job_id: str) -> dict[str, Any] | None:
        job = self.repository.get(job_id)
        if job is None:
            return None
        pool = _job_pool_config(job)
        if pool is None:
            return _disabled_pool_summary()
        enabled = pool.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError("客队战术池开关无效")
        entries = pool.get("entries")
        if not isinstance(entries, list):
            raise ValueError("客队战术池条目必须是列表")
        if not enabled:
            return _disabled_pool_summary(len(entries))
        if not entries:
            return _disabled_pool_summary()
        uniform = pool.get("uniform")
        if uniform is not None and not isinstance(uniform, Mapping):
            raise ValueError("统一属性设置必须是对象")
        summary = summarize_pool(
            entries,
            rotation=pool["rotation"] if "rotation" in pool else False,
            rounds=pool.get("rounds", 1),
            uniform=uniform,
            real=pool.get("real") or pool.get("squad_source") or False,
            enabled=True,
        )
        return {
            "enabled": True,
            "entry_count": len(entries),
            "mode": summary["mode"],
            "rounds": summary["rounds"],
            "players": summary["players"],
            "uniform": summary["uniform"],
            "entries": summary["entries"],
            "draws": self._completed_draws(job_id, len(entries)),
        }

    def _completed_draws(self, job_id: str, entry_count: int) -> dict[str, int]:
        runs: list[dict[str, Any]] = []
        for run in self.all_runs(job_id):
            stats = run.get("stats")
            if not isinstance(stats, Mapping):
                continue
            entry = stats.get("tactic_pool_entry")
            if entry is None:
                continue
            if type(entry) is int:
                entry = {"index": entry}
            runs.append({"seed": run.get("seed"), "tactic_pool_entry": entry})
        return completed_draw_counts(runs, entry_count)

    def matches(self, job_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any] | None:
        if type(limit) is not int or not 1 <= limit <= MATCH_PAGE_SIZE:
            raise ValueError("limit 必须为 1–200 的整数")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset 必须为非负整数")
        if self.repository.get(job_id) is None:
            return None
        items = self.repository.runs(job_id, limit=limit, offset=offset)
        total = self.repository.run_count(job_id)
        next_offset = offset + len(items)
        return {
            "items": items,
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
        }

    def export_csv(self, job_id: str) -> str | None:
        if self.repository.get(job_id) is None:
            return None
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(CSV_COLUMNS)
        for run in self.all_runs(job_id):
            score = run.get("score")
            events = run.get("events")
            writer.writerow(
                [
                    run["job_id"],
                    run["sequence"],
                    run["variant"],
                    run["seed"],
                    "" if score is None else score[0],
                    "" if score is None else score[1],
                    "true" if run["verified"] else "false",
                    run["created_at"],
                    _json_column(run["stats"]),
                    "" if events is None else _json_column(events),
                ]
            )
        return buffer.getvalue()
