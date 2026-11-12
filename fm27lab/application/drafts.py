"""Draft application service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fm27lab.adapters.storage_sqlite.repositories import DraftRepository
from fm27lab.domain.scenario import normalize_scenario


class DraftService:
    def __init__(self, repository: DraftRepository):
        self.repository = repository

    def create(
        self,
        name: str,
        scenario: Mapping[str, Any],
        source: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if source is not None and not isinstance(source, Mapping):
            raise ValueError("草案来源必须是对象")
        return self.repository.add(
            {
                "name": name,
                "scenario": normalize_scenario(scenario),
                "source": dict(source or {}),
            }
        )

    def get(self, draft_id: str) -> dict[str, Any] | None:
        return self.repository.get(draft_id)

    def list(self, limit: int = 128, offset: int = 0) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("limit 必须为 1–128 的整数")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset 必须为非负整数")
        rows = self.repository.list()
        page = rows[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "items": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "source": item["source"],
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                }
                for item in page
            ],
            "total": len(rows),
            "next_offset": next_offset if next_offset < len(rows) else None,
        }

    def update(self, draft_id: str, **changes: Any) -> dict[str, Any] | None:
        if not changes or set(changes) - {"name", "scenario", "source"}:
            raise ValueError("草案更新字段无效")
        if self.repository.get(draft_id) is None:
            return None
        if "scenario" in changes:
            changes["scenario"] = normalize_scenario(changes["scenario"])
        if "source" in changes and not isinstance(changes["source"], Mapping):
            raise ValueError("草案来源必须是对象")
        return self.repository.update(draft_id, changes)

    def delete(self, draft_id: str) -> bool:
        return self.repository.delete(draft_id)
