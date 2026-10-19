"""AR05 Task 12: appearance profile, CF drivers, layer vs band."""

from __future__ import annotations

from datetime import date

from app.domain.assistant.answer import Box
from app.domain.assistant.appearance import appearance_profile, cf_drivers, layer_vs_band
from app.domain.assistant.readings import Reading
from tests.test_ar03_analysis_report import NOW, data, get  # noqa: F401
from tests.test_ar04_assistant import assert_clean

KEY = "wavescan||M1|Red|Vertical"


def _r(colour, metric, value, n, box=KEY):
    return Reading("wavescan", None, "M1", colour, None, "Vertical", "P1", None, date(2026, 2, 3), metric,
                   float(value), None, box, None, f"{colour}{n}")


def _month(high=("wd", "we"), n=12):
    """Red runs +big on `high` bands; Blue is flat. Values vary so σ > 0."""
    rs = []
    for colour in ("Red", "Blue"):
        for i in range(n):
            for m in ("du", "wa", "wb", "wc", "wd", "we", "lw", "sw", "doi"):
                bump = 5.0 if colour == "Red" and m in high else 0.0
                rs.append(_r(colour, m, 10 + i % 4 + bump, i))
    return rs


def test_profile_long_waves():
    a = appearance_profile("Red", _month())
    assert_clean(a)
    assert a.headline == "Red: long waves high (Wd/We) → check Primer and E-coat"
    assert a.next_step == "Check Primer and E-coat; then Substrate"
    assert a.evidence["kind"] == "spectrum"
    assert a.evidence["columns"] == ["Band", "Colour", "Plant", "Gap (σ)", "High"]
    assert [r[0] for r in a.evidence["rows"]] == ["du", "Wa", "Wb", "Wc", "Wd", "We", "lw", "sw", "doi"]
    wd = a.evidence["rows"][4]
    assert wd[4] == "high" and a.evidence["rows"][0][4] == ""
    assert a.evidence["series"][0] == {"x": "du", "y": a.evidence["series"][0]["y"]}


def test_profile_short_mixed_clear_and_few():
    assert appearance_profile("Red", _month(("wa", "wb"))).headline == "Red: short waves high (Wa/Wb) → check Clear and Base"
    assert appearance_profile("Red", _month(("wa", "wd"))).headline == "Red: Wa/Wd high → check Clear and Primer"
    clear = appearance_profile("Red", _month(()))
    assert clear.status == "all_clear" and clear.headline == "Red: appearance bands are in line with the plant."
    few = appearance_profile("Red", [r for r in _month() if r.color != "Red" or r.metric != "wd" or int(r.measurement[3:]) < 5])
    assert few.method["caveats"] and "Wd" in few.method["caveats"][0]
    assert appearance_profile("Green", _month()).status == "not_enough"


def _cf(neg=("wb", "wc"), n=14):
    rs = []
    for i in range(n):
        rs.append(Reading("wavescan", None, "M1", "Red", None, "Vertical", "P1", None, date(2026, 2, 3),
                          "cf", 50.0 + i, False, KEY, None, f"m{i}"))
        for m in ("du", "wa", "wb", "wc", "wd", "we"):
            v = 30 - i if m in neg else (i * 7) % 5 + (3 if m == "du" else 0)
            rs.append(Reading("wavescan", None, "M1", "Red", None, "Vertical", "P1", None, date(2026, 2, 3),
                              m, float(v), None, KEY, None, f"m{i}"))
    return rs


def _box(domain="wavescan"):
    return Box(domain, None if domain == "wavescan" else "CLEAR", "M1", "Red", "Vertical", "FAIL", None, 40.0,
               None, "", (), ())


def test_cf_drivers():
    a = cf_drivers(_box(), _cf())
    assert_clean(a)
    assert a.headline == f"{_box().label}: CF loss tracks Wb and Wc (ρ -1.0, -1.0)"
    assert a.next_step == "Check Clear and Base"
    assert a.evidence["kind"] == "bar" and a.evidence["columns"] == ["Band", "ρ", "n"]
    assert a.evidence["rows"][0][2] == 14 and a.evidence["rows"][0][1] == -1.0
    none = cf_drivers(_box(), _cf(neg=()))
    assert none.headline == f"{_box().label}: no band clearly drives CF"
    assert cf_drivers(_box("film"), _cf()).headline == "Pick a Wave Scan box; CF drivers come from Wave Scan bands."
    assert cf_drivers(_box(), _cf(n=2)).status == "not_enough"


def _paired(sign=-1, n=6, layer="CLEAR"):
    return [{"car_no": str(i), "pair_group": "A", "layer_code": layer, "thickness": 40 + i,
             "wa": 20 + sign * i + (i % 2) * 0.1} for i in range(n)]


def test_layer_vs_band():
    a = layer_vs_band("CLEAR", "wa", _paired())
    assert_clean(a)
    assert a.headline == "Thicker Clear → lower Wa (ρ -1.0, n 6, exploratory)"
    assert a.confidence == "exploratory" and a.evidence["kind"] == "scatter"
    assert a.evidence["points"][0] == {"x": 40.0, "y": 20.0, "label": "0"}
    assert {c["label"] for c in a.evidence["card"]} == {"Slope", "Intercept"}
    assert layer_vs_band("CLEAR", "wa", _paired(1)).headline == "Thicker Clear → higher Wa (ρ 1.0, n 6, exploratory)"
    flat = [dict(r, wa=[1, 5, 2, 4, 3, 3][i]) for i, r in enumerate(_paired())]
    assert layer_vs_band("CLEAR", "wa", flat).headline.startswith("No clear link between Clear thickness and Wa")
    few = layer_vs_band("CLEAR", "wa", _paired(n=2))
    assert few.status == "not_enough" and few.headline == "Not enough paired cars to link Clear and Wa (3 needed)."
    assert layer_vs_band("BASE", "wa", _paired()).status == "not_enough"


def test_instrument_filter_and_measurement(data):  # noqa: F811
    from app.services.assistant import load_month

    film = get(data, "analysis/ask", topic="appearance_profile", month=NOW, domain="film")
    assert film["status"] == "not_enough_data"
    assert film["decision"]["headline"] == "This question needs Wave Scan data; the instrument filter is Film only."
    ws = get(data, "analysis/ask", topic="layer_vs_band", month=NOW, domain="wavescan", layer="BASE", metric="wb")
    assert ws["decision"]["headline"] == "This question needs Film data; the instrument filter is Wave Scan only."
    drv = get(data, "analysis/ask", topic="cf_drivers", month=NOW, domain="both")
    assert drv["status"] == "needs_slot"
    assert all(c["value"].startswith("wavescan|") for c in drv["slot"]["choices"])
    got = load_month(data["conn"], data["plant"], NOW, plant_scope=None, domain="wavescan", models=[], colors=[])
    assert all(r.measurement for r in got.readings)
