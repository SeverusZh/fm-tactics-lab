from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.saves import SavesRepository

STATUSES = frozenset({"pending", "reading", "ready", "error", "cancelled"})


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def sha(index: int) -> str:
    return hashlib.sha256(str(index).encode("utf-8")).hexdigest()


def save(index: int = 1, **extra):
    value = {
        "id": f"save-{index}",
        "source_path": f"/saves/season-{index}.fm",
        "source_sha256": sha(index),
    }
    value.update(extra)
    return value


def assert_iso(stamp) -> None:
    assert isinstance(stamp, str), "时间戳必须是字符串"
    datetime.fromisoformat(stamp)


def test_save_repository_round_trip_with_defaults(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    created = repo.add(save())
    assert set(created) == {
        "id",
        "source_path",
        "source_sha256",
        "status",
        "stage",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert created["id"] == "save-1"
    assert created["source_path"] == "/saves/season-1.fm"
    assert created["source_sha256"] == sha(1)
    assert created["status"] == "pending"
    assert created["stage"] is None
    assert created["metadata"] == {}
    assert_iso(created["created_at"])
    assert_iso(created["updated_at"])
    assert repo.get("save-1") == created
    assert repo.list() == [created]
    assert repo.list(status="pending") == [created]
    assert SavesRepository.SAVE_STATUSES == STATUSES


def test_save_repository_generates_id_and_lowercases_sha(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    value = save()
    del value["id"]
    value["source_sha256"] = sha(1).upper()
    created = repo.add(value)
    assert re.fullmatch(r"[0-9a-f]{16}", created["id"]), "自动标识必须是 token_hex(8) 的 16 位小写十六进制"
    assert created["source_sha256"] == sha(1), "哈希必须统一小写存储"
    assert repo.get(created["id"])["source_sha256"] == sha(1)


def test_save_repository_accepts_explicit_fields_and_timestamps(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    created = repo.add(
        save(
            1,
            status="ready",
            stage="league",
            metadata={"联赛": "英超", "nested": [1, True, None]},
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-02T00:00:00+00:00",
        )
    )
    assert created["status"] == "ready"
    assert created["stage"] == "league"
    assert created["metadata"] == {"联赛": "英超", "nested": [1, True, None]}
    assert created["created_at"] == "2026-01-01T00:00:00+00:00"
    assert created["updated_at"] == "2026-01-02T00:00:00+00:00"
    assert repo.get("save-1") == created
    second = repo.add(save(2, stage=None, metadata={}))
    assert second["stage"] is None
    assert second["metadata"] == {}
    assert_iso(second["created_at"])


def test_save_repository_accepts_every_status(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    for index, status in enumerate(sorted(STATUSES), start=1):
        created = repo.add(save(index, status=status))
        assert created["status"] == status


def test_save_repository_rejects_invalid_fields(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    invalid = (
        [],
        "save",
        save(1, id=""),
        save(1, id="a/b"),
        save(1, id="x" * 65),
        save(1, id="存档"),
        save(1, id=5),
        save(1, source_path=""),
        save(1, source_path="x" * 4097),
        save(1, source_path="/saves/\x00.fm"),
        save(1, source_path="/saves/\x80.fm"),
        save(1, source_path="/saves/\x9f.fm"),
        save(1, source_path="\ud800"),
        save(1, source_path=5),
        save(1, source_sha256="0" * 63),
        save(1, source_sha256="0" * 65),
        save(1, source_sha256="g" * 64),
        save(1, source_sha256=sha(1) + " "),
        save(1, source_sha256=5),
        save(1, status="unknown"),
        save(1, status=None),
        save(1, status=[]),
        save(1, stage=""),
        save(1, stage="s" * 201),
        save(1, stage="阶段\x01"),
        save(1, stage="阶段\x80"),
        save(1, stage=5),
        save(1, metadata=None),
        save(1, metadata=[]),
        save(1, metadata={"bad": float("nan")}),
        save(1, metadata={"bad": float("inf")}),
        save(1, metadata={"bad": {1, 2}}),
        save(1, metadata={"bad": "\ud800"}),
        save(1, created_at=""),
        save(1, created_at="not-a-date"),
        save(1, created_at=5),
        save(1, updated_at=""),
        save(1, updated_at="not-a-date"),
    )
    for value in invalid:
        with pytest.raises(ValueError):
            repo.add(value)
    assert repo.list() == [], "非法存档不得写入数据库"


def test_save_repository_rejects_duplicate_id_and_sha(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1))
    with pytest.raises(ValueError, match="存档已存在"):
        repo.add(save(1, source_sha256=sha(2)))
    assert repo.get("save-1")["source_sha256"] == sha(1)
    with pytest.raises(ValueError, match="存档内容重复"):
        repo.add(save(2, source_sha256=sha(1)))
    assert repo.get("save-2") is None


def test_save_repository_rejects_duplicate_sha_across_connections(tmp_path: Path):
    db = database(tmp_path)
    repo = SavesRepository(db)
    repo.add(save(1))
    with db.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM saves").fetchone()[0] == 1
        with pytest.raises(ValueError, match="存档内容重复"):
            repo.add(save(2, source_sha256=sha(1)), connection=connection)
    assert repo.get("save-2") is None


def test_save_repository_list_filters_sorts_and_paginates(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1, status="pending", created_at="2000-01-01T00:00:00+00:00"))
    repo.add(save(2, status="ready", created_at="2000-01-03T00:00:00+00:00"))
    repo.add(save(3, status="ready", created_at="2000-01-02T00:00:00+00:00"))
    assert [row["id"] for row in repo.list()] == ["save-2", "save-3", "save-1"]
    assert [row["id"] for row in repo.list(status="ready")] == ["save-2", "save-3"]
    assert repo.list(status="cancelled") == []
    assert [row["id"] for row in repo.list(limit=2)] == ["save-2", "save-3"]
    assert [row["id"] for row in repo.list(limit=2, offset=2)] == ["save-1"]
    assert repo.list(limit=256, offset=10) == []


def test_save_repository_list_uses_rowid_for_equal_timestamps(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    for index in (1, 2, 3):
        repo.add(save(index, created_at="2026-01-01T00:00:00+00:00"))
    assert [row["id"] for row in repo.list()] == ["save-3", "save-2", "save-1"]


def test_save_repository_list_validates_arguments(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    for kwargs in (
        {"status": "unknown"},
        {"status": []},
        {"status": 5},
        {"limit": 0},
        {"limit": 257},
        {"limit": True},
        {"limit": "5"},
        {"limit": 1.5},
        {"offset": -1},
        {"offset": 1.5},
        {"offset": True},
        {"offset": "0"},
    ):
        with pytest.raises(ValueError):
            repo.list(**kwargs)


def test_save_repository_update_refreshes_timestamp_and_restricts_fields(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1, created_at="2000-01-01T00:00:00+00:00", updated_at="2000-01-01T00:00:00+00:00"))
    updated = repo.update("save-1", {"status": "reading", "stage": "leagues", "metadata": {"联赛": 2}})
    assert updated is not None
    assert updated["status"] == "reading"
    assert updated["stage"] == "leagues"
    assert updated["metadata"] == {"联赛": 2}
    assert updated["created_at"] == "2000-01-01T00:00:00+00:00"
    assert updated["updated_at"] != "2000-01-01T00:00:00+00:00", "更新时间必须自动刷新"
    assert_iso(updated["updated_at"])
    assert updated["updated_at"].endswith("+00:00"), "刷新后的更新时间必须为 UTC"
    assert repo.get("save-1") == updated
    assert repo.update("missing", {"status": "ready"}) is None
    for changes in (
        {},
        None,
        "status",
        {"source_path": "/other.fm"},
        {"created_at": "2026-01-01T00:00:00+00:00"},
        {"status": "unknown"},
        {"stage": ""},
        {"stage": 5},
        {"metadata": None},
        {"metadata": []},
        {"metadata": {"bad": float("nan")}},
    ):
        with pytest.raises(ValueError):
            repo.update("save-1", changes)
    assert repo.get("save-1") == updated, "非法更新不得改变存档"


def test_save_repository_delete_cascades_children(tmp_path: Path):
    db = database(tmp_path)
    repo = SavesRepository(db)
    repo.add(save(1))
    repo.set_league("save-1", "英超", {"clubs": [1, 2]})
    repo.set_club("save-1", 7, {"name": "阿森纳"})
    assert repo.delete("save-1") is True
    assert repo.delete("save-1") is False
    assert repo.get("save-1") is None
    with closing(db.connect()) as connection:
        leagues = connection.execute("SELECT COUNT(*) FROM save_leagues").fetchone()[0]
        clubs = connection.execute("SELECT COUNT(*) FROM save_clubs").fetchone()[0]
    assert leagues == 0, "删除存档必须级联删除联赛"
    assert clubs == 0, "删除存档必须级联删除俱乐部"


def test_save_repository_league_upsert_and_order(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1))
    repo.add(save(2))
    created = repo.set_league("save-1", "z-league", {"clubs": [1]})
    assert created == {"save_id": "save-1", "league_key": "z-league", "payload": {"clubs": [1]}}
    repo.set_league("save-1", "a-league", {"clubs": [2]})
    repo.set_league("save-1", "z-league", {"clubs": [3, 4], "中文": "值"})
    repo.set_league("save-2", "a-league", {"clubs": [9]})
    rows = repo.leagues("save-1")
    assert [row["league_key"] for row in rows] == ["a-league", "z-league"]
    assert rows[1]["payload"] == {"clubs": [3, 4], "中文": "值"}
    assert len(rows) == 2, "同一联赛键必须覆盖而不是新增"
    assert [row["league_key"] for row in repo.leagues("save-2")] == ["a-league"]
    assert repo.remove_league("save-1", "a-league") is True
    assert repo.remove_league("save-1", "a-league") is False
    assert [row["league_key"] for row in repo.leagues("save-1")] == ["z-league"]


def test_save_repository_club_upsert_and_order(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1))
    created = repo.set_club("save-1", 10, {"name": "甲"})
    assert created == {"save_id": "save-1", "club_uid": 10, "payload": {"name": "甲"}}
    repo.set_club("save-1", 2, {"name": "乙"})
    repo.set_club("save-1", 10, {"name": "丙"})
    rows = repo.clubs("save-1")
    assert [row["club_uid"] for row in rows] == [2, 10]
    assert rows[1]["payload"] == {"name": "丙"}
    assert len(rows) == 2, "同一俱乐部必须覆盖而不是新增"


def test_save_repository_children_require_valid_input_and_existing_save(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1))
    for league_key in ("", "x" * 65, "a\x00b", "a\x80b", "a\x9fb", 5, None):
        with pytest.raises(ValueError):
            repo.set_league("save-1", league_key, {})
    for payload in ([], "x", {"bad": float("nan")}, {"bad": "\ud800"}):
        with pytest.raises(ValueError):
            repo.set_league("save-1", "英超", payload)
    for club_uid in (0, -1, True, "7", 7.0, None):
        with pytest.raises(ValueError):
            repo.set_club("save-1", club_uid, {})
    for payload in ([], "x", {"bad": {1, 2}}, {"bad": "\ud800"}):
        with pytest.raises(ValueError):
            repo.set_club("save-1", 7, payload)
    for league_key in ("", 5):
        with pytest.raises(ValueError):
            repo.remove_league("save-1", league_key)
    with pytest.raises(ValueError, match="存档不存在"):
        repo.set_league("missing", "英超", {})
    with pytest.raises(ValueError, match="存档不存在"):
        repo.set_club("missing", 7, {})
    with pytest.raises(ValueError, match="存档标识无效"):
        repo.leagues("a/b")
    assert repo.set_league("save-1", "英超", {})["payload"] == {}
    assert repo.set_club("save-1", 7, {})["payload"] == {}


def test_save_repository_replace_children_replaces_atomically(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1))
    repo.set_league("save-1", "old", {"x": 1})
    repo.set_club("save-1", 1, {"x": 1})
    result = repo.replace_children(
        "save-1",
        {"b": {"v": 2}, "a": {"v": 1}},
        {10: {"n": "甲"}, 2: {"n": "乙"}},
    )
    assert result == {"leagues": 2, "clubs": 2}
    rows = repo.leagues("save-1")
    assert [row["league_key"] for row in rows] == ["a", "b"]
    assert rows[0]["payload"] == {"v": 1}
    assert [row["club_uid"] for row in repo.clubs("save-1")] == [2, 10]
    assert repo.clubs("save-1")[1]["payload"] == {"n": "甲"}
    assert repo.replace_children("save-1", {}, {}) == {"leagues": 0, "clubs": 0}
    assert repo.leagues("save-1") == []
    assert repo.clubs("save-1") == []


def test_save_repository_replace_children_rolls_back_on_invalid_input(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1))
    repo.set_league("save-1", "keep", {"v": 1})
    repo.set_club("save-1", 7, {"v": 1})
    for leagues, clubs in (
        ({"ok": {"v": 1}, "bad": {"nan": float("nan")}}, {}),
        ({}, {1: {"v": 1}, 2: []}),
        ({}, {0: {}}),
        ({"": {}}, {}),
        ([], {}),
        ({}, []),
    ):
        with pytest.raises(ValueError):
            repo.replace_children("save-1", leagues, clubs)
        assert [row["league_key"] for row in repo.leagues("save-1")] == ["keep"], "失败后原联赛必须保留"
        assert [row["club_uid"] for row in repo.clubs("save-1")] == [7], "失败后原俱乐部必须保留"
    with pytest.raises(ValueError, match="存档不存在"):
        repo.replace_children("missing", {}, {})
    assert repo.replace_children("save-1", {"keep": {"v": 2}}, {7: {"v": 2}}) == {
        "leagues": 1,
        "clubs": 1,
    }


def test_save_repository_transaction_reads_own_writes_and_rolls_back(tmp_path: Path):
    db = database(tmp_path)
    repo = SavesRepository(db)
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            created = repo.add(save(1), connection=connection)
            assert repo.get("save-1", connection=connection) == created
            assert repo.list(connection=connection) == [created]
            repo.set_league("save-1", "英超", {"v": 1}, connection=connection)
            repo.set_club("save-1", 7, {"v": 1}, connection=connection)
            assert repo.leagues("save-1", connection=connection)[0]["payload"] == {"v": 1}
            assert repo.clubs("save-1", connection=connection)[0]["payload"] == {"v": 1}
            repo.replace_children("save-1", {"x": {"v": 2}}, {2: {"v": 2}}, connection=connection)
            assert [row["league_key"] for row in repo.leagues("save-1", connection=connection)] == ["x"]
            raise RuntimeError("rollback")
    assert repo.get("save-1") is None
    assert repo.list() == []
    repo.add(save(1))
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            updated = repo.update("save-1", {"status": "ready"}, connection=connection)
            assert updated is not None
            assert updated["status"] == "ready"
            assert repo.get("save-1", connection=connection)["status"] == "ready"
            raise RuntimeError("rollback")
    assert repo.get("save-1")["status"] == "pending"
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.replace_children("save-1", {"x": {}}, {2: {}}, connection=connection)
            raise RuntimeError("rollback")
    assert repo.leagues("save-1") == []
    assert repo.clubs("save-1") == []
    with db.transaction() as connection:
        created = repo.add(save(2), connection=connection)
        repo.set_league("save-2", "英超", {"v": 3}, connection=connection)
        assert repo.get("save-2", connection=connection) == created
    assert repo.get("save-2") is not None
    assert repo.leagues("save-2")[0]["payload"] == {"v": 3}


def test_save_repository_rejects_invalid_identifiers(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    for save_id in ("", "a/b", "x" * 65, "存档", None, 5):
        with pytest.raises(ValueError, match="存档标识无效"):
            repo.get(save_id)
        with pytest.raises(ValueError, match="存档标识无效"):
            repo.delete(save_id)
        with pytest.raises(ValueError, match="存档标识无效"):
            repo.update(save_id, {"status": "ready"})
        with pytest.raises(ValueError, match="存档标识无效"):
            repo.leagues(save_id)
        with pytest.raises(ValueError, match="存档标识无效"):
            repo.clubs(save_id)
        with pytest.raises(ValueError, match="存档标识无效"):
            repo.set_league(save_id, "英超", {})
        with pytest.raises(ValueError, match="存档标识无效"):
            repo.set_club(save_id, 7, {})
        with pytest.raises(ValueError, match="存档标识无效"):
            repo.replace_children(save_id, {}, {})


def test_save_repository_field_boundaries(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    created = repo.add(
        save(
            1,
            id="x" * 64,
            source_path="/" + "a" * 4095,
            stage="s" * 200,
            metadata={"k": "值"},
        )
    )
    assert len(created["id"]) == 64
    assert len(created["source_path"]) == 4096
    assert len(created["stage"]) == 200
    assert repo.set_league(created["id"], "l" * 64, {"k": "值"})["league_key"] == "l" * 64
    assert repo.set_club(created["id"], 1, {})["club_uid"] == 1


def test_save_repository_normalizes_external_timestamps_to_utc(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    created = repo.add(
        save(
            1,
            created_at="2026-01-01T05:00:00+05:00",
            updated_at="2026-01-02T00:00:00-03:00",
        )
    )
    assert created["created_at"] == "2026-01-01T00:00:00+00:00", "异时区创建时间必须规范化为 UTC"
    assert created["updated_at"] == "2026-01-02T03:00:00+00:00", "异时区更新时间必须规范化为 UTC"
    assert repo.get("save-1") == created
    naive = repo.add(save(2, created_at="2026-01-01T08:00:00"))
    assert naive["created_at"] == "2026-01-01T08:00:00+00:00", "naive 时间必须按 UTC 解释"


def test_save_repository_default_timestamps_are_utc(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    created = repo.add(save(1))
    for field in ("created_at", "updated_at"):
        assert created[field].endswith("+00:00"), "缺省时间必须带 UTC 后缀"
        assert datetime.fromisoformat(created[field]).utcoffset() == timedelta(0), "缺省时间必须为 UTC"


def test_save_repository_list_orders_normalized_timestamps_chronologically(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    repo.add(save(1, created_at="2026-01-01T05:00:00+05:00"))
    repo.add(save(2, created_at="2026-01-01T01:00:00+00:00"))
    repo.add(save(3, created_at="2025-12-31T23:30:00-02:00"))
    assert [row["id"] for row in repo.list()] == ["save-3", "save-2", "save-1"]
    assert repo.get("save-1")["created_at"] == "2026-01-01T00:00:00+00:00"


def test_save_repository_metadata_round_trip_coerces_non_string_keys(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    created = repo.add(save(1, metadata={1: "值"}))
    assert created["metadata"] == {"1": "值"}, "JSON 序列化会把非字符串键转为字符串"
    assert repo.get("save-1") == created


def test_save_repository_replace_children_rolls_back_after_partial_insert(tmp_path: Path):
    db = database(tmp_path)
    repo = SavesRepository(db)
    repo.add(save(1))
    repo.set_league("save-1", "keep", {"v": 1})
    repo.set_club("save-1", 7, {"v": 1})
    with closing(db.connect()) as connection:
        connection.execute(
            "CREATE TRIGGER fail_save_club_insert BEFORE INSERT ON save_clubs "
            "WHEN NEW.club_uid = 13 BEGIN SELECT RAISE(ABORT, '插入失败'); END"
        )
    try:
        with pytest.raises(sqlite3.IntegrityError, match="插入失败"):
            repo.replace_children(
                "save-1",
                {"new": {"v": 2}},
                {2: {"v": 2}, 13: {"v": 3}, 14: {"v": 4}},
            )
    finally:
        with closing(db.connect()) as connection:
            connection.execute("DROP TRIGGER IF EXISTS fail_save_club_insert")
    assert [row["league_key"] for row in repo.leagues("save-1")] == ["keep"], "部分插入失败后旧联赛必须保留"
    assert [row["club_uid"] for row in repo.clubs("save-1")] == [7], "部分插入失败后旧俱乐部必须保留"
    assert repo.replace_children("save-1", {"new": {"v": 2}}, {2: {"v": 2}, 13: {"v": 3}}) == {
        "leagues": 1,
        "clubs": 2,
    }


def test_save_repository_count_matches_list_and_filters(tmp_path: Path):
    repo = SavesRepository(database(tmp_path))
    assert repo.count() == 0
    repo.add(save(1, status="pending"))
    repo.add(save(2, status="ready"))
    repo.add(save(3, status="ready"))
    assert repo.count() == 3
    assert repo.count() == len(repo.list(limit=256))
    assert repo.count(status="pending") == 1
    assert repo.count(status="ready") == 2
    assert repo.count(status="cancelled") == 0
    for kwargs in ({"status": "unknown"}, {"status": []}, {"status": 5}, {"status": True}):
        with pytest.raises(ValueError, match="存档状态无效"):
            repo.count(**kwargs)


def test_save_repository_count_reads_own_transaction_writes(tmp_path: Path):
    db = database(tmp_path)
    repo = SavesRepository(db)
    repo.add(save(1))
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.add(save(2), connection=connection)
            repo.update("save-1", {"status": "ready"}, connection=connection)
            assert repo.count(connection=connection) == 2
            assert repo.count(status="pending", connection=connection) == 1
            assert repo.count(status="ready", connection=connection) == 1
            raise RuntimeError("rollback")
    assert repo.count() == 1
    assert repo.count(status="ready") == 0
