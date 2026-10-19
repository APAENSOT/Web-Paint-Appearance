"""T08: let an approved mapping land, and let a batch be replayed.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-12

Three changes. The first two are grants the approve route cannot work
without; the third is the only new database object, and it is the one worth
arguing about.

1. **`app_rw` gains `INSERT` on `ref_model_alias`.** T01 granted `SELECT` on
   every reference table with the comment "the loader resolves spellings
   through these tables; it must never invent a colour or zone". That reason
   is intact and this grant does not weaken it: nothing on the ingest path
   writes here. The only caller is the **Admin-only** approve route, acting on
   a proposal an Engineer wrote and an Admin read -- which is exactly the
   "propose -> Admin approve -> replay" sequence `AGENTS.md` rule 6 requires
   instead of guessing. `INSERT` only: no `UPDATE`, so an approved spelling
   cannot be quietly repointed at a different model, and no `DELETE`, so a
   decision cannot be withdrawn without a trace. `ref_column_alias` already
   had this shape from T02; this brings the model alias table in line with it.

   The other five alias tables (`ref_plant_alias`, `ref_color_alias`,
   `ref_checkzone_alias`, `ref_paintline_alias`, `ref_plant_zone_map`) are
   deliberately **not** granted. Their proposal kinds stay unimplemented in
   T08 (ZONE is D5's zone 14, ALIAS_COLOR is D2), and a grant with no caller
   is just an unguarded door.

2. **`app_rw` gains `UPDATE (enqueued_at)` on `ingest_job`.** `ingest_job`
   has `UNIQUE (load_id)`, so a replay cannot insert a second job for a batch
   that already has one; it re-queues the existing row. Without this column
   the re-queued job would advertise the first upload's `enqueued_at`
   alongside `attempts = 0`, which reads as a job that has been waiting for
   hours. `ingest_job` is a work queue, not a fact table: nothing in ADR 0005
   protects it, and T04 already granted `UPDATE` on its five other columns.

3. **`reset_batch_staging(bigint)`, `SECURITY DEFINER`.**

   Replaying a `PENDING_REVIEW` batch re-stages the same rows, and `stg_raw`
   has `UNIQUE (load_id, source_row)` -- so the second parse collides on
   every row unless the first parse's staging is cleared first. `app_rw`
   holds no `DELETE` on `stg_raw`, `reject_log` or `unidentified_model`, and
   T08 is explicitly forbidden from granting one.

   So the deletion lives in a function that runs as its owner and takes one
   argument, and the function refuses unless all three of these hold:

     * the batch exists;
     * its status is `REJECTED_TEMPLATE` or `PENDING_REVIEW` -- never
       `COMMITTED`, `SUPERSEDED`, `FAILED` or `RUNNING`;
     * `SELECT count(*) FROM wavescan WHERE load_id = $1` is **zero**.

   The third is the one that matters. A batch with no `wavescan` rows has
   produced no facts, so nothing it owns is evidence of a measurement:
   `stg_raw` is a verbatim copy of bytes still sitting in the object store,
   and `reject_log` / `unidentified_model` describe rows that were never
   loaded. Re-deriving all three from the same stored bytes is what
   `02-PIPELINE.md` §8 calls replay. **This is not an ADR 0005 exception** --
   ADR 0005 is about facts and batches, and this function cannot touch
   `wavescan` or `load_batch` at all. It has no statement that names either.

   `SECURITY DEFINER` is narrowed the way PostgreSQL's own documentation
   asks: `search_path` is pinned so the body cannot be redirected at
   attacker-created tables, `EXECUTE` is revoked from `PUBLIC`, and the only
   grantees are the two application roles. The argument is a `bigint`, so
   there is no string to inject.

**This revision is destructive**: it creates a function whose purpose is to
DELETE staging rows. It needs the owner's explicit approval line when the
owner commits (`AGENTS.md` §2). Nothing in `upgrade()` itself deletes a row.

`downgrade()` reverses all three and refuses nothing, because none of the
three can lose information on the way out.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

#: Staging, quarantine and reject rows. Re-derivable from the stored bytes,
#: which is what makes them safe to clear. `wavescan` and `load_batch` are
#: deliberately absent and the guard below is what keeps them absent.
STAGING_TABLES = ("stg_raw", "reject_log", "unidentified_model")

#: The only two states a batch may be replayed from. Everything else either
#: has facts (`COMMITTED`, `SUPERSEDED`) or is mid-flight (`RUNNING`).
REPLAYABLE_STATUSES = ("REJECTED_TEMPLATE", "PENDING_REVIEW")


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


def upgrade() -> None:
    # =================================================================
    # 1 + 2. The two grants the approve and replay paths need.
    # =================================================================
    _for_each_role(
        """
        -- Written only by the Admin approve route, never by ingest.
        -- No UPDATE: an approved alias cannot be repointed.
        -- No DELETE: a decision cannot be withdrawn silently.
        GRANT INSERT ON ref_model_alias TO {role};

        -- The queue, not a fact table. A re-queued job says when it was
        -- re-queued instead of when the file was first uploaded.
        GRANT UPDATE (enqueued_at) ON ingest_job TO {role};
        """
    )

    # =================================================================
    # 3. reset_batch_staging
    # =================================================================
    deletes = "\n".join(
        f"        DELETE FROM {table} WHERE load_id = p_load_id;\n"
        f"        GET DIAGNOSTICS v_n = ROW_COUNT;\n"
        f"        v_cleared := v_cleared || jsonb_build_object('{table}', v_n);"
        for table in STAGING_TABLES
    )
    quoted = ", ".join(f"'{s}'" for s in REPLAYABLE_STATUSES)
    # Same list, unquoted, for the error message. Quoting it there would nest
    # single quotes inside the message literal.
    listed = " or ".join(REPLAYABLE_STATUSES)

    # Messages are built with `||` rather than RAISE's `%` placeholders:
    # `op.execute` hands this text to psycopg, which reads `%` as a parameter
    # marker of its own.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION reset_batch_staging(p_load_id bigint)
        RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $fn$
        DECLARE
            v_status  text;
            v_facts   bigint;
            v_n       bigint;
            v_cleared jsonb := '{{}}'::jsonb;
        BEGIN
            SELECT status INTO v_status
              FROM load_batch WHERE load_id = p_load_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'batch % does not exist', p_load_id
                    USING ERRCODE = 'no_data_found';
            END IF;

            -- A batch that has become facts is never replayed. This check is
            -- the reason the function is allowed to exist: it is what keeps
            -- "clear staging" from ever meaning "delete evidence".
            SELECT count(*) INTO v_facts
              FROM wavescan WHERE load_id = p_load_id;

            IF v_facts > 0 THEN
                RAISE EXCEPTION
                    'batch % has % wavescan row(s); staging that belongs to committed measurements is evidence and is never cleared (ADR 0005)',
                    p_load_id, v_facts
                    USING ERRCODE = 'raise_exception';
            END IF;

            IF v_status NOT IN ({quoted}) THEN
                RAISE EXCEPTION
                    'batch % is %, so its staging is not clearable; only a {listed} batch can be replayed',
                    p_load_id, v_status
                    USING ERRCODE = 'raise_exception';
            END IF;

{deletes}

            RETURN v_cleared;
        END;
        $fn$;
        """
    )

    op.execute(
        "COMMENT ON FUNCTION reset_batch_staging(bigint) IS "
        "'Clear stg_raw/reject_log/unidentified_model for ONE batch that has "
        "produced no wavescan rows, so it can be replayed from stored bytes "
        "(docs/02-PIPELINE.md section 8). Refuses otherwise. Cannot touch "
        "wavescan or load_batch. T08.'"
    )

    # Deny by default, then name the two callers.
    op.execute("REVOKE ALL ON FUNCTION reset_batch_staging(bigint) FROM PUBLIC")
    _for_each_role(
        "GRANT EXECUTE ON FUNCTION reset_batch_staging(bigint) TO {role};"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS reset_batch_staging(bigint)")
    _for_each_role(
        """
        REVOKE INSERT ON ref_model_alias FROM {role};
        REVOKE UPDATE (enqueued_at) ON ingest_job FROM {role};
        """
    )
