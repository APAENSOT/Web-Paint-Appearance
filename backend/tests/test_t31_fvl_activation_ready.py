"""T31 -- FVL P703 maps while inactive, against the live API.

G1 FVL (`docs/reports/G1-P703-OWNER-PROOF.md`) names Efe Ularika and the
August `CF_Aug.xlsx` hash. This suite stores that signed 32-row set through
the T29 ZONE path with no `load_id`, then stores September `01HOOD` as a
second raw spelling of `RRHOOD` (same proof, not a silent merge of keys).
This suite does not flip `is_active` and does not publish a template. T32
may have onboarded FVL; T31 still only proves the maps.

No Ford workbook is copied into git. Maps are removed as the owner afterwards
so T29's leftover-map guard still holds on this cluster.
"""

from __future__ import annotations

from tests.conftest import delete_rows_created_since, row_keys
import re
from pathlib import Path

import pytest

from tests.test_t04_ingest import forget_proposals
from sqlalchemy import create_engine

from app.domain.references import normalise_alias
from app.repositories import reference as reference_repo
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    engineer,
    ingest_apps,
)
from tests.test_t08_mapping import approve

REPO_ROOT = Path(__file__).resolve().parents[2]
G1_PATH = REPO_ROOT / "backend" / "tests" / "fixtures" / "gold" / "G1-P703-OWNER-PROOF.md"

AUGUST_HASH = (
    "c0f9a8dae0ec329da740af29b04f76ffcce980ff7059804724bffe302854cad0"
)

#: G1-signed FVL August labels (Ranger SC/CC picture) -> canonical zone_code.
FVL_MAPPINGS = [
    (1, "1HOOD", "RRHOOD"),
    (2, "2HOOD", "RFHOOD"),
    (3, "3HOOD", "CFHOOD"),
    (4, "4HOOD", "LFHOOD"),
    (5, "5HOOD", "LRHOOD"),
    (6, "06LFFENDER", "LFFENDER"),
    (7, "07LFFENDER", "LCFENDER"),
    (8, "08LFFENDER", "LRFENDER"),
    (9, "09LFFTDOOR", "LTFDOOR"),
    (10, "10LFFTDOOR", "LCFDOOR"),
    (11, "11ROOF", "LCROOF"),
    (12, "12LDRPOST", "LCPILLAR"),
    (13, "13LFRDOOR", "LCRDOOR"),
    (14, "14ROOF", "RCROOF"),
    (15, "15RCPILLAR", "RCPILLAR"),
    (16, "16RTRDOOR", "RCRDOOR"),
    (17, "17RTFTDOOR", "RCFDOOR"),
    (18, "18RTFTDOOR", "FTFDOOR"),
    (19, "19RTFENDER", "RRFENDER"),
    (20, "20RTFENDER", "RCFENDER"),
    (21, "21RTFENDER", "RFFENDER"),
    (22, "22LFBOXSD", "LFBOX"),
    (23, "23LFBOXSD", "LCBOX"),
    (24, "24LFBOXSD", "LRBOX"),
    (25, "25TGATE", "LTTAILGATE"),
    (26, "26TGATE", "LBTAILGATE"),
    (27, "27TGATE", "LCTAILGATE"),
    (28, "28TGATE", "RTTAILGATE"),
    (29, "29TGATE", "RBTAILGATE"),
    (30, "30RTBOXSD", "RRBOX"),
    (31, "31RTBOXSD", "RCBOX"),
    (32, "32RTBOXSD", "RFBOX"),
]


def read_g1_fvl() -> tuple[str, str]:
    text = G1_PATH.read_text(encoding="utf-8")
    section = text.split("## FVL", 1)
    assert len(section) == 2, "G1 must have an FVL section"
    fvl = section[1]
    owner = re.search(r"\| `named_owner` \| `([^`]+)` \|", fvl)
    proof = re.search(r"\| `proof_hash` \| `([0-9a-f]{64})` \|", fvl)
    assert owner and proof, "G1 FVL must name named_owner and 64-hex proof_hash"
    assert "`1HOOD`" in fvl and "`01HOOD`" in fvl
    assert "second" in fvl.casefold()
    assert "11ROOF" in fvl and "LCROOF" in fvl
    assert "14ROOF" in fvl and "RCROOF" in fvl
    assert "28TGATE" in fvl and "RTTAILGATE" in fvl
    return owner.group(1), proof.group(1)


def zone_payload(owner: str, proof: str, mappings: list[tuple[int, str, str]]) -> dict:
    return {
        "plant_code": "FVL",
        "model_code": "P703 DBL RANGER",
        "mappings": [
            {
                "raw_zone_text": raw,
                "raw_position": pos,
                "zone_code": code,
            }
            for pos, raw, code in mappings
        ],
        "named_owner": owner,
        "proof_hash": proof,
        "proof_document": (
            "G1 FVL: T28 hash of 08 Aug data/CF_Aug.xlsx; "
            "matrix in docs/reports/G1-P703-DECISIONS.md"
        ),
        "method": (
            "Owner-signed picture map. 01HOOD is operator padding of "
            "picture 1, not a second panel. Not keyword or sequence."
        ),
        "note": "T31 FVL activation-ready from G1-P703-OWNER-PROOF.md",
    }


def padded_hood_mappings() -> list[tuple[int, str, str]]:
    """Same 32 zones; picture 1 spelled as September wrote it."""
    out = []
    for pos, raw, code in FVL_MAPPINGS:
        out.append((pos, "01HOOD", code) if raw == "1HOOD" else (pos, raw, code))
    return out


def test_g1_fvl_names_efe_ularika_and_the_august_hash():
    """Gate: T31 does not start without this file. No ingest needed."""
    owner, proof = read_g1_fvl()
    assert owner == "Efe Ularika"
    assert proof == AUGUST_HASH
    assert owner.casefold() != "admin"


@pytest.fixture()
def fvl_maps(engineer, admin, admin_conn):
    owner, proof = read_g1_fvl()
    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        before_active = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM ref_template_profile "
            " WHERE plant_code = 'FVL' AND fixture_verified"
        )
        before_verified = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM ref_model_alias "
            " WHERE plant_code IS NULL AND raw_value IN ('P703', 'P703 DBL')"
        )
        before_global = cur.fetchone()[0]

    # T76 CHANGE: snapshot first -- the live FVL leftover maps (0013) carry
    # this same owner and proof; only the maps approved here are removed.
    maps_before = row_keys(admin_conn, "ref_plant_zone_map", "map_id")
    for mappings in (FVL_MAPPINGS, padded_hood_mappings()):
        created = engineer.post(
            "/api/v1/mappings/proposals",
            json={"kind": "ZONE", "payload": zone_payload(owner, proof, mappings)},
        )
        assert created.status_code == 201, created.text
        approved = approve(admin, created.json()["id"])
        assert approved.status_code == 200, approved.text
        assert approved.json()["replay"] is None

    yield owner, proof, before_verified, before_global, before_active

    delete_rows_created_since(
        admin_conn, "ref_plant_zone_map", "map_id", maps_before,
        "plant_code = 'FVL' AND verified_by = %s AND proof_hash = %s "
        "AND model_code LIKE 'P703%%'",
        (owner, proof),
    )
    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        assert cur.fetchone()[0] == before_active, "T31 must never flip FVL is_active"


@pytest.mark.ingest
def test_fvl_maps_are_stored_plant_stays_inactive_and_01hood_is_extra_raw(
    admin_conn, app_database_url, fvl_maps
):
    owner, proof, before_verified, before_global, before_active = fvl_maps
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT raw_zone_text, zone_code FROM ref_plant_zone_map "
            " WHERE plant_code = 'FVL' AND model_code = 'P703 DBL RANGER' "
            "   AND verified_by = %s AND proof_hash = %s",
            (owner, proof),
        )
        rows = {(normalise_alias(raw), zone) for raw, zone in cur.fetchall()}
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        after_active = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM ref_template_profile "
            " WHERE plant_code = 'FVL' AND fixture_verified"
        )
        after_verified = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM ref_model_alias "
            " WHERE plant_code IS NULL AND raw_value IN ('P703', 'P703 DBL')"
        )
        after_global = cur.fetchone()[0]

    by_raw = dict(rows)
    assert len(by_raw) == 33, rows
    assert by_raw[normalise_alias("1HOOD")] == "RRHOOD"
    assert by_raw[normalise_alias("01HOOD")] == "RRHOOD"
    assert by_raw[normalise_alias("11ROOF")] == "LCROOF"
    assert by_raw[normalise_alias("14ROOF")] == "RCROOF"
    assert by_raw[normalise_alias("28TGATE")] == "RTTAILGATE"
    assert by_raw[normalise_alias("29TGATE")] == "RBTAILGATE"
    assert {zone for _raw, zone in rows} == {code for _p, _r, code in FVL_MAPPINGS}

    assert after_active == before_active
    assert after_verified == before_verified
    assert after_global == before_global

    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            ref = reference_repo.load_reference_data(conn)
    finally:
        engine.dispose()
    key = ("FVL", "P703 DBL RANGER")
    assert ref.plant_zone_map[(*key, normalise_alias("1HOOD"))] == "RRHOOD"
    assert ref.plant_zone_map[(*key, normalise_alias("01HOOD"))] == "RRHOOD"


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
    forget_proposals(admin_conn, before, ["T31 FVL activation-ready from G1-P703-OWNER-PROOF.md"], 'T31 FVL activation-ready')
