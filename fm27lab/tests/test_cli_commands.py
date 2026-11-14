from __future__ import annotations

import base64
import contextlib
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest
from typer.testing import CliRunner

import fm27lab
import fm27lab.cli as cli
from fm27lab.adapters.fmf import FmfCodec
from fm27lab.client import SidecarError
from fm27lab.tests.test_http_drafts import scenario as draft_scenario

TOKEN = "token-must-not-leak-2f8a"
GIB = 1024**3


class FakeClient:
    def __init__(self, responses=None, error=None, download=None):
        self.responses = list(responses or [])
        self.error = error
        self.download = download
        self.calls = []

    def _record(self, method, path, body, query):
        self.calls.append({"method": method, "path": path, "body": body, "query": query})
        if self.error is not None:
            raise self.error

    def request_json(self, method, path, *, body=None, query=None):
        self._record(method, path, body, query)
        if not self.responses:
            raise AssertionError(f"未预期的请求：{method} {path}")
        return self.responses.pop(0)

    def request_bytes(self, method, path, *, body=None, query=None):
        self._record(method, path, body, query)
        payload = self.download if self.download is not None else b""
        return payload, {"etag": '"unused"'}


@pytest.fixture(autouse=True)
def fake_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FM27LAB_DATA", str(tmp_path))
    monkeypatch.delenv("FM27LAB_TOKEN", raising=False)
    return tmp_path


def invoke(monkeypatch, args, responses=None, error=None, download=None):
    fake = FakeClient(responses, error, download)
    monkeypatch.setattr(cli, "_client_for", lambda data_dir: fake)
    result = CliRunner().invoke(cli.app, args)
    return result, fake


def parse_output(result):
    return json.loads(result.stdout)


def write_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def encode_base64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def test_root_help_lists_command_groups():
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0, result.output
    for name in (
        "version",
        "serve",
        "pools",
        "drafts",
        "jobs",
        "saves",
        "artifacts",
        "settings",
        "concurrency",
        "experiments",
        "catalog",
        "results",
        "system",
    ):
        assert name in result.stdout, name


def test_pools_help_lists_crud_commands():
    result = CliRunner().invoke(cli.app, ["pools", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("list", "get", "create", "delete"):
        assert name in result.stdout, name


def test_drafts_help_lists_crud_commands():
    result = CliRunner().invoke(cli.app, ["drafts", "--help"])
    assert result.exit_code == 0, result.output
    for name in (
        "list",
        "get",
        "create",
        "update",
        "delete",
        "attributes",
        "export-fmf",
        "import-fmf",
        "import-fmf-file",
        "apply-roster",
        "undo-roster",
    ):
        assert name in result.stdout, name


def test_jobs_help_lists_lifecycle_commands():
    result = CliRunner().invoke(cli.app, ["jobs", "--help"])
    assert result.exit_code == 0, result.output
    for name in (
        "list",
        "get",
        "create",
        "update",
        "cancel",
        "delete",
        "runs",
        "summary",
        "batch-action",
        "batch-delete",
        "export",
        "pool-summary",
    ):
        assert name in result.stdout, name


def test_saves_help_lists_lifecycle_commands():
    result = CliRunner().invoke(cli.app, ["saves", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("list", "get", "create", "update", "delete", "import", "import-file", "squad"):
        assert name in result.stdout, name


def test_artifacts_help_lists_commands():
    result = CliRunner().invoke(cli.app, ["artifacts", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("list", "get", "content", "create", "delete"):
        assert name in result.stdout, name


def test_settings_help_lists_commands():
    result = CliRunner().invoke(cli.app, ["settings", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("list", "get", "put", "delete"):
        assert name in result.stdout, name


def test_concurrency_help_lists_check_command():
    result = CliRunner().invoke(cli.app, ["concurrency", "--help"])
    assert result.exit_code == 0, result.output
    assert "check" in result.stdout


def test_experiments_help_lists_commands():
    result = CliRunner().invoke(cli.app, ["experiments", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("submit", "start", "cancel", "resume"):
        assert name in result.stdout, name


def test_catalog_help_lists_show_command():
    result = CliRunner().invoke(cli.app, ["catalog", "--help"])
    assert result.exit_code == 0, result.output
    assert "show" in result.stdout


def test_version_command_is_preserved():
    result = CliRunner().invoke(cli.app, ["version"])
    assert result.exit_code == 0, result.output
    assert fm27lab.__version__ in result.stdout


def test_pools_list_passes_pagination_and_outputs_json(monkeypatch):
    payload = {"items": [{"id": "p1"}], "total": 1, "next_offset": None}
    result, fake = invoke(monkeypatch, ["pools", "list", "--limit", "3", "--offset", "6"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "GET", "path": "/api/pools", "body": None, "query": {"limit": 3, "offset": 6}}
    ]


def test_pools_list_uses_route_pagination_defaults(monkeypatch):
    payload = {"items": [], "total": 0, "next_offset": None}
    result, fake = invoke(monkeypatch, ["pools", "list"], [payload])
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["query"] == {"limit": 128, "offset": 0}


def test_pools_get_requests_entry_by_id(monkeypatch):
    payload = {"id": "p1", "name": "角球"}
    result, fake = invoke(monkeypatch, ["pools", "get", "p1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [{"method": "GET", "path": "/api/pools/p1", "body": None, "query": None}]


def test_pools_create_posts_full_body(monkeypatch):
    tactic = {"tactic_name": "角球", "mentality": 3}
    roster = {"club_uid": 7}
    created = {"id": "p1", "name": "角球", "weight": 2, "tactic": tactic, "roster": roster}
    result, fake = invoke(
        monkeypatch,
        [
            "pools",
            "create",
            "--name",
            "角球",
            "--tactic",
            json.dumps(tactic, ensure_ascii=False),
            "--weight",
            "2",
            "--roster",
            json.dumps(roster),
            "--id",
            "p1",
        ],
        [created],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == created
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/api/pools")
    assert call["body"] == {"name": "角球", "weight": 2, "tactic": tactic, "roster": roster, "id": "p1"}


def test_pools_create_omits_optional_body_fields(monkeypatch):
    result, fake = invoke(monkeypatch, ["pools", "create", "--name", "X", "--tactic", "{}"], [{"id": "p1"}])
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {"name": "X", "weight": 1, "tactic": {}}


def test_pools_delete_reports_deleted(monkeypatch):
    result, fake = invoke(monkeypatch, ["pools", "delete", "p1"], [{}])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == {"deleted": True}
    assert fake.calls == [{"method": "DELETE", "path": "/api/pools/p1", "body": None, "query": None}]


def test_drafts_list_passes_pagination(monkeypatch):
    payload = {"items": [], "total": 0, "next_offset": None}
    result, fake = invoke(monkeypatch, ["drafts", "list", "--limit", "2"], [payload])
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["query"] == {"limit": 2, "offset": 0}


def test_drafts_get_requests_draft_by_id(monkeypatch):
    payload = {"id": "d1", "name": "草案", "scenario": {}}
    result, fake = invoke(monkeypatch, ["drafts", "get", "d1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls[0]["path"] == "/api/drafts/d1"


def test_drafts_create_reads_scenario_from_file(monkeypatch, fake_data_dir: Path):
    scenario = {"home": {"name": "主队"}}
    scenario_path = fake_data_dir / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")
    result, fake = invoke(
        monkeypatch,
        ["drafts", "create", "--name", "草案", "--scenario", f"@{scenario_path}"],
        [{"id": "d1"}],
    )
    assert result.exit_code == 0, result.output
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/api/drafts")
    assert call["body"] == {"name": "草案", "scenario": scenario}


def test_drafts_update_patches_only_given_fields(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["drafts", "update", "d1", "--name", "新名称", "--scenario", '{"a":1}'],
        [{"id": "d1"}],
    )
    assert result.exit_code == 0, result.output
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("PATCH", "/api/drafts/d1")
    assert call["body"] == {"name": "新名称", "scenario": {"a": 1}}


def test_drafts_delete_reports_deleted(monkeypatch):
    result, fake = invoke(monkeypatch, ["drafts", "delete", "d1"], [{}])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == {"deleted": True}
    assert fake.calls[0]["method"] == "DELETE"
    assert fake.calls[0]["path"] == "/api/drafts/d1"


def test_jobs_list_passes_status_and_pagination(monkeypatch):
    payload = {"items": [], "total": 0, "next_offset": None}
    result, fake = invoke(
        monkeypatch,
        ["jobs", "list", "--status", "running", "--limit", "10", "--offset", "20"],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["query"] == {"status": "running", "limit": 10, "offset": 20}


def test_jobs_list_uses_route_pagination_defaults(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "list"], [{"items": []}])
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["query"] == {"status": None, "limit": 50, "offset": 0}


def test_jobs_get_requests_job_by_id(monkeypatch):
    payload = {"id": "j1", "status": "running"}
    result, fake = invoke(monkeypatch, ["jobs", "get", "j1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls[0]["path"] == "/api/jobs/j1"


def test_jobs_create_posts_full_body(monkeypatch):
    config = {"seeds": [1, 2, 3]}
    result, fake = invoke(
        monkeypatch,
        [
            "jobs",
            "create",
            "--kind",
            "experiment",
            "--name",
            "批次",
            "--config",
            json.dumps(config),
            "--workers",
            "8",
            "--total",
            "100",
        ],
        [{"id": "j1"}],
    )
    assert result.exit_code == 0, result.output
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/api/jobs")
    assert call["body"] == {
        "kind": "experiment",
        "name": "批次",
        "config": config,
        "workers": 8,
        "total": 100,
    }


def test_jobs_create_defaults(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "create", "--kind", "experiment"], [{"id": "j1"}])
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {"kind": "experiment", "config": {}, "workers": 1, "total": 0}


def test_jobs_update_patches_only_given_fields(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "jobs",
            "update",
            "j1",
            "--status",
            "running",
            "--completed",
            "3",
            "--summary",
            '{"wins":3}',
        ],
        [{"id": "j1"}],
    )
    assert result.exit_code == 0, result.output
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("PATCH", "/api/jobs/j1")
    assert call["body"] == {"status": "running", "completed": 3, "summary": {"wins": 3}}


def test_jobs_cancel_posts_cancel_route(monkeypatch):
    payload = {"id": "j1", "status": "cancelled"}
    result, fake = invoke(monkeypatch, ["jobs", "cancel", "j1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/api/jobs/j1/cancel")
    assert call["body"] is None


def test_jobs_delete_reports_deleted(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "delete", "j1"], [{}])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == {"deleted": True}
    assert fake.calls[0]["path"] == "/api/jobs/j1"


def test_jobs_runs_passes_pagination(monkeypatch):
    payload = {"items": [{"seed": 1}], "total": 1, "next_offset": None}
    result, fake = invoke(monkeypatch, ["jobs", "runs", "j1", "--limit", "10", "--offset", "20"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls[0]["path"] == "/api/jobs/j1/runs"
    assert fake.calls[0]["query"] == {"limit": 10, "offset": 20}


def test_jobs_runs_uses_route_pagination_defaults(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "runs", "j1"], [{"items": []}])
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["query"] == {"limit": 50, "offset": 0}


def test_jobs_summary_calls_results_route_with_default_side(monkeypatch):
    payload = {
        "job": {
            "id": "j1",
            "kind": "experiment",
            "status": "completed",
            "name": "批次",
            "config": {"seeds": [1]},
            "summary": {},
            "workers": 8,
            "total": 100,
            "completed": 100,
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": None,
            "finished_at": None,
        },
        "metrics": {"n": 100, "wins": 60, "draws": 20, "losses": 20},
        "paired": {"n": 0, "goal_difference_delta": None},
    }
    result, fake = invoke(monkeypatch, ["jobs", "summary", "j1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "GET", "path": "/api/jobs/j1/summary", "body": None, "query": {"side": 0}}
    ]


def test_jobs_summary_forwards_side_option(monkeypatch):
    payload = {
        "job": {"id": "j1"},
        "metrics": None,
        "paired": {"n": 0, "goal_difference_delta": None},
    }
    result, fake = invoke(monkeypatch, ["jobs", "summary", "j1", "--side", "1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls[0]["path"] == "/api/jobs/j1/summary"
    assert fake.calls[0]["query"] == {"side": 1}


def test_jobs_summary_rejects_out_of_range_side(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "summary", "j1", "--side", "2"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_results_help_lists_compare_command():
    result = CliRunner().invoke(cli.app, ["results", "--help"])
    assert result.exit_code == 0, result.output
    assert "compare" in result.stdout
    assert "结果对比" in result.stdout


def test_results_compare_posts_default_body(monkeypatch):
    payload = {
        "baseline": {"job_id": "j1", "name": "基线", "metrics": None, "tactic_pool": {}},
        "variant": "B",
        "side": 0,
        "candidates": [],
    }
    result, fake = invoke(
        monkeypatch,
        ["results", "compare", "--baseline", "j1", "--candidate", "j2", "--candidate", "j3"],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/results/compare",
            "body": {
                "baseline_job_id": "j1",
                "candidate_job_ids": ["j2", "j3"],
                "variant": "B",
                "side": 0,
                "reps": 2000,
            },
            "query": None,
        }
    ]


def test_results_compare_prints_indented_unicode_json(monkeypatch):
    payload = {"baseline": {"name": "基线"}, "variant": "B", "side": 0, "candidates": []}
    result, _ = invoke(
        monkeypatch,
        ["results", "compare", "--baseline", "j1", "--candidate", "j2"],
        [payload],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith('{\n  "baseline"')
    assert "基线" in result.stdout


def test_results_compare_forwards_options(monkeypatch):
    payload = {"baseline": {}, "variant": "A", "side": 1, "candidates": []}
    result, fake = invoke(
        monkeypatch,
        [
            "results",
            "compare",
            "--baseline",
            "j1",
            "--candidate",
            "j2",
            "--variant",
            "A",
            "--side",
            "1",
            "--reps",
            "100",
        ],
        [payload],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {
        "baseline_job_id": "j1",
        "candidate_job_ids": ["j2"],
        "variant": "A",
        "side": 1,
        "reps": 100,
    }


def test_results_compare_requires_baseline_and_candidates(monkeypatch):
    missing_candidate, fake = invoke(monkeypatch, ["results", "compare", "--baseline", "j1"])
    assert missing_candidate.exit_code == 2
    assert fake.calls == []

    missing_baseline, fake = invoke(monkeypatch, ["results", "compare", "--candidate", "j2"])
    assert missing_baseline.exit_code == 2
    assert fake.calls == []


def test_results_compare_rejects_out_of_range_options(monkeypatch):
    for extra in (["--reps", "0"], ["--reps", "20001"], ["--side", "2"]):
        result, fake = invoke(
            monkeypatch,
            ["results", "compare", "--baseline", "j1", "--candidate", "j2", *extra],
        )
        assert result.exit_code == 2, extra
        assert fake.calls == [], extra


def test_saves_list_passes_status_and_pagination(monkeypatch):
    payload = {"items": [], "total": 0, "next_offset": None}
    result, fake = invoke(
        monkeypatch,
        ["saves", "list", "--status", "ready", "--limit", "5", "--offset", "10"],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["query"] == {"status": "ready", "limit": 5, "offset": 10}


def test_saves_get_requests_save_by_id(monkeypatch):
    payload = {"id": "s1", "status": "pending"}
    result, fake = invoke(monkeypatch, ["saves", "get", "s1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls[0]["path"] == "/api/saves/s1"


def test_saves_create_posts_full_body(monkeypatch):
    metadata = {"league": "英超"}
    result, fake = invoke(
        monkeypatch,
        [
            "saves",
            "create",
            "--source-path",
            "/saves/season.fm",
            "--source-sha256",
            "a" * 64,
            "--status",
            "reading",
            "--stage",
            "leagues",
            "--metadata",
            json.dumps(metadata, ensure_ascii=False),
        ],
        [{"id": "s1"}],
    )
    assert result.exit_code == 0, result.output
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/api/saves")
    assert call["body"] == {
        "source_path": "/saves/season.fm",
        "source_sha256": "a" * 64,
        "status": "reading",
        "stage": "leagues",
        "metadata": metadata,
    }


def test_saves_create_omits_optional_body_fields(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["saves", "create", "--source-path", "/saves/a.fm", "--source-sha256", "b" * 64],
        [{"id": "s1"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {"source_path": "/saves/a.fm", "source_sha256": "b" * 64}


def test_saves_update_patches_only_given_fields(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["saves", "update", "s1", "--status", "ready"],
        [{"id": "s1"}],
    )
    assert result.exit_code == 0, result.output
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("PATCH", "/api/saves/s1")
    assert call["body"] == {"status": "ready"}


def test_saves_delete_reports_deleted(monkeypatch):
    result, fake = invoke(monkeypatch, ["saves", "delete", "s1"], [{}])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == {"deleted": True}
    assert fake.calls[0]["path"] == "/api/saves/s1"


def test_saves_import_posts_import_payload(monkeypatch):
    leagues = {"1": {"name": "英超"}}
    clubs = {"7": {"name": "阿森纳"}}
    result, fake = invoke(
        monkeypatch,
        [
            "saves",
            "import",
            "s1",
            "--leagues",
            json.dumps(leagues, ensure_ascii=False),
            "--clubs",
            json.dumps(clubs, ensure_ascii=False),
            "--stage",
            "leagues",
        ],
        [{"id": "s1"}],
    )
    assert result.exit_code == 0, result.output
    call = fake.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/api/saves/s1/import")
    assert call["body"] == {"leagues": leagues, "clubs": clubs, "stage": "leagues"}


@pytest.mark.parametrize(
    ("args", "code", "message"),
    [
        (["pools", "list"], "unauthorized", "invalid bearer token"),
        (["drafts", "list"], "not_found", "draft not found"),
        (["jobs", "list"], "validation_failed", "limit 必须为 1–256 的整数"),
        (["jobs", "cancel", "j1"], "invalid_transition", "任务状态不允许该流转"),
        (["saves", "list"], "internal_error", "internal server error"),
    ],
)
def test_sidecar_errors_map_to_exit_1_with_code_and_message(monkeypatch, args, code, message):
    status = 500 if code == "internal_error" else error_status(code)
    result, fake = invoke(monkeypatch, args, error=SidecarError(code, message, status))
    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    assert code in result.stderr
    assert message in result.stderr


def test_unreachable_sidecar_maps_to_exit_1(monkeypatch):
    error = SidecarError("unreachable", "无法连接 sidecar：Connection refused")
    result, _ = invoke(monkeypatch, ["pools", "list"], error=error)
    assert result.exit_code == 1, result.output
    assert "无法连接 sidecar" in result.stderr


def test_endpoint_discovery_failure_maps_to_exit_1(monkeypatch):
    def fail(_data_dir):
        raise SidecarError("endpoint_missing", "找不到 sidecar 发现文件：/data/agent/endpoint.json")

    monkeypatch.setattr(cli, "discover_endpoint", fail)
    result = CliRunner().invoke(cli.app, ["pools", "list"])
    assert result.exit_code == 1, result.output
    assert "endpoint_missing" in result.stderr
    assert "找不到 sidecar 发现文件" in result.stderr


def test_missing_argument_is_usage_error(monkeypatch):
    result, fake = invoke(monkeypatch, ["pools", "get"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_invalid_json_option_is_usage_error(monkeypatch):
    result, fake = invoke(monkeypatch, ["pools", "create", "--name", "X", "--tactic", "not-json"])
    assert result.exit_code == 2
    assert fake.calls == []
    assert "tactic" in result.stderr


def test_update_without_fields_is_usage_error(monkeypatch):
    result, fake = invoke(monkeypatch, ["drafts", "update", "d1"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_data_dir_option_drives_endpoint_discovery(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_discover(data_dir):
        captured["data_dir"] = data_dir
        return {"url": "http://127.0.0.1:9876", "token": TOKEN}

    class FakeSidecarClient:
        def __init__(self, url, token, **kwargs):
            captured["url"] = url
            captured["token"] = token

        def request_json(self, method, path, *, body=None, query=None):
            return {"items": [], "total": 0, "next_offset": None}

    monkeypatch.setattr(cli, "discover_endpoint", fake_discover)
    monkeypatch.setattr(cli, "SidecarClient", FakeSidecarClient)
    result = CliRunner().invoke(cli.app, ["--data-dir", str(tmp_path), "pools", "list"])
    assert result.exit_code == 0, result.output
    assert captured["data_dir"] == tmp_path.resolve()
    assert captured["url"] == "http://127.0.0.1:9876"
    assert captured["token"] == TOKEN
    assert TOKEN not in result.stdout + result.stderr


def test_default_data_dir_comes_from_settings_env(monkeypatch, fake_data_dir: Path):
    captured = {}

    def fake_discover(data_dir):
        captured["data_dir"] = data_dir
        return {"url": "http://127.0.0.1:9876", "token": TOKEN}

    class FakeSidecarClient:
        def __init__(self, url, token, **kwargs):
            captured["url"] = url

        def request_json(self, method, path, *, body=None, query=None):
            return {"items": [], "total": 0, "next_offset": None}

    monkeypatch.setattr(cli, "discover_endpoint", fake_discover)
    monkeypatch.setattr(cli, "SidecarClient", FakeSidecarClient)
    result = CliRunner().invoke(cli.app, ["pools", "list"])
    assert result.exit_code == 0, result.output
    assert captured["data_dir"] == fake_data_dir.resolve()


def error_status(code):
    return {
        "unauthorized": 401,
        "not_found": 404,
        "validation_failed": 400,
        "conflict": 409,
        "invalid_transition": 409,
    }[code]


def test_global_data_dir_applies_to_serve(monkeypatch, tmp_path: Path):
    captured = {}
    monkeypatch.setattr(cli, "run", lambda settings: captured.setdefault("settings", settings) and 0)
    target = tmp_path / "root-data"
    result = CliRunner().invoke(cli.app, ["--data-dir", str(target), "serve"])
    assert result.exit_code == 0, result.output
    assert captured["settings"].data_dir == target.resolve()


def test_command_data_dir_overrides_global_for_serve(monkeypatch, tmp_path: Path):
    captured = {}
    monkeypatch.setattr(cli, "run", lambda settings: captured.setdefault("settings", settings) and 0)
    root = tmp_path / "root-data"
    command = tmp_path / "command-data"
    result = CliRunner().invoke(
        cli.app,
        ["--data-dir", str(root), "serve", "--data-dir", str(command)],
    )
    assert result.exit_code == 0, result.output
    assert captured["settings"].data_dir == command.resolve()


def test_serve_falls_back_to_settings_env_data_dir(monkeypatch, tmp_path: Path):
    captured = {}
    monkeypatch.setattr(cli, "run", lambda settings: captured.setdefault("settings", settings) and 0)
    env_dir = tmp_path / "env-data"
    monkeypatch.setenv("FM27LAB_DATA", str(env_dir))
    result = CliRunner().invoke(cli.app, ["serve"])
    assert result.exit_code == 0, result.output
    assert captured["settings"].data_dir == env_dir.resolve()


def test_limit_out_of_range_is_usage_error(monkeypatch):
    result, fake = invoke(monkeypatch, ["pools", "list", "--limit", "0"])
    assert result.exit_code == 2
    assert fake.calls == []


class ErrorServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler_class):
        super().__init__(("127.0.0.1", 0), handler_class)
        self.requests: list[dict] = []
        self.port = self.server_address[1]


@contextlib.contextmanager
def error_server():
    class ErrorHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.requests.append(
                {"path": self.path, "authorization": self.headers.get("Authorization")}
            )
            payload = json.dumps(
                {
                    "error": {
                        "code": "validation_failed",
                        "message": "条目 ID 无效",
                        "details": None,
                        "retriable": False,
                        "retry_after_seconds": None,
                    }
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            return

    server = ErrorServer(ErrorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_invalid_id_reports_structured_error_without_traceback(tmp_path: Path):
    endpoint = tmp_path / "agent" / "endpoint.json"
    endpoint.parent.mkdir(parents=True, exist_ok=True)
    with error_server() as server:
        endpoint.write_text(
            json.dumps({"url": f"http://127.0.0.1:{server.port}", "token": TOKEN}),
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            cli.app,
            ["--data-dir", str(tmp_path), "pools", "get", "bad/id?x=1"],
        )
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.stderr
    assert "validation_failed" in result.stderr
    assert "条目 ID 无效" in result.stderr
    assert server.requests == [{"path": "/api/pools/bad/id%3Fx%3D1", "authorization": f"Bearer {TOKEN}"}]


def test_drafts_attributes_posts_full_body(monkeypatch):
    payload = {"draft": {"id": "d1", "name": "草案"}, "snapshot": None, "changed_players": 2}
    result, fake = invoke(
        monkeypatch,
        [
            "drafts",
            "attributes",
            "d1",
            "--side",
            "home",
            "--scope",
            "starters",
            "--operation",
            "set",
            "--params",
            '{"overall":15}',
        ],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/drafts/d1/attributes",
            "body": {"side": "home", "scope": "starters", "operation": "set", "params": {"overall": 15}},
            "query": None,
        }
    ]


def test_drafts_attributes_includes_player_index(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "drafts",
            "attributes",
            "d1",
            "--side",
            "away",
            "--scope",
            "players",
            "--operation",
            "set",
            "--params",
            "{}",
            "--player-index",
            "5",
        ],
        [{"changed_players": 1}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {
        "side": "away",
        "scope": "players",
        "operation": "set",
        "params": {},
        "player_index": 5,
    }


def test_drafts_attributes_rejects_invalid_params_json(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "drafts",
            "attributes",
            "d1",
            "--side",
            "home",
            "--scope",
            "starters",
            "--operation",
            "set",
            "--params",
            "not-json",
        ],
    )
    assert result.exit_code == 2
    assert fake.calls == []
    assert "params" in result.stderr


def test_drafts_import_fmf_posts_base64_content(monkeypatch, fake_data_dir: Path):
    content = b"fmf-binary-content"
    path = write_bytes(fake_data_dir / "tactic.fmf", content)
    payload = {"id": "d1", "name": "草案"}
    result, fake = invoke(
        monkeypatch,
        ["drafts", "import-fmf", "--name", "草案", "--file", str(path), "--source", '{"save_id":"s1"}'],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/drafts/import-fmf",
            "body": {"name": "草案", "content_base64": encode_base64(content), "source": {"save_id": "s1"}},
            "query": None,
        }
    ]


def test_drafts_import_fmf_omits_optional_source(monkeypatch, fake_data_dir: Path):
    path = write_bytes(fake_data_dir / "tactic.fmf", b"data")
    result, fake = invoke(
        monkeypatch,
        ["drafts", "import-fmf", "--name", "草案", "--file", str(path)],
        [{"id": "d1"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {"name": "草案", "content_base64": encode_base64(b"data")}


def test_drafts_import_fmf_rejects_unreadable_file(monkeypatch, fake_data_dir: Path):
    missing = fake_data_dir / "missing.fmf"
    result, fake = invoke(monkeypatch, ["drafts", "import-fmf", "--name", "草案", "--file", str(missing)])
    assert result.exit_code == 2
    assert fake.calls == []
    assert "无法读取" in result.stderr


def test_drafts_apply_roster_posts_body(monkeypatch):
    payload = {"draft": {"id": "d1"}, "applied": {"starters": 11, "substitutes": 7}}
    result, fake = invoke(
        monkeypatch,
        [
            "drafts",
            "apply-roster",
            "d1",
            "--save-id",
            "s1",
            "--club-uid",
            "7",
            "--side",
            "home",
            "--scope",
            "starters",
        ],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/drafts/d1/apply-roster",
            "body": {"save_id": "s1", "club_uid": 7, "side": "home", "scope": "starters"},
            "query": None,
        }
    ]


def test_drafts_apply_roster_requires_club_uid(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["drafts", "apply-roster", "d1", "--save-id", "s1", "--side", "home", "--scope", "starters"],
    )
    assert result.exit_code == 2
    assert fake.calls == []


def test_drafts_undo_roster_posts_without_body(monkeypatch):
    payload = {"draft": {"id": "d1"}}
    result, fake = invoke(monkeypatch, ["drafts", "undo-roster", "d1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "POST", "path": "/api/drafts/d1/undo-roster", "body": None, "query": None}
    ]


def test_drafts_undo_roster_requires_draft_id(monkeypatch):
    result, fake = invoke(monkeypatch, ["drafts", "undo-roster"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_jobs_batch_actions_posts_action_and_ids(monkeypatch):
    payload = {"succeeded": ["j1"], "failed": [{"id": "j2", "code": "not_found", "message": "任务不存在"}]}
    result, fake = invoke(
        monkeypatch,
        ["jobs", "batch-action", "--action", "cancel", "--ids", "j1", "--ids", "j2"],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/jobs/actions",
            "body": {"action": "cancel", "ids": ["j1", "j2"]},
            "query": None,
        }
    ]


def test_jobs_batch_actions_rejects_unknown_action(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "batch-action", "--action", "stop", "--ids", "j1"])
    assert result.exit_code == 2
    assert fake.calls == []
    assert "cancel" in result.stderr or "delete" in result.stderr


def test_jobs_batch_actions_requires_ids(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "batch-action", "--action", "delete"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_jobs_batch_delete_sends_delete_with_body(monkeypatch):
    payload = {"deleted": ["j1"], "failed": [{"id": "j2", "error": "任务不存在"}]}
    result, fake = invoke(monkeypatch, ["jobs", "batch-delete", "--ids", "j1", "--ids", "j2"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "DELETE", "path": "/api/jobs", "body": {"ids": ["j1", "j2"]}, "query": None}
    ]


def test_jobs_batch_delete_requires_ids(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "batch-delete"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_jobs_pool_summary_requests_route(monkeypatch):
    payload = {"enabled": True, "entry_count": 2, "draws": {"a": 1}}
    result, fake = invoke(monkeypatch, ["jobs", "pool-summary", "j1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [{"method": "GET", "path": "/api/jobs/j1/pool-summary", "body": None, "query": None}]


def test_jobs_pool_summary_requires_job_id(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "pool-summary"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_saves_import_file_posts_source_path_and_replace(monkeypatch):
    payload = {"save_id": "s1", "status": "imported", "managed_clubs": [], "clubs": 0}
    result, fake = invoke(
        monkeypatch,
        ["saves", "import-file", "--source-path", "/saves/season.fm", "--replace"],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/saves/import",
            "body": {"source_path": "/saves/season.fm", "replace": True},
            "query": None,
        }
    ]


def test_saves_import_file_defaults_replace_to_false(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["saves", "import-file", "--source-path", "/saves/season.fm"],
        [{"save_id": "s1"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {"source_path": "/saves/season.fm", "replace": False}


def test_saves_import_file_requires_source_path(monkeypatch):
    result, fake = invoke(monkeypatch, ["saves", "import-file"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_saves_import_file_maps_conflict_to_exit_1(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["saves", "import-file", "--source-path", "/saves/season.fm"],
        error=SidecarError("conflict", "存档内容重复", 409),
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "conflict" in result.stderr
    assert "存档内容重复" in result.stderr
    assert len(fake.calls) == 1


def test_saves_squad_passes_club_uid_query(monkeypatch):
    payload = {"save_id": "s1", "club_uid": 7, "club_name": "阿森纳", "players": [], "selection": None}
    result, fake = invoke(monkeypatch, ["saves", "squad", "s1", "--club-uid", "7"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "GET", "path": "/api/saves/s1/squad", "body": None, "query": {"club_uid": 7}}
    ]


def test_saves_squad_requires_club_uid(monkeypatch):
    result, fake = invoke(monkeypatch, ["saves", "squad", "s1"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_saves_squad_rejects_out_of_range_club_uid(monkeypatch):
    result, fake = invoke(monkeypatch, ["saves", "squad", "s1", "--club-uid", "0"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_artifacts_list_passes_filters_and_pagination(monkeypatch):
    payload = {"items": [], "total": 0, "next_offset": None}
    result, fake = invoke(
        monkeypatch,
        ["artifacts", "list", "--kind", "tactic", "--job-id", "j1", "--limit", "5", "--offset", "10"],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "GET",
            "path": "/api/artifacts",
            "body": None,
            "query": {"kind": "tactic", "job_id": "j1", "limit": 5, "offset": 10},
        }
    ]


def test_artifacts_list_uses_route_defaults(monkeypatch):
    result, fake = invoke(monkeypatch, ["artifacts", "list"], [{"items": []}])
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["query"] == {"kind": None, "job_id": None, "limit": 50, "offset": 0}


def test_artifacts_list_rejects_out_of_range_limit(monkeypatch):
    result, fake = invoke(monkeypatch, ["artifacts", "list", "--limit", "0"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_artifacts_get_requests_by_id(monkeypatch):
    payload = {"id": "a1", "kind": "tactic", "filename": "a.bin"}
    result, fake = invoke(monkeypatch, ["artifacts", "get", "a1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [{"method": "GET", "path": "/api/artifacts/a1", "body": None, "query": None}]


def test_artifacts_get_requires_id(monkeypatch):
    result, fake = invoke(monkeypatch, ["artifacts", "get"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_artifacts_create_posts_base64_content(monkeypatch, fake_data_dir: Path):
    content = b"artifact-bytes"
    path = write_bytes(fake_data_dir / "artifact.bin", content)
    payload = {"id": "a1", "kind": "tactic", "filename": "artifact.bin"}
    result, fake = invoke(
        monkeypatch,
        [
            "artifacts",
            "create",
            "--kind",
            "tactic",
            "--filename",
            "artifact.bin",
            "--file",
            str(path),
            "--job-id",
            "j1",
        ],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/artifacts",
            "body": {
                "kind": "tactic",
                "filename": "artifact.bin",
                "content_base64": encode_base64(content),
                "job_id": "j1",
            },
            "query": None,
        }
    ]


def test_artifacts_create_omits_job_id(monkeypatch, fake_data_dir: Path):
    path = write_bytes(fake_data_dir / "artifact.bin", b"data")
    result, fake = invoke(
        monkeypatch,
        ["artifacts", "create", "--kind", "tactic", "--filename", "artifact.bin", "--file", str(path)],
        [{"id": "a1"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {
        "kind": "tactic",
        "filename": "artifact.bin",
        "content_base64": encode_base64(b"data"),
    }


def test_artifacts_create_rejects_unreadable_file(monkeypatch, fake_data_dir: Path):
    result, fake = invoke(
        monkeypatch,
        [
            "artifacts",
            "create",
            "--kind",
            "tactic",
            "--filename",
            "a.bin",
            "--file",
            str(fake_data_dir / "nope.bin"),
        ],
    )
    assert result.exit_code == 2
    assert fake.calls == []
    assert "无法读取" in result.stderr


def test_artifacts_delete_reports_deleted(monkeypatch):
    result, fake = invoke(monkeypatch, ["artifacts", "delete", "a1"], [{}])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == {"deleted": True}
    assert fake.calls == [{"method": "DELETE", "path": "/api/artifacts/a1", "body": None, "query": None}]


def test_artifacts_delete_maps_not_found_to_exit_1(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["artifacts", "delete", "a1"],
        error=SidecarError("not_found", "产物不存在", 404),
    )
    assert result.exit_code == 1
    assert "not_found" in result.stderr
    assert "产物不存在" in result.stderr
    assert len(fake.calls) == 1


def test_settings_list_requests_route(monkeypatch):
    payload = {"items": [{"key": "theme", "value": "dark"}], "total": 1}
    result, fake = invoke(monkeypatch, ["settings", "list"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [{"method": "GET", "path": "/api/settings", "body": None, "query": None}]


def test_settings_list_maps_server_error_to_exit_1(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["settings", "list"],
        error=SidecarError("internal_error", "internal server error", 500),
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "internal_error" in result.stderr
    assert "internal server error" in result.stderr


def test_settings_get_requests_key(monkeypatch):
    payload = {"key": "theme", "value": "dark", "note": None, "updated_at": "2026-01-01T00:00:00+00:00"}
    result, fake = invoke(monkeypatch, ["settings", "get", "theme"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [{"method": "GET", "path": "/api/settings/theme", "body": None, "query": None}]


def test_settings_get_requires_key(monkeypatch):
    result, fake = invoke(monkeypatch, ["settings", "get"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_settings_put_sends_value_and_note(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["settings", "put", "theme", "--value", '{"mode":"dark"}', "--note", "主题设置"],
        [{"key": "theme"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls == [
        {
            "method": "PUT",
            "path": "/api/settings/theme",
            "body": {"value": {"mode": "dark"}, "note": "主题设置"},
            "query": None,
        }
    ]


def test_settings_put_accepts_scalar_json_value(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["settings", "put", "theme", "--value", '"dark"'],
        [{"key": "theme"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {"value": "dark"}


def test_settings_put_omits_note(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["settings", "put", "theme", "--value", "1"],
        [{"key": "theme"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {"value": 1}


def test_settings_put_rejects_invalid_json_value(monkeypatch):
    result, fake = invoke(monkeypatch, ["settings", "put", "theme", "--value", "not-json"])
    assert result.exit_code == 2
    assert fake.calls == []
    assert "value" in result.stderr


def test_settings_delete_reports_deleted(monkeypatch):
    result, fake = invoke(monkeypatch, ["settings", "delete", "theme"], [{}])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == {"deleted": True}
    assert fake.calls == [{"method": "DELETE", "path": "/api/settings/theme", "body": None, "query": None}]


def test_settings_delete_maps_not_found_to_exit_1(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["settings", "delete", "theme"],
        error=SidecarError("not_found", "设置不存在", 404),
    )
    assert result.exit_code == 1
    assert "not_found" in result.stderr
    assert "设置不存在" in result.stderr


def test_concurrency_check_passes_query(monkeypatch):
    payload = {
        "allowed": True,
        "code": None,
        "recommended_workers": 8,
        "warnings": [],
        "memory_required_bytes": 0,
        "disk_required_bytes": 0,
    }
    result, fake = invoke(
        monkeypatch,
        [
            "concurrency",
            "check",
            "--workers",
            "8",
            "--cpu-count",
            "16",
            "--available-memory-bytes",
            "1024",
            "--free-disk-bytes",
            "2048",
            "--allow-oversubscription",
        ],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "GET",
            "path": "/api/concurrency/check",
            "body": None,
            "query": {
                "workers": 8,
                "cpu_count": 16,
                "available_memory_bytes": 1024,
                "free_disk_bytes": 2048,
                "allow_oversubscription": True,
            },
        }
    ]


def test_concurrency_check_defaults_oversubscription_to_false(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "concurrency",
            "check",
            "--workers",
            "1",
            "--cpu-count",
            "1",
            "--available-memory-bytes",
            "0",
            "--free-disk-bytes",
            "0",
        ],
        [{"allowed": True}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["query"]["allow_oversubscription"] is False


def test_concurrency_check_rejects_out_of_range_workers(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "concurrency",
            "check",
            "--workers",
            "0",
            "--cpu-count",
            "1",
            "--available-memory-bytes",
            "0",
            "--free-disk-bytes",
            "0",
        ],
    )
    assert result.exit_code == 2
    assert fake.calls == []


def test_system_help_lists_resources_command():
    result = CliRunner().invoke(cli.app, ["system", "--help"])
    assert result.exit_code == 0, result.output
    assert "resources" in result.stdout


def test_system_resources_prints_sidecar_payload(monkeypatch):
    payload = {
        "cpu_count": 16,
        "available_memory_bytes": 8 * GIB,
        "free_disk_bytes": 100 * GIB,
        "recommended_workers": 6,
    }
    result, fake = invoke(monkeypatch, ["system", "resources"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "GET", "path": "/api/system/resources", "body": None, "query": None}
    ]


def test_system_resources_maps_probe_failure_to_exit_1(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["system", "resources"],
        error=SidecarError("resource_probe_failed", "无法探测可用内存", 503),
    )
    assert result.exit_code == 1
    assert "resource_probe_failed" in result.stderr
    assert "无法探测可用内存" in result.stderr


def test_experiments_submit_posts_full_body(monkeypatch):
    payload = {"id": "j1", "kind": "experiment", "status": "queued"}
    result, fake = invoke(
        monkeypatch,
        [
            "experiments",
            "submit",
            "--name",
            "批次",
            "--draft-id",
            "draft-1",
            "--baseline-draft-id",
            "draft-0",
            "--seed",
            "1",
            "--seed",
            "2",
            "--workers",
            "4",
            "--cpu-count",
            "8",
            "--available-memory-bytes",
            "1024",
            "--free-disk-bytes",
            "2048",
            "--allow-oversubscription",
        ],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/experiments",
            "body": {
                "name": "批次",
                "seeds": [1, 2],
                "draft_id": "draft-1",
                "baseline_draft_id": "draft-0",
                "workers": 4,
                "cpu_count": 8,
                "available_memory_bytes": 1024,
                "free_disk_bytes": 2048,
                "allow_oversubscription": True,
            },
            "query": None,
        }
    ]


def test_experiments_submit_omits_optional_fields(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "experiments",
            "submit",
            "--draft-id",
            "draft-1",
            "--seed",
            "7",
            "--workers",
            "1",
            "--cpu-count",
            "1",
            "--available-memory-bytes",
            "0",
            "--free-disk-bytes",
            "0",
        ],
        [{"id": "j1"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {
        "seeds": [7],
        "draft_id": "draft-1",
        "workers": 1,
        "cpu_count": 1,
        "available_memory_bytes": 0,
        "free_disk_bytes": 0,
        "allow_oversubscription": False,
    }


def test_experiments_submit_requires_draft_id(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "experiments",
            "submit",
            "--seed",
            "1",
            "--workers",
            "1",
            "--cpu-count",
            "1",
            "--available-memory-bytes",
            "0",
            "--free-disk-bytes",
            "0",
        ],
    )
    assert result.exit_code == 2
    assert fake.calls == []


def test_experiments_submit_rejects_non_integer_seed(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "experiments",
            "submit",
            "--draft-id",
            "draft-1",
            "--seed",
            "abc",
            "--workers",
            "1",
            "--cpu-count",
            "1",
            "--available-memory-bytes",
            "0",
            "--free-disk-bytes",
            "0",
        ],
    )
    assert result.exit_code == 2
    assert fake.calls == []


def test_experiments_submit_help_marks_resources_as_auto_probed():
    result = CliRunner().invoke(cli.app, ["experiments", "submit", "--help"])
    assert result.exit_code == 0, result.output
    assert result.stdout.count("缺省时自动探测") == 3


def test_experiments_submit_prefills_missing_resources(monkeypatch):
    resources = {
        "cpu_count": 16,
        "available_memory_bytes": 8 * GIB,
        "free_disk_bytes": 100 * GIB,
        "recommended_workers": 6,
    }
    payload = {"id": "j1", "kind": "experiment", "status": "queued"}
    result, fake = invoke(
        monkeypatch,
        ["experiments", "submit", "--draft-id", "draft-1", "--seed", "3", "--workers", "2"],
        [resources, payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "GET", "path": "/api/system/resources", "body": None, "query": None},
        {
            "method": "POST",
            "path": "/api/experiments",
            "body": {
                "seeds": [3],
                "draft_id": "draft-1",
                "workers": 2,
                "cpu_count": 16,
                "available_memory_bytes": 8 * GIB,
                "free_disk_bytes": 100 * GIB,
                "allow_oversubscription": False,
            },
            "query": None,
        },
    ]


def test_experiments_submit_prefers_explicit_resources(monkeypatch):
    resources = {
        "cpu_count": 99,
        "available_memory_bytes": 8 * GIB,
        "free_disk_bytes": 100 * GIB,
        "recommended_workers": 6,
    }
    result, fake = invoke(
        monkeypatch,
        [
            "experiments",
            "submit",
            "--draft-id",
            "draft-1",
            "--seed",
            "1",
            "--workers",
            "1",
            "--cpu-count",
            "4",
        ],
        [resources, {"id": "j2"}],
    )
    assert result.exit_code == 0, result.output
    assert [call["path"] for call in fake.calls] == [
        "/api/system/resources",
        "/api/experiments",
    ]
    body = fake.calls[1]["body"]
    assert body["cpu_count"] == 4
    assert body["available_memory_bytes"] == 8 * GIB
    assert body["free_disk_bytes"] == 100 * GIB


def test_experiments_submit_skips_resource_probe_when_all_resources_given(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        [
            "experiments",
            "submit",
            "--draft-id",
            "draft-1",
            "--seed",
            "1",
            "--workers",
            "1",
            "--cpu-count",
            "1",
            "--available-memory-bytes",
            "0",
            "--free-disk-bytes",
            "0",
        ],
        [{"id": "j3"}],
    )
    assert result.exit_code == 0, result.output
    assert [call["path"] for call in fake.calls] == ["/api/experiments"]


def test_experiments_submit_reports_resource_probe_failure(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["experiments", "submit", "--draft-id", "draft-1", "--seed", "1", "--workers", "1"],
        error=SidecarError("resource_probe_failed", "无法探测可用内存", 503),
    )
    assert result.exit_code == 1
    assert "resource_probe_failed" in result.stderr
    assert "无法探测可用内存" in result.stderr
    assert [call["path"] for call in fake.calls] == ["/api/system/resources"]


def test_experiments_submit_rejects_invalid_resource_probe_payload(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["experiments", "submit", "--draft-id", "draft-1", "--seed", "1", "--workers", "1"],
        [{"cpu_count": 8, "available_memory_bytes": -1, "free_disk_bytes": 100 * GIB}],
    )
    assert result.exit_code == 1
    assert "宿主资源" in result.stderr
    assert [call["path"] for call in fake.calls] == ["/api/system/resources"]


def test_experiments_submit_rejects_non_object_resource_probe_payload(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["experiments", "submit", "--draft-id", "draft-1", "--seed", "1", "--workers", "1"],
        [[{"cpu_count": 8, "available_memory_bytes": 8 * GIB, "free_disk_bytes": 100 * GIB}]],
    )
    assert result.exit_code == 1
    assert "invalid_response: 宿主资源响应不是对象" in result.stderr
    assert [call["path"] for call in fake.calls] == ["/api/system/resources"]


def test_experiments_submit_rejects_zero_cpu_count_from_probe(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["experiments", "submit", "--draft-id", "draft-1", "--seed", "1", "--workers", "1"],
        [{"cpu_count": 0, "available_memory_bytes": 8 * GIB, "free_disk_bytes": 100 * GIB}],
    )
    assert result.exit_code == 1
    assert "invalid_response: 宿主资源字段无效：cpu_count" in result.stderr
    assert [call["path"] for call in fake.calls] == ["/api/system/resources"]


def test_experiments_submit_rejects_missing_probed_field(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["experiments", "submit", "--draft-id", "draft-1", "--seed", "1", "--workers", "1"],
        [{"cpu_count": 8, "free_disk_bytes": 100 * GIB}],
    )
    assert result.exit_code == 1
    assert "invalid_response: 宿主资源字段无效：available_memory_bytes" in result.stderr
    assert [call["path"] for call in fake.calls] == ["/api/system/resources"]


def test_experiments_start_posts_route(monkeypatch):
    payload = {"job": {"id": "j1", "status": "running"}}
    result, fake = invoke(monkeypatch, ["experiments", "start"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [{"method": "POST", "path": "/api/experiments/start", "body": None, "query": None}]


def test_experiments_start_outputs_empty_object_for_empty_queue(monkeypatch):
    result, fake = invoke(monkeypatch, ["experiments", "start"], [{}])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == {}


def test_experiments_start_maps_engine_unavailable_to_exit_1(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["experiments", "start"],
        error=SidecarError("engine_unavailable", "引擎执行失败", 503),
    )
    assert result.exit_code == 1
    assert "engine_unavailable" in result.stderr
    assert "引擎执行失败" in result.stderr


def test_experiments_cancel_posts_route(monkeypatch):
    payload = {"id": "j1", "status": "cancelled"}
    result, fake = invoke(monkeypatch, ["experiments", "cancel", "j1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "POST", "path": "/api/experiments/j1/cancel", "body": None, "query": None}
    ]


def test_experiments_cancel_maps_invalid_transition_to_exit_1(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["experiments", "cancel", "j1"],
        error=SidecarError("invalid_transition", "任务状态不允许该流转", 409),
    )
    assert result.exit_code == 1
    assert "invalid_transition" in result.stderr


def test_artifacts_content_downloads_to_output_file(monkeypatch, fake_data_dir: Path):
    payload = b"artifact-content"
    output = fake_data_dir / "artifact.bin"
    result, fake = invoke(
        monkeypatch,
        ["artifacts", "content", "a1", "--output", str(output)],
        download=payload,
    )
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == payload
    assert parse_output(result) == {"path": str(output), "bytes": len(payload)}
    assert fake.calls == [{"method": "GET", "path": "/api/artifacts/a1/content", "body": None, "query": None}]


def test_artifacts_content_requires_output_option(monkeypatch):
    result, fake = invoke(monkeypatch, ["artifacts", "content", "a1"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_artifacts_content_maps_not_found_without_writing(monkeypatch, fake_data_dir: Path):
    output = fake_data_dir / "artifact.bin"
    result, fake = invoke(
        monkeypatch,
        ["artifacts", "content", "a1", "--output", str(output)],
        error=SidecarError("not_found", "产物文件不存在", 404),
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not_found" in result.stderr
    assert not output.exists()
    assert len(fake.calls) == 1


def test_artifacts_content_reports_write_failure(monkeypatch, fake_data_dir: Path):
    output = fake_data_dir / "missing-dir" / "artifact.bin"
    result, fake = invoke(
        monkeypatch,
        ["artifacts", "content", "a1", "--output", str(output)],
        download=b"artifact-content",
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "无法写入" in result.stderr
    assert len(fake.calls) == 1


def test_drafts_export_fmf_downloads_to_output_file(monkeypatch, fake_data_dir: Path):
    payload = b"fmf-bytes"
    output = fake_data_dir / "tactic.fmf"
    result, fake = invoke(
        monkeypatch,
        ["drafts", "export-fmf", "d1", "--output", str(output)],
        download=payload,
    )
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == payload
    assert parse_output(result) == {"path": str(output), "bytes": len(payload)}
    assert fake.calls == [{"method": "GET", "path": "/api/drafts/d1/export.fmf", "body": None, "query": None}]


def test_drafts_export_fmf_requires_output_option(monkeypatch):
    result, fake = invoke(monkeypatch, ["drafts", "export-fmf", "d1"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_drafts_export_fmf_maps_not_found_to_exit_1(monkeypatch, fake_data_dir: Path):
    output = fake_data_dir / "tactic.fmf"
    result, fake = invoke(
        monkeypatch,
        ["drafts", "export-fmf", "d1", "--output", str(output)],
        error=SidecarError("not_found", "草案不存在", 404),
    )
    assert result.exit_code == 1
    assert "not_found" in result.stderr
    assert not output.exists()


def test_jobs_export_downloads_csv(monkeypatch, fake_data_dir: Path):
    payload = b"seed,score\n1,2\n"
    output = fake_data_dir / "job-j1.csv"
    result, fake = invoke(
        monkeypatch,
        ["jobs", "export", "j1", "--output", str(output)],
        download=payload,
    )
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == payload
    assert parse_output(result) == {"path": str(output), "bytes": len(payload)}
    assert fake.calls == [{"method": "GET", "path": "/api/jobs/j1/export.csv", "body": None, "query": None}]


def test_jobs_export_requires_output_option(monkeypatch):
    result, fake = invoke(monkeypatch, ["jobs", "export", "j1"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_jobs_export_maps_not_found_to_exit_1(monkeypatch, fake_data_dir: Path):
    output = fake_data_dir / "job-j1.csv"
    result, fake = invoke(
        monkeypatch,
        ["jobs", "export", "j1", "--output", str(output)],
        error=SidecarError("not_found", "任务不存在", 404),
    )
    assert result.exit_code == 1
    assert "not_found" in result.stderr
    assert not output.exists()


def test_experiments_resume_posts_route(monkeypatch):
    payload = {"id": "j1", "status": "queued"}
    result, fake = invoke(monkeypatch, ["experiments", "resume", "j1"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {"method": "POST", "path": "/api/experiments/j1/resume", "body": None, "query": None}
    ]


def test_experiments_resume_requires_job_id(monkeypatch):
    result, fake = invoke(monkeypatch, ["experiments", "resume"])
    assert result.exit_code == 2
    assert fake.calls == []


def test_catalog_show_requests_snapshot(monkeypatch):
    payload = {"available": True, "catalog": {"tactics": []}}
    result, fake = invoke(monkeypatch, ["catalog", "show"], [payload])
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [{"method": "GET", "path": "/api/catalog", "body": None, "query": None}]


def test_catalog_show_maps_server_error_to_exit_1(monkeypatch):
    result, fake = invoke(
        monkeypatch,
        ["catalog", "show"],
        error=SidecarError("internal_error", "internal server error", 500),
    )
    assert result.exit_code == 1
    assert "internal_error" in result.stderr


ROOT = Path(__file__).resolve().parents[2]
LIVE_TOKEN = "e" * 64


def _stop_live_sidecar(process: subprocess.Popen, port: int) -> None:
    if process.poll() is None:
        request_value = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/shutdown",
            data=b"",
            method="POST",
            headers={"Authorization": f"Bearer {LIVE_TOKEN}"},
        )
        try:
            urllib.request.urlopen(request_value, timeout=5).close()
        except OSError:
            process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextlib.contextmanager
def live_sidecar(data_dir: Path):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "fm27lab",
            "serve",
            "--data-dir",
            str(data_dir),
            "--token",
            LIVE_TOKEN,
            "--port",
            "0",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    port = 0
    try:
        ready = json.loads(process.stdout.readline().strip())
        assert ready["event"] == "ready"
        port = ready["port"]
        yield data_dir
    finally:
        _stop_live_sidecar(process, port)


@pytest.fixture
def live_data_dir(tmp_path: Path):
    with live_sidecar(tmp_path.resolve()) as data_dir:
        yield data_dir


def invoke_live(data_dir: Path, args):
    return CliRunner().invoke(cli.app, ["--data-dir", str(data_dir), *args])


def test_live_sidecar_round_trip_covers_new_commands(live_data_dir: Path):
    data_dir = live_data_dir

    put = invoke_live(
        data_dir,
        ["settings", "put", "theme", "--value", '{"mode":"dark"}', "--note", "主题"],
    )
    assert put.exit_code == 0, put.output
    assert json.loads(put.stdout)["value"] == {"mode": "dark"}
    got = invoke_live(data_dir, ["settings", "get", "theme"])
    assert got.exit_code == 0, got.output
    assert json.loads(got.stdout)["note"] == "主题"
    listing = invoke_live(data_dir, ["settings", "list"])
    assert listing.exit_code == 0, listing.output
    assert json.loads(listing.stdout)["total"] == 1
    removed = invoke_live(data_dir, ["settings", "delete", "theme"])
    assert removed.exit_code == 0, removed.output
    assert json.loads(removed.stdout) == {"deleted": True}

    check = invoke_live(
        data_dir,
        [
            "concurrency",
            "check",
            "--workers",
            "2",
            "--cpu-count",
            "8",
            "--available-memory-bytes",
            str(16 * 1024**3),
            "--free-disk-bytes",
            str(16 * 1024**3),
            "--allow-oversubscription",
        ],
    )
    assert check.exit_code == 0, check.output
    assert json.loads(check.stdout)["allowed"] is True

    catalog = invoke_live(data_dir, ["catalog", "show"])
    assert catalog.exit_code == 0, catalog.output
    assert "available" in json.loads(catalog.stdout)

    scenario_path = data_dir / "scenario.json"
    scenario_path.write_text(json.dumps(draft_scenario(), ensure_ascii=False), encoding="utf-8")
    created = invoke_live(
        data_dir,
        ["drafts", "create", "--name", "草案", "--scenario", f"@{scenario_path}"],
    )
    assert created.exit_code == 0, created.output
    draft = json.loads(created.stdout)
    attributed = invoke_live(
        data_dir,
        [
            "drafts",
            "attributes",
            draft["id"],
            "--side",
            "home",
            "--scope",
            "starters",
            "--operation",
            "bulk",
            "--params",
            '{"value": 12}',
        ],
    )
    assert attributed.exit_code == 0, attributed.output
    assert json.loads(attributed.stdout)["changed_players"] == 11

    fmf_path = data_dir / "tactic.fmf"
    exported = invoke_live(data_dir, ["drafts", "export-fmf", draft["id"], "--output", str(fmf_path)])
    assert exported.exit_code == 1
    assert "engine_unavailable" in exported.output
    fmf_path.write_bytes(FmfCodec().encode(draft_scenario()))
    imported = invoke_live(data_dir, ["drafts", "import-fmf", "--name", "导入", "--file", str(fmf_path)])
    assert imported.exit_code == 0, imported.output
    drafts_list = invoke_live(data_dir, ["drafts", "list"])
    assert json.loads(drafts_list.stdout)["total"] == 2

    apply_roster = invoke_live(
        data_dir,
        [
            "drafts",
            "apply-roster",
            "missing",
            "--save-id",
            "missing",
            "--club-uid",
            "7",
            "--side",
            "home",
            "--scope",
            "starters",
        ],
    )
    assert apply_roster.exit_code == 1
    assert "not_found" in apply_roster.stderr
    undo_roster = invoke_live(data_dir, ["drafts", "undo-roster", "missing"])
    assert undo_roster.exit_code == 1
    assert "not_found" in undo_roster.stderr

    created_job = invoke_live(data_dir, ["jobs", "create", "--kind", "report"])
    assert created_job.exit_code == 0, created_job.output
    job_id = json.loads(created_job.stdout)["id"]
    csv_path = data_dir / "job.csv"
    exported_csv = invoke_live(data_dir, ["jobs", "export", job_id, "--output", str(csv_path)])
    assert exported_csv.exit_code == 0, exported_csv.output
    assert csv_path.read_text(encoding="utf-8").startswith("job_id,")
    pool = invoke_live(data_dir, ["jobs", "pool-summary", job_id])
    assert pool.exit_code == 0, pool.output
    assert json.loads(pool.stdout)["enabled"] is False
    batch = invoke_live(data_dir, ["jobs", "batch-action", "--action", "cancel", "--ids", job_id])
    assert batch.exit_code == 0, batch.output
    assert json.loads(batch.stdout)["succeeded"] == [job_id]
    deleted = invoke_live(data_dir, ["jobs", "batch-delete", "--ids", job_id])
    assert deleted.exit_code == 0, deleted.output
    assert json.loads(deleted.stdout)["deleted"] == [job_id]

    artifact_source = data_dir / "artifact.bin"
    artifact_source.write_bytes(b"live-artifact-bytes")
    created_artifact = invoke_live(
        data_dir,
        [
            "artifacts",
            "create",
            "--kind",
            "tactic",
            "--filename",
            "artifact.bin",
            "--file",
            str(artifact_source),
        ],
    )
    assert created_artifact.exit_code == 0, created_artifact.output
    artifact = json.loads(created_artifact.stdout)
    downloaded = data_dir / "artifact.out"
    content = invoke_live(data_dir, ["artifacts", "content", artifact["id"], "--output", str(downloaded)])
    assert content.exit_code == 0, content.output
    assert downloaded.read_bytes() == b"live-artifact-bytes"
    assert json.loads(content.stdout) == {"path": str(downloaded), "bytes": len(b"live-artifact-bytes")}
    fetched = invoke_live(data_dir, ["artifacts", "get", artifact["id"]])
    assert fetched.exit_code == 0, fetched.output
    artifacts_list = invoke_live(data_dir, ["artifacts", "list", "--kind", "tactic"])
    assert artifacts_list.exit_code == 0, artifacts_list.output
    assert json.loads(artifacts_list.stdout)["total"] == 1
    artifact_delete = invoke_live(data_dir, ["artifacts", "delete", artifact["id"]])
    assert artifact_delete.exit_code == 0, artifact_delete.output
    assert json.loads(artifact_delete.stdout) == {"deleted": True}

    missing_import = invoke_live(
        data_dir,
        ["saves", "import-file", "--source-path", str(data_dir / "missing.fm")],
    )
    assert missing_import.exit_code == 1
    assert "validation_failed" in missing_import.stderr
    squad = invoke_live(data_dir, ["saves", "squad", "missing", "--club-uid", "7"])
    assert squad.exit_code == 1
    assert "not_found" in squad.stderr

    missing_draft = invoke_live(
        data_dir,
        [
            "experiments",
            "submit",
            "--draft-id",
            "missing-draft",
            "--seed",
            "1",
            "--workers",
            "1",
            "--cpu-count",
            "8",
            "--available-memory-bytes",
            str(16 * 1024**3),
            "--free-disk-bytes",
            str(16 * 1024**3),
        ],
    )
    assert missing_draft.exit_code == 1
    assert "not_found" in missing_draft.stderr
    assert "草案不存在" in missing_draft.stderr
    created_experiment = invoke_live(
        data_dir,
        ["jobs", "create", "--kind", "experiment", "--total", "2"],
    )
    assert created_experiment.exit_code == 0, created_experiment.output
    experiment = json.loads(created_experiment.stdout)
    resume = invoke_live(data_dir, ["experiments", "resume", experiment["id"]])
    assert resume.exit_code == 1
    assert "invalid_transition" in resume.stderr
    cancelled = invoke_live(data_dir, ["experiments", "cancel", experiment["id"]])
    assert cancelled.exit_code == 0, cancelled.output
    assert json.loads(cancelled.stdout)["status"] == "cancelled"
    started = invoke_live(data_dir, ["experiments", "start"])
    assert started.exit_code == 0, started.output
    assert json.loads(started.stdout) == {}


def test_drafts_import_fmf_file_posts_source_path(monkeypatch, fake_data_dir: Path):
    payload = {"id": "d1", "name": "草案"}
    result, fake = invoke(
        monkeypatch,
        ["drafts", "import-fmf-file", str(fake_data_dir / "tactic.fmf"), "--name", "草案"],
        [payload],
    )
    assert result.exit_code == 0, result.output
    assert parse_output(result) == payload
    assert fake.calls == [
        {
            "method": "POST",
            "path": "/api/drafts/import-fmf-file",
            "body": {"source_path": str(fake_data_dir / "tactic.fmf"), "name": "草案"},
            "query": None,
        }
    ]


def test_drafts_import_fmf_file_omits_optional_name(monkeypatch, fake_data_dir: Path):
    result, fake = invoke(
        monkeypatch,
        ["drafts", "import-fmf-file", str(fake_data_dir / "tactic.fmf")],
        [{"id": "d1"}],
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["body"] == {"source_path": str(fake_data_dir / "tactic.fmf")}
