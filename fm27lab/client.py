"""Sidecar HTTP client and endpoint discovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from http import client as http_client
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request

from fm27lab.config import LOOPBACK_HOSTS

DEFAULT_TIMEOUT = 30.0
ENDPOINT_RELATIVE_PATH = Path("agent") / "endpoint.json"
SUPPORTED_METHODS = frozenset({"GET", "POST", "PATCH", "DELETE"})


class SidecarError(Exception):
    """结构化错误：sidecar 返回的错误封套或本地传输失败。"""

    def __init__(
        self,
        code: str,
        message: str,
        status: int | None = None,
        *,
        details: Any = None,
        retriable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        self.retriable = retriable

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class _NoRedirectHandler(request.HTTPRedirectHandler):
    """拒绝一切重定向，避免 Bearer token 被转发到其他主机。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint_path(data_dir: Path) -> Path:
    return Path(data_dir) / ENDPOINT_RELATIVE_PATH


def _invalid_endpoint(target: Path, reason: str) -> SidecarError:
    return SidecarError("endpoint_invalid", f"sidecar 发现文件无效：{target}（{reason}）")


def _display_endpoint_url(parsed: urlparse.SplitResult) -> str:
    host = parsed.hostname or "<未知主机>"
    scheme = parsed.scheme or "<未知协议>"
    try:
        port = parsed.port
    except ValueError:
        port = None
    return f"{scheme}://{host}" + ("" if port is None else f":{port}")


def _parse_loopback_url(url: str) -> None:
    try:
        parsed = urlparse.urlsplit(url)
        port = parsed.port
    except ValueError:
        raise SidecarError("endpoint_invalid", "sidecar 地址端口无效") from None
    display = _display_endpoint_url(parsed)
    if parsed.username is not None or parsed.password is not None:
        raise SidecarError("endpoint_invalid", f"sidecar 地址不得包含用户信息：{display}")
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or parsed.hostname.lower() not in LOOPBACK_HOSTS
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or port is None
    ):
        raise SidecarError(
            "endpoint_invalid",
            f"sidecar 地址必须为 http://127.0.0.1 回环根地址：{display}",
        )


def discover_endpoint(data_dir: Path) -> dict[str, Any]:
    target = endpoint_path(data_dir)
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SidecarError("endpoint_missing", f"找不到 sidecar 发现文件：{target}") from None
    except OSError as error:
        raise SidecarError(
            "endpoint_unreadable",
            f"无法读取 sidecar 发现文件：{target}",
            details={"reason": str(error)},
        ) from None
    try:
        payload = json.loads(raw)
    except ValueError:
        raise _invalid_endpoint(target, "不是有效的 JSON") from None
    if not isinstance(payload, dict):
        raise _invalid_endpoint(target, "根节点必须是对象")
    url = payload.get("url")
    token = payload.get("token")
    if not isinstance(url, str) or not url.strip():
        raise _invalid_endpoint(target, "缺少有效的 url")
    if not isinstance(token, str) or not token.strip() or not token.isascii():
        raise _invalid_endpoint(target, "缺少有效的 token")
    _parse_loopback_url(url.strip())
    result = dict(payload)
    result["url"] = url.strip()
    result["token"] = token
    return result


def _http_error(status: int, raw: bytes) -> SidecarError:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        return SidecarError(
            code if isinstance(code, str) and code else "http_error",
            message if isinstance(message, str) and message else f"sidecar 返回 HTTP {status}",
            status,
            details=error.get("details"),
            retriable=bool(error.get("retriable", False)),
        )
    return SidecarError("http_error", f"sidecar 返回 HTTP {status}", status)


class SidecarClient:
    """通过标准库 urllib 访问 loopback sidecar 的 JSON 客户端。"""

    def __init__(self, url: str, token: str, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url 必须是非空字符串")
        if not isinstance(token, str) or not token:
            raise ValueError("token 必须是非空字符串")
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError):
            raise ValueError("timeout 必须是数字") from None
        if timeout_value <= 0:
            raise ValueError("timeout 必须大于 0")
        self.url = url.strip().rstrip("/")
        self.token = token
        self.timeout = timeout_value
        self._opener = request.build_opener(request.ProxyHandler({}), _NoRedirectHandler())

    def __repr__(self) -> str:
        return f"SidecarClient(url={self.url!r}, token='***', timeout={self.timeout!r})"

    def _request_url(self, path: str, query: Mapping[str, Any] | None) -> str:
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("path 必须以 / 开头")
        url = self.url + urlparse.quote(path, safe="/")
        if not query:
            return url
        pairs = [(str(key), str(value)) for key, value in query.items() if value is not None]
        if not pairs:
            return url
        return f"{url}?{urlparse.urlencode(pairs)}"

    def _open(self, request_value: request.Request):
        return self._opener.open(request_value, timeout=self.timeout)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = method.upper() if isinstance(method, str) else ""
        if normalized not in SUPPORTED_METHODS:
            raise ValueError(f"不支持的 HTTP 方法：{method}")
        url = self._request_url(path, query)
        data = None
        if body is not None:
            try:
                data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError):
                raise ValueError("请求体无法序列化为 JSON") from None
        try:
            request_value = request.Request(url, data=data, method=normalized)
            request_value.add_header("Accept", "application/json")
            request_value.add_header("Authorization", f"Bearer {self.token}")
            if data is not None:
                request_value.add_header("Content-Type", "application/json")
        except (ValueError, UnicodeError) as error:
            raise SidecarError("invalid_request", f"sidecar 请求地址无效：{error}") from None
        try:
            with self._open(request_value) as response:
                raw = response.read()
                status = response.status
        except urlerror.HTTPError as error:
            try:
                if 300 <= error.code < 400:
                    raise SidecarError(
                        "unexpected_redirect",
                        f"意外的重定向，已拒绝跟随：HTTP {error.code}",
                        error.code,
                    ) from None
                raw = error.read()
            finally:
                error.close()
            raise _http_error(error.code, raw) from None
        except (urlerror.URLError, OSError) as error:
            reason = getattr(error, "reason", None) or error
            raise SidecarError("unreachable", f"无法连接 sidecar：{reason}") from None
        except http_client.InvalidURL as error:
            raise SidecarError("invalid_request", f"sidecar 请求地址无效：{error}") from None
        except (ValueError, UnicodeError) as error:
            raise SidecarError("invalid_request", f"sidecar 请求参数无效：{error}") from None
        except http_client.HTTPException:
            raise SidecarError("invalid_response", "sidecar 返回了无效的 HTTP 响应") from None
        if status == 204 or not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise SidecarError("invalid_response", "sidecar 返回了无法解析的响应", status) from None
        if not isinstance(payload, dict):
            raise SidecarError("invalid_response", "sidecar 返回的 JSON 不是对象", status)
        return payload

    def get(self, path: str, *, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.request_json("GET", path, query=query)

    def post(
        self,
        path: str,
        *,
        body: Any = None,
        query: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.request_json("POST", path, body=body, query=query)

    def patch(
        self,
        path: str,
        *,
        body: Any = None,
        query: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.request_json("PATCH", path, body=body, query=query)

    def delete(self, path: str, *, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.request_json("DELETE", path, query=query)
