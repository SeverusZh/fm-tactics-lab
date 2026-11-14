from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository
from fm27lab.application.draft_attributes import DraftAttributeService
from fm27lab.application.drafts import DraftService
from fm27lab.domain.attributes import ATTRIBUTE_COUNT, POSITION_ATTRIBUTE_COUNT, VISIBLE_GROUPS, group_indices
from fm27lab.domain.roster import POSITION_INDEX

VISIBLE_INDICES = sorted(frozenset().union(*(group_indices(group) for group in VISIBLE_GROUPS)))
SUMMARY_KEYS = ("id", "name", "source", "created_at", "updated_at")


def player(uid: int) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[0 if uid == 100 else 7] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes}


def team(name: str = "Home") -> dict[str, Any]:
    return {
        "name": name,
        "players": [player(100 + index) for index in range(23)],
        "roster_size": 23,
        "lineup": list(range(11)),
        "captains": [5],
        "takers": {"penalties": [6]},
        "setpieces": {"role_priorities": {"8": [8]}},
    }


def scenario() -> dict[str, Any]:
    return {"schema": 4, "teams": [team("Home"), team("Away")]}


class StubDrafts:
    def __init__(self, value: dict[str, Any]):
        self.value = value
        self.updated: dict[str, Any] | None = None

    def get(self, draft_id: str) -> dict[str, Any] | None:
        if draft_id != "draft":
            return None
        return {
            "id": "draft",
            "name": "Draft",
            "scenario": self.value,
            "source": {"kind": "stub"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }

    def update(self, draft_id: str, **changes: Any) -> dict[str, Any] | None:
        self.updated = changes
        return {
            "id": draft_id,
            "name": "Draft",
            "scenario": changes["scenario"],
            "source": changes["source"],
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:01+00:00",
        }


@pytest.fixture
def env(tmp_path: Path):
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    drafts = DraftService(DraftRepository(database))
    return DraftAttributeService(drafts), drafts, database


def create(drafts: DraftService) -> dict[str, Any]:
    return drafts.create("Draft", scenario(), {"kind": "inline"})


def teams(draft: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [team_value["players"] for team_value in draft["scenario"]["teams"]]


def test_missing_draft_returns_none(env):
    service, _, _ = env
    result = service.apply(
        "missing",
        side="home",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 12},
    )
    assert result is None


def test_bulk_apply_updates_all_players_and_persists_snapshot(env):
    service, drafts, _ = env
    draft = create(drafts)
    result = service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 12},
    )
    assert result["changed_players"] == 23
    snapshot = result["snapshot"]
    assert snapshot["side"] == "home"
    assert snapshot["scope"] == "all"
    assert snapshot["operation"] == "bulk"
    assert snapshot["indices"] == VISIBLE_INDICES
    assert snapshot["include_personality"] is False
    stored = drafts.get(draft["id"])
    assert stored["source"]["attribute_snapshot"] == snapshot
    assert result["draft"] == {key: stored[key] for key in SUMMARY_KEYS}
    home, away = teams(stored)
    for entry in home:
        assert [entry["attributes"][index] for index in VISIBLE_INDICES] == [60] * len(VISIBLE_INDICES)
        position_index = 0 if entry["source_uid"] == 100 else 7
        assert entry["attributes"][position_index] == 18
        assert entry["attributes"][39] == 10
    assert away == team("Away")["players"]


def test_apply_scope_selects_all_starters_player_and_squad(env):
    service, drafts, _ = env
    for scope, player_index, expected in (
        ("all", None, 23),
        ("starters", None, 11),
        ("player", 5, 1),
        ("squad", None, 23),
    ):
        draft = create(drafts)
        result = service.apply(
            draft["id"],
            side="home",
            scope=scope,
            player_index=player_index,
            operation="bulk",
            params={"value": 15},
        )
        assert result["changed_players"] == expected, scope
        assert result["snapshot"]["scope"] == scope
        home, away = teams(drafts.get(draft["id"]))
        touched = {5} if scope == "player" else set(range(11 if scope == "starters" else 23))
        for index, entry in enumerate(home):
            expected_value = 75 if index in touched else 10
            assert {entry["attributes"][item] for item in VISIBLE_INDICES} == {expected_value}, scope
        assert away == team("Away")["players"], scope


def test_apply_targets_requested_side_only(env):
    service, drafts, _ = env
    draft = create(drafts)
    service.apply(
        draft["id"],
        side="away",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 14},
    )
    home, away = teams(drafts.get(draft["id"]))
    assert home == team("Home")["players"]
    assert all({entry["attributes"][index] for index in VISIBLE_INDICES} == {70} for entry in away)


def test_squad_scope_skips_players_without_attributes(env):
    del env
    reference = player(100)
    bare = {"source_uid": 101, "name": "P101"}
    drafts = StubDrafts({"teams": [{"players": [reference, bare]}, {"players": [player(200)]}]})
    result = DraftAttributeService(drafts).apply(
        "draft",
        side="home",
        scope="squad",
        player_index=None,
        operation="position",
        params={"position": 0, "value": 4},
    )
    assert result["changed_players"] == 1
    assert [entry["source_uid"] for entry in result["snapshot"]["players"]] == [100]


def test_squad_scope_without_attributes_falls_back_to_all_players(env):
    del env
    drafts = StubDrafts(
        {
            "teams": [
                {"players": [{"source_uid": 100, "name": "A"}, {"source_uid": 101, "name": "B"}]},
                {"players": [player(200)]},
            ]
        }
    )
    with pytest.raises(ValueError, match="69"):
        DraftAttributeService(drafts).apply(
            "draft",
            side="home",
            scope="squad",
            player_index=None,
            operation="position",
            params={"position": 0, "value": 4},
        )
    assert drafts.updated is None


def test_position_operation_edits_one_familiarity_and_undo_restores(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="starters",
        player_index=None,
        operation="position",
        params={"position": "ST", "value": 7},
    )
    assert result["changed_players"] == 11
    assert result["snapshot"]["indices"] == [POSITION_INDEX["ST"]]
    home, _ = teams(drafts.get(draft["id"]))
    for index, entry in enumerate(home):
        assert entry["attributes"][POSITION_INDEX["ST"]] == (7 if index < 11 else 10)
    undone = service.apply(
        draft["id"],
        side="home",
        scope="starters",
        player_index=None,
        operation="undo",
        params={},
    )
    assert undone["snapshot"] is None
    assert undone["changed_players"] == 11
    stored = drafts.get(draft["id"])
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]


def test_copy_operation_copies_reference_groups_and_personality(env):
    service, drafts, _ = env
    raw = scenario()
    reference = raw["teams"][0]["players"][5]
    reference["attributes"][15] = 100
    reference["attributes"][16] = 1
    reference["attributes"][39] = 20
    reference["attributes"][49] = 2
    reference["native_profile"] = {"professionalism": 14, "loyalty": 3}
    draft = drafts.create("Draft", raw, {"kind": "inline"})
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="starters",
        player_index=None,
        operation="copy",
        params={"source_uid": 105},
    )
    assert result["changed_players"] == 10
    assert len(result["snapshot"]["players"]) == 11
    home, _ = teams(drafts.get(draft["id"]))
    reference_now = home[5]
    for index, entry in enumerate(home):
        if index >= 11:
            continue
        for attribute_index in range(15, ATTRIBUTE_COUNT):
            assert entry["attributes"][attribute_index] == reference_now["attributes"][attribute_index]
        assert entry["native_profile"] == {"professionalism": 14, "loyalty": 3}
        before = original["scenario"]["teams"][0]["players"][index]["attributes"]
        assert entry["attributes"][:POSITION_ATTRIBUTE_COUNT] == before[:POSITION_ATTRIBUTE_COUNT]
    undone = service.apply(
        draft["id"],
        side="home",
        scope="starters",
        player_index=None,
        operation="undo",
        params={},
    )
    assert undone["changed_players"] == 10
    stored = drafts.get(draft["id"])
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]


def test_copy_operation_accepts_source_index_groups_and_personality_switch(env):
    service, drafts, _ = env
    raw = scenario()
    reference = raw["teams"][0]["players"][6]
    reference["attributes"][15] = 88
    reference["attributes"][49] = 2
    draft = drafts.create("Draft", raw, {"kind": "inline"})
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=8,
        operation="copy",
        params={"source_index": 6, "groups": ["physical"], "copy_personality": False},
    )
    assert result["changed_players"] == 1
    assert result["snapshot"]["indices"] == sorted(group_indices("physical"))
    assert result["snapshot"]["include_personality"] is False
    home, _ = teams(drafts.get(draft["id"]))
    assert home[8]["attributes"][49] == 2
    assert home[8]["attributes"][15] == 10
    assert "native_profile" not in home[8]
    service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=8,
        operation="undo",
        params={},
    )
    assert drafts.get(draft["id"])["scenario"] == original["scenario"]


def test_pair_feet_operation_sets_foot_pair_and_undo_restores(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=2,
        operation="pair_feet",
        params={
            "left_index": 39,
            "right_index": 40,
            "preferred": "right",
            "preferred_value": 18,
            "weaker_value": 6,
        },
    )
    assert result["changed_players"] == 1
    assert result["snapshot"]["indices"] == [39, 40]
    home, _ = teams(drafts.get(draft["id"]))
    assert home[2]["attributes"][39] == 6
    assert home[2]["attributes"][40] == 18
    undone = service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=2,
        operation="undo",
        params={},
    )
    assert undone["snapshot"] is None
    stored = drafts.get(draft["id"])
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]


def test_pair_feet_scope_starters_updates_each_starter(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="starters",
        player_index=None,
        operation="pair_feet",
        params={
            "left_index": 39,
            "right_index": 40,
            "preferred": "left",
            "preferred_value": 19,
            "weaker_value": 5,
        },
    )
    assert result["changed_players"] == 11
    home, _ = teams(drafts.get(draft["id"]))
    for index, entry in enumerate(home):
        if index < 11:
            assert entry["attributes"][39] == 19
            assert entry["attributes"][40] == 5
        else:
            assert entry["attributes"][39] == 10
            assert entry["attributes"][40] == 10
    service.apply(draft["id"], side="home", scope="starters", player_index=None, operation="undo", params={})
    assert drafts.get(draft["id"])["scenario"] == original["scenario"]


def test_bulk_personality_switch_and_undo_removes_profiles(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 11, "include_personality": True},
    )
    assert result["changed_players"] == 23
    assert result["snapshot"]["include_personality"] is True
    home, _ = teams(drafts.get(draft["id"]))
    assert all(entry["native_profile"]["professionalism"] == 11 for entry in home)
    assert all(entry["native_profile"]["adaptability"] == 11 for entry in home)
    undone = service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="undo",
        params={},
    )
    assert undone["changed_players"] == 23
    stored = drafts.get(draft["id"])
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]


def test_snapshot_is_single_slot_and_side_isolated(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 12},
    )
    home_after_first = copy.deepcopy(teams(drafts.get(draft["id"]))[0])
    second = service.apply(
        draft["id"],
        side="away",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 16},
    )
    assert second["snapshot"]["side"] == "away"
    assert drafts.get(draft["id"])["source"]["attribute_snapshot"] == second["snapshot"]
    with pytest.raises(ValueError, match="队伍"):
        service.apply(
            draft["id"],
            side="home",
            scope="all",
            player_index=None,
            operation="undo",
            params={},
        )
    undone = service.apply(
        draft["id"],
        side="away",
        scope="all",
        player_index=None,
        operation="undo",
        params={},
    )
    assert undone["changed_players"] == 23
    stored = drafts.get(draft["id"])
    assert teams(stored)[1] == original["scenario"]["teams"][1]["players"]
    assert teams(stored)[0] == home_after_first
    assert "attribute_snapshot" not in stored["source"]


def test_undo_without_snapshot_raises(env):
    service, drafts, _ = env
    draft = create(drafts)
    with pytest.raises(ValueError, match="没有可撤销的属性修改"):
        service.apply(
            draft["id"],
            side="home",
            scope="all",
            player_index=None,
            operation="undo",
            params={},
        )


def test_changed_players_counts_actual_changes_and_undo_handles_noop(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 2},
    )
    assert result["changed_players"] == 0
    assert result["snapshot"]["players"][0]["attributes"] == [10] * len(VISIBLE_INDICES)
    undone = service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="undo",
        params={},
    )
    assert undone["changed_players"] == 0
    stored = drafts.get(draft["id"])
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]


def test_undo_after_roster_change_raises_and_keeps_snapshot(env):
    service, drafts, _ = env
    draft = create(drafts)
    service.apply(
        draft["id"],
        side="home",
        scope="starters",
        player_index=None,
        operation="bulk",
        params={"value": 12},
    )
    stored = drafts.get(draft["id"])
    changed = copy.deepcopy(stored["scenario"])
    changed["teams"][0]["players"][0]["source_uid"] = 999
    drafts.update(draft["id"], scenario=changed)
    with pytest.raises(ValueError, match="名单已变化"):
        service.apply(
            draft["id"],
            side="home",
            scope="starters",
            player_index=None,
            operation="undo",
            params={},
        )
    assert "attribute_snapshot" in drafts.get(draft["id"])["source"]


def test_invalid_arguments_raise_and_keep_draft_unchanged(env):
    service, drafts, _ = env
    draft = create(drafts)
    before = drafts.get(draft["id"])
    valid_bulk = {
        "side": "home",
        "scope": "all",
        "player_index": None,
        "operation": "bulk",
        "params": {"value": 12},
    }
    cases: list[tuple[dict[str, Any], str]] = [
        ({"side": "both"}, "side"),
        ({"side": 0}, "side"),
        ({"scope": "bench"}, "scope"),
        ({"scope": "player", "player_index": None}, "player_index"),
        ({"scope": "player", "player_index": 23}, "0–22"),
        ({"scope": "player", "player_index": True}, "0–22"),
        ({"scope": "starters", "player_index": 0}, "player_index"),
        ({"operation": "boost", "params": {}}, "操作"),
        ({"params": []}, "参数"),
        ({"params": {}}, "value"),
        ({"params": {"value": 12, "unknown": 1}}, "不支持"),
        ({"params": {"value": 21}}, "属性显示值"),
        ({"params": {"value": 12, "groups": ["unknown"]}}, "分组"),
        ({"operation": "position", "params": {"value": 5}}, "position"),
        ({"operation": "position", "params": {"position": "XYZ", "value": 5}}, "位置"),
        ({"operation": "copy", "params": {}}, "source_uid"),
        ({"operation": "copy", "params": {"source_uid": 100, "source_index": 1}}, "source_uid"),
        ({"operation": "copy", "params": {"source_uid": 999}}, "参考球员"),
        ({"operation": "copy", "params": {"source_index": 23}}, "参考球员"),
        ({"operation": "pair_feet", "params": {}}, "pair_feet"),
        (
            {
                "operation": "pair_feet",
                "params": {
                    "left_index": 39,
                    "right_index": 40,
                    "preferred": "left",
                    "preferred_value": 18,
                },
            },
            "weaker_value",
        ),
        (
            {
                "operation": "pair_feet",
                "params": {
                    "left_index": 14,
                    "right_index": 40,
                    "preferred": "left",
                    "preferred_value": 18,
                    "weaker_value": 6,
                },
            },
            "15–68",
        ),
        ({"operation": "undo", "params": {"x": 1}}, "undo"),
    ]
    for changes, message in cases:
        arguments = {**valid_bulk, **changes}
        with pytest.raises(ValueError, match=message):
            service.apply(draft["id"], **arguments)
    assert drafts.get(draft["id"]) == before


def test_persisted_draft_reload_matches_returned_summary(env):
    service, drafts, database = env
    draft = create(drafts)
    result = service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 12},
    )
    reloaded = DraftService(DraftRepository(database)).get(draft["id"])
    assert result["draft"] == {key: reloaded[key] for key in SUMMARY_KEYS}
    assert reloaded["source"]["attribute_snapshot"] == result["snapshot"]


def test_cells_scope_player_updates_single_cell_and_undo_restores(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=0,
        operation="cells",
        params={"values": {"7": 12, "68": 15}},
    )
    assert result["changed_players"] == 1
    snapshot = result["snapshot"]
    assert snapshot["scope"] == "player"
    assert snapshot["operation"] == "cells"
    assert snapshot["indices"] == [7, 68]
    assert snapshot["include_personality"] is False
    assert drafts.get(draft["id"])["source"]["attribute_snapshot"] == snapshot
    home, away = teams(drafts.get(draft["id"]))
    assert home[0]["attributes"][7] == 12
    assert home[0]["attributes"][68] == 75
    assert home[0]["attributes"][15] == 10
    assert home[1]["attributes"][7] == 18
    assert home[1]["attributes"][68] == 10
    assert away == team("Away")["players"]
    undone = service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=0,
        operation="undo",
        params={},
    )
    assert undone["snapshot"] is None
    assert undone["changed_players"] == 1
    stored = drafts.get(draft["id"])
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]


def test_cells_scope_squad_updates_every_player_and_undo_restores(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="squad",
        player_index=None,
        operation="cells",
        params={"values": {"14": 12, "68": 15}},
    )
    assert result["changed_players"] == 23
    home, away = teams(drafts.get(draft["id"]))
    for entry in home:
        assert entry["attributes"][14] == 12
        assert entry["attributes"][68] == 75
    assert away == team("Away")["players"]
    service.apply(
        draft["id"],
        side="home",
        scope="squad",
        player_index=None,
        operation="undo",
        params={},
    )
    stored = drafts.get(draft["id"])
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]


def test_cells_accepts_canonical_json_string_keys(env):
    service, drafts, _ = env
    draft = create(drafts)
    result = service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=3,
        operation="cells",
        params={"values": {"0": 9, "15": 13, "68": 20}},
    )
    assert result["snapshot"]["indices"] == [0, 15, 68]
    assert result["changed_players"] == 1
    home, _ = teams(drafts.get(draft["id"]))
    assert home[3]["attributes"][0] == 9
    assert home[3]["attributes"][15] == 65
    assert home[3]["attributes"][68] == 100
    assert home[3]["attributes"][16] == 10


def test_cells_rejects_malformed_index_keys_and_keeps_draft_unchanged(env):
    service, drafts, _ = env
    draft = create(drafts)
    before = drafts.get(draft["id"])
    base: dict[str, Any] = {
        "side": "home",
        "scope": "player",
        "player_index": 0,
        "operation": "cells",
    }
    cases: list[tuple[dict[str, Any], str]] = [
        ({"values": {"+68": 15}}, "十进制字符串"),
        ({"values": {" 68": 15}}, "十进制字符串"),
        ({"values": {"68 ": 15}}, "十进制字符串"),
        ({"values": {"068": 15}}, "十进制字符串"),
        ({"values": {"68.0": 15}}, "十进制字符串"),
        ({"values": {"-1": 15}}, "十进制字符串"),
        ({"values": {"ab": 15}}, "十进制字符串"),
        ({"values": {"６８": 15}}, "十进制字符串"),
        ({"values": {68: 15}}, "十进制字符串"),
        ({"values": {"69": 15}}, "十进制字符串"),
        ({"values": []}, "索引到显示值"),
        ({"values": "68"}, "索引到显示值"),
        ({"values": None}, "索引到显示值"),
        ({"values": {}}, "至少需要一个属性值"),
        ({}, "values"),
        ({"values": {"0": 21}}, "位置熟练度"),
        ({"values": {"68": 0}}, "属性显示值"),
    ]
    for params, message in cases:
        with pytest.raises(ValueError, match=message):
            service.apply(draft["id"], **{**base, "params": params})
    assert drafts.get(draft["id"]) == before


def test_cells_replaces_previous_snapshot_slot(env):
    service, drafts, _ = env
    draft = create(drafts)
    service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="bulk",
        params={"value": 12},
    )
    home_after_bulk = copy.deepcopy(teams(drafts.get(draft["id"]))[0])
    result = service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=0,
        operation="cells",
        params={"values": {"68": 15}},
    )
    assert drafts.get(draft["id"])["source"]["attribute_snapshot"] == result["snapshot"]
    home, _ = teams(drafts.get(draft["id"]))
    assert home[0]["attributes"][68] == 75
    assert home[0]["attributes"][15] == 60
    undone = service.apply(
        draft["id"],
        side="home",
        scope="player",
        player_index=0,
        operation="undo",
        params={},
    )
    assert undone["changed_players"] == 1
    stored = drafts.get(draft["id"])
    assert teams(stored)[0] == home_after_bulk
    assert "attribute_snapshot" not in stored["source"]


def test_cells_noop_keeps_changed_players_zero_and_undo_restores(env):
    service, drafts, _ = env
    draft = create(drafts)
    original = drafts.get(draft["id"])
    result = service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="cells",
        params={"values": {"68": 2}},
    )
    assert result["changed_players"] == 0
    assert result["snapshot"]["players"][0]["attributes"] == [10]
    undone = service.apply(
        draft["id"],
        side="home",
        scope="all",
        player_index=None,
        operation="undo",
        params={},
    )
    assert undone["changed_players"] == 0
    stored = drafts.get(draft["id"])
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]
