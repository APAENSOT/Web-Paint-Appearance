"""The ingest worker.

`02-PIPELINE.md` §1 puts parsing behind a queue, and §9 says how the queue is
claimed: `SELECT ... FOR UPDATE SKIP LOCKED`, no broker. This is that loop.

**Why a worker and not parsing in the request.** The T04 brief allows
synchronous parsing for slice 1 "only if a worker is genuinely too heavy".
It is not: the queue is one table, the claim is one statement, and the loop
below is under a hundred lines. What it buys is the thing the request path
cannot offer -- a 40-file upload returns immediately instead of holding an
HTTP connection open through forty workbook parses, a parse that dies takes a
job with it rather than a user's request, and the same code path serves a
future replay after an Admin approves a mapping.

**Two transactions per job, deliberately.** The claim commits on its own, so
the job is marked RUNNING and no second worker can take it. The parse then
runs in a second transaction that also marks the job finished -- one fact,
one commit, so a batch is never PENDING_REVIEW while its job still claims to
be running. A failure rolls back the dispositions without un-claiming the
job and re-running for ever.

It runs as a thread inside the API process by default (one machine, thirty
users, `00-ARCHITECTURE.md` §1) and as a standalone process with
`python -m app.workers.ingest_worker`. Neither knows about the other: SKIP
LOCKED means N workers is as safe as one.
"""

from __future__ import annotations

import logging
import threading
import time

from app.core.db import Database
from app.repositories import batches, ingest_jobs
from app.services.ingest import IngestService

log = logging.getLogger("app.worker")


def run_once(database: Database, service: IngestService) -> bool:
    """Claim and process at most one job. True if one was processed."""
    with database.begin() as conn:
        job = ingest_jobs.claim(conn)
    if job is None:
        return False

    job_id, load_id, attempts = job["job_id"], job["load_id"], job["attempts"] + 1
    try:
        # One transaction for the parse AND the job's completion. Splitting
        # them leaves a window where the batch has reached PENDING_REVIEW but
        # the job still says RUNNING, which is a lie a reviewer can see.
        with database.begin() as conn:
            status = service.process_batch(conn, load_id)
            ingest_jobs.finish(conn, job_id)
        log.info(
            "batch parsed",
            extra={"detail": f"load_id={load_id} status={status}"},
        )
    except Exception as exc:  # noqa: BLE001 - the worker must not die on one file
        message = f"{exc.__class__.__name__}: {exc}"
        log.exception("ingest job failed", extra={"detail": f"load_id={load_id}"})
        with database.begin() as conn:
            if not ingest_jobs.requeue_if_retryable(conn, job_id, attempts):
                ingest_jobs.finish(conn, job_id, error=message[:2000])
                # The batch must not be left RUNNING for ever: a status a
                # reviewer can see is the point of the status column.
                batches.set_batch_outcome(
                    conn,
                    load_id,
                    status=batches.STATUS_FAILED,
                    notes=f"ingest failed after {attempts} attempt(s): {message}"[:2000],
                )
    return True


def drain(database: Database, service: IngestService, limit: int = 100) -> int:
    """Process everything queued. Used by the CLI path and by tests."""
    done = 0
    while done < limit and run_once(database, service):
        done += 1
    return done


class IngestWorker:
    """A background thread that polls the queue."""

    def __init__(
        self, database: Database, service: IngestService, poll_seconds: float = 0.2
    ) -> None:
        self.database = database
        self.service = service
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # Cleared here, not only in __init__: a worker that has been stopped
        # must be startable again, or `stop()` is a one-way door.
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ingest-worker", daemon=True
        )
        self._thread.start()
        log.info("ingest worker started")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        log.info("ingest worker stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = run_once(self.database, self.service)
            except Exception:  # noqa: BLE001 - includes the database being down
                log.exception("worker loop error")
                worked = False
            if not worked:
                self._stop.wait(self.poll_seconds)


def main() -> int:  # pragma: no cover - operational entry point
    """Run the worker as its own process, against the same configuration."""
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.services.raw_store import RawStore

    configure_logging()
    settings = get_settings()
    database = Database(settings)
    service = IngestService(settings, RawStore(settings.raw_store_path))
    worker = IngestWorker(database, service, settings.ingest_worker_poll_seconds)
    worker.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        worker.stop()
        database.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
