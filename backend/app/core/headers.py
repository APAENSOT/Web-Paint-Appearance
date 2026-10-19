"""Response hardening headers (`03-SECURITY.md` section 7, "Helmet-equivalent").

The API returns JSON, never HTML, so the set is small and boring on purpose.
HSTS is sent only outside development: emitting it on `http://localhost`
pins a browser to HTTPS for localhost and breaks the next developer's day.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

BASE_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"cross-origin-resource-policy": b"same-site",
}
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        self.app = app
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}
                for key, value in BASE_HEADERS.items():
                    if key not in present:
                        headers.append((key, value))
                if self.production and HSTS[0] not in present:
                    headers.append(HSTS)
            await send(message)

        await self.app(scope, receive, send_wrapper)
