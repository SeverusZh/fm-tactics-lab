from __future__ import annotations

import contextlib
import http.server
import io
import json
import socket
import threading
from http import HTTPStatus
from pathlib import Path
from urllib import error as urlerror
from urllib import parse as urlparse

import pytest

from fm27lab.client import SidecarClient, SidecarError, discover_endpoint

TOKEN = "7f3c9a1e5b2d4c6f8a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f"


def endpoint_payload(**overrides):
    payload = {
        "schema": 1,
        "api": "fm27lab/v2",
        "url": "http://127.0.0.1:4321",
        "port": 4321,
        "token": TOKEN,
        "pid": 1234,
    }
    payload.update(overrides)
    return payload


def write_endpoint(data_dir: Path, payload) -> Path:
    target = data_dir / "agent" / "endpoint.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    else:
        target.write_text(str(payload), encoding="utf-8")
    return target


class FakeResponse:
    def __init__(self, payload: bytes = b"", status: int = 200):
        self.payload = payload
        self.status = status

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc) -> bool:
        return False


def install_urlopen(monkeypatch, handler):
    calls = []

    def fake_open(client, request_value):
        calls.append({"request": request_value, "timeout": client.timeout})
        return handler(request_value)

    monkeypatch.setattr(SidecarClient, "_open", fake_open)
    return calls


def test_discover_endpoint_returns_valid_payload(tmp_path: Path):
    payload = endpoint_payload()
    write_endpoint(tmp_path, payload)
    assert discover_endpoint(tmp_path) == payload


def test_discover_endpoint_accepts_localhost_loopback(tmp_path: Path):
    payload = endpoint_payload(url="http://localhost:4321")
    write_endpoint(tmp_path, payload)
    assert discover_endpoint(tmp_path)["url"] == "http://localhost:4321"


def test_discover_endpoint_missing_file_raises_sidecar_error(tmp_path: Path):
    with pytest.raises(SidecarError) as raised:
        discover_endpoint(tmp_path)
    error = raised.value
    assert error.code == "endpoint_missing"
    assert error.status is None
    assert str(tmp_path / "agent" / "endpoint.json") in error.message


def test_discover_endpoint_corrupt_json_raises_sidecar_error(tmp_path: Path):
    target = write_endpoint(tmp_path, "{not-json")
    with pytest.raises(SidecarError) as raised:
        discover_endpoint(tmp_path)
    error = raised.value
    assert error.code == "endpoint_invalid"
    assert str(target) in error.message
    assert "JSON" in error.message


@pytest.mark.parametrize(
    "payload",
    [
        {"token": TOKEN},
        {"url": "http://127.0.0.1:4321"},
        {"url": None, "token": TOKEN},
        {"url": 42, "token": TOKEN},
        {"url": "http://127.0.0.1:4321", "token": ""},
        {"url": "http://127.0.0.1:4321", "token": 42},
    ],
)
def test_discover_endpoint_invalid_fields_raise_sidecar_error(tmp_path: Path, payload):
    write_endpoint(tmp_path, payload)
    with pytest.raises(SidecarError) as raised:
        discover_endpoint(tmp_path)
    error = raised.value
    assert error.code == "endpoint_invalid"
    assert TOKEN not in error.message


@pytest.mark.parametrize(
    "url",
    [
        "http://192.0.2.10:4321",
        "http://sidecar.example:4321",
        "https://127.0.0.1:4321",
        "ftp://127.0.0.1:4321",
        "http://127.0.0.1:4321/path",
    ],
)
def test_discover_endpoint_rejects_non_loopback_urls(tmp_path: Path, url: str):
    write_endpoint(tmp_path, endpoint_payload(url=url))
    with pytest.raises(SidecarError) as raised:
        discover_endpoint(tmp_path)
    error = raised.value
    assert error.code == "endpoint_invalid"
    assert "回环" in error.message
    assert TOKEN not in error.message


def test_discover_endpoint_does_not_print_token(tmp_path: Path, capsys):
    write_endpoint(tmp_path, endpoint_payload())
    discover_endpoint(tmp_path)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_request_json_sends_bearer_token_method_and_query(monkeypatch):
    calls = install_urlopen(
        monkeypatch,
        lambda request_value: FakeResponse(json.dumps({"items": []}).encode(), 200),
    )
    client = SidecarClient("http://127.0.0.1:4321/", TOKEN, timeout=7.5)
    result = client.request_json(
        "GET",
        "/api/pools",
        query={"limit": 2, "status": "进行 中", "offset": None},
    )
    assert result == {"items": []}
    call = calls[0]
    request_value = call["request"]
    assert call["timeout"] == 7.5
    assert request_value.get_method() == "GET"
    parsed = urlparse.urlsplit(request_value.full_url)
    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:4321"
    assert parsed.path == "/api/pools"
    assert urlparse.parse_qs(parsed.query) == {"limit": ["2"], "status": ["进行 中"]}
    assert request_value.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request_value.get_header("Accept") == "application/json"
    assert "Content-type" not in request_value.headers
    assert request_value.data is None


def test_request_json_serializes_utf8_json_body(monkeypatch):
    calls = install_urlopen(
        monkeypatch,
        lambda request_value: FakeResponse(json.dumps({"id": "p1"}).encode(), 201),
    )
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    result = client.request_json("POST", "/api/pools", body={"name": "角球", "weight": 2})
    assert result == {"id": "p1"}
    request_value = calls[0]["request"]
    assert request_value.get_method() == "POST"
    assert request_value.headers.get("Content-type") == "application/json"
    assert request_value.get_header("Authorization") == f"Bearer {TOKEN}"
    assert "角球".encode() in request_value.data
    assert json.loads(request_value.data.decode("utf-8")) == {"name": "角球", "weight": 2}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/api/drafts/d1", {"name": "新名称"}),
        ("POST", "/api/jobs/j1/cancel", None),
        ("DELETE", "/api/pools/p1", None),
    ],
)
def test_request_json_supports_lifecycle_methods(monkeypatch, method, path, body):
    calls = install_urlopen(monkeypatch, lambda request_value: FakeResponse(b"{}", 200))
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    client.request_json(method, path, body=body)
    request_value = calls[0]["request"]
    assert request_value.get_method() == method
    assert request_value.full_url == f"http://127.0.0.1:4321{path}"
    if body is None:
        assert request_value.data is None
    else:
        assert json.loads(request_value.data.decode("utf-8")) == body


@pytest.mark.parametrize(
    ("convenience", "method"),
    [("get", "GET"), ("post", "POST"), ("patch", "PATCH"), ("delete", "DELETE")],
)
def test_client_convenience_methods_delegate(monkeypatch, convenience, method):
    calls = install_urlopen(monkeypatch, lambda request_value: FakeResponse(b"{}", 200))
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    getattr(client, convenience)("/api/pools")
    assert calls[0]["request"].get_method() == method


def test_request_json_omits_query_when_all_values_none(monkeypatch):
    calls = install_urlopen(monkeypatch, lambda request_value: FakeResponse(b"{}", 200))
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    client.request_json("GET", "/api/jobs", query={"status": None, "limit": None})
    assert "?" not in calls[0]["request"].full_url


def test_discover_endpoint_rejects_non_object_root(tmp_path: Path):
    write_endpoint(tmp_path, [1, 2])
    with pytest.raises(SidecarError) as raised:
        discover_endpoint(tmp_path)
    assert raised.value.code == "endpoint_invalid"


def test_request_json_204_returns_empty_object(monkeypatch):
    install_urlopen(monkeypatch, lambda request_value: FakeResponse(b"", 204))
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    assert client.request_json("DELETE", "/api/pools/p1") == {}


def test_request_json_parses_error_envelope(monkeypatch):
    envelope = {
        "error": {
            "code": "not_found",
            "message": "任务不存在",
            "details": None,
            "retriable": False,
            "retry_after_seconds": None,
        }
    }

    def handler(request_value):
        body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        raise urlerror.HTTPError(request_value.full_url, 404, "Not Found", {}, io.BytesIO(body))

    install_urlopen(monkeypatch, handler)
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    with pytest.raises(SidecarError) as raised:
        client.request_json("GET", "/api/jobs/missing")
    error = raised.value
    assert error.code == "not_found"
    assert error.message == "任务不存在"
    assert error.status == 404
    assert TOKEN not in str(error)


def test_request_json_maps_unstructured_http_error(monkeypatch):
    def handler(request_value):
        raise urlerror.HTTPError(
            request_value.full_url,
            HTTPStatus.INTERNAL_SERVER_ERROR.value,
            "Internal Server Error",
            {},
            io.BytesIO(b"<html>boom</html>"),
        )

    install_urlopen(monkeypatch, handler)
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    with pytest.raises(SidecarError) as raised:
        client.request_json("GET", "/api/pools")
    error = raised.value
    assert error.code == "http_error"
    assert error.status == 500
    assert "500" in error.message


def test_request_json_maps_connection_errors(monkeypatch):
    def handler(request_value):
        raise urlerror.URLError(ConnectionRefusedError(111, "Connection refused"))

    install_urlopen(monkeypatch, handler)
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    with pytest.raises(SidecarError) as raised:
        client.request_json("GET", "/api/pools")
    error = raised.value
    assert error.code == "unreachable"
    assert "无法连接 sidecar" in error.message
    assert error.status is None
    assert TOKEN not in error.message


def test_request_json_maps_timeout_errors(monkeypatch):
    def handler(request_value):
        raise TimeoutError("timed out")

    install_urlopen(monkeypatch, handler)
    client = SidecarClient("http://127.0.0.1:4321", TOKEN, timeout=1.0)
    with pytest.raises(SidecarError) as raised:
        client.request_json("GET", "/api/pools")
    assert raised.value.code == "unreachable"
    assert "无法连接 sidecar" in raised.value.message


def test_request_json_rejects_unparseable_success_body(monkeypatch):
    install_urlopen(monkeypatch, lambda request_value: FakeResponse(b"not-json", 200))
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    with pytest.raises(SidecarError) as raised:
        client.request_json("GET", "/api/pools")
    error = raised.value
    assert error.code == "invalid_response"
    assert error.status == 200
    assert TOKEN not in error.message


def test_sidecar_client_repr_masks_token():
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    assert TOKEN not in repr(client)
    assert "http://127.0.0.1:4321" in repr(client)


@pytest.mark.parametrize(
    ("url", "token", "timeout"),
    [
        ("", TOKEN, 30.0),
        ("http://127.0.0.1:4321", "", 30.0),
        ("http://127.0.0.1:4321", TOKEN, 0.0),
    ],
)
def test_sidecar_client_rejects_invalid_construction(url, token, timeout):
    with pytest.raises(ValueError):
        SidecarClient(url, token, timeout=timeout)


def test_request_json_empty_200_returns_empty_object(monkeypatch):
    install_urlopen(monkeypatch, lambda request_value: FakeResponse(b"", 200))
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    assert client.request_json("GET", "/api/pools") == {}


def test_request_json_rejects_non_object_success_body(monkeypatch):
    install_urlopen(monkeypatch, lambda request_value: FakeResponse(b"[1,2]", 200))
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    with pytest.raises(SidecarError) as raised:
        client.request_json("GET", "/api/pools")
    error = raised.value
    assert error.code == "invalid_response"
    assert error.status == 200


def test_request_json_quotes_path_segments(monkeypatch):
    calls = install_urlopen(monkeypatch, lambda request_value: FakeResponse(b"{}", 200))
    client = SidecarClient("http://127.0.0.1:4321", TOKEN)
    client.request_json("GET", "/api/pools/角球 1?x=1")
    request_value = calls[0]["request"]
    assert request_value.full_url == ("http://127.0.0.1:4321/api/pools/%E8%A7%92%E7%90%83%201%3Fx%3D1")


def test_request_json_maps_unicode_host_to_sidecar_error():
    client = SidecarClient("http://例子.test:1234", TOKEN)
    with pytest.raises(SidecarError) as raised:
        client.request_json("GET", "/api/pools")
    error = raised.value
    assert error.code == "invalid_request"
    assert "无效" in error.message
    assert TOKEN not in error.message


def test_request_json_maps_invalid_url_characters_to_sidecar_error():
    client = SidecarClient("http://127.0.0.1:4321/bad path", TOKEN)
    with pytest.raises(SidecarError) as raised:
        client.request_json("GET", "/api/pools")
    error = raised.value
    assert error.code == "invalid_request"
    assert "无效" in error.message
    assert TOKEN not in error.message


@pytest.mark.parametrize(
    ("url", "secret", "keyword"),
    [
        ("http://127.0.0.1:4321/?token=SECRET-QUERY", "SECRET-QUERY", "回环"),
        ("http://127.0.0.1:4321/#SECRET-FRAGMENT", "SECRET-FRAGMENT", "回环"),
        ("http://127.0.0.1", None, "回环"),
        ("http://user:SECRET-PASSWORD@127.0.0.1:4321", "SECRET-PASSWORD", "用户信息"),
    ],
)
def test_discover_endpoint_rejects_malformed_url_without_leaking_secret(tmp_path: Path, url, secret, keyword):
    write_endpoint(tmp_path, endpoint_payload(url=url))
    with pytest.raises(SidecarError) as raised:
        discover_endpoint(tmp_path)
    error = raised.value
    assert error.code == "endpoint_invalid"
    assert keyword in error.message
    if secret is not None:
        assert secret not in error.message
    assert TOKEN not in error.message


class RecordingServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler_class):
        super().__init__(("127.0.0.1", 0), handler_class)
        self.requests: list[dict] = []
        self.port = self.server_address[1]


class TargetHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append({"path": self.path, "authorization": self.headers.get("Authorization")})
        payload = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return


def redirect_handler(location: str):
    class RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.requests.append(
                {"path": self.path, "authorization": self.headers.get("Authorization")}
            )
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def log_message(self, *args):
            return

    return RedirectHandler


@contextlib.contextmanager
def local_server(handler_class):
    server = RecordingServer(handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_redirect_to_other_loopback_port_is_refused_without_forwarding_token():
    with local_server(TargetHandler) as target:
        location = f"http://127.0.0.1:{target.port}/leak"
        with local_server(redirect_handler(location)) as origin:
            client = SidecarClient(f"http://127.0.0.1:{origin.port}", TOKEN, timeout=5.0)
            with pytest.raises(SidecarError) as raised:
                client.get("/api/pools")
    error = raised.value
    assert error.status == 302
    assert "意外的重定向" in error.message
    assert TOKEN not in error.message
    assert target.requests == []
    assert len(origin.requests) == 1
    assert origin.requests[0]["authorization"] == f"Bearer {TOKEN}"


def test_redirect_to_non_loopback_is_refused_without_second_connection(monkeypatch):
    connections = []
    real_create_connection = socket.create_connection

    def guarded_create_connection(address, *args, **kwargs):
        connections.append(address)
        if address[0] not in ("127.0.0.1", "localhost"):
            raise AssertionError(f"检测到外部连接：{address}")
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    with local_server(redirect_handler("http://192.0.2.10:9/leak")) as origin:
        client = SidecarClient(f"http://127.0.0.1:{origin.port}", TOKEN, timeout=5.0)
        with pytest.raises(SidecarError) as raised:
            client.get("/api/pools")
    error = raised.value
    assert error.status == 302
    assert "意外的重定向" in error.message
    assert TOKEN not in error.message
    assert connections
    assert all(address[0] == "127.0.0.1" for address in connections)
