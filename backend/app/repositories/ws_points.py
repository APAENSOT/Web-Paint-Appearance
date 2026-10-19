"""T114: Point Check's Wave Scan reads and writes.

One plant x model's live Wave Scan list (`ref_plant_ws_point`), its counted
setting (`ws_point_setting`, revision 0037) and the vocabulary a new point
is picked from (`ref_checkzone`, `ref_model_zone`).

**Append-only and insert-only.** Counted is a new `ws_point_setting` row,
never an UPDATE: the latest row wins and no row means counted (D-114-2). An
added point is an INSERT of a list row -- and, for a code nobody has used
before, of its `ref_checkzone` and `ref_model_zone` rows. A retire is the
existing `repositories.mappings.retire_plant_panels`, the only UPDATE the
application holds on the list (0031). Nothing here deletes anything.

Filters are bound parameters; no caller value is formatted into SQL.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import Connection, text

#: The latest counted setting of one point. No row -> NULL -> counted.
_LATEST = """
    LEFT JOIN LATERAL (
         SELECT s.counted, s.reason, s.created_by, s.created_at
           FROM ws_point_setting s
          WHERE s.plant_code = p.plant_code
            AND s.model_code = p.model_code
            AND s.zone_code = p.zone_code
          ORDER BY s.setting_id DESC
          LIMIT 1
         ) s ON true
"""

#: T115 (D-115-1): "Last change" names the person, never the uuid. Null
#: when no setting row names anyone; "-" for a user with no name on file.
_CHANGED_BY = """
    CASE WHEN s.created_by IS NULL THEN NULL
         ELSE COALESCE(NULLIF(btrim(u.display_name), ''), '-') END
"""

#: zone_no is a smallint in 1..40 (`ref_model_zone.ck_zone_no`).
MAX_ZONE_NO = 40


def live_lists(conn: Connection, plant_code: str) -> dict[str, frozenset[str]]:
    """T114-FIX (D-114F-1): this plant's **live, non-extra** codes per model.

    What a Wave Scan car is complete against (`domain.completeness`). Counted
    is not read (D-114F-2). A model with no live row is absent, so its cars
    fall back to `ref_model.expected_zone_count` (D-114F-4).
    `v_car_completeness` (0038) applies the same predicate in SQL.
    """
    rows = conn.execute(
        text(
            "SELECT model_code, zone_code FROM ref_plant_ws_point "
            "WHERE plant_code = :plant AND retired_at IS NULL AND NOT is_extra"
        ),
        {"plant": plant_code},
    ).all()
    found: dict[str, set[str]] = {}
    for model_code, zone_code in rows:
        found.setdefault(model_code, set()).add(zone_code)
    return {model: frozenset(codes) for model, codes in found.items()}


def models(conn: Connection, plant_code: str) -> list[dict]:
    """Every Wave Scan model this plant has a live list for."""
    rows = conn.execute(
        text(
            f"""
            SELECT p.model_code, m.display_name,
                   count(*) AS point_count,
                   count(*) FILTER (WHERE COALESCE(s.counted, true)) AS counted_count,
                   count(*) FILTER (WHERE p.is_extra) AS extra_count
              FROM ref_plant_ws_point p
              JOIN ref_model m ON m.model_code = p.model_code
              {_LATEST}
             WHERE p.plant_code = :plant AND p.retired_at IS NULL
               AND m.wavescan_ok
             GROUP BY p.model_code, m.display_name
             ORDER BY p.model_code
            """
        ),
        {"plant": plant_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def live_points(conn: Connection, plant_code: str, model_code: str) -> list[dict]:
    """The live list in walk order, with the latest counted row of each."""
    rows = conn.execute(
        text(
            f"""
            SELECT p.point_no, p.zone_code, p.tolerance_group, p.is_extra,
                   p.note, p.created_at,
                   COALESCE(s.counted, true) AS counted,
                   s.reason, {_CHANGED_BY} AS changed_by,
                   s.created_at AS changed_at
              FROM ref_plant_ws_point p
              JOIN v_point_walk_order w ON w.plant_code=p.plant_code
                   AND w.model_code=p.model_code AND w.point_code=p.zone_code
                   AND w.domain='WAVESCAN'
              {_LATEST}
              LEFT JOIN app_user u ON u.id = s.created_by
             WHERE p.plant_code = :plant AND p.model_code = :model
               AND p.retired_at IS NULL
             ORDER BY w.walk_rank
            """
        ),
        {"plant": plant_code, "model": model_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def retired_points(conn: Connection, plant_code: str, model_code: str) -> list[dict]:
    """What this list used to walk, in walk order, with when and why."""
    rows = conn.execute(
        text(
            """
            SELECT point_no, zone_code, tolerance_group, is_extra,
                   retired_at, retired_reason
              FROM ref_plant_ws_point
             WHERE plant_code = :plant AND model_code = :model
               AND retired_at IS NOT NULL
             ORDER BY point_no, zone_code
            """
        ),
        {"plant": plant_code, "model": model_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def point_row(
    conn: Connection, plant_code: str, model_code: str, zone_code: str
) -> dict | None:
    """One list row by its primary key, live or retired."""
    row = conn.execute(
        text(
            """
            SELECT zone_code, point_no, tolerance_group, is_extra,
                   retired_at, retired_reason
              FROM ref_plant_ws_point
             WHERE plant_code = :plant AND model_code = :model
               AND zone_code = :zone
            """
        ),
        {"plant": plant_code, "model": model_code, "zone": zone_code},
    ).mappings().first()
    return dict(row) if row else None


def point_states(conn: Connection, plant_code: str, model_code: str) -> dict[str, dict]:
    """``{zone_code: {retired, counted, is_extra}}`` for every row of a list.

    The tags History and Comparison put on a reading's point. A checkzone the
    list has never held is simply absent: it is not a point of this plant x
    model, so there is nothing to tag.
    """
    rows = conn.execute(
        text(
            f"""
            SELECT p.zone_code, p.retired_at IS NOT NULL AS retired,
                   COALESCE(s.counted, true) AS counted, p.is_extra
              FROM ref_plant_ws_point p
              {_LATEST}
             WHERE p.plant_code = :plant AND p.model_code = :model
            """
        ),
        {"plant": plant_code, "model": model_code},
    ).mappings().all()
    return {
        r["zone_code"]: {
            "retired": bool(r["retired"]),
            "counted": bool(r["counted"]),
            "is_extra": bool(r["is_extra"]),
        }
        for r in rows
    }


def insert_settings(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    rows: Sequence[tuple[str, bool]],
    reason: str,
    actor: str | None,
) -> int:
    """One **new** row per point (D-114-2). Never an UPDATE, never a DELETE."""
    written = 0
    for zone_code, counted in rows:
        written += conn.execute(
            text(
                """
                INSERT INTO ws_point_setting
                    (plant_code, model_code, zone_code, counted, reason, created_by)
                VALUES (:plant, :model, :zone, :counted, :reason,
                        CAST(:actor AS uuid))
                """
            ),
            {
                "plant": plant_code, "model": model_code, "zone": zone_code,
                "counted": bool(counted), "reason": reason, "actor": actor or None,
            },
        ).rowcount
    return written


def zone_choices(conn: Connection) -> list[dict]:
    """Every `ref_checkzone` code with its Hor / Ver, by code."""
    rows = conn.execute(
        text(
            "SELECT zone_code, tolerance_group FROM ref_checkzone ORDER BY zone_code"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def checkzone(conn: Connection, zone_code: str) -> dict | None:
    row = conn.execute(
        text(
            "SELECT zone_code, tolerance_group, panel_group FROM ref_checkzone "
            "WHERE zone_code = :zone"
        ),
        {"zone": zone_code},
    ).mappings().first()
    return dict(row) if row else None


def checkzone_twin(conn: Connection, zone_code: str) -> str | None:
    """An existing code equal to this one ignoring case and spaces (D-114-6).

    Only a **different** spelling is a twin: the same code exactly is the
    code itself, and picking it is the right answer.
    """
    row = conn.execute(
        text(
            """
            SELECT zone_code FROM ref_checkzone
             WHERE lower(regexp_replace(zone_code, '\\s', '', 'g'))
                 = lower(regexp_replace(:zone, '\\s', '', 'g'))
               AND zone_code <> :zone
             ORDER BY zone_code
             LIMIT 1
            """
        ),
        {"zone": zone_code},
    ).first()
    return row[0] if row else None


def insert_checkzone(
    conn: Connection, *, zone_code: str, panel_group: str, tolerance_group: str
) -> None:
    """A code nobody has used before. Its name is the code as typed.

    `ck_zone_rule` is the backstop on Hor / Ver: the caller reads it off the
    name by the same rule, and a disagreement would be refused here.
    """
    conn.execute(
        text(
            """
            INSERT INTO ref_checkzone (zone_code, zone_name, panel_group, tolerance_group)
            VALUES (:zone, :zone, :group, :tol)
            """
        ),
        {"zone": zone_code, "group": panel_group, "tol": tolerance_group},
    )


def model_zone_no(conn: Connection, model_code: str, zone_code: str) -> int | None:
    row = conn.execute(
        text(
            "SELECT zone_no FROM ref_model_zone "
            "WHERE model_code = :model AND zone_code = :zone"
        ),
        {"model": model_code, "zone": zone_code},
    ).first()
    return int(row[0]) if row else None


def next_zone_no(conn: Connection, model_code: str) -> int:
    """The number after the model's highest `zone_no` (1 for a model with none)."""
    return int(
        conn.execute(
            text(
                "SELECT COALESCE(max(zone_no), 0) + 1 FROM ref_model_zone "
                "WHERE model_code = :model"
            ),
            {"model": model_code},
        ).scalar_one()
    )


def insert_model_zone(
    conn: Connection, *, model_code: str, zone_code: str, zone_no: int
) -> None:
    conn.execute(
        text(
            "INSERT INTO ref_model_zone (model_code, zone_code, zone_no) "
            "VALUES (:model, :zone, :no)"
        ),
        {"model": model_code, "zone": zone_code, "no": zone_no},
    )


def next_point_no(conn: Connection, plant_code: str, model_code: str) -> int:
    """The end of the walk: the highest **live** `point_no` plus one."""
    return int(
        conn.execute(
            text(
                "SELECT COALESCE(max(point_no), 0) + 1 FROM ref_plant_ws_point "
                "WHERE plant_code = :plant AND model_code = :model "
                "  AND retired_at IS NULL"
            ),
            {"plant": plant_code, "model": model_code},
        ).scalar_one()
    )


def insert_point(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    zone_code: str,
    point_no: int,
    tolerance_group: str,
    note: str,
    is_extra: bool = True,
) -> None:
    """One point at the end of the walk (D-114-5, D-114-6). Extra unless an
    Admin counts it in completeness (RO17 D-RO17-7)."""
    conn.execute(
        text(
            """
            INSERT INTO ref_plant_ws_point
                (plant_code, model_code, zone_code, point_no, tolerance_group,
                 note, is_extra)
            VALUES (:plant, :model, :zone, :no, :tol, :note, :extra)
            """
        ),
        {
            "plant": plant_code, "model": model_code, "zone": zone_code,
            "no": point_no, "tol": tolerance_group, "note": note[:2000],
            "extra": bool(is_extra),
        },
    )


def restore_point(conn: Connection, plant_code: str, model_code: str, zone_code: str) -> int:
    """RO17 (D-RO17-9): clear the two retire columns, the only UPDATE held."""
    return conn.execute(
        text(
            "UPDATE ref_plant_ws_point SET retired_at = NULL, retired_reason = NULL "
            "WHERE plant_code = :plant AND model_code = :model AND zone_code = :zone "
            "  AND retired_at IS NOT NULL"
        ),
        {"plant": plant_code, "model": model_code, "zone": zone_code},
    ).rowcount


def live_point_at(
    conn: Connection, plant_code: str, model_code: str, point_no: int
) -> str | None:
    """The live point holding ``point_no`` on this list, if any."""
    return conn.execute(
        text(
            "SELECT zone_code FROM ref_plant_ws_point WHERE plant_code = :plant "
            "AND model_code = :model AND point_no = :no AND retired_at IS NULL ORDER BY zone_code LIMIT 1"
        ),
        {"plant": plant_code, "model": model_code, "no": point_no},
    ).scalar()


def offered_models(conn: Connection, plant_code: str) -> list[str]:
    """RO17 (D-RO17-10): Wave Scan models this plant offers (`is_offered`,
    `wavescan_ok`), by model_code."""
    return [
        r[0] for r in conn.execute(
            text(
                "SELECT pm.model_code FROM ref_plant_model pm "
                "JOIN ref_model m USING (model_code) "
                "WHERE pm.plant_code = :plant AND pm.is_offered AND m.wavescan_ok "
                "ORDER BY pm.model_code"
            ),
            {"plant": plant_code},
        ).all()
    ]


def incomplete_cars(conn: Connection, plant_code: str, model_code: str) -> int:
    """INCOMPLETE cars of `v_car_completeness` for one plant x model."""
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM v_car_completeness WHERE plant = :plant "
                "AND model = :model AND completeness = 'INCOMPLETE'"
            ),
            {"plant": plant_code, "model": model_code},
        ).scalar_one()
    )


__all__ = [
    "MAX_ZONE_NO",
    "checkzone",
    "checkzone_twin",
    "incomplete_cars",
    "insert_checkzone",
    "insert_model_zone",
    "insert_point",
    "insert_settings",
    "live_lists",
    "live_point_at",
    "live_points",
    "model_zone_no",
    "models",
    "next_point_no",
    "next_zone_no",
    "offered_models",
    "point_row",
    "point_states",
    "restore_point",
    "retired_points",
    "zone_choices",
]
