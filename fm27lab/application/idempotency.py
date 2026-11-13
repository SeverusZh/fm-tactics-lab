from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Protocol

HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
SNAPSHOT_FIELDS = frozenset({"status", "body", "content_type"})
MIN_STATUS = 100
MAX_STATUS = 599
MAX_CONTENT_TYPE_LENGTH = 255
MAX_PATH_LENGTH = 4096


class IdempotencyConflict(ValueError):
    pass


class IdempotencyStore(Protocol):
    def get(self, key: str) -> Mapping[str, Any] | None: ...

    def record(
        self,
        key: str,
        request_hash: str,
        response: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class IdempotencyService:
    def __init__(self, repository: IdempotencyStore) -> None:
        self.repository = repository

    def fingerprint(
        self,
        method: Any,
        path: Any,
        query: Any,
        body_bytes: Any,
    ) -> str:
        digest = hashlib.sha256()
        for part in (
            _normalize_method(method).encode("ascii"),
            _normalize_path(path).encode("utf-8"),
            _normalize_query(query).encode("utf-8"),
            _normalize_body(body_bytes),
        ):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
        return digest.hexdigest()

    def lookup(self, key: str, request_hash: Any) -> dict[str, Any] | None:
        digest = _normalize_hash(request_hash)
        record = self.repository.get(key)
        return None if record is None else _snapshot_from_record(record, digest)

    def store(self, key: str, request_hash: Any, snapshot: Any) -> dict[str, Any]:
        digest = _normalize_hash(request_hash)
        normalized = _normalize_snapshot(snapshot)
        try:
            record = self.repository.record(key, digest, normalized)
        except ValueError:
            existing = self.repository.get(key)
            if existing is None:
                raise
            return _snapshot_from_record(existing, digest)
        return _normalize_snapshot(record["response"])


def _normalize_method(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or any(character.isspace() for character in value)
    ):
        raise ValueError("幂等指纹方法无效")
    return value.upper()


def _normalize_path(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > MAX_PATH_LENGTH:
        raise ValueError("幂等指纹路径无效")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("幂等指纹路径无效") from error
    return value


def _normalize_query(value: Any) -> str:
    if isinstance(value, bytes):
        text = value.decode("latin-1")
    elif isinstance(value, str):
        text = value
    else:
        raise ValueError("幂等指纹查询无效")
    pairs: list[tuple[str, str]] = []
    for chunk in text.split("&"):
        if not chunk:
            continue
        name, _, raw_value = chunk.partition("=")
        pairs.append((name, raw_value))
    pairs.sort()
    canonical = "&".join(f"{name}={raw_value}" for name, raw_value in pairs)
    try:
        canonical.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("幂等指纹查询无效") from error
    return canonical


def _normalize_body(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    raise ValueError("幂等指纹请求体无效")


def _normalize_hash(value: Any) -> str:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise ValueError("幂等请求哈希无效")
    return value.lower()


def _normalize_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("幂等响应快照必须是对象")
    if set(value.keys()) != SNAPSHOT_FIELDS:
        raise ValueError("幂等响应快照字段无效")
    status = value["status"]
    if isinstance(status, bool) or not isinstance(status, int) or not MIN_STATUS <= status <= MAX_STATUS:
        raise ValueError("幂等响应快照状态无效")
    body = value["body"]
    if not isinstance(body, str):
        raise ValueError("幂等响应快照响应体无效")
    try:
        body.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("幂等响应快照响应体无效") from error
    content_type = value["content_type"]
    if not isinstance(content_type, str) or len(content_type) > MAX_CONTENT_TYPE_LENGTH:
        raise ValueError("幂等响应快照内容类型无效")
    if "\r" in content_type or "\n" in content_type:
        raise ValueError("幂等响应快照内容类型无效")
    try:
        content_type.encode("latin-1")
    except UnicodeEncodeError as error:
        raise ValueError("幂等响应快照内容类型无效") from error
    return {"status": status, "body": body, "content_type": content_type}


def _snapshot_from_record(record: Mapping[str, Any], digest: str) -> dict[str, Any]:
    stored = record.get("request_hash")
    if not isinstance(stored, str) or stored.lower() != digest:
        raise IdempotencyConflict("幂等键已被不同载荷使用")
    return _normalize_snapshot(record.get("response"))
