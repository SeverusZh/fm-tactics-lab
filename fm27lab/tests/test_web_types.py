from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPOSITORY_ROOT / "scripts" / "generate_web_types.py"
SCHEMA_PATH = REPOSITORY_ROOT / "web" / "src" / "lib" / "api-schema.ts"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_web_types", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(output: Path) -> int:
    return load_generator().main(["--output", str(output)])


def test_committed_types_match_generator_output(tmp_path: Path):
    generator = load_generator()
    assert generator.DEFAULT_OUTPUT == SCHEMA_PATH
    output = tmp_path / "api-schema.ts"
    assert generate(output) == 0
    generated = output.read_bytes()
    committed = SCHEMA_PATH.read_bytes()
    assert committed == generated, (
        "web/src/lib/api-schema.ts 与生成结果不一致，"
        "请运行 .venv/bin/python scripts/generate_web_types.py 重新生成"
    )


def test_generated_types_cover_every_component_schema(tmp_path: Path):
    output = tmp_path / "api-schema.ts"
    assert generate(output) == 0
    text = output.read_text(encoding="utf-8")
    header = "\n".join(text.splitlines()[:3])
    assert "自动生成" in header
    assert "请勿" in header
    schemas = load_generator().openapi_document()["components"]["schemas"]
    assert schemas
    for name in schemas:
        pattern = rf"^export (?:interface|type) {re.escape(name)}\b"
        assert re.search(pattern, text, re.MULTILINE), name


def test_generation_is_deterministic(tmp_path: Path):
    first = tmp_path / "first.ts"
    second = tmp_path / "second.ts"
    assert generate(first) == 0
    assert generate(second) == 0
    assert first.read_bytes() == second.read_bytes()


def test_check_mode_accepts_matching_output(tmp_path: Path):
    output = tmp_path / "api-schema.ts"
    assert generate(output) == 0
    assert load_generator().main(["--check", "--output", str(output)]) == 0


def test_check_mode_rejects_drifted_output(tmp_path: Path):
    output = tmp_path / "api-schema.ts"
    assert generate(output) == 0
    text = output.read_text(encoding="utf-8")
    output.write_text(text.replace("export interface ", "export interface Stale", 1), encoding="utf-8")
    assert load_generator().main(["--check", "--output", str(output)]) == 1


def test_render_types_sorts_schema_names():
    document = {
        "components": {
            "schemas": {
                "Zebra": {"type": "object", "properties": {"value": {"type": "string"}}},
                "Alpha": {"type": "object", "properties": {"value": {"type": "number"}}},
            }
        }
    }
    rendered = load_generator().render_types(document)
    assert rendered.index("export interface Alpha") < rendered.index("export interface Zebra")


def test_check_mode_reports_missing_file(tmp_path: Path):
    missing = tmp_path / "missing.ts"
    assert load_generator().main(["--check", "--output", str(missing)]) == 1
