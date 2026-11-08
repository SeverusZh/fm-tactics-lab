import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from agent_mock import start_server
from fm27_agent.client import AgentError, Client, expand_seeds, load_endpoint


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def client(self, token=None, data_dir=None):
        return Client(base_url=self.server.url, token=self.server.token if token is None else token,
                      data_dir=data_dir or tempfile.mkdtemp())

    def test_manifest_status_catalog(self):
        client = self.client()
        self.assertEqual(client.manifest()["api"], "fm27lab/v1")
        self.assertTrue(client.status()["engine_compatibility"]["compatible"])
        self.assertIn("catalog", client.catalog())
        self.assertEqual(len(client.defaults()["scenario"]["teams"]), 2)
        self.assertIn("tools", client.schemas())
        self.assertTrue(client.health()["ok"])

    def test_validate_repair_phase_plan(self):
        client = self.client()
        scenario = client.defaults()["scenario"]
        checked = client.validate(scenario)
        self.assertEqual(checked["records"], 30)
        self.assertEqual(client.repair(scenario)["changes"], [])
        self.assertEqual(client.phase_plan(scenario)["scenario"]["schema"], 4)

    def test_run_wait_pagination(self):
        client = self.client()
        scenario = client.defaults()["scenario"]
        started = client.run(scenario, reference=scenario, seeds=[1, 2], workers=2)
        self.assertEqual(started["total"], 4)
        job = client.wait_job(started["id"], timeout=5, poll=0.02)
        self.assertEqual(job["status"], "complete")
        self.assertEqual(len(job["runs"]), 4)
        page = client.job(started["id"], runs_offset=1, runs_limit=2)
        self.assertEqual(len(page["runs"]), 2)
        self.assertEqual(page["runs_total"], 4)
        self.assertTrue(page["runs_truncated"])
        export = client.job_export(started["id"])
        self.assertEqual(sorted(export["scenarios"]), ["A", "B"])
        log = client.job_logs(started["id"], job["runs"][0]["log"])
        self.assertIn("native_timings", log)

    def test_slow_wait(self):
        slow = start_server(slow_jobs=True)
        try:
            client = Client(base_url=slow.url, token=slow.token, data_dir=tempfile.mkdtemp())
            started = client.run(client.defaults()["scenario"], seeds=[9])
            job = client.wait_job(started["id"], timeout=5, poll=0.02)
            self.assertEqual(job["status"], "complete")
            self.assertFalse(job["timed_out"])
        finally:
            slow.stop()

    def test_errors(self):
        client = self.client(token="bad")
        with self.assertRaises(AgentError) as caught:
            client.manifest()
        self.assertEqual(caught.exception.code, "unauthorized")
        self.assertEqual(caught.exception.http_status, 401)
        busy = start_server(busy=True)
        try:
            busy_client = Client(base_url=busy.url, token=busy.token, data_dir=tempfile.mkdtemp())
            with self.assertRaises(AgentError) as caught:
                busy_client.run(busy_client.defaults()["scenario"], seeds=[1])
            self.assertEqual(caught.exception.code, "engine_busy")
            self.assertEqual(caught.exception.http_status, 409)
        finally:
            busy.stop()

    def test_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / "agent").mkdir()
            (data / "agent" / "endpoint.json").write_text(json.dumps({
                "url": self.server.url, "token": self.server.token,
                "data_dir": str(data)}), encoding="utf8")
            endpoint = load_endpoint(data)
            self.assertEqual(endpoint["token"], self.server.token)
            client = Client(data_dir=data)
            self.assertEqual(client.manifest()["api"], "fm27lab/v1")

    def test_expand_seeds(self):
        self.assertEqual(expand_seeds({"start": 3, "count": 3}), [3, 4, 5])
        self.assertEqual(expand_seeds([1, 2]), [1, 2])
        with self.assertRaises(AgentError):
            expand_seeds({"start": 0, "count": 0})
        with self.assertRaises(AgentError):
            expand_seeds([1, 1])
        with self.assertRaises(AgentError):
            expand_seeds([0xFFFFFFFF + 1])


if __name__ == "__main__":
    unittest.main()
