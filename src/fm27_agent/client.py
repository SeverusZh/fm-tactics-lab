"""HTTP client for the FM Tactics Lab agent API.

The client is standard-library only so it can run under the bundled Python
runtime and on a developer machine without extra packages.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request

API = "fm27lab/v1"
PREFIX = "/api/agent/v1"
DATA_ENV = "FM27LAB_DATA"
TERMINAL_STATES = ("complete", "error", "cancelled", "interrupted")


class AgentError(Exception):
    """Structured error returned by the agent API or the local transport."""

    def __init__(self, code, message, details=None, retriable=False,
                 retry_after_seconds=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retriable = bool(retriable)
        self.retry_after_seconds = retry_after_seconds
        self.http_status = http_status

    def to_dict(self):
        value = {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retriable": self.retriable,
        }
        if self.retry_after_seconds is not None:
            value["retry_after_seconds"] = self.retry_after_seconds
        return value

    def __str__(self):
        return f"{self.code}: {self.message}"

    @classmethod
    def from_payload(cls, payload, http_status=None):
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return cls(
                    error.get("code") or "internal_error",
                    error.get("message") or "请求失败",
                    error.get("details"),
                    error.get("retriable", False),
                    error.get("retry_after_seconds"),
                    http_status,
                )
            if isinstance(error, str) and error:
                return cls("internal_error", error, None, False, None, http_status)
        return cls("internal_error", f"请求失败，HTTP {http_status}", None, False, None, http_status)


def default_data_dir(env=None):
    env = os.environ if env is None else env
    configured = env.get(DATA_ENV)
    if configured:
        return Path(configured)
    if os.name == "nt":
        base = env.get("LOCALAPPDATA")
        if base:
            return Path(base) / "FM27TacticsDesktop"
        return Path.home() / "AppData" / "Local" / "FM27TacticsDesktop"
    base = env.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "fm27tactics"
    return Path.home() / ".local" / "share" / "fm27tactics"


def endpoint_path(data_dir=None, env=None):
    return Path(data_dir or default_data_dir(env)) / "agent" / "endpoint.json"


def load_endpoint(data_dir=None, env=None):
    path = endpoint_path(data_dir, env)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise AgentError(
            "app_unavailable",
            f"找不到应用发现文件：{path}",
            {"path": str(path)},
            retriable=True,
        ) from None
    except ValueError:
        raise AgentError(
            "app_unavailable",
            f"应用发现文件无法解析：{path}",
            {"path": str(path)},
            retriable=False,
        ) from None
    if not isinstance(value, dict) or not value.get("url") or not value.get("token"):
        raise AgentError(
            "app_unavailable",
            f"应用发现文件不完整：{path}",
            {"path": str(path)},
            retriable=True,
        )
    return value


def expand_seeds(value, limit=10000):
    """Expand [start, count] or an explicit list into a unique uint32 list."""
    if isinstance(value, dict):
        start = value.get("start")
        count = value.get("count")
        if type(start) is not int or type(count) is not int:
            raise AgentError("validation_failed", "seeds 需要 start 与 count 两个整数")
        seeds = list(range(start, start + count))
    elif isinstance(value, (list, tuple)):
        seeds = list(value)
    else:
        raise AgentError("validation_failed", "seeds 需要起始与数量，或整数数组")
    if not 1 <= len(seeds) <= limit:
        raise AgentError("validation_failed", f"种子数量必须在 1 到 {limit} 之间")
    if any(type(seed) is not int or not 0 <= seed <= 0xFFFFFFFF for seed in seeds):
        raise AgentError("validation_failed", "种子必须是 0 到 4294967295 的整数")
    if len(set(seeds)) != len(seeds):
        raise AgentError("validation_failed", "种子不能重复")
    return seeds


class Client:
    """Thin JSON client. Discovery reads <dataDir>/agent/endpoint.json."""

    def __init__(self, endpoint=None, *, data_dir=None, base_url=None, token=None,
                 timeout=120.0, env=None):
        self.env = os.environ if env is None else env
        self.timeout = float(timeout)
        self._source_dir = Path(data_dir) if data_dir else None
        if base_url is None:
            self.endpoint = endpoint or load_endpoint(data_dir, self.env)
            self.base_url = str(self.endpoint["url"]).rstrip("/")
            self.token = self.endpoint.get("token")
            self.data_dir = Path(self.endpoint.get("data_dir") or (data_dir or default_data_dir(self.env)))
            self._discovery = True
        else:
            self.endpoint = {}
            self.base_url = str(base_url).rstrip("/")
            self.token = token
            self.data_dir = Path(data_dir or default_data_dir(self.env))
            self._discovery = False

    def refresh(self):
        """Re-read endpoint.json after the app restarted with a new port or token."""
        if not self._discovery:
            return False
        endpoint = load_endpoint(self._source_dir, self.env)
        if endpoint.get("url") == self.endpoint.get("url") and endpoint.get("token") == self.token:
            return False
        self.endpoint = endpoint
        self.base_url = str(endpoint["url"]).rstrip("/")
        self.token = endpoint.get("token")
        self.data_dir = Path(endpoint.get("data_dir") or default_data_dir(self.env))
        return True

    def _request(self, method, path, body=None, query=None, timeout=None, idempotency_key=None):
        url = self.base_url + path
        if query:
            pairs = [(key, value) for key, value in query.items() if value is not None]
            if pairs:
                url += "?" + urlparse.urlencode(pairs)
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_value = request.Request(url, data=payload, method=method)
        request_value.add_header("Accept", "application/json")
        request_value.add_header("User-Agent", "fm27lab/1")
        if payload is not None:
            request_value.add_header("Content-Type", "application/json")
        if self.token:
            request_value.add_header("Authorization", "Bearer " + str(self.token))
        if idempotency_key:
            request_value.add_header("Idempotency-Key", idempotency_key)
        try:
            with request.urlopen(request_value, timeout=timeout or self.timeout) as response:
                raw = response.read()
        except urlerror.HTTPError as error:
            try:
                raw = error.read()
            finally:
                error.close()
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                decoded = {}
            raise AgentError.from_payload(decoded, error.code) from None
        except (urlerror.URLError, TimeoutError, OSError) as error:
            raise AgentError(
                "app_unavailable",
                f"无法连接应用：{error}",
                {"endpoint": self.base_url},
                retriable=True,
            ) from None
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise AgentError(
                "internal_error",
                "应用返回了无法解析的响应",
                {"body": raw[:500].decode("utf-8", "replace")},
            ) from None

    def get(self, path, query=None, timeout=None):
        return self._request("GET", path, query=query, timeout=timeout)

    def post(self, path, body=None, timeout=None, idempotency_key=None):
        return self._request("POST", path, body=body if body is not None else {}, timeout=timeout,
                             idempotency_key=idempotency_key)

    # Discovery and engine

    def health(self):
        return self.get(PREFIX + "/health")

    def manifest(self):
        return self.get(PREFIX + "/manifest")

    def status(self):
        return self.get(PREFIX + "/status")

    def catalog(self):
        return self.get(PREFIX + "/catalog")

    def defaults(self):
        return self.get(PREFIX + "/defaults")

    def schemas(self):
        return self.get(PREFIX + "/schemas")

    def engine_select(self, game_root):
        return self.post(PREFIX + "/engine/select", {"game_root": str(game_root)})

    # Scenario helpers

    def validate(self, scenario):
        return self.post(PREFIX + "/validate", {"scenario": scenario})

    def repair(self, scenario):
        return self.post(PREFIX + "/repair", {"scenario": scenario})

    def phase_plan(self, scenario):
        return self.post(PREFIX + "/phase-plan", {"scenario": scenario})

    # Jobs

    def jobs(self, limit=50, offset=0, status=None):
        return self.get(PREFIX + "/jobs", {"limit": limit, "offset": offset, "status": status})

    def job(self, job_id, runs_offset=None, runs_limit=None, variant=None, progress=None):
        return self.get(PREFIX + f"/jobs/{job_id}", {
            "runs_offset": runs_offset,
            "runs_limit": runs_limit,
            "variant": variant,
            "progress": progress,
        })

    def job_export(self, job_id):
        return self.get(PREFIX + f"/jobs/{job_id}/export")

    def job_logs(self, job_id, name):
        return self.get_text(PREFIX + f"/jobs/{job_id}/logs/{name}")

    def cancel(self, job_id):
        return self.post(PREFIX + f"/jobs/{job_id}/cancel")

    def resume(self, job_id, workers=None):
        body = {} if workers is None else {"workers": workers}
        return self.post(PREFIX + f"/jobs/{job_id}/resume", body)

    def rename(self, job_id, name):
        return self.post(PREFIX + f"/jobs/{job_id}/rename", {"name": name})

    def delete(self, job_id):
        return self.post(PREFIX + f"/jobs/{job_id}/delete")

    def wait_job(self, job_id, timeout=60.0, poll=1.0, on_progress=None, should_stop=None):
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            job = self.job(job_id)
            if on_progress:
                on_progress(job)
            if job.get("status") in TERMINAL_STATES:
                job["timed_out"] = False
                return job
            if should_stop and should_stop():
                job["timed_out"] = False
                job["stopped"] = True
                return job
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                job["timed_out"] = True
                return job
            time.sleep(min(max(0.05, float(poll)), remaining))

    # Runs

    def run(self, scenario, reference=None, seeds=None, workers=None,
            event_details=True, name=None, idempotency_key=None):
        body = {
            "scenario": scenario,
            "seeds": seeds,
            "event_details": bool(event_details),
        }
        if reference is not None:
            body["reference"] = reference
        if workers is not None:
            body["workers"] = workers
        if name is not None:
            body["name"] = name
        return self.post(PREFIX + "/runs", body, idempotency_key=idempotency_key)

    def selection(self, scenario, lineup, bench):
        return self.post(PREFIX + "/selection", {
            "scenario": scenario,
            "lineup": list(lineup),
            "bench": list(bench),
        })

    # FMF and set pieces

    def fmf_import(self, side, scenario, file_base64, setpiece_target=None):
        body = {"side": int(side), "scenario": scenario, "file_base64": file_base64}
        if setpiece_target is not None:
            body["setpiece_target"] = setpiece_target
        return self.post(PREFIX + "/fmf/import", body)

    def fmf_export(self, side, scenario, name=None):
        body = {"side": int(side), "scenario": scenario}
        if name is not None:
            body["name"] = name
        return self.post(PREFIX + "/fmf/export", body)

    def setpiece_export(self, side, scenario, type, variant):
        return self.post(PREFIX + "/setpiece/export", {
            "side": int(side),
            "scenario": scenario,
            "type": int(type),
            "variant": int(variant),
        })

    def shutdown(self):
        return self.post(PREFIX + "/shutdown")

    def get_text(self, path, query=None, timeout=None):
        """Fetch a non-JSON response such as a raw NDJSON match log."""
        url = self.base_url + path
        if query:
            pairs = [(key, value) for key, value in query.items() if value is not None]
            if pairs:
                url += "?" + urlparse.urlencode(pairs)
        request_value = request.Request(url, method="GET")
        request_value.add_header("Accept", "text/plain, application/x-ndjson")
        request_value.add_header("User-Agent", "fm27lab/1")
        if self.token:
            request_value.add_header("Authorization", "Bearer " + str(self.token))
        try:
            with request.urlopen(request_value, timeout=timeout or self.timeout) as response:
                raw = response.read()
        except urlerror.HTTPError as error:
            try:
                raw = error.read()
            finally:
                error.close()
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                decoded = {}
            raise AgentError.from_payload(decoded, error.code) from None
        except (urlerror.URLError, TimeoutError, OSError) as error:
            raise AgentError("app_unavailable", f"无法连接应用：{error}",
                             {"endpoint": self.base_url}, retriable=True) from None
        return raw.decode("utf-8", "replace")

