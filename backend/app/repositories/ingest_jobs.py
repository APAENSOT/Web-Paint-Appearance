"""The ingest work queue.

`02-PIPELINE.md` §9: "Job claim: SELECT ... FOR UPDATE SKIP LOCKED. No Redis
in v1." That is the whole design. PostgreSQL is already the single source of
truth and already transactional, so a second piece of infrastructure would
add an outage mode without adding a capability.

`SKIP LOCKED` is what makes two workers safe: a row another transaction has
locked is passed over rather than waited on, so N workers claim N different
jobs and none of them blocks.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

QUEUED = "QUEUED"
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"

#: A job that has failed this many times is left alone for a human. Retrying
#: a deterministic parse failure for ever just fills the log.
MAX_ATTEMPTS = 3


def enqueue(conn: Connection, load_id: int) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO ingest_job (load_id, status) "
                "VALUES (:load_id, :status) RETURNING job_id"
            ),
            {"load_id": load_id, "status": QUEUED},
        ).scalar_one()
    )


def claim(conn: Connection) -> dict | None:
    """Take the oldest queued job, or return None.

    Must run inside a transaction: the `FOR UPDATE` lock is what stops a
    second worker taking the same row, and it lasts only as long as the
    transaction does.
    """
    row = conn.execute(
        text(
            """
            SELECT job_id, load_id, attempts
              FROM ingest_job
             WHERE status = :queued
             ORDER BY job_id
             FOR UPDATE SKIP LOCKED
             LIMIT 1
            """
        ),
        {"queued": QUEUED},
    ).mappings().first()
    if row is None:
        return None
    conn.execute(
        text(
            "UPDATE ingest_job SET status = :running, attempts = attempts + 1, "
            "started_at = now() WHERE job_id = :job_id"
        ),
        {"running": RUNNING, "job_id": row["job_id"]},
    )
    return dict(row)


def finish(conn: Connection, job_id: int, *, error: str | None = None) -> None:
    conn.execute(
        text(
            "UPDATE ingest_job SET status = :status, last_error = :error, "
            "finished_at = now() WHERE job_id = :job_id"
        ),
        {"status": FAILED if error else DONE, "error": error, "job_id": job_id},
    )


def requeue_if_retryable(conn: Connection, job_id: int, attempts: int) -> bool:
    """Put a transient failure back on the queue; leave a hard one failed."""
    if attempts >= MAX_ATTEMPTS:
        return False
    conn.execute(
        text("UPDATE ingest_job SET status = :queued WHERE job_id = :job_id"),
        {"queued": QUEUED, "job_id": job_id},
    )
    return True


def get_for_batch(conn: Connection, load_id: int) -> dict | None:
    row = conn.execute(
        text(
            "SELECT job_id, load_id, status, attempts, last_error, "
            "       enqueued_at, started_at, finished_at "
            "FROM ingest_job WHERE load_id = :load_id"
        ),
        {"load_id": load_id},
    ).mappings().first()
    return dict(row) if row else None


def get_for_batches(conn: Connection, load_ids: list[int]) -> dict[int, dict]:
    """Jobs for a page of batches, in one round trip.

    `ingest_job` has `UNIQUE (load_id)`, so this is one job per batch and the
    dictionary cannot lose one. A batch with no job (a `REJECTED_TEMPLATE`
    sheet that was never queued) is simply absent.
    """
    if not load_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT job_id, load_id, status, attempts, last_error, "
            "       enqueued_at, started_at, finished_at "
            "FROM ingest_job WHERE load_id = ANY(:ids)"
        ),
        {"ids": list(load_ids)},
    ).mappings().all()
    return {int(r["load_id"]): dict(r) for r in rows}


def queued_count(conn: Connection) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM ingest_job WHERE status = :q"), {"q": QUEUED}
        ).scalar_one()
    )


def requeue_for_batch(conn: Connection, load_id: int) -> int:
    """Queue a batch for (re-)parsing, whether or not it has a job row.

    `ingest_job` has `UNIQUE (load_id)`, so a replay cannot simply enqueue a
    second job: a batch that has already been parsed owns a finished row, and
    a `REJECTED_TEMPLATE` batch owns none at all because T04 never queued it.
    One upsert covers both, and the conflict branch resets the attempt
    history so a replay is not judged by the previous parse's failures.

    Every column it writes is one the T04/T08 grants name; `enqueued_at` is
    among them precisely so a re-queued job reports when it was re-queued.
    """
    return int(
        conn.execute(
            text(
                """
                INSERT INTO ingest_job (load_id, status)
                VALUES (:load_id, :queued)
                ON CONFLICT (load_id) DO UPDATE
                   SET status = :queued,
                       attempts = 0,
                       last_error = NULL,
                       enqueued_at = now(),
                       started_at = NULL,
                       finished_at = NULL
                RETURNING job_id
                """
            ),
            {"load_id": load_id, "queued": QUEUED},
        ).scalar_one()
    )
