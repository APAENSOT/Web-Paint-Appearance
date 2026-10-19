"""Turning an authenticated caller into an `app_user` row.

T03 shipped a `Principal` whose `user_id` was always null, because the
application held `SELECT` on `app_user` and not `INSERT`. Revision `0003`
grants the insert; this is the flow that uses it, and it is what makes
`measurement_supersession.actor_user_id NOT NULL` a guarantee rather than an
obstacle.

**Where the upsert runs, and where it does not.** Only routes that need an
attributable identity resolve one: `/api/v1/auth/me`, which the frontend
calls on load, and every write route. A dashboard read does not, because a
`GET` that opens a write transaction to touch `last_seen_at` turns every read
into a write for no gain.

**The cache.** The id is memoised per process, keyed by the Entra object id.
After the first sign-in in a process, attribution costs nothing. The visible
consequence is that `last_seen_at` records the first sight of a person by
*this* process rather than their most recent request -- accurate enough for
"has this account ever been used", which is what the column is for, and
stated here rather than left to be discovered.
"""

from __future__ import annotations

import threading

from fastapi import Request

from app.core.errors import ServiceUnavailable
from app.core.security import Principal
from app.repositories import users


class IdentityCache:
    """Entra object id -> app_user.id, for the life of the process."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, entra_oid: str) -> str | None:
        with self._lock:
            return self._ids.get(entra_oid)

    def put(self, entra_oid: str, user_id: str) -> None:
        with self._lock:
            self._ids[entra_oid] = user_id

    def clear(self) -> None:
        with self._lock:
            self._ids.clear()


def ensure_user(request: Request, principal: Principal) -> Principal:
    """Return the principal with ``user_id`` filled in, creating the row once.

    Raises ``ServiceUnavailable`` rather than returning an unattributed
    principal: a write route that proceeded without an actor would produce
    exactly the gap this work exists to close.
    """
    if principal.user_id:
        return principal
    if not principal.entra_oid:
        raise ServiceUnavailable(
            "This identity carries no stable object id, so it cannot be "
            "recorded as an actor."
        )

    cache: IdentityCache = request.app.state.identity_cache
    cached = cache.get(principal.entra_oid)
    if cached:
        return principal.model_copy(update={"user_id": cached})

    database = request.app.state.database
    with database.begin() as conn:
        user_id = users.upsert(
            conn,
            entra_oid=principal.entra_oid,
            upn=principal.upn,
            display_name=principal.display_name,
        )
    cache.put(principal.entra_oid, user_id)
    return principal.model_copy(update={"user_id": user_id})
