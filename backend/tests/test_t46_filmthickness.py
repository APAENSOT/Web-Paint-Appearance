"""T46 -- the FilmThickness domain package (spec 2026-09-29, section 8).

Claims, with the spec's ten cases marked ``[n]``:

* [1] A WaveScan sheet still classifies WAVESCAN; a PELT Quick Summary
  classifies FILMTHICKNESS; a PELT layer diagram and an ODS link stub are
  OUT_OF_SCOPE_SHEET.
* [2] FTM ``AW_RAP_1.xlsx`` is ``P703 RAPCAP``, never Raptor.
* [3] FTM ``AW_RB_1.xlsx`` is ``P703 DBL RAPTOR``; Comments ``RANGER_RAP``
  do not choose the model.
* [4] ``095TGATEIN`` / ``001FTWISH`` are quarantined and never facts; the
  gold names on the same sheet load.
* [5] Four wide layers are four facts on one ``source_row``.
* [6] AAT EC1/BC1/BC2/CC1 are ECOAT/PRIMER/BASE/CLEAR.
* [7] Cab + Box with the same plant/date/colour and blank identity share a
  ``logical_vehicle_id`` and keep two ``load_id``.
* [8] Same date/colour, different Job Numbers: two ``logical_vehicle_id``.
* [9] ``app_rw`` cannot UPDATE or DELETE ``filmthickness``.
* [10] WaveScan ingest of ``P703 RAPCAP`` is held, not Ranger; the mapping
  and standards routes answer 422 for a film-only model.

Every workbook is built in the test (``.xlsx`` with openpyxl, ``.ods`` by
hand). No plant file is read or copied. Location **names** come from
``app.domain.film_catalog`` -- names, no thickness.
"""

from __future__ import annotations

import importlib.util
import io
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import psycopg
import time

import pytest
from openpyxl import Workbook
from psycopg import errors as pgerr

from app.domain import ods
from app.domain.cleaner import Cleaner, CleanRow, Reject
from app.domain.film import (
    FilmCleaner,
    FilmReference,
    FilmRow,
    is_extra_point,
    logical_vehicle_id,
    normalise_location,
    resolve_film_model,
    split_duplicates,
)
from app.domain.film_catalog import FTM_RAPCAP_93, FTM_SGL_58, FVL_GOLD_94, MODEL_CATALOGUES
from app.domain.reader import describe_film_sheet, read_film_sheet
from app.domain.references import ReferenceData
from app.services.ingest import _describe_one
from tests.test_t04_domain import ALIAS_MAP
from tests.test_t04_ingest import (  # noqa: F401  (fixtures)
    HEADERS,
    _forget_batches,
    acknowledge_required,
    admin,
    engineer,
    forget_bytes,
    ingest_apps,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)

pytestmark = pytest.mark.ingest

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations" / "versions" / "0017_t46_filmthickness.py"


def _migration(path: Path = MIGRATION, name: str = "t46_migration"):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M17 = _migration()
#: T55 CHANGE: revision 0020 adds the leftover Film model tokens (D-55-10).
M20 = _migration(
    BACKEND / "migrations" / "versions" / "0020_t55_plant_model_identity.py", "t55_migration"
)
M23 = _migration(
    BACKEND / "migrations" / "versions" / "0023_t60_named_ingest_aliases.py", "t60_migration"
)
FILM_ALIAS = {raw: logical for raw, logical in M17.FILM_COLUMN_ALIASES}
FILM_MODEL_ALIAS = {
    (p, t): m for p, t, m in (*M17.FILM_MODEL_ALIASES, *M20.FILM_MODEL_ALIASES)
}
CATALOGUE = {
    model: {normalise_location(p): p for p in points}
    for model, points in MODEL_CATALOGUES.items()
}
FILM_REF = FilmReference(
    column_alias=FILM_ALIAS, model_alias=FILM_MODEL_ALIAS, catalogue=CATALOGUE,
)
WS_REF = ReferenceData(column_alias=ALIAS_MAP)
COLOURS = ("Absolute Black", "Arctic White", "Traction Green", "Frozen White", "Command Grey")


# =====================================================================
# fixtures: synthetic PELT workbooks
# =====================================================================
def _day() -> str:
    n = uuid.uuid4().int
    return f"{(n % 27) + 1:02d}-{('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov')[(n // 31) % 11]}-{19 + (n // 997) % 6}"


def pelt(
    locations,
    *,
    colour: str = "Absolute Black",
    day: str | None = None,
    job: object = None,
    vin: object = 0,
    comments: str = "",
    title: str = "Ford Vietnam - PELT Filmbuild Report",
    diagram: bool = True,
    values=None,
) -> bytes:
    """An FVL/FTM-shaped PELT Quick Summary (header on row 14)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Quick Summary"
    ws.append([title])
    ws.append([])
    ws.append(["Date:", day or _day()])
    ws.append(["Time:", "09:43 PM", None, "Number of Points:", 0])
    ws.append(["Operator:", "T46", None, "File Name:", "synthetic.prn"])
    ws.append(["Job Number:", job if job is not None else "", None, "Booth:", 1])
    ws.append(["Layer 1:", "Clearcoat", None, "Shift:", "1st"])
    ws.append(["Layer 2:", colour, None, "Vin:", vin])
    ws.append(["Layer 3:", "Mid Grey Primer", None, "Report:", "Quick Summary"])
    ws.append(["Layer 4:", "E-Coat"])
    ws.append(["Layer 5:", "Steel"])
    ws.append(["Layer 6:", ""])
    ws.append(["Comments:", comments, None, None, None, None, "Total"])
    ws.append(["Location", "Clearcoat", colour, "Mid Grey Primer", "E-Coat",
               "Steel", "Thickness"])
    for i, loc in enumerate(locations):
        layer = values[i] if values else (40.1 + i, 18.2, 30.3, 21.4)
        total = sum(v for v in layer if isinstance(v, (int, float)))
        ws.append([loc, *layer, "", total])
    if diagram:
        d = wb.create_sheet("P703 | Clearcoat")
        d.append([title])
        d.append(["P703 | Clearcoat  Clearcoat"])
        d.append(["Date: 05-Jun-26", None, "Vin:   "])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def aat_august(
    rows,
    *,
    sheet: str = "P703_5ZT",
    with_identity: bool = True,
    banner: bool = True,
    sample: str = "2498534 P703 5ZT",
    swatch: str = "Command Grey_4",
    when: datetime | None = None,
) -> bytes:
    """AAT August/Sep EC1 layout: Byk banner, CC1/BC2/BC1/EC1 header on row 7.

    T56 CHANGE (D-56-07): the banner is the **live** one -- sample line in
    A1, the same timestamp twice, ``PELT AAT``, the ``_4`` swatch, model
    text -- and the swatch again in A2. ``with_identity`` adds the Date /
    Color columns the T46 fixture invented (the live files have none);
    ``banner=False`` drops the datetimes and the swatch from row 1.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    stamp = when or datetime(2026, 9, 22, 10, 15)
    if banner:
        ws.append([sample, None, None, None, stamp, None, None, None, stamp, None, None,
                   None, "", None, None, None, "PELT AAT P703", None, None, None,
                   swatch, None, None, None, "P703 DBL-RANGER", None, None, None, "D65/10"])
    else:
        ws.append([sample, None, None, None, None])
    ws.append([swatch, None, "total mic", "CC1 mic", "BC2 mic", "BC1 mic", "EC1 mic"])
    ws.append(["Fail High", None, 100, 45, 25, 15, 30])
    ws.append(["Warning High"])
    ws.append(["Warning Low"])
    ws.append(["Fail Low", None, 65, 25, 10, 7, 16])
    header = ["Checkzone", "Status", "total mic", "CC1 mic", "BC2 mic", "BC1 mic", "EC1 mic"]
    if with_identity:
        header += ["Date", "Color"]
    ws.append(header)
    ws.append(["Match to Standard"])
    for loc, cc1, bc2, bc1, ec1 in rows:
        line = [loc, "Pass", cc1 + bc2 + bc1 + ec1, cc1, bc2, bc1, ec1]
        if with_identity:
            line += ["2026-08-20", "Command Grey"]
        ws.append(line)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def ods_bytes(tables: dict[str, list[list]]) -> bytes:
    """A minimal OpenDocument spreadsheet, written by hand."""

    def cell(value):
        if value is None:
            return "<table:table-cell/>"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return (f'<table:table-cell office:value-type="float" '
                    f'office:value="{value}"><text:p>{value}</text:p></table:table-cell>')
        return (f'<table:table-cell office:value-type="string"><text:p>'
                f'{escape(str(value))}</text:p></table:table-cell>')

    body = []
    for name, rows in tables.items():
        body.append(f'<table:table table:name="{escape(name)}">')
        for row in rows:
            body.append("<table:table-row>" + "".join(cell(v) for v in row) + "</table:table-row>")
        body.append('<table:table-row table:number-rows-repeated="1048000">'
                    '<table:table-cell table:number-columns-repeated="1024"/></table:table-row>')
        body.append("</table:table>")
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'office:version="1.2"><office:body><office:spreadsheet>'
        + "".join(body)
        + "</office:spreadsheet></office:body></office:document-content>"
    )
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        '<manifest:file-entry manifest:full-path="/" '
        'manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
        "</manifest:manifest>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), ods.ODS_MIMETYPE)
        z.writestr("content.xml", content, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/manifest.xml", manifest, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def sap_ods(locations, *, day="12-Aug-26", vin="TP00001") -> bytes:
    preamble = [
        ["Axalta South Africa - PELT Filmbuild Report"], [],
        ["Date:", day], ["Time:", "11:48 pm", None, "Number of Points:", 0],
        ["Operator:", "T46", None, "File Name:", "synthetic.prn"],
        ["Job Number:", "SAPJOB", None, "Booth:", 1],
        ["Layer 1:", "Clearcoat", None, "Shift:", "1st"],
        ["Layer 2:", "Frozen White", None, "Vin:", vin],
        ["Layer 3:", "White Prime", None, "Report:", "Ranger 4 Door"],
        ["Layer 4:", "E-Coat"], ["Layer 5:", "Steel"], ["Layer 6:"],
        ["Comments:", None, None, None, None, None, "Total"],
        ["Location", "Clearcoat", "Frozen White", "White Prime", "E-Coat", "Steel", "Thickness"],
    ]
    data = [[loc, 40.5, 12.25, 30.125, 18.0, None, 100.875] for loc in locations]
    return ods_bytes({
        "QUICK_SUMMARY": preamble + data,
        "'https://example.invalid/Pelt%20Report.xls'#Home": [],
    })


# =====================================================================
# helpers against the database
# =====================================================================
def _wait_for_idle_jobs(admin_conn, load_ids: list[int], timeout: float = 20.0) -> None:
    """Block until no ingest job for these batches is QUEUED or RUNNING.

    T85 / D-87-8. Without this the teardown races the ingest worker, and
    the race is not theoretical -- it left batches 48327-48330 in the
    standing database on 2026-10-07. The sequence that produced them:
    `_forget_batches` deleted `ingest_job` and `stg_raw` for all four, the
    worker (which already held 48327) then re-inserted that batch's 12
    staging and 12 review rows, and the closing `DELETE FROM load_batch`
    hit `ON DELETE RESTRICT` and raised -- so **all four** `load_batch`
    rows survived, not just the one that raced.

    Deleting the job row does not stop a worker that has already claimed
    it, so the only correct move is to wait for it to finish first.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingest_job "
                " WHERE load_id = ANY(%s) AND status IN ('QUEUED', 'RUNNING')",
                (load_ids,),
            )
            if cur.fetchone()[0] == 0:
                return
        time.sleep(0.1)
    # Not an assertion: a worker that never finishes is the test's problem
    # to report, and the delete below is still worth attempting.


@pytest.fixture
def film_cleanup(admin_conn):
    """Forget every batch a test made, film facts first (owner, test DB).

    T85 / D-87-8: the teardown now runs **whatever the test did** and
    **proves** it emptied up after itself. It waits for the worker, deletes,
    and then checks: a batch still standing is retried once (the worker can
    only re-create rows while it holds the job, and it no longer does), and
    a batch still standing after that **fails the test run** rather than
    becoming silent residue in the standing database.
    """
    load_ids: list[int] = []
    yield load_ids
    if not load_ids:
        return
    leaked: list[int] = []
    for attempt in (1, 2):
        _wait_for_idle_jobs(admin_conn, load_ids)
        with admin_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM filmthickness WHERE load_id = ANY(%s)", (load_ids,)
            )
            cur.execute(
                "DELETE FROM worksheet_decision WHERE load_id = ANY(%s)", (load_ids,)
            )
            _forget_batches(cur, load_ids)
            cur.execute(
                "SELECT load_id FROM load_batch WHERE load_id = ANY(%s) ORDER BY 1",
                (load_ids,),
            )
            leaked = [row[0] for row in cur.fetchall()]
        if not leaked:
            return
    raise AssertionError(
        f"film_cleanup could not remove {leaked} after two attempts. Those "
        f"batches are now residue in the standing database and must be "
        f"removed by load_id (T85 / D-87-8)."
    )


def sent(engineer, film_cleanup, admin_conn, name, data, plant) -> dict[str, dict]:
    forget_bytes(admin_conn, data)
    response = engineer.post(
        "/api/v1/uploads",
        files={"files": (name, data, "application/octet-stream")},
        data={"expected_plant": plant},
    )
    assert response.status_code == 202, response.text
    out = {}
    for entry in response.json()["batches"]:
        film_cleanup.append(entry["load_id"])
        out[entry["sheet"]] = wait_for(engineer, entry["load_id"])
    return out


def commit(engineer, admin, review) -> dict:
    acknowledge_required(admin, review)
    fresh = engineer.get(f"/api/v1/batches/{review['batch']['load_id']}").json()
    response = engineer.post(f"/api/v1/batches/{fresh['batch']['load_id']}/commit")
    assert response.status_code == 200, response.text
    return response.json()


def film_facts(admin_conn, load_id: int) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT source_row, point_code, layer_code, thickness, model, color, "
            "       logical_vehicle_id, job_no, serial_no, src_location_text "
            "  FROM filmthickness WHERE load_id = %s ORDER BY source_row, layer_code",
            (load_id,),
        )
        return cur.fetchall()


def batch_domain(admin_conn, load_id: int) -> tuple:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT domain, sheet_class, status, rows_in_file, rows_loaded, "
            "       rows_duplicate, rows_rejected, rows_quarantine "
            "  FROM load_batch WHERE load_id = %s",
            (load_id,),
        )
        return cur.fetchone()


def review_rows(admin_conn, load_id: int) -> dict[int, tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT source_row, disposition, reason, canonical "
            "  FROM stg_review_row WHERE load_id = %s ORDER BY source_row",
            (load_id,),
        )
        return {r[0]: r[1:] for r in cur.fetchall()}


# =====================================================================
# A. schema (revision 0017)
# =====================================================================
def test_film_only_models_are_catalogue_rows_that_wavescan_cannot_use(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code, wavescan_ok, expected_zone_count, "
            "       expected_film_point_count, display_name "
            "  FROM ref_model WHERE model_code LIKE 'P703%' ORDER BY 1"
        )
        rows = {r[0]: r[1:] for r in cur.fetchall()}
    assert rows["P703 RAPCAP"] == (False, 0, 93, "RAPCAP")
    assert rows["P703 SGL"] == (False, 0, 58, "Single CAP")
    assert rows["P703 DBL RANGER"][:3] == (True, 32, 94)
    assert rows["P703 DBL RAPTOR"][:3] == (True, 32, 94)
    assert rows["P703 DBL SUPER DUTY"][2] is None, "no Super Duty FilmThickness"


@pytest.mark.parametrize("ok, zones", [(True, 0), (False, 32)])
def test_zero_zones_is_legal_only_for_a_film_only_model(admin_tx, ok, zones):
    with admin_tx.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                "INSERT INTO ref_model (model_code, model_family, body_style, "
                "expected_zone_count, wavescan_ok) VALUES ('T46 X', 'P703', "
                "'PICKUP', %s, %s)",
                (zones, ok),
            )


def test_ftm_tokens_are_film_only_and_rap_is_rapcap(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT plant_code, raw_token, model_code FROM ref_film_model_alias")
        rows = {(p, t): m for p, t, m in cur.fetchall()}
        cur.execute(
            "SELECT count(*) FROM ref_model_alias "
            "WHERE model_code IN ('P703 RAPCAP', 'P703 SGL')"
        )
        leaked = cur.fetchone()[0]
    assert rows[("FTM", "RAP")] == "P703 RAPCAP"
    assert rows[("FTM", "RB")] == "P703 DBL RAPTOR"
    assert rows[("FTM", "SGL")] == "P703 SGL"
    assert rows[("FTM", "DBL")] == "P703 DBL RANGER"
    outside = {(p, t) for (p, t), m in rows.items()
               if p != "FTM" and m in ("P703 RAPCAP", "P703 DBL RAPTOR", "P703 SGL")}
    assert outside == set(), "RAPCAP / RB / SGL exist only at FTM (F7)"
    assert leaked == 0, "film-only models never bind through WaveScan ref_model_alias"


def test_point_catalogues_are_the_named_sets(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code, point_code FROM ref_model_film_point ORDER BY model_code, point_no"
        )
        got: dict[str, list[str]] = {}
        for model, point in cur.fetchall():
            got.setdefault(model, []).append(point)
    assert got["P703 DBL RANGER"] == list(FVL_GOLD_94)
    assert got["P703 DBL RAPTOR"] == list(FVL_GOLD_94)
    assert got["P703 RAPCAP"] == list(FTM_RAPCAP_93)
    assert got["P703 SGL"] == list(FTM_SGL_58)
    assert len(FVL_GOLD_94) == 94 and "094LBOXSIDE" in FVL_GOLD_94 and "090RTFEND" in FVL_GOLD_94
    assert not any(is_extra_point(p) for points in got.values() for p in points)


def test_film_header_aliases_are_their_own_domain(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT raw_header, logical_field FROM ref_column_alias "
            "WHERE domain = 'FILMTHICKNESS' AND is_approved"
        )
        film = dict(cur.fetchall())
        cur.execute(
            "SELECT raw_header, logical_field FROM ref_column_alias WHERE domain = 'WAVESCAN'"
        )
        wave = dict(cur.fetchall())
    # T54 CHANGE: revision 0019 adds the proving file's Layer 3 header.
    # T60 CHANGE: revision 0023 adds the owner-named layer / ignore headers.
    # RO18: the owner approved FVL's "Cleatcoat" spelling (chat, 2026-10-14).
    assert film == {**FILM_ALIAS, "dk grey prime": "primer", **dict(M23.FILM_COLUMN_ALIASES),
                    "cleatcoat": "clear"}
    assert wave["checkzone"] == "checkzone", "WaveScan Checkzone is untouched"
    assert "cc1 mic" not in wave and "location" not in wave, "no film word in WaveScan"


def test_the_location_map_holds_only_proved_rows(admin_conn):
    # T47 CHANGE: 0017 seeded this empty; 0018 seeds the owner-proved P703
    # DBL maps. The T46 guarantee that survives is that none is unproved.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_film_location_map "
            "WHERE proof_hash IS NULL OR verified_by IS NULL"
        )
        assert cur.fetchone()[0] == 0, "every map names its proof (F10)"


def test_app_rw_holds_insert_and_select_only_on_film_facts(admin_conn):  # [9]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = 'app_rw' AND table_name = 'filmthickness'"
        )
        granted = {r[0] for r in cur.fetchall()}
    assert granted == {"INSERT", "SELECT"}


@pytest.mark.parametrize("statement", [
    "UPDATE filmthickness SET thickness = 0",
    "DELETE FROM filmthickness",
    "DELETE FROM load_batch WHERE domain = 'FILMTHICKNESS'",
])
def test_app_rw_cannot_update_or_delete_film_facts(app_conn, statement):  # [9]
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(statement)


def test_a_film_fact_cannot_arrive_already_retired(admin_tx, sample_load_id):
    with admin_tx.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                "INSERT INTO filmthickness (measured_date, plant, model, color, "
                "point_code, src_location_text, layer_code, thickness, "
                "logical_vehicle_id, load_id, source_sheet, source_row, is_superseded) "
                "VALUES ('2026-06-05', 'FVL', 'P703 DBL RANGER', 'Absolute Black', "
                "'001HOOD', '001HOOD', 'CLEAR', 40, 'x', %s, 'Quick Summary', 15, true)",
                (sample_load_id,),
            )


def test_a_fact_must_name_a_point_of_its_model(admin_tx, sample_load_id):
    with admin_tx.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO filmthickness (measured_date, plant, model, color, "
                "point_code, src_location_text, layer_code, thickness, "
                "logical_vehicle_id, load_id, source_sheet, source_row) "
                # T99 CHANGE (D-99-5): `095RBXFLOOR` is a real point of FTM's
                # Raptor walk now, so the name that proves the claim is one
                # the catalogue holds and this plant x model does not --
                # `011LTFEND` is an FVL point, never an FTM Raptor one.
                "VALUES ('2026-06-05', 'FTM', 'P703 DBL RAPTOR', 'Arctic White', "
                "'011LTFEND', '011LTFEND', 'CLEAR', 40, 'x', %s, 'Q', 15)",
                (sample_load_id,),
            )


def test_publish_accepts_the_film_domain(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT pg_get_functiondef('publish_template_profile'::regproc)")
        body = cur.fetchone()[0]
        cur.execute("SELECT pg_get_functiondef('reset_batch_staging'::regproc)")
        reset = cur.fetchone()[0]
    assert "'FILMTHICKNESS'" in body, "the T26 WAVESCAN-only stop is widened"
    assert "filmthickness" in reset, "replay refuses a batch with film facts"


# =====================================================================
# B. domain (no database)
# =====================================================================
def test_wavescan_still_wavescan_and_pelt_is_film():  # [1]
    wave = make_workbook(unique_rows(2))
    assert _describe_one(wave, "PasteData", WS_REF, FILM_REF).sheet_class == "WAVESCAN"
    data = pelt(FVL_GOLD_94[:3])
    qs = _describe_one(data, "Quick Summary", WS_REF, FILM_REF)
    assert (qs.domain, qs.sheet_class, qs.header_row) == ("FILMTHICKNESS", "FILMTHICKNESS", 14)
    assert qs.base_from_layer_block, "Base is the column PELT Layer 2 names"
    assert qs.missing_required == () and qs.unreviewed_headers == ()
    diagram = _describe_one(data, "P703 | Clearcoat", WS_REF, FILM_REF)
    assert diagram.sheet_class == "OUT_OF_SCOPE_SHEET"


def test_checkzone_plus_cf_is_still_wavescan_even_with_film_words():  # [1]
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS + ["Clearcoat", "E-Coat", "Location"])
    ws.append([None] * (len(HEADERS) + 3))
    buffer = io.BytesIO()
    wb.save(buffer)
    assert _describe_one(buffer.getvalue(), ws.title, WS_REF, FILM_REF).sheet_class == "WAVESCAN"


def test_ftm_rap_is_rapcap_not_raptor():  # [2]
    got = resolve_film_model("FTM", "AW_RAP_1.xlsx", "Quick Summary", FILM_MODEL_ALIAS)
    assert (got.model, got.token, got.source) == ("P703 RAPCAP", "RAP", "filename_token")


def test_ftm_rb_is_raptor_and_comments_do_not_choose():  # [3]
    got = resolve_film_model("FTM", "AW_RB_1.xlsx", "Quick Summary", FILM_MODEL_ALIAS)
    assert got.model == "P703 DBL RAPTOR"
    data = pelt(FVL_GOLD_94[:2], colour="Arctic White", comments="PROG_BL / RANGER_RAP")
    template = describe_film_sheet(data, "Quick Summary", FILM_ALIAS)
    assert "comments" in template.meta_map
    rows = list(read_film_sheet(data, "Quick Summary", template, "AW_RB_1.xlsx"))
    cleaner = _cleaner("FTM", got, template)
    assert {r.model for r in cleaner.clean_all(rows).clean} == {"P703 DBL RAPTOR"}


@pytest.mark.parametrize("plant, name, sheet, model", [
    ("FVL", "P703-UR56776-AB.xlsx", "Quick Summary", "P703 DBL RANGER"),
    ("SAP", "130820267VP703CCC2TP18044PELT.ods", "QUICK_SUMMARY", "P703 DBL RANGER"),
    ("AAT", "Data Pelt P703 Box 3HC(31Mar26).xlsx", "Quick Summary", "P703 DBL RANGER"),
    # T55 CHANGE (D-55-09/10): a leftover with a Film alias at that plant
    # loads on its own catalogue -- never Ranger -- and one without still holds.
    ("FVL", "CX743-UR57121-AB.xlsx", "Quick Summary", "CX743"),
    ("FVL", "V363-PR63667-AB-16MR.xlsx", "Quick Summary", "V363"),
    ("SAP", "7V J73 CC C1 TU88556 PELT.ods", "QUICK_SUMMARY", "J73 DBL"),
    ("AAT", "AAT Thickness Jul2026.xlsx", "U704", "U704"),
    ("AAT", "CX743-UR57121-AB.xlsx", "Quick Summary", None),
    ("SAP", "V363 PELT.ods", "QUICK_SUMMARY", None),
    ("FVL", "AW_RAP_1.xlsx", "Quick Summary", None),
])
def test_other_plants_read_p703_as_ranger_and_hold_leftovers(plant, name, sheet, model):
    assert resolve_film_model(plant, name, sheet, FILM_MODEL_ALIAS).model == model


def test_extra_points_are_held_and_gold_names_load():  # [4]
    assert is_extra_point("095TGATEIN") and is_extra_point("001FTWISH")
    assert is_extra_point("1)098TGATEIN") and not is_extra_point("094LBOXSIDE")
    data = pelt(["001HOOD", "095TGATEIN", "001FTWISH", "002HOOD", "021LAPILLAR"],
                colour="Arctic White")
    template = describe_film_sheet(data, "Quick Summary", FILM_ALIAS)
    rows = list(read_film_sheet(data, "Quick Summary", template, "AW_RB_7.xlsx"))
    model = resolve_film_model("FTM", "AW_RB_7.xlsx", "Quick Summary", FILM_MODEL_ALIAS)
    result = _cleaner("FTM", model, template).clean_all(rows)
    assert [r.point_code for r in result.clean] == ["001HOOD", "002HOOD"]
    held = {h.location: h.reason for h in result.held}
    assert held == {
        "095TGATEIN": "EXTRA_POINT",
        "001FTWISH": "EXTRA_POINT",
        "021LAPILLAR": "UNMAPPED_POINT",
    }, "an FTM label that is not a gold name is held, not matched by walk order"


def test_four_wide_layers_unpivot_to_four_facts_on_one_row():  # [5]
    data = pelt(["001HOOD"], values=[(38.625, 16.231, 32.76, 20.959)])
    template = describe_film_sheet(data, "Quick Summary", FILM_ALIAS)
    rows = list(read_film_sheet(data, "Quick Summary", template, "P703-X-AB.xlsx"))
    model = resolve_film_model("FVL", "P703-X-AB.xlsx", "Quick Summary", FILM_MODEL_ALIAS)
    [row] = _cleaner("FVL", model, template).clean_all(rows).clean
    assert row.source_row == 15
    assert row.layers == {
        "CLEAR": Decimal("38.625"), "BASE": Decimal("16.231"),
        "PRIMER": Decimal("32.76"), "ECOAT": Decimal("20.959"),
    }, "Steel and Thickness are read, never facts"


def test_a_blank_layer_is_absent_not_invented():  # [5]
    data = pelt(["001HOOD"], values=[(38.6, "", 32.7, 20.9)])
    template = describe_film_sheet(data, "Quick Summary", FILM_ALIAS)
    rows = list(read_film_sheet(data, "Quick Summary", template, "P703-X-AB.xlsx"))
    model = resolve_film_model("FVL", "P703-X-AB.xlsx", "Quick Summary", FILM_MODEL_ALIAS)
    [row] = _cleaner("FVL", model, template).clean_all(rows).clean
    assert set(row.layers) == {"CLEAR", "PRIMER", "ECOAT"}


def test_aat_ec1_bc1_bc2_cc1_are_the_four_layers():  # [6]
    data = aat_august([("001HOOD", 40.0, 12.0, 20.0, 18.0)])
    template = describe_film_sheet(data, "P703_5ZT", FILM_ALIAS)
    assert template.header_row == 7
    assert sorted(template.recognised.values()) == sorted(
        ["location", "status", "total_thickness", "clear", "base", "primer", "ecoat",
         "date", "color"]
    )
    rows = list(read_film_sheet(data, "P703_5ZT", template, "Data Pelt P703 (Aug26).xlsx"))
    model = resolve_film_model("AAT", "Data Pelt P703 (Aug26).xlsx", "P703_5ZT", FILM_MODEL_ALIAS)
    result = _cleaner("AAT", model, template).clean_all(rows)
    [row] = result.clean
    assert row.layers == {"CLEAR": Decimal("40.0"), "BASE": Decimal("12.0"),
                          "PRIMER": Decimal("20.0"), "ECOAT": Decimal("18.0")}
    assert [a.values["location"] for a in result.aggregates] == ["Match to Standard"]


def test_aat_ec1_live_banner_is_read_and_a_bare_one_is_still_refused():
    """T56 CHANGE (D-56-01..05). The live EC1 sheet has no Date / Color
    column: the banner datetime and the `_4` swatch are its identity, and
    the sample line is its job. A banner that truly lacks both is still
    refused, never filled from the upload day or a guess."""
    live = aat_august([("001HOOD", 40.0, 12.0, 20.0, 18.0)], with_identity=False)
    template = describe_film_sheet(live, "P703_5ZT", FILM_ALIAS)
    assert template.sheet_class == "FILMTHICKNESS"
    assert template.missing_required == ()
    meta = template.meta_map
    assert meta["date"] == datetime(2026, 9, 22, 10, 15)
    assert meta["banner colour"] == "Command Grey_4"
    assert meta["job number"] == "2498534 P703 5ZT"

    bare = aat_august([("001HOOD", 40.0, 12.0, 20.0, 18.0)], with_identity=False,
                      banner=False)
    template = describe_film_sheet(bare, "P703_5ZT", FILM_ALIAS)
    assert template.sheet_class == "FILMTHICKNESS"
    # RO18 (B4): no date is the month question, never filled; colour still refuses.
    assert template.missing_required == ("color",)
    assert "date" not in template.meta_map


def test_cab_and_box_with_blank_identity_share_a_car():  # [7]
    day = date(2026, 3, 31)
    cab = logical_vehicle_id("AAT", day, "P703 DBL RANGER", "Traction Green", None, None)
    box = logical_vehicle_id("AAT", day, "P703 DBL RANGER", "Traction Green", None, None)
    assert cab == box


def test_different_jobs_are_two_cars_and_blank_versus_filled_conflicts():  # [8]
    day = date(2026, 6, 5)
    one = logical_vehicle_id("FVL", day, "P703 DBL RANGER", "Absolute Black", "UR1", None)
    two = logical_vehicle_id("FVL", day, "P703 DBL RANGER", "Absolute Black", "UR2", None)
    blank = logical_vehicle_id("FVL", day, "P703 DBL RANGER", "Absolute Black", None, None)
    assert len({one, two, blank}) == 3
    colour = logical_vehicle_id("FVL", day, "P703 DBL RANGER", "Frozen White", None, None)
    assert colour != blank, "date/colour mismatch never combines"


def test_vin_zero_is_a_placeholder_and_job_number_identifies():
    data = pelt(["001HOOD"], job="UR56776", vin=0)
    template = describe_film_sheet(data, "Quick Summary", FILM_ALIAS)
    rows = list(read_film_sheet(data, "Quick Summary", template, "P703-UR56776-AB.xlsx"))
    model = resolve_film_model("FVL", "P703-UR56776-AB.xlsx", "Quick Summary", FILM_MODEL_ALIAS)
    [row] = _cleaner("FVL", model, template).clean_all(rows).clean
    assert (row.job_no, row.serial_no) == ("UR56776", None), "no VIN is generated"


def test_a_repeated_point_of_one_car_is_a_duplicate_not_a_second_fact():
    rows = [
        FilmRow(date(2026, 6, 5), "FVL", "P703 DBL RANGER", "Absolute Black", "J", None,
                "001HOOD", "001HOOD", "car", {"CLEAR": Decimal(1)}, "f", "s", n)
        for n in (15, 16)
    ]
    keep, dups = split_duplicates(rows, {})
    assert [r.source_row for r in keep] == [15] and len(dups) == 1


def test_wavescan_model_p703_rapcap_is_held_not_ranger():  # [10]
    ref = ReferenceData(
        column_alias=ALIAS_MAP,
        plant={"ftm": "FTM"},
        model={"p703 rapcap": "P703 RAPCAP"},
        film_only_models=frozenset({"P703 RAPCAP", "P703 SGL"}),
        offered_models={("FTM", "P703 RAPCAP"): True},
    )
    from app.domain.reader import RawRow

    raw = RawRow("f.xlsx", "PasteData", 2, {"plant": "FTM", "model": "P703 RAPCAP",
                                           "date": "2026-08-03", "checkzone": "01 RRHOOD",
                                           "color": "Arctic White", "cf": 60})
    out = Cleaner(ref, ("FTM",), expected_plant="FTM").clean_row(raw)
    assert isinstance(out, Reject) and not isinstance(out, CleanRow)
    # T115-FIX (D-115F-1): its own code, not the Removed-model one.
    assert out.reason == "FILM_ONLY_MODEL" and "not this domain" in out.detail


def test_ods_rows_are_read_like_xlsx():
    data = sap_ods(["001HOOD", "002HOOD"])
    assert ods.is_ods(data)
    names = ods.sheet_names(data)
    assert names[0] == "QUICK_SUMMARY"
    rows = list(ods.iter_rows(data, "QUICK_SUMMARY"))
    assert rows[13][:3] == ("Location", "Clearcoat", "Frozen White")
    assert rows[14][:2] == ("001HOOD", 40.5) and len(rows) == 16
    template = describe_film_sheet(data, "QUICK_SUMMARY", FILM_ALIAS)
    assert template.sheet_class == "FILMTHICKNESS" and template.header_row == 14


def _cleaner(plant, model, template) -> FilmCleaner:
    return FilmCleaner(
        FILM_REF, plant=plant, model=model, meta=template.meta_map,
        color_by_plant={}, color={}, known_color_names=COLOURS,
        # T78 (D-78-20): this fixture's colours are the ones the plant offers.
        offered_colors={(plant, c): True for c in COLOURS},
        # T112-FIX (D-112F-2): the sheet's model is one the plant offers.
        offered_models={(plant, model.model): True},
    )


# =====================================================================
# C. the running service: upload -> review -> commit
# =====================================================================
def test_fvl_quick_summary_commits_four_facts_per_point(
    engineer, admin, admin_conn, film_cleanup
):  # [1] [5]
    job = f"UR{uuid.uuid4().hex[:8].upper()}"
    data = pelt(FVL_GOLD_94[:3] + ("094LBOXSIDE",), job=job, vin=0)
    reviews = sent(engineer, film_cleanup, admin_conn, f"P703-{job}-AB.xlsx", data, "FVL")

    assert "P703 | Clearcoat" not in reviews, "out-of-scope diagram creates no rejected data batch"

    review = reviews["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file = engineer.get(f"/api/v1/plants/FVL/workbooks/{review['batch']['file_hash']}").json()["workbook"]
    assert {s["source_sheet"] for s in file["skipped_sheets"]} == {"P703 | Clearcoat"}
    assert all(s["reason"] for s in file["skipped_sheets"])
    assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"]["notes"]
    assert batch_domain(admin_conn, load_id)[:2] == ("FILMTHICKNESS", "FILMTHICKNESS")
    assert review["batch"]["counts"]["rows_loaded"] == 4
    assert review["commit_blockers"] == [], review["commit_blockers"]

    result = commit(engineer, admin, review)
    assert result["measurements_inserted"] == 16
    facts = film_facts(admin_conn, load_id)
    assert len(facts) == 16
    by_row: dict[int, set[str]] = {}
    for f in facts:
        by_row.setdefault(f[0], set()).add(f[2])
    assert all(layers == {"ECOAT", "PRIMER", "BASE", "CLEAR"} for layers in by_row.values())
    assert {f[4] for f in facts} == {"P703 DBL RANGER"}
    assert {(f[7], f[8]) for f in facts} == {(job, None)}
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 0, "film facts never reach wavescan"
        cur.execute(
            "SELECT after ->> 'domain', (after ->> 'measurements_inserted')::int "
            "FROM audit_event WHERE action = 'batch.commit' AND entity_id = %s",
            (str(load_id),),
        )
        assert cur.fetchone() == ("FILMTHICKNESS", 16)
        cur.execute(
            "SELECT status, rows_in_file = rows_loaded + rows_duplicate + "
            "rows_rejected + rows_quarantine FROM load_batch WHERE load_id = %s",
            (load_id,),
        )
        assert cur.fetchone() == ("COMMITTED", True), "ck_batch_balance holds"


def test_ftm_rb_extras_are_quarantined_and_never_facts(
    engineer, admin, admin_conn, film_cleanup
):  # [3] [4]
    # T99 CHANGE (D-99-5, D-99-6, D-99-7, D-99-10). Three rules change what
    # this file means at FTM, and the test now says each of them:
    #   * the Job Number must be FTM's shape (seven digits), so the random
    #     one is 7 digits rather than up to 9;
    #   * `095RBXFLOOR`-`098TGATEIN` and `021LAPILLAR` are real points of
    #     FTM's 98-name Raptor walk, so "extra point" is no longer what they
    #     are -- the names that are not on it are the FVL-only ones;
    #   * `001FTWISH` is the known tail of the walk: kept, not stored, and
    #     never a hold;
    #   * the body labels have to be the walk or a prefix of it, so the file
    #     walks the first four points and then the tail.
    # What the test still proves is the half that has not changed: an FTWISH
    # label never becomes a fact, and nothing off the list is taught as a
    # model.
    name = f"AW_RB_{uuid.uuid4().int % 10**7:07d}.xlsx"
    walk = ["001HOOD", "002HOOD", "003HOOD", "004HOOD"]
    data = pelt([*walk, "001FTWISH"], colour="Arctic White",
                comments="PROG_BL / FTM_FILM_BODY / RANGER_RAP",
                job=name[:-5], title="Ford Thailand Motors - PELT Filmbuild Report")
    review = sent(engineer, film_cleanup, admin_conn, name, data, "FTM")["Quick Summary"]
    load_id = review["batch"]["load_id"]
    counts = review["batch"]["counts"]
    assert (counts["rows_loaded"], counts["rows_quarantine"]) == (4, 0)
    projection = review_rows(admin_conn, load_id)
    tails = sorted(r[1] for r in projection.values() if r[0] == "AGGREGATE_ROW")
    assert tails == ["FILM_TAIL_LABEL"]
    assert {r[2]["model"] for r in projection.values() if r[0] == "LOAD"} == {"P703 DBL RAPTOR"}

    commit(engineer, admin, review)
    facts = film_facts(admin_conn, load_id)
    assert {f[1] for f in facts} == set(walk)
    assert not any("FTWISH" in f[9] for f in facts), "the tail is never a fact"
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM unidentified_model WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 0, "a label off the list is not a model to teach"


def test_ftm_rap_commits_as_rapcap(engineer, admin, admin_conn, film_cleanup):  # [2]
    name = f"AW_RAP_{uuid.uuid4().int % 10**7:07d}.xlsx"
    data = pelt(FTM_RAPCAP_93[:2], colour="Arctic White", job=name[:-5])
    review = sent(engineer, film_cleanup, admin_conn, name, data, "FTM")["Quick Summary"]
    commit(engineer, admin, review)
    assert {f[4] for f in film_facts(admin_conn, review["batch"]["load_id"])} == {"P703 RAPCAP"}


def test_cab_and_box_are_two_loads_of_one_car(
    engineer, admin, admin_conn, film_cleanup
):  # [7]
    day = _day()
    cab = pelt(["001HOOD", "002HOOD"], colour="Traction Green", day=day, job="",
               title="FORD TH- PELT Filmbuild Report", diagram=False)
    # T57 CHANGE (D-57-01): AAT box-side gold is its own Sep names
    # (059-065LBOXSIDE); FVL `036LBOXSIDE` is no longer an AAT point.
    box = pelt(["059LBOXSIDE", "060LBOXSIDE"], colour="Traction Green", day=day,
               job="", title="FORD TH- PELT Filmbuild Report  ", diagram=False)
    tag = uuid.uuid4().hex[:6]
    one = sent(engineer, film_cleanup, admin_conn, f"Data Pelt P703 Cab {tag}.xlsx", cab, "AAT")
    two = sent(engineer, film_cleanup, admin_conn, f"Data Pelt P703 Box {tag}.xlsx", box, "AAT")
    ids = []
    for reviews in (one, two):
        review = reviews["Quick Summary"]
        commit(engineer, admin, review)
        ids.append(review["batch"]["load_id"])
    assert ids[0] != ids[1], "two hashes stay two load_id (ADR 0005)"
    cars = {f[6] for i in ids for f in film_facts(admin_conn, i)}
    assert len(cars) == 1
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT point_code) FROM filmthickness_active "
            "WHERE logical_vehicle_id = %s", (cars.pop(),)
        )
        assert cur.fetchone()[0] == 4, "completeness is distinct points across loads"


def test_sap_ods_quick_summary_parses_and_the_link_stub_is_out_of_scope(
    engineer, admin, admin_conn, film_cleanup
):
    vin = f"TP{uuid.uuid4().int % 10**6:06d}"
    data = sap_ods(["012HOOD", "007HOOD"], vin=vin)
    reviews = sent(engineer, film_cleanup, admin_conn,
                   f"13082026 7V P703 CC C2 {vin} PELT.ods", data, "SAP")
    assert set(reviews) == {"QUICK_SUMMARY"}, "linked workbook stub creates no data batch"
    review = reviews["QUICK_SUMMARY"]
    file = engineer.get(f"/api/v1/plants/SAP/workbooks/{review['batch']['file_hash']}").json()["workbook"]
    assert file["skipped_sheet_count"] == 1
    assert file["skipped_sheets"][0]["reason"]
    assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"]["notes"]
    commit(engineer, admin, review)
    facts = film_facts(admin_conn, review["batch"]["load_id"])
    assert {(f[1], f[8]) for f in facts} == {("012HOOD", vin), ("007HOOD", vin)}
    assert {f[5] for f in facts} == {"Frozen White"}


def test_a_committed_film_batch_cannot_be_replayed(
    engineer, admin, admin_conn, film_cleanup
):
    job = f"UR{uuid.uuid4().hex[:8].upper()}"
    review = sent(engineer, film_cleanup, admin_conn, f"P703-{job}-FW.xlsx",
                  pelt(["001HOOD"], job=job, diagram=False), "FVL")["Quick Summary"]
    commit(engineer, admin, review)
    with admin_conn.cursor() as cur, pytest.raises(psycopg.errors.RaiseException):
        cur.execute("SELECT reset_batch_staging(%s)", (review["batch"]["load_id"],))


def test_wavescan_upload_of_p703_rapcap_writes_no_wavescan_row(
    engineer, admin_conn, film_cleanup
):  # [10]
    rows = unique_rows(2, Plant="FTM", Model="P703 RAPCAP")
    reviews = sent(engineer, film_cleanup, admin_conn, "t46-rapcap-wavescan.xlsx",
                   make_workbook(rows), "FTM")
    review = reviews["PasteData"]
    assert review["batch"]["counts"]["rows_loaded"] == 0
    assert review["batch"]["counts"]["rows_rejected"] == 2
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM stg_review_row WHERE load_id = %s "
            "AND canonical ->> 'model' = 'P703 DBL RANGER'",
            (review["batch"]["load_id"],),
        )
        assert cur.fetchone()[0] == 0, "never relabelled Ranger"


def test_a_wavescan_mapping_onto_a_film_only_model_is_422(
    engineer, sample_load_id
):  # [10]
    response = engineer.post(
        "/api/v1/mappings/proposals",
        json={"kind": "ALIAS_MODEL", "load_id": sample_load_id,
              "payload": {"raw_value": "P703 RAP", "model_code": "P703 RAPCAP"}},
    )
    assert response.status_code == 422, response.text
    assert "not this domain" in response.text


def test_standards_catalogue_keeps_film_only_models_off(admin):  # [10]
    # T112-FIX (D-112F-4): Attach / Remove now accept a Film-only model (the
    # offer gates Film ingest too), so this is no longer 422. P703 SGL is
    # already offered at FTM (0036), so Attach answers 409 and writes nothing.
    # The Wave Scan catalogue still leaves Film-only models out.
    response = admin.post(
        "/api/v1/standards/plant-models",
        json={"model_code": "P703 SGL", "plants": ["FTM"]},
    )
    assert response.status_code == 409, response.text
    assert "already attached" in response.text
    catalogue = admin.get("/api/v1/standards/catalogue").json()
    listed = {m["model_code"] for s in catalogue.get("series", []) for m in s.get("models", [])}
    assert "P703 SGL" not in listed and "P703 RAPCAP" not in listed
