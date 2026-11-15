from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from fm27lab.application.engine_diagnostics import (
    EngineDiagnoseError,
    EngineDiagnosis,
    diagnose_engine,
)


def build_engine_root(path: Path) -> Path:
    native = path / "fm27_native"
    native.mkdir(parents=True)
    (native / "FM27Simulator.exe").write_bytes(b"")
    (native / "catalog.json").write_text("{}", encoding="utf-8")
    (native / "editor_manual_default.json").write_text("{}", encoding="utf-8")
    (native / "editor_advanced_snapshot.json").write_text("{}", encoding="utf-8")
    (native / "editor_setpieces_default.json").write_text("{}", encoding="utf-8")
    research = path / "fm27_research"
    research.mkdir()
    (research / "setpiece_enum_catalog.json").write_text("{}", encoding="utf-8")
    return path


def build_game_root(path: Path) -> Path:
    plugins = path / "fm_Data" / "Plugins" / "x86_64"
    plugins.mkdir(parents=True)
    (plugins / "game_plugin.dll").write_bytes(b"")
    return path


def write_host(engine_root: Path, body: str) -> Path:
    host = engine_root / "fm27_native" / "diagnose_host.py"
    host.write_text(textwrap.dedent(body), encoding="utf-8")
    return host


def event(**fields: object) -> str:
    return json.dumps(fields)


def test_diagnose_engine_parses_stdout_events(tmp_path: Path, monkeypatch):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    argv_log = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_DIAGNOSE_ARGV", str(argv_log))
    host = write_host(
        engine,
        """
        import json
        import os
        import pathlib
        import sys

        pathlib.Path(os.environ["FAKE_DIAGNOSE_ARGV"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
        print(json.dumps({"event": "native_engine_compatibility", "compatible": True, "trial_allowed": False, "reason": "镜像哈希匹配"}))
        print(json.dumps({"event": "native_image_fingerprint", "sha256": "a" * 64}))
        """,
    )
    (engine / "fm27_native" / "adapter_version.json").write_text('{"version": "2.1.0"}', encoding="utf-8")

    diagnosis = diagnose_engine(engine, game, executable=host)

    assert diagnosis == EngineDiagnosis(
        compatible=True,
        trial_allowed=False,
        reason="镜像哈希匹配",
        adapter_version="2.1.0",
        image_sha256="a" * 64,
    )
    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    assert argv[0] == "--check-image"
    assert argv[1] == str(game.resolve() / "fm_Data" / "Plugins" / "x86_64" / "game_plugin.dll")
    assert "--output" in argv
    assert argv[argv.index("--output") + 1].endswith(".log")


def test_diagnose_engine_reads_events_written_to_output_file(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    host = write_host(
        engine,
        """
        import json
        import pathlib
        import sys

        output = pathlib.Path(sys.argv[sys.argv.index("--output") + 1])
        rows = [
            {"event": "native_engine_compatibility", "compatible": False, "trial_allowed": True, "reason": "试验可用"},
            {"event": "native_image_fingerprint", "sha256": "b" * 64},
        ]
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                print(json.dumps(row), file=handle)
        """,
    )

    diagnosis = diagnose_engine(engine, game, executable=host)

    assert diagnosis.compatible is False
    assert diagnosis.trial_allowed is True
    assert diagnosis.reason == "试验可用"
    assert diagnosis.image_sha256 == "b" * 64
    assert diagnosis.adapter_version is None


def test_diagnose_engine_rejects_timeout_with_chinese_message(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    host = write_host(
        engine,
        """
        import time

        time.sleep(5)
        """,
    )

    with pytest.raises(EngineDiagnoseError) as caught:
        diagnose_engine(engine, game, executable=host, timeout_seconds=0.2)

    assert "超时" in str(caught.value)


def test_diagnose_engine_reports_nonzero_exit(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    host = write_host(
        engine,
        """
        import json
        import sys

        print(json.dumps({"event": "native_engine_compatibility", "compatible": True, "trial_allowed": False}))
        sys.exit(99)
        """,
    )

    with pytest.raises(EngineDiagnoseError) as caught:
        diagnose_engine(engine, game, executable=host)

    message = str(caught.value)
    assert "诊断失败" in message
    assert "99" in message


def test_diagnose_engine_requires_compatibility_event(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = build_game_root(tmp_path / "game")
    host = write_host(
        engine,
        """
        import json

        print(json.dumps({"event": "native_image_fingerprint", "sha256": "c" * 64}))
        """,
    )

    with pytest.raises(EngineDiagnoseError) as caught:
        diagnose_engine(engine, game, executable=host)

    assert "兼容性" in str(caught.value)


def test_diagnose_engine_names_missing_engine_files(tmp_path: Path):
    engine = tmp_path / "engine"
    engine.mkdir()
    game = build_game_root(tmp_path / "game")

    with pytest.raises(EngineDiagnoseError) as caught:
        diagnose_engine(engine, game)

    assert "引擎目录缺少" in str(caught.value)
    assert "fm27_native/FM27Simulator.exe" in str(caught.value)


def test_diagnose_engine_names_missing_game_plugin(tmp_path: Path):
    engine = build_engine_root(tmp_path / "engine")
    game = tmp_path / "game"
    game.mkdir()

    with pytest.raises(EngineDiagnoseError) as caught:
        diagnose_engine(engine, game)

    assert "游戏目录缺少" in str(caught.value)
    assert "fm_Data/Plugins/x86_64/game_plugin.dll" in str(caught.value)


def test_diagnosis_dataclass_has_expected_fields(tmp_path: Path):
    diagnosis = EngineDiagnosis(True, False, None, None, None)
    assert diagnosis.compatible is True
    assert diagnosis.adapter_version is None
