from __future__ import annotations

import json
import threading
from collections.abc import Callable
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
    materializer: FakeMaterializer | None = None,
) -> tuple[ExperimentService, FakeEngine, JobService]:
    jobs = job_service(tmp_path)
    fake = FakeEngine() if engine is None else engine
    return ExperimentService(jobs, fake, PLAN, materializer=materializer), fake, jobs


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


class FakeMaterializer:
    def __init__(self, *, error: Exception | None = None, pool: dict[str, Any] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.discarded: list[str] = []
        self.error = error
        self.pool = pool

    def prepare(self, *, job_id, draft_id, baseline_draft_id, seeds):
        self.calls.append(
            {
                "job_id": job_id,
                "draft_id": draft_id,
                "baseline_draft_id": baseline_draft_id,
                "seeds": list(seeds),
            }
        )
        if self.error is not None:
            raise self.error
        variants = ("A", "B") if baseline_draft_id is not None else ("B",)
        configs = [
            {
                "variant": variant,
                "seed": seed,
                "entry": None,
                "config_file": f"/tmp/experiments/{job_id}/{variant}-{seed}.bin",
                "config_sha256": "0" * 64,
                "scenario_file": f"/tmp/experiments/{job_id}/{variant}-{seed}.json",
                "scenario_sha256": "1" * 64,
            }
            for seed in seeds
            for variant in variants
        ]
        return {
            "dir": f"/tmp/experiments/{job_id}",
            "codec": "FM27CFG1",
            "configs": configs,
            "pool": self.pool,
        }

    def discard(self, job_id: str) -> None:
        self.discarded.append(job_id)


class FailingDiscardMaterializer(FakeMaterializer):
    def __init__(self, *, discard_error: Exception, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.discard_error = discard_error

    def discard(self, job_id: str) -> None:
        super().discard(job_id)
        raise self.discard_error


def test_submit_materializes_and_updates_job_config(tmp_path: Path):
    materializer = FakeMaterializer()
    service, fake, jobs = make_service(tmp_path, materializer=materializer)
    job = submit(service, seeds=(3, 1), draft_id="draft-1", baseline_draft_id="draft-0")
    assert materializer.calls == [
        {
            "job_id": job["id"],
            "draft_id": "draft-1",
            "baseline_draft_id": "draft-0",
            "seeds": [3, 1],
        }
    ]
    assert job["status"] == "queued"
    assert job["total"] == 4
    config = job["config"]
    assert config["seeds"] == [3, 1]
    assert config["variants"] == ["A", "B"]
    assert config["draft_id"] == "draft-1"
    assert config["baseline_draft_id"] == "draft-0"
    materialized = config["materialized"]
    assert materialized["dir"] == f"/tmp/experiments/{job['id']}"
    assert materialized["codec"] == "FM27CFG1"
    assert [(item["variant"], item["seed"]) for item in materialized["configs"]] == [
        ("A", 3),
        ("B", 3),
        ("A", 1),
        ("B", 1),
    ]
    assert materialized["pool"] is None
    assert job["summary"]["configs_count"] == 4
    assert job["summary"]["provenance"] == PLAN.provenance
    assert job["summary"]["runtime_mode"] == PLAN.runtime_mode
    assert "pool" not in job["summary"]


def test_submit_without_baseline_materializes_single_variant(tmp_path: Path):
    materializer = FakeMaterializer()
    service, _, _ = make_service(tmp_path, materializer=materializer)
    job = submit(service, seeds=(7,), draft_id="draft-1")
    assert job["config"]["variants"] == ["B"]
    assert job["config"]["baseline_draft_id"] is None
    assert job["total"] == 1
    assert job["summary"]["configs_count"] == 1
    assert [(item["variant"], item["seed"]) for item in job["config"]["materialized"]["configs"]] == [
        ("B", 7)
    ]


def test_submit_materializer_pool_summary_lands_in_job_summary(tmp_path: Path):
    pool = {
        "profile": "away-tactic-pool-v1",
        "enabled": True,
        "mode": "random",
        "rounds": 1,
        "entries": [],
        "draws": {"7": 0},
        "salt": "salt",
    }
    service, _, _ = make_service(tmp_path, materializer=FakeMaterializer(pool=pool))
    job = submit(service, seeds=(7,), draft_id="draft-1")
    assert job["summary"]["pool"] == pool


def test_submit_deletes_job_when_materialization_fails(tmp_path: Path):
    materializer = FakeMaterializer(error=RuntimeError("物化失败"))
    service, fake, jobs = make_service(tmp_path, materializer=materializer)
    with pytest.raises(RuntimeError, match="物化失败"):
        submit(service, seeds=(1,), draft_id="draft-1")
    assert jobs.list()["items"] == []
    assert materializer.discarded == [materializer.calls[0]["job_id"]]


def test_submit_removes_job_and_materialization_when_base_exception_is_raised(tmp_path: Path):
    materializer = FakeMaterializer(error=KeyboardInterrupt())
    service, _, jobs = make_service(tmp_path, materializer=materializer)

    with pytest.raises(KeyboardInterrupt):
        submit(service, seeds=(1,), draft_id="draft-1")

    assert jobs.list()["items"] == []
    assert materializer.discarded == [materializer.calls[0]["job_id"]]


def test_submit_preserves_original_error_when_job_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    materializer = FakeMaterializer(error=RuntimeError("物化失败"))
    service, _, jobs = make_service(tmp_path, materializer=materializer)

    def failing_delete(job_id: str) -> bool:
        raise RuntimeError("任务删除失败")

    monkeypatch.setattr(jobs, "delete", failing_delete)

    with pytest.raises(RuntimeError, match="物化失败"):
        submit(service, seeds=(1,), draft_id="draft-1")

    assert materializer.discarded == [materializer.calls[0]["job_id"]]


def test_submit_preserves_original_error_when_materialization_cleanup_fails(tmp_path: Path):
    materializer = FailingDiscardMaterializer(
        error=RuntimeError("物化失败"),
        discard_error=OSError("目录清理失败"),
    )
    service, _, jobs = make_service(tmp_path, materializer=materializer)

    with pytest.raises(RuntimeError, match="物化失败"):
        submit(service, seeds=(1,), draft_id="draft-1")

    assert jobs.list()["items"] == []
    assert materializer.discarded == [materializer.calls[0]["job_id"]]


def test_submit_rejects_total_matches_above_limit(tmp_path: Path):
    service, _, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match="实验总场数不能超过 10000"):
        submit(service, seeds=list(range(5001)), variants=("A", "B"), workers=1)


def test_start_next_dispatches_materialized_config_paths(tmp_path: Path):
    materializer = FakeMaterializer()
    service, fake, jobs = make_service(tmp_path, materializer=materializer)
    job = submit(service, seeds=(3, 1), draft_id="draft-1", baseline_draft_id="draft-0")
    final = service.start_next()
    assert final is not None
    assert final["status"] == "completed"
    assert final["completed"] == 4
    prefix = f"/tmp/experiments/{job['id']}"
    assert fake.tasks == [
        {"variant": "A", "seed": 3, "config": f"{prefix}/A-3.bin"},
        {"variant": "B", "seed": 3, "config": f"{prefix}/B-3.bin"},
        {"variant": "A", "seed": 1, "config": f"{prefix}/A-1.bin"},
        {"variant": "B", "seed": 1, "config": f"{prefix}/B-1.bin"},
    ]
    assert all(Path(task["config"]).is_absolute() for task in fake.tasks)


def test_start_next_after_resume_dispatches_only_missing_materialized_tasks(tmp_path: Path):
    materializer = FakeMaterializer()
    service, fake, jobs = make_service(tmp_path, materializer=materializer)
    job = submit(service, seeds=(3, 1), draft_id="draft-1", baseline_draft_id="draft-0")
    jobs.update(job["id"], {"status": "running"})
    for variant, seed in (("A", 3), ("B", 3)):
        jobs.append_run(job["id"], run_record(variant, seed))
    jobs.update(job["id"], {"status": "interrupted"})
    assert service.resume(job["id"])["status"] == "queued"
    final = service.start_next()
    assert final is not None
    assert final["status"] == "completed"
    assert final["completed"] == 4
    prefix = f"/tmp/experiments/{job['id']}"
    assert fake.tasks == [
        {"variant": "A", "seed": 1, "config": f"{prefix}/A-1.bin"},
        {"variant": "B", "seed": 1, "config": f"{prefix}/B-1.bin"},
    ]
    assert len(materializer.calls) == 1
    assert materializer.discarded == []


class ProbeLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.holder: str | None = None
        self.starter_attempted = threading.Event()
        self.starter_holder: str | None = None

    def __enter__(self) -> ProbeLock:
        if threading.current_thread().name == "starter":
            self.starter_holder = self.holder
            self.starter_attempted.set()
        self._lock.acquire()
        self.holder = threading.current_thread().name
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.holder = None
        self._lock.release()


class GatedMaterializer(FakeMaterializer):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def prepare(self, *, job_id, draft_id, baseline_draft_id, seeds):
        self.entered.set()
        assert self.release.wait(5)
        return super().prepare(
            job_id=job_id,
            draft_id=draft_id,
            baseline_draft_id=baseline_draft_id,
            seeds=seeds,
        )


class JobMutatingMaterializer(FakeMaterializer):
    def __init__(self, mutate: Callable[[str], None]) -> None:
        super().__init__()
        self._mutate = mutate

    def prepare(self, *, job_id, draft_id, baseline_draft_id, seeds):
        prepared = super().prepare(
            job_id=job_id,
            draft_id=draft_id,
            baseline_draft_id=baseline_draft_id,
            seeds=seeds,
        )
        self._mutate(job_id)
        return prepared


def test_start_next_waits_for_submit_and_dispatches_materialized_configs(tmp_path: Path):
    jobs = job_service(tmp_path)
    engine = FakeEngine()
    materializer = GatedMaterializer()
    service = ExperimentService(jobs, engine, PLAN, materializer=materializer)
    probe = ProbeLock()
    service._lock = probe
    submitted: list[dict[str, Any]] = []
    started: list[dict[str, Any] | None] = []
    failures: list[BaseException] = []

    def run_submit() -> None:
        try:
            submitted.append(submit(service, seeds=(1,), draft_id="draft-1", baseline_draft_id="draft-0"))
        except BaseException as error:
            failures.append(error)

    def run_start() -> None:
        try:
            started.append(service.start_next())
        except BaseException as error:
            failures.append(error)

    submit_thread = threading.Thread(target=run_submit, name="submit")
    submit_thread.start()
    assert materializer.entered.wait(5)
    start_thread = threading.Thread(target=run_start, name="starter")
    start_thread.start()
    try:
        assert probe.starter_attempted.wait(5)
        assert probe.starter_holder == "submit"
        assert start_thread.is_alive()
        assert engine.tasks == []
    finally:
        materializer.release.set()
        submit_thread.join(timeout=5)
        start_thread.join(timeout=5)
    assert not submit_thread.is_alive()
    assert not start_thread.is_alive()
    assert failures == []
    final = started[0]
    assert final is not None
    assert final["status"] == "completed"
    assert final["completed"] == 2
    job = submitted[0]
    assert final["id"] == job["id"]
    assert job["config"]["materialized"]["configs"]
    assert [(task["variant"], task["seed"]) for task in engine.tasks] == [("A", 1), ("B", 1)]
    assert all(Path(task["config"]).is_absolute() for task in engine.tasks)


def test_submit_discards_job_when_job_deleted_during_materialization(tmp_path: Path):
    jobs = job_service(tmp_path)
    materializer = JobMutatingMaterializer(jobs.delete)
    service = ExperimentService(jobs, FakeEngine(), PLAN, materializer=materializer)

    with pytest.raises(ValueError, match="任务创建失败"):
        submit(service, seeds=(1,), draft_id="draft-1")

    assert jobs.list()["items"] == []
    assert materializer.discarded == [materializer.calls[0]["job_id"]]


def test_submit_removes_job_when_summary_update_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    materializer = FakeMaterializer()
    service, _, jobs = make_service(tmp_path, materializer=materializer)
    monkeypatch.setattr(jobs, "update", lambda job_id, changes: None)

    with pytest.raises(ValueError, match="任务创建失败"):
        submit(service, seeds=(1,), draft_id="draft-1")

    assert jobs.list()["items"] == []
    assert materializer.discarded == [materializer.calls[0]["job_id"]]


def test_submit_discards_job_when_job_cancelled_during_materialization(tmp_path: Path):
    jobs = job_service(tmp_path)

    def cancel_job(job_id: str) -> None:
        jobs.update(job_id, {"status": "cancelled"})

    materializer = JobMutatingMaterializer(cancel_job)
    service = ExperimentService(jobs, FakeEngine(), PLAN, materializer=materializer)

    with pytest.raises(ValueError, match="仅排队中的任务可以更新配置"):
        submit(service, seeds=(1,), draft_id="draft-1")

    assert jobs.list()["items"] == []
    assert materializer.discarded == [materializer.calls[0]["job_id"]]


def test_start_next_marks_new_config_without_materialized_scenarios_error(tmp_path: Path):
    service, fake, jobs = make_service(tmp_path)
    job = jobs.create(
        "experiment",
        config={"seeds": [1], "variants": ["B"], "draft_id": "draft-1"},
        total=1,
    )

    final = service.start_next()

    assert final is not None
    assert final["id"] == job["id"]
    assert final["status"] == "error"
    assert final["summary"]["error"] == "实验配置缺少比赛场景"
    assert fake.tasks == []
    assert jobs.runs(job["id"])["total"] == 0


class RecordingEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, int | None]] = []

    def configure_workers(self, workers: int) -> None:
        self.events.append(("configure", workers))

    def run_batch(self, tasks, on_result, on_progress) -> None:
        self.events.append(("run_batch", None))
        super().run_batch(tasks, on_result, on_progress)


def test_callable_runtime_plan_is_resolved_for_the_job_summary(tmp_path: Path):
    jobs = job_service(tmp_path)
    calls: list[None] = []

    def plan() -> RuntimePlan:
        calls.append(None)
        return PLAN

    service = ExperimentService(jobs, FakeEngine(), plan)
    job = submit(service, seeds=(1,), variants=("A",))
    assert calls == [None]
    assert job["summary"]["runtime_mode"] == PLAN.runtime_mode
    assert job["summary"]["provenance"] == PLAN.provenance


@pytest.mark.parametrize("invalid", [None, "plan", {"runtime_mode": "reused_worker"}])
def test_invalid_runtime_plan_is_rejected_before_job_creation(tmp_path: Path, invalid):
    jobs = job_service(tmp_path)
    service = ExperimentService(jobs, FakeEngine(), lambda: invalid)
    with pytest.raises(ValueError, match="运行时计划无效"):
        submit(service, seeds=(1,), variants=("A",))
    assert jobs.list()["items"] == []


def test_runtime_plan_failure_is_rejected_before_job_creation(tmp_path: Path):
    jobs = job_service(tmp_path)

    def plan() -> RuntimePlan:
        raise RuntimeError("引擎探测失败")

    service = ExperimentService(jobs, FakeEngine(), plan)
    with pytest.raises(RuntimeError, match="引擎探测失败"):
        submit(service, seeds=(1,), variants=("A",))
    assert jobs.list()["items"] == []


def test_start_next_configures_engine_workers_before_dispatch(tmp_path: Path):
    jobs = job_service(tmp_path)
    engine = RecordingEngine()
    service = ExperimentService(jobs, engine, PLAN)
    submitted = submit(service, seeds=(2,), variants=("A",), workers=3)

    final = service.start_next()

    assert final is not None
    assert final["status"] == "completed"
    assert submitted["workers"] == 3
    assert engine.events == [("configure", 3), ("run_batch", None)]


class WorkerStatusEngine(RecordingEngine):
    def __init__(self, jobs: JobService) -> None:
        super().__init__()
        self._jobs = jobs
        self.job_id: str | None = None
        self.worker_status: list[str] = []

    def configure_workers(self, workers: int) -> None:
        assert self.job_id is not None
        self.worker_status.append(self._jobs.get(self.job_id)["status"])
        super().configure_workers(workers)


def test_start_next_configures_workers_after_marking_the_job_running(tmp_path: Path):
    jobs = job_service(tmp_path)
    engine = WorkerStatusEngine(jobs)
    service = ExperimentService(jobs, engine, PLAN)
    submitted = submit(service, seeds=(2,), variants=("A",), workers=3)
    engine.job_id = submitted["id"]

    final = service.start_next()

    assert final is not None
    assert final["status"] == "completed"
    assert engine.worker_status == ["running"]
    assert engine.events == [("configure", 3), ("run_batch", None)]


def test_start_next_tolerates_engines_without_worker_configuration(tmp_path: Path):
    service, fake, _ = make_service(tmp_path)
    submit(service, seeds=(1,), variants=("A",))

    final = service.start_next()

    assert final is not None
    assert final["status"] == "completed"
    assert len(fake.tasks) == 1
