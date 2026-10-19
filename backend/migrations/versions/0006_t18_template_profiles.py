"""T18: versioned template profiles and a persisted review projection.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-16

Four changes. Two new tables, two additive columns, and one rewrite of an
existing function -- and the last of those is the destructive one.

1. **`ref_template_profile`.** A plant layout, keyed by
   `(plant_code, template_fingerprint)` and versioned. It is **data, not
   code**: there is no column that holds SQL or Python, and the only
   behaviour it can switch on is `fill_missing_plant`. Design section 5.1
   forbids a profile from guessing a model, colour, zone or serial, from
   auto-applying similarity, or from disabling balance, dedup or referential
   checks -- so none of those are expressible here. A profile decides
   **whether a layout is known**, not what a value means; what a value means
   stays in the alias tables the cleaner is handed.

   `app_rw` gets **SELECT only**. Nothing in the application inserts a
   profile, and in particular the Admin mapping-approve route cannot: M6 says
   an approved header is not proof that a layout commits correctly, and the
   cheapest way to guarantee that is to give the application no grant to
   write the proof with. `fixture_verified` moves by seed, migration, or the
   owner -- the same three identities that can write any other reference row.

2. **`stg_review_row`.** What the worker decided about **every** source row,
   stored once per parse. `02-PIPELINE.md` section 7 already made review "a
   persisted proposal, not a dry-run reprint"; until now the dispositions
   were persisted (`reject_log`, `unidentified_model`, counts) but the
   *cleaned values* were not, so a reviewer could see that row 412 was
   rejected and not what row 412 would have become. Design section 6 wants
   raw and canonical side by side without re-parsing the workbook on every
   GET, and this is that table.

   It is **staging evidence, not `wavescan`**: `app_rw` holds `SELECT` and
   `INSERT` and nothing else. There is deliberately **no UPDATE**, because
   editing a proposed value in place is the "fix it in review" flow ADR 0005
   and M13 both refuse -- changing a proposed value means an approved mapping
   and a replay, or new bytes.

3. **`load_batch.profile_id` and `load_batch.review_revision`.** Which
   profile parsed the batch and the hash of the projection a person reviewed.
   Both are written by the worker after the parse, so both join the
   column-scoped UPDATE allow-list (`01-DATA-MODEL.md` section 8). Nothing
   else about `load_batch` changes; `plant_code` is still written at insert
   from T17's `expected_plant`.

4. **`reset_batch_staging(bigint)` also clears `stg_review_row`.**

   **This revision is destructive** in exactly the sense T08's was: it
   replaces a function whose purpose is to DELETE staging rows, and it widens
   what that function deletes. It needs the owner's explicit approval line
   when the owner commits (`AGENTS.md` section 2). Nothing in `upgrade()`
   itself deletes a row.

   The alternative was a `DELETE` grant on the projection for `app_rw`, which
   T18 is forbidden to add and which would have been the wrong shape anyway:
   the three guards that make the existing function safe -- batch exists,
   replayable status, **zero** `wavescan` rows -- are exactly the guards the
   projection needs, and they already exist inside it.

**Seeded profiles.** The fingerprints below were computed with
`domain/reader.describe_sheet` against the approved `ref_column_alias` rows
T02 seeds, from the read-only vault workbooks and from the synthetic template
the test suite generates. No workbook is copied into this repository
(`03-SECURITY.md` section 8); only its SHA-256 and its fingerprint are
recorded here.

* `AAT` and `FTM` on the canonical WaveScan fingerprint -- **verified**,
  because those layouts have produced the facts this platform already holds,
  and `fill_missing_plant`, which closes the leftover T17 recorded: a sheet
  of a known layout that simply omits the Plant column is now filled from
  `expected_plant` instead of being refused as an unknown template.
* `AAT` and `FTM` on the same layout **minus the Plant column** --
  verified, `fill_missing_plant`. Proved by the T18 suite rather than by a
  stored workbook, and the row says so.
* `SAP` on the canonical fingerprint -- **deliberately not verified**. SAP's
  June workbook has that layout, but its Serial No column is blank and
  `ref_plant.requires_serial` is true for SAP, so its rows have no vehicle
  identity. M7 forbids inventing one. The unverified profile is what makes
  SAP *visible and blocked with a reason* (design section 5.4) instead of
  silently unknown.
* **No FVL profile at all.** D5 is open, FVL is `is_active = false`, and a
  profile would be a claim this platform has not earned.

There is also an optional backfill: a distinct `(plant_code,
template_fingerprint)` already carried by a **COMMITTED** AAT or FTM batch is
inserted as verified, naming that batch's `file_hash` as its proof. Those
layouts have already produced measurements; refusing them now would strand
data that is already in `wavescan`.

`downgrade()` drops both tables and restores the T08 function. The projection
is re-derivable from stored bytes, so dropping it loses no evidence a replay
could not rebuild -- unlike 0005, which refuses to reverse once a correction
exists.
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

#: T08's three, plus the projection. Every one of them is re-derivable from
#: the bytes in the object store, which is what makes clearing them a replay
#: rather than a deletion of evidence.
STAGING_TABLES = ("stg_raw", "reject_log", "unidentified_model", "stg_review_row")

REPLAYABLE_STATUSES = ("REJECTED_TEMPLATE", "PENDING_REVIEW")

#: T03/T04's list, plus the two columns the worker now writes after a parse.
LOAD_BATCH_UPDATABLE_COLUMNS = (
    "status",
    "rows_in_file", "rows_loaded", "rows_duplicate",
    "rows_rejected", "rows_quarantine",
    "started_at", "finished_at",
    "notes",
    "superseded_by",
    "plant_code",
    "profile_id",
    "review_revision",
)

# ---------------------------------------------------------------------
# Fingerprints. Recomputed, not remembered: see this file's docstring and
# docs/reports/T18-PROFILES.md for how, and for the command that reproduces
# them from the vault.
# ---------------------------------------------------------------------
#: Date/Month/Year/Plant/Model/Checkzone/Color/Tolerance Group/Paintline/
#: Serial No + the eleven measures. The AAT and FTM June and July workbooks
#: and the suite's synthetic workbook all fingerprint to this.
CANONICAL = "5d0070137d0005adfd73f0f4ba2d7031c96e55c47fb7313f501a83811bf2e990"
#: The same layout with the Plant column removed.
NO_PLANT_COLUMN = "b5dcecdb85acf437c89e2e73f0e479e5ce1e08d0a627f6cb3b6e6595f39c946e"

#: SHA-256 of the vault workbooks that prove the canonical layout commits.
#: The files stay in the vault; only these digests are recorded.
AAT_JUNE = "faee439ffb0b9d56200bced414e8854104a5d36e28f17090844f6eb82f29c3d5"
FTM_JUNE = "88ef205c91dd8a41f1bc8eea92c41dcfbcca657cfd959c71d34a792bfb4bf211"

SEEDS = (
    # plant, fingerprint, verified, fixture hash, fill_missing_plant, notes
    ("AAT", CANONICAL, True, AAT_JUNE, True,
     "Canonical WaveScan layout. Proved by the vault AAT June 2026 workbook "
     "(sha256 named in fixture_file_hash, file not copied into this repo) and "
     "by backend/tests/test_t04_ingest.py, which commits this layout end to "
     "end. fill_missing_plant: a sheet of this layout that omits the Plant "
     "column is filled from expected_plant (T18 locked decision 6)."),
    ("FTM", CANONICAL, True, FTM_JUNE, True,
     "Canonical WaveScan layout. Proved by the vault FTM June 2026 workbook "
     "and the same suite as AAT."),
    ("AAT", NO_PLANT_COLUMN, True, None, True,
     "Canonical WaveScan layout minus the Plant column. Proved by "
     "backend/tests/test_t18_profiles.py, which uploads this layout as AAT "
     "and commits it with every row's plant filled from expected_plant. No "
     "stored workbook proves it, so fixture_file_hash is null on purpose."),
    ("FTM", NO_PLANT_COLUMN, True, None, True,
     "Canonical WaveScan layout minus the Plant column, FTM. Same proof as "
     "the AAT row."),
    ("SAP", CANONICAL, False, None, False,
     "SAP June 2026 has this layout, so the sheet is readable and reviewable "
     "-- and it is deliberately NOT fixture-verified. Its Serial No column is "
     "blank while ref_plant.requires_serial is true for SAP, so its rows have "
     "no vehicle identity, and M7 forbids generating one, using "
     "(file, sheet, source_row) as identity, or turning off dedup. Commit "
     "stays blocked with VEHICLE_IDENTITY_MISSING until the owner approves a "
     "SAP identity rule. This row is what makes SAP visible and blocked with "
     "a reason instead of silently unknown."),
)


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


def _quote(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


# =====================================================================
def upgrade() -> None:
    _ref_template_profile()
    _seed_profiles()
    _stg_review_row()
    _load_batch_columns()
    _reset_batch_staging()


# ---------------------------------------------------------------------
def _ref_template_profile() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref_template_profile (
            profile_id            bigserial PRIMARY KEY,
            plant_code            text NOT NULL
                                      REFERENCES ref_plant (plant_code)
                                      ON DELETE RESTRICT,
            template_fingerprint  text NOT NULL,
            version               integer NOT NULL DEFAULT 1,
            is_active             boolean NOT NULL DEFAULT true,
            fixture_verified      boolean NOT NULL DEFAULT false,
            fixture_file_hash     char(64),
            fill_missing_plant    boolean NOT NULL DEFAULT false,
            notes                 text,
            created_at            timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_profile_version
                UNIQUE (plant_code, template_fingerprint, version),
            CONSTRAINT ck_profile_version_positive CHECK (version >= 1),
            -- A layout that claims to be proven has to say what proved it.
            -- The hash is the better answer and is used where a stored
            -- workbook exists; where the proof is a test, `notes` names it.
            CONSTRAINT ck_profile_verified_is_evidenced
                CHECK (fixture_verified = false OR notes IS NOT NULL)
        )
        """
    )
    # "At most one active version per layout" is the whole selection rule, so
    # it is a database constraint rather than an ORDER BY in the service.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_profile_active "
        "ON ref_template_profile (plant_code, template_fingerprint) "
        "WHERE is_active"
    )
    op.execute(
        "COMMENT ON TABLE ref_template_profile IS "
        "'A plant layout, keyed by (plant_code, template_fingerprint) and "
        "versioned (T18, design section 5.1). Data only: no SQL, no Python, "
        "no guessing. fixture_verified means a fixture proved this layout "
        "commits correctly and is written by seed, migration or the owner -- "
        "never by the Admin mapping-approve route (M6).'"
    )
    op.execute("REVOKE ALL ON ref_template_profile FROM PUBLIC")
    _for_each_role(
        """
        -- SELECT only, on purpose: nothing in the application may write a
        -- profile, so no route can promote a layout to commit-capable.
        GRANT SELECT ON ref_template_profile TO {role};
        """
    )


def _seed_profiles() -> None:
    values = ",\n            ".join(
        f"({_quote(plant)}, {_quote(fp)}, 1, true, {str(verified).lower()}, "
        f"{_quote(fixture)}, {str(fill).lower()}, {_quote(note)})"
        for plant, fp, verified, fixture, fill, note in SEEDS
    )
    # `WHERE EXISTS` on ref_plant: a database that has not onboarded SAP is
    # not a database this migration may add a plant to.
    op.execute(
        f"""
        INSERT INTO ref_template_profile
            (plant_code, template_fingerprint, version, is_active,
             fixture_verified, fixture_file_hash, fill_missing_plant, notes)
        SELECT v.plant_code, v.fingerprint, v.version, v.is_active,
               v.verified, v.fixture_hash, v.fill_plant, v.notes
          FROM (VALUES
            {values}
          ) AS v (plant_code, fingerprint, version, is_active, verified,
                  fixture_hash, fill_plant, notes)
         WHERE EXISTS (SELECT 1 FROM ref_plant p WHERE p.plant_code = v.plant_code)
        ON CONFLICT ON CONSTRAINT uq_profile_version DO NOTHING
        """
    )

    # Optional backfill (T18 work item 1). A layout that has already produced
    # COMMITTED measurements for AAT or FTM is verified by the strongest proof
    # there is -- the facts it produced -- and refusing it now would strand
    # data that is already in `wavescan`. Restricted to those two plants:
    # SAP's identity rule is undecided and FVL is not onboarded.
    op.execute(
        """
        INSERT INTO ref_template_profile
            (plant_code, template_fingerprint, version, is_active,
             fixture_verified, fixture_file_hash, fill_missing_plant, notes)
        SELECT b.plant_code,
               b.template_fingerprint,
               1,
               true,
               true,
               min(b.file_hash),
               false,
               'Backfilled by revision 0006 from a COMMITTED batch of this '
               'layout: these bytes already produced measurements in wavescan, '
               'which is the proof fixture_verified asks for. '
               'fill_missing_plant is false because nothing proved that.'
          FROM load_batch b
         WHERE b.status = 'COMMITTED'
           AND b.plant_code IN ('AAT', 'FTM')
           AND b.template_fingerprint IS NOT NULL
           AND NOT EXISTS (
                   SELECT 1 FROM ref_template_profile p
                    WHERE p.plant_code = b.plant_code
                      AND p.template_fingerprint = b.template_fingerprint)
         GROUP BY b.plant_code, b.template_fingerprint
        """
    )


def _stg_review_row() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stg_review_row (
            load_id              bigint NOT NULL
                                     REFERENCES load_batch (load_id)
                                     ON DELETE RESTRICT,
            source_row           integer NOT NULL,
            disposition          text NOT NULL,
            reason               text,
            detail               text,
            canonical            jsonb NOT NULL,
            raw                  jsonb NOT NULL,
            normalized_fields    jsonb NOT NULL DEFAULT '[]'::jsonb,
            profile_id           bigint
                                     REFERENCES ref_template_profile (profile_id)
                                     ON DELETE RESTRICT,
            template_fingerprint text NOT NULL,
            review_revision      char(64) NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_stg_review_row PRIMARY KEY (load_id, source_row),
            CONSTRAINT ck_review_disposition
                CHECK (disposition IN ('LOAD','DUPLICATE','REJECT','QUARANTINE'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_row_disposition "
        "ON stg_review_row (load_id, disposition)"
    )
    op.execute(
        "COMMENT ON TABLE stg_review_row IS "
        "'One row per source row of one parse: what commit would insert "
        "(canonical), what the file said (raw), the disposition, and the "
        "review_revision that binds them together (T18, design section 6). "
        "Staging evidence, not wavescan: INSERT and SELECT only. There is no "
        "UPDATE by design -- changing a proposed value means an approved "
        "mapping and a replay, or new bytes (M13). Cleared only by "
        "reset_batch_staging.'"
    )
    op.execute("REVOKE ALL ON stg_review_row FROM PUBLIC")
    _for_each_role(
        """
        -- No UPDATE: a proposed value is never edited in review.
        -- No DELETE: replay clears it through reset_batch_staging.
        GRANT SELECT, INSERT ON stg_review_row TO {role};
        """
    )


def _load_batch_columns() -> None:
    op.execute(
        """
        ALTER TABLE load_batch
            ADD COLUMN IF NOT EXISTS profile_id bigint
                REFERENCES ref_template_profile (profile_id) ON DELETE RESTRICT,
            ADD COLUMN IF NOT EXISTS review_revision char(64)
        """
    )
    op.execute(
        "COMMENT ON COLUMN load_batch.profile_id IS "
        "'Which template profile parsed this batch. Null before T18 and on a "
        "batch whose layout has no active profile (those are "
        "REJECTED_TEMPLATE).'"
    )
    op.execute(
        "COMMENT ON COLUMN load_batch.review_revision IS "
        "'Hash of the projection a reviewer saw. commit_batch re-derives it "
        "from the stored bytes and refuses if it disagrees (T18).'"
    )
    columns = ", ".join(LOAD_BATCH_UPDATABLE_COLUMNS)
    _for_each_role(
        f"""
        REVOKE UPDATE ON load_batch FROM {{role}};
        GRANT UPDATE ({columns}) ON load_batch TO {{role}};
        """
    )


def _reset_batch_staging() -> None:
    """T08's function, now clearing the projection as well.

    Rewritten rather than extended in the service, because the guards belong
    in the same place as the deletes: the function is the only identity that
    can delete these rows, so it is the identity that has to refuse.
    """
    deletes = "\n".join(
        f"        DELETE FROM {table} WHERE load_id = p_load_id;\n"
        f"        GET DIAGNOSTICS v_n = ROW_COUNT;\n"
        f"        v_cleared := v_cleared || jsonb_build_object('{table}', v_n);"
        for table in STAGING_TABLES
    )
    quoted = ", ".join(f"'{s}'" for s in REPLAYABLE_STATUSES)
    listed = " or ".join(REPLAYABLE_STATUSES)

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
        "'Clear stg_raw/reject_log/unidentified_model/stg_review_row for ONE "
        "batch that has produced no wavescan rows, so it can be replayed from "
        "stored bytes (docs/02-PIPELINE.md section 8). Refuses otherwise. "
        "Cannot touch wavescan or load_batch. T08, widened by T18.'"
    )
    op.execute("REVOKE ALL ON FUNCTION reset_batch_staging(bigint) FROM PUBLIC")
    _for_each_role(
        "GRANT EXECUTE ON FUNCTION reset_batch_staging(bigint) TO {role};"
    )


# =====================================================================
def downgrade() -> None:
    """Reverse all four. Nothing here can lose a measurement.

    The projection is re-derivable from the bytes in the object store, so
    dropping it costs a replay rather than evidence -- which is why this one
    does not refuse the way 0005's downgrade does once a correction exists.
    """
    op.execute("DROP TABLE IF EXISTS stg_review_row")

    columns = ", ".join(
        c for c in LOAD_BATCH_UPDATABLE_COLUMNS
        if c not in ("profile_id", "review_revision")
    )
    _for_each_role(
        f"""
        REVOKE UPDATE ON load_batch FROM {{role}};
        GRANT UPDATE ({columns}) ON load_batch TO {{role}};
        """
    )
    op.execute(
        "ALTER TABLE load_batch "
        "DROP COLUMN IF EXISTS profile_id, "
        "DROP COLUMN IF EXISTS review_revision"
    )
    op.execute("DROP TABLE IF EXISTS ref_template_profile")

    # Back to T08's three tables.
    deletes = "\n".join(
        f"        DELETE FROM {table} WHERE load_id = p_load_id;\n"
        f"        GET DIAGNOSTICS v_n = ROW_COUNT;\n"
        f"        v_cleared := v_cleared || jsonb_build_object('{table}', v_n);"
        for table in ("stg_raw", "reject_log", "unidentified_model")
    )
    quoted = ", ".join(f"'{s}'" for s in REPLAYABLE_STATUSES)
    listed = " or ".join(REPLAYABLE_STATUSES)
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
            SELECT status INTO v_status FROM load_batch WHERE load_id = p_load_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'batch % does not exist', p_load_id
                    USING ERRCODE = 'no_data_found';
            END IF;
            SELECT count(*) INTO v_facts FROM wavescan WHERE load_id = p_load_id;
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
    op.execute("REVOKE ALL ON FUNCTION reset_batch_staging(bigint) FROM PUBLIC")
    _for_each_role(
        "GRANT EXECUTE ON FUNCTION reset_batch_staging(bigint) TO {role};"
    )
