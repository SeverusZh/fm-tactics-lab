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
