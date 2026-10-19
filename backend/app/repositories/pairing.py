"""Wave Scan <-> Film pairing SQL (AR01). SELECT only.

Reads the **active** views as they are (D-AR01-5): ``v_wavescan_active`` and
``filmthickness_active``, with no filter of their own beyond the plant. The
film car number is read at query time with ``substring(job_no FROM
pattern)`` (D-AR01-1); a NULL pattern gives no car number. Never writes a
fact, an upload or a reference row (ADR 0005).
"""

from __future__ import annotations

from sqlalchemy import Connection, text

WS_VIEW = "v_wavescan_active"
FILM_VIEW = "filmthickness_active"


def car_rule(conn: Connection, plant_code: str) -> dict | None:
    row = conn.execute(
        text("SELECT pattern, note FROM ref_plant_film_car_rule WHERE plant_code = :p"),
        {"p": plant_code},
    ).mappings().first()
    return dict(row) if row else None


def wavescan_cars(conn: Connection, plant_code: str) -> list[dict]:
    """One row per car x model x colour x date. A reading with no serial is no car."""
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT serial_no AS car_no, model, color, measured_date
              FROM {WS_VIEW}
             WHERE plant = :p AND serial_no IS NOT NULL
               AND NOT date_is_month_only  -- RO18 (B4): never paired
            """
        ),
        {"p": plant_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def film_jobs(conn: Connection, plant_code: str, pattern: str | None) -> list[dict]:
    """One row per job_no x model x colour x date, with its car number or None."""
    rows = conn.execute(
        text(
            f"""
            SELECT j.job_no, substring(j.job_no FROM CAST(:pattern AS text)) AS car_no,
                   j.model, j.color, j.measured_date
              FROM (SELECT DISTINCT job_no, model, color, measured_date
                      FROM {FILM_VIEW}
                     WHERE plant = :p
                       AND NOT date_is_month_only) j  -- RO18 (B4): never paired
            """
        ),
        {"p": plant_code, "pattern": pattern},
    ).mappings().all()
    return [dict(r) for r in rows]


def pair_groups(conn: Connection, plant_code: str) -> list[dict]:
    """Every group mapped at the plant: its Wave Scan zones and film point count."""
    rows = conn.execute(
        text(
            """
            SELECT g.pair_group,
                   COALESCE(w.zones, ARRAY[]::text[]) AS wavescan_zones,
                   COALESCE(f.points, 0) AS film_points
              FROM (SELECT pair_group FROM ref_pair_ws_zone WHERE plant_code = :p
                    UNION
                    SELECT pair_group FROM ref_pair_film_point WHERE plant_code = :p) g
              LEFT JOIN (SELECT pair_group, array_agg(DISTINCT zone_code ORDER BY zone_code) AS zones
                           FROM ref_pair_ws_zone WHERE plant_code = :p GROUP BY 1) w
                     USING (pair_group)
              LEFT JOIN (SELECT pair_group, count(DISTINCT point_code) AS points
                           FROM ref_pair_film_point WHERE plant_code = :p GROUP BY 1) f
                     USING (pair_group)
             ORDER BY g.pair_group
            """
        ),
        {"p": plant_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def wavescan_car_groups(conn: Connection, plant_code: str) -> list[tuple[str, str]]:
    """(car_no, pair_group) for every car with a reading on a mapped zone."""
    return [
        tuple(r)
        for r in conn.execute(
            text(
                f"""
                SELECT DISTINCT w.serial_no, z.pair_group
                  FROM {WS_VIEW} w
                  JOIN ref_pair_ws_zone z
                    ON z.plant_code = w.plant AND z.model_code = w.model
                   AND z.zone_code = w.checkzone
                 WHERE w.plant = :p AND w.serial_no IS NOT NULL
                """
            ),
            {"p": plant_code},
        ).all()
    ]


def film_car_groups(
    conn: Connection, plant_code: str, pattern: str | None
) -> list[tuple[str, str]]:
    """(car_no, pair_group) for every numbered car with a reading on a mapped point."""
    return [
        tuple(r)
        for r in conn.execute(
            text(
                f"""
                SELECT DISTINCT c.car_no, c.pair_group
                  FROM (SELECT substring(d.job_no FROM CAST(:pattern AS text)) AS car_no,
                               d.pair_group
                          -- Distinct first: the regex then runs once per job, not per reading.
                          FROM (SELECT DISTINCT f.job_no, m.pair_group
                                  FROM {FILM_VIEW} f
                                  JOIN ref_pair_film_point m
                                    ON m.plant_code = f.plant AND m.model_code = f.model
                                   AND m.point_code = f.point_code
                                 WHERE f.plant = :p) d) c
                 WHERE c.car_no IS NOT NULL
                """
            ),
            {"p": plant_code, "pattern": pattern},
        ).all()
    ]


def wavescan_unmapped(conn: Connection, plant_code: str) -> list[tuple[str, int]]:
    """(zone_code, readings) for active readings on a zone with no pair group."""
    return [
        tuple(r)
        for r in conn.execute(
            text(
                f"""
                SELECT w.checkzone, count(*)
                  FROM {WS_VIEW} w
                  LEFT JOIN ref_pair_ws_zone z
                    ON z.plant_code = w.plant AND z.model_code = w.model
                   AND z.zone_code = w.checkzone
                 WHERE w.plant = :p AND z.zone_code IS NULL
                 GROUP BY 1 ORDER BY 2 DESC, 1
                """
            ),
            {"p": plant_code},
        ).all()
    ]


def film_unmapped(conn: Connection, plant_code: str) -> list[tuple[str, int]]:
    """(point_code, readings) for active readings on a point with no pair group."""
    return [
        tuple(r)
        for r in conn.execute(
            text(
                f"""
                SELECT f.point_code, count(*)
                  FROM {FILM_VIEW} f
                  LEFT JOIN ref_pair_film_point m
                    ON m.plant_code = f.plant AND m.model_code = f.model
                   AND m.point_code = f.point_code
                 WHERE f.plant = :p AND m.point_code IS NULL
                 GROUP BY 1 ORDER BY 2 DESC, 1
                """
            ),
            {"p": plant_code},
        ).all()
    ]
