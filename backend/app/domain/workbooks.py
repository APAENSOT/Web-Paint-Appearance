"""Workbook-level rules that are pure decisions about statuses and dates.

No FastAPI, no psycopg, no SQL (`00-ARCHITECTURE.md` section 5 rule 1, and
`AGENTS.md` rule 8). Everything here takes values and returns values, so the
two rules that are easiest to get subtly wrong -- what a mixed-status
workbook is called, and whether two date ranges touch -- are testable without
a database.

**The operational summary is a workflow label, not a grade** (T19 locked
decision 4). It says where a file is in upload -> review -> commit, and
nothing at all about whether the measurements in it are good. There is no
pass rate here, no Ford band, no percentage; D1 is open and this module is
not the place anybody gets to close it by accident.

**T21 adds three more pure rules**: which workbooks belong in an upload
inbox, how a sheet's rows fold into vehicle sets, and the id a vehicle set
is addressed by. The expected point count of a vehicle is injected (the
plant's live list, else `ref_model.expected_zone_count`; T114-FIX); this
module holds no default for it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Iterable, Mapping, Sequence

from app.domain.completeness import wavescan_points

#: The six labels, and the order the rules below try them in.
SUMMARY_SUPERSEDED = "SUPERSEDED"
SUMMARY_ABANDONED = "ABANDONED"
SUMMARY_PROCESSING = "PROCESSING"
SUMMARY_PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
SUMMARY_ACTIVE = "ACTIVE"
SUMMARY_REVIEW_REQUIRED = "REVIEW_REQUIRED"
SUMMARY_SKIPPED = "SKIPPED"

SUMMARIES: tuple[str, ...] = (
    SUMMARY_PROCESSING,
    SUMMARY_REVIEW_REQUIRED,
    SUMMARY_PARTIALLY_COMMITTED,
    SUMMARY_ACTIVE,
    SUMMARY_SUPERSEDED,
    SUMMARY_ABANDONED,
    SUMMARY_SKIPPED,
)

STATUS_RUNNING = "RUNNING"
STATUS_COMMITTED = "COMMITTED"
STATUS_SUPERSEDED = "SUPERSEDED"
STATUS_ABANDONED = "ABANDONED"

#: Statuses that take a sheet out of the live workflow. Neither deletes
#: anything: a superseded sheet's facts stay in `wavescan`, an abandoned
#: sheet never had any, and both keep their staging and audit trail.
RETIRED_STATUSES = frozenset({STATUS_SUPERSEDED, STATUS_ABANDONED})


def operational_summary(statuses: Sequence[str]) -> str:
    """One label for a workbook, from its sheets' `load_batch.status` values.

    The rules, highest first, as T19 locked them and T21 extended them. A
    sheet is **live** when its status is neither `SUPERSEDED` nor
    `ABANDONED`.

    1. No live sheet -> `SUPERSEDED` if any sheet is `SUPERSEDED`, otherwise
       `ABANDONED` (T21 locked decision 12). A retired workbook keeps its
       place in the file list, muted; it is not hidden, because the
       measurements it produced are still in `wavescan` -- or, for an
       abandoned one, because its evidence is -- and somebody will want to
       know where they came from (design M14, F6).
    2. Any live sheet `RUNNING` -> `PROCESSING`. The worker has not finished,
       so no other label would be true yet.
    3. Some live sheets committed and some not -> `PARTIALLY_COMMITTED`. This
       is a real and common state: commit is per sheet and per transaction
       (design M12), and a workbook whose second tab is blocked must not read
       as finished.
    4. All live sheets committed -> `ACTIVE`.
    5. Anything else (`PENDING_REVIEW`, `REJECTED_TEMPLATE`, `FAILED`, or a
       mixture) -> `REVIEW_REQUIRED`. A person has to look.

    Every sheet still carries its own real status alongside this; the label
    exists so a file list is readable, not so a status is hidden.

    An empty sequence answers `PROCESSING`: a workbook with no sheets at all
    should not exist, and if one ever does, "we do not know yet" is the only
    honest thing to say about it.
    """
    live = [s for s in statuses if s not in RETIRED_STATUSES]
    if statuses and not live:
        if any(s == STATUS_SUPERSEDED for s in statuses):
            return SUMMARY_SUPERSEDED
        return SUMMARY_ABANDONED
    if not live:
        return SUMMARY_PROCESSING
    if any(s == STATUS_RUNNING for s in live):
        return SUMMARY_PROCESSING
    committed = [s for s in live if s == STATUS_COMMITTED]
    if committed and len(committed) != len(live):
        return SUMMARY_PARTIALLY_COMMITTED
    if committed:
        return SUMMARY_ACTIVE
    return SUMMARY_REVIEW_REQUIRED


def ranges_overlap(
    a_min: date | None, a_max: date | None, b_min: date | None, b_max: date | None
) -> bool:
    """Do two measured-date ranges cover any day in common?

    Used only for the advisory possible-replacement hint. A missing bound
    answers **False**: a workbook still being parsed has no dates, and
    "unknown" must not be read as "overlaps everything" -- that would raise a
    replacement warning against every file in the plant.
    """
    if a_min is None or a_max is None or b_min is None or b_max is None:
        return False
    return a_min <= b_max and b_min <= a_max


def span(values: Iterable[date | None]) -> tuple[date | None, date | None]:
    """The earliest and latest of some dates, ignoring the missing ones."""
    present = sorted(v for v in values if v is not None)
    if not present:
        return (None, None)
    return (present[0], present[-1])


def spans_months(first: date | None, last: date | None) -> bool:
    """True when a measured-date range crosses a calendar month boundary.

    False when either end is unknown: a workbook still parsing has no range,
    and "unknown" is not a cross-month warning.
    """
    if first is None or last is None:
        return False
    return (first.year, first.month) != (last.year, last.month)


# =====================================================================
# T21: the upload inbox
# =====================================================================
INBOX_ALL = "all"
INBOX_CURRENT_MONTH = "current_month"
INBOX_NEEDS_ATTENTION = "needs_attention"
INBOXES: tuple[str, ...] = (INBOX_ALL, INBOX_CURRENT_MONTH, INBOX_NEEDS_ATTENTION)

#: Workflow labels that still want a person (design F4). ACTIVE, SUPERSEDED
#: and ABANDONED are finished, one way or another.
NEEDS_ATTENTION_SUMMARIES = frozenset({
    SUMMARY_PROCESSING, SUMMARY_REVIEW_REQUIRED, SUMMARY_PARTIALLY_COMMITTED,
})


def parse_month(value: str) -> tuple[int, int]:
    """`YYYY-MM` -> `(year, month)`, or ValueError naming the problem."""
    text = (value or "").strip()
    if len(text) != 7 or text[4] != "-" or not (text[:4] + text[5:]).isdigit():
        raise ValueError(f"uploaded_month {value!r} is not YYYY-MM")
    year, month = int(text[:4]), int(text[5:])
    if not 1 <= month <= 12:
        raise ValueError(f"uploaded_month {value!r} has no month {month:02d}")
    return year, month


def utc_month(moment: datetime) -> tuple[int, int]:
    """The UTC calendar month a timestamp falls in.

    A naive timestamp is taken as already UTC -- `timestamptz` never arrives
    naive from the database, so this only matters to a test.
    """
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.year, moment.month


def format_month(month: tuple[int, int]) -> str:
    return f"{month[0]:04d}-{month[1]:02d}"


def select_inbox(
    workbooks: Sequence[Mapping],
    inbox: str,
    month: tuple[int, int],
) -> list[Mapping]:
    """Filter and order a plant's workbook index for one inbox.

    Each entry carries `file_hash`, `uploaded_at` (earliest `started_at`),
    `measured_date_min` and `operational_summary`. The whole plant is
    decided here, on the server, so a client asking for Needs attention gets
    the oldest unfinished work on its first page and never has to walk the
    plant to find it (T21 locked decision 6).

    * `current_month` -- uploaded in `month` (UTC). Workbooks with no
      measured dates yet first, then newest upload first, hash breaking ties.
    * `needs_attention` -- uploaded in any **other** month and still
      PROCESSING, REVIEW_REQUIRED or PARTIALLY_COMMITTED. Oldest upload
      first: the longest-waiting file is the top of the list.

    `all` is not decided here: it keeps T19's SQL membership and ordering
    exactly, and asking this function for it is a programming error.
    """
    if inbox == INBOX_CURRENT_MONTH:
        chosen = [w for w in workbooks if utc_month(w["uploaded_at"]) == month]
        # Stable sorts, least significant key first.
        by_hash = sorted(chosen, key=lambda w: w["file_hash"])
        by_upload = sorted(by_hash, key=lambda w: w["uploaded_at"], reverse=True)
        return sorted(by_upload, key=lambda w: w["measured_date_min"] is not None)
    if inbox == INBOX_NEEDS_ATTENTION:
        chosen = [
            w for w in workbooks
            if utc_month(w["uploaded_at"]) != month
            and w["operational_summary"] in NEEDS_ATTENTION_SUMMARIES
        ]
        return sorted(chosen, key=lambda w: (w["uploaded_at"], w["file_hash"]))
    raise ValueError(f"select_inbox does not decide inbox {inbox!r}")


# =====================================================================
# T21: vehicle sets
# =====================================================================
#: The canonical fields that name a vehicle set on one sheet. Checkzone is
#: deliberately absent: it is a point inside the set, never the card key.
IDENTITY_KEYS: tuple[str, ...] = ("measured_date", "model", "color", "serial_no")

DISPOSITIONS: tuple[str, ...] = ("LOAD", "DUPLICATE", "REJECT", "QUARANTINE")

#: RO11 (D-RO11-2): a Film sheet's limit / label row. It is held out in
#: `/rows` and is never a vehicle.
AGGREGATE_ROW = "AGGREGATE_ROW"


def _present(value) -> str | None:
    """Blank and missing are the same thing for identity. Never invented."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def identity_of(canonical: Mapping | None) -> tuple[str | None, ...]:
    """`(measured_date, model, color, serial_no)` from one projection row.

    Read only from `canonical` -- what the cleaner decided -- and never from
    the raw cells: a colour no alias resolves is not a colour yet. A REJECT
    row's canonical carries no identity at all, and a QUARANTINE row's has
    no model, so those rows fall into an identity-incomplete group rather
    than being attached to a vehicle by guessing.
    """
    canonical = canonical or {}
    return tuple(_present(canonical.get(key)) for key in IDENTITY_KEYS)


#: ADR 0013 decision 8 (T39): the parts a vehicle set needs to be complete.
#: Serial is not one of them -- a colour tab with no serial is one vehicle.
#: Two serials on one tab still split into two sets, because the serial
#: stays in the key.
IDENTITY_REQUIRED: tuple[str, ...] = ("measured_date", "model", "color")


def identity_is_complete(identity: Sequence[str | None]) -> bool:
    """True when date, model and colour are present. Serial may be blank."""
    by_key = dict(zip(IDENTITY_KEYS, identity))
    return all(by_key.get(key) is not None for key in IDENTITY_REQUIRED)


def set_key(disposition: str | None, canonical: Mapping | None) -> tuple | None:
    """The vehicle set a row belongs to, or None for a limit row (RO11).

    The one rule behind both the vehicles read and the inbox card's count
    (D-RO11-2), so they cannot disagree. The key is `identity_of` plus the
    row's `logical_vehicle_id`: a Film car is keyed as History keys it
    (D-RO11-4), so two cars that differ only by Job Number are two sets.
    A Wave Scan row carries no `logical_vehicle_id`; RO16 (D-RO16-5): a car
    of a many-car blank-serial sheet carries its `car_key` there instead, so
    each car is its own set. Without one, the key is unchanged.
    """
    if disposition == AGGREGATE_ROW:
        return None
    canonical = canonical or {}
    return identity_of(canonical) + (
        _present(canonical.get("logical_vehicle_id"))
        or _present(canonical.get("car_key")),
    )


def vehicle_id(load_id: int, identity: Sequence[str | None]) -> str:
    """64-hex SHA-256 of `load_id|measured_date|model|color|serial_no`.

    Missing parts are empty strings. Stable across reads and replays of the
    same sheet, unique per sheet, URL-safe, and derived from nothing but the
    key -- no `source_row`, no counter, no generated serial (T21 locked
    decision 5, design M7).
    """
    parts = [str(load_id)] + [value or "" for value in identity]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def car_labels(cars: Iterable[tuple]) -> dict:
    """D-RO17-17: `(car id, day, first source row)` of each keyed car -> its label.

    `day` is the car's (load, date, model, colour). The ordinal is by first
    source row among that day's cars, e.g. "car 2 of 5 that day - from row 34".
    """
    days: dict = {}
    for car, day, first in cars:
        days.setdefault(day, []).append((first, car))
    labels = {}
    for same_day in days.values():
        same_day.sort(key=lambda item: item[0])
        for n, (first, car) in enumerate(same_day, 1):
            labels[car] = f"car {n} of {len(same_day)} that day \u00b7 from row {first}"
    return labels


@dataclass
class VehicleSet:
    vehicle_id: str
    load_id: int
    measured_date: str | None
    model: str | None
    color: str | None
    serial_no: str | None
    identity_complete: bool
    point_count: int
    expected_point_count: int | None
    incomplete_set: bool
    dispositions: dict[str, int] = field(default_factory=dict)
    source_rows: list[int] = field(default_factory=list)
    #: D-RO17-17: set only for a Wave Scan car with a `car_key`.
    car_label: str | None = None
    #: RO18 (B4): the sheet had no date; the day is not recorded.
    date_is_month_only: bool = False


def group_vehicle_sets(
    load_id: int,
    rows: Iterable[Mapping],
    expected_zones: Mapping[str, int],
    live_points: Mapping[str, frozenset[str]] | None = None,
    film: Callable[[str | None, set[str]], tuple[int, int | None, bool]] | None = None,
) -> list[VehicleSet]:
    """One sheet's rows, folded into vehicle sets, in review order.

    `rows` are that sheet's projection rows (or its facts, for a sheet with
    no projection), each with `source_row`, `disposition` and `canonical`.

    * Two serials never share a set: the serial is part of the key.
    * A blank serial is the sheet's one vehicle (ADR 0013 decision 8): every
      row with no serial for one `(measured_date, model, color)` is one set,
      complete when date, model and colour are present. A missing date,
      model or colour makes `identity_complete` false. Nothing is generated.
    * A DUPLICATE row carries the same identity as the vehicle it repeats,
      so it lands in that same set and is counted as a duplicate there, not
      minted as a second vehicle.
    * T114-FIX: `point_count` / `expected_point_count` are
      `domain.completeness.wavescan_points` -- the live, non-extra points of
      the plant's list for the set's model (`live_points`) and how many of
      them the set has a reading on; with no list, every distinct checkzone
      against `ref_model.expected_zone_count` (`expected_zones`). Null
      expected when the model is missing or unknown. There is no default
      count in this module.
    * RO11: an `AGGREGATE_ROW` (limit row) is no set (`set_key`). For a Film
      sheet the caller passes `film`, which answers `(point_count, expected,
      incomplete)` for a model and its `point_code`s by History's rule; the
      Wave Scan count above is then not used.

    Order: identity-incomplete first, then measured date, model, colour,
    serial, a missing part before a present one.
    """
    groups: dict[tuple[str | None, ...], dict] = {}
    for row in rows:
        canonical = row.get("canonical") or {}
        key = set_key(row.get("disposition"), canonical)
        if key is None:
            continue
        group = groups.setdefault(
            key,
            {"zones": set(), "dispositions": dict.fromkeys(DISPOSITIONS, 0), "rows": []},
        )
        zone = _present(canonical.get("point_code" if film else "checkzone"))
        if zone is not None:
            group["zones"].add(zone)
        disposition = row.get("disposition")
        if disposition in group["dispositions"]:
            group["dispositions"][disposition] += 1
        group["rows"].append(int(row["source_row"]))
        if canonical.get("date_is_month_only"):
            group["month_only"] = True  # RO18 (B4)

    sets: list[VehicleSet] = []
    keyed: list[VehicleSet] = []
    for key, group in groups.items():
        identity, car = key[:4], key[4]
        measured_date, model, color, serial_no = identity
        complete = identity_is_complete(identity)
        if film is not None:
            points, expected, short = film(model, group["zones"])
        else:
            points, expected = wavescan_points(
                group["zones"], model, live_points=live_points, expected_zones=expected_zones
            )
            short = expected is not None and points != expected
        sets.append(VehicleSet(
            # A Film car's id adds its logical_vehicle_id (D-RO11-4).
            vehicle_id=vehicle_id(load_id, identity if car is None else key),
            load_id=load_id,
            measured_date=measured_date,
            model=model,
            color=color,
            serial_no=serial_no,
            identity_complete=complete,
            point_count=points,
            expected_point_count=expected,
            incomplete_set=(not complete) or short,
            dispositions=group["dispositions"],
            source_rows=sorted(group["rows"]),
            date_is_month_only=bool(group.get("month_only")),
        ))
        if film is None and car is not None:
            keyed.append(sets[-1])

    # D-RO17-17: tell same-day cars of a many-car blank-serial sheet apart.
    labels = car_labels(
        (s.vehicle_id, (s.measured_date, s.model, s.color), s.source_rows[0])
        for s in keyed
    )
    for item in keyed:
        item.car_label = labels[item.vehicle_id]

    def order(item: VehicleSet):
        return (
            item.identity_complete,
            *((part is not None, part or "") for part in
              (item.measured_date, item.model, item.color, item.serial_no)),
            # RO17-FIX (D-RO17F-4): same-day cars in car order (first row).
            item.source_rows[0] if item.source_rows else 0,
        )

    return sorted(sets, key=order)


def order_points(
    rows: Iterable[Mapping], walk: Mapping[str, int] | None = None
) -> list[Mapping]:
    """Points of one set: by checkzone, then source row; no zone last.

    RO11: a Film set passes `walk` (`point_code -> point_no` of the plant's
    live list) and is ordered by `point_no`; a code off the list comes after.
    """
    def key(row: Mapping):
        canonical = row.get("canonical") or {}
        if walk is not None:
            code = _present(canonical.get("point_code"))
            rank = walk.get(code) if code is not None else None
            return (rank is None, rank or 0, code or "", int(row["source_row"]))
        zone = _present(canonical.get("checkzone"))
        return (zone is None, zone or "", int(row["source_row"]))

    return sorted(rows, key=key)


__all__ = [
    "AGGREGATE_ROW",
    "DISPOSITIONS",
    "IDENTITY_KEYS",
    "IDENTITY_REQUIRED",
    "identity_is_complete",
    "INBOXES",
    "INBOX_ALL",
    "INBOX_CURRENT_MONTH",
    "INBOX_NEEDS_ATTENTION",
    "NEEDS_ATTENTION_SUMMARIES",
    "RETIRED_STATUSES",
    "SUMMARIES",
    "SUMMARY_ABANDONED",
    "SUMMARY_ACTIVE",
    "SUMMARY_PARTIALLY_COMMITTED",
    "SUMMARY_PROCESSING",
    "SUMMARY_REVIEW_REQUIRED",
    "SUMMARY_SUPERSEDED",
    "VehicleSet",
    "car_labels",
    "format_month",
    "group_vehicle_sets",
    "identity_of",
    "operational_summary",
    "order_points",
    "parse_month",
    "ranges_overlap",
    "select_inbox",
    "set_key",
    "span",
    "spans_months",
    "utc_month",
    "vehicle_id",
]
