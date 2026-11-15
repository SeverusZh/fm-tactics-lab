from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import DraftRepository
from fm27lab.application.drafts import DraftService


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def player(uid):
    attributes = [10] * 69
    attributes[0 if uid == 100 else 7] = 18
    return {"source_uid": uid, "name": f"P{uid}", "attributes": attributes}


def team(count=26):
    return {
        "name": "Home",
        "players": [player(100 + index) for index in range(count)],
        "roster_size": count,
        "lineup": list(range(11)),
        "captains": [5],
        "takers": {"penalties": [6]},
        "setpieces": {"role_priorities": {"8": [8]}},
    }


def scenario(count=26):
    return {"schema": 4, "teams": [team(count), team(count)]}


def test_draft_repository_round_trip(tmp_path: Path):
    repo = DraftRepository(database(tmp_path))
    created = repo.add({"name": "Draft", "scenario": {"teams": []}, "source": {"kind": "inline"}})
    assert created["id"]
    assert repo.get(created["id"]) == created
    assert repo.list() == [created]
    updated = repo.update(created["id"], {"name": "Renamed", "scenario": {"teams": [1]}})
    assert updated["name"] == "Renamed"
    assert updated["scenario"] == {"teams": [1]}
    assert updated["source"] == {"kind": "inline"}
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] >= created["updated_at"]
    assert repo.get(created["id"]) == updated
    assert repo.list()[0] == updated
    assert repo.delete(created["id"]) is True
    assert repo.get(created["id"]) is None


def test_draft_repository_validates_and_rejects_duplicate_id(tmp_path: Path):
    repo = DraftRepository(database(tmp_path))
    for value in (
        {},
        {"name": "", "scenario": {}},
        {"name": "x", "scenario": []},
        {"name": "x", "scenario": {}, "source": []},
        {"name": "x", "scenario": {}, "id": "a/b"},
        {"name": "\ud800", "scenario": {}},
    ):
        with pytest.raises(ValueError):
            repo.add(value)
    repo.add({"name": "x", "scenario": {}, "id": "fixed"})
    with pytest.raises(sqlite3.IntegrityError):
        repo.add({"name": "y", "scenario": {}, "id": "fixed"})


def test_draft_repository_json_and_transaction_contract(tmp_path: Path):
    db = database(tmp_path)
    repo = DraftRepository(db)
    for value in ({"scenario": {"x": float("nan")}}, {"scenario": {"x": {1, 2}}}):
        with pytest.raises(ValueError, match="JSON"):
            repo.add({"name": "x", **value})
    with db.transaction() as connection:
        created = repo.add({"name": "inside", "scenario": {}}, connection=connection)
        assert repo.get(created["id"], connection=connection) == created
        assert repo.list(connection=connection) == [created]
        assert repo.update(created["id"], {"name": "inside2"}, connection=connection)["name"] == "inside2"
        assert repo.delete(created["id"], connection=connection) is True
    assert repo.list() == []


def test_draft_service_normalizes_scenario_and_exposes_summaries(tmp_path: Path):
    service = DraftService(DraftRepository(database(tmp_path)))
    created = service.create("Draft", scenario(26), {"kind": "inline"})
    assert len(created["scenario"]["teams"][0]["players"]) == 23
    assert created["scenario"]["teams"][0]["roster_size"] == 23
    assert created["scenario"]["teams"][0]["roster_trim"]["source_size"] == 26
    summaries = service.list()
    assert summaries["items"] == [
        {
            "id": created["id"],
            "name": "Draft",
            "source": {"kind": "inline"},
            "created_at": created["created_at"],
            "updated_at": created["updated_at"],
        }
    ]
    assert summaries["total"] == 1
    assert summaries["next_offset"] is None
    fetched = service.get(created["id"])
    assert fetched["scenario"]["teams"][0]["players"][0]["source_uid"] == 100


def test_draft_list_orders_by_updated_at_and_rolls_back(tmp_path: Path):
    db = database(tmp_path)
    repo = DraftRepository(db)
    first = repo.add({"name": "A", "scenario": {}, "created_at": "2000-01-01T00:00:00+00:00"})
    second = repo.add({"name": "B", "scenario": {}, "created_at": "2000-01-02T00:00:00+00:00"})
    assert [row["name"] for row in repo.list()] == ["B", "A"]
    repo.update(first["id"], {"name": "A2"})
    assert [row["name"] for row in repo.list()] == ["A2", "B"]
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.add({"name": "rollback", "scenario": {}}, connection=connection)
            raise RuntimeError("rollback")
    assert second["id"] in {row["id"] for row in repo.list()}
    assert "rollback" not in {row["name"] for row in repo.list()}


def test_draft_service_update_renormalizes_and_rejects_missing(tmp_path: Path):
    service = DraftService(DraftRepository(database(tmp_path)))
    created = service.create("Draft", scenario(26))
    updated = service.update(created["id"], scenario=scenario(20))
    assert len(updated["scenario"]["teams"][0]["players"]) == 23
    assert len(updated["scenario"]["teams"][0]["roster_trim"]["generated"]) == 3
    assert service.get(created["id"]) == updated
    assert service.update("missing", name="x") is None
    with pytest.raises(ValueError, match="来源"):
        service.create("Draft", scenario(23), source=[])
    with pytest.raises(ValueError, match="来源"):
        service.update(created["id"], source=[])
    with pytest.raises(ValueError, match="字段"):
        service.update(created["id"])
    with pytest.raises(ValueError, match="名称"):
        service.update(created["id"], name="\ud800")


def test_draft_service_pagination_and_update_delete_rollback(tmp_path: Path):
    db = database(tmp_path)
    service = DraftService(DraftRepository(db))
    ids = [service.create(f"D{index}", scenario(23))["id"] for index in range(3)]
    first = service.list(limit=2)
    assert len(first["items"]) == 2
    assert first["total"] == 3
    assert first["next_offset"] == 2
    last = service.list(limit=2, offset=2)
    assert len(last["items"]) == 1
    assert last["next_offset"] is None
    for limit in (0, 129, True, 1.0):
        with pytest.raises(ValueError, match="limit"):
            service.list(limit=limit)
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            DraftRepository(db).update(ids[0], {"name": "rollback"}, connection=connection)
            raise RuntimeError("rollback")
    assert service.get(ids[0])["name"] == "D0"
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            DraftRepository(db).delete(ids[1], connection=connection)
            raise RuntimeError("rollback")
    assert service.get(ids[1]) is not None
    assert service.delete(ids[2]) is True
    assert service.get(ids[2]) is None
