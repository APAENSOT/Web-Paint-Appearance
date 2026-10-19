"""Measurement reads.

**Every statement in this module selects from `v_wavescan_active`.** That
view is where the active-data predicate lives -- not a duplicate, not
retired, batch accepted (`01-DATA-MODEL.md` sections 5 and 10). The three
column and status names that make up the predicate therefore appear nowhere
in the Python package, and a test enforces that. Re-stating the predicate
here would be a second definition to keep in step, and the first time the
two disagreed the API would publish a retired measurement as current.

Filters are always bound parameters. No caller value is ever formatted into
SQL text; the only interpolation is the dimension column, chosen from a
fixed dictionary of two literals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from sqlalchemy import Connection, text

from app.domain.cleaner import dedup_key
from app.domain.dedup import ExistingMeasurement
from app.domain.reader import MEASURES_CORE

ACTIVE_VIEW = "v_wavescan_active"

#: T114 (D-114-12): the readings the **dashboard** counts -- `ACTIVE_VIEW`
#: rows whose point is live (not retired) and counted at its plant x model
#: (revision 0037). It reads through `ACTIVE_VIEW`, so the active-data
#: predicate is still written once. History, Comparison, the measurements
#: list and corrections keep `ACTIVE_VIEW` and therefore every reading.
COUNTED_VIEW = "v_wavescan_counted"

MEASUREMENT_COLUMNS = """
    measurement_id, measured_date, plant, model, checkzone, color,
    tolerance_group, paintline, serial_no,
    lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
    load_id, source_sheet, source_row, loaded_at,
    corrects_measurement_id, correction_reason, date_is_month_only
"""

#: The dashboard may group by exactly these. The value is a column name that
#: is interpolated into SQL, so the mapping is a closed dictionary and the key
#: is validated by the route's Literal type before it reaches here.
PREVIEW_DIMENSIONS = {"checkzone": "checkzone", "color": "color"}


@dataclass(frozen=True)
class MeasurementFilter:
    plant: str | None = None
    model: str | None = None
    color: str | None = None
    checkzone: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    #: One batch's measurements, for a file drill-down (T19). Additive: it
    #: narrows the same active view, and never widens it -- the rows of a
    #: superseded batch are not current and do not come back here.
    load_id: int | None = None
    #: Plant codes the caller may read, or None for all. Supplied only by
    #: the scoping module -- the single seam for D3.
    plant_scope: list[str] | None = None


def _where(f: MeasurementFilter) -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict = {}
    if f.plant:
        clauses.append("plant = :plant")
        params["plant"] = f.plant
    if f.model:
        clauses.append("model = :model")
        params["model"] = f.model
    if f.color:
        clauses.append("color = :color")
        params["color"] = f.color
    if f.checkzone:
        clauses.append("checkzone = :checkzone")
        params["checkzone"] = f.checkzone
    if f.date_from:
        clauses.append("measured_date >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to:
        clauses.append("measured_date <= :date_to")
        params["date_to"] = f.date_to
    if f.load_id:
        clauses.append("load_id = :load_id")
        params["load_id"] = f.load_id
    if f.plant_scope is not None:
        clauses.append("plant = ANY(:plant_scope)")
        params["plant_scope"] = list(f.plant_scope)
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def count_measurements(conn: Connection, f: MeasurementFilter) -> int:
    where, params = _where(f)
    sql = text(f"SELECT count(*) FROM {ACTIVE_VIEW} WHERE {where}")
    return int(conn.execute(sql, params).scalar_one())


def list_measurements(
    conn: Connection, f: MeasurementFilter, limit: int, offset: int
) -> list[dict]:
    where, params = _where(f)
    # measurement_id breaks ties, so paging is stable: a BIGSERIAL is unique
    # and never reused, and two rows can share a date.
    sql = text(
        f"""
        SELECT {MEASUREMENT_COLUMNS}
        FROM {ACTIVE_VIEW}
        WHERE {where}
        ORDER BY measured_date DESC, measurement_id DESC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = conn.execute(sql, {**params, "limit": limit, "offset": offset}).mappings().all()
    return [dict(r) for r in rows]


def get_active(conn: Connection, measurement_id: int, f: MeasurementFilter) -> dict | None:
    """One measurement, if it is current and the caller may see its plant.

    Through the same view as every other read, so a retired, duplicate or
    uncommitted row is simply absent -- the route answers 404 rather than
    leaking a measurement the platform has set aside. List filters (plant,
    model, date range) are ignored on purpose: a by-id route that inherited
    them would hide a current row because the dashboard had a leftover
    query. The only filter that applies is `plant_scope`, which is D3's
    single seam: a by-id route that skipped it would be the second scheme
    `03-SECURITY.md` §5 forbids.
    """
    scope = MeasurementFilter(plant_scope=f.plant_scope)
    where, params = _where(scope)
    sql = text(
        f"""
        SELECT {MEASUREMENT_COLUMNS}
        FROM {ACTIVE_VIEW}
        WHERE measurement_id = :measurement_id AND {where}
        """
    )
    row = conn.execute(sql, {**params, "measurement_id": measurement_id}).mappings().first()
    return dict(row) if row else None


def preview_points(
    conn: Connection, f: MeasurementFilter, dimension: str, limit: int
) -> list[dict]:
    """Raw CF values plus their dimensions. No statistic is computed here."""
    column = PREVIEW_DIMENSIONS[dimension]
    where, params = _where(f)
    sql = text(
        f"""
        SELECT {column} AS series_key,
               measurement_id, measured_date, plant, model, color, checkzone,
               tolerance_group, cf
        FROM {ACTIVE_VIEW}
        WHERE {where}
        ORDER BY series_key, measured_date, measurement_id
        LIMIT :limit
        """
    )
    rows = conn.execute(sql, {**params, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def existing_for_dedup(
    conn: Connection,
    pairs: Sequence[tuple[str, str | None]],
    serialless: Sequence[tuple] = (),
) -> dict[tuple, list[ExistingMeasurement]]:
    """Measurements already stored for these vehicles, keyed for the deduper.

    Only the (plant, serial) pairs the incoming file mentions are fetched, so
    this stays fast as the table grows -- the same shape the demo loader used.

    T39-FIX (ADR 0013 decision 8a): a point with no serial is looked up by
    ``(plant, measured_date, model, colour, car_key)`` among stored points
    that also have no serial, and keyed by ``cleaner.dedup_key`` exactly as
    the new row is -- never by ``(plant, NULL, zone)`` alone. RO16: the
    ``car_key`` matches ``IS NOT DISTINCT FROM``, so a one-car sheet (NULL)
    finds only one-car points and each car of a many-car sheet only itself.

    It reads through the active view, like every other measurement query in
    this package. A retired or duplicate-flagged row must not make a fresh
    row look like a duplicate: that would hide a genuine re-measurement
    behind a fact the platform has already set aside.
    """
    named = [(p, s) for p, s in pairs if s is not None]
    out: dict[tuple, list[ExistingMeasurement]] = {}
    if named:
        _existing_named(conn, named, out)
    if serialless:
        _existing_serialless(conn, serialless, out)
    return out


def _add(out: dict, row) -> None:
    key = dedup_key(row[0], row[1], row[2], row[16], row[17], row[18], row[19])
    out.setdefault(key, []).append(
        ExistingMeasurement(
            measures=dict(zip(MEASURES_CORE, row[3:13])),
            source=f"{row[13]} [{row[14]}] row {row[15]}",
        )
    )


_DEDUP_COLUMNS = """
        SELECT w.plant, w.serial_no, w.checkzone,
               w.lw, w.sw, w.cf, w.doi, w.du, w.wa, w.wb, w.wc, w.wd, w.we,
               b.source_file, w.source_sheet, w.source_row,
               w.measured_date, w.model, w.color, w.car_key
        FROM {view} w
        JOIN load_batch b ON b.load_id = w.load_id
"""


def _existing_serialless(
    conn: Connection, keys: Sequence[tuple], out: dict,
) -> None:
    sql = text(
        _DEDUP_COLUMNS.format(view=ACTIVE_VIEW)
        + """
        WHERE w.serial_no IS NULL
          AND EXISTS (
            SELECT 1 FROM unnest(
                CAST(:plants AS text[]), CAST(:dates AS date[]),
                CAST(:models AS text[]), CAST(:colors AS text[]),
                CAST(:cars AS text[])
            ) AS t(p, d, m, c, k)
            WHERE w.plant = t.p AND w.measured_date = t.d AND w.model = t.m
              AND w.color = t.c AND w.car_key IS NOT DISTINCT FROM t.k
        )
        """
    )
    params = {
        "plants": [k[0] for k in keys],
        "dates": [k[1] for k in keys],
        "models": [k[2] for k in keys],
        "colors": [k[3] for k in keys],
        # A ``(plant, day, model, colour)`` key is a one-car sheet's (no car_key).
        "cars": [k[4] if len(k) > 4 else None for k in keys],
    }
    for row in conn.execute(sql, params).all():
        _add(out, row)


def _existing_named(
    conn: Connection, pairs: Sequence[tuple[str, str]], out: dict
) -> None:
    plants = [p for p, _ in pairs]
    serials = [s for _, s in pairs]
    sql = text(
        f"""
        SELECT w.plant, w.serial_no, w.checkzone,
               w.lw, w.sw, w.cf, w.doi, w.du, w.wa, w.wb, w.wc, w.wd, w.we,
               b.source_file, w.source_sheet, w.source_row,
               w.measured_date, w.model, w.color, w.car_key
        FROM {ACTIVE_VIEW} w
        JOIN load_batch b ON b.load_id = w.load_id
        WHERE (w.plant, w.serial_no) IN (
            SELECT p, s FROM unnest(CAST(:plants AS text[]),
                                    CAST(:serials AS text[])) AS t(p, s)
        )
        """
    )
    for row in conn.execute(sql, {"plants": plants, "serials": serials}).all():
        _add(out, row)
