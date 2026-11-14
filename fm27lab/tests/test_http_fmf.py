"""FMF 导入导出 HTTP 接口契约测试。"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

from fm27lab.adapters.fmf import FmfCodec
from fm27lab.domain.scenario import normalize_scenario
from fm27lab.interfaces.http.app import create_app
from fm27lab.interfaces.http.routes.fmf import (
    MAX_FMF_BYTES,
    FmfFileImportInput,
    FmfService,
)
from fm27lab.ports.fmf import FMF_LENGTH_BYTES, FMF_MAGIC
from fm27lab.tests.test_http_drafts import auth, scenario
from fm27lab.tests.test_http_health import make_app

ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


def _frame(payload: object) -> bytes:
    document = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return FMF_MAGIC + len(document).to_bytes(FMF_LENGTH_BYTES, "big") + document


EXPORT_PATH = "/api/drafts/{draft_id}/export.fmf"
IMPORT_PATH = "/api/drafts/import-fmf"


def create_draft(client: TestClient, headers: dict[str, str], *, name: str = "Draft", count: int = 23):
    response = client.post(
        "/api/drafts",
        json={"name": name, "scenario": scenario(count), "source": {"kind": "inline"}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def export(client: TestClient, headers: dict[str, str], draft_id: str):
    return client.get(f"/api/drafts/{draft_id}/export.fmf", headers=headers)


def import_fmf(
    client: TestClient,
    headers: dict[str, str],
    payload: bytes,
    *,
    name: str = "Imported",
    source: dict | None = None,
):
    body: dict = {"name": name, "content_base64": base64.b64encode(payload).decode("ascii")}
    if source is not None:
        body["source"] = source
    return client.post(IMPORT_PATH, json=body, headers=headers)


def error_of(response) -> dict:
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    return error


def test_fmf_http_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    draft = create_draft(client, auth(settings))
    denied = client.get(f"/api/drafts/{draft['id']}/export.fmf")
    assert denied.status_code == 401
    assert error_of(denied)["code"] == "unauthorized"
    assert (
        client.get(
            f"/api/drafts/{draft['id']}/export.fmf", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    body = {"name": "x", "content_base64": base64.b64encode(b"FMFV2").decode("ascii")}
    assert client.post(IMPORT_PATH, json=body).status_code == 401
    assert client.post(IMPORT_PATH, json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_fmf_http_export_returns_attachment_with_sha256_etag(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    draft = create_draft(client, headers, name="Home Plan")
    response = export(client, headers, draft["id"])
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/octet-stream"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="Home Plan.fmf"' in disposition
    payload = response.content
    assert payload[: len(FMF_MAGIC)] == FMF_MAGIC
    assert response.headers["etag"] == f'"{hashlib.sha256(payload).hexdigest()}"'
    assert FmfCodec().decode(payload) == draft["scenario"]
    repeated = export(client, headers, draft["id"])
    assert repeated.content == payload
    assert repeated.headers["etag"] == response.headers["etag"]


def test_fmf_http_export_missing_draft_is_not_found(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    response = export(client, auth(settings), "missing-draft")
    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


def test_fmf_http_import_round_trip_creates_draft(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    source_draft = create_draft(client, headers, name="Home Plan")
    payload = export(client, headers, source_draft["id"]).content
    response = import_fmf(client, headers, payload, name="Imported Plan", source={"kind": "fmf"})
    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["name"] == "Imported Plan"
    assert imported["source"] == {"kind": "fmf"}
    assert imported["scenario"] == source_draft["scenario"]
    listed = client.get("/api/drafts", headers=headers).json()
    assert {item["id"] for item in listed["items"]} == {source_draft["id"], imported["id"]}
    assert listed["total"] == 2
    assert export(client, headers, imported["id"]).content == payload


def test_fmf_http_export_preserves_scenario_and_import_normalizes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    source_draft = create_draft(client, headers, count=26)
    payload = export(client, headers, source_draft["id"]).content
    assert FmfCodec().decode(payload) == source_draft["scenario"]
    imported = import_fmf(client, headers, payload).json()
    assert imported["scenario"] == normalize_scenario(source_draft["scenario"])
    assert imported["scenario"]["teams"][0]["roster_trim"]["source_size"] == 23


def test_fmf_http_import_rejects_invalid_payloads(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    cases = (
        ({"name": "x", "content_base64": "not base64!!"}, "FMF 文件内容不是合法的 base64"),
        ({"name": "x", "content_base64": ""}, "FMF 文件无效"),
        (
            {"name": "x", "content_base64": base64.b64encode(b"FMFV1\x00\x00\x00\x02{}").decode("ascii")},
            "FMF 文件无效",
        ),
        (
            {"name": "x", "content_base64": base64.b64encode(b"FMFV2").decode("ascii")},
            "FMF 文件无效",
        ),
        (
            {
                "name": "x",
                "content_base64": base64.b64encode(FMF_MAGIC + (9).to_bytes(4, "big") + b"{}").decode(
                    "ascii"
                ),
            },
            "FMF 文件无效",
        ),
        (
            {
                "name": "x",
                "content_base64": base64.b64encode(FMF_MAGIC + (2).to_bytes(4, "big") + b"[]").decode(
                    "ascii"
                ),
            },
            "FMF 文件无效",
        ),
    )
    for body, message in cases:
        response = client.post(IMPORT_PATH, json=body, headers=headers)
        assert response.status_code == 400, body
        error = error_of(response)
        assert error["code"] == "validation_failed"
        assert error["message"] == message
        assert error["retriable"] is False


def test_fmf_http_import_rejects_payload_over_four_mebibytes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    oversized = base64.b64encode(b"\x00" * (4 * 1024 * 1024 + 1)).decode("ascii")
    response = client.post(
        IMPORT_PATH,
        json={"name": "x", "content_base64": oversized},
        headers=auth(settings),
    )
    assert response.status_code == 400
    assert error_of(response)["message"] == "FMF 文件超过 4 MiB 上限"


def test_fmf_http_import_body_validation(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    for body in (
        {"content_base64": "Rk1GVjI="},
        {"name": "", "content_base64": "Rk1GVjI="},
        {"name": "x", "content_base64": "Rk1GVjI=", "unknown": True},
        {"name": "x", "content_base64": 1},
        {"name": "x"},
    ):
        response = client.post(IMPORT_PATH, json=body, headers=headers)
        assert response.status_code == 400, body
        assert error_of(response)["code"] == "validation_failed"


def test_fmf_http_export_escapes_attachment_filename(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    non_ascii = create_draft(client, headers, name="主场 计划")
    disposition = export(client, headers, non_ascii["id"]).headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    encoded = disposition.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == "主场 计划.fmf"
    unsafe = create_draft(client, headers, name='ev"il:name')
    header = export(client, headers, unsafe["id"]).headers["content-disposition"]
    assert 'filename="evilname.fmf"' in header


def test_fmf_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    assert EXPORT_PATH in document["paths"]
    assert IMPORT_PATH in document["paths"]
    export_operation = document["paths"][EXPORT_PATH]["get"]
    assert "422" not in export_operation["responses"]
    assert export_operation["security"] == [{"HTTPBearer": []}]
    for status in ("400", "401", "404"):
        schema = export_operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope")
    assert "application/octet-stream" in export_operation["responses"]["200"]["content"]
    import_operation = document["paths"][IMPORT_PATH]["post"]
    assert "422" not in import_operation["responses"]
    assert import_operation["security"] == [{"HTTPBearer": []}]
    schema = import_operation["responses"]["201"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("DraftOutput")
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_fmf_http_uses_injected_service(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    assert isinstance(app.state.fmf_service, FmfService)

    class StubFmf:
        def __init__(self) -> None:
            self.exported: list[str] = []

        def export(self, draft_id: str):
            if draft_id != "stub":
                return None
            self.exported.append(draft_id)
            return ({"name": "Stub"}, b"binary-fmf")

        def import_draft(self, name, content_base64, source=None):
            return {
                "id": "stub",
                "name": name,
                "source": source or {},
                "scenario": {},
                "created_at": "a",
                "updated_at": "a",
            }

    stub = StubFmf()
    second = create_app(settings, database, fmf_service=stub)
    client = TestClient(second)
    headers = auth(settings)
    response = client.get("/api/drafts/stub/export.fmf", headers=headers)
    assert response.status_code == 200
    assert response.content == b"binary-fmf"
    assert stub.exported == ["stub"]
    assert client.get("/api/drafts/none/export.fmf", headers=headers).status_code == 404
    imported = client.post(
        IMPORT_PATH,
        json={"name": "Injected", "content_base64": "AA=="},
        headers=headers,
    )
    assert imported.status_code == 201
    assert imported.json()["name"] == "Injected"


def test_fmf_import_rejects_payloads_that_fail_normalization(tmp_path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    payload = scenario(23)
    for team in payload["teams"]:
        for player in team["players"]:
            player["attributes"] = {f"key{index}": 10 for index in range(20)}
    content = base64.b64encode(_frame(payload)).decode("ascii")
    response = client.post(
        "/api/drafts/import-fmf",
        json={"name": "坏文件", "content_base64": content},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"
    assert client.get("/api/drafts", headers=headers).json()["total"] == 0


IMPORT_FILE_PATH = "/api/drafts/import-fmf-file"


def import_fmf_file(
    client: TestClient,
    headers: dict[str, str],
    source_path: str,
    *,
    name: str | None = None,
):
    body: dict = {"source_path": source_path}
    if name is not None:
        body["name"] = name
    return client.post(IMPORT_FILE_PATH, json=body, headers=headers)


def export_to_file(
    tmp_path: Path,
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "Draft",
) -> tuple[dict, Path]:
    draft = create_draft(client, headers, name=name)
    path = tmp_path / f"{name}.fmf"
    path.write_bytes(export(client, headers, draft["id"]).content)
    return draft, path


def test_fmf_file_http_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    _, path = export_to_file(tmp_path, client, auth(settings))
    body = {"source_path": str(path)}
    denied = client.post(IMPORT_FILE_PATH, json=body)
    assert denied.status_code == 401
    assert error_of(denied)["code"] == "unauthorized"
    wrong = client.post(IMPORT_FILE_PATH, json=body, headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401


def test_fmf_file_http_imports_exported_file_and_derives_name(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    source, path = export_to_file(tmp_path, client, headers, name="主场 战术")
    response = import_fmf_file(client, headers, str(path))
    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["name"] == "主场 战术"
    assert imported["scenario"] == source["scenario"]
    assert imported["source"] == {"kind": "fmf", "path": str(path)}
    assert export(client, headers, imported["id"]).content == path.read_bytes()
    assert client.get("/api/drafts", headers=headers).json()["total"] == 2


def test_fmf_file_http_import_keeps_explicit_name(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    _, path = export_to_file(tmp_path, client, headers)
    response = import_fmf_file(client, headers, str(path), name="导入 计划")
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "导入 计划"


def test_fmf_file_http_import_cleans_quoted_and_padded_path(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    _, path = export_to_file(tmp_path, client, headers)
    for wrapped in (f'"{path}"', f"'{path}'", f'  "{path}"  ', f"  {path}  "):
        response = import_fmf_file(client, headers, wrapped)
        assert response.status_code == 201, wrapped
        assert response.json()["source"] == {"kind": "fmf", "path": str(path)}


def test_fmf_file_http_import_missing_path_is_validation_error(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    target = tmp_path / "missing.fmf"
    for value in (str(target), str(tmp_path), f'"{target}', f"'{target}"):
        response = import_fmf_file(client, headers, value)
        assert response.status_code == 400, value
        error = error_of(response)
        assert error["code"] == "validation_failed"
        assert error["message"] == "战术文件不存在"
        assert error["retriable"] is False
    assert client.get("/api/drafts", headers=headers).json()["total"] == 0


def test_fmf_file_http_import_rejects_file_over_four_mebibytes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    oversized = tmp_path / "oversized.fmf"
    oversized.write_bytes(b"\x00" * (MAX_FMF_BYTES + 1))
    response = import_fmf_file(client, headers, str(oversized))
    assert response.status_code == 400
    error = error_of(response)
    assert error["code"] == "validation_failed"
    assert error["message"] == "FMF 文件超过 4 MiB 上限"
    assert client.get("/api/drafts", headers=headers).json()["total"] == 0


def test_fmf_file_http_import_rejects_corrupt_file(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    path = tmp_path / "corrupt.fmf"
    path.write_bytes(b"not an fmf document")
    response = import_fmf_file(client, headers, str(path))
    assert response.status_code == 400
    assert error_of(response)["message"] == "FMF 文件无效"
    assert client.get("/api/drafts", headers=headers).json()["total"] == 0


def test_fmf_file_http_import_unreadable_file_is_validation_error(tmp_path: Path, monkeypatch):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    path = tmp_path / "denied.fmf"
    path.write_bytes(b"fmf")

    def deny(_self: Path) -> bytes:
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(Path, "read_bytes", deny)
    response = import_fmf_file(client, headers, str(path))
    assert response.status_code == 400
    error = error_of(response)
    assert error["code"] == "validation_failed"
    assert error["message"] == "战术文件无法读取：拒绝访问"


def test_fmf_file_http_import_body_validation(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    _, path = export_to_file(tmp_path, client, headers)
    for body in (
        {},
        {"source_path": ""},
        {"source_path": 0},
        {"source_path": "x" * 4097},
        {"source_path": str(path), "unknown": True},
        {"source_path": str(path), "name": ""},
        {"source_path": str(path), "name": "x" * 81},
    ):
        response = client.post(IMPORT_FILE_PATH, json=body, headers=headers)
        assert response.status_code == 400, body
        assert error_of(response)["code"] == "validation_failed"
    assert client.get("/api/drafts", headers=headers).json()["total"] == 1


def test_fmf_file_import_input_is_strict():
    assert FmfFileImportInput.model_config.get("strict") is True
    assert FmfFileImportInput.model_config.get("extra") == "forbid"
    assert FmfFileImportInput.model_fields["source_path"].is_required()


def test_fmf_file_service_derives_and_truncates_names(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    _, path = export_to_file(tmp_path, client, headers, name="Home Plan")
    service = app.state.fmf_service
    assert isinstance(service, FmfService)
    assert service.import_draft_file("长" * 100, str(path))["name"] == "长" * 80
    long_stem = tmp_path / ("long" * 30 + ".fmf")
    long_stem.write_bytes(path.read_bytes())
    assert service.import_draft_file(None, str(long_stem))["name"] == ("long" * 30)[:80]
    anonymous = tmp_path / "   .fmf"
    anonymous.write_bytes(path.read_bytes())
    assert service.import_draft_file(None, str(anonymous))["name"] == "导入战术"
    assert service.import_draft_file("   ", str(path))["name"] == "Home Plan"


def test_fmf_file_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    assert IMPORT_FILE_PATH in document["paths"]
    operation = document["paths"][IMPORT_FILE_PATH]["post"]
    assert "422" not in operation["responses"]
    assert operation["security"] == [{"HTTPBearer": []}]
    for status in ("400", "401"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope")
    created = operation["responses"]["201"]["content"]["application/json"]["schema"]
    assert created["$ref"].endswith("DraftOutput")
    model = document["components"]["schemas"]["FmfFileImportInput"]
    assert model["additionalProperties"] is False
    assert set(model["properties"]) == {"source_path", "name"}
