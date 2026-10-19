"""T67 -- Film Overview: box status, family order, limit labels, out-of-spec points.

Claims (task section 6):

1. ``film_box_status`` follows the T67-CONTEXT table on the box mean: edges
   inside, Clear never OVER, Clear without target None, no rule None.
2. ``out_of_spec``: LOW / HIGH, no HIGH without ``hi``, edges not listed,
   Clear readings between lo and target not listed.
3. Labels exactly as D-67-05.
4. Migration 0027: latest AAT CLEAR is 30 / null / 35; the T63 AAT-02 pair
   is still stored, unchanged; 116 rows.
5. Live GET: every status equals ``film_box_status(mean, ...)``; every
   ``out_of_spec`` equals the facts beyond the box's lines; NONE boxes are
   null / []; AAT Clear 30/35 with Clear labels, never OVER; FVL E-coat H
   lists its LOW readings with point codes.
6. Family: AAT Absolute / Shadow Black DM (3), SAP Ignite Orange MM, FTM
   Code Orange MS; color_options and boxes in D-67-08 / D-67-09 order.
7. Synthetic: a group whose mean passes with one reading under lo is PASS,
   the reading listed LOW.
8. Publish validator: CLEAR with hi is 422; CLEAR lo + target is 201.
9. Nothing else: grading_available false; no pass-rate or count field; the
   T05 import guard sees only the two allowed services.

Test safety: rows are deleted only by this file's own NOTE or by
``film_cleanup`` (this test's own load_ids). Never a seed or reference row.
"""

from __future__ import annotations

from tests.ro19_synthetic import ro19_plants  # noqa: F401

import re
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.boxplot import model_sort_key
from app.domain.film_overview import line_labels, out_of_spec
from app.domain.film_standards import LAYERS
from app.domain.grading import EPS, film_box_status
from tests.test_t03_contract import client, make_client  # noqa: F401
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import commit, film_cleanup, pelt, sent  # noqa: F401
from tests.film_synthetic import film_month, forget_film_month, gold_points
from tests.test_t48_filmthickness_read import old_day

REPO = Path(__file__).resolve().parents[2]
PATH = "/api/v1/plants/{plant_code}/filmthickness/overview"
POST = "/api/v1/filmthickness/standards"
NOTE = "pytest-t67-film-overview-status"
T63_AAT_CLEAR = "FILM-STANDARDS-AUDIT AAT-02"
T67_AAT_CLEAR = "FILM-STANDARDS-AUDIT AAT-02 (T67 owner correction 2026-10-06)"
CANONICAL_BLACK = "Absolute / Shadow Black"
PLANTS = ("AAT", "FTM", "FVL", "SAP")
NO_CLEAR_MAX = "Clear has no Maximum; use target for Minimum requirement"


def D(x) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def get(c, plant: str, **params) -> dict:
    response = c.get(PATH.format(plant_code=plant), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def every_payload(c) -> list[dict]:
    """Latest month at each plant, plus FTM May (Desert Island Blue)."""
    return [get(c, p) for p in PLANTS] + [get(c, "FTM", month="2026-05")]


# ---------------------------------------------------------------- 1
STATUS_TABLE = [
    # E-coat, lo only (FTM/FVL/SAP shape)
    ("ECOAT", 17.99, 18, None, None, "FAIL"),
    ("ECOAT", 18, 18, None, None, "PASS"),            # edge: mean == lo is not FAIL
    ("ECOAT", 99, 18, None, None, "PASS"),            # no Maximum -> never OVER
    # E-coat, lo + hi (AAT 15-25)
    ("ECOAT", 14.9, 15, 25, None, "FAIL"),
    ("ECOAT", 15, 15, 25, None, "PASS"),
    ("ECOAT", 25, 15, 25, None, "PASS"),              # edge: mean == hi is not OVER
    ("ECOAT", 25.01, 15, 25, None, "OVER"),
    # Primer / Base, lo + hi
    ("PRIMER", 19.5, 20, 25, None, "FAIL"),
    ("PRIMER", 22, 20, 25, None, "PASS"),
    ("PRIMER", 26, 20, 25, None, "OVER"),
    ("BASE", 14, 15, 20, None, "FAIL"),
    ("BASE", 20, 15, 20, None, "PASS"),
    ("BASE", 20.5, 15, 20, None, "OVER"),
    # one bound only applies only that bound
    ("BASE", 5, 9, None, None, "FAIL"),
    ("PRIMER", 30, None, 25, None, "OVER"),
    ("PRIMER", 1, None, 25, None, "PASS"),
    # Clear, lo + target
    ("CLEAR", 29.9, 30, None, 35, "FAIL"),
    ("CLEAR", 30, 30, None, 35, "WARNING"),           # edge: mean == lo is not FAIL
    ("CLEAR", 34.99, 30, None, 35, "WARNING"),
    ("CLEAR", 35, 30, None, 35, "PASS"),              # edge: mean == target is PASS
    ("CLEAR", 80, 36, None, 46, "PASS"),
    ("CLEAR", 80, 30, 35, 35, "PASS"),                # stray hi: Clear never OVER
    ("CLEAR", 40, 30, 35, None, "None"),              # Clear without target -> None
    ("CLEAR", 40, None, None, 35, "None"),            # Clear without lo -> None
    # no rule -> None
    ("ECOAT", 20, None, None, None, "None"),
    ("PRIMER", 20, None, None, None, "None"),
    ("BASE", 20, None, None, None, "None"),
    ("CLEAR", 20, None, None, None, "None"),
]


@pytest.mark.parametrize("layer,mean,lo,hi,target,expected", STATUS_TABLE)
def test_film_box_status_table(layer, mean, lo, hi, target, expected):
    want = None if expected == "None" else expected
    assert film_box_status(layer, D(mean), D(lo), D(hi), D(target)) == want
    assert film_box_status(layer, mean, lo, hi, target) == want  # floats too


def test_film_box_status_eps_and_missing_mean():
    assert film_box_status("ECOAT", 18 - EPS / 10, 18, None, None) == "PASS"
    assert film_box_status("BASE", 20 + EPS / 10, 15, 20, None) == "PASS"
    assert film_box_status("CLEAR", 35 - EPS / 10, 30, None, 35) == "PASS"
    assert film_box_status("BASE", None, 15, 20, None) is None
    assert film_box_status("BASE", float("nan"), 15, 20, None) is None
    outcomes = {
        film_box_status("CLEAR", m, 30, hi, 35)
        for m in range(0, 200) for hi in (None, 35, 40)
    }
    assert "OVER" not in outcomes and outcomes == {"FAIL", "WARNING", "PASS"}
    assert not {
        film_box_status(layer, m, 10, 20, None)
        for layer in ("ECOAT", "PRIMER", "BASE") for m in range(0, 40)
    } & {"WARNING"}, "WARNING exists only on Clear"


# ---------------------------------------------------------------- 2
def _r(value, point="P", car="C") -> dict:
    return {"value": Decimal(str(value)), "point_code": point, "logical_vehicle_id": car}


def test_out_of_spec_sides_edges_and_order():
    readings = [_r(9, "A"), _r(10, "B"), _r(20, "C"), _r(21, "D"), _r(5, "E"), _r(15, "F")]
    got = out_of_spec(readings, Decimal("10"), Decimal("20"), eps=EPS)
    assert [(p["side"], p["value"], p["point_code"]) for p in got] == [
        ("LOW", Decimal("5"), "E"), ("LOW", Decimal("9"), "A"), ("HIGH", Decimal("21"), "D"),
    ]
    assert got[0]["logical_vehicle_id"] == "C"
    # no Maximum -> no HIGH
    assert [p["side"] for p in out_of_spec(readings, Decimal("10"), None, eps=EPS)] == [
        "LOW", "LOW"]
    # no line at all -> nothing
    assert out_of_spec(readings, None, None, eps=EPS) == []
    # Clear: the service passes hi=None; readings between lo and target are in spec
    clear = [_r(29.9), _r(30), _r(32), _r(34.99), _r(50)]
    assert [p["value"] for p in out_of_spec(clear, Decimal("30"), None, eps=EPS)] == [
        Decimal("29.9")]


# ---------------------------------------------------------------- 3
@pytest.mark.parametrize("layer,lo,hi,target,labels", [
    ("ECOAT", 18, None, None, ("Minimum", None, None)),          # FTM / FVL / SAP
    ("ECOAT", 15, 25, None, ("Minimum", "Maximum", None)),       # AAT
    ("PRIMER", 20, 25, None, ("Minimum", "Maximum", None)),
    ("BASE", 15, 20, None, ("Minimum", "Maximum", None)),
    ("CLEAR", 36, None, 46, ("No point below", None, "Minimum requirement")),
    ("CLEAR", 30, 35, 35, ("No point below", None, "Minimum requirement")),  # stray hi
    ("BASE", None, None, None, (None, None, None)),
    ("CLEAR", 30, None, None, ("No point below", None, None)),
])
def test_line_labels(layer, lo, hi, target, labels):
    got = line_labels(layer, lo, hi, target)
    assert (got["lo_label"], got["hi_label"], got["target_label"]) == labels


# ---------------------------------------------------------------- 4
def test_migration_appends_the_aat_clear_correction(client, admin_conn):  # noqa: F811
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] >= "0027"
        cur.execute(
            "SELECT count(*) FROM film_standard "
            "WHERE created_by IS NULL AND source_note LIKE 'FILM-STANDARDS-AUDIT %%'"
        )
        assert cur.fetchone()[0] == 116
        for note, shape in ((T63_AAT_CLEAR, (30, 35, None)), (T67_AAT_CLEAR, (30, None, 35))):
            cur.execute(
                "SELECT orient, lo, hi, target, color_name, created_by, source_document "
                "FROM film_standard WHERE plant_code = 'AAT' AND layer_code = 'CLEAR' "
                "AND source_note = %s ORDER BY orient",
                (note,),
            )
            rows = cur.fetchall()
            assert [r[0] for r in rows] == ["H", "V"], note
            for r in rows:
                assert (r[1], r[2], r[3]) == tuple(D(v) for v in shape), note
                assert r[4] is None and r[5] is None
                assert r[6] == "Prototype.html constants (owner-accepted 2026-10-06)"
    total_rows = [
        r for r in client.get("/api/v1/plants/AAT/filmthickness/standards").json()["rules"]
        if r["layer_code"] == "CLEAR" and r["color_name"] is None
    ]
    assert len(total_rows) == 1
    for orient in ("h", "v"):
        rule = total_rows[0][orient]
        assert (rule["lo"], rule["hi"], rule["target"]) == (30.0, None, 35.0)
        assert rule["source_note"] == T67_AAT_CLEAR


# ---------------------------------------------------------------- 5
def _facts(admin_conn, plant: str, month: str) -> dict[tuple, list[tuple]]:
    """(layer, model, colour, H/V) -> [(value, point_code, vehicle)], read independently."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.layer_code, f.model, f.color,
                   COALESCE(btrim(pp.orientation), btrim(mp.orientation)),
                   f.thickness, f.point_code, f.logical_vehicle_id
              FROM filmthickness_active f
              LEFT JOIN ref_plant_film_point pp
                ON pp.plant_code = f.plant AND pp.model_code = f.model
               AND pp.point_code = f.point_code AND pp.retired_at IS NULL
              LEFT JOIN ref_model_film_point mp
                ON mp.model_code = f.model AND mp.point_code = f.point_code
             WHERE f.plant = %s AND f.thickness IS NOT NULL
               AND to_char(f.measured_date, 'YYYY-MM') = %s
            """,
            (plant, month),
        )
        out: dict[tuple, list[tuple]] = defaultdict(list)
        for layer, model, color, orient, value, point, car in cur.fetchall():
            out[(layer, model, color, orient)].append((Decimal(value), point, car))
        return out


# =====================================================================
# T85: the Film months the status claims used to be read from
# =====================================================================
#: The live AAT / FVL / SAP / FTM Film walks these tests measured were in
#: T85's Clear list. The claims are about the **status and out-of-spec
#: read**, which is recreatable, so each gets a month it owns. The spec
#: rules themselves are the seed's -- T85 kept every `film_standard` row.
def _month(admin_conn, *, plant, model, colour, day, values, vehicles=2):
    points = gold_points(admin_conn, plant, model)
    assert points, f"no live Film points for {plant} / {model}"
    readings = {
        point.point_code: dict(zip(("CLEAR", "BASE", "PRIMER", "ECOAT"), values))
        for point in points
    }
    batch = film_month(admin_conn, plant=plant, model=model, colour=colour,
                       day=day, readings=readings, vehicles=vehicles)
    batch["points"] = {pt.point_code: pt.orientation for pt in points}
    return batch


@pytest.fixture()
def status_months(admin_conn):  # T85
    """One month at each plant this module makes a claim about.

    AAT carries two colours from two families (Dark Metallics and Medium
    Metallics), because one of the claims is that AAT spans families.
    FVL's E-coat is deliberately under its plant-wide Minimum of 20, so the
    out-of-spec list has something true to list.
    """
    made = []
    try:
        aat_black = _month(admin_conn, plant="AAT", model="U704",
                           colour=CANONICAL_BLACK, day="2026-09-15",
                           values=(33.0, 18.0, 10.0, 21.0))
        made.append(aat_black)
        aat_green = _month(admin_conn, plant="AAT", model="U704",
                           colour="Acacia Green", day="2026-09-15",
                           values=(34.0, 18.4, 10.2, 21.4))
        made.append(aat_green)
        # Under FVL's ECOAT Minimum 20, and every reading different, so the
        # out-of-spec list has an order to be asserted.
        fvl = _month(admin_conn, plant="FVL", model="P703 DBL RANGER",
                     colour=CANONICAL_BLACK, day="2026-08-12",
                     values=(40.0, 19.0, 25.0, 17.0), vehicles=3)
        made.append(fvl)
        sap = _month(admin_conn, plant="SAP", model="P703 DBL RANGER",
                     colour="Ignite Orange", day="2026-08-12",
                     values=(40.0, 17.0, 10.0, 21.0))
        made.append(sap)
        ftm = _month(admin_conn, plant="FTM", model="P703 DBL RANGER",
                     colour="Code Orange", day="2026-07-14",
                     values=(40.0, 17.0, 10.0, 21.0))
        made.append(ftm)
        yield {"aat": aat_black, "aat_green": aat_green, "fvl": fvl,
               "sap": sap, "ftm": ftm}
    finally:
        for batch in reversed(made):
            forget_film_month(admin_conn, batch)


def _expected_oos(box: dict, readings: list[tuple]) -> list[tuple]:
    lo = D(box["lo"])
    hi = None if box["layer_code"] == "CLEAR" else D(box["hi"])
    low = sorted((v, p, c) for v, p, c in readings if lo is not None and v < lo)
    high = sorted((v, p, c) for v, p, c in readings if hi is not None and v > hi)
    return [("LOW", *x) for x in low] + [("HIGH", *x) for x in high]


def test_live_status_and_out_of_spec_match_the_facts(  # T85
    viewer, admin_conn, status_months,  # noqa: F811
):
    checked = 0
    listed = 0
    for payload in every_payload(viewer):
        facts = _facts(admin_conn, payload["plant_code"], payload["month"])
        for b in payload["boxes"]:
            want = film_box_status(
                b["layer_code"], Decimal(b["mean"]), D(b["lo"]), D(b["hi"]), D(b["target"])
            )
            assert b["status"] == want, b
            if b["standard_scope"] == "NONE":
                assert b["status"] is None and b["out_of_spec"] == []
            if b["layer_code"] == "CLEAR":
                assert b["status"] != "OVER"
                assert all(p["side"] == "LOW" for p in b["out_of_spec"])
            if b["layer_code"] != "CLEAR":
                assert b["status"] != "WARNING"
            key = (b["layer_code"], b["model_code"], b["color_name"], b["orient"])
            got = [
                (p["side"], Decimal(p["value"]), p["point_code"], p["logical_vehicle_id"])
                for p in b["out_of_spec"]
            ]
            exp = _expected_oos(b, facts[key])
            # Same multiset; order is LOW first then value (ties in any order).
            assert sorted(got) == sorted(exp), key
            assert [(s, v) for s, v, _, _ in got] == [(s, v) for s, v, _, _ in exp], key
            checked += 1
            listed += len(got)
    # T85: this used to be `checked > 100`, a statement about how much data
    # the owner had uploaded. The months above are this test's own, so the
    # guard can say what it actually needs: every layer x orientation box
    # was compared, and at least one of them really had readings out of
    # spec -- without that, the out-of-spec branch above is never executed.
    assert checked >= 8, checked
    assert listed > 0, "no box had an out-of-spec reading; the comparison is vacuous"


def test_aat_clear_uses_the_correction_and_clear_labels(  # T85
    viewer, status_months,  # noqa: F811
):
    aat = get(viewer, "AAT", month=status_months["aat"]["month"])
    clear = [b for b in aat["boxes"] if b["layer_code"] == "CLEAR"]
    assert clear
    for b in clear:
        assert (D(b["lo"]), b["hi"], D(b["target"]), b["standard_scope"]) == (
            Decimal("30"), None, Decimal("35"), "PLANT")
        assert (b["lo_label"], b["hi_label"], b["target_label"]) == (
            "No point below", None, "Minimum requirement")
        assert b["status"] in ("PASS", "WARNING", "FAIL")
    ecoat = [b for b in aat["boxes"] if b["layer_code"] == "ECOAT"]
    assert all((b["lo_label"], b["hi_label"]) == ("Minimum", "Maximum") for b in ecoat)


def test_fvl_ecoat_h_lists_its_low_readings(viewer, admin_conn, ro19_plants):  # noqa: F811
    plant = ro19_plants(colours=(CANONICAL_BLACK,))
    with admin_conn.cursor() as cur:
        cur.execute("INSERT INTO film_standard (plant_code, layer_code, orient, lo, source_note) "
                    "VALUES (%s, 'ECOAT', 'H', 20, 'RO19 synthetic minimum')", (plant,))
    batch = film_month(admin_conn, plant=plant, model="P703 DBL RANGER", colour=CANONICAL_BLACK,
                       day="2012-02-12", readings={
                           "001HOOD": {"ECOAT": 17}, "002HOOD": {"ECOAT": 18},
                           "003HOOD": {"ECOAT": 19},
                       }, vehicles=3)
    fvl = get(viewer, plant, month=batch["month"])
    [b] = [x for x in fvl["boxes"] if (x["layer_code"], x["orient"]) == ("ECOAT", "H")]
    assert (D(b["lo"]), b["hi"], b["lo_label"], b["hi_label"]) == (
        Decimal("20"), None, "Minimum", None)
    assert Decimal(b["median"]) < Decimal("20")
    assert b["status"] == film_box_status("ECOAT", Decimal(b["mean"]), Decimal("20"), None, None)
    assert b["out_of_spec"], "readings under Minimum 20 are listed"
    assert all(p["side"] == "LOW" and Decimal(p["value"]) < 20 for p in b["out_of_spec"])
    assert all(p["point_code"] and len(p["logical_vehicle_id"]) == 64 for p in b["out_of_spec"])
    values = [Decimal(p["value"]) for p in b["out_of_spec"]]
    assert values == sorted(values)


# ---------------------------------------------------------------- 6
def _family(payload: dict, color: str) -> set[tuple]:
    from_boxes = {
        (b["family_code"], b["family_name"], b["family_order"])
        for b in payload["boxes"] if b["color_name"] == color
    }
    from_options = {
        (c["family_code"], c["family_name"], c["family_order"])
        for c in payload["color_options"] if c["color_name"] == color
    }
    assert from_boxes == from_options and len(from_boxes) == 1, (color, from_boxes, from_options)
    return from_boxes


def test_plant_family_metadata(viewer, status_months):  # noqa: F811  # T85
    aat = get(viewer, "AAT", month=status_months["aat"]["month"])
    assert _family(aat, CANONICAL_BLACK) == {("DM", "Dark Metallics", 3)}
    # ADR 0010: SAP's family for Ignite Orange is its own (MM), not AAT's (MS).
    sap = get(viewer, "SAP", month=status_months["sap"]["month"])
    assert _family(sap, "Ignite Orange") == {("MM", "Medium Metallics", 2)}
    ftm = get(viewer, "FTM", month=status_months["ftm"]["month"])
    assert _family(ftm, "Code Orange") == {("MS", "Medium Solids", 5)}


def test_color_options_and_box_order(viewer, status_months):  # noqa: F811  # T85
    for payload in every_payload(viewer):
        options = payload["color_options"]
        assert options == sorted(
            options,
            key=lambda c: (c["family_order"] is None, c["family_order"] or 0, c["color_name"]),
        )
        # T73 CHANGE: D-73-13 supersedes D-67-09's family/colour components;
        # within layer x model x H/V boxes follow the Base-ladder color_rank.
        order = [
            (
                LAYERS.index(b["layer_code"]),
                model_sort_key(b["model_code"]),
                0 if b["orient"] == "H" else 1,
                b["color_rank"],
            )
            for b in payload["boxes"]
        ]
        assert order == sorted(order), payload["plant_code"]
    # T85: the fixture walks AAT in two colours from two families, so this
    # is a real claim about ordering across families and not about how many
    # colours happen to have been uploaded.
    aat = get(viewer, "AAT", month=status_months["aat"]["month"])
    assert len({c["family_order"] for c in aat["color_options"]}) > 1, "AAT spans families"


# ---------------------------------------------------------------- 7
#: Clearcoat, Base, Primer, E-Coat (pelt()'s column order). FVL rules: ECOAT lo 20
#: plant-wide; CLEAR H 36 / t46, V 30 / t46; BASE Absolute / Shadow Black 18-20.
ONE_LOW = {
    "001HOOD": (47, 19, 25, 30.0),
    "002HOOD": (47, 19, 25, 19.0),      # E-coat under Minimum 20; mean 24.5 passes
    "022LTFTDOOR": (40, 19, 25, 22),
    "036LBOXSIDE": (40, 19, 25, 22),
}


@pytest.fixture()
def fvl_one_low(engineer, admin, admin_conn, film_cleanup):  # noqa: F811
    day, month = old_day()
    job = f"UR{uuid.uuid4().hex[:8].upper()}"
    data = pelt(list(ONE_LOW), colour="Absolute Black", day=day, job=job,
                values=list(ONE_LOW.values()))
    review = sent(engineer, film_cleanup, admin_conn, f"P703-{job}-AB.xlsx", data,
                  "FVL")["Quick Summary"]
    commit(engineer, admin, review)
    return month


def test_mean_passes_with_one_reading_under_lo(viewer, fvl_one_low):  # noqa: F811
    payload = get(viewer, "FVL", month=fvl_one_low)

    def box(layer, orient):
        [b] = [x for x in payload["boxes"] if (x["layer_code"], x["orient"]) == (layer, orient)]
        return b

    ecoat = box("ECOAT", "H")
    assert (Decimal(ecoat["mean"]), ecoat["status"]) == (Decimal("24.5"), "PASS")
    [low] = ecoat["out_of_spec"]
    assert (low["side"], Decimal(low["value"]), low["point_code"]) == (
        "LOW", Decimal("19"), "002HOOD")
    assert box("ECOAT", "V")["out_of_spec"] == []
    # Clear H mean 47 >= target 46: PASS. Clear V 40 between lo 30 and target 46:
    # WARNING, and no reading is out of spec (between lo and target is in spec).
    assert box("CLEAR", "H")["status"] == "PASS"
    assert (box("CLEAR", "V")["status"], box("CLEAR", "V")["out_of_spec"]) == ("WARNING", [])
    assert box("BASE", "H")["status"] == "PASS"
    assert payload["color_options"] == [{
        "color_name": CANONICAL_BLACK, "family_code": "DM",
        "family_name": "Dark Metallics", "family_order": 3,
    }]


# ---------------------------------------------------------------- 8
@pytest.fixture()
def own_standards(admin_conn):
    def _purge() -> None:
        # Only this file's rows, by its own note. Never a seed row.
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM film_standard WHERE source_note = %s", (NOTE,))

    _purge()
    yield
    _purge()


def _mine(admin_conn) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM film_standard WHERE source_note = %s", (NOTE,))
        return int(cur.fetchone()[0])


def test_publish_refuses_hi_on_clear(admin, admin_conn, own_standards):  # noqa: F811
    def body(layer, h, v):
        return {"plant_code": "FTM", "layer_code": layer, "color_name": None,
                "h": h, "v": v, "source_document": "synthetic", "source_note": NOTE}

    for h, v in (({"lo": 36, "hi": 60, "target": 46}, {"lo": 30, "target": 46}),
                 ({"lo": 36, "target": 46}, {"lo": 30, "hi": 50})):
        response = admin.post(POST, json=body("CLEAR", h, v))
        assert response.status_code == 422, response.text
        assert NO_CLEAR_MAX in response.json()["message"]
        assert "correlationId" in response.json()
    assert _mine(admin_conn) == 0, "a refusal inserts nothing"

    ok = admin.post(POST, json=body("CLEAR", {"lo": 36, "target": 46}, {"lo": 30, "target": 46}))
    assert ok.status_code == 201, ok.text
    primer = admin.post(POST, json=body("PRIMER", {"lo": 20, "hi": 25}, {"lo": 20, "hi": 25}))
    assert primer.status_code == 201, "hi is still allowed off Clear"
    assert _mine(admin_conn) == 4


# ---------------------------------------------------------------- 9
def test_nothing_else_moves(client):  # noqa: F811
    assert client.get("/api/v1/meta").json()["grading_available"] is False
    spec = client.app.openapi()
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(spec["paths"]) >= 57  # T86: + GET /mappings/panel-match.
    backend_copy = (REPO / "backend" / "openapi.json").read_bytes()
    assert backend_copy == (REPO / "docs" / "openapi.json").read_bytes()
    schemas = spec["components"]["schemas"]
    assert schemas["FilmBoxStatus"]["enum"] == ["PASS", "WARNING", "FAIL", "OVER"]
    assert {"FilmColorOption", "FilmOutOfSpecPoint"} <= set(schemas)
    props = set(schemas["FilmOverviewBox"]["properties"]) | set(
        schemas["FilmOverviewOut"]["properties"])
    assert not {p for p in props if re.search(r"pass|ribbon|rate|_count$", p)} - {"vehicle_count"}
    importers = sorted(
        str(path.relative_to(REPO)).replace("\\", "/")
        for path in (REPO / "backend/app").rglob("*.py")
        if re.search(r"\bimport +grading\b|\bfrom +\.?grading\b|domain\.grading\b",
                     path.read_text(encoding="utf-8"))
        and path.name != "grading.py"
    )
    # T105: IMG imports only orientation_of (canonical H/V), never a status.
    assert importers == [
        "backend/app/domain/img_overview.py",
        "backend/app/services/film_overview.py",
        "backend/app/services/img_overview.py",
        # Monthly Detail: owner-requested status of one point's monthly mean,
        # Overview's own rules; no per-reading grade, no pass rate -- D1 stays
        # open (docs/tasks/MONTHLY-DETAIL-inspection.md).
        "backend/app/services/monthly_detail.py",
        "backend/app/services/overview.py",
    ]
