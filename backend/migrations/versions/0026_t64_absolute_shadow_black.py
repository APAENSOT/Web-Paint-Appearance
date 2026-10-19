"""T64: "Absolute / Shadow Black" -- one colour, two historical names (ADR 0014).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-06

T64-CONTEXT D-64-01..10. Owner workbook ``standard color family.xlsx``
(``b9f54fcd...``) row 18: AAT ``G9Z Absolute Black``, FTM ``DM G9 Shadow
Black BC`` and FVL ``AB - Absolute Black`` are one Dark Metallics colour.

**No fact is touched** (ADR 0005): no UPDATE or DELETE of ``wavescan``,
``filmthickness``, ``cf_standard`` or ``film_standard``, no correction row.
The merge is a fold:

1. ``ref_color.merged_into`` (FK to ``ref_color``, not itself, one level only:
   ``trg_ref_color_merge_one_level``).
2. Mint ``Absolute / Shadow Black`` (BLACK, active).
3. ``Shadow Black`` and ``Absolute Black``: ``merged_into`` the canonical
   name, ``is_active = false``. Their rows stay for the facts' FKs.
4. ``ref_plant_color``: the canonical name offered at AAT, FTM, FVL with
   Dark Metallics; the four old-name rows un-offered. SAP untouched.
5. ``ref_color_alias`` (ON CONFLICT DO NOTHING): FTM ``DM G9 Shadow Black
   BC``, FVL ``AB - Absolute Black``, global ``Absolute Black`` and
   ``Absolute / Shadow Black``.
6. ``v_wavescan_active`` and ``filmthickness_active`` are re-created with
   ``COALESCE(rc.merged_into, <x>.color) AS color`` through a LEFT JOIN to
   ``ref_color``; every other column, the order and the WHERE are the
   ``pg_get_viewdef`` text unchanged. ``CREATE OR REPLACE`` keeps the
   grants and the dependants (``v_wavescan_p703``, ``v_wavescan_u704``,
   ``v_wavescan``, ``v_car_completeness``), which read ``v_wavescan_active``
   and so carry the folded name without being re-created.
7. Post-assertions: no offered row on a merged name; the canonical name is
   offered at exactly AAT, FTM, FVL, all Dark Metallics.

No ``audit_event`` row: no earlier reference-data migration wrote one.
Downgrade reverses 7 -> 1 and refuses while any fact or standard row is
stored under the canonical name.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

CANONICAL = "Absolute / Shadow Black"
MERGED = ("Shadow Black", "Absolute Black")
FAMILY = "Dark Metallics"
OFFER_PLANTS = ("AAT", "FTM", "FVL")
UNOFFER = (
    ("AAT", "Shadow Black"),
    ("AAT", "Absolute Black"),
    ("FTM", "Shadow Black"),
    ("FVL", "Absolute Black"),
)
ALIAS_NOTE = "T64 workbook b9f54fcd row 18"
#: (plant or None, raw spelling) -> CANONICAL.
ALIASES = (
    ("FTM", "DM G9 Shadow Black BC"),
    ("FVL", "AB - Absolute Black"),
    (None, "Absolute Black"),
    (None, CANONICAL),
)

# ---- view text: exact fragments of pg_get_viewdef, swapped and restored ----
WS_VIEW = "v_wavescan_active"
WS_COLOR_OLD = "    w.color,\n"
WS_COLOR_NEW = "    COALESCE(rc.merged_into, w.color) AS color,\n"
WS_JOIN_OLD = "     JOIN load_batch b ON b.load_id = w.load_id\n"
WS_JOIN_NEW = WS_JOIN_OLD + "     LEFT JOIN ref_color rc ON rc.color_name = w.color\n"

FT_VIEW = "filmthickness_active"
FT_COLOR_OLD = "    color,\n"
FT_COLOR_NEW = "    COALESCE(rc.merged_into, filmthickness.color) AS color,\n"
FT_FROM_OLD = "   FROM filmthickness\n"
FT_FROM_NEW = (
    "   FROM filmthickness\n"
    "     LEFT JOIN ref_color rc ON rc.color_name = filmthickness.color\n"
)


def _viewdef(conn, view: str) -> str:
    return conn.execute(
        text("SELECT pg_get_viewdef(CAST(:v AS regclass), true)"), {"v": view}
    ).scalar_one()


def _swap(conn, view: str, pairs: tuple[tuple[str, str], ...]) -> None:
    """CREATE OR REPLACE the view with each fragment swapped exactly once."""
    body = _viewdef(conn, view)
    for old, new in pairs:
        if body.count(old) != 1:
            raise RuntimeError(f"{view}: expected fragment {old!r} once; not re-created")
        body = body.replace(old, new)
    conn.execute(text(f"CREATE OR REPLACE VIEW {view} AS\n{body}"))


def upgrade() -> None:
    conn = op.get_bind()

    # 1. merge pointer, one level only
    op.execute(
        "ALTER TABLE ref_color ADD COLUMN merged_into text NULL "
        "REFERENCES ref_color (color_name), "
        "ADD CONSTRAINT ck_ref_color_merged_not_self "
        "CHECK (merged_into IS NULL OR merged_into <> color_name)"
    )
    op.execute(
        """
        CREATE FUNCTION ref_color_merge_one_level()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $fn$
        BEGIN
            IF NEW.merged_into IS NOT NULL THEN
                IF EXISTS (SELECT 1 FROM ref_color
                            WHERE color_name = NEW.merged_into
                              AND merged_into IS NOT NULL) THEN
                    RAISE EXCEPTION
                        'ref_color %: target % is itself merged; one level only',
                        NEW.color_name, NEW.merged_into
                        USING ERRCODE = 'check_violation';
                END IF;
                IF EXISTS (SELECT 1 FROM ref_color
                            WHERE merged_into = NEW.color_name) THEN
                    RAISE EXCEPTION
                        'ref_color % is a merge target and cannot itself be merged',
                        NEW.color_name
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $fn$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_ref_color_merge_one_level "
        "AFTER INSERT OR UPDATE OF merged_into ON ref_color "
        "FOR EACH ROW EXECUTE FUNCTION ref_color_merge_one_level()"
    )
    op.execute(
        "COMMENT ON COLUMN ref_color.merged_into IS "
        "'T64 / ADR 0014. This name is read and written as merged_into. "
        "Facts stay stored under the old name (ADR 0005); views and reads fold. "
        "One level only.'"
    )

    # 2-3. canonical name; old names point at it
    conn.execute(
        text(
            "INSERT INTO ref_color (color_name, color_group, is_active) "
            "VALUES (:c, 'BLACK', true)"
        ),
        {"c": CANONICAL},
    )
    for name in MERGED:
        conn.execute(
            text(
                "UPDATE ref_color SET merged_into = :c, is_active = false "
                "WHERE color_name = :n"
            ),
            {"c": CANONICAL, "n": name},
        )

    # 4. plant offer
    for plant in OFFER_PLANTS:
        conn.execute(
            text(
                "INSERT INTO ref_plant_color (plant_code, color_name, family_name, is_offered) "
                "VALUES (:p, :c, :f, true)"
            ),
            {"p": plant, "c": CANONICAL, "f": FAMILY},
        )
    for plant, name in UNOFFER:
        conn.execute(
            text(
                "UPDATE ref_plant_color SET is_offered = false, updated_at = now() "
                "WHERE plant_code = :p AND color_name = :n"
            ),
            {"p": plant, "n": name},
        )

    # 5. aliases
    for plant, raw in ALIASES:
        conflict = (
            "ON CONFLICT (plant_code, raw_value) WHERE plant_code IS NOT NULL DO NOTHING"
            if plant
            else "ON CONFLICT (raw_value) WHERE plant_code IS NULL DO NOTHING"
        )
        conn.execute(
            text(
                "INSERT INTO ref_color_alias (raw_value, color_name, note, plant_code) "
                f"VALUES (:r, :c, :note, :p) {conflict}"
            ),
            {"r": raw, "c": CANONICAL, "note": ALIAS_NOTE, "p": plant},
        )

    # 6. views fold the colour
    _swap(conn, WS_VIEW, ((WS_COLOR_OLD, WS_COLOR_NEW), (WS_JOIN_OLD, WS_JOIN_NEW)))
    _swap(conn, FT_VIEW, ((FT_COLOR_OLD, FT_COLOR_NEW), (FT_FROM_OLD, FT_FROM_NEW)))

    # 7. post-assertions
    stray = conn.execute(
        text(
            "SELECT pc.plant_code, pc.color_name FROM ref_plant_color pc "
            "JOIN ref_color rc ON rc.color_name = pc.color_name "
            "WHERE pc.is_offered AND rc.merged_into IS NOT NULL"
        )
    ).all()
    if stray:
        raise RuntimeError(f"T64: offered rows on a merged name: {stray}")
    offered = conn.execute(
        text(
            "SELECT plant_code, family_name FROM ref_plant_color "
            "WHERE color_name = :c AND is_offered ORDER BY plant_code"
        ),
        {"c": CANONICAL},
    ).all()
    if [tuple(r) for r in offered] != [(p, FAMILY) for p in OFFER_PLANTS]:
        raise RuntimeError(f"T64: canonical offer is {offered}, expected AAT/FTM/FVL DM")


def downgrade() -> None:
    conn = op.get_bind()
    held = conn.execute(
        text(
            "SELECT 'wavescan', count(*) FROM wavescan WHERE color = :c "
            "UNION ALL SELECT 'filmthickness', count(*) FROM filmthickness WHERE color = :c "
            "UNION ALL SELECT 'film_standard', count(*) FROM film_standard WHERE color_name = :c "
            "UNION ALL SELECT 'cf_standard', count(*) FROM cf_standard WHERE color_name = :c"
        ),
        {"c": CANONICAL},
    ).all()
    stored = [(t, n) for t, n in held if n]
    if stored:
        raise RuntimeError(
            f"T64 downgrade refused: rows are stored under {CANONICAL!r} {stored}; "
            f"removing the name would orphan them (ADR 0005)."
        )
    # 6. views back to their stored-colour text
    _swap(conn, FT_VIEW, ((FT_COLOR_NEW, FT_COLOR_OLD), (FT_FROM_NEW, FT_FROM_OLD)))
    _swap(conn, WS_VIEW, ((WS_COLOR_NEW, WS_COLOR_OLD), (WS_JOIN_NEW, WS_JOIN_OLD)))
    # 5. only the T64 alias rows
    conn.execute(
        text("DELETE FROM ref_color_alias WHERE color_name = :c AND note = :note"),
        {"c": CANONICAL, "note": ALIAS_NOTE},
    )
    # 4. offers back, canonical offer rows gone
    for plant, name in UNOFFER:
        conn.execute(
            text(
                "UPDATE ref_plant_color SET is_offered = true, updated_at = now() "
                "WHERE plant_code = :p AND color_name = :n"
            ),
            {"p": plant, "n": name},
        )
    conn.execute(
        text("DELETE FROM ref_plant_color WHERE color_name = :c"), {"c": CANONICAL}
    )
    # 3-2. old names reactivated, canonical name dropped
    conn.execute(
        text(
            "UPDATE ref_color SET merged_into = NULL, is_active = true "
            "WHERE merged_into = :c"
        ),
        {"c": CANONICAL},
    )
    conn.execute(text("DELETE FROM ref_color WHERE color_name = :c"), {"c": CANONICAL})
    # 1. pointer gone
    op.execute("DROP TRIGGER IF EXISTS trg_ref_color_merge_one_level ON ref_color")
    op.execute("DROP FUNCTION IF EXISTS ref_color_merge_one_level()")
    op.execute("ALTER TABLE ref_color DROP COLUMN IF EXISTS merged_into")
