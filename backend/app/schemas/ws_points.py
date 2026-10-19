"""T114: Point Check, Wave Scan -- the list, counted, add, retire."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import StrictModel


class WsPointModelOut(StrictModel):
    """One Wave Scan model this plant has a live point list for."""

    model_code: str
    display_name: str | None
    point_count: int = Field(ge=1, description="Live points on this plant's list.")
    counted_count: int = Field(
        ge=0, description="Live points the dashboard counts (latest setting, no row = counted)."
    )
    extra_count: int = Field(
        ge=0, description="Live points tagged extra (D-114-5): beyond the standard list."
    )


class WsPointModelsOut(StrictModel):
    plant_code: str
    items: list[WsPointModelOut] = Field(
        description="Models with a live Wave Scan list at this plant, by model_code."
    )
    offered_without_list: list[str] = Field(
        description=(
            "RO17 (D-RO17-10): Wave Scan models this plant offers that have "
            "no live list yet. Their list reads as empty, and an Engineer may "
            "add its first point."
        )
    )


class WsPointItem(StrictModel):
    """One live point of a plant x model Wave Scan list."""

    point_no: int = Field(ge=1, description="ref_plant_ws_point.point_no: walk order.")
    zone_code: str = Field(description="The point's identity, the plant's own panel text.")
    label: str = Field(
        description=(
            "RO17 (D-RO17-1): the point's current label, the word its plant "
            "uses (newest label row; the code where none). Show it first, "
            "the code second."
        )
    )
    tolerance_group: str = Field(
        description=(
            "Horizontal or Vertical, fixed by the name (ck_zone_rule: Hood, "
            "Roof or Floor in it is Horizontal). Shown, never edited."
        )
    )
    counted: bool = Field(
        description=(
            "Latest ws_point_setting.counted; true where none exists. False "
            "takes its readings off the dashboard for every month; History and "
            "Comparison keep them, tagged."
        )
    )
    is_extra: bool = Field(
        description=(
            "T114 (D-114-5): beyond the plant's standard list. Every point "
            "added on Point Check. A tag, not a grade."
        )
    )
    note: str | None = Field(description="Where the row came from (T58 lock, a Point Check add).")
    created_at: datetime
    reason: str | None = Field(description="Why the latest setting row says what it says.")
    changed_by: str | None = Field(
        description=(
            "T115 (D-115-1): app_user.display_name of who wrote it; null "
            "where no setting row exists, \"-\" for a user with no name."
        )
    )
    changed_at: datetime | None = Field(description="When. Null where no setting row exists.")


class WsRetiredPointItem(StrictModel):
    """One point this plant's list used to walk."""

    point_no: int = Field(ge=1)
    zone_code: str
    label: str = Field(
        description=(
            "RO17 (D-RO17-1): the point's current label, the word its plant "
            "uses (newest label row; the code where none). Show it first, "
            "the code second."
        )
    )
    tolerance_group: str
    is_extra: bool
    retired_at: datetime = Field(description="When it left the walk.")
    retired_reason: str = Field(description="Why, as the person or task wrote it.")


class WsZoneChoice(StrictModel):
    """One existing zone code Add may pick, with the Hor / Ver it carries."""

    zone_code: str
    tolerance_group: str


class WsPointListOut(StrictModel):
    """D-114-1: what Point Check's Wave Scan section shows for one model."""

    plant_code: str
    model_code: str
    items: list[WsPointItem] = Field(description="Every live point, in walk order.")
    retired_items: list[WsRetiredPointItem] = Field(
        description=(
            "Every retired row of this list, in walk order, with when and why. "
            "Never part of the live list: not a panel-match target, never "
            "pre-filled, off the dashboard. Its readings stay in History, tagged."
        )
    )
    zone_choices: list[WsZoneChoice] = Field(
        description=(
            "Every ref_checkzone code that is not already on this list, live "
            "or retired: what Add may pick. A code typed that is not here is a "
            "new code."
        )
    )
    horizontal_words: list[str] = Field(
        description=(
            "The words that make a name Horizontal (ck_zone_rule), so a screen "
            "can show a new code's Hor / Ver before it is sent. The server "
            "applies the same rule and the database enforces it."
        )
    )


class WsPointSettingRow(StrictModel):
    zone_code: str = Field(min_length=1, max_length=64)
    counted: bool


class WsPointSettingCreate(StrictModel):
    """D-114-2: change which points count. Append-only; latest row wins."""

    points: list[WsPointSettingRow] = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class WsPointSettingResult(StrictModel):
    rows_written: int
    operator_message: str


class WsPointAddCreate(StrictModel):
    """D-114-6: add a point at the end of this plant's walk for the model.

    Pick an existing zone code or type a new one. A new code is kept exactly
    as typed after trimming its ends; its Hor / Ver is read off the name. The
    point is tagged extra.
    """

    zone_code: str = Field(
        min_length=1, max_length=64,
        description=(
            "An existing ref_checkzone code (zone_choices), or a new one. A "
            "new code equal to an existing one ignoring case and spaces is "
            "refused 409 -- pick the existing one."
        ),
    )
    counted: bool = Field(default=True, description="Whether the dashboard counts it.")
    counted_in_completeness: bool = Field(
        default=False,
        description=(
            "RO17 (D-RO17-7). False (default): the point is tagged extra and "
            "car completeness ignores it, as before. True (Admin only, else "
            "403): it counts in completeness, and the result says how many "
            "stored cars became incomplete (ask completeness-impact first)."
        ),
    )
    reason: str = Field(
        min_length=3, max_length=500,
        description="Why this point exists. Stored with your name and the time.",
    )


class WsPointRetireCreate(StrictModel):
    """D-114-4: take a point off the live list, keeping everything."""

    zone_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(
        min_length=3, max_length=500,
        description="Why this point is gone. Stored with your name and the time.",
    )


class WsPointRestoreCreate(StrictModel):
    """RO17 (D-RO17-9): bring a retired point back at its own number."""

    zone_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(
        min_length=3, max_length=500,
        description="Why it is back. Stored with your name and the time.",
    )


class WsPointChangeResult(StrictModel):
    """What an add, a retire or a restore did, in the list's own terms."""

    zone_code: str
    point_no: int = Field(ge=1)
    tolerance_group: str
    label: str = Field(description="RO17: the point's current label.")
    incomplete_cars: int | None = Field(
        description=(
            "RO17 (D-RO17-7): stored cars of this plant x model that became "
            "INCOMPLETE because the added point counts in completeness. Null "
            "unless counted_in_completeness was true."
        )
    )
    operator_message: str


class WsCompletenessImpactOut(StrictModel):
    """RO17 (D-RO17-7): what counting a new point in completeness would do.

    Measured by doing the add inside a savepoint that is always rolled back.
    """

    zone_code: str
    cars_incomplete_now: int = Field(ge=0)
    cars_incomplete_after: int = Field(ge=0)
    cars_become_incomplete: int
    operator_message: str


__all__ = [
    "WsCompletenessImpactOut",
    "WsPointAddCreate",
    "WsPointChangeResult",
    "WsPointItem",
    "WsPointListOut",
    "WsPointModelOut",
    "WsPointModelsOut",
    "WsPointRestoreCreate",
    "WsPointRetireCreate",
    "WsPointSettingCreate",
    "WsPointSettingResult",
    "WsPointSettingRow",
    "WsRetiredPointItem",
    "WsZoneChoice",
]
