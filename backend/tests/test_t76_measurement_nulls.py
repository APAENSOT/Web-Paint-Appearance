"""T76 C1: `GET /measurements` carries the NULL measures T39 allows.

`MeasurementOut` declared every measure except `b` as required, so one stored
row with a NULL `doi` (T39 took `doi` out of the required measures; 409 live
AAT rows have none) turned any page that listed it into a 500. An approved
LW / SW hole (`MEASURES_HOLE_APPROVABLE`) is stored NULL too. Only `cf` is
never NULL.

The fact is this test's own: a COMMITTED batch and one row, removed by the
T04 ``cleanup`` fixture (owner) afterwards.
"""

from __future__ import annotations

import hashlib
import uuid

from tests.test_t03_contract import (  # noqa: F401
    client,
    make_client,
)
from tests.test_t04_ingest import cleanup  # noqa: F401

NULLABLE = ("lw", "sw", "doi", "du", "wa", "wb", "wc", "wd", "we", "b")


def _null_measure_fact(admin_conn, cleanup) -> tuple[int, int]:  # noqa: F811
    digest = hashlib.sha256(f"t76-null-measures:{uuid.uuid4().hex}".encode()).hexdigest()
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO load_batch (
                source_file, source_sheet, plant_code, file_hash, status,
                rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
                rows_quarantine, raw_store_key, finished_at, notes)
            VALUES ('t76-null-measures.xlsx', 'Sheet1', 'AAT', %s, 'COMMITTED',
                    1, 1, 0, 0, 0, %s, now(), 'pytest t76 null measures')
            RETURNING load_id
            """,
            (digest, f"wavescan/raw/{digest}"),
        )
        load_id = cur.fetchone()[0]
        cleanup.append(load_id)
        cur.execute(
            """
            INSERT INTO wavescan (
                measured_date, plant, model, checkzone, color, tolerance_group,
                paintline, serial_no, lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
                load_id, source_sheet, source_row)
            VALUES ('2099-02-10', 'AAT', 'U704', 'RRHOOD', 'Traction Green',
                    'Horizontal', NULL, NULL,
                    NULL, NULL, 61.5, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                    %s, 'Sheet1', 2)
            RETURNING measurement_id
            """,
            (load_id,),
        )
        return load_id, cur.fetchone()[0]


def test_a_row_with_null_measures_lists_instead_of_500(client, admin_conn, cleanup):  # noqa: F811
    load_id, measurement_id = _null_measure_fact(admin_conn, cleanup)
    listed = client.get("/api/v1/measurements", params={"load_id": load_id})
    assert listed.status_code == 200, listed.text
    [item] = listed.json()["items"]
    assert item["measurement_id"] == measurement_id
    assert item["cf"] == "61.5"
    assert all(item[m] is None for m in NULLABLE), item


def test_one_null_measure_row_reads_back(client, admin_conn, cleanup):  # noqa: F811
    _load_id, measurement_id = _null_measure_fact(admin_conn, cleanup)
    one = client.get(f"/api/v1/measurements/{measurement_id}")
    assert one.status_code == 200, one.text
    assert one.json()["doi"] is None and one.json()["lw"] is None


def test_the_contract_says_which_measures_may_be_null(client):
    props = client.app.openapi()["components"]["schemas"]["MeasurementOut"]["properties"]
    for name in NULLABLE:
        assert any(t.get("type") == "null" for t in props[name].get("anyOf", [])), name
    assert "anyOf" not in props["cf"], "cf is never NULL"
