"""AR04: guided no-AI assistant for the Analysis & Report page.

The pure tests (statistics primitives) need no database.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.assistant.answer import Box, all_clear, capability_word, not_enough, severity
from app.domain.report_summary import BAND_POINTS_TO

from app.domain.report_stats import (T95, binomial_sf, cpk, ewma_first_out, mann_whitney,
                                     mean_sd, multiple_ols, normal_cdf, ols_fit)


def test_normal_cdf_and_mean_sd():
    assert normal_cdf(0) == pytest.approx(0.5)
    assert normal_cdf(1.96) == pytest.approx(0.975, abs=1e-4)
    assert mean_sd([9, 10, 11]) == (10.0, 1.0)
    assert mean_sd([4]) == (4.0, None) and mean_sd([]) == (None, None)


def test_cpk_one_and_two_sided():
    assert cpk([9, 10, 11], 7, None) == pytest.approx(1.0)
    assert cpk([9, 10, 11], 7, 12) == pytest.approx(2 / 3)
    assert cpk([9, 10, 11], None, 13) == pytest.approx(1.0)
    assert cpk([5, 5, 5], 1, None) is None
    assert cpk([9, 10, 11], None, None) is None


def test_binomial_sf_exact():
    assert binomial_sf(0, 5, 0.1) == 1.0
    assert binomial_sf(5, 5, 0.5) == pytest.approx(1 / 32)
    assert binomial_sf(2, 3, 0.5) == pytest.approx(0.5)


def test_mann_whitney():
    same = list(range(10))
    assert mann_whitney(same, same) == pytest.approx(1.0)
    assert mann_whitney(list(range(1, 11)), list(range(11, 21))) == pytest.approx(0.000183, rel=0.02)
    assert mann_whitney(list(range(9)), list(range(10))) is None
    assert mann_whitney([1] * 10, [1] * 10) is None


def test_ols_fit_with_standard_error():
    fit = ols_fit([1, 2, 3, 4, 5], [1, 3, 2, 5, 4])
    assert (fit.slope, fit.intercept, fit.n) == (pytest.approx(0.8), pytest.approx(0.6), 5)
    assert fit.slope_se == pytest.approx((1.2 / 10) ** 0.5)
    lo, hi = fit.ci95()
    assert lo == pytest.approx(0.8 - T95[3] * fit.slope_se)
    assert ols_fit([1, 2], [1, 2]) is None and ols_fit([2, 2, 2], [1, 2, 3]) is None


def test_ewma_first_out():
    assert ewma_first_out([10] * 5 + [13] * 5, mu0=10, sd0=1) == 6
    assert ewma_first_out([10] * 10, mu0=10, sd0=1) is None


def test_multiple_ols_exact_fit():
    rows, ys = [[0, 0], [1, 0], [0, 1], [1, 1], [2, 1]], [1, 3, 4, 6, 8]
    assert multiple_ols(rows, ys) == pytest.approx([1, 2, 3])
    assert multiple_ols(rows[:3], ys[:3]) is None


FORBIDDEN = ("rate", "pct", "percent", "score", "grade")


def assert_clean(answer):
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                assert not any(w in str(k).lower() for w in FORBIDDEN), k
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            assert "%" not in x, x

    walk(answer.to_dict())


def _box(**kw):
    base = dict(domain="wavescan", layer="CLEAR", model="M1", color="Red", orient="Horizontal",
                status="FAIL", scope=None, lsl=2.5, usl=None, unit="", values=(1, 2, 3, 9, 10),
                dates=(date(2026, 1, 1),) * 5)
    return Box(**{**base, **kw})


def test_box_out_and_severity():
    b = _box()
    assert b.out == 2 and severity(b) == pytest.approx(6)
    assert b.key == "wavescan|CLEAR|M1|Red|Horizontal" and b.label == "M1 Red · Clear · H"
    assert _box(layer=None).label == "M1 Red · CF · H"
    assert severity(_box(values=(2, 2, 2), lsl=3)) == pytest.approx(9)  # sd 0 -> past 0


def test_capability_words():
    assert [capability_word(c) for c in (1.33, 1.0, 0.99)] == ["Capable", "Marginal", "Poor"]


def test_band_layers_owner_map():
    assert BAND_POINTS_TO == {"du": "Clear", "wa": "Clear", "wb": "Clear, Base", "wc": "Base",
                              "wd": "Primer, Substrate", "we": "E-coat, Substrate"}


def test_answer_strings_have_no_percent():
    a = not_enough("Need more data", 3, "n>=10")
    assert_clean(a)
    assert a.to_dict()["decision"] == {"status_code": None, "headline": "Need more data"}
    assert_clean(all_clear("All good", "rule", 12))


# ---- Task 3: colours ----
from app.domain.assistant.colours import colours, direction  # noqa: E402


def _film(**kw):
    base = dict(domain="film", layer="PRIMER", model="M1", color="Red", orient="Horizontal",
                status="FAIL", lsl=20.0, usl=40.0, unit="µm")
    vals = kw.pop("values", tuple(float(v) for v in range(21, 55)))
    return _box(**{**base, "values": vals, **kw})


def test_colours_ranks_by_severity_then_cpk():
    low = tuple([10.0] * 9 + [25.0] * 25)  # 34 values, 9 under Lo
    worse = _film(color="Blue", values=low)
    mild = _film(color="Red", values=tuple([10.0] * 3 + [25.0] * 31))
    a = colours([mild, worse])
    assert a.headline == f"{worse.label} is the weakest"
    assert "9 of 34 under Lo" in a.proof
    assert [r[0] for r in a.evidence["rows"]][0] == worse.label
    assert a.evidence["kind"] == "bar"
    assert a.followups[0] == {"label": "Is it trending?", "topic": "trend", "target": worse.key}
    assert a.followups[1] == {"label": "Which points (all colours)?", "topic": "points", "target": None}
    assert a.confidence == "solid"
    assert direction(worse).startswith("Mean ") and "reduce Primer build variation" in direction(worse)
    assert_clean(a)


def test_colours_skips_thin_and_flat_boxes():
    ok = _film(color="Blue", values=tuple([10.0] * 9 + [25.0] * 25))
    thin = _film(color="Thin", values=(10.0,) * 9)
    flat = _film(color="Flat", values=(30.0,) * 12, status="PASS")
    a = colours([ok, thin, flat])
    assert [r[0] for r in a.evidence["rows"]] == [ok.label]
    caveats = " ".join(a.method["caveats"])
    assert "fewer than 10 readings" in caveats and "no spread" in caveats
    assert_clean(a)
    n = colours([thin, flat])
    assert n.status == "not_enough" and "1 box skipped: fewer than 10 readings" in n.headline
    assert_clean(n)


def test_colours_all_clear_and_wavescan_direction():
    good = _film(status="PASS", values=tuple(30.0 + (i % 5) for i in range(20)))
    a = colours([good])
    assert a.status == "all_clear" and a.headline == "Every colour is capable this month."
    assert_clean(a)
    ws = _box(values=tuple([1.0] * 5 + [4.0] * 10))
    assert direction(ws) == "CF below minimum → check the Wave Scan bands"
    assert "below minimum" in colours([ws]).proof


def test_colours_out_word_with_no_readings_out_uses_nearer_limit():
    b = _film(lsl=None, usl=40.0, status="PASS", values=tuple(30.0 + (i % 9) for i in range(30)))
    assert b.out == 0
    a = colours([b])
    assert "0 of 30 over Hi" in a.proof
    assert_clean(a)


def test_direction_inside_and_outside_limits():
    inside = _film(values=tuple(22.0 + (i % 3) for i in range(20)))  # mean 23, lsl 20
    assert direction(inside) == "Mean 2.9 µm above Lo; the spread is the problem → reduce Primer build variation"
    over = _film(lsl=None, usl=30.0, values=tuple(34.0 + (i % 3) for i in range(20)))  # mean 35
    assert direction(over) == "Mean 5.0 µm over Hi → lower Primer build"
    hi_in = _film(lsl=None, usl=40.0, values=tuple(34.0 + (i % 3) for i in range(20)))
    assert direction(hi_in) == "Mean 5.0 µm below Hi; the spread is the problem → reduce Primer build variation"


def test_colours_not_all_clear_when_status_not_pass():
    b = _film(status="WARNING", values=tuple(30.0 + (i % 2) * 0.1 for i in range(20)))
    a = colours([b])
    assert a.status != "all_clear" and a.status_code == "WARNING"
    assert_clean(a)


from app.domain.assistant.answer import PointReading  # noqa: E402
from app.domain.assistant.points import points  # noqa: E402


def _film_pts(bad_point="P1", bad_cars=7, n_points=20, n_cars=8):
    return [PointReading("film", f"P{p}", f"C{c}", p == 1 and c < bad_cars)
            for p in range(1, n_points + 1) for c in range(n_cars)]


def test_points_flags_repeat_offender():
    a = points(_film_pts())
    assert a.status == "answer" and a.headline == "P1 is a repeat problem"
    assert a.proof.startswith("out on 7 of 8 cars (plant normal: about 1 in ")
    assert a.next_step == "Check film build at P1"
    assert a.evidence["columns"] == ["Point", "Out", "Measured", "Plant normal"]
    assert_clean(a)


def test_points_single_bad_reading_not_flagged():
    rs = [PointReading("film", f"P{p}", f"C{c}", p == 1 and c == 0) for p in range(1, 21) for c in range(8)]
    a = points(rs)
    assert a.status == "all_clear" and a.headline == "No point stands out from the plant's normal."
    assert_clean(a)


def test_points_counts_cars_not_readings():
    rs = _film_pts(bad_cars=0)
    rs += [PointReading("film", "P1", "C0", True)] * 3
    a = points(rs)
    assert a.status == "all_clear"  # 3 out readings on one car = 1 unit
    assert_clean(a)


def test_points_wavescan_and_empty():
    rs = [PointReading("wavescan", f"Z{p}", None, p == 1 and c < 6) for p in range(1, 16) for c in range(8)]
    a = points(rs)
    assert a.headline == "Z1 is a repeat problem" and "readings" in a.proof
    assert a.next_step == "Check Z1 for CF loss"
    assert_clean(a)
    e = points([])
    assert e.status == "not_enough" and e.headline == "No point readings for this month and filter."


from app.domain.assistant.changes import changes, shifts  # noqa: E402


def _cb(vals, **kw):
    return _film(values=tuple(float(v) for v in vals), **kw)


LOW = [20 + i * 0.1 for i in range(12)]
HIGH = [30 + i * 0.1 for i in range(12)]


def test_shift_real_vs_noise():
    s = shifts([_cb(HIGH)], [_cb(LOW)])[0]
    assert s.real and s.p < 0.05 and s.delta == pytest.approx(10.0)
    n = shifts([_cb(LOW)], [_cb(LOW)])[0]
    assert not n.real and n.delta == 0
    few = shifts([_cb(HIGH[:8])], [_cb(LOW[:8])])[0]
    assert few.p is None and not few.real
    a = changes([_cb(HIGH[:8], status="FAIL")], [_cb(LOW[:8], status="PASS")], "2026-09")
    assert a.evidence["rows"][0][4] == "Too few readings"
    assert_clean(a)


def test_changes_orders_worse_first():
    big = _cb(HIGH, model="M2", status="PASS")
    big_b = _cb(LOW, model="M2", status="PASS")
    worse = _cb(HIGH, status="FAIL", usl=32.0, lsl=None)
    worse_b = _cb(LOW, status="PASS", usl=32.0, lsl=None)
    new = _cb(LOW, model="M3")
    gone = _cb(LOW, model="M4")
    a = changes([big, worse, new], [big_b, worse_b, gone], "2026-09")
    assert a.headline == "1 box got worse (1 real shift)"
    assert a.status_code == "FAIL"
    assert a.proof == "biggest: M1 Red · Primer · H, +10.0 µm, now Fail"
    rows = a.evidence["rows"]
    assert rows[0][0].startswith("M1") and rows[0][4] == "Real shift"
    assert [r[4] for r in rows[-2:]] == ["New", "Gone"] and rows[-2][1] == "—"
    assert a.evidence["columns"] == ["Box", "Before", "Now", "Change", "Verdict"]
    assert_clean(a)
    ok = changes([_cb(LOW)], [_cb(LOW)], "2026-09")
    assert ok.status == "all_clear" and ok.headline == "Nothing changed for real since September 2026."
    sh = changes([big], [big_b], "2026-09")
    assert sh.headline == "Nothing got worse; 1 box shifted for real since September 2026"
    assert sh.proof == "biggest: M2 Red · Primer · H, +10.0 µm, now Pass"
    assert_clean(sh)
    rec = changes([_cb(LOW, status="PASS")], [_cb(LOW, status="FAIL")], "2026-09")
    assert rec.headline == "Nothing got worse; 1 box recovered since September 2026"
    assert_clean(rec)


def test_changes_without_previous_month():
    a = changes([_cb(HIGH)], [], "2026-09")
    assert a.status == "not_enough" and a.headline == "No September 2026 data to compare."
    assert changes([_cb(HIGH)], [], None).headline == "No previous month data to compare."
    assert_clean(a)


def test_changes_fix_round_1():
    # plural + ordering: worse (small), better, real same (big) -> rows worse, better, real
    w1 = _cb(HIGH, model="A", usl=32.0, lsl=None, status="FAIL")
    w1b = _cb(LOW, model="A", usl=32.0, lsl=None, status="PASS")
    w2 = _cb(HIGH, model="B", usl=32.0, lsl=None, status="FAIL")
    w2b = _cb(LOW, model="B", usl=32.0, lsl=None, status="PASS")
    bt = _cb(LOW, model="C", status="PASS")
    btb = _cb(LOW, model="C", status="FAIL")
    sm = _cb([v + 50 for v in HIGH], model="D", status="PASS")
    smb = _cb(LOW, model="D", status="PASS")
    a = changes([sm, bt, w1, w2], [smb, btb, w1b, w2b], "2026-09")
    assert a.headline == "2 boxes got worse (2 real shifts)"
    assert [r[0][:2] for r in a.evidence["rows"]] == ["A ", "B ", "C ", "D "] or         [r[0][:2] for r in a.evidence["rows"]][2:] == ["C ", "D "]
    # same + real counts only when moving toward the nearer limit
    up = _cb(HIGH, usl=32.0, lsl=None, status="PASS")
    upb = _cb(LOW, usl=32.0, lsl=None, status="PASS")
    assert changes([up], [upb], "2026-09").headline == "1 box got worse (1 real shift)"
    away = _cb(LOW, usl=32.0, lsl=None, status="PASS")
    away_b = _cb(HIGH, usl=32.0, lsl=None, status="PASS")
    assert changes([away], [away_b], "2026-09").headline.startswith("Nothing got worse; 1 box shifted")
    nolim = _cb(HIGH, lsl=None, usl=None, status="PASS")
    nolim_b = _cb(LOW, lsl=None, usl=None, status="PASS")
    assert changes([nolim], [nolim_b], "2026-09").headline.startswith("Nothing got worse; 1 box shifted")
    # unit-less proof and wave scan follow-up
    ws = _cb([v / 10 for v in HIGH], domain="wavescan", layer=None, unit="", status="FAIL", lsl=2.5, usl=None)
    wsb = _cb([v / 10 for v in LOW], domain="wavescan", layer=None, unit="", status="PASS", lsl=2.5, usl=None)
    a = changes([ws], [wsb], "2026-09")
    assert a.proof.endswith(", +1.0, now Fail")
    assert {"label": "Which layer?", "topic": "bands", "target": None} in a.followups
    assert not any(f["topic"] == "bands" for f in changes([w1], [w1b], "2026-09").followups)
    # no matching keys, and no-spread verdict
    n = changes([_cb(HIGH, model="X")], [_cb(LOW, model="Y")], "2026-09")
    assert n.status == "not_enough" and n.headline == "No box was measured in both September 2026 and January 2026."
    flat = changes([_cb([5.0] * 12, status="FAIL")], [_cb([5.0] * 12, status="PASS")], "2026-09")
    assert flat.evidence["rows"][0][4] == "No spread"
    assert_clean(a); assert_clean(n); assert_clean(flat)


from app.domain.assistant.summary import summary  # noqa: E402


def test_summary_fix_first_is_highest_severity():
    mild = _cb(range(30, 42), model="A", status="WARNING")
    bad = _cb(range(30, 50), model="B", status="FAIL")
    ok = _cb(range(25, 35), model="C", status="PASS")
    a = summary([mild, ok, bad], [], None)
    assert a.status == "answer" and a.headline == f"Fix first: {bad.label}" and a.status_code == "FAIL"
    assert a.proof == f"{bad.out} of {len(bad.values)} readings out"
    assert a.next_step == direction(bad)
    assert [r[0] for r in a.evidence["rows"]] == [bad.label, mild.label]
    assert a.evidence["columns"] == ["Box", "Status", "Out", "n"]
    assert [f["topic"] for f in a.followups] == ["colours", "points", "changes"]
    assert_clean(a)


def test_summary_all_pass():
    a = summary([_cb(range(25, 35), status="PASS"), _cb(range(25, 35), model="B", status=None)], [], None)
    assert a.status == "all_clear" and a.headline == "All 2 boxes Pass this month."
    e = summary([], [], None)
    assert e.status == "not_enough" and e.headline == "No boxes for this month and filter."
    assert_clean(a); assert_clean(e)


def test_summary_mentions_movement_only_with_previous_month():
    now = [_cb(HIGH, status="FAIL", usl=32.0, lsl=None)]
    prev = [_cb(LOW, status="PASS", usl=32.0, lsl=None)]
    a = summary(now, prev, "2026-09")
    assert a.proof.endswith("; 1 got worse, 0 recovered vs September 2026")
    assert "got worse" not in summary(now, [], "2026-09").proof
    assert "got worse" not in summary(now, prev, None).proof
    assert_clean(a)


from datetime import timedelta  # noqa: E402

from app.domain.assistant.answer import MonthPoint  # noqa: E402
from app.domain.assistant.trend import risk_count, trend  # noqa: E402


def _tb(vals, **kw):
    d0 = date(2026, 10, 1)
    base = dict(domain="film", layer=None, model="M1", color="Red", orient="Horizontal", status="WARNING",
                scope=None, lsl=16.0, usl=None, unit="", values=tuple(vals),
                dates=tuple(d0 + timedelta(days=i) for i in range(len(vals))))
    return Box(**{**base, **kw})


def test_trend_detects_drift_and_days_to_limit():
    now = _tb([20 - 0.3 * i for i in range(10)])
    before = _tb([20.0 + 0.1 * (i % 3) for i in range(12)], status="PASS")
    hist = [MonthPoint("2026-09", 20.1, "PASS"), MonthPoint("2026-10", None, None)]
    a = trend(now, before, hist)
    assert a.status == "answer" and a.headline == "M1 Red · CF · H: drifting down 0.30/day" and a.status_code == "WARNING"
    assert a.proof.startswith("reaches Lo in about 4 days") and "; control chart flagged 2026-10-0" in a.proof
    assert a.confidence == "solid" and a.evidence["kind"] == "trend"
    assert a.evidence["series"][0] == {"x": "2026-10-01", "y": 20.0}
    assert a.evidence["rows"] == [["September 2026", 20.1, "Pass"], ["October 2026", None, "No standard"]]
    assert a.evidence["limits"] == {"lo": 16.0, "hi": None}
    assert a.risk["of_next"] == 30 and a.risk["basis"] == "trend projected 7 days ahead"
    assert a.risk["expected_out"] > 0
    assert [f["topic"] for f in a.followups] == ["points", "changes"]
    assert_clean(a)


def test_trend_stable():
    a = trend(_tb([10, 11, 10, 11, 10, 11, 10, 11], unit="mm"), None, [])
    assert a.headline == "M1 Red · CF · H: stable, no trend this month" and a.proof.startswith("slope ")
    assert "mm/day is within noise (n 8 days)" in a.proof
    assert a.risk["basis"] == "current mean and spread" and a.confidence == "exploratory"
    assert "No usable previous month baseline; control chart uses this month." in a.method["caveats"]
    assert_clean(a)


def test_trend_too_few_days():
    a = trend(_tb([1, 2, 3, 4]), None, [])
    assert a.status == "not_enough" and a.headline == "Only 4 measuring days this month; 5 needed."
    assert_clean(a)
    one = trend(_tb([1]), None, [])
    assert one.headline == "Only 1 measuring day this month; 5 needed."


def test_risk_count():
    assert risk_count(10.0, 1.0, 10.0, None) == 15
    assert risk_count(13.0, 1.0, 10.0, None) == 0
    assert risk_count(10.0, 1.0, None, None) == 0
    assert risk_count(10.0, 1.0, 10.0, 10.0) == 30


def test_trend_without_baseline_uses_own_month():
    a = trend(_tb([20 - 0.3 * i for i in range(10)], unit="mm", domain="wavescan"), _tb([1.0] * 3), [])
    assert a.headline == "M1 Red · CF · H: drifting down 0.30 mm/day" and a.proof.startswith("reaches minimum in about 4 days")
    assert a.confidence == "exploratory" and a.method["caveats"]
    assert_clean(a)


def test_trend_pins_risk_and_flag_date():
    now = _tb([20 - 0.3 * i for i in range(10)])
    before = _tb([20.0 + 0.1 * (i % 3) for i in range(12)], status="PASS")
    a = trend(now, before, [])
    assert a.risk["expected_out"] == 24
    assert a.proof == "reaches Lo in about 4 days; control chart flagged 2026-10-02"


def test_trend_already_past_limit():
    a = trend(_tb([20 - 0.3 * i for i in range(10)], lsl=18.0), None, [])
    assert a.proof.startswith("already past Lo on the trend line")
    a = trend(_tb([20 - 0.3 * i for i in range(10)], lsl=18.0, domain="wavescan"), None, [])
    assert a.proof.startswith("already past minimum on the trend line")
    assert_clean(a)


def test_trend_limit_far_away_and_one_day():
    assert trend(_tb([20 - 0.3 * i for i in range(10)], lsl=0.0), None, []).proof.startswith(
        "no limit reached within 30 days")
    assert trend(_tb([20 - 0.3 * i for i in range(10)], lsl=17.2), None, []).proof.startswith(
        "reaches Lo in about 1 day")


def test_trend_upward_uses_usl_and_no_limit_in_direction():
    up = [10 + 0.3 * i for i in range(10)]
    assert trend(_tb(up, lsl=None, usl=15.0), None, []).proof.startswith("reaches Hi in about 8 days")
    assert trend(_tb(up, lsl=5.0, usl=None), None, []).proof.startswith("no limit reached within 30 days")


def test_trend_zero_sd_before_falls_back_and_no_flag():
    a = trend(_tb([10, 11, 10, 11, 10, 11, 10, 11]), _tb([5.0] * 12), [])
    assert a.confidence == "exploratory" and a.method["caveats"]
    assert "control chart" not in a.proof


from app.domain.assistant.answer import BandRow  # noqa: E402
from app.domain.assistant.bands import bands  # noqa: E402


def _br(model, color, band, vals):
    return [BandRow(model, color, {b: (v if b == band else None) for b in
                                   ("du", "wa", "wb", "wc", "wd", "we", "cf")}) for v in vals]


def _rise():
    now = _br("M1", "WHITE", "wc", [5.0 + 0.1 * (i % 5) for i in range(12)])
    before = _br("M1", "WHITE", "wc", [3.0 + 0.1 * (i % 5) for i in range(12)])
    return now, before


def _paired(base_tracks=True, n=12):
    ecoat = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8]
    other = [7, 2, 9, 4, 1, 8, 3, 6, 0, 5, 11, 10]
    rows = []
    for i in range(n):
        for code, t in (("ECOAT", ecoat[i]), ("PRIMER", i if not base_tracks else other[i]),
                        ("BASE", 20 + i if base_tracks else other[(i + 3) % 12] + 0.5),
                        ("CLEAR", ecoat[(i + 5) % 12] + 0.25)):
            rows.append({"car_no": f"C{i}", "pair_group": "g", "layer_code": code, "thickness": t,
                         "du": None, "wa": None, "wb": None, "wc": float(i), "wd": None, "we": None, "cf": None})
    return rows


def test_bands_maps_rise_to_owner_layer():
    now, before = _rise()
    a = bands(now, before, None)
    assert a.status == "answer" and a.headline == "Wc up on M1 WHITE (+2.0) → check Base"
    assert a.proof == "Not enough paired cars to check." and a.confidence == "solid"
    assert a.evidence["columns"] == ["Model", "Colour", "Band", "Change", "Verdict", "Layer"]
    assert a.evidence["rows"][0][4] == "Real rise" and a.method["n"] == 12
    assert a.followups == [{"label": "Which colours?", "topic": "colours", "target": None}]
    assert_clean(a)
    now = _br("M1", "WHITE", "we", [5.0 + 0.1 * (i % 5) for i in range(12)])
    before = _br("M1", "WHITE", "we", [3.0 + 0.1 * (i % 5) for i in range(12)])
    a = bands(now, before, [])
    assert a.headline.endswith("→ check E-coat") and a.next_step.endswith("; then Substrate")
    assert_clean(a)


def test_bands_data_agrees_and_disagrees():
    now, before = _rise()
    a = bands(now, before, _paired(True))
    assert a.proof.startswith("Data agrees (Base ρ 1.00, n 12, exploratory)") and a.confidence == "exploratory"
    assert any(c.startswith("Regression Wc on layers (n 12)") for c in a.method["caveats"])
    assert_clean(a)
    a = bands(now, before, _paired(False))
    assert a.proof.startswith("Data points elsewhere: Primer (ρ 1.00, n 12)")
    assert_clean(a)


def test_bands_without_wave_scan():
    a = bands([], [], None)
    assert a.status == "not_enough" and a.headline == "Band answers need Wave Scan data."
    assert_clean(a)


def test_bands_without_paired():
    now, before = _rise()
    assert bands(now, before, None).proof == "Not enough paired cars to check."
    assert bands(now, before, _paired()[:8]).proof == "Not enough paired cars to check."


def test_bands_fallback_and_all_clear():
    flat = _br("M1", "WHITE", "wc", [5.0 + 0.1 * (i % 5) for i in range(12)])
    other = _br("M2", "RED", "wc", [1.0 + 0.1 * (i % 5) for i in range(12)])
    a = bands(flat + other, flat + other, None)
    assert a.headline.startswith("Wc high on M1 WHITE (+") and a.headline.endswith("vs plant) → check Base")
    assert a.evidence["rows"][0][4] == "Above plant"
    assert_clean(a)
    a = bands(flat, flat, None)
    assert a.status == "all_clear" and a.headline == "No Wave Scan band stands out this month."


# =====================================================================
# DB: service and endpoint (Task 9), AR03's rolled-back marker plant
# =====================================================================
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from tests.test_ar03_analysis_report import NOW, RANGER, RAPTOR, WHITE, data, get  # noqa: E402,F401

ASK = "analysis/ask"


def _clean(body):
    assert_clean(SimpleNamespace(to_dict=lambda: body))


def test_ask_every_topic_returns_the_shape(data):
    from app.schemas.assistant import AssistantAnswerOut
    from app.services.assistant import TOPICS

    for topic in TOPICS:
        body = get(data, ASK, topic=topic, month=NOW)
        assert set(body) == set(AssistantAnswerOut.model_fields), topic
        assert body["topic"] == topic and body["month"] == NOW and body["previous_month"] == "2099-01"
        assert body["status"] in ("answer", "all_clear", "not_enough_data"), topic
        _clean(body)
    film_only = get(data, ASK, topic="bands", month=NOW, domain="film")
    assert film_only["status"] == "not_enough_data"
    assert film_only["decision"]["headline"] == "Band answers need Wave Scan data."
    points = get(data, ASK, topic="points", month=NOW, target="ignored")
    assert points["status"] in ("answer", "all_clear", "not_enough_data")


def test_box_counts_equal_the_overview(data):
    from app.services import film_overview, overview
    from app.services.assistant import load_month

    conn, plant = data["conn"], data["plant"]
    got = load_month(conn, plant, NOW, plant_scope=None, domain="both", models=[], colors=[])
    ws = {("wavescan", None, b["model_code"], b["color_name"], b["orient"]): b
          for b in overview.overview(conn, plant, plant_scope=None, month=NOW, models=[], colors=[])["boxes"]}
    film = {("film", b["layer_code"], b["model_code"], b["color_name"], b["orient"]): b
            for b in film_overview.overview(conn, plant, plant_scope=None, month=NOW, models=[],
                                            colors=[])["boxes"]}
    assert len(got.boxes) == len(ws) + len(film)
    for box in got.boxes:
        key = (box.domain, box.layer, box.model, box.color, box.orient)
        ref = ws.get(key) or film[key]
        listed = ref["below_minimum"] if box.domain == "wavescan" else ref["out_of_spec"]
        assert (len(box.values), box.out, box.status) == (ref["n"], len(listed), ref["status"]), key
    no_limit = sum(len(b.values) for b in got.boxes if b.lsl is None and b.usl is None)
    assert no_limit > 0 and got.skipped_no_limit == no_limit
    assert len(got.points) == sum(len(b.values) for b in got.boxes) - no_limit
    assert sum(p.out for p in got.points) == sum(b.out for b in got.boxes)
    body = get(data, ASK, topic="points", month=NOW)
    assert f"{no_limit} readings skipped: no limit" in body["method"]["caveats"]
    assert got.bands and all(r.model == RANGER and r.color == WHITE for r in got.bands)


def test_summary_fix_first_matches_report_issues(data):
    body = get(data, ASK, topic="summary", month=NOW)
    issues = get(data, month=NOW)["issues"]
    assert body["status"] == "answer"
    assert body["decision"]["status_code"] == issues[0]["status"] == "FAIL"


def test_unknown_topic_and_bad_target(data):
    client, plant = data["client"], data["plant"]
    assert client.get(f"/api/v1/plants/{plant}/{ASK}", params={"topic": "weather"}).status_code == 422
    assert client.get(f"/api/v1/plants/{plant}/{ASK}").status_code == 422
    bad = client.get(f"/api/v1/plants/{plant}/{ASK}", params={"topic": "trend", "target": "a|b"})
    assert bad.status_code == 422 and "domain|layer|model|color|orient" in bad.text
    assert client.get(f"/api/v1/plants/{plant}/{ASK}", params={"topic": "summary", "month": "2026-13"}).status_code == 422
    assert client.get(f"/api/v1/plants/NOPE404/{ASK}", params={"topic": "summary"}).status_code == 404


def test_missing_target_box_is_not_enough_data(data):
    target = f"wavescan||{RANGER}|{WHITE}|Horizontal"
    found = get(data, ASK, topic="trend", month=NOW, target=target)
    assert found["status"] == "not_enough_data"
    assert found["decision"]["headline"] == "Only 1 measuring day this month; 5 needed."
    body = get(data, ASK, topic="trend", month=NOW, target=target, models=[RAPTOR])
    assert body["status"] == "not_enough_data"
    assert body["decision"]["headline"] == "That box has no readings for February 2099 with these filters."
    _clean(body)


def test_assistant_grades_nothing_itself():
    app = Path(__file__).resolve().parents[1] / "app"
    for path in [app / "services" / "assistant.py", *(app / "domain" / "assistant").glob("*.py")]:
        source = path.read_text(encoding="utf-8")
        assert "domain.grading" not in source and "status_of" not in source, path.name
        for word in ("UPDATE ", "DELETE ", "INSERT "):
            assert word not in source, (path.name, word)


# ---- final whole-branch review fixes ----
def test_changes_counts_noise_worse_separately():
    a = changes([_cb(LOW, status="FAIL")], [_cb(LOW, status="PASS")], "2026-09")
    assert a.headline == "1 box got worse (0 real shifts)"
    assert_clean(a)
    two = changes([_cb(LOW, status="FAIL"), _cb(HIGH, model="B", status="FAIL")],
                  [_cb(LOW, status="PASS"), _cb(LOW, model="B", status="PASS")], "2026-09")
    assert two.headline == "2 boxes got worse (1 real shift)"


def test_changes_status_none_counts_as_same():
    assert changes([_cb(LOW, status="FAIL")], [_cb(LOW, status=None)], "2026-09").status == "all_clear"
    assert changes([_cb(LOW, status=None)], [_cb(LOW, status="FAIL")], "2026-09").status == "all_clear"
    assert shifts([_cb(LOW, status="PASS")], [_cb(LOW, status=None)])[0].move == "same"


def test_points_skipped_no_limit_caveat():
    a = points(_film_pts(), skipped_no_limit=5)
    assert a.method["caveats"] == ["5 readings skipped: no limit"]
    assert points(_film_pts()).method["caveats"] == []
    e = points([], skipped_no_limit=1)
    assert e.status == "not_enough" and e.method["caveats"] == ["1 reading skipped: no limit"]
    assert_clean(a)


def test_bands_film_filtered_out():
    now, before = _rise()
    a = bands(now, before, None, film_filtered=True)
    assert a.proof == "Film is filtered out, so the layer check is skipped."
    assert a.confidence == "exploratory"
    assert_clean(a)
    b = bands(now, before, [])
    assert b.proof == "Not enough paired cars to check." and b.confidence == "solid"


def test_trend_history_status_uses_box_scope():
    box = _tb([10, 11, 10, 11, 10, 11, 10, 11], scope="COLOR", status=None)
    a = trend(box, None, [MonthPoint("2026-10", 10.5, None)])
    assert a.evidence["rows"] == [["October 2026", 10.5, "Not graded"]]


def test_bands_service_flags_film_filtered(data, monkeypatch):
    import app.services.assistant as svc

    seen = []

    def spy(now, before, paired, *, film_filtered=False):
        seen.append((paired, film_filtered))
        return bands(now, before, paired, film_filtered=film_filtered)

    monkeypatch.setattr(svc, "bands", spy)
    get(data, ASK, topic="bands", month=NOW, domain="wavescan")
    get(data, ASK, topic="bands", month=NOW, domain="both")
    assert seen[0] == (None, True)
    assert seen[1][0] is not None and seen[1][1] is False
