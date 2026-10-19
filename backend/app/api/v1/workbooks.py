"""The plant Data Manager: reads for Engineer, its mutations Admin.

`/api/v1/plants/{plant_code}/workbooks...` is the contract the Files UI is
built against (design section 7, T19). T19 wrote five reads and one
append-only mutation, an **acknowledgement**. T21 adds two reads (vehicle
sets and their points) and a second append-only mutation, the **review
override**, which records a replacement for one measure of one pending row
and re-derives the sheet through the ingest service. Nothing here changes a
measurement, edits a projection cell in place, or moves a batch's status.

**Roles, on the server.** The seven reads are Engineer (Engineer or Admin;
RO12, owner 2026-10-13: the uploader sees the files they send); the
acknowledgement, override, purge and publish stay Admin (`03-SECURITY.md`
section 5). A Viewer gets 403, an unauthenticated caller 401. The RBAC of
the routes this phase does **not** own is unchanged -- upload and commit stay Engineer,
mapping approve and supersede stay Admin -- so T04, T08 and T09 keep meaning
what they meant, and chrome is still not security.

No SQL in this module (`00-ARCHITECTURE.md` section 5 rule 2), and no
workbook is opened by any of it.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.api.deps import (
    AdminPrincipal,
    DbConnection,
    EngineerPrincipal,
    EngineerReader,
    WriteConnection,
    get_ingest_service,
)
from app.api.v1.batches import batch_dto
from app.core.correlation import correlation_id_of
from app.core.security import CurrentPrincipal
from app.domain import workbooks as rules
from app.schemas.common import ErrorResponse, PageInfo
from app.schemas.ingest import BatchCountsOut
from app.schemas.workbooks import (
    AcknowledgementCreate,
    AcknowledgementOut,
    CurrentOverrideOut,
    Disposition,
    HistoryEventOut,
    Inbox,
    IssueOut,
    OverrideCreate,
    OverrideOut,
    OverrideResult,
    ReplacementHint,
    TemplateProfileOut,
    VehicleDispositionCounts,
    VehiclePointOut,
    VehiclePointPage,
    VehicleSetOut,
    VehicleSetPage,
    WorkbookDetailOut,
    WorkbookHistoryOut,
    WorkbookIssuesOut,
    WorkbookOut,
    WorkbookPage,
    WorkbookPurgeCreate,
    WorkbookPurgeResult,
    WorkbookRowFilters,
    WorkbookRowOut,
    WorkbookRowPage,
    WorkbookSheetOut,
)
from app.schemas.profiles import ProfilePublishCreate, ProfilePublished
from app.schemas.worksheet import (
    DecisionResult,
    FilmJobAnswerCreate,
    FilmModelAnswerCreate,
    FilmModelsOut,
    FilmDateAnswerCreate,
    FilmNotAPointCreate,
    FilmPointAddCreate,
    FilmPointAliasCreate,
    FilmPointChangeResult,
    FilmPointRestoreCreate,
    FilmPointRetireCreate,
    FilmPointSettingCreate,
    FilmPointSettingOut,
    FilmPointSettingResult,
    FilmTailLabelCreate,
    FilmTailLabelResult,
    FilmTailLabelRetireCreate,
    FilmWalkConfirmCreate,
    HoleApprovalCreate,
    IgnoreColumnsCreate,
    MonthAnswerCreate,
    PanelConfirmCreate,
    PlantAnswerCreate,
    PlantAnswerResult,
    WorkbookLoadResult,
    WorksheetOut,
)
from app.schemas.point_labels import (
    Domain,
    PointAliasesOut,
    PointAliasRetireCreate,
    PointAliasRetireResult,
    PointLabelChangeResult,
    PointLabelRenameCreate,
    PointLabelsOut,
)
from app.schemas.ws_points import (
    WsCompletenessImpactOut,
    WsPointAddCreate,
    WsPointChangeResult,
    WsPointListOut,
    WsPointModelsOut,
    WsPointRestoreCreate,
    WsPointRetireCreate,
    WsPointSettingCreate,
    WsPointSettingResult,
)
from app.services import point_labels as labels_service
from app.services import workbooks as service
from app.services import worksheet as worksheet_service
from app.services import ws_points as ws_points_service
from app.services.ingest import IngestService, ProfilePublishRefused
from app.services.workbooks import WorkbookError

router = APIRouter(prefix="/plants", tags=["data-manager"])

MAX_PAGE = 500

PlantCode = Annotated[
    str,
    Path(
        min_length=1,
        max_length=32,
        description=(
            "ref_plant.plant_code or any approved ref_plant_alias, in any "
            "case: /plants/ftm and /plants/FTM are one plant."
        ),
        examples=["AAT"],
    ),
]
FileHash = Annotated[
    str,
    Path(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the uploaded bytes, lower-case hex.",
    ),
]
FilmModelCode = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        description=(
            "T99: `ref_model.model_code` of a FilmThickness model this plant "
            "has a point list for, e.g. 'P703 RAPCAP'. A model the plant does "
            "not walk is a 404."
        ),
        examples=["P703 RAPCAP"],
    ),
]

WsModelCode = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        description=(
            "T114: `ref_model.model_code` of a Wave Scan model this plant has "
            "a live point list for, e.g. 'P703 DBL RANGER'. A model with no "
            "live list here is a 404, unless the plant offers it (RO17 "
            "D-RO17-10: an empty list that may take its first point)."
        ),
        examples=["P703 DBL RANGER"],
    ),
]

NOT_FOUND = {
    404: {
        "model": ErrorResponse,
        "description": (
            "No such plant, or no such workbook at this plant. A workbook "
            "filed under another plant is a 404 here rather than a redirect: "
            "one plant's file list must not leak through another's URL."
        ),
    }
}


def _sheet_dto(view: dict) -> WorkbookSheetOut:
    return WorkbookSheetOut(
        batch=batch_dto(view["row"], view["job"]),
        committable=view["committable"],
        commit_blockers=view["commit_blockers"],
        required_acknowledgements=view["required_acknowledgements"],
        acknowledged=view["acknowledged"],
    )


def _workbook_dto(item: dict) -> WorkbookOut:
    counts = item["counts"]
    return WorkbookOut(
        file_hash=item["file_hash"],
        plant_code=item["plant_code"],
        source_file=item["source_file"],
        operational_summary=item["operational_summary"],
        measured_date_min=item["measured_date_min"],
        measured_date_max=item["measured_date_max"],
        uploaded_at=item["uploaded_at"],
        loaded_by=item["loaded_by"],
        counts=BatchCountsOut(**counts.as_dict(), balanced=counts.balanced),
        sheet_count=item["sheet_count"],
        skipped_sheets=item.get("skipped_sheets", []),
        skipped_sheet_count=item.get("skipped_sheet_count", 0),
        superseded=item["superseded"],
        abandoned=item["abandoned"],
        vehicle_set_count=item["vehicle_set_count"],
        measured_dates_span_months=item["measured_dates_span_months"],
        sheets=[_sheet_dto(view) for view in item["sheets"]],
    )


def _refused(exc: WorkbookError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    "/{plant_code}/workbooks",
    response_model=WorkbookPage,
    responses=NOT_FOUND,
    summary="Workbooks filed under one plant, optionally as an upload inbox. Engineer.",
)
def list_workbooks(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    inbox: Annotated[
        Inbox,
        Query(
            description=(
                "all (default): every workbook, T19 order (no measured dates "
                "first, then measured_date_min DESC, file_hash). "
                "current_month: uploaded_at in uploaded_month (UTC); no "
                "measured dates first, then uploaded_at DESC, file_hash. "
                "needs_attention: uploaded_at NOT in uploaded_month and "
                "operational_summary PROCESSING, REVIEW_REQUIRED or "
                "PARTIALLY_COMMITTED; uploaded_at ASC, file_hash. Filtering "
                "is done by the server over the whole plant."
            )
        ),
    ] = "all",
    uploaded_month: Annotated[
        str | None,
        Query(
            pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
            description=(
                "YYYY-MM, a UTC calendar month of uploaded_at. Defaults to "
                "the current UTC month. Ignored by inbox=all."
            ),
            examples=["2026-09"],
        ),
    ] = None,
) -> WorkbookPage:
    """One card per `file_hash`; sheets are children.

    A plant this platform knows but has not onboarded (FVL, D5) answers an
    empty page with `plant_is_active: false`, not the 422 the upload route
    gives. Showing the plant and its reason is the point of the Data Manager;
    hiding it would make "four plants supported" look true.

    T21 adds the upload inbox. The default, `inbox=all`, is the T19 list
    unchanged. No week bucket is computed: the client places cards with
    `uploaded_at` and the documented day bands.
    """
    month = None
    if inbox != rules.INBOX_ALL:
        month = (
            rules.parse_month(uploaded_month) if uploaded_month
            else service.current_utc_month()
        )
    try:
        plant = service.resolve_plant(conn, plant_code)
        items, total = service.list_workbooks(
            conn, plant["plant_code"], limit=limit, offset=offset,
            inbox=inbox, uploaded_month=month,
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc
    return WorkbookPage(
        items=[_workbook_dto(item) for item in items],
        page=PageInfo(limit=limit, offset=offset, total=total, returned=len(items)),
        plant_code=plant["plant_code"],
        plant_is_active=bool(plant["is_active"]),
        inbox=inbox,
        uploaded_month=rules.format_month(month) if month else None,
    )


@router.get(
    "/{plant_code}/workbooks/{file_hash}",
    response_model=WorkbookDetailOut,
    responses=NOT_FOUND,
    summary="One workbook: sheets, profiles, replacement hint, acknowledgements. Engineer.",
)
def get_workbook(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
) -> WorkbookDetailOut:
    try:
        plant = service.resolve_plant(conn, plant_code)
        found = service.detail(conn, plant["plant_code"], file_hash)
    except WorkbookError as exc:
        raise _refused(exc) from exc
    return WorkbookDetailOut(
        workbook=_workbook_dto(found["workbook"]),
        profiles=[
            TemplateProfileOut(
                profile_id=p["profile_id"],
                template_fingerprint=p["template_fingerprint"],
                version=p["version"],
                is_active=p["is_active"],
                fixture_verified=p["fixture_verified"],
                fill_missing_plant=p["fill_missing_plant"],
                notes=p["notes"],
                load_ids=p["load_ids"],
            )
            for p in found["profiles"]
        ],
        possible_replacements=[
            ReplacementHint(**hint) for hint in found["possible_replacements"]
        ],
        acknowledgements=[
            _ack_dto(row) for row in found["acknowledgements"]
        ],
    )


@router.get(
    "/{plant_code}/workbooks/{file_hash}/rows",
    response_model=WorkbookRowPage,
    responses=NOT_FOUND,
    summary="Proposed or committed rows of one workbook, paginated. Engineer.",
)
def list_workbook_rows(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
    load_id: Annotated[
        int | None,
        Query(ge=1, description="One sheet of this workbook. 404 if it is not a child."),
    ] = None,
    disposition: Annotated[
        Disposition | None,
        Query(description="Filter the review projection. Omit for every row."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkbookRowPage:
    """Raw against canonical, without opening the workbook.

    Sheets in review come from the persisted projection. Committed and
    superseded sheets come from the projection joined to `wavescan`, so a row
    carries the `measurement_id` it produced -- **not** filtered through
    `v_wavescan_active`, because a retired file's rows are exactly what
    somebody opens this page to see. A sheet committed before the projection
    existed returns its facts with `raw` null and `projection_missing` true,
    rather than being re-parsed.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        items, total = service.rows(
            conn, plant["plant_code"], file_hash,
            load_id=load_id, disposition=disposition, limit=limit, offset=offset,
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc
    return WorkbookRowPage(
        items=[
            WorkbookRowOut(
                load_id=row["load_id"],
                source_sheet=row["source_sheet"],
                source_row=row["source_row"],
                disposition=row["disposition"],
                reason=row["reason"],
                detail=row["detail"],
                canonical=row["canonical"],
                raw=row["raw"],
                normalized_fields=list(row["normalized_fields"] or []),
                profile_id=row["profile_id"],
                template_fingerprint=row["template_fingerprint"],
                review_revision=(
                    str(row["review_revision"]).strip()
                    if row["review_revision"] else None
                ),
                measurement_id=row["measurement_id"],
                projection_missing=bool(row["projection_missing"]),
            )
            for row in items
        ],
        page=PageInfo(limit=limit, offset=offset, total=total, returned=len(items)),
        filters=WorkbookRowFilters(load_id=load_id, disposition=disposition),
        file_hash=file_hash,
        plant_code=plant["plant_code"],
    )


@router.get(
    "/{plant_code}/workbooks/{file_hash}/issues",
    response_model=WorkbookIssuesOut,
    responses=NOT_FOUND,
    summary="Blockers, warnings and information for one workbook. Engineer.",
)
def list_workbook_issues(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
) -> WorkbookIssuesOut:
    """Three levels, stable tokens, no grades.

    Blockers prevent a commit. Warnings need a person to accept them, and
    three of the four block the commit until they are accepted. Information
    is disclosure -- the plant cells this platform filled in from the
    declared plant, and the profile that read the layout -- and needs no
    action at all.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        found = service.issues(conn, plant["plant_code"], file_hash)
    except WorkbookError as exc:
        raise _refused(exc) from exc
    return WorkbookIssuesOut(
        file_hash=file_hash,
        plant_code=plant["plant_code"],
        issues=[IssueOut(**issue) for issue in found],
    )


@router.get(
    "/{plant_code}/workbooks/{file_hash}/history",
    response_model=WorkbookHistoryOut,
    responses=NOT_FOUND,
    summary="Append-only timeline of one workbook. Engineer.",
)
def get_workbook_history(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
) -> WorkbookHistoryOut:
    """Upload, replay, mapping, acknowledgement, commit, correction, supersede.

    Scoped to this workbook's batches. There is no global `GET /audit` and
    this is not one: an audit list without a subject is a different capability
    with a different threat model, and nobody has asked for it.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        events = service.history(conn, plant["plant_code"], file_hash)
    except WorkbookError as exc:
        raise _refused(exc) from exc
    return WorkbookHistoryOut(
        file_hash=file_hash,
        plant_code=plant["plant_code"],
        events=[
            HistoryEventOut(
                id=e["id"],
                occurred_at=e["occurred_at"],
                actor_user_id=str(e["actor_user_id"]) if e["actor_user_id"] else None,
                actor_type=e["actor_type"],
                action=e["action"],
                entity_type=e["entity_type"],
                entity_id=str(e["entity_id"]),
                correlation_id=e["correlation_id"],
                after=e["after"],
            )
            for e in events
        ],
    )


def _ack_dto(row: dict) -> AcknowledgementOut:
    return AcknowledgementOut(
        ack_id=row["ack_id"],
        load_id=row["load_id"],
        plant_code=row["plant_code"],
        file_hash=str(row["file_hash"]).strip(),
        category=row["category"],
        note=row["note"],
        review_revision=str(row["review_revision"]).strip(),
        actor_user_id=str(row["actor_user_id"]),
        created_at=row["created_at"],
    )


@router.post(
    "/{plant_code}/workbooks/{file_hash}/acknowledgements",
    response_model=AcknowledgementOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        **NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": (
                "The batch has been re-parsed since this review was read, so "
                "the review_revision sent is no longer current, or it has no "
                "projection at all. Nothing was written."
            ),
        },
    },
    summary="Acknowledge one warning category of one sheet. Admin.",
)
def acknowledge_warning(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
    body: AcknowledgementCreate,
) -> AcknowledgementOut:
    """One transaction: the acknowledgement and its audit event.

    Append-only. `app_rw` can neither rewrite nor remove a row of
    `review_acknowledgement`, so changing your mind means acknowledging
    again and both records stay. A replay does not remove one either -- it
    moves the batch's `review_revision`, which stops the old acknowledgement
    satisfying the commit gate while leaving the record that somebody read
    the older proposal.

    Acknowledging `REJECTED_ROWS` or `QUARANTINED_MODELS` requires a note; a
    blank one is a 422 here and a CHECK violation behind it.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        stored = service.acknowledge(
            conn,
            plant["plant_code"],
            file_hash,
            body,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc
    return _ack_dto(stored)


# =====================================================================
# T21: vehicle sets, points, overrides
# =====================================================================
VehicleId = Annotated[
    str,
    Path(
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "SHA-256 of '{load_id}|{measured_date}|{model}|{color}|{serial_no}' "
            "(a FilmThickness set appends '|{logical_vehicle_id}', RO11) "
            "as returned by the vehicles read."
        ),
    ),
]


def _vehicle_dto(found, plant_code: str) -> VehicleSetOut:
    counts = found.dispositions
    return VehicleSetOut(
        vehicle_id=found.vehicle_id,
        load_id=found.load_id,
        plant_code=plant_code,
        measured_date=(
            date.fromisoformat(found.measured_date) if found.measured_date else None
        ),
        model=found.model,
        color=found.color,
        serial_no=found.serial_no,
        identity_complete=found.identity_complete,
        point_count=found.point_count,
        expected_point_count=found.expected_point_count,
        incomplete_set=found.incomplete_set,
        car_label=found.car_label,
        date_is_month_only=found.date_is_month_only,
        dispositions=VehicleDispositionCounts(
            load=counts["LOAD"],
            duplicate=counts["DUPLICATE"],
            reject=counts["REJECT"],
            quarantine=counts["QUARANTINE"],
        ),
    )


def _override_dto(row: dict) -> OverrideOut:
    return OverrideOut(
        override_id=row["override_id"],
        load_id=row["load_id"],
        plant_code=row["plant_code"],
        file_hash=str(row["file_hash"]).strip(),
        source_row=row["source_row"],
        field=row["field"],
        previous_proposed=row["previous_proposed"],
        new_value=row["new_value"],
        reason=row["reason"],
        review_revision=str(row["review_revision"]).strip(),
        actor_user_id=str(row["actor_user_id"]),
        created_at=row["created_at"],
    )


@router.get(
    "/{plant_code}/workbooks/{file_hash}/vehicles",
    response_model=VehicleSetPage,
    responses=NOT_FOUND,
    summary="Vehicle sets of one sheet, grouped by the server. Engineer.",
)
def list_vehicle_sets(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
    load_id: Annotated[
        int,
        Query(ge=1, description="One sheet of this workbook. 404 if it is not a child."),
    ],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VehicleSetPage:
    """One card per vehicle: `measured_date + model + color + serial_no`.

    Grouped from the review projection, or from the sheet's own `wavescan`
    rows where it has no projection -- never by opening the workbook, and not
    through `v_wavescan_active`, so committed, superseded and abandoned
    sheets stay inspectable. Two serials are never one card; rows with a
    missing serial (or no cleaned identity at all) are one
    `identity_complete: false` group per remaining key, not a vehicle.
    `expected_point_count` is the live, non-extra points of this plant's
    Wave Scan list for the model (`ref_model.expected_zone_count` when the
    plant has no list for it), and `point_count` is how many of those points
    the car has a reading on (T114-FIX).

    Order: identity-incomplete first, then measured_date, model, color,
    serial_no.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        found, total = service.vehicles(
            conn, plant["plant_code"], file_hash,
            load_id=load_id, limit=limit, offset=offset,
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc
    return VehicleSetPage(
        items=[_vehicle_dto(v, plant["plant_code"]) for v in found],
        page=PageInfo(limit=limit, offset=offset, total=total, returned=len(found)),
        load_id=load_id,
        file_hash=file_hash,
        plant_code=plant["plant_code"],
    )


@router.get(
    "/{plant_code}/workbooks/{file_hash}/vehicles/{vehicle_id}/points",
    response_model=VehiclePointPage,
    responses=NOT_FOUND,
    summary="Points of one vehicle set: raw, proposed and current overrides. Engineer.",
)
def list_vehicle_points(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
    vehicle_id: VehicleId,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VehiclePointPage:
    """One row per source row of the set, by checkzone then source row.

    `raw` is what the file said and never changes. `proposed` is what commit
    would insert (or did), with the current overrides applied.
    `current_overrides` is the latest override per field, with who, when and
    why.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        found = service.points(
            conn, plant["plant_code"], file_hash, vehicle_id,
            limit=limit, offset=offset,
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc

    items = []
    for row in found["items"]:
        canonical = row["canonical"]
        loading = row["disposition"] == "LOAD" and not row["projection_missing"]
        items.append(VehiclePointOut(
            load_id=row["load_id"],
            source_sheet=row["source_sheet"],
            source_row=row["source_row"],
            # RO11 (D-RO11-5): the row's location in either domain.
            checkzone=(canonical or {}).get("checkzone") or (canonical or {}).get("point_code"),
            disposition=row["disposition"],
            reason=row["reason"],
            detail=row["detail"],
            raw=row["raw"],
            proposed=canonical,
            current_overrides=[
                CurrentOverrideOut(
                    override_id=o["override_id"],
                    field=o["field"],
                    previous_proposed=o["previous_proposed"],
                    new_value=o["new_value"],
                    reason=o["reason"],
                    review_revision=str(o["review_revision"]).strip(),
                    created_at=o["created_at"],
                    actor_user_id=str(o["actor_user_id"]),
                    applied=loading,
                )
                for o in row["current_overrides"]
            ],
            measurement_id=row["measurement_id"],
            projection_missing=bool(row["projection_missing"]),
        ))
    return VehiclePointPage(
        items=items,
        page=PageInfo(
            limit=limit, offset=offset, total=found["total"], returned=len(items)
        ),
        vehicle=_vehicle_dto(found["vehicle"], plant["plant_code"]),
        file_hash=file_hash,
        plant_code=plant["plant_code"],
    )


@router.post(
    "/{plant_code}/workbooks/{file_hash}/overrides",
    response_model=OverrideResult,
    status_code=status.HTTP_201_CREATED,
    responses={
        **NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": (
                "The sheet is not PENDING_REVIEW, the review_revision sent is "
                "not its current one, or re-deriving it with the overrides "
                "would not leave it PENDING_REVIEW with every override "
                "applied. Nothing was written."
            ),
        },
        422: {
            "model": ErrorResponse,
            "description": (
                "An identity field, a JSON number, an out-of-bounds value, a "
                "row outside the vehicle set, a row that is not LOAD, or a "
                "value equal to the proposed one. Nothing was written."
            ),
        },
    },
    summary="Append numeric overrides for one vehicle set and revalidate. Admin.",
)
def create_overrides(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: OverrideCreate,
) -> OverrideResult:
    """One transaction: override rows, synchronous revalidation, audit event.

    Append-only (`app_rw` can only add and read `review_override` rows). The
    sheet is re-derived from its stored bytes by the ingest service with the
    current overrides applied, its projection is rewritten (reset and
    insert, never an in-place edit of a projection cell), and its
    `review_revision` moves -- so an acknowledgement of the old revision no
    longer satisfies the commit gate. The status stays PENDING_REVIEW; no
    worker job is queued. `stg_raw` and each point's `raw` still show what
    the file said, and commit inserts the overridden values.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
        result = service.override(
            conn,
            ingest,
            plant["plant_code"],
            file_hash,
            body,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc
    counts = result["counts"]
    return OverrideResult(
        load_id=result["load_id"],
        vehicle_id=result["vehicle_id"],
        overrides=[_override_dto(row) for row in result["overrides"]],
        previous_review_revision=result["previous_review_revision"],
        review_revision=result["review_revision"],
        counts=BatchCountsOut(**counts.as_dict(), balanced=counts.balanced),
    )


# =====================================================================
# T39 -- the uploader's worksheet (ADR 0013). Engineer, not Admin-only.
# =====================================================================
WORKSHEET_REFUSALS = {
    **NOT_FOUND,
    409: {
        "model": ErrorResponse,
        "description": "Nothing to do in this state. Nothing was changed.",
    },
    422: {
        "model": ErrorResponse,
        "description": "The answer does not fit this workbook. Nothing was changed.",
    },
}


@router.get(
    "/{plant_code}/workbooks/{file_hash}/worksheet",
    response_model=WorksheetOut,
    responses=NOT_FOUND,
    summary="The uploader's confirm page for one workbook, in plain words. Engineer.",
)
def get_worksheet(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
) -> WorksheetOut:
    """Every tab: what loads on "Yes, load these rows", what is held and why.

    Read from what is stored -- batch rows, the persisted projection,
    `wavescan`. No workbook is opened. No grade (D1).
    """
    try:
        return WorksheetOut(**worksheet_service.worksheet(conn, plant_code, file_hash))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/ignore-columns",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Ignore columns we do not use, then re-read the tabs. Engineer.",
)
def ignore_columns(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: IgnoreColumnsCreate,
) -> DecisionResult:
    """ADR 0013 decision 6. Only an extra column, or one of two columns that
    mean the same field, can be ignored. Tabs re-read from the stored bytes
    and return to review; nothing is committed."""
    try:
        return DecisionResult(**worksheet_service.ignore_columns(
            conn, ingest, plant_code, file_hash, headers=body.headers,
            note=body.note, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/plant-answer",
    response_model=PlantAnswerResult,
    responses=WORKSHEET_REFUSALS,
    summary="Answer 'is this this plant's data?'. Engineer.",
)
def answer_plant(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: PlantAnswerCreate,
) -> PlantAnswerResult:
    """ADR 0013 decision 3. The page plant: the Plant texts are recorded as
    meaning this plant and the tabs re-read. Another plant: this upload is
    cancelled (only while nothing has loaded) so it can be sent from that
    plant's page. Nothing is relabelled without this answer."""
    try:
        return PlantAnswerResult(**worksheet_service.answer_plant(
            conn, ingest, plant_code, file_hash, answer=body.plant_code,
            actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/hole-approval",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Approve points with CF but no LW/SW to load without them. Engineer.",
)
def approve_holes(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: HoleApprovalCreate,
) -> DecisionResult:
    """ADR 0013 decision 1. LW/SW are never filled in; the approved points
    load with them NULL. Default stays: held."""
    try:
        return DecisionResult(**worksheet_service.approve_holes(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            source_rows=body.source_rows, note=body.note,
            actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/panel-confirm",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Confirm which panel a rough panel name is, for this upload. Engineer.",
)
def confirm_panels(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: PanelConfirmCreate,
) -> DecisionResult:
    """T94 (D-94-3, D-94-4, D-94-6). A panel name that does not say which
    panel it is -- `01HOOD` against five hoods -- never loads on its own,
    whatever the catalogue holds. This is the answer to it, given in the row
    of the confirm table: one pair for one row, or every pre-filled pair in
    one click. Only a name the tab is asking about may be answered, and only
    with a panel that name's own list offers.

    The tab is then re-read from the stored bytes, so `wavescan.checkzone`
    becomes the panel's long name while `src_zone_text` keeps the file's own
    spelling. The answer is recorded against this upload and is never
    written to `ref_plant_zone_map`, so it cannot decide next month's
    file."""
    try:
        return DecisionResult(**worksheet_service.confirm_panels(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            pairs=[pair.model_dump() for pair in body.pairs],
            note=body.note, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/film-model-answer",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Choose which model a Film sheet naming two models is. Engineer.",
)
def answer_film_model(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: FilmModelAnswerCreate,
) -> DecisionResult:
    """T99 (D-99-11). The Job Number's model token and the file name's
    disagree -- `AW_RB_1943641` in a file called `AW_DBL_...`. They are
    different trucks, so the whole sheet is held and nobody guesses. The
    uploader names the one that is right and the tab is re-read from the
    stored bytes under that model.

    The uploader, not an Admin: the owner decided on 2026-10-10 that anyone
    who can upload answers everything for now ("ignore the role ... I will
    set guardrails in the future"), so the answer is recorded with who gave
    it rather than gated. Only a model this plant has a Film point list for
    is accepted."""
    try:
        return DecisionResult(**worksheet_service.answer_film_model(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            model_code=body.model_code, note=body.note,
            actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/film-job-answer",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Load an unusual Film Job Number as written. Engineer.",
)
def answer_film_job(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: FilmJobAnswerCreate,
) -> DecisionResult:
    """T99 (D-99-10). The Job Number is not the shape this plant writes
    (`BL_RAP_6218` against FTM's seven digits), so the sheet is held. It may
    still be a real truck, so the uploader may say "load as written" and it
    loads as its own vehicle under exactly that number. Nothing is corrected:
    the only answer is to read it as it stands, which is why this body
    carries no value."""
    try:
        return DecisionResult(**worksheet_service.answer_film_job(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            note=body.note, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/film-walk-confirm",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Confirm point names a Film sheet appended to the walk. Engineer.",
)
def confirm_film_walk(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: FilmWalkConfirmCreate,
) -> DecisionResult:
    """T99 (D-99-14). The sheet walked past the end of the list we know. Each
    new name becomes a real point of this plant's list, with a
    `film_point_setting` row saying whether it counts and whether it is
    Horizontal or Vertical, an `audit_event`, and a `worksheet_decision` row
    naming who confirmed it. Then the tab is re-read and loads.

    Only names **appended after** the last known point can be confirmed. A
    walk that inserts, reorders or renumbers inside the known list is refused
    with the sentence that says why: a point is its number and its name
    (D-99-1), so a renumbered walk would file old names onto different spots
    on the truck, and no confirmation can make that safe. That one needs an
    owner decision."""
    try:
        return DecisionResult(**worksheet_service.confirm_film_walk(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            points=[point.model_dump() for point in body.points],
            note=body.note, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.get(
    "/{plant_code}/film-points",
    response_model=FilmModelsOut,
    responses=NOT_FOUND,
    summary="Which Film models this plant has a point list for. Engineer.",
)
def list_film_models(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
) -> FilmModelsOut:
    """T100 (Part A3). The models the Points panel can offer, with how many
    live points each list holds and whether the T99 point rules are switched
    on for it (`has_setting`). No read listed them before, so a client had to
    know a model code before it could ask about one."""
    try:
        return FilmModelsOut(**worksheet_service.film_models(conn, plant_code))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.get(
    "/{plant_code}/film-points/{model_code}",
    response_model=FilmPointSettingOut,
    responses=NOT_FOUND,
    summary="Which Film points count at this plant x model, and their Hor/Ver. Engineer.",
)
def get_film_point_setting(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    model_code: FilmModelCode,
) -> FilmPointSettingOut:
    """T99 (D-99-2, D-99-4). Every live point of the walk, in order, with the
    latest setting of each: does it count towards the dashboard's Horizontal
    and Vertical boxes, which of the two it is, whether a complete walk may
    stop there, and the reason, person and time of the row that last said so.

    `has_setting` is false where no `film_point_setting` row exists: the T99
    rules are switched off for that plant x model and the list behaves
    exactly as it did before (D-99-12)."""
    try:
        return FilmPointSettingOut(**worksheet_service.film_point_setting(
            conn, plant_code, model_code,
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/film-points/{model_code}",
    response_model=FilmPointSettingResult,
    responses=WORKSHEET_REFUSALS,
    summary="Change which Film points count, and their Hor/Ver. Engineer.",
)
def change_film_point_setting(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: FilmModelCode,
    body: FilmPointSettingCreate,
) -> FilmPointSettingResult:
    """T99 (D-99-4). Append-only: every point named here gets a **new** row
    with its reason and the person who wrote it, plus an `audit_event` in the
    same transaction. The row before it is never changed or deleted, and the
    latest row per point is what the dashboard reads.

    This changes past months' Horizontal and Vertical too. That is the
    owner's decision and it is by design -- which is why a reason is
    required, and why the rows that said otherwise stay readable."""
    try:
        return FilmPointSettingResult(
            **worksheet_service.change_film_point_setting(
                conn, plant_code, model_code, points=[
                    point.model_dump() for point in body.points
                ],
                reason=body.reason, actor=principal.user_id or "",
                correlation_id=correlation_id_of(request),
            )
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/film-points/{model_code}/add",
    response_model=FilmPointChangeResult,
    responses=WORKSHEET_REFUSALS,
    summary="Add a Film point to this plant's walk. Engineer.",
)
def add_film_point(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: FilmModelCode,
    body: FilmPointAddCreate,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
) -> FilmPointChangeResult:
    """RO19. Use the number in the name when free, otherwise the next free
    stable point number. Measuring order is independent: place_after names
    the point to follow, and an omitted placement appends to the walk.

    Horizontal / Vertical is pre-filled from this list's **own** points of
    the same panel word; where it has none, 422 asks you to choose. Every
    point added here is tagged **extra** (D-109-3) and counted unless you say
    otherwise.

    Writes the catalogue name if it is new, the list row, one
    `film_point_setting` row and an `audit_event`, in one transaction.
    Nothing already on the list is touched. Stored sheets held asking about
    this point are then read again; their ids are in `replayed_load_ids`."""
    try:
        return FilmPointChangeResult(**worksheet_service.add_film_point(
            conn, plant_code, model_code, point_code=body.point_code,
            counted=body.counted, orientation=body.orientation,
            place_after=body.place_after,
            reason=body.reason, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request), ingest=ingest,
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/film-points/{model_code}/retire",
    response_model=FilmPointChangeResult,
    responses=WORKSHEET_REFUSALS,
    summary="Retire a Film point: off the walk, kept in History. Engineer.",
)
def retire_film_point(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: FilmModelCode,
    body: FilmPointRetireCreate,
) -> FilmPointChangeResult:
    """T109 (D-109-4). Retire means "stop using this point", never "forget
    it". The point leaves the live walk and stops feeding the dashboard's
    Horizontal and Vertical **for every month**; the readings cars already
    have on it stay in History, marked retired; no car becomes incomplete
    because of it, because completeness counts live points on both sides; and
    a later upload that writes its label is asked about in the row (D-109-6).

    The only write is `retired_at` + `retired_reason`, which is the only
    UPDATE the application holds on this table (revision 0035, D-109-9), with
    an `audit_event` beside it. RO17: works with or without the point rules,
    never on the last live point; `restore` brings a point back."""
    try:
        return FilmPointChangeResult(**worksheet_service.retire_film_point(
            conn, plant_code, model_code, point_code=body.point_code,
            reason=body.reason, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/film-points/{model_code}/restore",
    response_model=FilmPointChangeResult,
    responses=WORKSHEET_REFUSALS,
    summary="Restore a retired Film point to the walk at its own number. Engineer.",
)
def restore_film_point(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: FilmModelCode,
    body: FilmPointRestoreCreate,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
) -> FilmPointChangeResult:
    """RO17 (D-RO17-9). Clears `retired_at` / `retired_reason`, with an
    `audit_event`. Refused with 409, nothing written: a live point holds its
    number (reorder is out of scope), or its code or current label now names
    another point of the list (D-RO17-4). Stored sheets held asking about
    the point are then read again (`replayed_load_ids`)."""
    try:
        return FilmPointChangeResult(**worksheet_service.restore_film_point(
            conn, plant_code, model_code, point_code=body.point_code,
            reason=body.reason, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request), ingest=ingest,
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/film-points/{model_code}/tail-labels",
    response_model=FilmTailLabelResult,
    responses=WORKSHEET_REFUSALS,
    summary="Add a Film tail label: a label this walk writes that is no point. Admin.",
)
def add_film_tail_label(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: FilmModelCode,
    body: FilmTailLabelCreate,
) -> FilmTailLabelResult:
    """RO17 (D-RO17-12). Rows with a tail label are skipped on upload. Refused
    when blank, already a live tail label, or a spelling that resolves to a
    live point (its readings would vanish). A retired one is put back."""
    try:
        return FilmTailLabelResult(**worksheet_service.add_film_tail_label(
            conn, plant_code, model_code, label=body.label, reason=body.reason,
            actor=principal.user_id or "", correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/film-points/{model_code}/tail-labels/retire",
    response_model=FilmTailLabelResult,
    responses=WORKSHEET_REFUSALS,
    summary="Retire a Film tail label: its rows are asked about again. Admin.",
)
def retire_film_tail_label(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: FilmModelCode,
    body: FilmTailLabelRetireCreate,
) -> FilmTailLabelResult:
    """RO17 (D-RO17-12). Sets `retired_at` / `retired_reason`; the row stays."""
    try:
        return FilmTailLabelResult(**worksheet_service.retire_film_tail_label(
            conn, plant_code, model_code, label=body.label, reason=body.reason,
            actor=principal.user_id or "", correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/film-point-answer",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Say which live point a Film label on this sheet is. Engineer.",
)
def answer_film_point(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: FilmPointAliasCreate,
) -> DecisionResult:
    """T109 (D-109-6). The sheet wrote a Location this plant's live list does
    not hold -- a point that was retired, a spelling this plant has started
    writing. The person with the file in front of them says which live point
    it is, in the row; the answer is stored as an **alias** and every later
    upload resolves it without asking again.

    Only a label the tab is actually asking about (`film_unknown_labels`) and
    only a live point of the tab's model (`film_point_choices`) are accepted.
    Nothing is minted here: a label that is a genuinely new point is added on
    Point Check first, and then the file is re-checked. Then the tab is
    re-read from the stored bytes and the rows that carried the label load
    like any other."""
    try:
        return DecisionResult(**worksheet_service.answer_film_point(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            raw_location=body.raw_location, point_code=body.point_code,
            note=body.note, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/film-not-a-point",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Say a Film label is not a point of this list: kept, never loaded. Engineer.",
)
def answer_film_not_a_point(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: FilmNotAPointCreate,
) -> DecisionResult:
    """RO18 (B5). The other answer to the row's point question. Remembered per
    plant x model; rows writing the label are kept with the file, never loaded,
    and never hold the sheet. Refused for a label the tab is not asking about
    or one that resolves to a point. Then the tab is re-read."""
    try:
        return DecisionResult(**worksheet_service.answer_film_not_a_point(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            raw_location=body.raw_location, note=body.note,
            actor=principal.user_id or "", correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/month-answer",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Name the month an undated sheet's cars were measured in. Engineer.",
)
def answer_month(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: MonthAnswerCreate,
) -> DecisionResult:
    """RO18 (B4, RO09). Either domain. Stored on the 1st of the month with
    "day not recorded"; such cars never pair. Then the tab is re-read."""
    try:
        return DecisionResult(**worksheet_service.answer_month(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            month=body.month, note=body.note, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/film-date-answer",
    response_model=DecisionResult,
    responses=WORKSHEET_REFUSALS,
    summary="Say which date of a Film sheet is right: the sheet's or the file name's. Engineer.",
)
def answer_film_date(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
    body: FilmDateAnswerCreate,
) -> DecisionResult:
    """RO18 (B3). Asked only when the file name carries one full date more
    than 3 days from the sheet's. Then the tab is re-read."""
    try:
        return DecisionResult(**worksheet_service.answer_film_date(
            conn, ingest, plant_code, file_hash, load_id=body.load_id,
            choice=body.choice, note=body.note, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/load-ready",
    response_model=WorkbookLoadResult,
    responses=WORKSHEET_REFUSALS,
    summary="'Yes, load these rows': commit every ready tab. Engineer.",
)
def load_ready(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
) -> WorkbookLoadResult:
    """ADR 0013 decision 8. Each ready tab is its own audited commit through
    the one ingest service; the warning acknowledgements it needs are
    recorded in the Engineer's name with a fixed note first. Held rows stay
    on the card. One transaction: a tab that fails loads nothing."""
    try:
        return WorkbookLoadResult(**worksheet_service.load_ready(
            conn, ingest, plant_code, file_hash, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/workbooks/{file_hash}/load-remaining",
    response_model=WorkbookLoadResult,
    responses=WORKSHEET_REFUSALS,
    summary="Insert rows of loaded tabs that became loadable. INSERT only. Engineer.",
)
def load_remaining(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    file_hash: FileHash,
) -> WorkbookLoadResult:
    """ADR 0013 decision 9. Same file, same load_ids. Only rows that now load
    and are not already measurements are inserted. No UPDATE of a stored
    value; no remainder file."""
    try:
        return WorkbookLoadResult(**worksheet_service.load_remaining(
            conn, ingest, plant_code, file_hash, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


# =====================================================================
# T37 -- permanent workbook purge (ADR 0011)
# =====================================================================
@router.post(
    "/{plant_code}/workbooks/{file_hash}/purge",
    response_model=WorkbookPurgeResult,
    responses={
        **NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": (
                "Another workbook depends on this one (it names a sheet of "
                "this file as its replacement, or a correction crosses the "
                "two), or the same hash is filed under another plant. "
                "Nothing was deleted."
            ),
        },
        422: {"model": ErrorResponse, "description": "Blank reason. Nothing was deleted."},
    },
    summary="Permanently delete one workbook's rows at this plant. Admin.",
)
def purge_workbook(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    file_hash: FileHash,
    body: WorkbookPurgeCreate,
) -> WorkbookPurgeResult:
    """ADR 0011: X on a workbook.

    One transaction through the `purge_workbook` SECURITY DEFINER function:
    the `workbook.purge` audit row first, then every sheet of this hash at
    this plant and its staging, review rows, rejects, unidentified models,
    ingest jobs and `wavescan` rows. `app_rw` still has no table DELETE.
    Template profiles, aliases and `cf_standard` are untouched. The stored
    bytes stay (D4). The hash is gone afterwards, so the same file uploads
    as a new batch and must be mapped again if its layout is unknown.
    """
    try:
        result = service.purge_workbook(
            conn,
            plant_code,
            file_hash,
            reason=body.reason,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc
    return WorkbookPurgeResult(**result)


# =====================================================================
# T26 -- owner-publish of a verified template profile (spec S20)
# =====================================================================
@router.post(
    "/{plant_code}/template-profiles/publish",
    response_model=ProfilePublished,
    responses={
        **NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": (
                "Those bytes are not a WaveScan-classifiable sheet, are "
                "missing a required field, give two columns one meaning, or "
                "the workbook has more than one WaveScan sheet and the "
                "request does not say which. Nothing was published."
            ),
        },
        422: {
            "model": ErrorResponse,
            "description": (
                "A blank named_owner, blank notes, or an ignored header with "
                "no reason. A verified layout records who verified it and "
                "what proved it. Nothing was published."
            ),
        },
    },
    summary=(
        "Publish an owner-verified template profile version for this plant. "
        "Admin role."
    ),
)
def publish_template_profile(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    plant_code: PlantCode,
    body: ProfilePublishCreate,
) -> ProfilePublished:
    """The only application path that can make a layout commit-capable.

    One transaction: the appended profile version, its column policy, and the
    `audit_event` naming the owner who verified it. The write itself happens
    inside `publish_template_profile` in PostgreSQL, because `app_rw` holds
    no INSERT or UPDATE on `ref_template_profile` -- which is what keeps the
    Admin mapping-approve route from ever becoming a second door to this one,
    however that route is later edited (design M6, spec S20).

    The body names a workbook **already stored for this plant**, by hash; it
    does not accept Excel. What is certified is therefore always bytes this
    platform can replay.

    Publishing then replays, from their stored bytes, the batches of this
    plant and contract that are REJECTED_TEMPLATE or PENDING_REVIEW, and
    returns their ids in `replayed_load_ids`. Replay ends at PENDING_REVIEW
    or REJECTED_TEMPLATE. Publishing commits nothing and supersedes nothing:
    an Engineer still presses commit on rows a person has read.
    """
    try:
        plant = service.resolve_plant(conn, plant_code)
    except WorkbookError as exc:
        raise _refused(exc) from exc
    try:
        result = ingest.publish_profile(
            conn,
            plant["plant_code"],
            file_hash=body.file_hash,
            source_sheet=body.source_sheet,
            named_owner=body.named_owner,
            notes=body.notes,
            fill_missing_plant=body.fill_missing_plant,
            ignored_headers=[
                {"header": item.header, "reason": item.reason}
                for item in body.ignored_headers
            ],
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except ProfilePublishRefused as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "that profile version could not be appended: "
                f"{exc.orig}. Nothing was published."
            ),
        ) from exc
    except DBAPIError as exc:
        # The function's own refusals -- blank owner, blank notes, missing
        # proof hash, unknown plant -- arrive as PostgreSQL exceptions. They
        # are guarantees rather than validations, so they are translated
        # here rather than re-implemented above where they could drift.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"publish refused: {exc.orig}. Nothing was published.",
        ) from exc

    return ProfilePublished(
        profile_id=int(result["profile_id"]),
        version=int(result["version"]),
        domain=result["domain"],
        plant_code=result["plant_code"],
        semantic_signature=result["semantic_signature"],
        template_fingerprint=result["template_fingerprint"],
        fixture_verified=bool(result["fixture_verified"]),
        fixture_file_hash=result["fixture_file_hash"],
        named_owner=result["named_owner"],
        previous_profile_id=result.get("previous_profile_id"),
        ignored_headers=int(result.get("ignored_headers") or 0),
        replayed_load_ids=list(result.get("replayed_load_ids") or []),
        audit_action=result.get("audit_action", "profile.publish"),
    )


# =====================================================================
# T114: Point Check, Wave Scan
# =====================================================================
@router.get(
    "/{plant_code}/ws-points",
    response_model=WsPointModelsOut,
    responses=NOT_FOUND,
    summary="Which Wave Scan models this plant has a point list for. Engineer.",
)
def list_ws_point_models(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
) -> WsPointModelsOut:
    """T114 (D-114-1). The models Point Check's Wave Scan section can offer,
    with how many live points each list holds, how many count, and how many
    are extra."""
    try:
        return WsPointModelsOut(**ws_points_service.ws_models(conn, plant_code))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.get(
    "/{plant_code}/ws-points/{model_code}",
    response_model=WsPointListOut,
    responses=NOT_FOUND,
    summary="One Wave Scan point list: live points, retired points, what Add may pick. Engineer.",
)
def get_ws_point_list(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    model_code: WsModelCode,
) -> WsPointListOut:
    """T114 (D-114-1). Every live point in walk order with its zone code,
    Hor / Ver (fixed by the name), Counted, the extra tag and the last change;
    the retired points with when and why; and the zone codes Add may pick."""
    try:
        return WsPointListOut(
            **ws_points_service.ws_point_list(conn, plant_code, model_code)
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/ws-points/{model_code}",
    response_model=WsPointSettingResult,
    responses=WORKSHEET_REFUSALS,
    summary="Change which Wave Scan points the dashboard counts. Engineer.",
)
def change_ws_point_setting(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: WsModelCode,
    body: WsPointSettingCreate,
) -> WsPointSettingResult:
    """T114 (D-114-2, D-114-3). Append-only: every point named here gets a
    **new** `ws_point_setting` row with its reason and person, plus an
    `audit_event`. Not counted takes the point's readings off the dashboard
    for every month; History and Comparison keep them, tagged."""
    try:
        return WsPointSettingResult(**ws_points_service.change_ws_point_setting(
            conn, plant_code, model_code,
            points=[point.model_dump() for point in body.points],
            reason=body.reason, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/ws-points/{model_code}/add",
    response_model=WsPointChangeResult,
    responses=WORKSHEET_REFUSALS,
    summary="Add a Wave Scan point at the end of this plant's walk. Engineer.",
)
def add_ws_point(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: WsModelCode,
    body: WsPointAddCreate,
) -> WsPointChangeResult:
    """T114 (D-114-5..7). Pick an existing zone code or type a new one; a new
    code is kept exactly as typed (ends trimmed) and its Hor / Ver is read off
    the name. The point goes at the **end of the walk** and is tagged extra.

    Refused with 409, nothing written: the code is already live on this list;
    it was retired here (restore it instead); it is an existing code
    spelled differently (case or spaces); the word clashes with another
    point's code, label or a spelling that loads onto it (RO17 D-RO17-4); the
    model's catalogue has no position left (40).

    RO17: `counted_in_completeness` true is Admin only (403 otherwise): the
    point is not extra, and `incomplete_cars` says how many stored cars it
    made incomplete. An offered model with no list may take its first point
    here (D-RO17-10). The word typed is the point's first label."""
    try:
        return WsPointChangeResult(**ws_points_service.add_ws_point(
            conn, plant_code, model_code, zone_code=body.zone_code,
            counted=body.counted, reason=body.reason,
            actor=principal.user_id or "", actor_name=principal.display_name,
            correlation_id=correlation_id_of(request),
            counted_in_completeness=body.counted_in_completeness,
            admin=principal.has_role("admin"),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/ws-points/{model_code}/retire",
    response_model=WsPointChangeResult,
    responses=WORKSHEET_REFUSALS,
    summary="Retire a Wave Scan point: off the walk, kept in History. Engineer.",
)
def retire_ws_point(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: WsModelCode,
    body: WsPointRetireCreate,
) -> WsPointChangeResult:
    """T114 (D-114-4). The point leaves the live list: it is no longer a
    panel-match target and never pre-filled. Its readings stay in History,
    tagged "retired point", and leave the dashboard for every month. The
    write is `retired_at` + `retired_reason` -- the existing T86 retire --
    with an `audit_event`. RO17: `restore` brings it back."""
    try:
        return WsPointChangeResult(**ws_points_service.retire_ws_point(
            conn, plant_code, model_code, zone_code=body.zone_code,
            reason=body.reason, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/ws-points/{model_code}/restore",
    response_model=WsPointChangeResult,
    responses=WORKSHEET_REFUSALS,
    summary="Restore a retired Wave Scan point to the walk at its own number. Engineer.",
)
def restore_ws_point(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    model_code: WsModelCode,
    body: WsPointRestoreCreate,
) -> WsPointChangeResult:
    """RO17 (D-RO17-9). Clears `retired_at` / `retired_reason`, with an
    `audit_event`. Refused with 409, nothing written: a live point holds its
    number (reorder is out of scope), or its code or current label now
    clashes with another point (D-RO17-4)."""
    try:
        return WsPointChangeResult(**ws_points_service.restore_ws_point(
            conn, plant_code, model_code, zone_code=body.zone_code,
            reason=body.reason, actor=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.get(
    "/{plant_code}/ws-points/{model_code}/completeness-impact",
    response_model=WsCompletenessImpactOut,
    responses=WORKSHEET_REFUSALS,
    summary="How many stored cars a point counted in completeness would make incomplete. Engineer.",
)
def ws_completeness_impact(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    model_code: WsModelCode,
    zone_code: Annotated[str, Query(min_length=1, max_length=64)],
) -> WsCompletenessImpactOut:
    """RO17 (D-RO17-7). The add with `counted_in_completeness` true, done
    inside a savepoint that is always rolled back, on a read connection that
    never commits: nothing persists. A refusal is the add's own refusal."""
    try:
        return WsCompletenessImpactOut(**ws_points_service.completeness_impact(
            conn, plant_code, model_code, zone_code=zone_code,
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


# =====================================================================
# RO17: point labels and the aliases screen, both domains
# =====================================================================
ListModelCode = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        description="RO17: `ref_model.model_code` of a point list of this plant in the domain.",
    ),
]


@router.get(
    "/{plant_code}/point-labels",
    response_model=PointLabelsOut,
    responses=NOT_FOUND,
    summary="Every point of the plant with its label, the plant's own word. Every role.",
)
def list_point_labels(
    principal: CurrentPrincipal,
    conn: DbConnection,
    plant_code: PlantCode,
    domain: Annotated[
        Domain | None, Query(description="wavescan or film; both when absent.")
    ] = None,
) -> PointLabelsOut:
    """RO17 (D-RO17-1, -16). Every point, live and retired, of every list of
    the plant, with its current label (the code where it has none), ordered
    domain, model, point_no, code."""
    try:
        return PointLabelsOut(**labels_service.plant_labels(conn, plant_code, domain))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/point-labels/{domain}/{model_code}/rename",
    response_model=PointLabelChangeResult,
    responses=WORKSHEET_REFUSALS,
    summary="Label a point with the plant's own word. Engineer.",
)
def rename_point_label(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    domain: Domain,
    model_code: ListModelCode,
    body: PointLabelRenameCreate,
) -> PointLabelChangeResult:
    """RO17 (D-RO17-6). A new label row and an `audit_event`; the point keeps
    its code, so every reading, History and Comparison stay one series, and
    every earlier label still loads onto it. 404 no list / not a point; 409
    retired (restore first), the same as now, or a clash (D-RO17-4)."""
    try:
        return PointLabelChangeResult(**labels_service.rename(
            conn, domain, plant_code, model_code, code=body.code,
            label=body.label, reason=body.reason,
            actor=principal.user_id or None,
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.get(
    "/{plant_code}/point-aliases/{domain}/{model_code}",
    response_model=PointAliasesOut,
    responses=NOT_FOUND,
    summary="Every alias that loads onto a point of this list. Engineer.",
)
def list_point_aliases(
    principal: EngineerReader,
    conn: DbConnection,
    plant_code: PlantCode,
    domain: Domain,
    model_code: ListModelCode,
) -> PointAliasesOut:
    """RO17 (D-RO17-13). Wave Scan: this plant x model's zone maps, the global
    aliases onto its live points (read-only, shared by all plants) and
    earlier labels. Film: T109 aliases, location maps, earlier labels. Each
    with how many active readings carry that spelling."""
    try:
        return PointAliasesOut(
            **labels_service.aliases(conn, plant_code, domain, model_code)
        )
    except WorkbookError as exc:
        raise _refused(exc) from exc


@router.post(
    "/{plant_code}/point-aliases/{domain}/{model_code}/retire",
    response_model=PointAliasRetireResult,
    responses=WORKSHEET_REFUSALS,
    summary="Retire one alias of this list. Admin.",
)
def retire_point_alias(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    plant_code: PlantCode,
    domain: Domain,
    model_code: ListModelCode,
    body: PointAliasRetireCreate,
) -> PointAliasRetireResult:
    """RO17 (D-RO17-13). Append-only: `retired_at` + reason + `audit_event`.
    Refused: a global alias (read-only here), already retired, the current
    label (rename instead), or when stored readings of a committed batch
    would be left with a spelling that no longer resolves. Repoint = retire
    + teach again."""
    try:
        return PointAliasRetireResult(**labels_service.retire_alias(
            conn, plant_code, domain, model_code, kind=body.kind,
            alias_id=body.alias_id, reason=body.reason,
            actor=principal.user_id or None,
            correlation_id=correlation_id_of(request),
        ))
    except WorkbookError as exc:
        raise _refused(exc) from exc
