"""T21 -- upload review: inbox filters, vehicle sets, overrides, abandon.

Five claims, the first three partly pure:

* **The inbox is decided by the server.** `inbox=all` is T19's list, and
  Needs attention returns an older unfinished workbook on the first page,
  without the client walking the plant.
* **A vehicle set is plant + measured date + model + colour + serial on one
  sheet.** Two serials are two sets, a blank serial is one
  identity-incomplete group and never a vehicle, a duplicate row is not a
  second vehicle, and the expected point count is
  `ref_model.expected_zone_count` -- U704 is 31 in the seed, which is exactly
  why a hardcoded 32 would be caught here.
* **An override is append-only evidence that re-enters the one parser.**
  Saving one re-derives the sheet from its bytes, moves the review revision
  (so old acknowledgements stop counting), leaves `stg_raw` saying what the
  file said, and commit inserts the overridden value. A mapping replay keeps
  applying it.
* **Abandon is a status, not a DELETE.** Everything is retained; replay and
  commit refuse the batch; a committed batch cannot be abandoned.
* **The reads are Engineer (RO12), the override and abandon Admin**, and the
  Engineer's upload and commit are untouched.

Run through T04's fixtures against the real application, worker and
database, like T19.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from psycopg import errors as pgerr

from app.domain import workbooks as rules
from app.domain.workbooks import (
    group_vehicle_sets,
    operational_summary,
    select_inbox,
    vehicle_id,
)
from tests.test_t04_ingest import (
    acknowledge,
    forget_bytes,
    make_workbook,
    unique_rows,
    wait_for,
)
from tests.test_t19_data_manager import (
    ABSENT_HASH,
    base,
    card,
    history_of,
    ingest_as,
    mixed_workbook,
    owner_batch,
    workbooks,
)

# Fixtures, in scope by being in the module namespace (as T08, T17-T19 do).
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)
from tests.test_t19_data_manager import alias_cleanup, anon  # noqa: F401

pytestmark = pytest.mark.ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


# =====================================================================
# helpers
# =====================================================================
def this_month() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def vehicles_of(client, plant: str, file_hash: str, load_id: int, **params) -> dict:
    response = client.get(
        f"{base(plant)}/{file_hash}/vehicles", params={"load_id": load_id, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


def points_of(client, plant: str, file_hash: str, vid: str, **params) -> dict:
    response = client.get(f"{base(plant)}/{file_hash}/vehicles/{vid}/points", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def review_of(client, load_id: int) -> dict:
    response = client.get(f"/api/v1/batches/{load_id}")
    assert response.status_code == 200, response.text
    return response.json()


def complete_vehicle(page: dict) -> dict:
    found = [v for v in page["items"] if v["identity_complete"]]
    assert len(found) == 1, page["items"]
    return found[0]


def post_override(client, review: dict, vid: str, changes: list[dict], revision=None):
    batch = review["batch"]
    return client.post(
        f"{base(batch['plant_code'])}/{batch['file_hash']}/overrides",
        json={
            "load_id": batch["load_id"],
            "vehicle_id": vid,
            "review_revision": revision or batch["review_revision"],
            "changes": changes,
        },
    )


def count(admin_conn, sql: str, *params) -> int:
    with admin_conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def backdate(admin_conn, load_id: int, when: str) -> None:
    """Move a batch's upload time into an earlier month, as the OWNER.

    The only way to have "last month's upload" in a test that runs today.
    `started_at` is provenance the application never writes after insert;
    changing it here changes nothing about the ingest path under test.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "UPDATE load_batch SET started_at = %s WHERE load_id = %s", (when, load_id)
        )


def abandon(client, load_id: int, reason: str = "T21: removed from review."):
    return client.post(f"/api/v1/batches/{load_id}/abandon", json={"reason": reason})


# =====================================================================
# 1. pure rules
# =====================================================================
@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["ABANDONED"], "ABANDONED"),
        (["ABANDONED", "ABANDONED"], "ABANDONED"),
        (["ABANDONED", "PENDING_REVIEW"], "REVIEW_REQUIRED"),
        (["ABANDONED", "COMMITTED"], "ACTIVE"),
        (["ABANDONED", "SUPERSEDED"], "SUPERSEDED"),
        (["ABANDONED", "RUNNING"], "PROCESSING"),
        (["ABANDONED", "COMMITTED", "PENDING_REVIEW"], "PARTIALLY_COMMITTED"),
        (["SUPERSEDED"], "SUPERSEDED"),
    ],
)
def test_the_summary_knows_abandoned(statuses, expected):
    assert operational_summary(statuses) == expected


def _row(source_row, disposition="LOAD", **canonical):
    base_canonical = {
        "measured_date": "2026-08-03", "model": "U704", "color": "3HC Traction Green",
        "serial_no": "S-1", "checkzone": f"Z{source_row:02d}",
    }
    return {
        "source_row": source_row,
        "disposition": disposition,
        "canonical": {**base_canonical, **canonical},
    }


def test_two_serials_on_the_same_date_model_and_colour_are_two_vehicle_sets():
    rows = [_row(2, serial_no="S-1"), _row(3, serial_no="S-2")]
    sets = group_vehicle_sets(7, rows, {"U704": 31})
    assert len(sets) == 2
    assert {s.serial_no for s in sets} == {"S-1", "S-2"}
    assert len({s.vehicle_id for s in sets}) == 2


def test_blank_serials_are_one_vehicle_the_sheet_with_no_serial():
    """T39 CHANGE (ADR 0013 decision 8): with no serial, the tab is one
    vehicle. It is complete when date, model and colour are present; it is
    still a short set when it has fewer panels than the model expects."""
    rows = [_row(2, serial_no=None), _row(3, serial_no="  "), _row(4, serial_no="")]
    sets = group_vehicle_sets(7, rows, {"U704": 31})
    assert len(sets) == 1
    only = sets[0]
    assert only.identity_complete is True
    assert only.incomplete_set is True, "3 of 31 panels is still a short vehicle"
    assert only.serial_no is None, "no serial is generated"
    assert only.source_rows == [2, 3, 4]
    assert only.vehicle_id == vehicle_id(7, ("2026-08-03", "U704", "3HC Traction Green", None))


def test_a_duplicate_row_lands_in_the_vehicle_it_repeats():
    rows = [_row(2, checkzone="01 RRHOOD"), _row(3, "DUPLICATE", checkzone="01 RRHOOD")]
    sets = group_vehicle_sets(7, rows, {"U704": 31})
    assert len(sets) == 1
    assert sets[0].dispositions["LOAD"] == 1
    assert sets[0].dispositions["DUPLICATE"] == 1
    assert sets[0].point_count == 1, "a repeated checkzone is one point"


def test_expected_count_is_injected_and_unknown_models_have_none():
    rows = [_row(i) for i in range(2, 5)]
    assert group_vehicle_sets(1, rows, {"U704": 3})[0].incomplete_set is False
    assert group_vehicle_sets(1, rows, {"U704": 4})[0].incomplete_set is True
    unknown = group_vehicle_sets(1, rows, {})[0]
    assert unknown.expected_point_count is None
    assert unknown.incomplete_set is False, "unknown expected is not a mismatch"


def test_the_vehicle_id_formula():
    expected = hashlib.sha256(
        "12|2026-08-03|U704|3HC Traction Green|S-1".encode("utf-8")
    ).hexdigest()
    assert vehicle_id(12, ("2026-08-03", "U704", "3HC Traction Green", "S-1")) == expected
    assert vehicle_id(12, (None, None, None, None)) == hashlib.sha256(b"12||||").hexdigest()
    assert vehicle_id(13, ("2026-08-03", "U704", "3HC Traction Green", "S-1")) != expected


def test_the_grouping_module_has_no_literal_expected_count_and_no_framework():
    source = (BACKEND_ROOT / "app" / "domain" / "workbooks.py").read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])32(?![\w.])", source), "a hardcoded 32 is a defect"
    for banned in ("import fastapi", "from fastapi", "import psycopg", "from psycopg",
                   "import sqlalchemy", "from sqlalchemy"):
        assert banned not in source


def test_the_inbox_rules_on_plain_values():
    def wb(h, uploaded, summary, measured=date(2026, 8, 1)):
        return {"file_hash": h, "uploaded_at": uploaded,
                "operational_summary": summary, "measured_date_min": measured}

    sept = datetime(2026, 9, 3, tzinfo=timezone.utc)
    later_sept = datetime(2026, 9, 10, tzinfo=timezone.utc)
    june = datetime(2026, 6, 1, tzinfo=timezone.utc)
    july = datetime(2026, 7, 1, tzinfo=timezone.utc)
    index = [
        wb("a", sept, "REVIEW_REQUIRED"),
        wb("b", later_sept, "ACTIVE"),
        wb("c", sept, "PROCESSING", measured=None),
        wb("d", july, "PARTIALLY_COMMITTED"),
        wb("e", june, "REVIEW_REQUIRED"),
        wb("f", june, "ACTIVE"),
        wb("g", june, "SUPERSEDED"),
        wb("h", june, "ABANDONED"),
    ]
    current = [w["file_hash"] for w in select_inbox(index, "current_month", (2026, 9))]
    assert current == ["c", "b", "a"]
    attention = [w["file_hash"] for w in select_inbox(index, "needs_attention", (2026, 9))]
    assert attention == ["e", "d"]
    # A timestamp just before midnight UTC on the 30th belongs to that month
    # even when it is already the 1st somewhere east of Greenwich.
    edge = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc).astimezone()
    assert rules.utc_month(edge) == (2026, 9)
    assert rules.spans_months(date(2026, 6, 30), date(2026, 7, 1)) is True
    assert rules.spans_months(date(2026, 6, 1), None) is False


# =====================================================================
# 2. the inbox against the running system
# =====================================================================
def test_inbox_all_is_the_t19_list(admin):
    plain = workbooks(admin, "AAT", limit=200)
    explicit = workbooks(admin, "AAT", limit=200, inbox="all")
    assert [w["file_hash"] for w in plain["items"]] == [
        w["file_hash"] for w in explicit["items"]
    ]
    assert plain["page"]["total"] == explicit["page"]["total"]
    assert plain["inbox"] == "all" and plain["uploaded_month"] is None


def test_invalid_inbox_queries_are_422(admin):
    for params in ({"inbox": "everything"}, {"inbox": "current_month", "uploaded_month": "2026-13"},
                   {"inbox": "current_month", "uploaded_month": "Sept"},
                   {"uploaded_month": "2026-9"}):
        response = admin.get(base("AAT"), params=params)
        assert response.status_code == 422, (params, response.text)


def test_current_month_and_needs_attention(engineer, admin, admin_conn, cleanup):
    """One workbook per interesting state, uploaded last month or this month."""
    fresh = ingest_as(engineer, cleanup, "t21-inbox-fresh.xlsx", make_workbook(unique_rows(2)))
    old_pending = ingest_as(engineer, cleanup, "t21-inbox-old.xlsx", make_workbook(unique_rows(2)))
    old_active = ingest_as(engineer, cleanup, "t21-inbox-active.xlsx", make_workbook(unique_rows(2)))
    old_retired = ingest_as(engineer, cleanup, "t21-inbox-retired.xlsx", make_workbook(unique_rows(2)))
    old_abandoned = ingest_as(engineer, cleanup, "t21-inbox-abandoned.xlsx", make_workbook(unique_rows(2)))

    for review in (old_active, old_retired):
        load_id = review["batch"]["load_id"]
        assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    assert admin.post(
        f"/api/v1/batches/{old_retired['batch']['load_id']}/supersede",
        json={"reason": "T21 inbox: retired."},
    ).status_code == 200
    assert abandon(admin, old_abandoned["batch"]["load_id"]).status_code == 200

    backdated = {
        old_pending["batch"]["load_id"]: "2026-05-10T08:00:00+00:00",
        old_active["batch"]["load_id"]: "2026-05-11T08:00:00+00:00",
        old_retired["batch"]["load_id"]: "2026-05-12T08:00:00+00:00",
        old_abandoned["batch"]["load_id"]: "2026-05-13T08:00:00+00:00",
    }
    for load_id, when in backdated.items():
        backdate(admin_conn, load_id, when)

    month = this_month()
    attention = workbooks(admin, "AAT", inbox="needs_attention", uploaded_month=month, limit=200)
    hashes = [w["file_hash"] for w in attention["items"]]
    assert attention["uploaded_month"] == month
    assert old_pending["batch"]["file_hash"] in hashes
    for excluded in (fresh, old_active, old_retired, old_abandoned):
        assert excluded["batch"]["file_hash"] not in hashes
    assert all(w["operational_summary"] in
               ("PROCESSING", "REVIEW_REQUIRED", "PARTIALLY_COMMITTED")
               for w in attention["items"])
    uploaded = [w["uploaded_at"] for w in attention["items"]]
    assert uploaded == sorted(uploaded), "oldest unfinished first"
    assert attention["page"]["total"] == len(hashes)

    # Paging is the server's: walking the filtered list one card at a time
    # gives the same order, so a client never pages the plant to find it.
    walked = [
        workbooks(admin, "AAT", inbox="needs_attention", uploaded_month=month,
                  limit=1, offset=i)["items"][0]["file_hash"]
        for i in range(attention["page"]["total"])
    ]
    assert walked == hashes

    current = workbooks(admin, "AAT", inbox="current_month", uploaded_month=month, limit=200)
    current_hashes = [w["file_hash"] for w in current["items"]]
    assert fresh["batch"]["file_hash"] in current_hashes
    assert old_pending["batch"]["file_hash"] not in current_hashes

    may = workbooks(admin, "AAT", inbox="current_month", uploaded_month="2026-05", limit=200)
    may_hashes = [w["file_hash"] for w in may["items"]]
    for review in (old_pending, old_active, old_retired, old_abandoned):
        assert review["batch"]["file_hash"] in may_hashes
    assert fresh["batch"]["file_hash"] not in may_hashes
    by_hash = {w["file_hash"]: w for w in may["items"]}
    assert by_hash[old_abandoned["batch"]["file_hash"]]["abandoned"] is True
    assert by_hash[old_abandoned["batch"]["file_hash"]]["operational_summary"] == "ABANDONED"
    assert by_hash[old_retired["batch"]["file_hash"]]["superseded"] is True
    assert by_hash[old_retired["batch"]["file_hash"]]["abandoned"] is False


def test_card_fields_count_vehicle_sets_and_cross_month_ranges(
    engineer, admin, admin_conn, cleanup
):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t21-card.xlsx", data)
    item = card(admin, "AAT", review["batch"]["file_hash"])
    assert item["vehicle_set_count"] == 3, "vehicle + quarantine group + reject group"
    assert item["measured_dates_span_months"] is False
    assert item["abandoned"] is False
    page = vehicles_of(admin, "AAT", item["file_hash"], review["batch"]["load_id"])
    assert page["page"]["total"] == item["vehicle_set_count"]

    rows = unique_rows(2)
    rows[0]["Date"] = "2026-06-30"
    rows[1]["Date"] = "2026-07-01"
    spanning = ingest_as(engineer, cleanup, "t21-span.xlsx", make_workbook(rows))
    assert card(admin, "AAT", spanning["batch"]["file_hash"])["measured_dates_span_months"] is True

    load_id, file_hash = owner_batch(admin_conn, cleanup, plant="AAT", status="RUNNING")
    parsing = card(admin, "AAT", file_hash)
    assert parsing["vehicle_set_count"] == 0
    assert parsing["measured_dates_span_months"] is False
    empty = vehicles_of(admin, "AAT", file_hash, load_id)
    assert empty["items"] == [] and empty["page"]["total"] == 0


# =====================================================================
# 3. vehicle sets and points against the running system
# =====================================================================
def test_vehicle_sets_of_a_mixed_sheet(engineer, admin, admin_conn, cleanup):
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t21-vehicles.xlsx", data)
    batch = review["batch"]
    page = vehicles_of(admin, "AAT", batch["file_hash"], batch["load_id"])

    items = page["items"]
    assert [v["identity_complete"] for v in items] == [False, False, True], (
        "identity-incomplete groups first"
    )
    vehicle = items[-1]
    expected = count(
        admin_conn, "SELECT expected_zone_count FROM ref_model WHERE model_code = %s", "U704"
    )
    assert vehicle["expected_point_count"] == expected
    assert vehicle["model"] == "U704" and vehicle["color"], "canonical colour, not raw"
    assert vehicle["dispositions"] == {"load": 1, "duplicate": 1, "reject": 0, "quarantine": 0}
    assert vehicle["point_count"] == 1
    assert vehicle["incomplete_set"] is True
    assert vehicle["vehicle_id"] == vehicle_id(
        batch["load_id"],
        (vehicle["measured_date"], vehicle["model"], vehicle["color"], vehicle["serial_no"]),
    )

    quarantine = [v for v in items if v["dispositions"]["quarantine"]][0]
    assert quarantine["model"] is None and quarantine["expected_point_count"] is None
    reject = [v for v in items if v["dispositions"]["reject"]][0]
    assert reject["serial_no"] is None and reject["identity_complete"] is False

    # Points: raw against proposed, checkzone order.
    points = points_of(admin, "AAT", batch["file_hash"], vehicle["vehicle_id"])
    assert points["page"]["total"] == 2
    assert points["vehicle"]["vehicle_id"] == vehicle["vehicle_id"]
    assert [p["disposition"] for p in points["items"]] == ["LOAD", "DUPLICATE"]
    loaded = points["items"][0]
    assert loaded["checkzone"] == "RRHOOD", "the canonical zone, not the cell text"
    assert loaded["raw"]["values"]["cf"] is not None
    assert loaded["proposed"]["measures"]["cf"] is not None
    assert loaded["current_overrides"] == []
    assert loaded["measurement_id"] is None


def test_two_serials_in_one_sheet_are_two_cards_and_blank_serials_are_not_vehicles(
    engineer, admin, cleanup
):
    first = unique_rows(2)
    second = unique_rows(2)
    blank = unique_rows(3, **{"Serial No": None})
    review = ingest_as(
        engineer, cleanup, "t21-serials.xlsx", make_workbook(first + second + blank)
    )
    batch = review["batch"]
    page = vehicles_of(admin, "AAT", batch["file_hash"], batch["load_id"])
    # T39 CHANGE (ADR 0013 decision 8): the blank-serial rows are one
    # vehicle -- the sheet -- and complete; two serials still split.
    complete = [v for v in page["items"] if v["identity_complete"]]
    assert {v["serial_no"] for v in complete} == {
        first[0]["Serial No"], second[0]["Serial No"], None,
    }
    assert len({v["vehicle_id"] for v in complete}) == 3
    blank_set = [v for v in complete if v["serial_no"] is None]
    assert len(blank_set) == 1, "every blank-serial row is one group"
    assert sum(blank_set[0]["dispositions"].values()) == 3


def test_vehicle_routes_scope_and_refusals(engineer, admin, admin_conn, cleanup):
    # T76 CHANGE (D2 / T55 / T58): FTM offers neither U704 nor Traction
    # Green, and AAT's walk is not FTM gold, so relabelling AAT rows made
    # every row a reject. `unique_rows(Plant="FTM")` writes FTM's own offered
    # model, colour and walk -- the vehicle this test needs.
    ftm_rows = unique_rows(2, Plant="FTM")
    ftm = ingest_as(engineer, cleanup, "t21-ftm.xlsx", make_workbook(ftm_rows), "FTM")
    aat = ingest_as(engineer, cleanup, "t21-aat.xlsx", make_workbook(unique_rows(2)))
    ftm_hash = ftm["batch"]["file_hash"]
    ftm_vehicle = complete_vehicle(
        vehicles_of(admin, "FTM", ftm_hash, ftm["batch"]["load_id"])
    )["vehicle_id"]

    # Cross-plant: the FTM workbook is not reachable through AAT.
    assert admin.get(
        f"{base('AAT')}/{ftm_hash}/vehicles", params={"load_id": ftm["batch"]["load_id"]}
    ).status_code == 404
    assert admin.get(
        f"{base('AAT')}/{ftm_hash}/vehicles/{ftm_vehicle}/points"
    ).status_code == 404
    # A vehicle of another workbook is not found in this one.
    assert admin.get(
        f"{base('AAT')}/{aat['batch']['file_hash']}/vehicles/{ftm_vehicle}/points"
    ).status_code == 404
    # A sheet of another workbook is not a child.
    assert admin.get(
        f"{base('AAT')}/{aat['batch']['file_hash']}/vehicles",
        params={"load_id": ftm["batch"]["load_id"]},
    ).status_code == 404
    # load_id is required; ids are 64 hex.
    assert admin.get(f"{base('AAT')}/{aat['batch']['file_hash']}/vehicles").status_code == 422
    assert admin.get(f"{base('AAT')}/{aat['batch']['file_hash']}/vehicles/xyz/points").status_code == 422
    assert admin.get(f"{base('NOWHERE')}/{ABSENT_HASH}/vehicles", params={"load_id": 1}).status_code == 404
    assert admin.get(f"{base('AAT')}/{ABSENT_HASH}/vehicles", params={"load_id": 1}).status_code == 404


def test_an_inactive_plant_still_lists_nothing(admin, admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT plant_code FROM ref_plant WHERE NOT is_active LIMIT 1")
        row = cur.fetchone()
    if row is None:
        pytest.skip("no inactive plant in ref_plant to exercise this")
    plant = row[0]
    body = workbooks(admin, plant, inbox="needs_attention")
    assert body["plant_is_active"] is False
    assert body["items"] == [] and body["page"]["total"] == 0
    assert admin.get(f"{base(plant)}/{ABSENT_HASH}/vehicles", params={"load_id": 1}).status_code == 404


def test_vehicle_reads_do_not_open_the_workbook(engineer, admin, admin_conn, cleanup):
    review = ingest_as(engineer, cleanup, "t21-no-excel.xlsx", make_workbook(unique_rows(3)))
    batch = review["batch"]
    with admin_conn.cursor() as cur:
        cur.execute("SELECT raw_store_key FROM load_batch WHERE load_id = %s", (batch["load_id"],))
        key = cur.fetchone()[0]
    stored = admin.app.state.ingest_service.store.path_for(key)
    moved = stored.with_suffix(stored.suffix + ".moved")
    stored.rename(moved)
    try:
        page = vehicles_of(admin, "AAT", batch["file_hash"], batch["load_id"])
        vid = complete_vehicle(page)["vehicle_id"]
        assert points_of(admin, "AAT", batch["file_hash"], vid)["page"]["total"] == 3
    finally:
        moved.rename(stored)


# =====================================================================
# 4. overrides
# =====================================================================
@pytest.fixture()
def pending_mixed(engineer, admin, admin_conn, cleanup):
    """A PENDING_REVIEW sheet with all four dispositions, and its vehicle."""
    data = mixed_workbook()
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t21-override.xlsx", data)
    batch = review["batch"]
    page = vehicles_of(admin, "AAT", batch["file_hash"], batch["load_id"])
    vehicle = complete_vehicle(page)
    points = points_of(admin, "AAT", batch["file_hash"], vehicle["vehicle_id"])["items"]
    load_row = [p for p in points if p["disposition"] == "LOAD"][0]
    dup_row = [p for p in points if p["disposition"] == "DUPLICATE"][0]
    return review, vehicle, load_row, dup_row


def test_override_refusals_write_nothing(engineer, admin, admin_conn, pending_mixed):
    review, vehicle, load_row, dup_row = pending_mixed
    load_id = review["batch"]["load_id"]
    vid = vehicle["vehicle_id"]
    ok_change = {"source_row": load_row["source_row"], "field": "cf",
                 "value": "55.5", "reason": "Tape reads 55.5."}

    refused = {
        "identity field": post_override(admin, review, vid, [{**ok_change, "field": "checkzone"}]),
        "serial as field": post_override(admin, review, vid, [{**ok_change, "field": "serial_no"}]),
        "extra identity key": post_override(admin, review, vid, [{**ok_change, "serial_no": "X"}]),
        "json number": post_override(admin, review, vid, [{**ok_change, "value": 55.5}]),
        "out of bounds": post_override(admin, review, vid, [{**ok_change, "value": "101"}]),
        "null non-b": post_override(admin, review, vid, [{**ok_change, "value": None}]),
        "blank reason": post_override(admin, review, vid, [{**ok_change, "reason": "   "}]),
        "no changes": post_override(admin, review, vid, []),
        "non-LOAD row": post_override(
            admin, review, vid, [{**ok_change, "source_row": dup_row["source_row"]}]
        ),
        "row outside set": post_override(admin, review, vid, [{**ok_change, "source_row": 999}]),
        "unknown vehicle": post_override(admin, review, "f" * 64, [ok_change]),
        "same value": post_override(
            admin, review, vid,
            [{**ok_change, "value": load_row["proposed"]["measures"]["cf"]}],
        ),
    }
    for name, response in refused.items():
        assert response.status_code == 422, (name, response.text)

    stale = post_override(admin, review, vid, [ok_change], revision="a" * 64)
    assert stale.status_code == 409, stale.text

    for role in (engineer,):
        assert post_override(role, review, vid, [ok_change]).status_code == 403

    assert count(admin_conn, "SELECT count(*) FROM review_override WHERE load_id = %s", load_id) == 0
    after = review_of(engineer, load_id)
    assert after["batch"]["review_revision"] == review["batch"]["review_revision"]


def test_a_viewer_and_anonymous_caller_cannot_override_or_abandon(viewer, anon):
    body = {"load_id": 1, "vehicle_id": "0" * 64, "review_revision": "0" * 64,
            "changes": [{"source_row": 2, "field": "cf", "value": "1", "reason": "x"}]}
    assert viewer.post(f"{base('AAT')}/{ABSENT_HASH}/overrides", json=body).status_code == 403
    assert anon.post(f"{base('AAT')}/{ABSENT_HASH}/overrides", json=body).status_code == 401
    assert viewer.post("/api/v1/batches/1/abandon", json={"reason": "x"}).status_code == 403
    assert anon.post("/api/v1/batches/1/abandon", json={"reason": "x"}).status_code == 401
    for path in (f"{base('AAT')}/{ABSENT_HASH}/vehicles?load_id=1",
                 f"{base('AAT')}/{ABSENT_HASH}/vehicles/{'0' * 64}/points"):
        assert viewer.get(path).status_code == 403
        assert anon.get(path).status_code == 401


def test_an_engineer_reads_the_new_reads_and_is_refused_abandon(engineer, admin, cleanup):
    # RO12 CHANGE (owner, 2026-10-13): vehicles, points and the inbox were
    # Admin (403 for an Engineer) and are now Engineer (200). Abandon stays Admin.
    review = ingest_as(engineer, cleanup, "t21-eng.xlsx", make_workbook(unique_rows(2)))
    batch = review["batch"]
    vid = complete_vehicle(vehicles_of(admin, "AAT", batch["file_hash"], batch["load_id"]))["vehicle_id"]
    assert engineer.get(
        f"{base('AAT')}/{batch['file_hash']}/vehicles", params={"load_id": batch["load_id"]}
    ).status_code == 200
    assert engineer.get(f"{base('AAT')}/{batch['file_hash']}/vehicles/{vid}/points").status_code == 200
    assert abandon(engineer, batch["load_id"]).status_code == 403
    for inbox in ("current_month", "needs_attention"):
        assert engineer.get(base("AAT"), params={"inbox": inbox}).status_code == 200
    # ...while upload and commit stay theirs.
    assert engineer.post(f"/api/v1/batches/{batch['load_id']}/commit").status_code == 200


def test_an_override_revalidates_and_commit_inserts_the_overridden_value(
    engineer, admin, admin_conn, pending_mixed
):
    review, vehicle, load_row, _ = pending_mixed
    batch = review["batch"]
    load_id = batch["load_id"]
    source_row = load_row["source_row"]
    file_cf = load_row["proposed"]["measures"]["cf"]
    raw_before = count(
        admin_conn, "SELECT raw_cf FROM stg_raw WHERE load_id = %s AND source_row = %s",
        load_id, source_row,
    )
    staged_before = count(admin_conn, "SELECT count(*) FROM stg_raw WHERE load_id = %s", load_id)

    # Every warning acknowledged at the original revision: committable.
    for category in ("REJECTED_ROWS", "QUARANTINED_MODELS", "DUPLICATE_ROWS"):
        assert acknowledge(admin, review, category).status_code == 201
    assert review_of(engineer, load_id)["committable"] is True

    saved = post_override(admin, review, vehicle["vehicle_id"], [
        {"source_row": source_row, "field": "cf", "value": "55.25",
         "reason": "Instrument tape reads 55.25; cell was mistyped."},
        {"source_row": source_row, "field": "b", "value": None,
         "reason": "B was not measured on this panel."},
    ])
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["previous_review_revision"] == batch["review_revision"]
    assert body["review_revision"] != batch["review_revision"]
    assert body["audit_action"] == "review.override"
    stored = {o["field"]: o for o in body["overrides"]}
    assert stored["cf"]["new_value"] == "55.25"
    assert stored["cf"]["previous_proposed"] == file_cf
    assert stored["b"]["new_value"] is None
    assert stored["cf"]["review_revision"] == batch["review_revision"]
    assert body["counts"]["rows_loaded"] == 1 and body["counts"]["balanced"] is True

    # Still in review, never through RUNNING, and the old acks no longer count.
    after = review_of(engineer, load_id)
    assert after["batch"]["status"] == "PENDING_REVIEW"
    assert after["batch"]["review_revision"] == body["review_revision"]
    assert "WARNINGS_UNACKNOWLEDGED" in after["commit_blockers"]
    assert after["committable"] is False
    refused = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert refused.status_code == 409 and "WARNINGS_UNACKNOWLEDGED" in refused.json()["message"]

    # The file's words are unchanged; the proposal carries the override.
    assert count(
        admin_conn, "SELECT raw_cf FROM stg_raw WHERE load_id = %s AND source_row = %s",
        load_id, source_row,
    ) == raw_before
    assert count(admin_conn, "SELECT count(*) FROM stg_raw WHERE load_id = %s", load_id) == staged_before
    points = points_of(admin, "AAT", batch["file_hash"], vehicle["vehicle_id"])["items"]
    point = [p for p in points if p["source_row"] == source_row][0]
    assert point["proposed"]["measures"]["cf"] == "55.25"
    assert point["proposed"]["measures"]["b"] is None
    assert point["raw"]["values"]["cf"] == load_row["raw"]["values"]["cf"]
    current = {o["field"]: o for o in point["current_overrides"]}
    assert set(current) == {"cf", "b"}
    assert current["cf"]["reason"] == "Instrument tape reads 55.25; cell was mistyped."
    assert current["cf"]["applied"] is True
    assert current["cf"]["actor_user_id"]
    assert vehicle["vehicle_id"] == complete_vehicle(
        vehicles_of(admin, "AAT", batch["file_hash"], load_id)
    )["vehicle_id"], "the vehicle id is stable across revalidation"

    # A second save of the same field is another row; the latest wins.
    fresh = review_of(engineer, load_id)
    again = post_override(admin, fresh, vehicle["vehicle_id"], [
        {"source_row": source_row, "field": "cf", "value": "55.30", "reason": "Re-read the tape."},
    ])
    assert again.status_code == 201, again.text
    assert count(admin_conn, "SELECT count(*) FROM review_override WHERE load_id = %s", load_id) == 3

    # Acknowledge at the new revision and commit: the overridden value lands.
    fresh = review_of(engineer, load_id)
    for category in ("REJECTED_ROWS", "QUARANTINED_MODELS", "DUPLICATE_ROWS"):
        assert acknowledge(admin, fresh, category).status_code == 201
    before = count(admin_conn, "SELECT count(*) FROM wavescan WHERE load_id = %s", load_id)
    committed = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert committed.status_code == 200, committed.text
    assert count(admin_conn, "SELECT count(*) FROM wavescan WHERE load_id = %s", load_id) == before + 1
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT cf::text, b FROM wavescan WHERE load_id = %s AND source_row = %s",
            (load_id, source_row),
        )
        cf, b_value = cur.fetchone()
    assert cf == "55.30"
    assert b_value is None
    assert count(
        admin_conn, "SELECT raw_cf FROM stg_raw WHERE load_id = %s AND source_row = %s",
        load_id, source_row,
    ) == raw_before

    # History names the override, attributed.
    actions = [e["action"] for e in history_of(admin, "AAT", batch["file_hash"])]
    assert actions.count("review.override") == 2
    assert actions[-1] == "batch.commit"

    # A committed sheet takes no more overrides.
    late = post_override(admin, review_of(engineer, load_id), vehicle["vehicle_id"], [
        {"source_row": source_row, "field": "cf", "value": "40", "reason": "Too late."},
    ])
    assert late.status_code == 409, late.text


def test_a_mapping_replay_keeps_applying_the_override(
    engineer, admin, admin_conn, cleanup, alias_cleanup
):
    unknown = f"P703 RAP {uuid.uuid4().hex[:6]}"
    alias_cleanup.append(unknown)
    rows = unique_rows(3)
    rows[0]["Model"] = unknown
    review = ingest_as(engineer, cleanup, "t21-replay.xlsx", make_workbook(rows))
    batch = review["batch"]
    load_id = batch["load_id"]
    assert batch["counts"]["rows_rejected"] == 1

    vehicle = complete_vehicle(vehicles_of(admin, "AAT", batch["file_hash"], load_id))
    points = points_of(admin, "AAT", batch["file_hash"], vehicle["vehicle_id"])["items"]
    target = points[-1]["source_row"]
    saved = post_override(admin, review, vehicle["vehicle_id"], [
        {"source_row": target, "field": "doi", "value": "80.125", "reason": "Gloss re-read."},
    ])
    assert saved.status_code == 201, saved.text
    overridden = review_of(engineer, load_id)
    assert acknowledge(admin, overridden, "REJECTED_ROWS").status_code == 201
    assert review_of(engineer, load_id)["committable"] is True

    proposal = engineer.post("/api/v1/mappings/proposals", json={
        "kind": "ALIAS_MODEL", "load_id": load_id,
        "payload": {"raw_value": unknown, "model_code": "U704"},
    })
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["status"] == "APPROVED"

    replayed = wait_for(engineer, load_id)
    assert replayed["batch"]["status"] == "PENDING_REVIEW"
    assert replayed["batch"]["counts"]["rows_rejected"] == 0
    assert replayed["batch"]["review_revision"] != overridden["batch"]["review_revision"]
    assert "WARNINGS_UNACKNOWLEDGED" not in replayed["commit_blockers"], (
        "no warning left to acknowledge"
    )
    assert count(admin_conn, "SELECT count(*) FROM review_override WHERE load_id = %s", load_id) == 1
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT canonical -> 'measures' ->> 'doi' FROM stg_review_row "
            "WHERE load_id = %s AND source_row = %s",
            (load_id, target),
        )
        assert cur.fetchone()[0] == "80.125", "the replay applied the current override"
        cur.execute(
            "SELECT count(*) FROM review_acknowledgement "
            "WHERE load_id = %s AND review_revision = %s",
            (load_id, replayed["batch"]["review_revision"]),
        )
        assert cur.fetchone()[0] == 0, "the old acknowledgement did not carry over"

    committed = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert committed.status_code == 200, committed.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT doi::text FROM wavescan WHERE load_id = %s AND source_row = %s",
            (load_id, target),
        )
        assert cur.fetchone()[0] == "80.125"


def test_a_replay_with_a_warning_left_needs_a_new_acknowledgement(
    engineer, admin, cleanup, alias_cleanup
):
    """Same flow, but a warning survives the replay: the ack from the
    override revision must not satisfy the gate at the replay revision."""
    first = f"P703 RAP {uuid.uuid4().hex[:6]}"
    second = f"P703 SVO {uuid.uuid4().hex[:6]}"
    alias_cleanup.extend([first, second])
    rows = unique_rows(4)
    rows[0]["Model"] = first
    rows[1]["Model"] = second
    review = ingest_as(engineer, cleanup, "t21-replay-ack.xlsx", make_workbook(rows))
    batch = review["batch"]
    load_id = batch["load_id"]
    vehicle = complete_vehicle(vehicles_of(admin, "AAT", batch["file_hash"], load_id))
    target = points_of(admin, "AAT", batch["file_hash"], vehicle["vehicle_id"])["items"][0]
    assert post_override(admin, review, vehicle["vehicle_id"], [
        {"source_row": target["source_row"], "field": "lw", "value": "4.5", "reason": "LW re-read."},
    ]).status_code == 201
    assert acknowledge(admin, review_of(engineer, load_id), "REJECTED_ROWS").status_code == 201

    proposal = engineer.post("/api/v1/mappings/proposals", json={
        "kind": "ALIAS_MODEL", "load_id": load_id,
        "payload": {"raw_value": first, "model_code": "U704"},
    })
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["status"] == "APPROVED"
    replayed = wait_for(engineer, load_id)
    assert replayed["batch"]["counts"]["rows_rejected"] == 1
    assert "WARNINGS_UNACKNOWLEDGED" in replayed["commit_blockers"]


# =====================================================================
# 5. abandon
# =====================================================================
def test_abandon_retains_everything_and_refuses_replay_and_commit(
    engineer, admin, admin_conn, pending_mixed, alias_cleanup
):
    review, vehicle, load_row, _ = pending_mixed
    batch = review["batch"]
    load_id = batch["load_id"]
    assert post_override(admin, review, vehicle["vehicle_id"], [
        {"source_row": load_row["source_row"], "field": "cf", "value": "50", "reason": "x-check"},
    ]).status_code == 201

    tables = ("stg_raw", "stg_review_row", "reject_log", "unidentified_model",
              "review_override", "review_acknowledgement")
    before = {t: count(admin_conn, f"SELECT count(*) FROM {t} WHERE load_id = %s", load_id)
              for t in tables}

    blank = admin.post(f"/api/v1/batches/{load_id}/abandon", json={"reason": "  "})
    assert blank.status_code == 422
    extra = admin.post(f"/api/v1/batches/{load_id}/abandon",
                       json={"reason": "x", "replacement_load_id": 1})
    assert extra.status_code == 422, "abandon takes { reason } only"

    done = abandon(admin, load_id, "Uploaded twice by mistake; the other copy is reviewed.")
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "ABANDONED"
    assert body["previous_status"] == "PENDING_REVIEW"
    assert body["audit_action"] == "batch.abandon"

    after = {t: count(admin_conn, f"SELECT count(*) FROM {t} WHERE load_id = %s", load_id)
             for t in tables}
    assert after == before, "nothing was deleted"
    assert count(admin_conn, "SELECT count(*) FROM wavescan WHERE load_id = %s", load_id) == 0
    assert admin.app.state.ingest_service.store.path_for(
        _raw_key(admin_conn, load_id)
    ).exists(), "the stored bytes are retained"

    events = [e for e in history_of(admin, "AAT", batch["file_hash"]) if e["action"] == "batch.abandon"]
    assert len(events) == 1 and events[0]["actor_user_id"]
    assert events[0]["after"]["reason"].startswith("Uploaded twice")

    # Still inspectable.
    assert vehicles_of(admin, "AAT", batch["file_hash"], load_id)["page"]["total"] == 3
    item = card(admin, "AAT", batch["file_hash"])
    assert item["operational_summary"] == "ABANDONED" and item["abandoned"] is True

    # Refused afterwards.
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 409
    assert abandon(admin, load_id).status_code == 409
    assert post_override(admin, review_of(engineer, load_id), vehicle["vehicle_id"], [
        {"source_row": load_row["source_row"], "field": "cf", "value": "51", "reason": "x"},
    ]).status_code == 409
    # Identity apply lands the alias even when the batch cannot replay
    # (spec A3). Replay is skipped; the sheet stays ABANDONED.
    raw_value = f"T21 {uuid.uuid4().hex[:6]}"
    # T76 CHANGE: the alias this test lands is removed afterwards (only that
    # row -- `alias_cleanup` deletes rows created during the test). Every run
    # used to leave one `T21 xxxxxx` -> U704 alias at AAT behind.
    alias_cleanup.append(raw_value)
    proposal = engineer.post("/api/v1/mappings/proposals", json={
        "kind": "ALIAS_MODEL", "load_id": load_id,
        "payload": {"raw_value": raw_value, "model_code": "U704"},
    })
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["status"] == "APPROVED"
    replay = admin.post(f"/api/v1/mappings/proposals/{proposal.json()['id']}/approve")
    assert replay.status_code == 409, replay.text
    assert count(
        admin_conn, "SELECT count(*) FROM ref_model_alias WHERE raw_value = %s", raw_value
    ) == 1, "the identity alias still lands when replay is skipped"
    assert review_of(engineer, load_id)["batch"]["status"] == "ABANDONED"


def _raw_key(admin_conn, load_id: int) -> str:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT raw_store_key FROM load_batch WHERE load_id = %s", (load_id,))
        return cur.fetchone()[0]


def test_abandon_refusals(engineer, admin, admin_conn, cleanup):
    committed = ingest_as(engineer, cleanup, "t21-abandon-c.xlsx", make_workbook(unique_rows(2)))
    load_id = committed["batch"]["load_id"]
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    refused = abandon(admin, load_id)
    assert refused.status_code == 409
    assert "supersede" in refused.json()["message"]
    facts = count(admin_conn, "SELECT count(*) FROM wavescan WHERE load_id = %s", load_id)
    assert facts == 2

    # Supersede is still { reason } and still works on the committed sheet.
    retired = admin.post(f"/api/v1/batches/{load_id}/supersede", json={"reason": "T21 retire."})
    assert retired.status_code == 200, retired.text
    assert abandon(admin, load_id).status_code == 409, "already retired"
    assert count(admin_conn, "SELECT count(*) FROM wavescan WHERE load_id = %s", load_id) == facts

    running, _ = owner_batch(admin_conn, cleanup, plant="AAT", status="RUNNING")
    assert abandon(admin, running).status_code == 409

    # Status says pending, rows say otherwise: the rows win.
    lying, _ = owner_batch(admin_conn, cleanup, plant="AAT", status="PENDING_REVIEW")
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wavescan (measured_date, plant, model, checkzone, color,
                tolerance_group, paintline, serial_no, lw, sw, cf, doi, du, wa, wb,
                wc, wd, we, b, load_id, source_sheet, source_row)
            SELECT measured_date, plant, model, checkzone, color, tolerance_group,
                   paintline, serial_no || '-t21', lw, sw, cf, doi, du, wa, wb, wc,
                   wd, we, b, %s, source_sheet, 2
              FROM wavescan WHERE load_id = %s LIMIT 1
            """,
            (lying, load_id),
        )
    assert abandon(admin, lying).status_code == 409
    assert count(admin_conn, "SELECT status FROM load_batch WHERE load_id = %s", lying) == "PENDING_REVIEW"
    assert count(admin_conn, "SELECT count(*) FROM wavescan WHERE load_id = %s", lying) == 1

    assert abandon(admin, 2**62).status_code == 404

    failed, _ = owner_batch(admin_conn, cleanup, plant="AAT", status="FAILED")
    assert abandon(admin, failed).status_code == 200
    rejected, _ = owner_batch(admin_conn, cleanup, plant="AAT", status="REJECTED_TEMPLATE")
    assert abandon(admin, rejected).status_code == 200


def test_the_ingest_service_never_writes_a_retired_status():
    source = (BACKEND_ROOT / "app" / "services" / "ingest.py").read_text(encoding="utf-8")
    for token in ("STATUS_ABANDONED", "'ABANDONED'", '"ABANDONED"',
                  "STATUS_SUPERSEDED", "'SUPERSEDED'", '"SUPERSEDED"'):
        assert token not in source, token


# =====================================================================
# 6. grants, contract, hygiene
# =====================================================================
@pytest.mark.parametrize("table", ["review_override", "wavescan", "review_acknowledgement"])
def test_the_application_role_cannot_update_or_delete(app_conn, table):
    column = {"review_override": "reason", "wavescan": "cf",
              "review_acknowledgement": "note"}[table]
    value = "'x'" if table != "wavescan" else "1"
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(f"UPDATE {table} SET {column} = {value}")
    app_conn.rollback()
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(f"DELETE FROM {table}")


def test_reset_batch_staging_does_not_touch_overrides(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_functiondef('reset_batch_staging(bigint)'::regprocedure)"
        )
        body = cur.fetchone()[0]
    assert "review_override" not in body
    assert "review_acknowledgement" not in body


def test_the_contract_has_the_four_t21_paths_and_both_artifacts_match(admin):
    spec = admin.get("/openapi.json").json()
    # T23 CHANGE: 27 -> 31. The four T21 paths below are unchanged.
    # T25 CHANGE: 31 -> 32 (POST /batches/{load_id}/restore).
    # T26 CHANGE: 32 -> 33 (POST /plants/{plant_code}/template-profiles/publish).
    # T-STANDARDS-D2 CHANGE: 33 -> 38.
    # Monthly Overview CHANGE: 38 -> 39.
    # T37 CHANGE: 39 -> 40 (POST /plants/{plant_code}/workbooks/{file_hash}/purge).
    # T39 CHANGE: 40 -> 46 (worksheet GET + five Engineer POSTs).
    # T48 CHANGE: 46 -> 49 (three FilmThickness GETs).
    # T62 CHANGE: 49 -> 51 (FilmThickness standards GET + Admin POST).
    # T66 CHANGE: 51 -> 52 (FilmThickness monthly overview GET).
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(spec["paths"]) >= 52
    root = "/api/v1/plants/{plant_code}/workbooks/{file_hash}"
    new = {
        f"{root}/vehicles": {"get"},
        f"{root}/vehicles/{{vehicle_id}}/points": {"get"},
        f"{root}/overrides": {"post"},
        "/api/v1/batches/{load_id}/abandon": {"post"},
    }
    for path, methods in new.items():
        assert set(spec["paths"][path]) == methods, path
    listing = {p["name"] for p in spec["paths"]["/api/v1/plants/{plant_code}/workbooks"]["get"]["parameters"]}
    assert {"inbox", "uploaded_month", "limit", "offset"} <= listing

    schemas = spec["components"]["schemas"]
    assert set(schemas["AbandonCreate"]["properties"]) == {"reason"}
    assert schemas["SupersedeCreate"]["required"] == ["reason"]
    assert "ABANDONED" in json.dumps(schemas["BatchOut"])
    assert set(schemas["WorkbookOut"]["properties"]) >= {
        "abandoned", "vehicle_set_count", "measured_dates_span_months", "superseded",
    }
    for forbidden in ("/api/v1/audit", "commit-all"):
        assert not any(forbidden in p for p in spec["paths"])

    backend = (BACKEND_ROOT / "openapi.json").read_bytes()
    docs = (REPO_ROOT / "docs" / "openapi.json").read_bytes()
    assert backend == docs


#: Files T21 created. Every line is checked.
T21_NEW_FILES = (
    "backend/app/repositories/overrides.py",
    "backend/migrations/versions/0008_t21_review_override_abandon.py",
    "backend/tests/test_t21_upload_review.py",
    "docs/reports/T21-UPLOAD-REVIEW.md",
)

#: Files T21 edited. Several already carried a section sign from earlier
#: tasks; what this task owns is the lines it added, so those are checked
#: against the committed version when git can show it.
T21_EDITED_FILES = (
    "backend/app/domain/workbooks.py",
    "backend/app/repositories/workbooks.py",
    "backend/app/repositories/corrections.py",
    "backend/app/repositories/batches.py",
    "backend/app/services/workbooks.py",
    "backend/app/services/corrections.py",
    "backend/app/services/ingest.py",
    "backend/app/schemas/workbooks.py",
    "backend/app/schemas/corrections.py",
    "backend/app/schemas/ingest.py",
    "backend/app/api/v1/workbooks.py",
    "backend/app/api/v1/batches.py",
    "backend/tests/test_t02_schema.py",
    "backend/tests/test_t03_contract.py",
    "backend/tests/test_t04_ingest.py",
    "backend/tests/test_t19_data_manager.py",
    "docs/01-DATA-MODEL.md",
    "docs/02-PIPELINE.md",
    "docs/03-SECURITY.md",
)


def _committed_lines(relative: str) -> set[str] | None:
    import subprocess

    try:
        shown = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=REPO_ROOT,
            capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return set(shown.stdout.decode("utf-8", "replace").splitlines())


def test_lines_this_task_adds_are_ascii():
    offenders = []
    for relative in T21_NEW_FILES + T21_EDITED_FILES:
        path = REPO_ROOT / relative
        if not path.exists():
            continue
        before = set() if relative in T21_NEW_FILES else _committed_lines(relative)
        if before is None:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line in before:
                continue
            if any(ord(ch) > 127 for ch in line):
                offenders.append(f"{relative}:{number}")
    assert not offenders, offenders
