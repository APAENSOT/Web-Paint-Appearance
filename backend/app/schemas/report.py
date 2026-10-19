"""Analysis report DTOs (AR03 section 3). Counts and statistics with their n.

``status`` fields carry the overview codes unchanged (PASS, WARNING, FAIL,
OVER, null). No field is a share; no key names a rate, percentage, score or
grade. ``grading_available`` is untouched.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.schemas.common import MeasureValue, StrictModel
from app.schemas.history import MONTH_PATTERN

Domain = Literal["wavescan", "film", "both"]
BoxCode = Literal["PASS", "WARNING", "FAIL", "OVER"]


class ReportOptions(StrictModel):
    months: list[str] = Field(description="Months with counted Wave Scan or active Film readings, newest first.")
    models: list[str] = Field(description="Before the model / colour filter.")
    colors: list[str]


class WavescanBoxCounts(StrictModel):
    PASS: int
    WARNING: int
    FAIL: int
    NONE: int = Field(description="Boxes with no standard (status null).")


class WavescanMonthGlance(StrictModel):
    readings: int = Field(description="Counted readings in the month and filters.")
    cars: int = Field(description="Distinct serial_no.")
    boxes: WavescanBoxCounts
    below_minimum: int = Field(description="Readings listed below their box's Minimum.")


class WavescanGlance(WavescanMonthGlance):
    previous: WavescanMonthGlance | None


class FilmLayerCounts(StrictModel):
    layer: str
    PASS: int
    WARNING: int
    FAIL: int
    OVER: int
    NONE: int = Field(description="Boxes with status null (no standard, or not graded).")


class FilmMonthGlance(StrictModel):
    readings: int = Field(description="Non-null readings in the overview boxes.")
    cars: int = Field(description="The Film overview's vehicle_count.")
    boxes_by_layer: list[FilmLayerCounts]
    out_of_spec: int = Field(description="Readings listed beyond a line.")


class FilmGlance(FilmMonthGlance):
    previous: FilmMonthGlance | None


class ReportGlance(StrictModel):
    wavescan: WavescanGlance | None
    film: FilmGlance | None


class IssuePoint(StrictModel):
    value: MeasureValue
    side: Literal["LOW", "HIGH"] | None = Field(description="Film only; null on Wave Scan (below Minimum).")
    panel: str | None = Field(description="Wave Scan panel group; null on Film.")
    point_code: str | None
    car: str | None = Field(description="Wave Scan serial_no or Film logical_vehicle_id.")
    date: dt.date | None


class ReportIssue(StrictModel):
    domain: Literal["wavescan", "film"]
    layer: str | None
    model: str
    color: str
    orient: Literal["H", "V"]
    status: BoxCode | None
    n: int
    mean: MeasureValue
    median: MeasureValue
    limits: dict[str, MeasureValue] = Field(
        description="The box's own lines by their label (Standard / Minimum; Film lo / hi / target labels)."
    )
    points: list[IssuePoint]


class ReportComparisonRow(StrictModel):
    domain: Literal["wavescan", "film"]
    layer: str | None
    model: str
    color: str
    orient: Literal["H", "V"]
    mean_now: MeasureValue | None
    mean_before: MeasureValue | None
    mean_change: MeasureValue | None
    status_now: BoxCode | None
    status_before: BoxCode | None


class BandBox(StrictModel):
    n: int
    box_min: MeasureValue
    q1: MeasureValue
    median: MeasureValue
    q3: MeasureValue
    box_max: MeasureValue
    whisker_lo: MeasureValue
    whisker_hi: MeasureValue
    outliers: list[MeasureValue]
    mean: MeasureValue
    values: list[MeasureValue] | None = Field(description="Every value, only when n < 5 (drawn as dots).")


class BandRow(StrictModel):
    band: str
    all: BandBox | None
    horizontal: BandBox | None
    vertical: BandBox | None
    previous_month_median: MeasureValue | None


class BandMedians(StrictModel):
    du: MeasureValue | None
    wa: MeasureValue | None
    wb: MeasureValue | None
    wc: MeasureValue | None
    wd: MeasureValue | None
    we: MeasureValue | None
    cf: MeasureValue | None


class PanelGroupRow(StrictModel):
    panel_group: str
    n_readings: int
    median: BandMedians


class BandBlock(StrictModel):
    n_readings: int
    n_cars: int
    bands: list[BandRow] = Field(description="Always 7: du, wa, wb, wc, wd, we, cf.")
    panel_groups: list[PanelGroupRow]


class CorrelationMatrix(StrictModel):
    params: list[str]
    rho: list[list[MeasureValue | None]] = Field(description="Spearman rho; null when n < 3 or a side is constant.")
    n: list[list[int]]


class PairedRow(StrictModel):
    film_layer: str
    ws_param: str
    rho: MeasureValue | None
    n: int = Field(description="Paired car x pair group units.")
    slope: MeasureValue | None = Field(description="OLS slope of the band on thickness; only when among the strongest.")


class PairedBlock(StrictModel):
    cars: int
    rows: list[PairedRow]


class StrongestRelationship(StrictModel):
    a: str
    b: str
    scope: Literal["wavescan", "film", "paired"]
    rho: MeasureValue
    n: int
    slope: MeasureValue | None = Field(description="OLS slope of b on a.")


class ReportRelationships(StrictModel):
    wavescan: CorrelationMatrix | None
    film: CorrelationMatrix | None = Field(description="Unit = car x point.")
    paired: PairedBlock | None = Field(description="Every month; exploratory.")
    strongest: list[StrongestRelationship] = Field(description="|rho| top 5 with n >= 10.")


class AnalysisReportOut(StrictModel):
    plant_code: str
    month: str | None = Field(pattern=MONTH_PATTERN)
    previous_month: str | None = Field(pattern=MONTH_PATTERN)
    domain: Domain
    models: list[str]
    colors: list[str]
    options: ReportOptions
    glance: ReportGlance
    issues: list[ReportIssue] = Field(
        description="Every non-Pass box; FAIL, OVER, WARNING, null, then domain, model, layer, colour, orient."
    )
    comparison: list[ReportComparisonRow]
    bands: BandBlock | None
    relationships: ReportRelationships
    summary: list[str]
