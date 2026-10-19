"""RO08 -- the review screen says the real reason a tab cannot load.

Claims, against the running application and the standing database:

* A tab whose every reading is already in History reads ``blocked`` with
  "Every reading of this tab is already in History (N) ..." -- not "waiting
  for an Admin" (D-RO08-1).
* A Film tab refused for a missing required field names it: the July shape
  (no date anywhere) gets the date sentence, a tab with no colour gets its
  own word (D-RO08-2).
* A layout really waiting on an Admin (T18's unverified profile) still says
  so (D-RO08-3), and the WaveScan T42 missing-column sentence is unchanged.

Every row is made by the test that asserts on it and removed afterwards
(``film_cleanup`` / ``cleanup``; T18's ``owned_profile`` removes its own
profile row). No shared reference or seed row is written.
"""

from __future__ import annotations

import io
import uuid

import pytest
from openpyxl import Workbook

from app.services.worksheet import film_missing_message
from tests.test_t04_ingest import forget_bytes, unique_rows, upload, wait_for
from tests.test_t04_ingest import admin, cleanup, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t18_profiles import ingest_as, signature_of
from tests.test_t18_profiles import owned_profile, reordered  # noqa: F401  (fixtures)
from tests.test_t18_profiles import workbook as t18_workbook
from tests.test_t26_semantic_clean_layer import HEADERS, _rows, sheet_bytes
from tests.test_t46_filmthickness import film_cleanup, sent  # noqa: F401
from tests.test_t54_filmthickness_polish import FTM_GOLD, desert_island, old_day, ws_url

pytestmark = pytest.mark.ingest

ADMIN_WAIT = "This tab cannot load yet: its layout is waiting for an Admin to approve it."
DATE_SENTENCE = (
    'This tab has no date: no Date column, no "Date:" line and no date in its '
    "banner, so it cannot load. Upload a version that has the date."
)
COLOR_SENTENCE = (
    'This tab has no color: no Color column, no "Layer 2:" line and no color in '
    "its banner, so it cannot load. Upload a version that has the color."
)

#: The owner's July AAT Film layout (`AAT Thickness Jul2026.xlsx`): no Date
#: column, no PELT `Date:` line, no EC1 banner.
JULY = ["Checkzone", "Clearcoat", "Basecoat2", "Basecoat1", "E-coat", "Orientation", "Color"]


def july_shaped(headers: list[str]) -> bytes:
    """A July-shaped AAT Film tab, values looked up by header."""
    tag = uuid.uuid4().hex[:8]
    values = {"Clearcoat": 40.1, "Basecoat2": 10.2, "Basecoat1": 8.3, "E-coat": 20.4,
              "Orientation": "H", "Color": "Command Grey", "Date": "2026-07-10"}
    wb = Workbook()
    ws = wb.active
    ws.title = f"RO08-{tag}"
    ws.append(headers)
    for loc in ("001HOOD", "002HOOD", "003HOOD"):
        ws.append([loc if h == "Checkzone" else values.get(h) for h in headers])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def only_tab(engineer, plant: str, review: dict) -> dict:
    body = engineer.get(ws_url(plant, review["batch"]["file_hash"])).json()
    [tab] = [s for s in body["sheets"] if s["load_id"] == review["batch"]["load_id"]]
    return tab


# =====================================================================
# A. the sentences (no database)
# =====================================================================
def test_each_missing_film_field_has_its_own_word():
    assert film_missing_message(["date"]) == DATE_SENTENCE
    assert film_missing_message(["color"]) == COLOR_SENTENCE
    assert film_missing_message(["location"]).startswith(
        "This tab has no location: no Location or Checkzone column, so it cannot load.")
    assert film_missing_message(["layer"]).startswith("This tab has no layer: ")
    assert film_missing_message(["date", "color"]) == (
        "This tab has no date or color, so it cannot load. Upload a version that has them."
    )
    for fields in (["date"], ["color"], ["location"], ["layer"], ["date", "color"]):
        assert "Admin" not in film_missing_message(fields)


# =====================================================================
# B. D-RO08-1: every reading already in History
# =====================================================================
def test_a_tab_whose_every_reading_is_in_history_says_so(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    day, _ = old_day()
    job = f"IB_RB_{uuid.uuid4().int % 10**7:07d}"
    first = sent(engineer, film_cleanup, admin_conn, f"RO08 {job} first.xlsx",
                 desert_island(FTM_GOLD[:3], day=day, job=job), "FTM")["Quick Summary"]
    loaded = engineer.post(ws_url("FTM", first["batch"]["file_hash"], "load-ready"))
    assert loaded.status_code == 200, loaded.text

    # The same car again, in different bytes: two of its points.
    again = sent(engineer, film_cleanup, admin_conn, f"RO08 {job} again.xlsx",
                 desert_island(FTM_GOLD[:2], day=day, job=job), "FTM")["Quick Summary"]
    assert again["batch"]["file_hash"] != first["batch"]["file_hash"]
    tab = only_tab(engineer, "FTM", again)
    assert (tab["status"], tab["rows_ready"], tab["rows_held"]) == ("PENDING_REVIEW", 0, 0)
    assert tab["rows_already_in_history"] == 2
    assert tab["state"] == "blocked"
    assert tab["operator_message"] == (
        "Every reading of this tab is already in History (2), so there is nothing "
        "new to add. Nothing is wrong with the file."
    )


# =====================================================================
# C. D-RO08-2: a Film tab missing a required field
# =====================================================================
def test_a_july_shaped_film_tab_with_no_date_asks_which_month(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    # RO18 (B4, RO09): no longer refused -- the tab asks one question, which month.
    review = next(iter(sent(engineer, film_cleanup, admin_conn, "RO08 July shape.xlsx",
                            july_shaped(JULY), "AAT").values()))
    assert review["batch"]["status"] == "PENDING_REVIEW"
    assert review["batch"]["sheet_class"] == "FILMTHICKNESS"
    tab = only_tab(engineer, "AAT", review)
    # This tab names no model, so that question is asked first; the month next.
    assert tab["state"] == "needs_answer"
    assert tab["operator_message"] != DATE_SENTENCE


def test_a_film_tab_with_no_colour_names_the_colour(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    headers = [h for h in JULY if h != "Color"] + ["Date"]
    review = next(iter(sent(engineer, film_cleanup, admin_conn, "RO08 no colour.xlsx",
                            july_shaped(headers), "AAT").values()))
    assert review["batch"]["status"] == "REJECTED_TEMPLATE"
    assert review["batch"]["sheet_class"] == "FILMTHICKNESS"
    tab = only_tab(engineer, "AAT", review)
    assert tab["state"] == "blocked"
    assert tab["operator_message"] == COLOR_SENTENCE


# =====================================================================
# C2. RO08-FIX (D-RO08F-2): a tab held only by an answerable label
# =====================================================================
ANSWER = "Answer the questions for this tab first."


def test_a_film_tab_held_only_by_an_unknown_colour_asks_the_question(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    day, _ = old_day()
    job = f"IB_RB_{uuid.uuid4().int % 10**7:07d}"
    spelling = f"RO08F Blue {uuid.uuid4().hex[:6]}"
    review = sent(engineer, film_cleanup, admin_conn, f"RO08F {job} colour.xlsx",
                  desert_island(FTM_GOLD[:3], day=day, job=job, colour=spelling),
                  "FTM")["Quick Summary"]
    tab = only_tab(engineer, "FTM", review)
    assert (tab["status"], tab["rows_ready"]) == ("PENDING_REVIEW", 0)
    assert {(g["reason"], g["raw_value"], g["teachable_kind"]) for g in tab["held"]} == {
        ("UNKNOWN_COLOR", spelling, "ALIAS_COLOR")}
    assert (tab["state"], tab["operator_message"]) == ("needs_answer", ANSWER)


def test_a_film_tab_held_only_by_its_model_asks_the_question(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    # The P704 shape: neither the file name nor the tab names an AAT Film model.
    day, _ = old_day()
    car = f"{uuid.uuid4().int % 10**7:07d}"
    review = sent(engineer, film_cleanup, admin_conn, f"{car} P704 A4D.xlsx",
                  desert_island(["001HOOD", "002HOOD"], day=day, job=f"{car} P704 A4"),
                  "AAT")["Quick Summary"]
    tab = only_tab(engineer, "AAT", review)
    assert (tab["status"], tab["rows_ready"]) == ("PENDING_REVIEW", 0)
    assert {(g["reason"], g["teachable_kind"]) for g in tab["held"]} == {
        ("FILM_MODEL_UNRESOLVED", "FILM_MODEL")}
    assert (tab["state"], tab["operator_message"]) == ("needs_answer", ANSWER)


# =====================================================================
# D. D-RO08-3 and T42: the other blocked sentences are unchanged
# =====================================================================
def test_a_layout_really_waiting_on_an_admin_still_says_so(
    engineer, admin_conn, cleanup, owned_profile, reordered  # noqa: F811
):
    # T18's layout: a profile exists for it but no Admin has verified it, so
    # it parses and only an Admin can let it commit.
    data = t18_workbook(unique_rows(3), order=reordered)
    forget_bytes(admin_conn, data)
    owned_profile("AAT", signature_of(admin_conn, data), fixture_verified=False)
    review = ingest_as(engineer, cleanup, "ro08-unverified.xlsx", data, "AAT")
    assert review["commit_blockers"] == ["UNVERIFIED_PROFILE"]
    tab = only_tab(engineer, "AAT", review)
    assert tab["state"] == "blocked"
    assert tab["operator_message"] == ADMIN_WAIT


def test_the_wavescan_missing_column_sentence_is_unchanged(
    engineer, admin_conn, cleanup  # noqa: F811
):
    headers = [h for h in HEADERS if h != "Color"]
    data = sheet_bytes(headers, _rows(2))
    forget_bytes(admin_conn, data)
    [entry] = upload(engineer, "ro08-no-colour-ws.xlsx", data, "AAT").json()["batches"]
    cleanup.append(entry["load_id"])
    review = wait_for(engineer, entry["load_id"])
    assert review["batch"]["status"] == "REJECTED_TEMPLATE"
    tab = only_tab(engineer, "AAT", review)
    assert tab["state"] == "blocked"
    assert tab["operator_message"] == (
        "This tab has no Color column, so it cannot load. Fix the file and upload it again."
    )
