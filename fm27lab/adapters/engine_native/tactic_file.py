"""真实 FM 战术文件（AFE 归档）读取与原生宿主调用。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AFE_PREFIXES = (b"\x02\x01afe.", b"\x02\x01fmf.")
FMFV2_MAGIC = b"FMFV2"
MAX_TACTIC_BYTES = 4 * 1024 * 1024
HOST_RELATIVE = Path("fm27_native") / "FM27Simulator.exe"
DEFAULT_TIMEOUT_SECONDS = 120.0
DECODED_EVENT = "native_fmf_decoded"
PARSED_EVENT = "native_tactic_file_parsed"
COMPATIBILITY_EVENT = "native_engine_compatibility"
INCOMPATIBLE_EXIT_CODE = 99
ENVIRONMENT_PREFIX = "FM27_"
IMPORT_FMF_ENVIRONMENT = "FM27_IMPORT_FMF"
IMPORT_TAC_ENVIRONMENT = "FM27_IMPORT_TAC"
GAME_ROOT_ENVIRONMENT = "FM27_GAME_ROOT"
ENGINE_ROOT_ENVIRONMENT = "FM27_ENGINE_ROOT"
FILE_MISSING_ERROR = "战术文件不存在"
SIZE_ERROR = "FMF 文件超过 4 MiB 上限"
NOT_ARCHIVE_ERROR = "文件不是 FM 战术归档"
PARSE_ERROR = "游戏引擎无法解析该战术文件"
UNCONFIGURED_ERROR = "未配置游戏与引擎目录，无法解析 FM 战术文件"
INVALID_RECORD_ERROR = f"{PARSE_ERROR}：解析记录字段无效"
INCOMPATIBLE_ERROR = "引擎与当前游戏版本不一致，请在设置页重新导入与游戏匹配的引擎资源"
TRAILING_ZERO_BYTES = 8
STREAM_MIN_BYTES = 8
STREAM_PROBE_BYTES = 1024 * 1024
STREAM_ERROR = "存档战术未通过原版完整回读，不使用猜测指令"
PHASE_COUNT = 2
SLOTS = 11

_HOST_LOCK = threading.Lock()

__all__ = [
    "AFE_PREFIXES",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENGINE_ROOT_ENVIRONMENT",
    "FMFV2_MAGIC",
    "GAME_ROOT_ENVIRONMENT",
    "HOST_RELATIVE",
    "IMPORT_FMF_ENVIRONMENT",
    "IMPORT_TAC_ENVIRONMENT",
    "INCOMPATIBLE_ERROR",
    "MAX_TACTIC_BYTES",
    "STREAM_ERROR",
    "STREAM_MIN_BYTES",
    "STREAM_PROBE_BYTES",
    "TacticCell",
    "TacticFileError",
    "TacticPlan",
    "execute_host",
    "is_afe_archive",
    "parse_tactic_stream",
    "read_tactic_file",
]


class TacticFileError(ValueError):
    """真实战术文件无法读取或无法解析。"""


@dataclass(frozen=True, slots=True)
class TacticCell:
    position: int
    role_flags: int
    pi_flags: int
    target_player: int
    target_position: int


@dataclass(frozen=True, slots=True)
class TacticPlan:
    name: str
    mentality: int
    team_bits: int
    mapping: tuple[int, ...]
    phases: tuple[tuple[TacticCell, ...], ...]


@dataclass(frozen=True, slots=True)
class HostRun:
    """一次原生宿主调用的原始结果。"""

    returncode: int
    events: list[dict[str, Any]]
    text: str


def is_afe_archive(payload: bytes) -> bool:
    return any(payload.startswith(prefix) for prefix in AFE_PREFIXES)


def read_tactic_file(
    path: Path,
    *,
    engine_root: Path | None = None,
    game_root: Path | None = None,
    executable: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> TacticPlan:
    payload_path = Path(path)
    _file_payload(payload_path)
    run = execute_host(
        engine_root=engine_root,
        game_root=game_root,
        executable=executable,
        timeout_seconds=timeout_seconds,
        environment={IMPORT_FMF_ENVIRONMENT: str(payload_path)},
    )
    decoded = _last_event(run.events, DECODED_EVENT)
    parsed = _last_event(run.events, PARSED_EVENT)
    return _tactic_plan(payload_path, decoded, parsed, run.returncode)


def parse_tactic_stream(
    payload: bytes,
    *,
    name: str,
    engine_root: Path | None = None,
    game_root: Path | None = None,
    executable: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    runner: Callable[..., HostRun] | None = None,
) -> TacticPlan:
    """两段式解析存档战术流：先探测原版读入的精确前缀，再在主读入范围内完整回读。"""
    run_host = execute_host if runner is None else runner
    data = bytes(payload)
    if len(data) < STREAM_MIN_BYTES:
        raise TacticFileError(f"{PARSE_ERROR}：战术流大小无效")
    probe = data[:STREAM_PROBE_BYTES]
    kwargs = {
        "engine_root": engine_root,
        "game_root": game_root,
        "executable": executable,
        "timeout_seconds": timeout_seconds,
    }
    run = _stream_run(run_host, probe, kwargs)
    parsed = _last_event(run.events, PARSED_EVENT)
    if len(probe) == len(data) and _stream_complete(parsed, run.returncode, len(data)):
        return _stream_plan(name, parsed)
    consumed = _stream_consumed(parsed)
    if not 0 < consumed <= len(probe):
        raise TacticFileError(STREAM_ERROR)
    exact = data[:consumed]
    second = _stream_run(run_host, exact, kwargs)
    parsed_exact = _last_event(second.events, PARSED_EVENT)
    if not _stream_complete(parsed_exact, second.returncode, len(exact)):
        raise TacticFileError(STREAM_ERROR)
    return _stream_plan(name, parsed_exact)


def _stream_run(
    runner: Callable[..., HostRun],
    payload: bytes,
    kwargs: Mapping[str, Any],
) -> HostRun:
    with tempfile.TemporaryDirectory(prefix="fm27lab-tac-") as directory:
        path = Path(directory) / "tactic_stream.tac"
        path.write_bytes(payload)
        return runner(environment={IMPORT_TAC_ENVIRONMENT: str(path)}, **kwargs)


def _stream_complete(parsed: Mapping[str, Any] | None, returncode: int, expected: int) -> bool:
    if parsed is None or parsed.get("accepted") is not True:
        return False
    if _stream_value(parsed, "stream_error") != 0:
        return False
    if _stream_value(parsed, "size") != expected:
        return False
    consumed = _stream_consumed(parsed)
    if consumed not in (expected, expected - TRAILING_ZERO_BYTES):
        return False
    return returncode == 0


def _stream_consumed(parsed: Mapping[str, Any] | None) -> int:
    return _stream_value(parsed, "consumed")


def _stream_value(parsed: Mapping[str, Any] | None, key: str) -> int:
    if parsed is None:
        return -1
    value = parsed.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return -1
    if isinstance(value, str) and not value.isdigit():
        return -1
    return int(value)


def _stream_plan(name: str, parsed: Mapping[str, Any]) -> TacticPlan:
    return TacticPlan(
        name=name,
        mentality=_as_int(parsed.get("mentality")),
        team_bits=_team_bits(parsed.get("team_bits")),
        mapping=_mapping(parsed.get("mapping")),
        phases=_phases(parsed.get("phases")),
    )


def execute_host(
    *,
    engine_root: Path | None,
    game_root: Path | None,
    executable: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    arguments: Sequence[str] = (),
) -> HostRun:
    """串行执行原生宿主进程，合并输出文件与标准输出后解析 JSON 事件。"""
    engine, game, host = _resolve_host(engine_root, game_root, executable)
    host_environment = _host_environment(engine, game, environment)
    items = [str(item) for item in arguments]
    explicit_output = _output_argument(items)
    with _HOST_LOCK, tempfile.TemporaryDirectory(prefix="fm27lab-fmf-") as directory:
        if explicit_output is None:
            output = Path(directory) / "tactic.jsonl"
            command = [*_executable_prefix(host), *items, "--output", str(output)]
        else:
            output = explicit_output if explicit_output.is_absolute() else engine / explicit_output
            command = [*_executable_prefix(host), *items]
        try:
            completed = subprocess.run(
                command,
                cwd=str(engine),
                env=host_environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                creationflags=_creation_flags(),
            )
        except subprocess.TimeoutExpired as error:
            raise TacticFileError(f"引擎解析超时：{timeout_seconds:g} 秒内未返回") from error
        except OSError as error:
            if os.name != "nt":
                raise TacticFileError(f"当前平台不支持原生引擎：{error}") from error
            raise TacticFileError(f"无法启动原生宿主：{error}") from error
        text = _read_output(output) + "\n" + (completed.stdout or "")
    run = HostRun(returncode=completed.returncode, events=_json_events(text), text=text)
    _ensure_compatible(run)
    return run


def _host_environment(
    engine: Path,
    game: Path,
    overrides: Mapping[str, str] | None,
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith(ENVIRONMENT_PREFIX)
    }
    environment[GAME_ROOT_ENVIRONMENT] = str(game)
    environment[ENGINE_ROOT_ENVIRONMENT] = str(engine)
    if overrides:
        environment.update({str(key): str(value) for key, value in overrides.items()})
    return environment


def _output_argument(arguments: Sequence[str]) -> Path | None:
    for index, argument in enumerate(arguments):
        if argument == "--output" and index + 1 < len(arguments):
            return Path(arguments[index + 1])
        if argument.startswith("--output="):
            return Path(argument.partition("=")[2])
    return None


def _ensure_compatible(run: HostRun) -> None:
    if run.returncode == INCOMPATIBLE_EXIT_CODE:
        raise TacticFileError(INCOMPATIBLE_ERROR)
    compatibility = _last_event(run.events, COMPATIBILITY_EVENT)
    if compatibility is not None and compatibility.get("compatible") is False:
        raise TacticFileError(INCOMPATIBLE_ERROR)


def _file_payload(path: Path) -> None:
    if not path.is_file():
        raise TacticFileError(FILE_MISSING_ERROR)
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise TacticFileError(f"战术文件无法读取：{error}") from error
    if len(payload) > MAX_TACTIC_BYTES:
        raise TacticFileError(SIZE_ERROR)
    if not is_afe_archive(payload):
        raise TacticFileError(NOT_ARCHIVE_ERROR)


def _resolve_host(
    engine_root: Path | None,
    game_root: Path | None,
    executable: Path | None,
) -> tuple[Path, Path, Path]:
    if engine_root is None or game_root is None:
        raise TacticFileError(UNCONFIGURED_ERROR)
    engine = Path(engine_root)
    game = Path(game_root)
    if not engine.is_dir():
        raise TacticFileError(f"引擎目录不存在或不是目录：{engine}")
    if not game.is_dir():
        raise TacticFileError(f"游戏目录不存在或不是目录：{game}")
    host = Path(executable) if executable is not None else engine / HOST_RELATIVE
    if not host.is_file():
        raise TacticFileError(f"原生宿主程序不存在：{host}")
    return engine, game, host


def _read_output(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _executable_prefix(host: Path) -> list[str]:
    if host.suffix.lower() == ".py":
        return [sys.executable, str(host)]
    return [str(host)]


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _json_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            event = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == name:
            return event
    return None


def _tactic_plan(
    path: Path,
    decoded: Mapping[str, Any] | None,
    parsed: Mapping[str, Any] | None,
    returncode: int,
) -> TacticPlan:
    if decoded is None:
        raise TacticFileError(_missing_decoded_error(returncode))
    if decoded.get("accepted") is not True:
        raise TacticFileError(NOT_ARCHIVE_ERROR)
    if _as_int(decoded.get("setpiece_type")) >= 0:
        raise TacticFileError(f"{NOT_ARCHIVE_ERROR}：该文件是定位球方案，暂不支持导入")
    if parsed is None:
        raise TacticFileError(_missing_parsed_error(returncode))
    if parsed.get("accepted") is not True:
        raise TacticFileError(f"{PARSE_ERROR}：解析器未接受")
    stream_error = _as_int(parsed.get("stream_error"))
    if stream_error:
        raise TacticFileError(f"{PARSE_ERROR}：解析流错误 {stream_error}")
    size = _as_int(parsed.get("size"))
    consumed = _as_int(parsed.get("consumed"))
    if consumed < 0 or consumed > size or size - consumed not in (0, TRAILING_ZERO_BYTES):
        raise TacticFileError(INVALID_RECORD_ERROR)
    if returncode != 0:
        raise TacticFileError(f"{PARSE_ERROR}：宿主退出码 {returncode}")
    return TacticPlan(
        name=_decoded_name(decoded, path),
        mentality=_as_int(parsed.get("mentality")),
        team_bits=_team_bits(parsed.get("team_bits")),
        mapping=_mapping(parsed.get("mapping")),
        phases=_phases(parsed.get("phases")),
    )


def _missing_decoded_error(returncode: int) -> str:
    if returncode == 171:
        return NOT_ARCHIVE_ERROR
    if returncode == 172:
        return f"{PARSE_ERROR}：战术流大小无效"
    if returncode == 173:
        return f"{PARSE_ERROR}：解析器未接受"
    if returncode != 0:
        return f"{PARSE_ERROR}：宿主退出码 {returncode}"
    return f"{PARSE_ERROR}：宿主未输出解析记录"


def _missing_parsed_error(returncode: int) -> str:
    if returncode == 172:
        return f"{PARSE_ERROR}：战术流大小无效"
    if returncode == 173:
        return f"{PARSE_ERROR}：解析器未接受"
    if returncode != 0:
        return f"{PARSE_ERROR}：宿主退出码 {returncode}"
    return f"{PARSE_ERROR}：宿主未输出解析记录"


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TacticFileError(INVALID_RECORD_ERROR)
    if isinstance(value, str) and not value.isdigit():
        raise TacticFileError(INVALID_RECORD_ERROR)
    return int(value)


def _team_bits(value: object) -> int:
    if not isinstance(value, str):
        raise TacticFileError(INVALID_RECORD_ERROR)
    try:
        return int.from_bytes(bytes.fromhex(value), "little")
    except ValueError as error:
        raise TacticFileError(INVALID_RECORD_ERROR) from error


def _mapping(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != SLOTS:
        raise TacticFileError(INVALID_RECORD_ERROR)
    return tuple(_as_int(item) for item in value)


def _phases(value: object) -> tuple[tuple[TacticCell, ...], ...]:
    if not isinstance(value, list) or len(value) != PHASE_COUNT:
        raise TacticFileError(INVALID_RECORD_ERROR)
    phases: list[tuple[TacticCell, ...]] = []
    for raw_phase in value:
        if not isinstance(raw_phase, list) or len(raw_phase) != SLOTS:
            raise TacticFileError(INVALID_RECORD_ERROR)
        cells: list[TacticCell] = []
        for raw_cell in raw_phase:
            if not isinstance(raw_cell, Mapping):
                raise TacticFileError(INVALID_RECORD_ERROR)
            cells.append(
                TacticCell(
                    position=_as_int(raw_cell.get("position")),
                    role_flags=_as_int(raw_cell.get("role_flags")),
                    pi_flags=_as_int(raw_cell.get("pi_flags")),
                    target_player=_as_int(raw_cell.get("target_player")),
                    target_position=_as_int(raw_cell.get("target_position")),
                )
            )
        phases.append(tuple(cells))
    return tuple(phases)


def _decoded_name(decoded: Mapping[str, Any], path: Path) -> str:
    raw = decoded.get("name_utf8_hex")
    if isinstance(raw, str):
        try:
            name = bytes.fromhex(raw).decode("utf-8").strip()
        except ValueError:
            name = ""
        if name:
            return name
    return path.stem.strip()
