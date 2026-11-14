"""并发通道对比基准，量化 NativeEngineHost 多通道对墙钟时间的影响。"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import sys
import tempfile
import time
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fm27lab import __version__ as SOURCE_VERSION  # noqa: E402
from fm27lab.adapters.engine_native.host import NativeEngineHost  # noqa: E402

OUTPUT_VERSION = "1"
MATCH_SECONDS = 2.0
TIMEOUT_SECONDS = 120
BASELINE_WORKERS = 1
DEFAULT_SIMULATOR = ROOT / "fm27lab" / "tests" / "fixtures" / "fake_simulator.py"
PROFILES: dict[str, dict[str, Any]] = {
    "quick": {"tasks": 2, "lanes": [1, 2]},
    "full": {"tasks": 4, "lanes": [1, 2, 4]},
}


class BenchmarkError(RuntimeError):
    """基准无法产生有效结论时抛出的错误。"""


def package_version() -> str:
    try:
        return importlib.metadata.version("fm27lab")
    except importlib.metadata.PackageNotFoundError:
        return SOURCE_VERSION


def compute_speedup(baseline_seconds: float | None, seconds: float | None) -> float:
    if baseline_seconds is None or baseline_seconds <= 0:
        raise ValueError("基准耗时缺失或非正数，无法计算加速比")
    if seconds is None or seconds <= 0:
        raise ValueError("本次耗时必须为正数")
    return round(baseline_seconds / seconds, 4)


def compute_seconds_per_match(seconds: float, completed: int) -> float:
    if completed <= 0:
        raise ValueError("完成场数必须为正数")
    return round(seconds / completed, 4)


def summarize(measurements: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    baseline = next(
        (item for item in measurements if item["workers"] == BASELINE_WORKERS),
        None,
    )
    if baseline is None:
        raise ValueError("缺少 workers=1 的基准测量")
    return [
        {
            "workers": item["workers"],
            "tasks": item["tasks"],
            "seconds": round(item["seconds"], 4),
            "seconds_per_match": compute_seconds_per_match(item["seconds"], item["completed"]),
            "speedup": compute_speedup(baseline["seconds"], item["seconds"]),
            "completed": item["completed"],
        }
        for item in measurements
    ]


def ensure_complete(results: Sequence[Mapping[str, Any]], tasks: int) -> None:
    if len(results) < 2:
        raise BenchmarkError("至少需要两档 workers 的测量结果")
    for result in results:
        if result["completed"] != tasks:
            raise BenchmarkError(
                f"批次未完成：workers={result['workers']} 仅完成 {result['completed']}/{tasks} 场"
            )


def resolve_simulator(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise BenchmarkError(f"模拟器文件不存在：{path}")
    if path.suffix.lower() == ".py":
        if not os.access(path, os.R_OK):
            raise BenchmarkError(f"模拟器脚本不可读：{path}")
    elif not os.access(path, os.X_OK):
        raise BenchmarkError(f"模拟器文件不可执行：{path}")
    return path


def _noop_progress(_descriptors: object) -> None:
    return None


def run_benchmark(mode: str, simulator: str | Path) -> dict[str, Any]:
    profile = PROFILES[mode]
    executable = resolve_simulator(simulator)
    tasks_count = profile["tasks"]
    measurements: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="fm27lab-concurrency-",
        ignore_cleanup_errors=True,
    ) as directory:
        base = Path(directory)
        root = base / "engine"
        work = base / "work"
        fixtures = root / "fixtures"
        fixtures.mkdir(parents=True)
        work.mkdir(parents=True)
        fixture = fixtures / "slow.pkm"
        fixture.write_bytes(b"fake fixture")
        host = NativeEngineHost(
            root,
            work,
            executable=executable,
            retries=0,
            timeout_seconds=TIMEOUT_SECONDS,
        )
        tasks = [
            {"variant": "A", "seed": seed, "fixture": str(fixture)}
            for seed in range(tasks_count)
        ]
        for lanes in profile["lanes"]:
            host.configure_workers(lanes)
            outcomes: list[Mapping[str, Any]] = []
            started = time.perf_counter()
            host.run_batch(tasks, outcomes.append, _noop_progress)
            elapsed = time.perf_counter() - started
            completed = sum(1 for outcome in outcomes if outcome.get("failed") is not True)
            measurements.append(
                {
                    "workers": lanes,
                    "tasks": tasks_count,
                    "seconds": elapsed,
                    "completed": completed,
                }
            )
    ensure_complete(measurements, tasks_count)
    results = summarize(measurements)
    return {
        "version": package_version(),
        "mode": mode,
        "environment": {
            "cpu_count": os.cpu_count() or 0,
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "params": {
            "tasks": tasks_count,
            "lanes": list(profile["lanes"]),
            "match_seconds": MATCH_SECONDS,
            "simulator": str(executable),
        },
        "results": results,
    }


def _cell_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _pad_cell(text: str, width: int, align: str) -> str:
    padding = " " * max(width - _cell_width(text), 0)
    return padding + text if align == "right" else text + padding


def format_table(report: Mapping[str, Any]) -> str:
    params = report["params"]
    title = (
        f"并发通道对比 模式={report['mode']} 场数={params['tasks']}"
        f" 每场基准={params['match_seconds']:.1f}s 模拟器={params['simulator']}"
    )
    headers = ("并发通道", "场数", "墙钟秒", "每场秒", "加速比", "完成")
    aligns = ("left", "right", "right", "right", "right", "right")
    rows = [
        (
            str(result["workers"]),
            str(result["tasks"]),
            f"{result['seconds']:.4f}",
            f"{result['seconds_per_match']:.4f}",
            f"{result['speedup']:.4f}",
            str(result["completed"]),
        )
        for result in report["results"]
    ]
    widths = [
        max(_cell_width(cells[column]) for cells in (headers, *rows))
        for column in range(len(headers))
    ]

    def render(cells: tuple[str, ...]) -> str:
        return "  ".join(
            _pad_cell(cell, widths[index], aligns[index]) for index, cell in enumerate(cells)
        )

    header_line = render(headers)
    lines = [title, "", header_line, "-" * _cell_width(header_line)]
    lines.extend(render(row) for row in rows)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="并发通道对比基准")
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--quick", action="store_true", help="快速档位：2 场，通道 1 与 2")
    profiles.add_argument("--full", action="store_true", help="完整档位：4 场，通道 1、2 与 4")
    parser.add_argument("--json", dest="as_json", action="store_true", help="输出 JSON 报告")
    parser.add_argument(
        "--simulator",
        default=str(DEFAULT_SIMULATOR),
        help="模拟器脚本或引擎可执行文件",
    )
    arguments = parser.parse_args(argv)
    mode = "full" if arguments.full else "quick"
    try:
        report = run_benchmark(mode, arguments.simulator)
    except (BenchmarkError, ValueError, RuntimeError) as error:
        print(f"基准失败：{error}", file=sys.stderr)
        return 1
    if arguments.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
