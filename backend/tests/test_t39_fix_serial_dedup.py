"""T39-FIX -- a serial-less point is deduplicated by its sheet-vehicle.

ADR 0013 decision 8a. With no serial, two points are the same measurement
when they share plant + measured date + model + colour + checkzone **and**
the existing 80% measure rule agrees. `(plant, NULL, zone)` alone is never a
key. A named serial keeps `(plant, serial, checkzone)`.
"""

from __future__ import annotations

from dataclasses import replace

from app.domain.cleaner import Cleaner, CleanRow, dedup_key
from app.domain.dedup import Deduplicator, ExistingMeasurement
from app.domain.reader import RawRow
from tests.test_t04_domain import REFERENCE
from tests.test_t04_ingest import cleanup  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    rows,
    sent,
    viewer,
    ws_url,
)

MEASURES = {m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")}


def point(source_row: int, *, date="2026-09-08", color="3HC Traction Green",
          serial=None) -> CleanRow:
    raw = RawRow(
        source_file="t.xlsx", source_sheet="s", source_row=source_row,
        values=dict(
            date=date, plant="AAT", model="U704", checkzone="01 RRHOOD",
            color=color, serial_no=serial, **MEASURES,
        ),
    )
    ref = REFERENCE
    if color != "3HC Traction Green":
        ref = replace(
            REFERENCE,
            color={**dict(REFERENCE.color), color.lower(): color},
            offered_colors={**dict(REFERENCE.offered_colors), ("AAT", color): True},
        )
    out = Cleaner(ref, ("AAT", "FTM"), expected_plant="AAT").clean_row(raw)
    assert isinstance(out, CleanRow), out
    return out


# =====================================================================
# the key
# =====================================================================
def test_the_serialless_key_is_the_sheet_vehicle_not_plant_null_zone():
    row = point(2)
    assert row.key() == ("AAT", "2026-09-08", "U704", "Traction Green", "RRHOOD")
    assert dedup_key("AAT", "S-1", "RRHOOD", row.measured_date, "U704", "x") == (
        "AAT", "S-1", "RRHOOD"
    )
    assert ("AAT", None, "RRHOOD") != row.key()


# =====================================================================
# within one file
# =====================================================================
def test_two_serialless_points_same_day_model_colour_panel_are_one():
    result = Deduplicator(80.0).run([point(2), point(3)])
    assert len(result.keep) == 1 and len(result.duplicates) == 1


def test_a_different_measured_date_is_not_a_duplicate():
    result = Deduplicator(80.0).run([point(2), point(3, date="2026-09-09")])
    assert len(result.keep) == 2 and not result.duplicates


def test_a_different_colour_is_not_a_duplicate():
    result = Deduplicator(80.0).run([point(2), point(3, color="Shadow Black")])
    assert len(result.keep) == 2 and not result.duplicates


def test_a_blank_serial_never_collides_with_a_named_serial():
    named = point(2, serial="T39FIX-CAR")
    blank = point(3)
    assert named.key() != blank.key()
    result = Deduplicator(80.0).run([named, blank])
    assert len(result.keep) == 2 and not result.duplicates


def test_the_80_percent_rule_still_decides():
    other = point(3)
    other = replace(other, measures={
        m: (v + 50 if v is not None else None) for m, v in other.measures.items()
    })
    result = Deduplicator(80.0).run([point(2), other])
    assert len(result.keep) == 2, "same sheet-vehicle, different numbers: a re-measurement"


def test_a_serialless_point_already_stored_is_a_duplicate():
    row = point(2)
    existing = {row.key(): [ExistingMeasurement(
        measures=dict(row.measures), source="Sep.xlsx [U704_38P] row 7",
    )]}
    result = Deduplicator(80.0).run([row], existing)
    assert not result.keep
    assert "already loaded from Sep.xlsx" in result.duplicates[0].kept_description


# =====================================================================
# across files, through the service and the database
# =====================================================================
def test_the_same_serialless_month_in_a_new_file_is_a_duplicate(
    engineer, cleanup, admin_conn
):
    """A re-export of the same serial-less month under a new hash must not
    load the same panels twice (the recheck's locked follow-up)."""
    month = rows(3, **{"Serial No": None})
    [review] = sent(engineer, cleanup, admin_conn, "t39fix-first.xlsx", book(HEADERS, month))
    assert review["batch"]["counts"]["rows_loaded"] == 3
    loaded = engineer.post(ws_url("AAT", review["batch"]["file_hash"], "load-ready"))
    assert loaded.status_code == 200, loaded.text

    # New bytes (another Month label), same points.
    again = book(HEADERS, [{**r, "Month": "Sept"} for r in month])
    [second] = sent(engineer, cleanup, admin_conn, "t39fix-again.xlsx", again)
    counts = second["batch"]["counts"]
    assert counts["rows_loaded"] == 0 and counts["rows_duplicate"] == 3, counts

    # The same panels on another day are new measurements.
    other_day = book(HEADERS, [{**r, "Date": "2026-07-01"} for r in month])
    [third] = sent(engineer, cleanup, admin_conn, "t39fix-day.xlsx", other_day)
    assert third["batch"]["counts"]["rows_loaded"] == 3
    assert third["batch"]["counts"]["rows_duplicate"] == 0


def test_a_named_serial_row_is_not_a_duplicate_of_a_stored_blank_serial_row(
    engineer, cleanup, admin_conn
):
    month = rows(2, **{"Serial No": None})
    [first] = sent(engineer, cleanup, admin_conn, "t39fix-blank.xlsx", book(HEADERS, month))
    assert engineer.post(
        ws_url("AAT", first["batch"]["file_hash"], "load-ready")
    ).status_code == 200
    named = book(HEADERS, [{**r, "Serial No": "T39FIX-NAMED"} for r in month])
    [second] = sent(engineer, cleanup, admin_conn, "t39fix-named.xlsx", named)
    assert second["batch"]["counts"]["rows_duplicate"] == 0
    assert second["batch"]["counts"]["rows_loaded"] == 2
