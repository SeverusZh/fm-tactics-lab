"""End-to-end tests for the fm27lab MCP stdio sidecar."""
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_mock import start_server

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

TOOL_NAMES = {
    "lab_status", "engine_select", "draft_create", "draft_get", "draft_edit",
    "draft_validate", "draft_list", "draft_delete", "career_import", "career_status",
    "career_team", "career_opponents", "career_preview", "career_cancel",
    "experiment_run", "career_run", "job_get", "job_wait", "job_list", "job_action",
    "results_summary", "results_matches", "results_csv", "fmf_import", "fmf_export",
    "setpiece_export",
}

BASE_CSV_COLUMNS = [
    "mode", "variant", "seed", "home_goals", "away_goals", "shots",
    "shots_on_target", "xg", "possession", "passes", "completed_passes",
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
            "capabilities": ["free_run", "career_save", "cancel"],
            "limits": {"max_seeds": 10000, "max_workers": 4},
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
        self.assertEqual(len(tools), 26)
        self.assertEqual(names, TOOL_NAMES)
        for key in ("lab_status", "draft_create", "experiment_run", "job_wait",
                    "results_csv", "career_run", "setpiece_export"):
            self.assertIn(key, names)
        by_name = {tool["name"]: tool for tool in tools}
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIsInstance(tool.get("description"), str)
            self.assertIn("properties", tool["inputSchema"])
            self.assertIn("required", tool["inputSchema"])
        self.assertEqual(by_name["engine_select"]["inputSchema"]["required"], ["game_root"])
        source = by_name["draft_create"]["inputSchema"]["properties"]["source"]
        self.assertEqual(source["enum"], ["default", "save", "fmf", "job", "inline"])

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

    def test_resources_prompts_and_career_smoke(self):
        resources = self.sidecar.request("resources/list")["result"]["resources"]
        uris = {resource["uri"] for resource in resources}
        self.assertIn("fm27://manifest", uris)
        self.assertIn("fm27://catalog", uris)
        self.assertIn("fm27://status", uris)

        templates = self.sidecar.request("resources/templates/list")["result"]["resourceTemplates"]
        template_uris = {template["uriTemplate"] for template in templates}
        self.assertIn("fm27://drafts/{draft_id}", template_uris)
        self.assertIn("fm27://jobs/{job_id}/logs/{name}", template_uris)
        self.assertIn("fm27://saves/{save_id}", template_uris)

        contents = self.sidecar.request(
            "resources/read", {"uri": "fm27://manifest"})["result"]["contents"]
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["mimeType"], "application/json")
        manifest = json.loads(contents[0]["text"])
        self.assertEqual(manifest["api"], "fm27lab/v1")

        status = self.sidecar.request(
            "resources/read", {"uri": "fm27://status"})["result"]["contents"][0]
        self.assertIn("engine_compatibility", json.loads(status["text"]))
        save = self.sidecar.request(
            "resources/read", {"uri": "fm27://saves/" + "a" * 16})["result"]["contents"][0]
        self.assertEqual(json.loads(save["text"])["id"], "a" * 16)

        prompts = self.sidecar.request("prompts/list")["result"]["prompts"]
        self.assertEqual({prompt["name"] for prompt in prompts},
                         {"test_tactic_change", "compare_baseline_vs_current", "opponent_sweep"})
        prompt = self.sidecar.request("prompts/get", {
            "name": "test_tactic_change",
            "arguments": {"draft_id": "dr_0123456789ab", "instruction": "提高逼抢强度"},
        })["result"]
        text = prompt["messages"][0]["content"]["text"]
        self.assertIn("dr_0123456789ab", text)
        self.assertIn("experiment_run", text)

        imported = self.call_tool("career_import", {"save_path": "/tmp/career.fm", "wait": True,
                                                    "timeout_seconds": 10})
        self.assertFalse(imported.get("isError"), imported)
        self.assertTrue(imported["structuredContent"]["save_id"])
        self.assertEqual(imported["structuredContent"]["status"], "complete")

        team = self.call_tool("career_team", {"save_id": "a" * 16, "club_uid": 7})
        self.assertIn("players", team["structuredContent"])
        self.assertIn("tactics", team["structuredContent"])

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
