"""T21: append-only review overrides, and an ABANDONED batch status.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-17

Two changes. **Nothing in this revision deletes anything**, no existing
function is rewritten, and no grant is widened beyond the new table, so it
is not destructive in the `AGENTS.md` section 2 sense.

1. **`ck_batch_status` gains `ABANDONED`.** A reviewer removing a sheet that
   never became measurements from the review queue (design F6). It is a
   status, not a DELETE: the bytes, `stg_raw`, the projection, the
   acknowledgements and the audit trail all stay, and a batch that has any
   `wavescan` row is refused by the service before this status is written.
   The CHECK is dropped and re-added with one more value; no row changes,
   because no row can hold a value the old CHECK forbade.

2. **`review_override`.** A named person said "the file's CF for this row is
   wrong, and here is the value and why" -- before commit (design F11). It is
   evidence, not staging:

   * `app_rw` holds `SELECT, INSERT` and nothing else. There is no UPDATE,
     because changing your mind means writing another override (the latest
     per `(source_row, field)` wins); there is no DELETE, for ADR 0005's
     reason applied to a reviewer's statement.
   * It is **not** in `reset_batch_staging`. That function is not touched
     here, so a replay re-derives the projection from the stored bytes and
     re-applies these rows, and cannot tidy them away.
   * Only measure fields (`field` CHECK). Identity -- plant, model, zone,
     colour, serial, date -- is never overridable; that is a mapping or a
     corrected re-upload.
   * `new_value` may be NULL only for `b`, the one nullable measure. The
     measure ranges themselves are the DTO's job and `wavescan`'s CHECKs at
     commit, exactly as for a T09 correction.
   * `review_revision` is the revision the reviewer had loaded when they
     wrote it, so the record says which proposal it was a statement about.

`downgrade()` drops the table and restores the six-status CHECK. It refuses
if any batch is `ABANDONED`, because silently relabelling one would be a
status nobody chose.
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

STATUSES_0002 = (
    "RUNNING", "PENDING_REVIEW", "COMMITTED",
    "FAILED", "SUPERSEDED", "REJECTED_TEMPLATE",
)
STATUSES = STATUSES_0002 + ("ABANDONED",)

#: The measures an override may change. Same vocabulary as
#: `schemas/corrections.py` MEASURE_BOUNDS plus `b`.
OVERRIDE_FIELDS = ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b")

#: Same bound as a supersede reason and an acknowledgement note.
REASON_MAX = 2000


def _for_each_role(sql: str) -> None:
    """Apply `sql` per role, skipping a role this database does not have."""
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                {sql.format(role=role)}
            END $$;
            """
        )


def _status_check(statuses: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{s}'" for s in statuses)
    op.execute("ALTER TABLE load_batch DROP CONSTRAINT IF EXISTS ck_batch_status")
    op.execute(
        f"ALTER TABLE load_batch ADD CONSTRAINT ck_batch_status "
        f"CHECK (status IN ({listed}))"
    )


def upgrade() -> None:
    _status_check(STATUSES)

    fields = ", ".join(f"'{f}'" for f in OVERRIDE_FIELDS)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS review_override (
            override_id       bigserial PRIMARY KEY,
            load_id           bigint NOT NULL
                                  REFERENCES load_batch (load_id)
                                  ON DELETE RESTRICT,
            plant_code        text NOT NULL
                                  REFERENCES ref_plant (plant_code)
                                  ON DELETE RESTRICT,
            file_hash         char(64) NOT NULL,
            source_row        integer NOT NULL,
            field             text NOT NULL,
            previous_proposed numeric,
            new_value         numeric,
            reason            text NOT NULL,
            review_revision   char(64) NOT NULL,
            actor_user_id     uuid NOT NULL REFERENCES app_user (id),
            created_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_override_field CHECK (field IN ({fields})),
            -- `b` is the one nullable measure, so clearing it is a value.
            -- Every other measure is NOT NULL in wavescan and an override
            -- that nulls one would only be refused later, at commit.
            CONSTRAINT ck_override_value CHECK (new_value IS NOT NULL OR field = 'b'),
            CONSTRAINT ck_override_reason CHECK (
                length(reason) BETWEEN 1 AND {REASON_MAX}
                AND btrim(reason) <> ''
            )
        )
        """
    )
    # Re-derivation asks one question: the latest value per (row, field).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_override_current "
        "ON review_override (load_id, source_row, field, created_at)"
    )
    op.execute(
        "COMMENT ON TABLE review_override IS "
        "'A named person replaced one measure of one review row before commit, "
        "with a reason (T21, design F11). Append-only: app_rw holds SELECT and "
        "INSERT only. Not staging: reset_batch_staging does not clear it, and "
        "every re-derivation from the stored bytes applies the latest row per "
        "(load_id, source_row, field). stg_raw keeps what the file said.'"
    )
    op.execute("REVOKE ALL ON review_override FROM PUBLIC")
    _for_each_role(
        """
        GRANT SELECT, INSERT ON review_override TO {role};
        GRANT USAGE, SELECT ON SEQUENCE review_override_override_id_seq TO {role};
        """
    )


def downgrade() -> None:
    """Drop the table and restore the T02 status CHECK.

    Refuses while any batch is ABANDONED: the old CHECK cannot hold it, and
    choosing another status for it on the owner's behalf is not a downgrade.
    Dropping `review_override` loses who replaced which value and why, which
    nothing in the object store can rebuild.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM load_batch WHERE status = 'ABANDONED') THEN
                RAISE EXCEPTION
                    'load_batch has ABANDONED rows; downgrade would have to relabel them';
            END IF;
        END $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS review_override")
    _status_check(STATUSES_0002)
