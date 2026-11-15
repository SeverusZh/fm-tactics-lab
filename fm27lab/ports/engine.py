"""Engine port contracts and negotiated runtime plan value objects."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class EngineCapabilities:
    """Capabilities declared by a native engine host during negotiation.

    ``counted_sessions`` is true for hosts that reuse one native session across a
    batch, release the per-match object and clear the execution context after
    every match. ``jobs_per_session`` is the match budget of an isolated session,
    or ``None`` when the host reuses the remaining batch lane. ``session_scope``
    names the reuse scope; ``capability_version`` versions the handshake
    declaration.
    """

    counted_sessions: bool
    jobs_per_session: int | None = None
    session_scope: str | None = None
    capability_version: int | None = None


@dataclass(frozen=True)
class RuntimePlan:
    """Scheduling decision derived from negotiated capabilities for one batch.

    ``runtime_mode`` is the upstream v1112 worker mode name. ``provenance`` is the
    flat record persisted with the job so later inspection can explain the
    chosen session policy.
    """

    runtime_mode: str
    jobs_per_native_session: int | None
    session_scope: str | None
    fallback_reason: str | None
    provenance: dict[str, Any]


@runtime_checkable
class EnginePort(Protocol):
    """Native match engine boundary implemented by engine adapters.

    The application layer only submits batches and observes callbacks; session
    negotiation, worker reuse, cancellation and result validation stay inside
    the adapter. Callbacks may run on worker threads, so implementations
    serialize them before forwarding.
    """

    def capabilities(self) -> EngineCapabilities:
        """Return the capabilities negotiated with this engine host."""
        ...

    def run_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        on_result: Callable[[Mapping[str, Any]], None],
        on_progress: Callable[[Sequence[Mapping[str, Any]]], None],
    ) -> None:
        """Run all tasks and report every accepted or failed match through ``on_result``.

        ``on_progress`` receives the currently active worker descriptors and may
        be called repeatedly while the batch runs. The call returns when the
        batch finishes; cancellation is requested through :meth:`cancel`.
        """
        ...

    def cancel(self) -> None:
        """Request cancellation of the running batch; accepted results stay valid."""
        ...
