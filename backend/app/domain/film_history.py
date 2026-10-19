"""T108: Film History's week -> model + colour cards.

Pure rules, no SQL and no FastAPI. One function, and it decides nothing the
server has not already decided about each car:

* **The week is WaveScan's week.** `domain.history.measured_week` owns the
  day bands (1 = days 1-7 ... 5 = 29 to the end of the month,
  `02-PIPELINE.md` section 8.1). It is imported here, not re-derived, so
  Film History and WaveScan History can never disagree about which week a
  day belongs to.
* **Box / No box and incomplete are the car's own fields.** `box` comes from
  `domain.film_walk.box_tag` and `incomplete` from the T99 completeness rule,
  both already applied per car by `services.filmthickness`. This module only
  counts them, so a card can never say something its cars do not
  (D-108-4). A car whose list names no stop has `box: null` and is counted
  in neither `box_count` nor `no_box_count`.
* **`point_count` is readings**, not points: one (car, point, layer)
  thickness is one reading, which is the grain of `filmthickness`. It is
  carried per car by the repository, never guessed from a point count.

Nothing here computes a grade, a pass rate or an average. D1 is open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

from app.domain.film_walk import BOX, NO_BOX
from app.domain.history import week_of


@dataclass(frozen=True)
class FilmCard:
    """One model + colour card inside a week of Film History."""

    model: str
    model_display_name: str | None
    color: str
    vehicle_count: int
    point_count: int
    box_count: int
    no_box_count: int
    incomplete_count: int
    measured_date_min: date
    measured_date_max: date


@dataclass
class FilmWeekSummary:
    week: int
    measured_date_min: date
    measured_date_max: date
    cards: list[FilmCard] = field(default_factory=list)


def _count(cars: Iterable[dict], key: str, value: object) -> int:
    return sum(1 for car in cars if car.get(key) == value)


def summarize(vehicles: Sequence[dict]) -> list[FilmWeekSummary]:
    """Film cars -> weeks descending, each with its model + colour cards.

    `vehicles` are the cars `services.filmthickness` already published for
    the same month and filters -- the same dicts the vehicles read returns,
    each with `reading_count` added by the repository. So a card's counts are
    the counts of the cars behind it by construction: summing a week's
    `vehicle_count` gives the cars of that week, and its `box_count` /
    `no_box_count` / `incomplete_count` are those cars' own tags and flags.

    Weeks with no cars are omitted; an empty list is an empty state, not a
    zero KPI. Cards are sorted by model then colour, as WaveScan's are.
    """
    buckets: dict[int, dict[tuple[str, str], list[dict]]] = {}
    for car in vehicles:
        week = week_of(car["measured_date"], car.get("date_is_month_only", False))
        key = (car["model"], car["color"])
        buckets.setdefault(week, {}).setdefault(key, []).append(car)

    weeks: list[FilmWeekSummary] = []
    for week in sorted(buckets, reverse=True):
        cards: list[FilmCard] = []
        days: list[date] = []
        for key in sorted(buckets[week]):
            cars = buckets[week][key]
            dates = [car["measured_date"] for car in cars]
            days.extend(dates)
            cards.append(FilmCard(
                model=key[0],
                # A property of the model, so one card has one of them.
                model_display_name=cars[0].get("model_display_name"),
                color=key[1],
                vehicle_count=len({car["logical_vehicle_id"] for car in cars}),
                point_count=sum(int(car["reading_count"]) for car in cars),
                box_count=_count(cars, "box", BOX),
                no_box_count=_count(cars, "box", NO_BOX),
                incomplete_count=_count(cars, "incomplete", True),
                measured_date_min=min(dates),
                measured_date_max=max(dates),
            ))
        weeks.append(FilmWeekSummary(
            week=week,
            measured_date_min=min(days),
            measured_date_max=max(days),
            cards=cards,
        ))
    return weeks


__all__ = ["FilmCard", "FilmWeekSummary", "summarize"]
