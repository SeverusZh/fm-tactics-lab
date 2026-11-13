"""Native engine host adapter: capability probe, worker-manifest sessions and file results.

The worker manifest mirrors the protocol consumed by src/desktop_warm_batch.py
and native/desktop_host.cpp. Counted-session hosts receive FM27DW2 followed by
the job count; legacy hosts receive FM27DW1 without a count line. Every job then
contributes five lines: fixture path, scenario config path (empty line when no
scenario is passed), per-match log path, seed and dump path ("-" when no dump is
requested).

Each session starts the host with --worker-manifest, --output session.jsonl,
--tick-step 1 and --cancel-event. Match completion is detected through the
per-match <log>.worker_done sidecar; the JSONL match log then provides the final
score, native statistics and optional event details for the append_run record.
The startup session file must carry the native_engine_compatibility declaration
and is also inspected for steam_session_cleanup warnings. Session failures are
retried for unresolved matches only, and exit code 180 is accepted as an
unconfirmed Steam cleanup warning.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fm27lab.adapters.engine_native.capabilities import parse_capabilities, plan_runtime
from fm27lab.domain.concurrency import validate_workers
from fm27lab.ports.engine import EngineCapabilities, RuntimePlan

CAPABILITY_TIMEOUT_SECONDS = 10.0
POLL_SECONDS = 0.02
CLEANUP_SECONDS = 15.0
TERMINATION_SECONDS = 2.0
STDERR_LIMIT = 2000
WORKER_SESSIONS_DIRECTORY = "worker_sessions"
MANIFEST_NAME = "manifest.txt"
SESSION_LOG_NAME = "session.jsonl"
CANCEL_EVENT_NAME = "cancel.event"
WORKER_DONE_SUFFIX = ".worker_done"
STEAM_CLEANUP_WARNING = "Steam 会话清理未确认"
COMPATIBILITY_MISSING = "原生启动兼容诊断缺失"
COMPATIBILITY_FAILED = "原生关键接口检查失败：引擎兼容声明不可用"
ENV_PREFIXES = (
    "FM27_IMPORT_",
    "FM27_EXPORT_",
    "FM27_EPISODE_",
    "FM27_SAVE_SECTION_",
    "FM27_SAVED_CORE_",
    "FM27_AI_",
)
ENV_EXCLUDED = frozenset({"FM27_DESKTOP_STATS_AUDIT", "FM27_SKIP_EVENT_DETAILS"})
UNSAFE_VARIANT_CHARACTERS = ("/", "\\", ":", "*", "?", '"', "<", ">", "|")


@dataclass(frozen=True)
class _Task:
    variant: str
    seed: int
    fixture: Path
    config: Path | None
    output: Path | None
    dump: Path | None


@dataclass(frozen=True)
class _SessionOutcome:
    ok: bool
    cancelled: bool
    error: str | None
    tasks: list[_Task]
    outputs: list[Path]
    unresolved: list[int]


class _PortableCancellation:
    """Per-session cancel token implemented as a path the worker can observe."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = str(path)

    def signal(self) -> None:
        self.path.write_text("cancelled\n", encoding="utf-8")

    def close(self) -> None:
        return None


class _WindowsEventCancellation:
    """Named event expected by the real Windows native host; created lazily."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel = self._kernel
        kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.SetEvent.argtypes = [wintypes.HANDLE]
        kernel.SetEvent.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.name = f"Local\\FM27MatchCancel_{os.getpid()}_{uuid.uuid4().hex}"
        self._handle = kernel.CreateEventW(None, True, False, self.name)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def signal(self) -> None:
        if self._handle and not self._kernel.SetEvent(self._handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


_Cancellation = _PortableCancellation | _WindowsEventCancellation


class _StderrCollector:
    """Keep the tail of the worker stderr without unbounded memory growth."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._size = 0
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        with self._lock:
            self._parts.append(text)
            self._size += len(text)
            if self._size > STDERR_LIMIT * 4:
                joined = "".join(self._parts)[-STDERR_LIMIT * 2 :]
                self._parts = [joined]
                self._size = len(joined)

    def text(self) -> str:
        with self._lock:
            return "".join(self._parts)[-STDERR_LIMIT:].strip()


def _last_json_object(data: bytes) -> Mapping[str, Any] | None:
    text = data.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            return None
        return value if isinstance(value, Mapping) else None
    return None


def _read_event_rows(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _drain_stream(stream: Any) -> None:
    try:
        for _ in stream:
            pass
    except (OSError, ValueError):
        pass


def _read_stderr(stream: Any, collector: _StderrCollector) -> None:
    try:
        for raw in stream:
            collector.append(raw.decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        pass


def _signal(cancellation: _Cancellation | None) -> None:
    if cancellation is None:
        return
    try:
        cancellation.signal()
    except OSError:
        pass


class _ProgressMerger:
    """Merge the active descriptors of every lane and serialize progress emission."""

    def __init__(
        self,
        lanes: int,
        emit: Callable[[Sequence[Mapping[str, Any]]], None],
    ) -> None:
        self._lanes = lanes
        self._emit = emit
        self._lock = threading.Lock()
        self._active: dict[int, list[dict[str, Any]]] = {}
        self._last: list[dict[str, Any]] | None = None

    def active(self, lane: int, descriptors: Sequence[Mapping[str, Any]]) -> None:
        with self._lock:
            if descriptors:
                self._active[lane] = [dict(descriptor) for descriptor in descriptors]
            else:
                self._active.pop(lane, None)
            merged: list[dict[str, Any]] = []
            for index in sorted(self._active):
                for descriptor in self._active[index]:
                    merged.append({"lane": index, **descriptor} if self._lanes > 1 else descriptor)
            if merged == self._last:
                return
            self._last = merged
            self._emit(merged)


class NativeEngineHost:
    """EnginePort implementation that runs batches through the native worker protocol.

    The executable defaults to root/fm27_native/FM27Simulator.exe. A script
    executable ending in .py is started through the current interpreter so the
    tests and local diagnostics can drive the adapter without a real host.

    timeout_seconds is an inactivity watchdog per session, matching the legacy
    last-progress semantics. cleanup_seconds is the grace window used after a
    cancel request or a session failure before the host process is terminated
    and then killed. A timed out or abnormally exited session is retried with
    only its unresolved matches; matches already accepted are never re-run.
    workers splits the batch into the legacy lanes (tasks[index::effective])
    that share one ThreadPoolExecutor; every lane chunks its own matches by
    jobs_per_native_session, retries and reports failures independently, and the
    user callbacks are serialized so lanes never interleave results or progress.
    cancel() requests every running session to stop through --cancel-event and
    keeps results already accepted. Diagnostics such as an unconfirmed Steam
    cleanup are appended to the diagnostics list.
    """

    def __init__(
        self,
        root: Path,
        work_dir: Path,
        *,
        executable: Path | None = None,
        plan: RuntimePlan | None = None,
        timeout_seconds: float = 190.0,
        retries: int = 1,
        cleanup_seconds: float = CLEANUP_SECONDS,
        workers: int = 1,
    ) -> None:
        self._root = Path(root)
        self._work_dir = Path(work_dir)
        self._executable = (
            Path(executable) if executable is not None else self._root / "fm27_native" / "FM27Simulator.exe"
        )
        if type(timeout_seconds) not in (int, float) or not timeout_seconds > 0:
            raise ValueError("超时时间必须为正数")
        if type(retries) is not int or retries < 0:
            raise ValueError("重试次数必须为非负整数")
        if type(cleanup_seconds) not in (int, float) or not cleanup_seconds > 0:
            raise ValueError("清理宽限必须为正数")
        self._workers = validate_workers(workers)
        if plan is not None:
            if not isinstance(plan, RuntimePlan):
                raise ValueError("运行时计划无效")
            budget = plan.jobs_per_native_session
            if budget is not None and (type(budget) is not int or budget < 1):
                raise ValueError("运行时计划无效")
        self._timeout_seconds = float(timeout_seconds)
        self._cleanup_seconds = float(cleanup_seconds)
        self._retries = retries
        self._lock = threading.Lock()
        self._callbacks_lock = threading.Lock()
        self._cancelled = threading.Event()
        self._cancellations: dict[str, _Cancellation] = {}
        self._capabilities: EngineCapabilities | None = None
        self.diagnostics: list[dict[str, Any]] = []
        self._plan = plan
        if self._plan is None:
            self._plan = plan_runtime(
                self.capabilities(),
                has_pool_variants=False,
                has_experimental_execution=False,
            )

    def capabilities(self) -> EngineCapabilities:
        with self._lock:
            cached = self._capabilities
        if cached is not None:
            return cached
        capabilities = self._probe_capabilities()
        with self._lock:
            if self._capabilities is None:
                self._capabilities = capabilities
            return self._capabilities

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: Callable[[Mapping[str, Any]], None],
        on_progress: Callable[[Sequence[Mapping[str, Any]]], None],
    ) -> None:
        prepared = self._prepare_tasks(tasks)
        if not prepared:
            return
        self._cancelled.clear()
        budget = self._plan.jobs_per_native_session
        lanes = min(self._workers, len(prepared))

        def emit_result(result: Mapping[str, Any]) -> None:
            with self._callbacks_lock:
                on_result(result)

        def emit_progress(descriptors: Sequence[Mapping[str, Any]]) -> None:
            with self._callbacks_lock:
                on_progress(descriptors)

        progress = _ProgressMerger(lanes, emit_progress)
        lane_tasks = [prepared[index::lanes] for index in range(lanes)]
        error: BaseException | None = None
        with ThreadPoolExecutor(max_workers=lanes, thread_name_prefix="fm27-engine-lane") as executor:
            futures = [
                executor.submit(self._run_lane, index, lane_tasks[index], budget, emit_result, progress)
                for index in range(lanes)
            ]
            try:
                for future in as_completed(futures):
                    caught = future.exception()
                    if caught is not None and error is None:
                        error = caught
                        self.cancel()
            except BaseException:
                self.cancel()
                raise
        if error is not None:
            raise error

    def cancel(self) -> None:
        """Request cancellation of every running session and keep accepted results."""
        with self._lock:
            self._cancelled.set()
            cancellations = list(self._cancellations.values())
        for cancellation in cancellations:
            _signal(cancellation)

    def _run_lane(
        self,
        lane: int,
        tasks: list[_Task],
        budget: int | None,
        on_result: Callable[[Mapping[str, Any]], None],
        progress: _ProgressMerger,
    ) -> None:
        pending = list(tasks)
        while pending and not self._cancelled.is_set():
            take = len(pending) if budget is None else min(budget, len(pending))
            chunk = pending[:take]
            pending = pending[take:]
            self._run_chunk(chunk, on_result, progress, lane)

    def _probe_capabilities(self) -> EngineCapabilities:
        command = [*self._executable_prefix(), "--worker-capabilities"]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=CAPABILITY_TIMEOUT_SECONDS,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return parse_capabilities(None)
        if completed.returncode != 0:
            return parse_capabilities(None)
        payload = _last_json_object(completed.stdout)
        try:
            return parse_capabilities(payload)
        except ValueError:
            return parse_capabilities(None)

    def _executable_prefix(self) -> list[str]:
        if self._executable.suffix.lower() == ".py":
            return [sys.executable, str(self._executable)]
        return [str(self._executable)]

    def _worker_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        for name in list(environment):
            if name in ENV_EXCLUDED or name.startswith(ENV_PREFIXES):
                environment.pop(name, None)
        return environment

    def _run_chunk(
        self,
        chunk: list[_Task],
        on_result: Callable[[Mapping[str, Any]], None],
        progress: _ProgressMerger,
        lane: int,
    ) -> None:
        remaining = list(chunk)
        attempts = self._retries + 1
        for attempt in range(attempts):
            if self._cancelled.is_set():
                return
            outcome = self._run_session(remaining, attempt, on_result, progress, lane)
            if outcome.ok or outcome.cancelled:
                return
            if not outcome.unresolved:
                raise RuntimeError(outcome.error or "原生会话执行失败")
            if attempt == attempts - 1:
                error = outcome.error or "原生会话执行失败"
                for position in outcome.unresolved:
                    on_result(
                        self._failed_result(
                            outcome.tasks[position],
                            error,
                            output=outcome.outputs[position],
                            failure_phase="native_session",
                        )
                    )
                return
            remaining = [outcome.tasks[position] for position in outcome.unresolved]

    def _run_session(
        self,
        tasks: list[_Task],
        attempt: int,
        on_result: Callable[[Mapping[str, Any]], None],
        progress: _ProgressMerger,
        lane: int,
    ) -> _SessionOutcome:
        try:
            session_dir = self._session_directory()
            outputs = [
                self._session_output(task, session_dir, position, attempt)
                for position, task in enumerate(tasks, start=1)
            ]
            for output in outputs:
                output.parent.mkdir(parents=True, exist_ok=True)
            manifest = self._write_manifest(session_dir, tasks, outputs)
        except OSError as error:
            raise RuntimeError(f"无法准备原生会话目录：{error}") from error
        cancellation = self._new_cancellation(session_dir)
        startup = session_dir / SESSION_LOG_NAME
        process: subprocess.Popen | None = None
        try:
            command = [
                *self._executable_prefix(),
                "--worker-manifest",
                str(manifest),
                "--output",
                str(startup),
                "--tick-step",
                "1",
                "--cancel-event",
                cancellation.name,
            ]
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(self._root),
                    env=self._worker_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as error:
                raise RuntimeError(f"原生宿主启动失败：{error}") from error
            try:
                outcome = self._consume_session(
                    tasks, outputs, startup, process, cancellation, on_result, progress, lane
                )
            except BaseException:
                self._force_stop(process, cancellation)
                raise
        finally:
            self._release_cancellation(cancellation)
            cancellation.close()
            if process is not None:
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
        progress.active(lane, [])
        return outcome

    def _force_stop(self, process: subprocess.Popen, cancellation: _Cancellation) -> None:
        """Stop a host after an unexpected failure so pipes can be closed."""
        _signal(cancellation)
        deadline = time.monotonic() + self._cleanup_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(POLL_SECONDS)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=TERMINATION_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def _consume_session(
        self,
        tasks: list[_Task],
        outputs: list[Path],
        startup: Path,
        process: subprocess.Popen,
        cancellation: _Cancellation,
        on_result: Callable[[Mapping[str, Any]], None],
        progress: _ProgressMerger,
        lane: int,
    ) -> _SessionOutcome:
        total = len(tasks)
        collector = _StderrCollector()
        stdout_thread = threading.Thread(target=_drain_stream, args=(process.stdout,), daemon=True)
        stderr_thread = threading.Thread(target=_read_stderr, args=(process.stderr, collector), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        completed = 0
        compatibility_checked = False
        last_active: list[dict[str, Any]] | None = None
        last_progress = time.monotonic()
        fatal: BaseException | None = None
        cancelled = False
        failure: str | None = None

        def consume_available() -> BaseException | None:
            nonlocal completed, compatibility_checked
            while completed < total:
                if not Path(str(outputs[completed]) + WORKER_DONE_SUFFIX).exists():
                    return None
                if not compatibility_checked:
                    self._check_startup(startup, self._startup_rows(startup))
                    compatibility_checked = True
                position = completed
                try:
                    self._consume_worker_done(tasks[position], outputs[position], position + 1, on_result)
                except BaseException as error:
                    completed = position + 1
                    return error
                completed = position + 1
            return None

        def unresolved_positions() -> list[int]:
            return list(range(completed, total))

        while True:
            if self._cancelled.is_set():
                cancelled = True
                break
            previous = completed
            error = consume_available()
            if error is not None:
                fatal = error
                break
            if completed != previous:
                last_progress = time.monotonic()
            if completed == total:
                if process.poll() is not None:
                    break
                if time.monotonic() - last_progress > self._cleanup_seconds:
                    failure = f"原生会话超时（超过 {self._cleanup_seconds:g} 秒未完成清理），已终止"
                    break
            else:
                if process.poll() is not None:
                    if Path(str(outputs[completed]) + WORKER_DONE_SUFFIX).exists():
                        continue
                    break
                if time.monotonic() - last_progress > self._timeout_seconds:
                    failure = f"原生会话超时（超过 {self._timeout_seconds:g} 秒无进展），已终止"
                    break
            descriptor = self._active_descriptor(tasks, completed)
            if descriptor != last_active:
                last_active = descriptor
                try:
                    progress.active(lane, descriptor)
                except BaseException as error:
                    fatal = error
                    break
            time.sleep(POLL_SECONDS)

        if fatal is not None or cancelled or failure is not None:
            _signal(cancellation)
            deadline = time.monotonic() + self._cleanup_seconds
            while time.monotonic() < deadline:
                error = consume_available()
                if error is not None and fatal is None:
                    fatal = error
                if process.poll() is not None:
                    break
                time.sleep(POLL_SECONDS)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=TERMINATION_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            stdout_thread.join(timeout=TERMINATION_SECONDS)
            stderr_thread.join(timeout=TERMINATION_SECONDS)
            error = consume_available()
            if error is not None and fatal is None:
                fatal = error
            if fatal is not None:
                raise fatal
            if not cancelled:
                self._check_startup(startup, self._startup_rows(startup))
            unresolved = unresolved_positions()
            if cancelled:
                return _SessionOutcome(False, True, None, tasks, outputs, unresolved)
            return _SessionOutcome(
                False, False, self._with_stderr(failure or "", collector), tasks, outputs, unresolved
            )

        try:
            process.wait(timeout=TERMINATION_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        stdout_thread.join(timeout=TERMINATION_SECONDS)
        stderr_thread.join(timeout=TERMINATION_SECONDS)
        error = consume_available()
        if error is not None:
            raise error
        rows = self._startup_rows(startup)
        self._check_startup(startup, rows)
        unresolved = unresolved_positions()
        stderr = collector.text()
        if process.returncode not in (0, 180):
            message = f"原生宿主退出 {process.returncode}"
            if stderr:
                message = f"{message}：{stderr}"
            if not unresolved:
                raise RuntimeError(message)
            return _SessionOutcome(False, False, message, tasks, outputs, unresolved)
        if process.returncode == 180 and unresolved:
            message = f"原生宿主退出 180 且未完成全部比赛：完成 {total - len(unresolved)}/{total}"
            if stderr:
                message = f"{message}；{stderr}"
            return _SessionOutcome(False, False, message, tasks, outputs, unresolved)
        self._record_steam_cleanup(startup.parent, rows, process.returncode)
        if unresolved:
            message = f"原生宿主未完成全部比赛：完成 {total - len(unresolved)}/{total}"
            if stderr:
                message = f"{message}；{stderr}"
            return _SessionOutcome(False, False, message, tasks, outputs, unresolved)
        return _SessionOutcome(True, False, None, tasks, outputs, [])

    def _consume_worker_done(
        self,
        task: _Task,
        output: Path,
        expected_index: int,
        on_result: Callable[[Mapping[str, Any]], None],
    ) -> None:
        done = Path(str(output) + WORKER_DONE_SUFFIX)
        try:
            ack = json.loads(done.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("原生逐场释放标记无效") from error
        if (
            not isinstance(ack, Mapping)
            or ack.get("released") is not True
            or type(ack.get("exit_code")) is not int
            or ack.get("exit_code") != 0
            or type(ack.get("index")) is not int
            or ack.get("index") != expected_index
        ):
            raise RuntimeError("原生逐场释放标记无效")
        try:
            rows = _read_event_rows(output)
        except OSError:
            on_result(
                self._failed_result(
                    task, "原生比赛日志无法读取", output=output, failure_phase="native_validation"
                )
            )
            return
        except ValueError:
            on_result(
                self._failed_result(
                    task,
                    "原生比赛日志无效：无法解析 JSON 行",
                    output=output,
                    failure_phase="native_validation",
                )
            )
            return
        try:
            result = self._map_match_result(task, output, rows)
        except ValueError as error:
            on_result(self._failed_result(task, str(error), output=output, failure_phase="native_validation"))
        else:
            on_result(result)

    def _map_match_result(
        self,
        task: _Task,
        output: Path,
        rows: list[Any],
    ) -> dict[str, Any]:
        finish = self._single_row(rows, "natural_match_finished", "原生比赛终场记录无效")
        if finish.get("full_match_completed") is not True:
            raise ValueError("原生比赛未自然完赛")
        score = finish.get("score")
        if (
            not isinstance(score, list)
            or len(score) != 2
            or any(type(value) is not int or value < 0 for value in score)
        ):
            raise ValueError("原生终场比分无效")
        statistics = self._single_row(rows, "native_match_statistics", "原生球队统计记录无效")
        events_row = next(
            (row for row in rows if isinstance(row, Mapping) and row.get("event") == "native_match_events"),
            None,
        )
        events: Mapping[str, Any] | None = None
        if events_row is not None:
            payload = events_row.get("events")
            if isinstance(payload, Mapping):
                events = dict(payload)
        return {
            "variant": task.variant,
            "seed": task.seed,
            "score_home": score[0],
            "score_away": score[1],
            "verified": True,
            "stats": dict(statistics),
            "events": events,
            "log_path": str(output),
        }

    @staticmethod
    def _single_row(rows: list[Any], event: str, message: str) -> Mapping[str, Any]:
        matches = [row for row in rows if isinstance(row, Mapping) and row.get("event") == event]
        if len(matches) != 1:
            raise ValueError(message)
        return matches[0]

    def _startup_rows(self, startup: Path) -> list[Mapping[str, Any]]:
        try:
            text = startup.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        rows: list[Mapping[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, Mapping):
                rows.append(value)
        return rows

    def _check_startup(self, startup: Path, rows: list[Mapping[str, Any]]) -> None:
        if not startup.is_file():
            raise RuntimeError(COMPATIBILITY_MISSING)
        compatibility = next((row for row in rows if row.get("event") == "native_engine_compatibility"), None)
        if compatibility is None:
            raise RuntimeError(COMPATIBILITY_MISSING)
        if not (compatibility.get("compatible") or compatibility.get("trial_allowed")):
            raise RuntimeError(COMPATIBILITY_FAILED)

    def _record_steam_cleanup(
        self,
        session_dir: Path,
        rows: list[Mapping[str, Any]],
        returncode: int,
    ) -> None:
        cleanup = next((row for row in rows if row.get("event") == "steam_session_cleanup"), None)
        warning = None
        if returncode == 180:
            warning = STEAM_CLEANUP_WARNING
        elif cleanup is not None and cleanup.get("ok") is not True:
            warning = STEAM_CLEANUP_WARNING
        if cleanup is None and returncode != 180:
            return
        self._record_diagnostic(
            {
                "session": str(session_dir),
                "event": "steam_session_cleanup",
                "returncode": returncode,
                "warning": warning,
                "steam_session_cleanup": dict(cleanup) if cleanup is not None else None,
            }
        )

    def _record_diagnostic(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            self.diagnostics.append(dict(record))

    def _active_descriptor(self, tasks: list[_Task], completed: int) -> list[dict[str, Any]]:
        position = min(completed, len(tasks) - 1)
        task = tasks[position]
        return [
            {
                "index": position + 1,
                "variant": task.variant,
                "seed": task.seed,
                "worker_completed": completed,
                "worker_total": len(tasks),
            }
        ]

    def _failed_result(
        self,
        task: _Task,
        error: str,
        *,
        output: Path | None,
        failure_phase: str,
    ) -> dict[str, Any]:
        return {
            "variant": task.variant,
            "seed": task.seed,
            "failed": True,
            "error": error,
            "failure_phase": failure_phase,
            "log_path": None if output is None else str(output),
        }

    def _with_stderr(self, message: str, collector: _StderrCollector) -> str:
        stderr = collector.text()
        return f"{message}；{stderr}" if stderr else message

    def _prepare_tasks(self, tasks: Sequence[Mapping[str, Any]]) -> list[_Task]:
        if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)):
            raise ValueError("任务列表无效")
        prepared: list[_Task] = []
        outputs: set[Path] = set()
        for task in tasks:
            if not isinstance(task, Mapping):
                raise ValueError("任务必须是对象")
            variant = task.get("variant")
            if (
                not isinstance(variant, str)
                or not variant
                or len(variant) > 64
                or any(ord(character) < 32 or ord(character) == 127 for character in variant)
                or any(character in UNSAFE_VARIANT_CHARACTERS for character in variant)
            ):
                raise ValueError("任务变体无效")
            seed = task.get("seed")
            if type(seed) is not int or not 0 <= seed <= 0xFFFFFFFF:
                raise ValueError("任务种子无效")
            fixture = self._task_path(task, "fixture")
            if fixture is None:
                fixture = self._root / "fm27_native" / "fixtures" / "match.pkm"
            config = self._task_path(task, "config")
            output = self._task_path(task, "output")
            if output is None:
                output = self._task_path(task, "path")
            dump = self._task_path(task, "dump")
            if output is not None:
                resolved_output = output.resolve()
                if resolved_output in outputs:
                    raise ValueError("任务输出路径不能重复")
                outputs.add(resolved_output)
                output = resolved_output
            prepared.append(
                _Task(
                    variant=variant,
                    seed=seed,
                    fixture=fixture.resolve(),
                    config=None if config is None else config.resolve(),
                    output=output,
                    dump=None if dump is None else dump.resolve(),
                )
            )
        return prepared

    def _task_path(self, task: Mapping[str, Any], key: str) -> Path | None:
        value = task.get(key)
        if value is None:
            return None
        if not isinstance(value, (str, Path)):
            raise ValueError("任务路径无效")
        text = str(value)
        if not text:
            return None
        if "\n" in text or "\r" in text:
            raise ValueError("任务路径包含换行符")
        path = Path(text)
        return path if path.is_absolute() else self._root / path

    def _session_directory(self) -> Path:
        directory = self._work_dir / WORKER_SESSIONS_DIRECTORY / uuid.uuid4().hex
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def _session_output(self, task: _Task, session_dir: Path, position: int, attempt: int) -> Path:
        if task.output is not None:
            output = task.output
        else:
            output = session_dir / f"{position:04d}_{task.variant}_seed_{task.seed}.jsonl"
        if attempt:
            output = output.with_name(f"{output.stem}.retry{attempt}{output.suffix}")
        return output

    def _write_manifest(self, session_dir: Path, tasks: list[_Task], outputs: list[Path]) -> Path:
        lines = ["FM27DW2", str(len(tasks))] if self.capabilities().counted_sessions else ["FM27DW1"]
        for task, output in zip(tasks, outputs, strict=True):
            values = [
                str(task.fixture),
                "" if task.config is None else str(task.config),
                str(output),
                str(task.seed),
                "-" if task.dump is None else str(task.dump),
            ]
            if any("\n" in value or "\r" in value for value in values):
                raise ValueError("任务路径包含换行符")
            lines.extend(values)
        manifest = session_dir / MANIFEST_NAME
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return manifest

    def _new_cancellation(self, session_dir: Path) -> _Cancellation:
        if os.name == "nt" and self._executable.suffix.lower() == ".exe":
            try:
                cancellation: _Cancellation = _WindowsEventCancellation()
            except OSError as error:
                raise RuntimeError(f"无法创建原生取消事件：{error}") from error
        else:
            cancellation = _PortableCancellation(session_dir / CANCEL_EVENT_NAME)
        with self._lock:
            self._cancellations[str(cancellation.name)] = cancellation
        return cancellation

    def _release_cancellation(self, cancellation: _Cancellation) -> None:
        with self._lock:
            self._cancellations.pop(str(cancellation.name), None)
