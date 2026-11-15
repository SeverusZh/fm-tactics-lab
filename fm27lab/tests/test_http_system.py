from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.adapters.host_resources import HostResources
from fm27lab.interfaces.http.routes import system as system_routes
from fm27lab.tests.test_http_health import make_app

GIB = 1024**3
RESOURCE_FIELDS = {
    "cpu_count",
    "available_memory_bytes",
    "free_disk_bytes",
    "recommended_workers",
}
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


def auth(settings) -> dict:
    return {"Authorization": f"Bearer {settings.token}"}


def test_resources_reports_probe_and_recommended_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app, settings, _, _ = make_app(tmp_path)
    seen: list[Path] = []

    def probe(data_dir: Path) -> HostResources:
        seen.append(data_dir)
        return HostResources(
            cpu_count=16,
            available_memory_bytes=4 * GIB + 512 * 1024**2,
            free_disk_bytes=50 * GIB,
        )

    monkeypatch.setattr(system_routes, "probe_host_resources", probe)
    response = TestClient(app).get("/api/system/resources", headers=auth(settings))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == RESOURCE_FIELDS
    assert body["cpu_count"] == 16
    assert body["available_memory_bytes"] == 4 * GIB + 512 * 1024**2
    assert body["free_disk_bytes"] == 50 * GIB
    assert body["recommended_workers"] == 2
    assert seen == [settings.data_dir]


def test_resources_requires_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    denied = client.get("/api/system/resources")
    assert denied.status_code == 401
    error = denied.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "unauthorized"
    assert denied.headers["www-authenticate"] == "Bearer"
    wrong = client.get("/api/system/resources", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401


def test_resources_maps_probe_failure_to_503_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app, settings, _, _ = make_app(tmp_path)

    def broken(data_dir: Path) -> HostResources:
        raise RuntimeError("无法探测可用内存")

    monkeypatch.setattr(system_routes, "probe_host_resources", broken)
    response = TestClient(app).get("/api/system/resources", headers=auth(settings))
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "resource_probe_failed"
    assert error["message"] == "无法探测可用内存"
    assert error["details"] is None
    assert error["retriable"] is True
    assert error["retry_after_seconds"] is None


def test_openapi_documents_resources_output_and_error_envelope(tmp_path: Path):
    app, *_ = make_app(tmp_path)
    document = app.openapi()
    assert "/api/system/resources" in document["paths"]
    operation = document["paths"]["/api/system/resources"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SystemResourcesOutput"
    }
    for status in ("401", "503"):
        failure = operation["responses"][status]["content"]["application/json"]["schema"]
        assert failure == {"$ref": "#/components/schemas/ErrorEnvelope"}, status
    assert "422" not in operation["responses"]
    model = document["components"]["schemas"]["SystemResourcesOutput"]
    assert set(model["properties"]) == RESOURCE_FIELDS
    assert set(model["required"]) == RESOURCE_FIELDS
