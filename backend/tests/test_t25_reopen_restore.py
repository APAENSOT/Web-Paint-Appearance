"""T25 -- identical-file reopen and the restore route.

The claims, each made against the running application, worker and database:

* **Identical bytes never become a second batch.** Reopening changes
  `load_batch.status` on the rows that already hold those bytes. The number
  of `load_batch` rows for the hash, and the number of `wavescan` rows, are
  counted before and after, not inferred from a response.
* **Abandoned comes back to where it was.** The target status is the one the
  latest `batch.abandon` audit event recorded -- PENDING_REVIEW, or
  REJECTED_TEMPLATE for a sheet nobody could parse -- and a reopened
  PENDING_REVIEW sheet can still be committed.
* **Retired comes back only for an Admin.** SUPERSEDED returns to COMMITTED
  with `superseded_by` cleared and its facts current again through
  `v_wavescan_active`, and not one fact is inserted. An Engineer's identical
  upload of such a workbook is a 409 that changes nothing, including its
  abandoned siblings.
* **Live bytes, and another plant's bytes, stay refused.**

These run through T04's fixtures -- one worker for the whole suite. Every
batch is created by the test that asserts on it; the owner's own batches in
this database are never touched.
"""

from __future__ import annotations

import uuid

import pytest

from tests.test_t04_ingest import (
    XLSX_MIME,
    forget_bytes,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)

# Imported for their side effect: a fixture is in scope where its function is
# in the module namespace (same reasoning as T08 onward).
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)

pytestmark = pytest.mark.ingest

REOPEN_REASON = "Reopened by identical-file upload"


# =====================================================================
# helpers
# =====================================================================
def ingest_new(client, cleanup, name: str, data: bytes, plant: str = "AAT") -> list[dict]:
    """Upload fresh bytes, wait for every sheet, return the review bodies."""
    response = upload(client, name, data, expected_plant=plant)
    assert response.status_code == 202, response.text
    reviews = []
    for entry in response.json()["batches"]:
        cleanup.append(entry["load_id"])
        reviews.append(wait_for(client, entry["load_id"]))
    return reviews


def abandon(client, load_id: int):
    response = client.post(
        f"/api/v1/batches/{load_id}/abandon", json={"reason": "T25: X on the card."}
    )
    assert response.status_code == 200, response.text
    return response.json()


def supersede(client, load_id: int):
    response = client.post(
        f"/api/v1/batches/{load_id}/supersede", json={"reason": "T25: X on the card."}
    )
    assert response.status_code == 200, response.text
    return response.json()


def restore(client, load_id: int, reason: str = "T25: brought back on purpose."):
    return client.post(f"/api/v1/batches/{load_id}/restore", json={"reason": reason})


def batch_row(admin_conn, load_id: int) -> tuple:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT status, superseded_by, file_hash FROM load_batch WHERE load_id = %s",
            (load_id,),
        )
        return cur.fetchone()


def batches_for_hash(admin_conn, file_hash: str) -> list[int]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT load_id FROM load_batch WHERE file_hash = %s ORDER BY load_id",
            (file_hash,),
        )
        return [r[0] for r in cur.fetchall()]


def facts(admin_conn, load_id: int) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        return cur.fetchone()[0]


def active_facts(admin_conn, load_id: int) -> int:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM v_wavescan_active WHERE load_id = %s", (load_id,)
        )
        return cur.fetchone()[0]


def audit_actions(admin_conn, load_id: int) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT action, before ->> 'status', after ->> 'status', "
            "       after ->> 'reason', actor_user_id "
            "  FROM audit_event "
            " WHERE entity_type = 'load_batch' AND entity_id = %s ORDER BY id",
            (str(load_id),),
        )
        return cur.fetchall()


def job_row(admin_conn, load_id: int) -> tuple | None:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT job_id, status, attempts, enqueued_at FROM ingest_job "
            "WHERE load_id = %s",
            (load_id,),
        )
        return cur.fetchone()


def fresh_bytes(admin_conn, rows: list[dict] | None = None, **sheets) -> bytes:
    data = make_workbook(rows or unique_rows(3), sheets=sheets or None)
    forget_bytes(admin_conn, data)
    return data


# =====================================================================
# 1. abandoned -> reopened by an identical upload
# =====================================================================
def test_an_engineer_reopens_an_abandoned_workbook_on_the_same_load_id(
    engineer, admin, cleanup, admin_conn
):
    data = fresh_bytes(admin_conn)
    [review] = ingest_new(engineer, cleanup, "t25-abandoned.xlsx", data)
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    abandon(admin, load_id)
    job_before = job_row(admin_conn, load_id)
    assert batch_row(admin_conn, load_id)[0] == "ABANDONED"

    again = upload(engineer, "t25-abandoned-renamed.xlsx", data, expected_plant="AAT")
    assert again.status_code == 202, again.text
    body = again.json()
    assert body["accepted_files"] == 1
    assert [(b["load_id"], b["status"]) for b in body["batches"]] == [
        (load_id, "PENDING_REVIEW")
    ], "the same load_id, back where it was abandoned from"
    assert REOPEN_REASON in body["batches"][0]["detail"]
    assert "file_hash" not in body["batches"][0], "the 202 shape is unchanged"

    # No second batch, no second stored copy of the evidence, no job.
    assert batches_for_hash(admin_conn, file_hash) == [load_id]
    assert job_row(admin_conn, load_id) == job_before, "nothing was queued"
    assert batch_row(admin_conn, load_id)[0] == "PENDING_REVIEW", "not via RUNNING"
    assert facts(admin_conn, load_id) == 0

    last = audit_actions(admin_conn, load_id)[-1]
    assert last[:4] == ("batch.reopen", "ABANDONED", "PENDING_REVIEW", REOPEN_REASON)
    assert last[4] is not None, "a reopen names the person who uploaded"

    # It is a real review again: the Engineer can commit it.
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    assert facts(admin_conn, load_id) == 3


def test_a_sheet_abandoned_from_rejected_template_reopens_as_rejected_template(
    engineer, admin, cleanup, admin_conn
):
    """The target is what the abandon audit recorded, not a default."""
    from tests.test_t18_profiles import workbook

    data = workbook(unique_rows(2), rename={"Checkzone": f"Mystery {uuid.uuid4().hex[:8]}"})
    forget_bytes(admin_conn, data)
    response = upload(engineer, "t25-unknown-layout.xlsx", data, expected_plant="AAT")
    assert response.status_code == 202, response.text
    load_id = response.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    assert response.json()["batches"][0]["status"] == "REJECTED_TEMPLATE"
    abandon(admin, load_id)

    again = upload(engineer, "t25-unknown-layout.xlsx", data, expected_plant="AAT")
    assert again.status_code == 202, again.text
    assert again.json()["batches"][0]["status"] == "REJECTED_TEMPLATE"
    assert batch_row(admin_conn, load_id)[0] == "REJECTED_TEMPLATE"


def test_without_an_abandon_audit_the_sheet_reopens_as_pending_review(
    engineer, admin, cleanup, admin_conn
):
    """Fallback (locked decision 4). The owner sets ABANDONED directly, the way
    a batch abandoned before the audit event existed would look."""
    [review] = ingest_new(engineer, cleanup, "t25-no-audit.xlsx", fresh_bytes(admin_conn))
    load_id = review["batch"]["load_id"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "UPDATE load_batch SET status = 'ABANDONED' WHERE load_id = %s", (load_id,)
        )

    response = restore(admin, load_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PENDING_REVIEW"
    assert response.json()["audit_action"] == "batch.reopen"


# =====================================================================
# 2. superseded -> restored, Admin only
# =====================================================================
def test_an_engineer_cannot_restore_a_retired_workbook_by_uploading_it(
    engineer, admin, cleanup, admin_conn
):
    data = fresh_bytes(admin_conn)
    [review] = ingest_new(engineer, cleanup, "t25-retired.xlsx", data)
    load_id = review["batch"]["load_id"]
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    supersede(admin, load_id)
    audit_before = audit_actions(admin_conn, load_id)

    refused = upload(engineer, "t25-retired.xlsx", data, expected_plant="AAT")
    assert refused.status_code == 409, refused.text
    assert "Admin" in refused.json()["message"]
    assert batch_row(admin_conn, load_id)[0] == "SUPERSEDED"
    assert audit_actions(admin_conn, load_id) == audit_before, "nothing was written"
    assert active_facts(admin_conn, load_id) == 0


def test_an_admin_upload_restores_a_retired_workbook_without_inserting_a_fact(
    engineer, admin, cleanup, admin_conn
):
    data = fresh_bytes(admin_conn)
    [review] = ingest_new(engineer, cleanup, "t25-restore.xlsx", data)
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT array_agg(measurement_id ORDER BY measurement_id) FROM wavescan "
            "WHERE load_id = %s",
            (load_id,),
        )
        measurement_ids = cur.fetchone()[0]
    supersede(admin, load_id)
    assert active_facts(admin_conn, load_id) == 0
    listed = engineer.get("/api/v1/measurements", params={"load_id": load_id}).json()
    assert listed["page"]["total"] == 0

    again = upload(admin, "t25-restore.xlsx", data, expected_plant="AAT")
    assert again.status_code == 202, again.text
    assert [(b["load_id"], b["status"]) for b in again.json()["batches"]] == [
        (load_id, "COMMITTED")
    ]

    status, superseded_by, _ = batch_row(admin_conn, load_id)
    assert (status, superseded_by) == ("COMMITTED", None)
    assert batches_for_hash(admin_conn, file_hash) == [load_id]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT array_agg(measurement_id ORDER BY measurement_id) FROM wavescan "
            "WHERE load_id = %s",
            (load_id,),
        )
        assert cur.fetchone()[0] == measurement_ids, "the same facts, none inserted"
    assert active_facts(admin_conn, load_id) == 3, "current again through the view"
    listed = engineer.get("/api/v1/measurements", params={"load_id": load_id}).json()
    assert listed["page"]["total"] == 3

    last = audit_actions(admin_conn, load_id)[-1]
    assert last[:4] == ("batch.restore", "SUPERSEDED", "COMMITTED", REOPEN_REASON)


def test_a_mixed_workbook_is_all_or_nothing_for_an_engineer(
    engineer, admin, cleanup, admin_conn
):
    """One sheet retired after commit, one abandoned. An Engineer gets 409 and
    the abandoned sibling stays abandoned; an Admin brings both back, each by
    its own rule."""
    data = fresh_bytes(
        admin_conn, PasteData=unique_rows(2), Sheet2=unique_rows(2)
    )
    first, second = ingest_new(engineer, cleanup, "t25-mixed.xlsx", data)
    committed_id = first["batch"]["load_id"]
    abandoned_id = second["batch"]["load_id"]
    assert engineer.post(f"/api/v1/batches/{committed_id}/commit").status_code == 200
    supersede(admin, committed_id)
    abandon(admin, abandoned_id)

    refused = upload(engineer, "t25-mixed.xlsx", data, expected_plant="AAT")
    assert refused.status_code == 409, refused.text
    assert batch_row(admin_conn, committed_id)[0] == "SUPERSEDED"
    assert batch_row(admin_conn, abandoned_id)[0] == "ABANDONED"

    again = upload(admin, "t25-mixed.xlsx", data, expected_plant="AAT")
    assert again.status_code == 202, again.text
    assert sorted((b["load_id"], b["status"]) for b in again.json()["batches"]) == sorted([
        (committed_id, "COMMITTED"), (abandoned_id, "PENDING_REVIEW"),
    ])
    assert audit_actions(admin_conn, committed_id)[-1][0] == "batch.restore"
    assert audit_actions(admin_conn, abandoned_id)[-1][0] == "batch.reopen"


# =====================================================================
# 3. what stays refused
# =====================================================================
def test_a_live_hash_is_still_a_409_even_for_an_admin(engineer, admin, cleanup, admin_conn):
    data = fresh_bytes(admin_conn)
    [review] = ingest_new(engineer, cleanup, "t25-live.xlsx", data)
    load_id = review["batch"]["load_id"]

    refused = upload(admin, "t25-live.xlsx", data, expected_plant="AAT")
    assert refused.status_code == 409, refused.text
    assert str(load_id) in refused.json()["message"]
    assert batch_row(admin_conn, load_id)[0] == "PENDING_REVIEW"


def test_a_live_duplicate_refuses_the_whole_request(engineer, admin, cleanup, admin_conn):
    """Classification runs over every file before anything is written, so a
    new file in the same request is not opened and an abandoned one is not
    reopened."""
    live = fresh_bytes(admin_conn)
    [live_review] = ingest_new(engineer, cleanup, "t25-live-a.xlsx", live)
    gone = fresh_bytes(admin_conn)
    [gone_review] = ingest_new(engineer, cleanup, "t25-gone.xlsx", gone)
    abandon(admin, gone_review["batch"]["load_id"])
    new = fresh_bytes(admin_conn)

    response = engineer.post(
        "/api/v1/uploads",
        files=[
            ("files", ("t25-gone.xlsx", gone, XLSX_MIME)),
            ("files", ("t25-new.xlsx", new, XLSX_MIME)),
            ("files", ("t25-live-a.xlsx", live, XLSX_MIME)),
        ],
        data={"expected_plant": "AAT"},
    )
    assert response.status_code == 409, response.text
    assert batch_row(admin_conn, gone_review["batch"]["load_id"])[0] == "ABANDONED"
    import hashlib

    assert batches_for_hash(admin_conn, hashlib.sha256(new).hexdigest()) == []
    assert batch_row(admin_conn, live_review["batch"]["load_id"])[0] == "PENDING_REVIEW"


def test_a_reopen_and_a_new_file_in_one_request_both_land(
    engineer, admin, cleanup, admin_conn
):
    gone = fresh_bytes(admin_conn)
    [gone_review] = ingest_new(engineer, cleanup, "t25-gone-2.xlsx", gone)
    gone_id = gone_review["batch"]["load_id"]
    abandon(admin, gone_id)
    new = fresh_bytes(admin_conn)

    response = engineer.post(
        "/api/v1/uploads",
        files=[
            ("files", ("t25-gone-2.xlsx", gone, XLSX_MIME)),
            ("files", ("t25-new-2.xlsx", new, XLSX_MIME)),
        ],
        data={"expected_plant": "AAT"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted_files"] == 2
    by_file = {b["filename"]: b for b in body["batches"]}
    assert by_file["t25-gone-2.xlsx"]["load_id"] == gone_id
    assert by_file["t25-gone-2.xlsx"]["status"] == "PENDING_REVIEW"
    new_id = by_file["t25-new-2.xlsx"]["load_id"]
    cleanup.append(new_id)
    assert new_id != gone_id
    assert wait_for(engineer, new_id)["batch"]["status"] == "PENDING_REVIEW"


def test_identical_bytes_for_another_plant_do_not_reopen(
    engineer, admin, cleanup, admin_conn
):
    """Plant cells are blank, so the T17 gate passes for either plant and the
    hash lookup is what has to refuse: these bytes are AAT's workbook."""
    rows = [{**r, "Plant": None} for r in unique_rows(2)]
    data = fresh_bytes(admin_conn, rows)
    [review] = ingest_new(engineer, cleanup, "t25-blank-plant.xlsx", data)
    load_id = review["batch"]["load_id"]
    assert review["batch"]["plant_code"] == "AAT"
    abandon(admin, load_id)

    refused = upload(admin, "t25-blank-plant.xlsx", data, expected_plant="FTM")
    assert refused.status_code == 409, refused.text
    assert "FTM" in refused.json()["message"] and "AAT" in refused.json()["message"]
    assert batch_row(admin_conn, load_id)[0] == "ABANDONED"


# =====================================================================
# 4. POST /batches/{load_id}/restore
# =====================================================================
def test_the_restore_route_brings_back_both_kinds(engineer, admin, cleanup, admin_conn):
    [kept] = ingest_new(engineer, cleanup, "t25-route-a.xlsx", fresh_bytes(admin_conn))
    [dropped] = ingest_new(engineer, cleanup, "t25-route-b.xlsx", fresh_bytes(admin_conn))
    kept_id = kept["batch"]["load_id"]
    dropped_id = dropped["batch"]["load_id"]
    assert engineer.post(f"/api/v1/batches/{kept_id}/commit").status_code == 200
    supersede(admin, kept_id)
    abandon(admin, dropped_id)

    first = restore(admin, kept_id, "  Retired by mistake  ")
    assert first.status_code == 200, first.text
    assert first.json() == {
        "load_id": kept_id, "status": "COMMITTED", "previous_status": "SUPERSEDED",
        "reason": "Retired by mistake", "audit_action": "batch.restore",
    }
    assert active_facts(admin_conn, kept_id) == 3

    second = restore(admin, dropped_id)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "PENDING_REVIEW"
    assert second.json()["previous_status"] == "ABANDONED"
    assert second.json()["audit_action"] == "batch.reopen"
    assert facts(admin_conn, dropped_id) == 0


def test_the_restore_route_refuses_what_is_not_retired(engineer, admin, cleanup):
    [review] = ingest_new(engineer, cleanup, "t25-route-live.xlsx", make_workbook(unique_rows(2)))
    load_id = review["batch"]["load_id"]
    assert restore(admin, load_id).status_code == 409
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    refused = restore(admin, load_id)
    assert refused.status_code == 409
    assert "COMMITTED" in refused.json()["message"]


@pytest.mark.parametrize("role", ["engineer", "viewer"])
def test_only_an_admin_may_call_restore(request, role, admin, engineer, cleanup):
    [review] = ingest_new(engineer, cleanup, "t25-route-rbac.xlsx", make_workbook(unique_rows(2)))
    load_id = review["batch"]["load_id"]
    abandon(admin, load_id)
    caller = request.getfixturevalue(role)
    assert restore(caller, load_id).status_code == 403


def test_the_restore_route_validates_its_body_and_its_target(admin):
    assert restore(admin, 999_999_999).status_code == 404
    assert restore(admin, 999_999_999, "   ").status_code == 422
    assert admin.post("/api/v1/batches/1/restore", json={}).status_code == 422
    assert admin.post(
        "/api/v1/batches/1/restore", json={"reason": "x", "status": "COMMITTED"}
    ).status_code == 422, "the target status is not the caller's to choose"


# =====================================================================
# 5. structure
# =====================================================================
def test_nothing_gained_a_delete_grant(app_conn):
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, privilege_type FROM information_schema.role_table_grants
             WHERE grantee = current_user
               AND table_name IN ('wavescan', 'load_batch')
               AND privilege_type IN ('DELETE', 'TRUNCATE')
            """
        )
        assert cur.fetchall() == []


def test_the_ingest_service_still_cannot_change_a_batch_status_by_itself():
    """Ingest decides whether identical bytes may come back; the status change
    is the correction service's, called by the route. Narrower than a ban on
    the words: ingest never imports that service and never calls restore."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/services/ingest.py").read_text(
        encoding="utf-8"
    )
    for banned in ("CorrectionService", "services.corrections", "restore_batch",
                   "abandon_batch", "supersede_batch"):
        assert banned not in source, banned


def test_the_contract_has_32_paths_and_the_restore_post(admin):
    spec = admin.get("/openapi.json").json()
    # T26 CHANGE: 32 -> 33 (POST /plants/{plant_code}/template-profiles/publish).
    # T-STANDARDS-D2 CHANGE: 33 -> 38.
    # Monthly Overview CHANGE: 38 -> 39.
    # T37 CHANGE: 39 -> 40 (POST /plants/{plant_code}/workbooks/{file_hash}/purge).
    # T39 CHANGE: 40 -> 46 (worksheet GET + five Engineer POSTs).
    # T48 CHANGE: 46 -> 49 (three FilmThickness GETs).
    # T62 CHANGE: 49 -> 51 (FilmThickness standards GET + Admin POST).
    # T66 CHANGE: 51 -> 52 (FilmThickness monthly overview GET).
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(spec["paths"]) >= 52, sorted(spec["paths"])
    route = spec["paths"]["/api/v1/batches/{load_id}/restore"]
    assert set(route) == {"post"}
    body = route["post"]["requestBody"]["content"]["application/json"]["schema"]
    schema = spec["components"]["schemas"][body["$ref"].rsplit("/", 1)[-1]]
    assert set(schema["properties"]) == {"reason"}
    assert set(spec["components"]["schemas"]["UploadedSheet"]["properties"]) == {
        "filename", "sheet", "load_id", "status", "detail",
    }, "the 202 shape is unchanged"
