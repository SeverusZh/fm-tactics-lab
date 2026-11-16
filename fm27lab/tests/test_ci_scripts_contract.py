from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPTS = ROOT / "scripts"


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def job_block(text: str, job: str) -> str:
    pattern = re.compile(rf"^  {job}:\n(?:.*\n)*?(?=^  [a-z][\w-]*:\n|\Z)", re.MULTILINE)
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


def read_gitattributes_rules():
    rules = []
    for raw in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern, *attributes = line.split()
        values = {}
        for attribute in attributes:
            key, _, value = attribute.partition("=")
            values[key] = value or True
        rules.append((pattern, values))
    return rules


def test_gitattributes_default_rule_pins_lf_checkout():
    rules = read_gitattributes_rules()
    default = [values for pattern, values in rules if pattern == "*"]
    assert len(default) == 1, "exactly one default rule decides every unlisted type"
    assert default[0].get("text") == "auto"
    assert default[0].get("eol") == "lf", "default checkout must stay LF or manifest hashes break on Windows"


def test_gitattributes_pins_text_checkout_line_endings():
    rules = read_gitattributes_rules()
    assert rules
    unpinned = [
        pattern
        for pattern, values in rules
        if "text" in values and values["text"] is not False and "eol" not in values
    ]
    assert unpinned == [], f"text rules without eol pin rewrite worktree bytes on Windows: {unpinned}"
    invalid = [
        (pattern, values.get("eol"))
        for pattern, values in rules
        if values.get("eol") not in (None, "lf", "crlf")
    ]
    assert invalid == [], f"unknown eol values: {invalid}"


def test_gitattributes_keeps_c_sources_on_crlf():
    rules = read_gitattributes_rules()
    by_pattern = {pattern: values for pattern, values in rules}
    for pattern in ("*.cs", "*.cpp", "*.h"):
        assert pattern in by_pattern, f"missing C family rule {pattern}"
        assert by_pattern[pattern].get("eol") == "crlf", (
            f"{pattern} must keep CRLF for the native host sources"
        )


def test_release_workflow_builds_installer_with_locked_dependencies():
    text = workflow("release.yml")
    assert "tauri build --bundles nsis" in text
    assert "cargo test --locked" in text
    assert "scripts/verify_installer_windows.ps1" in text
