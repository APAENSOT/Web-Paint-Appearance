"""The ingest service: the single parser.

`02-PIPELINE.md` §10 is blunt about why this file exists at all -- "It must
call the **same** `services/ingest.py` as HTTP upload. Two parsers = drift."
So the HTTP routes, the worker, and anything an operator runs later all enter
here and nowhere else.

Three phases, and the split between them is the whole design:

**1. `accept_upload` (in the request).** Door checks, hash, read *header rows
only*, check the workbook against the `expected_plant` the request declared,
refuse a plant that is not onboarded, store the bytes, open one `load_batch`
per sheet, enqueue a job. Nothing is interpreted. The two things this phase
must get right are that a refusal leaves no batch behind, and that it leaves
no stored object either -- which is why the plant gate runs before
`RawStore.put` and not after it (T17).

**2. `process_batch` (in the worker).** Read the stored bytes, stage them
verbatim, clean, dedup, write dispositions, count, and stop at
`PENDING_REVIEW`. **No measurement is written here.** A batch that has been
parsed but not committed has nothing in `wavescan`.

**3. `commit_batch` (in the request, Engineer).** Re-derive the plan from the
stored bytes, check it still matches what was reviewed, insert the LOAD rows,
write the audit event, move the batch to `COMMITTED` -- all in one
transaction.

**Why phase 3 re-derives instead of reading back what phase 2 decided.**
There is nowhere to put a pending measurement. `wavescan` is insert-only and
has no draft state, ADR 0005 forbids deleting a row that turned out not to be
wanted, and `stg_raw` holds text, not cleaned values. So the clean rows
cannot be parked between review and commit -- they have to be produced again
from the bytes, which is exactly the replay path `02-PIPELINE.md` §8
describes. The safeguard is that a re-derivation which disagrees with the
reviewed counts refuses the commit instead of quietly committing something
else.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import Connection

from app.core.config import Settings
from app.domain.cleaner import (
    AGGREGATE_SENTINELS, Aggregate, Cleaner, CleanResult, CleanRow,
    PlantNotOnboarded,
)
from app.domain.dedup import Deduplicator, DuplicateInfo
from app.domain.cleaner import (
    REASON_MONTH_UNKNOWN,
    Reject,
    month_question_detail,
    parse_month_answer,
)
from app.domain.film import (
    FilmCleanResult,
    FilmCleaner,
    FilmDuplicate,
    FilmReference,
    FilmRow,
    ModelResolution,
    REASON_FILM_JOB_UNUSUAL,
    REASON_FILM_MODEL_CONFLICT,
    REASON_FILM_NO_NAMED_POINTS,
    REASON_FILM_POINT_WAITING,
    REASON_FILM_TAIL_LABEL,
    REASON_FILM_NOT_A_POINT,
    REASON_FILM_DATE_DISAGREES,
    FILE_DATE_TOLERANCE_DAYS,
    file_name_date,
    film_date_question,
    REASON_FILM_WALK_UNKNOWN,
    REASON_LIMIT_ROW,
    fold_existing,
    ftm_filename_colour_token,
    ftm_filename_token,
    is_limit_row,
    normalise_location,
    not_a_point_detail,
    parse_film_date,
    real_identity,
    resolve_film_model,
    split_duplicates,
    stored_vehicle_ids,
)
from app.domain.film_header import (
    DOMAIN_FILMTHICKNESS, LAYER_FIELDS, SHEET_FILMTHICKNESS,
)
from app.domain.film_walk import (
    car_of,
    check_walks,
    model_conflict,
    model_conflict_detail,
    names_no_points,
    no_named_points_detail,
    read_job_no,
    tail_label_detail,
    walk_fingerprint,
    walk_mixed_detail,
    walk_starts,
)
from app.domain.reader import (
    DOMAIN_WAVESCAN,
    MEASURE_ALL,
    SHEET_OUT_OF_SCOPE,
    SHEET_UNKNOWN_DATA,
    SHEET_WAVESCAN,
    DuplicateFieldError,
    ReaderError,
    SheetTemplate,
    TemplateError,
    describe_film_sheet,
    describe_sheet,
    iter_rows,
    normalise_header,
    read_film_sheet,
    read_sheet,
    sha256_hex,
    sheet_names,
)
from app.domain.references import ReferenceData, normalise_alias
from app.repositories import (
    acknowledgements, audit, batches, ingest_jobs, measurements, overrides, profiles, workbook_uploads,
)
from app.repositories import filmthickness as film_repo
from app.repositories import mappings as mappings_repo
from app.repositories import worksheet as worksheet_repo
from app.repositories import reference as reference_repo
from app.services.raw_store import RawStore, key_for
from app.services.upload_guard import GuardLimits, UploadRejected, check_file, check_request_size

log = logging.getLogger("app.ingest")

#: Why a batch cannot be committed right now. Stable tokens: a client shows
#: them, a test asserts them, and `committable` is simply "this list is
#: empty". They are not error messages -- the message is written where the
#: refusal happens and quotes the same token.
BLOCKER_UNKNOWN_TEMPLATE = "UNKNOWN_TEMPLATE"
BLOCKER_UNVERIFIED_PROFILE = "UNVERIFIED_PROFILE"
#: T39 (ADR 0013 decision 2): no longer raised. A blank serial loads NULL
#: and the sheet is the vehicle. The token stays so older clients that list
#: it still type-check.
BLOCKER_VEHICLE_IDENTITY_MISSING = "VEHICLE_IDENTITY_MISSING"
BLOCKER_NOT_PENDING_REVIEW = "NOT_PENDING_REVIEW"
BLOCKER_UNBALANCED = "UNBALANCED"
BLOCKER_NO_REVIEW_PROJECTION = "NO_REVIEW_PROJECTION"
BLOCKER_WARNINGS_UNACKNOWLEDGED = "WARNINGS_UNACKNOWLEDGED"
#: T26 (spec S8-S10, S16, S18). Five more reasons a sheet is readable and
#: still must not become measurements. Each names something a *person*
#: decides: what an unmapped column means, which of two columns was meant,
#: which production line a vehicle ran on, what kind of sheet this is, and
#: whether a roll-up-only sheet has any real vehicle in it at all.
BLOCKER_UNREVIEWED_HEADER = "UNREVIEWED_HEADER"
BLOCKER_DUPLICATE_LOGICAL_FIELD = "DUPLICATE_LOGICAL_FIELD"
#: T39 (ADR 0013 decision 2): no longer raised; blank booth loads NULL.
BLOCKER_PAINTLINE_MISSING = "PAINTLINE_MISSING"
BLOCKER_OUT_OF_SCOPE_SHEET = "OUT_OF_SCOPE_SHEET"
BLOCKER_UNKNOWN_DATA_SHEET = "UNKNOWN_DATA_SHEET"
BLOCKER_AGGREGATE_ONLY_SHEET = "AGGREGATE_ONLY_SHEET"

#: The one field an approved profile may supply today (T18 locked decision 6).
#: A profile can say "this layout has no Plant column and that is known and
#: agreed"; it cannot supply a model, a colour, a zone or a serial, because
#: those are values, and guessing a value is what `AGENTS.md` rule 6 forbids.
PROFILE_SUPPLIED_FIELD = "plant"


class IngestError(RuntimeError):
    """An ingest step refused to proceed. The message is shown to the client."""


class DuplicateUpload(IngestError):
    """These exact bytes are already ingested (`02-PIPELINE.md` §3)."""

    def __init__(
        self, filename: str, prior: Sequence[dict], why: str | None = None
    ) -> None:
        listed = ", ".join(
            f"load_id {p['load_id']} ({p['source_file']} [{p['source_sheet']}], "
            f"{p['status']})"
            for p in prior
        )
        super().__init__(
            f"{filename!r} has already been ingested: its SHA-256 matches "
            f"{listed}. Nothing was stored. "
            + (
                why
                or "A corrected re-send must be a different file; identical "
                   "bytes are the same evidence."
            )
        )
        self.filename = filename
        self.prior = list(prior)


@dataclass(frozen=True)
class SheetPlantScan:
    """What one sheet's Plant column says, read before anything is stored.

    T17: the upload declares an ``expected_plant`` and the server checks the
    workbook against it at the door. This is the evidence that check
    produced, carried through to the ``batch.upload`` audit event so the
    fill is disclosed rather than silent.
    """

    sheet: str
    plant_column_present: bool
    blank_cells: int
    first_blank_row: int | None
    rows_scanned: int
    #: T39. Plant texts that do not mean the page plant, as written. The
    #: file is still stored and its rows are held as PLANT_MISMATCH until an
    #: Engineer answers (ADR 0013 decision 3).
    to_confirm: tuple[str, ...] = ()
    rows_to_confirm: int = 0


@dataclass
class SheetOutcome:
    filename: str
    sheet: str
    load_id: int | None
    status: str
    detail: str = ""


@dataclass(frozen=True)
class ReopenRequest:
    """Identical bytes of a workbook that is out of the workflow (T25).

    Every prior sheet is ABANDONED or retired, filed under the plant this
    upload declared, and the caller's role may bring each of them back. The
    ingest service decides that and writes nothing for it: no object-store
    put, no `load_batch` INSERT, no job. Changing a batch's status belongs
    to the service that retires batches, so the upload route hands these
    `load_id`s there, in the same transaction.
    """

    filename: str
    digest: str
    prior: tuple[dict, ...]

    @property
    def load_ids(self) -> list[int]:
        return [int(p["load_id"]) for p in self.prior]


@dataclass
class UploadOutcome:
    file_hash_by_name: dict[str, str] = field(default_factory=dict)
    sheets: list[SheetOutcome] = field(default_factory=list)
    skipped_sheets: list[dict] = field(default_factory=list)
    #: T25. Files whose bytes are already held by retired batches.
    reopen: list[ReopenRequest] = field(default_factory=list)

    @property
    def load_ids(self) -> list[int]:
        return [s.load_id for s in self.sheets if s.load_id is not None]


class ProfilePublishRefused(IngestError):
    """Owner-publish refused, with nothing written (T26, spec S20).

    Carries its own status code so the router never re-derives an outcome
    from a message string -- the same pattern `MappingError` uses.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class SheetNotWaveScan(TemplateError):
    """This sheet is not a WaveScan sheet at all (T26 / spec S10).

    Also a `TemplateError` subclass, for the same reason `ProfileMissing` is:
    the caller's answer is "stop, do not read a data row". What differs is
    what a person is being told. A Methods or Color Data sheet is preserved
    evidence of another domain, not a WaveScan layout somebody broke, and an
    Admin is not asked to map its headers. A data-like sheet that speaks part
    of this vocabulary is the genuinely ambiguous case and blocks for
    classification.
    """

    @property
    def sheet_class(self) -> str:
        return self.template.sheet_class


class FilmNamesNoPoints(TemplateError):
    """T99 (D-99-9). Every Location on this Film sheet is ``Point NNN``.

    A `TemplateError` subclass because the answer is the same -- stop, do not
    read a data row -- but the reason is neither a missing header nor another
    domain: the sheet is a FilmBuild report whose point names were never
    written. There is nothing to resolve and nothing to propose. Matching a
    reading to a point by its walk position is the one thing `domain/film`
    has refused to do since T46 (F10), so the sheet is refused with a plain
    sentence instead, and nobody is asked a question they cannot answer.
    """


class ProfileMissing(TemplateError):
    """No active template profile for this `(domain, plant, signature)`.

    A subclass of `TemplateError` on purpose: the caller already refuses a
    template it cannot read by moving the batch to `REJECTED_TEMPLATE` and
    leaving an Admin a proposal, without parsing a data row, and an
    unrecognised *layout* is the same answer as an unrecognised *header*.
    What differs is the reason, and that is carried in the proposal payload.
    """


@dataclass(frozen=True)
class ParseContext:
    """Which profile and which layout produced a plan.

    Carried beside the plan rather than looked up twice, so the projection,
    the batch row and the commit check all name the same profile.
    """

    template: SheetTemplate
    profile: dict | None

    @property
    def profile_id(self) -> int | None:
        return self.profile["profile_id"] if self.profile else None

    @property
    def fingerprint(self) -> str:
        """The **exact ordered-layout** hash. Provenance, not the key (S7)."""
        return self.template.fingerprint

    @property
    def semantic_signature(self) -> str:
        """What actually selected the profile (T26 / M5 as amended)."""
        return self.template.semantic_signature

    @property
    def domain(self) -> str:
        return self.template.domain

    @property
    def sheet_class(self) -> str:
        return self.template.sheet_class

    @property
    def unreviewed_headers(self) -> tuple[str, ...]:
        return self.template.unreviewed_headers

    @property
    def profile_free(self) -> bool:
        """T42: no profile, but a WaveScan tab readable on its required columns.

        Derived from the template alone, so upload, worker, commit and
        replay all reach the same answer from the same bytes.
        """
        t = self.template
        return (
            self.profile is None
            and t.sheet_class in (SHEET_WAVESCAN, SHEET_FILMTHICKNESS)
            and not t.duplicates
            and not t.missing_for_profile_free
        )

    @property
    def is_film(self) -> bool:
        """T46: this sheet was read under the FilmThickness vocabulary."""
        return self.template.domain == DOMAIN_FILMTHICKNESS


@dataclass
class Plan:
    """What committing this batch would write."""

    clean: list[CleanRow]
    duplicates: list[DuplicateInfo]
    result: CleanResult
    rows_in_file: int
    #: T21: source row -> the measure fields a current `review_override`
    #: replaced on that LOAD row. Empty when nobody has overridden anything.
    overridden: dict[int, tuple[str, ...]] = field(default_factory=dict)

    @property
    def aggregates(self) -> list[Aggregate]:
        """Report roll-up rows (T26 / spec S16).

        Deliberately **outside** `rows_in_file`, exactly as an entirely blank
        row already is. A `[All]` row is not a row of this file's data that
        went one of four ways; it is the pivot's own summary of rows that are
        also in the file. Counting it would either break the balance check or
        force thousands of rows behind the `REJECTED_ROWS` acknowledgement,
        and the design asks for neither ("not a thousands-row ack flood").
        It is still staged, still projected as `AGGREGATE_ROW`, and still
        disclosed as a count.
        """
        return self.result.aggregates

    @property
    def counts(self) -> batches.BatchCounts:
        return batches.BatchCounts(
            rows_in_file=self.rows_in_file,
            rows_loaded=len(self.clean),
            rows_duplicate=len(self.duplicates),
            rows_rejected=len(self.result.rejects),
            rows_quarantine=len(self.result.unidentified),
        )


@dataclass
class FilmPlan:
    """What committing a FilmThickness sheet would write (T46).

    Counts are **source rows**, exactly as for WaveScan, so
    `ck_batch_balance` holds unchanged: a LOAD row becomes one fact per
    numeric layer, and the fact count is reported beside the row counts.
    """

    clean: list[FilmRow]
    duplicates: list[FilmDuplicate]
    result: FilmCleanResult
    rows_in_file: int
    model: ModelResolution
    plant: str
    overridden: dict[int, tuple[str, ...]] = field(default_factory=dict)

    @property
    def aggregates(self):
        return self.result.aggregates

    @property
    def facts(self) -> int:
        return sum(len(r.layers) for r in self.clean)

    @property
    def counts(self) -> batches.BatchCounts:
        return batches.BatchCounts(
            rows_in_file=self.rows_in_file,
            rows_loaded=len(self.clean),
            rows_duplicate=len(self.duplicates),
            rows_rejected=len(self.result.rejects),
            rows_quarantine=len(self.result.held),
        )


# =====================================================================
class IngestService:
    def __init__(self, settings: Settings, store: RawStore) -> None:
        self.settings = settings
        self.store = store
        self.limits = GuardLimits(
            max_file_bytes=settings.upload_max_file_bytes,
            max_files=settings.upload_max_files,
            max_uncompressed_bytes=settings.upload_max_uncompressed_bytes,
            max_compression_ratio=settings.upload_max_compression_ratio,
        )

    # -----------------------------------------------------------------
    # phase 1: the request
    # -----------------------------------------------------------------
    def accept_upload(
        self,
        conn: Connection,
        files: Sequence[tuple[str, bytes]],
        *,
        expected_plant: str,
        actor_user_id: str,
        correlation_id: str | None = None,
        may_restore_committed: bool = False,
    ) -> UploadOutcome:
        """Door checks, plant gate, storage, one batch per sheet, one job each.

        Every check runs across *all* files before anything is written, so a
        request containing one bad file creates no batches at all rather than
        half a set.

        **T17 adds the plant gate, and where it sits is the whole point.**
        The caller uploaded from one plant's page and said so; that claim is
        ``expected_plant``. It is checked against ``ref_plant``, then against
        every sheet's Plant column, and only then are bytes stored and
        batches opened. A workbook that names another plant therefore leaves
        no object in the store and no ``load_batch`` row to explain -- the
        same property the door checks already had, extended to the one
        mistake a door check cannot see: a perfectly valid workbook filed
        under the wrong plant.

        Order of refusals, and why:

        1. size / count / magic / zip -- hostile bytes, before openpyxl.
        2. ``expected_plant`` unknown to ``ref_plant`` -- the claim itself is
           not a plant.
        3. T39 (ADR 0013): a Plant cell that starts with the page plant is
           that plant; any other nonblank Plant text is **not** a refusal. The
           file is stored, its batches open on the page plant, and those rows
           are held as PLANT_MISMATCH until an Engineer answers.
        4. ``expected_plant`` known but not onboarded -- 422 (D5).
        5. duplicate bytes -- 409. After the plant gate, so a wrong-plant
           upload cannot produce a duplicate lookup side effect either.

        **T25 splits step 5.** Identical bytes are still never stored twice
        and never open a second batch; what changes is the answer when every
        batch already holding them is out of the workflow:

        * any prior sheet live (PENDING_REVIEW, RUNNING, COMMITTED, FAILED,
          REJECTED_TEMPLATE) -> 409, as before;
        * prior sheets filed under another plant -> 409;
        * a prior sheet retired after commit and the caller not an Admin
          (``may_restore_committed`` false) -> 409 for the whole request,
          even when its siblings are only ABANDONED;
        * otherwise -> a `ReopenRequest` on the outcome, for the upload route
          to hand to the service that owns batch status. Nothing is written
          here for it.

        Every file is classified before anything is written, so one live
        duplicate still refuses a request that also carries new files.
        """
        check_request_size(len(files), self.limits)
        for filename, data in files:
            check_file(filename, data, self.limits)

        ref = reference_repo.load_reference_data(conn)
        film = film_repo.load_film_reference(conn)
        cleaner = Cleaner(ref, self._allowed_plants(ref))
        scope = self._resolve_expected_plant(cleaner, ref, expected_plant)

        # Nothing below writes anything until every file has been described
        # and its Plant column scanned.
        scoped = Cleaner(ref, self._allowed_plants(ref), expected_plant=scope)
        prepared: list[
            tuple[str, bytes, str, list[SheetTemplate], dict[str, SheetPlantScan]]
        ] = []
        for filename, data in files:
            templates = self._describe(filename, data, ref, film)
            scans = self._scan_plant_cells(scoped, data, templates)
            prepared.append((filename, data, sha256_hex(data), templates, scans))

        self._refuse_unonboarded_plant(cleaner, files, scope)

        outcome = UploadOutcome()
        reopened: set[str] = set()
        for filename, _, digest, _, _ in prepared:
            all_prior = batches.find_by_hash(conn, digest)
            prior = [p for p in all_prior if p.get("sheet_class") != SHEET_OUT_OF_SCOPE]
            other_plants = sorted({p["plant_code"] for p in all_prior if p["plant_code"] != scope})
            if other_plants:
                raise DuplicateUpload(
                    filename,
                    all_prior,
                    f"These bytes are filed under {', '.join(other_plants)}, not {scope}.",
                )
            if prior:
                outcome.reopen.append(
                    _reopenable(filename, digest, prior, scope, may_restore_committed)
                )
                reopened.add(digest)
            elif all_prior or workbook_uploads.unpurged(conn, digest):
                raise DuplicateUpload(filename, all_prior, "These bytes are already stored as workbook evidence.")

        for request in outcome.reopen:
            outcome.file_hash_by_name[request.filename] = request.digest

        for filename, data, digest, templates, scans in prepared:
            if digest in reopened:
                continue
            self.store.put(digest, data)
            outcome.file_hash_by_name[filename] = digest
            skips: list[dict] = []
            for template in templates:
                context = self._select_profile(
                    conn, scope, template, data=data,
                    alias_map=_alias_for(template, ref, film),
                )
                if context.sheet_class == SHEET_OUT_OF_SCOPE:
                    reason = (
                        "This sheet carries no Wave Scan vocabulary or FilmBuild header. "
                        "Its bytes and headers are kept as workbook evidence; no data row was read."
                    )
                    skips.append({"source_sheet": template.sheet, "reason": reason,
                                  "sheet_class": SHEET_OUT_OF_SCOPE, "raw_headers": template.as_json()})
                    outcome.skipped_sheets.append({"filename": filename, "sheet": template.sheet, "reason": reason})
                    continue
                outcome.sheets.append(
                    self._open_batch_for_sheet(
                        conn,
                        filename=filename,
                        digest=digest,
                        context=context,
                        expected_plant=scope,
                        scan=scans[context.template.sheet],
                        actor_user_id=actor_user_id,
                        correlation_id=correlation_id,
                    )
                )
            workbook_uploads.create(conn, plant_code=scope, file_hash=digest, source_file=filename,
                                    raw_store_key=key_for(digest), loaded_by=actor_user_id,
                                    skipped_sheets=skips)
            audit.record(conn, action="workbook.upload", entity_type="workbook_upload",
                         entity_id=f"{scope}:{digest}", actor_user_id=actor_user_id,
                         after={"plant_code": scope, "file_hash": digest, "source_file": filename,
                                "skipped_sheets": skips}, correlation_id=correlation_id)
        return outcome

    def _select_profile(
        self,
        conn: Connection,
        plant_code: str | None,
        template: SheetTemplate,
        *,
        data: bytes | None = None,
        alias_map=None,
    ) -> ParseContext:
        """Look up the active profile for this contract (T26, spec S7).

        The key is `(domain, expected_plant, semantic_signature)` -- never
        the filename, never a similarity score, and, since T26, never column
        order. FTM August and SAP July reorder the same twenty-one fields;
        under T18 each reorder minted a fingerprint nobody had approved and
        the sheet was refused. The ordered hash is still computed and still
        stored, as the record that the layout moved.

        Two things happen once a profile is found:

        * `fill_missing_plant` marks `plant` as supplied, which is what turns
          "this sheet has no Plant column" into a known layout whose plant
          comes from the declared scope (T18).
        * its **column policy** is applied, so headers a named owner approved
          ignoring stop counting as unreviewed extras (S9). That needs the
          bytes, because ignoring a column changes how the header row reads;
          without them the policy is skipped and the caller simply sees the
          extras it would have seen anyway -- never fewer.

        The signature used for the lookup is computed with **no** policy
        applied, which is what stops this being circular: a profile cannot be
        found by a signature that only that profile's own policy produces. If
        applying the policy then moved the signature, the profile ignores a
        column this domain recognises, and that is a policy the owner has to
        fix rather than something to resolve here -- so the profile is not
        applied and the sheet stays unknown.

        **T42 (L-02 / L-03, amends T39 D-35).** When no profile claims the
        exact contract, a WaveScan tab that maps every required column is
        still read -- on the profile-free contract (`_profile_free`). An
        optional column the seeded profile happened to carry (DOI, DU, Wa-We,
        B, Serial, Paintline) is not a new contract. An exact profile is
        still preferred when one exists (T26 unchanged).
        """
        profile = profiles.active_profile(
            conn, plant_code, template.semantic_signature, template.domain
        )
        if profile is None:
            return _profile_free(plant_code, template)

        ignored = profiles.ignored_headers(conn, profile["profile_id"])
        if ignored and data is not None:
            repolicied = _redescribe(data, template, alias_map, (), ignored)
            if repolicied.semantic_signature != template.semantic_signature:
                log.warning(
                    "column policy changes the semantic contract; not applied",
                    extra={
                        "detail": (
                            f"profile_id={profile['profile_id']} "
                            f"sheet={template.sheet} ignored={list(ignored)}"
                        )
                    },
                )
                return ParseContext(template=template, profile=None)
            template = repolicied

        extra_supplied: list[str] = []
        if template.domain == DOMAIN_FILMTHICKNESS:
            # A film layout's required fields come from its columns and its
            # PELT preamble; nothing is supplied by a profile (T46).
            return ParseContext(template=template, profile=profile)
        if profile["fill_missing_plant"]:
            extra_supplied.append(PROFILE_SUPPLIED_FIELD)
        if plant_code and not reference_repo.plant_requires_serial(conn, plant_code):
            extra_supplied.append("serial_no")
        if extra_supplied:
            template = replace(
                template,
                supplied=tuple(dict.fromkeys((*template.supplied, *extra_supplied))),
            )
        return ParseContext(template=template, profile=profile)

    def _resolve_expected_plant(
        self, cleaner: Cleaner, ref: ReferenceData, claimed: str
    ) -> str:
        """The declared scope, canonicalised and checked against ``ref_plant``.

        ``ref_plant.plant_code`` is the authority (T17 locked decision 2):
        the client says which plant it is uploading for, the server decides
        whether that is a plant at all. An alias spelling is accepted the
        same way a cell's spelling is; anything else is refused with nothing
        stored.
        """
        code = cleaner.canonical_plant(claimed)
        if not code:
            raise UploadRejected(
                "", "EXPECTED_PLANT_REQUIRED",
                "expected_plant is required: an upload has to say which "
                "plant's data it is. Nothing was stored.",
            )
        if code not in ref.known_plants:
            raise UploadRejected(
                "", "EXPECTED_PLANT_UNKNOWN",
                f"expected_plant {claimed!r} is not a plant in ref_plant. "
                f"Known plants: {', '.join(sorted(ref.known_plants)) or '(none)'}. "
                f"Nothing was stored.",
            )
        return code

    def _scan_plant_cells(
        self,
        cleaner: Cleaner,
        data: bytes,
        templates: Sequence[SheetTemplate],
    ) -> dict[str, SheetPlantScan]:
        """What each sheet's Plant column says, before ``store.put`` (T17/T39).

        Reads one column per sheet -- enough to know which plant wrote the
        rows, not enough to interpret a measurement. ``cleaner`` carries the
        page plant as ``expected_plant``.

        * a cell that resolves to the page plant, or **starts with** it
          (``AAT U704`` on AAT), agrees;
        * blank cells are counted: the cleaner fills them from the page;
        * a documented aggregate sentinel (``[All]``) is a roll-up, not a
          plant name (T26 S16), and is skipped;
        * any other text is recorded in ``to_confirm``. T17 refused the whole
          request here; ADR 0013 decision 3 replaces that with a question, so
          the file gets a card and nothing is relabelled without an answer.
        """
        scans: dict[str, SheetPlantScan] = {}
        for template in templates:
            column = next(
                (idx for idx, field_ in template.recognised.items() if field_ == "plant"),
                None,
            )
            if column is None:
                scans[template.sheet] = SheetPlantScan(
                    sheet=template.sheet, plant_column_present=False,
                    blank_cells=0, first_blank_row=None, rows_scanned=0,
                )
                continue
            nonblank, blanks, first_blank, rows = _scan_plant_column(
                data, template.sheet, column
            )
            to_confirm: dict[str, None] = {}
            rows_to_confirm = 0
            for _, raw_value in nonblank:
                if str(raw_value).strip().casefold() in AGGREGATE_SENTINELS:
                    continue
                found, _ = cleaner.page_plant_of(raw_value)
                if found is None:
                    to_confirm.setdefault(raw_value, None)
                    rows_to_confirm += 1
            scans[template.sheet] = SheetPlantScan(
                sheet=template.sheet, plant_column_present=True,
                blank_cells=blanks, first_blank_row=first_blank,
                rows_scanned=rows, to_confirm=tuple(to_confirm),
                rows_to_confirm=rows_to_confirm,
            )
        return scans

    def _refuse_unonboarded_plant(
        self,
        cleaner: Cleaner,
        files: Sequence[tuple[str, bytes]],
        expected_plant: str,
    ) -> None:
        """D5's gate, now applied to the declared scope rather than to cells.

        Before T17 this scanned every file's Plant column looking for a plant
        that is known but not active. It no longer has to: any cell that does
        not resolve to ``expected_plant`` has already refused the request, so
        the only plant a batch can be opened under is this one. Driven by
        ``ref_plant.is_active``, not by a plant name in code (`AGENTS.md`
        rule 6), and it still creates no ``load_batch``.
        """
        try:
            cleaner.check_plant_is_onboarded({expected_plant})
        except PlantNotOnboarded as exc:
            raise UploadRejected(
                files[0][0] if files else "", "PLANT_NOT_ONBOARDED", exc.detail
            ) from exc

    def _describe(
        self, filename: str, data: bytes, ref: ReferenceData, film: FilmReference
    ) -> list[SheetTemplate]:
        try:
            names = sheet_names(data)
        except Exception as exc:  # openpyxl raises a family of errors
            raise UploadRejected(
                filename, "UNREADABLE_WORKBOOK",
                f"{filename!r} passed the archive checks but cannot be opened "
                f"as a workbook: {exc.__class__.__name__}: {exc}",
            ) from exc
        if not names:
            raise UploadRejected(
                filename, "NO_SHEETS", f"{filename!r} contains no sheets."
            )
        return [_describe_one(data, name, ref, film) for name in names]

    def _open_batch_for_sheet(
        self,
        conn: Connection,
        *,
        filename: str,
        digest: str,
        context: ParseContext,
        expected_plant: str,
        scan: SheetPlantScan,
        actor_user_id: str,
        correlation_id: str | None,
    ) -> SheetOutcome:
        """Open one batch, already scoped to the plant the upload declared.

        ``plant_code`` is set **here**, at create, and never derived from the
        rows afterwards (T17). Before T17 it started NULL and was replaced
        once parsing had finished by whichever plant the rows agreed on --
        NULL if they disagreed. A mixed workbook can no longer get this far,
        so that helper is gone and a batch never advertises a plant it might
        later take back.

        The blank cells this upload will fill from ``expected_plant`` are
        written to the audit event in the same transaction, because a fill
        nobody can see afterwards is indistinguishable from a silent relabel.
        """
        template = context.template
        profile = context.profile
        if context.sheet_class == SHEET_OUT_OF_SCOPE:
            raise IngestError("Out-of-scope sheets must be recorded on their workbook, not opened as data batches.")
        load_id = batches.create_batch(
            conn,
            source_file=filename,
            source_sheet=template.sheet,
            file_hash=digest,
            raw_store_key=key_for(digest),
            plant_code=expected_plant,
            loaded_by=actor_user_id,
            template_fingerprint=template.fingerprint,
            raw_headers=template.as_json(),
            profile_id=context.profile_id,
            domain=context.domain,
            semantic_signature=context.semantic_signature,
            sheet_class=context.sheet_class,
            unreviewed_headers=list(context.unreviewed_headers),
        )
        audit.record(
            conn,
            action="batch.upload",
            entity_type="load_batch",
            entity_id=load_id,
            actor_user_id=actor_user_id,
            after={
                "source_file": filename,
                "source_sheet": template.sheet,
                "file_hash": digest,
                "template_fingerprint": template.fingerprint,
                "domain": context.domain,
                "semantic_signature": context.semantic_signature,
                "sheet_class": context.sheet_class,
                "unreviewed_headers": list(context.unreviewed_headers),
                "duplicate_logical_fields": list(template.duplicate_fields),
                "expected_plant": expected_plant,
                "plant_column_present": scan.plant_column_present,
                "plant_cells_filled": scan.blank_cells,
                "first_filled_row": scan.first_blank_row,
                "rows_scanned": scan.rows_scanned,
                "plant_texts_to_confirm": list(scan.to_confirm),
                "plant_rows_to_confirm": scan.rows_to_confirm,
                "profile_id": context.profile_id,
                "profile_fixture_verified": bool(profile and profile["fixture_verified"]),
                "plant_supplied_by_profile": (
                    profile is not None and PROFILE_SUPPLIED_FIELD in template.supplied
                ),
                "profile_free": context.profile_free,
                "missing_optional": list(template.missing_optional),
            },
            correlation_id=correlation_id,
        )

        # T18/T26: a layout nobody has agreed to read is refused here, before
        # any data row is touched, exactly as a missing required header is.
        # They are one answer -- "this platform does not know what this sheet
        # means" -- and the proposal payload says which of the four it was.
        if context.sheet_class == SHEET_UNKNOWN_DATA:
            reason = SHEET_UNKNOWN_DATA
            detail = (
                f"sheet [{template.sheet}] looks like a data grid and speaks "
                f"some WaveScan -- "
                f"{', '.join(sorted(set(template.recognised.values()))) or '(nothing)'}"
                f" -- but not enough of it to be a WaveScan sheet. It is "
                f"blocked for classification rather than guessed at (S10)"
            )
        elif template.duplicates:
            # S8. Before T26 the later column was dropped in silence, which
            # is the shape a swapped measure would have had.
            reason = BLOCKER_DUPLICATE_LOGICAL_FIELD
            detail = (
                "more than one column means the same logical field: "
                + "; ".join(
                    f"column {idx + 1} repeats {field_!r}"
                    for idx, field_ in template.duplicates
                )
                + ". No data row was read, because nothing here chooses which "
                "column was meant"
            )
        elif profile is None and _missing_columns(template):
            # T42: without a profile the tab is read on its required columns,
            # so the honest refusal is which of those it lacks (Prototype
            # `parseSheets` skips such a tab with a warning).
            reason = "TEMPLATE_UNKNOWN"
            detail = (
                f"sheet [{template.sheet}] has no column for: "
                f"{', '.join(_missing_columns(template))}. No data row was read"
            )
        elif profile is None and not context.profile_free:
            reason = "PROFILE_UNKNOWN"
            detail = (
                f"no active template profile for plant {expected_plant!r}, "
                f"domain {context.domain}, semantic signature "
                f"{context.semantic_signature[:12]}...; a layout has to be "
                f"approved before its rows are read (T18, selection amended "
                f"by T26). The exact column order "
                f"({template.fingerprint[:12]}...) is recorded separately: "
                f"reordering alone would not have landed here"
            )
        elif not template.is_parseable:
            reason = "TEMPLATE_UNKNOWN"
            detail = "missing required column(s): " + ", ".join(
                template.missing_required
            )
        else:
            reason = None
            detail = ""

        if reason is not None:
            # `02-PIPELINE.md` §4: refuse the template, do not parse the data
            # rows, and leave an Admin a proposal to decide.
            batches.set_batch_outcome(
                conn,
                load_id,
                status=batches.STATUS_REJECTED_TEMPLATE,
                notes=f"Unknown template: {detail}"[:2000],
            )
            self._propose_template_mapping(
                conn, load_id, template, actor_user_id, reason=reason
            )
            return SheetOutcome(
                filename=filename, sheet=template.sheet, load_id=load_id,
                status=batches.STATUS_REJECTED_TEMPLATE,
                detail=detail,
            )

        ingest_jobs.enqueue(conn, load_id)
        return SheetOutcome(
            filename=filename, sheet=template.sheet, load_id=load_id,
            status=batches.STATUS_RUNNING, detail="queued for parsing",
        )

    def _propose_template_mapping(
        self,
        conn: Connection,
        load_id: int,
        template: SheetTemplate,
        proposed_by: object,
        *,
        replayed: bool = False,
        reason: str = "TEMPLATE_UNKNOWN",
    ) -> str:
        """The header diff an Admin needs, written as a `COLUMN` proposal.

        One builder for both callers -- the first upload and a replay that
        still cannot read the sheet -- so the two can never describe the same
        problem differently. Advisory throughout: nothing in this payload is
        applied by anything, and the route that applies it is Admin-only.

        T46: not for a FilmBuild header. The COLUMN route approves WaveScan
        fields only, so a film proposal could never be applied; the refusal
        and its header diff stay on the batch (`raw_headers`, `notes`).
        """
        if template.domain == DOMAIN_FILMTHICKNESS:
            return ""
        return batches.propose_column_mapping(
            conn,
            load_id,
            {
                "reason": reason,
                "sheet": template.sheet,
                "domain": template.domain,
                "sheet_class": template.sheet_class,
                "missing_required": list(template.missing_required),
                "duplicate_logical_fields": list(template.duplicate_fields),
                "unrecognised_headers": list(template.unrecognised),
                "ignored_headers": list(template.ignored),
                "raw_headers": list(template.raw_headers),
                "template_fingerprint": template.fingerprint,
                "semantic_signature": template.semantic_signature,
                "after_replay": replayed,
                "note": (
                    "Advisory only. An Admin approves a column mapping; "
                    "the batch is then replayed from the stored bytes. "
                    "Nothing here is applied automatically."
                ),
            },
            str(proposed_by) if proposed_by else None,
        )

    # -----------------------------------------------------------------
    # phase 2: the worker
    # -----------------------------------------------------------------
    def process_batch(self, conn: Connection, load_id: int) -> str:
        """Parse, stage, disposition, count. Writes no measurement."""
        batch = batches.get_batch(conn, load_id)
        if batch is None:
            raise IngestError(f"batch {load_id} does not exist")
        if batch["status"] != batches.STATUS_RUNNING:
            raise IngestError(
                f"batch {load_id} is {batch['status']}, not RUNNING; refusing to "
                f"re-parse it. Re-parsing a reviewed or committed batch would "
                f"replace dispositions a person has already acted on."
            )

        data = self.store.get(batch["raw_store_key"])
        ref = reference_repo.load_reference_data(conn)

        try:
            plan, raw_rows, context = self._plan(conn, batch, data, ref)
        except TemplateError as exc:
            # Includes `ProfileMissing`, `DuplicateFieldError` and
            # `SheetNotWaveScan`: a sheet nobody has agreed how to read is
            # refused the same way a missing required header is, and for the
            # same reason -- no data row is read (T18 locked decision 3,
            # widened by T26 S8/S10).
            batches.set_batch_outcome(
                conn, load_id, status=batches.STATUS_REJECTED_TEMPLATE,
                notes=str(exc)[:2000],
                domain=exc.template.domain,
                semantic_signature=exc.template.semantic_signature,
                sheet_class=exc.template.sheet_class,
                unreviewed_headers=list(exc.template.unreviewed_headers),
            )
            if isinstance(exc, FilmNamesNoPoints) or (
                isinstance(exc, SheetNotWaveScan)
                and exc.sheet_class == SHEET_OUT_OF_SCOPE
            ):
                # Preserved evidence of another domain. Nobody is asked to
                # map a Methods sheet's headers (S10) -- or, for T99
                # (D-99-9), to map a header that is already understood on a
                # sheet whose rows name no point.
                return batches.STATUS_REJECTED_TEMPLATE
            # T08: a replay that still cannot read the sheet leaves a fresh
            # proposal, the same way the first upload did. Without this, an
            # Admin who approves an alias that turns out to be the wrong one
            # gets a REJECTED_TEMPLATE batch and no record of what is still
            # missing -- and the header diff is exactly what they need to
            # propose the next one. It does not loop: nothing here approves
            # anything, so each round still needs a person.
            self._propose_template_mapping(
                conn, load_id, exc.template, batch["loaded_by"], replayed=True,
                reason=_template_reason(exc),
            )
            return batches.STATUS_REJECTED_TEMPLATE

        status, _ = self._write_review(conn, batch, plan, raw_rows, context, ref)
        return status

    def _write_review(
        self,
        conn: Connection,
        batch: dict,
        plan: Plan,
        raw_rows: list,
        context: ParseContext,
        ref: ReferenceData,
    ) -> tuple[str, str]:
        """Stage, project, disposition and count one parse. Returns
        `(status, review_revision)`.

        Shared by the worker (`process_batch`) and by override revalidation
        (T21), so a sheet re-derived because a reviewer replaced a CF is
        written by exactly the statements that wrote it the first time:
        staging and projection are **inserted** into cleared tables, never
        updated in place.
        """
        load_id = batch["load_id"]
        film = isinstance(plan, FilmPlan)
        # Staging first, and unconditionally: `02-PIPELINE.md` §6 keeps
        # `stg_raw` for investigation precisely when the load does not
        # succeed, so it must not be conditional on the load succeeding.
        (film_repo.stage_rows if film else batches.stage_rows)(conn, load_id, raw_rows)

        # The review projection, in the same transaction as the staging it
        # describes (T18, design section 6). Written for **every** source row,
        # whatever its disposition: a reviewer needs to see the row that was
        # rejected as much as the row that would load, and T20 cannot show raw
        # against canonical by re-parsing the workbook on a GET.
        projection = _projection_of(plan, raw_rows, context)
        revision = _review_revision(projection)
        batches.insert_review_rows(
            conn,
            load_id,
            [
                batches.ReviewRow(
                    source_row=entry["source_row"],
                    disposition=entry["disposition"],
                    reason=entry["reason"],
                    detail=entry["detail"],
                    canonical=entry["canonical"],
                    raw=entry["raw"],
                    normalized_fields=entry["normalized_fields"],
                    profile_id=context.profile_id,
                    template_fingerprint=context.fingerprint,
                    review_revision=revision,
                )
                for entry in projection
            ],
        )

        counts = plan.counts

        # T17 belt and braces. The upload gate already refused any workbook
        # whose cells name another plant, so this cannot normally fire. If it
        # ever does -- a batch opened before T17, bytes swapped under a
        # content hash -- the batch FAILS with its staging kept. The one
        # answer that is not allowed is to write the row anyway under the
        # batch's plant, which is exactly the silent relabel this slice
        # exists to prevent.
        out_of_scope = _out_of_scope_rows(plan, batch["plant_code"])
        if out_of_scope:
            first = out_of_scope[0]
            batches.set_batch_outcome(
                conn, load_id, status=batches.STATUS_FAILED, counts=counts,
                profile_id=context.profile_id, review_revision=revision,
                **_parse_columns(context),
                notes=(
                    f"plant scope violated: batch is {batch['plant_code']!r} but "
                    f"{len(out_of_scope)} cleaned row(s) resolve elsewhere, first "
                    f"at row {first.source_row} ({first.plant!r}). Nothing was "
                    f"written to wavescan and staging is kept for investigation. "
                    f"A row is never relabelled to the batch's plant."
                )[:2000],
            )
            return batches.STATUS_FAILED, revision
        if not counts.balanced:
            accounted = (
                counts.rows_loaded + counts.rows_duplicate
                + counts.rows_rejected + counts.rows_quarantine
            )
            batches.set_batch_outcome(
                conn, load_id, status=batches.STATUS_FAILED, counts=counts,
                profile_id=context.profile_id, review_revision=revision,
                **_parse_columns(context),
                notes=(
                    f"balance check failed: {counts.rows_in_file} rows read but "
                    f"{accounted} accounted for. Staging kept for investigation."
                ),
            )
            return batches.STATUS_FAILED, revision

        if film:
            # T46: a film duplicate is a reject_log DUPLICATE_ROW like a
            # WaveScan one. Held film rows (extra point, unmapped location,
            # unresolved model) are QUARANTINE in the projection and are not
            # `unidentified_model` rows: that table is WaveScan model
            # teaching, and an FTM extra point is not a model to teach.
            batches.insert_rejects(
                conn, load_id,
                list(plan.result.rejects) + [_film_duplicate_reject(d) for d in plan.duplicates],
                [],
            )
        else:
            batches.insert_rejects(conn, load_id, plan.result.rejects, plan.duplicates)
            zone_counts: dict[str, int] = {}
            for u in plan.result.unidentified:
                if u.serial_no:
                    zone_counts[u.serial_no] = zone_counts.get(u.serial_no, 0) + 1
            batches.insert_unidentified(
                conn, load_id, plan.result.unidentified, zone_counts,
                dict(ref.expected_zones),
            )
        batches.set_batch_outcome(
            conn,
            load_id,
            status=batches.STATUS_PENDING_REVIEW,
            counts=counts,
            profile_id=context.profile_id,
            review_revision=revision,
            finished=False,
            **_parse_columns(context),
        )
        return batches.STATUS_PENDING_REVIEW, revision

    # -----------------------------------------------------------------
    # phase 3: commit
    # -----------------------------------------------------------------
    def commit_batch(
        self,
        conn: Connection,
        load_id: int,
        *,
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Insert the LOAD rows, audit it, and mark the batch committed.

        One transaction, owned by the caller. `02-PIPELINE.md` §9: "Promote
        (insert facts) is one transaction including `audit_event`."
        """
        batch = batches.get_batch_for_update(conn, load_id)
        if batch is None:
            raise IngestError(f"batch {load_id} does not exist")
        if batch["status"] != batches.STATUS_PENDING_REVIEW:
            raise IngestError(
                f"batch {load_id} is {batch['status']}. Only a PENDING_REVIEW "
                f"batch can be committed"
                + (
                    " -- this one is already committed."
                    if batch["status"] == batches.STATUS_COMMITTED
                    else "."
                )
            )

        data = self.store.get(batch["raw_store_key"])
        ref = reference_repo.load_reference_data(conn)
        try:
            plan, raw_rows, context = self._plan(conn, batch, data, ref)
        except TemplateError as exc:
            # T26: the token names *which* refusal, because they are fixed by
            # different people doing different things -- publish a profile,
            # remove a repeated column, classify a sheet, add a header.
            raise IngestError(
                f"batch {load_id} cannot be committed: "
                f"{_commit_template_token(exc)}. {exc} Nothing was committed."
            ) from exc

        # Every blocker at once, from the plan that was just re-derived.
        # Reporting only the first would send a reviewer round the loop twice
        # on a SAP file, which is both unverified *and* short of a vehicle
        # identity -- and the second answer is the one that cannot be fixed
        # by approving anything.
        blocking: list[tuple[str, str]] = []

        # M6. An approved header alias is not proof that a layout commits
        # correctly; a fixture is. The application cannot write
        # `fixture_verified` at all -- it has no grant for it -- so this
        # refusal cannot be lifted by anything a route does. T42: a tab read
        # on the profile-free contract (`_plan` refuses anything else with no
        # profile) has no layout claim to prove; its fields came from
        # approved aliases and its extras still block below.
        if context.profile is not None and not context.profile["fixture_verified"]:
            blocking.append((
                BLOCKER_UNVERIFIED_PROFILE,
                f"its layout ({batch['plant_code']} / "
                f"{context.fingerprint[:12]}...) has a template profile, so it "
                f"parses and can be reviewed, but no fixture has proved that "
                f"committing it produces correct measurements, and approving a "
                f"header mapping does not prove that (design M6)",
            ))

        # S9. A column nobody has decided about is not a column to ignore.
        # The known fields parsed and are fully reviewable; what is refused is
        # turning them into facts while a column of the same sheet has no
        # agreed meaning -- it could be the one that says which line, which
        # panel, or which of two vehicles this row is.
        if context.unreviewed_headers:
            blocking.append((
                BLOCKER_UNREVIEWED_HEADER,
                f"{len(context.unreviewed_headers)} header(s) on this sheet "
                f"have no agreed meaning: "
                f"{', '.join(repr(h) for h in context.unreviewed_headers)}. "
                f"They are preserved with the rows and the known fields "
                f"parsed, but nothing here decides that an unknown column is "
                f"unimportant. An Engineer confirms ignoring it on the "
                f"worksheet (POST .../workbooks/{{file_hash}}/ignore-columns, "
                f"ADR 0013), or an Admin maps the header",
            ))

        # S16. A sheet whose only rows are roll-ups has no vehicle in it.
        # Committing it would write nothing and report success, which reads
        # as "this month loaded" to the person who sent the file.
        if plan.aggregates and not plan.clean:
            blocking.append((
                BLOCKER_AGGREGATE_ONLY_SHEET,
                f"every row of this sheet is a report roll-up "
                f"({len(plan.aggregates)} of them) and none is a leaf "
                f"measurement. There is no vehicle here to record. Send the "
                f"unfiltered export rather than the pivot",
            ))

        # T39 (ADR 0013 decision 2): blank serial and blank paintline load
        # NULL at every plant, so neither is a commit gate any more.

        # A batch with no stored projection is refused below with
        # NO_REVIEW_PROJECTION, which is the more useful answer: there
        # is nothing anybody could have acknowledged.
        missing_acks = (
            unacknowledged_categories(conn, batch)
            if batch["review_revision"] else []
        )
        if missing_acks:
            blocking.append((
                BLOCKER_WARNINGS_UNACKNOWLEDGED,
                f"{len(missing_acks)} warning categor"
                f"{'y' if len(missing_acks) == 1 else 'ies'} "
                f"({', '.join(missing_acks)}) have not been acknowledged for "
                f"review revision "
                f"{str(batch['review_revision']).strip()[:12]}..., and each "
                f"means rows this plant sent are not becoming measurements. "
                f"Acknowledge them at POST /api/v1/plants/"
                f"{batch['plant_code']}/workbooks/"
                f"{str(batch['file_hash']).strip()}/acknowledgements "
                f"(a rejected or quarantined category needs a note) and "
                f"commit again (design M11)",
            ))

        if blocking:
            raise IngestError(
                f"batch {load_id} cannot be committed: "
                + ", ".join(token for token, _ in blocking)
                + ". "
                + " ".join(f"{token}: {why}." for token, why in blocking)
                + " Nothing was committed."
            )

        counts = plan.counts

        reviewed = batches.BatchCounts(
            rows_in_file=batch["rows_in_file"],
            rows_loaded=batch["rows_loaded"],
            rows_duplicate=batch["rows_duplicate"],
            rows_rejected=batch["rows_rejected"],
            rows_quarantine=batch["rows_quarantine"],
        )
        if counts.as_dict() != reviewed.as_dict():
            raise IngestError(
                f"batch {load_id} no longer produces what was reviewed: "
                f"reviewed {reviewed.as_dict()}, re-derived {counts.as_dict()}. "
                f"Reference data or the measurements this batch is compared "
                f"against changed in between. Nothing was committed. Re-parse "
                f"the batch so a person reviews what would actually be written."
            )
        if not counts.balanced:
            raise IngestError(
                f"batch {load_id} does not balance: {counts.as_dict()}. "
                f"Nothing was committed (docs/02-PIPELINE.md section 6)."
            )
        # The projection hash: what a person reviewed is what gets written,
        # or nothing does (T18 work item 3, design section 6). The counts
        # check above catches a different number of rows; this catches the
        # same number of rows meaning something different -- an alias
        # approved in between, a zone map changed -- which the counts cannot
        # see.
        derived_revision = _review_revision(_projection_of(plan, raw_rows, context))
        if batch["review_revision"] is None:
            raise IngestError(
                f"batch {load_id} has no stored review projection "
                f"({BLOCKER_NO_REVIEW_PROJECTION}), so there is nothing to "
                f"check what would be written against. Replay it so a person "
                f"reviews the rows that would actually be committed. Nothing "
                f"was committed."
            )
        if str(batch["review_revision"]).strip() != derived_revision:
            raise IngestError(
                f"batch {load_id} no longer produces the rows that were "
                f"reviewed: projection revision "
                f"{str(batch['review_revision']).strip()[:12]}... was reviewed, "
                f"{derived_revision[:12]}... is what the stored bytes produce "
                f"now. The counts still agree, so this is a change of meaning "
                f"rather than of volume -- an alias or a zone map moved in "
                f"between. Nothing was committed. Replay the batch so a person "
                f"reviews what would actually be written."
            )

        out_of_scope = _out_of_scope_rows(plan, batch["plant_code"])
        if out_of_scope:
            first = out_of_scope[0]
            raise IngestError(
                f"batch {load_id} is filed under plant "
                f"{batch['plant_code']!r} but {len(out_of_scope)} of the rows "
                f"it would insert resolve to another plant, first at row "
                f"{first.source_row} ({first.plant!r}). Nothing was committed. "
                f"A measurement is written under the plant its own row names "
                f"(docs/tasks/T17-expected-plant.md)."
            )

        if isinstance(plan, FilmPlan):
            # T46 (F16): one INSERT per (row, numeric layer) into the film
            # fact table. Same transaction as the audit row below.
            inserted = film_repo.insert_facts(conn, load_id, plan.clean)
        else:
            inserted = batches.insert_measurements(conn, load_id, plan.clean)
        batches.set_batch_outcome(
            conn, load_id, status=batches.STATUS_COMMITTED, counts=counts
        )
        audit.record(
            conn,
            action="batch.commit",
            entity_type="load_batch",
            entity_id=load_id,
            actor_user_id=actor_user_id,
            before={"status": batch["status"]},
            after={
                "status": batches.STATUS_COMMITTED,
                "domain": context.domain,
                "measurements_inserted": inserted,
                "profile_id": context.profile_id,
                "profile_free": context.profile_free,
                "template_fingerprint": context.fingerprint,
                "review_revision": derived_revision,
                **counts.as_dict(),
            },
            correlation_id=correlation_id,
        )
        return {"load_id": load_id, "measurements_inserted": inserted, **counts.as_dict()}

    # -----------------------------------------------------------------
    # phase 4: replay (T08)
    # -----------------------------------------------------------------
    def film_walk_question(
        self, conn: Connection, load_id: int
    ) -> tuple[object | None, str | None]:
        """T99 (D-99-14): what a held Film walk is asking, re-derived.

        Returns ``(WalkVerdict, model_code)`` for a Film sheet whose body
        labels are not the plant's known walk, or ``(None, None)`` for
        anything else. The worksheet calls it so the confirm page asks about
        the names **this parse** found appended, from the stored bytes and the
        live list -- not from anything a client sent and not from a second
        copy of the walk rule. No row is written and no workbook is re-read
        on a GET: it is the same `_plan_film` path the review already uses.
        """
        batch = batches.get_batch(conn, load_id)
        if batch is None:
            return None, None
        data = self.store.get(batch["raw_store_key"])
        ref = reference_repo.load_reference_data(conn)
        film = film_repo.load_film_reference(conn)
        try:
            template = _describe_one(data, batch["source_sheet"], ref, film)
            rows = list(read_film_sheet(
                data, batch["source_sheet"], template, batch["source_file"]
            ))
        except ReaderError:
            return None, None
        model = resolve_film_model(
            batch["plant_code"], batch["source_file"], batch["source_sheet"],
            film.model_alias,
        )
        chosen = worksheet_repo.film_sheet_answers(conn, load_id)["model"]
        model_code = chosen or model.model
        if not film.has_setting(batch["plant_code"], model_code):
            return None, None
        body = _film_body_rows(film, batch["plant_code"], model_code, rows)
        labels = [row.text("location") for row in body]
        # RO14 (D-RO14-2): each car of the sheet on its own, as the parse did.
        verdict = check_walks(
            labels, film.walk.get((batch["plant_code"], model_code), ()),
            rows=[row.source_row for row in body],
            plant=batch["plant_code"], model=model_code,
            identities=_film_identities(body, template.meta_map),
            # T109: the same resolved names the parse used, so the confirm
            # page asks about the names that are still unanswered.
            resolved=_film_resolved(
                film, batch["plant_code"], model_code, labels,
            ),
        )
        if verdict.ok:
            return None, None
        return verdict, model_code

    def replay_batch(
        self,
        conn: Connection,
        load_id: int,
        *,
        actor_user_id: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Re-run stored bytes through the same pipeline.

        `02-PIPELINE.md` §8: "Resolving quarantine or adding an alias re-runs
        stored bytes from the object store. No re-upload. Same pipeline code
        path as first ingest -- not a second 'resolution parser'." That is
        literally what this does: it puts the batch back to `RUNNING` and
        queues a job, and the worker then calls `process_batch`, unchanged.
        There is no replay parser to drift from the upload parser because
        there is no replay parser.

        **Three refusals, in the order that makes the message useful.**

        1. No such batch -> the caller has the wrong id.
        2. Wrong status -> only `REJECTED_TEMPLATE` and `PENDING_REVIEW` are
           replayable. `COMMITTED` and `SUPERSEDED` have produced facts;
           `RUNNING` is being parsed right now; `FAILED` wants a person to
           read `notes` first.
        3. The batch has `wavescan` rows -> refuse even if the status somehow
           says otherwise. Status is a column somebody could get wrong; the
           row count is the thing itself.

        Only then is staging cleared, and that clearing is itself guarded by
        the same fact count inside `reset_batch_staging` (revision 0004).
        Two checks of one condition, one in the application for the message
        and one in the database for the guarantee.

        Replay ends where the first parse ends: `PENDING_REVIEW`, or
        `REJECTED_TEMPLATE` if the sheet still cannot be read. **It never
        commits.** Turning rows into measurements stays an Engineer action on
        a batch a person has looked at.
        """
        batch = batches.get_batch_for_update(conn, load_id)
        if batch is None:
            raise IngestError(f"batch {load_id} does not exist")

        previous = batch["status"]
        if previous not in batches.REPLAYABLE_STATUSES:
            allowed = " or ".join(batches.REPLAYABLE_STATUSES)
            raise IngestError(
                f"batch {load_id} is {previous}, so it cannot be replayed. "
                f"Only a {allowed} batch can be: replay re-derives every "
                f"disposition from the stored bytes, and a batch that has "
                f"already become measurements would have to lose them first. "
                f"Nothing was changed."
            )

        facts = batches.count_facts(conn, load_id)
        if facts:
            raise IngestError(
                f"batch {load_id} is {previous} but already has {facts} "
                f"wavescan row(s). Replaying it would mean deleting "
                f"measurements, which no role in this system can do "
                f"(ADR 0005). Nothing was changed; this batch needs a "
                f"supersession, not a replay."
            )

        cleared = batches.reset_batch_staging(conn, load_id)
        batches.reopen_for_replay(
            conn, load_id, notes=f"replayed from stored bytes: {reason}"
        )
        job_id = ingest_jobs.requeue_for_batch(conn, load_id)
        audit.record(
            conn,
            action="batch.replay",
            entity_type="load_batch",
            entity_id=load_id,
            actor_user_id=actor_user_id,
            before={"status": previous, **{f"cleared_{k}": v for k, v in cleared.items()}},
            after={"status": batches.STATUS_RUNNING, "reason": reason, "job_id": job_id},
            correlation_id=correlation_id,
        )
        log.info(
            "batch queued for replay",
            extra={"detail": f"load_id={load_id} from={previous} reason={reason}"},
        )
        return {
            "load_id": load_id,
            "previous_status": previous,
            "status": batches.STATUS_RUNNING,
            "cleared": cleared,
            "job_id": job_id,
        }

    # -----------------------------------------------------------------
    # phase 5: revalidate after a review override (T21)
    # -----------------------------------------------------------------
    def revalidate_review(
        self,
        conn: Connection,
        batch: dict,
        *,
        expected_overrides: dict[int, set[str]],
    ) -> dict:
        """Re-derive one PENDING_REVIEW sheet now, with its current overrides.

        Called in the **same transaction** that just inserted
        `review_override` rows, with the batch already locked. It is the
        replay path without the queue: the plan is rebuilt from the stored
        bytes by `_plan` (which applies the current overrides), this sheet's
        staging is cleared through `reset_batch_staging` -- the one function
        allowed to, and it still refuses a batch with any `wavescan` row --
        and the projection is **inserted** again by `_write_review`, the same
        statements the worker uses. Nothing is updated in place, the status
        never passes through RUNNING, and no job is queued.

        The review revision moves whenever a proposed value moved, so every
        acknowledgement bound to the old revision stops satisfying the commit
        gate while staying on record.

        Refuses (IngestError, so the caller's transaction and the override
        rows roll back) rather than leaving the sheet anywhere but
        PENDING_REVIEW: a layout that no longer has a profile, a
        re-derivation that no longer balances or leaves the plant, or an
        override that did not land because its row is no longer LOAD.
        """
        load_id = batch["load_id"]
        if batch["status"] != batches.STATUS_PENDING_REVIEW:
            raise IngestError(
                f"batch {load_id} is {batch['status']}, not PENDING_REVIEW; "
                f"nothing was revalidated."
            )
        data = self.store.get(batch["raw_store_key"])
        ref = reference_repo.load_reference_data(conn)
        try:
            plan, raw_rows, context = self._plan(conn, batch, data, ref)
        except TemplateError as exc:
            raise IngestError(
                f"batch {load_id} can no longer be parsed ({exc}). Nothing was "
                f"written; replay the batch through a mapping instead."
            ) from exc
        if isinstance(plan, FilmPlan):
            raise IngestError(
                f"batch {load_id} is a FilmThickness sheet. Review overrides "
                f"replace WaveScan measures and do not apply to film layers "
                f"(T46 is the data slice). Nothing was written."
            )

        counts = plan.counts
        if _out_of_scope_rows(plan, batch["plant_code"]) or not counts.balanced:
            raise IngestError(
                f"batch {load_id} no longer re-derives to a balanced sheet of "
                f"plant {batch['plant_code']!r} ({counts.as_dict()}). Nothing "
                f"was written."
            )
        missed = sorted(
            (row, name)
            for row, names in expected_overrides.items()
            for name in names
            if name not in plan.overridden.get(row, ())
        )
        if missed:
            raise IngestError(
                f"batch {load_id} re-derived with row(s) "
                f"{', '.join(f'{r}:{n}' for r, n in missed)} no longer loading, "
                f"so those overrides would not apply. The reference data or the "
                f"measurements this sheet is deduplicated against moved since "
                f"the review was read. Nothing was written; re-read the review."
            )

        cleared = batches.reset_batch_staging(conn, load_id)
        status, revision = self._write_review(conn, batch, plan, raw_rows, context, ref)
        if status != batches.STATUS_PENDING_REVIEW:  # pragma: no cover - checked above
            raise IngestError(
                f"batch {load_id} re-derived to {status}. Nothing was written."
            )
        return {
            "review_revision": revision,
            "counts": counts,
            "cleared": cleared,
        }

    # -----------------------------------------------------------------
    # phase 5b: the second insert pass (T39, ADR 0013 decision 9)
    # -----------------------------------------------------------------
    def insert_remaining(
        self,
        conn: Connection,
        load_id: int,
        *,
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """INSERT the rows of a COMMITTED sheet that have become loadable.

        After good rows are measurements, a later colour/model match, plant
        answer or LW/SW approval can make more rows of the **same** sheet
        loadable. This re-derives the plan from the stored bytes -- the same
        `_plan` as commit and replay -- and inserts only the LOAD rows whose
        `source_row` is not already a measurement of this batch.

        * **INSERT only.** No measurement already stored is updated or
          deleted; `uq_ws_load_row_original` refuses a second copy of a row.
        * A verified profile is still required (M6), exactly as for commit.
        * The batch counts are recomputed per source row (already a fact ->
          LOAD, otherwise what the plan says) and must still balance.
        * The staging and projection of a committed sheet are evidence of
          committed measurements and are not re-written; the held list
          excludes rows that are now facts.
        """
        batch = batches.get_batch_for_update(conn, load_id)
        if batch is None:
            raise IngestError(f"batch {load_id} does not exist")
        if batch["status"] != batches.STATUS_COMMITTED:
            raise IngestError(
                f"batch {load_id} is {batch['status']}. Only a COMMITTED sheet "
                f"has remaining rows to insert; a PENDING_REVIEW sheet is "
                f"loaded with commit. Nothing was written."
            )
        data = self.store.get(batch["raw_store_key"])
        ref = reference_repo.load_reference_data(conn)
        try:
            plan, _, context = self._plan(conn, batch, data, ref)
        except TemplateError as exc:
            raise IngestError(
                f"batch {load_id} cannot be re-read: "
                f"{_commit_template_token(exc)}. {exc} Nothing was written."
            ) from exc
        if isinstance(plan, FilmPlan):
            raise IngestError(
                f"batch {load_id} is a FilmThickness sheet. The second insert "
                f"pass (ADR 0013 decision 9) is WaveScan-only in T46; a held "
                f"film row loads by replaying a PENDING_REVIEW sheet after its "
                f"location map is proved. Nothing was written."
            )
        if context.profile is not None and not context.profile["fixture_verified"]:
            raise IngestError(
                f"batch {load_id} cannot insert more rows: "
                f"{BLOCKER_UNVERIFIED_PROFILE}. Its layout is not proved "
                f"(design M6). Nothing was written."
            )

        have = worksheet_repo.fact_source_rows(conn, load_id)
        fresh = [row for row in plan.clean if row.source_row not in have]
        if _out_of_scope_rows(plan, batch["plant_code"]):
            raise IngestError(
                f"batch {load_id} re-derives rows outside plant "
                f"{batch['plant_code']!r}. Nothing was written."
            )

        disposition: dict[int, str] = {}
        for row in plan.clean:
            disposition[row.source_row] = "LOAD"
        for dup in plan.duplicates:
            disposition.setdefault(dup.dropped.source_row, "DUPLICATE")
        for rej in plan.result.rejects:
            disposition[rej.source_row] = "REJECT"
        for un in plan.result.unidentified:
            disposition[un.source_row] = "QUARANTINE"
        for source_row in have:
            disposition[source_row] = "LOAD"
        tally = {k: 0 for k in ("LOAD", "DUPLICATE", "REJECT", "QUARANTINE")}
        for value in disposition.values():
            tally[value] += 1
        counts = batches.BatchCounts(
            rows_in_file=plan.rows_in_file,
            rows_loaded=tally["LOAD"],
            rows_duplicate=tally["DUPLICATE"],
            rows_rejected=tally["REJECT"],
            rows_quarantine=tally["QUARANTINE"],
        )
        if not counts.balanced:
            raise IngestError(
                f"batch {load_id} would not balance after inserting the "
                f"remaining rows: {counts.as_dict()}. Nothing was written "
                f"(docs/02-PIPELINE.md section 6)."
            )
        before = {
            "rows_loaded": batch["rows_loaded"],
            "rows_duplicate": batch["rows_duplicate"],
            "rows_rejected": batch["rows_rejected"],
            "rows_quarantine": batch["rows_quarantine"],
        }
        inserted = batches.insert_measurements(conn, load_id, fresh)
        if inserted:
            batches.set_batch_outcome(
                conn, load_id, status=batches.STATUS_COMMITTED, counts=counts
            )
        audit.record(
            conn,
            action="batch.insert_remaining",
            entity_type="load_batch",
            entity_id=load_id,
            actor_user_id=actor_user_id,
            before=before,
            after={
                "measurements_inserted": inserted,
                "already_measurements": len(have),
                "profile_id": context.profile_id,
                **counts.as_dict(),
            },
            correlation_id=correlation_id,
        )
        return {
            "load_id": load_id,
            "measurements_inserted": inserted,
            "already_measurements": len(have),
            "still_held": tally["REJECT"] + tally["QUARANTINE"],
            **counts.as_dict(),
        }

    # -----------------------------------------------------------------
    # phase 6: owner-publish of a verified profile (T26, spec S20)
    # -----------------------------------------------------------------
    def publish_profile(
        self,
        conn: Connection,
        plant_code: str,
        *,
        file_hash: str,
        source_sheet: str | None,
        named_owner: str,
        notes: str,
        fill_missing_plant: bool,
        ignored_headers: Sequence[dict],
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Make a layout commit-capable, on a named person's word plus bytes.

        This is the one mutation T26 adds, and the shape of it is the point.
        It is **not** an upload: the workbook must already be stored for this
        plant, and it is re-read from the object store here. So the thing
        that gets verified is always something the platform can replay, and
        the hash on the profile names bytes somebody else can fetch -- not an
        attachment that existed for the duration of one request.

        It is also **not** the mapping-approve route, and must never become
        one (design M6). Approving a header alias says "this spelling means
        that field". Publishing says "committing this layout produces correct
        measurements", which only a fixture and a named plant or quality
        owner can say. The guarantee is structural rather than a check here:
        `app_rw` holds no INSERT or UPDATE on `ref_template_profile` at all,
        so the write happens inside `publish_template_profile`, which
        requires the owner, the notes and the hash, and writes `audit_event`
        in the same transaction.

        Refusals, with nothing written:

        * unknown plant, or no workbook of that hash stored **for this
          plant** -- a workbook filed elsewhere is not evidence here;
        * bytes that are not a WaveScan sheet, are missing a required field,
          or give two columns one meaning -- a layout nobody can read is not
          a layout to certify;
        * a blank owner or blank notes, refused by the function itself.

        It then **replays**, from stored bytes, this plant's and contract's
        `REJECTED_TEMPLATE` / `PENDING_REVIEW` batches and returns their ids
        in `replayed_load_ids`. Replay ends at those statuses. It **commits
        nothing and supersedes nothing**: an Engineer still presses commit on
        rows a person has read.
        """
        ref = reference_repo.load_reference_data(conn)
        cleaner = Cleaner(ref, self._allowed_plants(ref))
        plant = self._resolve_expected_plant(cleaner, ref, plant_code)

        prior = [
            row for row in batches.find_by_hash(conn, file_hash)
            if row.get("plant_code") == plant
        ]
        if not prior:
            raise ProfilePublishRefused(
                404,
                f"no workbook with hash {file_hash[:12]}... is stored for "
                f"plant {plant}. Publishing names a workbook this platform "
                f"already holds, so that the layout it proves can be "
                f"re-derived from the same bytes. Upload it first.",
            )
        if source_sheet is not None:
            chosen = [row for row in prior if row["source_sheet"] == source_sheet]
            if not chosen:
                raise ProfilePublishRefused(
                    404,
                    f"that workbook has no sheet {source_sheet!r} at plant "
                    f"{plant}. Its sheets are: "
                    + ", ".join(sorted(repr(r["source_sheet"]) for r in prior))
                    + ".",
                )
            prior = chosen

        data = self.store.get(key_for(file_hash))
        ignored = tuple(
            normalise_header(item["header"]) for item in ignored_headers
        )

        candidates = []
        for row in prior:
            try:
                template = describe_sheet(
                    data, row["source_sheet"], ref.column_alias, (), ignored,
                    DOMAIN_WAVESCAN,
                )
            except ReaderError:
                continue
            if template.sheet_class == SHEET_WAVESCAN:
                candidates.append(template)

        if not candidates:
            raise ProfilePublishRefused(
                409,
                f"none of the sheets named is a WaveScan sheet: their header "
                f"rows do not carry this domain's measures and an identity "
                f"field. A layout that cannot be read is not a layout to "
                f"certify (spec S10). Nothing was published.",
            )
        if len(candidates) > 1:
            raise ProfilePublishRefused(
                409,
                "that workbook has more than one WaveScan sheet, so this "
                "request does not say which layout is being published. Name "
                "one in source_sheet: "
                + ", ".join(sorted(repr(t.sheet) for t in candidates))
                + ". Nothing was published.",
            )

        template = candidates[0]
        if template.duplicates:
            raise ProfilePublishRefused(
                409,
                "that sheet gives more than one column the same meaning ("
                + ", ".join(
                    f"column {idx + 1} repeats {field_!r}"
                    for idx, field_ in template.duplicates
                )
                + f"), so its meaning is ambiguous and it cannot be certified "
                f"({BLOCKER_DUPLICATE_LOGICAL_FIELD}). Nothing was published.",
            )
        supplied = (PROFILE_SUPPLIED_FIELD,) if fill_missing_plant else ()
        missing = list(replace(template, supplied=supplied).missing_required)
        if not reference_repo.plant_requires_serial(conn, plant):
            missing = [field_ for field_ in missing if field_ != "serial_no"]
        if missing:
            raise ProfilePublishRefused(
                409,
                f"that sheet is missing required column(s): "
                f"{', '.join(missing)}. A layout that cannot produce a "
                f"measurement is not a layout to certify. Nothing was "
                f"published."
                + (
                    ""
                    if fill_missing_plant or "plant" not in missing
                    else " If this layout is known to omit the Plant column, "
                         "publish it with fill_missing_plant."
                ),
            )

        result = profiles.publish(
            conn,
            plant_code=plant,
            domain=template.domain,
            semantic_signature=template.semantic_signature,
            template_fingerprint=template.fingerprint,
            fixture_file_hash=file_hash,
            named_owner=named_owner,
            notes=notes,
            fill_missing_plant=fill_missing_plant,
            ignored=[
                {
                    "header": normalise_header(item["header"]),
                    "reason": item["reason"],
                }
                for item in ignored_headers
            ],
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )

        # Spec section 6: publishing replays the batches it unblocks, and
        # **never commits**. Narrowly scoped -- this plant, this contract,
        # and only the two statuses `02-PIPELINE.md` section 8 already calls
        # replayable, so a batch that has produced measurements is never in
        # the set. Each replay re-derives from the stored bytes through the
        # same service, which is how a newly ignored column stops being an
        # unreviewed header without anybody re-uploading anything.
        #
        # Also replay this proving workbook's own live batches by file_hash.
        # COLUMN aliases approved after 1063 was stored move the *current*
        # signature, so signature-only replay would miss the August bytes
        # F1 names, while Jan–Jul files (other hashes) stay unreplayed (F4).
        replayed: list[int] = []
        seen: set[int] = set()
        reason = (
            f"template profile {result.get('profile_id')} version "
            f"{result.get('version')} published by {named_owner}"
        )
        to_replay = list(
            batches.replayable_for_signature(
                conn, plant, template.domain, template.semantic_signature
            )
        )
        for row in batches.find_by_hash(conn, file_hash):
            if (
                row.get("plant_code") == plant
                and row["status"] in batches.REPLAYABLE_STATUSES
            ):
                to_replay.append(int(row["load_id"]))
        for blocked in to_replay:
            if blocked in seen:
                continue
            seen.add(blocked)
            try:
                self.replay_batch(
                    conn, blocked,
                    actor_user_id=actor_user_id,
                    reason=reason,
                    correlation_id=correlation_id,
                )
            except IngestError as exc:
                # One unreplayable batch does not undo a publish: the
                # verification the owner performed is still true, and the
                # batch is still exactly where it was. Say so rather than
                # rolling the decision back.
                log.info(
                    "batch not replayed after publish",
                    extra={"detail": f"load_id={blocked}: {exc}"},
                )
                continue
            replayed.append(blocked)
        result["replayed_load_ids"] = replayed

        log.info(
            "template profile published",
            extra={
                "detail": (
                    f"plant={plant} sheet={template.sheet} "
                    f"profile_id={result.get('profile_id')} "
                    f"version={result.get('version')}"
                )
            },
        )
        return result

    # -----------------------------------------------------------------
    def _plan(
        self, conn: Connection, batch: dict, data: bytes, ref: ReferenceData
    ) -> tuple[Plan, list, ParseContext]:
        """Re-derive what this batch would write, from the stored bytes.

        ``batch["plant_code"]`` is the scope the upload declared, so parse,
        commit and replay all clean against the same expected plant without a
        second source for it: replay (`02-PIPELINE.md` §8) re-enters here
        with the batch it stored, not with a fresh client claim.

        **The profile is looked up here, not passed in.** Replay exists
        because an alias was approved, and an approved alias can change which
        headers are recognised and therefore the fingerprint -- which is the
        whole point of T08's flow. So the layout is re-identified from the
        bytes every time, and a replay that now matches a verified profile
        becomes committable while one that does not stays refused.

        Raises `ProfileMissing` before a single data row is read when no
        active profile claims this layout.
        """
        film = film_repo.load_film_reference(conn)
        template = _describe_one(data, batch["source_sheet"], ref, film)
        alias_map = _alias_for(template, ref, film)
        context = self._select_profile(
            conn, batch["plant_code"], template,
            data=data, alias_map=alias_map,
        )
        decisions = worksheet_repo.decisions_for_batch(conn, batch["load_id"])
        context = _apply_engineer_ignores(
            context, decisions[worksheet_repo.KIND_IGNORE_HEADER], data, alias_map,
        )
        if context.profile is None:
            # T42: an Engineer ignore can clear a repeat that stopped the
            # profile-free read at upload; decide it on the re-read header.
            context = _profile_free(batch["plant_code"], context.template)
        if context.sheet_class == SHEET_FILMTHICKNESS:
            return self._plan_film(conn, batch, data, ref, film, context)
        if context.sheet_class != SHEET_WAVESCAN:
            raise SheetNotWaveScan(
                f"{batch['source_file']} [{batch['source_sheet']}] classifies "
                f"as {context.sheet_class} from its header row, not as a "
                f"WaveScan sheet. No data row was parsed. Sheet routing is by "
                f"headers, never by the tab's name "
                f"(spec S10).",
                context.template,
            )
        if context.template.duplicates:
            # Raised here as well as at upload, because an alias approved in
            # between can *create* a duplicate: two spellings that meant
            # nothing and one thing now both mean `cf`. Replay is where that
            # surfaces, and it has to surface as a refusal.
            raise DuplicateFieldError(
                f"{batch['source_file']} [{batch['source_sheet']}] gives more "
                f"than one column the same meaning: "
                + "; ".join(
                    f"column {idx + 1} repeats {field_!r}"
                    for idx, field_ in context.template.duplicates
                )
                + ". No data row was read.",
                context.template,
            )
        if context.profile is None and _missing_columns(context.template):
            # T42: no profile, so the profile-free contract decides -- and
            # this tab lacks one of its required columns.
            raise TemplateError(
                f"{batch['source_file']} [{batch['source_sheet']}] has no "
                f"column for: {', '.join(_missing_columns(context.template))}. "
                f"No data row was read.",
                context.template,
            )
        if context.profile is None and not context.profile_free:
            raise ProfileMissing(
                f"{batch['source_file']} [{batch['source_sheet']}] has no active "
                f"template profile for plant {batch['plant_code']!r}, domain "
                f"{context.domain} and semantic signature "
                f"{context.semantic_signature}. A layout is approved before "
                f"its rows are read, so no data row was parsed "
                f"(docs/02-PIPELINE.md section 4). Its exact column order "
                f"hashes to {context.fingerprint}; that is provenance, not "
                f"the reason it was refused.",
                context.template,
            )

        # RO18 (B4, RO09): a sheet with no date column is read; every row
        # takes the month a person named, or waits on that one question.
        no_date_column = "date" not in (
            set(context.template.recognised.values()) | set(context.template.supplied)
        )
        cleaner = Cleaner(
            ref, self._allowed_plants(ref), expected_plant=batch["plant_code"],
            no_date_column=no_date_column,
            month_only=(
                parse_month_answer(
                    worksheet_repo.sheet_date_answers(conn, batch["load_id"])["month"]
                ) if no_date_column else None
            ),
            month_detail=month_question_detail(batch["source_file"]),
            confirmed_plant_texts=decisions[worksheet_repo.KIND_PLANT_CONFIRM],
            hole_rows={
                int(r) for r in decisions[worksheet_repo.KIND_HOLE_APPROVAL]
                if str(r).isdigit()
            },
            # T94 (D-94-2, D-94-6): the panels a person confirmed a **rough**
            # label is, for this upload. Read per batch and handed to the
            # cleaner here, which is the only route by which a rough label
            # ever resolves. Nothing on the `ref_*` path can see it, so last
            # month's answer cannot file this month's hood.
            confirmed_panels=worksheet_repo.confirmed_panels_for_batch(
                conn, batch["load_id"]
            ),
        )
        raw_rows = list(
            read_sheet(
                data,
                batch["source_sheet"],
                ref.column_alias,
                batch["source_file"],
                context.template.supplied,
                context.template.ignored,
                context.domain,
            )
        )
        result = cleaner.clean_all(raw_rows)

        deduper = Deduplicator(self.settings.duplicate_threshold)
        # T39: a blank serial is NULL now, so the sort must not compare None.
        pairs = sorted(
            {(r.plant, r.serial_no) for r in result.clean},
            key=lambda pair: (pair[0], pair[1] is not None, pair[1] or ""),
        )
        # T39-FIX (ADR 0013 8a): serial-less points are looked up by the
        # day, model and colour of the sheet-vehicle, not by serial; RO16: and
        # by the car of the sheet (`car_key`, None on a one-car sheet).
        serialless = sorted(
            {
                (r.plant, r.measured_date, r.model, r.color, r.car_key)
                for r in result.clean if r.serial_no is None
            },
            key=lambda k: (*k[:4], k[4] or ""),
        )
        existing = measurements.existing_for_dedup(conn, pairs, serialless)
        deduped = deduper.run(result.clean, existing)

        clean, applied = _apply_overrides(
            deduped.keep, overrides.current_for_batch(conn, batch["load_id"])
        )

        return (
            Plan(
                clean=clean,
                duplicates=deduped.duplicates,
                result=result,
                # T26: a `[All]` roll-up is not one of the file's data rows
                # going one of four ways, so it is outside the balance the
                # same way a blank row already is (spec S16).
                rows_in_file=len(raw_rows) - len(result.aggregates),
                overridden=applied,
            ),
            raw_rows,
            context,
        )

    def _plan_film(
        self,
        conn: Connection,
        batch: dict,
        data: bytes,
        ref: ReferenceData,
        film: FilmReference,
        context: ParseContext,
    ) -> tuple[FilmPlan, list, ParseContext]:
        """Re-derive a FilmThickness sheet from the stored bytes (T46).

        Same contract as the WaveScan branch of `_plan`: refuse before a
        data row is read when the header is ambiguous or incomplete; else
        read, clean, and split repeats of a (car, point) already known.
        The model is resolved once per sheet from the file and tab name
        (F4-F7), never from a row and never from PELT Comments.
        """
        template = context.template
        rows = read_film_sheet(
            data, batch["source_sheet"], template, batch["source_file"]
        )
        raw_rows = list(rows)  # raises before yielding on S8 / missing fields
        # T99 (D-99-9): a sheet that names no point is refused at the door,
        # before a model is resolved -- there is no point question to ask and
        # no answer that would make one loadable.
        if film.plant_has_setting(batch["plant_code"]) and names_no_points(
            _film_body_labels(raw_rows)
        ):
            raise FilmNamesNoPoints(
                f"{REASON_FILM_NO_NAMED_POINTS}: "
                + no_named_points_detail(
                    plant=batch["plant_code"], model=None,
                    sheet=batch["source_sheet"],
                ),
                template,
            )
        model = resolve_film_model(
            batch["plant_code"], batch["source_file"], batch["source_sheet"],
            film.model_alias,
        )
        # T61 / T78 (D-78-31): if an Admin approved a FILM_MODEL choice for
        # this exact (load_id, source_sheet), that approved proposal is the
        # record, and replay reads it here -- in the SAME ingest service, so
        # there is no second parser (02-PIPELINE.md section 10). The choice
        # overrides only the model; every other rule still runs unchanged.
        chosen = mappings_repo.approved_film_model_choice(
            conn, int(batch["load_id"]), batch["source_sheet"]
        )
        if chosen and chosen != model.model:
            model = ModelResolution(
                chosen, model.token, "approved_choice",
                f"an Admin approved {chosen} for this sheet (T61); the names "
                f"said: {model.detail}",
            )
        # T99. Everything about the sheet rather than the row -- the Job
        # Number, the two models the names may give, the walk -- decided once
        # here, from reference data and the uploader's own answers. A plant x
        # model with no `film_point_setting` row gets `None` back and the
        # cleaner behaves exactly as it did before T99 (D-99-12).
        sheet_hold, sheet_waiting, colour_tokens, model = _film_sheet_rules(
            conn, batch, film, raw_rows, model, template.meta_map
        )
        # RO18 (B3 / B4): the sheet's date against its file name, and a sheet
        # with no date at all. Every plant, settings or not.
        date_hold, date_override, month_only = _film_sheet_date(
            conn, batch, template, raw_rows
        )
        sheet_hold = sheet_hold or date_hold
        # RO14 (D-RO14-1 / -3 / -4): a sheet that holds several cars one after
        # another, at every plant (settings or not). One walk changes nothing.
        walks = _film_walks(
            film, batch["plant_code"], model.model, raw_rows, template.meta_map
        )
        walk_keys: dict[int, str] = {}
        # RO18 (B4): a month-only sheet has no day to keep two same-colour
        # cars of the month apart, so even one walk takes its fingerprint.
        if len(walks) > 1 or month_only:
            if len(walks) > 1:
                sheet_hold = sheet_hold or _film_walks_mixed(walks, template.meta_map)
            for walk in walks:
                key = walk_fingerprint(
                    (
                        film.resolve_point(
                            batch["plant_code"], model.model, row.text("location")
                        ) or normalise_location(row.text("location")),
                        [row.get(name) for name in LAYER_FIELDS],
                    )
                    for row in walk
                )
                walk_keys.update((row.source_row, key) for row in walk)
        cleaner = FilmCleaner(
            film,
            plant=batch["plant_code"],
            model=model,
            meta=template.meta_map,
            color_by_plant=ref.color_by_plant,
            color=ref.color,
            known_color_names=sorted(ref.known_color_names),
            # T78 (D-78-20): the same `ref_plant_color` map WaveScan gates on.
            offered_colors=ref.offered_colors,
            # T112-FIX (D-112F-2): the same `ref_plant_model` map WaveScan gates on.
            offered_models=ref.offered_models,
            merged_colors=ref.merged_colors,
            sheet_hold=sheet_hold,
            sheet_waiting=sheet_waiting,
            colour_tokens=colour_tokens,
            walk_keys=walk_keys,
            date_override=date_override,
            month_only=month_only,
        )
        result = cleaner.clean_all(raw_rows)
        # T64: a car stored under a merged colour's id is still this car.
        existing = film_repo.existing_vehicle_points(
            conn,
            sorted({
                vid for r in result.clean
                for vid in stored_vehicle_ids(r, ref.merged_colors)
            }),
        )
        existing = fold_existing(result.clean, existing, ref.merged_colors)
        keep, dups = split_duplicates(result.clean, existing)
        return (
            FilmPlan(
                clean=keep,
                duplicates=dups,
                result=result,
                rows_in_file=len(raw_rows) - len(result.aggregates),
                model=model,
                plant=batch["plant_code"],
            ),
            raw_rows,
            context,
        )

    def _allowed_plants(self, ref: ReferenceData) -> tuple[str, ...]:
        """Which plants may be loaded.

        Driven by `ref_plant.is_active`, not by a list in configuration: the
        database is where a plant is onboarded, and `AGENTS.md` rule 6
        forbids a plant name living in code.
        """
        return tuple(sorted(ref.active_plants))


def _missing_columns(template: SheetTemplate) -> list[str]:
    """Profile-free required fields no column carries, beyond the page plant."""
    return [
        f for f in template.missing_for_profile_free if f != PROFILE_SUPPLIED_FIELD
    ]


def _profile_free(plant_code: str | None, template: SheetTemplate) -> ParseContext:
    """T42: read a WaveScan tab on its required columns, no profile needed.

    Prototype `parseSheets` shape, enterprise-safe: every field still maps
    through `ref_column_alias`, nothing is matched by inventing a header, and
    identity is still the cleaner's (AGENTS rule 6). The page plant supplies
    `plant` when the tab has no Plant column -- the same fill a
    `fill_missing_plant` profile makes (T17 / ADR 0013 decision 3).

    Only a tab that would then be readable gets the supplied fields. Any
    other tab comes back exactly as described, so the refusal and the Admin
    proposal still show the honest header diff (``plant`` included).
    Duplicates and non-WaveScan tabs are refused by the caller, as before.

    T46: a FilmBuild tab is read the same way -- on its approved FILMTHICKNESS
    columns and PELT preamble -- and nothing is supplied to it: its plant is
    the batch's, and no film field is ever filled from a profile.
    """
    if (
        not plant_code
        or template.sheet_class not in (SHEET_WAVESCAN, SHEET_FILMTHICKNESS)
        or template.duplicates
        or template.domain == DOMAIN_FILMTHICKNESS
    ):
        return ParseContext(template=template, profile=None)
    candidate = replace(
        template,
        supplied=tuple(dict.fromkeys((*template.supplied, PROFILE_SUPPLIED_FIELD))),
    )
    if candidate.missing_for_profile_free:
        return ParseContext(template=template, profile=None)
    return ParseContext(template=candidate, profile=None)


def _apply_engineer_ignores(
    context: "ParseContext",
    ignored: Iterable[str],
    data: bytes,
    alias_map,
) -> "ParseContext":
    """Re-read the header row with the columns an Engineer chose to ignore.

    ADR 0013 decision 6. Only a header that was an unreviewed extra or a
    repeat of a field another column still carries can be ignored (the route
    refuses anything else), so the semantic signature the profile was chosen
    by cannot move. If it would, the ignore is not applied and the sheet
    stays blocked -- the same rule `_select_profile` uses for an owner's
    column policy.
    """
    wanted = {normalise_header(h) for h in ignored if normalise_header(h)}
    if not wanted:
        return context
    template = context.template
    merged = tuple(dict.fromkeys((*template.ignored, *sorted(wanted))))
    reread = _redescribe(data, template, alias_map, template.supplied, merged)
    if reread.semantic_signature != template.semantic_signature:
        log.warning(
            "engineer ignore would change the semantic contract; not applied",
            extra={"detail": f"sheet={template.sheet} ignored={sorted(wanted)}"},
        )
        return context
    return ParseContext(template=reread, profile=context.profile)


def _empty_template(sheet: str) -> SheetTemplate:
    return SheetTemplate(
        sheet=sheet, raw_headers=(), recognised={}, unrecognised=(),
        fingerprint="empty", domain=DOMAIN_WAVESCAN,
    )


def _describe_one(
    data: bytes, sheet: str, ref: ReferenceData, film: FilmReference
) -> SheetTemplate:
    """Which domain's header row this sheet carries (T26 S10, T46 F2).

    WaveScan first, on row 1 with the WAVESCAN vocabulary, exactly as
    before: a real CF sheet (checkzone + measures) is WaveScan even if some
    FilmBuild word also appears. Only a sheet that is **not** WaveScan is
    searched for a FilmBuild header, with the FILMTHICKNESS vocabulary --
    two maps, never merged, so neither domain can read the other's words.
    Anything else keeps its WaveScan classification (out of scope or
    unknown data), as T26 decided it.
    """
    try:
        template = describe_sheet(data, sheet, ref.column_alias, domain=DOMAIN_WAVESCAN)
    except ReaderError as exc:
        # An empty sheet is not a hostile file; record it as an unparseable
        # template rather than refusing the workbook (T26 S10).
        log.info("sheet not describable", extra={"detail": str(exc)})
        template = _empty_template(sheet)
    if template.sheet_class == SHEET_WAVESCAN:
        return template
    try:
        found = describe_film_sheet(data, sheet, film.column_alias)
    except ReaderError:
        found = None
    return found if found is not None else template


def _alias_for(template: SheetTemplate, ref: ReferenceData, film: FilmReference):
    """The one vocabulary a template was read under (spec S6 / F3)."""
    return film.column_alias if template.domain == DOMAIN_FILMTHICKNESS else ref.column_alias


def _redescribe(
    data: bytes,
    template: SheetTemplate,
    alias_map,
    supplied,
    ignored,
) -> SheetTemplate:
    """Re-read a header row with ignored columns, in its own domain."""
    if template.domain == DOMAIN_FILMTHICKNESS:
        found = describe_film_sheet(data, template.sheet, alias_map, ignored)
        return found if found is not None else template
    return describe_sheet(
        data, template.sheet, alias_map, supplied, ignored, template.domain
    )


def _commit_template_token(exc: TemplateError) -> str:
    """The commit blocker a refusal to read the sheet maps to (T26)."""
    if isinstance(exc, DuplicateFieldError):
        return BLOCKER_DUPLICATE_LOGICAL_FIELD
    if isinstance(exc, SheetNotWaveScan):
        return exc.sheet_class
    return BLOCKER_UNKNOWN_TEMPLATE


def _parse_columns(context: ParseContext) -> dict:
    """What this parse decided about the *sheet*, for `load_batch` (T26).

    Written on every outcome the worker records, not only the happy one,
    because the read path has to answer "why is this blocked" without opening
    a workbook (design section 6: no Excel on a GET). A replay re-derives all
    four from the stored bytes, so an approved alias or a published column
    policy clears `unreviewed_headers` the same way it clears anything else.
    """
    return {
        "domain": context.domain,
        "semantic_signature": context.semantic_signature,
        "sheet_class": context.sheet_class,
        "unreviewed_headers": list(context.unreviewed_headers),
    }


def _template_reason(exc: TemplateError) -> str:
    """Which stable token a refusal to read a sheet carries.

    Four now, not two. They are different questions for a person: is the
    contract unapproved, does the sheet say a thing twice, is it a data sheet
    of another kind, or is a column simply missing?
    """
    if isinstance(exc, ProfileMissing):
        return "PROFILE_UNKNOWN"
    if isinstance(exc, DuplicateFieldError):
        return BLOCKER_DUPLICATE_LOGICAL_FIELD
    if isinstance(exc, SheetNotWaveScan):
        return exc.sheet_class
    return "TEMPLATE_UNKNOWN"


def _reopenable(
    filename: str,
    digest: str,
    prior: Sequence[dict],
    expected_plant: str | None,
    may_restore_committed: bool,
) -> ReopenRequest:
    """Decide whether identical bytes may reopen the batches holding them.

    Raises `DuplicateUpload` -- 409, nothing written -- for every case T25
    keeps refused, and returns a `ReopenRequest` otherwise. Pure over the
    rows it is given; the status change itself is not made here.
    """
    other_plant = [p for p in prior if p.get("plant_code") != expected_plant]
    if other_plant:
        raise DuplicateUpload(
            filename, prior,
            why=(
                f"Those batches are filed under plant "
                f"{other_plant[0].get('plant_code') or '(none)'}, not "
                f"{expected_plant}, so this upload cannot reopen them. "
                f"Identical bytes are one workbook at one plant."
            ),
        )
    live = [p for p in prior if p["status"] not in batches.RETIRED_STATUSES]
    if live:
        raise DuplicateUpload(filename, prior)
    retired = [
        p for p in prior if p["status"] in batches.ADMIN_ONLY_RESTORE_STATUSES
    ]
    if retired and not may_restore_committed:
        raise DuplicateUpload(
            filename, prior,
            why=(
                "At least one of those sheets was committed and then retired, "
                "and bringing committed measurements back into the active "
                "reads is an Admin decision. Ask an Admin to upload the file "
                "again or to restore the batch. Nothing was reopened, "
                "including any abandoned sibling sheet."
            ),
        )
    return ReopenRequest(filename=filename, digest=digest, prior=tuple(prior))


def _scan_plant_column(
    data: bytes, sheet: str, column: int
) -> tuple[list[tuple[int, str]], int, int | None, int]:
    """One column of one sheet, before the workbook is stored.

    Returns ``(nonblank, blank_cells, first_blank_row, rows_scanned)`` where
    ``nonblank`` is ``(source_row, value as written)``. Row numbers are the
    spreadsheet's own, the same numbers ``reader.read_sheet`` gives a
    measurement, so a refusal names a cell a person can open.

    Entirely blank rows are skipped, exactly as the reader skips them, so the
    blank count here is the number of cells the cleaner will actually fill --
    not a count inflated by trailing empty rows openpyxl happens to report.

    This reads nothing but this column: `02-PIPELINE.md` §4 refuses an
    unknown template *without* interpreting its data rows, and knowing which
    plant wrote a file is not interpreting a measurement.
    """
    rows = iter_rows(data, sheet)  # T46: .xlsx or .ods alike
    try:
        nonblank: list[tuple[int, str]] = []
        blank_cells = 0
        first_blank_row: int | None = None
        rows_scanned = 0
        for offset, row in enumerate(rows):
            if offset == 0:
                continue  # header, already interpreted
            if all(
                v is None or (isinstance(v, str) and not v.strip()) for v in row
            ):
                continue
            rows_scanned += 1
            source_row = offset + 1
            value = row[column] if column < len(row) else None
            text_value = "" if value is None else str(value).strip()
            if text_value:
                nonblank.append((source_row, text_value))
            else:
                blank_cells += 1
                if first_blank_row is None:
                    first_blank_row = source_row
        return nonblank, blank_cells, first_blank_row, rows_scanned
    finally:
        rows.close()


def _jsonable(value):
    """One value, in a form both JSON and a stable hash can hold.

    `Decimal` becomes its own text rather than a float: L12 stores
    measurements at full precision, and `float(Decimal("60.90"))` would put a
    different number in the projection than the one commit inserts.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _apply_overrides(
    rows: Sequence[CleanRow], patches: dict[int, dict[str, Decimal | None]]
) -> tuple[list[CleanRow], dict[int, tuple[str, ...]]]:
    """Put a reviewer's current overrides onto the rows that would load (T21).

    Applied **after** dedup, and only to rows that are LOAD in this
    derivation: an override replaces what the instrument read for a row the
    reviewer saw loading, so it must not change which copy of a vehicle
    dedup keeps, and it never promotes a rejected, quarantined or duplicate
    row. Identity is untouched -- a patch can only name measure fields
    (revision 0008 `ck_override_field`).

    Returns new rows (the originals are not mutated) and, per source row,
    which fields were replaced, so a caller can prove every override it just
    wrote actually landed.
    """
    if not patches:
        return list(rows), {}
    out: list[CleanRow] = []
    applied: dict[int, tuple[str, ...]] = {}
    for row in rows:
        patch = {
            name: value for name, value in patches.get(row.source_row, {}).items()
            if name in MEASURE_ALL
        }
        if not patch:
            out.append(row)
            continue
        out.append(replace(row, measures={**row.measures, **patch}))
        applied[row.source_row] = tuple(sorted(patch))
    return out, applied


def _canonical_of(row: CleanRow) -> dict:
    """What committing this row would insert, as JSON.

    The same fields `batches.insert_measurements` writes, which is what makes
    the projection a proposal rather than a summary: a reviewer reading this
    is reading the measurement. ``paintline_omitted_reason`` is review-only
    (spec P8): it is not a ``wavescan`` column.
    """
    payload = {
        "measured_date": row.measured_date.isoformat(),
        "plant": row.plant,
        "model": row.model,
        "checkzone": row.checkzone,
        "color": row.color,
        "tolerance_group": row.tolerance_group,
        "paintline": row.paintline,
        "serial_no": row.serial_no,
        "src_zone_text": row.src_zone_text,
        "src_zone_no": row.src_zone_no,
        "measures": {m: _jsonable(row.measures.get(m)) for m in MEASURE_ALL},
    }
    if row.paintline_omitted_reason:
        payload["paintline_omitted_reason"] = row.paintline_omitted_reason
    # RO16: only when present, so a one-car sheet's projection (and revision)
    # is byte-for-byte today's.
    if row.car_key:
        payload["car_key"] = row.car_key
    # RO18 (B4): likewise only when true.
    if row.date_is_month_only:
        payload["date_is_month_only"] = True
    return payload


def _raw_by_source_row(raw_rows: Sequence) -> dict[int, dict]:
    """The file's own words, keyed by the row they were on."""
    return {
        raw.source_row: {
            "values": {k: _jsonable(v) for k, v in raw.values.items()},
            "extra": {k: _jsonable(v) for k, v in raw.extra.items()},
        }
        for raw in raw_rows
    }


def _projection(plan: Plan, raw_rows: Sequence, context: ParseContext) -> list[dict]:
    """Every source row of this parse, with its disposition (design section 6).

    Ordered by source row so the hash below is stable: two parses of the same
    bytes must produce the same revision, and a dict iteration order is not
    something to hash.

    Rejects and quarantined rows carry what is known about them rather than a
    full canonical row -- there is no cleaned row to show, which is precisely
    what the reviewer is being told.
    """
    raw_by_row = _raw_by_source_row(raw_rows)
    entries: list[dict] = []

    def entry(source_row, disposition, canonical, reason=None, detail=None,
              normalized=()):
        entries.append({
            "source_row": source_row,
            "disposition": disposition,
            "reason": reason,
            "detail": detail,
            "canonical": canonical,
            "raw": raw_by_row.get(source_row, {"values": {}, "extra": {}}),
            "normalized_fields": tuple(normalized),
        })

    for row in plan.clean:
        entry(
            row.source_row, "LOAD", _canonical_of(row),
            normalized=(
                (PROFILE_SUPPLIED_FIELD,)
                if row.plant_filled or row.plant_read_as else ()
            ),
        )
    for dup in plan.duplicates:
        row = dup.dropped
        entry(
            row.source_row, "DUPLICATE", _canonical_of(row),
            reason="DUPLICATE_ROW",
            detail=f"{dup.similarity:.0f}% match - kept {dup.kept_description}",
            normalized=(PROFILE_SUPPLIED_FIELD,) if row.plant_filled else (),
        )
    for rej in plan.result.rejects:
        entry(
            rej.source_row, "REJECT",
            {"offending_column": rej.column, "offending_value": rej.value,
             # RO16: a held row of a many-car sheet names its car.
             **({"car_key": rej.car_key} if rej.car_key else {})},
            reason=rej.reason, detail=rej.detail,
        )
    for agg in plan.aggregates:
        # T26 / spec S16. Present in the projection, never in the facts. The
        # canonical side records *why* it is not a fact -- which identity
        # columns carried a roll-up marker -- rather than a cleaned row,
        # because there is no vehicle here to clean.
        entry(
            agg.source_row, "AGGREGATE_ROW",
            {
                "plant": agg.plant,
                "aggregate_fields": list(agg.fields),
                "aggregate_values": dict(agg.values),
            },
            reason="AGGREGATE_ROW",
            detail=(
                "report roll-up: "
                + ", ".join(f"{f}={agg.values[f]!r}" for f in agg.fields)
                + ". Preserved as evidence and excluded from measurements -- "
                "its numbers summarise other rows of this file, so loading it "
                "would invent a vehicle (spec S16)."
            ),
        )
    for un in plan.result.unidentified:
        entry(
            un.source_row, "QUARANTINE",
            {
                "plant": un.plant,
                "serial_no": un.serial_no,
                "raw_model": un.raw_model,
                "measured_date": (
                    un.measured_date.isoformat() if un.measured_date else None
                ),
            },
            reason="UNIDENTIFIED_MODEL",
            detail=f"model {un.raw_model!r} is not a model this platform knows",
        )

    entries.sort(key=lambda e: e["source_row"])
    return entries


def _projection_of(plan, raw_rows: Sequence, context: ParseContext) -> list[dict]:
    """The review projection of either domain's plan (T46 dispatch)."""
    if isinstance(plan, FilmPlan):
        return _film_projection(plan, raw_rows)
    return _projection(plan, raw_rows, context)


def _film_body_labels(raw_rows: Sequence) -> list[str]:
    """T99. The Location of every row that claims to be a point of a truck.

    A blank Location names nothing and a specification limit row is not a
    point (T46), so neither is part of the walk the guard compares. The tail
    labels of D-99-6 are dropped by the caller, which knows the model.
    """
    return [
        label for label in (row.text("location") for row in raw_rows)
        if label and not is_limit_row(label)
    ]


def _film_body_rows(
    film: FilmReference, plant: str, model: str | None, raw_rows: Sequence
) -> list:
    """The rows whose labels the walk guard reads: `_film_body_labels` with
    the model's known tail (D-99-6) dropped, kept as rows (RO14)."""
    tails = film.tail_labels.get((plant, model), frozenset())
    return [
        row for row in raw_rows
        if (label := row.text("location")) and not is_limit_row(label)
        and normalise_location(label) not in tails
    ]


def _film_identities(rows: Sequence, meta: Mapping[str, object]) -> list[tuple]:
    """RO14. Each row's ``(Job Number, VIN)`` as the cleaner reads it (F14)."""
    return [
        (
            real_identity(row.get("job") if "job" in row.values else meta.get("job number")),
            real_identity(row.get("vin") if "vin" in row.values else meta.get("vin")),
        )
        for row in rows
    ]


def _film_walks(
    film: FilmReference, plant: str, model: str | None, raw_rows: Sequence,
    meta: Mapping[str, object],
) -> list[list]:
    """RO14 (D-RO14-1). The sheet's body rows, one list per car's walk."""
    body = _film_body_rows(film, plant, model, raw_rows)
    labels = [row.text("location") for row in body]
    starts = walk_starts(
        labels, film.walk.get((plant, model), ()),
        _film_resolved(film, plant, model, labels),
        _film_identities(body, meta),
    )
    return [body[a:b] for a, b in zip(starts, starts[1:] + [len(body)])]


def _film_walks_mixed(
    walks: Sequence[Sequence], meta: Mapping[str, object]
) -> tuple[str, str] | None:
    """RO14 (D-RO14-3). One car is one day and one colour.

    A walk whose rows carry two days, or two colours as written, holds the
    whole sheet. A blank or unreadable cell is that row's own fault (the
    cleaner says so) and is not a second value.
    """
    for index, walk in enumerate(walks):
        days: dict[object, None] = {}
        colours: dict[str, None] = {}
        for row in walk:
            day, _ = parse_film_date(
                row.get("date") if "date" in row.values else meta.get("date")
            )
            if day is not None:
                days.setdefault(day.isoformat(), None)
            colour = row.text("color") if "color" in row.values else None
            if colour:
                colours.setdefault(colour.strip(), None)
        for what, seen in (("date", list(days)), ("colour", list(colours))):
            if len(seen) > 1:
                car = car_of(index, len(walks), walk[0].source_row)
                return (
                    REASON_FILM_WALK_UNKNOWN,
                    walk_mixed_detail(car, what, seen[0], seen[1]),
                )
    return None


def _film_resolved(
    film: FilmReference, plant: str, model: str | None, labels: Sequence[str]
) -> dict[str, str]:
    """T109. ``{label as written: the live point it resolves to}``.

    Only the labels a **remembered answer** moves -- an alias or an
    owner-proved map row -- are in it: a label that is already a live name of
    the walk needs no entry, and a label nothing answers must stay unresolved
    so the guard reports it as unknown and the row asks about it.
    """
    out: dict[str, str] = {}
    for label in labels:
        point = film.resolve_point(plant, model, label)
        if point and normalise_location(point) != normalise_location(label):
            out[label] = point
    return out


def _film_sheet_date(
    conn: Connection, batch: dict, template: SheetTemplate, raw_rows: Sequence,
) -> tuple[tuple[str, str] | None, date | None, bool]:
    """RO18. ``(sheet hold, the date every row takes, month only)``.

    **B4 (RO09):** a sheet with no date anywhere -- no column, no ``Date:`` --
    is held with one question until a person names the month; then every row
    is the 1st of it, ``date_is_month_only``.

    **B3:** when the file name carries exactly one full date and a row's date
    is more than ``FILE_DATE_TOLERANCE_DAYS`` from it, the sheet is held with
    one question until a person says which is right; "the file name" then
    dates every row. Within the tolerance the sheet's own date stands.
    """
    answers = worksheet_repo.sheet_date_answers(conn, int(batch["load_id"]))
    meta = template.meta_map
    has_column = "date" in set(template.recognised.values())
    if not has_column and str(meta.get("date") or "").strip() == "":
        month = parse_month_answer(answers["month"])
        if month is not None:
            return None, month, True
        return (
            (REASON_MONTH_UNKNOWN, month_question_detail(batch["source_file"])),
            None, False,
        )
    named = file_name_date(batch["source_file"])
    if named is None:
        return None, None, False
    days = sorted({
        day for day, _ in (
            parse_film_date(row.get("date") if "date" in row.values else meta.get("date"))
            for row in raw_rows
            if row.text("location") and not is_limit_row(row.text("location"))
        ) if day is not None
    })
    far = [day for day in days if abs((day - named).days) > FILE_DATE_TOLERANCE_DAYS]
    if not far or answers["date"] == "sheet":
        return None, None, False
    if answers["date"] == "file_name":
        return None, named, False
    return (REASON_FILM_DATE_DISAGREES, film_date_question(far[0], named)), None, False


def _film_sheet_rules(
    conn: Connection,
    batch: dict,
    film: FilmReference,
    raw_rows: Sequence,
    model: ModelResolution,
    meta: Mapping[str, object],
) -> tuple[
    tuple[str, str] | None,
    tuple[str, str] | None,
    tuple[str, str] | None,
    ModelResolution,
]:
    """T99: everything about the **sheet** rather than one of its rows.

    Returns ``(sheet hold, sheet waiting, colour-code disagreement, the model
    to use)``. The **hold** is a sheet-wide question -- the walk, the Job
    Number, the two models -- and every row carries its sentence. The
    **waiting** (T109-FIX, D-109F-1) is a sheet with an unanswered label on
    it: the questions stay in the rows that wrote those labels, and every row
    whose own label resolved waits rather than loads.

    The whole of T99's ingest half is one function on purpose: the Job
    Number, the two models the file and the Job Number may name, and the walk
    are three questions about the same sheet, they are answered in that order
    (you cannot check a walk until you know which walk), and each answer is
    the uploader's to give. A plant with no ``film_point_setting`` row gets
    ``(None, None, model)`` and the cleaner behaves exactly as it did before
    T99 -- that is D-99-12, kept by this one early return rather than by a
    flag threaded through the cleaner.
    """
    plant = batch["plant_code"]
    if not film.plant_has_setting(plant):
        return None, None, None, model

    filename = batch["source_file"]
    answers = worksheet_repo.film_sheet_answers(conn, int(batch["load_id"]))

    # --- D-99-10: the Job Number's shape ------------------------------
    job = meta.get("job number")
    verdict = read_job_no(film.job_pattern.get(plant), job)
    if not verdict.ok and not answers["job_as_written"]:
        return (REASON_FILM_JOB_UNUSUAL, verdict.detail), None, None, model

    # --- D-99-11: the file and the Job Number naming two models -------
    file_token = ftm_filename_token(filename)
    conflict = model_conflict(
        verdict.model_token, file_token, film.model_alias, plant=plant
    )
    chosen = answers["model"]
    if conflict and not chosen:
        return (
            REASON_FILM_MODEL_CONFLICT,
            model_conflict_detail(
                *conflict, job=str(job or "").strip(), filename=filename
            ),
        ), None, None, model
    if chosen and chosen != model.model:
        # D-99-4 / D-99-11: the person who uploaded the sheet chose, and the
        # choice overrides only the model. Every other rule still runs.
        model = ModelResolution(
            chosen, model.token, "uploader_choice",
            f"the uploader chose {chosen} for this sheet (T99, D-99-11); the "
            f"names said: {model.detail}",
        )

    # --- D-99-11: the colour codes disagreeing is a warning, not a hold
    file_colour = ftm_filename_colour_token(filename)
    colour_tokens = (
        (verdict.color_token, file_colour)
        if verdict.color_token and file_colour
        and verdict.color_token != file_colour
        else None
    )

    # --- D-99-7: the walk ----------------------------------------------
    if not film.has_setting(plant, model.model):
        return None, None, colour_tokens, model
    known = film.walk.get((plant, model.model), ())
    body = _film_body_rows(film, plant, model.model, raw_rows)
    labels = [row.text("location") for row in body]
    # RO14 (D-RO14-2): a sheet of several cars is checked car by car.
    walked = check_walks(
        labels, known, rows=[row.source_row for row in body],
        plant=plant, model=model.model,
        identities=_film_identities(body, meta),
        # T109 (section 3.5): the guard runs on **resolved** names. A label a
        # person has aliased onto a live point is that point here, in its
        # place on the walk, so answering one row's question can turn an
        # out-of-order sheet into the walk we know rather than leaving it
        # held for ever.
        resolved=_film_resolved(film, plant, model.model, labels),
    )
    # T109 (D-109-6): a sheet that `holds` is one sheet-wide question, and
    # every row carries its sentence.
    if walked.holds:
        return (
            (REASON_FILM_WALK_UNKNOWN, walked.detail), None,
            colour_tokens, model,
        )
    # T109-FIX (D-109F-1): a label the live list does not hold is still asked
    # about in its own row by the cleaner -- which reaches the same answer by
    # the same `resolve_point` -- but **nothing on the sheet loads** while any
    # of them is unanswered. A walk renumbered down writes live names one spot
    # out, so the rows that "resolve" would be filed onto the wrong points of
    # the truck. When every label is answered the replay runs this check again
    # on the resolved names (D-109F-2).
    if walked.unknown:
        return (
            None, (REASON_FILM_POINT_WAITING, walked.detail),
            colour_tokens, model,
        )
    return None, None, colour_tokens, model


def _film_canonical(row: FilmRow) -> dict:
    """What committing this film row inserts: one fact per layer listed."""
    return {
        "domain": DOMAIN_FILMTHICKNESS,
        "measured_date": row.measured_date.isoformat(),
        "plant": row.plant,
        "model": row.model,
        "color": row.color,
        "job_no": row.job_no,
        "serial_no": row.serial_no,
        "point_code": row.point_code,
        "orientation": row.orientation,
        "src_location_text": row.src_location_text,
        "logical_vehicle_id": row.logical_vehicle_id,
        "layers": {code: _jsonable(v) for code, v in sorted(row.layers.items())},
        # RO18 (B4): only when true, so every stored projection is unchanged.
        **({"date_is_month_only": True} if row.date_is_month_only else {}),
    }


def _film_projection(plan: FilmPlan, raw_rows: Sequence) -> list[dict]:
    """Every source row of a film parse with its disposition (T46).

    The same five dispositions and the same revision hash as WaveScan, so
    acknowledgement, commit and the workbook reads need no second path.
    Held rows (extra point, unmapped location, unresolved model) are
    QUARANTINE with their own reason token; the location they carry is the
    offending value a reviewer is shown.
    """
    raw_by_row = _raw_by_source_row(raw_rows)
    entries: list[dict] = []

    def entry(source_row, disposition, canonical, reason=None, detail=None):
        entries.append({
            "source_row": source_row,
            "disposition": disposition,
            "reason": reason,
            "detail": detail,
            "canonical": canonical,
            "raw": raw_by_row.get(source_row, {"values": {}, "extra": {}}),
            "normalized_fields": (),
        })

    for row in plan.clean:
        # T99 (D-99-11): a loading row may still carry a warning.
        entry(row.source_row, "LOAD", _film_canonical(row), detail=row.warning)
    for dup in plan.duplicates:
        entry(dup.row.source_row, "DUPLICATE", _film_canonical(dup.row),
              reason="DUPLICATE_ROW", detail=dup.detail)
    for rej in plan.result.rejects:
        entry(rej.source_row, "REJECT",
              {"offending_column": rej.column, "offending_value": rej.value},
              reason=rej.reason, detail=rej.detail)
    for agg in plan.aggregates:
        label = ", ".join(repr(v) for v in agg.values.values())
        entry(agg.source_row, "AGGREGATE_ROW",
              {"plant": agg.plant, "aggregate_fields": list(agg.fields),
               "aggregate_values": dict(agg.values)},
              # T99 (D-99-6): a film sheet now has two kinds of kept-and-not-
              # loaded row -- a specification limit, and the known tail of
              # the plant's walk. The cleaner says which.
              reason=agg.reason or REASON_LIMIT_ROW,
              detail=(
                  tail_label_detail(
                      str(agg.values.get("location") or label),
                      plant=plan.plant, model=plan.model.model or "this model",
                  )
                  if agg.reason == REASON_FILM_TAIL_LABEL else
                  not_a_point_detail(
                      str(agg.values.get("location") or label),
                      plant=plan.plant, model=plan.model.model or "this model",
                  )
                  if agg.reason == REASON_FILM_NOT_A_POINT else
                  "specification limit row under the Location header "
                  f"({label}). "
                  "Preserved as evidence; it names no point of a car."
              ))
    for held in plan.result.held:
        entry(held.source_row, "QUARANTINE",
              {"domain": DOMAIN_FILMTHICKNESS, "plant": plan.plant,
               "model": plan.model.model,
               "offending_column": "location", "offending_value": held.location},
              reason=held.reason, detail=held.detail)
    entries.sort(key=lambda e: e["source_row"])
    return entries


def _film_duplicate_reject(dup: FilmDuplicate) -> Reject:
    """A film duplicate, written to `reject_log` as DUPLICATE_ROW."""
    row = dup.row
    return Reject(
        reason="DUPLICATE_ROW",
        detail=dup.detail,
        source_file=row.source_file,
        source_sheet=row.source_sheet,
        source_row=row.source_row,
        raw=_film_canonical(row),
        column="location",
        value=row.src_location_text,
    )


def _review_revision(entries: Sequence[dict]) -> str:
    """A hash of what this parse decided, row by row.

    Deliberately over the *decisions* -- row, disposition, reason, canonical
    values -- and not over the raw cells, because the raw cells come from
    bytes that cannot change (the store is content-addressed) while the
    decisions depend on reference data that can. That is exactly the drift
    `commit_batch` has to refuse: the same workbook, the same row count, a
    different meaning.
    """
    payload = json.dumps(
        [
            [e["source_row"], e["disposition"], e["reason"], e["canonical"]]
            for e in entries
        ],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def required_acknowledgements(batch: dict) -> list[str]:
    """Which warning categories this batch must have acknowledged, if any.

    Driven by the counts the parse produced, so the question is always "did
    rows not become measurements", never "did somebody remember to look".
    Each of the three means the plant sent rows this commit will not load:

    * `REJECTED_ROWS` -- a value the platform would not accept.
    * `QUARANTINED_MODELS` -- a vehicle whose model is not named, held back
      rather than guessed (`AGENTS.md` rule 6).
    * `DUPLICATE_ROWS` -- a measurement this platform already holds.

    `POSSIBLE_REPLACEMENT` is not here on purpose: it is advisory, it does
    not block a commit, and it never retires anything by itself (T19 locked
    decision 7, design M14).
    """
    required: list[str] = []
    if batch["rows_rejected"]:
        required.append(acknowledgements.CATEGORY_REJECTED_ROWS)
    if batch["rows_quarantine"]:
        required.append(acknowledgements.CATEGORY_QUARANTINED_MODELS)
    if batch["rows_duplicate"]:
        required.append(acknowledgements.CATEGORY_DUPLICATE_ROWS)
    return required


def unacknowledged_categories(conn: Connection, batch: dict) -> list[str]:
    """Required categories nobody has acknowledged **at this revision**.

    The revision is what makes this a gate rather than a checkbox: an
    acknowledgement is a statement about the rows a person read, so a replay
    that changes what the rows mean leaves the old acknowledgement in place
    as evidence and stops it satisfying this (design section 10). A batch
    with no projection has nothing to acknowledge and is refused for that
    instead (`NO_REVIEW_PROJECTION`).
    """
    required = required_acknowledgements(batch)
    if not required:
        return []
    revision = batch.get("review_revision")
    revision = str(revision).strip() if revision else None
    if not revision:
        return required
    have = acknowledgements.acknowledged(conn, batch["load_id"], revision)
    return [c for c in required if c not in have]


def commit_blockers(conn: Connection, batch: dict) -> list[str]:
    """Why this batch cannot be committed right now, as stable tokens.

    Read entirely from what is already stored -- the batch row, its profile,
    and the persisted projection. **No workbook is opened.** Design section 6
    is explicit that the review reads must not re-parse Excel on every GET,
    and `committable` is a read.

    The authoritative check is still `commit_batch`, which re-derives from
    the bytes. This list is what a reviewer is shown so that pressing the
    button is not how they find out.
    """
    tokens: list[str] = []
    counts = batches.BatchCounts(
        rows_in_file=batch["rows_in_file"],
        rows_loaded=batch["rows_loaded"],
        rows_duplicate=batch["rows_duplicate"],
        rows_rejected=batch["rows_rejected"],
        rows_quarantine=batch["rows_quarantine"],
    )
    if batch["status"] != batches.STATUS_PENDING_REVIEW:
        tokens.append(BLOCKER_NOT_PENDING_REVIEW)
    if not counts.balanced:
        tokens.append(BLOCKER_UNBALANCED)

    # T26 (S8, S10). Read from what the parse recorded on the batch and from
    # the header interpretation stored beside it -- still no workbook opened.
    sheet_class = batch.get("sheet_class")
    if sheet_class == SHEET_OUT_OF_SCOPE:
        tokens.append(BLOCKER_OUT_OF_SCOPE_SHEET)
    elif sheet_class == SHEET_UNKNOWN_DATA:
        tokens.append(BLOCKER_UNKNOWN_DATA_SHEET)

    headers = batch.get("raw_headers") or {}
    if isinstance(headers, dict) and headers.get("duplicate_fields"):
        tokens.append(BLOCKER_DUPLICATE_LOGICAL_FIELD)

    if batch.get("unreviewed_headers"):
        tokens.append(BLOCKER_UNREVIEWED_HEADER)

    profile = profiles.get_profile(conn, batch["profile_id"])
    if batch["profile_id"] is None:
        # T42: a tab read on the profile-free contract has no profile and
        # needs none. The worker only records a review projection for a tab
        # it parsed, so a projected WaveScan tab without a profile is one.
        # T46: the same holds for a FilmBuild tab read on its columns.
        if not (
            batch.get("review_revision")
            and sheet_class in (SHEET_WAVESCAN, SHEET_FILMTHICKNESS)
        ):
            tokens.append(BLOCKER_UNKNOWN_TEMPLATE)
    elif profile is None or not profile["is_active"]:
        tokens.append(BLOCKER_UNKNOWN_TEMPLATE)
    elif not profile["fixture_verified"]:
        tokens.append(BLOCKER_UNVERIFIED_PROFILE)

    if batch["status"] == batches.STATUS_PENDING_REVIEW and not batch["review_revision"]:
        tokens.append(BLOCKER_NO_REVIEW_PROJECTION)

    # T19. A warning is acknowledged or the commit waits. Only asked of a
    # PENDING_REVIEW batch: a committed or superseded one is already refused
    # by NOT_PENDING_REVIEW, and asking would hang a permanent blocker on
    # every batch committed before this gate existed.
    if batch["status"] == batches.STATUS_PENDING_REVIEW and unacknowledged_categories(
        conn, batch
    ):
        tokens.append(BLOCKER_WARNINGS_UNACKNOWLEDGED)

    # T39 (ADR 0013 decision 2): VEHICLE_IDENTITY_MISSING and
    # PAINTLINE_MISSING are no longer raised -- blank serial and booth load
    # NULL at every plant. T26 S16 (roll-up only) still is.
    dispositions = batches.review_dispositions(conn, batch["load_id"])
    if (
        dispositions.get("AGGREGATE_ROW")
        and not batch["rows_loaded"]
        and not dispositions.get("REJECT")
        and not dispositions.get("QUARANTINE")
        and not dispositions.get("LOAD")
        and not dispositions.get("DUPLICATE")
    ):
        tokens.append(BLOCKER_AGGREGATE_ONLY_SHEET)

    return tokens


def _out_of_scope_rows(plan: Plan, expected_plant: str | None) -> list[CleanRow]:
    """Cleaned rows that do not belong to the batch's plant.

    Replaces T04's ``_dominant_plant``, which asked the opposite question --
    "which plant do these rows agree on, and NULL if they do not" -- and
    wrote the answer onto the batch after the fact. T17 decides the plant
    before the bytes are stored, so the only remaining question is whether
    anything disagrees with it, and disagreement is a failure rather than a
    NULL.

    ``expected_plant`` is None only for a batch opened before T17; those keep
    the old behaviour of not being scope-checked at all rather than failing
    retroactively.
    """
    if not expected_plant:
        return []
    return [row for row in plan.clean if row.plant != expected_plant]


__all__ = [
    "IngestService",
    "IngestError",
    "DuplicateUpload",
    "UploadOutcome",
    "SheetOutcome",
    "SheetPlantScan",
    "ReopenRequest",
    "ParseContext",
    "ProfileMissing",
    "ProfilePublishRefused",
    "SheetNotWaveScan",
    "commit_blockers",
    "BLOCKER_UNREVIEWED_HEADER",
    "BLOCKER_DUPLICATE_LOGICAL_FIELD",
    "BLOCKER_PAINTLINE_MISSING",
    "BLOCKER_OUT_OF_SCOPE_SHEET",
    "BLOCKER_UNKNOWN_DATA_SHEET",
    "BLOCKER_AGGREGATE_ONLY_SHEET",
    "BLOCKER_UNKNOWN_TEMPLATE",
    "BLOCKER_UNVERIFIED_PROFILE",
    "BLOCKER_VEHICLE_IDENTITY_MISSING",
    "BLOCKER_NOT_PENDING_REVIEW",
    "BLOCKER_UNBALANCED",
    "BLOCKER_NO_REVIEW_PROJECTION",
    "BLOCKER_WARNINGS_UNACKNOWLEDGED",
    "required_acknowledgements",
    "unacknowledged_categories",
]
