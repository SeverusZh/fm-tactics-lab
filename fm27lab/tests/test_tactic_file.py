"""真实 FMF 战术文件读取契约测试。"""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from fm27lab.adapters.engine_native.tactic_file import (
    AFE_PREFIXES,
    DEFAULT_TIMEOUT_SECONDS,
    INCOMPATIBLE_ERROR,
    INVALID_RECORD_ERROR,
    MAX_TACTIC_BYTES,
    TRAILING_ZERO_BYTES,
    TacticCell,
    TacticFileError,
    execute_host,
    is_afe_archive,
    read_tactic_file,
)

PAYLOAD_PREFIX = AFE_PREFIXES[0]
NAME = "主场战术"
SPEC_VARIABLE = "TACTIC_HOST_TEST_SPEC"

HOST_SOURCE = '''\
import json
import os
import sys
import time

with open(os.environ["TACTIC_HOST_TEST_SPEC"], encoding="utf-8") as handle:
    spec = json.load(handle)
capture = spec.get("capture")
if capture:
    with open(capture, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "argv": sys.argv[1:],
                "cwd": os.getcwd(),
                "fmf": os.environ.get("FM27_IMPORT_FMF"),
                "game": os.environ.get("FM27_GAME_ROOT"),
                "engine": os.environ.get("FM27_ENGINE_ROOT"),
                "fm27": {
                    key: value
                    for key, value in os.environ.items()
                    if key.startswith("FM27_")
                },
            },
            handle,
            ensure_ascii=False,
        )
trace = spec.get("trace")
if trace:
    with open(trace, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"phase": "start", "pid": os.getpid()}) + chr(10))
time.sleep(spec.get("sleep", 0))
lines = [json.dumps(event, ensure_ascii=False) for event in spec.get("events", [])]
output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else ""
if spec.get("stdout") or not output:
    for line in lines:
        print(line)
else:
    with open(output, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + chr(10))
if trace:
    with open(trace, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"phase": "end", "pid": os.getpid()}) + chr(10))
sys.exit(spec.get("exit", 0))
'''


def prepare(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    engine = tmp_path / "engine"
    native = engine / "fm27_native"
    native.mkdir(parents=True)
    host = native / "host.py"
    host.write_text(HOST_SOURCE, encoding="utf-8")
    game = tmp_path / "game"
    game.mkdir()
    payload = tmp_path / f"{NAME}.fmf"
    payload.write_bytes(PAYLOAD_PREFIX + b"native-payload-bytes")
    return engine, game, host, payload


def write_spec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    events: list[dict],
    *,
    exit_code: int = 0,
    sleep: float = 0.0,
    capture: Path | None = None,
    stdout: bool = False,
    trace: Path | None = None,
) -> None:
    spec = {
        "events": events,
        "exit": exit_code,
        "sleep": sleep,
        "capture": str(capture) if capture is not None else None,
        "stdout": stdout,
        "trace": str(trace) if trace is not None else None,
    }
    path = tmp_path / "host-spec.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv(SPEC_VARIABLE, str(path))


def install_native_host(engine_root: Path) -> Path:
    host = engine_root / "fm27_native" / "FM27Simulator.exe"
    host.write_text("#!" + sys.executable + "\n" + HOST_SOURCE, encoding="utf-8")
    host.chmod(0o755)
    return host


def read(
    engine: Path,
    game: Path,
    payload: Path,
    host: Path | None,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
):
    return read_tactic_file(
        payload,
        engine_root=engine,
        game_root=game,
        executable=host,
        timeout_seconds=timeout_seconds,
    )


def decoded_event(**overrides) -> dict:
    event = {
        "event": "native_fmf_decoded",
        "accepted": True,
        "bytes": 64,
        "name_utf8_hex": NAME.encode("utf-8").hex(),
        "setpiece_type": -1,
        "stream_revision": 60,
    }
    event.update(overrides)
    return event


def cell_event(**overrides) -> dict:
    event = {
        "position": 1,
        "role_flags": "256",
        "pi_flags": "0",
        "target_player": 255,
        "target_position": 0,
    }
    event.update(overrides)
    return event


def parsed_event(**overrides) -> dict:
    event = {
        "event": "native_tactic_file_parsed",
        "accepted": True,
        "stream_error": 0,
        "consumed": 64,
        "size": 64,
        "mentality": 4,
        "team_bits": bytes(range(16)).hex(),
        "mapping": list(range(11)),
        "phases": [[cell_event() for _ in range(11)] for _ in range(2)],
    }
    event.update(overrides)
    return event


def test_is_afe_archive_recognises_archive_headers():
    assert is_afe_archive(b"\x02\x01afe." + b"body")
    assert is_afe_archive(b"\x02\x01fmf." + b"body")
    assert not is_afe_archive(b"FMFV2")
    assert not is_afe_archive(b"")


def test_read_tactic_file_maps_native_host_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, payload = prepare(tmp_path)
    capture = tmp_path / "capture.json"
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event()], capture=capture)
    plan = read(engine, game, payload, host)
    assert plan.name == NAME
    assert plan.mentality == 4
    assert plan.team_bits == int.from_bytes(bytes(range(16)), "little")
    assert plan.mapping == tuple(range(11))
    assert plan.phases[0][0] == TacticCell(
        position=1,
        role_flags=256,
        pi_flags=0,
        target_player=255,
        target_position=0,
    )
    assert len(plan.phases) == 2
    assert all(len(phase) == 11 for phase in plan.phases)
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    assert recorded["fmf"] == str(payload)
    assert recorded["game"] == str(game)
    assert recorded["engine"] == str(engine)
    assert recorded["cwd"] == str(engine)
    assert recorded["argv"][0] == "--output"
    assert Path(recorded["argv"][1]).name == "tactic.jsonl"


def test_read_tactic_file_strips_inherited_fm27_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    engine, game, host, payload = prepare(tmp_path)
    capture = tmp_path / "capture.json"
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event()], capture=capture)
    monkeypatch.setenv("FM27_IMPORT_TAC", str(tmp_path / "foreign.tac"))
    monkeypatch.setenv("FM27_DESKTOP_STATS_AUDIT", "1")
    monkeypatch.setenv("FM27_EXPORT_TAC", str(tmp_path / "export.tac"))
    assert read(engine, game, payload, host).name == NAME
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    assert recorded["fm27"] == {
        "FM27_GAME_ROOT": str(game),
        "FM27_ENGINE_ROOT": str(engine),
        "FM27_IMPORT_FMF": str(payload),
    }


def test_read_tactic_file_accepts_fmf_archive_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, payload = prepare(tmp_path)
    payload.write_bytes(AFE_PREFIXES[1] + b"native-payload-bytes")
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event()])
    assert read(engine, game, payload, host).name == NAME


def test_read_tactic_file_falls_back_to_file_stem_for_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    engine, game, host, payload = prepare(tmp_path)
    for raw in ("", "zz", b"\xff\xfe".hex(), b"   ".hex(), 5):
        write_spec(monkeypatch, tmp_path, [decoded_event(name_utf8_hex=raw), parsed_event()])
        assert read(engine, game, payload, host).name == NAME, raw


def test_read_tactic_file_reads_events_from_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, payload = prepare(tmp_path)
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event()], stdout=True)
    assert read(engine, game, payload, host).name == NAME


def test_read_tactic_file_rejects_missing_file(tmp_path: Path):
    engine, game, host, _ = prepare(tmp_path)
    missing = tmp_path / "missing.fmf"
    with pytest.raises(TacticFileError, match="战术文件不存在"):
        read(engine, game, missing, host)


def test_read_tactic_file_rejects_oversized_file(tmp_path: Path):
    engine, game, host, payload = prepare(tmp_path)
    payload.write_bytes(PAYLOAD_PREFIX + b"\x00" * MAX_TACTIC_BYTES)
    with pytest.raises(TacticFileError, match="FMF 文件超过 4 MiB 上限"):
        read(engine, game, payload, host)


def test_read_tactic_file_rejects_non_archive_header(tmp_path: Path):
    engine, game, host, payload = prepare(tmp_path)
    payload.write_bytes(b"not a native fmf archive")
    with pytest.raises(TacticFileError, match="文件不是 FM 战术归档"):
        read(engine, game, payload, host)


def test_read_tactic_file_reports_unreadable_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, payload = prepare(tmp_path)

    def deny(_self: Path) -> bytes:
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(Path, "read_bytes", deny)
    with pytest.raises(TacticFileError, match="战术文件无法读取：拒绝访问"):
        read(engine, game, payload, host)


def test_read_tactic_file_requires_engine_and_game_configuration(tmp_path: Path):
    _, _, _, payload = prepare(tmp_path)
    with pytest.raises(TacticFileError, match="未配置游戏与引擎目录"):
        read_tactic_file(payload)
    with pytest.raises(TacticFileError, match="未配置游戏与引擎目录"):
        read_tactic_file(payload, engine_root=tmp_path / "engine", game_root=None)


def test_read_tactic_file_requires_existing_roots_and_host(tmp_path: Path):
    engine, game, host, payload = prepare(tmp_path)
    with pytest.raises(TacticFileError, match="引擎目录不存在或不是目录"):
        read(tmp_path / "missing-engine", game, payload, host)
    with pytest.raises(TacticFileError, match="游戏目录不存在或不是目录"):
        read(engine, tmp_path / "missing-game", payload, host)
    with pytest.raises(TacticFileError, match="原生宿主程序不存在"):
        read(engine, game, payload, None)


def test_read_tactic_file_reports_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, payload = prepare(tmp_path)
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event()], sleep=1.0)
    with pytest.raises(TacticFileError, match="引擎解析超时：0.2 秒内未返回"):
        read(engine, game, payload, host, timeout_seconds=0.2)


def test_read_tactic_file_reports_incompatible_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    engine, game, host, payload = prepare(tmp_path)
    write_spec(monkeypatch, tmp_path, [], exit_code=99)
    with pytest.raises(TacticFileError) as raised:
        read(engine, game, payload, host)
    assert str(raised.value) == INCOMPATIBLE_ERROR
    compatibility = {"event": "native_engine_compatibility", "compatible": False}
    write_spec(monkeypatch, tmp_path, [compatibility, decoded_event(), parsed_event()])
    with pytest.raises(TacticFileError) as raised:
        read(engine, game, payload, host)
    assert str(raised.value) == INCOMPATIBLE_ERROR
    write_spec(
        monkeypatch,
        tmp_path,
        [{**compatibility, "compatible": True}, decoded_event(), parsed_event()],
    )
    assert read(engine, game, payload, host).name == NAME


def test_read_tactic_file_maps_host_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, payload = prepare(tmp_path)
    cases = [
        ([], 171, "文件不是 FM 战术归档"),
        ([], 172, "游戏引擎无法解析该战术文件：战术流大小无效"),
        ([], 173, "游戏引擎无法解析该战术文件：解析器未接受"),
        ([decoded_event()], 173, "游戏引擎无法解析该战术文件：解析器未接受"),
        ([decoded_event()], 1, "游戏引擎无法解析该战术文件：宿主退出码 1"),
        ([], 0, "游戏引擎无法解析该战术文件：宿主未输出解析记录"),
    ]
    for events, exit_code, expected in cases:
        write_spec(monkeypatch, tmp_path, events, exit_code=exit_code)
        with pytest.raises(TacticFileError) as raised:
            read(engine, game, payload, host)
        assert str(raised.value) == expected, (events, exit_code)
    assert DEFAULT_TIMEOUT_SECONDS == 120.0


def test_read_tactic_file_rejects_non_tactic_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, payload = prepare(tmp_path)
    write_spec(monkeypatch, tmp_path, [decoded_event(accepted=False), parsed_event()])
    with pytest.raises(TacticFileError, match="文件不是 FM 战术归档"):
        read(engine, game, payload, host)
    write_spec(monkeypatch, tmp_path, [decoded_event(setpiece_type=3), parsed_event()])
    with pytest.raises(TacticFileError, match="该文件是定位球方案，暂不支持导入"):
        read(engine, game, payload, host)


def test_read_tactic_file_rejects_incomplete_parser_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    engine, game, host, payload = prepare(tmp_path)
    cases = [
        ([decoded_event(), parsed_event(accepted=False)], 173, "解析器未接受"),
        ([decoded_event(), parsed_event(stream_error=7)], 173, "解析流错误 7"),
        ([decoded_event(), parsed_event()], 1, "宿主退出码 1"),
    ]
    for events, exit_code, expected in cases:
        write_spec(monkeypatch, tmp_path, events, exit_code=exit_code)
        with pytest.raises(TacticFileError, match=expected):
            read(engine, game, payload, host)


@pytest.mark.parametrize(
    ("consumed", "size"),
    [
        (64, 64),
        (8, 16),
        (0, 8),
    ],
)
def test_read_tactic_file_accepts_trailing_zero_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumed: int, size: int
):
    engine, game, host, payload = prepare(tmp_path)
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event(consumed=consumed, size=size)])
    assert read(engine, game, payload, host).name == NAME
    assert TRAILING_ZERO_BYTES == 8


@pytest.mark.parametrize(
    ("consumed", "size"),
    [
        (8, 17),
        (9, 16),
        (63, 64),
        (-1, 8),
        (-1, 7),
        (65, 64),
    ],
)
def test_read_tactic_file_rejects_invalid_stream_size_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumed: int, size: int
):
    engine, game, host, payload = prepare(tmp_path)
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event(consumed=consumed, size=size)])
    with pytest.raises(TacticFileError) as raised:
        read(engine, game, payload, host)
    assert str(raised.value) == INVALID_RECORD_ERROR


@pytest.mark.parametrize(
    "overrides",
    [
        {"mapping": list(range(10))},
        {"mapping": list(range(12))},
        {"phases": [[cell_event() for _ in range(11)]]},
        {"phases": [[cell_event() for _ in range(10)], [cell_event() for _ in range(11)]]},
        {"phases": [[{"position": "x"}, *[cell_event() for _ in range(10)]], [cell_event() for _ in range(11)]]},
        {"mentality": "四"},
        {"team_bits": "zz"},
        {"team_bits": 1},
    ],
)
def test_read_tactic_file_rejects_malformed_parser_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict
):
    engine, game, host, payload = prepare(tmp_path)
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event(**overrides)])
    with pytest.raises(TacticFileError) as raised:
        read(engine, game, payload, host)
    assert str(raised.value) == INVALID_RECORD_ERROR


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 无法直接执行脚本型宿主")
def test_read_tactic_file_resolves_default_host_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, _, payload = prepare(tmp_path)
    install_native_host(engine)
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event()])
    assert read(engine, game, payload, None).name == NAME


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 缺少可执行位语义")
def test_read_tactic_file_reports_platform_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    engine, game, _, payload = prepare(tmp_path)
    host = engine / "fm27_native" / "native_host.bin"
    host.write_text(HOST_SOURCE, encoding="utf-8")
    host.chmod(0o644)
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event()])
    with pytest.raises(TacticFileError, match="当前平台不支持原生引擎"):
        read(engine, game, payload, host)


def test_execute_host_returns_events_text_and_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    engine, game, host, payload = prepare(tmp_path)
    capture = tmp_path / "capture.json"
    write_spec(monkeypatch, tmp_path, [decoded_event()], capture=capture)
    run = execute_host(
        engine_root=engine,
        game_root=game,
        executable=host,
        environment={"FM27_IMPORT_FMF": str(payload)},
        arguments=("--scenario-file", str(tmp_path / "plan.json")),
    )
    assert run.returncode == 0
    assert run.events == [decoded_event()]
    assert '"native_fmf_decoded"' in run.text
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    assert recorded["argv"][:2] == ["--scenario-file", str(tmp_path / "plan.json")]
    assert recorded["argv"][2] == "--output"
    assert Path(recorded["argv"][3]).name == "tactic.jsonl"
    assert recorded["fm27"]["FM27_IMPORT_FMF"] == str(payload)


def test_execute_host_injects_explicit_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, _ = prepare(tmp_path)
    capture = tmp_path / "capture.json"
    write_spec(monkeypatch, tmp_path, [decoded_event()], capture=capture)
    monkeypatch.setenv("FM27_IMPORT_TAC", str(tmp_path / "foreign.tac"))
    export = tmp_path / "export.tac"
    execute_host(
        engine_root=engine,
        game_root=game,
        executable=host,
        environment={"FM27_EXPORT_TAC": str(export)},
    )
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    assert recorded["fm27"] == {
        "FM27_GAME_ROOT": str(game),
        "FM27_ENGINE_ROOT": str(engine),
        "FM27_EXPORT_TAC": str(export),
    }


def test_execute_host_honours_caller_output_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, _ = prepare(tmp_path)
    capture = tmp_path / "capture.json"
    write_spec(monkeypatch, tmp_path, [decoded_event(), parsed_event()], capture=capture)
    output = tmp_path / "events.jsonl"
    run = execute_host(
        engine_root=engine,
        game_root=game,
        executable=host,
        arguments=("--output", str(output)),
    )
    assert run.events == [decoded_event(), parsed_event()]
    assert output.is_file()
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    assert recorded["argv"] == ["--output", str(output)]


def test_execute_host_serializes_concurrent_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine, game, host, _ = prepare(tmp_path)
    trace = tmp_path / "trace.jsonl"
    write_spec(monkeypatch, tmp_path, [], sleep=0.5, trace=trace)
    barrier = threading.Barrier(2)

    def invoke():
        barrier.wait(timeout=10)
        return execute_host(engine_root=engine, game_root=game, executable=host)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke), pool.submit(invoke)]
        runs = [future.result(timeout=60) for future in futures]
    assert [run.returncode for run in runs] == [0, 0]
    entries = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert [entry["phase"] for entry in entries] == ["start", "end", "start", "end"]
    assert len({entry["pid"] for entry in entries}) == 2
