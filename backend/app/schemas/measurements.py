"""Measurement list DTOs.

Every field here comes from `v_wavescan_active`, the one view that carries
the active-data predicate (`01-DATA-MODEL.md` sections 5 and 10). The DTO
deliberately exposes `load_id`, `source_sheet` and `source_row`: a quality
number a plant disputes has to be traceable back to the cell it came from.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.schemas.common import MeasureValue, PageInfo, StrictModel


class MeasurementOut(StrictModel):
    measurement_id: int
    measured_date: date
    date_is_month_only: bool = Field(
        default=False,
        description="RO18 (B4): measured_date is the 1st of a named month; the day is not recorded.",
    )
    plant: str
    model: str
    checkzone: str
    color: str
    tolerance_group: str = Field(description="Horizontal or Vertical; a property of the zone.")
    paintline: str | None
    serial_no: str | None

    # T76: only `cf` is never NULL. T39 took `doi` out of the required
    # measures, an approved LW/SW hole is stored NULL (MEASURES_HOLE_APPROVABLE),
    # and du..we were never required -- so the DTO must carry NULL, not 500.
    lw: MeasureValue | None
    sw: MeasureValue | None
    cf: MeasureValue
    doi: MeasureValue | None
    du: MeasureValue | None
    wa: MeasureValue | None
    wb: MeasureValue | None
    wc: MeasureValue | None
    wd: MeasureValue | None
    we: MeasureValue | None
    b: MeasureValue | None

    load_id: int
    source_sheet: str
    source_row: int
    loaded_at: datetime
    corrects_measurement_id: int | None = Field(
        default=None,
        description="Set when this row is a correction of an earlier measurement.",
    )
    correction_reason: str | None = None


class MeasurementFilters(StrictModel):
    """Echo of the filters that produced this page, for cache keys and debugging."""

    plant: str | None
    model: str | None
    color: str | None
    checkzone: str | None
    date_from: date | None
    date_to: date | None
    load_id: int | None = Field(
        default=None,
        description=(
            "The batch these rows were narrowed to, when the caller asked for "
            "one. Still read through v_wavescan_active: a superseded batch "
            "returns an empty page here (T19)."
        ),
    )


class MeasurementPage(StrictModel):
    items: list[MeasurementOut]
    page: PageInfo
    filters: MeasurementFilters
    active_data_source: str = Field(
        default="v_wavescan_active",
        description=(
            "The view these rows were read through. It applies the active-data "
            "predicate -- not a duplicate, not retired, batch accepted -- in "
            "one place (01-DATA-MODEL.md section 10)."
        ),
    )
