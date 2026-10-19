"""T30 -- SAP July/August P703 activation, against the live API.

G1 (`docs/reports/G1-P703-OWNER-PROOF.md`) names Efe Ularika and the July
workbook hash. This suite applies that signed 32-row set through the T29
ZONE path, plant-scopes the G1 model aliases, owner-publishes a stored
synthetic fixture, and commits July-shaped and August-canonical sheets.
June without a serial still cannot become facts. This suite does not
flip FVL `is_active`.

No Ford workbook is copied into git. Fixtures are synthetic, shaped like
T26's SAP July reorder and the canonical 21-column layout. Maps and the
published SAP profile are removed as the owner afterwards so T26's
"SAP cannot commit" claim stays true for later tests.
"""

from __future__ import annotations

from tests.conftest import delete_rows_created_since, row_keys
import re
import uuid
from pathlib import Path

import pytest

from tests.test_t04_ingest import forget_proposals

from tests.test_t04_ingest import (
    acknowledge_required,
    forget_bytes,
    upload,
    wait_for,
)
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
)
from tests.test_t08_mapping import approve
from tests.test_t26_semantic_clean_layer import (
    HEADERS,
    SAP_JULY_SHAPED,
    published_profiles,
    sheet_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
G1_PATH = REPO_ROOT / "backend" / "tests" / "fixtures" / "gold" / "G1-P703-OWNER-PROOF.md"

#: G1-signed SAP raw labels (T28 cell text) -> canonical zone_code.
#: Tailgate 20/21 by meaning, not FTM index. Do not read T28 proposed_zone_code.
SAP_MAPPINGS = [
    (1, "01RHS Hood Rr28", "RRHOOD"),
    (2, "02RHS Hood Frnt29", "RFHOOD"),
    (3, "03Hood Middle30", "CFHOOD"),
    (4, "04LHS Hood Frnt31", "LFHOOD"),
    (5, "05LHS Hood Rr32", "LRHOOD"),
    (6, "06LHS Fender Frnt1", "LFFENDER"),
    (7, "07LHS Fender Middle2", "LCFENDER"),
    (8, "08LHS Fender Rr3", "LRFENDER"),
    (9, "09LHS FD Frnt4", "LTFDOOR"),
    (10, "10LHS FD Rr5", "LCFDOOR"),
    (11, "11LHS Roof6", "LCROOF"),
    (12, "12LHS RD RR7", "LCRDOOR"),
    (13, "13LHS C-Pillar8", "LCPILLAR"),
    (14, "14LHS Box Frnt9", "LFBOX"),
    (15, "15LHS Box Middle10", "LCBOX"),
    (16, "16LHS Box Rr11", "LRBOX"),
    (17, "17LHS TG Top12", "LTTAILGATE"),
    (18, "18LHS TG Bot13", "LBTAILGATE"),
    (19, "19Tailgate Middle14", "LCTAILGATE"),
    (20, "20RHS TG Top15", "RTTAILGATE"),
    (21, "21RHS TG Bot16", "RBTAILGATE"),
    (22, "22RHS Box Rr17", "RRBOX"),
    (23, "23RHS Box Middle18", "RCBOX"),
    (24, "24RHS Box Frnt19", "RFBOX"),
    (25, "25RHS C-Pillar20", "RCPILLAR"),
    (26, "26RHS RD RR21", "RCRDOOR"),
    (27, "27RHS Roof22", "RCROOF"),
    (28, "28RHS FD Rr23", "RCFDOOR"),
    (29, "29RHS FD Frnt24", "FTFDOOR"),
    (30, "30RHS Fender Rr25", "RRFENDER"),
    (31, "31RHS Fender Middl26", "RCFENDER"),
    (32, "32RHS Fender Frnt27", "RFFENDER"),
]

HORIZONTAL = {
    "RRHOOD", "RFHOOD", "CFHOOD", "LFHOOD", "LRHOOD", "LCROOF", "RCROOF",
}

SAP_ALIAS_SPELLINGS = ("P703", "P703 DBL", "P703 RAP")


def read_g1() -> tuple[str, str]:
    text = G1_PATH.read_text(encoding="utf-8")
    owner = re.search(r"\| `named_owner` \| `([^`]+)` \|", text)
    proof = re.search(r"\| `proof_hash` \| `([0-9a-f]{64})` \|", text)
    assert owner and proof, "G1 SAP section must name named_owner and 64-hex proof_hash"
    assert "20RHS TG Top15" in text and "RTTAILGATE" in text
    assert "21RHS TG Bot16" in text and "RBTAILGATE" in text
    return owner.group(1), proof.group(1)


def zone_payload(model: str, owner: str, proof: str) -> dict:
    return {
        "plant_code": "SAP",
        "model_code": model,
        "mappings": [
            {
                "raw_zone_text": raw,
                "raw_position": pos,
                "zone_code": code,
            }
            for pos, raw, code in SAP_MAPPINGS
        ],
        "named_owner": owner,
        "proof_hash": proof,
        "proof_document": (
            "G1 SAP: T28 hash of 7 Jul-26 P703 & J73 CF INPUT.xlsx; "
            "matrices in docs/reports/G1-P703-DECISIONS.md"
        ),
        "method": (
            "Owner-signed raw_label to zone_code. Tailgate by meaning, "
            "not FTM index 20/21. Not keyword or sequence."
        ),
        "note": "T30 SAP activation from G1-P703-OWNER-PROOF.md",
    }


def sap_rows(model: str, *, serial: str | None = True) -> list[dict]:
    token = uuid.uuid4().hex[:10]
    serial_no = None if serial is None else f"T30-{token}"
    rows = []
    for i, (_pos, raw, code) in enumerate(SAP_MAPPINGS):
        rows.append(
            {
                "Plant": "SAP",
                "Model": model,
                "Color": "Frozen White",
                "Checkzone": raw,
                "Serial No": serial_no if serial_no is not None else "",
                "CF": 50.0 + i,
                "Tolerance Group": (
                    "Horizontal" if code in HORIZONTAL else "Vertical"
                ),
            }
        )
    return rows


def test_g1_sap_names_efe_ularika_and_the_july_hash():
    """Gate: T30 does not start without this file. No ingest needed."""
    owner, proof = read_g1()
    assert owner == "Efe Ularika"
    assert proof == (
        "46fcaf58bc3125937b6c0ed9be13efef3e13230ccc93324d19c978db83b5178d"
    )
    assert owner.casefold() != "admin"


@pytest.fixture()
def sap_maps(engineer, admin, admin_conn):
    """Approve both G1 SAP ZONE sets. Remove them as the owner afterwards.

    T76 CHANGE: only the maps this fixture approved. The G1 owner and proof
    are real; a live SAP map under the same proof is never deleted here.
    """
    maps_before = row_keys(admin_conn, "ref_plant_zone_map", "map_id")
    owner, proof = read_g1()
    for model in ("P703 DBL RANGER", "P703 DBL RAPTOR"):
        created = engineer.post(
            "/api/v1/mappings/proposals",
            json={"kind": "ZONE", "payload": zone_payload(model, owner, proof)},
        )
        assert created.status_code == 201, created.text
        approved = approve(admin, created.json()["id"])
        assert approved.status_code == 200, approved.text
    yield owner, proof
    delete_rows_created_since(
        admin_conn, "ref_plant_zone_map", "map_id", maps_before,
        "plant_code = 'SAP' AND verified_by = %s AND proof_hash = %s",
        (owner, proof),
    )


@pytest.fixture()
def sap_alias_cleanup(admin_conn):
    """T76 CHANGE: no delete before the test, and after it only the SAP
    aliases the test itself approved. The revision 0020 / 0023 seeds and any
    owner alias of these spellings stay (the T64 incident class)."""
    where = "plant_code = 'SAP' AND raw_value = ANY(%s)"
    params = (list(SAP_ALIAS_SPELLINGS),)
    before = row_keys(admin_conn, "ref_model_alias", "alias_id", where, params)
    yield
    delete_rows_created_since(
        admin_conn, "ref_model_alias", "alias_id", before, where, params
    )


@pytest.fixture()
def fvl_inactive(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        before = cur.fetchone()[0]
    yield
    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        after = cur.fetchone()[0]
    assert after == before, "T30 must never flip FVL is_active"


def _upload_sap(
    engineer,
    admin,
    admin_conn,
    cleanup,
    published_profiles,
    owner: str,
    headers: list[str],
    model: str,
    filename: str,
) -> int:
    """Parse + publish until PENDING_REVIEW. Does not commit.

    ALIAS_MODEL approve replays the batch, which is refused once the sheet
    is COMMITTED -- so aliases have to land while the load is still reviewable.
    """
    data = sheet_bytes(headers, sap_rows(model), sheet="PasteData")
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, filename, data, "SAP")
    assert accepted.status_code == 202, accepted.text
    load_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    review = wait_for(engineer, load_id)
    assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"].get("notes")
    file_hash = review["batch"]["file_hash"]

    if "UNVERIFIED_PROFILE" in review.get("commit_blockers", []):
        published = admin.post(
            "/api/v1/plants/SAP/template-profiles/publish",
            json={
                "file_hash": file_hash,
                "source_sheet": "PasteData",
                "named_owner": owner,
                "notes": "T30 synthetic SAP fixture; G1 map already approved.",
            },
        )
        assert published.status_code == 200, published.text
        body = published.json()
        published_profiles.append((body["profile_id"], body["previous_profile_id"]))
        review = wait_for(engineer, load_id)
    return load_id


def _finish_commit(engineer, admin, load_id: int) -> None:
    review = wait_for(engineer, load_id)
    acknowledge_required(admin, review)
    review = wait_for(engineer, load_id)
    assert review["committable"] is True, review["commit_blockers"]
    committed = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert committed.status_code == 200, committed.text


@pytest.mark.ingest
def test_july_and_august_p703_commit_and_june_parses_without_serials(
    engineer,
    admin,
    admin_conn,
    cleanup,
    published_profiles,
    sap_maps,
    sap_alias_cleanup,
    fvl_inactive,
):
    owner, _proof = sap_maps

    july_id = _upload_sap(
        engineer, admin, admin_conn, cleanup, published_profiles, owner,
        SAP_JULY_SHAPED, "P703 DBL RANGER", "t30-sap-july.xlsx",
    )
    # T55 CHANGE: SAP `P703 DBL` -> Ranger is seeded by revision 0020
    # (D-55-02); only the spellings still unnamed are taught here.
    # T60 CHANGE: SAP `P703 RAP` -> Raptor is seeded by revision 0023 (G1 D-06).
    for raw, model in (
        ("P703", "P703 DBL RANGER"),
    ):
        proposed = engineer.post(
            "/api/v1/mappings/proposals",
            json={
                "kind": "ALIAS_MODEL",
                "load_id": july_id,
                "payload": {
                    "raw_value": raw,
                    "model_code": model,
                    "note": "G1 SAP plant-scoped alias",
                },
            },
        )
        assert proposed.status_code == 201, proposed.text
        assert proposed.json()["status"] == "APPROVED"
        # Identity apply queues replay (RUNNING). The next alias also replays;
        # only PENDING_REVIEW / REJECTED_TEMPLATE are replayable.
        waited = wait_for(engineer, july_id)
        assert waited["batch"]["status"] == "PENDING_REVIEW", waited["batch"].get(
            "notes"
        )

    _finish_commit(engineer, admin, july_id)
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT checkzone, src_zone_text, model "
            "  FROM wavescan WHERE load_id = %s AND is_duplicate = false "
            " ORDER BY checkzone",
            (july_id,),
        )
        rows = cur.fetchall()
    assert len(rows) == 32, rows
    by_src = {src: (zone, model) for zone, src, model in rows}
    # T58 CHANGE (D-58-01, D-58-13): SAP Ranger gold is SAP's own T28 32, so
    # each checkpoint is stored as the SAP string itself -- never a canonical
    # tailgate, never a Top/Bottom swap. The G1 ZONE pack onto canonical codes
    # is not read at a plant x model with its own gold.
    assert by_src["20RHS TG Top15"][0] == "20RHS TG Top15"
    assert by_src["21RHS TG Bot16"][0] == "21RHS TG Bot16"
    assert all(zone == src for src, (zone, _model) in by_src.items())
    assert {model for _z, _s, model in rows} == {"P703 DBL RANGER"}

    aug_id = _upload_sap(
        engineer, admin, admin_conn, cleanup, published_profiles, owner,
        HEADERS, "P703 DBL", "t30-sap-august.xlsx",
    )
    _finish_commit(engineer, admin, aug_id)
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT model FROM wavescan WHERE load_id = %s",
            (aug_id,),
        )
        assert {r[0] for r in cur.fetchall()} == {"P703 DBL RANGER"}

    rap_id = _upload_sap(
        engineer, admin, admin_conn, cleanup, published_profiles, owner,
        SAP_JULY_SHAPED, "P703 RAP", "t30-sap-rap.xlsx",
    )
    _finish_commit(engineer, admin, rap_id)
    # T96 CHANGE (D-96-1): `P703 DBL RAPTOR` is the one SAP model with a
    # canonical list (32; `P703 DBL RANGER` has none -- T89 Part 1), and
    # SAP's own labels lead with a number and name no canonical panel
    # (`01RHS Hood Rr28`), so every row of this file now asks in the row
    # instead of loading. The model resolution this test is about is
    # unchanged and is asserted on the staging rows, which carry it
    # whether or not the panel question is answered.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT model FROM wavescan WHERE load_id = %s",
            (rap_id,),
        )
        assert {r[0] for r in cur.fetchall()} == set()
        cur.execute(
            "SELECT file_hash FROM load_batch WHERE load_id = %s", (rap_id,)
        )
        [(rap_hash,)] = cur.fetchall()
    worksheet = engineer.get(f"/api/v1/plants/SAP/workbooks/{rap_hash}/worksheet")
    assert worksheet.status_code == 200, worksheet.text
    [rap_sheet] = worksheet.json()["sheets"]
    rough = rap_sheet["rough_panels"]
    # The model resolution this test is about: the rough set is keyed by the
    # RESOLVED model, so `P703 RAP` reaching `P703 DBL RAPTOR` is what this
    # asserts -- and every one of the 32 SAP spellings is asked about.
    assert {panel["model_code"] for panel in rough} == {"P703 DBL RAPTOR"}
    assert len(rough) == 32, sorted(p["raw_zone_text"] for p in rough)
    assert all(panel["proposed_zone_code"] for panel in rough)

    june = sheet_bytes(
        HEADERS,
        sap_rows("P703 DBL RANGER", serial=None),
        sheet="PasteData",
    )
    forget_bytes(admin_conn, june)
    accepted = upload(engineer, "t30-sap-june.xlsx", june, "SAP")
    assert accepted.status_code == 202, accepted.text
    june_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(june_id)
    review = wait_for(engineer, june_id)
    blockers = review["commit_blockers"]
    # T39 CHANGE (ADR 0013 decision 2): blank serials load NULL and the
    # sheet is the vehicle, so June is no longer blocked for identity. No
    # serial is invented.
    assert "VEHICLE_IDENTITY_MISSING" not in blockers, blockers
    assert review["batch"]["counts"]["rows_loaded"] > 0, review["batch"]["counts"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM stg_review_row WHERE load_id = %s "
            "AND disposition = 'LOAD' AND (canonical ->> 'serial_no') IS NOT NULL",
            (june_id,),
        )
        assert cur.fetchone()[0] == 0, "no serial was invented"


@pytest.fixture(autouse=True)
def _t92_proposal_cleanup(admin_conn):
    """T92 Part 5: this module's own mapping proposals, removed after each test.

    The leak T89, T90 and T91 each reported and none owned: this module
    creates `proposed_mapping` rows and nothing deleted them, so 513 rows of
    test residue accumulated in the owner's live trial database. Snapshot
    first and delete only what this test added (the T76 shape), then fail
    loudly rather than leak (T87 D-87-8).
    """
    before = row_keys(admin_conn, "proposed_mapping", "id")
    yield
    forget_proposals(admin_conn, before, ["T30 SAP activation from G1-P703-OWNER-PROOF.md"], 'T30 SAP activation')
