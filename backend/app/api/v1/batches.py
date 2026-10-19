"""Batch reads, and the commit that turns a reviewed batch into measurements.

`POST /api/v1/batches/{load_id}/commit` replaces the reserved stub of the
same path; the URL and the Engineer role are unchanged. T09 does the same for
`POST /api/v1/batches/{load_id}/supersede`, which is **Admin** -- and the two
being different roles is the point: `02-PIPELINE.md` §3 wants a re-sent
workbook to retire the old batch, and §7 makes retiring an Admin decision, so
commit must not do it as a side effect. It does not, and a test asserts that
nothing in the ingest service can reach the supersede path.

The two `GET` routes are **new in T04** and recorded as a contract change in
`docs/reports/T04-INGEST.md`. They are not optional extras: upload answers
202 because parsing happens in a worker, so a client that cannot ask what
became of a batch cannot use the upload route at all. `02-PIPELINE.md` §7
also makes review "a persisted proposal, not a dry-run reprint" -- these are
what makes it persisted rather than printed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.api.deps import (
    AdminPrincipal,
    DbConnection,
    EngineerPrincipal,
    WriteConnection,
    get_correction_service,
    get_ingest_service,
)
from app.core.correlation import correlation_id_of
from app.core.security import CurrentPrincipal
from app.repositories import batches as repo
from app.repositories import ingest_jobs
from app.schemas.common import ErrorResponse, PageInfo
from app.schemas.corrections import (
    AbandonCreate,
    AbandonResult,
    RestoreCreate,
    RestoreResult,
    SupersedeCreate,
    SupersedeResult,
)
from app.schemas.ingest import (
    BatchCountsOut,
    BatchOut,
    BatchPage,
    BatchReviewOut,
    CommitResult,
    HeldLabelGroup,
    JobOut,
)
from app.services.corrections import CorrectionError, CorrectionService
from app.services.held_labels import held_label_items
from app.services.ingest import IngestError, IngestService, commit_blockers

router = APIRouter(prefix="/batches", tags=["ingest"])

LoadId = Annotated[int, Path(ge=1, description="load_batch.load_id")]


def batch_dto(row: dict, job: dict | None) -> BatchOut:
    """One `load_batch` row as the contract shape.

    Public rather than private since T19: the plant Data Manager lists
    the same sheets under a workbook, and two functions building the
    same DTO would be two places for a field to go missing.
    """
    counts = repo.BatchCounts(
        rows_in_file=row["rows_in_file"],
        rows_loaded=row["rows_loaded"],
        rows_duplicate=row["rows_duplicate"],
        rows_rejected=row["rows_rejected"],
        rows_quarantine=row["rows_quarantine"],
    )
    return BatchOut(
        load_id=row["load_id"],
        source_file=row["source_file"],
        source_sheet=row["source_sheet"],
        plant_code=row["plant_code"],
        file_hash=str(row["file_hash"]).strip(),
        status=row["status"],
        counts=BatchCountsOut(**counts.as_dict(), balanced=counts.balanced),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        loaded_by=str(row["loaded_by"]) if row["loaded_by"] else None,
        notes=row["notes"],
        superseded_by=row["superseded_by"],
        template_fingerprint=row["template_fingerprint"],
        # T26: the exact hash above is provenance; these three are what the
        # profile was selected by and what kind of sheet this turned out to
        # be. Additive -- nothing that was on this DTO has moved.
        domain=row.get("domain"),
        semantic_signature=row.get("semantic_signature"),
        sheet_class=row.get("sheet_class"),
        unreviewed_headers=list(row.get("unreviewed_headers") or []),
        profile_id=row.get("profile_id"),
        fixture_verified=bool(row.get("profile_fixture_verified")),
        review_revision=(
            str(row["review_revision"]).strip() if row.get("review_revision") else None
        ),
        job=JobOut(**{k: job[k] for k in
                      ("status", "attempts", "last_error", "enqueued_at",
                       "started_at", "finished_at")}) if job else None,
    )


def _held_labels(
    conn,
    load_id: int,
    unreviewed_headers: list[str] | None = None,
    plant_code: str | None = None,
) -> list[HeldLabelGroup]:
    """Group held spellings and attach existing catalogue candidates."""
    return [
        HeldLabelGroup(**item)
        for item in held_label_items(
            conn, load_id, plant_code=plant_code,
            unreviewed_headers=unreviewed_headers,
        )
    ]


@router.get(
    "",
    response_model=BatchPage,
    summary="Uploads and their outcomes, newest first.",
)
def list_batches(
    principal: CurrentPrincipal,
    conn: DbConnection,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BatchPage:
    rows = repo.list_batches(conn, limit=limit, offset=offset)
    items = [batch_dto(row, ingest_jobs.get_for_batch(conn, row["load_id"])) for row in rows]
    return BatchPage(
        items=items,
        page=PageInfo(
            limit=limit,
            offset=offset,
            total=repo.count_batches(conn),
            returned=len(items),
        ),
    )


@router.get(
    "/{load_id}",
    response_model=BatchReviewOut,
    summary="One batch, with the dispositions a reviewer needs before committing.",
)
def get_batch(principal: CurrentPrincipal, conn: DbConnection, load_id: LoadId) -> BatchReviewOut:
    row = repo.get_batch(conn, load_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No batch {load_id}."
        )
    dto = batch_dto(row, ingest_jobs.get_for_batch(conn, load_id))
    review = repo.batch_review(conn, load_id)
    # Read from what is stored -- the batch row, its profile and the persisted
    # projection. No workbook is opened on a GET (T18, design section 6).
    blockers = commit_blockers(conn, row)
    return BatchReviewOut(
        batch=dto,
        reject_reasons=review["reject_reasons"],
        unidentified_rows=review["unidentified_rows"],
        staged_rows=review["staged_rows"],
        review_rows=repo.count_review_rows(conn, load_id),
        review_dispositions=repo.review_dispositions(conn, load_id),
        commit_blockers=blockers,
        # One boolean, as T07 already uses: true only when pressing commit
        # would succeed. A reviewer should not discover a blocker by being
        # refused.
        committable=not blockers,
        held_labels=_held_labels(
            conn, load_id, unreviewed_headers=dto.unreviewed_headers or [],
            plant_code=row.get("plant_code"),
        ),
    )


@router.post(
    "/{load_id}/commit",
    response_model=CommitResult,
    summary="Commit a reviewed batch: insert its measurements. Engineer role.",
)
def commit_batch(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    service: Annotated[IngestService, Depends(get_ingest_service)],
    load_id: LoadId,
) -> CommitResult:
    """One transaction: measurements, audit event, batch status.

    The connection comes from the write dependency, so the whole thing
    commits together or not at all -- `02-PIPELINE.md` §9.
    """
    try:
        result = service.commit_batch(
            conn,
            load_id,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except IngestError as exc:
        message = str(exc)
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if "does not exist" in message
                else status.HTTP_409_CONFLICT
            ),
            detail=message,
        ) from exc

    counts = repo.BatchCounts(
        rows_in_file=result["rows_in_file"],
        rows_loaded=result["rows_loaded"],
        rows_duplicate=result["rows_duplicate"],
        rows_rejected=result["rows_rejected"],
        rows_quarantine=result["rows_quarantine"],
    )
    return CommitResult(
        load_id=load_id,
        status=repo.STATUS_COMMITTED,
        measurements_inserted=result["measurements_inserted"],
        counts=BatchCountsOut(**counts.as_dict(), balanced=counts.balanced),
    )


@router.post(
    "/{load_id}/supersede",
    response_model=SupersedeResult,
    responses={
        404: {"model": ErrorResponse, "description": "No such batch."},
        409: {
            "model": ErrorResponse,
            "description": (
                "The batch is not COMMITTED, is already superseded, or the "
                "named replacement is not a committed batch of the same "
                "plant. Nothing was written."
            ),
        },
    },
    summary="Retire a committed batch. Admin role. Never deletes it.",
)
def supersede_batch(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    service: Annotated[CorrectionService, Depends(get_correction_service)],
    load_id: LoadId,
    body: SupersedeCreate,
) -> SupersedeResult:
    """One column on `load_batch`, plus the audit event, in one transaction.

    The batch's measurements are untouched. They stop appearing in every
    reporting read because the active-data predicate tests the batch's status
    (`01-DATA-MODEL.md` §5), not because anything happened to them -- so the
    `wavescan` row count for this `load_id` is the same afterwards, and the
    response says how many rows that is.

    No `measurement_supersession` row is written. Retiring a batch is not a
    claim that each reading was replaced by a better one; that claim is what a
    correction makes, one row at a time.
    """
    try:
        result = service.supersede_batch(
            conn,
            load_id,
            body,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except CorrectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return SupersedeResult(**result)


@router.post(
    "/{load_id}/abandon",
    response_model=AbandonResult,
    responses={
        404: {"model": ErrorResponse, "description": "No such batch."},
        409: {
            "model": ErrorResponse,
            "description": (
                "The batch has wavescan rows, is COMMITTED (supersede it "
                "instead), is RUNNING, or is already ABANDONED or SUPERSEDED. "
                "Nothing was written."
            ),
        },
    },
    summary="Remove a sheet that never committed from review. Admin. Never deletes it.",
)
def abandon_batch(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    service: Annotated[CorrectionService, Depends(get_correction_service)],
    load_id: LoadId,
    body: AbandonCreate,
) -> AbandonResult:
    """T21. One column on `load_batch` plus the audit event, in one transaction.

    Allowed from PENDING_REVIEW, REJECTED_TEMPLATE and FAILED, and only while
    the batch has **zero** `wavescan` rows. The stored bytes, `stg_raw`, the
    review projection, acknowledgements, overrides and history all stay;
    replay and commit refuse an ABANDONED batch afterwards. A committed batch
    is never abandoned -- POST .../supersede with a reason is the tool for that.
    """
    try:
        result = service.abandon_batch(
            conn,
            load_id,
            body,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except CorrectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return AbandonResult(**result)


@router.post(
    "/{load_id}/restore",
    response_model=RestoreResult,
    responses={
        404: {"model": ErrorResponse, "description": "No such batch."},
        409: {
            "model": ErrorResponse,
            "description": (
                "The batch is neither ABANDONED nor SUPERSEDED, so there is "
                "nothing to restore. Nothing was written."
            ),
        },
    },
    summary="Bring one ABANDONED or SUPERSEDED sheet back. Admin. Never re-inserts facts.",
)
def restore_batch(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    service: Annotated[CorrectionService, Depends(get_correction_service)],
    load_id: LoadId,
    body: RestoreCreate,
) -> RestoreResult:
    """T25. The same mutation an identical-file upload makes, without a file.

    From SUPERSEDED the batch returns to COMMITTED and `superseded_by` is
    cleared; its `wavescan` rows were never touched and read as current again
    through `v_wavescan_active`. From ABANDONED it returns to the status it
    was abandoned from. One sheet per call, one `audit_event` each
    (`batch.restore` or `batch.reopen`), in the same transaction as the
    status change. No workbook is opened and no fact is written.
    """
    try:
        result = service.restore_batch(
            conn,
            load_id,
            body,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except CorrectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return RestoreResult(**result)
