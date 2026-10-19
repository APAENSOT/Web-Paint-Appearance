"""T56 -- AAT EC1 / Byk banner identity (date / colour / job).

Claims (task section 5), on synthetic workbooks shaped like the live
`Data Pelt {P703|U704}_Sep26.xlsx` tabs (no Date / Color column):

* The banner datetime is the date, the ``_4`` swatch is the colour, the
  sample line is the job; the sheet is not ``missing_required`` and its
  rows load on T55 gold with that identity.
* Two banners of one colour with different sample lines are two cars.
* No banner datetime -> still missing date (never the upload day).
* ``Aluminum Met_4`` / ``DesertIslandBlu_4`` take their T57 AAT alias;
  ``Snowflake White_4`` never cleans to Arctic White and, if it resolves, is
  Pearl White (RO05); nothing is guessed or minted.
* The sample line is job text only: ``2507117 P704 A4D`` on a P703 tab
  never makes a model.
* SAP ``.ods`` ``Date:`` / ``Layer 2:`` is unchanged.
* Live: an AAT U704 EC1 upload with no identity columns is ready and loads
  with banner date, colour and job.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine

from app.domain.film import FilmCleaner, resolve_film_model
from app.domain.reader import describe_film_sheet, read_film_sheet
from app.repositories.filmthickness import load_film_reference
from app.repositories.reference import load_reference_data
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import (
    FILM_ALIAS,
    film_cleanup,  # noqa: F401
    film_facts,
    sap_ods,
    sent,
)

pytestmark = pytest.mark.ingest

LAYERS = (40.0, 12.0, 20.0, 18.0)


def ec1(locations, *, sheet: str = "U704_5ZT", sample: str = "2502647 U704 5ZT",
        swatch: str = "Command Grey_4", stamp: datetime | None = datetime(2026, 9, 8, 9, 30),
        model_text: str = "U704") -> bytes:
    """The live Byk banner: sample, timestamp twice, PELT AAT, swatch, model."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append([sample, None, None, None, stamp, None, None, None, stamp, None, None, None,
               "", None, None, None, f"PELT AAT {model_text}", None, None, None, swatch,
               None, None, None, model_text, None, None, None, "D65/10", None, None, None,
               "BS01280"])
    ws.append([swatch, None, "total mic", "CC1 mic", "BC2 mic", "BC1 mic", "EC1 mic"])
    ws.append(["Fail High", None, 100, 45, 25, 15, 30])
    ws.append(["Warning High"])
    ws.append(["Warning Low"])
    ws.append(["Fail Low", None, 65, 25, 10, 7, 16])
    ws.append(["Checkzone", "Status", "total mic", "CC1 mic", "BC2 mic", "BC1 mic", "EC1 mic"])
    ws.append(["Match to Standard"])
    for loc in locations:
        ws.append([loc, "Pass", sum(LAYERS), *LAYERS])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def refs(app_database_url):
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            found = (load_reference_data(conn), load_film_reference(conn))
    finally:
        engine.dispose()
    return found


def clean(refs, data, filename, sheet, plant="AAT"):
    template = describe_film_sheet(data, sheet, FILM_ALIAS)
    rows = list(read_film_sheet(data, sheet, template, filename))
    model = resolve_film_model(plant, filename, sheet, refs[1].model_alias)
    return FilmCleaner(
        refs[1], plant=plant, model=model, meta=template.meta_map,
        color_by_plant=refs[0].color_by_plant, color=refs[0].color,
        known_color_names=sorted(refs[0].known_color_names),
        # T78 (D-78-20): the live `ref_plant_color` offer list, as ingest uses.
        offered_colors=refs[0].offered_colors,
        # T112-FIX (D-112F-2): the live `ref_plant_model` offer list, as ingest uses.
        offered_models=refs[0].offered_models,
    ).clean_all(rows)


# =====================================================================
# A. the banner
# =====================================================================
def test_an_ec1_sheet_without_identity_columns_reads_its_banner():
    template = describe_film_sheet(ec1(["001HOOD"]), "U704_5ZT", FILM_ALIAS)
    assert template.sheet_class == "FILMTHICKNESS" and template.header_row == 7
    assert "date" not in template.recognised.values()
    assert "color" not in template.recognised.values()
    assert template.missing_required == ()
    meta = template.meta_map
    assert meta["date"] == datetime(2026, 9, 8, 9, 30)
    assert meta["banner colour"] == "Command Grey_4"
    assert meta["job number"] == "2502647 U704 5ZT"


def test_rows_take_the_banner_identity_and_load_on_t55_gold(refs):
    result = clean(refs, ec1(["001HOOD", "095Roof LH"]), "Data Pelt U704_Sep26.xlsx", "U704_5ZT")
    assert [r.point_code for r in result.clean] == ["001HOOD", "095ROOFLH"]
    for row in result.clean:
        assert (row.model, row.color, row.measured_date.isoformat(), row.job_no, row.serial_no) == (
            "U704", "Command Grey", "2026-09-08", "2502647 U704 5ZT", None,
        )


def test_two_banners_of_one_colour_are_two_cars(refs):
    one = clean(refs, ec1(["001HOOD"], sample="2502647 U704 5ZT"),
                "Data Pelt U704_Sep26.xlsx", "U704_5ZT")
    two = clean(refs, ec1(["001HOOD"], sample="2502999 U704 5ZT"),
                "Data Pelt U704_Sep26.xlsx", "U704_5ZT")
    assert one.clean[0].color == two.clean[0].color
    assert one.clean[0].logical_vehicle_id != two.clean[0].logical_vehicle_id


def test_no_banner_datetime_is_still_missing_date():
    template = describe_film_sheet(ec1(["001HOOD"], stamp=None), "U704_5ZT", FILM_ALIAS)
    # RO18 (B4): a sheet with no date is read and asked its month (it is never
    # filled from the upload day), so it is no longer a missing field.
    assert "date" not in template.missing_required
    assert "date" not in template.meta_map


def test_a_swatch_the_banner_does_not_repeat_is_not_trusted(refs):
    wb_bytes = ec1(["001HOOD"])
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(wb_bytes))
    wb.active["A2"] = "Shadow Black_4"   # not the banner's swatch
    buffer = io.BytesIO()
    wb.save(buffer)
    template = describe_film_sheet(buffer.getvalue(), "U704_5ZT", FILM_ALIAS)
    assert "banner colour" not in template.meta_map
    assert template.missing_required == ("color",)


@pytest.mark.parametrize("swatch, colour", [
    # T57 CHANGE (D-57-06): the owner named these three AAT swatches.
    ("Aluminum Met_4", "Aluminum Metallic"),
    ("DesertIslandBlu_4", "Desert Island Blue"),
    # RO05 CHANGE: `Snowflake White_4` is no longer Arctic White; its own test below.
])
def test_named_live_swatches_take_their_aat_alias(refs, swatch, colour):
    result = clean(refs, ec1(["001HOOD", "002HOOD"], swatch=swatch),
                   "Data Pelt U704_Sep26.xlsx", "U704_5ZT")
    assert result.rejects == []
    assert {r.color for r in result.clean} == {colour}


def test_the_snowflake_swatch_never_cleans_to_arctic_white(refs):
    # RO05 CHANGE (owner, 2026-10-12): Snowflake White is Pearl White, never Arctic
    # White. Valid now (no Snowflake alias) and after RO06 (alias -> Pearl White).
    result = clean(refs, ec1(["001HOOD", "002HOOD"], swatch="Snowflake White_4"),
                   "Data Pelt U704_Sep26.xlsx", "U704_5ZT")
    colours = {r.color for r in result.clean}
    assert "Arctic White" not in colours, "Snowflake White is never Arctic White (owner, 2026-10-12)"
    assert colours <= {"Pearl White"}, "if it resolves, it is Pearl White"
    for reject in result.rejects:
        assert "Arctic White" not in reject.detail, reject
        assert reject.reason == "UNKNOWN_COLOR" or (
            reject.reason == "COLOR_NOT_OFFERED" and "Pearl White" in reject.detail
        ), reject
    assert not [n for n in refs[0].known_color_names if n.lower().startswith("snowflake")], (
        "no Snowflake colour is minted"
    )


def test_an_unnamed_swatch_still_holds_unknown_color(refs):
    result = clean(refs, ec1(["001HOOD"], swatch="Moonlit Teal_4"),
                   "Data Pelt U704_Sep26.xlsx", "U704_5ZT")
    assert result.clean == []
    assert {(r.reason, r.value) for r in result.rejects} == {("UNKNOWN_COLOR", "Moonlit Teal_4")}


def test_the_sample_line_is_job_text_never_a_model(refs):
    data = ec1(["001HOOD"], sheet="P703_A4D", sample="2507117 P704 A4D",
               swatch="Arctic White_4", model_text="P703 DBL-RANGER")
    result = clean(refs, data, "Data Pelt P703_Sep26.xlsx", "P703_A4D")
    [row] = result.clean
    assert (row.model, row.job_no, row.color) == ("P703 DBL RANGER", "2507117 P704 A4D", "Arctic White")


def test_sap_pelt_labels_are_unchanged():
    template = describe_film_sheet(sap_ods(["001HOOD"]), "QUICK_SUMMARY", FILM_ALIAS)
    meta = template.meta_map
    assert template.missing_required == ()
    assert meta["date"] == "12-Aug-26" and meta["layer 2"] == "Frozen White"
    assert "banner colour" not in meta


# =====================================================================
# B. the running application
# =====================================================================
def test_a_live_shaped_u704_upload_is_ready_and_loads_with_banner_identity(
    engineer, viewer, admin_conn, film_cleanup  # noqa: F811
):
    n = uuid.uuid4().int
    stamp = datetime(2001 + n % 15, (n // 15) % 12 + 1, (n // 180) % 28 + 1, 9, 30)
    sample = f"25{n % 10**5:05d} U704 5ZT"
    name = f"Data Pelt U704_{uuid.uuid4().hex[:6]}.xlsx"
    data = ec1(["001HOOD", "095Roof LH"], sample=sample, stamp=stamp)
    review = sent(engineer, film_cleanup, admin_conn, name, data, "AAT")["U704_5ZT"]
    assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"].get("notes")
    file_hash = review["batch"]["file_hash"]

    body = engineer.get(f"/api/v1/plants/AAT/workbooks/{file_hash}/worksheet").json()
    [sheet] = body["sheets"]
    assert sheet["state"] == "ready", (sheet["operator_message"], sheet["commit_blockers"])
    ready = [r for r in sheet["rows"] if r["outcome"] == "ready"]
    assert {(r["panel_label"], r["checkzone"], r["model"], r["color"]) for r in ready} == {
        ("001HOOD", "001HOOD", "U704", "Command Grey"),
        ("095Roof LH", "095ROOFLH", "U704", "Command Grey"),
    }
    assert viewer.post(f"/api/v1/plants/AAT/workbooks/{file_hash}/load-ready").status_code == 403
    loaded = engineer.post(f"/api/v1/plants/AAT/workbooks/{file_hash}/load-ready")
    assert loaded.status_code == 200, loaded.text
    facts = film_facts(admin_conn, review["batch"]["load_id"])
    assert {(f[1], f[4], f[5], f[7], f[8]) for f in facts} == {
        ("001HOOD", "U704", "Command Grey", sample, None),
        ("095ROOFLH", "U704", "Command Grey", sample, None),
    }
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT measured_date FROM filmthickness WHERE load_id = %s",
            (review["batch"]["load_id"],),
        )
        assert [r[0] for r in cur.fetchall()] == [stamp.date()]


def test_no_proving_workbook_is_in_tests():
    here = Path(__file__).resolve().parent
    assert not [p for p in here.rglob("*") if p.suffix.lower() in (".xlsx", ".ods")]
