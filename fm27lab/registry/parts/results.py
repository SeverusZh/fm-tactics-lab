"""results 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "results_compare",
        "跨任务同种子配对比较",
        ("POST", "/api/results/compare"),
        ("results", "compare"),
        "results_compare",
    ),
)
