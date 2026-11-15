"""阵型模板应用服务。"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from fm27lab.adapters.catalog_native.catalog import CatalogRepository
from fm27lab.application.drafts import DraftService
from fm27lab.domain.formations import Formation, formation, formations
from fm27lab.domain.roster import POSITION_INDEX, canonical_position, player_ability
from fm27lab.domain.scenario import upgrade_legacy_scenario
from fm27lab.domain.tactics import Catalog

SIDE_LABELS = ("主队", "客队")
DEFAULT_DUTY = "0"
MISSING_PLAYERS_NOTE = "缺少球员名单，按位置顺序填充"
SHORT_SQUAD_NOTE = "球员不足，未覆盖的位置按顺序补位"


class FormationsService:
    def __init__(self, drafts: DraftService, catalog_repository: CatalogRepository):
        self.drafts = drafts
        self.catalog_repository = catalog_repository

    def list(self) -> dict[str, Any]:
        return {
            "formations": [
                {
                    "id": item.id,
                    "name": item.name,
                    "phases": [
                        [
                            {
                                "position": cell.position,
                                "role": cell.role,
                                "x": cell.x,
                                "y": cell.y,
                            }
                            for cell in phase
                        ]
                        for phase in item.phases
                    ],
                }
                for item in formations()
            ],
            "editing": self._editing(),
        }

    def apply(
        self,
        draft_id: str,
        formation_id: str,
        *,
        overwrite: bool = False,
        scenario: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        draft = self.drafts.get(draft_id)
        if draft is None:
            return None
        template = formation(formation_id)
        if template is None:
            raise ValueError("阵型模板不存在")
        source = scenario if scenario is not None else draft.get("scenario")
        if not isinstance(source, Mapping):
            raise ValueError("场景格式无效")
        target = copy.deepcopy(dict(upgrade_legacy_scenario(source)))
        teams = target.get("teams")
        if not isinstance(teams, list) or len(teams) != 2:
            raise ValueError("场景必须包含两支球队")
        catalog = self._catalog()
        duty = self._default_duty(catalog)
        notes: list[str] = []
        for side, team in enumerate(teams):
            if not isinstance(team, dict):
                raise ValueError("球队数据格式无效")
            for note in self._apply_team(team, template, catalog, overwrite, duty):
                notes.append(SIDE_LABELS[side] + "：" + note)
        if self.drafts.validator is not None:
            checked = self.drafts.validator.validate(target)
            if checked is not None:
                target = dict(checked)
        return {"formation_id": template.id, "scenario": target, "notes": notes}

    def _apply_team(
        self,
        team: dict[str, Any],
        template: Formation,
        catalog: Catalog | None,
        overwrite: bool,
        duty: str,
    ) -> list[str]:
        notes: list[str] = []
        team["lineup"] = self._assign_lineup(team.get("players"), template.phases[0], notes)
        existing = team.get("phases")
        previous: list[Sequence[Any]] = []
        if isinstance(existing, list) and len(existing) == len(template.phases):
            previous = [phase if isinstance(phase, list) else [] for phase in existing]
        phases: list[list[dict[str, Any]]] = []
        for phase, cells in enumerate(template.phases):
            old_cells = previous[phase] if phase < len(previous) else []
            context = self._context(cells, catalog)
            built: list[dict[str, Any]] = []
            for index, cell in enumerate(cells):
                old = old_cells[index] if index < len(old_cells) else None
                keep = not overwrite and isinstance(old, Mapping) and old.get("position") == cell.position
                built.append(
                    {
                        "position": cell.position,
                        "role": self._role(cell.position, phase, cell.role, context, catalog),
                        "duty": self._kept_duty(old, keep, duty, catalog),
                        "instructions": self._kept_instructions(old, keep, catalog),
                        "target_player": self._kept_target(old, keep, "target_player", 255),
                        "target_position": self._kept_target(old, keep, "target_position", 0),
                    }
                )
            phases.append(built)
        team["phases"] = phases
        return notes

    def _assign_lineup(
        self,
        players: Any,
        cells: Sequence[Any],
        notes: list[str],
    ) -> list[int]:
        if not isinstance(players, list) or not players:
            notes.append(MISSING_PLAYERS_NOTE)
            return list(range(len(cells)))
        used: dict[int, int] = {}
        taken: set[int] = set()
        for slot, cell in enumerate(cells):
            if cell.position != "GK":
                continue
            candidates = [index for index in range(len(players)) if index not in taken]
            best = max(
                candidates,
                key=lambda index: (
                    self._familiarity(players[index], cell.position),
                    self._ability(players[index]),
                    -index,
                ),
            )
            used[slot] = best
            taken.add(best)
            break
        pairs: list[tuple[float, float, int, int, int]] = []
        for slot, cell in enumerate(cells):
            if slot in used:
                continue
            for index, player in enumerate(players):
                if index in taken:
                    continue
                pairs.append(
                    (
                        self._familiarity(player, cell.position),
                        self._ability(player),
                        -index,
                        slot,
                        index,
                    )
                )
        pairs.sort(key=lambda item: item[:3], reverse=True)
        for _familiarity, _ability, _order, slot, index in pairs:
            if slot in used or index in taken:
                continue
            used[slot] = index
            taken.add(index)
        if len(used) < len(cells):
            notes.append(SHORT_SQUAD_NOTE)
        return [used[slot] if slot in used else slot % len(players) for slot in range(len(cells))]

    def _familiarity(self, player: Any, position: str) -> float:
        if not isinstance(player, Mapping):
            return 0.0
        attributes = player.get("attributes")
        index = POSITION_INDEX.get(canonical_position(position))
        if not isinstance(attributes, list) or index is None or index >= len(attributes):
            return 0.0
        value = attributes[index]
        return float(value) if isinstance(value, (int, float)) else 0.0

    def _ability(self, player: Any) -> float:
        return player_ability(player) if isinstance(player, Mapping) else 0.0

    def _role(
        self,
        position: str,
        phase: int,
        default: str,
        context: str | None,
        catalog: Catalog | None,
    ) -> str:
        candidates = self._eligible(position, phase, context, catalog)
        if not candidates:
            return default
        if default in candidates:
            return default
        return sorted(candidates)[0]

    def _eligible(
        self,
        position: str,
        phase: int,
        context: str | None,
        catalog: Catalog | None,
    ) -> frozenset[str]:
        if catalog is None:
            return frozenset()
        if catalog.eligibility_context:
            if context is None:
                return frozenset()
            return catalog.eligibility_context.get((context, position, phase), frozenset())
        return catalog.eligibility.get((position, phase), frozenset())

    def _context(self, cells: Sequence[Any], catalog: Catalog | None) -> str | None:
        if catalog is None:
            return None
        defenders = 0
        holding = 0
        for cell in cells:
            position = next(
                (item for item in catalog.positions if item.id == cell.position),
                None,
            )
            if position is None:
                return None
            if position.mask & 16:
                defenders += 1
            if position.mask & 128:
                holding += 1
        return f"{3 if defenders >= 3 else 0}:{1 if holding == 1 else 0}"

    def _kept_duty(
        self,
        old: Any,
        keep: bool,
        default: str,
        catalog: Catalog | None,
    ) -> str:
        if keep and isinstance(old, Mapping):
            value = old.get("duty")
            if isinstance(value, str) and (catalog is None or value in catalog.duties):
                return value
        return default

    def _kept_instructions(
        self,
        old: Any,
        keep: bool,
        catalog: Catalog | None,
    ) -> dict[str, Any]:
        if keep and isinstance(old, Mapping):
            value = old.get("instructions")
            if isinstance(value, Mapping):
                return copy.deepcopy(dict(value))
        if catalog is None or not catalog.player_instructions:
            return {}
        return {
            group_id: 0 if 0 in catalog.player_instructions[group_id] else catalog.player_instructions[group_id][0]
            for group_id in sorted(catalog.player_instructions, key=int)
        }

    def _kept_target(self, old: Any, keep: bool, key: str, default: int) -> int:
        if keep and isinstance(old, Mapping):
            value = old.get(key)
            if type(value) is int:
                return value
        return default

    def _default_duty(self, catalog: Catalog | None) -> str:
        if catalog is None or not catalog.duties:
            return DEFAULT_DUTY
        if DEFAULT_DUTY in catalog.duties:
            return DEFAULT_DUTY
        return catalog.duties[0]

    def _catalog(self) -> Catalog | None:
        document = self._document()
        if document is None:
            return None
        try:
            return Catalog.from_mapping(document)
        except ValueError:
            return None

    def _editing(self) -> dict[str, Any] | None:
        document = self._document()
        if document is None:
            return None
        return {
            "duties": self._section(document, "duties", []),
            "player_instructions": self._section(document, "player_instructions", []),
            "positions": [
                {"id": entry.get("id"), "mask": entry.get("mask")}
                for entry in document.get("positions", [])
                if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)
            ],
            "role_eligibility": self._section(document, "role_eligibility", {}),
            "role_eligibility_context": document.get("role_eligibility_context"),
        }

    def _section(self, document: Mapping[str, Any], key: str, default: Any) -> Any:
        value = document.get(key, default)
        return copy.deepcopy(value) if isinstance(value, (list, dict)) else default

    def _document(self) -> Mapping[str, Any] | None:
        try:
            document = self.catalog_repository.load_document()
        except ValueError:
            return None
        return document if isinstance(document, Mapping) else None
