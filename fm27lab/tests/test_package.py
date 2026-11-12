from importlib.metadata import entry_points

import fm27lab


def test_package_version():
    assert fm27lab.__version__ == "2.0.0.dev0"


def test_api_version():
    assert fm27lab.API_VERSION == "fm27lab/v2"


def test_console_entry_point_exists():
    scripts = {entry.name: entry.value for entry in entry_points(group="console_scripts")}
    assert scripts.get("fm27lab") == "fm27lab.cli:main"
    assert scripts.get("fm27lab-sidecar") == "fm27lab.sidecar_main:main"
