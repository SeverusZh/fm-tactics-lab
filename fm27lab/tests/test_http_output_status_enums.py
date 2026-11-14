from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.adapters.storage_sqlite.saves import SavesRepository
from fm27lab.application.jobs import JobService
from fm27lab.application.saves import SavesService
from fm27lab.tests.test_http_health import make_app

ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}


def auth(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def job_payload() -> dict:
    return {
        "kind": "experiment",
        "name": "Experiment",
        "config": {"seeds": [1, 2]},
        "workers": 2,
        "total": 4,
    }


def save_payload() -> dict:
    return {
        "source_path": "/saves/status-enum.fm",
        "source_sha256": "a" * 64,
    }


def openapi_schemas(tmp_path: Path) -> dict:
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    return document["components"]["schemas"]


def test_job_output_status_enum_matches_transitions(tmp_path: Path):
    schema = openapi_schemas(tmp_path)["JobOutput"]["properties"]["status"]
    assert schema["type"] == "string"
    assert set(schema["enum"]) == set(JobService.TRANSITIONS)
    assert len(schema["enum"]) == len(set(schema["enum"]))


def test_save_output_status_enum_matches_save_statuses(tmp_path: Path):
    schema = openapi_schemas(tmp_path)["SaveOutput"]["properties"]["status"]
    assert schema["type"] == "string"
    assert set(schema["enum"]) == set(SavesRepository.SAVE_STATUSES)
    assert set(schema["enum"]) == set(SavesService.TRANSITIONS)
    assert len(schema["enum"]) == len(set(schema["enum"]))


def test_status_inputs_remain_plain_strings(tmp_path: Path):
    schemas = openapi_schemas(tmp_path)
    for schema_name in ("JobUpdateInput", "SaveCreateInput", "SaveUpdateInput"):
        schema = schemas[schema_name]["properties"]["status"]
        assert "enum" not in schema, schema_name
        if "anyOf" in schema:
            assert {"type": "string"} in schema["anyOf"], schema_name
        else:
            assert schema["type"] == "string", schema_name


def test_job_patch_invalid_status_reports_route_message(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = client.post("/api/jobs", json=job_payload(), headers=headers).json()
    response = client.patch(f"/api/jobs/{job['id']}", json={"status": "bogus"}, headers=headers)
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "validation_failed"
    assert error["message"] == "任务状态无效"
    running = client.patch(f"/api/jobs/{job['id']}", json={"status": "running"}, headers=headers)
    assert running.status_code == 200, running.text
    assert running.json()["status"] in set(JobService.TRANSITIONS)


def test_save_patch_invalid_status_reports_route_message(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    save = client.post("/api/saves", json=save_payload(), headers=headers).json()
    response = client.patch(f"/api/saves/{save['id']}", json={"status": "bogus"}, headers=headers)
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "validation_failed"
    assert error["message"] == "存档状态无效"
    pending = client.patch(f"/api/saves/{save['id']}", json={"status": "reading"}, headers=headers)
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] in set(SavesRepository.SAVE_STATUSES)
