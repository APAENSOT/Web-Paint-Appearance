"""AR06 Task 3: plottable numbers for the table-only answers (shift dumbbell, went_well bar)."""

from __future__ import annotations

from statistics import median

from app.domain.assistant.changes import changes
from app.domain.assistant.compare_topics import compare_months
from app.domain.assistant.report_grids import went_well
from app.schemas.assistant import AssistantEvidence
from tests import test_ar05_grids as tg
from tests.test_ar04_assistant import HIGH, LOW, _cb, assert_clean


def test_shift_points_are_before_and_now_medians_for_boxes_in_both_months():
    big, big_b = _cb(HIGH, model="M2", status="PASS"), _cb(LOW, model="M2", status="PASS")
    new, gone = _cb(LOW, model="M3"), _cb(LOW, model="M4")
    a = changes([big, new], [big_b, gone], "2026-09")
    assert_clean(a)
    ev = a.evidence
    assert ev["kind"] == "shift"
    assert ev["points"] == [{"x": round(median(LOW), 2), "y": round(median(HIGH), 2), "label": big.label}]
    assert ev["rows"][0][0] == big.label and ev["rows"][0][4] == "Real shift"  # points align with the first rows
    AssistantEvidence(**ev)  # the schema accepts it


def test_compare_months_carries_the_same_points():
    a = compare_months([_cb(HIGH)], [_cb(LOW)], "2026-10", "2026-09")
    assert len(a.evidence["points"]) == 1


def test_went_well_change_is_signed_and_verdict_stays_text():
    now = [tg._b("Blue", "PASS", values=tg.HIGH), tg._b("Gold", "PASS", values=(10.0, 10.1) * 5, layer="PRIMER")]
    before = [tg._b("Blue", "FAIL", values=tg.LOW)]
    a = went_well(now, before, "2026-01")
    assert_clean(a)
    ev = a.evidence
    assert ev["columns"] == ["Box", "Change", "Verdict", "Now"]
    assert ev["rows"][0][1] == "+2.0"  # signed string, as bands sends; the bar parses it
    assert ev["rows"][0][2] == "Real shift"
    assert ev["rows"][1][1] is None and ev["rows"][1][2].startswith("Capable")  # no change to plot
    AssistantEvidence(**ev)
