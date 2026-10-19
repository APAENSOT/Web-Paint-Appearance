"""T04: make ingest possible, and make attribution mandatory.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-10

Five changes. The first two are the ordered identity work T02's review handed
to T03 and T03's report §6 deferred to here; the third is a conflict between
two constraints T01 and T02 each added for good reasons; the fourth is the
queue; the fifth is a correctness fix T03 found and could not make.

1. **`app_user` becomes writable by the application.** T01 granted `SELECT`
   and deliberately withheld `INSERT` "until T04 implements the OIDC
   first-login flow that would need it". T04 implements it, so the grant
   lands here -- *before* the constraint in (2), because a `NOT NULL` on a
   column nobody can populate is a broken deployment, not a guarantee.

2. **`measurement_supersession.actor_user_id` becomes `NOT NULL`.** With (1)
   in place and every write path attributing, a retirement without an actor
   is now impossible rather than merely discouraged. Existing NULL rows are a
   refusal, not a backfill: inventing an actor for a retirement nobody can
   name would be worse than the NULL it replaces.

3. **`UNIQUE (file_hash)` becomes `UNIQUE (file_hash, source_sheet)`.**
   T01 added the reload guard when every demo batch was one sheet. T02 then
   made a measurement's identity `(load_id, source_row)`. Together they are
   unsatisfiable for a real multi-sheet workbook: `02-PIPELINE.md` and
   `load_batch`'s own comment say "one row per uploaded sheet", two sheets
   both have a row 2, so two sheets need two batches -- and two batches from
   one file share a hash. The vault's SAP July 2026 workbook has two sheets,
   so this is not hypothetical. Widening the key keeps the guarantee that
   matters ("the same bytes cannot be ingested twice": a re-upload collides
   on every sheet) and drops only the accidental restriction to one sheet.
   Discussed in docs/reports/T04-INGEST.md -- this is the change in this
   revision most worth a second opinion.

4. **`ingest_job`**, the queue `02-PIPELINE.md` §9 asks for: claimed with
   `FOR UPDATE SKIP LOCKED`, one job per batch.

5. **The `wavescan` range CHECKs compare NUMERIC to NUMERIC.** They were
   written when the columns were `REAL` and the T02 type change preserved
   the `::double precision` casts, so `cf = 100.0000000000000001` was
   accepted by a constraint that reads as 0-100 (T03 report §11, confirmed by
   the architect review). No stored value changes: every existing row is
   re-checked by `ALTER TABLE ... ADD CONSTRAINT` and the migration fails
   loudly if any row does not satisfy the tighter form.

`downgrade()` reverses all five, refusing where reversal would lose
information.
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

#: Re-stated from 0001 so the widened set is visible in one place. The only
#: addition is plant_code -- see _load_batch_plant_code() for why.
LOAD_BATCH_UPDATABLE_COLUMNS = (
    "status",
    "rows_in_file", "rows_loaded", "rows_duplicate",
    "rows_rejected", "rows_quarantine",
    "started_at", "finished_at",
    "notes",
    "superseded_by",
)

#: (constraint, columns, tighter definition). The old definitions differ only
#: by `::double precision` casts on both sides of every comparison.
RANGE_CHECKS = {
    "ck_ws_cf": "cf >= 0 AND cf <= 100",
    "ck_ws_doi": "doi >= 0 AND doi <= 100",
    "ck_ws_b": "b IS NULL OR (b >= -100 AND b <= 100)",
    "ck_ws_nonneg": (
        "lw >= 0 AND sw >= 0 AND cf >= 0 AND doi >= 0 AND du >= 0 "
        "AND wa >= 0 AND wb >= 0 AND wc >= 0 AND wd >= 0 AND we >= 0"
    ),
}

OLD_RANGE_CHECKS = {
    "ck_ws_cf": "cf::double precision >= 0 AND cf::double precision <= 100",
    "ck_ws_doi": "doi::double precision >= 0 AND doi::double precision <= 100",
    "ck_ws_b": (
        "b IS NULL OR (b::double precision >= -100 "
        "AND b::double precision <= 100)"
    ),
    "ck_ws_nonneg": (
        "lw::double precision >= 0 AND sw::double precision >= 0 "
        "AND cf::double precision >= 0 AND doi::double precision >= 0 "
        "AND du::double precision >= 0 AND wa::double precision >= 0 "
        "AND wb::double precision >= 0 AND wc::double precision >= 0 "
        "AND wd::double precision >= 0 AND we::double precision >= 0"
    ),
}


# =====================================================================
def upgrade() -> None:
    _preflight()
    _app_user_grants()
    _supersession_actor_required()
    _batch_identity()
    _load_batch_plant_code()
    _ingest_job()
    _tighten_range_checks()


# ---------------------------------------------------------------------
def _preflight() -> None:
    """Refuse rather than guess, the stance 0001 and 0002 both take."""
    op.execute(
        """
        DO $$
        DECLARE orphan_count bigint; sample text;
        BEGIN
            SELECT count(*) INTO orphan_count
              FROM measurement_supersession WHERE actor_user_id IS NULL;
            IF orphan_count > 0 THEN
                SELECT string_agg(id::text, ', ' ORDER BY id) INTO sample
                  FROM (SELECT id FROM measurement_supersession
                         WHERE actor_user_id IS NULL ORDER BY id LIMIT 10) s;
                RAISE EXCEPTION
                    '0003 precondition failed: % measurement_supersession row(s) '
                    'have no actor_user_id (ids: %). These retirements were '
                    'recorded before authentication existed. This migration will '
                    'not invent an actor for them - attributing a retirement to '
                    'someone who did not make it is worse than the NULL. Decide '
                    'per row: set actor_user_id to the app_user who actually did '
                    'it, or delete the row as owner if it was a test artefact, '
                    'then re-run.', orphan_count, sample;
            END IF;
        END $$;
        """
    )
    # A batch whose (file_hash, source_sheet) is not unique cannot exist today
    # -- file_hash alone is unique -- but check anyway so a hand-edited
    # database fails here rather than half way through.
    op.execute(
        """
        DO $$
        DECLARE dupes bigint;
        BEGIN
            SELECT count(*) INTO dupes FROM (
                SELECT file_hash, source_sheet FROM load_batch
                 GROUP BY file_hash, source_sheet HAVING count(*) > 1) d;
            IF dupes > 0 THEN
                RAISE EXCEPTION
                    '0003 precondition failed: % (file_hash, source_sheet) pair(s) '
                    'are already duplicated in load_batch. Report them; do not '
                    'force this through.', dupes;
            END IF;
        END $$;
        """
    )


# ---------------------------------------------------------------------
def _app_user_grants() -> None:
    """Step (a) of T03 report §6: the application may create identities.

    UPDATE is column-scoped to the three fields a sign-in refreshes. There is
    no DELETE: an identity that has attributed anything must stay resolvable,
    or the audit trail acquires dangling actor ids.
    """
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                GRANT INSERT ON app_user TO {role};
                GRANT UPDATE (upn, display_name, last_seen_at) ON app_user TO {role};
            END $$;
            """
        )
    op.execute(
        "COMMENT ON TABLE app_user IS "
        "'One row per authenticated person. Created on first sign-in (T04). "
        "Roles are NOT stored here - they come from the token at request time "
        "(01-DATA-MODEL.md section 6.1). No DELETE grant: an identity that has "
        "attributed a batch, a correction or an audit event must stay "
        "resolvable.'"
    )


def _supersession_actor_required() -> None:
    """Step (d): only after the grant above exists."""
    op.execute(
        "ALTER TABLE measurement_supersession "
        "ALTER COLUMN actor_user_id SET NOT NULL"
    )
    op.execute(
        "COMMENT ON COLUMN measurement_supersession.actor_user_id IS "
        "'Who retired this measurement. NOT NULL since T04: the application "
        "can create app_user rows from T04 onward, so an unattributed "
        "retirement is now a bug rather than a limitation.'"
    )


def _batch_identity() -> None:
    """Change 3. One batch per sheet; the same bytes still cannot land twice."""
    op.execute(
        "ALTER TABLE load_batch DROP CONSTRAINT IF EXISTS uq_load_batch_file_hash"
    )
    op.execute(
        "ALTER TABLE load_batch ADD CONSTRAINT uq_load_batch_file_sheet "
        "UNIQUE (file_hash, source_sheet)"
    )
    op.execute(
        "COMMENT ON CONSTRAINT uq_load_batch_file_sheet ON load_batch IS "
        "'A file is its bytes, and a batch is one sheet of one file "
        "(02-PIPELINE.md section 3, load_batch''s own comment). Re-uploading "
        "the same bytes collides on every sheet it contains, so the reload "
        "guard T01 added is intact; what this drops is the accidental rule "
        "that a workbook may only ever have one sheet.'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_batch_hash ON load_batch (file_hash)")


def _load_batch_plant_code() -> None:
    """`plant_code` joins the column-scoped UPDATE set.

    T01 called it provenance and froze it at insert. The batch row now has to
    exist before its rows are read -- that is what makes the duplicate-hash
    refusal a database guarantee rather than a SELECT -- and which plant a
    file belongs to is only known once the rows are read. Every other
    provenance column (source_file, source_sheet, file_hash, raw_store_key,
    loaded_by) stays frozen.
    """
    columns = ", ".join(LOAD_BATCH_UPDATABLE_COLUMNS + ("plant_code",))
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                REVOKE UPDATE ON load_batch FROM {role};
                GRANT UPDATE ({columns}) ON load_batch TO {role};
            END $$;
            """
        )


def _ingest_job() -> None:
    """Change 4. The queue from `02-PIPELINE.md` section 9."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ingest_job (
            job_id       bigserial PRIMARY KEY,
            load_id      bigint NOT NULL REFERENCES load_batch (load_id)
                             ON DELETE RESTRICT,
            status       text NOT NULL DEFAULT 'QUEUED',
            attempts     integer NOT NULL DEFAULT 0,
            last_error   text,
            enqueued_at  timestamptz NOT NULL DEFAULT now(),
            started_at   timestamptz,
            finished_at  timestamptz,
            CONSTRAINT uq_ingest_job_load UNIQUE (load_id),
            CONSTRAINT ck_ingest_job_status
                CHECK (status IN ('QUEUED','RUNNING','DONE','FAILED'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_job_claim "
        "ON ingest_job (status, job_id) WHERE status = 'QUEUED'"
    )
    op.execute(
        "COMMENT ON TABLE ingest_job IS "
        "'Work queue for the ingest worker. Claimed with SELECT ... FOR UPDATE "
        "SKIP LOCKED (02-PIPELINE.md section 9), so two workers never take the "
        "same batch and no broker is needed. Not a fact table: attempts and "
        "status are meant to be updated.'"
    )
    op.execute("REVOKE ALL ON ingest_job FROM PUBLIC")
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                GRANT SELECT, INSERT ON ingest_job TO {role};
                GRANT UPDATE (status, attempts, last_error, started_at, finished_at)
                    ON ingest_job TO {role};
                GRANT USAGE, SELECT ON SEQUENCE ingest_job_job_id_seq TO {role};
            END $$;
            """
        )


def _tighten_range_checks() -> None:
    """Change 5. NUMERIC compared to NUMERIC, so 0-100 means 0-100."""
    for name, definition in RANGE_CHECKS.items():
        op.execute(f"ALTER TABLE wavescan DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE wavescan ADD CONSTRAINT {name} CHECK ({definition})")
    op.execute(
        "COMMENT ON CONSTRAINT ck_ws_cf ON wavescan IS "
        "'CF is a percentage. Compared as NUMERIC since T04: the pre-T04 form "
        "cast both sides to double precision, so a value one part in 1e17 "
        "above 100 was accepted by a constraint that reads as 0-100.'"
    )


# =====================================================================
def downgrade() -> None:
    """Reverse T04's schema, refusing where reversal would destroy evidence."""
    op.execute(
        """
        DO $$
        DECLARE multi bigint;
        BEGIN
            SELECT count(*) INTO multi FROM (
                SELECT file_hash FROM load_batch
                 GROUP BY file_hash HAVING count(*) > 1) d;
            IF multi > 0 THEN
                RAISE EXCEPTION
                    '0003 downgrade refused: % file(s) have been ingested as more '
                    'than one sheet, so restoring UNIQUE (file_hash) would require '
                    'deleting a batch and its measurements. ADR 0005 does not '
                    'allow that. Supersede the batches first, or stay at 0003.',
                    multi;
            END IF;
        END $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS ingest_job")

    for name, definition in OLD_RANGE_CHECKS.items():
        op.execute(f"ALTER TABLE wavescan DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE wavescan ADD CONSTRAINT {name} CHECK ({definition})")

    op.execute("DROP INDEX IF EXISTS idx_batch_hash")
    op.execute(
        "ALTER TABLE load_batch DROP CONSTRAINT IF EXISTS uq_load_batch_file_sheet"
    )
    op.execute(
        "ALTER TABLE load_batch ADD CONSTRAINT uq_load_batch_file_hash "
        "UNIQUE (file_hash)"
    )

    columns = ", ".join(LOAD_BATCH_UPDATABLE_COLUMNS)
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                REVOKE UPDATE ON load_batch FROM {role};
                GRANT UPDATE ({columns}) ON load_batch TO {role};
                REVOKE INSERT ON app_user FROM {role};
                REVOKE UPDATE ON app_user FROM {role};
            END $$;
            """
        )

    op.execute(
        "ALTER TABLE measurement_supersession "
        "ALTER COLUMN actor_user_id DROP NOT NULL"
    )
