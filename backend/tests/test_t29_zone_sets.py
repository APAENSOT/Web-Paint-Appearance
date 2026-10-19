"""T29 -- atomic 32-row ZONE mapping sets.

`ZONE` is a kind the data model has declared since T02 and the API answered
501 for until now. T29 makes it a real mutation on the **existing** path
(`POST /mappings/proposals` and `.../approve`), under the P703 spec section 5
contract:

* One proposal is one **complete** set for one `(plant, model)`: 32 rows whose
  `zone_code` set equals `ref_model_zone` for that model. A 31-row set, a
  33-row set, or 32 rows that swap `LTTAILGATE` for a second hood are refused
  before anything is written.
* Approve is **all or nothing**. A row that already maps the same raw label to
  a *different* zone, or carries a *different* proof, refuses the whole set
  and nothing is written.
* Every approved row carries S15 proof -- `proof_hash`, `proof_document`, and
  a typed `verified_by` that is a named person, not the Admin who pressed
  approve -- and the loader now reads **only** proved rows.
* FVL may propose with no `load_id` (it has nothing committable to replay);
  approving stores the maps and flips nothing.

Everything here runs against PostgreSQL and the running application, because
the claims are about what is stored, what is refused and what a grant allows.
No zone map is seeded: every row this suite writes carries a run-scoped raw
label and is removed as the owner afterwards. No Ford workbook, owner name or
real proof hash is in this file.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests.test_t04_ingest import forget_proposals

from tests.conftest import SUITE_STARTED, row_keys
from sqlalchemy import create_engine

from app.domain.references import normalise_alias
from app.repositories import reference as reference_repo
from tests.test_t04_ingest import unique_rows
from tests.test_t04_ingest import (  # noqa: F401  (fixtures, by import)
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)
from tests.test_t08_mapping import approve, propose, rejected_template_batch

pytestmark = pytest.mark.ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: `ref_model_zone.zone_no` 1-32 for every P703 variant (plan, "Canonical P703
#: zone_code order"). Checked against the catalogue by
#: `test_the_fixture_matches_the_catalogue` rather than trusted.
P703_ZONE_CODES = [
    "RRHOOD", "RFHOOD", "CFHOOD", "LFHOOD", "LRHOOD",
    "LFFENDER", "LCFENDER", "LRFENDER", "LTFDOOR", "LCFDOOR",
    "LCROOF", "LCRDOOR", "LCPILLAR", "LFBOX", "LCBOX", "LRBOX",
    "LTTAILGATE", "LBTAILGATE", "LCTAILGATE", "RBTAILGATE", "RTTAILGATE",
    "RRBOX", "RCBOX", "RFBOX", "RCPILLAR", "RCRDOOR", "RCROOF", "RCFDOOR", "FTFDOOR",
    "RRFENDER", "RCFENDER", "RFFENDER",
]

#: Synthetic proof: 64 lowercase hex, and obviously not a workbook's digest.
PROOF = "ab" * 32
OTHER_PROOF = "cd" * 32
#: A role name, not a person. G1 supplies the real one; this suite must not.
OWNER = "Quality Owner (synthetic, T29 suite)"

_RUN = uuid.uuid4().hex[:8]


def raw_label(code: str, tag: str) -> str:
    """A raw checkpoint label nobody else will ever write.

    Run- and test-scoped, and already in the normalised form the service
    stores, so a test can look a row up by what it sent.
    """
    return normalise_alias(f"t29-{_RUN}-{tag}-{code}")


def zone_body(
    *,
    tag: str,
    plant: str = "FVL",
    model: str = "P703 DBL RANGER",
    codes: list[str] | None = None,
    load_id: int | None = None,
    **payload_over,
) -> dict:
    codes = list(P703_ZONE_CODES if codes is None else codes)
    payload = {
        "plant_code": plant,
        "model_code": model,
        "mappings": [
            {"raw_zone_text": raw_label(code, tag).upper(), "zone_code": code}
            for code in codes
        ],
        "named_owner": OWNER,
        "proof_hash": PROOF,
        "proof_document": "synthetic fixture hash only (T29 suite)",
        "method": "owner-signed matrix; not keyword grouping or sequence",
        "note": "T29 test set",
    }
    payload.update(payload_over)
    body = {"kind": "ZONE", "payload": payload}
    if load_id is not None:
        body["load_id"] = load_id
    return body


def post_zone(client, body: dict):
    return client.post("/api/v1/mappings/proposals", json=body)


def zone_rows(admin_conn, tag: str) -> list[dict]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT map_id, plant_code, model_code, raw_zone_text, zone_code, "
            "       confidence, approved_by, proof_hash, proof_document, "
            "       verified_by, proposal_method "
            "  FROM ref_plant_zone_map WHERE raw_zone_text LIKE %s "
            " ORDER BY raw_zone_text",
            (normalise_alias(f"t29-{_RUN}-{tag}-") + "%",),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def owner_insert(admin_conn, tag: str, code: str, zone: str, **over) -> int:
    """A pre-existing zone-map row, written as the owner (legacy state)."""
    row = {
        "plant": "FVL", "model": "P703 DBL RANGER",
        "confidence": "APPROVED", "approved_by": "legacy admin",
        "proof_hash": None, "verified_by": None,
    }
    row.update(over)
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ref_plant_zone_map
                (plant_code, model_code, raw_zone_text, zone_code, confidence,
                 approved_by, approved_at, proof_hash, verified_by, note)
            VALUES (%(plant)s, %(model)s, %(raw)s, %(zone)s, %(confidence)s,
                    %(approved_by)s,
                    CASE WHEN %(approved_by)s::text IS NULL THEN NULL ELSE now() END,
                    %(proof_hash)s, %(verified_by)s, 'inserted by the T29 suite')
            RETURNING map_id
            """,
            {**row, "raw": raw_label(code, tag), "zone": zone},
        )
        return cur.fetchone()[0]


def proposal_status(admin_conn, proposal_id: str) -> str:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM proposed_mapping WHERE id = %s", (proposal_id,))
        return cur.fetchone()[0]


@pytest.fixture(autouse=True)
def zone_cleanup(admin_conn):
    """Remove every zone-map row this run wrote, as the owner.

    `app_rw` has no DELETE on `ref_plant_zone_map` and T29 does not add one;
    an approved mapping is permanent as far as the application is concerned.
    """
    yield
    prefix = normalise_alias(f"t29-{_RUN}-") + "%"
    with admin_conn.cursor() as cur:
        # T95 D-95-1: the `t29-<run>-` prefix is already a spelling nothing
        # else writes, but the delete still names all three columns, read
        # back from the rows this run actually wrote, so the rule holds
        # here too and the guard test needs no exception.
        cur.execute(
            "SELECT DISTINCT plant_code, model_code FROM ref_plant_zone_map"
            " WHERE raw_zone_text LIKE %s",
            (prefix,),
        )
        for plant, model in cur.fetchall():
            # T98 (D-98-2): and bounded in time, uniformly with every other
            # reference cleanup -- a `LIKE` is not a bound.
            cur.execute(
                "DELETE FROM ref_plant_zone_map WHERE plant_code = %s"
                "   AND model_code = %s AND raw_zone_text LIKE %s"
                "   AND created_at >= %s",
                (plant, model, prefix, SUITE_STARTED),
            )


@pytest.fixture()
def fvl_state(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        before = cur.fetchone()[0]
    yield before
    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        assert cur.fetchone()[0] == before, "T29 must never flip FVL is_active"


# =====================================================================
# 0. the fixture is the catalogue
# =====================================================================
def test_the_fixture_matches_the_catalogue(admin_conn):
    with admin_conn.cursor() as cur:
        for model in ("P703 DBL RANGER", "P703 DBL RAPTOR", "P703 DBL SUPER DUTY"):
            cur.execute(
                "SELECT zone_code FROM ref_model_zone WHERE model_code = %s "
                "ORDER BY zone_no",
                (model,),
            )
            assert [r[0] for r in cur.fetchall()] == P703_ZONE_CODES, model


# =====================================================================
# 1. propose: 201 writes no map; 422 before anything is written
# =====================================================================
def test_zone_propose_without_load_id_on_inactive_fvl_is_201_and_writes_no_map(
    engineer, admin_conn, fvl_state
):
    response = post_zone(engineer, zone_body(tag="p201"))
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["kind"] == "ZONE"
    assert created["load_id"] is None
    assert created["status"] == "PROPOSED"
    # Stored normalised, the key the cleaner already uses.
    stored = {m["raw_zone_text"] for m in created["payload"]["mappings"]}
    assert stored == {raw_label(c, "p201") for c in P703_ZONE_CODES}
    assert zone_rows(admin_conn, "p201") == [], "proposing writes no zone map"


def test_column_and_alias_model_still_require_a_load_id(engineer):
    for kind, payload in (
        ("COLUMN", {"raw_header": "x", "logical_field": "plant"}),
        ("ALIAS_MODEL", {"raw_value": "x", "model_code": "U704"}),
    ):
        response = engineer.post(
            "/api/v1/mappings/proposals", json={"kind": kind, "payload": payload}
        )
        assert response.status_code == 422, (kind, response.text)


def test_a_non_p703_model_is_not_this_phase(engineer):
    """U704's catalogue is 31 zones; a P703 32-set is not that catalogue."""
    response = post_zone(engineer, zone_body(tag="u704", model="U704"))
    assert response.status_code == 422, response.text
    message = response.json()["message"].lower()
    assert "not positions on" in message or "u704 has 31" in message


def test_j73_cannot_receive_a_p703_zone_set_via_alias(engineer):
    """Finish-batch H7: leftover models are not spelling aliases onto P703 zones."""
    response = post_zone(engineer, zone_body(tag="j73", model="J73 DBL"))
    assert response.status_code == 422, response.text
    assert "not positions on" in response.json()["message"].lower()


def test_cx743_complete_catalogue_is_a_valid_zone_set(engineer, admin, admin_conn):
    from app.domain.fvl_leftover_identity import CX743_PANELS

    codes = [raw for _pos, raw in CX743_PANELS]
    response = post_zone(engineer, zone_body(tag="cx743", model="CX743", codes=codes))
    assert response.status_code == 201, response.text
    approved = approve(admin, response.json()["id"])
    assert approved.status_code == 200, approved.text
    assert len(zone_rows(admin_conn, "cx743")) == 32


@pytest.mark.parametrize(
    "codes, why",
    [
        (P703_ZONE_CODES[:31], "31 rows"),
        (P703_ZONE_CODES + ["RRHOOD"], "33 rows"),
        (
            [c for c in P703_ZONE_CODES if c != "LTTAILGATE"] + ["RRHOOD"],
            "32 rows, LTTAILGATE omitted and a hood duplicated",
        ),
    ],
)
def test_an_incomplete_or_padded_set_is_422(engineer, admin_conn, codes, why):
    tag = f"inc{len(codes)}{uuid.uuid4().hex[:4]}"
    body = zone_body(tag=tag, codes=codes)
    # A duplicated zone_code would also collide on raw label; make the raw
    # labels unique so the refusal is about the *zone* set, not the text.
    for i, row in enumerate(body["payload"]["mappings"]):
        row["raw_zone_text"] = f"{row['raw_zone_text']}-{i}"
    response = post_zone(engineer, body)
    assert response.status_code == 422, (why, response.text)
    assert zone_rows(admin_conn, tag) == []


def test_a_duplicated_raw_label_is_422(engineer):
    body = zone_body(tag="duplabel")
    body["payload"]["mappings"][1]["raw_zone_text"] = body["payload"]["mappings"][0][
        "raw_zone_text"
    ].lower()  # same once normalised
    response = post_zone(engineer, body)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "over",
    [
        {"proof_hash": "AB" * 32},        # upper case
        {"proof_hash": "ab" * 31},        # short
        {"proof_hash": "zz" * 32},        # not hex
        {"named_owner": "   "},
        {"method": "   "},
        {"note": "   "},
        {"proof_document": "   "},
    ],
)
def test_blank_proof_fields_are_422(engineer, over):
    response = post_zone(engineer, zone_body(tag="blank", **over))
    assert response.status_code == 422, (over, response.text)


def test_an_unknown_plant_is_422(engineer):
    response = post_zone(engineer, zone_body(tag="noplant", plant="XXX"))
    assert response.status_code == 422, response.text


def test_a_load_id_at_another_plant_is_422(engineer, cleanup):
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))  # AAT
    response = post_zone(engineer, zone_body(tag="mismatch", plant="FVL", load_id=load_id))
    assert response.status_code == 422, response.text
    assert "plant" in response.json()["message"].lower()


def test_the_other_reserved_kinds_stay_501(engineer, cleanup):
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    # T41 CHANGE: ALIAS_CHECKZONE is implemented (one row, Engineer, D-31).
    for kind in ("ALIAS_PLANT", "ALIAS_PAINTLINE"):
        response = propose(engineer, kind, load_id, {"anything": True})
        assert response.status_code == 501, (kind, response.text)


# =====================================================================
# 2. approve: RBAC, 32 proved rows, no replay without a batch
# =====================================================================
def test_an_engineer_cannot_approve_a_zone_set(engineer):
    created = post_zone(engineer, zone_body(tag="rbac")).json()
    assert approve(engineer, created["id"]).status_code == 403


def test_admin_approve_writes_32_proved_rows_and_flips_nothing(
    engineer, admin, admin_conn, fvl_state
):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ref_template_profile WHERE fixture_verified")
        verified_before = cur.fetchone()[0]

    created = post_zone(engineer, zone_body(tag="ok")).json()
    response = approve(admin, created["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["replay"] is None, "no load_id, nothing to replay"
    assert body["applied_to"] == "ref_plant_zone_map"
    assert body["proposal"]["status"] == "APPROVED"

    rows = zone_rows(admin_conn, "ok")
    assert len(rows) == 32
    assert {r["zone_code"] for r in rows} == set(P703_ZONE_CODES)
    for row in rows:
        assert row["plant_code"] == "FVL"
        assert row["model_code"] == "P703 DBL RANGER"
        assert row["confidence"] == "APPROVED"
        assert row["proof_hash"] == PROOF
        assert row["verified_by"] == OWNER, "the named owner, typed"
        assert row["approved_by"] and row["approved_by"] != OWNER, (
            "approved_by is the Admin who recorded it, not the verifier"
        )
        assert row["proposal_method"].startswith("owner-signed")
        assert row["raw_zone_text"] == row["raw_zone_text"].strip().casefold()

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ref_template_profile WHERE fixture_verified")
        assert cur.fetchone()[0] == verified_before, "approve never verifies a layout (M6)"
        cur.execute(
            "SELECT after FROM audit_event WHERE action = 'mapping.approve' "
            "AND entity_id = %s",
            (created["id"],),
        )
        after = cur.fetchone()[0]
    assert after["plant_code"] == "FVL"
    assert after["model_code"] == "P703 DBL RANGER"
    assert after["mapping_count"] == 32
    assert after["proof_hash"] == PROOF
    assert after["named_owner"] == OWNER
    assert after["load_id"] is None


def test_approving_twice_is_409(engineer, admin):
    created = post_zone(engineer, zone_body(tag="twice")).json()
    assert approve(admin, created["id"]).status_code == 200
    assert approve(admin, created["id"]).status_code == 409


# =====================================================================
# 3. atomicity: conflicts roll back the whole set
# =====================================================================
def test_a_conflicting_zone_code_is_409_and_nothing_is_written(
    engineer, admin, admin_conn
):
    # An existing row maps the RRHOOD label to RFHOOD. The set says RRHOOD.
    legacy = owner_insert(admin_conn, "conflict", "RRHOOD", "RFHOOD")
    created = post_zone(engineer, zone_body(tag="conflict")).json()
    response = approve(admin, created["id"])
    assert response.status_code == 409, response.text

    rows = zone_rows(admin_conn, "conflict")
    assert len(rows) == 1, "none of the other 31 rows was written"
    assert rows[0]["map_id"] == legacy
    assert rows[0]["zone_code"] == "RFHOOD", "zone_code is never updated"
    assert rows[0]["proof_hash"] is None
    assert proposal_status(admin_conn, created["id"]) == "PROPOSED"


def test_a_different_existing_proof_is_409(engineer, admin, admin_conn):
    owner_insert(
        admin_conn, "proof", "RRHOOD", "RRHOOD",
        proof_hash=OTHER_PROOF, verified_by="someone else",
    )
    created = post_zone(engineer, zone_body(tag="proof")).json()
    response = approve(admin, created["id"])
    assert response.status_code == 409, response.text
    assert len(zone_rows(admin_conn, "proof")) == 1
    assert proposal_status(admin_conn, created["id"]) == "PROPOSED"


def test_an_exact_legacy_row_is_certified_in_place(engineer, admin, admin_conn):
    """Same label, same zone, no proof: certify -- fill proof only."""
    legacy = owner_insert(admin_conn, "certify", "LTTAILGATE", "LTTAILGATE")
    created = post_zone(engineer, zone_body(tag="certify")).json()
    response = approve(admin, created["id"])
    assert response.status_code == 200, response.text

    rows = {r["zone_code"]: r for r in zone_rows(admin_conn, "certify")}
    assert len(rows) == 32
    certified = rows["LTTAILGATE"]
    assert certified["map_id"] == legacy, "the existing row, not a new one"
    assert certified["proof_hash"] == PROOF
    assert certified["verified_by"] == OWNER
    assert certified["approved_by"] == "legacy admin", "an earlier approval stays"


def test_an_unapproved_exact_row_gets_the_admin_on_certify(engineer, admin, admin_conn):
    owner_insert(
        admin_conn, "proposed", "LTTAILGATE", "LTTAILGATE",
        confidence="PROPOSED", approved_by=None,
    )
    created = post_zone(engineer, zone_body(tag="proposed")).json()
    assert approve(admin, created["id"]).status_code == 200
    row = {r["zone_code"]: r for r in zone_rows(admin_conn, "proposed")}["LTTAILGATE"]
    assert row["confidence"] == "APPROVED"
    assert row["approved_by"] and row["approved_by"] != OWNER


# =====================================================================
# 4. a set with a batch replays it through the one ingest service
# =====================================================================
def test_a_set_with_a_load_id_replays_that_batch(engineer, admin, cleanup, admin_conn):
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))  # AAT
    created = post_zone(engineer, zone_body(tag="replay", plant="AAT", load_id=load_id))
    assert created.status_code == 201, created.text
    response = approve(admin, created.json()["id"])
    assert response.status_code == 200, response.text
    replay = response.json()["replay"]
    assert replay is not None and replay["load_id"] == load_id
    assert len(zone_rows(admin_conn, "replay")) == 32


# =====================================================================
# 5. the loader reads proved rows only  (S15)
# =====================================================================
def test_the_loader_ignores_approved_rows_without_proof(admin_conn, app_database_url):
    unproved = raw_label("RRHOOD", "unproved")
    proved = raw_label("RFHOOD", "proved")
    owner_insert(admin_conn, "unproved", "RRHOOD", "RRHOOD")
    owner_insert(
        admin_conn, "proved", "RFHOOD", "RFHOOD",
        proof_hash=PROOF, verified_by=OWNER,
    )
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as conn:
            ref = reference_repo.load_reference_data(conn)
    finally:
        engine.dispose()
    assert ("FVL", "P703 DBL RANGER", unproved) not in ref.plant_zone_map
    assert ref.plant_zone_map[("FVL", "P703 DBL RANGER", proved)] == "RFHOOD"


# =====================================================================
# 6. grants and structure
# =====================================================================
def test_app_rw_may_update_proof_columns_and_not_zone_code(admin_conn, app_role):
    with admin_conn.cursor() as cur:
        for column in (
            "proof_hash", "proof_document", "verified_by", "proposal_method",
            "raw_position", "confidence", "approved_by", "approved_at", "note",
        ):
            cur.execute(
                "SELECT has_column_privilege(%s, 'ref_plant_zone_map', %s, 'UPDATE')",
                (app_role, column),
            )
            assert cur.fetchone()[0], column
        for column in ("zone_code", "raw_zone_text", "plant_code", "model_code"):
            cur.execute(
                "SELECT has_column_privilege(%s, 'ref_plant_zone_map', %s, 'UPDATE')",
                (app_role, column),
            )
            assert not cur.fetchone()[0], f"{column} must stay frozen"
        cur.execute(
            "SELECT has_table_privilege(%s, 'ref_plant_zone_map', 'DELETE')",
            (app_role,),
        )
        assert not cur.fetchone()[0], "no DELETE on zone maps"


def test_revision_0010_seeds_no_zone_map():
    source = (
        BACKEND_ROOT / "migrations" / "versions" / "0010_t29_zone_map_proof_grants.py"
    ).read_text(encoding="utf-8")
    assert "INSERT INTO ref_plant_zone_map" not in source
    assert "is_active" not in source, "T29 flips no plant"
    for forbidden in ("ON wavescan", "ON load_batch", "GRANT DELETE", "DELETE FROM"):
        assert forbidden not in source, forbidden


def test_no_sap_or_fvl_approved_map_exists_outside_this_suite(admin_conn):
    """T76 CHANGE: revision 0013 seeded 64 owner-signed FVL leftover maps
    (CX743 / V363, named verifier and proof hash), so "none" is no longer the
    rule. The rule S15 states, and `reference.load_reference_data` reads, is
    that an APPROVED SAP/FVL map is live only with a proof hash **and** a
    named verifier, or as a T41 Engineer alias. None may be approved without.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT map_id, plant_code, model_code FROM ref_plant_zone_map "
            "WHERE plant_code IN ('SAP','FVL') AND confidence = 'APPROVED' "
            "AND raw_zone_text NOT LIKE 't29-%%' "
            "AND NOT ((proof_hash IS NOT NULL AND verified_by IS NOT NULL) "
            "         OR proposal_method = 'ENGINEER_ALIAS')"
        )
        assert cur.fetchall() == []


def test_the_mapping_service_still_never_reads_similarity():
    from tests.test_t26_semantic_clean_layer import _statements

    for line in _statements(BACKEND_ROOT / "app" / "services" / "mapping.py"):
        assert "if similarity" not in line, line
        assert "similarity >" not in line and "similarity <" not in line, line
        assert "fixture_verified" not in line, f"approve never verifies a layout: {line}"
        assert "is_active" not in line, f"approve never onboards a plant: {line}"


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
    forget_proposals(admin_conn, before, [f"t29-{_RUN}-"], 'T29 zone sets')
