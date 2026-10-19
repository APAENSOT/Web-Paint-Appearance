"""IMG monthly family summary wire contract. All means are decimal strings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import MeasureValue, StrictModel
from app.schemas.history import MONTH_PATTERN

FilmMeasure = Literal["ECOAT", "PRIMER", "BASE", "CLEAR", "CALCULATED_TOTAL"]


class ImgMember(StrictModel):
    model_code: str
    model_name: str


class ImgContribution(StrictModel):
    key: str
    included_count: int


class ImgExclusions(StrictModel):
    SETTING_EXCLUDED: int
    INCOMPLETE_TOTAL: int
    UNKNOWN_ORIENTATION: int
    INVALID_VALUE: int
    DUPLICATE_LAYER: int


class ImgSeries(StrictModel):
    id: str = Field(description="Stable plant|family|metric|orientation|measure aggregate identity.")
    plant_code: Literal["FTM", "FVL", "SAP", "AAT"]
    family_key: str
    family_name: str
    orient: Literal["H", "V"]
    metric: Literal["CF", "FILM"]
    unit: Literal["CF", "micron"]
    film_measure: FilmMeasure | None
    mean: MeasureValue | None
    included_count: int
    count_unit: Literal["CF_READING", "LAYER_READING", "FILM_POINT"]
    availability: Literal["AVAILABLE", "NO_ELIGIBLE_READINGS", "EXCLUDED_OR_INCOMPLETE"]
    member_models: list[ImgMember]
    models: list[ImgContribution]
    colors: list[ImgContribution]
    locations: list[ImgContribution]
    exclusions: ImgExclusions


class ImgMonthsOut(StrictModel):
    months: list[str] = Field(description="Eligible measured YYYY-MM keys, descending.")
    plants: list[str] = Field(description="IMG plants in the caller's scope, FTM/FVL/SAP/AAT order.")
    source: str = "v_wavescan_active + filmthickness_active"


class ImgOverviewOut(StrictModel):
    month: str = Field(pattern=MONTH_PATTERN)
    film_measure: FilmMeasure
    plants: list[str] = Field(description="IMG plants in the caller's scope, FTM/FVL/SAP/AAT order.")
    series: list[ImgSeries]
    source: str = "v_wavescan_active + filmthickness_active"
    aggregation: str = (
        "Pooled eligible CF/layer readings; CALCULATED_TOTAL is the mean of four-layer "
        "sums at complete logical-vehicle/point observations. The dashboard's point "
        "rules apply: Wave Scan reads only v_wavescan_counted points, Film skips points "
        "the latest film_point_setting switches off or the plant retired, and the latest "
        "setting can override Film orientation. Those readings are counted in "
        "SETTING_EXCLUDED. No limits or grades are applied."
    )


class ImgColorSeries(StrictModel):
    """One plant x canonical colour x H/V average CF of IMG Color."""

    id: str = Field(description="Stable plant|colour|CF|orientation|- identity.")
    plant_code: Literal["FTM", "FVL", "SAP", "AAT"]
    color_name: str = Field(description="Canonical (folded) colour name.")
    orient: Literal["H", "V"]
    unit: Literal["CF"]
    mean: MeasureValue | None = Field(
        description="Pooled mean of eligible CF readings; null when none qualify."
    )
    included_count: int
    count_unit: Literal["CF_READING"]
    availability: Literal["AVAILABLE", "NO_ELIGIBLE_READINGS", "EXCLUDED_OR_INCOMPLETE"]
    member_models: list[ImgMember]
    models: list[ImgContribution]
    locations: list[ImgContribution]
    exclusions: ImgExclusions


class ImgColorsOut(StrictModel):
    month: str = Field(pattern=MONTH_PATTERN)
    plants: list[str] = Field(description="IMG plants in the caller's scope, FTM/FVL/SAP/AAT order.")
    series: list[ImgColorSeries] = Field(
        description=(
            "H series then V series, each ranked by mean descending (ties: plant "
            "FTM/FVL/SAP/AAT, then colour); series without a mean last."
        )
    )
    source: str = "v_wavescan_counted"
    aggregation: str = (
        "Average CF per plant x colour, pooling eligible WaveScan CF readings across "
        "models, separately for Horizontal and Vertical. Same point rules as Overview "
        "IMG: only v_wavescan_counted points contribute; excluded or invalid readings "
        "are disclosed in exclusions. Ranked highest first. No limits or grades."
    )
