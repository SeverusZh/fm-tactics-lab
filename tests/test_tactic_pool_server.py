"""Offline integration tests for the away tactic pool run submission path."""
import copy
import io
import json
import os
import shutil
import subprocess  # noqa: F401  (import before stubbing msvcrt so subprocess stays POSIX)
import sys
import tempfile
import types
import unittest
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


class _RecordingPool:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args):
        self.submissions.append((fn, args))


class _PostRequest:
    def __init__(self, path, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf8")
        self.path = path
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)
        self.response = None

    def send(self, value, status=200, kind="application/json; charset=utf-8"):
        self.response = (status, value)


def post(module, path, payload):
    request = _PostRequest(path, payload)
    module.Handler.do_POST(request)
    if request.response is None:
        raise AssertionError("HTTP handler produced no response")
    return request.response


@unittest.skipUnless(HAS_PRIVATE_FIXTURES, "需要 private 引擎夹具与 catalog")
class PoolRunSubmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_root = ROOT / "private" / "engine"
        cls.data_root = Path(tempfile.mkdtemp(prefix="pool-run-"))
        cls.module = load_server_module(cls.engine_root, cls.data_root)
        sys.modules.pop("msvcrt", None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.data_root, ignore_errors=True)

    def setUp(self):
        self.module = type(self).module
        self.module.JOBS.clear()
        self.module.POOL = _RecordingPool()

    def tearDown(self):
        self.module.JOBS.clear()

    def start(self, scenario, seeds, reference=None):
        payload = {"scenario": scenario, "seeds": seeds, "event_details": False}
        if reference is not None:
            payload["reference"] = reference
        return post(self.module, "/api/run", payload)

    def test_rotation_runs_every_entry_for_each_round(self):
        scenario = pool_scenario(self.module)
        scenario["away_tactic_pool"]["rotation"] = {"enabled": True, "rounds": 2}
        reference = copy.deepcopy(self.module.DEFAULT)
        status, value = self.start(scenario, [41, 42, 43, 44], reference)
        self.assertEqual(status, 202)
        job = self.module.JOBS[value["id"]]
        self.assertEqual(job["total"], 8)
        self.assertEqual(job["_pool_draws"], {"41": 0, "42": 1, "43": 0, "44": 1})
        self.assertEqual(job["tactic_pool"]["mode"], "rotation")
        self.assertEqual(job["tactic_pool"]["rounds"], 2)
        self.assertEqual(job["tactic_pool"]["players"], "uniform")
        self.assertEqual([row["roster"] for row in job["tactic_pool"]["entries"]], [False, False])
        provenance = json.loads((job["_dir"] / "provenance.json").read_text(encoding="utf8"))
        self.assertEqual(provenance["pool"]["mode"], "rotation")
        self.assertEqual(provenance["pool"]["rounds"], 2)
        self.assertEqual(provenance["pool"]["players"], "uniform")
        for label in ("A", "B"):
            names = [item["teams"][1]["tactic_name"] for item in job["_pool_variants"][label]]
            self.assertEqual(names, ["池战术甲", "池战术乙"])
        self.assertEqual(len(self.module.POOL.submissions), 1)
        self.assertEqual(self.module.POOL.submissions[0][0].__name__, "execute")

    def test_rotation_requires_seed_count_matching_entries_times_rounds(self):
        scenario = pool_scenario(self.module)
        scenario["away_tactic_pool"]["rotation"] = {"enabled": True, "rounds": 2}
        status, value = self.start(scenario, [1, 2, 3])
        self.assertEqual(status, 400)
        self.assertIn("2 套 × 2 轮 = 4 场", value["error"])
        self.assertEqual(self.module.JOBS, {})
        self.assertEqual(self.module.POOL.submissions, [])

    def test_real_roster_replaces_away_players_and_lineup(self):
        scenario = pool_scenario(self.module)
        players = [{"name": f"存档球员{index + 1}", "source_uid": 900 + index,
                    "attributes": [10] * 15 + [50] * 54, "native_profile": {}} for index in range(11)]
        roster = {"club_uid": 7, "club": "乙队", "coach": "乙队主教练", "source": "coach_preset",
                  "roster_size": 11, "lineup": list(range(11)), "players": players}
        for entry in scenario["away_tactic_pool"]["entries"]:
            entry["roster"] = copy.deepcopy(roster)
        scenario["away_tactic_pool"]["real"] = {"enabled": True}
        status, value = self.start(scenario, [31])
        self.assertEqual(status, 202)
        job = self.module.JOBS[value["id"]]
        self.assertEqual(job["tactic_pool"]["players"], "real")
        self.assertEqual([row["roster"] for row in job["tactic_pool"]["entries"]], [True, True])
        index = job["_pool_draws"]["31"]
        away = job["_pool_variants"]["B"][index]["teams"][1]
        self.assertEqual(away["roster_size"], 11)
        self.assertEqual(away["lineup"], list(range(11)))
        self.assertEqual([player["source_uid"] for player in away["players"][:11]], list(range(900, 911)))
        self.assertEqual([player["name"] for player in away["players"][:11]],
                         [f"存档球员{number}" for number in range(1, 12)])
        self.assertEqual(away["players"][0]["attributes"], [10] * 15 + [50] * 54)
        saved = json.loads((job["_dir"] / f"B_pool{index}.json").read_text(encoding="utf8"))
        self.assertEqual(saved["teams"][1]["players"][0]["name"], "存档球员1")

    def test_real_roster_requires_every_entry_to_carry_a_roster(self):
        scenario = pool_scenario(self.module)
        scenario["away_tactic_pool"]["real"] = {"enabled": True}
        status, value = self.start(scenario, [31])
        self.assertEqual(status, 400)
        self.assertIn("真实名单", value["error"])
        self.assertEqual(self.module.JOBS, {})

    def test_resume_rejects_reordered_rotation_seeds(self):
        scenario = pool_scenario(self.module)
        scenario["away_tactic_pool"]["rotation"] = {"enabled": True, "rounds": 2}
        status, value = self.start(scenario, [41, 42, 43, 44])
        self.assertEqual(status, 202)
        job = self.module.JOBS[value["id"]]
        path = job["_dir"] / "provenance.json"
        provenance = json.loads(path.read_text(encoding="utf8"))
        provenance["seeds"] = list(reversed(provenance["seeds"]))
        path.write_text(json.dumps(provenance, indent=2), encoding="utf8")
        with self.assertRaises(ValueError) as caught:
            self.module.resume_job(job, 1)
        self.assertIn("轮战模式客队战术排期与原任务不符", str(caught.exception))

    def test_apply_roster_route_passes_through_save_library(self):
        calls = []

        class _Library:
            real_active = None
            active = None

            def apply_roster(self, key, club, scenario):
                calls.append((key, club))
                return {"scenario": scenario, "source": {"club_uid": club}}

        previous = self.module.SAVE_LIBRARY
        self.module.SAVE_LIBRARY = _Library()
        try:
            status, value = post(self.module, "/api/save/apply-roster",
                                 {"id": "abcdef0123456789", "club_uid": 7,
                                  "scenario": self.module.DEFAULT})
        finally:
            self.module.SAVE_LIBRARY = previous
        self.assertEqual(status, 200)
        self.assertEqual(calls, [("abcdef0123456789", 7)])
        self.assertEqual(value["source"]["club_uid"], 7)


if __name__ == "__main__":
    unittest.main()
