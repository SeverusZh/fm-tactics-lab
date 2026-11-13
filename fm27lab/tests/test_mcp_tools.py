from __future__ import annotations

import base64
import json
import re

import pytest

from fm27lab.client import SidecarError
from fm27lab.interfaces.mcp.protocol import McpServer
from fm27lab.interfaces.mcp.tools import build_tools, tool_names

CJK = re.compile(r"[\u4e00-\u9fff]")
MAX_OFFSET = 2**31 - 1

EXPECTED_TOOL_NAMES = (
    "pools_list",
    "pools_get",
    "pools_create",
    "pools_delete",
    "drafts_list",
    "drafts_get",
    "drafts_create",
    "drafts_update",
    "drafts_delete",
    "jobs_list",
    "jobs_get",
    "jobs_create",
    "jobs_update",
    "jobs_cancel",
    "jobs_delete",
    "jobs_runs",
    "saves_list",
    "saves_get",
    "saves_create",
    "saves_update",
    "saves_delete",
    "saves_import",
    "drafts_attributes",
    "drafts_export_fmf",
    "drafts_import_fmf",
    "drafts_apply_roster",
    "drafts_undo_roster",
    "jobs_batch_actions",
    "jobs_batch_delete",
    "jobs_export",
    "jobs_pool_summary",
    "saves_import_file",
    "saves_squad",
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
)

PAGINATION_SCHEMAS = {
    "pools_list": (128, 128),
    "drafts_list": (128, 128),
    "jobs_list": (256, 50),
    "jobs_runs": (200, 50),
    "saves_list": (256, 50),
    "artifacts_list": (256, 50),
}

REQUEST_CASES = (
    (
        "pools_list",
        {"limit": 10, "offset": 20},
        "GET",
        "/api/pools",
        {"limit": 10, "offset": 20},
        None,
    ),
    ("pools_get", {"entry_id": "pool-1"}, "GET", "/api/pools/pool-1", None, None),
    (
        "pools_create",
        {
            "name": "主战术",
            "weight": 3,
            "tactic": {"formation": "4-4-2"},
            "roster": {"players": []},
            "id": "pool-2",
        },
        "POST",
        "/api/pools",
        None,
        {
            "name": "主战术",
            "weight": 3,
            "tactic": {"formation": "4-4-2"},
            "roster": {"players": []},
            "id": "pool-2",
        },
    ),
    ("pools_delete", {"entry_id": "pool-1"}, "DELETE", "/api/pools/pool-1", None, None),
    ("drafts_list", {"limit": 128}, "GET", "/api/drafts", {"limit": 128}, None),
    ("drafts_get", {"draft_id": "draft-1"}, "GET", "/api/drafts/draft-1", None, None),
    (
        "drafts_create",
        {"name": "草案", "scenario": {"teams": []}, "source": {"kind": "default"}},
        "POST",
        "/api/drafts",
        None,
        {"name": "草案", "scenario": {"teams": []}, "source": {"kind": "default"}},
    ),
    (
        "drafts_update",
        {"draft_id": "draft-1", "name": "改名", "scenario": {"teams": []}},
        "PATCH",
        "/api/drafts/draft-1",
        None,
        {"name": "改名", "scenario": {"teams": []}},
    ),
    ("drafts_delete", {"draft_id": "draft-1"}, "DELETE", "/api/drafts/draft-1", None, None),
    (
        "jobs_list",
        {"status": "running", "limit": 5, "offset": 0},
        "GET",
        "/api/jobs",
        {"status": "running", "limit": 5, "offset": 0},
        None,
    ),
    ("jobs_get", {"job_id": "job-1"}, "GET", "/api/jobs/job-1", None, None),
    (
        "jobs_create",
        {"kind": "match", "name": "批次", "config": {"seeds": [1, 2]}, "workers": 4, "total": 10},
        "POST",
        "/api/jobs",
        None,
        {"kind": "match", "name": "批次", "config": {"seeds": [1, 2]}, "workers": 4, "total": 10},
    ),
    (
        "jobs_update",
        {
            "job_id": "job-1",
            "status": "cancelled",
            "completed": 3,
            "summary": {"wins": 1},
            "name": "新名",
        },
        "PATCH",
        "/api/jobs/job-1",
        None,
        {"status": "cancelled", "completed": 3, "summary": {"wins": 1}, "name": "新名"},
    ),
    ("jobs_cancel", {"job_id": "job-1"}, "POST", "/api/jobs/job-1/cancel", None, None),
    ("jobs_delete", {"job_id": "job-1"}, "DELETE", "/api/jobs/job-1", None, None),
    (
        "jobs_runs",
        {"job_id": "job-1", "limit": 50, "offset": 10},
        "GET",
        "/api/jobs/job-1/runs",
        {"limit": 50, "offset": 10},
        None,
    ),
    (
        "saves_list",
        {"status": "ready", "limit": 50, "offset": 0},
        "GET",
        "/api/saves",
        {"status": "ready", "limit": 50, "offset": 0},
        None,
    ),
    ("saves_get", {"save_id": "save-1"}, "GET", "/api/saves/save-1", None, None),
    (
        "saves_create",
        {
            "source_path": "/tmp/save.fm",
            "source_sha256": "a" * 64,
            "status": "pending",
            "stage": "reading",
            "metadata": {"club": "x"},
        },
        "POST",
        "/api/saves",
        None,
        {
            "source_path": "/tmp/save.fm",
            "source_sha256": "a" * 64,
            "status": "pending",
            "stage": "reading",
            "metadata": {"club": "x"},
        },
    ),
    (
        "saves_update",
        {"save_id": "save-1", "status": "reading", "stage": "done", "metadata": {"a": 1}},
        "PATCH",
        "/api/saves/save-1",
        None,
        {"status": "reading", "stage": "done", "metadata": {"a": 1}},
    ),
    ("saves_delete", {"save_id": "save-1"}, "DELETE", "/api/saves/save-1", None, None),
    (
        "saves_import",
        {
            "save_id": "save-1",
            "leagues": {"premier": {"name": "英超"}},
            "clubs": {"100": {"name": "甲队"}},
            "stage": "ready",
        },
        "POST",
        "/api/saves/save-1/import",
        None,
        {"leagues": {"premier": {"name": "英超"}}, "clubs": {"100": {"name": "甲队"}}, "stage": "ready"},
    ),
    (
        "drafts_attributes",
        {
            "draft_id": "draft-1",
            "side": "home",
            "scope": "player",
            "player_index": 3,
            "operation": "bulk",
            "params": {"value": 12},
        },
        "POST",
        "/api/drafts/draft-1/attributes",
        None,
        {"side": "home", "scope": "player", "player_index": 3, "operation": "bulk", "params": {"value": 12}},
    ),
    (
        "drafts_import_fmf",
        {"name": "导入草案", "content_base64": "Zm1m", "source": {"kind": "fmf"}},
        "POST",
        "/api/drafts/import-fmf",
        None,
        {"name": "导入草案", "content_base64": "Zm1m", "source": {"kind": "fmf"}},
    ),
    (
        "drafts_apply_roster",
        {"draft_id": "draft-1", "save_id": "save-1", "club_uid": 42, "side": "away", "scope": "both"},
        "POST",
        "/api/drafts/draft-1/apply-roster",
        None,
        {"save_id": "save-1", "club_uid": 42, "side": "away", "scope": "both"},
    ),
    ("drafts_undo_roster", {"draft_id": "draft-1"}, "POST", "/api/drafts/draft-1/undo-roster", None, None),
    (
        "jobs_batch_actions",
        {"action": "cancel", "ids": ["job-1", "job-2"]},
        "POST",
        "/api/jobs/actions",
        None,
        {"action": "cancel", "ids": ["job-1", "job-2"]},
    ),
    ("jobs_batch_delete", {"ids": ["job-1"]}, "DELETE", "/api/jobs", None, {"ids": ["job-1"]}),
    ("jobs_pool_summary", {"job_id": "job-1"}, "GET", "/api/jobs/job-1/pool-summary", None, None),
    (
        "saves_import_file",
        {"source_path": "/tmp/career.fm", "replace": True},
        "POST",
        "/api/saves/import",
        None,
        {"source_path": "/tmp/career.fm", "replace": True},
    ),
    (
        "saves_squad",
        {"save_id": "save-1", "club_uid": 7},
        "GET",
        "/api/saves/save-1/squad",
        {"club_uid": 7},
        None,
    ),
    (
        "artifacts_list",
        {"kind": "report", "job_id": "job-1", "limit": 10, "offset": 5},
        "GET",
        "/api/artifacts",
        {"kind": "report", "job_id": "job-1", "limit": 10, "offset": 5},
        None,
    ),
    ("artifacts_get", {"artifact_id": "art-1"}, "GET", "/api/artifacts/art-1", None, None),
    (
        "artifacts_create",
        {"kind": "report", "filename": "a.csv", "content_base64": "YQ==", "job_id": "job-1"},
        "POST",
        "/api/artifacts",
        None,
        {"kind": "report", "filename": "a.csv", "content_base64": "YQ==", "job_id": "job-1"},
    ),
    ("artifacts_delete", {"artifact_id": "art-1"}, "DELETE", "/api/artifacts/art-1", None, None),
    ("settings_list", {}, "GET", "/api/settings", None, None),
    ("settings_get", {"key": "ui.theme"}, "GET", "/api/settings/ui.theme", None, None),
    (
        "settings_put",
        {"key": "ui.theme", "value": {"mode": "dark"}, "note": "主题"},
        "PUT",
        "/api/settings/ui.theme",
        None,
        {"value": {"mode": "dark"}, "note": "主题"},
    ),
    ("settings_delete", {"key": "ui.theme"}, "DELETE", "/api/settings/ui.theme", None, None),
    (
        "concurrency_check",
        {
            "workers": 8,
            "cpu_count": 16,
            "available_memory_bytes": 17179869184,
            "free_disk_bytes": 107374182400,
            "allow_oversubscription": False,
        },
        "GET",
        "/api/concurrency/check",
        {
            "workers": 8,
            "cpu_count": 16,
            "available_memory_bytes": 17179869184,
            "free_disk_bytes": 107374182400,
            "allow_oversubscription": False,
        },
        None,
    ),
    (
        "experiments_submit",
        {
            "name": "实验批次",
            "seeds": [1, 2],
            "variants": ["A", "B"],
            "workers": 4,
            "cpu_count": 8,
            "available_memory_bytes": 8589934592,
            "free_disk_bytes": 10737418240,
            "allow_oversubscription": True,
        },
        "POST",
        "/api/experiments",
        None,
        {
            "name": "实验批次",
            "seeds": [1, 2],
            "variants": ["A", "B"],
            "workers": 4,
            "cpu_count": 8,
            "available_memory_bytes": 8589934592,
            "free_disk_bytes": 10737418240,
            "allow_oversubscription": True,
        },
    ),
    ("experiments_start", {}, "POST", "/api/experiments/start", None, None),
    ("experiments_cancel", {"job_id": "job-1"}, "POST", "/api/experiments/job-1/cancel", None, None),
    ("experiments_resume", {"job_id": "job-1"}, "POST", "/api/experiments/job-1/resume", None, None),
    ("catalog_snapshot", {}, "GET", "/api/catalog", None, None),
)

INVALID_CASES = (
    ("pools_get", {}, "缺少必填参数：entry_id"),
    ("pools_get", {"entry_id": 3}, "参数 entry_id 类型必须是字符串"),
    ("pools_get", {"entry_id": ""}, "参数 entry_id 长度不能小于 1"),
    ("pools_list", {"limit": 0}, "参数 limit 不能小于 1"),
    ("pools_list", {"limit": 129}, "参数 limit 不能大于 128"),
    ("pools_list", {"limit": True}, "参数 limit 类型必须是整数"),
    ("pools_list", {"limit": 2.5}, "参数 limit 类型必须是整数"),
    ("pools_list", {"offset": -1}, "参数 offset 不能小于 0"),
    ("pools_list", {"offset": 2**31}, "参数 offset 不能大于 2147483647"),
    ("pools_list", {"bogus": 1}, "未知参数：bogus"),
    ("pools_create", {"name": "x"}, "缺少必填参数：tactic"),
    ("pools_create", {"name": "", "tactic": {}}, "参数 name 长度不能小于 1"),
    ("pools_create", {"name": "x", "tactic": []}, "参数 tactic 类型必须是对象"),
    ("pools_create", {"name": "x", "tactic": {}, "weight": 1001}, "参数 weight 不能大于 1000"),
    ("pools_create", {"name": "x", "tactic": {}, "id": "bad id"}, "参数 id 格式无效"),
    ("drafts_update", {"draft_id": "draft-1"}, "至少需要提供一项更新字段"),
    ("jobs_update", {"job_id": "job-1"}, "至少需要提供一项更新字段"),
    ("saves_update", {"save_id": "save-1"}, "至少需要提供一项更新字段"),
    ("jobs_create", {"kind": ""}, "参数 kind 长度不能小于 1"),
    ("jobs_create", {"kind": "match", "workers": 0}, "参数 workers 不能小于 1"),
    ("jobs_create", {"kind": "match", "workers": 257}, "参数 workers 不能大于 256"),
    ("jobs_create", {"kind": "match", "total": -1}, "参数 total 不能小于 0"),
    ("jobs_update", {"job_id": "job-1", "completed": -1}, "参数 completed 不能小于 0"),
    ("jobs_update", {"job_id": "job-1", "status": 5}, "参数 status 类型必须是字符串"),
    (
        "saves_import",
        {"save_id": "save-1", "leagues": [], "clubs": {}},
        "参数 leagues 类型必须是对象",
    ),
    (
        "saves_import",
        {"save_id": "save-1", "leagues": {"a": 1}, "clubs": {}},
        "参数 leagues.a 类型必须是对象",
    ),
    ("saves_import", {"save_id": "save-1", "leagues": {}}, "缺少必填参数：clubs"),
    ("saves_create", {"source_path": "/a"}, "缺少必填参数：source_sha256"),
    ("saves_create", {"source_path": 1, "source_sha256": "x"}, "参数 source_path 类型必须是字符串"),
    ("jobs_runs", {"job_id": "job-1", "limit": 201}, "参数 limit 不能大于 200"),
    ("drafts_attributes", {"draft_id": "draft-1"}, "缺少必填参数：side"),
    (
        "drafts_attributes",
        {"draft_id": "draft-1", "side": "home", "scope": "all", "operation": "undo", "params": []},
        "参数 params 类型必须是对象",
    ),
    (
        "drafts_attributes",
        {
            "draft_id": "draft-1",
            "side": "home",
            "scope": "player",
            "player_index": -1,
            "operation": "bulk",
            "params": {},
        },
        "参数 player_index 不能小于 0",
    ),
    ("drafts_export_fmf", {}, "缺少必填参数：draft_id"),
    ("drafts_import_fmf", {"name": "导入"}, "缺少必填参数：content_base64"),
    ("drafts_import_fmf", {"name": "", "content_base64": "Zm1m"}, "参数 name 长度不能小于 1"),
    (
        "drafts_apply_roster",
        {"draft_id": "draft-1", "save_id": "save-1", "club_uid": 0, "side": "home", "scope": "both"},
        "参数 club_uid 不能小于 1",
    ),
    (
        "drafts_apply_roster",
        {"draft_id": "draft-1", "save_id": "save-1", "club_uid": 1, "side": "home"},
        "缺少必填参数：scope",
    ),
    ("drafts_undo_roster", {}, "缺少必填参数：draft_id"),
    ("jobs_batch_actions", {"ids": ["job-1"]}, "缺少必填参数：action"),
    ("jobs_batch_actions", {"action": "purge", "ids": ["job-1"]}, "参数 action 不在允许范围内"),
    ("jobs_batch_actions", {"action": "cancel", "ids": []}, "参数 ids 至少需要 1 项"),
    ("jobs_batch_actions", {"action": "cancel", "ids": ["job-1", "job-1"]}, "参数 ids 不能包含重复项"),
    ("jobs_batch_actions", {"action": "cancel", "ids": ["bad id"]}, "参数 ids[0] 格式无效"),
    ("jobs_batch_delete", {"ids": "job-1"}, "参数 ids 类型必须是数组"),
    ("jobs_batch_delete", {"ids": [str(index) for index in range(257)]}, "参数 ids 不能超过 256 项"),
    ("jobs_export", {}, "缺少必填参数：job_id"),
    ("jobs_pool_summary", {}, "缺少必填参数：job_id"),
    ("saves_import_file", {}, "缺少必填参数：source_path"),
    ("saves_import_file", {"source_path": "/tmp/a.fm", "replace": "yes"}, "参数 replace 类型必须是布尔值"),
    ("saves_squad", {"save_id": "save-1"}, "缺少必填参数：club_uid"),
    ("saves_squad", {"save_id": "save-1", "club_uid": 0}, "参数 club_uid 不能小于 1"),
    ("artifacts_list", {"limit": 257}, "参数 limit 不能大于 256"),
    ("artifacts_list", {"offset": -1}, "参数 offset 不能小于 0"),
    ("artifacts_create", {"kind": "report", "content_base64": "YQ=="}, "缺少必填参数：filename"),
    (
        "artifacts_create",
        {"kind": "report", "filename": "a.csv", "content_base64": "YQ==", "job_id": 5},
        "参数 job_id 类型必须是字符串",
    ),
    ("artifacts_content", {}, "缺少必填参数：artifact_id"),
    ("settings_get", {"key": ""}, "参数 key 长度不能小于 1"),
    ("settings_put", {"key": "ui.theme"}, "缺少必填参数：value"),
    ("settings_put", {"key": "ui.theme", "value": {"mode": "dark"}, "note": 3}, "参数 note 类型必须是字符串"),
    ("settings_list", {"limit": 1}, "未知参数：limit"),
    (
        "concurrency_check",
        {
            "workers": 0,
            "cpu_count": 8,
            "available_memory_bytes": 0,
            "free_disk_bytes": 0,
            "allow_oversubscription": False,
        },
        "参数 workers 不能小于 1",
    ),
    (
        "concurrency_check",
        {"workers": 8, "cpu_count": 8, "available_memory_bytes": 0, "free_disk_bytes": 0},
        "缺少必填参数：allow_oversubscription",
    ),
    (
        "concurrency_check",
        {
            "workers": 8,
            "cpu_count": 8,
            "available_memory_bytes": 0,
            "free_disk_bytes": 0,
            "allow_oversubscription": "false",
        },
        "参数 allow_oversubscription 类型必须是布尔值",
    ),
    (
        "experiments_submit",
        {
            "seeds": [],
            "variants": ["A"],
            "workers": 1,
            "cpu_count": 1,
            "available_memory_bytes": 0,
            "free_disk_bytes": 0,
        },
        "参数 seeds 至少需要 1 项",
    ),
    (
        "experiments_submit",
        {"seeds": [1], "variants": ["A"], "workers": 1, "cpu_count": 1, "available_memory_bytes": 0},
        "缺少必填参数：free_disk_bytes",
    ),
    (
        "experiments_submit",
        {
            "seeds": [1],
            "variants": ["A"],
            "workers": 257,
            "cpu_count": 1,
            "available_memory_bytes": 0,
            "free_disk_bytes": 0,
        },
        "参数 workers 不能大于 256",
    ),
    (
        "experiments_submit",
        {
            "name": "",
            "seeds": [1],
            "variants": ["A"],
            "workers": 1,
            "cpu_count": 1,
            "available_memory_bytes": 0,
            "free_disk_bytes": 0,
        },
        "参数 name 长度不能小于 1",
    ),
    ("experiments_cancel", {}, "缺少必填参数：job_id"),
    ("catalog_snapshot", {"bogus": 1}, "未知参数：bogus"),
)

ENCODING_CASES = (
    ("pools_get", {"entry_id": "a/b?c#d e%"}, ["/api/pools/a%2Fb%3Fc%23d%20e%25"]),
    ("jobs_runs", {"job_id": "任务/一"}, ["/api/jobs/%E4%BB%BB%E5%8A%A1%2F%E4%B8%80/runs"]),
    ("saves_import", {"save_id": "x/y", "leagues": {}, "clubs": {}}, ["/api/saves/x%2Fy/import"]),
    (
        "drafts_attributes",
        {"draft_id": "a/b", "side": "home", "scope": "all", "operation": "undo", "params": {}},
        ["/api/drafts/a%2Fb/attributes"],
    ),
    (
        "drafts_apply_roster",
        {"draft_id": "d/1", "save_id": "save-1", "club_uid": 2, "side": "home", "scope": "both"},
        ["/api/drafts/d%2F1/apply-roster"],
    ),
    ("drafts_export_fmf", {"draft_id": "x y"}, ["/api/drafts/x%20y/export.fmf"]),
    ("artifacts_get", {"artifact_id": "art/一"}, ["/api/artifacts/art%2F%E4%B8%80"]),
    ("artifacts_content", {"artifact_id": "art/1"}, ["/api/artifacts/art%2F1/content"]),
    ("settings_get", {"key": "a/b"}, ["/api/settings/a%2Fb"]),
    ("settings_put", {"key": "a/b", "value": 1}, ["/api/settings/a%2Fb"]),
    ("saves_squad", {"save_id": "s/1", "club_uid": 2}, ["/api/saves/s%2F1/squad"]),
    ("jobs_export", {"job_id": "j/1"}, ["/api/jobs/j%2F1/export.csv"]),
    ("jobs_pool_summary", {"job_id": "j/1"}, ["/api/jobs/j%2F1/pool-summary"]),
    ("experiments_cancel", {"job_id": "j/1"}, ["/api/experiments/j%2F1/cancel"]),
    ("experiments_resume", {"job_id": "j/1"}, ["/api/experiments/j%2F1/resume"]),
)

DOWNLOAD_CASES = (
    (
        "artifacts_content",
        {"artifact_id": "art-1"},
        "GET",
        "/api/artifacts/art-1/content",
        None,
        "application/octet-stream",
    ),
    (
        "drafts_export_fmf",
        {"draft_id": "draft-1"},
        "GET",
        "/api/drafts/draft-1/export.fmf",
        None,
        "application/octet-stream",
    ),
    (
        "jobs_export",
        {"job_id": "job-1"},
        "GET",
        "/api/jobs/job-1/export.csv",
        None,
        "text/csv; charset=utf-8",
    ),
)

NEW_ERROR_CASES = (
    ("settings_get", {"key": "ui.theme"}),
    ("artifacts_get", {"artifact_id": "art-1"}),
    ("experiments_cancel", {"job_id": "job-1"}),
    ("drafts_undo_roster", {"draft_id": "draft-1"}),
)


class RecordingClient:
    "记录请求并返回固定结果的替身客户端。"

    def __init__(self, response=None, error=None, download=b"", headers=None):
        self.response = {"ok": True} if response is None else response
        self.error = error
        self.download = download
        self.headers = {"content-type": "application/octet-stream"} if headers is None else headers
        self.calls: list[dict] = []

    def request_json(self, method, path, *, body=None, query=None):
        self.calls.append({"method": method, "path": path, "query": query, "body": body})
        if self.error is not None:
            raise self.error
        return self.response

    def request_bytes(self, method, path, *, query=None, accept="*/*"):
        self.calls.append({"method": method, "path": path, "query": query, "accept": accept})
        if self.error is not None:
            raise self.error
        return self.download, self.headers


def tools_by_name(client=None):
    client = RecordingClient() if client is None else client
    return {tool.name: tool for tool in build_tools(client)}


def handler_for(name, client):
    return tools_by_name(client)[name].handler


def assert_chinese(text):
    assert CJK.search(text), text


def test_tool_inventory_is_stable():
    assert tool_names() == EXPECTED_TOOL_NAMES
    assert len(tool_names()) == 48
    assert [tool.name for tool in build_tools(RecordingClient())] == list(EXPECTED_TOOL_NAMES)


def test_build_tools_does_not_issue_requests():
    client = RecordingClient()
    build_tools(client)
    assert client.calls == []


def test_handlers_are_bound_to_the_given_client():
    first = RecordingClient()
    second = RecordingClient()
    handler_for("pools_list", first)({})
    assert len(first.calls) == 1
    assert second.calls == []


def test_every_tool_schema_is_strict_and_chinese_described():
    for tool in build_tools(RecordingClient()):
        schema = tool.input_schema
        assert schema["type"] == "object", tool.name
        assert isinstance(schema["properties"], dict), tool.name
        assert isinstance(schema["required"], list), tool.name
        assert schema["additionalProperties"] is False, tool.name
        assert set(schema["required"]) <= set(schema["properties"]), tool.name
        for name, subschema in schema["properties"].items():
            assert isinstance(subschema, dict), (tool.name, name)
            assert "type" in subschema, (tool.name, name)
        assert tool.description, tool.name
        assert_chinese(tool.description)


def test_required_fields_match_create_contracts():
    expected = {
        "pools_get": ["entry_id"],
        "pools_delete": ["entry_id"],
        "pools_create": ["name", "tactic"],
        "drafts_get": ["draft_id"],
        "drafts_delete": ["draft_id"],
        "drafts_create": ["name", "scenario"],
        "drafts_update": ["draft_id"],
        "jobs_get": ["job_id"],
        "jobs_delete": ["job_id"],
        "jobs_cancel": ["job_id"],
        "jobs_runs": ["job_id"],
        "jobs_create": ["kind"],
        "jobs_update": ["job_id"],
        "saves_get": ["save_id"],
        "saves_delete": ["save_id"],
        "saves_create": ["source_path", "source_sha256"],
        "saves_update": ["save_id"],
        "saves_import": ["save_id", "leagues", "clubs"],
        "drafts_attributes": ["draft_id", "side", "scope", "operation", "params"],
        "drafts_export_fmf": ["draft_id"],
        "drafts_import_fmf": ["name", "content_base64"],
        "drafts_apply_roster": ["draft_id", "save_id", "club_uid", "side", "scope"],
        "drafts_undo_roster": ["draft_id"],
        "jobs_batch_actions": ["action", "ids"],
        "jobs_batch_delete": ["ids"],
        "jobs_export": ["job_id"],
        "jobs_pool_summary": ["job_id"],
        "saves_import_file": ["source_path"],
        "saves_squad": ["save_id", "club_uid"],
        "artifacts_get": ["artifact_id"],
        "artifacts_content": ["artifact_id"],
        "artifacts_create": ["kind", "filename", "content_base64"],
        "artifacts_delete": ["artifact_id"],
        "settings_get": ["key"],
        "settings_put": ["key", "value"],
        "settings_delete": ["key"],
        "concurrency_check": [
            "workers",
            "cpu_count",
            "available_memory_bytes",
            "free_disk_bytes",
            "allow_oversubscription",
        ],
        "experiments_submit": [
            "seeds",
            "variants",
            "workers",
            "cpu_count",
            "available_memory_bytes",
            "free_disk_bytes",
        ],
        "experiments_cancel": ["job_id"],
        "experiments_resume": ["job_id"],
    }
    for name, required in expected.items():
        assert tools_by_name()[name].input_schema["required"] == required, name


@pytest.mark.parametrize(
    ("name", "arguments", "method", "path", "query", "body"),
    REQUEST_CASES,
    ids=[case[0] for case in REQUEST_CASES],
)
def test_handler_maps_arguments_to_sidecar_request(name, arguments, method, path, query, body):
    client = RecordingClient(response={"result": name})
    result = handler_for(name, client)(arguments)
    assert result == {"result": name}
    assert client.calls == [{"method": method, "path": path, "query": query, "body": body}]


def test_create_body_contains_only_supplied_fields():
    client = RecordingClient()
    handler_for("jobs_create", client)({"kind": "match"})
    handler_for("pools_create", client)({"name": "x", "tactic": {}})
    handler_for("saves_create", client)({"source_path": "/a", "source_sha256": "b"})
    assert [call["body"] for call in client.calls] == [
        {"kind": "match"},
        {"name": "x", "tactic": {}},
        {"source_path": "/a", "source_sha256": "b"},
    ]


def test_update_body_contains_only_supplied_fields():
    client = RecordingClient()
    handler_for("jobs_update", client)({"job_id": "job-1", "completed": 2})
    handler_for("saves_update", client)({"save_id": "save-1", "stage": "ready"})
    handler_for("drafts_update", client)({"draft_id": "draft-1", "name": "新名"})
    assert [call["body"] for call in client.calls] == [
        {"completed": 2},
        {"stage": "ready"},
        {"name": "新名"},
    ]


def test_handlers_return_backend_json_verbatim():
    payload = {
        "id": "pool-1",
        "items": [{"名称": "主战术", "weight": 1}],
        "total": 1,
        "next_offset": None,
        "flag": True,
    }
    client = RecordingClient(response=payload)
    result = handler_for("pools_list", client)({"limit": 5})
    assert result is payload
    assert json.loads(json.dumps(result, ensure_ascii=False)) == payload


@pytest.mark.parametrize(
    ("name", "limit_maximum", "limit_default"),
    [(name, *values) for name, values in PAGINATION_SCHEMAS.items()],
    ids=list(PAGINATION_SCHEMAS),
)
def test_pagination_schema_uses_route_bounds(name, limit_maximum, limit_default):
    properties = tools_by_name()[name].input_schema["properties"]
    limit = properties["limit"]
    offset = properties["offset"]
    assert limit["type"] == "integer"
    assert limit["minimum"] == 1
    assert limit["maximum"] == limit_maximum
    assert limit["default"] == limit_default
    assert offset["type"] == "integer"
    assert offset["minimum"] == 0
    assert offset["maximum"] == MAX_OFFSET
    assert offset["default"] == 0
    required = tools_by_name()[name].input_schema["required"]
    assert "limit" not in required
    assert "offset" not in required


def test_only_list_tools_expose_pagination():
    for tool in build_tools(RecordingClient()):
        if tool.name in PAGINATION_SCHEMAS:
            continue
        assert "limit" not in tool.input_schema["properties"], tool.name
        assert "offset" not in tool.input_schema["properties"], tool.name


def test_pagination_is_optional_transmitted_and_never_sent_as_none():
    client = RecordingClient()
    handler = handler_for("jobs_list", client)
    handler({})
    handler({"limit": 7, "offset": 3})
    handler({"offset": 2})
    assert [call["query"] for call in client.calls] == [
        None,
        {"limit": 7, "offset": 3},
        {"offset": 2},
    ]
    for call in client.calls:
        assert call["query"] is None or None not in call["query"].values()


def test_status_filter_is_optional_and_omitted_when_absent():
    client = RecordingClient()
    handler = handler_for("saves_list", client)
    handler({})
    handler({"status": "ready"})
    assert [call["query"] for call in client.calls] == [None, {"status": "ready"}]


@pytest.mark.parametrize(
    ("name", "arguments", "fragment"),
    INVALID_CASES,
    ids=[case[0] + str(index) for index, case in enumerate(INVALID_CASES)],
)
def test_invalid_arguments_raise_chinese_validation_errors(name, arguments, fragment):
    client = RecordingClient()
    with pytest.raises(SidecarError) as caught:
        handler_for(name, client)(arguments)
    error = caught.value
    assert error.code == "validation_failed"
    assert_chinese(error.message)
    assert fragment in error.message
    assert client.calls == []


def test_handler_rejects_non_object_arguments():
    client = RecordingClient()
    with pytest.raises(SidecarError) as caught:
        handler_for("pools_list", client)(["limit"])
    assert caught.value.code == "validation_failed"
    assert caught.value.message == "工具参数必须是 JSON 对象"
    assert client.calls == []


@pytest.mark.parametrize(
    ("name", "arguments", "expected_path"), ENCODING_CASES, ids=[case[0] for case in ENCODING_CASES]
)
def test_path_ids_are_percent_encoded(name, arguments, expected_path):
    client = RecordingClient()
    handler_for(name, client)(arguments)
    assert [call["path"] for call in client.calls] == expected_path


def test_sidecar_error_from_client_propagates_unchanged():
    error = SidecarError("not_found", "任务不存在", 404, retriable=False)
    client = RecordingClient(error=error)
    with pytest.raises(SidecarError) as caught:
        handler_for("jobs_get", client)({"job_id": "missing"})
    assert caught.value is error
    assert caught.value.code == "not_found"
    assert caught.value.status == 404


def protocol_server(client):
    return McpServer(name="fm27lab-test", version="0.0.0", tools=build_tools(client))


def call_tool(server, name, arguments=None):
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    line = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
        ensure_ascii=False,
    )
    return server.handle_line(line)


def test_protocol_tools_list_exposes_all_tools():
    response = protocol_server(RecordingClient()).handle_line(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    )
    listed = response["result"]["tools"]
    assert [item["name"] for item in listed] == list(tool_names())
    assert all(item["inputSchema"]["additionalProperties"] is False for item in listed)


def test_protocol_tools_call_returns_backend_content():
    payload = {"items": [], "total": 0, "next_offset": None}
    client = RecordingClient(response=payload)
    response = call_tool(protocol_server(client), "pools_list", {"limit": 3})
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == payload
    assert json.loads(result["content"][0]["text"]) == payload
    assert client.calls == [{"method": "GET", "path": "/api/pools", "query": {"limit": 3}, "body": None}]


def test_protocol_isolates_backend_errors():
    client = RecordingClient(error=SidecarError("not_found", "任务不存在", 404))
    response = call_tool(protocol_server(client), "jobs_get", {"job_id": "missing"})
    result = response["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "工具执行失败" in text
    assert "任务不存在" in text
    assert_chinese(text)


def test_protocol_isolates_validation_errors_before_any_request():
    client = RecordingClient()
    response = call_tool(protocol_server(client), "pools_list", {"limit": 0})
    result = response["result"]
    assert result["isError"] is True
    assert "参数 limit" in result["content"][0]["text"]
    assert client.calls == []


@pytest.mark.parametrize(
    ("name", "arguments", "method", "path", "query", "content_type"),
    DOWNLOAD_CASES,
    ids=[case[0] for case in DOWNLOAD_CASES],
)
def test_download_tools_return_base64_envelope(name, arguments, method, path, query, content_type):
    payload = "下载内容".encode() + b"\x00\xff"
    client = RecordingClient(download=payload, headers={"content-type": content_type})
    result = handler_for(name, client)(arguments)
    assert result == {
        "content_base64": base64.b64encode(payload).decode("ascii"),
        "content_type": content_type,
        "bytes": len(payload),
    }
    assert base64.b64decode(result["content_base64"]) == payload
    assert client.calls == [{"method": method, "path": path, "query": query, "accept": "*/*"}]


def test_download_tools_keep_content_type_from_response_headers():
    client = RecordingClient(download=b"a,b\n1,2\n", headers={"content-type": "text/csv; charset=utf-8"})
    result = handler_for("jobs_export", client)({"job_id": "job-1"})
    assert result["content_type"] == "text/csv; charset=utf-8"
    assert result["bytes"] == len(b"a,b\n1,2\n")


def test_download_tools_propagate_sidecar_errors():
    error = SidecarError("not_found", "产物不存在", 404)
    client = RecordingClient(error=error)
    with pytest.raises(SidecarError) as caught:
        handler_for("artifacts_content", client)({"artifact_id": "missing"})
    assert caught.value is error
    assert caught.value.code == "not_found"


def test_download_tools_validate_before_request():
    client = RecordingClient()
    with pytest.raises(SidecarError) as caught:
        handler_for("jobs_export", client)({})
    assert caught.value.code == "validation_failed"
    assert caught.value.message == "缺少必填参数：job_id"
    assert client.calls == []


def test_batch_id_arrays_are_bounded_and_pattern_checked():
    for name in ("jobs_batch_actions", "jobs_batch_delete"):
        ids = tools_by_name()[name].input_schema["properties"]["ids"]
        assert ids["type"] == "array", name
        assert ids["minItems"] == 1, name
        assert ids["maxItems"] == 256, name
        assert ids["uniqueItems"] is True, name
        assert ids["items"] == {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,64}$"}, name
    action = tools_by_name()["jobs_batch_actions"].input_schema["properties"]["action"]
    assert action == {"type": "string", "enum": ["cancel", "delete"]}


def test_saves_squad_requires_and_sends_club_uid():
    schema = tools_by_name()["saves_squad"].input_schema
    assert schema["required"] == ["save_id", "club_uid"]
    client = RecordingClient()
    handler_for("saves_squad", client)({"save_id": "save-1", "club_uid": 7})
    assert client.calls == [
        {"method": "GET", "path": "/api/saves/save-1/squad", "query": {"club_uid": 7}, "body": None}
    ]


def test_concurrency_check_bounds_and_query_mapping():
    schema = tools_by_name()["concurrency_check"].input_schema
    properties = schema["properties"]
    assert schema["required"] == [
        "workers",
        "cpu_count",
        "available_memory_bytes",
        "free_disk_bytes",
        "allow_oversubscription",
    ]
    assert properties["workers"]["minimum"] == 1
    assert properties["workers"]["maximum"] == 256
    assert properties["cpu_count"]["minimum"] == 1
    assert properties["available_memory_bytes"]["minimum"] == 0
    assert properties["free_disk_bytes"]["minimum"] == 0
    assert properties["allow_oversubscription"]["type"] == "boolean"
    client = RecordingClient()
    arguments = {
        "workers": 4,
        "cpu_count": 8,
        "available_memory_bytes": 8589934592,
        "free_disk_bytes": 10737418240,
        "allow_oversubscription": True,
    }
    handler_for("concurrency_check", client)(arguments)
    assert client.calls[0]["query"] == arguments
    assert client.calls[0]["body"] is None


def test_experiments_submit_schema_matches_route():
    schema = tools_by_name()["experiments_submit"].input_schema
    properties = schema["properties"]
    assert properties["seeds"] == {
        "type": "array",
        "items": {"type": "integer", "minimum": 0, "maximum": 2**32 - 1},
        "minItems": 1,
    }
    assert properties["variants"] == {"type": "array", "items": {"type": "string"}, "minItems": 1}
    assert properties["workers"] == {"type": "integer", "minimum": 1, "maximum": 256}
    assert properties["name"]["minLength"] == 1
    assert properties["name"]["maxLength"] == 100
    assert properties["allow_oversubscription"]["default"] is False


def test_boolean_properties_declare_boolean_type():
    expected = {
        "saves_import_file": ("replace",),
        "concurrency_check": ("allow_oversubscription",),
        "experiments_submit": ("allow_oversubscription",),
    }
    for name, fields in expected.items():
        properties = tools_by_name()[name].input_schema["properties"]
        for field in fields:
            assert properties[field]["type"] == "boolean", (name, field)


def test_artifacts_list_exposes_filters_and_pagination():
    schema = tools_by_name()["artifacts_list"].input_schema
    assert schema["properties"]["kind"] == {"type": "string"}
    assert schema["properties"]["job_id"] == {"type": "string"}
    assert schema["properties"]["limit"]["maximum"] == 256
    assert schema["properties"]["offset"]["maximum"] == MAX_OFFSET
    client = RecordingClient()
    handler_for("artifacts_list", client)({"kind": "report", "job_id": "job-1", "limit": 10, "offset": 2})
    assert client.calls[0]["query"] == {"kind": "report", "job_id": "job-1", "limit": 10, "offset": 2}


def test_settings_put_accepts_any_json_value():
    value = tools_by_name()["settings_put"].input_schema["properties"]["value"]
    assert isinstance(value["type"], list)
    assert set(value["type"]) == {"array", "boolean", "integer", "null", "number", "object", "string"}
    client = RecordingClient()
    for item in (1, 1.5, "文本", True, None, [1, 2], {"a": 1}):
        handler_for("settings_put", client)({"key": "ui.theme", "value": item})
    assert [call["body"]["value"] for call in client.calls] == [1, 1.5, "文本", True, None, [1, 2], {"a": 1}]


def test_keys_and_ids_are_string_schemas():
    assert tools_by_name()["settings_get"].input_schema["properties"]["key"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
    }
    assert tools_by_name()["settings_delete"].input_schema["required"] == ["key"]
    assert tools_by_name()["artifacts_delete"].input_schema["required"] == ["artifact_id"]


def test_new_create_bodies_contain_only_supplied_fields():
    client = RecordingClient()
    handler_for("drafts_attributes", client)(
        {"draft_id": "draft-1", "side": "home", "scope": "all", "operation": "undo", "params": {}}
    )
    handler_for("artifacts_create", client)({"kind": "report", "filename": "a.csv", "content_base64": "YQ=="})
    handler_for("settings_put", client)({"key": "ui.theme", "value": 1})
    handler_for("saves_import_file", client)({"source_path": "/tmp/a.fm"})
    handler_for("experiments_submit", client)(
        {
            "seeds": [1],
            "variants": ["A"],
            "workers": 1,
            "cpu_count": 1,
            "available_memory_bytes": 0,
            "free_disk_bytes": 0,
        }
    )
    assert [call["body"] for call in client.calls] == [
        {"side": "home", "scope": "all", "operation": "undo", "params": {}},
        {"kind": "report", "filename": "a.csv", "content_base64": "YQ=="},
        {"value": 1},
        {"source_path": "/tmp/a.fm"},
        {
            "seeds": [1],
            "variants": ["A"],
            "workers": 1,
            "cpu_count": 1,
            "available_memory_bytes": 0,
            "free_disk_bytes": 0,
        },
    ]


def test_zero_argument_tools_send_no_query_or_body():
    client = RecordingClient()
    for name in ("settings_list", "experiments_start", "catalog_snapshot"):
        handler_for(name, client)({})
    assert [(call["method"], call["path"], call["query"], call["body"]) for call in client.calls] == [
        ("GET", "/api/settings", None, None),
        ("POST", "/api/experiments/start", None, None),
        ("GET", "/api/catalog", None, None),
    ]


def test_new_tools_reject_unknown_arguments_before_request():
    for name, arguments in (
        ("settings_list", {"limit": 1}),
        ("catalog_snapshot", {"status": "ok"}),
        ("experiments_start", {"job_id": "job-1"}),
    ):
        client = RecordingClient()
        with pytest.raises(SidecarError) as caught:
            handler_for(name, client)(arguments)
        assert caught.value.code == "validation_failed"
        assert client.calls == []


@pytest.mark.parametrize(("name", "arguments"), NEW_ERROR_CASES, ids=[case[0] for case in NEW_ERROR_CASES])
def test_new_tools_propagate_sidecar_errors(name, arguments):
    error = SidecarError("not_found", "资源不存在", 404)
    client = RecordingClient(error=error)
    with pytest.raises(SidecarError) as caught:
        handler_for(name, client)(arguments)
    assert caught.value is error
    assert caught.value.status == 404


def test_protocol_download_tool_returns_json_envelope():
    payload = b"FMF"
    client = RecordingClient(download=payload)
    response = call_tool(protocol_server(client), "drafts_export_fmf", {"draft_id": "draft-1"})
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {
        "content_base64": base64.b64encode(payload).decode("ascii"),
        "content_type": "application/octet-stream",
        "bytes": len(payload),
    }
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
