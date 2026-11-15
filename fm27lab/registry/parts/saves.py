"""saves 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "saves_list",
        "分页列出存档",
        ("GET", "/api/saves"),
        ("saves", "list"),
        "saves_list",
    ),
    Capability(
        "saves_get",
        "查看单个存档",
        ("GET", "/api/saves/{save_id}"),
        ("saves", "get"),
        "saves_get",
    ),
    Capability(
        "saves_create",
        "登记存档",
        ("POST", "/api/saves"),
        ("saves", "create"),
        "saves_create",
    ),
    Capability(
        "saves_update",
        "更新存档状态或元数据",
        ("PATCH", "/api/saves/{save_id}"),
        ("saves", "update"),
        "saves_update",
    ),
    Capability(
        "saves_delete",
        "删除存档",
        ("DELETE", "/api/saves/{save_id}"),
        ("saves", "delete"),
        "saves_delete",
    ),
    Capability(
        "saves_import",
        "从存档文件导入存档与俱乐部名单",
        ("POST", "/api/saves/import"),
        ("saves", "import-file"),
        "saves_import_file",
    ),
    Capability(
        "saves_squad",
        "读取存档中的俱乐部名单",
        ("GET", "/api/saves/{save_id}/squad"),
        ("saves", "squad"),
        "saves_squad",
    ),
    Capability(
        "saves_import_payload",
        "导入存档联赛与俱乐部数据",
        ("POST", "/api/saves/{save_id}/import"),
        ("saves", "import"),
        "saves_import",
    ),
)
