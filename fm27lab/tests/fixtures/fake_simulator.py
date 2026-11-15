"""Fake native engine host used by the engine adapter tests.

The process is started through sys.executable. It consumes the worker manifest
protocol, writes the session startup diagnostics file, and writes one JSONL
match log plus a .worker_done sidecar per match, mirroring the real
FM27Simulator.exe contract. Behaviour is selected by the fixture file name or
FAKE_SIMULATOR_* environment variables so one script covers capability
negotiation, success, failure, timeout and retry scenarios.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

DEFAULT_CAPABILITIES = {
    "protocol": 2,
    "max_jobs": 1000000,
    "execution_context_reset": True,
    "per_match_resource_release": True,
}
LEGACY_CAPABILITIES = {"counted_sessions": False, "jobs_per_session": 64}
CANCEL_EXIT_CODE = 86
RETRY_STATE_SUFFIX = ".retry-state"
SLOW_SECONDS = 2.0
WORKER_DONE_SUFFIX = ".worker_done"


def _log_argv(argv):
    target = os.environ.get("FAKE_SIMULATOR_ARGV_LOG")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(argv, ensure_ascii=False) + "\n")


def _log_environment():
    target = os.environ.get("FAKE_SIMULATOR_ENV_LOG")
    if not target:
        return
    Path(target).write_text(json.dumps(sorted(os.environ), ensure_ascii=False) + "\n", encoding="utf-8")


def _capabilities():
    probe_log = os.environ.get("FAKE_SIMULATOR_PROBE_LOG")
    if probe_log:
        with open(probe_log, "a", encoding="utf-8") as stream:
            stream.write("probe\n")
    exit_code = os.environ.get("FAKE_SIMULATOR_CAPABILITIES_EXIT")
    if exit_code:
        return int(exit_code)
    payload = os.environ.get("FAKE_SIMULATOR_CAPABILITIES")
    if payload is None:
        schema = os.environ.get("FAKE_SIMULATOR_CAPABILITIES_SCHEMA", "native")
        payload = json.dumps(LEGACY_CAPABILITIES if schema == "legacy" else DEFAULT_CAPABILITIES)
    sys.stdout.write("fake simulator capability diagnostic\n")
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()
    return 0


def _option(argv, flag):
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def _cancelled(argv):
    path = _option(argv, "--cancel-event")
    return bool(path) and Path(path).exists()


def _sleep(seconds, argv):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _cancelled(argv):
            return False
        time.sleep(0.02)
    return True


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def _append_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _write_rows(path, rows):
    lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_worker_done(path, index, released=True):
    done = Path(str(path) + WORKER_DONE_SUFFIX)
    _write_json(done, {"index": index, "pid": os.getpid(), "released": released, "exit_code": 0})


def _success_rows(seed):
    home = seed % 4
    away = (seed * 7) % 3
    return [
        {"event": "simulator_started", "isolated_desktop": True, "full_match_completed": False},
        {
            "event": "natural_match_finished",
            "full_match_completed": True,
            "tick": 47900,
            "clock": "90:00",
            "score": [home, away],
        },
        {
            "event": "native_match_statistics",
            "teams": [
                {"shots": home + 5, "completed_passes": 10},
                {"shots": away + 5, "completed_passes": 9},
            ],
        },
        {"event": "native_match_events", "events": {"goals": [], "cards": []}},
    ]


def _read_manifest(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise SystemExit(184)
    magic = lines[0]
    if magic == "FM27DW2":
        try:
            count = int(lines[1])
        except (IndexError, ValueError):
            raise SystemExit(184) from None
        if count < 1 or len(lines[1:]) != 1 + count * 5:
            raise SystemExit(184)
        body = lines[2:]
    elif magic == "FM27DW1":
        body = lines[1:]
        if not body or len(body) % 5:
            raise SystemExit(184)
    else:
        raise SystemExit(184)
    tasks = []
    for offset in range(0, len(body), 5):
        fixture, config, output, seed_text, dump = body[offset : offset + 5]
        try:
            seed = int(seed_text)
        except ValueError:
            raise SystemExit(184) from None
        if not fixture or not output or not 0 <= seed <= 0xFFFFFFFF:
            raise SystemExit(184)
        tasks.append({"fixture": fixture, "config": config, "output": output, "seed": seed, "dump": dump})
    return magic, tasks


def _write_startup(path):
    mode = os.environ.get("FAKE_SIMULATOR_COMPAT_MODE", "supported")
    if mode == "absent":
        return
    if mode == "directory":
        path.mkdir(parents=True, exist_ok=True)
        return
    rows = []
    if mode != "no_row":
        rows.append(
            {
                "event": "native_engine_compatibility",
                "compatible": mode == "supported",
                "trial_allowed": mode == "trial",
            }
        )
    rows.append({"event": "native_image_fingerprint", "sha256": "0" * 64})
    _write_rows(path, rows)


def _finish_session(startup, exit_code):
    if Path(startup).is_dir():
        return exit_code
    cleanup = os.environ.get("FAKE_SIMULATOR_STEAM_CLEANUP", "ok")
    if cleanup != "missing":
        _append_json(Path(startup), {"event": "steam_session_cleanup", "ok": cleanup == "ok"})
    return exit_code


def _worker(argv):
    manifest = _option(argv, "--worker-manifest")
    startup = _option(argv, "--output")
    if not manifest or not startup:
        return 184
    try:
        magic, tasks = _read_manifest(Path(manifest))
    except (OSError, SystemExit):
        return 184
    _log_environment()
    _write_startup(Path(startup))
    sys.stderr.write("fake simulator stderr diagnostic\n")
    sys.stderr.flush()
    exit_after = int(os.environ.get("FAKE_SIMULATOR_EXIT_AFTER", "0"))
    for position, task in enumerate(tasks, start=1):
        if exit_after and position > exit_after:
            return 180
        if _cancelled(argv):
            return CANCEL_EXIT_CODE
        fixture = Path(task["fixture"])
        name = fixture.name.lower()
        output = Path(task["output"])
        if "slow" in name and not _sleep(SLOW_SECONDS, argv):
            return CANCEL_EXIT_CODE
        if "stubborn" in name:
            time.sleep(SLOW_SECONDS)
        if "exit1" in name:
            sys.stderr.write("fake simulator forced exit\n")
            sys.stderr.flush()
            return 1
        if "retry_once" in name:
            state = fixture.with_name(fixture.name + RETRY_STATE_SUFFIX)
            if not state.exists():
                state.write_text("failed once\n", encoding="utf-8")
                return 1
        if "bad_ack" in name:
            _write_rows(output, _success_rows(task["seed"]))
            _write_worker_done(output, position, released=False)
            return 0
        if "bad_output" in name:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("this line is not json\n", encoding="utf-8")
            _write_worker_done(output, position)
            continue
        if "fail" in name:
            _write_rows(output, [{"event": "simulator_started", "full_match_completed": False}])
            _write_worker_done(output, position)
            continue
        _write_rows(output, _success_rows(task["seed"]))
        _write_worker_done(output, position)
    exit_code = int(os.environ.get("FAKE_SIMULATOR_WORKER_EXIT", "0"))
    return _finish_session(startup, exit_code)


def main(argv):
    _log_argv(argv)
    if "--worker-capabilities" in argv:
        return _capabilities()
    if "--worker-manifest" in argv:
        return _worker(argv)
    sys.stderr.write("fake simulator: unsupported invocation\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
