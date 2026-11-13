from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
SECURITY = HTTPBearer(auto_error=False)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None
    retriable: bool
    retry_after_seconds: int | float | None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def error_body(code: str, message: str, status: int) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": None,
            "retriable": status >= 500 or status == 409,
            "retry_after_seconds": None,
        }
    }


def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(SECURITY)] = None,
) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "missing bearer token", "retriable": False},
            headers={"WWW-Authenticate": "Bearer"},
        )
    supplied = credentials.credentials.strip()
    expected = request.app.state.settings.token
    if not supplied or not supplied.isascii() or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "invalid bearer token", "retriable": False},
            headers={"WWW-Authenticate": "Bearer"},
        )


def _query_integer(value: str, name: str, low: int, high: int) -> int:
    if not value.isascii() or not value.isdigit():
        raise ValueError(f"{name} 必须为 {low}–{high} 的整数")
    number = int(value)
    if not low <= number <= high:
        raise ValueError(f"{name} 必须为 {low}–{high} 的整数")
    return number
