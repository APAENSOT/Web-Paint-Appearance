"""T39 -- the uploader worksheet contract (ADR 0013).

Claims, each against the cleaner, or the running application, worker and
database:

* DOI, Paintline and Serial No are optional; a sheet with none of those
  columns parses and its complete rows load. CF is required; LW/SW load
  empty only after an Engineer approves the point.
* `AAT U704` on the AAT page is AAT. Another plant's name is held and asked
  about, never refused for the whole upload and never relabelled silently.
  Answering "another plant" cancels the upload; the hash is gone.
* A leftover program loads as itself (U704), never folded onto Ranger.
* An extra column blocks until an Engineer ignores it; two CF columns still
  block.
* A colour not on this plant's list is asked about with official names and
  no default; confirming an existing name offers it at the plant; a new name
  is still refused (Admin).
* Empty / `(None)` model is never teachable, and the good rows of the same
  sheet still load.
* "Yes, load these rows" loads every ready tab; a later answer INSERTs only
  the rows that became loadable -- no stored value is updated.
* `app_rw` still cannot DELETE from `wavescan` (T01).

Every workbook here is built in the test (headers + a few rows). The owner's
desktop files are read-only and only described, if present.
"""

from __future__ import annotations

from tests.conftest import delete_rows_created_since, row_keys
import io
import uuid
from pathlib import Path

import psycopg
import pytest
from openpyxl import Workbook

from app.domain.cleaner import Cleaner, CleanRow, Reject, RejectReason
from app.domain.reader import describe_sheet
from tests.test_t04_domain import REFERENCE, make_raw
from tests.test_t04_ingest import BASE_ROW, forget_bytes, on_base_row, upload, wait_for
from tests.test_t04_ingest import cleanup  # noqa: F401

pytestmark = pytest.mark.ingest


# Module-scoped on purpose (T39): the T04 client fixtures are session-scoped
# and every module that imports them keeps its own apps, pools and worker
# until the session ends. The standing cluster allows 60 connections, so this
# module releases its clients when it finishes instead.
@pytest.fixture(scope="module")
def ingest_apps(app_database_url: str):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.test_t04_ingest import _settings

    created = []

    def _make(**overrides):
        app = create_app(_settings(app_database_url, **overrides))
        client = TestClient(app)
        client.__enter__()
        created.append((client, app))
        return client

    yield _make
    for client, app in created:
        client.__exit__(None, None, None)
        app.state.database.dispose()


@pytest.fixture(scope="module")
def engineer(ingest_apps):
    return ingest_apps()


@pytest.fixture(scope="module")
def viewer(ingest_apps):
    return ingest_apps(auth_dev_bypass_roles_raw="viewer", ingest_worker_enabled=False)


@pytest.fixture(scope="module")
def admin(ingest_apps):
    return ingest_apps(auth_dev_bypass_roles_raw="admin", ingest_worker_enabled=False)

HEADERS = [
    "Date", "Month", "Year", "Plant", "Model", "Checkzone", "Color",
    "Tolerance Group", "Paintline", "Serial No",
    "LW", "SW", "CF", "DOI", "du", "Wa", "Wb", "Wc", "Wd", "We", "B",
]
#: The owner's instrument exports: no DOI, no Serial, no Paintline.
INSTRUMENT = [h for h in HEADERS if h not in ("DOI", "Serial No", "Paintline")]
ZONES = ["01 RRHOOD", "02 RFHOOD", "03 CFHOOD", "04 LFHOOD", "05 LRHOOD"]
DESKTOP = Path(__file__).resolve().parents[3]
OWNER_FILES = ("Wave scan U704_Sep26_W3.xlsx", "Wave scan P703_Sep26_W3.xlsx")


# =====================================================================
# helpers
# =====================================================================
def book(headers: list[str], rows: list[dict], sheet: str = "PasteData") -> bytes:
    """A workbook from header names; values are looked up by header name."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for row in rows:
        merged = on_base_row(row)
        ws.append([merged.get(h) for h in headers])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def rows(count: int, **over) -> list[dict]:
    """AAT U704 Traction Green rows for one fresh vehicle date."""
    day = f"2026-08-{(uuid.uuid4().int % 27) + 1:02d}"
    tag = uuid.uuid4().hex[:8]
    return [
        {"Date": day, "Checkzone": ZONES[i % len(ZONES)], "CF": 55.0 + i,
         "Serial No": f"T39-{tag}", **over}
        for i in range(count)
    ]


def sent(engineer, cleanup, admin_conn, name: str, data: bytes, plant: str = "AAT"):
    forget_bytes(admin_conn, data)
    response = upload(engineer, name, data, expected_plant=plant)
    assert response.status_code == 202, response.text
    out = []
    for entry in response.json()["batches"]:
        cleanup.append(entry["load_id"])
        out.append(wait_for(engineer, entry["load_id"]))
    return out


def ws_url(plant: str, file_hash: str, tail: str = "worksheet") -> str:
    return f"/api/v1/plants/{plant}/workbooks/{file_hash}/{tail}"


def facts(admin_conn, load_id: int) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT measurement_id, source_row, cf, lw, doi, serial_no, paintline, "
            "       plant, model, color, loaded_at "
            "  FROM wavescan WHERE load_id = %s ORDER BY source_row",
            (load_id,),
        )
        return cur.fetchall()


def hash_rows(admin_conn, file_hash: str) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM load_batch WHERE file_hash = %s", (file_hash,))
        return cur.fetchone()[0]


def aat() -> Cleaner:
    return Cleaner(REFERENCE, ("AAT", "FTM"), expected_plant="AAT")


MEASURES = {m: 1.5 for m in ("lw", "sw", "cf", "du", "wa", "wb", "wc", "wd", "we")}


# =====================================================================
# A. the cleaner and reader contract (no database)
# =====================================================================
def test_missing_doi_loads_and_doi_is_null():
    out = aat().clean_row(make_raw(
        date="2026-09-08", plant="AAT", model="U704", checkzone="01 RRHOOD",
        color="3HC Traction Green", paintline="BOOTH1", serial_no="1", **MEASURES,
    ))
    assert isinstance(out, CleanRow), out
    assert out.measures["doi"] is None


def test_blank_serial_and_paintline_load_null_at_aat():
    out = aat().clean_row(make_raw(
        date="2026-09-08", plant="AAT", model="U704", checkzone="01 RRHOOD",
        color="3HC Traction Green", paintline=None, serial_no="(None)", **MEASURES,
    ))
    assert isinstance(out, CleanRow), out
    assert out.serial_no is None and out.paintline is None


def test_an_unknown_nonblank_paintline_still_holds():
    out = aat().clean_row(make_raw(
        date="2026-09-08", plant="AAT", model="U704", checkzone="01 RRHOOD",
        color="3HC Traction Green", paintline="BOOTH 99 NOWHERE", serial_no="1",
        **MEASURES,
    ))
    assert isinstance(out, Reject)
    assert out.reason == RejectReason.UNKNOWN_PAINTLINE


def test_blank_cf_holds_and_blank_lw_holds_until_approved():
    no_cf = aat().clean_row(make_raw(
        date="2026-09-08", plant="AAT", model="U704", checkzone="01 RRHOOD",
        color="3HC Traction Green", serial_no="1",
        **{**MEASURES, "cf": None},
    ))
    assert isinstance(no_cf, Reject) and no_cf.column == "cf"

    raw = make_raw(
        date="2026-09-08", plant="AAT", model="U704", checkzone="01 RRHOOD",
        color="3HC Traction Green", serial_no="1", **{**MEASURES, "lw": None},
    )
    held = aat().clean_row(raw)
    assert isinstance(held, Reject) and held.column == "lw"
    approved = Cleaner(
        REFERENCE, ("AAT", "FTM"), expected_plant="AAT", hole_rows={raw.source_row}
    ).clean_row(raw)
    assert isinstance(approved, CleanRow) and approved.measures["lw"] is None
    # Approving holes never excuses a missing CF.
    no_cf_approved = Cleaner(
        REFERENCE, ("AAT", "FTM"), expected_plant="AAT", hole_rows={raw.source_row}
    ).clean_row(make_raw(
        date="2026-09-08", plant="AAT", model="U704", checkzone="01 RRHOOD",
        color="3HC Traction Green", serial_no="1", **{**MEASURES, "cf": None},
    ))
    assert isinstance(no_cf_approved, Reject)


def test_plant_prefix_is_the_page_plant_and_another_plant_is_asked():
    cleaner = aat()
    base = dict(date="2026-09-08", model="U704", checkzone="01 RRHOOD",
                color="3HC Traction Green", serial_no="1", **MEASURES)
    prefixed = cleaner.clean_row(make_raw(plant="AAT U704", **base))
    assert isinstance(prefixed, CleanRow) and prefixed.plant == "AAT"
    assert prefixed.plant_read_as == "prefix"

    for other in ("FTM", "U704", "FTM AAT"):
        out = cleaner.clean_row(make_raw(plant=other, **base))
        assert isinstance(out, Reject), other
        assert out.reason == RejectReason.PLANT_MISMATCH and out.value == other

    confirmed = Cleaner(
        REFERENCE, ("AAT", "FTM"), expected_plant="AAT", confirmed_plant_texts={"U704"}
    ).clean_row(make_raw(plant="U704", **base))
    assert isinstance(confirmed, CleanRow) and confirmed.plant == "AAT"
    assert confirmed.plant_read_as == "confirmed"


def test_a_leftover_u704_loads_as_u704_not_ranger():
    out = aat().clean_row(make_raw(
        date="2026-09-08", plant="AAT U704", model="U704", checkzone="01 RRHOOD",
        color="3HC Traction Green", **MEASURES,
    ))
    assert isinstance(out, CleanRow), out
    assert out.model == "U704"


def test_a_sheet_with_no_serial_paintline_or_doi_column_is_parseable():
    template = describe_sheet(
        book(INSTRUMENT, rows(1)), "PasteData",
        {**{h.lower(): h.lower() for h in ("Date", "Month", "Year", "Plant", "Model",
                                             "Checkzone", "Color", "LW", "SW", "CF",
                                             "du", "Wa", "Wb", "Wc", "Wd", "We", "B")},
         "tolerance group": "tolerance_group"},
    )
    assert template.missing_required == ()
    assert template.is_parseable


@pytest.mark.parametrize("name", OWNER_FILES)
def test_owner_workbooks_describe_as_wavescan_without_doi(name):
    """Read-only, and only if the owner's file is on this desk. Never copied."""
    path = DESKTOP / name
    if not path.exists():
        pytest.skip(f"{name} is not on this machine")
    from app.domain.reader import sheet_names

    data = path.read_bytes()
    alias = {
        "date": "date", "month": "month", "year": "year", "plant": "plant",
        "model": "model", "checkzone": "checkzone", "color": "color",
        "tolerance group": "tolerance_group", "paintline": "paintline",
        "serial no": "serial_no", "lw": "lw", "sw": "sw", "cf": "cf",
        "doi": "doi", "du": "du", "wa": "wa", "wb": "wb", "wc": "wc",
        "wd": "wd", "we": "we", "b": "b",
    }
    wavescan = [
        t for t in (describe_sheet(data, s, alias) for s in sheet_names(data))
        if t.sheet_class == "WAVESCAN"
    ]
    assert wavescan, "at least one WaveScan tab"
    for template in wavescan:
        assert "serial_no" not in template.missing_required
        assert "doi" not in set(template.recognised.values())


# =====================================================================
# B. upload: plant prefix, optional columns, the plant question
# =====================================================================
def test_an_instrument_sheet_with_aat_u704_and_no_doi_loads(
    engineer, cleanup, admin_conn
):
    """The U704 owner shape: Plant `AAT U704`, no DOI / Serial / Paintline."""
    data = book(INSTRUMENT, rows(3, Plant="AAT U704", Model="U704"))
    [review] = sent(engineer, cleanup, admin_conn, "t39-u704.xlsx", data)
    counts = review["batch"]["counts"]
    # The layout may be one no profile has approved yet (Admin publish). Either
    # it parsed and all three load, or it is waiting on the layout -- never a
    # plant refusal and never a missing-serial refusal.
    if review["batch"]["status"] == "PENDING_REVIEW":
        assert counts["rows_loaded"] == 3, review["reject_reasons"]
        assert "VEHICLE_IDENTITY_MISSING" not in review["commit_blockers"]
        assert "PAINTLINE_MISSING" not in review["commit_blockers"]
    else:
        assert review["batch"]["status"] == "REJECTED_TEMPLATE"
        assert "serial_no" not in (review["batch"]["notes"] or "")


def test_blank_paintline_and_serial_and_no_doi_load_at_aat(
    engineer, admin, cleanup, admin_conn
):
    """Same verified layout as T04, with blank cells instead of absent columns."""
    data = book(HEADERS, rows(3, Paintline=None, **{"Serial No": None, "DOI": None}))
    [review] = sent(engineer, cleanup, admin_conn, "t39-blanks.xlsx", data)
    assert review["batch"]["counts"]["rows_loaded"] == 3, review["reject_reasons"]
    file_hash = review["batch"]["file_hash"]
    loaded = admin.post(ws_url("AAT", file_hash, "load-ready"))
    assert loaded.status_code == 200, loaded.text
    stored = facts(admin_conn, review["batch"]["load_id"])
    assert len(stored) == 3
    assert {(r[4], r[5], r[6]) for r in stored} == {(None, None, None)}, (
        "DOI, serial and paintline are NULL -- nothing invented"
    )


def test_another_plant_is_asked_page_plant_answer_loads_it(
    engineer, cleanup, admin_conn
):
    data = book(HEADERS, rows(2, Plant="FTM"))
    [review] = sent(engineer, cleanup, admin_conn, "t39-ask.xlsx", data)
    file_hash = review["batch"]["file_hash"]
    assert review["reject_reasons"] == {"PLANT_MISMATCH": 2}

    sheet = engineer.get(ws_url("AAT", file_hash)).json()
    assert sheet["plant_question"]["page_plant"] == "AAT"
    assert sheet["plant_question"]["plant_texts"] == ["FTM"]
    assert "AAT" in sheet["plant_question"]["operator_message"]
    assert sheet["sheets"][0]["state"] == "needs_answer"

    answered = engineer.post(ws_url("AAT", file_hash, "plant-answer"), json={"plant_code": "AAT"})
    assert answered.status_code == 200, answered.text
    assert answered.json()["answer"] == "page_plant"
    assert answered.json()["replayed_load_ids"] == [review["batch"]["load_id"]]
    again = wait_for(engineer, review["batch"]["load_id"])
    assert again["batch"]["counts"]["rows_loaded"] == 2
    assert engineer.get(ws_url("AAT", file_hash)).json()["plant_question"] is None


def test_answering_another_plant_cancels_and_frees_the_hash(
    engineer, cleanup, admin_conn
):
    data = book(HEADERS, rows(2, Plant="FTM"))
    [review] = sent(engineer, cleanup, admin_conn, "t39-cancel.xlsx", data)
    file_hash = review["batch"]["file_hash"]

    answered = engineer.post(ws_url("AAT", file_hash, "plant-answer"), json={"plant_code": "FTM"})
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["cancelled"] is True and body["open_plant"] == "FTM"
    assert "FTM" in body["operator_message"]
    assert hash_rows(admin_conn, file_hash) == 0
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_event WHERE action = 'workbook.purge' "
            "AND entity_id = %s",
            (f"AAT:{file_hash}",),
        )
        assert cur.fetchone()[0] == 1

    resent = upload(engineer, "t39-cancel.xlsx", data, expected_plant="FTM")
    assert resent.status_code == 202, resent.text
    for entry in resent.json()["batches"]:
        cleanup.append(entry["load_id"])
        wait_for(engineer, entry["load_id"])


def test_a_viewer_cannot_read_or_answer_the_worksheet(viewer, engineer, cleanup, admin_conn):
    [review] = sent(engineer, cleanup, admin_conn, "t39-viewer.xlsx", book(HEADERS, rows(1)))
    file_hash = review["batch"]["file_hash"]
    assert viewer.get(ws_url("AAT", file_hash)).status_code == 403
    assert viewer.post(ws_url("AAT", file_hash, "load-ready")).status_code == 403
    assert engineer.get(ws_url("AAT", "0" * 64)).status_code == 404


# =====================================================================
# C. extra columns, duplicate columns
# =====================================================================
def test_an_extra_column_blocks_until_the_engineer_ignores_it(
    engineer, cleanup, admin_conn
):
    extra = f"Operator Note {uuid.uuid4().hex[:6]}"
    data = book(HEADERS + [extra], rows(2, **{extra: "ok"}))
    [review] = sent(engineer, cleanup, admin_conn, "t39-extra.xlsx", data)
    file_hash = review["batch"]["file_hash"]
    assert "UNREVIEWED_HEADER" in review["commit_blockers"]

    sheet = engineer.get(ws_url("AAT", file_hash)).json()
    assert sheet["extra_columns"] == [extra.lower()]
    header = [h for h in sheet["sheets"][0]["held"] if h["reason"] == "UNREVIEWED_HEADER"]
    assert header and "We do not use the column" in header[0]["operator_message"]

    refused = engineer.post(ws_url("AAT", file_hash, "ignore-columns"), json={"headers": ["CF"]})
    assert refused.status_code == 422, "a column we need cannot be ignored"

    ignored = engineer.post(ws_url("AAT", file_hash, "ignore-columns"), json={"headers": [extra]})
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["replayed_load_ids"] == [review["batch"]["load_id"]]
    after = wait_for(engineer, review["batch"]["load_id"])
    assert "UNREVIEWED_HEADER" not in after["commit_blockers"]
    assert after["batch"]["counts"]["rows_loaded"] == 2
    assert after["batch"]["status"] == "PENDING_REVIEW", "ignoring never commits"


def test_two_cf_columns_still_block(engineer, cleanup, admin_conn):
    wb = Workbook()
    ws = wb.active
    ws.title = "PasteData"
    ws.append(HEADERS + ["CF"])
    for row in rows(2):
        merged = {**BASE_ROW, **row}
        ws.append([merged.get(h) for h in HEADERS] + [99.0])
    buffer = io.BytesIO()
    wb.save(buffer)
    [review] = sent(engineer, cleanup, admin_conn, "t39-two-cf.xlsx", buffer.getvalue())
    assert review["batch"]["status"] == "REJECTED_TEMPLATE"
    file_hash = review["batch"]["file_hash"]
    # Ignoring "CF" by name drops both columns, so the sheet still cannot be
    # read: nothing silently picks the first CF.
    engineer.post(ws_url("AAT", file_hash, "ignore-columns"), json={"headers": ["CF"]})
    after = wait_for(engineer, review["batch"]["load_id"])
    assert after["batch"]["status"] == "REJECTED_TEMPLATE"
    assert facts(admin_conn, review["batch"]["load_id"]) == []


# =====================================================================
# D. held rows: empty identity, colour not offered, LW/SW holes
# =====================================================================
def test_empty_model_is_never_teachable_and_the_good_rows_still_load(
    engineer, cleanup, admin_conn
):
    good = rows(2)
    bad = [{**good[0], "Model": "(None)", "Checkzone": "03 CFHOOD"}]
    [review] = sent(engineer, cleanup, admin_conn, "t39-none.xlsx", book(HEADERS, good + bad))
    assert review["batch"]["counts"]["rows_loaded"] == 2
    held = [h for h in review["held_labels"] if h["column"] == "model"]
    assert held and held[0]["teachable_kind"] is None
    assert held[0]["display_group"] == "empty_identity"
    assert held[0]["candidates"] == []


def test_colour_not_offered_is_asked_and_confirming_offers_it(
    engineer, admin, cleanup, admin_conn
):
    """G9Z-shaped: an official colour AAT does not list. No default.

    T64 CHANGE: Absolute Black is now offered at AAT as "Absolute / Shadow
    Black" (ADR 0014), so the un-offered official colour is Agate Black (SAP
    only; AAT has no row for it, so the cleanup below removes only what this
    test created).
    """
    raw = "DM Agate Black"
    # T76 CHANGE: snapshot, so the cleanup removes only what this test made
    # (an owner's AAT Agate Black offer or alias would stay).
    alias_before = row_keys(admin_conn, "ref_color_alias", "alias_id")
    offer_before = row_keys(
        admin_conn, "ref_plant_color", "plant_code || ':' || color_name"
    )
    [review] = sent(
        engineer, cleanup, admin_conn, "t39-g9z.xlsx", book(HEADERS, rows(2, Color=raw))
    )
    load_id = review["batch"]["load_id"]
    assert review["reject_reasons"] == {"COLOR_NOT_OFFERED": 2}
    [held] = [h for h in review["held_labels"] if h["reason"] == "COLOR_NOT_OFFERED"]
    assert held["teachable_kind"] == "ALIAS_COLOR"
    assert "Agate Black" in held["candidates"]  # T64 CHANGE
    assert not {"Absolute Black", "Shadow Black"} & set(held["candidates"])  # T64: merged
    assert held["candidates"] == sorted(held["candidates"]), "asked, no default first"

    new_name = engineer.post("/api/v1/mappings/proposals", json={
        "kind": "ALIAS_COLOR", "load_id": load_id,
        "payload": {"raw_value": raw, "color_name": f"Brand New {uuid.uuid4().hex[:4]}",
                    "plant_code": "AAT"},
    })
    assert new_name.status_code in (409, 422), "a new colour name is Admin's"

    try:
        taught = engineer.post("/api/v1/mappings/proposals", json={
            "kind": "ALIAS_COLOR", "load_id": load_id,
            "payload": {"raw_value": raw, "color_name": "Agate Black",  # T64 CHANGE
                        "plant_code": "AAT"},
        })
        assert taught.status_code == 201, taught.text
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT is_offered, family_name FROM ref_plant_color "
                "WHERE plant_code = 'AAT' AND color_name = 'Agate Black'"  # T64 CHANGE
            )
            assert cur.fetchone() == (True, None), "offered, family left to D2"
            cur.execute(
                "SELECT count(*) FROM audit_event WHERE action = "
                "'catalogue.plant_color.offer' AND entity_id = 'AAT:Agate Black'"  # T64 CHANGE
            )
            assert cur.fetchone()[0] >= 1
        after = wait_for(engineer, load_id)
        assert after["batch"]["counts"]["rows_loaded"] == 2
    finally:
        delete_rows_created_since(
            admin_conn, "ref_color_alias", "alias_id", alias_before,
            "plant_code = 'AAT' AND raw_value = %s", (raw,),
        )
        delete_rows_created_since(
            admin_conn, "ref_plant_color", "plant_code || ':' || color_name",
            offer_before, "plant_code = 'AAT' AND color_name = 'Agate Black'",
        )


def test_lw_holes_hold_until_the_engineer_approves_them(engineer, cleanup, admin_conn):
    good = rows(2)
    hole = [{**good[0], "Checkzone": "03 CFHOOD", "LW": None}]
    [review] = sent(engineer, cleanup, admin_conn, "t39-hole.xlsx", book(HEADERS, good + hole))
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert review["batch"]["counts"]["rows_loaded"] == 2
    sheet = engineer.get(ws_url("AAT", file_hash)).json()["sheets"][0]
    assert sheet["hole_rows"] == [4]
    measure = [h for h in sheet["held"] if h["display_group"] == "measure"]
    assert measure and "approve" in measure[0]["operator_message"].lower()
    # T98 (D-98-1): the sentence names what is actually empty -- here LW alone.
    assert measure[0]["operator_message"].startswith("LW is empty")

    wrong = engineer.post(ws_url("AAT", file_hash, "hole-approval"),
                          json={"load_id": load_id, "source_rows": [2]})
    assert wrong.status_code == 422
    ok = engineer.post(ws_url("AAT", file_hash, "hole-approval"),
                       json={"load_id": load_id, "source_rows": [4]})
    assert ok.status_code == 200, ok.text
    after = wait_for(engineer, load_id)
    assert after["batch"]["counts"]["rows_loaded"] == 3



def test_a_point_short_of_cf_names_cf_and_is_offered_no_hole_button(
    engineer, cleanup, admin_conn
):
    """T98 (D-98-1): the owner's July row 104 -- only `du`, nothing else.

    It used to be counted as an LW/SW hole and the screen said "LW is empty
    ... approve loading them without LW/SW", offering a button that still
    refused the row, because nothing loads without CF (D-97-6, unchanged).
    """
    good = rows(2)
    blind = [{**good[0], "Checkzone": "03 CFHOOD",
              "LW": None, "SW": None, "CF": None, "du": 43.7}]
    [review] = sent(
        engineer, cleanup, admin_conn, "t98-no-cf.xlsx", book(HEADERS, good + blind)
    )
    file_hash = review["batch"]["file_hash"]
    sheet = engineer.get(ws_url("AAT", file_hash)).json()["sheets"][0]

    assert sheet["hole_rows"] == [], "no button: approving it would still refuse"
    [measure] = [h for h in sheet["held"] if h["display_group"] == "measure"]
    message = measure["operator_message"]
    assert message.startswith("LW, SW and CF are empty")
    assert "cannot load" in message and "without CF" in message
    assert "approve" not in message.lower()

# =====================================================================
# E. Yes-load and the second INSERT pass
# =====================================================================
def test_yes_loads_ready_rows_and_a_later_answer_inserts_only_the_rest(
    engineer, cleanup, admin_conn
):
    good = rows(2)
    hole = [{**good[0], "Checkzone": "03 CFHOOD", "LW": None, "CF": 71.25}]
    [review] = sent(engineer, cleanup, admin_conn, "t39-second.xlsx", book(HEADERS, good + hole))
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]

    yes = engineer.post(ws_url("AAT", file_hash, "load-ready"))
    assert yes.status_code == 200, yes.text
    assert yes.json()["measurements_inserted"] == 2
    first = facts(admin_conn, load_id)
    assert [r[1] for r in first] == [2, 3]

    nothing = engineer.post(ws_url("AAT", file_hash, "load-remaining"))
    assert nothing.status_code == 200
    assert nothing.json()["measurements_inserted"] == 0

    approved = engineer.post(ws_url("AAT", file_hash, "hole-approval"),
                             json={"load_id": load_id, "source_rows": [4]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["replayed_load_ids"] == [], "a committed tab is not replayed"

    more = engineer.post(ws_url("AAT", file_hash, "load-remaining"))
    assert more.status_code == 200, more.text
    assert more.json()["measurements_inserted"] == 1
    second = facts(admin_conn, load_id)
    assert len(second) == 3
    assert second[:2] == first, "no stored measurement was updated"
    assert second[2][1] == 4 and second[2][3] is None and str(second[2][2]) == "71.25"

    again = engineer.post(ws_url("AAT", file_hash, "load-remaining"))
    assert again.json()["measurements_inserted"] == 0, "INSERT only, never twice"
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT rows_in_file, rows_loaded, rows_rejected FROM load_batch "
            "WHERE load_id = %s", (load_id,),
        )
        assert cur.fetchone() == (3, 3, 0), "the counts still balance"
        cur.execute(
            "SELECT count(*) FROM audit_event WHERE action = 'batch.insert_remaining' "
            "AND entity_id = %s", (str(load_id),),
        )
        assert cur.fetchone()[0] >= 2
    sheet = engineer.get(ws_url("AAT", file_hash)).json()["sheets"][0]
    assert sheet["state"] == "loaded" and sheet["rows_held"] == 0


def test_yes_with_nothing_ready_is_refused(engineer, cleanup, admin_conn):
    data = book(HEADERS, rows(2, Plant="FTM"))
    [review] = sent(engineer, cleanup, admin_conn, "t39-noready.xlsx", data)
    refused = engineer.post(ws_url("AAT", review["batch"]["file_hash"], "load-ready"))
    assert refused.status_code == 409
    assert facts(admin_conn, review["batch"]["load_id"]) == []


# =====================================================================
# F. T01 still holds
# =====================================================================
@pytest.mark.parametrize("table", ["wavescan", "load_batch", "worksheet_decision"])
def test_app_rw_still_cannot_delete(app_conn, table):
    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(f"DELETE FROM {table}")


def test_app_rw_cannot_update_a_decision_or_a_measurement(app_conn):
    for sql in (
        "UPDATE worksheet_decision SET subject = 'x'",
        "UPDATE wavescan SET cf = cf",
    ):
        with app_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(sql)
        app_conn.rollback()


# =====================================================================
# G. contract
# =====================================================================
def test_openapi_publishes_the_worksheet_routes(viewer):
    spec = viewer.get("/openapi.json").json()
    base = "/api/v1/plants/{plant_code}/workbooks/{file_hash}/"
    assert set(spec["paths"][base + "worksheet"]) == {"get"}
    for tail in ("ignore-columns", "plant-answer", "hole-approval", "load-ready",
                 "load-remaining"):
        assert set(spec["paths"][base + tail]) == {"post"}, tail
    schemas = spec["components"]["schemas"]
    assert {"WorksheetOut", "WorksheetSheetOut", "PlantQuestion", "DecisionResult",
            "PlantAnswerResult", "WorkbookLoadResult"} <= set(schemas)
    groups = schemas["HeldLabelGroup"]["properties"]["display_group"]["enum"]
    assert {"plant", "measure"} <= set(groups)
