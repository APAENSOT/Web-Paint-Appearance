"""AR05 Task 9: why failing, few cars or whole process, worst cars."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.domain.assistant.answer import Box
from app.domain.assistant.problem import cars_or_process, why_failing, worst_cars
from app.domain.assistant.readings import Reading
from tests.test_ar04_assistant import assert_clean

POINTS = ["R-12", "R-14", "L-05", "L-06", "C-1"]
NO_CARS = "Car questions use Film cars; Wave Scan readings are not linked to cars here."


def _box(domain="film"):
    return Box(domain, "CLEAR" if domain == "film" else None, "P703 DBL RANGER", "Blue", "Vertical", "FAIL",
               None, 2.0, None, "µm", (), ())


def _grid(box, out, day=lambda car: date(2026, 2, 8 + car % 20), cars=20, domain="film", metric=None):
    """cars x 5 points; `out(car, point)` says which readings are out."""
    return [Reading(domain, box.layer, box.model, box.color, None, box.orient, p, str(c), day(c),
                    metric or box.layer or "cf", 1.0, out(c, p), box.key, f"AB{2000000 + c}X")
            for c in range(1, cars + 1) for p in POINTS]


def test_why_failing_concentrated_by_point_side_week():
    box = _box()
    rs = _grid(box, lambda c, p: c <= 10 and p in ("R-12", "R-14") or (c == 1 and p == "L-05"),
               day=lambda c: date(2026, 2, 3) if c <= 10 else date(2026, 2, 8 + c % 20))
    a = why_failing(box, rs)
    assert_clean(a)
    assert a.headline == f"{box.label}: concentrated at R-12 and R-14 right, in week 1"
    assert a.evidence["kind"] == "breakdown" and a.evidence["columns"] == ["By", "Where", "Out", "Readings"]
    assert a.evidence["rows"][0] == ["Point", "R-12", 10, 20]
    assert {r[0] for r in a.evidence["rows"]} == {"Point", "Side", "Week", "Car"}
    assert [f["topic"] for f in a.followups] == ["trend", "cars_or_process"]
    assert a.followups[0]["target"] == box.key


def test_why_failing_cars_and_spread():
    box = _box()
    few = why_failing(box, _grid(box, lambda c, p: c <= 3, day=lambda c: date(2026, 2, 3 + c * 3 % 25)),
                      {"1": "C1", "2": "C2", "3": "C3"})
    assert few.headline == f"{box.label}: concentrated on 2 cars"
    spread = why_failing(box, _grid(box, lambda c, p: (c + POINTS.index(p)) % 7 == 0,
                                    day=lambda c: date(2026, 2, 3 + c % 25)))
    assert spread.headline == f"{box.label}: spread across the process"
    clear = why_failing(box, _grid(box, lambda c, p: False))
    assert clear.status == "all_clear" and clear.headline == f"{box.label}: no readings out this month."


def test_why_failing_wavescan_uses_cf_only():
    box = _box("wavescan")
    rs = _grid(box, lambda c, p: p == "R-12" and c <= 8, domain="wavescan", metric="cf")
    rs += _grid(box, lambda c, p: None, domain="wavescan", metric="lw")
    a = why_failing(box, rs)
    assert "at R-12 right" in a.headline and a.followups == [
        {"label": "Is it trending?", "topic": "trend", "target": box.key}]


def test_cars_or_process_and_worst_cars():
    box = _box()
    labels = {str(c): f"{2000000 + c}" for c in range(1, 21)}
    few = cars_or_process(box, _grid(box, lambda c, p: c <= 2), labels)
    assert_clean(few)
    assert few.headline == f"{box.label}: a few cars — 2 of 20 cars hold 10 of 10 outs"
    assert few.evidence["kind"] == "car_bars" and few.evidence["rows"][0] == ["2000001", 5, 5]
    assert few.followups == [{"label": "Why is it failing?", "topic": "why_failing", "target": box.key}]
    whole = cars_or_process(box, _grid(box, lambda c, p: p == "R-12"), labels)
    assert whole.headline == f"{box.label}: whole process — 20 of 20 cars have readings out"
    assert cars_or_process(box, _grid(box, lambda c, p: False), labels).status == "all_clear"
    assert cars_or_process(_box("wavescan"), [], labels).headline == NO_CARS

    rs = _grid(box, lambda c, p: c == 4 or (c == 5 and p == "R-12"))
    w = worst_cars(rs, labels)
    assert_clean(w)
    assert w.headline == "Car 2000004: 5 points out — open its history"
    assert w.evidence["rows"][:2] == [["2000004", 5, 5], ["2000005", 1, 5]] and len(w.evidence["rows"]) == 10
    assert w.followups[0]["target"] == box.key
    assert worst_cars(_grid(box, lambda c, p: False), labels).status == "all_clear"
    assert worst_cars([], labels).headline == NO_CARS


def test_runners(monkeypatch):
    import app.services.assistant as svc
    box, ws = _box(), _box("wavescan")
    good = Box("film", "BASE", "P703 DBL RANGER", "Blue", "Vertical", "PASS", None, 2.0, None, "µm", (1.0,), (date(2026, 2, 3),))
    rs = _grid(box, lambda c, p: c <= 2)
    data = svc.MonthData([good, box, ws], [], [], 0, rs)
    monkeypatch.setattr(svc.assistant_slots, "car_labels", lambda c: {})
    ctx = SimpleNamespace(load=lambda m: data, used="2026-02", domain="both")
    assert svc.RUNNERS["cars_or_process"](ctx, {}).headline.startswith(f"{box.label}: a few cars")
    assert svc.RUNNERS["cars_or_process"](ctx, {"target": ws.key}).headline == NO_CARS
    assert svc.RUNNERS["why_failing"](ctx, {"target": box.key}).status == "answer"
    assert svc.RUNNERS["why_failing"](ctx, {"target": "film|X|a|b|c"}).status == "not_enough"
    assert svc.RUNNERS["worst_cars"](ctx, {}).status == "answer"


# ---- Task 10: centring or spread
from app.domain.assistant.problem import centre_or_spread  # noqa: E402


def _vals(mean, sd, n=20):
    """n values with exactly this mean and (sample) sd, alternating around the mean."""
    k = (sd * ((n - 1) / n) ** 0.5)
    return tuple(mean + (k if i % 2 else -k) for i in range(n))


def _cs(mean, sd, domain="film", lsl=2.0, usl=None, n=20):
    layer = "CLEAR" if domain == "film" else None
    return Box(domain, layer, "P703", "Blue", "Vertical", "FAIL", None, lsl, usl, "µm" if layer else "",
               _vals(mean, sd, n), ())


def test_centre_target_offset_is_centring():
    b = _cs(30.0, 2.0)
    a = centre_or_spread(b, _cs(30.0, 2.0), 25.0)
    assert_clean(a)
    assert a.headline == f"{b.label}: centring — mean 5.0 µm from target"
    assert a.next_step == "Re-centre Clear build"
    assert a.evidence["kind"] == "distribution" and len(a.evidence["rows"]) == 10
    assert sum(r[1] for r in a.evidence["rows"]) == 20
    assert [c["label"] for c in a.evidence["card"]] == ["Mean", "σ", "Last month σ", "Target"]
    assert a.evidence["limits"] == {"lo": 2.0, "hi": None}


def test_centre_target_centred_but_spread_grew_is_spread():
    b = _cs(30.0, 4.2)
    a = centre_or_spread(b, _cs(30.0, 2.1), 30.0)
    assert a.headline == f"{b.label}: spread — σ 4.2 µm vs 2.1 µm last month"
    assert a.next_step == "Reduce Clear variation (check Clear application consistency)"


def test_centre_no_target_larger_move_wins():
    b = _cs(26.0, 2.0)
    a = centre_or_spread(b, _cs(30.0, 2.0), None)
    assert a.headline == f"{b.label}: centring — mean moved 2.0σ toward Lo"
    ws = _cs(60.0, 2.0, domain="wavescan", lsl=50.0)
    a = centre_or_spread(ws, _cs(58.0, 2.0, domain="wavescan", lsl=50.0), None)
    assert a.headline.endswith("mean moved 1.0σ away from minimum") and a.next_step == "Re-centre CF build"
    a = centre_or_spread(_cs(30.0, 3.0), _cs(30.0, 2.0), None)
    assert a.headline.endswith("spread — σ 3.0 µm vs 2.0 µm last month")


def test_centre_not_enough():
    a = centre_or_spread(_cs(30.0, 2.0), None, None, "2026-09")
    assert a.status == "not_enough" and a.headline == "No September 2026 baseline to compare spread."
    assert centre_or_spread(_cs(30.0, 2.0), None, None).headline == "No previous month baseline to compare spread."
    assert centre_or_spread(_cs(30.0, 2.0), _cs(30.0, 2.0, n=5), None).status == "not_enough"
    a = centre_or_spread(_cs(30.0, 2.0, n=5), _cs(30.0, 2.0), 25.0)
    assert a.headline == "Not enough readings in this box to judge centring or spread."


def test_centre_target_well_centred_without_baseline():
    b = _cs(30.0, 2.0)
    a = centre_or_spread(b, None, 30.5, "2026-09")
    assert a.status == "answer" and a.next_step is None
    assert a.headline == f"{b.label}: well centred — mean 0.5 µm from target; no September 2026 baseline to judge spread"
    assert [c["label"] for c in a.evidence["card"]] == ["Mean", "σ", "Target"]
    assert centre_or_spread(b, None, 30.5).headline.endswith("no previous month baseline to judge spread")


def test_centre_nothing_moved():
    b = _cs(30.0, 2.0)
    a = centre_or_spread(b, _cs(30.0, 2.0), None, "2026-09")
    assert a.headline == f"{b.label}: no meaningful change in centring or spread since September 2026" and a.next_step is None
    assert centre_or_spread(b, _cs(30.0, 2.0), None).headline.endswith("since previous month")


def test_centre_toward_hi_and_no_limits_and_bin_labels():
    hi = lambda m: _cs(m, 2.0, lsl=None, usl=40.0)  # noqa: E731
    assert centre_or_spread(hi(32.0), hi(30.0), None).headline.endswith("mean moved 1.0σ toward Hi")
    assert centre_or_spread(hi(28.0), hi(30.0), None).headline.endswith("mean moved 1.0σ away from Hi")
    free = lambda m: _cs(m, 2.0, lsl=None)  # noqa: E731
    assert centre_or_spread(free(32.0), free(30.0), None).headline.endswith("moved 1.0σ up")
    assert centre_or_spread(free(28.0), free(30.0), None).headline.endswith("moved 1.0σ down")
    labels = [r[0] for r in centre_or_spread(_cs(30.0, 0.02), _cs(30.0, 0.02), 30.0).evidence["rows"]]
    assert len(set(labels)) == 10
