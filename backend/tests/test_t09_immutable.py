"""T09 — corrections and batch supersede, without mutating a fact.

`AGENTS.md` rule 7: *"No UPDATE of measurement values, no DELETE of batches
(ADR 0005). Supersede + correction rows + `audit_event`."* T02 built the
machinery; T09 calls it. So most of this file is about proving the calling did
not quietly become mutating:

* the original row's values are **byte-identical** after a correction, checked
  column by column against a snapshot taken before;
* `is_superseded` on the original went true, and the only thing that could
  have set it is the T02 trigger — the application role has no `UPDATE` on
  that table at all, which is asserted here as `app_rw`, not assumed;
* `wavescan` grows by exactly one row per correction and by zero rows per
  batch supersede;
* the count of rows a superseded batch owns is **unchanged** — they leave the
  active reads, not the table.

Plus the refusals, which is most of what these two routes do: a retired
measurement, a duplicate, an uncommitted batch, a replacement from another
plant, a Viewer, an Engineer reaching for an Admin route.

These tests need the live database for the same reason T01's do: several of
the guarantees are PostgreSQL privileges and triggers, and a mock cannot fail
to have a privilege.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from tests.test_t04_ingest import (
    ingest,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)

# Imported for their side effect: a fixture is in scope where its function is
# in the module namespace, so these are T04's fixtures rather than copies.
# One set of app clients means one worker, not several racing for jobs.
from tests.test_t04_ingest import (  # noqa: F401
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)
from tests.test_t08_mapping import admin  # noqa: F401

pytestmark = pytest.mark.ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

#: Every column whose value a correction must not disturb on the ORIGINAL row.
#: `is_superseded` is deliberately absent: it is the one column that changes,
#: and it is checked separately because the trigger is what changes it.
IMMUTABLE_ON_ORIGINAL = (
    "measured_date", "plant", "model", "checkzone", "color", "tolerance_group",
    "paintline", "serial_no",
    "lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b",
    "load_id", "source_sheet", "source_row", "is_duplicate", "loaded_at",
    "src_zone_text", "src_zone_no",
    "corrects_measurement_id", "correction_reason", "corrected_by", "corrected_at",
)

#: Fields a correction may not carry. `StrictModel` refuses them as unknown
#: keys, which is the mechanism; this is the list a reviewer checks against.
IDENTITY_FIELDS = (
    "plant", "model", "checkzone", "color", "tolerance_group", "paintline",
    "load_id", "source_sheet", "source_row",
)


# =====================================================================
# helpers
# =====================================================================
def snapshot(admin_conn, measurement_id: int) -> dict:
    """Every column of one measurement, read as the owner."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM wavescan WHERE measurement_id = %s", (measurement_id,)
        )
        row = cur.fetchone()
        assert row is not None, f"measurement {measurement_id} is not in wavescan"
        names = [c.name for c in cur.description]
    return dict(zip(names, row))


def total_rows(admin_conn) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan")
        return cur.fetchone()[0]


def rows_for_batch(admin_conn, load_id: int) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        return cur.fetchone()[0]


def batch_status(admin_conn, load_id: int) -> tuple[str, int | None]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT status, superseded_by FROM load_batch WHERE load_id = %s", (load_id,)
        )
        return cur.fetchone()


def correct(client, measurement_id: int, **body):
    return client.post(
        f"/api/v1/measurements/{measurement_id}/corrections", json=body
    )


def supersede(client, load_id: int, **body):
    return client.post(f"/api/v1/batches/{load_id}/supersede", json=body)


def committed_batch(client, cleanup, rows=None) -> dict:
    """Upload, wait, commit. Returns the review body plus the committed rows."""
    rows = rows if rows is not None else unique_rows(3)
    review = ingest(client, cleanup, f"t09-{uuid.uuid4().hex[:8]}.xlsx", make_workbook(rows))
    load_id = review["batch"]["load_id"]
    assert review["batch"]["status"] == "PENDING_REVIEW", review
    response = client.post(f"/api/v1/batches/{load_id}/commit")
    assert response.status_code == 200, response.text
    # RO03 CHANGE: narrowed to this batch (`load_id`, T19) as T76 did -- AAT
    # holds real readings now, so this batch need not be on the first page.
    page = client.get(
        "/api/v1/measurements", params={"limit": 500, "plant": "AAT", "load_id": load_id}
    ).json()
    assert page["page"]["total"] == len(rows), page["page"]
    mine = [m for m in page["items"] if m["load_id"] == load_id]
    assert len(mine) == len(rows), f"expected {len(rows)} committed rows, got {len(mine)}"
    return {"load_id": load_id, "items": mine}


@pytest.fixture()
def committed(engineer, cleanup):
    return committed_batch(engineer, cleanup)


# =====================================================================
# 1. RBAC — 03-SECURITY.md section 5
# =====================================================================
def test_a_viewer_can_neither_correct_nor_supersede(viewer, committed):
    """"Insert correction row: no" and "Supersede committed batch: no"."""
    target = committed["items"][0]["measurement_id"]
    assert correct(viewer, target, reason="x", cf="61").status_code == 403
    assert supersede(viewer, committed["load_id"], reason="x").status_code == 403


def test_an_engineer_corrects_but_cannot_supersede(engineer, committed, admin_conn):
    """The split the matrix draws. A correction is an Engineer's to make; a
    batch retirement is not."""
    target = committed["items"][0]["measurement_id"]
    assert correct(engineer, target, reason="engineer may", cf="61.5").status_code == 201

    response = supersede(engineer, committed["load_id"], reason="engineer may not")
    assert response.status_code == 403
    assert batch_status(admin_conn, committed["load_id"])[0] == "COMMITTED"


def test_an_admin_may_do_both(admin, cleanup, admin_conn):
    """ROLE_RANK is monotone, so an Admin can also do the Engineer's job."""
    batch = committed_batch(admin, cleanup)
    target = batch["items"][0]["measurement_id"]
    assert correct(admin, target, reason="admin outranks", cf="59").status_code == 201
    assert supersede(admin, batch["load_id"], reason="admin retires").status_code == 200


# =====================================================================
# 2. The correction does not mutate the original
# =====================================================================
def test_the_original_row_is_untouched_except_for_the_trigger_flag(
    engineer, committed, admin_conn
):
    """The central assertion of T09.

    Every column of the original is compared against a snapshot taken before
    the correction. The only difference permitted is `is_superseded`, and the
    only thing in the system that can set it is the T02 `AFTER INSERT` trigger
    on `measurement_supersession`.
    """
    original_id = committed["items"][0]["measurement_id"]
    before = snapshot(admin_conn, original_id)
    assert before["is_superseded"] is False
    rows_before = total_rows(admin_conn)

    response = correct(
        engineer, original_id,
        reason="CF transposed at entry; tape reads 62.4",
        cf="62.4",
    )
    assert response.status_code == 201, response.text

    after = snapshot(admin_conn, original_id)
    differing = {k for k in IMMUTABLE_ON_ORIGINAL if before[k] != after[k]}
    assert differing == set(), f"a correction changed the original: {differing}"
    assert after["is_superseded"] is True, "the supersession trigger did not fire"
    assert total_rows(admin_conn) == rows_before + 1, "wavescan did not grow by one"


def test_the_correction_row_carries_the_new_value_and_the_old_identity(
    engineer, committed, admin_conn
):
    """Identity is copied by the database from the original, not re-sent."""
    original = committed["items"][0]
    original_id = original["measurement_id"]
    before = snapshot(admin_conn, original_id)

    body = {"reason": "re-measured after booth recalibration", "cf": "58.25", "b": "-0.75"}
    response = correct(engineer, original_id, **body)
    assert response.status_code == 201, response.text
    new = response.json()["measurement"]

    assert new["measurement_id"] != original_id
    assert new["corrects_measurement_id"] == original_id
    assert new["correction_reason"] == body["reason"]
    assert Decimal(new["cf"]) == Decimal("58.25")
    assert Decimal(new["b"]) == Decimal("-0.75")

    # Identity and provenance, copied.
    for field in ("plant", "model", "checkzone", "color", "tolerance_group",
                  "paintline", "load_id", "source_sheet", "source_row"):
        assert new[field] == original[field], field
    # Untouched measures, copied.
    for field in ("lw", "sw", "doi", "du", "wa", "wb", "wc", "wd", "we"):
        assert Decimal(new[field]) == before[field], field

    row = snapshot(admin_conn, new["measurement_id"])
    assert row["corrected_by"] is not None, "the correction names no person"
    assert row["corrected_at"] is not None
    assert row["is_superseded"] is False


def test_a_correction_is_attributed_and_audited_in_one_transaction(
    engineer, committed, admin_conn
):
    """`AGENTS.md` §2. The supersession record carries the reason and actor;
    the audit event carries the same in the same transaction."""
    original_id = committed["items"][0]["measurement_id"]
    reason = f"audited correction {uuid.uuid4().hex[:6]}"
    response = correct(engineer, original_id, reason=reason, doi="88.5")
    assert response.status_code == 201, response.text
    body = response.json()

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT superseded_by_measurement_id, reason, actor_user_id IS NOT NULL "
            "FROM measurement_supersession WHERE superseded_measurement_id = %s",
            (original_id,),
        )
        supersession = cur.fetchone()
        cur.execute(
            "SELECT action, actor_user_id IS NOT NULL, after "
            "FROM audit_event WHERE entity_type = 'wavescan' AND entity_id = %s",
            (str(original_id),),
        )
        events = cur.fetchall()

    assert supersession[0] == body["measurement"]["measurement_id"]
    assert supersession[1] == reason
    assert supersession[2] is True, "the retirement names nobody"
    assert [e[0] for e in events] == ["measurement.correct"]
    assert events[0][1] is True
    assert events[0][2]["supersession_id"] == body["supersession_id"]


def test_the_list_swaps_the_original_for_the_correction(engineer, committed):
    """`GET /measurements` after a correction: same number of active rows for
    the batch, the original gone, the correction present."""
    load_id = committed["load_id"]
    original_id = committed["items"][0]["measurement_id"]
    before = {m["measurement_id"] for m in committed["items"]}

    new_id = correct(
        engineer, original_id, reason="swap check", cf="60.75"
    ).json()["measurement"]["measurement_id"]

    # RO03 CHANGE: narrowed to this batch (`load_id`, T19), as T76.
    page = engineer.get(
        "/api/v1/measurements", params={"limit": 500, "plant": "AAT", "load_id": load_id}
    ).json()
    assert page["page"]["total"] == len(before), page["page"]
    now = {m["measurement_id"] for m in page["items"] if m["load_id"] == load_id}

    assert original_id not in now, "a retired measurement is still being published"
    assert new_id in now
    assert len(now) == len(before), "the batch's active row count changed"


def test_an_exact_decimal_survives_the_correction(engineer, committed, admin_conn):
    """T04 stores CF unrounded and `AGENTS.md` §4 calls rounding it a defect.
    A decimal sent as a string must land in `wavescan` digit for digit."""
    original_id = committed["items"][0]["measurement_id"]
    precise = "62.123456789012345"
    new_id = correct(
        engineer, original_id, reason="precision check", cf=precise
    ).json()["measurement"]["measurement_id"]
    assert snapshot(admin_conn, new_id)["cf"] == Decimal(precise)


def test_b_can_be_cleared_but_only_when_it_is_sent(engineer, cleanup, admin_conn):
    """`b` is the one nullable measure, so "omitted" and "sent as null" have to
    mean different things -- otherwise no correction could ever leave it alone."""
    batch = committed_batch(engineer, cleanup, unique_rows(2))
    first, second = batch["items"][0], batch["items"][1]

    cleared = correct(engineer, first["measurement_id"], reason="b is not valid here", b=None)
    assert cleared.status_code == 201, cleared.text
    assert cleared.json()["measurement"]["b"] is None

    kept = correct(engineer, second["measurement_id"], reason="cf only", cf="60.1")
    assert kept.status_code == 201, kept.text
    assert kept.json()["measurement"]["b"] == second["b"]


# =====================================================================
# 3. A correction chain
# =====================================================================
def test_a_second_correction_targets_the_active_row(engineer, committed, admin_conn):
    """Corrections chain. Each one retires the row that was current, and the
    retired ones stay in `wavescan` with their original values."""
    original_id = committed["items"][0]["measurement_id"]
    rows_before = total_rows(admin_conn)

    first = correct(engineer, original_id, reason="first pass", cf="61")
    assert first.status_code == 201, first.text
    second_target = first.json()["measurement"]["measurement_id"]

    second = correct(engineer, second_target, reason="second pass", cf="62")
    assert second.status_code == 201, second.text
    final_id = second.json()["measurement"]["measurement_id"]

    assert total_rows(admin_conn) == rows_before + 2
    assert Decimal(snapshot(admin_conn, original_id)["cf"]) == Decimal(
        committed["items"][0]["cf"]
    )
    assert snapshot(admin_conn, second_target)["cf"] == Decimal("61")
    assert snapshot(admin_conn, final_id)["cf"] == Decimal("62")
    assert snapshot(admin_conn, final_id)["corrects_measurement_id"] == second_target

    active = engineer.get(f"/api/v1/measurements/{final_id}")
    assert active.status_code == 200
    assert engineer.get(f"/api/v1/measurements/{second_target}").status_code == 404


def test_correcting_an_already_retired_measurement_is_refused(engineer, committed):
    """`uq_supersession_once`: a retirement is recorded once. The message says
    what replaced it so the caller can aim at the right row."""
    original_id = committed["items"][0]["measurement_id"]
    replacement = correct(
        engineer, original_id, reason="first", cf="61"
    ).json()["measurement"]["measurement_id"]

    again = correct(engineer, original_id, reason="again", cf="63")
    assert again.status_code == 409, again.text
    message = again.json()["message"]
    assert "already retired" in message
    assert str(replacement) in message


# =====================================================================
# 4. GET one measurement
# =====================================================================
def test_one_active_measurement_can_be_read_back(engineer, committed):
    item = committed["items"][0]
    response = engineer.get(f"/api/v1/measurements/{item['measurement_id']}")
    assert response.status_code == 200, response.text
    assert response.json() == item


def test_a_measurement_that_never_existed_is_404(engineer):
    assert engineer.get("/api/v1/measurements/999999999").status_code == 404


def test_a_retired_measurement_is_404_not_a_leaked_original(engineer, committed):
    """The by-id read goes through the same view as the list, so it cannot
    publish a measurement the platform has set aside."""
    original_id = committed["items"][0]["measurement_id"]
    correct(engineer, original_id, reason="retire it", cf="60.5")
    assert engineer.get(f"/api/v1/measurements/{original_id}").status_code == 404


def test_list_filters_do_not_hide_an_active_row_by_id(engineer, committed):
    """Architect review: GET-by-id used to inherit the list's query string,
    so `?plant=FTM` 404'd an active AAT measurement. A by-id read is scoped
    by D3 only."""
    item = committed["items"][0]
    mid = item["measurement_id"]
    assert item["plant"] == "AAT"
    assert engineer.get(
        f"/api/v1/measurements/{mid}", params={"plant": "FTM", "model": "P703 DBL RANGER"}
    ).status_code == 200


def test_list_filters_do_not_refuse_a_correction_as_a_duplicate(engineer, committed):
    """Same leak on POST: `?plant=FTM` answered 409 claiming a duplicate.
    The correction must succeed; leftover dashboard filters are not a body."""
    target = committed["items"][0]["measurement_id"]
    response = engineer.post(
        f"/api/v1/measurements/{target}/corrections",
        params={"plant": "FTM"},
        json={"reason": "list filters are not a correction body", "cf": "60.25"},
    )
    assert response.status_code == 201, response.text


def test_a_measurement_from_an_uncommitted_batch_is_404(engineer, cleanup):
    """`PENDING_REVIEW` rows are not facts yet, so there is nothing to read or
    to correct."""
    review = ingest(engineer, cleanup, "t09-pending.xlsx", make_workbook(unique_rows(2)))
    assert review["batch"]["status"] == "PENDING_REVIEW"
    # Nothing is in wavescan at all before commit, so there is no id to ask
    # for -- which is itself the assertion.
    assert review["batch"]["counts"]["rows_loaded"] == 2
    # RO03 CHANGE: narrowed to this batch (`load_id`, T19), as T76, so the
    # check covers every row of the batch, not whatever is on page one.
    page = engineer.get(
        "/api/v1/measurements",
        params={"limit": 500, "plant": "AAT", "load_id": review["batch"]["load_id"]},
    ).json()
    assert page["page"]["total"] == 0, page["page"]
    assert not [m for m in page["items"] if m["load_id"] == review["batch"]["load_id"]]


# =====================================================================
# 5. The body is validated, not trusted
# =====================================================================
def test_an_identity_field_in_the_body_is_refused(engineer, committed):
    """A wrong plant or zone is a mapping or onboarding decision, not a
    correction. `StrictModel` makes sending one a 422."""
    target = committed["items"][0]["measurement_id"]
    for field, value in (
        ("plant", "FTM"), ("model", "P703 DBL RANGER"), ("checkzone", "RRHOOD"),
        ("color", "Arctic White"), ("tolerance_group", "Vertical"),
        ("paintline", "BOOTH2"), ("load_id", 1), ("source_sheet", "X"),
        ("source_row", 9),
    ):
        response = correct(engineer, target, reason="nope", **{field: value})
        assert response.status_code == 422, f"{field} was accepted: {response.text}"


def test_no_identity_field_is_even_a_field_of_the_dto():
    """The structural half of the test above."""
    from app.schemas.corrections import CorrectionCreate

    assert not set(IDENTITY_FIELDS) & set(CorrectionCreate.model_fields)


def test_an_unknown_key_is_refused(engineer, committed):
    target = committed["items"][0]["measurement_id"]
    assert correct(
        engineer, target, reason="x", cf="60", is_superseded=True
    ).status_code == 422


def test_a_reason_with_no_change_is_refused(engineer, committed):
    """A reason on its own records no correction, and writing one would add a
    duplicate row and an audit event for nothing."""
    target = committed["items"][0]["measurement_id"]
    response = correct(engineer, target, reason="I changed my mind about nothing")
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_reason_is_refused(engineer, admin, committed, blank):
    """"After trim" matters. `min_length` alone counts whitespace, so a reason
    of three spaces would otherwise pass the DTO and be refused by
    `ck_supersession_reason` three layers down -- a 409 from a constraint
    where the caller deserves a 422 naming the field."""
    target = committed["items"][0]["measurement_id"]
    assert correct(engineer, target, reason=blank, cf="60").status_code == 422
    assert supersede(admin, committed["load_id"], reason=blank).status_code == 422


def test_a_reason_is_stored_trimmed(engineer, committed, admin_conn):
    """It is read back by whoever audits the correction, so it is stored the
    way it will be read."""
    target = committed["items"][0]["measurement_id"]
    response = correct(engineer, target, reason="   padded reason   ", cf="60")
    assert response.status_code == 201, response.text
    assert response.json()["measurement"]["correction_reason"] == "padded reason"
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT reason FROM measurement_supersession "
            "WHERE superseded_measurement_id = %s",
            (target,),
        )
        assert cur.fetchone()[0] == "padded reason"


@pytest.mark.parametrize(
    "field, value",
    [
        ("cf", "101"), ("cf", "-1"), ("doi", "100.01"), ("doi", "-0.5"),
        ("b", "101"), ("b", "-101"), ("lw", "-1"), ("we", "-0.01"),
    ],
)
def test_a_value_outside_the_column_check_is_422_not_500(engineer, committed, field, value):
    """The DTO bounds are the same numbers as `ck_ws_cf`, `ck_ws_doi`,
    `ck_ws_b` and `ck_ws_nonneg`. A caller gets a field name, not a constraint
    violation from the driver."""
    target = committed["items"][0]["measurement_id"]
    response = correct(engineer, target, reason="out of range", **{field: value})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("value", ["1990-01-01", "2101-01-01"])
def test_a_date_outside_ck_ws_date_is_422_not_500(engineer, committed, value):
    """Architect review: `measured_date` cited ck_ws_date in the description
    but had no Field bounds, so 1990-01-01 was an unhandled CheckViolation."""
    target = committed["items"][0]["measurement_id"]
    response = correct(engineer, target, reason="out of range", measured_date=value)
    assert response.status_code == 422, response.text


def test_the_dto_bounds_match_the_database(admin_conn):
    """Asserted against `pg_constraint`, so a future CHECK change that the DTO
    does not follow fails here rather than in production."""
    from app.schemas.corrections import B_BOUNDS, DATE_BOUNDS, MEASURE_BOUNDS

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'wavescan'::regclass AND contype = 'c'"
        )
        checks = dict(cur.fetchall())

    assert "cf >= (0)::numeric" in checks["ck_ws_cf"].replace("(", "(")
    for name, (low, high) in MEASURE_BOUNDS.items():
        assert low == 0, name
        if high is not None:
            assert high == 100, name
            assert f"{name} <= (100)::numeric" in checks[f"ck_ws_{name}"]
        assert f"{name} >= (0)::numeric" in (
            checks.get(f"ck_ws_{name}", "") + checks["ck_ws_nonneg"]
        ), name
    assert B_BOUNDS == (-100, 100)
    assert "b <= (100)::numeric" in checks["ck_ws_b"]
    assert DATE_BOUNDS[0].isoformat() in checks["ck_ws_date"]
    assert DATE_BOUNDS[1].isoformat() in checks["ck_ws_date"]


def test_correcting_a_measurement_that_does_not_exist_is_404(engineer):
    assert correct(engineer, 999999999, reason="x", cf="60").status_code == 404


# =====================================================================
# 6. Batch supersede
# =====================================================================
def test_superseding_a_batch_hides_its_rows_without_deleting_them(
    admin, engineer, cleanup, admin_conn
):
    """The whole point of the route: the facts stay, the reads change."""
    batch = committed_batch(engineer, cleanup)
    load_id = batch["load_id"]
    rows = rows_for_batch(admin_conn, load_id)
    assert rows == len(batch["items"])
    total_before = total_rows(admin_conn)

    response = supersede(admin, load_id, reason="plant re-sent the file with fixed serials")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUPERSEDED"
    assert body["previous_status"] == "COMMITTED"
    assert body["superseded_by"] is None
    assert body["measurements_hidden"] == rows

    # Facts intact.
    assert rows_for_batch(admin_conn, load_id) == rows
    assert total_rows(admin_conn) == total_before
    assert batch_status(admin_conn, load_id)[0] == "SUPERSEDED"

    # Gone from every active read.
    # RO03 CHANGE: narrowed to this batch (`load_id`, T19), as T76.
    page = engineer.get(
        "/api/v1/measurements", params={"limit": 500, "plant": "AAT", "load_id": load_id}
    ).json()
    assert page["page"]["total"] == 0, page["page"]
    assert not [m for m in page["items"] if m["load_id"] == load_id]
    for item in batch["items"]:
        assert engineer.get(
            f"/api/v1/measurements/{item['measurement_id']}"
        ).status_code == 404


def test_superseding_writes_no_per_row_supersession(admin, engineer, cleanup, admin_conn):
    """A batch retirement is not a bulk correction. It does not claim each
    reading was replaced by a better one."""
    batch = committed_batch(engineer, cleanup)
    ids = [m["measurement_id"] for m in batch["items"]]
    assert supersede(admin, batch["load_id"], reason="not a bulk correction").status_code == 200

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM measurement_supersession "
            "WHERE superseded_measurement_id = ANY(%s)",
            (ids,),
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM wavescan WHERE measurement_id = ANY(%s) "
            "AND is_superseded",
            (ids,),
        )
        assert cur.fetchone()[0] == 0, "a batch supersede flagged individual rows"


def test_a_replacement_batch_is_recorded_on_the_retired_one(
    admin, engineer, cleanup, admin_conn
):
    """`load_batch.superseded_by` names the send that took over."""
    first = committed_batch(engineer, cleanup)
    second = committed_batch(engineer, cleanup)

    response = supersede(
        admin, first["load_id"],
        reason="corrected re-send", replacement_load_id=second["load_id"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["superseded_by"] == second["load_id"]
    assert batch_status(admin_conn, first["load_id"]) == (
        "SUPERSEDED", second["load_id"]
    )
    # The replacement is untouched.
    assert batch_status(admin_conn, second["load_id"])[0] == "COMMITTED"


def test_superseding_is_audited(admin, engineer, cleanup, admin_conn):
    batch = committed_batch(engineer, cleanup)
    reason = f"audited retirement {uuid.uuid4().hex[:6]}"
    assert supersede(admin, batch["load_id"], reason=reason).status_code == 200

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT action, actor_user_id IS NOT NULL, before, after "
            "FROM audit_event WHERE entity_type = 'load_batch' AND entity_id = %s "
            "ORDER BY id",
            (str(batch["load_id"]),),
        )
        actions = cur.fetchall()

    retirement = [a for a in actions if a[0] == "batch.supersede"]
    assert len(retirement) == 1
    assert retirement[0][1] is True
    assert retirement[0][2]["status"] == "COMMITTED"
    assert retirement[0][3]["reason"] == reason
    assert retirement[0][3]["measurements_hidden"] == len(batch["items"])


def test_superseding_twice_is_refused(admin, engineer, cleanup):
    batch = committed_batch(engineer, cleanup)
    assert supersede(admin, batch["load_id"], reason="first").status_code == 200
    second = supersede(admin, batch["load_id"], reason="second")
    assert second.status_code == 409, second.text
    assert "already retired" in second.json()["message"]


def test_superseding_an_uncommitted_batch_is_refused(admin, engineer, cleanup, admin_conn):
    """A batch that never committed has no facts in production. Cancelling or
    re-parsing it is a different route."""
    review = ingest(engineer, cleanup, "t09-nocommit.xlsx", make_workbook(unique_rows(2)))
    load_id = review["batch"]["load_id"]
    assert review["batch"]["status"] == "PENDING_REVIEW"

    response = supersede(admin, load_id, reason="too early")
    assert response.status_code == 409, response.text
    assert "PENDING_REVIEW" in response.json()["message"]
    assert batch_status(admin_conn, load_id)[0] == "PENDING_REVIEW"


def test_superseding_a_batch_that_does_not_exist_is_404(admin):
    assert supersede(admin, 999999999, reason="x").status_code == 404


@pytest.mark.parametrize("field", ["reason"])
def test_a_supersede_without_a_reason_is_refused(admin, engineer, cleanup, field):
    batch = committed_batch(engineer, cleanup)
    assert admin.post(
        f"/api/v1/batches/{batch['load_id']}/supersede", json={}
    ).status_code == 422
    assert supersede(admin, batch["load_id"], reason="").status_code == 422


def test_an_unknown_supersede_key_is_refused(admin, engineer, cleanup):
    batch = committed_batch(engineer, cleanup)
    assert admin.post(
        f"/api/v1/batches/{batch['load_id']}/supersede",
        json={"reason": "x", "delete_facts": True},
    ).status_code == 422


def test_a_replacement_must_be_a_committed_batch_of_the_same_plant(
    admin, engineer, cleanup, admin_conn
):
    """A `superseded_by` pointing at something unreadable is worse than null:
    it looks like an answer."""
    target = committed_batch(engineer, cleanup)
    pending = ingest(engineer, cleanup, "t09-repl.xlsx", make_workbook(unique_rows(2)))

    itself = supersede(
        admin, target["load_id"], reason="self", replacement_load_id=target["load_id"]
    )
    assert itself.status_code == 409 and "itself" in itself.json()["message"]

    missing = supersede(
        admin, target["load_id"], reason="ghost", replacement_load_id=999999999
    )
    assert missing.status_code == 409 and "does not exist" in missing.json()["message"]

    uncommitted = supersede(
        admin, target["load_id"], reason="not ready",
        replacement_load_id=pending["batch"]["load_id"],
    )
    assert uncommitted.status_code == 409
    assert "PENDING_REVIEW" in uncommitted.json()["message"]

    # None of the refusals retired anything.
    assert batch_status(admin_conn, target["load_id"]) == ("COMMITTED", None)


def test_a_correction_inside_a_superseded_batch_is_refused(
    admin, engineer, cleanup, admin_conn
):
    """Once the batch is retired its rows are not current, so there is nothing
    to correct -- and the message says why rather than 404-ing blankly."""
    batch = committed_batch(engineer, cleanup)
    target = batch["items"][0]["measurement_id"]
    assert supersede(admin, batch["load_id"], reason="retire first").status_code == 200

    response = correct(engineer, target, reason="too late", cf="60")
    assert response.status_code == 409, response.text
    assert "SUPERSEDED" in response.json()["message"]
    assert snapshot(admin_conn, target)["is_superseded"] is False, (
        "a batch retirement flagged an individual row"
    )


# =====================================================================
# 7. Commit still does not auto-supersede — T04 §9, approved
# =====================================================================
def test_committing_a_second_file_for_the_same_plant_retires_nothing(
    engineer, cleanup, admin_conn
):
    """`02-PIPELINE.md` §3 wants the old batch retired on a re-send; §7 makes
    that an Admin action. T04 recorded the gap; T09 fills it with a route and
    does **not** change commit. Regression test for that decision."""
    first = committed_batch(engineer, cleanup)
    second = committed_batch(engineer, cleanup)

    assert batch_status(admin_conn, first["load_id"]) == ("COMMITTED", None)
    assert batch_status(admin_conn, second["load_id"]) == ("COMMITTED", None)
    # RO03 CHANGE: narrowed to the first batch (`load_id`, T19), as T76.
    page = engineer.get(
        "/api/v1/measurements",
        params={"limit": 500, "plant": "AAT", "load_id": first["load_id"]},
    ).json()
    assert page["page"]["total"] == len(first["items"]), page["page"]
    assert [m for m in page["items"] if m["load_id"] == first["load_id"]], (
        "committing a second batch retired the first"
    )


def test_the_ingest_service_cannot_reach_a_supersede(admin_conn):
    """Structural half of the test above: if commit could call the retirement
    path, an Engineer would be able to retire an Admin's batch as a side
    effect. The two live in different services and the ingest one does not
    import the other."""
    source = (REPO_ROOT / "backend/app/services/ingest.py").read_text(encoding="utf-8")
    # Reachability, not vocabulary: `SUPERSEDED` appears in a comment there
    # listing the batch statuses replay refuses, which is prose about the
    # word rather than a use of it.
    for banned in ("CorrectionService", "services.corrections",
                   "measurement_supersession", "record_supersession",
                   "supersede_batch"):
        assert banned not in source, f"ingest.py reaches {banned}"
    assert not re.search(r"status\s*=\s*['\"]SUPERSEDED", source), (
        "ingest.py sets a batch to SUPERSEDED"
    )


# =====================================================================
# 8. The database's own guarantees — asserted as app_rw
# =====================================================================
def test_the_application_role_still_cannot_update_or_delete_a_measurement(app_conn):
    """T09 added no grant. This is the guarantee every claim above rests on."""
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT privilege_type FROM information_schema.role_table_grants
             WHERE grantee = current_user AND table_name = 'wavescan'
             ORDER BY privilege_type
            """
        )
        assert [r[0] for r in cur.fetchall()] == ["INSERT", "SELECT"]

    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("UPDATE wavescan SET cf = 1 WHERE measurement_id = 1")
    app_conn.rollback()
    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM wavescan WHERE measurement_id = 1")
    app_conn.rollback()


def test_the_application_role_cannot_delete_a_batch(app_conn):
    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM load_batch WHERE load_id = 1")
    app_conn.rollback()


def test_a_row_cannot_be_inserted_already_superseded(app_conn, admin_conn):
    """`trg_reject_presuperseded`. A row that arrives hidden is a delete
    wearing a hat (`01-DATA-MODEL.md` §5)."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT measured_date, plant, model, checkzone, color, tolerance_group, "
            "       paintline, serial_no, lw, sw, cf, doi, du, wa, wb, wc, wd, we, b, "
            "       load_id, source_sheet "
            "FROM wavescan ORDER BY measurement_id LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None, "wavescan is empty"

    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation) as excinfo:
            cur.execute(
                "INSERT INTO wavescan (measured_date, plant, model, checkzone, color, "
                "tolerance_group, paintline, serial_no, lw, sw, cf, doi, du, wa, wb, "
                "wc, wd, we, b, load_id, source_sheet, source_row, is_superseded) "
                "VALUES (" + ",".join(["%s"] * 21) + ", 999123, true)",
                row,
            )
    app_conn.rollback()
    assert "is_superseded cannot be set" in str(excinfo.value)


def test_a_supersession_cannot_be_withdrawn(app_conn):
    """No UPDATE and no DELETE on the side table: a retirement is followed by
    a further correction, never erased."""
    with app_conn.cursor() as cur:
        cur.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = current_user AND table_name = 'measurement_supersession' "
            "ORDER BY privilege_type"
        )
        assert [r[0] for r in cur.fetchall()] == ["INSERT", "SELECT"]


# =====================================================================
# 9. The partial unique index — revision 0005
# =====================================================================
def test_the_ingest_uniqueness_rule_is_now_partial(admin_conn):
    """`(load_id, source_row)` is still unique among ingest rows, and now
    excludes corrections -- which is the only reason a correction can exist."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'wavescan' AND indexname = 'uq_ws_load_row_original'"
        )
        row = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conrelid = 'wavescan'::regclass AND conname = 'uq_ws_load_row'"
        )
        old = cur.fetchone()[0]

    assert row is not None, "revision 0005 did not create the partial index"
    indexdef = row[0]
    assert re.search(r"UNIQUE INDEX .* \(load_id, source_row\)", indexdef), indexdef
    assert "WHERE (corrects_measurement_id IS NULL)" in indexdef
    assert old == 0, "the full constraint survived alongside the partial index"


def test_the_same_spreadsheet_row_still_cannot_be_ingested_twice(app_conn, admin_conn):
    """The guarantee T02 wrote is unchanged: an ingest row (one with no
    `corrects_measurement_id`) still cannot share a cell with another."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT measured_date, plant, model, checkzone, color, tolerance_group, "
            "       paintline, serial_no, lw, sw, cf, doi, du, wa, wb, wc, wd, we, b, "
            "       load_id, source_sheet, source_row "
            "FROM wavescan WHERE corrects_measurement_id IS NULL "
            "ORDER BY measurement_id LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None, "wavescan has no ingest rows"

    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO wavescan (measured_date, plant, model, checkzone, color, "
                "tolerance_group, paintline, serial_no, lw, sw, cf, doi, du, wa, wb, "
                "wc, wd, we, b, load_id, source_sheet, source_row) "
                "VALUES (" + ",".join(["%s"] * 22) + ")",
                row,
            )
    app_conn.rollback()


# =====================================================================
# 10. The rules T09 did not change
# =====================================================================
def test_the_domain_package_still_imports_no_framework():
    """`00-ARCHITECTURE.md` §5 rule 1. T09 added a service, a repository and a
    schema module, none of which is in `domain/`."""
    for path in (REPO_ROOT / "backend/app/domain").rglob("*.py"):
        code = path.read_text(encoding="utf-8")
        for banned in ("import fastapi", "from fastapi", "import psycopg", "import sqlalchemy"):
            assert banned not in code, f"{path.name} imports {banned}"


def test_no_t09_module_updates_or_deletes_a_fact():
    """Read the SQL. `AGENTS.md` rule 7 as a grep over the modules that write."""
    # Matched on SQL syntax, not on the bare keyword: these modules discuss
    # the UPDATE and DELETE privileges they do not hold, which is the point of
    # them. `UPDATE x SET` and `DELETE FROM x` are statements; the prose is not.
    mutating = re.compile(r"UPDATE\s+(\w+)\s+SET|DELETE\s+FROM\s+(\w+)", re.I)
    for name in ("app/repositories/corrections.py", "app/services/corrections.py",
                 "app/api/v1/measurements.py", "app/api/v1/batches.py"):
        code = (REPO_ROOT / "backend" / name).read_text(encoding="utf-8")
        for updated, deleted in mutating.findall(code):
            table = (updated or deleted).lower()
            assert not deleted, f"{name} deletes from {deleted}"
            assert table not in ("wavescan", "measurement_supersession"), (
                f"{name} updates {table} in place"
            )
            # The one table T09 may update, and only on its two granted columns.
            assert table == "load_batch", f"{name} updates an unexpected table: {table}"


def test_t09_added_no_grading_field():
    """D1 and D2 stay open. T05's rule exists and nothing here reads it."""
    from app.schemas.corrections import (
        CorrectionCreate,
        CorrectionResult,
        SupersedeCreate,
        SupersedeResult,
    )

    for model in (CorrectionCreate, CorrectionResult, SupersedeCreate, SupersedeResult):
        fields = set(model.model_fields)
        assert not fields & {"grade", "status_of", "pass_rate", "ribbon", "verdict"}, model

    for name in ("app/schemas/corrections.py", "app/services/corrections.py",
                 "app/repositories/corrections.py"):
        code = (REPO_ROOT / "backend" / name).read_text(encoding="utf-8")
        for banned in ("domain.grading", "status_of", "pass_rate", "grading_family"):
            assert banned not in code, f"{name} uses {banned}"


def test_by_id_and_correction_do_not_publish_list_filters():
    """The recorded contract change is GET-by-id and a correction body, not
    a second copy of the list's plant/model/date query string."""
    import json
    spec = json.loads((REPO_ROOT / "docs/openapi.json").read_text(encoding="utf-8"))
    for path in (
        "/api/v1/measurements/{measurement_id}",
        "/api/v1/measurements/{measurement_id}/corrections",
    ):
        ops = spec["paths"][path]
        method = "get" if path.endswith("}") else "post"
        names = {p["name"] for p in ops[method].get("parameters", []) if p.get("in") == "query"}
        assert names == set(), f"{path} still publishes list filters: {names}"


def test_no_mutating_route_stays_reserved():
    """`POST /standards` is implemented. `reserved.py` has no stubs left."""
    source = (REPO_ROOT / "backend/app/api/v1/reserved.py").read_text(encoding="utf-8")
    assert "@router.post" not in source
