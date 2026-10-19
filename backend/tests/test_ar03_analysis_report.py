"""AR03: Analysis & Report first version (one GET, no migration).

Every write is in one owner transaction that is always rolled back (a marker
plant, its standards, loads and facts); nothing is deleted. The pure tests
(Spearman, OLS, summary templates, status words) need no database.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.deps import get_connection
from app.core.config import Settings
from app.domain.boxplot import box_stats, percentile_linear
from app.domain.report_stats import ols_slope, spearman
from app.domain.report_summary import STATUS_WORD, sentences, status_word
from app.main import create_app
from tests.conftest import _keyword_dsn_to_url

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "frontend" / "src" / "features"
RANGER, RAPTOR = "P703 DBL RANGER", "P703 DBL RAPTOR"
WHITE = "Arctic White"
NOW, BEFORE = "2099-02", "2099-01"
FORBIDDEN = ("rate", "pct", "percent", "score", "grade")
H_ZONES = ("CFHOOD", "LFHOOD", "LRHOOD", "RFHOOD", "RRHOOD", "LCROOF", "RCROOF")
V_ZONES = ("LCFENDER", "LFFENDER", "LRFENDER")
H_CF = (50, 52, 54, 56, 58, 70, 71)  # mean 58.71: between Minimum 55 and Standard 62
H_WB = (11, 12, 15, 19, 26, 34, 47)  # n = 7: linear quartiles differ from other methods
V_WB = (20, 21, 23)


# =====================================================================
# pure: statistics
# =====================================================================
def test_spearman_against_hand_computed_cases():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == (1.0, 4)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == (-1.0, 4)
    # ties take the average rank: y ranks 1, 2, 3.5, 5, 3.5 -> 8 / sqrt(95)
    rho, n = spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7])
    assert n == 5 and rho == pytest.approx(8 / 95 ** 0.5)
    assert spearman([1, 2], [1, 2]) == (None, 2)
    assert spearman([1, 1, 1], [1, 2, 3]) == (None, 3)
    assert spearman([1, None, 3, 4], [1, 2, None, 4]) == (None, 2)


def test_ols_slope_against_hand_computed_cases():
    assert ols_slope([1, 2, 3], [2, 4, 6]) == 2.0
    assert ols_slope([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)
    assert ols_slope([1, 2], [1, 2]) is None
    assert ols_slope([2, 2, 2], [1, 2, 3]) is None


# =====================================================================
# pure: summary templates and words
# =====================================================================
def _report(**over) -> dict:
    report = {
        "plant_code": "FTM", "month": "2026-09", "previous_month": "2026-08",
        "glance": {
            "wavescan": {"readings": 1081, "cars": 2, "below_minimum": 26,
                         "boxes": {"PASS": 18, "WARNING": 6, "FAIL": 0, "NONE": 0}},
            "film": {"cars": 61, "boxes_by_layer": [
                {"layer": "ECOAT", "PASS": 34, "WARNING": 0, "FAIL": 0, "OVER": 0, "NONE": 0},
                {"layer": "PRIMER", "PASS": 32, "WARNING": 0, "FAIL": 1, "OVER": 1, "NONE": 0}]},
        },
        "comparison": [
            {"layer": None, "model": RANGER, "color": WHITE, "orient": "H", "mean_now": 1,
             "mean_before": 2, "status_now": "WARNING", "status_before": "PASS"},
            {"layer": "CLEAR", "model": RANGER, "color": WHITE, "orient": "V", "mean_now": 1,
             "mean_before": 2, "status_now": None, "status_before": "PASS", "_scope_now": "PLANT"},
            {"layer": "BASE", "model": RANGER, "color": WHITE, "orient": "V", "mean_now": 1,
             "mean_before": None, "status_now": "OVER", "status_before": None},
        ],
        "bands": {"bands": [
            {"band": "du", "all": {"median": Decimal("11.44")}},
            {"band": "wb", "all": {"median": Decimal("28.96")}},
            {"band": "cf", "all": {"median": Decimal("53.8")}},
        ]},
        "relationships": {"strongest": [{"a": "Wc", "b": "CF", "rho": Decimal("-0.768"), "n": 1081}],
                          "paired": {"cars": 6, "rows": []}},
    }
    report.update(over)
    return report


def test_every_template_exactly():
    assert sentences(_report()) == [
        "FTM September 2026: 1081 Wave Scan readings on 2 cars; 61 cars with Film readings.",
        "Wave Scan: 18 of 24 boxes Pass, 6 Acceptable, 0 Fail; 26 readings below the minimum.",
        "E-coat: all 34 boxes Pass.",
        "Primer: 2 of 34 boxes not Pass (0 Acceptable, 1 Fail, 1 Over).",
        f"Compared with August 2026: 2 boxes changed status ({RANGER} {WHITE} H: Pass → "
        f"Acceptable; Clear {RANGER} {WHITE} V: Pass → Not graded).",
        "Highest Wave Scan band: Wb (median 29.0); it points to Clear, Base.",
        "Strongest relationship: Wc and CF move in opposite directions (rho -0.8, n 1081).",
        "Film and Wave Scan were measured on the same car 6 times; relationships between "
        "them are exploratory.",
    ]


def test_templates_skip_when_their_data_is_absent():
    empty = _report(
        glance={"wavescan": None, "film": None}, comparison=[], bands=None,
        relationships={"strongest": [], "paired": None},
    )
    assert sentences(empty) == []
    many = _report(relationships={"strongest": [], "paired": {"cars": 100, "rows": []}})
    assert not [s for s in sentences(many) if "exploratory" in s]


def test_status_words_match_the_site_helpers():
    assert STATUS_WORD == {"PASS": "Pass", "WARNING": "Acceptable", "FAIL": "Fail", "OVER": "Over"}
    assert status_word(None) == "No standard" and status_word(None, "NONE") == "No standard"
    assert status_word(None, "COLOR") == "Not graded"
    assert status_word("WARNING", layer="CLEAR") == "For Improvement"
    assert status_word("WARNING", layer="BASE") == "Acceptable"
    ws = (FRONTEND / "measurements" / "overview-display.ts").read_text(encoding="utf-8")
    film = (FRONTEND / "filmthickness" / "film-overview-display.ts").read_text(encoding="utf-8")
    for code in ("PASS", "WARNING", "FAIL"):
        assert re.search(rf'status === "{code}"\) return "{STATUS_WORD[code]}"', ws), code
    for code, word in STATUS_WORD.items():
        if code == "WARNING":
            continue  # Layer-specific display copy is exercised above and in frontend tests.
        assert re.search(rf'{code}: \{{ text: "{word}"', film), code
    assert 'return "No standard"' in ws
    assert '"No standard" : "Not graded"' in film


def test_the_service_grades_nothing_itself():
    for name in ("services/report.py", "repositories/report.py", "domain/report_summary.py",
                 "domain/report_stats.py"):
        source = (ROOT / "app" / name).read_text(encoding="utf-8")
        assert "domain.grading" not in source and "status_of" not in source, name
        for word in ("UPDATE ", "DELETE ", "INSERT "):
            assert word not in source, (name, word)
    assert "COUNTED_VIEW" in (ROOT / "app/repositories/report.py").read_text(encoding="utf-8")


# =====================================================================
# marker plant, one rolled-back transaction
# =====================================================================
@pytest.fixture
def data(admin_dsn):
    engine = create_engine(_keyword_dsn_to_url(admin_dsn))
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            plant = f"AR03{uuid.uuid4().hex[:6].upper()}"
            conn.execute(text("INSERT INTO ref_plant (plant_code, plant_name, is_active) "
                              "VALUES (:p, 'AR03 rolled-back fixture', true)"), {"p": plant})
            conn.execute(text(
                "INSERT INTO ref_plant_ws_point (plant_code, model_code, zone_code, point_no, "
                "tolerance_group) SELECT :p, model_code, zone_code, point_no, tolerance_group "
                "FROM ref_plant_ws_point WHERE plant_code = 'FTM' AND model_code IN (:a, :b) "
                "AND retired_at IS NULL"), {"p": plant, "a": RANGER, "b": RAPTOR})
            conn.execute(text(
                "INSERT INTO ref_plant_film_point (plant_code, model_code, point_code, point_no, "
                "orientation) SELECT :p, model_code, point_code, point_no, orientation "
                "FROM ref_plant_film_point WHERE plant_code = 'FTM' AND model_code IN (:a, :b) "
                "AND retired_at IS NULL"), {"p": plant, "a": RANGER, "b": RAPTOR})
            conn.execute(text("INSERT INTO ref_plant_film_car_rule (plant_code, pattern, note) "
                              "SELECT :p, pattern, 'AR03 fixture' FROM ref_plant_film_car_rule "
                              "WHERE plant_code = 'FTM'"), {"p": plant})
            conn.execute(text("INSERT INTO ref_pair_ws_zone SELECT :p, model_code, zone_code, "
                              "pair_group FROM ref_pair_ws_zone WHERE plant_code = 'FTM'"), {"p": plant})
            conn.execute(text("INSERT INTO ref_pair_film_point SELECT :p, model_code, point_code, "
                              "pair_group FROM ref_pair_film_point WHERE plant_code = 'FTM'"), {"p": plant})
            # Standards: Wave Scan H only (V has none -> status null); Film Primer H plant-wide.
            conn.execute(text(
                "INSERT INTO cf_standard (scope, color_name, orient, ford, min, effective_from, "
                "source_note, plant_code) VALUES ('COLOR', :c, 'H', 62, 55, '2099-01-01', "
                "'AR03 fixture', :p)"), {"c": WHITE, "p": plant})
            conn.execute(text(
                "INSERT INTO film_standard (plant_code, layer_code, orient, lo, hi, source_note) "
                "VALUES (:p, 'PRIMER', 'H', 20, 25, 'AR03 fixture')"), {"p": plant})
            tolerance = dict(conn.execute(text(
                "SELECT zone_code, tolerance_group FROM ref_plant_ws_point "
                "WHERE plant_code = :p AND model_code = :m"), {"p": plant, "m": RANGER}).all())

            def batch(domain):
                return conn.execute(text(
                    "INSERT INTO load_batch (source_file, source_sheet, plant_code, file_hash, "
                    "raw_store_key, status, domain) VALUES (:f, 'AR03', :p, :h, 'unused', "
                    "'COMMITTED', :d) RETURNING load_id"),
                    {"f": f"ar03-{uuid.uuid4().hex}.xlsx", "p": plant, "h": uuid.uuid4().hex * 2,
                     "d": domain}).scalar_one()

            def ws(serial, day, zones, cfs, wbs, du=None):
                load = batch("WAVESCAN")
                for row, (zone, cf, wb) in enumerate(zip(zones, cfs, wbs), 1):
                    conn.execute(text(
                        "INSERT INTO wavescan (measured_date, plant, model, color, serial_no, "
                        "checkzone, tolerance_group, cf, du, wa, wb, wc, wd, we, load_id, "
                        "source_sheet, source_row) VALUES (:d, :p, :m, :c, :s, :z, :t, :cf, :du, "
                        ":wb + 1, :wb, :wb + 2, :wb + 3, :wb - 1, :l, 'AR03', :r)"),
                        {"d": day, "p": plant, "m": RANGER, "c": WHITE, "s": serial, "z": zone,
                         "t": tolerance[zone], "cf": cf, "wb": wb,
                         "du": None if du is not None and row == du else wb / 2, "l": load,
                         "r": row})

            def film(job, day, layer, points, values, model=RANGER):
                load = batch("FILMTHICKNESS")
                for row, (point, value) in enumerate(zip(points, values), 1):
                    conn.execute(text(
                        "INSERT INTO filmthickness (measured_date, plant, model, color, job_no, "
                        "point_code, src_location_text, layer_code, thickness, logical_vehicle_id, "
                        "load_id, source_sheet, source_row) VALUES (:d, :p, :m, :c, :j, :pt, :pt, "
                        ":ly, :v, :j, :l, 'AR03', :r)"),
                        {"d": day, "p": plant, "m": model, "c": WHITE, "j": job, "pt": point,
                         "ly": layer, "v": value, "l": load, "r": row})

            now, before = date(2099, 2, 10), date(2099, 1, 10)
            hood = [f"{i:03d}HOOD" for i in range(1, 6)]
            ws("7000001", now, H_ZONES, H_CF, H_WB, du=1)  # row 1 has no du
            ws("7000001", now, V_ZONES, (70, 70, 70), V_WB)
            ws("7000002", before, H_ZONES, (70,) * 7, (30,) * 7)
            film("AW_DBL_7000001", now, "PRIMER", hood, (10, 22, 22, 22, 22))  # mean 19.6 -> FAIL
            film("AW_DBL_7000001", now, "CLEAR", hood, (40, 41, 42, 43, 44))
            film("AW_DBL_7000001", now, "PRIMER", ("016LTFEND", "096TGATEIN"), (21, 99))
            film("AW_RB_7000009", now, "PRIMER", hood, (21, 21, 21, 21, 21), model=RAPTOR)  # film only

            conn.execute(text("SET LOCAL ROLE app_rw"))
            app = create_app(Settings(env="development", app_database_url="", auth_dev_bypass=True,
                                      auth_dev_bypass_roles_raw="viewer", ingest_worker_enabled=False))

            def connection():
                yield conn
            app.dependency_overrides[get_connection] = connection
            with TestClient(app) as client:
                yield {"client": client, "plant": plant, "conn": conn}
        finally:
            tx.rollback()
    engine.dispose()


def get(data, path="analysis/report", **params):
    response = data["client"].get(f"/api/v1/plants/{data['plant']}/{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def report(data, **params):
    return get(data, month=NOW, **params)


def _band(body, band):
    return next(b for b in body["bands"]["bands"] if b["band"] == band)


def _dec(values):
    return [Decimal(v) for v in values]


# =====================================================================
# statuses, issues, comparison
# =====================================================================
def test_statuses_equal_the_overview_endpoints(data):
    body = report(data)
    ws = get(data, "wavescan/overview", month=NOW)["boxes"]
    film = get(data, "filmthickness/overview", month=NOW)["boxes"]
    expected = {("wavescan", None, b["model_code"], b["color_name"], b["orient"][0]): b["status"]
                for b in ws}
    expected |= {("film", b["layer_code"], b["model_code"], b["color_name"], b["orient"]): b["status"]
                 for b in film}
    got = {(r["domain"], r["layer"], r["model"], r["color"], r["orient"]): r["status_now"]
           for r in body["comparison"] if r["mean_now"] is not None}
    assert got == expected
    issues = {(i["domain"], i["layer"], i["model"], i["color"], i["orient"]): i["status"]
              for i in body["issues"]}
    assert issues == {k: v for k, v in expected.items() if v != "PASS"}
    glance = body["glance"]["wavescan"]
    assert glance["boxes"] == {"PASS": 0, "WARNING": 1, "FAIL": 0, "NONE": 1}
    assert glance["readings"] == 10 and glance["cars"] == 1 and glance["below_minimum"] == 3
    assert glance["previous"]["boxes"] == {"PASS": 1, "WARNING": 0, "FAIL": 0, "NONE": 0}
    primer = next(r for r in body["glance"]["film"]["boxes_by_layer"] if r["layer"] == "PRIMER")
    assert primer["FAIL"] == 1


def test_issues_are_ordered_with_their_limits_and_points(data):
    issues = report(data)["issues"]
    assert [i["status"] for i in issues][0] == "FAIL"
    order = {"FAIL": 0, "OVER": 1, "WARNING": 2, None: 3}
    assert [order[i["status"]] for i in issues] == sorted(order[i["status"]] for i in issues)
    fail = issues[0]
    assert (fail["domain"], fail["layer"], fail["model"], fail["orient"]) == ("film", "PRIMER", RANGER, "H")
    assert {k: Decimal(v) for k, v in fail["limits"].items()} == {"Minimum": 20, "Maximum": 25}
    assert [(Decimal(p["value"]), p["side"], p["point_code"], p["car"]) for p in fail["points"]] == [
        (10, "LOW", "001HOOD", "AW_DBL_7000001")]
    warn = next(i for i in issues if i["status"] == "WARNING")
    assert warn["domain"] == "wavescan"
    assert {k: Decimal(v) for k, v in warn["limits"].items()} == {"Standard": 62, "Minimum": 55}
    assert [(Decimal(p["value"]), p["car"], p["panel"]) for p in warn["points"]] == [
        (Decimal(50), "7000001", "HOOD"), (Decimal(52), "7000001", "HOOD"),
        (Decimal(54), "7000001", "HOOD")]


def test_comparison_keys_and_a_missing_side(data):
    rows = {(r["domain"], r["layer"], r["orient"], r["model"]): r for r in report(data)["comparison"]}
    h = rows[("wavescan", None, "H", RANGER)]
    assert (h["status_now"], h["status_before"]) == ("WARNING", "PASS")
    assert Decimal(h["mean_before"]) == 70
    assert Decimal(h["mean_change"]) == Decimal(h["mean_now"]) - Decimal(h["mean_before"])
    v = rows[("wavescan", None, "V", RANGER)]
    assert v["mean_before"] is None and v["mean_change"] is None and v["status_before"] is None


# =====================================================================
# bands (superseded AR03 tests 1-8)
# =====================================================================
def test_band_boxes_equal_box_stats(data):
    body = report(data)
    wb = _band(body, "wb")
    for key, values in (("all", H_WB + V_WB), ("horizontal", H_WB), ("vertical", V_WB)):
        stats = box_stats(_dec(values))
        assert Decimal(wb[key]["q1"]) == stats.q1 and Decimal(wb[key]["q3"]) == stats.q3, key
        assert Decimal(wb[key]["median"]) == stats.median and wb[key]["n"] == stats.n, key
    assert [b["band"] for b in body["bands"]["bands"]] == ["du", "wa", "wb", "wc", "wd", "we", "cf"]
    assert body["bands"]["n_readings"] == 10 and body["bands"]["n_cars"] == 1


def test_a_null_band_is_skipped_for_that_band_only(data):
    body = report(data)
    assert _band(body, "du")["all"]["n"] == _band(body, "wb")["all"]["n"] - 1


def test_values_only_below_five(data):
    wb = _band(report(data), "wb")
    assert _dec(wb["vertical"]["values"]) == _dec(V_WB)
    assert wb["all"]["values"] is None and wb["horizontal"]["values"] is None


def test_panel_group_medians_and_order(data):
    groups = report(data)["bands"]["panel_groups"]
    assert [g["panel_group"] for g in groups] == ["HOOD", "ROOF", "FENDER"]
    hood = next(g for g in groups if g["panel_group"] == "HOOD")
    assert hood["n_readings"] == 5
    assert Decimal(hood["median"]["wb"]) == percentile_linear(sorted(_dec(H_WB[:5])), Decimal("0.5"))


def test_previous_month_median_follows_the_filters(data):
    assert Decimal(_band(report(data), "wb")["previous_month_median"]) == 30
    assert _band(get(data, month=BEFORE), "wb")["previous_month_median"] is None


def test_month_default_empty_bad_and_unknown_plant(data):
    body = get(data)
    assert body["month"] == NOW and body["previous_month"] == BEFORE
    assert body["options"]["months"] == [NOW, BEFORE]
    empty = get(data, month="2099-05")
    assert empty["bands"]["n_readings"] == 0 and _band(empty, "wb")["all"] is None
    assert empty["glance"] == {"wavescan": None, "film": None} and empty["issues"] == []
    client = data["client"]
    assert client.get(f"/api/v1/plants/{data['plant']}/analysis/report?month=2099-13").status_code == 422
    missing = client.get("/api/v1/plants/NOWHERE-AR03/analysis/report")
    assert missing.status_code == 404 and "No plant 'NOWHERE-AR03'" in missing.json()["message"]


def test_counted_not_active(data):
    conn = data["conn"]
    conn.execute(text("RESET ROLE"))
    conn.execute(text("INSERT INTO ws_point_setting (plant_code, model_code, zone_code, counted, "
                      "reason) VALUES (:p, :m, 'LCROOF', false, 'AR03 fixture')"),
                 {"p": data["plant"], "m": RANGER})
    conn.execute(text("SET LOCAL ROLE app_rw"))
    body = report(data)
    assert body["bands"]["n_readings"] == 9
    assert "ROOF" in [g["panel_group"] for g in body["bands"]["panel_groups"]]  # RCROOF stays


def test_filters_narrow_every_section_and_options_stay(data):
    body = report(data, models=[RAPTOR])
    assert body["models"] == [RAPTOR]
    assert body["bands"]["n_readings"] == 0 and body["glance"]["wavescan"] is None
    assert {i["model"] for i in body["issues"]} <= {RAPTOR}
    assert body["relationships"]["paired"]["cars"] == 0
    assert set(body["options"]["models"]) >= {RANGER, RAPTOR}
    film_only = report(data, domain="film")
    assert film_only["bands"] is None and film_only["glance"]["wavescan"] is None
    assert film_only["relationships"]["wavescan"] is None and film_only["relationships"]["paired"] is None


# =====================================================================
# relationships
# =====================================================================
def test_paired_uses_only_paired_cars_and_mapped_groups(data):
    rel = report(data)["relationships"]
    paired = rel["paired"]
    assert paired["cars"] == 1  # 7000009 is film only
    rows = {(r["film_layer"], r["ws_param"]): r for r in paired["rows"]}
    assert len(rows) == 28
    # PRIMER: HOOD + L_FENDER; 096TGATEIN has no pair group so adds no unit.
    assert rows[("PRIMER", "du")]["n"] == 2 and rows[("PRIMER", "du")]["rho"] is None
    assert rows[("CLEAR", "wb")]["n"] == 1 and rows[("ECOAT", "wb")]["n"] == 0
    assert rel["wavescan"]["params"] == ["du", "wa", "wb", "wc", "wd", "we", "cf"]
    assert rel["film"]["params"] == ["ECOAT", "PRIMER", "BASE", "CLEAR"]
    assert rel["wavescan"]["n"][2][2] == 10 and rel["wavescan"]["n"][0][2] == 9
    assert all(s["n"] >= 10 for s in rel["strongest"]) and len(rel["strongest"]) <= 5


# =====================================================================
# summary, words, API
# =====================================================================
def test_summary_has_no_share_and_uses_the_site_words(data):
    body = report(data)
    assert body["summary"][0] == f"{data['plant']} February 2099: 10 Wave Scan readings on 1 cars; " \
                                 "2 cars with Film readings."
    assert "Wave Scan: 0 of 2 boxes Pass, 1 Acceptable, 0 Fail; 3 readings below the minimum." \
        in body["summary"]
    assert not [s for s in body["summary"] if "%" in s or "Warning" in s]


def test_no_key_names_a_rate_share_score_or_grade(data):
    spec = data["client"].app.openapi()
    assert "/api/v1/plants/{plant_code}/analysis/report" in spec["paths"]
    schemas = spec["components"]["schemas"]
    seen, todo = set(), ["AnalysisReportOut"]
    keys = []
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        props = schemas[name].get("properties", {})
        keys += list(props)
        todo += re.findall(r'#/components/schemas/(\w+)', str(props))
    assert len(seen) > 10
    assert keys and not [k for k in keys if any(word in k.lower() for word in FORBIDDEN)]


def test_every_role_reads_it(data):
    for role in ("viewer", "engineer", "admin"):
        data["client"].app.state.settings.auth_dev_bypass_roles_raw = role
        assert report(data)["plant_code"] == data["plant"]
