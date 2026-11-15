"""Pure concurrency preflight: worker limits, recommendation and resource checks."""

from __future__ import annotations

from typing import Any

MEMORY_PER_WORKER = 1024**3
MEMORY_RESERVE = 2 * 1024**3
DISK_PER_WORKER = 1024**3
MAX_WORKERS = 256

WORKERS_ERROR = "并行数必须为 1–256 的整数"
WARNING_OVERRIDE = "已按显式覆盖运行"
WARNING_ABOVE_RECOMMENDED = "并行数高于推荐值，收益不保证"
WARNING_INSUFFICIENT_MEMORY = "可用内存低于 2 GiB，资源预检未通过"
WARNING_INSUFFICIENT_DISK = "空闲磁盘不足，资源预检未通过"


def _require_int(value: Any, message: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(message)
    return value


def validate_workers(value: Any) -> int:
    """Accept only a strict integer inside the supported 1–256 range."""
    if type(value) is not int or not 1 <= value <= MAX_WORKERS:
        raise ValueError(WORKERS_ERROR)
    return value


def recommend_workers(*, cpu_count: int, available_memory_bytes: int) -> int:
    """Recommend a worker count from CPU cores and the memory budget.

    One worker lane costs 1 GiB on top of a 2 GiB reservation; the lower of the
    CPU and memory bounds wins and the result is clamped to the legal range.
    """
    cpu = _require_int(cpu_count, "CPU 数量必须为正整数", minimum=1)
    memory = _require_int(available_memory_bytes, "可用内存必须为非负整数", minimum=0)
    memory_lanes = (memory - MEMORY_RESERVE) // MEMORY_PER_WORKER
    return min(MAX_WORKERS, min(cpu, max(1, memory_lanes)))


def resource_check(
    workers: Any,
    *,
    cpu_count: int,
    available_memory_bytes: int,
    free_disk_bytes: int,
    allow_oversubscription: bool = False,
) -> dict[str, Any]:
    """Run the submit-time resource preflight for a requested worker count.

    Insufficient memory (below the 2 GiB reservation) or insufficient disk
    (one lane plus the reservation) blocks the submission unless the caller
    explicitly allows oversubscription. Workers above the recommendation only
    add a non-blocking warning.
    """
    validated = validate_workers(workers)
    recommended = recommend_workers(cpu_count=cpu_count, available_memory_bytes=available_memory_bytes)
    free_disk = _require_int(free_disk_bytes, "空闲磁盘必须为非负整数", minimum=0)
    if type(allow_oversubscription) is not bool:
        raise ValueError("资源覆盖开关必须为布尔值")
    memory_required = validated * MEMORY_PER_WORKER + MEMORY_RESERVE
    disk_required = validated * DISK_PER_WORKER + MEMORY_RESERVE
    blocked_code: str | None = None
    blocked_reason = ""
    if available_memory_bytes < MEMORY_RESERVE:
        blocked_code = "insufficient_memory"
        blocked_reason = WARNING_INSUFFICIENT_MEMORY
    elif free_disk < disk_required:
        blocked_code = "insufficient_disk"
        blocked_reason = WARNING_INSUFFICIENT_DISK
    warnings: list[str] = []
    code: str | None = None
    if blocked_code is not None:
        if allow_oversubscription:
            warnings.append(WARNING_OVERRIDE)
        else:
            code = blocked_code
            warnings.append(blocked_reason)
    if validated > recommended:
        warnings.append(WARNING_ABOVE_RECOMMENDED)
    return {
        "allowed": code is None,
        "code": code,
        "recommended_workers": recommended,
        "warnings": warnings,
        "memory_required_bytes": memory_required,
        "disk_required_bytes": disk_required,
    }
