"""T64: "Absolute / Shadow Black" -- one colour via read and write fold (ADR 0014).

1. Migration state: canonical name active; old names inactive and merged;
   offered at AAT/FTM/FVL with Dark Metallics; old names not offered; SAP same.
2. No fact changed: base-table counts by stored colour.
3. Read fold: active views, History facets list the colour once.
4. Overview at AAT September resolves Dark Metallics for the canonical colour.
5. Film standards GET lists the seed rules under the canonical name.
6. Write fold: a synthetic ingest stores the canonical name.
7. Duplicate: a copy of a stored AAT Absolute Black row is a duplicate; the
   serial-less lookup keys stored old-name rows by the folded colour.
8. Refusals: alias / mapping / plant offer / film publish onto a merged name.
9. One level: a chain or a self-merge is rejected.
10. ``grading_available`` false; OpenAPI unchanged.
Plus the pure fold helpers.

Synthetic workbooks only. Test batches are removed by the T04 ``cleanup``
fixture (owner); nothing stored before T64 is changed.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest

from app.domain.color_identity import fold_colour, merged_sources
from app.domain.film import (
    FilmCleaner,
    FilmRow,
    fold_existing,
    logical_vehicle_id,
    stored_vehicle_ids,
)
from tests.test_t03_contract import (  # noqa: F401
    admin_client,
    client,
    engineer_client,
    make_client,
)
from tests.test_t04_ingest import cleanup  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    sent,
    viewer,
    ws_url,
)

REPO = Path(__file__).resolve().parents[2]
CANON = "Absolute / Shadow Black"
OLD = ("Shadow Black", "Absolute Black")
MERGED = {"Shadow Black": CANON, "Absolute Black": CANON}


def q(admin_conn, sql: str, *params) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ---------------------------------------------------------------- pure
def test_fold_helpers_are_one_lookup():
    assert fold_colour("Shadow Black", MERGED) == CANON
    assert fold_colour(CANON, MERGED) == CANON
    assert fold_colour("Frozen White", MERGED) == "Frozen White"
    assert fold_colour(None, MERGED) is None
    assert merged_sources(CANON, MERGED) == ("Absolute Black", "Shadow Black")
    assert merged_sources("Frozen White", MERGED) == ()


def test_film_cleaner_writes_the_canonical_name():
    cleaner = FilmCleaner(
        None, plant="AAT", model=None, meta={},
        color_by_plant={}, color={"g9z shadow black": "Shadow Black"},
        known_color_names=[CANON], merged_colors=MERGED,
        # This test calls `_colour` only: it asserts the T64 fold, not the
        # T78 plant-offer gate, so the offer list is deliberately empty.
        offered_colors={},
        # T112-FIX: likewise the model offer list (no model here).
        offered_models={},
    )
    assert cleaner._colour("G9Z Shadow Black") == CANON


def test_film_duplicate_key_finds_a_car_stored_under_an_old_name():
    day = date(2026, 9, 25)
    row = FilmRow(day, "AAT", "P703 DBL RANGER", CANON, "J1", None, "001HOOD", "x",
                  logical_vehicle_id("AAT", day, "P703 DBL RANGER", CANON, "J1", None),
                  {}, "f.xlsx", "s", 2, None)
    old_id = logical_vehicle_id("AAT", day, "P703 DBL RANGER", "Shadow Black", "J1", None)
    ids = stored_vehicle_ids(row, MERGED)
    assert ids[0] == row.logical_vehicle_id and old_id in ids
    folded = fold_existing([row], {(old_id, "001HOOD"): 99}, MERGED)
    assert folded[(row.logical_vehicle_id, "001HOOD")] == 99


# ---------------------------------------------------------------- 1
def test_migration_state(admin_conn):
    colours = dict(
        (name, (active, merged)) for name, active, merged in q(
            admin_conn,
            "SELECT color_name, is_active, merged_into FROM ref_color "
            "WHERE color_name IN (%s, %s, %s)", CANON, *OLD,
        )
    )
    assert colours == {
        CANON: (True, None),
        "Shadow Black": (False, CANON),
        "Absolute Black": (False, CANON),
    }
    offered = q(
        admin_conn,
        "SELECT plant_code, family_name FROM ref_plant_color "
        "WHERE color_name = %s AND is_offered ORDER BY 1", CANON,
    )
    assert offered == [("AAT", "Dark Metallics"), ("FTM", "Dark Metallics"),
                       ("FVL", "Dark Metallics")]
    assert q(
        admin_conn,
        "SELECT count(*) FROM ref_plant_color WHERE color_name IN (%s, %s) AND is_offered",
        *OLD,
    ) == [(0,)]
    assert q(
        admin_conn,
        "SELECT color_name, family_name, is_offered FROM ref_plant_color "
        "WHERE plant_code = 'SAP' AND color_name ILIKE '%%black%%'",
    ) == [("Agate Black", "Dark Metallics", True)]
    aliases = q(
        admin_conn,
        "SELECT plant_code, raw_value FROM ref_color_alias "
        "WHERE color_name = %s AND note = 'T64 workbook b9f54fcd row 18' ORDER BY 1, 2",
        CANON,
    )
    assert aliases == [("FTM", "DM G9 Shadow Black BC"), ("FVL", "AB - Absolute Black"),
                       (None, CANON), (None, "Absolute Black")]


# ---------------------------------------------------------------- 2
def test_no_fact_changed(admin_conn):
    """T64 renamed no stored fact; the pre-T64 rows left only by being cleared.

    Written against live t02_dev on 2026-10-06, when AAT / FTM / FVL still
    held 63 + 63 + 288 + 1184 Wave Scan rows and 376 AAT Film rows under the
    old names, in loads including 1064 / 6052 / 6063. T85's Clear list
    removed those loads whole (see the T85 note below), and every load since
    stores the canonical name. So: no row is stored under an old name, and
    the old loads are gone rather than carrying the canonical name -- the
    merge folds on read, it never rewrote them (ADR 0014).
    """
    assert q(admin_conn, "SELECT plant, color, count(*) FROM wavescan "
             "WHERE color IN (%s, %s) GROUP BY 1, 2", *OLD) == []
    assert q(admin_conn, "SELECT plant, color, count(*) FROM filmthickness "
             "WHERE color IN (%s, %s) GROUP BY 1, 2", *OLD) == []
    assert q(admin_conn, "SELECT count(*) FROM load_batch "
             "WHERE load_id IN (1064, 6052, 6063)") == [(0,)]
    assert q(admin_conn, "SELECT count(*) FROM wavescan WHERE color = %s "
             "AND load_id IN (1064, 6052, 6063)", CANON) == [(0,)]


# =====================================================================
# T85: the rows these read-fold tests used to read
# =====================================================================
#: The pre-T64 AAT rows this file was written against -- load_ids 1064 /
#: 6052 / 6063 and the 2026-09-25 Film walk -- were in T85's Clear list and
#: are gone. The *claim* is not about those rows: it is that a row **stored**
#: under a pre-merge name reads back under the canonical one (ADR 0014,
#: section 3 of this module's docstring). That is recreatable, so it is
#: recreated here rather than skipped, and nothing but these rows is read.
OLD_ROW_MONTHS = {"july": date(2026, 7, 15), "september": date(2026, 9, 15)}


@pytest.fixture()
def stored_old_names(admin_conn, cleanup):  # noqa: F811
    """A committed AAT batch whose rows are stored under the two old names.

    Exactly what the database held before T64's merge: `wavescan.color` is
    the literal old spelling, and `ref_color.merged_into` is what folds it.
    One WaveScan row per old name per month, and one Film row, so every
    active view in this module has something of ours to fold.

    `cleanup` (owner) removes the batch and its facts; the module's own
    assertions never look outside this `load_id`.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO load_batch (source_file, source_sheet, file_hash, "
            "  raw_store_key, status, plant_code) "
            "VALUES (%s, 'S', %s, 'k', 'COMMITTED', 'AAT') RETURNING load_id",
            (f"t64-old-names-{uuid.uuid4().hex[:8]}.xlsx",
             uuid.uuid4().hex + uuid.uuid4().hex),
        )
        load_id = cur.fetchone()[0]
        cleanup.append(load_id)

        ids: dict[tuple[str, str], int] = {}
        row_no = 0
        for month, day in OLD_ROW_MONTHS.items():
            for old in OLD:
                row_no += 1
                # Every measure is filled: a copy of this row has to be a
                # complete point, or ADR 0013 holds it for missing LW/SW
                # instead of calling it the duplicate it is.
                cur.execute(
                    "INSERT INTO wavescan (measured_date, plant, model, checkzone, "
                    "  color, tolerance_group, paintline, serial_no, "
                    "  lw, sw, cf, doi, du, wa, wb, wc, wd, we, b, "
                    "  load_id, source_sheet, source_row) "
                    "VALUES (%s, 'AAT', 'U704', 'RRHOOD', %s, 'Horizontal', 'BOOTH1', %s, "
                    "        1.5, 2.5, 60.1, 80.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, -1.25, "
                    "        %s, 'S', %s) RETURNING measurement_id",
                    (day, old, f"T64-{month}-{row_no}", load_id, row_no),
                )
                ids[(month, old)] = cur.fetchone()[0]

        cur.execute(
            "SELECT point_code FROM ref_plant_film_point "
            " WHERE plant_code = 'AAT' AND model_code = 'U704' "
            "   AND retired_at IS NULL ORDER BY point_no LIMIT 1"
        )
        point = cur.fetchone()
        film_id = None
        if point is not None:
            cur.execute(
                "INSERT INTO filmthickness (measured_date, plant, model, color, "
                "  point_code, src_location_text, layer_code, thickness, "
                "  logical_vehicle_id, load_id, source_sheet, source_row) "
                "VALUES (%s, 'AAT', 'U704', %s, %s, %s, 'BASE', 12.5, %s, %s, 'S', 1) "
                "RETURNING measurement_id",
                (OLD_ROW_MONTHS["september"], OLD[0], point[0], point[0],
                 f"t64-veh-{load_id}", load_id),
            )
            film_id = cur.fetchone()[0]

    yield {"load_id": load_id, "wavescan": ids, "filmthickness": film_id,
           "months": OLD_ROW_MONTHS}

    # `cleanup` removes the batch, but `_forget_batches` has no Film table in
    # its list (it predates FilmThickness) and `filmthickness_load_id_fkey`
    # is ON DELETE RESTRICT. This fixture tears down before `cleanup` does,
    # so it takes its own Film row with it.
    if film_id is not None:
        with admin_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM filmthickness WHERE load_id = %s", (load_id,)
            )


# ---------------------------------------------------------------- 3
def test_active_views_fold(admin_conn, stored_old_names):  # T85
    for view in ("v_wavescan_active", "v_wavescan_p703", "v_wavescan_u704",
                 "filmthickness_active"):
        assert q(admin_conn, f"SELECT count(*) FROM {view} WHERE color IN (%s, %s)",
                 *OLD) == [(0,)], view
    # T85: the four rows this fixture stored under the OLD names all read
    # back under the canonical one, and none of them reads back under the
    # name it is actually stored with. That is the fold, on rows this test
    # owns, instead of on the three AAT batches T85 cleared.
    load_id = stored_old_names["load_id"]
    assert q(admin_conn, "SELECT count(*) FROM v_wavescan_active "
             "WHERE plant = 'AAT' AND color = %s AND load_id = %s",
             CANON, load_id) == [(len(stored_old_names["wavescan"]),)]
    assert q(admin_conn, "SELECT count(*) FROM wavescan "
             "WHERE load_id = %s AND color = %s", load_id, CANON) == [(0,)]
    if stored_old_names["filmthickness"] is not None:
        assert q(admin_conn, "SELECT count(*) FROM filmthickness_active "
                 "WHERE plant = 'AAT' AND color = %s AND load_id = %s",
                 CANON, load_id) == [(1,)]
    columns = q(
        admin_conn,
        "SELECT table_name, string_agg(column_name, ',' ORDER BY ordinal_position) "
        "FROM information_schema.columns WHERE table_name IN "
        "('v_wavescan_active', 'filmthickness_active') GROUP BY 1",
    )
    shape = dict(columns)
    assert shape["v_wavescan_active"].split(",")[7] == "color"
    assert shape["filmthickness_active"].split(",")[4] == "color"


def test_history_facets_list_the_colour_once(client, stored_old_names):  # T85
    for month in ("2026-07", "2026-09"):
        body = client.get(
            "/api/v1/plants/AAT/history/facets", params={"month": month}
        ).json()
        assert CANON in body["colors"], (month, body["colors"])
        assert body["colors"].count(CANON) == 1, body["colors"]
        assert not set(OLD) & set(body["colors"])


# ---------------------------------------------------------------- 4
def test_overview_september_resolves_dark_metallics(client, stored_old_names):  # T85
    body = client.get(
        "/api/v1/plants/AAT/wavescan/overview", params={"month": "2026-09"}
    ).json()
    mine = [b for b in body["boxes"] if b["color_name"] == CANON]
    assert mine, [b["color_name"] for b in body["boxes"]]
    assert {b["family_code"] for b in mine} == {"DM"}
    assert not [b for b in body["boxes"] if b["color_name"] in OLD]
    options = {o["color_name"]: o["family_code"] for o in body["color_options"]}
    assert options[CANON] == "DM"
    assert not set(OLD) & set(options)


# ---------------------------------------------------------------- 5
def _rule(client, plant, layer, colour):
    body = client.get(f"/api/v1/plants/{plant}/filmthickness/standards").json()
    assert not [r for r in body["rules"] if r["color_name"] in OLD]
    [hit] = [r for r in body["rules"]
             if r["layer_code"] == layer and r["color_name"] == colour]
    return (hit["h"]["lo"], hit["h"]["hi"]), (hit["v"]["lo"], hit["v"]["hi"])


def test_film_standards_read_under_the_canonical_name(client):
    assert _rule(client, "AAT", "PRIMER", CANON) == ((9.0, 11.0), (9.0, 11.0))
    assert _rule(client, "AAT", "BASE", CANON) == ((9.0, 11.0), (9.0, 11.0))
    assert _rule(client, "FTM", "BASE", CANON) == ((15.0, 20.0), (15.0, 20.0))
    assert _rule(client, "FVL", "BASE", CANON) == ((18.0, 20.0), (18.0, 20.0))


# ---------------------------------------------------------------- 6
def _facts(admin_conn, load_id: int) -> list[tuple]:
    return q(admin_conn, "SELECT color, serial_no, checkzone FROM wavescan "
             "WHERE load_id = %s ORDER BY source_row", load_id)


def test_ingest_writes_the_canonical_name(engineer, admin, cleanup, admin_conn):  # noqa: F811
    day = f"2026-08-{(uuid.uuid4().int % 27) + 1:02d}"
    serial = f"T64-{uuid.uuid4().hex[:8]}"
    data = book(HEADERS, [
        {"Date": day, "Checkzone": "01 RRHOOD", "CF": 55.0, "Serial No": serial,
         "Color": "G9Z Shadow Black"},
        {"Date": day, "Checkzone": "02 RFHOOD", "CF": 56.0, "Serial No": serial,
         "Color": "G9Z Absolute Black"},
    ])
    [review] = sent(engineer, cleanup, admin_conn, "t64-write-fold.xlsx", data)
    assert review["batch"]["counts"]["rows_loaded"] == 2, review["reject_reasons"]
    loaded = admin.post(ws_url("AAT", review["batch"]["file_hash"], "load-ready"))
    assert loaded.status_code == 200, loaded.text
    stored = _facts(admin_conn, review["batch"]["load_id"])
    assert [r[0] for r in stored] == [CANON, CANON]


# ---------------------------------------------------------------- 7
def test_a_copy_of_a_stored_absolute_black_row_is_a_duplicate(
    engineer, cleanup, admin_conn, stored_old_names,  # noqa: F811  # T85
):
    # T85: read the row back from the batch this test stored under an OLD
    # name, instead of from AAT load_id 6063, which T85 cleared. The claim
    # is unchanged -- a new file whose colour folds to the canonical name is
    # a duplicate of a row stored under the pre-merge spelling.
    [row] = q(
        admin_conn,
        "SELECT measured_date, model, checkzone, tolerance_group, paintline, serial_no, "
        "       lw, sw, cf, doi, du, wa, wb, wc, wd, we, b "
        "  FROM v_wavescan_active WHERE load_id = %s AND plant = 'AAT' "
        " ORDER BY measurement_id LIMIT 1",
        stored_old_names["load_id"],
    )
    (day, model, zone, tol, line, serial, lw, sw, cf, doi, du, wa, wb, wc, wd, we, b) = row
    copy = {
        "Date": day.isoformat(), "Plant": "AAT", "Model": model, "Checkzone": zone,
        "Color": "G9Z Shadow Black", "Tolerance Group": tol, "Paintline": line,
        "Serial No": serial,
        **{k: (float(v) if v is not None else None) for k, v in zip(
            ("LW", "SW", "CF", "DOI", "du", "Wa", "Wb", "Wc", "Wd", "We", "B"),
            (lw, sw, cf, doi, du, wa, wb, wc, wd, we, b),
        )},
    }
    data = book(HEADERS, [copy])
    [review] = sent(engineer, cleanup, admin_conn, f"t64-dup-{uuid.uuid4().hex[:6]}.xlsx",
                    data)
    counts = review["batch"]["counts"]
    assert counts["rows_duplicate"] == 1, (counts, review.get("reject_reasons"))
    assert counts["rows_loaded"] == 0


def test_serialless_lookup_keys_stored_old_names_by_the_folded_colour(
    admin_conn, app_database_url, cleanup,  # noqa: F811
):
    """A serial-less row stored as `Absolute Black` before T64 matches a new
    row whose colour resolved to the canonical name (colour is in that key)."""
    from sqlalchemy import create_engine

    from app.domain.cleaner import dedup_key
    from app.repositories.measurements import existing_for_dedup

    day = date(2003, 3, 3)  # far from any real month
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO load_batch (source_file, source_sheet, file_hash, raw_store_key, "
            "status, plant_code) VALUES ('t64-old.xlsx', 'S', %s, 'k', 'COMMITTED', 'AAT') "
            "RETURNING load_id",
            (uuid.uuid4().hex + uuid.uuid4().hex,),
        )
        load_id = cur.fetchone()[0]
        cleanup.append(load_id)
        cur.execute(
            "INSERT INTO wavescan (measured_date, plant, model, checkzone, color, "
            "tolerance_group, serial_no, cf, load_id, source_sheet, source_row) "
            "VALUES (%s, 'AAT', 'U704', 'RRHOOD', 'Absolute Black', 'Horizontal', NULL, "
            "60.1, %s, 'S', 2)",
            (day, load_id),
        )
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            found = existing_for_dedup(conn, [], [("AAT", day, "U704", CANON)])
    finally:
        engine.dispose()
    assert dedup_key("AAT", None, "RRHOOD", day, "U704", CANON) in found


# ---------------------------------------------------------------- 8
def test_alias_onto_a_merged_name_is_422(engineer_client, admin_conn):
    before = q(admin_conn, "SELECT count(*) FROM proposed_mapping")
    response = engineer_client.post(
        "/api/v1/mappings/proposals",
        json={"kind": "ALIAS_COLOR",
              "payload": {"raw_value": "T64 Pytest Black", "color_name": "Shadow Black",
                          "plant_code": "AAT"}},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "merged into 'Absolute / Shadow Black'" in body["message"]
    assert body["correlationId"]
    assert q(admin_conn, "SELECT count(*) FROM proposed_mapping") == before


def test_offering_a_merged_name_is_422(admin_client, admin_conn):
    response = admin_client.post(
        "/api/v1/standards/plant-colours",
        json={"plant_code": "FTM", "color_name": "Shadow Black", "is_offered": True},
    )
    assert response.status_code == 422, response.text
    assert "merged into" in response.json()["message"]
    assert q(admin_conn, "SELECT is_offered FROM ref_plant_color "
             "WHERE plant_code = 'FTM' AND color_name = 'Shadow Black'") == [(False,)]


def test_film_publish_on_a_merged_name_is_422(admin_client, admin_conn):
    before = q(admin_conn, "SELECT count(*) FROM film_standard")
    response = admin_client.post(
        "/api/v1/filmthickness/standards",
        json={"plant_code": "AAT", "layer_code": "BASE", "color_name": "Shadow Black",
              "h": {"lo": 1}, "v": {"lo": 1}, "source_note": "pytest-t64-refused"},
    )
    assert response.status_code == 422, response.text
    assert "not offered" in response.json()["message"]
    assert q(admin_conn, "SELECT count(*) FROM film_standard") == before


# ---------------------------------------------------------------- 9
@pytest.mark.parametrize(
    "statement",
    [
        # a merge target cannot itself be merged
        "UPDATE ref_color SET merged_into = 'Frozen White' "
        "WHERE color_name = 'Absolute / Shadow Black'",
        # a name cannot merge into a merged name (chain)
        "UPDATE ref_color SET merged_into = 'Shadow Black' WHERE color_name = 'Frozen White'",
        # never into itself
        "UPDATE ref_color SET merged_into = color_name WHERE color_name = 'Frozen White'",
    ],
)
def test_one_level_only(admin_dsn, statement):
    with psycopg.connect(admin_dsn) as conn:
        try:
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(statement)
        finally:
            conn.rollback()


# ---------------------------------------------------------------- 10
def test_grading_and_openapi_unchanged(client):
    assert client.get("/api/v1/meta").json()["grading_available"] is False
    live = client.app.openapi()
    # T66 CHANGE: 51 -> 52 (FilmThickness monthly overview GET).
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(live["paths"]) >= 57  # T79 + T81: four Comparison reads; T86: the panel-match read.
    backend_copy = (REPO / "backend" / "openapi.json").read_bytes()
    assert backend_copy == (REPO / "docs" / "openapi.json").read_bytes()
    assert json.loads(backend_copy) == live
