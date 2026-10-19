"""`POST /api/v1/uploads` -- the Engineer's way in.

Replaces the reserved stub of the same path (T03 `api/v1/reserved.py`); the
URL and the required role are unchanged, so no generated client breaks.

Everything this route decides is one of five answers, and each has a status
code that means what it says:

* **422 (validation)** -- the request did not say which plant it is for.
  `expected_plant` is a required multipart field alongside `files` (T17):
  an upload is made from one plant's page and carries that plant's code.
* **400** -- a door check refused the file (`02-PIPELINE.md` §2), the
  declared plant is not a plant, or a sheet's own Plant column names a
  different one. No `load_batch` row and no stored object exist afterwards,
  which is the property that makes a rejected upload leave no trail for a
  reviewer to explain.
* **409** -- these exact bytes are already ingested and still live, filed
  under another plant, or (for an Engineer) retired after commit. The
  response names the prior `load_id`. The unique key in the database is the
  real guard; the lookup below is the polite version of the same answer.
* **202 without a new batch (T25)** -- these exact bytes belong to sheets
  that are ABANDONED, or (for an Admin) SUPERSEDED. Those same `load_id`s
  are brought back through the correction service, in this transaction:
  nothing is stored again, no batch is inserted, no job is queued.
* **422** -- the file is a valid workbook for a plant that is not onboarded
  (D5). Also no batch.
* **202** -- accepted, queued, one batch per data sheet, every batch filed
  under `expected_plant`; out-of-scope sheets are workbook evidence (RO19).

**Why `expected_plant` is required rather than inferred.** The plant is the
scope of everything downstream: which page the evidence appears on, whose
rows a correction touches, what a dashboard counts. Inferring it from the
cells means a workbook that mixes plants, or one whose Plant column is
blank, gets a plant chosen by majority vote or left NULL. Requiring it means
the person uploading states the scope and the server checks the file against
that statement -- and refuses rather than relabels when they disagree
(`docs/superpowers/specs/2026-09-16-plant-data-manager-design.md` M3).

The route contains no SQL and no parsing: it hands bytes to
`services/ingest.py`, which is the single parser (`02-PIPELINE.md` §10).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    EngineerPrincipal,
    WriteConnection,
    get_correction_service,
    get_ingest_service,
)
from app.core.correlation import correlation_id_of
from app.schemas.common import ErrorResponse
from app.schemas.corrections import RestoreCreate
from app.schemas.ingest import UploadAccepted, UploadedSheet
from app.services.corrections import (
    IDENTICAL_UPLOAD_REASON,
    CorrectionError,
    CorrectionService,
)
from app.services.ingest import (
    DuplicateUpload,
    IngestError,
    IngestService,
    SheetOutcome,
)
from app.services.upload_guard import GuardLimits, UploadRejected, check_request_size

log = logging.getLogger("app.api.uploads")

router = APIRouter(tags=["ingest"])


@router.post(
    "/uploads",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        409: {
            "model": ErrorResponse,
            "description": (
                "Identical bytes are already held by a live batch "
                "(PENDING_REVIEW, RUNNING, COMMITTED, FAILED or "
                "REJECTED_TEMPLATE), by batches filed under another plant, or "
                "-- for an Engineer -- by a batch that was committed and then "
                "retired (SUPERSEDED). Nothing was stored or reopened. "
                "Identical bytes whose batches are all ABANDONED (or, for an "
                "Admin, SUPERSEDED) are reopened instead and answer 202 with "
                "those same load_ids (T25)."
            ),
        },
    },
    summary="Upload one or more WaveScan workbooks. Engineer role.",
)
def create_upload(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    service: Annotated[IngestService, Depends(get_ingest_service)],
    corrections: Annotated[CorrectionService, Depends(get_correction_service)],
    files: Annotated[list[UploadFile], File(description=".xlsx, .xlsm or .ods (T46: SAP PELT Quick Summary)")],
    expected_plant: Annotated[
        str,
        Form(
            min_length=1,
            description=(
                "The plant this upload belongs to, as a ref_plant.plant_code "
                "(for example AAT). Required. Every sheet's Plant column must "
                "agree with it; blank plant cells are filled from it and the "
                "fill is counted on the batch's audit event."
            ),
            examples=["AAT"],
        ),
    ],
) -> UploadAccepted:
    # Door checks on count and size happen *before* the bytes become a
    # Python object. Reading each part unbounded would let a 2 GB "xlsx"
    # sit in RAM and only then be refused -- the opposite of
    # `02-PIPELINE.md` §2. Cap the read at the configured limit + 1 so
    # `check_file` can still say TOO_LARGE, and refuse a 41-file request
    # without opening any of them.
    # A present-but-blank field passes `min_length` once it is whitespace,
    # and "which plant?" is not a question this route may answer with a
    # guess, so it is refused with the same 422 shape a missing field gets.
    if not expected_plant.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "expected_plant: this upload must name the plant it belongs "
                "to (a ref_plant.plant_code such as AAT). Nothing was stored."
            ),
        )

    settings = request.app.state.settings
    limits = GuardLimits(
        max_file_bytes=settings.upload_max_file_bytes,
        max_files=settings.upload_max_files,
        max_uncompressed_bytes=settings.upload_max_uncompressed_bytes,
        max_compression_ratio=settings.upload_max_compression_ratio,
    )
    try:
        check_request_size(len(files), limits)
    except UploadRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{exc.reason}: {exc.detail}",
        ) from exc

    payload: list[tuple[str, bytes]] = []
    cap = limits.max_file_bytes
    for upload in files:
        payload.append((upload.filename or "", upload.file.read(cap + 1)))

    correlation_id = correlation_id_of(request)
    try:
        outcome = service.accept_upload(
            conn,
            payload,
            expected_plant=expected_plant.strip(),
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id,
            # T25: only an Admin may bring committed-then-retired
            # measurements back into the active reads by re-uploading them.
            may_restore_committed=principal.has_role("admin"),
        )
        # T25: identical bytes of retired sheets. Ingest decided they may
        # come back and wrote nothing; the status change is the correction
        # service's, in this same transaction, so a refusal below rolls back
        # every batch this request opened as well.
        for request_ in outcome.reopen:
            by_id = {int(p["load_id"]): p for p in request_.prior}
            for load_id in request_.load_ids:
                restored = corrections.restore_batch(
                    conn,
                    load_id,
                    RestoreCreate(reason=IDENTICAL_UPLOAD_REASON),
                    actor_user_id=principal.user_id or "",
                    correlation_id=correlation_id,
                )
                outcome.sheets.append(
                    SheetOutcome(
                        filename=request_.filename,
                        sheet=by_id[load_id]["source_sheet"],
                        load_id=load_id,
                        status=restored["status"],
                        detail=(
                            f"{IDENTICAL_UPLOAD_REASON}: load_id {load_id} "
                            f"{restored['previous_status']} -> "
                            f"{restored['status']} ({restored['audit_action']}). "
                            f"No new batch, no new stored object, nothing "
                            f"queued."
                        ),
                    )
                )
    except CorrectionError as exc:
        # The batch moved between the hash lookup and its row lock -- a
        # concurrent abandon, supersede or restore. Nothing is kept.
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except UploadRejected as exc:
        # Door check, or the T17 plant gate. Nothing has been written: both
        # run across every file in the request before the first batch is
        # opened and before a single byte reaches the object store.
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
                if exc.reason == "PLANT_NOT_ONBOARDED"
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=f"{exc.reason}: {exc.detail}",
        ) from exc
    except DuplicateUpload as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        # The database's own UNIQUE (file_hash, source_sheet) got there first:
        # two identical uploads racing each other. The constraint is the
        # guard; the SELECT above is only the friendly version of it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "These bytes were ingested by a concurrent request. The unique "
                "key on (file_hash, source_sheet) refused the second copy, so "
                "nothing was duplicated."
            ),
        ) from exc
    except IngestError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return UploadAccepted(
        accepted_files=len(outcome.file_hash_by_name),
        skipped_sheets=outcome.skipped_sheets,
        batches=[
            UploadedSheet(
                filename=sheet.filename,
                sheet=sheet.sheet,
                load_id=sheet.load_id,  # type: ignore[arg-type]
                status=sheet.status,
                detail=sheet.detail,
            )
            for sheet in outcome.sheets
        ],
    )
