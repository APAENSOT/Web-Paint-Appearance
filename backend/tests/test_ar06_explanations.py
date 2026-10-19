"""AR06 Task 1: the plain-language `explanation` paragraph for the month and compare questions."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from app.domain.assistant.answer import Box, PointReading, not_enough
from app.domain.assistant.changes import changes
from app.domain.assistant.colours import colours
from app.domain.assistant.compare_topics import (compare_cars, compare_colours, compare_families, compare_models,
                                                 compare_months, compare_orient, compare_plants, compare_sides)
from app.domain.assistant.plain_words import BANNED, capability_sentence, difference_sentence
from app.domain.assistant.points import points
from app.domain.assistant.readings import Reading
from app.domain.assistant.report_grids import colour_report, model_report, weekly, went_well
from app.domain.assistant.summary import summary
from tests import test_ar04_assistant as t4
from tests import test_ar05_compare as tc
from tests import test_ar05_grids as tg
from tests.test_ar03_analysis_report import NOW, data, get  # noqa: F401


# ---- fixtures (AR04/AR05 builders) ----
def _summary():
    mild = t4._cb(range(30, 42), model="A", status="WARNING")
    bad = t4._cb(range(30, 50), model="B", status="FAIL")
    return summary([mild, t4._cb(range(25, 35), model="C", status="PASS"), bad], [], None)


def _colours():
    worse = t4._film(color="Blue", values=tuple([10.0] * 9 + [25.0] * 25))
    mild = t4._film(color="Red", values=tuple([10.0] * 3 + [25.0] * 31))
    return colours([mild, worse])


def _changes():
    big, big_b = t4._cb(t4.HIGH, model="M2", status="PASS"), t4._cb(t4.LOW, model="M2", status="PASS")
    worse = t4._cb(t4.HIGH, status="FAIL", usl=32.0, lsl=None)
    worse_b = t4._cb(t4.LOW, status="PASS", usl=32.0, lsl=None)
    return changes([big, worse], [big_b, worse_b], "2026-09")


def _models():
    a = tc._box(tc.RAPTOR, "Blue", "Vertical", tc.LO, "FAIL")
    b = tc._box(tc.RANGER, "Blue", "Vertical", tc.HI)
    return compare_models(tc.RAPTOR, tc.RANGER, "CLEAR", tc._rs(a) + tc._rs(b), [a, b])


def _pooled_colours():
    boxes = [tc._box(tc.RAPTOR, c, o, v) for c, v in (("Blue", tc.LO), ("Red", tc.HI)) for o in ("Horizontal", "Vertical")]
    return compare_colours("Blue", "Red", "CLEAR", [r for b in boxes for r in tc._rs(b)], boxes)


def _orient():
    h, v = tc._box(tc.RAPTOR, "Blue", "Horizontal", tc.HI), tc._box(tc.RAPTOR, "Blue", "Vertical", tc.LO)
    return compare_orient("Blue", "CLEAR", tc._rs(h) + tc._rs(v), [h, v])


def _months():
    now = [tc._box(tc.RAPTOR, "Blue", "Vertical", tc.HI, "FAIL")]
    old = [tc._box(tc.RAPTOR, "Blue", "Vertical", tc.LO)]
    return compare_months(now, old, "2026-02", "2025-12")


def _sides(same=False):
    rs = []
    for panel in ("BOXSIDE", "DOOR", "FENDER"):
        rs += tc._pts(f"094R{panel}", tc.HI) + tc._pts(f"101L{panel}", tc.LO)
    if same:
        rs = [Reading(**{**r.__dict__, "value": 20.0 + (i % 3)}) for i, r in enumerate(rs)]
    return compare_sides("CLEAR", rs, [])


def _families():
    dark, light = tc._box(tc.RAPTOR, "Black", "Vertical", tc.LO, "FAIL"), tc._box(tc.RAPTOR, "White", "Vertical", tc.HI)
    rs = tc._pts("P", tc.LO, "Dark metallic", dark, True) + tc._pts("P", tc.HI, None, light)
    return compare_families("CLEAR", rs, [dark, light])


PTS = {"094RROOF": 20.0, "101LROOF": 21.0, "050HOOD": 22.0, "060DECK": 23.0}


def _cars():
    rs = tc._car("11", PTS) + tc._car("22", {**PTS, "094RROOF": 10.0, "101LROOF": 11.0}, outs=("094RROOF", "101LROOF"))
    return compare_cars("11", "22", rs, {"22": "1234567"})


def _cars_none():
    return compare_cars("11", "22", tc._car("11", PTS, outs=("050HOOD",)) + tc._car("22", PTS))


def _plants():
    here = tc._model(tc.RAPTOR, tc.HI) + tc._model(tc.RANGER, tc.HI[:3])
    there = tc._model(tc.RAPTOR, tc.LO) + tc._model(tc.RANGER, tc.LO)
    return compare_plants("AAT", "U704", "PRIMER", here, there, [], "2026-02")


def _colour_report():
    now = [tg._b("Blue", "FAIL", values=(1, 1, 1, 1, 1, 1, 1, 3, 3, 3)), tg._b("Blue", "PASS", "BASE"),
           tg._b("Red", "PASS"), tg._b("Green", "WARNING", "PRIMER", orient="Horizontal")]
    return colour_report(now, [tg._b("Blue", "PASS")], "2026-02", "2026-01")


def _model_report():
    now = [tg._b("Blue", "FAIL"), tg._b("Red", "PASS"), tg._b("Red", "PASS", "BASE"),
           tg._b("Red", "PASS", orient="Horizontal")]
    return model_report("P703 DBL RANGER", now, [tg._b("Blue", "PASS")])


def _went_well():
    now = [tg._b("Blue", "PASS", values=tg.HIGH), tg._b("Red", "PASS", values=tg.HIGH, layer="BASE"),
           tg._b("Gold", "PASS", values=(10.0, 10.1) * 5, layer="PRIMER")]
    before = [tg._b("Blue", "FAIL", values=tg.LOW), tg._b("Red", "PASS", values=tg.HIGH, layer="BASE")]
    return went_well(now, before, "2026-01")


def _weekly():
    rs = [tg._r("film", date(2026, 2, 10), True) for _ in range(6)]
    rs += [tg._r("film", date(2026, 2, 3), False) for _ in range(30)]
    rs += [tg._r("film", None, True) for _ in range(5)]
    return weekly(rs)


def _weekly_spread():
    return weekly([tg._r("film", date(2026, 2, d), i % 2 == 0) for i, d in enumerate([2, 9, 16, 23] * 5)])


# (id, builder, words that must appear: the headline's subject and key number)
ANSWERS = [
    ("summary", _summary, ["Red Primer on the B", "9 of 20"]),
    ("summary", lambda: summary([t4._cb(range(25, 35), status="PASS")], [], None), ["1 box"]),
    ("colours", _colours, ["Blue Primer on the M1", "9 of 34"]),
    ("colours", lambda: colours([t4._film(status="PASS", values=tuple(30.0 + (i % 5) for i in range(20)))]),
     ["colour"]),
    ("points", lambda: points(t4._film_pts()), ["P1", "7 of 8"]),
    ("points", lambda: points([PointReading("film", f"P{p}", f"C{c}", p == 1 and c == 0)
                               for p in range(1, 21) for c in range(8)]), ["point"]),
    ("changes", _changes, ["1 box got worse", "10.0 µm"]),
    ("changes", lambda: changes([t4._cb(t4.LOW)], [t4._cb(t4.LOW)], "2026-09"), ["September 2026"]),
    ("changes", lambda: changes([t4._cb(t4.LOW, status="PASS")], [t4._cb(t4.LOW, status="FAIL")], "2026-09"),
     ["1 box recovered"]),
    ("compare_months", _months, ["December 2025", "4.0 µm"]),
    ("compare_models", _models, ["RAPTOR", "RANGER", "4.0 µm"]),
    ("compare_colours", _pooled_colours, ["Blue", "Red", "4.0 µm"]),
    ("compare_orient", _orient, ["Horizontal", "Vertical", "4.0 µm"]),
    ("compare_sides", _sides, ["Left", "4.0 µm", "BOXSIDE"]),
    ("compare_sides", lambda: _sides(same=True), ["Left", "Clear"]),
    ("compare_families", _families, ["Dark metallic", "1 of 1"]),
    ("compare_cars", _cars, ["Car 1234567", "2 of 4", "ROOF"]),
    ("compare_cars", _cars_none, ["Car 22", "4 measured"]),
    ("compare_plants", _plants, ["RAPTOR", "AAT", "U704", "4.0 µm"]),
    ("colour_report", _colour_report, ["2 of 3 colours", "Blue Clear"]),
    ("colour_report", lambda: colour_report([tg._b("Blue", "PASS"), tg._b("Red", "PASS")], [], "2026-02", None),
     ["2 colours"]),
    ("model_report", _model_report, ["RANGER", "Clear", "1 of 3"]),
    ("went_well", _went_well, ["Blue Clear on the Ranger", "2.0 µm"]),
    ("went_well", lambda: went_well([tg._b("Blue", "PASS", values=tg.WIDE)], [tg._b("Blue", "PASS", values=tg.WIDE)],
                                    "2026-01"), ["January 2026"]),
    ("weekly", _weekly, ["6 of 11", "week 2"]),
    ("weekly", _weekly_spread, ["spread across the weeks"]),
]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.])\s+(?=[A-Z0-9])", text.strip()) if s]


@pytest.mark.parametrize("topic,build,must", ANSWERS, ids=[f"{a[0]}-{i}" for i, a in enumerate(ANSWERS)])
def test_paragraph_rules(topic, build, must):
    a = build()
    assert a.status in ("answer", "all_clear"), (topic, a.headline)
    e = a.explanation
    assert e and e.endswith(".") and "!" not in e and "please" not in e.lower()
    n = len(_sentences(e))
    assert (n == 1) if a.status == "all_clear" else (2 <= n <= 3), e
    assert len(e.split()) <= 70, e
    assert not [t for t in BANNED if t in e], e
    assert "%" not in e
    for word in must:
        assert word.lower() in e.lower(), (word, e)
    assert a.to_dict()["explanation"] == e
    t4.assert_clean(a)


def test_headline_subject_and_number_reused():
    """The paragraph repeats the headline's own numbers (Review Focus 1)."""
    for _, build, _ in ANSWERS:
        a = build()
        for num in re.findall(r"\d+ of \d+|\d+\.\d", a.headline):
            assert num in a.explanation, (num, a.headline, a.explanation)


def test_not_enough_and_needs_slot_are_empty():
    assert not_enough("x", 0, "r").explanation == ""
    assert not_enough("x", 0, "r").to_dict()["explanation"] == ""
    assert points([]).explanation == ""
    assert compare_models(tc.RAPTOR, tc.RANGER, "CLEAR", [], []).explanation == ""
    assert changes([], [], None).explanation == ""
    assert weekly([]).explanation == ""


def test_helpers():
    assert capability_sentence(1.5) == "the process holds the standard comfortably"
    assert capability_sentence(1.1) == "the process only just holds the standard"
    assert capability_sentence(0.2) == "the process can't keep it inside the standard"
    assert difference_sentence(tc.Verdict(True, 1, 0.01, 12, 12)) == "a real difference, not day-to-day noise"
    assert difference_sentence(tc.Verdict(False, 1, 0.5, 12, 12)) == "within day-to-day noise"
    assert "Cpk" in BANNED and "binomial" in BANNED


def _ws_colour():
    return colours([t4._box(layer=None, values=tuple([1.0] * 10 + [4.0] * 5))])


def _models_noise():
    b = tc._box(tc.RANGER, "Blue", "Vertical", tc.HI)
    return compare_models(tc.RANGER, "OTHER", "CLEAR", tc._rs(b) + tc._rs(tc._box("OTHER", "Blue", "Vertical", tc.HI[::-1])),
                          [b])


def _families_noise():
    dark, light = tc._box(tc.RAPTOR, "Black", "Vertical", tc.LO, "FAIL"), tc._box(tc.RAPTOR, "White", "Vertical", tc.LO)
    rs = tc._pts("P", tc.LO, "Dark metallic", dark, True) + tc._pts("P", tc.LO[::-1], None, light)
    return compare_families("CLEAR", rs, [dark, light])


REAL = "That's a real difference, not day-to-day noise."
EXACT = {
    "summary": (_summary,
                "Red Primer on the B, horizontal panels, is the box to fix first this month; it's at Fail. "
                "9 of 20 readings were outside the standard even though the film averages 0.5 µm below the high "
                "limit, so the spread is the problem. Next on the list is Red Primer on the A, horizontal panels."),
    "colours": (_colours,
                "Blue Primer on the M1, horizontal panels, is the weakest box this month: the process can't keep it "
                "inside the standard. 9 of 34 readings were under the low limit even though the film averages 1.0 µm "
                "above the low limit, so the spread is the problem. Next weakest is Red Primer, with 3 of 34 readings "
                "under the low limit."),
    "colours_wavescan": (_ws_colour,
                         "Red Wave Scan CF on the M1, horizontal panels, is the weakest box this month: the process "
                         "can't keep it inside the standard. 10 of 15 readings were below the minimum and the CF runs "
                         "0.5 CF points below the minimum on average, so the average itself needs to move."),
    "points": (lambda: points(t4._film_pts()),
               "P1 is a repeat problem on Film: it was out on 7 of 8 cars, against about 1 in 23 across the plant. "
               "That's too often to be bad luck, so the cause sits at that spot rather than in the whole process."),
    "points_one": (lambda: points([PointReading("film", "P1", "C0", False)]),
                   "The 1 measured point is not out more often than normal."),
    "changes": (_changes,
                "1 box got worse since September 2026; the move is a real difference, not day-to-day noise. "
                "The biggest is Red Primer on the M1, horizontal panels, now at Fail after moving 10.0 µm thicker."),
    "compare_months": (_months,
                       "Comparing February 2026 with December 2025, 1 box got worse; the move is a real difference, "
                       "not day-to-day noise. The biggest is Blue Clear on the Raptor, vertical panels, now at Fail "
                       "after moving 4.0 µm thicker."),
    "compare_models": (_models, f"Raptor is 4.0 µm thinner than Ranger on Clear (medians 16.6 µm and 20.6 µm). {REAL}"),
    "compare_models_noise": (_models_noise,
                             "Ranger and Other medians on Clear are 20.6 µm and 20.6 µm, a gap of 0.0 µm. "
                             "That's within day-to-day noise."),
    "compare_colours": (_pooled_colours,
                        f"Blue is 4.0 µm thinner than Red on Clear (medians 16.6 µm and 20.6 µm). {REAL} "
                        "Both orientations are pooled here, so a horizontal–vertical gap could hide inside these numbers."),
    "compare_orient": (_orient,
                       f"Horizontal is 4.0 µm thicker than Vertical on Clear (medians 20.6 µm and 16.6 µm). {REAL}"),
    "compare_sides": (_sides,
                      "Left-side panels run 4.0 µm thinner on Clear than the right, across 3 panel pairs. "
                      "That's a real difference, not day-to-day noise; 3 of 3 panel pairs differ on their own, "
                      "the biggest at BOXSIDE."),
    "compare_families": (_families,
                         "Dark metallic drives 1 of 1 Clear problem boxes this month. Its Clear median runs 4.0 µm "
                         "thinner than the other families', a real difference, not day-to-day noise."),
    "compare_families_noise": (_families_noise,
                               "Dark metallic drives 1 of 1 Clear problem boxes this month. Its Clear readings are "
                               "within day-to-day noise of the other families, so the family doesn't explain the "
                               "problems."),
    "compare_cars": (_cars,
                     "Car 1234567 is out at 2 of 4 measured points, all on the ROOF. Car 11 has no points out on the "
                     "same check, so the trouble is specific to car 1234567."),
    "compare_plants": (_plants,
                       f"AAT is 4.0 µm thicker than U704 on Raptor Primer (medians 20.6 µm and 16.6 µm). {REAL}"),
    "colour_report": (_colour_report,
                      "2 of 3 colours need action this month, and Blue Clear is the place to start. Its worst box is "
                      "on the Ranger, vertical panels, at Fail, with 7 of 10 readings outside the standard. "
                      "1 colour layer slipped to a worse status since January 2026."),
    "colour_report_clear": (lambda: colour_report([tg._b("Blue", "PASS"), tg._b("Red", "PASS")], [], "2026-02", None),
                            "All 2 colours are at Pass on every layer."),
    "colour_report_no_standard": (lambda: colour_report([tg._b("Blue", "PASS"), tg._b("Red", None)], [], "2026-02",
                                                        None),
                                  "No colour has a layer at Fail, Over or For Improvement (1 without a standard)."),
    "model_report": (_model_report,
                     "On the Ranger, Clear is the worst layer this month, with 1 of 3 boxes not at Pass. The worst "
                     "box is Blue on vertical panels, at Fail, with 10 of 10 readings outside the standard."),
    "model_report_clear": (lambda: model_report("P703 DBL RANGER", [tg._b("Blue", "PASS"), tg._b("Red", "PASS")], []),
                           "All 2 Ranger boxes are at Pass."),
    "model_report_no_standard": (lambda: model_report("P703 DBL RANGER", [tg._b("Blue", "PASS"), tg._b("Red", None)],
                                                      []),
                                 "No Ranger layer is at Fail, Over or For Improvement (1 without a standard)."),
    "went_well": (_went_well,
                  "Blue Clear on the Ranger, vertical panels, improved since January 2026. It moved 2.0 µm "
                  "thicker, a real difference, not day-to-day noise, and it's now at Pass. 2 more boxes hold their "
                  "limits comfortably."),
    "weekly": (_weekly,
               "6 of 11 out readings this month came in week 2. That's far more than a normal week's share, "
               "so look for what changed on the line that week."),
    "weekly_one": (lambda: weekly([tg._r("film", date(2026, 2, 3), False)]),
                   "The 1 reading this month was within limits."),
}


@pytest.mark.parametrize("topic", sorted(EXACT))
def test_exact_paragraph(topic):
    build, text = EXACT[topic]
    assert build().explanation == text


def test_endpoint_carries_explanation(data):
    for topic in ("summary", "colours", "points", "changes", "colour_report", "weekly"):
        body = get(data, "analysis/ask", topic=topic, month=NOW)
        assert isinstance(body["explanation"], str)
        if body["status"] in ("not_enough_data", "needs_slot"):
            assert body["explanation"] == ""
        else:
            assert body["explanation"] and not [t for t in BANNED if t in body["explanation"]]
    slot = get(data, "analysis/ask", topic="compare_orient", month=NOW, colour="x", metric="CLEAR")
    assert slot["status"] == "needs_slot" and slot["explanation"] == ""


# =====================================================================
# AR06 Task 2: problem, trend, appearance and data questions
from app.domain.assistant.appearance import appearance_profile, cf_drivers, layer_vs_band  # noqa: E402
from app.domain.assistant.bands import bands  # noqa: E402
from app.domain.assistant.catalog import CATALOG  # noqa: E402
from app.domain.assistant.data_checks import data_complete, no_standard, pairing, standard_for  # noqa: E402
from app.domain.assistant.problem import cars_or_process, centre_or_spread, why_failing, worst_cars  # noqa: E402
from app.domain.assistant.report_grids import recurring  # noqa: E402
from app.domain.assistant.risk import history, next_month_risk  # noqa: E402
from app.domain.assistant.trend import trend  # noqa: E402
from tests import test_ar05_appearance as ta  # noqa: E402
from tests import test_ar05_data as td  # noqa: E402
from tests import test_ar05_problem as tp  # noqa: E402
from tests import test_ar05_risk as tr  # noqa: E402

LABELS = {str(c): f"{2000000 + c}" for c in range(1, 21)}


def _why():
    box = tp._box()
    return why_failing(box, tp._grid(box, lambda c, p: c <= 10 and p in ("R-12", "R-14") or (c == 1 and p == "L-05"),
                                     day=lambda c: date(2026, 2, 3) if c <= 10 else date(2026, 2, 8 + c % 20)))


def _why_cars():
    box = tp._box()
    return why_failing(box, tp._grid(box, lambda c, p: c <= 3, day=lambda c: date(2026, 2, 3 + c * 3 % 25)),
                       {"1": "C1", "2": "C2", "3": "C3"})


def _why_spread():
    box = tp._box()
    return why_failing(box, tp._grid(box, lambda c, p: (c + tp.POINTS.index(p)) % 7 == 0,
                                     day=lambda c: date(2026, 2, 3 + c % 25)))


def _few_cars():
    return cars_or_process(tp._box(), tp._grid(tp._box(), lambda c, p: c <= 2), LABELS)


def _whole():
    return cars_or_process(tp._box(), tp._grid(tp._box(), lambda c, p: p == "R-12"), LABELS)


def _worst():
    return worst_cars(tp._grid(tp._box(), lambda c, p: c == 4 or (c == 5 and p == "R-12")), LABELS)


def _drift():
    return trend(t4._tb([20 - 0.3 * i for i in range(10)], layer="PRIMER", unit="µm"),
                 t4._tb([20.0 + 0.1 * (i % 3) for i in range(12)], layer="PRIMER", status="PASS"), [])


def _risk():
    return next_month_risk([tr._b("Red"), tr._b("Blue", "WARNING", step=-0.1)])


def _streak():
    return history(tr._b("Blue", "FAIL"), [tr._mp("2026-03", 1.5, "FAIL"), tr._mp("2026-02", 1.6, "FAIL"),
                                           tr._mp("2026-01", 3.0, "PASS")])


def _sequence():
    return history(tr._b("Blue", "FAIL"), [tr._mp("2026-03", 1.5, "FAIL"), tr._mp("2026-02", 3.1, "PASS"),
                                           tr._mp("2026-01", 3.0, "PASS")])


def _recurring():
    bad, ok = tr._b("Blue", "FAIL"), tr._b("Red")
    return recurring({"2026-01": [bad, ok], "2026-02": [bad, ok], "2026-03": [tr._b("Blue", "WARNING"), ok],
                      "2026-04": [tr._b("Blue"), ok]})


def _bands():
    now, before = t4._rise()
    return bands(now, before, t4._paired(True))


def _bands_plant():
    flat = t4._br("M1", "WHITE", "wc", [5.0 + 0.1 * (i % 5) for i in range(12)])
    other = t4._br("M2", "RED", "wc", [1.0 + 0.1 * (i % 5) for i in range(12)])
    return bands(flat + other, flat + other, t4._paired(False))


def _data_complete():
    film = [td._r("film", d) for d in (2, 9, 23)]
    ws = [td._r("wavescan", d) for d in (2, 9, 16, 23)]
    return data_complete(film + ws, [td._b(n=3), td._b(n=2, color="Red"), td._b(), td._b(color="Grey", n=1),
                                     td._b(color="Pink", n=4)], date(2026, 2, 20), [1, 2, 3, 4])


def _standard():
    boxes = [td._b("CLEAR", status="PASS", lsl=40), td._b("BASE", status="FAIL", lsl=15, usl=30.04, scope="PLANT"),
             td._b(None, status="PASS", lsl=55.0, scope=None), td._b("BASE", orient="Horizontal", lsl=15, usl=30.04)]
    return standard_for("Blue", boxes, {boxes[1].key: 22.5}, "2026-02")


def _no_standard():
    return no_standard([td._b(status=None, scope=None), td._b(status=None, scope="COLOR", color="Red"), td._b()])


def _centre():
    return centre_or_spread(tp._cs(30.0, 2.0), tp._cs(30.0, 2.0), 25.0)


def _profile():
    return appearance_profile("Red", ta._month())


def _drivers():
    return cf_drivers(ta._box(), ta._cf())


def _link():
    return layer_vs_band("CLEAR", "wa", ta._paired())


def _pairing():
    return pairing({"paired_cars": 6})


LEAD = "cars measured on both instruments, so treat it as a lead, not proof"
T2 = [
    ("why_failing", _why, ["Blue Clear on the Ranger", "R-12 and R-14", "20 of 21"]),
    ("why_failing", _why_cars, ["2 cars", "check those cars' history"]),
    ("why_failing", _why_spread, ["process"]),
    ("why_failing", lambda: why_failing(tp._box(), tp._grid(tp._box(), lambda c, p: False)), ["Blue Clear"]),
    ("cars_or_process", _few_cars, ["Blue Clear", "2 of 20", "10 of 10", "check those cars' history"]),
    ("cars_or_process", _whole, ["20 of 20", "it's the process, not individual cars"]),
    ("cars_or_process", lambda: cars_or_process(tp._box(), tp._grid(tp._box(), lambda c, p: False), LABELS),
     ["20 cars"]),
    ("worst_cars", _worst, ["Car 2000004", "5 of 5", "2 of 20"]),
    ("worst_cars", lambda: worst_cars(tp._grid(tp._box(), lambda c, p: False), LABELS), ["20 cars"]),
    ("centre_or_spread", _centre, ["Blue Clear", "5.0 µm", "target"]),
    ("centre_or_spread", lambda: centre_or_spread(tp._cs(30.0, 4.2), tp._cs(30.0, 2.1), 30.0, "2026-09"),
     ["more scattered", "twice", "September 2026"]),
    ("centre_or_spread", lambda: centre_or_spread(tp._cs(26.0, 2.0), tp._cs(30.0, 2.0), None, "2026-09"),
     ["toward the low limit", "4.0 µm"]),
    ("centre_or_spread", lambda: centre_or_spread(tp._cs(30.0, 2.0), tp._cs(30.0, 2.0), None, "2026-09"),
     ["September 2026"]),
    ("centre_or_spread", lambda: centre_or_spread(tp._cs(30.0, 2.0), None, 30.5, "2026-09"),
     ["0.5 µm", "September 2026"]),
    ("trend", _drift, ["Red", "falling", "0.30 µm a day", "low limit in about 4 days", "of the next 30 cars"]),
    ("trend", lambda: trend(t4._tb([10, 11, 10, 11, 10, 11, 10, 11], unit="mm"), None, []),
     ["day-to-day noise"]),
    ("next_month_risk", _risk, ["Blue Clear on the Ranger", "about 30 of the next 30 cars"]),
    ("next_month_risk", lambda: next_month_risk([tr._b("Red")]), ["heading out"]),
    ("history", _streak, ["Blue Clear", "not a one-off", "February 2026", "2 months"]),
    ("history", _sequence, ["Blue Clear", "Pass", "Fail"]),
    ("recurring", _recurring, ["Blue Clear on the Ranger", "not a one-off", "3 of the last 4 months"]),
    ("recurring", lambda: recurring({m: [tr._b("Red")] for m in ("2026-01", "2026-02", "2026-03")}),
     ["3 months"]),
    ("bands", _bands, ["Wc", "M1 WHITE", "2.0", "Base", f"from 12 {LEAD}"]),
    ("bands", _bands_plant, ["Wc", "above the plant", "Primer", "lead, not proof"]),
    ("bands", lambda: bands(t4._br("M1", "WHITE", "wc", [5.0] * 12), t4._br("M1", "WHITE", "wc", [5.0] * 12), None),
     ["Wave Scan band"]),
    ("appearance_profile", _profile, ["Red", "long waves", "Wd and We", "Primer and E-coat"]),
    ("appearance_profile", lambda: appearance_profile("Red", ta._month(())), ["Red", "plant"]),
    ("cf_drivers", _drivers, ["Red Wave Scan CF on the M1", "Wb and Wc", "the higher the Wb, the lower the CF",
                              "Clear and Base"]),
    ("cf_drivers", lambda: cf_drivers(ta._box(), ta._cf(neg=())), ["Red Wave Scan CF", "14"]),
    ("layer_vs_band", _link, ["the thicker the Clear, the lower the Wa", f"from 6 {LEAD}"]),
    ("layer_vs_band", lambda: layer_vs_band("CLEAR", "wa", [dict(r, wa=[1, 5, 2, 4, 3, 3][i])
                                                            for i, r in enumerate(ta._paired())]),
     ["Clear", "Wa", f"from 6 {LEAD}"]),
    ("data_complete", _data_complete, ["Film week 3 has no readings", "may miss a shift", "4 boxes"]),
    ("data_complete", lambda: data_complete([td._r("film", 2), td._r("film", 9)], [td._b()], None, [1, 2]),
     ["every box"]),
    ("standard_for", _standard, ["Blue", "Base", "15 and 30 µm", "plant rule", "55"]),
    ("no_standard", _no_standard, ["2 boxes", "Blue Clear on the M"]),
    ("no_standard", lambda: no_standard([td._b()]), ["1 box"]),
    ("pairing", _pairing, ["6 cars", "about 100", "lead, not proof"]),
    ("pairing", lambda: pairing({"paired_cars": 120}), ["120 cars", "trusted"]),
]


@pytest.mark.parametrize("topic,build,must", T2, ids=[f"{a[0]}-{i}" for i, a in enumerate(T2)])
def test_task2_paragraph_rules(topic, build, must):
    test_paragraph_rules(topic, build, must)


def test_task2_headline_numbers_reused():
    """Every 'x of y' and decimal in the headline is in the paragraph (a ρ in brackets stays in the headline)."""
    for _, build, _ in T2:
        a = build()
        head = re.sub(r"\(ρ[^)]*\)", "", a.headline)
        for num in re.findall(r"\d+ of \d+|\d+\.\d", head):
            assert num in a.explanation, (num, a.headline, a.explanation)


def test_task2_not_enough_is_empty():
    for a in (cars_or_process(tp._box("wavescan"), []), worst_cars([]),
              centre_or_spread(tp._cs(30.0, 2.0, n=5), None, None), trend(t4._tb([1, 2, 3]), None, []),
              next_month_risk([]), history(tr._b("Blue"), []), recurring({}), bands([], [], None),
              appearance_profile("Green", ta._month()), cf_drivers(ta._box("film"), []),
              layer_vs_band("CLEAR", "wa", []), data_complete([], [], None, [1]),
              standard_for("Red", [], {}, "2026-02"), no_standard([])):
        assert a.explanation == "", a.headline


# The main fixture answer of every catalogue question.
MAIN = {
    **{k: v[0] for k, v in EXACT.items() if k in {q.id for q in CATALOG}},
    "why_failing": _why, "cars_or_process": _few_cars, "worst_cars": _worst, "centre_or_spread": _centre,
    "trend": _drift, "next_month_risk": _risk, "history": _streak, "recurring": _recurring, "bands": _bands,
    "appearance_profile": _profile, "cf_drivers": _drivers, "layer_vs_band": _link, "data_complete": _data_complete,
    "standard_for": _standard, "no_standard": _no_standard, "pairing": _pairing,
}


def test_every_catalog_question_has_a_paragraph():
    assert set(MAIN) == {q.id for q in CATALOG}
    for q in CATALOG:
        a = MAIN[q.id]()
        assert a.status in ("answer", "all_clear") and a.explanation, q.id
        assert not [t for t in BANNED if t in a.explanation], (q.id, a.explanation)


LEAD_END = "so treat it as a lead, not proof."
EXACT2 = {
    "why_failing": (_why, "Blue Clear on the Ranger, vertical panels, has its out readings bunched at R-12 and R-14 "
                          "right, in week 1. 20 of 21 outs are at R-12 and R-14, far more than their share of the "
                          "readings, so look at that spot first."),
    "why_failing_cars": (_why_cars, "Blue Clear on the Ranger, vertical panels, has its out readings bunched on 2 cars. "
                                    "10 of 15 outs are on those 2 cars, far more than their share of the readings, so "
                                    "check those cars' history before changing the process."),
    "why_failing_spread": (_why_spread, "The 14 out readings on Blue Clear on the Ranger, vertical panels, are spread "
                                        "over points, sides, weeks and cars. No spot or car holds more than its share, "
                                        "so it's the process, not individual cars."),
    "cars_or_process": (_few_cars, "For Blue Clear on the Ranger, vertical panels, 2 of 20 cars hold 10 of 10 out "
                                   "readings. That's a few cars, so check those cars' history before changing the "
                                   "process; the worst is car 2000001, with 5 points out."),
    "cars_or_process_whole": (_whole, "For Blue Clear on the Ranger, vertical panels, 20 of 20 cars have readings out. "
                                      "The outs are spread over too many cars to blame a few, so it's the process, not "
                                      "individual cars."),
    "worst_cars": (_worst, "2 of 20 cars had Film points out this month. The worst is car 2000004, with 5 of 5 "
                           "measured points out, so open its history first."),
    "centre_or_spread": (_centre, "For Blue Clear on the P703, vertical panels, the average sits 5.0 µm above its "
                                  "target of 25.0 µm. Re-centring the Clear build will help more than reducing its "
                                  "scatter."),
    "centre_or_spread_spread": (T2[10][1], "For Blue Clear on the P703, vertical panels, the readings have become more "
                                           "scattered: their typical scatter is 4.2 µm against 2.1 µm in September "
                                           "2026, about twice as wide. Making the Clear build more consistent will "
                                           "help more than moving its average."),
    "centre_or_spread_moved": (T2[11][1], "For Blue Clear on the P703, vertical panels, the average has moved 4.0 µm "
                                          "toward the low limit since September 2026. That's 2.0 times last month's "
                                          "typical scatter, so re-centre the Clear build."),
    "trend": (_drift, "The daily average of Red Primer on the M1, horizontal panels, has been falling about 0.30 µm a "
                      "day this month. At that pace it reaches the low limit in about 4 days. If it keeps going for "
                      "another week, about 24 of the next 30 cars would be out."),
    "next_month_risk": (_risk, "If nothing changes, Blue Clear on the Ranger, vertical panels, is the box most likely "
                               "to fail next: about 30 of the next 30 cars would be out. Its daily average has been "
                               "moving steadily this month, and that pace carries it toward the low limit."),
    "history": (_streak, "Blue Clear on the Ranger, vertical panels, is not a one-off: it has been at Fail every month "
                         "since February 2026, 2 months running. Its monthly average went from 1.6 µm to 1.5 µm over "
                         "that time, so it needs a fix rather than waiting for it to clear."),
    "history_sequence": (_sequence, "Over the last 3 months with readings, Blue Clear on the Ranger, vertical panels, "
                                    "went Pass, then Pass, then Fail. It's at Fail now, with a monthly average of "
                                    "1.5 µm. It passed in February 2026, so look at what changed since then."),
    "recurring": (_recurring, "Blue Clear on the Ranger, vertical panels, is not a one-off: it was not at Pass in 3 "
                              "of the last 4 months. It needs a lasting fix, not a one-month correction."),
    "recurring_clear": (T2[21][1], "No box missed Pass in all of the last 3 months (1 box checked)."),
    "bands": (_bands, "The Wc band on M1 WHITE rose 2.0 since last month, a real difference, not day-to-day noise. By "
                      "the band-to-layer table, Wc points to Base, so check that build first. The paired cars agree: "
                      f"the thicker the Base, the higher the Wc, from 12 cars measured on both instruments, {LEAD_END}"),
    "bands_plant": (_bands_plant, "The Wc band on M1 WHITE runs 2.0 above the plant this month. By the band-to-layer "
                                  "table, Wc points to Base, so check that build first. The paired cars point to "
                                  f"Primer instead, from 12 cars measured on both instruments, {LEAD_END}"),
    "appearance_profile": (_profile, "Red runs high on long waves this month, on Wd and We. By the band-to-layer "
                                     "table that points to Primer and E-coat, so check those builds first. Wd is "
                                     "furthest out, with a median of 16.5 against 14.0 across the plant."),
    "cf_drivers": (_drivers, "For Red Wave Scan CF on the M1, vertical panels, CF loss tracks Wb and Wc: the higher "
                             "the Wb, the lower the CF. It's a strong link across 14 measurements, and by the "
                             "band-to-layer table Wb points to Clear and Base, so check Clear and Base first."),
    "layer_vs_band": (_link, "The thicker the Clear, the lower the Wa, a strong link: each extra µm of Clear goes with "
                             f"about 0.99 lower Wa. That's from 6 cars measured on both instruments, {LEAD_END}"),
    "layer_vs_band_none": (T2[30][1], "Clear thickness and Wa don't move together in any clear way. That's from 6 "
                                      f"cars measured on both instruments, {LEAD_END}"),
    "data_complete": (_data_complete, "Film week 3 has no readings, so this month's Film results may miss a shift. 4 "
                                      "boxes have under 10 readings, so their status rests on thin data; the thinnest "
                                      "is Grey Clear on the M, vertical panels, with 1 reading. The last upload was on "
                                      "20 February 2026."),
    "standard_for": (_standard, "For Blue, Base must stay between 15 and 30 µm under the plant rule, and it's at Fail "
                                "this month. That's the vertical panels; other orientations or models carry different "
                                "limits. Wave Scan CF must stay at or above 55."),
    "no_standard": (_no_standard, "2 boxes have no standard to grade against this month, starting with Blue Clear on "
                                  "the M, vertical panels. They show no Pass or Fail, so a problem there won't stand "
                                  "out until a standard is applied."),
    "pairing": (_pairing, "6 cars have been measured on both Film and Wave Scan, across all months and the whole "
                          "plant. About 100 are needed, so for now treat the layer checks as a lead, not proof."),
}


@pytest.mark.parametrize("topic", sorted(EXACT2))
def test_task2_exact_paragraph(topic):
    build, text = EXACT2[topic]
    assert build().explanation == text


def test_task2_endpoint_carries_explanation(data):  # noqa: F811
    for topic in ("worst_cars", "next_month_risk", "recurring", "bands", "data_complete", "no_standard", "pairing"):
        body = get(data, "analysis/ask", topic=topic, month=NOW)
        if body["status"] in ("not_enough_data", "needs_slot"):
            assert body["explanation"] == "", topic
        else:
            assert body["explanation"] and not [t for t in BANNED if t in body["explanation"]], topic
            assert "%" not in body["explanation"], topic


# ---- Task 2 fix round 1 ----
def test_risk_paragraph_follows_where_the_box_is():
    away = next_month_risk([tr._b("Blue", "FAIL", start=1.5, step=-0.1)])
    assert away.explanation == ("If nothing changes, Blue Clear on the Ranger, vertical panels, will put the most cars "
                                "out next month: about 30 of the next 30 cars would be out. It's already outside the "
                                "limit and still moving away from it.")
    back = next_month_risk([tr._b("Blue", "FAIL", start=0.5, step=0.03)])
    assert back.explanation == ("If nothing changes, Blue Clear on the Ranger, vertical panels, will put the most "
                                "cars out next month: about {e} of the next 30 cars would be out. It's outside the "
                                "limit but moving back toward it.").format(e=back.evidence["rows"][0][1])
    toward = _risk().explanation
    assert "most likely to fail next" in toward and toward.endswith("that pace carries it toward the low limit.")
    for a in (away, back):
        test_paragraph_rules("next_month_risk", lambda: a, ["Blue Clear"])


def test_worst_cars_makes_no_cause_claim():
    many = worst_cars(tp._grid(tp._box(), lambda c, p: p == "R-12" or (c == 4 and p == "R-14")), LABELS)
    assert many.explanation == ("20 of 20 cars had Film points out this month. The worst is car 2000004, with 2 of 5 "
                                "measured points out, so open its history first.")
    assert "process" not in _worst().explanation


def _ws_spread():
    box = tp._box("wavescan")
    return why_failing(box, tp._grid(box, lambda c, p: (c + tp.POINTS.index(p)) % 7 == 0, domain="wavescan",
                                     metric="cf", day=lambda c: date(2026, 2, 3 + c % 25)))


def test_why_failing_spread_wording():
    box = tp._box()
    one = why_failing(box, tp._grid(box, lambda c, p: c == 1 and p == "R-12", day=lambda c: date(2026, 2, 3 + c % 25)))
    assert one.explanation == ("The 1 out reading on Blue Clear on the Ranger, vertical panels, is a one-off, not a "
                               "pattern. There are too few out readings or cars to tell one spot or car from the "
                               "whole process.")
    few = why_failing(box, tp._grid(box, lambda c, p: c in (1, 9, 17) and p == tp.POINTS[c % 5],
                                    day=lambda c: date(2026, 2, 3 + c % 25)))
    assert few.headline.endswith("spread across the process") and "it's the process" not in few.explanation
    assert few.explanation.startswith("The 3 out readings on Blue Clear")
    ws = _ws_spread()
    assert ws.headline.endswith("spread across the process")
    assert ws.explanation == ("The 14 out readings on Blue Wave Scan CF on the Ranger, vertical panels, are spread "
                              "over points, sides and weeks. No spot holds more than its share, so it's the process "
                              "rather than one spot.")
    for a in (one, few, ws):
        test_paragraph_rules("why_failing", lambda: a, [])


def test_layer_vs_band_size_only_when_slope_agrees():
    rows = [{"car_no": str(i), "pair_group": "A", "layer_code": "CLEAR", "thickness": float(i),
             "wa": float(10 * i if i < 10 else -200)} for i in range(1, 11)]
    a = layer_vs_band("CLEAR", "wa", rows)
    assert a.headline.startswith("Thicker Clear → higher Wa")
    assert a.explanation == ("The thicker the Clear, the higher the Wa, a moderate link. That's from 10 cars measured "
                             "on both instruments, so treat it as a lead, not proof.")


def test_cf_drivers_none_wording():
    assert cf_drivers(ta._box(), ta._cf(neg=())).explanation == (
        "For Red Wave Scan CF on the M1, vertical panels, no band clearly moves with CF this month. That's across 6 "
        "bands and 14 measurements, so the CF loss doesn't point to one paint layer.")


def test_standard_for_pads_only_a_single_sentence():
    two = standard_for("Blue", [td._b("CLEAR"), td._b(None, lsl=55.0, scope=None)], {}, "2026-02")
    assert two.explanation == ("For Blue, Clear must stay at or above 40 µm under the colour rule. Wave Scan CF must "
                               "stay at or above 55.")
    one = standard_for("Blue", [td._b("CLEAR")], {}, "2026-02")
    assert one.explanation == ("For Blue, Clear must stay at or above 40 µm under the colour rule. That's what the "
                               "1 box for Blue this month is graded against.")


# ---- Task 2 fix round 2 ----
def _inside(lsl, usl, step):
    """10 days, two readings a day 0.4 either side of a daily mean that moves `step` a day from 2.0."""
    days = tuple(date(2026, 2, 1) + timedelta(days=i) for i in range(10) for _ in (0, 1))
    vals = tuple(2.0 + step * i + (0.005 if i % 2 else -0.005) + side
                 for i in range(10) for side in (-0.4, 0.4))
    return Box("film", "CLEAR", "P703 DBL RANGER", "Blue", "Vertical", "WARNING", None, lsl, usl, "µm", vals, days)


def test_risk_inside_moving_away_blames_scatter():
    up = next_month_risk([_inside(2.0, None, 0.01)])
    assert up.explanation == ("If nothing changes, Blue Clear on the Ranger, vertical panels, is the box most likely "
                              "to fail next: about {e} of the next 30 cars would be out. It's moving away from the low "
                              "limit; the risk comes from how scattered its readings are."
                              ).format(e=up.evidence["rows"][0][1])
    down = next_month_risk([_inside(None, 2.0, -0.01)])
    assert down.explanation == ("If nothing changes, Blue Clear on the Ranger, vertical panels, is the box most likely "
                                "to fail next: about {e} of the next 30 cars would be out. It's moving away from the "
                                "high limit; the risk comes from how scattered its readings are."
                                ).format(e=down.evidence["rows"][0][1])
    assert up.evidence["rows"][0][1] > 0 and down.evidence["rows"][0][1] > 0
    both = next_month_risk([_inside(1.0, 3.0, 0.01)])
    assert both.status == "answer" and both.explanation.endswith("that pace carries it toward the high limit.")


def test_risk_lead_uses_outside_not_only_fail():
    over = next_month_risk([tr._b("Blue", "WARNING", start=1.5, step=-0.1)])
    assert "will put the most cars out next month" in over.explanation


def test_worst_cars_one_car_is_singular():
    a = worst_cars(tp._grid(tp._box(), lambda c, p: p == "R-12", cars=1), LABELS)
    assert a.explanation.startswith("1 of 1 car had Film points out this month.")
