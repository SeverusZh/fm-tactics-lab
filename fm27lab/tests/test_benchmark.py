from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "benchmark.py"
EXPECTED_RESULTS = {
    "compare.bootstrap_ci",
    "http.job_runs",
    "http.jobs_list",
    "http.jobs_summary",
    "pool.expand_away",
    "scenario.normalize",
}
RESULT_FIELDS = {
    "iterations",
    "name",
    "p50_ms",
    "p95_ms",
    "per_op_ms",
    "throughput_per_s",
    "total_ms",
    "unit",
}
QUICK_ITERATIONS = {
    "compare.bootstrap_ci": 3,
    "http.job_runs": 5,
    "http.jobs_list": 5,
    "http.jobs_summary": 5,
    "pool.expand_away": 10,
    "scenario.normalize": 10,
}


def run_script(*arguments: str) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    return completed, time.perf_counter() - started


@pytest.fixture(scope="module")
def quick_report() -> tuple[dict[str, object], float]:
    completed, elapsed = run_script("--quick", "--json")
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout), elapsed


@pytest.fixture(scope="module")
def benchmark_module():
    spec = importlib.util.spec_from_file_location("benchmark_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quick_json_report_follows_contract(quick_report):
    report, elapsed = quick_report
    assert set(report) == {"version", "mode", "environment", "results"}
    assert report["version"] == "1"
    assert report["mode"] == "quick"
    environment = report["environment"]
    assert isinstance(environment, dict)
    assert set(environment) == {"python", "platform", "cpu_count"}
    assert isinstance(environment["python"], str) and environment["python"]
    assert isinstance(environment["platform"], str) and environment["platform"]
    assert isinstance(environment["cpu_count"], int) and environment["cpu_count"] >= 1
    results = report["results"]
    assert isinstance(results, list) and results
    for result in results:
        assert isinstance(result, dict)
        assert set(result) == RESULT_FIELDS
        assert isinstance(result["name"], str) and result["name"]
        assert isinstance(result["unit"], str) and result["unit"]
        assert type(result["iterations"]) is int and result["iterations"] >= 1
        for field in ("total_ms", "per_op_ms", "p50_ms", "p95_ms", "throughput_per_s"):
            value = result[field]
            assert type(value) is float, field
            assert math.isfinite(value) and value >= 0, field
        iterations = result["iterations"]
        assert result["p50_ms"] <= result["p95_ms"]
        assert result["per_op_ms"] == pytest.approx(result["total_ms"] / iterations, rel=1e-3, abs=0.002)
        assert result["throughput_per_s"] == pytest.approx(
            iterations * 1000.0 / result["total_ms"], rel=0.02, abs=1.0
        )
    assert any(result["p95_ms"] > result["p50_ms"] for result in results)
    assert elapsed < 30


def test_quick_report_keeps_every_benchmark_name(quick_report):
    report, _ = quick_report
    results = report["results"]
    assert isinstance(results, list)
    names = [result["name"] for result in results if isinstance(result, dict)]
    assert set(names) == EXPECTED_RESULTS
    assert len(names) == len(set(names))


def test_quick_report_uses_quick_iteration_profile(quick_report):
    report, _ = quick_report
    results = report["results"]
    assert isinstance(results, list)
    iterations = {result["name"]: result["iterations"] for result in results if isinstance(result, dict)}
    assert iterations == QUICK_ITERATIONS


def test_percentile_uses_linear_interpolation(benchmark_module):
    percentile = benchmark_module._percentile
    assert percentile([0.0, 10.0], 95.0) == pytest.approx(9.5)
    assert percentile([0.0, 10.0], 50.0) == pytest.approx(5.0)
    assert percentile([1.0, 2.0, 3.0, 4.0], 50.0) == pytest.approx(2.5)
    assert percentile([0.0, 10.0], 0.0) == pytest.approx(0.0)
    assert percentile([0.0, 10.0], 100.0) == pytest.approx(10.0)
    assert percentile([4.0], 95.0) == pytest.approx(4.0)


def test_human_report_prints_table_with_every_benchmark():
    completed, _ = run_script("--quick")
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout
    assert output.strip()
    with pytest.raises(json.JSONDecodeError):
        json.loads(output)
    for name in EXPECTED_RESULTS:
        assert name in output
