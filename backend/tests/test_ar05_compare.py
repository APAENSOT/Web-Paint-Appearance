"""AR05 Task 6: compare core, models, colours, orientation, months."""

from __future__ import annotations

from datetime import date

from app.domain.assistant.answer import Box
from app.domain.assistant.compare import Verdict, compare_values, difference_words, group_stats
from app.domain.assistant.compare_topics import compare_colours, compare_models, compare_months, compare_orient
from app.domain.assistant.readings import Reading
from tests.test_ar03_analysis_report import NOW, data, get  # noqa: F401
from tests.test_ar04_assistant import assert_clean

D = date(2026, 2, 3)
RAPTOR, RANGER = "P703 DBL RAPTOR", "P703 DBL RANGER"
HI = [20.0 + 0.1 * i for i in range(12)]
LO = [v - 4.0 for v in HI]


def _box(model, color, orient, values, status="PASS", layer="CLEAR", lsl=2.0):
    return Box("film", layer, model, color, orient, status, None, lsl, None, "µm", tuple(values), (D,) * len(values))


def _rs(box, metric="CLEAR"):
    return [Reading("film", box.layer, box.model, box.color, None, box.orient, "P", None, D, metric, v, False, box.key)
            for v in box.values]


def test_compare_values_rules():
    v = compare_values(LO, HI)
    assert v and v.real and round(v.delta, 1) == -4.0 and (v.n_a, v.n_b) == (12, 12)
    noise = compare_values([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [2, 1, 4, 3, 6, 5, 8, 7, 10, 9])
    assert noise and not noise.real
    assert compare_values(LO[:7], HI) is None and compare_values(LO, HI[:9]) is None


def test_words_and_stats():
    assert difference_words(Verdict(True, -4.1, 0.01, 12, 12), "µm", "RAPTOR", "RANGER", "Clear") == (
        "RAPTOR is 4.1 µm thinner on Clear than RANGER — real difference")
    assert difference_words(Verdict(True, 2.0, 0.01, 12, 12), "", "A", "B", "CF") == (
        "A is 2.0 higher on CF than B — real difference")
    assert difference_words(Verdict(False, 0.34, 0.5, 12, 12), "µm", "A", "B", "Base") == (
        "No real difference on Base (A vs B, Δ 0.3 µm)")
    g = group_stats("X", [1.0, 2.0, 3.0, 4.0])
    assert g["label"] == "X" and g["n"] == 4 and g["median"] == 2.5 and g["mean"] == 2.5
    assert set(g) == {"label", "n", "q1", "median", "q3", "low", "high", "mean"}


def test_compare_models_real_noise_and_few():
    a, b = _box(RAPTOR, "Blue", "Vertical", LO, "FAIL"), _box(RANGER, "Blue", "Vertical", HI)
    rs = _rs(a) + _rs(b)
    ans = compare_models(RAPTOR, RANGER, "CLEAR", rs, [a, b])
    assert_clean(ans)
    assert ans.headline == "RAPTOR is 4.0 µm thinner on Clear than RANGER — real difference"
    ev = ans.evidence
    assert ev["kind"] == "boxplot_pair" and [g["label"] for g in ev["groups"]] == ["RAPTOR", "RANGER"]
    assert ev["limits"] == {"lo": 2.0, "hi": None} and ans.confidence == "solid"
    assert [f["topic"] for f in ans.followups] == ["why_failing", "compare_colours"]
    assert ans.followups[0]["target"] == a.key
    noise = compare_models(RANGER, "OTHER", "CLEAR", _rs(b) + _rs(_box("OTHER", "Blue", "Vertical", HI[::-1])), [b])
    assert noise.headline.startswith("No real difference on Clear (RANGER vs OTHER")
    few = compare_models(RAPTOR, RANGER, "CLEAR", _rs(_box(RAPTOR, "Blue", "Vertical", LO[:7])) + _rs(b), [b])
    assert few.status == "not_enough" and few.headline == "RAPTOR 7, RANGER 12 readings; 10 needed each."


def test_limits_differ_caveat():
    a, b = _box(RAPTOR, "Blue", "Vertical", LO), _box(RANGER, "Blue", "Vertical", HI, lsl=3.0)
    ans = compare_models(RAPTOR, RANGER, "CLEAR", _rs(a) + _rs(b), [a, b])
    assert ans.evidence["limits"] is None
    assert "Limits differ between the groups, so none are drawn." in ans.method["caveats"]


def test_colours_and_orient():
    a, b = _box(RAPTOR, "Blue", "Vertical", LO), _box(RAPTOR, "Red", "Vertical", HI)
    c = compare_colours("Blue", "Red", "CLEAR", _rs(a) + _rs(b), [a, b])
    assert c.headline == "Blue is 4.0 µm thinner on Clear than Red — real difference"
    assert c.followups[-1]["topic"] == "compare_models"
    h, v = _box(RAPTOR, "Blue", "Horizontal", HI), _box(RAPTOR, "Blue", "Vertical", LO)
    o = compare_orient("Blue", "CLEAR", _rs(h) + _rs(v) + _rs(_box(RAPTOR, "Red", "Vertical", HI)), [h, v])
    assert o.headline == "Horizontal is 4.0 µm thicker on Clear than Vertical — real difference"
    assert [g["n"] for g in o.evidence["groups"]] == [12, 12]
    assert_clean(c)
    assert_clean(o)


def test_compare_months_uses_month2_boxes():
    now = [_box(RAPTOR, "Blue", "Vertical", HI)]
    old = [_box(RAPTOR, "Blue", "Vertical", LO)]
    a = compare_months(now, old, "2026-02", "2025-12")
    assert_clean(a)
    assert a.evidence["kind"] == "shift" and "December 2025" in " ".join(
        [a.headline, a.method["rule"], *map(str, a.evidence["rows"][0])] + a.method["caveats"] + [a.proof])
    assert compare_months(now, [], "2026-02", "2025-12").headline == "No December 2025 data to compare."


def test_endpoints(data):
    from tests.test_ar03_analysis_report import BEFORE, RANGER as R2, RAPTOR as R1

    a = get(data, "analysis/ask", topic="compare_models", month=NOW, a=R1, b=R2, metric="CLEAR")
    assert a["status"] in ("answer", "all_clear", "not_enough_data")
    if a["status"] == "answer":
        assert a["evidence"]["kind"] == "boxplot_pair"
    o = get(data, "analysis/ask", topic="compare_orient", month=NOW, colour="x", metric="CLEAR")
    assert o["status"] == "needs_slot"


def test_endpoint_months_and_orient_run(data):
    from tests.test_ar03_analysis_report import BEFORE, RANGER as R2, RAPTOR as R1

    m = get(data, "analysis/ask", topic="compare_months", month=NOW, month2=BEFORE)
    assert m["status"] != "needs_slot" and m["evidence"]["kind"] in ("shift", None)
    c = get(data, "analysis/ask", topic="compare_models", month=NOW, a=R1, b=R2, metric="CLEAR")
    assert c["status"] != "needs_slot"
    assert c["evidence"]["kind"] == "boxplot_pair" or c["status"] == "not_enough_data"


from app.domain.assistant.compare_topics import compare_families, compare_sides  # noqa: E402


def _pts(point, values, family=None, box=None, out=False, metric="CLEAR"):
    b = box or _box(RAPTOR, "Blue", "Vertical", values)
    return [Reading("film", "CLEAR", RAPTOR, b.color, family, b.orient, point, None, D, metric, v, out, b.key)
            for v in values]


def test_compare_sides_real_and_few():
    rs = []
    for panel in ("BOXSIDE", "DOOR", "FENDER"):
        rs += _pts(f"094R{panel}", HI) + _pts(f"101L{panel}", LO)
    rs += _pts("CFHOOD", HI)
    ans = compare_sides("CLEAR", rs, [])
    assert_clean(ans)
    assert ans.headline == "Left runs 4.0 µm thinner on Clear — real difference (biggest at BOXSIDE)"
    assert ans.evidence["kind"] == "mirrored_bar" and ans.evidence["columns"] == ["Panel", "Left", "Right", "Δ", "Verdict"]
    assert ans.evidence["rows"][0][3:] == ["-4.0", "Real difference"]
    assert ans.method["caveats"] == ["1 points without a side left out"]
    flat = [r for r in rs if r.point != "CFHOOD"]
    same = compare_sides("CLEAR", [Reading(**{**r.__dict__, "value": 20.0 + (i % 3)}) for i, r in enumerate(flat)], [])
    assert same.headline == "No real left–right difference on Clear"
    two = compare_sides("CLEAR", [r for r in rs if "FENDER" not in str(r.point)], [])
    assert two.status == "not_enough" and two.headline == "Not enough left–right panel pairs to compare."


def test_compare_families():
    dark, light = _box(RAPTOR, "Black", "Vertical", LO, "FAIL"), _box(RAPTOR, "White", "Vertical", HI)
    rs = _pts("P", LO, "Dark metallic", dark, True) + _pts("P", HI, None, light)
    ans = compare_families("CLEAR", rs, [dark, light])
    assert_clean(ans)
    assert ans.headline == "Dark metallic drives 1 of 1 Clear problems"
    assert ans.proof.startswith("Dark metallic is 4.0 µm thinner on Clear than the other families")
    ev = ans.evidence
    assert ev["kind"] == "boxplot_group" and [g["label"] for g in ev["groups"]] == ["Dark metallic", "No family"]
    other = compare_families("DU", rs, [dark, light])
    assert other.status == "not_enough" and other.headline.endswith("has no standard, so no family has problems to count.")


# ---- Task 8: cars and plants ----
from app.domain.assistant.compare_topics import compare_cars, compare_plants  # noqa: E402


def _car(car, points, layer="CLEAR", outs=(), domain="film"):
    return [Reading(domain, layer, RAPTOR, "Blue", None, "Vertical", p, car, D, layer, v, p in outs, "k")
            for p, v in points.items()]


def test_compare_cars_all_on_one_panel():
    pts = {"094RROOF": 20.0, "101LROOF": 21.0, "050HOOD": 22.0, "060DECK": 23.0}
    rs = _car("11", pts) + _car("22", {**pts, "094RROOF": 10.0, "101LROOF": 11.0}, outs=("094RROOF", "101LROOF"))
    ans = compare_cars("11", "22", rs, {"22": "1234567"})
    assert_clean(ans)
    assert ans.headline == "Car 1234567 is out at 2 of 4 points, all on ROOF"
    ev = ans.evidence
    assert ev["kind"] == "point_bars" and ev["columns"] == ["Layer", "Point", "Car A", "Car B", "Out"]
    assert ["Clear", "094RROOF", "20.0", "10.0", "B out"] == [str(x) for x in next(r for r in ev["rows"] if r[1] == "094RROOF")]
    mixed = _car("22", pts, outs=("094RROOF", "050HOOD"))
    m = compare_cars("11", "22", _car("11", pts) + mixed)
    assert m.headline == "Car 22 is out at 2 of 4 points"
    one = compare_cars("11", "22", _car("11", pts) + _car("22", pts, outs=("050HOOD",)))
    assert one.headline == "Car 22 is out at 1 of 4 points"
    stem = compare_cars("11", "22", _car("11", pts) + _car("22", {"01HOOD": 1.0, "02HOOD": 1.0}, outs=("01HOOD", "02HOOD")))
    assert stem.headline == "Car 22 is out at 2 of 2 points, all on HOOD"
    none = compare_cars("11", "22", _car("11", pts) + _car("22", pts))
    assert none.headline == "Car 22 has no points out (4 measured)"
    gap = compare_cars("11", "22", _car("11", {"050HOOD": 22.0}) + _car("22", {"060DECK": 5.0}))
    assert sorted(r[1] for r in gap.evidence["rows"]) == ["050HOOD", "060DECK"]
    assert [r[2:4] for r in gap.evidence["rows"] if r[1] == "050HOOD"] == [["22.0", "—"]]


def test_compare_cars_wave_scan_copy():
    rs = _car(None, {"A": 1.0}, domain="wavescan")
    ans = compare_cars("1", "2", rs)
    assert ans.status == "not_enough"
    assert ans.headline == "Car questions use Film cars; Wave Scan readings are not linked to cars here."


def _model(model, vals, family="Dark metallic"):
    return [Reading("film", "PRIMER", model, "Blue", family, "Vertical", "P", None, D, "PRIMER", v, False, "k")
            for v in vals]


def test_compare_plants():
    here = _model(RAPTOR, HI) + _model(RANGER, HI[:3])
    there = _model(RAPTOR, LO) + _model(RANGER, LO)
    ans = compare_plants("AAT", "U704", "PRIMER", here, there, [], "2026-02")
    assert_clean(ans)
    assert ans.headline == "RAPTOR: AAT is 4.0 µm thicker on Primer than U704 — real difference"
    assert ans.evidence["kind"] == "boxplot_pair" and ans.evidence["limits"] is None
    assert ans.method["caveats"] == ["Each plant has its own limits, so none are drawn."]
    one = compare_plants("AAT", "U704", "PRIMER", here, there, [RANGER], "2026-02")
    assert one.status == "not_enough"  # only 3 readings here
    miss = compare_plants("AAT", "U704", "PRIMER", here, _model("P703 DBL OTHER", LO), [RAPTOR], "2026-02")
    assert miss.headline == "U704 has no RAPTOR readings in February 2026."
    none = compare_plants("AAT", "U704", "PRIMER", here, _model("P703 DBL OTHER", LO), [], "2026-02")
    assert none.headline == "U704 shares no model with AAT in February 2026."
    fam = compare_plants("AAT", "U704", "PRIMER", here, _model(RAPTOR, LO, "Light"), [], "2026-02")
    assert fam.status == "not_enough"


def test_car_label_and_wavescan_slot(monkeypatch):
    from types import SimpleNamespace

    from app.domain.assistant.catalog import by_id
    from app.services.assistant import MonthData
    from app.services.assistant_slots import car_labels, resolve

    r = Reading("film", "CLEAR", RAPTOR, "Blue", None, "Vertical", "P", "77", D, "CLEAR", 1.0, False, "k", "AB1234567X")
    ctx = SimpleNamespace(conn=None, plant="X", used="2026-02", domain="both",
                          load=lambda m: MonthData([], [], [], 0, [r]))
    import app.services.assistant_slots as s
    monkeypatch.setattr(s, "pairing_repo", SimpleNamespace(car_rule=lambda conn, plant: {"pattern": r"(\d{7})", "note": ""}))
    assert car_labels(ctx) == {"77": "1234567"}
    monkeypatch.setattr(s, "pairing_repo", SimpleNamespace(car_rule=lambda conn, plant: None))
    assert car_labels(ctx) == {"77": "77"}
    ctx.domain = "wavescan"
    out = resolve(by_id("compare_cars"), {}, ctx)
    assert out.status == "not_enough" and out.headline.startswith("Car questions use Film cars")


def test_compare_cars_plants_endpoints(data):
    c = get(data, "analysis/ask", topic="compare_cars", month=NOW)
    assert c["status"] in ("needs_slot", "not_enough_data")
    p = get(data, "analysis/ask", topic="compare_plants", month=NOW, plant2="NOPE", metric="PRIMER")
    assert p["status"] == "not_enough_data"  # no other plant to offer (final I5)
