from __future__ import annotations

import json
import queue
import threading
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

DEFAULT_HISTORY_LIMIT = 256
KEEPALIVE_INTERVAL_SECONDS = 15.0
KEEPALIVE_COMMENT = ": keepalive\n\n"
_CLOSED = object()


class EventSubscription:
    """事件发布器返回的订阅句柄，提供阻塞与非阻塞读取。"""

    def __init__(self, publisher: EventPublisher) -> None:
        self._publisher = publisher
        self._queue: queue.Queue[Any] = queue.Queue()
        self._close_lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, block: bool = True, timeout: float | None = None) -> dict[str, Any] | None:
        """读取一个事件；订阅关闭且无剩余事件时返回 None，空队列非阻塞或超时读取抛出 queue.Empty。"""
        if self._closed and self._queue.empty():
            return None
        return self._unwrap(self._queue.get(block=block, timeout=timeout))

    def get_nowait(self) -> dict[str, Any] | None:
        if self._closed and self._queue.empty():
            return None
        return self._unwrap(self._queue.get_nowait())

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._publisher._remove_subscriber(self)
        self._queue.put(_CLOSED)

    def _offer(self, event: dict[str, Any]) -> None:
        if not self._closed:
            self._queue.put(event)

    def _close_from_publisher(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(_CLOSED)

    def _unwrap(self, item: Any) -> dict[str, Any] | None:
        if item is _CLOSED:
            self._closed = True
            return None
        return item


class EventPublisher:
    """线程安全的内存事件发布器：单调递增 id、有界历史、多订阅者广播。"""

    def __init__(self, history_limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._capacity = _positive_integer(history_limit, "历史容量")
        self._lock = threading.Lock()
        self._history: deque[dict[str, Any]] = deque(maxlen=self._capacity)
        self._subscribers: set[EventSubscription] = set()
        self._last_id = 0
        self._closed = False

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._last_id

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: str, data: Mapping[str, Any]) -> dict[str, Any]:
        name = _event_name(event)
        payload = _event_data(data)
        with self._lock:
            if self._closed:
                raise RuntimeError("事件发布器已关闭")
            self._last_id += 1
            published = {"id": self._last_id, "event": name, "data": payload}
            self._history.append(published)
            for subscription in self._subscribers:
                subscription._offer(published)
            return published

    def history(self, limit: int | None = None) -> list[dict[str, Any]]:
        count = None if limit is None else _non_negative_integer(limit, "历史条数")
        with self._lock:
            events = list(self._history)
        if count is None or count >= len(events):
            return events
        return events[len(events) - count :] if count else []

    def replay(self, after_id: int) -> list[dict[str, Any]]:
        boundary = _non_negative_integer(after_id, "事件 id")
        with self._lock:
            return [event for event in self._history if event["id"] > boundary]

    @contextmanager
    def subscriber(self) -> Iterator[EventSubscription]:
        subscription = EventSubscription(self)
        with self._lock:
            if self._closed:
                subscription._close_from_publisher()
            else:
                self._subscribers.add(subscription)
        try:
            yield subscription
        finally:
            subscription.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
        for subscription in subscribers:
            subscription._close_from_publisher()

    def _remove_subscriber(self, subscription: EventSubscription) -> None:
        with self._lock:
            self._subscribers.discard(subscription)


def format_event(event: Mapping[str, Any]) -> str:
    """把事件编码为单行 data 的 SSE 帧。"""
    event_id = _non_negative_integer(event.get("id"), "事件 id")
    name = _event_name(event.get("event"))
    payload = _event_data(event.get("data", {}))
    return f"id: {event_id}\nevent: {name}\ndata: {_serialize_json(payload)}\n\n"


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label}必须为正整数")
    return value


def _non_negative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label}必须为非负整数")
    return value


def _event_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("事件名必须为非空字符串")
    if "\r" in value or "\n" in value or "\x00" in value:
        raise ValueError("事件名不能包含换行或空字符")
    return value


def _event_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("事件数据必须是映射对象")
    payload = dict(value)
    _serialize_json(payload)
    return payload


def _serialize_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("事件数据必须可 JSON 序列化") from error
