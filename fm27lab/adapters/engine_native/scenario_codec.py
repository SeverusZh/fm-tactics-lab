"""Native scenario codec ported from the legacy FM27 tactic server."""

from __future__ import annotations

import copy
import struct
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from fm27lab.domain import setpieces

if TYPE_CHECKING:
    from fm27lab.adapters.engine_native.scenario_assets import ScenarioAssets

MAGIC = b"FM27CFG1"
SCHEMA = 3
FIXTURE = "bundled_match_pkm"
RULES = ("game", "lab")
EXECUTION_COMPONENTS = ("understanding", "buy_in", "opposition", "ability")
DUTIES = ("0", "2097152", "4194304", "8388608", "33554432", "67108864", "17179869184")
FIELDS: dict[str, tuple[int, int, int]] = {
    "height_cm": (0, 140, 220),
    "age": (1, 14, 60),
    "professionalism": (2, 1, 20),
    "loyalty": (3, 1, 20),
    "sportsmanship": (4, 1, 20),
    "temperament": (5, 1, 20),
    "pressure": (6, 1, 20),
    "ambition": (7, 1, 20),
    "adaptability": (8, 1, 20),
    "traits_low": (9, 0, 0xFFFFFFFF),
    "traits_high": (10, 0, 0xFFFFFFFF),
    "current_ability": (11, 0, 200),
    "home_reputation": (12, 0, 10000),
    "current_reputation": (13, 0, 10000),
    "world_reputation": (14, 0, 10000),
    "condition": (15, 0, 10000),
    "sharpness": (16, 0, 10000),
    "sharpness_secondary": (17, 0, 10000),
    "fatigue_raw": (18, 0, 65535),
    "weight_kg": (19, 40, 140),
    "team_cohesion": (20, 0, 100),
    "club_cohesion": (21, 0, 100),
    "morale": (22, 1, 20),
}
CONTROLLED_START: dict[str, int] = {
    "condition": 10000,
    "sharpness": 10000,
    "sharpness_secondary": 10000,
    "fatigue_raw": 0,
    "team_cohesion": 80,
    "club_cohesion": 100,
    "morale": 20,
}
OOP_PERSONAL = 0x80000


def integer(value: Any, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}必须为 {low}–{high} 的整数")
    return value


def normalize_profile(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("未知球员扩展输入")
    normalized: dict[str, int] = {}
    for key, item in value.items():
        if key not in FIELDS:
            raise ValueError("未知球员扩展输入")
        _field_id, low, high = FIELDS[key]
        if type(item) is not int or not low <= item <= high:
            raise ValueError(f"球员扩展输入范围无效: {key}")
        normalized[key] = item
    return normalized


def unpack_oi(value: int) -> dict[str, Any]:
    return {
        "press": value & 7,
        "mark": (value >> 3) & 7,
        "tackle": (value >> 8) & 7,
        "foot": (value >> 11) & 7,
        "personal": bool(value & OOP_PERSONAL),
    }


def pack_oi(row: Mapping[str, Any]) -> int:
    return (
        row["press"]
        | (row["mark"] << 3)
        | (row["tackle"] << 8)
        | (row["foot"] << 11)
        | (OOP_PERSONAL if row["personal"] else 0)
    )


def _cell_hex(value: Any) -> bytes:
    try:
        return bytes.fromhex(value)
    except (TypeError, ValueError):
        raise ValueError("场景快照格式无效") from None


def defaults(assets: ScenarioAssets) -> dict[str, Any]:
    teams: list[dict[str, Any]] = []
    for side, snapshot_team in enumerate(assets.snapshot["teams"]):
        creator = _cell_hex(snapshot_team["creator_hex"])
        bits = int.from_bytes(creator[:16], "little")
        instructions: dict[str, int] = {}
        for group in assets.groups.values():
            active = [
                option["id"]
                for option in group["options"]
                if option.get("native_bit") and bits >> option["native_bit"] & 1
            ]
            if len(active) > 1:
                raise ValueError("场景资源球队指令冲突")
            instructions[str(group["id"])] = active[0] if active else next(
                (option["id"] for option in group["options"] if not option.get("native_bit")),
                group["options"][0]["id"],
            )
        phases: list[list[dict[str, Any]]] = []
        for phase in range(2):
            cells: list[dict[str, Any]] = []
            for index in range(11):
                native_slot = assets.oop_map[side][index] if phase else index
                raw = _cell_hex(snapshot_team["tactical_slots"][phase][native_slot])
                position_mask = struct.unpack_from("<I", raw)[0]
                flag = struct.unpack_from("<Q", raw, 64)[0] & assets.role_mask
                role = next(
                    (
                        candidate
                        for candidate in assets.roles.values()
                        if candidate["phase"] == phase and int(candidate["flags"]) == flag
                    ),
                    None,
                )
                if role is None:
                    raise ValueError(f"场景资源缺少角色: {phase}:{flag}")
                position = next(
                    (
                        candidate["id"]
                        for candidate in assets.positions.values()
                        if candidate["mask"] == position_mask
                    ),
                    None,
                )
                if position is None:
                    raise ValueError(f"场景资源缺少位置: {position_mask}")
                personal = snapshot_team["personal_instructions"][phase][native_slot]
                flags = int(personal["flags"])
                values = {
                    str(group["id"]): next(
                        (
                            option["id"]
                            for option in group["options"]
                            if option["id"] and flags >> option["id"] & 1
                        ),
                        0,
                    )
                    for group in assets.pis.values()
                }
                cells.append(
                    {
                        "position": position,
                        "role": role["id"],
                        "duty": str(struct.unpack_from("<Q", raw, 64)[0] & ~assets.role_mask),
                        "instructions": values,
                        "target_player": personal["target_player"],
                        "target_position": personal["target_position"],
                    }
                )
            phases.append(cells)
        advanced = assets.advanced["teams"][side]
        positional = {
            position["id"]: unpack_oi(
                next(
                    (
                        entry["packed"]
                        for entry in advanced["opposition_positions"]
                        if entry["position"] == position["mask"]
                    ),
                    OOP_PERSONAL,
                )
            )
            for position in assets.positions.values()
        }
        opposition = [
            unpack_oi(value)
            for value in advanced["opposition"][: assets.snapshot["teams"][1 - side]["count"]]
        ]
        teams.append(
            {
                "name": ["主队", "客队"][side],
                "tactic_name": "",
                "native_extra_team_bits": str(bits & ~assets.team_known_mask),
                "mentality": creator[0x25],
                "instructions": instructions,
                "lineup": list(range(11)),
                "opposition": {"players": opposition, "positions": positional},
                "captains": [],
                "takers": {key: [] for key in assets.taker_keys},
                "setpieces": copy.deepcopy(assets.setpiece_defaults[side]),
                "phases": phases,
                "players": [
                    {
                        "name": f"{['主', '客'][side]}队球员 {player['index'] + 1:02d}",
                        "native_id": player["id"],
                        "attributes": list(player["attributes"]),
                        "native_profile": copy.deepcopy(CONTROLLED_START),
                    }
                    for player in snapshot_team["players"]
                ],
            }
        )
    return {"schema": SCHEMA, "rules": "game", "fixture": FIXTURE, "teams": teams}


def _oi_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: integer(row[key], 0, maximum, "针对性指令")
        for key, maximum in (("press", 2), ("mark", 2), ("tackle", 3), ("foot", 3))
    }
    if type(row["personal"]) is not bool:
        raise ValueError("针对性指令模式无效")
    result["personal"] = row["personal"]
    return result


def _player_order(players: Any, base_players: Sequence[Mapping[str, Any]]) -> list[int]:
    """Map each source player index onto the matching match-sample player index.

    A source roster may hold the leading match squad of the sample, so it may be
    shorter than the sample list; the mapped indices must stay a prefix of it.
    """
    if not isinstance(players, list) or len(players) > len(base_players):
        raise ValueError("名单长度不匹配")
    positions = {player["native_id"]: index for index, player in enumerate(base_players)}
    order: list[int] = []
    for player in players:
        native = player.get("native_id") if isinstance(player, Mapping) else None
        if type(native) is not int or native not in positions:
            raise ValueError("球员顺序或标识不匹配")
        order.append(positions[native])
    if sorted(order) != list(range(len(order))):
        raise ValueError("球员顺序或标识不匹配")
    return order


def _remap_indices(values: Any, order: Sequence[int]) -> Any:
    if not isinstance(values, list):
        return values
    return [
        order[value] if type(value) is int and 0 <= value < len(order) else value
        for value in values
    ]


def _squad_size(team: Mapping[str, Any], order: Sequence[int]) -> int:
    if "roster_size" not in team:
        return len(order)
    players = team.get("players")
    if not isinstance(players, list) or len(players) < 11:
        raise ValueError("名单长度不匹配")
    return integer(team.get("roster_size"), 11, len(players), "比赛名单人数")


def _validate_team(
    side: int,
    source: Mapping[str, Any],
    base: Mapping[str, Any],
    assets: ScenarioAssets,
    *,
    order: Sequence[int],
    opponent_squad: int,
) -> dict[str, Any]:
    normalized = copy.deepcopy(base)
    normalized["name"] = str(source.get("name", base["name"]))[:40]
    normalized["tactic_name"] = str(source.get("tactic_name", base["tactic_name"]))[:120]
    try:
        extra = int(source.get("native_extra_team_bits", base["native_extra_team_bits"]))
    except (TypeError, ValueError):
        raise ValueError("附加原生战术选项格式无效") from None
    if extra < 0 or extra >= 1 << 128 or extra & assets.team_known_mask:
        raise ValueError("附加原生选项越界或与已命名指令重复")
    normalized["native_extra_team_bits"] = str(extra)
    normalized["mentality"] = integer(source.get("mentality", base["mentality"]), 1, 7, "比赛心态")
    roster_key = "roster_size" in source
    requested_roster = source.get("roster_size")
    instructions: dict[str, int] = {}
    for group in assets.groups.values():
        value = source.get("instructions", {}).get(
            str(group["id"]), base["instructions"][str(group["id"])]
        )
        integer(value, 0, 0xFFFFFFFF, "球队指令")
        if value not in [option["id"] for option in group["options"]]:
            raise ValueError("未知球队指令选项")
        instructions[str(group["id"])] = value
    normalized["instructions"] = instructions
    players = source.get("players")
    if not isinstance(players, list):
        raise ValueError("名单长度不匹配")
    if not roster_key and len(order) != len(base["players"]):
        raise ValueError("名单长度不匹配")
    if roster_key and len(players) < 11:
        raise ValueError("名单长度不匹配")
    if roster_key:
        roster_size = integer(requested_roster, 11, len(players), "比赛名单人数")
        normalized["roster_size"] = roster_size
    else:
        roster_size = len(base["players"])
    sources = [0] * len(order)
    for source_index, base_index in enumerate(order):
        sources[base_index] = source_index
    normalized_players: list[dict[str, Any]] = []
    for index, source_index in enumerate(sources):
        player = players[source_index]
        attributes = player.get("attributes")
        if not isinstance(attributes, list) or len(attributes) != 69:
            raise ValueError("每名球员必须包含69项原生输入")
        normalized_player = copy.deepcopy(base["players"][index])
        normalized_player["name"] = str(player.get("name", base["players"][index]["name"]))[:48]
        normalized_player["attributes"] = [
            integer(
                value,
                0 if attribute < 15 else 1,
                20 if attribute < 15 else 100,
                "属性",
            )
            for attribute, value in enumerate(attributes)
        ]
        profile = normalize_profile(player.get("native_profile", {}))
        profile.update(CONTROLLED_START)
        normalized_player["native_profile"] = profile
        normalized_players.append(normalized_player)
    normalized["players"] = normalized_players
    lineup = source.get("lineup")
    if not isinstance(lineup, list) or len(lineup) != 11 or len(set(lineup)) != 11:
        raise ValueError("首发必须是11名不同球员")
    normalized["lineup"] = [
        order[integer(slot, 0, len(order) - 1, "首发球员")] for slot in lineup
    ]
    if any(slot >= roster_size for slot in normalized["lineup"]):
        raise ValueError("首发包含未进入比赛名单的球员")
    source_captains = source.get("captains")
    captains = (
        base["captains"] if source_captains is None else _remap_indices(source_captains, order)
    )
    if (
        not isinstance(captains, list)
        or len(captains) > roster_size
        or len(set(captains)) != len(captains)
    ):
        raise ValueError("队长优先顺序无效")
    normalized["captains"] = [
        integer(slot, 0, roster_size - 1, "队长") for slot in captains
    ]
    setpieces_source = source.get("setpieces")
    if setpieces_source is None:
        setpieces_source = base["setpieces"]
    elif isinstance(setpieces_source, Mapping):
        setpieces_source = copy.deepcopy(dict(setpieces_source))
        priorities = setpieces_source.get("role_priorities")
        if isinstance(priorities, Mapping):
            setpieces_source["role_priorities"] = {
                key: _remap_indices(rows, order) for key, rows in priorities.items()
            }
    normalized["setpieces"] = setpieces.normalize(
        setpieces_source,
        side,
        roster_size,
        enums=assets.setpiece_enums,
        default_value=base["setpieces"],
    )
    source_takers = source.get("takers")
    takers = base["takers"] if source_takers is None else source_takers
    if not isinstance(takers, Mapping) or set(takers) != set(assets.taker_keys):
        raise ValueError("定位球主罚名单分类不符")
    normalized_takers: dict[str, list[int]] = {}
    for key in assets.taker_keys:
        values = takers[key]
        if source_takers is not None:
            values = _remap_indices(values, order)
        if (
            not isinstance(values, list)
            or len(values) > roster_size
            or any(type(value) is not int for value in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError("定位球主罚顺序无效")
        normalized_takers[key] = [
            integer(value, 0, roster_size - 1, "主罚球员") for value in values
        ]
    normalized["takers"] = normalized_takers
    opposition = source.get("opposition", base["opposition"])
    rows = opposition.get("players") if isinstance(opposition, Mapping) else None
    if not isinstance(rows, list) or len(rows) != len(base["opposition"]["players"]):
        raise ValueError("针对性指令的对方名单长度不符")
    for index, row in enumerate(rows):
        if index >= opponent_squad and row != base["opposition"]["players"][index]:
            raise ValueError("针对性指令只能设置进入比赛名单的对方球员")
    position_rows = opposition.get("positions") if isinstance(opposition, Mapping) else None
    if not isinstance(position_rows, Mapping) or set(assets.positions) - set(position_rows):
        raise ValueError("针对性指令的对方位置数据不符")
    normalized["opposition"] = {
        "players": [_oi_row(row) for row in rows],
        "positions": {
            position: _oi_row(position_rows[position]) for position in assets.positions
        },
    }
    phases = source.get("phases")
    if not isinstance(phases, list) or len(phases) != 2:
        raise ValueError("必须配置有球和无球阶段")
    normalized_phases: list[list[dict[str, Any]]] = []
    for phase, cells in enumerate(phases):
        if not isinstance(cells, list) or len(cells) != 11:
            raise ValueError("每个阶段必须有11个位置")
        positions = [cell["position"] for cell in cells]
        if positions.count("GK") != 1 or positions[0] != "GK" or len(set(positions)) != 11:
            raise ValueError("每个阶段必须有一名门将且位置不能重复；0号位置为门将")
        normalized_cells: list[dict[str, Any]] = []
        for index, cell in enumerate(cells):
            if (
                cell["position"] not in assets.positions
                or cell["role"] not in assets.roles
                or assets.roles[cell["role"]]["phase"] != phase
            ):
                raise ValueError("未知位置或阶段角色")
            original = base["phases"][phase][index]
            normalized_cell = copy.deepcopy(original)
            normalized_cell["position"] = cell["position"]
            normalized_cell["role"] = cell["role"]
            duty = str(
                cell.get(
                    "duty",
                    "0" if cell["role"] != original["role"] else original["duty"],
                )
            )
            if duty not in DUTIES:
                raise ValueError("未知角色职责位")
            normalized_cell["duty"] = duty
            cell_instructions: dict[str, int] = {}
            for group in assets.pis.values():
                value = cell.get("instructions", {}).get(str(group["id"]))
                if type(value) is not int or value not in [
                    option["id"] for option in group["options"]
                ]:
                    raise ValueError("未知个人指令选项")
                cell_instructions[str(group["id"])] = value
            normalized_cell["instructions"] = cell_instructions
            target = integer(cell.get("target_player"), 0, 255, "盯防球员")
            if target != 255 and target >= opponent_squad:
                raise ValueError("盯防球员不存在")
            normalized_cell["target_player"] = target
            if cell.get("target_position") not in [0] + [
                position["mask"] for position in assets.positions.values()
            ]:
                raise ValueError("盯防位置不存在")
            normalized_cell["target_position"] = cell["target_position"]
            if "14" in normalized_cell["instructions"]:
                if normalized_cell["instructions"]["14"] == 34 and target == 255:
                    raise ValueError("指定盯防需要选择对方名单序号")
                if normalized_cell["instructions"]["14"] == 35 and not normalized_cell["target_position"]:
                    raise ValueError("指定盯防需要选择位置")
            normalized_cells.append(normalized_cell)
        normalized_phases.append(normalized_cells)
    normalized["phases"] = normalized_phases
    return normalized


def validate_scenario(assets: ScenarioAssets, data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping) or data.get("schema") != SCHEMA or data.get("fixture") != FIXTURE:
        raise ValueError("方案格式或比赛样本不匹配")
    rules = data.get("rules")
    if rules not in RULES:
        raise ValueError("未知角色限制模式")
    if "native_generation" in data:
        raise ValueError("暂不支持电脑球队生成输入")
    teams = data.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        raise ValueError("必须包含两支球队")
    normalized: dict[str, Any] = {
        "schema": SCHEMA,
        "rules": rules,
        "fixture": FIXTURE,
        "teams": [],
    }
    orders: list[list[int]] = []
    for side, team in enumerate(teams):
        if not isinstance(team, Mapping):
            raise ValueError("必须包含两支球队")
        try:
            orders.append(
                _player_order(team.get("players"), assets.default_teams[side]["players"])
            )
        except (KeyError, IndexError, TypeError):
            raise ValueError("方案格式或比赛样本不匹配") from None
    squads = [_squad_size(teams[side], orders[side]) for side in range(2)]
    for side, team in enumerate(teams):
        try:
            normalized_team = _validate_team(
                side,
                team,
                assets.default_teams[side],
                assets,
                order=orders[side],
                opponent_squad=squads[1 - side],
            )
        except (KeyError, IndexError, TypeError):
            raise ValueError("方案格式或比赛样本不匹配") from None
        normalized["teams"].append(normalized_team)
    if "experimental_execution" in data:
        values = data["experimental_execution"]
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError("请分别设置两队的实验执行力")
        execution: list[Any] = []
        for value in values:
            if isinstance(value, dict):
                if set(value) not in (
                    set(EXECUTION_COMPONENTS[:3]),
                    set(EXECUTION_COMPONENTS),
                ):
                    raise ValueError("请填写战术理解、教练认可和对手情报")
                execution.append(
                    {
                        key: integer(value[key], 0, 100, "实验执行力分项")
                        for key in EXECUTION_COMPONENTS
                        if key in value
                    }
                )
            else:
                execution.append(integer(value, 0, 100, "实验执行力"))
        normalized["experimental_execution"] = execution
    return normalized


def encode_scenario(assets: ScenarioAssets, scenario: Any, absolute: bool = True) -> bytes:
    data = validate_scenario(assets, scenario)
    records: list[tuple[int, int, int, int, int]] = []
    for side, value in enumerate(data.get("experimental_execution", [])):
        if isinstance(value, dict):
            records.extend(
                (61, side, index, 0, value[key])
                for index, key in enumerate(EXECUTION_COMPONENTS, 1)
                if key in value
            )
        else:
            records.append((61, side, 0, 0, value))
    for side, team in enumerate(data["teams"]):
        base = assets.default_teams[side]
        records.append((10, side, 0, 0, 1))
        if "roster_size" in team:
            records.append((17, side, 0, 0, team["roster_size"]))
        records.extend(setpieces.encode_records(team["setpieces"], side, base["setpieces"]))
        records.append((13, side, 0, 0, int(data["rules"] == "game")))
        records.extend((12, side, index, 0, native) for index, native in enumerate(assets.oop_map[side]))
        for index, player in enumerate(team["players"]):
            if index >= team.get("roster_size", len(team["players"])):
                continue
            for key, value in player.get("native_profile", {}).items():
                records.append((15, side, index, FIELDS[key][0], value))
            for attribute, value in enumerate(player["attributes"]):
                if absolute or value != base["players"][index]["attributes"][attribute]:
                    records.append((1, side, index, attribute, value))
        for group, value in team["instructions"].items():
            if absolute or value != base["instructions"][group]:
                records.append((2, side, int(group), 0, value))
        extra = int(team.get("native_extra_team_bits", base["native_extra_team_bits"]))
        old_extra = int(base["native_extra_team_bits"])
        for bit in range(128):
            if not assets.team_known_mask >> bit & 1 and (
                absolute or (extra ^ old_extra) >> bit & 1
            ):
                records.append((60, side, bit, 0, extra >> bit & 1))
        if absolute or team["mentality"] != base["mentality"]:
            records.append((3, side, 0, 0, team["mentality"]))
        for phase, cells in enumerate(team["phases"]):
            for index, cell in enumerate(cells):
                original = base["phases"][phase][index]
                slot = phase * 16 + (assets.oop_map[side][index] if phase else index)
                if absolute or cell["role"] != original["role"]:
                    flags = int(assets.roles[cell["role"]]["flags"])
                    records.append((4, side, slot, flags >> 32, flags & 0xFFFFFFFF))
                if absolute or cell["position"] != original["position"]:
                    records.append((5, side, slot, 0, assets.positions[cell["position"]]["mask"]))
                if absolute or cell["duty"] != original["duty"]:
                    duty = int(cell["duty"])
                    records.append((14, side, slot, duty >> 32, duty & 0xFFFFFFFF))
                if absolute:
                    records.append((18, side, slot, 0, 0))
                for group, value in cell["instructions"].items():
                    if (
                        absolute
                        or value != original["instructions"][group]
                        or (cell["role"] != original["role"] and value)
                    ):
                        records.append((6, side, slot, int(group), value))
                if (
                    absolute
                    or cell["target_player"] != original["target_player"]
                    or (cell["role"] != original["role"] and cell["target_player"] != 255)
                ):
                    records.append((7, side, slot, 0, cell["target_player"]))
                if (
                    absolute
                    or cell["target_position"] != original["target_position"]
                    or (cell["role"] != original["role"] and cell["target_position"])
                ):
                    records.append((7, side, slot, 1, cell["target_position"]))
        if absolute or team["lineup"] != base["lineup"]:
            records.extend((11, side, index, 0, player) for index, player in enumerate(team["lineup"]))
        other = data["teams"][1 - side]
        order = other["lineup"] + [
            index for index in range(len(other["players"])) if index not in other["lineup"]
        ]
        for index, row in enumerate(team["opposition"]["players"]):
            if row != base["opposition"]["players"][index]:
                records.append((20, side, order.index(index), 0, pack_oi(row)))
        for position, row in team["opposition"]["positions"].items():
            if row != base["opposition"]["positions"][position]:
                records.append((21, side, assets.positions[position]["mask"], 0, pack_oi(row)))
        if team["captains"] != base["captains"]:
            records.append((30, side, 0, 0xFFFFFFFF, 0))
            records.extend((30, side, 0, rank, player) for rank, player in enumerate(team["captains"]))
            captain = next((player for player in team["captains"] if player in team["lineup"]), 0xFFFFFFFF)
            records.append((31, side, 0, 0, captain))
        for list_id, key in enumerate(assets.taker_keys, 1):
            if team["takers"][key] != base["takers"][key]:
                records.append((30, side, list_id, 0xFFFFFFFF, 0))
                records.extend(
                    (30, side, list_id, rank, player)
                    for rank, player in enumerate(team["takers"][key])
                )
    return (
        MAGIC
        + struct.pack("<I", len(records))
        + b"".join(struct.pack("<5I", *record) for record in records)
    )
