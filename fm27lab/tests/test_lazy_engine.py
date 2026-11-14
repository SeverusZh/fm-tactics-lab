"""Lazy native engine construction tests."""

from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from fm27lab.adapters.engine_native.host import NativeEngineHost
from fm27lab.adapters.engine_native.lazy import LazyNativeEngine
from fm27lab.domain.concurrency import WORKERS_ERROR
from fm27lab.ports.engine import EngineCapabilities, EnginePort

CAPABILITIES = EngineCapabilities(
    counted_sessions=True,
    jobs_per_session=None,
    session_scope="remaining_batch_lane",
    capability_version=2,
)


class FakeHost:
    def __init__(self, root: Path, work_dir: Path, *, workers: int = 1) -> None:
        self.root = root
        self.work_dir = work_dir
        self.workers = workers
        self.configured: list[int] = []
        self.capabilities_calls = 0
        self.batches: list[list[dict[str, Any]]] = []
        self.cancel_calls = 0

    def capabilities(self) -> EngineCapabilities:
        self.capabilities_calls += 1
        return CAPABILITIES

    def run_batch(self, tasks, on_result, on_progress) -> None:
        recorded = [dict(task) for task in tasks]
        self.batches.append(recorded)
        for index, task in enumerate(recorded):
            on_progress([{"worker": index}])
            on_result({**task, "score_home": 1, "score_away": 0, "verified": True})

    def cancel(self) -> None:
        self.cancel_calls += 1

    def configure_workers(self, workers: int) -> None:
        self.configured.append(workers)
        self.workers = workers


class RecordingFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.hosts: list[FakeHost] = []
        self.entered = threading.Event()
        self.gate: threading.Event | None = None
        self._lock = threading.Lock()

    def __call__(self, *args: Any, **kwargs: Any) -> FakeHost:
        self.entered.set()
        if self.gate is not None and not self.gate.wait(5):
            raise RuntimeError("factory gate timed out")
        host = FakeHost(*args, **kwargs)
        with self._lock:
            self.calls.append((args, dict(kwargs)))
            self.hosts.append(host)
        return host


def make_engine(tmp_path: Path, factory: RecordingFactory) -> LazyNativeEngine:
    return LazyNativeEngine(tmp_path / "engine", tmp_path / "work", factory=factory)


def test_lazy_engine_satisfies_engine_port(tmp_path: Path):
    engine = make_engine(tmp_path, RecordingFactory())
    assert isinstance(engine, EnginePort)


def test_construction_defers_host_creation(tmp_path: Path):
    factory = RecordingFactory()
    engine = make_engine(tmp_path, factory)
    assert factory.calls == []
    assert engine._host is None


def test_default_factory_is_the_native_engine_host():
    default = inspect.signature(LazyNativeEngine.__init__).parameters["factory"].default
    assert default is NativeEngineHost


def test_first_capabilities_constructs_host_once(tmp_path: Path):
    factory = RecordingFactory()
    engine = make_engine(tmp_path, factory)
    assert engine.capabilities() == CAPABILITIES
    assert engine.capabilities() == CAPABILITIES
    assert len(factory.calls) == 1
    args, kwargs = factory.calls[0]
    assert args[0] is engine._root
    assert args[1] is engine._work_dir
    assert kwargs == {"workers": 1}
    assert factory.hosts[0].capabilities_calls == 2


def test_first_run_batch_constructs_host_once(tmp_path: Path):
    factory = RecordingFactory()
    engine = make_engine(tmp_path, factory)
    first: list[dict[str, Any]] = []
    engine.run_batch([{"variant": "A", "seed": 1}], first.append, lambda active: None)
    second: list[dict[str, Any]] = []
    engine.run_batch([{"variant": "B", "seed": 2}], second.append, lambda active: None)
    assert len(factory.calls) == 1
    assert factory.hosts[0].batches == [
        [{"variant": "A", "seed": 1}],
        [{"variant": "B", "seed": 2}],
    ]
    assert [result["seed"] for result in first + second] == [1, 2]


def test_concurrent_first_use_constructs_one_host(tmp_path: Path):
    factory = RecordingFactory()
    factory.gate = threading.Event()
    engine = make_engine(tmp_path, factory)
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def call_capabilities() -> None:
        try:
            engine.capabilities()
        except BaseException as error:
            errors.append(error)

    def call_run_batch() -> None:
        try:
            engine.run_batch([{"variant": "A", "seed": 1}], results.append, lambda active: None)
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=call_capabilities)
    first.start()
    assert factory.entered.wait(5)
    second = threading.Thread(target=call_run_batch)
    second.start()
    time.sleep(0.1)
    factory.gate.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(factory.calls) == 1
    assert len(results) == 1


def test_cancel_before_construction_does_not_construct(tmp_path: Path):
    factory = RecordingFactory()
    engine = make_engine(tmp_path, factory)
    engine.cancel()
    assert factory.calls == []
    assert engine._host is None


def test_cancel_after_construction_is_forwarded(tmp_path: Path):
    factory = RecordingFactory()
    engine = make_engine(tmp_path, factory)
    engine.capabilities()
    engine.cancel()
    engine.cancel()
    assert len(factory.calls) == 1
    assert factory.hosts[0].cancel_calls == 2


def test_configure_workers_before_construction_reaches_the_factory(tmp_path: Path):
    factory = RecordingFactory()
    engine = make_engine(tmp_path, factory)
    engine.configure_workers(3)
    engine.configure_workers(2)
    assert factory.calls == []
    engine.capabilities()
    assert len(factory.calls) == 1
    assert factory.calls[0][1] == {"workers": 2}
    assert factory.hosts[0].workers == 2


def test_configure_workers_after_construction_is_forwarded(tmp_path: Path):
    factory = RecordingFactory()
    engine = make_engine(tmp_path, factory)
    engine.capabilities()
    engine.configure_workers(4)
    engine.configure_workers(2)
    assert len(factory.calls) == 1
    assert factory.hosts[0].configured == [4, 2]


@pytest.mark.parametrize("workers", [0, 257, -1, True, False, 2.0, "2", None])
def test_configure_workers_rejects_invalid_counts(tmp_path: Path, workers):
    factory = RecordingFactory()
    engine = make_engine(tmp_path, factory)
    with pytest.raises(ValueError, match=WORKERS_ERROR):
        engine.configure_workers(workers)
    assert factory.calls == []
    engine.capabilities()
    assert factory.calls[0][1] == {"workers": 1}


def test_factory_receives_root_and_work_dir_unchanged(tmp_path: Path):
    factory = RecordingFactory()
    root = tmp_path / "engine-root"
    work_dir = tmp_path / "engine-work"
    engine = LazyNativeEngine(root, work_dir, factory=factory)
    engine.capabilities()
    args, _ = factory.calls[0]
    assert args[0] is root
    assert args[1] is work_dir


class FlakyFactory:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.hosts: list[FakeHost] = []

    def __call__(self, *args: Any, **kwargs: Any) -> FakeHost:
        self.calls.append((args, dict(kwargs)))
        if len(self.calls) <= self.failures:
            raise RuntimeError("factory failed")
        host = FakeHost(*args, **kwargs)
        self.hosts.append(host)
        return host


def test_factory_failure_is_not_cached_and_next_use_retries(tmp_path: Path):
    factory = FlakyFactory(failures=2)
    engine = LazyNativeEngine(tmp_path / "engine", tmp_path / "work", factory=factory)

    with pytest.raises(RuntimeError, match="factory failed"):
        engine.capabilities()
    assert engine._host is None

    with pytest.raises(RuntimeError, match="factory failed"):
        engine.capabilities()
    assert engine._host is None

    assert engine.capabilities() == CAPABILITIES
    assert engine._host is not None
    assert len(factory.calls) == 3
    assert factory.calls[-1][1] == {"workers": 1}
    assert factory.hosts[0].capabilities_calls == 1
