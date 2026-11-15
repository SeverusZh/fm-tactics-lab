"""Pool application service."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fm27lab.adapters.fmf import FmfCodec
from fm27lab.adapters.storage_sqlite.repositories import PoolRepository
from fm27lab.domain.pool import MAX_NAME, normalize_away_pool

FALLBACK_NAME = "导入战术"
UPDATE_FIELDS = frozenset({"name", "weight"})


def _source_name(filename: str) -> str:
    stem = Path(str(filename or "")).name
    if stem.lower().endswith(".fmf"):
        stem = stem[:-4]
    stem = stem.strip()[:MAX_NAME].strip()
    return stem or FALLBACK_NAME


def _unique_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    index = 2
    while True:
        suffix = f" {index}"
        candidate = name[: MAX_NAME - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        index += 1


def _scenario_entry(scenario: Mapping[str, Any], filename: str) -> dict[str, Any]:
    teams = scenario.get("teams")
    if not isinstance(teams, (list, tuple)) or not teams or not isinstance(teams[0], Mapping):
        raise ValueError("FMF 文件不包含球队战术")
    team = teams[0]
    phases = team.get("phases")
    if not isinstance(phases, (list, tuple)):
        raise ValueError("FMF 文件不包含可用战术")
    tactic_name = team.get("tactic_name")
    if tactic_name is not None and not isinstance(tactic_name, str):
        raise ValueError("FMF 文件战术名称无效")
    return {
        "name": _source_name(filename),
        "weight": 1,
        "tactic": {
            "tactic_name": tactic_name or "",
            "mentality": team.get("mentality"),
            "instructions": team.get("instructions") or {},
            "native_extra_team_bits": team.get("native_extra_team_bits") or "0",
            "phases": phases,
        },
    }


class PoolService:
    def __init__(self, repository: PoolRepository):
        self.repository = repository

    def create(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return self.repository.add(value)

    def get(self, entry_id: str) -> dict[str, Any] | None:
        return self.repository.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        return self.repository.delete(entry_id)

    def update(self, entry_id: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(payload, Mapping):
            raise ValueError("客队战术更新内容必须是对象")
        if set(payload) - UPDATE_FIELDS:
            raise ValueError("仅支持更新客队战术名称与权重")
        changes = {key: value for key, value in payload.items() if value is not None}
        if not changes:
            raise ValueError("至少需要提供一项更新字段")
        return self.repository.update(entry_id, changes)

    def add_from_scenario(self, scenario: Mapping[str, Any], name: str) -> dict[str, Any]:
        raw = _scenario_entry(scenario, name)
        taken = {entry["name"] for entry in self.repository.list()}
        raw["name"] = _unique_name(raw["name"], taken)
        entry = normalize_away_pool({"entries": [raw]})["entries"][0]
        return self.repository.add(entry)

    def import_fmf(self, data: bytes, filename: str) -> list[dict[str, Any]]:
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("FMF 文件内容无效")
        scenario = FmfCodec().decode(bytes(data))
        if not isinstance(scenario, Mapping):
            raise ValueError("FMF 文件无效")
        return [self.add_from_scenario(scenario, filename)]

    def list(self, limit: int = 128, offset: int = 0) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("limit 必须为 1–128 的整数")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset 必须为非负整数")
        rows = self.repository.list()
        page = rows[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "items": page,
            "total": len(rows),
            "next_offset": next_offset if next_offset < len(rows) else None,
        }
