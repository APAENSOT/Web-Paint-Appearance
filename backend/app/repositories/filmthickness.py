"""FilmThickness SQL: load the film maps, stage, insert facts. No UPDATE.

T46 (spec F10, F16). The only statements here that write are INSERTs --
`app_rw` holds no UPDATE or DELETE on `filmthickness` (revision 0017), so a
statement that tried would be refused by the database, not by this file.

Every read of film facts goes through `filmthickness_active` (the one
active-data predicate, `01-DATA-MODEL.md` section 10).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import Connection, text

from app.domain.film import FilmReference, FilmRow
from app.domain.film_header import DOMAIN_FILMTHICKNESS
from app.domain.film import normalise_location
from app.domain.reader import RawRow
from app.domain.references import normalise_alias

#: The active-data view (revision 0017). Film reads select from this.
ACTIVE_VIEW = "filmthickness_active"


def load_film_reference(conn: Connection) -> FilmReference:
    column_alias = {
        normalise_alias(raw): logical
        for raw, logical in conn.execute(
            text(
                "SELECT raw_header, logical_field FROM ref_column_alias "
                "WHERE is_approved AND domain = :domain"
            ),
            {"domain": DOMAIN_FILMTHICKNESS},
        ).all()
    }
    model_alias = {
        (plant, token.upper()): model
        for plant, token, model in conn.execute(
            text("SELECT plant_code, raw_token, model_code FROM ref_film_model_alias")
        ).all()
    }
    catalogue: dict[str, dict[str, str]] = {}
    orientation: dict[tuple[str, str], str] = {}
    for model, point, orient in conn.execute(
        text("SELECT model_code, point_code, orientation FROM ref_model_film_point")
    ).all():
        catalogue.setdefault(model, {})[normalise_location(point)] = point
        if orient:
            orientation[(model, point)] = orient.strip()
    # T54 (D-53-01..05): each plant's own gold list per model. T57: a
    # retired row is a record only (kept for the facts that named it).
    plant_catalogue: dict[tuple[str, str], dict[str, str]] = {}
    plant_orientation: dict[tuple[str, str, str], str] = {}
    for plant, model, point, orient in conn.execute(
        text(
            # T99: walk order, so `gold_for` lists a plant's points in the
            # order the plant walks them rather than in whatever order the
            # heap returned them.
            "SELECT p.plant_code, p.model_code, p.point_code, p.orientation "
            "FROM ref_plant_film_point p JOIN v_point_walk_order w "
            "ON w.plant_code=p.plant_code AND w.model_code=p.model_code "
            "AND w.point_code=p.point_code AND w.domain='FILMTHICKNESS' "
            "WHERE p.retired_at IS NULL ORDER BY p.plant_code,p.model_code,w.walk_rank"
        )
    ).all():
        plant_catalogue.setdefault((plant, model), {})[normalise_location(point)] = point
        if orient:
            plant_orientation[(plant, model, point)] = orient.strip()
    # S15 analog: a location map reaches the reader only when a named owner
    # proved it. An unproved row stays in the table as a record. T54: a
    # retired row (FTM's T47 maps onto FVL names) is a record only too.
    location_map = {
        (plant, model, raw): point
        for plant, model, raw, point in conn.execute(
            text(
                "SELECT plant_code, model_code, raw_location_norm, point_code "
                "FROM ref_film_location_map "
                "WHERE proof_hash IS NOT NULL AND verified_by IS NOT NULL "
                "  AND retired_at IS NULL"
            )
        ).all()
    }
    expected = {
        model: int(n)
        for model, n in conn.execute(
            text(
                "SELECT model_code, expected_film_point_count FROM ref_model "
                "WHERE expected_film_point_count IS NOT NULL"
            )
        ).all()
    }
    # T99. The live list in walk order, where a complete walk may stop, the
    # never-stored tail, the Job Number shape, and the latest setting of each
    # point. The setting's presence is the switch for every T99 rule
    # (D-99-12), so it is loaded here with the rest of the Film reference and
    # nowhere else.
    walk: dict[tuple[str, str], list[str]] = {}
    stops: dict[tuple[str, str], set[str]] = {}
    for plant, model, point, is_stop in conn.execute(
        text(
            "SELECT p.plant_code, p.model_code, p.point_code, p.is_complete_stop "
            "FROM ref_plant_film_point p JOIN v_point_walk_order w "
            "ON w.plant_code=p.plant_code AND w.model_code=p.model_code "
            "AND w.point_code=p.point_code AND w.domain='FILMTHICKNESS' "
            "WHERE p.retired_at IS NULL ORDER BY p.plant_code,p.model_code,w.walk_rank"
        )
    ).all():
        walk.setdefault((plant, model), []).append(point)
        if is_stop:
            stops.setdefault((plant, model), set()).add(point)
    tails: dict[tuple[str, str], set[str]] = {}
    not_a_point: dict[tuple[str, str], set[str]] = {}
    for plant, model, label, answered in conn.execute(
        text(
            # RO17 (D-RO17-12): a retired tail label is a record only.
            # RO18 (B5): a "Not a point" answer is read as a tail label.
            "SELECT plant_code, model_code, label_norm, not_a_point "
            "FROM ref_plant_film_tail_label WHERE retired_at IS NULL"
        )
    ).all():
        tails.setdefault((plant, model), set()).add(normalise_location(label))
        if answered:
            not_a_point.setdefault((plant, model), set()).add(normalise_location(label))
    setting: dict[tuple[str, str], dict[str, tuple[bool, str]]] = {}
    for plant, model, point, counted, orient in conn.execute(
        text(
            # The latest row per point wins: the table is INSERT-only and a
            # person may correct themselves (D-99-4).
            "SELECT DISTINCT ON (plant_code, model_code, point_code) "
            "       plant_code, model_code, point_code, counted, orientation "
            "  FROM film_point_setting "
            " ORDER BY plant_code, model_code, point_code, setting_id DESC"
        )
    ).all():
        setting.setdefault((plant, model), {})[point] = (
            bool(counted), orient.strip(),
        )
    job_pattern = {
        plant: pattern
        for plant, pattern in conn.execute(
            text(
                "SELECT plant_code, film_job_no_pattern FROM ref_plant "
                "WHERE film_job_no_pattern IS NOT NULL"
            )
        ).all()
    }
    # T109 (D-109-6). The live aliases a person wrote in a review row. Live
    # only: a retired alias is a record of what was answered once, the same
    # way a retired list row is (ADR 0005). Its own table rather than
    # `ref_film_location_map`, whose 118 FTM rows are all retired and whose
    # primary key cannot hold a live FTM answer beside them (D-109-8).
    point_alias = {
        (plant, model, raw): point
        for plant, model, raw, point in conn.execute(
            text(
                "SELECT plant_code, model_code, raw_location_norm, point_code "
                "FROM ref_film_point_alias WHERE retired_at IS NULL"
            )
        ).all()
    }
    # T109 (D-109-3). Which live points are beyond the plant's standard list.
    extra: dict[tuple[str, str], set[str]] = {}
    for plant, model, point in conn.execute(
        text(
            "SELECT plant_code, model_code, point_code FROM ref_plant_film_point "
            "WHERE is_extra AND retired_at IS NULL"
        )
    ).all():
        extra.setdefault((plant, model), set()).add(point)
    # RO17 (D-RO17-3). Every unretired label, current and earlier, of a live
    # point, keyed by the plant's own word; `resolve_point` reads it last.
    point_label = {
        (plant, model, normalise_location(label)): point
        for plant, model, label, point in conn.execute(
            text(
                "SELECT l.plant_code, l.model_code, l.label, l.point_code "
                "  FROM ref_plant_film_point_label l "
                "  JOIN ref_plant_film_point p USING (plant_code, model_code, point_code) "
                " WHERE l.retired_at IS NULL AND p.retired_at IS NULL "
                " ORDER BY l.label_id"
            )
        ).all()
    }
    return FilmReference(
        column_alias=column_alias,
        model_alias=model_alias,
        catalogue=catalogue,
        location_map=location_map,
        expected_points=expected,
        orientation=orientation,
        plant_catalogue=plant_catalogue,
        plant_orientation=plant_orientation,
        point_setting={k: dict(v) for k, v in setting.items()},
        tail_labels={k: frozenset(v) for k, v in tails.items()},
        not_a_point={k: frozenset(v) for k, v in not_a_point.items()},
        complete_stops={k: frozenset(v) for k, v in stops.items()},
        walk={k: tuple(v) for k, v in walk.items()},
        job_pattern=job_pattern,
        point_alias=point_alias,
        extra_points={k: frozenset(v) for k, v in extra.items()},
        point_label=point_label,
    )


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def stage_rows(conn: Connection, load_id: int, rows: Iterable[RawRow]) -> int:
    """`stg_raw` for a film sheet: the identity columns it shares, plus
    every film cell verbatim in ``extra`` (spec 5.6). Nothing is dropped."""
    sql = text(
        "INSERT INTO stg_raw (load_id, source_row, raw_date, raw_color, "
        "raw_checkzone, raw_serial_no, extra) VALUES (:load_id, :source_row, "
        ":raw_date, :raw_color, :raw_checkzone, :raw_serial_no, CAST(:extra AS jsonb))"
    )
    payload = []
    for raw in rows:
        payload.append({
            "load_id": load_id,
            "source_row": raw.source_row,
            "raw_date": raw.text("date"),
            "raw_color": raw.text("color"),
            "raw_checkzone": raw.text("location"),
            "raw_serial_no": raw.text("vin"),
            "extra": json.dumps(
                {
                    "domain": DOMAIN_FILMTHICKNESS,
                    "values": {k: _jsonable(v) for k, v in raw.values.items()},
                    "unrecognised": {k: _jsonable(v) for k, v in raw.extra.items()},
                },
                default=str,
            ),
        })
    if payload:
        conn.execute(sql, payload)
    return len(payload)


INSERT_FACT = text(
    """
    INSERT INTO filmthickness
        (measured_date, plant, model, color, job_no, serial_no,
         point_code, src_location_text, layer_code, thickness,
         logical_vehicle_id, load_id, source_sheet, source_row,
         date_is_month_only)
    VALUES
        (:measured_date, :plant, :model, :color, :job_no, :serial_no,
         :point_code, :src_location_text, :layer_code, :thickness,
         :logical_vehicle_id, :load_id, :source_sheet, :source_row,
         :date_is_month_only)
    """
)


def insert_facts(conn: Connection, load_id: int, rows: Sequence[FilmRow]) -> int:
    """One INSERT per (row, numeric layer). Returns facts written."""
    payload = [
        {
            "measured_date": r.measured_date,
            "plant": r.plant,
            "model": r.model,
            "color": r.color,
            "job_no": r.job_no,
            "serial_no": r.serial_no,
            "point_code": r.point_code,
            "src_location_text": r.src_location_text,
            "layer_code": layer,
            "thickness": value,
            "logical_vehicle_id": r.logical_vehicle_id,
            "load_id": load_id,
            "source_sheet": r.source_sheet,
            "source_row": r.source_row,
            "date_is_month_only": r.date_is_month_only,  # RO18 (B4)
        }
        for r in rows
        for layer, value in sorted(r.layers.items())
    ]
    if payload:
        conn.execute(INSERT_FACT, payload)
    return len(payload)


def existing_vehicle_points(
    conn: Connection, vehicle_ids: Sequence[str]
) -> dict[tuple[str, str], int]:
    """Active `(logical_vehicle_id, point_code) -> load_id` already stored."""
    if not vehicle_ids:
        return {}
    rows = conn.execute(
        text(
            f"SELECT DISTINCT ON (logical_vehicle_id, point_code) "
            f"logical_vehicle_id, point_code, load_id FROM {ACTIVE_VIEW} "
            f"WHERE logical_vehicle_id = ANY(:ids) "
            f"ORDER BY logical_vehicle_id, point_code, load_id"
        ),
        {"ids": list(vehicle_ids)},
    ).all()
    return {(v, p): int(load) for v, p, load in rows}


def count_facts(conn: Connection, load_id: int) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM filmthickness WHERE load_id = :id"),
            {"id": load_id},
        ).scalar_one()
    )


def vehicle_points(conn: Connection, logical_vehicle_id: str) -> list[str]:
    """Distinct active points of one car across every load (spec section 6)."""
    return [
        r[0]
        for r in conn.execute(
            text(
                f"SELECT DISTINCT point_code FROM {ACTIVE_VIEW} "
                f"WHERE logical_vehicle_id = :v ORDER BY 1"
            ),
            {"v": logical_vehicle_id},
        ).all()
    ]


# =====================================================================
# T48 reads: facets, vehicles, the gold point grid. SELECT only.
# =====================================================================
def _where(
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    bounds: tuple[date, date] | None = None,
    model: str | None = None,
    color: str | None = None,
) -> tuple[str, dict]:
    """Plant, D3's single seam, then the optional filters. Nothing implicit."""
    clauses = ["f.plant = :plant"]
    params: dict = {"plant": plant_code}
    if plant_scope is not None:
        clauses.append("f.plant = ANY(:plant_scope)")
        params["plant_scope"] = list(plant_scope)
    if bounds is not None:
        clauses.append("f.measured_date BETWEEN :date_from AND :date_to")
        params["date_from"], params["date_to"] = bounds
    if model is not None:
        clauses.append("f.model = :model")
        params["model"] = model
    if color is not None:
        clauses.append("f.color = :color")
        params["color"] = color
    return " AND ".join(clauses), params


def film_months(conn: Connection, plant_code: str, plant_scope: list[str] | None) -> list[str]:
    """Months of `measured_date` with active film facts, newest first."""
    where, params = _where(plant_code, plant_scope)
    return [
        r[0]
        for r in conn.execute(
            text(
                f"SELECT DISTINCT to_char(f.measured_date, 'YYYY-MM') AS month "
                f"  FROM {ACTIVE_VIEW} f WHERE {where} ORDER BY month DESC"
            ),
            params,
        ).all()
    ]


def film_distinct(
    conn: Connection,
    column: str,
    plant_code: str,
    plant_scope: list[str] | None,
    bounds: tuple[date, date],
    model: str | None = None,
) -> list[str]:
    """Distinct `model` or `color` in one month (and model). Sorted."""
    if column not in ("model", "color"):
        raise ValueError(column)
    where, params = _where(plant_code, plant_scope, bounds=bounds, model=model)
    return [
        r[0]
        for r in conn.execute(
            text(
                f"SELECT DISTINCT f.{column} FROM {ACTIVE_VIEW} f "
                f" WHERE {where} ORDER BY 1"
            ),
            params,
        ).all()
    ]


def live_walks(
    conn: Connection, plant_code: str
) -> dict[str, tuple[dict[str, int], list[int]]]:
    """RO11: this plant's live Film list per model, for the review's cars.

    `model -> ({point_code: walk_rank}, [walk_rank of each complete stop])`:
    the same live rows `_VEHICLES` joins as `p` and `g`, so the review
    counts a car on the list History counts it on.
    """
    out: dict[str, tuple[dict[str, int], list[int]]] = {}
    for model, point, walk_rank, is_stop in conn.execute(
        text(
            "SELECT p.model_code,p.point_code,w.walk_rank,p.is_complete_stop "
            "FROM ref_plant_film_point p JOIN v_point_walk_order w "
            "ON w.plant_code=p.plant_code AND w.model_code=p.model_code "
            "AND w.point_code=p.point_code AND w.domain='FILMTHICKNESS' "
            "WHERE p.plant_code=:plant AND p.retired_at IS NULL ORDER BY p.model_code,w.walk_rank"
        ),
        {"plant": plant_code},
    ).all():
        walk, stops = out.setdefault(model, ({}, []))
        walk[point] = int(walk_rank)
        if is_stop:
            stops.append(int(walk_rank))
    return out


#: One row per logical vehicle. Plant, day, model and colour are inside the
#: id's hash, so grouping by them as well splits nothing. T54: the expected
#: count is the size of **this plant's** gold list for the model
#: (`ref_plant_film_point`), not a model-wide number.
#:
#: T109 (section 3.3): **live** points on both sides of the comparison.
#: ``expected_point_count`` already counted only live rows, so counting every
#: stored point against it made a car measured before a retirement read
#: 98 of 97 and show "incomplete" -- the car did not change, the list did.
#: The filter is conditional on ``g.n`` so a plant x model with no live list
#: at all (AAT's P703 DBL RAPTOR, FVL's RAPCAP) keeps the old number exactly.
_VEHICLES = f"""
    SELECT f.logical_vehicle_id,
           f.measured_date,
           f.model,
           m.display_name,
           f.color,
           max(f.serial_no)                                           AS serial_no,
           array_agg(DISTINCT f.job_no)
               FILTER (WHERE f.job_no IS NOT NULL)                    AS job_nos,
           array_agg(DISTINCT f.load_id)                              AS load_ids,
           count(DISTINCT f.point_code)
               FILTER (WHERE g.n IS NULL OR p.point_code IS NOT NULL) AS mapped_point_count,
           g.n                                                        AS expected_point_count,
           max(w.walk_rank)                                           AS walked_to,
           g.stops                                                    AS stop_point_nos,
           bool_or(f.date_is_month_only)                              AS date_is_month_only
      FROM {ACTIVE_VIEW} f
      JOIN ref_model m ON m.model_code = f.model
      LEFT JOIN ref_plant_film_point p
             ON p.plant_code = f.plant AND p.model_code = f.model
            AND p.point_code = f.point_code AND p.retired_at IS NULL
      LEFT JOIN v_point_walk_order w ON w.plant_code=p.plant_code
             AND w.model_code=p.model_code AND w.point_code=p.point_code
             AND w.domain='FILMTHICKNESS'
      LEFT JOIN (SELECT p.plant_code, p.model_code, count(*) AS n,
                        array_agg(w.walk_rank ORDER BY w.walk_rank) FILTER (WHERE p.is_complete_stop)
                            AS stops
                   FROM ref_plant_film_point p JOIN v_point_walk_order w
                     ON w.plant_code=p.plant_code AND w.model_code=p.model_code
                    AND w.point_code=p.point_code AND w.domain='FILMTHICKNESS'
                  WHERE p.retired_at IS NULL
                  GROUP BY 1, 2) g
             ON g.plant_code = f.plant AND g.model_code = f.model
     WHERE {{where}}
     GROUP BY f.logical_vehicle_id, f.measured_date, f.model, m.display_name,
              f.color, g.n, g.stops
"""


def _source_files(conn: Connection, load_ids: set[int]) -> dict[int, str]:
    if not load_ids:
        return {}
    return {
        int(i): f
        for i, f in conn.execute(
            text("SELECT load_id, source_file FROM load_batch WHERE load_id = ANY(:ids)"),
            {"ids": sorted(load_ids)},
        ).all()
    }


def _identity_notes(conn: Connection, load_ids: set[int]) -> dict[str, str]:
    """T103 (D-103-6): the warning the car's loaded rows already carry.

    D-99-11 writes the Job Number / file name colour-code disagreement onto
    every `stg_review_row` it loads, so it can be found afterwards. Nothing
    is re-parsed and no new table is read: the staging of a committed sheet
    is evidence of the measurements it produced (ADR 0005), so the sentence
    stored then is the sentence shown now. One statement per page, keyed by
    the car the rows named.
    """
    if not load_ids:
        return {}
    notes: dict[str, list[str]] = {}
    for vid, detail in conn.execute(
        text(
            """
            SELECT DISTINCT r.canonical ->> 'logical_vehicle_id' AS vid,
                            r.detail
              FROM stg_review_row r
             WHERE r.load_id = ANY(:ids)
               AND r.disposition = 'LOAD'
               AND r.detail IS NOT NULL
               AND r.canonical ->> 'logical_vehicle_id' IS NOT NULL
             ORDER BY 1, 2
            """
        ),
        {"ids": sorted(load_ids)},
    ).all():
        notes.setdefault(str(vid), []).append(str(detail))
    return {vid: " ".join(details) for vid, details in notes.items()}


def _vehicle_rows(conn: Connection, rows) -> list[dict]:
    out = [
        {
            "logical_vehicle_id": r[0],
            "measured_date": r[1],
            "model": r[2],
            "model_display_name": r[3],
            "color": r[4],
            "serial_no": r[5],
            "job_nos": sorted(r[6] or []),
            "load_ids": sorted(int(i) for i in r[7]),
            "mapped_point_count": int(r[8]),
            "expected_point_count": None if r[9] is None else int(r[9]),
            # T99 (D-99-8): how far along the walk this car got, and where a
            # complete walk of its list is allowed to stop.
            "walked_to": None if r[10] is None else int(r[10]),
            "stop_point_nos": sorted(int(n) for n in (r[11] or [])),
            # RO18 (B4): the sheet had no date; the day is not recorded.
            "date_is_month_only": bool(r[12]),
        }
        for r in rows
    ]
    load_ids = {i for v in out for i in v["load_ids"]}
    files = _source_files(conn, load_ids)
    notes = _identity_notes(conn, load_ids)
    for v in out:
        v["source_files"] = [files.get(i, "") for i in v["load_ids"]]
        v["identity_note"] = notes.get(v["logical_vehicle_id"])
    return out


def film_vehicles(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    bounds: tuple[date, date],
    model: str | None,
    color: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """Vehicles with active film facts in one month. Newest day first."""
    where, params = _where(plant_code, plant_scope, bounds=bounds, model=model, color=color)
    sql = _VEHICLES.format(where=where)
    total = int(
        conn.execute(text(f"SELECT count(*) FROM ({sql}) v"), params).scalar_one()
    )
    rows = conn.execute(
        text(
            f"{sql} ORDER BY f.measured_date DESC, f.model, f.color, "
            f"f.logical_vehicle_id LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()
    return _vehicle_rows(conn, rows), total


def film_month_vehicles(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    bounds: tuple[date, date],
    model: str | None,
    color: str | None,
) -> tuple[list[dict], dict[str, int]]:
    """T108: every vehicle of one month, and its readings. No LIMIT.

    The week cards are a summary of a whole month, so there is no page to
    take: `film_vehicles` is the same statement with `LIMIT`/`OFFSET`, and
    one month of one plant is a few hundred cars (169 in the owner's four
    FTM months).

    Returns the cars in the same shape `film_vehicles` returns them, and
    beside them `{logical_vehicle_id: readings}` -- active `filmthickness`
    rows, one per (point, layer) thickness -- counted by a second aggregate
    over the same predicate rather than off the join above, which carries a
    row per fact and a point list beside it. The readings stay out of the
    car so the vehicle DTO is unchanged by this read.
    """
    where, params = _where(plant_code, plant_scope, bounds=bounds, model=model, color=color)
    rows = conn.execute(
        text(
            f"{_VEHICLES.format(where=where)} "
            f"ORDER BY f.measured_date DESC, f.model, f.color, f.logical_vehicle_id"
        ),
        params,
    ).all()
    found = _vehicle_rows(conn, rows)
    readings = {
        str(vid): int(n)
        for vid, n in conn.execute(
            text(
                f"SELECT f.logical_vehicle_id, count(*) FROM {ACTIVE_VIEW} f "
                f" WHERE {where} GROUP BY 1"
            ),
            params,
        ).all()
    }
    return found, readings


def film_vehicle(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    logical_vehicle_id: str,
) -> dict | None:
    """One vehicle at this plant, or None if it has no active film fact."""
    where, params = _where(plant_code, plant_scope)
    rows = conn.execute(
        text(_VEHICLES.format(where=f"{where} AND f.logical_vehicle_id = :vid")),
        {**params, "vid": logical_vehicle_id},
    ).all()
    found = _vehicle_rows(conn, rows)
    return found[0] if found else None


def film_point_grid(
    conn: Connection, plant_code: str, model: str, logical_vehicle_id: str
) -> list[dict]:
    """Every point of this plant's gold list for `model` (T54), LEFT JOINed
    to this car's facts.

    Membership comes from `filmthickness_active` only. A point with no fact
    comes back with null layers; nothing is padded. If two active rows ever
    named one point of one car (ingest refuses that as a duplicate), the
    earliest load and row wins whole -- its four layers are never mixed with
    another row's.

    T109 (D-109-4, section 3.2): the live list **plus** any retired point
    this car actually has a reading on, tagged ``retired``. A retire means
    "stop using this point", not "forget what was measured there": dropping
    the row from this grid would make the readings of every car measured
    before the retirement unreachable, which is a silent delete of evidence
    (ADR 0005). A retired point with no reading on this car is not shown --
    it is not part of this car's story.
    """
    rows = conn.execute(
        text(
            f"""
            WITH f AS (
                SELECT point_code, src_location_text, load_id, source_row,
                       layer_code, thickness,
                       dense_rank() OVER (PARTITION BY point_code
                                          ORDER BY load_id, source_row) AS pick
                  FROM {ACTIVE_VIEW}
                 WHERE plant = :plant AND logical_vehicle_id = :vid
            )
            SELECT c.point_no, c.point_code,
                   COALESCE(s.orientation, c.orientation),
                   min(f.src_location_text), min(f.load_id), min(f.source_row),
                   min(f.thickness) FILTER (WHERE f.layer_code = 'ECOAT'),
                   min(f.thickness) FILTER (WHERE f.layer_code = 'PRIMER'),
                   min(f.thickness) FILTER (WHERE f.layer_code = 'BASE'),
                   min(f.thickness) FILTER (WHERE f.layer_code = 'CLEAR'),
                   COALESCE(s.counted, true), c.is_complete_stop,
                   c.is_extra, c.retired_at IS NOT NULL AS retired
              FROM ref_plant_film_point c
              LEFT JOIN f ON f.point_code = c.point_code AND f.pick = 1
              -- T99 (D-99-2): History shows every point of the walk, the
              -- ones that do not count included, and says which they are.
              -- A point hidden from the grid is a point nobody can put back.
              LEFT JOIN LATERAL (
                   SELECT counted, orientation
                     FROM film_point_setting ps
                    WHERE ps.plant_code = c.plant_code
                      AND ps.model_code = c.model_code
                      AND ps.point_code = c.point_code
                    ORDER BY ps.setting_id DESC
                    LIMIT 1
                   ) s ON true
             WHERE c.plant_code = :plant AND c.model_code = :model
               -- T109 (D-109-4): live, or retired with a reading on this car.
               AND (c.retired_at IS NULL
                    OR EXISTS (SELECT 1 FROM f WHERE f.point_code = c.point_code))
             GROUP BY c.point_no, c.point_code, c.orientation, c.is_complete_stop,
                      c.is_extra, c.retired_at, s.counted, s.orientation
             ORDER BY c.point_no
            """
        ),
        {"plant": plant_code, "vid": logical_vehicle_id, "model": model},
    ).all()
    return [
        {
            "point_no": int(r[0]),
            "point_code": r[1],
            "orientation": r[2].strip() if r[2] else None,
            "src_location_text": r[3],
            "load_id": None if r[4] is None else int(r[4]),
            "source_row": None if r[5] is None else int(r[5]),
            "layers": {"ecoat": r[6], "primer": r[7], "base": r[8], "clear": r[9]},
            "counted": bool(r[10]),
            "is_complete_stop": bool(r[11]),
            "is_extra": bool(r[12]),
            "retired": bool(r[13]),
        }
        for r in rows
    ]


# =====================================================================
# T66 read: monthly overview readings. SELECT only, uncapped.
# =====================================================================
def film_overview_readings(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    *,
    bounds: tuple[date, date],
    models: list[str] | None,
    colors: list[str] | None,
) -> list[dict]:
    """Every active film fact of the month, with its gold point's Hor / Ver.

    Orientation is this plant's gold list (`ref_plant_film_point`, T54),
    else the model catalogue (`ref_model_film_point`, T47): the two agree
    wherever both name the point. The colour is already folded by the view.
    T67: also `point_code` and **this plant's** colour family
    (`ref_plant_color` + `ref_color_family`, ADR 0010) on the folded colour.
    T68: also each fact row's own `measured_date` (D-68-01).
    No threshold here: spec lines and status are attached in the service.
    """
    where, params = _where(plant_code, plant_scope, bounds=bounds)
    if models:
        where += " AND f.model = ANY(:models)"
        params["models"] = list(models)
    if colors:
        where += " AND f.color = ANY(:colors)"
        params["colors"] = list(colors)
    rows = conn.execute(
        text(
            f"""
            SELECT f.logical_vehicle_id,
                   f.job_no,
                   f.model,
                   f.color,
                   COALESCE(btrim(s.orientation), btrim(pp.orientation),
                            btrim(mp.orientation))                       AS orientation,
                   f.layer_code,
                   f.thickness,
                   f.point_code,
                   f.measured_date,
                   cf.family_code,
                   cf.family_name,
                   cf.display_order
              FROM {ACTIVE_VIEW} f
              LEFT JOIN ref_plant_color pc
                ON pc.plant_code = f.plant
               AND pc.color_name = f.color
              LEFT JOIN ref_color_family cf
                ON cf.family_name = pc.family_name
              LEFT JOIN ref_plant_film_point pp
                ON pp.plant_code = f.plant
               AND pp.model_code = f.model
               AND pp.point_code = f.point_code
               AND pp.retired_at IS NULL
              LEFT JOIN ref_model_film_point mp
                ON mp.model_code = f.model
               AND mp.point_code = f.point_code
              -- T109 (section 3.1): the plant's own list row for this point
              -- when it has been **retired**. Named explicitly because the
              -- `pp` join above drops a retired row and the `mp` fallback
              -- then handed the fact a model-wide orientation, so a retired
              -- point went on feeding Hor / Ver through the catalogue.
              LEFT JOIN ref_plant_film_point rp
                ON rp.plant_code = f.plant
               AND rp.model_code = f.model
               AND rp.point_code = f.point_code
               AND rp.retired_at IS NOT NULL
              LEFT JOIN LATERAL (
                   SELECT counted, orientation
                     FROM film_point_setting ps
                    WHERE ps.plant_code = f.plant
                      AND ps.model_code = f.model
                      AND ps.point_code = f.point_code
                    ORDER BY ps.setting_id DESC
                    LIMIT 1
                   ) s ON true
             WHERE {where}
               -- T99 (D-99-2): a point the latest setting says does not
               -- count feeds no Hor / Ver box. The fact stays a fact; it is
               -- the dashboard grain that the setting decides.
               AND s.counted IS NOT false
               -- T109 (D-109-4): a retired point feeds no box either, for
               -- any month. Its readings stay in History, tagged.
               AND rp.point_code IS NULL
            """
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def film_color_options(
    conn: Connection,
    plant_code: str,
    plant_scope: list[str] | None,
    bounds: tuple[date, date],
) -> list[dict]:
    """T67: folded colours with film facts in the month, with this plant's
    family (ADR 0010). Family order (NULL last), then name, like WaveScan."""
    where, params = _where(plant_code, plant_scope, bounds=bounds)
    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT f.color AS color_name,
                   cf.family_code,
                   cf.family_name,
                   cf.display_order AS family_order
              FROM {ACTIVE_VIEW} f
              LEFT JOIN ref_plant_color pc
                ON pc.plant_code = f.plant
               AND pc.color_name = f.color
              LEFT JOIN ref_color_family cf
                ON cf.family_name = pc.family_name
             WHERE {where}
             ORDER BY family_order NULLS LAST, color_name
            """
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


# =====================================================================
# T99: the per plant x model point setting. INSERT-only (revision 0033).
# =====================================================================
def point_setting(conn: Connection, plant_code: str, model_code: str) -> list[dict]:
    """Every live point of this plant's list with its latest setting (D-99-4).

    Walk order, one row per point, and the setting's own reason / person /
    time so the page can say who last changed it and why. A point with no
    setting row at all comes back ``counted = true`` with the catalogue's
    orientation -- the shape of every plant but FTM, where the T99 rules are
    switched off and nothing reads this.
    """
    rows = conn.execute(
        text(
            """
            SELECT c.point_no, c.point_code, c.orientation, c.is_complete_stop,
                   s.counted, s.orientation, s.reason,
                   -- T115 (D-115-1): the person's name, not the uuid.
                   CASE WHEN s.created_by IS NULL THEN NULL
                        ELSE COALESCE(NULLIF(btrim(u.display_name), ''), '-')
                   END,
                   s.created_at, c.is_extra
              FROM ref_plant_film_point c
              LEFT JOIN (
                   SELECT DISTINCT ON (point_code)
                          point_code, counted, orientation, reason,
                          created_by, created_at
                     FROM film_point_setting
                    WHERE plant_code = :plant AND model_code = :model
                    ORDER BY point_code, setting_id DESC
                   ) s ON s.point_code = c.point_code
              LEFT JOIN app_user u ON u.id = s.created_by
              JOIN v_point_walk_order w ON w.plant_code=c.plant_code
                   AND w.model_code=c.model_code AND w.point_code=c.point_code
                   AND w.domain='FILMTHICKNESS'
             WHERE c.plant_code = :plant AND c.model_code = :model
               AND c.retired_at IS NULL
             ORDER BY w.walk_rank
            """
        ),
        {"plant": plant_code, "model": model_code},
    ).all()
    return [
        {
            "point_no": int(r[0]),
            "point_code": r[1],
            "counted": True if r[4] is None else bool(r[4]),
            "orientation": (r[5] or r[2] or "").strip() or None,
            "is_complete_stop": bool(r[3]),
            "reason": r[6],
            "changed_by": r[7],
            "changed_at": r[8],
            # T109 (D-109-3): beyond this plant's standard list for the model.
            "is_extra": bool(r[9]),
        }
        for r in rows
    ]


def insert_setting(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    rows: Sequence[tuple[str, bool, str]],
    reason: str,
    actor: str | None,
) -> int:
    """One **new** row per point (D-99-4). Never an UPDATE, never a DELETE.

    The older row stays exactly as it was: it is what somebody said about
    this point before, and the latest ``setting_id`` is what stands now.
    """
    written = 0
    for point_code, counted, orientation in rows:
        written += conn.execute(
            text(
                """
                INSERT INTO film_point_setting
                    (plant_code, model_code, point_code, counted, orientation,
                     reason, created_by)
                VALUES (:plant, :model, :point, :counted, :orient, :reason,
                        CAST(:actor AS uuid))
                """
            ),
            {
                "plant": plant_code, "model": model_code, "point": point_code,
                "counted": bool(counted), "orient": orientation,
                "reason": reason, "actor": actor or None,
            },
        ).rowcount
    return written


def add_walk_points(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    points: Sequence[str],
) -> list[tuple[str, int]]:
    """T99 (D-99-14): append confirmed point names to this plant's list.

    INSERT only, in the order given, each one ``point_no`` after the last
    live point. The catalogue name is created first when it is new
    (`ref_film_point` is the FK target). Nothing is moved and nothing is
    renumbered -- the one thing a confirm may never do (D-99-1), kept here by
    having no UPDATE at all rather than by a check.
    """
    last = conn.execute(
        text(
            "SELECT coalesce(max(point_no), 0) FROM ref_plant_film_point "
            "WHERE plant_code = :plant AND model_code = :model "
            "  AND retired_at IS NULL"
        ),
        {"plant": plant_code, "model": model_code},
    ).scalar_one()
    added: list[tuple[str, int]] = []
    for offset, point_code in enumerate(points, start=1):
        conn.execute(
            text(
                "INSERT INTO ref_film_point (point_code) VALUES (:code) "
                "ON CONFLICT (point_code) DO NOTHING"
            ),
            {"code": point_code},
        )
        point_no = int(last) + offset
        conn.execute(
            text(
                """
                INSERT INTO ref_plant_film_point
                    (plant_code, model_code, point_code, point_no, note,
                     is_extra)
                VALUES (:plant, :model, :code, :no, :note, true)
                """
            ),
            {
                "plant": plant_code, "model": model_code, "code": point_code,
                "no": point_no,
                "note": (
                    "T99 (D-99-14): appended to the walk by the uploader who "
                    "confirmed the sheet that first wrote it"
                ),
            },
        )
        added.append((point_code, point_no))
    return added


# =====================================================================
# T109: Point Check's own writes. INSERT, and the one column-scoped
# UPDATE revision 0035 grants (D-109-9). Never a DELETE.
# =====================================================================
def live_point_at(
    conn: Connection, plant_code: str, model_code: str, point_no: int
) -> str | None:
    """T109 (D-109-5). The live point this list already numbers ``point_no``.

    RO19 permits duplicate stable numbers after a restore. This occupancy
    read chooses one holder deterministically; add allocates a free number
    without changing any current point identity.
    """
    return conn.execute(
        text(
            "SELECT point_code FROM ref_plant_film_point "
            "WHERE plant_code = :plant AND model_code = :model "
            "  AND point_no = :no AND retired_at IS NULL ORDER BY point_code LIMIT 1"
        ),
        {"plant": plant_code, "model": model_code, "no": int(point_no)},
    ).scalar_one_or_none()


def free_point_no(
    conn: Connection, plant_code: str, model_code: str, point_no: int
) -> int:
    """RO19 F6. ``point_no`` when no row of this list carries it, else one past
    the list's highest.

    Retired rows count: a retired point keeps its number and can be restored,
    so handing its number to a new point would make two live points share one.
    """
    numbers = set(
        conn.execute(
            text(
                "SELECT point_no FROM ref_plant_film_point "
                "WHERE plant_code = :plant AND model_code = :model"
            ),
            {"plant": plant_code, "model": model_code},
        ).scalars()
    )
    number = int(point_no)
    return number if number not in numbers else max(numbers, default=0) + 1


def point_row(
    conn: Connection, plant_code: str, model_code: str, point_code: str
) -> dict | None:
    """T109. This plant's list row for the name, live **or retired**.

    Add reads it before inserting: the primary key is
    ``(plant, model, point_code)``, so a name the list has ever carried
    cannot be added again, and a person is told which of the two it is
    instead of being shown a constraint violation.
    """
    row = conn.execute(
        text(
            "SELECT point_no, retired_at, retired_reason, is_extra "
            "FROM ref_plant_film_point "
            "WHERE plant_code = :plant AND model_code = :model "
            "  AND point_code = :code"
        ),
        {"plant": plant_code, "model": model_code, "code": point_code},
    ).one_or_none()
    if row is None:
        return None
    return {
        "point_no": int(row[0]),
        "retired_at": row[1],
        "retired_reason": row[2],
        "is_extra": bool(row[3]),
    }


def add_point(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    point_code: str,
    point_no: int,
    note: str,
    orientation: str | None = None,
) -> None:
    """T109 (D-109-5). One new point on this plant's list for the model.

    The catalogue name is created first when it is new (`ref_film_point` is
    the FK target), then the list row at the number the name carries, tagged
    extra (D-109-3). INSERT only: nothing already on the list is touched, so
    adding a point can never move one.

    RO17 (D-RO17-11): ``orientation`` goes on the list row where the list has
    no `film_point_setting` (a setting row would switch the T99 rules on).
    """
    conn.execute(
        text(
            "INSERT INTO ref_film_point (point_code) VALUES (:code) "
            "ON CONFLICT (point_code) DO NOTHING"
        ),
        {"code": point_code},
    )
    conn.execute(
        text(
            """
            INSERT INTO ref_plant_film_point
                (plant_code, model_code, point_code, point_no, note, is_extra,
                 orientation)
            VALUES (:plant, :model, :code, :no, :note, true, :orient)
            """
        ),
        {
            "plant": plant_code, "model": model_code, "code": point_code,
            "no": int(point_no), "note": note, "orient": orientation,
        },
    )


def retire_point(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    point_code: str,
    reason: str,
) -> int:
    """T109 (D-109-4). Take a point off the live list, keeping everything.

    The only write is ``retired_at`` + ``retired_reason``, which are the only
    two columns revision 0035 grants `app_rw` UPDATE on (D-109-9): the
    database itself refuses to let this move a point, rename one or unname
    one. The row stays, its readings stay, and `film_point_grid` goes on
    showing them tagged. ``WHERE retired_at IS NULL`` makes it once-only --
    a second call writes nothing rather than overwriting who retired it and
    why.
    """
    return conn.execute(
        text(
            "UPDATE ref_plant_film_point "
            "   SET retired_at = now(), retired_reason = :why "
            " WHERE plant_code = :plant AND model_code = :model "
            "   AND point_code = :code AND retired_at IS NULL"
        ),
        {
            "plant": plant_code, "model": model_code, "code": point_code,
            "why": reason,
        },
    ).rowcount


def restore_point(
    conn: Connection, *, plant_code: str, model_code: str, point_code: str
) -> int:
    """RO17 (D-RO17-9). Put a retired point back on the live list.

    Clears exactly the two columns revision 0035 grants (the check allows
    both NULL; no trigger, measured in 0047). ``WHERE retired_at IS NOT
    NULL`` makes it once-only. The retire is still in `audit_event`.
    """
    return conn.execute(
        text(
            "UPDATE ref_plant_film_point "
            "   SET retired_at = NULL, retired_reason = NULL "
            " WHERE plant_code = :plant AND model_code = :model "
            "   AND point_code = :code AND retired_at IS NOT NULL"
        ),
        {"plant": plant_code, "model": model_code, "code": point_code},
    ).rowcount


def has_point_label(
    conn: Connection, plant_code: str, model_code: str, point_code: str
) -> bool:
    """RO17. Does this point have any label row (0047 gave live points one)?"""
    return bool(conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM ref_plant_film_point_label "
            " WHERE plant_code = :plant AND model_code = :model "
            "   AND point_code = :code)"
        ),
        {"plant": plant_code, "model": model_code, "code": point_code},
    ).scalar_one())


def offered_models(conn: Connection, plant_code: str) -> set[str]:
    """RO17 (D-RO17-10). The models this plant offers (`ref_plant_model`)."""
    return set(conn.execute(
        text(
            "SELECT model_code FROM ref_plant_model "
            "WHERE plant_code = :plant AND is_offered"
        ),
        {"plant": plant_code},
    ).scalars().all())


def tail_labels(
    conn: Connection, plant_code: str, model_code: str, *, not_a_point: bool = False
) -> list[dict]:
    """RO17 (D-RO17-12). This list's tail labels, live and retired.

    RO18 (B5): ``not_a_point`` picks the uploaders' "Not a point of this list"
    answers instead; they live on the Aliases screen, not Point Check.
    """
    rows = conn.execute(
        text(
            "SELECT label_norm, note, created_at, retired_at, retired_reason "
            "  FROM ref_plant_film_tail_label "
            " WHERE plant_code = :plant AND model_code = :model "
            "   AND not_a_point = :answered "
            " ORDER BY label_norm"
        ),
        {"plant": plant_code, "model": model_code, "answered": not_a_point},
    ).mappings().all()
    return [dict(r) for r in rows]


def add_tail_label(
    conn: Connection, *, plant_code: str, model_code: str, label_norm: str,
    note: str, not_a_point: bool = False,
) -> int:
    """RO17 (D-RO17-12). One new tail label. INSERT only. RO18 (B5):
    ``not_a_point`` marks an uploader's "Not a point of this list" answer."""
    return conn.execute(
        text(
            "INSERT INTO ref_plant_film_tail_label "
            "    (plant_code, model_code, label_norm, note, not_a_point) "
            "VALUES (:plant, :model, :label, :note, :answered)"
        ),
        {"plant": plant_code, "model": model_code, "label": label_norm,
         "note": note, "answered": not_a_point},
    ).rowcount


def set_tail_label_retired(
    conn: Connection, *, plant_code: str, model_code: str, label_norm: str,
    reason: str | None,
) -> int:
    """RO17 (D-RO17-12). Retire (``reason``) or restore (None) a tail label.

    The PK is (plant, model, label_norm), so re-adding a retired one clears
    its two retire columns -- the only UPDATE 0047 grants on this table.
    """
    flip = "retired_at IS NULL" if reason else "retired_at IS NOT NULL"
    return conn.execute(
        text(
            "UPDATE ref_plant_film_tail_label "
            "   SET retired_at = CASE WHEN CAST(:why AS text) IS NULL "
            "                         THEN NULL ELSE now() END, "
            "       retired_reason = :why "
            " WHERE plant_code = :plant AND model_code = :model "
            f"  AND label_norm = :label AND {flip}"
        ),
        {"plant": plant_code, "model": model_code, "label": label_norm,
         "why": reason},
    ).rowcount


def retired_points(
    conn: Connection, plant_code: str, model_code: str
) -> list[dict]:
    """T109 (D-109-4, section 3.7). The points this list used to walk.

    `point_setting` is the **live** list -- it is what the walk is, what the
    picker may offer and what a change may touch -- so a retire would
    otherwise disappear from the screen that made it, and the reason the
    person typed would be readable nowhere. These rows are read-only: the
    one thing Point Check shows about a retired point is when it went and
    why, beside the readings that are still in History.
    """
    rows = conn.execute(
        text(
            """
            SELECT point_no, point_code, orientation, is_extra,
                   retired_at, retired_reason
              FROM ref_plant_film_point
             WHERE plant_code = :plant AND model_code = :model
               AND retired_at IS NOT NULL
             ORDER BY point_no
            """
        ),
        {"plant": plant_code, "model": model_code},
    ).all()
    return [
        {
            "point_no": int(r[0]),
            "point_code": r[1],
            "orientation": (r[2] or "").strip() or None,
            "is_extra": bool(r[3]),
            "retired_at": r[4],
            "retired_reason": r[5],
        }
        for r in rows
    ]


def insert_point_alias(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    raw_location_norm: str,
    point_code: str,
    reason: str,
    actor: str | None,
) -> int:
    """T109 (D-109-6). Remember that this label is that live point.

    One INSERT into the T109 alias store. `ref_film_location_map` is never
    written: its 118 FTM rows are all retired and are the record for the
    facts that were mapped through them, and its key could not hold a live
    row beside one of them anyway (D-109-8).
    """
    return conn.execute(
        text(
            """
            INSERT INTO ref_film_point_alias
                (plant_code, model_code, raw_location_norm, point_code,
                 reason, created_by)
            VALUES (:plant, :model, :raw, :code, :reason, CAST(:actor AS uuid))
            """
        ),
        {
            "plant": plant_code, "model": model_code, "raw": raw_location_norm,
            "code": point_code, "reason": reason, "actor": actor or None,
        },
    ).rowcount


def live_alias(
    conn: Connection, plant_code: str, model_code: str, raw_location_norm: str
) -> str | None:
    """T109. The live point this label is already remembered as, if any."""
    return conn.execute(
        text(
            "SELECT point_code FROM ref_film_point_alias "
            "WHERE plant_code = :plant AND model_code = :model "
            "  AND raw_location_norm = :raw AND retired_at IS NULL"
        ),
        {"plant": plant_code, "model": model_code, "raw": raw_location_norm},
    ).scalar_one_or_none()


def plant_film_models(conn: Connection, plant_code: str) -> list[dict]:
    """T100 (Part A3): the Film models this plant has a live point list for.

    No read listed them before, so the Points panel had no way to offer a
    model without being told one. Live rows only, so a list T83 retired does
    not come back as an empty page.

    T103-FIX (D-103F-1): `point_count` is the size of the **list**, so it is
    counted over `point_code` and not over the joined rows. `count(*)` here
    counted a point once per `film_point_setting` row it had, which is 1 for
    a seeded point and more as soon as somebody corrects one (D-99-4, an
    append-only table) -- live FTM Ranger read 100 for a list of 98 after the
    two D-101-4 rows on `095RBXFLOOR`.
    """
    rows = conn.execute(
        text(
            """
            SELECT c.model_code, m.display_name,
                   count(DISTINCT c.point_code) AS n,
                   bool_or(s.setting_id IS NOT NULL) AS has_setting
              FROM ref_plant_film_point c
              JOIN ref_model m ON m.model_code = c.model_code
              LEFT JOIN film_point_setting s
                ON s.plant_code = c.plant_code
               AND s.model_code = c.model_code
               AND s.point_code = c.point_code
             WHERE c.plant_code = :plant AND c.retired_at IS NULL
             GROUP BY c.model_code, m.display_name
             ORDER BY c.model_code
            """
        ),
        {"plant": plant_code},
    ).all()
    return [
        {
            "model_code": r[0],
            "display_name": r[1],
            "point_count": int(r[2]),
            "has_setting": bool(r[3]),
        }
        for r in rows
    ]
