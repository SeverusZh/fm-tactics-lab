"""stdio MCP sidecar for the FM Tactics Lab agent interface."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import sys
import threading
import time
from pathlib import Path
from urllib import parse as urlparse

from . import __version__, schemas
from .client import API, AgentError, Client, default_data_dir, expand_seeds
from .drafts import DraftService

SERVER_NAME = schemas.SERVER_NAME
PROTOCOL_VERSIONS = schemas.PROTOCOL_VERSIONS
LATEST_PROTOCOL = schemas.LATEST_PROTOCOL
CAREER_TERMINAL = ("complete", "error", "empty", "cancelled")
MAX_WAIT_SECONDS = 300.0
MAX_TEXT_CHARS = 2048
RUN_PAGE_SIZE = 200
EXPORT_SUBDIR = ("agent", "exports")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APP_ERROR = -32000
RESOURCE_NOT_FOUND = -32002

BASE_CSV_COLUMNS = [
    "mode", "variant", "seed", "home_goals", "away_goals", "shots",
    "shots_on_target", "xg", "possession", "passes", "completed_passes",
    "elapsed_seconds", "attempts", "log",
]
CAREER_CSV_COLUMNS = ["opponent_key", "venue", "tested_side"]
EVENT_CSV_COLUMNS = ["goals", "cards"]


class JsonRpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class RequestContext:
    __slots__ = ("request_id", "progress_token", "cancelled")

    def __init__(self, request_id, progress_token=None):
        self.request_id = request_id
        self.progress_token = progress_token
        self.cancelled = threading.Event()


def validate_arguments(schema, arguments):
    """Raise AgentError when tool arguments do not satisfy the input schema."""
    if not isinstance(arguments, dict):
        raise AgentError("validation_failed", "工具参数必须是 JSON 对象")
    _validate_object(schema, arguments, "")
    choices = schema.get("oneOf") if isinstance(schema, dict) else None
    if choices:
        for choice in choices:
            try:
                _validate_object(choice, arguments, "")
                return
            except AgentError:
                continue
        raise AgentError("validation_failed", "工具参数不满足必需的字段组合")


def _validate_object(schema, value, prefix):
    properties = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in value:
            raise AgentError("validation_failed", f"缺少必填参数：{prefix}{key}")
    for key, item in value.items():
        subschema = properties.get(key)
        if isinstance(subschema, dict):
            _validate_value(subschema, item, prefix + key)


def _validate_value(schema, value, label):
    choices = schema.get("oneOf") or schema.get("anyOf")
    if choices:
        for choice in choices:
            try:
                _validate_value(choice, value, label)
                return
            except AgentError:
                continue
        raise AgentError("validation_failed", f"参数 {label} 不匹配允许的结构")
    allowed = schema.get("enum")
    if allowed is not None and value not in allowed:
        raise AgentError("validation_failed", f"参数 {label} 必须是 {'、'.join(map(str, allowed))} 之一")
    expected = schema.get("type")
    if expected:
        _check_type(expected, value, label)
    if isinstance(value, str):
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            raise AgentError("validation_failed", f"参数 {label} 长度不能小于 {minimum}")
        pattern = schema.get("pattern")
        if pattern and not re.fullmatch(pattern, value):
            raise AgentError("validation_failed", f"参数 {label} 格式无效")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise AgentError("validation_failed", f"参数 {label} 不能小于 {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            raise AgentError("validation_failed", f"参数 {label} 不能大于 {maximum}")
        multiple = schema.get("multipleOf")
        if multiple and value % multiple:
            raise AgentError("validation_failed", f"参数 {label} 必须是 {multiple} 的倍数")
    elif isinstance(value, list):
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            raise AgentError("validation_failed", f"参数 {label} 至少需要 {minimum} 项")
        maximum = schema.get("maxItems")
        if maximum is not None and len(value) > maximum:
            raise AgentError("validation_failed", f"参数 {label} 最多允许 {maximum} 项")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise AgentError("validation_failed", f"参数 {label} 不能包含重复项")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _validate_value(items, item, f"{label}[{index}]")
    elif isinstance(value, dict):
        _validate_object(schema, value, label + ".")


def _check_type(expected, value, label):
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
    }
    check = checks.get(expected)
    if check is not None and not check(value):
        raise AgentError("validation_failed", f"参数 {label} 类型必须是 {expected}")


def _truncate(text):
    text = str(text)
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[: MAX_TEXT_CHARS - 16] + "…（已截断）"


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _compact(value):
    return json.dumps(value if value is not None else [], ensure_ascii=False, separators=(",", ":"))


def _score(run):
    result = run.get("result") or {}
    score = result.get("score") or []
    if len(score) >= 2:
        return score[0], score[1]
    return None, None


def _metrics_by_variant(runs):
    groups = {}
    for run in runs:
        variant = run.get("variant") or "B"
        entry = groups.setdefault(variant, {
            "n": 0, "wins": 0, "draws": 0, "losses": 0,
            "goals_for": 0, "goals_against": 0, "points": 0,
        })
        entry["n"] += 1
        goals_for, goals_against = _score(run)
        if isinstance(goals_for, int) and isinstance(goals_against, int):
            entry["goals_for"] += goals_for
            entry["goals_against"] += goals_against
            if goals_for > goals_against:
                entry["wins"] += 1
                entry["points"] += 3
            elif goals_for == goals_against:
                entry["draws"] += 1
                entry["points"] += 1
            else:
                entry["losses"] += 1
    for entry in groups.values():
        entry["win_rate"] = round(entry["wins"] / entry["n"], 4) if entry["n"] else None
        entry["win_interval"] = None
    return groups


def _scorelines(runs):
    values = {}
    for run in runs:
        variant = run.get("variant") or "B"
        goals_for, goals_against = _score(run)
        key = f"{goals_for}-{goals_against}" if goals_for is not None else "unknown"
        bucket = values.setdefault(variant, {})
        bucket[key] = bucket.get(key, 0) + 1
    return {"scorelines": values}


def _paired_metrics(runs):
    pairs = {}
    for run in runs:
        seed = run.get("seed")
        variant = run.get("variant") or "B"
        pairs.setdefault(seed, {})[variant] = _score(run)
    diffs = []
    for values in pairs.values():
        baseline = values.get("A")
        current = values.get("B")
        if not baseline or not current:
            continue
        if None in baseline or None in current:
            continue
        diffs.append((current[0] - current[1]) - (baseline[0] - baseline[1]))
    return {
        "n": len(diffs),
        "goal_difference_delta": round(sum(diffs) / len(diffs), 4) if diffs else None,
    }


class McpServer:
    def __init__(self, data_dir=None, base_url=None, token=None, timeout=120.0,
                 stdin=None, stdout=None, stderr=None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.base_url = base_url
        self.token = token
        self.timeout = float(timeout)
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.client = None
        self.draft_service = None
        self.exit_code = 0
        self._closing = False
        self._write_lock = threading.Lock()
        self._lock = threading.Lock()
        self._requests = {}
        self._local = threading.local()
        self._handlers = {
            "lab_status": self._tool_lab_status,
            "engine_select": self._tool_engine_select,
            "draft_create": self._tool_draft_create,
            "draft_get": self._tool_draft_get,
            "draft_edit": self._tool_draft_edit,
            "draft_validate": self._tool_draft_validate,
            "draft_list": self._tool_draft_list,
            "draft_delete": self._tool_draft_delete,
            "career_import": self._tool_career_import,
            "career_status": self._tool_career_status,
            "career_team": self._tool_career_team,
            "career_opponents": self._tool_career_opponents,
            "career_preview": self._tool_career_preview,
            "career_cancel": self._tool_career_cancel,
            "experiment_run": self._tool_experiment_run,
            "career_run": self._tool_career_run,
            "job_get": self._tool_job_get,
            "job_wait": self._tool_job_wait,
            "job_list": self._tool_job_list,
            "job_action": self._tool_job_action,
            "results_summary": self._tool_results_summary,
            "results_matches": self._tool_results_matches,
            "results_csv": self._tool_results_csv,
            "fmf_import": self._tool_fmf_import,
            "fmf_export": self._tool_fmf_export,
            "setpiece_export": self._tool_setpiece_export,
        }

    # Transport

    def serve(self):
        self._log(f"{SERVER_NAME} 已启动")
        while not self._closing:
            line = self.stdin.readline()
            if not line:
                break
            self._handle_line(line)
        self._log(f"{SERVER_NAME} 退出")
        return self.exit_code

    def _handle_line(self, line):
        try:
            message = json.loads(line)
        except ValueError:
            self._write({"jsonrpc": "2.0", "id": None,
                         "error": {"code": PARSE_ERROR, "message": "无法解析的 JSON"}})
            return
        if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
                or not isinstance(message.get("method"), str)):
            request_id = message.get("id") if isinstance(message, dict) else None
            self._write({"jsonrpc": "2.0", "id": request_id,
                         "error": {"code": INVALID_REQUEST, "message": "无效请求"}})
            return
        method = message["method"]
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "notifications/cancelled":
            self._cancel_request(params)
            return
        if method == "notifications/initialized":
            self._log("客户端完成初始化")
            return
        if "id" not in message:
            if method.startswith("notifications/"):
                return
            self._write({"jsonrpc": "2.0", "id": None,
                         "error": {"code": INVALID_REQUEST, "message": "请求缺少 id"}})
            return
        if method == "initialize":
            try:
                result = self._initialize(params)
            except JsonRpcError as error:
                self._write_error(message["id"], error)
            else:
                self._write({"jsonrpc": "2.0", "id": message["id"], "result": result})
            return
        context = RequestContext(message["id"], (params.get("_meta") or {}).get("progressToken"))
        with self._lock:
            self._requests[message["id"]] = context
        thread = threading.Thread(target=self._dispatch, args=(message, context),
                                  name=f"mcp-{method}", daemon=True)
        thread.start()

    def _dispatch(self, message, context):
        self._local.context = context
        try:
            params = message.get("params")
            if not isinstance(params, dict):
                params = {}
            result = self._invoke(message["method"], params)
            self._write({"jsonrpc": "2.0", "id": message["id"], "result": result})
        except JsonRpcError as error:
            self._write_error(message["id"], error)
        except AgentError as error:
            self._write_error(message["id"], JsonRpcError(INTERNAL_ERROR, str(error), error.to_dict()))
        except Exception as error:
            self._log(f"请求处理失败：{error!r}")
            self._write_error(message["id"], JsonRpcError(INTERNAL_ERROR, "内部错误", {"message": str(error)}))
        finally:
            with self._lock:
                self._requests.pop(message["id"], None)
            self._local.context = None

    def _invoke(self, method, params):
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": schemas.TOOLS}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "resources/list":
            return {"resources": schemas.RESOURCES}
        if method == "resources/templates/list":
            return {"resourceTemplates": schemas.RESOURCE_TEMPLATES}
        if method == "resources/read":
            return self._read_resource(params.get("uri"))
        if method == "prompts/list":
            return {"prompts": schemas.PROMPTS}
        if method == "prompts/get":
            return self._get_prompt(params)
        if method == "logging/setLevel":
            return {}
        raise JsonRpcError(METHOD_NOT_FOUND, f"未知方法：{method}")

    def _write(self, payload):
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            try:
                self.stdout.write(line + "\n")
                self.stdout.flush()
            except (BrokenPipeError, OSError):
                self._closing = True

    def _write_error(self, request_id, error):
        value = {"code": error.code, "message": error.message}
        if error.data is not None:
            value["data"] = error.data
        self._write({"jsonrpc": "2.0", "id": request_id, "error": value})

    def _notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _log(self, message):
        try:
            self.stderr.write(f"[{SERVER_NAME}] {message}\n")
            self.stderr.flush()
        except (BrokenPipeError, OSError):
            pass

    def _cancel_request(self, params):
        request_id = params.get("requestId")
        with self._lock:
            context = self._requests.get(request_id)
        if context is None:
            return
        context.cancelled.set()
        self._log(f"取消请求 {request_id}")

    # Discovery

    def _ensure_client(self):
        if self.client is None:
            try:
                self.client = self._new_client()
            except AgentError as error:
                path = (error.details or {}).get("path") or str(self.data_dir / "agent" / "endpoint.json")
                raise AgentError(
                    "app_unavailable",
                    "应用未运行或发现文件缺失，请启动 FM Tactics Lab 后重试",
                    {"endpoint": path},
                    retriable=True,
                ) from None
        return self.client

    def _new_client(self):
        if self.base_url:
            return Client(data_dir=self.data_dir, base_url=self.base_url, token=self.token,
                          timeout=self.timeout)
        return Client(data_dir=self.data_dir, timeout=self.timeout)

    def _with_client(self, operation, retry=True):
        client = self._ensure_client()
        try:
            return operation(client)
        except AgentError as error:
            if error.code != "app_unavailable":
                raise
            changed = False
            try:
                changed = client.refresh()
            except AgentError:
                changed = False
            if not retry or not changed:
                raise
            return operation(client)

    def _drafts(self, client):
        data_dir = Path(getattr(client, "data_dir", None) or self.data_dir)
        service = self.draft_service
        if service is None or service.data_dir != data_dir:
            service = DraftService(client, data_dir=data_dir)
            self.draft_service = service
        return service

    def _context(self):
        return getattr(self._local, "context", None)

    # Initialize

    def _initialize(self, params):
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else LATEST_PROTOCOL
        result = {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
                "logging": {},
            },
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": (
                "FM Tactics Lab 本机接入层。先用 lab_status 检查应用与引擎，"
                "再用 draft_* 准备场景、experiment_run 或 career_run 提交批次，"
                "job_wait 等待结果，results_summary 读取汇总，results_csv 导出明细。"
            ),
        }
        try:
            manifest = self._with_client(lambda client: client.manifest())
        except AgentError as error:
            if error.code == "app_unavailable":
                self._log("应用当前不可用，工具调用时重试")
            else:
                self._log(f"读取清单失败：{error.code}: {error.message}")
            return result
        api = str(manifest.get("api") or "")
        if not api.startswith(API):
            self.exit_code = 1
            self._closing = True
            raise JsonRpcError(INTERNAL_ERROR, f"应用 API 不兼容：{api}", {"expected": API})
        self._log(f"应用就绪：{manifest.get('server_version')} / {api}")
        return result

    # Tools

    def _call_tool(self, params):
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise JsonRpcError(INVALID_PARAMS, "tools/call 需要工具名称")
        tool = schemas.TOOL_BY_NAME.get(name)
        if tool is None:
            raise JsonRpcError(INVALID_PARAMS, f"未知工具：{name}")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        try:
            validate_arguments(tool["inputSchema"], arguments)
            data = self._handlers[name](arguments)
            return {
                "content": [{"type": "text", "text": self._summary(name, data)}],
                "structuredContent": data,
            }
        except JsonRpcError:
            raise
        except AgentError as error:
            return {
                "content": [{"type": "text", "text": _error_text(error)}],
                "isError": True,
                "structuredContent": {"error": error.to_dict()},
            }
        except Exception as error:
            wrapped = AgentError("internal_error", f"工具执行失败：{error}")
            return {
                "content": [{"type": "text", "text": _error_text(wrapped)}],
                "isError": True,
                "structuredContent": {"error": wrapped.to_dict()},
            }

    def _summary(self, name, data):
        if not isinstance(data, dict):
            return _truncate(json.dumps(data, ensure_ascii=False))
        if name == "lab_status":
            manifest = data.get("manifest") or {}
            engine = data.get("engine") or {}
            compatible = "是" if engine.get("compatible") else "否"
            return _truncate(
                f"应用 {manifest.get('api') or '?'} / 版本 {manifest.get('server_version') or '?'}；"
                f"引擎兼容={compatible}；活动任务={data.get('active_job') or '无'}；"
                f"存档活动={data.get('save_active') or '无'}"
            )
        if name == "draft_create":
            return f"已创建草案 {data.get('draft_id')}"
        if name == "draft_edit":
            return f"草案 {data.get('draft_id')} 已更新"
        if name == "draft_validate":
            state = "通过" if data.get("valid") else "失败"
            return f"草案 {data.get('draft_id')} 校验{state}"
        if name == "draft_list":
            drafts = data.get("drafts") or []
            return f"共 {len(drafts)} 个草案"
        if name == "draft_delete":
            return f"已删除草案 {data.get('draft_id')}"
        if name in ("experiment_run", "career_run"):
            return f"已提交任务 {data.get('job_id')}，共 {data.get('total')} 场"
        if name == "job_wait":
            extras = ""
            if data.get("timed_out"):
                extras += "，已超时"
            if data.get("stopped"):
                extras += "，已停止等待"
            return (f"任务 {data.get('id') or data.get('job_id')} 状态 {data.get('status')}，"
                    f"完成 {data.get('completed')}/{data.get('total')}{extras}")
        if name == "job_action":
            return f"任务 {data.get('job_id')} 操作 {data.get('action')} 已提交"
        if name == "results_summary":
            return f"任务 {data.get('job_id')} 状态 {data.get('status')}，汇总 {len(data.get('metrics') or {})} 个方案"
        if name == "results_csv":
            return f"CSV 已写入 {data.get('path')}，{data.get('rows')} 行"
        if name == "career_import":
            return f"存档 {data.get('save_id')} 状态 {data.get('status')}"
        return _truncate(json.dumps(data, ensure_ascii=False))

    def _tool_lab_status(self, args):
        def operation(client):
            status = client.status()
            return {
                "manifest": client.manifest(),
                "engine": status.get("engine_compatibility"),
                "active_job": status.get("active_job"),
                "save_active": status.get("save_active"),
            }
        return self._with_client(operation)

    def _tool_engine_select(self, args):
        return self._with_client(lambda client: client.engine_select(args["game_root"]), retry=False)

    def _tool_draft_create(self, args):
        source = args["source"]
        keys = ("save_id", "club_uid", "tactic_index", "lineup", "bench", "side",
                "file_base64", "file_path", "base_scenario", "base_draft_id", "job_id",
                "variant", "scenario")
        extra = {key: args[key] for key in keys if key in args}

        def operation(client):
            summary = self._drafts(client).create(source=source, name=args.get("name"), **extra)
            return {"draft_id": summary["draft_id"], "draft": summary}
        return self._with_client(operation)

    def _tool_draft_get(self, args):
        def operation(client):
            return self._drafts(client).get(
                args["draft_id"], include_scenario=bool(args.get("include_scenario", False)))
        return self._with_client(operation)

    def _tool_draft_edit(self, args):
        draft_id = args["draft_id"]
        op = args["op"]
        extra = {key: value for key, value in args.items() if key not in ("draft_id", "op")}
        return self._with_client(lambda client: self._drafts(client).edit(draft_id, op, **extra))

    def _tool_draft_validate(self, args):
        return self._with_client(lambda client: self._drafts(client).validate(args["draft_id"]))

    def _tool_draft_list(self, args):
        return self._with_client(lambda client: {"drafts": self._drafts(client).list()})

    def _tool_draft_delete(self, args):
        return self._with_client(lambda client: self._drafts(client).delete(args["draft_id"]))

    def _tool_career_import(self, args):
        save_path = args["save_path"]
        accepted = self._with_client(lambda client: client.career_import(save_path), retry=False)
        save_id = accepted.get("save_id") or accepted.get("id")
        result = {"save_id": save_id, "reused": accepted.get("reused")}
        if bool(args.get("wait", False)) and save_id:
            status = self._wait_career(save_id, float(args.get("timeout_seconds", 60)))
            result["status"] = status.get("status")
            result["progress"] = status
            result["timed_out"] = bool(status.get("timed_out"))
        else:
            result["status"] = accepted.get("status") or "reading"
            result["timed_out"] = False
        return result

    def _tool_career_status(self, args):
        return self._with_client(lambda client: client.career_status(args.get("save_id")))

    def _tool_career_team(self, args):
        save_id = args["save_id"]
        club_uid = int(args["club_uid"])
        return self._with_client(lambda client: client.career_team(save_id, club_uid))

    def _tool_career_opponents(self, args):
        save_id = args["save_id"]
        club_uid = int(args["club_uid"])
        accepted = self._with_client(
            lambda client: client.career_opponents(save_id, club_uid), retry=False)
        result = {
            "save_id": save_id,
            "club_uid": club_uid,
            "status": accepted.get("status") or "reading",
            "opponents": accepted.get("opponents"),
            "reading": accepted.get("reading"),
            "timed_out": False,
        }
        if bool(args.get("wait", False)) and result["status"] not in ("complete", "error"):
            report = self._wait_opponents(save_id, club_uid, float(args.get("timeout_seconds", 60)))
            result.update(report)
        return result

    def _tool_career_preview(self, args):
        save_id = args["save_id"]
        club_uid = int(args["club_uid"])
        key = args["key"]

        def operation(client):
            scenario = self._drafts(client).scenario(args["draft_id"])
            return client.career_preview(save_id, club_uid, key, scenario)
        return self._with_client(operation)

    def _tool_career_cancel(self, args):
        kind = args["kind"]
        save_id = args["save_id"]
        if kind == "import":
            return self._with_client(lambda client: client.career_import_cancel(save_id), retry=False)
        if kind == "opponents" and args.get("club_uid") is not None:
            club_uid = int(args["club_uid"])
            return self._with_client(
                lambda client: client.career_opponents_cancel(save_id, club_uid), retry=False)
        raise AgentError("validation_failed", "取消对手扫描需要 club_uid")

    def _tool_experiment_run(self, args):
        draft_id = args["draft_id"]
        baseline_id = args.get("baseline_draft_id")
        seeds = expand_seeds(args["seeds"])
        workers = args.get("workers")
        event_details = bool(args.get("event_details", True))
        name = args.get("name")

        def operation(client):
            drafts = self._drafts(client)
            scenario = drafts.scenario(draft_id)
            reference = drafts.scenario(baseline_id) if baseline_id else None
            created = client.run(scenario, reference=reference, seeds=seeds, workers=workers,
                                 event_details=event_details, name=name)
            return {
                "job_id": created.get("id"),
                "total": created.get("total"),
                "workers": created.get("workers", workers or 1),
            }
        return self._with_client(operation, retry=False)

    def _tool_career_run(self, args):
        save_id = args["save_id"]
        club_uid = int(args["club_uid"])
        opponents = []
        for item in args["opponents"]:
            opponents.append(item.get("key") if isinstance(item, dict) else item)
        baseline_id = args.get("baseline_draft_id")
        workers = args.get("workers")
        event_details = bool(args.get("event_details", True))
        name = args.get("name")
        count = int(args["count"])
        first_seed = int(args["first_seed"])

        def operation(client):
            drafts = self._drafts(client)
            scenario = drafts.scenario(args["draft_id"])
            reference = drafts.scenario(baseline_id) if baseline_id else None
            created = client.career_run(save_id, club_uid, scenario, opponents, count, first_seed,
                                        reference=reference, workers=workers,
                                        event_details=event_details, name=name)
            return {
                "job_id": created.get("id"),
                "total": created.get("total"),
                "workers": created.get("workers", workers or 1),
            }
        return self._with_client(operation, retry=False)

    def _tool_job_get(self, args):
        return self._with_client(lambda client: client.job(
            args["job_id"],
            runs_offset=args.get("runs_offset"),
            runs_limit=args.get("runs_limit"),
            variant=args.get("variant"),
        ))

    def _tool_job_wait(self, args):
        job_id = args["job_id"]
        timeout = min(max(_number(args.get("timeout_seconds", 60)), 0.0), MAX_WAIT_SECONDS)
        poll = max(0.05, _number(args.get("poll_ms", 1000)) / 1000.0)
        context = self._context()
        token = context.progress_token if context is not None else None
        should_stop = context.cancelled.is_set if context is not None else None

        def on_progress(job):
            if token is None:
                return
            params = {
                "progressToken": token,
                "progress": int(job.get("completed") or 0),
                "total": int(job.get("total") or 0),
            }
            if job.get("status"):
                params["message"] = job["status"]
            self._notify("notifications/progress", params)

        self._notify("notifications/message", {
            "level": "info",
            "logger": SERVER_NAME,
            "data": {"job_id": job_id, "event": "wait_started", "timeout_seconds": timeout},
        })
        return self._with_client(lambda client: client.wait_job(
            job_id, timeout=timeout, poll=poll, on_progress=on_progress,
            should_stop=should_stop,
        ))

    def _tool_job_list(self, args):
        return self._with_client(lambda client: client.jobs(
            limit=int(args.get("limit", 50)),
            offset=int(args.get("offset", 0)),
            status=args.get("status"),
        ))

    def _tool_job_action(self, args):
        job_id = args["job_id"]
        action = args["action"]
        if action == "cancel":
            response = self._with_client(lambda client: client.cancel(job_id), retry=False)
        elif action == "resume":
            workers = args.get("workers")
            response = self._with_client(
                lambda client: client.resume(job_id, workers=workers), retry=False)
        elif action == "delete":
            response = self._with_client(lambda client: client.delete(job_id), retry=False)
        else:
            name = args.get("name")
            if not isinstance(name, str) or not name.strip():
                raise AgentError("validation_failed", "重命名任务需要非空 name")
            response = self._with_client(
                lambda client: client.rename(job_id, name.strip()), retry=False)
        if not isinstance(response, dict):
            response = {"result": response}
        response = dict(response)
        response["job_id"] = job_id
        response["action"] = action
        return response

    def _tool_results_summary(self, args):
        job = self._with_client(lambda client: self._fetch_job(client, args["job_id"]))
        runs = job.get("runs") or []
        metrics = job.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            metrics = _metrics_by_variant(runs)
        paired = job.get("paired")
        if not isinstance(paired, dict) or not paired.get("n"):
            paired = _paired_metrics(runs)
        failures = job.get("failures") or []
        elapsed = round(sum(_number(run.get("elapsed_seconds")) for run in runs), 3)
        native_elapsed = round(sum(_number(run.get("native_elapsed_seconds")) for run in runs), 3)
        timings = {
            "runs": len(runs),
            "elapsed_seconds": elapsed,
            "native_elapsed_seconds": native_elapsed,
            "average_elapsed_seconds": round(elapsed / len(runs), 3) if runs else None,
        }
        return {
            "job_id": job.get("id") or args["job_id"],
            "status": job.get("status"),
            "metrics": metrics,
            "distributions": _scorelines(runs),
            "paired": paired,
            "failures": {
                "count": len(failures),
                "items": failures[:20],
                "truncated": len(failures) > 20,
            },
            "timings": timings,
        }

    def _tool_results_matches(self, args):
        job_id = args["job_id"]
        variant = args.get("variant")
        seed = args.get("seed")
        include_events = bool(args.get("include_events", False))
        if seed is not None:
            run = self._with_client(
                lambda client: self._find_run(client, job_id, int(seed), variant))
            return {"job_id": job_id, "seed": seed, "found": run is not None, "run": run}
        limit = int(args.get("limit", 50))
        offset = int(args.get("offset", 0))
        detail = self._with_client(lambda client: client.job(
            job_id, runs_offset=offset, runs_limit=limit, variant=variant))
        runs = list(detail.get("runs") or [])
        if not include_events:
            for run in runs:
                run.pop("events", None)
        total = int(detail.get("runs_total") or len(runs))
        next_offset = offset + len(runs)
        return {
            "job_id": job_id,
            "runs": runs,
            "runs_total": total,
            "runs_offset": offset,
            "runs_limit": limit,
            "next_offset": next_offset if next_offset < total else None,
        }

    def _tool_results_csv(self, args):
        job_id = args["job_id"]

        def operation(client):
            job = self._fetch_job(client, job_id)
            columns = _csv_columns(job)
            rows = _csv_rows(job, columns)
            target = _export_target(client.data_dir, job_id, args.get("out"))
            sha256, count = _write_csv(target, columns, rows)
            return {
                "job_id": job_id,
                "path": str(target),
                "sha256": sha256,
                "rows": count,
                "columns": columns,
            }
        return self._with_client(operation)

    def _tool_fmf_import(self, args):
        draft_id = args["draft_id"]
        side = int(args["side"])
        file_base64 = args.get("file_base64")
        if file_base64 is None:
            try:
                file_base64 = base64.b64encode(
                    Path(args["file_path"]).expanduser().read_bytes()).decode("ascii")
            except OSError as error:
                raise AgentError("validation_failed", f"无法读取 FMF 文件：{error}") from None

        def operation(client):
            service = self._drafts(client)
            imported = client.fmf_import(side, service.scenario(draft_id), file_base64)
            scenario = imported.get("scenario")
            summary = service.replace_scenario(draft_id, scenario) if isinstance(scenario, dict) else service.get(draft_id)
            return {
                "draft_id": draft_id,
                "summary": summary,
                "report": imported.get("report"),
            }
        return self._with_client(operation, retry=False)

    def _tool_fmf_export(self, args):
        draft_id = args["draft_id"]
        side = int(args["side"])
        name = args.get("name")

        def operation(client):
            scenario = self._drafts(client).scenario(draft_id)
            exported = client.fmf_export(side, scenario, name=name)
            return {
                "draft_id": draft_id,
                "filename": exported.get("filename"),
                "path": exported.get("path"),
                "sha256": exported.get("sha256"),
                "report": exported.get("report"),
            }
        return self._with_client(operation, retry=False)

    def _tool_setpiece_export(self, args):
        draft_id = args["draft_id"]
        side = int(args["side"])
        setpiece_type = int(args["type"])
        variant = int(args["variant"])

        def operation(client):
            scenario = self._drafts(client).scenario(draft_id)
            exported = client.setpiece_export(side, scenario, setpiece_type, variant)
            return {
                "draft_id": draft_id,
                "filename": exported.get("filename"),
                "path": exported.get("path"),
                "sha256": exported.get("sha256"),
                "report": exported.get("report"),
            }
        return self._with_client(operation, retry=False)

    # Waiting helpers

    def _wait_career(self, save_id, timeout):
        deadline = time.monotonic() + max(0.0, timeout)
        status = {}
        while True:
            status = dict(self._with_client(lambda client: client.career_status(save_id)))
            if status.get("status") in CAREER_TERMINAL:
                status["timed_out"] = False
                return status
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status["timed_out"] = True
                return status
            time.sleep(min(0.5, remaining))

    def _wait_opponents(self, save_id, club_uid, timeout):
        deadline = time.monotonic() + max(0.0, timeout)
        report = {}
        while True:
            report = dict(self._with_client(
                lambda client: client.career_opponents(save_id, club_uid), retry=False))
            report["timed_out"] = False
            if report.get("status") in ("complete", "error"):
                return report
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                report["timed_out"] = True
                return report
            time.sleep(min(0.5, remaining))

    # Job helpers

    def _fetch_job(self, client, job_id, variant=None):
        detail = client.job(job_id, runs_offset=0, runs_limit=RUN_PAGE_SIZE, variant=variant)
        runs = list(detail.get("runs") or [])
        total = int(detail.get("runs_total") or len(runs))
        offset = len(runs)
        guard = 0
        while len(runs) < total and guard < 100:
            chunk = client.job(job_id, runs_offset=offset, runs_limit=RUN_PAGE_SIZE,
                               variant=variant).get("runs") or []
            if not chunk:
                break
            runs.extend(chunk)
            offset += len(chunk)
            guard += 1
        detail["runs"] = runs
        detail["runs_total"] = max(total, len(runs))
        detail["runs_truncated"] = len(runs) < total
        return detail

    def _find_run(self, client, job_id, seed, variant):
        offset = 0
        while True:
            detail = client.job(job_id, runs_offset=offset, runs_limit=RUN_PAGE_SIZE,
                                variant=variant)
            runs = detail.get("runs") or []
            for run in runs:
                if run.get("seed") == seed:
                    return run
            if not runs:
                return None
            offset += len(runs)
            total = int(detail.get("runs_total") or 0)
            if not detail.get("runs_truncated") or offset >= total:
                return None

    # Resources

    def _read_resource(self, uri):
        if not isinstance(uri, str) or not uri:
            raise JsonRpcError(INVALID_PARAMS, "resources/read 需要 uri")
        try:
            return self._read_resource_value(uri)
        except AgentError as error:
            raise self._resource_error(error) from None

    def _read_resource_value(self, uri):
        parsed = urlparse.urlsplit(uri)
        if parsed.scheme != "fm27":
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"资源不存在：{uri}")
        host = parsed.netloc
        parts = [part for part in parsed.path.split("/") if part]
        if host == "manifest" and not parts:
            return self._resource_json(uri, self._with_client(lambda client: client.manifest()))
        if host == "catalog" and not parts:
            return self._resource_json(uri, self._with_client(lambda client: client.catalog()))
        if host == "status" and not parts:
            return self._resource_json(uri, self._with_client(lambda client: client.status()))
        if host == "drafts" and len(parts) == 1:
            draft_id = parts[0]
            data = self._with_client(
                lambda client: self._drafts(client).get(draft_id, include_scenario=True))
            return self._resource_json(uri, data)
        if host == "jobs" and parts:
            job_id = parts[0]
            if len(parts) == 1:
                data = self._with_client(lambda client: client.job(job_id))
                return self._resource_json(uri, data)
            if len(parts) == 2 and parts[1] == "export":
                data = self._with_client(lambda client: client.job_export(job_id))
                return self._resource_json(uri, data)
            if len(parts) >= 3 and parts[1] == "logs":
                name = _quote("/".join(parts[2:]))
                text = self._with_client(lambda client: client.job_logs(job_id, name))
                return {"contents": [{"uri": uri, "mimeType": "application/jsonl", "text": text}]}
        if host == "saves" and len(parts) == 1:
            data = self._with_client(lambda client: client.career_status(parts[0]))
            return self._resource_json(uri, data)
        raise JsonRpcError(RESOURCE_NOT_FOUND, f"资源不存在：{uri}")

    def _resource_json(self, uri, data):
        return {"contents": [{
            "uri": uri,
            "mimeType": "application/json",
            "text": json.dumps(data, ensure_ascii=False),
        }]}

    def _resource_error(self, error):
        code = {
            "not_found": RESOURCE_NOT_FOUND,
            "app_unavailable": APP_ERROR,
        }.get(error.code, INTERNAL_ERROR)
        return JsonRpcError(code, f"{error.code}: {error.message}", error.to_dict())

    # Prompts

    def _get_prompt(self, params):
        name = params.get("name")
        prompt = schemas.PROMPT_BY_NAME.get(name) if isinstance(name, str) else None
        if prompt is None:
            raise JsonRpcError(INVALID_PARAMS, f"未知 prompt：{name}")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        missing = [argument["name"] for argument in prompt["arguments"]
                   if argument.get("required") and not arguments.get(argument["name"])]
        if missing:
            raise JsonRpcError(INVALID_PARAMS, "缺少 prompt 参数：" + "、".join(missing))
        return {
            "description": prompt["description"],
            "messages": [{
                "role": "user",
                "content": {"type": "text", "text": _prompt_text(name, arguments)},
            }],
        }


def _quote(value):
    return urlparse.quote(value, safe="")


def _error_text(error):
    return _truncate(f"{error.code}: {error.message}")


def _prompt_text(name, arguments):
    draft_id = arguments.get("draft_id")
    if name == "test_tactic_change":
        instruction = arguments.get("instruction")
        seeds = arguments.get("seeds") or "101:10"
        return (
            f"对草案 {draft_id} 执行单变量对照实验。变更内容：{instruction}。"
            f"先用 draft_create source=default 建立基线草案并 draft_validate，"
            f"再用 draft_edit draft_id={draft_id} 只应用本次变更并 draft_validate 校验；"
            f"然后 experiment_run draft_id={draft_id} baseline_draft_id=<基线草案> "
            f"seeds={seeds} workers=2 event_details=false，job_wait 到终态后用 "
            f"results_summary 读取 metrics.A/metrics.B 与 paired.goal_difference_delta。"
            f"先跑 2 到 6 场探测，确认方向后再扩到 20 到 100 场。"
        )
    if name == "compare_baseline_vs_current":
        baseline_id = arguments.get("baseline_draft_id")
        seeds = arguments.get("seeds") or "101:10"
        return (
            f"比较基线草案 {baseline_id} 与当前草案 {draft_id}。先 draft_validate 两者，"
            f"再 experiment_run draft_id={draft_id} baseline_draft_id={baseline_id} "
            f"seeds={seeds} event_details=false，job_wait 后读取 results_summary。"
            f"若 paired.n 为 0，说明没有同种子配对，可用 results_matches 逐场核对。"
            f"用 metrics.B.win_rate 与 win_interval 判断变化是否稳定，"
            f"用 paired.goal_difference_delta 判断同种子下的净胜球变化。"
        )
    if name == "opponent_sweep":
        save_id = arguments.get("save_id")
        club_uid = arguments.get("club_uid")
        count = arguments.get("count") or 6
        return (
            f"对存档 {save_id} 的俱乐部 {club_uid} 用草案 {draft_id} 做多对手扫描。"
            f"先 career_import save_path=<存档路径> wait=true 确认导入完成，"
            f"career_team 读取战术列表并 draft_create source=save 建立草案，"
            f"draft_validate 后 career_opponents wait=true 取得对手 key；"
            f"career_preview 逐个预览后 career_run save_id={save_id} club_uid={club_uid} "
            f"draft_id={draft_id} opponents=[key,...] count={count} first_seed=100 workers=2。"
            f"count 为每对手总场数，必须偶数且主客场各半。"
        )
    raise JsonRpcError(INVALID_PARAMS, f"未知 prompt：{name}")


def _csv_columns(job):
    runs = job.get("runs") or []
    mode = str(job.get("mode") or "")
    career = mode == "career" or any(isinstance(run, dict) and
                                     any(key in run for key in CAREER_CSV_COLUMNS)
                                     for run in runs)
    columns = list(BASE_CSV_COLUMNS)
    if career:
        columns.extend(CAREER_CSV_COLUMNS)
    if job.get("event_details"):
        columns.extend(EVENT_CSV_COLUMNS)
    return columns


def _csv_rows(job, columns):
    mode = job.get("mode") or ""
    rows = []
    for run in job.get("runs") or []:
        statistics = run.get("statistics") or {}
        teams = statistics.get("teams") or []
        home = teams[0] if len(teams) > 0 else {}
        away = teams[1] if len(teams) > 1 else {}
        goals_for, goals_against = _score(run)
        events = run.get("events") or {}
        row = {
            "mode": mode,
            "variant": run.get("variant"),
            "seed": run.get("seed"),
            "home_goals": goals_for,
            "away_goals": goals_against,
            "shots": home.get("shots"),
            "shots_on_target": home.get("shots_on_target"),
            "xg": home.get("xg"),
            "possession": home.get("possession"),
            "passes": home.get("passes"),
            "completed_passes": home.get("completed_passes"),
            "elapsed_seconds": run.get("elapsed_seconds"),
            "attempts": run.get("attempts"),
            "log": run.get("log"),
            "opponent_key": run.get("opponent_key"),
            "venue": run.get("venue"),
            "tested_side": run.get("tested_side"),
            "goals": _compact(events.get("goals")),
            "cards": _compact(events.get("cards")),
        }
        rows.append(row)
    return rows


def _export_target(data_dir, job_id, name):
    text = str(name).strip() if name else f"{job_id}.csv"
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise AgentError("validation_failed", "out 必须是 dataDir/agent/exports 下的相对文件名")
    if not relative.suffix:
        relative = relative.with_name(relative.name + ".csv")
    root = Path(data_dir).joinpath(*EXPORT_SUBDIR)
    root.mkdir(parents=True, exist_ok=True)
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise AgentError("validation_failed", "out 不能越出导出目录") from None
    return target


def _write_csv(target, columns, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    data = buffer.getvalue().encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(rows)


def _configure_stdio():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if stream is sys.stdout:
                reconfigure(encoding="utf-8", newline="\n")
            else:
                reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fm27lab mcp", description="启动 fm27lab MCP stdio sidecar")
    parser.add_argument("--data-dir", help="数据目录，默认取 FM27LAB_DATA 或平台默认目录")
    parser.add_argument("--endpoint", help="覆盖服务地址，用于测试")
    parser.add_argument("--token", help="覆盖访问 token")
    parser.add_argument("--timeout", type=float, default=120.0, help="单次 HTTP 超时秒数")
    namespace, _ = parser.parse_known_args(argv)
    _configure_stdio()
    server = McpServer(
        data_dir=namespace.data_dir,
        base_url=namespace.endpoint,
        token=namespace.token,
        timeout=namespace.timeout,
    )
    return server.serve()


if __name__ == "__main__":
    raise SystemExit(main())
