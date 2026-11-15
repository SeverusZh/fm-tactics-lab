"""system 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "system_resources",
        "探测宿主可用资源并给出推荐并行数",
        ("GET", "/api/system/resources"),
        ("system", "resources"),
        None,
    ),
)
