"""Wave Scan <-> Film pairing readiness DTOs (AR01). Counts only: no field is
a percentage, rate, score, status or grade (D-AR01-6)."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from app.schemas.common import StrictModel


class CarRuleOut(StrictModel):
    pattern: str = Field(description="Regex; its first capture group is the car number in job_no.")
    note: str


class ModelColourCount(StrictModel):
    model: str
    color: str
    wavescan_cars: int
    film_cars: int = Field(description="Distinct film car numbers the rule reads.")
    paired_cars: int = Field(
        description="Cars both domains measured as this model x colour. A mismatched pair "
        "counts in the total and under quality, not here."
    )


class PairGroupCount(StrictModel):
    pair_group: str
    wavescan_zones: list[str]
    film_points: int = Field(description="Distinct mapped film point codes in the group.")
    paired_cars: int = Field(
        description="Cars with >=1 Wave Scan reading on a mapped zone and >=1 film reading "
        "on a mapped point of this group (any layer)."
    )


class PairOut(StrictModel):
    car_no: str
    wavescan_model: str
    film_model: str
    wavescan_color: str
    film_color: str
    wavescan_dates: list[date]
    film_dates: list[date]
    gap_days: int = Field(ge=0, description="Smallest |WS date - film date| of this car.")
    flags: list[str] = Field(description="model_mismatch, colour_mismatch; empty when both agree.")


class QualityItem(StrictModel):
    kind: str
    count: int = Field(ge=0)
    examples: list[str] = Field(max_length=5)


class PairingReadinessOut(StrictModel):
    plant_code: str
    car_rule: CarRuleOut | None = Field(
        description="Null: this plant has no film car-number rule, so nothing is paired."
    )
    wavescan_cars: int = Field(description="Distinct serial_no at the plant (active readings).")
    film_cars: int = Field(description="Distinct car numbers the rule reads (active readings).")
    paired_cars: int
    by_model_colour: list[ModelColourCount]
    by_pair_group: list[PairGroupCount]
    pairs: list[PairOut]
    quality: list[QualityItem] = Field(description="Every kind, always; count may be 0.")
