import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import fm27_agent_server as agent_server


class FakePhaseInputs:
    def pack(self, scenario, catalog):
        return {"schema": 4, "teams": scenario.get("teams", [])}


class FakeSaveLibrary:
    def __init__(self):
        self.active = None
        self.cancelled = []

    def status(self, key=None):
        return {"status": "empty"}

    def start(self, path):
        return {"id": "a" * 16}

    def select_squad(self, scenario, side, lineup, bench):
        return scenario


class FakeApp:
    def __init__(self):
        self.LOCK = threading.RLock()
        self.JOBS = {}
        self.BATCH_LIMITS = {"maximum": 4, "recommended": 2}
        self.NATIVE = Path(tempfile.mkdtemp())
        (self.NATIVE / "adapter_version.json").write_text(
            json.dumps({"version": "test-adapter"}), encoding="utf8")
        self.ENGINE_COMPATIBILITY = {"compatible": True, "profile": {"version": "test-build"}}
        self.CATALOG = {}
        self.DEFAULT = {"schema": 3, "teams": []}
        self.phase_inputs = FakePhaseInputs()
        self.SAVE_LIBRARY = FakeSaveLibrary()
        self.RUNS = self.NATIVE / "data" / "runs"
        self.RUNS.mkdir(parents=True)
        self.started = []
        self.shutdowns = 0
        self.validation_raises = False

    def validate_scenario(self, scenario):
        if self.validation_raises:
            raise ValueError("bad scenario")
        return scenario

    def encode_scenario(self, scenario):
        return b"x" * 32

    def repair_saved_scenario(self, scenario):
        return {"scenario": scenario, "changes": []}

    def start_run(self, data):
        self.started.append(data)
        return {"id": "jobnew", "total": len(data["seeds"])}

    def select_engine(self, path):
        return {"compatible": True, "selected_game_root": path}

    def request_shutdown(self):
        self.shutdowns += 1

    def cancel_job(self, job):
        return {"accepted": True}

    def resume_job_api(self, job, data):
        return {"id": job["id"]}

    def rename_job(self, job, name):
        job["name"] = name
        return {"id": job["id"], "name": name}

    def delete_job(self, job):
        self.JOBS.pop(job["id"], None)
        return {"id": job["id"]}

    def import_fmf(self, data):
        return {"scenario": data["scenario"], "report": {}}

    def export_fmf(self, data):
        return {"filename": "a.fmf", "file_base64": "QUFB", "report": {}}

    def export_setpiece(self, data):
        return {"filename": "b.fmf", "file_base64": "QUFB", "report": {}}


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.router = agent_server.Router(self.app, token="t" * 64, port=12345)

    def test_manifest_and_status(self):
        status, payload, _ = self.router.get("/api/agent/v1/manifest", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["api"], "fm27lab/v1")
        self.assertEqual(payload["adapter_version"], "test-adapter")
        self.assertEqual(payload["engine_build"], "test-build")
        self.assertEqual(payload["limits"]["max_workers"], 4)
        self.app.JOBS["running"] = {"id": "running", "status": "running", "created": 1}
        status, payload, _ = self.router.get("/api/agent/v1/status", {})
        self.assertEqual(payload["active_job"]["id"], "running")

    def test_jobs_pagination(self):
        for index in range(3):
            self.app.JOBS[f"job{index}"] = {"id": f"job{index}", "status": "complete",
                                          "created": index, "runs": []}
        status, payload, _ = self.router.get("/api/agent/v1/jobs",
                                             {"limit": "2", "offset": "0"})
        self.assertEqual(len(payload["jobs"]), 2)
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["next_offset"], 2)
        status, payload, _ = self.router.get("/api/agent/v1/jobs/job1", {})
        self.assertEqual(payload["id"], "job1")

    def test_job_detail_pagination(self):
        self.app.JOBS["job"] = {"id": "job", "status": "complete", "created": 1,
                                "runs": [{"variant": "B", "seed": index, "sequence": index}
                                         for index in range(1, 6)],
                                "completed": 5}
        status, payload, _ = self.router.get("/api/agent/v1/jobs/job",
                                             {"runs_offset": "1", "runs_limit": "2"})
        self.assertEqual([run["sequence"] for run in payload["runs"]], [2, 3])
        self.assertEqual(payload["runs_total"], 5)
        self.assertTrue(payload["runs_truncated"])

    def test_validate_and_failure(self):
        status, payload, _ = self.router.post("/api/agent/v1/validate",
                                              {"scenario": {"schema": 3}}, {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["records"], 1)
        self.app.validation_raises = True
        with self.assertRaises(agent_server.AgentHttpError) as caught:
            self.router.post("/api/agent/v1/validate", {"scenario": {}}, {})
        self.assertEqual(caught.exception.code, "validation_failed")
        self.assertEqual(caught.exception.status, 400)

    def test_idempotency(self):
        body = {"scenario": {}, "seeds": [1], "event_details": True}
        headers = {"Idempotency-Key": "same-key"}
        status, payload, extra = self.router.post("/api/agent/v1/runs", body, headers)
        self.assertEqual(status, 202)
        self.assertEqual(payload["id"], "jobnew")
        status, payload, extra = self.router.post("/api/agent/v1/runs", body, headers)
        self.assertEqual(status, 202)
        self.assertEqual(extra["Idempotency-Replayed"], "true")
        with self.assertRaises(agent_server.AgentHttpError) as caught:
            self.router.post("/api/agent/v1/runs",
                             {"scenario": {}, "seeds": [2], "event_details": True}, headers)
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_busy_and_cancel(self):
        self.app.JOBS["active"] = {"id": "active", "status": "queued", "created": 1}
        status, payload, _ = self.router.post(
            "/api/agent/v1/runs",
            {"scenario": {}, "seeds": [1], "event_details": True}, {})
        self.assertEqual(status, 202)
        self.assertEqual(payload["id"], "jobnew")
        with self.assertRaises(agent_server.AgentHttpError) as caught:
            self.router.post("/api/agent/v1/engine/select", {"game_root": "C:/game"}, {})
        self.assertEqual(caught.exception.code, "engine_busy")
        self.assertEqual(self.router.status()["active_job"]["queue_position"], 1)
        status, payload, _ = self.router.post("/api/agent/v1/jobs/active/cancel", {}, {})
        self.assertTrue(payload["accepted"])

    def test_shutdown_and_unknown(self):
        status, payload, _ = self.router.post("/api/agent/v1/shutdown", {}, {})
        self.assertEqual(status, 202)
        self.assertEqual(self.app.shutdowns, 1)
        with self.assertRaises(agent_server.AgentHttpError) as caught:
            self.router.get("/api/agent/v1/nope", {})
        self.assertEqual(caught.exception.status, 404)

    def test_career_endpoints_are_gone(self):
        for path in ("/api/agent/v1/career/import", "/api/agent/v1/career/run"):
            with self.assertRaises(agent_server.AgentHttpError) as caught:
                self.router.post(path, {}, {})
            self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(agent_server.AgentHttpError) as caught:
            self.router.get("/api/agent/v1/career/status", {})
        self.assertEqual(caught.exception.status, 404)


class RunQueueTests(unittest.TestCase):
    def test_gate_serializes_overlapping_runs_in_submission_order(self):
        gate = agent_server.RunGate()
        events = []
        lock = threading.Lock()

        def work(name, hold):
            with gate:
                with lock:
                    events.append(("start", name))
                time.sleep(hold)
                with lock:
                    events.append(("end", name))

        first = threading.Thread(target=work, args=("first", 0.15))
        first.start()
        time.sleep(0.02)
        second = threading.Thread(target=work, args=("second", 0.01))
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)
        self.assertEqual(events, [("start", "first"), ("end", "first"),
                                  ("start", "second"), ("end", "second")])

    def test_queue_state_orders_queued_and_running_by_creation(self):
        jobs = {
            "new": {"id": "new", "status": "queued", "created": 20},
            "done": {"id": "done", "status": "complete", "created": 5},
            "active": {"id": "active", "status": "running", "created": 10},
            "old": {"id": "old", "status": "queued", "created": 1},
        }
        positions = agent_server.run_queue_state(jobs)
        self.assertEqual(positions, {"old": 1, "active": 2, "new": 3})

    def test_cancel_marks_queued_run_cancelled_immediately(self):
        job = {"id": "queued", "status": "queued", "created": 1}
        stopped = agent_server.cancel_run_state(job)
        self.assertFalse(stopped)
        self.assertEqual(job["status"], "cancelled")
        self.assertTrue(job["_cancel"])
        self.assertIn("finished", job)

    def test_cancel_running_run_keeps_status_for_runner(self):
        job = {"id": "running", "status": "running", "created": 1}
        self.assertTrue(agent_server.cancel_run_state(job))
        self.assertEqual(job["status"], "running")
        self.assertTrue(job["_cancel"])

    def test_cancel_finished_run_is_noop(self):
        job = {"id": "done", "status": "complete", "created": 1}
        self.assertFalse(agent_server.cancel_run_state(job))
        self.assertEqual(job["status"], "complete")
        self.assertNotIn("_cancel", job)


if __name__ == "__main__":
    unittest.main()
