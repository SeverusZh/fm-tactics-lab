"""catalog 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "catalog_snapshot",
        "读取运行时目录快照",
        ("GET", "/api/catalog"),
        ("catalog", "show"),
        "catalog_snapshot",
    ),
)
