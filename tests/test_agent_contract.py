import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import fm27_agent_contract as contract


class ContractTests(unittest.TestCase):
    def test_host_allowlist(self):
        self.assertTrue(contract.host_allowed("127.0.0.1:18765", 18765))
        self.assertTrue(contract.host_allowed("localhost:18765", 18765))
        self.assertTrue(contract.host_allowed("[::1]:18765", 18765))
        self.assertFalse(contract.host_allowed("evil.example:18765", 18765))
        self.assertFalse(contract.host_allowed(None, 18765))

    def test_token_sources(self):
        token = "a" * 64
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(contract.request_token(headers), token)
        self.assertTrue(contract.authorized(headers, token))
        self.assertFalse(contract.authorized(headers, "b" * 64))
        cookie = {"Cookie": "theme=dark; fm27_session=" + token}
        self.assertEqual(contract.request_token(cookie), token)
        self.assertTrue(contract.authorized(cookie, token))
        self.assertFalse(contract.authorized({"Cookie": "fm27_session=wrong"}, token))

    def test_exempt_paths(self):
        static = {"/": "index.html", "/app.js": "app.js"}
        self.assertTrue(contract.is_exempt("/", static))
        self.assertTrue(contract.is_exempt("/api/agent/v1/health"))
        self.assertTrue(contract.is_exempt("/api/status"))
        self.assertFalse(contract.is_exempt("/api/jobs", static))
        self.assertFalse(contract.is_exempt("/api/catalog", static))

    def test_error_payload(self):
        value = contract.error_payload("engine_busy", "忙", {"job": "x"}, True, 30)
        self.assertEqual(value["error"]["code"], "engine_busy")
        self.assertTrue(value["error"]["retriable"])
        self.assertEqual(value["error"]["retry_after_seconds"], 30)

    def test_pagination(self):
        page = contract.paginate(list(range(5)), 2, 1, "jobs")
        self.assertEqual(page["jobs"], [1, 2])
        self.assertEqual(page["total"], 5)
        self.assertEqual(page["next_offset"], 3)
        page = contract.paginate(list(range(2)), 10, 0)
        self.assertIsNone(page["next_offset"])

    def test_idempotency(self):
        clock = [100.0]
        store = contract.IdempotencyStore(ttl=10, clock=lambda: clock[0])
        digest = contract.json_digest({"a": 1})
        self.assertEqual(store.check("k", digest)[0], "missing")
        store.remember("k", digest, 202, {"id": "x"})
        self.assertEqual(store.check("k", digest), ("replay", (202, {"id": "x"})))
        self.assertEqual(store.check("k", "other")[0], "conflict")
        clock[0] = 200.0
        self.assertEqual(store.check("k", digest)[0], "missing")

    def test_endpoint_and_scripts(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            endpoint = contract.build_endpoint(
                1234, "t" * 64, data, data / "engine", "", {"server": "x"},
                ["free_run"], {"max_seeds": 10})
            path = contract.write_endpoint(data, endpoint)
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(path.read_text(encoding="utf8"))["url"],
                             "http://127.0.0.1:1234")
            scripts = contract.write_agent_scripts(data, data / "source", data / "python.exe")
            command = Path(scripts["command"]).read_bytes()
            self.assertIn(b"PYTHONPATH", command)
            self.assertIn(b"-m fm27_agent", command)
            self.assertIn(b"\r\n", command)
            self.assertNotIn(b"\r\r\n", command)
            self.assertTrue(Path(scripts["config"]).is_file())
            contract.remove_endpoint(data)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
