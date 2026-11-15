"""concurrency 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "concurrency_check",
        "并发资源预检",
        ("GET", "/api/concurrency/check"),
        ("concurrency", "check"),
        "concurrency_check",
    ),
)
