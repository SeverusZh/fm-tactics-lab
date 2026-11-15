from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.idempotency import IdempotencyRepository
from fm27lab.application.idempotency import IdempotencyConflict, IdempotencyService

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HASH = "a" * 64
SNAPSHOT = {"status": 201, "body": '{"id":"pool1"}', "content_type": "application/json"}


def make_service(tmp_path: Path) -> IdempotencyService:
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    return IdempotencyService(IdempotencyRepository(database))


def second_service(service: IdempotencyService) -> IdempotencyService:
    return IdempotencyService(IdempotencyRepository(Database(service.repository.database.path)))


def test_fingerprint_is_stable_sha256_digest(tmp_path: Path):
    service = make_service(tmp_path)
    first = service.fingerprint("POST", "/api/pools", "limit=2&offset=0", b'{"name":"a"}')
    second = service.fingerprint("POST", "/api/pools", "limit=2&offset=0", b'{"name":"a"}')
    assert first == second
    assert HASH_PATTERN.fullmatch(first)


def test_fingerprint_normalizes_method_case_and_query_order(tmp_path: Path):
    service = make_service(tmp_path)
    assert service.fingerprint("post", "/api/pools", "limit=2&offset=0", b"{}") == service.fingerprint(
        "POST", "/api/pools", "offset=0&limit=2", b"{}"
    )
    assert service.fingerprint("PATCH", "/api/drafts/x", "", b"{}") == service.fingerprint(
        "patch", "/api/drafts/x", b"", b"{}"
    )


def test_fingerprint_changes_with_each_component(tmp_path: Path):
    service = make_service(tmp_path)
    baseline = service.fingerprint("POST", "/api/pools", "limit=2", b'{"name":"a"}')
    variants = (
        service.fingerprint("PATCH", "/api/pools", "limit=2", b'{"name":"a"}'),
        service.fingerprint("POST", "/api/drafts", "limit=2", b'{"name":"a"}'),
        service.fingerprint("POST", "/api/pools", "limit=3", b'{"name":"a"}'),
        service.fingerprint("POST", "/api/pools", "limit=2", b'{"name":"b"}'),
        service.fingerprint("POST", "/api/pools", "limit=2", b""),
    )
    assert len(set(variants)) == len(variants)
    for value in variants:
        assert HASH_PATTERN.fullmatch(value)
        assert value != baseline


def test_fingerprint_rejects_invalid_components(tmp_path: Path):
    service = make_service(tmp_path)
    for method in ("", None, 7, "PO ST", "póst"):
        with pytest.raises(ValueError, match="幂等指纹方法无效"):
            service.fingerprint(method, "/api/pools", "", b"")
    for path in ("", "api/pools", None, 7, "/api/\ud800"):
        with pytest.raises(ValueError, match="幂等指纹路径无效"):
            service.fingerprint("POST", path, "", b"")
    for query in (None, 7, ["a=1"]):
        with pytest.raises(ValueError, match="幂等指纹查询无效"):
            service.fingerprint("POST", "/api/pools", query, b"")
    for body in ("{}", None, 7, [1]):
        with pytest.raises(ValueError, match="幂等指纹请求体无效"):
            service.fingerprint("POST", "/api/pools", "", body)


def test_lookup_returns_none_for_unknown_key(tmp_path: Path):
    service = make_service(tmp_path)
    assert service.lookup("unknown", HASH) is None
    assert service.repository.count() == 0


def test_store_then_lookup_replays_snapshot(tmp_path: Path):
    service = make_service(tmp_path)
    stored = service.store("pool-once", HASH, SNAPSHOT)
    assert stored == SNAPSHOT
    assert stored is not SNAPSHOT
    assert service.lookup("pool-once", HASH) == SNAPSHOT
    assert service.repository.count() == 1
    record = service.repository.get("pool-once")
    assert record["request_hash"] == HASH
    assert record["response"] == SNAPSHOT


def test_store_is_idempotent_for_same_hash_and_key(tmp_path: Path):
    service = make_service(tmp_path)
    first = service.store("pool-once", HASH, SNAPSHOT)
    second = service.store("pool-once", HASH, {"status": 200, "body": "other", "content_type": ""})
    assert second == first == SNAPSHOT
    assert service.repository.count() == 1
    assert service.lookup("pool-once", HASH) == SNAPSHOT


def test_store_conflicts_for_same_key_with_different_hash(tmp_path: Path):
    service = make_service(tmp_path)
    first = service.store("pool-once", HASH, SNAPSHOT)
    with pytest.raises(IdempotencyConflict, match="幂等键已被不同载荷使用") as caught:
        service.store("pool-once", "b" * 64, SNAPSHOT)
    assert isinstance(caught.value, ValueError)
    with pytest.raises(IdempotencyConflict, match="幂等键已被不同载荷使用"):
        service.lookup("pool-once", "b" * 64)
    assert service.repository.get("pool-once")["request_hash"] == HASH
    assert service.repository.get("pool-once")["response"] == first
    assert service.repository.count() == 1


def test_store_and_lookup_validate_snapshot_fields(tmp_path: Path):
    service = make_service(tmp_path)
    invalid_snapshots = (
        [],
        "snapshot",
        None,
        7,
        {"status": 200, "body": "x"},
        {"status": 200, "body": "x", "content_type": "", "extra": 1},
        {"status": True, "body": "x", "content_type": ""},
        {"status": 99, "body": "x", "content_type": ""},
        {"status": 600, "body": "x", "content_type": ""},
        {"status": "200", "body": "x", "content_type": ""},
        {"status": 200, "body": b"x", "content_type": ""},
        {"status": 200, "body": "\ud800", "content_type": ""},
        {"status": 200, "body": "x", "content_type": None},
        {"status": 200, "body": "x", "content_type": 7},
        {"status": 200, "body": "x", "content_type": "x" * 256},
        {"status": 200, "body": "x", "content_type": "text/plain\nX: y"},
        {"status": 200, "body": "x", "content_type": "键"},
    )
    for snapshot in invalid_snapshots:
        with pytest.raises(ValueError):
            service.store("invalid", HASH, snapshot)
    assert service.repository.count() == 0
    boundary = {"status": 100, "body": "", "content_type": ""}
    assert service.store("boundary", HASH, boundary) == boundary
    assert service.lookup("boundary", HASH) == boundary
    service.repository.record("corrupt", HASH, {"status": "bad", "body": "x", "content_type": ""})
    with pytest.raises(ValueError):
        service.lookup("corrupt", HASH)
    assert service.repository.count() == 2


def test_service_reuses_repository_key_and_hash_validation(tmp_path: Path):
    service = make_service(tmp_path)
    for invalid_key in ("", "a b", "a/b", "k" * 129, 7, None):
        with pytest.raises(ValueError, match="幂等键无效"):
            service.lookup(invalid_key, HASH)
        with pytest.raises(ValueError, match="幂等键无效"):
            service.store(invalid_key, HASH, SNAPSHOT)
    for invalid_hash in ("a" * 63, "a" * 65, "g" * 64, "", 7, None):
        with pytest.raises(ValueError, match="幂等请求哈希无效"):
            service.lookup("key", invalid_hash)
        with pytest.raises(ValueError, match="幂等请求哈希无效"):
            service.store("key", invalid_hash, SNAPSHOT)
    assert service.repository.count() == 0
    assert service.store("upper", "A" * 64, SNAPSHOT) == SNAPSHOT
    assert service.repository.get("upper")["request_hash"] == HASH


def test_concurrent_store_keeps_single_row(tmp_path: Path):
    service = make_service(tmp_path)
    other = second_service(service)
    barrier = Barrier(2)

    def submit(store: IdempotencyService, body: str):
        barrier.wait(timeout=10)
        return store.store("concurrent", HASH, {"status": 201, "body": body, "content_type": ""})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=30)
            for future in (
                pool.submit(submit, service, "first"),
                pool.submit(submit, other, "second"),
            )
        ]
    assert results[0] == results[1]
    assert results[0]["body"] in {"first", "second"}
    assert service.repository.count() == 1
    assert service.lookup("concurrent", HASH) == results[0]


def test_concurrent_conflicting_store_has_single_winner(tmp_path: Path):
    service = make_service(tmp_path)
    other = second_service(service)
    barrier = Barrier(2)

    def submit(store: IdempotencyService, digest: str):
        barrier.wait(timeout=10)
        try:
            return "stored", store.store("race", digest, {**SNAPSHOT, "body": digest})
        except IdempotencyConflict as error:
            return "conflict", str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=30)
            for future in (
                pool.submit(submit, service, "a" * 64),
                pool.submit(submit, other, "b" * 64),
            )
        ]
    winners = [value for outcome, value in results if outcome == "stored"]
    conflicts = [value for outcome, value in results if outcome == "conflict"]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert conflicts[0] == "幂等键已被不同载荷使用"
    assert service.repository.count() == 1
    assert service.repository.get("race")["request_hash"] in {"a" * 64, "b" * 64}
