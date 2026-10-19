"""T63: seed ``film_standard`` from the owner-signed FILM-STANDARDS-AUDIT.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-06

T63-CONTEXT D-63-01..12. Data only: no DDL, no CHECK change, no grant.
57 publishes = **114 rows** (one H and one V row each), the literal values of
``docs/tasks/T63-film-standards-seed.md`` section 1 (= audit section 2 minus
STRIKE). Nothing is read from the vault or the prototype at migration time.

* ``created_by`` NULL (a seed, not a person); ``source_note`` is
  ``FILM-STANDARDS-AUDIT <row id>``; ``source_document`` is the FTM Control
  Plan scan hash on FTM-03..FTM-10 only, the prototype string elsewhere
  (D-63-03).
* AAT BC1 is ``PRIMER`` and BC2 is ``BASE``, per colour; AAT has no
  plant-wide PRIMER or BASE row, and no plant has a plant-wide BASE row
  (D-63-04, D-63-05). Colours no source covers get **no** row (D-63-07).
* **Preflight** (D-63-08): every seeded colour must be offered at its plant,
  otherwise the upgrade raises listing every miss and inserts nothing.
* No ``audit_event``: the earlier seed migrations (0002 ``cf_standard``
  version 1, 0014, 0017, 0023) wrote none (D-63-09).
* An adjustment later is a new Admin publish (newer row wins), never an
  UPDATE of these rows (D-63-11).

Downgrade deletes only the seed rows (``created_by IS NULL`` and the audit
note prefix); a later Admin publish is never removed (D-63-10).
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

CP1 = (
    "Control Plan scan Reference/Standard1.jpg "
    "sha256:cbb564cf87b5e3bb09a354e22894ae0fe5b222b7eb4052046dee92fa50965e52"
)
PROTO = "Prototype.html constants (owner-accepted 2026-10-06)"
NOTE_PREFIX = "FILM-STANDARDS-AUDIT "
EXPECTED_ROWS = 114

#: (row id, plant, layer, colour or None, H (lo, hi, target), V (lo, hi, target), source).
#: Every tuple is one publish = an H row and a V row.
PUBLISHES = (
    # ---- FTM (12) ----
    ("FTM-01", "FTM", "ECOAT", None, (18, None, None), (18, None, None), PROTO),
    ("FTM-02", "FTM", "PRIMER", None, (20, 25, None), (20, 25, None), PROTO),
    ("FTM-03", "FTM", "CLEAR", None, (36, None, 46), (30, None, 46), CP1),
    ("FTM-04", "FTM", "BASE", "Shadow Black", (15, 20, None), (15, 20, None), CP1),
    ("FTM-05", "FTM", "BASE", "Blue Lightning", (15, 20, None), (15, 20, None), CP1),
    ("FTM-06", "FTM", "BASE", "Command Grey", (20, 25, None), (20, 25, None), CP1),
    ("FTM-07", "FTM", "BASE", "Arctic White", (25, 30, None), (25, 30, None), CP1),
    ("FTM-08", "FTM", "BASE", "Aluminum Metallic", (15, 20, None), (15, 20, None), CP1),
    ("FTM-09", "FTM", "BASE", "Meteor Grey", (15, 20, None), (15, 20, None), CP1),
    ("FTM-10", "FTM", "BASE", "Code Orange", (20, 25, None), (20, 25, None), CP1),
    ("FTM-11", "FTM", "BASE", "Desert Island Blue", (15, 20, None), (15, 20, None), PROTO),
    ("FTM-12", "FTM", "BASE", "Ignite Orange", (20, 25, None), (20, 25, None), PROTO),
    # ---- FVL (11) ----
    ("FVL-01", "FVL", "ECOAT", None, (20, None, None), (20, None, None), PROTO),
    ("FVL-02", "FVL", "PRIMER", None, (23, 31, None), (18, 25, None), PROTO),
    ("FVL-03", "FVL", "CLEAR", None, (36, None, 46), (30, None, 46), PROTO),
    ("FVL-04", "FVL", "BASE", "Magnetic", (18, 22, None), (18, 22, None), PROTO),
    ("FVL-05", "FVL", "BASE", "Absolute Black", (18, 20, None), (18, 20, None), PROTO),
    ("FVL-06", "FVL", "BASE", "Frozen White", (20, 25, None), (20, 25, None), PROTO),
    ("FVL-07", "FVL", "BASE", "Diffused Silver", (15, 20, None), (15, 20, None), PROTO),
    ("FVL-08", "FVL", "BASE", "Iconic Silver", (15, 20, None), (15, 20, None), PROTO),
    ("FVL-09", "FVL", "BASE", "Pace Red", (20, 25, None), (20, 25, None), PROTO),
    ("FVL-10", "FVL", "BASE", "Ignite Orange", (20, 25, None), (20, 25, None), PROTO),
    ("FVL-11", "FVL", "BASE", "Vapor Blue", (20, 25, None), (20, 25, None), PROTO),
    # ---- SAP (14) ----
    ("SAP-01", "SAP", "ECOAT", None, (15, None, None), (15, None, None), PROTO),
    ("SAP-02", "SAP", "PRIMER", None, (23, 31, None), (18, 25, None), PROTO),
    ("SAP-03", "SAP", "CLEAR", None, (36, None, 46), (30, None, 46), PROTO),
    ("SAP-04", "SAP", "BASE", "Frozen White", (18, 22, None), (18, 22, None), PROTO),
    ("SAP-05", "SAP", "BASE", "Diffused Silver", (12, 18, None), (12, 18, None), PROTO),
    ("SAP-06", "SAP", "BASE", "Blue Lightning", (18, 22, None), (18, 22, None), PROTO),
    ("SAP-07", "SAP", "BASE", "Agate Black", (12, 18, None), (12, 18, None), PROTO),
    ("SAP-08", "SAP", "BASE", "Lucid Red", (20, 25, None), (20, 25, None), PROTO),
    ("SAP-09", "SAP", "BASE", "Carbonized Grey", (13, 19, None), (13, 19, None), PROTO),
    ("SAP-10", "SAP", "BASE", "Iconic Silver", (14, 19, None), (14, 19, None), PROTO),
    ("SAP-11", "SAP", "BASE", "Chill Grey", (15, 18, None), (15, 18, None), PROTO),
    ("SAP-12", "SAP", "BASE", "Cyclone Terra Green", (16, 19, None), (16, 19, None), PROTO),
    ("SAP-13", "SAP", "BASE", "Command Grey", (12, 15, None), (12, 15, None), PROTO),
    ("SAP-14", "SAP", "BASE", "Acacia Green", (13, 19, None), (13, 19, None), PROTO),
    # ---- AAT (20): BC1 = PRIMER, BC2 = BASE ----
    ("AAT-01", "AAT", "ECOAT", None, (15, 25, None), (15, 25, None), PROTO),
    ("AAT-02", "AAT", "CLEAR", None, (30, 35, None), (30, 35, None), PROTO),
    ("AAT-03 PRIMER", "AAT", "PRIMER", "Aluminum Metallic", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-03 BASE", "AAT", "BASE", "Aluminum Metallic", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-04 PRIMER", "AAT", "PRIMER", "Meteor Grey", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-04 BASE", "AAT", "BASE", "Meteor Grey", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-05 PRIMER", "AAT", "PRIMER", "Arctic White", (24, 26, None), (24, 26, None), PROTO),
    ("AAT-05 BASE", "AAT", "BASE", "Arctic White", (11, 13, None), (11, 13, None), PROTO),
    ("AAT-06 PRIMER", "AAT", "PRIMER", "Traction Green", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-06 BASE", "AAT", "BASE", "Traction Green", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-07 PRIMER", "AAT", "PRIMER", "Command Grey", (9, 11, None), (9, 11, None), PROTO),
    ("AAT-07 BASE", "AAT", "BASE", "Command Grey", (9, 11, None), (9, 11, None), PROTO),
    ("AAT-08 PRIMER", "AAT", "PRIMER", "Ignite Orange", (9, 11, None), (9, 11, None), PROTO),
    ("AAT-08 BASE", "AAT", "BASE", "Ignite Orange", (9, 11, None), (9, 11, None), PROTO),
    ("AAT-09 PRIMER", "AAT", "PRIMER", "Pearl White", (31, 33, None), (31, 33, None), PROTO),
    ("AAT-09 BASE", "AAT", "BASE", "Pearl White", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-10 PRIMER", "AAT", "PRIMER", "Acacia Green", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-10 BASE", "AAT", "BASE", "Acacia Green", (7, 9, None), (7, 9, None), PROTO),
    ("AAT-11 PRIMER", "AAT", "PRIMER", "Shadow Black", (9, 11, None), (9, 11, None), PROTO),
    ("AAT-11 BASE", "AAT", "BASE", "Shadow Black", (9, 11, None), (9, 11, None), PROTO),
)

_SEED_PREDICATE = "created_by IS NULL AND source_note LIKE 'FILM-STANDARDS-AUDIT %'"


def _preflight(conn) -> None:
    """D-63-08: every seeded colour offered at its plant, or raise with all misses."""
    misses = []
    for row_id, plant, _layer, colour, _h, _v, _src in PUBLISHES:
        if colour is None:
            continue
        offered = conn.execute(
            text(
                "SELECT is_offered FROM ref_plant_color "
                "WHERE plant_code = :p AND color_name = :c"
            ),
            {"p": plant, "c": colour},
        ).scalar()
        if offered is not True:
            misses.append(f"{row_id}: {colour!r} not offered at {plant}")
    if misses:
        raise RuntimeError(
            "T63 seed preflight failed; nothing inserted:\n  " + "\n  ".join(misses)
        )


def upgrade() -> None:
    conn = op.get_bind()
    if len(PUBLISHES) * 2 != EXPECTED_ROWS:
        raise RuntimeError(f"T63 seed table has {len(PUBLISHES) * 2} rows, expected 114")
    _preflight(conn)
    for row_id, plant, layer, colour, h, v, source in PUBLISHES:
        for orient, (lo, hi, target) in (("H", h), ("V", v)):
            conn.execute(
                text(
                    "INSERT INTO film_standard "
                    "(plant_code, layer_code, orient, color_name, lo, hi, target, "
                    " source_document, source_note, created_by) "
                    "VALUES (:p, :l, :o, :c, :lo, :hi, :t, :doc, :note, NULL)"
                ),
                {
                    "p": plant,
                    "l": layer,
                    "o": orient,
                    "c": colour,
                    "lo": lo,
                    "hi": hi,
                    "t": target,
                    "doc": source,
                    "note": NOTE_PREFIX + row_id,
                },
            )
    seeded = conn.execute(
        text(f"SELECT count(*) FROM film_standard WHERE {_SEED_PREDICATE}")
    ).scalar_one()
    if seeded != EXPECTED_ROWS:
        raise RuntimeError(f"T63 seed wrote {seeded} rows, expected {EXPECTED_ROWS}")


def downgrade() -> None:
    op.execute(f"DELETE FROM film_standard WHERE {_SEED_PREDICATE}")
