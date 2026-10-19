"""Comparison reads against PostgreSQL, with all fixture writes rolled back.

The API connection uses SET LOCAL ROLE app_rw after setup. No workbook,
shared seed edit, worker, persistent fixture, or cleanup DELETE is needed.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.deps import get_connection
from app.api.deps import active_measurement_scope
from app.core.config import Settings
from app.domain.film import logical_vehicle_id
from app.domain.workbooks import identity_of, vehicle_id
from app.main import create_app
from app.repositories.measurements import MeasurementFilter
from tests.conftest import _keyword_dsn_to_url

MODEL = "P703 DBL RANGER"
OTHER_MODEL = "P703 DBL RAPTOR"
PRECISE = "62.123456789012345678900"


@pytest.fixture
def data(admin_dsn):
    engine = create_engine(_keyword_dsn_to_url(admin_dsn))
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            plant = "T79" + uuid.uuid4().hex[:8]
            empty = plant + "E"
            active_empty = plant + "A"
            for code, active in ((plant, True), (empty, False), (active_empty, True)):
                conn.execute(text("INSERT INTO ref_plant (plant_code, plant_name, is_active) "
                                  "VALUES (:p, 'T79 transactional fixture', :a)"), {"p": code, "a": active})
            for table in ("ref_plant_ws_point", "ref_plant_film_point"):
                code_col = "zone_code" if table.endswith("ws_point") else "point_code"
                orient_col = "tolerance_group" if table.endswith("ws_point") else "orientation"
                # T83 retired the T54-copied Raptor Film list at FVL (Raptor Film is
                # FTM-only, D-FT-08c), so OTHER_MODEL's Film points come from FTM's live list.
                source = ("(plant_code='FVL' AND model_code=:m) OR (plant_code='FTM' AND model_code=:o)"
                          if table == "ref_plant_film_point"
                          else "plant_code='FVL' AND model_code IN (:m, :o)")
                conn.execute(text(f"INSERT INTO {table} (plant_code, model_code, {code_col}, "
                                  f"point_no, {orient_col}, retired_at) SELECT :p, model_code, "
                                  f"{code_col}, point_no, {orient_col}, retired_at FROM {table} "
                                  f"WHERE ({source}) AND retired_at IS NULL"),
                             {"p": plant, "m": MODEL, "o": OTHER_MODEL})
            # An old zone is a retained FK target, outside the live catalogue.
            conn.execute(text("INSERT INTO ref_plant_ws_point "
                              "(plant_code, model_code, zone_code, point_no, tolerance_group, retired_at, retired_reason) "
                              "VALUES (:p, :m, 'RRHOOD', 1, 'Horizontal', now(), 'T79 old zone') "
                              "ON CONFLICT DO NOTHING"), {"p": plant, "m": MODEL})
            ws_ids, film_ids, loads = {}, {}, []

            def batch(domain, status="COMMITTED"):
                load = conn.execute(text("INSERT INTO load_batch "
                    "(source_file, source_sheet, plant_code, file_hash, raw_store_key, status, domain) "
                    "VALUES (:file, 'Synthetic', :p, :hash, 'unused', :status, :domain) RETURNING load_id"),
                    {"file": f"t79-{uuid.uuid4().hex}.xlsx", "p": plant, "hash": uuid.uuid4().hex * 2,
                     "status": status, "domain": domain}).scalar_one()
                loads.append(load)
                return load

            def ws(name, day, serial, color="Arctic White", model=MODEL, status="COMMITTED", duplicate=False):
                load = batch("WAVESCAN", status)
                for row, zone in enumerate(("1HOOD", "1HOOD", "RRHOOD"), 1):
                    conn.execute(text("INSERT INTO wavescan (measured_date, plant, model, color, "
                        "serial_no, checkzone, tolerance_group, cf, doi, load_id, source_sheet, source_row, "
                        "src_zone_text, is_duplicate) VALUES (:day, :p, :m, :color, :serial, :zone, "
                        "'Horizontal', :value, NULL, :load, 'Synthetic', :row, :label, :dup)"),
                        {"day": day, "p": plant, "m": model, "color": color, "serial": serial,
                         "zone": zone, "value": PRECISE, "load": load, "row": row,
                         "label": f"plant label {row}", "dup": duplicate})
                ws_ids[name] = vehicle_id(load, identity_of({"measured_date": day.isoformat(),
                                     "model": model, "color": color, "serial_no": serial}))

            def film(name, day, serial, job, color="Arctic White", model=MODEL, status="COMMITTED", duplicate=False):
                vid = logical_vehicle_id(plant, day, model, color, job, serial)
                film_ids[name] = vid
                # Film facts are inserted only on commit. Its active view
                # filters fact flags, rather than load_batch.status.
                if status != "COMMITTED":
                    batch("FILMTHICKNESS", status)
                    return
                # A later CLEAR at 002HOOD must not mix into the earlier
                # BASE-only point's membership (the existing Film grid rule).
                for point, layer, row in (("001HOOD", "CLEAR", 1), ("002HOOD", "BASE", 2),
                                          ("002HOOD", "CLEAR", 3)):
                    load = batch("FILMTHICKNESS", status)
                    conn.execute(text("INSERT INTO filmthickness (measured_date, plant, model, color, "
                        "serial_no, job_no, point_code, src_location_text, layer_code, thickness, "
                        "logical_vehicle_id, load_id, source_sheet, source_row, is_duplicate) "
                        "VALUES (:day, :p, :m, :color, :serial, :job, :point, :point, :layer, :value, "
                        ":vid, :load, 'Synthetic', :row, :dup)"),
                        {"day": day, "p": plant, "m": model, "color": color, "serial": serial,
                         "job": job, "point": point, "layer": layer, "value": PRECISE,
                         "vid": vid, "load": load, "row": row, "dup": duplicate})
                film_ids[name] = vid

            for factory in (ws, film):
                extra = {} if factory == ws else {"job": "JOB-A"}
                factory("older", date(2002, 6, 24), "Alpha", **extra)
                factory("newer", date(2002, 7, 3), "Beta", **extra)
                factory("tie", date(2002, 7, 3), "Alpha", color="Traction Green", **extra)
                if factory == ws:
                    factory("blank", date(2002, 7, 3), None)
                    factory("same_serial_other_load", date(2002, 7, 3), "Beta")
                else:
                    factory("blank", date(2002, 7, 3), None, None)
                    factory("job", date(2002, 7, 3), None, "Lexical-Job")
                factory("pending", date(2002, 8, 1), "Pending", status="PENDING_REVIEW", **extra)
                factory("retired", date(2002, 9, 1), "Retired", status="SUPERSEDED", **extra)
                factory("dup", date(2002, 10, 1), "Duplicate", duplicate=True, **extra)
                # Other-model fact uses a valid model/zone tuple.
                if factory == film:
                    factory("other", date(2002, 7, 3), "Other", model=OTHER_MODEL, **extra)

            conn.execute(text("SET LOCAL ROLE app_rw"))
            app = create_app(Settings(env="development", app_database_url="", auth_dev_bypass=True,
                                      auth_dev_bypass_roles_raw="viewer", ingest_worker_enabled=False))
            def connection():
                yield conn
            app.dependency_overrides[get_connection] = connection
            with TestClient(app) as client:
                yield {"client": client, "conn": conn, "plant": plant, "empty": empty,
                       "active_empty": active_empty, "ws": ws_ids, "film": film_ids}
        finally:
            tx.rollback()
    engine.dispose()


def get(data, read="vehicles", domain="WAVESCAN", plant=None, **params):
    return data["client"].get(f"/api/v1/plants/{plant or data['plant']}/comparison/{read}",
                              params={"domain": domain, **params})


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("domain,key", [("WAVESCAN", "ws"), ("FILMTHICKNESS", "film")])
def test_picker_cross_month_options_filters_order_and_paging(data, domain, key):
    initial = ok(get(data, domain=domain))
    assert initial["default_month"] == "2002-07"
    assert initial["available_months"] == ["2002-07", "2002-06"]
    assert initial["selected_months"] == ["2002-07"]
    assert initial["items"] == initial["color_options"] == initial["week_options"] == []
    params = {"month": ["2002-06", "2002-07"], "model": MODEL}
    body = ok(get(data, domain=domain, **params))
    assert body["week_options"] == [{"month": "2002-07", "week": 1}, {"month": "2002-06", "week": 4}]
    assert body["color_options"] == ["Arctic White", "Traction Green"]
    serials = [v["serial_no"] for v in body["items"]]
    assert serials[:3] == (["Alpha", "Beta", "Beta"] if key == "ws" else ["Alpha", "Beta", None])
    assert serials[-2:] == [None, "Alpha"]
    beta = [v["vehicle_id"] for v in body["items"] if v["serial_no"] == "Beta"]
    assert beta == sorted(beta)
    blank = next(v for v in body["items"] if v["vehicle_id"] == data[key]["blank"])
    assert blank["serial_no"] is None
    # T39 permits a blank WaveScan serial: retain the current History meaning.
    assert blank["identity_complete"] is (key == "ws")
    cross = ok(get(data, domain=domain, **params, period=["2002-06-W4", "2002-07-W1"], q="  ALpHa  "))
    assert [v["vehicle_id"] for v in cross["items"]] == [data[key]["tie"], data[key]["older"]]
    filtered = ok(get(data, domain=domain, **params, color=["Arctic White"], period=["2002-06-W4"]))
    assert [v["vehicle_id"] for v in filtered["items"]] == [data[key]["older"]]
    assert filtered["week_options"] == body["week_options"] and filtered["color_options"] == body["color_options"]
    page = ok(get(data, domain=domain, **params, limit=2, offset=1))
    assert page["items"] == body["items"][1:3]
    assert page["page"] == {"limit": 2, "offset": 1, "total": 5, "returned": 2}
    assert ok(get(data, domain=domain, **params, q=data[key]["newer"]))["items"] == []
    assert ok(get(data, domain=domain, **params, q="   "))["page"]["total"] == 5
    if key == "film":
        job = ok(get(data, domain=domain, **params, q="lexical-job"))["items"]
        assert [v["vehicle_id"] for v in job] == [data[key]["job"]]
        assert job[0]["week"] == 1 and job[0]["job_nos"] == ["Lexical-Job"]
        assert len(job[0]["load_ids"]) == len(job[0]["source_files"]) == 3
        assert job[0]["source_file"] is None


@pytest.mark.parametrize("domain,key,metric", [("WAVESCAN", "ws", "cf"), ("FILMTHICKNESS", "film", "clear")])
def test_full_grid_missing_duplicates_unaligned_and_exact_decimals(data, domain, key, metric):
    ids = [data[key]["older"], data[key]["newer"]]
    body = ok(get(data, "points", domain, model=MODEL, metric=metric, vehicle_id=ids))
    assert [v["vehicle_id"] for v in body["columns"]] == ids
    locations = body["locations"]
    assert [(p["point_no"], p["code"]) for p in locations] == sorted((p["point_no"], p["code"]) for p in locations)
    assert len(locations) == (32 if key == "ws" else 94)
    assert [c["vehicle_id"] for c in locations[0]["cells"]] == ids
    for cell in locations[0]["cells"]:
        assert cell["missing"] is False
        assert [r["value"] for r in cell["readings"]] == [PRECISE] * (2 if key == "ws" else 1)
    assert all(c["missing"] and c["readings"] == [] for p in locations[1:] for c in p["cells"])
    if key == "ws":
        assert [p["checkzone"] for p in body["unaligned_locations"]] == ["RRHOOD", "RRHOOD"]
        assert [p["vehicle_id"] for p in body["unaligned_locations"]] == ids
        # T94 (D-94-4): panel_label is the stored position, the long name.
        assert all(p["reading"]["value"] == PRECISE and p["reading"]["panel_label"] == p["checkzone"]
                   for p in body["unaligned_locations"])
        assert all(c["missing"] for p in ok(get(data, "points", domain, model=MODEL, metric="doi", vehicle_id=ids))["locations"] for c in p["cells"])
    else:
        assert body["unaligned_locations"] == []
        assert locations[1]["cells"][0]["missing"]  # BASE exists but CLEAR does not.


@pytest.mark.parametrize("domain,key", [("WAVESCAN", "ws"), ("FILMTHICKNESS", "film")])
def test_empty_unknown_active_membership_and_validation(data, domain, key):
    empty = ok(get(data, domain=domain, plant=data["empty"]))
    assert empty["plant_is_active"] is False and empty["items"] == empty["available_months"] == []
    assert ok(get(data, domain=domain, plant=data["empty"], model=MODEL))["items"] == []
    assert ok(get(data, domain=domain, plant=data["active_empty"], month="2002-07", model=MODEL))["items"] == []
    assert get(data, domain=domain, plant="no-such-plant").status_code == 404
    for params in ({"period": "2002-06-W4"}, {"month": "2002-13"}, {"month": "0000-01"},
                   {"period": "2002-07-W6"}, {"limit": 101}, {"limit": 0}, {"offset": -1},
                   {"model": "no-such-model"}):
        assert get(data, domain=domain, **params).status_code == 422
    ids = data[key]
    metric = "cf" if key == "ws" else "clear"
    for name in ("pending", "retired", "dup"):
        resp = get(data, "points", domain, model=MODEL, metric=metric, vehicle_id=[ids[name]])
        assert resp.status_code == 404 and set(resp.json()) == {"statusCode", "error", "message", "correlationId"}
    for plant, model, vid in ((data["empty"], MODEL, ids["newer"]),
                              (None, OTHER_MODEL, ids["newer"]),
                              (None, MODEL, data["film" if key == "ws" else "ws"]["newer"])):
        assert get(data, "points", domain, plant=plant, model=model, metric=metric, vehicle_id=[vid]).status_code == 404
    for params in ({"vehicle_id": [ids["newer"]] * 2}, {"vehicle_id": [f"{i:064x}" for i in range(9)]},
                   {"vehicle_id": [ids["newer"]], "metric": "clear" if key == "ws" else "cf"},
                   {"vehicle_id": []}):
        assert get(data, "points", domain, **{"model": MODEL, "metric": metric, **params}).status_code == 422
    assert get(data, "points", domain, model=MODEL, metric=metric,
               vehicle_id=[ids["newer"], ids["pending"]]).status_code == 404


def test_eight_ids_are_accepted_in_caller_order_and_scope_is_enforced(data):
    conn = data["conn"]
    base = ok(get(data, model=MODEL, month=["2002-06", "2002-07"]))["items"]
    conn.execute(text("RESET ROLE"))
    load = base[0]["load_id"]
    extra = []
    for i in range(3):
        serial = f"Eight-{i}"
        conn.execute(text("INSERT INTO wavescan (measured_date, plant, model, color, serial_no, "
                          "checkzone, tolerance_group, cf, load_id, source_sheet, source_row) "
                          "VALUES ('2002-07-03', :p, :m, 'Arctic White', :serial, '1HOOD', "
                          "'Horizontal', 0, :load, 'Synthetic', :row)"),
                     {"p": data["plant"], "m": MODEL, "serial": serial, "load": load, "row": 100+i})
        extra.append(vehicle_id(load, identity_of({"measured_date": "2002-07-03", "model": MODEL,
                                                  "color": "Arctic White", "serial_no": serial})))
    conn.execute(text("SET LOCAL ROLE app_rw"))
    ids = list(reversed([v["vehicle_id"] for v in base] + extra))
    body = ok(get(data, "points", model=MODEL, metric="cf", vehicle_id=ids))
    assert len(ids) == 8 and [c["vehicle_id"] for c in body["columns"]] == ids
    assert all([c["vehicle_id"] for c in p["cells"]] == ids for p in body["locations"])
    assert body["locations"][0]["cells"][0]["readings"][0]["value"] == "0"
    assert body["locations"][0]["cells"][0]["missing"] is False
    app = data["client"].app
    app.dependency_overrides[active_measurement_scope] = lambda: MeasurementFilter(plant_scope=[])
    assert ok(get(data))["available_months"] == []
    assert get(data, "points", model=MODEL, metric="cf", vehicle_id=[ids[0]]).status_code == 404


def test_gets_are_read_only_for_every_history_role(data):
    tables = ("wavescan", "filmthickness", "load_batch", "audit_event", "app_user", "stg_review_row")
    def counts():
        return [data["conn"].execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in tables]
    before = counts()
    for role in ("viewer", "engineer", "admin"):
        data["client"].app.state.settings.auth_dev_bypass_roles_raw = role
        for domain, key, metric in (("WAVESCAN", "ws", "cf"), ("FILMTHICKNESS", "film", "clear")):
            ok(get(data, domain=domain, month=["2002-06", "2002-07"], model=MODEL))
            ok(get(data, "points", domain, model=MODEL, metric=metric, vehicle_id=[data[key]["newer"]]))
    assert counts() == before
    assert get(data, domain="INVALID").status_code == 422
    data["client"].app.state.settings.auth_dev_bypass = False
    assert get(data).status_code == 401


def test_generated_comparison_contract():
    root = Path(__file__).resolve().parents[1]
    backend = (root / "openapi.json").read_bytes()
    assert backend == (root.parent / "docs/openapi.json").read_bytes()
    spec = json.loads(backend)
    for name in ("vehicles", "points"):
        assert f"/api/v1/plants/{{plant_code}}/comparison/{name}" in spec["paths"]
    for name, schema in spec["components"]["schemas"].items():
        if name.startswith("Comparison"):
            assert all(field.get("description") for field in schema.get("properties", {}).values()), name
