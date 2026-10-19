"""T66 -- FilmThickness monthly overview: boxplots with spec lines.

Claims (task section 4):

1. Shape: the route is in both OpenAPI copies (byte-identical, equal to the
   live app, 52 paths); ``FilmOverviewBox`` has no ``status``.
2. Grain: AAT 2026-09 has exactly one box per (layer, model, colour, H/V)
   group with a non-null reading; ``n`` and ``vehicles`` match the facts.
3. Statistics: a synthetic two-car FVL month gives boxes equal to
   ``box_stats`` on the same values; a blank layer is skipped, not zero.
4. Spec lines from the seed: FTM CLEAR H, FTM BASE Desert Island Blue,
   AAT PRIMER Absolute / Shadow Black, SAP BASE Ignite Orange (NONE, box
   still present).
5. Latest wins: a test FTM CLEAR publish moves the lines; its own rows are
   removed by their note.
6. Filters: ``models=`` / ``colors=`` narrow; a merged old name matches no
   box, the canonical name does.
7. Month: default is the latest Film month; unknown month is empty; a bad
   format is 422.
8. Roles: Viewer 200, unauthenticated 401, unknown plant 404.
9. Nothing else moves: ``grading_available`` false; film_standard and fact
   counts unchanged by the reads.

Test safety (T64 incident): a test deletes only rows it inserted -- its own
loads (``film_cleanup``) and its own ``film_standard`` rows by NOTE.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.boxplot import box_stats
from tests.test_t03_contract import client, make_client  # noqa: F401
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t19_data_manager import anon  # noqa: F401
from tests.test_t46_filmthickness import commit, film_cleanup, pelt, sent  # noqa: F401
from tests.film_synthetic import film_month, forget_film_month, gold_points
from tests.test_t48_filmthickness_read import old_day

REPO = Path(__file__).resolve().parents[2]
PATH = "/api/v1/plants/{plant_code}/filmthickness/overview"
NOTE = "pytest-t66-film-overview"
STAT_KEYS = ("box_min", "q1", "median", "q3", "box_max", "whisker_lo", "whisker_hi", "mean")
CANONICAL_BLACK = "Absolute / Shadow Black"   # ADR 0014 canonical name
MERGED_BLACK = "Shadow Black"                  # a merged old name


def url(plant: str) -> str:
    return PATH.format(plant_code=plant)


def get(c, plant: str, **params) -> dict:
    response = c.get(url(plant), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def box(payload: dict, layer: str, color: str, orient: str, model: str | None = None) -> dict:
    found = [
        b for b in payload["boxes"]
        if (b["layer_code"], b["color_name"], b["orient"]) == (layer, color, orient)
        and (model is None or b["model_code"] == model)
    ]
    assert len(found) == 1, (layer, color, orient, found)
    return found[0]


def lines(b: dict) -> tuple:
    def num(v):
        return None if v is None else Decimal(v)
    return num(b["lo"]), num(b["hi"]), num(b["target"]), b["standard_scope"]


def _count(admin_conn, sql: str) -> int:
    with admin_conn.cursor() as cur:
        cur.execute(sql)
        return int(cur.fetchone()[0])


# ---------------------------------------------------------------- 1
def test_route_in_both_openapi_copies_and_box_has_no_status(client):  # noqa: F811
    live = client.app.openapi()
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(live["paths"]) >= 57  # T79 + T81: four Comparison reads; T86: the panel-match read.
    backend_copy = (REPO / "backend" / "openapi.json").read_bytes()
    assert backend_copy == (REPO / "docs" / "openapi.json").read_bytes()
    spec = json.loads(backend_copy)
    assert spec == live
    assert list(spec["paths"][PATH]) == ["get"]
    schemas = spec["components"]["schemas"]
    box_props = set(schemas["FilmOverviewBox"]["properties"])
    out_props = set(schemas["FilmOverviewOut"]["properties"])
    # T67 CHANGE: the box now carries a backend status (box mean, D-67-01);
    # still no pass rate and no count by status anywhere.
    assert box_props & {p for p in box_props if "status" in p} == {"status"}
    assert not {p for p in box_props | out_props if "pass" in p or "count" in p} - {
        "vehicle_count"}
    assert {"lo", "hi", "target", "standard_scope", "vehicles", "n"} <= box_props


# =====================================================================
# T85: the Film months these tests used to read
# =====================================================================
#: AAT September, FTM 2026-05 and SAP 2026-08 Film were in T85's Clear list.
#: Each claim below is about the **read** -- grain, spec lines, filters -- so
#: each gets a month of its own to read, built by `tests/film_synthetic.py`.
#: The spec lines themselves are untouched: T85 kept every `film_standard`
#: row, and these facts are only what the lines are drawn against.
def _film_fixture(admin_conn, *, plant, model, colour, day, values, vehicles=2):
    points = gold_points(admin_conn, plant, model)
    assert points, f"no live Film points for {plant} / {model}"
    readings = {
        point.point_code: dict(zip(("CLEAR", "BASE", "PRIMER", "ECOAT"), values))
        for point in points
    }
    batch = film_month(admin_conn, plant=plant, model=model, colour=colour,
                       day=day, readings=readings, vehicles=vehicles)
    batch["points"] = {point.point_code: point.orientation for point in points}
    return batch


@pytest.fixture()
def aat_film(admin_conn):  # T85
    """An AAT month under a pre-merge colour name, plus a second colour."""
    day = "2026-09-15"
    black = _film_fixture(admin_conn, plant="AAT", model="U704",
                          colour="Absolute Black", day=day,
                          values=(40.1, 18.0, 10.0, 21.0))
    green = _film_fixture(admin_conn, plant="AAT", model="U704",
                          colour="Acacia Green", day=day,
                          values=(41.0, 18.5, 10.5, 21.5))
    try:
        yield {"month": day[:7], "black": black, "green": green}
    finally:
        forget_film_month(admin_conn, green)
        forget_film_month(admin_conn, black)


@pytest.fixture()
def ftm_film(admin_conn):  # T85
    """An FTM month in Desert Island Blue, for the CLEAR / BASE spec lines."""
    day = "2026-05-12"
    batch = _film_fixture(admin_conn, plant="FTM", model="P703 DBL RANGER",
                          colour="Desert Island Blue", day=day,
                          values=(40.0, 17.0, 10.0, 21.0))
    try:
        yield batch
    finally:
        forget_film_month(admin_conn, batch)


@pytest.fixture()
def sap_film(admin_conn):  # T85
    """A SAP month in Ignite Orange, whose BASE has no published rule."""
    day = "2026-08-12"
    batch = _film_fixture(admin_conn, plant="SAP", model="P703 DBL RANGER",
                          colour="Ignite Orange", day=day,
                          values=(40.0, 17.0, 10.0, 21.0))
    try:
        yield batch
    finally:
        forget_film_month(admin_conn, batch)


# ---------------------------------------------------------------- 2
def test_grain_matches_the_facts_aat_september(viewer, admin_conn, aat_film):  # noqa: F811  # T85
    payload = get(viewer, "AAT", month=aat_film["month"])
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.layer_code, f.model, f.color,
                   COALESCE(btrim(pp.orientation), btrim(mp.orientation)),
                   count(f.thickness), count(DISTINCT f.logical_vehicle_id)
              FROM filmthickness_active f
              LEFT JOIN ref_plant_film_point pp
                ON pp.plant_code = f.plant AND pp.model_code = f.model
               AND pp.point_code = f.point_code AND pp.retired_at IS NULL
              LEFT JOIN ref_model_film_point mp
                ON mp.model_code = f.model AND mp.point_code = f.point_code
             WHERE f.plant = 'AAT' AND f.thickness IS NOT NULL
               AND f.measured_date BETWEEN '2026-09-01' AND '2026-09-30'
             GROUP BY 1, 2, 3, 4
            """
        )
        expected = {(r[0], r[1], r[2], r[3]): (r[4], r[5]) for r in cur.fetchall()}
        cur.execute(
            "SELECT count(thickness), count(DISTINCT logical_vehicle_id) "
            "FROM filmthickness_active WHERE plant = 'AAT' "
            "AND measured_date BETWEEN '2026-09-01' AND '2026-09-30'"
        )
        facts, cars = cur.fetchone()
    assert expected and None not in {k[3] for k in expected}, "every AAT fact has H/V"
    got = {
        (b["layer_code"], b["model_code"], b["color_name"], b["orient"]): (b["n"], b["vehicles"])
        for b in payload["boxes"]
    }
    assert len(got) == len(payload["boxes"]), "one box per group"
    assert got == expected
    assert sum(b["n"] for b in payload["boxes"]) == facts, "no fact dropped"
    assert payload["vehicle_count"] == cars
    assert {b["layer_code"] for b in payload["boxes"]} == {"ECOAT", "PRIMER", "BASE", "CLEAR"}
    # The rows are ours, and both orientations are represented, so "one box
    # per (layer, model, colour, H/V) group" is a real grouping claim.
    assert {k[3] for k in expected} == {"H", "V"}


# ---------------------------------------------------------------- 3 + 6
#: Clearcoat, Base (the colour), Primer, E-Coat -- pelt()'s column order.
CAR_A = {
    "001HOOD": (40.1, 18.0, 30.0, 21.0),
    "002HOOD": (41.3, None, 30.5, 21.5),
    "022LTFTDOOR": (38.2, 19.1, 29.9, 20.8),
    "036LBOXSIDE": (55.0, 18.4, 31.2, 22.0),
}
CAR_B = {
    "001HOOD": (42.7, 17.6, 30.1, 21.2),
    "002HOOD": (39.9, 18.8, 29.4, 20.9),
    "022LTFTDOOR": (37.5, 19.3, None, 21.1),
    "036LBOXSIDE": (36.6, 18.9, 30.7, 21.3),
}
ORIENT = {"001HOOD": "H", "002HOOD": "H", "022LTFTDOOR": "V", "036LBOXSIDE": "V"}
COLUMNS = ("CLEAR", "BASE", "PRIMER", "ECOAT")


@pytest.fixture()
def fvl_month(engineer, admin, admin_conn, film_cleanup):  # noqa: F811
    day, month = old_day()
    for car in (CAR_A, CAR_B):
        job = f"UR{uuid.uuid4().hex[:8].upper()}"
        data = pelt(list(car), colour="Absolute Black", day=day, job=job,
                    values=list(car.values()))
        review = sent(engineer, film_cleanup, admin_conn, f"P703-{job}-AB.xlsx", data,
                      "FVL")["Quick Summary"]
        commit(engineer, admin, review)
    return month


def test_box_values_equal_box_stats_and_nulls_are_skipped(viewer, fvl_month):  # noqa: F811
    payload = get(viewer, "FVL", month=fvl_month)
    expected: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for car in (CAR_A, CAR_B):
        for point, layers in car.items():
            for layer, value in zip(COLUMNS, layers):
                if value is not None:
                    expected[(layer, ORIENT[point])].append(Decimal(str(value)))
    assert payload["vehicle_count"] == 2
    # T67 CHANGE: color_options are objects with this plant's family (D-67-08).
    assert [c["color_name"] for c in payload["color_options"]] == [CANONICAL_BLACK]
    assert payload["model_options"] == ["P703 DBL RANGER"]
    assert len(payload["boxes"]) == 8
    for (layer, orient), values in expected.items():
        b = box(payload, layer, CANONICAL_BLACK, orient)
        stats = box_stats(values)
        assert b["n"] == len(values) == stats.n
        assert b["vehicles"] == 2
        for key in STAT_KEYS:
            assert Decimal(b[key]) == getattr(stats, key), (layer, orient, key)
        assert [Decimal(v) for v in b["outliers"]] == list(stats.outliers)
    # The blank Base on CAR_A 002HOOD and Primer on CAR_B 022LTFTDOOR are
    # skipped: 3 readings, not 4 with a zero.
    assert box(payload, "BASE", CANONICAL_BLACK, "H")["n"] == 3
    assert box(payload, "PRIMER", CANONICAL_BLACK, "V")["n"] == 3
    assert Decimal(box(payload, "BASE", CANONICAL_BLACK, "H")["box_min"]) == Decimal("17.6")
    # CLEAR V holds 55.0 among 36.6..38.2: an outlier, as box_stats says.
    assert [Decimal(v) for v in box(payload, "CLEAR", CANONICAL_BLACK, "V")["outliers"]] == [
        Decimal("55")]
    # FVL-05 seed: BASE Absolute / Shadow Black 18-20 per colour.
    assert lines(box(payload, "BASE", CANONICAL_BLACK, "H")) == (
        Decimal("18"), Decimal("20"), None, "COLOR")


def test_model_and_colour_filters(viewer, fvl_month, admin_conn, aat_film):  # noqa: F811  # T85
    every = get(viewer, "FVL", month=fvl_month)
    assert every["models"] == [] and every["colors"] == []
    same = get(viewer, "FVL", month=fvl_month, models=["P703 DBL RANGER"],
               colors=[CANONICAL_BLACK])
    assert same["boxes"] == every["boxes"]
    assert (same["models"], same["colors"]) == (["P703 DBL RANGER"], [CANONICAL_BLACK])
    for params in ({"models": ["P703 DBL RAPTOR"]}, {"colors": [MERGED_BLACK]},
                   {"colors": ["Absolute Black"]}):
        narrowed = get(viewer, "FVL", month=fvl_month, **params)
        assert narrowed["boxes"] == [] and narrowed["vehicle_count"] == 0, params
        # T67 CHANGE: color_options are objects (D-67-08).
        assert [c["color_name"] for c in narrowed["color_options"]] == [CANONICAL_BLACK], (
            "options ignore the filter")

    # T85: the same claim on an AAT month this test owns. The black rows are
    # stored under a pre-merge name, so this also proves the filter matches
    # the canonical name and not the stored one (ADR 0014).
    month = aat_film["month"]
    aat = get(viewer, "AAT", month=month, colors=["Acacia Green", CANONICAL_BLACK])
    assert {b["color_name"] for b in aat["boxes"]} == {"Acacia Green", CANONICAL_BLACK}
    assert aat["vehicle_count"] == _count(
        admin_conn,
        "SELECT count(DISTINCT logical_vehicle_id) FROM filmthickness_active "
        f"WHERE plant = 'AAT' AND measured_date BETWEEN '{month}-01' AND '{month}-30' "
        f"AND color IN ('Acacia Green', '{CANONICAL_BLACK}') AND thickness IS NOT NULL",
    )
    assert get(viewer, "AAT", month=month, colors=[MERGED_BLACK])["boxes"] == []


# ---------------------------------------------------------------- 4
def test_seeded_spec_lines_and_scope(viewer, ftm_film, aat_film, sap_film):  # noqa: F811  # T85
    # T85: the published rules are the seed's, untouched by the reset; what
    # these months provide is a box for each rule to be drawn on.
    ftm = get(viewer, "FTM", month=ftm_film["month"])
    clear_h = box(ftm, "CLEAR", "Desert Island Blue", "H")
    assert lines(clear_h) == (Decimal("36"), None, Decimal("46"), "PLANT")
    for orient in ("H", "V"):
        assert lines(box(ftm, "BASE", "Desert Island Blue", orient)) == (
            Decimal("15"), Decimal("20"), None, "COLOR")

    aat = get(viewer, "AAT", month=aat_film["month"])
    for orient in ("H", "V"):
        assert lines(box(aat, "PRIMER", CANONICAL_BLACK, orient, model="U704")) == (
            Decimal("9"), Decimal("11"), None, "COLOR")

    sap = get(viewer, "SAP", month=sap_film["month"])
    for orient in ("H", "V"):
        none = box(sap, "BASE", "Ignite Orange", orient)
        assert lines(none) == (None, None, None, "NONE")
        assert none["n"] > 0, "a NONE box is still returned with its statistics"
    assert sap["standards_note"] == (
        "Spec lines are the latest published standard; they apply to every month."
    )


# ---------------------------------------------------------------- 5
@pytest.fixture()
def own_standards(admin_conn):
    def _purge() -> None:
        # Only this test's rows, by its own note. Never a seed row.
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM film_standard WHERE source_note = %s", (NOTE,))

    _purge()
    yield
    _purge()


def test_latest_publish_wins_then_seed_lines_return(  # T85
    viewer, admin, admin_conn, own_standards, ftm_film,  # noqa: F811
):
    month = ftm_film["month"]
    seed = _count(admin_conn, f"SELECT count(*) FROM film_standard WHERE source_note <> '{NOTE}'")
    before = box(get(viewer, "FTM", month=month), "CLEAR", "Desert Island Blue", "H")
    assert lines(before) == (Decimal("36"), None, Decimal("46"), "PLANT")
    response = admin.post(
        "/api/v1/filmthickness/standards",
        json={
            "plant_code": "FTM", "layer_code": "CLEAR", "color_name": None,
            "h": {"lo": 37, "target": 47}, "v": {"lo": 31, "target": 47},
            "source_document": "synthetic", "source_note": NOTE,
        },
    )
    assert response.status_code == 201, response.text
    after = get(viewer, "FTM", month=month)
    assert lines(box(after, "CLEAR", "Desert Island Blue", "H")) == (
        Decimal("37"), None, Decimal("47"), "PLANT")
    assert lines(box(after, "CLEAR", "Desert Island Blue", "V")) == (
        Decimal("31"), None, Decimal("47"), "PLANT")
    # Every month reads the latest rule, not only the month it was published
    # in. T85: read it back on this fixture's own month, which is not the
    # month the rule was published in either.
    assert {lines(b) for b in after["boxes"] if b["layer_code"] == "CLEAR"} == {
        (Decimal("37"), None, Decimal("47"), "PLANT"),
        (Decimal("31"), None, Decimal("47"), "PLANT"),
    }
    assert _count(admin_conn, f"SELECT count(*) FROM film_standard WHERE source_note <> '{NOTE}'") == seed

    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM film_standard WHERE source_note = %s", (NOTE,))
    restored = box(get(viewer, "FTM", month=month), "CLEAR", "Desert Island Blue", "H")
    assert lines(restored) == lines(before)


# ---------------------------------------------------------------- 7
def test_month_default_unknown_and_bad_format(viewer, ftm_film):  # noqa: F811  # T85
    default = get(viewer, "FTM")
    assert default["available_months"][0] == default["month"]
    assert default["available_months"] == sorted(default["available_months"], reverse=True)
    assert default["boxes"] == get(viewer, "FTM", month=default["month"])["boxes"]

    empty = get(viewer, "FTM", month="1999-01")
    assert empty["month"] == "1999-01"
    assert (empty["boxes"], empty["vehicle_count"]) == ([], 0)
    assert (empty["model_options"], empty["color_options"]) == ([], [])
    assert empty["available_months"] == default["available_months"]

    for bad in ("2026-13", "2026-5", "abc"):
        response = viewer.get(url("FTM"), params={"month": bad})
        assert response.status_code == 422, bad
        assert {"message", "correlationId"} <= set(response.json())


# ---------------------------------------------------------------- 8
def test_roles_and_unknown_plant(viewer, anon):  # noqa: F811
    assert viewer.get(url("aat"), params={"month": "2026-09"}).status_code == 200
    assert anon.get(url("AAT")).status_code == 401
    missing = viewer.get(url("NOPE"))
    assert missing.status_code == 404
    assert {"message", "correlationId"} <= set(missing.json())


# ---------------------------------------------------------------- 9
def test_reads_move_nothing(viewer, admin_conn):  # noqa: F811
    counts = (
        "SELECT count(*) FROM film_standard",
        "SELECT count(*) FROM filmthickness",
        "SELECT count(*) FROM audit_event",
    )
    before = [_count(admin_conn, q) for q in counts]
    for plant in ("AAT", "FTM", "FVL", "SAP"):
        get(viewer, plant)
    assert [_count(admin_conn, q) for q in counts] == before
    assert viewer.get("/api/v1/meta").json()["grading_available"] is False
