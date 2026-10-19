"""Monthly Overview reads: every matching active CF, plus filter options.

**Every measurement statement selects from `v_wavescan_counted`**
(`COUNTED_VIEW`, T114 D-114-12): `v_wavescan_active` narrowed to readings
whose point is live and counted, both imported from
`repositories.measurements`. The active-data predicate is not restated here.
A switched-off or retired point's readings leave the dashboard for every
month; History and Comparison read `ACTIVE_VIEW` and keep them.

The CF read is uncapped: a box built from a point cap would be a wrong
dashboard.

Standards come from the latest `cf_standard` row for the selected plant, else
the NULL-plant seed (ADR 0012). The selected month does not filter them.
COLOR-scope wins over FAMILY for that colour.
`DEFAULT_STANDARDS` is not consulted.

Joins allowed: `ref_plant_color` and `ref_color_family` for the plant's
catalogue family, not for membership of the active set.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from app.repositories.measurements import ACTIVE_VIEW, COUNTED_VIEW


def _scope(plant_code: str, plant_scope: list[str] | None) -> tuple[list[str], dict]:
    clauses = ["w.plant = :plant"]
    params: dict = {"plant": plant_code}
    if plant_scope is not None:
        clauses.append("w.plant = ANY(:plant_scope)")
        params["plant_scope"] = list(plant_scope)
    return clauses, params


def _view(view: str) -> str:
    """T114: the dashboard reads `COUNTED_VIEW`; Comparison's month boxes,
    which keep every reading (D-114-3), pass `ACTIVE_VIEW`. Nothing else."""
    if view not in (COUNTED_VIEW, ACTIVE_VIEW):
        raise ValueError(f"unknown Wave Scan view {view!r}")
    return view


def months(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    view: str = COUNTED_VIEW,
) -> list[str]:
    view = _view(view)
    clauses, params = _scope(plant_code, plant_scope)
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT to_char(w.measured_date, 'YYYY-MM') AS month
              FROM {view} w
             WHERE {' AND '.join(clauses)}
             ORDER BY month DESC
            """
        ),
        params,
    ).all()
    return [r[0] for r in rows]


def model_options(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    view: str = COUNTED_VIEW,
) -> list[str]:
    """Models with readings. The dashboard's own list counts what it shows;
    Comparison passes `ACTIVE_VIEW` because it keeps every reading (T114)."""
    view = _view(view)
    clauses, params = _scope(plant_code, plant_scope)
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT w.model
              FROM {view} w
             WHERE {' AND '.join(clauses)}
            """
        ),
        params,
    ).all()
    return [r[0] for r in rows if r[0] is not None]


def color_options(conn: Connection, plant_code: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT pc.color_name, f.family_code
              FROM ref_plant_color pc
              LEFT JOIN ref_color_family f ON f.family_name = pc.family_name
             WHERE pc.plant_code = :plant
               AND pc.is_offered = true
             ORDER BY f.display_order NULLS LAST, pc.color_name
            """
        ),
        {"plant": plant_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def readings(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    bounds: tuple[date, date],
    models: list[str] | None,
    colors: list[str] | None,
    view: str = COUNTED_VIEW,
) -> list[dict]:
    """Every matching CF of `view` (counted, for the dashboard). Uncapped.

    T73 (D-73-05): each row also carries its own ``measurement_id``,
    ``measured_date`` and ``checkzone`` so a below-Minimum reading is listed
    with its own identity, date and zone. No threshold is applied here.
    """
    clauses, params = _scope(plant_code, plant_scope)
    clauses.append("w.measured_date BETWEEN :date_from AND :date_to")
    params["date_from"], params["date_to"] = bounds
    if models:
        clauses.append("w.model = ANY(:models)")
        params["models"] = list(models)
    if colors:
        clauses.append("w.color = ANY(:colors)")
        params["colors"] = list(colors)
    rows = conn.execute(
        text(
            f"""
            SELECT w.model,
                   w.color,
                   pc.family_name,
                   f.family_code,
                   f.display_order,
                   w.tolerance_group,
                   w.cf,
                   w.measurement_id,
                   w.measured_date,
                   w.checkzone
              FROM {_view(view)} w
              LEFT JOIN ref_plant_color pc
                ON pc.plant_code = w.plant
               AND pc.color_name = w.color
              LEFT JOIN ref_color_family f
                ON f.family_name = pc.family_name
             WHERE {' AND '.join(clauses)}
            """
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def color_standards(
    conn: Connection, plant_code: str, color_names: list[str]
) -> list[dict]:
    """Latest COLOR row per (colour, orient): this plant's, else NULL-plant.

    T64 (ADR 0014): ``color_name`` is folded through ``ref_color.merged_into``
    before DISTINCT ON, matching the folded colour the active view returns.
    """
    if not color_names:
        return []
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (f.color_name, s.orient)
                   f.color_name, s.orient, s.ford, s.min
              FROM cf_standard s
              LEFT JOIN ref_color rc ON rc.color_name = s.color_name
             CROSS JOIN LATERAL (
                   SELECT COALESCE(rc.merged_into, s.color_name) AS color_name
             ) f
             WHERE s.scope = 'COLOR'
               AND f.color_name = ANY(:colors)
               AND (s.plant_code = :plant OR s.plant_code IS NULL)
             ORDER BY f.color_name, s.orient, (s.plant_code IS NULL),
                      s.created_at DESC, s.effective_from DESC
            """
        ),
        {"colors": list(color_names), "plant": plant_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def family_standards(
    conn: Connection, plant_code: str, family_names: list[str]
) -> list[dict]:
    """Latest FAMILY row per (family, orient): this plant's, else NULL-plant.

    ADR 0012: every month uses the newest row; ``effective_from`` does not
    filter by the selected month.
    """
    if not family_names:
        return []
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (family_name, orient)
                   family_name, orient, ford, min
              FROM cf_standard
             WHERE scope = 'FAMILY'
               AND family_name = ANY(:families)
               AND (plant_code = :plant OR plant_code IS NULL)
             ORDER BY family_name, orient, (plant_code IS NULL),
                      created_at DESC, effective_from DESC
            """
        ),
        {"families": list(family_names), "plant": plant_code},
    ).mappings().all()
    return [dict(r) for r in rows]
