from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.tests.test_http_health import make_app

GIB = 1024**3
SETTING_FIELDS = {"key", "value", "note", "updated_at"}
CHECK_FIELDS = {
    "allowed",
    "code",
    "recommended_workers",
    "warnings",
    "memory_required_bytes",
    "disk_required_bytes",
}
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
OVERRIDE_WARNING = "已按显式覆盖运行"
ABOVE_RECOMMENDED_WARNING = "并行数高于推荐值，收益不保证"
CHECK_QUERY = {
    "workers": "4",
    "cpu_count": "8",
    "available_memory_bytes": str(32 * GIB),
    "free_disk_bytes": str(100 * GIB),
    "allow_oversubscription": "false",
}


def auth(settings) -> dict:
    return {"Authorization": f"Bearer {settings.token}"}


def check_url(**overrides) -> str:
    values = dict(CHECK_QUERY)
    for name, value in overrides.items():
        if value is None:
            values.pop(name)
        else:
            values[name] = value
    query = "&".join(f"{name}={value}" for name, value in values.items())
    return f"/api/concurrency/check?{query}"


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == code
    assert error["details"] is None
    return error


def put_setting(client, headers, key: str, **body):
    return client.put(f"/api/settings/{key}", json=body, headers=headers)


def nested_value(depth: int) -> object:
    value: object = 0
    for _ in range(depth):
        value = [value]
    return value


def raw_nested_body(depth: int) -> bytes:
    return b'{"value":' + b"[" * depth + b"0" + b"]" * depth + b"}"


def test_settings_and_concurrency_http_require_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    requests = (
        client.get("/api/settings"),
        client.get("/api/settings/match.roster_size"),
        client.put("/api/settings/match.roster_size", json={"value": 23}),
        client.delete("/api/settings/match.roster_size"),
        client.get(check_url()),
    )
    for response in requests:
        error = assert_error(response, 401, "unauthorized")
        assert error["retriable"] is False
        assert response.headers["www-authenticate"] == "Bearer"
    wrong = client.get("/api/settings", headers={"Authorization": "Bearer wrong"})
    assert_error(wrong, 401, "unauthorized")
    lower = client.get("/api/settings", headers={"Authorization": f"bearer {settings.token}"})
    assert lower.status_code == 200


def test_settings_http_crud_round_trip(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)

    empty = client.get("/api/settings", headers=headers)
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "total": 0}

    created = put_setting(
        client,
        headers,
        "match.roster_size",
        value={"size": 23, "labels": ["主", "客"]},
        note="fixed",
    )
    assert created.status_code == 200
    entry = created.json()
    assert set(entry) == SETTING_FIELDS
    assert entry["key"] == "match.roster_size"
    assert entry["value"] == {"size": 23, "labels": ["主", "客"]}
    assert entry["note"] == "fixed"
    assert entry["updated_at"].endswith("+00:00")

    fetched = client.get("/api/settings/match.roster_size", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == entry
    listed = client.get("/api/settings", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"items": [entry], "total": 1}

    updated = put_setting(client, headers, "match.roster_size", value=24)
    assert updated.status_code == 200
    assert updated.json()["value"] == 24
    assert updated.json()["note"] is None
    assert client.get("/api/settings", headers=headers).json()["total"] == 1
    repeated = put_setting(client, headers, "match.roster_size", value=24)
    assert repeated.status_code == 200
    assert repeated.json()["value"] == 24
    assert client.get("/api/settings", headers=headers).json()["total"] == 1

    removed = client.delete("/api/settings/match.roster_size", headers=headers)
    assert removed.status_code == 204
    assert removed.content == b""
    assert "content-type" not in removed.headers
    assert_error(client.get("/api/settings/match.roster_size", headers=headers), 404, "not_found")
    assert_error(client.delete("/api/settings/match.roster_size", headers=headers), 404, "not_found")
    assert client.get("/api/settings", headers=headers).json() == {"items": [], "total": 0}


def test_settings_http_rejects_invalid_keys(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    for key in ("Bad-Key", "1bad", "bad%20key"):
        for response in (
            client.get(f"/api/settings/{key}", headers=headers),
            put_setting(client, headers, key, value=1),
            client.delete(f"/api/settings/{key}", headers=headers),
        ):
            error = assert_error(response, 400, "validation_failed")
            assert "设置键" in error["message"]
    assert client.get("/api/settings", headers=headers).json() == {"items": [], "total": 0}


def test_settings_http_rejects_invalid_payloads(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    invalid_bodies = (
        {},
        {"note": "missing value"},
        {"value": 1, "extra": True},
        {"value": 1, "note": 7},
        [1, 2],
    )
    for body in invalid_bodies:
        response = client.put("/api/settings/bad.value", json=body, headers=headers)
        assert_error(response, 400, "validation_failed")
    for note in ("", "n" * 201, "line\nbreak"):
        response = put_setting(client, headers, "bad.value", value=1, note=note)
        error = assert_error(response, 400, "validation_failed")
        assert "设置备注" in error["message"]
    nan_body = client.put(
        "/api/settings/bad.value",
        content=b'{"value": NaN}',
        headers=headers | {"Content-Type": "application/json"},
    )
    assert_error(nan_body, 400, "validation_failed")
    assert "JSON" in nan_body.json()["error"]["message"]
    assert client.get("/api/settings", headers=headers).json() == {"items": [], "total": 0}


def test_settings_http_rejects_deeply_nested_values(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    normal = put_setting(client, headers, "normal.key", value={"ok": True})
    assert normal.status_code == 200
    for depth in (65, 256):
        response = put_setting(client, headers, "deep.value", value=nested_value(depth))
        error = assert_error(response, 400, "validation_failed")
        assert "嵌套过深" in error["message"]
    listed = client.get("/api/settings", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"items": [normal.json()], "total": 1}
    assert_error(client.get("/api/settings/deep.value", headers=headers), 404, "not_found")

    accepted = put_setting(client, headers, "deep.value", value=nested_value(64))
    assert accepted.status_code == 200
    assert client.get("/api/settings/deep.value", headers=headers).json() == accepted.json()
    assert client.get("/api/settings", headers=headers).json()["total"] == 2


def test_settings_http_rejects_oversized_values(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    response = put_setting(client, headers, "large.value", value="x" * 70000)
    error = assert_error(response, 400, "validation_failed")
    assert "设置值过大" in error["message"]
    assert client.get("/api/settings", headers=headers).json() == {"items": [], "total": 0}
    assert_error(client.get("/api/settings/large.value", headers=headers), 404, "not_found")


@pytest.mark.parametrize(
    ("depth", "code"),
    [(5000, "validation_failed"), (20000, "http_error")],
)
def test_settings_http_deep_bodies_stay_validation_errors(tmp_path: Path, depth, code):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings) | {"Content-Type": "application/json"}
    response = client.put("/api/settings/deep.body", content=raw_nested_body(depth), headers=headers)
    assert_error(response, 400, code)
    assert client.get("/api/settings", headers=auth(settings)).json() == {"items": [], "total": 0}


def test_concurrency_http_check_allows_sufficient_resources(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.get(check_url(), headers=auth(settings))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == CHECK_FIELDS
    assert body["allowed"] is True
    assert body["code"] is None
    assert body["recommended_workers"] == 8
    assert body["warnings"] == []
    assert body["memory_required_bytes"] == 4 * GIB + 2 * GIB
    assert body["disk_required_bytes"] == 4 * GIB + 2 * GIB

    boundary = client.get(
        check_url(
            workers="256",
            cpu_count="256",
            available_memory_bytes=str(4096 * GIB),
            free_disk_bytes=str(4096 * GIB),
        ),
        headers=auth(settings),
    )
    assert boundary.status_code == 200
    assert boundary.json()["allowed"] is True
    assert boundary.json()["recommended_workers"] == 256


def test_concurrency_http_check_reports_blocks_as_results(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)

    memory = client.get(check_url(workers="8", available_memory_bytes=str(GIB)), headers=headers)
    assert memory.status_code == 200
    assert memory.json()["allowed"] is False
    assert memory.json()["code"] == "insufficient_memory"
    assert memory.json()["recommended_workers"] == 1
    assert memory.json()["memory_required_bytes"] == 8 * GIB + 2 * GIB
    assert any("内存" in warning for warning in memory.json()["warnings"])

    disk = client.get(check_url(workers="4", free_disk_bytes=str(5 * GIB)), headers=headers)
    assert disk.status_code == 200
    assert disk.json()["allowed"] is False
    assert disk.json()["code"] == "insufficient_disk"
    assert disk.json()["disk_required_bytes"] == 4 * GIB + 2 * GIB
    assert any("磁盘" in warning for warning in disk.json()["warnings"])

    override_memory = client.get(
        check_url(workers="4", available_memory_bytes=str(GIB), allow_oversubscription="true"),
        headers=headers,
    )
    assert override_memory.status_code == 200
    assert override_memory.json()["allowed"] is True
    assert override_memory.json()["code"] is None
    assert OVERRIDE_WARNING in override_memory.json()["warnings"]

    override_disk = client.get(
        check_url(workers="4", free_disk_bytes=str(GIB), allow_oversubscription="true"),
        headers=headers,
    )
    assert override_disk.status_code == 200
    assert override_disk.json()["allowed"] is True
    assert override_disk.json()["code"] is None
    assert OVERRIDE_WARNING in override_disk.json()["warnings"]

    above = client.get(check_url(workers="8", cpu_count="2"), headers=headers)
    assert above.status_code == 200
    assert above.json()["allowed"] is True
    assert above.json()["warnings"] == [ABOVE_RECOMMENDED_WARNING]

    exact = client.get(check_url(workers="4", free_disk_bytes=str(6 * GIB)), headers=headers)
    assert exact.status_code == 200
    assert exact.json()["allowed"] is True
    assert exact.json()["code"] is None


@pytest.mark.parametrize(
    ("field", "value", "message_fragment"),
    [
        ("workers", "0", "并行数"),
        ("workers", "257", "并行数"),
        ("workers", "abc", "并行数"),
        ("workers", "1.0", "并行数"),
        ("workers", "-1", "并行数"),
        ("workers", "", "并行数"),
        ("workers", "9" * 5000, "并行数"),
        ("cpu_count", "0", "CPU"),
        ("cpu_count", "abc", "CPU"),
        ("cpu_count", "-1", "CPU"),
        ("available_memory_bytes", "-1", "内存"),
        ("available_memory_bytes", "abc", "内存"),
        ("free_disk_bytes", "-1", "磁盘"),
        ("free_disk_bytes", "abc", "磁盘"),
        ("allow_oversubscription", "yes", "资源覆盖开关"),
        ("allow_oversubscription", "True", "资源覆盖开关"),
        ("allow_oversubscription", "1", "资源覆盖开关"),
        ("allow_oversubscription", "", "资源覆盖开关"),
    ],
)
def test_concurrency_http_check_rejects_invalid_queries(tmp_path: Path, field, value, message_fragment):
    app, settings, _, _ = make_app(tmp_path)
    response = TestClient(app).get(check_url(**{field: value}), headers=auth(settings))
    error = assert_error(response, 400, "validation_failed")
    assert message_fragment in error["message"]


@pytest.mark.parametrize(
    "field",
    [
        "workers",
        "cpu_count",
        "available_memory_bytes",
        "free_disk_bytes",
        "allow_oversubscription",
    ],
)
def test_concurrency_http_check_requires_every_query_parameter(tmp_path: Path, field):
    app, settings, _, _ = make_app(tmp_path)
    response = TestClient(app).get(check_url(**{field: None}), headers=auth(settings))
    assert_error(response, 400, "validation_failed")


def test_settings_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    paths = document["paths"]
    for path in ("/api/settings", "/api/settings/{key}", "/api/concurrency/check"):
        assert path in paths, path

    settings_list = paths["/api/settings"]["get"]
    assert settings_list["security"] == [{"HTTPBearer": []}]
    assert "422" not in settings_list["responses"]
    assert settings_list["responses"]["401"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorEnvelope"
    )
    assert settings_list["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "SettingListOutput"
    )

    member = paths["/api/settings/{key}"]
    for method in ("get", "put", "delete"):
        operation = member[method]
        assert operation["security"] == [{"HTTPBearer": []}], method
        assert "422" not in operation["responses"], method
        for status in ("400", "401"):
            schema = operation["responses"][status]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("ErrorEnvelope"), (method, status)
    assert member["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "SettingOutput"
    )
    assert member["put"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "SettingOutput"
    )
    assert member["delete"]["responses"]["204"] == {"description": "Successful Response"}
    for method in ("get", "delete"):
        schema = member[method]["responses"]["404"]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope")
    put_body = member["put"]["requestBody"]["content"]["application/json"]["schema"]
    assert put_body["$ref"].endswith("SettingPutInput")

    check = paths["/api/concurrency/check"]["get"]
    assert check["security"] == [{"HTTPBearer": []}]
    assert "422" not in check["responses"]
    for status in ("400", "401"):
        schema = check["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope")
    assert check["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ConcurrencyCheckOutput"
    )
    parameters = {item["name"]: item["schema"] for item in check["parameters"]}
    assert set(parameters) == {
        "workers",
        "cpu_count",
        "available_memory_bytes",
        "free_disk_bytes",
        "allow_oversubscription",
    }
    assert all(item["required"] is True for item in check["parameters"])
    assert parameters["workers"]["type"] == "integer"
    assert parameters["workers"]["minimum"] == 1
    assert parameters["workers"]["maximum"] == 256
    assert parameters["cpu_count"]["minimum"] == 1
    assert parameters["available_memory_bytes"]["minimum"] == 0
    assert parameters["free_disk_bytes"]["minimum"] == 0
    assert parameters["allow_oversubscription"]["type"] == "boolean"

    schemas = document["components"]["schemas"]
    assert set(schemas["SettingOutput"]["required"]) == SETTING_FIELDS
    assert set(schemas["SettingListOutput"]["required"]) == {"items", "total"}
    assert set(schemas["SettingPutInput"]["required"]) == {"value"}
    assert set(schemas["SettingPutInput"]["properties"]) == {"value", "note"}
    assert set(schemas["ConcurrencyCheckOutput"]["properties"]) == CHECK_FIELDS
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_settings_http_keeps_existing_routes_working(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/version").status_code == 200
    assert client.get("/api/jobs", headers=headers).json()["items"] == []
    assert client.get("/api/pools", headers=headers).json()["items"] == []
    assert client.get("/api/drafts", headers=headers).json()["items"] == []
    assert client.get("/api/saves", headers=headers).json()["items"] == []
    assert client.get("/api/settings", headers=headers).json()["items"] == []

    wrong_collection = client.put("/api/settings", headers=headers)
    assert wrong_collection.status_code == 405
    assert "GET" in wrong_collection.headers["allow"]
    wrong_member = client.post("/api/settings/match.roster_size", headers=headers)
    assert wrong_member.status_code == 405
    allowed = {item.strip() for item in wrong_member.headers["allow"].split(",")}
    assert {"GET", "PUT", "DELETE"} <= allowed
    wrong_check = client.delete("/api/concurrency/check", headers=headers)
    assert wrong_check.status_code == 405
    assert "GET" in wrong_check.headers["allow"]


def test_settings_http_cors_preflight_allows_put(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    preflight = client.options(
        "/api/settings/match.roster_size",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert preflight.status_code == 200
    assert "PUT" in preflight.headers["access-control-allow-methods"]
