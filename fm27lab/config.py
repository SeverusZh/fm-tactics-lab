from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import fm27lab

LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


def _restrict_directory(path: Path) -> None:
    if os.name == "nt":
        return
    path.chmod(0o700)


def default_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "FM27TacticsDesktop"
    return Path.home() / ".fm27lab"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    token: str = field(repr=False)
    engine_root: Path | None = None
    host: str = "127.0.0.1"
    port: int = 0
    dev: bool = False
    version: str = field(default=fm27lab.__version__)

    def __post_init__(self) -> None:
        if not self.token or not self.token.isascii():
            raise ValueError("token must be a non-empty ASCII string")
        if self.host not in LOOPBACK_HOSTS:
            raise ValueError(f"host must be a loopback address: {sorted(LOOPBACK_HOSTS)}")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if not self.data_dir.is_absolute():
            raise ValueError("data_dir must be an absolute path")

    @classmethod
    def create(
        cls,
        data_dir: Path,
        engine_root: Path | None = None,
        token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        dev: bool = False,
    ) -> Settings:
        raw = str(data_dir).strip()
        if not raw or raw == ".":
            raise ValueError("data_dir must not be empty or the current directory")
        resolved = Path(data_dir).expanduser().resolve()
        if resolved == Path.cwd().resolve():
            raise ValueError("data_dir must not be the current working directory")
        if token is not None and not token:
            raise ValueError("token must not be empty")
        return cls(
            data_dir=resolved,
            engine_root=Path(engine_root).expanduser().resolve() if engine_root is not None else None,
            token=token or secrets.token_hex(32),
            host=host,
            port=port,
            dev=dev,
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if env is None else env
        raw_data_dir = values.get("FM27LAB_DATA")
        if raw_data_dir is not None and not raw_data_dir.strip():
            raise ValueError("FM27LAB_DATA must not be empty")
        data_dir = Path(raw_data_dir) if raw_data_dir is not None else default_data_dir()
        engine_root = values.get("FM27_ENGINE_ROOT")
        token = values.get("FM27LAB_TOKEN") or None
        port = int(values.get("FM27LAB_PORT", "0"))
        return cls.create(
            data_dir=data_dir,
            engine_root=Path(engine_root) if engine_root else None,
            token=token,
            host=values.get("FM27LAB_HOST", "127.0.0.1"),
            port=port,
            dev=values.get("FM27LAB_DEV") == "1",
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "fm27lab.db"

    @property
    def endpoint_path(self) -> Path:
        return self.data_dir / "agent" / "endpoint.json"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.endpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self.data_dir, self.endpoint_path.parent, self.exports_dir):
            _restrict_directory(directory)
