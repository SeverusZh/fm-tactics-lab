from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, BinaryIO, TextIO

PROTOCOL_VERSION = "2024-11-05"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class McpResource:
    uri: str
    name: str
    description: str
    mime_type: str
    handler: Callable[[], str]


@dataclass(frozen=True, slots=True)
class McpPromptArgument:
    name: str
    description: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class McpPrompt:
    name: str
    description: str
    arguments: tuple[McpPromptArgument, ...]
    handler: Callable[[dict[str, str]], str]


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class McpServer:
    def __init__(
        self,
        name: str,
        version: str,
        tools: Iterable[McpTool] = (),
        resources: Iterable[McpResource] = (),
        prompts: Iterable[McpPrompt] = (),
    ) -> None:
        self.name = name
        self.version = version
        self._tools: list[McpTool] = []
        self._tool_by_name: dict[str, McpTool] = {}
        self._resources: list[McpResource] = []
        self._resource_by_uri: dict[str, McpResource] = {}
        self._prompts: list[McpPrompt] = []
        self._prompt_by_name: dict[str, McpPrompt] = {}
        for tool in tools:
            self.register(tool)
        for resource in resources:
            self.register_resource(resource)
        for prompt in prompts:
            self.register_prompt(prompt)

    @property
    def tools(self) -> tuple[McpTool, ...]:
        return tuple(self._tools)

    @property
    def resources(self) -> tuple[McpResource, ...]:
        return tuple(self._resources)

    @property
    def prompts(self) -> tuple[McpPrompt, ...]:
        return tuple(self._prompts)

    def register(self, tool: McpTool) -> None:
        if not tool.name:
            raise ValueError("工具名称不能为空")
        if tool.name in self._tool_by_name:
            raise ValueError(f"工具重复注册：{tool.name}")
        self._tools.append(tool)
        self._tool_by_name[tool.name] = tool

    def register_resource(self, resource: McpResource) -> None:
        if not resource.uri:
            raise ValueError("资源 URI 不能为空")
        if resource.uri in self._resource_by_uri:
            raise ValueError(f"资源重复注册：{resource.uri}")
        self._resources.append(resource)
        self._resource_by_uri[resource.uri] = resource

    def register_prompt(self, prompt: McpPrompt) -> None:
        if not prompt.name:
            raise ValueError("提示词名称不能为空")
        if prompt.name in self._prompt_by_name:
            raise ValueError(f"提示词重复注册：{prompt.name}")
        seen: set[str] = set()
        for argument in prompt.arguments:
            if not argument.name:
                raise ValueError("提示词参数名称不能为空")
            if argument.name in seen:
                raise ValueError(f"提示词参数重复：{argument.name}")
            seen.add(argument.name)
        self._prompts.append(prompt)
        self._prompt_by_name[prompt.name] = prompt

    def serve(self, instream: BinaryIO | TextIO, outstream: BinaryIO | TextIO) -> None:
        while True:
            try:
                line = instream.readline()
            except UnicodeDecodeError:
                if not self._emit(outstream, self._decode_error()):
                    break
                continue
            except (BrokenPipeError, OSError):
                # 客户端关闭管道属于正常收尾，读取失败按 EOF 结束循环。
                break
            if not line:
                break
            response = self.handle_line(line)
            if response is None:
                continue
            if not self._emit(outstream, response):
                break

    def handle_line(self, line: str | bytes) -> dict[str, Any] | None:
        text = self._decode(line)
        if text is None:
            return self._decode_error()
        if not text.strip():
            return None
        try:
            message = json.loads(text)
        except RecursionError:
            return self._error(None, PARSE_ERROR, "无法解析的 JSON：嵌套层级过深")
        except ValueError:
            return self._error(None, PARSE_ERROR, "无法解析的 JSON")
        return self._handle_message(message)

    def _decode(self, line: str | bytes) -> str | None:
        if isinstance(line, str):
            return line
        try:
            return line.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _decode_error(self) -> dict[str, Any]:
        return self._error(None, PARSE_ERROR, "无法解析的 JSON：编码不是合法的 UTF-8")

    def _emit(self, outstream: BinaryIO | TextIO, payload: dict[str, Any]) -> bool:
        try:
            self._write(outstream, payload)
        except (BrokenPipeError, OSError):
            # 客户端关闭管道属于正常收尾，停止写出。
            return False
        return True

    def _handle_message(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return self._error(None, INVALID_REQUEST, "无效请求：消息必须是 JSON 对象")
        request_id = message.get("id")
        if message.get("jsonrpc") != "2.0":
            return self._error(request_id, INVALID_REQUEST, "无效请求：jsonrpc 必须为 2.0")
        method = message.get("method")
        if not isinstance(method, str) or not method:
            return self._error(request_id, INVALID_REQUEST, "无效请求：method 必须为非空字符串")
        if method == "notifications/initialized":
            return None
        if "id" not in message:
            if method.startswith("notifications/"):
                return None
            return self._error(None, INVALID_REQUEST, "无效请求：缺少 id")
        try:
            result = self._dispatch(method, message.get("params"))
        except JsonRpcError as error:
            return self._error(request_id, error.code, error.message)
        except Exception:
            return self._error(request_id, INTERNAL_ERROR, "服务器内部错误")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: Any) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize()
        if method == "tools/list":
            return self._list_tools()
        if method == "tools/call":
            return self._call_tool(params)
        if method == "resources/list":
            return self._list_resources()
        if method == "resources/read":
            return self._read_resource(params)
        if method == "prompts/list":
            return self._list_prompts()
        if method == "prompts/get":
            return self._get_prompt(params)
        raise JsonRpcError(METHOD_NOT_FOUND, f"未知方法：{method}")

    def _initialize(self) -> dict[str, Any]:
        capabilities: dict[str, Any] = {"tools": {"listChanged": False}}
        if self._resources:
            capabilities["resources"] = {"listChanged": False}
        if self._prompts:
            capabilities["prompts"] = {"listChanged": False}
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": capabilities,
            "serverInfo": {"name": self.name, "version": self.version},
        }

    def _list_tools(self) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
                for tool in self._tools
            ]
        }

    def _list_resources(self) -> dict[str, Any]:
        return {
            "resources": [
                {
                    "uri": resource.uri,
                    "name": resource.name,
                    "description": resource.description,
                    "mimeType": resource.mime_type,
                }
                for resource in self._resources
            ]
        }

    def _read_resource(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise JsonRpcError(INVALID_PARAMS, "resources/read 参数必须是 JSON 对象")
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri:
            raise JsonRpcError(INVALID_PARAMS, "resources/read 需要 uri")
        resource = self._resource_by_uri.get(uri)
        if resource is None:
            raise JsonRpcError(INVALID_PARAMS, f"未知资源：{uri}")
        text = self._render(resource.handler, "资源读取失败")
        return {"contents": [{"uri": resource.uri, "mimeType": resource.mime_type, "text": text}]}

    def _list_prompts(self) -> dict[str, Any]:
        return {
            "prompts": [
                {
                    "name": prompt.name,
                    "description": prompt.description,
                    "arguments": [
                        {
                            "name": argument.name,
                            "description": argument.description,
                            "required": argument.required,
                        }
                        for argument in prompt.arguments
                    ],
                }
                for prompt in self._prompts
            ]
        }

    def _get_prompt(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise JsonRpcError(INVALID_PARAMS, "prompts/get 参数必须是 JSON 对象")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise JsonRpcError(INVALID_PARAMS, "prompts/get 需要提示词名称")
        prompt = self._prompt_by_name.get(name)
        if prompt is None:
            raise JsonRpcError(INVALID_PARAMS, f"未知提示词：{name}")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "提示词参数必须是 JSON 对象")
        values = self._prompt_values(prompt, arguments)
        text = self._render(lambda: prompt.handler(values), "提示词生成失败")
        return {
            "description": prompt.description,
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }

    @staticmethod
    def _prompt_values(prompt: McpPrompt, arguments: dict[str, Any]) -> dict[str, str]:
        declared = {argument.name: argument for argument in prompt.arguments}
        for key in arguments:
            if key not in declared:
                raise JsonRpcError(INVALID_PARAMS, f"未知提示词参数：{key}")
        values: dict[str, str] = {}
        for argument in prompt.arguments:
            if argument.name not in arguments:
                if argument.required:
                    raise JsonRpcError(INVALID_PARAMS, f"缺少必填参数：{argument.name}")
                continue
            value = arguments[argument.name]
            if not isinstance(value, str):
                raise JsonRpcError(INVALID_PARAMS, f"参数 {argument.name} 类型必须是字符串")
            values[argument.name] = value
        return values

    @staticmethod
    def _render(handler: Callable[[], str], failure: str) -> str:
        try:
            text = handler()
        except Exception as error:
            detail = str(error) or type(error).__name__
            raise JsonRpcError(INTERNAL_ERROR, f"{failure}：{detail}") from None
        if not isinstance(text, str):
            raise JsonRpcError(INTERNAL_ERROR, f"{failure}：处理结果不是文本")
        return text

    def _call_tool(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise JsonRpcError(INVALID_PARAMS, "tools/call 参数必须是 JSON 对象")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise JsonRpcError(INVALID_PARAMS, "tools/call 需要工具名称")
        tool = self._tool_by_name.get(name)
        if tool is None:
            raise JsonRpcError(INVALID_PARAMS, f"未知工具：{name}")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "工具参数必须是 JSON 对象")
        try:
            data = tool.handler(arguments)
            text = json.dumps(data, ensure_ascii=False, allow_nan=False)
        except Exception as error:
            detail = str(error) or type(error).__name__
            message = f"工具执行失败：{detail}"
            return {
                "content": [{"type": "text", "text": message}],
                "structuredContent": {"error": {"code": "tool_error", "message": message}},
                "isError": True,
            }
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": data,
            "isError": False,
        }

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _write(outstream: BinaryIO | TextIO, payload: dict[str, Any]) -> None:
        try:
            line = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        except (ValueError, RecursionError):
            fallback = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": INTERNAL_ERROR, "message": "响应序列化失败"},
            }
            line = json.dumps(fallback, ensure_ascii=False, allow_nan=False) + "\n"
        try:
            outstream.write(line)
        except TypeError:
            outstream.write(line.encode("utf-8"))
        outstream.flush()
