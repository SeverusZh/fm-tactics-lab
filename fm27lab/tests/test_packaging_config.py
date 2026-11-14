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


def test_ci_verifies_installer_payload_layout():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "sidecar/_internal" in workflow
    assert "7-Zip" in workflow
    assert any(
        "Test-Path $installedInternal" in line for line in workflow.splitlines()
    )
