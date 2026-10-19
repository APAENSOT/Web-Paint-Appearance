"""Measurement History DTOs: facets, week summaries, vehicle sets, points.

Separate from `schemas/workbooks.py` on purpose (T23 locked decision 8).
A review vehicle carries a `disposition`, `raw` against `proposed`, and
`current_overrides`, because it describes a **proposal**. A History vehicle
describes **active facts**: there is no disposition to show, nothing is
proposed any more, and every point carries the `measurement_id` a T09
correction needs.

Three absences are part of the contract:

* **No grade, pass rate or band.** D1 is open, and nothing here is derived
  from a measurement value.
* **No week resource.** `week` is a field on a summary, computed from the
  day of `measured_date` (`02-PIPELINE.md` section 8.1). T21's Upload Data
  weeks stay the client's, from `uploaded_at`.
* **No mutation.** Every shape here is a read of something already
  committed; editing a point is the existing T09 correction POST.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import MeasureValue, PageInfo, StrictModel

#: The view every History statement reads through, echoed on each payload so
#: a client can see which predicate produced the numbers.
ACTIVE_DATA_SOURCE = "v_wavescan_active"

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
VEHICLE_ID_PATTERN = r"^[0-9a-f]{64}$"

#: RO18 (B4): 0 is the "day not recorded" group -- cars of a sheet with no
#: date, filed on the 1st of the month a person named. Never week 1.
Week = Literal[0, 1, 2, 3, 4, 5]

_ACTIVE_NOTE = Field(
    default=ACTIVE_DATA_SOURCE,
    description=(
        "The view these numbers were read through. It applies the "
        "active-data predicate -- not a duplicate, not retired, batch "
        "committed -- in one place (01-DATA-MODEL.md section 10). Superseded "
        "facts and abandoned reviews are absent by construction."
    ),
)


class HistoryFacetsOut(StrictModel):
    """The cascading pick lists for Month -> Model -> Colour (design F14).

    They are API fields because the alternative is the client downloading
    every active row to fold its own lists.
    """

    plant_code: str
    plant_is_active: bool = Field(
        description=(
            "False for a known plant this platform has not onboarded (FVL, "
            "D5). Its History is an empty set of months rather than an error."
        )
    )
    default_month: str | None = Field(
        description=(
            "The latest month with at least one active row for this plant, "
            "YYYY-MM, or null when the plant has none."
        )
    )
    months: list[str] = Field(
        description="Months of measured_date that have active rows, newest first."
    )
    month: str | None = Field(description="Echo of the query, or null.")
    models: list[str] = Field(
        description=(
            "Models present in the selected month, sorted. Empty when no "
            "month was given: there is nothing to cascade from."
        )
    )
    model: str | None
    colors: list[str] = Field(
        description=(
            "Colours present in the selected month, narrowed to the selected "
            "model when one was given. Empty when no month was given."
        )
    )
    color: str | None
    active_data_source: str = _ACTIVE_NOTE


class HistoryCardOut(StrictModel):
    """One model + colour card inside a week (design F13)."""

    model: str | None
    color: str | None
    vehicle_count: int = Field(
        description=(
            "Distinct vehicle sets, not distinct serials: two sheets that "
            "measured the same serial on the same day are two vehicles."
        )
    )
    point_count: int = Field(
        description=(
            "Active measurement rows. Summing a month's cards gives the same "
            "number as GET /measurements page.total for the same plant, "
            "month, model and colour."
        )
    )
    measured_date_min: date
    measured_date_max: date


class HistoryWeekOut(StrictModel):
    week: Week = Field(
        description=(
            "Day bands of measured_date: 1 = days 1-7, 2 = 8-14, 3 = 15-21, "
            "4 = 22-28, 5 = 29 to the end of that month. 0 = day not recorded "
            "(RO18: a sheet with no date, filed under the month a person named)."
        )
    )
    measured_date_min: date
    measured_date_max: date
    cards: list[HistoryCardOut]


class HistorySummariesOut(StrictModel):
    plant_code: str
    plant_is_active: bool
    month: str
    model: str | None
    color: str | None
    weeks: list[HistoryWeekOut] = Field(
        description=(
            "Weeks descending, weeks with no matching rows omitted. An empty "
            "list is an empty state, not a zero KPI."
        )
    )
    active_data_source: str = _ACTIVE_NOTE


class HistoryVehicleSetOut(StrictModel):
    """One vehicle set of active facts, on one committed sheet."""

    vehicle_id: str = Field(
        description=(
            "The T21 id: 64-hex SHA-256 of UTF-8 "
            "'{load_id}|{measured_date ISO or empty}|{model or empty}|"
            "{color or empty}|{serial_no or empty}'. load_id is inside the "
            "hash, so two sheets that measured the same serial on the same "
            "day are two vehicles."
        )
    )
    load_id: int
    plant_code: str
    measured_date: date
    model: str | None
    color: str | None
    serial_no: str | None
    identity_complete: bool = Field(
        description=(
            "False when any of measured_date, model, color or serial_no is "
            "missing. Such a group is not a vehicle: no serial is generated "
            "and source_row is never the card id (design M7)."
        )
    )
    point_count: int = Field(
        description=(
            "How many of the expected_point_count points this set has a "
            "reading on (T114-FIX). A reading on a retired point, an extra "
            "point or a code off the list counts neither way; with no list, "
            "every distinct checkzone counts."
        )
    )
    expected_point_count: int | None = Field(
        description=(
            "The live, non-extra points of this plant's Wave Scan list for "
            "this model (ref_model.expected_zone_count when the plant has "
            "no list for it; T114-FIX). Null when the model is unknown: "
            "expected not available."
        )
    )
    incomplete_set: bool = Field(
        description=(
            "True when identity_complete is false, or expected_point_count "
            "is known and point_count differs from it."
        )
    )
    source_file: str | None = Field(
        description=(
            "The workbook these facts came from. Provenance shown on the "
            "vehicle, never the card identity (design section 8.3)."
        )
    )
    source_sheet: str | None
    week: Week
    car_label: str | None = Field(
        default=None,
        description=(
            "D-RO17-17: set only for a Wave Scan car with a car_key (a "
            "many-car blank-serial sheet), e.g. 'car 2 of 5 that day - from "
            "row 34'. The ordinal is by the car's first source row among the "
            "cars of its (load, date, model, colour). Null otherwise."
        ),
    )
    date_is_month_only: bool = Field(
        default=False,
        description=(
            "RO18 (B4): the sheet had no date. measured_date is the 1st of "
            "the month a person named; show '<Month YYYY> - day not "
            "recorded', never the day. Such cars never pair."
        ),
    )


class HistoryVehiclePage(StrictModel):
    items: list[HistoryVehicleSetOut]
    page: PageInfo
    plant_code: str
    plant_is_active: bool
    month: str
    week: Week
    model: str
    color: str
    active_data_source: str = _ACTIVE_NOTE


class HistoryPointOut(StrictModel):
    """One active measurement of a vehicle set.

    `measurement_id` is required: editing a point is the existing T09
    correction POST against this id, never the T21 review override.
    """

    measurement_id: int
    load_id: int
    source_sheet: str
    source_row: int
    source_file: str | None
    checkzone: str = Field(
        description=(
            "Stored zone_code. Identity for grading and grids. Since T58 a new "
            "load stores that plant x model's own gold name (FVL `11ROOF`, SAP "
            "`01RHS Hood Rr28`); AAT/FTM long-form may store `RRHOOD`. Earlier "
            "facts keep what they stored."
        )
    )
    panel_label: str = Field(
        description=(
            "The panel to show people. T94 (D-94-4): this is the stored "
            "position -- the long name -- so a rough spelling is never "
            "displayed as a position. A reading the file called `01HOOD` "
            "and a person confirmed as RRHOOD reads `RRHOOD` here. Before "
            "T94 this was src_zone_text (T53, D-53-09); the file's own words "
            "are now carried beside it as src_zone_text instead, so nothing "
            "is lost. Equals checkzone by construction."
        )
    )
    src_zone_text: str | None = Field(
        description=(
            "T94 (D-94-4): the panel exactly as the plant wrote it in the "
            "file (`01HOOD`, `01 RRHOOD`, `06LFFENDER`), for provenance -- "
            "show it beside the position, never as the position. Null for a "
            "fact stored without source text."
        )
    )
    measured_date: date
    model: str
    color: str
    serial_no: str | None
    tolerance_group: str = Field(
        description="Horizontal or Vertical; a property of the zone."
    )
    date_is_month_only: bool = Field(
        default=False,
        description="RO18 (B4): measured_date is the 1st of a named month; the day is not recorded.",
    )
    paintline: str | None

    # T96: every measure is nullable, because `wavescan` allows it and the
    # owner's real August file uses it -- 320 of its readings carry no DoI.
    # This read required all ten, so one such reading made the whole
    # vehicle's History a 500 (`decimal_type`, input None). `MeasurementOut`
    # has always been nullable here; the screen already shows "Not
    # recorded". Measured on `08 Aug2026 CF data FTM.xlsx`, 2026-10-10.
    lw: MeasureValue | None
    sw: MeasureValue | None
    cf: MeasureValue | None
    doi: MeasureValue | None
    du: MeasureValue | None
    wa: MeasureValue | None
    wb: MeasureValue | None
    wc: MeasureValue | None
    wd: MeasureValue | None
    we: MeasureValue | None
    b: MeasureValue | None

    loaded_at: datetime
    corrects_measurement_id: int | None = Field(
        default=None,
        description="Set when this row is a correction of an earlier measurement.",
    )
    correction_reason: str | None = None
    # T114 (D-114-3, D-114-4, D-114-5): what Point Check says about this
    # reading's point at this plant x model. Tags only: History keeps every
    # reading whatever they say.
    retired: bool = Field(
        default=False,
        description=(
            "T114: the point was retired on this plant's list. The reading "
            "stays here; it no longer feeds the dashboard."
        ),
    )
    counted: bool = Field(
        default=True,
        description=(
            "T114: the point's latest ws_point_setting.counted (no row = "
            "counted). False: the reading stays here and leaves the dashboard."
        ),
    )
    is_extra: bool = Field(
        default=False,
        description="T114: the point is beyond the plant's standard list (D-114-5).",
    )


class HistoryPointPage(StrictModel):
    items: list[HistoryPointOut]
    page: PageInfo
    vehicle: HistoryVehicleSetOut = Field(
        description=(
            "The parent set, so a client can show 'N of expected' without "
            "computing anything."
        )
    )
    plant_code: str
    active_data_source: str = _ACTIVE_NOTE


__all__ = [
    "ACTIVE_DATA_SOURCE",
    "HistoryCardOut",
    "HistoryFacetsOut",
    "HistoryPointOut",
    "HistoryPointPage",
    "HistorySummariesOut",
    "HistoryVehiclePage",
    "HistoryVehicleSetOut",
    "HistoryWeekOut",
    "MONTH_PATTERN",
    "VEHICLE_ID_PATTERN",
    "Week",
]
