"""OpenAPI 契约快照测试。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fm27lab.registry import CAPABILITIES

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPOSITORY_ROOT / "scripts" / "generate_openapi_snapshot.py"
SNAPSHOT_PATH = REPOSITORY_ROOT / "docs" / "openapi.json"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_openapi_snapshot", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(output: Path) -> int:
    return load_generator().main(["--output", str(output)])


def generated_document(tmp_path: Path) -> dict:
    output = tmp_path / "openapi.json"
    assert generate(output) == 0
    return json.loads(output.read_text(encoding="utf-8"))


def operations(document: dict) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, methods in document["paths"].items()
        for method in methods
    }


def test_committed_snapshot_matches_generator_output(tmp_path: Path):
    generator = load_generator()
    assert generator.DEFAULT_OUTPUT == SNAPSHOT_PATH
    output = tmp_path / "openapi.json"
    assert generate(output) == 0
    assert output.read_bytes() == SNAPSHOT_PATH.read_bytes(), (
        "docs/openapi.json 与当前应用不一致，"
        "请运行 .venv/bin/python scripts/generate_openapi_snapshot.py 重新生成"
    )


def test_snapshot_covers_every_registered_capability(tmp_path: Path):
    document = generated_document(tmp_path)
    declared = operations(document)
    missing = [item.name for item in CAPABILITIES if item.http not in declared]
    assert missing == []


def test_snapshot_is_deterministic(tmp_path: Path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    assert generate(first) == 0
    assert generate(second) == 0
    assert first.read_bytes() == second.read_bytes()


def test_snapshot_format_is_stable(tmp_path: Path):
    output = tmp_path / "openapi.json"
    assert generate(output) == 0
    text = output.read_text(encoding="utf-8")
    document = json.loads(text)
    assert text == json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert list(document["paths"]) == sorted(document["paths"])
    assert "/api/health" in document["paths"]


def test_snapshot_has_no_environment_specific_content(tmp_path: Path):
    output = tmp_path / "openapi.json"
    assert generate(output) == 0
    text = output.read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert str(Path.home()) not in text
    assert "TemporaryDirectory" not in text


def test_check_mode_accepts_matching_snapshot(tmp_path: Path):
    output = tmp_path / "openapi.json"
    assert generate(output) == 0
    assert load_generator().main(["--check", "--output", str(output)]) == 0


def test_check_mode_reports_drift(tmp_path: Path, capsys):
    output = tmp_path / "openapi.json"
    assert generate(output) == 0
    text = output.read_text(encoding="utf-8")
    output.write_text(text.replace('"/api/health"', '"/api/health-stale"', 1), encoding="utf-8")
    assert load_generator().main(["--check", "--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert "不一致" in captured.err


def test_check_mode_reports_missing_snapshot(tmp_path: Path):
    assert load_generator().main(["--check", "--output", str(tmp_path / "missing.json")]) == 1
