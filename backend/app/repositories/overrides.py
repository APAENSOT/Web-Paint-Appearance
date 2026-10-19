"""`review_override`: a reviewer's replacement for one measure of one row.

Revision 0008. Two statements, and the missing ones are the design:

* There is **no UPDATE**. A second override of the same field is another
  row, and the latest by `created_at` is the one every re-derivation applies.
  The earlier one stays, because it is what somebody said at a time.
* There is **no DELETE**, and `reset_batch_staging` does not clear this
  table. A replay re-derives the projection from the stored bytes and then
  applies these rows again; it cannot tidy them away.

`app_rw` holds `SELECT, INSERT` and nothing else, so neither is a convention
this module could break.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Connection, text

#: The measures an override may carry (revision 0008 `ck_override_field`).
OVERRIDE_FIELDS: tuple[str, ...] = (
    "lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b",
)

OVERRIDE_COLUMNS = """
    override_id, load_id, plant_code, file_hash, source_row, field,
    previous_proposed, new_value, reason, review_revision, actor_user_id,
    created_at
"""


def insert(
    conn: Connection,
    *,
    load_id: int,
    plant_code: str,
    file_hash: str,
    source_row: int,
    field: str,
    previous_proposed: Decimal | None,
    new_value: Decimal | None,
    reason: str,
    review_revision: str,
    actor_user_id: str,
) -> dict:
    """Record one override. Returns the stored row, server clock included."""
    row = conn.execute(
        text(
            f"""
            INSERT INTO review_override
                (load_id, plant_code, file_hash, source_row, field,
                 previous_proposed, new_value, reason, review_revision,
                 actor_user_id)
            VALUES (:load_id, :plant_code, :file_hash, :source_row, :field,
                    :previous_proposed, :new_value, :reason, :review_revision,
                    CAST(:actor_user_id AS uuid))
            RETURNING {OVERRIDE_COLUMNS}
            """
        ),
        {
            "load_id": load_id,
            "plant_code": plant_code,
            "file_hash": file_hash,
            "source_row": source_row,
            "field": field,
            "previous_proposed": previous_proposed,
            "new_value": new_value,
            "reason": reason,
            "review_revision": review_revision,
            "actor_user_id": actor_user_id,
        },
    ).mappings().one()
    return dict(row)


def _current(conn: Connection, load_id: int, source_rows: list[int] | None) -> list[dict]:
    """The latest override per `(source_row, field)` of one batch.

    `override_id` breaks a `created_at` tie: two rows written in one
    transaction share `now()`, and the later INSERT is the later statement.
    """
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT ON (source_row, field) {OVERRIDE_COLUMNS}
              FROM review_override
             WHERE load_id = :load_id
               AND (CAST(:rows AS integer[]) IS NULL
                    OR source_row = ANY(CAST(:rows AS integer[])))
             ORDER BY source_row, field, created_at DESC, override_id DESC
            """
        ),
        {"load_id": load_id, "rows": source_rows},
    ).mappings().all()
    return [dict(r) for r in rows]


def current_for_batch(conn: Connection, load_id: int) -> dict[int, dict[str, Decimal | None]]:
    """`source_row -> {field: value}` to apply on top of a re-derived plan.

    Values come back from a NUMERIC column as `Decimal`, so the write-time
    revalidation and a later commit apply exactly the same number.
    """
    patches: dict[int, dict[str, Decimal | None]] = {}
    for row in _current(conn, load_id, None):
        patches.setdefault(int(row["source_row"]), {})[row["field"]] = row["new_value"]
    return patches


def current_for_rows(conn: Connection, load_id: int, source_rows: list[int]) -> list[dict]:
    """The current override rows for some source rows, for a points read."""
    if not source_rows:
        return []
    return _current(conn, load_id, list(source_rows))


__all__ = [
    "OVERRIDE_FIELDS",
    "insert",
    "current_for_batch",
    "current_for_rows",
]
