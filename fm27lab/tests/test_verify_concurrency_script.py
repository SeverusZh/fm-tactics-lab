"""并发验收脚本的内存探测、容量覆盖与预检门。"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_concurrency_matrix.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("verify_concurrency_matrix", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_available_memory_bytes_reports_positive_value(script):
    assert script.available_memory_bytes() > 0


def test_windows_memory_bytes_returns_zero_off_windows(script):
    if sys.platform != "win32":
        assert script.windows_memory_bytes() == 0


def test_windows_memory_bytes_reads_win32_api(script, monkeypatch):
    class Kernel32:
        @staticmethod
        def GlobalMemoryStatusEx(pointer):
            pointer._obj.available_physical = 5 * 1024**3
            return 1

    class Windll:
        kernel32 = Kernel32()

    monkeypatch.setattr(script.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", Windll(), raising=False)
    assert script.windows_memory_bytes() == 5 * 1024**3


def test_windows_memory_bytes_returns_zero_when_api_fails(script, monkeypatch):
    class Kernel32:
        @staticmethod
        def GlobalMemoryStatusEx(pointer):
            return 0

    class Windll:
        kernel32 = Kernel32()

    monkeypatch.setattr(script.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", Windll(), raising=False)
    assert script.windows_memory_bytes() == 0


def test_applied_resources_applies_capacity_overrides(script):
    measured = {"cpu_count": 4, "available_memory_bytes": 8 * script.GIB, "free_disk_bytes": 90 * script.GIB}
    arguments = script.build_parser().parse_args(
        ["--available-memory-bytes", str(16 * script.GIB), "--free-disk-bytes", str(300 * script.GIB)]
    )
    resources = script.applied_resources(measured, arguments)
    assert resources == {
        "cpu_count": 4,
        "available_memory_bytes": 16 * script.GIB,
        "free_disk_bytes": 300 * script.GIB,
    }
    assert measured["available_memory_bytes"] == 8 * script.GIB


def test_applied_resources_keeps_measured_values_without_overrides(script):
    measured = {"cpu_count": 4, "available_memory_bytes": 8 * script.GIB, "free_disk_bytes": 90 * script.GIB}
    arguments = script.build_parser().parse_args([])
    assert script.applied_resources(measured, arguments) == measured


def test_applied_resources_rejects_non_positive_override(script):
    measured = {"cpu_count": 4, "available_memory_bytes": 8 * script.GIB, "free_disk_bytes": 90 * script.GIB}
    arguments = script.build_parser().parse_args(["--free-disk-bytes", "0"])
    with pytest.raises(script.VerificationError):
        script.applied_resources(measured, arguments)


def test_preflight_rejects_capacity_below_requirement(script):
    log = script.CheckLog()
    script.run_preflight(
        log,
        {"cpu_count": 4, "available_memory_bytes": 16 * script.GIB, "free_disk_bytes": 3 * script.GIB},
        (2,),
        Path("fake_simulator.py"),
    )
    assert log.passed() is False


def test_preflight_passes_with_overridden_capacity(script):
    log = script.CheckLog()
    script.run_preflight(
        log,
        {"cpu_count": 4, "available_memory_bytes": 16 * script.GIB, "free_disk_bytes": 300 * script.GIB},
        (1, 8, 256),
        Path("fake_simulator.py"),
    )
    assert log.passed() is True


def test_job_error_reports_recorded_batch_error(script):
    final = {"status": "error", "summary": {"error": "原生逐场释放标记无效"}}
    assert script.job_error(final) == "原生逐场释放标记无效"


def test_job_error_is_absent_for_completed_batch(script):
    assert script.job_error({"status": "completed", "summary": {}}) is None
    assert script.job_error({"status": "completed"}) is None
    assert script.job_error(None) is None
