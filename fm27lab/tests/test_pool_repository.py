from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import PoolRepository


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def entry(name="Corner", weight=2):
    return {
        "name": name,
        "weight": weight,
        "tactic": {"tactic_name": "角球", "mentality": 3, "phases": []},
        "roster": {"club_uid": 7, "players": [{"source_uid": 1}]},
    }


def test_pool_repository_round_trip(tmp_path: Path):
    repo = PoolRepository(database(tmp_path))
    created = repo.add(entry())
    assert created["id"]
    assert created["name"] == "Corner"
    assert created["weight"] == 2
    assert created["tactic"]["tactic_name"] == "角球"
    assert created["roster"]["club_uid"] == 7
    assert repo.get(created["id"]) == created
    listed = repo.list()
    assert listed == [created]


def test_pool_repository_rejects_invalid_entries(tmp_path: Path):
    repo = PoolRepository(database(tmp_path))
    for value in (
        {},
        {"name": "", "weight": 1, "tactic": {}},
        {"name": "x", "weight": 0, "tactic": {}},
        {"name": "x", "weight": 1001, "tactic": {}},
        {"name": "x", "weight": True, "tactic": {}},
        {"name": "x", "weight": 1, "tactic": []},
        {"name": "x", "weight": 1, "tactic": {}, "roster": []},
        {"name": "x", "weight": 1, "tactic": {}, "id": ""},
    ):
        with pytest.raises(ValueError):
            repo.add(value)


def test_pool_repository_delete_and_missing(tmp_path: Path):
    repo = PoolRepository(database(tmp_path))
    created = repo.add(entry())
    assert repo.get("missing") is None
    assert repo.delete(created["id"]) is True
    assert repo.delete(created["id"]) is False
    assert repo.list() == []


def test_pool_repository_supports_transaction_connection(tmp_path: Path):
    db = database(tmp_path)
    repo = PoolRepository(db)
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.add(entry("rollback"), connection=connection)
            raise RuntimeError("rollback")
    assert repo.list() == []
    with closing(db.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pool_entries").fetchone()[0] == 0


def test_pool_repository_duplicate_explicit_id_is_rejected(tmp_path: Path):
    repo = PoolRepository(database(tmp_path))
    repo.add({**entry(), "id": "fixed"})
    with pytest.raises(sqlite3.IntegrityError):
        repo.add({**entry("Other"), "id": "fixed"})


def test_pool_repository_list_is_stable_and_unicode_safe(tmp_path: Path):
    repo = PoolRepository(database(tmp_path))
    first = repo.add(entry("甲"), created_at="2026-01-01T00:00:00+00:00")
    second = repo.add(entry("乙"), created_at="2026-01-02T00:00:00+00:00")
    assert [row["id"] for row in repo.list()] == [first["id"], second["id"]]


def test_transaction_reads_own_writes_and_deletes(tmp_path):
    db = database(tmp_path)
    repo = PoolRepository(db)
    with db.transaction() as connection:
        created = repo.add(entry("inside"), connection=connection)
        assert repo.get(created["id"], connection=connection) == created
        assert repo.list(connection=connection) == [created]
        assert repo.delete(created["id"], connection=connection) is True
        assert repo.list(connection=connection) == []


def test_serialization_failures_and_created_at_are_value_errors(tmp_path):
    repo = PoolRepository(database(tmp_path))
    for tactic in ({"x": float("nan")}, {"x": float("inf")}, {"x": {1, 2}}):
        with pytest.raises(ValueError, match="JSON"):
            repo.add({"name": "x", "weight": 1, "tactic": tactic})
    with pytest.raises(ValueError, match="时间"):
        repo.add(entry(), created_at="")
    with pytest.raises(ValueError, match="时间"):
        repo.add(entry(), created_at="not-a-date")
    with pytest.raises(ValueError, match="JSON"):
        repo.add({"name": "x", "weight": 1, "tactic": {"x": "\ud800"}})
    with pytest.raises(ValueError, match="名称"):
        repo.add({"name": "\ud800", "weight": 1, "tactic": {}})
    with pytest.raises(ValueError, match="标识"):
        repo.add({"name": "x", "weight": 1, "tactic": {}, "id": "\ud800"})
    for unsafe in ("a/b", "..", "a%2Fb", " ", "a.b"):
        with pytest.raises(ValueError, match="标识"):
            repo.add({"name": "x", "weight": 1, "tactic": {}, "id": unsafe})


def test_pool_limit_is_atomic_under_concurrency(tmp_path):
    repo = PoolRepository(database(tmp_path))
    for index in range(127):
        repo.add(entry(f"base{index}"))
    barrier = threading.Barrier(8)

    def attempt(index):
        barrier.wait()
        try:
            repo.add(entry(f"race{index}"))
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count(True) == 1
    assert len(repo.list()) == 128


def test_pool_limit_is_enforced_inside_the_repository(tmp_path):
    repo = PoolRepository(database(tmp_path))
    for index in range(128):
        repo.add(entry(f"E{index}"))
    with pytest.raises(ValueError, match="128"):
        repo.add(entry("overflow"))


def test_same_timestamp_preserves_insertion_order_and_unicode(tmp_path):
    repo = PoolRepository(database(tmp_path))
    first = repo.add(entry("甲"), created_at="2026-01-01T00:00:00+00:00")
    second = repo.add(entry("乙"), created_at="2026-01-01T00:00:00+00:00")
    rows = repo.list()
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert [row["name"] for row in rows] == ["甲", "乙"]
