from __future__ import annotations

import json
import queue
import re
import threading
from types import MappingProxyType

import pytest

from fm27lab.application.events import (
    DEFAULT_HISTORY_LIMIT,
    KEEPALIVE_COMMENT,
    EventPublisher,
    format_event,
)

CHINESE = re.compile(r"[\u4e00-\u9fff]")


def publish_n(publisher: EventPublisher, count: int, event: str = "job.progress", **extra) -> list[dict]:
    return [publisher.publish(event, {"n": index, **extra}) for index in range(1, count + 1)]


def test_publish_returns_event_with_monotonic_ids():
    publisher = EventPublisher()
    first = publisher.publish("job.progress", {"job_id": "abc", "completed": 1})
    second = publisher.publish("job.done", {"job_id": "abc"})

    assert first == {"id": 1, "event": "job.progress", "data": {"job_id": "abc", "completed": 1}}
    assert second["id"] == 2
    assert second["event"] == "job.done"
    assert publisher.last_id == 2


def test_publish_accepts_mapping_proxy_and_rejects_invalid_input():
    publisher = EventPublisher()
    event = publisher.publish("job.progress", MappingProxyType({"completed": 3}))
    assert event["data"] == {"completed": 3}

    with pytest.raises(ValueError) as empty_name:
        publisher.publish("", {})
    assert CHINESE.search(str(empty_name.value))

    with pytest.raises(ValueError) as newline_name:
        publisher.publish("job\nprogress", {})
    assert CHINESE.search(str(newline_name.value))

    with pytest.raises(ValueError) as not_mapping:
        publisher.publish("job.progress", ["not", "a", "mapping"])
    assert CHINESE.search(str(not_mapping.value))

    with pytest.raises(ValueError) as not_json:
        publisher.publish("job.progress", {"value": object()})
    assert CHINESE.search(str(not_json.value))

    assert publisher.last_id == 1


def test_history_is_bounded_and_drops_oldest_events():
    publisher = EventPublisher(history_limit=3)
    publish_n(publisher, 5)

    retained = publisher.history()
    assert [event["id"] for event in retained] == [3, 4, 5]
    assert publisher.replay(0) == retained

    default = EventPublisher()
    assert default.capacity == DEFAULT_HISTORY_LIMIT
    publish_n(default, DEFAULT_HISTORY_LIMIT + 10)
    history = default.history()
    assert len(history) == DEFAULT_HISTORY_LIMIT
    assert history[0]["id"] == 11
    assert history[-1]["id"] == DEFAULT_HISTORY_LIMIT + 10


def test_history_limit_argument_and_validation():
    publisher = EventPublisher()
    publish_n(publisher, 5)

    assert [event["id"] for event in publisher.history(2)] == [4, 5]
    assert [event["id"] for event in publisher.history(0)] == []
    assert [event["id"] for event in publisher.history(10)] == [1, 2, 3, 4, 5]

    for invalid in (-1, "2", 2.5, True):
        with pytest.raises(ValueError):
            publisher.history(invalid)

    for invalid in (0, -2):
        with pytest.raises(ValueError):
            EventPublisher(history_limit=invalid)


def test_replay_filters_events_newer_than_after_id():
    publisher = EventPublisher()
    publish_n(publisher, 5)

    assert [event["id"] for event in publisher.replay(0)] == [1, 2, 3, 4, 5]
    assert [event["id"] for event in publisher.replay(2)] == [3, 4, 5]
    assert publisher.replay(5) == []
    assert publisher.replay(99) == []

    bounded = EventPublisher(history_limit=3)
    publish_n(bounded, 5)
    assert [event["id"] for event in bounded.replay(3)] == [4, 5]

    for invalid in (-1, "3", 1.5, True):
        with pytest.raises(ValueError):
            publisher.replay(invalid)


def test_subscribers_receive_broadcast_without_history():
    publisher = EventPublisher()
    publisher.publish("job.progress", {"n": 0})

    with publisher.subscriber() as first, publisher.subscriber() as second:
        assert publisher.subscriber_count == 2
        event = publisher.publish("job.progress", {"n": 1})
        assert first.get(timeout=1) == event
        assert second.get(timeout=1) == event

        with pytest.raises(queue.Empty):
            first.get_nowait()
    assert publisher.subscriber_count == 0


def test_blocking_and_non_blocking_reads():
    publisher = EventPublisher()
    with publisher.subscriber() as subscription:
        with pytest.raises(queue.Empty):
            subscription.get_nowait()
        with pytest.raises(queue.Empty):
            subscription.get(block=False)
        with pytest.raises(queue.Empty):
            subscription.get(timeout=0.01)

        event = publisher.publish("job.progress", {"n": 1})
        assert subscription.get_nowait() == event
    assert subscription.closed


def test_publisher_close_wakes_all_blocked_subscribers():
    publisher = EventPublisher()
    managers = [publisher.subscriber() for _ in range(3)]
    subscriptions = [manager.__enter__() for manager in managers]
    results: list[dict | None] = []
    errors: list[BaseException] = []

    def read_one(subscription):
        try:
            results.append(subscription.get(timeout=5))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=read_one, args=(subscription,)) for subscription in subscriptions]
    for thread in threads:
        thread.start()

    publisher.close()

    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert errors == []
    assert results == [None, None, None]
    assert publisher.closed
    assert publisher.subscriber_count == 0

    with pytest.raises(RuntimeError) as closed:
        publisher.publish("job.progress", {})
    assert CHINESE.search(str(closed.value))

    for subscription in subscriptions:
        assert subscription.get_nowait() is None
    for manager in managers:
        manager.__exit__(None, None, None)


def test_subscription_close_unregisters_and_stops_delivery():
    publisher = EventPublisher()
    with publisher.subscriber() as subscription:
        assert publisher.subscriber_count == 1

        subscription.close()
        assert subscription.closed
        assert publisher.subscriber_count == 0
        event = publisher.publish("job.progress", {"n": 1})
        assert subscription.get_nowait() is None
        assert event["id"] == 1

        subscription.close()
    assert publisher.subscriber_count == 0


def test_concurrent_publishers_produce_unique_monotonic_ids():
    publisher = EventPublisher(history_limit=8)
    threads_count = 8
    per_thread = 50
    collected: list[int] = []
    lock = threading.Lock()

    def worker(thread_index: int):
        for index in range(per_thread):
            event = publisher.publish("job.progress", {"thread": thread_index, "index": index})
            with lock:
                collected.append(event["id"])

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(collected) == list(range(1, threads_count * per_thread + 1))
    retained = publisher.history()
    assert [event["id"] for event in retained] == list(
        range(threads_count * per_thread - 7, threads_count * per_thread + 1)
    )


def test_format_event_uses_compact_single_line_json():
    publisher = EventPublisher()
    event = publisher.publish("job.progress", {"completed": 2, "name": "第一场", "note": "a\nb"})
    framed = format_event(event)
    lines = framed.split("\n")
    assert lines[0] == "id: 1"
    assert lines[1] == "event: job.progress"
    assert lines[2].startswith("data: {")
    assert framed.endswith("\n\n")
    assert "\n" not in lines[2]
    payload = json.loads(lines[2][len("data: ") :])
    assert payload == {"completed": 2, "name": "第一场", "note": "a\nb"}


def test_keepalive_comment_is_valid_sse_comment():
    assert KEEPALIVE_COMMENT == ": keepalive\n\n"
