"""FilmThickness monthly overview DTOs (T66, T67): boxplots, lines, box status.

One box per layer x model x colour x orientation, every active Film car of
the month pooled. Each box carries the lines of the latest ``film_standard``
rule that applies (D-66-05).

T67: ``status`` is graded by the backend on the **box mean** (D-67-01); a
client must not grade a box or a point itself. ``out_of_spec`` lists the
individual readings beyond a line. There is still no count by status and no
pass rate; D1 is open and ``grading_available`` is unchanged.
Schema names must not start with Dashboard or Preview (T03 bans those).
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import Field

from app.schemas.common import MeasureValue, StrictModel
from app.schemas.filmthickness import ACTIVE_DATA_SOURCE, Orientation
from app.schemas.history import MONTH_PATTERN

FilmLayer = Literal["ECOAT", "PRIMER", "BASE", "CLEAR"]
StandardScope = Literal["COLOR", "PLANT", "NONE"]
OutOfSpecSide = Literal["LOW", "HIGH"]
Ladder = Literal["BASE", "NO_BASE_STANDARD"]


class FilmBoxStatus(str, Enum):
    """Box status from the box mean (T67-CONTEXT table). WARNING is Clear
    only; OVER only where a Maximum exists (E-coat AAT, Primer, Base)."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    OVER = "OVER"


STANDARDS_NOTE = (
    "Spec lines are the latest published standard; they apply to every month."
)


class FilmColorOption(StrictModel):
    """A colour with Film facts this month and this plant's family (ADR 0010)."""

    color_name: str = Field(description="Folded colour name (ADR 0014).")
    family_code: str | None = None
    family_name: str | None = None
    family_order: int | None = Field(
        default=None, description="ref_color_family.display_order; null = no family."
    )


class FilmColorSequenceEntry(StrictModel):
    """One colour's slot in the response's Base-ladder sequence (T73).

    One sequence per response, shared by every layer (E-coat, Primer, Base,
    Clear), every model and both orientations, at every plant. Sorted
    ascending by: Base H lo, Base H hi, Base V lo, Base V hi (each null after
    any number), family_order (null last), color_name. Horizontal is primary;
    Vertical only breaks ties, and the colour has one rank for both
    orientations. A partial range sorts its missing end after any present
    value. No Base rule for H sorts after every colour with one; no Base rule
    at all sorts after every laddered colour, by family order then name. The
    Base values are the current published rule (latest-wins); the month
    never changes them.
    """

    rank: int = Field(description="1-based, dense and unique within the response.")
    color_name: str = Field(description="Folded colour name (ADR 0014).")
    family_code: str | None = Field(description="This plant's family code (ADR 0010).")
    family_name: str | None = Field(description="This plant's family name.")
    family_order: int | None = Field(
        description="ref_color_family.display_order; null sorts last."
    )
    base_lo_h: MeasureValue | None = Field(description="Base Horizontal lo the key used.")
    base_hi_h: MeasureValue | None = Field(description="Base Horizontal hi the key used.")
    base_lo_v: MeasureValue | None = Field(description="Base Vertical lo the key used.")
    base_hi_v: MeasureValue | None = Field(description="Base Vertical hi the key used.")
    ladder: Ladder = Field(
        description="BASE if any of the four Base values is present, else NO_BASE_STANDARD."
    )


class FilmOutOfSpecPoint(StrictModel):
    """One reading beyond a line. Listed, never graded on its own (D-67-04)."""

    value: MeasureValue
    side: OutOfSpecSide = Field(
        description="LOW: below lo (Minimum / No point below). HIGH: above hi (Maximum)."
    )
    point_code: str
    logical_vehicle_id: str
    measured_date: date | None = Field(
        description=(
            "Date the reading was measured, from its own fact row. Null only "
            "if that fact has no measured_date."
        )
    )


class FilmOverviewBox(StrictModel):
    """Every non-null reading of one layer x model x colour x H/V group."""

    layer_code: FilmLayer
    model_code: str
    color_name: str = Field(description="Folded colour name (ADR 0014).")
    orient: Orientation = Field(
        description=(
            "Hor / Ver of the gold point: this plant's list "
            "(ref_plant_film_point), else the model catalogue "
            "(ref_model_film_point). A box pools every point of it."
        )
    )
    n: int = Field(description="Non-null readings in the box. Nulls are not zero.")
    vehicles: int = Field(description="Distinct logical_vehicle_id contributing.")
    box_min: MeasureValue
    q1: MeasureValue
    median: MeasureValue
    q3: MeasureValue
    box_max: MeasureValue
    whisker_lo: MeasureValue
    whisker_hi: MeasureValue
    outliers: list[MeasureValue]
    mean: MeasureValue
    lo: MeasureValue | None = Field(description="Spec floor, or null.")
    hi: MeasureValue | None = Field(description="Spec ceiling, or null.")
    target: MeasureValue | None = Field(description="Clear target, or null.")
    standard_scope: StandardScope = Field(
        description=(
            "COLOR: a per-colour rule applies. PLANT: the plant-wide rule. "
            "NONE: no rule; the three lines are null and the box is still here."
        )
    )
    status: FilmBoxStatus | None = Field(
        description=(
            "Status is graded on the box mean; out_of_spec lists individual "
            "readings. Clear: mean < lo FAIL, lo <= mean < target WARNING, "
            "else PASS, never OVER. Other layers: mean < lo FAIL, mean > hi "
            "OVER, else PASS. Edges are inside. Null when NONE or Clear has no target."
        )
    )
    family_code: str | None = Field(description="This plant's family code (ADR 0010).")
    family_name: str | None = Field(description="This plant's family name.")
    family_order: int | None = Field(
        description="ref_color_family.display_order; null sorts last."
    )
    color_rank: int = Field(
        description=(
            "This colour's rank in color_sequence. Boxes sort layer, model, "
            "H before V, then color_rank."
        )
    )
    lo_label: str | None = Field(
        description="'Minimum'; on Clear 'No point below'. Null when lo is null."
    )
    hi_label: str | None = Field(
        description="'Maximum'. Always null on Clear (no Maximum). Null when hi is null."
    )
    target_label: str | None = Field(
        description="'Minimum requirement' on Clear. Null when target is null."
    )
    out_of_spec: list[FilmOutOfSpecPoint] = Field(
        description=(
            "Every reading < lo (LOW) or > hi (HIGH, only where a Maximum "
            "exists; never on Clear). Edges are inside. LOW first, then value. "
            "Empty for NONE. Independent of outliers and of status."
        )
    )


class FilmOverviewOut(StrictModel):
    plant_code: str
    month: str | None = Field(
        pattern=MONTH_PATTERN,
        description=(
            "The month used, YYYY-MM: the query, else the latest Film month. "
            "Null only when no month was asked for and the plant has no Film facts."
        ),
    )
    available_months: list[str] = Field(
        description="Months with active Film facts at this plant, newest first."
    )
    model_options: list[str] = Field(description="Models with Film facts this month.")
    color_options: list[FilmColorOption] = Field(
        description=(
            "Folded colours with Film facts this month, with this plant's family; "
            "family order (null last), then name."
        )
    )
    models: list[str] = Field(description="Model filter applied. Empty = all.")
    colors: list[str] = Field(
        description=(
            "Colour filter applied, canonical names. Empty = all. A merged old "
            "name matches nothing (ADR 0014)."
        )
    )
    vehicle_count: int = Field(description="Distinct logical_vehicle_id in scope.")
    color_sequence: list[FilmColorSequenceEntry] = Field(
        description=(
            "One Base-ladder colour order for the whole response, one entry per "
            "colour in boxes, in rank order. The same order applies to every "
            "layer, model and orientation."
        )
    )
    boxes: list[FilmOverviewBox]
    standards_note: str = STANDARDS_NOTE
    active_data_source: str = ACTIVE_DATA_SOURCE
