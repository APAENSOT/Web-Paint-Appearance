"""Plant WaveScan Monthly Overview: full-population boxes, stored standards.

Pins:

* a known CF set produces Plotly-linear quartiles, the exact mean, and the
  same status ``status_of`` returns
* Horizontal uses the H standard; Vertical uses the V standard
* missing family / missing standard → null status and null lines
* COLOR-scope wins over FAMILY
* FTM does not include another plant's rows
* more than 5,000 rows in one month still grade the full set
* DEFAULT_STANDARDS is not a fallback
* the CF read has no LIMIT
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.grading import status_of
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)

pytestmark = pytest.mark.ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SENTINEL = "OVW"


def overview(plant: str) -> str:
    return f"/api/v1/plants/{plant}/wavescan/overview"


def _batch(cur, tag: str, plant: str = "FTM") -> int:
    digest = hashlib.sha256(f"{SENTINEL}:{tag}:{uuid.uuid4().hex}".encode()).hexdigest()
    cur.execute(
        """
        INSERT INTO load_batch (
            source_file, source_sheet, plant_code, file_hash, status,
            rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
            rows_quarantine, raw_store_key, finished_at, notes)
        VALUES (%s, 'Sheet1', %s, %s, 'COMMITTED', 1, 1, 0, 0, 0, %s, now(), %s)
        RETURNING load_id
        """,
        (
            f"{SENTINEL} {tag}.xlsx",
            plant,
            digest,
            f"wavescan/raw/{digest}",
            f"{SENTINEL} overview fixture",
        ),
    )
    return cur.fetchone()[0]


def _row(
    cur,
    load_id: int,
    source_row: int,
    *,
    plant: str,
    model: str,
    color: str,
    checkzone: str,
    tolerance_group: str,
    cf,
    measured: str = "2099-01-10",
    serial: str | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO wavescan (
            measured_date, plant, model, checkzone, color, tolerance_group,
            paintline, serial_no,
            lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
            load_id, source_sheet, source_row)
        VALUES (%s, %s, %s, %s, %s, %s, 'BOOTH1', %s,
                1, 2, %s, 80, 3, 4, 5, 6, 7, 8, 0,
                %s, 'Sheet1', %s)
        """,
        (
            measured,
            plant,
            model,
            checkzone,
            color,
            tolerance_group,
            serial or f"{SENTINEL}-{load_id}-{source_row}",
            cf,
            load_id,
            source_row,
        ),
    )


def _get(client, plant: str, **params) -> dict:
    response = client.get(overview(plant), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_pinned_quartiles_mean_and_status_match_status_of(viewer, admin_conn, cleanup):
    """Plotly-linear box + exact mean + Light Solids H standard."""
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 20]
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "pin")
        cleanup.append(load_id)
        for i, cf in enumerate(values, start=1):
            _row(
                cur,
                load_id,
                i,
                plant="FTM",
                model="P703 DBL RAPTOR",
                color="Arctic White",
                checkzone="RRHOOD",
                tolerance_group="Horizontal",
                cf=cf,
            )
    body = _get(viewer, "FTM", month="2099-01", model="P703 DBL RAPTOR", color="Arctic White")
    boxes = [
        b
        for b in body["boxes"]
        if b["orient"] == "Horizontal" and b["color_name"] == "Arctic White"
    ]
    assert len(boxes) == 1, body["boxes"]
    box = boxes[0]
    assert box["n"] == 10
    assert Decimal(box["q1"]) == Decimal("3.25")
    assert Decimal(box["median"]) == Decimal("5.5")
    assert Decimal(box["q3"]) == Decimal("7.75")
    assert Decimal(box["whisker_lo"]) == Decimal("1")
    assert Decimal(box["whisker_hi"]) == Decimal("9")
    assert [Decimal(v) for v in box["outliers"]] == [Decimal("20")]
    assert Decimal(box["mean"]) == Decimal("6.5")
    assert Decimal(box["ford"]) == Decimal("62")
    assert Decimal(box["minimum"]) == Decimal("55")
    assert box["status"] == status_of(Decimal("6.5"), Decimal("62"), Decimal("55"))
    assert box["status"] == "FAIL"
    # T114 CHANGE (D-114-12): the dashboard reads the counted readings.
    assert body["active_data_source"] == "v_wavescan_counted"
    assert "pass_rate" not in body
    assert "grading_available" not in body


def test_horizontal_and_vertical_use_their_own_standards(viewer, admin_conn, cleanup):
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "hv")
        cleanup.append(load_id)
        _row(
            cur, load_id, 1, plant="FTM", model="P703 DBL RAPTOR",
            color="Arctic White", checkzone="RRHOOD",
            tolerance_group="Horizontal", cf=60, measured="2099-02-10",
        )
        _row(
            cur, load_id, 2, plant="FTM", model="P703 DBL RAPTOR",
            color="Arctic White", checkzone="LTFDOOR",
            tolerance_group="Vertical", cf=50, measured="2099-02-10",
        )
    body = _get(viewer, "FTM", month="2099-02")
    by_orient = {
        b["orient"]: b
        for b in body["boxes"]
        if b["color_name"] == "Arctic White" and b["model_code"] == "P703 DBL RAPTOR"
    }
    horizontal = by_orient["Horizontal"]
    vertical = by_orient["Vertical"]
    assert Decimal(horizontal["ford"]) == Decimal("62")
    assert Decimal(horizontal["minimum"]) == Decimal("55")
    assert horizontal["status"] == "WARNING"
    assert Decimal(vertical["ford"]) == Decimal("49")
    assert Decimal(vertical["minimum"]) == Decimal("42")
    assert vertical["status"] == "PASS"


def test_missing_family_is_ungraded(viewer, admin_conn, cleanup):
    """Pearl White is not offered at FTM, so there is no plant family."""
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "nofam")
        cleanup.append(load_id)
        _row(
            cur, load_id, 1, plant="FTM", model="P703 DBL RAPTOR",
            color="Pearl White", checkzone="RRHOOD",
            tolerance_group="Horizontal", cf=80, measured="2099-03-10",
        )
    body = _get(viewer, "FTM", month="2099-03")
    box = next(b for b in body["boxes"] if b["color_name"] == "Pearl White")
    assert box["family_code"] is None
    assert box["ford"] is None
    assert box["minimum"] is None
    assert box["status"] is None
    assert Decimal(box["mean"]) == Decimal("80")


def test_color_scope_wins_over_family(viewer, admin_conn, cleanup):
    note = f"{SENTINEL}-color-override-{uuid.uuid4().hex}"
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "colorstd")
        cleanup.append(load_id)
        _row(
            cur, load_id, 1, plant="FTM", model="P703 DBL RAPTOR",
            color="Arctic White", checkzone="RRHOOD",
            tolerance_group="Horizontal", cf=60, measured="2099-04-10",
        )
        cur.execute(
            """
            INSERT INTO cf_standard
                (scope, color_name, orient, ford, min, effective_from, source_note)
            VALUES ('COLOR', 'Arctic White', 'H', 100, 90, DATE '2020-01-01', %s)
            """,
            (note,),
        )
    try:
        body = _get(viewer, "FTM", month="2099-04")
        box = next(
            b
            for b in body["boxes"]
            if b["color_name"] == "Arctic White" and b["orient"] == "Horizontal"
        )
        assert Decimal(box["ford"]) == Decimal("100")
        assert Decimal(box["minimum"]) == Decimal("90")
        assert box["status"] == "FAIL"
    finally:
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM cf_standard WHERE source_note = %s", (note,))


def test_ftm_does_not_include_another_plant(viewer, admin_conn, cleanup):
    with admin_conn.cursor() as cur:
        ftm = _batch(cur, "iso-ftm", "FTM")
        aat = _batch(cur, "iso-aat", "AAT")
        cleanup.extend([ftm, aat])
        _row(
            cur, ftm, 1, plant="FTM", model="P703 DBL RAPTOR",
            color="Arctic White", checkzone="RRHOOD",
            tolerance_group="Horizontal", cf=60, measured="2099-05-10",
        )
        # T76 CHANGE (T58): AAT has no P703 DBL RAPTOR gold
        # (`fk_ws_plant_point`); the isolation claim is by plant, so the AAT
        # row uses AAT's own P703 DBL RANGER, whose gold has RRHOOD.
        _row(
            cur, aat, 1, plant="AAT", model="P703 DBL RANGER",
            color="Arctic White", checkzone="RRHOOD",
            tolerance_group="Horizontal", cf=1, measured="2099-05-10",
        )
    body = _get(viewer, "FTM", month="2099-05")
    boxes = [b for b in body["boxes"] if b["color_name"] == "Arctic White"]
    assert boxes
    assert all(Decimal(b["mean"]) != Decimal("1") for b in boxes)
    assert all(b["n"] == 1 for b in boxes)
    aat_body = _get(viewer, "AAT", month="2099-05")
    aat_box = next(
        b for b in aat_body["boxes"]
        if b["color_name"] == "Arctic White" and b["orient"] == "Horizontal"
    )
    assert Decimal(aat_box["mean"]) == Decimal("1")


def test_more_than_five_thousand_rows_still_grade_the_full_set(viewer, admin_conn, cleanup):
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "uncap")
        cleanup.append(load_id)
        cur.execute(
            """
            INSERT INTO wavescan (
                measured_date, plant, model, checkzone, color, tolerance_group,
                paintline, serial_no,
                lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
                load_id, source_sheet, source_row)
            SELECT DATE '2099-06-10', 'FTM', 'P703 DBL RANGER', 'RRHOOD',
                   'Arctic White', 'Horizontal', 'BOOTH1',
                   %s || '-' || g::text,
                   1, 2, 80, 80, 3, 4, 5, 6, 7, 8, 0,
                   %s, 'Sheet1', g
              FROM generate_series(1, 5001) AS g
            """,
            (SENTINEL, load_id),
        )
    body = _get(viewer, "FTM", month="2099-06", model="P703 DBL RANGER")
    box = next(b for b in body["boxes"] if b["orient"] == "Horizontal")
    assert box["n"] == 5001
    assert Decimal(box["mean"]) == Decimal("80")
    assert box["status"] == "PASS"


def test_empty_month_returns_no_boxes_and_does_not_reuse_another_month(
    viewer, admin_conn, cleanup
):
    with admin_conn.cursor() as cur:
        load_id = _batch(cur, "june")
        cleanup.append(load_id)
        _row(
            cur, load_id, 1, plant="FTM", model="P703 DBL RAPTOR",
            color="Arctic White", checkzone="RRHOOD",
            tolerance_group="Horizontal", cf=60, measured="2099-07-15",
        )
    body = _get(viewer, "FTM", month="2099-09")
    assert body["boxes"] == []
    assert "2099-07" in body["available_months"]
    june = _get(viewer, "FTM", month="2099-07")
    assert june["boxes"]


def test_unknown_plant_is_404(viewer):
    response = viewer.get(overview("NOPE"), params={"month": "2026-09"})
    assert response.status_code == 404


def test_month_is_required(viewer):
    response = viewer.get(overview("FTM"))
    assert response.status_code == 422


def test_preview_and_meta_stay_ungraded(viewer):
    meta = viewer.get("/api/v1/meta").json()
    assert meta["grading_available"] is False
    preview = viewer.get("/api/v1/dashboard/preview").json()
    assert preview["grading_available"] is False


def test_the_cf_read_has_no_limit():
    source = (BACKEND_ROOT / "app/repositories/overview.py").read_text(encoding="utf-8")
    sql = source.split('"""', 2)[-1]
    assert "LIMIT" not in sql
    assert "ACTIVE_VIEW" in source
    assert "DEFAULT_STANDARDS" not in sql


def test_overview_repository_never_restates_the_active_predicate():
    source = (BACKEND_ROOT / "app/repositories/overview.py").read_text(encoding="utf-8")
    assert "is_duplicate" not in source
    assert "is_superseded" not in source
    assert "FROM wavescan" not in source


def test_overview_router_does_not_import_grading():
    source = (BACKEND_ROOT / "app/api/v1/overview.py").read_text(encoding="utf-8")
    assert "domain.grading" not in source
    assert "status_of" not in source


def test_the_contract_publishes_the_overview_path(viewer):
    spec = viewer.get("/openapi.json").json()
    path = "/api/v1/plants/{plant_code}/wavescan/overview"
    assert set(spec["paths"][path]) == {"get"}
    schemas = spec["components"]["schemas"]
    assert "WavescanOverviewOut" in schemas
    assert "OverviewBox" in schemas
    props = schemas["OverviewBox"]["properties"]
    assert "status" in props
    assert "mean" in props
    assert "ford" in props
    assert "minimum" in props
    assert "pass_rate" not in schemas["WavescanOverviewOut"]["properties"]
    assert "grading_available" not in schemas["WavescanOverviewOut"]["properties"]
    for name in schemas:
        assert not name.startswith(("Dashboard", "Preview")) or name in {
            "DashboardPreview",
            "PreviewPoint",
            "PreviewSeries",
        }


def test_color_options_follow_family_order_and_include_ds():
    source = (BACKEND_ROOT / "app/repositories/overview.py").read_text(encoding="utf-8")
    assert "display_order" in source
    assert "is_offered = true" in source
