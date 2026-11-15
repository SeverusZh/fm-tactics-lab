"""三入口能力契约注册表：HTTP、CLI 与 MCP 的能力映射与漂移校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass

HTTP_METHODS: frozenset[str] = frozenset({"DELETE", "GET", "PATCH", "POST", "PUT"})
SYSTEM_PATHS: frozenset[str] = frozenset(
    {
        "/api/docs",
        "/api/engine",
        "/api/engine/diagnose",
        "/api/engine/import",
        "/api/engine/select",
        "/api/events",
        "/api/health",
        "/api/openapi.json",
        "/api/shutdown",
        "/api/saves/{save_id}/tactics",
        "/api/saves/{save_id}/tactics/{tactic_index}/export.fmf",
        "/api/saves/{save_id}/tactics/{tactic_index}/import",
        "/api/saves/{save_id}/tactics/{tactic_index}/pool",
        "/api/system/restart",
        "/api/tactics/template",
        "/api/version",
    }
)
SYSTEM_CLI_COMMANDS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("mcp",),
        ("serve",),
        ("version",),
    }
)
CAPABILITY_GROUPS: dict[str, tuple[str, str | None]] = {
    "artifacts": ("/api/artifacts", "artifact_id"),
    "catalog": ("/api/catalog", None),
    "concurrency": ("/api/concurrency", None),
    "drafts": ("/api/drafts", "draft_id"),
    "experiments": ("/api/experiments", "job_id"),
    "formations": ("/api/formations", "formation_id"),
    "jobs": ("/api/jobs", "job_id"),
    "pools": ("/api/pools", "entry_id"),
    "results": ("/api/results", None),
    "saves": ("/api/saves", "save_id"),
    "setpieces": ("/api/setpieces", "setpiece_id"),
    "settings": ("/api/settings", "key"),
    "system": ("/api/system", None),
}
ACTION_METHODS: dict[str, str] = {
    "apply_roster": "POST",
    "attributes": "POST",
    "batch_actions": "POST",
    "batch_delete": "DELETE",
    "cancel": "POST",
    "check": "GET",
    "compare": "POST",
    "content": "GET",
    "create": "POST",
    "delete": "DELETE",
    "export": "GET",
    "export_file": "GET",
    "export_fmf": "GET",
    "formation": "POST",
    "get": "GET",
    "import": "POST",
    "import_file": "POST",
    "import_fmf": "POST",
    "import_fmf_file": "POST",
    "import_payload": "POST",
    "list": "GET",
    "pool_summary": "GET",
    "put": "PUT",
    "resources": "GET",
    "resume": "POST",
    "runs": "GET",
    "snapshot": "GET",
    "squad": "GET",
    "start": "POST",
    "submit": "POST",
    "summary": "GET",
    "undo_roster": "POST",
    "update": "PATCH",
}
ITEM_ACTIONS: frozenset[str] = frozenset(
    {
        "apply_roster",
        "attributes",
        "cancel",
        "content",
        "delete",
        "export",
        "export_file",
        "export_fmf",
        "formation",
        "get",
        "import_file",
        "import_payload",
        "pool_summary",
        "put",
        "resume",
        "runs",
        "squad",
        "summary",
        "undo_roster",
        "update",
    }
)
_PATH_PARAMETER = re.compile(r"{(\w+)}")


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    description: str
    http: tuple[str, str]
    cli: tuple[str, ...] | None = None
    mcp: str | None = None
