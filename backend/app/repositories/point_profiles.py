"""Model Studio point profile SQL. Append-only ``point_profile_anchor`` (0044).

INSERT and SELECT only (ADR 0005). Reads ``ref_model`` and ``app_user``;
never writes them, nor any fact, standard, upload, appearance or Point Check
table. The Point Check lists are read through ``ws_points`` and
``filmthickness``, the same reads Point Check itself shows.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

#: The persisted shape every read and write returns. ``saved_by`` is the
#: person's display name, never their UUID.
_ROW = (
    "a.anchor_event_id, a.point_key, a.revision, a.action, a.asset_version, "
    "a.mesh_name, a.body_zone, a.pos_x, a.pos_y, a.pos_z, a.nrm_x, a.nrm_y, "
    "a.nrm_z, a.created_by, a.created_at AS saved_at, u.display_name AS saved_by"
)
_KEY = "a.plant_code = :p AND a.model_code = :m AND a.domain = :d"


def model_exists(conn: Connection, model_code: str) -> bool:
    """Exact ``ref_model`` code. Aliases are not resolved: no guessed names."""
    return bool(
        conn.execute(
            text("SELECT 1 FROM ref_model WHERE model_code = :m"), {"m": model_code}
        ).scalar()
    )


def latest_per_point(conn: Connection, plant: str, model: str, domain: str) -> list[dict]:
    """Each point's latest row in this profile, placed or removed."""
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT ON (a.point_key) {_ROW}
              FROM point_profile_anchor a
              LEFT JOIN app_user u ON u.id = a.created_by
             WHERE {_KEY}
             ORDER BY a.point_key, a.revision DESC
            """
        ),
        {"p": plant, "m": model, "d": domain},
    ).mappings().all()
    return [dict(r) for r in rows]


def profile_stats(conn: Connection, plant: str, model: str, domain: str) -> tuple[int, object]:
    """``(rows ever written, newest created_at)``; ``(0, None)`` when unconfigured."""
    count, last = conn.execute(
        text(
            f"SELECT count(*), max(a.created_at) FROM point_profile_anchor a WHERE {_KEY}"
        ),
        {"p": plant, "m": model, "d": domain},
    ).one()
    return int(count), last


def at_revision(
    conn: Connection, plant: str, model: str, domain: str, point_key: str,
    revision: int | None = None,
) -> dict | None:
    """One point's row at ``revision``, or its latest when ``revision`` is None."""
    row = conn.execute(
        text(
            f"""
            SELECT {_ROW}
              FROM point_profile_anchor a
              LEFT JOIN app_user u ON u.id = a.created_by
             WHERE {_KEY} AND a.point_key = :k
               AND (CAST(:r AS integer) IS NULL OR a.revision = :r)
             ORDER BY a.revision DESC LIMIT 1
            """
        ),
        {"p": plant, "m": model, "d": domain, "k": point_key, "r": revision},
    ).mappings().first()
    return dict(row) if row else None


def insert(
    conn: Connection,
    *,
    plant: str,
    model: str,
    domain: str,
    point_key: str,
    revision: int,
    anchor: dict | None,
    actor_user_id: str | None,
) -> dict:
    """Append one revision: a placement, or a removal when ``anchor`` is None.

    A taken revision raises the UNIQUE violation."""
    a = anchor or {}
    pos, nrm = a.get("position") or (None,) * 3, a.get("normal") or (None,) * 3
    event_id = conn.execute(
        text(
            """
            INSERT INTO point_profile_anchor
                (plant_code, model_code, domain, point_key, revision, action,
                 asset_version, mesh_name, body_zone,
                 pos_x, pos_y, pos_z, nrm_x, nrm_y, nrm_z, created_by)
            VALUES (:p, :m, :d, :k, :r, :action, :asset, :mesh, :zone,
                    :px, :py, :pz, :nx, :ny, :nz, CAST(:by AS uuid))
            RETURNING anchor_event_id
            """
        ),
        {
            "p": plant, "m": model, "d": domain, "k": point_key, "r": revision,
            "action": "place" if anchor else "remove",
            "asset": a.get("asset_version"), "mesh": a.get("mesh_name"),
            "zone": a.get("body_zone"),
            "px": pos[0], "py": pos[1], "pz": pos[2],
            "nx": nrm[0], "ny": nrm[1], "nz": nrm[2],
            "by": actor_user_id or None,
        },
    ).scalar_one()
    found = at_revision(conn, plant, model, domain, point_key, revision)
    assert found is not None and found["anchor_event_id"] == event_id
    return found
