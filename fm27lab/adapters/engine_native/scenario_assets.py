"""Scenario resource loading for the native engine codec."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fm27lab.domain.setpieces import build_catalog
from fm27lab.domain.setpieces import defaults as setpiece_snapshot_defaults

ROLE_MASK = 0xFFFFFFFBF91FFFFF
OOP_OFFSET = 0x1FB4 - 0x2E0
CATALOG_CANDIDATES = ("fm27_native/catalog.json", "catalog.json")
TAKER_KEYS = ["penalties"] + [
    f"{kind}_{direction}_{'foot' if kind in ('corners', 'wide_free_kicks') else 'side'}"
    for kind in ("corners", "direct_free_kicks", "wide_free_kicks", "deep_free_kicks", "throw_ins")
    for direction in ("left", "right")
]


@dataclass(frozen=True)
class ScenarioAssets:
    catalog: dict[str, Any]
    snapshot: dict[str, Any]
    advanced: dict[str, Any]
    setpiece_enums: dict[str, Any]
    setpiece_snapshot: dict[str, Any]
    roles: dict[str, dict[str, Any]]
    positions: dict[str, dict[str, Any]]
    groups: dict[int, dict[str, Any]]
    pis: dict[int, dict[str, Any]]
    role_mask: int
    oop_map: list[list[int]]
    team_known_mask: int
    taker_keys: list[str]
    setpiece_catalog: dict[str, Any]
    setpiece_defaults: list[dict[str, Any]]
    default_teams: list[dict[str, Any]] = field(default_factory=list)


def _damaged(path: Path) -> ValueError:
    return ValueError(f"场景资源文件损坏: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"缺少场景资源文件: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise _damaged(path) from None
    if not isinstance(document, dict):
        raise _damaged(path)
    return document


def _load_catalog(engine_root: Path, catalog_path: Path | None) -> tuple[dict[str, Any], Path]:
    candidates = [catalog_path] if catalog_path is not None else [
        engine_root / name for name in CATALOG_CANDIDATES
    ]
    for path in candidates:
        if path.is_file():
            return _read_json(path), path
    raise ValueError(f"缺少场景资源文件: {candidates[0]}")


def _validate_catalog(catalog: dict[str, Any], path: Path) -> None:
    for key in ("positions", "roles", "team_instructions", "player_instructions"):
        if not isinstance(catalog.get(key), list) or not catalog[key]:
            raise _damaged(path)


def _validate_snapshot(snapshot: dict[str, Any], path: Path) -> None:
    teams = snapshot.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        raise _damaged(path)
    try:
        for team in teams:
            if len(bytes.fromhex(team["creator_hex"])) < 0x26:
                raise _damaged(path)
            if len(team["players"]) != team["count"]:
                raise _damaged(path)
            slots = team["tactical_slots"]
            if len(slots) != 2 or any(len(phase) != 11 for phase in slots):
                raise _damaged(path)
            for phase in slots:
                for cell in phase:
                    if len(bytes.fromhex(cell)) < 72:
                        raise _damaged(path)
            instructions = team["personal_instructions"]
            if len(instructions) != 2 or any(len(row) != 11 for row in instructions):
                raise _damaged(path)
            for row in instructions:
                for entry in row:
                    int(entry["flags"])
                    int(entry["target_player"])
                    int(entry["target_position"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise _damaged(path) from None


def _validate_advanced(advanced: dict[str, Any], path: Path) -> None:
    teams = advanced.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        raise _damaged(path)
    try:
        for team in teams:
            if not isinstance(team["opposition"], list):
                raise _damaged(path)
            for value in team["opposition"]:
                if type(value) is not int:
                    raise _damaged(path)
            if not isinstance(team["opposition_positions"], list):
                raise _damaged(path)
            for entry in team["opposition_positions"]:
                int(entry["position"])
                int(entry["packed"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise _damaged(path) from None


def _validate_setpiece_snapshot(snapshot: dict[str, Any], path: Path) -> None:
    teams = snapshot.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        raise _damaged(path)
    try:
        for team in teams:
            manager = bytes.fromhex(team["manager_tactical_hex"])
            if len(manager) < OOP_OFFSET + 11:
                raise _damaged(path)
            variants = team["routine_variants"]
            if not isinstance(variants, list) or len(variants) != 10:
                raise _damaged(path)
    except (KeyError, IndexError, TypeError, ValueError):
        raise _damaged(path) from None


def _validate_enums(enums: dict[str, Any], path: Path) -> None:
    allowed = enums.get("allowed")
    if not isinstance(allowed, dict) or not allowed:
        raise _damaged(path)
    if not all(isinstance(rows, list) for rows in allowed.values()):
        raise _damaged(path)


def _oop_map(setpiece_snapshot: dict[str, Any]) -> list[list[int]]:
    maps: list[list[int]] = []
    for team in setpiece_snapshot["teams"]:
        manager = bytes.fromhex(team["manager_tactical_hex"])
        mapping = [index if value == 255 else value for index, value in enumerate(manager[OOP_OFFSET : OOP_OFFSET + 11])]
        if sorted(mapping) != list(range(11)):
            raise ValueError("场景资源 OOP 映射无效")
        maps.append(mapping)
    return maps


def load_scenario_assets(engine_root: Path, catalog_path: Path | None = None) -> ScenarioAssets:
    engine_root = Path(engine_root)
    catalog, resolved_catalog_path = _load_catalog(engine_root, catalog_path)
    _validate_catalog(catalog, resolved_catalog_path)
    snapshot_path = engine_root / "fm27_native" / "editor_manual_default.json"
    advanced_path = engine_root / "fm27_native" / "editor_advanced_snapshot.json"
    setpiece_snapshot_path = engine_root / "fm27_native" / "editor_setpieces_default.json"
    enums_path = engine_root / "fm27_research" / "setpiece_enum_catalog.json"
    snapshot = _read_json(snapshot_path)
    _validate_snapshot(snapshot, snapshot_path)
    advanced = _read_json(advanced_path)
    _validate_advanced(advanced, advanced_path)
    setpiece_snapshot = _read_json(setpiece_snapshot_path)
    _validate_setpiece_snapshot(setpiece_snapshot, setpiece_snapshot_path)
    enums = _read_json(enums_path)
    _validate_enums(enums, enums_path)
    try:
        roles = {role["id"]: role for role in catalog["roles"]}
        positions = {position["id"]: position for position in catalog["positions"]}
        groups = {group["id"]: group for group in catalog["team_instructions"]}
        pis = {group["id"]: group for group in catalog["player_instructions"]}
    except (KeyError, TypeError):
        raise _damaged(resolved_catalog_path) from None
    team_known_mask = sum(
        1 << bit
        for bit in {
            option["native_bit"]
            for group in groups.values()
            for option in group.get("options", [])
            if option.get("native_bit")
        }
    )
    oop_map = _oop_map(setpiece_snapshot)
    try:
        setpiece_defaults = [
            setpiece_snapshot_defaults(team) for team in setpiece_snapshot["teams"]
        ]
    except (KeyError, IndexError, TypeError, ValueError):
        raise _damaged(setpiece_snapshot_path) from None
    assets = ScenarioAssets(
        catalog=catalog,
        snapshot=snapshot,
        advanced=advanced,
        setpiece_enums=enums,
        setpiece_snapshot=setpiece_snapshot,
        roles=roles,
        positions=positions,
        groups=groups,
        pis=pis,
        role_mask=ROLE_MASK,
        oop_map=oop_map,
        team_known_mask=team_known_mask,
        taker_keys=list(TAKER_KEYS),
        setpiece_catalog=build_catalog(enums),
        setpiece_defaults=setpiece_defaults,
    )
    from fm27lab.adapters.engine_native import scenario_codec

    try:
        teams = scenario_codec.defaults(assets)["teams"]
    except (KeyError, IndexError, TypeError):
        raise _damaged(snapshot_path) from None
    return dataclasses.replace(assets, default_teams=teams)
