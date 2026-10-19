"""Landing status wire contract: plant cards, feed sidebar, plant preview."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StrictModel


class LandingQualityGroup(StrictModel):
    group: Literal["WAVESCAN_H", "WAVESCAN_V", "FILM_H", "FILM_V"]
    graded: int = Field(description="Dashboard boxes with a status this month.")
    passed: int = Field(description="Of those, boxes the dashboard marks PASS.")


class LandingQuality(StrictModel):
    pct: float | None = Field(
        description=(
            "Mean of the groups' PASS share (graded groups only), 0-100; null when no "
            "box is graded this month. Statuses are the dashboards' own."
        )
    )
    groups: list[LandingQualityGroup]


class LandingFeed(StrictModel):
    level: Literal["UPDATE", "LATE", "MISSING"]
    pct: float = Field(
        description="Share of the plan (offered model x colour, once per week so far) on file."
    )
    week: int = Field(description="Current measured-date week band, 1-5.")
    late_weeks: int
    missing_weeks: int
    colours_this_week: int
    colours: int = Field(description="Offered colours at the plant.")
    models: int = Field(description="Offered models at the plant.")


class LandingFile(StrictModel):
    load_id: int
    source_file: str
    file_hash: str
    status: str
    domain: str | None
    started_at: datetime


class LandingPlant(StrictModel):
    plant_code: Literal["FTM", "FVL", "SAP", "AAT"]
    quality: LandingQuality
    feed: LandingFeed | None = Field(description="Null when the plant offers no model or colour.")
    wavescan_cars: int = Field(description="Distinct Wave Scan serials on file (active).")
    film_cars: int = Field(description="Distinct Film car numbers on file (active).")
    latest_files: list[LandingFile] = Field(description="Newest four uploaded workbooks.")


class LandingStatusOut(StrictModel):
    as_of: datetime
    month: str = Field(description="The current calendar month, YYYY-MM.")
    plants: list[LandingPlant]
    rules: str = (
        "Quality: PASS share of the plant dashboards' graded boxes per Wave Scan H/V and "
        "Film H/V, averaged. Feed: every offered model x colour once per measured-date "
        "week band; a past week with nothing on file is MISSING, one that arrived after "
        "the week ended or left a colour out is LATE, otherwise UPDATE. The current "
        "week never counts against the plant."
    )
