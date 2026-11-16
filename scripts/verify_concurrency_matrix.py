"""并发验收矩阵：1、8、256 路的提交、取消、续跑与结果身份一致性。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import shutil
import sys
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:
    resource = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fm27lab import __version__ as SOURCE_VERSION  # noqa: E402
from fm27lab.adapters.engine_native import NativeEngineHost, plan_runtime  # noqa: E402
from fm27lab.adapters.engine_native.lazy import LazyNativeEngine  # noqa: E402
from fm27lab.adapters.storage_sqlite.db import Database  # noqa: E402
from fm27lab.adapters.storage_sqlite.repositories import JobRepository  # noqa: E402
from fm27lab.application.events import EventPublisher, EventSubscription  # noqa: E402
from fm27lab.application.experiments import (  # noqa: E402
    CANCEL_ERROR,
    RESUME_ERROR,
    ExperimentService,
)
from fm27lab.application.jobs import JobService  # noqa: E402
from fm27lab.domain.concurrency import (  # noqa: E402
    MAX_WORKERS,
    WARNING_OVERRIDE,
    resource_check,
    validate_workers,
)
from fm27lab.ports.engine import EngineCapabilities, EnginePort  # noqa: E402

DEFAULT_SIMULATOR = ROOT / "fm27lab" / "tests" / "fixtures" / "fake_simulator.py"
DEFAULT_WORKERS = (1, 8, 256)
DEFAULT_MATCHES = 256
MAX_MATCHES = 10000
DEFAULT_TIMEOUT_SECONDS = 90.0
CLEANUP_SECONDS = 5.0
GIB = 1024**3
MATRIX_VARIANTS = ("A", "B")
HISTORY_LIMIT = 100_000
WORKER_WAIT_SECONDS = 120.0
CANCEL_LIMIT_SECONDS = 30.0
CRASH_ACCEPTED_MATCHES = 32
RESIDUAL_WAIT_SECONDS = 5.0
EVIDENCE_ROOT = ROOT / "dist"
FAKE_FIXTURE_BYTES = b"fake match fixture"
CRASH_MESSAGE = "模拟宿主崩溃"

ResultCallback = Callable[[Mapping[str, Any]], None]
ProgressCallback = Callable[[Sequence[Mapping[str, Any]]], None]
HostFactory = Callable[..., NativeEngineHost]


class VerificationError(RuntimeError):
    """验收无法继续执行时抛出的错误。"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _posix_memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_AVPHYS_PAGES"))
    except (AttributeError, ValueError, OSError):
        return 0


def windows_memory_bytes() -> int:
    """Read available physical memory on Windows through the Win32 API."""
    if sys.platform != "win32":
        return 0
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return 0
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) == 0:
        return 0
    return int(status.available_physical)


def available_memory_bytes() -> int:
    measured = _posix_memory_bytes()
    if measured > 0:
        return measured
    return windows_memory_bytes()


def measured_resources() -> dict[str, int]:
    memory = available_memory_bytes()
    if memory <= 0:
        raise VerificationError("无法读取可用内存")
    usage = shutil.disk_usage(ROOT)
    return {
        "cpu_count": os.cpu_count() or 1,
        "available_memory_bytes": memory,
        "free_disk_bytes": int(usage.free),
    }


def applied_resources(
    measured: Mapping[str, int], arguments: argparse.Namespace
) -> dict[str, int]:
    """Apply CLI capacity overrides to the measured host resources."""
    resources = dict(measured)
    for key, override in (
        ("available_memory_bytes", arguments.available_memory_bytes),
        ("free_disk_bytes", arguments.free_disk_bytes),
    ):
        if override is None:
            continue
        if override <= 0:
            raise VerificationError("资源覆盖值必须为正数")
        resources[key] = int(override)
    return resources


def resolve_simulator(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise VerificationError(f"模拟器文件不存在：{path}")
    if path.suffix.lower() == ".py":
        if not os.access(path, os.R_OK):
            raise VerificationError(f"模拟器脚本不可读：{path}")
    elif not os.access(path, os.X_OK):
        raise VerificationError(f"模拟器文件不可执行：{path}")
    return path


def expected_score(seed: int) -> tuple[int, int]:
    """假模拟器按种子生成的确定性比分。"""
    return seed % 4, (seed * 7) % 3


def expected_pairs(seeds: Sequence[int], variants: Sequence[str]) -> list[tuple[str, int]]:
    """任务批次顺序：种子外层、变体内层。"""
    return [(variant, seed) for seed in seeds for variant in variants]


def task_pairs(items: Sequence[Mapping[str, Any]]) -> list[tuple[str, int]]:
    return [(str(item["variant"]), int(item["seed"])) for item in items]


def read_runs(job_service: JobService, job_id: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = job_service.runs(job_id, limit=200, offset=offset)
        runs.extend(page["items"])
        if page["next_offset"] is None:
            return runs
        offset = page["next_offset"]


def job_error(final: Mapping[str, Any] | None) -> str | None:
    """Expose the recorded batch error so a failed case is diagnosable from the report."""
    if final is None:
        return None
    error = (final.get("summary") or {}).get("error")
    return str(error) if error else None


def runs_digest(runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    digest = []
    for run in runs:
        teams = (run.get("stats") or {}).get("teams") or []
        digest.append(
            {
                "sequence": run["sequence"],
                "variant": run["variant"],
                "seed": run["seed"],
                "score": run["score"],
                "verified": run["verified"],
                "shots": [team.get("shots") for team in teams],
            }
        )
    return digest


def distribution_from_digest(digest: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], tuple[Any, ...]]:
    return {
        (str(item["variant"]), int(item["seed"])): (tuple(item["score"]), tuple(item["shots"]))
        for item in digest
    }


def session_directory_count(work_directory: Path) -> int:
    sessions = work_directory / "worker_sessions"
    if not sessions.is_dir():
        return 0
    return sum(1 for path in sessions.iterdir() if path.is_dir())


def simulate_process_count(simulator: Path) -> int | None:
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    target = str(simulator).encode()
    count = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if target in cmdline:
            count += 1
    return count


def wait_residual_processes(simulator: Path, *, timeout: float = RESIDUAL_WAIT_SECONDS) -> int | None:
    count = simulate_process_count(simulator)
    deadline = time.monotonic() + timeout
    while count not in (None, 0) and time.monotonic() < deadline:
        time.sleep(0.05)
        count = simulate_process_count(simulator)
    return count


def peak_child_megabytes() -> float | None:
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return round(usage.ru_maxrss / 1024.0, 1)


def accepts_workers(value: object) -> bool:
    try:
        validate_workers(value)
    except ValueError:
        return False
    return True


class CheckLog:
    """收集验收检查项，并支持按作用域汇总。"""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def record(self, scope: str, name: str, passed: bool, detail: str = "") -> bool:
        self.items.append(
            {"scope": scope, "name": name, "passed": bool(passed), "detail": detail}
        )
        return bool(passed)

    def passed_scope(self, scope: str) -> bool:
        return all(item["passed"] for item in self.items if item["scope"] == scope)

    def passed(self) -> bool:
        return all(item["passed"] for item in self.items)

    def failures(self) -> list[dict[str, Any]]:
        return [item for item in self.items if not item["passed"]]


class EventCollector:
    """按发布顺序收集事件，并可阻塞等待满足条件的事件。"""

    def __init__(self, publisher: EventPublisher) -> None:
        self._publisher = publisher
        self._manager: Any = None
        self._subscription: EventSubscription | None = None
        self.events: list[dict[str, Any]] = []

    def __enter__(self) -> EventCollector:
        self._manager = self._publisher.subscriber()
        self._subscription = self._manager.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        manager = self._manager
        self._manager = None
        self._subscription = None
        if manager is not None:
            manager.__exit__(exc_type, exc, traceback)

    def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float,
    ) -> dict[str, Any] | None:
        subscription = self._subscription
        if subscription is None:
            raise VerificationError("事件订阅未打开")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                event = subscription.get(timeout=remaining)
            except queue.Empty:
                return None
            if event is None:
                return None
            self.events.append(event)
            if predicate(event):
                return event

    def drain(self) -> list[dict[str, Any]]:
        subscription = self._subscription
        if subscription is None:
            raise VerificationError("事件订阅未打开")
        while True:
            try:
                event = subscription.get_nowait()
            except queue.Empty:
                return self.events
            if event is None:
                return self.events
            self.events.append(event)


class RecordingEngine:
    """记录下发任务与并行数，并把执行委托给内层引擎。"""

    def __init__(self, inner: EnginePort) -> None:
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


class FixtureEngine:
    """按任务顺序交替注入快慢匹配场景，用于真实适配器上的取消验收。"""

    def __init__(self, inner: EnginePort, slow_fixture: Path, fast_fixture: Path) -> None:
        self._inner = inner
        self._slow_fixture = slow_fixture
        self._fast_fixture = fast_fixture
        self.cancel_calls = 0

    def capabilities(self) -> EngineCapabilities:
        return self._inner.capabilities()

    def configure_workers(self, workers: int) -> None:
        configure = getattr(self._inner, "configure_workers", None)
        if callable(configure):
            configure(workers)

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: ResultCallback,
        on_progress: ProgressCallback,
    ) -> None:
        enriched = [
            dict(task, fixture=str(self._slow_fixture if index % 2 else self._fast_fixture))
            for index, task in enumerate(tasks)
        ]
        self._inner.run_batch(enriched, on_result, on_progress)

    def cancel(self) -> None:
        self.cancel_calls += 1
        self._inner.cancel()


class CrashAfterEngine:
    """受理固定数量结果后模拟宿主崩溃，用于续跑验收。"""

    def __init__(self, inner: EnginePort, limit: int) -> None:
        self._inner = inner
        self.limit = limit
        self.accepted = 0

    def capabilities(self) -> EngineCapabilities:
        return self._inner.capabilities()

    def configure_workers(self, workers: int) -> None:
        configure = getattr(self._inner, "configure_workers", None)
        if callable(configure):
            configure(workers)

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: ResultCallback,
        on_progress: ProgressCallback,
    ) -> None:
        def collect(result: Mapping[str, Any]) -> None:
            if self.accepted >= self.limit:
                raise SystemExit(CRASH_MESSAGE)
            on_result(result)
            self.accepted += 1
            if self.accepted >= self.limit:
                raise SystemExit(CRASH_MESSAGE)

        self._inner.run_batch(tasks, collect, on_progress)

    def cancel(self) -> None:
        self._inner.cancel()


class BlockingRunsJobService(JobService):
    """首次读取比赛记录时阻塞，用于构造取消早于派发的窗口。"""

    def __init__(self, repository: JobRepository, publisher: EventPublisher) -> None:
        super().__init__(repository, publisher)
        self.entered = threading.Event()
        self.release = threading.Event()

    def runs(self, job_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if not self.entered.is_set():
            self.entered.set()
            if not self.release.wait(WORKER_WAIT_SECONDS):
                raise RuntimeError("取消窗口等待超时")
        return super().runs(job_id, limit=limit, offset=offset)


class DispatchSpyEngine:
    """记录批次派发与取消次数的空引擎，用于验证取消先于派发。"""

    def __init__(self) -> None:
        self.batches: list[list[tuple[str, int]]] = []
        self.cancel_calls = 0
        self.workers: int | None = None

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            counted_sessions=True,
            jobs_per_session=None,
            session_scope="remaining_batch_lane",
            capability_version=2,
        )

    def configure_workers(self, workers: int) -> None:
        self.workers = workers

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: ResultCallback,
        on_progress: ProgressCallback,
    ) -> None:
        self.batches.append(task_pairs(tasks))

    def cancel(self) -> None:
        self.cancel_calls += 1


def host_factory(simulator: Path, timeout_seconds: float) -> HostFactory:
    def factory(root: Path, work_dir: Path, **options: Any) -> NativeEngineHost:
        return NativeEngineHost(
            root,
            work_dir,
            executable=simulator,
            retries=0,
            timeout_seconds=timeout_seconds,
            cleanup_seconds=CLEANUP_SECONDS,
            **options,
        )

    return factory


def make_engine(directory: Path, simulator: Path, *, timeout_seconds: float) -> LazyNativeEngine:
    root = directory / "engine"
    work = directory / "work"
    fixtures = root / "fm27_native" / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures / "match.pkm").write_bytes(FAKE_FIXTURE_BYTES)
    (fixtures / "slow.pkm").write_bytes(FAKE_FIXTURE_BYTES)
    work.mkdir(parents=True, exist_ok=True)
    return LazyNativeEngine(root, work, factory=host_factory(simulator, timeout_seconds))


def runtime_plan_for(engine: EnginePort) -> Callable[[], Any]:
    return lambda: plan_runtime(
        engine.capabilities(),
        has_pool_variants=False,
        has_experimental_execution=False,
    )


def make_service(
    service_dir: Path, engine: EnginePort
) -> tuple[ExperimentService, JobService, EventPublisher]:
    service_dir.mkdir(parents=True, exist_ok=True)
    database = Database(service_dir / "fm27lab.db")
    database.initialize()
    publisher = EventPublisher(history_limit=HISTORY_LIMIT)
    job_service = JobService(JobRepository(database), publisher)
    service = ExperimentService(job_service, engine, runtime_plan_for(engine), publisher)
    return service, job_service, publisher


def submit_batch(
    service: ExperimentService,
    *,
    seeds: Sequence[int],
    variants: Sequence[str],
    workers: int,
    resources: Mapping[str, int],
    allow_oversubscription: bool = False,
) -> dict[str, Any]:
    return service.submit(
        {"seeds": list(seeds), "variants": list(variants)},
        workers=workers,
        cpu_count=resources["cpu_count"],
        available_memory_bytes=resources["available_memory_bytes"],
        free_disk_bytes=resources["free_disk_bytes"],
        allow_oversubscription=allow_oversubscription,
    )


def verify_complete_identity(
    log: CheckLog, scope: str, runs: Sequence[Mapping[str, Any]], pairs: Sequence[tuple[str, int]]
) -> None:
    total = len(pairs)
    log.record(scope, "结果总数", len(runs) == total, f"实际 {len(runs)}，期望 {total}")
    sequences = [int(run["sequence"]) for run in runs]
    log.record(scope, "结果序列连续", sequences == list(range(1, total + 1)), str(sequences[:3]))
    actual_pairs = task_pairs(runs)
    log.record(scope, "结果身份唯一", len(set(actual_pairs)) == len(actual_pairs))
    log.record(scope, "结果身份匹配任务", sorted(actual_pairs) == sorted(pairs))
    mismatched: list[tuple[Any, ...]] = []
    for run in runs:
        seed = int(run["seed"])
        home, away = expected_score(seed)
        teams = (run.get("stats") or {}).get("teams") or []
        shots = [team.get("shots") for team in teams]
        if run["score"] != [home, away] or run["verified"] is not True or shots != [home + 5, away + 5]:
            mismatched.append((run["sequence"], run["variant"], seed, run["score"], shots))
    log.record(scope, "比分与种子映射", not mismatched, f"异常 {mismatched[:5]}")


def verify_accepted_identity(
    log: CheckLog,
    scope: str,
    runs: Sequence[Mapping[str, Any]],
    pairs: Sequence[tuple[str, int]],
    completed: int,
) -> None:
    log.record(scope, "已受理结果数", len(runs) == completed, f"记录 {len(runs)}，完成 {completed}")
    sequences = [int(run["sequence"]) for run in runs]
    log.record(scope, "已受理序列连续", sequences == list(range(1, completed + 1)), str(sequences[:3]))
    actual_pairs = task_pairs(runs)
    log.record(scope, "已受理身份唯一", len(set(actual_pairs)) == len(actual_pairs))
    log.record(scope, "已受理任务不串场", set(actual_pairs) <= set(pairs))
    mismatched: list[tuple[Any, ...]] = []
    for run in runs:
        home, away = expected_score(int(run["seed"]))
        if run["score"] != [home, away] or run["verified"] is not True:
            mismatched.append((run["sequence"], run["variant"], int(run["seed"]), run["score"]))
    log.record(scope, "已受理比分映射", not mismatched, f"异常 {mismatched[:5]}")


def verify_progress(
    log: CheckLog,
    scope: str,
    events: Sequence[Mapping[str, Any]],
    *,
    job_id: str,
    run_count: int,
) -> None:
    run_events = [
        event for event in events if event["event"] == "job.run" and event["data"]["job_id"] == job_id
    ]
    log.record(scope, "job.run 计数", len(run_events) == run_count, f"{len(run_events)}/{run_count}")
    completed_values = [int(event["data"]["completed"]) for event in run_events]
    log.record(
        scope,
        "job.run 完成数连续",
        completed_values == list(range(1, run_count + 1)),
        str(completed_values[:3]),
    )
    accepted = 0
    previous = 0
    monotonic = True
    consistent = True
    progress_count = 0
    mismatched: list[tuple[Any, Any]] = []
    for event in events:
        data = event.get("data") or {}
        if data.get("job_id") != job_id:
            continue
        if event["event"] == "job.run":
            accepted += 1
        elif event["event"] == "experiment.progress":
            progress_count += 1
            completed = int(data["completed"])
            if completed != accepted:
                consistent = False
                mismatched.append((completed, accepted))
            if completed < previous:
                monotonic = False
            previous = completed
    log.record(scope, "进度计数与完成数一致", consistent, f"不一致 {mismatched[:5]}")
    log.record(scope, "进度单调不减", monotonic)
    log.record(scope, "进度事件存在", progress_count > 0, f"{progress_count} 条")


def verify_final_event(
    log: CheckLog,
    scope: str,
    events: Sequence[Mapping[str, Any]],
    *,
    name: str,
    job_id: str,
    status: str,
    completed: int,
    total: int,
) -> None:
    finals = [
        event
        for event in events
        if event["event"] == name and (event.get("data") or {}).get("job_id") == job_id
    ]
    expected = {"job_id": job_id, "status": status, "completed": completed, "total": total}
    matched = len(finals) == 1 and dict(finals[0]["data"]) == expected
    log.record(scope, "终态事件唯一且一致", matched, f"事件数 {len(finals)}")


def run_preflight(
    log: CheckLog,
    resources: Mapping[str, int],
    workers_values: Sequence[int],
    simulator: Path,
) -> list[dict[str, Any]]:
    bounds_scope = "preflight/bounds"
    log.record(bounds_scope, "下界 1 合法", accepts_workers(1))
    log.record(bounds_scope, "上界 256 合法", accepts_workers(MAX_WORKERS))
    log.record(bounds_scope, "0 被拒绝", not accepts_workers(0))
    log.record(bounds_scope, "257 被拒绝", not accepts_workers(MAX_WORKERS + 1))
    log.record(bounds_scope, "非整数被拒绝", not accepts_workers("8"))
    records: list[dict[str, Any]] = []
    for workers in workers_values:
        scope = f"preflight/workers={workers}"
        check = resource_check(
            workers,
            cpu_count=resources["cpu_count"],
            available_memory_bytes=resources["available_memory_bytes"],
            free_disk_bytes=resources["free_disk_bytes"],
        )
        log.record(scope, "资源预检通过", check["allowed"] is True, str(check["code"] or ""))
        log.record(
            scope,
            "推荐并行数有效",
            1 <= int(check["recommended_workers"]) <= MAX_WORKERS,
            str(check["recommended_workers"]),
        )
        records.append(
            {
                "workers": workers,
                "allowed": check["allowed"],
                "code": check["code"],
                "recommended_workers": check["recommended_workers"],
                "memory_required_bytes": check["memory_required_bytes"],
                "disk_required_bytes": check["disk_required_bytes"],
                "warnings": list(check["warnings"]),
            }
        )
    gate_scope = "preflight/gate"
    memory_blocked = resource_check(
        1,
        cpu_count=resources["cpu_count"],
        available_memory_bytes=GIB,
        free_disk_bytes=resources["free_disk_bytes"],
    )
    log.record(
        gate_scope,
        "内存不足被拒绝",
        memory_blocked["allowed"] is False and memory_blocked["code"] == "insufficient_memory",
        str(memory_blocked["code"]),
    )
    memory_overridden = resource_check(
        1,
        cpu_count=resources["cpu_count"],
        available_memory_bytes=GIB,
        free_disk_bytes=resources["free_disk_bytes"],
        allow_oversubscription=True,
    )
    log.record(
        gate_scope,
        "内存不足可显式覆盖",
        memory_overridden["allowed"] is True and WARNING_OVERRIDE in memory_overridden["warnings"],
        str(memory_overridden["warnings"]),
    )
    disk_blocked = resource_check(
        MAX_WORKERS,
        cpu_count=resources["cpu_count"],
        available_memory_bytes=32 * GIB,
        free_disk_bytes=MAX_WORKERS * GIB + GIB // 2,
    )
    log.record(
        gate_scope,
        "磁盘不足被拒绝",
        disk_blocked["allowed"] is False and disk_blocked["code"] == "insufficient_disk",
        str(disk_blocked["code"]),
    )
    disk_overridden = resource_check(
        MAX_WORKERS,
        cpu_count=resources["cpu_count"],
        available_memory_bytes=32 * GIB,
        free_disk_bytes=MAX_WORKERS * GIB + GIB // 2,
        allow_oversubscription=True,
    )
    log.record(
        gate_scope,
        "磁盘不足可显式覆盖",
        disk_overridden["allowed"] is True and WARNING_OVERRIDE in disk_overridden["warnings"],
        str(disk_overridden["warnings"]),
    )
    records.append({"simulator": str(simulator), "gate": gate_scope})
    return records


def run_matrix_case(
    base_directory: Path,
    log: CheckLog,
    *,
    workers: int,
    seeds: Sequence[int],
    variants: Sequence[str],
    total: int,
    simulator: Path,
    resources: Mapping[str, int],
    timeout_seconds: float,
) -> dict[str, Any]:
    scope = f"matrix/workers={workers}"
    case_directory = base_directory / f"matrix-{workers}"
    engine = make_engine(case_directory, simulator, timeout_seconds=timeout_seconds)
    service, job_service, publisher = make_service(case_directory, engine)
    pairs = expected_pairs(seeds, variants)
    collector = EventCollector(publisher)
    with collector:
        job = submit_batch(service, seeds=seeds, variants=variants, workers=workers, resources=resources)
        started = time.perf_counter()
        final = service.start_next()
        seconds = time.perf_counter() - started
        collector.drain()
    runs = read_runs(job_service, job["id"])
    sessions = session_directory_count(case_directory / "work")
    seconds = round(seconds, 4)
    throughput = round(total / seconds, 4) if seconds > 0 else 0.0
    log.record(scope, "任务并行数", job["workers"] == workers, str(job["workers"]))
    runtime_mode = (job.get("summary") or {}).get("runtime_mode")
    log.record(scope, "运行时模式复用会话", runtime_mode == "reused_worker", str(runtime_mode))
    log.record(
        scope,
        "批次完成",
        final is not None and final["status"] == "completed" and final["completed"] == total,
        str(final["status"] if final else None),
    )
    verify_complete_identity(log, scope, runs, pairs)
    verify_progress(log, scope, collector.events, job_id=job["id"], run_count=total)
    verify_final_event(
        log,
        scope,
        collector.events,
        name="experiment.completed",
        job_id=job["id"],
        status="completed",
        completed=total,
        total=total,
    )
    log.record(
        scope,
        "并行分道数",
        sessions == min(workers, total),
        f"会话 {sessions}，期望 {min(workers, total)}",
    )
    log.record(scope, "吞吐为正", throughput > 0, f"{throughput} 场每秒")
    error = job_error(final)
    log.record(scope, "批次无错误记录", error is None, error or "")
    return {
        "phase": "matrix",
        "workers": workers,
        "scope": scope,
        "total": total,
        "completed": final["completed"] if final else 0,
        "seconds": seconds,
        "matches_per_second": throughput,
        "sessions": sessions,
        "peak_child_megabytes": peak_child_megabytes(),
        "results": runs_digest(runs),
        "error": error,
        "events": collector.events,
    }


def run_cancel_case(
    base_directory: Path,
    log: CheckLog,
    *,
    workers: int,
    seeds: Sequence[int],
    variants: Sequence[str],
    total: int,
    simulator: Path,
    resources: Mapping[str, int],
    timeout_seconds: float,
) -> dict[str, Any]:
    scope = f"cancel/workers={workers}"
    case_directory = base_directory / f"cancel-{workers}"
    fixtures = case_directory / "engine" / "fm27_native" / "fixtures"
    engine = FixtureEngine(
        make_engine(case_directory, simulator, timeout_seconds=timeout_seconds),
        fixtures / "slow.pkm",
        fixtures / "match.pkm",
    )
    service, job_service, publisher = make_service(case_directory, engine)
    pairs = expected_pairs(seeds, variants)
    failures: list[str] = []

    def dispatch() -> None:
        try:
            service.start_next()
        except BaseException as error:  # noqa: BLE001
            failures.append(repr(error))

    collector = EventCollector(publisher)
    with collector:
        job = submit_batch(service, seeds=seeds, variants=variants, workers=workers, resources=resources)
        thread = threading.Thread(target=dispatch, daemon=True)
        started = time.perf_counter()
        thread.start()
        first = collector.wait_for(
            lambda event: event["event"] == "job.run" and event["data"]["job_id"] == job["id"],
            timeout=WORKER_WAIT_SECONDS,
        )
        if first is None:
            raise VerificationError("取消验收未收到首场完成结果")
        cancel_return = service.cancel(job["id"])
        thread.join(WORKER_WAIT_SECONDS)
        seconds = time.perf_counter() - started
        collector.drain()
    if thread.is_alive():
        raise VerificationError("取消验收等待批次退出超时")
    events = collector.events
    final = job_service.get(job["id"])
    if final is None:
        raise VerificationError("取消验收读取任务记录失败")
    runs = read_runs(job_service, job["id"])
    completed = int(final["completed"])
    sessions = session_directory_count(case_directory / "work")
    seconds = round(seconds, 4)
    residual = wait_residual_processes(simulator)
    log.record(scope, "批处理线程无异常", not failures, str(failures[:1]))
    log.record(scope, "取消返回未完成终态", cancel_return["status"] in {"running", "cancelled"})
    log.record(scope, "任务终态为取消", final["status"] == "cancelled", str(final["status"]))
    log.record(scope, "完成数与结果数一致", completed == len(runs), f"{completed}/{len(runs)}")
    log.record(scope, "取消时仍有未完成场次", 0 < completed < total, f"{completed}/{total}")
    verify_accepted_identity(log, scope, runs, pairs, completed)
    verify_progress(log, scope, events, job_id=job["id"], run_count=completed)
    verify_final_event(
        log,
        scope,
        events,
        name="experiment.cancelled",
        job_id=job["id"],
        status="cancelled",
        completed=completed,
        total=total,
    )
    log.record(scope, "取消信号下发一次", engine.cancel_calls == 1, str(engine.cancel_calls))
    log.record(
        scope,
        "取消耗时远小于串行",
        seconds < CANCEL_LIMIT_SECONDS,
        f"{seconds}s < {CANCEL_LIMIT_SECONDS}s",
    )
    log.record(
        scope,
        "取消时分道数受控",
        1 <= sessions <= min(workers, total),
        f"会话 {sessions}，上限 {min(workers, total)}",
    )
    if residual is None:
        log.record(scope, "无残留模拟器进程", True, "当前平台不提供 /proc")
    else:
        log.record(scope, "无残留模拟器进程", residual == 0, f"残留 {residual}")
    try:
        service.cancel(job["id"])
    except ValueError as error:
        log.record(scope, "重复取消被拒绝", str(error) == CANCEL_ERROR, str(error))
    else:
        log.record(scope, "重复取消被拒绝", False, "重复取消未报错")
    try:
        service.resume(job["id"])
    except ValueError as error:
        log.record(scope, "取消后不可续跑", str(error) == RESUME_ERROR, str(error))
    else:
        log.record(scope, "取消后不可续跑", False, "取消态续跑未报错")
    return {
        "phase": "cancel",
        "workers": workers,
        "scope": scope,
        "total": total,
        "completed": completed,
        "seconds": seconds,
        "matches_per_second": round(completed / seconds, 4) if seconds > 0 else 0.0,
        "sessions": sessions,
        "peak_child_megabytes": peak_child_megabytes(),
        "results": runs_digest(runs),
        "events": events,
    }


def run_dispatch_race_case(
    base_directory: Path,
    log: CheckLog,
    *,
    workers: int,
    seeds: Sequence[int],
    variants: Sequence[str],
    total: int,
    resources: Mapping[str, int],
) -> dict[str, Any]:
    scope = f"cancel-race/workers={workers}"
    case_directory = base_directory / f"cancel-race-{workers}"
    case_directory.mkdir(parents=True, exist_ok=True)
    database = Database(case_directory / "fm27lab.db")
    database.initialize()
    publisher = EventPublisher(history_limit=HISTORY_LIMIT)
    engine = DispatchSpyEngine()
    job_service = BlockingRunsJobService(JobRepository(database), publisher)
    service = ExperimentService(job_service, engine, runtime_plan_for(engine), publisher)
    failures: list[str] = []

    def dispatch() -> None:
        try:
            service.start_next()
        except BaseException as error:  # noqa: BLE001
            failures.append(repr(error))

    collector = EventCollector(publisher)
    with collector:
        job = submit_batch(service, seeds=seeds, variants=variants, workers=workers, resources=resources)
        thread = threading.Thread(target=dispatch, daemon=True)
        started = time.perf_counter()
        thread.start()
        if not job_service.entered.wait(WORKER_WAIT_SECONDS):
            job_service.release.set()
            raise VerificationError("派发前取消验收未进入读取窗口")
        cancel_return = service.cancel(job["id"])
        job_service.release.set()
        thread.join(WORKER_WAIT_SECONDS)
        seconds = time.perf_counter() - started
        collector.drain()
    if thread.is_alive():
        raise VerificationError("派发前取消验收等待批次退出超时")
    events = collector.events
    final = job_service.get(job["id"])
    if final is None:
        raise VerificationError("派发前取消验收读取任务记录失败")
    runs = read_runs(job_service, job["id"])
    seconds = round(seconds, 4)
    log.record(scope, "批处理线程无异常", not failures, str(failures[:1]))
    log.record(scope, "取消返回运行态", cancel_return["status"] == "running", str(cancel_return["status"]))
    log.record(scope, "终态为取消", final["status"] == "cancelled", str(final["status"]))
    log.record(
        scope,
        "取消后无结果",
        int(final["completed"]) == 0 and not runs,
        f"完成 {final['completed']}，记录 {len(runs)}",
    )
    log.record(scope, "取消后未派发批次", engine.batches == [], str(engine.batches[:1]))
    log.record(scope, "取消后未配置并行数", engine.workers is None, str(engine.workers))
    log.record(scope, "取消信号下发一次", engine.cancel_calls == 1, str(engine.cancel_calls))
    verify_final_event(
        log,
        scope,
        events,
        name="experiment.cancelled",
        job_id=job["id"],
        status="cancelled",
        completed=0,
        total=total,
    )
    return {
        "phase": "cancel-race",
        "workers": workers,
        "scope": scope,
        "total": total,
        "completed": 0,
        "seconds": seconds,
        "matches_per_second": 0.0,
        "sessions": 0,
        "peak_child_megabytes": 0.0,
        "results": [],
        "events": events,
    }


def run_resume_case(
    base_directory: Path,
    log: CheckLog,
    *,
    workers: int,
    seeds: Sequence[int],
    variants: Sequence[str],
    total: int,
    simulator: Path,
    resources: Mapping[str, int],
    timeout_seconds: float,
) -> dict[str, Any]:
    scope = f"resume/workers={workers}"
    case_directory = base_directory / f"resume-{workers}"
    crash_limit = min(CRASH_ACCEPTED_MATCHES, total // 2)
    crash_engine = CrashAfterEngine(
        make_engine(case_directory / "crash", simulator, timeout_seconds=timeout_seconds),
        crash_limit,
    )
    service, job_service, publisher = make_service(case_directory, crash_engine)
    pairs = expected_pairs(seeds, variants)
    collector = EventCollector(publisher)
    with collector:
        job = submit_batch(service, seeds=seeds, variants=variants, workers=workers, resources=resources)
        crashed = False
        try:
            service.start_next()
        except SystemExit:
            crashed = True
        snapshot = job_service.get(job["id"])
        if snapshot is None:
            raise VerificationError("续跑验收读取崩溃后任务记录失败")
        runs_after_crash = read_runs(job_service, job["id"])
        log.record(scope, "崩溃中止启动", crashed)
        log.record(
            scope,
            "崩溃后停留运行态",
            snapshot["status"] == "running",
            str(snapshot["status"]),
        )
        log.record(
            scope,
            "崩溃后保留受理结果",
            int(snapshot["completed"]) == crash_limit and len(runs_after_crash) == crash_limit,
            f"{snapshot['completed']}/{len(runs_after_crash)}，期望 {crash_limit}",
        )
        try:
            service.resume(job["id"])
        except ValueError as error:
            log.record(scope, "运行态续跑被拒绝", str(error) == RESUME_ERROR, str(error))
        else:
            log.record(scope, "运行态续跑被拒绝", False, "运行态续跑未报错")
        interrupted = job_service.update(job["id"], {"status": "interrupted"})
        log.record(scope, "标记中断状态", interrupted["status"] == "interrupted", str(interrupted["status"]))
        resumed = service.resume(job["id"])
        log.record(scope, "恢复为排队状态", resumed["status"] == "queued", str(resumed["status"]))
        resumed_engine = RecordingEngine(
            make_engine(case_directory / "resume", simulator, timeout_seconds=timeout_seconds)
        )
        resumed_service = ExperimentService(
            job_service, resumed_engine, runtime_plan_for(resumed_engine), publisher
        )
        started = time.perf_counter()
        final = resumed_service.start_next()
        seconds = time.perf_counter() - started
        collector.drain()
    events = collector.events
    runs = read_runs(job_service, job["id"])
    completed_pairs = set(task_pairs(runs_after_crash))
    remaining = [pair for pair in pairs if pair not in completed_pairs]
    sessions = session_directory_count(case_directory / "resume" / "work")
    seconds = round(seconds, 4)
    log.record(scope, "续跑只下发缺失场次", task_pairs(resumed_engine.dispatched) == remaining)
    log.record(scope, "续跑并行数", resumed_engine.workers == workers, str(resumed_engine.workers))
    log.record(
        scope,
        "续跑批次完成",
        final is not None and final["status"] == "completed" and final["completed"] == total,
        str(final["status"] if final else None),
    )
    verify_complete_identity(log, scope, runs, pairs)
    verify_progress(log, scope, events, job_id=job["id"], run_count=total)
    verify_final_event(
        log,
        scope,
        events,
        name="experiment.completed",
        job_id=job["id"],
        status="completed",
        completed=total,
        total=total,
    )
    resumed_events = [
        event
        for event in events
        if event["event"] == "experiment.resumed" and (event.get("data") or {}).get("job_id") == job["id"]
    ]
    log.record(scope, "恢复事件一次", len(resumed_events) == 1, str(len(resumed_events)))
    log.record(
        scope,
        "续跑并行分道数",
        sessions == min(workers, total - crash_limit),
        f"会话 {sessions}，期望 {min(workers, total - crash_limit)}",
    )
    log.record(scope, "续跑耗时为正值", seconds > 0, f"{seconds}s")
    error = job_error(final)
    log.record(scope, "续跑无错误记录", error is None, error or "")
    return {
        "phase": "resume",
        "workers": workers,
        "scope": scope,
        "total": total,
        "completed": final["completed"] if final else 0,
        "seconds": seconds,
        "matches_per_second": round((total - crash_limit) / seconds, 4) if seconds > 0 else 0.0,
        "sessions": sessions,
        "peak_child_megabytes": peak_child_megabytes(),
        "results": runs_digest(runs),
        "error": error,
        "events": events,
    }


def run_verification(arguments: argparse.Namespace) -> dict[str, Any]:
    total = arguments.matches
    if total < 2 or total > MAX_MATCHES or total % 2:
        raise VerificationError(f"场数须为 2–{MAX_MATCHES} 的偶数")
    if arguments.timeout_seconds <= 0:
        raise VerificationError("单场超时秒数必须为正数")
    workers_values = tuple(arguments.workers)
    variants = MATRIX_VARIANTS
    seeds = tuple(range(1, total // 2 + 1))
    expected_total = len(seeds) * len(variants)
    simulator = resolve_simulator(arguments.simulator)
    measured = measured_resources()
    resources = applied_resources(measured, arguments)
    log = CheckLog()
    preflight = run_preflight(log, resources, workers_values, simulator)
    with tempfile.TemporaryDirectory(
        prefix="fm27lab-matrix-",
        ignore_cleanup_errors=True,
    ) as directory:
        base = Path(directory)
        matrix_records = [
            run_matrix_case(
                base,
                log,
                workers=workers,
                seeds=seeds,
                variants=variants,
                total=expected_total,
                simulator=simulator,
                resources=resources,
                timeout_seconds=arguments.timeout_seconds,
            )
            for workers in workers_values
        ]
        distributions = [distribution_from_digest(record["results"]) for record in matrix_records]
        consistent = all(item == distributions[0] for item in distributions[1:])
        differences = sum(
            1
            for item in distributions[1:]
            for pair in set(item) | set(distributions[0])
            if item.get(pair) != distributions[0].get(pair)
        )
        log.record(
            "matrix/distribution",
            "并行数不改变结果分布",
            consistent,
            f"差异项 {differences}",
        )
        cancel_records = [
            run_cancel_case(
                base,
                log,
                workers=workers,
                seeds=seeds,
                variants=variants,
                total=expected_total,
                simulator=simulator,
                resources=resources,
                timeout_seconds=arguments.timeout_seconds,
            )
            for workers in workers_values
        ]
        dispatch_race_records = [
            run_dispatch_race_case(
                base,
                log,
                workers=workers,
                seeds=seeds,
                variants=variants,
                total=expected_total,
                resources=resources,
            )
            for workers in workers_values
        ]
        resume_records = [
            run_resume_case(
                base,
                log,
                workers=workers,
                seeds=seeds,
                variants=variants,
                total=expected_total,
                simulator=simulator,
                resources=resources,
                timeout_seconds=arguments.timeout_seconds,
            )
            for workers in workers_values
        ]
    cases = matrix_records + cancel_records + dispatch_race_records + resume_records
    for case in cases:
        case["passed"] = log.passed_scope(case["scope"])
    return {
        "generated_at": now_iso(),
        "version": SOURCE_VERSION,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "simulator": str(simulator),
        },
        "params": {
            "matches": expected_total,
            "seeds": list(seeds),
            "variants": list(variants),
            "workers": list(workers_values),
            "timeout_seconds": arguments.timeout_seconds,
            "resource_overrides": {
                "available_memory_bytes": arguments.available_memory_bytes,
                "free_disk_bytes": arguments.free_disk_bytes,
            },
        },
        "resources": resources,
        "measured_resources": measured,
        "preflight": preflight,
        "cases": cases,
        "checks": log.items,
        "passed": log.passed(),
    }


def _cell_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _pad_cell(text: str, width: int, align: str) -> str:
    padding = " " * max(width - _cell_width(text), 0)
    return padding + text if align == "right" else text + padding


def _render_table(
    headers: Sequence[str], aligns: Sequence[str], rows: Sequence[Sequence[str]]
) -> list[str]:
    widths = [
        max(_cell_width(cells[column]) for cells in (headers, *rows))
        for column in range(len(headers))
    ]

    def render(cells: Sequence[str]) -> str:
        return "  ".join(
            _pad_cell(cell, widths[index], aligns[index]) for index, cell in enumerate(cells)
        )

    header_line = render(headers)
    return [header_line, "-" * _cell_width(header_line), *(render(row) for row in rows)]


def format_summary(report: Mapping[str, Any]) -> str:
    params = report["params"]
    resources = report["resources"]
    title = (
        f"并发验收矩阵 场数={params['matches']} 并行数={params['workers']}"
        f" CPU={resources['cpu_count']}"
        f" 可用内存={resources['available_memory_bytes'] / GIB:.1f}GiB"
        f" 空闲磁盘={resources['free_disk_bytes'] / GIB:.1f}GiB"
    )
    rows = []
    for case in report["cases"]:
        rows.append(
            (
                str(case["phase"]),
                str(case["workers"]),
                str(case["total"]),
                str(case["completed"]),
                f"{case['seconds']:.4f}",
                f"{case['matches_per_second']:.4f}",
                str(case["sessions"]),
                "通过" if case["passed"] else "失败",
            )
        )
    headers = ("阶段", "并行数", "场数", "完成", "耗时秒", "场每秒", "会话数", "结论")
    aligns = ("left", "right", "right", "right", "right", "right", "right", "left")
    lines = [title, ""]
    lines.extend(_render_table(headers, aligns, rows))
    total_checks = len(report["checks"])
    passed_checks = sum(1 for item in report["checks"] if item["passed"])
    lines.extend(["", f"校验 {passed_checks}/{total_checks} 通过"])
    failures = report.get("failures")
    if failures:
        lines.append("未通过校验：")
        lines.extend(
            f"- [{item['scope']}] {item['name']}：{item['detail']}" for item in failures[:30]
        )
    return "\n".join(lines)


def evidence_directory(value: str | None) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = EVIDENCE_ROOT / f"concurrency-matrix-{stamp}"
    if candidate.exists():
        candidate = EVIDENCE_ROOT / f"concurrency-matrix-{stamp}-{os.getpid()}"
    return candidate


def write_evidence(directory: Path, report: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    events_directory = directory / "events"
    events_directory.mkdir(parents=True, exist_ok=True)
    for case in report["cases"]:
        events = case.pop("events", [])
        path = events_directory / f"{case['phase']}-workers-{case['workers']}.jsonl"
        content = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
        path.write_text(content, encoding="utf-8")
        case["events_path"] = str(path)
    report_path = directory / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path = directory / "summary.txt"
    summary_path.write_text(format_summary(report) + "\n", encoding="utf-8")


def _configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


def _workers_argument(value: str) -> tuple[int, ...]:
    try:
        workers = tuple(int(part) for part in value.split(",") if part.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("并行数必须为逗号分隔的整数") from error
    if not workers:
        raise argparse.ArgumentTypeError("并行数不能为空")
    for item in workers:
        try:
            validate_workers(item)
        except ValueError as error:
            raise argparse.ArgumentTypeError(str(error)) from error
    return workers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="并发验收矩阵 1、8、256")
    parser.add_argument("--matches", type=int, default=DEFAULT_MATCHES, help="批判场数，须为偶数，默认 256")
    parser.add_argument(
        "--workers",
        type=_workers_argument,
        default=DEFAULT_WORKERS,
        help="逗号分隔的并行数，默认 1,8,256",
    )
    parser.add_argument(
        "--simulator",
        default=str(DEFAULT_SIMULATOR),
        help="原生模拟器脚本或引擎可执行文件",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="单场超时秒数",
    )
    parser.add_argument(
        "--available-memory-bytes",
        type=int,
        default=None,
        help="覆盖可用内存字节数，供容量受限的验收环境使用",
    )
    parser.add_argument(
        "--free-disk-bytes",
        type=int,
        default=None,
        help="覆盖空闲磁盘字节数，供容量受限的验收环境使用",
    )
    parser.add_argument(
        "--evidence-dir",
        default=None,
        help="证据输出目录，默认 dist/concurrency-matrix-<时间戳>",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_streams()
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        report = run_verification(arguments)
    except (VerificationError, ValueError, RuntimeError) as error:
        print(f"验收失败：{error}", file=sys.stderr)
        return 1
    report["failures"] = [item for item in report["checks"] if not item["passed"]]
    directory = evidence_directory(arguments.evidence_dir)
    write_evidence(directory, report)
    print(format_summary(report))
    print(f"\n证据目录：{directory}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
