"""从草案场景导出 FMF v8 归档的应用层测试。"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from fm27lab.adapters.engine_native import scenario_codec
from fm27lab.adapters.engine_native.scenario_assets import load_scenario_assets
from fm27lab.adapters.engine_native.tactic_file import (
    INCOMPATIBLE_ERROR,
    HostRun,
    TacticCell,
    TacticFileError,
    TacticPlan,
)
from fm27lab.adapters.fmf.archive import (
    ARCHIVE_HEADER,
    read_tactics_archive,
)
from fm27lab.application.tactic_export import (
    DEFAULT_TITLE,
    EXPORT_FAILED_ERROR,
    EXPORT_TIMEOUT_ERROR,
    EXPORT_TIMEOUT_SECONDS,
    ROUND_TRIP_ERROR,
    ROUND_TRIP_KEYS,
    SCENARIO_ERROR,
    UNCONFIGURED_ERROR,
    WRITE_MISSING_ERROR,
    EngineUnavailableError,
    TacticExporter,
    TacticExportError,
    archive_title,
    check_written_event,
    export_failure,
    export_scenario,
    require_local_path,
    verify_round_trip,
)
from fm27lab.tests.test_scenario_assets import write_engine_root
from fm27lab.tests.test_tactic_import import DUTY_BIT, plan_from_defaults

PLAN_MARKER = b"FM27LABPLAN\n"
TITLE = "主场战术"
TACTICAL_KEYS = ("mentality", "instructions", "native_extra_team_bits", "phases")


def build_game_root(root: Path) -> Path:
    (root / "fm_Data" / "Plugins" / "x86_64").mkdir(parents=True, exist_ok=True)
    (root / "fm_Data" / "Plugins" / "x86_64" / "game_plugin.dll").write_bytes(b"plugin")
    return root


def faithful_plan(assets, **overrides) -> TacticPlan:
    plan = plan_from_defaults(assets, **overrides)
    phases = tuple(
        tuple(dataclasses.replace(cell, role_flags=cell.role_flags & ~DUTY_BIT) for cell in phase)
        for phase in plan.phases
    )
    return dataclasses.replace(plan, phases=phases)


def plan_document(plan: TacticPlan) -> dict:
    return {
        "name": plan.name,
        "mentality": plan.mentality,
        "team_bits": plan.team_bits,
        "mapping": list(plan.mapping),
        "phases": [
            [
                {
                    "position": cell.position,
                    "role_flags": cell.role_flags,
                    "pi_flags": cell.pi_flags,
                    "target_player": cell.target_player,
                    "target_position": cell.target_position,
                }
                for cell in phase
            ]
            for phase in plan.phases
        ],
    }


def encode_plan(plan: TacticPlan) -> bytes:
    return PLAN_MARKER + json.dumps(plan_document(plan), sort_keys=True).encode("utf-8")


def decode_plan(payload: bytes) -> TacticPlan:
    assert payload.startswith(PLAN_MARKER)
    data = json.loads(payload[len(PLAN_MARKER) :])
    return TacticPlan(
        name=data["name"],
        mentality=data["mentality"],
        team_bits=data["team_bits"],
        mapping=tuple(data["mapping"]),
        phases=tuple(
            tuple(TacticCell(**{**cell, "role_flags": int(cell["role_flags"]), "pi_flags": int(cell["pi_flags"])}) for cell in phase)
            for phase in data["phases"]
        ),
    )


class FakeHost:
    def __init__(
        self,
        plan: bytes | None = None,
        *,
        returncode: int = 0,
        events: list[dict] | None = None,
        write_plan: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.plan = plan
        self.returncode = returncode
        self.events = events
        self.write_plan = write_plan
        self.error = error
        self.calls: list[dict] = []
        self.config_bytes: bytes | None = None

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        config = Path(kwargs["arguments"][1])
        self.config_bytes = config.read_bytes()
        if self.error is not None:
            raise self.error
        environment = kwargs["environment"]
        plan_path = Path(environment["FM27_EXPORT_TAC"])
        if self.write_plan:
            plan_path.write_bytes(self.plan or b"")
        size = len(plan_path.read_bytes()) if self.write_plan else 0
        events = self.events
        if events is None:
            events = [
                {
                    "event": "native_tactic_file_written",
                    "accepted": True,
                    "stream_error": 0,
                    "size": size,
                    "side": 0,
                }
            ]
        return HostRun(self.returncode, events, "")


class ArchiveReader:
    def __init__(self, transform=None, error: Exception | None = None) -> None:
        self.transform = transform
        self.error = error
        self.paths: list[Path] = []
        self.payloads: list[bytes] = []

    def __call__(self, path: Path, **kwargs):
        self.paths.append(Path(path))
        if self.error is not None:
            raise self.error
        payload = Path(path).read_bytes()
        self.payloads.append(payload)
        plan = decode_plan(read_tactics_archive(payload).plan)
        return self.transform(plan) if self.transform is not None else plan


@pytest.fixture()
def engine(tmp_path: Path) -> Path:
    root = write_engine_root(tmp_path / "engine-root")
    (root / "fm27_native" / "FM27Simulator.exe").write_bytes(b"native-host")
    return root


@pytest.fixture()
def game(tmp_path: Path) -> Path:
    return build_game_root(tmp_path / "game")


@pytest.fixture()
def assets(engine: Path):
    return load_scenario_assets(engine)


def make_exporter(host: FakeHost, reader: ArchiveReader | None = None, *, loader=load_scenario_assets) -> TacticExporter:
    return TacticExporter(
        assets_loader=loader,
        runner=host,
        reader=reader if reader is not None else ArchiveReader(),
    )


def export_defaults(exporter: TacticExporter, engine: Path, game: Path, scenario: dict | None = None) -> bytes:
    scenario = scenario if scenario is not None else scenario_codec.defaults(load_scenario_assets(engine))
    return exporter.export(name=TITLE, scenario=scenario, engine_root=engine, game_root=game)


def test_export_runs_host_and_packs_archive(engine: Path, game: Path, assets) -> None:
    plan = faithful_plan(assets)
    host = FakeHost(encode_plan(plan))
    payload = export_defaults(make_exporter(host), engine, game)
    assert payload.startswith(ARCHIVE_HEADER)
    archive = read_tactics_archive(payload)
    assert archive.title == TITLE
    assert archive.plan == encode_plan(plan)
    call = host.calls[0]
    environment = call["environment"]
    assert environment["FM27_EXPORT_SIDE"] == "0"
    assert environment["FM27_EXPORT_TITLE"] == TITLE
    assert Path(environment["FM27_EXPORT_TAC"]).suffix == ".tac"
    assert call["arguments"][0] == "--scenario-file"
    assert call["arguments"][2] == "--output"
    assert call["engine_root"] == engine
    assert call["game_root"] == game
    assert call["timeout_seconds"] == EXPORT_TIMEOUT_SECONDS
    assert host.config_bytes is not None
    assert host.config_bytes.startswith(b"FM27CFG1")


def test_export_round_trip_passes_for_draft_overrides(engine: Path, game: Path, assets) -> None:
    plan = dataclasses.replace(faithful_plan(assets), mentality=7)
    scenario = scenario_codec.defaults(assets)
    scenario["teams"][0]["mentality"] = 7
    host = FakeHost(encode_plan(plan))
    reader = ArchiveReader()
    payload = export_defaults(make_exporter(host, reader), engine, game, scenario)
    assert read_tactics_archive(payload).plan == encode_plan(plan)
    assert len(reader.paths) == 1
    assert reader.paths[0].is_absolute()
    assert reader.payloads[0] == payload


def test_export_maps_host_timeout(engine: Path, game: Path) -> None:
    host = FakeHost(error=TacticFileError("引擎解析超时：45 秒内未返回"))
    with pytest.raises(TacticExportError, match=EXPORT_TIMEOUT_ERROR):
        export_defaults(make_exporter(host), engine, game)


def test_export_rejects_nonzero_exit(engine: Path, game: Path) -> None:
    host = FakeHost(b"plan", returncode=171)
    with pytest.raises(TacticExportError, match=EXPORT_FAILED_ERROR):
        export_defaults(make_exporter(host), engine, game)


def test_export_rejects_missing_plan_file(engine: Path, game: Path) -> None:
    host = FakeHost(b"plan", write_plan=False)
    with pytest.raises(TacticExportError, match=WRITE_MISSING_ERROR):
        export_defaults(make_exporter(host), engine, game)


@pytest.mark.parametrize(
    "event",
    [
        {"event": "native_tactic_file_written", "accepted": False, "stream_error": 0, "size": 4, "side": 0},
        {"event": "native_tactic_file_written", "accepted": True, "stream_error": 1, "size": 4, "side": 0},
        {"event": "native_tactic_file_written", "accepted": True, "stream_error": 0, "size": 3, "side": 0},
        {"event": "native_tactic_file_written", "accepted": True, "stream_error": 0, "size": 4, "side": 1},
    ],
)
def test_export_rejects_failed_written_event(engine: Path, game: Path, event: dict) -> None:
    host = FakeHost(b"plan", events=[event])
    with pytest.raises(TacticExportError, match=EXPORT_FAILED_ERROR):
        export_defaults(make_exporter(host), engine, game)


def test_export_requires_configured_engine(engine: Path) -> None:
    host = FakeHost(b"plan")
    with pytest.raises(EngineUnavailableError, match=UNCONFIGURED_ERROR):
        make_exporter(host).export(name=TITLE, scenario={}, engine_root=None, game_root=None)
    with pytest.raises(EngineUnavailableError, match=UNCONFIGURED_ERROR):
        make_exporter(host).export(name=TITLE, scenario={}, engine_root=engine, game_root=None)
    assert host.calls == []


def test_export_reports_incomplete_engine(tmp_path: Path) -> None:
    engine = tmp_path / "empty-engine"
    engine.mkdir()
    game = build_game_root(tmp_path / "game")
    with pytest.raises(EngineUnavailableError) as caught:
        make_exporter(FakeHost(b"plan")).export(
            name=TITLE, scenario={}, engine_root=engine, game_root=game
        )
    message = str(caught.value)
    assert message.startswith("引擎资源不完整")
    assert "fm27_native/FM27Simulator.exe" in message


def test_export_maps_incompatible_engine(engine: Path, game: Path) -> None:
    host = FakeHost(error=TacticFileError(INCOMPATIBLE_ERROR))
    with pytest.raises(EngineUnavailableError, match=INCOMPATIBLE_ERROR):
        export_defaults(make_exporter(host), engine, game)


def test_export_rejects_round_trip_mismatch(engine: Path, game: Path, assets) -> None:
    plan = faithful_plan(assets)
    reader = ArchiveReader(transform=lambda plan: dataclasses.replace(plan, mentality=plan.mentality + 1))
    with pytest.raises(TacticExportError, match=ROUND_TRIP_ERROR):
        export_defaults(make_exporter(FakeHost(encode_plan(plan)), reader), engine, game)


def test_export_rejects_phase_round_trip_mismatch(engine: Path, game: Path, assets) -> None:
    plan = faithful_plan(assets)

    def retarget(value: TacticPlan) -> TacticPlan:
        phases = tuple(
            tuple(
                dataclasses.replace(cell, target_player=cell.target_player + 1) if index == 0 else cell
                for index, cell in enumerate(phase)
            )
            for phase in value.phases
        )
        return dataclasses.replace(value, phases=phases)

    reader = ArchiveReader(transform=retarget)
    with pytest.raises(TacticExportError, match=ROUND_TRIP_ERROR):
        export_defaults(make_exporter(FakeHost(encode_plan(plan)), reader), engine, game)


def test_export_maps_read_back_failures(engine: Path, game: Path, assets) -> None:
    error = TacticFileError("游戏引擎无法解析该战术文件")
    reader = ArchiveReader(error=error)
    with pytest.raises(TacticExportError, match="游戏引擎无法解析该战术文件"):
        export_defaults(make_exporter(FakeHost(encode_plan(faithful_plan(assets))), reader), engine, game)


def test_export_uses_local_temporary_paths(engine: Path, game: Path, assets) -> None:
    host = FakeHost(encode_plan(faithful_plan(assets)))
    reader = ArchiveReader()
    export_defaults(make_exporter(host, reader), engine, game)
    environment = host.calls[0]["environment"]
    paths = [Path(environment["FM27_EXPORT_TAC"]), Path(host.calls[0]["arguments"][1]), Path(host.calls[0]["arguments"][3])]
    for path in paths:
        assert path.is_absolute()
        assert not str(path).startswith("//")
        assert ".." not in path.parts
    assert all(not path.exists() for path in (*paths, reader.paths[0]))


def test_export_scenario_overrides_only_home_tactical_keys(assets) -> None:
    base = scenario_codec.defaults(assets)
    draft = scenario_codec.defaults(assets)
    draft["teams"][0]["mentality"] = 9
    draft["teams"][0]["name"] = "被忽略的主队名"
    draft["teams"][1]["mentality"] = 2
    exported = export_scenario(assets, draft)
    assert exported["teams"][1] == base["teams"][1]
    home = exported["teams"][0]
    for key in ("mentality", "instructions", "native_extra_team_bits", "phases"):
        expected = draft["teams"][0][key] if key != "mentality" else 9
        assert home[key] == expected
    assert home["name"] == base["teams"][0]["name"]


def test_export_scenario_falls_back_to_defaults_for_plain_drafts(assets) -> None:
    draft = {**scenario_codec.defaults(assets)}
    for key in ("mentality", "instructions", "native_extra_team_bits", "phases"):
        draft["teams"][0].pop(key)
    exported = export_scenario(assets, draft)
    assert exported["teams"][0]["mentality"] == scenario_codec.defaults(assets)["teams"][0]["mentality"]


def test_export_scenario_rejects_malformed_drafts(assets) -> None:
    with pytest.raises(TacticExportError, match=SCENARIO_ERROR):
        export_scenario(assets, {})
    with pytest.raises(TacticExportError, match=SCENARIO_ERROR):
        export_scenario(assets, {"teams": [{}]})


def test_round_trip_keys_cover_tactical_sections() -> None:
    assert ROUND_TRIP_KEYS == TACTICAL_KEYS


@pytest.mark.parametrize("key", TACTICAL_KEYS)
def test_export_scenario_copies_each_draft_key(assets, key: str) -> None:
    draft = scenario_codec.defaults(assets)
    if key == "phases":
        marker = [[dict(cell) for cell in phase] for phase in draft["teams"][0][key]]
        marker[0][0]["target_player"] = 9
    elif key == "mentality":
        marker = 9
    elif key == "instructions":
        marker = {"5": 0}
    else:
        marker = "16"
    draft["teams"][0][key] = marker
    assert export_scenario(assets, draft)["teams"][0][key] == marker


@pytest.mark.parametrize("key", TACTICAL_KEYS)
def test_verify_round_trip_rejects_mismatch_for_each_key(assets, key: str) -> None:
    exported = export_scenario(assets, scenario_codec.defaults(assets))
    home = exported["teams"][0]
    if key == "phases":
        home[key][0][0]["target_player"] += 1
    elif key == "mentality":
        home[key] += 1
    elif key == "instructions":
        home[key] = {"9": 9}
    else:
        home[key] = "deadbeef"
    with pytest.raises(TacticExportError, match=ROUND_TRIP_ERROR):
        verify_round_trip(assets, exported, faithful_plan(assets))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("主场战术", "主场战术"),
        ('ev"il:name', "evilname"),
        ("  . ", DEFAULT_TITLE),
        ("", DEFAULT_TITLE),
        (None, DEFAULT_TITLE),
        ("a" * 130, "a" * 100),
    ],
)
def test_archive_title_sanitizes_draft_names(name, expected: str) -> None:
    assert archive_title(name) == expected


def test_require_local_path_rejects_unc_paths(tmp_path: Path) -> None:
    local = tmp_path / "tactic.tac"
    assert require_local_path(local) == local
    for text in ("//server/share/tactic.tac", "\\\\server\\\\share\\\\tactic.tac"):
        with pytest.raises(TacticExportError, match="本地路径"):
            require_local_path(Path(text))


def test_check_written_event_tolerates_missing_event_and_fields() -> None:
    check_written_event([], 4)
    check_written_event([{"event": "native_tactic_file_written", "accepted": True}], 4)
    check_written_event(
        [{"event": "native_tactic_file_written", "accepted": True, "stream_error": 0, "size": 4, "side": 0}],
        4,
    )


def test_export_failure_mapping() -> None:
    assert isinstance(export_failure(TacticFileError(INCOMPATIBLE_ERROR)), EngineUnavailableError)
    assert str(export_failure(TacticFileError("引擎解析超时：45 秒内未返回"))) == EXPORT_TIMEOUT_ERROR
    assert str(export_failure(TacticFileError("引擎目录不存在或不是目录：/x"))) == "引擎目录不存在或不是目录：/x"