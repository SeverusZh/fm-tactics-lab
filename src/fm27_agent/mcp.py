"""stdio MCP sidecar for the FM Tactics Lab agent interface."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import random
import re
import secrets
import sys
import threading
from pathlib import Path
from urllib import parse as urlparse

from . import __version__, schemas
from .client import API, AgentError, Client, default_data_dir, expand_seeds
from .drafts import DraftService

SERVER_NAME = schemas.SERVER_NAME
PROTOCOL_VERSIONS = schemas.PROTOCOL_VERSIONS
LATEST_PROTOCOL = schemas.LATEST_PROTOCOL
# The app rotates its token on restart; retry once after reloading endpoint.json.
RECONNECT_CODES = ("app_unavailable", "unauthorized")
MAX_WAIT_SECONDS = 300.0
MAX_TEXT_CHARS = 16000
RUN_PAGE_SIZE = 200
EXPORT_SUBDIR = ("agent", "exports")
FREE_MODE_WORKFLOW = """# 自由模式战术对比

1. lab_status 确认引擎兼容且无活动任务，记录 paths。
2. draft_create source=default -> fmf_import 双方 -> draft_validate。
3. 构造受控夹具：draft_get save_scenario=true 取得场景，双方首发属性一致、lineup 相同、位置熟练度满值；draft_create source=inline scenario_path=<文件> 并 draft_validate。
4. 候选用 draft_create source=draft 克隆受控基准，draft_edit ops 批量修改，draft_validate。
5. experiment_run 单草案或 candidates，同种子 200 场，workers 用上限，event_details=false。
6. job_get include_runs=false 看进度与 queue_position；job_wait timeout_seconds<=45；超时按 next_poll_seconds 轮询。
7. results_summary 读单任务；results_compare 读跨任务同种子配对与 95%CI；results_csv 取逐场双方数据。
8. 客队战术池：场景带启用的 away_tactic_pool 时，随机模式按权重逐场抽取，轮战模式按条目顺序轮换；同一任务的 A/B 共享同一分配（同 seed 同客队战术）。轮战模式要求种子数等于条目数乘轮数，results_summary 的 tactic_pool.draws 给出每套出场次数。客队名单支持统一属性或存档真实名单。跨任务比较前先看 results_compare 的 comparable；分配不同会被拒绝配对。
9. 200 场只做筛选；确认需两个独立种子块各 200 场且方向一致；再做消融。
10. fmf_export 导出后重新 fmf_import，静态对比场景并跑同种子 200 场验证逐场一致。
"""


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APP_ERROR = -32000
RESOURCE_NOT_FOUND = -32002

BASE_CSV_COLUMNS = [
    "mode", "variant", "seed", "tactic_pool_entry_index", "tactic_pool_entry_name",
    "home_goals", "away_goals", "shots",
    "shots_on_target", "xg", "possession", "passes", "completed_passes",
    "opponent_shots", "opponent_shots_on_target", "xga", "opponent_possession",
    "opponent_passes", "opponent_completed_passes", "score_changes", "goal_minutes",
    "elapsed_seconds", "attempts", "log",
]
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


def _json_text(data, hint=None):
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= MAX_TEXT_CHARS:
        return text
    value = {
        "truncated": True,
        "chars": len(text),
        "keys": list(data)[:24] if isinstance(data, dict) else [],
        "hint": hint or "结果过大，请使用分页参数或读取运行目录 summary.json",
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _wsl_hint(path):
    text = str(path or "")
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if not match:
        return None
    return "/mnt/" + match.group(1).lower() + "/" + match.group(2).replace("\\", "/")


def _progress_view(job):
    total = job.get("total")
    completed = job.get("completed")
    progress = round(completed / total, 4) if isinstance(total, int) and total else None
    return {
        "id": job.get("id") or job.get("job_id"),
        "name": job.get("name"),
        "status": job.get("status"),
        "mode": job.get("mode"),
        "completed": completed,
        "total": total,
        "progress": progress,
        "queue_position": job.get("queue_position"),
        "eta_seconds": job.get("eta_seconds"),
        "elapsed_seconds": job.get("elapsed_seconds"),
        "matches_per_minute": job.get("matches_per_minute"),
        "active_count": len(job.get("active") or []),
        "failures": len(job.get("failures") or []),
        "error": job.get("error"),
    }


def _engine_profile(engine):
    profile = engine.get("profile") if isinstance(engine, dict) else None
    return profile if isinstance(profile, (dict, str)) else None


def _engine_profile_version(engine):
    profile = _engine_profile(engine)
    if isinstance(profile, dict):
        return profile.get("version")
    return profile if isinstance(profile, str) else None


def _draft_view(draft):
    teams = []
    for team in draft.get("teams") or []:
        teams.append({
            "name": team.get("name"),
            "tactic_name": team.get("tactic_name"),
            "mentality": team.get("mentality"),
            "lineup": team.get("lineup"),
            "players": team.get("players"),
        })
    return {
        "draft_id": draft.get("draft_id"),
        "name": draft.get("name"),
        "source": draft.get("source"),
        "updated_at": draft.get("updated_at"),
        "scenario_schema": draft.get("scenario_schema"),
        "away_tactic_pool": draft.get("away_tactic_pool"),
        "teams": teams,
    }


def _match_view(run):
    teams = (run.get("statistics") or {}).get("teams") or []
    home = teams[0] if len(teams) > 0 else {}
    away = teams[1] if len(teams) > 1 else {}
    goals_for, goals_against = _score(run)
    return {
        "variant": run.get("variant"),
        "seed": run.get("seed"),
        "score": [goals_for, goals_against],
        "xg": home.get("xg"),
        "xga": away.get("xg"),
        "shots": home.get("shots"),
        "sot": home.get("shots_on_target"),
        "poss": home.get("possession"),
        "elapsed_seconds": run.get("elapsed_seconds"),
        "tactic_pool_entry": run.get("tactic_pool_entry"),
    }


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


def _oriented_score(run):
    score = (run.get("result") or {}).get("score") or []
    if len(score) < 2:
        return None, None
    side = run.get("tested_side")
    side = side if side in (0, 1) else 0
    return score[side], score[1 - side]


def _oriented_stats(run):
    teams = (run.get("statistics") or {}).get("teams") or []
    side = run.get("tested_side")
    side = side if side in (0, 1) else 0
    if len(teams) <= side:
        return {}
    return teams[side]


def _compare_metrics(runs):
    n = len(runs)
    if not n:
        return {"n": 0}
    wins = 0
    draws = 0
    goals_for = 0
    goals_against = 0
    points = 0
    xg = 0.0
    xga = 0.0
    shots = 0.0
    shots_on_target = 0.0
    possession = 0.0
    for run in runs:
        gf, ga = _oriented_score(run)
        if gf is None:
            continue
        goals_for += gf
        goals_against += ga
        if gf > ga:
            wins += 1
            points += 3
        elif gf == ga:
            draws += 1
            points += 1
        me = _oriented_stats(run)
        opponent = (run.get("statistics") or {}).get("teams") or []
        other = opponent[1] if run.get("tested_side") in (0, None) else opponent[0]
        xg += _number(me.get("xg"))
        xga += _number(other.get("xg"))
        shots += _number(me.get("shots"))
        shots_on_target += _number(me.get("shots_on_target"))
        possession += _number(me.get("possession"))
    return {
        "n": n,
        "wins": wins,
        "draws": draws,
        "losses": n - wins - draws,
        "win_rate": round(wins / n, 4),
        "points": round(points / n, 4),
        "goals_for": round(goals_for / n, 4),
        "goals_against": round(goals_against / n, 4),
        "xg": round(xg / n, 4),
        "xga": round(xga / n, 4),
        "shots": round(shots / n, 3),
        "shots_on_target": round(shots_on_target / n, 3),
        "possession": round(possession / n, 4),
    }


def _oriented_xgd(run):
    teams = (run.get("statistics") or {}).get("teams") or []
    side = run.get("tested_side")
    side = side if side in (0, 1) else 0
    if len(teams) <= side:
        return 0.0
    return _number(teams[side].get("xg")) - _number(teams[1 - side].get("xg"))


def _bootstrap_ci(values, reps=2000, alpha=0.05, seed=20261108):
    if not values:
        return [None, None]
    rng = random.Random(seed)
    size = len(values)
    means = []
    for _ in range(reps):
        means.append(sum(values[rng.randrange(size)] for _ in range(size)) / size)
    means.sort()
    return [round(means[int(alpha / 2 * reps)], 4),
            round(means[int((1 - alpha / 2) * reps)], 4)]


def _pool_view(job):
    pool = job.get("tactic_pool") if isinstance(job, dict) else None
    if not isinstance(pool, dict) or not pool.get("enabled"):
        return None
    rows = []
    for entry in pool.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        rows.append({"index": entry.get("index"), "name": entry.get("name"),
                     "weight": entry.get("weight"), "probability": entry.get("probability"),
                     "roster": bool(entry.get("roster"))})
    draws = pool.get("draws") if isinstance(pool.get("draws"), dict) else {}
    counts = draws.get("counts") if isinstance(draws.get("counts"), dict) else {}
    for row in rows:
        row["draws"] = int(counts.get(str(row.get("index")), 0))
    return {
        "profile": pool.get("profile"),
        "salt": pool.get("salt"),
        "mode": pool.get("mode", "random"),
        "rounds": pool.get("rounds", 1),
        "players": pool.get("players", "uniform"),
        "uniform": pool.get("uniform"),
        "entries": rows,
        "draws": {"total": draws.get("total"),
                  "counts": {str(row.get("index")): row["draws"] for row in rows}},
    }


def _pool_pairing(baseline, candidate, seeds):
    """Decide whether two jobs paired the same away tactic draw on every shared seed."""
    if baseline is None and candidate is None:
        return True, None, None
    seeds = [seed for seed in seeds if isinstance(seed, int)]
    salts = {"baseline": baseline.get("salt") if baseline else None,
             "candidate": candidate.get("salt") if candidate else None}
    info = {"salts": salts, "common_seeds": len(seeds),
            "draw_mismatches": None, "mismatched_seeds": []}
    if baseline is None or candidate is None:
        if baseline is None:
            reason = "基线任务未使用客队战术池，候选任务使用了客队战术池"
        else:
            reason = "候选任务未使用客队战术池，基线任务使用了客队战术池"
        return False, reason, info
    baseline_mode = (baseline.get("mode") or "random", baseline.get("rounds") or 1,
                     baseline.get("players") or "uniform")
    candidate_mode = (candidate.get("mode") or "random", candidate.get("rounds") or 1,
                      candidate.get("players") or "uniform")
    if baseline_mode != candidate_mode:
        return False, "两个任务的客队战术池模式不同，同种子分配无法对齐", info
    if baseline.get("entries") != candidate.get("entries"):
        return False, "两个任务的客队战术池条目不同，同种子分配无法对齐", info
    if not seeds:
        return False, "没有同种子比赛，无法核对客队战术池分配", info
    missing = [seed for seed in seeds
               if seed not in baseline.get("draws", {}) or seed not in candidate.get("draws", {})]
    if missing:
        info["missing_seeds"] = missing[:20]
        return False, "缺少同种子的客队战术池分配记录，不能配对", info
    mismatched = [seed for seed in seeds
                  if baseline["draws"][seed] != candidate["draws"][seed]]
    info["draw_mismatches"] = len(mismatched)
    info["mismatched_seeds"] = mismatched[:20]
    if mismatched:
        return False, (f"客队战术池分配不同：{len(mismatched)}/{len(seeds)} 个同种子场次"
                       "使用了不同战术"), info
    return True, None, info


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
            "draft_options": self._tool_draft_options,
            "draft_delete": self._tool_draft_delete,
            "experiment_run": self._tool_experiment_run,
            "job_get": self._tool_job_get,
            "job_wait": self._tool_job_wait,
            "job_list": self._tool_job_list,
            "job_action": self._tool_job_action,
            "results_summary": self._tool_results_summary,
            "results_compare": self._tool_results_compare,
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

    def _with_client(self, operation, retry=True, codes=RECONNECT_CODES):
        client = self._ensure_client()
        try:
            return operation(client)
        except AgentError as error:
            if error.code not in codes:
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
                "再用 draft_* 准备场景、experiment_run 提交批次，"
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
            return _json_text(data)
        if name == "lab_status":
            manifest = data.get("manifest") if isinstance(data.get("manifest"), dict) else {}
            engine = data.get("engine") if isinstance(data.get("engine"), dict) else {}
            return _json_text({
                "api": manifest.get("api"),
                "server_version": manifest.get("server_version"),
                "adapter_version": manifest.get("adapter_version"),
                "engine_build": manifest.get("engine_build"),
                "scenario_schema": manifest.get("scenario_schema"),
                "batch_schema": manifest.get("batch_schema"),
                "capabilities": manifest.get("capabilities"),
                "limits": manifest.get("limits"),
                "engine": {
                    "compatible": engine.get("compatible"),
                    "profile": _engine_profile(engine),
                    "profile_version": _engine_profile_version(engine),
                    "reason": engine.get("reason"),
                    "can_simulate": engine.get("can_simulate"),
                },
                "active_job": _progress_view(data["active_job"]) if isinstance(data.get("active_job"), dict) else None,
                "save_active": data.get("save_active"),
                "paths": data.get("paths"),
            })
        if name == "draft_create":
            return _json_text({
                "draft_id": data.get("draft_id"),
                "draft": _draft_view((data.get("draft") or {})),
            })
        if name == "draft_edit":
            return _json_text({
                "draft_id": data.get("draft_id"),
                "changed": data.get("changed"),
                "ops": data.get("ops"),
                "validation": data.get("validation"),
                "draft": _draft_view((data.get("summary") or {})),
            })
        if name == "draft_validate":
            return _json_text({
                "draft_id": data.get("draft_id"),
                "valid": data.get("valid"),
                "errors": data.get("errors"),
                "records": data.get("records"),
                "draft": _draft_view((data.get("summary") or {})),
            })
        if name == "draft_list":
            drafts = data.get("drafts") or []
            return _json_text({"drafts": [_draft_view(item) for item in drafts]})
        if name == "draft_get":
            value = _draft_view(data)
            scenario = data.get("scenario")
            if isinstance(scenario, dict):
                value["scenario_bytes"] = len(json.dumps(scenario, ensure_ascii=False))
            for key in ("scenario_path", "scenario_sha256"):
                if data.get(key) is not None:
                    value[key] = data.get(key)
            return _json_text(value)
        if name == "draft_options":
            return _json_text(data)
        if name == "draft_delete":
            return _json_text(data)
        if name == "experiment_run":
            return _json_text({
                "job_id": data.get("job_id"),
                "total": data.get("total"),
                "workers": data.get("workers"),
                "mode": data.get("mode"),
                "queued": data.get("queued"),
                "queue_position": data.get("queue_position"),
                "seeds": data.get("seeds"),
                "jobs": data.get("jobs"),
            })
        if name == "job_wait":
            value = _progress_view(data)
            value["timed_out"] = data.get("timed_out")
            value["stopped"] = data.get("stopped")
            value["next_poll_seconds"] = data.get("next_poll_seconds")
            return _json_text(value)
        if name == "job_get":
            return _json_text(_progress_view(data))
        if name == "job_list":
            jobs = data.get("jobs") or []
            return _json_text({
                "jobs": [_progress_view(job) for job in jobs],
                "total": data.get("total"),
                "next_offset": data.get("next_offset"),
            })
        if name == "job_action":
            return _json_text(data)
        if name == "results_summary":
            return _json_text({
                "job_id": data.get("job_id"),
                "status": data.get("status"),
                "mode": data.get("mode"),
                "metrics": data.get("metrics"),
                "paired": data.get("paired"),
                "distributions": data.get("distributions"),
                "tactic_pool": data.get("tactic_pool"),
                "timings": data.get("timings"),
                "failures": data.get("failures"),
            })
        if name == "results_compare":
            return _json_text(data)
        if name == "results_csv":
            return _json_text({
                "job_id": data.get("job_id"),
                "path": data.get("path"),
                "path_wsl_hint": data.get("path_wsl_hint"),
                "sha256": data.get("sha256"),
                "rows": data.get("rows"),
                "columns": data.get("columns"),
            })
        if name == "results_matches":
            if data.get("seed") is not None:
                run = data.get("run") or {}
                return _json_text({
                    "job_id": data.get("job_id"),
                    "seed": data.get("seed"),
                    "found": data.get("found"),
                    "run": _match_view(run) if run else None,
                })
            rows = [_match_view(run) for run in (data.get("runs") or [])]
            return _json_text({
                "job_id": data.get("job_id"),
                "runs_total": data.get("runs_total"),
                "runs_offset": data.get("runs_offset"),
                "next_offset": data.get("next_offset"),
                "runs": rows,
            })
        if name in ("fmf_import", "fmf_export", "setpiece_export"):
            return _json_text(data)
        return _json_text(data)

    def _tool_lab_status(self, args):
        def operation(client):
            status = client.status()
            if not isinstance(status, dict):
                status = {}
            data_dir = Path(getattr(client, "data_dir", None) or self.data_dir)
            paths = {
                "data_dir": str(data_dir),
                "runs_dir": str(data_dir / "runs"),
                "drafts_dir": str(data_dir / "agent" / "drafts"),
                "exports_dir": str(data_dir / "agent" / "exports"),
            }
            paths["data_dir_wsl_hint"] = _wsl_hint(paths["data_dir"])
            paths["runs_dir_wsl_hint"] = _wsl_hint(paths["runs_dir"])
            paths["exports_dir_wsl_hint"] = _wsl_hint(paths["exports_dir"])
            engine = status.get("engine_compatibility")
            if not isinstance(engine, dict):
                engine = status.get("engine")
            manifest = client.manifest()
            return {
                "manifest": manifest if isinstance(manifest, dict) else {},
                "engine": engine if isinstance(engine, dict) else {},
                "active_job": status.get("active_job") if isinstance(status.get("active_job"), dict) else None,
                "save_active": status.get("save_active"),
                "paths": paths,
            }
        return self._with_client(operation)

    def _tool_engine_select(self, args):
        return self._with_client(lambda client: client.engine_select(args["game_root"]), retry=False)

    def _tool_draft_create(self, args):
        source = args["source"]
        keys = ("side", "file_base64", "file_path", "base_scenario", "base_draft_id",
                "job_id", "variant", "scenario", "scenario_path")
        extra = {key: args[key] for key in keys if key in args}

        def operation(client):
            summary = self._drafts(client).create(source=source, name=args.get("name"), **extra)
            return {"draft_id": summary["draft_id"], "draft": summary}
        return self._with_client(operation)

    def _tool_draft_get(self, args):
        draft_id = args["draft_id"]
        include_scenario = bool(args.get("include_scenario", False))
        save_scenario = bool(args.get("save_scenario", False))

        def operation(client):
            service = self._drafts(client)
            value = service.get(draft_id, include_scenario=include_scenario or save_scenario)
            if save_scenario:
                scenario = value.pop("scenario", None)
                if not isinstance(scenario, dict):
                    raise AgentError("internal_error", "草案场景缺失")
                data_dir = Path(getattr(client, "data_dir", None) or self.data_dir)
                target = data_dir.joinpath(*EXPORT_SUBDIR, "scenarios", f"{draft_id}.json")
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = json.dumps(scenario, ensure_ascii=False, indent=2).encode("utf-8")
                target.write_bytes(payload)
                value["scenario_path"] = str(target)
                value["scenario_sha256"] = hashlib.sha256(payload).hexdigest()
                value["scenario_bytes"] = len(payload)
                if include_scenario:
                    value["scenario"] = scenario
            return value
        return self._with_client(operation)

    def _tool_draft_edit(self, args):
        draft_id = args["draft_id"]
        if "ops" in args:
            operations = args["ops"]

            def batch(client):
                return self._drafts(client).edit_many(draft_id, operations)
            return self._with_client(batch)
        op = args["op"]
        extra = {key: value for key, value in args.items()
                 if key not in ("draft_id", "op", "ops")}
        return self._with_client(lambda client: self._drafts(client).edit(draft_id, op, **extra))

    def _tool_draft_validate(self, args):
        return self._with_client(lambda client: self._drafts(client).validate(args["draft_id"]))

    def _tool_draft_list(self, args):
        return self._with_client(lambda client: {"drafts": self._drafts(client).list()})

    def _tool_draft_options(self, args):
        draft_id = args["draft_id"]
        side = int(args.get("side", 0))
        phase = args.get("phase")
        slot = args.get("slot")
        include_team = bool(args.get("include_team_instructions", False))

        def operation(client):
            service = self._drafts(client)
            scenario = service.scenario(draft_id)
            catalog = (client.catalog() or {}).get("catalog") or {}
            positions = {item["id"]: item for item in catalog.get("positions") or []}
            roles = {item["id"]: item for item in catalog.get("roles") or []}
            context = catalog.get("role_eligibility_context") or {}
            groups = {int(item["id"]): item for item in catalog.get("team_instructions") or []}
            teams = scenario.get("teams") or []
            if side not in (0, 1) or side >= len(teams):
                raise AgentError("validation_failed", "side 必须是 0 或 1")
            team = teams[side]
            phases = [phase] if phase else ["in_possession", "out_of_possession"]
            result = {
                "draft_id": draft_id,
                "side": side,
                "duties": list(catalog.get("duties") or []),
                "phases": [],
            }
            for current_phase in phases:
                plan = next((item for item in team.get("phase_plans") or []
                             if item.get("phase") == current_phase), None)
                if plan is None:
                    raise AgentError("validation_failed", f"未知阶段：{current_phase}")
                cells = plan.get("assignments") or []
                defenders = sum(bool(positions.get(cell.get("position"), {}).get("mask", 0) & 16)
                                for cell in cells)
                defensive_midfielders = sum(
                    bool(positions.get(cell.get("position"), {}).get("mask", 0) & 0x80)
                    for cell in cells)
                key = f"{3 if defenders >= 3 else 0}:{int(defensive_midfielders == 1)}"
                phase_index = 0 if current_phase == "in_possession" else 1
                entries = []
                for index, cell in enumerate(cells):
                    if slot is not None and index != slot:
                        continue
                    position = cell.get("position")
                    options = (context.get(key) or {}).get(position) or [[], []]
                    option_ids = options[phase_index] if len(options) > phase_index else []
                    entries.append({
                        "slot": index,
                        "position": position,
                        "role": cell.get("role"),
                        "duty": cell.get("duty"),
                        "valid_roles": [
                            {"id": role_id, "label": (roles.get(role_id) or {}).get("label")}
                            for role_id in option_ids
                        ],
                    })
                value = {"phase": current_phase, "context_key": key, "slots": entries}
                if include_team:
                    team_instructions = []
                    for group_id, current_value in (plan.get("team_instructions") or {}).items():
                        if not str(group_id).isdigit():
                            continue
                        group = groups.get(int(group_id))
                        if group is None:
                            continue
                        team_instructions.append({
                            "group": str(group_id),
                            "label": group.get("label"),
                            "value": current_value,
                            "options": [{"id": option["id"], "label": option["label"]}
                                        for option in group.get("options") or []],
                        })
                    value["team_instructions"] = team_instructions
                result["phases"].append(value)
            return result
        return self._with_client(operation)

    def _tool_draft_delete(self, args):
        if "draft_ids" in args:
            return self._with_client(
                lambda client: self._drafts(client).delete_many(args["draft_ids"]))
        return self._with_client(
            lambda client: self._drafts(client).delete(args["draft_id"]))

    def _tool_experiment_run(self, args):
        baseline_id = args.get("baseline_draft_id")
        seeds = expand_seeds(args["seeds"])
        workers = args.get("workers")
        event_details = bool(args.get("event_details", True))
        name = args.get("name")
        per_job_total = len(seeds) * (2 if baseline_id else 1)
        seed_summary = {"count": len(seeds), "first": seeds[0], "last": seeds[-1]}
        candidates = args.get("candidates")
        submission_keys = ["mcp-run-" + secrets.token_hex(12)
                           for _ in (candidates if candidates else [None])]

        def submit(client, drafts, draft_id, draft_name, idempotency_key):
            scenario = drafts.scenario(draft_id)
            reference = drafts.scenario(baseline_id) if baseline_id else None
            created = client.run(scenario, reference=reference, seeds=seeds, workers=workers,
                                 event_details=event_details, name=draft_name,
                                 idempotency_key=idempotency_key)
            total = created.get("total")
            return {
                "job_id": created.get("id"),
                "draft_id": draft_id,
                "name": draft_name,
                "total": total if isinstance(total, int) else per_job_total,
                "workers": created.get("workers", workers or 1),
                "mode": created.get("mode") or ("comparison" if baseline_id else "single"),
                "queued": created.get("queued"),
                "queue_position": created.get("queue_position"),
            }

        def operation(client):
            drafts = self._drafts(client)
            if candidates:
                jobs = []
                try:
                    for index, candidate in enumerate(candidates):
                        candidate_id = candidate["draft_id"]
                        candidate_name = candidate.get("name") or name
                        jobs.append(submit(client, drafts, candidate_id, candidate_name,
                                           submission_keys[index]))
                except Exception:
                    for job in jobs:
                        try:
                            client.cancel(job["job_id"])
                        except Exception:
                            pass
                    raise
                return {
                    "jobs": jobs,
                    "job_id": jobs[0]["job_id"],
                    "total": sum(job["total"] for job in jobs),
                    "workers": jobs[0]["workers"],
                    "mode": jobs[0]["mode"],
                    "seeds": seed_summary,
                }
            job = submit(client, drafts, args["draft_id"], name, submission_keys[0])
            job["seeds"] = seed_summary
            return job
        return self._with_client(operation)

    def _tool_job_get(self, args):
        include_runs = bool(args.get("include_runs", True))
        runs_limit = args.get("runs_limit") if include_runs else 1

        def operation(client):
            detail = client.job(
                args["job_id"],
                runs_offset=args.get("runs_offset"),
                runs_limit=runs_limit,
                variant=args.get("variant"),
            )
            if not include_runs:
                detail = dict(detail)
                detail["runs"] = []
            return detail
        return self._with_client(operation)

    def _tool_job_wait(self, args):
        job_id = args["job_id"]
        timeout = min(max(_number(args.get("timeout_seconds", 45)), 0.0), MAX_WAIT_SECONDS)
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

        def operation(client):
            job = client.wait_job(job_id, timeout=timeout, poll=poll, on_progress=on_progress,
                                  should_stop=should_stop)
            if isinstance(job, dict) and job.get("timed_out"):
                eta = job.get("eta_seconds")
                if isinstance(eta, (int, float)) and eta >= 0:
                    job["next_poll_seconds"] = max(3, min(30, int(eta) + 2))
                else:
                    job["next_poll_seconds"] = 5
            return job
        return self._with_client(operation)

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
            "mode": job.get("mode"),
            "metrics": metrics,
            "distributions": _scorelines(runs),
            "paired": paired,
            "tactic_pool": _pool_view(job),
            "failures": {
                "count": len(failures),
                "items": failures[:20],
                "truncated": len(failures) > 20,
            },
            "timings": timings,
        }

    def _tool_results_compare(self, args):
        baseline_id = args["baseline_job_id"]
        candidate_ids = list(args["candidate_job_ids"])
        variant = args.get("variant") or "B"
        reps = int(args.get("reps", 2000))

        def select_runs(job):
            runs = list(job.get("runs") or [])
            filtered = [run for run in runs if run.get("variant") == variant]
            return filtered or runs

        def operation(client):
            baseline = self._fetch_job(client, baseline_id)
            baseline_runs = select_runs(baseline)
            baseline_pool = self._pool_draws(client, baseline)
            baseline_by_seed = {run["seed"]: run for run in baseline_runs
                                if isinstance(run.get("seed"), int)}
            result = {
                "baseline": {
                    "job_id": baseline.get("id") or baseline_id,
                    "name": baseline.get("name"),
                    "metrics": _compare_metrics(baseline_runs),
                    "tactic_pool": _pool_view(baseline),
                },
                "variant": variant,
                "candidates": [],
            }
            for candidate_id in candidate_ids:
                candidate = self._fetch_job(client, candidate_id)
                candidate_runs = select_runs(candidate)
                candidate_by_seed = {run["seed"]: run for run in candidate_runs
                                     if isinstance(run.get("seed"), int)}
                seeds = sorted(set(baseline_by_seed) & set(candidate_by_seed))
                comparable, reason, pairing = _pool_pairing(
                    baseline_pool, self._pool_draws(client, candidate), seeds)
                entry = {
                    "job_id": candidate.get("id") or candidate_id,
                    "name": candidate.get("name"),
                    "metrics": _compare_metrics(candidate_runs),
                    "tactic_pool": _pool_view(candidate),
                    "comparable": comparable,
                    "reason": reason,
                }
                if pairing is not None:
                    entry["pairing"] = pairing
                if not comparable:
                    entry["paired"] = None
                    result["candidates"].append(entry)
                    continue
                win_delta = []
                points_delta = []
                gd_delta = []
                xgd_delta = []
                for seed in seeds:
                    base_run = baseline_by_seed[seed]
                    candidate_run = candidate_by_seed[seed]
                    bgf, bga = _oriented_score(base_run)
                    cgf, cga = _oriented_score(candidate_run)
                    if None in (bgf, bga, cgf, cga):
                        continue
                    win_delta.append((1 if cgf > cga else 0) - (1 if bgf > bga else 0))
                    points_delta.append((3 if cgf > cga else 1 if cgf == cga else 0)
                                        - (3 if bgf > bga else 1 if bgf == bga else 0))
                    gd_delta.append((cgf - cga) - (bgf - bga))
                    xgd_delta.append(_oriented_xgd(candidate_run) - _oriented_xgd(base_run))
                entry["paired"] = {
                    "seeds": len(win_delta),
                    "win_rate_delta": round(sum(win_delta) / len(win_delta), 4) if win_delta else None,
                    "win_rate_delta_ci": _bootstrap_ci(win_delta, reps),
                    "points_delta": round(sum(points_delta) / len(points_delta), 4) if points_delta else None,
                    "points_delta_ci": _bootstrap_ci(points_delta, reps),
                    "goal_difference_delta": round(sum(gd_delta) / len(gd_delta), 4) if gd_delta else None,
                    "goal_difference_delta_ci": _bootstrap_ci(gd_delta, reps),
                    "xgd_delta": round(sum(xgd_delta) / len(xgd_delta), 4) if xgd_delta else None,
                    "xgd_delta_ci": _bootstrap_ci(xgd_delta, reps),
                }
                result["candidates"].append(entry)
            return result
        return self._with_client(operation)

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
                "path_wsl_hint": _wsl_hint(target),
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
            path = exported.get("path")
            return {
                "draft_id": draft_id,
                "filename": exported.get("filename"),
                "path": path,
                "path_wsl_hint": _wsl_hint(path),
                "install_hint": "把导出的 .fmf 复制到 FM27 战术目录，或在游戏战术界面导入。",
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

    # Job helpers

    def _pool_draws(self, client, job):
        pool = job.get("tactic_pool") if isinstance(job, dict) else None
        if not isinstance(pool, dict) or not pool.get("enabled"):
            return None
        provenance = {}
        try:
            exported = client.job_export(job.get("id"))
            if isinstance(exported, dict):
                provenance = exported.get("provenance") or {}
        except AgentError:
            provenance = {}
        recorded = provenance.get("pool") if isinstance(provenance, dict) else None
        recorded = recorded if isinstance(recorded, dict) else {}
        entries = recorded.get("entries") or pool.get("entries") or []
        signature = []
        for entry in entries:
            if isinstance(entry, dict):
                signature.append((entry.get("index"), entry.get("name"), entry.get("weight"),
                                  bool(entry.get("roster"))))
        raw = recorded.get("draws") if isinstance(recorded.get("draws"), dict) else {}
        draws = {}
        for seed, index in raw.items():
            try:
                draws[int(seed)] = index
            except (TypeError, ValueError):
                continue
        salt = recorded.get("salt")
        if salt is None:
            salt = pool.get("salt")
        mode = recorded.get("mode") or pool.get("mode") or "random"
        rounds = recorded.get("rounds") or pool.get("rounds") or 1
        players = recorded.get("players") or pool.get("players") or "uniform"
        return {"salt": salt if salt is not None else "", "mode": mode, "rounds": rounds,
                "players": players, "entries": signature, "draws": draws}

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
        if host == "workflow" and parts == ["free-mode"]:
            return {"contents": [{"uri": uri, "mimeType": "text/markdown",
                                  "text": FREE_MODE_WORKFLOW}]}
        if host == "paths" and not parts:
            def operation(client):
                data_dir = Path(getattr(client, "data_dir", None) or self.data_dir)
                paths = {
                    "data_dir": str(data_dir),
                    "runs_dir": str(data_dir / "runs"),
                    "drafts_dir": str(data_dir / "agent" / "drafts"),
                    "exports_dir": str(data_dir / "agent" / "exports"),
                }
                paths["data_dir_wsl_hint"] = _wsl_hint(paths["data_dir"])
                paths["runs_dir_wsl_hint"] = _wsl_hint(paths["runs_dir"])
                paths["exports_dir_wsl_hint"] = _wsl_hint(paths["exports_dir"])
                return {"paths": paths, "limits": client.manifest().get("limits")}
            return self._resource_json(uri, self._with_client(operation))
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
        seeds = arguments.get("seeds") or "5001:200"
        return (
            f"对草案 {draft_id} 执行单变量对照实验。变更内容：{instruction}。"
            f"先建立受控夹具：draft_get 基准草案 save_scenario=true，生成双方属性一致、"
            f"位置熟练度满值的场景，再用 draft_create source=inline scenario_path=<文件> 创建受控基准并 draft_validate。"
            f"候选从受控基准 draft_create source=draft 克隆，只用 draft_edit ops 应用本次变更并 draft_validate。"
            f"然后 experiment_run draft_id={draft_id} baseline_draft_id=<受控基准> seeds={seeds} "
            f"workers=2 event_details=false，job_wait timeout_seconds=45，"
            f"再用 results_compare 读取配对差与置信区间。200 场只做筛选，确认需两个独立种子块。"
        )
    if name == "compare_baseline_vs_current":
        baseline_id = arguments.get("baseline_draft_id")
        seeds = arguments.get("seeds") or "5001:200"
        return (
            f"比较受控基准草案 {baseline_id} 与当前草案 {draft_id}。先 draft_validate 两者，"
            f"再 experiment_run draft_id={draft_id} baseline_draft_id={baseline_id} "
            f"seeds={seeds} event_details=false，job_wait timeout_seconds=45 后读取 results_summary。"
            f"若 paired.n 为 0，说明没有同种子配对，可用 results_matches 逐场核对。"
            f"两个独立种子块合并后用 results_compare 计算 ΔWin、ΔPts、ΔGD、ΔxGD 与 95%CI。"
        )
    raise JsonRpcError(INVALID_PARAMS, f"未知 prompt：{name}")


def _csv_columns(job):
    columns = list(BASE_CSV_COLUMNS)
    if job.get("event_details"):
        columns.extend(EVENT_CSV_COLUMNS)
    return columns


def _goal_minutes(run):
    values = []
    previous = [0, 0]
    for change in run.get("score_changes") or []:
        score = change.get("score") or []
        if len(score) < 2:
            continue
        clock = _number(change.get("clock"))
        minute = round(clock / 240.0, 1) if clock else None
        for side in (0, 1):
            delta = int(score[side]) - previous[side]
            for _ in range(max(0, delta)):
                values.append({"side": side, "minute": minute})
        previous = [int(score[0]), int(score[1])]
    return _compact(values)


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
        pool_entry = run.get("tactic_pool_entry")
        if not isinstance(pool_entry, dict):
            pool_entry = {}
        row = {
            "mode": mode,
            "variant": run.get("variant"),
            "seed": run.get("seed"),
            "tactic_pool_entry_index": pool_entry.get("index"),
            "tactic_pool_entry_name": pool_entry.get("name"),
            "home_goals": goals_for,
            "away_goals": goals_against,
            "shots": home.get("shots"),
            "shots_on_target": home.get("shots_on_target"),
            "xg": home.get("xg"),
            "possession": home.get("possession"),
            "passes": home.get("passes"),
            "completed_passes": home.get("completed_passes"),
            "opponent_shots": away.get("shots"),
            "opponent_shots_on_target": away.get("shots_on_target"),
            "xga": away.get("xg"),
            "opponent_possession": away.get("possession"),
            "opponent_passes": away.get("passes"),
            "opponent_completed_passes": away.get("completed_passes"),
            "score_changes": _compact(run.get("score_changes")),
            "goal_minutes": _goal_minutes(run),
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
