"""三入口能力契约注册表：HTTP、CLI 与 MCP 的能力映射与漂移校验。"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

HTTP_METHODS: frozenset[str] = frozenset({"DELETE", "GET", "PATCH", "POST", "PUT"})
SYSTEM_PATHS: frozenset[str] = frozenset(
    {
        "/api/docs",
        "/api/events",
        "/api/health",
        "/api/openapi.json",
        "/api/shutdown",
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
    "jobs": ("/api/jobs", "job_id"),
    "pools": ("/api/pools", "entry_id"),
    "saves": ("/api/saves", "save_id"),
    "settings": ("/api/settings", "key"),
}
ACTION_METHODS: dict[str, str] = {
    "attributes": "POST",
    "batch_actions": "POST",
    "batch_delete": "DELETE",
    "cancel": "POST",
    "check": "GET",
    "content": "GET",
    "create": "POST",
    "delete": "DELETE",
    "export": "GET",
    "export_fmf": "GET",
    "get": "GET",
    "import": "POST",
    "import_fmf": "POST",
    "list": "GET",
    "pool_summary": "GET",
    "put": "PUT",
    "resume": "POST",
    "runs": "GET",
    "snapshot": "GET",
    "start": "POST",
    "submit": "POST",
    "summary": "GET",
    "update": "PATCH",
}
ITEM_ACTIONS: frozenset[str] = frozenset(
    {
        "attributes",
        "cancel",
        "content",
        "delete",
        "export",
        "export_fmf",
        "get",
        "import",
        "pool_summary",
        "put",
        "resume",
        "runs",
        "summary",
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
        None,
        None,
    ),
    Capability(
        "drafts_export_fmf",
        "导出场景草案为 FMF 文件",
        ("GET", "/api/drafts/{draft_id}/export.fmf"),
        None,
        None,
    ),
    Capability(
        "drafts_import_fmf",
        "从 FMF 文件导入场景草案",
        ("POST", "/api/drafts/import-fmf"),
        None,
        None,
    ),
    Capability("jobs_list", "分页列出实验任务", ("GET", "/api/jobs"), ("jobs", "list"), "jobs_list"),
    Capability("jobs_get", "查看单个实验任务", ("GET", "/api/jobs/{job_id}"), ("jobs", "get"), "jobs_get"),
    Capability("jobs_create", "创建实验任务", ("POST", "/api/jobs"), ("jobs", "create"), "jobs_create"),
    Capability(
        "jobs_update",
        "更新任务状态、进度或摘要",
        ("PATCH", "/api/jobs/{job_id}"),
        ("jobs", "update"),
        "jobs_update",
    ),
    Capability(
        "jobs_cancel",
        "取消实验任务",
        ("POST", "/api/jobs/{job_id}/cancel"),
        ("jobs", "cancel"),
        "jobs_cancel",
    ),
    Capability(
        "jobs_delete",
        "删除实验任务及其逐场记录",
        ("DELETE", "/api/jobs/{job_id}"),
        ("jobs", "delete"),
        "jobs_delete",
    ),
    Capability(
        "jobs_batch_actions",
        "批量取消或删除实验任务",
        ("POST", "/api/jobs/actions"),
        None,
        None,
    ),
    Capability(
        "jobs_batch_delete",
        "批量删除实验任务",
        ("DELETE", "/api/jobs"),
        None,
        None,
    ),
    Capability(
        "jobs_runs",
        "分页查看任务逐场记录",
        ("GET", "/api/jobs/{job_id}/runs"),
        ("jobs", "runs"),
        "jobs_runs",
    ),
    Capability(
        "jobs_summary",
        "查看任务结果汇总",
        ("GET", "/api/jobs/{job_id}/summary"),
        ("jobs", "summary"),
        None,
    ),
    Capability(
        "jobs_export",
        "导出任务结果 CSV",
        ("GET", "/api/jobs/{job_id}/export.csv"),
        None,
        None,
    ),
    Capability(
        "jobs_pool_summary",
        "查看任务客队战术池汇总",
        ("GET", "/api/jobs/{job_id}/pool-summary"),
        None,
        None,
    ),
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
        "导入存档联赛与俱乐部数据",
        ("POST", "/api/saves/{save_id}/import"),
        ("saves", "import"),
        "saves_import",
    ),
    Capability("artifacts_list", "分页列出产物", ("GET", "/api/artifacts"), None, None),
    Capability(
        "artifacts_get",
        "查看单个产物",
        ("GET", "/api/artifacts/{artifact_id}"),
        None,
        None,
    ),
    Capability(
        "artifacts_content",
        "下载产物文件内容",
        ("GET", "/api/artifacts/{artifact_id}/content"),
        None,
        None,
    ),
    Capability("artifacts_create", "登记产物", ("POST", "/api/artifacts"), None, None),
    Capability(
        "artifacts_delete",
        "删除产物",
        ("DELETE", "/api/artifacts/{artifact_id}"),
        None,
        None,
    ),
    Capability("settings_list", "列出设置项", ("GET", "/api/settings"), None, None),
    Capability("settings_get", "查看单个设置项", ("GET", "/api/settings/{key}"), None, None),
    Capability("settings_put", "写入设置项", ("PUT", "/api/settings/{key}"), None, None),
    Capability(
        "settings_delete",
        "删除设置项",
        ("DELETE", "/api/settings/{key}"),
        None,
        None,
    ),
    Capability(
        "concurrency_check",
        "并发资源预检",
        ("GET", "/api/concurrency/check"),
        None,
        None,
    ),
    Capability("experiments_submit", "提交实验批次", ("POST", "/api/experiments"), None, None),
    Capability(
        "experiments_start",
        "启动下一个待运行实验",
        ("POST", "/api/experiments/start"),
        None,
        None,
    ),
    Capability(
        "experiments_cancel",
        "取消实验任务",
        ("POST", "/api/experiments/{job_id}/cancel"),
        None,
        None,
    ),
    Capability(
        "experiments_resume",
        "恢复实验任务",
        ("POST", "/api/experiments/{job_id}/resume"),
        None,
        None,
    ),
    Capability("catalog_snapshot", "读取运行时目录快照", ("GET", "/api/catalog"), None, None),
)


def capability(name: str) -> Capability:
    for item in CAPABILITIES:
        if item.name == name:
            return item
    raise KeyError(f"未知能力：{name}")


def capability_names() -> tuple[str, ...]:
    return tuple(item.name for item in CAPABILITIES)


def duplicates(capabilities: Sequence[Capability] = CAPABILITIES) -> list[str]:
    problems: list[str] = []
    surfaces: tuple[tuple[str, Iterable[str]], ...] = (
        ("能力名称", (item.name for item in capabilities)),
        ("HTTP 入口", (f"{item.http[0]} {item.http[1]}" for item in capabilities)),
        ("CLI 命令", (" ".join(item.cli) for item in capabilities if item.cli is not None)),
        ("MCP 工具", (item.mcp for item in capabilities if item.mcp is not None)),
    )
    for label, values in surfaces:
        seen: set[str] = set()
        for value in values:
            if value in seen:
                problems.append(f"{label}重复：{value}")
            seen.add(value)
    return problems


def detect_drift(
    capabilities: Sequence[Capability] = CAPABILITIES,
    *,
    openapi_operations: Collection[tuple[str, str]] | None = None,
    cli_commands: Collection[tuple[str, ...]] | None = None,
    mcp_tools: Collection[str] | None = None,
) -> list[str]:
    problems = _definition_problems(capabilities)
    problems.extend(duplicates(capabilities))
    if openapi_operations is not None:
        problems.extend(_openapi_problems(capabilities, openapi_operations))
    if cli_commands is not None:
        problems.extend(_cli_problems(capabilities, cli_commands))
    if mcp_tools is not None:
        problems.extend(_mcp_problems(capabilities, mcp_tools))
    return problems


def _definition_problems(capabilities: Sequence[Capability]) -> list[str]:
    problems: list[str] = []
    for item in capabilities:
        if not item.name:
            problems.append("能力名称不能为空")
            continue
        group, separator, action = item.name.partition("_")
        if not separator or not group or not action:
            problems.append(f"能力名称缺少分组或动作：{item.name}")
            continue
        if not item.description.strip():
            problems.append(f"能力 {item.name} 缺少描述")
        route = CAPABILITY_GROUPS.get(group)
        if route is None:
            problems.append(f"能力 {item.name} 的分组未知：{group}")
            continue
        prefix, parameter = route
        method, path = item.http
        if method not in HTTP_METHODS:
            problems.append(f"能力 {item.name} 的 HTTP 方法无效：{method}")
        expected_method = ACTION_METHODS.get(action)
        if expected_method is None:
            problems.append(f"能力 {item.name} 的动作未知：{action}")
        elif method != expected_method:
            problems.append(f"能力 {item.name} 的 HTTP 方法应为 {expected_method}，实际为 {method}")
        if path != prefix and not path.startswith(prefix + "/"):
            problems.append(f"能力 {item.name} 的路径应以 {prefix} 开头：{path}")
        parameters = _PATH_PARAMETER.findall(path)
        if action in ITEM_ACTIONS:
            if parameter is None:
                problems.append(f"能力 {item.name} 的分组不支持单条路径：{group}")
            elif parameters != [parameter]:
                problems.append(f"能力 {item.name} 的路径参数应为 {parameter}：{path}")
        elif parameters:
            problems.append(f"能力 {item.name} 的集合路径不应包含路径参数：{path}")
        if item.cli is not None and (not item.cli or any(not part for part in item.cli)):
            problems.append(f"能力 {item.name} 的 CLI 命令无效")
        if item.mcp is not None and not item.mcp.strip():
            problems.append(f"能力 {item.name} 的 MCP 工具名为空")
    return problems


def _openapi_problems(
    capabilities: Sequence[Capability],
    operations: Collection[tuple[str, str]],
) -> list[str]:
    problems: list[str] = []
    declared = {(method.upper(), path) for method, path in operations}
    registered = {item.http for item in capabilities}
    for item in capabilities:
        if item.http not in declared:
            method, path = item.http
            problems.append(f"能力 {item.name} 的 HTTP 入口缺失：{method} {path}")
    for method, path in sorted(declared):
        if path in SYSTEM_PATHS or (method, path) in registered:
            continue
        problems.append(f"OpenAPI 操作未注册能力：{method} {path}")
    return problems


def _cli_problems(
    capabilities: Sequence[Capability],
    commands: Collection[tuple[str, ...]],
) -> list[str]:
    problems: list[str] = []
    declared = {tuple(command) for command in commands}
    registered = {item.cli for item in capabilities if item.cli is not None}
    for item in capabilities:
        if item.cli is not None and item.cli not in declared:
            problems.append(f"能力 {item.name} 的 CLI 命令缺失：{' '.join(item.cli)}")
    for command in sorted(declared):
        if command in SYSTEM_CLI_COMMANDS or command in registered:
            continue
        problems.append(f"CLI 命令未注册能力：{' '.join(command)}")
    return problems


def _mcp_problems(capabilities: Sequence[Capability], tools: Collection[str]) -> list[str]:
    problems: list[str] = []
    declared = set(tools)
    registered = {item.mcp for item in capabilities if item.mcp is not None}
    for item in capabilities:
        if item.mcp is not None and item.mcp not in declared:
            problems.append(f"能力 {item.name} 的 MCP 工具缺失：{item.mcp}")
    for name in sorted(declared - registered):
        problems.append(f"MCP 工具未注册能力：{name}")
    return problems
