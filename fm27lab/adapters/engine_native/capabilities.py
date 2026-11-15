"""Native host capability negotiation and batch runtime planning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fm27lab.ports.engine import EngineCapabilities, RuntimePlan

LEGACY_JOBS_PER_SESSION = 64
MIN_JOBS_PER_SESSION = 1
MAX_JOBS_PER_SESSION = 4096
MAX_NATIVE_JOBS = 1000000
REAL_PROTOCOL_VERSION = 2
COUNTED_SESSION_SCOPE = "remaining_batch_lane"
COUNTED_SESSIONS_UNAVAILABLE = "counted_sessions_unavailable"
INVALID_CAPABILITIES = "引擎能力声明无效"


def _jobs_per_session(payload: Mapping[str, Any], counted_sessions: bool) -> int | None:
    if "jobs_per_session" not in payload:
        return None if counted_sessions else LEGACY_JOBS_PER_SESSION
    value = payload["jobs_per_session"]
    if value is None:
        return None
    if type(value) is not int or not MIN_JOBS_PER_SESSION <= value <= MAX_JOBS_PER_SESSION:
        raise ValueError(INVALID_CAPABILITIES)
    return value


def _session_scope(payload: Mapping[str, Any]) -> str | None:
    if "session_scope" not in payload:
        return None
    value = payload["session_scope"]
    if not isinstance(value, str) or not value:
        raise ValueError(INVALID_CAPABILITIES)
    return value


def _capability_version(payload: Mapping[str, Any]) -> int | None:
    if "capability_version" not in payload:
        return None
    value = payload["capability_version"]
    if type(value) is not int or value < 1:
        raise ValueError(INVALID_CAPABILITIES)
    return value


def _legacy_capabilities() -> EngineCapabilities:
    return EngineCapabilities(
        counted_sessions=False,
        jobs_per_session=LEGACY_JOBS_PER_SESSION,
        session_scope=None,
        capability_version=None,
    )


def _native_counted_capabilities(payload: Mapping[str, Any]) -> EngineCapabilities | None:
    """Interpret the real native protocol declaration; None means a legacy host.

    The native host declares protocol 2 sessions only when it can reset the
    execution context and release per-match resources after every match.
    """
    if payload.get("protocol") != REAL_PROTOCOL_VERSION:
        return None
    maximum = payload.get("max_jobs")
    if type(maximum) is not int or not MIN_JOBS_PER_SESSION <= maximum <= MAX_NATIVE_JOBS:
        return None
    if payload.get("execution_context_reset") is not True:
        return None
    if payload.get("per_match_resource_release") is not True:
        return None
    return EngineCapabilities(
        counted_sessions=True,
        jobs_per_session=None,
        session_scope=COUNTED_SESSION_SCOPE,
        capability_version=REAL_PROTOCOL_VERSION,
    )


def parse_capabilities(payload: Mapping[str, Any] | None) -> EngineCapabilities:
    """Parse a host capability declaration.

    Two declarations are understood. The desktop worker protocol uses the
    protocol, max_jobs, execution_context_reset and per_match_resource_release
    fields and opts into counted sessions only when all four fields pass. The
    earlier counted_sessions declaration is authoritative and strictly
    validated. A missing, unknown or unusable declaration describes a legacy
    host: isolated sessions rebuilt after 64 matches.
    """
    if payload is None:
        return _legacy_capabilities()
    if not isinstance(payload, Mapping):
        raise ValueError(INVALID_CAPABILITIES)
    if "counted_sessions" not in payload:
        native = _native_counted_capabilities(payload)
        return native if native is not None else _legacy_capabilities()
    counted_sessions = payload["counted_sessions"]
    if type(counted_sessions) is not bool:
        raise ValueError(INVALID_CAPABILITIES)
    return EngineCapabilities(
        counted_sessions=counted_sessions,
        jobs_per_session=_jobs_per_session(payload, counted_sessions),
        session_scope=_session_scope(payload),
        capability_version=_capability_version(payload),
    )


def plan_runtime(
    capabilities: EngineCapabilities,
    *,
    has_pool_variants: bool,
    has_experimental_execution: bool,
) -> RuntimePlan:
    """Resolve the worker mode and session policy for one submitted batch.

    Counted hosts reuse a worker for the remaining batch lane; hosts without
    the counted-session capability keep the legacy isolated policy, and
    execution-force experiments always isolate a single match per session.
    """
    if not isinstance(capabilities, EngineCapabilities):
        raise ValueError(INVALID_CAPABILITIES)
    counted_sessions = capabilities.counted_sessions
    if has_experimental_execution:
        if counted_sessions:
            runtime_mode = "reused_pool_execution_worker" if has_pool_variants else "reused_execution_worker"
            jobs_per_native_session = None
            session_scope = capabilities.session_scope or COUNTED_SESSION_SCOPE
            fallback_reason = None
        else:
            runtime_mode = (
                "isolated_pool_execution_experiment" if has_pool_variants else "isolated_execution_experiment"
            )
            jobs_per_native_session = 1
            session_scope = None
            fallback_reason = None
    elif counted_sessions:
        runtime_mode = "reused_worker"
        jobs_per_native_session = None
        session_scope = capabilities.session_scope or COUNTED_SESSION_SCOPE
        fallback_reason = None
    else:
        runtime_mode = "isolated_worker"
        jobs_per_native_session = capabilities.jobs_per_session or LEGACY_JOBS_PER_SESSION
        session_scope = None
        fallback_reason = COUNTED_SESSIONS_UNAVAILABLE
    return RuntimePlan(
        runtime_mode=runtime_mode,
        jobs_per_native_session=jobs_per_native_session,
        session_scope=session_scope,
        fallback_reason=fallback_reason,
        provenance={
            "counted_sessions": counted_sessions,
            "fallback_reason": fallback_reason,
            "jobs_per_native_session": jobs_per_native_session,
            "session_scope": session_scope,
            "capability_version": capabilities.capability_version,
        },
    )
