"""Analysis report SQL (AR03). SELECT only; no threshold, no status.

* Band rows read ``COUNTED_VIEW``, the set the dashboard counts (band design
  D-AR03-1), joined to ``ref_checkzone`` for the panel group.
* Paired rows follow AR01: the active views, the plant's film car rule and the
  AR01/AR02 pair maps; one row per paired car x pair group x film layer.
Never writes a fact, an upload or a reference row (ADR 0005).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from app.repositories.filmthickness import ACTIVE_VIEW as FILM_VIEW
from app.repositories.measurements import ACTIVE_VIEW as WS_ACTIVE_VIEW, COUNTED_VIEW

BANDS = ("du", "wa", "wb", "wc", "wd", "we", "cf")


def _filters(alias: str, models: list[str] | None, colors: list[str] | None) -> tuple[str, dict]:
    sql, params = "", {}
    if models:
        sql += f" AND {alias}.model = ANY(:models)"
        params["models"] = list(models)
    if colors:
        sql += f" AND {alias}.color = ANY(:colors)"
        params["colors"] = list(colors)
    return sql, params


def band_rows(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    bounds: tuple[date, date],
    models: list[str] | None,
    colors: list[str] | None,
) -> list[dict]:
    """Every counted reading of the month: its car, H/V, panel group, model, colour and the 7 bands."""
    extra, params = _filters("w", models, colors)
    if plant_scope is not None:
        extra += " AND w.plant = ANY(:plant_scope)"
        params["plant_scope"] = list(plant_scope)
    rows = conn.execute(
        text(
            f"""
            SELECT w.measurement_id, w.serial_no, w.tolerance_group, z.panel_group, w.model, w.color,
                   {', '.join(f'w.{b}' for b in BANDS)},
                   w.lw, w.sw, w.doi, w.b, w.checkzone, w.measured_date
              FROM {COUNTED_VIEW} w
              LEFT JOIN ref_checkzone z ON z.zone_code = w.checkzone
             WHERE w.plant = :plant
               AND w.measured_date BETWEEN :date_from AND :date_to{extra}
            """
        ),
        {"plant": plant_code, "date_from": bounds[0], "date_to": bounds[1], **params},
    ).mappings().all()
    return [dict(r) for r in rows]


def paired_rows(
    conn: Connection,
    plant_code: str,
    *,
    models: list[str] | None,
    colors: list[str] | None,
) -> list[dict]:
    """Mean film thickness and mean Wave Scan bands per paired car x pair group x layer.

    Every month: pairs are rare, so the month filter would leave almost none.
    """
    film_extra, params = _filters("f", models, colors)
    ws_extra, _ = _filters("w", models, colors)
    rows = conn.execute(
        text(
            f"""
            WITH film AS (
                SELECT substring(f.job_no FROM r.pattern) AS car_no, m.pair_group,
                       f.layer_code, avg(f.thickness) AS thickness
                  FROM {FILM_VIEW} f
                  JOIN ref_plant_film_car_rule r ON r.plant_code = f.plant
                  JOIN ref_pair_film_point m
                    ON m.plant_code = f.plant AND m.model_code = f.model
                   AND m.point_code = f.point_code
                 WHERE f.plant = :plant AND f.thickness IS NOT NULL{film_extra}
                 GROUP BY 1, 2, 3
            ), ws AS (
                SELECT w.serial_no AS car_no, z.pair_group,
                       {', '.join(f'avg(w.{b}) AS {b}' for b in BANDS)}
                  FROM {WS_ACTIVE_VIEW} w
                  JOIN ref_pair_ws_zone z
                    ON z.plant_code = w.plant AND z.model_code = w.model
                   AND z.zone_code = w.checkzone
                 WHERE w.plant = :plant{ws_extra}
                 GROUP BY 1, 2
            )
            SELECT film.car_no, film.pair_group, film.layer_code, film.thickness,
                   {', '.join(f'ws.{b}' for b in BANDS)}
              FROM film JOIN ws USING (car_no, pair_group)
             WHERE film.car_no IS NOT NULL
             ORDER BY 1, 2, 3
            """
        ),
        {"plant": plant_code, **params},
    ).mappings().all()
    return [dict(r) for r in rows]
