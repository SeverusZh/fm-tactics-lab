from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from fm27lab.application.idempotency import IdempotencyConflict, IdempotencyService
from fm27lab.interfaces.http.common import error_body, require_token

IDEMPOTENCY_HEADER = "Idempotency-Key"
WRITE_METHODS = frozenset({"POST", "PATCH", "DELETE"})
API_PREFIX = "/api/"
JSON_MEDIA_TYPE = "application/json"
INVALID_KEY_CODE = "invalid_idempotency_key"
CONFLICT_CODE = "idempotency_conflict"
CONFLICT_MESSAGE = "幂等键已被不同载荷使用"
NO_CONTENT = 204


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, service: IdempotencyService) -> None:
        super().__init__(app)
        self.service = service
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, int] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._applies(request):
            return await call_next(request)
        key = request.headers.get(IDEMPOTENCY_HEADER)
        if key is None:
            return await call_next(request)
        unauthorized = self._authorize(request)
        if unauthorized is not None:
            return unauthorized
        body = await request.body()
        digest = self.service.fingerprint(
            request.method,
            request.url.path,
            request.scope.get("query_string", b""),
            body,
        )
        lock = self._reserve(key)
        try:
            async with lock:
                return await self._dispatch_keyed(request, call_next, key, digest)
        finally:
            self._release(key)

    async def _dispatch_keyed(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
        key: str,
        digest: str,
    ) -> Response:
        try:
            snapshot = await run_in_threadpool(self.service.lookup, key, digest)
        except IdempotencyConflict:
            return _conflict_response()
        except ValueError as error:
            return _invalid_key_response(error)
        if snapshot is not None:
            return _replay_response(snapshot)
        response = await call_next(request)
        payload = await _consume_body(response)
        rebuilt = _rebuild_response(response, payload)
        if 200 <= response.status_code < 300:
            conflict = await self._store_response(key, digest, response, payload)
            if conflict is not None:
                return conflict
        return rebuilt

    async def _store_response(
        self,
        key: str,
        digest: str,
        response: Response,
        payload: bytes,
    ) -> Response | None:
        if not _is_complete_response(response, payload):
            return None
        content_type = response.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        is_json = media_type == JSON_MEDIA_TYPE or media_type.endswith("+json")
        if not (is_json or (not content_type and not payload)):
            return None
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
        snapshot = {"status": response.status_code, "body": text, "content_type": content_type}
        try:
            await run_in_threadpool(self.service.store, key, digest, snapshot)
        except IdempotencyConflict:
            return _conflict_response()
        except ValueError:
            # 快照序列化或大小上限校验失败时放弃缓存，已执行的响应不受影响。
            return None
        return None

    def _reserve(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        self._waiters[key] = self._waiters.get(key, 0) + 1
        return lock

    def _release(self, key: str) -> None:
        remaining = self._waiters.get(key, 1) - 1
        if remaining <= 0:
            self._waiters.pop(key, None)
            self._locks.pop(key, None)
        else:
            self._waiters[key] = remaining

    @staticmethod
    def _applies(request: Request) -> bool:
        return request.method in WRITE_METHODS and request.url.path.startswith(API_PREFIX)

    @staticmethod
    def _authorize(request: Request) -> Response | None:
        header = request.headers.get("authorization")
        credentials = None
        if header is not None:
            scheme, _, value = header.partition(" ")
            credentials = HTTPAuthorizationCredentials(scheme=scheme, credentials=value)
        try:
            require_token(request, credentials)
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {}
            payload = {
                "error": {
                    "code": detail.get("code", "unauthorized"),
                    "message": detail.get("message", "unauthorized"),
                    "details": detail.get("details"),
                    "retriable": detail.get("retriable", False),
                    "retry_after_seconds": detail.get("retry_after_seconds"),
                }
            }
            return JSONResponse(
                status_code=error.status_code,
                content=payload,
                headers=dict(error.headers or {}),
            )
        return None


async def _consume_body(response: Response) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else bytes(chunk))
    return b"".join(chunks)


def _is_complete_response(response: Response, payload: bytes) -> bool:
    if response.status_code == NO_CONTENT:
        return not payload
    declared = response.headers.get("content-length")
    if declared is None:
        return False
    try:
        length = int(declared)
    except ValueError:
        return False
    return length >= 0 and length == len(payload)


def _rebuild_response(response: Response, payload: bytes) -> Response:
    rebuilt = Response(content=payload, status_code=response.status_code)
    rebuilt.raw_headers = list(response.raw_headers)
    return rebuilt


def _replay_response(snapshot: dict[str, Any]) -> Response:
    # 快照契约仅保存 status/body/content_type，重放不还原其余响应头（如 Set-Cookie）。
    body = snapshot["body"].encode("utf-8")
    headers = {}
    if snapshot["content_type"]:
        headers["content-type"] = snapshot["content_type"]
    return Response(content=body, status_code=snapshot["status"], headers=headers)


def _invalid_key_response(error: ValueError) -> JSONResponse:
    message = str(error) or "幂等键无效"
    return JSONResponse(
        status_code=400,
        content=error_body(INVALID_KEY_CODE, message, 400),
    )


def _conflict_response() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=error_body(CONFLICT_CODE, CONFLICT_MESSAGE, 409),
    )
