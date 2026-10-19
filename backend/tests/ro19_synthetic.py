"""RO19 reference fixtures. Each test owns a fresh plant and every removed row.

Worker tests need committed reference rows. Batches are removed by their exact
IDs before the owned plant's references; no production plant is changed.
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_t04_ingest import _forget_batches
from tests.test_t46_filmthickness import _wait_for_idle_jobs

RANGER = "P703 DBL RANGER"
POINTS = ("001HOOD", "002HOOD", "003HOOD")


@pytest.fixture()
def ro19_plants(admin_conn):
    owned = []
    point_codes = []

    def make(lists=None, *, ruled=False, colours=("Command Grey", "Pace Red", "Absolute / Shadow Black")):
        plant = "ZR19_" + uuid.uuid4().hex[:12].upper()
        owned.append(plant)
        lists = lists or {RANGER: POINTS}
        with admin_conn.cursor() as cur:
            cur.execute("INSERT INTO ref_plant (plant_code, plant_name, requires_serial, is_active) "
                        "VALUES (%s, 'RO19 synthetic fixture', false, true)", (plant,))
            cur.execute("INSERT INTO ref_plant_alias (raw_value, plant_code) VALUES (%s, %s)", (plant, plant))
            for colour in colours:
                cur.execute("INSERT INTO ref_plant_color (plant_code, color_name, family_name) "
                            "SELECT %s, color_name, family_name FROM ref_plant_color "
                            "WHERE color_name = %s ORDER BY plant_code LIMIT 1", (plant, colour))
                assert cur.rowcount == 1, f"missing fixture colour {colour}"
            for model, points in lists.items():
                cur.execute("INSERT INTO ref_plant_model (plant_code, model_code, is_offered) "
                            "VALUES (%s, %s, true)", (plant, model))
                token = {RANGER: "P703", "J73 DBL": "J73"}.get(model, model)
                cur.execute("INSERT INTO ref_film_model_alias (plant_code, raw_token, model_code) "
                            "VALUES (%s, %s, %s)", (plant, token, model))
                for no, code in enumerate(points, 1):
                    cur.execute("INSERT INTO ref_film_point (point_code) VALUES (%s) "
                                "ON CONFLICT DO NOTHING RETURNING point_code", (code,))
                    created = cur.fetchone()
                    if created:
                        point_codes.append(created[0])
                    cur.execute("INSERT INTO ref_plant_film_point "
                                "(plant_code, model_code, point_code, point_no, orientation) "
                                "VALUES (%s, %s, %s, %s, 'H')", (plant, model, code, no))
                    cur.execute("INSERT INTO ref_plant_film_point_label "
                                "(plant_code, model_code, point_code, label, label_norm, reason) "
                                "VALUES (%s, %s, %s, %s, %s, 'RO19 synthetic')", (plant, model, code, code, code))
                    if ruled:
                        cur.execute("INSERT INTO film_point_setting "
                                    "(plant_code, model_code, point_code, counted, orientation, reason) "
                                    "VALUES (%s, %s, %s, true, 'H', 'RO19 synthetic')", (plant, model, code))
        return plant

    # Tests that introduce a UUID-bearing point through the application can
    # register that exact code for cleanup after their owned list is gone.
    make.track_code = point_codes.append
    try:
        yield make
    finally:
        for plant in reversed(owned):
            with admin_conn.cursor() as cur:
                cur.execute("SELECT load_id FROM load_batch WHERE plant_code = %s", (plant,))
                ids = [row[0] for row in cur.fetchall()]
            if ids:
                _wait_for_idle_jobs(admin_conn, ids)
            with admin_conn.cursor() as cur:
                if ids:
                    cur.execute("DELETE FROM filmthickness WHERE load_id = ANY(%s)", (ids,))
                    cur.execute("DELETE FROM worksheet_decision WHERE load_id = ANY(%s)", (ids,))
                    _forget_batches(cur, ids)
                cur.execute("SELECT file_hash FROM workbook_upload WHERE plant_code = %s", (plant,))
                own_workbooks = [f"{plant}:{row[0]}" for row in cur.fetchall()]
                if own_workbooks:
                    cur.execute("DELETE FROM audit_event WHERE entity_type = 'workbook_upload' "
                                "AND entity_id = ANY(%s)", (own_workbooks,))
                cur.execute("DELETE FROM workbook_upload WHERE plant_code = %s", (plant,))
                cur.execute("SELECT version_id FROM point_walk_version WHERE plant_code = %s", (plant,))
                own_versions = [row[0] for row in cur.fetchall()]
                if own_versions:
                    cur.execute("DELETE FROM audit_event WHERE entity_type = 'point_walk_version' "
                                "AND entity_id = ANY(%s)", ([str(v) for v in own_versions],))
                cur.execute("DELETE FROM point_walk_member WHERE version_id IN "
                            "(SELECT version_id FROM point_walk_version WHERE plant_code = %s)", (plant,))
                cur.execute("DELETE FROM point_walk_version WHERE plant_code = %s", (plant,))
                cur.execute("DELETE FROM audit_event WHERE entity_id = %s "
                            "OR left(entity_id, length(%s) + 1) = %s || ':'", (plant, plant, plant))
                for table in ("film_standard", "film_point_setting", "ref_film_point_alias",
                              "ref_film_location_map", "ref_plant_film_tail_label",
                              "ref_plant_film_point_label", "ref_plant_film_point",
                              "ref_film_model_alias", "ref_plant_model", "ref_plant_color", "ref_plant_alias"):
                    cur.execute(f"DELETE FROM {table} WHERE plant_code = %s", (plant,))
                cur.execute("DELETE FROM ref_plant WHERE plant_code = %s", (plant,))
        with admin_conn.cursor() as cur:
            for code in point_codes:
                cur.execute("DELETE FROM ref_film_point WHERE point_code = %s", (code,))
