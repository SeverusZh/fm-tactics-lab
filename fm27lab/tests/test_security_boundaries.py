"""安全边界回归测试。

覆盖鉴权矩阵、令牌泄漏、endpoint 描述符、路径逃逸、输入上限与仓库隐私边界。
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fm27lab
from fm27lab import sidecar
from fm27lab.application.experiment_material import ExperimentMaterializer
from fm27lab.config import Settings
from fm27lab.sidecar import write_endpoint
from fm27lab.tests.test_http_health import make_app

ROOT = Path(__file__).resolve().parents[2]
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
# 公开面只允许探活与版本；文档路由是框架自带边界，单独断言并记入安全文档。
PUBLIC_API_ROUTES = {("GET", "/api/health"), ("GET", "/api/version")}
DOCUMENTATION_PATHS = {"/api/docs", "/api/openapi.json"}
ENDPOINT_FIELDS = {
    "schema",
    "api",
    "url",
    "port",
    "token",
    "pid",
    "data_dir",
    "engine_root",
    "created_at",
}
CONTENT = b"security-boundary"
CONTENT_BASE64 = base64.b64encode(CONTENT).decode("ascii")
ARTIFACT_LIMIT = 16 * 1024 * 1024
FMF_LIMIT = 4 * 1024 * 1024
FMF_BASE64_LIMIT = (FMF_LIMIT + 2) // 3 * 4
WINDOWS_SYMLINK = pytest.mark.skipif(sys.platform == "win32", reason="符号链接语义依赖平台")
GITIGNORE_PATTERNS = (
    "/private/",
    "/data/",
    "*.jsonl",
    "*.fm",
    "*.fmf",
    "*.pkm",
    ".env",
    "*.db",
    "endpoint.json",
)
TRACKED_FORBIDDEN_SUFFIXES = (".jsonl", ".fm", ".fmf", ".pkm", ".db")


class NoDrafts:
    def get(self, draft_id: str):
        return None


def build_client(tmp_path: Path):
    app, settings, stopped, database = make_app(tmp_path)
    return TestClient(app), app, settings, database


def auth(settings: Settings) -> dict:
    return {"Authorization": f"Bearer {settings.token}"}


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == code
    return error


def api_endpoints(app) -> list[tuple[str, str]]:
    endpoints = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in DOCUMENTATION_PATHS:
            continue
        methods = getattr(route, "methods", None) or set()
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            endpoints.append((method, path))
    return endpoints


def fill_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "probe-id", path)


def register_artifact(client: TestClient, settings: Settings, filename: str) -> dict:
    response = client.post(
        "/api/artifacts",
        json={"kind": "fmf", "filename": filename, "content_base64": CONTENT_BASE64},
        headers=auth(settings),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_api_authentication_matrix(tmp_path: Path):
    client, app, settings, _database = build_client(tmp_path)
    endpoints = api_endpoints(app)
    assert len(endpoints) >= 50
    for method, path in endpoints:
        response = client.request(method, fill_path(path))
        if (method, path) in PUBLIC_API_ROUTES:
            assert response.status_code == 200, f"{method} {path} -> {response.status_code}"
            continue
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS
        assert error["code"] == "unauthorized"
        assert response.headers.get("www-authenticate") == "Bearer"
    assert set(PUBLIC_API_ROUTES) <= set(endpoints)


def test_documentation_routes_are_public_boundary(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    for path in sorted(DOCUMENTATION_PATHS):
        response = client.get(path)
        assert response.status_code == 200
        assert settings.token not in response.text
    assert client.get("/api/redoc").status_code == 404


def test_unauthorized_responses_do_not_leak_token(tmp_path: Path):
    client, app, settings, _database = build_client(tmp_path)
    token = settings.token
    supplied = "wrong-" + "x" * 32
    headers = {"Authorization": f"Bearer {supplied}"}
    for method, path in api_endpoints(app):
        if (method, path) in PUBLIC_API_ROUTES:
            continue
        response = client.request(method, fill_path(path), headers=headers)
        assert response.status_code == 401, f"{method} {path}"
        serialized = response.text + json.dumps(dict(response.headers), ensure_ascii=False)
        assert token not in serialized
        assert supplied not in response.text


def test_openapi_declares_bearer_security(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    schema = client.get("/api/openapi.json").json()
    assert schema["components"]["securitySchemes"] == {
        "HTTPBearer": {"type": "http", "scheme": "bearer"}
    }
    assert settings.token not in json.dumps(schema, ensure_ascii=False)
    protected = 0
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if (method.upper(), path) in PUBLIC_API_ROUTES:
                assert "security" not in operation
                continue
            assert operation.get("security") == [{"HTTPBearer": []}], f"{method} {path}"
            protected += 1
            declared = operation.get("responses", {}).get("401")
            if declared is not None:
                content = declared.get("content", {})
                assert content["application/json"]["schema"]["$ref"] == (
                    "#/components/schemas/ErrorEnvelope"
                )
    assert protected >= 50


def test_endpoint_descriptor_contract(tmp_path: Path):
    data_dir = tmp_path / "data"
    settings = Settings.create(data_dir=data_dir, token="e" * 64)
    write_endpoint(settings, 47821)
    path = settings.endpoint_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == ENDPOINT_FIELDS
    assert payload["schema"] == 1
    assert payload["api"] == fm27lab.API_VERSION
    assert payload["url"] == "http://127.0.0.1:47821"
    assert payload["port"] == 47821
    assert payload["token"] == settings.token
    assert payload["pid"] == os.getpid()
    assert payload["data_dir"] == str(settings.data_dir)
    assert payload["engine_root"] is None
    assert datetime.fromisoformat(payload["created_at"]).tzinfo is not None
    assert not list(path.parent.glob("*.tmp"))
    write_endpoint(settings, 47822)
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert rewritten["port"] == 47822
    assert rewritten["url"] == "http://127.0.0.1:47822"


def test_endpoint_file_permissions(tmp_path: Path):
    settings = Settings.create(data_dir=tmp_path / "data", token="f" * 64)
    write_endpoint(settings, 47823)
    if os.name == "nt":
        pytest.skip("Windows 使用 icacls，权限断言见 test_serve.py")
    assert stat.S_IMODE(settings.endpoint_path.stat().st_mode) == 0o600
    write_endpoint(settings, 47824)
    assert stat.S_IMODE(settings.endpoint_path.stat().st_mode) == 0o600


def test_endpoint_write_failure_leaves_no_temporary_file(tmp_path: Path, monkeypatch):
    settings = Settings.create(data_dir=tmp_path / "data", token="a" * 64)

    def fail(*_args, **_kwargs):
        raise RuntimeError("dump failure")

    monkeypatch.setattr(sidecar.json, "dump", fail)
    with pytest.raises(RuntimeError, match="dump failure"):
        write_endpoint(settings, 47825)
    assert not settings.endpoint_path.exists()
    assert not settings.endpoint_path.with_name("endpoint.json.tmp").exists()


def test_endpoint_replace_failure_preserves_previous_descriptor(tmp_path: Path, monkeypatch):
    settings = Settings.create(data_dir=tmp_path / "data", token="b" * 64)
    settings.ensure_dirs()
    previous = {"schema": 1, "api": "previous"}
    settings.endpoint_path.write_text(json.dumps(previous), encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise OSError("replace failure")

    monkeypatch.setattr(sidecar.os, "replace", fail)
    with pytest.raises(OSError, match="replace failure"):
        write_endpoint(settings, 47826)
    payload = json.loads(settings.endpoint_path.read_text(encoding="utf-8"))
    assert payload == previous
    assert not settings.endpoint_path.with_name("endpoint.json.tmp").exists()


@pytest.mark.skipif(os.name == "nt", reason="目录权限语义依赖 POSIX")
def test_data_directories_are_owner_only(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.chmod(0o755)
    settings = Settings.create(data_dir=data_dir, token="d" * 64)
    settings.ensure_dirs()
    for path in (settings.data_dir, settings.endpoint_path.parent, settings.exports_dir):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700, str(path)


def test_artifact_upload_rejects_traversal_names(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    headers = auth(settings)
    attempts = [
        {"kind": "fmf", "filename": "../security-escape.bin"},
        {"kind": "fmf", "filename": ".."},
        {"kind": "fmf", "filename": "."},
        {"kind": "fmf", "filename": "sub/name.bin"},
        {"kind": "fmf", "filename": "a" * 129},
        {"kind": "../fmf", "filename": "probe.bin"},
        {"kind": "..", "filename": "probe.bin"},
    ]
    for payload in attempts:
        body = {**payload, "content_base64": CONTENT_BASE64}
        response = client.post("/api/artifacts", json=body, headers=headers)
        error = assert_error(response, 400, "validation_failed")
        assert error["retriable"] is False
    assert not (tmp_path.parent / "security-escape.bin").exists()


def test_artifact_content_rejects_paths_outside_root(tmp_path: Path):
    client, _app, settings, database = build_client(tmp_path)
    outside = tmp_path / "outside-secret.bin"
    outside.write_bytes(b"outside-secret")
    artifact = register_artifact(client, settings, "tampered.bin")
    with closing(database.connect()) as connection:
        connection.execute(
            "UPDATE artifacts SET path=? WHERE id=?", (str(outside), artifact["id"])
        )
    response = client.get(f"/api/artifacts/{artifact['id']}/content", headers=auth(settings))
    assert response.status_code == 404
    assert b"outside-secret" not in response.content


@WINDOWS_SYMLINK
def test_artifact_download_rejects_symlink_swap(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    outside = tmp_path / "outside-secret.bin"
    outside.write_bytes(b"outside-secret")
    artifact = register_artifact(client, settings, "swapped.bin")
    stored = Path(artifact["path"])
    stored.unlink()
    stored.symlink_to(outside)
    response = client.get(f"/api/artifacts/{artifact['id']}/content", headers=auth(settings))
    assert response.status_code == 404
    assert b"outside-secret" not in response.content


@WINDOWS_SYMLINK
def test_artifact_delete_keeps_external_symlink_target(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    outside = tmp_path / "outside-sentinel.bin"
    outside.write_bytes(b"sentinel")
    artifact = register_artifact(client, settings, "deleted.bin")
    stored = Path(artifact["path"])
    stored.unlink()
    stored.symlink_to(outside)
    response = client.delete(f"/api/artifacts/{artifact['id']}", headers=auth(settings))
    assert response.status_code == 204
    assert outside.read_bytes() == b"sentinel"
    assert not os.path.lexists(stored)
    assert client.get(f"/api/artifacts/{artifact['id']}", headers=auth(settings)).status_code == 404


@WINDOWS_SYMLINK
def test_experiment_discard_rejects_symlinked_agent_dir(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "outside"
    target = outside / "experiments" / "job-probe"
    target.mkdir(parents=True)
    sentinel = target / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    (data_dir / "agent").symlink_to(outside)
    settings = Settings(data_dir=data_dir, token="c" * 64)
    worker = ExperimentMaterializer(NoDrafts(), settings)
    with pytest.raises(ValueError, match="实验目录不合法"):
        worker.discard("job-probe")
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_experiment_discard_ignores_traversal_job_id(tmp_path: Path):
    settings = Settings.create(data_dir=tmp_path / "data", token="c" * 64)
    settings.ensure_dirs()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    worker = ExperimentMaterializer(NoDrafts(), settings)
    for job_id in ("../sentinel.txt", "..", "a/b", "", "x" * 65):
        assert worker.discard(job_id) is None
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_oversized_artifact_payload_returns_413_envelope(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    payload = base64.b64encode(b"x" * (ARTIFACT_LIMIT + 1)).decode("ascii")
    body = {"kind": "fmf", "filename": "big.bin", "content_base64": payload}
    response = client.post("/api/artifacts", json=body, headers=auth(settings))
    error = assert_error(response, 413, "payload_too_large")
    assert "16 MiB" in error["message"]
    assert settings.token not in response.text
    listed = client.get("/api/artifacts", headers=auth(settings))
    assert listed.json()["total"] == 0


def test_oversized_fmf_payload_returns_400_envelope(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    payload = base64.b64encode(b"z" * (FMF_LIMIT + 3)).decode("ascii")
    assert len(payload) > FMF_BASE64_LIMIT
    body = {"name": "probe", "content_base64": payload}
    response = client.post("/api/drafts/import-fmf", json=body, headers=auth(settings))
    error = assert_error(response, 400, "validation_failed")
    assert "4 MiB" in error["message"]
    assert settings.token not in response.text


def test_malformed_json_returns_400_envelope(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    headers = {**auth(settings), "Content-Type": "application/json"}
    response = client.post("/api/artifacts", content=b"{", headers=headers)
    assert_error(response, 400, "validation_failed")


def test_invalid_query_bounds_return_400_envelope(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    for value in ("0", "257", "1; drop", "1.5", "-3"):
        response = client.get("/api/jobs", params={"limit": value}, headers=auth(settings))
        assert_error(response, 400, "validation_failed")


def test_unknown_input_fields_are_rejected(tmp_path: Path):
    client, _app, settings, _database = build_client(tmp_path)
    body = {
        "kind": "fmf",
        "filename": "probe.bin",
        "content_base64": CONTENT_BASE64,
        "unexpected": 1,
    }
    response = client.post("/api/artifacts", json=body, headers=auth(settings))
    assert_error(response, 400, "validation_failed")


def tracked_files() -> list[str] | None:
    executable = shutil.which("git")
    if executable is None:
        return None
    result = subprocess.run(
        [executable, "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def test_gitignore_covers_private_and_runtime_data():
    lines = [line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    for pattern in GITIGNORE_PATTERNS:
        assert pattern in lines, pattern
    tracked = tracked_files()
    if tracked is None:
        pytest.skip("git 不可用，跳过跟踪文件检查")
    assert not [path for path in tracked if path.startswith(("private/", "data/"))]
    assert not [path for path in tracked if path.endswith(TRACKED_FORBIDDEN_SUFFIXES)]
    names = [Path(path).name for path in tracked]
    assert "endpoint.json" not in names
    assert ".env" not in names
    assert not [name for name in names if name.startswith(".env.") and name != ".env.example"]


def test_source_manifest_excludes_private_runtime_files():
    manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    assert isinstance(manifest, dict) and manifest
    for path in manifest:
        assert not path.startswith("private/"), path
        assert not path.endswith(".db"), path
        assert not path.endswith("endpoint.json"), path
