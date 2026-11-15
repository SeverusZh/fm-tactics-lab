from __future__ import annotations

import pytest

from fm27lab.domain.concurrency import (
    DISK_PER_WORKER,
    MAX_WORKERS,
    MEMORY_PER_WORKER,
    MEMORY_RESERVE,
    recommend_workers,
    resource_check,
    validate_workers,
)

GIB = 1024**3
WORKERS_ERROR = "并行数必须为 1–256 的整数"
OVERRIDE_WARNING = "已按显式覆盖运行"
ABOVE_RECOMMENDED_WARNING = "并行数高于推荐值，收益不保证"
CHECK_KEYS = {
    "allowed",
    "code",
    "recommended_workers",
    "warnings",
    "memory_required_bytes",
    "disk_required_bytes",
}


def check(**overrides):
    values = {
        "workers": 4,
        "cpu_count": 8,
        "available_memory_bytes": 32 * GIB,
        "free_disk_bytes": 100 * GIB,
    }
    values.update(overrides)
    workers = values.pop("workers")
    return resource_check(workers, **values)


def test_resource_constants():
    assert MEMORY_PER_WORKER == GIB
    assert MEMORY_RESERVE == 2 * GIB
    assert DISK_PER_WORKER == GIB
    assert MAX_WORKERS == 256


@pytest.mark.parametrize("value", [1, 2, 8, 128, 256])
def test_validate_workers_accepts_integer_range(value):
    assert validate_workers(value) == value


@pytest.mark.parametrize(
    "value",
    [0, -1, 257, 1000, True, False, 1.0, 8.0, "8", None, [8], {"workers": 8}, 8j],
)
def test_validate_workers_rejects_non_integer_or_out_of_range(value):
    with pytest.raises(ValueError, match=WORKERS_ERROR):
        validate_workers(value)


@pytest.mark.parametrize(
    ("cpu_count", "available_memory_bytes", "expected"),
    [
        (8, 64 * GIB, 8),
        (8, 5 * GIB, 3),
        (8, 4 * GIB, 2),
        (4, 3 * GIB, 1),
        (4, 2 * GIB, 1),
        (4, GIB, 1),
        (4, 0, 1),
        (1, 64 * GIB, 1),
        (256, 4096 * GIB, 256),
        (1000, 4096 * GIB, 256),
    ],
)
def test_recommend_workers_uses_cpu_and_memory_budget(cpu_count, available_memory_bytes, expected):
    assert recommend_workers(cpu_count=cpu_count, available_memory_bytes=available_memory_bytes) == expected


@pytest.mark.parametrize("cpu_count", [0, -1, True, 1.0, "8", None])
def test_recommend_workers_rejects_invalid_cpu_count(cpu_count):
    with pytest.raises(ValueError, match="CPU"):
        recommend_workers(cpu_count=cpu_count, available_memory_bytes=64 * GIB)


@pytest.mark.parametrize("available_memory_bytes", [-1, True, 1.0, "1024", None])
def test_recommend_workers_rejects_invalid_memory(available_memory_bytes):
    with pytest.raises(ValueError, match="内存"):
        recommend_workers(cpu_count=8, available_memory_bytes=available_memory_bytes)


def test_resource_check_allows_sufficient_resources():
    result = check()
    assert set(result) == CHECK_KEYS
    assert result["allowed"] is True
    assert result["code"] is None
    assert result["recommended_workers"] == 8
    assert result["warnings"] == []
    assert result["memory_required_bytes"] == 4 * GIB + 2 * GIB
    assert result["disk_required_bytes"] == 4 * GIB + 2 * GIB


def test_resource_check_warns_above_recommended_workers():
    result = check(workers=8, cpu_count=2)
    assert result["allowed"] is True
    assert result["code"] is None
    assert result["recommended_workers"] == 2
    assert result["warnings"] == [ABOVE_RECOMMENDED_WARNING]


def test_resource_check_does_not_warn_at_recommended_workers():
    result = check(workers=2, cpu_count=2)
    assert result["allowed"] is True
    assert result["warnings"] == []


def test_resource_check_blocks_insufficient_memory():
    result = check(workers=8, available_memory_bytes=GIB)
    assert result["allowed"] is False
    assert result["code"] == "insufficient_memory"
    assert result["recommended_workers"] == 1
    assert any("内存" in warning for warning in result["warnings"])
    assert ABOVE_RECOMMENDED_WARNING in result["warnings"]
    assert result["memory_required_bytes"] == 8 * GIB + 2 * GIB


def test_resource_check_prefers_memory_block_when_both_resources_are_short():
    result = check(workers=2, available_memory_bytes=GIB, free_disk_bytes=GIB)
    assert result["allowed"] is False
    assert result["code"] == "insufficient_memory"


def test_resource_check_blocks_insufficient_disk():
    result = check(workers=4, free_disk_bytes=5 * GIB)
    assert result["allowed"] is False
    assert result["code"] == "insufficient_disk"
    assert any("磁盘" in warning for warning in result["warnings"])
    assert result["disk_required_bytes"] == 4 * GIB + 2 * GIB


def test_resource_check_accepts_exact_disk_requirement():
    result = check(workers=4, free_disk_bytes=6 * GIB)
    assert result["allowed"] is True
    assert result["code"] is None


def test_resource_check_override_covers_insufficient_memory():
    result = check(workers=4, available_memory_bytes=GIB, allow_oversubscription=True)
    assert result["allowed"] is True
    assert result["code"] is None
    assert OVERRIDE_WARNING in result["warnings"]
    assert ABOVE_RECOMMENDED_WARNING in result["warnings"]


def test_resource_check_override_covers_insufficient_disk():
    result = check(workers=4, free_disk_bytes=GIB, allow_oversubscription=True)
    assert result["allowed"] is True
    assert result["code"] is None
    assert OVERRIDE_WARNING in result["warnings"]


def test_resource_check_override_is_ignored_when_resources_are_sufficient():
    result = check(allow_oversubscription=True)
    assert result["allowed"] is True
    assert result["warnings"] == []


def test_resource_check_blocked_reason_is_reported_without_override():
    result = check(workers=2, available_memory_bytes=GIB)
    assert result["allowed"] is False
    assert OVERRIDE_WARNING not in result["warnings"]
    assert result["warnings"]


@pytest.mark.parametrize("workers", [0, 257, True, 1.0, "4"])
def test_resource_check_rejects_invalid_workers(workers):
    with pytest.raises(ValueError, match=WORKERS_ERROR):
        resource_check(
            workers,
            cpu_count=8,
            available_memory_bytes=32 * GIB,
            free_disk_bytes=100 * GIB,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cpu_count", 0),
        ("cpu_count", -1),
        ("cpu_count", True),
        ("cpu_count", 1.0),
        ("available_memory_bytes", -1),
        ("available_memory_bytes", True),
        ("available_memory_bytes", "1024"),
        ("free_disk_bytes", -1),
        ("free_disk_bytes", True),
        ("free_disk_bytes", "1024"),
        ("allow_oversubscription", 1),
        ("allow_oversubscription", "yes"),
    ],
)
def test_resource_check_rejects_invalid_parameters(field, value):
    values = {
        "cpu_count": 8,
        "available_memory_bytes": 32 * GIB,
        "free_disk_bytes": 100 * GIB,
    }
    values[field] = value
    with pytest.raises(ValueError):
        resource_check(4, **values)
