"""Measurement History reads: months, facets, vehicle groups, points.

**Every statement in this module selects from `v_wavescan_active`**, the one
place the active-data predicate lives (`01-DATA-MODEL.md` sections 5 and 10).
It is imported from `repositories.measurements` rather than spelled again, so
there is one name to change if the view is ever renamed, and the three column
and status names that make up the predicate appear nowhere here -- a test
enforces that for this module as well as for measurements.

Two joins are allowed and no others (T23 locked decision 1):

* `load_batch`, to attach `source_file` **provenance**. It never decides
  membership: the view has already done that, and the join is on the
  `load_id` of a row the view returned.
* `ref_model`, which is not joined at all today -- the expected zone count
  is injected from `ReferenceData` by the service, so this module holds no
  count and no literal 32.

`v_vehicle_completeness` is deliberately not used: it groups without
`load_id`, which would merge two sheets that measured the same serial on the
same day into one card.

Filters are always bound parameters.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from app.repositories.measurements import ACTIVE_VIEW, MEASUREMENT_COLUMNS

#: One aggregated row per candidate vehicle set: the T21 identity key on one
#: committed sheet, with the two counts a card and a set need.
_IDENTITY_GROUP = f"""
    SELECT w.load_id,
           w.measured_date,
           w.model,
           w.color,
           w.serial_no,
           w.car_key,
           min(w.source_sheet)          AS source_sheet,
           min(b.source_file)           AS source_file,
           count(*)                     AS row_count,
           min(w.source_row)            AS first_source_row,
           array_remove(array_agg(DISTINCT w.checkzone), NULL) AS zones,
           bool_or(w.date_is_month_only) AS date_is_month_only
      FROM {ACTIVE_VIEW} w
      JOIN load_batch b ON b.load_id = w.load_id
     WHERE {{where}}
     GROUP BY w.load_id, w.measured_date, w.model, w.color, w.serial_no,
              w.car_key
"""


def _scope(plant_code: str, plant_scope: list[str] | None) -> tuple[list[str], dict]:
    """Plant, plus D3's single seam. Nothing else is implicit."""
    clauses = ["w.plant = :plant"]
    params: dict = {"plant": plant_code}
    if plant_scope is not None:
        clauses.append("w.plant = ANY(:plant_scope)")
        params["plant_scope"] = list(plant_scope)
    return clauses, params


def _filtered(
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    bounds: tuple[date, date] | None = None,
    model: str | None = None,
    color: str | None = None,
) -> tuple[str, dict]:
    clauses, params = _scope(plant_code, plant_scope)
    if bounds is not None:
        clauses.append("w.measured_date BETWEEN :date_from AND :date_to")
        params["date_from"], params["date_to"] = bounds
    if model is not None:
        clauses.append("w.model = :model")
        params["model"] = model
    if color is not None:
        clauses.append("w.color = :color")
        params["color"] = color
    return " AND ".join(clauses), params


# =====================================================================
# facets
# =====================================================================
def months(conn: Connection, plant_code: str, plant_scope: list[str] | None) -> list[str]:
    """Calendar months of `measured_date` that have active rows, newest first.

    The month of the **measured** date, never of `uploaded_at` or
    `loaded_at`: a June workbook uploaded in September is June data (T19
    locked decision 3, T23 locked decision 4).
    """
    where, params = _filtered(plant_code, plant_scope)
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT to_char(w.measured_date, 'YYYY-MM') AS month
              FROM {ACTIVE_VIEW} w
             WHERE {where}
             ORDER BY month DESC
            """
        ),
        params,
    ).all()
    return [r[0] for r in rows]


def _distinct(
    conn: Connection,
    column: str,
    plant_code: str,
    plant_scope: list[str] | None,
    bounds: tuple[date, date],
    model: str | None = None,
) -> list[str]:
    where, params = _filtered(plant_code, plant_scope, bounds=bounds, model=model)
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT w.{column} AS value
              FROM {ACTIVE_VIEW} w
             WHERE {where}
             ORDER BY value
            """
        ),
        params,
    ).all()
    return [r[0] for r in rows if r[0] is not None]


def models(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    bounds: tuple[date, date],
) -> list[str]:
    return _distinct(conn, "model", plant_code, plant_scope, bounds)


def colors(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    bounds: tuple[date, date],
    model: str | None = None,
) -> list[str]:
    """Colours in that month, narrowed to one model when the client picked one."""
    return _distinct(conn, "color", plant_code, plant_scope, bounds, model=model)


# =====================================================================
# vehicle sets
# =====================================================================
def identity_groups(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    bounds: tuple[date, date] | None = None,
    model: str | None = None,
    color: str | None = None,
) -> list[dict]:
    """Candidate vehicle sets: the T21 key on one sheet, with its counts.

    `row_count` is active measurement rows (what a card counts, so it agrees
    with `GET /measurements`); `zones` is the set's distinct checkzones,
    which `domain.completeness` counts against the plant's live list
    (T114-FIX).
    """
    where, params = _filtered(
        plant_code, plant_scope, bounds=bounds, model=model, color=color
    )
    rows = conn.execute(
        text(_IDENTITY_GROUP.format(where=where)), params
    ).mappings().all()
    return [dict(r) for r in rows]


def points(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    load_id: int,
    measured_date: date,
    model: str | None,
    color: str | None,
    serial_no: str | None,
    car_key: str | None = None,
) -> list[dict]:
    """Every active fact of one vehicle set, by checkzone then source row.

    `IS NOT DISTINCT FROM` rather than `=` for the three nullable parts of
    the key: a set whose serial is blank is one set, and `NULL = NULL` would
    return none of its rows.
    """
    clauses, params = _scope(plant_code, plant_scope)
    clauses.append("w.load_id = :load_id")
    clauses.append("w.measured_date = :measured_date")
    clauses.append("w.model IS NOT DISTINCT FROM :model")
    clauses.append("w.color IS NOT DISTINCT FROM :color")
    clauses.append("w.serial_no IS NOT DISTINCT FROM :serial_no")
    # RO16: one car of a many-car blank-serial sheet, not all of them.
    clauses.append("w.car_key IS NOT DISTINCT FROM :car_key")
    params.update({
        "load_id": load_id,
        "measured_date": measured_date,
        "model": model,
        "color": color,
        "serial_no": serial_no,
        "car_key": car_key,
    })
    # Every measurement column except `plant`: this read is already scoped to
    # one plant by its URL, and a point that repeated it would be a second
    # place for the two to disagree.
    # T53 (D-53-09) made `panel_label` the panel text the plant wrote, so
    # History showed `01HOOD` even when `checkzone` was a picked `RRHOOD`.
    # **T94 (D-94-4) replaces that**: the panel column is the stored
    # position, the long name -- *"it always show the long name in
    # Measurement History because it should be show what we clean"*. A rough
    # spelling is never displayed as a position, and that has to hold for
    # `06LFFENDER` as much as for `01HOOD`: both are rough on the September
    # sheet, and a rule that showed the one and not the other would be a
    # rule about spelling rather than about what the name says.
    #
    # T53's information is not lost and nothing here guesses: the file's own
    # words travel beside the position as `src_zone_text`, so a client can
    # still show "the file called this 01HOOD" without ever putting that in
    # the position column. The confirm worksheet shows both side by side.
    #
    # Still from the two stored values and the two joins T23 locked: no
    # `worksheet_decision` read, no classification, no third join.
    columns = ", ".join(
        f"w.{name}" for name in
        (c.strip() for c in MEASUREMENT_COLUMNS.split(","))
        if name and name != "plant"
    )
    rows = conn.execute(
        text(
            f"""
            SELECT {columns}, b.source_file, w.src_zone_text
              FROM {ACTIVE_VIEW} w
              JOIN load_batch b ON b.load_id = w.load_id
             WHERE {' AND '.join(clauses)}
             ORDER BY w.checkzone, w.source_row, w.measurement_id
            """
        ),
        params,
    ).mappings().all()
    out: list[dict] = []
    for row in rows:
        point = dict(row)
        spelling = (point.get("src_zone_text") or "").strip() or None
        point["src_zone_text"] = spelling
        point["panel_label"] = point["checkzone"]
        out.append(point)
    return out


__all__ = ["colors", "identity_groups", "models", "months", "points"]
