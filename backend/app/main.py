"""FastAPI application factory.

Read `docs/tasks/T03-api-contract.md` and `docs/00-ARCHITECTURE.md` sections
4-5 before changing anything here. The shape this file publishes is what the
frontend is generated from, so a rename is a breaking change for another
agent, not a refactor.

What this build does and does not do:

* **Reads** health, identity, reference data, active measurements, and raw
  CF for plotting.
* **Writes** through the RBAC matrix routes, including Admin catalogue mint
  and append-only `POST /standards` (plant-scoped D2). `reserved.py` is empty.
  D1 stays open: `grading_available` remains false.
* **Authenticates** through `AUTH_DEV_BYPASS` (only when `ENV=development`)
  or, in this no-sign-in release, `AUTH_OPEN_ACCESS` (one shared account).
  Otherwise a bearer token is refused rather than trusted unverified.
* **Serves** the built frontend too when `STATIC_DIR` is set (`core/spa.py`).
* **Connects** as `app_rw`, and refuses to serve data through any connection
  that turns out to hold DELETE or UPDATE on `wavescan` (`core/db.py`).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES

from app.api import health
from app.api.v1 import router as v1_router
from app.api.v1.comparison import install_openapi_examples
from app.core.config import Settings, get_settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.db import Database
from app.core.identity import IdentityCache
from app.core.errors import install_error_handlers
from app.core.headers import SecurityHeadersMiddleware
from app.core.logging import configure_logging
from app.core.spa import mount_spa
from app.schemas.common import ErrorResponse  # noqa: F401 - re-exported below
from app.services.ingest import IngestService
from app.services.corrections import CorrectionService
from app.services.mapping import MappingService
from app.services.raw_store import RawStore
from app.workers.ingest_worker import IngestWorker

log = logging.getLogger("app")

DESCRIPTION = """
WaveScan paint-appearance API (slice 1).

Monthly Overview returns one PASS / WARNING / FAIL (or ungraded) per
model, colour and orientation mean, using `status_of` and stored
`cf_standard` rows. That grain is not a product pass rate. D1 stays
open. `grading_available` on meta and preview stays false. A client
that averages preview points or computes a status locally is inventing
an answer this platform has not made.

**Facts are immutable.** Measurements are never updated or deleted (ADR 0005).
Corrections are new rows; retirement is recorded, never applied in place.

Errors always have the shape `{statusCode, error, message, correlationId}`.
"""

#: Attached to every route so the generated client knows the error shape.
COMMON_RESPONSES: dict = {
    401: {"model": ErrorResponse, "description": "Not authenticated."},
    403: {"model": ErrorResponse, "description": "Authenticated, but the role is insufficient."},
    422: {"model": ErrorResponse, "description": "Request validation failed."},
    500: {"model": ErrorResponse, "description": "Unexpected error; quote correlationId."},
    503: {"model": ErrorResponse, "description": "A dependency (database) is unavailable."},
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # The identity guard runs on the first connection rather than here:
        # a database that is briefly unreachable must not stop the process
        # from starting and reporting itself unready.
        log.info("api starting", extra={"detail": f"env={settings.env}"})
        if settings.auth_open_access:
            log.warning("open access: no sign-in, every request acts as the shared account",
                        extra={"detail": settings.auth_open_access_upn})
        worker: IngestWorker | None = None
        if settings.ingest_worker_enabled:
            # One machine, thirty users (00-ARCHITECTURE.md §1), so the worker
            # runs in this process by default. It claims jobs with SKIP
            # LOCKED, so running `python -m app.workers.ingest_worker`
            # alongside is safe and needs no coordination.
            worker = IngestWorker(
                app.state.database,
                app.state.ingest_service,
                settings.ingest_worker_poll_seconds,
            )
            worker.start()
        app.state.ingest_worker = worker
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()
            app.state.database.dispose()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
        responses=COMMON_RESPONSES,
    )
    app.state.settings = settings
    app.state.database = Database(settings)
    app.state.identity_cache = IdentityCache()
    app.state.raw_store = RawStore(settings.raw_store_path)
    # One parser, shared by the HTTP routes and the worker
    # (02-PIPELINE.md §10: "Two parsers = drift").
    app.state.ingest_service = IngestService(settings, app.state.raw_store)
    # T08's approve route replays through that same service rather than
    # carrying a parser of its own.
    app.state.mapping_service = MappingService(app.state.ingest_service)
    # ADR 0005's two write paths. Deliberately not part of the ingest
    # service: a commit must not be able to reach a supersede
    # (02-PIPELINE.md section 3, T04 report section 9).
    app.state.correction_service = CorrectionService()

    # JSON lists here run to hundreds of KB; level 5 keeps most of the
    # saving at a fraction of level 9's CPU. Under 1 KB is not worth it.
    # Spreadsheets are zip files already: compressing them again is CPU for nothing.
    app.add_middleware(
        GZipMiddleware, minimum_size=1024, compresslevel=5,
        exclude_content_types=DEFAULT_EXCLUDED_CONTENT_TYPES + (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.oasis.opendocument.spreadsheet",
        ),
    )
    # Order matters: CORS outermost so a rejected preflight still gets its
    # headers, then correlation id so every log line and error body has one.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, production=not settings.is_development)
    app.add_middleware(CorrelationIdMiddleware)

    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(v1_router)
    install_openapi_examples(app)
    if settings.static_dir.strip():
        # Last: the catch-all must never shadow an API route.
        mount_spa(app, Path(settings.static_dir))
    return app


app = create_app()
