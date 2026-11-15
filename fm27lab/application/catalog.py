"""运行时目录快照应用服务。"""

from __future__ import annotations

from typing import Any

from fm27lab.adapters.catalog_native.catalog import CatalogRepository


class CatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def snapshot(self) -> dict[str, Any]:
        catalog = self.repository.load()
        if catalog is None:
            return {"available": False, "catalog": None}
        return {"available": True, "catalog": catalog}
