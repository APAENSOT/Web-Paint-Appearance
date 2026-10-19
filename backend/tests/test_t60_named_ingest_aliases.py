"""T60 -- named ingest leftovers: SAP P703 RAP, Film headers, colour aliases.

Claims (task section 4), on synthetic workbooks:

* SAP WaveScan ``P703 RAP`` is Raptor; FTM Film ``_RAP_`` is still RAPCAP;
  no Film ``P703 RAP`` / ``RAP`` token exists at SAP; teaching WaveScan
  ``P703 RAP`` onto RAPCAP is still 422.
* Film ``Mid Grey`` -> primer, ``EPIC`` -> ecoat, ``Basecoat1`` / ``L28 BC1``
  -> primer, ``Basecoat2`` -> base, each as facts.
* ``Orientation`` and ``Ground-coat`` are recognised non-facts: no Ignore
  question, no duplicate refusal when both are present, no thickness from
  them.
* The two swatch aliases exist at AAT, FVL, SAP and FTM; RO05 (owner,
  2026-10-12): Snowflake White is never Arctic White and, if it resolves, is
  Pearl White; no colour was minted; an alias onto a
  colour a plant does not offer is still ``COLOR_NOT_OFFERED`` (WaveScan).
* Viewer 403 on load-ready; no UPDATE / DELETE grants; grading stays off.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine

from app.domain.cleaner import Cleaner, CleanRow, Reject, RejectReason
from app.domain.film import FilmCleaner, resolve_film_model
from app.domain.film_header import IGNORED_FIELD, LAYER_FIELDS, NON_FACT_FIELDS
from app.domain.reader import RawRow, describe_film_sheet, read_film_sheet
from app.repositories.filmthickness import load_film_reference
from app.repositories.reference import load_reference_data
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import FILM_ALIAS, M23, film_cleanup, film_facts, sent  # noqa: F401

pytestmark = pytest.mark.ingest

T60_FILM_ALIAS = {**FILM_ALIAS, **dict(M23.FILM_COLUMN_ALIASES)}
# RO05 CHANGE: `Snowflake White_4 -> Arctic White` left (0041; owner: it is Pearl White).
SWATCHES = {"Aluminum Met_4": "Aluminum Metallic", "DesertIslandBlu_4": "Desert Island Blue"}
MEASURES = {m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")}


@pytest.fixture(scope="module")
def refs(app_database_url):
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            found = (load_reference_data(conn), load_film_reference(conn))
    finally:
        engine.dispose()
    return found


def qs(headers: list[str], locations: list[str], *, colour="Absolute Black",
       day="12-Feb-03", job="UR1") -> bytes:
    """A PELT Quick Summary with the given header row (row 14)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Quick Summary"
    ws.append(["Ford Vietnam - PELT Filmbuild Report"])
    ws.append([])
    ws.append(["Date:", day])
    ws.append(["Time:", "09:43 PM", None, "Number of Points:", len(locations)])
    ws.append(["Operator:", "T60", None, "File Name:", "synthetic.prn"])
    ws.append(["Job Number:", job, None, "Booth:", 1])
    ws.append(["Layer 1:", "Clearcoat", None, "Shift:", "1st"])
    ws.append(["Layer 2:", colour, None, "Vin:", 0])
    ws.append(["Layer 3:", "Primer", None, "Report:", "Quick Summary"])
    ws.append(["Layer 4:", "E-Coat"])
    ws.append(["Layer 5:", "Steel"])
    ws.append(["Layer 6:", ""])
    ws.append(["Comments:", "", None, None, None, None, "Total"])
    ws.append(["Location", *headers])
    for i, loc in enumerate(locations):
        cells = []
        for h in headers:
            low = h.lower()
            if low == "orientation":
                cells.append("Horizontal")
            elif low == "ground-coat":
                cells.append(99.9)
            else:
                cells.append(10.0 + i + len(cells))
        ws.append([loc, *cells])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def film_rows(refs, data, plant="FVL", filename="P703-UR1-AB.xlsx"):
    template = describe_film_sheet(data, "Quick Summary", T60_FILM_ALIAS)
    rows = list(read_film_sheet(data, "Quick Summary", template, filename))
    model = resolve_film_model(plant, filename, "Quick Summary", refs[1].model_alias)
    result = FilmCleaner(
        refs[1], plant=plant, model=model, meta=template.meta_map,
        color_by_plant=refs[0].color_by_plant, color=refs[0].color,
        known_color_names=sorted(refs[0].known_color_names),
        # T78 (D-78-20): the live `ref_plant_color` offer list, as ingest uses.
        offered_colors=refs[0].offered_colors,
        # T112-FIX (D-112F-2): the live `ref_plant_model` offer list, as ingest uses.
        offered_models=refs[0].offered_models,
    ).clean_all(rows)
    return template, result


# =====================================================================
# A. SAP WaveScan P703 RAP vs Film RAP
# =====================================================================
def test_sap_wavescan_p703_rap_is_raptor_and_film_rap_is_still_rapcap(refs, admin_conn):
    ref, film = refs
    cleaner = Cleaner(ref, ("SAP",), expected_plant="SAP")
    assert cleaner.plant_first(ref.model_by_plant, ref.model, "SAP", "P703 RAP") == "P703 DBL RAPTOR"
    out = cleaner.clean_row(RawRow("t60.xlsx", "s", 2, dict(
        date="2026-09-08", plant="SAP", model="P703 RAP", checkzone="01 RRHOOD",
        color="Frozen White", **MEASURES)))
    assert not (isinstance(out, Reject) and out.reason == RejectReason.UNKNOWN_MODEL), out
    if isinstance(out, CleanRow):
        assert out.model == "P703 DBL RAPTOR"
    assert resolve_film_model("FTM", "AW_RAP_1.xlsx", "Quick Summary", film.model_alias).model == "P703 RAPCAP"
    assert ("SAP", "RAP") not in film.model_alias and ("SAP", "P703 RAP") not in film.model_alias
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code, note FROM ref_model_alias WHERE raw_value = 'P703 RAP'"
        )
        assert cur.fetchall() == [("SAP", "P703 DBL RAPTOR", "T60 owner lock 2026-10-05")]


def test_teaching_wavescan_p703_rap_onto_rapcap_is_still_422(engineer, admin_conn):  # noqa: F811
    from tests.test_t04_ingest import cleanup as _c  # noqa: F401
    from tests.test_t04_ingest import forget_bytes, make_workbook, unique_rows, upload, wait_for

    data = make_workbook(unique_rows(1, Plant="SAP", Model="P703 RAPX"))
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t60-rapcap.xlsx", data, expected_plant="SAP")
    assert accepted.status_code == 202, accepted.text
    load_id = accepted.json()["batches"][0]["load_id"]
    try:
        wait_for(engineer, load_id)
        response = engineer.post("/api/v1/mappings/proposals", json={
            "kind": "ALIAS_MODEL", "load_id": load_id,
            "payload": {"raw_value": "P703 RAPX", "model_code": "P703 RAPCAP"},
        })
        assert response.status_code == 422, response.text
    finally:
        forget_bytes(admin_conn, data)


# =====================================================================
# B. Film headers
# =====================================================================
def test_the_film_vocabulary_has_the_named_headers():
    assert T60_FILM_ALIAS["mid grey"] == T60_FILM_ALIAS["basecoat1"] == "primer"
    assert T60_FILM_ALIAS["basecoat 1"] == T60_FILM_ALIAS["l28 bc1"] == "primer"
    assert T60_FILM_ALIAS["basecoat2"] == T60_FILM_ALIAS["basecoat 2"] == "base"
    assert T60_FILM_ALIAS["epic"] == "ecoat"
    for raw in ("ground-coat", "ground coat", "orientation"):
        assert T60_FILM_ALIAS[raw] == IGNORED_FIELD
    assert IGNORED_FIELD in NON_FACT_FIELDS and IGNORED_FIELD not in LAYER_FIELDS
    assert T60_FILM_ALIAS["mid grey prime"] == "primer", "the existing primer spelling stays"


def test_mid_grey_and_epic_become_primer_and_ecoat_facts(refs):
    data = qs(["Clearcoat", "Absolute Black", "Mid Grey", "EPIC", "Steel", "Thickness"],
              ["001HOOD", "002HOOD"])
    template, result = film_rows(refs, data)
    assert template.missing_required == () and template.unrecognised == ()
    assert {r.point_code for r in result.clean} == {"001HOOD", "002HOOD"}
    for row in result.clean:
        assert set(row.layers) == {"CLEAR", "BASE", "PRIMER", "ECOAT"}


@pytest.mark.parametrize("primer, base", [("Basecoat1", "Basecoat2"), ("L28 BC1", "Basecoat 2")])
def test_basecoat_headers_are_primer_and_base(refs, primer, base):
    data = qs(["Clearcoat", base, primer, "E-Coat"], ["001HOOD"])
    template, result = film_rows(refs, data)
    assert template.unrecognised == ()
    [row] = result.clean
    assert row.layers == {"CLEAR": Decimal("10.0"), "BASE": Decimal("11.0"),
                          "PRIMER": Decimal("12.0"), "ECOAT": Decimal("13.0")}


def test_orientation_and_ground_coat_are_non_facts_and_ask_nothing(refs):
    data = qs(["Clearcoat", "Absolute Black", "Mid Grey", "E-Coat", "Orientation", "Ground-coat"],
              ["001HOOD"])
    template, result = film_rows(refs, data)
    assert template.unrecognised == (), "no Ignore question"
    assert template.duplicates == (), "two named non-facts are not one field twice"
    assert template.missing_required == ()
    [row] = result.clean
    assert set(row.layers) == {"CLEAR", "BASE", "PRIMER", "ECOAT"}
    assert Decimal("99.9") not in row.layers.values(), "Ground-coat is never a layer"


# =====================================================================
# C. colour aliases
# =====================================================================
def test_swatch_aliases_exist_at_every_plant_and_mint_nothing(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, raw_value, color_name FROM ref_color_alias "
            "WHERE raw_value = ANY(%s) AND plant_code IS NOT NULL",
            (list(SWATCHES),),
        )
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM ref_color WHERE color_name ILIKE 'Snowflake%'")
        snowflake = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ref_color WHERE color_name = 'Pearl White'")
        pearl = cur.fetchone()[0]
        cur.execute(
            "SELECT DISTINCT color_name FROM ref_color_alias WHERE raw_value ILIKE 'Snowflake%'"
        )
        snowflake_aliases = {r[0] for r in cur.fetchall()}
    assert {(p, raw): colour for p, raw, colour in rows} == {
        (p, raw): colour for p in ("AAT", "FVL", "SAP", "FTM") for raw, colour in SWATCHES.items()
    }
    assert "Pearl White" not in {c for _p, _r, c in rows}, "no T60 swatch is Pearl White"
    assert snowflake == 0 and pearl == 1
    assert snowflake_aliases <= {"Pearl White"}, "a Snowflake alias, if any (RO06), is Pearl White"


def test_film_snowflake_at_ftm_is_never_arctic_white(refs):
    # RO05 CHANGE (owner, 2026-10-12): Snowflake White is Pearl White, never Arctic
    # White. Valid now (no Snowflake alias) and after RO06 (alias -> Pearl White).
    data = qs(["Clearcoat", "Snowflake White_4", "Mid Grey", "E-Coat"], ["001HOOD"],
              colour="Snowflake White_4")
    _t, result = film_rows(refs, data, plant="FTM", filename="AW_DBL_1.xlsx")
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


def test_wavescan_alias_onto_an_unoffered_colour_is_still_not_offered(refs):
    ref = refs[0]
    assert ref.color_by_plant[("FVL", "aluminum met_4")] == "Aluminum Metallic"
    assert not ref.offered_colors.get(("FVL", "Aluminum Metallic"), False)
    out = Cleaner(ref, ("FVL",), expected_plant="FVL").clean_row(RawRow("t60.xlsx", "s", 2, dict(
        date="2026-09-08", plant="FVL", model="P703", checkzone="1HOOD",
        color="Aluminum Met_4", **MEASURES)))
    assert isinstance(out, Reject) and out.reason == RejectReason.COLOR_NOT_OFFERED
    assert out.value == "Aluminum Met_4"


# =====================================================================
# D. the running application
# =====================================================================
def test_a_film_upload_with_named_headers_is_ready_and_loads(
    engineer, viewer, admin_conn, film_cleanup  # noqa: F811
):
    n = uuid.uuid4().int
    day = f"{n % 28 + 1:02d}-{('Jan', 'Feb', 'Mar', 'Apr')[n % 4]}-{n % 9 + 1:02d}"
    job = f"UR{uuid.uuid4().hex[:8].upper()}"
    data = qs(["Clearcoat", "Absolute Black", "Mid Grey", "EPIC", "Orientation"],
              ["001HOOD", "002HOOD"], day=day, job=job)
    review = sent(engineer, film_cleanup, admin_conn, f"P703-{job}-AB.xlsx", data, "FVL")["Quick Summary"]
    assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"].get("notes")
    assert "UNREVIEWED_HEADER" not in review["commit_blockers"]
    file_hash = review["batch"]["file_hash"]
    body = engineer.get(f"/api/v1/plants/FVL/workbooks/{file_hash}/worksheet").json()
    sheet = {s["sheet"]: s for s in body["sheets"]}["Quick Summary"]
    assert sheet["state"] == "ready" and sheet["extra_columns"] == [], sheet["operator_message"]
    assert viewer.post(f"/api/v1/plants/FVL/workbooks/{file_hash}/load-ready").status_code == 403
    loaded = engineer.post(f"/api/v1/plants/FVL/workbooks/{file_hash}/load-ready")
    assert loaded.status_code == 200, loaded.text
    facts = film_facts(admin_conn, review["batch"]["load_id"])
    assert {f[2] for f in facts} == {"CLEAR", "BASE", "PRIMER", "ECOAT"}
    assert len(facts) == 8, "two points x four layers; Orientation wrote nothing"
    assert engineer.get("/api/v1/meta").json()["grading_available"] is False


def test_no_new_write_grants(admin_conn, app_role: str):
    with admin_conn.cursor() as cur:
        for table in ("ref_model_alias", "ref_column_alias", "ref_color_alias"):
            cur.execute("SELECT has_table_privilege(%s, %s, 'DELETE')", (app_role, table))
            assert cur.fetchone()[0] is False, table
        for table in ("wavescan", "filmthickness"):
            for privilege in ("UPDATE", "DELETE"):
                cur.execute("SELECT has_table_privilege(%s, %s, %s)", (app_role, table, privilege))
                assert cur.fetchone()[0] is False, (table, privilege)


def test_no_proving_workbook_in_tests():
    here = Path(__file__).resolve().parent
    assert not [p for p in here.rglob("*") if p.suffix.lower() in (".xlsx", ".ods")]
