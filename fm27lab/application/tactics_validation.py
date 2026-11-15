"""Validate draft scenarios against the runtime tactics catalog."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fm27lab.adapters.catalog_native.catalog import CatalogRepository
from fm27lab.domain.tactics import Catalog, validate_phases


class TacticalValidator:
    def __init__(self, repository: CatalogRepository):
        self.repository = repository

    def validate(self, scenario: Mapping[str, Any]) -> Mapping[str, Any] | None:
        try:
            document = self.repository.load_document()
        except ValueError:
            return None
        if document is None:
            return None
        try:
            catalog = Catalog.from_mapping(document)
        except ValueError:
            return None
        teams = scenario.get("teams") if isinstance(scenario, Mapping) else None
        if not isinstance(teams, (list, tuple)):
            return None
        normalized_teams: list[Any] = []
        changed = False
        for team in teams:
            if not isinstance(team, Mapping) or "phases" not in team:
                normalized_teams.append(team)
                continue
            phases = validate_phases(team["phases"], catalog)
            normalized_phases = [list(phase) for phase in phases]
            normalized = dict(team)
            normalized["phases"] = normalized_phases
            if normalized_phases != team["phases"]:
                changed = True
            normalized_teams.append(normalized)
        if not changed:
            return None
        result = dict(scenario)
        result["teams"] = normalized_teams
        return result
