from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque

from fastapi import Request


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str) -> deque[float]:
        failures = self._failures[key]
        threshold = time.monotonic() - self.window_seconds
        while failures and failures[0] < threshold:
            failures.popleft()
        return failures

    def is_blocked(self, key: str) -> bool:
        return len(self._trim(key)) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        self._trim(key).append(time.monotonic())

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def is_authenticated(request: Request) -> bool:
    return request.session.get("admin_authenticated") is True


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def valid_csrf(request: Request, token: str) -> bool:
    expected = request.session.get("csrf_token", "")
    return bool(expected and token and secrets.compare_digest(expected, token))
