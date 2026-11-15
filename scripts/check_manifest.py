from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from export_source import source_files  # noqa: E402


def main() -> int:
    expected = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    actual = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files(ROOT)
    }
    missing = sorted(set(actual) - set(expected))
    extra = sorted(set(expected) - set(actual))
    changed = sorted(key for key in set(actual) & set(expected) if actual[key] != expected[key])
    if missing or extra or changed:
        print(json.dumps({"missing": missing, "extra": extra, "changed": changed}, indent=2))
        return 1
    print(f"manifest matches {len(actual)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
