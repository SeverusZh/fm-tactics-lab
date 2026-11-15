"""定位球能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "setpieces_list",
        "列出主客队定位球配置摘要与可选类型",
        ("GET", "/api/setpieces"),
        ("setpieces", "list"),
        "setpieces_list",
    ),
    Capability(
        "setpieces_get",
        "读取单队定位球配置与默认值",
        ("GET", "/api/setpieces/{setpiece_id}"),
        ("setpieces", "get"),
        "setpieces_get",
    ),
    Capability(
        "setpieces_update",
        "校验并保存单队定位球配置",
        ("PATCH", "/api/setpieces/{setpiece_id}"),
        ("setpieces", "update"),
        "setpieces_update",
    ),
    Capability(
        "setpieces_import_file",
        "导入定位球 JSON 文档",
        ("POST", "/api/setpieces/{setpiece_id}/import-file"),
        ("setpieces", "import-file"),
        "setpieces_import_file",
    ),
    Capability(
        "setpieces_export_file",
        "导出定位球 JSON 文档",
        ("GET", "/api/setpieces/{setpiece_id}/export-file"),
        ("setpieces", "export-file"),
        "setpieces_export_file",
    ),
)
