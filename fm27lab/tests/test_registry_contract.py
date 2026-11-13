from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from typer.main import get_command

from fm27lab.cli import app as cli_app
from fm27lab.interfaces.mcp.tools import build_tools, tool_names
from fm27lab.registry import (
    ACTION_METHODS,
    CAPABILITIES,
    CAPABILITY_GROUPS,
    ITEM_ACTIONS,
    SYSTEM_CLI_COMMANDS,
    SYSTEM_PATHS,
    capability,
    capability_names,
    detect_drift,
    duplicates,
)
from fm27lab.tests.test_http_health import make_app

PATH_PARAMETER = re.compile(r"{(\w+)}")
EXPECTED_NAMES = frozenset(
    {
        "pools_list",
        "pools_get",
        "pools_create",
        "pools_delete",
        "drafts_list",
        "drafts_get",
        "drafts_create",
        "drafts_update",
        "drafts_delete",
        "drafts_attributes",
        "drafts_export_fmf",
        "drafts_import_fmf",
        "drafts_apply_roster",
        "drafts_undo_roster",
        "jobs_list",
        "jobs_get",
        "jobs_create",
        "jobs_update",
        "jobs_cancel",
        "jobs_delete",
        "jobs_batch_actions",
        "jobs_batch_delete",
        "jobs_runs",
        "jobs_summary",
        "jobs_export",
        "jobs_pool_summary",
        "saves_list",
        "saves_get",
        "saves_create",
        "saves_update",
        "saves_delete",
        "saves_import",
        "saves_squad",
        "saves_import_payload",
        "artifacts_list",
        "artifacts_get",
        "artifacts_content",
        "artifacts_create",
        "artifacts_delete",
        "settings_list",
        "settings_get",
        "settings_put",
        "settings_delete",
        "concurrency_check",
        "experiments_submit",
        "experiments_start",
        "experiments_cancel",
        "experiments_resume",
        "catalog_snapshot",
        "results_compare",
        "system_resources",
    }
)

EXTENDED_SURFACES: dict[str, tuple[tuple[str, ...], str]] = {
    "drafts_attributes": (("drafts", "attributes"), "drafts_attributes"),
    "drafts_export_fmf": (("drafts", "export-fmf"), "drafts_export_fmf"),
    "drafts_import_fmf": (("drafts", "import-fmf"), "drafts_import_fmf"),
    "drafts_apply_roster": (("drafts", "apply-roster"), "drafts_apply_roster"),
    "drafts_undo_roster": (("drafts", "undo-roster"), "drafts_undo_roster"),
    "jobs_batch_actions": (("jobs", "batch-action"), "jobs_batch_actions"),
    "jobs_batch_delete": (("jobs", "batch-delete"), "jobs_batch_delete"),
    "jobs_export": (("jobs", "export"), "jobs_export"),
    "jobs_pool_summary": (("jobs", "pool-summary"), "jobs_pool_summary"),
    "saves_import": (("saves", "import-file"), "saves_import_file"),
    "saves_squad": (("saves", "squad"), "saves_squad"),
    "artifacts_list": (("artifacts", "list"), "artifacts_list"),
    "artifacts_get": (("artifacts", "get"), "artifacts_get"),
    "artifacts_content": (("artifacts", "content"), "artifacts_content"),
    "artifacts_create": (("artifacts", "create"), "artifacts_create"),
    "artifacts_delete": (("artifacts", "delete"), "artifacts_delete"),
    "settings_list": (("settings", "list"), "settings_list"),
    "settings_get": (("settings", "get"), "settings_get"),
    "settings_put": (("settings", "put"), "settings_put"),
    "settings_delete": (("settings", "delete"), "settings_delete"),
    "concurrency_check": (("concurrency", "check"), "concurrency_check"),
    "experiments_submit": (("experiments", "submit"), "experiments_submit"),
    "experiments_start": (("experiments", "start"), "experiments_start"),
    "experiments_cancel": (("experiments", "cancel"), "experiments_cancel"),
    "experiments_resume": (("experiments", "resume"), "experiments_resume"),
    "catalog_snapshot": (("catalog", "show"), "catalog_snapshot"),
    "results_compare": (("results", "compare"), "results_compare"),
}


class _FakeClient:
    def request_json(self, *_args, **_kwargs):
        raise AssertionError("契约测试不得发起 HTTP 请求")


def _openapi_operations(app) -> set[tuple[str, str]]:
    return {
        (method.upper(), path) for path, operations in app.openapi()["paths"].items() for method in operations
    }


def _cli_leaves(command=None) -> list[tuple[str, ...]]:
    node = get_command(cli_app) if command is None else command
    children = getattr(node, "commands", None)
    if not children:
        return [()]
    leaves: list[tuple[str, ...]] = []
    for name, child in children.items():
        leaves.extend((name, *leaf) for leaf in _cli_leaves(child))
    return leaves


def _mcp_tools() -> set[str]:
    return {tool.name for tool in build_tools(_FakeClient())}


def test_registry_entries_are_complete_unique_and_lookupable():
    assert set(capability_names()) == EXPECTED_NAMES
    assert len(capability_names()) == len(EXPECTED_NAMES)
    assert duplicates() == []
    assert detect_drift() == []
    for item in CAPABILITIES:
        assert capability(item.name) is item
        assert item.description.strip()
        assert item.http[0] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert item.http[1].startswith("/api/")
        if item.cli is not None:
            assert item.cli and all(part for part in item.cli)
        if item.mcp is not None:
            assert item.mcp.strip()
    with pytest.raises(KeyError):
        capability("unknown_capability")


def test_openapi_business_operations_match_registry(tmp_path: Path):
    app, *_ = make_app(tmp_path)
    operations = _openapi_operations(app)
    registered = {item.http for item in CAPABILITIES}
    for item in CAPABILITIES:
        assert item.http in operations, item.name
    declared_paths = {path for _method, path in operations}
    assert declared_paths - {path for _method, path in registered} == {
        "/api/events",
        "/api/health",
        "/api/shutdown",
        "/api/version",
    }
    business = {(method, path) for method, path in operations if path not in SYSTEM_PATHS}
    assert business == registered
    assert detect_drift(CAPABILITIES, openapi_operations=operations) == []


def test_cli_leaf_commands_match_registry():
    commands = set(_cli_leaves())
    registered = {item.cli for item in CAPABILITIES if item.cli is not None}
    assert registered <= commands
    assert commands - SYSTEM_CLI_COMMANDS == registered
    assert detect_drift(CAPABILITIES, cli_commands=commands) == []


def test_mcp_tool_names_match_registry():
    tools = _mcp_tools()
    assert tools == set(tool_names())
    registered = {item.mcp for item in CAPABILITIES if item.mcp is not None}
    assert tools == registered
    assert detect_drift(CAPABILITIES, mcp_tools=tools) == []


def test_http_methods_and_paths_follow_name_contract():
    for item in CAPABILITIES:
        group, separator, action = item.name.partition("_")
        assert separator, item.name
        prefix, parameter = CAPABILITY_GROUPS[group]
        method, path = item.http
        assert method == ACTION_METHODS[action], item.name
        assert path.startswith(prefix), item.name
        parameters = PATH_PARAMETER.findall(path)
        if action in ITEM_ACTIONS:
            assert parameters == [parameter], item.name
        else:
            assert parameters == [], item.name


def test_duplicates_detects_name_http_cli_and_mcp_collisions():
    first = capability("pools_list")
    variants = {
        "能力名称": replace(first, http=("PUT", "/api/pools/dup"), cli=("pools", "dup"), mcp="pools_dup"),
        "HTTP 入口": replace(first, name="pools_http", cli=("pools", "http"), mcp="pools_http"),
        "CLI 命令": replace(first, name="pools_cli", http=("PUT", "/api/pools/cli"), mcp="pools_cli"),
        "MCP 工具": replace(first, name="pools_mcp", http=("PUT", "/api/pools/mcp"), cli=("pools", "mcp")),
    }
    for label, variant in variants.items():
        problems = duplicates((first, variant))
        assert problems, label
        assert any(label in problem for problem in problems), label
    assert duplicates((first,)) == []


def test_detect_drift_reports_missing_capability_and_wrong_path(tmp_path: Path):
    app, *_ = make_app(tmp_path)
    openapi_operations = _openapi_operations(app)
    cli_commands = set(_cli_leaves())
    mcp_tools = _mcp_tools()
    assert (
        detect_drift(
            CAPABILITIES,
            openapi_operations=openapi_operations,
            cli_commands=cli_commands,
            mcp_tools=mcp_tools,
        )
        == []
    )

    missing = tuple(item for item in CAPABILITIES if item.name != "pools_list")
    missing_problems = detect_drift(
        missing,
        openapi_operations=openapi_operations,
        cli_commands=cli_commands,
        mcp_tools=mcp_tools,
    )
    assert missing_problems
    assert any("GET /api/pools" in problem for problem in missing_problems)

    wrong_path = tuple(
        replace(item, http=("GET", "/api/jobs/{job_id}/nope")) if item.name == "jobs_summary" else item
        for item in CAPABILITIES
    )
    path_problems = detect_drift(wrong_path, openapi_operations=openapi_operations)
    assert path_problems
    assert any("/api/jobs/{job_id}/nope" in problem for problem in path_problems)

    wrong_method = tuple(
        replace(item, http=("POST", "/api/jobs/{job_id}")) if item.name == "jobs_get" else item
        for item in CAPABILITIES
    )
    assert detect_drift(wrong_method)


def test_extended_capabilities_declare_mapped_cli_and_mcp_surfaces():
    assert set(EXTENDED_SURFACES) <= set(capability_names())
    for name, (cli_command, tool) in EXTENDED_SURFACES.items():
        item = capability(name)
        assert item.cli == cli_command, name
        assert item.mcp == tool, name


def test_every_capability_declares_cli_surface():
    assert [item.name for item in CAPABILITIES if item.cli is None] == []


def test_system_resources_serves_http_and_cli_without_mcp(tmp_path: Path):
    assert len(CAPABILITIES) == 51
    item = capability("system_resources")
    assert item.description.strip()
    assert item.http == ("GET", "/api/system/resources")
    assert item.cli == ("system", "resources")
    assert item.mcp is None
    app, *_ = make_app(tmp_path)
    assert item.http in _openapi_operations(app)
    assert item.cli in set(_cli_leaves())
    assert detect_drift(CAPABILITIES) == []


def test_saves_payload_import_keeps_existing_surfaces():
    payload_import = capability("saves_import_payload")
    assert payload_import.http == ("POST", "/api/saves/{save_id}/import")
    assert payload_import.cli == ("saves", "import")
    assert payload_import.mcp == "saves_import"
    file_import = capability("saves_import")
    assert file_import.http == ("POST", "/api/saves/import")
    assert file_import.cli == ("saves", "import-file")
    assert file_import.mcp == "saves_import_file"
