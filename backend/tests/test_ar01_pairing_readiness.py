"""AR01: Wave Scan <-> Film pairing readiness (migration 0043 + one GET).

Every write is in one owner transaction that is always rolled back (marker
plants, marker loads and marker facts); nothing is deleted. The migration
checks read the live reference tables only.
"""

from __future__ import annotations

import uuid
from datetime import date
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
SOURCES = [ROOT / "app/repositories/pairing.py", ROOT / "app/services/pairing.py"]
TABLES = ("ref_plant_film_car_rule", "ref_pair_ws_zone", "ref_pair_film_point")
RANGER, RAPTOR = "P703 DBL RANGER", "P703 DBL RAPTOR"
WHITE, GREY = "Arctic White", "Command Grey"
FTM_RULE = r"^[A-Z]{2}_[A-Z]{2,3}_(\d{7})$"

#: Live FTM film points per model with no pair group (AR01 section 2), measured 2026-10-12.
UNMAPPED_FILM = {
    "021LAPILLAR", "022LAPILLAR", "056RAPILLAR", "057RAPILLAR", "063RAPILLAR", "064RAPILLAR",
    "086RBXFRONT", "087RBXFRONT", "088LBXFRONT", "089LBXFRONT", "090LBXFLOOR", "091LBXFLOOR",
    "092LBXFLOOR", "093RBXFLOOR", "094RBXFLOOR", "095RBXFLOOR",
    "096TGATEIN", "097TGATEIN", "098TGATEIN",
}
FORBIDDEN = ("rate", "pct", "percent", "score", "status", "grade")


# =====================================================================
# 1. migration (live reference tables, read only)
# =====================================================================
def test_the_three_tables_hold_the_seed(admin_conn):
    with admin_conn.cursor() as cur:
        counts = {}
        for table in TABLES:
            cur.execute(f"SELECT count(*) FROM {table} WHERE plant_code = 'FTM'")
            counts[table] = cur.fetchone()[0]
        assert counts == {"ref_plant_film_car_rule": 1, "ref_pair_ws_zone": 64,
                          "ref_pair_film_point": 158}
        cur.execute("SELECT pattern FROM ref_plant_film_car_rule WHERE plant_code = 'FTM'")
        assert cur.fetchone()[0] == FTM_RULE
        cur.execute(
            "SELECT model_code, pair_group FROM ref_pair_ws_zone "
            " WHERE plant_code = 'FTM' AND zone_code = 'FTFDOOR' ORDER BY 1"
        )
        assert cur.fetchall() == [(RANGER, "R_FRONT_DOOR"), (RAPTOR, "R_FRONT_DOOR")]
        cur.execute(
            "SELECT count(*) FROM ref_pair_film_point "
            " WHERE plant_code = 'FTM' AND point_code LIKE '%TGATEIN'"
        )
        assert cur.fetchone()[0] == 0
        for model in (RANGER, RAPTOR):
            cur.execute(
                "SELECT p.point_code FROM ref_plant_film_point p "
                "  LEFT JOIN ref_pair_film_point m USING (plant_code, model_code, point_code) "
                " WHERE p.plant_code = 'FTM' AND p.model_code = %s "
                "   AND p.retired_at IS NULL AND m.point_code IS NULL",
                (model,),
            )
            assert {r[0] for r in cur.fetchall()} == UNMAPPED_FILM, model
            cur.execute(
                "SELECT count(*) FROM ref_plant_ws_point p "
                "  LEFT JOIN ref_pair_ws_zone z USING (plant_code, model_code, zone_code) "
                " WHERE p.plant_code = 'FTM' AND p.model_code = %s "
                "   AND p.retired_at IS NULL AND z.zone_code IS NULL",
                (model,),
            )
            assert cur.fetchone()[0] == 0, model


def test_the_app_role_may_only_select(app_conn):
    with app_conn.cursor() as cur:
        for table in TABLES:
            cur.execute(f"SELECT count(*) FROM {table}")
            for statement in (
                f"UPDATE {table} SET plant_code = plant_code",
                f"DELETE FROM {table}",
                f"INSERT INTO {table} SELECT * FROM {table} LIMIT 0",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with app_conn.transaction():
                        cur.execute(statement)


def test_the_source_selects_only_and_reads_the_active_views():
    for path in SOURCES:
        source = path.read_text(encoding="utf-8")
        for word in ("UPDATE", "DELETE", "INSERT"):
            assert word not in source, (path.name, word)
        assert "v_wavescan_counted" not in source and "COUNTED_VIEW" not in source
    repo = SOURCES[0].read_text(encoding="utf-8")
    assert '"v_wavescan_active"' in repo and '"filmthickness_active"' in repo


def test_the_car_rule_reads_only_the_ftm_shape(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT substring(v FROM r.pattern) FROM ref_plant_film_car_rule r, "
            "unnest(ARRAY['AW_RB_1970561','AW_RB_197056','AWX_RB_1970561','aw_rb_1970561']) "
            "WITH ORDINALITY AS t(v, n) WHERE r.plant_code = 'FTM' ORDER BY n"
        )
        assert [r[0] for r in cur.fetchall()] == ["1970561", None, None, None]


# =====================================================================
# marker plants, one rolled-back transaction
# =====================================================================
@pytest.fixture
def data(admin_dsn):
    engine = create_engine(_keyword_dsn_to_url(admin_dsn))
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            tag = uuid.uuid4().hex[:6].upper()
            marked, bare, clean = f"AR01{tag}", f"AR01{tag}N", f"AR01{tag}C"
            for code in (marked, bare, clean):
                conn.execute(text("INSERT INTO ref_plant (plant_code, plant_name, is_active) "
                                  "VALUES (:p, 'AR01 rolled-back fixture', true)"), {"p": code})
                # The live FTM lists of both models, so every FK holds.
                conn.execute(text(
                    "INSERT INTO ref_plant_ws_point (plant_code, model_code, zone_code, point_no, "
                    "tolerance_group) SELECT :p, model_code, zone_code, point_no, tolerance_group "
                    "FROM ref_plant_ws_point WHERE plant_code = 'FTM' AND model_code IN (:a, :b) "
                    "AND retired_at IS NULL"), {"p": code, "a": RANGER, "b": RAPTOR})
                conn.execute(text(
                    "INSERT INTO ref_plant_film_point (plant_code, model_code, point_code, point_no, "
                    "orientation) SELECT :p, model_code, point_code, point_no, orientation "
                    "FROM ref_plant_film_point WHERE plant_code = 'FTM' AND model_code IN (:a, :b) "
                    "AND retired_at IS NULL"), {"p": code, "a": RANGER, "b": RAPTOR})
            conn.execute(text("INSERT INTO ref_plant_alias (raw_value, plant_code) VALUES (:a, :p)"),
                         {"a": f"ar01-alias-{tag}", "p": marked})
            for code in (marked, clean):
                conn.execute(text("INSERT INTO ref_plant_film_car_rule (plant_code, pattern, note) "
                                  "SELECT :p, pattern, 'AR01 fixture' FROM ref_plant_film_car_rule "
                                  "WHERE plant_code = 'FTM'"), {"p": code})
            for code in (marked, bare, clean):
                # FTM's map; the marked plant leaves RRHOOD out, so a reading there is unmapped.
                skip = "RRHOOD" if code == marked else ""
                conn.execute(text("INSERT INTO ref_pair_ws_zone SELECT :p, model_code, zone_code, "
                                  "pair_group FROM ref_pair_ws_zone WHERE plant_code = 'FTM' "
                                  "AND zone_code <> :skip"), {"p": code, "skip": skip})
                conn.execute(text("INSERT INTO ref_pair_film_point SELECT :p, model_code, point_code, "
                                  "pair_group FROM ref_pair_film_point WHERE plant_code = 'FTM'"),
                             {"p": code})
            tolerance = dict(conn.execute(text(
                "SELECT zone_code, tolerance_group FROM ref_plant_ws_point "
                "WHERE plant_code = :p AND model_code = :m"), {"p": marked, "m": RANGER}).all())

            def batch(plant, domain):
                return conn.execute(text(
                    "INSERT INTO load_batch (source_file, source_sheet, plant_code, file_hash, "
                    "raw_store_key, status, domain) VALUES (:f, 'AR01', :p, :h, 'unused', "
                    "'COMMITTED', :d) RETURNING load_id"),
                    {"f": f"ar01-{uuid.uuid4().hex}.xlsx", "p": plant, "h": uuid.uuid4().hex * 2,
                     "d": domain}).scalar_one()

            def ws(plant, serial, day, zones=("LCFENDER",), model=RANGER, color=WHITE):
                load = batch(plant, "WAVESCAN")
                for row, zone in enumerate(zones, 1):
                    conn.execute(text(
                        "INSERT INTO wavescan (measured_date, plant, model, color, serial_no, "
                        "checkzone, tolerance_group, cf, load_id, source_sheet, source_row) "
                        "VALUES (:d, :p, :m, :c, :s, :z, :t, 60, :l, 'AR01', :r)"),
                        {"d": day, "p": plant, "m": model, "c": color, "s": serial, "z": zone,
                         "t": tolerance[zone], "l": load, "r": row})

            def film(plant, job, day, points=("016LTFEND",), model=RANGER, color=WHITE):
                load = batch(plant, "FILMTHICKNESS")
                for row, point in enumerate(points, 1):
                    conn.execute(text(
                        "INSERT INTO filmthickness (measured_date, plant, model, color, job_no, "
                        "point_code, src_location_text, layer_code, thickness, logical_vehicle_id, "
                        "load_id, source_sheet, source_row) VALUES (:d, :p, :m, :c, :j, :pt, :pt, "
                        "'CLEAR', 40, :j, :l, 'AR01', :r)"),
                        {"d": day, "p": plant, "m": model, "c": color, "j": job, "pt": point,
                         "l": load, "r": row})

            d = date(2099, 1, 10)
            # in both -> paired, gap 0, L_FENDER
            ws(marked, "7000001", d)
            film(marked, "AW_DBL_7000001", d)
            # WS only / film only -> not paired
            ws(marked, "7000002", d)
            film(marked, "AW_DBL_7000003", d)
            # model and colour disagree -> paired and flagged
            ws(marked, "7000004", d)
            film(marked, "AW_RB_7000004", d, model=RAPTOR)
            ws(marked, "7000005", d)
            film(marked, "AW_DBL_7000005", d, color=GREY)
            # one serial on two WS dates -> one pair, the smallest gap (1 day)
            ws(marked, "7000006", date(2099, 1, 1))
            ws(marked, "7000006", date(2099, 1, 12))
            film(marked, "AW_DBL_7000006", date(2099, 1, 11))
            # WS on the tailgate, film only on TGATEIN -> TAILGATE not paired
            ws(marked, "7000007", d, zones=("LTTAILGATE",))
            film(marked, "AW_DBL_7000007", d, points=("096TGATEIN",))
            # quality markers
            film(marked, "NOT-A-JOB", d)
            ws(marked, "12345678", d, zones=("RRHOOD",))
            # no rule: same car on both sides, nothing paired
            ws(bare, "7000001", d)
            film(bare, "AW_DBL_7000001", d)
            # clean: one agreeing pair, nothing to report
            ws(clean, "7000001", d)
            film(clean, "AW_DBL_7000001", d)

            conn.execute(text("SET LOCAL ROLE app_rw"))
            app = create_app(Settings(env="development", app_database_url="", auth_dev_bypass=True,
                                      auth_dev_bypass_roles_raw="viewer", ingest_worker_enabled=False))

            def connection():
                yield conn
            app.dependency_overrides[get_connection] = connection
            with TestClient(app) as client:
                yield {"client": client, "marked": marked, "bare": bare, "clean": clean, "tag": tag}
        finally:
            tx.rollback()
    engine.dispose()


def readiness(data, plant):
    response = data["client"].get(f"/api/v1/plants/{plant}/analysis/pairing")
    assert response.status_code == 200, response.text
    return response.json()


def quality(body) -> dict[str, dict]:
    return {q["kind"]: q for q in body["quality"]}


# =====================================================================
# 2-5. car rule, pairs, groups, quality
# =====================================================================
def test_pairs_follow_the_car_number_and_keep_disagreements_flagged(data):
    body = readiness(data, data["marked"])
    pairs = {p["car_no"]: p for p in body["pairs"]}
    assert set(pairs) == {"7000001", "7000004", "7000005", "7000006", "7000007"}
    assert body["paired_cars"] == 5
    assert body["wavescan_cars"] == 7 and body["film_cars"] == 6
    assert pairs["7000001"]["gap_days"] == 0 and pairs["7000001"]["flags"] == []
    assert pairs["7000004"]["flags"] == ["model_mismatch"]
    assert (pairs["7000004"]["wavescan_model"], pairs["7000004"]["film_model"]) == (RANGER, RAPTOR)
    assert pairs["7000005"]["flags"] == ["colour_mismatch"]
    assert (pairs["7000005"]["wavescan_color"], pairs["7000005"]["film_color"]) == (WHITE, GREY)
    assert pairs["7000006"]["wavescan_dates"] == ["2099-01-01", "2099-01-12"]
    assert pairs["7000006"]["film_dates"] == ["2099-01-11"]
    assert pairs["7000006"]["gap_days"] == 1
    assert body["car_rule"]["pattern"] == FTM_RULE


def test_groups_count_a_car_only_where_both_domains_have_a_mapped_reading(data):
    groups = {g["pair_group"]: g for g in readiness(data, data["marked"])["by_pair_group"]}
    assert len(groups) == 13
    # 7000001 and 7000006 (both on LCFENDER / 016LTFEND, models agree); 7000004 and
    # 7000005 too: a group needs a mapped reading on each side, not agreement.
    assert groups["L_FENDER"]["paired_cars"] == 4
    assert groups["TAILGATE"]["paired_cars"] == 0
    assert groups["L_FENDER"]["wavescan_zones"] == ["LCFENDER", "LFFENDER", "LRFENDER"]
    assert groups["L_FENDER"]["film_points"] == 5
    assert groups["R_FRONT_DOOR"]["wavescan_zones"] == ["FTFDOOR", "RCFDOOR"]


def test_model_colour_rows_count_pairs_where_both_domains_agree(data):
    rows = {(r["model"], r["color"]): r for r in readiness(data, data["marked"])["by_model_colour"]}
    assert set(rows) == {(RANGER, WHITE), (RAPTOR, WHITE), (RANGER, GREY)}
    assert rows[(RANGER, WHITE)]["paired_cars"] == 3  # 7000001, 7000006, 7000007
    assert rows[(RAPTOR, WHITE)] == {"model": RAPTOR, "color": WHITE, "wavescan_cars": 0,
                                     "film_cars": 1, "paired_cars": 0}


def test_every_quality_kind_is_produced_by_a_marker(data):
    q = quality(readiness(data, data["marked"]))
    assert q["film_no_car_number"] == {"kind": "film_no_car_number", "count": 1,
                                       "examples": ["NOT-A-JOB"]}
    assert q["wavescan_serial_not_7_digits"]["examples"] == ["12345678"]
    assert q["film_colour_code_shared"]["count"] == 1
    assert q["film_colour_code_shared"]["examples"] == [
        f"AW: {WHITE} (5), {GREY} (AW_DBL_7000005)"]
    assert q["pair_model_mismatch"]["examples"] == ["7000004"]
    assert q["pair_colour_mismatch"]["examples"] == ["7000005"]
    assert q["wavescan_reading_unmapped"] == {"kind": "wavescan_reading_unmapped", "count": 1,
                                              "examples": ["RRHOOD"]}
    assert q["film_reading_unmapped"] == {"kind": "film_reading_unmapped", "count": 1,
                                          "examples": ["096TGATEIN"]}


def test_every_kind_is_present_with_zero_when_clean(data):
    body = readiness(data, data["clean"])
    assert body["paired_cars"] == 1 and body["pairs"][0]["flags"] == []
    assert [(q["kind"], q["count"], q["examples"]) for q in body["quality"]] == [
        (kind, 0, []) for kind in (
            "film_no_car_number", "wavescan_serial_not_7_digits", "film_colour_code_shared",
            "pair_model_mismatch", "pair_colour_mismatch", "wavescan_reading_unmapped",
            "film_reading_unmapped")]


def test_a_plant_with_no_rule_pairs_nothing_and_lists_every_job(data):
    body = readiness(data, data["bare"])
    assert body["car_rule"] is None
    assert body["paired_cars"] == 0 and body["film_cars"] == 0 and body["pairs"] == []
    assert body["wavescan_cars"] == 1
    assert quality(body)["film_no_car_number"]["examples"] == ["AW_DBL_7000001"]
    assert all(g["paired_cars"] == 0 for g in body["by_pair_group"])


# =====================================================================
# 7. API
# =====================================================================
def test_the_plant_resolves_by_alias_and_case_and_unknown_is_404(data):
    client = data["client"]
    assert readiness(data, f"ar01-alias-{data['tag']}")["plant_code"] == data["marked"]
    assert readiness(data, data["marked"].lower())["plant_code"] == data["marked"]
    assert readiness(data, "ftm")["plant_code"] == "FTM"
    missing = client.get("/api/v1/plants/NOWHERE-AR01/analysis/pairing")
    assert missing.status_code == 404
    assert "No plant 'NOWHERE-AR01'" in missing.json()["message"]


def test_every_role_reads_the_same_counts(data):
    paired = []
    for role in ("viewer", "engineer", "admin"):
        data["client"].app.state.settings.auth_dev_bypass_roles_raw = role
        paired.append(readiness(data, data["marked"])["paired_cars"])
    assert paired == [5, 5, 5]


def test_no_response_key_is_a_rate_score_status_or_grade(data):
    spec = data["client"].app.openapi()
    schemas = spec["components"]["schemas"]
    names = ["PairingReadinessOut", "CarRuleOut", "ModelColourCount", "PairGroupCount",
             "PairOut", "QualityItem"]
    keys = [key for name in names for key in schemas[name]["properties"]]
    assert keys and not [k for k in keys if any(word in k.lower() for word in FORBIDDEN)]
    assert "/api/v1/plants/{plant_code}/analysis/pairing" in spec["paths"]
