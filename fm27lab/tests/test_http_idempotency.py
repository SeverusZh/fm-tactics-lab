from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import Response
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from fm27lab.interfaces.http.app import create_app
from fm27lab.tests.test_http_drafts import body as draft_payload
from fm27lab.tests.test_http_health import make_app

ERROR_FIELDS = {"code", "message", "details", "retriable", "retry_after_seconds"}
KEY_HEADER = "Idempotency-Key"
SHA256 = "a" * 64


def auth(settings) -> dict:
    return {"Authorization": f"Bearer {settings.token}"}


def keyed(settings, key: str, **extra: str) -> dict:
    headers = auth(settings)
    headers[KEY_HEADER] = key
    headers.update(extra)
    return headers


def pool_payload(name: str = "Corner") -> dict:
    return {"name": name, "weight": 2, "tactic": {"tactic_name": "角球"}, "roster": {"club_uid": 7}}


def job_payload() -> dict:
    return {
        "kind": "experiment",
        "name": "Experiment",
        "config": {"seeds": [1, 2]},
        "workers": 2,
        "total": 4,
    }


def save_payload() -> dict:
    return {"source_path": "/saves/season-1.fm", "source_sha256": SHA256}


def stored_rows(app) -> int:
    return app.state.idempotency.repository.count()


def test_post_pool_replays_first_response_and_keeps_single_row(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = keyed(settings, "pool-once")
    first = client.post("/api/pools", json=pool_payload(), headers=headers)
    second = client.post("/api/pools", json=pool_payload(), headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert first.headers["content-type"] == second.headers["content-type"] == "application/json"
    assert first.headers["content-length"] == second.headers["content-length"]
    assert stored_rows(app) == 1
    assert client.get("/api/pools", headers=auth(settings)).json()["total"] == 1


def test_same_key_with_different_payload_returns_conflict(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = keyed(settings, "pool-conflict")
    created = client.post("/api/pools", json=pool_payload("Corner"), headers=headers)
    assert created.status_code == 201
    conflict = client.post("/api/pools", json=pool_payload("FreeKick"), headers=headers)
    assert conflict.status_code == 409
    error = conflict.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "idempotency_conflict"
    assert error["message"] == "幂等键已被不同载荷使用"
    assert stored_rows(app) == 1
    listed = client.get("/api/pools", headers=auth(settings)).json()
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "Corner"


def test_request_without_key_executes_every_time(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = auth(settings)
    first = client.post("/api/pools", json=pool_payload("One"), headers=headers)
    second = client.post("/api/pools", json=pool_payload("One"), headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert stored_rows(app) == 0
    assert client.get("/api/pools", headers=headers).json()["total"] == 2


def test_patch_and_delete_replay_without_repeating_effects(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    created = client.post("/api/drafts", json=draft_payload("Draft"), headers=auth(settings))
    assert created.status_code == 201
    draft_id = created.json()["id"]
    patch_headers = keyed(settings, "draft-patch")
    first_patch = client.patch(f"/api/drafts/{draft_id}", json={"name": "Renamed"}, headers=patch_headers)
    second_patch = client.patch(f"/api/drafts/{draft_id}", json={"name": "Renamed"}, headers=patch_headers)
    assert first_patch.status_code == second_patch.status_code == 200
    assert first_patch.json() == second_patch.json()
    assert stored_rows(app) == 1
    conflict = client.patch(f"/api/drafts/{draft_id}", json={"name": "Other"}, headers=patch_headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    delete_headers = keyed(settings, "draft-delete")
    first_delete = client.delete(f"/api/drafts/{draft_id}", headers=delete_headers)
    second_delete = client.delete(f"/api/drafts/{draft_id}", headers=delete_headers)
    assert first_delete.status_code == second_delete.status_code == 204
    assert first_delete.content == second_delete.content == b""
    assert "content-type" not in second_delete.headers
    assert stored_rows(app) == 2
    assert client.get(f"/api/drafts/{draft_id}", headers=auth(settings)).status_code == 404


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        pytest.param("/api/pools", pool_payload(), id="pools"),
        pytest.param("/api/drafts", draft_payload("Routed"), id="drafts"),
        pytest.param("/api/jobs", job_payload(), id="jobs"),
        pytest.param("/api/saves", save_payload(), id="saves"),
    ],
)
def test_write_routes_replay_and_store_single_row(tmp_path: Path, path: str, payload: dict):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = keyed(settings, "route-once")
    first = client.post(path, json=payload, headers=headers)
    second = client.post(path, json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert stored_rows(app) == 1


def test_shutdown_replays_without_second_call(tmp_path: Path):
    app, settings, stopped, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = keyed(settings, "shutdown-once")
    first = client.post("/api/shutdown", headers=headers)
    second = client.post("/api/shutdown", headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert stopped == [True]
    assert stored_rows(app) == 1


def test_get_head_and_options_ignore_idempotency_key(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    client.post("/api/pools", json=pool_payload(), headers=auth(settings))
    get_headers = keyed(settings, "read-key")
    assert client.get("/api/pools", headers=get_headers).status_code == 200
    assert client.get("/api/pools", headers=get_headers).status_code == 200
    head_headers = {KEY_HEADER: "bad key"}
    assert client.head("/api/pools", headers=head_headers).status_code == 405
    assert client.head("/api/pools", headers=head_headers).status_code == 405
    preflight = client.options(
        "/api/pools",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": KEY_HEADER,
        },
    )
    assert preflight.status_code == 200
    assert stored_rows(app) == 0


def test_invalid_idempotency_key_returns_400_and_skips_route(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    for invalid in ("", "bad key", "a/b", "k" * 129):
        response = client.post("/api/pools", json=pool_payload(), headers=keyed(settings, invalid))
        assert response.status_code == 400, invalid
        error = response.json()["error"]
        assert set(error) == ERROR_FIELDS
        assert error["code"] == "invalid_idempotency_key"
        assert error["message"] == "幂等键无效"
    assert stored_rows(app) == 0
    assert client.get("/api/pools", headers=auth(settings)).json()["total"] == 0


def test_auth_failure_is_not_cached(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    body = pool_payload()
    denied = client.post(
        "/api/pools",
        json=body,
        headers={KEY_HEADER: "auth-once", "Authorization": "Bearer wrong"},
    )
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    assert denied.json()["error"]["code"] == "unauthorized"
    assert stored_rows(app) == 0
    allowed = client.post("/api/pools", json=body, headers=keyed(settings, "auth-once"))
    assert allowed.status_code == 201
    assert stored_rows(app) == 1


def test_cached_replay_requires_bearer_token(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = keyed(settings, "replay-auth")
    created = client.post("/api/pools", json=pool_payload(), headers=headers)
    assert created.status_code == 201
    denied = client.post("/api/pools", json=pool_payload(), headers={KEY_HEADER: "replay-auth"})
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    error = denied.json()["error"]
    assert set(error) == ERROR_FIELDS
    assert error["code"] == "unauthorized"
    wrong_token = client.post(
        "/api/pools",
        json=pool_payload(),
        headers={KEY_HEADER: "replay-auth", "Authorization": "Bearer wrong"},
    )
    assert wrong_token.status_code == 401
    assert wrong_token.json()["error"]["code"] == "unauthorized"
    replayed = client.post("/api/pools", json=pool_payload(), headers=headers)
    assert replayed.status_code == 201
    assert replayed.json() == created.json()
    assert stored_rows(app) == 1


def test_client_errors_are_not_cached_and_retry_can_succeed(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    invalid_payload = {"name": "", "weight": 1, "tactic": {}}
    headers = keyed(settings, "bad-payload")
    first = client.post("/api/pools", json=invalid_payload, headers=headers)
    second = client.post("/api/pools", json=invalid_payload, headers=headers)
    assert first.status_code == second.status_code == 400
    assert first.json()["error"]["code"] == "validation_failed"
    assert stored_rows(app) == 0
    retried = client.post("/api/pools", json=pool_payload(), headers=headers)
    assert retried.status_code == 201
    assert stored_rows(app) == 1
    assert client.get("/api/pools", headers=auth(settings)).json()["total"] == 1


def test_csv_and_binary_responses_are_not_cached(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    calls = {"csv": 0, "empty": 0, "binary": 0}

    @app.post("/api/exports/csv")
    def export_csv():
        calls["csv"] += 1
        return Response("rank,points\n1,90", media_type="text/csv")

    @app.post("/api/exports/empty")
    def export_empty():
        calls["empty"] += 1
        return Response(b"", media_type="text/csv")

    @app.post("/api/exports/binary")
    def export_binary():
        calls["binary"] += 1
        return Response(b"\x00\x01\x02", media_type="application/octet-stream")

    csv_headers = keyed(settings, "export-csv")
    first_csv = client.post("/api/exports/csv", headers=csv_headers)
    second_csv = client.post("/api/exports/csv", headers=csv_headers)
    assert first_csv.status_code == second_csv.status_code == 200
    assert first_csv.content == second_csv.content == b"rank,points\n1,90"
    assert second_csv.headers["content-type"] == "text/csv; charset=utf-8"
    empty_headers = keyed(settings, "export-empty")
    first_empty = client.post("/api/exports/empty", headers=empty_headers)
    second_empty = client.post("/api/exports/empty", headers=empty_headers)
    assert first_empty.status_code == second_empty.status_code == 200
    assert first_empty.content == second_empty.content == b""
    binary_headers = keyed(settings, "export-binary")
    first_binary = client.post("/api/exports/binary", headers=binary_headers)
    second_binary = client.post("/api/exports/binary", headers=binary_headers)
    assert first_binary.content == second_binary.content == b"\x00\x01\x02"
    assert second_binary.headers["content-type"] == "application/octet-stream"
    assert calls == {"csv": 2, "empty": 2, "binary": 2}
    assert stored_rows(app) == 0


def test_method_not_allowed_and_unhandled_errors_keep_envelopes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    wrong_member = client.post("/api/pools/missing", headers=keyed(settings, "method-key"))
    assert wrong_member.status_code == 405
    assert "GET" in wrong_member.headers["allow"] and "DELETE" in wrong_member.headers["allow"]
    assert wrong_member.json()["error"]["code"] == "method_not_allowed"

    class ExplodingJobs:
        def create(self, *args, **kwargs):
            raise RuntimeError("secret detail")

    second_app = create_app(settings, app.state.database, job_service=ExplodingJobs())
    crashed = TestClient(second_app, raise_server_exceptions=False).post(
        "/api/jobs",
        json=job_payload(),
        headers=auth(settings) | {KEY_HEADER: "exploding-job"},
    )
    assert crashed.status_code == 500
    assert crashed.json()["error"]["code"] == "internal_error"
    assert "secret detail" not in crashed.text
    assert second_app.state.idempotency.repository.count() == 0


def test_replay_keeps_cors_headers(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = keyed(settings, "cors-key", Origin="tauri://localhost")
    first = client.post("/api/pools", json=pool_payload(), headers=headers)
    second = client.post("/api/pools", json=pool_payload(), headers=headers)
    assert first.status_code == second.status_code == 201
    assert second.headers["access-control-allow-origin"] == "tauri://localhost"
    assert second.json() == first.json()


def test_truncated_streaming_response_is_not_cached(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    attempts = []

    @app.post("/api/stream/retry")
    async def stream_retry():
        attempts.append(1)
        if len(attempts) == 1:

            async def broken():
                yield b'{"items":['
                raise RuntimeError("stream failed")

            return StreamingResponse(broken(), media_type="application/json")
        return {"attempts": len(attempts)}

    client = TestClient(app, raise_server_exceptions=False)
    headers = keyed(settings, "stream-retry")
    first = client.post("/api/stream/retry", headers=headers)
    assert first.status_code == 200
    assert first.content == b'{"items":['
    assert stored_rows(app) == 0
    second = client.post("/api/stream/retry", headers=headers)
    assert second.status_code == 200
    assert second.json() == {"attempts": 2}
    assert stored_rows(app) == 1
    replay = client.post("/api/stream/retry", headers=headers)
    assert replay.status_code == 200
    assert replay.content == second.content
    assert len(attempts) == 2


def test_oversized_json_response_is_not_cached(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    calls = []

    @app.post("/api/exports/large")
    def export_large():
        calls.append(1)
        return {"payload": "x" * 1_048_576}

    client = TestClient(app)
    headers = keyed(settings, "large-json")
    first = client.post("/api/exports/large", headers=headers)
    second = client.post("/api/exports/large", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls == [1, 1]
    assert stored_rows(app) == 0


def test_concurrent_same_key_executes_once(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    calls = []
    started = asyncio.Event()
    release = asyncio.Event()

    @app.post("/api/slow")
    async def slow_route():
        calls.append(1)
        started.set()
        await release.wait()
        return {"calls": len(calls)}

    async def scenario():
        headers = keyed(settings, "concurrent-once")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first = asyncio.create_task(client.post("/api/slow", json={"value": 1}, headers=headers))
            await started.wait()
            second = asyncio.create_task(client.post("/api/slow", json={"value": 1}, headers=headers))
            await asyncio.sleep(0.05)
            release.set()
            return await asyncio.wait_for(asyncio.gather(first, second), timeout=15)

    first, second = asyncio.run(scenario())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"calls": 1}
    assert calls == [1]
    assert stored_rows(app) == 1


def test_concurrent_different_payload_conflicts_before_execution(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    calls = []
    started = asyncio.Event()
    release = asyncio.Event()

    @app.post("/api/slow-conflict")
    async def slow_conflict():
        calls.append(1)
        started.set()
        await release.wait()
        return {"calls": len(calls)}

    async def scenario():
        headers = keyed(settings, "concurrent-conflict")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first = asyncio.create_task(client.post("/api/slow-conflict", json={"value": 1}, headers=headers))
            await started.wait()
            second = asyncio.create_task(
                client.post("/api/slow-conflict", json={"value": 2}, headers=headers)
            )
            await asyncio.sleep(0.05)
            release.set()
            return await asyncio.wait_for(asyncio.gather(first, second), timeout=15)

    first, second = asyncio.run(scenario())
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    conflict = first if first.status_code == 409 else second
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert calls == [1]
    assert stored_rows(app) == 1


def test_unauthenticated_requests_cannot_probe_key_state(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    created = client.post("/api/pools", json=pool_payload("Corner"), headers=keyed(settings, "probe-key"))
    assert created.status_code == 201
    same_payload = client.post("/api/pools", json=pool_payload("Corner"), headers={KEY_HEADER: "probe-key"})
    assert same_payload.status_code == 401
    assert same_payload.json()["error"]["code"] == "unauthorized"
    different_payload = client.post(
        "/api/pools", json=pool_payload("Other"), headers={KEY_HEADER: "probe-key"}
    )
    assert different_payload.status_code == 401
    invalid_key = client.post("/api/pools", json=pool_payload(), headers={KEY_HEADER: "bad key"})
    assert invalid_key.status_code == 401
    assert stored_rows(app) == 1
    assert client.get("/api/pools", headers=auth(settings)).json()["total"] == 1


def test_rebuilt_response_keeps_duplicate_headers(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)

    @app.post("/api/headers")
    def header_route():
        response = Response('{"ok":true}', media_type="application/json")
        response.raw_headers.append((b"set-cookie", b"first=1; Path=/"))
        response.raw_headers.append((b"set-cookie", b"second=2; Path=/"))
        return response

    client = TestClient(app)
    headers = keyed(settings, "headers-key")
    first = client.post("/api/headers", headers=headers)
    assert first.status_code == 200
    assert first.headers.get_list("set-cookie") == ["first=1; Path=/", "second=2; Path=/"]
    replayed = client.post("/api/headers", headers=headers)
    assert replayed.json() == {"ok": True}
    assert "set-cookie" not in replayed.headers
    assert stored_rows(app) == 1


def test_query_reordering_and_trailing_separator_replay(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = keyed(settings, "query-key")
    first = client.post("/api/pools?limit=2&offset=0", json=pool_payload(), headers=headers)
    second = client.post("/api/pools?offset=0&limit=2&", json=pool_payload(), headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert stored_rows(app) == 1


def test_same_key_across_paths_conflicts(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    client = TestClient(app)
    headers = keyed(settings, "global-key")
    created = client.post("/api/pools", json=pool_payload(), headers=headers)
    assert created.status_code == 201
    conflict = client.post("/api/jobs", json=job_payload(), headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert client.get("/api/jobs", headers=auth(settings)).json()["total"] == 0
    assert stored_rows(app) == 1


def test_server_error_is_not_cached_and_retry_executes(tmp_path: Path):
    app, settings, _, _ = make_app(tmp_path)
    calls = []

    @app.post("/api/flaky")
    def flaky_route():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first attempt fails")
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    headers = keyed(settings, "flaky-key")
    failed = client.post("/api/flaky", headers=headers)
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "internal_error"
    assert stored_rows(app) == 0
    retried = client.post("/api/flaky", headers=headers)
    assert retried.status_code == 200
    assert retried.json() == {"ok": True}
    assert calls == [1, 1]
    assert stored_rows(app) == 1
    replay = client.post("/api/flaky", headers=headers)
    assert replay.json() == retried.json()
    assert calls == [1, 1]
