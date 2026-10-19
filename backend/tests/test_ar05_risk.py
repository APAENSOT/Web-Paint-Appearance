"""AR05 Task 11: next-month risk, 6-month history, recurring problems."""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.assistant.answer import Box, MonthPoint
from app.domain.assistant.report_grids import recurring
from app.domain.assistant.risk import history, next_month_risk
from tests.test_ar03_analysis_report import NOW, data, get  # noqa: F401
from tests.test_ar04_assistant import assert_clean

DAYS = tuple(date(2026, 2, 1) + timedelta(days=i) for i in range(10))


def _b(color, status="PASS", start=3.0, step=0.0, days=DAYS, layer="CLEAR", lsl=2.0, usl=None, scope=None):
    vals = tuple(start + step * i + (0.05 if i % 2 else -0.05) for i in range(len(days)))
    return Box("film", layer, "P703 DBL RANGER", color, "Vertical", status, scope, lsl, usl, "µm", vals, days)


def test_risk_ranks_trend_over_level_and_skips_ineligible():
    drift, flat = _b("Blue", "WARNING", step=-0.1), _b("Red")
    few = _b("Grey", step=-0.5, days=DAYS[:4])
    nolimit = _b("Pink", step=-0.5, lsl=None)
    a = next_month_risk([flat, few, nolimit, drift])
    assert_clean(a)
    assert a.headline == "If nothing changes, P703 DBL RANGER Blue · Clear · V is next: about 30 of the next 30 cars out"
    ev = a.evidence
    assert ev["kind"] == "bar" and ev["columns"] == ["Box", "Expected out of 30", "Basis", "Now"]
    assert [r[0] for r in ev["rows"]] == [drift.label, flat.label]
    assert ev["rows"][0][1:] == [30, "trend", "For Improvement"]
    assert ev["rows"][1][1:] == [0, "level", "Pass"]
    assert a.followups == [{"label": "Is it trending?", "topic": "trend", "target": drift.key},
                           {"label": "Why is it failing?", "topic": "why_failing", "target": drift.key}]


def test_risk_all_clear_and_not_enough():
    a = next_month_risk([_b("Red")])
    assert a.status == "all_clear" and a.headline == "No box is heading out of its limits."
    b = next_month_risk([_b("Red", days=DAYS[:4])])
    assert b.status == "not_enough" and b.headline == "Not enough measuring days to project any box (5 needed)."


def _mp(m, mean, status):
    return MonthPoint(m, mean, status)


def test_history_streak_and_sequence():
    box = _b("Blue", "FAIL")
    run = history(box, [_mp("2026-03", 1.5, "FAIL"), _mp("2026-02", 1.6, "FAIL"), _mp("2026-01", 3.0, "PASS")])
    assert_clean(run)
    assert run.headline == "P703 DBL RANGER Blue · Clear · V: Fail 2 months running"
    ev = run.evidence
    assert ev["kind"] == "trend_monthly" and ev["columns"] == ["Month", "Mean", "Status"]
    assert ev["series"] == [{"x": "2026-01", "y": 3.0}, {"x": "2026-02", "y": 1.6}, {"x": "2026-03", "y": 1.5}]
    assert ev["rows"][0] == ["January 2026", 3.0, "Pass"] and ev["limits"] == {"lo": 2.0, "hi": None}
    mixed = history(box, [_mp("2026-03", 1.5, "FAIL"), _mp("2026-02", None, None), _mp("2026-01", 3.0, "PASS")])
    assert mixed.headline == "P703 DBL RANGER Blue · Clear · V: Pass → Fail over 2 months"
    assert mixed.evidence["rows"][1] == ["February 2026", "—", "—"]


def test_recurring():
    bad, ok = _b("Blue", "FAIL"), _b("Red")
    mon = {"2026-01": [bad, ok], "2026-02": [bad, ok], "2026-03": [_b("Blue", "WARNING"), ok],
           "2026-04": [_b("Blue"), ok], "2025-12": []}
    a = recurring(mon)
    assert_clean(a)
    assert a.headline == "1 box was not Pass in at least 3 of the last 4 months"
    ev = a.evidence
    assert ev["kind"] == "grid" and ev["columns"] == ["Box", "January 2026", "February 2026", "March 2026", "April 2026"]
    assert [c["word"] for c in ev["cells"][0]] == ["Fail", "Fail", "For Improvement", "Pass"]
    assert ev["cells"][0][0] == {"status_code": "FAIL", "word": "Fail", "note": "", "arrow": ""}
    assert recurring({"2026-01": [bad], "2026-02": [bad], "2026-03": [bad]}).headline.endswith("of the last 3 months")
    clear = recurring({m: [ok] for m in mon if m != "2025-12"})
    assert clear.status == "all_clear" and clear.headline == "No box keeps coming back."
    few = recurring({"2026-01": [bad], "2026-02": [bad]})
    assert few.status == "not_enough" and few.headline == "Needs at least 3 months of data."


def test_endpoints_run(data):
    for topic in ("next_month_risk", "recurring"):
        a = get(data, "analysis/ask", topic=topic, month=NOW)
        assert a["status"] in ("answer", "all_clear", "not_enough_data"), topic
    s = get(data, "analysis/ask", topic="history", month=NOW)
    assert s["status"] == "needs_slot"
    box = get(data, "analysis/ask", topic="trend", month=NOW)
    if box["status"] == "answer":
        key = box["followups"][0].get("target")
        h = get(data, "analysis/ask", topic="history", month=NOW, target=key) if key else s
        assert h["status"] in ("answer", "not_enough_data", "needs_slot")


def test_history_gap_breaks_streak():
    box = _b("Blue", "FAIL")
    gap = history(box, [_mp("2026-03", 1.5, "FAIL"), _mp("2026-02", None, None), _mp("2026-01", 1.6, "FAIL")])
    assert gap.headline == "P703 DBL RANGER Blue · Clear · V: Fail → Fail over 2 months"
    run = history(box, [_mp("2026-03", 1.5, "FAIL"), _mp("2026-02", 1.6, "FAIL"), _mp("2026-01", None, None)])
    assert run.headline.endswith("Fail 2 months running")


def test_risk_proof_wording():
    a = next_month_risk([_b("Blue", "WARNING", step=-0.1), _b("Red")])
    assert a.proof == "Projected from the trend; 2 boxes had enough measuring days"
