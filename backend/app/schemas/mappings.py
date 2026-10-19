"""Mapping proposal DTOs.

A proposal is the whole reason this platform does not guess. `AGENTS.md`
rule 6: "Never guess plant, model, colour, zone, or column mapping.
Propose -> Admin approve -> replay. Similarity scores are advisory." These
shapes are that sentence made into a contract.

Two things the schema enforces that a comment could not:

* **`logical_field` is an enumeration, not a string.** It is exactly
  `domain.reader.STAGED_FIELDS`, imported rather than retyped, so a proposal
  cannot name a column the staging table has no home for. T08's escalation
  list asks whether that set is enumerable from the reader without inventing
  names; it is, and this is where it is read.
* **`similarity` is advisory and says so.** Nothing in this package or in
  `services/mapping.py` branches on its value.

Every model inherits `StrictModel`, so an unknown key in a payload is a 422
rather than a field silently ignored -- which for a mapping proposal is the
difference between "the Admin approved what you meant" and "the Admin
approved what parsed".
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.domain.held_label_copy import is_empty_identity_sentinel
from app.domain.film_header import LAYER_FIELDS, NON_FACT_FIELDS
from app.domain.reader import STAGED_FIELDS, normalise_header
from app.domain.references import normalise_alias
from app.schemas.common import PageInfo, StrictModel

#: Every kind `proposed_mapping.kind`'s CHECK constraint allows
#: (`01-DATA-MODEL.md` §6.7). A read can return any of them, because T04 rows
#: already exist and a later task will add the rest.
ProposalKind = Literal[
    "COLUMN", "ZONE", "ALIAS_COLOR", "ALIAS_MODEL",
    "ALIAS_PLANT", "ALIAS_CHECKZONE", "ALIAS_PAINTLINE",
    # T61 / T78 (D-78-31): one Film sheet's model, Engineer -> Admin.
    "FILM_MODEL",
]

#: What is implemented. The others are declared, accepted by the route, and
#: answered 501 -- the same reserved pattern the mutating routes have used
#: since T03.
#:
#: `ALIAS_COLOR` is **identity only** (finish-batch spec H6 / S12): a
#: spelling at a plant maps to an existing `ref_color.color_name`. It does
#: not close D2. Colour-family / standards stay 501.
#:
#: T29 adds `ZONE`, as the P703 spec section 5 contract and nothing looser:
#: one proposal is one complete, owner-proved 32-row set for one plant and
#: one P703 model. It does **not** close D5 -- approving an FVL set stores
#: maps and flips no plant.
#:
#: T41 adds `ALIAS_CHECKZONE` (ADR 0013 decision 10, T39-CONTEXT D-31): one
#: Excel panel spelling at one plant x model onto an **existing** zone_code
#: on that model's `ref_model_zone` list. One row, Engineer, never a mint.
#: A complete owner-proved set is still `ZONE` (Admin / named owner).
#:
#: T86 adds a second `ZONE` payload -- the guided panel-match set
#: (`ZonePanelMatchPayload`, key `matches`). N pairs a person confirmed on
#: the match screen, applied all-or-none by an Admin, which may also retire
#: the block of live panels the owner says it supersedes (D-86-2). It is
#: still `ZONE`, still atomic, and still Admin-approved; what it is not is
#: a named owner's proved whole-catalogue pack.
IMPLEMENTED_KINDS: tuple[str, ...] = (
    "COLUMN", "ALIAS_MODEL", "ZONE", "ALIAS_COLOR", "ALIAS_CHECKZONE",
    "FILM_MODEL",
)

#: The P703 family (spec S2). ZONE completeness is the named model's
#: `ref_model_zone` catalogue, not this list. Leftover programs keep their
#: own catalogues; they are not Ranger aliases.
P703_MODEL_CODES: tuple[str, ...] = (
    "P703 DBL RANGER",
    "P703 DBL RAPTOR",
    "P703 DBL SUPER DUTY",
)

ProposalStatus = Literal["PROPOSED", "APPROVED", "REJECTED"]

#: The logical fields a sheet column may be mapped to. Imported from the
#: reader so the two can never disagree.
#: RO18: the FilmThickness vocabulary a Film header may be taught onto (the
#: fields `ref_column_alias` already holds for that domain).
FILM_COLUMN_FIELDS = ("location", "date", "color", "job", "vin", *LAYER_FIELDS, *NON_FACT_FIELDS)
LogicalField = Literal[STAGED_FIELDS + FILM_COLUMN_FIELDS]  # type: ignore[valid-type]


class ColumnPayload(StrictModel):
    """`COLUMN`: this header in the file means this logical field.

    Approving one inserts a `ref_column_alias` row, which is what turns an
    unknown template into a parseable one on the next replay
    (`01-DATA-MODEL.md` §6.3).
    """

    raw_header: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "The header cell as the file spells it. Stored normalised "
            "(lower, trimmed, '_' -> ' '), the same normalisation "
            "ref_column_alias.raw_header uses, so 'Check_Zone' and "
            "'check zone' are one alias and not two."
        ),
        examples=["check_zone"],
    )
    logical_field: LogicalField = Field(
        description=(
            "The staging column this header feeds. Chosen from the reader's "
            "own field list; a free string is refused."
        ),
        examples=["checkzone"],
    )
    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Why the proposer believes these are the same column.",
    )
    domain: Literal["WAVESCAN", "FILMTHICKNESS"] = Field(
        default="WAVESCAN",
        description=(
            "RO18: the vocabulary the header belongs to. A Film header "
            "(FILMTHICKNESS) may only name a Film field, a Wave Scan header "
            "only a Wave Scan field."
        ),
    )

    @model_validator(mode="after")
    def _field_in_its_domain(self) -> "ColumnPayload":
        fields = FILM_COLUMN_FIELDS if self.domain == "FILMTHICKNESS" else STAGED_FIELDS
        if self.logical_field not in fields:
            raise ValueError(
                f"{self.logical_field!r} is not a {self.domain} field; "
                f"choose one of {', '.join(fields)}"
            )
        return self

    @field_validator("raw_header")
    @classmethod
    def _normalise(cls, value: str) -> str:
        normalised = normalise_header(value)
        if not normalised:
            raise ValueError("raw_header is blank once normalised")
        return normalised


class ModelAliasPayload(StrictModel):
    """`ALIAS_MODEL`: this spelling in the file means this existing model.

    Approving one inserts a `ref_model_alias` row. It never creates a model:
    `model_code` must already be in `ref_model`, checked against the database
    at approve time and again by the foreign key.
    """

    raw_value: str = Field(
        min_length=1,
        max_length=200,
        description="The Model cell as the file spells it, e.g. 'P703 RAP'.",
        examples=["P703 RAP"],
    )
    model_code: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "An existing ref_model.model_code. This route never invents a "
            "model; onboarding one is a separate decision."
        ),
        examples=["U704"],
    )
    suggested_model: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Advisory. What unidentified_model.suggested_model guessed, "
            "copied in for the Admin to read. Never applied."
        ),
    )
    note: str | None = Field(default=None, max_length=2000)


class ColorAliasPayload(StrictModel):
    """`ALIAS_COLOR`: this spelling in the file means this existing colour.

    Approving one inserts a plant-scoped `ref_color_alias` row. It never
    creates a colour: `color_name` must already be in `ref_color`. Extra
    keys are refused (StrictModel), so a family/standards field cannot
    ride along and D2 stays closed.
    """

    raw_value: str = Field(
        min_length=1,
        max_length=200,
        description="The Color cell as the file spells it.",
        examples=["3HC Traction Green BC"],
    )
    color_name: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "An existing ref_color.color_name. This route never invents a "
            "colour; onboarding one is a named-owner catalogue decision."
        ),
        examples=["Traction Green"],
    )
    plant_code: str = Field(
        min_length=1,
        max_length=16,
        description=(
            "The plant that writes this spelling. Must match the batch's "
            "plant when load_id is set. Required when load_id is omitted "
            "so a committed remainder can still teach future files."
        ),
        examples=["AAT"],
    )
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("raw_value", "color_name", "plant_code")
    @classmethod
    def _strip(cls, value: str) -> str:
        return _not_blank(value)


class FilmModelPayload(StrictModel):
    """`FILM_MODEL`: which model one held FilmThickness sheet is (T61).

    D-78-30/31. The Engineer proposes, an Admin approves, and the approved
    proposal is the record replay reads for that `(load_id, source_sheet)`.
    There is no new table.

    `model_code` must be in the batch plant's **Film vocabulary**
    (`ref_film_model_alias` targets at that plant) and nothing else -- never
    a WaveScan reading, so `RAP` is never Raptor here (D-FT-08), and never a
    leftover program the plant has no Film list for (F8 / D-55-09).

    `raw_token` is optional and, when given, must be one of the
    **server-derived** `teachable_tokens` the held-label read published for
    this sheet. The client never sends free text. When the file and tab name
    gave two different models the hold is ambiguous, the sheet carries no
    teachable token, and so `raw_token` must be absent: the choice resolves
    that one sheet and teaches nothing.
    """

    plant: str = Field(
        min_length=1,
        max_length=16,
        description="The batch's plant. Must match the batch named by load_id.",
        examples=["FTM"],
    )
    load_id: int = Field(
        ge=1,
        description=(
            "The held Film batch. Must equal the proposal's own load_id -- "
            "the payload names the sheet, so it names its batch too."
        ),
    )
    source_sheet: str = Field(
        min_length=1,
        max_length=200,
        description="The tab this choice is for, exactly as the batch stores it.",
        examples=["Quick Summary"],
    )
    model_code: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "One of the plant's Film vocabulary codes, as published in the "
            "held label's film_model.choices. Anything else is 422."
        ),
        examples=["P703 SGL"],
    )
    raw_token: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional. One of this sheet's film_model.teachable_tokens. "
            "Approving then also writes ref_film_model_alias "
            "(plant, raw_token) -> model_code, so the next file with that "
            "token resolves by itself. The same model again is a no-op; a "
            "different model already taught for that token is 409 and is "
            "never overwritten."
        ),
        examples=["XX"],
    )
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("plant", "source_sheet", "model_code")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        return _not_blank(value)

    @field_validator("raw_token")
    @classmethod
    def _upper_token(cls, value: str | None) -> str | None:
        """Stored as `ref_film_model_alias` requires: upper, trimmed."""
        if value is None:
            return None
        cleaned = str(value).strip().upper()
        if not cleaned:
            raise ValueError("raw_token must not be blank; omit it instead")
        return cleaned


class CheckzoneAliasPayload(StrictModel):
    """`ALIAS_CHECKZONE`: this panel spelling, at this plant and model, is
    this existing zone (T41, D-31).

    Applying one writes **one** `ref_plant_zone_map` row with
    `proposal_method = 'ENGINEER_ALIAS'`. It never creates a zone: the
    `zone_code` must already be on `ref_model_zone` for `model_code` (checked
    by the service and by the table's `(model_code, zone_code)` foreign key).
    Extra keys are refused. A blank or `(None)` panel is never teachable.
    """

    raw_value: str = Field(
        min_length=1,
        max_length=200,
        description="The Checkzone cell as the file spells it.",
        examples=["07 RR DOOR UPR"],
    )
    zone_code: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "An existing ref_model_zone.zone_code for model_code. Use a value "
            "from the held label's candidates. Never minted."
        ),
        examples=["RRDOOR"],
    )
    plant_code: str = Field(
        min_length=1,
        max_length=16,
        description="The plant that writes this spelling. Must match the batch's plant.",
        examples=["AAT"],
    )
    model_code: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "The existing ref_model.model_code of the held rows (the held "
            "label's model_code)."
        ),
        examples=["U704"],
    )
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("raw_value", "zone_code", "plant_code", "model_code")
    @classmethod
    def _strip(cls, value: str) -> str:
        return _not_blank(value)

    @field_validator("raw_value")
    @classmethod
    def _not_empty_sentinel(cls, value: str) -> str:
        if is_empty_identity_sentinel(value) or not normalise_alias(value):
            raise ValueError(
                "a blank or (None) panel is not a spelling; it cannot be mapped"
            )
        return value


def _not_blank(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("must not be blank")
    return trimmed


class ZoneMappingRow(StrictModel):
    """One raw checkpoint label of one plant, and the canonical zone it is."""

    raw_zone_text: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "The Checkzone cell as the plant's file writes it, e.g. "
            "'25TGATE' or '01RHS Hood Rr28'. Stored normalised (trim + "
            "case-fold), the same key the cleaner already looks zone maps up "
            "by."
        ),
        examples=["25TGATE"],
    )
    raw_position: int | None = Field(
        default=None,
        ge=1,
        le=40,
        description=(
            "The plant-local number, if the label has one. Provenance only: "
            "sequence is never physical identity (spec S14)."
        ),
    )
    zone_code: str = Field(
        min_length=1,
        max_length=64,
        description="An existing ref_model_zone.zone_code for this model.",
        examples=["LTTAILGATE"],
    )

    @field_validator("raw_zone_text")
    @classmethod
    def _normalise(cls, value: str) -> str:
        normalised = normalise_alias(value)
        if not normalised:
            raise ValueError("raw_zone_text is blank once normalised")
        return normalised


class ZoneSetPayload(StrictModel):
    """`ZONE`: one complete, owner-proved checkpoint map for one plant and model.

    **Atomic.** The set must cover exactly the model's `ref_model_zone`
    catalogue -- 32 rows for P703, each zone once, each raw label once -- and
    approving it writes all of it or none of it (spec section 5). A partial
    set is not a smaller mapping; it is an unproved one.

    **Proved.** `named_owner` is the plant or quality owner who signed the
    matrix, typed by a person; it is never filled in from the Admin who
    presses approve. `proof_hash` names the workbook or checkpoint document
    that proves it (S15). Keyword grouping, similarity and sequence may have
    *suggested* the rows; none of them is proof.
    """

    plant_code: str = Field(min_length=1, max_length=16, examples=["FVL"])
    model_code: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "An existing ref_model.model_code whose catalogue this set covers. "
            "P703 variants: " + ", ".join(P703_MODEL_CODES) + "."
        ),
        examples=["P703 DBL RANGER"],
    )
    mappings: list[ZoneMappingRow] = Field(
        description=(
            "Exactly ref_model.expected_zone_count rows (32 for P703) whose "
            "zone_code set equals the model's catalogue."
        ),
    )
    named_owner: str = Field(
        min_length=1,
        max_length=200,
        description="The plant/quality owner who verified the set. A person.",
    )
    proof_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 (lower-case hex) of the proving workbook or document.",
    )
    proof_document: str = Field(min_length=1, max_length=2000)
    method: str = Field(
        min_length=1,
        max_length=2000,
        description="How the owner decided. Text for a person; never executed.",
    )
    note: str = Field(min_length=1, max_length=2000)

    @field_validator(
        "plant_code", "model_code", "named_owner", "proof_document", "method", "note"
    )
    @classmethod
    def _strip(cls, value: str) -> str:
        return _not_blank(value)


class PanelRetireRequest(StrictModel):
    """D-86-2: the block of live panels the owner says this set supersedes.

    **The owner names it.** There is no rule in this platform for working
    out which of two blocks of panel names is the old one -- the walk
    numbers of the two blocks overlap, and that is the whole reason T86
    exists. So the zone_codes are typed in by the person who knows, and the
    reason is written by them too.

    Approving retires exactly those rows (`retired_at` + `retired_reason`).
    Nothing is deleted: old measurements stay readable, and only new
    uploads stop matching onto them.
    """

    zone_codes: list[str] = Field(
        min_length=1,
        description=(
            "Live `ref_plant_ws_point.zone_code` values at this plant x "
            "model. Each must be live now, and none may be a target of this "
            "same set -- retiring the panel you just matched onto would "
            "silently stop the map being read (T58 D-58-09)."
        ),
    )
    reason: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "Why these panels are superseded, in the owner's words. Stored "
            "on every retired row as `retired_reason`."
        ),
    )

    @field_validator("zone_codes")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        codes = [_not_blank(v) for v in value]
        duplicates = sorted({c for c in codes if codes.count(c) > 1})
        if duplicates:
            raise ValueError(
                "the same panel named twice: " + ", ".join(duplicates)
            )
        return codes

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return _not_blank(value)


class PanelMatchRow(StrictModel):
    """One confirmed pair: this file spelling IS this live panel.

    `raw_position` is the number the file's own label carries. It is stored
    as provenance and is not part of the key, the validation or the
    matching (D-86-3).
    """

    raw_zone_text: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "The Checkzone cell as the file spells it, from the match "
            "screen's `held_panels`. Stored normalised (trim + case-fold), "
            "the key the cleaner looks zone maps up by."
        ),
        examples=["06LFFENDER"],
    )
    raw_position: int | None = Field(
        default=None,
        ge=1,
        le=40,
        description="The label's own leading number. Provenance only.",
    )
    proposed_by_signal: Literal["name", "number", "exhaustion", "none"] = Field(
        default="none",
        description=(
            "T88 (G-88-6). Which signal proposed this pair on the match "
            "screen: `name`, `number`, `exhaustion`, or `none` when the "
            "person picked it themselves. Stored on the learned row, "
            "because an **exhaustion**-derived pair is the one that can be "
            "confidently wrong and has to be findable again afterwards "
            "(`scripts/audit_panel_identities.py`). The person still "
            "confirmed every pair; this records what argued for it."
        ),
    )
    zone_code: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "A live panel of this plant x model that the person chose. "
            "Never minted, and never derived from `raw_position`."
        ),
        examples=["LFFENDER"],
    )

    @field_validator("raw_zone_text")
    @classmethod
    def _normalise(cls, value: str) -> str:
        normalised = normalise_alias(value)
        if not normalised:
            raise ValueError("raw_zone_text is blank once normalised")
        if is_empty_identity_sentinel(value):
            raise ValueError(
                "a blank or (None) panel is not a spelling; it cannot be matched"
            )
        return normalised

    @field_validator("zone_code")
    @classmethod
    def _strip_zone(cls, value: str) -> str:
        return _not_blank(value)


class WalkPairRow(StrictModel):
    """One pair of a confirmed walk, with how specific its name is.

    **T90 (D-90-3).** `specificity` is the whole safety story of this task.
    A `specific` name -- `12LCPILLAR`, whose core is shared with nothing
    else in the sheet -- names a position by itself and is safe to learn
    forever, so it also appears in `matches` and becomes a permanent
    `ref_plant_zone_map` alias. A `rough` name -- one of five `HOOD`s,
    where the **number** is doing the identifying -- is confirmed for *this
    upload* and recorded here on the batch, and is **refused** in `matches`.
    The month the plant reshuffles its walk, a learned `01HOOD -> RRHOOD`
    would file a hood as the wrong hood with no error anywhere, and
    `AGENTS.md` opens by calling that worse than a crash.
    """

    raw_zone_text: str = Field(
        min_length=1,
        max_length=200,
        description="The panel name as the file spells it, from `walk.rows`.",
    )
    zone_code: str = Field(
        min_length=1,
        max_length=64,
        description="The canonical panel the person confirmed it is.",
    )
    specificity: Literal["rough", "specific"] = Field(
        description=(
            "From the read model's `walk.rows[].specificity`, never decided "
            "by the client: the server classifies it from the sheet's own "
            "name cores and refuses a `matches` row whose walk entry says "
            "`rough` (D-90-3)."
        )
    )
    rule: Literal["group_ordinal", "walk_number", "none"] = Field(
        default="none",
        description=(
            "Which structural rule proposed it, recorded so a wrong one can "
            "be found again. The person still confirmed every pair."
        ),
    )
    attention: Literal["yellow", "red"] = Field(
        default="red",
        description=(
            "The colour the row carried when it was confirmed. There is no "
            "green (D-90-6)."
        ),
    )

    @field_validator("raw_zone_text")
    @classmethod
    def _normalise_walk_raw(cls, value: str) -> str:
        normalised = normalise_alias(value)
        if not normalised:
            raise ValueError("raw_zone_text is blank once normalised")
        return normalised

    @field_validator("zone_code")
    @classmethod
    def _strip_walk_zone(cls, value: str) -> str:
        return _not_blank(value)


class WalkConfirmation(StrictModel):
    """T90 (D-90-5, D-90-11): the whole walk a person confirmed, on the batch.

    It is recorded against the upload that was reviewed and **nowhere
    else**. No new reference table and no migration: this block rides on
    the `ZONE` panel-match proposal, whose `load_id` *is* the batch.

    Why that beats a reference table, and it is not a style preference:
    `domain/cleaner.py` resolves a panel name from `ReferenceData` and
    nothing else, and `load_reference_data` builds `ReferenceData` from
    `ref_*` tables and nothing else. Neither can reach a `proposed_mapping`
    row or a `load_batch`, so a rough label **structurally cannot** leak
    into automatic resolution -- the same choice T87 made with its
    column-scoped `GRANT`, a guarantee rather than a promise. A test
    asserts the resolution path has no route to it.

    A later upload of the same `(plant, model, fingerprint)` pre-fills from
    the most recent of these and still asks for one click (D-90-5).
    """

    fingerprint: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "The ordered sequence of panel **groups**, `|`-joined, exactly "
            "as the read model's `walk.fingerprint` gives it (D-90-4). Not "
            "the spellings: a respelling must not invalidate a confirmed "
            "walk, and a reshuffle must."
        ),
    )
    pairs: list[WalkPairRow] = Field(
        min_length=1,
        description="Every pair of the walk the person confirmed, rough and specific.",
    )

    @field_validator("fingerprint")
    @classmethod
    def _strip_fingerprint(cls, value: str) -> str:
        return _not_blank(value)

    @model_validator(mode="after")
    def _one_pair_per_name(self):
        names = [pair.raw_zone_text for pair in self.pairs]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(
                "the same name confirmed twice in one walk: " + ", ".join(repeated)
            )
        return self


class ZonePanelMatchPayload(StrictModel):
    """`ZONE`, T86 shape: one guided panel-match set for one plant x model.

    The second payload `ZONE` accepts, told apart from T29's
    :class:`ZoneSetPayload` by carrying `matches` where that one carries
    `mappings` (`services/mapping.py` `_zone_payload_model`). The two are
    different records of different things and must not be confused:

    * :class:`ZoneSetPayload` is a **named owner's proved pack** -- the whole
      of one model's `ref_model_zone` catalogue, with a proof hash;
    * this one is **N pairs a person confirmed on the match screen**, N of
      the file's own spellings onto live panels, Engineer -> Admin (D-86-4).
      It mints nothing and proves nothing, so it carries no proof hash; what
      it carries instead is who decided and how.

    **Atomic** (T86 section 3.3): approval writes all N rows and the
    retirement in one transaction, or it writes nothing.
    """

    plant_code: str = Field(min_length=1, max_length=16, examples=["FTM"])
    model_code: str = Field(
        min_length=1,
        max_length=64,
        description="An existing ref_model.model_code the held rows are on.",
        examples=["P703 DBL RANGER"],
    )
    load_id: int = Field(
        ge=1,
        description=(
            "The held batch the spellings were read from. Required: a match "
            "set answers one file's question, and replay is how the answer "
            "reaches those rows."
        ),
    )
    matches: list[PanelMatchRow] = Field(
        description=(
            "The pairs that become **permanent** `ref_plant_zone_map` "
            "aliases. Each spelling once and each live panel once -- two "
            "spellings onto one panel is the August 64-identity defect in "
            "advance, so it is refused. **T90 (D-90-3):** only names whose "
            "own spelling identifies a panel belong here; a name the set's "
            "own `walk` calls rough is refused. It may therefore be empty, "
            "but only when `walk` carries the confirmation instead -- a set "
            "that records nothing at all is not a decision."
        ),
    )
    retire: PanelRetireRequest | None = Field(
        default=None,
        description=(
            "D-86-2. The block of live panels the owner says this set "
            "supersedes, or null when they say nothing is superseded. The "
            "code never fills this in."
        ),
    )
    walk: WalkConfirmation | None = Field(
        default=None,
        description=(
            "T90 (D-90-11). The whole confirmed walk -- its fingerprint and "
            "every pair, rough and specific -- recorded on this batch. "
            "`matches` carries only the **specific** pairs, because only "
            "those may become permanent aliases (D-90-3); a `matches` row "
            "whose walk entry says `rough` is refused and nothing is "
            "written. Null for a set confirmed without a structural reading."
        ),
    )
    decided_by: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "The person who said which physical panel each name is. Typed by "
            "a human; never the signed-in user filled in automatically, "
            "because the Engineer at the screen may be relaying the plant's "
            "answer rather than giving their own."
        ),
    )
    method: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "How they decided -- the document, the walk, the conversation. "
            "Text for a person; never executed."
        ),
    )
    note: str = Field(min_length=1, max_length=2000)

    @field_validator(
        "plant_code", "model_code", "decided_by", "method", "note"
    )
    @classmethod
    def _strip(cls, value: str) -> str:
        return _not_blank(value)

    @model_validator(mode="after")
    def _records_something(self):
        """At least one of the two halves, or this set decides nothing.

        **T90 (D-90-3 / D-90-11).** `matches` may be empty, because a walk
        every one of whose names is rough has no permanent alias to write --
        August's numbered block is 28 rough names and 4 specific ones, and a
        month could be all 28. What it still has is the walk, recorded on
        this batch, which is the whole of D-90-11. What is refused is a set
        that records neither: that is not a decision, it is a no-op, and a
        silent no-op in this platform is a defect.
        """
        if not self.matches and not (self.walk and self.walk.pairs):
            raise ValueError(
                "this set records nothing: `matches` is empty and there is "
                "no confirmed `walk` either. Send the pairs that become "
                "permanent aliases, the walk that is confirmed on this "
                "batch, or both."
            )
        return self


class ProposalCreate(StrictModel):
    """The Engineer's request body.

    `payload` is a free object here and a strict model one layer down, in
    `services/mapping.py`, because which model applies depends on `kind` --
    and an unimplemented `kind` has to reach the service to be answered 501
    rather than being rejected as a bad enum.
    """

    kind: ProposalKind = Field(
        description=(
            "COLUMN, ALIAS_MODEL, ZONE, ALIAS_COLOR (identity) and "
            "ALIAS_CHECKZONE (one panel spelling onto an existing zone, T41) "
            "are implemented. ALIAS_PLANT and ALIAS_PAINTLINE are declared by "
            "the data model and answer 501."
        )
    )
    load_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "The batch this proposal is about. Required for COLUMN and "
            "ALIAS_MODEL (and every kind still reserved): replay is the only "
            "way an approved alias reaches data. Optional for ZONE when "
            "payload.plant_code names the plant -- an FVL set has nothing "
            "committable to replay. Optional for ALIAS_COLOR when "
            "payload.plant_code names the plant, so a committed remainder "
            "can teach future files without replaying facts. Same for "
            "ALIAS_CHECKZONE (T41). When given, "
            "the batch must be filed under that plant."
        ),
    )
    payload: dict = Field(
        description=(
            "Shape depends on kind. See ColumnPayload / ModelAliasPayload / "
            "ZoneSetPayload / ZonePanelMatchPayload / ColorAliasPayload / "
            "CheckzoneAliasPayload / FilmModelPayload. ZONE takes two "
            "shapes: an owner-proved whole-catalogue pack (ZoneSetPayload, "
            "key `mappings`, T29) or a guided panel-match set "
            "(ZonePanelMatchPayload, key `matches`, T86). For FILM_MODEL "
            "(T61) that is "
            "{plant, load_id, source_sheet, model_code, raw_token?, note?}, "
            "where model_code comes from the held label's film_model.choices "
            "and raw_token, if sent, from its film_model.teachable_tokens."
        ),
    )
    similarity: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Advisory score from the mapping engine, 0-1. Recorded for the "
            "Admin to read. Nothing branches on it and no threshold "
            "auto-applies anything (docs/02-PIPELINE.md section 4)."
        ),
    )

    @model_validator(mode="after")
    def _load_id_rule(self):
        """`load_id` stays required except ZONE and identity ALIAS_COLOR.

        T29 relaxes ZONE: a set may omit the batch when its payload names
        the plant, because FVL has no committable batch to replay.

        Finish-batch H1/H2 relaxes ALIAS_COLOR the same way: a committed
        remainder cannot be replayed (ADR 0005), but the spelling still
        needs to teach the next file. `payload.plant_code` is then the
        plant the alias is scoped to.
        """
        if self.kind == "ZONE" and "matches" in self.payload and self.load_id is None:
            # T86: a guided panel-match set answers one file's question, so
            # the batch is not optional the way an owner-proved pack's is.
            raise ValueError(
                "load_id is required for a T86 panel-match set: it names the "
                "held file whose spellings were matched, and replay is how "
                "the answer reaches those rows"
            )
        if self.load_id is not None:
            return self
        if self.kind not in ("ZONE", "ALIAS_COLOR", "ALIAS_CHECKZONE"):
            raise ValueError(
                "load_id is required: a proposal with no batch has nothing to "
                "replay, and replay is the only way an approved alias reaches "
                "data"
            )
        if not str(self.payload.get("plant_code") or "").strip():
            raise ValueError(
                f"a {self.kind} proposal with no load_id must name "
                "payload.plant_code"
            )
        return self


class ProposalOut(StrictModel):
    id: str
    kind: ProposalKind
    payload: dict
    load_id: int | None
    status: ProposalStatus
    similarity: Decimal | None = Field(description="Advisory only.")
    proposed_by: str | None = Field(description="app_user.id of the proposer.")
    decided_by: str | None = Field(description="app_user.id of the deciding Admin.")
    created_at: datetime
    decided_at: datetime | None


class ProposalPage(StrictModel):
    items: list[ProposalOut]
    page: PageInfo


class ReplayOut(StrictModel):
    """What approving a proposal did to the batch."""

    load_id: int
    previous_status: str
    status: str = Field(description="RUNNING: the worker re-parses stored bytes.")
    cleared: dict[str, int] = Field(
        description=(
            "Rows removed from each staging table so the batch could be "
            "re-derived. Never includes wavescan or load_batch: the reset "
            "refuses outright when the batch has measurements."
        )
    )
    job_id: int


class ApprovalResult(StrictModel):
    proposal: ProposalOut
    applied_to: str = Field(
        description=(
            "The reference table the approved mapping was written to: "
            "ref_column_alias, ref_model_alias, ref_color_alias, or "
            "ref_plant_zone_map (ZONE)."
        )
    )
    replay: ReplayOut | None = Field(
        description=(
            "Null only when the proposal carries no load_id. Replay stops at "
            "PENDING_REVIEW; committing stays an Engineer action."
        )
    )
    audit_action: str = Field(
        default="mapping.approve",
        description="The audit_event written in the same transaction.",
    )
    note: str = Field(
        default=(
            "No measurement was written. Poll GET /api/v1/batches/{load_id} "
            "until the status leaves RUNNING, then commit a PENDING_REVIEW "
            "batch as an Engineer."
        )
    )
