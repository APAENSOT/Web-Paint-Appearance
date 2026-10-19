"""T17 -- the plant-scope contract on `POST /api/v1/uploads`.

An upload now declares which plant it is for. The server checks that claim
against `ref_plant` and against every sheet's own Plant column **before** the
bytes reach the object store and before any `load_batch` exists, and blank
Plant cells inherit the declared plant with the fill counted on the batch's
audit event (`docs/tasks/T17-expected-plant.md`, design M3).

Two claims here cannot be made against a mock, so nothing here uses one:

* **A refusal leaves nothing behind.** Proven by counting `load_batch` rows
  in PostgreSQL *and* asking the real content-addressed store whether the
  object exists. "The service returned 400" is not the same statement.
* **A filled blank is disclosed.** Proven by reading `audit_event.after`
  written in the same transaction as the batch it describes, not by reading
  back a value the service returned to itself.

These run against the same application, worker and database as T04, through
T04's fixtures, because a second set would be a second worker racing the
first for the same jobs.
"""

from __future__ import annotations

import hashlib
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.services.raw_store import key_for
from tests.test_t04_ingest import (
    XLSX_MIME,
    forget_bytes,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)

# Imported for their side effect: a fixture is in scope where its function is
# in the module namespace (same reasoning as T08).
from tests.test_t04_ingest import (  # noqa: F401
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)

pytestmark = pytest.mark.ingest


# =====================================================================
# helpers
# =====================================================================
def blank_plant_rows(count: int = 3, **over) -> list[dict]:
    """Rows whose Plant cell is empty -- the case `expected_plant` answers."""
    return [{**row, "Plant": None} for row in unique_rows(count, **over)]


def upload_many(
    client: TestClient, files: list[tuple[str, bytes]], expected_plant: str
):
    """One multipart request carrying several workbooks.

    Request atomicity is a claim about a *request*, so it needs a request
    with more than one file in it.
    """
    return client.post(
        "/api/v1/uploads",
        files=[("files", (name, data, XLSX_MIME)) for name, data in files],
        data={"expected_plant": expected_plant},
    )


def batch_count(admin_conn) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM load_batch")
        return cur.fetchone()[0]


def batches_for(admin_conn, data: bytes) -> list[tuple]:
    """Every batch holding these exact bytes. The leftover proof."""
    digest = hashlib.sha256(data).hexdigest()
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT load_id, source_sheet, status, plant_code FROM load_batch "
            "WHERE file_hash = %s ORDER BY load_id",
            (digest,),
        )
        return cur.fetchall()


def stored(client: TestClient, data: bytes) -> bool:
    """Does the object store hold these bytes?

    Asked of the real store the application writes to, because "no leftover
    object" is the half of the refusal a database count cannot see. Content
    addressing means this is also a statement about *these* bytes and not
    about a filename somebody chose.
    """
    return client.app.state.raw_store.exists(key_for(hashlib.sha256(data).hexdigest()))


def audit_upload(admin_conn, load_id: int) -> dict:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT after FROM audit_event WHERE entity_type = 'load_batch' "
            "AND entity_id = %s AND action = 'batch.upload'",
            (str(load_id),),
        )
        row = cur.fetchone()
    assert row is not None, f"batch {load_id} has no batch.upload audit event"
    return row[0]


@pytest.fixture()
def paused_engineer(engineer) -> TestClient:
    """The Engineer client with its worker stopped for one test.

    Needed for one claim only: that `load_batch.plant_code` is the expected
    plant *at create time*, not something a later parse fills in. With a
    worker running, the batch would already have left RUNNING before the
    assertion could look.

    The worker is paused rather than a second application being built, the
    same way T04 does it: another app means another connection pool against a
    cluster that has a connection limit, and another worker racing this one
    for the same jobs.
    """
    worker = engineer.app.state.ingest_worker
    worker.stop()
    yield engineer
    worker.start()


@pytest.fixture()
def inactive_plant(admin_conn) -> str:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT plant_code FROM ref_plant WHERE NOT is_active LIMIT 1")
        row = cur.fetchone()
    if row is None:
        pytest.skip("no inactive plant in ref_plant to exercise the gate")
    return row[0]


# =====================================================================
# 1. the field is required
# =====================================================================
def test_an_upload_without_expected_plant_is_refused(engineer, admin_conn):
    """The T16 SPA sends `files` only. That body is now incomplete, and the
    refusal has to say which field is missing rather than 500 or guess."""
    data = make_workbook(unique_rows(2))
    before = batch_count(admin_conn)

    response = upload(engineer, "t17-no-plant.xlsx", data, expected_plant=None)

    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"statusCode", "error", "message", "correlationId"}
    assert "expected_plant" in body["message"]
    assert batch_count(admin_conn) == before
    assert not stored(engineer, data), "a refused request stored bytes"


def test_a_blank_expected_plant_is_refused_like_a_missing_one(engineer, admin_conn):
    """"   " is present, so it passes multipart validation. It still does not
    name a plant, and the route may not pick one."""
    data = make_workbook(unique_rows(2))
    before = batch_count(admin_conn)

    response = engineer.post(
        "/api/v1/uploads",
        files={"files": ("t17-blank-plant.xlsx", data, XLSX_MIME)},
        data={"expected_plant": "   "},
    )

    assert response.status_code == 422, response.text
    assert "expected_plant" in response.json()["message"]
    assert batch_count(admin_conn) == before
    assert not stored(engineer, data)


def test_an_unknown_expected_plant_is_refused_before_anything_is_stored(
    engineer, admin_conn
):
    """`ref_plant` is the authority: the client names a plant, the server
    decides whether that is one."""
    data = make_workbook(unique_rows(2))
    before = batch_count(admin_conn)

    response = upload(engineer, "t17-narnia-scope.xlsx", data, expected_plant="NARNIA")

    assert response.status_code == 400, response.text
    message = response.json()["message"]
    assert "EXPECTED_PLANT_UNKNOWN" in message and "NARNIA" in message
    assert batch_count(admin_conn) == before
    assert not stored(engineer, data)


# =====================================================================
# 2. the plant gate -- wrong plant leaves nothing behind
# =====================================================================
def _mismatches(admin_conn, load_id: int) -> list[str]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT offending_value FROM reject_log "
            "WHERE load_id = %s AND reject_reason = 'PLANT_MISMATCH' "
            "ORDER BY source_row",
            (load_id,),
        )
        return [r[0] for r in cur.fetchall()]


def _loaded_plants(admin_conn, load_id: int) -> list[str]:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT plant FROM wavescan WHERE load_id = %s", (load_id,))
        return [r[0] for r in cur.fetchall()]


def test_a_workbook_from_another_plant_is_held_and_asked_not_refused(
    engineer, admin_conn, cleanup
):
    """T39 CHANGE (ADR 0013 decision 3). An AAT workbook uploaded from the
    FTM page used to be a 400 with nothing stored. Now the file gets a card:
    the batch is filed under the page plant, every row is held as
    PLANT_MISMATCH naming what the cell said, and nothing is relabelled
    until an Engineer answers."""
    data = make_workbook(unique_rows(3))  # BASE_ROW is AAT
    forget_bytes(admin_conn, data)

    response = upload(engineer, "t17-wrong-plant.xlsx", data, expected_plant="FTM")

    assert response.status_code == 202, response.text
    [entry] = response.json()["batches"]
    cleanup.append(entry["load_id"])
    review = wait_for(engineer, entry["load_id"])
    assert review["batch"]["plant_code"] == "FTM"
    assert review["batch"]["counts"]["rows_loaded"] == 0
    assert review["reject_reasons"] == {"PLANT_MISMATCH": 3}
    assert _mismatches(admin_conn, entry["load_id"]) == ["AAT", "AAT", "AAT"]
    assert audit_upload(admin_conn, entry["load_id"])["plant_texts_to_confirm"] == ["AAT"]
    held = [h for h in review["held_labels"] if h["reason"] == "PLANT_MISMATCH"]
    assert held and held[0]["display_group"] == "plant"
    assert "FTM" in held[0]["operator_message"]
    assert stored(engineer, data), "the file is kept so the question can be answered"


def test_a_mixed_plant_workbook_loads_the_agreeing_sheet_and_asks_about_the_other(
    engineer, admin_conn, cleanup
):
    """T39 CHANGE. Sheet A says AAT, Sheet B says FTM, uploaded as AAT: A is
    reviewable as AAT, B's rows are held and asked about. Neither is filed
    under FTM and neither is relabelled."""
    data = make_workbook(
        [],
        sheets={
            "Sheet A": unique_rows(2),
            "Sheet B": [{**row, "Plant": "FTM"} for row in unique_rows(2)],
        },
    )
    forget_bytes(admin_conn, data)

    response = upload(engineer, "t17-mixed.xlsx", data, expected_plant="AAT")

    assert response.status_code == 202, response.text
    by_sheet = {}
    for entry in response.json()["batches"]:
        cleanup.append(entry["load_id"])
        by_sheet[entry["sheet"]] = wait_for(engineer, entry["load_id"])
    assert by_sheet["Sheet A"]["batch"]["counts"]["rows_loaded"] == 2
    assert by_sheet["Sheet B"]["batch"]["counts"]["rows_loaded"] == 0
    assert by_sheet["Sheet B"]["reject_reasons"] == {"PLANT_MISMATCH": 2}


def test_one_disagreeing_file_no_longer_refuses_the_files_uploaded_with_it(
    engineer, admin_conn, cleanup
):
    """T39 CHANGE. Both files are stored and get cards; only the rows that
    name another plant wait for an answer."""
    good = make_workbook(unique_rows(2))
    bad = make_workbook([{**row, "Plant": "FTM"} for row in unique_rows(2)])
    forget_bytes(admin_conn, good)
    forget_bytes(admin_conn, bad)

    response = upload_many(
        engineer, [("t17-good.xlsx", good), ("t17-bad.xlsx", bad)], "AAT"
    )

    assert response.status_code == 202, response.text
    for entry in response.json()["batches"]:
        cleanup.append(entry["load_id"])
        wait_for(engineer, entry["load_id"])
    assert stored(engineer, good) and stored(engineer, bad)
    bad_id = batches_for(admin_conn, bad)[0][0]
    assert _mismatches(admin_conn, bad_id) == ["FTM", "FTM"]


def test_an_aggregate_sentinel_in_the_plant_column_is_not_a_scope_conflict(
    engineer, admin_conn, cleanup
):
    """FVL monthly files write `[All]` on roll-up rows (T26 S16).

    That is not a plant name. Refusing it would block the leaf rows of the
    same named workbook; storing it as the declared plant would invent a
    vehicle. The plant gate skips documented sentinels; parse still stages
    them as `AGGREGATE_ROW`.
    """
    rows = unique_rows(2)
    rows.append({**rows[0], "Plant": "[All]", "Model": "[All]", "Checkzone": "[All]"})
    data = make_workbook(rows)

    response = upload(engineer, "t17-all-plant.xlsx", data, expected_plant="AAT")

    assert response.status_code == 202, response.text
    load_id = response.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    assert stored(engineer, data)
    assert batches_for(admin_conn, data), "leaf rows must still open a batch"


def test_an_unknown_plant_string_is_held_and_asked_not_refused(
    engineer, admin_conn, cleanup
):
    """T39 CHANGE (ADR 0013 decision 3): `NARNIA` (or `U704` with no plant)
    in a Plant cell is a question for the Engineer, not a door refusal and
    not a silent fill. The rows are held as PLANT_MISMATCH."""
    data = make_workbook([{**row, "Plant": "NARNIA"} for row in unique_rows(2)])
    forget_bytes(admin_conn, data)

    response = upload(engineer, "t17-narnia-cell.xlsx", data, expected_plant="AAT")

    assert response.status_code == 202, response.text
    [entry] = response.json()["batches"]
    cleanup.append(entry["load_id"])
    wait_for(engineer, entry["load_id"])
    assert _mismatches(admin_conn, entry["load_id"]) == ["NARNIA", "NARNIA"]
    assert _loaded_plants(admin_conn, entry["load_id"]) == []


def test_an_inactive_expected_plant_is_still_the_d5_refusal(
    engineer, admin_conn, inactive_plant
):
    """Blank plant cells, declared scope is a plant that is not onboarded.

    Nothing in the workbook conflicts, so the remaining answer is D5's, with
    the same copy T04 shipped and still no batch.
    """
    data = make_workbook(blank_plant_rows(2))
    before = batch_count(admin_conn)

    response = upload(
        engineer, "t17-inactive.xlsx", data, expected_plant=inactive_plant
    )

    assert response.status_code == 422, response.text
    message = response.json()["message"]
    assert "PLANT_NOT_ONBOARDED" in message
    assert inactive_plant in message and "D5" in message
    assert batch_count(admin_conn) == before
    assert not stored(engineer, data)


def test_a_conflicting_cell_outranks_the_onboarding_refusal(
    engineer, admin_conn, inactive_plant
):
    """T17 locked decision 7: when both are true, say the more precise one."""
    data = make_workbook(unique_rows(2))  # AAT cells
    before = batch_count(admin_conn)

    response = upload(
        engineer, "t17-inactive-conflict.xlsx", data, expected_plant=inactive_plant
    )

    # T39 CHANGE: a disagreeing cell is no longer a door refusal, so the D5
    # refusal of the declared plant is the answer.
    assert response.status_code == 422, response.text
    assert "PLANT_NOT_ONBOARDED" in response.json()["message"]
    assert batch_count(admin_conn) == before
    assert not stored(engineer, data)


# =====================================================================
# 3. blank cells inherit the declared plant, and the fill is disclosed
# =====================================================================
def test_the_batch_is_filed_under_the_expected_plant_at_create_time(
    paused_engineer, cleanup, admin_conn
):
    """`load_batch.plant_code` is the declared plant while the batch is still
    RUNNING -- before any row has been read.

    This is the assertion that `_dominant_plant` is gone. That helper set the
    column *after* parsing, to NULL when the rows disagreed; a batch that has
    not been parsed yet had no plant at all.
    """
    data = make_workbook(blank_plant_rows(3))
    forget_bytes(admin_conn, data)

    response = upload(paused_engineer, "t17-at-create.xlsx", data, expected_plant="AAT")
    assert response.status_code == 202, response.text
    entry = response.json()["batches"][0]
    load_id = entry["load_id"]
    cleanup.append(load_id)
    assert entry["status"] == "RUNNING"

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT status, plant_code FROM load_batch WHERE load_id = %s", (load_id,)
        )
        status, plant_code = cur.fetchone()
    assert status == "RUNNING"
    assert plant_code == "AAT"

    after = audit_upload(admin_conn, load_id)
    assert after["expected_plant"] == "AAT"
    assert after["plant_column_present"] is True
    assert after["plant_cells_filled"] == 3, (
        "every blank Plant cell must be counted as evidence of the fill"
    )
    assert after["first_filled_row"] == 2


def test_blank_plant_cells_become_the_expected_plant_on_every_clean_row(
    engineer, cleanup, admin_conn
):
    rows = blank_plant_rows(4)
    data = make_workbook(rows)
    forget_bytes(admin_conn, data)

    response = upload(engineer, "t17-fill.xlsx", data, expected_plant="AAT")
    assert response.status_code == 202, response.text
    load_id = response.json()["batches"][0]["load_id"]
    cleanup.append(load_id)

    review = wait_for(engineer, load_id)
    batch = review["batch"]
    assert batch["status"] == "PENDING_REVIEW", batch
    assert batch["plant_code"] == "AAT"
    assert batch["counts"] == {
        "rows_in_file": 4, "rows_loaded": 4, "rows_duplicate": 0,
        "rows_rejected": 0, "rows_quarantine": 0, "balanced": True,
    }, "a blank Plant cell is no longer a MISSING_REQUIRED_FIELD reject"

    assert audit_upload(admin_conn, load_id)["plant_cells_filled"] == 4

    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT plant FROM wavescan WHERE load_id = %s", (load_id,)
        )
        assert [r[0] for r in cur.fetchall()] == ["AAT"], (
            "a filled blank must reach the fact table as the declared plant"
        )
        cur.execute(
            "SELECT count(*) FROM stg_raw WHERE load_id = %s AND "
            "(raw_plant IS NULL OR raw_plant = '')",
            (load_id,),
        )
        assert cur.fetchone()[0] == 4, (
            "staging keeps what the file said; the fill is not written back "
            "over the evidence"
        )


def test_a_matching_nonblank_plant_cell_is_not_counted_as_filled(
    engineer, cleanup, admin_conn
):
    """The count is fill evidence, not a row count."""
    data = make_workbook(unique_rows(2))  # AAT cells, declared AAT
    forget_bytes(admin_conn, data)
    response = upload(engineer, "t17-nofill.xlsx", data, expected_plant="AAT")
    assert response.status_code == 202, response.text
    load_id = response.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    wait_for(engineer, load_id)

    after = audit_upload(admin_conn, load_id)
    assert after["plant_cells_filled"] == 0
    assert after["first_filled_row"] is None
    assert after["expected_plant"] == "AAT"


def test_an_alias_spelling_of_the_expected_plant_is_accepted(
    engineer, cleanup, admin_conn
):
    """`expected_plant` resolves through `ref_plant_alias`, the same table a
    cell resolves through. A lower-case route code is not a different plant."""
    data = make_workbook(unique_rows(2))
    forget_bytes(admin_conn, data)
    response = upload(engineer, "t17-alias-scope.xlsx", data, expected_plant="aat")
    assert response.status_code == 202, response.text
    load_id = response.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    with admin_conn.cursor() as cur:
        cur.execute("SELECT plant_code FROM load_batch WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == "AAT", "the canonical code is stored, not the claim"


def test_a_replay_reuses_the_batchs_own_plant_scope(engineer, cleanup, admin_conn):
    """`02-PIPELINE.md` section 8: replay re-runs stored bytes through the same
    service. The expected plant comes from the batch, not from a second
    client claim -- there is no re-upload to carry one."""
    data = make_workbook(blank_plant_rows(2))
    forget_bytes(admin_conn, data)
    response = upload(engineer, "t17-replay.xlsx", data, expected_plant="AAT")
    load_id = response.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    assert wait_for(engineer, load_id)["batch"]["status"] == "PENDING_REVIEW"

    service = engineer.app.state.ingest_service
    with engineer.app.state.database.connect() as conn:
        with conn.begin():
            service.replay_batch(
                conn, load_id, actor_user_id=None, reason="T17 replay of a filled batch"
            )

    review = wait_for(engineer, load_id)
    assert review["batch"]["status"] == "PENDING_REVIEW"
    assert review["batch"]["plant_code"] == "AAT"
    assert review["batch"]["counts"]["rows_loaded"] == 2, (
        "the blanks must fill on replay too, or a replayed batch would reject "
        "rows the first parse accepted"
    )


# =====================================================================
# 4. what T17 must not have changed
# =====================================================================
def test_identical_bytes_are_still_409_after_a_valid_expected_plant(
    engineer, cleanup, admin_conn
):
    """The duplicate guard now runs *after* the plant gate. It still runs."""
    data = make_workbook(unique_rows(2))
    forget_bytes(admin_conn, data)
    first = upload(engineer, "t17-dup.xlsx", data, expected_plant="AAT")
    assert first.status_code == 202, first.text
    load_id = first.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    wait_for(engineer, load_id)

    again = upload(engineer, "t17-dup-again.xlsx", data, expected_plant="AAT")
    assert again.status_code == 409
    assert f"load_id {load_id}" in again.json()["message"]


def test_known_bytes_on_another_plant_page_are_still_refused(
    engineer, cleanup, admin_conn
):
    """T39 CHANGE: the plant gate no longer refuses, so identical bytes filed
    under AAT and sent again from FTM meet the duplicate guard (T25: another
    plant's bytes stay refused). Still a refusal, still nothing new stored."""
    data = make_workbook(unique_rows(2))
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t17-order.xlsx", data, expected_plant="AAT")
    assert accepted.status_code == 202, accepted.text
    cleanup.append(accepted.json()["batches"][0]["load_id"])

    again = upload(engineer, "t17-order.xlsx", data, expected_plant="FTM")
    assert again.status_code == 409, again.text
    assert len(batches_for(admin_conn, data)) == 1


def test_a_viewer_still_cannot_upload_and_an_engineer_still_can(
    viewer, engineer, cleanup, admin_conn
):
    """T17 locked decision 8: `POST /uploads` stays Engineer (Admin
    outranks). RBAC is checked before the body is, so a Viewer sending a
    perfectly formed request is still refused."""
    refused = upload(viewer, "t17-viewer.xlsx", make_workbook(unique_rows(1)))
    assert refused.status_code == 403
    assert "engineer" in refused.json()["message"]

    data = make_workbook(unique_rows(2))
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t17-engineer.xlsx", data, expected_plant="AAT")
    assert accepted.status_code == 202, accepted.text
    cleanup.append(accepted.json()["batches"][0]["load_id"])


def test_app_rw_still_cannot_update_or_delete_a_measurement(app_conn):
    """ADR 0005, re-asserted here because T17 touches the path that writes
    them. A plant fill must not have arrived with a grant."""
    for sql in (
        "UPDATE wavescan SET cf = cf + 1 WHERE measurement_id = "
        "(SELECT min(measurement_id) FROM wavescan)",
        "DELETE FROM wavescan WHERE measurement_id = "
        "(SELECT min(measurement_id) FROM wavescan)",
    ):
        with app_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(sql)
        app_conn.rollback()


def test_the_dominant_plant_helper_is_gone_from_the_upload_path():
    """T17 locked decision 6. The helper picked a plant from parsed rows and
    wrote NULL when they disagreed; on a plant-scoped upload that is a
    defect, so it is not dead code -- it is deleted."""
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    for module in ("app/services/ingest.py", "app/workers/ingest_worker.py"):
        source = (backend / module).read_text(encoding="utf-8")
        offending = [
            line
            for line in source.splitlines()
            if "_dominant_plant" in line and not line.lstrip().startswith(("#", "*"))
            and '``_dominant_plant``' not in line
        ]
        assert not offending, f"{module} still calls _dominant_plant: {offending}"


def test_the_cleaner_still_imports_no_framework():
    """`00-ARCHITECTURE.md` section 5 rule 1. `expected_plant` is injected as a
    string; it did not arrive as a Request, a Settings, or a connection."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "domain" / "cleaner.py"
    ).read_text(encoding="utf-8")
    for banned in ("import fastapi", "from fastapi", "import psycopg",
                   "import sqlalchemy", "from sqlalchemy"):
        assert banned not in source, f"domain/cleaner.py imports {banned}"


def test_a_row_that_names_another_plant_is_held_rather_than_relabelled(
    engineer, cleanup, admin_conn
):
    """The defence behind the question (T39 CHANGE).

    A batch filed as FTM whose bytes say AAT: every row is held as
    PLANT_MISMATCH. Writing them as FTM would be the silent wrong label;
    writing them as AAT under an FTM batch would be a fact nobody can trace
    back to its page. Staging is kept and nothing reaches `wavescan`.
    """
    data = make_workbook(unique_rows(2))
    forget_bytes(admin_conn, data)
    service = engineer.app.state.ingest_service
    digest = hashlib.sha256(data).hexdigest()
    service.store.put(digest, data)

    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO load_batch (source_file, source_sheet, file_hash, "
            "raw_store_key, status, plant_code) "
            "VALUES (%s, 'PasteData', %s, %s, 'RUNNING', 'FTM') RETURNING load_id",
            (f"t17-scope-{uuid.uuid4().hex[:8]}.xlsx", digest, key_for(digest)),
        )
        load_id = cur.fetchone()[0]
        cleanup.append(load_id)
        cur.execute(
            "INSERT INTO ingest_job (load_id, status) VALUES (%s, 'QUEUED')", (load_id,)
        )

    body = wait_for(engineer, load_id, timeout=40)
    assert body["batch"]["counts"]["rows_loaded"] == 0, body["batch"]
    assert body["reject_reasons"] == {"PLANT_MISMATCH": 2}
    assert body["staged_rows"] == 2, "staging is kept for investigation"
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 0


def test_a_workbook_with_no_plant_column_is_filed_under_the_declared_plant(
    engineer, cleanup, admin_conn
):
    """T18 CHANGE, and it is T17's leftover being closed rather than a T17
    claim being weakened.

    T17 shipped with this case refused: the gate passed -- there is nothing
    to disagree with -- but `plant` is one of `reader.REQUIRED_FIELDS`, so a
    sheet without the column was `REJECTED_TEMPLATE`. T18 makes that a
    decision a **profile** takes: the seeded AAT profile for this layout sets
    `fill_missing_plant`, so the column is supplied from `expected_plant` and
    the sheet parses.

    What T17 owed is unchanged and is still asserted here: the batch is filed
    under the plant that was declared. The same workbook with no matching
    profile is still refused -- that is
    `test_t18_profiles.py::test_a_layout_with_no_profile_is_refused_before_any_row_is_read`.
    """
    from io import BytesIO

    from openpyxl import Workbook

    from tests.test_t04_ingest import BASE_ROW, HEADERS

    headers = [h for h in HEADERS if h != "Plant"]
    wb = Workbook()
    ws = wb.active
    ws.title = "PasteData"
    ws.append(headers)
    ws.append([{**BASE_ROW, "Serial No": f"T17-{uuid.uuid4().hex[:8]}"}[h] for h in headers])
    buffer = BytesIO()
    wb.save(buffer)
    data = buffer.getvalue()
    forget_bytes(admin_conn, data)

    response = upload(engineer, "t17-no-plant-column.xlsx", data, expected_plant="AAT")

    assert response.status_code == 202, response.text
    entry = response.json()["batches"][0]
    load_id = entry["load_id"]
    cleanup.append(load_id)
    assert entry["status"] == "RUNNING", entry

    review = wait_for(engineer, load_id)
    assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"]
    assert review["batch"]["plant_code"] == "AAT"
    assert review["batch"]["counts"]["rows_loaded"] == 1

    after = audit_upload(admin_conn, load_id)
    assert after["plant_column_present"] is False
    # No cell was filled because there are no plant cells at all; the column
    # itself was supplied by the profile, which the audit event says.
    assert after["plant_cells_filled"] == 0
    assert after["plant_supplied_by_profile"] is True

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT canonical ->> 'plant' FROM stg_review_row "
            "WHERE load_id = %s AND disposition = 'LOAD'",
            (load_id,),
        )
        assert [r[0] for r in cur.fetchall()] == ["AAT"]
