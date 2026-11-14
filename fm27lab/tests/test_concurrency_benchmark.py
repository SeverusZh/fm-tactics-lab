"""Concurrency lane benchmark tests driven by the fake simulator fixture."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import time
import tomllib
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "concurrency_benchmark.py"
SIMULATOR = ROOT / "fm27lab" / "tests" / "fixtures" / "fake_simulator.py"
DOCUMENT = ROOT / "docs" / "PERFORMANCE.md"
TOP_LEVEL_FIELDS = {"version", "mode", "environment", "params", "results"}
ENVIRONMENT_FIELDS = {"cpu_count", "platform", "python"}
PARAMS_FIELDS = {"tasks", "lanes", "match_seconds", "simulator"}
RESULT_FIELDS = {"workers", "tasks", "seconds", "seconds_per_match", "speedup", "completed"}
SERIAL_LANES = 1
PARALLEL_LANES = 2
EXPECTED_LANES = [1, 2]
QUICK_TASKS = 2
MATCH_SECONDS = 2.0
SPEEDUP_FLOOR = 1.2
QUICK_BUDGET_SECONDS = 60.0


def run_script(
    *arguments: str,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=env,
    )
    return completed, time.perf_counter() - started


@pytest.fixture(scope="module")
def quick_run() -> tuple[dict[str, object], float]:
    completed, elapsed = run_script("--quick", "--json")
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout), elapsed


@pytest.fixture(scope="module")
def quick_report(quick_run: tuple[dict[str, object], float]) -> dict[str, object]:
    return quick_run[0]


@pytest.fixture(scope="module")
def benchmark_module():
    spec = importlib.util.spec_from_file_location("concurrency_benchmark_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def results_by_workers(report: dict[str, object]) -> dict[int, dict[str, object]]:
    results = report["results"]
    assert isinstance(results, list)
    return {result["workers"]: result for result in results}


def test_quick_json_report_follows_contract(quick_run: tuple[dict[str, object], float]) -> None:
    report, elapsed = quick_run
    assert set(report) == TOP_LEVEL_FIELDS
    assert report["mode"] == "quick"
    assert elapsed < QUICK_BUDGET_SECONDS

    environment = report["environment"]
    assert isinstance(environment, dict)
    assert set(environment) == ENVIRONMENT_FIELDS
    assert type(environment["cpu_count"]) is int
    assert environment["cpu_count"] >= 1
    assert isinstance(environment["platform"], str) and environment["platform"]
    assert isinstance(environment["python"], str) and environment["python"]

    params = report["params"]
    assert isinstance(params, dict)
    assert set(params) == PARAMS_FIELDS
    assert params["tasks"] == QUICK_TASKS
    assert params["lanes"] == EXPECTED_LANES
    assert params["match_seconds"] == pytest.approx(MATCH_SECONDS)
    simulator = Path(params["simulator"])
    assert simulator.is_absolute()
    assert simulator.resolve() == SIMULATOR.resolve()

    results = report["results"]
    assert isinstance(results, list)
    assert len(results) == len(EXPECTED_LANES)
    for result in results:
        assert isinstance(result, dict)
        assert set(result) == RESULT_FIELDS
        assert type(result["workers"]) is int
        assert result["tasks"] == QUICK_TASKS
        assert result["completed"] == QUICK_TASKS
        assert type(result["seconds"]) is float
        assert result["seconds"] > 0
        assert type(result["seconds_per_match"]) is float
        assert result["seconds_per_match"] > 0
        assert type(result["speedup"]) is float
        assert result["speedup"] > 0
    assert [result["workers"] for result in results] == EXPECTED_LANES
    assert results_by_workers(report)[SERIAL_LANES]["speedup"] == pytest.approx(1.0)


def test_quick_report_version_matches_project_version(quick_report: dict[str, object]) -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert quick_report["version"] == project["project"]["version"]
    assert quick_report["version"] == importlib.metadata.version("fm27lab")


def test_serial_lane_seconds_per_match_matches_fixture_delay(quick_report: dict[str, object]) -> None:
    baseline = results_by_workers(quick_report)[SERIAL_LANES]
    per_match = baseline["seconds_per_match"]
    assert isinstance(per_match, float)
    assert 1.7 <= per_match <= 2.3
    assert per_match == pytest.approx(baseline["seconds"] / baseline["completed"], abs=1e-3)


def test_parallel_lanes_shorten_wall_clock(quick_report: dict[str, object]) -> None:
    lanes = results_by_workers(quick_report)
    parallel = lanes[PARALLEL_LANES]
    assert parallel["speedup"] > SPEEDUP_FLOOR
    assert parallel["seconds"] < lanes[SERIAL_LANES]["seconds"]


def test_compute_speedup_is_baseline_ratio(benchmark_module) -> None:
    compute = benchmark_module.compute_speedup
    assert compute(4.0, 2.0) == pytest.approx(2.0)
    assert compute(4.0, 4.0) == pytest.approx(1.0)
    assert compute(1.0, 3.0) == 0.3333
    assert compute(2.0, 3.0) == 0.6667


def test_compute_speedup_rejects_missing_baseline_and_zero_time(benchmark_module) -> None:
    compute = benchmark_module.compute_speedup
    with pytest.raises(ValueError, match="基准"):
        compute(None, 2.0)
    with pytest.raises(ValueError, match="基准"):
        compute(0.0, 2.0)
    with pytest.raises(ValueError, match="正数"):
        compute(4.0, 0.0)
    with pytest.raises(ValueError, match="正数"):
        compute(4.0, -1.0)


def test_seconds_per_match_divides_by_completed_matches(benchmark_module) -> None:
    per_match = benchmark_module.compute_seconds_per_match
    assert per_match(4.0, 2) == pytest.approx(2.0)
    assert per_match(2.0, 2) == pytest.approx(1.0)
    assert per_match(0.5, 1) == pytest.approx(0.5)
    with pytest.raises(ValueError, match="完成场数"):
        per_match(4.0, 0)


def test_summarize_uses_single_worker_measurement_as_baseline(benchmark_module) -> None:
    measurements = [
        {"workers": 1, "tasks": 4, "seconds": 8.0, "completed": 4},
        {"workers": 2, "tasks": 4, "seconds": 4.0, "completed": 4},
        {"workers": 4, "tasks": 4, "seconds": 2.0, "completed": 4},
    ]
    results = benchmark_module.summarize(measurements)
    assert [result["workers"] for result in results] == [1, 2, 4]
    assert [result["speedup"] for result in results] == pytest.approx([1.0, 2.0, 4.0])
    assert [result["seconds_per_match"] for result in results] == pytest.approx([2.0, 1.0, 0.5])
    assert all(result["tasks"] == 4 for result in results)
    assert all(result["completed"] == 4 for result in results)


def test_summarize_rejects_missing_baseline(benchmark_module) -> None:
    with pytest.raises(ValueError, match="基准"):
        benchmark_module.summarize([{"workers": 2, "tasks": 2, "seconds": 2.0, "completed": 2}])


def test_ensure_complete_rejects_incomplete_batches(benchmark_module) -> None:
    module = benchmark_module
    module.ensure_complete(
        [{"workers": 1, "completed": 2}, {"workers": 2, "completed": 2}],
        2,
    )
    with pytest.raises(module.BenchmarkError, match="未完成"):
        module.ensure_complete(
            [{"workers": 1, "completed": 1}, {"workers": 2, "completed": 2}],
            2,
        )
    with pytest.raises(module.BenchmarkError, match="两档"):
        module.ensure_complete([{"workers": 1, "completed": 2}], 2)


def test_missing_simulator_fails_with_chinese_reason(tmp_path: Path) -> None:
    completed, _ = run_script("--quick", "--json", "--simulator", str(tmp_path / "missing.py"))
    assert completed.returncode != 0
    assert "模拟器" in completed.stderr


def test_incomplete_batch_exits_non_zero_with_chinese_reason() -> None:
    environment = dict(os.environ)
    environment["FAKE_SIMULATOR_EXIT_AFTER"] = "1"
    completed, _ = run_script("--quick", "--json", env=environment)
    assert completed.returncode != 0
    assert "未完成" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_human_report_prints_chinese_table() -> None:
    completed, _ = run_script("--quick")
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout
    assert output.strip()
    with pytest.raises(json.JSONDecodeError):
        json.loads(output)
    assert "并发通道" in output
    assert "加速比" in output


def table_display_width(line: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in line)


def test_human_table_columns_share_width(benchmark_module) -> None:
    report = {
        "mode": "quick",
        "params": {"tasks": 2, "lanes": [1, 2], "match_seconds": 2.0, "simulator": "/tmp/fake.py"},
        "results": [
            {
                "workers": 1,
                "tasks": 2,
                "seconds": 4.0575,
                "seconds_per_match": 2.0288,
                "speedup": 1.0,
                "completed": 2,
            },
            {
                "workers": 2,
                "tasks": 2,
                "seconds": 2.031,
                "seconds_per_match": 1.0155,
                "speedup": 1.9978,
                "completed": 2,
            },
        ],
    }
    lines = benchmark_module.format_table(report).splitlines()
    table_lines = lines[2:]
    assert table_lines
    assert len({table_display_width(line) for line in table_lines}) == 1
    assert table_lines[0].startswith("并发通道")


def test_profiles_match_contract(benchmark_module) -> None:
    profiles = benchmark_module.PROFILES
    assert set(profiles) == {"quick", "full"}
    assert profiles["quick"]["tasks"] == 2
    assert list(profiles["quick"]["lanes"]) == [1, 2]
    assert profiles["full"]["tasks"] == 4
    assert list(profiles["full"]["lanes"]) == [1, 2, 4]


class FailingEngineHost:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.workers: list[int] = []

    def configure_workers(self, workers: int) -> None:
        self.workers.append(workers)

    def run_batch(self, tasks, on_result, on_progress) -> None:
        for task in tasks:
            on_result(
                {
                    "variant": task["variant"],
                    "seed": task["seed"],
                    "failed": True,
                    "error": "worker exited",
                    "failure_phase": "startup",
                }
            )


def test_zero_completion_raises_benchmark_error(benchmark_module, monkeypatch) -> None:
    monkeypatch.setattr(benchmark_module, "NativeEngineHost", FailingEngineHost)
    with pytest.raises(benchmark_module.BenchmarkError, match="未完成"):
        benchmark_module.run_benchmark("quick", SIMULATOR)


def test_main_reports_value_error_without_traceback(benchmark_module, monkeypatch, capsys) -> None:
    def boom(mode: str, simulator: object) -> dict[str, object]:
        raise ValueError("完成场数必须为正数")

    monkeypatch.setattr(benchmark_module, "run_benchmark", boom)
    assert benchmark_module.main(["--quick", "--json"]) == 1
    captured = capsys.readouterr()
    assert "完成场数必须为正数" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_broken_simulator_exits_with_chinese_reason(tmp_path: Path) -> None:
    simulator = tmp_path / "broken.py"
    simulator.write_text(
        "import json, sys\n"
        'CAPABILITIES = {"protocol": 2, "max_jobs": 1000000, "execution_context_reset": True,\n'
        '                "per_match_resource_release": True}\n'
        'if "--worker-capabilities" in sys.argv:\n'
        "    print(json.dumps(CAPABILITIES))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    completed, _ = run_script("--quick", "--json", "--simulator", str(simulator))
    assert completed.returncode != 0
    assert "基准失败" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "Traceback" not in completed.stdout


def test_performance_document_documents_concurrency_section() -> None:
    document = DOCUMENT.read_text(encoding="utf-8")
    assert "## 并发通道对比" in document
    assert "fake simulator" in document
    assert "workers" in document
    assert ".venv/bin/python scripts/concurrency_benchmark.py --quick --json" in document
    assert ".venv/bin/python scripts/concurrency_benchmark.py --full --json" in document
    assert "单次运行存在波动" in document
    assert document.endswith("\n")
    assert not document.endswith("\n\n")
