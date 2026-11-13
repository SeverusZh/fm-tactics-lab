from __future__ import annotations

import contextlib
import http.server
import json
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

import fm27lab
import fm27lab.cli as cli
from fm27lab.client import SidecarError

TOKEN = "token-must-not-leak-2f8a"


class FakeClient:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def request_json(self, method, path, *, body=None, query=None):
        self.calls.append({"method": method, "path": path, "body": body, "query": query})
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError(f"未预期的请求：{method} {path}")
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def fake_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FM27LAB_DATA", str(tmp_path))
    monkeypatch.delenv("FM27LAB_TOKEN", raising=False)
    return tmp_path


def invoke(monkeypatch, args, responses=None, error=None):
    fake = FakeClient(responses, error)
    monkeypatch.setattr(cli, "_client_for", lambda data_dir: fake)
    result = CliRunner().invoke(cli.app, args)
    return result, fake


def parse_output(result):
    return json.loads(result.stdout)


def test_root_help_lists_command_groups():
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0, result.output
    for name in ("version", "serve", "pools", "drafts", "jobs", "saves"):
        assert name in result.stdout, name


def test_pools_help_lists_crud_commands():
    result = CliRunner().invoke(cli.app, ["pools", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("list", "get", "create", "delete"):
        assert name in result.stdout, name


def test_drafts_help_lists_crud_commands():
    result = CliRunner().invoke(cli.app, ["drafts", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("list", "get", "create", "update", "delete"):
        assert name in result.stdout, name


def test_jobs_help_lists_lifecycle_commands():
    result = CliRunner().invoke(cli.app, ["jobs", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("list", "get", "create", "update", "cancel", "delete", "runs", "summary"):
        assert name in result.stdout, name


def test_saves_help_lists_lifecycle_commands():
    result = CliRunner().invoke(cli.app, ["saves", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("list", "get", "create", "update", "delete", "import"):
        assert name in result.stdout, name


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
