"""Measurement History rules: weeks, month bounds, and active-fact grouping.

No FastAPI, no psycopg, no SQL (`00-ARCHITECTURE.md` section 5 rule 1, and
`AGENTS.md` rule 8). Everything takes values and returns values.

Three things live here and nowhere else:

* **The week bands.** Week 1 = days 1-7, Week 2 = 8-14, Week 3 = 15-21,
  Week 4 = 22-28, Week 5 = 29 to the end of that calendar month
  (`02-PIPELINE.md` section 8.1). History emits the week as a **field** on a
  summary; there is no week resource, and T21's Upload Data weeks stay the
  client's, computed from `uploaded_at` (T23 locked decision 6).
* **Grouping active facts into vehicle sets**, by calling
  `domain.workbooks.identity_of` and `domain.workbooks.vehicle_id`. The
  SHA-256 is **not** re-implemented here: a History vehicle and a review
  vehicle of the same committed sheet are the same id, and `load_id` stays
  inside the hash, so two sheets that measured the same serial on the same
  day are two vehicles rather than one merged card.
* **Summarising those sets into week / model / colour cards.**

**No expected point count is defaulted here.** The plant's live list
(`live_points`) and `ref_model.expected_zone_count` are injected and
`domain.completeness` applies T114-FIX's rule; an unknown model answers
null, and the number 32 appears nowhere in this module (T23 locked
decision 9).

Nothing here computes a grade, a pass rate or a band. D1 is open.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Mapping, Sequence

from app.domain.completeness import wavescan_points
from app.domain.workbooks import (
    identity_is_complete,
    identity_of,
    parse_month,
    vehicle_id,
)

#: (first day, last day) of each week band. Week 5's end is the last day of
#: the month, which is 28, 29, 30 or 31 -- never assumed.
WEEK_BANDS: tuple[tuple[int, int], ...] = ((1, 7), (8, 14), (15, 21), (22, 28), (29, 31))

WEEKS: tuple[int, ...] = (1, 2, 3, 4, 5)


def measured_week(day: int) -> int:
    """The week band a day of the month falls in, 1..5.

    Raises for a day that is not a real day of a month; the repository never
    passes one, because the value comes from a `date` column.
    """
    if not isinstance(day, int) or isinstance(day, bool) or not 1 <= day <= 31:
        raise ValueError(f"{day!r} is not a day of a month")
    for week, (first, last) in enumerate(WEEK_BANDS, start=1):
        if first <= day <= last:
            return week
    raise ValueError(f"no week band contains day {day}")  # pragma: no cover


#: RO18 (B4, RO09). The "day not recorded" group: a car whose sheet had no
#: date is filed on the 1st of a named month and is never put in week 1.
MONTH_ONLY_WEEK = 0


def week_of(measured_date: date, month_only: bool = False) -> int:
    """The week band of a stored car, or ``MONTH_ONLY_WEEK`` (RO18 B4)."""
    return MONTH_ONLY_WEEK if month_only else measured_week(measured_date.day)


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def month_date_bounds(yyyy_mm: str) -> tuple[date, date]:
    """First and last calendar day of `YYYY-MM`. ValueError if it is not one.

    The last day is the month's own -- 28, 29, 30 or 31 -- so a February
    range does not reach into March and a 31-day month does not stop on the
    30th.
    """
    year, month = parse_month(yyyy_mm)
    return date(year, month, 1), date(year, month, _last_day(year, month))


def week_date_bounds(yyyy_mm: str, week: int) -> tuple[date, date]:
    """First and last day of one week band inside `YYYY-MM`.

    Week 5 ends on the month's last day, so a 28-day February has no week 5
    at all (its first day would be the 29th, which does not exist) and this
    raises rather than inventing one.
    """
    if week not in WEEKS:
        raise ValueError(f"{week!r} is not a week band (1..5)")
    first_of_month, last_of_month = month_date_bounds(yyyy_mm)
    first_day, last_day = WEEK_BANDS[week - 1]
    if first_day > last_of_month.day:
        raise ValueError(
            f"{yyyy_mm} has {last_of_month.day} days, so it has no week {week}"
        )
    return (
        first_of_month.replace(day=first_day),
        first_of_month.replace(day=min(last_day, last_of_month.day)),
    )


@dataclass(frozen=True)
class HistoryVehicle:
    """One vehicle set of active facts, on one committed sheet."""

    vehicle_id: str
    load_id: int
    measured_date: date
    model: str | None
    color: str | None
    serial_no: str | None
    identity_complete: bool
    point_count: int
    expected_point_count: int | None
    incomplete_set: bool
    source_file: str | None
    source_sheet: str | None
    week: int
    #: Active measurement rows in this set. A card's point count is the sum
    #: of these, which is what makes it agree with `GET /measurements`.
    row_count: int
    #: RO16 (D-RO16-5). Which car of a many-car blank-serial sheet this is;
    #: in the id only when present, so every other id is unchanged. Not in
    #: any response: the cars are told apart by id.
    car_key: str | None = None
    #: D-RO17-17: "car n of m that day - from row r"; set by services.history.
    car_label: str | None = None
    #: RO17-FIX (D-RO17F-4): same-day cars sort in car order, not by id.
    first_source_row: int = 0
    #: RO18 (B4): the sheet had no date; the day is not recorded.
    date_is_month_only: bool = False


@dataclass(frozen=True)
class SummaryCard:
    model: str | None
    color: str | None
    vehicle_count: int
    point_count: int
    measured_date_min: date
    measured_date_max: date


@dataclass
class WeekSummary:
    week: int
    measured_date_min: date
    measured_date_max: date
    cards: list[SummaryCard] = field(default_factory=list)


def _present(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def group_vehicles(
    rows: Iterable[Mapping],
    expected_zones: Mapping[str, int],
    live_points: Mapping[str, frozenset[str]] | None = None,
) -> list[HistoryVehicle]:
    """Active identity groups -> vehicle sets, in History order.

    Each row is one `(load_id, measured_date, model, color, serial_no)` group
    the repository already aggregated, carrying `row_count` (active rows) and
    `zones` (its distinct checkzones), plus `source_file` and
    `source_sheet` as provenance.

    * The id comes from `domain.workbooks.vehicle_id` with `load_id` in it,
      so two sheets that measured the same serial on the same day stay two
      vehicles.
    * A missing part of the key makes the set `identity_complete: false`. No
      serial is generated and `source_row` is never the card id (design M7).
    * T114-FIX: `point_count` / `expected_point_count` are
      `domain.completeness.wavescan_points` -- the live, non-extra points of
      this plant's list for the model and how many of them the set has a
      reading on; `ref_model.expected_zone_count` and every distinct
      checkzone when the model has no list; null expected when the model is
      unknown. `incomplete_set` follows T23 locked decision 9.

    Order: identity-incomplete first, then measured date, model, colour,
    serial, `load_id`.
    """
    out: list[HistoryVehicle] = []
    for row in rows:
        measured_date = row["measured_date"]
        identity = identity_of({
            "measured_date": measured_date.isoformat() if measured_date else None,
            "model": row.get("model"),
            "color": row.get("color"),
            "serial_no": row.get("serial_no"),
        })
        complete = identity_is_complete(identity)
        model = _present(row.get("model"))
        points, expected = wavescan_points(
            row["zones"], model, live_points=live_points, expected_zones=expected_zones
        )
        car_key = _present(row.get("car_key"))
        out.append(HistoryVehicle(
            # RO16: the review's id for the same car (`workbooks.set_key`).
            vehicle_id=vehicle_id(
                int(row["load_id"]), identity + ((car_key,) if car_key else ())
            ),
            load_id=int(row["load_id"]),
            measured_date=measured_date,
            model=model,
            color=_present(row.get("color")),
            serial_no=_present(row.get("serial_no")),
            identity_complete=complete,
            point_count=points,
            expected_point_count=expected,
            incomplete_set=(not complete) or (expected is not None and points != expected),
            source_file=row.get("source_file"),
            source_sheet=row.get("source_sheet"),
            week=week_of(measured_date, bool(row.get("date_is_month_only"))),
            date_is_month_only=bool(row.get("date_is_month_only")),
            row_count=int(row["row_count"]),
            car_key=car_key,
            first_source_row=int(row.get("first_source_row") or 0),
        ))

    def order(item: HistoryVehicle):
        return (
            item.identity_complete,
            item.measured_date,
            *((part is not None, part or "") for part in
              (item.model, item.color, item.serial_no)),
            item.load_id,
            item.first_source_row,
            item.car_key or "",
        )

    return sorted(out, key=order)


def summarize(vehicles: Sequence[HistoryVehicle]) -> list[WeekSummary]:
    """Week -> model + colour cards, weeks descending, empty weeks omitted.

    A card's `point_count` is the number of **active measurement rows**, so
    summing the cards of a month gives the same number as
    `GET /measurements` reports for the same filters (T23 locked decision
    10). `vehicle_count` counts distinct vehicle ids, not distinct serials.
    """
    buckets: dict[int, dict[tuple[str | None, str | None], list[HistoryVehicle]]] = {}
    for item in vehicles:
        buckets.setdefault(item.week, {}).setdefault((item.model, item.color), []).append(item)

    weeks: list[WeekSummary] = []
    for week in sorted(buckets, reverse=True):
        cards: list[SummaryCard] = []
        dates: list[date] = []
        for key in sorted(
            buckets[week],
            key=lambda k: ((k[0] is not None, k[0] or ""), (k[1] is not None, k[1] or "")),
        ):
            members = buckets[week][key]
            days = [m.measured_date for m in members]
            dates.extend(days)
            cards.append(SummaryCard(
                model=key[0],
                color=key[1],
                vehicle_count=len({m.vehicle_id for m in members}),
                point_count=sum(m.row_count for m in members),
                measured_date_min=min(days),
                measured_date_max=max(days),
            ))
        weeks.append(WeekSummary(
            week=week,
            measured_date_min=min(dates),
            measured_date_max=max(dates),
            cards=cards,
        ))
    return weeks


__all__ = [
    "HistoryVehicle",
    "SummaryCard",
    "WEEKS",
    "WEEK_BANDS",
    "WeekSummary",
    "group_vehicles",
    "measured_week",
    "MONTH_ONLY_WEEK",
    "week_of",
    "month_date_bounds",
    "summarize",
    "week_date_bounds",
]
