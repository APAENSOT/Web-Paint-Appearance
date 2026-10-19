"""Correlation id per request (`docs/00-ARCHITECTURE.md` section 9).

One id is attached to the request, echoed in the response header, included
in the error body, and put on every log record emitted while the request is
being served. A client that reports "it failed" with an id turns into a
single grep.

A client-supplied `X-Correlation-ID` is honoured so a browser can tie a page
load to several calls -- but it is bounded and stripped of anything that is
not id-shaped, because it lands in log files.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "x-correlation-id"
_SAFE = re.compile(r"[^A-Za-z0-9._:-]")
_MAX_LEN = 64

log = logging.getLogger("app.access")


def _sanitise(raw: str) -> str:
    return _SAFE.sub("", raw)[:_MAX_LEN]


def correlation_id_of(request: Request) -> str:
    return getattr(request.state, "correlation_id", "") or "-"


class CorrelationIdMiddleware:
    """Pure ASGI so it also wraps responses produced by exception handlers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for key, value in scope.get("headers", []):
            if key.decode("latin-1").lower() == HEADER:
                incoming = _sanitise(value.decode("latin-1"))
                break
        cid = incoming or uuid.uuid4().hex
        scope.setdefault("state", {})
        scope["state"]["correlation_id"] = cid

        started = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = message.setdefault("headers", [])
                if not any(k.decode("latin-1").lower() == HEADER for k, _ in headers):
                    headers.append((HEADER.encode(), cid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "%s %s -> %s",
                scope.get("method", "?"),
                scope.get("path", "?"),
                status_holder["status"],
                extra={
                    "correlation_id": cid,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
