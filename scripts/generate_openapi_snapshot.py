"""导出 FastAPI OpenAPI 契约快照并支持一致性校验。"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "docs" / "openapi.json"


def openapi_document() -> dict[str, Any]:
    from fm27lab.adapters.storage_sqlite.db import Database
    from fm27lab.config import Settings
    from fm27lab.interfaces.http.app import create_app

    with tempfile.TemporaryDirectory(prefix="fm27lab-openapi-") as directory:
        settings = Settings.create(data_dir=Path(directory))
        database = Database(settings.database_path)
        return create_app(settings, database).openapi()


def render_snapshot(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _operations(document: dict[str, Any]) -> set[tuple[str, str]]:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return set()
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        if isinstance(operations, dict)
        for method in operations
    }


def _preview(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."


def _first_difference(current: Any, expected: Any, pointer: str) -> str | None:
    if type(current) is not type(expected):
        return f"{pointer}（类型 {type(current).__name__} → {type(expected).__name__}）"
    if isinstance(current, dict):
        current_keys = set(current)
        expected_keys = set(expected)
        if current_keys != expected_keys:
            missing = sorted(expected_keys - current_keys)[:5]
            extra = sorted(current_keys - expected_keys)[:5]
            details = []
            if missing:
                details.append("缺少 " + ", ".join(missing))
            if extra:
                details.append("多余 " + ", ".join(extra))
            return f"{pointer}（{'; '.join(details)}）"
        for key in sorted(current):
            difference = _first_difference(current[key], expected[key], f"{pointer}/{key}")
            if difference is not None:
                return difference
        return None
    if isinstance(current, list):
        if len(current) != len(expected):
            return f"{pointer}（长度 {len(current)} → {len(expected)}）"
        for index, (left, right) in enumerate(zip(current, expected, strict=True)):
            difference = _first_difference(left, right, f"{pointer}/{index}")
            if difference is not None:
                return difference
        return None
    if current != expected:
        return f"{pointer}（{_preview(current)} → {_preview(expected)}）"
    return None


def diff_summary(committed: bytes, generated: bytes) -> str:
    try:
        current = json.loads(committed.decode("utf-8"))
        expected = json.loads(generated.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return f"快照内容无法解析：{error}"
    if not isinstance(current, dict) or not isinstance(expected, dict):
        return "快照内容不是 JSON 对象"
    lines: list[str] = []
    missing = sorted(_operations(expected) - _operations(current))
    extra = sorted(_operations(current) - _operations(expected))
    if missing:
        lines.append("缺少操作：" + ", ".join(f"{method} {path}" for method, path in missing[:5]))
    if extra:
        lines.append("多余操作：" + ", ".join(f"{method} {path}" for method, path in extra[:5]))
    difference = _first_difference(current, expected, "#")
    if difference is not None:
        lines.append("首个不一致字段：" + difference)
    return "；".join(lines) or "内容一致但字节不同（格式或排序漂移）"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 OpenAPI 契约快照并校验一致性")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="快照文件路径")
    parser.add_argument("--check", action="store_true", help="校验已提交快照与当前应用一致，不一致时退出码为 1")
    arguments = parser.parse_args(argv)
    output = arguments.output if arguments.output.is_absolute() else Path.cwd() / arguments.output
    if arguments.check and not output.is_file():
        print(f"OpenAPI 快照不存在：{output}", file=sys.stderr)
        return 1
    content = render_snapshot(openapi_document()).encode("utf-8")
    if arguments.check:
        committed = output.read_bytes()
        if committed != content:
            print(f"OpenAPI 快照与当前应用不一致：{output}", file=sys.stderr)
            print(diff_summary(committed, content), file=sys.stderr)
            print("请运行 .venv/bin/python scripts/generate_openapi_snapshot.py 重新生成", file=sys.stderr)
            return 1
        print(f"OpenAPI 快照一致：{output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(f"已生成 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
