"""桌面文件对话框接线的结构性回归测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES = ROOT / "src-tauri" / "capabilities" / "default.json"
LIB = ROOT / "src-tauri" / "src" / "lib.rs"
MANIFEST = ROOT / "src-tauri" / "Cargo.toml"
LOCK = ROOT / "src-tauri" / "Cargo.lock"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _permissions() -> list[str]:
    document = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    return list(document["permissions"])


def test_capabilities_grant_only_dialog_open() -> None:
    permissions = _permissions()
    assert "core:default" in permissions
    assert "dialog:allow-open" in permissions
    assert "dialog:default" not in permissions


def test_dialog_plugin_registered_once_after_single_instance() -> None:
    source = LIB.read_text(encoding="utf-8")
    assert source.count("tauri_plugin_dialog::init()") == 1
    dialog = source.index("tauri_plugin_dialog::init()")
    single_instance = source.index("tauri_plugin_single_instance::init(")
    assert single_instance < dialog


def test_manifest_and_lock_declare_dialog_plugin() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert re.search(r'^tauri-plugin-dialog = "2"$', manifest, re.MULTILINE)
    lock = LOCK.read_text(encoding="utf-8")
    assert 'name = "tauri-plugin-dialog"' in lock


def test_ci_builds_rust_with_locked_dependencies() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "cargo test --locked --manifest-path rust/Cargo.toml -p fm27lab-core" in workflow
    assert "cargo build --locked --manifest-path src-tauri/Cargo.toml" in workflow
    assert "cargo test --locked --manifest-path src-tauri/Cargo.toml" in workflow
