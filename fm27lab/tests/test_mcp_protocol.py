from __future__ import annotations

import io
import json

import pytest

from fm27lab.interfaces.mcp.protocol import McpServer, McpTool

CJK_START = "\u4e00"
CJK_END = "\u9fff"


def echo_tool() -> McpTool:
    return McpTool(
        name="echo",
        description="回显参数",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=lambda arguments: {"text": arguments["text"]},
    )


def make_server(*tools: McpTool) -> McpServer:
    return McpServer(name="fm27lab-test", version="9.9.9", tools=list(tools))


def request(
    method: str,
    params: dict | None = None,
    request_id: int | str | None = 1,
) -> str:
    message: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    if request_id is not None:
        message["id"] = request_id
    return json.dumps(message, ensure_ascii=False)


def exchange(server: McpServer, *lines: str) -> list[dict]:
    instream = io.StringIO("\n".join(lines) + "\n")
    outstream = io.StringIO()
    server.serve(instream, outstream)
    output = outstream.getvalue()
    if output:
        assert output.endswith("\n"), "每条协议响应都必须以换行结束"
    responses = [json.loads(line) for line in output.splitlines()]
    assert output.count("\n") == len(responses), "每个响应必须独占一行"
    return responses


def single(server: McpServer, line: str) -> dict:
    responses = exchange(server, line)
    assert len(responses) == 1
    return responses[0]


class StrictDecodeStream:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self._decode_failed = False

    def readline(self) -> str:
        if not self._decode_failed:
            self._decode_failed = True
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        if self._lines:
            return self._lines.pop(0)
        return ""


def assert_chinese(message: str) -> None:
    assert any(CJK_START <= char <= CJK_END for char in message), message


def test_initialize_handshake():
    response = single(
        make_server(),
        request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "pytest", "version": "1.0"},
                "capabilities": {},
            },
        ),
    )
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["result"] == {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "fm27lab-test", "version": "9.9.9"},
    }


def test_initialize_reports_fixed_protocol_for_other_requested_versions():
    response = single(make_server(), request("initialize", {"protocolVersion": "2099-01-01"}))
    assert response["result"]["protocolVersion"] == "2024-11-05"


def test_initialized_notification_has_no_response():
    responses = exchange(
        make_server(),
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}',
        '{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":3}}',
    )
    assert responses == []


def test_tools_list_returns_name_description_and_schema():
    tool = echo_tool()
    response = single(make_server(tool), request("tools/list", {}))
    assert response["result"] == {
        "tools": [
            {
                "name": "echo",
                "description": "回显参数",
                "inputSchema": tool.input_schema,
            }
        ]
    }


def test_tools_list_is_empty_without_tools():
    response = single(make_server(), request("tools/list", {}))
    assert response["result"] == {"tools": []}


def test_tools_call_success_returns_text_and_structured_content():
    received: list[dict] = []
    tool = McpTool(
        name="echo",
        description="回显参数",
        input_schema={"type": "object"},
        handler=lambda arguments: received.append(arguments) or {"text": arguments["text"]},
    )
    response = single(
        make_server(tool),
        request("tools/call", {"name": "echo", "arguments": {"text": "你好"}}),
    )
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"text": "你好"}
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == {"text": "你好"}
    assert received == [{"text": "你好"}]


def test_tools_call_defaults_arguments_to_empty_object():
    receiver = McpTool(
        name="inspect",
        description="检查参数",
        input_schema={"type": "object"},
        handler=lambda arguments: {"arguments": arguments},
    )
    result = single(make_server(receiver), request("tools/call", {"name": "inspect"}))["result"]
    assert result["structuredContent"] == {"arguments": {}}


def test_tools_call_unknown_tool_returns_invalid_params():
    response = single(
        make_server(echo_tool()),
        request("tools/call", {"name": "nope", "arguments": {}}),
    )
    assert response["id"] == 1
    assert "result" not in response
    assert response["error"]["code"] == -32602
    assert "未知工具" in response["error"]["message"]
    assert_chinese(response["error"]["message"])


def test_tools_call_invalid_params_return_invalid_params():
    responses = exchange(
        make_server(echo_tool()),
        request("tools/call", {}, 1),
        request("tools/call", {"name": "echo", "arguments": ["不是对象"]}, 2),
    )
    assert [response["error"]["code"] for response in responses] == [-32602, -32602]
    for response in responses:
        assert_chinese(response["error"]["message"])


def test_tools_call_params_must_be_object():
    responses = exchange(
        make_server(),
        '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":["echo"]}',
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":"echo"}',
    )
    assert [response["id"] for response in responses] == [1, 2]
    assert [response["error"]["code"] for response in responses] == [-32602, -32602]


def test_unknown_method_returns_method_not_found():
    response = single(make_server(), request("tools/unknown", {}))
    assert response["id"] == 1
    assert response["error"]["code"] == -32601
    assert "未知方法" in response["error"]["message"]
    assert_chinese(response["error"]["message"])


def test_invalid_json_returns_parse_error():
    response = single(make_server(), "{不是合法的 JSON")
    assert response["id"] is None
    assert response["error"]["code"] == -32700
    assert_chinese(response["error"]["message"])


def test_deeply_nested_json_returns_parse_error_and_service_continues():
    nested = "[" * 50000 + "]" * 50000
    deep_request = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":' + nested + "}"
    responses = exchange(make_server(), deep_request, request("tools/list", {}, 2))
    assert len(responses) == 2
    assert responses[0]["id"] is None
    assert responses[0]["error"]["code"] == -32700
    assert "嵌套" in responses[0]["error"]["message"]
    assert_chinese(responses[0]["error"]["message"])
    assert responses[1]["id"] == 2
    assert responses[1]["result"] == {"tools": []}


def test_invalid_messages_return_invalid_request():
    responses = exchange(
        make_server(),
        json.dumps({"jsonrpc": "2.0", "id": 7}),
        json.dumps({"jsonrpc": "1.0", "id": 8, "method": "initialize"}),
        '{"jsonrpc":"2.0","method":"tools/list"}',
        json.dumps([{"jsonrpc": "2.0", "id": 9, "method": "tools/list"}]),
    )
    assert [response["error"]["code"] for response in responses] == [-32600] * 4
    assert [response["id"] for response in responses] == [7, 8, None, None]
    for response in responses:
        assert_chinese(response["error"]["message"])


def test_handler_exception_is_isolated_and_returns_tool_error():
    def explode(arguments: dict) -> dict:
        raise RuntimeError("内部爆炸")

    server = make_server(
        McpTool("boom", "失败工具", {"type": "object"}, explode),
        echo_tool(),
    )
    responses = exchange(
        server,
        request("tools/call", {"name": "boom", "arguments": {}}, request_id="失败-1"),
        request("tools/call", {"name": "echo", "arguments": {"text": "仍然可用"}}, request_id="next"),
    )
    assert responses[0]["id"] == "失败-1"
    result = responses[0]["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "工具执行失败" in text
    assert "内部爆炸" in text
    assert responses[1]["result"]["isError"] is False
    assert responses[1]["result"]["structuredContent"] == {"text": "仍然可用"}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_tool_returning_non_finite_number_is_isolated_as_tool_error(value: float):
    tool = McpTool("score", "非有限数值", {"type": "object"}, lambda arguments: {"score": value})
    result = single(make_server(tool), request("tools/call", {"name": "score", "arguments": {}}))["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "tool_error"
    text = result["content"][0]["text"]
    assert "工具执行失败" in text
    assert_chinese(text)


def test_tool_returning_unserializable_value_is_isolated_as_tool_error():
    tool = McpTool("bad", "无法序列化", {"type": "object"}, lambda arguments: {"value": object()})
    result = single(make_server(tool), request("tools/call", {"name": "bad", "arguments": {}}))["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "工具执行失败" in text
    assert_chinese(text)


def test_response_echoes_request_id_verbatim():
    responses = exchange(
        make_server(),
        request("tools/list", {}, request_id="alpha"),
        request("tools/list", {}, request_id=42),
        request("tools/list", {}, request_id=0),
    )
    assert [response["id"] for response in responses] == ["alpha", 42, 0]


def test_request_with_explicit_null_id_is_answered_with_null_id():
    response = single(make_server(), '{"jsonrpc":"2.0","id":null,"method":"tools/list"}')
    assert response["jsonrpc"] == "2.0"
    assert response["id"] is None
    assert response["result"] == {"tools": []}


def test_processes_multiple_lines_in_order():
    responses = exchange(
        make_server(echo_tool()),
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}',
        '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{"text":"三次"}}}',
    )
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[2]["result"]["structuredContent"] == {"text": "三次"}


def test_eof_exits_normally_and_blank_lines_are_skipped():
    server = make_server()
    outstream = io.StringIO()
    server.serve(io.StringIO(""), outstream)
    assert outstream.getvalue() == ""
    responses = exchange(server, "", "   ", request("tools/list", {}, 5))
    assert [response["id"] for response in responses] == [5]


def test_final_line_without_newline_is_processed():
    outstream = io.StringIO()
    make_server().serve(io.StringIO(request("tools/list", {}, 6)), outstream)
    output = outstream.getvalue()
    assert output.endswith("\n")
    assert [json.loads(line)["id"] for line in output.splitlines()] == [6]


def test_stdout_contains_only_protocol_json():
    def explode(arguments: dict) -> dict:
        raise RuntimeError("诊断不应写入 stdout")

    server = make_server(McpTool("boom", "失败工具", {"type": "object"}, explode))
    lines = [
        request("tools/list", {}, 1),
        "{坏 JSON",
        request("tools/call", {"name": "boom", "arguments": {}}, 2),
        request("missing/method", {}, 3),
    ]
    outstream = io.StringIO()
    server.serve(io.StringIO("\n".join(lines) + "\n"), outstream)
    output_lines = outstream.getvalue().splitlines()
    assert len(output_lines) == 4
    for line in output_lines:
        payload = json.loads(line)
        assert payload["jsonrpc"] == "2.0"
        assert set(payload) <= {"jsonrpc", "id", "result", "error"}
        assert ("result" in payload) != ("error" in payload)


def test_serve_supports_binary_streams_and_rejects_invalid_utf8():
    server = make_server()
    instream = io.BytesIO(request("initialize", {}, 1).encode("utf-8") + b"\n" + b"\xff\xfe\n")
    outstream = io.BytesIO()
    server.serve(instream, outstream)
    raw = outstream.getvalue()
    assert raw.endswith(b"\n")
    responses = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    assert raw.count(b"\n") == len(responses)
    assert responses[0]["result"]["protocolVersion"] == "2024-11-05"
    assert responses[1]["id"] is None
    assert responses[1]["error"]["code"] == -32700


def test_serve_survives_strict_text_stream_decode_error():
    instream = io.TextIOWrapper(io.BytesIO(b"\xff\xfe\n"), encoding="utf-8", errors="strict")
    outstream = io.StringIO()
    make_server().serve(instream, outstream)
    responses = [json.loads(line) for line in outstream.getvalue().splitlines()]
    assert len(responses) == 1
    assert responses[0]["id"] is None
    assert responses[0]["error"]["code"] == -32700


def test_serve_recovers_from_text_decode_error_and_continues():
    instream = StrictDecodeStream([request("tools/list", {}, 7)])
    outstream = io.StringIO()
    make_server().serve(instream, outstream)
    responses = [json.loads(line) for line in outstream.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["id"] is None
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 7
    assert responses[1]["result"] == {"tools": []}


def test_register_adds_tools_and_rejects_duplicates():
    server = make_server()
    assert single(server, request("tools/list", {}))["result"] == {"tools": []}
    server.register(echo_tool())
    listed = single(server, request("tools/list", {}))["result"]["tools"]
    assert [tool["name"] for tool in listed] == ["echo"]
    with pytest.raises(ValueError):
        server.register(echo_tool())


def test_register_rejects_empty_name():
    server = make_server()
    with pytest.raises(ValueError):
        server.register(McpTool("", "空名工具", {"type": "object"}, lambda arguments: {}))
