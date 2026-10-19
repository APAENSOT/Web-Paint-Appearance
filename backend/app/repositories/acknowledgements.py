"""`review_acknowledgement`: who accepted which warning, and of what.

Two statements, and the missing ones are the design (revision 0007):

* There is **no UPDATE**. Changing your mind means acknowledging again, and
  both records stay. An acknowledgement is a statement a person made at a
  time, so editing one would be rewriting what they said.
* There is **no DELETE**, and `reset_batch_staging` does not clear this
  table. A replay invalidates an acknowledgement by moving the batch's
  `review_revision` out from under it, not by removing it: "somebody read
  the older proposal and accepted it" stays true after the re-parse, and is
  exactly what a later reader needs to see.

`app_rw` holds `SELECT, INSERT` and nothing else, so neither of those is a
convention this module could break.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

#: The four categories revision 0007's CHECK allows.
CATEGORY_REJECTED_ROWS = "REJECTED_ROWS"
CATEGORY_QUARANTINED_MODELS = "QUARANTINED_MODELS"
CATEGORY_DUPLICATE_ROWS = "DUPLICATE_ROWS"
CATEGORY_POSSIBLE_REPLACEMENT = "POSSIBLE_REPLACEMENT"

CATEGORIES: tuple[str, ...] = (
    CATEGORY_REJECTED_ROWS,
    CATEGORY_QUARANTINED_MODELS,
    CATEGORY_DUPLICATE_ROWS,
    CATEGORY_POSSIBLE_REPLACEMENT,
)

#: The three that block a commit while unacknowledged, each because it means
#: rows the plant sent are **not** becoming measurements and somebody should
#: have noticed. `POSSIBLE_REPLACEMENT` is deliberately absent: it is a hint
#: that an older workbook may be stale, which is an Admin's supersede
#: decision and never a reason to refuse this commit (design M14).
BLOCKING_CATEGORIES: tuple[str, ...] = (
    CATEGORY_REJECTED_ROWS,
    CATEGORY_QUARANTINED_MODELS,
    CATEGORY_DUPLICATE_ROWS,
)

#: The two whose note the database insists on (design M11).
NOTE_REQUIRED: tuple[str, ...] = (
    CATEGORY_REJECTED_ROWS,
    CATEGORY_QUARANTINED_MODELS,
)

ACK_COLUMNS = """
    ack_id, load_id, plant_code, file_hash, category, note,
    review_revision, actor_user_id, created_at
"""


def insert(
    conn: Connection,
    *,
    load_id: int,
    plant_code: str,
    file_hash: str,
    category: str,
    note: str | None,
    review_revision: str,
    actor_user_id: str,
) -> dict:
    """Record one acknowledgement. Returns the stored row.

    The row is returned rather than rebuilt by the caller so the response
    shows what the database actually holds -- including `created_at`, which
    is the server's clock and not the client's.
    """
    row = conn.execute(
        text(
            f"""
            INSERT INTO review_acknowledgement
                (load_id, plant_code, file_hash, category, note,
                 review_revision, actor_user_id)
            VALUES (:load_id, :plant_code, :file_hash, :category, :note,
                    :review_revision, CAST(:actor_user_id AS uuid))
            RETURNING {ACK_COLUMNS}
            """
        ),
        {
            "load_id": load_id,
            "plant_code": plant_code,
            "file_hash": file_hash,
            "category": category,
            "note": note,
            "review_revision": review_revision,
            "actor_user_id": actor_user_id,
        },
    ).mappings().one()
    return dict(row)


def acknowledged(conn: Connection, load_id: int, review_revision: str | None) -> set[str]:
    """Categories acknowledged for this batch **at this revision**.

    A null revision answers the empty set rather than "everything": a batch
    with no projection has nothing anybody could have read.
    """
    if not review_revision:
        return set()
    rows = conn.execute(
        text(
            "SELECT DISTINCT category FROM review_acknowledgement "
            "WHERE load_id = :load_id AND review_revision = :revision"
        ),
        {"load_id": load_id, "revision": review_revision},
    ).all()
    return {r[0] for r in rows}


def acknowledged_for_batches(
    conn: Connection, load_ids: list[int]
) -> dict[int, set[str]]:
    """The same question for a page of batches, in one round trip.

    The revision compared against is each batch's **current** one, joined
    here rather than passed in, so a caller cannot accidentally ask with a
    stale revision and be told a warning is handled when it is not.
    """
    if not load_ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT a.load_id, a.category
              FROM review_acknowledgement a
              JOIN load_batch b ON b.load_id = a.load_id
             WHERE a.load_id = ANY(:ids)
               AND b.review_revision = a.review_revision
            """
        ),
        {"ids": list(load_ids)},
    ).all()
    out: dict[int, set[str]] = {}
    for load_id, category in rows:
        out.setdefault(int(load_id), set()).add(category)
    return out


def for_batches(conn: Connection, load_ids: list[int]) -> list[dict]:
    """Every acknowledgement of these batches, oldest first.

    Includes the ones a replay invalidated, which is the point: the workbook
    detail shows what was accepted and when, and a reader comparing
    `review_revision` against the batch's current one can see that an earlier
    reviewer was looking at different rows.
    """
    if not load_ids:
        return []
    rows = conn.execute(
        text(
            f"SELECT {ACK_COLUMNS} FROM review_acknowledgement "
            f"WHERE load_id = ANY(:ids) ORDER BY ack_id"
        ),
        {"ids": list(load_ids)},
    ).mappings().all()
    return [dict(r) for r in rows]


__all__ = [
    "CATEGORIES",
    "BLOCKING_CATEGORIES",
    "NOTE_REQUIRED",
    "CATEGORY_REJECTED_ROWS",
    "CATEGORY_QUARANTINED_MODELS",
    "CATEGORY_DUPLICATE_ROWS",
    "CATEGORY_POSSIBLE_REPLACEMENT",
    "insert",
    "acknowledged",
    "acknowledged_for_batches",
    "for_batches",
]
