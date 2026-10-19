"""T37 -- plant x family Ford/Min and the workbook purge (ADR 0011, ADR 0012).

Claims, each against the running application and the database:

* ``cf_standard.plant_code`` exists, is nullable, and the seed stays NULL.
* ``POST /standards`` requires a plant and appends H+V for that plant only.
  Publishing Medium Solids at FTM does not move AAT.
* Monthly Overview uses the newest plant row for **every** month: a row with
  a September ``effective_from`` grades June. A plant row beats a newer
  NULL-plant row. A COLOR row still beats FAMILY.
* ``POST /plants/{plant}/workbooks/{hash}/purge`` deletes that hash's rows
  only, writes ``workbook.purge`` first, is a 404 the second time, and the
  identical bytes then upload as a new batch.
* ``app_rw`` still cannot ``DELETE FROM wavescan`` or ``load_batch`` (T01).

Every row is created by the test that asserts on it. Numbers compared are
read back from the API or the table, not restated as CF constants.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from tests.test_t04_ingest import (
    forget_bytes,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)
from tests.test_t04_ingest import cleanup  # noqa: F401

pytestmark = pytest.mark.ingest


# Module-scoped on purpose (T39): the T04 client fixtures are session-scoped
# and every module that imports them keeps its own apps, pools and worker
# until the session ends. The standing cluster allows 60 connections, so this
# module releases its clients when it finishes instead.
@pytest.fixture(scope="module")
def ingest_apps(app_database_url: str):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.test_t04_ingest import _settings

    created = []

    def _make(**overrides):
        app = create_app(_settings(app_database_url, **overrides))
        client = TestClient(app)
        client.__enter__()
        created.append((client, app))
        return client

    yield _make
    for client, app in created:
        client.__exit__(None, None, None)
        app.state.database.dispose()


@pytest.fixture(scope="module")
def engineer(ingest_apps):
    return ingest_apps()


@pytest.fixture(scope="module")
def viewer(ingest_apps):
    return ingest_apps(auth_dev_bypass_roles_raw="viewer", ingest_worker_enabled=False)


@pytest.fixture(scope="module")
def admin(ingest_apps):
    return ingest_apps(auth_dev_bypass_roles_raw="admin", ingest_worker_enabled=False)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
NOTE = "pytest-t37"
SENTINEL = "T37"
MODEL = "P703 DBL RANGER"
#: Medium Solids at both AAT and FTM (0014 plant map).
MS_COLOR = "Command Grey"
FAMILY = "Medium Solids"


# =====================================================================
# helpers
# =====================================================================
def _note() -> str:
    return f"{NOTE}-{uuid.uuid4().hex[:12]}"


def _forget_standards(admin_conn, note: str) -> None:
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM cf_standard WHERE source_note = %s", (note,))


def _publish(client, plant: str, note: str, *, ford_h, ford_v, min_h, min_v,
             effective_from: str = "2026-09-23", family_code: str = "MS"):
    return client.post(
        "/api/v1/standards",
        json={
            "plant_code": plant,
            "family_code": family_code,
            "ford_h": ford_h,
            "ford_v": ford_v,
            "min_h": min_h,
            "min_v": min_v,
            "effective_from": effective_from,
            "source_note": note,
        },
    )


def _batch(cur, tag: str, plant: str) -> int:
    digest = hashlib.sha256(f"{SENTINEL}:{tag}:{uuid.uuid4().hex}".encode()).hexdigest()
    cur.execute(
        """
        INSERT INTO load_batch (
            source_file, source_sheet, plant_code, file_hash, status,
            rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
            rows_quarantine, raw_store_key, finished_at, notes)
        VALUES (%s, 'Sheet1', %s, %s, 'COMMITTED', 2, 2, 0, 0, 0, %s, now(), %s)
        RETURNING load_id
        """,
        (f"{SENTINEL} {tag}.xlsx", plant, digest, f"wavescan/raw/{digest}",
         f"{SENTINEL} fixture"),
    )
    return cur.fetchone()[0]


def _rows(cur, load_id: int, plant: str, measured: str, color: str = MS_COLOR) -> None:
    for i, (zone, group) in enumerate(
        (("RRHOOD", "Horizontal"), ("LTFDOOR", "Vertical")), start=1
    ):
        cur.execute(
            """
            INSERT INTO wavescan (
                measured_date, plant, model, checkzone, color, tolerance_group,
                paintline, serial_no,
                lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
                load_id, source_sheet, source_row)
            VALUES (%s, %s, %s, %s, %s, %s, 'BOOTH1', %s,
                    1, 2, 60, 80, 3, 4, 5, 6, 7, 8, 0,
                    %s, 'Sheet1', %s)
            """,
            (measured, plant, MODEL, zone, color, group,
             f"{SENTINEL}-{load_id}-{i}", load_id, i),
        )


def _boxes(client, plant: str, month: str, color: str = MS_COLOR) -> dict[str, dict]:
    response = client.get(
        f"/api/v1/plants/{plant}/wavescan/overview",
        params={"month": month, "model": MODEL, "color": color},
    )
    assert response.status_code == 200, response.text
    return {
        b["orient"]: b
        for b in response.json()["boxes"]
        if b["color_name"] == color and b["model_code"] == MODEL
    }


def _catalogue_family(client, code: str = "MS") -> dict:
    body = client.get("/api/v1/standards/catalogue")
    assert body.status_code == 200, body.text
    return next(f for f in body.json()["families"] if f["family_code"] == code)


def _pair(box: dict) -> tuple[Decimal, Decimal]:
    return Decimal(box["ford"]), Decimal(box["minimum"])


# =====================================================================
# A. schema, function, privileges
# =====================================================================
def test_cf_standard_plant_code_is_a_nullable_fk_and_the_seed_stays_null(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'cf_standard' AND column_name = 'plant_code'"
        )
        assert cur.fetchone() == ("YES",)
        cur.execute(
            "SELECT confrelid::regclass::text FROM pg_constraint "
            "WHERE conrelid = 'cf_standard'::regclass AND contype = 'f' "
            "  AND conkey = ARRAY[(SELECT attnum FROM pg_attribute "
            "     WHERE attrelid = 'cf_standard'::regclass AND attname = 'plant_code')]"
        )
        assert cur.fetchone() == ("ref_plant",)
        cur.execute(
            "SELECT count(*), count(plant_code) FROM cf_standard "
            "WHERE scope = 'FAMILY' AND source_note LIKE 'prototype DEFAULT_STANDARDS%%'"
        )
        seeded, with_plant = cur.fetchone()
    assert seeded == 12
    assert with_plant == 0


def test_purge_function_is_definer_fixed_path_and_only_app_rw_executes(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT p.prosecdef, p.proconfig, "
            "       has_function_privilege('public', p.oid, 'EXECUTE'), "
            "       has_function_privilege('app_rw', p.oid, 'EXECUTE') "
            "  FROM pg_proc p WHERE p.proname = 'purge_workbook'"
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    definer, config, public_exec, app_exec = rows[0]
    assert definer is True
    assert any(c.startswith("search_path=") for c in config)
    assert public_exec is False
    assert app_exec is True


def test_app_rw_still_has_no_table_delete_on_facts(admin_conn):
    with admin_conn.cursor() as cur:
        for table in ("wavescan", "load_batch"):
            cur.execute("SELECT has_table_privilege('app_rw', %s, 'DELETE')", (table,))
            assert cur.fetchone()[0] is False, table


@pytest.mark.parametrize("table", ["wavescan", "load_batch"])
def test_app_rw_delete_from_facts_is_insufficient_privilege(app_conn, table):
    """T01 stays green: the function is the only door, not a grant."""
    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(f"DELETE FROM {table}")


# =====================================================================
# B. publish, catalogue, overview
# =====================================================================
def test_publish_requires_a_known_plant(admin):
    body = {
        "family_code": "MS", "ford_h": 60, "ford_v": 50, "min_h": 55, "min_v": 45,
        "effective_from": "2026-09-23", "source_note": NOTE,
    }
    missing = admin.post("/api/v1/standards", json=body)
    assert missing.status_code == 422, missing.text
    wrong = admin.post("/api/v1/standards", json={**body, "plant_code": "XYZ"})
    assert wrong.status_code == 422, wrong.text


def test_publish_ms_at_ftm_does_not_move_aat(admin, viewer, admin_conn, cleanup):
    note = _note()
    aat_before = next(
        p for p in _catalogue_family(admin)["plants"] if p["plant_code"] == "AAT"
    )
    top_before = {k: _catalogue_family(admin)[k] for k in ("ford_h", "ford_v", "min_h", "min_v")}
    with admin_conn.cursor() as cur:
        ftm = _batch(cur, "iso-ftm", "FTM")
        aat = _batch(cur, "iso-aat", "AAT")
        cleanup.extend([ftm, aat])
        _rows(cur, ftm, "FTM", "2099-08-10")
        _rows(cur, aat, "AAT", "2099-08-10")
    try:
        # Distinct from the seed and from AAT so a leak would show.
        target = {"ford_h": 91, "ford_v": 87, "min_h": 83, "min_v": 79}
        response = _publish(admin, "FTM", note, **target)
        assert response.status_code == 201, response.text
        assert response.json()["plant_code"] == "FTM"
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT plant_code, scope, orient FROM cf_standard "
                "WHERE source_note = %s ORDER BY orient",
                (note,),
            )
            assert cur.fetchall() == [("FTM", "FAMILY", "H"), ("FTM", "FAMILY", "V")]

        family = _catalogue_family(admin)
        by_plant = {p["plant_code"]: p for p in family["plants"]}
        assert set(by_plant) == {"AAT", "FTM", "FVL", "SAP"}
        assert by_plant["FTM"]["plant_specific"] is True
        assert {k: by_plant["FTM"][k] for k in target} == target
        assert by_plant["AAT"] == aat_before, "AAT keeps its seed or its own row"
        assert {k: family[k] for k in top_before} == top_before, "top level is the seed"

        ftm_boxes = _boxes(viewer, "FTM", "2099-08")
        assert _pair(ftm_boxes["Horizontal"]) == (Decimal(91), Decimal(83))
        assert _pair(ftm_boxes["Vertical"]) == (Decimal(87), Decimal(79))
        aat_boxes = _boxes(viewer, "AAT", "2099-08")
        assert _pair(aat_boxes["Horizontal"]) == (
            Decimal(aat_before["ford_h"]), Decimal(aat_before["min_h"])
        )
        assert _pair(aat_boxes["Vertical"]) == (
            Decimal(aat_before["ford_v"]), Decimal(aat_before["min_v"])
        )
    finally:
        _forget_standards(admin_conn, note)


def test_june_overview_uses_the_latest_plant_row_dated_september(
    admin, viewer, admin_conn, cleanup
):
    """ADR 0012: effective_from no longer filters the selected month."""
    note = _note()
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "june", "FTM")
        cleanup.append(load_id)
        _rows(cur, load_id, "FTM", "2026-06-15")
    try:
        first = _publish(admin, "FTM", note, ford_h=70, ford_v=66, min_h=64, min_v=60,
                         effective_from="2026-09-01")
        assert first.status_code == 201, first.text
        latest = _publish(admin, "FTM", note, ford_h=72, ford_v=68, min_h=65, min_v=61,
                          effective_from="2026-09-23")
        assert latest.status_code == 201, latest.text
        boxes = _boxes(viewer, "FTM", "2026-06")
        assert _pair(boxes["Horizontal"]) == (Decimal(72), Decimal(65))
        assert _pair(boxes["Vertical"]) == (Decimal(68), Decimal(61))
    finally:
        _forget_standards(admin_conn, note)


def test_plant_row_beats_a_newer_null_plant_row(admin, viewer, admin_conn, cleanup):
    note = _note()
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "plantwins", "FTM")
        cleanup.append(load_id)
        _rows(cur, load_id, "FTM", "2099-10-10")
    try:
        assert _publish(admin, "FTM", note, ford_h=73, ford_v=69, min_h=66,
                        min_v=62).status_code == 201
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cf_standard
                    (scope, family_name, orient, ford, min, effective_from,
                     source_note, created_at)
                VALUES ('FAMILY', %s, 'H', 11, 10, DATE '2026-09-30', %s,
                        now() + interval '1 hour')
                """,
                (FAMILY, note),
            )
        boxes = _boxes(viewer, "FTM", "2099-10")
        assert _pair(boxes["Horizontal"]) == (Decimal(73), Decimal(66))
    finally:
        _forget_standards(admin_conn, note)


def test_plant_color_row_beats_plant_family_row(admin, viewer, admin_conn, cleanup):
    note = _note()
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "colorwins", "FTM")
        cleanup.append(load_id)
        _rows(cur, load_id, "FTM", "2099-11-10")
    try:
        assert _publish(admin, "FTM", note, ford_h=74, ford_v=70, min_h=67,
                        min_v=63).status_code == 201
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cf_standard
                    (scope, plant_code, color_name, orient, ford, min,
                     effective_from, source_note)
                VALUES ('COLOR', 'FTM', %s, 'H', 99, 97, DATE '2026-09-23', %s),
                       ('COLOR', 'AAT', %s, 'V', 98, 96, DATE '2026-09-23', %s)
                """,
                (MS_COLOR, note, MS_COLOR, note),
            )
        boxes = _boxes(viewer, "FTM", "2099-11")
        assert _pair(boxes["Horizontal"]) == (Decimal(99), Decimal(97)), "COLOR wins"
        assert _pair(boxes["Vertical"]) == (Decimal(70), Decimal(63)), (
            "AAT's COLOR row does not reach FTM; FTM's FAMILY row applies"
        )
    finally:
        _forget_standards(admin_conn, note)


def test_publish_never_updates_or_deletes_prior_rows(admin, admin_conn):
    note = _note()
    with admin_conn.cursor() as cur:
        cur.execute("SELECT id, ford, min, plant_code FROM cf_standard ORDER BY id")
        before = cur.fetchall()
    try:
        assert _publish(admin, "SAP", note, ford_h=60, ford_v=50, min_h=55,
                        min_v=45).status_code == 201
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT id, ford, min, plant_code FROM cf_standard "
                "WHERE source_note <> %s ORDER BY id",
                (note,),
            )
            assert cur.fetchall() == before
    finally:
        _forget_standards(admin_conn, note)


# =====================================================================
# C. purge
# =====================================================================
def _ingest(engineer, cleanup, admin_conn, name: str, plant: str = "AAT") -> dict:
    data = make_workbook(unique_rows(3))
    forget_bytes(admin_conn, data)
    response = upload(engineer, name, data, expected_plant=plant)
    assert response.status_code == 202, response.text
    [entry] = response.json()["batches"]
    cleanup.append(entry["load_id"])
    review = wait_for(engineer, entry["load_id"])
    return {"load_id": entry["load_id"], "file_hash": review["batch"]["file_hash"],
            "data": data, "status": review["batch"]["status"]}


def _counts(admin_conn, file_hash: str) -> dict[str, int]:
    """Rows per table for one hash. Counts only, never CF values."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT array_agg(load_id) FROM load_batch WHERE file_hash = %s",
                    (file_hash,))
        ids = cur.fetchone()[0] or []
        out = {"load_batch": len(ids)}
        for table in ("wavescan", "stg_raw", "stg_review_row", "reject_log",
                      "unidentified_model", "ingest_job", "review_acknowledgement",
                      "review_override"):
            cur.execute(f"SELECT count(*) FROM {table} WHERE load_id = ANY(%s)", (ids,))
            out[table] = cur.fetchone()[0]
    return out


def _untouched(admin_conn) -> tuple:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM ref_template_profile), "
            "       (SELECT count(*) FROM ref_column_alias), "
            "       (SELECT count(*) FROM ref_model_alias), "
            "       (SELECT count(*) FROM cf_standard)"
        )
        return cur.fetchone()


def _purge(client, plant: str, file_hash: str, reason: str = "T37: X on the card."):
    return client.post(
        f"/api/v1/plants/{plant}/workbooks/{file_hash}/purge", json={"reason": reason}
    )


def test_purge_removes_that_hash_only_audits_first_and_404s_twice(
    engineer, admin, admin_conn, cleanup
):
    target = _ingest(engineer, cleanup, admin_conn, "t37-purge-me.xlsx")
    sibling = _ingest(engineer, cleanup, admin_conn, "t37-keep-me.xlsx")
    for item in (target, sibling):
        assert item["status"] == "PENDING_REVIEW"
        commit = engineer.post(f"/api/v1/batches/{item['load_id']}/commit")
        assert commit.status_code == 200, commit.text

    before = _counts(admin_conn, target["file_hash"])
    sibling_before = _counts(admin_conn, sibling["file_hash"])
    kept_before = _untouched(admin_conn)
    assert before["wavescan"] == 3
    assert before["load_batch"] == 1
    assert before["stg_raw"] > 0 and before["ingest_job"] > 0

    response = _purge(admin, "AAT", target["file_hash"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["load_ids"] == [target["load_id"]]
    assert body["wavescan_deleted"] == 3
    assert body["batches_deleted"] == 1
    assert body["audit_action"] == "workbook.purge"

    after = _counts(admin_conn, target["file_hash"])
    assert after == {k: 0 for k in after}, after
    assert _counts(admin_conn, sibling["file_hash"]) == sibling_before
    assert _untouched(admin_conn) == kept_before

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT id, action, entity_type, entity_id, actor_user_id, before, after "
            "FROM audit_event WHERE id = %s",
            (body["audit_id"],),
        )
        audit_id, action, etype, eid, actor, a_before, a_after = cur.fetchone()
    assert (action, etype, eid) == (
        "workbook.purge", "workbook", f"AAT:{target['file_hash']}"
    )
    assert actor is not None
    # Written before the deletes: it holds the pre-purge counts.
    assert a_before["wavescan"] == before["wavescan"]
    assert a_before["stg_raw"] == before["stg_raw"]
    assert a_after["reason"] == "T37: X on the card."
    assert a_after["load_ids"] == [target["load_id"]]

    again = _purge(admin, "AAT", target["file_hash"])
    assert again.status_code == 404, again.text


def test_identical_bytes_after_purge_are_a_new_batch(engineer, admin, admin_conn, cleanup):
    first = _ingest(engineer, cleanup, admin_conn, "t37-reupload.xlsx")
    assert _purge(admin, "AAT", first["file_hash"]).status_code == 200
    again = upload(engineer, "t37-reupload.xlsx", first["data"], expected_plant="AAT")
    assert again.status_code == 202, again.text
    [entry] = again.json()["batches"]
    cleanup.append(entry["load_id"])
    assert entry["load_id"] != first["load_id"], "a new batch, not a T25 reopen"
    review = wait_for(engineer, entry["load_id"])
    assert review["batch"]["file_hash"] == first["file_hash"]


def test_purge_refuses_blank_reason_wrong_role_and_wrong_plant(
    engineer, admin, admin_conn, cleanup
):
    item = _ingest(engineer, cleanup, admin_conn, "t37-refusals.xlsx")
    blank = _purge(admin, "AAT", item["file_hash"], reason="   ")
    assert blank.status_code == 422, blank.text
    assert _purge(engineer, "AAT", item["file_hash"]).status_code == 403
    assert _purge(admin, "FTM", item["file_hash"]).status_code == 404
    assert _purge(admin, "AAT", "0" * 64).status_code == 404
    assert _counts(admin_conn, item["file_hash"])["load_batch"] == 1


def test_purge_refuses_when_another_file_names_it_as_replacement(
    engineer, admin, admin_conn, cleanup
):
    target = _ingest(engineer, cleanup, admin_conn, "t37-replacement.xlsx")
    other = _ingest(engineer, cleanup, admin_conn, "t37-replaced.xlsx")
    with admin_conn.cursor() as cur:
        cur.execute(
            "UPDATE load_batch SET superseded_by = %s WHERE load_id = %s",
            (target["load_id"], other["load_id"]),
        )
    try:
        response = _purge(admin, "AAT", target["file_hash"])
        assert response.status_code == 409, response.text
        assert _counts(admin_conn, target["file_hash"])["load_batch"] == 1
    finally:
        with admin_conn.cursor() as cur:
            cur.execute(
                "UPDATE load_batch SET superseded_by = NULL WHERE load_id = %s",
                (other["load_id"],),
            )


def test_purge_function_refuses_blank_reason_in_sql(admin_dsn, actor_user_id):
    """The guarantee holds even for a caller that skips the DTO."""
    with psycopg.connect(admin_dsn) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                cur.execute(
                    "SELECT purge_workbook('AAT', %s, %s, '  ', NULL)",
                    ("0" * 64, actor_user_id),
                )
        conn.rollback()


# =====================================================================
# D. contract
# =====================================================================
def _assert_contract(spec: dict) -> None:
    paths = spec["paths"]
    purge = "/api/v1/plants/{plant_code}/workbooks/{file_hash}/purge"
    assert set(paths[purge]) == {"post"}
    assert {"200", "404", "409", "422"} <= set(paths[purge]["post"]["responses"])
    schemas = spec["components"]["schemas"]
    assert "plant_code" in schemas["StandardPublishIn"]["required"]
    assert "plant_code" in schemas["StandardPublishOut"]["properties"]
    assert "plants" in schemas["CatalogueFamilyOut"]["required"]
    assert "ford_h" in schemas["CatalogueFamilyOut"]["properties"]
    targets = schemas["PlantFamilyTargets"]["properties"]
    assert {"plant_code", "plant_specific", "ford_h", "ford_v", "min_h", "min_v",
            "effective_from"} <= set(targets)
    assert set(schemas["WorkbookPurgeCreate"]["properties"]) == {"reason"}


def test_openapi_publishes_t37_shapes(viewer):
    _assert_contract(viewer.get("/openapi.json").json())


@pytest.mark.parametrize("path", ["backend/openapi.json", "docs/openapi.json"])
def test_both_emitted_openapi_copies_carry_t37(path):
    _assert_contract(json.loads((REPO_ROOT / path).read_text(encoding="utf-8")))
