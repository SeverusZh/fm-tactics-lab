from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient

from fm27lab.adapters.engine_native.capabilities import parse_capabilities, plan_runtime
from fm27lab.adapters.engine_native.host import NativeEngineHost
from fm27lab.adapters.engine_native.lazy import LazyNativeEngine
from fm27lab.adapters.engine_native.scenario_assets import load_scenario_assets
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository, JobRepository
from fm27lab.application.drafts import DraftService
from fm27lab.application.experiment_material import ExperimentMaterializer
from fm27lab.application.experiments import ExperimentService
from fm27lab.application.jobs import JobService
from fm27lab.config import Settings
from fm27lab.domain.roster import POSITION_SLOTS, canonical_position
from fm27lab.interfaces.http.app import MissingEngine, create_app
from fm27lab.ports.engine import EngineCapabilities, EnginePort
from fm27lab.tests.test_experiment_material import engine_scenario
from fm27lab.tests.test_http_health import make_app
from fm27lab.tests.test_scenario_assets import POSITION_ORDER, write_engine_root

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
FAKE_SIMULATOR = Path(__file__).resolve().parent / "fixtures" / "fake_simulator.py"


def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def experiment_payload(**overrides) -> dict:
    value = {
        "name": "Experiment",
        "seeds": [1, 2],
        "draft_id": "draft-1",
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


def build_settings(tmp_path: Path, *, engine: bool = True) -> Settings:
    settings = Settings.create(
        data_dir=tmp_path / "data",
        engine_root=write_engine_root(tmp_path) if engine else None,
        token="c" * 64,
        dev=True,
    )
    settings.ensure_dirs()
    return settings


def seed_drafts(database: Database, settings: Settings) -> tuple[str, str]:
    assert settings.engine_root is not None
    assets = load_scenario_assets(settings.engine_root)
    repository = DraftRepository(database)
    draft_id = repository.add(
        {
            "name": "候选",
            "scenario": engine_scenario(assets, home_name="候选主队"),
            "source": {},
        }
    )["id"]
    baseline_id = repository.add(
        {
            "name": "基线",
            "scenario": engine_scenario(assets, home_name="基线主队"),
            "source": {},
        }
    )["id"]
    return draft_id, baseline_id


class EngineApp(NamedTuple):
    client: TestClient
    settings: Settings
    jobs: JobService
    engine: FakeEngine
    draft_id: str
    baseline_id: str


def make_engine_app(tmp_path: Path) -> EngineApp:
    settings = build_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    draft_id, baseline_id = seed_drafts(database, settings)
    drafts = DraftService(DraftRepository(database))
    jobs = JobService(JobRepository(database))
    engine = FakeEngine()
    experiments = ExperimentService(
        jobs,
        engine,
        DEFAULT_PLAN,
        materializer=ExperimentMaterializer(drafts, settings),
    )
    app = create_app(
        settings,
        database,
        job_service=jobs,
        draft_service=drafts,
        experiment_service=experiments,
    )
    return EngineApp(TestClient(app), settings, jobs, engine, draft_id, baseline_id)


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


class StubDrafts:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self.rows = {} if rows is None else rows
        self.requested: list[str] = []

    def get(self, draft_id: str):
        self.requested.append(draft_id)
        row = self.rows.get(draft_id)
        return copy.deepcopy(row) if row is not None else None


def draft_row(scenario: dict, draft_id: str = "draft-1") -> dict:
    return {"id": draft_id, "name": draft_id, "scenario": scenario, "source": None}


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
    app = make_engine_app(tmp_path)
    client = app.client
    headers = auth(app.settings)
    response = client.post(
        "/api/experiments",
        json=experiment_payload(name=None, draft_id=app.draft_id),
        headers=headers,
    )
    assert response.status_code == 201
    job = response.json()
    assert set(job) == JOB_FIELDS
    assert job["kind"] == "experiment"
    assert job["status"] == "queued"
    assert job["name"] is None
    assert job["config"]["seeds"] == [1, 2]
    assert job["config"]["variants"] == ["B"]
    assert job["config"]["draft_id"] == app.draft_id
    assert job["config"]["baseline_draft_id"] is None
    materialized = job["config"]["materialized"]
    assert materialized["codec"] == "FM27CFG1"
    assert [item["variant"] for item in materialized["configs"]] == ["B", "B"]
    assert [item["seed"] for item in materialized["configs"]] == [1, 2]
    for item in materialized["configs"]:
        config_file = Path(item["config_file"])
        assert config_file.is_absolute()
        assert config_file.is_file()
        assert config_file.name == f"B-{item['seed']}.bin"
        assert config_file.read_bytes()[:8] == b"FM27CFG1"
        scenario_file = Path(item["scenario_file"])
        assert scenario_file.is_relative_to(app.settings.data_dir)
    assert materialized["pool"] is None
    assert job["workers"] == 2
    assert job["total"] == 2
    assert job["completed"] == 0
    assert job["started_at"] is None
    assert job["finished_at"] is None
    assert job["summary"]["runtime_mode"] == "isolated_worker"
    assert job["summary"]["provenance"] == DEFAULT_PLAN.provenance
    assert job["summary"]["provenance"]["fallback_reason"] == "counted_sessions_unavailable"
    assert job["summary"]["configs_count"] == 2
    fetched = client.get(f"/api/jobs/{job['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == job


def test_submit_with_baseline_draft_uses_ab_variants(tmp_path: Path):
    app = make_engine_app(tmp_path)
    response = app.client.post(
        "/api/experiments",
        json=experiment_payload(
            seeds=[5],
            draft_id=app.draft_id,
            baseline_draft_id=app.baseline_id,
        ),
        headers=auth(app.settings),
    )
    assert response.status_code == 201
    job = response.json()
    assert job["config"]["variants"] == ["A", "B"]
    assert job["config"]["baseline_draft_id"] == app.baseline_id
    configs = job["config"]["materialized"]["configs"]
    assert [(item["variant"], item["seed"]) for item in configs] == [("A", 5), ("B", 5)]
    assert job["total"] == 2
    assert job["summary"]["configs_count"] == 2


def test_submit_uses_injected_experiment_service(tmp_path: Path):
    _, settings, _, database = make_app(tmp_path)
    stub = StubExperiments()
    second = create_app(settings, database, experiment_service=stub)
    client = TestClient(second)
    payload = experiment_payload(
        name="Injected",
        seeds=[3, 1],
        draft_id="draft-9",
        baseline_draft_id="draft-8",
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
            "config": {"seeds": [3, 1]},
            "workers": 4,
            "name": "Injected",
            "cpu_count": 16,
            "available_memory_bytes": 64 * GIB,
            "free_disk_bytes": 200 * GIB,
            "allow_oversubscription": True,
            "draft_id": "draft-9",
            "baseline_draft_id": "draft-8",
        }
    ]
    assert second.state.jobs.list()["total"] == 0


def test_submit_resource_preflight_returns_409(tmp_path: Path):
    app = make_engine_app(tmp_path)
    client = app.client
    headers = auth(app.settings)
    payload = experiment_payload(draft_id=app.draft_id)
    memory = client.post(
        "/api/experiments",
        json={**payload, "available_memory_bytes": GIB},
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
        json={**payload, "free_disk_bytes": 3 * GIB},
        headers=headers,
    )
    assert disk.status_code == 409
    assert disk.json()["error"]["code"] == "insufficient_disk"
    assert "磁盘" in disk.json()["error"]["message"]
    assert app.jobs.list()["total"] == 0
    allowed = client.post(
        "/api/experiments",
        json={**payload, "available_memory_bytes": GIB, "allow_oversubscription": True},
        headers=headers,
    )
    assert allowed.status_code == 201
    assert app.jobs.list()["total"] == 1


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
        experiment_payload(seeds=[4294967296]),
        experiment_payload(seeds=["1"]),
        experiment_payload(seeds=[True]),
        experiment_payload(seeds=list(range(10001))),
        experiment_payload(draft_id=None),
        experiment_payload(draft_id=""),
        experiment_payload(draft_id="bad.id"),
        experiment_payload(draft_id="x" * 65),
        experiment_payload(baseline_draft_id="bad id"),
        experiment_payload(variants=["A", "B"]),
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


def test_submit_rejects_total_matches_above_limit(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/experiments",
        json=experiment_payload(
            seeds=list(range(10000)),
            draft_id="draft-1",
            baseline_draft_id="draft-0",
        ),
        headers=auth(settings),
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert "实验总场数不能超过 10000" in error["message"]
    assert app.state.jobs.list()["total"] == 0


def test_submit_missing_draft_returns_404(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    stub = StubDrafts()
    second = create_app(settings, database, draft_service=stub)
    client = TestClient(second)
    response = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id="missing-draft"),
        headers=auth(settings),
    )
    assert response.status_code == 404
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "not_found"
    assert error["message"] == "草案不存在"
    assert error["retriable"] is False
    assert stub.requested == ["missing-draft"]
    assert second.state.jobs.list()["total"] == 0


def test_submit_missing_baseline_draft_returns_404(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    assets = load_scenario_assets(write_engine_root(tmp_path / "fixtures"))
    stub = StubDrafts({"draft-1": draft_row(engine_scenario(assets))})
    second = create_app(settings, database, draft_service=stub)
    client = TestClient(second)
    response = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id="draft-1", baseline_draft_id="missing-baseline"),
        headers=auth(settings),
    )
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "基线草案不存在"
    assert stub.requested == ["draft-1", "missing-baseline"]
    assert second.state.jobs.list()["total"] == 0


def test_submit_without_configured_engine_returns_400(tmp_path: Path):
    app, settings, _, database = make_app(tmp_path)
    assets = load_scenario_assets(write_engine_root(tmp_path / "fixtures"))
    stub = StubDrafts({"draft-1": draft_row(engine_scenario(assets))})
    second = create_app(settings, database, draft_service=stub)
    client = TestClient(second)
    response = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id="draft-1"),
        headers=auth(settings),
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["message"] == "引擎目录未配置，无法生成比赛配置"
    assert second.state.jobs.list()["total"] == 0


def test_submit_without_catalog_returns_400(tmp_path: Path):
    settings = Settings.create(
        data_dir=tmp_path / "data",
        engine_root=tmp_path / "empty-engine",
        token="c" * 64,
        dev=True,
    )
    settings.ensure_dirs()
    (tmp_path / "empty-engine").mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_path)
    database.initialize()
    assets = load_scenario_assets(write_engine_root(tmp_path / "fixtures"))
    stub = StubDrafts({"draft-1": draft_row(engine_scenario(assets))})
    app = create_app(settings, database, draft_service=stub)
    client = TestClient(app)
    response = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id="draft-1"),
        headers=auth(settings),
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert "引擎目录文件" in error["message"]
    assert app.state.jobs.list()["total"] == 0


def test_start_dispatches_materialized_config_paths(tmp_path: Path):
    app = make_engine_app(tmp_path)
    client = app.client
    headers = auth(app.settings)
    created = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id=app.draft_id),
        headers=headers,
    )
    assert created.status_code == 201
    job = created.json()
    job_id = job["id"]
    materialized = job["config"]["materialized"]
    started = client.post("/api/experiments/start", headers=headers)
    assert started.status_code == 200
    body = started.json()
    assert set(body) == {"job"}
    finished = body["job"]
    assert set(finished) == JOB_FIELDS
    assert finished["id"] == job_id
    assert finished["status"] == "completed"
    assert finished["completed"] == 2
    assert finished["total"] == 2
    assert finished["started_at"] is not None
    assert finished["finished_at"] is not None
    assert finished["summary"]["runtime_mode"] == DEFAULT_PLAN.runtime_mode
    assert finished["summary"]["provenance"] == DEFAULT_PLAN.provenance
    assert app.engine.tasks == [
        {
            "variant": item["variant"],
            "seed": item["seed"],
            "config": item["config_file"],
        }
        for item in materialized["configs"]
    ]
    assert all(Path(task["config"]).is_absolute() for task in app.engine.tasks)
    runs = client.get(f"/api/jobs/{job_id}/runs", headers=headers)
    assert runs.status_code == 200
    assert runs.json()["total"] == 2
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
    app = make_engine_app(tmp_path)
    client = app.client
    headers = auth(app.settings)
    first = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id=app.draft_id),
        headers=headers,
    ).json()
    app.jobs.update(first["id"], {"status": "running"})
    response = client.post("/api/experiments/start", headers=headers)
    assert response.status_code == 409
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "invalid_transition"
    assert "已有任务在运行" in error["message"]
    assert error["retriable"] is False
    assert app.jobs.get(first["id"])["status"] == "running"


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


def test_create_app_builds_materializer_and_lazy_default_engine(tmp_path: Path):
    settings = build_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    draft_id, _ = seed_drafts(database, settings)
    jobs = JobService(JobRepository(database))
    app = create_app(settings, database, job_service=jobs)
    client = TestClient(app)
    assert isinstance(app.state.experiments, ExperimentService)
    default_engine = app.state.experiments._engine
    assert isinstance(default_engine, LazyNativeEngine)
    assert default_engine._host is None
    submitted = client.post(
        "/api/experiments",
        json=experiment_payload(seeds=[1], draft_id=draft_id),
        headers=auth(settings),
    )
    assert submitted.status_code == 201
    job = submitted.json()
    assert job["config"]["materialized"]["codec"] == "FM27CFG1"
    assert job["summary"]["configs_count"] == 1
    assert job["summary"]["runtime_mode"] == DEFAULT_PLAN.runtime_mode
    assert job["summary"]["provenance"] == DEFAULT_PLAN.provenance


def test_create_app_passes_the_configured_game_root_to_the_lazy_engine(tmp_path: Path):
    settings = build_settings(tmp_path)
    game_root = tmp_path / "game"
    game_root.mkdir()
    settings = replace(settings, game_root=game_root)
    database = Database(settings.database_path)
    database.initialize()
    app = create_app(settings, database)
    engine = app.state.experiments._engine
    assert isinstance(engine, LazyNativeEngine)
    assert engine._game_root == game_root


class _RecordingHostFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        raise AssertionError("create_app must not construct the native host")


def test_create_app_does_not_construct_the_native_engine(tmp_path: Path):
    settings = build_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    factory = _RecordingHostFactory()
    lazy = LazyNativeEngine(settings.engine_root, tmp_path / "engine-work", factory=factory)
    create_app(settings, database, engine=lazy)
    assert factory.calls == []
    assert lazy._host is None


def test_create_app_builds_materializer_and_default_engine(tmp_path: Path):
    settings = build_settings(tmp_path, engine=False)
    materializer_settings = build_settings(tmp_path / "assets")
    database = Database(settings.database_path)
    database.initialize()
    draft_id, _ = seed_drafts(database, materializer_settings)
    drafts = DraftService(DraftRepository(database))
    jobs = JobService(JobRepository(database))
    materializer = ExperimentMaterializer(drafts, materializer_settings)
    app = create_app(
        settings,
        database,
        job_service=jobs,
        draft_service=drafts,
        experiment_materializer=materializer,
    )
    client = TestClient(app)
    headers = auth(settings)
    assert isinstance(app.state.experiments._engine, MissingEngine)
    submitted = client.post(
        "/api/experiments",
        json=experiment_payload(seeds=[1], draft_id=draft_id),
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    job = submitted.json()
    started = client.post("/api/experiments/start", headers=headers)
    assert started.status_code == 503
    error = started.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "engine_unavailable"
    assert error["message"] == ENGINE_UNAVAILABLE
    assert error["retriable"] is True
    assert jobs.get(job["id"])["status"] == "error"
    assert jobs.get(job["id"])["summary"]["error"] == ENGINE_UNAVAILABLE


def test_explicit_engine_takes_precedence_over_configured_root(tmp_path: Path):
    settings = build_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    jobs = JobService(JobRepository(database))
    engine = FakeEngine()
    app = create_app(settings, database, job_service=jobs, engine=engine)
    assert app.state.experiments._engine is engine
    assert not isinstance(app.state.experiments._engine, LazyNativeEngine)


def test_default_runtime_plan_is_built_from_engine_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, settings, _, database = make_app(tmp_path)
    engine = FakeEngine()
    recorded = []

    def recording(capabilities, *, has_pool_variants, has_experimental_execution):
        recorded.append((capabilities, has_pool_variants, has_experimental_execution))
        return DEFAULT_PLAN

    monkeypatch.setattr("fm27lab.interfaces.http.app.plan_runtime", recording)
    app = create_app(settings, database, engine=engine)
    plan = app.state.experiments._runtime_plan
    assert callable(plan)
    assert recorded == []
    assert plan() == DEFAULT_PLAN
    capabilities, pool_variants, experimental_execution = recorded[0]
    assert capabilities == engine.capabilities()
    assert pool_variants is False
    assert experimental_execution is False


def test_cancel_experiment_contract(tmp_path: Path):
    app = make_engine_app(tmp_path)
    client = app.client
    headers = auth(app.settings)
    missing = client.post("/api/experiments/missing-job/cancel", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    malformed = client.post("/api/experiments/bad.id/cancel", headers=headers)
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "validation_failed"

    queued = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id=app.draft_id),
        headers=headers,
    ).json()
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

    completed = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id=app.draft_id),
        headers=headers,
    ).json()
    assert client.post("/api/experiments/start", headers=headers).status_code == 200
    terminal = client.post(f"/api/experiments/{completed['id']}/cancel", headers=headers)
    assert terminal.status_code == 409
    assert terminal.json()["error"]["code"] == "invalid_transition"


def test_resume_experiment_contract(tmp_path: Path):
    app = make_engine_app(tmp_path)
    client = app.client
    headers = auth(app.settings)
    missing = client.post("/api/experiments/missing-job/resume", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    queued = client.post(
        "/api/experiments",
        json=experiment_payload(draft_id=app.draft_id),
        headers=headers,
    ).json()
    conflict = client.post(f"/api/experiments/{queued['id']}/resume", headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "invalid_transition"

    app.jobs.update(queued["id"], {"status": "running"})
    app.jobs.update(queued["id"], {"status": "interrupted"})
    resumed = client.post(f"/api/experiments/{queued['id']}/resume", headers=headers)
    assert resumed.status_code == 200
    value = resumed.json()
    assert set(value) == JOB_FIELDS
    assert value["status"] == "queued"
    assert value["started_at"] is not None
    assert value["finished_at"] is None
    assert app.jobs.get(queued["id"])["status"] == "queued"


def test_resume_and_start_finishes_missing_matches(tmp_path: Path):
    app = make_engine_app(tmp_path)
    client = app.client
    headers = auth(app.settings)
    job = client.post(
        "/api/experiments",
        json=experiment_payload(
            seeds=[1],
            draft_id=app.draft_id,
            baseline_draft_id=app.baseline_id,
        ),
        headers=headers,
    ).json()
    materialized = job["config"]["materialized"]
    assert [(item["variant"], item["seed"]) for item in materialized["configs"]] == [
        ("A", 1),
        ("B", 1),
    ]
    app.jobs.update(job["id"], {"status": "running"})
    app.jobs.append_run(
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
    app.jobs.update(job["id"], {"status": "interrupted"})
    assert client.post(f"/api/experiments/{job['id']}/resume", headers=headers).status_code == 200
    started = client.post("/api/experiments/start", headers=headers)
    assert started.status_code == 200
    assert started.json()["job"]["status"] == "completed"
    assert started.json()["job"]["completed"] == 2
    missing_config = materialized["configs"][1]["config_file"]
    assert app.engine.tasks == [{"variant": "B", "seed": 1, "config": missing_config}]


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
    for status in ("400", "404", "409"):
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
        "draft_id",
        "baseline_draft_id",
        "workers",
        "cpu_count",
        "available_memory_bytes",
        "free_disk_bytes",
        "allow_oversubscription",
    }
    assert submit_input["additionalProperties"] is False
    assert set(submit_input["required"]) == {
        "seeds",
        "draft_id",
        "workers",
        "cpu_count",
        "available_memory_bytes",
        "free_disk_bytes",
    }
    seeds = submit_input["properties"]["seeds"]
    assert seeds["type"] == "array"
    assert seeds["items"]["type"] == "integer"
    assert seeds["items"]["minimum"] == 0
    assert seeds["items"]["maximum"] == 4294967295
    assert seeds["minItems"] == 1
    assert seeds["maxItems"] == 10000
    draft_id = submit_input["properties"]["draft_id"]
    assert draft_id["type"] == "string"
    assert draft_id["minLength"] == 1
    assert draft_id["maxLength"] == 64
    assert draft_id["pattern"] == "^[A-Za-z0-9_-]+$"
    assert "variants" not in submit_input["properties"]
    assert submit_input["properties"]["allow_oversubscription"]["default"] is False
    assert components["ExperimentStartOutput"]["properties"]["job"]["$ref"].endswith("JobOutput")
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"

def normalizable_scenario(assets, *, home_name: str = "主队", home_mentality: int = 4) -> dict:
    slot_index = {name: index for index, name in enumerate(POSITION_SLOTS)}
    teams = []
    for side, base in enumerate(assets.default_teams):
        team = copy.deepcopy(base)
        team["name"] = home_name if side == 0 else "客队"
        for index, player in enumerate(team["players"]):
            player["source_uid"] = f"{side}-{index}"
            position = POSITION_ORDER[index] if index < 11 else "MC"
            attributes = [0] * 15 + list(player["attributes"][15:])
            attributes[slot_index[canonical_position(position)]] = 20
            player["attributes"] = attributes
        team["lineup"] = list(range(11))
        team["substitutes"] = list(range(11, 23))
        team["captains"] = [0]
        team["takers"] = {key: [] for key in team["takers"]}
        team["takers"]["penalties"] = [0]
        team["setpieces"] = copy.deepcopy(team["setpieces"])
        team["setpieces"]["role_priorities"] = {str(group): [] for group in range(8)}
        team["mentality"] = home_mentality if side == 0 else 4
        teams.append(team)
    return {"schema": 3, "rules": "lab", "fixture": "bundled_match_pkm", "teams": teams}


def test_end_to_end_draft_create_submit_and_start(tmp_path: Path):
    app = make_engine_app(tmp_path)
    client, settings = app.client, app.settings
    headers = auth(settings)
    assets = load_scenario_assets(settings.engine_root)
    candidate = client.post(
        "/api/drafts",
        json={"name": "候选草案", "scenario": normalizable_scenario(assets)},
        headers=headers,
    )
    assert candidate.status_code == 201, candidate.text
    baseline = client.post(
        "/api/drafts",
        json={
            "name": "基线草案",
            "scenario": normalizable_scenario(assets, home_name="基线主队", home_mentality=3),
        },
        headers=headers,
    )
    assert baseline.status_code == 201, baseline.text
    submitted = client.post(
        "/api/experiments",
        json=experiment_payload(
            seeds=[11, 12],
            draft_id=candidate.json()["id"],
            baseline_draft_id=baseline.json()["id"],
        ),
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    job = submitted.json()
    materialized = job["config"]["materialized"]
    assert job["total"] == 4
    assert job["summary"]["configs_count"] == 4
    assert [(entry["variant"], entry["seed"]) for entry in materialized["configs"]] == [
        ("A", 11),
        ("B", 11),
        ("A", 12),
        ("B", 12),
    ]
    started = client.post("/api/experiments/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["job"]["status"] == "completed"
    assert app.engine.tasks == [
        {
            "variant": entry["variant"],
            "seed": entry["seed"],
            "config": entry["config_file"],
        }
        for entry in materialized["configs"]
    ]
    binaries = [Path(task["config"]).read_bytes() for task in app.engine.tasks]
    assert all(data.startswith(b"FM27CFG1") for data in binaries)
    assert len({data for data in binaries}) == 2
    runs = app.jobs.runs(job["id"], limit=10)
    assert runs["total"] == 4
    assert len(runs["items"]) == 4

def materialized_client(tmp_path: Path) -> tuple[TestClient, Settings, dict[str, str], str]:
    settings = build_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    draft_id, _ = seed_drafts(database, settings)
    return TestClient(create_app(settings, database)), settings, auth(settings), draft_id


def submit_materialized_job(
    client: TestClient, headers: dict[str, str], draft_id: str, seed: int
) -> tuple[dict, Path]:
    submitted = client.post(
        "/api/experiments",
        json=experiment_payload(seeds=[seed], draft_id=draft_id, workers=1),
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    job = submitted.json()
    directory = Path(job["config"]["materialized"]["dir"])
    assert directory.is_dir()
    return job, directory


def test_delete_job_removes_materialized_directory(tmp_path: Path):
    client, _, headers, draft_id = materialized_client(tmp_path)
    job, directory = submit_materialized_job(client, headers, draft_id, 3)

    deleted = client.delete(f"/api/jobs/{job['id']}", headers=headers)

    assert deleted.status_code == 204, deleted.text
    assert not directory.exists()


def test_batch_delete_removes_materialized_directories(tmp_path: Path):
    client, _, headers, draft_id = materialized_client(tmp_path)
    directories: list[Path] = []
    ids: list[str] = []
    for seed in (3, 4):
        job, directory = submit_materialized_job(client, headers, draft_id, seed)
        cancelled = client.post(f"/api/experiments/{job['id']}/cancel", headers=headers)
        assert cancelled.status_code == 200, cancelled.text
        ids.append(job["id"])
        directories.append(directory)

    removed = client.request("DELETE", "/api/jobs", json={"ids": ids}, headers=headers)

    assert removed.status_code == 200, removed.text
    assert removed.json()["deleted"] == ids
    assert all(not directory.exists() for directory in directories)


def test_batch_delete_action_removes_materialized_directory(tmp_path: Path):
    client, _, headers, draft_id = materialized_client(tmp_path)
    job, directory = submit_materialized_job(client, headers, draft_id, 3)

    actions = client.post(
        "/api/jobs/actions",
        json={"action": "delete", "ids": [job["id"]]},
        headers=headers,
    )

    assert actions.status_code == 200, actions.text
    assert actions.json()["succeeded"] == [job["id"]]
    assert not directory.exists()


def test_end_to_end_native_engine_host_wiring(tmp_path: Path):
    settings = build_settings(tmp_path)
    assert settings.engine_root is not None
    fixture = settings.engine_root / "fm27_native" / "fixtures" / "match.pkm"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_bytes(b"fake match fixture")
    database = Database(settings.database_path)
    database.initialize()
    drafts = DraftService(DraftRepository(database))
    jobs = JobService(JobRepository(database))
    work_dir = tmp_path / "native-work"
    work_dir.mkdir()
    host = NativeEngineHost(
        settings.engine_root,
        work_dir,
        executable=FAKE_SIMULATOR,
        retries=0,
    )
    app = create_app(
        settings,
        database,
        job_service=jobs,
        draft_service=drafts,
        engine=host,
    )
    client = TestClient(app)
    headers = auth(settings)
    assets = load_scenario_assets(settings.engine_root)
    candidate = client.post(
        "/api/drafts",
        json={"name": "候选草案", "scenario": normalizable_scenario(assets)},
        headers=headers,
    )
    assert candidate.status_code == 201, candidate.text
    baseline = client.post(
        "/api/drafts",
        json={
            "name": "基线草案",
            "scenario": normalizable_scenario(assets, home_name="基线主队", home_mentality=3),
        },
        headers=headers,
    )
    assert baseline.status_code == 201, baseline.text
    submitted = client.post(
        "/api/experiments",
        json=experiment_payload(
            seeds=[11, 12],
            draft_id=candidate.json()["id"],
            baseline_draft_id=baseline.json()["id"],
        ),
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    job = submitted.json()
    materialized = job["config"]["materialized"]
    assert job["total"] == 4
    assert [(entry["variant"], entry["seed"]) for entry in materialized["configs"]] == [
        ("A", 11),
        ("B", 11),
        ("A", 12),
        ("B", 12),
    ]
    config_paths = [Path(entry["config_file"]) for entry in materialized["configs"]]
    assert all(path.is_absolute() for path in config_paths)
    assert all(path.read_bytes().startswith(b"FM27CFG1") for path in config_paths)
    started = client.post("/api/experiments/start", headers=headers)
    assert started.status_code == 200, started.text
    finished = started.json()["job"]
    assert finished["status"] == "completed"
    assert finished["completed"] == 4
    runs = client.get(f"/api/jobs/{job['id']}/runs?limit=10", headers=headers)
    assert runs.status_code == 200
    runs_body = runs.json()
    assert runs_body["total"] == 4
    assert {(item["variant"], item["seed"]) for item in runs_body["items"]} == {
        ("A", 11),
        ("B", 11),
        ("A", 12),
        ("B", 12),
    }
    assert all(item["score"] is not None for item in runs_body["items"])
    assert all(Path(item["log_path"]).is_file() for item in runs_body["items"])
    summary = client.get(f"/api/jobs/{job['id']}/summary", headers=headers)
    assert summary.status_code == 200
    summary_body = summary.json()
    assert set(summary_body) == {"job", "metrics", "paired"}
    assert summary_body["job"]["status"] == "completed"
    assert summary_body["metrics"]["n"] == 4


def legacy_scenario(native: dict) -> dict:
    value = copy.deepcopy(native)
    value["schema"] = 4
    for team in value["teams"]:
        instructions = team.pop("instructions", {})
        phases = team.pop("phases")
        team["phase_plans"] = [
            {
                "phase": "in_possession",
                "team_instructions": instructions,
                "assignments": phases[0],
            },
            {
                "phase": "out_of_possession",
                "team_instructions": {},
                "assignments": phases[1],
            },
        ]
    return value


def test_end_to_end_legacy_scenario_drafts_materialize(tmp_path: Path):
    app = make_engine_app(tmp_path)
    client, settings = app.client, app.settings
    headers = auth(settings)
    assets = load_scenario_assets(settings.engine_root)
    candidate = client.post(
        "/api/drafts",
        json={"name": "旧版候选", "scenario": legacy_scenario(normalizable_scenario(assets))},
        headers=headers,
    )
    assert candidate.status_code == 201, candidate.text
    baseline = client.post(
        "/api/drafts",
        json={
            "name": "旧版基线",
            "scenario": legacy_scenario(
                normalizable_scenario(assets, home_name="基线主队", home_mentality=3)
            ),
        },
        headers=headers,
    )
    assert baseline.status_code == 201, baseline.text
    for response in (candidate, baseline):
        stored = response.json()["scenario"]
        assert stored["schema"] == 3
        assert all("phase_plans" not in team for team in stored["teams"])
    submitted = client.post(
        "/api/experiments",
        json=experiment_payload(
            seeds=[21, 22],
            draft_id=candidate.json()["id"],
            baseline_draft_id=baseline.json()["id"],
        ),
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    job = submitted.json()
    materialized = job["config"]["materialized"]
    assert job["total"] == 4
    assert job["summary"]["configs_count"] == 4
    assert [(entry["variant"], entry["seed"]) for entry in materialized["configs"]] == [
        ("A", 21),
        ("B", 21),
        ("A", 22),
        ("B", 22),
    ]
    started = client.post("/api/experiments/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["job"]["status"] == "completed"
    binaries = [Path(entry["config_file"]).read_bytes() for entry in materialized["configs"]]
    assert all(data.startswith(b"FM27CFG1") for data in binaries)
    runs = app.jobs.runs(job["id"], limit=10)
    assert runs["total"] == 4
    assert len(runs["items"]) == 4
