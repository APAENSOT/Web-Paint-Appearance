"""Read-only landing status for the four plant cards and the feed sidebar."""

from __future__ import annotations

import time
from datetime import datetime
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ActiveScope, DbConnection
from app.core.security import CurrentPrincipal
from app.schemas.landing import LandingStatusOut
from app.services import landing as service

router = APIRouter(prefix="/landing", tags=["landing"])

# The home page's summary costs ~90 queries. Every visitor in the same 30 s
# gets the same answer (the frontend reuses reads for 30 s too).
# shortcut: per-process cache; with several Cloud Run instances each keeps
# its own, which is fine for a 30 s summary. Move to a shared cache if it
# ever has to be exact right after an upload.
CACHE_SECONDS = 30.0
_cache: dict[tuple[str, ...] | None, tuple[float, LandingStatusOut]] = {}
_cache_lock = Lock()


@router.get("/status", response_model=LandingStatusOut,
            summary="Plant cards: month-to-date quality, weekly feed, cars and latest files.")
def landing_status(
    principal: CurrentPrincipal,
    conn: DbConnection,
    scope: ActiveScope,
    as_of: Annotated[datetime | None, Query(
        description="Evaluate as of this moment (testing and replay). Default: now.")] = None,
) -> LandingStatusOut:
    if as_of is not None:  # testing and replay: always computed fresh
        when = as_of if as_of.tzinfo is not None else as_of.astimezone()
        return LandingStatusOut(**service.status(conn, scope.plant_scope, when))
    key = tuple(scope.plant_scope) if scope.plant_scope is not None else None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = LandingStatusOut(**service.status(conn, scope.plant_scope, service.today()))
    with _cache_lock:
        _cache[key] = (now, result)
    return result
