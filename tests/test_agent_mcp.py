"""End-to-end tests for the fm27lab MCP stdio sidecar."""
import csv
import hashlib
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_mock import POOL_PROFILE, make_pool_scenario, start_server

import fm27_tactic_pool

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

TOOL_NAMES = {
    "lab_status", "engine_select", "draft_create", "draft_get", "draft_edit",
    "draft_validate", "draft_list", "draft_options", "draft_delete",
    "experiment_run", "job_get",
    "job_wait", "job_list", "job_action", "results_summary", "results_compare",
    "results_matches", "results_csv", "fmf_import", "fmf_export", "setpiece_export",
}

BASE_CSV_COLUMNS = [
    "mode", "variant", "seed", "tactic_pool_entry_index", "tactic_pool_entry_name",
    "home_goals", "away_goals", "shots",
    "shots_on_target", "xg", "possession", "passes", "completed_passes",
    "opponent_shots", "opponent_shots_on_target", "xga", "opponent_possession",
    "opponent_passes", "opponent_completed_passes", "score_changes", "goal_minutes",
    "elapsed_seconds", "attempts", "log",
]


class SidecarProcess:
    def __init__(self, data_dir):
        env = os.environ.copy()
        env["FM27LAB_DATA"] = str(data_dir)
        env["PYTHONPATH"] = str(SRC) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONIOENCODING"] = "utf-8"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "fm27_agent", "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.next_id = 0
        self.messages = queue.Queue()
        self.notifications = []
        self.responses = {}
        self.stderr_lines = []
        self.stdout_reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.stdout_reader.start()
        self.stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self.stderr_reader.start()

    def _read_stdout(self):
        try:
            while True:
                line = self.process.stdout.readline()
                if not line:
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    self.messages.put({"raw": line})
        except (ValueError, OSError):
            return

    def _read_stderr(self):
        try:
            for line in self.process.stderr:
                self.stderr_lines.append(line.rstrip("\n"))
        except (ValueError, OSError):
            return

    def send(self, payload):
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def notify(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method, params=None, timeout=30):
        self.next_id += 1
        request_id = self.next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method,
                   "params": params or {}})
        return self.read_response(request_id, timeout)

    def read_response(self, request_id, timeout=30):
        if request_id in self.responses:
            return self.responses.pop(request_id)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(
                    f"等待响应 {request_id} 超时；stderr={self.stderr_tail()}")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(
                    f"等待响应 {request_id} 超时；stderr={self.stderr_tail()}") from None
            if "method" in message:
                if message.get("id") is None:
                    self.notifications.append(message)
                    continue
            if message.get("id") == request_id and ("result" in message or "error" in message):
                return message
            if "method" not in message:
                self.responses[message.get("id")] = message

    def wait_notification(self, method, timeout=10):
        for index, message in enumerate(self.notifications):
            if message.get("method") == method:
                return self.notifications.pop(index)
        deadline = time.monotonic() + timeout
        while True:
            for index, message in enumerate(self.notifications):
                if message.get("method") == method:
                    return self.notifications.pop(index)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(
                    f"等待通知 {method} 超时；stderr={self.stderr_tail()}")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(
                    f"等待通知 {method} 超时；stderr={self.stderr_tail()}") from None
            if "method" in message and message.get("id") is None:
                self.notifications.append(message)
            else:
                self.responses[message.get("id")] = message

    def stderr_tail(self):
        return "\n".join(self.stderr_lines[-20:])

    def close(self):
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        for stream in (self.process.stdout, self.process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass


def call_tool(sidecar, name, arguments, meta=None):
    params = {"name": name, "arguments": arguments}
    if meta is not None:
        params["_meta"] = meta
    response = sidecar.request("tools/call", params)
    if "error" in response:
        raise AssertionError(f"工具 {name} 返回协议错误：{response['error']}")
    return response["result"]


class McpSidecarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = start_server(slow_jobs=True)
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.temp_dir.name)
        agent_dir = cls.data_dir / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        endpoint = {
            "schema": 1,
            "api": "fm27lab/v1",
            "url": cls.mock.url,
            "token": cls.mock.token,
            "pid": os.getpid(),
            "data_dir": str(cls.data_dir),
            "versions": {"server": "test"},
            "capabilities": ["free_run", "cancel"],
            "limits": {"max_seeds": 10000, "max_workers": 256},
        }
        (agent_dir / "endpoint.json").write_text(
            json.dumps(endpoint, ensure_ascii=False), encoding="utf-8")
        cls.sidecar = SidecarProcess(cls.data_dir)
        response = cls.sidecar.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        })
        if "result" not in response:
            raise AssertionError(f"initialize 失败：{response}；stderr={cls.sidecar.stderr_tail()}")
        cls.initialize_result = response["result"]
        cls.sidecar.notify("notifications/initialized")

    @classmethod
    def tearDownClass(cls):
        cls.sidecar.close()
        cls.mock.stop()
        cls.temp_dir.cleanup()

    def call_tool(self, name, arguments, meta=None):
        return call_tool(self.sidecar, name, arguments, meta=meta)

    def test_initialize_and_protocol_negotiation(self):
        result = self.initialize_result
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "fm27lab-mcp")
        capabilities = result["capabilities"]
        self.assertIn("tools", capabilities)
        self.assertIn("resources", capabilities)
        self.assertIn("prompts", capabilities)
        pong = self.sidecar.request("ping")
        self.assertEqual(pong["result"], {})

        with tempfile.TemporaryDirectory() as folder:
            sidecar = SidecarProcess(Path(folder))
            try:
                response = sidecar.request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "old-client", "version": "0.1"},
                })
                self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")
            finally:
                sidecar.close()

    def test_tools_list_contains_full_contract(self):
        response = self.sidecar.request("tools/list")
        tools = response["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(len(tools), 21)
        self.assertEqual(names, TOOL_NAMES)
        for key in ("lab_status", "draft_create", "experiment_run", "job_wait",
                    "results_csv", "results_compare", "draft_options", "setpiece_export"):
            self.assertIn(key, names)
        by_name = {tool["name"]: tool for tool in tools}
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIsInstance(tool.get("description"), str)
            self.assertIn("properties", tool["inputSchema"])
            self.assertIn("required", tool["inputSchema"])
        self.assertEqual(by_name["engine_select"]["inputSchema"]["required"], ["game_root"])
        source = by_name["draft_create"]["inputSchema"]["properties"]["source"]
        self.assertEqual(source["enum"], ["default", "fmf", "job", "inline", "draft"])
        self.assertEqual(by_name["job_wait"]["inputSchema"]["properties"]["timeout_seconds"]["default"],
                         45)
        self.assertEqual(by_name["experiment_run"]["inputSchema"]["properties"]["workers"]["maximum"],
                         256)
        status = self.call_tool("lab_status", {})
        self.assertFalse(status.get("isError"), status)
        self.assertEqual(status["structuredContent"]["manifest"]["limits"]["max_workers"], 256)

    def test_workers_above_four_are_accepted(self):
        created = self.call_tool("draft_create", {"source": "default", "name": "MCP 并行"})
        self.assertFalse(created.get("isError"), created)
        draft_id = created["structuredContent"]["draft_id"]
        submitted = self.call_tool("experiment_run", {
            "draft_id": draft_id,
            "seeds": {"start": 201, "count": 2},
            "workers": 5,
            "event_details": False,
        })
        self.assertFalse(submitted.get("isError"), submitted)
        self.assertEqual(submitted["structuredContent"]["workers"], 5)

    def test_draft_edit_run_wait_and_results(self):
        created = self.call_tool("draft_create", {"source": "default", "name": "MCP 基线"})
        self.assertFalse(created.get("isError"), created)
        draft_id = created["structuredContent"]["draft_id"]
        self.assertRegex(draft_id, r"^dr_[0-9a-f]{12}$")

        edited = self.call_tool("draft_edit", {
            "draft_id": draft_id, "op": "mentality", "side": 0, "value": 5,
        })
        self.assertFalse(edited.get("isError"), edited)
        body = edited["structuredContent"]
        self.assertTrue(body["changed"])
        self.assertEqual(body["draft_id"], draft_id)

        fetched = self.call_tool("draft_get", {"draft_id": draft_id, "include_scenario": True})
        scenario = fetched["structuredContent"]["scenario"]
        self.assertEqual(scenario["schema"], 4)
        self.assertEqual(scenario["teams"][0]["mentality"], 5)

        listed = self.call_tool("draft_list", {})
        self.assertIn(draft_id, [item["draft_id"] for item in listed["structuredContent"]["drafts"]])

        validated = self.call_tool("draft_validate", {"draft_id": draft_id})
        self.assertTrue(validated["structuredContent"]["valid"])

        submitted = self.call_tool("experiment_run", {
            "draft_id": draft_id,
            "seeds": {"start": 101, "count": 3},
            "event_details": False,
        })
        self.assertFalse(submitted.get("isError"), submitted)
        run = submitted["structuredContent"]
        job_id = run["job_id"]
        self.assertEqual(run["total"], 3)

        draft_resource = self.sidecar.request(
            "resources/read", {"uri": f"fm27://drafts/{draft_id}"})["result"]["contents"][0]
        self.assertEqual(json.loads(draft_resource["text"])["draft_id"], draft_id)
        job_resource = self.sidecar.request(
            "resources/read", {"uri": f"fm27://jobs/{job_id}"})["result"]["contents"][0]
        self.assertEqual(json.loads(job_resource["text"])["id"], job_id)
        log_resource = self.sidecar.request(
            "resources/read", {"uri": f"fm27://jobs/{job_id}/logs/0001_B_seed_101.jsonl"}
        )["result"]["contents"][0]
        self.assertEqual(log_resource["mimeType"], "application/jsonl")
        self.assertIn("0001_B_seed_101.jsonl", log_resource["text"])

        progress_token = "job-progress-token"
        waited = self.call_tool(
            "job_wait",
            {"job_id": job_id, "timeout_seconds": 10, "poll_ms": 100},
            meta={"progressToken": progress_token},
        )
        self.assertFalse(waited.get("isError"), waited)
        job = waited["structuredContent"]
        self.assertEqual(job["id"], job_id)
        self.assertEqual(job["status"], "complete")
        self.assertFalse(job["timed_out"])
        progress = self.sidecar.wait_notification("notifications/progress", timeout=10)
        self.assertEqual(progress["params"]["progressToken"], progress_token)
        self.assertIn("progress", progress["params"])
        self.assertIn("total", progress["params"])

        summary = self.call_tool("results_summary", {"job_id": job_id})
        data = summary["structuredContent"]
        self.assertEqual(data["metrics"]["B"]["n"], 3)
        self.assertAlmostEqual(data["metrics"]["B"]["win_rate"], 1.0)
        self.assertEqual(data["timings"]["runs"], 3)
        self.assertIn("scorelines", data["distributions"])

        exported = self.call_tool("results_csv", {"job_id": job_id, "out": "mcp-run.csv"})
        exported_body = exported["structuredContent"]
        path = Path(exported_body["path"])
        self.assertTrue(path.is_file())
        self.assertTrue(path.is_relative_to(self.data_dir / "agent" / "exports"))
        self.assertEqual(exported_body["rows"], 3)
        self.assertEqual(exported_body["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split(","), BASE_CSV_COLUMNS)
        self.assertEqual(len(lines), 4)

        matches = self.call_tool("results_matches", {"job_id": job_id, "limit": 2})
        matches_body = matches["structuredContent"]
        self.assertEqual(matches_body["runs_total"], 3)
        self.assertEqual(len(matches_body["runs"]), 2)
        single = self.call_tool("results_matches", {"job_id": job_id, "seed": 102})
        self.assertTrue(single["structuredContent"]["found"])
        self.assertEqual(single["structuredContent"]["run"]["seed"], 102)

    def text_body(self, result):
        self.assertFalse(result.get("isError"), result)
        text = result["content"][0]["text"]
        return json.loads(text)

    def test_text_payloads_are_json_and_data_rich(self):
        created = self.call_tool("draft_create", {"source": "default", "name": "文本基线"})
        draft_id = created["structuredContent"]["draft_id"]
        body = self.text_body(created)
        self.assertEqual(body["draft_id"], draft_id)
        self.assertIn("teams", body["draft"])

        edited = self.call_tool("draft_edit", {
            "draft_id": draft_id, "op": "mentality", "side": 0, "value": 5,
        })
        self.assertTrue(self.text_body(edited)["validation"]["valid"])
        listed = self.text_body(self.call_tool("draft_list", {}))
        self.assertIn(draft_id, [item["draft_id"] for item in listed["drafts"]])
        validated = self.text_body(self.call_tool("draft_validate", {"draft_id": draft_id}))
        self.assertTrue(validated["valid"])
        fetched = self.text_body(self.call_tool(
            "draft_get", {"draft_id": draft_id, "include_scenario": True}))
        self.assertIn("scenario_bytes", fetched)
        self.assertNotIn("scenario", fetched)

        submitted = self.call_tool("experiment_run", {
            "draft_id": draft_id,
            "seeds": {"start": 301, "count": 3},
            "event_details": False,
        })
        run = submitted["structuredContent"]
        job_id = run["job_id"]
        run_text = self.text_body(submitted)
        self.assertEqual(run_text["total"], 3)
        progress = self.text_body(self.call_tool(
            "job_get", {"job_id": job_id, "include_runs": False}))
        self.assertEqual(progress["id"], job_id)
        self.assertNotIn("runs", progress)
        summary = self.text_body(self.call_tool("results_summary", {"job_id": job_id}))
        self.assertEqual(summary["metrics"]["B"]["n"], 3)
        waited = self.text_body(self.call_tool(
            "job_wait", {"job_id": job_id, "timeout_seconds": 5, "poll_ms": 50}))
        self.assertFalse(waited["timed_out"])
        status = self.text_body(self.call_tool("lab_status", {}))
        self.assertIn("paths", status)
        self.assertIn("data_dir", status["paths"])

    def test_draft_clone_inline_path_batch_edit_and_options(self):
        base = self.call_tool("draft_create", {"source": "default", "name": "克隆源"})
        base_id = base["structuredContent"]["draft_id"]
        scenario = self.call_tool(
            "draft_get", {"draft_id": base_id, "include_scenario": True}
        )["structuredContent"]["scenario"]

        cloned = self.call_tool("draft_create", {
            "source": "draft", "base_draft_id": base_id, "name": "克隆草案",
        })
        clone_id = cloned["structuredContent"]["draft_id"]
        self.assertNotEqual(clone_id, base_id)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scenario.json"
            path.write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")
            inline = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(path), "name": "内联文件",
            })
        inline_id = inline["structuredContent"]["draft_id"]

        batch = self.call_tool("draft_edit", {
            "draft_id": clone_id,
            "ops": [
                {"op": "mentality", "side": 0, "value": 6},
                {"op": "team_instruction", "side": 0, "phase": "in_possession",
                 "group": "1", "option": 12},
            ],
        })
        batch_body = batch["structuredContent"]
        self.assertEqual(batch_body["ops"], ["mentality", "team_instruction"])
        edited_scenario = self.call_tool(
            "draft_get", {"draft_id": clone_id, "include_scenario": True}
        )["structuredContent"]["scenario"]
        self.assertEqual(edited_scenario["teams"][0]["mentality"], 6)

        before = edited_scenario
        bad = self.call_tool("draft_edit", {
            "draft_id": clone_id,
            "ops": [
                {"op": "mentality", "side": 0, "value": 2},
                {"op": "role", "side": 0, "phase": "in_possession", "slot": 0,
                 "role": "BadRole"},
            ],
        })
        self.assertTrue(bad.get("isError"), bad)
        self.assertIn("可用角色", bad["content"][0]["text"])
        after = self.call_tool(
            "draft_get", {"draft_id": clone_id, "include_scenario": True}
        )["structuredContent"]["scenario"]
        self.assertEqual(after, before)

        options = self.call_tool("draft_options", {
            "draft_id": clone_id, "phase": "in_possession",
            "include_team_instructions": True,
        })["structuredContent"]
        self.assertEqual(len(options["phases"][0]["slots"]), 11)
        self.assertTrue(options["phases"][0]["slots"][0]["valid_roles"])
        self.assertTrue(options["phases"][0]["team_instructions"])
        single = self.call_tool("draft_options", {
            "draft_id": clone_id, "phase": "in_possession", "slot": 3,
        })["structuredContent"]
        self.assertEqual(len(single["phases"][0]["slots"]), 1)
        self.assertEqual(single["phases"][0]["slots"][0]["slot"], 3)

        fetched = self.call_tool(
            "draft_get", {"draft_id": clone_id, "save_scenario": True}
        )["structuredContent"]
        saved_path = Path(fetched["scenario_path"])
        self.assertTrue(saved_path.is_file())
        self.assertEqual(hashlib.sha256(saved_path.read_bytes()).hexdigest(),
                         fetched["scenario_sha256"])

        deleted = self.call_tool("draft_delete", {"draft_ids": [clone_id, inline_id]})
        deleted_body = deleted["structuredContent"]
        self.assertEqual(deleted_body["deleted_count"], 2)
        self.assertEqual(deleted_body["error_count"], 0)

    def test_candidate_batch_and_results_compare(self):
        first = self.call_tool("draft_create", {"source": "default", "name": "候选甲"})
        second = self.call_tool("draft_create", {"source": "default", "name": "候选乙"})
        submitted = self.call_tool("experiment_run", {
            "candidates": [
                {"draft_id": first["structuredContent"]["draft_id"], "name": "候选甲批次"},
                {"draft_id": second["structuredContent"]["draft_id"], "name": "候选乙批次"},
            ],
            "seeds": {"start": 401, "count": 3},
            "workers": 2,
            "event_details": False,
        })
        body = submitted["structuredContent"]
        self.assertEqual(len(body["jobs"]), 2)
        self.assertEqual(body["total"], 6)
        self.assertEqual(len({job["job_id"] for job in body["jobs"]}), 2)
        compared = self.call_tool("results_compare", {
            "baseline_job_id": body["jobs"][0]["job_id"],
            "candidate_job_ids": [body["jobs"][1]["job_id"]],
            "reps": 200,
        })["structuredContent"]
        candidate = compared["candidates"][0]
        self.assertEqual(compared["baseline"]["metrics"]["n"], 3)
        self.assertEqual(candidate["paired"]["seeds"], 3)
        self.assertEqual(candidate["paired"]["win_rate_delta"], 0.0)
        self.assertEqual(candidate["paired"]["goal_difference_delta"], 0.0)

    def test_job_wait_timeout_returns_next_poll(self):
        draft = self.call_tool("draft_create", {"source": "default", "name": "等待测试"})
        submitted = self.call_tool("experiment_run", {
            "draft_id": draft["structuredContent"]["draft_id"],
            "seeds": {"start": 501, "count": 3},
            "event_details": False,
        })
        job_id = submitted["structuredContent"]["job_id"]
        self.mock.hold_job(job_id)
        try:
            waited = self.call_tool(
                "job_wait", {"job_id": job_id, "timeout_seconds": 0, "poll_ms": 50})
            body = waited["structuredContent"]
            self.assertTrue(body["timed_out"])
            self.assertGreaterEqual(body["next_poll_seconds"], 3)
            self.assertIn("next_poll_seconds", self.text_body(waited))
        finally:
            self.mock.release_job(job_id)

    def test_resources_and_prompts_without_career(self):
        resources = self.sidecar.request("resources/list")["result"]["resources"]
        uris = {resource["uri"] for resource in resources}
        self.assertIn("fm27://manifest", uris)
        self.assertIn("fm27://catalog", uris)
        self.assertIn("fm27://status", uris)
        self.assertIn("fm27://paths", uris)
        self.assertIn("fm27://workflow/free-mode", uris)

        templates = self.sidecar.request("resources/templates/list")["result"]["resourceTemplates"]
        template_uris = {template["uriTemplate"] for template in templates}
        self.assertIn("fm27://drafts/{draft_id}", template_uris)
        self.assertIn("fm27://jobs/{job_id}/logs/{name}", template_uris)
        self.assertNotIn("fm27://saves/{save_id}", template_uris)

        contents = self.sidecar.request(
            "resources/read", {"uri": "fm27://manifest"})["result"]["contents"]
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["mimeType"], "application/json")
        manifest = json.loads(contents[0]["text"])
        self.assertEqual(manifest["api"], "fm27lab/v1")

        status = self.sidecar.request(
            "resources/read", {"uri": "fm27://status"})["result"]["contents"][0]
        self.assertIn("engine_compatibility", json.loads(status["text"]))
        workflow = self.sidecar.request(
            "resources/read", {"uri": "fm27://workflow/free-mode"})["result"]["contents"][0]
        self.assertEqual(workflow["mimeType"], "text/markdown")
        self.assertIn("results_compare", workflow["text"])

        prompts = self.sidecar.request("prompts/list")["result"]["prompts"]
        self.assertEqual({prompt["name"] for prompt in prompts},
                         {"test_tactic_change", "compare_baseline_vs_current"})
        prompt = self.sidecar.request("prompts/get", {
            "name": "test_tactic_change",
            "arguments": {"draft_id": "dr_0123456789ab", "instruction": "提高逼抢强度"},
        })["result"]
        text = prompt["messages"][0]["content"]["text"]
        self.assertIn("dr_0123456789ab", text)
        self.assertIn("experiment_run", text)

        retired = self.sidecar.request("tools/call", {
            "name": "career_import", "arguments": {"save_path": "/tmp/career.fm"}})
        self.assertIn("error", retired)
        self.assertEqual(retired["error"]["code"], -32602)

    def test_unknown_tool_and_invalid_arguments(self):
        unknown = self.sidecar.request("tools/call", {"name": "not_a_tool", "arguments": {}})
        self.assertIn("error", unknown)
        self.assertEqual(unknown["error"]["code"], -32602)

        missing = self.call_tool("engine_select", {})
        self.assertTrue(missing.get("isError"))
        self.assertEqual(missing["structuredContent"]["error"]["code"], "validation_failed")
        self.assertIn("game_root", missing["content"][0]["text"])

        wrong_type = self.call_tool("draft_get", {"draft_id": "not-a-draft"})
        self.assertTrue(wrong_type.get("isError"))
        self.assertEqual(wrong_type["structuredContent"]["error"]["code"], "validation_failed")

        bad_seeds = self.call_tool("experiment_run", {
            "draft_id": "dr_0123456789ab",
            "seeds": [1, 1],
        })
        self.assertTrue(bad_seeds.get("isError"))
        self.assertEqual(bad_seeds["structuredContent"]["error"]["code"], "validation_failed")

        rename = self.call_tool("job_action", {"job_id": "job00000001", "action": "rename"})
        self.assertTrue(rename.get("isError"))
        self.assertEqual(rename["structuredContent"]["error"]["code"], "validation_failed")

    def test_lab_status_handles_string_engine_profile(self):
        result = self.call_tool("lab_status", {})
        self.assertFalse(result.get("isError"), result)
        data = result["structuredContent"]
        self.assertEqual(data["manifest"]["server_version"], "test")
        self.assertEqual(data["engine"]["profile"], "fm27_desktop_2493426_adapter_v1")
        text = self.text_body(result)
        self.assertEqual(text["engine"]["profile_version"],
                         "fm27_desktop_2493426_adapter_v1")
        self.assertEqual(text["engine"]["can_simulate"], True)

    def test_tool_call_reloads_endpoint_after_token_rotation(self):
        mock = start_server()
        temp = tempfile.TemporaryDirectory()
        try:
            data_dir = Path(temp.name)
            agent_dir = data_dir / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)
            endpoint = {"schema": 1, "api": "fm27lab/v1", "url": mock.url,
                        "token": mock.token, "pid": os.getpid(),
                        "data_dir": str(data_dir), "versions": {"server": "test"}}
            (agent_dir / "endpoint.json").write_text(
                json.dumps(endpoint, ensure_ascii=False), encoding="utf-8")
            sidecar = SidecarProcess(data_dir)
            try:
                response = sidecar.request("initialize", {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "rotation-client", "version": "1.0"}})
                self.assertIn("result", response, sidecar.stderr_tail())
                sidecar.notify("notifications/initialized")
                draft = call_tool(sidecar, "draft_create",
                                  {"source": "default", "name": "轮换草案"})
                draft_id = draft["structuredContent"]["draft_id"]
                self.assertFalse(call_tool(sidecar, "lab_status", {}).get("isError"))
                rotated = secrets.token_hex(16)
                mock.token = rotated
                endpoint["token"] = rotated
                (agent_dir / "endpoint.json").write_text(
                    json.dumps(endpoint, ensure_ascii=False), encoding="utf-8")
                retried = call_tool(sidecar, "lab_status", {})
                self.assertFalse(retried.get("isError"), retried)
                self.assertEqual(retried["structuredContent"]["manifest"]["api"],
                                 "fm27lab/v1")
                rotated_again = secrets.token_hex(16)
                mock.token = rotated_again
                endpoint["token"] = rotated_again
                (agent_dir / "endpoint.json").write_text(
                    json.dumps(endpoint, ensure_ascii=False), encoding="utf-8")
                submitted = call_tool(sidecar, "experiment_run", {
                    "draft_id": draft_id, "seeds": {"start": 11, "count": 2},
                    "event_details": False})
                self.assertFalse(submitted.get("isError"), submitted)
                self.assertIn("job_id", submitted["structuredContent"])
            finally:
                sidecar.close()
        finally:
            mock.stop()
            temp.cleanup()

    def test_pool_round_trips_through_draft_sources(self):
        expected_pool = {"enabled": True, "entries": 2, "mode": "random",
                         "rounds": 1, "players": "uniform", "roster_entries": 0,
                         "uniform": {"enabled": True, "attribute_value": 15}}
        scenario = make_pool_scenario()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pool.json"
            path.write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")
            created = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(path), "name": "池往返"})
        body = created["structuredContent"]
        draft_id = body["draft_id"]
        self.assertEqual(body["draft"]["away_tactic_pool"], expected_pool)
        fetched = self.call_tool("draft_get", {"draft_id": draft_id, "include_scenario": True})
        fetched_pool = fetched["structuredContent"]["scenario"]["away_tactic_pool"]
        self.assertEqual([entry["name"] for entry in fetched_pool["entries"]],
                         ["池战术甲", "池战术乙"])
        saved = self.call_tool("draft_get", {"draft_id": draft_id, "save_scenario": True})
        saved_path = Path(saved["structuredContent"]["scenario_path"])
        saved_scenario = json.loads(saved_path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved_scenario["away_tactic_pool"]["entries"]), 2)
        cloned = self.call_tool("draft_create", {"source": "draft", "base_draft_id": draft_id})
        self.assertEqual(cloned["structuredContent"]["draft"]["away_tactic_pool"], expected_pool)
        imported = self.call_tool("draft_create", {
            "source": "fmf", "side": 1, "file_base64": "QUFB", "base_draft_id": draft_id})
        self.assertEqual(imported["structuredContent"]["draft"]["away_tactic_pool"],
                         expected_pool)
        submitted = self.call_tool("experiment_run", {
            "draft_id": draft_id, "seeds": {"start": 701, "count": 2},
            "event_details": False})
        job_id = submitted["structuredContent"]["job_id"]
        from_job = self.call_tool("draft_create", {
            "source": "job", "job_id": job_id, "variant": "B"})
        self.assertEqual(from_job["structuredContent"]["draft"]["away_tactic_pool"],
                         expected_pool)

    def test_pool_ab_same_draw_and_results_views(self):
        scenario = make_pool_scenario()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pool.json"
            path.write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")
            candidate = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(path), "name": "池候选"})
            baseline = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(path), "name": "池基准"})
        candidate_id = candidate["structuredContent"]["draft_id"]
        baseline_id = baseline["structuredContent"]["draft_id"]
        submitted = self.call_tool("experiment_run", {
            "draft_id": candidate_id, "baseline_draft_id": baseline_id,
            "seeds": {"start": 801, "count": 6}, "event_details": False})
        submitted_body = submitted["structuredContent"]
        self.assertEqual(submitted_body["total"], 12)
        self.assertEqual(submitted_body["mode"], "comparison")
        job_id = submitted_body["job_id"]
        job = self.call_tool("job_get", {"job_id": job_id, "runs_limit": 200})
        runs = job["structuredContent"]["runs"]
        self.assertEqual(len(runs), 12)
        draws = {}
        for run in runs:
            entry = run["tactic_pool_entry"]
            draws.setdefault(run["seed"], {})[run["variant"]] = entry["index"]
            self.assertIn(entry["name"], ("池战术甲", "池战术乙"))
        for seed, paired in draws.items():
            self.assertEqual(len(paired), 2, seed)
            self.assertEqual(paired["A"], paired["B"])
        summary = self.call_tool("results_summary", {"job_id": job_id})
        data = summary["structuredContent"]
        self.assertEqual(data["metrics"]["A"]["n"], 6)
        self.assertEqual(data["metrics"]["B"]["n"], 6)
        pool = data["tactic_pool"]
        self.assertEqual(pool["salt"], job_id)
        self.assertEqual(pool["draws"]["total"], 6)
        self.assertEqual(sum(row["draws"] for row in pool["entries"]), 6)
        self.assertEqual({row["name"] for row in pool["entries"]},
                         {"池战术甲", "池战术乙"})
        text = self.text_body(summary)
        self.assertEqual(text["tactic_pool"]["draws"]["total"], 6)
        seed = sorted(draws)[0]
        single = self.call_tool("results_matches", {"job_id": job_id, "seed": seed})
        single_body = single["structuredContent"]
        self.assertTrue(single_body["found"])
        self.assertIn(single_body["run"]["tactic_pool_entry"]["index"], (0, 1))
        page = self.call_tool("results_matches", {"job_id": job_id, "limit": 200})
        self.assertTrue(all(run["tactic_pool_entry"] for run in page["structuredContent"]["runs"]))
        exported = self.call_tool("results_csv", {"job_id": job_id, "out": "pool.csv"})
        exported_body = exported["structuredContent"]
        self.assertEqual(exported_body["columns"], BASE_CSV_COLUMNS)
        with Path(exported_body["path"]).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 12)
        for row in rows:
            self.assertIn(row["tactic_pool_entry_index"], ("0", "1"))
            self.assertIn(row["tactic_pool_entry_name"], ("池战术甲", "池战术乙"))

    def test_results_compare_rejects_unpaired_pool_draws(self):
        pool_scenario = make_pool_scenario()
        other_pool = make_pool_scenario(("别的甲", "别的乙"))
        plain = self.call_tool("draft_create", {"source": "default", "name": "无池"})
        with tempfile.TemporaryDirectory() as folder:
            first_path = Path(folder) / "pool.json"
            first_path.write_text(json.dumps(pool_scenario, ensure_ascii=False), encoding="utf-8")
            pooled = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(first_path), "name": "池"})
            second_path = Path(folder) / "other.json"
            second_path.write_text(json.dumps(other_pool, ensure_ascii=False), encoding="utf-8")
            other = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(second_path), "name": "别的池"})
        seeds = {"start": 901, "count": 8}
        plain_job = self.call_tool("experiment_run", {
            "draft_id": plain["structuredContent"]["draft_id"], "seeds": seeds,
            "event_details": False})["structuredContent"]["job_id"]
        pooled_job = self.call_tool("experiment_run", {
            "draft_id": pooled["structuredContent"]["draft_id"], "seeds": seeds,
            "event_details": False})["structuredContent"]["job_id"]
        other_job = self.call_tool("experiment_run", {
            "draft_id": other["structuredContent"]["draft_id"], "seeds": seeds,
            "event_details": False})["structuredContent"]["job_id"]
        compared = self.call_tool("results_compare", {
            "baseline_job_id": plain_job,
            "candidate_job_ids": [pooled_job], "reps": 200})["structuredContent"]
        candidate = compared["candidates"][0]
        self.assertFalse(candidate["comparable"])
        self.assertIn("战术池", candidate["reason"])
        self.assertIsNone(candidate["paired"])
        compared = self.call_tool("results_compare", {
            "baseline_job_id": pooled_job,
            "candidate_job_ids": [other_job], "reps": 200})["structuredContent"]
        candidate = compared["candidates"][0]
        self.assertFalse(candidate["comparable"])
        self.assertIn("条目", candidate["reason"])
        entries = pool_scenario["away_tactic_pool"]["entries"]
        baseline_draws = {seed: fm27_tactic_pool.draw_index(entries, seed, pooled_job)
                          for seed in range(901, 909)}
        mismatch_job = None
        for _ in range(4):
            job_id = self.call_tool("experiment_run", {
                "draft_id": pooled["structuredContent"]["draft_id"], "seeds": seeds,
                "event_details": False})["structuredContent"]["job_id"]
            candidate_draws = {seed: fm27_tactic_pool.draw_index(entries, seed, job_id)
                               for seed in range(901, 909)}
            if any(baseline_draws[seed] != candidate_draws[seed] for seed in baseline_draws):
                mismatch_job = job_id
                break
        self.assertIsNotNone(mismatch_job)
        compared = self.call_tool("results_compare", {
            "baseline_job_id": pooled_job,
            "candidate_job_ids": [mismatch_job], "reps": 200})["structuredContent"]
        candidate = compared["candidates"][0]
        self.assertFalse(candidate["comparable"])
        self.assertIn("分配", candidate["reason"])
        self.assertIsNone(candidate["paired"])
        self.assertGreater(candidate["pairing"]["draw_mismatches"], 0)

    def test_rotation_and_real_pool_summaries_and_pairing(self):
        import copy

        def roster(team):
            return {"club_uid": 2, "club": "乙队", "coach": "乙队主教练",
                    "source": "coach_preset", "roster_size": 11,
                    "lineup": list(range(11)),
                    "players": [{"name": f"存档球员{index}", "source_uid": 700 + index,
                                 "attributes": [12] * 69, "native_profile": {}}
                                for index in range(11)]}

        rotation = make_pool_scenario()
        rotation["away_tactic_pool"]["rotation"] = {"enabled": True, "rounds": 2}
        with tempfile.TemporaryDirectory() as folder:
            rotation_path = Path(folder) / "rotation.json"
            rotation_path.write_text(json.dumps(rotation, ensure_ascii=False), encoding="utf-8")
            rotation_draft = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(rotation_path),
                "name": "轮战池"})["structuredContent"]["draft_id"]
            uniform = make_pool_scenario()
            real = make_pool_scenario()
            shared_roster = roster(real["teams"][1])
            for scenario in (uniform, real):
                for entry in scenario["away_tactic_pool"]["entries"]:
                    entry["roster"] = copy.deepcopy(shared_roster)
            real["away_tactic_pool"]["real"] = {"enabled": True}
            real_path = Path(folder) / "real.json"
            real_path.write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
            real_draft = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(real_path),
                "name": "真实名单池"})["structuredContent"]["draft_id"]
            uniform_path = Path(folder) / "uniform.json"
            uniform_path.write_text(json.dumps(uniform, ensure_ascii=False), encoding="utf-8")
            uniform_draft = self.call_tool("draft_create", {
                "source": "inline", "scenario_path": str(uniform_path),
                "name": "统一属性池"})["structuredContent"]["draft_id"]
        rotation_job = self.call_tool("experiment_run", {
            "draft_id": rotation_draft, "seeds": {"start": 501, "count": 4},
            "event_details": False})["structuredContent"]["job_id"]
        rotation_summary = self.call_tool("results_summary", {
            "job_id": rotation_job})["structuredContent"]["tactic_pool"]
        self.assertEqual((rotation_summary["mode"], rotation_summary["rounds"],
                          rotation_summary["players"]), ("rotation", 2, "uniform"))
        self.assertEqual(rotation_summary["draws"]["total"], 4)
        self.assertEqual(sum(row["draws"] for row in rotation_summary["entries"]), 4)
        self.assertTrue(all(row["roster"] is False for row in rotation_summary["entries"]))
        real_job = self.call_tool("experiment_run", {
            "draft_id": real_draft, "seeds": {"start": 601, "count": 2},
            "event_details": False})["structuredContent"]["job_id"]
        real_summary = self.call_tool("results_summary", {
            "job_id": real_job})["structuredContent"]["tactic_pool"]
        self.assertEqual(real_summary["players"], "real")
        self.assertTrue(all(row["roster"] for row in real_summary["entries"]))
        uniform_job = self.call_tool("experiment_run", {
            "draft_id": uniform_draft, "seeds": {"start": 601, "count": 2},
            "event_details": False})["structuredContent"]["job_id"]
        compared = self.call_tool("results_compare", {
            "baseline_job_id": real_job, "candidate_job_ids": [uniform_job],
            "reps": 100})["structuredContent"]["candidates"][0]
        self.assertFalse(compared["comparable"])
        self.assertIn("模式", compared["reason"])

    def test_app_unavailable_returns_tool_error(self):
        with tempfile.TemporaryDirectory() as folder:
            sidecar = SidecarProcess(Path(folder))
            try:
                response = sidecar.request("initialize", {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "offline-client", "version": "1.0"},
                })
                self.assertIn("result", response)
                result = call_tool(sidecar, "lab_status", {})
                self.assertTrue(result.get("isError"))
                error = result["structuredContent"]["error"]
                self.assertEqual(error["code"], "app_unavailable")
                self.assertIn("启动", error["message"])
            finally:
                sidecar.close()


if __name__ == "__main__":
    unittest.main()
