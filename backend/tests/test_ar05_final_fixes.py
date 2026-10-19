"""AR05 final whole-change review fixes (C1, C2, I3-I8, minors)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.domain.assistant.answer import Box
from app.domain.assistant.appearance import appearance_profile, cf_drivers, layer_vs_band
from app.domain.assistant.compare_topics import compare_colours, compare_models, compare_months, compare_sides
from app.domain.assistant.problem import cars_or_process, centre_or_spread, why_failing
from app.domain.assistant.readings import Reading
from app.domain.assistant.report_grids import colour_report, model_report, recurring
from tests.test_ar03_analysis_report import NOW, data, get  # noqa: F401
from tests.test_ar04_assistant import assert_clean
from tests.test_ar05_appearance import _box as _ws_box, _cf, _month, _paired
from tests.test_ar05_compare import HI, LO, RANGER, RAPTOR, _box, _pts, _rs
from tests.test_ar05_grids import _b
from tests.test_ar05_problem import _box as _pbox, _cs, _grid


# ---- C1: compare_months keeps time order
def test_compare_months_later_month2_is_now():
    early = [_box(RAPTOR, "Blue", "Vertical", LO)]   # December 2025
    late = [_box(RAPTOR, "Blue", "Vertical", HI)]    # February 2026
    a = compare_months(early, late, "2025-12", "2026-02")
    assert_clean(a)
    assert a.headline.endswith("since December 2025")
    assert a.evidence["rows"][0][3] == "+4.0 µm"
    same = compare_months(late, early, "2026-02", "2025-12")
    assert (same.headline, same.evidence["rows"]) == (a.headline, a.evidence["rows"])


# ---- C2: spread counts only when σ grew; small moves are no change
def test_centre_sigma_halved_is_not_spread():
    b = _cs(30.0, 1.0)
    a = centre_or_spread(b, _cs(30.0, 2.0), None, "2026-09")
    assert "spread —" not in a.headline and a.next_step is None
    assert a.headline == f"{b.label}: no meaningful change in centring or spread since September 2026"
    t = centre_or_spread(b, _cs(30.0, 2.0), 30.2)
    assert "spread —" not in t.headline and "Reduce" not in (t.next_step or "")


def test_centre_small_move_is_no_meaningful_change():
    b = _cs(30.2, 2.0)
    a = centre_or_spread(b, _cs(30.0, 2.0), None, "2026-09")
    assert a.headline == f"{b.label}: no meaningful change in centring or spread since September 2026"
    assert a.next_step is None
    grew = centre_or_spread(_cs(30.0, 2.6), _cs(30.0, 2.0), None)
    assert grew.headline.endswith("spread — σ 2.6 µm vs 2.0 µm last month")


# ---- I3: cars_or_process needs 5 cars
def test_cars_or_process_needs_five_cars():
    box = _pbox()
    a = cars_or_process(box, _grid(box, lambda c, p: c == 1, cars=4))
    assert a.status == "not_enough" and a.headline == "4 cars; 5 needed to tell a few cars from the process."
    one = cars_or_process(box, _grid(box, lambda c, p: c == 1, cars=1))
    assert one.headline == "1 car; 5 needed to tell a few cars from the process."


# ---- I4: layer_vs_band takes a band; constant side; all-months caveat
def test_layer_vs_band_constant_side_and_caveat():
    a = layer_vs_band("CLEAR", "wa", _paired())
    assert a.method["caveats"] == ["Uses paired cars from all months."]
    flat = [dict(r, wa=5.0) for r in _paired()]
    c = layer_vs_band("CLEAR", "wa", flat)
    assert c.status == "not_enough"
    assert c.headline == "Clear or Wa didn't vary across the paired cars, so no link can be measured."


def test_layer_vs_band_slot_is_a_band():
    from app.domain.assistant.catalog import by_id
    from app.services.assistant import MonthData
    from app.services.assistant_slots import resolve

    q = by_id("layer_vs_band")
    assert [s.kind for s in q.slots] == ["layer", "band"]
    box = Box("film", "CLEAR", "M1", "Red", "Horizontal", "FAIL", None, 40, None, "µm", (1.0,), ())
    ws = [Reading("wavescan", None, "M1", "Red", None, "Vertical", "P", None, date(2099, 2, 3), m, 1.0, None, "k")
          for m in ("lw", "doi", "wa", "cf", "b")]
    ctx = SimpleNamespace(used="2099-02", months=["2099-02"], domain="both",
                          load=lambda m: MonthData([box], [], [], 0, ws))
    got = resolve(q, {"layer": "CLEAR"}, ctx)
    assert [c["value"] for c in got.slot["choices"]] == ["wa", "cf"]


def test_layer_vs_band_422_outside_bands(data):  # noqa: F811
    url = f"/api/v1/plants/{data['plant']}/analysis/ask"
    bad = data["client"].get(url, params={"topic": "layer_vs_band", "layer": "CLEAR", "metric": "lw"})
    assert bad.status_code == 422 and "du, wa, wb, wc, wd, we, cf" in bad.text
    ok = data["client"].get(url, params={"topic": "compare_sides", "metric": "lw"})
    assert ok.status_code == 200


# ---- I5: a sent value with zero options is not a chip-less ask
def test_sent_value_with_no_options_is_not_enough():
    from app.domain.assistant.catalog import by_id
    from app.services.assistant import MonthData
    from app.services.assistant_slots import resolve

    ctx = SimpleNamespace(used="2099-02", months=["2099-02"], domain="both", load=lambda m: MonthData([], [], []))
    got = resolve(by_id("why_failing"), {"target": "film|CLEAR|M|C|V"}, ctx)
    assert got.status == "not_enough" and got.slot is None
    assert got.headline == "No readings for film|CLEAR|M|C|V in February 2099 with these filters."


# ---- I6: the other plant ignores the colour filter
def test_compare_plants_loads_other_plant_without_colours(data, monkeypatch):  # noqa: F811
    import app.services.assistant as svc

    seen = []
    real = svc.load_month

    def spy(conn, plant, month, **kw):
        seen.append((plant, kw["colors"]))
        return real(conn, plant, month, **kw)

    monkeypatch.setattr(svc, "load_month", spy)
    monkeypatch.setattr(svc.assistant_slots, "resolve", lambda q, p, c: {"plant2": "OTHERX", "metric": "PRIMER"})
    svc.answer(data["conn"], data["plant"], plant_scope=None, month=NOW, domain="both", models=[],
               colors=["Arctic White"], topic="compare_plants", target=None)
    assert ("OTHERX", []) in seen and (data["plant"], ["Arctic White"]) in seen


# ---- I7: pooled orientations caveat
def test_compare_pools_orientations_caveat():
    ah, av = _box(RAPTOR, "Blue", "Horizontal", LO), _box(RAPTOR, "Blue", "Vertical", LO)
    bv = _box(RANGER, "Blue", "Vertical", HI)
    a = compare_models(RAPTOR, RANGER, "CLEAR", _rs(ah) + _rs(av) + _rs(bv), [ah, av, bv])
    assert "Both orientations pooled: RAPTOR H 12 / V 12, RANGER H 0 / V 12." in a.method["caveats"]
    one = compare_models(RAPTOR, RANGER, "CLEAR", _rs(av) + _rs(bv), [av, bv])
    assert not any("pooled" in c for c in one.method["caveats"])
    rh, bv2 = _box(RAPTOR, "Red", "Horizontal", HI), _box(RAPTOR, "Blue", "Vertical", LO)
    c = compare_colours("Blue", "Red", "CLEAR", _rs(rh) + _rs(bv2), [rh, bv2])
    assert "Both orientations pooled: Blue H 0 / V 12, Red H 12 / V 0." in c.method["caveats"]


# ---- I8a: biggest panel goes the same way as the overall gap
def test_compare_sides_biggest_has_overall_sign():
    rs = []
    for panel in ("BOXSIDE", "DOOR", "FENDER"):
        rs += _pts(f"094R{panel}", HI) + _pts(f"101L{panel}", LO)
    rs += _pts("094RROOF", HI) + _pts("101LROOF", [v + 10 for v in HI])
    a = compare_sides("CLEAR", rs, [])
    assert "thinner" in a.headline and a.headline.endswith("(biggest at BOXSIDE)")


# ---- I8b: side word only when every named point is on that side
def test_why_failing_points_on_both_sides_have_no_side_word():
    box = _pbox()
    out = lambda c, p: (p == "R-12" and c <= 27) or (p == "L-05" and c <= 25) or (p == "R-14" and c <= 24)  # noqa: E731
    a = why_failing(box, _grid(box, out, cars=60, day=lambda c: date(2026, 2, 1 + c % 28)))
    assert a.headline.startswith(f"{box.label}: concentrated at R-12 and L-05")
    assert "right" not in a.headline and "left" not in a.headline
    assert ["Side", "right", 51, 120] in a.evidence["rows"]  # the side did concentrate


# ---- I8c: only du..we can be marked high
def test_profile_marks_only_bands_high():
    a = appearance_profile("Red", _month(("doi", "lw", "sw")))
    assert a.status == "all_clear"
    assert all(r[4] == "" for r in a.evidence["rows"])
    b = appearance_profile("Red", _month(("wd", "doi")))
    assert {r[0]: r[4] for r in b.evidence["rows"]}["doi"] == ""


# ---- minors
def test_colour_report_month_words_and_no_standard_copy():
    assert colour_report([], [], "2026-09", None).headline == "No boxes for September 2026 with these filters."
    a = colour_report([_b("Blue", "PASS"), _b("Red", None)], [], "2026-02", None)
    assert a.status == "all_clear"
    assert a.headline == "No box is Fail, Over or For Improvement (1 without a standard)."
    m = model_report("P703 DBL RANGER", [_b("Blue", "PASS"), _b("Red", None), _b("Red", None, "BASE")], [])
    assert m.headline == "No box is Fail, Over or For Improvement (2 without a standard)."
    assert colour_report([_b("Blue", "PASS")], [], "2026-02", None).headline == "All 1 colours Pass this month."


def test_cf_drivers_headline_top_two():
    a = cf_drivers(_ws_box(), _cf(neg=("wb", "wc", "wd")))
    assert a.headline == f"{_ws_box().label}: CF loss tracks Wb and Wc (ρ -1.0, -1.0)"
    assert [r[0] for r in a.evidence["rows"][:3]] == ["Wb", "Wc", "Wd"]


def test_recurring_why_only_for_box_in_used_month():
    def bx(status):
        return Box("film", "CLEAR", "M", "Blue", "Vertical", status, None, 2.0, None, "µm", (1.0,), ())

    other = Box("film", "BASE", "M", "Blue", "Vertical", "PASS", None, 2.0, None, "µm", (1.0,), ())
    by_month = {"2026-01": [bx("FAIL")], "2026-02": [bx("FAIL")], "2026-03": [bx("FAIL")], "2026-04": [other]}
    a = recurring(by_month, "2026-04")
    assert [f["topic"] for f in a.followups] == ["history"]
    by_month["2026-04"] = [bx("FAIL")]
    assert [f["topic"] for f in recurring(by_month, "2026-04").followups] == ["history", "why_failing"]


def test_runner_rules_are_never_empty(monkeypatch):
    import app.services.assistant as svc
    from app.services.assistant import MonthData

    ctx = SimpleNamespace(load=lambda m: MonthData([], [], []), used="2026-02", plant="X", plant_scope=["Y"])
    assert svc._drivers(ctx, {"target": "a|b|c|d|e"}).method["rule"]
    assert svc._pairing(ctx, {}).method["rule"]
