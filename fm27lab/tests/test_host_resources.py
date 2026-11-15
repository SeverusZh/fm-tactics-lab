from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from fm27lab.adapters import host_resources
from fm27lab.adapters.host_resources import HostResources, probe_host_resources

GIB = 1024**3
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def write_meminfo(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_probe_reports_cpu_memory_and_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(host_resources, "_read_cpu_count", lambda: 12)
    monkeypatch.setattr(host_resources, "_read_memory_available", lambda: 6 * GIB)
    expected_disk = host_resources.shutil.disk_usage(tmp_path).free
    probe = probe_host_resources(tmp_path)
    assert probe == HostResources(
        cpu_count=12,
        available_memory_bytes=6 * GIB,
        free_disk_bytes=expected_disk,
    )
    assert type(probe.cpu_count) is int
    assert type(probe.available_memory_bytes) is int
    assert type(probe.free_disk_bytes) is int


def test_probe_propagates_cpu_probe_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def unavailable() -> int:
        raise RuntimeError("无法探测 CPU 数量")

    monkeypatch.setattr(host_resources, "_read_cpu_count", unavailable)
    with pytest.raises(RuntimeError, match="无法探测 CPU 数量"):
        probe_host_resources(tmp_path)


@pytest.mark.parametrize("value", [None, 0, -4])
def test_cpu_probe_rejects_missing_or_invalid_count(monkeypatch: pytest.MonkeyPatch, value):
    monkeypatch.setattr(host_resources.os, "cpu_count", lambda: value)
    with pytest.raises(RuntimeError, match="无法探测 CPU 数量"):
        host_resources._read_cpu_count()


def test_meminfo_memavailable_is_converted_from_kibibytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = write_meminfo(
        tmp_path / "meminfo",
        "MemTotal: 16384000 kB\nMemAvailable: 2097152 kB\nMemFree: 1024 kB\n",
    )
    monkeypatch.setattr(host_resources, "MEMINFO_PATH", path)
    assert host_resources._read_meminfo_available() == 2097152 * 1024


def test_meminfo_missing_memavailable_falls_back_to_memfree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = write_meminfo(tmp_path / "meminfo", "MemTotal: 16384000 kB\nMemFree: 524288 kB\n")
    monkeypatch.setattr(host_resources, "MEMINFO_PATH", path)
    assert host_resources._read_meminfo_available() == 524288 * 1024


def test_meminfo_invalid_memavailable_fails_the_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = write_meminfo(
        tmp_path / "meminfo",
        "MemAvailable: not-a-number kB\nMemFree: 524288 kB\n",
    )
    monkeypatch.setattr(host_resources, "MEMINFO_PATH", path)
    assert host_resources._read_meminfo_available() is None


def test_meminfo_negative_memavailable_fails_the_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = write_meminfo(
        tmp_path / "meminfo",
        "MemAvailable: -1024 kB\nMemFree: 524288 kB\n",
    )
    monkeypatch.setattr(host_resources, "MEMINFO_PATH", path)
    assert host_resources._read_meminfo_available() is None


def test_negative_memavailable_falls_through_to_sysconf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = write_meminfo(
        tmp_path / "meminfo",
        "MemAvailable: -1024 kB\nMemFree: 524288 kB\n",
    )
    monkeypatch.setattr(host_resources, "MEMINFO_PATH", path)
    monkeypatch.setattr(host_resources, "_current_platform", lambda: "Linux")
    monkeypatch.setattr(host_resources.os, "name", "posix")
    sizes = {"SC_PHYS_PAGES": 1024, "SC_PAGE_SIZE": 4096}
    monkeypatch.setattr(host_resources, "_sysconf", lambda name: sizes[name])
    assert host_resources._read_memory_available() == 1024 * 4096


def test_meminfo_unreadable_file_fails_the_strategy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(host_resources, "MEMINFO_PATH", tmp_path / "absent")
    assert host_resources._read_meminfo_available() is None


def test_linux_falls_back_to_sysconf_when_meminfo_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(host_resources, "MEMINFO_PATH", tmp_path / "absent")
    monkeypatch.setattr(host_resources, "_current_platform", lambda: "Linux")
    monkeypatch.setattr(host_resources.os, "name", "posix")
    sizes = {"SC_PHYS_PAGES": 1024, "SC_PAGE_SIZE": 4096}
    monkeypatch.setattr(host_resources, "_sysconf", lambda name: sizes[name])
    assert host_resources._read_memory_available() == 1024 * 4096


def test_sysconf_memory_multiplies_pages_by_page_size(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(host_resources, "_current_platform", lambda: "Darwin")
    monkeypatch.setattr(host_resources.os, "name", "posix")
    sizes = {"SC_PHYS_PAGES": 2048, "SC_PAGE_SIZE": 8192}
    monkeypatch.setattr(host_resources, "_sysconf", lambda name: sizes[name])
    assert host_resources._read_memory_available() == 2048 * 8192


def install_fake_ctypes(monkeypatch: pytest.MonkeyPatch, kernel32) -> None:
    fake = types.SimpleNamespace(
        Structure=type("Structure", (), {}),
        sizeof=lambda status: 64,
        byref=lambda status: status,
        c_ulong=int,
        c_ulonglong=int,
        windll=types.SimpleNamespace(kernel32=kernel32),
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake)


class FakeKernel32:
    def __init__(self, succeed: bool, available: int) -> None:
        self.succeed = succeed
        self.available = available
        self.calls = 0

    def GlobalMemoryStatusEx(self, memory) -> int:
        self.calls += 1
        memory.available = self.available
        return 1 if self.succeed else 0


def test_windows_branch_reads_global_memory_status(monkeypatch: pytest.MonkeyPatch):
    kernel32 = FakeKernel32(succeed=True, available=3 * GIB)
    install_fake_ctypes(monkeypatch, kernel32)
    monkeypatch.setattr(host_resources, "_current_platform", lambda: "Windows")
    monkeypatch.setattr(host_resources.os, "name", "nt")
    assert host_resources._read_memory_available() == 3 * GIB
    assert kernel32.calls == 1


def test_windows_probe_failure_falls_back_to_sysconf(monkeypatch: pytest.MonkeyPatch):
    kernel32 = FakeKernel32(succeed=False, available=0)
    install_fake_ctypes(monkeypatch, kernel32)
    monkeypatch.setattr(host_resources, "_current_platform", lambda: "Windows")
    monkeypatch.setattr(host_resources.os, "name", "nt")
    sizes = {"SC_PHYS_PAGES": 512, "SC_PAGE_SIZE": 4096}
    monkeypatch.setattr(host_resources, "_sysconf", lambda name: sizes[name])
    assert host_resources._read_memory_available() == 512 * 4096


def test_memory_probe_failure_uses_chinese_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(host_resources, "MEMINFO_PATH", tmp_path / "absent")
    monkeypatch.setattr(host_resources, "_current_platform", lambda: "Linux")
    monkeypatch.setattr(host_resources.os, "name", "posix")

    def unavailable(name):
        raise OSError("sysconf unavailable")

    monkeypatch.setattr(host_resources, "_sysconf", unavailable)
    with pytest.raises(RuntimeError, match="无法探测可用内存"):
        host_resources._read_memory_available()


def test_missing_sysconf_strategy_uses_chinese_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(host_resources, "_current_platform", lambda: "Darwin")
    monkeypatch.setattr(host_resources.os, "name", "posix")

    def missing(name):
        raise AttributeError("sysconf unavailable")

    monkeypatch.setattr(host_resources, "_sysconf", missing)
    with pytest.raises(RuntimeError, match="无法探测可用内存"):
        host_resources._read_memory_available()


def test_disk_probe_wraps_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def unavailable(path):
        raise OSError("disk unavailable")

    monkeypatch.setattr(host_resources.shutil, "disk_usage", unavailable)
    with pytest.raises(RuntimeError, match="无法探测空闲磁盘"):
        host_resources._read_free_disk(tmp_path)


def test_importing_module_does_not_touch_ctypes():
    assert "ctypes" not in vars(host_resources)
    script = """
import sys

class BlockCtypes:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "ctypes" or fullname.startswith("ctypes."):
            raise ImportError("ctypes is not available on this platform")
        return None

assert "ctypes" not in sys.modules
sys.meta_path.insert(0, BlockCtypes())
import fm27lab.adapters.host_resources  # noqa: F401
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
