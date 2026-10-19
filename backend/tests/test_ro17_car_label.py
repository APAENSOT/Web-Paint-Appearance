"""RO17 -- same-day cars told apart (D-RO17-17) and Comparison's raw Wave
Scan label (D-RO17-16).

Claims:

* A Wave Scan car with a ``car_key`` carries ``car_label`` "car n of m that
  day · from row r": n by the car's first source row among the cars of its
  (load, date, model, colour), m how many. A serial car, a Film car and a
  car without a key carry null. History and the review say the same.
* A Wave Scan Comparison reading and trace carry ``src_zone_text``, the
  plant's own label of that reading.

Synthetic only: the pure tests build rows in memory; the DB test reuses
T79's ``data`` fixture, whose writes are one transaction that is rolled back
(no worker, no commit, no residue).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

from sqlalchemy import text

from app.domain.workbooks import car_labels, group_vehicle_sets
from app.services import history as history_service
from app.services import workbooks as workbooks_service
from tests.test_t79_comparison import MODEL, data, get, ok  # noqa: F401

DAY = date(2002, 7, 10)  # week 2; T79's own cars are on other days


def key(n: int) -> str:
    return hashlib.sha256(f"ro17-{n}".encode()).hexdigest()[:16]


def expected(firsts: list[int]) -> list[str]:
    return [f"car {n} of {len(firsts)} that day · from row {r}"
            for n, r in enumerate(firsts, 1)]


# =====================================================================
# pure rules
# =====================================================================
def test_the_ordinal_is_by_first_source_row_within_one_day():
    day, other = (1, DAY, MODEL, "White"), (2, DAY, MODEL, "White")
    labels = car_labels([("c", day, 66), ("a", day, 2), ("e", day, 130),
                         ("b", day, 34), ("d", day, 98), ("x", other, 5)])
    assert [labels[c] for c in "abcde"] == expected([2, 34, 66, 98, 130])
    assert labels["x"] == "car 1 of 1 that day · from row 5"
    assert car_labels([]) == {}


def _row(source_row, *, car_key=None, serial=None, color="White", zone="1HOOD", **extra):
    return {"source_row": source_row, "disposition": "LOAD", "canonical": {
        "measured_date": DAY.isoformat(), "model": MODEL, "color": color,
        "serial_no": serial, "checkzone": zone, "point_code": zone,
        "car_key": car_key, **extra}}


def test_the_review_labels_keyed_cars_only():
    # Five keyed cars, keys deliberately not in row order; one serial car.
    rows = [_row(2 + 32 * i + j, car_key=key(4 - i)) for i in range(5) for j in range(2)]
    rows += [_row(200, serial="S1"), _row(201, serial="S1")]
    sets = group_vehicle_sets(7, rows, {})
    keyed = [s for s in sets if s.serial_no is None]
    # RO17-FIX (D-RO17F-4): listed in car order, not by id.
    assert [s.car_label for s in keyed] == expected([2, 34, 66, 98, 130])
    [serial] = [s for s in sets if s.serial_no == "S1"]
    assert serial.car_label is None
    # One car without a key (today's blank-serial sheet): null.
    [single] = group_vehicle_sets(7, [_row(2), _row(3)], {})
    assert single.car_label is None
    # Film: a logical_vehicle_id car is never labelled.
    film = group_vehicle_sets(
        7, [_row(2, logical_vehicle_id="v1"), _row(3, logical_vehicle_id="v2")], {},
        film=lambda model, zones: (len(zones), None, False),
    )
    assert [s.car_label for s in film] == [None, None]


# =====================================================================
# History, the review and Comparison on one rolled-back synthetic sheet
# =====================================================================
def test_history_review_and_comparison(data):  # noqa: F811
    conn, plant = data["conn"], data["plant"]
    conn.execute(text("RESET ROLE"))
    file_hash = uuid.uuid4().hex * 2
    load = conn.execute(text(
        "INSERT INTO load_batch (source_file, source_sheet, plant_code, file_hash, "
        "raw_store_key, status, domain) VALUES ('ro17.xlsx', 'Synthetic', :p, :h, "
        "'unused', 'COMMITTED', 'WAVESCAN') RETURNING load_id"),
        {"p": plant, "h": file_hash}).scalar_one()
    cars = [(key(4 - i), None, 2 + 32 * i) for i in range(5)] + [(None, "RO17-S", 200)]
    for car_key, serial, first in cars:
        for j in range(2):
            conn.execute(text(
                "INSERT INTO wavescan (measured_date, plant, model, color, serial_no, "
                "checkzone, tolerance_group, cf, load_id, source_sheet, source_row, "
                "src_zone_text, car_key) VALUES (:d, :p, :m, 'Arctic White', :s, '1HOOD', "
                "'Horizontal', 50, :l, 'Synthetic', :r, :raw, :k)"),
                {"d": DAY, "p": plant, "m": MODEL, "s": serial, "l": load,
                 "r": first + j, "raw": f"plant hood {first}", "k": car_key})
    conn.execute(text("SET LOCAL ROLE app_rw"))
    firsts = expected([2, 34, 66, 98, 130])

    found, total = history_service.vehicles(
        conn, plant, plant_scope=None, month="2002-07", week=2, model=MODEL,
        color="Arctic White", limit=50, offset=0)
    assert total == 6
    by_row = [v for v in found if v.car_key]
    # RO17-FIX (D-RO17F-4): History lists them in car order, not by id.
    assert [v.car_label for v in by_row] == firsts
    assert [v.car_label for v in found if v.serial_no] == [None]

    sets, _ = workbooks_service.vehicles(conn, plant, file_hash, load_id=load,
                                         limit=50, offset=0)
    review = {s.vehicle_id: s.car_label for s in sets}
    assert review == {v.vehicle_id: v.car_label for v in found}
    assert [s.car_label for s in sets if s.car_label] == firsts, "review: car order"

    # D-RO17-16: a Wave Scan reading carries the plant's own label.
    picker = ok(get(data, model=MODEL, month="2002-07"))
    vid = by_row[0].vehicle_id
    assert vid in {v["vehicle_id"] for v in picker["items"]}
    assert all("car_label" not in v for v in picker["items"])
    body = ok(get(data, "points", model=MODEL, metric="cf", vehicle_id=[vid]))
    readings = [r for p in body["locations"] for c in p["cells"] for r in c["readings"]]
    assert readings and {r["src_zone_text"] for r in readings} == {"plant hood 2"}
    assert all(r["src_location_text"] is None for r in readings)
    visual = ok(data["client"].get(
        f"/api/v1/plants/{plant}/comparison/vehicle-visuals",
        params={"model": MODEL, "vehicle_id": [vid]}))["vehicles"][0]
    traces = [t for p in visual["locations"] for t in p["traces"]]
    assert traces and {t["src_zone_text"] for t in traces} == {"plant hood 2"}
