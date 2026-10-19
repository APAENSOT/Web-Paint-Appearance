"""T114-FIX -- a Wave Scan car is complete against its plant's live list.

Claims (task section 3):

1. **The rule** (`domain.completeness`, D-114F-1 / D-114F-4): expected = the
   live, non-extra points of the plant x model list; mapped = how many of
   them the car has a reading on; a reading off the list (retired, extra,
   unknown) counts neither way; no list -> `ref_model.expected_zone_count`.
2. **Every reader applies it** -- History, Comparison's candidates, review
   vehicles, the worksheet's short vehicles and `v_car_completeness` (0038):
   * retire one point -> an old car (it has that reading) and a new car
     (it has not) are both complete on the remaining points;
   * add an extra point -> a car without it is complete, and a car with it
     is complete too (the extra is ignored);
   * a car missing a live, non-extra point is incomplete;
   * a plant x model with no live list falls back to the model count.
3. **No live car moves** (read-only): every live car reads the same against
   the list as against `ref_model.expected_zone_count`, in History,
   Comparison and the view.

**What this file writes.** Every write runs inside T114's `tx` -- one admin
transaction that is always **rolled back** -- calling the same services the
routes call. Nothing here commits.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date

import pytest
from sqlalchemy import text

from app.domain.completeness import wavescan_points
from app.domain.history import group_vehicles
from app.repositories import history as history_repo
from app.repositories import ws_points as ws_points_repo
from app.repositories.reference import load_reference_data
from app.services import comparison as comparison_service
from app.services import history as history_service
from app.services import workbooks as workbooks_service
from app.services import worksheet as worksheet_service
from tests.test_t114_point_check_wavescan import (  # noqa: F401
    MODEL,
    PLANT,
    add,
    engine,
    live_list,
    retire,
    tx,
)

pytestmark = pytest.mark.ingest

BOUNDS = (date(2099, 1, 1), date(2099, 1, 31))


# =====================================================================
# helpers
# =====================================================================
def car(conn, tag: str, zones: list[tuple[str, str]], model: str = MODEL) -> dict:
    """One committed car at FTM in 2099-01, one reading per zone. Inside `tx`."""
    digest = hashlib.sha256(f"T114FIX:{tag}:{uuid.uuid4().hex}".encode()).hexdigest()
    load_id = conn.execute(
        text(
            """
            INSERT INTO load_batch (
                source_file, source_sheet, plant_code, file_hash, status,
                rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
                rows_quarantine, raw_store_key, finished_at, notes)
            VALUES (:file, 'Sheet1', :plant, :hash, 'COMMITTED', :n, :n, 0, 0, 0,
                    :key, now(), 'T114-FIX fixture, rolled back')
            RETURNING load_id
            """
        ),
        {
            "file": f"T114FIX {tag}.xlsx", "plant": PLANT, "hash": digest,
            "n": len(zones), "key": f"wavescan/raw/{digest}",
        },
    ).scalar_one()
    serial = f"T114FIX-{tag}-{load_id}"
    for row, (zone_code, tolerance) in enumerate(zones, start=2):
        conn.execute(
            text(
                """
                INSERT INTO wavescan (
                    measured_date, plant, model, checkzone, color,
                    tolerance_group, paintline, serial_no,
                    lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
                    load_id, source_sheet, source_row)
                VALUES ('2099-01-10', :plant, :model, :zone, 'Arctic White', :tol,
                        'BOOTH1', :serial, 1, 2, 60, 80, 3, 4, 5, 6, 7, 8, 0,
                        :load, 'Sheet1', :row)
                """
            ),
            {
                "plant": PLANT, "model": model, "zone": zone_code, "tol": tolerance,
                "serial": serial, "load": load_id, "row": row,
            },
        )
        # The projection the review and the worksheet read, one LOAD row each.
        conn.execute(
            text(
                """
                INSERT INTO stg_review_row (
                    load_id, source_row, disposition, canonical, raw,
                    template_fingerprint, review_revision)
                VALUES (:load, :row, 'LOAD', CAST(:canonical AS jsonb), '{}'::jsonb,
                        'T114FIX', :revision)
                """
            ),
            {
                "load": load_id, "row": row, "revision": digest,
                "canonical": json.dumps({
                    "plant": PLANT, "model": model, "color": "Arctic White",
                    "serial_no": serial, "measured_date": "2099-01-10",
                    "checkzone": zone_code, "tolerance_group": tolerance,
                }),
            },
        )
    return {"serial": serial, "load_id": load_id, "file_hash": digest, "model": model}


def walk(conn) -> list[tuple[str, str]]:
    """The live list of the marker plant x model, as (zone, H/V)."""
    return [(p["zone_code"], p["tolerance_group"]) for p in live_list(conn)]


def states(conn, found: dict) -> dict[str, tuple]:
    """(mapped, expected, complete) of one car from every reader."""
    model = found["model"]
    history = next(
        v for v in history_service._vehicles(
            conn, PLANT, plant_scope=None, bounds=BOUNDS, model=model, color=None,
        )
        if v.serial_no == found["serial"]
    )
    candidates, _ = _comparison(conn, model)
    candidate = next(c for c in candidates if c["serial_no"] == found["serial"])
    review, _ = workbooks_service.vehicles(
        conn, PLANT, found["file_hash"], load_id=found["load_id"], limit=50, offset=0,
    )
    [review] = review
    view = conn.execute(
        text(
            "SELECT zones_recorded, zones_expected, completeness "
            "  FROM v_car_completeness WHERE plant = :p AND serial_no = :s"
        ),
        {"p": PLANT, "s": found["serial"]},
    ).one()
    return {
        "history": (history.point_count, history.expected_point_count, not history.incomplete_set),
        "comparison": (
            candidate["point_count"], candidate["expected_point_count"],
            not candidate["incomplete"],
        ),
        "review": (review.point_count, review.expected_point_count, not review.incomplete_set),
        "view": (int(view[0]), int(view[1]), view[2] == "COMPLETE"),
    }


def _comparison(conn, model: str):
    body = comparison_service.vehicles(
        conn, PLANT, plant_scope=None, domain="WAVESCAN", months=["2099-01"],
        model=model, colors=None, periods=None, q=None, limit=500, offset=0,
    )
    return body["items"], body["page"]["total"]


def every(state: tuple) -> dict[str, tuple]:
    return {reader: state for reader in ("history", "comparison", "review", "view")}


def short_vehicles(conn, found: dict) -> list[dict]:
    """The worksheet's "this vehicle has N of M panels" list for the car's file."""
    sheet = next(
        s for s in worksheet_service.worksheet(conn, PLANT, found["file_hash"])["sheets"]
        if s["load_id"] == found["load_id"]
    )
    return sheet["short_vehicles"]


# =====================================================================
# 1. the rule
# =====================================================================
LIST = {"M": frozenset({"A", "B", "C"})}


def test_the_rule_counts_only_live_non_extra_points():
    assert wavescan_points(["A", "B", "C"], "M", live_points=LIST, expected_zones={"M": 32}) == (3, 3)
    # A reading off the list (retired, extra, unknown) counts neither way.
    assert wavescan_points(["A", "B", "C", "X"], "M", live_points=LIST, expected_zones={}) == (3, 3)
    assert wavescan_points(["A", "B", "X"], "M", live_points=LIST, expected_zones={}) == (2, 3)
    assert wavescan_points(["A", "A", None], "M", live_points=LIST, expected_zones={}) == (1, 3)


def test_no_list_falls_back_to_the_model_count():
    assert wavescan_points(["A", "X"], "N", live_points=LIST, expected_zones={"N": 31}) == (2, 31)
    assert wavescan_points(["A"], "M", live_points=None, expected_zones={"M": 32}) == (1, 32)
    assert wavescan_points(["A"], "Q", live_points=LIST, expected_zones={}) == (1, None)
    assert wavescan_points(["A"], None, live_points=LIST, expected_zones={"M": 3}) == (1, None)


# =====================================================================
# 2. every reader, on the marker list (rolled back)
# =====================================================================
def test_a_retire_leaves_old_and_new_cars_complete(engine, actor_user_id):  # noqa: F811
    with tx(engine) as conn:
        full = walk(conn)
        old = car(conn, "old", full)
        assert states(conn, old) == every((32, 32, True))

        retire(conn, "LCFENDER", actor_user_id)
        new = car(conn, "new", [z for z in full if z[0] != "LCFENDER"])

        assert states(conn, old) == every((31, 31, True))
        assert states(conn, new) == every((31, 31, True))
        assert short_vehicles(conn, new) == []


def test_an_extra_point_is_ignored_either_way(engine, actor_user_id):  # noqa: F811
    with tx(engine) as conn:
        full = walk(conn)
        add(conn, "T114FIX Mark Door", actor_user_id)
        extra = next(z for z in walk(conn) if z[0] == "T114FIX Mark Door")
        assert ws_points_repo.live_lists(conn, PLANT)[MODEL] == frozenset(z for z, _ in full)

        without = car(conn, "without", full)
        walked = car(conn, "with", full + [extra])

        assert states(conn, without) == every((32, 32, True))
        assert states(conn, walked) == every((32, 32, True))
        assert short_vehicles(conn, walked) == []


def test_a_car_missing_a_live_point_is_incomplete(engine):  # noqa: F811
    with tx(engine) as conn:
        found = car(conn, "short", walk(conn)[1:])
        assert states(conn, found) == every((31, 32, False))
        [short] = short_vehicles(conn, found)
        assert (short["point_count"], short["expected_point_count"]) == (31, 32)


def test_no_live_list_falls_back_to_the_model_count(engine):  # noqa: F811
    """D-114F-4. Every fact points at a list row (`fk_ws_plant_point`), so a
    plant x model "with no live list" is one whose every point is retired --
    which Point Check refuses (the last point stays), so it is built here
    directly, inside the rolled-back transaction."""
    with tx(engine) as conn:
        full = walk(conn)
        whole = car(conn, "nolist-whole", full)
        short = car(conn, "nolist-short", full[1:])
        conn.execute(
            text(
                "UPDATE ref_plant_ws_point SET retired_at = now(), "
                "       retired_reason = 'T114-FIX test, rolled back' "
                " WHERE plant_code = :p AND model_code = :m AND retired_at IS NULL"
            ),
            {"p": PLANT, "m": MODEL},
        )
        assert MODEL not in ws_points_repo.live_lists(conn, PLANT)
        expected = load_reference_data(conn).expected_zones[MODEL]
        assert expected == 32
        assert states(conn, whole) == every((32, 32, True))
        assert states(conn, short) == every((31, 32, False))


# =====================================================================
# 3. no live car moves (read-only)
# =====================================================================
def test_every_live_car_reads_the_same_against_the_list_and_the_model(engine):  # noqa: F811
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        expected = dict(load_reference_data(conn).expected_zones)
        plants = [r[0] for r in conn.execute(text("SELECT DISTINCT plant FROM v_wavescan_active"))]
        cars = 0
        for plant in plants:
            groups = history_repo.identity_groups(conn, plant, None)
            by_list = group_vehicles(groups, expected, ws_points_repo.live_lists(conn, plant))
            by_model = group_vehicles(groups, expected, None)
            assert by_list == by_model, plant
            cars += len(by_list)
        assert cars > 0
        # The view: every live car the same against the list as against the model.
        moved = conn.execute(
            text(
                "SELECT count(*) FROM v_car_completeness v "
                "  JOIN ref_model m ON m.model_code = v.model "
                " WHERE v.zones_expected <> m.expected_zone_count"
            )
        ).scalar_one()
        assert moved == 0
        conn.rollback()
