from __future__ import annotations

import io
import json
import re
import socket

import pytest
from typer.testing import CliRunner

import fm27lab
import fm27lab.cli as cli
from fm27lab.client import SidecarError
from fm27lab.interfaces.mcp.tools import tool_names

TOKEN = "token-must-not-leak-7d3e"
HEALTH_PATH = "/api/health"
CJK = re.compile(r"[\u4e00-\u9fff]")
ENDPOINT = {"url": "http://127.0.0.1:4321", "token": TOKEN}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "clientInfo": {"name": "pytest", "version": "1.0"},
        "capabilities": {},
    },
}
INITIALIZED_NOTIFICATION = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def request(request_id, method, params=None):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class FakeClient:
    """记录 sidecar 请求并按路径返回健康检查或预设结果的替身。"""

    def __init__(self, responses=None, health_error=None, error=None):
        self.responses = list(responses or [])
        self.health_error = health_error
        self.error = error
        self.calls = []

    def request_json(self, method, path, *, body=None, query=None):
        self.calls.append({"method": method, "path": path, "body": body, "query": query})
        if path == HEALTH_PATH:
            if self.health_error is not None:
                raise self.health_error
            return {"status": "ok"}
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError(f"未预期的请求：{method} {path}")
        return self.responses.pop(0)


def install_fake_sidecar(monkeypatch, responses=(), health_error=None, error=None):
    fake = FakeClient(responses, health_error, error)
    captured = {}

    def fake_discover(data_dir):
        captured["data_dir"] = data_dir
        return dict(ENDPOINT)

    class FakeSidecarClient:
        def __init__(self, url, token, **kwargs):
            captured["url"] = url
            captured["token"] = token

        def request_json(self, method, path, *, body=None, query=None):
            return fake.request_json(method, path, body=body, query=query)

    monkeypatch.setattr(cli, "discover_endpoint", fake_discover)
    monkeypatch.setattr(cli, "SidecarClient", FakeSidecarClient)
    return fake, captured


def encode_messages(*messages):
    return io.BytesIO(
        b"".join(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n" for message in messages)
    )


def decode_replies(outstream):
    raw = outstream.getvalue()
    if not raw:
        return []
    text = raw.decode("utf-8")
    assert text.endswith("\n"), "响应必须以换行结束"
    lines = text.splitlines()
    assert raw.count(b"\n") == len(lines), "每个响应必须独占一行"
    replies = [json.loads(line) for line in lines]
    for reply in replies:
        assert reply["jsonrpc"] == "2.0"
        assert set(reply) <= {"jsonrpc", "id", "result", "error"}
        assert ("result" in reply) != ("error" in reply)
    return replies


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("FM27LAB_DATA", raising=False)
    monkeypatch.delenv("FM27LAB_TOKEN", raising=False)


def test_run_mcp_serves_handshake_lists_tools_and_routes_tool_call(monkeypatch, tmp_path, capsys):
    payload = {"items": [{"id": "p1"}], "total": 1, "next_offset": None}
    fake, captured = install_fake_sidecar(monkeypatch, [payload])
    messages = (
        INITIALIZE,
        INITIALIZED_NOTIFICATION,
        request(2, "tools/list", {}),
        request(3, "tools/call", {"name": "pools_list", "arguments": {"limit": 5, "offset": 2}}),
    )
    outstream = io.BytesIO()
    exit_code = cli.run_mcp(tmp_path, encode_messages(*messages), outstream)
    assert exit_code == 0
    replies = decode_replies(outstream)
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert replies[0]["result"] == {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False},
            "prompts": {"listChanged": False},
        },
        "serverInfo": {"name": "fm27lab", "version": fm27lab.__version__},
    }
    listed = replies[1]["result"]["tools"]
    assert [item["name"] for item in listed] == list(tool_names())
    assert len(listed) == 22
    result = replies[2]["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == payload
    assert json.loads(result["content"][0]["text"]) == payload
    assert fake.calls == [
        {"method": "GET", "path": HEALTH_PATH, "body": None, "query": None},
        {"method": "GET", "path": "/api/pools", "body": None, "query": {"limit": 5, "offset": 2}},
    ]
    assert captured == {"data_dir": tmp_path, "url": ENDPOINT["url"], "token": TOKEN}
    assert capsys.readouterr().err == ""
    assert TOKEN not in outstream.getvalue().decode("utf-8")


def test_run_mcp_sends_no_reply_for_notifications(monkeypatch, tmp_path, capsys):
    fake, _ = install_fake_sidecar(monkeypatch)
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, encode_messages(INITIALIZED_NOTIFICATION), outstream) == 0
    assert outstream.getvalue() == b""
    assert fake.calls == [{"method": "GET", "path": HEALTH_PATH, "body": None, "query": None}]
    assert capsys.readouterr().err == ""


def test_run_mcp_keeps_stdout_pure_for_blank_and_invalid_lines(monkeypatch, tmp_path, capsys):
    install_fake_sidecar(monkeypatch)
    instream = io.BytesIO(
        b"\n{bad json\n" + json.dumps(request(2, "tools/list"), ensure_ascii=False).encode("utf-8") + b"\n"
    )
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, instream, outstream) == 0
    replies = decode_replies(outstream)
    assert len(replies) == 2
    assert replies[0] == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "无法解析的 JSON"},
    }
    assert replies[1]["id"] == 2
    assert capsys.readouterr().err == ""


def test_run_mcp_isolates_invalid_requests_without_backend_calls(monkeypatch, tmp_path, capsys):
    fake, _ = install_fake_sidecar(monkeypatch)
    messages = (
        {"jsonrpc": "1.0", "id": 1, "method": "tools/list"},
        request(2, "missing/method", {}),
        request(3, "tools/call", {"name": "nope", "arguments": {}}),
    )
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, encode_messages(*messages), outstream) == 0
    replies = decode_replies(outstream)
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert [reply["error"]["code"] for reply in replies] == [-32600, -32601, -32602]
    assert fake.calls == [{"method": "GET", "path": HEALTH_PATH, "body": None, "query": None}]
    assert capsys.readouterr().err == ""


def test_run_mcp_returns_zero_on_eof_without_tool_requests(monkeypatch, tmp_path, capsys):
    fake, _ = install_fake_sidecar(monkeypatch)
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, io.BytesIO(b""), outstream) == 0
    assert outstream.getvalue() == b""
    assert fake.calls == [{"method": "GET", "path": HEALTH_PATH, "body": None, "query": None}]
    assert capsys.readouterr().err == ""


def test_run_mcp_reports_tool_errors_in_protocol_not_stderr(monkeypatch, tmp_path, capsys):
    install_fake_sidecar(monkeypatch, error=SidecarError("not_found", "任务不存在", 404))
    messages = (request(1, "tools/call", {"name": "jobs_get", "arguments": {"job_id": "missing"}}),)
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, encode_messages(*messages), outstream) == 0
    replies = decode_replies(outstream)
    assert len(replies) == 1
    result = replies[0]["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "工具执行失败" in text
    assert "任务不存在" in text
    assert capsys.readouterr().err == ""


def test_run_mcp_carries_utf8_tool_arguments_and_results(monkeypatch, tmp_path, capsys):
    payload = {"id": "p1", "name": "角球战术"}
    fake, _ = install_fake_sidecar(monkeypatch, [payload])
    messages = (
        request(
            1,
            "tools/call",
            {"name": "pools_create", "arguments": {"name": "角球战术", "tactic": {"formation": "4-4-2"}}},
        ),
    )
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, encode_messages(*messages), outstream) == 0
    replies = decode_replies(outstream)
    assert replies[0]["result"]["structuredContent"] == payload
    assert "角球战术" in outstream.getvalue().decode("utf-8")
    assert fake.calls[-1] == {
        "method": "POST",
        "path": "/api/pools",
        "body": {"name": "角球战术", "tactic": {"formation": "4-4-2"}},
        "query": None,
    }
    assert capsys.readouterr().err == ""


def test_run_mcp_reports_missing_endpoint_on_stderr(tmp_path, capsys):
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, io.BytesIO(b""), outstream) == 1
    assert outstream.getvalue() == b""
    stderr = capsys.readouterr().err
    assert "无法启动 MCP 服务" in stderr
    assert "endpoint_missing" in stderr
    assert "找不到 sidecar 发现文件" in stderr
    assert CJK.search(stderr)


def test_run_mcp_reports_corrupt_endpoint_on_stderr(tmp_path, capsys):
    endpoint = tmp_path / "agent" / "endpoint.json"
    endpoint.parent.mkdir(parents=True)
    endpoint.write_text("{not-json", encoding="utf-8")
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, io.BytesIO(b""), outstream) == 1
    assert outstream.getvalue() == b""
    stderr = capsys.readouterr().err
    assert "endpoint_invalid" in stderr
    assert CJK.search(stderr)
    assert "Traceback" not in stderr


def test_run_mcp_rejects_non_loopback_endpoint_without_leaking_token(tmp_path, capsys):
    endpoint = tmp_path / "agent" / "endpoint.json"
    endpoint.parent.mkdir(parents=True)
    endpoint.write_text(
        json.dumps({"url": "https://example.com:443", "token": TOKEN}),
        encoding="utf-8",
    )
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, io.BytesIO(b""), outstream) == 1
    assert outstream.getvalue() == b""
    stderr = capsys.readouterr().err
    assert "endpoint_invalid" in stderr
    assert CJK.search(stderr)
    assert TOKEN not in stderr


def test_run_mcp_reports_unreachable_sidecar_on_stderr(monkeypatch, tmp_path, capsys):
    error = SidecarError("unreachable", "无法连接 sidecar：Connection refused")
    fake, _ = install_fake_sidecar(monkeypatch, health_error=error)
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, io.BytesIO(b""), outstream) == 1
    assert outstream.getvalue() == b""
    stderr = capsys.readouterr().err
    assert "unreachable" in stderr
    assert "无法连接 sidecar" in stderr
    assert CJK.search(stderr)
    assert TOKEN not in stderr
    assert fake.calls == [{"method": "GET", "path": HEALTH_PATH, "body": None, "query": None}]


def test_run_mcp_reports_connection_refused_from_real_client(tmp_path, capsys):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        endpoint = tmp_path / "agent" / "endpoint.json"
        endpoint.parent.mkdir(parents=True)
        endpoint.write_text(
            json.dumps({"url": f"http://127.0.0.1:{port}", "token": TOKEN}),
            encoding="utf-8",
        )
        outstream = io.BytesIO()
        assert cli.run_mcp(tmp_path, io.BytesIO(b""), outstream) == 1
    assert outstream.getvalue() == b""
    stderr = capsys.readouterr().err
    assert "unreachable" in stderr
    assert "无法连接 sidecar" in stderr
    assert CJK.search(stderr)
    assert TOKEN not in stderr
    assert "Traceback" not in stderr


def test_run_mcp_reports_client_creation_failure_on_stderr(monkeypatch, tmp_path, capsys):
    error = SidecarError("unreachable", "无法连接 sidecar：Connection refused")

    class FailingClient:
        def __init__(self, url, token, **kwargs):
            raise error

    monkeypatch.setattr(cli, "discover_endpoint", lambda data_dir: dict(ENDPOINT))
    monkeypatch.setattr(cli, "SidecarClient", FailingClient)
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, io.BytesIO(b""), outstream) == 1
    assert outstream.getvalue() == b""
    stderr = capsys.readouterr().err
    assert "无法启动 MCP 服务" in stderr
    assert "unreachable" in stderr
    assert CJK.search(stderr)
    assert TOKEN not in stderr


def test_root_help_lists_mcp_command():
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "mcp" in result.stdout


def test_mcp_help_renders_without_endpoint_discovery(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("--help 不应读取 endpoint.json")

    monkeypatch.setattr(cli, "discover_endpoint", fail)
    result = CliRunner().invoke(cli.app, ["mcp", "--help"])
    assert result.exit_code == 0, result.output
    assert "MCP" in result.stdout
    assert "stdio" in result.stdout
    assert "Traceback" not in result.output


def test_mcp_command_maps_run_mcp_result_to_exit_code(monkeypatch, tmp_path):
    captured = {}

    def fake_run_mcp(data_dir, instream, outstream):
        captured.update(data_dir=data_dir, instream=instream, outstream=outstream)
        return 3

    monkeypatch.setattr(cli, "run_mcp", fake_run_mcp)
    result = CliRunner().invoke(cli.app, ["--data-dir", str(tmp_path), "mcp"])
    assert result.exit_code == 3
    assert result.stdout == ""
    assert captured["data_dir"] == tmp_path.resolve()
    assert hasattr(captured["instream"], "readline")
    assert hasattr(captured["outstream"], "write")


def test_mcp_command_global_data_dir_overrides_environment(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        cli,
        "run_mcp",
        lambda data_dir, instream, outstream: captured.setdefault("data_dir", data_dir) and 0,
    )
    env_dir = tmp_path / "env-data"
    global_dir = tmp_path / "global-data"
    monkeypatch.setenv("FM27LAB_DATA", str(env_dir))
    result = CliRunner().invoke(cli.app, ["--data-dir", str(global_dir), "mcp"])
    assert result.exit_code == 0, result.output
    assert captured["data_dir"] == global_dir.resolve()


def test_mcp_command_falls_back_to_environment_data_dir(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        cli,
        "run_mcp",
        lambda data_dir, instream, outstream: captured.setdefault("data_dir", data_dir) and 0,
    )
    monkeypatch.setenv("FM27LAB_DATA", str(tmp_path))
    result = CliRunner().invoke(cli.app, ["mcp"])
    assert result.exit_code == 0, result.output
    assert captured["data_dir"] == tmp_path.resolve()


def test_mcp_command_rejects_invalid_environment_data_dir(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "run_mcp", lambda *args: called.append(args) or 0)
    monkeypatch.setenv("FM27LAB_DATA", "   ")
    result = CliRunner().invoke(cli.app, ["mcp"])
    assert result.exit_code == 2
    assert "数据目录无效" in result.stderr
    assert called == []


def test_mcp_command_reports_discovery_errors_on_stderr(monkeypatch, tmp_path):
    def fail(_data_dir):
        raise SidecarError("endpoint_missing", "找不到 sidecar 发现文件：/data/agent/endpoint.json")

    monkeypatch.setattr(cli, "discover_endpoint", fail)
    result = CliRunner().invoke(cli.app, ["--data-dir", str(tmp_path), "mcp"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "endpoint_missing" in result.stderr
    assert "找不到 sidecar 发现文件" in result.stderr
    assert CJK.search(result.stderr)


def test_mcp_command_serves_protocol_over_stdio_end_to_end(monkeypatch, tmp_path):
    payload = {"items": [], "total": 0, "next_offset": None}
    install_fake_sidecar(monkeypatch, [payload])
    messages = (
        INITIALIZE,
        INITIALIZED_NOTIFICATION,
        request(2, "tools/list"),
        request(3, "tools/call", {"name": "pools_list", "arguments": {"limit": 1}}),
    )
    result = CliRunner().invoke(
        cli.app,
        ["--data-dir", str(tmp_path), "mcp"],
        input="".join(json.dumps(message, ensure_ascii=False) + "\n" for message in messages),
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.endswith("\n")
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert replies[2]["result"]["structuredContent"] == payload
    assert result.stderr == ""
    assert TOKEN not in result.stdout + result.stderr


def test_run_mcp_exposes_resources_and_prompts_alongside_tools(monkeypatch, tmp_path, capsys):
    payload = {"items": [{"id": "dr_1"}], "total": 1, "next_offset": None}
    fake, _ = install_fake_sidecar(monkeypatch, [payload])
    messages = (
        INITIALIZE,
        INITIALIZED_NOTIFICATION,
        request(2, "resources/list"),
        request(3, "prompts/list"),
        request(4, "tools/list"),
        request(5, "resources/read", {"uri": "fm27lab://drafts"}),
        request(
            6,
            "prompts/get",
            {
                "name": "experiment-design",
                "arguments": {"draft_id": "dr_1", "instruction": "提高逼抢"},
            },
        ),
    )
    outstream = io.BytesIO()
    assert cli.run_mcp(tmp_path, encode_messages(*messages), outstream) == 0
    replies = decode_replies(outstream)
    assert [reply["id"] for reply in replies] == [1, 2, 3, 4, 5, 6]
    capabilities = replies[0]["result"]["capabilities"]
    assert capabilities == {
        "tools": {"listChanged": False},
        "resources": {"listChanged": False},
        "prompts": {"listChanged": False},
    }
    assert [item["uri"] for item in replies[1]["result"]["resources"]] == [
        "fm27lab://drafts",
        "fm27lab://pools",
        "fm27lab://jobs",
        "fm27lab://saves",
    ]
    assert [item["name"] for item in replies[2]["result"]["prompts"]] == [
        "experiment-design",
        "pool-review",
    ]
    assert [item["name"] for item in replies[3]["result"]["tools"]] == list(tool_names())
    contents = replies[4]["result"]["contents"][0]
    assert contents["uri"] == "fm27lab://drafts"
    assert contents["mimeType"] == "application/json"
    assert json.loads(contents["text"]) == payload
    prompt_message = replies[5]["result"]["messages"][0]
    assert prompt_message["role"] == "user"
    assert prompt_message["content"]["type"] == "text"
    assert "dr_1" in prompt_message["content"]["text"]
    assert fake.calls == [
        {"method": "GET", "path": HEALTH_PATH, "body": None, "query": None},
        {"method": "GET", "path": "/api/drafts", "body": None, "query": {"limit": 128, "offset": 0}},
    ]
    assert capsys.readouterr().err == ""
    assert TOKEN not in outstream.getvalue().decode("utf-8")
