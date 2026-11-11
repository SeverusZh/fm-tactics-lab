"""Offline integration tests for the shared web/agent run submission queue."""
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ENGINE_FIXTURE = ROOT / "private" / "engine"
HAS_PRIVATE_FIXTURES = (
    (ENGINE_FIXTURE / "fm27_native" / "editor_manual_default.json").is_file()
    and (ENGINE_FIXTURE / "fm27_research" / "setpiece_enum_catalog.json").is_file()
    and (ROOT / "private" / "catalog.json").is_file()
)


def load_server_module(engine_root, data_root):
    """Load fm27_tactics_server.py without the Windows runtime it normally needs."""
    source = (SRC / "fm27_tactics_server.py").read_text(encoding="utf-8")
    web = Path(tempfile.mkdtemp(prefix="server-web-"))
    (web / "tactics_ui").mkdir()
    shutil.copy(ROOT / "private" / "catalog.json", web / "tactics_ui" / "catalog.json")
    environment = {"FM27_ENGINE_ROOT": str(engine_root), "FM27_DESKTOP_DATA": str(data_root)}
    previous = {key: os.environ.get(key) for key in environment}
    os.environ.update(environment)
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    sys.modules.setdefault("msvcrt", types.ModuleType("msvcrt"))
    module = types.ModuleType("fm27_tactics_server_offline")
    module.__file__ = str(web / "fm27_tactics_server.py")
    sys.modules[module.__name__] = module
    try:
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    module.ENGINE_COMPATIBILITY = {**module.ENGINE_COMPATIBILITY,
                                   "can_simulate": True,
                                   "actual_dll_sha256": module.ENGINE_DLL_SHA256}
    return module


def pool_scenario(module, names=("池战术甲", "池战术乙")):
    team = module.DEFAULT["teams"][1]
    entries = []
    for name in names:
        entries.append({"name": name, "weight": 1, "tactic": {
            "tactic_name": name,
            "mentality": team["mentality"],
            "instructions": copy.deepcopy(team["instructions"]),
            "native_extra_team_bits": team["native_extra_team_bits"],
            "phases": copy.deepcopy(team["phases"]),
        }})
    scenario = copy.deepcopy(module.DEFAULT)
    scenario["away_tactic_pool"] = {"enabled": True, "entries": entries,
                                    "uniform": {"enabled": True, "attribute_value": 15}}
    return scenario


@unittest.skipUnless(HAS_PRIVATE_FIXTURES, "需要 private 引擎夹具与 catalog")
class ServerQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_root = ROOT / "private" / "engine"
        cls.data_root = Path(tempfile.mkdtemp(prefix="server-data-"))
        cls.module = load_server_module(cls.engine_root, cls.data_root)
        sys.modules.pop("msvcrt", None)

    @classmethod
    def tearDownClass(cls):
        module = cls.module
        module.POOL.shutdown(wait=False, cancel_futures=True)
        if cls.data_root.exists():
            shutil.rmtree(cls.data_root, ignore_errors=True)

    def setUp(self):
        self.module = type(self).module
        self.module.JOBS.clear()
        self.lock = threading.Lock()
        self.starts = []
        self.ends = []
        self.running = False
        self.overlap = False
        self.records = []
        self.release = threading.Event()
        self.block = False
        self.module._execute = self.fake_execute

    def tearDown(self):
        self.release.set()
        self.wait_idle(timeout=10)
        self.module.JOBS.clear()

    def fake_execute(self, job, scenarios, seeds):
        with self.lock:
            if self.running:
                self.overlap = True
            self.running = True
            self.starts.append(job["id"])
            self.records.append(("start", job["id"], job.get("_pool_draws")))
        with self.module.LOCK:
            job.update(status="running", started=time.time())
        if self.block:
            self.release.wait(10)
        else:
            time.sleep(0.05)
        with self.module.LOCK:
            job.update(status="complete", completed=job["total"], finished=time.time())
            self.module.persist(job)
        with self.lock:
            self.running = False
            self.ends.append(job["id"])
            self.records.append(("end", job["id"], None))

    def wait_idle(self, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.module.LOCK:
                active = [job for job in self.module.JOBS.values()
                          if job.get("status") in ("queued", "running")]
            if not active:
                return True
            time.sleep(0.01)
        self.fail("运行队列未在限定时间内空闲")

    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        self.fail("条件未在限定时间内满足")

    def request(self, extra=None, **overrides):
        body = {"scenario": copy.deepcopy(self.module.DEFAULT), "seeds": [11, 12],
                "event_details": False}
        body.update(extra or {})
        body.update(overrides)
        return body

    def test_agent_submissions_run_one_at_a_time_in_creation_order(self):
        ids = [self.module.start_run(self.request())["id"] for _ in range(3)]
        self.wait_for(lambda: all(
            self.module.JOBS[job_id]["status"] == "complete" for job_id in ids))
        self.assertFalse(self.overlap)
        self.assertEqual(self.starts, ids)
        self.assertEqual(self.ends, ids)

    def test_ui_path_rejects_concurrency_while_agent_path_queues(self):
        body = self.request()
        first = self.module.start_run(body)
        self.wait_for(lambda: self.module.JOBS[first["id"]]["status"] == "running")
        with self.assertRaises(self.module.EngineBusy) as caught:
            self.module.start_run(self.request(), "/api/run", allow_queue=False)
        self.assertIn("已有比赛运行中", str(caught.exception))
        with self.assertRaises(ValueError):
            self.module.start_run(self.request(), "/api/run-episodes", allow_queue=False)
        queued = self.module.start_run(self.request())
        self.assertTrue(queued["queued"])
        self.assertEqual(queued["queue_position"], 2)
        self.wait_idle()
        self.assertEqual(self.module.JOBS[queued["id"]]["status"], "complete")

    def test_queued_cancel_marks_cancelled_and_skips_native_run(self):
        self.block = True
        first = self.module.start_run(self.request())
        self.wait_for(lambda: self.module.JOBS[first["id"]]["status"] == "running")
        queued = self.module.start_run(self.request())
        queued_job = self.module.JOBS[queued["id"]]
        self.assertEqual(queued_job["status"], "queued")
        self.assertEqual(queued["queue_position"], 2)
        self.module.cancel_job(queued_job)
        self.assertEqual(queued_job["status"], "cancelled")
        self.assertTrue(queued_job["_cancel"])
        self.release.set()
        self.wait_idle()
        self.assertNotIn(queued["id"], self.starts)
        self.assertEqual(self.module.JOBS[queued["id"]]["status"], "cancelled")

    def test_resume_requires_idle_queue(self):
        self.block = True
        first = self.module.start_run(self.request())
        self.wait_for(lambda: self.module.JOBS[first["id"]]["status"] == "running")
        pending = {"id": "missing", "status": "error", "created": time.time(), "_dir": self.data_root}
        with self.assertRaises(self.module.EngineBusy):
            self.module.resume_job_api(pending, {})

    def test_pool_run_expands_each_entry_and_records_draws(self):
        self.block = False
        scenario = pool_scenario(self.module)
        reference = copy.deepcopy(self.module.DEFAULT)
        submitted = self.module.start_run({
            "scenario": scenario, "reference": reference, "seeds": [21, 22, 23],
            "event_details": False})
        job_id = submitted["id"]
        job = self.module.JOBS[job_id]
        self.assertEqual(submitted["total"], 6)
        self.assertEqual(submitted["mode"], "comparison")
        self.wait_for(lambda: self.module.JOBS[job_id]["status"] == "complete")
        provenance = json.loads((job["_dir"] / "provenance.json").read_text(encoding="utf8"))
        recorded = provenance["pool"]
        self.assertEqual(recorded["salt"], job_id)
        self.assertEqual([row["name"] for row in recorded["entries"]], ["池战术甲", "池战术乙"])
        self.assertEqual(set(recorded["draws"]), {"21", "22", "23"})
        self.assertEqual(len(provenance["configs"]), 4)
        for label in ("A", "B"):
            for index in range(2):
                config = job["_dir"] / f"{label}_pool{index}.bin"
                document = job["_dir"] / f"{label}_pool{index}.json"
                self.assertTrue(config.is_file())
                self.assertTrue(document.is_file())
                expanded = json.loads(document.read_text(encoding="utf8"))
                self.assertEqual(expanded["teams"][1]["tactic_name"],
                                 recorded["entries"][index]["name"])
                self.assertNotIn("away_tactic_pool", expanded)
        start = next(record for record in self.records if record[0] == "start")
        self.assertEqual(set(start[2]), {"21", "22", "23"})
        pool = job["tactic_pool"]
        self.assertEqual(pool["draws"]["total"], 3)
        self.assertEqual(len(pool["entries"]), 2)

    def test_pool_rotation_plan_expands_every_entry_in_round_order(self):
        scenario=pool_scenario(self.module)
        scenario['away_tactic_pool']['rotation']={'enabled':True,'rounds':2}
        reference=copy.deepcopy(self.module.DEFAULT)
        submitted=self.module.start_run({
            "scenario":scenario,"reference":reference,"seeds":[41,42,43,44],
            "event_details":False})
        self.assertEqual(submitted["total"],8)
        job=self.module.JOBS[submitted["id"]]
        self.wait_for(lambda: self.module.JOBS[submitted["id"]]["status"]=="complete")
        self.assertEqual(job["_pool_draws"],{"41":0,"42":1,"43":0,"44":1})
        self.assertEqual(job["tactic_pool"]["mode"],"rotation")
        self.assertEqual(job["tactic_pool"]["rounds"],2)
        self.assertEqual(job["tactic_pool"]["players"],"uniform")
        provenance=json.loads((job["_dir"]/"provenance.json").read_text(encoding="utf8"))
        self.assertEqual(provenance["pool"]["mode"],"rotation")
        self.assertEqual(provenance["pool"]["rounds"],2)
        for label in ("A","B"):
            names=[item["teams"][1]["tactic_name"]for item in job["_pool_variants"][label]]
            self.assertEqual(names,["池战术甲","池战术乙"])

    def test_pool_rotation_rejects_seed_count_mismatch(self):
        scenario=pool_scenario(self.module)
        scenario['away_tactic_pool']['rotation']={'enabled':True,'rounds':2}
        with self.assertRaises(ValueError)as caught:
            self.module.start_run({"scenario":scenario,"seeds":[1,2,3],"event_details":False})
        self.assertIn("2 套 × 2 轮 = 4 场",str(caught.exception))
        with self.assertRaises(ValueError):
            self.module.start_run({"scenario":scenario,"seeds":[1,2,3,4,5],"event_details":False})

    def test_pool_real_roster_expands_saved_players(self):
        scenario=pool_scenario(self.module)
        players=[{'name':f'存档球员{index+1}','source_uid':900+index,
            'attributes':[10]*15+[50]*54,'native_profile':{}}for index in range(11)]
        roster={'club_uid':7,'club':'乙队','coach':'乙队主教练','source':'coach_preset',
            'roster_size':11,'lineup':list(range(11)),'players':players}
        for entry in scenario['away_tactic_pool']['entries']:entry["roster"]=copy.deepcopy(roster)
        scenario['away_tactic_pool']['real']={'enabled':True}
        submitted=self.module.start_run({"scenario":scenario,"seeds":[31],"event_details":False})
        job=self.module.JOBS[submitted["id"]]
        self.wait_for(lambda: self.module.JOBS[submitted["id"]]["status"]=="complete")
        self.assertEqual(job["tactic_pool"]["players"],"real")
        self.assertTrue(all(row["roster"]for row in job["tactic_pool"]["entries"]))
        index=job["_pool_draws"]["31"]
        expanded=job["_pool_variants"]["B"][index]
        away=expanded["teams"][1]
        self.assertEqual(away["roster_size"],11)
        self.assertEqual(away["lineup"],list(range(11)))
        self.assertEqual([player["source_uid"]for player in away["players"][:11]],
            list(range(900,911)))
        self.assertEqual([player["name"]for player in away["players"][:11]],
            [f"存档球员{index+1}"for index in range(11)])
        self.assertEqual(away["players"][0]["attributes"],[10]*15+[50]*54)
        config=job["_dir"]/f"B_pool{index}.json"
        saved=json.loads(config.read_text(encoding="utf8"))
        self.assertEqual(saved["teams"][1]["players"][0]["name"],"存档球员1")

    def test_apply_roster_output_passes_real_validation(self):
        module = self.module
        library = module.SAVE_LIBRARY
        key = "abcdef0123456789"
        folder = library.root / key
        folder.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "dataset.json").write_text(json.dumps({
            "clubs": [{"uid": 2, "name": "乙队", "short_name": "乙"}],
            "source": "C:/saves/career.fm", "source_sha256": "a" * 64,
            "date": "2027-01-15", "build": "27.1.0"}, ensure_ascii=False), encoding="utf8")
        (folder / "rosters").mkdir(exist_ok=True)
        positions = ["gk", "sw", "dl", "dc", "dr", "dm", "ml", "mc", "mr", "aml",
                     "amc", "amr", "stc", "wbl", "wbr"]
        people = [{"unique_id": 900 + index, "name": f"乙队球员{index}", "club_uid": 2,
                   "team_slot": 0, "positions": {name: 10 for name in positions},
                   "ability": {"current": 100 + index}, "personality": None,
                   "trait_bits": None, "reputation": {"home": 0, "current": 0, "world": 0}}
                  for index in range(23)]
        (folder / "rosters" / "2.json").write_text(json.dumps(people, ensure_ascii=False),
                                                   encoding="utf8")
        scenario = copy.deepcopy(module.DEFAULT)
        with mock.patch.object(library, "player_values",
                               side_effect=lambda person: ([10] * 15 + [50] * 54, {})):
            result = library.apply_roster(key, 2, scenario)
        validated = module.validate_scenario(result["scenario"])
        home = validated["teams"][0]
        self.assertEqual(home["roster_size"], 23)
        self.assertEqual(len(home["squad"]), 23)
        self.assertEqual({player["source_uid"] for player in home["players"][:23]},
                         set(range(900, 923)))
        self.assertEqual(home["players"][0]["attributes"], [10] * 15 + [50] * 54)
        self.assertEqual(result["source"]["club"], "乙")
        self.assertEqual(result["source"]["match_roster_count"], 23)

    def test_pool_rejects_native_generation_and_setpiece_episodes(self):
        scenario = pool_scenario(self.module)
        generated = copy.deepcopy(scenario)
        generated["native_generation"] = {}
        with self.assertRaises(ValueError):
            self.module.start_run({"scenario": generated, "seeds": [1],
                                   "event_details": False})
        with self.assertRaises(ValueError) as caught:
            self.module.start_run({"scenario": scenario, "seeds": [1],
                                   "event_details": True}, "/api/run-episodes")
        self.assertIn("战术池", str(caught.exception))

    def test_experimental_execution_survives_pool_expansion(self):
        module = self.module
        original = module.ENGINE_DLL_SHA256
        module.ENGINE_DLL_SHA256 = next(iter(module.EXECUTION_EXPERIMENT_DLLS))
        try:
            scenario = pool_scenario(module)
            execution = [{"understanding": 10, "buy_in": 20, "opposition": 30},
                         {"understanding": 40, "buy_in": 50, "opposition": 60}]
            scenario["experimental_execution"] = execution
            submitted = module.start_run({"scenario": scenario, "seeds": [31],
                                          "event_details": False})
            job = module.JOBS[submitted["id"]]
            self.wait_idle()
            expanded = job["_pool_variants"]["B"]
            self.assertEqual(len(expanded), 2)
            for item in expanded:
                self.assertEqual(item["experimental_execution"], execution)
            document = json.loads((job["_dir"] / "B_pool1.json").read_text(encoding="utf8"))
            self.assertEqual(document["experimental_execution"], execution)
            provenance = json.loads((job["_dir"] / "provenance.json").read_text(encoding="utf8"))
            self.assertEqual(len(provenance["configs"]), 2)
        finally:
            module.ENGINE_DLL_SHA256 = original

    def test_setpiece_episode_branch_keeps_isolated_runtime(self):
        submitted = self.module.start_run({"scenario": copy.deepcopy(self.module.DEFAULT),
                                           "seeds": [41, 42], "event_details": True,
                                           "type": 6, "side": 0, "variant": 0},
                                          "/api/run-episodes")
        job = self.module.JOBS[submitted["id"]]
        self.assertEqual(submitted["total"], 2)
        self.assertEqual(job["experiment_type"], "setpiece_episode")
        self.assertEqual(job["runtime_mode"], "isolated_native_episode")
        self.assertEqual(job["jobs_per_native_session"], 1)
        self.assertEqual(job["episode_settings"]["tested_type"], 6)
        self.assertEqual(job["episode_settings"]["type"], 6)
        self.wait_idle()

    def test_unknown_run_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self.module.start_run(self.request(), "/api/lab/status")

    def test_ui_http_handler_keeps_409_while_agent_router_queues(self):
        self.block = True
        first = self.module.start_run(self.request())
        self.wait_for(lambda: self.module.JOBS[first["id"]]["status"] == "running")
        module = self.module
        token = "t" * 64
        port = 8765
        body = json.dumps(self.request(), ensure_ascii=False).encode("utf8")
        captured = []
        original_send = module.Handler.send
        original_token = module.AGENT_TOKEN
        module.AGENT_TOKEN = token
        module.Handler.send = lambda handler, value, status=200, kind=None, headers=None: \
            captured.append((status, value))
        try:
            handler = object.__new__(module.Handler)
            handler.path = "/api/run"
            handler.headers = {
                "Host": f"127.0.0.1:{port}",
                "Origin": f"http://127.0.0.1:{port}",
                "Cookie": f"fm27_session={token}",
                "Content-Length": str(len(body)),
            }
            handler.rfile = io.BytesIO(body)
            handler.wfile = io.BytesIO()
            handler.server = types.SimpleNamespace(server_address=("127.0.0.1", port))
            handler.do_POST()
        finally:
            module.Handler.send = original_send
            module.AGENT_TOKEN = original_token
        self.assertEqual(captured[0][0], 409)
        self.assertIn("已有比赛运行中", captured[0][1]["error"])


    def test_ui_validate_accepts_large_pool_bodies_within_new_limit(self):
        module = self.module
        token = "t" * 64
        port = 8765
        captured = []
        original_send = module.Handler.send
        original_token = module.AGENT_TOKEN
        module.AGENT_TOKEN = token
        module.Handler.send = lambda handler, value, status=200, kind=None, headers=None: \
            captured.append((status, value))
        try:
            handler = object.__new__(module.Handler)
            handler.path = "/api/validate"
            handler.headers = {
                "Host": f"127.0.0.1:{port}",
                "Origin": f"http://127.0.0.1:{port}",
                "Cookie": f"fm27_session={token}",
                "Content-Length": str(0),
            }
            handler.rfile = None
            handler.wfile = io.BytesIO()
            handler.server = types.SimpleNamespace(server_address=("127.0.0.1", port))
            payload = json.dumps({**module.DEFAULT, "padding": "x" * 4400000},
                                  ensure_ascii=False).encode("utf8")
            handler.rfile = io.BytesIO(payload)
            handler.headers["Content-Length"] = str(len(payload))
            handler.do_POST()
            self.assertEqual(captured[-1][0], 200)
            self.assertIn("scenario", captured[-1][1])
            handler.rfile = io.BytesIO(b"{}")
            handler.headers["Content-Length"] = str(8500000)
            handler.do_POST()
            self.assertEqual(captured[-1][0], 400)
            self.assertIn("请求大小无效", captured[-1][1]["error"])
        finally:
            module.Handler.send = original_send
            module.AGENT_TOKEN = original_token


if __name__ == "__main__":
    unittest.main()
