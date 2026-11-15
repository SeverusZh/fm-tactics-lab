"""drafts 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "drafts_list",
        "分页列出场景草案",
        ("GET", "/api/drafts"),
        ("drafts", "list"),
        "drafts_list",
    ),
    Capability(
        "drafts_get",
        "查看单个场景草案",
        ("GET", "/api/drafts/{draft_id}"),
        ("drafts", "get"),
        "drafts_get",
    ),
    Capability(
        "drafts_create",
        "创建场景草案",
        ("POST", "/api/drafts"),
        ("drafts", "create"),
        "drafts_create",
    ),
    Capability(
        "drafts_update",
        "更新场景草案",
        ("PATCH", "/api/drafts/{draft_id}"),
        ("drafts", "update"),
        "drafts_update",
    ),
    Capability(
        "drafts_delete",
        "删除场景草案",
        ("DELETE", "/api/drafts/{draft_id}"),
        ("drafts", "delete"),
        "drafts_delete",
    ),
    Capability(
        "drafts_attributes",
        "批量编辑场景草案球员属性",
        ("POST", "/api/drafts/{draft_id}/attributes"),
        ("drafts", "attributes"),
        "drafts_attributes",
    ),
    Capability(
        "drafts_export_fmf",
        "导出场景草案为 FMF 文件",
        ("GET", "/api/drafts/{draft_id}/export.fmf"),
        ("drafts", "export-fmf"),
        "drafts_export_fmf",
    ),
    Capability(
        "drafts_import_fmf",
        "从 FMF 文件导入场景草案",
        ("POST", "/api/drafts/import-fmf"),
        ("drafts", "import-fmf"),
        "drafts_import_fmf",
    ),
    Capability(
        "drafts_import_fmf_file",
        "从本地 FMF 文件导入场景草案",
        ("POST", "/api/drafts/import-fmf-file"),
        ("drafts", "import-fmf-file"),
    ),
    Capability(
        "drafts_apply_roster",
        "把存档名单同步到场景草案阵容",
        ("POST", "/api/drafts/{draft_id}/apply-roster"),
        ("drafts", "apply-roster"),
        "drafts_apply_roster",
    ),
    Capability(
        "drafts_undo_roster",
        "撤销场景草案的阵容同步",
        ("POST", "/api/drafts/{draft_id}/undo-roster"),
        ("drafts", "undo-roster"),
        "drafts_undo_roster",
    ),
)
