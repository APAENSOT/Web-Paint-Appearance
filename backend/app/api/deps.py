"""Shared route dependencies.

Routers contain no SQL (`00-ARCHITECTURE.md` section 5, rule 2). They get a
connection from here and hand it to a repository.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Iterator

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy import Connection

from app.core.identity import ensure_user
from app.core.scoping import visible_plants
from app.core.security import CurrentPrincipal, Principal, require_role
from app.repositories.measurements import MeasurementFilter


def get_connection(request: Request) -> Iterator[Connection]:
    """A read connection, always closed, never committed.

    No route in T03 writes. The context manager rolls back on exit, so an
    accidental write in a future edit does not reach disk through a read
    route.
    """
    database = request.app.state.database
    with database.connect() as conn:
        yield conn


DbConnection = Annotated[Connection, Depends(get_connection)]


def get_write_connection(request: Request) -> Iterator[Connection]:
    """A transaction that COMMITS when the route returns.

    Separate from `get_connection` on purpose: that one always rolls back, so
    a write issued through it would appear to succeed and then vanish. A
    route that writes has to say so by asking for this dependency.
    """
    database = request.app.state.database
    with database.begin() as conn:
        yield conn


WriteConnection = Annotated[Connection, Depends(get_write_connection)]


def get_ingest_service(request: Request):
    """The single parser (`02-PIPELINE.md` §10). Built once, at startup."""
    return request.app.state.ingest_service


def get_correction_service(request: Request):
    """Corrections and batch supersede. Holds no parser and no grading."""
    return request.app.state.correction_service


def get_mapping_service(request: Request):
    """Propose / approve / replay. Wraps the one ingest service, never a
    second parser."""
    return request.app.state.mapping_service


def _attributed(required_role: str):
    """An authenticated caller with the given role AND an `app_user` row.

    Every mutating route depends on this rather than on `require_role` alone:
    the identity has to exist in the database before the route writes
    anything, or the audit row it produces has no actor.
    """
    role_check = require_role(required_role)

    def _dependency(request: Request, principal: Principal = Depends(role_check)) -> Principal:
        return ensure_user(request, principal)

    _dependency.__name__ = f"attributed_{required_role}"
    return _dependency


#: The two roles the RBAC matrix gives a mutating route.
EngineerPrincipal = Annotated[Principal, Depends(_attributed("engineer"))]
AdminPrincipal = Annotated[Principal, Depends(_attributed("admin"))]

#: An Engineer **read** (T39). Not `_attributed`: a GET must not open a write
#: transaction to upsert `app_user`, and nothing it returns is attributed to
#: anybody. The uploader's worksheet is read by the person who uploaded the
#: file. RO12: so are the plant Data Manager reads. (RO13 opened the last
#: Admin reads, the standards catalogue and model points, to every role.)
EngineerReader = Annotated[Principal, Depends(require_role("engineer"))]


def current_user(request: Request, principal: CurrentPrincipal) -> Principal:
    """Any authenticated caller, with `user_id` resolved."""
    return ensure_user(request, principal)


CurrentUser = Annotated[Principal, Depends(current_user)]


def measurement_filters(
    principal: CurrentPrincipal,
    plant: Annotated[str | None, Query(max_length=32, description="ref_plant.plant_code")] = None,
    model: Annotated[str | None, Query(max_length=64, description="ref_model.model_code")] = None,
    color: Annotated[str | None, Query(max_length=64, description="ref_color.color_name")] = None,
    checkzone: Annotated[
        str | None, Query(max_length=32, description="ref_checkzone.zone_code")
    ] = None,
    date_from: Annotated[date | None, Query(description="measured_date >= this date")] = None,
    date_to: Annotated[date | None, Query(description="measured_date <= this date")] = None,
    load_id: Annotated[
        int | None,
        Query(
            ge=1,
            description=(
                "load_batch.load_id. Narrows the list to the measurements one "
                "sheet produced, for a file drill-down. It filters the same "
                "active view as every other filter, so a superseded batch "
                "returns nothing here -- its rows are still visible on the "
                "workbook rows route (T19)."
            ),
        ),
    ] = None,
) -> MeasurementFilter:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from is after date_to, so the range selects nothing.",
        )
    return MeasurementFilter(
        plant=plant,
        model=model,
        color=color,
        checkzone=checkzone,
        date_from=date_from,
        date_to=date_to,
        load_id=load_id,
        # D3's single seam. Today this is always None (all plants visible).
        plant_scope=visible_plants(principal),
    )


Filters = Annotated[MeasurementFilter, Depends(measurement_filters)]


def active_measurement_scope(principal: CurrentPrincipal) -> MeasurementFilter:
    """Plant visibility only. By-id and correction must not inherit list filters.

    `Filters` is the list endpoint's query string. Reusing it on
    `GET /measurements/{id}` and `POST /corrections` documented `plant` /
    `model` / `date_from` as if they belonged there, and a leftover
    `?plant=FTM` 404'd an active AAT row (or 409'd a correction as a
    "duplicate"). D3's seam is `visible_plants`; the dashboard's current
    page filters are not.
    """
    return MeasurementFilter(plant_scope=visible_plants(principal))


ActiveScope = Annotated[MeasurementFilter, Depends(active_measurement_scope)]
