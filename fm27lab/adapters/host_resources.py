from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

MEMINFO_PATH = Path("/proc/meminfo")
KIBIBYTE_BYTES = 1024
MEMORY_ERROR = "无法探测可用内存"
CPU_ERROR = "无法探测 CPU 数量"
DISK_ERROR = "无法探测空闲磁盘"


@dataclass(frozen=True, slots=True)
class HostResources:
    cpu_count: int
    available_memory_bytes: int
    free_disk_bytes: int


def _current_platform() -> str:
    return platform.system()


def _read_cpu_count() -> int:
    count = os.cpu_count()
    if count is None or count < 1:
        raise RuntimeError(CPU_ERROR)
    return count


def _meminfo_field(text: str, key: str) -> tuple[bool, int | None]:
    for line in text.splitlines():
        name, separator, rest = line.partition(":")
        if not separator or name.strip() != key:
            continue
        parts = rest.split()
        if not parts:
            return True, None
        try:
            value = int(parts[0])
        except ValueError:
            return True, None
        return True, value if value >= 0 else None
    return False, None


def _read_meminfo_available() -> int | None:
    try:
        text = MEMINFO_PATH.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    found, available = _meminfo_field(text, "MemAvailable")
    if not found:
        found, available = _meminfo_field(text, "MemFree")
    if not found or available is None:
        return None
    return available * KIBIBYTE_BYTES


def _read_windows_memory() -> int | None:
    import ctypes

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            ("total", ctypes.c_ulonglong),
            ("available", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.length = ctypes.sizeof(MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    available = int(status.available)
    return available if available >= 0 else None


def _sysconf(name: str) -> int:
    return os.sysconf(name)


def _read_sysconf_memory() -> int | None:
    try:
        pages = _sysconf("SC_PHYS_PAGES")
        page_size = _sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    if not isinstance(pages, int) or not isinstance(page_size, int):
        return None
    if pages < 1 or page_size < 1:
        return None
    return pages * page_size


def _read_memory_available() -> int:
    if _current_platform() == "Linux":
        available = _read_meminfo_available()
        if available is not None:
            return available
    if os.name == "nt":
        available = _read_windows_memory()
        if available is not None:
            return available
    available = _read_sysconf_memory()
    if available is not None:
        return available
    raise RuntimeError(MEMORY_ERROR)


def _read_free_disk(data_dir: Path) -> int:
    try:
        usage = shutil.disk_usage(data_dir)
    except OSError as error:
        raise RuntimeError(DISK_ERROR) from error
    free = int(usage.free)
    if free < 0:
        raise RuntimeError(DISK_ERROR)
    return free


def probe_host_resources(data_dir: Path) -> HostResources:
    return HostResources(
        cpu_count=_read_cpu_count(),
        available_memory_bytes=_read_memory_available(),
        free_disk_bytes=_read_free_disk(data_dir),
    )
