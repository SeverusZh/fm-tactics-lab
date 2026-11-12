from pathlib import Path

import pytest

from fm27lab.config import Settings


def test_settings_paths_and_directories(tmp_path: Path):
    settings = Settings.create(
        data_dir=tmp_path,
        engine_root=tmp_path / "engine",
        token="a" * 64,
    )
    assert settings.database_path == tmp_path / "fm27lab.db"
    assert settings.endpoint_path == tmp_path / "agent" / "endpoint.json"
    settings.ensure_dirs()
    assert settings.data_dir.is_dir()
    assert settings.endpoint_path.parent.is_dir()
    assert settings.exports_dir.is_dir()


def test_settings_from_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FM27LAB_DATA", str(tmp_path))
    monkeypatch.setenv("FM27LAB_TOKEN", "b" * 64)
    monkeypatch.setenv("FM27_ENGINE_ROOT", str(tmp_path / "engine"))
    monkeypatch.setenv("FM27LAB_PORT", "4321")
    monkeypatch.setenv("FM27LAB_DEV", "1")
    settings = Settings.from_env()
    assert settings.data_dir == tmp_path
    assert settings.token == "b" * 64
    assert settings.engine_root == tmp_path / "engine"
    assert settings.port == 4321
    assert settings.dev is True
    assert settings.host == "127.0.0.1"


def test_settings_reject_invalid_boundaries(tmp_path: Path):
    with pytest.raises(ValueError):
        Settings.create(data_dir="", token="a" * 64)
    with pytest.raises(ValueError):
        Settings.create(data_dir=tmp_path, token="")
    with pytest.raises(ValueError):
        Settings.create(data_dir=tmp_path, token="ключ")
    with pytest.raises(ValueError):
        Settings.create(data_dir=tmp_path, token="a" * 64, host="0.0.0.0")
    with pytest.raises(ValueError):
        Settings.create(data_dir=tmp_path, token="a" * 64, host="::1")
    with pytest.raises(ValueError):
        Settings.create(data_dir="./.", token="a" * 64)
    with pytest.raises(ValueError):
        Settings.create(data_dir="sub/..", token="a" * 64)
    with pytest.raises(ValueError):
        Settings.create(data_dir=tmp_path, token="a" * 64, port=70000)


def test_repr_does_not_leak_token(tmp_path: Path):
    settings = Settings.create(data_dir=tmp_path, token="topsecret" * 8)
    assert "topsecret" not in repr(settings)
    assert "topsecret" not in str(settings)


def test_empty_environment_data_dir_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        Settings.from_env({"FM27LAB_DATA": ""})
    with pytest.raises(ValueError):
        Settings.from_env({"FM27LAB_DATA": "."})
