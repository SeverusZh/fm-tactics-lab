from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier

import pytest

from fm27lab.adapters.storage_sqlite.artifacts import ArtifactRepository
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.idempotency import IdempotencyConflict, IdempotencyRepository
from fm27lab.adapters.storage_sqlite.repositories import JobRepository

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HASH = "a" * 64


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def job(**extra):
    value = {"id": "job1", "kind": "experiment", "status": "queued", "config": {}}
    value.update(extra)
    return value


def artifact(**extra):
    value = {
        "kind": "fmf",
        "path": "exports/tactic.fmf",
        "sha256": "a" * 64,
        "bytes": 128,
    }
    value.update(extra)
    return value


def payload(**extra):
    value = {"status": "accepted", "job_id": "job1"}
    value.update(extra)
    return value


def test_artifact_repository_round_trip_and_generated_id(tmp_path: Path):
    repo = ArtifactRepository(database(tmp_path))
    created = repo.add(artifact(id="artifact1"))
    assert created["id"] == "artifact1"
    assert created["job_id"] is None
    assert created["kind"] == "fmf"
    assert created["path"] == "exports/tactic.fmf"
    assert created["sha256"] == "a" * 64
    assert created["bytes"] == 128
    assert isinstance(created["created_at"], str)
    datetime.fromisoformat(created["created_at"])
    assert repo.get("artifact1") == created
    generated = repo.add(artifact())
    assert ID_PATTERN.fullmatch(generated["id"])
    assert repo.get(generated["id"]) == generated
    assert repo.get("missing") is None
    stamped = repo.add(artifact(id="stamped", created_at="2000-01-02T03:04:05+00:00"))
    assert stamped["created_at"] == "2000-01-02T03:04:05+00:00"


def test_artifact_repository_sha256_is_stored_lowercase(tmp_path: Path):
    repo = ArtifactRepository(database(tmp_path))
    created = repo.add(artifact(sha256="A" * 64))
    assert created["sha256"] == "a" * 64
    assert repo.get(created["id"])["sha256"] == "a" * 64


def test_artifact_repository_validates_fields(tmp_path: Path):
    repo = ArtifactRepository(database(tmp_path))
    invalid = (
        [],
        artifact(id=""),
        artifact(id="a/b"),
        artifact(id="x" * 65),
        artifact(id=7),
        artifact(job_id=""),
        artifact(job_id="a/b"),
        artifact(job_id=7),
        artifact(kind=""),
        artifact(kind="x" * 65),
        artifact(kind="bad\nkind"),
        artifact(kind="bad\x85kind"),
        artifact(kind="bad\x9fkind"),
        artifact(kind="\ud800"),
        artifact(kind=7),
        artifact(path=""),
        artifact(path="x" * 4097),
        artifact(path="bad\npath"),
        artifact(path="bad\x85path"),
        artifact(path="\x9f"),
        artifact(path="\ud800"),
        artifact(path=7),
        artifact(sha256="a" * 63),
        artifact(sha256="g" * 64),
        artifact(sha256=7),
        artifact(bytes=-1),
        artifact(bytes=True),
        artifact(bytes=1.0),
        artifact(bytes="1"),
        artifact(created_at=""),
        artifact(created_at="not-a-time"),
        artifact(created_at="2000-01-01T00:00:00"),
        artifact(created_at=7),
    )
    for value in invalid:
        with pytest.raises(ValueError):
            repo.add(value)


def test_artifact_repository_accepts_boundary_values(tmp_path: Path):
    repo = ArtifactRepository(database(tmp_path))
    created = repo.add(artifact(id="i" * 64, kind="k" * 64, path="p" * 4096, bytes=0))
    assert created["id"] == "i" * 64
    assert created["kind"] == "k" * 64
    assert created["path"] == "p" * 4096
    assert created["bytes"] == 0
    assert repo.get("i" * 64) == created
    for index in range(3):
        repo.add(artifact(id=f"page{index}", created_at=f"2000-01-0{index + 1}T00:00:00+00:00"))
    assert len(repo.list(limit=1)) == 1
    assert len(repo.list(limit=256)) == 4


def test_artifact_repository_normalizes_created_at_to_utc(tmp_path: Path):
    repo = ArtifactRepository(database(tmp_path))
    created = repo.add(artifact(id="zoned", created_at="2000-01-01T05:00:00+05:00"))
    assert created["created_at"] == "2000-01-01T00:00:00+00:00"
    assert repo.get("zoned")["created_at"] == "2000-01-01T00:00:00+00:00"
    other = repo.add(artifact(id="zoned_minus", created_at="1999-12-31T19:00:00-05:00"))
    assert other["created_at"] == "2000-01-01T00:00:00+00:00"


def test_artifact_repository_orders_created_at_as_instant(tmp_path: Path):
    repo = ArtifactRepository(database(tmp_path))
    repo.add(artifact(id="earlier", created_at="2000-01-01T02:00:00+02:00"))
    repo.add(artifact(id="later", created_at="1999-12-31T22:00:00-03:00"))
    assert [row["id"] for row in repo.list()] == ["later", "earlier"]


def test_artifact_repository_rejects_duplicate_id(tmp_path: Path):
    repo = ArtifactRepository(database(tmp_path))
    repo.add(artifact(id="duplicated"))
    with pytest.raises(ValueError, match="产物已存在"):
        repo.add(artifact(id="duplicated"))


def test_artifact_repository_distinguishes_duplicate_id_from_missing_job(tmp_path: Path):
    db = database(tmp_path)
    repo = ArtifactRepository(db)
    JobRepository(db).add(job())
    repo.add(artifact(id="duplicated", job_id="job1"))
    with pytest.raises(ValueError, match="产物已存在"):
        repo.add(artifact(id="duplicated", job_id="job1"))
    with pytest.raises(ValueError, match="任务不存在"):
        repo.add(artifact(id="unique", job_id="missingjob"))


def test_artifact_repository_job_reference_and_set_null(tmp_path: Path):
    db = database(tmp_path)
    jobs = JobRepository(db)
    repo = ArtifactRepository(db)
    jobs.add(job())
    linked = repo.add(artifact(id="linked", job_id="job1"))
    assert linked["job_id"] == "job1"
    assert repo.get("linked")["job_id"] == "job1"
    assert jobs.delete("job1") is True
    assert repo.get("linked")["job_id"] is None
    with pytest.raises(ValueError, match="任务不存在"):
        repo.add(artifact(job_id="missingjob"))


def test_artifact_repository_list_filters_orders_and_paginates(tmp_path: Path):
    db = database(tmp_path)
    jobs = JobRepository(db)
    repo = ArtifactRepository(db)
    jobs.add(job())
    jobs.add(job(id="job2"))
    repo.add(artifact(id="a1", created_at="2000-01-01T00:00:00+00:00"))
    repo.add(artifact(id="a2", kind="csv", created_at="2000-01-02T00:00:00+00:00"))
    repo.add(artifact(id="a3", created_at="2000-01-02T00:00:00+00:00", job_id="job1"))
    repo.add(artifact(id="a4", kind="csv", created_at="2000-01-03T00:00:00+00:00", job_id="job2"))
    assert [row["id"] for row in repo.list()] == ["a4", "a3", "a2", "a1"]
    assert [row["id"] for row in repo.list(kind="fmf")] == ["a3", "a1"]
    assert [row["id"] for row in repo.list(job_id="job1")] == ["a3"]
    assert [row["id"] for row in repo.list(kind="csv", job_id="job2")] == ["a4"]
    assert [row["id"] for row in repo.list(limit=2)] == ["a4", "a3"]
    assert [row["id"] for row in repo.list(limit=2, offset=2)] == ["a2", "a1"]
    assert repo.list(limit=2, offset=4) == []
    for kwargs in (
        {"limit": 0},
        {"limit": 257},
        {"limit": True},
        {"offset": -1},
        {"offset": True},
        {"kind": ""},
        {"kind": 7},
        {"job_id": "a/b"},
    ):
        with pytest.raises(ValueError):
            repo.list(**kwargs)


def test_artifact_repository_delete_and_invalid_identifiers(tmp_path: Path):
    repo = ArtifactRepository(database(tmp_path))
    repo.add(artifact(id="fixed"))
    assert repo.delete("fixed") is True
    assert repo.delete("fixed") is False
    assert repo.get("fixed") is None
    for invalid in ("", "a/b", "x" * 65, 7, None, []):
        with pytest.raises(ValueError, match="产物标识无效"):
            repo.get(invalid)
        with pytest.raises(ValueError, match="产物标识无效"):
            repo.delete(invalid)


def test_artifact_repository_transaction_contract_and_rollback(tmp_path: Path):
    db = database(tmp_path)
    jobs = JobRepository(db)
    repo = ArtifactRepository(db)
    with db.transaction() as connection:
        jobs.add(job(), connection=connection)
        created = repo.add(artifact(id="inside", job_id="job1"), connection=connection)
        assert repo.get("inside", connection=connection) == created
        assert repo.list(job_id="job1", connection=connection) == [created]
    assert repo.get("inside") is not None
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.add(artifact(id="rolled", job_id="job1"), connection=connection)
            assert repo.get("rolled", connection=connection) is not None
            raise RuntimeError("rollback")
    assert repo.get("rolled") is None
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            assert repo.delete("inside", connection=connection) is True
            raise RuntimeError("rollback")
    assert repo.get("inside") is not None
    with db.transaction() as connection:
        with pytest.raises(ValueError, match="任务不存在"):
            repo.add(artifact(id="orphan", job_id="missingjob"), connection=connection)
        repo.add(artifact(id="after_failure", job_id="job1"), connection=connection)
    assert repo.get("orphan") is None
    assert repo.get("after_failure") is not None


def test_idempotency_repository_round_trip(tmp_path: Path):
    repo = IdempotencyRepository(database(tmp_path))
    assert repo.get("key-1") is None
    record = repo.record("key-1", HASH, payload())
    assert record["key"] == "key-1"
    assert record["request_hash"] == HASH
    assert record["response"] == payload()
    datetime.fromisoformat(record["created_at"])
    assert repo.get("key-1") == record
    assert repo.count() == 1
    assert repo.get("A.z_9:-") is None
    assert repo.get("k" * 128) is None


def test_idempotency_repository_hash_is_canonical_lowercase(tmp_path: Path):
    repo = IdempotencyRepository(database(tmp_path))
    created = repo.record("canonical", "A" * 64, payload())
    assert created["request_hash"] == HASH
    assert repo.record("canonical", HASH, payload()) == created


def test_idempotency_repository_replay_and_conflict(tmp_path: Path):
    repo = IdempotencyRepository(database(tmp_path))
    first = repo.record("submit", HASH, payload())
    assert repo.record("submit", HASH, payload()) == first
    assert repo.record("submit", HASH, {"status": "ignored"}) == first
    with pytest.raises(IdempotencyConflict, match="幂等键已被不同载荷使用") as caught:
        repo.record("submit", "b" * 64, payload())
    assert isinstance(caught.value, ValueError)
    assert repo.get("submit") == first
    assert repo.count() == 1


def test_idempotency_repository_validates_key_hash_and_response(tmp_path: Path):
    repo = IdempotencyRepository(database(tmp_path))
    for invalid_key in ("", "k" * 129, "a b", "键", 7, None, []):
        with pytest.raises(ValueError, match="幂等键无效"):
            repo.get(invalid_key)
        with pytest.raises(ValueError, match="幂等键无效"):
            repo.record(invalid_key, HASH, payload())
        with pytest.raises(ValueError, match="幂等键无效"):
            repo.delete(invalid_key)
    for invalid_hash in ("a" * 63, "a" * 65, "g" * 64, "", 7, None):
        with pytest.raises(ValueError):
            repo.record("key", invalid_hash, payload())
    for invalid_response in (
        [],
        "text",
        None,
        7,
        {"x": {1, 2}},
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": "\ud800"},
    ):
        with pytest.raises(ValueError):
            repo.record("key", HASH, invalid_response)
    assert repo.count() == 0


def test_idempotency_repository_rejects_oversized_response(tmp_path: Path):
    repo = IdempotencyRepository(database(tmp_path))
    limit = 1_048_576
    boundary = {"x": "a" * (limit - 8)}
    created = repo.record("boundary", HASH, boundary)
    assert created["response"] == boundary
    with pytest.raises(ValueError, match="幂等响应过大"):
        repo.record("oversized", "b" * 64, {"x": "a" * (limit - 7)})
    assert repo.count() == 1


def test_idempotency_repository_delete_prune_and_count(tmp_path: Path):
    db = database(tmp_path)
    repo = IdempotencyRepository(db)
    repo.record("a", HASH, payload())
    repo.record("b", "b" * 64, payload())
    repo.record("c", "c" * 64, payload())
    assert repo.count() == 3
    assert repo.delete("a") is True
    assert repo.delete("a") is False
    assert repo.count() == 2
    with db.transaction() as connection:
        assert repo.count(connection=connection) == 2
        assert repo.get("b", connection=connection)["response"] == payload()
        connection.execute(
            "UPDATE idempotency SET created_at=? WHERE key=?",
            ("1999-01-01T00:00:00+00:00", "b"),
        )
        connection.execute(
            "UPDATE idempotency SET created_at=? WHERE key=?",
            ("2000-01-01T00:00:00+00:00", "c"),
        )
    assert repo.prune("1999-01-01T00:00:00+00:00") == 0
    assert repo.prune("2000-01-01T00:00:00+00:00") == 1
    assert repo.count() == 1
    assert repo.prune("2999-01-01T00:00:00+00:00") == 1
    assert repo.count() == 0
    for invalid_before in ("", "not-a-time", 7, None):
        with pytest.raises(ValueError):
            repo.prune(invalid_before)


def test_idempotency_prune_compares_instants_not_strings(tmp_path: Path):
    scenarios = (
        ("2000-01-01T02:00:00+00:00", "2000-01-01T05:00:00+05:00", False),
        ("1999-12-31T22:00:00+00:00", "1999-12-31T20:00:00-05:00", True),
        ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00Z", False),
        ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00.000000+00:00", False),
        ("2000-01-01T00:00:00.500000+00:00", "2000-01-01T00:00:00+00:00", False),
        ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00.500000+00:00", True),
    )
    for index, (created_at, before, deleted) in enumerate(scenarios):
        db = Database(tmp_path / f"case{index}" / "fm27lab.db")
        db.initialize()
        repo = IdempotencyRepository(db)
        repo.record("row", HASH, payload())
        with db.transaction() as connection:
            connection.execute(
                "UPDATE idempotency SET created_at=? WHERE key=?",
                (created_at, "row"),
            )
        assert repo.prune(before) == (1 if deleted else 0)
        assert (repo.get("row") is None) is deleted


def test_idempotency_prune_rejects_naive_cutoff(tmp_path: Path):
    db = database(tmp_path)
    repo = IdempotencyRepository(db)
    repo.record("row", HASH, payload())
    for before in (
        "2000-01-01T00:00:00",
        "2000-01-01",
        "2000-01-01T00:00:00.123456",
        "",
        "not-a-time",
        7,
        None,
    ):
        with pytest.raises(ValueError, match="幂等截止时间无效"):
            repo.prune(before)
    assert repo.count() == 1


def test_idempotency_repository_concurrent_record_keeps_single_row(tmp_path: Path):
    db = database(tmp_path)
    first = IdempotencyRepository(db)
    second = IdempotencyRepository(Database(db.path))
    barrier = Barrier(2)

    def submit(repo: IdempotencyRepository):
        barrier.wait(timeout=10)
        return repo.record("concurrent", HASH, payload())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=30) for future in (pool.submit(submit, first), pool.submit(submit, second))
        ]
    assert results[0] == results[1]
    assert first.count() == 1
    assert first.get("concurrent") == results[0]


def test_idempotency_repository_concurrent_different_hash_single_winner(tmp_path: Path):
    db = database(tmp_path)
    first = IdempotencyRepository(db)
    second = IdempotencyRepository(Database(db.path))
    barrier = Barrier(2)

    def submit(repo: IdempotencyRepository, digest: str):
        barrier.wait(timeout=10)
        try:
            return "stored", repo.record("race", digest, {"digest": digest})
        except IdempotencyConflict as error:
            return "conflict", str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=30)
            for future in (
                pool.submit(submit, first, "a" * 64),
                pool.submit(submit, second, "b" * 64),
            )
        ]
    assert first.count() == 1
    winners = [value for outcome, value in results if outcome == "stored"]
    conflicts = [value for outcome, value in results if outcome == "conflict"]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert conflicts[0] == "幂等键已被不同载荷使用"
    assert first.get("race") == winners[0]
    assert first.get("race")["request_hash"] in {"a" * 64, "b" * 64}


def test_idempotency_repository_transaction_contract_and_rollback(tmp_path: Path):
    db = database(tmp_path)
    repo = IdempotencyRepository(db)
    with db.transaction() as connection:
        record = repo.record("inside", HASH, payload(), connection=connection)
        assert repo.get("inside", connection=connection) == record
        assert repo.count(connection=connection) == 1
        assert repo.record("inside", HASH, payload(), connection=connection) == record
        with pytest.raises(IdempotencyConflict):
            repo.record("inside", "b" * 64, payload(), connection=connection)
        assert repo.count(connection=connection) == 1
    assert repo.get("inside") == record
    with pytest.raises(RuntimeError):
        with db.transaction() as connection:
            repo.record("rolled", "c" * 64, payload(), connection=connection)
            raise RuntimeError("rollback")
    assert repo.get("rolled") is None
    assert repo.count() == 1
