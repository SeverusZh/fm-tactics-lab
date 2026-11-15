"""settings 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "settings_list", "列出设置项", ("GET", "/api/settings"), ("settings", "list"), "settings_list"
    ),
    Capability(
        "settings_get", "查看单个设置项", ("GET", "/api/settings/{key}"), ("settings", "get"), "settings_get"
    ),
    Capability(
        "settings_put", "写入设置项", ("PUT", "/api/settings/{key}"), ("settings", "put"), "settings_put"
    ),
    Capability(
        "settings_delete",
        "删除设置项",
        ("DELETE", "/api/settings/{key}"),
        ("settings", "delete"),
        "settings_delete",
    ),
)
