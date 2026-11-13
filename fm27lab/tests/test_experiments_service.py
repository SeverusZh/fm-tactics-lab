from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.application.experiments import ExperimentService, ResourceBlocked
from fm27lab.application.jobs import JobService
from fm27lab.ports.engine import EngineCapabilities, EnginePort, RuntimePlan

GIB = 1024**3
CPU_COUNT = 8
AVAILABLE_MEMORY = 32 * GIB
FREE_DISK = 100 * GIB
SUBMIT_OPTIONS = {
    "workers": 2,
    "name": None,
    "cpu_count": CPU_COUNT,
    "available_memory_bytes": AVAILABLE_MEMORY,
    "free_disk_bytes": FREE_DISK,
    "allow_oversubscription": False,
}
PLAN = RuntimePlan(
    runtime_mode="reused_worker",
    jobs_per_native_session=None,
    session_scope="remaining_batch_lane",
    fallback_reason=None,
    provenance={
        "counted_sessions": True,
        "fallback_reason": None,
        "jobs_per_native_session": None,
        "session_scope": "remaining_batch_lane",
        "capability_version": 2,
    },
)


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def job_service(tmp_path: Path) -> JobService:
    return JobService(JobRepository(database(tmp_path)))


def make_service(
    tmp_path: Path,
    engine: FakeEngine | None = None,
) -> tuple[ExperimentService, FakeEngine, JobService]:
    jobs = job_service(tmp_path)
    fake = FakeEngine() if engine is None else engine
    return ExperimentService(jobs, fake, PLAN), fake, jobs


def submit(service: ExperimentService, *, seeds=(1, 2), variants=("A", "B"), **overrides) -> dict[str, Any]:
    options = dict(SUBMIT_OPTIONS)
    options.update(overrides)
    return service.submit({"seeds": list(seeds), "variants": list(variants)}, **options)


def result_for(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant": task["variant"],
        "seed": task["seed"],
        "score_home": 1,
        "score_away": 0,
        "verified": True,
        "stats": {"shots": [4, 2]},
    }


def run_record(variant: str, seed: int) -> dict[str, Any]:
    return {
        "variant": variant,
        "seed": seed,
        "score_home": 1,
        "score_away": 0,
        "verified": True,
        "stats": {},
    }


class FakeEngine:
    def __init__(self, *, error: Exception | None = None, block_until_cancelled: bool = False):
        self.tasks: list[dict[str, Any]] = []
        self.progress: list[list[dict[str, Any]]] = []
        self.cancel_calls = 0
        self.error = error
        self.block_until_cancelled = block_until_cancelled
        self.started = threading.Event()
        self.cancel_seen = threading.Event()

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            counted_sessions=True,
            session_scope="remaining_batch_lane",
            capability_version=2,
        )

    def run_batch(self, tasks, on_result, on_progress) -> None:
        self.tasks = [dict(task) for task in tasks]
        if self.block_until_cancelled:
            self.started.set()
            self.cancel_seen.wait(timeout=5)
            on_progress([])
            return
        if self.error is not None:
            raise self.error
        for index, task in enumerate(self.tasks):
            active = [{"worker": index}]
            self.progress.append(active)
            on_progress(active)
            on_result(result_for(task))

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.cancel_seen.set()


def test_fake_engine_satisfies_engine_port():
    assert isinstance(FakeEngine(), EnginePort)


def test_submit_creates_queued_job_with_plan_provenance(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    job = submit(service, seeds=(3, 1), variants=("A", "B"))
    assert job["kind"] == "experiment"
    assert job["status"] == "queued"
    assert job["workers"] == 2
    assert job["total"] == 4
    assert job["completed"] == 0
    assert job["config"] == {"seeds": [3, 1], "variants": ["A", "B"]}
    assert job["summary"] == {"provenance": PLAN.provenance, "runtime_mode": PLAN.runtime_mode}
    assert job["started_at"] is None
    assert job["finished_at"] is None
    assert jobs.get(job["id"]) == job
    assert jobs.list(status="running")["total"] == 0
    assert fake.tasks == []
    assert fake.progress == []


def test_submit_counts_total_across_seeds_and_variants(tmp_path: Path):
    service, _, _ = make_service(tmp_path)
    job = submit(service, seeds=(1, 2, 3), variants=("B",), workers=1)
    assert job["total"] == 3
    assert job["config"] == {"seeds": [1, 2, 3], "variants": ["B"]}


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"variants": ["A"]}, "种子"),
        ({"seeds": [1]}, "变体"),
        ({"seeds": [], "variants": ["A"]}, "种子"),
        ({"seeds": (1, 2), "variants": ["A"]}, "种子"),
        ({"seeds": "1,2", "variants": ["A"]}, "种子"),
        ({"seeds": [1.5], "variants": ["A"]}, "种子"),
        ({"seeds": [True], "variants": ["A"]}, "种子"),
        ({"seeds": [False], "variants": ["A"]}, "种子"),
        ({"seeds": [-1], "variants": ["A"]}, "种子"),
        ({"seeds": [2**32], "variants": ["A"]}, "种子"),
        ({"seeds": [1, 1], "variants": ["A"]}, "种子"),
        ({"seeds": [1, "2"], "variants": ["A"]}, "种子"),
        ({"seeds": [1], "variants": []}, "变体"),
        ({"seeds": [1], "variants": "AB"}, "变体"),
        ({"seeds": [1], "variants": ["C"]}, "变体"),
        ({"seeds": [1], "variants": ["a"]}, "变体"),
        ({"seeds": [1], "variants": [1]}, "变体"),
        ({"seeds": [1], "variants": ["A", "A"]}, "变体"),
        ({"seeds": [1], "variants": None}, "变体"),
    ],
)
def test_submit_rejects_invalid_config(tmp_path: Path, config, message):
    service, fake, jobs = make_service(tmp_path)
    with pytest.raises(ValueError, match=message):
        service.submit(config, **dict(SUBMIT_OPTIONS))
    assert jobs.list()["total"] == 0
    assert fake.tasks == []


@pytest.mark.parametrize("config", [[], "scenario", None, 42, ("seeds",)])
def test_submit_rejects_non_mapping_config(tmp_path: Path, config):
    service, _, jobs = make_service(tmp_path)
    with pytest.raises(ValueError, match="配置"):
        service.submit(config, **dict(SUBMIT_OPTIONS))
    assert jobs.list()["total"] == 0


@pytest.mark.parametrize("workers", [0, 257, True, 1.0, "2"])
def test_submit_rejects_invalid_workers(tmp_path: Path, workers):
    service, _, jobs = make_service(tmp_path)
    with pytest.raises(ValueError, match="并行数"):
        submit(service, workers=workers)
    assert jobs.list()["total"] == 0


def test_submit_blocks_insufficient_memory(tmp_path: Path):
    service, _, jobs = make_service(tmp_path)
    with pytest.raises(ResourceBlocked) as caught:
        submit(service, workers=4, available_memory_bytes=GIB)
    assert isinstance(caught.value, ValueError)
    assert caught.value.code == "insufficient_memory"
    assert jobs.list()["total"] == 0


def test_submit_blocks_insufficient_disk(tmp_path: Path):
    service, _, jobs = make_service(tmp_path)
    with pytest.raises(ResourceBlocked) as caught:
        submit(service, workers=2, free_disk_bytes=3 * GIB)
    assert caught.value.code == "insufficient_disk"
    assert jobs.list()["total"] == 0


def test_submit_allow_oversubscription_bypasses_resource_block(tmp_path: Path):
    service, _, _ = make_service(tmp_path)
    job = submit(
        service,
        workers=4,
        available_memory_bytes=GIB,
        allow_oversubscription=True,
    )
    assert job["status"] == "queued"
    assert job["total"] == 4
    assert job["summary"]["provenance"] == PLAN.provenance


def test_submit_allows_workers_above_recommended(tmp_path: Path):
    service, _, _ = make_service(tmp_path)
    job = submit(service, workers=4, cpu_count=2)
    assert job["status"] == "queued"
    assert job["workers"] == 4


def test_start_next_returns_none_without_queued_jobs(tmp_path: Path):
    service, fake, _ = make_service(tmp_path)
    assert service.start_next() is None
    assert fake.tasks == []


def test_start_next_runs_earliest_queued_job(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    first = submit(service, seeds=(3, 1), variants=("A", "B"))
    second = submit(service, seeds=(9,), variants=("B",))
    final = service.start_next()
    assert final is not None
    assert final["id"] == first["id"]
    assert final["status"] == "completed"
    assert final["completed"] == 4
    assert final["started_at"] is not None
    assert final["finished_at"] is not None
    assert fake.tasks == [
        {"variant": "A", "seed": 3},
        {"variant": "B", "seed": 3},
        {"variant": "A", "seed": 1},
        {"variant": "B", "seed": 1},
    ]
    runs = jobs.runs(first["id"], limit=100)["items"]
    assert [run["sequence"] for run in runs] == [1, 2, 3, 4]
    assert [(run["variant"], run["seed"]) for run in runs] == [
        ("A", 3),
        ("B", 3),
        ("A", 1),
        ("B", 1),
    ]
    assert final["summary"]["provenance"] == PLAN.provenance
    assert final["summary"]["runtime_mode"] == PLAN.runtime_mode
    assert final["summary"]["active"] == [{"worker": 3}]
    assert final["summary"]["current"] == {"worker": 3}
    assert jobs.get(second["id"])["status"] == "queued"
    assert service.start_next()["id"] == second["id"]


def test_start_next_follows_creation_order(tmp_path: Path):
    service, _, _ = make_service(tmp_path)
    created = [
        submit(service, name=name, seeds=(index,), variants=("B",), workers=1)
        for index, name in enumerate(("first", "second", "third"))
    ]
    started = [service.start_next()["id"] for _ in created]
    assert started == [job["id"] for job in created]
    assert service.start_next() is None


def test_start_next_rejects_when_another_job_is_running(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    running = submit(service)
    queued = submit(service)
    jobs.update(running["id"], {"status": "running"})
    with pytest.raises(ValueError, match="已有任务在运行"):
        service.start_next()
    assert jobs.get(running["id"])["status"] == "running"
    assert jobs.get(queued["id"])["status"] == "queued"
    assert fake.tasks == []


def test_run_batch_error_marks_job_error(tmp_path: Path):
    engine = FakeEngine(error=RuntimeError("引擎崩溃"))
    service, fake, jobs = make_service(tmp_path, engine)
    job = submit(service)
    final = service.start_next()
    assert final["status"] == "error"
    assert final["completed"] == 0
    assert final["summary"]["error"] == "引擎崩溃"
    assert final["summary"]["provenance"] == PLAN.provenance
    assert final["summary"]["runtime_mode"] == PLAN.runtime_mode
    assert final["finished_at"] is not None
    assert jobs.runs(job["id"])["total"] == 0
    assert service.start_next() is None


def test_start_next_marks_invalid_config_job_error(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    created = jobs.create("experiment", config={}, total=1)
    final = service.start_next()
    assert final is not None
    assert final["id"] == created["id"]
    assert final["status"] == "error"
    assert final["summary"]["error"]
    assert fake.tasks == []


def test_cancel_queued_job(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    job = submit(service)
    cancelled = service.cancel(job["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["finished_at"] is not None
    assert jobs.get(job["id"])["status"] == "cancelled"
    assert service.start_next() is None
    assert fake.tasks == []
    with pytest.raises(ValueError, match="不允许取消"):
        service.cancel(job["id"])


def test_cancel_running_job_signals_engine_and_stops_batch(tmp_path: Path):
    engine = FakeEngine(block_until_cancelled=True)
    service, fake, jobs = make_service(tmp_path, engine)
    job = submit(service, seeds=(1, 2), variants=("A", "B"))
    outcome: list[dict[str, Any]] = []
    thread = threading.Thread(target=lambda: outcome.append(service.start_next()))
    thread.start()
    try:
        assert fake.started.wait(5)
        assert jobs.get(job["id"])["status"] == "running"
        cancelled = service.cancel(job["id"])
        assert cancelled["id"] == job["id"]
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()
    final = outcome[0]
    assert final["status"] == "cancelled"
    assert final["finished_at"] is not None
    assert final["summary"]["provenance"] == PLAN.provenance
    assert fake.cancel_calls == 1
    assert jobs.get(job["id"])["status"] == "cancelled"


def test_cancel_rejects_completed_job(tmp_path: Path):
    service, _, _ = make_service(tmp_path)
    job = submit(service, seeds=(1,), variants=("B",), workers=1)
    assert service.start_next()["status"] == "completed"
    with pytest.raises(ValueError, match="不允许取消"):
        service.cancel(job["id"])


def test_cancel_rejects_missing_job(tmp_path: Path):
    service, _, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match="不允许取消"):
        service.cancel("missing")


def test_resume_interrupted_job(tmp_path: Path):
    service, _, jobs = make_service(tmp_path)
    job = submit(service)
    jobs.update(job["id"], {"status": "running"})
    jobs.update(job["id"], {"status": "interrupted"})
    resumed = service.resume(job["id"])
    assert resumed["status"] == "queued"
    assert resumed["started_at"] is not None
    assert resumed["finished_at"] is None
    assert jobs.get(job["id"])["status"] == "queued"


@pytest.mark.parametrize("status", ["queued", "running", "completed", "cancelled", "error"])
def test_resume_rejects_non_interrupted_status(tmp_path: Path, status):
    service, _, jobs = make_service(tmp_path)
    job = submit(service, seeds=(1,), variants=("B",), workers=1)
    if status == "running":
        jobs.update(job["id"], {"status": "running"})
    elif status == "completed":
        assert service.start_next()["status"] == "completed"
    elif status == "cancelled":
        service.cancel(job["id"])
    elif status == "error":
        jobs.update(job["id"], {"status": "running"})
        jobs.update(job["id"], {"status": "error"})
    with pytest.raises(ValueError, match="不允许续跑"):
        service.resume(job["id"])


def test_resume_rejects_missing_job(tmp_path: Path):
    service, _, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match="不允许续跑"):
        service.resume("missing")


def test_start_next_after_resume_runs_only_missing_matches(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    job = submit(service, seeds=(3, 1), variants=("A", "B"))
    jobs.update(job["id"], {"status": "running"})
    for variant, seed in (("A", 3), ("B", 3)):
        jobs.append_run(job["id"], run_record(variant, seed))
    jobs.update(job["id"], {"status": "interrupted"})
    assert jobs.get(job["id"])["completed"] == 2
    assert service.resume(job["id"])["status"] == "queued"
    final = service.start_next()
    assert final is not None
    assert final["id"] == job["id"]
    assert final["status"] == "completed"
    assert final["completed"] == 4
    assert final["total"] == 4
    assert fake.tasks == [
        {"variant": "A", "seed": 1},
        {"variant": "B", "seed": 1},
    ]
    runs = jobs.runs(job["id"], limit=100)["items"]
    assert [(run["variant"], run["seed"]) for run in runs] == [
        ("A", 3),
        ("B", 3),
        ("A", 1),
        ("B", 1),
    ]
    assert len({(run["variant"], run["seed"]) for run in runs}) == 4


def test_start_next_completes_without_engine_when_all_matches_exist(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    job = submit(service, seeds=(1,), variants=("B",), workers=1)
    jobs.update(job["id"], {"status": "running"})
    jobs.append_run(job["id"], run_record("B", 1))
    jobs.update(job["id"], {"status": "interrupted"})
    assert service.resume(job["id"])["status"] == "queued"
    final = service.start_next()
    assert final is not None
    assert final["status"] == "completed"
    assert final["completed"] == 1
    assert fake.tasks == []
    assert fake.progress == []
    assert jobs.runs(job["id"])["total"] == 1


def test_start_next_filters_existing_runs_across_pages(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    seeds = list(range(202))
    job = submit(service, seeds=seeds, variants=("B",), workers=1)
    assert job["total"] == 202
    jobs.update(job["id"], {"status": "running"})
    for seed in seeds[:201]:
        jobs.append_run(job["id"], run_record("B", seed))
    jobs.update(job["id"], {"status": "interrupted"})
    assert service.resume(job["id"])["status"] == "queued"
    final = service.start_next()
    assert final is not None
    assert final["status"] == "completed"
    assert final["completed"] == 202
    assert fake.tasks == [{"variant": "B", "seed": 201}]
    assert jobs.runs(job["id"], limit=200)["total"] == 202


class RecordingPublisher:
    def __init__(self, error: Exception | None = None):
        self.events: list[tuple[str, dict]] = []
        self.error = error
        self._lock = threading.Lock()

    def publish(self, event: str, data) -> dict:
        payload = dict(data)
        with self._lock:
            self.events.append((event, payload))
        if self.error is not None:
            raise self.error
        return {"event": event, "data": payload}


def make_event_service(
    tmp_path: Path,
    engine: FakeEngine | None = None,
) -> tuple[ExperimentService, FakeEngine, JobService, RecordingPublisher]:
    jobs = job_service(tmp_path)
    fake = FakeEngine() if engine is None else engine
    publisher = RecordingPublisher()
    return ExperimentService(jobs, fake, PLAN, publisher=publisher), fake, jobs, publisher


def event_names(publisher: RecordingPublisher) -> list[str]:
    return [event for event, _ in publisher.events]


def experiment_snapshot(job) -> dict:
    return {
        "job_id": job["id"],
        "status": job["status"],
        "completed": job["completed"],
        "total": job["total"],
    }


def test_submit_publishes_experiment_submitted(tmp_path: Path):
    service, fake, jobs, publisher = make_event_service(tmp_path)
    job = submit(service, seeds=(1,), variants=("B",), workers=1)
    assert publisher.events == [("experiment.submitted", experiment_snapshot(job))]
    assert json.dumps(publisher.events[0][1])


def test_start_next_publishes_started_progress_and_completed(tmp_path: Path):
    service, fake, jobs, publisher = make_event_service(tmp_path)
    job = submit(service, seeds=(1,), variants=("B",), workers=1)
    publisher.events.clear()
    final = service.start_next()
    assert final is not None
    assert event_names(publisher) == [
        "experiment.started",
        "experiment.progress",
        "experiment.completed",
    ]
    assert publisher.events[0][1] == {**experiment_snapshot(job), "status": "running"}
    assert publisher.events[1][1] == {**experiment_snapshot(job), "status": "running"}
    assert publisher.events[2][1] == experiment_snapshot(final)
    assert publisher.events[2][1]["status"] == "completed"
    assert publisher.events[2][1]["completed"] == 1
    assert json.dumps(publisher.events[2][1])


def test_start_next_engine_error_publishes_experiment_error(tmp_path: Path):
    engine = FakeEngine(error=RuntimeError("引擎崩溃"))
    service, fake, jobs, publisher = make_event_service(tmp_path, engine)
    job = submit(service, seeds=(3, 1), variants=("A", "B"))
    publisher.events.clear()
    final = service.start_next()
    assert final is not None
    assert event_names(publisher) == ["experiment.started", "experiment.error"]
    assert publisher.events[1][1] == {**experiment_snapshot(job), "status": "error"}


def test_cancel_queued_job_publishes_experiment_cancelled(tmp_path: Path):
    service, fake, jobs, publisher = make_event_service(tmp_path)
    job = submit(service)
    publisher.events.clear()
    cancelled = service.cancel(job["id"])
    assert publisher.events == [
        ("experiment.cancelled", {**experiment_snapshot(job), "status": "cancelled"}),
    ]
    assert cancelled["status"] == "cancelled"


def test_cancel_running_job_publishes_cancelled_when_batch_stops(tmp_path: Path):
    engine = FakeEngine(block_until_cancelled=True)
    service, fake, jobs, publisher = make_event_service(tmp_path, engine)
    job = submit(service, seeds=(1,), variants=("A", "B"))
    publisher.events.clear()
    outcome: list[dict[str, Any]] = []
    thread = threading.Thread(target=lambda: outcome.append(service.start_next()))
    thread.start()
    try:
        assert fake.started.wait(5)
        service.cancel(job["id"])
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()
    final = outcome[0]
    assert final["status"] == "cancelled"
    assert event_names(publisher) == [
        "experiment.started",
        "experiment.progress",
        "experiment.cancelled",
    ]
    assert publisher.events[-1][1]["status"] == "cancelled"


def test_resume_publishes_experiment_resumed(tmp_path: Path):
    service, fake, jobs, publisher = make_event_service(tmp_path)
    job = submit(service)
    jobs.update(job["id"], {"status": "running"})
    jobs.update(job["id"], {"status": "interrupted"})
    publisher.events.clear()
    resumed = service.resume(job["id"])
    assert publisher.events == [("experiment.resumed", experiment_snapshot(resumed))]
    assert resumed["status"] == "queued"


def test_publisher_failure_keeps_experiment_flow_working(tmp_path: Path):
    jobs = job_service(tmp_path)
    publisher = RecordingPublisher(error=RuntimeError("事件发布失败"))
    service = ExperimentService(jobs, FakeEngine(), PLAN, publisher=publisher)
    job = submit(service, seeds=(1,), variants=("B",), workers=1)
    assert job["status"] == "queued"
    final = service.start_next()
    assert final is not None
    assert final["status"] == "completed"
    assert event_names(publisher) == [
        "experiment.submitted",
        "experiment.started",
        "experiment.progress",
        "experiment.completed",
    ]
