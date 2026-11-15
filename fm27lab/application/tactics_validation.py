"""Validate draft scenarios against the runtime tactics catalog."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fm27lab.adapters.catalog_native.catalog import CatalogRepository
from fm27lab.domain.tactics import Catalog, validate_phases


class TacticalValidator:
    def __init__(self, repository: CatalogRepository):
        self.repository = repository

    def validate(self, scenario: Mapping[str, Any]) -> None:
        try:
            document = self.repository.load_document()
        except ValueError:
            return
        if document is None:
            return
        try:
            catalog = Catalog.from_mapping(document)
        except ValueError:
            return
        teams = scenario.get("teams") if isinstance(scenario, Mapping) else None
        if not isinstance(teams, (list, tuple)):
            return
        for team in teams:
            if not isinstance(team, Mapping) or "phases" not in team:
                continue
            validate_phases(team["phases"], catalog)
