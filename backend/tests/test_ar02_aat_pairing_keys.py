"""AR02: AAT pairing keys (migration 0045), read back on the live tables.

Read-only checks plus rolled-back owner transactions (a CHECK probe and the
downgrade guard's marker rows); nothing is deleted. The endpoint is a GET on
the live AAT data through ``TestClient`` inside a rolled-back transaction.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.deps import get_connection
from app.core.config import Settings
from app.main import create_app
from tests.conftest import _keyword_dsn_to_url

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "migration_0045", ROOT / "migrations/versions/0045_ar02_aat_pairing_keys.py"
)
m0045 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m0045)

TABLES = ("ref_plant_film_car_rule", "ref_pair_ws_zone", "ref_pair_film_point")
RANGER, SUPER_DUTY, U704 = "P703 DBL RANGER", "P703 DBL SUPER DUTY", "U704"
AAT_RULE = r"^(\d{7}) "
GROUPS = sorted([
    "HOOD", "ROOF", "L_FENDER", "R_FENDER", "L_FRONT_DOOR", "R_FRONT_DOOR", "L_REAR_DOOR",
    "R_REAR_DOOR", "L_C_PILLAR", "R_C_PILLAR", "L_BOX_SIDE", "R_BOX_SIDE", "TAILGATE", "LIFTGATE",
])
#: Live AAT Wave Scan zones with no pair group (AR02 D-AR02-5), measured 2026-10-13.
UNMAPPED_ZONES = {
    "LCPILLAR", "RRPILLARRH", "RFENDERHILH", "RFENDERMIDLH", "RFENDERLOWLH",
    "RRFENHIRH", "RRFENMIDRH", "RRFENLOWRH",
}
#: Live AAT film panels with no pair group, per model (AR02 tables A and B).
UNMAPPED_PANELS = {
    RANGER: {"LBXFLOOR", "LBXFRONT", "RBXFRONT", "TGATEIN", "LFDRPOST", "RTDRPOST", "TRFEND"},
    U704: {"PILLAHILH", "PILLAMEDLH", "PILLALOWLH", "PILLAHIRH", "PILLAMEDRH", "PILLALOWRH",
           "RRPILLAHILH", "RRPILLAMEDLH", "RRPILLALOWLH", "RRPILLAHIRH", "RRPILLAMEDRH",
           "RRPILLALOWRH", "CRPILLALH", "CRPILLARH", "BRPILLARH", "LBDOOR"},
}


def _one(cur, sql, *args):
    cur.execute(sql, args or None)
    return cur.fetchall()


# =====================================================================
# 1. seed (live reference tables, read only)
# =====================================================================
def test_the_aat_seed_matches_tables_a_and_b(admin_conn):
    with admin_conn.cursor() as cur:
        for plant, expected in (("AAT", [1, 87, 152]), ("FTM", [1, 64, 158])):
            counts = [_one(cur, f"SELECT count(*) FROM {t} WHERE plant_code = %s", plant)[0][0]
                      for t in TABLES]
            assert counts == expected, plant
        assert dict(_one(cur, "SELECT model_code, count(*) FROM ref_pair_ws_zone "
                              "WHERE plant_code = 'AAT' GROUP BY 1")) == {
            RANGER: 32, SUPER_DUTY: 32, U704: 23}
        assert dict(_one(cur, "SELECT model_code, count(*) FROM ref_pair_film_point "
                              "WHERE plant_code = 'AAT' GROUP BY 1")) == {RANGER: 78, U704: 74}

        unmapped_zones = _one(
            cur,
            "SELECT p.model_code, p.zone_code FROM ref_plant_ws_point p "
            "  LEFT JOIN ref_pair_ws_zone z USING (plant_code, model_code, zone_code) "
            " WHERE p.plant_code = 'AAT' AND p.retired_at IS NULL AND z.zone_code IS NULL",
        )
        assert {m for m, _ in unmapped_zones} == {U704}
        assert {z for _, z in unmapped_zones} == UNMAPPED_ZONES and len(unmapped_zones) == 8

        unmapped_points = _one(
            cur,
            "SELECT p.model_code, regexp_replace(p.point_code, '^[0-9]+', '') "
            "  FROM ref_plant_film_point p "
            "  LEFT JOIN ref_pair_film_point m USING (plant_code, model_code, point_code) "
            " WHERE p.plant_code = 'AAT' AND p.retired_at IS NULL AND m.point_code IS NULL",
        )
        for model, count in ((RANGER, 16), (U704, 21)):
            mine = [panel for m, panel in unmapped_points if m == model]
            assert len(mine) == count and set(mine) == UNMAPPED_PANELS[model], model

        assert _one(cur, "SELECT model_code, pair_group FROM ref_pair_ws_zone "
                         "WHERE plant_code = 'AAT' AND zone_code = 'FTFDOOR' ORDER BY 1") == [
            (RANGER, "R_FRONT_DOOR"), (SUPER_DUTY, "R_FRONT_DOOR")]
        assert _one(cur, "SELECT count(*) FROM ref_pair_film_point WHERE plant_code = 'AAT' "
                         "AND pair_group IN ('L_C_PILLAR', 'R_C_PILLAR')") == [(0,)]
        assert _one(cur, "SELECT DISTINCT plant_code, model_code FROM ref_pair_ws_zone "
                         "WHERE pair_group = 'LIFTGATE' UNION SELECT DISTINCT plant_code, "
                         "model_code FROM ref_pair_film_point WHERE pair_group = 'LIFTGATE'") == [
            ("AAT", U704)]
        # Exact match: the film spelling LIFTGAT... and TGATE never take LIFTGATE... / TGATEIN.
        assert _one(cur, "SELECT count(*) FROM ref_pair_film_point WHERE plant_code = 'AAT' "
                         "AND point_code ~ 'TGATEIN$'") == [(0,)]


def test_both_checks_hold_the_14_codes_and_refuse_another(admin_conn, admin_tx):
    with admin_conn.cursor() as cur:
        for table, name in m0045.CHECKS.items():
            (definition,) = _one(cur, "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                                      "WHERE conname = %s", name)[0]
            assert sorted(re.findall(r"'([A-Z_]+)'", definition)) == GROUPS, table
    with admin_tx.cursor() as cur:
        for statement in (
            "INSERT INTO ref_pair_ws_zone VALUES ('AAT', 'U704', 'LCPILLAR', 'NOPE')",
            "INSERT INTO ref_pair_film_point VALUES ('AAT', 'U704', '028LBDOOR', 'NOPE')",
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                with admin_tx.transaction():
                    cur.execute(statement)


def test_the_app_role_holds_select_only(admin_conn):
    with admin_conn.cursor() as cur:
        for table in TABLES:
            assert _one(cur, "SELECT privilege_type FROM information_schema.table_privileges "
                             "WHERE grantee = 'app_rw' AND table_schema = 'public' "
                             "AND table_name = %s", table) == [("SELECT",)], table


# =====================================================================
# 2. AAT car rule
# =====================================================================
def test_the_aat_rule_reads_the_leading_seven_digits_and_a_space(admin_conn):
    values = ["2494614 U704 A4D", "2509105 P703 G9Z",
              "2494614U704 A4D", "249461 U704 A4D", "AW_RB_1970561"]
    with admin_conn.cursor() as cur:
        assert _one(cur, "SELECT pattern FROM ref_plant_film_car_rule "
                         "WHERE plant_code = 'AAT'") == [(AAT_RULE,)]
        rows = _one(
            cur,
            "SELECT substring(v FROM r.pattern) FROM ref_plant_film_car_rule r, "
            "unnest(%s::text[]) WITH ORDINALITY AS t(v, n) WHERE r.plant_code = 'AAT' ORDER BY n",
            values,
        )
    assert [r[0] for r in rows] == ["2494614", "2509105", None, None, None]


# =====================================================================
# 3. endpoint on the live AAT data (GET, rolled back)
# =====================================================================
@pytest.fixture
def client(admin_dsn):
    engine = create_engine(_keyword_dsn_to_url(admin_dsn))
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("SET LOCAL ROLE app_rw"))
            app = create_app(Settings(env="development", app_database_url="", auth_dev_bypass=True,
                                      auth_dev_bypass_roles_raw="viewer",
                                      ingest_worker_enabled=False))

            def connection():
                yield conn
            app.dependency_overrides[get_connection] = connection
            with TestClient(app) as c:
                yield c
        finally:
            tx.rollback()
    engine.dispose()


def test_aat_pairs_ten_cars_and_flags_the_disagreements(client):
    response = client.get("/api/v1/plants/AAT/analysis/pairing")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["car_rule"]["pattern"] == AAT_RULE
    assert body["paired_cars"] == 10
    assert {p["gap_days"] for p in body["pairs"]} == {0}
    q = {item["kind"]: item for item in body["quality"]}
    assert q["film_no_car_number"]["count"] == 0
    assert q["wavescan_serial_not_7_digits"]["examples"] == ["250727l9"]
    assert q["pair_model_mismatch"]["examples"] == ["2498496", "2508818", "2509087"]
    assert q["pair_colour_mismatch"]["examples"] == ["2507591", "2509087"]
    # Unmapped readings sit only on the zones / panels AR02 leaves out.
    assert q["wavescan_reading_unmapped"]["count"] > 0
    assert set(q["wavescan_reading_unmapped"]["examples"]) <= UNMAPPED_ZONES
    left_out = set().union(*UNMAPPED_PANELS.values())
    assert q["film_reading_unmapped"]["count"] > 0
    assert {p.lstrip("0123456789") for p in q["film_reading_unmapped"]["examples"]} <= left_out

    groups = {g["pair_group"]: g["paired_cars"] for g in body["by_pair_group"]}
    assert sorted(groups) == GROUPS
    assert groups == {
        **dict.fromkeys(["HOOD", "ROOF", "L_FENDER", "R_FENDER", "L_FRONT_DOOR",
                         "R_FRONT_DOOR", "L_REAR_DOOR", "R_REAR_DOOR"], 10),
        **dict.fromkeys(["LIFTGATE", "L_BOX_SIDE", "R_BOX_SIDE", "TAILGATE"], 5),
        **dict.fromkeys(["L_C_PILLAR", "R_C_PILLAR"], 0),
    }


# =====================================================================
# 4. downgrade guard
# =====================================================================
@pytest.mark.parametrize("table", ["ref_pair_ws_zone", "ref_pair_film_point"])
def test_the_downgrade_refuses_while_another_plant_uses_liftgate(admin_dsn, table):
    engine = create_engine(_keyword_dsn_to_url(admin_dsn))
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            m0045.refuse_foreign_liftgate(conn)  # live data: AAT alone uses LIFTGATE
            plant = f"AR02{uuid.uuid4().hex[:6].upper()}"
            conn.execute(text("INSERT INTO ref_plant (plant_code, plant_name, is_active) "
                              "VALUES (:p, 'AR02 rolled-back fixture', true)"), {"p": plant})
            if table == "ref_pair_ws_zone":
                conn.execute(text(
                    "INSERT INTO ref_plant_ws_point (plant_code, model_code, zone_code, point_no, "
                    "tolerance_group) SELECT :p, model_code, zone_code, point_no, tolerance_group "
                    "FROM ref_plant_ws_point WHERE plant_code = 'AAT' AND model_code = 'U704' "
                    "AND zone_code = 'LIFTGATEHILH'"), {"p": plant})
                conn.execute(text("INSERT INTO ref_pair_ws_zone VALUES "
                                  "(:p, 'U704', 'LIFTGATEHILH', 'LIFTGATE')"), {"p": plant})
            else:
                code = conn.execute(text(
                    "SELECT point_code FROM ref_pair_film_point WHERE plant_code = 'AAT' "
                    "AND pair_group = 'LIFTGATE' ORDER BY 1 LIMIT 1")).scalar_one()
                conn.execute(text(
                    "INSERT INTO ref_plant_film_point (plant_code, model_code, point_code, "
                    "point_no, orientation) SELECT :p, model_code, point_code, point_no, "
                    "orientation FROM ref_plant_film_point WHERE plant_code = 'AAT' "
                    "AND model_code = 'U704' AND point_code = :c"), {"p": plant, "c": code})
                conn.execute(text("INSERT INTO ref_pair_film_point VALUES "
                                  "(:p, 'U704', :c, 'LIFTGATE')"), {"p": plant, "c": code})
            with pytest.raises(RuntimeError, match=f"downgrade refused.*{plant}"):
                m0045.refuse_foreign_liftgate(conn)
        finally:
            tx.rollback()
    engine.dispose()
