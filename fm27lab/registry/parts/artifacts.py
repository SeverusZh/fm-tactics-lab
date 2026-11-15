"""artifacts 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "artifacts_list", "分页列出产物", ("GET", "/api/artifacts"), ("artifacts", "list"), "artifacts_list"
    ),
    Capability(
        "artifacts_get",
        "查看单个产物",
        ("GET", "/api/artifacts/{artifact_id}"),
        ("artifacts", "get"),
        "artifacts_get",
    ),
    Capability(
        "artifacts_content",
        "下载产物文件内容",
        ("GET", "/api/artifacts/{artifact_id}/content"),
        ("artifacts", "content"),
        "artifacts_content",
    ),
    Capability(
        "artifacts_create",
        "登记产物",
        ("POST", "/api/artifacts"),
        ("artifacts", "create"),
        "artifacts_create",
    ),
    Capability(
        "artifacts_delete",
        "删除产物",
        ("DELETE", "/api/artifacts/{artifact_id}"),
        ("artifacts", "delete"),
        "artifacts_delete",
    ),
)
