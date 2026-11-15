"""从草案场景导出游戏可识别的 FMF v8 战术归档。

游戏宿主负责把场景序列化成 TAC 计划；本模块负责准备导出场景、驱动宿主、打包
归档，并用导入链路回读归档确认四段战术数据与导出场景一致。
"""

from __future__ import annotations

import copy
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from fm27lab.adapters.engine_native.scenario_assets import load_scenario_assets
from fm27lab.adapters.engine_native.scenario_codec import defaults as scenario_defaults
from fm27lab.adapters.engine_native.scenario_codec import encode_scenario
from fm27lab.adapters.engine_native.tactic_file import (
    INCOMPATIBLE_ERROR,
    TacticFileError,
    execute_host,
    read_tactic_file,
)
from fm27lab.adapters.fmf.archive import tactics_archive
from fm27lab.application.engine_config import missing_engine_files, missing_game_files
from fm27lab.application.tactic_import import build_scenario

ROUND_TRIP_KEYS: Final = ("mentality", "instructions", "native_extra_team_bits", "phases")
TITLE_MAX_CHARS: Final = 100
TITLE_FORBIDDEN: Final = '\\/:*?"<>|'
DEFAULT_TITLE: Final = "战术"
HOST_SIDE: Final = 0
EXPORT_TAC_ENVIRONMENT: Final = "FM27_EXPORT_TAC"
EXPORT_SIDE_ENVIRONMENT: Final = "FM27_EXPORT_SIDE"
EXPORT_TITLE_ENVIRONMENT: Final = "FM27_EXPORT_TITLE"
WRITTEN_EVENT: Final = "native_tactic_file_written"
TIMEOUT_PREFIX: Final = "引擎解析超时"
EXPORT_TIMEOUT_SECONDS: Final = 45.0
SCENARIO_FILE_NAME: Final = "scenario.bin"
PLAN_FILE_NAME: Final = "tactic.tac"
LOG_FILE_NAME: Final = "export.jsonl"
ARCHIVE_FILE_NAME: Final = "export.fmf"

UNCONFIGURED_ERROR = "未配置引擎与游戏目录，无法导出游戏可识别的战术文件；请在设置页导入引擎资源并配置游戏目录"
INCOMPLETE_ERROR = "引擎资源不完整，无法导出游戏可识别的战术文件；缺少：{files}"
SCENARIO_ERROR = "草案场景缺少主队战术数据"
EXPORT_FAILED_ERROR = "原版战术序列化失败，未导出"
WRITE_MISSING_ERROR = "原版战术序列化失败，未生成导出文件"
EXPORT_TIMEOUT_ERROR = "原版战术写入超时，未生成导出文件"
ROUND_TRIP_ERROR = "导出结果未通过回读校验"
LOCAL_PATH_ERROR = "导出临时路径必须是本地路径：{path}"


class TacticExportError(ValueError):
    """导出失败，消息可直接展示给用户。"""


class EngineUnavailableError(TacticExportError):
    """引擎或游戏目录不可用：未配置、资源不完整或版本不兼容。"""


class TacticExporter:
    """把草案主队战术导出成 FMF v8 归档字节。"""

    def __init__(
        self,
        *,
        assets_loader: Any = load_scenario_assets,
        runner: Any = execute_host,
        reader: Any = read_tactic_file,
    ) -> None:
        self._assets_loader = assets_loader
        self._runner = runner
        self._reader = reader

    def export(
        self,
        *,
        name: str,
        scenario: Mapping[str, Any],
        engine_root: Path | None,
        game_root: Path | None,
        executable: str | Path | None = None,
        timeout_seconds: float = EXPORT_TIMEOUT_SECONDS,
    ) -> bytes:
        engine, game = self._require_engine(engine_root, game_root)
        assets = self._assets_loader(engine)
        base = export_scenario(assets, scenario)
        title = archive_title(name)
        config_bytes = encode_scenario(assets, base, absolute=True)
        with tempfile.TemporaryDirectory(prefix="fm27lab-export-") as directory:
            workspace = require_local_path(Path(directory))
            config_path = workspace / SCENARIO_FILE_NAME
            plan_path = workspace / PLAN_FILE_NAME
            log_path = workspace / LOG_FILE_NAME
            archive_path = workspace / ARCHIVE_FILE_NAME
            config_path.write_bytes(config_bytes)
            run = self._run_export(
                engine=engine,
                game=game,
                executable=executable,
                plan_path=plan_path,
                config_path=config_path,
                log_path=log_path,
                title=title,
                timeout_seconds=timeout_seconds,
            )
            if run.returncode != 0:
                raise TacticExportError(EXPORT_FAILED_ERROR)
            if not plan_path.is_file():
                raise TacticExportError(WRITE_MISSING_ERROR)
            plan_bytes = plan_path.read_bytes()
            check_written_event(run.events, len(plan_bytes))
            payload = tactics_archive(plan_bytes, title)
            archive_path.write_bytes(payload)
            read_plan = self._read_back(
                archive_path=archive_path,
                engine=engine,
                game=game,
                executable=executable,
                timeout_seconds=timeout_seconds,
            )
        verify_round_trip(assets, base, read_plan)
        return payload

    def _run_export(
        self,
        *,
        engine: Path,
        game: Path,
        executable: str | Path | None,
        plan_path: Path,
        config_path: Path,
        log_path: Path,
        title: str,
        timeout_seconds: float,
    ) -> Any:
        environment = {
            EXPORT_TAC_ENVIRONMENT: str(require_local_path(plan_path)),
            EXPORT_SIDE_ENVIRONMENT: str(HOST_SIDE),
            EXPORT_TITLE_ENVIRONMENT: title,
        }
        arguments = (
            "--scenario-file",
            str(require_local_path(config_path)),
            "--output",
            str(require_local_path(log_path)),
        )
        try:
            return self._runner(
                engine_root=engine,
                game_root=game,
                executable=executable,
                timeout_seconds=timeout_seconds,
                environment=environment,
                arguments=arguments,
            )
        except TacticFileError as error:
            raise export_failure(error) from error

    def _read_back(
        self,
        *,
        archive_path: Path,
        engine: Path,
        game: Path,
        executable: str | Path | None,
        timeout_seconds: float,
    ) -> Any:
        try:
            return self._reader(
                require_local_path(archive_path),
                engine_root=engine,
                game_root=game,
                executable=executable,
                timeout_seconds=timeout_seconds,
            )
        except TacticFileError as error:
            raise export_failure(error) from error

    def _require_engine(
        self,
        engine_root: Path | None,
        game_root: Path | None,
    ) -> tuple[Path, Path]:
        if engine_root is None or game_root is None:
            raise EngineUnavailableError(UNCONFIGURED_ERROR)
        engine = Path(engine_root)
        game = Path(game_root)
        missing = (*missing_engine_files(engine), *missing_game_files(game))
        if missing:
            raise EngineUnavailableError(INCOMPLETE_ERROR.format(files="，".join(missing)))
        return engine, game


def export_scenario(assets: Any, scenario: Mapping[str, Any]) -> dict[str, Any]:
    teams = scenario.get("teams") if isinstance(scenario, Mapping) else None
    if not isinstance(teams, (list, tuple)) or len(teams) != 2 or not isinstance(teams[0], Mapping):
        raise TacticExportError(SCENARIO_ERROR)
    base = scenario_defaults(assets)
    home = base["teams"][0]
    source = teams[0]
    for key in ROUND_TRIP_KEYS:
        if key in source:
            home[key] = copy.deepcopy(source[key])
    return base


def archive_title(name: object) -> str:
    text = str(name or "")
    cleaned = "".join(
        character for character in text if character not in TITLE_FORBIDDEN and ord(character) >= 32
    )
    return cleaned.strip(" .")[:TITLE_MAX_CHARS] or DEFAULT_TITLE


def require_local_path(path: Path) -> Path:
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        raise TacticExportError(LOCAL_PATH_ERROR.format(path=text))
    return path


def check_written_event(events: list[dict[str, Any]], plan_size: int) -> None:
    event = _last_event(events, WRITTEN_EVENT)
    if event is None:
        return
    if event.get("accepted") is not True:
        raise TacticExportError(EXPORT_FAILED_ERROR)
    stream_error = event.get("stream_error")
    if stream_error is not None and int(stream_error) != 0:
        raise TacticExportError(EXPORT_FAILED_ERROR)
    size = event.get("size")
    if size is not None and int(size) != plan_size:
        raise TacticExportError(EXPORT_FAILED_ERROR)
    side = event.get("side")
    if side is not None and int(side) != HOST_SIDE:
        raise TacticExportError(EXPORT_FAILED_ERROR)


def verify_round_trip(assets: Any, exported: Mapping[str, Any], plan: Any) -> None:
    try:
        read_scenario = build_scenario(assets, plan)
    except ValueError as error:
        raise TacticExportError(ROUND_TRIP_ERROR) from error
    expected = exported["teams"][0]
    actual = read_scenario["teams"][0]
    differences = [key for key in ROUND_TRIP_KEYS if actual.get(key) != expected.get(key)]
    if differences:
        raise TacticExportError(ROUND_TRIP_ERROR)


def export_failure(error: TacticFileError) -> TacticExportError:
    message = str(error)
    if message == INCOMPATIBLE_ERROR:
        return EngineUnavailableError(message)
    if message.startswith(TIMEOUT_PREFIX):
        return TacticExportError(EXPORT_TIMEOUT_ERROR)
    return TacticExportError(message)


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if isinstance(event, Mapping) and event.get("event") == name:
            return dict(event)
    return None