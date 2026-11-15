"""pools 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability("pools_list", "分页列出战术池条目", ("GET", "/api/pools"), ("pools", "list"), "pools_list"),
    Capability(
        "pools_get",
        "查看单个战术池条目",
        ("GET", "/api/pools/{entry_id}"),
        ("pools", "get"),
        "pools_get",
    ),
    Capability(
        "pools_create",
        "创建战术池条目",
        ("POST", "/api/pools"),
        ("pools", "create"),
        "pools_create",
    ),
    Capability(
        "pools_delete",
        "删除战术池条目",
        ("DELETE", "/api/pools/{entry_id}"),
        ("pools", "delete"),
        "pools_delete",
    ),
)
