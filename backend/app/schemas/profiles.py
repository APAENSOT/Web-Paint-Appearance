"""Owner-publish of a verified template profile (T26, spec S20).

One body and one result. The body carries **no Excel**: it names a workbook
this plant has already stored, by hash, so publishing proves a layout against
bytes the platform can replay rather than against an attachment nobody can
check afterwards. Everything else in the body is the part a database cannot
supply -- who verified it, and what the proof was.

`AGENTS.md` rule 9: the frontend's types come from here, not the other way
round. The Admin publish UI is Codex's, after this report is rechecked.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from app.schemas.common import StrictModel


class IgnoredHeader(StrictModel):
    """A column a named owner decided is not a WaveScan field.

    FVL's `Panel2` is the case this exists for: a derived group keyword that
    is genuinely not a measurement field. It becomes an approved, reasoned
    `IGNORED` row on this profile version -- never an auto-ignore, because a
    column nobody looked at could be the one that says which line the vehicle
    ran on (spec S9).
    """

    header: str = Field(
        min_length=1, max_length=200,
        description=(
            "The header as the sheet spells it. Normalised on the way in the "
            "same way the reader normalises a header row: lower-cased, "
            "trimmed, underscores to spaces."
        ),
        examples=["Panel2"],
    )
    reason: str = Field(
        min_length=1, max_length=2000,
        description="Why this column is not a field. Stored with the approver.",
    )

    @field_validator("header", "reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("must not be blank")
        return trimmed


class ProfilePublishCreate(StrictModel):
    file_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "SHA-256 of a workbook **already stored for this plant**. The "
            "layout published is the one those bytes carry, re-read from the "
            "object store -- this route does not accept an upload, so what is "
            "verified is always something the platform can replay."
        ),
    )
    source_sheet: str | None = Field(
        default=None, max_length=200,
        description=(
            "Which sheet of that workbook proves the layout. Optional when "
            "the workbook has exactly one WaveScan sheet."
        ),
    )
    named_owner: str = Field(
        min_length=1, max_length=200,
        description=(
            "The plant or quality owner who verified the fixture. A person, "
            "not the Admin account pressing the button: an ordinary Admin "
            "approval is explicitly not enough to make a layout "
            "commit-capable (design M6, spec S15/S20)."
        ),
    )
    notes: str = Field(
        min_length=1, max_length=4000,
        description=(
            "What the proof was, named. Required: a layout that claims to be "
            "proven has to say what proved it."
        ),
    )
    fill_missing_plant: bool = Field(
        default=False,
        description=(
            "This layout is known to omit the Plant column, so `plant` is "
            "filled from the upload's expected_plant. The only field a "
            "profile may supply (T18)."
        ),
    )
    ignored_headers: list[IgnoredHeader] = Field(
        default_factory=list,
        description=(
            "Columns of this layout that are not WaveScan fields. Each needs "
            "a reason; the approver recorded against them is named_owner."
        ),
    )

    @field_validator("named_owner", "notes")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError(
                "must not be blank: a verified layout records who verified it "
                "and what proved it"
            )
        return trimmed


class ProfilePublished(StrictModel):
    profile_id: int
    version: int = Field(
        description=(
            "Appended, never edited. The previous active version for this "
            "contract is deactivated; its own fixture_verified is left as it "
            "was, because it is a statement about a decision that was made."
        )
    )
    domain: str = Field(examples=["WAVESCAN"])
    plant_code: str
    semantic_signature: str = Field(
        description="The contract this version is selected by (domain, plant, this)."
    )
    template_fingerprint: str = Field(
        description="The exact ordered layout of the proving workbook. Provenance."
    )
    fixture_verified: bool = Field(
        description="True. This route is the only application path that can set it."
    )
    fixture_file_hash: str = Field(description="The stored workbook that proved it.")
    named_owner: str
    previous_profile_id: int | None = Field(
        default=None,
        description="The version this one supersedes, or null for a first publish.",
    )
    ignored_headers: int = Field(
        default=0, description="Column-policy IGNORED rows written with this version."
    )
    replayed_load_ids: list[int] = Field(
        default_factory=list,
        description=(
            "Batches of this plant and contract that were re-derived from "
            "their stored bytes because of this publish. Replay ends at "
            "PENDING_REVIEW or REJECTED_TEMPLATE and never commits: turning "
            "rows into measurements stays an Engineer pressing commit on a "
            "sheet a person has read."
        ),
    )
    audit_action: str = Field(
        default="profile.publish",
        description="The audit_event written in the same transaction.",
    )
