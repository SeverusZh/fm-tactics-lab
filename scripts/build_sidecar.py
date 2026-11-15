from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "sidecar-dist"
WORK = ROOT / "build" / "sidecar"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is required: python -m pip install pyinstaller", file=sys.stderr)
        return 2
    migrations = ROOT / "fm27lab" / "adapters" / "storage_sqlite" / "migrations"
    if not migrations.is_dir():
        print(f"missing migrations: {migrations}", file=sys.stderr)
        return 2
    DIST.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "fm27lab-sidecar",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
        "--paths",
        str(ROOT),
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "fastapi",
        "--add-data",
        f"{migrations}{os.pathsep}fm27lab/adapters/storage_sqlite/migrations",
        str(ROOT / "fm27lab" / "sidecar_main.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    executable = DIST / "fm27lab-sidecar" / (
        "fm27lab-sidecar.exe" if os.name == "nt" else "fm27lab-sidecar"
    )
    if not executable.exists():
        print(f"sidecar executable was not produced: {executable}", file=sys.stderr)
        return 1
    print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
