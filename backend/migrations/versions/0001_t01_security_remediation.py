"""T01 security remediation: immutable facts, append-only audit, least privilege.

Revision ID: 0001
Revises:
Create Date: 2026-09-07

Implements docs/tasks/T01-security-remediation.md against the schema shipped
by the demo project (``Paint Appearance/Component/Database/sql/``). Authority:
docs/ADR/0005-immutable-facts.md, docs/03-SECURITY.md section 2,
docs/01-DATA-MODEL.md sections 6.1, 6.2 and 8.

What this revision guarantees when it has run:

  1. No application role can DELETE from ``wavescan`` or ``load_batch``,
     and none can UPDATE ``wavescan`` at all.
  2. ``load_batch`` UPDATE is column-scoped to status / counts /
     timestamps / notes / superseded_by. Identity and provenance columns
     (``source_file``, ``file_hash``, ``plant_code``, ``loaded_by``) are
     read-only after insert.
  3. Deleting a batch cannot take its staging evidence with it: the FKs
     from ``stg_raw``, ``reject_log`` and ``unidentified_model`` are
     ON DELETE RESTRICT, so the batch row cannot be removed at all while
     evidence exists -- by any principal, including the schema owner.
  4. ``load_batch.file_hash`` is UNIQUE: the reload guard is a database
     constraint, not an application SELECT that a second worker can race.
  5. ``audit_event`` exists and is append-only: INSERT and SELECT to the
     app role, UPDATE and DELETE to nobody.
  6. ``app_user`` exists so attribution FKs resolve (T04 populates it).

Scope notes -- deliberately NOT done here, and why:

  * The ``load_batch`` status enum is not revised. ADR 0005 replaces
    "delete this upload" with ``status = 'SUPERSEDED'``, but the demo
    CHECK allows only RUNNING/SUCCESS/FAILED/ROLLED_BACK, and the revised
    lifecycle (SUCCESS -> COMMITTED, + PENDING_REVIEW/SUPERSEDED/
    REJECTED_TEMPLATE) is a T02 data migration that also has to move
    ``purge_stg_raw`` and the reporting views off ``status = 'SUCCESS'``.
    Doing half of it here would leave a schema matching neither document.
    ``superseded_by`` is added now because step 3 of the task grants
    UPDATE on it; the status value that completes the supersede workflow
    lands in T02. Until then, retiring a batch is not yet possible --
    which is strictly safer than the delete path this revision removes.
  * ``file_hash`` stays nullable ``text``. ``char(64) NOT NULL``
    (01-DATA-MODEL.md section 3) would reject the existing demo batch,
    which has a NULL hash. T02 backfills and tightens it.

This revision is destructive in the Alembic sense (it drops privileges and
rebuilds constraints) and per docs/AGENTS.md section 2 needs explicit owner
approval in the PR/commit message before it is applied to any database
holding real plant data.
"""

from __future__ import annotations

from alembic import op

revision = "0001"
# T02 change: was None. 0001 alters the demo schema rather than creating it,
# so on a database that never had that schema it failed with
# `relation "load_batch" does not exist`. Revision 0000 now supplies the
# baseline ahead of it. The body of this revision is unchanged; a database
# already stamped 0001 walks straight on to 0002 and never replays 0000.
down_revision = "0000"
branch_labels = None
depends_on = None


# The role the API and worker authenticate as, per 01-DATA-MODEL.md section 8.
APP_ROLE = "app_rw"

# The demo's role. 01-DATA-MODEL.md section 8: "retired or renamed to app_rw
# with the reduced grant set (T01)". It is not dropped here -- dropping a role
# that still owns a live connection string is an outage, and the credential is
# in the intern's local .env. It is reduced to exactly the same rights as
# app_rw instead, so it is no longer a way around any of the guarantees above.
LEGACY_APP_ROLE = "wavescan_loader"

APP_ROLES = (APP_ROLE, LEGACY_APP_ROLE)

REFERENCE_TABLES = (
    "ref_plant", "ref_plant_alias",
    "ref_model", "ref_model_alias",
    "ref_checkzone", "ref_checkzone_alias",
    "ref_model_zone",
    "ref_color", "ref_color_alias",
    "ref_paintline", "ref_paintline_alias",
)

# INSERT + SELECT. No UPDATE, no DELETE: these rows are evidence.
APPEND_ONLY_TABLES = ("wavescan", "stg_raw", "reject_log", "unidentified_model")

VIEWS = (
    "v_wavescan", "v_wavescan_p703", "v_wavescan_u704",
    "v_load_summary", "v_car_completeness",
)

SEQUENCES = (
    "wavescan_measurement_id_seq",
    "stg_raw_stg_id_seq",
    "load_batch_load_id_seq",
    "reject_log_reject_id_seq",
    "unidentified_model_unid_id_seq",
    "ref_plant_zone_map_map_id_seq",
    "audit_event_id_seq",
)

# docs/tasks/T01-security-remediation.md step 3.
LOAD_BATCH_UPDATABLE_COLUMNS = (
    "status",
    "rows_in_file", "rows_loaded", "rows_duplicate",
    "rows_rejected", "rows_quarantine",
    "started_at", "finished_at",
    "notes",
    "superseded_by",
)

# A human decides a mapping; the app only records the decision.
PLANT_ZONE_MAP_UPDATABLE_COLUMNS = (
    "confidence", "approved_by", "approved_at", "note",
)


def upgrade() -> None:
    # =================================================================
    # 0. Preconditions
    # =================================================================
    # Step 5 of the task: if duplicate hashes already exist, stop and
    # report them rather than forcing the constraint through. Raising
    # here aborts the whole migration transaction, so nothing is applied
    # half-way.
    op.execute(
        """
        DO $$
        DECLARE
            v_detail text;
        BEGIN
            SELECT string_agg(
                       format('  file_hash %s appears %s times, load_ids %s',
                              file_hash, n, load_ids),
                       E'\\n' ORDER BY n DESC)
              INTO v_detail
              FROM (
                  SELECT file_hash,
                         count(*)                        AS n,
                         array_agg(load_id ORDER BY load_id) AS load_ids
                    FROM load_batch
                   WHERE file_hash IS NOT NULL
                   GROUP BY file_hash
                  HAVING count(*) > 1
              ) dupes;

            IF v_detail IS NOT NULL THEN
                RAISE EXCEPTION
                    'T01 precondition failed: duplicate load_batch.file_hash values exist.%',
                    E'\\n' || v_detail || E'\\n' ||
                    'Two batches claim the same file bytes. Resolve which is authoritative ' ||
                    'before UNIQUE (file_hash) can be added -- do not force this through. ' ||
                    'See docs/tasks/T01-security-remediation.md step 5.';
            END IF;
        END $$;
        """
    )

    # =================================================================
    # 1. app_user -- 01-DATA-MODEL.md section 6.1
    # =================================================================
    # Minimal and empty at this stage; it exists so attribution FKs
    # resolve. Roles are NOT stored here: they come from the token at
    # request time (03-SECURITY.md section 4), so there is nothing to
    # drift out of sync with Entra.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_user (
            id            uuid        PRIMARY KEY,
            entra_oid     text        UNIQUE NOT NULL,
            upn           text        NOT NULL,
            display_name  text        NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_seen_at  timestamptz
        );
        """
    )
    op.execute(
        "COMMENT ON TABLE app_user IS "
        "'Ford identities mirrored from Entra for FK attribution. "
        "Roles are not stored here - they come from the token at request time.';"
    )

    # =================================================================
    # 2. audit_event -- 01-DATA-MODEL.md section 6.2
    # =================================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_event (
            id             bigserial   PRIMARY KEY,
            occurred_at    timestamptz NOT NULL DEFAULT now(),
            actor_user_id  uuid        REFERENCES app_user,
            actor_type     text        NOT NULL
                                       CHECK (actor_type IN ('user','system')),
            action         text        NOT NULL,
            entity_type    text        NOT NULL,
            entity_id      text        NOT NULL,
            before         jsonb,
            after          jsonb,
            correlation_id text
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_entity "
        "ON audit_event (entity_type, entity_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_occurred ON audit_event (occurred_at);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_correlation "
        "ON audit_event (correlation_id);"
    )
    op.execute(
        "COMMENT ON TABLE audit_event IS "
        "'Append-only. INSERT and SELECT are granted to the application; "
        "UPDATE and DELETE are granted to nobody (ADR 0005).';"
    )
    op.execute(
        "COMMENT ON COLUMN audit_event.actor_user_id IS "
        "'The person, from the validated token. NULL only for system/worker actions.';"
    )

    # =================================================================
    # 3. load_batch.superseded_by -- the replacement for DELETE
    # =================================================================
    op.execute("ALTER TABLE load_batch ADD COLUMN IF NOT EXISTS superseded_by bigint;")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'fk_load_batch_superseded_by'
                   AND conrelid = 'load_batch'::regclass
            ) THEN
                ALTER TABLE load_batch
                    ADD CONSTRAINT fk_load_batch_superseded_by
                    FOREIGN KEY (superseded_by) REFERENCES load_batch (load_id)
                    ON DELETE RESTRICT;
            END IF;
        END $$;
        """
    )
    op.execute(
        "COMMENT ON COLUMN load_batch.superseded_by IS "
        "'The batch that replaced this one. Set instead of deleting (ADR 0005). "
        "The SUPERSEDED status value itself arrives with the T02 status enum.';"
    )

    # =================================================================
    # 4. Evidence FKs: ON DELETE CASCADE -> ON DELETE RESTRICT
    # =================================================================
    # 03-SECURITY.md section 1: deleting a batch currently cascades to
    # stg_raw / reject_log / unidentified_model, destroying the ability to
    # prove what the file said. The app can no longer delete a batch after
    # this revision, but the cascade is removed anyway so that no future
    # admin or maintenance path can wipe evidence either.
    #
    # Constraint names are read from the catalog rather than hardcoded, so
    # this works whether or not the demo's default names were kept.
    op.execute(
        """
        DO $$
        DECLARE
            r record;
        BEGIN
            FOR r IN
                SELECT c.conname,
                       c.conrelid::regclass::text AS child_table,
                       a.attname                  AS child_column
                  FROM pg_constraint c
                  JOIN LATERAL unnest(c.conkey) AS k(attnum) ON true
                  JOIN pg_attribute a
                    ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                 WHERE c.contype  = 'f'
                   AND c.confrelid = 'load_batch'::regclass
                   AND c.conrelid IN ('stg_raw'::regclass,
                                      'reject_log'::regclass,
                                      'unidentified_model'::regclass)
                   AND c.confdeltype <> 'r'          -- not already RESTRICT
            LOOP
                EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I',
                               r.child_table, r.conname);
                EXECUTE format(
                    'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (%I) '
                    'REFERENCES load_batch (load_id) ON DELETE RESTRICT',
                    r.child_table, r.conname, r.child_column);
                RAISE NOTICE 'T01: %.% is now ON DELETE RESTRICT',
                             r.child_table, r.conname;
            END LOOP;
        END $$;
        """
    )

    # =================================================================
    # 5. UNIQUE (file_hash) -- the reload guard becomes a DB guarantee
    # =================================================================
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'uq_load_batch_file_hash'
                   AND conrelid = 'load_batch'::regclass
            ) THEN
                ALTER TABLE load_batch
                    ADD CONSTRAINT uq_load_batch_file_hash UNIQUE (file_hash);
            END IF;
        END $$;
        """
    )
    op.execute(
        "COMMENT ON CONSTRAINT uq_load_batch_file_hash ON load_batch IS "
        "'A file is its bytes. The same SHA-256 cannot be loaded twice, "
        "regardless of filename (01-DATA-MODEL.md section 3).';"
    )

    # =================================================================
    # 6. Roles
    # =================================================================
    # app_rw is created without a password on purpose: under scram/md5 a
    # passwordless role cannot authenticate, so the role fails closed
    # until the owner sets a credential out of band (local .env) or binds
    # a Cloud SQL IAM user. A migration must never carry a password --
    # it would end up in git.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN;
                RAISE NOTICE 'T01: role {APP_ROLE} created with no password '
                             '(set one out of band before use)';
            END IF;
        END $$;
        """
    )
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    ALTER ROLE {role} NOSUPERUSER NOCREATEDB NOCREATEROLE
                                      NOINHERIT NOREPLICATION NOBYPASSRLS;
                END IF;
            EXCEPTION WHEN insufficient_privilege THEN
                -- Supabase's postgres login is not a superuser, so it cannot
                -- mention the SUPERUSER attribute. The role is created above
                -- without that attribute; the lock-down is already true.
                RAISE NOTICE 'T01: could not alter role {role} (needs superuser); continuing';
            END $$;
            """
        )
    # COMMENT ON ROLE needs superuser. A CI migrator with only CREATEROLE
    # must not fail the whole revision over a comment.
    op.execute(
        f"""
        DO $$
        BEGIN
            COMMENT ON ROLE {APP_ROLE} IS
                'API and ingest worker. Inserts facts, staging and audit; reads '
                'references; updates only load_batch status/counts. No DELETE, no DDL.';
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'T01: could not comment on role {APP_ROLE} (needs superuser); continuing';
        END $$;
        """
    )

    # =================================================================
    # 7. Privileges -- revoke everything, then grant the exact set
    # =================================================================
    # Revoking first makes the end state deterministic: it does not matter
    # what any earlier script or manual GRANT left behind.
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;

                EXECUTE format(
                    'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', '{role}');
                EXECUTE format(
                    'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', '{role}');
                EXECUTE format(
                    'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM %I', '{role}');
                EXECUTE format(
                    'REVOKE ALL ON SCHEMA public FROM %I', '{role}');
                EXECUTE format(
                    'REVOKE ALL ON DATABASE %I FROM %I',
                    current_database(), '{role}');

                -- connect + look up objects, but never create them
                EXECUTE format(
                    'GRANT CONNECT ON DATABASE %I TO %I',
                    current_database(), '{role}');
                EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', '{role}');
            END $$;
            """
        )

    # purge_stg_raw() deletes staging rows. It is not SECURITY DEFINER, so
    # it already cannot do more than its caller -- but EXECUTE on functions
    # is granted to PUBLIC by default, so revoke it explicitly rather than
    # relying on the DELETE revoke alone.
    op.execute(
        """
        DO $$
        DECLARE
            r record;
        BEGIN
            FOR r IN
                SELECT p.oid::regprocedure AS sig
                  FROM pg_proc p
                  JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'public' AND p.proname = 'purge_stg_raw'
            LOOP
                EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', r.sig);
                RAISE NOTICE 'T01: EXECUTE on % revoked from PUBLIC', r.sig;
            END LOOP;
        END $$;
        """
    )

    for role in APP_ROLES:
        _grant_app_privileges(role)

    # Nothing in public should be creatable by anyone but the owner.
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC;")

    # The two new tables start closed to everyone else.
    op.execute("REVOKE ALL ON audit_event FROM PUBLIC;")
    op.execute("REVOKE ALL ON app_user   FROM PUBLIC;")


def _grant_app_privileges(role: str) -> None:
    """The complete privilege set an application role may hold.

    Written as one guarded block per role so that a role which does not
    exist (e.g. a fresh database that never had ``wavescan_loader``) is
    skipped instead of failing the migration.
    """
    reference = ", ".join(REFERENCE_TABLES)
    append_only = ", ".join(APPEND_ONLY_TABLES)
    views = ", ".join(VIEWS)
    sequences = ", ".join(SEQUENCES)
    load_batch_cols = ", ".join(LOAD_BATCH_UPDATABLE_COLUMNS)
    zone_map_cols = ", ".join(PLANT_ZONE_MAP_UPDATABLE_COLUMNS)

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                RETURN;
            END IF;

            -- reference data: read only. The loader resolves spellings
            -- through these tables; it must never invent a colour or zone.
            GRANT SELECT ON {reference} TO {role};

            -- facts, staging and quarantine: append only.
            -- No UPDATE (a measurement is never rewritten in place) and
            -- no DELETE (evidence is never removed) -- ADR 0005.
            GRANT SELECT, INSERT ON {append_only} TO {role};

            -- load_batch: insert a batch, then only ever move its status,
            -- counts, timestamps, notes and supersede pointer.
            -- source_file / source_sheet / plant_code / file_hash /
            -- loaded_by are provenance and stay read-only after insert.
            GRANT SELECT, INSERT ON load_batch TO {role};
            GRANT UPDATE ({load_batch_cols}) ON load_batch TO {role};

            -- mapping proposals: the app records a human's decision.
            GRANT SELECT, INSERT ON ref_plant_zone_map TO {role};
            GRANT UPDATE ({zone_map_cols}) ON ref_plant_zone_map TO {role};

            -- audit: append only. No UPDATE, no DELETE, for any role.
            GRANT SELECT, INSERT ON audit_event TO {role};

            -- identities: readable so attribution can be resolved.
            -- INSERT is deliberately withheld until T04 implements the
            -- OIDC first-login flow that would need it.
            GRANT SELECT ON app_user TO {role};

            -- reporting views
            GRANT SELECT ON {views} TO {role};

            -- sequences behind the BIGSERIAL primary keys
            GRANT USAGE, SELECT ON SEQUENCE {sequences} TO {role};
        END $$;
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0001 is not reversible by design.\n"
        "\n"
        "A downgrade would have to re-grant DELETE on wavescan and load_batch, "
        "restore ON DELETE CASCADE to the evidence tables, and drop audit_event "
        "- that is, recreate every defect docs/03-SECURITY.md section 1 records, "
        "and destroy the audit history while doing it.\n"
        "\n"
        "docs/AGENTS.md section 4 lists 'enabling DELETE just for admin' as a "
        "defect, not a feature. If this revision has to be rolled back, restore "
        "the database from a backup and record why in an ADR."
    )
