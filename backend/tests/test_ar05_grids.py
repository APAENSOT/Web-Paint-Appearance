"""AR05 Task 4: colour report and model report."""

from __future__ import annotations

from datetime import date

from app.domain.assistant.answer import Box
from app.domain.assistant.report_grids import colour_report, model_report
from tests.test_ar03_analysis_report import NOW, RANGER, data, get  # noqa: F401
from tests.test_ar04_assistant import assert_clean

D = (date(2026, 2, 1),) * 10


def _b(color, status, layer="CLEAR", model="P703 DBL RANGER", orient="Vertical", values=(1.0,) * 10, scope=None):
    return Box("film", layer, model, color, orient, status, scope, 2.0, None, "µm", values, D)


def test_colour_report_ranks_and_arrows():
    now = [_b("Blue", "FAIL", values=(1, 1, 1, 1, 1, 1, 1, 3, 3, 3)), _b("Blue", "PASS", "BASE"),
           _b("Red", "PASS"), _b("Green", "WARNING", "PRIMER", orient="Horizontal")]
    before = [_b("Blue", "PASS")]
    a = colour_report(now, before, "2026-02", "2026-01")
    assert_clean(a)
    assert a.headline == "2 of 3 colours need action; start with Blue (Clear)"
    ev = a.evidence
    assert ev["kind"] == "heatmap" and ev["columns"] == ["Colour", "E-coat", "Primer", "Base", "Clear", "CF"]
    assert ev["rows"][0][0] == "Blue" and len(ev["cells"][0]) == 5
    clear = ev["cells"][0][3]
    assert clear == {"status_code": "FAIL", "word": "Fail", "note": "RANGER V", "arrow": "↓"}
    assert ev["cells"][0][0] == {"status_code": None, "word": "—", "note": "", "arrow": ""}
    assert ev["cells"][0][2]["note"] == "" and ev["cells"][0][2]["word"] == "Pass"
    assert [f["topic"] for f in a.followups] == ["model_report", "why_failing"]
    assert a.followups[0]["target"] == "P703 DBL RANGER" and a.followups[1]["target"] == now[0].key


def test_colour_report_singular_clear_word_and_all_pass():
    a = colour_report([_b("Blue", "WARNING"), _b("Red", "PASS")], [], "2026-02", None)
    assert a.headline == "1 of 2 colours needs action; start with Blue (Clear)"
    assert a.evidence["cells"][0][3]["word"] == "For Improvement"
    ok = colour_report([_b("Blue", "PASS"), _b("Red", "PASS")], [], "2026-02", None)
    assert ok.status == "all_clear" and ok.headline == "All 2 colours Pass this month."
    assert_clean(ok)


def test_model_report():
    now = [_b("Blue", "FAIL"), _b("Red", "PASS"), _b("Red", "PASS", "BASE"), _b("Red", "PASS", orient="Horizontal")]
    a = model_report("P703 DBL RANGER", now, [_b("Blue", "PASS")])
    assert_clean(a)
    assert a.headline == "RANGER: Clear is the worst layer (1 of 3 boxes not Pass)"
    assert a.evidence["columns"] == ["Layer", "H", "V"]
    assert [r[0] for r in a.evidence["rows"]] == ["Base", "Clear"]
    v = a.evidence["cells"][1][1]
    assert v == {"status_code": "FAIL", "word": "Fail", "note": "Blue", "arrow": "↓"}
    assert model_report("NOPE", now, []).status == "not_enough"


def test_endpoints(data):
    c = get(data, "analysis/ask", topic="colour_report", month=NOW)
    assert c["evidence"]["kind"] == "heatmap" and c["evidence"]["cells"]
    m = get(data, "analysis/ask", topic="model_report", month=NOW, target=RANGER)
    assert m["status"] != "needs_slot" and m["evidence"]["columns"] == ["Layer", "H", "V"]


def test_acceptable_only_colour_ranks_above_all_pass():
    a = colour_report([_b("Alpha", "PASS"), _b("Zulu", "WARNING", values=(3.0,) * 10)], [], "2026-02", None)
    assert a.evidence["rows"][0][0] == "Zulu"
    assert a.headline == "1 of 2 colours needs action; start with Zulu (Clear)"


def test_model_report_without_previous_month_says_so():
    a = model_report("P703 DBL RANGER", [_b("Blue", "FAIL")], [])
    assert "No previous month, so no arrows" in a.method["caveats"]


# ---- Task 5: went_well and weekly
from app.domain.assistant.readings import Reading  # noqa: E402
from app.domain.assistant.report_grids import weekly, went_well  # noqa: E402

LOW = (1.0, 1.1, 1.2, 0.9, 1.0, 1.1, 1.2, 0.9, 1.0, 1.1)
HIGH = tuple(v + 2.0 for v in LOW)
WIDE = (1.0, 5.0, 2.0, 4.0, 3.0, 1.5, 4.5, 2.5, 3.5, 3.0)


def test_went_well_headline_and_capable_rows():
    now = [_b("Blue", "PASS", values=HIGH), _b("Red", "PASS", values=HIGH, layer="BASE"),
           _b("Gold", "PASS", values=(10.0, 10.1) * 5, layer="PRIMER")]
    before = [_b("Blue", "FAIL", values=LOW), _b("Red", "PASS", values=HIGH, layer="BASE")]
    a = went_well(now, before, "2026-01")
    assert_clean(a)
    assert a.headline == "P703 DBL RANGER Blue · Clear · V improved for real (+2.0 µm); now Pass"
    ev = a.evidence
    assert ev["kind"] == "bar" and ev["columns"] == ["Box", "Change", "Verdict", "Now"]
    assert ev["rows"][0][2] == "Real shift"
    assert ev["rows"][1][2].startswith("Capable (Cpk ") and "Gold" in ev["rows"][1][0]


def test_went_well_none_and_no_previous():
    same = [_b("Blue", "PASS", values=WIDE)]
    a = went_well(same, same, "2026-01")
    assert a.status == "all_clear" and a.headline == "Nothing improved for real since January 2026."
    n = went_well(same, [], "2026-01")
    assert n.status == "not_enough" and n.headline == "No January 2026 data to compare."
    assert_clean(a)


def _r(domain, d, out, metric="CLEAR"):
    return Reading(domain, "CLEAR", "M", "Blue", None, "Vertical", "P1", None, d, metric, 1.0, out, "k")


def test_weekly_flags_busy_week_and_never_week_zero():
    rs = [_r("film", date(2026, 2, 10), True) for _ in range(6)]  # week 2, all out
    rs += [_r("film", date(2026, 2, 3), False) for _ in range(30)]
    rs += [_r("film", None, True) for _ in range(5)]  # undated: never flagged
    rs += [_r("wavescan", date(2026, 2, 3), None, "wa")]  # no out verdict: ignored
    a = weekly(rs)
    assert_clean(a)
    assert a.headline == "6 of 11 out readings were in week 2"
    ev = a.evidence
    assert ev["kind"] == "weekly_strip" and ev["columns"] == ["Week", "Readings", "Out", "Flag"]
    assert ev["rows"] == [["Week 1", 30, 0, ""], ["Week 2", 6, 6, "flagged"], ["Day not recorded", 5, 5, ""]]


def test_weekly_spread_domains_and_empty():
    even = [_r("film", date(2026, 2, d), i % 2 == 0) for i, d in enumerate([2, 9, 16, 23] * 5)]
    assert weekly(even).headline == "Out readings are spread across the weeks"
    both = [_r("film", date(2026, 2, 10), True) for _ in range(6)] + [_r("film", date(2026, 2, 3), False)] * 30
    both += [_r("wavescan", date(2026, 2, 3), False, "cf")] * 5 + [_r("wavescan", date(2026, 2, 3), True, "cf")]
    assert weekly(both).headline == "6 of 6 Film out readings were in week 2"
    assert weekly([]).headline == "No readings for this month and filter."
    assert weekly([_r("wavescan", date(2026, 2, 3), None, "wa")]).status == "not_enough"


def test_task5_endpoints(data):
    w = get(data, "analysis/ask", topic="weekly", month=NOW)
    assert w["status"] == "answer" and w["evidence"]["kind"] == "weekly_strip"
    g = get(data, "analysis/ask", topic="went_well", month=NOW)
    assert g["status"] == "all_clear" and g["decision"]["headline"].startswith("Nothing improved for real since")


def test_went_well_status_only_move_is_not_for_real():
    a = went_well([_b("Blue", "PASS", values=WIDE)], [_b("Blue", "FAIL", values=WIDE)], "2026-01")
    assert a.headline == "P703 DBL RANGER Blue · Clear · V moved to a better status (Fail → Pass)"
    assert a.evidence["rows"][0][2] == "Better status"
    now = [_b("Red", "PASS", values=WIDE, layer="BASE"), _b("Blue", "PASS", values=HIGH)]
    before = [_b("Red", "FAIL", values=WIDE, layer="BASE"), _b("Blue", "FAIL", values=LOW)]
    m = went_well(now, before, "2026-01")
    assert m.headline == "P703 DBL RANGER Blue · Clear · V improved for real (+2.0 µm); now Pass"
    assert [r[2] for r in m.evidence["rows"]] == ["Real shift", "Better status"]


def test_weekly_both_domains_one_row_per_domain_and_week():
    rs = [_r("film", date(2026, 2, 10), True) for _ in range(6)] + [_r("film", date(2026, 2, 3), False)] * 30
    rs += [_r("wavescan", date(2026, 2, 3), False, "cf")] * 5 + [_r("wavescan", date(2026, 2, 3), True, "cf")]
    assert weekly(rs).evidence["rows"] == [["Week 1 · Film", 30, 0, ""], ["Week 1 · Wave Scan", 6, 1, ""],
                                           ["Week 2 · Film", 6, 6, "flagged"]]


def test_binomial_sf_survives_a_month_of_readings():
    # Live 500: comb(n, i) overflowed a float when a week held thousands of readings.
    import pytest
    from app.domain.report_stats import binomial_sf

    assert 0.0 <= binomial_sf(300, 4000, 0.05) <= 1.0
    assert binomial_sf(60, 1000, 0.05) == pytest.approx(0.0867321783848, rel=1e-9)
    assert binomial_sf(5, 4000, 0.5) == pytest.approx(1.0)
    assert binomial_sf(1, 5, 0.0) == 0.0 and binomial_sf(1, 5, 1.0) == 1.0 and binomial_sf(6, 5, 0.5) == 0.0
