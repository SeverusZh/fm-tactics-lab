"""Save application service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fm27lab.adapters.storage_sqlite.saves import SavesRepository


class SavesService:
    TRANSITIONS: dict[str, set[str]] = {
        "pending": {"reading", "error", "cancelled"},
        "reading": {"ready", "error", "cancelled"},
        "ready": set(),
        "error": set(),
        "cancelled": set(),
    }

    def __init__(self, repository: SavesRepository):
        self.repository = repository

    def create(
        self,
        source_path: str,
        source_sha256: str,
        *,
        status: str = "pending",
        stage: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.repository.add(
            {
                "source_path": source_path,
                "source_sha256": source_sha256,
                "status": status,
                "stage": stage,
                "metadata": {} if metadata is None else metadata,
            }
        )

    def get(self, save_id: str) -> dict[str, Any] | None:
        return self.repository.get(save_id)

    def list(self, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("limit 必须为 1–256 的整数")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset 必须为非负整数")
        items = self.repository.list(status=status, limit=limit, offset=offset)
        total = self.repository.count(status=status)
        next_offset = offset + len(items)
        return {
            "items": items,
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
        }

    def update(self, save_id: str, changes: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(changes, Mapping) or not changes:
            raise ValueError("存档更新字段无效")
        if set(changes) - {"status", "stage", "metadata"}:
            raise ValueError("存档更新字段无效")
        with self.repository.database.transaction() as connection:
            current = self.repository.get(save_id, connection=connection)
            if current is None:
                return None
            if "status" in changes:
                status = changes["status"]
                if not isinstance(status, str) or status not in self.TRANSITIONS[current["status"]]:
                    raise ValueError("存档状态不允许该操作")
            return self.repository.update(save_id, changes, connection=connection)

    def delete(self, save_id: str) -> bool:
        return self.repository.delete(save_id)

    def set_league(self, save_id: str, league_key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.repository.set_league(save_id, league_key, payload)

    def leagues(self, save_id: str) -> list[dict[str, Any]]:
        return self.repository.leagues(save_id)

    def remove_league(self, save_id: str, league_key: str) -> bool:
        return self.repository.remove_league(save_id, league_key)

    def set_club(self, save_id: str, club_uid: int, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.repository.set_club(save_id, club_uid, payload)

    def clubs(self, save_id: str) -> list[dict[str, Any]]:
        return self.repository.clubs(save_id)

    def import_payload(
        self,
        save_id: str,
        leagues: Mapping[str, Mapping],
        clubs: Mapping[int, Mapping],
        *,
        stage: str | None = None,
    ) -> dict[str, Any]:
        with self.repository.database.transaction() as connection:
            if self.repository.get(save_id, connection=connection) is None:
                raise ValueError("存档不存在")
            self.repository.replace_children(save_id, leagues, clubs, connection=connection)
            updated = self.repository.update(
                save_id,
                {"status": "ready", "stage": stage},
                connection=connection,
            )
            if updated is None:
                raise ValueError("存档不存在")
            return updated
