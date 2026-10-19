"""T19 -- the plant Data Manager: reads, and the warning acknowledgement.

Four claims, and only the first can be made without a database:

* **The operational summary is a workflow label.** A pure function over
  statuses, tested as one, so nobody has to run PostgreSQL to find out that a
  half-committed workbook does not read as finished.
* **A reviewer can see raw against canonical without opening Excel.** Proven
  by asking the running application for rows and checking that what comes
  back is what `stg_review_row` and `wavescan` hold -- and, for the rows of a
  **superseded** batch, that they are still here while being absent from
  `GET /measurements`, which is a different question with a different answer.
* **A warning is acknowledged or the commit waits.** Proven by being refused,
  acknowledging, and being allowed -- and by a real replay, through an
  approved model alias, moving the review revision and making the earlier
  acknowledgement stop counting without deleting it.
* **The reads are Engineer, the acknowledgement Admin** (RO12). Proven
  against the running application for every path, for an Engineer, a Viewer
  and an anonymous caller.

They run through T04's fixtures, against the same application, worker and
database. A second worker would race the first for jobs and prove nothing.
"""

from __future__ import annotations

from tests.conftest import delete_rows_created_since, row_keys
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg import errors as pgerr

from app.domain.workbooks import operational_summary, ranges_overlap
from tests.test_t04_ingest import (
    BASE_ROW,
    acknowledge,
    forget_bytes,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)

# Imported for their side effect: a fixture is in scope where its function is
# in the module namespace (same reasoning as T08, T17 and T18).
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)

pytestmark = pytest.mark.ingest

#: A hash that is 64 valid hex characters and belongs to nothing.
ABSENT_HASH = "0" * 64


# =====================================================================
# fixtures and helpers
# =====================================================================
@pytest.fixture(scope="module")
def anon(ingest_apps) -> TestClient:
    """A caller with no identity at all, and no worker."""
    return ingest_apps(auth_dev_bypass=False, ingest_worker_enabled=False)


@pytest.fixture()
def alias_cleanup(admin_conn):
    """Remove model aliases a test approved.

    The application holds INSERT and deliberately no DELETE on
    `ref_model_alias` (T08), which is the property being protected -- so the
    cleanup runs as the owner, on a throwaway database.
    """
    # T76 CHANGE: only aliases created during the test.
    before = row_keys(admin_conn, "ref_model_alias", "alias_id")
    models: list[str] = []
    yield models
    if models:
        delete_rows_created_since(
            admin_conn, "ref_model_alias", "alias_id", before,
            "raw_value = ANY(%s)", (models,),
        )


def ingest_as(client, cleanup, name: str, data: bytes, plant: str = "AAT") -> dict:
    """Upload one workbook for one plant and wait for its single sheet."""
    response = upload(client, name, data, expected_plant=plant)
    assert response.status_code == 202, response.text
    load_id = response.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    return wait_for(client, load_id)


def base(plant: str) -> str:
    return f"/api/v1/plants/{plant}/workbooks"


def manager_paths(plant: str, file_hash: str) -> list[str]:
    """Every read this task adds, for the RBAC sweep."""
    root = base(plant)
    return [
        root,
        f"{root}/{file_hash}",
        f"{root}/{file_hash}/rows",
        f"{root}/{file_hash}/issues",
        f"{root}/{file_hash}/history",
    ]


def workbooks(client, plant: str, **params) -> dict:
    response = client.get(base(plant), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def card(client, plant: str, file_hash: str) -> dict:
    """One workbook from the list, so grouping is exercised, not bypassed."""
    body = workbooks(client, plant, limit=200)
    found = [w for w in body["items"] if w["file_hash"] == file_hash]
    assert len(found) == 1, f"{file_hash} appears {len(found)} times in the list"
    return found[0]


def detail(client, plant: str, file_hash: str) -> dict:
    response = client.get(f"{base(plant)}/{file_hash}")
    assert response.status_code == 200, response.text
    return response.json()


def rows_of(client, plant: str, file_hash: str, **params) -> dict:
    response = client.get(f"{base(plant)}/{file_hash}/rows", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def issues_of(client, plant: str, file_hash: str) -> list[dict]:
    response = client.get(f"{base(plant)}/{file_hash}/issues")
    assert response.status_code == 200, response.text
    return response.json()["issues"]


def history_of(client, plant: str, file_hash: str) -> list[dict]:
    response = client.get(f"{base(plant)}/{file_hash}/history")
    assert response.status_code == 200, response.text
    return response.json()["events"]


def tokens(issues: list[dict], level: str) -> set[str]:
    return {i["token"] for i in issues if i["level"] == level}


def facts(admin_conn, load_id: int) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        return cur.fetchone()[0]


def mixed_workbook(serial: str | None = None) -> bytes:
    """One sheet carrying all four dispositions.

    Built explicitly rather than from `unique_rows`, because the point is the
    four outcomes: two identical rows (the second is a duplicate of the
    first), one colour no alias knows (a reject), and one model cell that
    says the field was left blank (a quarantine -- `(none)` does not name a
    truck, so no alias may rescue it).
    """
    serial = serial or f"T19-{uuid.uuid4().hex[:10]}"
    row = {**BASE_ROW, "Serial No": serial}
    return make_workbook([
        {**row, "Checkzone": "01 RRHOOD"},
        {**row, "Checkzone": "01 RRHOOD"},
        {**row, "Checkzone": "02 RFHOOD", "Color": "Fictional Purple"},
        {**row, "Checkzone": "03 CFHOOD", "Model": "(none)"},
    ])


def owner_batch(admin_conn, cleanup, *, plant: str, status: str) -> tuple[int, str]:
    """A `load_batch` row created by the OWNER, in a state a test needs.

    Used only for `RUNNING`: catching the real worker mid-parse is a race,
    and what the Files list has to prove about a parsing workbook is that it
    has **no dates** and reads as `PROCESSING` -- which is a property of a
    batch with no projection and no facts, however it got there. Nothing
    about the ingest path is bypassed for any other state.
    """
    file_hash = uuid.uuid4().hex + uuid.uuid4().hex
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO load_batch
                (source_file, source_sheet, plant_code, file_hash,
                 raw_store_key, status, rows_in_file)
            VALUES ('t19-processing.xlsx', 'PasteData', %s, %s, %s, %s, 0)
            RETURNING load_id
            """,
            (plant, file_hash, f"t19/{file_hash}", status),
        )
        load_id = cur.fetchone()[0]
    cleanup.append(load_id)
    return load_id, file_hash


# =====================================================================
# 1. the summary is a workflow label, not a grade (pure)
# =====================================================================
@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["PENDING_REVIEW"], "REVIEW_REQUIRED"),
        (["PENDING_REVIEW", "REJECTED_TEMPLATE"], "REVIEW_REQUIRED"),
        (["FAILED"], "REVIEW_REQUIRED"),
        (["COMMITTED", "COMMITTED"], "ACTIVE"),
        (["COMMITTED", "PENDING_REVIEW"], "PARTIALLY_COMMITTED"),
        (["RUNNING", "COMMITTED"], "PROCESSING"),
        (["SUPERSEDED", "SUPERSEDED"], "SUPERSEDED"),
        # One live sheet is enough to stop a workbook reading as retired.
        (["SUPERSEDED", "COMMITTED"], "ACTIVE"),
        (["SUPERSEDED", "PENDING_REVIEW"], "REVIEW_REQUIRED"),
    ],
)
def test_the_operational_summary_is_deterministic_from_statuses(statuses, expected):
    assert operational_summary(statuses) == expected


def test_an_unknown_date_range_does_not_overlap_everything():
    """A workbook still parsing has no dates. Treating that as "overlaps"
    would raise a possible-replacement warning against every file at the
    plant, which is worse than silence."""
    from datetime import date

    assert ranges_overlap(date(2026, 6, 1), date(2026, 6, 30),
                          date(2026, 6, 30), date(2026, 7, 5)) is True
    assert ranges_overlap(date(2026, 6, 1), date(2026, 6, 30),
                          date(2026, 7, 1), date(2026, 7, 5)) is False
    assert ranges_overlap(None, None, date(2026, 6, 1), date(2026, 6, 2)) is False


# =====================================================================
# 2. the file list
# =====================================================================
def test_two_sheets_of_one_upload_are_one_workbook(engineer, admin, cleanup):
    """Identity is the bytes, not the sheet and not the filename."""
    data = make_workbook(
        [],
        sheets={"PasteData": unique_rows(3), "Sheet2": unique_rows(2)},
    )
    response = upload(engineer, "t19-two-sheets.xlsx", data, expected_plant="AAT")
    assert response.status_code == 202, response.text
    entries = response.json()["batches"]
    assert len(entries) == 2, "one batch per sheet"
    reviews = []
    for entry in entries:
        cleanup.append(entry["load_id"])
        reviews.append(wait_for(engineer, entry["load_id"]))

    hashes = {r["batch"]["file_hash"] for r in reviews}
    assert len(hashes) == 1, "two sheets of one file share its bytes"
    item = card(admin, "AAT", hashes.pop())

    assert item["sheet_count"] == 2
    assert {s["batch"]["source_sheet"] for s in item["sheets"]} == {
        "PasteData", "Sheet2"
    }
    assert item["counts"]["rows_in_file"] == 5, "sheet counts are summed"
    assert item["counts"]["rows_loaded"] == 5
    assert item["operational_summary"] == "REVIEW_REQUIRED"
    assert item["superseded"] is False


def test_the_dates_are_measured_dates_not_upload_dates(engineer, admin, cleanup):
    """T19 locked decision 3. A June file uploaded in September is a June
    file, so the range comes from the rows and never from `started_at`."""
    rows = unique_rows(3)
    rows[0]["Date"] = "2026-06-02"
    rows[1]["Date"] = "2026-06-11"
    rows[2]["Date"] = "2026-06-27"
    review = ingest_as(engineer, cleanup, "t19-dates.xlsx", make_workbook(rows))
    item = card(admin, "AAT", review["batch"]["file_hash"])

    assert item["measured_date_min"] == "2026-06-02"
    assert item["measured_date_max"] == "2026-06-27"
    assert not item["uploaded_at"].startswith("2026-06-02"), (
        "the upload time is a different field and must stay one"
    )


def test_a_workbook_with_no_parse_yet_has_no_dates_and_reads_as_processing(
    admin, admin_conn, cleanup
):
    load_id, file_hash = owner_batch(admin_conn, cleanup, plant="AAT", status="RUNNING")
    item = card(admin, "AAT", file_hash)

    assert item["operational_summary"] == "PROCESSING"
    assert item["measured_date_min"] is None
    assert item["measured_date_max"] is None
    assert [s["batch"]["load_id"] for s in item["sheets"]] == [load_id]


def test_a_known_but_un_onboarded_plant_lists_nothing_rather_than_refusing(
    admin, admin_conn
):
    """D5 stays open and FVL stays visible. The upload route answers 422 for
    this plant; the Data Manager answers an empty page and says why, because
    hiding the plant is how "four plants supported" becomes untrue."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT plant_code FROM ref_plant WHERE NOT is_active LIMIT 1")
        row = cur.fetchone()
    if row is None:
        pytest.skip("no inactive plant in ref_plant to exercise this")

    body = workbooks(admin, row[0])
    assert body["plant_is_active"] is False
    assert body["items"] == []
    assert body["page"]["total"] == 0


def test_an_unknown_plant_is_a_404(admin):
    assert admin.get(base("NOWHERE")).status_code == 404


def test_a_plant_alias_and_a_lower_case_code_are_the_same_plant(admin, admin_conn):
    """`/plants/ftm` and `/plants/FTM` are one plant, resolved through the
    same alias table a Plant cell is resolved through."""
    lower = workbooks(admin, "aat", limit=1)
    assert lower["plant_code"] == "AAT"

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT raw_value FROM ref_plant_alias WHERE plant_code = 'AAT' LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        pytest.skip("no ref_plant_alias row for AAT")
    assert workbooks(admin, row[0], limit=1)["plant_code"] == "AAT"


def test_a_workbook_filed_under_another_plant_is_not_reachable_here(
    engineer, admin, cleanup
):
    """Cross-plant is a 404, not a redirect: one plant's file list must not
    leak through another plant's URL one hash at a time."""
    rows = [{**r, "Plant": "FTM"} for r in unique_rows(2)]
    review = ingest_as(engineer, cleanup, "t19-ftm.xlsx", make_workbook(rows), "FTM")
    file_hash = review["batch"]["file_hash"]

    assert card(admin, "FTM", file_hash)["plant_code"] == "FTM"
    assert admin.get(f"{base('AAT')}/{file_hash}").status_code == 404
    assert admin.get(f"{base('AAT')}/{file_hash}/rows").status_code == 404
    assert file_hash not in {
        w["file_hash"] for w in workbooks(admin, "AAT", limit=200)["items"]
    }


def test_an_absent_hash_is_a_404(admin):
    assert admin.get(f"{base('AAT')}/{ABSENT_HASH}").status_code == 404


# =====================================================================
# 3. summaries against the running system
# =====================================================================
def test_committing_one_of_two_sheets_is_partially_committed_then_active(
    engineer, admin, cleanup
):
    data = make_workbook(
        [],
        sheets={"PasteData": unique_rows(2), "Sheet2": unique_rows(2)},
    )
    response = upload(engineer, "t19-partial.xlsx", data, expected_plant="AAT")
    entries = response.json()["batches"]
    for entry in entries:
        cleanup.append(entry["load_id"])
    first = wait_for(engineer, entries[0]["load_id"])
    wait_for(engineer, entries[1]["load_id"])
    file_hash = first["batch"]["file_hash"]

    assert card(admin, "AAT", file_hash)["operational_summary"] == "REVIEW_REQUIRED"

    assert engineer.post(
        f"/api/v1/batches/{entries[0]['load_id']}/commit"
    ).status_code == 200
    assert card(admin, "AAT", file_hash)["operational_summary"] == "PARTIALLY_COMMITTED"

    assert engineer.post(
        f"/api/v1/batches/{entries[1]['load_id']}/commit"
    ).status_code == 200
    item = card(admin, "AAT", file_hash)
    assert item["operational_summary"] == "ACTIVE"
    assert item["superseded"] is False


def test_a_superseded_workbook_stays_listed_and_is_marked(engineer, admin, cleanup):
    review = ingest_as(engineer, cleanup, "t19-supersede.xlsx", make_workbook(unique_rows(2)))
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200

    retired = admin.post(
        f"/api/v1/batches/{load_id}/supersede",
        json={"reason": "T19: re-sent by the plant with corrected serials."},
    )
    assert retired.status_code == 200, retired.text

    item = card(admin, "AAT", file_hash)
    assert item["operational_summary"] == "SUPERSEDED"
    assert item["superseded"] is True
    assert item["sheets"][0]["batch"]["status"] == "SUPERSEDED"


# =====================================================================
# 4. the reads are Engineer, the acknowledgement Admin
# =====================================================================
@pytest.mark.parametrize("role", ["engineer", "viewer"])
def test_the_manager_reads_are_engineer_and_the_acknowledgement_admin(
    request, engineer, admin, viewer, cleanup, role
):
    """RO12 CHANGE (owner, 2026-10-13): the reads were Admin-only (design
    M15); an Engineer now reads the files they send. A Viewer is still refused
    every path, and the acknowledgement stays Admin for both. Chrome is not
    security: this is the server answering."""
    review = ingest_as(engineer, cleanup, "t19-rbac.xlsx", make_workbook(unique_rows(2)))
    file_hash = review["batch"]["file_hash"]
    caller = request.getfixturevalue(role)

    for path in manager_paths("AAT", file_hash):
        # RO12 CHANGE: Engineer 403 -> 200; Viewer stays 403.
        expected = 200 if role == "engineer" else 403
        assert caller.get(path).status_code == expected, path
    assert caller.post(
        f"{base('AAT')}/{file_hash}/acknowledgements",
        json={
            "load_id": review["batch"]["load_id"],
            "category": "DUPLICATE_ROWS",
            "review_revision": review["batch"]["review_revision"],
        },
    ).status_code == 403

    for path in manager_paths("AAT", file_hash):
        assert admin.get(path).status_code == 200, path


def test_an_unauthenticated_caller_is_refused_every_manager_route(anon):
    for path in manager_paths("AAT", ABSENT_HASH):
        assert anon.get(path).status_code == 401, path
    assert anon.post(
        f"{base('AAT')}/{ABSENT_HASH}/acknowledgements", json={}
    ).status_code == 401


def test_the_upload_and_commit_roles_are_unchanged(engineer, cleanup):
    """T19 adds Admin routes; it does not take anything away from an
    Engineer. If this fails, T04 and T08 have stopped meaning what they
    meant."""
    review = ingest_as(engineer, cleanup, "t19-roles.xlsx", make_workbook(unique_rows(2)))
    assert engineer.post(
        f"/api/v1/batches/{review['batch']['load_id']}/commit"
    ).status_code == 200


# =====================================================================
# 5. rows
# =====================================================================
def test_every_disposition_is_readable_without_opening_the_workbook(
    engineer, admin, cleanup, admin_conn
):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t19-mixed.xlsx", data)
    batch = review["batch"]
    file_hash = batch["file_hash"]
    assert batch["counts"] == {
        "rows_in_file": 4, "rows_loaded": 1, "rows_duplicate": 1,
        "rows_rejected": 1, "rows_quarantine": 1, "balanced": True,
    }

    page = rows_of(admin, "AAT", file_hash, limit=100)
    assert page["page"]["total"] == 4
    assert [r["source_row"] for r in page["items"]] == [2, 3, 4, 5]
    assert {r["disposition"] for r in page["items"]} == {
        "LOAD", "DUPLICATE", "REJECT", "QUARANTINE"
    }

    loaded = [r for r in page["items"] if r["disposition"] == "LOAD"][0]
    assert loaded["canonical"]["plant"] == "AAT"
    assert loaded["raw"]["values"]["color"] == "3HC Traction Green"
    assert loaded["measurement_id"] is None, "nothing is committed yet"
    assert loaded["projection_missing"] is False

    rejected = [r for r in page["items"] if r["disposition"] == "REJECT"][0]
    assert rejected["reason"] == "UNKNOWN_COLOR"
    assert rejected["canonical"]["offending_value"] == "Fictional Purple"

    for disposition in ("LOAD", "DUPLICATE", "REJECT", "QUARANTINE"):
        filtered = rows_of(admin, "AAT", file_hash, disposition=disposition)
        assert filtered["page"]["total"] == 1, disposition
        assert filtered["items"][0]["disposition"] == disposition


def test_rows_paginate_stably(engineer, admin, cleanup):
    review = ingest_as(engineer, cleanup, "t19-paging.xlsx", make_workbook(unique_rows(5)))
    file_hash = review["batch"]["file_hash"]

    first = rows_of(admin, "AAT", file_hash, limit=2, offset=0)["items"]
    second = rows_of(admin, "AAT", file_hash, limit=2, offset=2)["items"]
    third = rows_of(admin, "AAT", file_hash, limit=2, offset=4)["items"]
    seen = [r["source_row"] for r in first + second + third]
    assert seen == sorted(seen) and len(set(seen)) == 5


def test_a_load_id_that_is_not_a_sheet_of_this_workbook_is_404(
    engineer, admin, cleanup
):
    mine = ingest_as(engineer, cleanup, "t19-child-a.xlsx", make_workbook(unique_rows(2)))
    other = ingest_as(engineer, cleanup, "t19-child-b.xlsx", make_workbook(unique_rows(2)))
    response = admin.get(
        f"{base('AAT')}/{mine['batch']['file_hash']}/rows",
        params={"load_id": other["batch"]["load_id"]},
    )
    assert response.status_code == 404, response.text


def test_a_superseded_batch_keeps_its_rows_here_and_loses_them_in_measurements(
    engineer, admin, cleanup
):
    """T19 locked decision 8, stated as two reads of the same facts.

    `GET /measurements` answers what is **current**, through
    `v_wavescan_active`, so a retired batch contributes nothing. The workbook
    drill-down answers what this **file** contains, which is why somebody
    opens it after a supersede.
    """
    review = ingest_as(engineer, cleanup, "t19-retired.xlsx", make_workbook(unique_rows(3)))
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200

    active = engineer.get("/api/v1/measurements", params={"load_id": load_id}).json()
    assert active["page"]["total"] == 3
    assert active["filters"]["load_id"] == load_id

    committed = rows_of(admin, "AAT", file_hash, disposition="LOAD")["items"]
    assert all(r["measurement_id"] is not None for r in committed)

    assert admin.post(
        f"/api/v1/batches/{load_id}/supersede",
        json={"reason": "T19: retired so the drill-down can be checked."},
    ).status_code == 200

    after = engineer.get("/api/v1/measurements", params={"load_id": load_id}).json()
    assert after["page"]["total"] == 0, "a retired batch is not current"

    still_here = rows_of(admin, "AAT", file_hash, disposition="LOAD")["items"]
    assert len(still_here) == 3
    assert [r["measurement_id"] for r in still_here] == [
        r["measurement_id"] for r in committed
    ], "the file still contains exactly the rows it always contained"


# =====================================================================
# 6. information: a plant filled from the declared plant
# =====================================================================
def test_a_sheet_without_a_plant_column_reports_plant_filled_and_still_commits(
    engineer, admin, cleanup, admin_conn
):
    """T17's fill, T18's profile, T19's disclosure.

    The fill is **information**, not a warning: it was declared at upload and
    a profile says this layout is known to omit the column. So the sheet has
    nothing to acknowledge and commits without one -- which is the half of
    the gate that would otherwise be untested.
    """
    from tests.test_t18_profiles import workbook

    data = workbook(unique_rows(3), drop=("Plant",))
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t19-no-plant-col.xlsx", data)
    batch = review["batch"]
    assert batch["status"] == "PENDING_REVIEW", batch

    found = issues_of(admin, "AAT", batch["file_hash"])
    assert "PLANT_FILLED" in tokens(found, "INFORMATION")
    assert "PROFILE_APPLIED" in tokens(found, "INFORMATION")
    plant_filled = [i for i in found if i["token"] == "PLANT_FILLED"][0]
    assert plant_filled["count"] == 3
    assert plant_filled["resolution"] is None, "information needs no action"

    assert review["committable"] is True
    assert review["commit_blockers"] == []
    assert engineer.post(
        f"/api/v1/batches/{batch['load_id']}/commit"
    ).status_code == 200

    row = rows_of(admin, "AAT", batch["file_hash"], disposition="LOAD")["items"][0]
    assert row["normalized_fields"] == ["plant"]
    assert row["canonical"]["plant"] == "AAT"


# =====================================================================
# 7. issues
# =====================================================================
def test_issues_carry_three_levels_and_no_grade(engineer, admin, cleanup, admin_conn):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t19-issues.xlsx", data)
    file_hash = review["batch"]["file_hash"]
    found = issues_of(admin, "AAT", file_hash)

    assert tokens(found, "WARNING") >= {
        "REJECTED_ROWS", "QUARANTINED_MODELS", "DUPLICATE_ROWS",
    }
    assert "WARNINGS_UNACKNOWLEDGED" in tokens(found, "BLOCKER")
    assert "PROFILE_APPLIED" in tokens(found, "INFORMATION")

    rejected = [i for i in found if i["token"] == "REJECTED_ROWS"][0]
    assert rejected["count"] == 1
    assert rejected["acked"] is False
    assert rejected["resolution"] == "acknowledge"
    assert rejected["sample_rows"][0]["reason"] == "UNKNOWN_COLOR"
    assert rejected["sample_rows"][0]["source_sheet"] == "PasteData"

    # No grade, no pass rate, no band -- D1 is open and this is a workflow
    # view, not a quality one.
    serialised = str(found).lower()
    for forbidden in ("pass_rate", "grade", "ford", "status_of"):
        assert forbidden not in serialised


def test_possible_replacement_is_a_warning_and_never_a_commit_blocker(
    engineer, admin, cleanup, admin_conn
):
    """Design M14. Two workbooks whose measured dates overlap: the newer one
    gets a hint that it may replace the older, and nothing is retired."""
    rows = unique_rows(2)
    for row in rows:
        row["Date"] = "2026-06-15"
    older = make_workbook(rows)
    forget_bytes(admin_conn, older)
    first = ingest_as(engineer, cleanup, "t19-replace-old.xlsx", older)
    assert engineer.post(
        f"/api/v1/batches/{first['batch']['load_id']}/commit"
    ).status_code == 200

    newer_rows = unique_rows(2)
    for row in newer_rows:
        row["Date"] = "2026-06-15"
    newer = make_workbook(newer_rows)
    forget_bytes(admin_conn, newer)
    second = ingest_as(engineer, cleanup, "t19-replace-new.xlsx", newer)
    file_hash = second["batch"]["file_hash"]

    hints = detail(admin, "AAT", file_hash)["possible_replacements"]
    assert first["batch"]["file_hash"] in {h["file_hash"] for h in hints}

    found = issues_of(admin, "AAT", file_hash)
    replacement = [i for i in found if i["token"] == "POSSIBLE_REPLACEMENT"]
    assert len(replacement) == 1
    assert replacement[0]["level"] == "WARNING"
    assert replacement[0]["load_id"] is None, "it is a statement about the file"
    assert replacement[0]["resolution"] == "supersede_separate"

    # It blocks nothing, and it retires nothing.
    assert second["committable"] is True
    assert "POSSIBLE_REPLACEMENT" not in second["commit_blockers"]
    assert card(admin, "AAT", first["batch"]["file_hash"])["superseded"] is False


# =====================================================================
# 8. the acknowledgement
# =====================================================================
def test_a_rejected_category_needs_a_note(engineer, admin, cleanup, admin_conn):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t19-note.xlsx", data)
    batch = review["batch"]

    blank = admin.post(
        f"{base('AAT')}/{batch['file_hash']}/acknowledgements",
        json={
            "load_id": batch["load_id"],
            "category": "REJECTED_ROWS",
            "review_revision": batch["review_revision"],
            "note": "   ",
        },
    )
    assert blank.status_code == 422, blank.text

    # A duplicate needs none: the row it matched already describes it.
    assert admin.post(
        f"{base('AAT')}/{batch['file_hash']}/acknowledgements",
        json={
            "load_id": batch["load_id"],
            "category": "DUPLICATE_ROWS",
            "review_revision": batch["review_revision"],
        },
    ).status_code == 201

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM review_acknowledgement WHERE load_id = %s",
            (batch["load_id"],),
        )
        assert cur.fetchone()[0] == 1, "the blank note wrote nothing"


def test_a_stale_review_revision_is_refused_and_writes_nothing(
    engineer, admin, cleanup, admin_conn
):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t19-stale.xlsx", data)
    batch = review["batch"]

    stale = admin.post(
        f"{base('AAT')}/{batch['file_hash']}/acknowledgements",
        json={
            "load_id": batch["load_id"],
            "category": "REJECTED_ROWS",
            "review_revision": "a" * 64,
            "note": "read them",
        },
    )
    assert stale.status_code == 409, stale.text
    assert batch["review_revision"][:12] in stale.json()["message"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM review_acknowledgement WHERE load_id = %s",
            (batch["load_id"],),
        )
        assert cur.fetchone()[0] == 0


def test_a_replay_invalidates_an_acknowledgement_without_deleting_it(
    engineer, admin, cleanup, alias_cleanup, admin_conn
):
    """The gate is about rows, not about a file.

    Two rows carry model spellings no alias knows, so both are rejected and
    the sheet needs `REJECTED_ROWS` acknowledged. It is acknowledged. Then an
    Admin approves an alias for **one** of the two spellings, which replays
    the stored bytes: the same workbook now means something different, the
    review revision moves, and the earlier acknowledgement -- still in the
    table, still readable -- stops satisfying the gate.
    """
    first_model = f"P703 RAP {uuid.uuid4().hex[:6]}"
    second_model = f"P703 SVO {uuid.uuid4().hex[:6]}"
    alias_cleanup.extend([first_model, second_model])

    rows = unique_rows(4)
    rows[0]["Model"] = first_model
    rows[1]["Model"] = second_model
    review = ingest_as(engineer, cleanup, "t19-replay.xlsx", make_workbook(rows))
    batch = review["batch"]
    load_id = batch["load_id"]
    assert batch["counts"]["rows_rejected"] == 2
    assert "WARNINGS_UNACKNOWLEDGED" in review["commit_blockers"]

    assert acknowledge(admin, review, "REJECTED_ROWS").status_code == 201
    accepted = engineer.get(f"/api/v1/batches/{load_id}").json()
    assert "WARNINGS_UNACKNOWLEDGED" not in accepted["commit_blockers"]

    proposal = engineer.post(
        "/api/v1/mappings/proposals",
        json={
            "kind": "ALIAS_MODEL",
            "load_id": load_id,
            "payload": {"raw_value": first_model, "model_code": "U704"},
        },
    )
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["status"] == "APPROVED"

    replayed = wait_for(engineer, load_id)
    assert replayed["batch"]["counts"]["rows_rejected"] == 1, "one spelling is still unknown"
    assert replayed["batch"]["review_revision"] != batch["review_revision"]
    assert "WARNINGS_UNACKNOWLEDGED" in replayed["commit_blockers"], (
        "an acknowledgement of the previous proposal does not carry over"
    )

    # The old record is still there. A replay does not tidy away the fact
    # that somebody read the earlier rows.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT review_revision FROM review_acknowledgement WHERE load_id = %s",
            (load_id,),
        )
        assert [r[0].strip() for r in cur.fetchall()] == [batch["review_revision"]]

    assert acknowledge(admin, replayed, "REJECTED_ROWS").status_code == 201
    cleared = engineer.get(f"/api/v1/batches/{load_id}").json()
    assert cleared["commit_blockers"] == []
    assert cleared["committable"] is True


def test_the_application_role_cannot_update_or_delete_an_acknowledgement(app_conn):
    """Append-only is a grant, not a convention (revision 0007)."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("UPDATE review_acknowledgement SET note = 'rewritten'")
    app_conn.rollback()
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("DELETE FROM review_acknowledgement")


def test_commit_after_acknowledgement_writes_only_the_load_rows(
    engineer, admin, cleanup, admin_conn
):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t19-gate.xlsx", data)
    batch = review["batch"]
    load_id = batch["load_id"]

    refused = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert refused.status_code == 409, refused.text
    assert "WARNINGS_UNACKNOWLEDGED" in refused.json()["message"]
    assert facts(admin_conn, load_id) == 0

    for category in ("REJECTED_ROWS", "QUARANTINED_MODELS", "DUPLICATE_ROWS"):
        assert acknowledge(admin, review, category).status_code == 201

    ready = engineer.get(f"/api/v1/batches/{load_id}").json()
    assert ready["committable"] is True
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200

    assert facts(admin_conn, load_id) == 1, "only the LOAD row became a measurement"
    sheet = card(admin, "AAT", batch["file_hash"])["sheets"][0]
    assert sorted(sheet["acknowledged"]) == [
        "DUPLICATE_ROWS", "QUARANTINED_MODELS", "REJECTED_ROWS",
    ]


def test_an_acknowledgement_names_a_person_and_is_shown_on_the_workbook(
    engineer, admin, cleanup, admin_conn
):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t19-ack-detail.xlsx", data)
    batch = review["batch"]

    created = acknowledge(admin, review, "REJECTED_ROWS", note="Plant confirmed a re-test.")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["actor_user_id"], "an acknowledgement nobody can name is not one"
    assert body["review_revision"] == batch["review_revision"]
    assert body["note"] == "Plant confirmed a re-test."

    shown = detail(admin, "AAT", batch["file_hash"])["acknowledgements"]
    assert [a["ack_id"] for a in shown] == [body["ack_id"]]


# =====================================================================
# 9. history
# =====================================================================
def test_the_history_is_one_timeline_with_actors(
    engineer, admin, cleanup, admin_conn
):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t19-history.xlsx", data)
    batch = review["batch"]
    load_id = batch["load_id"]

    for category in ("REJECTED_ROWS", "QUARANTINED_MODELS", "DUPLICATE_ROWS"):
        assert acknowledge(admin, review, category).status_code == 201
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200

    events = history_of(admin, "AAT", batch["file_hash"])
    actions = [e["action"] for e in events]
    assert actions[0] == "batch.upload"
    assert actions[-1] == "batch.commit"
    assert actions.count("review.acknowledge") == 3
    assert all(e["actor_user_id"] for e in events), "every event names a person"

    acked = [e for e in events if e["action"] == "review.acknowledge"][0]
    assert acked["after"]["review_revision"] == batch["review_revision"]
    assert acked["entity_type"] == "load_batch"
    assert acked["entity_id"] == str(load_id)


# =====================================================================
# 10. the contract
# =====================================================================
def test_the_six_new_paths_are_published(admin):
    spec = admin.get("/openapi.json").json()
    # T21 CHANGE: 23 -> 27 (vehicles, points, overrides, abandon).
    # T23 CHANGE: 27 -> 31 (four History reads). The six T19 paths below are
    # unchanged by both.
    # T25 CHANGE: 31 -> 32 (POST /batches/{load_id}/restore).
    # T26 CHANGE: 32 -> 33 (POST /plants/{plant_code}/template-profiles/publish).
    # T-STANDARDS-D2 CHANGE: 33 -> 38 (catalogue GET + four POSTs; POST /standards existed).
    # Monthly Overview CHANGE: 38 -> 39.
    # T37 CHANGE: 39 -> 40 (POST /plants/{plant_code}/workbooks/{file_hash}/purge).
    # T39 CHANGE: 40 -> 46 (worksheet GET + five Engineer POSTs).
    # T48 CHANGE: 46 -> 49 (three FilmThickness GETs).
    # T62 CHANGE: 49 -> 51 (FilmThickness standards GET + Admin POST).
    # T66 CHANGE: 51 -> 52 (FilmThickness monthly overview GET).
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(spec["paths"]) >= 52, sorted(spec["paths"])
    root = "/api/v1/plants/{plant_code}/workbooks"
    assert set(spec["paths"]) >= {
        root,
        f"{root}/{{file_hash}}",
        f"{root}/{{file_hash}}/rows",
        f"{root}/{{file_hash}}/issues",
        f"{root}/{{file_hash}}/history",
        f"{root}/{{file_hash}}/acknowledgements",
    }
    acknowledgements = spec["paths"][f"{root}/{{file_hash}}/acknowledgements"]
    assert set(acknowledgements) == {"post"}, "the reads are separate paths"

    measurements = spec["paths"]["/api/v1/measurements"]["get"]
    assert "load_id" in {p["name"] for p in measurements["parameters"]}


def test_no_workbook_is_opened_by_a_read(admin, engineer, cleanup, admin_conn):
    """T19 locked decision 1, proven by taking the bytes away.

    Every read below is served from `load_batch`, `stg_review_row`,
    `wavescan`, `audit_event` and `ref_template_profile`. If any of them
    re-parsed the workbook, deleting the stored object would break it -- and
    `commit_batch`, which is allowed to re-derive, would still fail loudly,
    which is the difference.
    """
    review = ingest_as(engineer, cleanup, "t19-no-excel.xlsx", make_workbook(unique_rows(3)))
    batch = review["batch"]
    file_hash = batch["file_hash"]

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT raw_store_key FROM load_batch WHERE load_id = %s",
            (batch["load_id"],),
        )
        key = cur.fetchone()[0]
    stored = admin.app.state.ingest_service.store.path_for(key)
    moved = stored.with_suffix(stored.suffix + ".moved")
    stored.rename(moved)
    try:
        for path in manager_paths("AAT", file_hash):
            assert admin.get(path).status_code == 200, path
        assert engineer.get(f"/api/v1/batches/{batch['load_id']}").status_code == 200
    finally:
        moved.rename(stored)
