from __future__ import annotations

import getpass
import json
import os
import socket
import subprocess
from datetime import datetime
from pathlib import Path

import uvicorn

import fm27lab
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.config import Settings
from fm27lab.interfaces.http.app import create_app


def endpoint_payload(settings: Settings, port: int) -> dict:
    return {
        "schema": 1,
        "api": fm27lab.API_VERSION,
        "url": f"http://127.0.0.1:{port}",
        "port": port,
        "token": settings.token,
        "pid": os.getpid(),
        "data_dir": str(settings.data_dir),
        "engine_root": str(settings.engine_root) if settings.engine_root else None,
        "created_at": datetime.now().astimezone().isoformat(),
    }


def write_endpoint(settings: Settings, port: int) -> None:
    settings.ensure_dirs()
    target = settings.endpoint_path
    temporary = target.with_name(target.name + ".tmp")
    payload = endpoint_payload(settings, port)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    try:
        restrict_permissions(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def restrict_permissions(path: Path) -> None:
    if os.name != "nt":
        return
    user = os.environ.get("USERNAME") or getpass.getuser()
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
        check=True,
        capture_output=True,
        text=True,
    )


def clear_endpoint(settings: Settings) -> None:
    try:
        settings.endpoint_path.unlink()
    except FileNotFoundError:
        pass


def run(settings: Settings) -> int:
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    server_state: dict[str, uvicorn.Server | None] = {"server": None}

    def shutdown() -> None:
        server = server_state["server"]
        if server is not None:
            server.should_exit = True

    app = create_app(settings, database, shutdown=shutdown)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((settings.host, settings.port))
    listener.listen(128)
    try:
        port = listener.getsockname()[1]
        write_endpoint(settings, port)
        print(json.dumps({"event": "ready", "port": port, "pid": os.getpid()}), flush=True)
        config = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off")
        server = uvicorn.Server(config)
        server_state["server"] = server
        server.run(sockets=[listener])
    finally:
        clear_endpoint(settings)
        listener.close()
    return 0
