from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.saves import SavesRepository
from fm27lab.application.saves import SavesService


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def service(tmp_path: Path) -> SavesService:
    return SavesService(SavesRepository(database(tmp_path)))


def sha(index: int) -> str:
    return hashlib.sha256(str(index).encode("utf-8")).hexdigest()


def create_save(target: SavesService, index: int = 1, **extra) -> dict:
    return target.create(f"/saves/season-{index}.fm", sha(index), **extra)


def test_transitions_contract():
    assert SavesService.TRANSITIONS == {
        "pending": {"reading", "error", "cancelled"},
        "reading": {"ready", "error", "cancelled"},
        "ready": set(),
        "error": set(),
        "cancelled": set(),
    }


def test_create_defaults_and_get_round_trip(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves)
    assert created["id"]
    assert created["source_path"] == "/saves/season-1.fm"
    assert created["source_sha256"] == sha(1)
    assert created["status"] == "pending"
    assert created["stage"] is None
    assert created["metadata"] == {}
    for field in ("created_at", "updated_at"):
        assert created[field].endswith("+00:00"), "缺省时间必须带 UTC 后缀"
        datetime.fromisoformat(created[field])
    assert saves.get(created["id"]) == created
    assert saves.get("missing") is None


def test_create_accepts_explicit_fields(tmp_path: Path):
    saves = service(tmp_path)
    created = saves.create(
        "/saves/season-1.fm",
        sha(1),
        status="ready",
        stage="league",
        metadata={"联赛": "英超"},
    )
    assert created["status"] == "ready"
    assert created["stage"] == "league"
    assert created["metadata"] == {"联赛": "英超"}
    assert saves.get(created["id"]) == created


def test_create_propagates_repository_validation(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves)
    with pytest.raises(ValueError, match="存档内容重复"):
        saves.create("/saves/season-2.fm", created["source_sha256"])
    assert saves.repository.count() == 1
    for kwargs in (
        {"source_path": "", "source_sha256": sha(2)},
        {"source_path": "/saves/other.fm", "source_sha256": "bad"},
        {"source_path": "/saves/other.fm", "source_sha256": sha(3), "status": "unknown"},
        {"source_path": "/saves/other.fm", "source_sha256": sha(4), "stage": ""},
        {"source_path": "/saves/other.fm", "source_sha256": sha(5), "metadata": []},
    ):
        with pytest.raises(ValueError):
            saves.create(**kwargs)
    assert saves.list(limit=256)["total"] == 1


def test_list_envelope_and_pagination(tmp_path: Path):
    saves = service(tmp_path)
    first = create_save(saves, 1)
    second = create_save(saves, 2)
    third = create_save(saves, 3)
    listed = saves.list()
    assert set(listed) == {"items", "total", "next_offset"}
    assert [item["id"] for item in listed["items"]] == [third["id"], second["id"], first["id"]]
    assert listed["total"] == 3
    assert listed["next_offset"] is None
    page = saves.list(limit=2)
    assert [item["id"] for item in page["items"]] == [third["id"], second["id"]]
    assert page["total"] == 3
    assert page["next_offset"] == 2
    tail = saves.list(limit=2, offset=2)
    assert [item["id"] for item in tail["items"]] == [first["id"]]
    assert tail["total"] == 3
    assert tail["next_offset"] is None
    beyond = saves.list(offset=10)
    assert beyond == {"items": [], "total": 3, "next_offset": None}
    assert saves.list(limit=256, offset=0)["total"] == 3


def test_list_filters_by_status_and_validates_arguments(tmp_path: Path):
    saves = service(tmp_path)
    first = create_save(saves, 1, status="pending")
    second = create_save(saves, 2, status="ready")
    third = create_save(saves, 3, status="ready")
    ready = saves.list(status="ready")
    assert [item["id"] for item in ready["items"]] == [third["id"], second["id"]]
    assert ready["total"] == 2
    assert ready["next_offset"] is None
    assert ready["total"] == saves.repository.count(status="ready")
    assert [item["id"] for item in saves.list(status="pending")["items"]] == [first["id"]]
    assert saves.list(status="cancelled") == {"items": [], "total": 0, "next_offset": None}
    assert saves.repository.count() == saves.list(limit=256)["total"] == 3
    with pytest.raises(ValueError, match="状态"):
        saves.list(status="unknown")
    for limit in (0, 257, True, 1.0, "5"):
        with pytest.raises(ValueError, match="limit"):
            saves.list(limit=limit)
    for offset in (-1, True, 1.5, "0"):
        with pytest.raises(ValueError, match="offset"):
            saves.list(offset=offset)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("pending", "reading"),
        ("pending", "error"),
        ("pending", "cancelled"),
        ("reading", "ready"),
        ("reading", "error"),
        ("reading", "cancelled"),
    ],
)
def test_legal_transitions_apply_status_and_optional_fields(tmp_path: Path, source: str, target: str):
    saves = service(tmp_path)
    created = create_save(saves, 1, status=source)
    before = saves.get(created["id"])
    updated = saves.update(
        created["id"],
        {"status": target, "stage": "leagues", "metadata": {"联赛": "英超"}},
    )
    assert updated is not None
    assert updated["status"] == target
    assert updated["stage"] == "leagues"
    assert updated["metadata"] == {"联赛": "英超"}
    assert updated["source_path"] == before["source_path"]
    assert updated["created_at"] == before["created_at"]
    assert updated["updated_at"] != before["updated_at"], "更新必须刷新更新时间"
    datetime.fromisoformat(updated["updated_at"])
    assert saves.get(created["id"]) == updated


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("pending", "pending"),
        ("pending", "ready"),
        ("reading", "pending"),
        ("reading", "reading"),
        ("ready", "pending"),
        ("ready", "reading"),
        ("ready", "ready"),
        ("ready", "error"),
        ("ready", "cancelled"),
        ("error", "pending"),
        ("error", "reading"),
        ("error", "ready"),
        ("error", "error"),
        ("error", "cancelled"),
        ("cancelled", "pending"),
        ("cancelled", "reading"),
        ("cancelled", "ready"),
        ("cancelled", "error"),
        ("cancelled", "cancelled"),
    ],
)
def test_illegal_transitions_are_rejected_without_changes(tmp_path: Path, source: str, target: str):
    saves = service(tmp_path)
    created = create_save(saves, 1, status=source)
    before = saves.get(created["id"])
    with pytest.raises(ValueError, match="存档状态不允许该操作"):
        saves.update(created["id"], {"status": target, "stage": "leagues", "metadata": {"v": 1}})
    assert saves.get(created["id"]) == before, "非法流转不得改变存档"


def test_invalid_status_values_are_rejected_without_changes(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves, 1)
    before = saves.get(created["id"])
    for status in ("ready", [], {}, None, 5, True):
        with pytest.raises(ValueError, match="存档状态不允许该操作"):
            saves.update(created["id"], {"status": status})
        assert saves.get(created["id"]) == before
    assert saves.get(created["id"])["status"] == "pending"


def test_update_stage_and_metadata_without_status(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves, 1, stage="old", metadata={"a": 1})
    save_id = created["id"]
    updated = saves.update(save_id, {"stage": "leagues"})
    assert updated["status"] == "pending"
    assert updated["stage"] == "leagues"
    assert updated["metadata"] == {"a": 1}
    updated = saves.update(save_id, {"metadata": {"b": 2}})
    assert updated["stage"] == "leagues"
    assert updated["metadata"] == {"b": 2}
    updated = saves.update(save_id, {"stage": None})
    assert updated["stage"] is None
    assert saves.get(save_id) == updated


def test_update_rejects_invalid_changes_without_writes(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves, 1)
    before = saves.get(created["id"])
    for changes in ({}, None, "status", {"source_path": "/other.fm"}, {"created_at": "2026-01-01"}):
        with pytest.raises(ValueError, match="存档更新字段无效"):
            saves.update(created["id"], changes)
    assert saves.get(created["id"]) == before
    for changes in (
        {"status": "unknown"},
        {"stage": ""},
        {"stage": 5},
        {"metadata": None},
        {"metadata": []},
        {"metadata": {"bad": float("nan")}},
    ):
        with pytest.raises(ValueError):
            saves.update(created["id"], changes)
    assert saves.get(created["id"]) == before, "非法更新不得改变存档"
    with pytest.raises(ValueError):
        saves.update(created["id"], {"status": "reading", "stage": ""})
    assert saves.get(created["id"]) == before, "字段校验失败时状态流转不得落库"


def test_update_missing_save_returns_none(tmp_path: Path):
    saves = service(tmp_path)
    assert saves.update("missing", {"status": "reading"}) is None
    assert saves.update("missing", {"stage": "leagues"}) is None
    assert saves.update("missing", {"metadata": {"a": 1}}) is None
    with pytest.raises(ValueError, match="存档更新字段无效"):
        saves.update("missing", {"source_path": "/other.fm"})


def test_sequential_updates_read_latest_state(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves, 1)
    saves.update(created["id"], {"status": "reading"})
    saves.update(created["id"], {"status": "ready"})
    assert saves.get(created["id"])["status"] == "ready"
    with pytest.raises(ValueError, match="存档状态不允许该操作"):
        saves.update(created["id"], {"status": "reading"})
    assert saves.get(created["id"])["status"] == "ready"


def test_delete_cascades_children(tmp_path: Path):
    db = database(tmp_path)
    saves = SavesService(SavesRepository(db))
    created = create_save(saves)
    saves.set_league(created["id"], "英超", {"clubs": [1]})
    saves.set_club(created["id"], 7, {"name": "阿森纳"})
    assert saves.delete(created["id"]) is True
    assert saves.get(created["id"]) is None
    assert saves.leagues(created["id"]) == []
    assert saves.clubs(created["id"]) == []
    assert saves.delete(created["id"]) is False
    with closing(db.connect()) as connection:
        leagues = connection.execute("SELECT COUNT(*) FROM save_leagues").fetchone()[0]
        clubs = connection.execute("SELECT COUNT(*) FROM save_clubs").fetchone()[0]
    assert leagues == 0, "删除存档必须级联删除联赛"
    assert clubs == 0, "删除存档必须级联删除俱乐部"


def test_child_operations_delegate_to_repository(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves)
    save_id = created["id"]
    assert saves.set_league(save_id, "z-league", {"clubs": [1]}) == {
        "save_id": save_id,
        "league_key": "z-league",
        "payload": {"clubs": [1]},
    }
    saves.set_league(save_id, "a-league", {"clubs": [2]})
    assert [row["league_key"] for row in saves.leagues(save_id)] == ["a-league", "z-league"]
    assert saves.set_club(save_id, 10, {"name": "甲"}) == {
        "save_id": save_id,
        "club_uid": 10,
        "payload": {"name": "甲"},
    }
    saves.set_club(save_id, 2, {"name": "乙"})
    assert [row["club_uid"] for row in saves.clubs(save_id)] == [2, 10]
    assert saves.remove_league(save_id, "a-league") is True
    assert saves.remove_league(save_id, "a-league") is False
    assert [row["league_key"] for row in saves.leagues(save_id)] == ["z-league"]


def test_child_operations_preserve_repository_errors(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves)
    with pytest.raises(ValueError, match="存档不存在"):
        saves.set_league("missing", "英超", {})
    with pytest.raises(ValueError, match="存档不存在"):
        saves.set_club("missing", 7, {})
    with pytest.raises(ValueError):
        saves.set_league(created["id"], "", {})
    with pytest.raises(ValueError):
        saves.set_league(created["id"], "英超", [])
    with pytest.raises(ValueError):
        saves.set_club(created["id"], 0, {})
    with pytest.raises(ValueError):
        saves.set_club(created["id"], 7, [])
    assert saves.leagues(created["id"]) == []
    assert saves.clubs(created["id"]) == []


def test_invalid_identifiers_propagate_repository_errors(tmp_path: Path):
    saves = service(tmp_path)
    for save_id in ("", "a/b", "x" * 65, "存档", None, 5):
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.get(save_id)
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.delete(save_id)
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.update(save_id, {"stage": "leagues"})
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.leagues(save_id)
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.clubs(save_id)
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.set_league(save_id, "英超", {})
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.set_club(save_id, 7, {})
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.remove_league(save_id, "英超")
        with pytest.raises(ValueError, match="存档标识无效"):
            saves.import_payload(save_id, {}, {}, stage="leagues")


def test_import_payload_replaces_children_and_marks_ready(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves, 1, status="reading", stage="old", metadata={"来源": "手动"})
    save_id = created["id"]
    saves.set_league(save_id, "old", {"v": 1})
    saves.set_club(save_id, 7, {"v": 1})
    result = saves.import_payload(
        save_id,
        {"premier": {"clubs": [1, 2]}, "la-liga": {"clubs": [3]}},
        {10: {"name": "甲"}, 2: {"name": "乙"}},
        stage="leagues",
    )
    assert result["id"] == save_id
    assert result["status"] == "ready"
    assert result["stage"] == "leagues"
    assert result["metadata"] == {"来源": "手动"}
    assert result["source_path"] == created["source_path"]
    assert saves.get(save_id) == result
    assert [row["league_key"] for row in saves.leagues(save_id)] == ["la-liga", "premier"]
    assert saves.leagues(save_id)[1]["payload"] == {"clubs": [1, 2]}
    assert [row["club_uid"] for row in saves.clubs(save_id)] == [2, 10]
    assert saves.repository.count() == 1
    cleared = saves.import_payload(save_id, {}, {})
    assert cleared["status"] == "ready"
    assert cleared["stage"] is None
    assert saves.leagues(save_id) == []
    assert saves.clubs(save_id) == []


def test_import_payload_requires_existing_save(tmp_path: Path):
    saves = service(tmp_path)
    with pytest.raises(ValueError, match="存档不存在"):
        saves.import_payload("missing", {"premier": {}}, {1: {}})
    assert saves.list(limit=256) == {"items": [], "total": 0, "next_offset": None}


def test_import_payload_rolls_back_on_invalid_children(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves, 1, status="reading", stage="old", metadata={"a": 1})
    save_id = created["id"]
    saves.set_league(save_id, "keep", {"v": 1})
    saves.set_club(save_id, 7, {"v": 1})
    before = saves.get(save_id)
    for leagues, clubs in (
        ({"premier": {"v": 1}, "": {}}, {}),
        ({"premier": {"bad": float("nan")}}, {}),
        ({}, {1: {"v": 1}, 2: []}),
        ({}, {0: {}}),
        ([], {}),
        ({}, []),
    ):
        with pytest.raises(ValueError):
            saves.import_payload(save_id, leagues, clubs, stage="leagues")
        assert saves.get(save_id) == before, "导入失败后原状态必须保留"
        assert [row["league_key"] for row in saves.leagues(save_id)] == ["keep"], "导入失败后旧联赛必须保留"
        assert [row["club_uid"] for row in saves.clubs(save_id)] == [7], "导入失败后旧俱乐部必须保留"


def test_import_payload_rolls_back_when_stage_update_fails(tmp_path: Path):
    saves = service(tmp_path)
    created = create_save(saves, 1, status="reading", stage="old")
    save_id = created["id"]
    saves.set_league(save_id, "keep", {"v": 1})
    saves.set_club(save_id, 7, {"v": 1})
    before = saves.get(save_id)
    with pytest.raises(ValueError, match="存档阶段无效"):
        saves.import_payload(save_id, {"new": {"v": 2}}, {2: {"v": 2}}, stage="")
    assert saves.get(save_id) == before, "阶段写入失败后原状态必须保留"
    assert [row["league_key"] for row in saves.leagues(save_id)] == ["keep"], "阶段写入失败后旧联赛必须保留"
    assert [row["club_uid"] for row in saves.clubs(save_id)] == [7], "阶段写入失败后旧俱乐部必须保留"


def test_import_payload_rolls_back_on_write_failure(tmp_path: Path):
    db = database(tmp_path)
    saves = SavesService(SavesRepository(db))
    created = create_save(saves, 1, status="reading")
    save_id = created["id"]
    saves.set_league(save_id, "keep", {"v": 1})
    saves.set_club(save_id, 7, {"v": 1})
    before = saves.get(save_id)
    with closing(db.connect()) as connection:
        connection.execute(
            "CREATE TRIGGER fail_save_club_insert BEFORE INSERT ON save_clubs "
            "WHEN NEW.club_uid = 13 BEGIN SELECT RAISE(ABORT, '插入失败'); END"
        )
    try:
        with pytest.raises(sqlite3.IntegrityError, match="插入失败"):
            saves.import_payload(
                save_id,
                {"new": {"v": 2}},
                {2: {"v": 2}, 13: {"v": 3}},
                stage="leagues",
            )
    finally:
        with closing(db.connect()) as connection:
            connection.execute("DROP TRIGGER IF EXISTS fail_save_club_insert")
    assert saves.get(save_id) == before, "写入失败后原状态必须保留"
    assert [row["league_key"] for row in saves.leagues(save_id)] == ["keep"], "写入失败后旧联赛必须保留"
    assert [row["club_uid"] for row in saves.clubs(save_id)] == [7], "写入失败后旧俱乐部必须保留"
