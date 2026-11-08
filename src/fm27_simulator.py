"""Batch driver for the original native match host; no replacement football model."""
from __future__ import annotations

import os
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(os.environ["FM27_ENGINE_ROOT"])
BUNDLE = ROOT / "fm27_native"


def uint32(value: str) -> int:
    result = int(value)
    if not 0 <= result <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("seed must be a uint32")
    return result


def inspect_log(path: Path, rows=None) -> dict:
    if rows is None:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def one(event: str) -> dict:
        matches = [r for r in rows if r.get("event") == event]
        if len(matches) != 1:
            raise ValueError(f"expected one {event}, found {len(matches)}")
        return matches[0]

    if not one("simulator_started")["isolated_desktop"]:
        raise ValueError("private desktop not established")
    if not one("runtime_dependencies_checked")["fm_exe_unity_player_game_assembly_absent"]:
        raise ValueError("unexpected game runtime dependency")
    one("native_activation_completed")
    if one("host_icu_data_initialized")["status"] > 0:
        raise ValueError("ICU data initialization failed")
    if not one("native_engine_bootstrap_returned")["accepted"]:
        raise ValueError("original engine bootstrap failed")
    models = one("native_xg_models_parsed")
    if not models["version_groups"] or not models["model_records"]:
        raise ValueError("empty native xG models")
    if not one("native_recording_stream_opened")["success"]:
        raise ValueError("native recording reader could not open input")
    if not one("native_fixture_deserialized")["accepted"]:
        raise ValueError("original recording parser rejected input")
    if one("native_fixture_deserialized").get("input_adapter") != "original_native":
        raise ValueError("input was not read through the original native reader")
    if one("native_score_before_simulation")["score"] != [0, 0]:
        raise ValueError("input already has a nonzero starting score")
    if one("native_preparation_returned")["gates"] != [1, 1, 1]:
        raise ValueError("original preparation did not become ready")
    finish = one("natural_match_finished")
    if not finish["full_match_completed"] or finish["tick"] >= 47996:
        raise ValueError("natural completion/watchdog boundary check failed")
    return {
        "seed": one("native_input_seed"),
        "result": finish,
        "xg_models": models,
        "score_changes": [r for r in rows if r.get("event") == "observed_score_change"],
        "parser": one("native_fixture_deserialized"),
        "raw_log": str(path.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=BUNDLE / "fixtures/match.pkm")
    parser.add_argument("--seeds", nargs="+", type=uint32,
                        help="omit to retain the input recording's original seed")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--tick-step", type=int, default=1, choices=range(1, 257), metavar="1..256")
    parser.add_argument("--inspect", type=Path, help="validate an existing final-host log without launching anything")
    parser.add_argument("--scenario", type=Path, help="exported tactics editor JSON (bundled PKM only)")
    parser.add_argument("--workers", type=int, default=1, choices=range(1,9), help="parallel isolated native hosts (default: serial baseline)")
    args = parser.parse_args()
    if args.inspect:
        print(json.dumps(inspect_log(args.inspect), ensure_ascii=False, indent=2))
        return 0
    executable = BUNDLE / "FM27Simulator.exe"
    fixture = args.fixture.resolve()
    if not executable.is_file() or not fixture.is_file():
        parser.error("host executable or input fixture missing")
    output = (args.output_dir or BUNDLE / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "summary.json"
    if summary_path.exists():
        parser.error("output directory already contains a summary; use a new directory")
    scenario_path = None
    scenario_hash = None
    if args.scenario:
        try:
            if hashlib.sha256(fixture.read_bytes()).digest() != hashlib.sha256((BUNDLE / "fixtures/match.pkm").read_bytes()).digest():
                parser.error("--scenario supports only the bundled PKM input")
            from fm27_tactics_server import encode_scenario, validate_scenario
            scenario = validate_scenario(json.loads(args.scenario.read_text(encoding="utf-8-sig")))
            scenario_path = output / "scenario.bin"
            scenario_path.write_bytes(encode_scenario(scenario))
            (output / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")
            scenario_hash = hashlib.sha256(scenario_path.read_bytes()).hexdigest()
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(f"invalid scenario: {error}")
    summary = {
        "runtime": "native_library_host",
        "extracted_engine": False,
        "original_dll_required": True,
        "football_algorithms_reimplemented": False,
        "fixture": str(fixture),
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "tick_step": args.tick_step,
        "scenario_sha256": scenario_hash,
        "runs": [],
    }
    try:
        from fm27_batch import BatchRunner,worker_limits
        if args.workers>worker_limits()['maximum']:raise ValueError('worker count exceeds current CPU/memory limit')
        summary['workers']=args.workers;summary['failures']=[]
        tasks=[]
        for index,seed in enumerate(args.seeds or [None]):
            label='fixture'if seed is None else str(seed);log=output/f'{index:04d}_seed_{label}.jsonl'
            if log.exists():raise ValueError(f'refusing to overwrite {log}')
            tasks.append({'key':str(index),'variant':'B','seed':seed,'config':scenario_path,'path':log,'fixture':fixture,'tick_step':args.tick_step})
        def completed(result):
            if result.get('failed'):
                summary['failures'].append(result);return
            run=inspect_log(output/result['log']);run['elapsed_seconds']=result['elapsed_seconds'];run['timings']=result['timings'];run['attempts']=result['attempts'];summary['runs'].append(run)
            summary['runs'].sort(key=lambda r:r['seed']['effective_seed'])
            temporary=summary_path.with_suffix('.tmp');temporary.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(summary_path)
            print(f"seed={run['seed']['effective_seed']} score={run['result']['score']} seconds={run['elapsed_seconds']}",flush=True)
        started=time.perf_counter();BatchRunner(ROOT,args.workers).run(tasks,completed);summary['wall_seconds']=round(time.perf_counter()-started,3)
        if summary['failures']:summary['error']=f"{len(summary['failures'])} matches failed after retry"
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        summary["error"] = str(error)
    finally:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)
    if "error" in summary:
        print(summary["error"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
