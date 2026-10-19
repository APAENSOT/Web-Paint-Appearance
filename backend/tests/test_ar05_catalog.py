"""AR05 catalog: per-reading loader."""

from __future__ import annotations

from app.domain.assistant.readings import side_panel
from tests.test_ar03_analysis_report import NOW, data  # noqa: F401


def test_side_panel_rules():
    assert side_panel("094RBOXSIDE") == ("R", "BOXSIDE")
    assert side_panel("LCFDOOR") == ("L", "CFDOOR")
    assert side_panel("FRFENRH1") == ("R", "FRFEN1")
    assert side_panel("001HOOD") is None
    assert side_panel("CFHOOD") is None
    assert side_panel(None) is None


def test_readings_match_boxes(data):
    from app.services.assistant import load_month

    got = load_month(data["conn"], data["plant"], NOW, plant_scope=None, domain="both", models=[], colors=[])
    assert got.boxes and got.readings
    for box in got.boxes:
        metric = box.layer or "cf"
        mine = [r for r in got.readings if r.box_key == box.key and r.metric == metric]
        assert len(mine) == len(box.values), box.key
        assert sum(bool(r.out) for r in mine) == box.out, box.key
    assert {r.metric for r in got.readings if r.domain == "wavescan"} - {"cf"}, "band metrics missing"


def test_week_of_reading():
    from datetime import date

    from app.domain.assistant.readings import week_of_reading
    from app.domain.history import week_of

    d = date(2026, 10, 18)
    assert week_of_reading(d) == week_of(d) and 1 <= week_of_reading(d) <= 5
    assert week_of_reading(None) == 0
    assert week_of_reading(d, month_only=True) == 0


# ---- Task 2: registry, slots, endpoints ----
from tests.test_ar03_analysis_report import RANGER, RAPTOR, get  # noqa: E402

ASK = "analysis/ask"
IDS = (
    "summary", "colour_report", "model_report", "went_well", "weekly",
    "changes", "compare_months", "compare_models", "compare_colours", "compare_orient", "compare_sides",
    "compare_families", "compare_cars", "compare_plants",
    "colours", "points", "why_failing", "cars_or_process", "worst_cars", "centre_or_spread",
    "trend", "next_month_risk", "history", "recurring",
    "bands", "appearance_profile", "cf_drivers", "layer_vs_band",
    "data_complete", "standard_for", "no_standard", "pairing",
)
KINDS = {"bar", "table", "shift", "trend", "heatmap", "weekly_strip", "boxplot_pair", "boxplot_group",
         "mirrored_bar", "point_bars", "car_bars", "breakdown", "distribution", "trend_monthly", "grid",
         "spectrum", "scatter", "limit_card", "stat"}


def test_catalog_complete():
    from app.domain.assistant.catalog import CATALOG, by_id
    from app.services.assistant import RUNNERS

    assert tuple(q.id for q in CATALOG) == IDS
    keysets = set()
    for q in CATALOG:
        assert q.label and q.label_th and q.example, q.id
        assert len(q.keywords) >= 2 and len(q.keywords_th) >= 1, q.id
        assert q.graph in KINDS, q.id
        assert q.group in ("month", "compare", "problem", "trend", "appearance", "data"), q.id
        assert q.id in RUNNERS and by_id(q.id) is q
        keysets.add(frozenset(q.keywords + q.keywords_th))
    assert len(keysets) == len(CATALOG)
    assert set(RUNNERS) == set(IDS)  # every id has its own runner; no placeholder is left


def test_questions_endpoint(data):
    body = get(data, "analysis/questions")
    assert [q["id"] for q in body["questions"]] == list(IDS)
    compare = next(q for q in body["questions"] if q["id"] == "compare_models")
    assert [s["name"] for s in compare["slots"]] == ["a", "b", "metric"]
    assert set(body["keywords"]) == set(IDS) and "สรุป" in body["keywords"]["summary"]


def test_needs_slot_lists_live_models(data):
    body = get(data, ASK, topic="compare_models", month=NOW)
    assert body["status"] == "needs_slot" and body["slot"]["name"] == "a"
    assert [c["value"] for c in body["slot"]["choices"]] == [RANGER, RAPTOR]
    assert body["decision"]["headline"] == body["slot"]["prompt"]
    b = get(data, ASK, topic="compare_models", month=NOW, a=RANGER)
    assert b["slot"]["name"] == "b" and [c["value"] for c in b["slot"]["choices"]] == [RAPTOR]
    done = get(data, ASK, topic="compare_models", month=NOW, a=RANGER, b=RAPTOR, metric="PRIMER")
    assert done["status"] == "not_enough_data" and done["decision"]["headline"] == (
        "RANGER 7, RAPTOR 5 readings; 10 needed each.")
    assert done["slot"] is None


def test_unknown_slot_value_reasks(data):
    body = get(data, ASK, topic="compare_models", month=NOW, a="BRONCO")
    assert body["status"] == "needs_slot" and body["slot"]["name"] == "a"
    assert body["slot"]["prompt"].startswith("No readings for BRONCO in February 2099 with these filters.\n")


def test_unknown_topic_422(data):
    client, plant = data["client"], data["plant"]
    url = f"/api/v1/plants/{plant}/{ASK}"
    assert client.get(url, params={"topic": "weather"}).status_code == 422
    assert client.get(url, params={"topic": "why_failing", "target": "a|b"}).status_code == 422
    assert client.get(url, params={"topic": "compare_months", "month2": "2099-13"}).status_code == 422


def test_resolve_choices_by_kind():
    from types import SimpleNamespace

    from app.domain.assistant.answer import Box
    from app.domain.assistant.catalog import by_id
    from app.services.assistant import MonthData
    from app.services.assistant_slots import resolve

    from app.domain.assistant.readings import Reading

    box = Box("film", "CLEAR", "M1", "Red", "Horizontal", "FAIL", None, 40, None, "µm", (1.0,), ())
    wa = Reading("wavescan", None, "M1", "Red", None, "Vertical", "P", None, None, "wa", 1.0, None, "k")
    ctx = SimpleNamespace(used="2099-02", months=["2099-02", "2099-01"],
                          load=lambda m: MonthData([box], [], [], 0, [wa]))
    got = resolve(by_id("layer_vs_band"), {}, ctx)
    assert got.status == "needs_slot" and got.slot["choices"] == [{"value": "CLEAR", "label": "Clear"}]
    assert resolve(by_id("layer_vs_band"), {"layer": "CLEAR", "metric": "wa"}, ctx) == {
        "layer": "CLEAR", "metric": "wa"}
    months = resolve(by_id("compare_months"), {}, ctx)
    assert months.slot["name"] == "month2" and months.slot["choices"][1] == {"value": "2099-01",
                                                                             "label": "January 2099"}
    assert resolve(by_id("trend"), {}, ctx) == {}  # optional: AR04 picks the worst box itself


# ---- Task 2 fix round 1 ----
def test_pair_choices_ignore_the_compared_filter(data):
    b = get(data, ASK, topic="compare_models", month=NOW, models=[RANGER], a=RANGER)
    assert b["status"] == "needs_slot" and [c["value"] for c in b["slot"]["choices"]] == [RAPTOR]
    a = get(data, ASK, topic="compare_models", month=NOW, models=[RAPTOR])
    assert [c["value"] for c in a["slot"]["choices"]] == [RANGER, RAPTOR]
    done = get(data, ASK, topic="compare_models", month=NOW, models=[RANGER], a=RANGER, b=RAPTOR,
               metric="PRIMER")
    assert done["decision"]["headline"] == "RANGER 7, RAPTOR 5 readings; 10 needed each."
    # one colour only in the fixture: nothing to compare it with
    c = get(data, ASK, topic="compare_colours", month=NOW, colors=["Arctic White"], a="Arctic White")
    assert c["status"] == "not_enough_data"
    assert c["decision"]["headline"] == "No other colour has readings in February 2099 with these filters."


def test_miss_line_per_kind(data):
    m = get(data, ASK, topic="compare_months", month=NOW, month2="2098-05")
    assert m["slot"]["name"] == "month2" and m["slot"]["prompt"].startswith("No readings in May 2098.\n")
    p = get(data, ASK, topic="compare_plants", month=NOW, plant2="NOPE", metric="PRIMER")
    # no other plant has readings, so no chips: the miss line alone (final I5)
    assert p["status"] == "not_enough_data" and p["slot"] is None
    assert p["decision"]["headline"] == "NOPE has no readings in February 2099."
    absent = get(data, ASK, topic="layer_vs_band", month=NOW, layer="BASE", metric="wb")
    assert absent["slot"]["name"] == "layer"
    assert absent["slot"]["prompt"].startswith("No readings for BASE in February 2099 with these filters.\n")


def test_unknown_layer_or_metric_422(data):
    url = f"/api/v1/plants/{data['plant']}/{ASK}"
    bad = data["client"].get(url, params={"topic": "layer_vs_band", "layer": "PAINT"})
    assert bad.status_code == 422 and "ECOAT, PRIMER, BASE, CLEAR" in bad.text
    bad = data["client"].get(url, params={"topic": "compare_sides", "metric": "zz"})
    assert bad.status_code == 422 and "lw, sw, cf" in bad.text


def test_no_choices_is_not_enough_data_not_an_empty_ask():
    from types import SimpleNamespace

    from app.domain.assistant.catalog import by_id
    from app.services.assistant import MonthData
    from app.services.assistant_slots import resolve

    ctx = SimpleNamespace(used="2099-02", months=["2099-02"], domain="both", load=lambda m: MonthData([], [], []))
    got = resolve(by_id("cf_drivers"), {}, ctx)
    assert got.status == "not_enough" and "No readings" in got.headline
