"""Pool application service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fm27lab.adapters.storage_sqlite.repositories import PoolRepository


class PoolService:
    def __init__(self, repository: PoolRepository):
        self.repository = repository

    def create(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return self.repository.add(value)

    def get(self, entry_id: str) -> dict[str, Any] | None:
        return self.repository.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        return self.repository.delete(entry_id)

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
