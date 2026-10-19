"""Writes that retire a fact without deleting one.

Two operations, both from ADR 0005 and `01-DATA-MODEL.md` §5:

* a **correction** inserts a new `wavescan` row and one
  `measurement_supersession` row. The side table's `AFTER INSERT` trigger is
  what sets `is_superseded` on the original -- this module never does, and
  could not: the application role holds no `UPDATE` on `wavescan`.
* a **batch supersede** changes one column on `load_batch`. It writes nothing
  to `wavescan`.

**There is no `UPDATE wavescan` and no `DELETE` anywhere in this file.** The
grants make that a guarantee rather than a promise, but the statements are
worth reading for it too.

The correction insert is an `INSERT ... SELECT` from the row being corrected.
That is not a style choice: it means identity -- plant, model, checkzone,
colour, tolerance group, paintline, `load_id`, `source_sheet`, `source_row`
and the source-zone provenance -- is copied by the **database** from the
original, not re-sent by the client and trusted. A caller cannot move a
measurement to another plant by correcting it, because the statement has
nowhere to put a plant.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

#: Copied verbatim from the row being corrected. Identity and provenance:
#: which cell this is and where it came from.
COPIED_COLUMNS = (
    "plant", "model", "checkzone", "color", "tolerance_group", "paintline",
    "load_id", "source_sheet", "source_row", "src_zone_text", "src_zone_no",
)

#: Taken from the patch when the caller sent them, from the original
#: otherwise. `b` is handled separately below because it is the only one that
#: can legitimately be set to NULL.
OVERLAID_COLUMNS = (
    "measured_date", "serial_no",
    "lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we",
)


def _correction_insert() -> str:
    """Build the INSERT once, from the column lists above.

    `COALESCE(:field, w.field)` is the whole patch mechanism for the
    non-nullable columns: a parameter that is NULL means "not sent", which for
    a `NOT NULL` column is unambiguous. `b` is nullable, so "not sent" and
    "sent as null" would look identical -- hence the explicit `:b_set` flag.

    `is_superseded` and `is_duplicate` are absent on purpose. Both default to
    false, and `trg_reject_presuperseded` refuses an insert that tries to set
    the first one (`01-DATA-MODEL.md` §5: "a row inserted already superseded
    is a delete wearing a hat").
    """
    overlaid = ",\n               ".join(
        f"COALESCE(:{c}, w.{c})" for c in OVERLAID_COLUMNS
    )
    copied = ", ".join(f"w.{c}" for c in COPIED_COLUMNS)
    return f"""
        INSERT INTO wavescan (
            {", ".join(OVERLAID_COLUMNS)}, b,
            {", ".join(COPIED_COLUMNS)}, date_is_month_only,
            corrects_measurement_id, correction_reason, corrected_by, corrected_at
        )
        SELECT {overlaid},
               CASE WHEN :b_set THEN CAST(:b AS numeric) ELSE w.b END,
               {copied},
               -- RO18 (B4): still "day not recorded" unless the date is corrected
               w.date_is_month_only
                   AND COALESCE(CAST(:measured_date AS date), w.measured_date) = w.measured_date,
               w.measurement_id, :reason, CAST(:actor AS uuid), now()
          FROM wavescan w
         WHERE w.measurement_id = :original
        RETURNING measurement_id
    """


CORRECTION_INSERT = text(_correction_insert())


def find_any(conn: Connection, measurement_id: int) -> dict | None:
    """One measurement regardless of whether it is active, plus its batch's
    status.

    Deliberately reads the base table rather than `v_wavescan_active`: this
    exists to tell "no such measurement" (404) apart from "it exists and is
    not current" (409), and the active view cannot answer the second. It
    selects no predicate column and re-implements no predicate -- the batch
    status comes back as data for the service to compare against its own
    constants, which is how every other repository in this package reports a
    status.
    """
    row = conn.execute(
        text(
            """
            SELECT w.measurement_id, w.load_id, w.plant, w.corrects_measurement_id,
                   b.status AS batch_status
              FROM wavescan w
              JOIN load_batch b ON b.load_id = w.load_id
             WHERE w.measurement_id = :id
            """
        ),
        {"id": measurement_id},
    ).mappings().first()
    return dict(row) if row else None


def supersession_of(conn: Connection, measurement_id: int) -> dict | None:
    """The record retiring this measurement, if there is one.

    `measurement_supersession` is the evidence: who retired it, when, why, and
    what replaced it. A 409 that can quote all four is worth the extra read.
    """
    row = conn.execute(
        text(
            """
            SELECT id, superseded_by_measurement_id, reason, actor_user_id, occurred_at
              FROM measurement_supersession
             WHERE superseded_measurement_id = :id
            """
        ),
        {"id": measurement_id},
    ).mappings().first()
    return dict(row) if row else None


def exists(conn: Connection, measurement_id: int) -> bool:
    """Is there a measurement with this id at all, current or not?

    A plain `SELECT`. An earlier draft took `SELECT ... FOR UPDATE` here to
    serialise two simultaneous corrections of the same reading -- and
    PostgreSQL refused it, because a row lock requires `UPDATE` on the table
    and the application role deliberately has none. That refusal is the
    design working: the serialisation belongs to `uq_supersession_once` on
    `measurement_supersession`, which makes the second transaction block on
    the unique index and then fail, rolling back its half-written correction.
    The constraint is the guard; a lock would only have been the polite
    version of it, bought with a privilege ADR 0005 forbids.
    """
    return (
        conn.execute(
            text("SELECT 1 FROM wavescan WHERE measurement_id = :id"),
            {"id": measurement_id},
        ).first()
        is not None
    )


def insert_correction(
    conn: Connection,
    *,
    original_id: int,
    patch: dict,
    reason: str,
    actor_user_id: str,
) -> int:
    """Add the corrected row. Returns its new `measurement_id`.

    Every value not in `patch` is read out of the original by the database.
    Nothing is updated and nothing is deleted.
    """
    params: dict = {
        "original": original_id,
        "reason": reason,
        "actor": actor_user_id or None,
        "b_set": "b" in patch,
        "b": patch.get("b"),
    }
    for column in OVERLAID_COLUMNS:
        params[column] = patch.get(column)
    return int(conn.execute(CORRECTION_INSERT, params).scalar_one())


def record_supersession(
    conn: Connection,
    *,
    superseded_measurement_id: int,
    superseded_by_measurement_id: int | None,
    reason: str,
    actor_user_id: str,
) -> int:
    """Retire a measurement by writing the evidence.

    The `AFTER INSERT` trigger `mark_measurement_superseded` then sets
    `is_superseded` on the retired row. That ordering is the point: the flag
    can only become true after a reason and an actor are on record.
    `uq_supersession_once` makes a second attempt a unique violation, which
    the service turns into a 409.
    """
    return int(
        conn.execute(
            text(
                """
                INSERT INTO measurement_supersession
                    (superseded_measurement_id, superseded_by_measurement_id,
                     reason, actor_user_id)
                VALUES (:superseded, :replacement, :reason, CAST(:actor AS uuid))
                RETURNING id
                """
            ),
            {
                "superseded": superseded_measurement_id,
                "replacement": superseded_by_measurement_id,
                "reason": reason,
                "actor": actor_user_id or None,
            },
        ).scalar_one()
    )


def count_rows_for_batch(conn: Connection, load_id: int) -> int:
    """How many `wavescan` rows this batch owns, active or not.

    Read before and after a batch supersede so the response can say how many
    rows left the active reads -- and so a test can prove none of them left
    the table.
    """
    return int(
        conn.execute(
            text("SELECT count(*) FROM wavescan WHERE load_id = :load_id"),
            {"load_id": load_id},
        ).scalar_one()
    )


def abandon_batch(conn: Connection, load_id: int, *, status: str) -> None:
    """Take a sheet that produced no measurement out of the review queue.

    One column, `status`, inside the column-scoped grant. Staging, the
    projection, the stored bytes and the audit trail are untouched -- this
    statement has nowhere to delete them from (T21).
    """
    conn.execute(
        text("UPDATE load_batch SET status = :status WHERE load_id = :load_id"),
        {"status": status, "load_id": load_id},
    )


def supersede_batch(
    conn: Connection, load_id: int, *, status: str, superseded_by: int | None
) -> None:
    """Retire a batch: two columns on `load_batch`, nothing else.

    `status` and `superseded_by` are both in the column-scoped `UPDATE` grant
    T01 wrote, so this statement is the entire extent of what the application
    can do to a batch. It cannot delete one, and it does not touch the
    measurements -- they stop being read because the active-data predicate
    tests the batch's status, not because anything changed about them.
    """
    conn.execute(
        text(
            "UPDATE load_batch SET status = :status, superseded_by = :superseded_by "
            "WHERE load_id = :load_id"
        ),
        {"status": status, "superseded_by": superseded_by, "load_id": load_id},
    )


def restore_batch(
    conn: Connection, load_id: int, *, status: str, clear_superseded_by: bool
) -> None:
    """Put a retired batch back in the workflow (T25). `load_batch` only.

    From `ABANDONED` only `status` moves. From `SUPERSEDED` the batch returns
    to `COMMITTED` and `superseded_by` is cleared, because a batch that is
    current is not replaced by anything. Both columns are inside the
    column-scoped grant T01 wrote; nothing here can touch `wavescan`, and the
    measurements a restored batch owns become current again only because
    `v_wavescan_active` tests the batch's status.
    """
    if clear_superseded_by:
        conn.execute(
            text(
                "UPDATE load_batch SET status = :status, superseded_by = NULL "
                "WHERE load_id = :load_id"
            ),
            {"status": status, "load_id": load_id},
        )
        return
    conn.execute(
        text("UPDATE load_batch SET status = :status WHERE load_id = :load_id"),
        {"status": status, "load_id": load_id},
    )
