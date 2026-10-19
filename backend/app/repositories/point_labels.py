"""RO17: point labels and the aliases screen, both domains.

A point keeps its code; its **label** is the word its plant uses
(`ref_plant_ws_point_label` / `ref_plant_film_point_label`, revision 0047).
Append-only: the current label is the newest row (highest ``label_id``); a
rename is a new row. The only UPDATE here is the two retire columns, on an
earlier label or on one alias row of the aliases screen (D-RO17-13).

Table and column names come from the fixed `TABLES` map, never from a
caller; every caller value is a bound parameter.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

#: domain -> (label table, point table, code column)
TABLES = {
    "wavescan": ("ref_plant_ws_point_label", "ref_plant_ws_point", "zone_code"),
    "film": ("ref_plant_film_point_label", "ref_plant_film_point", "point_code"),
}


def lock_list(conn: Connection, domain: str, plant: str, model: str) -> None:
    """One plant x model x domain list at a time, until the transaction ends."""
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"ro17:{domain}:{plant}:{model}"},
    )


def points(
    conn: Connection, domain: str, plant: str, model: str | None = None
) -> list[dict]:
    """Every point (live and retired) with its current label (code if none).

    Ordered model, point_no, code. ``model`` None = every list of the plant.
    """
    label_t, point_t, code = TABLES[domain]
    rows = conn.execute(
        text(
            f"""
            SELECT p.model_code, p.{code} AS code, p.point_no,
                   p.retired_at IS NULL AS live,
                   COALESCE(l.label, p.{code}) AS label
              FROM {point_t} p
              LEFT JOIN LATERAL (
                   SELECT x.label FROM {label_t} x
                    WHERE x.plant_code = p.plant_code
                      AND x.model_code = p.model_code AND x.{code} = p.{code}
                    ORDER BY x.label_id DESC LIMIT 1
                   ) l ON true
             WHERE p.plant_code = :plant
               AND (CAST(:model AS text) IS NULL OR p.model_code = :model)
             ORDER BY p.model_code, p.point_no, p.{code}
            """
        ),
        {"plant": plant, "model": model},
    ).mappings().all()
    return [dict(r) for r in rows]


def label_rows(conn: Connection, domain: str, plant: str, model: str) -> list[dict]:
    """Every label row of one list, with whether it is its point's current one."""
    label_t, point_t, code = TABLES[domain]
    rows = conn.execute(
        text(
            f"""
            SELECT l.label_id, l.{code} AS code, l.label, l.label_norm,
                   l.set_at, l.reason, l.retired_at, l.retired_reason,
                   l.label_id = max(l.label_id) OVER (PARTITION BY l.{code})
                       AS is_current,
                   p.retired_at IS NULL AS point_live
              FROM {label_t} l
              JOIN {point_t} p USING (plant_code, model_code, {code})
             WHERE l.plant_code = :plant AND l.model_code = :model
             ORDER BY l.label_id
            """
        ),
        {"plant": plant, "model": model},
    ).mappings().all()
    return [dict(r) for r in rows]


def insert_label(
    conn: Connection, domain: str, *, plant: str, model: str, code: str,
    label: str, label_norm: str, reason: str, actor: str | None,
) -> int:
    label_t, _, code_col = TABLES[domain]
    return int(
        conn.execute(
            text(
                f"""
                INSERT INTO {label_t}
                    (plant_code, model_code, {code_col}, label, label_norm,
                     set_by, reason)
                VALUES (:plant, :model, :code, :label, :norm,
                        CAST(:actor AS uuid), :reason)
                RETURNING label_id
                """
            ),
            {
                "plant": plant, "model": model, "code": code, "label": label,
                "norm": label_norm, "actor": actor or None, "reason": reason,
            },
        ).scalar_one()
    )


# =====================================================================
# the aliases screen (D-RO17-13)
# =====================================================================
def zone_map_rows(conn: Connection, plant: str, model: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT map_id, raw_zone_text, zone_code, confidence, note,
                   created_at, retired_at, retired_reason
              FROM ref_plant_zone_map
             WHERE plant_code = :plant AND model_code = :model
             ORDER BY raw_zone_text, map_id
            """
        ),
        {"plant": plant, "model": model},
    ).mappings().all()
    return [dict(r) for r in rows]


def global_alias_rows(conn: Connection, plant: str, model: str) -> list[dict]:
    """`ref_checkzone_alias` rows whose zone is a live point of this list."""
    rows = conn.execute(
        text(
            """
            SELECT a.raw_value, a.zone_code, a.note
              FROM ref_checkzone_alias a
              JOIN ref_plant_ws_point p
                ON p.zone_code = a.zone_code AND p.plant_code = :plant
               AND p.model_code = :model AND p.retired_at IS NULL
             ORDER BY a.raw_value
            """
        ),
        {"plant": plant, "model": model},
    ).mappings().all()
    return [dict(r) for r in rows]


def film_alias_rows(conn: Connection, plant: str, model: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT alias_id, raw_location_norm, point_code, reason AS note,
                   created_at, retired_at, retired_reason
              FROM ref_film_point_alias
             WHERE plant_code = :plant AND model_code = :model
             ORDER BY raw_location_norm, alias_id
            """
        ),
        {"plant": plant, "model": model},
    ).mappings().all()
    return [dict(r) for r in rows]


def location_map_rows(conn: Connection, plant: str, model: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT raw_location_norm, point_code, note, created_at,
                   retired_at, retired_reason
              FROM ref_film_location_map
             WHERE plant_code = :plant AND model_code = :model
             ORDER BY raw_location_norm
            """
        ),
        {"plant": plant, "model": model},
    ).mappings().all()
    return [dict(r) for r in rows]


def raw_label_counts(
    conn: Connection, domain: str, plant: str, model: str
) -> list[tuple[str, int]]:
    """``(raw label as written, active facts)`` of one plant x model.

    The active views read COMMITTED, unsuperseded, non-duplicate facts only.
    """
    if domain == "wavescan":
        sql = (
            "SELECT src_zone_text, count(*) FROM v_wavescan_active "
            "WHERE plant = :plant AND model = :model AND src_zone_text IS NOT NULL "
            "GROUP BY src_zone_text"
        )
    else:
        sql = (
            "SELECT src_location_text, count(*) FROM filmthickness_active "
            "WHERE plant = :plant AND model = :model AND src_location_text IS NOT NULL "
            "GROUP BY src_location_text"
        )
    return [
        (raw, int(n))
        for raw, n in conn.execute(text(sql), {"plant": plant, "model": model}).all()
    ]


#: kind -> (table, key column, extra scope) for the one-row retire UPDATE.
_RETIRE = {
    "zone_map": ("ref_plant_zone_map", "map_id = CAST(:id AS bigint)"),
    "film_alias": ("ref_film_point_alias", "alias_id = CAST(:id AS bigint)"),
    "location_map": ("ref_film_location_map", "raw_location_norm = :id"),
    # RO18 (B5): an uploader's "Not a point of this list" answer.
    "not_a_point": ("ref_plant_film_tail_label", "label_norm = :id AND not_a_point"),
    "earlier_label:wavescan": (TABLES["wavescan"][0], "label_id = CAST(:id AS bigint)"),
    "earlier_label:film": (TABLES["film"][0], "label_id = CAST(:id AS bigint)"),
}


def retire_row(
    conn: Connection, kind: str, *, plant: str, model: str, alias_id: str,
    reason: str,
) -> int:
    """Set ``retired_at`` / ``retired_reason`` on one live row. Rows changed."""
    table, where = _RETIRE[kind]
    return conn.execute(
        text(
            f"UPDATE {table} SET retired_at = now(), retired_reason = :reason "
            f"WHERE plant_code = :plant AND model_code = :model AND {where} "
            f"AND retired_at IS NULL"
        ),
        {"plant": plant, "model": model, "id": alias_id, "reason": reason},
    ).rowcount


__all__ = [
    "TABLES",
    "film_alias_rows",
    "global_alias_rows",
    "insert_label",
    "label_rows",
    "location_map_rows",
    "lock_list",
    "points",
    "raw_label_counts",
    "retire_row",
    "zone_map_rows",
]
