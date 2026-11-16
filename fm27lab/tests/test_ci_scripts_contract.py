from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPTS = ROOT / "scripts"


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def job_block(text: str, job: str) -> str:
    pattern = re.compile(
        rf"^  {job}:\n(?:.*\n)*?(?=^  [a-z][\w-]*:\n|\Z)", re.MULTILINE
    )
    match = pattern.search(text)
    assert match is not None, f"job {job} not found"
    return match.group(0)


def test_windows_concurrency_job_supplies_capacity_overrides():
    block = job_block(workflow("ci.yml"), "windows-concurrency")
    assert "scripts/verify_concurrency_matrix.py" in block
    assert "--matches 256" in block
    assert "--available-memory-bytes 17179869184" in block
    assert "--free-disk-bytes 322122547200" in block
    assert "timeout-minutes: 60" in block


def test_matrix_script_accepts_the_overrides_used_by_ci():
    text = (SCRIPTS / "verify_concurrency_matrix.py").read_text(encoding="utf-8")
    assert '"--available-memory-bytes"' in text
    assert '"--free-disk-bytes"' in text


def test_engine_script_does_not_shadow_matches_variable():
    text = (SCRIPTS / "verify_engine_windows.ps1").read_text(encoding="utf-8")
    assert "$Matches" not in text
    assert "[int]$MatchCount" in text
    assert text.count("-MatchCount $MatchCount") == 2


def test_installer_qa_runs_in_windows_tauri_job():
    block = job_block(workflow("ci.yml"), "windows-tauri")
    assert "scripts/verify_installer_windows.ps1" in block
    assert "dist/installer-qa" in block


def test_gitattributes_pins_text_checkout_line_endings():
    rules = [line for line in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rules
    unpinned = [line for line in rules if "text" in line and "eol=" not in line]
    assert unpinned == [], f"text rules without eol pin rewrite worktree bytes on Windows: {unpinned}"


def test_release_workflow_builds_installer_with_locked_dependencies():
    text = workflow("release.yml")
    assert "tauri build --bundles nsis" in text
    assert "cargo test --locked" in text
    assert "scripts/verify_installer_windows.ps1" in text
