"""Contract tests for the fm27lab CLI against the in-memory agent server."""
from __future__ import annotations

import base64
import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import agent_mock  # noqa: E402
from fm27_agent import __main__ as agent_main  # noqa: E402
from fm27_agent import cli  # noqa: E402


class AgentCliTests(unittest.TestCase):
    def setUp(self):
        self.server = agent_mock.start_server()
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.base = ["--endpoint", self.server.url, "--token", self.server.token,
                     "--data-dir", str(self.dir)]

    def tearDown(self):
        self.server.stop()
        self.temp.cleanup()

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main([str(item) for item in arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def invoke_json(self, *arguments):
        code, stdout, stderr = self.invoke(*arguments, "--json")
        data = json.loads(stdout) if stdout.strip() else None
        return code, data, stderr

    def create_draft(self, name=None):
        arguments = self.base + ["draft", "create", "--from", "default"]
        if name:
            arguments += ["--name", name]
        code, data, stderr = self.invoke_json(*arguments)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["source"]["kind"], "default")
        return data["draft_id"]

    def run_job(self, draft_id, *extra):
        code, data, stderr = self.invoke_json(
            *self.base, "run", "--draft", draft_id, "--seeds", "1", *extra)
        self.assertEqual(code, 0, stderr)
        return data["id"]

    def test_status_reads_endpoint_file(self):
        agent_dir = self.dir / "agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "endpoint.json").write_text(json.dumps({
            "schema": 1, "api": "fm27lab/v1", "url": self.server.url,
            "token": self.server.token, "pid": 1, "data_dir": str(self.dir),
        }), encoding="utf-8")
        code, stdout, stderr = self.invoke("--data-dir", str(self.dir), "--json", "status")
        self.assertEqual(code, 0, stderr)
        value = json.loads(stdout)
        self.assertEqual(value["manifest"]["api"], "fm27lab/v1")
        self.assertTrue(value["status"]["engine_compatibility"]["compatible"])
        self.assertEqual(stderr, "")

    def test_global_options_after_subcommand(self):
        code, stdout, stderr = self.invoke("status", "--json", *self.base)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["manifest"]["api"], "fm27lab/v1")
        code, stdout, stderr = self.invoke("status", "--quiet", "--no-color", *self.base)
        self.assertEqual(code, 0, stderr)
        self.assertIn("fm27lab/v1", stdout)

    def test_missing_endpoint_returns_3(self):
        code, stdout, stderr = self.invoke("--data-dir", str(self.dir), "--json", "status")
        self.assertEqual(code, 3)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "app_unavailable")

    def test_usage_error_returns_2(self):
        code, stdout, stderr = self.invoke(
            *self.base, "--json", "run", "--draft", "dr_000000000000", "--seeds", "abc")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "usage")

    def test_draft_create_show_list_validate(self):
        draft_id = self.create_draft("基线")
        self.assertRegex(draft_id, r"^dr_[0-9a-f]{12}$")
        code, data, stderr = self.invoke_json(*self.base, "draft", "show", draft_id, "--full")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["name"], "基线")
        self.assertEqual(data["scenario"]["schema"], 4)
        self.assertEqual(len(data["scenario"]["teams"]), 2)
        code, data, stderr = self.invoke_json(*self.base, "draft", "list")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["drafts"][0]["draft_id"], draft_id)
        code, data, stderr = self.invoke_json(*self.base, "draft", "validate", draft_id)
        self.assertEqual(code, 0, stderr)
        self.assertTrue(data["valid"])
        self.assertEqual(data["records"], 30)

    def test_draft_edit_mentality(self):
        draft_id = self.create_draft()
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "edit", draft_id, "--op", "mentality",
            "--team", "B", "--value", "5")
        self.assertEqual(code, 0, stderr)
        self.assertTrue(data["changed"])
        self.assertEqual(data["summary"]["teams"][1]["mentality"], 5)
        code, data, stderr = self.invoke_json(*self.base, "draft", "show", draft_id, "--full")
        self.assertEqual(data["scenario"]["teams"][1]["mentality"], 5)

    def test_draft_edit_invalid_returns_6_and_keeps_draft(self):
        draft_id = self.create_draft()
        code, stdout, stderr = self.invoke(
            *self.base, "--json", "draft", "edit", draft_id,
            "--op", "mentality", "--team", "A", "--value", "9")
        self.assertEqual(code, 6)
        self.assertEqual(json.loads(stderr)["error"]["code"], "validation_failed")
        code, data, stderr = self.invoke_json(*self.base, "draft", "show", draft_id, "--full")
        self.assertEqual(data["scenario"]["teams"][0]["mentality"], 3)

    def test_draft_create_alternate_sources(self):
        draft_id = self.create_draft()
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "create", "--from", "save", "--save-id", "a" * 16,
            "--club", "1", "--tactic", "0", "--lineup", ",".join(map(str, range(11))))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["source"]["kind"], "save")
        self.assertEqual(data["source"]["tactic_index"], 0)
        scenario_file = self.dir / "scenario.json"
        scenario_file.write_text(json.dumps(agent_mock.make_scenario()), encoding="utf-8")
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "create", "--from", "inline", "--inline", str(scenario_file))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["source"]["kind"], "inline")
        self.assertEqual(data["scenario_schema"], 4)
        fmf_file = self.dir / "tactic.fmf"
        fmf_file.write_bytes(b"fake-fmf")
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "create", "--from", "fmf", "--file", str(fmf_file),
            "--side", "A")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["source"]["kind"], "fmf")
        job_id = self.run_job(draft_id)
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "create", "--from", "job", "--job", job_id,
            "--variant", "B")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["source"]["kind"], "job")
        self.assertEqual(data["source"]["variant"], "B")

    def test_draft_edit_role_formation_and_tactic_name(self):
        draft_id = self.create_draft()
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "edit", draft_id, "--op", "role", "--team", "A",
            "--phase", "out_of_possession", "--slot", "5", "--role", "DM",
            "--duty", "defend")
        self.assertEqual(code, 0, stderr)
        # mock 场景只是形状夹具；真实 CATALOG 位置 id 唯一，服务端要求 11 个不重复位置。
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "edit", draft_id, "--op", "formation", "--team", "A",
            "--phase", "in_possession", "--positions",
            "GK,LB,CB,RB,DM,CM,LM,RM,LW,ST,RW")
        self.assertEqual(code, 0, stderr)
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "edit", draft_id, "--op", "tactic_name",
            "--team", "A", "--value", "高位逼抢")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["summary"]["teams"][0]["tactic_name"], "高位逼抢")
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "show", draft_id, "--full")
        assignment = next(plan for plan in data["scenario"]["teams"][0]["phase_plans"]
                          if plan["phase"] == "out_of_possession")["assignments"][5]
        self.assertEqual(assignment["role"], "DM")
        self.assertEqual(assignment["duty"], "defend")
        positions = next(plan for plan in data["scenario"]["teams"][0]["phase_plans"]
                         if plan["phase"] == "in_possession")["assignments"]
        self.assertEqual([cell["position"] for cell in positions],
                         ["GK", "LB", "CB", "RB", "DM", "CM", "LM", "RM",
                          "LW", "ST", "RW"])

    def test_job_wait_and_action(self):
        draft_id = self.create_draft()
        self.server.slow_jobs = True
        try:
            code, data, stderr = self.invoke_json(
                *self.base, "run", "--draft", draft_id, "--seeds", "1")
            self.assertEqual(code, 0, stderr)
            job_id = data["id"]
            code, data, stderr = self.invoke_json(
                *self.base, "job", "wait", job_id, "--timeout", "0.05")
        finally:
            self.server.slow_jobs = False
        self.assertEqual(code, 0, stderr)
        self.assertTrue(data["timed_out"])
        self.assertEqual(data["status"], "running")
        code, data, stderr = self.invoke_json(
            *self.base, "job", "action", job_id, "--rename", "改名")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["name"], "改名")
        code, data, stderr = self.invoke_json(
            *self.base, "job", "action", job_id, "--resume", "--workers", "2")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["id"], job_id)
        code, data, stderr = self.invoke_json(
            *self.base, "job", "action", job_id, "--cancel")
        self.assertEqual(code, 0, stderr)
        self.assertTrue(data["accepted"])
        code, data, stderr = self.invoke_json(
            *self.base, "job", "action", job_id, "--delete")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["id"], job_id)

    def test_failed_job_returns_9(self):
        draft_id = self.create_draft()
        original = self.server.create_job

        def failing(body, mode):
            status, payload = original(body, mode)
            self.server.jobs[payload["id"]].update(status="error", error="模拟失败")
            return status, payload

        self.server.create_job = failing
        try:
            code, data, stderr = self.invoke_json(
                *self.base, "run", "--draft", draft_id, "--seeds", "1", "--wait")
        finally:
            self.server.create_job = original
        self.assertEqual(code, 9, stderr)
        self.assertEqual(data["status"], "error")
        code, data, stderr = self.invoke_json(*self.base, "job", "wait", data["id"])
        self.assertEqual(code, 9, stderr)
        self.assertEqual(data["status"], "error")

    def test_setpiece_export(self):
        draft_id = self.create_draft()
        code, data, stderr = self.invoke_json(
            *self.base, "setpiece", "export", "--draft", draft_id, "--side", "A",
            "--type", "0", "--variant", "1")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["draft_id"], draft_id)
        self.assertEqual(data["filename"], "setpiece.fmf")
        self.assertEqual((data["type"], data["variant"]), (0, 1))

    def test_missing_draft_returns_8(self):
        code, data, stderr = self.invoke_json(
            *self.base, "draft", "show", "dr_000000000000")
        self.assertEqual(code, 8)
        self.assertIsNone(data)
        self.assertEqual(json.loads(stderr)["error"]["code"], "not_found")

    def test_run_wait_quick(self):
        draft_id = self.create_draft()
        code, data, stderr = self.invoke_json(
            *self.base, "run", "--draft", draft_id, "--seeds", "1-3", "--quick", "--wait")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["runs_total"], 3)
        self.assertEqual(sorted(run["seed"] for run in data["runs"]), [1, 2, 3])
        self.assertIn("3/3", stderr)
        request = next(call for call in reversed(self.server.calls)
                       if call["path"] == "/api/agent/v1/runs")
        self.assertEqual(request["body"]["seeds"], [1, 2, 3])
        self.assertFalse(request["body"]["event_details"])

    def test_results_summary_and_matches(self):
        baseline = self.create_draft("基线")
        candidate = self.create_draft("实验")
        code, data, stderr = self.invoke_json(
            *self.base, "run", "--draft", candidate, "--baseline", baseline,
            "--seeds", "1,2", "--wait")
        self.assertEqual(code, 0, stderr)
        job_id = data["id"]
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["total"], 4)
        code, summary, stderr = self.invoke_json(*self.base, "results", "summary", job_id)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(summary["job_id"], job_id)
        self.assertIn("metrics", summary)
        self.assertIn("paired", summary)
        self.assertEqual(summary["total"], 4)
        code, matches, stderr = self.invoke_json(
            *self.base, "results", "matches", job_id, "--limit", "2")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(matches["runs"]), 2)
        self.assertEqual(matches["runs_total"], 4)
        self.assertNotIn("events", matches["runs"][0])
        code, matches, stderr = self.invoke_json(
            *self.base, "results", "matches", job_id, "--variant", "B")
        self.assertTrue(all(run["variant"] == "B" for run in matches["runs"]))
        code, match, stderr = self.invoke_json(
            *self.base, "results", "match", job_id, "--seed", "2", "--variant", "B")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(match["run"]["seed"], 2)

    def test_results_csv(self):
        baseline = self.create_draft("基线")
        candidate = self.create_draft("实验")
        code, data, stderr = self.invoke_json(
            *self.base, "run", "--draft", candidate, "--baseline", baseline,
            "--seeds", "1,2", "--wait")
        self.assertEqual(code, 0, stderr)
        job_id = data["id"]
        target = self.dir / "results.csv"
        code, data, stderr = self.invoke_json(
            *self.base, "results", "csv", job_id, "--out", str(target), "--events")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["rows"], 4)
        self.assertTrue(target.is_file())
        with target.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 4)
        self.assertEqual(list(rows[0].keys()), [
            "mode", "variant", "seed", "tactic_pool_entry_index",
            "tactic_pool_entry_name", "home_goals", "away_goals", "shots",
            "shots_on_target", "xg", "possession", "passes", "completed_passes",
            "elapsed_seconds", "attempts", "log", "goals", "cards"])
        self.assertEqual(rows[0]["mode"], "comparison")
        self.assertEqual(rows[0]["home_goals"], "1")
        self.assertEqual(rows[0]["away_goals"], "0")
        self.assertEqual(rows[0]["shots"], "8")
        self.assertEqual(rows[0]["xg"], "1.2")
        self.assertEqual(rows[0]["possession"], "55")
        self.assertEqual(rows[0]["goals"], "[]")
        self.assertEqual({row["variant"] for row in rows}, {"A", "B"})
        self.assertEqual(sorted({int(row["seed"]) for row in rows}), [1, 2])

    def test_job_list_pagination(self):
        draft_id = self.create_draft()
        for _ in range(3):
            self.run_job(draft_id)
        code, data, stderr = self.invoke_json(*self.base, "job", "list", "--limit", "2")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["jobs"]), 2)
        self.assertEqual(data["next_offset"], 2)
        code, data, stderr = self.invoke_json(
            *self.base, "job", "list", "--limit", "2", "--offset", "2")
        self.assertEqual(len(data["jobs"]), 1)
        self.assertEqual(data["offset"], 2)

    def test_job_export_and_logs(self):
        draft_id = self.create_draft()
        code, data, stderr = self.invoke_json(
            *self.base, "run", "--draft", draft_id, "--seeds", "1", "--wait")
        self.assertEqual(code, 0, stderr)
        job_id = data["id"]
        log_name = data["runs"][0]["log"]
        out_dir = self.dir / "export"
        code, bundle, stderr = self.invoke_json(
            *self.base, "job", "export", job_id, "--out", str(out_dir))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(set(bundle["files"]), {"summary", "scenarios", "provenance"})
        for key in ("summary", "scenarios", "provenance"):
            path = out_dir / (key + ".json")
            self.assertTrue(path.is_file())
            json.loads(path.read_text(encoding="utf-8"))
        code, stdout, stderr = self.invoke(
            *self.base, "job", "logs", job_id, "--run", log_name)
        self.assertEqual(code, 0, stderr)
        self.assertIn(log_name, stdout)

    def test_career_import_and_status(self):
        save = self.dir / "career.fm"
        save.write_bytes(b"fm-save")
        code, data, stderr = self.invoke_json(
            *self.base, "career", "import", "--save", str(save))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["save_id"], "a" * 16)
        self.assertFalse(data["reused"])
        code, data, stderr = self.invoke_json(
            *self.base, "career", "status", "--save-id", "a" * 16)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["status"], "complete")
        request = next(call for call in reversed(self.server.calls)
                       if call["path"] == "/api/agent/v1/career/import")
        self.assertEqual(request["body"]["path"], str(save))

    def test_career_opponents(self):
        code, data, stderr = self.invoke_json(
            *self.base, "career", "opponents", "--save-id", "a" * 16, "--club", "7")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["save_id"], "a" * 16)
        self.assertEqual(data["club_uid"], 7)
        self.assertEqual(data["opponents"][0]["key"], "coach:1")

    def test_fmf_export(self):
        draft_id = self.create_draft()
        code, data, stderr = self.invoke_json(
            *self.base, "fmf", "export", "--draft", draft_id, "--side", "A")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["draft_id"], draft_id)
        self.assertEqual(data["side"], 0)
        self.assertEqual(data["filename"], "tactic.fmf")
        self.assertEqual(data["sha256"], "0" * 64)
        request = next(call for call in reversed(self.server.calls)
                       if call["path"] == "/api/agent/v1/fmf/export")
        self.assertEqual(request["body"]["side"], 0)

    def test_fmf_import_updates_draft(self):
        draft_id = self.create_draft()
        source = self.dir / "tactic.fmf"
        source.write_bytes(b"fake-fmf")
        code, data, stderr = self.invoke_json(
            *self.base, "fmf", "import", "--draft", draft_id, "--side", "B",
            "--file", str(source))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(data["draft_id"], draft_id)
        self.assertTrue(data["report"]["native_roundtrip_verified"])
        self.assertEqual(data["summary"]["draft_id"], draft_id)
        request = next(call for call in reversed(self.server.calls)
                       if call["path"] == "/api/agent/v1/fmf/import")
        self.assertEqual(request["body"]["file_base64"],
                         base64.b64encode(b"fake-fmf").decode("ascii"))
        code, draft, stderr = self.invoke_json(*self.base, "draft", "show", draft_id)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(draft["scenario_schema"], 4)

    def test_engine_busy_returns_7(self):
        draft_id = self.create_draft()
        self.server.busy = True
        try:
            code, data, stderr = self.invoke_json(
                *self.base, "run", "--draft", draft_id, "--seeds", "1")
        finally:
            self.server.busy = False
        self.assertEqual(code, 7)
        self.assertIsNone(data)
        try:
            payload = json.loads(stderr)
        except ValueError:
            self.fail(f"stderr 不是单份 JSON：{stderr!r}")
        self.assertEqual(payload["error"]["code"], "engine_busy")

    def test_module_entry_dispatches_to_cli(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = agent_main.main(["status", "--json", *self.base])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["manifest"]["api"], "fm27lab/v1")


if __name__ == "__main__":
    unittest.main()
