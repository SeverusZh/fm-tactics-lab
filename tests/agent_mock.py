"""In-memory stand-in for the FM Tactics Lab agent API used by tests."""
from __future__ import annotations

import json
import secrets
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE) not in sys.path:
    sys.path.insert(0, str(_SOURCE))
import fm27_tactic_pool

POOL_PROFILE = fm27_tactic_pool.PROFILE


def make_scenario(first="主队", second="客队"):
    positions = ["GK", "LB", "CB", "CB", "RB", "DM", "CM", "CM", "LW", "ST", "RW"]
    positions_oop = ["GK", "LB", "CB", "CB", "RB", "DM", "CM", "CM", "LM", "ST", "RM"]

    def team(name, positions_value):
        players = [{
            "name": f"{name}球员{i + 1}",
            "native_id": i + 1,
            "attributes": [12] * 69,
            "native_profile": {},
        } for i in range(26)]
        plans = []
        for phase, names in (("in_possession", positions), ("out_of_possession", positions_oop)):
            assignments = [{
                "position": names[index],
                "role": f"role_{phase}_{index}",
                "duty": "0",
                "instructions": {},
                "target_player": 255,
                "target_position": 0,
            } for index in range(11)]
            plans.append({"phase": phase, "team_instructions": {}, "assignments": assignments})
        return {
            "name": name,
            "tactic_name": "测试战术",
            "mentality": 3,
            "phase_plans": plans,
            "lineup": list(range(11)),
            "players": players,
            "roster_size": 11,
            "captains": [],
            "takers": {},
        }

    return {
        "schema": 4,
        "rules": "game",
        "fixture": "bundled_match_pkm",
        "teams": [team(first, positions), team(second, positions)],
    }


def _pool_entry(name, team):
    phases = []
    for plan in team.get("phase_plans") or []:
        phases.append([
            {key: cell.get(key) for key in ("position", "role", "duty", "instructions",
                                            "target_player", "target_position")}
            for cell in plan.get("assignments") or []
        ])
    return {"name": name, "weight": 1, "tactic": {
        "tactic_name": name,
        "mentality": team.get("mentality", 3),
        "instructions": {},
        "native_extra_team_bits": "0",
        "phases": phases,
    }}


def make_pool_scenario(names=("池战术甲", "池战术乙")):
    """Scenario with an enabled, weighted away tactic pool on the second team."""
    value = make_scenario()
    team = value["teams"][1]
    value["away_tactic_pool"] = {
        "profile": POOL_PROFILE,
        "enabled": True,
        "entries": [_pool_entry(name, team) for name in names],
        "uniform": {"enabled": True, "attribute_value": 15},
    }
    return value


def enabled_pool(scenario):
    if not isinstance(scenario, dict):
        return None
    pool = scenario.get("away_tactic_pool")
    if isinstance(pool, dict) and pool.get("enabled") and pool.get("entries"):
        return pool
    return None


def make_run(variant, seed, sequence):
    return {
        "variant": variant,
        "seed": seed,
        "sequence": sequence,
        "result": {"score": [1, 0], "full_match_completed": True, "event": "natural_match_finished"},
        "statistics": {"teams": [{"xg": 1.2, "shots": 8, "possession": 55}, {"xg": 0.7, "shots": 5, "possession": 45}]},
        "events": {"collected": True, "goals": [], "cards": []},
        "verified": True,
        "attempts": 1,
        "elapsed_seconds": 1.5,
        "native_elapsed_seconds": 1.2,
        "log": f"{sequence:04d}_{variant}_seed_{seed}.jsonl",
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    @property
    def state(self):
        return self.server.state

    def _send(self, status, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        headers = headers or {}
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, status, body, kind="application/x-ndjson; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, code, message):
        self._send(status, {"error": {"code": code, "message": message,
                                      "details": {}, "retriable": False}})

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _auth(self):
        token = self.state.token
        header = self.headers.get("Authorization") or ""
        if not token or header == "Bearer " + token:
            return True
        self._error(401, "unauthorized", "缺少或错误 token")
        return False

    def do_GET(self):
        if not self._auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        self.state.record("GET", path, query, None, dict(self.headers))
        if path == "/api/agent/v1/health":
            return self._send(200, {"ok": True, "pid": 1, "server_version": "test"})
        if path == "/api/agent/v1/manifest":
            return self._send(200, {
                "api": "fm27lab/v1", "server_version": "test", "adapter_version": "test",
                "scenario_schema": 3, "scenario_view_schema": 4, "batch_schema": 1,
                "capabilities": ["free_run", "comparison", "fmf",
                                 "repair", "resume", "cancel", "idempotency"],
                "limits": {"max_seeds": 10000, "max_workers": 256,
                           "max_body_bytes": 8000000,
                           "max_import_bytes": 8000000, "max_draft_bytes": 5242880},
                "schemas": "/api/agent/v1/schemas",
            })
        if path == "/api/agent/v1/status":
            return self._send(200, {
                "engine_compatibility": {
                    "compatible": True, "can_simulate": True, "reason": "ok",
                    "message": "ok", "disposition": "verified",
                    "profile": "fm27_desktop_2493426_adapter_v1",
                },
                "active_job": None, "save_active": None,
                "server": {"pid": 1, "port": self.state.port, "api": "fm27lab/v1"},
            })
        if path == "/api/agent/v1/catalog":
            positions = [
                ("GK", 1), ("LB", 8), ("CB", 16), ("RB", 4), ("DM", 128),
                ("CM", 1024), ("LW", 4096), ("ST", 16384), ("RW", 2048),
                ("LM", 512), ("RM", 256),
            ]
            role_context = {
                key: {
                    position: [["MockGoalkeeper", "MockCentreBack"],
                               ["OPMockGoalkeeper", "OPMockCentreBack"]]
                    for position, _ in positions
                }
                for key in ("0:0", "0:1", "3:0", "3:1")
            }
            return self._send(200, {"catalog": {
                "positions": [{"id": position, "mask": mask} for position, mask in positions],
                "roles": [
                    {"id": "MockGoalkeeper", "label": "模拟门将"},
                    {"id": "MockCentreBack", "label": "模拟中卫"},
                    {"id": "MockMidfielder", "label": "模拟中场"},
                    {"id": "OPMockGoalkeeper", "label": "模拟无球门将"},
                    {"id": "OPMockCentreBack", "label": "模拟无球中卫"},
                    {"id": "OPMockMidfielder", "label": "模拟无球中场"},
                ],
                "role_eligibility_context": role_context,
                "duties": ["0", "2097152", "4194304"],
                "team_instructions": [{
                    "id": 1, "label": "传球方式", "phase": 0,
                    "options": [{"id": 11, "label": "短传"}, {"id": 12, "label": "直传"}],
                }],
            }})
        if path == "/api/agent/v1/defaults":
            return self._send(200, {"scenario": make_scenario()})
        if path == "/api/agent/v1/schemas":
            return self._send(200, {"tools": {"lab_status": {}}})
        if path == "/api/agent/v1/jobs":
            return self._send(200, self.state.jobs_page(query))
        parts = path.strip("/").split("/")
        if len(parts) >= 5 and parts[:4] == ["api", "agent", "v1", "jobs"]:
            job_id = parts[4]
            job = self.state.jobs.get(job_id)
            if job is None:
                return self._error(404, "not_found", "任务不存在")
            if len(parts) == 5:
                return self._send(200, self.state.job_detail(job, query))
            if len(parts) == 6 and parts[5] == "export":
                return self._send(200, self.state.job_export(job))
            if len(parts) == 7 and parts[5] == "logs":
                return self._send_raw(200, json.dumps({"event": "native_timings",
                                                       "log": parts[6]}) + "\n")
        return self._error(404, "unknown_endpoint", "路径不存在")

    def do_POST(self):
        if not self._auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        self.state.record("POST", path, {}, body, dict(self.headers))
        parts = path.strip("/").split("/")
        if path == "/api/agent/v1/runs":
            status, payload = self.state.create_job(body, "single")
            return self._send(status, payload)
        if path == "/api/agent/v1/validate":
            roles = [cell.get("role")
                     for team in (body.get("scenario") or {}).get("teams") or []
                     for plan in team.get("phase_plans") or []
                     for cell in plan.get("assignments") or []]
            if "BadRole" in roles:
                return self._error(400, "validation_failed", "该位置或当前阵型不可使用所选原版角色")
            return self._send(200, {"scenario": body.get("scenario"), "records": 30})
        if path == "/api/agent/v1/repair":
            return self._send(200, {"scenario": body.get("scenario"), "changes": []})
        if path == "/api/agent/v1/phase-plan":
            return self._send(200, {"scenario": body.get("scenario")})
        if path == "/api/agent/v1/engine/select":
            return self._send(200, {"compatible": True, "can_simulate": True,
                                    "message": "ok", "selected_game_root": body.get("game_root")})
        if path == "/api/agent/v1/selection":
            return self._send(200, {"scenario": body.get("scenario")})
        if path == "/api/agent/v1/fmf/import":
            return self._send(200, {"scenario": body.get("scenario"),
                                    "report": {"native_roundtrip_verified": True}})
        if path == "/api/agent/v1/fmf/export":
            return self._send(200, {"filename": "tactic.fmf", "path": "/tmp/tactic.fmf",
                                    "sha256": "0" * 64, "report": {"native_roundtrip_verified": True}})
        if path == "/api/agent/v1/setpiece/export":
            return self._send(200, {"filename": "setpiece.fmf", "path": "/tmp/setpiece.fmf",
                                    "sha256": "0" * 64, "report": {"native_roundtrip_verified": True}})
        if path == "/api/agent/v1/shutdown":
            return self._send(202, {"accepted": True})
        if len(parts) >= 6 and parts[:4] == ["api", "agent", "v1", "jobs"]:
            job_id = parts[4]
            action = parts[5]
            if job_id not in self.state.jobs:
                return self._error(404, "not_found", "任务不存在")
            if action == "cancel":
                return self._send(200, {"accepted": True})
            if action == "resume":
                return self._send(202, {"id": job_id})
            if action == "rename":
                return self._send(200, {"id": job_id, "name": body.get("name")})
            if action == "delete":
                self.state.jobs.pop(job_id, None)
                return self._send(200, {"id": job_id})
        return self._error(404, "unknown_endpoint", "路径不存在")


class MockAgentServer:
    def __init__(self, token=None, busy=False, slow_jobs=False):
        self.token = token if token is not None else secrets.token_hex(16)
        self.busy = busy
        self.slow_jobs = slow_jobs
        self.jobs = {}
        self.job_seeds = {}
        self.job_scenarios = {}
        self.job_pool_draws = {}
        self.calls = []
        self.lock = threading.Lock()
        self.next_job = 1
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.state = self
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def record(self, method, path, query, body, headers):
        with self.lock:
            self.calls.append({"method": method, "path": path, "query": query,
                               "body": body, "headers": headers})

    def create_job(self, body, mode):
        if self.busy:
            return self._error_response(409, "engine_busy", "已有比赛运行中")
        job_id = f"job{self.next_job:08d}"
        self.next_job += 1
        seeds = list(body.get("seeds") or [])
        pool = enabled_pool(body.get("scenario")) or enabled_pool(body.get("reference"))
        draws = {}
        entry_rows = []
        if pool:
            rotation = bool((pool.get("rotation") or {}).get("enabled"))
            entry_rows = [{"index": index, "name": entry.get("name"),
                           "weight": row["weight"],
                           "probability": None if rotation else row["probability"],
                           "roster": bool(entry.get("roster"))}
                          for index, (entry, row) in enumerate(zip(
                              pool["entries"], fm27_tactic_pool.probabilities(pool["entries"])))]
            draws = fm27_tactic_pool.draws(pool, seeds, job_id)
        total = len(seeds) * (2 if body.get("reference") else 1)
        scenarios = [("B", body.get("scenario"))]
        if body.get("reference"):
            scenarios.insert(0, ("A", body.get("reference")))
        runs = []
        sequence = 0
        for seed in seeds:
            for variant, _ in scenarios:
                sequence += 1
                run = make_run(variant, seed, sequence)
                if pool:
                    entry = entry_rows[draws[seed]]
                    run["tactic_pool_entry"] = {key: entry[key]
                                                for key in ("index", "name", "weight", "probability")}
                runs.append(run)
        job = {
            "id": job_id,
            "name": body.get("name") or "测试实验",
            "status": "complete",
            "completed": len(runs),
            "total": total or len(runs),
            "runs": runs,
            "failures": [],
            "mode": "comparison" if body.get("reference") else "single",
            "created": time.time(),
            "workers": body.get("workers") or 1,
            "event_details": body.get("event_details", True),
            "variant_names": {variant: "方案" + variant for variant, _ in scenarios},
            "team_names": {},
            "metrics": {},
            "paired": {"n": 0, "goal_difference_delta": None},
            "eta_seconds": 0,
            "matches_per_minute": 0,
        }
        if pool:
            summary = fm27_tactic_pool.summary({**pool, "entries": pool["entries"]})
            job["tactic_pool"] = {
                "profile": pool.get("profile") or POOL_PROFILE,
                "enabled": True,
                "salt": job_id,
                "mode": summary["mode"], "rounds": summary["rounds"], "players": summary["players"],
                "uniform": pool.get("uniform"),
                "entries": entry_rows,
                "draws": {"total": len(draws),
                          "counts": fm27_tactic_pool.completed_draw_counts(runs, len(entry_rows))},
            }
        self.jobs[job_id] = job
        self.job_seeds[job_id] = seeds
        self.job_scenarios[job_id] = {variant: scenario for variant, scenario in scenarios
                                      if isinstance(scenario, dict)}
        self.job_pool_draws[job_id] = draws
        if self.slow_jobs:
            job.update(status="running", completed=0)
            def finish():
                time.sleep(0.25)
                job.update(status="complete", completed=job["total"])
            threading.Thread(target=finish, daemon=True).start()
        return self._send_response(202, {"id": job_id, "total": job["total"],
                                         "workers": body.get("workers") or 1})

    def _send_response(self, status, payload):
        return status, payload

    def hold_job(self, job_id):
        job = self.jobs[job_id]
        job.update(status="running", completed=0, eta_seconds=10)
        return job

    def release_job(self, job_id):
        job = self.jobs[job_id]
        job.update(status="complete", completed=job.get("total") or 0, eta_seconds=0)
        return job

    def _error_response(self, status, code, message):
        return status, {"error": {"code": code, "message": message,
                                  "details": {}, "retriable": False}}

    def jobs_page(self, query):
        limit = int(query.get("limit") or 50)
        offset = int(query.get("offset") or 0)
        status = query.get("status")
        values = [job for job in self.jobs.values() if not status or job["status"] == status]
        values.sort(key=lambda job: job.get("created", 0))
        page = values[offset:offset + limit]
        return {"jobs": page, "total": len(values), "limit": limit, "offset": offset,
                "next_offset": offset + limit if offset + limit < len(values) else None}

    def job_detail(self, job, query):
        runs = list(job.get("runs") or [])
        runs.sort(key=lambda run: run.get("sequence") or 0)
        variant = query.get("variant")
        if variant:
            runs = [run for run in runs if run.get("variant") == variant]
        total = len(runs)
        offset = int(query.get("runs_offset") or 0)
        limit = int(query.get("runs_limit") or total or 50)
        page = runs[offset:offset + limit]
        value = dict(job)
        value["runs"] = page
        value["runs_total"] = total
        value["runs_truncated"] = offset + len(page) < total
        return value

    def job_export(self, job):
        job_id = job["id"]
        pool = job.get("tactic_pool") if isinstance(job.get("tactic_pool"), dict) else None
        draws = self.job_pool_draws.get(job_id) or {}
        provenance = {"seeds": self.job_seeds.get(job_id) or [],
                      "fixture_sha256": "0" * 64}
        if pool and draws:
            provenance["pool"] = {"salt": pool.get("salt"),
                                  "mode": pool.get("mode", "random"),
                                  "rounds": pool.get("rounds", 1),
                                  "players": pool.get("players", "uniform"),
                                  "entries": pool.get("entries"),
                                  "draws": {str(seed): index for seed, index in draws.items()}}
        scenarios = self.job_scenarios.get(job_id) or {
            "A": make_scenario("对照主队", "对照客队"), "B": make_scenario()}
        return {"summary": {key: value for key, value in job.items() if key != "runs"},
                "scenarios": scenarios,
                "provenance": provenance}


def start_server(**kwargs):
    return MockAgentServer(**kwargs).start()
