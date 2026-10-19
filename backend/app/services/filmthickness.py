"""FilmThickness reads: facets, vehicles, the gold point grid (T48).

Every statement reads `filmthickness_active` (the one film predicate,
`01-DATA-MODEL.md` section 10); nothing here writes, audits or grades.

* **A film vehicle is `filmthickness.logical_vehicle_id`** (T46), not a
  WaveScan History vehicle: `load_id` is not inside it, so a Cab walk and a
  Box walk of one car are one vehicle whose points are the union across
  loads. `load_ids` rides along as provenance.
* **The point grid is the model's catalogue**, not the rows a file had:
  94 gold points for P703 DBL Ranger / Raptor with the owner's Hor / Ver,
  or RAPCAP's / SGL's own list. An unmeasured slot is null.
* **The plant is resolved as History resolves it** (code or alias, any
  case); unknown is 404, a known plant with no film is an empty 200.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection

from app.domain import film_history
from app.domain import history as rules
from app.domain.film_walk import box_tag
from app.repositories import filmthickness as repo
from app.services.history import HistoryError, resolve_plant

__all__ = [
    "HistoryError",
    "resolve_plant",
    "facets",
    "summaries",
    "vehicles",
    "points",
]


def _bounds(month: str) -> tuple[date, date]:
    try:
        return rules.month_date_bounds(month)
    except ValueError as exc:  # pragma: no cover - the route pattern refuses first
        raise HistoryError(422, str(exc)) from exc


def _complete(vehicle: dict) -> dict:
    """Is this car's walk whole?

    Until T99 the answer was one number: the size of the plant's live list.
    D-99-8 adds the measured fact that an FTM truck built without a box is
    **finished** at ``059RTFEND`` (RAPCAP) or ``064RAPILLAR`` (DBL) -- a whole
    vehicle, not a short one -- so where a list names the points a complete
    walk may stop at, a car that walked to one of them with no gap is
    complete and that stop is what was expected of it. A car that stopped
    anywhere else still loads and is still shown incomplete, against the
    whole list. A list that names no stop keeps the old answer exactly.

    T103 (D-103-1) reads the same two facts a second way: the points after
    the lowest stop are the list's **box** section, so a car with a reading
    there is a Box truck and a car without one is not.
    """
    expected = vehicle["expected_point_count"]
    stops = vehicle.get("stop_point_nos") or []
    walked_to = vehicle.get("walked_to")
    mapped = vehicle["mapped_point_count"]
    if stops and walked_to in stops:
        # No gap: a car with points 1, 2 and 98 walked *to* 98 but is not
        # the list up to 98.
        if mapped == walked_to:
            expected = walked_to
    return {
        # `walked_to` and `stop_point_nos` are how this function knows; they
        # are not part of the contract and stay out of the DTO.
        **{k: v for k, v in vehicle.items()
           if k not in ("walked_to", "stop_point_nos")},
        "identity_complete": bool(vehicle["serial_no"] or vehicle["job_nos"]),
        "incomplete": expected is None or mapped != expected,
        "expected_point_count": expected,
        # T103 (D-103-1): the highest point this car reached against the
        # list's lowest stop, by the one function that owns the rule. The
        # review screen answers the same question the same way.
        "box": box_tag(stops, [] if walked_to is None else [walked_to]),
    }


def facets(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str | None,
    model: str | None,
    color: str | None,
) -> dict:
    """Months with film facts, then models in that month, then colours."""
    months = repo.film_months(conn, plant_code, plant_scope)
    models: list[str] = []
    colors: list[str] = []
    if month:
        bounds = _bounds(month)
        models = repo.film_distinct(conn, "model", plant_code, plant_scope, bounds)
        colors = repo.film_distinct(conn, "color", plant_code, plant_scope, bounds, model=model)
    return {
        "months": months,
        "default_month": months[0] if months else None,
        "month": month,
        "models": models,
        "model": model,
        "colors": colors,
        "color": color,
    }


def vehicles(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str,
    week: int | None = None,
    model: str | None,
    color: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """The cars of one month, or (T108) of one week card of that month.

    Without a `week` this is the month, paged by the database exactly as it
    was before T108. With one, the month's cars are read whole and the week
    is applied **here**, by `domain.history.measured_week` -- the same
    function the cards are grouped by, so a car can never be under a card it
    is not in. The page is then taken over the filtered list, which is what
    makes `page.total` the card's own number.
    """
    if week is None:
        found, total = repo.film_vehicles(
            conn, plant_code, plant_scope, bounds=_bounds(month), model=model,
            color=color, limit=limit, offset=offset,
        )
        return [_complete(v) for v in found], total
    rows, _readings = repo.film_month_vehicles(
        conn, plant_code, plant_scope, bounds=_bounds(month), model=model,
        color=color,
    )
    cars = [
        _complete(v) for v in rows
        if rules.week_of(v["measured_date"], v.get("date_is_month_only", False)) == week
    ]
    return cars[offset:offset + limit], len(cars)


def summaries(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str,
    model: str | None,
    color: str | None,
) -> list[film_history.FilmWeekSummary]:
    """T108 (D-108-1): week -> model + colour cards for one Film month.

    The cards are folded from **the cars this service already publishes** --
    the same `_complete` rows the vehicles read returns for the same month,
    model and colour -- so `vehicle_count`, `box_count`, `no_box_count` and
    `incomplete_count` are those cars' own numbers and cannot drift from
    them. The week bands are WaveScan's, by import (`domain.film_history`).
    """
    rows, readings = repo.film_month_vehicles(
        conn, plant_code, plant_scope, bounds=_bounds(month),
        model=model, color=color,
    )
    return film_history.summarize([
        {**_complete(v), "reading_count": readings.get(v["logical_vehicle_id"], 0)}
        for v in rows
    ])


def points(
    conn: Connection,
    plant_code: str,
    logical_vehicle_id: str,
    *,
    plant_scope: list[str] | None,
) -> dict:
    """The vehicle and its model's whole catalogue. 404 if no active fact."""
    vehicle = repo.film_vehicle(conn, plant_code, plant_scope, logical_vehicle_id)
    if vehicle is None:
        raise HistoryError(
            404,
            f"No active FilmThickness vehicle {logical_vehicle_id} at {plant_code}. "
            f"GET .../filmthickness/vehicles lists the ones that exist.",
        )
    grid = repo.film_point_grid(conn, plant_code, vehicle["model"], logical_vehicle_id)
    return {"vehicle": _complete(vehicle), "items": grid}
