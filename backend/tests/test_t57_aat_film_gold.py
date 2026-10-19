"""T57 -- AAT P703 Film gold = Sep Checkzone 94 + named AAT colour aliases.

Claims (task section 6), on synthetic workbooks (the proving xlsx is never
read here):

* Revision 0021 made AAT x P703 DBL RANGER live gold exactly the evidence
  94, in Sep order with D-53-06 Hor/Ver and the source hash; the FVL-only
  copy rows are retired (kept), and every AAT T47 map is retired.
  FVL / SAP / FTM Ranger gold and AAT U704 95 are unchanged.
* The 11 D-57-07 names load as themselves; ``073LBXFLOOR`` is AAT left
  floor, never an FVL code; an FVL-only name holds at AAT.
* AAT banner ``Aluminum Met_4`` / ``DesertIslandBlu_4`` are Aluminum
  Metallic / Desert Island Blue; FVL does not inherit the AAT alias.
  RO05 (owner, 2026-10-12): ``Snowflake White_4`` is never Arctic White and,
  if it resolves, is Pearl White; no Snowflake colour is minted.
* A QS-shaped (other-plant layout) AAT sheet still classifies FILMTHICKNESS
  and loads only AAT gold names.
* Live: an AAT P703 EC1 upload is ready and loads; a Viewer is 403; no
  UPDATE / DELETE grants.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine

from app.domain.film import FilmCleaner, resolve_film_model
from app.domain.film_catalog import FVL_GOLD_94
from app.domain.reader import describe_film_sheet, read_film_sheet
from app.repositories.filmthickness import load_film_reference
from app.repositories.reference import load_reference_data
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import (
    FILM_ALIAS,
    film_cleanup,  # noqa: F401
    film_facts,
    pelt,
    sent,
)

pytestmark = pytest.mark.ingest

REPO = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO / "backend" / "tests" / "fixtures" / "gold"
AAT = json.loads((EVIDENCE_DIR / "AAT-P703-film-points.json").read_text(encoding="utf-8"))
AAT_GOLD = [p["point_code"] for p in AAT["locations"]]
U704_GOLD = next(
    [p["point_code"] for p in c["locations"]]
    for c in json.loads((EVIDENCE_DIR / "LEFTOVER-film-points.json").read_text(encoding="utf-8"))["catalogues"]
    if (c["plant_code"], c["model_code"]) == ("AAT", "U704")
)
FTM_GOLD = [p["point_code"] for p in json.loads(
    (EVIDENCE_DIR / "FTM-QS-film-points.json").read_text(encoding="utf-8"))["locations"]]
ELEVEN = ["031LTRRDOOR", "032LFDRPOST", "036RTRRDOOR", "037RTDRPOST", "066LBXFRONT",
          "067LBXFRONT", "068RBXFRONT", "069RBXFRONT", "073LBXFLOOR", "074LBXFLOOR",
          "075LBXFLOOR"]
RANGER = "P703 DBL RANGER"
LAYERS = (40.0, 12.0, 20.0, 18.0)


def ec1(locations, *, sheet="P703_38P", sample="2508774 P703 38P", swatch="Aluminum Met_4",
        stamp=datetime(2026, 9, 24, 8, 0), model_text="P703 DBL-RANGER") -> bytes:
    """The live AAT Byk EC1 layout (T56 banner), no Date / Color columns."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append([sample, None, None, None, stamp, None, None, None, stamp, None, None, None,
               "", None, None, None, "PELT AAT P703", None, None, None, swatch,
               None, None, None, model_text, None, None, None, "D65/10"])
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
# A. seed
# =====================================================================
def _gold(cur, plant, model, live=True):
    cur.execute(
        "SELECT point_code, point_no, orientation, proof_hash FROM ref_plant_film_point "
        "WHERE plant_code = %s AND model_code = %s AND (retired_at IS NULL) = %s "
        "ORDER BY point_no, point_code",
        (plant, model, live),
    )
    return cur.fetchall()


def test_aat_p703_live_gold_is_the_sep_94_and_the_fvl_copy_is_retired(admin_conn):
    with admin_conn.cursor() as cur:
        live = _gold(cur, "AAT", RANGER)
        retired = _gold(cur, "AAT", RANGER, live=False)
        fvl = _gold(cur, "FVL", RANGER)
        sap = _gold(cur, "SAP", RANGER)
        ftm = _gold(cur, "FTM", RANGER)
        u704 = _gold(cur, "AAT", "U704")
    assert [r[0] for r in live] == AAT_GOLD
    assert [r[1] for r in live] == list(range(1, 95))
    assert [r[2] for r in live] == [p["orientation"] for p in AAT["locations"]]
    assert {r[3] for r in live} == {AAT["source_sha256"]}
    assert set(ELEVEN) <= set(AAT_GOLD)
    assert {r[0] for r in retired} == set(FVL_GOLD_94) - set(AAT_GOLD)
    assert len(retired) == 64
    assert [r[0] for r in fvl] == list(FVL_GOLD_94) == [r[0] for r in sap]
    # T99 CHANGE (D-99-5): FTM's Ranger walk is 98 now -- the 94 names this
    # test's evidence describes plus 095RBXFLOOR and 096-098TGATEIN, which the
    # real Jul-Oct files walk. The claim here is about AAT, and the FTM line
    # is the control that AAT's list is not FTM's; it still is.
    assert [r[0] for r in ftm][:94] == FTM_GOLD
    assert [r[0] for r in ftm][94:] == [
        "095RBXFLOOR", "096TGATEIN", "097TGATEIN", "098TGATEIN"
    ]
    assert [r[0] for r in live] != [r[0] for r in ftm]
    assert [r[0] for r in u704] == U704_GOLD and len(u704) == 95


def test_every_aat_map_is_retired_and_sap_maps_stay_live(admin_conn, refs):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, count(*) FILTER (WHERE retired_at IS NULL), count(*) "
            "FROM ref_film_location_map WHERE plant_code IN ('AAT', 'SAP') GROUP BY 1"
        )
        got = {p: (live, total) for p, live, total in cur.fetchall()}
    assert got["AAT"][0] == 0 and got["AAT"][1] > 0, "kept as a record, none read"
    assert got["SAP"][0] == got["SAP"][1] > 0
    assert not [k for k in refs[1].location_map if k[0] == "AAT"]


def test_aat_colour_aliases_are_plant_scoped_and_name_no_new_colour(admin_conn, refs):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, raw_value, color_name FROM ref_color_alias "
            "WHERE note = 'T57 owner lock 2026-10-05' ORDER BY raw_value"
        )
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM ref_color WHERE color_name ILIKE 'Snowflake%'")
        snowflake = cur.fetchone()[0]
    assert rows == [
        ("AAT", "Aluminum Met_4", "Aluminum Metallic"),
        ("AAT", "DesertIslandBlu_4", "Desert Island Blue"),
    ], "RO05 CHANGE: the T57 Snowflake -> Arctic White row is gone (0041)"
    assert snowflake == 0, "Snowflake White is not minted"
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT color_name FROM ref_color_alias "
            " WHERE plant_code = 'AAT' AND raw_value ILIKE 'Snowflake%'"
        )
        assert {r[0] for r in cur.fetchall()} <= {"Pearl White"}, (
            "an AAT Snowflake alias, if any (RO06), names Pearl White"
        )
    assert "Pearl White" in refs[0].known_color_names


# =====================================================================
# B. resolve
# =====================================================================
def test_the_eleven_load_as_aat_names_not_fvl_codes(refs):
    result = clean(refs, ec1(ELEVEN), "Data Pelt P703_Sep26.xlsx", "P703_38P")
    assert [(r.src_location_text, r.point_code, r.model) for r in result.clean] == [
        (n, n, RANGER) for n in ELEVEN
    ]
    assert result.held == [] and result.rejects == []
    floor = next(r for r in result.clean if r.point_code == "073LBXFLOOR")
    assert floor.orientation == "H"
    assert not {r.point_code for r in result.clean} & (set(FVL_GOLD_94) - set(AAT_GOLD))


def test_the_whole_sep_walk_loads_and_an_fvl_only_name_holds(refs):
    fvl_only = ["036LBOXSIDE", "059RBXFLOOR"]
    assert not set(fvl_only) & set(AAT_GOLD) and set(fvl_only) <= set(FVL_GOLD_94)
    result = clean(refs, ec1(AAT_GOLD + fvl_only), "Data Pelt P703_Sep26.xlsx", "P703_38P")
    assert [r.point_code for r in result.clean] == AAT_GOLD
    # RO05 CHANGE (owner, RO04): AAT has Film settings, so the name is still held
    # but asked in its own row (T109 `FILM_POINT_UNKNOWN`), not `UNMAPPED_POINT`.
    assert {h.location: h.reason for h in result.held} == {
        name: "FILM_POINT_UNKNOWN" for name in fvl_only
    }


def test_u704_95_is_unchanged(refs):
    walk = [n.replace("ROOFLH", "Roof LH").replace("ROOFCTR", "Roof Ctr") for n in U704_GOLD]
    result = clean(refs, ec1(walk, sheet="U704_5ZT", sample="2502647 U704 5ZT",
                             swatch="Command Grey_4", model_text="U704"),
                   "Data Pelt U704_Sep26.xlsx", "U704_5ZT")
    assert [r.point_code for r in result.clean] == U704_GOLD
    assert {r.model for r in result.clean} == {"U704"}
    assert "095Roof LH" in {r.src_location_text for r in result.clean}


@pytest.mark.parametrize("swatch, colour", [
    ("Aluminum Met_4", "Aluminum Metallic"),
    ("DesertIslandBlu_4", "Desert Island Blue"),
    # RO05 CHANGE: `Snowflake White_4` is no longer Arctic White; its own test below.
])
def test_named_banner_swatches_resolve_at_aat(refs, swatch, colour):
    result = clean(refs, ec1(["001HOOD", "073LBXFLOOR"], swatch=swatch),
                   "Data Pelt P703_Sep26.xlsx", "P703_38P")
    assert result.rejects == []
    assert {r.color for r in result.clean} == {colour}
    assert colour != "Pearl White"


def test_the_snowflake_banner_swatch_is_never_arctic_white_at_aat(refs):
    # RO05 CHANGE (owner, 2026-10-12): Snowflake White is Pearl White, never Arctic
    # White. Valid now (no Snowflake alias) and after RO06 (alias -> Pearl White).
    result = clean(refs, ec1(["001HOOD", "073LBXFLOOR"], swatch="Snowflake White_4"),
                   "Data Pelt P703_Sep26.xlsx", "P703_38P")
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


def test_fvl_reads_the_swatch_through_its_own_t60_alias(refs):
    # T60 CHANGE (D-60-07): the alias is now seeded at FVL too, as its own
    # plant-scoped row -- not inherited from AAT.
    assert refs[0].color_by_plant[("FVL", "aluminum met_4")] == "Aluminum Metallic"
    data = pelt(["001HOOD"], colour="Aluminum Met_4", job="UR1")
    result = clean(refs, data, "P703-UR1-AB.xlsx", "Quick Summary", plant="FVL")

    # T78 CHANGE (D-78-20). What this test is about is unchanged: FVL reads
    # the swatch through its OWN plant-scoped alias, so the spelling resolves
    # and folds to the catalogue name. What changed is what happens next --
    # FVL does not OFFER Aluminum Metallic, so the row is now held
    # COLOR_NOT_OFFERED instead of becoming a fact. Resolution and offer are
    # two separate questions, and this proves both answers.
    assert not refs[0].offered_colors.get(("FVL", "Aluminum Metallic"), False)
    assert result.clean == []
    [held] = result.rejects
    assert held.reason == "COLOR_NOT_OFFERED"
    assert held.value == "Aluminum Met_4"          # the spelling the file used
    assert "Aluminum Metallic" in held.detail      # the name it resolved to


def test_a_qs_shaped_aat_sheet_still_classifies_and_loads_only_aat_gold(refs):
    data = pelt(["001HOOD", "059LBOXSIDE", "036LBOXSIDE"], colour="Command Grey", job="QS1")
    template = describe_film_sheet(data, "Quick Summary", FILM_ALIAS)
    assert template.sheet_class == "FILMTHICKNESS" and template.missing_required == ()
    result = clean(refs, data, "Data Pelt P703 Oct26.xlsx", "Quick Summary")
    assert [r.point_code for r in result.clean] == ["001HOOD", "059LBOXSIDE"]
    # RO05 CHANGE (owner, RO04): AAT has Film settings, so the name is still held
    # but asked in its own row (T109 `FILM_POINT_UNKNOWN`), not `UNMAPPED_POINT`.
    assert {h.location: h.reason for h in result.held} == {"036LBOXSIDE": "FILM_POINT_UNKNOWN"}


# =====================================================================
# C. the running application
# =====================================================================
def test_an_aat_p703_ec1_upload_is_ready_and_loads_on_sep_gold(
    engineer, viewer, admin_conn, film_cleanup  # noqa: F811
):
    n = uuid.uuid4().int
    stamp = datetime(2001 + n % 15, (n // 15) % 12 + 1, (n // 180) % 28 + 1, 8, 0)
    sample = f"25{n % 10**5:05d} P703 38P"
    walk = ["001HOOD", "032LFDRPOST", "073LBXFLOOR"]
    data = ec1(walk, sample=sample, stamp=stamp)
    review = sent(engineer, film_cleanup, admin_conn, f"Data Pelt P703_{uuid.uuid4().hex[:6]}.xlsx",
                  data, "AAT")["P703_38P"]
    assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"].get("notes")
    file_hash = review["batch"]["file_hash"]
    body = engineer.get(f"/api/v1/plants/AAT/workbooks/{file_hash}/worksheet").json()
    [sheet] = body["sheets"]
    assert sheet["state"] == "ready", (sheet["operator_message"], sheet["commit_blockers"])
    ready = {r["panel_label"]: (r["checkzone"], r["color"]) for r in sheet["rows"]
             if r["outcome"] == "ready"}
    assert ready == {n_: (n_, "Aluminum Metallic") for n_ in walk}

    assert viewer.post(f"/api/v1/plants/AAT/workbooks/{file_hash}/load-ready").status_code == 403
    loaded = engineer.post(f"/api/v1/plants/AAT/workbooks/{file_hash}/load-ready")
    assert loaded.status_code == 200, loaded.text
    facts = film_facts(admin_conn, review["batch"]["load_id"])
    assert {(f[1], f[4], f[5], f[7]) for f in facts} == {
        (n_, RANGER, "Aluminum Metallic", sample) for n_ in walk
    }


def test_app_rw_still_cannot_rewrite_film_facts_or_gold(admin_conn, app_role: str):
    with admin_conn.cursor() as cur:
        for table, privilege in (
            ("filmthickness", "UPDATE"), ("filmthickness", "DELETE"),
            ("ref_plant_film_point", "UPDATE"), ("ref_plant_film_point", "DELETE"),
            ("ref_color_alias", "DELETE"),
        ):
            cur.execute("SELECT has_table_privilege(%s, %s, %s)", (app_role, table, privilege))
            assert cur.fetchone()[0] is False, (table, privilege)
