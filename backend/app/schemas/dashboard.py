"""Dashboard preview DTOs -- raw CF only.

**D1 is open.** Nobody has decided whether the product pass rate groups by
checkzone, by colour x orientation, or by both (`docs/DEFERRED.md`). So this
endpoint returns measured CF values and the dimensions they carry, and
nothing else:

* no PASS / WARN / FAIL,
* no pass rate,
* no mean, median, min, max or count per series.

A mean CF per checkzone is not a neutral convenience -- it asserts that
checkzone is the grouping key, which is precisely the open question. The
`dimension` parameter only says how to *draw* the points; it is a display
choice the caller makes, and the payload says so.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from app.schemas.common import MeasureValue, StrictModel
from app.schemas.measurements import MeasurementFilters

PreviewDimension = Literal["checkzone", "color"]


class PreviewPoint(StrictModel):
    measurement_id: int
    measured_date: date
    plant: str
    model: str
    color: str
    checkzone: str
    tolerance_group: str
    cf: MeasureValue


class PreviewSeries(StrictModel):
    key: str = Field(description="The value of the chosen dimension, e.g. 'RRHOOD'.")
    points: list[PreviewPoint]


class DashboardPreview(StrictModel):
    dimension: PreviewDimension
    series: list[PreviewSeries]
    filters: MeasurementFilters
    point_limit: int
    truncated: bool = Field(
        description="True when more active rows matched than point_limit allowed."
    )
    active_data_source: str = "v_wavescan_active"
    grading_available: Literal[False] = Field(
        default=False,
        description=(
            "No grade, pass rate or status is returned. D1 (grouping key) and "
            "D2 (colour -> family) are open and grading is T05; a client that "
            "computes one locally is inventing an answer the platform has not "
            "made (AGENTS.md section 4)."
        ),
    )
    grading_note: str = Field(
        default=(
            "Raw CF only. Grouping is a display choice, not a grading key: D1 "
            "is unresolved."
        )
    )
