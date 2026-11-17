"""Unbound drafts survive save imports and replacements."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository
from fm27lab.adapters.storage_sqlite.saves import SavesRepository
from fm27lab.application.drafts import DraftService
from fm27lab.application.save_import import SaveImportService
from fm27lab.application.saves import SavesService
from fm27lab.domain.roster import MATCH_ROSTER_SIZE, STARTERS

ATTRIBUTE_COUNT = 69


def player(uid: int) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[0] = 16
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes, "ability": 12}


def team(name: str, base: int) -> dict[str, Any]:
    return {
        "name": name,
        "players": [player(base + index) for index in range(MATCH_ROSTER_SIZE)],
        "roster_size": MATCH_ROSTER_SIZE,
        "lineup": list(range(STARTERS)),
        "substitutes": list(range(STARTERS, MATCH_ROSTER_SIZE)),
        "captains": [5],
        "takers": {"penalties": [5], "corners": [2]},
        "setpieces": {"role_priorities": {"8": [8]}, "marking": "zonal"},
        "phases": [{"phase": 0}, {"phase": 1}],
    }


def scenario() -> dict[str, Any]:
    return {"schema": 4, "teams": [team("Home", 100), team("Away", 200)]}


def save_player(uid: int) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[7] = 15
    return {"source_uid": uid, "name": f"S{uid}", "attributes": attributes, "ability": 12}


def save_data(club_uid: int, club_name: str) -> dict[str, Any]:
    uids = list(range(club_uid * 1000, club_uid * 1000 + MATCH_ROSTER_SIZE))
    return {
        "info": {
            "game": "FM27",
            "build": "27.0.1+2503222",
            "db_version": "27.0",
            "game_date": "2026-07-01",
            "save_name": "season",
        },
        "managed_clubs": [
            {
                "club_uid": club_uid,
                "club_name": club_name,
                "club_short_name": club_name[:3],
                "manager_name": "教练",
                "manager_staff_uid": club_uid * 10 + 1,
            }
        ],
        "clubs": [
            {
                "uid": club_uid,
                "unique_id": club_uid * 100,
                "name": club_name,
                "short_name": club_name[:3],
                "nation_id": 1,
            }
        ],
        "squads": {club_uid: [save_player(uid) for uid in uids]},
        "selections": {
            club_uid: {
                "club_uid": club_uid,
                "team_id": 100,
                "team_slot": 0,
                "lineup": uids[:STARTERS],
                "substitutes": uids[STARTERS:],
            }
        },
    }


class FakeReader:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    def read_info(self) -> dict[str, Any]:
        return copy.deepcopy(self.data["info"])

    def read_managed_clubs(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.data["managed_clubs"])

    def read_clubs(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.data["clubs"])

    def read_squad(self, club_uid: int) -> list[dict[str, Any]]:
        return copy.deepcopy(self.data["squads"][club_uid])

    def read_selection(self, club_uid: int) -> dict[str, Any] | None:
        return copy.deepcopy(self.data["selections"].get(club_uid))


def service(tmp_path: Path, data: dict[str, Any]) -> tuple[SaveImportService, DraftService]:
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    drafts = DraftService(DraftRepository(database))
    saves = SavesService(SavesRepository(database))
    return SaveImportService(saves, drafts, lambda _path: FakeReader(data)), drafts


def test_replacing_a_save_keeps_unbound_drafts(tmp_path: Path):
    importer, drafts = service(tmp_path, save_data(7, "阿森纳"))
    draft = drafts.create("Legacy plan", scenario(), {"kind": "inline"})
    source = tmp_path / "season.fm"
    source.write_bytes(b"FM27 save bytes")

    importer.import_save(str(source))
    importer.import_save(str(source), replace=True)

    stored = drafts.get(draft["id"])
    assert stored is not None
    assert stored["name"] == "Legacy plan"
    assert stored["scenario"] == draft["scenario"]
    assert [item["id"] for item in drafts.list()["items"]] == [draft["id"]]


def test_importing_another_club_keeps_unbound_drafts(tmp_path: Path):
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    drafts = DraftService(DraftRepository(database))
    saves = SavesService(SavesRepository(database))
    draft = drafts.create("Shared plan", scenario(), {"kind": "inline"})
    first = tmp_path / "first.fm"
    first.write_bytes(b"first save")
    SaveImportService(saves, drafts, lambda _path: FakeReader(save_data(7, "阿森纳"))).import_save(
        str(first)
    )
    second = tmp_path / "second.fm"
    second.write_bytes(b"second save")
    SaveImportService(saves, drafts, lambda _path: FakeReader(save_data(9, "切尔西"))).import_save(
        str(second)
    )

    stored = drafts.get(draft["id"])
    assert stored is not None
    assert stored["scenario"] == draft["scenario"]
    assert len(saves.list()["items"]) == 2
