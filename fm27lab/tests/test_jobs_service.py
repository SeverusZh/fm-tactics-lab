from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.application.jobs import JobService


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def service(tmp_path: Path) -> JobService:
    return JobService(JobRepository(database(tmp_path)))


def run(**extra):
    value = {
        "variant": "B",
        "seed": 11,
        "score_home": 2,
        "score_away": 1,
        "verified": True,
        "stats": {"shots": [10, 7]},
    }
    value.update(extra)
    return value


def test_create_defaults_and_get_round_trip(tmp_path: Path):
    jobs = service(tmp_path)
    created = jobs.create("experiment")
    assert created["id"]
    assert created["kind"] == "experiment"
    assert created["status"] == "queued"
    assert created["name"] is None
    assert created["config"] == {}
    assert created["summary"] == {}
    assert created["workers"] == 1
    assert created["total"] == 0
    assert created["completed"] == 0
    assert created["started_at"] is None
    assert created["finished_at"] is None
    assert jobs.get(created["id"]) == created
    assert jobs.get("missing") is None
    with pytest.raises(sqlite3.IntegrityError):
        jobs.create("experiment", job_id=created["id"])
    for kwargs in (
        {"kind": ""},
        {"kind": "experiment", "workers": 0},
        {"kind": "experiment", "total": -1},
        {"kind": "experiment", "config": []},
        {"kind": "experiment", "job_id": "a/b"},
    ):
        with pytest.raises(ValueError):
            jobs.create(**kwargs)
    with pytest.raises(ValueError, match="JSON"):
        jobs.create("experiment", config={"x": float("nan")})


def test_create_accepts_explicit_values(tmp_path: Path):
    jobs = service(tmp_path)
    created = jobs.create(
        "experiment",
        name="First",
        config={"seeds": [1, 2]},
        workers=2,
        total=4,
        job_id="job1",
    )
    assert created["id"] == "job1"
    assert created["name"] == "First"
    assert created["config"] == {"seeds": [1, 2]}
    assert created["workers"] == 2
    assert created["total"] == 4


def test_list_envelope_and_pagination(tmp_path: Path):
    jobs = service(tmp_path)
    first = jobs.create("experiment")
    jobs.create("experiment", job_id="job1")
    jobs.create("experiment", job_id="job2")
    listed = jobs.list()
    assert set(listed) == {"items", "total", "next_offset"}
    assert [item["id"] for item in listed["items"]] == ["job2", "job1", first["id"]]
    assert listed["total"] == 3
    assert listed["next_offset"] is None
    page = jobs.list(limit=2)
    assert [item["id"] for item in page["items"]] == ["job2", "job1"]
    assert page["total"] == 3
    assert page["next_offset"] == 2
    tail = jobs.list(limit=2, offset=2)
    assert [item["id"] for item in tail["items"]] == [first["id"]]
    assert tail["total"] == 3
    assert tail["next_offset"] is None


def test_list_filters_by_status_and_validates_paging(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", job_id="q1")
    jobs.create("experiment", job_id="r1")
    jobs.create("experiment", job_id="r2")
    jobs.update("r1", {"status": "running"})
    jobs.update("r2", {"status": "running"})
    running = jobs.list(status="running")
    assert [item["id"] for item in running["items"]] == ["r2", "r1"]
    assert running["total"] == 2
    assert running["next_offset"] is None
    queued = jobs.list(status="queued", limit=10)
    assert [item["id"] for item in queued["items"]] == ["q1"]
    assert queued["total"] == 1
    assert jobs.list(status="completed") == {"items": [], "total": 0, "next_offset": None}
    for limit in (0, 257, True, 1.0):
        with pytest.raises(ValueError, match="limit"):
            jobs.list(limit=limit)
    for offset in (-1, True, 1.0):
        with pytest.raises(ValueError, match="offset"):
            jobs.list(offset=offset)
    with pytest.raises(ValueError, match="状态"):
        jobs.list(status="unknown")


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("queued", "running"),
        ("queued", "cancelled"),
        ("queued", "error"),
        ("running", "completed"),
        ("running", "error"),
        ("running", "cancelled"),
        ("running", "interrupted"),
        ("interrupted", "queued"),
        ("interrupted", "running"),
        ("interrupted", "cancelled"),
    ],
)
def test_legal_transitions_set_timestamps(tmp_path: Path, source: str, target: str):
    jobs = service(tmp_path)
    jobs.create("experiment", total=2, job_id="job1")
    if source in {"running", "interrupted"}:
        jobs.update("job1", {"status": "running"})
    if source == "interrupted":
        jobs.update("job1", {"status": "interrupted"})
    current = jobs.get("job1")
    assert current["status"] == source
    updated = jobs.update("job1", {"status": target})
    assert updated["status"] == target
    assert jobs.get("job1") == updated
    if target == "running":
        assert updated["started_at"] is not None
        datetime.fromisoformat(updated["started_at"])
    elif current["started_at"] is None:
        assert updated["started_at"] is None
    if target in {"completed", "error", "cancelled"}:
        assert updated["finished_at"] is not None
        datetime.fromisoformat(updated["finished_at"])
    else:
        assert updated["finished_at"] is None


def test_illegal_transitions_are_rejected_without_changes(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", total=2, job_id="job1")
    before = jobs.get("job1")
    for status in ("completed", "interrupted", "queued", "bogus", [], {}):
        with pytest.raises(ValueError, match="状态"):
            jobs.update("job1", {"status": status})
        assert jobs.get("job1") == before
    jobs.update("job1", {"status": "running"})
    before = jobs.get("job1")
    for status in ("queued", "running"):
        with pytest.raises(ValueError, match="状态"):
            jobs.update("job1", {"status": status})
        assert jobs.get("job1") == before
    jobs.create("experiment", job_id="job2")
    jobs.update("job2", {"status": "running"})
    jobs.update("job2", {"status": "completed"})
    before = jobs.get("job2")
    with pytest.raises(ValueError, match="状态"):
        jobs.update("job2", {"status": "running"})
    assert jobs.get("job2") == before


def test_update_name_summary_and_completed_bounds(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", name="Old", total=4, job_id="job1")
    updated = jobs.update("job1", {"name": "New", "summary": {"wins": 2}})
    assert updated["name"] == "New"
    assert updated["summary"] == {"wins": 2}
    assert updated["status"] == "queued"
    assert jobs.get("job1") == updated
    for completed in (5, -1, True, 1.0, "2"):
        with pytest.raises(ValueError, match="进度"):
            jobs.update("job1", {"completed": completed})
    assert jobs.get("job1")["completed"] == 0
    assert jobs.update("job1", {"completed": 4})["completed"] == 4
    after = jobs.get("job1")
    with pytest.raises(ValueError, match="JSON"):
        jobs.update("job1", {"summary": {"x": float("nan")}})
    assert jobs.get("job1") == after


def test_update_missing_job_and_invalid_changes(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", job_id="job1")
    assert jobs.update("missing", {"status": "running"}) is None
    for changes in (
        {},
        {"workers": 2},
        {"completed": 1, "config": {}},
        {"started_at": "2026-01-01T00:00:00+00:00"},
    ):
        with pytest.raises(ValueError, match="字段"):
            jobs.update("job1", changes)
    assert jobs.get("job1")["workers"] == 1


def test_cancel_transitions_and_missing(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", job_id="job1")
    cancelled = jobs.cancel("job1")
    assert cancelled["status"] == "cancelled"
    assert cancelled["finished_at"] is not None
    assert jobs.get("job1") == cancelled
    with pytest.raises(ValueError, match="状态"):
        jobs.cancel("job1")
    assert jobs.cancel("missing") is None


def test_append_run_increments_completed(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", total=2, job_id="job1")
    jobs.update("job1", {"status": "running"})
    first = jobs.append_run("job1", run())
    assert first["job_id"] == "job1"
    assert first["sequence"] == 1
    assert first["score"] == [2, 1]
    assert first["verified"] is True
    second = jobs.append_run("job1", run(variant="A", seed=12))
    assert second["sequence"] == 2
    job = jobs.get("job1")
    assert job["completed"] == 2
    assert job["started_at"] is not None
    assert job["finished_at"] is None
    assert jobs.runs("job1")["total"] == 2


def test_append_run_overflow_rolls_back_everything(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", total=1, job_id="job1")
    jobs.update("job1", {"status": "running"})
    jobs.append_run("job1", run())
    with pytest.raises(ValueError, match="进度"):
        jobs.append_run("job1", run(seed=12))
    assert jobs.get("job1")["completed"] == 1
    assert jobs.runs("job1")["total"] == 1
    jobs.create("experiment", total=0, job_id="job2")
    jobs.update("job2", {"status": "running"})
    with pytest.raises(ValueError, match="进度"):
        jobs.append_run("job2", run())
    assert jobs.get("job2")["completed"] == 0
    assert jobs.runs("job2")["total"] == 0


def test_append_run_requires_running_job(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", total=2, job_id="job1")
    before = jobs.get("job1")
    with pytest.raises(ValueError, match="比赛记录"):
        jobs.append_run("job1", run())
    assert jobs.get("job1") == before
    jobs.update("job1", {"status": "running"})
    jobs.update("job1", {"status": "completed"})
    with pytest.raises(ValueError, match="比赛记录"):
        jobs.append_run("job1", run())
    assert jobs.get("job1")["completed"] == 0
    assert jobs.runs("job1")["total"] == 0
    with pytest.raises(ValueError, match="比赛记录"):
        jobs.append_run("missing", run())


def test_runs_envelope_pagination_and_missing_job(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", total=3, job_id="job1")
    jobs.update("job1", {"status": "running"})
    for index in range(3):
        jobs.append_run("job1", run(seed=index))
    first = jobs.runs("job1", limit=2)
    assert set(first) == {"items", "total", "next_offset"}
    assert [item["sequence"] for item in first["items"]] == [1, 2]
    assert first["total"] == 3
    assert first["next_offset"] == 2
    tail = jobs.runs("job1", limit=2, offset=2)
    assert [item["sequence"] for item in tail["items"]] == [3]
    assert tail["total"] == 3
    assert tail["next_offset"] is None
    assert jobs.runs("missing") == {"items": [], "total": 0, "next_offset": None}
    with pytest.raises(ValueError, match="分页"):
        jobs.runs("job1", limit=0)
    with pytest.raises(ValueError, match="分页"):
        jobs.runs("job1", limit=201)


def test_delete_removes_job_and_runs(tmp_path: Path):
    jobs = service(tmp_path)
    jobs.create("experiment", total=1, job_id="job1")
    jobs.update("job1", {"status": "running"})
    jobs.append_run("job1", run())
    assert jobs.delete("job1") is True
    assert jobs.get("job1") is None
    assert jobs.runs("job1") == {"items": [], "total": 0, "next_offset": None}
    assert jobs.delete("job1") is False


def test_only_committed_writes_are_visible(tmp_path: Path):
    db = database(tmp_path)
    jobs = JobService(JobRepository(db))
    jobs.create("experiment", total=2, job_id="job1")
    jobs.update("job1", {"status": "running"})
    repository = JobRepository(db)
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repository.add_run("job1", run(), connection=connection)
            repository.update("job1", {"completed": 1}, connection=connection)
            raise RuntimeError("rollback")
    assert jobs.get("job1")["completed"] == 0
    assert jobs.runs("job1")["total"] == 0


def test_two_threads_append_runs_with_unique_sequences(tmp_path: Path):
    db = database(tmp_path)
    jobs = JobService(JobRepository(db))
    jobs.create("experiment", total=6, job_id="job1")
    jobs.update("job1", {"status": "running"})
    barrier = threading.Barrier(2)

    def worker(start_seed):
        barrier.wait()
        return [jobs.append_run("job1", run(seed=start_seed + index)) for index in range(3)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(worker, (0, 100)))
    records = [record for batch in batches for record in batch]
    assert sorted(record["sequence"] for record in records) == [1, 2, 3, 4, 5, 6]
    assert jobs.get("job1")["completed"] == 6
    assert jobs.runs("job1", limit=200)["total"] == 6


def test_two_threads_overflow_keeps_completed_atomic(tmp_path: Path):
    db = database(tmp_path)
    jobs = JobService(JobRepository(db))
    jobs.create("experiment", total=3, job_id="job1")
    jobs.update("job1", {"status": "running"})
    barrier = threading.Barrier(2)

    def worker(start_seed):
        barrier.wait()
        records, errors = [], 0
        for index in range(2):
            try:
                records.append(jobs.append_run("job1", run(seed=start_seed + index)))
            except ValueError:
                errors += 1
        return records, errors

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (0, 100)))
    records = [record for batch, _ in results for record in batch]
    errors = sum(count for _, count in results)
    assert errors == 1
    assert sorted(record["sequence"] for record in records) == [1, 2, 3]
    assert jobs.get("job1")["completed"] == 3
    assert jobs.runs("job1", limit=200)["total"] == 3
