"""Correction and batch-supersede request DTOs.

The two halves of ADR 0005: a wrong fact is corrected by **adding a row**, and
a bad batch is retired by **changing its status**. Neither writes over a
measurement value, and nothing in this package can -- the application role
holds no `UPDATE` and no `DELETE` on `wavescan` at all.

Two rules are enforced here rather than in SQL, because a 422 that names the
field is a better answer than a 500 from a CHECK constraint:

* **Ranges match the database.** `cf` and `doi` are 0-100, `b` is -100..100,
  the rest are non-negative, `measured_date` is 2000-01-01..2100-12-31 --
  the same bounds as `ck_ws_cf`, `ck_ws_doi`, `ck_ws_b`, `ck_ws_nonneg` and
  `ck_ws_date`. A correction of 101 or a date of 1990 is refused by the DTO
  with a readable message instead of reaching the table.
* **Identity is not patchable.** `plant`, `model`, `checkzone`, `color`,
  `tolerance_group`, `paintline`, `load_id`, `source_sheet` and `source_row`
  are absent from `CorrectionCreate`, and `StrictModel` forbids extra keys, so
  sending one is a 422. That is deliberate: those fields say *which cell this
  is*, and a wrong zone or colour is a mapping decision (T08) or an onboarding
  one, not a correction. A correction changes what the instrument read, never
  what was measured.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from app.schemas.common import StrictModel
from app.schemas.measurements import MeasurementOut

#: The measures a correction may change, and the bounds each already has in
#: the database. Kept as data so the DTO and the report cannot drift from
#: each other, and so a test can assert the pairing.
#: (field, minimum, maximum) -- `None` means the column has no bound there.
MEASURE_BOUNDS: dict[str, tuple[Decimal, Decimal | None]] = {
    "lw": (Decimal(0), None),
    "sw": (Decimal(0), None),
    "cf": (Decimal(0), Decimal(100)),
    "doi": (Decimal(0), Decimal(100)),
    "du": (Decimal(0), None),
    "wa": (Decimal(0), None),
    "wb": (Decimal(0), None),
    "wc": (Decimal(0), None),
    "wd": (Decimal(0), None),
    "we": (Decimal(0), None),
}

#: `b` is the one nullable measure, and the one that may be negative.
B_BOUNDS = (Decimal(-100), Decimal(100))

#: Same inclusive window as `ck_ws_date`.
DATE_BOUNDS = (date(2000, 1, 1), date(2100, 12, 31))

#: Everything a correction may carry besides the reason. Used by the "at
#: least one change" check below and by the service that applies the patch.
PATCHABLE_FIELDS: tuple[str, ...] = (
    "measured_date", "serial_no", *MEASURE_BOUNDS, "b",
)

#: What a correction may NOT carry. Not a runtime check -- `StrictModel`
#: already refuses any key that is not a field -- but the list belongs in the
#: contract so a client knows why, and a test asserts none of them is a field.
IDENTITY_FIELDS: tuple[str, ...] = (
    "plant", "model", "checkzone", "color", "tolerance_group", "paintline",
    "load_id", "source_sheet", "source_row",
)

_MEASURE_NOTE = (
    "Send a decimal STRING for an exact value. A JSON number is parsed as an "
    "IEEE-754 double first, which is the rounding T02 removed from the "
    "database and AGENTS.md section 4 lists as a defect."
)

def _required_reason(value: str) -> str:
    """Trim, then insist there is something left.

    `min_length` alone counts whitespace, so "   " would pass the DTO and be
    refused three layers down by `ck_supersession_reason` -- a 409 from a
    constraint where the caller deserves a 422 naming the field. Trimming
    here also means the reason is stored the way it is read.
    """
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(
            "a reason is required and cannot be only whitespace. It is stored "
            "on the record that retires the measurement, and is what somebody "
            "reading the history later has to go on."
        )
    return trimmed


NonNegative = Annotated[Decimal, Field(ge=0, description=_MEASURE_NOTE, examples=["3.7"])]
Percentage = Annotated[
    Decimal, Field(ge=0, le=100, description=_MEASURE_NOTE, examples=["62.4"])
]


class CorrectionCreate(StrictModel):
    """What an Engineer is changing, and why.

    The reason is mandatory (`03-SECURITY.md` §5: "Insert correction row
    (reason required)"). A body carrying only a reason is a 422: a reason with
    no change is not a correction, and recording one would put an audit event
    and a duplicate row in the database for nothing.
    """

    reason: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "Why the original is wrong. Stored on the new row and on the "
            "supersession record, and shown to whoever reads either."
        ),
        examples=["CF transposed at entry; instrument tape reads 62.4"],
    )

    measured_date: date | None = Field(
        default=None,
        ge=DATE_BOUNDS[0],
        le=DATE_BOUNDS[1],
        description="Between 2000-01-01 and 2100-12-31 (ck_ws_date).",
    )
    serial_no: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Panel serial. Blank is refused (ck_ws_serial).",
    )

    lw: NonNegative | None = None
    sw: NonNegative | None = None
    cf: Percentage | None = None
    doi: Percentage | None = None
    du: NonNegative | None = None
    wa: NonNegative | None = None
    wb: NonNegative | None = None
    wc: NonNegative | None = None
    wd: NonNegative | None = None
    we: NonNegative | None = None
    b: Annotated[Decimal, Field(ge=-100, le=100, description=_MEASURE_NOTE)] | None = Field(
        default=None,
        description=(
            "The one nullable measure. Send null to clear it; omit the key to "
            "leave it as the original had it. " + _MEASURE_NOTE
        ),
    )

    _trim_reason = field_validator("reason")(_required_reason)

    @model_validator(mode="after")
    def _at_least_one_change(self) -> "CorrectionCreate":
        """A reason with nothing to change is not a correction.

        `model_fields_set` is what distinguishes "omitted" from "sent as
        null", which matters for `b`: clearing it is a real change and must
        count as one.
        """
        changed = self.model_fields_set & set(PATCHABLE_FIELDS)
        if not changed:
            raise ValueError(
                "a correction must change at least one of: "
                + ", ".join(PATCHABLE_FIELDS)
                + ". A reason on its own records no correction. Identity "
                "fields ("
                + ", ".join(IDENTITY_FIELDS)
                + ") are not correctable here: they say which cell this is, "
                "and changing one is a mapping or onboarding decision."
            )
        return self

    @property
    def patch(self) -> dict[str, object]:
        """Only the fields the caller actually sent, `b: null` included."""
        return {
            name: getattr(self, name)
            for name in PATCHABLE_FIELDS
            if name in self.model_fields_set
        }


class CorrectionResult(StrictModel):
    """The correction, and what it retired.

    `measurement` is the new active row -- the same shape `GET /measurements`
    returns, so a client can drop it straight into the table it is already
    rendering.
    """

    measurement: MeasurementOut = Field(
        description=(
            "The new active row, the same shape GET /measurements returns. "
            "Its measurement_id is new and its corrects_measurement_id names "
            "the row below."
        )
    )
    superseded_measurement_id: int = Field(
        description=(
            "The row this correction retired. It is still in wavescan and "
            "still readable by the owner; it is gone from every active read."
        )
    )
    supersession_id: int = Field(
        description="measurement_supersession.id -- the evidence, with reason and actor."
    )
    audit_action: str = Field(
        default="measurement.correct",
        description="The audit_event written in the same transaction.",
    )
    note: str = Field(
        default=(
            "wavescan grew by one row. No measurement value was overwritten "
            "and nothing was deleted (ADR 0005)."
        )
    )


class SupersedeCreate(StrictModel):
    """Retire a whole committed batch.

    This is **not** a per-row supersession. The active-data predicate already
    hides a batch's facts once its status leaves `COMMITTED`
    (`01-DATA-MODEL.md` §5), so retiring the batch is one status change, not
    one `measurement_supersession` row per measurement. Per-row supersession
    is what a *correction* does, and it means something different: that one
    reading was replaced by another.
    """

    reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Why this batch should no longer be read as current.",
        examples=["Re-sent by the plant with corrected serials; superseded by load 812"],
    )
    _trim_reason = field_validator("reason")(_required_reason)

    replacement_load_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Optional. Another COMMITTED batch for the same plant that "
            "replaces this one. Recorded on load_batch.superseded_by of the "
            "batch being retired."
        ),
    )


class AbandonCreate(StrictModel):
    """Remove a sheet that never produced a measurement from the review queue.

    `{ reason }` and nothing else (T21). There is no replacement batch: an
    abandoned sheet replaces nothing, and a committed one is superseded
    instead.
    """

    reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Why this sheet should leave the review queue.",
        examples=["Uploaded under the wrong month; plant re-sent the full file."],
    )
    _trim_reason = field_validator("reason")(_required_reason)


class AbandonResult(StrictModel):
    load_id: int
    status: str = Field(description="ABANDONED.")
    previous_status: str = Field(
        description="PENDING_REVIEW, REJECTED_TEMPLATE or FAILED."
    )
    reason: str
    audit_action: str = Field(
        default="batch.abandon",
        description="The audit_event written in the same transaction.",
    )
    note: str = Field(
        default=(
            "Nothing was deleted. The stored bytes, stg_raw, the review "
            "projection, acknowledgements, overrides and history are retained; "
            "this batch has no wavescan rows. Replay and commit now refuse it."
        )
    )


class SupersedeResult(StrictModel):
    load_id: int
    status: str = Field(description="SUPERSEDED.")
    previous_status: str
    superseded_by: int | None = Field(
        description="replacement_load_id, when one was named."
    )
    reason: str
    measurements_hidden: int = Field(
        description=(
            "How many rows left the active reads. They are still in wavescan: "
            "this route changes one column on load_batch and nothing else."
        )
    )
    audit_action: str = Field(
        default="batch.supersede",
        description="The audit_event written in the same transaction.",
    )


class RestoreCreate(StrictModel):
    """Put one ABANDONED or SUPERSEDED sheet back (T25). `{ reason }` only.

    One sheet per call. There is no restore-all: each sheet is its own
    decision and its own audit row, as abandon and supersede are.
    """

    reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Why this sheet should be back in the workflow.",
        examples=["Retired by mistake; this is the only July AAT file."],
    )
    _trim_reason = field_validator("reason")(_required_reason)


class RestoreResult(StrictModel):
    load_id: int
    status: str = Field(
        description=(
            "COMMITTED when restored from SUPERSEDED. From ABANDONED, the "
            "status the sheet was abandoned from (PENDING_REVIEW, "
            "REJECTED_TEMPLATE or FAILED), read from the batch.abandon audit "
            "event; PENDING_REVIEW when that event is missing."
        )
    )
    previous_status: str = Field(description="ABANDONED or SUPERSEDED.")
    reason: str
    audit_action: str = Field(
        description=(
            "batch.restore (from SUPERSEDED) or batch.reopen (from "
            "ABANDONED). Written in the same transaction."
        )
    )
