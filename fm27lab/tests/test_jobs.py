from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def job(**extra):
    value = {
        "id": "job1",
        "kind": "experiment",
        "status": "queued",
        "name": "Test",
        "config": {"seeds": [1, 2]},
        "workers": 2,
        "total": 4,
    }
    value.update(extra)
    return value


def run(sequence=1, **extra):
    value = {
        "sequence": sequence,
        "variant": "B",
        "seed": 11,
        "score_home": 2,
        "score_away": 1,
        "verified": True,
        "stats": {"shots": [10, 7]},
        "events": {"goals": []},
        "log_path": "run-1.jsonl",
    }
    value.update(extra)
    return value


def test_job_repository_create_get_list_update_delete(tmp_path: Path):
    repo = JobRepository(database(tmp_path))
    created = repo.add(job())
    assert created["id"] == "job1"
    assert created["config"] == {"seeds": [1, 2]}
    assert repo.get("job1") == created
    assert repo.list() == [created]
    updated = repo.update("job1", {"status": "running", "completed": 2})
    assert updated["status"] == "running"
    assert updated["completed"] == 2
    assert repo.get("job1") == updated
    assert repo.delete("job1") is True
    assert repo.get("job1") is None
    assert repo.delete("job1") is False


def test_job_repository_runs_are_ordered_and_cascade_deleted(tmp_path: Path):
    repo = JobRepository(database(tmp_path))
    repo.add(job())
    first = repo.add_run("job1", run(2))
    repo.add_run("job1", run(1, variant="A", seed=12))
    assert [item["sequence"] for item in repo.runs("job1")] == [1, 2]
    assert repo.runs("job1")[0]["variant"] == "A"
    assert [item["sequence"] for item in repo.runs("job1", limit=1, offset=1)] == [2]
    assert repo.get_run("job1", 2) == first
    assert repo.delete("job1") is True
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_run("job1", run(3))


def test_job_repository_validates_job_and_run_fields(tmp_path: Path):
    repo = JobRepository(database(tmp_path))
    for value in (
        {},
        job(status="unknown"),
        job(workers=0),
        job(total=-1),
        job(completed=5),
        job(config=[]),
        job(id="a/b"),
        job(name="\ud800"),
    ):
        with pytest.raises(ValueError):
            repo.add(value)
    repo.add(job())
    for value in (
        run(sequence=0),
        run(variant=""),
        run(seed=-1),
        run(verified="yes"),
        run(stats=[]),
        run(events=[]),
    ):
        with pytest.raises(ValueError):
            repo.add_run("job1", value)


def test_job_repository_json_and_transaction_contract(tmp_path: Path):
    db = database(tmp_path)
    repo = JobRepository(db)
    for value in ({"config": {"x": float("nan")}}, {"summary": {"x": {1, 2}}}):
        with pytest.raises(ValueError, match="JSON"):
            repo.add(job(**value))
    with db.transaction() as connection:
        created = repo.add(job(id="inside"), connection=connection)
        assert repo.get("inside", connection=connection) == created
        assert repo.list(connection=connection) == [created]
        repo.add_run("inside", run(1), connection=connection)
        assert repo.runs("inside", connection=connection)[0]["sequence"] == 1
    assert repo.get("inside") is not None
    repo.delete("inside")
    assert repo.get("inside") is None


def test_job_repository_status_filter_and_pagination(tmp_path: Path):
    repo = JobRepository(database(tmp_path))
    repo.add(job(id="a", status="queued", created_at="2000-01-01T00:00:00+00:00"))
    repo.add(job(id="b", status="running", created_at="2000-01-02T00:00:00+00:00"))
    repo.add(job(id="c", status="running", created_at="2000-01-03T00:00:00+00:00"))
    assert [item["id"] for item in repo.list(status="running")] == ["c", "b"]
    assert [item["id"] for item in repo.list(limit=2)] == ["c", "b"]
    assert [item["id"] for item in repo.list(limit=2, offset=2)] == ["a"]


def test_job_repository_rejects_false_timestamps_and_unhashable_status(tmp_path: Path):
    repo = JobRepository(database(tmp_path))
    for value in (job(created_at=""), job(created_at=0), job(status=[]), job(status={})):
        with pytest.raises(ValueError):
            repo.add(value)
    repo.add(job())
    for status in ([], {}):
        with pytest.raises(ValueError):
            repo.list(status=status)
    with pytest.raises(ValueError, match="比分"):
        repo.add_run("job1", run(score_home=3, score_away=None))


def test_job_repository_rollback_failed_update_and_duplicates(tmp_path: Path):
    db = database(tmp_path)
    repo = JobRepository(db)
    repo.add(job())
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.add(job(id="rollback"), connection=connection)
            raise RuntimeError("rollback")
    assert repo.get("rollback") is None
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.update("job1", {"status": "running"}, connection=connection)
            raise RuntimeError("rollback")
    assert repo.get("job1")["status"] == "queued"
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.add_run("job1", run(1), connection=connection)
            raise RuntimeError("rollback")
    assert repo.runs("job1") == []
    with pytest.raises(ValueError):
        repo.update("job1", {"completed": 9})
    assert repo.get("job1")["completed"] == 0
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(job())
    repo.add_run("job1", run(1))
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_run("job1", run(1))
    with pytest.raises(ValueError):
        repo.runs("job1", limit=0)
    with pytest.raises(ValueError):
        repo.runs("job1", limit=201)
