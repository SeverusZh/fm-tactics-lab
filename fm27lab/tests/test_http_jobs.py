from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.tests.test_http_health import make_app

JOB_FIELDS = {
    "id",
    "kind",
    "status",
    "name",
    "config",
    "summary",
    "workers",
    "total",
    "completed",
    "created_at",
    "started_at",
    "finished_at",
}
RUN_FIELDS = {
    "job_id",
    "sequence",
    "variant",
    "seed",
    "score",
    "verified",
    "stats",
    "events",
    "log_path",
    "created_at",
}
HTTP_METHODS = {"get", "post", "patch", "put", "delete", "options", "head"}


def auth(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def job_payload(**overrides):
    value = {
        "kind": "experiment",
        "name": "Experiment",
        "config": {"seeds": [1, 2]},
        "workers": 2,
        "total": 4,
    }
    value.update(overrides)
    return value


def create_job(client, headers, **overrides):
    response = client.post("/api/jobs", json=job_payload(**overrides), headers=headers)
    assert response.status_code == 201
    return response.json()


def run_payload(seed=11):
    return {
        "variant": "B",
        "seed": seed,
        "score_home": 2,
        "score_away": 1,
        "verified": True,
        "stats": {"shots": [10, 7]},
    }


def test_job_http_requires_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    for response in (
        client.get("/api/jobs"),
        client.post("/api/jobs", json=job_payload()),
        client.get("/api/jobs/none"),
        client.patch("/api/jobs/none", json={"name": "x"}),
        client.delete("/api/jobs/none"),
        client.post("/api/jobs/none/cancel"),
        client.get("/api/jobs/none/runs"),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    wrong = client.get("/api/jobs", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"


def test_job_http_create_list_detail_update_cancel_delete(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = create_job(client, headers)
    assert set(created) == JOB_FIELDS
    assert created["kind"] == "experiment"
    assert created["status"] == "queued"
    assert created["name"] == "Experiment"
    assert created["config"] == {"seeds": [1, 2]}
    assert created["summary"] == {}
    assert created["workers"] == 2
    assert created["total"] == 4
    assert created["completed"] == 0
    assert created["started_at"] is None
    assert created["finished_at"] is None
    datetime.fromisoformat(created["created_at"])

    listed = client.get("/api/jobs", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"items": [created], "total": 1, "next_offset": None}
    fetched = client.get(f"/api/jobs/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == created

    renamed = client.patch(
        f"/api/jobs/{created['id']}",
        json={"name": "Renamed", "summary": {"wins": 2}},
        headers=headers,
    )
    assert renamed.status_code == 200
    updated = renamed.json()
    assert updated["name"] == "Renamed"
    assert updated["summary"] == {"wins": 2}
    assert updated["status"] == "queued"
    assert updated["created_at"] == created["created_at"]

    started = client.patch(f"/api/jobs/{created['id']}", json={"status": "running"}, headers=headers)
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert datetime.fromisoformat(started.json()["started_at"])
    progressed = client.patch(f"/api/jobs/{created['id']}", json={"completed": 2}, headers=headers)
    assert progressed.status_code == 200
    assert progressed.json()["completed"] == 2

    cancelled = client.post(f"/api/jobs/{created['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert datetime.fromisoformat(cancelled.json()["finished_at"])

    removed = client.delete(f"/api/jobs/{created['id']}", headers=headers)
    assert removed.status_code == 204
    assert removed.content == b""
    assert "content-type" not in removed.headers
    missing = client.get(f"/api/jobs/{created['id']}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert client.get("/api/jobs", headers=headers).json() == {
        "items": [],
        "total": 0,
        "next_offset": None,
    }


def test_job_http_list_status_filter_and_pagination_boundaries(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = [create_job(client, headers, total=1) for _ in range(3)]
    identifiers = {item["id"] for item in created}
    running_id = created[1]["id"]
    assert (
        client.patch(f"/api/jobs/{running_id}", json={"status": "running"}, headers=headers).status_code
        == 200
    )

    running = client.get("/api/jobs?status=running", headers=headers)
    assert running.status_code == 200
    assert running.json()["total"] == 1
    assert [item["id"] for item in running.json()["items"]] == [running_id]
    queued = client.get("/api/jobs?status=queued", headers=headers).json()
    assert queued["total"] == 2
    assert {item["id"] for item in queued["items"]} == identifiers - {running_id}
    empty = client.get("/api/jobs?status=completed", headers=headers).json()
    assert empty == {"items": [], "total": 0, "next_offset": None}
    for status in ("bogus", ""):
        rejected = client.get(f"/api/jobs?status={status}", headers=headers)
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "validation_failed"

    first_page = client.get("/api/jobs?limit=2&offset=0", headers=headers).json()
    assert first_page["total"] == 3
    assert len(first_page["items"]) == 2
    assert first_page["next_offset"] == 2
    tail = client.get("/api/jobs?limit=2&offset=2", headers=headers).json()
    assert tail["total"] == 3
    assert len(tail["items"]) == 1
    assert tail["next_offset"] is None
    assert {item["id"] for item in first_page["items"] + tail["items"]} == identifiers
    beyond = client.get("/api/jobs?limit=2&offset=99", headers=headers).json()
    assert beyond == {"items": [], "total": 3, "next_offset": None}
    assert client.get("/api/jobs?limit=256", headers=headers).status_code == 200
    assert client.get("/api/jobs?offset=2147483647", headers=headers).status_code == 200
    for query in ("limit=1.0", "limit=0", "limit=257", "limit=abc", "offset=-1", "offset=abc"):
        assert client.get(f"/api/jobs?{query}", headers=headers).status_code == 400, query


def test_job_http_create_validation_failures(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    invalid = (
        {},
        {"kind": ""},
        {"kind": 123},
        {"kind": "experiment", "name": ""},
        {"kind": "experiment", "name": "x" * 101},
        {"kind": "experiment", "workers": 0},
        {"kind": "experiment", "workers": 257},
        {"kind": "experiment", "workers": True},
        {"kind": "experiment", "workers": "2"},
        {"kind": "experiment", "total": -1},
        {"kind": "experiment", "total": True},
        {"kind": "experiment", "config": []},
        {"kind": "experiment", "unknown": True},
    )
    for payload in invalid:
        response = client.post("/api/jobs", json=payload, headers=headers)
        assert response.status_code == 400, payload
        assert response.json()["error"]["code"] == "validation_failed", payload
    nan = client.post(
        "/api/jobs",
        content=b'{"kind": "experiment", "config": {"x": NaN}}',
        headers={**headers, "Content-Type": "application/json"},
    )
    assert nan.status_code == 400
    assert nan.json()["error"]["code"] == "validation_failed"
    assert client.get("/api/jobs", headers=headers).json()["total"] == 0


def test_job_http_patch_transitions_and_validation(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = create_job(client, headers, total=2)
    job_id = created["id"]
    before = client.get(f"/api/jobs/{job_id}", headers=headers).json()

    conflict = client.patch(f"/api/jobs/{job_id}", json={"status": "completed"}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "invalid_transition"
    assert client.get(f"/api/jobs/{job_id}", headers=headers).json() == before

    for payload in (
        {},
        {"status": "bogus"},
        {"status": None},
        {"workers": 2},
        {"unknown": True},
        {"completed": 3},
        {"completed": -1},
        {"completed": None},
        {"completed": True},
        {"completed": 1.5},
        {"summary": None},
        {"summary": []},
        {"name": ""},
        {"name": "x" * 101},
        {"status": []},
        {"completed": "2"},
    ):
        response = client.patch(f"/api/jobs/{job_id}", json=payload, headers=headers)
        assert response.status_code == 400, payload
        assert response.json()["error"]["code"] == "validation_failed", payload
    assert client.get(f"/api/jobs/{job_id}", headers=headers).json() == before
    assert client.patch("/api/jobs/missing", json={"name": "x"}, headers=headers).status_code == 404
    assert client.patch("/api/jobs/missing", json={}, headers=headers).status_code == 400

    running = client.patch(f"/api/jobs/{job_id}", json={"status": "running"}, headers=headers)
    assert running.status_code == 200
    assert running.json()["started_at"] is not None
    assert client.patch(f"/api/jobs/{job_id}", json={"completed": 3}, headers=headers).status_code == 400
    progressed = client.patch(f"/api/jobs/{job_id}", json={"completed": 2}, headers=headers)
    assert progressed.status_code == 200
    assert progressed.json()["completed"] == 2
    completed = client.patch(f"/api/jobs/{job_id}", json={"status": "completed"}, headers=headers)
    assert completed.status_code == 200
    snapshot = client.get(f"/api/jobs/{job_id}", headers=headers).json()
    back = client.patch(f"/api/jobs/{job_id}", json={"status": "running"}, headers=headers)
    assert back.status_code == 409
    assert back.json()["error"]["code"] == "invalid_transition"
    assert client.get(f"/api/jobs/{job_id}", headers=headers).json() == snapshot

    failed = create_job(client, headers, total=1)
    assert (
        client.patch(f"/api/jobs/{failed['id']}", json={"status": "error"}, headers=headers).status_code
        == 200
    )
    retry = client.patch(f"/api/jobs/{failed['id']}", json={"status": "running"}, headers=headers)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "invalid_transition"


def test_job_http_cancel_contract(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    assert client.post("/api/jobs/missing/cancel", headers=headers).status_code == 404
    assert client.delete("/api/jobs/missing", headers=headers).status_code == 404

    queued = create_job(client, headers)
    cancelled = client.post(f"/api/jobs/{queued['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    value = cancelled.json()
    assert value["status"] == "cancelled"
    assert value["finished_at"] is not None
    again = client.post(f"/api/jobs/{queued['id']}/cancel", headers=headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_transition"
    assert client.get(f"/api/jobs/{queued['id']}", headers=headers).json() == value

    finished = create_job(client, headers)
    assert (
        client.patch(f"/api/jobs/{finished['id']}", json={"status": "running"}, headers=headers).status_code
        == 200
    )
    assert (
        client.patch(f"/api/jobs/{finished['id']}", json={"status": "completed"}, headers=headers).status_code
        == 200
    )
    terminal = client.post(f"/api/jobs/{finished['id']}/cancel", headers=headers)
    assert terminal.status_code == 409
    assert terminal.json()["error"]["code"] == "invalid_transition"
    assert client.get(f"/api/jobs/{finished['id']}", headers=headers).json()["status"] == "completed"


def test_job_http_runs_pagination_and_missing_job(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    created = create_job(client, headers, total=3)
    job_id = created["id"]
    assert client.patch(f"/api/jobs/{job_id}", json={"status": "running"}, headers=headers).status_code == 200
    for seed in (11, 12, 13):
        app.state.jobs.append_run(job_id, run_payload(seed))

    first = client.get(f"/api/jobs/{job_id}/runs?limit=2&offset=0", headers=headers)
    assert first.status_code == 200
    page = first.json()
    assert set(page) == {"items", "total", "next_offset"}
    assert [item["sequence"] for item in page["items"]] == [1, 2]
    assert page["total"] == 3
    assert page["next_offset"] == 2
    record = page["items"][0]
    assert set(record) == RUN_FIELDS
    assert record["job_id"] == job_id
    assert record["variant"] == "B"
    assert record["score"] == [2, 1]
    assert record["verified"] is True
    assert record["stats"] == {"shots": [10, 7]}
    assert record["events"] is None
    assert record["log_path"] is None

    tail = client.get(f"/api/jobs/{job_id}/runs?limit=2&offset=2", headers=headers).json()
    assert [item["sequence"] for item in tail["items"]] == [3]
    assert tail["total"] == 3
    assert tail["next_offset"] is None
    default_page = client.get(f"/api/jobs/{job_id}/runs", headers=headers).json()
    assert len(default_page["items"]) == 3
    assert client.get(f"/api/jobs/{job_id}", headers=headers).json()["completed"] == 3

    assert client.get("/api/jobs/missing/runs", headers=headers).status_code == 404
    empty_job = create_job(client, headers)
    empty = client.get(f"/api/jobs/{empty_job['id']}/runs", headers=headers).json()
    assert empty == {"items": [], "total": 0, "next_offset": None}
    for query in ("limit=0", "limit=201", "limit=abc", "offset=-1"):
        assert client.get(f"/api/jobs/{job_id}/runs?{query}", headers=headers).status_code == 400, query


def test_job_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    paths = document["paths"]
    for path in ("/api/jobs", "/api/jobs/{job_id}", "/api/jobs/{job_id}/cancel", "/api/jobs/{job_id}/runs"):
        assert path in paths
    for path in ("/api/jobs", "/api/jobs/{job_id}", "/api/jobs/{job_id}/cancel", "/api/jobs/{job_id}/runs"):
        for method, operation in paths[path].items():
            if method not in HTTP_METHODS:
                continue
            assert operation["security"] == [{"HTTPBearer": []}], (path, method)
            assert "422" not in operation["responses"], (path, method)
            for status in ("400", "401"):
                assert status in operation["responses"], (path, method)
                schema = operation["responses"][status]["content"]["application/json"]["schema"]
                assert schema["$ref"].endswith("ErrorEnvelope"), (path, method, status)

    components = document["components"]["schemas"]
    job_schema = components["JobOutput"]
    assert set(job_schema["properties"]) == JOB_FIELDS
    assert set(job_schema["required"]) == JOB_FIELDS
    create_input = components["JobCreateInput"]
    assert set(create_input["properties"]) == {"kind", "name", "config", "workers", "total"}
    assert create_input["additionalProperties"] is False

    list_operation = paths["/api/jobs"]["get"]
    assert list_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "JobListOutput"
    )
    create_operation = paths["/api/jobs"]["post"]
    assert create_operation["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "JobOutput"
    )
    member_operations = paths["/api/jobs/{job_id}"]
    assert member_operations["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("JobOutput")
    for status in ("400", "401", "404"):
        schema = member_operations["get"]["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope")
    patch_responses = member_operations["patch"]["responses"]
    assert patch_responses["409"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorEnvelope")
    cancel_responses = paths["/api/jobs/{job_id}/cancel"]["post"]["responses"]
    assert cancel_responses["409"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorEnvelope")
    runs_operation = paths["/api/jobs/{job_id}/runs"]["get"]
    assert runs_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "JobRunListOutput"
    )
    assert set(components["JobRunOutput"]["properties"]) == RUN_FIELDS

    parameters = {item["name"]: item["schema"] for item in list_operation["parameters"]}
    assert parameters["limit"]["type"] == "integer"
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 256
    assert parameters["limit"]["default"] == 50
    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["default"] == 0
    assert "status" in parameters
    run_parameters = {item["name"]: item["schema"] for item in runs_operation["parameters"]}
    assert run_parameters["limit"]["minimum"] == 1
    assert run_parameters["limit"]["maximum"] == 200
    assert run_parameters["limit"]["default"] == 50
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_job_http_cors_methods_and_existing_routes(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    preflight = client.options(
        "/api/jobs/x",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "Authorization, Idempotency-Key",
        },
    )
    assert preflight.status_code == 200
    allowed_methods = preflight.headers["access-control-allow-methods"]
    for method in ("GET", "POST", "PATCH", "DELETE"):
        assert method in allowed_methods
    assert "idempotency-key" in preflight.headers["access-control-allow-headers"].lower()

    wrong = client.put("/api/jobs", headers=headers)
    assert wrong.status_code == 405
    assert "GET" in wrong.headers["allow"] and "POST" in wrong.headers["allow"]
    wrong_member = client.put("/api/jobs/x", headers=headers)
    assert wrong_member.status_code == 405
    member_methods = {item.strip() for item in wrong_member.headers["allow"].split(",")}
    assert {"GET", "PATCH", "DELETE"} <= member_methods
    wrong_cancel = client.get("/api/jobs/x/cancel", headers=headers)
    assert wrong_cancel.status_code == 405
    assert "POST" in wrong_cancel.headers["allow"]
    assert client.get("/api/pools", headers=headers).json()["items"] == []
    assert client.get("/api/drafts", headers=headers).json()["items"] == []
    assert (
        client.post(
            "/api/pools", json={"name": "Corner", "weight": 1, "tactic": {}}, headers=headers
        ).status_code
        == 201
    )

    class FakeJobs:
        def list(self, status=None, limit=50, offset=0):
            return {"items": [], "total": 0, "next_offset": None}

        def create(self, kind, name=None, config=None, workers=1, total=0):
            return {
                "id": "fake",
                "kind": kind,
                "status": "queued",
                "name": name,
                "config": config or {},
                "summary": {},
                "workers": workers,
                "total": total,
                "completed": 0,
                "created_at": "2026-01-01T00:00:00+00:00",
                "started_at": None,
                "finished_at": None,
            }

        def get(self, job_id):
            return None

        def update(self, job_id, changes):
            return None

        def cancel(self, job_id):
            return None

        def delete(self, job_id):
            return False

        def runs(self, job_id, limit=50, offset=0):
            return {"items": [], "total": 0, "next_offset": None}

    from fm27lab.interfaces.http.app import create_app

    second = create_app(settings, database, job_service=FakeJobs())
    fake_client = TestClient(second)
    assert fake_client.get("/api/jobs", headers=headers).json() == {
        "items": [],
        "total": 0,
        "next_offset": None,
    }
    created = fake_client.post("/api/jobs", json={"kind": "experiment"}, headers=headers)
    assert created.status_code == 201
    assert created.json()["id"] == "fake"
