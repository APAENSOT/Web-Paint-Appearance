"""RO15: a Wave Scan row whose date disagrees with its own Month / Year cells
is held as ``BAD_DATE`` on that column, never loaded into the wrong month.

Pure tests of the cleaner and the copy; no database.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.cleaner import CleanRow, Reject, RejectReason
from app.domain.held_label_copy import operator_message_for
from app.services.worksheet import held_row_message, preview_rows
from tests.test_t04_domain import cleaner, make_raw  # noqa: F401 -- `cleaner` is a fixture

MEASURES = {m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")}


def _row(cleaner, **cells):
    values = dict(
        date=datetime(2026, 9, 15, 2, 24), plant="aat", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no="TB1", **MEASURES,
    )
    values.update(cells)
    return cleaner.clean_row(make_raw(**values))


@pytest.mark.parametrize("month", ["September", " september ", "Sep", "SEP", 9, 9.0, "9", " 9 "])
def test_a_month_cell_that_agrees_loads(cleaner, month):
    assert isinstance(_row(cleaner, month=month, year=2026), CleanRow)


@pytest.mark.parametrize("year", [2026, 2026.0, "2026"])
def test_a_year_cell_that_agrees_loads(cleaner, year):
    assert isinstance(_row(cleaner, month="September", year=year), CleanRow)


def test_a_date_in_another_month_is_held_on_the_month_column(cleaner):
    out = _row(cleaner, date=datetime(2026, 2, 15, 2, 24), month="September", year=2026)
    assert isinstance(out, Reject)
    assert out.reason == RejectReason.BAD_DATE
    assert (out.column, out.value) == ("month", "September")
    assert out.detail == (
        "date 2026-02-15 is in February 2026 but this row's Month cell says 'September'"
    )


def test_a_date_in_another_year_is_held_on_the_year_column(cleaner):
    out = _row(cleaner, month="September", year=2025)
    assert isinstance(out, Reject) and out.reason == RejectReason.BAD_DATE
    assert (out.column, out.value) == ("year", "2025")
    assert "2026" in out.detail and "Year cell says 2025" in out.detail


def test_month_is_named_first_when_both_disagree(cleaner):
    out = _row(cleaner, month="March", year=2025)
    assert isinstance(out, Reject) and out.column == "month"


@pytest.mark.parametrize("month", [None, "", "Q3", "Sept.", "Sept", 13, 0, 9.5, "9.0"])
def test_a_blank_or_unreadable_month_is_not_checked(cleaner, month):
    out = _row(cleaner, date=datetime(2026, 2, 15), month=month, year=2026)
    assert isinstance(out, CleanRow), "a spelling we do not know never creates a hold"


@pytest.mark.parametrize("year", [None, "", "FY26", "2026.0"])
def test_a_blank_or_unreadable_year_is_not_checked(cleaner, year):
    assert isinstance(_row(cleaner, month="September", year=year), CleanRow)


def test_an_aat_text_date_reads_its_year_and_is_checked_against_the_month(cleaner):
    loads = _row(cleaner, date="09/14 8:04 AM", month="September", year=2026)
    assert isinstance(loads, CleanRow) and loads.measured_date.isoformat() == "2026-09-14"
    held = _row(cleaner, date="09/14 8:04 AM", month="August", year=2026)
    assert isinstance(held, Reject) and (held.reason, held.column) == ("BAD_DATE", "month")


def test_an_unparseable_date_keeps_todays_hold(cleaner):
    out = _row(cleaner, date="last tuesday", month="September", year=2026)
    assert isinstance(out, Reject) and out.reason == RejectReason.BAD_DATE
    assert (out.column, out.value) == ("date", "last tuesday")
    assert out.detail == "unrecognised date format: 'last tuesday'"


# --- the sentence on screen -------------------------------------------
DETAIL = "date 2026-02-15 is in February 2026 but this row's Month cell says 'September'"


def test_the_row_sentence_names_the_date_and_the_month_cell():
    said = held_row_message("BAD_DATE", "month", "September", plant="SAP", detail=DETAIL)
    assert said == (
        'This row\'s date is 15 Feb 2026, but its Month cell says "September". '
        "It will not load. Fix the date or the month in the file and upload it "
        "again. We never choose one for you."
    )
    assert "**" not in said


def test_the_held_list_names_every_date_in_its_group():
    said = operator_message_for(
        "date", "September", column="month", reason="BAD_DATE",
        details=[DETAIL, DETAIL.replace("2026-02-15 is in February", "2026-05-10 is in May")],
    )
    assert said.startswith(
        'These rows are dated 15 Feb 2026 and 10 May 2026, but their Month cell says "September".'
    )
    three = operator_message_for(
        "date", "September", column="month",
        details=[DETAIL.replace("2026-02-15", d) for d in ("2026-05-18", "2026-02-24", "2026-05-10")],
    )
    assert three.startswith("These rows are dated 24 Feb 2026, 10 May 2026 and 18 May 2026,")


def test_a_year_hold_says_year():
    said = operator_message_for(
        "date", "2025", column="year",
        details=["date 2026-09-15 is in September 2026 but this row's Year cell says 2025"],
    )
    assert 'its Year cell says "2025"' in said and "Fix the date or the year" in said


def test_an_unparseable_date_keeps_the_old_sentence():
    assert held_row_message("BAD_DATE", "date", "last tuesday", plant="SAP",
                            detail="unrecognised date format: 'last tuesday'") == (
        "This row has no usable measure date, so it will not load. Fix the "
        "date cell. We never use the upload day instead."
    )


def test_the_worksheet_row_carries_the_month_sentence():
    [row] = preview_rows("P703 SEPTEMBER 2026", [{
        "source_row": 258, "disposition": "REJECT", "reason": "BAD_DATE",
        "detail": DETAIL,
        "canonical": {"offending_column": "month", "offending_value": "September"},
        "raw": {"values": {"date": "2026-02-15T02:24:00", "month": "September"}},
    }], set(), plant="SAP")
    assert row["operator_message"].startswith("This row's date is 15 Feb 2026")
