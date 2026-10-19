"""T55 -- plant model identity: exact offered codes + leftover Film gold.

Claims (task section 6), against the cleaner and film resolver with the live
reference, and the running application, worker and database:

* WaveScan: FVL ``CX743`` is CX743 (offered there), AAT ``CX743`` is still
  unknown (not offered there). SAP ``P703 DBL`` is Ranger by the named alias;
  SAP ``P703 RAP`` is still unknown. ``V363`` at FVL and ``U704`` at AAT load.
  ``P703`` never exact-matches ``P703 DBL RANGER``; a code offered only at
  another plant never counts.
* Film: AAT ``U704`` / FVL ``CX743`` / FVL ``V363`` / SAP ``J73`` resolve to
  their own catalogue (never Ranger); one without a Film alias still holds.
  FTM ``_RAP_`` is still RAPCAP. Every gold name loads as itself, including
  U704 ``095Roof LH`` (not an extra); footer rows (``BOOTH_1`` ...) and a
  Ranger-only name hold.
* Live: an AAT U704 EC1 sheet and a SAP J73 ``.ods`` go through the same
  worksheet and load-ready; a Viewer is 403.
* ``.ods`` is still on the door; ``app_rw`` still cannot UPDATE / DELETE
  ``wavescan`` or ``filmthickness``.

Workbooks are synthetic. No proving file is read here.
"""

from __future__ import annotations

import io
import json
import re
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine

from app.domain.cleaner import Cleaner, CleanRow, Reject, RejectReason
from app.domain.film import FilmCleaner, FilmReference, normalise_location, resolve_film_model
from app.domain.held_label_copy import operator_message_for
from app.domain.reader import describe_film_sheet, read_film_sheet
from app.repositories.filmthickness import load_film_reference
from app.repositories.reference import load_reference_data
from app.services.upload_guard import ALLOWED_EXTENSIONS
from tests.test_t04_domain import REFERENCE, make_raw
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import (
    FILM_ALIAS,
    film_cleanup,  # noqa: F401
    film_facts,
    pelt,
    sap_ods,
    sent,
)

pytestmark = pytest.mark.ingest

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = json.loads(
    (REPO / "backend" / "migrations" / "seed" / "LEFTOVER-film-points.json").read_text(encoding="utf-8")
)
GOLD = {(c["plant_code"], c["model_code"]): [p["point_code"] for p in c["locations"]]
        for c in EVIDENCE["catalogues"]}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MEASURES = {m: 1.5 for m in ("lw", "sw", "cf", "du", "wa", "wb", "wc", "wd", "we")}


@pytest.fixture(scope="module")
def refs(app_database_url):
    # Read once and release the connection (the standing cluster has 60 slots).
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            found = (load_reference_data(conn), load_film_reference(conn))
    finally:
        engine.dispose()
    return found


# =====================================================================
# A. WaveScan: exact offered catalogue code + named aliases
# =====================================================================
def wave_model(ref, plant: str, cell: str) -> str | None:
    cleaner = Cleaner(ref, (plant,), expected_plant=plant)
    return cleaner.plant_first(ref.model_by_plant, ref.model, plant, cell) or (
        cleaner.offered_model_code(plant, cell)
    )


@pytest.mark.parametrize("plant, cell, model", [
    ("FVL", "CX743", "CX743"),
    ("FVL", "cx743 ", "CX743"),
    ("FVL", "V363", "V363"),
    ("AAT", "U704", "U704"),
    ("SAP", "P703 DBL", "P703 DBL RANGER"),
    ("SAP", "J73 DBL", "J73 DBL"),
    ("AAT", "CX743", None),
    # T60 CHANGE (D-60-01): SAP WaveScan `P703 RAP` is Raptor (G1 D-06).
    ("SAP", "P703 RAP", "P703 DBL RAPTOR"),
])
def test_wavescan_model_cells_resolve_on_this_plants_list(refs, plant, cell, model):
    assert wave_model(refs[0], plant, cell) == model


def test_unknown_or_unoffered_model_cells_hold_as_unknown_model(refs):
    ref = refs[0]
    for plant, cell in (("AAT", "CX743"), ("SAP", "P703 RAPTOR X")):
        out = Cleaner(ref, (plant,), expected_plant=plant).clean_row(make_raw(
            date="2026-09-08", plant=plant, model=cell, checkzone="01 RRHOOD",
            color="3HC Traction Green", **MEASURES,
        ))
        assert isinstance(out, Reject) and out.reason == RejectReason.UNKNOWN_MODEL, (plant, cell)
    out = Cleaner(ref, ("FVL",), expected_plant="FVL").clean_row(make_raw(
        date="2026-09-08", plant="FVL", model="CX743", checkzone="1HOOD",
        color="3HC Traction Green", **MEASURES,
    ))
    assert not (isinstance(out, Reject) and out.reason == RejectReason.UNKNOWN_MODEL), out


def test_exact_code_is_exact_and_never_crosses_plants():
    ref = replace(
        REFERENCE,
        model={},
        model_by_plant={},
        offered_models={
            ("SAP", "P703 DBL RANGER"): True,
            ("FVL", "CX743"): True,
            ("AAT", "U704"): False,
        },
        model_zone=frozenset({("P703 DBL RANGER", "RRHOOD")}),
        plant={"sap": "SAP", "fvl": "FVL", "aat": "AAT"},
        active_plants=frozenset({"SAP", "FVL", "AAT"}),
    )
    sap = Cleaner(ref, ("SAP",), expected_plant="SAP")
    assert sap.offered_model_code("SAP", "p703 dbl ranger") == "P703 DBL RANGER"
    for cell in ("P703", "P703 DBL", "P703 DBL RANGER X", "RANGER"):
        assert sap.offered_model_code("SAP", cell) is None, "no prefix / substring fold"
    assert sap.offered_model_code("SAP", "CX743") is None, "offered at FVL only"
    assert sap.offered_model_code("AAT", "U704") is None, "not offered (is_offered false)"
    row = sap.clean_row(make_raw(
        date="2026-09-08", plant="SAP", model="P703 DBL RANGER", checkzone="rrhood",
        color="3HC Traction Green", **MEASURES,
    ))
    assert not (isinstance(row, Reject) and row.reason == RejectReason.UNKNOWN_MODEL)
    if isinstance(row, CleanRow):
        assert row.model == "P703 DBL RANGER"


def test_unknown_model_copy_points_at_this_plants_list():
    message = operator_message_for("model", "P703 RAP", plant="SAP")
    assert "not a model we know" not in message
    assert "SAP's list" in message and "never goes onto Ranger" in message


# =====================================================================
# B. leftover Film: own catalogue, never Ranger
# =====================================================================
@pytest.mark.parametrize("plant, name, sheet, model", [
    ("AAT", "Data Pelt U704_Sep26.xlsx", "U704_5GR", "U704"),
    ("FVL", "CX743-MR59125-AB.xlsx", "Quick Summary", "CX743"),
    ("FVL", "V363-PR63667-AB-16MR.xlsx", "Quick Summary", "V363"),
    ("SAP", "25082026 7V J73 CC C1 TP24187 PELT.ods", "QUICK_SUMMARY", "J73 DBL"),
    ("SAP", "13082026 7V P703 CC C2 TP18044 PELT.ods", "QUICK_SUMMARY", "P703 DBL RANGER"),
    ("FTM", "AW_RAP_1.xlsx", "Quick Summary", "P703 RAPCAP"),
    ("AAT", "CX743-MR59125-AB.xlsx", "Quick Summary", None),
    ("AAT", "Data Pelt U704_Sep26.xlsx", "P703_5ZT", None),
])
def test_leftover_film_resolves_to_its_own_model(refs, plant, name, sheet, model):
    assert resolve_film_model(plant, name, sheet, refs[1].model_alias).model == model


def test_the_evidence_and_the_seed_agree(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code, point_code, point_no, orientation, proof_hash "
            "FROM ref_plant_film_point WHERE note LIKE 'T55 seed%' "
            "ORDER BY plant_code, model_code, point_no"
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT model_code, expected_film_point_count FROM ref_model "
            "WHERE model_code IN ('U704', 'CX743', 'V363', 'J73 DBL')"
        )
        expected = dict(cur.fetchall())
    hashes = {(c["plant_code"], c["model_code"]): c["source_sha256"] for c in EVIDENCE["catalogues"]}
    assert {k: len(v) for k, v in GOLD.items()} == {
        ("AAT", "U704"): 95, ("FVL", "CX743"): 81, ("FVL", "V363"): 88, ("SAP", "J73 DBL"): 93,
    }
    for key, names in GOLD.items():
        mine = [r for r in rows if (r[0], r[1]) == key]
        assert [r[2] for r in mine] == names
        assert {r[5] for r in mine} == {hashes[key]}
        for r in mine:
            family = any(w in r[2] for w in ("HOOD", "ROOF", "FLOOR"))
            assert r[4] == ("H" if family else "V")
        assert expected[key[1]] == len(names)
    assert "095ROOFLH" in GOLD[("AAT", "U704")]
    footer = {"BOOTH_1", "PROG", "FVL_FILM_BODY", "FMCSA_FILM_BODY", "CX743", "V363", "J73_CC"}
    assert not footer & {n for names in GOLD.values() for n in names}
    for c in EVIDENCE["catalogues"]:
        for p in c["locations"]:
            assert set(p) == {"point_no", "point_code", "orientation"}, "labels only"


def u704_ec1(locations, *, day: str, colour: str = "Command Grey") -> bytes:
    """AAT EC1 one-sheet layout (header row 7) for U704, with Date / Color."""
    wb = Workbook()
    ws = wb.active
    ws.title = "U704_5ZT"
    ws.append(["2500000 U704 5ZT"])
    ws.append([f"{colour}_4", None, "total mic", "CC1 mic", "BC2 mic", "BC1 mic", "EC1 mic"])
    ws.append(["Fail High", None, 100, 45, 25, 15, 30])
    ws.append(["Warning High"])
    ws.append(["Warning Low"])
    ws.append(["Fail Low", None, 65, 25, 10, 7, 16])
    ws.append(["Checkzone", "Status", "total mic", "CC1 mic", "BC2 mic", "BC1 mic", "EC1 mic",
               "Date", "Color"])
    ws.append(["Match to Standard"])
    for i, loc in enumerate(locations):
        ws.append([loc, "Pass", 100.0 + i, 40.0 + i, 12.0, 20.0, 18.0, day, colour])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _clean(refs, plant, filename, sheet, data):
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


def test_all_95_u704_names_load_including_095_roof_lh_and_footers_hold(refs):
    walk = [n.replace("ROOFLH", "Roof LH").replace("ROOFCTR", "Roof Ctr")
            for n in GOLD[("AAT", "U704")]]
    assert "095Roof LH" in walk
    data = u704_ec1(walk + ["BOOTH_1", "094LBOXSIDE"], day="2026-09-20")
    result = _clean(refs, "AAT", "Data Pelt U704_Sep26.xlsx", "U704_5ZT", data)
    assert [r.point_code for r in result.clean] == GOLD[("AAT", "U704")]
    assert {r.model for r in result.clean} == {"U704"}, "never Ranger"
    got = {r.src_location_text: r.point_code for r in result.clean}
    assert got["095Roof LH"] == "095ROOFLH"
    # RO05 CHANGE (owner, RO04): AAT has Film settings, so the name is still held
    # but asked in its own row (T109 `FILM_POINT_UNKNOWN`), not `UNMAPPED_POINT`.
    # RO06 CHANGE (owner, option a): AAT has FTM's `BOOTH_1` tail label, so the
    # footer is kept and never stored (D-99-6), as at FTM; it is not a hold.
    assert {h.location: h.reason for h in result.held} == {
        "094LBOXSIDE": "FILM_POINT_UNKNOWN",
    }, "a Ranger-only name holds; 095Roof LH is not an extra"
    assert [(a.values["location"], a.reason) for a in result.aggregates
            if a.reason == "FILM_TAIL_LABEL"] == [("BOOTH_1", "FILM_TAIL_LABEL")], \
        "the footer row is the tail aggregate, not a fact"


def synthetic_leftover_refs(refs, plant, model, names):
    """Same complete gold and parser vocabulary, with no rollout-dependent rules."""
    token = "J73" if model == "J73 DBL" else model
    reference = replace(
        refs[0], offered_colors={**refs[0].offered_colors,
                                **{(plant, c): True for c in refs[0].known_color_names}},
        offered_models={(plant, model): True},
    )
    film = FilmReference(
        column_alias=refs[1].column_alias,
        model_alias={(plant, token): model},
        plant_catalogue={(plant, model): {normalise_location(n): n for n in names}},
        plant_orientation={(plant, model, n): "H" for n in names},
        walk={(plant, model): tuple(names)},
    )
    assert not film.has_setting(plant, model) and not film.tail_labels
    return reference, film


@pytest.mark.parametrize("plant, model, filename, last", [
    ("FVL", "CX743", "CX743-MR59125-AB.xlsx", "081LFTGATE"),
    ("FVL", "V363", "V363-PR63667-AB-16MR.xlsx", "088ROOF"),
])
def test_fvl_leftover_quick_summaries_load_their_own_gold(refs, plant, model, filename, last):
    names = GOLD[(plant, model)]
    plant = "ZR19_LEFTOVER"
    refs = synthetic_leftover_refs(refs, plant, model, names)
    data = pelt(names + ["BOOTH_1", "PROG", "FVL_FILM_BODY", model, "036LBOXSIDE"],
                colour="Absolute Black", job=Path(filename).stem)
    result = _clean(refs, plant, filename, "Quick Summary", data)
    assert [r.point_code for r in result.clean] == names and names[-1] == last
    assert {r.model for r in result.clean} == {model}
    assert set(h.location for h in result.held) == {
        "BOOTH_1", "PROG", "FVL_FILM_BODY", model, "036LBOXSIDE",
    }


def test_sap_j73_ods_loads_its_own_gold(refs):
    names = GOLD[("SAP", "J73 DBL")]
    plant = "ZR19_J73"
    refs = synthetic_leftover_refs(refs, plant, "J73 DBL", names)
    data = sap_ods(names[:3] + ["J73_CC", "FMCSA_FILM_BODY"], vin="TP24187")
    result = _clean(refs, plant, "25082026 7V J73 CC C1 TP24187 PELT.ods", "QUICK_SUMMARY", data)
    assert [r.point_code for r in result.clean] == names[:3]
    assert {r.model for r in result.clean} == {"J73 DBL"}
    assert {h.location for h in result.held} == {"J73_CC", "FMCSA_FILM_BODY"}


# =====================================================================
# C. the running application
# =====================================================================
def old_day() -> tuple[str, str]:
    n = uuid.uuid4().int
    day, month, year = n % 28 + 1, (n // 28) % 12, 2001 + (n // 997) % 15
    return f"{year}-{month + 1:02d}-{day:02d}", f"{year}-{month + 1:02d}"


def ws_url(plant: str, file_hash: str, tail: str = "worksheet") -> str:
    return f"/api/v1/plants/{plant}/workbooks/{file_hash}/{tail}"


def test_aat_u704_film_sheet_confirms_and_loads_on_u704_gold(
    engineer, viewer, admin_conn, film_cleanup  # noqa: F811
):
    day, month = old_day()
    tag = uuid.uuid4().hex[:6]
    walk = ["001HOOD", "094Roof Ctr", "095Roof LH", "BOOTH_1"]
    data = u704_ec1(walk, day=day)
    name = f"Data Pelt U704_{tag}.xlsx"
    review = sent(engineer, film_cleanup, admin_conn, name, data, "AAT")["U704_5ZT"]
    file_hash = review["batch"]["file_hash"]

    body = engineer.get(ws_url("AAT", file_hash)).json()
    sheet = body["sheets"][0]
    assert sheet["state"] == "ready", (sheet["operator_message"], sheet["commit_blockers"])
    rows = {r["panel_label"]: r for r in sheet["rows"]}
    assert (rows["095Roof LH"]["outcome"], rows["095Roof LH"]["checkzone"]) == ("ready", "095ROOFLH")
    assert rows["094Roof Ctr"]["checkzone"] == "094ROOFCTR"
    assert {r["model"] for r in sheet["rows"] if r["outcome"] == "ready"} == {"U704"}
    assert (rows["BOOTH_1"]["outcome"], rows["BOOTH_1"]["checkzone"]) == ("held_out", None)

    assert viewer.post(ws_url("AAT", file_hash, "load-ready")).status_code == 403
    loaded = engineer.post(ws_url("AAT", file_hash, "load-ready"))
    assert loaded.status_code == 200, loaded.text
    words = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    # BOOTH_1 is the walk tail (not stored, as at FTM); the AAT "Match to
    # Standard" limit row is the one held out.
    assert loaded.json()["operator_message"] == (
        f"3 readings added to {words}, 1 held out, 1 not stored (walk tail)."
    )
    facts = film_facts(admin_conn, review["batch"]["load_id"])
    assert {(f[9], f[1], f[4]) for f in facts} == {
        ("001HOOD", "001HOOD", "U704"), ("094Roof Ctr", "094ROOFCTR", "U704"),
        ("095Roof LH", "095ROOFLH", "U704"),
    }


def test_sap_j73_ods_upload_is_ready_on_j73_gold(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    vin = f"TP{uuid.uuid4().int % 10**6:06d}"
    gold = GOLD[("SAP", "J73 DBL")][:2]
    reviews = sent(engineer, film_cleanup, admin_conn, f"25082026 7V J73 CC C1 {vin} PELT.ods",
                   # RO18 (B3): the sheet's day agrees with the file name's.
                   sap_ods(gold, vin=vin, day="25-Aug-26"), "SAP")
    review = reviews["QUICK_SUMMARY"]
    body = engineer.get(ws_url("SAP", review["batch"]["file_hash"])).json()
    tabs = {s["sheet"]: s for s in body["sheets"]}
    sheet = tabs["QUICK_SUMMARY"]
    assert sheet["state"] == "ready", (
        sheet["operator_message"], sheet["commit_blockers"],
        [(r["outcome"], r["operator_message"]) for r in sheet["rows"]],
    )
    assert [(r["panel_label"], r["checkzone"], r["model"]) for r in sheet["rows"]] == [
        (n, n, "J73 DBL") for n in gold
    ]


def test_ods_is_still_on_the_door_and_app_rw_cannot_rewrite_facts(admin_conn, app_role: str):
    assert ".ods" in ALLOWED_EXTENSIONS
    with admin_conn.cursor() as cur:
        for table in ("wavescan", "filmthickness"):
            for privilege in ("UPDATE", "DELETE"):
                cur.execute("SELECT has_table_privilege(%s, %s, %s)", (app_role, table, privilege))
                assert cur.fetchone()[0] is False, (table, privilege)


def test_p703_rap_is_wavescan_raptor_at_sap_only(admin_conn):
    # T60 CHANGE (D-60-01..02): WaveScan SAP `P703 RAP` -> Raptor is seeded by
    # 0023; Film keeps no `P703 RAP` / `RAP` token at SAP (FTM `_RAP_` = RAPCAP).
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code FROM ref_model_alias "
            "WHERE upper(raw_value) = 'P703 RAP'"
        )
        assert cur.fetchall() == [("SAP", "P703 DBL RAPTOR")]
        cur.execute(
            "SELECT count(*) FROM ref_film_model_alias "
            "WHERE plant_code = 'SAP' AND raw_token IN ('P703 RAP', 'RAP')"
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT plant_code, raw_value, model_code FROM ref_model_alias "
            "WHERE note = 'T55 owner lock 2026-10-05' ORDER BY 1"
        )
        assert cur.fetchall() == [("FVL", "CX743", "CX743"), ("SAP", "P703 DBL", "P703 DBL RANGER")]
    assert not re.search(r"(?i)\.xlsx?$|\.ods$", " ".join(
        p.name for p in (REPO / "backend" / "tests").rglob("*") if p.is_file()
    )), "no proving workbook under tests/"
