from __future__ import annotations

import csv
import io
import json
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.application.results import ResultsService
from fm27lab.tests.test_http_health import make_app

CSV_COLUMNS = [
    "job_id",
    "sequence",
    "variant",
    "seed",
    "score_home",
    "score_away",
    "verified",
    "created_at",
    "stats_json",
    "events_json",
]
ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
PAIRED_RUNS = (
    {"variant": "A", "seed": 1, "score_home": 3, "score_away": 0},
    {"variant": "B", "seed": 1, "score_home": 1, "score_away": 0},
    {"variant": "A", "seed": 2, "score_home": 0, "score_away": 1},
    {"variant": "B", "seed": 2, "score_home": 2, "score_away": 2},
)


def auth(settings) -> dict:
    return {"Authorization": f"Bearer {settings.token}"}


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == code
    return error


def create_job(client: TestClient, headers: dict, total: int = 4) -> dict:
    response = client.post(
        "/api/jobs",
        json={"kind": "experiment", "name": "Experiment", "total": total},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def running_job(client: TestClient, headers: dict, total: int = 4) -> dict:
    job = create_job(client, headers, total)
    response = client.patch(f"/api/jobs/{job['id']}", json={"status": "running"}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def append_paired_runs(app, job_id: str) -> None:
    for run in PAIRED_RUNS:
        app.state.jobs.append_run(job_id, dict(run))


def test_results_http_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    job = create_job(client, auth(settings))
    responses = (
        client.get(f"/api/jobs/{job['id']}/summary"),
        client.get(f"/api/jobs/{job['id']}/summary?side=1"),
        client.get(f"/api/jobs/{job['id']}/export.csv"),
    )
    for response in responses:
        assert response.status_code == 401
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS
        assert error["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    wrong = client.get(
        f"/api/jobs/{job['id']}/summary",
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"


def test_results_http_summary_reports_metrics_and_lazily_builds_service(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = running_job(client, headers)
    append_paired_runs(app, job["id"])
    assert not hasattr(app.state, "results")

    response = client.get(f"/api/jobs/{job['id']}/summary", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"job", "metrics", "paired"}
    assert body["job"] == client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    metrics = body["metrics"]
    assert metrics["n"] == 4
    assert metrics["wins"] == 2
    assert metrics["draws"] == 1
    assert metrics["losses"] == 1
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["goals_for"] == pytest.approx(1.5)
    assert metrics["goals_against"] == pytest.approx(0.75)
    assert metrics["points"] == pytest.approx(1.75)
    assert body["paired"] == {"n": 2, "goal_difference_delta": pytest.approx(-0.5)}
    assert isinstance(app.state.results, ResultsService)


def test_results_http_summary_orients_metrics_to_away_side(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = running_job(client, headers)
    append_paired_runs(app, job["id"])

    response = client.get(f"/api/jobs/{job['id']}/summary?side=1", headers=headers)

    assert response.status_code == 200, response.text
    metrics = response.json()["metrics"]
    assert metrics["wins"] == 1
    assert metrics["draws"] == 1
    assert metrics["losses"] == 2
    assert metrics["win_rate"] == pytest.approx(0.25)
    assert metrics["goals_for"] == pytest.approx(0.75)
    assert metrics["goals_against"] == pytest.approx(1.5)
    assert response.json()["paired"]["goal_difference_delta"] == pytest.approx(0.5)


def test_results_http_summary_side_query_edge_behaviour(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = running_job(client, headers)
    append_paired_runs(app, job["id"])
    home = client.get(f"/api/jobs/{job['id']}/summary?side=0", headers=headers).json()
    away = client.get(f"/api/jobs/{job['id']}/summary?side=1", headers=headers).json()

    repeated = client.get(f"/api/jobs/{job['id']}/summary?side=0&side=1", headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["metrics"] == away["metrics"]
    trailing = client.get(f"/api/jobs/{job['id']}/summary?side=1&side=0", headers=headers)
    assert trailing.status_code == 200
    assert trailing.json()["metrics"] == home["metrics"]

    # _query_integer 按十进制解析前导零，side=01 等价于 side=1。
    for query, expected in (("side=00", home), ("side=01", away)):
        padded = client.get(f"/api/jobs/{job['id']}/summary?{query}", headers=headers)
        assert padded.status_code == 200
        assert padded.json()["metrics"] == expected["metrics"]


def test_results_http_summary_without_runs_has_no_metrics(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_job(client, headers)

    response = client.get(f"/api/jobs/{job['id']}/summary", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metrics"] is None
    assert body["paired"] == {"n": 0, "goal_difference_delta": None}
    assert body["job"]["status"] == "queued"


def test_results_http_summary_missing_job_and_invalid_side(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_job(client, headers)

    assert_error(client.get("/api/jobs/missing/summary", headers=headers), 404, "not_found")
    for side in ("2", "-1", "abc", "1.5", "%20", ""):
        response = client.get(f"/api/jobs/{job['id']}/summary?side={side}", headers=headers)
        assert_error(response, 400, "validation_failed")
    for identifier in ("存档", "a b", "x" * 65):
        quoted = urllib.parse.quote(identifier, safe="")
        assert_error(
            client.get(f"/api/jobs/{quoted}/summary", headers=headers),
            400,
            "validation_failed",
        )
        assert_error(
            client.get(f"/api/jobs/{quoted}/export.csv", headers=headers),
            400,
            "validation_failed",
        )


def test_results_http_csv_export_headers_content_and_determinism(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = running_job(client, headers, total=2)
    stats = {"teams": [{"xg": 1.5}, {"xg": 0.5}], "note": "中文"}
    events = {"goals": [{"side": 0, "clock": 12}]}
    app.state.jobs.append_run(
        job["id"],
        {
            "variant": "A",
            "seed": 5,
            "score_home": 2,
            "score_away": 1,
            "verified": True,
            "stats": stats,
            "events": events,
        },
    )
    app.state.jobs.append_run(
        job["id"],
        {
            "variant": "B",
            "seed": 6,
            "score_home": None,
            "score_away": None,
            "verified": False,
            "stats": {},
        },
    )

    response = client.get(f"/api/jobs/{job['id']}/export.csv", headers=headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="job-{job["id"]}.csv"'
    expected_bytes = app.state.results.export_csv(job["id"]).encode("utf-8")
    assert response.content == expected_bytes
    text = expected_bytes.decode("utf-8")
    assert text.endswith("\r\n")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 3
    assert rows[1][0] == job["id"]
    assert rows[1][1:6] == ["1", "A", "5", "2", "1"]
    assert rows[1][6] == "true"
    assert json.loads(rows[1][8]) == stats
    assert json.loads(rows[1][9]) == events
    assert rows[2][1:6] == ["2", "B", "6", "", ""]
    assert rows[2][6] == "false"
    assert rows[2][8] == "{}"
    assert rows[2][9] == ""

    again = client.get(f"/api/jobs/{job['id']}/export.csv", headers=headers)
    assert again.content == response.content


def test_results_http_csv_export_missing_job_is_not_found(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)

    assert_error(client.get("/api/jobs/missing/export.csv", headers=headers), 404, "not_found")


def test_results_http_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    paths = document["paths"]
    for path in ("/api/jobs/{job_id}/summary", "/api/jobs/{job_id}/export.csv"):
        assert path in paths

    summary_operation = paths["/api/jobs/{job_id}/summary"]["get"]
    assert summary_operation["security"] == [{"HTTPBearer": []}]
    assert "422" not in summary_operation["responses"]
    for status in ("400", "401", "404"):
        schema = summary_operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope"), status
    success = summary_operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success["$ref"].endswith("ResultsSummaryOutput")
    parameters = {item["name"]: item["schema"] for item in summary_operation["parameters"]}
    assert parameters["side"]["type"] == "integer"
    assert parameters["side"]["minimum"] == 0
    assert parameters["side"]["maximum"] == 1
    assert parameters["side"]["default"] == 0
    assert parameters["side"]["enum"] == [0, 1]

    csv_operation = paths["/api/jobs/{job_id}/export.csv"]["get"]
    assert csv_operation["security"] == [{"HTTPBearer": []}]
    assert "422" not in csv_operation["responses"]
    assert "200" in csv_operation["responses"]
    assert "text/csv" in csv_operation["responses"]["200"]["content"]
    for status in ("400", "401", "404"):
        schema = csv_operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope"), status

    components = document["components"]["schemas"]
    summary_schema = components["ResultsSummaryOutput"]
    assert set(summary_schema["properties"]) == {"job", "metrics", "paired"}
    assert set(summary_schema["required"]) == {"job", "metrics", "paired"}
    assert summary_schema["properties"]["job"]["$ref"].endswith("JobOutput")
    assert document["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_results_http_cors_405_and_existing_routes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    preflight = client.options(
        "/api/jobs/x/summary",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert preflight.status_code == 200
    assert "GET" in preflight.headers["access-control-allow-methods"]

    wrong_summary = client.put("/api/jobs/x/summary", headers=headers)
    assert wrong_summary.status_code == 405
    allowed = {item.strip() for item in wrong_summary.headers["allow"].split(",")}
    assert "GET" in allowed
    wrong_csv = client.post("/api/jobs/x/export.csv", headers=headers)
    assert wrong_csv.status_code == 405
    assert "GET" in {item.strip() for item in wrong_csv.headers["allow"].split(",")}

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/version").status_code == 200
    assert client.get("/api/jobs", headers=headers).json()["items"] == []
    assert client.get("/api/pools", headers=headers).json()["items"] == []
    assert client.get("/api/drafts", headers=headers).json()["items"] == []
    assert client.get("/api/saves", headers=headers).json()["items"] == []


def pool_config(entry_count: int = 2) -> dict:
    return {
        "enabled": True,
        "entries": [
            {"name": f"客队战术 {index + 1}", "weight": index + 1, "tactic": {}}
            for index in range(entry_count)
        ],
        "uniform": {"enabled": True, "attribute_value": 15},
        "rotation": {"enabled": False, "rounds": 1},
        "real": {"enabled": False},
    }


def create_pool_job(client: TestClient, headers: dict, pool: dict, total: int = 4) -> dict:
    response = client.post(
        "/api/jobs",
        json={"kind": "experiment", "name": "Pool", "config": {"away_tactic_pool": pool}, "total": total},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    job = response.json()
    started = client.patch(f"/api/jobs/{job['id']}", json={"status": "running"}, headers=headers)
    assert started.status_code == 200, started.text
    return started.json()


def test_results_http_pool_summary_reports_entries_and_draws(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_pool_job(client, headers, pool_config(2))
    app.state.jobs.append_run(
        job["id"],
        {"variant": "A", "seed": 21, "score_home": 2, "score_away": 0, "stats": {"tactic_pool_entry": 1}},
    )
    app.state.jobs.append_run(
        job["id"],
        {
            "variant": "B",
            "seed": 21,
            "score_home": 1,
            "score_away": 0,
            "stats": {"tactic_pool_entry": {"index": 1}},
        },
    )
    assert not hasattr(app.state, "results")

    response = client.get(f"/api/jobs/{job['id']}/pool-summary", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "enabled",
        "entry_count",
        "mode",
        "rounds",
        "players",
        "uniform",
        "entries",
        "draws",
    }
    assert body["mode"] == "random"
    assert body["rounds"] == 1
    assert body["players"] == "uniform"
    assert [row["index"] for row in body["entries"]] == [0, 1]
    assert [row["name"] for row in body["entries"]] == ["客队战术 1", "客队战术 2"]
    assert body["entries"][0]["probability"] == pytest.approx(1 / 3)
    assert body["draws"] == {"0": 0, "1": 1}
    assert isinstance(app.state.results, ResultsService)


def test_results_http_pool_summary_is_disabled_without_pool_config(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_job(client, headers)

    response = client.get(f"/api/jobs/{job['id']}/pool-summary", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "enabled": False,
        "entry_count": 0,
        "mode": None,
        "players": None,
        "draws": {},
    }


def test_results_http_pool_summary_disabled_pool_keeps_entry_count(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_pool_job(client, headers, {**pool_config(2), "enabled": False})

    response = client.get(f"/api/jobs/{job['id']}/pool-summary", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "enabled": False,
        "entry_count": 2,
        "mode": None,
        "players": None,
        "draws": {},
    }


def test_results_http_pool_summary_missing_job_and_invalid_config(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    invalid = client.post(
        "/api/jobs",
        json={"kind": "experiment", "config": {"away_tactic_pool": {}}},
        headers=headers,
    )
    assert invalid.status_code == 201, invalid.text
    invalid_id = invalid.json()["id"]

    error = assert_error(
        client.get(f"/api/jobs/{invalid_id}/pool-summary", headers=headers), 400, "validation_failed"
    )
    assert any("\u4e00" <= character <= "\u9fff" for character in error["message"])
    assert_error(client.get("/api/jobs/missing/pool-summary", headers=headers), 404, "not_found")
    for identifier in ("存档", "a b", "x" * 65):
        quoted = urllib.parse.quote(identifier, safe="")
        assert_error(
            client.get(f"/api/jobs/{quoted}/pool-summary", headers=headers),
            400,
            "validation_failed",
        )


def test_results_http_pool_summary_rejects_non_boolean_enabled(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "experiment",
            "config": {"away_tactic_pool": {"enabled": "yes", "entries": [{"name": "客队"}]}},
        },
        headers=headers,
    )
    assert job.status_code == 201, job.text

    response = client.get(f"/api/jobs/{job.json()['id']}/pool-summary", headers=headers)

    error = assert_error(response, 400, "validation_failed")
    assert error["message"] == "客队战术池开关无效"


def test_results_http_pool_summary_rejects_non_get_methods(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_job(client, headers)

    response = client.post(f"/api/jobs/{job['id']}/pool-summary", headers=headers)

    assert response.status_code == 405
    allowed = {item.strip() for item in response.headers["allow"].split(",")}
    assert "GET" in allowed


def test_results_http_pool_summary_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = create_job(client, headers)

    denied = client.get(f"/api/jobs/{job['id']}/pool-summary")
    assert denied.status_code == 401
    error = denied.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "unauthorized"
    assert denied.headers["www-authenticate"] == "Bearer"

    wrong = client.get(
        f"/api/jobs/{job['id']}/pool-summary",
        headers={"Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"


def test_results_http_pool_summary_openapi_contract(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()
    operation = document["paths"]["/api/jobs/{job_id}/pool-summary"]["get"]

    assert operation["security"] == [{"HTTPBearer": []}]
    assert "422" not in operation["responses"]
    for status in ("400", "401", "404"):
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope"), status
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success["$ref"].endswith("PoolSummaryOutput")

    components = document["components"]["schemas"]
    assert set(components["PoolSummaryOutput"]["properties"]) == {
        "enabled",
        "entry_count",
        "mode",
        "rounds",
        "players",
        "uniform",
        "entries",
        "draws",
    }
    assert set(components["PoolSummaryEntryOutput"]["properties"]) == {
        "index",
        "name",
        "weight",
        "probability",
        "roster",
    }
    assert set(components["PoolSummaryUniformOutput"]["properties"]) == {"enabled", "attribute_value"}
