"""T67: AAT Clear correction pair -- lo 30, target 35, no Maximum (D-67-06).

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-06

The T63 seed stored AAT CLEAR as ``lo 30 hi 35`` (the prototype's range
shape). The owner says AAT Clear follows the other plants: 30 = No point
below, 35 = Minimum requirement, no Maximum.

**Data only, append only** (ADR 0005, D-FS-03): two INSERTs into
``film_standard`` (H and V, plant-wide). Latest ``created_at`` wins, so the
T63 AAT-02 pair stays as history, unchanged. No UPDATE, no DELETE, no DDL,
no CHECK (D-67-07 refuses ``hi`` on CLEAR in the API only).

Downgrade deletes only these two rows (``created_by IS NULL`` and this note).
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

PROTO = "Prototype.html constants (owner-accepted 2026-10-06)"
NOTE = "FILM-STANDARDS-AUDIT AAT-02 (T67 owner correction 2026-10-06)"
_PREDICATE = "created_by IS NULL AND source_note = :note"


def upgrade() -> None:
    conn = op.get_bind()
    for orient in ("H", "V"):
        conn.execute(
            text(
                "INSERT INTO film_standard "
                "(plant_code, layer_code, orient, color_name, lo, hi, target, "
                " source_document, source_note, created_by) "
                "VALUES ('AAT', 'CLEAR', :o, NULL, 30, NULL, 35, :doc, :note, NULL)"
            ),
            {"o": orient, "doc": PROTO, "note": NOTE},
        )
    written = conn.execute(
        text(f"SELECT count(*) FROM film_standard WHERE {_PREDICATE}"), {"note": NOTE}
    ).scalar_one()
    if written != 2:
        raise RuntimeError(f"T67 correction wrote {written} rows, expected 2")


def downgrade() -> None:
    op.get_bind().execute(
        text(f"DELETE FROM film_standard WHERE {_PREDICATE}"), {"note": NOTE}
    )
