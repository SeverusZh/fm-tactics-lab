from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import create_app


def make_app(tmp_path: Path, dev: bool = True):
    settings = Settings.create(data_dir=tmp_path, token="c" * 64, dev=dev)
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    stopped = []

    def shutdown():
        stopped.append(True)

    return create_app(settings, database, shutdown=shutdown), settings, stopped, database


def test_health_version_docs_and_openapi_are_public(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["api"] == "fm27lab/v2"
    assert body["database"] == "ready"
    assert body["version"] == settings.version

    version = client.get("/api/version")
    assert version.status_code == 200
    assert version.json()["limits"]["max_workers"] == 256
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200


def test_shutdown_requires_full_error_envelope_and_calls_once(tmp_path: Path):
    app, settings, stopped, _ = make_app(tmp_path)
    client = TestClient(app)
    denied = client.post("/api/shutdown")
    assert denied.status_code == 401
    error = denied.json()["error"]
    assert set(error) == {"code", "message", "details", "retriable", "retry_after_seconds"}
    assert error["code"] == "unauthorized"
    wrong = client.post("/api/shutdown", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401
    allowed = client.post(
        "/api/shutdown",
        headers={"Authorization": f"Bearer {settings.token}"},
    )
    assert allowed.status_code == 202
    assert stopped == [True]


def test_events_requires_token_and_streams_ready_event(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.get("/api/events").status_code == 401
    with client.stream(
        "GET",
        "/api/events",
        headers={
            "Authorization": f"Bearer {settings.token}",
            "Accept": "text/event-stream",
            "Last-Event-ID": "41",
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        ready = next(response.iter_text())
    assert "event: ready" in ready


def test_unknown_routes_and_methods_use_error_envelope(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    client = TestClient(app)
    not_found = client.get("/api/nope")
    assert not_found.status_code == 404
    error = not_found.json()["error"]
    assert set(error) == {"code", "message", "details", "retriable", "retry_after_seconds"}
    assert error["code"] == "not_found"
    method = client.delete("/api/health")
    assert method.status_code == 405
    error = method.json()["error"]
    assert set(error) == {"code", "message", "details", "retriable", "retry_after_seconds"}
    assert error["code"] == "method_not_allowed"


def test_unhandled_errors_use_fixed_error_envelope(tmp_path: Path):
    app, _, _, database = make_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)

    def explode():
        raise RuntimeError("secret detail")

    database.health = explode
    response = client.get("/api/health")
    assert response.status_code == 500
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "retriable", "retry_after_seconds"}
    assert error["code"] == "internal_error"
    assert "secret detail" not in response.text


def test_empty_database_health_is_503_and_does_not_create_file(tmp_path: Path):
    settings = Settings.create(data_dir=tmp_path, token="e" * 64)
    settings.ensure_dirs()
    database = Database(settings.database_path)
    app = create_app(settings, database, shutdown=lambda: None)
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 503
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "retriable", "retry_after_seconds"}
    assert error["code"] == "database_unavailable"
    assert not settings.database_path.exists()


def test_cors_and_origin_enforcement(tmp_path: Path):
    app, settings, stopped, _ = make_app(tmp_path, dev=False)
    client = TestClient(app)
    allowed = client.get("/api/health", headers={"Origin": "tauri://localhost"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "tauri://localhost"
    assert "access-control-allow-credentials" not in allowed.headers
    dev_origin = client.get("/api/health", headers={"Origin": "http://localhost:1420"})
    assert dev_origin.status_code == 403
    assert dev_origin.json()["error"]["code"] == "forbidden_origin"
    rejected = client.post(
        "/api/shutdown",
        headers={
            "Authorization": f"Bearer {settings.token}",
            "Origin": "https://evil.invalid",
        },
    )
    assert rejected.status_code == 403
    assert stopped == []


def test_dev_cors_allows_localhost(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path, dev=True)
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:1420"
