from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "web" / "src" / "lib" / "api-schema.ts"
HEADER_LINES = (
    "// 本文件由 scripts/generate_web_types.py 自动生成，请勿手动修改。",
    "// 重新生成：.venv/bin/python scripts/generate_web_types.py",
    "// 校验一致：.venv/bin/python scripts/generate_web_types.py --check",
)
IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
SCALAR_TYPES = {
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "string": "string",
    "null": "null",
}


def openapi_document() -> dict[str, Any]:
    from fm27lab.adapters.storage_sqlite.db import Database
    from fm27lab.config import Settings
    from fm27lab.interfaces.http.app import create_app

    with tempfile.TemporaryDirectory(prefix="fm27lab-web-types-") as directory:
        settings = Settings.create(data_dir=Path(directory))
        database = Database(settings.database_path)
        return create_app(settings, database).openapi()


def render_types(document: dict[str, Any]) -> str:
    schemas = component_schemas(document)
    declarations = [render_declaration(name, schemas[name]) for name in sorted(schemas)]
    body = "\n\n".join(declarations)
    return "\n".join((*HEADER_LINES, "", body)) + "\n"


def component_schemas(document: dict[str, Any]) -> dict[str, Any]:
    schemas = document.get("components", {}).get("schemas")
    if not isinstance(schemas, dict) or not schemas:
        raise ValueError("OpenAPI 文档缺少 components.schemas")
    return schemas


def render_declaration(name: str, schema: Any) -> str:
    if isinstance(schema, dict) and schema.get("type") == "object":
        members = object_members(schema)
        return "\n".join((f"export interface {name} {{", *(f"  {member};" for member in members), "}"))
    return f"export type {name} = {ts_type(schema)};"


def ts_type(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "unknown"
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return reference.rsplit("/", 1)[-1]
    values = schema.get("enum")
    if isinstance(values, list) and values:
        return union(json.dumps(value, ensure_ascii=False) for value in values)
    for keyword in ("oneOf", "anyOf"):
        options = schema.get(keyword)
        if isinstance(options, list) and options:
            return union(ts_type(option) for option in options)
    kind = schema.get("type")
    if isinstance(kind, list):
        return union(ts_type({**schema, "type": item}) for item in kind)
    if kind == "object":
        return object_type(schema)
    if kind == "array":
        item = ts_type(schema.get("items", {}))
        return f"({item})[]" if " | " in item else f"{item}[]"
    return SCALAR_TYPES.get(kind, "unknown")


def union(parts: Iterable[str]) -> str:
    unique: list[str] = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    # unknown 包含任意值，保留它可避免生成冗余联合类型。
    if "unknown" in unique:
        return "unknown"
    if len(unique) == 1:
        return unique[0]
    return " | ".join(unique)


def object_type(schema: dict[str, Any]) -> str:
    members = object_members(schema)
    if not members:
        return "Record<string, unknown>"
    return "{ " + "; ".join(members) + " }"


def object_members(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    members: list[str] = []
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            marker = "" if name in required_names else "?"
            members.append(f"{property_name(name)}{marker}: {ts_type(child)}")
    additional = schema.get("additionalProperties")
    if additional is True:
        members.append("[key: string]: unknown")
    elif isinstance(additional, dict):
        members.append(f"[key: string]: {ts_type(additional)}")
    return members


def property_name(name: str) -> str:
    return name if IDENTIFIER.match(name) else json.dumps(name, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 FastAPI OpenAPI 文档生成 Web 端 TypeScript 类型")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出文件路径")
    parser.add_argument(
        "--check", action="store_true", help="校验已提交文件与生成结果一致，不一致时退出码为 1"
    )
    arguments = parser.parse_args(argv)
    output = arguments.output if arguments.output.is_absolute() else Path.cwd() / arguments.output
    if arguments.check and not output.is_file():
        print(f"类型文件不存在：{output}", file=sys.stderr)
        return 1
    content = render_types(openapi_document()).encode("utf-8")
    if arguments.check:
        if output.read_bytes() != content:
            print(
                f"类型文件与 OpenAPI 不一致：{output}；"
                "请运行 .venv/bin/python scripts/generate_web_types.py 重新生成",
                file=sys.stderr,
            )
            return 1
        print(f"类型文件与 OpenAPI 一致：{output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(f"已生成 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
