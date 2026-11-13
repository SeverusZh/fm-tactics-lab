from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.adapters.engine_native.capabilities import parse_capabilities, plan_runtime
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.application.experiments import ExperimentService
from fm27lab.application.jobs import JobService
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import MissingEngine, create_app
from fm27lab.ports.engine import EngineCapabilities, EnginePort
from fm27lab.tests.test_http_health import make_app

GIB = 1024**3
DEFAULT_PLAN = plan_runtime(
    parse_capabilities(None),
    has_pool_variants=False,
    has_experimental_execution=False,
)
ENGINE_UNAVAILABLE = "原生引擎未配置"
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
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
HTTP_METHODS = {"get", "post", "patch", "put", "delete", "options", "head"}


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def experiment_payload(**overrides) -> dict:
    value = {
        "name": "Experiment",
        "seeds": [1, 2],
        "variants": ["A", "B"],
        "workers": 2,
        "cpu_count": 8,
        "available_memory_bytes": 32 * GIB,
        "free_disk_bytes": 100 * GIB,
    }
    value.update(overrides)
    return value


class FakeEngine:
    def __init__(self) -> None:
        self.tasks: list[dict] = []
        self.cancel_calls = 0

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(counted_sessions=False, jobs_per_session=64)

    def run_batch(self, tasks, on_result, on_progress) -> None:
        self.tasks = [dict(task) for task in tasks]
        for index, task in enumerate(self.tasks):
            on_progress([{"worker": index}])
            on_result(
                {
                    "variant": task["variant"],
                    "seed": task["seed"],
                    "score_home": 1,
                    "score_away": 0,
                    "verified": True,
                    "stats": {"shots": [4, 2]},
                }
            )

    def cancel(self) -> None:
        self.cancel_calls += 1


def make_engine_app(tmp_path: Path) -> tuple[TestClient, Settings, JobService, FakeEngine]:
    settings = Settings.create(data_dir=tmp_path, token="c" * 64, dev=True)
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    jobs = JobService(JobRepository(database))
    engine = FakeEngine()
    experiments = ExperimentService(jobs, engine, DEFAULT_PLAN)
    app = create_app(settings, database, job_service=jobs, experiment_service=experiments)
    return TestClient(app), settings, jobs, engine


def canned_job(**overrides) -> dict:
    value = {
        "id": "job-fixture",
        "kind": "experiment",
        "status": "queued",
        "name": "Fixture",
        "config": {"seeds": [1], "variants": ["A"]},
        "summary": {},
        "workers": 1,
        "total": 1,
        "completed": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": None,
        "finished_at": None,
    }
    value.update(overrides)
    return value


class StubJobs:
    def __init__(self, job: dict) -> None:
        self.job = job

    def get(self, job_id):
        return self.job


class StubExperiments:
    def __init__(self, *, job: dict | None = None, start_result=None, start_error=None) -> None:
        self.job = canned_job() if job is None else job
        self.start_result = start_result
        self.start_error = start_error
        self.submissions: list[dict] = []
        self.start_calls = 0
        self.cancelled: list[str] = []
        self.resumed: list[str] = []

    def submit(self, config, **options):
        self.submissions.append({"config": config, **options})
        return self.job

    def start_next(self):
        self.start_calls += 1
        if self.start_error is not None:
            raise self.start_error
        return self.start_result

    def cancel(self, job_id):
        self.cancelled.append(job_id)
        return {
            **self.job,
            "id": job_id,
            "status": "cancelled",
            "finished_at": "2026-01-01T00:00:00+00:00",
        }

    def resume(self, job_id):
        self.resumed.append(job_id)
        return {**self.job, "id": job_id, "status": "queued"}


def test_experiment_http_requires_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    for response in (
        client.post("/api/experiments", json=experiment_payload()),
        client.post("/api/experiments/start"),
        client.post("/api/experiments/job-1/cancel"),
        client.post("/api/experiments/job-1/resume"),
    ):
        assert response.status_code == 401
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS
        assert error["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    wrong = client.post("/api/experiments/start", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"


def test_submit_creates_queued_experiment_job(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    assert isinstance(app.state.experiments, ExperimentService)
    client = TestClient(app)
    headers = auth(settings)
    response = client.post("/api/experiments", json=experiment_payload(name=None), headers=headers)
    assert response.status_code == 201
    job = response.json()
    assert set(job) == JOB_FIELDS
    assert job["kind"] == "experiment"
    assert job["status"] == "queued"
    assert job["name"] is None
    assert job["config"] == {"seeds": [1, 2], "variants": ["A", "B"]}
    assert job["workers"] == 2
    assert job["total"] == 4
    assert job["completed"] == 0
    assert job["started_at"] is None
    assert job["finished_at"] is None
    assert job["summary"]["runtime_mode"] == "isolated_worker"
    assert job["summary"]["provenance"] == DEFAULT_PLAN.provenance
    assert job["summary"]["provenance"]["fallback_reason"] == "counted_sessions_unavailable"
    fetched = client.get(f"/api/jobs/{job['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == job


def test_submit_uses_injected_experiment_service(tmp_path: Path):
    _, settings, _, database = make_app(tmp_path)
    stub = StubExperiments()
    second = create_app(settings, database, experiment_service=stub)
    client = TestClient(second)
    payload = experiment_payload(
        name="Injected",
        seeds=[3, 1],
        variants=["B", "A"],
        workers=4,
        cpu_count=16,
        available_memory_bytes=64 * GIB,
        free_disk_bytes=200 * GIB,
        allow_oversubscription=True,
    )
    response = client.post("/api/experiments", json=payload, headers=auth(settings))
    assert response.status_code == 201
    assert response.json() == stub.job
    assert stub.submissions == [
        {
            "config": {"seeds": [3, 1], "variants": ["B", "A"]},
            "workers": 4,
            "name": "Injected",
            "cpu_count": 16,
            "available_memory_bytes": 64 * GIB,
            "free_disk_bytes": 200 * GIB,
            "allow_oversubscription": True,
        }
    ]
    assert second.state.jobs.list()["total"] == 0


def test_submit_resource_preflight_returns_409(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    memory = client.post(
        "/api/experiments",
        json=experiment_payload(available_memory_bytes=GIB),
        headers=headers,
    )
    assert memory.status_code == 409
    error = memory.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "insufficient_memory"
    assert "内存" in error["message"]
    assert error["retriable"] is True
    disk = client.post(
        "/api/experiments",
        json=experiment_payload(free_disk_bytes=3 * GIB),
        headers=headers,
    )
    assert disk.status_code == 409
    assert disk.json()["error"]["code"] == "insufficient_disk"
    assert "磁盘" in disk.json()["error"]["message"]
    assert app.state.jobs.list()["total"] == 0
    allowed = client.post(
        "/api/experiments",
        json=experiment_payload(available_memory_bytes=GIB, allow_oversubscription=True),
        headers=headers,
    )
    assert allowed.status_code == 201
    assert app.state.jobs.list()["total"] == 1


def test_submit_validation_failures_return_400(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    invalid = (
        {},
        {"name": "Only name"},
        experiment_payload(seeds=[]),
        experiment_payload(seeds=[1, 1]),
        experiment_payload(seeds=[-1]),
        experiment_payload(seeds=["1"]),
        experiment_payload(seeds=[True]),
        experiment_payload(variants=[]),
        experiment_payload(variants=["C"]),
        experiment_payload(variants=["A", "A"]),
        experiment_payload(variants=[1]),
        experiment_payload(workers=0),
        experiment_payload(workers=257),
        experiment_payload(workers=True),
        experiment_payload(cpu_count=0),
        experiment_payload(available_memory_bytes=-1),
        experiment_payload(free_disk_bytes=-1),
        experiment_payload(allow_oversubscription="yes"),
        experiment_payload(name=""),
        experiment_payload(name="x" * 101),
        {**experiment_payload(), "extra": True},
        [],
    )
    for payload in invalid:
        response = client.post("/api/experiments", json=payload, headers=headers)
        assert response.status_code == 400, payload
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS, payload
        assert error["code"] == "validation_failed", payload
        assert error["retriable"] is False, payload
    malformed = client.post(
        "/api/experiments",
        content=b'{"seeds": [',
        headers={**headers, "Content-Type": "application/json"},
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "validation_failed"
    assert app.state.jobs.list()["total"] == 0


def test_start_runs_queued_job_with_fake_engine(tmp_path: Path):
    client, settings, _, engine = make_engine_app(tmp_path)
    headers = auth(settings)
    created = client.post("/api/experiments", json=experiment_payload(), headers=headers)
    assert created.status_code == 201
    job_id = created.json()["id"]
    started = client.post("/api/experiments/start", headers=headers)
    assert started.status_code == 200
    body = started.json()
    assert set(body) == {"job"}
    job = body["job"]
    assert set(job) == JOB_FIELDS
    assert job["id"] == job_id
    assert job["status"] == "completed"
    assert job["completed"] == 4
    assert job["total"] == 4
    assert job["started_at"] is not None
    assert job["finished_at"] is not None
    assert job["summary"]["runtime_mode"] == DEFAULT_PLAN.runtime_mode
    assert job["summary"]["provenance"] == DEFAULT_PLAN.provenance
    assert engine.tasks == [
        {"variant": "A", "seed": 1},
        {"variant": "B", "seed": 1},
        {"variant": "A", "seed": 2},
        {"variant": "B", "seed": 2},
    ]
    runs = client.get(f"/api/jobs/{job_id}/runs", headers=headers)
    assert runs.status_code == 200
    assert runs.json()["total"] == 4
    empty = client.post("/api/experiments/start", headers=headers)
    assert empty.status_code == 204
    assert empty.content == b""
    assert "content-type" not in empty.headers


def test_start_without_queued_jobs_returns_204(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.post("/api/experiments/start", headers=auth(settings))
    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers


def test_start_uses_injected_experiment_service(tmp_path: Path):
    _, settings, _, database = make_app(tmp_path)
    completed = canned_job(status="completed", completed=1)
    stub = StubExperiments(start_result=completed)
    client = TestClient(create_app(settings, database, experiment_service=stub))
    response = client.post("/api/experiments/start", headers=auth(settings))
    assert response.status_code == 200
    assert response.json() == {"job": completed}
    assert stub.start_calls == 1
    stub.start_result = None
    empty = client.post("/api/experiments/start", headers=auth(settings))
    assert empty.status_code == 204
    assert empty.content == b""


def test_start_conflicts_with_running_job(tmp_path: Path):
    client, settings, jobs, _ = make_engine_app(tmp_path)
    headers = auth(settings)
    first = client.post("/api/experiments", json=experiment_payload(), headers=headers).json()
    jobs.update(first["id"], {"status": "running"})
    response = client.post("/api/experiments/start", headers=headers)
    assert response.status_code == 409
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "invalid_transition"
    assert "已有任务在运行" in error["message"]
    assert error["retriable"] is False
    assert jobs.get(first["id"])["status"] == "running"


def test_start_maps_errors_from_injected_service(tmp_path: Path):
    _, settings, _, database = make_app(tmp_path)
    headers = auth(settings)
    unavailable = StubExperiments(start_error=RuntimeError(ENGINE_UNAVAILABLE))
    client = TestClient(create_app(settings, database, experiment_service=unavailable))
    response = client.post("/api/experiments/start", headers=headers)
    assert response.status_code == 503
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "engine_unavailable"
    assert error["message"] == ENGINE_UNAVAILABLE
    assert error["retriable"] is True

    conflict = StubExperiments(start_error=ValueError("已有任务在运行"))
    second = TestClient(create_app(settings, database, experiment_service=conflict))
    response = second.post("/api/experiments/start", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_transition"
    assert response.json()["error"]["retriable"] is False


def test_missing_engine_is_engine_port_and_reports_unavailable():
    engine = MissingEngine()
    assert isinstance(engine, EnginePort)
    with pytest.raises(RuntimeError, match=ENGINE_UNAVAILABLE):
        engine.run_batch([], lambda result: None, lambda active: None)
    engine.cancel()


def test_start_without_configured_engine_returns_503(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    submitted = client.post("/api/experiments", json=experiment_payload(), headers=headers)
    assert submitted.status_code == 201
    response = client.post("/api/experiments/start", headers=headers)
    assert response.status_code == 503
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "engine_unavailable"
    assert error["message"] == ENGINE_UNAVAILABLE
    assert error["retriable"] is True


def test_cancel_experiment_contract(tmp_path: Path):
    client, settings, _, _ = make_engine_app(tmp_path)
    headers = auth(settings)
    missing = client.post("/api/experiments/missing-job/cancel", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    malformed = client.post("/api/experiments/bad.id/cancel", headers=headers)
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "validation_failed"

    queued = client.post("/api/experiments", json=experiment_payload(), headers=headers).json()
    cancelled = client.post(f"/api/experiments/{queued['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    value = cancelled.json()
    assert set(value) == JOB_FIELDS
    assert value["status"] == "cancelled"
    assert value["finished_at"] is not None
    again = client.post(f"/api/experiments/{queued['id']}/cancel", headers=headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_transition"
    assert again.json()["error"]["retriable"] is False

    completed = client.post("/api/experiments", json=experiment_payload(), headers=headers).json()
    assert client.post("/api/experiments/start", headers=headers).status_code == 200
    terminal = client.post(f"/api/experiments/{completed['id']}/cancel", headers=headers)
    assert terminal.status_code == 409
    assert terminal.json()["error"]["code"] == "invalid_transition"


def test_resume_experiment_contract(tmp_path: Path):
    client, settings, jobs, _ = make_engine_app(tmp_path)
    headers = auth(settings)
    missing = client.post("/api/experiments/missing-job/resume", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    queued = client.post("/api/experiments", json=experiment_payload(), headers=headers).json()
    conflict = client.post(f"/api/experiments/{queued['id']}/resume", headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "invalid_transition"

    jobs.update(queued["id"], {"status": "running"})
    jobs.update(queued["id"], {"status": "interrupted"})
    resumed = client.post(f"/api/experiments/{queued['id']}/resume", headers=headers)
    assert resumed.status_code == 200
    value = resumed.json()
    assert set(value) == JOB_FIELDS
    assert value["status"] == "queued"
    assert value["started_at"] is not None
    assert value["finished_at"] is None
    assert jobs.get(queued["id"])["status"] == "queued"


def test_resume_and_start_finishes_missing_matches(tmp_path: Path):
    client, settings, jobs, engine = make_engine_app(tmp_path)
    headers = auth(settings)
    job = client.post(
        "/api/experiments",
        json=experiment_payload(seeds=[1], variants=["A", "B"]),
        headers=headers,
    ).json()
    jobs.update(job["id"], {"status": "running"})
    jobs.append_run(
        job["id"],
        {
            "variant": "A",
            "seed": 1,
            "score_home": 1,
            "score_away": 0,
            "verified": True,
            "stats": {},
        },
    )
    jobs.update(job["id"], {"status": "interrupted"})
    assert client.post(f"/api/experiments/{job['id']}/resume", headers=headers).status_code == 200
    started = client.post("/api/experiments/start", headers=headers)
    assert started.status_code == 200
    assert started.json()["job"]["status"] == "completed"
    assert started.json()["job"]["completed"] == 2
    assert engine.tasks == [{"variant": "B", "seed": 1}]


def test_cancel_and_resume_use_injected_experiment_service(tmp_path: Path):
    _, settings, _, database = make_app(tmp_path)
    job = canned_job()
    stub = StubExperiments(job=job)
    second = create_app(settings, database, job_service=StubJobs(job), experiment_service=stub)
    client = TestClient(second)
    headers = auth(settings)
    cancelled = client.post(f"/api/experiments/{job['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert stub.cancelled == [job["id"]]
    resumed = client.post(f"/api/experiments/{job['id']}/resume", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"
    assert stub.resumed == [job["id"]]


def test_experiment_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    paths = document["paths"]
    for path in (
        "/api/experiments",
        "/api/experiments/start",
        "/api/experiments/{job_id}/cancel",
        "/api/experiments/{job_id}/resume",
    ):
        assert path in paths
        for method, operation in paths[path].items():
            if method not in HTTP_METHODS:
                continue
            assert operation["security"] == [{"HTTPBearer": []}], (path, method)
            assert "422" not in operation["responses"], (path, method)
            assert "401" in operation["responses"], (path, method)
            schema = operation["responses"]["401"]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("ErrorEnvelope"), (path, method)

    submit_operation = paths["/api/experiments"]["post"]
    submit_schema = submit_operation["responses"]["201"]["content"]["application/json"]["schema"]
    assert submit_schema["$ref"].endswith("JobOutput")
    for status in ("400", "409"):
        schema = submit_operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope"), status

    start_operation = paths["/api/experiments/start"]["post"]
    assert "204" in start_operation["responses"]
    started_schema = start_operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert started_schema["$ref"].endswith("ExperimentStartOutput")
    for status in ("409", "503"):
        schema = start_operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope"), status

    for path in (
        "/api/experiments/{job_id}/cancel",
        "/api/experiments/{job_id}/resume",
    ):
        operation = paths[path]["post"]
        success = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert success["$ref"].endswith("JobOutput")
        for status in ("400", "404", "409"):
            schema = operation["responses"][status]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("ErrorEnvelope"), (path, status)

    components = document["components"]["schemas"]
    submit_input = components["ExperimentSubmitInput"]
    assert set(submit_input["properties"]) == {
        "name",
        "seeds",
        "variants",
        "workers",
        "cpu_count",
        "available_memory_bytes",
        "free_disk_bytes",
        "allow_oversubscription",
    }
    assert submit_input["additionalProperties"] is False
    assert set(submit_input["required"]) == {
        "seeds",
        "variants",
        "workers",
        "cpu_count",
        "available_memory_bytes",
        "free_disk_bytes",
    }
    assert submit_input["properties"]["seeds"]["type"] == "array"
    assert submit_input["properties"]["seeds"]["items"]["type"] == "integer"
    assert submit_input["properties"]["variants"]["type"] == "array"
    assert submit_input["properties"]["variants"]["items"]["type"] == "string"
    assert submit_input["properties"]["allow_oversubscription"]["default"] is False
    assert components["ExperimentStartOutput"]["properties"]["job"]["$ref"].endswith("JobOutput")
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
