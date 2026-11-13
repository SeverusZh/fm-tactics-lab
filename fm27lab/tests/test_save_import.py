from __future__ import annotations

import copy
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository
from fm27lab.adapters.storage_sqlite.saves import SavesRepository
from fm27lab.application.drafts import DraftService
from fm27lab.application.save_import import SaveImportService
from fm27lab.application.saves import SavesService
from fm27lab.domain.roster import MATCH_ROSTER_SIZE, STARTERS

ATTRIBUTE_COUNT = 69
SUMMARY_KEYS = ("id", "name", "source", "created_at", "updated_at")
SAVE_BYTES = b"FM27 save bytes"
SAVED_STARTERS = [500, 501, 502, 105, 504, 505, 506, 108, 508, 509, 510]
SAVED_SUBSTITUTES = list(range(511, 523))
SAVED_UIDS = SAVED_STARTERS + SAVED_SUBSTITUTES
OTHER_UIDS = list(range(600, 623))


def save_player(uid: int, *, goalkeeper: bool = False) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[0 if goalkeeper else 7] = 18
    return {"source_uid": uid, "name": f"S{uid}", "attributes": attributes, "ability": 12}


def draft_player(uid: int, *, goalkeeper: bool = False) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[0 if goalkeeper else 7] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes}


def squad(uids: list[int]) -> list[dict[str, Any]]:
    return [save_player(uid, goalkeeper=index == 0) for index, uid in enumerate(uids)]


def selection(club_uid: int, lineup: list[int], substitutes: list[int]) -> dict[str, Any]:
    return {
        "club_uid": club_uid,
        "team_id": 100,
        "team_slot": 0,
        "lineup": list(lineup),
        "substitutes": list(substitutes),
    }


def managed_club(club_uid: int, name: str, short_name: str) -> dict[str, Any]:
    return {
        "club_uid": club_uid,
        "club_name": name,
        "club_short_name": short_name,
        "manager_name": "教练",
        "manager_staff_uid": club_uid * 10 + 1,
    }


def save_data(managed: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "info": {
            "game": "FM27",
            "build": "27.1.0",
            "db_version": "27.0",
            "game_date": "2026-07-01",
            "save_name": "season",
        },
        "managed_clubs": list(managed) if managed is not None else [managed_club(7, "阿森纳", "ARS")],
        "clubs": [
            {"uid": 7, "unique_id": 700, "name": "Arsenal", "short_name": "Ars", "nation_id": 1},
            {"uid": 9, "unique_id": 900, "name": "Chelsea", "short_name": "Che", "nation_id": 1},
        ],
        "squads": {7: squad(SAVED_UIDS), 9: squad(OTHER_UIDS)},
        "selections": {
            7: selection(7, SAVED_STARTERS, SAVED_SUBSTITUTES),
            9: selection(9, OTHER_UIDS[:STARTERS], OTHER_UIDS[STARTERS:]),
        },
    }


class FakeReader:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.calls: list[tuple[str, int | None]] = []

    def read_info(self) -> dict[str, Any]:
        self.calls.append(("info", None))
        return copy.deepcopy(self.data["info"])

    def read_managed_clubs(self) -> list[dict[str, Any]]:
        self.calls.append(("managed_clubs", None))
        return copy.deepcopy(self.data["managed_clubs"])

    def read_clubs(self) -> list[dict[str, Any]]:
        self.calls.append(("clubs", None))
        return copy.deepcopy(self.data["clubs"])

    def read_squad(self, club_uid: int) -> list[dict[str, Any]]:
        self.calls.append(("squad", club_uid))
        return copy.deepcopy(self.data["squads"][club_uid])

    def read_selection(self, club_uid: int) -> dict[str, Any] | None:
        self.calls.append(("selection", club_uid))
        return copy.deepcopy(self.data["selections"].get(club_uid))


class FakeFactory:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.paths: list[Path] = []
        self.readers: list[FakeReader] = []

    def __call__(self, path: Path) -> FakeReader:
        self.paths.append(Path(path))
        reader = FakeReader(self.data)
        self.readers.append(reader)
        return reader


def make_service(tmp_path: Path, data: dict[str, Any]):
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    saves = SavesService(SavesRepository(database))
    drafts = DraftService(DraftRepository(database))
    factory = FakeFactory(copy.deepcopy(data))
    return SaveImportService(saves, drafts, factory), saves, drafts, factory


@pytest.fixture
def env(tmp_path: Path):
    return make_service(tmp_path, save_data())


def source_file(tmp_path: Path, name: str = "season.fm", content: bytes = SAVE_BYTES) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def draft_team(name: str, base: int) -> dict[str, Any]:
    return {
        "name": name,
        "players": [draft_player(base + index, goalkeeper=index == 0) for index in range(MATCH_ROSTER_SIZE)],
        "roster_size": MATCH_ROSTER_SIZE,
        "lineup": list(range(STARTERS)),
        "substitutes": list(range(STARTERS, MATCH_ROSTER_SIZE)),
        "captains": [5],
        "takers": {"penalties": [5], "corners": [2]},
        "setpieces": {"role_priorities": {"8": [8]}, "marking": "zonal"},
        "phases": [{"phase": 0}, {"phase": 1}],
    }


def scenario() -> dict[str, Any]:
    return {"schema": 4, "teams": [draft_team("Home", 100), draft_team("Away", 200)]}


def generated_player(index: int) -> dict[str, Any]:
    attributes = [10] * ATTRIBUTE_COUNT
    attributes[7] = 15
    return {
        "source_uid": f"generated:{index}",
        "name": f"占位球员 {index}",
        "attributes": attributes,
        "ability": 10,
        "generated": True,
    }


def placeholder_team(name: str, base: int, *, placeholder_starters: bool) -> dict[str, Any]:
    if placeholder_starters:
        players = [generated_player(index) for index in range(1, STARTERS + 1)]
        players += [
            draft_player(base + index, goalkeeper=index == 0) for index in range(MATCH_ROSTER_SIZE - STARTERS)
        ]
    else:
        players = [draft_player(base + index, goalkeeper=index == 0) for index in range(STARTERS)]
        players += [generated_player(index) for index in range(1, MATCH_ROSTER_SIZE - STARTERS + 1)]
    return {
        "name": name,
        "players": players,
        "roster_size": MATCH_ROSTER_SIZE,
        "lineup": list(range(STARTERS)),
        "substitutes": list(range(STARTERS, MATCH_ROSTER_SIZE)),
        "captains": [5],
        "takers": {"penalties": [5], "corners": [2]},
        "setpieces": {"role_priorities": {"8": [8]}},
        "phases": [{"phase": 0}, {"phase": 1}],
    }


def placeholder_scenario() -> dict[str, Any]:
    return {
        "schema": 4,
        "teams": [
            placeholder_team("Home", 100, placeholder_starters=False),
            placeholder_team("Away", 200, placeholder_starters=True),
        ],
    }


def created_placeholder_draft(drafts: DraftService) -> dict[str, Any]:
    return drafts.create("Placeholders", placeholder_scenario(), {"kind": "inline"})


def club_insert_trigger(database, club_uid: int) -> None:
    with closing(database.connect()) as connection:
        connection.execute(
            "CREATE TRIGGER fail_save_club_insert BEFORE INSERT ON save_clubs "
            f"WHEN NEW.club_uid = {club_uid} BEGIN SELECT RAISE(ABORT, '插入失败'); END"
        )


def drop_club_insert_trigger(database) -> None:
    with closing(database.connect()) as connection:
        connection.execute("DROP TRIGGER IF EXISTS fail_save_club_insert")


def imported(service: SaveImportService, tmp_path: Path) -> dict[str, Any]:
    return service.import_save(str(source_file(tmp_path)))


def created_draft(drafts: DraftService) -> dict[str, Any]:
    return drafts.create("Draft", scenario(), {"kind": "inline"})


def uids(players: list[dict[str, Any]]) -> list[int]:
    return [player["source_uid"] for player in players]


def test_import_save_persists_record_metadata_and_club_payloads(env, tmp_path: Path):
    service, saves, _, factory = env
    path = source_file(tmp_path)

    result = service.import_save(str(path))

    assert set(result) == {"save_id", "status", "managed_clubs", "clubs"}
    assert result["status"] == "ready"
    assert result["clubs"] == 1
    assert result["managed_clubs"] == [{"club_uid": 7, "club_name": "阿森纳", "players": 23}]
    record = saves.get(result["save_id"])
    assert record is not None
    assert record["status"] == "ready"
    assert record["source_path"] == str(path)
    assert record["source_sha256"] == hashlib.sha256(SAVE_BYTES).hexdigest()
    assert record["metadata"] == {
        "game": "FM27",
        "build": "27.1.0",
        "game_date": "2026-07-01",
        "managed_club_uids": [7],
    }
    rows = saves.clubs(result["save_id"])
    assert [row["club_uid"] for row in rows] == [7]
    assert rows[0]["payload"] == {
        "club_uid": 7,
        "club_name": "阿森纳",
        "club_short_name": "ARS",
        "manager_name": "教练",
        "manager_staff_uid": 71,
        "name": "Arsenal",
        "short_name": "Ars",
        "nation_id": 1,
        "players": save_data()["squads"][7],
        "selection": save_data()["selections"][7],
    }
    assert factory.paths == [path]
    calls = factory.readers[0].calls
    for expected in (
        ("info", None),
        ("managed_clubs", None),
        ("clubs", None),
        ("squad", 7),
        ("selection", 7),
    ):
        assert expected in calls


def test_import_save_reads_squad_and_selection_for_every_managed_club(tmp_path: Path):
    data = save_data([managed_club(7, "阿森纳", "ARS"), managed_club(9, "切尔西", "CHE")])
    service, saves, _, factory = make_service(tmp_path, data)

    result = service.import_save(str(source_file(tmp_path)))

    assert result["clubs"] == 2
    assert [entry["club_uid"] for entry in result["managed_clubs"]] == [7, 9]
    rows = saves.clubs(result["save_id"])
    assert [row["club_uid"] for row in rows] == [7, 9]
    assert uids(rows[1]["payload"]["players"]) == OTHER_UIDS
    assert rows[1]["payload"]["selection"]["lineup"] == OTHER_UIDS[:STARTERS]
    calls = factory.readers[0].calls
    assert ("squad", 9) in calls
    assert ("selection", 9) in calls


def test_import_save_missing_path_is_rejected_without_writes(env, tmp_path: Path):
    service, saves, _, factory = env
    for value in (str(tmp_path / "missing.fm"), str(tmp_path), "", None, 5):
        with pytest.raises(ValueError, match="存档文件不存在"):
            service.import_save(value)
    assert saves.list(limit=256)["items"] == []
    assert factory.paths == []


def test_import_save_duplicate_content_is_rejected(env, tmp_path: Path):
    service, saves, _, _ = env
    first = imported(service, tmp_path)
    other = source_file(tmp_path, "copy.fm")

    with pytest.raises(ValueError, match="存档内容重复"):
        service.import_save(str(other))

    assert saves.list(limit=256)["total"] == 1
    assert saves.get(first["save_id"]) is not None


def test_import_save_replace_refreshes_existing_record(env, tmp_path: Path):
    service, saves, _, factory = env
    source_file(tmp_path)
    first = imported(service, tmp_path)

    factory.data["info"] = {**factory.data["info"], "build": "27.2.0"}
    factory.data["managed_clubs"] = [managed_club(9, "切尔西", "CHE")]
    second = service.import_save(str(source_file(tmp_path, "again.fm")), replace=True)

    assert second["save_id"] == first["save_id"]
    assert second["clubs"] == 1
    record = saves.get(first["save_id"])
    assert record["metadata"]["build"] == "27.2.0"
    assert record["metadata"]["managed_club_uids"] == [9]
    assert [row["club_uid"] for row in saves.clubs(first["save_id"])] == [9]
    assert saves.list(limit=256)["total"] == 1


def test_import_save_reader_failure_leaves_no_record(env, tmp_path: Path):
    _, saves, _, _ = env
    path = source_file(tmp_path)

    class BrokenFactory:
        def __call__(self, _path: Path) -> FakeReader:
            raise ValueError("不是有效的 FM 存档")

    service = SaveImportService(
        saves, DraftService(DraftRepository(saves.repository.database)), BrokenFactory()
    )
    with pytest.raises(ValueError, match="不是有效的 FM 存档"):
        service.import_save(str(path))
    assert saves.list(limit=256)["items"] == []


def test_get_squad_returns_players_and_selection(env, tmp_path: Path):
    service, _, _, _ = env
    save = imported(service, tmp_path)

    squad_value = service.get_squad(save["save_id"], 7)

    assert set(squad_value) == {"save_id", "club_uid", "club_name", "players", "selection"}
    assert squad_value["save_id"] == save["save_id"]
    assert squad_value["club_uid"] == 7
    assert squad_value["club_name"] == "阿森纳"
    assert uids(squad_value["players"]) == SAVED_UIDS
    assert squad_value["selection"] == save_data()["selections"][7]
    assert service.get_squad(save["save_id"], 999) is None
    assert service.get_squad("missing", 7) is None
    with pytest.raises(ValueError, match="俱乐部标识无效"):
        service.get_squad(save["save_id"], 0)
    with pytest.raises(ValueError, match="俱乐部标识无效"):
        service.get_squad(save["save_id"], True)


def test_apply_roster_both_replaces_roster_and_remaps_references(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)
    original = drafts.get(draft["id"])

    result = service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")

    assert set(result) == {"draft", "applied"}
    assert result["applied"] == {"starters": 11, "substitutes": 12}
    stored = drafts.get(draft["id"])
    assert result["draft"] == {key: stored[key] for key in SUMMARY_KEYS}
    home = stored["scenario"]["teams"][0]
    assert uids(home["players"]) == SAVED_UIDS
    assert home["lineup"] == list(range(STARTERS))
    assert uids(home["players"])[STARTERS:] == SAVED_SUBSTITUTES
    assert home["captains"] == [3]
    assert home["takers"]["penalties"] == [3]
    assert home["setpieces"]["role_priorities"]["8"] == [7]
    assert home["setpieces"]["marking"] == "zonal"
    assert home["phases"] == original["scenario"]["teams"][0]["phases"]
    assert stored["scenario"]["teams"][1] == original["scenario"]["teams"][1]
    snapshot = stored["source"]["roster_snapshot"]
    assert snapshot["side"] == "home"
    assert snapshot["save_id"] == save["save_id"]
    assert snapshot["club_uid"] == 7
    assert snapshot["scenario_before"] == original["scenario"]


def test_apply_roster_starters_only_replaces_lineup_section(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)

    result = service.apply_roster(draft["id"], save["save_id"], 7, "home", "starters")

    assert result["applied"] == {"starters": 11, "substitutes": 0}
    home = drafts.get(draft["id"])["scenario"]["teams"][0]
    assert uids(home["players"]) == SAVED_STARTERS + list(range(111, 123))
    assert home["lineup"] == list(range(STARTERS))
    assert home["captains"] == [3]
    assert home["takers"]["penalties"] == [3]
    assert home["setpieces"]["role_priorities"]["8"] == [7]


def test_apply_roster_bench_only_replaces_substitutes_section(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)

    result = service.apply_roster(draft["id"], save["save_id"], 7, "home", "bench")

    assert result["applied"] == {"starters": 0, "substitutes": 12}
    home = drafts.get(draft["id"])["scenario"]["teams"][0]
    assert uids(home["players"]) == list(range(100, 111)) + SAVED_SUBSTITUTES
    assert home["lineup"] == list(range(STARTERS))
    assert home["captains"] == [5]
    assert home["takers"]["penalties"] == [5]
    assert home["takers"]["corners"] == [2]
    assert home["setpieces"]["role_priorities"]["8"] == [8]


def test_apply_roster_uses_persisted_payload_not_reader(env, tmp_path: Path):
    service, _, drafts, factory = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)

    factory.data["squads"][7] = squad(OTHER_UIDS)
    service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")

    home = drafts.get(draft["id"])["scenario"]["teams"][0]
    assert uids(home["players"]) == SAVED_UIDS


def test_apply_roster_reports_no_applied_changes_when_roster_matches(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)
    first = service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")
    assert first["applied"] == {"starters": 11, "substitutes": 12}

    second = service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")

    assert second["applied"] == {"starters": 0, "substitutes": 0}


def test_undo_roster_restores_scenario_and_removes_snapshot(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)
    original = drafts.get(draft["id"])
    service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")

    result = service.undo_roster(draft["id"])

    assert set(result) == {"draft"}
    stored = drafts.get(draft["id"])
    assert result["draft"] == {key: stored[key] for key in SUMMARY_KEYS}
    assert stored["scenario"] == original["scenario"]
    assert stored["source"] == original["source"]
    assert "roster_snapshot" not in stored["source"]
    with pytest.raises(ValueError, match="没有可撤销的阵容同步"):
        service.undo_roster(draft["id"])
    assert service.undo_roster("missing") is None


def test_apply_roster_snapshot_keeps_single_slot(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)
    service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")
    after_first = drafts.get(draft["id"])

    service.apply_roster(draft["id"], save["save_id"], 7, "home", "bench")
    restored = service.undo_roster(draft["id"])

    assert restored is not None
    assert drafts.get(draft["id"])["scenario"] == after_first["scenario"]
    assert "roster_snapshot" not in drafts.get(draft["id"])["source"]


def test_apply_roster_missing_draft_save_or_club_returns_none(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)

    assert service.apply_roster("missing", save["save_id"], 7, "home", "both") is None
    assert service.apply_roster(draft["id"], "missing", 7, "home", "both") is None
    assert service.apply_roster(draft["id"], save["save_id"], 999, "home", "both") is None


def test_apply_roster_rejects_invalid_side_and_scope_without_changes(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)
    before = drafts.get(draft["id"])

    for side in ("both", "HOME", "", 0, None):
        with pytest.raises(ValueError, match="side"):
            service.apply_roster(draft["id"], save["save_id"], 7, side, "both")
    for scope in ("all", "starter", "", 0, None):
        with pytest.raises(ValueError, match="scope"):
            service.apply_roster(draft["id"], save["save_id"], 7, "home", scope)

    assert drafts.get(draft["id"]) == before


def test_apply_roster_rejects_incomplete_saved_squad_without_snapshot(tmp_path: Path):
    data = save_data()
    data["squads"][7] = squad(OTHER_UIDS[:10])
    service, _, drafts, _ = make_service(tmp_path, data)
    save = service.import_save(str(source_file(tmp_path)))
    draft = created_draft(drafts)
    before = drafts.get(draft["id"])

    with pytest.raises(ValueError, match="存档球队不足 23 名真实球员"):
        service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")

    assert drafts.get(draft["id"]) == before


def test_apply_roster_translates_domain_roster_errors(tmp_path: Path):
    data = save_data()
    data["squads"][7] = [save_player(uid) for uid in SAVED_UIDS]
    service, _, drafts, _ = make_service(tmp_path, data)
    save = service.import_save(str(source_file(tmp_path)))
    draft = created_draft(drafts)

    with pytest.raises(ValueError, match="存档球队缺少门将"):
        service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")


def test_import_save_reader_failure_midway_leaves_no_record(tmp_path: Path):
    data = save_data([managed_club(7, "阿森纳", "ARS"), managed_club(9, "切尔西", "CHE")])

    class FailingReader(FakeReader):
        def read_squad(self, club_uid: int) -> list[dict[str, Any]]:
            if club_uid == 9:
                raise ValueError("不是有效的 FM 存档")
            return super().read_squad(club_uid)

    class FailingFactory(FakeFactory):
        def __call__(self, path: Path) -> FailingReader:
            self.paths.append(Path(path))
            return FailingReader(self.data)

    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    saves = SavesService(SavesRepository(database))
    drafts = DraftService(DraftRepository(database))
    service = SaveImportService(saves, drafts, FailingFactory(copy.deepcopy(data)))

    with pytest.raises(ValueError, match="不是有效的 FM 存档"):
        service.import_save(str(source_file(tmp_path)))

    assert saves.list(limit=256)["items"] == []


def test_apply_roster_targets_requested_side_only(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_draft(drafts)
    original = drafts.get(draft["id"])

    service.apply_roster(draft["id"], save["save_id"], 7, "away", "both")

    stored = drafts.get(draft["id"])
    assert stored["scenario"]["teams"][0] == original["scenario"]["teams"][0]
    away = stored["scenario"]["teams"][1]
    assert uids(away["players"]) == SAVED_UIDS
    assert stored["source"]["roster_snapshot"]["side"] == "away"


def test_apply_roster_starters_keeps_generated_bench(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_placeholder_draft(drafts)
    before = drafts.get(draft["id"])

    result = service.apply_roster(draft["id"], save["save_id"], 7, "home", "starters")

    assert result["applied"] == {"starters": 11, "substitutes": 0}
    stored = drafts.get(draft["id"])
    assert stored["scenario"]["teams"][1] == before["scenario"]["teams"][1]
    home = stored["scenario"]["teams"][0]
    assert uids(home["players"][:STARTERS]) == SAVED_STARTERS
    assert all(player.get("generated") is True for player in home["players"][STARTERS:])
    assert [player["name"] for player in home["players"][STARTERS:]] == [
        f"占位球员 {index}" for index in range(1, MATCH_ROSTER_SIZE - STARTERS + 1)
    ]
    assert home["lineup"] == list(range(STARTERS))
    assert home["captains"] == [3]
    assert home["takers"]["penalties"] == [3]
    assert home["setpieces"]["role_priorities"]["8"] == [7]
    assert home["takers"]["corners"]
    assert all(
        not player.get("generated")
        for index in home["takers"]["corners"]
        for player in [home["players"][index]]
    )


def test_apply_roster_bench_keeps_generated_starters(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_placeholder_draft(drafts)
    before = drafts.get(draft["id"])
    before_away = before["scenario"]["teams"][1]

    result = service.apply_roster(draft["id"], save["save_id"], 7, "away", "bench")

    assert result["applied"] == {"starters": 0, "substitutes": 12}
    stored = drafts.get(draft["id"])
    assert stored["scenario"]["teams"][0] == before["scenario"]["teams"][0]
    away = stored["scenario"]["teams"][1]
    assert away["players"][:STARTERS] == before_away["players"][:STARTERS]
    assert any(player.get("generated") is True for player in away["players"][:STARTERS])
    assert uids(away["players"][STARTERS:]) == SAVED_SUBSTITUTES
    assert away["captains"] == before_away["captains"]
    for values in away["takers"].values():
        assert values
        assert all(not away["players"][index].get("generated") for index in values)
    assert all(
        not away["players"][index].get("generated") for index in away["setpieces"]["role_priorities"]["8"]
    )


def test_apply_roster_both_replaces_generated_placeholders(env, tmp_path: Path):
    service, _, drafts, _ = env
    save = imported(service, tmp_path)
    draft = created_placeholder_draft(drafts)

    result = service.apply_roster(draft["id"], save["save_id"], 7, "home", "both")

    assert result["applied"] == {"starters": 11, "substitutes": 12}
    home = drafts.get(draft["id"])["scenario"]["teams"][0]
    assert uids(home["players"]) == SAVED_UIDS
    assert all(not player.get("generated") for player in home["players"])
    assert home["lineup"] == list(range(STARTERS))


def test_import_save_write_failure_rolls_back_new_record(tmp_path: Path):
    data = save_data([managed_club(7, "阿森纳", "ARS"), managed_club(9, "切尔西", "CHE")])
    service, saves, _, _ = make_service(tmp_path, data)
    club_insert_trigger(saves.repository.database, 9)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="插入失败"):
            service.import_save(str(source_file(tmp_path)))
    finally:
        drop_club_insert_trigger(saves.repository.database)
    assert saves.list(limit=256)["items"] == []


def test_import_save_write_failure_keeps_existing_record_and_children(env, tmp_path: Path):
    service, saves, _, factory = env
    path = source_file(tmp_path)
    first = imported(service, tmp_path)
    saves.set_league(first["save_id"], "英超", {"clubs": [1]})
    before = saves.get(first["save_id"])
    before_clubs = saves.clubs(first["save_id"])
    factory.data["info"] = {**factory.data["info"], "build": "27.2.0"}
    factory.data["managed_clubs"] = [managed_club(7, "阿森纳", "ARS"), managed_club(9, "切尔西", "CHE")]
    club_insert_trigger(saves.repository.database, 9)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="插入失败"):
            service.import_save(str(path), replace=True)
    finally:
        drop_club_insert_trigger(saves.repository.database)
    assert saves.get(first["save_id"]) == before
    assert saves.clubs(first["save_id"]) == before_clubs
    assert [row["league_key"] for row in saves.leagues(first["save_id"])] == ["英超"]


def test_import_save_unreadable_source_is_rejected_without_writes(env, tmp_path: Path, monkeypatch):
    service, saves, _, factory = env
    path = source_file(tmp_path)

    def denied(self, *args, **kwargs):
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(ValueError, match="存档无法读取"):
        service.import_save(str(path))
    assert saves.list(limit=256)["items"] == []
    assert factory.paths == []


def test_import_save_missing_reader_dependency_is_rejected_without_writes(env, tmp_path: Path):
    _, saves, drafts, _ = env

    class MissingDependencyReader:
        def read_info(self):
            raise RuntimeError("未安装存档读取依赖 fmsave")

    service = SaveImportService(saves, drafts, lambda _path: MissingDependencyReader())
    with pytest.raises(ValueError, match="存档无法读取"):
        service.import_save(str(source_file(tmp_path)))
    assert saves.list(limit=256)["items"] == []


def test_import_save_reader_failure_midway_is_rejected_without_writes(env, tmp_path: Path):
    _, saves, drafts, _ = env

    class MissingDependencyReader(FakeReader):
        def read_squad(self, club_uid: int) -> list[dict[str, Any]]:
            raise RuntimeError("未安装存档读取依赖 fmsave")

    service = SaveImportService(
        saves,
        drafts,
        lambda _path: MissingDependencyReader(copy.deepcopy(save_data())),
    )
    with pytest.raises(ValueError, match="存档无法读取"):
        service.import_save(str(source_file(tmp_path)))
    assert saves.list(limit=256)["items"] == []


def test_import_save_replace_preserves_existing_leagues(env, tmp_path: Path):
    service, saves, _, factory = env
    path = source_file(tmp_path)
    first = imported(service, tmp_path)
    saves.set_league(first["save_id"], "英超", {"clubs": [1, 2]})
    factory.data["info"] = {**factory.data["info"], "build": "27.2.0"}

    second = service.import_save(str(path), replace=True)

    assert second["save_id"] == first["save_id"]
    assert saves.get(first["save_id"])["metadata"]["build"] == "27.2.0"
    assert [row["league_key"] for row in saves.leagues(first["save_id"])] == ["英超"]
    assert saves.leagues(first["save_id"])[0]["payload"] == {"clubs": [1, 2]}


def test_import_save_indexes_club_identity_by_uid_only(tmp_path: Path):
    data = save_data()
    data["clubs"] = [{"uid": 700, "unique_id": 7, "name": "Arsenal", "short_name": "Ars", "nation_id": 1}]
    service, saves, _, _ = make_service(tmp_path, data)

    result = service.import_save(str(source_file(tmp_path)))

    payload = saves.clubs(result["save_id"])[0]["payload"]
    assert payload["name"] is None
    assert payload["club_name"] == "阿森纳"
    assert service.get_squad(result["save_id"], 7)["club_name"] == "阿森纳"


def test_import_save_keeps_identity_name_when_club_uid_matches(tmp_path: Path):
    data = save_data()
    data["clubs"] = [{"uid": 7, "unique_id": 700, "name": "Arsenal", "short_name": "Ars", "nation_id": 1}]
    service, saves, _, _ = make_service(tmp_path, data)

    result = service.import_save(str(source_file(tmp_path)))

    payload = saves.clubs(result["save_id"])[0]["payload"]
    assert payload["name"] == "Arsenal"
    assert payload["short_name"] == "Ars"
    assert payload["nation_id"] == 1
