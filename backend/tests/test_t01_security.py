"""T01 -- the application role cannot erase or rewrite evidence.

Ported from and extending ``Paint Appearance/Component/Database/sql/99_verify.sql``:
same approach (attempt the illegal operation, the database must refuse it),
moved from psql NOTICEs to pytest so CI can gate on it.

The three cases T01 adds to the demo's verify script:

  a. DELETE FROM wavescan   as the app role -> must be refused
  b. DELETE FROM load_batch as the app role -> must be refused
  c. INSERT INTO audit_event as the app role -> must succeed

Everything else in this module exists so those three cannot be satisfied
by accident (e.g. by revoking DELETE from one role while a second login
role keeps it, or by leaving UPDATE on the fact table wide open).

Authority: docs/ADR/0005-immutable-facts.md, docs/03-SECURITY.md section 2,
docs/01-DATA-MODEL.md section 8.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import errors as pgerr

from conftest import application_roles

pytestmark = pytest.mark.security

# Tables whose rows are evidence: nothing an application role does may remove them.
EVIDENCE_TABLES = (
    "wavescan",
    "load_batch",
    "stg_raw",
    "reject_log",
    "unidentified_model",
    "audit_event",
    "measurement_supersession",
    # T18: the review projection. Re-derivable from stored bytes, so a replay
    # may clear it -- but only through `reset_batch_staging`, which is the
    # function's own privilege and not a grant any login role holds.
    "stg_review_row",
    # T19: who accepted which warning. Not re-derivable from anything: a
    # replay invalidates an acknowledgement by moving the batch's revision,
    # never by removing the record.
    "review_acknowledgement",
)

# The only load_batch columns an application may ever write after insert
# (docs/tasks/T01-security-remediation.md step 3).
#
# T04 CHANGE: plant_code joined this set in revision 0003. The batch row now
# has to exist before its rows are read -- that is what makes the
# duplicate-hash refusal a database guarantee rather than a SELECT -- and
# which plant a file belongs to is only known once the rows are read. Every
# other provenance column is still frozen at insert, and the two tests below
# still prove it.
# T18 CHANGE: profile_id and review_revision join it in revision 0006. Both
# are written by the worker *after* the parse -- which template profile read
# the sheet, and the hash of the projection a reviewer will be shown -- so
# neither can be set at insert. Every provenance column is still frozen.
# T26 CHANGE: domain, semantic_signature, sheet_class and unreviewed_headers
# join it in revision 0009. The worker re-derives all four from the stored
# bytes on every parse and replay; source_file, source_sheet, file_hash,
# raw_store_key, loaded_by and template_fingerprint stay frozen at insert.
ALLOWED_LOAD_BATCH_UPDATE_COLUMNS = {
    "domain",
    "semantic_signature",
    "sheet_class",
    "unreviewed_headers",
    "status",
    "plant_code",
    "rows_in_file",
    "rows_loaded",
    "rows_duplicate",
    "rows_rejected",
    "rows_quarantine",
    "started_at",
    "finished_at",
    "notes",
    "superseded_by",
    "profile_id",
    "review_revision",
}


# =====================================================================
# (a) DELETE FROM wavescan must be refused
# =====================================================================


def test_app_role_cannot_delete_from_wavescan(app_conn, sample_measurement_id):
    """ADR 0005: a measurement is an instrument fact. It is never deleted."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(
                "DELETE FROM wavescan WHERE measurement_id = %s",
                (sample_measurement_id,),
            )


def test_app_role_cannot_delete_whole_wavescan_table(app_conn):
    """The unqualified statement -- the one that empties the fact table."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("DELETE FROM wavescan")


def test_app_role_cannot_delete_a_whole_upload_from_wavescan(
    app_conn, sample_load_id
):
    """The exact statement in loader.py:371 (``delete_batch`` step 1)."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("DELETE FROM wavescan WHERE load_id = %s", (sample_load_id,))


# =====================================================================
# (b) DELETE FROM load_batch must be refused
# =====================================================================


def test_app_role_cannot_delete_from_load_batch(app_conn, sample_load_id):
    """The exact statement in loader.py:381 (``delete_batch`` step 2)."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("DELETE FROM load_batch WHERE load_id = %s", (sample_load_id,))


def test_app_role_cannot_delete_whole_load_batch_table(app_conn):
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("DELETE FROM load_batch")


def test_app_role_cannot_wipe_an_upload_via_the_loader_delete_sequence(
    app_conn, sample_load_id
):
    """The whole of ``Loader.delete_batch`` (loader.py:353-387), in order.

    A bare ``DELETE FROM load_batch`` is refused by wavescan's FK even
    without T01, which makes the privilege look adequate when it is not:
    the demo clears wavescan first, and then the batch row -- and the
    staging evidence -- goes with it. This test runs that exact sequence,
    with a stg_raw row present, so it fails unless the *privilege* is
    what stops step one.
    """
    with app_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO stg_raw (load_id, source_row, raw_date) "
            "VALUES (%s, 990200, '2026-06-01')",
            (sample_load_id,),
        )

        # A savepoint, so the surviving-evidence check below can still run
        # after the refusal aborts the inner block.
        with pytest.raises(pgerr.InsufficientPrivilege):
            with app_conn.transaction():
                # step 1: clear the measurements the batch produced
                cur.execute(
                    "DELETE FROM wavescan WHERE load_id = %s", (sample_load_id,)
                )
                # step 2: remove the batch -- cascading stg_raw / reject_log /
                # unidentified_model in the demo schema
                cur.execute(
                    "DELETE FROM load_batch WHERE load_id = %s", (sample_load_id,)
                )

        # the evidence is still there
        cur.execute(
            "SELECT count(*) FROM stg_raw WHERE load_id = %s", (sample_load_id,)
        )
        assert cur.fetchone()[0] == 1, "staging evidence was destroyed"


# =====================================================================
# (c) INSERT INTO audit_event must succeed
# =====================================================================


def test_app_role_can_insert_audit_event(app_conn, sample_load_id):
    """Append-only means append must work; the mutation and its audit row
    are written in the same transaction (docs/AGENTS.md section 2)."""
    correlation_id = str(uuid.uuid4())
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_event
                (actor_user_id, actor_type, action, entity_type, entity_id,
                 before, after, correlation_id)
            VALUES (NULL, 'system', 'batch.commit', 'load_batch', %s,
                    NULL, %s::jsonb, %s)
            RETURNING id, occurred_at
            """,
            (str(sample_load_id), '{"status": "COMMITTED"}', correlation_id),
        )
        row = cur.fetchone()

    assert row is not None, "INSERT INTO audit_event returned no row"
    assert row[0] > 0, "audit_event.id sequence is not usable by the app role"
    assert row[1] is not None, "audit_event.occurred_at was not defaulted"

    # and it is readable back in the same transaction
    with app_conn.cursor() as cur:
        cur.execute(
            "SELECT action, actor_type FROM audit_event WHERE correlation_id = %s",
            (correlation_id,),
        )
        assert cur.fetchone() == ("batch.commit", "system")


def test_audit_event_rejects_an_unknown_actor_type(app_conn):
    """Append-only is not the same as unvalidated."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                """
                INSERT INTO audit_event
                    (actor_type, action, entity_type, entity_id)
                VALUES ('robot', 'batch.commit', 'load_batch', '1')
                """
            )


def test_app_role_cannot_update_audit_event(app_conn, sample_load_id):
    """Append-only: rewriting history must be impossible, not discouraged."""
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_event (actor_type, action, entity_type, entity_id)
            VALUES ('system', 'batch.commit', 'load_batch', %s)
            RETURNING id
            """,
            (str(sample_load_id),),
        )
        audit_id = cur.fetchone()[0]

        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(
                "UPDATE audit_event SET action = 'tampered' WHERE id = %s",
                (audit_id,),
            )


def test_app_role_cannot_delete_audit_event(app_conn, sample_load_id):
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_event (actor_type, action, entity_type, entity_id)
            VALUES ('system', 'batch.commit', 'load_batch', %s)
            RETURNING id
            """,
            (str(sample_load_id),),
        )
        audit_id = cur.fetchone()[0]

        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("DELETE FROM audit_event WHERE id = %s", (audit_id,))


# =====================================================================
# No in-place edit of a measurement (ADR 0005, loader.py:434)
# =====================================================================


def test_app_role_cannot_update_wavescan(app_conn, sample_measurement_id):
    """``Loader.update_row`` -- the UPDATE that overwrote a gauge reading."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(
                "UPDATE wavescan SET cf = 99.9 WHERE measurement_id = %s",
                (sample_measurement_id,),
            )


def test_app_role_cannot_update_wavescan_flags(app_conn, sample_measurement_id):
    """Not even the cheap-looking columns: is_duplicate hides a row from
    every reporting view, so it is a value change in disguise."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(
                "UPDATE wavescan SET is_duplicate = true WHERE measurement_id = %s",
                (sample_measurement_id,),
            )


def test_app_role_can_still_insert_wavescan(app_conn, sample_load_id):
    """Immutability must not break ingest: INSERT is the whole job."""
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wavescan (measured_date,plant,model,checkzone,color,
                                  tolerance_group,paintline,serial_no,
                                  lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                                  load_id,source_sheet,source_row)
            VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey','Horizontal',
                    'BOOTH1','T01INS',5,15,60,87,14,19,25,13,13,9,0,
                    %s,'t',990001)
            RETURNING measurement_id
            """,
            (sample_load_id,),
        )
        assert cur.fetchone()[0] > 0


# =====================================================================
# load_batch: UPDATE narrowed to status / counts / timestamps / notes
# =====================================================================


def test_app_role_can_update_load_batch_status_and_counts(app_conn, sample_load_id):
    """The legitimate write: the loader finishing a batch."""
    with app_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE load_batch
               SET status = 'RUNNING',
                   rows_in_file = 10, rows_loaded = 7, rows_duplicate = 1,
                   rows_rejected = 1, rows_quarantine = 1,
                   finished_at = now(),
                   notes = 'T01 test'
             WHERE load_id = %s
            RETURNING load_id
            """,
            (sample_load_id,),
        )
        assert cur.fetchone()[0] == sample_load_id


@pytest.mark.parametrize(
    "column, value",
    [
        ("source_file", "'rewritten.xlsx'"),
        ("source_sheet", "'other'"),
        # plant_code was here until T04; see the note on
        # ALLOWED_LOAD_BATCH_UPDATE_COLUMNS for why it moved.
        ("file_hash", "'0'"),
        ("loaded_by", "'00000000-0000-0000-0000-000000000001'::uuid"),
    ],
)
def test_app_role_cannot_update_load_batch_identity_columns(
    app_conn, sample_load_id, column, value
):
    """Identity and provenance columns are as immutable as the facts.
    Rewriting file_hash would defeat the reload guard; rewriting
    source_file would relabel someone else's upload."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(
                f"UPDATE load_batch SET {column} = {value} WHERE load_id = %s",
                (sample_load_id,),
            )


def test_load_batch_update_grant_is_column_scoped(admin_conn, app_role):
    """Catalog check: the grant itself is narrow, not just unused."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.column_privileges
            WHERE table_schema = 'public'
              AND table_name = 'load_batch'
              AND privilege_type = 'UPDATE'
              AND grantee = %s
            ORDER BY column_name
            """,
            (app_role,),
        )
        granted = {r[0] for r in cur.fetchall()}

    assert granted, f"{app_role} has no UPDATE on load_batch at all"
    assert granted <= ALLOWED_LOAD_BATCH_UPDATE_COLUMNS, (
        "UPDATE granted on columns outside the allowed set: "
        f"{sorted(granted - ALLOWED_LOAD_BATCH_UPDATE_COLUMNS)}"
    )


# =====================================================================
# Evidence tables: no DELETE for anyone, no CASCADE from load_batch
# =====================================================================


@pytest.mark.parametrize("table", ["stg_raw", "reject_log", "unidentified_model"])
def test_app_role_cannot_delete_evidence_tables(app_conn, table):
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(f"DELETE FROM {table}")


def test_no_login_role_holds_delete_on_evidence_tables(admin_conn):
    """Sweep every non-superuser login role, not just the one under test:
    revoking from one role while another keeps DELETE is still a hole."""
    roles = application_roles(admin_conn)
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT grantee, table_name, privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
              AND privilege_type IN ('DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER')
              AND grantee = ANY(%s)
            ORDER BY grantee, table_name, privilege_type
            """,
            (list(EVIDENCE_TABLES), roles),
        )
        offenders = cur.fetchall()

    assert offenders == [], f"forbidden privileges still granted: {offenders}"


def test_no_login_role_holds_update_on_wavescan(admin_conn):
    roles = application_roles(admin_conn)
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT grantee, column_name
            FROM information_schema.column_privileges
            WHERE table_schema = 'public'
              AND table_name = 'wavescan'
              AND privilege_type = 'UPDATE'
              AND grantee = ANY(%s)
            ORDER BY grantee, column_name
            """,
            (roles,),
        )
        offenders = cur.fetchall()

    assert offenders == [], f"UPDATE on wavescan still granted: {offenders}"


def test_no_login_role_holds_update_or_delete_on_audit_event(admin_conn):
    """docs/01-DATA-MODEL.md section 6.2: granted to nobody, ever."""
    roles = application_roles(admin_conn)
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT grantee, privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = 'public'
              AND table_name = 'audit_event'
              AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
              AND grantee = ANY(%s)
            """,
            (roles,),
        )
        offenders = cur.fetchall()

    assert offenders == [], f"audit_event is not append-only: {offenders}"


@pytest.mark.parametrize(
    "child_table",
    ["stg_raw", "reject_log", "unidentified_model"],
)
def test_load_batch_child_fks_are_not_cascade(admin_conn, child_table):
    """The CASCADE wipe path (03-SECURITY.md section 1) must be gone."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.conname,
                   CASE c.confdeltype
                       WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
                       WHEN 'c' THEN 'CASCADE'   WHEN 'n' THEN 'SET NULL'
                       WHEN 'd' THEN 'SET DEFAULT'
                   END AS on_delete
            FROM pg_constraint c
            WHERE c.contype = 'f'
              AND c.confrelid = 'load_batch'::regclass
              AND c.conrelid = %s::regclass
            """,
            (child_table,),
        )
        rows = cur.fetchall()

    assert rows, f"{child_table} has no FK to load_batch"
    for conname, on_delete in rows:
        assert on_delete == "RESTRICT", (
            f"{child_table}.{conname} is ON DELETE {on_delete}; "
            "deleting a batch would destroy its evidence"
        )


def test_deleting_a_batch_is_refused_even_for_the_owner(admin_tx):
    """Belt and braces: even a principal that *has* DELETE cannot remove a
    batch while its staging evidence exists. Grants can be re-granted by
    mistake; this constraint cannot be bypassed by a grant."""
    with admin_tx.cursor() as cur:
        cur.execute(
            """
            INSERT INTO load_batch (source_file, source_sheet, file_hash,
                                    raw_store_key, status)
            VALUES ('T01-RESTRICT-TEST', 'sheet', repeat('e',64),
                    'raw/t01-restrict', 'RUNNING')
            RETURNING load_id
            """
        )
        load_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO stg_raw (load_id, source_row, raw_date) VALUES (%s, 1, 'x')",
            (load_id,),
        )

        with pytest.raises((pgerr.ForeignKeyViolation, pgerr.RestrictViolation)):
            cur.execute("DELETE FROM load_batch WHERE load_id = %s", (load_id,))


# =====================================================================
# file_hash: the reload guard is a database constraint, not a SELECT
# =====================================================================


def test_load_batch_file_hash_has_a_unique_constraint(admin_conn):
    """The reload guard is a constraint, not an application SELECT.

    T04 CHANGE: the key is `(file_hash, source_sheet)`, not `file_hash`
    alone. T01 added the narrower form when every demo batch was one sheet;
    T02 then made a measurement's identity `(load_id, source_row)`, which
    forces one batch per sheet, which makes two batches of one file share a
    hash. The guarantee that matters is unchanged and is asserted by
    `test_reloading_the_same_file_hash_is_refused` below: the same bytes
    cannot be ingested twice. See revision 0003 and
    docs/reports/T04-INGEST.md.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'load_batch'::regclass
              AND contype = 'u'
              AND pg_get_constraintdef(oid) ILIKE '%%file_hash%%'
            """
        )
        rows = cur.fetchall()

    assert rows, "load_batch has no UNIQUE constraint covering file_hash"
    assert any("source_sheet" in definition for _, definition in rows), (
        f"the file_hash unique key does not include source_sheet: {rows}"
    )


def test_reloading_the_same_file_hash_is_refused(app_conn):
    """Two batches, same bytes: the second must be refused by the
    database, not merely by an application-level SELECT check."""
    file_hash = "a" * 64
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO load_batch (source_file, source_sheet, file_hash,
                                    raw_store_key, status)
            VALUES ('T01-first.xlsx', 'sheet', %s, 'raw/t01-first', 'RUNNING')
            """,
            (file_hash,),
        )
        with pytest.raises(pgerr.UniqueViolation):
            cur.execute(
                """
                INSERT INTO load_batch (source_file, source_sheet, file_hash,
                                        raw_store_key, status)
                VALUES ('T01-second-name-same-bytes.xlsx', 'sheet', %s,
                        'raw/t01-second', 'RUNNING')
                """,
                (file_hash,),
            )


def test_no_duplicate_file_hash_values_exist(admin_conn):
    """Guards the migration precondition: if this ever fails, the UNIQUE
    constraint was forced through over real collisions.

    T04 CHANGE: grouped by `(file_hash, source_sheet)`. One workbook with two
    sheets is now two batches sharing a hash -- that is the point of the
    widened key, and the vault's SAP July file is exactly that shape. What
    must still never happen is the same sheet of the same bytes twice.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT file_hash, source_sheet, count(*),
                   array_agg(load_id ORDER BY load_id)
            FROM load_batch
            WHERE file_hash IS NOT NULL
            GROUP BY file_hash, source_sheet
            HAVING count(*) > 1
            """
        )
        duplicates = cur.fetchall()

    assert duplicates == [], (
        f"the same sheet of the same bytes is present twice: {duplicates}"
    )


# =====================================================================
# Supporting schema objects
# =====================================================================


def test_app_user_table_exists(admin_conn):
    """docs/01-DATA-MODEL.md section 6.1 -- needed so attribution FKs resolve."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'app_user'
            ORDER BY ordinal_position
            """
        )
        columns = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    assert columns, "app_user does not exist"
    for required in ("id", "entra_oid", "upn", "display_name", "created_at",
                     "last_seen_at"):
        assert required in columns, f"app_user is missing {required}"
    assert columns["id"][0] == "uuid"


def test_audit_event_actor_fk_points_at_app_user(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.confrelid::regclass::text
            FROM pg_constraint c
            WHERE c.contype = 'f' AND c.conrelid = 'audit_event'::regclass
            """
        )
        parents = {r[0] for r in cur.fetchall()}

    assert "app_user" in parents, (
        "audit_event.actor_user_id does not reference app_user; "
        "attribution would not be enforced"
    )


# =====================================================================
# No DDL, no escalation
# =====================================================================


def test_app_role_cannot_create_tables(app_conn):
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("CREATE TABLE t01_should_not_exist (x int)")


def test_app_role_cannot_drop_the_fact_table(app_conn):
    with app_conn.cursor() as cur:
        with pytest.raises((pgerr.InsufficientPrivilege, psycopg.errors.SyntaxError)):
            cur.execute("DROP TABLE wavescan")


def test_app_role_cannot_truncate_the_fact_table(app_conn):
    """TRUNCATE is a DELETE that leaves no rows to audit."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("TRUNCATE wavescan")


def test_app_role_is_not_a_superuser(admin_conn, app_role):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolreplication
            FROM pg_roles WHERE rolname = %s
            """,
            (app_role,),
        )
        row = cur.fetchone()

    assert row is not None, f"role {app_role} not found"
    assert row == (False, False, False, False, False), (
        f"{app_role} holds elevated role attributes: {row}"
    )
