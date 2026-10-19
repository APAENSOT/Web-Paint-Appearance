"""RO11 -- a Film file's review shows its cars as Film cars; a limit row is not a car.

Claims (task section 3, steps 4):

1. **A limit row is never a vehicle set** (D-RO11-2). `domain.workbooks.set_key`
   is the one rule: it drops `AGGREGATE_ROW` for the vehicles read and for the
   inbox card's count alike.
2. **A Film sheet's sets are Film cars** (D-RO11-3, D-RO11-4): keyed by
   `logical_vehicle_id`, counted on `point_code` against the plant's live
   Film list, and judged by History's own complete-stop rule.
3. **Through the running application** (synthetic FTM PELT walks, uploaded by
   the real uploader): `/rows` unfiltered is 200 with the limit rows held out,
   `/vehicles` is one complete set, `/points` is the walk in `point_no` order
   with its layers, and the card counts one set. A walk that stops at a
   complete stop reads complete in the review **and** in History.
4. **Wave Scan is unchanged**: its key and its `vehicle_id` are what they were.

The parser writes one Job Number per sheet (it is read from the sheet header),
so two cars that differ only by Job Number cannot be put on one sheet through
the uploader; claim 2's two-car case is the rule itself, which both reads use.

**What this file writes:** only synthetic uploads, through `film_cleanup`,
which deletes those batches and their facts by `load_id`. No reference row.
"""

from __future__ import annotations

import pytest

from app.domain.workbooks import AGGREGATE_ROW, group_vehicle_sets, set_key, vehicle_id
from app.services.workbooks import _film_count
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import commit, film_cleanup, film_facts, pelt, sent  # noqa: F401
from tests.test_t99_film_point_lists import COLOUR, PLANT, RANGER, RAPCAP, TAIL, job_name, walk_of


def ws(file_hash: str, tail: str) -> str:
    return f"/api/v1/plants/{PLANT}/workbooks/{file_hash}{tail}"


def film_row(source_row: int, code: str, car: str, *, disposition: str = "LOAD") -> dict:
    return {
        "source_row": source_row,
        "disposition": disposition,
        "canonical": {
            "measured_date": "2026-08-20", "model": "M", "color": "C", "serial_no": None,
            "point_code": code, "logical_vehicle_id": car,
            "layers": {"ECOAT": "20.1", "PRIMER": "10.2", "BASE": "15.3", "CLEAR": "38.4"},
        },
    }


LIMIT_ROW = {
    "source_row": 99,
    "disposition": AGGREGATE_ROW,
    "canonical": {"plant": "AAT", "aggregate_fields": ["location"]},
}


# =====================================================================
# 1 + 2 + 4. the rule (pure)
# =====================================================================
def test_a_limit_row_has_no_key_and_wave_scan_keys_are_unchanged():
    assert set_key(AGGREGATE_ROW, LIMIT_ROW["canonical"]) is None
    wave = {"measured_date": "2026-08-20", "model": "U704", "color": "C", "serial_no": "7"}
    assert set_key("LOAD", wave) == ("2026-08-20", "U704", "C", "7", None)
    # The card reads flat rows; the same rule answers the same key.
    assert set_key("LOAD", {**wave, "logical_vehicle_id": None}) == set_key("LOAD", wave)
    [only] = group_vehicle_sets(5, [{"source_row": 1, "disposition": "LOAD",
                                     "canonical": {**wave, "checkzone": "Z1"}}], {"U704": 1})
    assert only.vehicle_id == vehicle_id(5, ("2026-08-20", "U704", "C", "7")), \
        "a Wave Scan vehicle_id is the T21 hash, unchanged"


def test_a_film_sheet_groups_by_car_and_never_makes_a_limit_row_a_set():
    walk = {"P1": 1, "P2": 2, "P3": 3}
    rows = [film_row(1, "P1", "car-a"), film_row(2, "P2", "car-a"), film_row(3, "P3", "car-a"),
            film_row(4, "P1", "car-b"), LIMIT_ROW]
    sets = group_vehicle_sets(7, rows, {}, {}, film=_film_count({"M": (walk, [])}))
    assert len(sets) == 2, "two cars that differ only by Job Number are two sets"
    by_rows = {tuple(s.source_rows): s for s in sets}
    a, b = by_rows[(1, 2, 3)], by_rows[(4,)]
    assert (a.point_count, a.expected_point_count, a.incomplete_set) == (3, 3, False)
    assert (b.point_count, b.expected_point_count, b.incomplete_set) == (1, 3, True)
    assert a.vehicle_id != b.vehicle_id and len(a.vehicle_id) == 64
    assert 99 not in a.source_rows + b.source_rows


@pytest.mark.parametrize("codes, stops, expected", [
    ({"P1", "P2"}, [2], (2, 2, False)),        # walked to a stop with no gap: complete
    ({"P1", "P3"}, [3], (2, 4, True)),         # a gap before the stop: the whole list
    ({"P1", "P2", "P3", "P4"}, [2], (4, 4, False)),
    ({"P1", "X9"}, [], (1, 4, True)),          # a code off the list counts neither way
])
def test_film_counts_follow_historys_rule(codes, stops, expected):
    walk = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
    assert _film_count({"M": (walk, stops)})("M", codes) == expected


def test_a_model_with_no_live_list_is_incomplete_as_in_history():
    assert _film_count({})("M", {"P1", "P2"}) == (2, None, True)
    assert _film_count({"M": ({"P1": 1}, [])})(None, {"P1"}) == (1, None, True)


# =====================================================================
# 3. through the running application
# =====================================================================
def test_a_film_tab_with_a_car_and_limit_rows_reads_as_one_film_car(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, RAPCAP)
    name, job = job_name("RAP")
    review = sent(engineer, film_cleanup, admin_conn, name,
                  pelt([*walk, *TAIL], colour=COLOUR, job=job), PLANT)["Quick Summary"]
    load_id, file_hash = review["batch"]["load_id"], review["batch"]["file_hash"]

    rows = admin.get(ws(file_hash, "/rows"), params={"load_id": load_id, "limit": 500})
    assert rows.status_code == 200, rows.text
    held = [r for r in rows.json()["items"] if r["disposition"] == AGGREGATE_ROW]
    assert len(held) == len(TAIL), "the limit rows stay in /rows, held out"
    only = admin.get(ws(file_hash, "/rows"),
                     params={"load_id": load_id, "disposition": AGGREGATE_ROW})
    assert only.status_code == 200 and only.json()["page"]["total"] == len(TAIL), only.text

    page = admin.get(ws(file_hash, "/vehicles"), params={"load_id": load_id})
    assert page.status_code == 200, page.text
    [car] = page.json()["items"]
    assert (car["model"], car["point_count"], car["expected_point_count"],
            car["incomplete_set"], car["identity_complete"]) == (
        RAPCAP, len(walk), len(walk), False, True)

    points = admin.get(ws(file_hash, f"/vehicles/{car['vehicle_id']}/points"),
                       params={"limit": 500})
    assert points.status_code == 200, points.text
    items = points.json()["items"]
    assert [p["checkzone"] for p in items] == walk, "the plant's walk order (point_no)"
    assert all(set(p["proposed"]["layers"]) >= {"ECOAT", "PRIMER", "BASE", "CLEAR"}
               for p in items)

    workbook = admin.get(ws(file_hash, "")).json()["workbook"]
    assert workbook["vehicle_set_count"] == 1, "the card counts the car, not the limit rows"


@pytest.mark.parametrize("model, token, stop, complete", [
    (RAPCAP, "RAP", "059RTFEND", True),
    (RANGER, "DBL", "063RAPILLAR", False),
])
def test_a_walk_that_stops_reads_the_same_in_the_review_and_in_history(
    engineer, admin, viewer, admin_conn, film_cleanup, model, token, stop, complete  # noqa: F811
):
    walk = walk_of(admin_conn, model)
    cut = walk[: walk.index(stop) + 1]
    name, job = job_name(token)
    review = sent(engineer, film_cleanup, admin_conn, name,
                  pelt([*cut, *TAIL], colour=COLOUR, job=job), PLANT)["Quick Summary"]
    load_id, file_hash = review["batch"]["load_id"], review["batch"]["file_hash"]
    [car] = admin.get(ws(file_hash, "/vehicles"), params={"load_id": load_id}).json()["items"]
    assert car["incomplete_set"] is not complete
    assert car["expected_point_count"] == (len(cut) if complete else len(walk))

    commit(engineer, admin, review)
    [vid] = {f[6] for f in film_facts(admin_conn, load_id)}
    history = viewer.get(f"/api/v1/plants/{PLANT}/filmthickness/vehicles/{vid}/points").json()
    assert (car["point_count"], car["expected_point_count"], car["incomplete_set"]) == (
        history["vehicle"]["mapped_point_count"],
        history["vehicle"]["expected_point_count"],
        history["vehicle"]["incomplete"],
    ), "the review's car is History's car"
    [after] = admin.get(ws(file_hash, "/vehicles"), params={"load_id": load_id}).json()["items"]
    assert after == car, "committing does not change the review's car"
