"""formations 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "formations_list",
        "列出内置阵型模板与战术编辑选项",
        ("GET", "/api/formations"),
        ("formations", "list"),
        "formations_list",
    ),
)
