"""Experiment submission, serial queue dispatch and cancellation service."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from fm27lab.application.events import EventPublisher
from fm27lab.application.jobs import JobService
from fm27lab.domain.concurrency import resource_check
from fm27lab.ports.engine import EnginePort, RuntimePlan

if TYPE_CHECKING:
    from fm27lab.application.experiment_material import ExperimentMaterializer

JOB_PAGE_SIZE = 256
RUN_PAGE_SIZE = 200
MAX_SEED = 0xFFFFFFFF
MAX_TOTAL_MATCHES = 10000
ALLOWED_VARIANTS = ("A", "B")
CONFIG_ERROR = "实验配置必须包含 seeds 与 variants"
MISSING_SCENARIO_ERROR = "实验配置缺少比赛场景"
SEED_ERROR = "种子必须为非空且不重复的 0–4294967295 整数列表"
VARIANT_ERROR = "变体必须为非空且不重复的 A/B 列表"
TOTAL_LIMIT_ERROR = "实验总场数不能超过 10000"
RUNNING_ERROR = "已有任务在运行"
CANCEL_ERROR = "任务状态不允许取消"
RESUME_ERROR = "任务状态不允许续跑"
ENGINE_ERROR = "引擎执行失败"
RUNTIME_PLAN_ERROR = "运行时计划无效"
RESOURCE_ERROR_MESSAGES = {
    "insufficient_memory": "可用内存低于 2 GiB，资源预检未通过",
    "insufficient_disk": "空闲磁盘不足，资源预检未通过",
}
FINAL_EVENT_NAMES = {
    "completed": "experiment.completed",
    "cancelled": "experiment.cancelled",
    "error": "experiment.error",
}


class ResourceBlocked(ValueError):
    """Raised when the resource preflight rejects a submission."""

    def __init__(self, code: str):
        super().__init__(RESOURCE_ERROR_MESSAGES.get(code, "资源预检未通过"))
        self.code = code


def _validate_seeds(value: Any) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(SEED_ERROR)
    if any(type(seed) is not int or not 0 <= seed <= MAX_SEED for seed in value):
        raise ValueError(SEED_ERROR)
    if len(set(value)) != len(value):
        raise ValueError(SEED_ERROR)
    return list(value)


def _validate_variants(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(VARIANT_ERROR)
    if any(not isinstance(variant, str) or variant not in ALLOWED_VARIANTS for variant in value):
        raise ValueError(VARIANT_ERROR)
    if len(set(value)) != len(value):
        raise ValueError(VARIANT_ERROR)
    return list(value)


def _batch_tasks(config: Any) -> list[dict[str, Any]]:
    if not isinstance(config, Mapping):
        raise ValueError(CONFIG_ERROR)
    seeds = _validate_seeds(config.get("seeds"))
    variants = _validate_variants(config.get("variants"))
    return [{"variant": variant, "seed": seed} for seed in seeds for variant in variants]


def _materialized_configs(config: Any) -> list[dict[str, Any]] | None:
    if not isinstance(config, Mapping):
        raise ValueError(CONFIG_ERROR)
    materialized = config.get("materialized")
    if not isinstance(materialized, Mapping):
        return None
    configs = materialized.get("configs")
    if not isinstance(configs, Sequence) or isinstance(configs, (str, bytes)):
        return None
    if not configs:
        return None
    tasks: list[dict[str, Any]] = []
    for item in configs:
        if not isinstance(item, Mapping):
            raise ValueError(CONFIG_ERROR)
        variant = item.get("variant")
        seed = item.get("seed")
        config_file = item.get("config_file")
        if (
            not isinstance(variant, str)
            or variant not in ALLOWED_VARIANTS
            or type(seed) is not int
            or not 0 <= seed <= MAX_SEED
            or not isinstance(config_file, str)
            or not config_file
        ):
            raise ValueError(CONFIG_ERROR)
        tasks.append({"variant": variant, "seed": seed, "config": config_file})
    return tasks


def _tasks(config: Any) -> list[dict[str, Any]]:
    materialized = _materialized_configs(config)
    if materialized is not None:
        return materialized
    if isinstance(config, Mapping) and config.get("draft_id") is not None:
        raise ValueError(MISSING_SCENARIO_ERROR)
    return _batch_tasks(config)


class ExperimentService:
    """Submit experiments, dispatch queued batches serially and cancel runs.

    One instance runs at most one batch at a time; submissions stay queued until
    start_next is called. Cancellation is carried by a per-job event so the
    dispatcher can tell an engine stop from a normal batch return.
    """

    def __init__(
        self,
        job_service: JobService,
        engine: EnginePort,
        runtime_plan: RuntimePlan | Callable[[], RuntimePlan],
        publisher: EventPublisher | None = None,
        materializer: ExperimentMaterializer | None = None,
    ):
        self._job_service = job_service
        self._engine = engine
        self._runtime_plan = runtime_plan
        self._publisher = publisher
        self._materializer = materializer
        self._lock = threading.Lock()
        self._cancel_requested: dict[str, threading.Event] = {}

    def _resolve_plan(self) -> RuntimePlan:
        plan = self._runtime_plan() if callable(self._runtime_plan) else self._runtime_plan
        if not isinstance(plan, RuntimePlan):
            raise ValueError(RUNTIME_PLAN_ERROR)
        return plan

    def submit(
        self,
        config: Mapping[str, Any],
        *,
        workers: int,
        name: str | None = None,
        cpu_count: int,
        available_memory_bytes: int,
        free_disk_bytes: int,
        allow_oversubscription: bool = False,
        draft_id: str | None = None,
        baseline_draft_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(config, Mapping):
            raise ValueError(CONFIG_ERROR)
        seeds = _validate_seeds(config.get("seeds"))
        if draft_id is None:
            variants = _validate_variants(config.get("variants"))
        else:
            variants = ["A", "B"] if baseline_draft_id is not None else ["B"]
        total = len(seeds) * len(variants)
        if total > MAX_TOTAL_MATCHES:
            raise ValueError(TOTAL_LIMIT_ERROR)
        preflight = resource_check(
            workers,
            cpu_count=cpu_count,
            available_memory_bytes=available_memory_bytes,
            free_disk_bytes=free_disk_bytes,
            allow_oversubscription=allow_oversubscription,
        )
        if not preflight["allowed"]:
            raise ResourceBlocked(preflight["code"])
        created_config: dict[str, Any] = {"seeds": seeds, "variants": variants}
        if draft_id is not None:
            created_config["draft_id"] = draft_id
            created_config["baseline_draft_id"] = baseline_draft_id
        runtime_plan = self._resolve_plan()
        with self._lock:
            job = self._job_service.create(
                kind="experiment",
                name=name,
                config=created_config,
                workers=workers,
                total=total,
            )
            summary: dict[str, Any] = {
                "provenance": dict(runtime_plan.provenance),
                "runtime_mode": runtime_plan.runtime_mode,
            }
            try:
                if self._materializer is not None and draft_id is not None:
                    job = self._materialize(
                        job,
                        summary,
                        seeds=seeds,
                        variants=variants,
                        draft_id=draft_id,
                        baseline_draft_id=baseline_draft_id,
                    )
                updated = self._job_service.update(job["id"], {"summary": summary})
                if updated is None:
                    raise ValueError("任务创建失败")
            except BaseException:
                self._discard_submission(job["id"])
                raise
            self._publish("experiment.submitted", updated)
            return updated

    def _materialize(
        self,
        job: Mapping[str, Any],
        summary: dict[str, Any],
        *,
        seeds: list[int],
        variants: list[str],
        draft_id: str,
        baseline_draft_id: str | None,
    ) -> dict[str, Any]:
        assert self._materializer is not None
        job_id = job["id"]
        materialized = self._materializer.prepare(
            job_id=job_id,
            draft_id=draft_id,
            baseline_draft_id=baseline_draft_id,
            seeds=seeds,
        )
        updated = self._job_service.set_config(
            job_id,
            {
                "seeds": list(seeds),
                "variants": list(variants),
                "draft_id": draft_id,
                "baseline_draft_id": baseline_draft_id,
                "materialized": materialized,
            },
        )
        if updated is None:
            raise ValueError("任务创建失败")
        summary["configs_count"] = len(materialized.get("configs") or ())
        pool = materialized.get("pool")
        if pool is not None:
            summary["pool"] = pool
        return updated

    def _discard_submission(self, job_id: str) -> None:
        try:
            self._job_service.delete(job_id)
        except Exception:
            pass
        if self._materializer is None:
            return
        try:
            self._materializer.discard(job_id)
        except Exception:
            pass

    def start_next(self) -> dict[str, Any] | None:
        with self._lock:
            if self._running_job() is not None:
                raise ValueError(RUNNING_ERROR)
            job = self._next_queued()
            if job is None:
                return None
            job_id = job["id"]
            running = self._job_service.update(job_id, {"status": "running"})
            if running is None:
                return None
            event = threading.Event()
            self._cancel_requested[job_id] = event
        self._publish("experiment.started", running)

        def on_result(result: Mapping[str, Any]) -> None:
            self._job_service.append_run(job_id, result)

        def on_progress(active: Sequence[Mapping[str, Any]]) -> None:
            self._record_progress(job_id, active)

        try:
            completed_pairs = {(run["variant"], run["seed"]) for run in self._existing_runs(job_id)}
            remaining = [
                task
                for task in _tasks(running["config"])
                if (task["variant"], task["seed"]) not in completed_pairs
            ]
            if remaining:
                configure = getattr(self._engine, "configure_workers", None)
                if callable(configure):
                    configure(int(running["workers"]))
                self._engine.run_batch(remaining, on_result, on_progress)
                status = "cancelled" if event.is_set() else "completed"
                final = self._job_service.update(job_id, {"status": status})
            else:
                status = "completed"
                final = self._job_service.update(job_id, {"status": "completed"})
        except Exception as error:
            status = "error"
            final = self._finish_error(job_id, error)
        finally:
            with self._lock:
                self._cancel_requested.pop(job_id, None)
        if final is not None:
            self._publish(FINAL_EVENT_NAMES[status], final)
        return final

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._job_service.get(job_id)
            if job is None:
                raise ValueError(CANCEL_ERROR)
            status = job["status"]
            if status == "queued":
                cancelled = self._job_service.update(job_id, {"status": "cancelled"})
                if cancelled is None:
                    raise ValueError(CANCEL_ERROR)
                self._publish("experiment.cancelled", cancelled)
                return cancelled
            if status != "running":
                raise ValueError(CANCEL_ERROR)
            event = self._cancel_requested.get(job_id)
            if event is not None:
                event.set()
        self._engine.cancel()
        current = self._job_service.get(job_id)
        if current is None:
            raise ValueError(CANCEL_ERROR)
        return current

    def resume(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._job_service.get(job_id)
            if job is None or job["status"] != "interrupted":
                raise ValueError(RESUME_ERROR)
            resumed = self._job_service.update(job_id, {"status": "queued"})
            if resumed is None:
                raise ValueError(RESUME_ERROR)
            self._publish("experiment.resumed", resumed)
            return resumed

    def _record_progress(self, job_id: str, active: Sequence[Mapping[str, Any]]) -> None:
        job = self._job_service.get(job_id)
        if job is None:
            return
        summary = dict(job["summary"])
        summary["active"] = [dict(item) for item in active]
        summary["current"] = summary["active"][0] if summary["active"] else None
        updated = self._job_service.update(job_id, {"summary": summary})
        if updated is not None:
            self._publish("experiment.progress", updated)

    def _finish_error(self, job_id: str, error: Exception) -> dict[str, Any] | None:
        job = self._job_service.get(job_id)
        summary = dict(job["summary"]) if job is not None else {}
        summary["error"] = str(error) or ENGINE_ERROR
        return self._job_service.update(job_id, {"status": "error", "summary": summary})

    def _existing_runs(self, job_id: str) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._job_service.runs(job_id, limit=RUN_PAGE_SIZE, offset=offset)
            runs.extend(page["items"])
            if page["next_offset"] is None:
                return runs
            offset = page["next_offset"]

    def _publish(self, event: str, job: Mapping[str, Any]) -> None:
        if self._publisher is None:
            return
        try:
            self._publisher.publish(
                event,
                {
                    "job_id": job["id"],
                    "status": job["status"],
                    "completed": job["completed"],
                    "total": job["total"],
                },
            )
        except Exception:
            return

    def _running_job(self) -> dict[str, Any] | None:
        page = self._job_service.list(status="running", limit=1)
        return page["items"][0] if page["items"] else None

    def _next_queued(self) -> dict[str, Any] | None:
        queued: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._job_service.list(status="queued", limit=JOB_PAGE_SIZE, offset=offset)
            queued.extend(page["items"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        if not queued:
            return None
        queued.reverse()
        queued.sort(key=lambda item: item["created_at"])
        return queued[0]
