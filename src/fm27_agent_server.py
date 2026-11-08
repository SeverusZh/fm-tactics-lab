"""Agent namespace router. All football work is delegated to the running server."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
from pathlib import Path

import fm27_agent_contract as contract


class AgentHttpError(Exception):
    def __init__(self, status, code, message, details=None, retriable=False,
                 retry_after_seconds=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.retriable = retriable
        self.retry_after_seconds = retry_after_seconds

    def payload(self):
        return contract.error_payload(self.code, self.message, self.details,
                                      self.retriable, self.retry_after_seconds)


class Router:
    def __init__(self, app, token=None, port=0, idempotency=None):
        self.app = app
        self.token = token
        self.port = int(port)
        self.idempotency = idempotency or contract.IdempotencyStore()
        self._idempotency_lock = threading.Lock()

    # ---------- helpers ----------

    def _parts(self, path):
        if not isinstance(path, str) or not path.startswith(contract.PREFIX):
            raise AgentHttpError(404, "unknown_endpoint", f"未知路径：{path}")
        suffix = path[len(contract.PREFIX):].strip("/")
        return suffix.split("/") if suffix else []

    def _ok(self, payload, status=200, headers=None):
        return status, payload, headers or {}

    def _ensure_idle(self):
        with self.app.LOCK:
            active = [job for job in self.app.JOBS.values()
                      if job.get("status") in ("queued", "running")]
        if active:
            job = sorted(active, key=lambda item: item.get("created", 0))[0]
            raise AgentHttpError(409, "engine_busy", "已有比赛运行中",
                                 {"active_job": job.get("id")}, True, 30)

    def _call(self, function, *args):
        try:
            return function(*args)
        except AgentHttpError:
            raise
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            message = str(error)
            if "已有比赛运行中" in message:
                raise AgentHttpError(409, "engine_busy", message, {}, True, 30) from None
            if "请等待存档" in message or "正在解析" in message or "解析中" in message:
                raise AgentHttpError(409, "conflict", message, {}, True, 10) from None
            raise AgentHttpError(400, "validation_failed", message) from None
        except OSError as error:
            raise AgentHttpError(500, "internal_error", str(error)) from None
        except Exception as error:
            raise AgentHttpError(500, "internal_error", str(error)) from None

    def limits(self):
        return {
            "max_seeds": 10000,
            "max_workers": int(self.app.BATCH_LIMITS.get("maximum", 4)),
            "max_opponents": 40,
            "max_career_count": 10000,
            "max_body_bytes": 1500000,
            "max_import_bytes": 6000000,
            "max_draft_bytes": 5242880,
        }

    def manifest(self):
        try:
            adapter = json.loads((self.app.NATIVE / "adapter_version.json").read_text(encoding="utf8"))
        except (OSError, ValueError):
            adapter = {}
        compatibility = self.app.ENGINE_COMPATIBILITY if isinstance(self.app.ENGINE_COMPATIBILITY, dict) else {}
        profile = compatibility.get("profile")
        return {
            "api": contract.API,
            "server_version": contract.APP_VERSION,
            "adapter_version": adapter.get("version"),
            "engine_build": profile.get("version") if isinstance(profile, dict) else None,
            "scenario_schema": 3,
            "scenario_view_schema": 4,
            "batch_schema": 1,
            "capabilities": ["free_run", "career_save", "comparison", "fmf", "repair",
                             "resume", "cancel", "idempotency"],
            "limits": self.limits(),
            "schemas": contract.PREFIX + "/schemas",
        }

    def status(self):
        active = None
        with self.app.LOCK:
            for job in sorted(self.app.JOBS.values(), key=lambda item: item.get("created", 0)):
                if job.get("status") in ("queued", "running"):
                    active = {key: value for key, value in job.items() if not key.startswith("_")}
                    active.pop("runs", None)
                    break
        return {
            "engine_compatibility": self.app.ENGINE_COMPATIBILITY,
            "active_job": active,
            "save_active": self.app.SAVE_LIBRARY.active,
            "server": {"pid": os.getpid(), "port": self.port, "api": contract.API},
        }

    def _public_job(self, job):
        return {key: value for key, value in job.items() if not key.startswith("_")}

    def jobs_page(self, query):
        status = query.get("status")
        values = []
        with self.app.LOCK:
            for job in self.app.JOBS.values():
                if status and job.get("status") != status:
                    continue
                value = self._public_job(job)
                value.pop("runs", None)
                values.append(value)
        values.sort(key=lambda item: item.get("created", 0))
        return contract.paginate(values, query.get("limit"), query.get("offset"), "jobs")

    def _job_detail(self, job, query):
        runs = [dict(run) for run in (job.get("runs") or [])]
        runs.sort(key=lambda run: run.get("sequence") or 0)
        variant = query.get("variant")
        if variant:
            runs = [run for run in runs if run.get("variant") == variant]
        total = len(runs)
        value = self._public_job(job)
        progress = query.get("progress")
        if progress is not None and str(progress).isdigit():
            completed = int(progress)
            unchanged = completed == int(job.get("completed") or 0)
            delta = completed <= int(job.get("completed") or 0) and all("sequence" in run for run in runs)
            value["runs_unchanged"] = unchanged
            if not unchanged and delta:
                value["runs_delta"] = [run for run in runs if (run.get("sequence") or 0) > completed]
            elif unchanged:
                value["runs"] = []
            else:
                value["runs"] = runs
            value["runs_total"] = total
            return value
        offset = contract.clamp_offset(query.get("runs_offset"))
        limit = contract.clamp_limit(query.get("runs_limit"))
        value["runs"] = runs[offset:offset + limit]
        value["runs_total"] = total
        value["runs_truncated"] = offset + len(value["runs"]) < total
        return value

    def job_export(self, job):
        package = {"summary": self._public_job(job), "scenarios": {}}
        directory = Path(job["_dir"])
        for variant in (job.get("schedule") or ("A", "B")):
            path = directory / f"{variant}.json"
            if path.exists():
                package["scenarios"][variant] = self.app.phase_inputs.pack(
                    json.loads(path.read_text(encoding="utf8")), self.app.CATALOG)
        package["provenance"] = json.loads((directory / "provenance.json").read_text(encoding="utf8"))
        return package

    def job_logs(self, job, name):
        logs = {run.get("log") for run in (job.get("runs") or [])}
        if name not in logs:
            raise AgentHttpError(404, "not_found", "日志不存在")
        path = Path(job["_dir"]) / name
        try:
            return path.read_bytes()
        except OSError:
            raise AgentHttpError(404, "not_found", "日志不存在") from None

    def _schema_bundle(self):
        try:
            from fm27_agent import schemas
        except ImportError:
            return {"tools": [], "resources": [], "prompts": []}
        value = {"tools": getattr(schemas, "TOOLS", []),
                 "resources": getattr(schemas, "RESOURCES", []),
                 "prompts": getattr(schemas, "PROMPTS", [])}
        bundle = getattr(schemas, "schema_bundle", None)
        return bundle() if callable(bundle) else value

    # ---------- GET ----------

    def get(self, path, query):
        parts = self._parts(path)
        try:
            if parts == ["health"]:
                return self._ok({"ok": True, "pid": os.getpid(),
                                 "server_version": contract.APP_VERSION})
            if parts == ["manifest"]:
                return self._ok(self.manifest())
            if parts == ["status"]:
                return self._ok(self.status())
            if parts == ["catalog"]:
                return self._ok({"catalog": self.app.CATALOG})
            if parts == ["defaults"]:
                return self._ok({"scenario": self.app.phase_inputs.pack(
                    self.app.DEFAULT, self.app.CATALOG)})
            if parts == ["schemas"]:
                return self._ok(self._schema_bundle())
            if parts == ["jobs"]:
                return self._ok(self.jobs_page(query))
            if len(parts) >= 2 and parts[0] == "jobs":
                job = self.app.JOBS.get(parts[1])
                if job is None:
                    raise AgentHttpError(404, "not_found", "任务不存在")
                if len(parts) == 2:
                    return self._ok(self._job_detail(job, query))
                if len(parts) == 3 and parts[2] == "export":
                    return self._ok(self._call(self.job_export, job))
                if len(parts) == 4 and parts[2] == "logs":
                    content = self._call(self.job_logs, job, parts[3])
                    return self._ok(content, headers={"Content-Type": "application/x-ndjson; charset=utf-8"})
            if len(parts) == 2 and parts[0] == "career" and parts[1] == "status":
                return self._ok(self._call(self.app.SAVE_LIBRARY.status, query.get("id")))
            raise AgentHttpError(404, "unknown_endpoint", f"未知路径：{path}")
        except AgentHttpError:
            raise
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            raise AgentHttpError(400, "validation_failed", str(error)) from None
        except Exception as error:
            raise AgentHttpError(500, "internal_error", str(error)) from None

    # ---------- POST ----------

    def _idempotent(self, path):
        return path in ("/runs", "/career/import", "/career/run") or path.endswith("/resume")

    def post(self, path, data, headers=None):
        headers = headers or {}
        key = headers.get("Idempotency-Key")
        parts = self._parts(path)
        relative = "/" + "/".join(parts)
        if key and self._idempotent(relative):
            digest = contract.json_digest(data)
            with self._idempotency_lock:
                kind, cached = self.idempotency.check(key, digest)
            if kind == "conflict":
                raise AgentHttpError(409, "idempotency_conflict",
                                     "同一幂等键的请求内容不同")
            if kind == "replay":
                status, payload = cached
                return status, payload, {"Idempotency-Replayed": "true"}
            status, payload, extra = self._dispatch_post(parts, data)
            with self._idempotency_lock:
                self.idempotency.remember(key, digest, status, payload)
            return status, payload, extra
        return self._dispatch_post(parts, data)

    def _dispatch_post(self, parts, data):
        try:
            if parts == ["shutdown"]:
                self.app.request_shutdown()
                return self._ok({"accepted": True}, 202)
            if parts == ["runs"]:
                self._ensure_idle()
                return self._ok(self._call(self.app.start_run, data), 202)
            if parts == ["validate"]:
                scenario = self._call(self.app.validate_scenario, data["scenario"])
                records = (len(self._call(self.app.encode_scenario, scenario)) - 12) // 20
                return self._ok({"scenario": scenario, "records": records})
            if parts == ["repair"]:
                return self._ok(self._call(self.app.repair_saved_scenario, data["scenario"]))
            if parts == ["phase-plan"]:
                scenario = self._call(self.app.validate_scenario, data["scenario"])
                return self._ok({"scenario": self.app.phase_inputs.pack(scenario, self.app.CATALOG)})
            if parts == ["engine", "select"]:
                self._ensure_idle()
                return self._ok(self._call(self.app.select_engine, data["game_root"]))
            if parts == ["career", "import"]:
                return self._ok(self._call(self.app.SAVE_LIBRARY.start, data["path"]), 202)
            if parts == ["career", "import", "cancel"]:
                return self._ok(self._call(self.app.SAVE_LIBRARY.cancel_import, data.get("id")))
            if parts == ["career", "team"]:
                return self._ok(self._call(self.app.SAVE_LIBRARY.club,
                                           data["save_id"], data["club_uid"]))
            if parts == ["career", "load"]:
                self._ensure_idle()
                return self._ok(self._call(
                    self.app.SAVE_LIBRARY.load_team,
                    data["save_id"], data["club_uid"], data["tactic_index"],
                    data.get("lineup"), 0, data["scenario"], data.get("bench")))
            if parts == ["career", "selection"]:
                self._ensure_idle()
                return self._ok(self._call(
                    self.app.SAVE_LIBRARY.select_squad,
                    data["scenario"], 0, data["lineup"], data["bench"]))
            if parts == ["career", "opponents"]:
                self._ensure_idle()
                return self._ok(self._call(self.app.SAVE_LIBRARY.begin_opponents,
                                           data["save_id"], data["club_uid"]))
            if parts == ["career", "opponents", "cancel"]:
                return self._ok(self._call(self.app.SAVE_LIBRARY.cancel_opponents,
                                           data["save_id"], data["club_uid"]))
            if parts == ["career", "preview"]:
                return self._ok(self._career_preview(data))
            if parts == ["career", "run"]:
                self._ensure_idle()
                return self._ok(self._call(self.app.create_save_job, data), 202)
            if parts == ["fmf", "import"]:
                return self._ok(self._call(self.app.import_fmf, data))
            if parts == ["fmf", "export"]:
                return self._ok(self._export_archive(self.app.export_fmf, data))
            if parts == ["setpiece", "export"]:
                return self._ok(self._export_archive(self.app.export_setpiece, data))
            if len(parts) >= 3 and parts[0] == "jobs":
                job = self.app.JOBS.get(parts[1])
                if job is None:
                    raise AgentHttpError(404, "not_found", "任务不存在")
                action = parts[2]
                if action == "cancel":
                    return self._ok(self._call(self.app.cancel_job, job))
                if action == "resume":
                    return self._ok(self._call(self.app.resume_job_api, job, data), 202)
                if action == "rename":
                    return self._ok(self._call(self.app.rename_job, job, data.get("name")))
                if action == "delete":
                    if job.get("status") in ("queued", "running"):
                        raise AgentHttpError(409, "conflict", "请等待实验结束或取消后再删除")
                    return self._ok(self._call(self.app.delete_job, job))
            raise AgentHttpError(404, "unknown_endpoint", "未知路径")
        except AgentHttpError:
            raise
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            message = str(error)
            if "已有比赛运行中" in message:
                raise AgentHttpError(409, "engine_busy", message, {}, True, 30) from None
            raise AgentHttpError(400, "validation_failed", message) from None
        except OSError as error:
            raise AgentHttpError(500, "internal_error", str(error)) from None
        except Exception as error:
            raise AgentHttpError(500, "internal_error", str(error)) from None

    def _career_preview(self, data):
        report = self.app.SAVE_LIBRARY.inspect_opponents(data["save_id"], data["club_uid"])
        opponent = next((row for row in report["opponents"] if row["key"] == data["key"]), None)
        if opponent is None:
            raise ValueError("对手方案未通过核实")
        scenario = self.app.validate_scenario(data["scenario"])
        if opponent.get("source_kind") == "original_ai_generation":
            return self.app.desktop_generation_catalog.preview(
                self.app.SAVE_LIBRARY, data["save_id"], int(data["club_uid"]), opponent, scenario)
        team = self.app.SAVE_LIBRARY.opponent_team(
            data["save_id"], opponent.get("fixture_key", opponent["key"]),
            opponent["side"], scenario["teams"][0])
        return {"team": team, "source": {
            **opponent,
            "match_roster_count": team.get("roster_size", len(team["players"])),
            "roster_pending": False,
        }}

    def _export_archive(self, function, data):
        result = function(data)
        payload = base64.b64decode(result["file_base64"])
        directory = Path(self.app.RUNS.parent) / "agent" / "exports" / secrets.token_hex(8)
        directory.mkdir(parents=True, exist_ok=True)
        filename = result.get("filename") or "export.fmf"
        path = directory / filename
        path.write_bytes(payload)
        return {
            "filename": filename,
            "path": str(path),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "report": result.get("report"),
        }
