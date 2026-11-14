"""Native engine image diagnostics driven by the desktop host executable."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fm27lab.application.engine_config import validate_engine_root, validate_game_root

GAME_PLUGIN_RELATIVE = Path("fm_Data") / "Plugins" / "x86_64" / "game_plugin.dll"
HOST_RELATIVE = Path("fm27_native") / "FM27Simulator.exe"
ADAPTER_VERSION_RELATIVE = Path("fm27_native") / "adapter_version.json"
COMPATIBILITY_EVENT = "native_engine_compatibility"
FINGERPRINT_EVENT = "native_image_fingerprint"
DEFAULT_TIMEOUT_SECONDS = 30.0


class EngineDiagnoseError(ValueError):
    """Raised when the host cannot produce a usable compatibility diagnosis."""


@dataclass(frozen=True, slots=True)
class EngineDiagnosis:
    compatible: bool
    trial_allowed: bool
    reason: str | None
    adapter_version: str | None
    image_sha256: str | None


def diagnose_engine(
    engine_root: str | Path,
    game_root: str | Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    executable: Path | None = None,
) -> EngineDiagnosis:
    try:
        engine = validate_engine_root(engine_root)
        game = validate_game_root(game_root)
    except ValueError as error:
        raise EngineDiagnoseError(str(error)) from error
    host = Path(executable) if executable is not None else engine / HOST_RELATIVE
    if not host.is_file():
        raise EngineDiagnoseError(f"宿主程序不存在：{host}")
    plugin = game / GAME_PLUGIN_RELATIVE
    with tempfile.TemporaryDirectory(prefix="fm27lab-diagnose-") as directory:
        output = Path(directory) / "diagnosis.log"
        command = [*_executable_prefix(host), "--check-image", str(plugin), "--output", str(output)]
        try:
            completed = subprocess.run(
                command,
                cwd=str(engine),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise EngineDiagnoseError(f"引擎诊断超时：{timeout_seconds:g} 秒内未返回") from error
        text = completed.stdout or ""
        if output.is_file():
            text += "\n" + output.read_text(encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip()
            message = f"引擎诊断失败：宿主退出码 {completed.returncode}"
            raise EngineDiagnoseError(f"{message}；{detail}" if detail else message)
        events = _json_events(text)
    compatibility = _last_event(events, COMPATIBILITY_EVENT)
    if compatibility is None:
        raise EngineDiagnoseError("引擎诊断未返回兼容性声明")
    compatible = compatibility.get("compatible")
    trial_allowed = compatibility.get("trial_allowed", False)
    if not isinstance(compatible, bool) or not isinstance(trial_allowed, bool):
        raise EngineDiagnoseError("原生引擎兼容性声明无效")
    reason = compatibility.get("reason")
    fingerprint = _last_event(events, FINGERPRINT_EVENT)
    image_sha256 = None
    if fingerprint is not None and isinstance(fingerprint.get("sha256"), str):
        image_sha256 = fingerprint["sha256"]
    return EngineDiagnosis(
        compatible=compatible,
        trial_allowed=trial_allowed,
        reason=reason if isinstance(reason, str) else None,
        adapter_version=_adapter_version(engine),
        image_sha256=image_sha256,
    )


def _executable_prefix(host: Path) -> list[str]:
    if host.suffix.lower() == ".py":
        return [sys.executable, str(host)]
    return [str(host)]


def _json_events(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            value = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _last_event(events: list[dict[str, object]], name: str) -> dict[str, object] | None:
    found = None
    for event in events:
        if event.get("event") == name:
            found = event
    return found


def _adapter_version(engine_root: Path) -> str | None:
    path = engine_root / ADAPTER_VERSION_RELATIVE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("version"), str):
        return payload["version"]
    return None
