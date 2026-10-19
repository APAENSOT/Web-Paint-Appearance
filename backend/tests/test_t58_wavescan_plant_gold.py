"""T58 -- WaveScan plant gold: each plant x model keeps its own panel names.

Claims (task section 5), against the seed, the cleaner with the live
reference, and the running application, on synthetic workbooks:

* FVL Ranger ``11ROOF`` loads as ``11ROOF`` (not ``LCROOF``); CX743
  ``11LFRTDOOR`` loads as itself; slot 11 never crosses models. ``1HOOD``
  and ``01HOOD`` are one gold point; ``11ROOF`` is not ``14ROOF``.
* FVL ``17LIFGATE`` holds on a Ranger row and loads on a CX743 row.
* SAP Ranger and SAP J73 each load the T28 32 as themselves (no
  ``RRHOOD``, no tailgate Top/Bottom swap); SAP ``P703 RAP`` stays unknown.
* AAT ``01 RRHOOD`` still stores ``RRHOOD``; AAT ``01HOOD`` holds. FTM
  ``01 RRHOOD`` is ``RRHOOD``; FTM ``01HOOD`` is FTM compact gold.
* Hor/Ver follows the name, any case (SAP ``Hood`` is Horizontal), and
  ``ck_zone_rule`` agrees. ``[All]`` is still a roll-up; an extra panel holds.
* New inserts are gated by plant gold (``fk_ws_plant_point`` NOT VALID);
  earlier facts are kept as retired gold; a pick must be gold here.
* Viewer 403 on load-ready; ``app_rw`` still no UPDATE / DELETE on wavescan.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine

from app.domain.cleaner import Aggregate, Cleaner, CleanRow, Reject, RejectReason
from app.domain.reader import RawRow
from app.domain.ws_plant_gold import gold_key, ws_tolerance
from app.repositories.reference import load_reference_data
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t04_ingest import cleanup, forget_bytes, upload, wait_for  # noqa: F401

pytestmark = pytest.mark.ingest

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = json.loads(
    (REPO / "backend" / "migrations" / "seed" / "WS-plant-gold.json").read_text(encoding="utf-8")
)
GOLD = {(c["plant_code"], c["model_code"]): [p["zone_code"] for p in c["points"]]
        for c in EVIDENCE["catalogues"]}
RANGER, RAPTOR = "P703 DBL RANGER", "P703 DBL RAPTOR"
MEASURES = {m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")}


@pytest.fixture(scope="module")
def ref(app_database_url):
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            found = load_reference_data(conn)
    finally:
        engine.dispose()
    return found


def zone(ref, plant, model, raw):
    return Cleaner(ref, (plant,), expected_plant=plant).resolve_checkzone(plant, model, raw)


def offered_colour(ref, plant) -> str:
    return sorted(c for (p, c), on in ref.offered_colors.items() if p == plant and on)[0]


def row(ref, plant, model_cell, panel, **over) -> RawRow:
    values = dict(date="2026-09-08", plant=plant, model=model_cell, checkzone=panel,
                  color=offered_colour(ref, plant), **MEASURES)
    values.update(over)
    return RawRow(source_file="t58.xlsx", source_sheet="s", source_row=2, values=values)


def clean(ref, plant, *args, **kw):
    return Cleaner(ref, (plant,), expected_plant=plant).clean_row(row(ref, plant, *args, **kw))


# =====================================================================
# A. seed and schema
# =====================================================================
def test_evidence_lists_are_the_t28_and_compact_walks():
    assert {k: len(v) for k, v in GOLD.items()} == {
        ("FVL", RANGER): 32, ("FVL", "CX743"): 32, ("FVL", "V363"): 32,
        ("SAP", RANGER): 32, ("SAP", "J73 DBL"): 32,
        ("FTM", RANGER): 32, ("FTM", RAPTOR): 32,
    }
    fvl = GOLD[("FVL", RANGER)]
    assert fvl[0] == "1HOOD" and "11ROOF" in fvl and "14ROOF" in fvl and fvl[-1] == "32RTBOXSD"
    assert not {"17LIFGATE", "12DROPSIDE", "11LFRTDOOR"} & set(fvl), "no leftover on Ranger"
    assert GOLD[("SAP", RANGER)] == GOLD[("SAP", "J73 DBL")]
    assert GOLD[("SAP", RANGER)][16:18] == ["17LHS TG Top12", "18LHS TG Bot13"]
    assert GOLD[("FTM", RANGER)][0] == "01HOOD" and "17TGATE" in GOLD[("FTM", RANGER)]
    for cat in EVIDENCE["catalogues"]:
        for p in cat["points"]:
            assert set(p) == {"point_no", "zone_code", "tolerance_group", "panel_group"}


def test_live_gold_matches_the_evidence_and_the_long_form_copies(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code, zone_code, point_no, tolerance_group "
            "FROM ref_plant_ws_point WHERE retired_at IS NULL ORDER BY 1, 2, 4"
        )
        rows = cur.fetchall()
        cur.execute("SELECT model_code, zone_code, zone_no FROM ref_model_zone ORDER BY 1, 3")
        catalogue = cur.fetchall()
        # T113-FIX (D-113-1): FTM short-name block retired 2026-10-11. The
        # compact names are still gold -- as retired history, never deleted
        # (ADR 0005) -- so the evidence list is read from the retired rows.
        cur.execute(
            "SELECT model_code, zone_code, point_no, retired_reason "
            "FROM ref_plant_ws_point WHERE plant_code = 'FTM' "
            " AND retired_at IS NOT NULL ORDER BY 1, 3"
        )
        retired_ftm = cur.fetchall()
    live: dict[tuple[str, str], list[tuple]] = {}
    for p, m, z, n, t in rows:
        live.setdefault((p, m), []).append((z, n, t))
    retired: dict[tuple[str, str], list[tuple]] = {}
    for m, z, n, reason in retired_ftm:
        retired.setdefault(("FTM", m), []).append((z, n, reason))
    for key, names in GOLD.items():
        # T113-FIX (D-113-1): at FTM the compact walk is the retired block.
        source = retired[key] if key[0] == "FTM" else live[key]
        mine = [z for z, n, _r in source if not (key[0] == "FTM" and n <= 32)]
        assert mine == names, key
        assert all(t == ws_tolerance(z) for z, _n, t in live[key])
    for key in (("FTM", RANGER), ("FTM", RAPTOR)):
        # T113-FIX (D-113-1): 32 retired with T113's reason, and 0 live above 32.
        assert [n for _z, n, _r in retired[key]] == list(range(33, 65)), key
        assert all("T113" in reason for _z, _n, reason in retired[key]), key
        assert [n for _z, n, _t in live[key]] == list(range(1, 33)), key
    by_model: dict[str, list[str]] = {}
    for m, z, _n in catalogue:
        by_model.setdefault(m, []).append(z)
    for key in (("AAT", RANGER), ("AAT", "U704"), ("AAT", "P703 DBL SUPER DUTY"),
                ("SAP", RAPTOR)):
        assert [z for z, _n, _t in live[key]] == by_model[key[1]], key
    for key in (("FTM", RANGER), ("FTM", RAPTOR)):
        assert [z for z, n, _t in live[key] if n <= 32] == by_model[key[1]], key
    assert ("SAP", "P703 RAP") not in live


def test_sap_hood_is_horizontal_and_ck_zone_rule_agrees(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT zone_code, tolerance_group FROM ref_checkzone WHERE zone_code = ANY(%s)",
            (["01RHS Hood Rr28", "11LHS Roof6", "17LHS TG Top12", "11ROOF", "01HOOD"],),
        )
        got = dict(cur.fetchall())
        cur.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_zone_rule'")
        rule = cur.fetchone()[0]
    assert got == {"01RHS Hood Rr28": "Horizontal", "11LHS Roof6": "Horizontal",
                   "17LHS TG Top12": "Vertical", "11ROOF": "Horizontal", "01HOOD": "Horizontal"}
    assert "upper(zone_code)" in rule and "FLOOR" in rule


def test_inserts_are_gated_by_plant_gold_not_valid_and_old_facts_are_kept(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT conname, convalidated, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'wavescan'::regclass AND conname IN "
            "('fk_ws_plant_point', 'fk_ws_model_zone')"
        )
        fks = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        cur.execute(
            "SELECT count(*) FROM wavescan w WHERE NOT EXISTS (SELECT 1 FROM ref_plant_ws_point g "
            "WHERE g.plant_code = w.plant AND g.model_code = w.model AND g.zone_code = w.checkzone)"
        )
        orphans = cur.fetchone()[0]
    assert set(fks) == {"fk_ws_plant_point"}
    assert fks["fk_ws_plant_point"][0] is False and "ref_plant_ws_point" in fks["fk_ws_plant_point"][1]
    assert orphans == 0, "every earlier fact keeps an FK target (retired gold)"


def test_t31_fvl_maps_are_kept_not_deleted(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ref_plant_zone_map WHERE plant_code = 'FVL'")
        assert cur.fetchone()[0] > 0


def test_app_rw_reads_gold_and_cannot_rewrite_facts(admin_conn, app_role: str):
    with admin_conn.cursor() as cur:
        # T114 CHANGE (D-114-11): Point Check's add appends a list row, so
        # app_rw may now INSERT one. It still may not UPDATE (beyond the 0031
        # retire columns) or DELETE one, and facts stay untouchable.
        for table, privilege, allowed in (
            ("ref_plant_ws_point", "SELECT", True), ("ref_plant_ws_point", "INSERT", True),
            ("ref_plant_ws_point", "UPDATE", False), ("ref_plant_ws_point", "DELETE", False),
            ("wavescan", "UPDATE", False), ("wavescan", "DELETE", False),
        ):
            cur.execute("SELECT has_table_privilege(%s, %s, %s)", (app_role, table, privilege))
            assert cur.fetchone()[0] is allowed, (table, privilege)


# =====================================================================
# B. the cleaner (D-58-09)
# =====================================================================
def test_fvl_ranger_keeps_its_own_names_and_the_zero_pad(ref):
    assert zone(ref, "FVL", RANGER, "11ROOF") == "11ROOF"
    assert zone(ref, "FVL", RANGER, "14ROOF") == "14ROOF"
    assert zone(ref, "FVL", RANGER, "1HOOD") == zone(ref, "FVL", RANGER, "01HOOD") == "1HOOD"
    assert zone(ref, "FVL", RANGER, "11ROOF") != zone(ref, "FVL", RANGER, "14ROOF")
    assert zone(ref, "FVL", RANGER, "25TGATE") == "25TGATE"
    assert zone(ref, "FVL", RANGER, "01 RRHOOD") is None, "not FVL gold; never RRHOOD"
    assert gold_key("01HOOD") == gold_key("1HOOD") != gold_key("11HOOD")


def test_slot_11_never_crosses_ranger_and_cx743(ref):
    assert zone(ref, "FVL", "CX743", "11LFRTDOOR") == "11LFRTDOOR"
    assert zone(ref, "FVL", RANGER, "11LFRTDOOR") is None
    assert zone(ref, "FVL", "CX743", "11ROOF") is None
    assert zone(ref, "FVL", RANGER, "17LIFGATE") is None
    assert zone(ref, "FVL", "CX743", "17LIFGATE") == "17LIFGATE"


def test_fvl_rows_store_the_gold_name_and_the_file_text(ref):
    out = clean(ref, "FVL", "P703", "11ROOF")
    assert isinstance(out, CleanRow), out
    assert (out.model, out.checkzone, out.src_zone_text, out.src_zone_no, out.tolerance_group) == (
        RANGER, "11ROOF", "11ROOF", 11, "Horizontal",
    )
    pad = clean(ref, "FVL", "P703", "01HOOD")
    assert isinstance(pad, CleanRow) and pad.checkzone == "1HOOD" and pad.src_zone_text == "01HOOD"
    held = clean(ref, "FVL", "P703", "17LIFGATE")
    assert isinstance(held, Reject) and held.reason == RejectReason.UNKNOWN_CHECKZONE
    cx = clean(ref, "FVL", "CX743", "17LIFGATE")
    assert isinstance(cx, CleanRow) and (cx.model, cx.checkzone) == ("CX743", "17LIFGATE")


@pytest.mark.parametrize("model_cell, model", [("P703 DBL", RANGER), ("J73 DBL", "J73 DBL")])
def test_sap_t28_strings_are_gold_as_themselves_per_model(ref, model_cell, model):
    for label in GOLD[("SAP", model)]:
        assert zone(ref, "SAP", model, label) == label
    hood = clean(ref, "SAP", model_cell, "01RHS Hood Rr28")
    assert isinstance(hood, CleanRow), hood
    assert (hood.model, hood.checkzone, hood.tolerance_group) == (model, "01RHS Hood Rr28", "Horizontal")
    top = clean(ref, "SAP", model_cell, "17LHS TG Top12")
    assert isinstance(top, CleanRow) and top.checkzone == "17LHS TG Top12", "no Top/Bottom swap"
    assert zone(ref, "SAP", model, "01 RRHOOD") is None


def test_sap_p703_rap_is_raptor_and_sap_does_not_offer_raptor(ref):
    # T60 CHANGE (D-60-01..03): the Model cell resolves to Raptor.
    # RO18 CHANGE (owner decision): SAP has no Raptor -- P703 DBL RAPTOR is
    # not offered at SAP, so a `P703 RAP` row is refused on its model before
    # any panel is read, whatever the panel spelling.
    for label in ("01 RRHOOD", "01RHS Hood Rr28"):
        out = clean(ref, "SAP", "P703 RAP", label)
        assert isinstance(out, Reject), out
        assert out.reason == RejectReason.MODEL_NOT_OFFERED, out
        assert (out.column, out.value) == ("model", "P703 RAP")
        assert RAPTOR in out.detail


def test_aat_long_form_stays_and_aat_compact_holds(ref):
    out = clean(ref, "AAT", "U704", "01 RRHOOD")
    assert isinstance(out, CleanRow), out
    assert (out.checkzone, out.src_zone_text) == ("RRHOOD", "01 RRHOOD")
    held = clean(ref, "AAT", "U704", "01HOOD")
    assert isinstance(held, Reject) and held.reason == RejectReason.UNKNOWN_CHECKZONE


def test_ftm_long_form_and_compact_are_two_vocabularies(ref):
    """The long form is FTM's only vocabulary now.

    **T113-FIX (D-113-1): the short-name block was retired 2026-10-11**, so
    the compact spellings no longer resolve on their own -- which is what
    T113 measured and proved harmless: every one of FTM's 690 real short
    labels was already held as ``UNKNOWN_CHECKZONE`` and answered in the
    row. The long form still resolves, and a name of another model's
    vocabulary still does not.
    """
    assert zone(ref, "FTM", RANGER, "01 RRHOOD") == "RRHOOD"
    # T113-FIX (D-113-1): FTM short-name block retired 2026-10-11 -- held,
    # and asked in the row, instead of resolving to itself.
    assert zone(ref, "FTM", RANGER, "01HOOD") is None, "retired: not gold here any more"
    assert zone(ref, "FTM", RAPTOR, "17TGATE") is None
    assert zone(ref, "FTM", RANGER, "11ROOF") is None
    assert zone(ref, "FTM", RANGER, "11LFRTDOOR") is None


def test_junk_and_extra_panels(ref):
    agg = clean(ref, "FVL", "P703", "[All]")
    assert isinstance(agg, Aggregate)
    extra = clean(ref, "FVL", "P703", "99MYSTERY")
    assert isinstance(extra, Reject) and extra.reason == RejectReason.UNKNOWN_CHECKZONE
    assert isinstance(clean(ref, "FVL", "P703", "2HOOD"), CleanRow)


# =====================================================================
# C. picks and the running application
# =====================================================================
HEADERS = ["Date", "Plant", "Model", "Checkzone", "Color",
           "LW", "SW", "CF", "DOI", "du", "Wa", "Wb", "Wc", "Wd", "We"]


def workbook(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(HEADERS)
    for r in rows:
        ws.append([r.get(h, 1.5) for h in HEADERS])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _year_day() -> str:
    n = uuid.uuid4().int
    return f"{2001 + n % 15}-{(n // 15) % 12 + 1:02d}-{(n // 180) % 28 + 1:02d}"


def test_a_checkzone_pick_must_be_gold_at_that_plant(engineer, cleanup, ref, admin_conn):  # noqa: F811
    day = _year_day()
    data = workbook([{"Date": day, "Plant": "FVL", "Model": "P703", "Checkzone": "99MYSTERY",
                      "Color": offered_colour(ref, "FVL")}])
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t58-pick.xlsx", data, expected_plant="FVL")
    assert accepted.status_code == 202, accepted.text
    load_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    wait_for(engineer, load_id)
    for target, ok in (("RRHOOD", False), ("11LFRTDOOR", False)):
        response = engineer.post("/api/v1/mappings/proposals", json={
            "kind": "ALIAS_CHECKZONE", "load_id": load_id,
            "payload": {"plant_code": "FVL", "model_code": RANGER,
                        "raw_value": "99MYSTERY", "zone_code": target},
        })
        assert response.status_code == 422, (target, response.text)
        assert "panel list" in response.json()["message"]


def test_fvl_mixed_sheet_confirms_on_own_names(engineer, viewer, cleanup, ref, admin_conn):  # noqa: F811
    day = _year_day()
    colour = offered_colour(ref, "FVL")
    rows = [
        {"Date": day, "Plant": "FVL", "Model": "P703", "Checkzone": "11ROOF", "Color": colour},
        {"Date": day, "Plant": "FVL", "Model": "P703", "Checkzone": "01HOOD", "Color": colour},
        {"Date": day, "Plant": "FVL", "Model": "P703", "Checkzone": "17LIFGATE", "Color": colour},
        {"Date": day, "Plant": "FVL", "Model": "CX743", "Checkzone": "11LFRTDOOR", "Color": colour},
    ]
    data = workbook(rows)
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, f"t58-fvl-{uuid.uuid4().hex[:6]}.xlsx", data, expected_plant="FVL")
    assert accepted.status_code == 202, accepted.text
    load_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    review = wait_for(engineer, load_id)
    file_hash = review["batch"]["file_hash"]
    sheet = engineer.get(f"/api/v1/plants/FVL/workbooks/{file_hash}/worksheet").json()["sheets"][0]
    got = {r["panel_label"]: (r["outcome"], r["checkzone"], r["model"]) for r in sheet["rows"]}
    assert got == {
        "11ROOF": ("ready", "11ROOF", RANGER),
        "01HOOD": ("ready", "1HOOD", RANGER),
        # RO18 (B1): FVL Ranger's own list is now offerable, so the name is
        # asked in the row instead of only held. It still does not load.
        "17LIFGATE": ("needs_confirmation", None, None),
        "11LFRTDOOR": ("ready", "11LFRTDOOR", "CX743"),
    }, sheet["operator_message"]
    assert viewer.post(f"/api/v1/plants/FVL/workbooks/{file_hash}/load-ready").status_code == 403
    loaded = engineer.post(f"/api/v1/plants/FVL/workbooks/{file_hash}/load-ready")
    assert loaded.status_code == 200, loaded.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model, checkzone, src_zone_text, tolerance_group FROM wavescan "
            "WHERE load_id = %s ORDER BY source_row", (load_id,),
        )
        facts = cur.fetchall()
    assert facts == [
        (RANGER, "11ROOF", "11ROOF", "Horizontal"),
        (RANGER, "1HOOD", "01HOOD", "Horizontal"),
        ("CX743", "11LFRTDOOR", "11LFRTDOOR", "Vertical"),
    ]


def test_sap_sheet_loads_t28_strings_on_ranger_and_j73(engineer, cleanup, ref, admin_conn):  # noqa: F811
    day = _year_day()
    colour = offered_colour(ref, "SAP")
    rows = [
        {"Date": day, "Plant": "SAP", "Model": "P703 DBL", "Checkzone": "01RHS Hood Rr28", "Color": colour},
        {"Date": day, "Plant": "SAP", "Model": "P703 DBL", "Checkzone": "17LHS TG Top12", "Color": colour},
        {"Date": day, "Plant": "SAP", "Model": "J73 DBL", "Checkzone": "01RHS Hood Rr28", "Color": colour},
        {"Date": day, "Plant": "SAP", "Model": "P703 DBL", "Checkzone": "Horizontal", "Color": colour},
    ]
    data = workbook(rows)
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, f"t58-sap-{uuid.uuid4().hex[:6]}.xlsx", data, expected_plant="SAP")
    assert accepted.status_code == 202, accepted.text
    load_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    review = wait_for(engineer, load_id)
    file_hash = review["batch"]["file_hash"]
    sheet = engineer.get(f"/api/v1/plants/SAP/workbooks/{file_hash}/worksheet").json()["sheets"][0]
    got = [(r["panel_label"], r["outcome"], r["checkzone"], r["model"]) for r in sheet["rows"]]
    assert got == [  
        ("01RHS Hood Rr28", "ready", "01RHS Hood Rr28", RANGER),
        ("17LHS TG Top12", "ready", "17LHS TG Top12", RANGER),
        ("01RHS Hood Rr28", "ready", "01RHS Hood Rr28", "J73 DBL"),
        ("Horizontal", "held_out", None, None),
    ], (sheet["operator_message"], [r["operator_message"] for r in sheet["rows"]])
