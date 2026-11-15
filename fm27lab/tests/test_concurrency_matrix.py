"""并发验收矩阵：1、8、256 路提交的结果身份、进度计数、取消与续跑语义。"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from fm27lab.adapters.engine_native import NativeEngineHost, plan_runtime
from fm27lab.adapters.engine_native.lazy import LazyNativeEngine
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.application.events import EventPublisher, EventSubscription
from fm27lab.application.experiments import ExperimentService
from fm27lab.application.jobs import JobService
from fm27lab.ports.engine import EngineCapabilities, EnginePort

FAKE_SIMULATOR = Path(__file__).resolve().parent / "fixtures" / "fake_simulator.py"
GIB = 1024**3
MATRIX_SEEDS = (3, 5, 8)
MATRIX_VARIANTS = ("A", "B")
MATRIX_WORKERS = (1, 8, 256)
MATRIX_CPU_COUNT = 8
MATRIX_AVAILABLE_MEMORY = 32 * GIB
MATRIX_FREE_DISK = 1024 * GIB
MATCH_TIMEOUT_SECONDS = 60.0
WAIT_SECONDS = 30.0
COUNTED_CAPABILITIES = EngineCapabilities(
    counted_sessions=True,
    jobs_per_session=None,
    session_scope="remaining_batch_lane",
    capability_version=2,
)
EXPECTED_PAIRS = tuple((variant, seed) for seed in MATRIX_SEEDS for variant in MATRIX_VARIANTS)
EXPECTED_TOTAL = len(EXPECTED_PAIRS)

ResultCallback = Callable[[Mapping[str, Any]], None]
ProgressCallback = Callable[[Sequence[Mapping[str, Any]]], None]


def expected_score(seed: int) -> tuple[int, int]:
    """假模拟器按种子生成的确定性比分。"""
    return seed % 4, (seed * 7) % 3


def success_result(task: Mapping[str, Any]) -> dict[str, Any]:
    """构造与假模拟器统计一致的单场成功结果。"""
    seed = int(task["seed"])
    home, away = expected_score(seed)
    return {
        "variant": task["variant"],
        "seed": seed,
        "score_home": home,
        "score_away": away,
        "verified": True,
        "stats": {
            "event": "native_match_statistics",
            "teams": [
                {"shots": home + 5, "completed_passes": 10},
                {"shots": away + 5, "completed_passes": 9},
            ],
        },
        "events": {"goals": [], "cards": []},
        "log_path": None,
    }


def read_runs(job_service: JobService, job_id: str) -> list[dict[str, Any]]:
    """按 sequence 顺序读取全部运行记录。"""
    runs: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = job_service.runs(job_id, limit=200, offset=offset)
        runs.extend(page["items"])
        if page["next_offset"] is None:
            return runs
        offset = page["next_offset"]


def drain_events(subscription: EventSubscription) -> list[dict[str, Any]]:
    """取出订阅队列里已发布的全部事件。"""
    events: list[dict[str, Any]] = []
    while True:
        try:
            event = subscription.get_nowait()
        except queue.Empty:
            return events
        if event is None:
            return events
        events.append(event)


def task_pairs(tasks: Sequence[Mapping[str, Any]]) -> list[tuple[str, int]]:
    """提取任务的变体与种子顺序。"""
    return [(task["variant"], task["seed"]) for task in tasks]


def session_directories(directory: Path, name: str = "engine") -> list[Path]:
    """列出某档位引擎实际创建的原生会话目录。"""
    sessions = directory / name / "work" / "worker_sessions"
    if not sessions.exists():
        return []
    return [path for path in sessions.iterdir() if path.is_dir()]


def assert_identity(runs: Sequence[Mapping[str, Any]]) -> None:
    """校验每场结果与种子一一对应且不串场。"""
    assert len(runs) == EXPECTED_TOTAL
    assert [run["sequence"] for run in runs] == list(range(1, EXPECTED_TOTAL + 1))
    pairs = task_pairs(runs)
    assert sorted(pairs) == sorted(EXPECTED_PAIRS)
    assert len(set(pairs)) == len(pairs)
    for run in runs:
        home, away = expected_score(int(run["seed"]))
        assert run["score"] == [home, away]
        assert run["verified"] is True
        teams = run["stats"]["teams"]
        assert [team["shots"] for team in teams] == [home + 5, away + 5]


def result_distribution(runs: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], tuple[Any, ...]]:
    """去掉环境相关路径后的结果分布，用于跨 worker 数比较。"""
    return {
        (run["variant"], run["seed"]): (tuple(run["score"]), run["stats"]["teams"])
        for run in runs
    }


def assert_progress_consistent(
    events: Sequence[Mapping[str, Any]],
    *,
    job_id: str,
    run_count: int,
) -> list[dict[str, Any]]:
    """校验进度事件的完成数与已落库结果数一致且单调不减。"""
    run_events = [
        event for event in events if event["event"] == "job.run" and event["data"]["job_id"] == job_id
    ]
    assert [event["data"]["completed"] for event in run_events] == list(range(1, run_count + 1))
    accepted = 0
    previous = 0
    progress: list[dict[str, Any]] = []
    for event in events:
        data = event["data"]
        if data.get("job_id") != job_id:
            continue
        if event["event"] == "job.run":
            accepted += 1
        elif event["event"] == "experiment.progress":
            completed = data["completed"]
            assert completed == accepted
            assert completed >= previous
            previous = completed
            progress.append(event)
    assert progress
    return progress


def assert_final_event(
    events: Sequence[Mapping[str, Any]],
    *,
    name: str,
    job_id: str,
    status: str,
    completed: int,
    total: int,
) -> None:
    """校验终态事件只发布一次且快照与任务记录一致。"""
    finals = [event for event in events if event["event"] == name and event["data"]["job_id"] == job_id]
    assert len(finals) == 1
    assert dict(finals[0]["data"]) == {
        "job_id": job_id,
        "status": status,
        "completed": completed,
        "total": total,
    }


def fake_host_factory(root: Path, work_dir: Path, **options: Any) -> NativeEngineHost:
    """构造由假模拟器驱动的原生引擎宿主。"""
    return NativeEngineHost(
        root,
        work_dir,
        executable=FAKE_SIMULATOR,
        retries=0,
        timeout_seconds=MATCH_TIMEOUT_SECONDS,
        cleanup_seconds=5.0,
        **options,
    )


class RecordingEngine:
    """记录下发任务与并行数，并把执行委托给内层引擎。"""

    def __init__(self, inner: EnginePort):
        self._inner = inner
        self.dispatched: list[dict[str, Any]] = []
        self.workers: int | None = None

    def capabilities(self) -> EngineCapabilities:
        return self._inner.capabilities()

    def configure_workers(self, workers: int) -> None:
        self.workers = workers
        configure = getattr(self._inner, "configure_workers", None)
        if callable(configure):
            configure(workers)

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: ResultCallback,
        on_progress: ProgressCallback,
    ) -> None:
        self.dispatched = [dict(task) for task in tasks]
        self._inner.run_batch(tasks, on_result, on_progress)

    def cancel(self) -> None:
        self._inner.cancel()


class GatedEngine:
    """先交付固定数量结果再阻塞，直到取消唤醒，用于确定性取消验证。"""

    def __init__(self, release: int = 2):
        self.release = release
        self.dispatched: list[dict[str, Any]] = []
        self.cancel_calls = 0
        self.workers: int | None = None
        self.started = threading.Event()
        self._released = threading.Event()

    def capabilities(self) -> EngineCapabilities:
        return COUNTED_CAPABILITIES

    def configure_workers(self, workers: int) -> None:
        self.workers = workers

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: ResultCallback,
        on_progress: ProgressCallback,
    ) -> None:
        self.dispatched = [dict(task) for task in tasks]
        for task in self.dispatched[: self.release]:
            on_result(success_result(task))
        if self.dispatched:
            first = self.dispatched[0]
            on_progress(
                [
                    {
                        "variant": first["variant"],
                        "seed": first["seed"],
                        "worker_completed": min(self.release, len(self.dispatched)),
                        "worker_total": len(self.dispatched),
                    }
                ]
            )
        self.started.set()
        if not self._released.wait(WAIT_SECONDS):
            raise RuntimeError("取消信号等待超时")

    def cancel(self) -> None:
        self.cancel_calls += 1
        self._released.set()


class CancelOnConfigureEngine(GatedEngine):
    """在配置并行度期间触发取消，覆盖配置阶段的取消窗口。"""

    def __init__(self):
        super().__init__(release=0)
        self.cancel_hook: Callable[[], None] | None = None

    def configure_workers(self, workers: int) -> None:
        super().configure_workers(workers)
        hook = self.cancel_hook
        if hook is not None:
            hook()


class CrashEngine:
    """交付固定数量结果后模拟宿主崩溃，用于续跑验证。"""

    def __init__(self, release: int = 2):
        self.release = release
        self.dispatched: list[dict[str, Any]] = []
        self.workers: int | None = None

    def capabilities(self) -> EngineCapabilities:
        return COUNTED_CAPABILITIES

    def configure_workers(self, workers: int) -> None:
        self.workers = workers

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: ResultCallback,
        on_progress: ProgressCallback,
    ) -> None:
        self.dispatched = [dict(task) for task in tasks]
        for task in self.dispatched[: self.release]:
            on_result(success_result(task))
        raise SystemExit("模拟宿主崩溃")

    def cancel(self) -> None:
        return None


class BlockingRunsJobService(JobService):
    """首次读取比赛记录时阻塞，用于构造取消早于派发的窗口。"""

    def __init__(self, repository: Any, publisher: EventPublisher):
        super().__init__(repository, publisher)
        self.entered = threading.Event()
        self.release = threading.Event()

    def runs(self, job_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if not self.entered.is_set():
            self.entered.set()
            if not self.release.wait(WAIT_SECONDS):
                raise RuntimeError("取消窗口等待超时")
        return super().runs(job_id, limit=limit, offset=offset)


class MatrixHarness:
    """每个 worker 档位独立的存储、事件、引擎与实验服务装配。"""

    def __init__(self, directory: Path, engine: EnginePort | None = None, *, name: str = "engine"):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.publisher = EventPublisher(history_limit=100_000)
        database = Database(self.directory / "fm27lab.db")
        database.initialize()
        self.job_service = JobService(JobRepository(database), self.publisher)
        inner = self.native_engine(name) if engine is None else engine
        self.inner = inner
        self.engine = RecordingEngine(inner)
        self.service = self.make_service(self.engine)

    def native_engine(self, name: str = "engine") -> LazyNativeEngine:
        """创建默认匹配立刻完成的原生引擎适配器。"""
        root = self.directory / name / "engine"
        work = self.directory / name / "work"
        fixtures = root / "fm27_native" / "fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        (fixtures / "match.pkm").write_bytes(b"fake match fixture")
        work.mkdir(parents=True, exist_ok=True)
        return LazyNativeEngine(root, work, factory=fake_host_factory)

    def make_service(self, engine: EnginePort) -> ExperimentService:
        return ExperimentService(
            self.job_service,
            engine,
            lambda: plan_runtime(
                engine.capabilities(),
                has_pool_variants=False,
                has_experimental_execution=False,
            ),
            self.publisher,
        )

    def submit(self, *, workers: int) -> dict[str, Any]:
        return self.service.submit(
            {"seeds": list(MATRIX_SEEDS), "variants": list(MATRIX_VARIANTS)},
            workers=workers,
            cpu_count=MATRIX_CPU_COUNT,
            available_memory_bytes=MATRIX_AVAILABLE_MEMORY,
            free_disk_bytes=MATRIX_FREE_DISK,
        )


@pytest.mark.parametrize("workers", MATRIX_WORKERS)
def test_matrix_worker_counts_preserve_result_identity(tmp_path, workers):
    harness = MatrixHarness(tmp_path / f"identity-{workers}")
    with harness.publisher.subscriber() as subscription:
        job = harness.submit(workers=workers)
        final = harness.service.start_next()
        events = drain_events(subscription)
    assert job["workers"] == workers
    assert job["summary"]["runtime_mode"] == "reused_worker"
    assert final is not None
    assert final["status"] == "completed"
    assert final["completed"] == EXPECTED_TOTAL
    assert harness.engine.workers == workers
    assert len(session_directories(harness.directory)) == min(workers, EXPECTED_TOTAL)
    runs = read_runs(harness.job_service, job["id"])
    assert_identity(runs)
    progress = assert_progress_consistent(events, job_id=job["id"], run_count=EXPECTED_TOTAL)
    assert max(event["data"]["completed"] for event in progress) == EXPECTED_TOTAL
    assert_final_event(
        events,
        name="experiment.completed",
        job_id=job["id"],
        status="completed",
        completed=EXPECTED_TOTAL,
        total=EXPECTED_TOTAL,
    )


def test_matrix_worker_counts_share_result_distribution(tmp_path):
    distributions: list[dict[tuple[str, int], tuple[Any, ...]]] = []
    for workers in MATRIX_WORKERS:
        harness = MatrixHarness(tmp_path / f"distribution-{workers}")
        job = harness.submit(workers=workers)
        assert harness.service.start_next() is not None
        distribution = result_distribution(read_runs(harness.job_service, job["id"]))
        assert len(distribution) == EXPECTED_TOTAL
        distributions.append(distribution)
    assert distributions[0] == distributions[1] == distributions[2]


@pytest.mark.parametrize("workers", MATRIX_WORKERS)
def test_cancel_keeps_accepted_results_and_marks_job_cancelled(tmp_path, workers):
    gated = GatedEngine(release=2)
    harness = MatrixHarness(tmp_path / f"cancel-{workers}", gated)
    failures: list[BaseException] = []

    def dispatch() -> None:
        try:
            harness.service.start_next()
        except BaseException as error:
            failures.append(error)

    with harness.publisher.subscriber() as subscription:
        job = harness.submit(workers=workers)
        thread = threading.Thread(target=dispatch, daemon=True)
        thread.start()
        assert gated.started.wait(WAIT_SECONDS)
        current = harness.service.cancel(job["id"])
        thread.join(WAIT_SECONDS)
        events = drain_events(subscription)
    assert not thread.is_alive()
    assert failures == []
    assert current["status"] in {"running", "cancelled"}
    final = harness.job_service.get(job["id"])
    assert final is not None
    assert final["status"] == "cancelled"
    assert final["completed"] == 2
    runs = read_runs(harness.job_service, job["id"])
    assert task_pairs(runs) == list(EXPECTED_PAIRS[:2])
    assert [run["sequence"] for run in runs] == [1, 2]
    assert harness.engine.workers == workers
    assert gated.cancel_calls == 1
    assert task_pairs(harness.engine.dispatched) == list(EXPECTED_PAIRS)
    progress = assert_progress_consistent(events, job_id=job["id"], run_count=2)
    assert max(event["data"]["completed"] for event in progress) == 2
    assert_final_event(
        events,
        name="experiment.cancelled",
        job_id=job["id"],
        status="cancelled",
        completed=2,
        total=EXPECTED_TOTAL,
    )


@pytest.mark.parametrize("workers", MATRIX_WORKERS)
def test_resume_runs_only_missing_matches(tmp_path, workers):
    crash = CrashEngine(release=2)
    harness = MatrixHarness(tmp_path / f"resume-{workers}", crash)
    with harness.publisher.subscriber() as subscription:
        job = harness.submit(workers=workers)
        with pytest.raises(SystemExit):
            harness.service.start_next()
        interrupted = harness.job_service.update(job["id"], {"status": "interrupted"})
        assert interrupted["status"] == "interrupted"
        assert interrupted["completed"] == 2
        assert harness.service.resume(job["id"])["status"] == "queued"
        resumed_engine = RecordingEngine(harness.native_engine("resume"))
        final = harness.make_service(resumed_engine).start_next()
        events = drain_events(subscription)
    assert final is not None
    assert final["status"] == "completed"
    assert final["completed"] == EXPECTED_TOTAL
    assert resumed_engine.workers == workers
    assert task_pairs(resumed_engine.dispatched) == list(EXPECTED_PAIRS[2:])
    remaining = EXPECTED_TOTAL - 2
    assert len(session_directories(harness.directory, "resume")) == min(workers, remaining)
    runs = read_runs(harness.job_service, job["id"])
    assert_identity(runs)
    progress = assert_progress_consistent(events, job_id=job["id"], run_count=EXPECTED_TOTAL)
    assert max(event["data"]["completed"] for event in progress) == EXPECTED_TOTAL
    resumed = [event for event in events if event["event"] == "experiment.resumed"]
    assert len(resumed) == 1
    assert_final_event(
        events,
        name="experiment.completed",
        job_id=job["id"],
        status="completed",
        completed=EXPECTED_TOTAL,
        total=EXPECTED_TOTAL,
    )


def test_cancel_before_dispatch_skips_engine_batch(tmp_path):
    """取消在派发前到达时不启动引擎，终态为取消且无结果。"""
    gated = GatedEngine(release=0)
    harness = MatrixHarness(tmp_path / "cancel-before-dispatch", gated)
    blocking = BlockingRunsJobService(harness.job_service.repository, harness.publisher)
    harness.job_service = blocking
    harness.service = harness.make_service(harness.engine)
    failures: list[str] = []

    def dispatch() -> None:
        try:
            harness.service.start_next()
        except BaseException as error:  # noqa: BLE001
            failures.append(repr(error))

    with harness.publisher.subscriber() as subscription:
        job = harness.submit(workers=1)
        thread = threading.Thread(target=dispatch, daemon=True)
        thread.start()
        assert blocking.entered.wait(WAIT_SECONDS)
        current = harness.service.cancel(job["id"])
        blocking.release.set()
        thread.join(WAIT_SECONDS)
        events = drain_events(subscription)
    assert not thread.is_alive()
    assert failures == []
    assert current["status"] == "running"
    final = blocking.get(job["id"])
    assert final is not None
    assert final["status"] == "cancelled"
    assert final["completed"] == 0
    assert harness.engine.dispatched == []
    assert gated.started.is_set() is False
    assert gated.cancel_calls == 1
    assert read_runs(blocking, job["id"]) == []
    assert_final_event(
        events,
        name="experiment.cancelled",
        job_id=job["id"],
        status="cancelled",
        completed=0,
        total=EXPECTED_TOTAL,
    )


def test_cancel_during_configure_skips_engine_batch(tmp_path):
    """取消在配置并行度期间到达时不派发引擎批次。"""
    gated = CancelOnConfigureEngine()
    harness = MatrixHarness(tmp_path / "cancel-during-configure", gated)
    failures: list[str] = []

    def dispatch() -> None:
        try:
            harness.service.start_next()
        except BaseException as error:  # noqa: BLE001
            failures.append(repr(error))

    with harness.publisher.subscriber() as subscription:
        job = harness.submit(workers=1)
        gated.cancel_hook = lambda: harness.service.cancel(job["id"])
        thread = threading.Thread(target=dispatch, daemon=True)
        thread.start()
        thread.join(WAIT_SECONDS)
        events = drain_events(subscription)
    assert not thread.is_alive()
    assert failures == []
    final = harness.job_service.get(job["id"])
    assert final is not None
    assert final["status"] == "cancelled"
    assert final["completed"] == 0
    assert harness.engine.dispatched == []
    assert gated.started.is_set() is False
    assert gated.cancel_calls == 1
    assert read_runs(harness.job_service, job["id"]) == []
    assert_final_event(
        events,
        name="experiment.cancelled",
        job_id=job["id"],
        status="cancelled",
        completed=0,
        total=EXPECTED_TOTAL,
    )

