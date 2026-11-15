"""能力注册表：HTTP、CLI 与 MCP 三入口的单一事实来源。"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence

from fm27lab.registry.model import (
    _PATH_PARAMETER,
    ACTION_METHODS,
    CAPABILITY_GROUPS,
    HTTP_METHODS,
    ITEM_ACTIONS,
    SYSTEM_CLI_COMMANDS,
    SYSTEM_PATHS,
    Capability,
)
from fm27lab.registry.parts import (
    artifacts,
    catalog,
    concurrency,
    drafts,
    experiments,
    formations,
    jobs,
    pools,
    results,
    saves,
    setpieces,
    settings,
    system,
)

CAPABILITIES: tuple[Capability, ...] = (
    *pools.CAPABILITIES,
    *drafts.CAPABILITIES,
    *jobs.CAPABILITIES,
    *saves.CAPABILITIES,
    *setpieces.CAPABILITIES,
    *artifacts.CAPABILITIES,
    *settings.CAPABILITIES,
    *concurrency.CAPABILITIES,
    *experiments.CAPABILITIES,
    *formations.CAPABILITIES,
    *catalog.CAPABILITIES,
    *results.CAPABILITIES,
    *system.CAPABILITIES,
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
