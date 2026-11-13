from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from fm27lab.application.events import EventPublisher
from fm27lab.interfaces.http.routes.system import stream_events
from fm27lab.tests.test_http_health import make_app

SSE_HEADERS = {"Accept": "text/event-stream"}


def auth(settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}


def parse_event_frame(block: str) -> dict | None:
    fields: dict = {}
    for line in block.splitlines():
        name, separator, value = line.partition(":")
        if not separator:
            continue
        if value.startswith(" "):
            value = value[1:]
        if name == "id":
            fields["id"] = int(value)
        elif name == "event":
            fields["event"] = value
        elif name == "data":
            fields["data"] = json.loads(value)
    return fields if "event" in fields else None


class FrameReader:
    def __init__(self, chunks) -> None:
        self._chunks = chunks
        self._buffer = ""

    def next(self) -> dict:
        while True:
            while "\n\n" in self._buffer:
                block, self._buffer = self._buffer.split("\n\n", 1)
                frame = parse_event_frame(block)
                if frame is not None:
                    return frame
            self._buffer += next(self._chunks)


def wait_for_subscriber_count(publisher: EventPublisher, expected: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while publisher.subscriber_count != expected and time.monotonic() < deadline:
        time.sleep(0.01)
    assert publisher.subscriber_count == expected, (
        f"subscriber_count 未在 {timeout}s 内达到 {expected}，当前为 {publisher.subscriber_count}"
    )


def test_events_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)

    missing = client.get("/api/events")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"

    wrong = client.get("/api/events", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"


def test_events_stream_sends_ready_event_and_headers(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)

    with client.stream("GET", "/api/events", headers={**auth(settings), **SSE_HEADERS}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        ready = FrameReader(response.iter_text()).next()

    assert ready["event"] == "ready"
    assert ready["data"] == {"api": "fm27lab/v2", "version": settings.version}


def test_last_event_id_replays_newer_events_in_order(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    publisher = EventPublisher()
    for number in (1, 2, 3, 4, 5):
        publisher.publish("job.progress", {"n": number})
    app.state.events = publisher
    client = TestClient(app)

    headers = {**auth(settings), "Last-Event-ID": "2"}
    with client.stream("GET", "/api/events", headers=headers) as response:
        reader = FrameReader(response.iter_text())
        frames = [reader.next() for _ in range(4)]

    assert [frame["event"] for frame in frames] == [
        "ready",
        "job.progress",
        "job.progress",
        "job.progress",
    ]
    assert [frame["id"] for frame in frames[1:]] == [3, 4, 5]
    assert [frame["data"]["n"] for frame in frames[1:]] == [3, 4, 5]


def test_replay_and_live_overlap_is_deduplicated_without_loss():
    publisher = EventPublisher()
    for number in range(1, 21):
        publisher.publish("job.progress", {"n": number})

    async def scenario() -> list[str]:
        stream = stream_events(
            publisher,
            20,
            api="fm27lab/v2",
            version="2.0.0.dev0",
            keepalive_seconds=0.05,
        )
        try:
            ready = parse_event_frame(await anext(stream))
            assert ready is not None
            assert ready["id"] == 20
            for number in (21, 22, 23):
                publisher.publish("job.progress", {"n": number})
            frames = [await anext(stream) for _ in range(3)]
            publisher.publish("job.progress", {"n": 24})
            frames.append(await anext(stream))
            return frames
        finally:
            await stream.aclose()

    frames = [parse_event_frame(frame) for frame in asyncio.run(scenario())]
    assert all(frame is not None for frame in frames)
    assert [frame["id"] for frame in frames] == [21, 22, 23, 24]
    assert [frame["data"]["n"] for frame in frames] == [21, 22, 23, 24]


def test_live_event_is_pushed_with_sse_framing_and_fresh_clients_skip_history(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    publisher = EventPublisher()
    for number in (1, 2, 3):
        publisher.publish("job.progress", {"n": number})
    app.state.events = publisher
    client = TestClient(app)

    with client.stream("GET", "/api/events", headers={**auth(settings), **SSE_HEADERS}) as response:
        chunks = response.iter_text()
        reader = FrameReader(chunks)
        ready = reader.next()
        assert ready["event"] == "ready"

        event = publisher.publish("job.progress", {"completed": 1, "name": "第一场"})
        raw = next(chunks)

    assert raw == (f'id: {event["id"]}\nevent: job.progress\ndata: {{"completed":1,"name":"第一场"}}\n\n')
    frame = parse_event_frame(raw)
    assert frame is not None
    assert frame["id"] == 4
    assert frame["data"] == {"completed": 1, "name": "第一场"}


def test_keepalive_comment_is_sent_on_configured_interval(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    app.state.events = EventPublisher()
    app.state.event_keepalive_seconds = 0.05
    client = TestClient(app)

    with client.stream("GET", "/api/events", headers={**auth(settings), **SSE_HEADERS}) as response:
        chunks = response.iter_text()
        reader = FrameReader(chunks)
        assert reader.next()["event"] == "ready"

        keepalive = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            chunk = next(chunks)
            if chunk == ": keepalive\n\n":
                keepalive = chunk
                break

    assert keepalive == ": keepalive\n\n"


def test_client_disconnect_unregisters_subscriber(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    publisher = EventPublisher()
    app.state.events = publisher
    client = TestClient(app)

    with client.stream("GET", "/api/events", headers={**auth(settings), **SSE_HEADERS}) as response:
        assert FrameReader(response.iter_text()).next()["event"] == "ready"
        wait_for_subscriber_count(publisher, 1)
        assert publisher.subscriber_count == 1

    wait_for_subscriber_count(publisher, 0)
    assert publisher.subscriber_count == 0


def test_ready_cursor_is_clamped_when_last_event_id_is_ahead(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    publisher = EventPublisher()
    for number in (1, 2, 3, 4, 5):
        publisher.publish("job.progress", {"n": number})
    app.state.events = publisher
    client = TestClient(app)

    # after_id 超前时 ready 游标钳制到最后事件 id；实时事件从 last_id+1 继续，故 id ≤ after_id 仍可能到达。
    headers = {**auth(settings), "Last-Event-ID": "20"}
    with client.stream("GET", "/api/events", headers=headers) as response:
        reader = FrameReader(response.iter_text())
        ready = reader.next()
        assert ready["event"] == "ready"
        assert ready["id"] == 5

        next_event = publisher.publish("job.progress", {"n": 6})
        frame = reader.next()

    assert frame["id"] == next_event["id"] == 6
    assert frame["id"] <= 20


def test_invalid_last_event_id_is_rejected(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.get(
        "/api/events",
        headers={**auth(settings), "Last-Event-ID": "not-a-number"},
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_last_event_id"


def test_events_cors_preflight_and_method_not_allowed_do_not_regress(tmp_path: Path):
    app, _, _, _ = make_app(tmp_path)
    client = TestClient(app)

    preflight = client.options(
        "/api/events",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Last-Event-ID",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:1420"
    allowed = preflight.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "last-event-id" in allowed

    method = client.delete("/api/events")
    assert method.status_code == 405
    assert method.json()["error"]["code"] == "method_not_allowed"
