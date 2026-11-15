"""定位球 HTTP 路由测试。"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.application.setpieces import (
    DOCUMENT_SCHEMA,
    DOCUMENT_TARGET_ERROR,
    ENGINE_UNAVAILABLE_CODE,
    ENGINE_UNAVAILABLE_MESSAGE,
    UNKNOWN_SETPIECE_MESSAGE,
)
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import create_app
from fm27lab.tests.test_scenario_assets import write_engine_root

TOKEN = "c" * 64
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


def make_app(tmp_path: Path, *, engine_root: Path | None = None, with_engine: bool = True):
    if with_engine and engine_root is None:
        engine_root = write_engine_root(tmp_path)
    settings = Settings.create(
        data_dir=tmp_path / "data",
        token=TOKEN,
        engine_root=engine_root if with_engine else None,
        dev=True,
    )
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    return TestClient(create_app(settings, database)), settings


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()["error"]
    assert set(body) == ERROR_FIELDS
    assert body["code"] == code
    assert body["retriable"] is (status >= 500)
    return body


ENDPOINTS = (
    ("GET", "/api/setpieces", None),
    ("GET", "/api/setpieces/home", None),
    ("PATCH", "/api/setpieces/home", {"value": {}}),
    ("POST", "/api/setpieces/home/import-file", {"content_base64": "e30="}),
    ("GET", "/api/setpieces/home/export-file", None),
)


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_endpoints_require_token(tmp_path, method, path, body):
    client, _settings = make_app(tmp_path)
    response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert_error(response, 401, "unauthorized")


def test_list_returns_catalog_and_both_sides(tmp_path):
    client, settings = make_app(tmp_path)
    response = client.get("/api/setpieces", headers=auth(settings))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["catalog"]["types"]) == 10
    assert [item["setpiece_id"] for item in payload["setpieces"]] == ["home", "away"]
    assert all(item["configured"] is False for item in payload["setpieces"])


def test_get_returns_default_value(tmp_path):
    client, settings = make_app(tmp_path)
    response = client.get("/api/setpieces/home", headers=auth(settings))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["setpiece_id"] == "home"
    assert payload["roster_size"] == 23
    assert payload["value"]["throw_styles"] == [0, 1, 0]
    assert payload["default"] == payload["value"]


def test_get_unknown_setpiece_returns_404(tmp_path):
    client, settings = make_app(tmp_path)
    body = assert_error(
        client.get("/api/setpieces/neutral", headers=auth(settings)), 404, "not_found"
    )
    assert body["message"] == UNKNOWN_SETPIECE_MESSAGE


def test_get_invalid_setpiece_id_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    assert_error(client.get("/api/setpieces/bad id", headers=auth(settings)), 400, "validation_failed")


def test_patch_saves_validated_value(tmp_path):
    client, settings = make_app(tmp_path)
    detail = client.get("/api/setpieces/home", headers=auth(settings)).json()
    value = detail["value"]
    value["throw_styles"] = [1, 1, 0]
    response = client.patch("/api/setpieces/home", headers=auth(settings), json={"value": value})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["configured"] is True
    assert payload["updated_at"] is not None
    assert payload["value"]["throw_styles"] == [1, 1, 0]

    reloaded = client.get("/api/setpieces/home", headers=auth(settings)).json()
    assert reloaded["configured"] is True
    assert reloaded["value"]["throw_styles"] == [1, 1, 0]


def test_patch_unknown_setpiece_returns_404(tmp_path):
    client, settings = make_app(tmp_path)
    response = client.patch(
        "/api/setpieces/neutral", headers=auth(settings), json={"value": {}}
    )
    assert_error(response, 404, "not_found")


def test_patch_missing_value_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    body = assert_error(
        client.patch("/api/setpieces/home", headers=auth(settings), json={}),
        400,
        "validation_failed",
    )
    assert body["message"] == "定位球更新请求缺少 value 字段"


def test_patch_unknown_field_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    response = client.patch(
        "/api/setpieces/home", headers=auth(settings), json={"value": {}, "extra": 1}
    )
    body = assert_error(response, 400, "validation_failed")
    assert "extra" in body["message"]


def test_patch_invalid_value_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    response = client.patch("/api/setpieces/home", headers=auth(settings), json={"value": []})
    body = assert_error(response, 400, "validation_failed")
    assert body["message"] == "定位球设置格式错误"


def test_patch_invalid_throw_styles_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    detail = client.get("/api/setpieces/home", headers=auth(settings)).json()
    value = detail["value"]
    value["throw_styles"] = [0, 1]
    response = client.patch("/api/setpieces/home", headers=auth(settings), json={"value": value})
    body = assert_error(response, 400, "validation_failed")
    assert body["message"] == "界外球必须包含后场、中场和前场三种策略"


def test_export_returns_json_attachment(tmp_path):
    client, settings = make_app(tmp_path)
    response = client.get("/api/setpieces/home/export-file", headers=auth(settings))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == 'attachment; filename="setpieces-home.json"'
    assert response.headers["etag"] == f'"{hashlib.sha256(response.content).hexdigest()}"'
    document = json.loads(response.content)
    assert document["schema"] == DOCUMENT_SCHEMA
    assert document["setpiece_id"] == "home"
    assert document["value"]["throw_styles"] == [0, 1, 0]


def test_export_unknown_setpiece_returns_404(tmp_path):
    client, settings = make_app(tmp_path)
    assert_error(
        client.get("/api/setpieces/neutral/export-file", headers=auth(settings)), 404, "not_found"
    )


def test_import_base64_document_round_trip(tmp_path):
    client, settings = make_app(tmp_path)
    detail = client.get("/api/setpieces/home", headers=auth(settings)).json()
    value = detail["value"]
    value["throw_styles"] = [0, 0, 1]
    client.patch("/api/setpieces/home", headers=auth(settings), json={"value": value})
    exported = client.get("/api/setpieces/home/export-file", headers=auth(settings)).content

    other, other_settings = make_app(tmp_path / "other")
    encoded = base64.b64encode(exported).decode("ascii")
    response = other.post(
        "/api/setpieces/home/import-file",
        headers=auth(other_settings),
        json={"content_base64": encoded},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["configured"] is True
    assert payload["value"]["throw_styles"] == [0, 0, 1]


def test_import_source_path_document(tmp_path):
    client, settings = make_app(tmp_path)
    document = {
        "schema": DOCUMENT_SCHEMA,
        "setpiece_id": "away",
        "value": client.get("/api/setpieces/away", headers=auth(settings)).json()["value"],
    }
    path = tmp_path / "setpieces-away.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    response = client.post(
        "/api/setpieces/away/import-file",
        headers=auth(settings),
        json={"source_path": str(path)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is True


def test_import_target_mismatch_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    exported = client.get("/api/setpieces/home/export-file", headers=auth(settings)).content
    response = client.post(
        "/api/setpieces/away/import-file",
        headers=auth(settings),
        json={"content_base64": base64.b64encode(exported).decode("ascii")},
    )
    body = assert_error(response, 400, "validation_failed")
    assert body["message"] == DOCUMENT_TARGET_ERROR


def test_import_requires_exactly_one_source(tmp_path):
    client, settings = make_app(tmp_path)
    body = assert_error(
        client.post("/api/setpieces/home/import-file", headers=auth(settings), json={}),
        400,
        "validation_failed",
    )
    assert body["message"] == "定位球导入请求必须提供 content_base64 或 source_path 之一"
    both = assert_error(
        client.post(
            "/api/setpieces/home/import-file",
            headers=auth(settings),
            json={"content_base64": "e30=", "source_path": "/tmp/x.json"},
        ),
        400,
        "validation_failed",
    )
    assert both["message"] == "定位球导入请求只能提供 content_base64 或 source_path 之一"


def test_import_invalid_base64_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    body = assert_error(
        client.post(
            "/api/setpieces/home/import-file",
            headers=auth(settings),
            json={"content_base64": "不是base64"},
        ),
        400,
        "validation_failed",
    )
    assert body["message"] == "定位球文档内容不是合法的 base64"


def test_import_unknown_field_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    body = assert_error(
        client.post(
            "/api/setpieces/home/import-file",
            headers=auth(settings),
            json={"content_base64": "e30=", "bogus": True},
        ),
        400,
        "validation_failed",
    )
    assert "bogus" in body["message"]


def test_import_missing_file_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    body = assert_error(
        client.post(
            "/api/setpieces/home/import-file",
            headers=auth(settings),
            json={"source_path": str(tmp_path / "missing.json")},
        ),
        400,
        "validation_failed",
    )
    assert body["message"] == "定位球文档文件不存在"


def test_import_normalization_error_returns_400(tmp_path):
    client, settings = make_app(tmp_path)
    document = json.dumps({"value": {"throw_styles": [0, 1]}}).encode("utf-8")
    body = assert_error(
        client.post(
            "/api/setpieces/home/import-file",
            headers=auth(settings),
            json={"content_base64": base64.b64encode(document).decode("ascii")},
        ),
        400,
        "validation_failed",
    )
    assert body["message"] == "界外球必须包含后场、中场和前场三种策略"


def test_engine_not_configured_returns_503(tmp_path):
    client, settings = make_app(tmp_path, with_engine=False)
    body = assert_error(client.get("/api/setpieces", headers=auth(settings)), 503, ENGINE_UNAVAILABLE_CODE)
    assert body["message"] == ENGINE_UNAVAILABLE_MESSAGE
    assert body["retriable"] is True
    assert str(tmp_path) not in json.dumps(body, ensure_ascii=False)


def test_damaged_engine_root_returns_503(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    client, settings = make_app(tmp_path, engine_root=broken)
    assert_error(
        client.get("/api/setpieces/home", headers=auth(settings)), 503, ENGINE_UNAVAILABLE_CODE
    )


def test_openapi_declares_setpieces_operations(tmp_path):
    client, _settings = make_app(tmp_path)
    paths = client.app.openapi()["paths"]
    assert paths["/api/setpieces"]["get"]
    assert paths["/api/setpieces/{setpiece_id}"]["get"]
    assert paths["/api/setpieces/{setpiece_id}"]["patch"]
    assert paths["/api/setpieces/{setpiece_id}/import-file"]["post"]
    assert paths["/api/setpieces/{setpiece_id}/export-file"]["get"]
