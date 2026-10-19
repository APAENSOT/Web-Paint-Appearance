"""Plant Data Manager DTOs: workbooks, rows, issues, history, acknowledgement.

Shapes only. Three things are deliberately absent, and their absence is the
contract:

* **No grade, pass rate or band.** D1 is open. `operational_summary` is a
  workflow label (uploaded -> reviewed -> committed), never a judgement of
  the measurements, and nothing in this module derives a number from a
  measurement value.
* **No week or month bucket.** Dates are API fields; the grouping rule is
  documented in `02-PIPELINE.md` and applied by the client (T19 locked
  decision 3). A bucket computed here would be a second place to disagree
  about which week a file belongs to.
* **No mutation except the acknowledgement and (T21) the review override.**
  Every other shape here is a read of something already stored. An override
  is append-only evidence about a proposed value; it never edits a
  measurement, a projection cell or a raw cell.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import MeasureValue, PageInfo, StrictModel
from app.schemas.corrections import B_BOUNDS, MEASURE_BOUNDS, _required_reason
from app.schemas.ingest import BatchCountsOut, BatchOut

#: T21: the measures a review override may replace -- the correction
#: vocabulary, never an identity field.
OverrideField = Literal["lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b"]

DECIMAL_PATTERN = re.compile(r"-?\d+(\.\d+)?")

OperationalSummary = Literal[
    "PROCESSING", "REVIEW_REQUIRED", "PARTIALLY_COMMITTED", "ACTIVE", "SUPERSEDED",
    "ABANDONED", "SKIPPED",
]

Disposition = Literal["LOAD", "DUPLICATE", "REJECT", "QUARANTINE", "AGGREGATE_ROW"]

AckCategory = Literal[
    "REJECTED_ROWS", "QUARANTINED_MODELS", "DUPLICATE_ROWS", "POSSIBLE_REPLACEMENT",
]

IssueLevel = Literal["BLOCKER", "WARNING", "INFORMATION"]

#: What a reviewer is allowed to do about an issue. Short, closed, and ASCII
#: so a UI can switch on it: `mapping` (propose a column/model mapping for an
#: Admin to approve, then replay), `corrected_source` (the plant re-sends
#: better bytes), `blocked_identity` (nothing in this platform fixes it --
#: SAP vehicle identity, M7), `acknowledge` (read it and accept it),
#: `wait_for_worker` (the parse has not finished), `supersede_separate` (an
#: explicit Admin supersede with a reason, never automatic).
IssueResolution = Literal[
    "mapping", "corrected_source", "blocked_identity", "acknowledge",
    "wait_for_worker", "supersede_separate",
]

HASH_PATTERN = r"^[0-9a-f]{64}$"


class WorkbookSheetOut(StrictModel):
    """One sheet of a workbook: a `load_batch` plus its readiness."""

    batch: BatchOut
    committable: bool = Field(
        description=(
            "True only when committing this sheet right now would succeed. "
            "The same value GET /api/v1/batches/{load_id} publishes."
        )
    )
    commit_blockers: list[str] = Field(
        description=(
            "Stable tokens naming why this sheet cannot be committed: "
            "NOT_PENDING_REVIEW, UNBALANCED, UNKNOWN_TEMPLATE, "
            "UNVERIFIED_PROFILE, NO_REVIEW_PROJECTION, "
            "VEHICLE_IDENTITY_MISSING, WARNINGS_UNACKNOWLEDGED."
        )
    )
    required_acknowledgements: list[AckCategory] = Field(
        description=(
            "Warning categories this sheet must have acknowledged before it "
            "can be committed, because rows the plant sent are not becoming "
            "measurements."
        )
    )
    acknowledged: list[AckCategory] = Field(
        description=(
            "Categories already acknowledged for this sheet's CURRENT "
            "review_revision. A replay moves the revision, so an earlier "
            "acknowledgement stops appearing here while staying in the "
            "history."
        )
    )


class SkippedWorkbookSheetOut(StrictModel):
    source_sheet: str
    reason: str
    legacy_load_id: int | None = Field(default=None, description="Kept historical batch id; skipped sheets create no new batch.")


class WorkbookOut(StrictModel):
    """One workbook: one file_hash at one plant, with its sheets as children."""

    file_hash: str = Field(description="SHA-256 of the uploaded bytes. The identity.")
    plant_code: str
    source_file: str = Field(
        description=(
            "The filename as uploaded. A label: a renamed file with the same "
            "bytes is the same workbook, and identity is the hash."
        )
    )
    operational_summary: OperationalSummary = Field(
        description=(
            "Where this file is in the workflow. NOT a grade and not a pass "
            "rate: it is derived from its sheets' load_batch.status values "
            "only (docs/02-PIPELINE.md)."
        )
    )
    measured_date_min: date | None = Field(
        description=(
            "Earliest cleaned measurement date in this workbook, from the "
            "review projection for sheets in review and from wavescan for "
            "committed ones. Null while the worker is still parsing -- a week "
            "is never inferred from the upload time or the filename."
        )
    )
    measured_date_max: date | None
    uploaded_at: datetime = Field(description="Workbook upload time, or earliest legacy load_batch.started_at.")
    loaded_by: str | None = Field(description="app_user.id of the uploader.")
    counts: BatchCountsOut = Field(description="Sum of this workbook's data batch counts, excluding skipped side sheets.")
    sheet_count: int
    skipped_sheets: list[SkippedWorkbookSheetOut] = Field(default_factory=list, description="Out-of-scope sheets kept under this file, excluded from data batch counts.")
    skipped_sheet_count: int = Field(default=0, ge=0)
    superseded: bool = Field(
        description=(
            "True exactly when operational_summary is SUPERSEDED: no live "
            "sheet, and at least one SUPERSEDED. The rows stay readable."
        )
    )
    abandoned: bool = Field(
        description=(
            "True exactly when operational_summary is ABANDONED: every sheet "
            "was removed from review before producing a measurement. Bytes, "
            "staging, projection and history are retained (T21)."
        )
    )
    vehicle_set_count: int = Field(
        description=(
            "Vehicle sets across this workbook's sheets, grouped by the "
            "server exactly as the vehicles read groups them, including "
            "identity-incomplete groups. 0 while nothing has been parsed or "
            "committed yet."
        )
    )
    measured_dates_span_months: bool = Field(
        description=(
            "True when measured_date_min and measured_date_max fall in "
            "different calendar months. False when either is null."
        )
    )
    sheets: list[WorkbookSheetOut]


Inbox = Literal["all", "current_month", "needs_attention"]


class WorkbookPage(StrictModel):
    items: list[WorkbookOut]
    page: PageInfo
    plant_code: str
    plant_is_active: bool = Field(
        description=(
            "False for a known plant this platform has not onboarded (FVL, "
            "D5). Its workbook list is an empty page rather than an error: "
            "the plant is shown with its reason, not hidden."
        )
    )
    inbox: Inbox = Field(
        default="all",
        description="The inbox this page was selected by (the query value).",
    )
    uploaded_month: str | None = Field(
        default=None,
        description=(
            "The UTC month (YYYY-MM) current_month and needs_attention were "
            "decided against: the query value, or the current UTC month when "
            "none was sent. Null for inbox=all, which ignores it."
        ),
    )


class TemplateProfileOut(StrictModel):
    profile_id: int
    template_fingerprint: str
    version: int
    is_active: bool
    fixture_verified: bool = Field(
        description=(
            "A fixture proved this layout commits correctly. Written by seed, "
            "migration or the owner only -- approving a header mapping does "
            "not set it (design M6)."
        )
    )
    fill_missing_plant: bool
    notes: str | None
    load_ids: list[int] = Field(description="Sheets of this workbook that it parsed.")


class ReplacementHint(StrictModel):
    """An older active workbook whose dates overlap this one.

    Advisory only. Nothing retires a workbook automatically: supersede stays
    an explicit Admin action carrying a reason (design M14).
    """

    file_hash: str
    source_file: str
    measured_date_min: date | None
    measured_date_max: date | None


class AcknowledgementOut(StrictModel):
    ack_id: int
    load_id: int
    plant_code: str
    file_hash: str
    category: AckCategory
    note: str | None
    review_revision: str = Field(
        description=(
            "The projection hash this acknowledgement is about. It satisfies "
            "the commit gate only while the batch still reports the same "
            "revision."
        )
    )
    actor_user_id: str
    created_at: datetime
    audit_action: str = Field(
        default="review.acknowledge",
        description="The audit_event written in the same transaction.",
    )


class WorkbookDetailOut(StrictModel):
    workbook: WorkbookOut
    profiles: list[TemplateProfileOut] = Field(
        description=(
            "The template profiles that parsed this workbook's sheets. Where "
            "a sheet has a projection, the fingerprint shown is the one that "
            "actually parsed it, not the frozen load_batch.template_fingerprint "
            "recorded at upload."
        )
    )
    possible_replacements: list[ReplacementHint]
    acknowledgements: list[AcknowledgementOut] = Field(
        description=(
            "Every acknowledgement ever written for these sheets, oldest "
            "first, including ones a replay has invalidated -- compare "
            "review_revision with the sheet's current one."
        )
    )


class WorkbookRowOut(StrictModel):
    load_id: int
    source_sheet: str
    source_row: int = Field(description="1-based row number in the sheet.")
    disposition: Disposition
    reason: str | None
    detail: str | None
    canonical: dict | None = Field(
        description="What commit would insert, or did insert, for this row."
    )
    raw: dict | None = Field(
        description=(
            "What the file said: recognised values and unmapped extras. Null "
            "only when projection_missing is true."
        )
    )
    normalized_fields: list[str] = Field(
        description=(
            "Fields filled or mapped for this row rather than read from it. "
            "Today: plant, filled from the upload's expected_plant."
        )
    )
    profile_id: int | None
    template_fingerprint: str | None
    review_revision: str | None
    measurement_id: int | None = Field(
        description=(
            "The wavescan row this source row produced, once committed. "
            "Present for a superseded batch too: this is the file's own "
            "drill-down, not the active measurement list."
        )
    )
    projection_missing: bool = Field(
        description=(
            "True for a sheet committed before the review projection existed "
            "(T18). Its facts are shown with raw null; the workbook is never "
            "re-parsed to fill them in."
        )
    )


class WorkbookRowFilters(StrictModel):
    load_id: int | None
    disposition: Disposition | None


class WorkbookRowPage(StrictModel):
    items: list[WorkbookRowOut]
    page: PageInfo
    filters: WorkbookRowFilters
    file_hash: str
    plant_code: str


class IssueSample(StrictModel):
    load_id: int
    source_sheet: str
    source_row: int
    reason: str | None


class IssueOut(StrictModel):
    level: IssueLevel
    token: str = Field(
        description=(
            "Stable token. Blockers are the commit_blockers vocabulary plus "
            "the sheet statuses FAILED, REJECTED_TEMPLATE and RUNNING; "
            "warnings are the four acknowledgement categories; information "
            "is PLANT_FILLED and PROFILE_APPLIED."
        )
    )
    load_id: int | None = Field(description="Null when the issue is workbook-wide.")
    count: int = Field(description="Rows or sheets this issue covers.")
    sample_rows: list[IssueSample] = Field(
        description="Up to 20 example rows. The full list is the rows route."
    )
    acked: bool = Field(
        description=(
            "True when this category is acknowledged for the sheet's CURRENT "
            "review revision. Always false for blockers and information."
        )
    )
    resolution: IssueResolution | None = Field(
        description=(
            "What a reviewer can do about it. Null for INFORMATION, "
            "which is disclosure and needs no action."
        )
    )
    operator_message: str | None = Field(
        default=None,
        description=(
            "T103 (D-103-4): the stored sentence for an issue whose token "
            "alone would mislead -- today the Film sheet that names no point "
            "(D-99-9), whose refusal is final and names what would help. "
            "Null for every other issue, whose token and resolution say it."
        ),
    )


class WorkbookIssuesOut(StrictModel):
    file_hash: str
    plant_code: str
    issues: list[IssueOut]


class HistoryEventOut(StrictModel):
    id: int
    occurred_at: datetime
    actor_user_id: str | None
    actor_type: str
    action: str
    entity_type: str
    entity_id: str
    correlation_id: str | None
    after: dict | None = Field(description="Stored as written. Never edited.")


class WorkbookHistoryOut(StrictModel):
    file_hash: str
    plant_code: str
    events: list[HistoryEventOut] = Field(
        description=(
            "Oldest first, by audit_event.id. Append-only: no role holds "
            "UPDATE or DELETE on audit_event."
        )
    )


def _clean_note(value: str | None) -> str | None:
    """Trim, and treat a whitespace-only note as absent.

    `min_length` alone counts spaces, so "   " would pass the DTO and be
    refused by `ck_ack_note_required` three layers down -- a 500 from a
    constraint where the caller deserves a 422 naming the field. Same
    reasoning as the correction reason.
    """
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class AcknowledgementCreate(StrictModel):
    """Read these warnings and accept them, for exactly these rows.

    `review_revision` is required and is not a formality: it is what makes
    this an acknowledgement of a proposal rather than a standing permission.
    If the batch has been replayed since the reviewer loaded the page, the
    revision no longer matches and the request is refused with 409 rather
    than recorded against rows nobody read.
    """

    load_id: int = Field(
        ge=1, description="A sheet of this workbook, at this plant."
    )
    category: AckCategory
    review_revision: str = Field(
        min_length=64,
        max_length=64,
        pattern=HASH_PATTERN,
        description=(
            "The batch's current review_revision, as returned by GET "
            "/api/v1/batches/{load_id}. A stale value is a 409 and nothing "
            "is written."
        ),
        examples=["0" * 64],
    )
    note: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Why these rows are acceptable. REQUIRED for REJECTED_ROWS and "
            "QUARANTINED_MODELS (design M11); optional for DUPLICATE_ROWS and "
            "POSSIBLE_REPLACEMENT. Stored with the actor and the revision."
        ),
        examples=["Plant confirmed rows 41-44 were a re-test; originals stand."],
    )

    _trim_note = field_validator("note")(_clean_note)


# =====================================================================
# T21: vehicle sets, points, overrides
# =====================================================================
VEHICLE_ID_PATTERN = HASH_PATTERN


class VehicleDispositionCounts(StrictModel):
    load: int
    duplicate: int
    reject: int
    quarantine: int


class VehicleSetOut(StrictModel):
    """One vehicle on one sheet: the review unit (design F8).

    The key is `plant_code + measured_date + model + color + serial_no` on
    one `load_id`. Checkzone is a point inside the set, never the key, and
    two serials are never one set.
    """

    vehicle_id: str = Field(
        description=(
            "64-hex SHA-256 of UTF-8 "
            "'{load_id}|{measured_date ISO or empty}|{model or empty}|"
            "{color or empty}|{serial_no or empty}' for a WaveScan set; a "
            "FilmThickness set appends '|{logical_vehicle_id}' (RO11), so it "
            "is History's car. Stable and unique per sheet. Not derived from "
            "any source_row."
        )
    )
    load_id: int
    plant_code: str
    measured_date: date | None
    model: str | None
    color: str | None
    serial_no: str | None
    identity_complete: bool = Field(
        description=(
            "False when any of measured_date, model, color or serial_no is "
            "missing. Such a group is NOT a vehicle: all rows sharing the "
            "same missing parts are one group, and no serial is generated. "
            "REJECT rows have no cleaned identity and QUARANTINE rows have "
            "no model, so they land in groups like this."
        )
    )
    point_count: int = Field(
        description=(
            "How many of the expected_point_count points this set has a "
            "reading on (T114-FIX). A reading on a retired point, an extra "
            "point or a code off the list counts neither way; with no list, "
            "every distinct checkzone counts."
        )
    )
    expected_point_count: int | None = Field(
        description=(
            "The live, non-extra points of this plant's Wave Scan list for "
            "this model (ref_model.expected_zone_count when the plant has "
            "no list for it; T114-FIX). Null when the model is missing or "
            "unknown: expected not available."
        )
    )
    incomplete_set: bool = Field(
        description=(
            "True when identity_complete is false, or expected_point_count "
            "is known and point_count differs from it."
        )
    )
    dispositions: VehicleDispositionCounts = Field(
        description=(
            "Rows of this set by disposition. A DUPLICATE row repeats a "
            "vehicle and is counted here, never as a second vehicle."
        )
    )
    car_label: str | None = Field(
        default=None,
        description=(
            "D-RO17-17: set only for a Wave Scan car with a car_key (a "
            "many-car blank-serial sheet), e.g. 'car 2 of 5 that day - from "
            "row 34'. The ordinal is by the car's first source row among the "
            "cars of its (load, date, model, colour). Null otherwise."
        ),
    )
    date_is_month_only: bool = Field(
        default=False,
        description=(
            "RO18 (B4): the sheet had no date. measured_date is the 1st of "
            "the month a person named; show '<Month YYYY> - day not "
            "recorded', never the day."
        ),
    )


class VehicleSetPage(StrictModel):
    items: list[VehicleSetOut]
    page: PageInfo
    load_id: int
    file_hash: str
    plant_code: str


class CurrentOverrideOut(StrictModel):
    """The latest override of one field of one row (by created_at)."""

    override_id: int
    field: str
    previous_proposed: MeasureValue | None = Field(
        description="The proposed value this override replaced."
    )
    new_value: MeasureValue | None = Field(
        description="Null only for b, which is the one nullable measure."
    )
    reason: str
    review_revision: str = Field(
        description="The revision the reviewer had loaded when writing it."
    )
    created_at: datetime
    actor_user_id: str
    applied: bool = Field(
        description=(
            "True when this row is LOAD in the current projection, so the "
            "proposed value carries this override. An override is never "
            "applied to a row that is not loading."
        )
    )


class VehiclePointOut(StrictModel):
    load_id: int
    source_sheet: str
    source_row: int
    checkzone: str | None
    disposition: Disposition
    reason: str | None
    detail: str | None
    raw: dict | None = Field(
        description=(
            "What the file said. Never changed by an override. Null only "
            "when projection_missing is true."
        )
    )
    proposed: dict | None = Field(
        description=(
            "Canonical: what commit would insert, or did insert, including "
            "any applied override."
        )
    )
    current_overrides: list[CurrentOverrideOut]
    measurement_id: int | None
    projection_missing: bool


class VehiclePointPage(StrictModel):
    items: list[VehiclePointOut]
    page: PageInfo
    vehicle: VehicleSetOut
    file_hash: str
    plant_code: str


def _override_reason(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(
            "a reason is required and cannot be only whitespace: it is the "
            "record of why the file's value was not used."
        )
    return trimmed


class OverrideChange(StrictModel):
    """Replace one measure of one row of the vehicle set, with a reason.

    Identity fields (plant, model, checkzone, color, tolerance_group,
    paintline, serial_no, measured_date, load_id, source_sheet, source_row
    as a value) are not a `field` here and are a 422: changing which vehicle
    or zone a row is, is a mapping or a corrected re-upload.
    """

    source_row: int = Field(ge=1, description="A LOAD row of this vehicle set.")
    field: OverrideField
    value: str | None = Field(
        description=(
            "The new value as a decimal STRING, e.g. \"62.4\". A JSON number "
            "is a 422 (it would be parsed as a double first). JSON null is "
            "allowed only for b, to clear it. Bounds: cf and doi 0..100, b "
            "-100..100, the rest >= 0 -- the same bounds a T09 correction "
            "and wavescan's CHECKs use."
        ),
        examples=["62.4"],
    )
    reason: str = Field(min_length=1, max_length=2000)

    _trim_reason = field_validator("reason")(_override_reason)

    @field_validator("value", mode="before")
    @classmethod
    def _string_or_null(cls, value):
        if value is not None and not isinstance(value, str):
            raise ValueError(
                "value must be a decimal string or null, not a JSON number "
                "(same rule as a correction)."
            )
        return value

    @model_validator(mode="after")
    def _in_bounds(self) -> "OverrideChange":
        self.decimal_value()
        return self

    def decimal_value(self) -> Decimal | None:
        if self.value is None:
            if self.field != "b":
                raise ValueError(
                    f"{self.field} cannot be cleared: only b is a nullable "
                    f"measure."
                )
            return None
        text = self.value.strip()
        if not DECIMAL_PATTERN.fullmatch(text):
            raise ValueError(f"value {self.value!r} is not a plain decimal string")
        number = Decimal(text)
        if self.field == "b":
            low, high = B_BOUNDS
        else:
            low, high = MEASURE_BOUNDS[self.field]
        if number < low or (high is not None and number > high):
            bound = f"{low}..{high}" if high is not None else f">= {low}"
            raise ValueError(f"{self.field} {text} is outside {bound}")
        return number


class OverrideCreate(StrictModel):
    """Numeric overrides for ONE vehicle set of ONE sheet, as one save."""

    load_id: int = Field(ge=1, description="A sheet of this workbook, at this plant.")
    vehicle_id: str = Field(
        pattern=VEHICLE_ID_PATTERN,
        description="The server-computed id of the vehicle set being edited.",
    )
    review_revision: str = Field(
        min_length=64,
        max_length=64,
        pattern=HASH_PATTERN,
        description=(
            "The sheet's CURRENT review_revision. A stale value is a 409 and "
            "nothing is written."
        ),
    )
    changes: list[OverrideChange] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _one_change_per_cell(self) -> "OverrideCreate":
        seen: set[tuple[int, str]] = set()
        for change in self.changes:
            cell = (change.source_row, change.field)
            if cell in seen:
                raise ValueError(
                    f"row {change.source_row} field {change.field} appears "
                    f"twice in one save; send one value per cell."
                )
            seen.add(cell)
        return self


class OverrideOut(StrictModel):
    override_id: int
    load_id: int
    plant_code: str
    file_hash: str
    source_row: int
    field: str
    previous_proposed: MeasureValue | None
    new_value: MeasureValue | None
    reason: str
    review_revision: str = Field(description="The revision the reviewer had loaded.")
    actor_user_id: str
    created_at: datetime


class OverrideResult(StrictModel):
    load_id: int
    vehicle_id: str
    overrides: list[OverrideOut]
    previous_review_revision: str
    review_revision: str = Field(
        description=(
            "The sheet's NEW revision after synchronous revalidation. Every "
            "acknowledgement of the previous revision no longer satisfies "
            "the commit gate."
        )
    )
    counts: BatchCountsOut
    audit_action: str = Field(
        default="review.override",
        description="The audit_event written in the same transaction.",
    )
    note: str = Field(
        default=(
            "The sheet was re-derived from its stored bytes with the current "
            "overrides applied. stg_raw and each point's raw still show what "
            "the file said. No measurement was written."
        )
    )


__all__ = [
    "AckCategory",
    "CurrentOverrideOut",
    "Inbox",
    "OverrideChange",
    "OverrideCreate",
    "OverrideOut",
    "OverrideResult",
    "VehicleDispositionCounts",
    "VehiclePointOut",
    "VehiclePointPage",
    "VehicleSetOut",
    "VehicleSetPage",
    "AcknowledgementCreate",
    "AcknowledgementOut",
    "Disposition",
    "HistoryEventOut",
    "IssueLevel",
    "IssueOut",
    "IssueResolution",
    "IssueSample",
    "OperationalSummary",
    "ReplacementHint",
    "TemplateProfileOut",
    "WorkbookDetailOut",
    "WorkbookHistoryOut",
    "WorkbookIssuesOut",
    "WorkbookOut",
    "WorkbookPage",
    "WorkbookRowFilters",
    "WorkbookRowOut",
    "WorkbookRowPage",
    "WorkbookSheetOut",
]


# =====================================================================
# T37 -- workbook purge (ADR 0011)
# =====================================================================
class WorkbookPurgeCreate(StrictModel):
    """`{ reason }` and nothing else. The reason is stored on the audit row."""

    reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Why this workbook should not exist in the database.",
        examples=["Wrong layout loaded; will re-upload and map again."],
    )
    _trim_reason = field_validator("reason")(_required_reason)


class WorkbookPurgeResult(StrictModel):
    plant_code: str
    file_hash: str
    reason: str
    load_ids: list[int] = Field(description="Every load_batch of this hash that was deleted.")
    wavescan_deleted: int
    batches_deleted: int
    audit_id: int = Field(description="audit_event.id of the workbook.purge row.")
    audit_action: Literal["workbook.purge"] = "workbook.purge"
    note: str = Field(
        default=(
            "This workbook's batches, staging, review rows, rejects, jobs and "
            "wavescan rows were deleted. Published template profiles, aliases "
            "and standards are untouched. Uploading the same bytes again is a "
            "new batch."
        )
    )
