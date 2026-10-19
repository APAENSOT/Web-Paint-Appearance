"""T08 — mapping proposals, Admin approval, and replay from stored bytes.

The thing under test is a sequence, not an endpoint: an unknown template
arrives, an Engineer says what a header means, an Admin agrees, the batch is
re-derived from the bytes already on disk, and **only then** may somebody
commit. `AGENTS.md` rule 6 is the whole spec — "Never guess plant, model,
colour, zone, or column mapping. Propose -> Admin approve -> replay."

Three properties get the most assertions, because each is a way the sequence
could quietly stop being a sequence:

* **Proposing applies nothing.** A 201 from the propose route must leave the
  alias tables, the batch, and `wavescan` exactly as they were.
* **Replay writes no measurement.** It ends at `PENDING_REVIEW`. Every test
  that replays checks the fact count on the way through, not just at the end.
* **Nothing is deleted that is evidence.** `app_rw` gains no DELETE, and the
  one function that does delete refuses a batch with facts — asserted here
  against the database, as `app_rw`, not against the Python that calls it.

These tests need the live database for the same reason T01's do: the
guarantee is partly a set of PostgreSQL privileges, and a mock cannot fail to
have a privilege.
"""

from __future__ import annotations

from tests.conftest import delete_rows_created_since, row_keys
import io
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from openpyxl import Workbook

from tests.test_t04_ingest import (
    BASE_ROW,
    HEADERS,
    ingest,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)

# Imported for their side effect: a fixture is in scope where its function is
# in the module namespace, so these are T04's fixtures, not copies of them.
# T08 tests the same running system through the same clients -- a second set
# of app fixtures would be a second set of workers racing the first for jobs.
from tests.test_t04_ingest import (  # noqa: F401
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)

pytestmark = pytest.mark.ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

#: A header spelling no seeded alias knows. `ref_column_alias` seeds
#: "checkzone", "check zone" and "zone"; this is none of them, and it
#: normalises (lower / trim / '_' -> ' ') to something equally unknown.
#:
#: The suffix is fresh every run, and that is not decoration. Approving an
#: alias is permanent as far as the application is concerned -- T08 grants
#: INSERT and no DELETE -- so a fixed spelling would make this suite depend
#: on whether something else had already approved it. The local harness
#: approves exactly this kind of alias. A run-scoped header makes the suite
#: answerable only for its own state.
_RUN = uuid.uuid4().hex[:8]
UNKNOWN_HEADER = f"Check_Zone Code {_RUN}"
NORMALISED_HEADER = f"check zone code {_RUN}"

#: Kinds the data model declares and nothing implements yet.
#: T29 CHANGE: `ZONE` left this list -- it is the atomic 32-row set of
#: docs/tasks/T29-atomic-zone-sets.md, tested in test_t29_zone_sets.py.
#: Finish-batch CHANGE: `ALIAS_COLOR` left this list -- identity alias
#: (S12), not colour-family / D2. Family payloads stay refused as extra keys.
#: T41 CHANGE: `ALIAS_CHECKZONE` left this list (one panel spelling onto an
#: existing zone, D-31), tested in test_t41_alias_checkzone.py.
UNIMPLEMENTED_KINDS = [
    "ALIAS_PLANT", "ALIAS_PAINTLINE",
]


# =====================================================================
# fixtures and helpers
# =====================================================================
@pytest.fixture(scope="module")
def admin(ingest_apps):
    return ingest_apps(auth_dev_bypass_roles_raw="admin")


@pytest.fixture()
def alias_cleanup(admin_conn):
    """Remove alias rows a test approved.

    The application cannot: T08 grants INSERT and deliberately no DELETE, so
    an approved alias is permanent as far as `app_rw` is concerned. That is
    the property being protected, which is exactly why the cleanup has to run
    as the owner on a throwaway database.
    """
    # T76 CHANGE: only rows created during the test. `(none)` and other fixed
    # spellings could be an owner's alias; an existing row is never removed.
    column_before = row_keys(admin_conn, "ref_column_alias", "id")
    model_before = row_keys(admin_conn, "ref_model_alias", "alias_id")
    headers: list[str] = []
    models: list[str] = []
    yield headers, models
    if headers:
        delete_rows_created_since(
            admin_conn, "ref_column_alias", "id", column_before,
            "raw_header = ANY(%s)", (headers,),
        )
    if models:
        delete_rows_created_since(
            admin_conn, "ref_model_alias", "alias_id", model_before,
            "raw_value = ANY(%s)", (models,),
        )


def workbook_with_unknown_header(rows: list[dict], header: str = UNKNOWN_HEADER) -> bytes:
    """The standard sheet with `Checkzone` renamed to something unmapped.

    Everything else resolves, so the batch fails on exactly one missing
    required field — which makes one approved alias the whole difference
    between REJECTED_TEMPLATE and a parseable sheet.
    """
    headers = [header if h == "Checkzone" else h for h in HEADERS]
    wb = Workbook()
    ws = wb.active
    ws.title = "PasteData"
    ws.append(headers)
    for row in rows:
        merged = {**BASE_ROW, **row}
        ws.append([merged[h] for h in HEADERS])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def count(admin_conn, table: str, load_id: int) -> int:
    with admin_conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE load_id = %s", (load_id,))
        return cur.fetchone()[0]


def alias_exists(admin_conn, table: str, column: str, value: str) -> bool:
    with admin_conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE {column} = %s", (value,))
        return cur.fetchone() is not None


def propose(client, kind: str, load_id: int, payload: dict, **extra):
    body = {"kind": kind, "load_id": load_id, "payload": payload, **extra}
    return client.post("/api/v1/mappings/proposals", json=body)


def approve(client, proposal_id: str):
    return client.post(f"/api/v1/mappings/proposals/{proposal_id}/approve")


def rejected_template_batch(engineer, cleanup, rows: list[dict]) -> int:
    """Upload a sheet with one unmapped required header. Returns its load_id."""
    response = upload(
        engineer,
        f"t08-{uuid.uuid4().hex[:8]}.xlsx",
        workbook_with_unknown_header(rows),
    )
    assert response.status_code == 202, response.text
    entry = response.json()["batches"][0]
    cleanup.append(entry["load_id"])
    assert entry["status"] == "REJECTED_TEMPLATE", entry
    return entry["load_id"]


# =====================================================================
# 1. RBAC — 03-SECURITY.md section 5
# =====================================================================
def test_a_viewer_may_read_proposals_but_propose_nothing(viewer):
    """"Propose mapping / alias: no" for a Viewer; reading is every role's."""
    assert viewer.get("/api/v1/mappings/proposals").status_code == 200
    assert propose(viewer, "COLUMN", 1, {"raw_header": "x", "logical_field": "plant"}).status_code == 403
    assert approve(viewer, str(uuid.uuid4())).status_code == 403


def test_an_engineer_proposes_and_cannot_approve(engineer, cleanup, admin_conn):
    """The split the matrix draws: "Approve mapping / alias: Engineer no"."""
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    created = propose(
        engineer, "COLUMN", load_id,
        {"raw_header": UNKNOWN_HEADER, "logical_field": "checkzone"},
    )
    assert created.status_code == 201, created.text
    assert approve(engineer, created.json()["id"]).status_code == 403
    assert not alias_exists(admin_conn, "ref_column_alias", "raw_header", NORMALISED_HEADER)


def test_an_admin_outranks_an_engineer_on_propose(admin, cleanup, engineer):
    """ROLE_RANK is monotone, so the Admin can do the Engineer's job too."""
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    response = propose(
        admin, "COLUMN", load_id,
        {"raw_header": f"admin col {uuid.uuid4().hex[:6]}", "logical_field": "paintline"},
    )
    assert response.status_code == 201, response.text


# =====================================================================
# 2. Proposing applies nothing
# =====================================================================
def test_proposing_changes_no_alias_no_batch_and_no_measurement(
    engineer, cleanup, admin_conn
):
    """`02-PIPELINE.md` §4: "never auto-apply". The similarity is deliberately
    high, because a threshold is the one thing that could be tempted to."""
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(3))
    before = engineer.get(f"/api/v1/batches/{load_id}").json()["batch"]

    created = propose(
        engineer, "COLUMN", load_id,
        {"raw_header": UNKNOWN_HEADER, "logical_field": "checkzone",
         "note": "same column, different spelling"},
        similarity=0.99,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "PROPOSED"
    assert body["decided_by"] is None and body["decided_at"] is None
    assert body["similarity"] == "0.99"

    assert not alias_exists(admin_conn, "ref_column_alias", "raw_header", NORMALISED_HEADER)
    after = engineer.get(f"/api/v1/batches/{load_id}").json()["batch"]
    assert after["status"] == before["status"] == "REJECTED_TEMPLATE"
    assert count(admin_conn, "wavescan", load_id) == 0
    assert count(admin_conn, "stg_raw", load_id) == 0


def test_the_propose_path_cannot_reach_the_apply_path(admin_conn):
    """The structural half of the test above.

    `services/mapping.py` keeps proposing and applying in two functions with
    no call between them, so auto-applying would have to be added on purpose
    rather than slipped in. This asserts that shape, and that nothing in the
    module branches on the advisory score.
    """
    source = (REPO_ROOT / "backend/app/services/mapping.py").read_text(encoding="utf-8")
    propose_body = re.search(
        r"\n    def propose\(.*?\n    # -+\n    def _apply_identity\(", source, re.S
    )
    assert propose_body, "propose() no longer has the shape this test reads"
    body = propose_body.group(0)
    # COLUMN / ZONE still do not write aliases inside propose().
    for forbidden in ("insert_column_alias", "insert_model_alias",
                      "insert_color_alias", "replay_batch", "decide("):
        assert forbidden not in body, f"propose() reaches {forbidden}"
    assert "_apply_identity" in body

    # Identity kinds may apply on purpose (spec A2). Apply lives in
    # _apply_identity, not in propose()'s COLUMN path.
    apply_body = re.search(
        r"\n    def _apply_identity\(.*?\n    # -+\n    def approve\(", source, re.S
    )
    assert apply_body, "_apply_identity() no longer has the shape this test reads"
    assert "replay_batch" in apply_body.group(0)
    assert "insert_color_alias" not in apply_body.group(0)

    # Carried and stored; never compared. A threshold here is the defect
    # `02-PIPELINE.md` §4 names.
    for line in source.splitlines():
        if "similarity" in line and re.search(r"(if|elif|while|assert).*similarity", line):
            raise AssertionError(f"similarity is branched on: {line.strip()}")


# =====================================================================
# 3. Kinds T08 does not implement stay reserved
# =====================================================================
@pytest.mark.parametrize("kind", UNIMPLEMENTED_KINDS)
def test_an_unimplemented_kind_is_501_for_the_right_role(engineer, cleanup, kind):
    """Same reserved pattern as the routes: the role is sufficient, the
    behaviour is not built. (ZONE was here until T29 made it the
    owner-proved atomic 32-row set; it still does not close D5.
    ALIAS_COLOR identity left this list in the finish-batch slice; colour
    family / D2 is still not a mapping kind.)"""
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    response = propose(engineer, kind, load_id, {"anything": "at all"})
    assert response.status_code == 501, response.text
    assert "reserved" in response.json()["message"]


@pytest.mark.parametrize("kind", UNIMPLEMENTED_KINDS)
def test_an_unimplemented_kind_is_403_for_a_viewer(viewer, kind):
    """Role first, then capability: a Viewer must not learn which kinds exist
    by being told which are unimplemented."""
    assert propose(viewer, kind, 1, {}).status_code == 403


# =====================================================================
# 4. The payload is validated, not trusted
# =====================================================================
def test_a_logical_field_the_reader_does_not_have_is_refused(engineer, cleanup):
    """`logical_field` is the reader's own STAGED_FIELDS, imported. A free
    string would let an approval write an alias nothing ever reads."""
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    response = propose(
        engineer, "COLUMN", load_id,
        {"raw_header": "something", "logical_field": "grade"},
    )
    assert response.status_code == 422, response.text


def test_a_model_code_that_does_not_exist_is_refused(engineer, cleanup):
    """Approving a mapping never creates a model (`AGENTS.md` rule 6). The
    message names the models that do exist, so the Engineer can fix it."""
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    response = propose(
        engineer, "ALIAS_MODEL", load_id,
        {"raw_value": "P703 RAP", "model_code": "NOT_A_MODEL"},
    )
    assert response.status_code == 422, response.text
    assert "U704" in response.json()["message"]


def test_an_unknown_payload_key_is_refused(engineer, cleanup):
    """`03-SECURITY.md` §7 forbids extra fields. For a mapping proposal it is
    the difference between approving what you meant and approving what
    parsed."""
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    response = propose(
        engineer, "COLUMN", load_id,
        {"raw_header": "x", "logical_field": "plant", "apply_now": True},
    )
    assert response.status_code == 422, response.text


def test_a_proposal_against_a_batch_that_does_not_exist_is_refused(engineer):
    """A proposal with nothing to replay is a decision that can never land."""
    assert propose(
        engineer, "COLUMN", 999_999_999,
        {"raw_header": "x", "logical_field": "plant"},
    ).status_code == 422


def test_the_raw_header_is_stored_normalised(engineer, cleanup):
    """`01-DATA-MODEL.md` §6.3: lower, trim, '_' -> ' '. Otherwise
    'Check_Zone' and 'check zone' would be two aliases for one column.

    Its own spelling, not the module's: this test is about the three
    transformations, so the input has to exercise all three regardless of
    what the rest of the suite happens to be using.
    """
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    created = propose(
        engineer, "COLUMN", load_id,
        {"raw_header": "  Panel_Group LABEL  ", "logical_field": "checkzone"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["payload"]["raw_header"] == "panel group label"


# =====================================================================
# 5. The round trip: COLUMN
# =====================================================================
def test_an_unknown_template_becomes_loadable_only_after_approval_and_replay(
    engineer, admin, cleanup, alias_cleanup, admin_conn
):
    """The task in one test.

    Upload a sheet whose checkzone column is spelled in a way no alias knows;
    watch it refuse to parse; propose the mapping; approve it; watch the
    **stored bytes** be re-read into a balanced PENDING_REVIEW batch; confirm
    `wavescan` is still empty at that point; then commit as an Engineer and
    watch the measurements appear.
    """
    headers, _ = alias_cleanup
    headers.append(NORMALISED_HEADER)
    rows = unique_rows(4)
    load_id = rejected_template_batch(engineer, cleanup, rows)

    # T04 already left a proposal describing what is missing.
    auto = engineer.get("/api/v1/mappings/proposals", params={"load_id": load_id}).json()
    assert auto["page"]["total"] == 1
    diagnostic = auto["items"][0]
    assert diagnostic["kind"] == "COLUMN" and diagnostic["status"] == "PROPOSED"
    assert diagnostic["payload"]["missing_required"] == ["checkzone"]
    assert NORMALISED_HEADER in diagnostic["payload"]["unrecognised_headers"]

    # That diagnostic row is a header diff, not a mapping. Approving it must
    # not be mistaken for approving a decision nobody made.
    refused = approve(admin, diagnostic["id"])
    assert refused.status_code == 422, refused.text

    created = propose(
        engineer, "COLUMN", load_id,
        {"raw_header": UNKNOWN_HEADER, "logical_field": "checkzone"},
        similarity=0.91,
    )
    assert created.status_code == 201, created.text
    proposal_id = created.json()["id"]

    assert count(admin_conn, "wavescan", load_id) == 0

    approved = approve(admin, proposal_id)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["proposal"]["status"] == "APPROVED"
    assert body["proposal"]["decided_by"]
    assert body["applied_to"] == "ref_column_alias"
    assert body["replay"]["previous_status"] == "REJECTED_TEMPLATE"
    assert body["replay"]["status"] == "RUNNING"

    review = wait_for(engineer, load_id)
    assert review["batch"]["status"] == "PENDING_REVIEW", review
    assert review["batch"]["counts"]["rows_loaded"] == len(rows)
    assert review["batch"]["counts"]["balanced"] is True
    assert review["committable"] is True

    # The property the whole task turns on: replay produced dispositions,
    # not facts.
    assert count(admin_conn, "wavescan", load_id) == 0
    assert count(admin_conn, "stg_raw", load_id) == len(rows)

    committed = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["measurements_inserted"] == len(rows)
    assert count(admin_conn, "wavescan", load_id) == len(rows)


def test_approval_is_audited_in_the_same_transaction(
    engineer, admin, cleanup, alias_cleanup, admin_conn
):
    """`AGENTS.md` §2: the audit row and the change commit together."""
    headers, _ = alias_cleanup
    header = f"audited col {uuid.uuid4().hex[:6]}"
    headers.append(header)
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    created = propose(engineer, "COLUMN", load_id,
                      {"raw_header": header, "logical_field": "paintline"})
    proposal_id = created.json()["id"]
    assert approve(admin, proposal_id).status_code == 200

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT action, actor_user_id IS NOT NULL, after "
            "FROM audit_event WHERE entity_type = 'proposed_mapping' "
            "AND entity_id = %s ORDER BY id",
            (proposal_id,),
        )
        events = cur.fetchall()
        cur.execute(
            "SELECT action FROM audit_event WHERE entity_type = 'load_batch' "
            "AND entity_id = %s ORDER BY id",
            (str(load_id),),
        )
        batch_actions = [r[0] for r in cur.fetchall()]

    assert [e[0] for e in events] == ["mapping.propose", "mapping.approve"]
    assert all(e[1] for e in events), "every mapping decision names a person"
    assert events[0][2]["applied"] is False
    assert events[1][2]["applied_to"] == "ref_column_alias"
    assert "batch.replay" in batch_actions


# =====================================================================
# 6. The round trip: ALIAS_MODEL
# =====================================================================
def test_an_unrecognised_model_spelling_becomes_loadable_after_an_approved_alias(
    engineer, admin, cleanup, alias_cleanup, admin_conn
):
    """The ALIAS_MODEL round trip, on the disposition that an alias can fix.

    A model spelling no alias knows is a **reject**, `UNKNOWN_MODEL`, whose
    message already says "Add a row to ref_model_alias". T08 is how that row
    gets added without anybody guessing: the Engineer names an existing
    model, the Admin agrees, the bytes are re-read, and the rejected row
    joins `rows_loaded`.

    It does **not** become a measurement. The batch is still PENDING_REVIEW
    when this test ends.
    """
    _, models = alias_cleanup
    raw_model = f"P703 RAP {uuid.uuid4().hex[:6]}"
    models.append(raw_model)

    rows = unique_rows(3)
    rows[0]["Model"] = raw_model
    review = ingest(engineer, cleanup, "t08-alias-model.xlsx", make_workbook(rows))
    load_id = review["batch"]["load_id"]
    assert review["batch"]["counts"]["rows_rejected"] == 1
    assert review["batch"]["counts"]["rows_loaded"] == 2
    assert review["reject_reasons"] == {"UNKNOWN_MODEL": 1}

    created = propose(
        engineer, "ALIAS_MODEL", load_id,
        {"raw_value": raw_model, "model_code": "U704",
         "suggested_model": "U704", "note": "same truck, plant spelling"},
        similarity=0.88,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "APPROVED"
    already = approve(admin, created.json()["id"])
    assert already.status_code == 409, already.text

    replayed = wait_for(engineer, load_id)
    assert replayed["batch"]["status"] == "PENDING_REVIEW"
    assert replayed["batch"]["counts"]["rows_rejected"] == 0
    assert replayed["batch"]["counts"]["rows_loaded"] == 3
    assert replayed["batch"]["counts"]["balanced"] is True
    assert replayed["reject_reasons"] == {}

    # Replay never commits.
    assert count(admin_conn, "wavescan", load_id) == 0


def test_a_placeholder_model_stays_quarantined_because_no_alias_can_name_a_truck(
    engineer, admin, cleanup, alias_cleanup, admin_conn
):
    """The disposition T08's brief asks to have stated exactly.

    A row whose Model cell says `(none)` goes to `unidentified_model`, and an
    approved `ALIAS_MODEL` does **not** rescue it. `domain/cleaner.py` checks
    its placeholder set (`(none)`, `n/a`, `-`, …) *before* it consults
    `ref_model_alias`, so the alias is written and then never reached.

    That ordering is correct and T08 did not change it. `(none)` does not
    name a truck; it says the cell was left empty. An alias is a statement
    about a **spelling** and applies to every future file, so
    `(none) -> U704` would quietly assign every blank-model row in every
    plant to one model — the guess at scale that `AGENTS.md` rule 6 exists to
    prevent. Resolving a quarantined row needs a decision about *that row*,
    which is a different mechanism and not in this task.

    Recorded in docs/reports/T08-MAPPING.md rather than worked around.
    """
    _, models = alias_cleanup
    models.append("(none)")

    rows = unique_rows(3)
    rows[0]["Model"] = "(none)"
    review = ingest(engineer, cleanup, "t08-placeholder.xlsx", make_workbook(rows))
    load_id = review["batch"]["load_id"]
    assert review["batch"]["counts"]["rows_quarantine"] == 1
    assert review["unidentified_rows"] == 1

    created = propose(engineer, "ALIAS_MODEL", load_id,
                      {"raw_value": "(none)", "model_code": "U704"})
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "APPROVED"

    replayed = wait_for(engineer, load_id)
    assert replayed["batch"]["status"] == "PENDING_REVIEW"
    assert replayed["batch"]["counts"]["rows_quarantine"] == 1, (
        "a placeholder became a named truck because of an alias"
    )
    assert replayed["batch"]["counts"]["balanced"] is True
    assert count(admin_conn, "wavescan", load_id) == 0


def test_replaying_a_parsed_batch_does_not_duplicate_its_staging(
    engineer, admin, cleanup, alias_cleanup, admin_conn
):
    """`stg_raw` has UNIQUE (load_id, source_row), so a replay that did not
    clear the first parse would collide on every row. This is the reason
    `reset_batch_staging` exists."""
    _, models = alias_cleanup
    raw_model = f"P703 RAP {uuid.uuid4().hex[:6]}"
    models.append(raw_model)

    rows = unique_rows(4)
    rows[0]["Model"] = raw_model
    review = ingest(engineer, cleanup, "t08-restage.xlsx", make_workbook(rows))
    load_id = review["batch"]["load_id"]
    assert count(admin_conn, "stg_raw", load_id) == len(rows)

    created = propose(engineer, "ALIAS_MODEL", load_id,
                      {"raw_value": raw_model, "model_code": "U704"})
    assert created.status_code == 201, created.text
    assert wait_for(engineer, load_id)["batch"]["status"] == "PENDING_REVIEW"

    assert count(admin_conn, "stg_raw", load_id) == len(rows), "staged twice"


# =====================================================================
# 7. Conflicts and refusals — nothing half-applied
# =====================================================================
def test_approving_twice_is_refused(engineer, admin, cleanup, alias_cleanup):
    headers, _ = alias_cleanup
    header = f"twice col {uuid.uuid4().hex[:6]}"
    headers.append(header)
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    created = propose(engineer, "COLUMN", load_id,
                      {"raw_header": header, "logical_field": "paintline"})
    proposal_id = created.json()["id"]

    assert approve(admin, proposal_id).status_code == 200
    second = approve(admin, proposal_id)
    assert second.status_code == 409, second.text
    assert "already APPROVED" in second.json()["message"]


def test_an_alias_that_already_exists_is_refused_and_nothing_is_written(
    engineer, admin, cleanup, admin_conn
):
    """`checkzone` is seeded. Approving a second alias for it must refuse
    rather than repoint somebody else's approved mapping — and must leave the
    proposal PROPOSED, because a decision that did not take effect is not a
    decision."""
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    created = propose(engineer, "COLUMN", load_id,
                      {"raw_header": "checkzone", "logical_field": "color"})
    proposal_id = created.json()["id"]

    response = approve(admin, proposal_id)
    assert response.status_code == 409, response.text

    with admin_conn.cursor() as cur:
        cur.execute("SELECT status, decided_by FROM proposed_mapping WHERE id = %s",
                    (proposal_id,))
        assert cur.fetchone() == ("PROPOSED", None)
        cur.execute(
            "SELECT logical_field FROM ref_column_alias WHERE raw_header = 'checkzone'"
        )
        assert cur.fetchone()[0] == "checkzone", "the seeded alias was repointed"


def test_a_committed_batch_is_never_replayed(
    engineer, admin, cleanup, alias_cleanup, admin_conn
):
    """ADR 0005. Replaying a batch that has become measurements would mean
    deleting them, and nothing in this system can. The refusal rolls the
    approval back with it, so the alias is not written either."""
    headers, _ = alias_cleanup
    header = f"committed col {uuid.uuid4().hex[:6]}"
    headers.append(header)

    review = ingest(engineer, cleanup, "t08-committed.xlsx", make_workbook(unique_rows(2)))
    load_id = review["batch"]["load_id"]
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    facts = count(admin_conn, "wavescan", load_id)
    assert facts == 2

    created = propose(engineer, "COLUMN", load_id,
                      {"raw_header": header, "logical_field": "paintline"})
    response = approve(admin, created.json()["id"])
    assert response.status_code == 409, response.text
    assert "COMMITTED" in response.json()["message"]

    assert count(admin_conn, "wavescan", load_id) == facts
    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM proposed_mapping WHERE id = %s",
                    (created.json()["id"],))
        assert cur.fetchone()[0] == "PROPOSED"
    assert not alias_exists(admin_conn, "ref_column_alias", "raw_header", header)


def test_a_replay_that_still_cannot_read_the_sheet_leaves_a_new_proposal(
    engineer, admin, cleanup, alias_cleanup, admin_conn
):
    """An Admin who approves the wrong alias gets the current header diff
    back, not a dead end. It does not loop: nothing here approves anything."""
    headers, _ = alias_cleanup
    header = f"wrong col {uuid.uuid4().hex[:6]}"
    headers.append(header)
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))

    # A real mapping, for a header this sheet does not have. Approving it is
    # legitimate and changes nothing about this batch.
    created = propose(engineer, "COLUMN", load_id,
                      {"raw_header": header, "logical_field": "paintline"})
    assert approve(admin, created.json()["id"]).status_code == 200

    after = wait_for(engineer, load_id)
    assert after["batch"]["status"] == "REJECTED_TEMPLATE"

    proposals = engineer.get(
        "/api/v1/mappings/proposals", params={"load_id": load_id}
    ).json()["items"]
    replayed = [p for p in proposals if p["payload"].get("after_replay")]
    assert len(replayed) == 1, proposals
    assert replayed[0]["status"] == "PROPOSED"
    assert replayed[0]["payload"]["missing_required"] == ["checkzone"]
    assert count(admin_conn, "wavescan", load_id) == 0


def test_approving_a_proposal_that_does_not_exist_is_404(admin):
    assert approve(admin, str(uuid.uuid4())).status_code == 404


# =====================================================================
# 8. The database's own guarantees — asserted as app_rw
# =====================================================================
def test_the_application_role_still_holds_no_delete_on_anything(app_conn):
    """T08 added INSERT on one alias table and EXECUTE on one function. It
    added no DELETE, which is the thing it was forbidden to add."""
    with app_conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, privilege_type
              FROM information_schema.role_table_grants
             WHERE grantee = current_user AND privilege_type IN ('DELETE', 'TRUNCATE')
            """
        )
        assert cur.fetchall() == []


def test_the_application_role_cannot_delete_staging_directly(app_conn, admin_conn):
    """The reset function is the only route to those rows, and it is the
    route that carries the guard."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT load_id FROM load_batch ORDER BY load_id LIMIT 1")
        load_id = cur.fetchone()[0]
    for table in ("stg_raw", "reject_log", "unidentified_model"):
        with app_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(f"DELETE FROM {table} WHERE load_id = %s", (load_id,))
        app_conn.rollback()


def test_reset_batch_staging_refuses_a_batch_that_has_facts(app_conn, admin_conn):
    """The guard that lets the function exist at all. Asserted against the
    database as `app_rw`, because the Python check above it is a courtesy and
    this one is the guarantee."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT load_id FROM load_batch WHERE status = 'COMMITTED' "
            "AND (SELECT count(*) FROM wavescan w WHERE w.load_id = load_batch.load_id) > 0 "
            "LIMIT 1"
        )
        row = cur.fetchone()
    assert row, "no committed batch to test against"

    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException) as excinfo:
            cur.execute("SELECT reset_batch_staging(%s)", (row[0],))
    app_conn.rollback()
    assert "ADR 0005" in str(excinfo.value)


def test_reset_batch_staging_refuses_a_batch_that_does_not_exist(app_conn):
    with app_conn.cursor() as cur:
        with pytest.raises(psycopg.errors.NoDataFound):
            cur.execute("SELECT reset_batch_staging(%s)", (999_999_999,))
    app_conn.rollback()


def test_reset_batch_staging_cannot_touch_facts_or_batches(admin_conn):
    """Read the function's own body. It has no statement naming `wavescan` or
    `load_batch` as a delete target, so the guard is not the only thing
    standing between it and a fact — it has no way to reach one."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT prosrc FROM pg_proc WHERE proname = 'reset_batch_staging'")
        body = cur.fetchone()[0]
    deletes = re.findall(r"DELETE\s+FROM\s+(\w+)", body, re.I)
    # T18 CHANGE: revision 0006 widened the function to the review projection
    # as well. The list is asserted exactly, not loosened, because the point
    # of the test is that it can be read at a glance and that `wavescan` and
    # `load_batch` are not on it.
    assert sorted(deletes) == [
        "reject_log", "stg_raw", "stg_review_row", "unidentified_model",
    ]
    assert not re.search(r"(UPDATE|INSERT\s+INTO)\s+\w+", body, re.I)


def test_the_reset_function_is_not_executable_by_everyone(admin_conn):
    """SECURITY DEFINER plus a pinned search_path plus a named grantee list.
    Any one of the three missing would make it a way around T01."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT prosecdef, proconfig, pg_get_userbyid(proowner), proacl::text "
            "FROM pg_proc WHERE proname = 'reset_batch_staging'"
        )
        secdef, config, owner, acl = cur.fetchone()
    assert secdef is True
    assert any(c.startswith("search_path=") for c in config)
    assert "=X/" in acl and "PUBLIC" not in acl.replace(f"{owner}=", "")


# =====================================================================
# 9. Reads
# =====================================================================
def test_proposals_list_newest_first_and_filter_by_batch(engineer, cleanup):
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    first = propose(engineer, "COLUMN", load_id,
                    {"raw_header": f"a {uuid.uuid4().hex[:6]}", "logical_field": "plant"})
    second = propose(engineer, "COLUMN", load_id,
                     {"raw_header": f"b {uuid.uuid4().hex[:6]}", "logical_field": "model"})
    assert first.status_code == second.status_code == 201

    body = engineer.get("/api/v1/mappings/proposals", params={"load_id": load_id}).json()
    ids = [p["id"] for p in body["items"]]
    assert ids[0] == second.json()["id"], "not newest first"
    assert first.json()["id"] in ids
    assert body["page"]["total"] == len(ids)
    assert all(p["load_id"] == load_id for p in body["items"])


def test_one_proposal_can_be_read_back(engineer, cleanup):
    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    created = propose(engineer, "COLUMN", load_id,
                      {"raw_header": f"c {uuid.uuid4().hex[:6]}", "logical_field": "year"})
    proposal_id = created.json()["id"]
    fetched = engineer.get(f"/api/v1/mappings/proposals/{proposal_id}")
    assert fetched.status_code == 200
    assert fetched.json() == created.json()


def test_an_unknown_proposal_is_404(engineer):
    assert engineer.get(f"/api/v1/mappings/proposals/{uuid.uuid4()}").status_code == 404


# =====================================================================
# 10. The rules T08 did not change
# =====================================================================
def test_the_domain_package_still_imports_no_framework():
    """`00-ARCHITECTURE.md` §5 rule 1. T08 added a service and a repository,
    neither of which is in `domain/`; this asserts it stayed that way."""
    for path in (REPO_ROOT / "backend/app/domain").rglob("*.py"):
        code = path.read_text(encoding="utf-8")
        for banned in ("import fastapi", "from fastapi", "import psycopg", "import sqlalchemy"):
            assert banned not in code, f"{path.name} imports {banned}"


def test_replay_uses_the_one_ingest_service():
    """`02-PIPELINE.md` §10: "Two parsers = drift". The mapping service holds
    a reference to the ingest service and calls it; it does not read a
    workbook itself."""
    source = (REPO_ROOT / "backend/app/services/mapping.py").read_text(encoding="utf-8")
    assert "self.ingest.replay_batch(" in source
    for forbidden in ("read_sheet", "describe_sheet", "load_workbook", "openpyxl"):
        assert forbidden not in source, f"mapping.py parses for itself: {forbidden}"


def test_t08_reads_no_grading_rule_and_exposes_no_grade():
    """D1 and D2 are untouched.

    T05's rule exists in `domain/grading.py` and nothing in T08 imports it,
    calls it, or ships a field derived from it. The prose in these modules
    mentions D2 by name — that is the point of the prose — so the check is on
    what the code does, not on which words appear in it.
    """
    banned_code = (
        "domain.grading", "import grading", "status_of", "statusOf",
        "pass_rate", "passRate", "ribbon", "grading_family",
    )
    for name in ("app/schemas/mappings.py", "app/services/mapping.py",
                 "app/api/v1/mappings.py", "app/repositories/mappings.py"):
        code = (REPO_ROOT / "backend" / name).read_text(encoding="utf-8")
        for banned in banned_code:
            assert banned not in code, f"{name} uses {banned}"

    # The DTOs themselves: no field a dashboard could mistake for a verdict.
    from app.schemas import mappings as dto

    for model_name in ("ProposalOut", "ApprovalResult", "ReplayOut",
                       "ColorAliasPayload"):
        fields = set(getattr(dto, model_name).model_fields)
        assert not fields & {"grade", "pass_rate", "ribbon", "verdict"}, model_name
        assert "grading_family" not in fields
