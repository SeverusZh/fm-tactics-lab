from pathlib import Path

from typer.testing import CliRunner

import fm27lab.cli as cli


def test_serve_inherits_dev_from_environment(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "run", lambda settings: captured.setdefault("settings", settings) and 0)
    monkeypatch.setenv("FM27LAB_DATA", str(tmp_path))
    monkeypatch.setenv("FM27LAB_TOKEN", "a" * 64)
    monkeypatch.setenv("FM27LAB_DEV", "1")
    result = CliRunner().invoke(cli.app, ["serve"])
    assert result.exit_code == 0, result.output
    assert captured["settings"].dev is True


def test_serve_inherits_host_and_port_from_environment(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "run", lambda settings: captured.setdefault("settings", settings) and 0)
    monkeypatch.setenv("FM27LAB_DATA", str(tmp_path))
    monkeypatch.setenv("FM27LAB_TOKEN", "a" * 64)
    monkeypatch.setenv("FM27LAB_HOST", "localhost")
    monkeypatch.setenv("FM27LAB_PORT", "4321")
    result = CliRunner().invoke(cli.app, ["serve"])
    assert result.exit_code == 0, result.output
    assert captured["settings"].host == "localhost"
    assert captured["settings"].port == 4321


def test_no_dev_flag_overrides_environment(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "run", lambda settings: captured.setdefault("settings", settings) and 0)
    monkeypatch.setenv("FM27LAB_DATA", str(tmp_path))
    monkeypatch.setenv("FM27LAB_TOKEN", "a" * 64)
    monkeypatch.setenv("FM27LAB_DEV", "1")
    result = CliRunner().invoke(cli.app, ["serve", "--no-dev"])
    assert result.exit_code == 0, result.output
    assert captured["settings"].dev is False


def test_serve_passes_explicit_roots_to_the_runner(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_run(settings, **kwargs):
        captured["settings"] = settings
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setenv("FM27LAB_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("FM27LAB_TOKEN", "a" * 64)
    engine = tmp_path / "engine"
    engine.mkdir()
    game = tmp_path / "game"
    game.mkdir()
    result = CliRunner().invoke(
        cli.app,
        ["serve", "--engine-root", str(engine), "--game-root", str(game)],
    )
    assert result.exit_code == 0, result.output
    assert captured["kwargs"] == {"engine_root": engine, "game_root": game}
    assert captured["settings"].engine_root is None
    assert captured["settings"].game_root is None
