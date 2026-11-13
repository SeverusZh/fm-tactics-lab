"""Native engine host adapter tests driven by the fake simulator fixture."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fm27lab.adapters.engine_native import NativeEngineHost as ExportedNativeEngineHost
from fm27lab.adapters.engine_native.host import NativeEngineHost
from fm27lab.ports.engine import EngineCapabilities, EnginePort, RuntimePlan

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FAKE_SIMULATOR = Path(__file__).resolve().parent / "fixtures" / "fake_simulator.py"
LEGACY_CAPABILITIES = EngineCapabilities(
    counted_sessions=False,
    jobs_per_session=64,
    session_scope=None,
    capability_version=None,
)
COUNTED_PAYLOAD = {
    "counted_sessions": True,
    "session_scope": "remaining_batch_lane",
    "capability_version": 2,
}
COUNTED_CAPABILITIES = EngineCapabilities(
    counted_sessions=True,
    jobs_per_session=None,
    session_scope="remaining_batch_lane",
    capability_version=2,
)
TWO_JOB_PLAN = RuntimePlan(
    runtime_mode="isolated_worker",
    jobs_per_native_session=2,
    session_scope=None,
    fallback_reason="counted_sessions_unavailable",
    provenance={"counted_sessions": False},
)
SUCCESS_FIELDS = {
    "variant",
    "seed",
    "score_home",
    "score_away",
    "verified",
    "stats",
    "events",
    "log_path",
}
FAILED_FIELDS = {"variant", "seed", "failed", "error", "failure_phase", "log_path"}
STDERR_MARKER = "fake simulator stderr diagnostic"
WORKER_ERROR = "并行数必须为 1–256 的整数"


def make_host(
    tmp_path: Path,
    *,
    name: str = "host",
    plan: RuntimePlan | None = None,
    executable: Path | None = None,
    retries: int = 0,
    timeout_seconds: float = 190.0,
    cleanup_seconds: float = 15.0,
    workers: int = 1,
) -> NativeEngineHost:
    root = tmp_path / name / "engine"
    work = tmp_path / name / "work"
    root.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    return NativeEngineHost(
        root,
        work,
        executable=FAKE_SIMULATOR if executable is None else executable,
        plan=plan,
        timeout_seconds=timeout_seconds,
        cleanup_seconds=cleanup_seconds,
        retries=retries,
        workers=workers,
    )


def fixture_file(tmp_path: Path, name: str) -> Path:
    directory = tmp_path / "fixtures"
    directory.mkdir(exist_ok=True)
    path = directory / name
    if not path.exists():
        path.write_bytes(b"fake match fixture")
    return path


def config_file(tmp_path: Path) -> Path:
    return fixture_file(tmp_path, "scenario.cfg")


def make_task(
    tmp_path: Path,
    *,
    variant: str = "A",
    seed: int = 1,
    fixture: str = "match.pkm",
    config: bool = True,
) -> dict[str, object]:
    task: dict[str, object] = {
        "variant": variant,
        "seed": seed,
        "fixture": str(fixture_file(tmp_path, fixture)),
    }
    if config:
        task["config"] = str(config_file(tmp_path))
    return task


def run_batch(
    host: NativeEngineHost, tasks: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[list[dict[str, object]]]]:
    results: list[dict[str, object]] = []
    progress: list[list[dict[str, object]]] = []
    host.run_batch(tasks, results.append, progress.append)
    return results, progress


def normalized_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    """Results without volatile session paths, ordered by variant and seed."""
    return sorted(
        ({key: value for key, value in result.items() if key != "log_path"} for result in results),
        key=lambda item: (item["variant"], item["seed"]),
    )


def fake_simulator_processes() -> list[int]:
    """Fake simulator child processes of this test process through the proc filesystem."""
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        pytest.skip("当前平台无法枚举残留进程")
    marker = str(FAKE_SIMULATOR).encode("utf-8")
    parent = str(os.getpid())
    found: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
            status = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if marker not in command:
            continue
        owner = next(
            (line.split(":", 1)[1].strip() for line in status.splitlines() if line.startswith("PPid:")),
            "",
        )
        if owner == parent:
            found.append(int(entry.name))
    return found


def manifest_paths(tmp_path: Path, name: str = "host") -> list[Path]:
    directory = tmp_path / name / "work" / "worker_sessions"
    if not directory.exists():
        return []
    return sorted(directory.glob("*/manifest.txt"))


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def session_startup(manifest: Path) -> Path:
    return manifest.parent / "session.jsonl"


def test_package_exports_native_engine_host():
    assert ExportedNativeEngineHost is NativeEngineHost


def test_import_succeeds_without_windows_runtime():
    program = "\n".join(
        [
            "import sys",
            "import fm27lab.adapters.engine_native as package",
            "import fm27lab.adapters.engine_native.host",
            "assert package.NativeEngineHost is fm27lab.adapters.engine_native.host.NativeEngineHost",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 解释器会预加载 ctypes")
def test_import_does_not_load_windows_only_apis():
    program = "\n".join(
        [
            "import sys",
            "import fm27lab.adapters.engine_native as package",
            "import fm27lab.adapters.engine_native.host",
            "assert package.NativeEngineHost is fm27lab.adapters.engine_native.host.NativeEngineHost",
            "assert 'ctypes' not in sys.modules",
            "assert 'msvcrt' not in sys.modules",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_capabilities_reads_last_stdout_line_and_caches(tmp_path, monkeypatch):
    probe_log = tmp_path / "probe.log"
    monkeypatch.setenv("FAKE_SIMULATOR_PROBE_LOG", str(probe_log))
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES_SCHEMA", "legacy")
    host = make_host(tmp_path)
    assert host.capabilities() == LEGACY_CAPABILITIES
    assert host.capabilities() == LEGACY_CAPABILITIES
    assert probe_log.read_text(encoding="utf-8").splitlines() == ["probe"]


def test_capabilities_parse_counted_declaration(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES", json.dumps(COUNTED_PAYLOAD))
    host = make_host(tmp_path)
    assert host.capabilities() == COUNTED_CAPABILITIES
    results, _ = run_batch(host, [make_task(tmp_path, seed=index) for index in range(65)])
    assert len(results) == 65
    paths = manifest_paths(tmp_path)
    assert len(paths) == 1
    assert read_lines(paths[0])[:2] == ["FM27DW2", "65"]


def test_capabilities_fall_back_when_probe_process_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES_EXIT", "3")
    host = make_host(tmp_path)
    assert host.capabilities() == LEGACY_CAPABILITIES


def test_capabilities_fall_back_on_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES", "not json")
    host = make_host(tmp_path)
    assert host.capabilities() == LEGACY_CAPABILITIES


def test_capabilities_fall_back_on_invalid_declaration(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES", json.dumps({"counted_sessions": "yes"}))
    host = make_host(tmp_path)
    assert host.capabilities() == LEGACY_CAPABILITIES


def test_capabilities_fall_back_when_executable_is_missing(tmp_path):
    host = make_host(tmp_path, executable=tmp_path / "missing" / "FM27Simulator.exe")
    assert host.capabilities() == LEGACY_CAPABILITIES
    with pytest.raises(RuntimeError, match="原生宿主启动失败"):
        run_batch(host, [make_task(tmp_path)])


def test_default_plan_keeps_legacy_session_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES_SCHEMA", "legacy")
    host = make_host(tmp_path)
    results, _ = run_batch(host, [make_task(tmp_path, seed=index) for index in range(65)])
    assert len(results) == 65
    paths = manifest_paths(tmp_path)
    assert len(paths) == 2
    assert all(read_lines(path)[0] == "FM27DW1" for path in paths)


def test_legacy_manifest_has_no_count_line_and_five_fields_per_match(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES_SCHEMA", "legacy")
    host = make_host(tmp_path)
    first = make_task(tmp_path, variant="A", seed=7, fixture="match.pkm")
    second = make_task(tmp_path, variant="B", seed=9, fixture="other.pkm")
    results, _ = run_batch(host, [first, second])
    paths = manifest_paths(tmp_path)
    assert len(paths) == 1
    manifest = paths[0]
    lines = read_lines(manifest)
    session_dir = manifest.parent
    assert lines[0] == "FM27DW1"
    assert len(lines) == 11
    assert lines[1] == str(Path(str(first["fixture"])).resolve())
    assert lines[2] == str(Path(str(first["config"])).resolve())
    assert Path(lines[3]).parent == session_dir
    assert lines[4] == "7"
    assert lines[5] == "-"
    assert lines[6] == str(Path(str(second["fixture"])).resolve())
    assert Path(lines[8]).parent == session_dir
    assert lines[9] == "9"
    assert lines[10] == "-"
    startup_rows = [json.loads(line) for line in read_lines(session_startup(manifest))]
    compatibility = [row for row in startup_rows if row.get("event") == "native_engine_compatibility"]
    assert compatibility == [
        {"event": "native_engine_compatibility", "compatible": True, "trial_allowed": False}
    ]
    assert results[0]["log_path"] == lines[3]
    assert results[1]["log_path"] == lines[8]


def test_manifest_allows_absent_scenario_config(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES_SCHEMA", "legacy")
    host = make_host(tmp_path)
    task = make_task(tmp_path, seed=2, config=False)
    results, _ = run_batch(host, [task])
    lines = read_lines(manifest_paths(tmp_path)[0])
    assert lines[2] == ""
    assert results[0]["log_path"] == lines[3]


def test_counted_manifest_declares_count(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES", json.dumps(COUNTED_PAYLOAD))
    host = make_host(tmp_path)
    tasks = [make_task(tmp_path, variant="A", seed=1), make_task(tmp_path, variant="B", seed=1)]
    results, _ = run_batch(host, tasks)
    lines = read_lines(manifest_paths(tmp_path)[0])
    assert lines[:2] == ["FM27DW2", "2"]
    assert len(lines) == 12
    assert [result["variant"] for result in results] == ["A", "B"]


def test_plan_chunks_batch_into_isolated_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES_SCHEMA", "legacy")
    host = make_host(tmp_path, plan=TWO_JOB_PLAN)
    results, _ = run_batch(host, [make_task(tmp_path, seed=index) for index in range(5)])
    assert [result["seed"] for result in results] == [0, 1, 2, 3, 4]
    paths = manifest_paths(tmp_path)
    assert len(paths) == 3
    assert sorted(len(read_lines(path)) for path in paths) == [6, 11, 11]
    assert len({path.parent for path in paths}) == 3
    assert all(session_startup(path).is_file() for path in paths)


def test_worker_command_uses_legacy_flags(tmp_path, monkeypatch):
    argv_log = tmp_path / "argv.log"
    monkeypatch.setenv("FAKE_SIMULATOR_ARGV_LOG", str(argv_log))
    host = make_host(tmp_path)
    results, _ = run_batch(host, [make_task(tmp_path, seed=8)])
    entries = [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines()]
    probes = [entry for entry in entries if "--worker-capabilities" in entry]
    workers = [entry for entry in entries if "--worker-manifest" in entry]
    assert len(probes) == 1
    assert len(workers) == 1
    args = workers[0]
    manifest = Path(args[args.index("--worker-manifest") + 1])
    startup = Path(args[args.index("--output") + 1])
    cancel = Path(args[args.index("--cancel-event") + 1])
    assert args[args.index("--tick-step") + 1] == "1"
    assert startup.name == "session.jsonl"
    assert startup.parent == manifest.parent
    assert cancel.parent == manifest.parent
    assert startup.is_file()
    assert results[0]["log_path"] != str(startup)


def test_match_result_maps_native_log_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_CAPABILITIES_SCHEMA", "legacy")
    host = make_host(tmp_path)
    results, _ = run_batch(host, [make_task(tmp_path, variant="A", seed=7)])
    manifest = manifest_paths(tmp_path)[0]
    output = Path(read_lines(manifest)[3])
    assert len(results) == 1
    assert results[0] == {
        "variant": "A",
        "seed": 7,
        "score_home": 3,
        "score_away": 1,
        "verified": True,
        "stats": {
            "event": "native_match_statistics",
            "teams": [
                {"shots": 8, "completed_passes": 10},
                {"shots": 6, "completed_passes": 9},
            ],
        },
        "events": {"goals": [], "cards": []},
        "log_path": str(output),
    }
    assert set(results[0]) == SUCCESS_FIELDS


def test_match_callback_order_follows_manifest(tmp_path):
    host = make_host(tmp_path)
    results, _ = run_batch(host, [make_task(tmp_path, variant="A", seed=index) for index in range(3)])
    assert [result["seed"] for result in results] == [0, 1, 2]
    assert [result["verified"] for result in results] == [True, True, True]


def test_progress_reports_active_worker_descriptors(tmp_path):
    host = make_host(tmp_path)
    _, progress = run_batch(host, [make_task(tmp_path, seed=4)])
    active = [item for descriptors in progress for item in descriptors]
    assert {
        "index": 1,
        "variant": "A",
        "seed": 4,
        "worker_completed": 0,
        "worker_total": 1,
    } in active
    assert progress[-1] == []


def test_failed_match_output_is_isolated(tmp_path):
    host = make_host(tmp_path)
    tasks = [
        make_task(tmp_path, variant="A", seed=1, fixture="match.pkm"),
        make_task(tmp_path, variant="B", seed=2, fixture="fail.pkm"),
    ]
    results, _ = run_batch(host, tasks)
    assert len(results) == 2
    assert results[0]["seed"] == 1
    assert "failed" not in results[0]
    assert results[1]["variant"] == "B"
    assert results[1]["seed"] == 2
    assert results[1]["failed"] is True
    assert results[1]["error"] == "原生比赛终场记录无效"
    assert results[1]["failure_phase"] == "native_validation"
    assert results[1]["log_path"] is not None
    assert set(results[1]) == FAILED_FIELDS


def test_malformed_match_log_is_reported_as_failed_record(tmp_path):
    host = make_host(tmp_path)
    results, _ = run_batch(host, [make_task(tmp_path, seed=3, fixture="bad_output.pkm")])
    assert len(results) == 1
    assert results[0]["failed"] is True
    assert "原生比赛日志无效" in str(results[0]["error"])


def test_malformed_worker_done_ack_is_rejected(tmp_path):
    host = make_host(tmp_path)
    with pytest.raises(RuntimeError, match="原生逐场释放标记无效"):
        run_batch(host, [make_task(tmp_path, seed=3, fixture="bad_ack.pkm")])


def test_startup_compatibility_rejects_unsupported_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_COMPAT_MODE", "unsupported")
    host = make_host(tmp_path)
    with pytest.raises(RuntimeError, match="原生关键接口检查失败"):
        run_batch(host, [make_task(tmp_path)])


def test_startup_compatibility_accepts_trial_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_COMPAT_MODE", "trial")
    host = make_host(tmp_path)
    results, _ = run_batch(host, [make_task(tmp_path)])
    assert len(results) == 1
    assert results[0]["verified"] is True


def test_startup_compatibility_missing_diagnostics_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_COMPAT_MODE", "absent")
    host = make_host(tmp_path)
    with pytest.raises(RuntimeError, match="原生启动兼容诊断缺失"):
        run_batch(host, [make_task(tmp_path)])


def test_nonzero_exit_reports_failed_run_with_stderr(tmp_path):
    host = make_host(tmp_path, retries=0)
    results, _ = run_batch(host, [make_task(tmp_path, seed=3, fixture="exit1.pkm")])
    assert len(results) == 1
    assert results[0]["variant"] == "A"
    assert results[0]["seed"] == 3
    assert results[0]["failed"] is True
    assert "原生宿主退出 1" in str(results[0]["error"])
    assert STDERR_MARKER in str(results[0]["error"])


def test_all_completed_nonzero_exit_raises_engine_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_WORKER_EXIT", "1")
    host = make_host(tmp_path)
    with pytest.raises(RuntimeError, match="原生宿主退出 1"):
        run_batch(host, [make_task(tmp_path, seed=3)])


def test_timeout_reports_failed_run_with_stderr(tmp_path):
    host = make_host(tmp_path, timeout_seconds=0.3, retries=0)
    started = time.monotonic()
    results, _ = run_batch(host, [make_task(tmp_path, seed=5, fixture="slow.pkm")])
    elapsed = time.monotonic() - started
    assert elapsed < 5
    assert len(results) == 1
    assert results[0]["failed"] is True
    assert "超时" in str(results[0]["error"])
    assert STDERR_MARKER in str(results[0]["error"])


def test_retry_reruns_unfinished_session(tmp_path):
    host = make_host(tmp_path, retries=1)
    results, _ = run_batch(host, [make_task(tmp_path, seed=6, fixture="retry_once.pkm")])
    assert len(results) == 1
    assert results[0].get("failed") is not True
    assert results[0]["seed"] == 6
    assert str(results[0]["log_path"]).endswith(".retry1.jsonl")
    assert len(manifest_paths(tmp_path)) == 2


def test_cancel_keeps_results_produced_before_cancellation(tmp_path):
    host = make_host(tmp_path, timeout_seconds=60.0)
    tasks = [
        make_task(tmp_path, variant="A", seed=1),
        make_task(tmp_path, variant="B", seed=2, fixture="slow.pkm"),
    ]
    results: list[dict[str, object]] = []
    progress: list[list[dict[str, object]]] = []

    def on_progress(active):
        progress.append(list(active))
        if any(item.get("seed") == 2 for item in active):
            host.cancel()

    started = time.monotonic()
    host.run_batch(tasks, results.append, on_progress)
    elapsed = time.monotonic() - started
    assert elapsed < 5
    assert [result["seed"] for result in results] == [1]
    assert progress[-1] == []


def test_cancel_before_first_result_returns_without_failed_runs(tmp_path):
    host = make_host(tmp_path, timeout_seconds=60.0)
    results: list[dict[str, object]] = []
    progress: list[list[dict[str, object]]] = []

    def on_progress(active):
        progress.append(list(active))
        if active:
            host.cancel()

    host.run_batch([make_task(tmp_path, seed=1, fixture="slow.pkm")], results.append, on_progress)
    assert results == []
    assert progress[-1] == []


def test_empty_batch_is_a_noop(tmp_path):
    host = make_host(tmp_path)
    results, progress = run_batch(host, [])
    assert results == []
    assert progress == []
    assert manifest_paths(tmp_path) == []


@pytest.mark.parametrize(
    "bad_task",
    [
        {"seed": 1},
        {"variant": "A"},
        {"variant": "", "seed": 1},
        {"variant": "A", "seed": -1},
        {"variant": "A", "seed": True},
        {"variant": "A", "seed": 1, "fixture": 3},
    ],
)
def test_invalid_tasks_are_rejected(tmp_path, bad_task):
    host = make_host(tmp_path)
    with pytest.raises(ValueError, match="任务"):
        host.run_batch([bad_task], lambda result: None, lambda active: None)


def test_paths_with_newlines_are_rejected(tmp_path):
    host = make_host(tmp_path)
    task = make_task(tmp_path)
    task["fixture"] = str(tmp_path / "bad\nfixture.pkm")
    with pytest.raises(ValueError, match="换行"):
        host.run_batch([task], lambda result: None, lambda active: None)


def test_constructor_validates_configuration(tmp_path):
    root = tmp_path / "root"
    work = tmp_path / "work"
    root.mkdir()
    work.mkdir()
    with pytest.raises(ValueError, match="超时"):
        NativeEngineHost(root, work, executable=FAKE_SIMULATOR, timeout_seconds=0)
    with pytest.raises(ValueError, match="重试"):
        NativeEngineHost(root, work, executable=FAKE_SIMULATOR, retries=-1)
    with pytest.raises(ValueError, match="运行时计划"):
        NativeEngineHost(root, work, executable=FAKE_SIMULATOR, plan="plan")
    with pytest.raises(ValueError, match="运行时计划"):
        NativeEngineHost(
            root,
            work,
            executable=FAKE_SIMULATOR,
            plan=RuntimePlan(
                runtime_mode="isolated_worker",
                jobs_per_native_session=0,
                session_scope=None,
                fallback_reason=None,
                provenance={},
            ),
        )


def test_native_engine_host_satisfies_engine_port(tmp_path):
    host = make_host(tmp_path)
    assert isinstance(host, EnginePort)


def _session_rows(tmp_path):
    manifest = manifest_paths(tmp_path)[0]
    return [json.loads(line) for line in read_lines(session_startup(manifest))]


def test_all_completed_exit_180_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_WORKER_EXIT", "180")
    monkeypatch.setenv("FAKE_SIMULATOR_STEAM_CLEANUP", "missing")
    host = make_host(tmp_path)
    results, _ = run_batch(host, [make_task(tmp_path, seed=5)])
    assert len(results) == 1
    assert results[0]["verified"] is True
    assert "failed" not in results[0]
    diagnostics = [item for item in host.diagnostics if item.get("event") == "steam_session_cleanup"]
    assert diagnostics and diagnostics[0]["warning"]


def test_unresolved_matches_with_exit_180_are_reported_as_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_EXIT_AFTER", "1")
    host = make_host(tmp_path)
    tasks = [
        make_task(tmp_path, variant="A", seed=1),
        make_task(tmp_path, variant="B", seed=2),
    ]
    results, _ = run_batch(host, tasks)
    assert len(results) == 2
    assert results[0]["seed"] == 1
    assert "failed" not in results[0]
    assert results[1]["seed"] == 2
    assert results[1]["failed"] is True
    assert "180" in str(results[1]["error"])


def test_retry_exhaustion_does_not_repeat_accepted_matches(tmp_path):
    host = make_host(tmp_path, retries=1)
    tasks = [
        make_task(tmp_path, variant="A", seed=1),
        make_task(tmp_path, variant="B", seed=2, fixture="exit1.pkm"),
    ]
    results, _ = run_batch(host, tasks)
    pairs = [(result["variant"], result["seed"]) for result in results]
    assert pairs.count(("A", 1)) == 1
    assert pairs.count(("B", 2)) == 1
    assert len(results) == 2
    accepted = next(result for result in results if result.get("seed") == 1)
    assert "failed" not in accepted


def test_callback_exception_cancels_running_host(tmp_path):
    host = make_host(tmp_path)

    def fail_callback(_results):
        raise RuntimeError("进度回调失败")

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="进度回调失败"):
        host.run_batch([make_task(tmp_path, seed=4, fixture="slow.pkm")], lambda _: None, fail_callback)
    assert time.monotonic() - started < 1.5


def test_worker_environment_drops_inherited_fm27_variables(tmp_path, monkeypatch):
    env_log = tmp_path / "env.log"
    monkeypatch.setenv("FAKE_SIMULATOR_ENV_LOG", str(env_log))
    monkeypatch.setenv("FM27_IMPORT_SECRET", "1")
    monkeypatch.setenv("FM27_DESKTOP_STATS_AUDIT", "1")
    monkeypatch.setenv("FM27_SKIP_EVENT_DETAILS", "1")
    host = make_host(tmp_path)
    run_batch(host, [make_task(tmp_path, seed=6)])
    names = set(json.loads(env_log.read_text(encoding="utf-8")))
    assert "FM27_IMPORT_SECRET" not in names
    assert "FM27_DESKTOP_STATS_AUDIT" not in names
    assert "FM27_SKIP_EVENT_DETAILS" not in names
    assert "PATH" in names


@pytest.mark.parametrize("variant", ["A/B", "..\\evil", "a:b", "a|b"])
def test_unsafe_variant_is_rejected_before_start(tmp_path, variant):
    host = make_host(tmp_path)
    with pytest.raises(ValueError, match="任务变体无效"):
        run_batch(host, [make_task(tmp_path, variant=variant, seed=1)])
    assert manifest_paths(tmp_path) == []


def test_callback_exception_does_not_repeat_accepted_match(tmp_path):
    host = make_host(tmp_path)
    calls: list[int] = []

    def fail_callback(result):
        calls.append(result["seed"])
        raise RuntimeError("结果回调失败")

    with pytest.raises(RuntimeError, match="结果回调失败"):
        host.run_batch([make_task(tmp_path, seed=7)], fail_callback, lambda _: None)
    assert calls == [7]


def test_compatibility_failure_is_rejected_before_accepting_results(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_COMPAT_MODE", "unsupported")
    host = make_host(tmp_path)
    results: list[dict[str, object]] = []
    with pytest.raises(RuntimeError, match="原生关键接口检查失败"):
        host.run_batch([make_task(tmp_path, seed=1)], results.append, lambda _: None)
    assert results == []


def test_native_declaration_runs_one_counted_session(tmp_path):
    host = make_host(tmp_path)
    results, _ = run_batch(host, [make_task(tmp_path, seed=index) for index in range(65)])
    assert len(results) == 65
    paths = manifest_paths(tmp_path)
    assert len(paths) == 1
    assert read_lines(paths[0])[:2] == ["FM27DW2", "65"]


def test_compatibility_failure_stops_host_without_waiting_for_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_COMPAT_MODE", "unsupported")
    host = make_host(tmp_path)
    results: list[dict[str, object]] = []
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="原生关键接口检查失败"):
        host.run_batch(
            [
                make_task(tmp_path, variant="A", seed=1),
                make_task(tmp_path, variant="B", seed=2, fixture="slow.pkm"),
            ],
            results.append,
            lambda _: None,
        )
    assert time.monotonic() - started < 1.0
    assert results == []


def test_compatibility_failure_terminates_unresponsive_host(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SIMULATOR_COMPAT_MODE", "absent")
    host = make_host(tmp_path, cleanup_seconds=0.2)
    results: list[dict[str, object]] = []
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="原生启动兼容诊断缺失"):
        host.run_batch(
            [
                make_task(tmp_path, variant="A", seed=1),
                make_task(tmp_path, variant="B", seed=2, fixture="stubborn.pkm"),
            ],
            results.append,
            lambda _: None,
        )
    assert time.monotonic() - started < 1.0
    assert results == []


@pytest.mark.parametrize("workers", [0, 257, -1, True, False, 1.0, 2.5, "4", None])
def test_constructor_rejects_invalid_worker_counts(tmp_path, workers):
    root = tmp_path / "root"
    work = tmp_path / "work"
    root.mkdir()
    work.mkdir()
    with pytest.raises(ValueError, match=WORKER_ERROR):
        NativeEngineHost(root, work, executable=FAKE_SIMULATOR, workers=workers)


def test_invalid_worker_count_is_rejected_before_engine_probe(tmp_path, monkeypatch):
    probe_log = tmp_path / "probe.log"
    monkeypatch.setenv("FAKE_SIMULATOR_PROBE_LOG", str(probe_log))
    root = tmp_path / "root"
    work = tmp_path / "work"
    root.mkdir()
    work.mkdir()
    with pytest.raises(ValueError, match=WORKER_ERROR):
        NativeEngineHost(root, work, executable=FAKE_SIMULATOR, workers=0)
    assert not probe_log.exists()


def test_explicit_single_worker_matches_default_batch(tmp_path):
    tasks = [make_task(tmp_path, variant="A", seed=seed) for seed in range(6)]
    default_host = make_host(tmp_path, name="default")
    single_host = make_host(tmp_path, name="single", workers=1)
    default_results, default_progress = run_batch(default_host, tasks)
    single_results, single_progress = run_batch(single_host, tasks)
    assert normalized_results(default_results) == normalized_results(single_results)
    assert default_progress[-1] == []
    assert single_progress[-1] == []
    assert len(manifest_paths(tmp_path, "default")) == 1
    assert len(manifest_paths(tmp_path, "single")) == 1


def test_worker_lanes_clamp_to_task_count(tmp_path):
    host = make_host(tmp_path, workers=256)
    tasks = [make_task(tmp_path, variant="A", seed=seed) for seed in range(3)]
    results, _ = run_batch(host, tasks)
    assert sorted(result["seed"] for result in results) == [0, 1, 2]
    assert len(manifest_paths(tmp_path)) == 3


def test_worker_lanes_preserve_result_identity(tmp_path):
    tasks = [make_task(tmp_path, variant=variant, seed=seed) for variant in ("A", "B") for seed in range(6)]
    expected_pairs = {(task["variant"], task["seed"]) for task in tasks}
    identities: dict[int, list[dict[str, object]]] = {}
    session_counts: dict[int, int] = {}
    for workers in (1, 4, 8):
        host = make_host(tmp_path, name=f"workers-{workers}", workers=workers, plan=TWO_JOB_PLAN)
        results, _ = run_batch(host, tasks)
        assert len(results) == len(tasks)
        assert {(result["variant"], result["seed"]) for result in results} == expected_pairs
        assert all(result["verified"] is True and "failed" not in result for result in results)
        identities[workers] = normalized_results(results)
        session_counts[workers] = len(manifest_paths(tmp_path, f"workers-{workers}"))
    assert identities[1] == identities[4] == identities[8]
    assert session_counts == {1: 6, 4: 8, 8: 8}


def test_parallel_lanes_report_every_task_once(tmp_path):
    host = make_host(tmp_path, workers=8)
    tasks = [make_task(tmp_path, variant="A", seed=seed) for seed in range(16)]
    results, _ = run_batch(host, tasks)
    pairs = [(result["variant"], result["seed"]) for result in results]
    assert len(pairs) == len(tasks)
    assert len(set(pairs)) == len(tasks)
    assert set(pairs) == {(task["variant"], task["seed"]) for task in tasks}


def test_parallel_progress_merges_active_lanes(tmp_path):
    host = make_host(tmp_path, workers=4)
    tasks = [
        make_task(tmp_path, variant="A", seed=seed, fixture=f"slow{seed}.pkm") for seed in range(1, 5)
    ] + [make_task(tmp_path, variant="A", seed=seed) for seed in range(5, 9)]
    results, progress = run_batch(host, tasks)
    descriptors = [item for snapshot in progress for item in snapshot]
    assert set(descriptors[0]) == {
        "lane",
        "index",
        "variant",
        "seed",
        "worker_completed",
        "worker_total",
    }
    assert {item["lane"] for item in descriptors} == {0, 1, 2, 3}
    assert max(len(snapshot) for snapshot in progress) == 4
    assert all(item["worker_total"] == 2 for item in descriptors)
    assert progress[-1] == []
    assert len(results) == 8


def test_parallel_lanes_isolate_match_failures(tmp_path):
    host = make_host(tmp_path, workers=2)
    tasks = [
        make_task(tmp_path, variant="A", seed=1),
        make_task(tmp_path, variant="B", seed=2),
        make_task(tmp_path, variant="C", seed=3, fixture="fail.pkm"),
        make_task(tmp_path, variant="D", seed=4),
    ]
    results, _ = run_batch(host, tasks)
    assert len(results) == 4
    by_variant = {result["variant"]: result for result in results}
    assert set(by_variant) == {"A", "B", "C", "D"}
    assert by_variant["C"]["failed"] is True
    assert by_variant["C"]["error"] == "原生比赛终场记录无效"
    for variant in ("A", "B", "D"):
        assert "failed" not in by_variant[variant]
        assert by_variant[variant]["verified"] is True


def test_parallel_lanes_retry_unresolved_matches_only(tmp_path):
    host = make_host(tmp_path, workers=2, retries=1)
    tasks = [
        make_task(tmp_path, variant="A", seed=1, fixture="retry_once.pkm"),
        make_task(tmp_path, variant="B", seed=2),
        make_task(tmp_path, variant="C", seed=3),
        make_task(tmp_path, variant="D", seed=4),
    ]
    results, _ = run_batch(host, tasks)
    assert len(results) == 4
    assert {(result["variant"], result["seed"]) for result in results} == {
        ("A", 1),
        ("B", 2),
        ("C", 3),
        ("D", 4),
    }
    retried = next(result for result in results if result["variant"] == "A")
    assert retried.get("failed") is not True
    assert str(retried["log_path"]).endswith(".retry1.jsonl")
    assert len(manifest_paths(tmp_path)) == 3


def test_cancel_parallel_batch_discards_unfinished_matches(tmp_path):
    host = make_host(tmp_path, workers=4, timeout_seconds=60.0)
    tasks = [make_task(tmp_path, variant="A", seed=seed, fixture=f"slow{seed}.pkm") for seed in range(1, 9)]
    results: list[dict[str, object]] = []
    progress: list[list[dict[str, object]]] = []

    def on_progress(active):
        progress.append([dict(item) for item in active])
        if len(active) >= 2:
            host.cancel()

    started = time.monotonic()
    host.run_batch(tasks, results.append, on_progress)
    elapsed = time.monotonic() - started
    assert elapsed < 5.0
    assert max(len(snapshot) for snapshot in progress) >= 2
    assert results == []
    assert progress[-1] == []
    assert fake_simulator_processes() == []


def test_lane_failure_stops_other_lanes_and_raises(tmp_path):
    host = make_host(tmp_path, workers=2, timeout_seconds=60.0)
    tasks = [
        make_task(tmp_path, variant="A", seed=1, fixture="bad_ack.pkm"),
        make_task(tmp_path, variant="B", seed=2, fixture="slow.pkm"),
    ]
    results: list[dict[str, object]] = []
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="原生逐场释放标记无效"):
        host.run_batch(tasks, results.append, lambda _: None)
    assert time.monotonic() - started < 2.0
    assert results == []


def test_parallel_lane_batch_is_stable_across_repeats(tmp_path):
    tasks = [make_task(tmp_path, variant="A", seed=seed) for seed in range(10)]
    identities: list[list[dict[str, object]]] = []
    for attempt in range(3):
        host = make_host(tmp_path, name=f"repeat-{attempt}", workers=8, plan=TWO_JOB_PLAN)
        results, _ = run_batch(host, tasks)
        pairs = [(result["variant"], result["seed"]) for result in results]
        assert len(pairs) == len(tasks)
        assert len(set(pairs)) == len(tasks)
        identities.append(normalized_results(results))
    assert identities[0] == identities[1] == identities[2]
