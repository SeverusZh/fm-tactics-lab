from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "src-tauri" / "tauri.conf.json"


def sidecar_resources() -> dict[str, str]:
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    return document["bundle"]["resources"]


def test_sidecar_resources_use_directory_mapping():
    assert sidecar_resources() == {"../sidecar-dist/fm27lab-sidecar/": "sidecar/"}


def test_sidecar_resources_do_not_flatten_nested_files():
    for pattern in sidecar_resources():
        assert "*" not in pattern


def test_sidecar_build_produces_onedir_payload():
    script = (ROOT / "scripts" / "build_sidecar.py").read_text(encoding="utf-8")
    assert '"--onedir"' in script
    assert "fm27lab/adapters/storage_sqlite/migrations" in script


def installer_hooks() -> Path:
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    relative = document["bundle"]["windows"]["nsis"]["installerHooks"]
    return (CONFIG.parent / relative).resolve()


def test_installer_hooks_file_exists():
    hooks = installer_hooks()
    assert hooks.is_file()
    assert hooks.suffix == ".nsh"


def test_installer_hooks_stop_running_processes_before_touching_files():
    text = installer_hooks().read_text(encoding="utf-8")
    assert "!macro NSIS_HOOK_PREINSTALL" in text
    assert "!macro NSIS_HOOK_PREUNINSTALL" in text
    assert text.count("!insertmacro FM27LAB_STOP_PROCESSES") == 2
    for image in ("fm27lab-sidecar.exe", "fm27lab-desktop.exe"):
        assert f"nsExec::Exec 'taskkill /F /T /IM {image}'" in text
    assert text.count("Pop $0") == 2


def test_ci_verifies_installer_payload_layout():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "sidecar/_internal" in workflow
    assert "7-Zip" in workflow
    assert any(
        "Test-Path $installedInternal" in line for line in workflow.splitlines()
    )
