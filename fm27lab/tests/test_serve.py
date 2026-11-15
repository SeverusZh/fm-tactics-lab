from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def request(url: str, method: str = "GET", token: str = "", origin: str | None = None) -> tuple[int, dict]:
    data = b"" if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def test_serve_prints_ready_writes_endpoint_and_shuts_down(tmp_path: Path):
    token = "d" * 64
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "fm27lab",
            "serve",
            "--data-dir",
            str(tmp_path),
            "--token",
            token,
            "--port",
            "0",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT), "FM27LAB_DEV": "1"},
    )
    try:
        line = process.stdout.readline().strip()
        ready = json.loads(line)
        assert ready["event"] == "ready"
        port = ready["port"]
        assert 1 <= port <= 65535
        endpoint_path = tmp_path / "agent" / "endpoint.json"
        endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
        assert endpoint["port"] == port
        assert endpoint["token"] == token
        cors = request(f"http://127.0.0.1:{port}/api/health", origin="http://localhost:1420")
        assert cors[0] == 200
        if os.name != "nt":
            assert endpoint_path.stat().st_mode & 0o777 == 0o600
        else:
            acl = subprocess.run(
                ["icacls", str(endpoint_path)], check=True, capture_output=True, text=True
            ).stdout
            assert os.environ.get("USERNAME", "") in acl

        status, body = request(f"http://127.0.0.1:{port}/api/health")
        assert status == 200
        assert body["database"] == "ready"
        denied, _ = request(f"http://127.0.0.1:{port}/api/shutdown", "POST")
        assert denied == 401
        accepted, body = request(f"http://127.0.0.1:{port}/api/shutdown", "POST", token)
        assert accepted == 202
        assert body["status"] == "shutting_down"
        process.wait(timeout=10)
        assert process.returncode == 0
        assert not (tmp_path / "agent" / "endpoint.json").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
