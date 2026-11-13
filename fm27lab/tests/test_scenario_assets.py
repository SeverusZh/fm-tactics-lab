"""Synthetic engine resource fixtures and scenario asset contract tests."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets, load_scenario_assets
from fm27lab.domain.setpieces import TYPE_NAMES

ROLE_MASK = 0xFFFFFFFBF91FFFFF
POSITION_ROWS = [
    ("GK", 1),
    ("DR", 4),
    ("DL", 8),
    ("DC", 16),
    ("DMC", 128),
    ("MR", 256),
    ("MC", 1024),
    ("AMR", 2048),
    ("AML", 4096),
    ("AMC", 8192),
    ("ST", 16384),
]
POSITION_ORDER = [position for position, _ in POSITION_ROWS]
OOP_MAPS = [[2, 0, 1, 3, 4, 5, 6, 7, 8, 9, 10], list(range(11))]
ROLE_FLAGS = {0: {"GK": 0x100, "FIELD": 0x200}, 1: {"GK": 0x400, "FIELD": 0x800}}
TEAM_KNOWN_MASK = (1 << 4) | (1 << 3)
CREATOR_MENTALITY = 4
DEFAULT_ATTRIBUTES = [10] * 15 + [50] * 54
CONTROLLED_START = {
    "condition": 10000,
    "sharpness": 10000,
    "sharpness_secondary": 10000,
    "fatigue_raw": 0,
    "team_cohesion": 80,
    "club_cohesion": 100,
    "morale": 20,
}
TAKER_KEYS = [
    "penalties",
    "corners_left_foot",
    "corners_right_foot",
    "direct_free_kicks_left_side",
    "direct_free_kicks_right_side",
    "wide_free_kicks_left_foot",
    "wide_free_kicks_right_foot",
    "deep_free_kicks_left_side",
    "deep_free_kicks_right_side",
    "throw_ins_left_side",
    "throw_ins_right_side",
]
ROUTINE_VALUES = [[1, 2, 3, 4, 5, 6], [7], [8, 9, 10], [], [], [], [], []]
OPPOSITION_PLAYER = {"press": 1, "mark": 2, "tackle": 3, "foot": 1, "personal": True}
OPPOSITION_POSITION = {"press": 2, "mark": 0, "tackle": 1, "foot": 0, "personal": False}


def pack_oi(row: dict) -> int:
    return (
        row["press"]
        | (row["mark"] << 3)
        | (row["tackle"] << 8)
        | (row["foot"] << 11)
        | (0x80000 if row["personal"] else 0)
    )


def unpack_oi(value: int) -> dict:
    return {
        "press": value & 7,
        "mark": (value >> 3) & 7,
        "tackle": (value >> 8) & 7,
        "foot": (value >> 11) & 7,
        "personal": bool(value & 0x80000),
    }


def make_cell(mask: int, flag: int) -> str:
    cell = bytearray(72)
    struct.pack_into("<I", cell, 0, mask)
    struct.pack_into("<Q", cell, 64, flag)
    return bytes(cell).hex()


def make_manager_hex(oop: list[int], throw_styles: list[int]) -> str:
    manager = bytearray(11312)
    manager[0x1410:0x1413] = bytes(throw_styles)
    manager[0x1CD4:0x1CDF] = bytes(oop)
    return bytes(manager).hex()


def make_catalog(marker: str = "native") -> dict:
    return {
        "schema_version": marker,
        "positions": [
            {"id": position, "mask": mask, "x": 0.5, "y": 0.5} for position, mask in POSITION_ROWS
        ],
        "roles": [
            {
                "id": "GK_ROLE_0",
                "label": "有球门将",
                "phase": 0,
                "flags": str(ROLE_FLAGS[0]["GK"]),
                "defaults": {},
            },
            {
                "id": "FIELD_ROLE_0",
                "label": "有球角色",
                "phase": 0,
                "flags": str(ROLE_FLAGS[0]["FIELD"]),
                "defaults": {},
            },
            {
                "id": "GK_ROLE_1",
                "label": "无球门将",
                "phase": 1,
                "flags": str(ROLE_FLAGS[1]["GK"]),
                "defaults": {},
            },
            {
                "id": "FIELD_ROLE_1",
                "label": "无球角色",
                "phase": 1,
                "flags": str(ROLE_FLAGS[1]["FIELD"]),
                "defaults": {},
            },
        ],
        "team_instructions": [
            {
                "id": 1,
                "label": "传球方式",
                "options": [
                    {"id": 0, "label": "标准", "native_bit": 0},
                    {"id": 1, "label": "短传", "native_bit": 4},
                ],
            },
            {
                "id": 2,
                "label": "防守宽度",
                "options": [
                    {"id": 0, "label": "默认", "native_bit": 0},
                    {"id": 1, "label": "收缩", "native_bit": 3},
                ],
            },
            {"id": 4, "label": "进攻节奏", "options": [{"id": 0, "label": "默认", "native_bit": 0}]},
        ],
        "player_instructions": [
            {
                "id": 0,
                "label": "进攻站位",
                "phase": 0,
                "options": [{"id": 0, "label": "默认"}, {"id": 1, "label": "前插"}],
            },
            {
                "id": 1,
                "label": "逼抢",
                "phase": 1,
                "options": [{"id": 0, "label": "默认"}, {"id": 2, "label": "高压"}],
            },
        ],
    }


def make_snapshot() -> dict:
    teams = []
    for side in range(2):
        tactical_slots = [[], []]
        for index, (_, mask) in enumerate(POSITION_ROWS):
            flag = ROLE_FLAGS[0]["GK"] if index == 0 else ROLE_FLAGS[0]["FIELD"]
            tactical_slots[0].append(make_cell(mask, flag))
        phase_one = [""] * 11
        for index, (_, mask) in enumerate(POSITION_ROWS):
            flag = ROLE_FLAGS[1]["GK"] if index == 0 else ROLE_FLAGS[1]["FIELD"]
            phase_one[OOP_MAPS[side][index]] = make_cell(mask, flag)
        tactical_slots[1] = phase_one
        personal_instructions = [
            [{"flags": 0, "target_player": 255, "target_position": 0} for _ in range(11)]
            for _ in range(2)
        ]
        personal_instructions[0][0].update(flags=2, target_player=5, target_position=1)
        creator = bytearray(40)
        creator[0] = 1 << 4
        creator[0x25] = CREATOR_MENTALITY
        teams.append(
            {
                "count": 23,
                "creator_hex": bytes(creator).hex(),
                "tactical_slots": tactical_slots,
                "personal_instructions": personal_instructions,
                "players": [
                    {
                        "index": index,
                        "id": 100 + index,
                        "attributes": list(DEFAULT_ATTRIBUTES),
                        "prefix_hex": "ff",
                    }
                    for index in range(23)
                ],
            }
        )
    return {"teams": teams}


def make_advanced() -> dict:
    teams = []
    for _ in range(2):
        opposition = [0x80000] * 23
        opposition[0] = pack_oi(OPPOSITION_PLAYER)
        teams.append(
            {
                "opposition": opposition,
                "opposition_positions": [
                    {"position": dict(POSITION_ROWS)["GK"], "packed": pack_oi(OPPOSITION_POSITION)}
                ],
            }
        )
    return {"teams": teams}


def make_routine(kind: int) -> dict:
    return {
        "type": kind,
        "frequency": 0,
        "strategy": 255,
        "swing": 255,
        "priority": [0, 2, 1],
        "groups": [{"id": group, "values": list(tasks)} for group, tasks in enumerate(ROUTINE_VALUES)],
        "backups": [],
    }


def make_setpiece_snapshot() -> dict:
    return {
        "teams": [
            {
                "manager_tactical_hex": make_manager_hex(OOP_MAPS[side], [0, 1, 0] if side == 0 else [1, 0, 0]),
                "routine_variants": [[make_routine(kind)] for kind in range(10)],
            }
            for side in range(2)
        ]
    }


def make_setpiece_enums() -> dict:
    return {
        "allowed": {str(group): list(range(1, 16)) for group in range(8)},
        "attack": [{"id": 1, "label": "进攻任务"}],
        "defend": [{"id": 1, "label": "防守任务"}],
        "categories": [{"id": 1, "label": "角色类别"}],
        "corner_target": [{"id": 1, "label": "角球目标"}],
        "free_kick_risk": [{"id": 1, "label": "任意球风险"}],
        "swing": [{"id": 0, "label": "内旋"}, {"id": 1, "label": "外旋"}],
        "defensive_line": [{"id": 1, "label": "防线"}],
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def write_engine_root(tmp_path: Path) -> Path:
    root = tmp_path / "engine"
    native = root / "fm27_native"
    research = root / "fm27_research"
    native.mkdir(parents=True)
    research.mkdir()
    write_json(native / "catalog.json", make_catalog("native"))
    write_json(native / "editor_manual_default.json", make_snapshot())
    write_json(native / "editor_advanced_snapshot.json", make_advanced())
    write_json(native / "editor_setpieces_default.json", make_setpiece_snapshot())
    write_json(research / "setpiece_enum_catalog.json", make_setpiece_enums())
    return root


def load_fixture_assets(tmp_path: Path) -> ScenarioAssets:
    return load_scenario_assets(write_engine_root(tmp_path))


def test_load_scenario_assets_builds_derived_state(tmp_path):
    assets = load_fixture_assets(tmp_path)
    assert isinstance(assets, ScenarioAssets)
    assert set(assets.positions) == set(POSITION_ORDER)
    assert assets.roles["GK_ROLE_0"]["phase"] == 0
    assert assets.groups[1]["options"][1]["native_bit"] == 4
    assert assets.pis[0]["options"][1]["id"] == 1
    assert assets.role_mask == ROLE_MASK
    assert assets.oop_map == OOP_MAPS
    assert assets.team_known_mask == TEAM_KNOWN_MASK
    assert assets.taker_keys == TAKER_KEYS
    assert [entry["id"] for entry in assets.setpiece_catalog["types"]] == list(range(10))
    assert [entry["label"] for entry in assets.setpiece_catalog["types"]] == TYPE_NAMES
    assert assets.setpiece_defaults[0]["throw_styles"] == [0, 1, 0]
    assert set(assets.setpiece_defaults[0]["routines"]) == {str(kind) for kind in range(10)}
    assert len(assets.default_teams) == 2
    assert assets.catalog["schema_version"] == "native"


def test_default_teams_port_native_snapshot(tmp_path):
    assets = load_fixture_assets(tmp_path)
    home = assets.default_teams[0]
    assert [team["name"] for team in assets.default_teams] == ["主队", "客队"]
    assert home["mentality"] == CREATOR_MENTALITY
    assert home["instructions"] == {"1": 1, "2": 0, "4": 0}
    assert home["native_extra_team_bits"] == "0"
    assert home["lineup"] == list(range(11))
    assert home["captains"] == []
    assert home["takers"] == {key: [] for key in TAKER_KEYS}
    assert [cell["position"] for cell in home["phases"][0]] == POSITION_ORDER
    assert [cell["position"] for cell in home["phases"][1]] == POSITION_ORDER
    assert home["phases"][0][0]["role"] == "GK_ROLE_0"
    assert home["phases"][0][1]["role"] == "FIELD_ROLE_0"
    assert home["phases"][1][0]["role"] == "GK_ROLE_1"
    assert home["phases"][1][1]["role"] == "FIELD_ROLE_1"
    assert home["phases"][0][0]["duty"] == "0"
    assert home["phases"][0][0]["instructions"] == {"0": 1, "1": 0}
    assert home["phases"][0][0]["target_player"] == 5
    assert home["phases"][0][0]["target_position"] == 1
    assert home["phases"][0][1]["instructions"] == {"0": 0, "1": 0}
    assert home["phases"][0][1]["target_player"] == 255
    assert home["opposition"]["players"][0] == OPPOSITION_PLAYER
    assert home["opposition"]["players"][1] == {"press": 0, "mark": 0, "tackle": 0, "foot": 0, "personal": True}
    assert home["opposition"]["positions"]["GK"] == OPPOSITION_POSITION
    assert home["opposition"]["positions"]["ST"] == {"press": 0, "mark": 0, "tackle": 0, "foot": 0, "personal": True}
    assert len(home["players"]) == 23
    assert home["players"][0]["name"] == "主队球员 01"
    assert home["players"][0]["native_id"] == 100
    assert home["players"][0]["attributes"] == DEFAULT_ATTRIBUTES
    assert home["players"][0]["native_profile"] == CONTROLLED_START
    assert assets.default_teams[1]["players"][0]["name"] == "客队球员 01"
    assert home["setpieces"] == assets.setpiece_defaults[0]
    assert home["setpieces"]["routines"]["0"][0]["name"] == "防守角球 1"


def test_catalog_search_prefers_native_then_root(tmp_path):
    root = write_engine_root(tmp_path)
    write_json(root / "catalog.json", make_catalog("root"))
    assets = load_scenario_assets(root)
    assert assets.catalog["schema_version"] == "native"
    (root / "fm27_native" / "catalog.json").unlink()
    assets = load_scenario_assets(root)
    assert assets.catalog["schema_version"] == "root"
    explicit = tmp_path / "explicit_catalog.json"
    write_json(explicit, make_catalog("explicit"))
    assets = load_scenario_assets(root, explicit)
    assert assets.catalog["schema_version"] == "explicit"


def test_missing_resource_file_raises_chinese_error(tmp_path):
    root = write_engine_root(tmp_path)
    (root / "fm27_research" / "setpiece_enum_catalog.json").unlink()
    with pytest.raises(ValueError, match="缺少场景资源文件"):
        load_scenario_assets(root)


def test_missing_catalog_raises_chinese_error(tmp_path):
    root = write_engine_root(tmp_path)
    (root / "fm27_native" / "catalog.json").unlink()
    with pytest.raises(ValueError, match="缺少场景资源文件"):
        load_scenario_assets(root)


def test_corrupt_json_raises_chinese_error(tmp_path):
    root = write_engine_root(tmp_path)
    (root / "fm27_native" / "editor_manual_default.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="场景资源文件损坏"):
        load_scenario_assets(root)


def test_malformed_snapshot_raises_chinese_error(tmp_path):
    root = write_engine_root(tmp_path)
    write_json(root / "fm27_native" / "editor_manual_default.json", {"teams": []})
    with pytest.raises(ValueError, match="场景资源文件损坏"):
        load_scenario_assets(root)


def test_truncated_tactical_cell_raises_chinese_error(tmp_path):
    root = write_engine_root(tmp_path)
    snapshot = make_snapshot()
    snapshot["teams"][0]["tactical_slots"][0][0] = "00" * 4
    write_json(root / "fm27_native" / "editor_manual_default.json", snapshot)
    with pytest.raises(ValueError, match="场景资源文件损坏"):
        load_scenario_assets(root)


def test_truncated_creator_raises_chinese_error(tmp_path):
    root = write_engine_root(tmp_path)
    snapshot = make_snapshot()
    snapshot["teams"][0]["creator_hex"] = "00" * 16
    write_json(root / "fm27_native" / "editor_manual_default.json", snapshot)
    with pytest.raises(ValueError, match="场景资源文件损坏"):
        load_scenario_assets(root)


def test_invalid_oop_map_raises_chinese_error(tmp_path):
    root = write_engine_root(tmp_path)
    snapshot = make_setpiece_snapshot()
    snapshot["teams"][0]["manager_tactical_hex"] = make_manager_hex([0] * 11, [0, 1, 0])
    write_json(root / "fm27_native" / "editor_setpieces_default.json", snapshot)
    with pytest.raises(ValueError, match="OOP 映射"):
        load_scenario_assets(root)


def test_unknown_role_flag_raises_chinese_error(tmp_path):
    root = write_engine_root(tmp_path)
    snapshot = make_snapshot()
    snapshot["teams"][0]["tactical_slots"][0][0] = make_cell(1, 0x10)
    write_json(root / "fm27_native" / "editor_manual_default.json", snapshot)
    with pytest.raises(ValueError, match="缺少角色"):
        load_scenario_assets(root)
