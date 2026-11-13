from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fm27lab.domain.compare import bootstrap_ci
from fm27lab.tests.test_http_health import make_app
from fm27lab.tests.test_http_results import (
    assert_error,
    auth,
    create_pool_job,
    pool_config,
    running_job,
)

COMPARE_PATH = "/api/results/compare"


def append_runs(app, job_id: str, runs) -> None:
    for run in runs:
        app.state.jobs.append_run(job_id, dict(run))


def paired_runs(entry: int | None = None) -> tuple[dict, dict]:
    first: dict = {"variant": "B", "seed": 1, "score_home": 2, "score_away": 1}
    second: dict = {"variant": "B", "seed": 2, "score_home": 0, "score_away": 0}
    if entry is not None:
        first["stats"] = {"tactic_pool_entry": entry}
        second["stats"] = {"tactic_pool_entry": (entry + 1) % 2}
    return first, second


def test_results_compare_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": "job-1", "candidate_job_ids": ["job-2"]},
    )
    assert_error(response, 401, "unauthorized")

    wrong = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": "job-1", "candidate_job_ids": ["job-2"]},
        headers={"Authorization": "Bearer wrong"},
    )
    assert_error(wrong, 401, "unauthorized")


def test_results_compare_without_pools_returns_paired_metrics(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    baseline = running_job(client, headers)
    candidate = running_job(client, headers)
    append_runs(app, baseline["id"], paired_runs())
    append_runs(app, candidate["id"], paired_runs())
    assert not hasattr(app.state, "results")

    response = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": baseline["id"], "candidate_job_ids": [candidate["id"]]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"baseline", "variant", "side", "candidates"}
    assert hasattr(app.state, "results")
    assert body["variant"] == "B"
    assert body["side"] == 0
    assert body["baseline"]["job_id"] == baseline["id"]
    assert body["baseline"]["name"] == "Experiment"
    assert body["baseline"]["metrics"]["n"] == 2
    assert body["baseline"]["tactic_pool"] == {
        "enabled": False,
        "entry_count": 0,
        "mode": None,
        "rounds": None,
        "players": None,
        "uniform": None,
        "entries": None,
        "draws": {},
    }
    candidate_body = body["candidates"][0]
    assert candidate_body["job_id"] == candidate["id"]
    assert candidate_body["comparable"] is True
    assert candidate_body["reason"] is None
    assert candidate_body["pairing"] is None
    assert candidate_body["paired"]["seeds"] == 2
    assert candidate_body["paired"]["win_rate_delta"] == pytest.approx(0.0)
    assert candidate_body["paired"]["points_delta"] == pytest.approx(0.0)
    assert candidate_body["paired"]["goal_difference_delta"] == pytest.approx(0.0)


def test_results_compare_pool_jobs_return_pairing(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    baseline = create_pool_job(client, headers, pool_config(2))
    candidate = create_pool_job(client, headers, pool_config(2))
    append_runs(app, baseline["id"], paired_runs(entry=0))
    append_runs(app, candidate["id"], paired_runs(entry=0))

    response = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": baseline["id"], "candidate_job_ids": [candidate["id"]]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["baseline"]["tactic_pool"]["enabled"] is True
    assert body["baseline"]["tactic_pool"]["entry_count"] == 2
    candidate_body = body["candidates"][0]
    assert candidate_body["comparable"] is True
    assert candidate_body["pairing"] == {
        "common_seeds": 2,
        "draw_mismatches": None,
        "mismatched_seeds": [],
        "missing_seeds": [],
    }
    assert candidate_body["paired"]["seeds"] == 2
    assert candidate_body["tactic_pool"]["draws"] == {"0": 1, "1": 1}


def test_results_compare_returns_not_found_for_unknown_jobs(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = running_job(client, headers)

    missing_candidate = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": job["id"], "candidate_job_ids": ["missing"]},
        headers=headers,
    )
    assert_error(missing_candidate, 404, "not_found")

    missing_baseline = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": "missing", "candidate_job_ids": [job["id"]]},
        headers=headers,
    )
    assert_error(missing_baseline, 404, "not_found")


VALID_BODY = {"baseline_job_id": "job-1", "candidate_job_ids": ["job-2"]}


@pytest.mark.parametrize(
    "payload",
    [
        {**VALID_BODY, "variant": "C"},
        {**VALID_BODY, "side": 2},
        {**VALID_BODY, "side": -1},
        {**VALID_BODY, "reps": 0},
        {**VALID_BODY, "reps": 20001},
        {**VALID_BODY, "candidate_job_ids": []},
        {**VALID_BODY, "candidate_job_ids": ["job-2", "job-2"]},
        {**VALID_BODY, "candidate_job_ids": [f"job-{index}" for index in range(2, 35)]},
        {**VALID_BODY, "variantt": "B"},
        {**VALID_BODY, "side": "1"},
        {**VALID_BODY, "reps": "50"},
        {**VALID_BODY, "side": 1.0},
        {**VALID_BODY, "side": True},
        {**VALID_BODY, "reps": 1.5},
        {"baseline_job_id": "job 1", "candidate_job_ids": ["job-2"]},
        {"baseline_job_id": "", "candidate_job_ids": ["job-2"]},
    ],
)
def test_results_compare_rejects_malformed_requests(tmp_path: Path, payload):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(COMPARE_PATH, json=payload, headers=auth(settings))

    assert_error(response, 400, "validation_failed")


def test_results_compare_rejects_baseline_in_candidates(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": "job-1", "candidate_job_ids": ["job-1"]},
        headers=auth(settings),
    )

    error = assert_error(response, 400, "validation_failed")
    assert error["message"] == "候选任务不能包含基线任务"


def test_results_compare_openapi_contract(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    document = TestClient(app).get("/api/openapi.json").json()

    operation = document["paths"][COMPARE_PATH]["post"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "422" not in operation["responses"]
    assert (
        operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        .endswith("CompareOutput")
    )
    for status in ("400", "401", "404"):
        assert (
            operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
            .endswith("ErrorEnvelope")
        )

    schemas = document["components"]["schemas"]
    expected_properties = {
        "CompareInput": {
            "baseline_job_id",
            "candidate_job_ids",
            "variant",
            "side",
            "reps",
        },
        "ComparePairingOutput": {
            "common_seeds",
            "draw_mismatches",
            "mismatched_seeds",
            "missing_seeds",
        },
        "ComparePairedOutput": {
            "seeds",
            "win_rate_delta",
            "win_rate_delta_ci",
            "points_delta",
            "points_delta_ci",
            "goal_difference_delta",
            "goal_difference_delta_ci",
            "xgd_delta",
            "xgd_delta_ci",
        },
        "CompareJobOutput": {"job_id", "name", "metrics", "tactic_pool"},
        "CompareCandidateOutput": {
            "job_id",
            "name",
            "metrics",
            "tactic_pool",
            "comparable",
            "reason",
            "pairing",
            "paired",
        },
        "CompareOutput": {"baseline", "variant", "side", "candidates"},
    }
    for name, properties in expected_properties.items():
        assert set(schemas[name]["properties"]) == properties, name
    assert schemas["CompareInput"]["additionalProperties"] is False
    assert set(schemas["CompareInput"]["required"]) == {
        "baseline_job_id",
        "candidate_job_ids",
    }


def test_results_compare_rejects_ids_longer_than_64_characters(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    long_id = "a" * 65

    for payload in (
        {"baseline_job_id": long_id, "candidate_job_ids": ["job-2"]},
        {"baseline_job_id": "job-1", "candidate_job_ids": [long_id]},
    ):
        response = client.post(COMPARE_PATH, json=payload, headers=headers)

        error = assert_error(response, 400, "validation_failed")
        assert error["message"] == "request body or query is invalid"


def test_results_compare_accepts_64_character_ids(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    job = running_job(client, headers)

    response = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": "a" * 64, "candidate_job_ids": [job["id"]]},
        headers=headers,
    )

    assert_error(response, 404, "not_found")


def test_results_compare_marks_pool_mismatch_as_unpaired_and_keeps_metrics(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    baseline = create_pool_job(client, headers, pool_config(2))
    candidate = running_job(client, headers)
    append_runs(app, baseline["id"], paired_runs(entry=0))
    append_runs(app, candidate["id"], paired_runs())

    response = client.post(
        COMPARE_PATH,
        json={"baseline_job_id": baseline["id"], "candidate_job_ids": [candidate["id"]]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["baseline"]["tactic_pool"]["enabled"] is True
    candidate_body = body["candidates"][0]
    assert candidate_body["comparable"] is False
    assert candidate_body["reason"] == "候选任务未使用客队战术池，基线任务使用了客队战术池"
    assert candidate_body["pairing"] == {
        "common_seeds": 2,
        "draw_mismatches": None,
        "mismatched_seeds": [],
        "missing_seeds": [],
    }
    assert candidate_body["paired"] is None
    assert candidate_body["tactic_pool"]["enabled"] is False
    assert candidate_body["metrics"]["n"] == 2
    assert candidate_body["metrics"]["win_rate"] is not None


def test_results_compare_forwards_variant_side_and_reps(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    baseline = running_job(client, headers, total=16)
    candidate = running_job(client, headers, total=16)
    baseline_a = [
        {"variant": "A", "seed": seed, "score_home": 0, "score_away": 0}
        for seed in range(1, 9)
    ]
    candidate_a = [
        {"variant": "A", "seed": 1, "score_home": 0, "score_away": 0},
        {"variant": "A", "seed": 2, "score_home": 0, "score_away": 1},
        {"variant": "A", "seed": 3, "score_home": 0, "score_away": 2},
        {"variant": "A", "seed": 4, "score_home": 0, "score_away": 3},
        {"variant": "A", "seed": 5, "score_home": 1, "score_away": 0},
        {"variant": "A", "seed": 6, "score_home": 2, "score_away": 0},
        {"variant": "A", "seed": 7, "score_home": 0, "score_away": 0},
        {"variant": "A", "seed": 8, "score_home": 0, "score_away": 1},
    ]
    baseline_b = [
        {"variant": "B", "seed": seed, "score_home": 5, "score_away": 0}
        for seed in range(1, 9)
    ]
    candidate_b = [
        {"variant": "B", "seed": seed, "score_home": 0, "score_away": 5}
        for seed in range(1, 9)
    ]
    append_runs(app, baseline["id"], baseline_a + baseline_b)
    append_runs(app, candidate["id"], candidate_a + candidate_b)

    response = client.post(
        COMPARE_PATH,
        json={
            "baseline_job_id": baseline["id"],
            "candidate_job_ids": [candidate["id"]],
            "variant": "A",
            "side": 1,
            "reps": 500,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["variant"] == "A"
    assert body["side"] == 1
    candidate_body = body["candidates"][0]
    assert candidate_body["comparable"] is True
    assert candidate_body["metrics"]["n"] == 8
    paired = candidate_body["paired"]
    assert paired["seeds"] == 8
    win_deltas = [0.0, 0.5, 0.5, 0.5, -0.5, -0.5, 0.0, 0.5]
    points_deltas = [0.0, 2.0, 2.0, 2.0, -1.0, -1.0, 0.0, 2.0]
    goal_deltas = [0.0, 1.0, 2.0, 3.0, -1.0, -2.0, 0.0, 1.0]
    assert paired["win_rate_delta"] == pytest.approx(0.125)
    assert paired["points_delta"] == pytest.approx(0.75)
    assert paired["goal_difference_delta"] == pytest.approx(0.5)
    for key, values in (
        ("win_rate_delta_ci", win_deltas),
        ("points_delta_ci", points_deltas),
        ("goal_difference_delta_ci", goal_deltas),
    ):
        expected = [round(value, 4) for value in bootstrap_ci(values, reps=500)]
        assert paired[key] == expected, key
