"""T18 -- template profiles and the persisted review projection.

Three claims, and none of them can be made against a mock:

* **A layout nobody approved does not get parsed.** Proven by counting
  `stg_raw` and `stg_review_row` rows in PostgreSQL after the upload, not by
  reading a return value.
* **A profile that no fixture proved does not commit.** Proven by asking the
  running application to commit and reading `wavescan` afterwards. The
  refusal has to come from the database's own shape too: `app_rw` holds no
  grant that could set `fixture_verified`, which is asserted against the
  catalog.
* **What a reviewer saw is what gets written.** Proven by moving the stored
  `review_revision` out from under a batch, as the owner, and watching the
  commit refuse.

These run through T04's fixtures, against the same application, worker and
database, because a second set would be a second worker racing the first.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.domain.reader import DOMAIN_WAVESCAN, describe_sheet
from tests.test_t04_ingest import (
    BASE_ROW,
    HEADERS,
    XLSX_MIME,
    forget_bytes,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)

# Imported for their side effect: a fixture is in scope where its function is
# in the module namespace (same reasoning as T08 and T17).
from tests.test_t04_ingest import (  # noqa: F401
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)

pytestmark = pytest.mark.ingest

#: The **exact ordered-layout hash** every AAT and FTM workbook in the
#: vault has, and the one the suite's synthetic workbook generates. Seeded
#: by revision 0006. T26 CHANGE: this is provenance now, not the selection
#: key -- a reorder of these columns moves it and still selects the same
#: profile (backend/tests/test_t26_semantic_clean_layer.py proves that).
CANONICAL = "5d0070137d0005adfd73f0f4ba2d7031c96e55c47fb7313f501a83811bf2e990"


# =====================================================================
# helpers
# =====================================================================
def alias_map(admin_conn) -> dict[str, str]:
    with admin_conn.cursor() as cur:
        cur.execute(
            # T46: the reader is handed one vocabulary. FilmThickness rows
            # (`checkzone` -> location) are not WaveScan aliases.
            "SELECT raw_header, logical_field FROM ref_column_alias "
            "WHERE is_approved AND domain = 'WAVESCAN'"
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def workbook(
    rows: list[dict],
    *,
    rename: dict[str, str] | None = None,
    drop: tuple[str, ...] = (),
    order: list[str] | None = None,
    sheet: str = "PasteData",
) -> bytes:
    """A workbook whose *layout* a test chooses, with the usual values in it.

    `make_workbook` always writes the canonical headers, which is exactly what
    a test about unknown layouts cannot use. The three knobs are the three
    ways a layout differs: a column is spelled differently (`rename`), a
    column is absent (`drop`), or the columns are in another order (`order`).

    Values are always looked up by the **canonical** field, so renaming the
    Color column still writes the colour into it -- a renamed header with an
    empty column underneath would test nothing.
    """
    rename = rename or {}
    keys = [h for h in (order or HEADERS) if h not in drop]
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append([rename.get(k, k) for k in keys])
    for row in rows:
        merged = {**BASE_ROW, **row}
        ws.append([merged.get(k) for k in keys])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def fingerprint_of(admin_conn, data: bytes, sheet: str = "PasteData") -> str:
    """The fingerprint the service will compute for these bytes.

    Read through the same `describe_sheet` the ingest path uses, with the
    same approved aliases, because a test that hardcoded a hex string would
    pass while meaning nothing.
    """
    return describe_sheet(data, sheet, alias_map(admin_conn)).fingerprint


def signature_of(admin_conn, data: bytes, sheet: str = "PasteData") -> str:
    """The semantic contract the service selects a profile by (T26).

    T26 CHANGE: the profile lookup key is `(domain, plant, this)`. The
    fingerprint above is still stored and still asserted on, as the record
    of which exact column order produced a batch.
    """
    return describe_sheet(
        data, sheet, alias_map(admin_conn)
    ).semantic_signature


def insert_profile(admin_conn, plant: str, signature: str, **over) -> int:
    """Insert a profile **as the owner**.

    Deliberately not through the application: `app_rw` has no INSERT on
    `ref_template_profile` and T18 does not give it one. A profile arrives by
    seed, migration or the owner, which is the whole of M6's guarantee.
    """
    row = {
        "version": 1, "is_active": True, "fixture_verified": False,
        "fixture_file_hash": None, "fill_missing_plant": False,
        "notes": "inserted by the T18 suite as the owner",
        # T26: the key is the semantic contract. The ordered hash rides along
        # as provenance and may be anything the caller knows about, which is
        # exactly the separation that slice introduced.
        "domain": DOMAIN_WAVESCAN,
        "fingerprint": "t18-provenance-" + uuid.uuid4().hex,
        "verified_by": None,
    }
    row.update(over)
    if row["fixture_verified"] and not row["verified_by"]:
        row["verified_by"] = "the T18 suite, as the owner"
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ref_template_profile
                (plant_code, domain, semantic_signature, template_fingerprint,
                 version, is_active, fixture_verified, fixture_file_hash,
                 fill_missing_plant, notes, verified_by, verified_at)
            VALUES (%(plant)s, %(domain)s, %(sig)s, %(fingerprint)s,
                    %(version)s, %(is_active)s,
                    %(fixture_verified)s, %(fixture_file_hash)s,
                    %(fill_missing_plant)s, %(notes)s, %(verified_by)s,
                    CASE WHEN %(fixture_verified)s THEN now() ELSE NULL END)
            RETURNING profile_id
            """,
            {"plant": plant, "sig": signature, **row},
        )
        return cur.fetchone()[0]


def drop_profile(admin_conn, profile_id: int) -> None:
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ref_template_profile WHERE profile_id = %s", (profile_id,)
        )


@pytest.fixture()
def owned_profile(admin_conn):
    """Profiles this test created, removed as the owner afterwards.

    Reference data outlives a test otherwise, and a stray active profile
    would silently change what a later test's layout means.
    """
    created: list[int] = []

    def make(plant: str, signature: str, **over) -> int:
        profile_id = insert_profile(admin_conn, plant, signature, **over)
        created.append(profile_id)
        return profile_id

    yield make
    for profile_id in reversed(created):
        with admin_conn.cursor() as cur:
            cur.execute(
                "UPDATE load_batch SET profile_id = NULL WHERE profile_id = %s",
                (profile_id,),
            )
            cur.execute(
                "UPDATE stg_review_row SET profile_id = NULL WHERE profile_id = %s",
                (profile_id,),
            )
        drop_profile(admin_conn, profile_id)


def review_rows(admin_conn, load_id: int) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT source_row, disposition, reason, canonical, raw, "
            "       normalized_fields, review_revision, template_fingerprint "
            "  FROM stg_review_row WHERE load_id = %s ORDER BY source_row",
            (load_id,),
        )
        return cur.fetchall()


def profile_snapshot(admin_conn) -> list[tuple]:
    """Every profile, as a comparable value.

    Used to assert that a route did not create, retire or verify a layout.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT profile_id, plant_code, template_fingerprint, version, "
            "       is_active, fixture_verified, fill_missing_plant "
            "  FROM ref_template_profile ORDER BY profile_id"
        )
        return cur.fetchall()


def facts(admin_conn, load_id: int) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        return cur.fetchone()[0]


def ingest_as(client: TestClient, cleanup, name: str, data: bytes, plant: str) -> dict:
    response = upload(client, name, data, expected_plant=plant)
    assert response.status_code == 202, response.text
    entry = response.json()["batches"][0]
    cleanup.append(entry["load_id"])
    if entry["status"] != "RUNNING":
        return {"batch": {"load_id": entry["load_id"], "status": entry["status"]},
                "entry": entry}
    body = wait_for(client, entry["load_id"])
    body["entry"] = entry
    return body


# =====================================================================
# 1. the canonical layout still works, and now leaves a projection
# =====================================================================
@pytest.mark.parametrize("plant", ["AAT", "FTM"])
def test_a_seeded_layout_parses_projects_and_commits(
    engineer, cleanup, admin_conn, plant
):
    """The acceptance case: nothing T04 could do got harder."""
    rows = unique_rows(3, Plant=plant)
    data = make_workbook(rows)
    forget_bytes(admin_conn, data)

    review = ingest_as(engineer, cleanup, f"t18-{plant.lower()}.xlsx", data, plant)
    batch = review["batch"]
    load_id = batch["load_id"]

    assert batch["status"] == "PENDING_REVIEW", batch
    assert batch["template_fingerprint"] == CANONICAL
    assert batch["profile_id"] is not None
    assert batch["fixture_verified"] is True
    assert batch["review_revision"], "a parsed batch must carry its projection hash"
    assert review["commit_blockers"] == []
    assert review["committable"] is True

    projection = review_rows(admin_conn, load_id)
    assert len(projection) == batch["counts"]["rows_in_file"] == 3, (
        "one projection row per source row, whatever its disposition"
    )
    assert {r[1] for r in projection} == {"LOAD"}
    assert {r[6] for r in projection} == {batch["review_revision"]}
    canonical = projection[0][3]
    assert canonical["plant"] == plant
    assert isinstance(canonical["measures"]["cf"], str), (
        "a measure is carried as text, not as a float: L12 stores measurements "
        "at full precision and JSON floats would round them"
    )
    assert Decimal(canonical["measures"]["cf"]) == Decimal(str(rows[0]["CF"]))
    assert projection[0][4]["values"]["serial_no"] == rows[0]["Serial No"], (
        "the projection keeps what the file said beside what commit would write"
    )

    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    assert facts(admin_conn, load_id) == 3


def test_every_disposition_reaches_the_projection(engineer, cleanup, admin_conn):
    """Not only the rows that would load (T18 weak point).

    One rejected colour, one unidentified model, one clean row: a reviewer
    has to be able to see all three, and the count has to balance.
    """
    rows = unique_rows(3)
    rows[0]["Color"] = "Fictional Purple"
    rows[1]["Model"] = "(none)"
    data = make_workbook(rows)
    forget_bytes(admin_conn, data)

    review = ingest_as(engineer, cleanup, "t18-dispositions.xlsx", data, "AAT")
    load_id = review["batch"]["load_id"]
    assert review["batch"]["status"] == "PENDING_REVIEW"

    projection = review_rows(admin_conn, load_id)
    assert len(projection) == 3
    by_disposition = {r[1]: r for r in projection}
    assert set(by_disposition) == {"LOAD", "REJECT", "QUARANTINE"}
    assert by_disposition["REJECT"][2] == "UNKNOWN_COLOR"
    assert by_disposition["REJECT"][3]["offending_value"] == "Fictional Purple"
    assert by_disposition["QUARANTINE"][2] == "UNIDENTIFIED_MODEL"
    assert review["review_rows"] == 3
    assert review["review_dispositions"] == {"LOAD": 1, "REJECT": 1, "QUARANTINE": 1}


def test_a_filled_plant_cell_is_named_in_the_projection(engineer, cleanup, admin_conn):
    """T17 disclosed the fill on the audit event; T18 disclosed it per row."""
    data = make_workbook([{**r, "Plant": None} for r in unique_rows(2)])
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t18-filled.xlsx", data, "AAT")
    load_id = review["batch"]["load_id"]

    projection = review_rows(admin_conn, load_id)
    assert len(projection) == 2
    for row in projection:
        assert row[3]["plant"] == "AAT"
        assert row[5] == ["plant"], "the filled field must be named, not implied"
        assert row[4]["values"].get("plant") is None, "the file said nothing"


# =====================================================================
# 2. the missing Plant column -- T17's leftover
# =====================================================================
def test_a_missing_plant_column_parses_when_the_profile_says_so(
    engineer, cleanup, admin_conn
):
    data = workbook(unique_rows(3), drop=("Plant",))
    forget_bytes(admin_conn, data)

    review = ingest_as(engineer, cleanup, "t18-no-plant-col.xlsx", data, "AAT")
    batch = review["batch"]
    load_id = batch["load_id"]

    assert batch["status"] == "PENDING_REVIEW", batch
    assert batch["fixture_verified"] is True
    assert review["committable"] is True
    assert batch["counts"] == {
        "rows_in_file": 3, "rows_loaded": 3, "rows_duplicate": 0,
        "rows_rejected": 0, "rows_quarantine": 0, "balanced": True,
    }
    assert all(r[3]["plant"] == "AAT" for r in review_rows(admin_conn, load_id))

    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT plant FROM wavescan WHERE load_id = %s", (load_id,)
        )
        assert [r[0] for r in cur.fetchall()] == ["AAT"]


def test_a_layout_with_no_profile_is_read_on_its_required_columns(
    engineer, cleanup, admin_conn
):
    """The same workbook, uploaded for a plant that has no profile for it.

    **T42 CHANGE (L-02 / L-03).** This used to be locked decision 3: no active
    profile meant REJECTED_TEMPLATE and no data row parsed. T42 reads a
    WaveScan tab whose required columns all map (plant supplied by the page)
    without a profile, so this tab is parsed and staged for review. What still
    holds: it has no profile, and nothing about its identity is guessed --
    whatever SAP does not offer is held by the cleaner, not relabelled.
    """
    data = workbook(
        unique_rows(3, **{"Serial No": f"T18-{uuid.uuid4().hex[:8]}"}),
        drop=("Plant",),
    )
    forget_bytes(admin_conn, data)

    response = upload(engineer, "t18-no-profile.xlsx", data, expected_plant="SAP")
    assert response.status_code == 202, response.text
    entry = response.json()["batches"][0]
    load_id = entry["load_id"]
    cleanup.append(load_id)
    assert entry["status"] == "RUNNING", entry

    body = wait_for(engineer, load_id)
    assert body["batch"]["status"] == "PENDING_REVIEW", body["batch"]["notes"]
    assert "UNKNOWN_TEMPLATE" not in body["commit_blockers"]
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stg_raw WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 3, "the rows are staged for review"
        cur.execute("SELECT profile_id FROM load_batch WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] is None, "no profile was invented for it"
        cur.execute(
            "SELECT count(*) FROM proposed_mapping WHERE load_id = %s "
            "   AND kind = 'COLUMN'",
            (load_id,),
        )
        assert cur.fetchone()[0] == 0, "nothing for an Admin to map"
    assert facts(admin_conn, load_id) == 0, "reviewing never commits"


def test_an_unknown_header_is_still_an_unknown_template(engineer, cleanup, admin_conn):
    """T04's case, unchanged: a missing required header never reaches a
    profile lookup, because the fingerprint it produces has no profile."""
    data = workbook(unique_rows(2), rename={"Checkzone": "Mystery"})
    forget_bytes(admin_conn, data)

    response = upload(engineer, "t18-mystery.xlsx", data, expected_plant="AAT")
    entry = response.json()["batches"][0]
    cleanup.append(entry["load_id"])
    assert entry["status"] == "REJECTED_TEMPLATE", entry

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM stg_review_row WHERE load_id = %s", (entry["load_id"],)
        )
        assert cur.fetchone()[0] == 0


# =====================================================================
# 3. an unverified profile is reviewable and not committable
# =====================================================================
@pytest.fixture()
def reordered(admin_conn):
    """A layout that is real but not seeded.

    **T26 CHANGE.** This fixture used to swap two columns, because under T18 a
    swap minted a fingerprint nobody had approved. It no longer does: a
    reorder is the same *contract* now and selects the seeded profile, which
    is the whole point of that slice. So the fixture drops a column instead --
    `B` is the one measure that is not required -- which is a genuinely
    different contract. Every remaining header still resolves, so the rows
    clean exactly as they would otherwise, and the claim these tests make is
    unchanged: a layout nobody has approved is not commit-capable just because
    its values happen to be readable.
    """
    return [h for h in HEADERS if h != "B"]


def test_an_unverified_profile_parses_but_cannot_commit(
    engineer, cleanup, admin_conn, owned_profile, reordered
):
    data = workbook(unique_rows(3), order=reordered)
    forget_bytes(admin_conn, data)
    signature = signature_of(admin_conn, data)
    assert fingerprint_of(admin_conn, data) != CANONICAL, (
        "the fixture did not actually change the layout"
    )
    assert signature != signature_of(admin_conn, workbook(unique_rows(1))), (
        "the fixture did not actually change the contract: since T26 a "
        "reorder alone selects the seeded profile"
    )
    owned_profile("AAT", signature, fixture_verified=False)

    review = ingest_as(engineer, cleanup, "t18-unverified.xlsx", data, "AAT")
    batch = review["batch"]
    load_id = batch["load_id"]

    assert batch["status"] == "PENDING_REVIEW", batch
    assert batch["counts"]["rows_loaded"] == 3, "it parses; that is the point"
    assert len(review_rows(admin_conn, load_id)) == 3, "and it is reviewable"

    assert batch["fixture_verified"] is False
    assert review["committable"] is False
    assert review["commit_blockers"] == ["UNVERIFIED_PROFILE"]

    refused = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert refused.status_code == 409, refused.text
    assert "UNVERIFIED_PROFILE" in refused.json()["message"]
    assert facts(admin_conn, load_id) == 0


def test_the_application_cannot_grant_itself_a_verified_profile(admin_conn, app_role):
    """M6 as a catalog fact rather than a code review.

    `fixture_verified` cannot be written by the application at all: there is
    no INSERT and no UPDATE on the table for the application role, so no
    route -- including the Admin approve route -- can promote a layout.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT privilege_type
              FROM information_schema.role_table_grants
             WHERE table_name = 'ref_template_profile' AND grantee = %s
             ORDER BY privilege_type
            """,
            (app_role,),
        )
        granted = {r[0] for r in cur.fetchall()}
    assert granted == {"SELECT"}, granted


def test_the_app_role_cannot_write_a_profile_directly(app_conn):
    for sql in (
        "INSERT INTO ref_template_profile (plant_code, domain, "
        "semantic_signature, template_fingerprint) "
        "VALUES ('AAT', 'WAVESCAN', 'deadbeef', 'deadbeef')",
        "UPDATE ref_template_profile SET fixture_verified = true",
        "DELETE FROM ref_template_profile",
    ):
        with app_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(sql)
        app_conn.rollback()


# =====================================================================
# 4. mapping approve does not promote a layout (M6)
# =====================================================================
def test_approving_a_header_mapping_never_verifies_a_layout(
    engineer, cleanup, admin_conn, actor_user_id
):
    """T08's flow, with M6's question asked of it.

    An Admin approves a header nobody had mapped and the batch is replayed.
    That makes the sheet *readable*, and here it also makes it committable --
    but only because the layout it now fingerprints to is the canonical AAT
    one, which a fixture proved. The approval itself writes an alias and
    nothing else: the profile table is identical before and after, so no
    layout was promoted by anyone pressing approve.

    The approve is driven through `MappingService` rather than a second HTTP
    application, because the claim is about what the service writes and a
    second app would be a second worker racing this one for the queue.
    """
    from app.services.mapping import MappingService

    profiles_before = profile_snapshot(admin_conn)

    # A spelling no alias covers, unique per run so the approved alias this
    # test writes cannot make a later run start from a different place.
    raw_header = f"mystery colour header {uuid.uuid4().hex[:8]}"
    data = workbook(unique_rows(2), rename={"Color": raw_header})
    forget_bytes(admin_conn, data)

    response = upload(engineer, "t18-approve.xlsx", data, expected_plant="AAT")
    entry = response.json()["batches"][0]
    load_id = entry["load_id"]
    cleanup.append(load_id)
    assert entry["status"] == "REJECTED_TEMPLATE", entry

    proposal = engineer.post(
        "/api/v1/mappings/proposals",
        json={
            "kind": "COLUMN",
            "load_id": load_id,
            "payload": {"raw_header": raw_header.lower(), "logical_field": "color"},
        },
    )
    assert proposal.status_code == 201, proposal.text

    service = MappingService(engineer.app.state.ingest_service)
    with engineer.app.state.database.connect() as conn:
        with conn.begin():
            service.approve(
                conn, proposal.json()["id"], actor_user_id=actor_user_id,
            )

    assert profile_snapshot(admin_conn) == profiles_before, (
        "approving a mapping created or changed a template profile"
    )

    review = wait_for(engineer, load_id)
    assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"]
    # `load_batch.template_fingerprint` is provenance, frozen at insert by
    # T01's grant, so it still records the layout the file arrived as. The
    # layout that actually parsed it is on the projection -- and it is the
    # canonical one, which is why this batch is now committable. The approval
    # did not verify anything; it made this workbook *be* a verified layout.
    assert {r[7] for r in review_rows(admin_conn, load_id)} == {CANONICAL}
    assert review["batch"]["fixture_verified"] is True
    assert review["commit_blockers"] == []
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    assert facts(admin_conn, load_id) == 2

    # Remove the alias this test approved, as the owner. It is reference
    # data: left behind, it would silently change what the *next* run's
    # unknown header means, and an alias is supposed to be a decision
    # somebody made rather than a test artefact.
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ref_column_alias WHERE raw_header = %s", (raw_header.lower(),)
        )


def test_a_replay_onto_a_verified_layout_becomes_committable(
    engineer, cleanup, admin_conn, owned_profile, reordered
):
    """The other half of M6: a replay that lands on a *verified* fingerprint
    is committable, and one that lands on an unverified fingerprint is not.

    Driven without the approve route so the claim is about the fingerprint
    and not about who pressed the button: the batch is replayed after the
    owner verifies the profile the layout selects.
    """
    data = workbook(unique_rows(2), order=reordered)
    forget_bytes(admin_conn, data)
    profile_id = owned_profile(
        "AAT", signature_of(admin_conn, data), fixture_verified=False
    )

    review = ingest_as(engineer, cleanup, "t18-replay-verify.xlsx", data, "AAT")
    load_id = review["batch"]["load_id"]
    assert review["committable"] is False

    with admin_conn.cursor() as cur:
        cur.execute(
            "UPDATE ref_template_profile SET fixture_verified = true, "
            "notes = 'verified by the T18 suite as the owner', "
            # T26: a verified row names its verifier (ck_profile_verifier_named).
            "verified_by = 'the T18 suite, as the owner', verified_at = now() "
            "WHERE profile_id = %s",
            (profile_id,),
        )

    body = engineer.get(f"/api/v1/batches/{load_id}").json()
    assert body["batch"]["fixture_verified"] is True
    assert body["commit_blockers"] == []
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    assert facts(admin_conn, load_id) == 2


# =====================================================================
# 5. the projection binds review to commit
# =====================================================================
def test_a_commit_is_refused_when_the_stored_revision_disagrees(
    engineer, cleanup, admin_conn
):
    """The hash is the guard, and it is checked against the stored bytes.

    The revision is moved out from under the batch as the owner -- standing
    in for what a changed alias would do between review and commit -- and the
    commit must refuse rather than write rows nobody reviewed.
    """
    data = make_workbook(unique_rows(2))
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t18-revision.xlsx", data, "AAT")
    load_id = review["batch"]["load_id"]
    assert review["committable"] is True

    with admin_conn.cursor() as cur:
        cur.execute(
            "UPDATE load_batch SET review_revision = %s WHERE load_id = %s",
            ("0" * 64, load_id),
        )

    refused = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert refused.status_code == 409, refused.text
    assert "projection revision" in refused.json()["message"]
    assert facts(admin_conn, load_id) == 0

    # Put it back and the same batch commits: the refusal was about the hash,
    # not about the batch being broken.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT review_revision FROM stg_review_row WHERE load_id = %s",
            (load_id,),
        )
        real = cur.fetchone()[0]
        cur.execute(
            "UPDATE load_batch SET review_revision = %s WHERE load_id = %s",
            (real, load_id),
        )
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    assert facts(admin_conn, load_id) == 2


def test_the_revision_is_the_same_for_the_same_bytes(engineer, cleanup, admin_conn):
    """Two parses of one workbook agree, or commit could never trust the
    hash. Driven by replaying the batch, which re-derives everything."""
    data = make_workbook(unique_rows(3))
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t18-stable.xlsx", data, "AAT")
    load_id = review["batch"]["load_id"]
    first = review["batch"]["review_revision"]

    service = engineer.app.state.ingest_service
    with engineer.app.state.database.connect() as conn:
        with conn.begin():
            service.replay_batch(
                conn, load_id, actor_user_id=None, reason="T18 revision stability"
            )
    again = wait_for(engineer, load_id)
    assert again["batch"]["status"] == "PENDING_REVIEW"
    assert again["batch"]["review_revision"] == first


def test_replay_clears_and_rewrites_the_projection(engineer, cleanup, admin_conn):
    """The projection is replaced, never edited (M13).

    `reset_batch_staging` is the only thing that can clear it, and `app_rw`
    cannot delete a row of it directly -- both asserted here, because "we
    only ever replace it" is a promise about code while the grant is a
    property of the database.
    """
    data = make_workbook(unique_rows(3))
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t18-replay-projection.xlsx", data, "AAT")
    load_id = review["batch"]["load_id"]
    assert len(review_rows(admin_conn, load_id)) == 3

    service = engineer.app.state.ingest_service
    with engineer.app.state.database.connect() as conn:
        with conn.begin():
            cleared = service.replay_batch(
                conn, load_id, actor_user_id=None, reason="T18 projection replay"
            )["cleared"]
    assert cleared["stg_review_row"] == 3, cleared

    again = wait_for(engineer, load_id)
    assert again["batch"]["status"] == "PENDING_REVIEW"
    assert len(review_rows(admin_conn, load_id)) == 3, "and it was rewritten"


def test_the_app_role_cannot_delete_or_edit_a_projection_row(app_conn, admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stg_review_row")
        if cur.fetchone()[0] == 0:
            pytest.skip("no projection rows to attempt this against")
    for sql in (
        "DELETE FROM stg_review_row",
        "UPDATE stg_review_row SET canonical = '{}'::jsonb",
    ):
        with app_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(sql)
        app_conn.rollback()


def test_reset_batch_staging_still_refuses_once_facts_exist(
    engineer, cleanup, admin_conn, app_conn
):
    """T08's guard, re-asserted now that the function deletes one more table.

    A committed batch's projection is evidence of what produced its
    measurements; the function must not clear it any more than it clears
    `stg_raw`.
    """
    data = make_workbook(unique_rows(2))
    forget_bytes(admin_conn, data)
    review = ingest_as(engineer, cleanup, "t18-reset-guard.xlsx", data, "AAT")
    load_id = review["batch"]["load_id"]
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200

    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException):
            cur.execute("SELECT reset_batch_staging(%s)", (load_id,))
    app_conn.rollback()
    assert len(review_rows(admin_conn, load_id)) == 2, "the projection survived"


# =====================================================================
# 6. SAP: visible, reviewable, and not committable (M7)
# =====================================================================
def test_a_blank_serial_workbook_loads_with_null_serials(engineer, cleanup, admin_conn):
    """SAP's June file, reduced to its blank serials.

    T39 CHANGE (ADR 0013 decision 2 and 8): a blank serial loads NULL at
    every plant and the sheet is the vehicle, so these rows are LOAD and
    `VEHICLE_IDENTITY_MISSING` is no longer raised. Still: no serial is
    generated, and the source row is not used as an identity.
    """
    rows = unique_rows(3, Plant="SAP", **{"Serial No": None})
    data = make_workbook(rows)
    forget_bytes(admin_conn, data)

    review = ingest_as(engineer, cleanup, "t18-sap-blank-serial.xlsx", data, "SAP")
    batch = review["batch"]
    load_id = batch["load_id"]

    assert batch["status"] == "PENDING_REVIEW", batch
    assert batch["profile_id"] is not None, "SAP's layout is known"
    assert batch["counts"]["rows_loaded"] == 3
    assert batch["counts"]["rows_rejected"] == 0
    assert "VEHICLE_IDENTITY_MISSING" not in review["commit_blockers"]

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM stg_review_row WHERE load_id = %s "
            "AND (canonical ->> 'serial_no') IS NOT NULL",
            (load_id,),
        )
        assert cur.fetchone()[0] == 0, "no serial was invented anywhere"


def test_no_verified_profile_exists_for_sap_or_fvl(admin_conn):
    """D5 is open and SAP's identity rule is undecided. A verified profile
    for either would be this task quietly answering both.

    T76 CHANGE: both are now decided -- SAP by T30 and FVL by T32, which
    closed D5 (`DEFERRED.md`). Owner-verified profiles exist for both. What
    stays true is that none of them was verified quietly: each names the
    fixture bytes it was proved on and the person who verified it (T26
    `ck_profile_verifier_named`, the T30 / T32 publish).
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT profile_id, plant_code FROM ref_template_profile "
            "WHERE fixture_verified AND plant_code IN ('SAP', 'FVL') "
            "AND (fixture_file_hash IS NULL OR verified_by IS NULL "
            "     OR btrim(verified_by) = '')"
        )
        assert cur.fetchall() == [], "a verified SAP/FVL layout names no proof"


def test_an_inactive_plant_is_still_refused_at_the_door(engineer, admin_conn):
    """T17's gate runs first: a profile lookup never happens for a plant
    that is not onboarded, because the upload never gets that far."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT plant_code FROM ref_plant WHERE NOT is_active LIMIT 1")
        row = cur.fetchone()
    if row is None:
        pytest.skip("no inactive plant in ref_plant to exercise the gate")
    inactive = row[0]

    data = make_workbook([{**r, "Plant": None} for r in unique_rows(2)])
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM load_batch")
        before = cur.fetchone()[0]

    response = upload(engineer, "t18-inactive.xlsx", data, expected_plant=inactive)

    assert response.status_code == 422, response.text
    assert "PLANT_NOT_ONBOARDED" in response.json()["message"]
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM load_batch")
        assert cur.fetchone()[0] == before


# =====================================================================
# 7. shape of the thing
# =====================================================================
def test_there_is_still_one_parser(admin_conn):
    """A profile translates *into* the existing cleaner; it does not become a
    second one. `read_sheet` is called from exactly one module."""
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    callers = [
        path.relative_to(backend).as_posix()
        for path in (backend / "app").rglob("*.py")
        if "read_sheet(" in path.read_text(encoding="utf-8")
        and path.name != "reader.py"
    ]
    assert callers == ["app/services/ingest.py"], callers


def test_a_profile_cannot_carry_executable_text(admin_conn):
    """Design section 5.1: profiles are data. The table has no column that
    could hold SQL or Python, which is a schema fact, not a review note."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'ref_template_profile' ORDER BY column_name"
        )
        columns = dict(cur.fetchall())
    # T26 adds four: the domain and semantic signature that select the
    # row, and the verifier identity a fixture_verified row must carry.
    # None of them can hold SQL or Python either.
    assert set(columns) == {
        "profile_id", "plant_code", "template_fingerprint", "version",
        "is_active", "fixture_verified", "fixture_file_hash",
        "fill_missing_plant", "notes", "created_at",
        "domain", "semantic_signature", "verified_by", "verified_at",
    }, columns


def test_only_one_profile_can_be_active_per_layout(admin_conn, owned_profile):
    """Selection has to be unambiguous, and that is enforced by the database
    rather than by an ORDER BY in the service."""
    signature = "t18-" + uuid.uuid4().hex
    owned_profile("AAT", signature, version=1)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_profile(admin_conn, "AAT", signature, version=2)
    admin_conn.rollback()
