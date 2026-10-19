"""T54 -- FilmThickness polish: FTM's own gold, junk holds, the same confirm.

Claims (task section 6), against the seed, the film cleaner with the live
reference, and the running application, worker and database:

* The evidence JSON is 94 FTM labels with a source hash and the D-53-06
  Hor/Ver rule, and revision 0019 seeded exactly that for FTM x Ranger,
  Raptor, RAPCAP and Single CAP. Other plants keep the T46/T47 catalogue.
* FTM labels load as **FTM gold names**: ``021LAPILLAR`` never becomes FVL
  ``021LTFEND``; FTM's T47 maps are retired, not read.
* A row off the 94 (FTWISH, 095-098, a RAPCAP-only walk name) is held; the
  complete rows still load. Missing names are empty slots, never invented.
* Filename `_DBL_` Ranger, `_RB_` Raptor, `_RAP_` RAPCAP, `_SGL_` Single CAP.
* Worksheet: the Quick Summary rows carry ``panel_label`` = the Location cell
  and ``checkzone`` = the FTM point; held rows have ``checkzone`` null; the
  picture tabs say "Extra tab kept. Not loaded." and do not block Approve.
  Load-ready answers with the T53 toast; a second file of the same car is
  already in History; the same bytes are 409; a Viewer is 403.
* FVL exact ``001HOOD`` still loads as FVL gold.
* ``app_rw`` still has no UPDATE / DELETE on ``filmthickness``.

Workbooks are synthetic; the proving file is never read here.
"""

from __future__ import annotations

import io
import json
import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine

from app.domain.film import FilmCleaner, resolve_film_model
from app.domain.reader import describe_film_sheet, read_film_sheet
from app.repositories.filmthickness import load_film_reference
from app.services.worksheet import EXTRA_TAB_MESSAGE
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import (
    FILM_ALIAS,
    FILM_MODEL_ALIAS,
    film_cleanup,  # noqa: F401
    film_facts,
    pelt,
    sent,
)

pytestmark = pytest.mark.ingest

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = json.loads(
    (REPO / "backend" / "migrations" / "seed" / "FTM-QS-film-points.json").read_text(encoding="utf-8")
)
FTM_GOLD = [p["point_code"] for p in EVIDENCE["locations"]]
FTM_MODELS = ("P703 DBL RANGER", "P703 DBL RAPTOR", "P703 RAPCAP", "P703 SGL")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TOKENS = re.compile(r"\b(LOAD|DUPLICATE|REJECT|QUARANTINE|Duplicate|Quarantine)\b")


@pytest.fixture(scope="module")
def film_ref(app_database_url):
    # Read once and release the connection: by this point of a full run the
    # standing cluster's 60 slots are nearly spent by earlier modules.
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            ref = load_film_reference(conn)
    finally:
        engine.dispose()
    return ref


def clean(film_ref, plant, filename, locations, colour="Arctic White"):
    data = pelt(locations, colour=colour, job=Path(filename).stem)
    template = describe_film_sheet(data, "Quick Summary", FILM_ALIAS)
    rows = list(read_film_sheet(data, "Quick Summary", template, filename))
    model = resolve_film_model(plant, filename, "Quick Summary", FILM_MODEL_ALIAS)
    cleaner = FilmCleaner(
        film_ref, plant=plant, model=model, meta=template.meta_map,
        color_by_plant={}, color={}, known_color_names=(colour,),
        # T78 (D-78-20): this fixture's colour is one the plant offers.
        offered_colors={(plant, colour): True},
        # T112-FIX (D-112F-2): the sheet's model is one the plant offers.
        offered_models={(plant, model.model): True},
    )
    return cleaner.clean_all(rows)


def loaded(result) -> dict[str, tuple[str, str | None, str]]:
    return {r.src_location_text: (r.point_code, r.orientation, r.model) for r in result.clean}


def held(result) -> dict[str, str]:
    return {h.location: h.reason for h in result.held}


# =====================================================================
# A. evidence and seed
# =====================================================================
def test_the_evidence_is_94_ftm_labels_with_a_hash_and_the_family_rule():
    assert EVIDENCE["plant_code"] == "FTM" and EVIDENCE["point_count"] == 94
    assert re.fullmatch(r"[0-9a-f]{64}", EVIDENCE["source_sha256"])
    assert len(set(FTM_GOLD)) == 94
    assert [p["point_no"] for p in EVIDENCE["locations"]] == list(range(1, 95))
    for p in EVIDENCE["locations"]:
        family = any(w in p["point_code"] for w in ("HOOD", "ROOF", "FLOOR"))
        assert p["orientation"] == ("H" if family else "V"), p
        assert set(p) == {"point_no", "point_code", "orientation"}, "labels only"
    assert Counter(p["orientation"] for p in EVIDENCE["locations"]) == {"H": 29, "V": 65}
    assert not list((REPO / "backend" / "tests").rglob("*.xlsx")), "no workbook in tests/"


def test_0019_seeds_ftm_gold_and_keeps_other_plants_on_their_catalogue(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            # T99 CHANGE (D-99-5): `retired_at` is read too, because T99
            # retires the copied names a model's real walk does not contain.
            "SELECT model_code, point_code, point_no, orientation, proof_hash, "
            "       retired_at "
            "FROM ref_plant_film_point WHERE plant_code = 'FTM' ORDER BY model_code, point_no"
        )
        ftm = cur.fetchall()
        cur.execute(
            "SELECT p.plant_code, count(*) FILTER (WHERE c.point_code IS NULL) "
            "  FROM ref_plant_film_point p "
            "  LEFT JOIN ref_model_film_point c "
            "    ON c.model_code = p.model_code AND c.point_code = p.point_code "
            "   AND c.point_no = p.point_no "
            "       AND c.orientation IS NOT DISTINCT FROM p.orientation "
            " WHERE p.plant_code <> 'FTM' "
            # T57 CHANGE: AAT Ranger is its own Sep 94 (revision 0021).
            "   AND NOT (p.plant_code = 'AAT' AND p.model_code = 'P703 DBL RANGER') "
            # T55 CHANGE: leftover gold (0020) is its own list, not the copy.
            "   AND p.note NOT LIKE 'T55 seed%' "
            # RO19 CHANGE (D-RO19-5): a point the owner added on Point Check
            # (SAP J73 061TGATE) is the plant's own, not the copy.
            "   AND p.note NOT LIKE 'T109 (D-109-5)%' GROUP BY 1 ORDER BY 1"
        )
        others = dict(cur.fetchall())
        cur.execute("SELECT count(*) FROM ref_model_film_point")
        model_rows = cur.fetchone()[0]
        cur.execute(
            "SELECT plant_code, count(*) FROM ref_plant_film_point "
            "WHERE plant_code <> 'FTM' AND note NOT LIKE 'T55 seed%' "
            "  AND note NOT LIKE 'T109 (D-109-5)%' "
            "  AND NOT (plant_code = 'AAT' AND model_code = 'P703 DBL RANGER') GROUP BY 1"
        )
        other_counts = dict(cur.fetchall())
    # T99 CHANGE (D-99-5): FTM's four lists are no longer one 94-name copy.
    # DBL RANGER and DBL RAPTOR are the 94 **plus** 095RBXFLOOR and
    # 096-098TGATEIN (98); RAPCAP is its own 93 and SGL its own 58, measured
    # on the real files. T54's claim -- that 0019 seeded the evidence's 94
    # names, in order, with the D-53-06 orientation and the source hash --
    # is kept for the names the evidence still describes: the 94 are the
    # first 94 of each DBL list and carry their proof hash, and every row
    # T99 added or kept carries the one H/V rule.
    for model in FTM_MODELS:
        live = [r for r in ftm if r[0] == model and r[5] is None]
        assert len(live) == {"P703 RAPCAP": 93, "P703 SGL": 58}.get(model, 98), model
        for row in live:
            want = "H" if re.sub(r"^[0-9]+", "", row[1]) in (
                "HOOD", "ROOF", "LBXFLOOR", "RBXFLOOR"
            ) else "V"
            assert row[3] == want, (model, row[1])
        if model.startswith("P703 DBL"):
            assert [r[1] for r in live[:94]] == FTM_GOLD, model
            assert [r[3] for r in live[:94]] == [
                p["orientation"] for p in EVIDENCE["locations"]
            ]
            assert {r[4] for r in live[:94]} == {EVIDENCE["source_sha256"]}
    assert set(others) >= {"AAT", "FVL", "SAP"}
    assert set(others.values()) == {0}, "a non-FTM plant row equals the model catalogue"
    # T57 CHANGE: AAT's Ranger rows (excluded above) are its own Sep 94.
    ranger_rows = 94
    assert {p: n for p, n in other_counts.items() if p != "AAT"} == {
        p: model_rows for p in other_counts if p != "AAT"
    }
    assert other_counts["AAT"] == model_rows - ranger_rows


def test_ftm_t47_maps_are_retired_and_other_plants_stay_live(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, count(*) FILTER (WHERE retired_at IS NULL), "
            "       count(*) FILTER (WHERE retired_at IS NOT NULL) "
            "  FROM ref_film_location_map GROUP BY 1 ORDER BY 1"
        )
        got = {p: (live, retired) for p, live, retired in cur.fetchall()}
        cur.execute(
            "SELECT convalidated, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'filmthickness'::regclass AND conname = 'fk_ft_plant_model_point'"
        )
        fk = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM pg_constraint WHERE conrelid = 'filmthickness'::regclass "
            "AND conname = 'filmthickness_model_point_code_fkey'"
        )
        old_fk = cur.fetchone()[0]
    assert got["FTM"][0] == 0 and got["FTM"][1] > 0, "rows kept, none read"
    # T57 CHANGE (D-57-03): AAT's T47 maps are retired too.
    assert got["AAT"][0] == 0 and got["AAT"][1] > 0
    assert all(live > 0 and retired == 0 for p, (live, retired) in got.items()
               if p not in ("FTM", "AAT"))
    assert fk is not None and "ref_plant_film_point" in fk[1]
    assert fk[0] is False, "NOT VALID: earlier FTM facts on FVL names are never rewritten"
    assert old_fk == 0


def test_the_live_reference_reads_no_ftm_map(film_ref):
    assert not [k for k in film_ref.location_map if k[0] == "FTM"]
    assert {k for k in film_ref.location_map if k[0] in ("SAP", "AAT")}
    # T99 CHANGE (D-99-5): each FTM model has its **own** walk now, so the
    # reference is compared against the live list of that model rather than
    # against one shared 94. The claim T54 made -- that the reference reads
    # the plant's list in walk order and nothing else -- is kept, and the
    # 94 evidence names are still the head of each DBL list.
    for model in FTM_MODELS:
        walk = list(film_ref.gold_for("FTM", model).values())
        assert walk == list(film_ref.walk[("FTM", model)])
        if model.startswith("P703 DBL"):
            assert walk[:94] == FTM_GOLD


# =====================================================================
# B. resolve: FTM gold by name, extras hold, FVL unchanged
# =====================================================================
@pytest.mark.parametrize("token, model", [
    ("DBL", "P703 DBL RANGER"), ("RB", "P703 DBL RAPTOR"),
    ("RAP", "P703 RAPCAP"), ("SGL", "P703 SGL"),
])
def test_all_94_ftm_names_load_as_themselves_for_every_filename_token(film_ref, token, model):
    # T99 CHANGE (D-99-1, D-99-5): a name is never compared across models, so
    # the labels walked here are **this model's own** live list, not one
    # shared 94 -- RAPCAP's 93 and SGL's 58 do not contain every DBL name.
    # The claim is unchanged: every name of the plant's list for the model
    # the filename token names loads as itself, never remapped onto an FVL
    # point, with the H/V its own list carries.
    walk = list(film_ref.walk[("FTM", model)])
    result = clean(film_ref, "FTM", f"AW_{token}_1.xlsx", walk)
    got = loaded(result)
    assert held(result) == {}
    assert {k: v[0] for k, v in got.items()} == {n: n for n in walk}, "never an FVL remap"
    assert {v[2] for v in got.values()} == {model}
    assert {k: v[1] for k, v in got.items()} == {
        point: film_ref.orientation_of("FTM", model, point) for point in walk
    }
    if model.startswith("P703 DBL"):
        assert walk[:94] == FTM_GOLD
        assert {k: v[1] for k, v in got.items() if k in FTM_GOLD} == {
            p["point_code"]: p["orientation"] for p in EVIDENCE["locations"]
        }


def test_an_fvl_only_name_or_an_extra_is_held_at_ftm_and_the_rest_still_loads(film_ref):
    labels = ["001HOOD", "021LAPILLAR", "021LTFEND", "095RBXFLOOR", "001FTWISH"]
    result = clean(film_ref, "FTM", "AW_RB_2.xlsx", labels)
    # T99 CHANGE (D-99-5): `095RBXFLOOR` **is** an FTM Raptor point now -- it
    # is the point the real 98-walk writes after `094RBXFLOOR` -- so it loads
    # as itself. The rest of the claim is untouched: an FVL-only name is
    # still held, and the complete rows still load.
    assert loaded(result) == {
        "001HOOD": ("001HOOD", "H", "P703 DBL RAPTOR"),
        "021LAPILLAR": ("021LAPILLAR", "V", "P703 DBL RAPTOR"),
        "095RBXFLOOR": ("095RBXFLOOR", "H", "P703 DBL RAPTOR"),
    }
    # T99 CHANGE (D-99-6): `001FTWISH` is the known tail of an FTM walk, so it
    # is kept as a not-stored row rather than held -- never a fact either way,
    # and now never a reason the rest of the sheet waits.
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
    assert held(result) == {"021LTFEND": "FILM_POINT_UNKNOWN"}
    assert [a.values["location"] for a in result.aggregates] == ["001FTWISH"]


def test_a_partial_sgl_walk_fills_only_the_names_it_has(film_ref):
    # T99 CHANGE (D-99-5): FTM's Single CAP list is its own 58-name walk now,
    # which contains neither `023ROOF` nor `035LBPILLAR` -- both were names of
    # T54's copied DBL 94. The claim is unchanged: a partial walk fills only
    # the names the plant's own list for that model holds, and a name off it
    # is held rather than padded onto a neighbouring slot.
    sgl = list(film_ref.walk[("FTM", "P703 SGL")])
    walk = [sgl[0], sgl[22], "035LBPILLAR"]
    result = clean(film_ref, "FTM", "AW_SGL_3.xlsx", walk)
    assert loaded(result) == {
        sgl[0]: (sgl[0], film_ref.orientation_of("FTM", "P703 SGL", sgl[0]), "P703 SGL"),
        sgl[22]: (sgl[22], film_ref.orientation_of("FTM", "P703 SGL", sgl[22]), "P703 SGL"),
    }
    assert "035LBPILLAR" not in sgl
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
    assert held(result) == {"035LBPILLAR": "FILM_POINT_UNKNOWN"}, "not padded onto the list"
    assert len(result.clean) == 2


def test_fvl_exact_001hood_still_loads_as_fvl_gold(film_ref):
    result = clean(film_ref, "FVL", "P703-UR1-AB.xlsx", ["001HOOD", "021LTFEND"],
                   colour="Absolute Black")
    assert loaded(result) == {
        "001HOOD": ("001HOOD", "H", "P703 DBL RANGER"),
        "021LTFEND": ("021LTFEND", "V", "P703 DBL RANGER"),
    }


# =====================================================================
# C. the running application: same confirm table, toast, History
# =====================================================================
def old_day() -> tuple[str, str]:
    n = uuid.uuid4().int
    day, month, year = n % 28 + 1, (n // 28) % 12, 1 + (n // 997) % 15
    return f"{day:02d}-{MONTHS[month]}-{year:02d}", f"20{year:02d}-{month + 1:02d}"


def desert_island(locations, *, day: str, job: str, colour: str = "Arctic White") -> bytes:
    """Desert Island Blue-shaped workbook: QS with `Dk Grey Prime`, three picture tabs."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Quick Summary"
    ws.append(["Ford Thailand Motors - PELT Filmbuild Report "])
    ws.append([])
    ws.append(["Date:", day])
    ws.append(["Time:", "11:32 AM", None, "Number of Points:", len(locations)])
    ws.append(["Operator:", "T54", None, "File Name:", f"{job}.prn"])
    ws.append(["Job Number:", job, None, "Booth:", 1])
    ws.append(["Layer 1:", "Clearcoat", None, "Shift:", "1st"])
    ws.append(["Layer 2:", colour, None, "Vin:", 0])
    ws.append(["Layer 3:", "Dk Grey Prime", None, "Report:", "Quick Summary"])
    ws.append(["Layer 4:", "E-Coat"])
    ws.append(["Layer 5:", "Steel"])
    ws.append(["Layer 6:", ""])
    ws.append(["Comments:", "", None, None, None, None, "Total"])
    ws.append(["Location", "Clearcoat", colour, "Dk Grey Prime", "E-Coat", "Steel", "Thickness"])
    for i, loc in enumerate(locations):
        ws.append([loc, 40.0 + i, 18.0, 30.0, 21.0, "", 109.0 + i])
    for tab in ("P703 CC", "P703 (BC)", "P703 (PR)"):
        pic = wb.create_sheet(tab)
        pic.append(["Ford Thailand Motors - PELT Filmbuild Report "])
        pic.append([f"{tab} picture"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def ws_url(plant: str, file_hash: str, tail: str = "worksheet") -> str:
    return f"/api/v1/plants/{plant}/workbooks/{file_hash}/{tail}"


def test_ftm_quick_summary_confirm_table_toast_and_reads(
    engineer, viewer, admin_conn, film_cleanup  # noqa: F811
):
    day, month = old_day()
    # T100 CHANGE: zero-padded. `% 10**7` is under a million about one
    # run in ten, and FTM's Job Number shape is exactly seven digits
    # (D-99-10), so an unpadded number held this sheet at random.
    job = f"IB_RB_{uuid.uuid4().int % 10**7:07d}"
    name = f"Desert Island Blue_RB_{job[6:]}_PP Build.xlsx"
    # T99 CHANGE (D-99-7): an FTM sheet's body labels must be the plant's
    # known walk or a prefix of it, so this file walks the first three points
    # of FTM's Raptor list instead of three names picked out of it. The claim
    # is unchanged -- the confirm table, the FTWISH row, the toast, the
    # second file and the same bytes -- and the walk guard has its own tests.
    locations = [*FTM_GOLD[:3], "001FTWISH"]
    data = desert_island(locations, day=day, job=job)
    reviews = sent(engineer, film_cleanup, admin_conn, name, data, "FTM")
    qs = reviews["Quick Summary"]
    file_hash = qs["batch"]["file_hash"]

    body = engineer.get(ws_url("FTM", file_hash)).json()
    tabs = {s["sheet"]: s for s in body["sheets"]}
    file = engineer.get(f"/api/v1/plants/FTM/workbooks/{file_hash}").json()["workbook"]
    skipped = {s["source_sheet"]: s for s in file["skipped_sheets"]}
    for tab in ("P703 CC", "P703 (BC)", "P703 (PR)"):
        assert tab not in tabs, tab
        assert skipped[tab]["reason"], tab
    sheet = tabs["Quick Summary"]
    assert sheet["state"] == "ready", (sheet["operator_message"], sheet["commit_blockers"])
    assert "dk grey prime" not in body["extra_columns"], "primer is read, not an extra column"
    rows = {r["panel_label"]: r for r in sheet["rows"]}
    assert set(rows) == set(locations)
    for loc in FTM_GOLD[:3]:
        assert (rows[loc]["outcome"], rows[loc]["checkzone"]) == ("ready", loc)
        assert rows[loc]["model"] == "P703 DBL RAPTOR"
    extra = rows["001FTWISH"]
    # T99 CHANGE (D-99-6): FTWISH is the known tail of an FTM walk, so it is
    # kept and not stored with its own sentence instead of held as an extra
    # point. Never a fact either way; now never a reason anything waits.
    assert (extra["outcome"], extra["checkzone"]) == ("held_out", None)
    assert "known tail" in extra["operator_message"]
    for r in sheet["rows"]:
        assert not TOKENS.search(r["operator_message"]), r
    # T103 CHANGE (D-103-5): the tail row is counted on its own line. It is
    # not "held out" -- there is nothing to fix and it never loads.
    assert body["summary_message"] == (
        "3 readings ready to add, 1 not stored (walk tail)."
    )

    assert viewer.post(ws_url("FTM", file_hash, "load-ready")).status_code == 403
    loaded_now = engineer.post(ws_url("FTM", file_hash, "load-ready"))
    assert loaded_now.status_code == 200, loaded_now.text
    result = loaded_now.json()
    words = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    assert result["months"] == [month]
    assert result["operator_message"] == (
        f"3 readings added to {words}, 1 not stored (walk tail)."
    )
    by_sheet = {s["sheet"]: s for s in result["sheets"]}
    # RO19 (D-RO19-7): out-of-scope tabs are workbook evidence, not batches,
    # so load-ready reports only the data sheet it acted on.
    assert set(by_sheet) == {"Quick Summary"}

    facts = film_facts(admin_conn, qs["batch"]["load_id"])
    assert {(f[9], f[1]) for f in facts} == {(n, n) for n in locations[:3]}, (
        "src_location_text is the file label and point_code the FTM name"
    )
    after = engineer.get(ws_url("FTM", file_hash)).json()
    done = {s["sheet"]: s for s in after["sheets"]}["Quick Summary"]
    assert done["state"] == "loaded" and done["rows_already_in_history"] == 3

    # The same car in a second file is already in History, never twice.
    again = desert_island(locations[:2], day=day, job=job)
    second = sent(engineer, film_cleanup, admin_conn, name.replace("PP Build", "copy"),
                  again, "FTM")["Quick Summary"]
    resent = engineer.get(ws_url("FTM", second["batch"]["file_hash"])).json()
    tab = {s["sheet"]: s for s in resent["sheets"]}["Quick Summary"]
    assert [r["outcome"] for r in tab["rows"]] == ["already_in_history"] * 2
    assert "2 already in History" in resent["summary_message"]

    # Same bytes: 409 at the door.
    again_same = engineer.post(
        "/api/v1/uploads",
        files={"files": (name, data, "application/octet-stream")},
        data={"expected_plant": "FTM"},
    )
    assert again_same.status_code == 409, again_same.text

    # T48 reads: the FTM grid is FTM's Raptor walk with only the three loaded
    # slots filled. T99 CHANGE (D-99-5): that walk is 98 now, the 94 evidence
    # names plus 095RBXFLOOR and 096-098TGATEIN, so the expected count is 98.
    [vid] = {f[6] for f in facts}
    grid = viewer.get(f"/api/v1/plants/FTM/filmthickness/vehicles/{vid}/points").json()
    assert [p["point_code"] for p in grid["items"]][:94] == FTM_GOLD
    assert [p["point_code"] for p in grid["items"]][94:] == [
        "095RBXFLOOR", "096TGATEIN", "097TGATEIN", "098TGATEIN"
    ]
    assert grid["vehicle"]["expected_point_count"] == 98
    # T99 (D-99-2): every point of the walk is counted after the seed, and
    # the two no-box / full-walk stops are flagged.
    assert all(p["counted"] for p in grid["items"])
    assert [p["point_code"] for p in grid["items"] if p["is_complete_stop"]] == [
        "064RAPILLAR", "098TGATEIN"
    ]
    filled = {p["point_code"]: p["src_location_text"] for p in grid["items"]
              if p["src_location_text"] is not None}
    assert filled == {n: n for n in locations[:3]}


def test_app_rw_still_cannot_rewrite_film_facts_or_gold(admin_conn, app_role: str):
    with admin_conn.cursor() as cur:
        # T99 CHANGE (D-99-14): `app_rw` now holds INSERT on
        # `ref_plant_film_point`, because the uploader who confirms an
        # appended walk adds a point to the plant's list. UPDATE and DELETE
        # stay refused by the database, so a confirm can add a point and can
        # never move, renumber or unname one -- which is the guarantee D-99-1
        # needs and the half of this claim that matters. The same holds for
        # `film_point_setting`: INSERT only, so a setting is never rewritten.
        for table, privilege in (
            ("filmthickness", "UPDATE"), ("filmthickness", "DELETE"),
            ("ref_plant_film_point", "UPDATE"),
            ("ref_plant_film_point", "DELETE"),
            ("film_point_setting", "UPDATE"), ("film_point_setting", "DELETE"),
        ):
            cur.execute("SELECT has_table_privilege(%s, %s, %s)", (app_role, table, privilege))
            assert cur.fetchone()[0] is False, (table, privilege)
        for table, privilege in (
            ("ref_plant_film_point", "SELECT"), ("ref_plant_film_point", "INSERT"),
            ("film_point_setting", "SELECT"), ("film_point_setting", "INSERT"),
        ):
            cur.execute("SELECT has_table_privilege(%s, %s, %s)", (app_role, table, privilege))
            assert cur.fetchone()[0] is True, (table, privilege)

