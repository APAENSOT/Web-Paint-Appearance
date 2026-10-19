"""RO12 -- an Engineer reads the files they upload; no write moved with it.

Two claims, against the running application, worker and database (T04's
fixtures, synthetic workbooks, cleaned by load_id):

* **Every Admin write still refuses an Engineer.** The seven plant Data
  Manager reads became Engineer (owner, 2026-10-13). Every non-GET route that
  depends on the Admin role -- found by walking the application, not from a
  list -- answers 403 to an Engineer, so the widening cannot have reached a
  write. The writes RO12 names are checked to be among them.
* **An Engineer alone can finish a sheet with held rows (D-RO12-3).** A sheet
  with a duplicate, a rejected and a quarantined row: the Engineer's direct
  commit waits on acknowledgements an Engineer may not write, and "Yes, load
  these rows" (`load-ready`, Engineer) records them in the Engineer's name
  and commits. No Admin step.
"""

from __future__ import annotations

import re

import pytest
from fastapi.routing import iter_route_contexts

from app.services.worksheet import YES_NOTE
from tests.test_t04_ingest import acknowledge, forget_bytes, make_workbook, unique_rows
from tests.test_t19_data_manager import ingest_as, mixed_workbook

# Imported for their side effect: a fixture is in scope where its function is
# in the module namespace (same reasoning as T19).
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)

pytestmark = pytest.mark.ingest

#: The Admin writes RO12 section 1 and D-RO12-2 name.
NAMED_ADMIN_WRITES = {
    ("POST", "/api/v1/plants/{plant_code}/workbooks/{file_hash}/acknowledgements"),
    ("POST", "/api/v1/plants/{plant_code}/workbooks/{file_hash}/overrides"),
    ("POST", "/api/v1/plants/{plant_code}/workbooks/{file_hash}/purge"),
    ("POST", "/api/v1/plants/{plant_code}/template-profiles/publish"),
    ("POST", "/api/v1/batches/{load_id}/abandon"),
    ("POST", "/api/v1/batches/{load_id}/restore"),
    ("POST", "/api/v1/standards"),
    ("POST", "/api/v1/standards/colours"),
    ("POST", "/api/v1/standards/plant-colours"),
    ("POST", "/api/v1/standards/plant-models"),
    ("POST", "/api/v1/standards/plant-models/offered"),
}


def _needs_admin(dependant) -> bool:
    return any(
        getattr(dep.call, "__name__", "") == "attributed_admin" or _needs_admin(dep)
        for dep in dependant.dependencies
    )


def admin_writes(app) -> set[tuple[str, str]]:
    """Every non-GET route whose dependencies include the Admin write role."""
    # FastAPI 0.141 nests included routers; this yields each route with its full path.
    return {
        (method, ctx.path)
        for ctx in iter_route_contexts(app.routes)
        if getattr(ctx.route, "dependant", None) is not None and _needs_admin(ctx.route.dependant)
        for method in (ctx.methods or set()) - {"GET", "HEAD"}
    }


def test_an_engineer_is_refused_every_admin_write(engineer, admin_conn, cleanup):
    review = ingest_as(engineer, cleanup, "ro12-writes.xlsx", make_workbook(unique_rows(2)))
    batch = review["batch"]
    values = {"plant_code": "AAT", "file_hash": batch["file_hash"], "load_id": str(batch["load_id"])}
    writes = admin_writes(engineer.app)
    assert NAMED_ADMIN_WRITES <= writes, sorted(NAMED_ADMIN_WRITES - writes)

    for method, path in sorted(writes):
        url = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), "1"), path)
        # The role check runs before the body is read, so an empty body is enough.
        response = engineer.request(method, url, json={})
        assert response.status_code == 403, (method, path, response.status_code, response.text)

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM review_acknowledgement WHERE load_id = %s", (batch["load_id"],)
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM review_override WHERE load_id = %s", (batch["load_id"],)
        )
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT status FROM load_batch WHERE load_id = %s", (batch["load_id"],))
        assert cur.fetchone()[0] == "PENDING_REVIEW", "nothing was abandoned or purged"


def test_an_engineer_alone_finishes_a_sheet_with_held_rows(engineer, admin_conn, cleanup):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "ro12-held.xlsx", data)
    batch = review["batch"]
    load_id, file_hash = batch["load_id"], batch["file_hash"]
    assert batch["counts"] == {
        "rows_in_file": 4, "rows_loaded": 1, "rows_duplicate": 1,
        "rows_rejected": 1, "rows_quarantine": 1, "balanced": True,
    }

    # The direct commit waits on the three acknowledgements...
    direct = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert direct.status_code == 409, direct.text
    assert "WARNINGS_UNACKNOWLEDGED" in direct.text
    # ...which the Admin route will not take from an Engineer.
    for category in ("DUPLICATE_ROWS", "REJECTED_ROWS", "QUARANTINED_MODELS"):
        assert acknowledge(engineer, review, category).status_code == 403

    # "Yes, load these rows" is the Engineer's own statement about the held rows.
    yes = engineer.post(f"/api/v1/plants/AAT/workbooks/{file_hash}/load-ready")
    assert yes.status_code == 200, yes.text
    assert yes.json()["measurements_inserted"] == 1

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT category, note, actor_user_id FROM review_acknowledgement "
            "WHERE load_id = %s ORDER BY category",
            (load_id,),
        )
        acks = cur.fetchall()
        cur.execute("SELECT status FROM load_batch WHERE load_id = %s", (load_id,))
        status = cur.fetchone()[0]
        cur.execute(
            "SELECT DISTINCT actor_user_id FROM audit_event "
            "WHERE action = 'batch.commit' AND entity_id = %s",
            (str(load_id),),
        )
        committers = [row[0] for row in cur.fetchall()]
    assert [a[0] for a in acks] == ["DUPLICATE_ROWS", "QUARANTINED_MODELS", "REJECTED_ROWS"]
    assert {a[1] for a in acks} == {YES_NOTE}
    assert len({a[2] for a in acks}) == 1 and acks[0][2] is not None
    assert status == "COMMITTED"
    assert committers == [acks[0][2]], "the same Engineer acknowledged and committed"
