"""Read-only monthly vehicle profiles and exact per-point sample inspection."""
from datetime import date
from typing import Literal
from pydantic import Field
from app.schemas.common import MeasureValue, StrictModel
from app.schemas.comparison import ComparisonMetric, ComparisonReading, ComparisonUngradedStats
from app.schemas.point_profiles import Domain


class MonthlyProfile(StrictModel):
    profile_id: str = Field(description='Stable identity of plant, domain, exact model and exact colour; independent of month.')
    domain: Domain
    model_code: str
    color_name: str
    family_name: str | None
    is_offered: bool = Field(description='Both model and canonical colour currently offered here. A combination does not assert this colour is manufactured on this model.')
    sample_count: int = Field(ge=0, description='All active History vehicle sets (Wave Scan) or logical vehicles (Film) in the selected measured month. No cap; not reading count.')


class MonthlyProfilesOut(StrictModel):
    plant_code: str
    domain: Domain
    month: str | None
    available_months: list[str]
    items: list[MonthlyProfile] = Field(description='Current plant Standard model × colour combinations, plus observed historical combinations. Empty combinations remain explicit.')


class MonthlySample(StrictModel):
    vehicle_id: str
    measured_date: date
    serial_no: str | None
    car_label: str | None = Field(default=None, description='Existing same-day History car label where stored; never a fabricated serial.')
    job_nos: list[str] | None = None
    readings: list[ComparisonReading] = Field(description='Every nonnull active reading at the exact selected canonical point and metric. Missing samples have []. Film preserves existing earliest whole-point selection.')


class MonthlyPointBox(ComparisonUngradedStats):
    box_min: MeasureValue = Field(description='Minimum selected-metric reading at this exact point across all matching monthly samples.')
    box_max: MeasureValue = Field(description='Maximum selected-metric reading at this exact point across all matching monthly samples.')
    mean: MeasureValue = Field(description='Backend Decimal arithmetic mean of every nonnull selected-metric reading at this point in this month/model/colour; not a mean of vehicle means.')


class MonthlyReferenceLine(StrictModel):
    label: str
    value: MeasureValue
    kind: Literal['standard', 'minimum', 'maximum', 'target']


class MonthlyPointsOut(StrictModel):
    plant_code: str
    domain: Domain
    month: str
    model_code: str
    color_name: str
    metric: ComparisonMetric
    unit: Literal['µm', 'index']
    point_key: str
    orientation: Literal['H', 'V'] | None = Field(description='Current Point Check orientation; never inferred from the point name.')
    standard_scope: Literal['COLOR','FAMILY','PLANT','NONE']
    reference_lines: list[MonthlyReferenceLine] = Field(description='Latest applicable backend Standard lines, using the same precedence and labels as Monthly Overview. CF only for Wave Scan; Film selected layer/orientation. Status uses these current lines against the point mean; these are not historical standard snapshots.')
    sample_count: int
    checked_sample_count: int = Field(description='Distinct samples with at least one nonnull selected metric at this point.')
    reading_count: int = Field(description='Full nonnull reading count; duplicates of a checkzone remain separate source measurements, zero contributes.')
    box: MonthlyPointBox | None = Field(description='Existing backend Decimal box_stats over all selected point readings. Null for an empty sample.')
    status: Literal['PASS', 'WARNING', 'FAIL', 'OVER'] | None = Field(
        description='Status of this point box mean under the same current Standard rule as Monthly Overview. Null without readings or an applicable Standard.'
    )
    samples: list[MonthlySample] = Field(description='Every matching sample, ordered by measured_date then existing car order then ID. Same-day sample order is not a measurement timestamp.')
    unaligned_reading_count: int = Field(description='Nonnull selected-metric rows outside the current live point list, kept out of this point plot; no guessed mapping.')
    active_data_source: Literal['v_wavescan_active', 'filmthickness_active']


class MonthlyPointStatus(StrictModel):
    point_key: str
    mean: MeasureValue | None = Field(description='Mean of every nonnull selected-metric reading at this point. Null when no reading exists.')
    reading_count: int = Field(ge=0)
    status: Literal['PASS', 'WARNING', 'FAIL', 'OVER'] | None = Field(
        description='Status of the point mean under the same current Standard rule as Monthly Overview. Null without readings or an applicable Standard.'
    )


class MonthlyPointStatusesOut(StrictModel):
    plant_code: str
    domain: Domain
    month: str
    model_code: str
    color_name: str
    metric: ComparisonMetric
    unit: Literal['µm', 'index']
    items: list[MonthlyPointStatus] = Field(
        description='Every live Standard point in walk order. Values are grouped by exact point identity; no client grading or guessed mapping.'
    )
    active_data_source: Literal['v_wavescan_active', 'filmthickness_active']
