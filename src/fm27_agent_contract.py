"""Pure helpers shared by the local server and the agent adapters."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

API = "fm27lab/v1"
PREFIX = "/api/agent/v1"
APP_VERSION = "1108.5"
ENDPOINT_SCHEMA = 1
TOKEN_COOKIE = "fm27_session"
EXEMPT_PATHS = {
    "/",
    "/api/agent/v1/health",
    "/api/status",
    "/api/desktop-presence",
}
MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def new_token():
    return secrets.token_hex(32)


def host_allowed(host, port):
    if not isinstance(host, str) or not host:
        return False
    value = host.strip().lower()
    return value in {
        f"127.0.0.1:{int(port)}",
        f"localhost:{int(port)}",
        f"[::1]:{int(port)}",
    }


def cookie_token(header):
    if not header:
        return None
    for item in header.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == TOKEN_COOKIE:
            return value
    return None


def request_token(headers):
    authorization = headers.get("Authorization") if headers else None
    if authorization and authorization.lower().startswith("bearer "):
        value = authorization[7:].strip()
        if value:
            return value
    cookie = headers.get("Cookie") if headers else None
    return cookie_token(cookie)


def authorized(headers, token):
    value = request_token(headers)
    if not value or not token:
        return False
    return hmac.compare_digest(str(value), str(token))


def is_exempt(path, static_paths=()):
    return path in EXEMPT_PATHS or path in static_paths


def error_payload(code, message, details=None, retriable=False, retry_after_seconds=None):
    value = {
        "code": code,
        "message": message,
        "details": details or {},
        "retriable": bool(retriable),
    }
    if retry_after_seconds is not None:
        value["retry_after_seconds"] = retry_after_seconds
    return {"error": value}


def json_digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def clamp_limit(value, default=DEFAULT_LIMIT, maximum=MAX_LIMIT):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, number))


def clamp_offset(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def paginate(items, limit=DEFAULT_LIMIT, offset=0, field="items"):
    total = len(items)
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    page = items[offset:offset + limit]
    next_offset = offset + limit if offset + limit < total else None
    return {
        field: page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
    }


class IdempotencyStore:
    def __init__(self, ttl=86400, clock=None):
        self.ttl = float(ttl)
        self.clock = clock or time.time
        self.values = {}
        self.lock = None

    def _prune(self):
        now = self.clock()
        for key in [key for key, value in self.values.items() if value["expires"] <= now]:
            self.values.pop(key, None)

    def check(self, key, digest):
        self._prune()
        value = self.values.get(key)
        if value is None:
            return "missing", None
        if value["digest"] != digest:
            return "conflict", None
        return "replay", (value["status"], value["payload"])

    def remember(self, key, digest, status, payload):
        self._prune()
        self.values[key] = {
            "digest": digest,
            "status": status,
            "payload": payload,
            "expires": self.clock() + self.ttl,
        }


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def build_endpoint(port, token, data_dir, engine_root, game_root, versions,
                   capabilities, limits):
    return {
        "schema": ENDPOINT_SCHEMA,
        "api": API,
        "url": f"http://127.0.0.1:{int(port)}",
        "token": str(token),
        "pid": os.getpid(),
        "data_dir": str(Path(data_dir)),
        "engine_root": str(Path(engine_root)),
        "game_root": str(game_root or ""),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "versions": versions,
        "capabilities": list(capabilities),
        "limits": dict(limits),
    }


def endpoint_file(data_dir):
    return Path(data_dir) / "agent" / "endpoint.json"


def write_endpoint(data_dir, value):
    write_json_atomic(endpoint_file(data_dir), value)
    return endpoint_file(data_dir)


def remove_endpoint(data_dir):
    path = endpoint_file(data_dir)
    try:
        path.unlink()
    except OSError:
        pass


def write_agent_scripts(data_dir, source_dir, python_exe):
    """Write stable launcher shims so MCP clients do not depend on release hashes."""
    agent_dir = Path(data_dir) / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    command = agent_dir / "fm27lab.cmd"
    lines = [
        "@echo off",
        f'set "PYTHONPATH={Path(source_dir)}"',
        f'"{Path(python_exe)}" -m fm27_agent %*',
    ]
    with command.open("w", encoding="utf-8", newline="") as stream:
        stream.write("\r\n".join(lines) + "\r\n")
    configuration = {
        "mcpServers": {
            "fm27lab": {
                "command": str(command),
                "args": ["mcp"],
            }
        }
    }
    config = agent_dir / "mcp.json"
    config.write_text(json.dumps(configuration, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"command": str(command), "config": str(config)}
