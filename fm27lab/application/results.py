"""Results application service."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.domain.compare import paired_deltas, pool_pairing
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


def _select_runs(runs: Sequence[Mapping[str, Any]], variant: str) -> list[Mapping[str, Any]]:
    selected = [run for run in runs if run.get("variant") == variant]
    return selected or list(runs)


def _pool_entry_index(raw: Any, entry_count: int) -> int:
    if type(raw) is int:
        return raw
    if isinstance(raw, Mapping):
        index = raw.get("index")
    else:
        raise ValueError("客队战术记录格式无效")
    if type(index) is not int or not 0 <= index < entry_count:
        raise ValueError(f"客队战术序号必须为 0–{entry_count - 1} 的整数")
    return index


def _pool_view(
    job: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    pool = _job_pool_config(job)
    if pool is None:
        return None
    enabled = pool.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("客队战术池开关无效")
    entries = pool.get("entries")
    if not isinstance(entries, list):
        raise ValueError("客队战术池条目必须是列表")
    if not enabled or not entries:
        return None
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
    draws: dict[int, int] = {}
    for run in runs:
        stats = run.get("stats")
        if not isinstance(stats, Mapping):
            continue
        raw = stats.get("tactic_pool_entry")
        if raw is None:
            continue
        index = _pool_entry_index(raw, len(entries))
        seed = run.get("seed")
        if type(seed) is not int:
            raise ValueError("比赛记录缺少整数种子")
        if seed in draws and draws[seed] != index:
            raise ValueError("同种子对照的客队战术不一致")
        draws[seed] = index
    return {
        "mode": summary["mode"],
        "rounds": summary["rounds"],
        "players": summary["players"],
        "entries": [
            {
                "index": entry["index"],
                "name": entry["name"],
                "weight": entry["weight"],
                "roster": entry["roster"],
            }
            for entry in summary["entries"]
        ],
        "draws": draws,
    }


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

    def compare(
        self,
        baseline_job_id: str,
        candidate_job_ids: Sequence[str],
        *,
        variant: str = "B",
        side: int = 0,
        reps: int = 2000,
    ) -> dict[str, Any] | None:
        if variant not in ("A", "B"):
            raise ValueError("variant 必须为 A 或 B")
        if isinstance(candidate_job_ids, (str, bytes)):
            raise ValueError("候选任务不能为空")
        try:
            candidates = list(candidate_job_ids)
        except TypeError:
            raise ValueError("候选任务不能为空") from None
        if not candidates:
            raise ValueError("候选任务不能为空")
        if len(candidates) > 32:
            raise ValueError("候选任务最多 32 个")
        if len(set(candidates)) != len(candidates):
            raise ValueError("候选任务不能重复")
        if baseline_job_id in candidates:
            raise ValueError("候选任务不能包含基线任务")
        if type(side) is not int or side not in (0, 1):
            raise ValueError("side 必须为 0 或 1")
        if type(reps) is not int or not 1 <= reps <= 20000:
            raise ValueError("reps 必须为 1–20000 的整数")
        baseline_job = self.repository.get(baseline_job_id)
        if baseline_job is None:
            return None
        candidate_jobs: list[dict[str, Any]] = []
        for job_id in candidates:
            job = self.repository.get(job_id)
            if job is None:
                return None
            candidate_jobs.append(job)
        baseline_runs = self.all_runs(baseline_job_id)
        baseline_completed = _complete_runs(_select_runs(baseline_runs, variant))
        baseline_by_seed = {
            run["seed"]: run
            for run in baseline_completed
            if type(run.get("seed")) is int
        }
        baseline_view = _pool_view(baseline_job, baseline_runs)
        results: list[dict[str, Any]] = []
        for job_id, job in zip(candidates, candidate_jobs, strict=True):
            candidate_runs = self.all_runs(job_id)
            candidate_completed = _complete_runs(_select_runs(candidate_runs, variant))
            candidate_by_seed = {
                run["seed"]: run
                for run in candidate_completed
                if type(run.get("seed")) is int
            }
            candidate_view = _pool_view(job, candidate_runs)
            shared = sorted(set(baseline_by_seed) & set(candidate_by_seed))
            if not shared:
                comparable, reason, pairing = False, "没有同种子的已完成比赛", None
                paired = None
            elif baseline_view is None and candidate_view is None:
                comparable, reason, pairing = True, None, None
                paired = paired_deltas(
                    baseline_by_seed, candidate_by_seed, side, reps=reps
                )
            else:
                comparable, reason, pairing = pool_pairing(
                    baseline_view, candidate_view, shared
                )
                paired = (
                    paired_deltas(baseline_by_seed, candidate_by_seed, side, reps=reps)
                    if comparable
                    else None
                )
            results.append(
                {
                    "job_id": job_id,
                    "name": job.get("name"),
                    "metrics": summarize_runs(candidate_completed, side),
                    "tactic_pool": self.pool_summary(job_id),
                    "comparable": comparable,
                    "reason": reason,
                    "pairing": pairing,
                    "paired": paired,
                }
            )
        return {
            "baseline": {
                "job_id": baseline_job_id,
                "name": baseline_job.get("name"),
                "metrics": summarize_runs(baseline_completed, side),
                "tactic_pool": self.pool_summary(baseline_job_id),
            },
            "variant": variant,
            "side": side,
            "candidates": results,
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
