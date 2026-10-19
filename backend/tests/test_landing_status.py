"""Landing status: weekly feed rule, dashboard box share, and the read itself.

The pure tests pin the owner's feed rule. The integration tests build their own
committed batch in 2099-01 inside a transaction that is always rolled back, and
evaluate the read `as_of` a moment in that month.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.domain.landing import WeekUpload, box_share, feed_status, week_of
from app.main import create_app
from app.services import landing as service
from app.services import overview as overview_service
from app.services import ws_points

TZ = timezone(timedelta(hours=7))
AS_OF = datetime(2099, 1, 10, 9, tzinfo=TZ)  # week 2 of January 2099
MODELS, COLORS = ["RANGER", "RAPTOR"], ["White", "Black"]


def week(n, combos, first="2099-01-06T09:00:00+07:00"):
    return WeekUpload(n, frozenset(combos), datetime.fromisoformat(first) if first else None)


# ------------------------------------------------------------------ rules
def test_week_bands_follow_history():
    assert [week_of(d) for d in (1, 7, 8, 14, 15, 28, 29, 31)] == [1, 1, 2, 2, 3, 4, 5, 5]


def test_past_week_with_nothing_is_missing():
    found = feed_status(AS_OF, [], MODELS, COLORS)
    assert found["level"] == "MISSING" and found["missing_weeks"] == 1 and found["pct"] == 0


def test_week_uploaded_after_it_ended_is_late():
    late = week(1, {("RANGER", "White"), ("RANGER", "Black")}, "2099-01-09T08:00:00+07:00")
    assert feed_status(AS_OF, [late], MODELS, COLORS)["level"] == "LATE"


def test_week_missing_an_offered_colour_is_late():
    assert feed_status(AS_OF, [week(1, {("RANGER", "White")})], MODELS, COLORS)["level"] == "LATE"


def test_every_colour_on_time_is_update_and_pct_grows_with_this_week():
    w1 = week(1, {("RANGER", "White"), ("RAPTOR", "Black")})
    before = feed_status(AS_OF, [w1], MODELS, COLORS)
    assert before["level"] == "UPDATE" and before["pct"] == 25  # 2 of 4 combos x 2 weeks
    after = feed_status(AS_OF, [w1, week(2, {("RANGER", "White"), ("X", "White")}, None)],
                        MODELS, COLORS)
    assert after["pct"] == 37.5 and after["colours_this_week"] == 1


def test_no_plan_gives_no_feed():
    assert feed_status(AS_OF, [], [], COLORS) is None


def test_box_share_skips_ungraded_groups_and_boxes():
    found = box_share({"WAVESCAN_H": ["PASS", "FAIL"], "WAVESCAN_V": ["PASS", None],
                       "FILM_H": ["WARNING"], "FILM_V": []})
    assert found["pct"] == (50 + 100 + 0) / 3
    assert box_share({"FILM_H": [None]})["pct"] is None


# ----------------------------------------------------------- integration
PLANT = "FTM"
MODEL = "P703 DBL RAPTOR"


@pytest.fixture(scope="module")
def engine(admin_dsn):
    found = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn))
    yield found
    found.dispose()


@contextmanager
def tx(engine):
    with engine.connect() as conn:
        outer = conn.begin()
        try:
            yield conn
        finally:
            outer.rollback()


def every_colour(conn, started: str, day: str = "2099-01-03") -> int:
    """One committed batch: one CF reading per offered FTM colour, measured `day`."""
    digest = hashlib.sha256(f"landing:{uuid.uuid4().hex}".encode()).hexdigest()
    load_id = conn.execute(text("""
        INSERT INTO load_batch (source_file, source_sheet, plant_code, file_hash, status,
                                rows_in_file, raw_store_key, started_at, finished_at, notes)
        VALUES ('LANDING fixture.xlsx', 'Sheet1', :plant, :hash, 'COMMITTED', 0, :key,
                CAST(:started AS timestamptz), CAST(:started AS timestamptz),
                'landing test, rolled back')
        RETURNING load_id
    """), {"plant": PLANT, "hash": digest, "key": f"raw/{digest}", "started": started}).scalar_one()
    point = ws_points.ws_point_list(conn, PLANT, MODEL)["items"][0]
    _, colours = service.repo.offered(conn, PLANT)
    for row, colour in enumerate(colours, start=2):
        conn.execute(text("""
            INSERT INTO wavescan (measured_date, plant, model, checkzone, color,
                tolerance_group, paintline, serial_no, lw, sw, cf, doi, du, wa, wb,
                wc, wd, we, b, load_id, source_sheet, source_row)
            VALUES (:day, :plant, :model, :zone, :colour, :tol, 'BOOTH1', :serial,
                    1, 2, 60, 80, 3, 4, 5, 6, 7, 8, 0, :load, 'Sheet1', :row)
        """), {"day": day, "plant": PLANT, "model": MODEL, "zone": point["zone_code"],
               "colour": colour, "tol": point["tolerance_group"],
               "serial": f"LAND-{load_id}-{row}", "load": load_id, "row": row})
    return load_id


def ftm(conn, scope=None):
    return next(p for p in service.status(conn, scope, AS_OF)["plants"] if p["plant_code"] == PLANT)


@pytest.mark.ingest
def test_feed_reads_the_active_views_and_batch_times(engine):
    with tx(engine) as conn:
        assert ftm(conn)["feed"]["level"] == "MISSING"
        load_id = every_colour(conn, "2099-01-05T10:00:00+07:00")
        found = ftm(conn)
        models, colours = service.repo.offered(conn, PLANT)
        assert found["feed"]["level"] == "UPDATE"
        assert found["feed"]["pct"] == 100 * len(colours) / (len(models) * len(colours) * 2)
        assert found["latest_files"][0]["load_id"] == load_id
        conn.execute(text("UPDATE load_batch SET started_at = '2099-01-09T10:00:00+07:00' "
                          "WHERE load_id = :id"), {"id": load_id})
        assert ftm(conn)["feed"]["level"] == "LATE"
        conn.execute(text("UPDATE load_batch SET status = 'SUPERSEDED' WHERE load_id = :id"),
                     {"id": load_id})
        assert ftm(conn)["feed"]["level"] == "MISSING"  # superseded data is not on file


@pytest.mark.ingest
def test_quality_is_the_dashboards_own_box_statuses(engine):
    with tx(engine) as conn:
        every_colour(conn, "2099-01-05T10:00:00+07:00")
        boxes = overview_service.overview(conn, PLANT, plant_scope=None, month="2099-01",
                                          models=None, colors=None)["boxes"]
        quality = ftm(conn)["quality"]
        h = next(g for g in quality["groups"] if g["group"] == "WAVESCAN_H")
        v = next(g for g in quality["groups"] if g["group"] == "WAVESCAN_V")
        graded = [b for b in boxes if b["status"] is not None]
        assert h["graded"] + v["graded"] == len(graded)
        assert h["passed"] + v["passed"] == sum(1 for b in graded if b["status"] == "PASS")


@pytest.mark.ingest
def test_scope_limits_plants(engine):
    with tx(engine) as conn:
        assert [p["plant_code"] for p in service.status(conn, ["AAT"], AS_OF)["plants"]] == ["AAT"]


def test_route_shape_and_as_of(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.deps import active_measurement_scope, get_connection
    from app.repositories.measurements import MeasurementFilter

    app = create_app(Settings(env="development", app_database_url="", auth_dev_bypass=True))

    def connection():
        yield object()

    app.dependency_overrides[get_connection] = connection
    app.dependency_overrides[active_measurement_scope] = lambda: MeasurementFilter(plant_scope=["FVL"])
    seen = []
    monkeypatch.setattr(service, "status", lambda conn, scope, when: seen.append((scope, when)) or {
        "as_of": when, "month": when.strftime("%Y-%m"), "plants": []})
    with TestClient(app) as client:
        found = client.get("/api/v1/landing/status?as_of=2099-01-10T09:00:00%2B07:00")
        assert found.status_code == 200 and found.json()["month"] == "2099-01"
        assert client.get("/api/v1/landing/status").status_code == 200
        assert client.get("/api/v1/landing/status?as_of=nope").status_code == 422
    assert seen[0][0] == ["FVL"] and seen[0][1] == AS_OF
