"""T48 -- FilmThickness read API: facets, vehicles, the gold point grid.

Claims (task "Tests"):

1. An FVL commit of 4 gold points reads back as the whole 94-point
   catalogue: 4 with layers, 90 null; ``001HOOD`` is ``H``, a door is ``V``.
2. T54 CHANGE: FTM ``_RB_`` reads FTM's own 94 (Desert Island Blue QS).
   ``029LTFTDOOR`` and ``021LAPILLAR`` sit on their own FTM slots; there is
   no FVL ``021LTFEND`` / ``022LTFTDOOR`` slot in an FTM grid.
3. FTM extras ``095RBXFLOOR`` / ``001FTWISH`` are nowhere in the grid.
4. Two loads of one ``logical_vehicle_id`` (blank identity) are one vehicle:
   points unioned, two ``load_ids``.
5. ``GET /measurements`` does not count film facts.
6. Viewer 200, unauthenticated 401, unknown plant 404, bad month 422.
7. Both OpenAPI copies carry the three paths; ``grading_available`` false.

Plus (T54 CHANGE): FTM RAPCAP answers the FTM 94 with Hor/Ver; only the names
its walk has are filled, the rest stay empty.
Workbooks are synthetic; dates are in 2001-2015 so no live month is touched.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.film_catalog import FVL_GOLD_94
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t19_data_manager import anon  # noqa: F401
from tests.test_t46_filmthickness import commit, film_cleanup, film_facts, pelt, sent  # noqa: F401

pytestmark = pytest.mark.ingest

REPO = Path(__file__).resolve().parents[2]
FTM_GOLD = [p["point_code"] for p in json.loads(
    (REPO / "backend" / "tests" / "fixtures" / "gold" / "FTM-QS-film-points.json").read_text(encoding="utf-8")
)["locations"]]
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
ZERO_LAYERS = {"ecoat": None, "primer": None, "base": None, "clear": None}


def film(plant: str) -> str:
    return f"/api/v1/plants/{plant}/filmthickness"


def old_day() -> tuple[str, str]:
    """A random PELT day in 2001-2015 and its YYYY-MM."""
    n = uuid.uuid4().int
    day, month, year = n % 28 + 1, (n // 28) % 12, 1 + (n // 997) % 15
    return f"{day:02d}-{MONTHS[month]}-{year:02d}", f"20{year:02d}-{month + 1:02d}"


def ok(client, path: str, **params) -> dict:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def committed(engineer, admin, admin_conn, film_cleanup, name, data, plant) -> int:  # noqa: F811
    review = sent(engineer, film_cleanup, admin_conn, name, data, plant)["Quick Summary"]
    commit(engineer, admin, review)
    return review["batch"]["load_id"]


def vehicle_of(admin_conn, load_id: int) -> str:
    [vid] = {f[6] for f in film_facts(admin_conn, load_id)}
    return vid


def filled(grid: dict) -> dict[str, dict]:
    return {p["point_code"]: p for p in grid["items"] if p["src_location_text"] is not None}


# =====================================================================
# 1. FVL: the grid is the catalogue, not the rows
# =====================================================================
def test_fvl_four_points_read_as_the_94_gold_grid(
    engineer, admin, viewer, admin_conn, film_cleanup  # noqa: F811
):  # [1] [5]
    day, month = old_day()
    job = f"UR{uuid.uuid4().hex[:8].upper()}"
    four = ["001HOOD", "002HOOD", "022LTFTDOOR", "036LBOXSIDE"]
    load_id = committed(engineer, admin, admin_conn, film_cleanup, f"P703-{job}-AB.xlsx",
                        pelt(four, colour="Absolute Black", day=day, job=job), "FVL")
    vid = vehicle_of(admin_conn, load_id)

    facets = ok(viewer, f"{film('fvl')}/facets", month=month)
    assert facets["plant_code"] == "FVL" and month in facets["months"]
    # T64 CHANGE: "Absolute Black" is written and read as its canonical name (ADR 0014).
    assert "P703 DBL RANGER" in facets["models"] and "Absolute / Shadow Black" in facets["colors"]
    assert facets["active_data_source"] == "filmthickness_active"

    page = ok(viewer, f"{film('FVL')}/vehicles", month=month, model="P703 DBL RANGER",
              color="Absolute / Shadow Black")  # T64 CHANGE: canonical name
    [car] = [v for v in page["items"] if v["logical_vehicle_id"] == vid]
    assert (car["load_ids"], car["job_nos"], car["identity_complete"]) == ([load_id], [job], True)
    assert (car["mapped_point_count"], car["expected_point_count"], car["incomplete"]) == (4, 94, True)

    grid = ok(viewer, f"{film('FVL')}/vehicles/{vid}/points")
    assert [p["point_code"] for p in grid["items"]] == list(FVL_GOLD_94)
    assert [p["point_no"] for p in grid["items"]] == list(range(1, 95))
    assert Counter(p["orientation"] for p in grid["items"]) == {"H": 30, "V": 64}
    got = filled(grid)
    assert set(got) == set(four)
    assert got["001HOOD"]["orientation"] == "H" and got["022LTFTDOOR"]["orientation"] == "V"
    # pelt() row i: Clearcoat 40.1+i, Base 18.2, Primer 30.3, E-Coat 21.4
    assert got["002HOOD"]["layers"] == {"ecoat": "21.4", "primer": "30.3", "base": "18.2",
                                        "clear": "41.1"}
    assert {(p["load_id"], p["src_location_text"]) for p in got.values()} == {
        (load_id, p) for p in four
    }
    empty = [p for p in grid["items"] if p["point_code"] not in got]
    assert len(empty) == 90
    assert all(p["layers"] == ZERO_LAYERS and p["load_id"] is None for p in empty)

    # [5] film facts are not WaveScan measurements
    for params in ({"load_id": load_id}, {"plant": "FVL", "date_from": car["measured_date"],
                                          "date_to": car["measured_date"]}):
        listed = engineer.get("/api/v1/measurements", params={"limit": 1, **params})
        assert listed.status_code == 200, listed.text
        assert listed.json()["page"]["total"] == 0


# =====================================================================
# 2 + 3. FTM Raptor: mapped labels on gold slots, held labels nowhere
# =====================================================================
def test_ftm_raptor_mapped_labels_fill_gold_slots_and_held_labels_do_not(
    engineer, admin, viewer, admin_conn, film_cleanup  # noqa: F811
):  # [2] [3]
    day, month = old_day()
    name = f"AW_RB_{uuid.uuid4().int % 10**7:07d}.xlsx"
    # T99 CHANGE (D-99-6, D-99-7): the body labels have to be FTM's known
    # Raptor walk or a prefix of it, so this file walks the first two points
    # and then the FTWISH tail. The claim is unchanged: the loaded labels
    # fill their own gold slots, the FTWISH tail fills none, and no FVL slot
    # exists at FTM.
    walk = ["001HOOD", "002HOOD"]
    data = pelt([*walk, "001FTWISH"], colour="Arctic White", day=day, job=name[:-5])
    load_id = committed(engineer, admin, admin_conn, film_cleanup, name, data, "FTM")
    vid = vehicle_of(admin_conn, load_id)

    grid = ok(viewer, f"{film('FTM')}/vehicles/{vid}/points")
    assert grid["vehicle"]["model"] == "P703 DBL RAPTOR"
    # T99 CHANGE (D-99-5): FTM's Raptor walk is 98 -- the 94 evidence names
    # plus 095RBXFLOOR and 096-098TGATEIN.
    assert [p["point_code"] for p in grid["items"]][:94] == FTM_GOLD
    assert grid["vehicle"]["expected_point_count"] == 98
    got = filled(grid)
    assert {k: (v["src_location_text"], v["orientation"]) for k, v in got.items()} == {
        "001HOOD": ("001HOOD", "H"),
        "002HOOD": ("002HOOD", "H"),
    }
    assert all(v is not None for v in got["002HOOD"]["layers"].values())
    slots = {p["point_code"]: p for p in grid["items"]}
    assert "021LTFEND" not in slots and "022LTFTDOOR" not in slots, "no FVL slot at FTM"
    sources = {p["src_location_text"] for p in grid["items"]}
    assert not sources & {"001FTWISH"}, "the tail fills no slot (D-99-6)"
    assert (grid["vehicle"]["mapped_point_count"], grid["vehicle"]["incomplete"]) == (2, True)

    page = ok(viewer, f"{film('FTM')}/vehicles", month=month, model="P703 DBL RAPTOR")
    assert [v["mapped_point_count"] for v in page["items"] if v["logical_vehicle_id"] == vid] == [2]


def test_ftm_rapcap_reads_its_own_list_and_fills_only_what_it_has(
    engineer, admin, viewer, admin_conn, film_cleanup  # noqa: F811
):
    # T99 CHANGE (D-99-1, D-99-5): RAPCAP is its own 93-name walk, not a copy
    # of the DBL 94, and a body label must be a prefix of it. The claim is
    # unchanged: the grid is the whole of this plant x model's list, in walk
    # order, with only the walked slot filled and the rest empty -- never
    # padded, never borrowed from another model.
    day, _ = old_day()
    name = f"AW_RAP_{uuid.uuid4().int % 10**7:07d}.xlsx"
    load_id = committed(engineer, admin, admin_conn, film_cleanup, name,
                        pelt(["001HOOD"], colour="Arctic White", day=day, job=name[:-5]),
                        "FTM")
    grid = ok(viewer, f"{film('FTM')}/vehicles/{vehicle_of(admin_conn, load_id)}/points")
    assert grid["vehicle"]["model"] == "P703 RAPCAP"
    assert grid["vehicle"]["expected_point_count"] == 93
    assert len(grid["items"]) == 93
    assert [p["point_no"] for p in grid["items"]] == list(range(1, 94))
    assert all(
        p["orientation"] == ("H" if re.sub(r"^[0-9]+", "", p["point_code"]) in (
            "HOOD", "ROOF", "LBXFLOOR", "RBXFLOOR") else "V")
        for p in grid["items"]
    ), "the one D-99-5 H/V rule"
    assert set(filled(grid)) == {"001HOOD"}
    empty = [p for p in grid["items"] if p["point_code"] != "001HOOD"]
    assert all(p["layers"] == ZERO_LAYERS for p in empty), "empty slots stay empty"


# =====================================================================
# 4. Cab + Box: one logical vehicle, two loads
# =====================================================================
def test_cab_and_box_are_one_vehicle_with_two_loads(
    engineer, admin, viewer, admin_conn, film_cleanup  # noqa: F811
):  # [4]
    day, month = old_day()
    tag = uuid.uuid4().hex[:6]
    cab = pelt(["001HOOD", "002HOOD"], colour="Traction Green", day=day, job="",
               title="FORD TH- PELT Filmbuild Report", diagram=False)
    # T57 CHANGE: AAT box-side gold is its own Sep names.
    box = pelt(["059LBOXSIDE", "060LBOXSIDE"], colour="Traction Green", day=day, job="",
               title="FORD TH- PELT Filmbuild Report  ", diagram=False)
    one = committed(engineer, admin, admin_conn, film_cleanup,
                    f"Data Pelt P703 Cab {tag}.xlsx", cab, "AAT")
    two = committed(engineer, admin, admin_conn, film_cleanup,
                    f"Data Pelt P703 Box {tag}.xlsx", box, "AAT")
    vid = vehicle_of(admin_conn, one)
    assert vehicle_of(admin_conn, two) == vid and one != two

    page = ok(viewer, f"{film('AAT')}/vehicles", month=month, color="Traction Green")
    [car] = [v for v in page["items"] if v["logical_vehicle_id"] == vid]
    assert car["load_ids"] == sorted([one, two]) and len(car["source_files"]) == 2
    assert (car["mapped_point_count"], car["identity_complete"]) == (4, False)

    grid = ok(viewer, f"{film('AAT')}/vehicles/{vid}/points")
    assert {k: v["load_id"] for k, v in filled(grid).items()} == {
        "001HOOD": one, "002HOOD": one, "059LBOXSIDE": two, "060LBOXSIDE": two,
    }


# =====================================================================
# 6. access and refusals
# =====================================================================
def test_any_role_reads_and_anonymous_is_refused(viewer, engineer, admin, anon):  # noqa: F811
    for client in (viewer, engineer, admin):
        assert client.get(f"{film('AAT')}/facets").status_code == 200
    paths = (f"{film('AAT')}/facets", f"{film('AAT')}/vehicles?month=2026-07",
             f"{film('AAT')}/vehicles/{'0' * 64}/points")
    for path in paths:
        assert anon.get(path).status_code == 401, path


def test_refusals_and_empty_months(viewer):  # noqa: F811
    assert viewer.get(f"{film('NOWHERE')}/facets").status_code == 404
    assert viewer.get(f"{film('NOWHERE')}/vehicles", params={"month": "2026-07"}).status_code == 404
    assert viewer.get(f"{film('AAT')}/vehicles/{'0' * 64}/points").status_code == 404
    assert viewer.get(f"{film('AAT')}/vehicles/not-a-hash/points").status_code == 422
    for params in ({"month": "2026-13"}, {"month": "July"}, {"color": "Traction Green"}):
        assert viewer.get(f"{film('AAT')}/facets", params=params).status_code == 422, params
    assert viewer.get(f"{film('AAT')}/vehicles").status_code == 422, "month is required"
    empty = ok(viewer, f"{film('aat')}/facets", month="2000-01")
    assert (empty["plant_code"], empty["models"], empty["colors"]) == ("AAT", [], [])
    assert "2000-01" not in empty["months"]
    page = ok(viewer, f"{film('AAT')}/vehicles", month="2000-01")
    assert (page["items"], page["page"]["total"]) == ([], 0)


def test_a_plant_without_film_facts_is_an_empty_200(viewer, admin_conn):  # noqa: F811
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code FROM ref_plant p WHERE NOT EXISTS "
            "(SELECT 1 FROM filmthickness_active f WHERE f.plant = p.plant_code) "
            "ORDER BY 1 LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        pytest.skip("every plant holds film facts in this database")
    body = ok(viewer, f"{film(row[0])}/facets")
    assert (body["months"], body["default_month"]) == ([], None)


# =====================================================================
# 7. contract
# =====================================================================
FILM_PATHS = {
    "/api/v1/plants/{plant_code}/filmthickness/facets",
    "/api/v1/plants/{plant_code}/filmthickness/vehicles",
    "/api/v1/plants/{plant_code}/filmthickness/vehicles/{logical_vehicle_id}/points",
}


def test_both_openapi_copies_carry_the_three_reads(viewer):  # noqa: F811
    live = viewer.app.openapi()
    assert FILM_PATHS <= set(live["paths"])
    assert all(set(live["paths"][p]) == {"get"} for p in FILM_PATHS)
    for copy in (REPO / "backend" / "openapi.json", REPO / "docs" / "openapi.json"):
        assert json.loads(copy.read_text(encoding="utf-8")) == live, copy
    layers = live["components"]["schemas"]["FilmLayersOut"]["properties"]
    assert set(layers) == {"ecoat", "primer", "base", "clear"}
    assert "FilmPointOut" not in json.dumps(live["paths"]["/api/v1/measurements"])
    assert ok(viewer, "/api/v1/meta")["grading_available"] is False


def test_decimal_layers_cross_the_wire_as_strings():
    from app.schemas.filmthickness import FilmLayersOut

    body = FilmLayersOut(ecoat=Decimal("21.40"), primer=None, base=None, clear=None)
    assert json.loads(body.model_dump_json()) == {"ecoat": "21.40", "primer": None,
                                                  "base": None, "clear": None}
