from __future__ import annotations

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
)

PAGINATION_SCHEMAS = {
    "pools_list": (128, 128),
    "drafts_list": (128, 128),
    "jobs_list": (256, 50),
    "jobs_runs": (200, 50),
    "saves_list": (256, 50),
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
)

ENCODING_CASES = (
    ("pools_get", {"entry_id": "a/b?c#d e%"}, ["/api/pools/a%2Fb%3Fc%23d%20e%25"]),
    ("jobs_runs", {"job_id": "任务/一"}, ["/api/jobs/%E4%BB%BB%E5%8A%A1%2F%E4%B8%80/runs"]),
    ("saves_import", {"save_id": "x/y", "leagues": {}, "clubs": {}}, ["/api/saves/x%2Fy/import"]),
)


class RecordingClient:
    "记录请求并返回固定结果的替身客户端。"

    def __init__(self, response=None, error=None):
        self.response = {"ok": True} if response is None else response
        self.error = error
        self.calls: list[dict] = []

    def request_json(self, method, path, *, body=None, query=None):
        self.calls.append({"method": method, "path": path, "query": query, "body": body})
        if self.error is not None:
            raise self.error
        return self.response


def tools_by_name(client=None):
    client = RecordingClient() if client is None else client
    return {tool.name: tool for tool in build_tools(client)}


def handler_for(name, client):
    return tools_by_name(client)[name].handler


def assert_chinese(text):
    assert CJK.search(text), text


def test_tool_inventory_is_stable():
    assert tool_names() == EXPECTED_TOOL_NAMES
    assert len(tool_names()) == 22
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
