"""File-backed scenario drafts shared by the CLI and the MCP sidecar."""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from .client import AgentError, default_data_dir

DRAFT_PREFIX = "dr_"
DRAFT_PATTERN = re.compile(r"dr_[0-9a-f]{12}")
MAX_DRAFT_BYTES = 5 * 1024 * 1024
EDIT_OPS = ("team_instruction", "mentality", "role", "player_instruction",
            "lineup", "formation", "tactic_name")


def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _pool_summary(pool):
    if not isinstance(pool, dict):
        return None
    entries = pool.get("entries") if isinstance(pool.get("entries"), list) else []
    uniform = pool.get("uniform") if isinstance(pool.get("uniform"), dict) else None
    rotation = pool.get("rotation") if isinstance(pool.get("rotation"), dict) else {}
    real = pool.get("real") if isinstance(pool.get("real"), dict) else {}
    return {
        "enabled": bool(pool.get("enabled")),
        "entries": len(entries),
        "mode": "rotation" if rotation.get("enabled") else "random",
        "rounds": int(rotation.get("rounds") or 1),
        "players": "real" if real.get("enabled") else "uniform",
        "roster_entries": sum(1 for item in entries
                              if isinstance(item, dict) and isinstance(item.get("roster"), dict)),
        "uniform": copy.deepcopy(uniform),
    }


class DraftService:
    """Draft JSON files live under <dataDir>/agent/drafts."""

    def __init__(self, client, data_dir=None):
        self.client = client
        self.data_dir = Path(data_dir or getattr(client, "data_dir", None) or default_data_dir())
        self.root = self.data_dir / "agent" / "drafts"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, draft_id):
        if not isinstance(draft_id, str) or not DRAFT_PATTERN.fullmatch(draft_id):
            raise AgentError("not_found", f"草案标识无效：{draft_id}")
        return self.root / f"{draft_id}.json"

    def _load(self, draft_id):
        path = self._path(draft_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            raise AgentError("not_found", f"草案不存在：{draft_id}", {"draft_id": draft_id}) from None
        except ValueError:
            raise AgentError("internal_error", f"草案文件无法解析：{draft_id}") from None
        if not isinstance(value, dict) or not isinstance(value.get("scenario"), dict):
            raise AgentError("internal_error", f"草案文件结构无效：{draft_id}")
        return value

    def _save(self, draft):
        path = self._path(draft["id"])
        draft["updated_at"] = now_text()
        text = json.dumps(draft, ensure_ascii=False, indent=2)
        if len(text.encode("utf-8")) > MAX_DRAFT_BYTES:
            raise AgentError("validation_failed", "草案超过 5 MB 上限")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)

    def _new_id(self):
        return DRAFT_PREFIX + secrets.token_hex(6)

    def _scenario(self, value):
        if not isinstance(value, dict):
            raise AgentError("validation_failed", "场景必须是 JSON 对象")
        return value

    def _normalize(self, scenario):
        result = self.client.phase_plan(scenario)
        value = result.get("scenario")
        if not isinstance(value, dict):
            raise AgentError("internal_error", "服务端未返回归一化场景")
        return value

    def _from_save(self, params):
        save_id = params.get("save_id")
        club_uid = params.get("club_uid")
        tactic_index = params.get("tactic_index")
        if not save_id or club_uid is None or tactic_index is None:
            raise AgentError("validation_failed", "save 来源需要 save_id、club_uid 与 tactic_index")
        base = self.client.defaults().get("scenario")
        if not isinstance(base, dict):
            raise AgentError("internal_error", "服务端默认场景缺失")
        loaded = self.client.career_load(
            save_id, int(club_uid), int(tactic_index), base,
            lineup=params.get("lineup"), bench=params.get("bench"),
        )
        scenario = self._normalize(loaded.get("scenario"))
        source = {"kind": "save", "save_id": save_id, "club_uid": int(club_uid),
                  "tactic_index": int(tactic_index), "detail": loaded.get("source")}
        return scenario, source

    def _from_fmf(self, params):
        side = params.get("side")
        if side not in (0, 1):
            raise AgentError("validation_failed", "fmf 来源需要 side 为 0 或 1")
        file_base64 = params.get("file_base64")
        file_path = params.get("file_path")
        if file_base64 is None and file_path:
            try:
                import base64
                file_base64 = base64.b64encode(Path(file_path).expanduser().read_bytes()).decode("ascii")
            except OSError as error:
                raise AgentError("validation_failed", f"无法读取 FMF 文件：{error}") from None
        if not file_base64:
            raise AgentError("validation_failed", "fmf 来源需要 file_base64 或 file_path")
        base = params.get("base_scenario")
        base_draft = params.get("base_draft_id")
        if base is None and base_draft:
            base = self._load(base_draft)["scenario"]
        if base is None:
            base = self.client.defaults().get("scenario")
        if not isinstance(base, dict):
            raise AgentError("validation_failed", "fmf 来源需要可用的基础场景")
        loaded = self.client.fmf_import(int(side), base, file_base64,
                                        params.get("setpiece_target"))
        scenario = self._normalize(loaded.get("scenario"))
        return scenario, {"kind": "fmf", "side": int(side),
                          "base_draft_id": base_draft, "report": loaded.get("report")}

    def _from_draft(self, params):
        base_draft_id = params.get("base_draft_id")
        if not base_draft_id:
            raise AgentError("validation_failed", "draft 来源需要 base_draft_id")
        base = self._load(base_draft_id)
        return copy.deepcopy(base["scenario"]), {
            "kind": "draft",
            "base_draft_id": base_draft_id,
            "base_name": base.get("name"),
        }

    def _from_job(self, params):
        job_id = params.get("job_id")
        variant = params.get("variant") or "B"
        if not job_id:
            raise AgentError("validation_failed", "job 来源需要 job_id")
        exported = self.client.job_export(job_id)
        scenarios = exported.get("scenarios") or {}
        scenario = scenarios.get(variant)
        if not isinstance(scenario, dict):
            raise AgentError("not_found", f"任务 {job_id} 没有方案 {variant}")
        return scenario, {"kind": "job", "job_id": job_id, "variant": variant}

    def create(self, source="default", name=None, **params):
        if source == "default":
            scenario = self.client.defaults().get("scenario")
            if not isinstance(scenario, dict):
                raise AgentError("internal_error", "服务端默认场景缺失")
            origin = {"kind": "default"}
        elif source == "save":
            scenario, origin = self._from_save(params)
        elif source == "fmf":
            scenario, origin = self._from_fmf(params)
        elif source == "job":
            scenario, origin = self._from_job(params)
        elif source == "draft":
            scenario, origin = self._from_draft(params)
        elif source == "inline":
            scenario = params.get("scenario")
            if scenario is None:
                path = params.get("scenario_path")
                if not path:
                    raise AgentError("validation_failed",
                                     "inline 来源需要 scenario 或 scenario_path")
                try:
                    scenario = json.loads(Path(path).expanduser().read_text(encoding="utf-8-sig"))
                except (OSError, ValueError) as error:
                    raise AgentError("validation_failed", f"无法读取场景文件：{error}") from None
            scenario = self._scenario(scenario)
            origin = {"kind": "inline", "scenario_path": params.get("scenario_path")}
        else:
            raise AgentError("validation_failed",
                             "source 必须是 default、save、fmf、job、inline 或 draft")
        scenario = self._normalize(scenario)
        draft = {
            "schema": 1,
            "id": self._new_id(),
            "name": (str(name).strip()[:100] if name else
                     (scenario.get("teams") or [{}])[0].get("name") or "未命名草案"),
            "created_at": now_text(),
            "updated_at": now_text(),
            "source": origin,
            "meta": {"api": "fm27lab/v1", "scenario_view_schema": 4},
            "scenario": scenario,
        }
        self._save(draft)
        return self.get(draft["id"])

    def summary(self, draft):
        scenario = draft.get("scenario") or {}
        pool = scenario.get("away_tactic_pool")
        teams = []
        for team in scenario.get("teams") or []:
            teams.append({
                "name": team.get("name"),
                "tactic_name": team.get("tactic_name"),
                "mentality": team.get("mentality"),
                "lineup": len(team.get("lineup") or []),
                "players": len(team.get("players") or []),
                "roster_size": team.get("roster_size"),
            })
        return {
            "draft_id": draft.get("id"),
            "name": draft.get("name"),
            "created_at": draft.get("created_at"),
            "updated_at": draft.get("updated_at"),
            "source": draft.get("source"),
            "scenario_schema": (scenario.get("schema") if isinstance(scenario, dict) else None),
            "away_tactic_pool": _pool_summary(pool),
            "teams": teams,
        }

    def get(self, draft_id, include_scenario=False):
        draft = self._load(draft_id)
        value = self.summary(draft)
        if include_scenario:
            value["scenario"] = draft["scenario"]
        return value

    def scenario(self, draft_id):
        return self._load(draft_id)["scenario"]

    def replace_scenario(self, draft_id, scenario):
        draft = self._load(draft_id)
        draft["scenario"] = self._normalize(self._scenario(scenario))
        self._save(draft)
        return self.get(draft_id)

    def list(self):
        values = []
        for path in self.root.glob("dr_*.json"):
            try:
                draft = json.loads(path.read_text(encoding="utf-8"))
                if DRAFT_PATTERN.fullmatch(draft.get("id", "")) and isinstance(draft.get("scenario"), dict):
                    values.append(self.summary(draft))
            except (OSError, ValueError):
                continue
        values.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return values

    def delete(self, draft_id):
        path = self._path(draft_id)
        try:
            path.unlink()
        except OSError:
            raise AgentError("not_found", f"草案不存在：{draft_id}") from None
        return {"draft_id": draft_id, "deleted": True}

    def delete_many(self, draft_ids):
        if not isinstance(draft_ids, list) or not draft_ids:
            raise AgentError("validation_failed", "draft_ids 必须是非空数组")
        deleted = []
        errors = []
        for draft_id in draft_ids:
            try:
                self.delete(draft_id)
                deleted.append(draft_id)
            except AgentError as error:
                errors.append({"draft_id": draft_id, "code": error.code,
                               "message": error.message})
        return {"deleted": deleted, "errors": errors,
                "deleted_count": len(deleted), "error_count": len(errors)}

    def _plan(self, scenario, side, phase):
        teams = scenario.get("teams") or []
        if side not in (0, 1) or side >= len(teams):
            raise AgentError("validation_failed", "side 必须是 0 或 1")
        team = teams[side]
        plans = team.get("phase_plans")
        if not isinstance(plans, list) or len(plans) != 2:
            raise AgentError("validation_failed", "场景缺少双阶段方案")
        for plan in plans:
            if plan.get("phase") == phase:
                return team, plan
        raise AgentError("validation_failed", f"未知阶段：{phase}")

    def _assignment(self, plan, slot):
        assignments = plan.get("assignments") or []
        if type(slot) is not int or not 0 <= slot < len(assignments):
            raise AgentError("validation_failed", "slot 必须是 0 到 10")
        return assignments[slot]

    def _apply(self, scenario, op, params):
        if op not in EDIT_OPS:
            raise AgentError("validation_failed", f"未知编辑操作：{op}")
        side = params.get("side")
        if side not in (0, 1):
            raise AgentError("validation_failed", "side 必须是 0 或 1")
        teams = scenario.get("teams") or []
        if side >= len(teams):
            raise AgentError("validation_failed", "side 超出球队数量")
        team = teams[side]
        if op == "team_instruction":
            _, plan = self._plan(scenario, side, params.get("phase"))
            group = params.get("group")
            option = params.get("option")
            if group is None or type(option) is not int:
                raise AgentError("validation_failed", "team_instruction 需要 group 与 option")
            plan.setdefault("team_instructions", {})[str(group)] = option
            return None
        if op == "mentality":
            value = params.get("value")
            if type(value) is not int or not 1 <= value <= 7:
                raise AgentError("validation_failed", "mentality 必须是 1 到 7")
            team["mentality"] = value
            return None
        if op == "role":
            _, plan = self._plan(scenario, side, params.get("phase"))
            cell = self._assignment(plan, params.get("slot"))
            role = params.get("role")
            if not isinstance(role, str) or not role:
                raise AgentError("validation_failed", "role 必须是非空字符串")
            cell["role"] = role
            if params.get("duty") is not None:
                cell["duty"] = str(params["duty"])
            return None
        if op == "player_instruction":
            _, plan = self._plan(scenario, side, params.get("phase"))
            cell = self._assignment(plan, params.get("slot"))
            group = params.get("group")
            option = params.get("option")
            if group is None or type(option) is not int:
                raise AgentError("validation_failed", "player_instruction 需要 group 与 option")
            cell.setdefault("instructions", {})[str(group)] = option
            return None
        if op == "lineup":
            starters = params.get("starters")
            bench = params.get("bench") or []
            players = team.get("players") or []
            if (not isinstance(starters, list) or len(starters) != 11
                    or any(type(index) is not int for index in starters)
                    or len(set(starters)) != 11
                    or any(not 0 <= index < len(players) for index in starters)):
                raise AgentError("validation_failed", "starters 必须是 11 个不重复的球员序号")
            if (not isinstance(bench, list) or len(bench) > 12
                    or any(type(index) is not int or not 0 <= index < len(players) for index in bench)
                    or len(set(bench)) != len(bench)
                    or set(bench) & set(starters)):
                raise AgentError("validation_failed", "bench 必须是 0 到 12 个不重复且不在首发的球员序号")
            has_squad = bool(team.get("squad")) and all(
                players[index].get("source_uid") is not None for index in starters + bench)
            if has_squad:
                starters_uid = [players[index]["source_uid"] for index in starters]
                bench_uid = [players[index]["source_uid"] for index in bench]
                selected = self.client.career_selection(scenario, starters_uid, bench_uid)
                return selected.get("scenario")
            team["lineup"] = list(starters)
            team["roster_size"] = max(11, max(starters + bench) + 1)
            return None
        if op == "formation":
            _, plan = self._plan(scenario, side, params.get("phase"))
            positions = params.get("positions")
            if (not isinstance(positions, list) or len(positions) != 11
                    or any(not isinstance(value, str) or not value for value in positions)
                    or len(set(positions)) != 11):
                raise AgentError("validation_failed", "positions 必须是 11 个不重复的位置")
            for index, position in enumerate(positions):
                plan["assignments"][index]["position"] = position
            return None
        if op == "tactic_name":
            value = params.get("value")
            if not isinstance(value, str) or not value.strip():
                raise AgentError("validation_failed", "tactic_name 必须是非空字符串")
            team["tactic_name"] = value.strip()[:120]
            return None
        raise AgentError("validation_failed", f"未知编辑操作：{op}")

    def _role_hint(self, scenario, side, phase, slot):
        try:
            catalog = (self.client.catalog() or {}).get("catalog") or {}
            positions = {item["id"]: item for item in catalog.get("positions") or []}
            roles = {item["id"]: item for item in catalog.get("roles") or []}
            context = catalog.get("role_eligibility_context") or {}
            _, plan = self._plan(scenario, side, phase)
            cells = plan.get("assignments") or []
            defenders = sum(bool(positions[cell["position"]]["mask"] & 16) for cell in cells)
            defensive_midfielders = sum(
                bool(positions[cell["position"]]["mask"] & 0x80) for cell in cells)
            key = f"{3 if defenders >= 3 else 0}:{int(defensive_midfielders == 1)}"
            position = cells[slot]["position"]
            phase_index = 0 if phase == "in_possession" else 1
            options = context[key][position][phase_index]
            labels = [f"{roles.get(item, {}).get('label') or item}({item})" for item in options]
            return f"位置 {position} 可用角色：{'、'.join(labels)}"
        except (AgentError, KeyError, IndexError, TypeError, ValueError):
            return None

    def _validate_with_hint(self, scenario, operations):
        try:
            return self.client.validate(scenario)
        except AgentError as error:
            if error.code != "validation_failed":
                raise
            hints = []
            for operation, params in operations:
                if operation != "role":
                    continue
                hint = self._role_hint(scenario, params.get("side"), params.get("phase"),
                                       params.get("slot"))
                if hint and hint not in hints:
                    hints.append(hint)
            if hints:
                raise AgentError("validation_failed",
                                 f"{error.message}；{'；'.join(hints)}",
                                 error.details) from None
            raise

    def edit_many(self, draft_id, operations):
        if not isinstance(operations, list) or not operations:
            raise AgentError("validation_failed", "ops 必须是非空数组")
        normalized_ops = []
        for index, item in enumerate(operations):
            if not isinstance(item, dict) or not isinstance(item.get("op"), str):
                raise AgentError("validation_failed", f"ops[{index}] 缺少 op")
            params = {key: value for key, value in item.items() if key != "op"}
            normalized_ops.append((item["op"], params))
        draft = self._load(draft_id)
        scenario = copy.deepcopy(draft["scenario"])
        for operation, params in normalized_ops:
            replacement = self._apply(scenario, operation, params)
            if replacement is not None:
                scenario = replacement
        normalized = self._normalize(scenario)
        validated = self._validate_with_hint(normalized, normalized_ops)
        draft["scenario"] = normalized
        self._save(draft)
        return {
            "draft_id": draft_id,
            "changed": True,
            "ops": [operation for operation, _ in normalized_ops],
            "summary": self.summary(draft),
            "validation": {"valid": True, "records": validated.get("records")},
        }

    def edit(self, draft_id, op, **params):
        return self.edit_many(draft_id, [{**params, "op": op}])

    def validate(self, draft_id):
        draft = self._load(draft_id)
        try:
            checked = self.client.validate(draft["scenario"])
            normalized = self.client.phase_plan(checked.get("scenario") or draft["scenario"]).get("scenario")
        except AgentError as error:
            if error.code != "validation_failed":
                raise
            return {
                "draft_id": draft_id,
                "valid": False,
                "errors": [error.to_dict()],
                "summary": self.summary(draft),
            }
        if isinstance(normalized, dict):
            draft["scenario"] = normalized
            self._save(draft)
        return {
            "draft_id": draft_id,
            "valid": True,
            "errors": [],
            "records": checked.get("records"),
            "summary": self.summary(draft),
        }
