"""T53 -- WaveScan polish: catch, junk-strip, plant-own panel, easy confirm.

Claims, against the cleaner and the worksheet helpers (no database) and the
running application, worker and database:

* A compact `01HOOD` never becomes `RRHOOD` through the global checkzone
  alias. It is held until a plant map, an exact zone code, or an Engineer's
  pick names the panel. `src_zone_text` stays `01HOOD`.
* AAT `01 RRHOOD` still loads (the label names the zone), and so does a
  documented source typo (`17 LTTailagte`).
* `[All]`, `(None)` and blank CF are held; the complete rows still load.
* U704 (31 zones) is not folded onto Ranger's 32; a leftover model never
  binds onto Ranger.
* The worksheet shows every row as ready / held out / already in History in
  plain words; an extra tab says "Extra tab kept. Not loaded."
* "Yes, load these rows" answers with the prototype toast, "N readings added
  to {month}", never a Duplicate/Load token.
* History points carry `panel_label`, the plant's own panel text.
* A viewer cannot load; `app_rw` still cannot DELETE from `wavescan`.

Every workbook here is built in the test.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import replace
from datetime import date

import pytest
from openpyxl import Workbook

from app.domain.cleaner import (
    Cleaner,
    CleanRow,
    Reject,
    RejectReason,
    label_names_zone,
)
from app.domain.reader import RawRow
from app.services.worksheet import (
    AGGREGATE_ROW_MESSAGE,
    EARLIER_FILE_MESSAGE,
    EXTRA_TAB_MESSAGE,
    IN_FILE_COPY_MESSAGE,
    month_words,
    preview_rows,
    summary_message,
    toast_message,
)
from tests.test_t04_domain import REFERENCE, make_raw
from tests.test_t04_ingest import BASE_ROW, forget_bytes, upload, wait_for
from tests.test_t04_ingest import cleanup  # noqa: F401

MEASURES = {m: 1.5 for m in ("lw", "sw", "cf", "du", "wa", "wb", "wc", "wd", "we")}

#: Tokens the uploader face must not lead with (D-53-12).
TOKENS = re.compile(r"\b(LOAD|DUPLICATE|REJECT|QUARANTINE|Duplicate|Quarantine)\b")

RANGER = "P703 DBL RANGER"
#: How the file spells it; REFERENCE maps `p703` onto Ranger.
P703 = "P703"
RANGER_ZONES = {
    ("P703 DBL RANGER", "RRHOOD"),
    ("P703 DBL RANGER", "LTTAILGATE"),
    ("P703 DBL RANGER", "LFFENDER"),
}

#: REFERENCE plus a Ranger catalogue, a global compact alias that must NOT be
#: honoured, and a documented source typo that must be.
REF = replace(
    REFERENCE,
    checkzone={
        **dict(REFERENCE.checkzone),
        "01hood": "RRHOOD",
        "25tgate": "LTTAILGATE",
        "17 lttailagte": "LTTAILGATE",
        "17 liftgate hi lh": "LIFTGATEHILH",
    },
    model={**dict(REFERENCE.model), "cx743": "CX743"},
    model_zone=frozenset(
        REFERENCE.model_zone
        | RANGER_ZONES
        | {("U704", "LIFTGATEHILH"), ("CX743", "1HOOD")}
    ),
    zone_names={"RRHOOD": "RR Hood", "LTTAILGATE": "LT Tailgate"},
    checkzone_documented=frozenset({"17 lttailagte"}),
    offered_models={
        **dict(REFERENCE.offered_models),
        ("FTM", "CX743"): True,
    },
)


def ftm(**kwargs) -> Cleaner:
    return Cleaner(REF, ("AAT", "FTM"), expected_plant="FTM", **kwargs)


def row(model: str, zone: str, **over) -> RawRow:
    values = dict(
        date="2026-09-08", plant="FTM", model=model, checkzone=zone,
        color="3HC Traction Green", serial_no="1", **MEASURES,
    )
    values.update(over)
    return make_raw(**values)


# =====================================================================
# A. the checkzone guard (D-53-09)
# =====================================================================
def test_label_names_zone_by_code_or_name_and_never_a_compact_relabel():
    assert label_names_zone("01 RRHOOD", "RRHOOD", "RR Hood")
    assert label_names_zone("06LFFENDER", "LFFENDER")
    assert label_names_zone("19Tailgate Middle14", "TGMIDDLE", "Tailgate Middle")
    assert label_names_zone("29 Fr Fen RH3", "FRFENRH3")
    for compact, code, name in (
        ("01HOOD", "RRHOOD", "RR Hood"),
        ("1HOOD", "RRHOOD", "RR Hood"),
        ("25TGATE", "LTTAILGATE", "LT Tailgate"),
    ):
        assert not label_names_zone(compact, code, name), compact


def test_compact_01hood_is_held_not_relabelled_rrhood_by_the_global_alias():
    out = ftm().clean_row(row(P703, "01HOOD"))
    assert isinstance(out, Reject), out
    assert out.reason == RejectReason.UNKNOWN_CHECKZONE
    assert out.value == "01HOOD"
    assert "Pick the panel" in out.detail

    tgate = ftm().clean_row(row(P703, "25TGATE"))
    assert isinstance(tgate, Reject) and tgate.reason == RejectReason.UNKNOWN_CHECKZONE


def test_a_plant_map_pick_resolves_01hood_and_keeps_the_plant_text():
    ref = replace(REF, plant_zone_map={("FTM", RANGER, "01hood"): "RRHOOD"})
    out = Cleaner(ref, ("AAT", "FTM"), expected_plant="FTM").clean_row(
        row(P703, "01HOOD")
    )
    assert isinstance(out, CleanRow), out
    assert out.checkzone == "RRHOOD"
    assert out.src_zone_text == "01HOOD"
    assert out.tolerance_group == "Horizontal"


def test_an_exact_zone_code_on_the_model_resolves_without_an_alias():
    out = ftm().clean_row(row(P703, "rrhood"))
    assert isinstance(out, CleanRow), out
    assert out.checkzone == "RRHOOD" and out.src_zone_text == "rrhood"


def test_aat_01_rrhood_still_loads_with_src_zone_text_preserved():
    out = ftm().clean_row(row(P703, "01 RRHOOD"))
    assert isinstance(out, CleanRow), out
    assert out.checkzone == "RRHOOD"
    assert out.src_zone_text == "01 RRHOOD"
    assert out.src_zone_no == 1


def test_a_documented_source_typo_still_loads_and_an_undocumented_one_holds():
    out = ftm().clean_row(row(P703, "17 LTTailagte"))
    assert isinstance(out, CleanRow), out
    assert out.checkzone == "LTTAILGATE" and out.src_zone_text == "17 LTTailagte"

    undocumented = replace(REF, checkzone_documented=frozenset())
    held = Cleaner(undocumented, ("AAT", "FTM"), expected_plant="FTM").clean_row(
        row(P703, "17 LTTailagte")
    )
    assert isinstance(held, Reject) and held.reason == RejectReason.UNKNOWN_CHECKZONE


def test_u704_is_not_folded_onto_ranger_and_ranger_names_do_not_fit_u704():
    u704 = ftm().clean_row(row("U704", "17 Liftgate Hi LH"))
    assert isinstance(u704, CleanRow), u704
    assert u704.model == "U704" and u704.checkzone == "LIFTGATEHILH"

    ranger_on_u704 = ftm().clean_row(row("U704", "17 LTTailagte"))
    assert isinstance(ranger_on_u704, Reject)
    assert ranger_on_u704.reason == RejectReason.ZONE_NOT_VALID_FOR_MODEL

    u704_on_ranger = ftm().clean_row(row(P703, "17 Liftgate Hi LH"))
    assert isinstance(u704_on_ranger, Reject)
    assert u704_on_ranger.reason == RejectReason.ZONE_NOT_VALID_FOR_MODEL


def test_a_leftover_model_never_binds_onto_ranger():
    out = ftm().clean_row(row("CX743", "1HOOD"))
    assert isinstance(out, CleanRow), out
    assert out.model == "CX743" and out.checkzone == "1HOOD"

    # Its compact label is never a Ranger panel either.
    onto_ranger = ftm().clean_row(row("CX743", "01HOOD"))
    assert isinstance(onto_ranger, Reject)
    assert onto_ranger.reason == RejectReason.UNKNOWN_CHECKZONE


def test_junk_rows_hold_and_complete_rows_still_load():
    rows = [
        row(P703, "01 RRHOOD"),
        row(P703, "01 RRHOOD", color="[All]"),
        row("(None)", "01 RRHOOD"),
        row(P703, "01 RRHOOD", cf=None),
        row(P703, ""),
    ]
    for i, raw in enumerate(rows, start=2):
        raw.source_row = i
    result = ftm().clean_all(rows)
    assert [r.source_row for r in result.clean] == [2]
    assert [a.source_row for a in result.aggregates] == [3]
    assert [u.source_row for u in result.unidentified] == [4]
    assert {(r.source_row, r.column) for r in result.rejects} == {
        (5, "cf"), (6, "checkzone"),
    }


# =====================================================================
# B. the confirm table and toast, as pure functions (D-53-12..15)
# =====================================================================
def _stored(source_row, disposition, *, reason=None, detail=None, canonical=None,
            checkzone="01HOOD"):
    return {
        "source_row": source_row, "disposition": disposition, "reason": reason,
        "detail": detail, "canonical": canonical or {},
        "raw": {"values": {
            "checkzone": checkzone, "model": "P703 DBL", "color": "Vapor Blue",
            "date": "2026-09-08T00:00:00",
        }},
    }


def test_preview_rows_speak_ready_held_out_and_already_in_history():
    clean = {"checkzone": "RRHOOD", "model": RANGER, "color": "Vapor Blue",
             "measured_date": "2026-09-08"}
    stored = [
        _stored(2, "LOAD", canonical=clean, checkzone="01 RRHOOD"),
        _stored(3, "LOAD", canonical=clean, checkzone="01 RRHOOD"),
        _stored(4, "DUPLICATE", reason="DUPLICATE_ROW", canonical=clean,
                detail="100% match - kept already loaded from x.xlsx [s] row 2"),
        _stored(5, "DUPLICATE", reason="DUPLICATE_ROW", canonical=clean,
                detail="100% match - kept x.xlsx [s] row 2"),
        _stored(6, "AGGREGATE_ROW", reason="AGGREGATE_ROW"),
        _stored(7, "REJECT", reason="UNKNOWN_CHECKZONE",
                canonical={"offending_column": "checkzone", "offending_value": "01HOOD"}),
        _stored(8, "REJECT", reason="MISSING_MEASUREMENT",
                canonical={"offending_column": "cf", "offending_value": None}),
        _stored(9, "QUARANTINE", reason="UNIDENTIFIED_MODEL",
                canonical={"raw_model": "(None)"}),
    ]
    table = preview_rows("PasteData", stored, {3}, plant="FTM")
    by_row = {r["source_row"]: r for r in table}

    assert by_row[2]["outcome"] == "ready"
    assert by_row[2]["panel_label"] == "01 RRHOOD" and by_row[2]["checkzone"] == "RRHOOD"
    assert by_row[2]["measured_date"] == date(2026, 9, 8)
    assert by_row[2]["date_text"] == "2026-09-08"
    assert by_row[3]["outcome"] == "already_in_history"
    assert by_row[4]["outcome"] == "already_in_history"
    assert by_row[4]["operator_message"] == EARLIER_FILE_MESSAGE
    assert by_row[5]["outcome"] == "held_out"
    assert by_row[5]["operator_message"] == IN_FILE_COPY_MESSAGE
    assert by_row[6]["operator_message"] == AGGREGATE_ROW_MESSAGE
    assert by_row[7]["outcome"] == "held_out"
    assert by_row[7]["panel_label"] == "01HOOD" and by_row[7]["checkzone"] is None
    assert "panel list at FTM" in by_row[7]["operator_message"]
    assert "CF is empty" in by_row[8]["operator_message"]
    assert "blank model" in by_row[9]["operator_message"]
    for item in table:
        assert not TOKENS.search(item["operator_message"]), item["operator_message"]
        item["operator_message"].encode("ascii")


def test_summary_and_toast_are_plain_sentences():
    assert summary_message(40, 2, 31) == (
        "40 readings ready to add, 2 held out, 31 already in History."
    )
    assert summary_message(1, 0, 0) == "1 reading ready to add."
    assert month_words(["2026-08", "2026-09"]) == "August 2026 and September 2026"
    toast = toast_message(40, ["2026-09"], 2, 31)
    assert toast == "40 readings added to September 2026, 2 held out, 31 already in History."
    assert toast_message(3, ["2026-09"], 0, 0) == "3 readings added to September 2026."
    assert toast_message(1, ["2026-09"], 0, 0, more=True) == (
        "1 more reading added to September 2026."
    )
    assert not TOKENS.search(toast)


# =====================================================================
# C. the running application
# =====================================================================
HEADERS = [
    "Date", "Month", "Year", "Plant", "Model", "Checkzone", "Color",
    "Tolerance Group", "Paintline", "Serial No",
    "LW", "SW", "CF", "DOI", "du", "Wa", "Wb", "Wc", "Wd", "We", "B",
]


@pytest.fixture(scope="module")
def ingest_apps(app_database_url: str):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.test_t04_ingest import _settings

    created = []

    def _make(**overrides):
        # Small pools: by this point of a full run the standing cluster's 60
        # slots are nearly spent by session-scoped clients of earlier modules.
        overrides = {"db_pool_size": 2, "db_pool_max_overflow": 1, **overrides}
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
    return ingest_apps(
        auth_dev_bypass_roles_raw="viewer", ingest_worker_enabled=False,
        db_pool_size=1, db_pool_max_overflow=0,
    )


def workbook(data_rows: list[dict], *, sheet: str = "PasteData",
             extra_tab: bool = True) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(HEADERS)
    for r in data_rows:
        merged = {**BASE_ROW, **r}
        ws.append([merged.get(h) for h in HEADERS])
    if extra_tab:
        notes = wb.create_sheet("Methods")
        notes.append(["How to measure"])
        notes.append(["Wipe the panel, then scan three times."])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def ws_url(plant: str, file_hash: str, tail: str = "worksheet") -> str:
    return f"/api/v1/plants/{plant}/workbooks/{file_hash}/{tail}"


def sent(engineer, cleanup, admin_conn, name: str, data: bytes) -> list[dict]:
    forget_bytes(admin_conn, data)
    response = upload(engineer, name, data, expected_plant="AAT")
    assert response.status_code == 202, response.text
    out = []
    for entry in response.json()["batches"]:
        cleanup.append(entry["load_id"])
        out.append(wait_for(engineer, entry["load_id"]))
    return out


@pytest.fixture()
def compact_global_alias(admin_conn):
    """A global `01HOOD` -> RRHOOD alias with no note, as the hazard looks."""
    raw = f"01HOOD{uuid.uuid4().hex[:4].upper()}"
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ref_checkzone_alias (raw_value, zone_code, note) "
            "VALUES (%s, 'RRHOOD', NULL)",
            (raw,),
        )
    try:
        yield raw
    finally:
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM ref_checkzone_alias WHERE raw_value = %s", (raw,))


@pytest.mark.ingest
def test_worksheet_table_load_toast_and_history_panel_label(
    engineer, viewer, cleanup, admin_conn, compact_global_alias
):
    day = f"2026-08-{(uuid.uuid4().int % 27) + 1:02d}"
    serial = f"T53-{uuid.uuid4().hex[:8]}"
    good = [
        {"Date": day, "Serial No": serial, "Checkzone": "01 RRHOOD", "CF": 61.0},
        {"Date": day, "Serial No": serial, "Checkzone": "06 LFFender", "CF": 62.0},
    ]
    junk = [
        {"Date": day, "Serial No": serial, "Checkzone": compact_global_alias, "CF": 63.0},
        {"Date": day, "Serial No": serial, "Checkzone": "02 RFHOOD", "Color": "[All]"},
        {"Date": day, "Serial No": serial, "Checkzone": "03 CFHOOD", "CF": None},
    ]
    data = workbook(good + junk)
    reviews = sent(engineer, cleanup, admin_conn, "t53-polish.xlsx", data)
    file_hash = reviews[0]["batch"]["file_hash"]

    sheet = engineer.get(ws_url("AAT", file_hash))
    assert sheet.status_code == 200, sheet.text
    body = sheet.json()
    tabs = {s["sheet"]: s for s in body["sheets"]}
    assert "Methods" not in tabs
    file = engineer.get(f"/api/v1/plants/AAT/workbooks/{file_hash}").json()["workbook"]
    assert file["skipped_sheet_count"] == 1
    assert file["skipped_sheets"][0]["source_sheet"] == "Methods"
    assert file["skipped_sheets"][0]["reason"]

    paste = tabs["PasteData"]
    by_row = {r["source_row"]: r for r in paste["rows"]}
    assert [by_row[i]["outcome"] for i in (2, 3)] == ["ready", "ready"]
    assert by_row[2]["panel_label"] == "01 RRHOOD" and by_row[2]["checkzone"] == "RRHOOD"
    compact = by_row[4]
    # T96 (D-96-1): the spelling leads with a number and names no canonical
    # panel of this model, so the row asks in the row instead of being
    # held silently. What T53 is about is unchanged -- the global alias
    # never resolves it, and nothing loads as RRHOOD.
    assert compact["outcome"] == "needs_confirmation"
    assert compact["panel_label"] == compact_global_alias
    assert compact["checkzone"] is None, "never silently RRHOOD"
    assert {by_row[5]["outcome"], by_row[6]["outcome"]} == {"held_out"}
    assert body["rows_ready"] == 2
    # Still three rows that do not load; one of them now asks in the row
    # rather than only being held (T96, D-96-1).
    assert body["summary_message"].startswith("2 readings ready to add, 2 held out")
    assert "does not say which panel it is" in body["summary_message"]
    for r in paste["rows"]:
        assert not TOKENS.search(r["operator_message"]), r
    assert not TOKENS.search(paste["operator_message"])

    assert viewer.post(ws_url("AAT", file_hash, "load-ready")).status_code == 403

    loaded = engineer.post(ws_url("AAT", file_hash, "load-ready"))
    assert loaded.status_code == 200, loaded.text
    result = loaded.json()
    month = date.fromisoformat(day).strftime("%B %Y")
    assert result["measurements_inserted"] == 2
    assert result["months"] == [day[:7]]
    assert result["operator_message"].startswith(f"2 readings added to {month}, 2 held out")
    assert not TOKENS.search(result["operator_message"])
    result["operator_message"].encode("ascii")
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM wavescan WHERE load_id = %s AND checkzone = 'RRHOOD'",
            (paste["load_id"],),
        )
        assert cur.fetchone()[0] == 1, "only the 01 RRHOOD row is RRHOOD"

    after = engineer.get(ws_url("AAT", file_hash)).json()
    done = {s["sheet"]: s for s in after["sheets"]}["PasteData"]
    assert done["rows_already_in_history"] == 2
    assert done["state"] == "loaded"

    # History shows the plant's own panel text beside the catalogue code.
    week = min((int(day[-2:]) - 1) // 7 + 1, 5)
    vehicles = engineer.get(
        "/api/v1/plants/AAT/history/vehicles",
        params={"month": day[:7], "week": week, "model": "U704",
                "color": "Traction Green", "limit": 200},
    )
    assert vehicles.status_code == 200, vehicles.text
    mine = [v for v in vehicles.json()["items"] if v["serial_no"] == serial]
    assert len(mine) == 1
    points = engineer.get(
        f"/api/v1/plants/AAT/history/vehicles/{mine[0]['vehicle_id']}/points"
    )
    assert points.status_code == 200, points.text
    # T94 (D-94-4): History's panel column is the stored POSITION -- the
    # long name -- not the file's spelling. "It always show the long name in
    # Measurement History because it should be show what we clean." The
    # plant's own words are still carried, beside it, as `src_zone_text`,
    # which is what T53 (D-53-09) wanted them for; they are simply never
    # shown as the position again.
    items = points.json()["items"]
    labels = {p["checkzone"]: p["panel_label"] for p in items}
    assert labels == {"RRHOOD": "RRHOOD", "LFFENDER": "LFFENDER"}
    spellings = {p["checkzone"]: p["src_zone_text"] for p in items}
    assert spellings == {"RRHOOD": "01 RRHOOD", "LFFENDER": "06 LFFender"}

    # The same readings in a new file are already in History, never twice.
    again = workbook(good, sheet="Resent", extra_tab=False)
    [review] = sent(engineer, cleanup, admin_conn, "t53-again.xlsx", again)
    resent = engineer.get(ws_url("AAT", review["batch"]["file_hash"])).json()
    outcomes = [r["outcome"] for r in resent["sheets"][0]["rows"]]
    assert outcomes == ["already_in_history", "already_in_history"]
    assert resent["rows_already_in_history"] == 2
    assert "2 already in History" in resent["summary_message"]

    # Same bytes again: the door still says 409.
    assert upload(engineer, "t53-polish.xlsx", data, expected_plant="AAT").status_code == 409


def test_app_rw_still_cannot_delete_from_wavescan(admin_conn, app_role: str):
    """T01, read from the catalog on the session's owner connection."""
    allowed = admin_conn.execute(
        "SELECT has_table_privilege(%s, 'wavescan', 'DELETE')", (app_role,)
    ).fetchone()[0]
    assert allowed is False
