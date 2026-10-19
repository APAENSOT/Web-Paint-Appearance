"""T114 -- Point Check, Wave Scan: counted, extra, retire, add (revision 0037).

Claims (task section 4), against the running application and the live
database:

1. **The migration.** `ref_plant_ws_point.is_extra` defaults false and no
   point carries it; `v_wavescan_counted` reads through `v_wavescan_active`
   and, with nothing switched off, returns exactly its rows; `app_rw` holds
   exactly D-114-11 and can append a setting but never rewrite or delete one.
2. **Counted off** (D-114-2, D-114-3): the reading leaves the dashboard and
   the view; History and Comparison keep it, tagged "not counted"; the Model
   card counts one fewer (D-114-10). Switching back is a second row.
3. **Retire** (D-114-4): the point leaves the live list, the dashboard, the
   panel-match pool and the gold the cleaner reads; History keeps its reading
   tagged "retired"; Comparison keeps it, tagged; the pre-fill memory never
   pre-fills onto it -- that row arrives red and is asked.
4. **Add** (D-114-5..7): an existing code or a typed one goes to the end of
   the walk, tagged extra, counted, with H/V read off the name; a new code
   writes its `ref_checkzone` row and the model its `ref_model_zone` row; a
   taught map onto the added point is accepted (the T89 FK); and every
   D-114-7 refusal -- live, retired, a case-and-space twin, position 40 --
   writes nothing.
5. **Old cars never change state** (D-114-8): a car measured before an add,
   a retire and a switch-off stays complete. (T114-FIX: its counts follow
   the live, non-extra list, so a retire takes one point off both sides.)
6. **Film Point Check untouched**, and Point Check's own reads (GET only):
   every plant's live lists, 0 extras, Viewer refused.

**What this file writes.** Almost everything runs inside one admin
transaction that is **rolled back** (`tx` below), calling the same services
the routes call -- nothing it adds, retires or switches ever commits. The one
exception is `test_the_api_round_trip_on_a_marker`, which proves the HTTP
path and the `app_rw` grants end to end on one marker code (`T114 MARK
DOOR`) and removes every row it wrote by that name. The live lists are
asserted unchanged on the way out (`test_reference_counts_are_flat`).
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from datetime import date

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.domain.panel_walk import (
    ATTENTION_RED,
    CanonicalPoint,
    WalkRow,
    fingerprint,
    match_walk,
    read_walk,
)
from app.domain.ws_plant_gold import gold_key, ws_tolerance
from app.repositories import mappings as maps
from app.repositories.reference import load_reference_data
from app.repositories.standards import model_points
from app.services import comparison as comparison_service
from app.services import history as history_service
from app.services import overview as overview_service
from app.services import ws_points as service
from app.services.panel_pool import panel_pool
from app.services.workbooks import WorkbookError
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t58_wavescan_plant_gold import zone as resolve_zone

pytestmark = pytest.mark.ingest

PLANT = "FTM"
MODEL = "P703 DBL RAPTOR"
COLOUR = "Arctic White"
MONTH = "2099-01"
BOUNDS = (date(2099, 1, 1), date(2099, 1, 31))
REASON = "T114 test, rolled back"

#: Measured 2026-10-12 (T114 section 1).
LIVE = {
    "AAT": {"P703 DBL RANGER": 32, "P703 DBL SUPER DUTY": 32, "U704": 31},
    "FTM": {"P703 DBL RANGER": 32, "P703 DBL RAPTOR": 32},
    "FVL": {"CX743": 32, "P703 DBL RANGER": 32, "V363": 32},
    "SAP": {"J73 DBL": 32, "P703 DBL RANGER": 32, "P703 DBL RAPTOR": 32},
}

#: D-114-11, exactly.
GRANTS = {
    "ws_point_setting": {"SELECT", "INSERT"},
    "ref_plant_ws_point": {"SELECT", "INSERT"},
    "ref_checkzone": {"SELECT", "INSERT"},
    "ref_model_zone": {"SELECT", "INSERT"},
    "v_wavescan_counted": {"SELECT"},
}

#: The one code the API round trip commits, and removes by name.
MARKER = "T114 MARK DOOR"


# =====================================================================
# helpers
# =====================================================================
@pytest.fixture(scope="module")
def engine(admin_dsn):
    found = create_engine(
        "postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn)
    )
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


def live_list(conn) -> list[dict]:
    return service.ws_point_list(conn, PLANT, MODEL)["items"]


def car(conn, tag: str, zones: list[tuple[str, str]] | None = None) -> str:
    """One committed car at FTM / Raptor in 2099-01, one reading per point.

    Returns the serial. Inside `tx`, so it never commits.
    """
    zones = zones or [(p["zone_code"], p["tolerance_group"]) for p in live_list(conn)]
    digest = hashlib.sha256(f"T114:{tag}:{uuid.uuid4().hex}".encode()).hexdigest()
    load_id = conn.execute(
        text(
            """
            INSERT INTO load_batch (
                source_file, source_sheet, plant_code, file_hash, status,
                rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
                rows_quarantine, raw_store_key, finished_at, notes)
            VALUES (:file, 'Sheet1', :plant, :hash, 'COMMITTED', :n, :n, 0, 0, 0,
                    :key, now(), 'T114 fixture, rolled back')
            RETURNING load_id
            """
        ),
        {
            "file": f"T114 {tag}.xlsx", "plant": PLANT, "hash": digest,
            "n": len(zones), "key": f"wavescan/raw/{digest}",
        },
    ).scalar_one()
    serial = f"T114-{tag}-{load_id}"
    for row, (zone_code, tolerance) in enumerate(zones, start=2):
        conn.execute(
            text(
                """
                INSERT INTO wavescan (
                    measured_date, plant, model, checkzone, color,
                    tolerance_group, paintline, serial_no,
                    lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
                    load_id, source_sheet, source_row)
                VALUES ('2099-01-10', :plant, :model, :zone, :colour, :tol,
                        'BOOTH1', :serial, 1, 2, 60, 80, 3, 4, 5, 6, 7, 8, 0,
                        :load, 'Sheet1', :row)
                """
            ),
            {
                "plant": PLANT, "model": MODEL, "zone": zone_code,
                "colour": COLOUR, "tol": tolerance, "serial": serial,
                "load": load_id, "row": row,
            },
        )
    return serial


def dashboard_n(conn) -> int:
    """Every reading the dashboard counts in 2099-01, from its own boxes."""
    found = overview_service.overview(
        conn, PLANT, plant_scope=None, month=MONTH, models=[MODEL], colors=None
    )
    return sum(box["n"] for box in found["boxes"])


def counted_view_n(conn) -> int:
    return conn.execute(
        text(
            "SELECT count(*) FROM v_wavescan_counted "
            "WHERE plant = :p AND model = :m AND measured_date BETWEEN :a AND :b"
        ),
        {"p": PLANT, "m": MODEL, "a": BOUNDS[0], "b": BOUNDS[1]},
    ).scalar_one()


def history_vehicle(conn, serial: str):
    return next(
        v for v in history_service._vehicles(
            conn, PLANT, plant_scope=None, bounds=BOUNDS, model=MODEL, color=None,
        )
        if v.serial_no == serial
    )


def history_points(conn, serial: str) -> dict[str, dict]:
    found = history_service.points(
        conn, PLANT, history_vehicle(conn, serial).vehicle_id,
        plant_scope=None, limit=500, offset=0,
    )
    return {item["checkzone"]: item for item in found["items"]}


def comparison_of(conn, serial: str) -> dict:
    return comparison_service.points(
        conn, PLANT, plant_scope=None, domain="WAVESCAN", model=MODEL,
        metric="cf", vehicle_ids=[history_vehicle(conn, serial).vehicle_id],
    )


def card(conn) -> int:
    return next(
        m["wavescan_points"] for m in model_points(conn, PLANT)
        if m["model_code"] == MODEL
    )


def switch(conn, zone_code: str, counted: bool, actor: str) -> dict:
    return service.change_ws_point_setting(
        conn, PLANT, MODEL, points=[{"zone_code": zone_code, "counted": counted}],
        reason=REASON, actor=actor, correlation_id=None,
    )


def add(conn, zone_code: str, actor: str, **over) -> dict:
    return service.add_ws_point(
        conn, PLANT, MODEL, zone_code=zone_code, counted=over.get("counted", True),
        reason=REASON, actor=actor, actor_name="T114 test",
        correlation_id=None,
    )


def retire(conn, zone_code: str, actor: str) -> dict:
    return service.retire_ws_point(
        conn, PLANT, MODEL, zone_code=zone_code, reason=REASON, actor=actor,
        correlation_id=None,
    )


def counts(conn) -> dict[str, int]:
    out = {}
    for table in ("ref_plant_ws_point", "ws_point_setting", "ref_checkzone",
                  "ref_model_zone", "ref_plant_zone_map"):
        out[table] = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
    return out


def spare_code(conn, tolerance: str) -> str:
    """An existing code that is on neither this list nor this model's catalogue."""
    return conn.execute(
        text(
            """
            SELECT c.zone_code FROM ref_checkzone c
             WHERE c.tolerance_group = :tol
               AND NOT EXISTS (SELECT 1 FROM ref_plant_ws_point p
                                WHERE p.plant_code = :p AND p.model_code = :m
                                  AND p.zone_code = c.zone_code)
               AND NOT EXISTS (SELECT 1 FROM ref_model_zone z
                                WHERE z.model_code = :m AND z.zone_code = c.zone_code)
             ORDER BY c.zone_code LIMIT 1
            """
        ),
        {"tol": tolerance, "p": PLANT, "m": MODEL},
    ).scalar_one()


# =====================================================================
# 1. the migration
# =====================================================================
def test_the_extra_column_defaults_false_and_no_point_is_extra(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT data_type, column_default, is_nullable "
            "  FROM information_schema.columns "
            " WHERE table_name = 'ref_plant_ws_point' AND column_name = 'is_extra'"
        )
        assert cur.fetchone() == ("boolean", "false", "NO")
        cur.execute("SELECT count(*) FROM ref_plant_ws_point WHERE is_extra")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT version_num FROM alembic_version")
        # T114-FIX: 0038 (v_car_completeness) follows 0037.
        assert cur.fetchone()[0] >= "0037"


def test_the_counted_view_reads_through_the_active_view(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT pg_get_viewdef('v_wavescan_counted'::regclass, true)")
        definition = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM v_wavescan_counted")
        counted = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM v_wavescan_active")
        active = cur.fetchone()[0]
    assert "v_wavescan_active" in definition
    # The predicate stays in one place (01-DATA-MODEL section 10): the view
    # carries the columns through `w.*` but never filters on them again.
    for token in ("COMMITTED", "is_superseded = false", "is_duplicate = false",
                  "NOT w.is_superseded", "NOT w.is_duplicate"):
        assert token not in definition, token
    # Nothing is switched off and every live reading joins a live point.
    assert counted == active


def test_the_grants_are_exactly_d_114_11(admin_conn, app_role):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, privilege_type FROM information_schema.table_privileges "
            " WHERE grantee = %s AND table_schema = 'public' AND table_name = ANY(%s)",
            (app_role, list(GRANTS)),
        )
        found: dict[str, set[str]] = {name: set() for name in GRANTS}
        for table, privilege in cur.fetchall():
            found[table].add(privilege)
        cur.execute(
            "SELECT column_name FROM information_schema.column_privileges "
            " WHERE grantee = %s AND table_name = 'ref_plant_ws_point' "
            "   AND privilege_type = 'UPDATE'",
            (app_role,),
        )
        updatable = {row[0] for row in cur.fetchall()}
    assert found == GRANTS
    assert updatable == {"retired_at", "retired_reason"}


def test_the_app_role_appends_a_setting_and_never_rewrites_one(app_conn):
    with app_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ws_point_setting (plant_code, model_code, zone_code, counted, reason) "
            "VALUES (%s, %s, 'RRHOOD', false, %s) RETURNING setting_id",
            (PLANT, MODEL, REASON),
        )
        setting_id = cur.fetchone()[0]
        for statement in (
            "UPDATE ws_point_setting SET counted = true WHERE setting_id = %s",
            "DELETE FROM ws_point_setting WHERE setting_id = %s",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with app_conn.transaction():
                    cur.execute(statement, (setting_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with app_conn.transaction():
                cur.execute(
                    "UPDATE ref_plant_ws_point SET point_no = 99 "
                    "WHERE plant_code = %s AND model_code = %s AND zone_code = 'RRHOOD'",
                    (PLANT, MODEL),
                )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with app_conn.transaction():
                cur.execute("DELETE FROM ref_checkzone WHERE zone_code = 'RRHOOD'")
    # `app_conn` rolls the insert back.


# =====================================================================
# 2. counted (D-114-2, D-114-3, D-114-10)
# =====================================================================
def test_not_counted_leaves_the_dashboard_and_stays_in_history_and_comparison(
    engine, actor_user_id
):
    with tx(engine) as conn:
        serial = car(conn, "counted")
        assert dashboard_n(conn) == counted_view_n(conn) == 32
        assert card(conn) == 32

        written = switch(conn, "LFFENDER", False, actor_user_id)
        assert written["rows_written"] == 1

        assert dashboard_n(conn) == counted_view_n(conn) == 31
        assert card(conn) == 31
        points = history_points(conn, serial)
        assert len(points) == 32, "History keeps every reading"
        assert points["LFFENDER"]["counted"] is False
        assert points["LFFENDER"]["retired"] is False
        assert all(p["counted"] for z, p in points.items() if z != "LFFENDER")
        matrix = comparison_of(conn, serial)
        location = next(loc for loc in matrix["locations"] if loc["code"] == "LFFENDER")
        assert location["counted"] is False
        assert location["cells"][0]["readings"], "Comparison keeps the reading"
        assert service.ws_point_list(conn, PLANT, MODEL)["items"][5]["counted"] is False

        # Append-only: switching back is a second row, and the latest wins.
        switch(conn, "LFFENDER", True, actor_user_id)
        assert dashboard_n(conn) == 32
        rows = conn.execute(
            text(
                "SELECT counted FROM ws_point_setting WHERE plant_code = :p "
                "AND model_code = :m AND zone_code = 'LFFENDER' ORDER BY setting_id"
            ),
            {"p": PLANT, "m": MODEL},
        ).scalars().all()
        assert rows == [False, True]
        audits = conn.execute(
            text(
                "SELECT count(*) FROM audit_event "
                "WHERE action = 'catalogue.ws_point_setting.change' "
                "  AND entity_id = :e AND occurred_at >= now() - interval '1 hour'"
            ),
            {"e": f"{PLANT}:{MODEL}"},
        ).scalar_one()
        assert audits >= 2


def test_a_setting_names_only_live_points(engine, actor_user_id):
    with tx(engine) as conn:
        with pytest.raises(WorkbookError) as refused:
            switch(conn, "NOT A POINT", False, actor_user_id)
        assert refused.value.status_code == 422


# =====================================================================
# 3. retire (D-114-4)
# =====================================================================
def test_a_retire_keeps_history_and_comparison_and_leaves_everything_else(
    engine, actor_user_id
):
    with tx(engine) as conn:
        serial = car(conn, "retire")
        before = history_vehicle(conn, serial)

        done = retire(conn, "LCFENDER", actor_user_id)
        assert done["zone_code"] == "LCFENDER" and done["point_no"] == 7

        listed = service.ws_point_list(conn, PLANT, MODEL)
        assert "LCFENDER" not in [p["zone_code"] for p in listed["items"]]
        gone = next(p for p in listed["retired_items"] if p["zone_code"] == "LCFENDER")
        assert gone["retired_reason"].startswith("T114 (D-114-4)")
        assert REASON in gone["retired_reason"]

        # The dashboard, the view and the card drop it.
        assert dashboard_n(conn) == counted_view_n(conn) == 31
        assert card(conn) == 31
        # History keeps the reading, tagged; the car stays complete.
        points = history_points(conn, serial)
        assert len(points) == 32
        assert points["LCFENDER"]["retired"] is True
        after = history_vehicle(conn, serial)
        # T114-FIX CHANGE (D-114F-1): complete against the live list, so the
        # counts follow it (32 / 32 -> 31 / 31); completeness does not move.
        assert (before.point_count, before.expected_point_count, before.incomplete_set) == (
            32, 32, False,
        )
        assert (after.point_count, after.expected_point_count, after.incomplete_set) == (
            31, 31, False,
        )
        # Comparison keeps it, beside the catalogue, tagged.
        matrix = comparison_of(conn, serial)
        assert "LCFENDER" not in [loc["code"] for loc in matrix["locations"]]
        kept = [u for u in matrix["unaligned_locations"] if u["checkzone"] == "LCFENDER"]
        assert len(kept) == 1 and kept[0]["retired"] is True

        # No longer a target: not live, not in the pool, not in the gold.
        assert "LCFENDER" not in maps.live_panel_codes(conn, PLANT, MODEL)
        pool = panel_pool(conn, load_id=None, plant_code=PLANT, model_code=MODEL)
        assert "LCFENDER" not in [p.zone_code for p in pool.canonical_points]
        ref = load_reference_data(conn)
        assert gold_key("LCFENDER") not in ref.plant_gold[(PLANT, MODEL)]

        # The existing T86 audit action, and once only.
        assert conn.execute(
            text(
                "SELECT count(*) FROM audit_event WHERE action = "
                "'catalogue.plant_ws_point.retire' AND entity_id = :e "
                "AND after ->> 'via' = 'Point Check'"
            ),
            {"e": f"{PLANT}:{MODEL}"},
        ).scalar_one() >= 1
        with pytest.raises(WorkbookError) as again:
            retire(conn, "LCFENDER", actor_user_id)
        assert again.value.status_code == 409


def test_the_memory_never_prefills_onto_a_retired_point():
    """D-114-4: a remembered answer onto a point that left the live list is
    dropped, and its row arrives red and asked. `points` is the live list, so
    a retired point is simply not in it."""
    rows = [
        WalkRow(source_row=i, raw_zone_text=label, vehicle="car")
        for i, label in enumerate(("01HOOD", "07LFFENDER", "08LCFENDER"), start=2)
    ]
    walk = fingerprint(read_walk(rows))
    remembered = {"01HOOD": "RRHOOD", "07LFFENDER": "LFFENDER", "08LCFENDER": "LCFENDER"}
    live = [
        CanonicalPoint(zone_code="RRHOOD", point_no=1),
        CanonicalPoint(zone_code="LFFENDER", point_no=6),
        CanonicalPoint(zone_code="LCFENDER", point_no=7),
    ]
    before = match_walk(rows, live, remembered=remembered, remembered_fingerprint=walk)
    assert before.by_spelling()["08LCFENDER"].prefilled_zone_code == "LCFENDER"

    after_retire = [p for p in live if p.zone_code != "LCFENDER"]
    after = match_walk(
        rows, after_retire, remembered=remembered, remembered_fingerprint=walk
    )
    verdict = after.by_spelling()["08LCFENDER"]
    assert verdict.prefilled_zone_code is None
    assert verdict.attention == ATTENTION_RED
    assert "retired" in verdict.reason and "LCFENDER" in verdict.reason
    # The other rows keep their memory.
    assert after.by_spelling()["07LFFENDER"].prefilled_zone_code == "LFFENDER"


def test_the_last_live_point_cannot_be_retired(engine, actor_user_id):
    with tx(engine) as conn:
        codes = [p["zone_code"] for p in live_list(conn)]
        for code in codes[:-1]:
            retire(conn, code, actor_user_id)
        with pytest.raises(WorkbookError) as refused:
            retire(conn, codes[-1], actor_user_id)
        assert refused.value.status_code == 409
        assert "last live point" in refused.value.detail


# =====================================================================
# 4. add (D-114-5..7)
# =====================================================================
def test_an_existing_code_goes_to_the_end_extra_and_counted(engine, actor_user_id):
    with tx(engine) as conn:
        code = spare_code(conn, "Vertical")
        before = counts(conn)
        done = add(conn, code, actor_user_id)
        assert done["point_no"] == 33 and done["tolerance_group"] == "Vertical"

        listed = live_list(conn)
        last = listed[-1]
        assert (last["zone_code"], last["point_no"], last["is_extra"], last["counted"]) == (
            code, 33, True, True,
        )
        assert last["note"] == "T114 Point Check add by T114 test"
        after = counts(conn)
        assert after["ref_checkzone"] == before["ref_checkzone"], "an existing code"
        assert after["ref_model_zone"] == before["ref_model_zone"] + 1
        assert after["ref_plant_ws_point"] == before["ref_plant_ws_point"] + 1
        assert after["ws_point_setting"] == before["ws_point_setting"] + 1
        assert conn.execute(
            text(
                "SELECT zone_no FROM ref_model_zone WHERE model_code = :m AND zone_code = :z"
            ),
            {"m": MODEL, "z": code},
        ).scalar_one() == 33
        # A new point is a normal live target: in the pool, in the gold, and
        # a reading on it counts.
        pool = panel_pool(conn, load_id=None, plant_code=PLANT, model_code=MODEL)
        assert code in [p.zone_code for p in pool.canonical_points]
        assert resolve_zone(load_reference_data(conn), PLANT, MODEL, code) == code
        assert card(conn) == 33
        car(conn, "added", [(code, "Vertical")])
        assert dashboard_n(conn) == 1
        assert conn.execute(
            text(
                "SELECT count(*) FROM audit_event WHERE action = "
                "'catalogue.plant_ws_point.add' AND entity_id = :e"
            ),
            {"e": f"{PLANT}:{MODEL}:{code}"},
        ).scalar_one() == 1


@pytest.mark.parametrize(
    ("typed", "stored", "tolerance", "group"),
    [
        ("  T114 Mark Roof  ", "T114 Mark Roof", "Horizontal", "ROOF"),
        ("T114 Mark Door", "T114 Mark Door", "Vertical", "DOOR"),
        ("t114floorbox", "t114floorbox", "Horizontal", "BOX"),
    ],
)
def test_a_new_code_is_kept_as_typed_and_hv_comes_from_its_name(
    engine, actor_user_id, typed, stored, tolerance, group
):
    with tx(engine) as conn:
        done = add(conn, typed, actor_user_id, counted=False)
        assert done["zone_code"] == stored
        assert done["tolerance_group"] == tolerance == ws_tolerance(stored)
        row = conn.execute(
            text(
                "SELECT zone_name, panel_group, tolerance_group FROM ref_checkzone "
                "WHERE zone_code = :z"
            ),
            {"z": stored},
        ).one()
        assert tuple(row) == (stored, group, tolerance)
        last = live_list(conn)[-1]
        assert (last["zone_code"], last["is_extra"], last["counted"]) == (stored, True, False)


def test_a_taught_map_onto_an_added_point_is_accepted(engine, actor_user_id):
    """T89: a map row needs `ref_model_zone`. The add wrote it."""
    with tx(engine) as conn:
        add(conn, "T114 Mark Door", actor_user_id)
        maps.insert_panel_match_row(
            conn, plant_code=PLANT, model_code=MODEL,
            raw_zone_text="t114 mark door spelling", raw_position=33,
            zone_code="T114 Mark Door", approved_by=actor_user_id,
            note=REASON, signal="name",
        )
        ref = load_reference_data(conn)
        assert resolve_zone(ref, PLANT, MODEL, "T114 MARK DOOR SPELLING") == "T114 Mark Door"


def test_every_add_refusal_writes_nothing(engine, actor_user_id):
    with tx(engine) as conn:
        retired = conn.execute(
            text(
                "SELECT zone_code FROM ref_plant_ws_point WHERE plant_code = :p "
                "AND model_code = :m AND retired_at IS NOT NULL ORDER BY point_no LIMIT 1"
            ),
            {"p": PLANT, "m": MODEL},
        ).scalar_one()
        before = counts(conn)
        cases = [
            ("RRHOOD", 409, "already point 1"),
            (retired, 409, "This point was retired; restore it instead."),
            ("rr hood", 409, "same panel as 'RRHOOD'"),
            ("RR Hood", 409, "same panel as 'RRHOOD'"),
            ("T114 XYZ", 422, "does not say which panel"),
            ("   ", 422, "Name the point"),
        ]
        for typed, status, words in cases:
            with pytest.raises(WorkbookError) as refused:
                add(conn, typed, actor_user_id)
            assert refused.value.status_code == status, typed
            assert words in refused.value.detail, (typed, refused.value.detail)
        assert counts(conn) == before


def test_a_model_with_no_position_left_refuses_a_new_one(engine, actor_user_id):
    with tx(engine) as conn:
        fillers = conn.execute(
            text(
                """
                SELECT c.zone_code FROM ref_checkzone c
                 WHERE NOT EXISTS (SELECT 1 FROM ref_model_zone z
                                    WHERE z.model_code = :m AND z.zone_code = c.zone_code)
                   AND NOT EXISTS (SELECT 1 FROM ref_plant_ws_point p
                                    WHERE p.plant_code = :p AND p.model_code = :m
                                      AND p.zone_code = c.zone_code)
                 ORDER BY c.zone_code LIMIT 8
                """
            ),
            {"m": MODEL, "p": PLANT},
        ).scalars().all()
        for number, code in enumerate(fillers, start=33):
            conn.execute(
                text(
                    "INSERT INTO ref_model_zone (model_code, zone_code, zone_no) "
                    "VALUES (:m, :z, :n)"
                ),
                {"m": MODEL, "z": code, "n": number},
            )
        before = counts(conn)
        with pytest.raises(WorkbookError) as refused:
            add(conn, "T114 Mark Door", actor_user_id)
        assert refused.value.status_code == 409
        assert "40" in refused.value.detail
        assert counts(conn) == before
        # A code already on the model's catalogue needs no position: allowed.
        assert add(conn, fillers[0], actor_user_id)["point_no"] == 33


# =====================================================================
# 5. old cars (D-114-8)
# =====================================================================
def test_an_old_car_keeps_its_state_through_add_retire_and_switch(engine, actor_user_id):
    with tx(engine) as conn:
        serial = car(conn, "old")
        before = history_vehicle(conn, serial)
        assert (before.point_count, before.expected_point_count, before.incomplete_set) == (
            32, 32, False,
        )
        candidate = comparison_of(conn, serial)["columns"][0]

        add(conn, "T114 Mark Door", actor_user_id)
        retire(conn, "RRBOX", actor_user_id)
        switch(conn, "RCBOX", False, actor_user_id)

        after = history_vehicle(conn, serial)
        # T114-FIX CHANGE (D-114F-1): the car stays complete; its counts
        # follow the live, non-extra list -- the retire takes one point off
        # both sides, the extra and the switch-off take nothing.
        assert (after.point_count, after.expected_point_count, after.incomplete_set) == (
            31, 31, False,
        )
        again = comparison_of(conn, serial)["columns"][0]
        assert candidate["incomplete"] is False and again["incomplete"] is False
        assert (again["point_count"], again["expected_point_count"]) == (31, 31)


# =====================================================================
# 6. reads, Film, roles (GET only on the live database)
# =====================================================================
def test_point_check_lists_every_plant_as_measured(engineer):  # noqa: F811
    for plant, models in LIVE.items():
        response = engineer.get(f"/api/v1/plants/{plant}/ws-points")
        assert response.status_code == 200, response.text
        got = {
            m["model_code"]: (m["point_count"], m["counted_count"], m["extra_count"])
            for m in response.json()["items"]
        }
        assert got == {m: (n, n, 0) for m, n in models.items()}, plant


def test_one_list_says_everything_point_check_shows(engineer):  # noqa: F811
    response = engineer.get(f"/api/v1/plants/{PLANT}/ws-points/{MODEL}")
    assert response.status_code == 200, response.text
    body = response.json()
    items = body["items"]
    assert [p["point_no"] for p in items] == list(range(1, 33))
    assert items[0]["zone_code"] == "RRHOOD"
    for point in items:
        assert point["tolerance_group"] == ws_tolerance(point["zone_code"])
        assert point["counted"] is True and point["is_extra"] is False
    assert len(body["retired_items"]) == 32
    assert all(p["retired_reason"] for p in body["retired_items"])
    on_list = {p["zone_code"] for p in items} | {p["zone_code"] for p in body["retired_items"]}
    assert not on_list & {z["zone_code"] for z in body["zone_choices"]}
    assert body["horizontal_words"] == ["HOOD", "ROOF", "FLOOR"]
    assert engineer.get(f"/api/v1/plants/{PLANT}/ws-points/P703 RAPCAP").status_code == 404


def test_a_viewer_sees_no_point_check(viewer):  # noqa: F811
    assert viewer.get(f"/api/v1/plants/{PLANT}/ws-points").status_code == 403
    assert viewer.post(
        f"/api/v1/plants/{PLANT}/ws-points/{MODEL}/add",
        json={"zone_code": MARKER, "reason": REASON},
    ).status_code == 403


def test_film_point_check_is_untouched(engineer):  # noqa: F811
    response = engineer.get(f"/api/v1/plants/{PLANT}/film-points")
    assert response.status_code == 200, response.text
    assert {m["model_code"]: m["point_count"] for m in response.json()["items"]} == {
        "P703 DBL RANGER": 98, "P703 DBL RAPTOR": 98, "P703 RAPCAP": 93, "P703 SGL": 58,
    }


def test_api_refusals_write_nothing(engineer, engine):  # noqa: F811
    with engine.connect() as conn:
        before = counts(conn)
    base = f"/api/v1/plants/{PLANT}/ws-points/{MODEL}"
    assert engineer.post(f"{base}/add", json={"zone_code": "RRHOOD", "reason": REASON}).status_code == 409
    assert engineer.post(f"{base}/add", json={"zone_code": "rr hood", "reason": REASON}).status_code == 409
    assert engineer.post(f"{base}/retire", json={"zone_code": MARKER, "reason": REASON}).status_code == 409
    assert engineer.post(
        base, json={"points": [{"zone_code": MARKER, "counted": False}], "reason": REASON}
    ).status_code == 422
    assert engineer.post(f"{base}/add", json={"zone_code": MARKER, "reason": "x"}).status_code == 422
    with engine.connect() as conn:
        assert counts(conn) == before


@pytest.fixture()
def marker_cleanup(admin_conn):
    """Remove every row the round trip wrote, by the marker name only."""
    # RO19 F3: the HTTP add also snapshots a measuring order (ws_points.py
    # `record_membership`). Record this plant's versions first, so only the
    # new ones that name this fixture's own marker are removed.
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_id FROM point_walk_version WHERE plant_code = %s "
                    "AND domain = 'WAVESCAN'", (PLANT,))
        versions_before = [row[0] for row in cur.fetchall()]
    yield
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT v.version_id FROM point_walk_version v WHERE v.plant_code = %s "
            "AND v.domain = 'WAVESCAN' AND NOT (v.version_id = ANY(%s)) AND EXISTS "
            "(SELECT 1 FROM point_walk_member m WHERE m.version_id = v.version_id "
            "AND m.point_code = %s)",
            (PLANT, versions_before, MARKER),
        )
        own_versions = [row[0] for row in cur.fetchall()]
        if own_versions:
            cur.execute("DELETE FROM audit_event WHERE entity_type = 'point_walk_version' "
                        "AND entity_id = ANY(%s)", ([str(v) for v in own_versions],))
            cur.execute("DELETE FROM point_walk_member WHERE version_id = ANY(%s)", (own_versions,))
            cur.execute("DELETE FROM point_walk_version WHERE version_id = ANY(%s)", (own_versions,))
        cur.execute(
            "DELETE FROM ws_point_setting WHERE plant_code = %s AND model_code = %s "
            "AND zone_code = %s", (PLANT, MODEL, MARKER),
        )
        # RO17: an add writes the point's first label row (FK to the point).
        cur.execute(
            "DELETE FROM ref_plant_ws_point_label WHERE plant_code = %s "
            "AND model_code = %s AND zone_code = %s", (PLANT, MODEL, MARKER),
        )
        cur.execute(
            "DELETE FROM ref_plant_ws_point WHERE plant_code = %s AND model_code = %s "
            "AND zone_code = %s", (PLANT, MODEL, MARKER),
        )
        cur.execute(
            "DELETE FROM ref_model_zone WHERE model_code = %s AND zone_code = %s",
            (MODEL, MARKER),
        )
        cur.execute("DELETE FROM ref_checkzone WHERE zone_code = %s", (MARKER,))


def test_the_api_round_trip_on_a_marker(engineer, marker_cleanup):  # noqa: F811
    """The HTTP path and the app_rw grants, end to end, on one marker code."""
    base = f"/api/v1/plants/{PLANT}/ws-points/{MODEL}"
    added = engineer.post(f"{base}/add", json={"zone_code": MARKER, "reason": REASON})
    assert added.status_code == 200, added.text
    assert added.json()["point_no"] == 33
    assert added.json()["tolerance_group"] == "Vertical"
    listed = engineer.get(base).json()
    assert listed["items"][-1]["zone_code"] == MARKER
    assert listed["items"][-1]["is_extra"] is True

    switched = engineer.post(
        base, json={"points": [{"zone_code": MARKER, "counted": False}], "reason": REASON}
    )
    assert switched.status_code == 200, switched.text
    assert engineer.get(base).json()["items"][-1]["counted"] is False

    retired = engineer.post(f"{base}/retire", json={"zone_code": MARKER, "reason": REASON})
    assert retired.status_code == 200, retired.text
    listed = engineer.get(base).json()
    assert MARKER not in [p["zone_code"] for p in listed["items"]]
    assert MARKER in [p["zone_code"] for p in listed["retired_items"]]
    again = engineer.post(f"{base}/add", json={"zone_code": MARKER, "reason": REASON})
    assert again.status_code == 409
    assert "restore it instead" in again.json()["message"]


def test_reference_counts_are_flat(admin_conn):
    """On the way out: the live lists as measured, nothing extra, nothing switched."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code, count(*) FROM ref_plant_ws_point "
            "WHERE retired_at IS NULL GROUP BY 1, 2"
        )
        live: dict[str, dict[str, int]] = {}
        for plant, model, n in cur.fetchall():
            live.setdefault(plant, {})[model] = n
        cur.execute("SELECT count(*) FROM ref_plant_ws_point")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ws_point_setting")
        settings = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ref_checkzone WHERE zone_code ILIKE 't114%'")
        markers = cur.fetchone()[0]
    assert live == LIVE
    assert total == 511
    assert settings == 0
    assert markers == 0
