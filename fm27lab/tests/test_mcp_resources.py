from __future__ import annotations

import io
import json

import pytest

from fm27lab.client import SidecarError
from fm27lab.interfaces.mcp.protocol import McpServer
from fm27lab.interfaces.mcp.resources import build_resources

RESOURCE_CASES = (
    ("fm27lab://drafts", "/api/drafts", {"limit": 128, "offset": 0}),
    ("fm27lab://pools", "/api/pools", {"limit": 128, "offset": 0}),
    ("fm27lab://jobs", "/api/jobs", {"limit": 256, "offset": 0}),
    ("fm27lab://saves", "/api/saves", {"limit": 256, "offset": 0}),
)


class FakeClient:
    """记录 sidecar 请求并按路径返回预设列表的替身。"""

    def __init__(self, payloads=None, error=None):
        self.payloads = dict(payloads or {})
        self.error = error
        self.calls = []

    def request_json(self, method, path, *, body=None, query=None):
        self.calls.append({"method": method, "path": path, "body": body, "query": query})
        if self.error is not None:
            raise self.error
        if path not in self.payloads:
            raise AssertionError(f"未预期的请求：{method} {path}")
        return self.payloads[path]


def make_server(client):
    return McpServer(name="fm27lab-test", version="9.9.9", resources=build_resources(client))


def request(method, params=None):
    message = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message, ensure_ascii=False)


def serve(server, line):
    outstream = io.StringIO()
    server.serve(io.StringIO(line + "\n"), outstream)
    return json.loads(outstream.getvalue())


def read_resource(server, uri):
    return serve(server, request("resources/read", {"uri": uri}))


def test_build_resources_exposes_four_json_resources():
    resources = build_resources(FakeClient())
    assert [resource.uri for resource in resources] == [case[0] for case in RESOURCE_CASES]
    for resource in resources:
        assert resource.name
        assert "列表" in resource.description
        assert resource.mime_type == "application/json"


def test_resources_list_exposes_all_resource_uris():
    listed = serve(make_server(FakeClient()), request("resources/list", {}))["result"]["resources"]
    assert [item["uri"] for item in listed] == [case[0] for case in RESOURCE_CASES]
    for item in listed:
        assert item["mimeType"] == "application/json"


@pytest.mark.parametrize(("uri", "path", "query"), RESOURCE_CASES)
def test_resource_read_returns_compact_json_from_list_endpoint(uri, path, query):
    payload = {"items": [{"id": "x1", "name": "中文条目"}], "total": 1, "next_offset": None}
    client = FakeClient({path: payload})
    contents = read_resource(make_server(client), uri)["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == uri
    assert contents[0]["mimeType"] == "application/json"
    assert json.loads(contents[0]["text"]) == payload
    assert contents[0]["text"] == json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert client.calls == [{"method": "GET", "path": path, "body": None, "query": query}]


def test_unknown_resource_uri_is_rejected_without_backend_call():
    client = FakeClient()
    reply = read_resource(make_server(client), "fm27lab://unknown")
    assert reply["error"]["code"] == -32602
    assert "未知资源" in reply["error"]["message"]
    assert client.calls == []


def test_resource_read_surfaces_client_error_as_internal_error():
    error = SidecarError("unreachable", "无法连接 sidecar：Connection refused")
    reply = read_resource(make_server(FakeClient(error=error)), "fm27lab://drafts")
    assert reply["error"]["code"] == -32603
    assert "资源读取失败" in reply["error"]["message"]
    assert "无法连接 sidecar" in reply["error"]["message"]
