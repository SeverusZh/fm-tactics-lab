from __future__ import annotations

import base64
import hashlib
import shutil
import urllib.parse
from contextlib import closing
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.application.artifacts import ArtifactService
from fm27lab.tests.test_http_health import make_app

CONTENT = b"hello world"
CONTENT_BASE64 = base64.b64encode(CONTENT).decode("ascii")
CONTENT_SHA256 = hashlib.sha256(CONTENT).hexdigest()
SIZE_LIMIT = 16 * 1024 * 1024
ARTIFACT_FIELDS = {"id", "job_id", "kind", "path", "sha256", "bytes", "created_at"}
HTTP_METHODS = {"get", "post", "patch", "put", "delete", "options", "head"}
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


def auth(settings) -> dict:
    return {"Authorization": f"Bearer {settings.token}"}


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == code
    return error


def artifact_payload(**overrides) -> dict:
    value = {"kind": "fmf", "filename": "tactic.fmf", "content_base64": CONTENT_BASE64}
    value.update(overrides)
    return value


def register_artifact(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post("/api/artifacts", json=artifact_payload(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def create_job(client: TestClient, headers: dict) -> dict:
    response = client.post("/api/jobs", json={"kind": "experiment"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def tamper_artifact_path(app, artifact_id: str, path: str) -> None:
    with closing(app.state.database.connect()) as connection:
        connection.execute("UPDATE artifacts SET path=? WHERE id=?", (path, artifact_id))


def test_artifact_http_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_job(client, headers)
    responses = (
        client.get("/api/artifacts"),
        client.post("/api/artifacts", json=artifact_payload()),
        client.get("/api/artifacts/none"),
        client.get("/api/artifacts/none/content"),
        client.delete("/api/artifacts/none"),
        client.get(f"/api/artifacts?job_id={job['id']}"),
    )
    for response in responses:
        assert response.status_code == 401
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS
        assert error["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    wrong = client.post(
        "/api/artifacts",
        json=artifact_payload(),
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"
    assert client.get("/api/artifacts", headers=headers).json()["total"] == 0


def test_artifact_http_register_detail_download_round_trip(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    assert not hasattr(app.state, "artifacts")

    created = register_artifact(client, headers)

    assert set(created) == ARTIFACT_FIELDS
    assert created["id"]
    assert created["kind"] == "fmf"
    assert created["job_id"] is None
    assert created["sha256"] == CONTENT_SHA256
    assert created["bytes"] == len(CONTENT)
    datetime.fromisoformat(created["created_at"])
    stored = Path(created["path"])
    assert stored.resolve() == (settings.data_dir / "agent" / "artifacts" / "fmf" / "tactic.fmf")
    assert stored.read_bytes() == CONTENT
    assert isinstance(app.state.artifacts, ArtifactService)
    assert app.state.artifacts.root == settings.data_dir / "agent" / "artifacts"

    detail = client.get(f"/api/artifacts/{created['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json() == created

    download = client.get(f"/api/artifacts/{created['id']}/content", headers=headers)
    assert download.status_code == 200
    assert download.content == CONTENT
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["etag"] == f'"{CONTENT_SHA256}"'
    assert download.headers["content-disposition"] == 'attachment; filename="tactic.fmf"'

    duplicate = client.post(
        "/api/artifacts",
        json=artifact_payload(content_base64=base64.b64encode(b"replacement").decode("ascii")),
        headers=headers,
    )
    assert_error(duplicate, 400, "validation_failed")
    assert stored.read_bytes() == CONTENT
    assert client.get("/api/artifacts", headers=headers).json()["total"] == 1


def test_artifact_http_list_filters_and_pagination(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_job(client, headers)
    first = register_artifact(client, headers, filename="a.fmf")
    second = register_artifact(client, headers, kind="csv", filename="b.csv", content_base64="")
    third = register_artifact(client, headers, filename="c.fmf", job_id=job["id"])

    listed = client.get("/api/artifacts", headers=headers)
    assert listed.status_code == 200
    assert set(listed.json()) == {"items", "total", "next_offset"}
    assert listed.json()["total"] == 3
    assert {item["id"] for item in listed.json()["items"]} == {
        first["id"],
        second["id"],
        third["id"],
    }
    assert listed.json()["next_offset"] is None

    fmf = client.get("/api/artifacts?kind=fmf", headers=headers).json()
    assert {item["id"] for item in fmf["items"]} == {first["id"], third["id"]}
    assert fmf["total"] == 2
    csv_page = client.get("/api/artifacts?kind=csv", headers=headers).json()
    assert [item["id"] for item in csv_page["items"]] == [second["id"]]
    empty = client.get("/api/artifacts?kind=unknown", headers=headers).json()
    assert empty == {"items": [], "total": 0, "next_offset": None}
    linked = client.get(f"/api/artifacts?job_id={job['id']}", headers=headers).json()
    assert [item["id"] for item in linked["items"]] == [third["id"]]
    assert linked["total"] == 1

    page = client.get("/api/artifacts?limit=2&offset=0", headers=headers).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["next_offset"] == 2
    tail = client.get("/api/artifacts?limit=2&offset=2", headers=headers).json()
    assert tail["total"] == 3
    assert len(tail["items"]) == 1
    assert tail["next_offset"] is None
    assert {item["id"] for item in page["items"] + tail["items"]} == {
        first["id"],
        second["id"],
        third["id"],
    }
    beyond = client.get("/api/artifacts?limit=2&offset=99", headers=headers).json()
    assert beyond == {"items": [], "total": 3, "next_offset": None}
    assert client.get("/api/artifacts?limit=256", headers=headers).status_code == 200
    assert client.get("/api/artifacts?offset=2147483647", headers=headers).status_code == 200
    # _query_integer 只要求 ASCII 数字，前导零按十进制解析。
    padded = client.get("/api/artifacts?limit=02&offset=00", headers=headers).json()
    assert padded["total"] == 3
    assert len(padded["items"]) == 2
    assert padded["next_offset"] == 2
    for query in ("limit=1.0", "limit=0", "limit=257", "limit=abc", "offset=-1", "offset=abc"):
        assert_error(client.get(f"/api/artifacts?{query}", headers=headers), 400, "validation_failed")
    for query in ("kind=", f"kind={'x' * 65}"):
        assert_error(client.get(f"/api/artifacts?{query}", headers=headers), 400, "validation_failed")
    invalid_job = urllib.parse.quote("a b", safe="")
    assert_error(
        client.get(f"/api/artifacts?job_id={invalid_job}", headers=headers),
        400,
        "validation_failed",
    )


def test_artifact_http_register_rejects_invalid_base64_filename_and_kind(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    for content_base64 in ("not base64!!", "abc", "中文", "aGVsbG8", "===="):
        response = client.post(
            "/api/artifacts",
            json=artifact_payload(content_base64=content_base64),
            headers=headers,
        )
        assert_error(response, 400, "validation_failed")
    for filename in ("../evil.txt", "a/b.txt", ".hidden", "键.txt", "x" * 129, ""):
        response = client.post(
            "/api/artifacts",
            json=artifact_payload(filename=filename),
            headers=headers,
        )
        assert_error(response, 400, "validation_failed")
    for kind in ("../x", "a/b", "键", "x" * 65, ""):
        response = client.post(
            "/api/artifacts",
            json=artifact_payload(kind=kind),
            headers=headers,
        )
        assert_error(response, 400, "validation_failed")
    for payload in (
        {},
        {"kind": "fmf", "filename": "x.fmf"},
        {"kind": "fmf", "content_base64": CONTENT_BASE64},
        {"kind": 5, "filename": "x.fmf", "content_base64": CONTENT_BASE64},
        {"kind": "fmf", "filename": 5, "content_base64": CONTENT_BASE64},
        {"kind": "fmf", "filename": "x.fmf", "content_base64": ["x"]},
        {**artifact_payload(), "unknown": True},
    ):
        assert_error(client.post("/api/artifacts", json=payload, headers=headers), 400, "validation_failed")

    orphan = client.post(
        "/api/artifacts",
        json=artifact_payload(filename="orphan.fmf", job_id="missingjob"),
        headers=headers,
    )
    assert_error(orphan, 400, "validation_failed")
    assert client.get("/api/artifacts", headers=headers).json()["total"] == 0
    assert not (tmp_path / "evil.txt").exists()
    root = settings.data_dir / "agent" / "artifacts"
    assert not root.exists() or [path for path in root.rglob("*") if path.is_file()] == []


def test_artifact_http_register_size_limit_boundary(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    oversized = base64.b64encode(b"\0" * (SIZE_LIMIT + 1)).decode("ascii")
    response = client.post(
        "/api/artifacts",
        json=artifact_payload(filename="too-big.bin", content_base64=oversized),
        headers=headers,
    )
    assert_error(response, 413, "payload_too_large")
    assert client.get("/api/artifacts", headers=headers).json()["total"] == 0

    exact = base64.b64encode(b"\0" * SIZE_LIMIT).decode("ascii")
    created = register_artifact(client, headers, filename="exact.bin", content_base64=exact)
    assert created["bytes"] == SIZE_LIMIT
    assert Path(created["path"]).stat().st_size == SIZE_LIMIT


def test_artifact_http_register_accepts_nonzero_base64_padding_bits(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)

    # Python 的 base64 解码不校验尾部填充位：非规范输入 AB== 与规范编码 AA== 同样解出 b"\x00"。
    created = register_artifact(client, headers, filename="pad.bin", content_base64="AB==")

    assert created["bytes"] == 1
    assert created["sha256"] == hashlib.sha256(b"\x00").hexdigest()
    assert Path(created["path"]).read_bytes() == b"\x00"


def test_artifact_http_missing_detail_content_and_invalid_identifiers(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)

    detail_error = assert_error(client.get("/api/artifacts/missing", headers=headers), 404, "not_found")
    content_error = assert_error(
        client.get("/api/artifacts/missing/content", headers=headers), 404, "not_found"
    )
    delete_error = assert_error(client.delete("/api/artifacts/missing", headers=headers), 404, "not_found")
    assert {detail_error["message"], content_error["message"], delete_error["message"]} == {"产物不存在"}

    for identifier in ("存档", "a b", "x" * 65):
        quoted = urllib.parse.quote(identifier, safe="")
        assert_error(client.get(f"/api/artifacts/{quoted}", headers=headers), 400, "validation_failed")
        assert_error(
            client.get(f"/api/artifacts/{quoted}/content", headers=headers),
            400,
            "validation_failed",
        )
        assert_error(client.delete(f"/api/artifacts/{quoted}", headers=headers), 400, "validation_failed")


def test_artifact_http_content_missing_file_is_not_found(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = register_artifact(client, headers)
    Path(created["path"]).unlink()

    error = assert_error(
        client.get(f"/api/artifacts/{created['id']}/content", headers=headers), 404, "not_found"
    )
    assert error["message"] == "产物文件不存在"
    detail = client.get(f"/api/artifacts/{created['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json() == created


def test_artifact_http_content_rejects_record_path_outside_root(tmp_path: Path, monkeypatch):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = register_artifact(client, headers)
    outside = tmp_path / "outside-secret.txt"
    outside.write_bytes(b"OUTSIDE SECRET")

    tamper_artifact_path(app, created["id"], str(outside))
    response = client.get(f"/api/artifacts/{created['id']}/content", headers=headers)
    error = assert_error(response, 404, "not_found")
    assert error["message"] == "产物文件不存在"
    assert b"OUTSIDE SECRET" not in response.content
    assert "etag" not in response.headers

    monkeypatch.chdir(tmp_path)
    (tmp_path / "leak.txt").write_bytes(b"CWD SECRET")
    tamper_artifact_path(app, created["id"], "leak.txt")
    response = client.get(f"/api/artifacts/{created['id']}/content", headers=headers)
    error = assert_error(response, 404, "not_found")
    assert error["message"] == "产物文件不存在"
    assert b"CWD SECRET" not in response.content
    assert "etag" not in response.headers


def test_artifact_http_content_rejects_symlink_swap(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = register_artifact(client, headers)
    stored = Path(created["path"])
    outside = tmp_path / "outside-secret.txt"
    outside.write_bytes(b"SYMLINK SECRET")

    stored.unlink()
    stored.symlink_to(outside)
    response = client.get(f"/api/artifacts/{created['id']}/content", headers=headers)
    error = assert_error(response, 404, "not_found")
    assert error["message"] == "产物文件不存在"
    assert b"SYMLINK SECRET" not in response.content
    assert "etag" not in response.headers

    inside = register_artifact(client, headers, filename="inside.fmf")
    stored.unlink()
    stored.symlink_to(Path(inside["path"]))
    response = client.get(f"/api/artifacts/{created['id']}/content", headers=headers)
    assert_error(response, 404, "not_found")
    assert b"hello world" not in response.content


def test_artifact_http_content_rejects_parent_directory_escape(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = register_artifact(client, headers)
    stored = Path(created["path"])
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / stored.name).write_bytes(b"PARENT SECRET")
    shutil.rmtree(stored.parent)
    stored.parent.symlink_to(outside_dir)

    response = client.get(f"/api/artifacts/{created['id']}/content", headers=headers)
    error = assert_error(response, 404, "not_found")
    assert error["message"] == "产物文件不存在"
    assert b"PARENT SECRET" not in response.content
    assert "etag" not in response.headers


def test_artifact_http_delete_removes_record_and_file(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = register_artifact(client, headers)
    stored = Path(created["path"])

    removed = client.delete(f"/api/artifacts/{created['id']}", headers=headers)

    assert removed.status_code == 204
    assert removed.content == b""
    assert "content-type" not in removed.headers
    assert not stored.exists()
    assert_error(client.get(f"/api/artifacts/{created['id']}", headers=headers), 404, "not_found")
    assert_error(client.get(f"/api/artifacts/{created['id']}/content", headers=headers), 404, "not_found")
    assert_error(client.delete(f"/api/artifacts/{created['id']}", headers=headers), 404, "not_found")
    assert client.get("/api/artifacts", headers=headers).json() == {
        "items": [],
        "total": 0,
        "next_offset": None,
    }


def test_artifact_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    paths = document["paths"]
    for path in (
        "/api/artifacts",
        "/api/artifacts/{artifact_id}",
        "/api/artifacts/{artifact_id}/content",
    ):
        assert path in paths

    for path, operations in paths.items():
        if not path.startswith("/api/artifacts"):
            continue
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            assert operation["security"] == [{"HTTPBearer": []}], (path, method)
            assert "422" not in operation["responses"], (path, method)
            for status in ("400", "401"):
                schema = operation["responses"][status]["content"]["application/json"]["schema"]
                assert schema["$ref"].endswith("ErrorEnvelope"), (path, method, status)

    list_operation = paths["/api/artifacts"]["get"]
    parameters = {item["name"]: item["schema"] for item in list_operation["parameters"]}
    assert {"kind", "job_id"} <= set(parameters)
    assert parameters["limit"]["type"] == "integer"
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 256
    assert parameters["limit"]["default"] == 50
    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["default"] == 0
    assert list_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ArtifactListOutput"
    )
    create_operation = paths["/api/artifacts"]["post"]
    assert create_operation["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ArtifactOutput"
    )
    for status in ("400", "413"):
        schema = create_operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope"), status
    member_operations = paths["/api/artifacts/{artifact_id}"]
    for method in ("get", "delete"):
        assert member_operations[method]["security"] == [{"HTTPBearer": []}]
        schema = member_operations[method]["responses"]["404"]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope")
    assert member_operations["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("ArtifactOutput")
    content_operation = paths["/api/artifacts/{artifact_id}/content"]["get"]
    assert "200" in content_operation["responses"]
    assert "application/octet-stream" in content_operation["responses"]["200"]["content"]
    assert content_operation["responses"]["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorEnvelope"
    )

    components = document["components"]["schemas"]
    output_schema = components["ArtifactOutput"]
    assert set(output_schema["properties"]) == ARTIFACT_FIELDS
    assert set(output_schema["required"]) == ARTIFACT_FIELDS
    register_input = components["ArtifactRegisterInput"]
    assert set(register_input["properties"]) == {"kind", "filename", "content_base64", "job_id"}
    assert set(register_input["required"]) == {"kind", "filename", "content_base64"}
    assert register_input["additionalProperties"] is False


def test_artifact_http_cors_405_and_existing_routes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    preflight = client.options(
        "/api/artifacts",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert preflight.status_code == 200
    allowed_methods = preflight.headers["access-control-allow-methods"]
    assert "GET" in allowed_methods and "POST" in allowed_methods

    wrong = client.put("/api/artifacts", headers=headers)
    assert wrong.status_code == 405
    allowed = {item.strip() for item in wrong.headers["allow"].split(",")}
    assert {"GET", "POST"} <= allowed
    wrong_member = client.put("/api/artifacts/x", headers=headers)
    assert wrong_member.status_code == 405
    member_methods = {item.strip() for item in wrong_member.headers["allow"].split(",")}
    assert {"GET", "DELETE"} <= member_methods
    wrong_content = client.post("/api/artifacts/x/content", headers=headers)
    assert wrong_content.status_code == 405
    assert "GET" in {item.strip() for item in wrong_content.headers["allow"].split(",")}

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/version").status_code == 200
    assert client.get("/api/jobs", headers=headers).json()["items"] == []
    assert client.get("/api/pools", headers=headers).json()["items"] == []
    assert client.get("/api/drafts", headers=headers).json()["items"] == []
    assert client.get("/api/saves", headers=headers).json()["items"] == []
