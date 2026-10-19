"""Overview IMG against the real views, inside one rolled-back transaction.

`test_t105_img_overview.py` proves the pure aggregation on hand-made rows.
This file proves the parts a fixture cannot: that the repository reads the
same active and counted data the plant dashboards read. Every test builds its
own committed batch in month 2099-01/02 inside `tx`, which is always rolled
back, so nothing here ever commits and no owner row is read or touched.

Covered: Wave Scan counted / retired points (T114), Film point settings and
retired points (T99, T109), the Calculated Total over real point identities,
supersession through the active view, and plant scope on months + summary.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from decimal import Decimal

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.services import img_overview as service
from app.services import ws_points

pytestmark = pytest.mark.ingest

PLANT = "FTM"
MODEL = "P703 DBL RAPTOR"
COLOUR = "Arctic White"
MONTH = "2099-01"
REASON = "T105 IMG integration test, rolled back"


@pytest.fixture(scope="module")
def engine(admin_dsn):
    found = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn))
    yield found
    found.dispose()


@contextmanager
def tx(engine):
    """One transaction, always rolled back: nothing in it ever commits."""
    with engine.connect() as conn:
        outer = conn.begin()
        try:
            yield conn
        finally:
            outer.rollback()


def batch(conn, tag: str) -> int:
    digest = hashlib.sha256(f"T105:{tag}:{uuid.uuid4().hex}".encode()).hexdigest()
    return conn.execute(text("""
        INSERT INTO load_batch (source_file, source_sheet, plant_code, file_hash, status,
                                rows_in_file, raw_store_key, finished_at, notes)
        VALUES (:file, 'Sheet1', :plant, :hash, 'COMMITTED', 0, :key, now(), :notes)
        RETURNING load_id
    """), {"file": f"T105 {tag}.xlsx", "plant": PLANT, "hash": digest,
           "key": f"raw/{digest}", "notes": REASON}).scalar_one()


def ws_points_live(conn) -> list[dict]:
    return ws_points.ws_point_list(conn, PLANT, MODEL)["items"]


def cf_car(conn, cf: int = 60) -> int:
    """One committed FTM Raptor car in 2099-01, one CF reading per live point."""
    load_id = batch(conn, "cf")
    for row, point in enumerate(ws_points_live(conn), start=2):
        conn.execute(text("""
            INSERT INTO wavescan (measured_date, plant, model, checkzone, color,
                tolerance_group, paintline, serial_no, lw, sw, cf, doi, du, wa, wb,
                wc, wd, we, b, load_id, source_sheet, source_row)
            VALUES ('2099-01-10', :plant, :model, :zone, :colour, :tol, 'BOOTH1',
                    :serial, 1, 2, :cf, 80, 3, 4, 5, 6, 7, 8, 0, :load, 'Sheet1', :row)
        """), {"plant": PLANT, "model": MODEL, "zone": point["zone_code"],
               "colour": COLOUR, "tol": point["tolerance_group"],
               "serial": f"T105-{load_id}", "cf": cf, "load": load_id, "row": row})
    return load_id


def film_points(conn, orientation: str, n: int) -> list[str]:
    return list(conn.execute(text("""
        SELECT point_code FROM ref_plant_film_point
         WHERE plant_code = :p AND model_code = :m AND retired_at IS NULL
           AND btrim(orientation) = :o
         ORDER BY point_no LIMIT :n
    """), {"p": PLANT, "m": MODEL, "o": orientation, "n": n}).scalars())


def film_car(conn, readings: dict[str, dict[str, float]], day: str = "2099-01-12") -> int:
    load_id = batch(conn, "film")
    vehicle = hashlib.sha256(f"t105:{load_id}".encode()).hexdigest()
    for row, (point, layers) in enumerate(readings.items(), start=1):
        for layer, value in layers.items():
            conn.execute(text("""
                INSERT INTO filmthickness (measured_date, plant, model, color, point_code,
                    src_location_text, layer_code, thickness, logical_vehicle_id, load_id,
                    source_sheet, source_row)
                VALUES (:day, :plant, :model, :colour, :point, :point, :layer, :v,
                        :vehicle, :load, 'Quick Summary', :row)
            """), {"day": day, "plant": PLANT, "model": MODEL, "colour": COLOUR,
                   "point": point, "layer": layer, "v": value, "vehicle": vehicle,
                   "load": load_id, "row": row})
    return load_id


def series(conn, orient: str, metric: str, measure: str = "CALCULATED_TOTAL",
           scope: list[str] | None = None) -> dict | None:
    found = [s for s in service.overview(conn, scope, MONTH, measure)
             if s["plant_code"] == PLANT and s["family_key"] == "P703"
             and s["metric"] == metric and s["orient"] == orient]
    assert len(found) <= 1
    return found[0] if found else None


def reconciles(s: dict) -> None:
    for dimension in ("models", "colors", "locations"):
        assert sum(c["included_count"] for c in s[dimension]) == s["included_count"], dimension


# =====================================================================
def test_cf_reads_counted_points_and_discloses_setting_exclusions(engine, actor_user_id):
    with tx(engine) as conn:
        cf_car(conn)
        points = ws_points_live(conn)
        h = sum(1 for p in points if p["tolerance_group"].strip().lower().startswith("h"))
        before = {o: series(conn, o, "CF") for o in ("H", "V")}
        assert before["H"]["included_count"] + before["V"]["included_count"] == len(points)
        assert before["H"]["included_count"] == h
        assert Decimal(before["H"]["mean"]) == 60
        assert before["H"]["exclusions"]["SETTING_EXCLUDED"] == 0

        off = next(p for p in points if p["tolerance_group"].strip().lower().startswith("h"))
        ws_points.change_ws_point_setting(
            conn, PLANT, MODEL, points=[{"zone_code": off["zone_code"], "counted": False}],
            reason=REASON, actor=actor_user_id, correlation_id=None)
        after = series(conn, "H", "CF")
        assert after["included_count"] == h - 1
        assert after["exclusions"]["SETTING_EXCLUDED"] == 1
        assert series(conn, "V", "CF")["exclusions"]["SETTING_EXCLUDED"] == 0
        assert off["zone_code"] not in {c["key"] for c in after["locations"]}
        reconciles(after)

        retired = next(p for p in points if p["tolerance_group"].strip().lower().startswith("v"))
        ws_points.retire_ws_point(conn, PLANT, MODEL, zone_code=retired["zone_code"],
                                  reason=REASON, actor=actor_user_id, correlation_id=None)
        v = series(conn, "V", "CF")
        assert v["included_count"] == len(points) - h - 1
        assert v["exclusions"]["SETTING_EXCLUDED"] == 1
        reconciles(v)


def test_superseded_batch_leaves_months_and_summary(engine):
    with tx(engine) as conn:
        load_id = cf_car(conn)
        assert MONTH in service.months(conn, None)
        assert series(conn, "H", "CF")["included_count"] > 0
        conn.execute(text("UPDATE load_batch SET status = 'SUPERSEDED' WHERE load_id = :id"),
                     {"id": load_id})
        assert MONTH not in service.months(conn, None)
        assert series(conn, "H", "CF") is None


def test_plant_scope_applies_to_months_summary_and_contributors(engine):
    with tx(engine) as conn:
        cf_car(conn)
        assert MONTH in service.months(conn, [PLANT])
        assert MONTH not in service.months(conn, ["AAT"])
        assert series(conn, "H", "CF", scope=["AAT"]) is None
        assert all(s["plant_code"] == "AAT"
                   for s in service.overview(conn, ["AAT"], MONTH, "CALCULATED_TOTAL"))
        mine = series(conn, "H", "CF", scope=[PLANT])
        assert mine["member_models"] == [{"model_code": MODEL, "model_name": mine["member_models"][0]["model_name"]}]
        reconciles(mine)


def test_film_total_settings_and_retired_points_against_the_views(engine, actor_user_id):
    with tx(engine) as conn:
        a, b, c = film_points(conn, "H", 3)
        film_car(conn, {
            a: {"ECOAT": 0, "PRIMER": 10, "BASE": 20, "CLEAR": 30},   # total 60, a real zero
            b: {"ECOAT": 10, "PRIMER": 10, "BASE": 10, "CLEAR": 10},  # total 40
            c: {"ECOAT": 100},                                        # incomplete
        })
        total = series(conn, "H", "FILM")
        assert Decimal(total["mean"]) == 50 and total["included_count"] == 2
        assert total["count_unit"] == "FILM_POINT"
        assert total["exclusions"]["INCOMPLETE_TOTAL"] == 1
        reconciles(total)
        ecoat = series(conn, "H", "FILM", "ECOAT")
        assert ecoat["included_count"] == 3  # the incomplete point still feeds its layer
        assert Decimal(ecoat["mean"]) == Decimal(110) / 3

        conn.execute(text("""
            INSERT INTO film_point_setting (plant_code, model_code, point_code, counted,
                                            orientation, reason, created_by)
            VALUES (:p, :m, :pt, false, 'H', :r, CAST(:actor AS uuid))
        """), {"p": PLANT, "m": MODEL, "pt": a, "r": REASON, "actor": actor_user_id})
        total = series(conn, "H", "FILM")
        assert Decimal(total["mean"]) == 40 and total["included_count"] == 1
        assert total["exclusions"]["SETTING_EXCLUDED"] == 1
        assert total["exclusions"]["INCOMPLETE_TOTAL"] == 1  # never double-counted

        conn.execute(text("""
            UPDATE ref_plant_film_point SET retired_at = now(), retired_reason = :r
             WHERE plant_code = :p AND model_code = :m AND point_code = :pt
        """), {"p": PLANT, "m": MODEL, "pt": b, "r": REASON})
        total = series(conn, "H", "FILM")
        assert total["mean"] is None and total["included_count"] == 0
        assert total["availability"] == "EXCLUDED_OR_INCOMPLETE"
        assert total["exclusions"]["SETTING_EXCLUDED"] == 2


def test_incomplete_only_film_month_is_listed_for_its_layer(engine):
    with tx(engine) as conn:
        (point,) = film_points(conn, "V", 1)
        film_car(conn, {point: {"PRIMER": 25}}, day="2099-02-03")
        assert "2099-02" in service.months(conn, [PLANT])
        rows = service.overview(conn, [PLANT], "2099-02", "CALCULATED_TOTAL")
        v = next(s for s in rows if s["metric"] == "FILM" and s["orient"] == "V")
        assert v["mean"] is None and v["exclusions"]["INCOMPLETE_TOTAL"] == 1
        primer = next(s for s in service.overview(conn, [PLANT], "2099-02", "PRIMER")
                      if s["metric"] == "FILM" and s["orient"] == "V")
        assert Decimal(primer["mean"]) == 25 and primer["included_count"] == 1


def test_img_color_reads_the_same_views_and_settings(engine, actor_user_id):
    with tx(engine) as conn:
        cf_car(conn, cf=63)
        points = ws_points_live(conn)
        horizontal = [p for p in points if p["tolerance_group"].strip().lower().startswith("h")]
        def white():
            return next(s for s in service.colors(conn, [PLANT], MONTH)
                        if s["color_name"] == COLOUR and s["orient"] == "H")
        assert Decimal(white()["mean"]) == 63
        assert white()["included_count"] == len(horizontal)
        assert white()["unit"] == "CF" and white()["count_unit"] == "CF_READING"
        ws_points.change_ws_point_setting(
            conn, PLANT, MODEL, points=[{"zone_code": horizontal[0]["zone_code"], "counted": False}],
            reason=REASON, actor=actor_user_id, correlation_id=None)
        assert Decimal(white()["mean"]) == 63
        assert white()["included_count"] == len(horizontal) - 1
        assert white()["exclusions"]["SETTING_EXCLUDED"] == 1
        assert not [s for s in service.colors(conn, ["AAT"], MONTH) if s["plant_code"] == PLANT]
