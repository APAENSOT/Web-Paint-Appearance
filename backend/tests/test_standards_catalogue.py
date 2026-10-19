"""Plant-scoped catalogue + append-only POST /standards (D2, ADR 0010)."""

from __future__ import annotations

from tests.conftest import delete_rows_created_since, row_keys
from app.repositories.standards import WORKBOOK_HASH
from tests.test_t03_contract import (  # noqa: F401
    admin_client,
    client,
    engineer_client,
    make_client,
)

MINT_NAME = "Pytest Catalogue Zebra"
PUBLISH_NOTE = "pytest-standards-catalogue-d2"
PUBLISH_BODY = {
    "plant_code": "FTM",
    "family_code": "MS",
    "ford_h": 65,
    "ford_v": 52,
    "min_h": 58,
    "min_v": 45,
    "effective_from": "2026-09-22",
    "source_document": WORKBOOK_HASH,
    "source_note": PUBLISH_NOTE,
}


def _count_family(admin_conn) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM cf_standard WHERE scope = 'FAMILY'")
        return int(cur.fetchone()[0])


def _delete_mint(admin_conn, name: str = MINT_NAME) -> None:
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM ref_plant_color WHERE color_name = %s", (name,))
        cur.execute("DELETE FROM ref_color WHERE color_name = %s", (name,))


def _delete_publish(admin_conn) -> None:
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM cf_standard WHERE source_note = %s",
            (PUBLISH_NOTE,),
        )


def test_viewer_and_engineer_read_catalogue(client, engineer_client):
    # RO13: the catalogue is reference data, read by every signed-in role.
    for reader in (client, engineer_client):
        response = reader.get("/api/v1/standards/catalogue")
        assert response.status_code == 200, response.text


def test_engineer_cannot_publish_standards(engineer_client):
    response = engineer_client.post("/api/v1/standards", json=PUBLISH_BODY)
    assert response.status_code == 403, response.text


def test_viewer_cannot_mint(client):
    response = client.post(
        "/api/v1/standards/colours",
        json={"color_name": MINT_NAME, "family_code": "MS", "plants": ["AAT"]},
    )
    assert response.status_code == 403, response.text


def test_admin_catalogue_shows_plant_scoped_ignite(admin_client):
    body = admin_client.get("/api/v1/standards/catalogue").json()
    families = {row["family_code"]: row["family_name"] for row in body["families"]}
    assert families["MS"] == "Medium Solids"
    assert families["MM"] == "Medium Metallics"
    ignite = next(c for c in body["colors"] if c["color_name"] == "Ignite Orange")
    by_plant = {p["plant_code"]: p for p in ignite["plants"]}
    assert by_plant["SAP"]["family_code"] == "MM"
    assert by_plant["AAT"]["family_code"] == "MS"
    assert by_plant["FTM"]["family_code"] == "MS"
    assert by_plant["FVL"]["family_code"] == "MS"
    # T64 CHANGE: Shadow Black and Absolute Black are one colour (ADR 0014),
    # offered at AAT, FTM and FVL with DM; the merged names are not listed.
    merged = next(c for c in body["colors"] if c["color_name"] == "Absolute / Shadow Black")
    assert {p["plant_code"] for p in merged["plants"] if p["is_offered"]} == {"AAT", "FTM", "FVL"}
    assert {p["family_code"] for p in merged["plants"] if p["is_offered"]} == {"DM"}
    assert not {"Shadow Black", "Absolute Black"} & {c["color_name"] for c in body["colors"]}
    names = {c["color_name"] for c in body["colors"]}
    assert "Magnetic" in names
    assert "Magnetic Grey" not in names
    series = {row["series_code"] for row in body["series"]}
    assert series >= {"P703", "J73", "CX743", "V363", "U704"}


def test_admin_publish_appends_family_rows(admin_client, admin_conn):
    _delete_publish(admin_conn)
    before = _count_family(admin_conn)
    try:
        response = admin_client.post("/api/v1/standards", json=PUBLISH_BODY)
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["family_code"] == "MS"
        assert payload["audit_action"] == "standards.publish"
        assert _count_family(admin_conn) == before + 2
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT orient, source_document FROM cf_standard "
                "WHERE source_note = %s ORDER BY orient",
                (PUBLISH_NOTE,),
            )
            rows = cur.fetchall()
        assert [r[0] for r in rows] == ["H", "V"]
        assert {r[1] for r in rows} == {WORKBOOK_HASH}
    finally:
        _delete_publish(admin_conn)
        assert _count_family(admin_conn) == before


def test_admin_mint_is_409_on_duplicate(admin_client, admin_conn):
    _delete_mint(admin_conn)
    body = {"color_name": MINT_NAME, "family_code": "MS", "plants": ["AAT", "SAP"]}
    try:
        first = admin_client.post("/api/v1/standards/colours", json=body)
        assert first.status_code == 201, first.text
        second = admin_client.post("/api/v1/standards/colours", json=body)
        assert second.status_code == 409, second.text
        offered = admin_client.post(
            "/api/v1/standards/plant-colours",
            json={"plant_code": "AAT", "color_name": MINT_NAME, "is_offered": False},
        )
        assert offered.status_code == 200, offered.text
        assert offered.json()["is_offered"] is False
    finally:
        _delete_mint(admin_conn)


def test_attach_existing_model_409_when_unchanged(admin_client, admin_conn):
    # T76 CHANGE: never delete a live (FVL, U704) row. The test needs U704 not
    # yet attached at FVL; that is checked, and only the row it creates goes.
    key = "plant_code || ':' || model_code"
    before = row_keys(admin_conn, "ref_plant_model", key)
    assert "FVL:U704" not in before, "U704 is attached at FVL in live data"
    try:
        attached = admin_client.post(
            "/api/v1/standards/plant-models",
            json={"model_code": "U704", "plants": ["FVL"]},
        )
        assert attached.status_code == 201, attached.text
        again = admin_client.post(
            "/api/v1/standards/plant-models",
            json={"model_code": "U704", "plants": ["FVL"]},
        )
        assert again.status_code == 409, again.text
        offered = admin_client.post(
            "/api/v1/standards/plant-models/offered",
            json={"plant_code": "FVL", "model_code": "U704", "is_offered": False},
        )
        assert offered.status_code == 200, offered.text
        assert offered.json()["is_offered"] is False
        missing = admin_client.post(
            "/api/v1/standards/plant-models",
            json={"model_code": "NOT-A-MODEL", "plants": ["AAT"]},
        )
        assert missing.status_code == 404, missing.text
    finally:
        delete_rows_created_since(
            admin_conn, "ref_plant_model", key, before,
            "plant_code = 'FVL' AND model_code = 'U704'",
        )


def test_unmapped_offered_count_is_null_family_rows(admin_client, admin_conn, client):
    _delete_mint(admin_conn)
    try:
        minted = admin_client.post(
            "/api/v1/standards/colours",
            json={"color_name": MINT_NAME, "family_code": "LS", "plants": ["SAP"]},
        )
        assert minted.status_code == 201, minted.text
        with admin_conn.cursor() as cur:
            cur.execute(
                "UPDATE ref_plant_color SET family_name = NULL "
                "WHERE plant_code = 'SAP' AND color_name = %s",
                (MINT_NAME,),
            )
        meta = client.get("/api/v1/meta").json()
        assert meta["grading_available"] is False
        assert meta["unmapped_color_count"] == 1
        for colour in meta["colors"]:
            assert colour["grading_family"] is None
    finally:
        _delete_mint(admin_conn)
        meta = client.get("/api/v1/meta").json()
        assert meta["unmapped_color_count"] == 0
        assert meta["grading_available"] is False
