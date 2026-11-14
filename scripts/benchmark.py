"""Performance benchmarks for sidecar read paths and pure domain helpers."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from fm27lab.adapters.storage_sqlite.db import Database  # noqa: E402
from fm27lab.adapters.storage_sqlite.repositories import JobRepository  # noqa: E402
from fm27lab.config import Settings  # noqa: E402
from fm27lab.domain.compare import bootstrap_ci  # noqa: E402
from fm27lab.domain.pool import expand_away_scenarios  # noqa: E402
from fm27lab.domain.scenario import normalize_scenario  # noqa: E402
from fm27lab.interfaces.http.app import create_app  # noqa: E402

OUTPUT_VERSION = "1"
TOKEN = "b" * 64
JOB_COUNT = 50
RUN_PAIRS = 50
POOL_ENTRIES = 8
WARMUP = 2
POSITION_CODES = ("GK", "SW", "DL", "DC", "DR", "DM", "ML", "MC", "MR", "AML", "ST")
PROFILES: dict[str, dict[str, int]] = {
    "quick": {"http": 5, "normalize": 10, "pool": 10, "bootstrap": 3},
    "full": {"http": 50, "normalize": 200, "pool": 100, "bootstrap": 30},
}


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * fraction / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _benchmark(
    name: str,
    unit: str,
    operation: Callable[[], None],
    iterations: int,
) -> dict[str, Any]:
    for _ in range(WARMUP):
        operation()
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000.0)
    total_ms = sum(samples)
    return {
        "name": name,
        "unit": unit,
        "iterations": iterations,
        "total_ms": round(total_ms, 3),
        "per_op_ms": round(total_ms / iterations, 3),
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(_percentile(samples, 95.0), 3),
        "throughput_per_s": round(iterations * 1000.0 / total_ms, 2) if total_ms > 0 else 0.0,
    }


def _normalize_player(uid: int, position: int) -> dict[str, Any]:
    attributes = [10] * 69
    attributes[position] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes, "ability": 10}


def _normalize_team(name: str, base: int) -> dict[str, Any]:
    return {
        "name": name,
        "players": [_normalize_player(base + index, 0 if index == 0 else 7) for index in range(23)],
        "roster_size": 23,
        "lineup": list(range(11)),
        "captains": [5],
        "takers": {"penalties": [6]},
        "setpieces": {"role_priorities": {"8": [8]}, "routines": {}},
        "phases": [[], []],
    }


def _normalize_fixture() -> dict[str, Any]:
    return {
        "schema": 4,
        "teams": [_normalize_team("Home", 100), _normalize_team("Away", 300)],
        "away_tactic_pool": {"enabled": False, "entries": []},
    }


def _pool_player(uid: int) -> dict[str, Any]:
    return {"source_uid": uid, "name": f"P{uid}", "attributes": [5] * 15 + [50] * 54}


def _pool_team(name: str, base: int) -> dict[str, Any]:
    return {
        "name": name,
        "players": [_pool_player(base + index) for index in range(23)],
        "roster_size": 23,
        "lineup": list(range(11)),
        "captains": [0],
        "takers": {},
        "setpieces": {},
    }


def _pool_cell(position: str) -> dict[str, Any]:
    return {"position": position, "role": "角色", "duty": "0"}


def _pool_tactic(index: int) -> dict[str, Any]:
    return {
        "tactic_name": f"bench-tactic-{index}",
        "mentality": 3,
        "instructions": {"1": 2},
        "native_extra_team_bits": "7",
        "phases": [[_pool_cell(code) for code in POSITION_CODES] for _ in range(2)],
    }


def _pool_fixture() -> dict[str, Any]:
    return {
        "profile": "away-tactic-pool-v1",
        "enabled": True,
        "entries": [
            {"name": f"bench-entry-{index}", "weight": index + 1, "tactic": _pool_tactic(index)}
            for index in range(POOL_ENTRIES)
        ],
        "uniform": {"enabled": True, "attribute_value": 15},
        "rotation": {"enabled": False, "rounds": 1},
        "real": {"enabled": False},
    }


def _pool_operation(
    scenario: Mapping[str, Any],
    pool: Mapping[str, Any],
    seed_count: int,
) -> Callable[[], None]:
    seeds = list(range(seed_count))
    cursor = 0

    def operation() -> None:
        nonlocal cursor
        seed = seeds[cursor % seed_count]
        cursor += 1
        expand_away_scenarios(scenario, pool, [seed], "benchmark")

    return operation


def _paired_values() -> list[float]:
    return [((index * 37) % 13 - 6) / 4.0 for index in range(200)]


def _seed_job(index: int, summary_job_id: str) -> dict[str, Any]:
    total = RUN_PAIRS * 2 if index == 0 else 2
    return {
        "id": summary_job_id if index == 0 else f"bench-job-{index:03d}",
        "kind": "experiment",
        "status": "completed",
        "config": {"seeds": RUN_PAIRS} if index == 0 else {},
        "workers": 1,
        "total": total,
        "completed": total,
    }


def _seed_run(seed: int, variant: str) -> dict[str, Any]:
    return {
        "sequence": seed * 2 + (1 if variant == "A" else 2),
        "variant": variant,
        "seed": seed,
        "score_home": (seed + (1 if variant == "A" else 2)) % 3,
        "score_away": (seed * 2 + (0 if variant == "A" else 1)) % 3,
        "verified": True,
        "stats": {
            "teams": [
                {"xg": 1.4, "possession": 55, "shots": 12, "passes": 600, "completed_passes": 540},
                {"xg": 0.9, "possession": 45, "shots": 8, "passes": 400, "completed_passes": 320},
            ]
        },
    }


def _seed_http_data(database: Database, summary_job_id: str) -> None:
    repository = JobRepository(database)
    with database.transaction() as connection:
        for index in range(JOB_COUNT):
            repository.add(_seed_job(index, summary_job_id), connection=connection)
        for seed in range(RUN_PAIRS):
            for variant in ("A", "B"):
                repository.add_run(summary_job_id, _seed_run(seed, variant), connection=connection)


def _check_jobs(payload: Mapping[str, Any]) -> None:
    if len(payload["items"]) != JOB_COUNT:
        raise RuntimeError("任务列表未返回预期条数")


def _check_runs(payload: Mapping[str, Any]) -> None:
    if len(payload["items"]) != RUN_PAIRS * 2:
        raise RuntimeError("比赛列表未返回预期条数")


def _check_summary(payload: Mapping[str, Any]) -> None:
    metrics = payload["metrics"]
    if not isinstance(metrics, Mapping) or metrics.get("n") != RUN_PAIRS * 2:
        raise RuntimeError("结果汇总未覆盖预期比赛数")


def _request_operation(
    client: TestClient,
    path: str,
    headers: Mapping[str, str],
    check: Callable[[Mapping[str, Any]], None],
) -> Callable[[], None]:
    def operation() -> None:
        response = client.get(path, headers=dict(headers))
        if response.status_code != 200:
            raise RuntimeError(f"{path} 返回状态码 {response.status_code}")
        check(response.json())

    return operation


def _bench_http(directory: Path, iterations: int) -> list[dict[str, Any]]:
    settings = Settings.create(data_dir=directory, token=TOKEN, dev=True)
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    summary_job_id = "bench-summary-job"
    _seed_http_data(database, summary_job_id)
    app = create_app(settings, database)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    client = TestClient(app)
    try:
        return [
            _benchmark(
                "http.jobs_list",
                "request",
                _request_operation(client, "/api/jobs?limit=50", headers, _check_jobs),
                iterations,
            ),
            _benchmark(
                "http.job_runs",
                "request",
                _request_operation(
                    client,
                    f"/api/jobs/{summary_job_id}/runs?limit=100",
                    headers,
                    _check_runs,
                ),
                iterations,
            ),
            _benchmark(
                "http.jobs_summary",
                "request",
                _request_operation(client, f"/api/jobs/{summary_job_id}/summary", headers, _check_summary),
                iterations,
            ),
        ]
    finally:
        client.close()


def _bench_domain(iterations: Mapping[str, int]) -> list[dict[str, Any]]:
    scenario = _normalize_fixture()
    pool_scenario = {"teams": [_pool_team("Home", 100), _pool_team("Away", 300)]}
    pool = _pool_fixture()
    values = _paired_values()
    return [
        _benchmark(
            "scenario.normalize",
            "scenario",
            lambda: normalize_scenario(scenario),
            iterations["normalize"],
        ),
        _benchmark(
            "pool.expand_away",
            "seed",
            _pool_operation(pool_scenario, pool, iterations["pool"]),
            iterations["pool"],
        ),
        _benchmark(
            "compare.bootstrap_ci",
            "call",
            lambda: bootstrap_ci(values, reps=2000),
            iterations["bootstrap"],
        ),
    ]


def _environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count() or 0,
    }


def _run(mode: str) -> dict[str, Any]:
    iterations = PROFILES[mode]
    with tempfile.TemporaryDirectory(prefix="fm27lab-benchmark-") as directory:
        results = _bench_http(Path(directory), iterations["http"])
    results.extend(_bench_domain(iterations))
    return {
        "version": OUTPUT_VERSION,
        "mode": mode,
        "environment": _environment(),
        "results": results,
    }


def _format_table(results: list[dict[str, Any]]) -> str:
    header = (
        f"{'name':<22}{'unit':>8}{'iterations':>12}{'total_ms':>12}"
        f"{'per_op_ms':>12}{'p50_ms':>10}{'p95_ms':>10}{'throughput_per_s':>18}"
    )
    lines = [header, "-" * len(header)]
    for result in results:
        lines.append(
            f"{result['name']:<22}{result['unit']:>8}{result['iterations']:>12}"
            f"{result['total_ms']:>12.3f}{result['per_op_ms']:>12.3f}"
            f"{result['p50_ms']:>10.3f}{result['p95_ms']:>10.3f}"
            f"{result['throughput_per_s']:>18.2f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run fm27lab performance benchmarks.")
    parser.add_argument("--quick", action="store_true", help="run the small iteration profile")
    parser.add_argument("--json", dest="as_json", action="store_true", help="write a JSON report to stdout")
    arguments = parser.parse_args(argv)
    report = _run("quick" if arguments.quick else "full")
    if arguments.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_table(report["results"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
