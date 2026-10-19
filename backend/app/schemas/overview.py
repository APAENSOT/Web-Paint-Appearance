"""Monthly Overview DTOs: one graded box per model × colour × orientation.

The grain is the plant month mean, not a product pass-rate. D1 stays open:
there is no ribbon, no pass_rate, and grading_available is not set true.
Schema names must not start with Dashboard or Preview (T03 bans those).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from app.schemas.common import MeasureValue, StrictModel
from app.schemas.history import MONTH_PATTERN

Orient = Literal["Horizontal", "Vertical"]
BoxStatus = Literal["PASS", "WARNING", "FAIL"]

#: T114 (D-114-12): the dashboard reads the counted readings.
COUNTED_DATA_SOURCE = "v_wavescan_counted"

_ACTIVE_NOTE = Field(
    default=COUNTED_DATA_SOURCE,
    description=(
        "The view these numbers were read through: v_wavescan_active narrowed "
        "to readings whose point is live and counted (T114). Quartiles, the "
        "mean and status cover every matching counted row — there is no "
        "point cap."
    ),
)


class OverviewColorOption(StrictModel):
    color_name: str
    family_code: str | None = None


class WavescanBelowMinimumReading(StrictModel):
    """One reading of a box below that box's own Minimum (T73 D-73-01).

    Listed, never graded on its own: the box status is still the mean's.
    """

    measurement_id: int = Field(
        description="The reading's own v_wavescan_active.measurement_id (identity)."
    )
    measured_date: date | None = Field(
        description="Date the reading was measured, from its own row."
    )
    checkzone: str | None = Field(
        description="The reading's own canonical checkzone (point / zone label)."
    )
    cf: MeasureValue = Field(description="The reading's own CF, exact and unrounded.")


class OverviewBox(StrictModel):
    model_code: str
    color_name: str
    family_code: str | None = None
    orient: Orient
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
    ford: MeasureValue | None = None
    minimum: MeasureValue | None = None
    status: BoxStatus | None = None
    below_minimum: list[WavescanBelowMinimumReading] = Field(
        description=(
            "Every reading of this box with cf < minimum (the box's own "
            "standard; equal to Minimum is not listed, between Minimum and "
            "Standard is not listed). Empty when the box has no standard. "
            "Duplicates are kept. Ordered cf ascending, then measured_date, "
            "checkzone, measurement_id. Independent of outliers and status."
        )
    )


class WavescanOverviewOut(StrictModel):
    plant_code: str
    plant_is_active: bool
    month: str = Field(pattern=MONTH_PATTERN)
    models: list[str] = Field(
        description="Selected model_code values. Empty means every measured model."
    )
    colors: list[str] = Field(
        description="Selected colour names. Empty means every offered colour."
    )
    available_months: list[str]
    model_options: list[str]
    color_options: list[OverviewColorOption]
    boxes: list[OverviewBox]
    active_data_source: str = _ACTIVE_NOTE
