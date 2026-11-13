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
from fm27lab.interfaces.http.routes.fmf import FmfService
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
