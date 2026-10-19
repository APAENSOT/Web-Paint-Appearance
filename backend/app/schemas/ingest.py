"""Upload, batch and commit DTOs.

Shapes only. Every number here is a count the database holds, and there is no
grade, pass rate or status derived from a measurement anywhere in this module
(D1, T05).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import PageInfo, StrictModel
from app.schemas.panel_match import BlockedPanelOut, CarriedOverOut

#: T21 adds ABANDONED: a sheet removed from the review queue before it
#: produced any measurement. Its bytes, staging, projection and audit trail
#: stay; replay and commit refuse it.
BatchStatus = Literal[
    "RUNNING", "PENDING_REVIEW", "COMMITTED", "FAILED", "SUPERSEDED",
    "REJECTED_TEMPLATE", "ABANDONED",
]


class BatchCountsOut(StrictModel):
    rows_in_file: int
    rows_loaded: int = Field(description="Rows that would become measurements.")
    rows_duplicate: int
    rows_rejected: int
    rows_quarantine: int = Field(description="Rows whose model is unidentified.")
    balanced: bool = Field(
        description=(
            "rows_in_file == loaded + duplicate + rejected + quarantine. A "
            "batch cannot be committed unless this is true "
            "(docs/02-PIPELINE.md section 6)."
        )
    )


class JobOut(StrictModel):
    status: Literal["QUEUED", "RUNNING", "DONE", "FAILED"]
    attempts: int
    last_error: str | None
    enqueued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class BatchOut(StrictModel):
    load_id: int
    source_file: str
    source_sheet: str
    plant_code: str | None = Field(
        description=(
            "The plant this batch is filed under: the expected_plant the "
            "upload declared, set when the batch was created and never "
            "re-derived from the rows (T17). Null only on batches created "
            "before that field existed."
        )
    )
    file_hash: str
    status: BatchStatus
    counts: BatchCountsOut
    started_at: datetime
    finished_at: datetime | None
    loaded_by: str | None = Field(description="app_user.id of the uploader.")
    notes: str | None
    superseded_by: int | None
    template_fingerprint: str | None = Field(
        default=None,
        description=(
            "The EXACT ordered-layout hash of this sheet's header row: "
            "ordered recognised fields with gaps, plus sorted unrecognised "
            "extras. Since T26 this is provenance, not the profile selection "
            "key -- when it moves between one month and the next but "
            "semantic_signature does not, somebody reordered the columns and "
            "the contract is unchanged."
        ),
    )
    domain: str | None = Field(
        default=None,
        description=(
            "Which measurement vocabulary read this sheet: WAVESCAN (CF) or, "
            "since T46, FILMTHICKNESS (PELT FilmBuild layers, facts in the "
            "filmthickness table). The two never share header aliases or "
            "model spellings."
        ),
    )
    semantic_signature: str | None = Field(
        default=None,
        description=(
            "Hash of the sorted set of recognised logical fields for this "
            "domain. With domain and plant_code, this selects the template "
            "profile (T26). A reordered workbook signs the same and parses."
        ),
    )
    sheet_class: str | None = Field(
        default=None,
        description=(
            "WAVESCAN, FILMTHICKNESS (T46), OUT_OF_SCOPE_SHEET or "
            "UNKNOWN_DATA_SHEET, decided from the header row and never from "
            "the tab's name. A FILMTHICKNESS sheet's held rows carry reason "
            "EXTRA_POINT, UNMAPPED_POINT or FILM_MODEL_UNRESOLVED. An "
            "out-of-scope sheet (Methods, Color Data) is preserved evidence "
            "of another domain, not a broken WaveScan template; an unknown "
            "data-like sheet blocks for classification."
        ),
    )
    unreviewed_headers: list[str] = Field(
        default_factory=list,
        description=(
            "Headers of this sheet that are neither a recognised logical "
            "field nor a column an owner approved ignoring. Non-empty means "
            "UNREVIEWED_HEADER blocks the commit until somebody decides; "
            "nothing is ever auto-ignored."
        ),
    )
    profile_id: int | None = Field(
        default=None,
        description=(
            "The template profile that parsed this batch: the active "
            "ref_template_profile row for (domain, plant_code, "
            "semantic_signature) (T26; T18 keyed on the ordered fingerprint). "
            "Null when no profile claims this contract, which is why such a "
            "batch is REJECTED_TEMPLATE."
        ),
    )
    fixture_verified: bool = Field(
        default=False,
        description=(
            "True when a fixture has proved this layout commits correctly. "
            "False when there is no profile, or a profile exists but has not "
            "been proved -- such a batch can be parsed and reviewed but not "
            "committed. Approving a header mapping does not set this."
        ),
    )
    review_revision: str | None = Field(
        default=None,
        description=(
            "Hash of the persisted review projection for this batch. Commit "
            "re-derives it from the stored bytes and refuses if it disagrees, "
            "so what was reviewed is what gets written (T18)."
        ),
    )
    job: JobOut | None = None


class FilmModelOptionsOut(StrictModel):
    """T61 (D-78-34): what may be picked for a sheet held FILM_MODEL_UNRESOLVED.

    Every field is **server-derived**, from the batch's own plant, file name
    and tab name. The client picks from these lists and never sends free
    text. Send the answer to
    `POST /api/v1/mappings/proposals` with `kind = "FILM_MODEL"` and payload
    `{plant, load_id, source_sheet, model_code, raw_token?}`; an Admin then
    approves it and the sheet is replayed.
    """

    load_id: int = Field(ge=1, description="The held batch, for the payload.")
    source_sheet: str = Field(description="The tab, for the payload.")
    plant_code: str = Field(description="The batch's plant, for the payload.")
    detail: str = Field(
        description=(
            "Why the model did not settle: the resolver's own sentence "
            "(for example which spellings disagreed)."
        )
    )
    resolution_source: str = Field(
        description=(
            "How far resolution got: `ambiguous` (the file and tab name mean "
            "two different models -- raw_token must then be omitted), "
            "`leftover` (a program with no FilmThickness list at this plant) "
            "or `none` (no approved spelling in either name)."
        ),
        examples=["none"],
    )
    candidates: list[str] = Field(
        default_factory=list,
        description=(
            "The models the file or tab name actually pointed at. Empty when "
            "the names carried no approved spelling. These are listed first "
            "in `choices`."
        ),
    )
    choices: list[str] = Field(
        default_factory=list,
        description=(
            "The ONLY models that may be sent as payload.model_code: this "
            "plant's FilmThickness vocabulary, candidates first. Derived from "
            "`ref_film_model_alias`, never `ref_plant_model` -- WaveScan "
            "reads that table and must never resolve RAPCAP (D-FT-08). "
            "Anything outside this list is 422."
        ),
    )
    teachable_tokens: list[str] = Field(
        default_factory=list,
        description=(
            "The only values that may be sent as payload.raw_token: the FTM "
            "filename token, and the words and run-together spellings of the "
            "file and tab name the resolver examined. Approving a choice that "
            "carries one also teaches `ref_film_model_alias` so the next file "
            "with that token resolves by itself. **Empty when "
            "`resolution_source` is `ambiguous`** -- that choice resolves the "
            "one sheet and teaches nothing, so raw_token must be omitted."
        ),
    )


class HeldLabelGroup(StrictModel):
    """One distinct held spelling on a batch (finish-batch spec section 4).

    Grouped from the persisted review projection, so a GET never opens Excel.
    `teachable_kind` is set only when Engineer identity-alias is implemented
    for that reason. Candidates are existing catalogue codes, never invented.
    """

    reason: str = Field(examples=["UNKNOWN_COLOR"])
    column: str = Field(examples=["color"])
    raw_value: str = Field(description="The cell text as the file spelled it.")
    count: int = Field(ge=1)
    teachable_kind: str | None = Field(
        default=None,
        description=(
            "ALIAS_COLOR or ALIAS_MODEL when that kind is implemented for "
            "this reason; null when the row stays held (named-owner "
            "catalogue, leftover without its own ref_model, or a reserved kind)."
        ),
    )
    candidates: list[str] = Field(
        default_factory=list,
        description=(
            "Existing catalogue codes for this field. Empty if none. **T89 "
            "(D-89-6)** for a panel question: the same list the guided match "
            "screen offers, in the same order -- mappable panels only, "
            "orientation-filtered, with the panels this batch has already "
            "used moved to `blocked_candidates`. Before T89 this was the "
            "plant's raw live panel list, half of which the approval path "
            "refuses."
        ),
    )
    blocked_candidates: list[BlockedPanelOut] = Field(
        default_factory=list,
        description=(
            "T89 (D-89-6). Panels this file has already used, for a panel "
            "question: shown last, disabled, each labelled with the spelling "
            "that took it. Empty for every other kind of question."
        ),
    )
    carried_over: CarriedOverOut | None = Field(
        default=None,
        description=(
            "T89 (D-89-9). An earlier decision about this exact spelling, so "
            "the row arrives pre-selected and marked as carried over instead "
            "of blank. Null when there is none; never auto-applied."
        ),
    )
    display_group: Literal[
        "colour", "model", "zone", "empty_identity", "date", "header", "plant_offer",
        "plant", "measure", "film_point", "film_model",
    ] = Field(
        description=(
            "Which question this is. T39 adds `plant` (the Plant column names "
            "another plant than the page) and `measure` (CF, or LW/SW, empty). "
            "T54 adds `film_point` (a FilmThickness location not on this "
            "plant's gold list, or an extra point) and `film_model` (the file or "
            "tab name does not settle one model this plant has a FilmThickness "
            "list for -- DBL / RB / RAP / SGL, or a leftover's own U704 / CX743 "
            "/ V363 / J73 since T55). Neither is teachable here."
        )
    )
    operator_message: str = Field(min_length=1, max_length=500)
    film_model: FilmModelOptionsOut | None = Field(
        default=None,
        description=(
            "T61 (D-78-34). Present only when `reason` is "
            "`FILM_MODEL_UNRESOLVED`: the server-derived model choices and "
            "teachable tokens for this sheet. Null for every other reason."
        ),
    )
    model_code: str | None = Field(
        default=None,
        description=(
            "T41 / T88. The model this panel question is about. **T88 "
            "(D-88-1):** a spelling written on more than one model produces "
            "one group per model, each carrying its own model, its own row "
            "`count` and its own `candidates` -- they are independent "
            "questions, not one ambiguity. Send it as ALIAS_CHECKZONE "
            "payload.model_code. Null for a hold that is not about a panel, "
            "or whose Model cell resolved to nothing."
        ),
    )
    orientations: list[str] = Field(
        default_factory=list,
        description=(
            "T88 (D-88-2 / G-88-5). The Tolerance Group values the file "
            "wrote for this spelling on this model -- normally one, "
            "`Horizontal` or `Vertical`. It is a **hard filter on proposals** "
            "in the guided match screen and never a score. More than one "
            "entry is a file problem: the screen says so and applies no "
            "orientation filter and no exhaustion for that spelling."
        ),
    )


#: Reject/quarantine reasons an Engineer may bind to an existing canonical.
TEACHABLE_HELD_REASONS: dict[str, str] = {
    "UNKNOWN_COLOR": "ALIAS_COLOR",
    "UNKNOWN_MODEL": "ALIAS_MODEL",
    # T39 (ADR 0013 decision 10): a real colour not on this plant's list is
    # matched onto an existing catalogue name; confirming a name the plant
    # does not list yet offers it there. Never a new colour name.
    "COLOR_NOT_OFFERED": "ALIAS_COLOR",
    # T41 (D-31): one panel spelling onto an existing zone of that model.
    # ZONE_NOT_VALID_FOR_MODEL is deliberately absent: a zone another model
    # owns is not taught onto this one.
    "UNKNOWN_CHECKZONE": "ALIAS_CHECKZONE",
    # T61 / T78 (D-78-31): the Engineer picks which model a held Film sheet
    # is; an Admin approves and the sheet is replayed. The pickable set and
    # the teachable tokens are on `film_model` below -- not in `candidates`,
    # which stays the flat per-cell catalogue list the other kinds use.
    "FILM_MODEL_UNRESOLVED": "FILM_MODEL",
}


class BatchReviewOut(StrictModel):
    """What a reviewer sees before committing (`02-PIPELINE.md` section 7)."""

    batch: BatchOut
    reject_reasons: dict[str, int] = Field(
        description="Counts by reject_log.reject_reason for this batch."
    )
    unidentified_rows: int
    staged_rows: int
    review_rows: int = Field(
        default=0,
        description=(
            "Rows in the persisted review projection: one per source row, "
            "whatever its disposition (T18)."
        ),
    )
    review_dispositions: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Projection rows by disposition: LOAD, DUPLICATE, REJECT, "
            "QUARANTINE, and (T26) AGGREGATE_ROW -- a report roll-up such as "
            "a [All] hierarchy row, preserved and disclosed as a count and "
            "never written to wavescan. Aggregates are outside the balance "
            "equation, exactly as a blank row already is."
        ),
    )
    commit_blockers: list[str] = Field(
        default_factory=list,
        description=(
            "Stable tokens naming why this batch cannot be committed right "
            "now: NOT_PENDING_REVIEW, UNBALANCED, UNKNOWN_TEMPLATE, "
            "UNVERIFIED_PROFILE, NO_REVIEW_PROJECTION, "
            "VEHICLE_IDENTITY_MISSING, and (T26) UNREVIEWED_HEADER, "
            "DUPLICATE_LOGICAL_FIELD, PAINTLINE_MISSING, "
            "OUT_OF_SCOPE_SHEET, UNKNOWN_DATA_SHEET, AGGREGATE_ONLY_SHEET. "
            "Empty if and only if committable is true."
        ),
    )
    committable: bool = Field(
        description=(
            "True only when committing right now would succeed: a balanced "
            "PENDING_REVIEW batch with no commit_blockers."
        )
    )
    held_labels: list[HeldLabelGroup] = Field(
        description=(
            "Distinct held spellings (REJECT / QUARANTINE) grouped by "
            "reason, column and raw value, with counts. Present on "
            "PENDING_REVIEW and on a committed remainder. Catalogue "
            "candidates are existing codes only. Empty when nothing is held."
        ),
    )


class BatchPage(StrictModel):
    items: list[BatchOut]
    page: PageInfo


class UploadedSheet(StrictModel):
    filename: str
    sheet: str
    load_id: int
    status: BatchStatus
    detail: str


class UploadedSkippedSheet(StrictModel):
    filename: str
    sheet: str
    reason: str


class UploadAccepted(StrictModel):
    accepted_files: int
    skipped_sheets: list[UploadedSkippedSheet] = Field(default_factory=list, description="Out-of-scope sheets recorded on their workbook, without a batch.")
    batches: list[UploadedSheet] = Field(
        description=(
            "One per in-scope or unreadable data sheet. Out-of-scope sheets "
            "are recorded under skipped_sheets on the workbook (RO19)."
        )
    )
    note: str = Field(
        default=(
            "Parsing runs in the background. Poll GET /api/v1/batches/{load_id} "
            "until the status leaves RUNNING, then commit a PENDING_REVIEW batch."
        )
    )


class CommitResult(StrictModel):
    load_id: int
    status: BatchStatus
    measurements_inserted: int
    counts: BatchCountsOut
    audit_action: str = Field(
        default="batch.commit",
        description="The audit_event written in the same transaction.",
    )
