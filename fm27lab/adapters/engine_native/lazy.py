"""Lazy native engine construction.

The production composition root builds the engine port without spawning the
native host: the first capability probe or batch run creates it, and worker
counts configured before that point are applied to the constructor.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from fm27lab.adapters.engine_native.host import NativeEngineHost
from fm27lab.domain.concurrency import validate_workers
from fm27lab.ports.engine import EngineCapabilities

DEFAULT_WORKERS = 1


class LazyNativeEngine:
    """Engine port that defers native host construction until first use."""

    def __init__(
        self,
        root: Path,
        work_dir: Path,
        *,
        game_root: Path | None = None,
        factory: Callable[..., NativeEngineHost] = NativeEngineHost,
    ) -> None:
        self._root = root
        self._work_dir = work_dir
        self._game_root = game_root
        self._factory = factory
        self._workers = DEFAULT_WORKERS
        self._host: NativeEngineHost | None = None
        self._lock = threading.Lock()

    def capabilities(self) -> EngineCapabilities:
        return self._ensure_host().capabilities()

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: Callable[[Mapping[str, Any]], None],
        on_progress: Callable[[Sequence[Mapping[str, Any]]], None],
    ) -> None:
        self._ensure_host().run_batch(tasks, on_result, on_progress)

    def cancel(self) -> None:
        host = self._host
        if host is not None:
            host.cancel()

    def configure_workers(self, workers: int) -> None:
        validated = validate_workers(workers)
        with self._lock:
            self._workers = validated
            host = self._host
        if host is not None:
            host.configure_workers(validated)

    def _ensure_host(self) -> NativeEngineHost:
        host = self._host
        if host is None:
            with self._lock:
                host = self._host
                if host is None:
                    options: dict[str, object] = {"workers": self._workers}
                    if self._game_root is not None:
                        options["game_root"] = self._game_root
                    host = self._factory(self._root, self._work_dir, **options)
                    self._host = host
        return host
