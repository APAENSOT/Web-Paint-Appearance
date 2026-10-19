"""T02: migrate the demo schema to the target data model.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-08

Implements docs/tasks/T02-schema-migration.md against docs/01-DATA-MODEL.md.
Driver: psycopg3 via SQLAlchemy 2.x Core (recorded per the task's "pick one").
Every statement here is hand-written SQL -- Alembic cannot autogenerate the
data conversions, the grant changes, or the supersession trigger.

The three changes worth reading carefully
-----------------------------------------

1. **REAL -> NUMERIC on eleven measurement columns.** float4 carries about
   seven significant digits, so a gauge reading is silently rounded on the
   way in and can never be recovered. The cast goes through PostgreSQL's
   float4 -> numeric conversion, which produces the shortest decimal that
   round-trips the stored float, so no existing value is altered -- it is
   the *future* writes that stop losing precision. This is the destructive
   step the task flags for escalation; `downgrade()` below reverses it, but
   only after refusing if any value would not survive the trip back.

2. **`is_superseded` without granting UPDATE on `wavescan`.** T01's whole
   result is that the application cannot rewrite a measurement. A plain
   `is_superseded` flag would need an UPDATE grant and hand that back. So
   supersession is recorded in an append-only side table
   (`measurement_supersession`, which carries the reason and the actor) and
   an AFTER INSERT trigger maintains the flag. The trigger function is
   SECURITY DEFINER because the caller has no UPDATE on `wavescan` -- it is
   deliberately tiny, has a pinned `search_path`, takes no identifiers from
   the caller, and is revoked from PUBLIC. Net effect: the flag cannot move
   unless a row exists saying who moved it and why. This is
   01-DATA-MODEL.md section 5's "insert-only + side table is preferred".

3. **`load_batch.loaded_by` text -> uuid.** The old column held
   `current_user` (always the pool role, never a person). Rather than drop
   it, it is renamed to `loaded_by_role_legacy`; a system whose thesis is
   "never destroy evidence" should not start by destroying a column. See
   the report for why this deviates from the documented column list.

Preconditions
-------------
`file_hash` becomes `char(64) NOT NULL`. A batch with no hash cannot be
given one -- the bytes are gone -- and inventing one would assert a false
file identity in a table whose entire job is file identity. So the
migration stops and names the offending batches instead, the same stance
0001 takes on duplicate hashes.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


APP_ROLES = ("app_rw", "wavescan_loader")

MEASURE_COLUMNS = ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b")

# 04-ANALYSIS.md section 3 / Prototype.html COLOR_FAMILY_ORDER (1807-1814).
COLOR_FAMILIES = [
    "Light Metallics", "Medium Metallics", "Dark Metallics",
    "Light Solids", "Medium Solids", "Dark Solids",
]

# 04-ANALYSIS.md section 3 / Prototype.html DEFAULT_STANDARDS (1798-1805).
# family -> (fordH, fordV, minH, minV)
DEFAULT_STANDARDS = {
    "Light Metallics":  (57, 44, 50, 37),
    "Medium Metallics": (60, 47, 53, 40),
    "Dark Metallics":   (62, 49, 55, 42),
    "Light Solids":     (62, 49, 55, 42),
    "Medium Solids":    (65, 52, 58, 45),
    "Dark Solids":      (67, 54, 60, 47),
}

STANDARD_SOURCE_NOTE = (
    "prototype DEFAULT_STANDARDS; Color Family - IMG Plants document"
)
# The standards predate every measurement in scope; wavescan's own date CHECK
# starts at 2000-01-01, so that is the earliest meaningful "in force since".
# The real effective date arrives with the IMG Plants document (D2).
STANDARD_EFFECTIVE_FROM = "2000-01-01"

# reader.py:24-46 HEADER_ALIASES. Ported, not retyped from memory
# (docs/AGENTS.md rule 4). Normalisation is lower / trim / '_' -> ' ',
# which these spellings already satisfy.
HEADER_ALIASES = {
    "date": ["date", "painted date", "paint date", "measured date"],
    "month": ["month"],
    "year": ["year"],
    "plant": ["plant"],
    "model": ["model"],
    "checkzone": ["checkzone", "check zone", "zone"],
    "color": ["color", "colour"],
    "tolerance_group": ["tolerance group", "tolerancegroup", "tolerance"],
    "paintline": ["paintline", "paint line", "booth"],
    "serial_no": ["serial no", "serial no.", "serialno", "serial number", "serial"],
    "lw": ["lw"], "sw": ["sw"], "cf": ["cf"], "doi": ["doi"], "du": ["du"],
    "wa": ["wa"], "wb": ["wb"], "wc": ["wc"], "wd": ["wd"], "we": ["we"],
    "b": ["b"],
}

FACT_VIEWS = (
    "v_wavescan", "v_wavescan_p703", "v_wavescan_u704",
    "v_car_completeness", "v_load_summary", "v_wavescan_active",
)


def _sql_str(value: str) -> str:
    """Single-quote a literal for embedding in generated DDL."""
    return "'" + value.replace("'", "''") + "'"


# =====================================================================
def upgrade() -> None:
    _preflight()
    # Every reporting view reads columns whose type changes below, and
    # PostgreSQL refuses to alter a column a view depends on. They are all
    # rebuilt in _views() against the new shape.
    _drop_dependent_views()
    _load_batch()
    _stg_raw()
    _wavescan()
    _quarantine()
    _new_tables()
    _supersession()
    _seeds()
    _purge_function()
    _views()
    _grants()


# ---------------------------------------------------------------------
def _preflight() -> None:
    """Refuse rather than fabricate. Mirrors 0001's duplicate-hash guard."""
    op.execute(
        """
        DO $$
        DECLARE
            v_ids text;
        BEGIN
            SELECT string_agg(load_id::text || ' (' || source_file || ')', ', '
                              ORDER BY load_id)
              INTO v_ids
              FROM load_batch WHERE file_hash IS NULL;

            IF v_ids IS NOT NULL THEN
                RAISE EXCEPTION
                    'T02 precondition failed: load_batch rows with no file_hash.%',
                    E'\\n  load_ids: ' || v_ids || E'\\n' ||
                    'file_hash becomes char(64) NOT NULL: a file is its bytes ' ||
                    '(01-DATA-MODEL.md principle 3). These rows cannot be given a ' ||
                    'hash after the fact, and inventing one would assert a file ' ||
                    'identity that is not true.' || E'\\n' ||
                    'Decide per batch, then re-run:' || E'\\n' ||
                    '  - real upload whose bytes still exist: set the true SHA-256;' || E'\\n' ||
                    '  - seed/demo row: give it a documented sentinel, e.g.' || E'\\n' ||
                    '      UPDATE load_batch SET file_hash = ' ||
                    'repeat(''0'',64) WHERE load_id = <id>;' || E'\\n' ||
                    '  - obsolete: status = ''SUPERSEDED'' does not exempt it; it ' ||
                    'still needs a hash or a deliberate sentinel.';
            END IF;
        END $$;
        """
    )
    # wavescan's key becomes (load_id, source_row). The demo key was
    # (source_file, source_sheet, source_row), which allowed one batch to
    # hold rows from SEVERAL files as long as the filenames differed -- and
    # the demo seed does exactly that. A real load cannot: the loader opens
    # one (file, sheet) per batch and source_row is that sheet's row number.
    # So a collision here means the batch does not describe a single upload,
    # and picking a winner would silently destroy one file's provenance.
    op.execute(
        """
        DO $$
        DECLARE
            v_groups bigint;
            v_detail text;
            v_mixed  text;
        BEGIN
            SELECT count(*) INTO v_groups FROM (
                SELECT 1 FROM wavescan GROUP BY load_id, source_row HAVING count(*) > 1
            ) x;

            IF v_groups = 0 THEN RETURN; END IF;

            SELECT string_agg(format('    load_id %s, source_row %s -> %s rows',
                                     load_id, source_row, n), E'\\n')
              INTO v_detail
              FROM (SELECT load_id, source_row, count(*) AS n
                      FROM wavescan GROUP BY load_id, source_row
                    HAVING count(*) > 1
                     ORDER BY load_id, source_row LIMIT 5) s;

            SELECT string_agg(format('    load_id %s spans %s source files: %s',
                                     load_id, nfiles, files), E'\\n')
              INTO v_mixed
              FROM (SELECT load_id, count(DISTINCT source_file) AS nfiles,
                           string_agg(DISTINCT source_file, ', ') AS files
                      FROM wavescan GROUP BY load_id
                    HAVING count(DISTINCT source_file) > 1) m;

            RAISE EXCEPTION
                'T02 precondition failed: wavescan rows collide on (load_id, source_row).%',
                format(E'\\n  %s colliding group(s); first few:\\n%s\\n', v_groups, v_detail) ||
                COALESCE(E'  Cause:\\n' || v_mixed || E'\\n', '') ||
                E'  A load_batch describes ONE uploaded sheet (01-DATA-MODEL.md ' ||
                E'section 3), so source_row is unique within it. A batch holding ' ||
                E'rows from several files is not a real upload -- the demo seed ' ||
                E'06_demo_data.sql builds one like this on purpose.\\n' ||
                E'  Split the batch so each source file has its own load_batch row, ' ||
                E'then re-run. Do not renumber source_row: it is the spreadsheet ' ||
                E'coordinate a value is traced back to.';
        END $$;
        """
    )

    # Any status outside the union of old and new vocabularies means someone
    # has been writing free text; the rename below would silently keep it.
    op.execute(
        """
        DO $$
        DECLARE
            v_bad text;
        BEGIN
            SELECT string_agg(DISTINCT status, ', ') INTO v_bad
              FROM load_batch
             WHERE status NOT IN ('RUNNING','SUCCESS','FAILED','ROLLED_BACK',
                                  'PENDING_REVIEW','COMMITTED','SUPERSEDED',
                                  'REJECTED_TEMPLATE');
            IF v_bad IS NOT NULL THEN
                RAISE EXCEPTION
                    'T02 precondition failed: unrecognised load_batch.status values: %',
                    v_bad;
            END IF;
        END $$;
        """
    )


# ---------------------------------------------------------------------
def _load_batch() -> None:
    """01-DATA-MODEL.md section 3."""
    # Status vocabulary: rename the data BEFORE tightening the CHECK.
    op.execute("ALTER TABLE load_batch DROP CONSTRAINT IF EXISTS ck_batch_status")
    op.execute("ALTER TABLE load_batch DROP CONSTRAINT IF EXISTS ck_batch_balance")

    op.execute("UPDATE load_batch SET status = 'COMMITTED' WHERE status = 'SUCCESS'")
    # ROLLED_BACK is retired: 'FAILED' plus inspectable staging replaces it.
    op.execute("UPDATE load_batch SET status = 'FAILED' WHERE status = 'ROLLED_BACK'")

    op.execute(
        """
        ALTER TABLE load_batch ADD CONSTRAINT ck_batch_status CHECK (
            status IN ('RUNNING','PENDING_REVIEW','COMMITTED',
                       'FAILED','SUPERSEDED','REJECTED_TEMPLATE')
        )
        """
    )
    op.execute(
        """
        ALTER TABLE load_batch ADD CONSTRAINT ck_batch_balance CHECK (
            status <> 'COMMITTED'
            OR rows_in_file = rows_loaded + rows_duplicate
                            + rows_rejected + rows_quarantine
        )
        """
    )
    op.execute(
        "COMMENT ON CONSTRAINT ck_batch_balance ON load_batch IS "
        "'A committed load must account for every row: loaded + duplicate + "
        "rejected + quarantined.'"
    )

    # file_hash: the reload guard becomes a real identity column.
    op.execute("ALTER TABLE load_batch ALTER COLUMN file_hash TYPE char(64)")
    op.execute("ALTER TABLE load_batch ALTER COLUMN file_hash SET NOT NULL")

    # raw_store_key: object-store path. The hash IS the path (section 3).
    op.execute("ALTER TABLE load_batch ADD COLUMN IF NOT EXISTS raw_store_key text")
    op.execute(
        "UPDATE load_batch SET raw_store_key = 'wavescan/raw/' || file_hash "
        "WHERE raw_store_key IS NULL"
    )
    op.execute("ALTER TABLE load_batch ALTER COLUMN raw_store_key SET NOT NULL")

    op.execute(
        "ALTER TABLE load_batch ADD COLUMN IF NOT EXISTS template_fingerprint text"
    )
    op.execute("ALTER TABLE load_batch ADD COLUMN IF NOT EXISTS raw_headers jsonb")

    # loaded_by: role name -> person. The old value is preserved rather than
    # dropped; see the module docstring.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='load_batch'
                          AND column_name='loaded_by' AND data_type <> 'uuid') THEN
                ALTER TABLE load_batch RENAME COLUMN loaded_by TO loaded_by_role_legacy;
                ALTER TABLE load_batch ALTER COLUMN loaded_by_role_legacy DROP NOT NULL;
                ALTER TABLE load_batch ALTER COLUMN loaded_by_role_legacy DROP DEFAULT;
                ALTER TABLE load_batch ADD COLUMN loaded_by uuid REFERENCES app_user;
            END IF;
        END $$;
        """
    )
    op.execute(
        "COMMENT ON COLUMN load_batch.loaded_by_role_legacy IS "
        "'Pre-T02 value of loaded_by: the database ROLE that ran the load "
        "(always the pool role, never a person). Kept so no attribution data is "
        "destroyed; superseded by loaded_by. Safe to drop once the owner confirms.'"
    )
    op.execute(
        "COMMENT ON COLUMN load_batch.loaded_by IS "
        "'The authenticated person who uploaded this batch (01-DATA-MODEL.md "
        "principle 7). NULL for batches loaded before authentication existed.'"
    )

    # Principle 8: four plants, three time zones.
    for column in ("started_at", "finished_at"):
        op.execute(
            f"ALTER TABLE load_batch ALTER COLUMN {column} TYPE timestamptz "
            f"USING {column} AT TIME ZONE current_setting('TimeZone')"
        )
    op.execute("ALTER TABLE load_batch ALTER COLUMN started_at SET DEFAULT now()")


# ---------------------------------------------------------------------
def _stg_raw() -> None:
    """Section 4: nothing a file said is lost, even without an alias."""
    op.execute(
        "ALTER TABLE stg_raw ADD COLUMN IF NOT EXISTS extra jsonb "
        "NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute("ALTER TABLE stg_raw ADD COLUMN IF NOT EXISTS raw_headers jsonb")
    op.execute(
        "COMMENT ON COLUMN stg_raw.extra IS "
        "'Unmapped header -> value. A template column with no ref_column_alias "
        "lands here rather than being dropped.'"
    )
    op.execute(
        "ALTER TABLE stg_raw ALTER COLUMN ingested_at TYPE timestamptz "
        "USING ingested_at AT TIME ZONE current_setting('TimeZone')"
    )
    op.execute("ALTER TABLE stg_raw ALTER COLUMN ingested_at SET DEFAULT now()")


# ---------------------------------------------------------------------
def _drop_dependent_views() -> None:
    for view in ("v_car_completeness", "v_load_summary", "v_wavescan_u704",
                 "v_wavescan_p703", "v_wavescan", "v_wavescan_active"):
        op.execute(f"DROP VIEW IF EXISTS {view} CASCADE")


def _wavescan() -> None:
    """Section 5. Views were dropped in _drop_dependent_views()."""
    # Principle 9: full precision in the fact table, forever.
    for column in MEASURE_COLUMNS:
        op.execute(
            f"ALTER TABLE wavescan ALTER COLUMN {column} TYPE numeric "
            f"USING {column}::numeric"
        )

    op.execute(
        "ALTER TABLE wavescan ADD COLUMN IF NOT EXISTS is_superseded boolean "
        "NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE wavescan ADD COLUMN IF NOT EXISTS corrects_measurement_id "
        "bigint REFERENCES wavescan (measurement_id)"
    )
    op.execute("ALTER TABLE wavescan ADD COLUMN IF NOT EXISTS correction_reason text")
    op.execute(
        "ALTER TABLE wavescan ADD COLUMN IF NOT EXISTS corrected_by "
        "uuid REFERENCES app_user"
    )
    op.execute("ALTER TABLE wavescan ADD COLUMN IF NOT EXISTS corrected_at timestamptz")

    op.execute(
        "ALTER TABLE wavescan ALTER COLUMN loaded_at TYPE timestamptz "
        "USING loaded_at AT TIME ZONE current_setting('TimeZone')"
    )
    op.execute("ALTER TABLE wavescan ALTER COLUMN loaded_at SET DEFAULT now()")

    # Identity is (batch, row), not (filename, sheet, row): two plants both
    # sending June.xlsx must not collide.
    op.execute("ALTER TABLE wavescan DROP CONSTRAINT IF EXISTS uq_ws_source")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                            WHERE conname='uq_ws_load_row'
                              AND conrelid='wavescan'::regclass) THEN
                ALTER TABLE wavescan
                    ADD CONSTRAINT uq_ws_load_row UNIQUE (load_id, source_row);
            END IF;
        END $$;
        """
    )
    # source_file is fully derivable from load_batch via load_id.
    op.execute("ALTER TABLE wavescan DROP COLUMN IF EXISTS source_file")

    op.execute(
        "COMMENT ON COLUMN wavescan.is_superseded IS "
        "'Set only by the measurement_supersession trigger. The application has "
        "no UPDATE on this table (T01).'"
    )
    op.execute(
        "COMMENT ON COLUMN wavescan.corrects_measurement_id IS "
        "'This row is a correction of that measurement. Set at INSERT time; the "
        "original is retired through measurement_supersession.'"
    )


# ---------------------------------------------------------------------
def _quarantine() -> None:
    """Section 7: reject reasons extended for template/header problems."""
    op.execute("ALTER TABLE reject_log DROP CONSTRAINT IF EXISTS ck_reject_reason")
    op.execute(
        """
        ALTER TABLE reject_log ADD CONSTRAINT ck_reject_reason CHECK (
            reject_reason IN (
                'UNKNOWN_PLANT','UNKNOWN_MODEL','UNKNOWN_CHECKZONE','UNKNOWN_COLOR',
                'UNKNOWN_PAINTLINE','ZONE_NOT_VALID_FOR_MODEL','MISSING_MEASUREMENT',
                'MISSING_REQUIRED_FIELD','BAD_DATE','BAD_NUMBER','OUT_OF_RANGE',
                'DUPLICATE_ROW','OTHER',
                'TEMPLATE_UNKNOWN','HEADER_AMBIGUOUS','UNMAPPED_COLUMN'
            )
        )
        """
    )
    for table, columns in (
        ("reject_log", ("reviewed_at", "created_at")),
        ("unidentified_model", ("reviewed_at", "created_at")),
        ("ref_plant_zone_map", ("approved_at", "created_at")),
    ):
        for column in columns:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
                f"USING {column} AT TIME ZONE current_setting('TimeZone')"
            )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now()")


# ---------------------------------------------------------------------
def _new_tables() -> None:
    # 6.3 -- replaces reader.py's HEADER_ALIASES dict.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref_column_alias (
            id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            raw_header     text        NOT NULL,
            logical_field  text        NOT NULL,
            is_approved    boolean     NOT NULL DEFAULT false,
            proposed_by    uuid        REFERENCES app_user,
            approved_by    uuid        REFERENCES app_user,
            created_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_column_alias_raw_header UNIQUE (raw_header)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_column_alias IS "
        "'Header spelling -> logical field. A new spelling is an approved INSERT, "
        "not a deploy. Normalised: lower, trim, underscore to space.'"
    )

    # 6.4
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref_color_family (
            family_name    text     PRIMARY KEY,
            display_order  smallint NOT NULL,
            CONSTRAINT uq_color_family_order UNIQUE (display_order)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_color_family IS "
        "'The six CF grading families. Display order from Prototype.html "
        "COLOR_FAMILY_ORDER. NOT the same axis as ref_color.color_group.'"
    )

    # 6.5 -- D2 is open, so this stays NULL for every colour.
    op.execute(
        "ALTER TABLE ref_color ADD COLUMN IF NOT EXISTS grading_family text "
        "REFERENCES ref_color_family"
    )
    op.execute(
        "COMMENT ON COLUMN ref_color.grading_family IS "
        "'CF grading family. NULL until D2 is resolved: a colour with no family "
        "cannot be graded, and guessing one produces a wrong grade silently. "
        "color_group (hue) is display grouping and is NOT this.'"
    )

    # 6.6
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cf_standard (
            id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            scope            text        NOT NULL CHECK (scope IN ('FAMILY','COLOR')),
            family_name      text        REFERENCES ref_color_family,
            color_name       text        REFERENCES ref_color,
            orient           char(1)     NOT NULL CHECK (orient IN ('H','V')),
            ford             numeric     NOT NULL,
            min              numeric     NOT NULL,
            effective_from   date        NOT NULL,
            source_document  text,
            source_note      text        NOT NULL,
            created_by       uuid        REFERENCES app_user,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_cf_standard_scope CHECK (
                (scope = 'FAMILY' AND family_name IS NOT NULL AND color_name IS NULL)
                OR (scope = 'COLOR' AND color_name IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE cf_standard IS "
        "'Ford/Min CF targets. Never updated in place - a standards change is a "
        "new row, so history re-grades. The only home for thresholds: SQL "
        "elsewhere contains none (04-ANALYSIS.md section 8).'"
    )

    # 6.7
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS proposed_mapping (
            id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            kind            text        NOT NULL CHECK (kind IN (
                                'COLUMN','ZONE','ALIAS_COLOR','ALIAS_MODEL',
                                'ALIAS_PLANT','ALIAS_CHECKZONE','ALIAS_PAINTLINE')),
            payload         jsonb       NOT NULL,
            load_id         bigint      REFERENCES load_batch ON DELETE RESTRICT,
            status          text        NOT NULL DEFAULT 'PROPOSED'
                                        CHECK (status IN ('PROPOSED','APPROVED','REJECTED')),
            similarity      numeric,
            proposed_by     uuid        REFERENCES app_user,
            decided_by      uuid        REFERENCES app_user,
            created_at      timestamptz NOT NULL DEFAULT now(),
            decided_at      timestamptz
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN proposed_mapping.similarity IS "
        "'Advisory score only. Never auto-applied - a human approves.'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposed_mapping_pending "
        "ON proposed_mapping (status) WHERE status = 'PROPOSED'"
    )


# ---------------------------------------------------------------------
def _supersession() -> None:
    """Insert-only wavescan + append-only side table (section 5)."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS measurement_supersession (
            id                           bigserial   PRIMARY KEY,
            superseded_measurement_id    bigint      NOT NULL
                                         REFERENCES wavescan (measurement_id)
                                         ON DELETE RESTRICT,
            superseded_by_measurement_id bigint
                                         REFERENCES wavescan (measurement_id)
                                         ON DELETE RESTRICT,
            reason                       text        NOT NULL,
            actor_user_id                uuid        REFERENCES app_user,
            occurred_at                  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_supersession_once UNIQUE (superseded_measurement_id),
            CONSTRAINT ck_supersession_not_self CHECK (
                superseded_by_measurement_id IS NULL
                OR superseded_by_measurement_id <> superseded_measurement_id
            ),
            CONSTRAINT ck_supersession_reason CHECK (length(btrim(reason)) > 0)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE measurement_supersession IS "
        "'Append-only record retiring a measurement. Insert here instead of "
        "updating wavescan: the reason and actor are mandatory, and the trigger "
        "below maintains wavescan.is_superseded.'"
    )

    # SECURITY DEFINER because the caller intentionally has no UPDATE on
    # wavescan. Kept minimal and non-parameterised: fixed search_path, no
    # dynamic SQL, no caller-supplied identifiers, revoked from PUBLIC.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION mark_measurement_superseded()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            UPDATE public.wavescan
               SET is_superseded = true
             WHERE measurement_id = NEW.superseded_measurement_id;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION mark_measurement_superseded() FROM PUBLIC")
    op.execute(
        "COMMENT ON FUNCTION mark_measurement_superseded() IS "
        "'Trigger-only. SECURITY DEFINER so the application can retire a "
        "measurement without holding UPDATE on wavescan. Sets one boolean on the "
        "row named by the new supersession record and nothing else.'"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_mark_superseded ON measurement_supersession")
    op.execute(
        """
        CREATE TRIGGER trg_mark_superseded
        AFTER INSERT ON measurement_supersession
        FOR EACH ROW EXECUTE FUNCTION mark_measurement_superseded()
        """
    )

    # The flag above is only trustworthy if the side table is the ONLY way it
    # can become true. UPDATE is already impossible for the application (T01),
    # but INSERT was not: a caller could write a fact that arrives already
    # superseded, and every reporting view would hide it with no record of who
    # hid it or why. Refuse that at the door rather than silently coercing the
    # value, so a caller doing it by accident finds out.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_presuperseded_measurement()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            RAISE EXCEPTION
                'wavescan.is_superseded cannot be set when the row is inserted'
                USING ERRCODE = 'check_violation',
                DETAIL = 'A measurement is retired by inserting into '
                    'measurement_supersession, which records the reason and the '
                    'actor and then sets the flag. A row inserted with '
                    'is_superseded = true is invisible to every reporting view '
                    'with no evidence attached (01-DATA-MODEL.md principles 1 '
                    'and 6, section 5).',
                HINT = 'Insert the measurement, then insert the supersession '
                    'record naming the reason and the actor.';
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION reject_presuperseded_measurement() FROM PUBLIC")
    op.execute("DROP TRIGGER IF EXISTS trg_reject_presuperseded ON wavescan")
    op.execute(
        """
        CREATE TRIGGER trg_reject_presuperseded
        BEFORE INSERT ON wavescan
        FOR EACH ROW WHEN (NEW.is_superseded)
        EXECUTE FUNCTION reject_presuperseded_measurement()
        """
    )


# ---------------------------------------------------------------------
def _seeds() -> None:
    # ref_color_family -- six rows, prototype order.
    values = ", ".join(
        f"({_sql_str(name)}, {i})" for i, name in enumerate(COLOR_FAMILIES, start=1)
    )
    op.execute(
        f"INSERT INTO ref_color_family (family_name, display_order) VALUES {values} "
        f"ON CONFLICT (family_name) DO NOTHING"
    )

    # cf_standard -- six families x H/V, version 1.
    rows = []
    for family, (ford_h, ford_v, min_h, min_v) in DEFAULT_STANDARDS.items():
        for orient, ford, minimum in (("H", ford_h, min_h), ("V", ford_v, min_v)):
            rows.append(
                f"('FAMILY', {_sql_str(family)}, {_sql_str(orient)}, {ford}, "
                f"{minimum}, DATE {_sql_str(STANDARD_EFFECTIVE_FROM)}, "
                f"{_sql_str(STANDARD_SOURCE_NOTE)})"
            )
    op.execute(
        "INSERT INTO cf_standard (scope, family_name, orient, ford, min, "
        "effective_from, source_note)\nSELECT * FROM (VALUES\n  "
        + ",\n  ".join(rows)
        + "\n) AS v(scope, family_name, orient, ford, min, effective_from, source_note)\n"
        "WHERE NOT EXISTS (SELECT 1 FROM cf_standard)"
    )

    # ref_column_alias -- seeded approved from reader.py.
    alias_rows = []
    for logical, raws in HEADER_ALIASES.items():
        for raw in raws:
            alias_rows.append(f"({_sql_str(raw)}, {_sql_str(logical)}, true)")
    op.execute(
        "INSERT INTO ref_column_alias (raw_header, logical_field, is_approved) "
        "VALUES " + ", ".join(alias_rows) + " ON CONFLICT (raw_header) DO NOTHING"
    )

    # T02 step 6: every in-scope plant is a row here, even where loads are
    # deferred, so an alias or zone mapping has something to reference.
    #
    # SAP normally arrives with baseline 13_sap_plant.sql, but revision 0000
    # ADOPTS an already-provisioned database instead of applying the baseline
    # to it. On that path SAP would be missing, so seed it here too, with the
    # values that file uses -- plant_name 'SAP' and country NULL, because
    # nothing in the source material states what SAP stands for or where it is.
    op.execute(
        """
        INSERT INTO ref_plant (plant_code, plant_name, country, requires_serial)
        VALUES ('SAP', 'SAP', NULL, true)
        ON CONFLICT (plant_code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO ref_plant_alias (raw_value, plant_code)
        VALUES ('SAP', 'SAP')
        ON CONFLICT (raw_value) DO NOTHING
        """
    )

    # FVL: present but inactive (D5). plant_name is NOT invented here -- the
    # source material never states it (the frontend mock says "Hai Duong
    # Plant", a PELT report title says "Ford Vietnam"; neither is confirmed),
    # and reference data that a dashboard displays as fact is the wrong place
    # to guess (docs/AGENTS.md rule 6). Same stance 13_sap_plant.sql took.
    op.execute(
        """
        INSERT INTO ref_plant (plant_code, plant_name, country, is_active)
        VALUES ('FVL', 'FVL', NULL, false)
        ON CONFLICT (plant_code) DO NOTHING
        """
    )
    # requires_serial defaults to true, which is wrong for FVL and would make
    # the loader reject every FVL row the day D5 opens: FVL's export does not
    # populate Serial No. at all (11_plant_zone_map.sql, measured 1504/1504
    # rows blank in the July file). Guarded because the column arrives with
    # that baseline file, which the adopt path does not apply.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='ref_plant'
                          AND column_name='requires_serial') THEN
                UPDATE ref_plant SET requires_serial = false
                 WHERE plant_code = 'FVL';
            END IF;
        END $$;
        """
    )
    # No ref_plant_alias row for FVL: an alias is what makes an uploaded file
    # resolve to a plant, and FVL uploads are not accepted until D5.
    op.execute(
        "COMMENT ON TABLE ref_plant IS "
        "'Plants in scope. FVL is present but is_active=false: investigation-only "
        "until D5 (no Serial/Paintline, different zone numbering).'"
    )


# ---------------------------------------------------------------------
def _purge_function() -> None:
    """The retention job filtered status='SUCCESS', which no longer exists."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION purge_stg_raw(p_months INTEGER DEFAULT 6)
        RETURNS TABLE (batches_purged BIGINT, rows_purged BIGINT)
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_batches BIGINT;
            v_rows    BIGINT;
        BEGIN
            SELECT count(*) INTO v_rows
            FROM stg_raw s
            JOIN load_batch b ON b.load_id = s.load_id
            WHERE b.status = 'COMMITTED'
              AND b.finished_at < now() - make_interval(months => p_months);

            WITH doomed AS (
                SELECT load_id FROM load_batch
                WHERE status = 'COMMITTED'
                  AND finished_at < now() - make_interval(months => p_months)
            ), zapped AS (
                DELETE FROM stg_raw WHERE load_id IN (SELECT load_id FROM doomed)
                RETURNING load_id
            )
            SELECT count(DISTINCT load_id) INTO v_batches FROM zapped;

            RETURN QUERY SELECT COALESCE(v_batches,0), COALESCE(v_rows,0);
        END;
        $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION purge_stg_raw IS "
        "'Delete staging rows for COMMITTED batches older than N months "
        "(default 6). load_batch is kept forever. Retention policy is D4.'"
    )
    # T01 revoked this from PUBLIC; CREATE OR REPLACE keeps the ACL, but be
    # explicit so a fresh database gets the same posture.
    op.execute("REVOKE ALL ON FUNCTION purge_stg_raw(INTEGER) FROM PUBLIC")


# ---------------------------------------------------------------------
def _views() -> None:
    """Section 10: ONE place implements the active-data predicate."""
    op.execute("DROP VIEW IF EXISTS v_wavescan_active CASCADE")
    op.execute(
        """
        CREATE VIEW v_wavescan_active AS
        SELECT w.*
        FROM wavescan w
        JOIN load_batch b ON b.load_id = w.load_id
        WHERE w.is_duplicate  = false
          AND w.is_superseded = false
          AND b.status = 'COMMITTED'
        """
    )
    op.execute(
        "COMMENT ON VIEW v_wavescan_active IS "
        "'THE active-data predicate (01-DATA-MODEL.md section 10): not a "
        "duplicate, not superseded, batch committed. Every reporting view and "
        "list endpoint reads through this. Querying wavescan directly and "
        "re-implementing the filter is a correctness bug even when the output "
        "happens to match.'"
    )

    op.execute(
        """
        CREATE VIEW v_wavescan AS
        SELECT
            measured_date    AS "Date",
            month            AS "Month",
            year             AS "Year",
            plant            AS "Plant",
            model            AS "Model",
            checkzone        AS "Checkzone",
            color            AS "Color",
            tolerance_group  AS "Tolerance Group",
            paintline        AS "Paintline",
            serial_no        AS "Serial No",
            lw               AS "LW",
            sw               AS "SW",
            cf               AS "CF",
            doi              AS "DOI",
            du               AS "du",
            wa               AS "Wa",
            wb               AS "Wb",
            wc               AS "Wc",
            wd               AS "Wd",
            we               AS "We",
            b                AS "B"
        FROM v_wavescan_active
        """
    )
    op.execute(
        "COMMENT ON VIEW v_wavescan IS "
        "'The 21 template columns in template order with original labels, "
        "active rows only. Read this, not the base table.'"
    )

    op.execute(
        "CREATE VIEW v_wavescan_p703 AS SELECT * FROM v_wavescan_active "
        "WHERE model LIKE 'P703%'"
    )
    op.execute(
        "COMMENT ON VIEW v_wavescan_p703 IS 'P703 pickups (32 zones), active rows only.'"
    )
    op.execute(
        "CREATE VIEW v_wavescan_u704 AS SELECT * FROM v_wavescan_active "
        "WHERE model = 'U704'"
    )
    op.execute(
        "COMMENT ON VIEW v_wavescan_u704 IS 'U704 SUVs (31 zones), active rows only.'"
    )

    op.execute(
        """
        CREATE VIEW v_car_completeness AS
        SELECT
            w.plant,
            w.serial_no,
            w.model,
            w.measured_date,
            count(*)                         AS zones_recorded,
            m.expected_zone_count            AS zones_expected,
            m.expected_zone_count - count(*) AS zones_missing,
            CASE
                WHEN count(*) = m.expected_zone_count THEN 'COMPLETE'
                WHEN count(*) <  m.expected_zone_count THEN 'INCOMPLETE'
                ELSE 'EXCESS'
            END                              AS completeness
        FROM v_wavescan_active w
        JOIN ref_model m ON m.model_code = w.model
        GROUP BY w.plant, w.serial_no, w.model, w.measured_date, m.expected_zone_count
        """
    )
    op.execute(
        "COMMENT ON VIEW v_car_completeness IS "
        "'Per-vehicle zone count vs expected (P703=32, U704=31), active rows only.'"
    )

    # Load monitoring covers every batch by design -- a FAILED or
    # PENDING_REVIEW batch is exactly what an operator needs to see, so this
    # view does NOT apply the active-data predicate.
    op.execute(
        """
        CREATE VIEW v_load_summary AS
        SELECT
            b.load_id,
            b.source_file,
            b.source_sheet,
            b.plant_code AS plant,
            b.status,
            b.file_hash,
            b.rows_in_file,
            b.rows_loaded,
            b.rows_duplicate,
            b.rows_rejected,
            b.rows_quarantine,
            (SELECT count(*) FROM reject_log r
              WHERE r.load_id = b.load_id AND r.status = 'NEW')  AS rejects_awaiting_review,
            (SELECT count(*) FROM unidentified_model u
              WHERE u.load_id = b.load_id AND u.status = 'NEW')  AS unidentified_awaiting_review,
            b.started_at,
            b.finished_at,
            b.finished_at - b.started_at AS duration,
            b.loaded_by,
            b.superseded_by
        FROM load_batch b
        ORDER BY b.load_id DESC
        """
    )
    op.execute(
        "COMMENT ON VIEW v_load_summary IS "
        "'Per-upload result. Intentionally NOT filtered by the active-data "
        "predicate: failed and pending batches are the point of this view.'"
    )


# ---------------------------------------------------------------------
def _grants() -> None:
    """Same least-privilege posture T01 established, extended to T02's tables.

    Dropping a view drops its grants, so every view is re-granted here.
    """
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;

                -- reference data: read only
                GRANT SELECT ON ref_color_family TO {role};

                -- header aliases: propose new spellings, record approval.
                -- No DELETE: a rejected spelling is kept, like every other
                -- mapping decision in this schema.
                GRANT SELECT, INSERT ON ref_column_alias TO {role};
                GRANT UPDATE (is_approved, approved_by) ON ref_column_alias TO {role};

                -- standards: append a new version, never edit one
                GRANT SELECT, INSERT ON cf_standard TO {role};

                -- mapping proposals: propose, then record the human decision
                GRANT SELECT, INSERT ON proposed_mapping TO {role};
                GRANT UPDATE (status, decided_by, decided_at)
                    ON proposed_mapping TO {role};

                -- supersession: append only. No UPDATE and no DELETE, so a
                -- retirement cannot be quietly withdrawn.
                GRANT SELECT, INSERT ON measurement_supersession TO {role};
                GRANT USAGE, SELECT ON SEQUENCE measurement_supersession_id_seq
                    TO {role};

                -- views (recreated above, so their grants were dropped)
                GRANT SELECT ON v_wavescan_active, v_wavescan, v_wavescan_p703,
                                v_wavescan_u704, v_load_summary, v_car_completeness
                    TO {role};
            END $$;
            """
        )

    op.execute("REVOKE ALL ON ref_column_alias FROM PUBLIC")
    op.execute("REVOKE ALL ON ref_color_family FROM PUBLIC")
    op.execute("REVOKE ALL ON cf_standard FROM PUBLIC")
    op.execute("REVOKE ALL ON proposed_mapping FROM PUBLIC")
    op.execute("REVOKE ALL ON measurement_supersession FROM PUBLIC")


# =====================================================================
def downgrade() -> None:
    """Reverse T02, refusing wherever reversal would destroy information.

    The task asks for a reversible migration, and the schema half genuinely
    is. The data half is not unconditionally: NUMERIC -> REAL discards
    precision for anything written since the upgrade, and the new tables hold
    records that have no pre-T02 home. So this checks first and stops with a
    specific reason rather than silently losing evidence.
    """
    op.execute(
        """
        DO $$
        DECLARE
            v_problems text := '';
            v_n bigint;
        BEGIN
            SELECT count(*) INTO v_n FROM measurement_supersession;
            IF v_n > 0 THEN
                v_problems := v_problems || format(
                    E'\\n  - %s supersession record(s): pre-T02 has nowhere to put them', v_n);
            END IF;

            SELECT count(*) INTO v_n FROM wavescan WHERE corrects_measurement_id IS NOT NULL;
            IF v_n > 0 THEN
                v_problems := v_problems || format(
                    E'\\n  - %s correction row(s): the correction link would be dropped', v_n);
            END IF;

            SELECT count(*) INTO v_n FROM proposed_mapping;
            IF v_n > 0 THEN
                v_problems := v_problems || format(
                    E'\\n  - %s mapping proposal(s) would be dropped', v_n);
            END IF;

            SELECT count(*) INTO v_n FROM stg_raw WHERE extra <> '{}'::jsonb;
            IF v_n > 0 THEN
                v_problems := v_problems || format(
                    E'\\n  - %s staging row(s) carry unmapped columns in extra', v_n);
            END IF;

            SELECT count(*) INTO v_n FROM load_batch
             WHERE status IN ('PENDING_REVIEW','SUPERSEDED','REJECTED_TEMPLATE');
            IF v_n > 0 THEN
                v_problems := v_problems || format(
                    E'\\n  - %s batch(es) use a status the old CHECK forbids', v_n);
            END IF;

            -- Precision: every measurement must survive numeric -> real -> numeric.
            SELECT count(*) INTO v_n FROM wavescan
             WHERE lw::real::numeric <> lw OR sw::real::numeric <> sw
                OR cf::real::numeric <> cf OR doi::real::numeric <> doi
                OR du::real::numeric <> du OR wa::real::numeric <> wa
                OR wb::real::numeric <> wb OR wc::real::numeric <> wc
                OR wd::real::numeric <> wd OR we::real::numeric <> we
                OR (b IS NOT NULL AND b::real::numeric <> b);
            IF v_n > 0 THEN
                v_problems := v_problems || format(
                    E'\\n  - %s measurement row(s) would lose precision converting back to REAL', v_n);
            END IF;

            IF v_problems <> '' THEN
                -- One '%' = one placeholder. '%%' is an escaped literal and
                -- would make this RAISE fail to compile with "too many
                -- parameters", masking every check above it.
                RAISE EXCEPTION 'T02 downgrade refused - it would destroy data:%',
                    v_problems || E'\\n' ||
                    'Resolve or export these first. Downgrading an empty or ' ||
                    'freshly-migrated database is safe and will proceed.';
            END IF;
        END $$;
        """
    )

    # Views and the supersession machinery first.
    for view in ("v_car_completeness", "v_load_summary", "v_wavescan_u704",
                 "v_wavescan_p703", "v_wavescan", "v_wavescan_active"):
        op.execute(f"DROP VIEW IF EXISTS {view} CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_mark_superseded ON measurement_supersession")
    op.execute("DROP FUNCTION IF EXISTS mark_measurement_superseded()")
    # Must go before is_superseded is dropped below: a trigger left behind
    # referencing a column that no longer exists breaks every INSERT.
    op.execute("DROP TRIGGER IF EXISTS trg_reject_presuperseded ON wavescan")
    op.execute("DROP FUNCTION IF EXISTS reject_presuperseded_measurement()")
    op.execute("DROP TABLE IF EXISTS measurement_supersession")
    op.execute("DROP TABLE IF EXISTS proposed_mapping")
    op.execute("DROP TABLE IF EXISTS cf_standard")
    op.execute("DROP TABLE IF EXISTS ref_column_alias")
    op.execute("ALTER TABLE ref_color DROP COLUMN IF EXISTS grading_family")
    op.execute("DROP TABLE IF EXISTS ref_color_family")

    # wavescan back to the demo shape.
    op.execute("ALTER TABLE wavescan ADD COLUMN IF NOT EXISTS source_file text")
    op.execute(
        "UPDATE wavescan w SET source_file = b.source_file "
        "FROM load_batch b WHERE b.load_id = w.load_id AND w.source_file IS NULL"
    )
    op.execute("ALTER TABLE wavescan ALTER COLUMN source_file SET NOT NULL")
    op.execute("ALTER TABLE wavescan DROP CONSTRAINT IF EXISTS uq_ws_load_row")
    op.execute(
        "ALTER TABLE wavescan ADD CONSTRAINT uq_ws_source "
        "UNIQUE (source_file, source_sheet, source_row)"
    )
    for column in ("corrected_at", "corrected_by", "correction_reason",
                   "corrects_measurement_id", "is_superseded"):
        op.execute(f"ALTER TABLE wavescan DROP COLUMN IF EXISTS {column}")
    for column in MEASURE_COLUMNS:
        op.execute(
            f"ALTER TABLE wavescan ALTER COLUMN {column} TYPE real "
            f"USING {column}::real"
        )
    op.execute("ALTER TABLE wavescan ALTER COLUMN loaded_at TYPE timestamp")

    # load_batch / stg_raw / quarantine.
    op.execute("ALTER TABLE stg_raw DROP COLUMN IF EXISTS raw_headers")
    op.execute("ALTER TABLE stg_raw DROP COLUMN IF EXISTS extra")
    op.execute("ALTER TABLE stg_raw ALTER COLUMN ingested_at TYPE timestamp")

    op.execute("ALTER TABLE load_batch DROP COLUMN IF EXISTS loaded_by")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='load_batch'
                          AND column_name='loaded_by_role_legacy') THEN
                ALTER TABLE load_batch RENAME COLUMN loaded_by_role_legacy TO loaded_by;
                UPDATE load_batch SET loaded_by = current_user WHERE loaded_by IS NULL;
                ALTER TABLE load_batch ALTER COLUMN loaded_by SET NOT NULL;
                ALTER TABLE load_batch ALTER COLUMN loaded_by SET DEFAULT current_user;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE load_batch DROP COLUMN IF EXISTS raw_headers")
    op.execute("ALTER TABLE load_batch DROP COLUMN IF EXISTS template_fingerprint")
    op.execute("ALTER TABLE load_batch DROP COLUMN IF EXISTS raw_store_key")
    op.execute("ALTER TABLE load_batch ALTER COLUMN file_hash DROP NOT NULL")
    op.execute("ALTER TABLE load_batch ALTER COLUMN file_hash TYPE text")
    op.execute("ALTER TABLE load_batch ALTER COLUMN started_at TYPE timestamp")
    op.execute("ALTER TABLE load_batch ALTER COLUMN finished_at TYPE timestamp")
    # Drop the constraints BEFORE renaming the data back: the T02 CHECK does
    # not allow 'SUCCESS', so updating first fails on its own constraint.
    op.execute("ALTER TABLE load_batch DROP CONSTRAINT IF EXISTS ck_batch_status")
    op.execute("ALTER TABLE load_batch DROP CONSTRAINT IF EXISTS ck_batch_balance")
    op.execute("UPDATE load_batch SET status='SUCCESS' WHERE status='COMMITTED'")
    op.execute(
        "ALTER TABLE load_batch ADD CONSTRAINT ck_batch_status CHECK "
        "(status IN ('RUNNING','SUCCESS','FAILED','ROLLED_BACK'))"
    )
    op.execute(
        "ALTER TABLE load_batch ADD CONSTRAINT ck_batch_balance CHECK ("
        "status <> 'SUCCESS' OR rows_in_file = rows_loaded + rows_duplicate "
        "+ rows_rejected + rows_quarantine)"
    )

    op.execute("ALTER TABLE reject_log DROP CONSTRAINT IF EXISTS ck_reject_reason")
    op.execute(
        """
        ALTER TABLE reject_log ADD CONSTRAINT ck_reject_reason CHECK (
            reject_reason IN (
                'UNKNOWN_PLANT','UNKNOWN_MODEL','UNKNOWN_CHECKZONE','UNKNOWN_COLOR',
                'UNKNOWN_PAINTLINE','ZONE_NOT_VALID_FOR_MODEL','MISSING_MEASUREMENT',
                'MISSING_REQUIRED_FIELD','BAD_DATE','BAD_NUMBER','OUT_OF_RANGE',
                'DUPLICATE_ROW','OTHER')
        )
        """
    )
    for table, columns in (
        ("reject_log", ("reviewed_at", "created_at")),
        ("unidentified_model", ("reviewed_at", "created_at")),
        ("ref_plant_zone_map", ("approved_at", "created_at")),
    ):
        for column in columns:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamp")

    # Restore the demo views.
    op.execute(
        """
        CREATE VIEW v_wavescan AS
        SELECT measured_date AS "Date", month AS "Month", year AS "Year",
               plant AS "Plant", model AS "Model", checkzone AS "Checkzone",
               color AS "Color", tolerance_group AS "Tolerance Group",
               paintline AS "Paintline", serial_no AS "Serial No",
               lw AS "LW", sw AS "SW", cf AS "CF", doi AS "DOI", du AS "du",
               wa AS "Wa", wb AS "Wb", wc AS "Wc", wd AS "Wd", we AS "We", b AS "B"
        FROM wavescan WHERE is_duplicate = false
        """
    )
    op.execute(
        "CREATE VIEW v_wavescan_p703 AS SELECT * FROM wavescan "
        "WHERE model LIKE 'P703%' AND is_duplicate = false"
    )
    op.execute(
        "CREATE VIEW v_wavescan_u704 AS SELECT * FROM wavescan "
        "WHERE model = 'U704' AND is_duplicate = false"
    )
    op.execute(
        """
        CREATE VIEW v_load_summary AS
        SELECT b.load_id, b.source_file, b.source_sheet, b.plant_code AS plant,
               b.status, b.rows_in_file, b.rows_loaded, b.rows_duplicate,
               b.rows_rejected, b.rows_quarantine,
               (SELECT count(*) FROM reject_log r
                 WHERE r.load_id = b.load_id AND r.status='NEW') AS rejects_awaiting_review,
               (SELECT count(*) FROM unidentified_model u
                 WHERE u.load_id = b.load_id AND u.status='NEW') AS unidentified_awaiting_review,
               b.started_at, b.finished_at, b.finished_at - b.started_at AS duration,
               b.loaded_by
        FROM load_batch b ORDER BY b.load_id DESC
        """
    )
    op.execute(
        """
        CREATE VIEW v_car_completeness AS
        SELECT w.plant, w.serial_no, w.model, w.measured_date,
               count(*) AS zones_recorded, m.expected_zone_count AS zones_expected,
               m.expected_zone_count - count(*) AS zones_missing,
               CASE WHEN count(*) = m.expected_zone_count THEN 'COMPLETE'
                    WHEN count(*) <  m.expected_zone_count THEN 'INCOMPLETE'
                    ELSE 'EXCESS' END AS completeness
        FROM wavescan w JOIN ref_model m ON m.model_code = w.model
        WHERE w.is_duplicate = false
        GROUP BY w.plant, w.serial_no, w.model, w.measured_date, m.expected_zone_count
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION purge_stg_raw(p_months INTEGER DEFAULT 6)
        RETURNS TABLE (batches_purged BIGINT, rows_purged BIGINT)
        LANGUAGE plpgsql AS $$
        DECLARE v_batches BIGINT; v_rows BIGINT;
        BEGIN
            SELECT count(*) INTO v_rows FROM stg_raw s
              JOIN load_batch b ON b.load_id = s.load_id
             WHERE b.status='SUCCESS'
               AND b.finished_at < now() - make_interval(months => p_months);
            WITH doomed AS (
                SELECT load_id FROM load_batch WHERE status='SUCCESS'
                  AND finished_at < now() - make_interval(months => p_months)
            ), zapped AS (
                DELETE FROM stg_raw WHERE load_id IN (SELECT load_id FROM doomed)
                RETURNING load_id
            )
            SELECT count(DISTINCT load_id) INTO v_batches FROM zapped;
            RETURN QUERY SELECT COALESCE(v_batches,0), COALESCE(v_rows,0);
        END; $$
        """
    )
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
                    GRANT SELECT ON v_wavescan, v_wavescan_p703, v_wavescan_u704,
                                    v_load_summary, v_car_completeness TO {role};
                END IF;
            END $$;
            """
        )
