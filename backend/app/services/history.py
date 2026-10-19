"""Measurement History: four reads of active facts, for any authenticated role.

This service answers "what approved measurements does this plant hold, and
how do they group" entirely from `v_wavescan_active` (T23 locked decision 1).
It writes nothing, opens no workbook, computes no grade, and holds no
expected point count of its own -- `ref_model.expected_zone_count` is read
from the database and injected into the domain.

Two rules worth stating where they are implemented:

* **A History vehicle is a T21 vehicle.** The id comes from
  `domain.workbooks.vehicle_id` with `load_id` inside it, so the review
  dialog and the History drill-down agree about what one vehicle is, and two
  sheets that measured the same serial on the same day never merge.
* **The plant is resolved exactly as the Data Manager resolves it** -- code
  or approved alias, any case -- so `/plants/ftm/history/...` and
  `/plants/FTM/...` are one plant, and an unknown code is a 404 while a
  known un-onboarded one (FVL, D5) is an empty 200.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from sqlalchemy import Connection

from app.domain import history as rules
from app.domain.workbooks import car_labels
from app.repositories import history as repo
from app.repositories import reference as reference_repo
from app.repositories import workbooks as plants_repo
from app.repositories import ws_points as ws_points_repo


class HistoryError(RuntimeError):
    """A History read was refused. Carries the HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def resolve_plant(conn: Connection, plant_code: str) -> dict:
    """The plant this URL names, or 404 -- the same resolution as T19."""
    plant = plants_repo.resolve_plant(conn, plant_code)
    if plant is None:
        raise HistoryError(
            404,
            f"No plant {plant_code!r}. Plant codes and their aliases come from "
            f"ref_plant / ref_plant_alias; GET /api/v1/meta lists them.",
        )
    return plant


def _bounds(month: str) -> tuple[date, date]:
    try:
        return rules.month_date_bounds(month)
    except ValueError as exc:  # pragma: no cover - the route pattern refuses first
        raise HistoryError(422, str(exc)) from exc


def _expected_zones(conn: Connection) -> dict[str, int]:
    """`ref_model.expected_zone_count` per model. Never a literal count."""
    return dict(reference_repo.load_reference_data(conn).expected_zones)


# =====================================================================
def facets(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str | None,
    model: str | None,
    color: str | None,
) -> dict:
    """Months, then models in that month, then colours in that model.

    Without a month there is nothing to cascade from, so `models` and
    `colors` are empty rather than a list of everything the plant has ever
    measured -- which is the list the client would then have to filter
    itself.
    """
    found = repo.months(conn, plant_code, plant_scope)
    models: list[str] = []
    colors: list[str] = []
    if month:
        bounds = _bounds(month)
        models = repo.models(conn, plant_code, plant_scope, bounds)
        colors = repo.colors(conn, plant_code, plant_scope, bounds, model=model)
    return {
        "months": found,
        "default_month": found[0] if found else None,
        "month": month,
        "models": models,
        "model": model,
        "colors": colors,
        "color": color,
    }


def _vehicles(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    bounds: tuple[date, date] | None,
    model: str | None,
    color: str | None,
) -> list[rules.HistoryVehicle]:
    groups = repo.identity_groups(
        conn, plant_code, plant_scope, bounds=bounds, model=model, color=color
    )
    # T114-FIX (D-114F-1): complete against this plant's live, non-extra list.
    found = rules.group_vehicles(
        groups, _expected_zones(conn), ws_points_repo.live_lists(conn, plant_code)
    )
    # D-RO17-17: a car with a car_key is told apart from its same-day cars.
    first = {(g["load_id"], g["measured_date"], g["car_key"]): g["first_source_row"]
             for g in groups if g["car_key"]}
    labels = car_labels(
        (v.vehicle_id, (v.load_id, v.measured_date, v.model, v.color),
         first[(v.load_id, v.measured_date, v.car_key)])
        for v in found if v.car_key
    )
    return [replace(v, car_label=labels[v.vehicle_id]) if v.car_key else v
            for v in found]


def summaries(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str,
    model: str | None,
    color: str | None,
) -> list[rules.WeekSummary]:
    """Week -> model + colour cards for one month. Weeks descending."""
    vehicles = _vehicles(
        conn, plant_code, plant_scope=plant_scope, bounds=_bounds(month),
        model=model, color=color,
    )
    return rules.summarize(vehicles)


def vehicles(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str,
    week: int,
    model: str,
    color: str,
    limit: int,
    offset: int,
) -> tuple[list[rules.HistoryVehicle], int]:
    """The vehicle sets behind one week / model / colour card."""
    found = [
        v for v in _vehicles(
            conn, plant_code, plant_scope=plant_scope, bounds=_bounds(month),
            model=model, color=color,
        )
        if v.week == week
    ]
    return found[offset:offset + limit], len(found)


def points(
    conn: Connection,
    plant_code: str,
    vehicle_id: str,
    *,
    plant_scope: list[str] | None,
    limit: int,
    offset: int,
) -> dict:
    """One vehicle set's active facts, by checkzone then source row.

    The id is a hash, so the set it names is found by grouping this plant's
    active facts and comparing ids -- the same grouping the vehicles read
    uses. An id that belongs to another plant, to a review row that never
    committed, or to a superseded sheet matches nothing here and is a 404:
    History answers what is current, and saying "not here" is the honest
    answer for all three.
    """
    found = next(
        (
            v for v in _vehicles(
                conn, plant_code, plant_scope=plant_scope, bounds=None,
                model=None, color=None,
            )
            if v.vehicle_id == vehicle_id
        ),
        None,
    )
    if found is None:
        raise HistoryError(
            404,
            f"No active vehicle set {vehicle_id} at plant {plant_code}. A "
            f"vehicle_id names one set of committed, current measurements; a "
            f"set that was never committed, or whose batch has been retired, "
            f"is not readable here.",
        )
    rows = repo.points(
        conn,
        plant_code,
        plant_scope,
        load_id=found.load_id,
        measured_date=found.measured_date,
        model=found.model,
        color=found.color,
        serial_no=found.serial_no,
        car_key=found.car_key,
    )
    # T114: Point Check's tags, read beside the facts rather than joined into
    # them (T23 locked the facts read to two joins). A checkzone the list has
    # never held carries no tag.
    states = (
        ws_points_repo.point_states(conn, plant_code, found.model)
        if found.model else {}
    )
    for row in rows:
        state = states.get(row["checkzone"])
        if state is not None:
            row.update(state)
    return {
        "vehicle": found,
        "items": rows[offset:offset + limit],
        "total": len(rows),
    }


__all__ = [
    "HistoryError",
    "facets",
    "points",
    "resolve_plant",
    "summaries",
    "vehicles",
]
