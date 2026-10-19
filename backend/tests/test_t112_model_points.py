"""T112 -- the Model screen's per-plant read, ``GET /plants/{p}/model-points``.

Claims (task section 3):

1. Live numbers (GET-only): every plant's cards and counts are section 1's,
   FTM's RAPCAP / Single CAP appear as Film-only cards and nowhere else.
2. Counts are live **and counted**: a ``counted = false`` setting lowers Film
   by one, a retired Film point lowers it by one, a retired Wave Scan point
   lowers Wave Scan by one.
3. A Film-only model stays off the Wave Scan catalogue (T46); a Viewer and an
   Engineer read the cards (RO13: any signed-in role). (T112-FIX D-112F-4:
   Attach now accepts a Film-only model.)

**What this file writes.** Claim 2 runs inside one owner transaction that is
always rolled back, so nothing it inserts or retires ever commits. Claim 3's
Attach is refused before any write. Nothing else is written.
"""

from __future__ import annotations

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.repositories.standards import model_points
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401

#: Section 1, measured 2026-10-11 (FTM Wave Scan after T113 ``--apply``).
#: model_code -> (display_name, wavescan_points, film_points).
LIVE = {
    "AAT": {
        "P703 DBL RANGER": (None, 32, 94),
        "P703 DBL SUPER DUTY": (None, 32, None),
        "U704": (None, 31, 95),
    },
    "FTM": {
        "P703 DBL RANGER": (None, 32, 98),
        "P703 DBL RAPTOR": (None, 32, 98),
        "P703 RAPCAP": ("RAPCAP", None, 93),
        "P703 SGL": ("Single CAP", None, 58),
    },
    "FVL": {
        "CX743": (None, 32, 81),
        "P703 DBL RANGER": (None, 32, 94),
        "V363": (None, 32, 88),
    },
    # RO18: SAP has no Raptor -- P703 DBL RAPTOR is not offered, so no card.
    # RO19 D-RO19-5 added J73 061TGATE uncounted: 94 live, still 93 counted.
    "SAP": {
        "J73 DBL": (None, 32, 93),
        "P703 DBL RANGER": (None, 32, 94),
    },
}
FILM_ONLY = {"P703 RAPCAP", "P703 SGL"}


@pytest.mark.parametrize("plant", sorted(LIVE))
def test_live_cards_and_counts(admin, plant):  # noqa: F811
    response = admin.get(f"/api/v1/plants/{plant.lower()}/model-points")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plant_code"] == plant
    got = {
        m["model_code"]: (m["display_name"], m["wavescan_points"], m["film_points"])
        for m in body["models"]
    }
    assert got == LIVE[plant]
    for m in body["models"]:
        film_only = m["model_code"] in FILM_ONLY
        assert m["wavescan_ok"] is not film_only
        assert m["wavescan_offered"] is not film_only
        assert m["series_code"]


def test_unknown_plant_is_404_and_viewer_and_engineer_read(admin, engineer, viewer):  # noqa: F811
    assert admin.get("/api/v1/plants/NOPE/model-points").status_code == 404
    assert viewer.get("/api/v1/plants/FTM/model-points").status_code == 200
    assert engineer.get("/api/v1/plants/FTM/model-points").status_code == 200


def test_counts_are_live_and_counted(admin_dsn):
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn))
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                def counts(plant: str) -> dict[str, tuple]:
                    return {
                        m["model_code"]: (m["wavescan_points"], m["film_points"])
                        for m in model_points(conn, plant)
                    }

                assert counts("FTM")["P703 RAPCAP"] == (None, 93)
                first, second = [
                    r[0]
                    for r in conn.execute(
                        text(
                            "SELECT point_code FROM ref_plant_film_point "
                            "WHERE plant_code = 'FTM' AND model_code = 'P703 RAPCAP' "
                            "AND retired_at IS NULL ORDER BY point_no LIMIT 2"
                        )
                    )
                ]
                conn.execute(
                    text(
                        "INSERT INTO film_point_setting (plant_code, model_code, "
                        "point_code, counted, orientation, reason) "
                        "SELECT plant_code, model_code, point_code, false, "
                        "COALESCE(orientation, 'H'), 'T112 marker, rolled back' "
                        "FROM ref_plant_film_point WHERE plant_code = 'FTM' "
                        "AND model_code = 'P703 RAPCAP' AND point_code = :p"
                    ),
                    {"p": first},
                )
                assert counts("FTM")["P703 RAPCAP"] == (None, 92)
                conn.execute(
                    text(
                        "UPDATE ref_plant_film_point SET retired_at = now(), "
                        "retired_reason = 'T112 marker, rolled back' "
                        "WHERE plant_code = 'FTM' AND model_code = 'P703 RAPCAP' "
                        "AND point_code = :p"
                    ),
                    {"p": second},
                )
                assert counts("FTM")["P703 RAPCAP"] == (None, 91)
                conn.execute(
                    text(
                        "UPDATE ref_plant_ws_point SET retired_at = now(), "
                        "retired_reason = 'T112 marker, rolled back' "
                        "WHERE (plant_code, model_code, point_no) = "
                        "(SELECT plant_code, model_code, min(point_no) FROM ref_plant_ws_point "
                        " WHERE plant_code = 'FVL' AND model_code = 'CX743' "
                        " AND retired_at IS NULL GROUP BY 1, 2)"
                    )
                )
                assert counts("FVL")["CX743"] == (31, 81)
            finally:
                tx.rollback()
    finally:
        engine.dispose()


def test_film_only_model_stays_off_wavescan_catalogue_and_attach(admin):  # noqa: F811
    catalogue = admin.get("/api/v1/standards/catalogue").json()
    listed = {m["model_code"] for s in catalogue["series"] for m in s["models"]}
    assert listed.isdisjoint(FILM_ONLY)
    # T112-FIX (D-112F-4): Attach no longer refuses a Film-only model with
    # 422. RAPCAP is already offered at FTM (0036), so this is 409 and writes
    # nothing; acceptance itself is tested in test_t112fix_remove_both_domains.
    response = admin.post(
        "/api/v1/standards/plant-models",
        json={"model_code": "P703 RAPCAP", "plants": ["FTM"]},
    )
    assert response.status_code == 409, response.text
