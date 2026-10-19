"""Uncapped IMG facts through the two authoritative active views."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from app.repositories.measurements import ACTIVE_VIEW as CF_ACTIVE, COUNTED_VIEW as CF_COUNTED
from app.repositories.filmthickness import ACTIVE_VIEW as FILM_ACTIVE

PLANTS = ("FTM", "FVL", "SAP", "AAT")


def catalogue(conn: Connection) -> dict[str, dict]:
    rows = conn.execute(text(
        "SELECT model_code, model_family, series_code, display_name, "
        "wavescan_ok, is_active FROM ref_model"
    )).mappings().all()
    return {r["model_code"]: dict(r) for r in rows}


def cf_rows(conn: Connection, scope: list[str] | None, bounds: tuple[date, date] | None = None) -> list[dict]:
    clauses = ["w.plant = ANY(:plants)"]
    params: dict = {"plants": list(PLANTS)}
    if scope is not None:
        clauses.append("w.plant = ANY(:scope)")
        params["scope"] = list(scope)
    if bounds is not None:
        clauses.append("w.measured_date BETWEEN :start AND :end")
        params.update(start=bounds[0], end=bounds[1])
    # The dashboard's own rule (T114): a reading counts only when it is in
    # the counted view -- its point live and counted. Others are kept here
    # solely to disclose them as setting exclusions.
    return [dict(r) for r in conn.execute(text(f"""
        SELECT w.plant, w.model, w.color, w.checkzone AS location,
               w.tolerance_group, w.cf AS value, w.measured_date,
               EXISTS (SELECT 1 FROM {CF_COUNTED} c
                        WHERE c.measurement_id = w.measurement_id) AS counted
          FROM {CF_ACTIVE} w WHERE {' AND '.join(clauses)}
    """), params).mappings().all()]


def film_rows(conn: Connection, scope: list[str] | None, bounds: tuple[date, date] | None = None) -> list[dict]:
    clauses = ["f.plant = ANY(:plants)"]
    params: dict = {"plants": list(PLANTS)}
    if scope is not None:
        clauses.append("f.plant = ANY(:scope)")
        params["scope"] = list(scope)
    if bounds is not None:
        clauses.append("f.measured_date BETWEEN :start AND :end")
        params.update(start=bounds[0], end=bounds[1])
    # The same precedence, latest-setting lateral join and retired-point rule
    # (T99, T109) as the plant Film Overview. A point the setting switches off
    # or the plant retired is `counted = false`; it is kept here solely to
    # count the exclusion.
    return [dict(r) for r in conn.execute(text(f"""
        SELECT f.plant, f.model, f.color, f.point_code AS location,
               f.logical_vehicle_id, f.layer_code, f.thickness AS value,
               f.measured_date, COALESCE(btrim(s.orientation),
               btrim(pp.orientation), btrim(mp.orientation)) AS orientation,
               (s.counted IS NOT false AND rp.point_code IS NULL) AS counted
          FROM {FILM_ACTIVE} f
          LEFT JOIN ref_plant_film_point pp
            ON pp.plant_code=f.plant AND pp.model_code=f.model
           AND pp.point_code=f.point_code AND pp.retired_at IS NULL
          LEFT JOIN ref_model_film_point mp
            ON mp.model_code=f.model AND mp.point_code=f.point_code
          LEFT JOIN ref_plant_film_point rp
            ON rp.plant_code=f.plant AND rp.model_code=f.model
           AND rp.point_code=f.point_code AND rp.retired_at IS NOT NULL
          LEFT JOIN LATERAL (
              SELECT counted, orientation FROM film_point_setting ps
               WHERE ps.plant_code=f.plant AND ps.model_code=f.model
                 AND ps.point_code=f.point_code
               ORDER BY ps.setting_id DESC LIMIT 1
          ) s ON true
         WHERE {' AND '.join(clauses)}
    """), params).mappings().all()]
