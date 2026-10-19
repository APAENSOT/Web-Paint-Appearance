"""Mapping proposals: read, propose, approve.

`POST /api/v1/mappings/proposals` and
`POST /api/v1/mappings/proposals/{proposal_id}/approve` replace the reserved
stubs of the same paths (T03 `api/v1/reserved.py`). Same URLs, same required
roles — Engineer proposes, Admin approves, Viewer neither — so no generated
client breaks.

The two `GET` routes are **new in T08** and recorded as a contract change in
`docs/reports/T08-MAPPING.md`. They are not optional: T04 already writes a
`COLUMN` proposal whenever a sheet's template is unknown, and until now
nothing could read one back. An Admin cannot approve what they cannot see,
and a client that had to guess the DTO would be inventing the shape — which
`AGENTS.md` rule 9 puts the other way round: the frontend's types come from
this contract.

What approving does, in one transaction: write the alias, record the
decision, write the audit row, and queue the batch for replay from its
**stored bytes**. What it does not do is commit anything. Replay ends at
`PENDING_REVIEW`, and turning those rows into measurements is still an
Engineer pressing commit on a batch a person has read.

No SQL in this module (`00-ARCHITECTURE.md` §5 rule 2) and no branching on a
similarity score.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.api.deps import (
    AdminPrincipal,
    CurrentUser,
    DbConnection,
    EngineerPrincipal,
    WriteConnection,
    get_mapping_service,
)
from app.core.correlation import correlation_id_of
from app.repositories import mappings as repo
from app.schemas.common import ErrorResponse, PageInfo
from app.schemas.panel_match import PanelMatchOut
from app.schemas.mappings import (
    ApprovalResult,
    ProposalCreate,
    ProposalOut,
    ProposalPage,
    ReplayOut,
)
from app.services.mapping import MappingError, MappingService
from app.services.panel_match import PanelMatchUnavailable, panel_match_view

router = APIRouter(prefix="/mappings", tags=["mappings"])

#: `COMMON_RESPONSES` in `main.py` declares 401/403/422/500/503 for every
#: route. These three are specific to this module and are declared because a
#: refusal IS the behaviour here -- a generated client that does not know 409
#: and 501 are possible would treat "already decided" as an unexpected error
#: (`AGENTS.md` rule 9: the frontend's types come from this contract).
NOT_FOUND = {404: {"model": ErrorResponse, "description": "No such proposal."}}
CONFLICT = {
    409: {
        "model": ErrorResponse,
        "description": (
            "Already decided, the alias already exists, or the batch cannot "
            "be replayed. Nothing was applied in any of the three."
        ),
    }
}
RESERVED = {
    501: {
        "model": ErrorResponse,
        "description": (
            "A proposal kind the data model declares and this slice does not "
            "implement. The caller's role is sufficient."
        ),
    }
}

ProposalId = Annotated[str, Path(description="proposed_mapping.id (uuid)")]


def _to_dto(row: dict) -> ProposalOut:
    return ProposalOut(**{k: row[k] for k in ProposalOut.model_fields})


def _refuse(exc: MappingError) -> HTTPException:
    """One place that turns a refusal into its status code.

    The service decides *why* and carries the code with the exception, so the
    router never has to re-derive an outcome from a message string.
    """
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    "/proposals",
    response_model=ProposalPage,
    summary="Mapping proposals, newest first. Any authenticated role.",
)
def list_proposals(
    principal: CurrentUser,
    conn: DbConnection,
    load_id: Annotated[
        int | None,
        Query(ge=1, description="Only proposals about this batch."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProposalPage:
    rows = repo.list_proposals(conn, load_id=load_id, limit=limit, offset=offset)
    return ProposalPage(
        items=[_to_dto(row) for row in rows],
        page=PageInfo(
            limit=limit,
            offset=offset,
            total=repo.count_proposals(conn, load_id=load_id),
            returned=len(rows),
        ),
    )


@router.get(
    "/proposals/{proposal_id}",
    response_model=ProposalOut,
    responses=NOT_FOUND,
    summary="One mapping proposal. Any authenticated role.",
)
def get_proposal(principal: CurrentUser, conn: DbConnection, proposal_id: ProposalId) -> ProposalOut:
    row = repo.get_proposal(conn, proposal_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No mapping proposal {proposal_id}.")
    return _to_dto(row)


@router.get(
    "/panel-match",
    response_model=PanelMatchOut,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No such batch, or no such model in ref_model.",
        }
    },
    summary="The guided panel-match screen for one batch and model. Any authenticated role.",
)
def panel_match(
    principal: CurrentUser,
    conn: DbConnection,
    load_id: Annotated[int, Query(ge=1, description="The held batch.")],
    model_code: Annotated[
        str,
        Query(min_length=1, max_length=64, description="The model the held rows are on."),
    ],
    confirmed: Annotated[
        list[str] | None,
        Query(
            description=(
                "T88. Pairs the owner has already confirmed on this screen, "
                "each `raw_zone_text=zone_code`. They are **pinned**: the "
                "solver never moves, drops or re-proposes one, and their "
                "panels leave the pool so the rest re-solves around them "
                "(D-88-2 / G-88-4). Read-only -- confirming for real is "
                "still the atomic ZONE proposal."
            ),
        ),
    ] = None,
) -> PanelMatchOut:
    """What this file calls each panel, what the plant's live panels are, and
    which of those each file name **looks like by name** (T86).

    The plant is the batch's own `load_batch.plant_code`; it is not a
    parameter, so a caller cannot ask for one plant's panels against another
    plant's file.

    Every `candidates` entry is scored on the panel NAME with its leading
    number removed, and every entry carries that score so the screen can
    show how strong the match is. `raw_position` and `point_no` are shown
    and never read: `14ROOF` is not proposed onto `14LFBOXSD` (D-86-3). An
    empty `candidates` is an answer -- nothing in this platform fills it
    with the nearest number.

    A `live_panels` entry with `mappable = false` cannot be the target of a
    confirmed pair, and `not_mappable_reason` says why in plain words.
    """
    pinned: dict[str, str] = {}
    for pair in confirmed or []:
        spelling, _, zone = pair.partition("=")
        if not spelling.strip() or not zone.strip():
            raise HTTPException(
                status_code=422,
                detail=f"confirmed pair {pair!r} must read 'raw_zone_text=zone_code'.",
            )
        pinned[spelling.strip()] = zone.strip()
    try:
        return PanelMatchOut(
            **panel_match_view(conn, load_id, model_code, confirmed=pinned)
        )
    except PanelMatchUnavailable as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/proposals",
    response_model=ProposalOut,
    status_code=201,
    responses=RESERVED,
    summary="Propose a column or zone mapping, or apply an identity alias. Engineer role.",
)
def create_proposal(
    request: Request,
    principal: EngineerPrincipal,
    conn: WriteConnection,
    service: Annotated[MappingService, Depends(get_mapping_service)],
    body: ProposalCreate,
) -> ProposalOut:
    """Record a COLUMN/ZONE proposal, or apply an identity alias.

    A 201 here changes how no file is read **for COLUMN and ZONE**. Identity
    aliases (`ALIAS_COLOR`, rostered `ALIAS_MODEL`) are applied in this
    same Engineer request (spec A2): alias + audit, replay if the batch
    allows. Leftover programs (J73 / CX743 / V363 / U704) are 422 onto
    Ranger; they may bind onto that program's own catalogue. A committed
    remainder still keeps the alias when replay is refused. The similarity
    score is carried for a person to read, not acted on.

    `ZONE` (T29) is one complete, owner-proved checkpoint set for one plant
    and one `ref_model` catalogue. It may omit `load_id` when `payload.plant_code`
    names the plant (FVL has no committable batch); COLUMN and ALIAS_MODEL
    still require it. `ALIAS_COLOR` is identity only (S12): it may omit
    `load_id` when `payload.plant_code` names the plant, so a committed
    remainder can teach future files without replaying facts. `422` for an
    incomplete or padded set, a zone that is not a position on that model,
    a blank proof field, a colour name not in `ref_color`, a leftover
    spelling taught onto a foreign catalogue, or a `load_id` at another plant.

    **`ZONE` takes a second shape (T86).** A payload carrying `matches`
    instead of `mappings` is a guided panel-match set: N pairs of one of
    this file's panel spellings onto a live panel of that plant x model,
    which a person chose on `GET /mappings/panel-match`, plus the block of
    live panels the **owner** says the set supersedes. It carries no proof
    hash because it proves nothing and mints nothing; `decided_by` and
    `method` record who said which panel each name is. `load_id` is
    required. Still Engineer -> Admin, still all-or-none. `422` for a
    spelling or a target named twice, a target that is not live at this
    plant x model or is not a position on the model's own catalogue, a
    panel both matched onto and retired, or a batch at another plant or in
    a state that cannot replay.

    `501` for a kind the data model declares and nothing implements
    (`ALIAS_PLANT`, `ALIAS_CHECKZONE`, `ALIAS_PAINTLINE`).
    """
    try:
        row = service.propose(
            conn,
            body,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except MappingError as exc:
        raise _refuse(exc) from exc
    return _to_dto(row)


@router.post(
    "/proposals/{proposal_id}/approve",
    response_model=ApprovalResult,
    responses={**NOT_FOUND, **CONFLICT, **RESERVED},
    summary="Approve a proposal, write the mapping, replay the batch if any. Admin role.",
)
def approve_proposal(
    request: Request,
    principal: AdminPrincipal,
    conn: WriteConnection,
    service: Annotated[MappingService, Depends(get_mapping_service)],
    proposal_id: ProposalId,
) -> ApprovalResult:
    """One transaction: decision, alias, audit, replay enqueue.

    * `404` — no such proposal.
    * `409` — already decided, or the alias already exists, or the batch is
      in a state that cannot be replayed. In all three nothing is applied.
    * `422` — the proposal's payload does not describe an applicable mapping.
      T04's diagnostic `COLUMN` rows are header diffs for a person to read;
      approving one means proposing the actual mapping first.
    * `501` — a kind nothing implements.

    **ZONE (T29).** All 32 rows or none, in this transaction. A missing row
    is inserted APPROVED with the named owner's proof; a row that already
    maps the same label to the same zone is certified in place; a row that
    maps it to a *different* zone, or carries a different proof, is `409`
    and nothing in the set is written. `zone_code` is never updated. With no
    `load_id`, `replay` is null and no plant is onboarded. Approving never
    sets `fixture_verified`.

    **ZONE, panel-match shape (T86).** All N pairs, plus the owner's
    retirement, in this one transaction. A pair whose spelling already maps
    to the same panel is left alone; one that maps to a *different* panel is
    `409` and nothing in the set is written. Retiring sets `retired_at` and
    `retired_reason` on the named `ref_plant_ws_point` rows -- nothing is
    deleted, so old measurements stay readable while new uploads stop
    matching onto them (D-86-2).
    """
    try:
        result = service.approve(
            conn,
            proposal_id,
            actor_user_id=principal.user_id or "",
            correlation_id=correlation_id_of(request),
        )
    except MappingError as exc:
        raise _refuse(exc) from exc

    return ApprovalResult(
        proposal=_to_dto(result["proposal"]),
        applied_to=result["applied_to"],
        replay=ReplayOut(**result["replay"]) if result["replay"] else None,
    )
