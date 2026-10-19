"""Liveness and readiness (`00-ARCHITECTURE.md` section 9).

`/health/live` answers "is this process running" and touches nothing. It
must stay true when the database is down, otherwise an orchestrator
restarts a healthy API because PostgreSQL blinked.

`/health/ready` answers "should traffic be sent here" and reports each
dependency by name -- the database and, since T04, the raw object store. It
also republishes the database identity guard's verdict, so "the API holds no
DELETE on wavescan" is something an operator can curl rather than something a
report claims.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

router = APIRouter(tags=["health"])


@router.get("/health/live", summary="Liveness: the process is up. No dependencies checked.")
def live(request: Request) -> dict:
    settings = request.app.state.settings
    return {"status": "alive", "service": settings.api_title, "version": settings.api_version}


@router.get("/health/ready", summary="Readiness: dependencies checked by name.")
def ready(request: Request, response: Response) -> dict:
    database = request.app.state.database
    db_check = database.check()

    # T04 gave this process an object store, so readiness stops saying
    # "not_configured" and starts actually checking it: a batch whose bytes
    # cannot be read back can be neither replayed nor committed, and that is
    # exactly the failure an operator wants to see before users do.
    store_check = request.app.state.raw_store.health()

    checks = {"database": db_check, "object_store": store_check}
    ready_now = (
        db_check.get("status") == "ok" and store_check.get("status") == "ok"
    )
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready_now else "not_ready", "checks": checks}
