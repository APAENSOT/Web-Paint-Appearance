"""T47 -- proved P703 DBL location maps and gold Hor/Ver (D-FT-12..16).

Claims (task section C), **amended by T54 for FTM** (T53-CONTEXT D-53-01..05):
FTM's gold is its own Desert Island Blue Quick Summary 94 and its T47 maps
onto FVL names are retired from resolve (revision 0019).

1. FTM ``021LAPILLAR`` is FTM gold ``021LAPILLAR``, never FVL ``021LTFEND``.
2. FTM ``029LTFTDOOR`` is FTM gold ``029LTFTDOOR`` on ``_RB_`` (Raptor) and
   ``_DBL_`` (Ranger) -- no longer FVL ``022LTFTDOOR``. Vertical.
3. FTM ``095RBXFLOOR`` / ``096TGATEIN`` / ``001FTWISH`` are extras off the 94
   and are held. A six-row sheet never becomes six (or 94) facts by count.
4. FVL ``001HOOD`` loads by exact name with no map row.
5. SAP ``033LBOXSIDE`` is gold ``036LBOXSIDE`` -- and SAP ``036LBOXSIDE`` is
   gold ``039LBOXSIDE``: a proved plant map outranks an exact spelling.
6. AAT ``059LBOXSIDE`` is gold ``036LBOXSIDE``; AAT ``073LBXFLOOR`` is held,
   not right-floor ``059RBXFLOOR``.
7. ``app_rw`` still has no UPDATE / DELETE on ``filmthickness``.

Plus: the seed equals the evidence JSON (233 maps, one proof hash, held rows
absent) and Hor/Ver is 30 / 64 on the gold catalogue only. Workbooks are
synthetic; location names come from the evidence JSON.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path

import pytest
from psycopg import errors as pgerr
from sqlalchemy import create_engine

from app.domain.film import FilmCleaner, resolve_film_model
from app.domain.reader import describe_film_sheet, read_film_sheet
from app.repositories.filmthickness import load_film_reference
from tests.test_t04_ingest import admin, engineer, ingest_apps  # noqa: F401
from tests.test_t46_filmthickness import (
    FILM_ALIAS,
    FILM_MODEL_ALIAS,
    commit,
    film_cleanup,  # noqa: F401
    film_facts,
    pelt,
    review_rows,
    sap_ods,
    sent,
)

pytestmark = pytest.mark.ingest

EVIDENCE = (Path(__file__).resolve().parent / "fixtures" / "gold"
            / "P703-DBL-film-location-map.json")
DATA = json.loads(EVIDENCE.read_text(encoding="utf-8"))
COLOURS = ("Absolute Black", "Arctic White", "Frozen White", "Command Grey",
           "Traction Green")


@pytest.fixture(scope="module")
def film_ref(app_database_url):
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            yield load_film_reference(conn)
    finally:
        engine.dispose()


def clean(film_ref, plant, filename, locations, colour="Arctic White"):
    data = pelt(locations, colour=colour, job=Path(filename).stem)
    template = describe_film_sheet(data, "Quick Summary", FILM_ALIAS)
    rows = list(read_film_sheet(data, "Quick Summary", template, filename))
    model = resolve_film_model(plant, filename, "Quick Summary", FILM_MODEL_ALIAS)
    cleaner = FilmCleaner(
        film_ref, plant=plant, model=model, meta=template.meta_map,
        color_by_plant={}, color={}, known_color_names=COLOURS,
        # T78 (D-78-20): this fixture's colours are the ones the plant offers.
        offered_colors={(plant, c): True for c in COLOURS},
        # T112-FIX (D-112F-2): the sheet's model is one the plant offers.
        offered_models={(plant, model.model): True},
    )
    return cleaner.clean_all(rows)


def loaded(result) -> dict[str, tuple[str, str | None, str]]:
    return {r.src_location_text: (r.point_code, r.orientation, r.model) for r in result.clean}


def held(result) -> dict[str, str]:
    return {h.location: h.reason for h in result.held}


# =====================================================================
# seed
# =====================================================================
def test_the_seed_is_the_evidence_json(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code, raw_location_norm, point_code, raw_position, "
            "       proof_hash, verified_by, approved_at IS NOT NULL "
            "  FROM ref_film_location_map"
        )
        rows = cur.fetchall()
    assert len(rows) == len(DATA["maps"]) == 233
    assert {r[5] for r in rows} == {DATA["proof_hash"]}
    assert {r[6] for r in rows} == {DATA["verified_by"]}
    assert all(r[7] for r in rows)
    assert {r[:5] for r in rows} == {
        (m["plant_code"], m["model_code"], m["raw_location_norm"], m["point_code"],
         m["raw_position"])
        for m in DATA["maps"]
    }
    stored = {(r[0], r[1], r[2]) for r in rows}
    for h in DATA["held_not_seeded"]:
        assert (h["plant_code"], h["model_code"], h["raw_location_norm"]) not in stored
    assert not any(r[1] in ("P703 RAPCAP", "P703 SGL") for r in rows)


def test_hor_ver_lives_on_the_gold_catalogue_only(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code, point_code, orientation FROM ref_model_film_point"
        )
        rows = cur.fetchall()
    gold = {p["point_code"]: p["orientation"] for p in DATA["gold_points"]}
    for model in ("P703 DBL RANGER", "P703 DBL RAPTOR"):
        got = {p: o for m, p, o in rows if m == model}
        assert got == gold
        assert Counter(got.values()) == {"H": 30, "V": 64}
    assert {o for m, _, o in rows if m in ("P703 RAPCAP", "P703 SGL")} == {None}


# =====================================================================
# the allow-list (domain, maps loaded from the database)
# =====================================================================
def test_021lapillar_is_ftm_gold_never_021ltfend(film_ref):  # [1] T54 CHANGE
    result = clean(film_ref, "FTM", "AW_RB_1.xlsx", ["021LAPILLAR"])
    assert loaded(result) == {"021LAPILLAR": ("021LAPILLAR", "V", "P703 DBL RAPTOR")}
    assert held(result) == {}


@pytest.mark.parametrize("token, model", [
    ("RB", "P703 DBL RAPTOR"), ("DBL", "P703 DBL RANGER"),
])
def test_ftm_029ltftdoor_is_ftm_gold_not_fvl_022ltftdoor(film_ref, token, model):  # [2] T54
    result = clean(film_ref, "FTM", f"AW_{token}_1.xlsx", ["029LTFTDOOR"])
    assert loaded(result) == {"029LTFTDOOR": ("029LTFTDOOR", "V", model)}


def test_ftm_extras_hold_and_ftm_names_load_as_themselves(film_ref):  # [3] T54 CHANGE
    six = ["095RBXFLOOR", "096TGATEIN", "001FTWISH", "021LAPILLAR",
           "036LTRRDOOR", "002FTWISH"]
    result = clean(film_ref, "FTM", "AW_RB_7.xlsx", six)
    # T99 CHANGE (D-99-5, D-99-6): `095RBXFLOOR` and `096TGATEIN` are real
    # points of FTM's 98-name Raptor walk now, so they load as themselves;
    # the FTWISH labels are the known tail, kept and not stored rather than
    # held. The claim this test exists for is untouched: an FTM label resolves
    # to the **FTM** point of that name and never to the FVL point the
    # retired T47 maps once pointed at.
    assert loaded(result) == {
        "021LAPILLAR": ("021LAPILLAR", "V", "P703 DBL RAPTOR"),
        "036LTRRDOOR": ("036LTRRDOOR", "V", "P703 DBL RAPTOR"),
        "095RBXFLOOR": ("095RBXFLOOR", "H", "P703 DBL RAPTOR"),
        "096TGATEIN": ("096TGATEIN", "V", "P703 DBL RAPTOR"),
    }, "FTM gold names, never FVL 021LTFEND / 028-030LTRRDOOR"
    assert held(result) == {}
    assert [a.values["location"] for a in result.aggregates] == [
        "001FTWISH", "002FTWISH"
    ], "the tail is kept and not stored (D-99-6)"
    assert sum(len(r.layers) for r in result.clean) == 16, "4 rows x 4 layers, not 6 or 98"


def test_fvl_exact_name_loads_without_a_map(film_ref):  # [4]
    result = clean(film_ref, "FVL", "P703-UR1-AB.xlsx", ["001HOOD", "036LBOXSIDE"],
                   colour="Absolute Black")
    assert loaded(result) == {
        "001HOOD": ("001HOOD", "H", "P703 DBL RANGER"),
        "036LBOXSIDE": ("036LBOXSIDE", "V", "P703 DBL RANGER"),
    }


def test_sap_map_outranks_an_exact_spelling(film_ref):  # [5]
    result = clean(film_ref, "SAP", "7V P703 CC C1 TP1 PELT.xlsx",
                   ["033LBOXSIDE", "036LBOXSIDE"], colour="Frozen White")
    assert loaded(result) == {
        "033LBOXSIDE": ("036LBOXSIDE", "V", "P703 DBL RANGER"),
        "036LBOXSIDE": ("039LBOXSIDE", "V", "P703 DBL RANGER"),
    }


def test_aat_names_are_aat_gold_and_fvl_names_hold_at_aat(film_ref):  # [6] T57 CHANGE
    # D-57-01/03: AAT P703 gold is its Sep Checkzone 94 and the T47 AAT maps
    # onto FVL codes are retired. `059LBOXSIDE` is itself; `073LBXFLOOR` is
    # AAT left floor, never FVL right floor; FVL `036LBOXSIDE` holds at AAT.
    result = clean(film_ref, "AAT", "Data Pelt P703 (Aug26).xlsx",
                   ["059LBOXSIDE", "073LBXFLOOR", "036LBOXSIDE"], colour="Command Grey")
    assert loaded(result) == {
        "059LBOXSIDE": ("059LBOXSIDE", "V", "P703 DBL RANGER"),
        "073LBXFLOOR": ("073LBXFLOOR", "H", "P703 DBL RANGER"),
    }
    # RO05 CHANGE (owner, RO04): AAT has Film settings, so the name is still held
    # but asked in its own row (T109 `FILM_POINT_UNKNOWN`), not `UNMAPPED_POINT`.
    assert held(result) == {"036LBOXSIDE": "FILM_POINT_UNKNOWN"}


def test_rapcap_uses_ftm_gold_and_does_not_borrow_the_dbl_maps(film_ref):  # T54 CHANGE
    # T99 CHANGE (D-99-1, D-99-5): FTM's RAPCAP list is its own 93-name walk,
    # which holds **both** of these names -- they are the 29th and 35th points
    # of the real RAP walk. The claim is the same one, so it is made against
    # a name RAPCAP does not walk: `029LTFTDOOR` still resolves to RAPCAP's
    # own point and never borrows a DBL map, and an FVL name still holds.
    result = clean(film_ref, "FTM", "AW_RAP_1.xlsx",
                   ["029LTFTDOOR", "035LBPILLAR", "011LTFEND"])
    assert [(r.model, r.point_code, r.orientation) for r in result.clean] == [
        ("P703 RAPCAP", "029LTFTDOOR", "V"),
        ("P703 RAPCAP", "035LBPILLAR", "V"),
    ]
    # T109 CHANGE (D-109-6): at a plant x model whose point rules are
    # switched on, a label the live list does not hold is now a question
    # **in its own row** -- which live point is this? -- rather than the
    # old "ask an Admin to map it". The row is held and the rest of the
    # sheet still loads exactly as before; only the reason changed.
    # T109-FIX note (D-109F-1): this calls the cleaner directly, with no
    # sheet verdict, which is why the other rows still load here. Through the
    # pipeline a sheet with an unanswered label loads nothing at all --
    # `_film_sheet_rules` holds every row of it (see
    # `test_t109_point_check_film.py` section 9).
    assert held(result) == {"011LTFEND": "FILM_POINT_UNKNOWN"}, "not on FTM's RAPCAP 93"


@pytest.mark.parametrize("statement", [
    "UPDATE filmthickness SET thickness = 0",
    "DELETE FROM filmthickness",
    "UPDATE ref_film_location_map SET point_code = '001HOOD'",
    "DELETE FROM ref_film_location_map",
])
def test_app_rw_cannot_rewrite_facts_or_maps(app_conn, statement):  # [7]
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(statement)


# =====================================================================
# the running service
# =====================================================================
def test_ftm_98_walk_sheet_commits_only_ftm_gold(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):  # [2] [3] T54 CHANGE
    # T99 CHANGE (D-99-5, D-99-6, D-99-7). Every one of these labels is now a
    # real point of FTM's 98-name Raptor walk, and the body labels have to be
    # that walk or a prefix of it, so the file walks a prefix and then the
    # tail. The claim stands: what commits is the FTM point of that name --
    # never an FVL remap -- with the orientation its own list carries, and
    # the FTWISH tail never becomes a fact.
    name = f"AW_RB_{uuid.uuid4().int % 10**7:07d}.xlsx"
    walk = ["001HOOD", "002HOOD", "003HOOD"]
    data = pelt([*walk, "001FTWISH"], colour="Arctic White", job=name[:-5])
    review = sent(engineer, film_cleanup, admin_conn, name, data, "FTM")["Quick Summary"]
    load_id = review["batch"]["load_id"]
    counts = review["batch"]["counts"]
    assert (counts["rows_loaded"], counts["rows_quarantine"]) == (3, 0)
    projection = review_rows(admin_conn, load_id)
    orient = {r[2]["point_code"]: r[2]["orientation"] for r in projection.values() if r[0] == "LOAD"}
    assert orient == {name_: "H" for name_ in walk}, "Hood is H by the D-99-5 rule"

    commit(engineer, admin, review)
    facts = film_facts(admin_conn, load_id)
    assert len(facts) == 12
    assert {(f[9], f[1]) for f in facts} == {(n, n) for n in walk}, (
        "point_code is the FTM name; no FVL remap"
    )
    assert {f[4] for f in facts} == {"P703 DBL RAPTOR"}


def test_sap_ods_mapped_label_commits_onto_gold(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):  # [5]
    vin = f"TP{uuid.uuid4().int % 10**6:06d}"
    reviews = sent(engineer, film_cleanup, admin_conn, f"13082026 7V P703 CC C2 {vin} PELT.ods",
                   sap_ods(["033LBOXSIDE"], vin=vin), "SAP")
    review = reviews["QUICK_SUMMARY"]
    commit(engineer, admin, review)
    assert {(f[9], f[1]) for f in film_facts(admin_conn, review["batch"]["load_id"])} == {
        ("033LBOXSIDE", "036LBOXSIDE")
    }
