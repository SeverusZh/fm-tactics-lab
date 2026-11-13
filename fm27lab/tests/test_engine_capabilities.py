from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from fm27lab.adapters.engine_native.capabilities import parse_capabilities, plan_runtime
from fm27lab.ports.engine import EngineCapabilities, EnginePort, RuntimePlan

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INVALID_CAPABILITIES = "引擎能力声明无效"
COUNTED_SCOPE = "remaining_batch_lane"
FALLBACK_REASON = "counted_sessions_unavailable"
PROVENANCE_FIELDS = {
    "counted_sessions",
    "fallback_reason",
    "jobs_per_native_session",
    "session_scope",
    "capability_version",
}


def counted_capabilities() -> EngineCapabilities:
    return parse_capabilities(
        {
            "counted_sessions": True,
            "session_scope": COUNTED_SCOPE,
            "capability_version": 2,
        }
    )


def legacy_capabilities() -> EngineCapabilities:
    return parse_capabilities(None)


def test_parse_none_payload_falls_back_to_legacy_host():
    assert parse_capabilities(None) == EngineCapabilities(
        counted_sessions=False,
        jobs_per_session=64,
        session_scope=None,
        capability_version=None,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"protocol": 2, "max_jobs": 512, "execution_context_reset": True},
        {"jobs_per_session": 128, "capability_version": 3},
    ],
)
def test_parse_missing_counted_declaration_falls_back_to_legacy_host(payload):
    assert parse_capabilities(payload) == EngineCapabilities(
        counted_sessions=False,
        jobs_per_session=64,
        session_scope=None,
        capability_version=None,
    )


def test_parse_counted_declaration():
    assert parse_capabilities({"counted_sessions": True}) == EngineCapabilities(
        counted_sessions=True,
        jobs_per_session=None,
        session_scope=None,
        capability_version=None,
    )
    assert parse_capabilities(
        {
            "counted_sessions": True,
            "jobs_per_session": None,
            "session_scope": COUNTED_SCOPE,
            "capability_version": 2,
        }
    ) == EngineCapabilities(
        counted_sessions=True,
        jobs_per_session=None,
        session_scope=COUNTED_SCOPE,
        capability_version=2,
    )


def test_parse_non_counted_declaration():
    assert parse_capabilities({"counted_sessions": False}) == EngineCapabilities(
        counted_sessions=False,
        jobs_per_session=64,
        session_scope=None,
        capability_version=None,
    )
    assert parse_capabilities(
        {"counted_sessions": False, "jobs_per_session": 16, "capability_version": 1}
    ) == EngineCapabilities(
        counted_sessions=False,
        jobs_per_session=16,
        session_scope=None,
        capability_version=1,
    )


@pytest.mark.parametrize("value", [1, 0, "true", None, 1.0, [], {}])
def test_parse_rejects_non_boolean_counted_declaration(value):
    with pytest.raises(ValueError, match=INVALID_CAPABILITIES):
        parse_capabilities({"counted_sessions": value})


@pytest.mark.parametrize("value", [0, 4097, -1, True, False, "64", 64.0, [64]])
def test_parse_rejects_invalid_jobs_per_session(value):
    with pytest.raises(ValueError, match=INVALID_CAPABILITIES):
        parse_capabilities({"counted_sessions": True, "jobs_per_session": value})


@pytest.mark.parametrize("value", [1, 64, 4096])
def test_parse_accepts_jobs_per_session_range(value):
    capabilities = parse_capabilities({"counted_sessions": False, "jobs_per_session": value})
    assert capabilities.jobs_per_session == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capability_version", "2"),
        ("capability_version", 2.0),
        ("capability_version", True),
        ("capability_version", 0),
        ("session_scope", 2),
        ("session_scope", b"remaining_batch_lane"),
    ],
)
def test_parse_rejects_invalid_optional_declarations(field, value):
    with pytest.raises(ValueError, match=INVALID_CAPABILITIES):
        parse_capabilities({"counted_sessions": True, field: value})


@pytest.mark.parametrize(
    "payload",
    [[], "counted_sessions", 42, 3.5, object(), ("counted_sessions", True), True],
)
def test_parse_rejects_non_mapping_payload(payload):
    with pytest.raises(ValueError, match=INVALID_CAPABILITIES):
        parse_capabilities(payload)


@pytest.mark.parametrize(
    ("capabilities", "has_pool_variants", "has_experimental_execution", "mode", "jobs", "scope", "fallback"),
    [
        pytest.param(
            counted_capabilities(),
            True,
            True,
            "reused_pool_execution_worker",
            None,
            COUNTED_SCOPE,
            None,
            id="pool-experiment-counted",
        ),
        pytest.param(
            counted_capabilities(),
            False,
            True,
            "reused_execution_worker",
            None,
            COUNTED_SCOPE,
            None,
            id="experiment-counted",
        ),
        pytest.param(
            counted_capabilities(),
            True,
            False,
            "reused_worker",
            None,
            COUNTED_SCOPE,
            None,
            id="pool-counted",
        ),
        pytest.param(
            counted_capabilities(),
            False,
            False,
            "reused_worker",
            None,
            COUNTED_SCOPE,
            None,
            id="counted",
        ),
        pytest.param(
            legacy_capabilities(),
            True,
            True,
            "isolated_pool_execution_experiment",
            1,
            None,
            None,
            id="pool-experiment-legacy",
        ),
        pytest.param(
            legacy_capabilities(),
            False,
            True,
            "isolated_execution_experiment",
            1,
            None,
            None,
            id="experiment-legacy",
        ),
        pytest.param(
            legacy_capabilities(),
            True,
            False,
            "isolated_worker",
            64,
            None,
            FALLBACK_REASON,
            id="pool-legacy",
        ),
        pytest.param(
            legacy_capabilities(),
            False,
            False,
            "isolated_worker",
            64,
            None,
            FALLBACK_REASON,
            id="legacy",
        ),
    ],
)
def test_runtime_plan_matrix(
    capabilities,
    has_pool_variants,
    has_experimental_execution,
    mode,
    jobs,
    scope,
    fallback,
):
    plan = plan_runtime(
        capabilities,
        has_pool_variants=has_pool_variants,
        has_experimental_execution=has_experimental_execution,
    )
    assert isinstance(plan, RuntimePlan)
    assert plan.runtime_mode == mode
    assert plan.jobs_per_native_session == jobs
    assert plan.session_scope == scope
    assert plan.fallback_reason == fallback


@pytest.mark.parametrize(
    ("capabilities", "has_pool_variants", "has_experimental_execution"),
    [
        (counted_capabilities(), True, True),
        (counted_capabilities(), False, True),
        (counted_capabilities(), True, False),
        (counted_capabilities(), False, False),
        (legacy_capabilities(), True, True),
        (legacy_capabilities(), False, True),
        (legacy_capabilities(), True, False),
        (legacy_capabilities(), False, False),
    ],
)
def test_runtime_plan_provenance_is_complete(capabilities, has_pool_variants, has_experimental_execution):
    plan = plan_runtime(
        capabilities,
        has_pool_variants=has_pool_variants,
        has_experimental_execution=has_experimental_execution,
    )
    assert set(plan.provenance) == PROVENANCE_FIELDS
    assert plan.provenance["counted_sessions"] is capabilities.counted_sessions
    assert plan.provenance["fallback_reason"] == plan.fallback_reason
    assert plan.provenance["jobs_per_native_session"] == plan.jobs_per_native_session
    assert plan.provenance["session_scope"] == plan.session_scope
    assert plan.provenance["capability_version"] == capabilities.capability_version


def test_legacy_plan_records_fallback_provenance():
    plan = plan_runtime(
        legacy_capabilities(),
        has_pool_variants=False,
        has_experimental_execution=False,
    )
    assert plan.fallback_reason == FALLBACK_REASON
    assert plan.provenance == {
        "counted_sessions": False,
        "fallback_reason": FALLBACK_REASON,
        "jobs_per_native_session": 64,
        "session_scope": None,
        "capability_version": None,
    }


def test_counted_plan_provenance_keeps_capability_version():
    plan = plan_runtime(
        counted_capabilities(),
        has_pool_variants=False,
        has_experimental_execution=False,
    )
    assert plan.provenance["counted_sessions"] is True
    assert plan.provenance["fallback_reason"] is None
    assert plan.provenance["capability_version"] == 2


def test_isolated_plan_keeps_declared_session_budget():
    capabilities = parse_capabilities({"counted_sessions": False, "jobs_per_session": 16})
    plan = plan_runtime(
        capabilities,
        has_pool_variants=False,
        has_experimental_execution=False,
    )
    assert plan.jobs_per_native_session == 16


def test_plan_rejects_invalid_capabilities():
    with pytest.raises(ValueError, match=INVALID_CAPABILITIES):
        plan_runtime("counted", has_pool_variants=False, has_experimental_execution=False)


def test_engine_capabilities_is_frozen():
    capabilities = legacy_capabilities()
    with pytest.raises(dataclasses.FrozenInstanceError):
        capabilities.counted_sessions = True


def test_runtime_plan_is_frozen():
    plan = plan_runtime(legacy_capabilities(), has_pool_variants=False, has_experimental_execution=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.runtime_mode = "reused_worker"


class FakeEngine:
    def __init__(self):
        self.results: list[Any] = []
        self.progress: list[Any] = []
        self.cancelled = False

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(counted_sessions=False, jobs_per_session=64)

    def run_batch(self, tasks, on_result, on_progress):
        for task in tasks:
            on_progress([{"seed": task["seed"]}])
            on_result({"seed": task["seed"]})
            self.results.append(task["seed"])

    def cancel(self) -> None:
        self.cancelled = True


def test_engine_port_is_structurally_satisfied_by_fake():
    engine: EnginePort = FakeEngine()
    assert isinstance(engine, EnginePort)
    assert engine.capabilities() == EngineCapabilities(counted_sessions=False, jobs_per_session=64)
    results: list[Any] = []
    progress: list[Any] = []
    engine.run_batch([{"seed": 1}, {"seed": 2}], results.append, progress.append)
    assert results == [{"seed": 1}, {"seed": 2}]
    assert progress == [[{"seed": 1}], [{"seed": 2}]]
    engine.cancel()
    assert engine.cancelled
    assert not isinstance(object(), EnginePort)


def test_engine_port_rejects_incomplete_implementation():
    class Incomplete:
        def capabilities(self) -> EngineCapabilities:
            return EngineCapabilities(counted_sessions=False, jobs_per_session=64)

    assert not isinstance(Incomplete(), EnginePort)


def test_ports_layer_does_not_import_adapters():
    program = (
        "import sys\n"
        "import fm27lab.ports.engine\n"
        "loaded = [name for name in sys.modules if name.startswith('fm27lab.adapters')]\n"
        "assert not loaded, loaded\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
