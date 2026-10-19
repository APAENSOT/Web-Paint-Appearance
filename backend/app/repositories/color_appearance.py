"""Colour appearance SQL (T116). Append-only ``color_appearance``.

INSERT and SELECT only (ADR 0005, D-116-4). Reads ``ref_color`` and
``ref_plant_color`` to validate and list; never writes them, nor any fact,
standard, upload or point table (D-116-8).
"""

from __future__ import annotations

from sqlalchemy import Connection, text

#: The persisted shape every read and the save return. ``saved_by`` is the
#: person's display name, never their UUID (D-116-6).
_ROW = (
    "a.appearance_id, a.color_name, a.hex, a.revision, a.created_by, "
    "a.created_at AS saved_at, u.display_name AS saved_by"
)


def color(conn: Connection, color_name: str) -> dict | None:
    """``{color_name, merged_into}`` or None for an unknown name. Exact match."""
    row = conn.execute(
        text("SELECT color_name, merged_into FROM ref_color WHERE color_name = :c"),
        {"c": color_name},
    ).mappings().first()
    return dict(row) if row else None


def is_offered(conn: Connection, plant_code: str, color_name: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT is_offered FROM ref_plant_color "
                "WHERE plant_code = :p AND color_name = :c"
            ),
            {"p": plant_code, "c": color_name},
        ).scalar()
    )


def plant_colors(conn: Connection, plant_code: str) -> list[dict]:
    """Every colour the plant lists, offered or not, with its canonical name."""
    rows = conn.execute(
        text(
            "SELECT pc.color_name, pc.family_name, pc.is_offered, rc.merged_into "
            "  FROM ref_plant_color pc "
            "  JOIN ref_color rc ON rc.color_name = pc.color_name "
            " WHERE pc.plant_code = :p ORDER BY pc.color_name"
        ),
        {"p": plant_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def latest_per_color(conn: Connection, plant_code: str) -> list[dict]:
    """Each colour's own latest revision at this plant, with its canonical name."""
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT ON (a.color_name) {_ROW}, rc.merged_into
              FROM color_appearance a
              JOIN ref_color rc ON rc.color_name = a.color_name
              LEFT JOIN app_user u ON u.id = a.created_by
             WHERE a.plant_code = :p
             ORDER BY a.color_name, a.revision DESC
            """
        ),
        {"p": plant_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def at_revision(
    conn: Connection, plant_code: str, color_name: str, revision: int | None = None
) -> dict | None:
    """One colour's row at ``revision``, or its latest when ``revision`` is None."""
    row = conn.execute(
        text(
            f"""
            SELECT {_ROW}
              FROM color_appearance a
              LEFT JOIN app_user u ON u.id = a.created_by
             WHERE a.plant_code = :p AND a.color_name = :c
               AND (CAST(:r AS integer) IS NULL OR a.revision = :r)
             ORDER BY a.revision DESC LIMIT 1
            """
        ),
        {"p": plant_code, "c": color_name, "r": revision},
    ).mappings().first()
    return dict(row) if row else None


def insert(
    conn: Connection,
    *,
    plant_code: str,
    color_name: str,
    revision: int,
    hex_value: str,
    actor_user_id: str | None,
) -> dict:
    """Append one revision. A taken revision raises the UNIQUE violation."""
    appearance_id = conn.execute(
        text(
            "INSERT INTO color_appearance "
            "(plant_code, color_name, revision, hex, created_by) "
            "VALUES (:p, :c, :r, :h, :by) RETURNING appearance_id"
        ),
        {"p": plant_code, "c": color_name, "r": revision, "h": hex_value,
         "by": actor_user_id or None},
    ).scalar_one()
    found = at_revision(conn, plant_code, color_name, revision)
    assert found is not None and found["appearance_id"] == appearance_id
    return found
