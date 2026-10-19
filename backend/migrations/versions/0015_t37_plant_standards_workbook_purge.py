"""T37: plant-scoped Ford/Min and the workbook purge function.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-28

Two changes (T37, ADR 0011, ADR 0012):

1. **`cf_standard.plant_code`**, nullable, FK `ref_plant`. A FAMILY row with
   a plant is that plant's Ford/Min; the seed rows keep ``plant_code`` NULL
   and are the fallback until a plant publishes. Rows stay append-only: no
   UPDATE, no DELETE, and this revision back-fills nothing.

2. **`purge_workbook(p_plant, p_hash, p_actor, p_reason, p_correlation)`**,
   ``SECURITY DEFINER`` with a fixed ``search_path``. The only way the
   application can remove a workbook's rows. It writes ``workbook.purge`` to
   ``audit_event`` **before** any fact is deleted, in the caller's
   transaction, then deletes that plant + hash's batches and their
   dependants. ``app_rw`` still holds no table DELETE on ``wavescan`` or
   ``load_batch`` (T01); it gets EXECUTE on this one function and nothing
   else. ``PUBLIC`` is revoked.

   Not touched: other hashes, ``ref_template_profile``, aliases,
   ``cf_standard``. A purge that would have to change another hash's rows --
   a batch of another file that names this one in ``superseded_by``, a
   correction or supersession that crosses files, or the same hash filed
   under another plant -- is refused, not tidied.

**Destructive.** The function deletes fact rows on request. The owner's
approval line belongs in the commit message (AGENTS.md section 2).
"""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

#: ADR 0011: EXECUTE on the function goes to the application role only.
APP_ROLE = "app_rw"

PURGE_SIGNATURE = "purge_workbook(text, character, uuid, text, text)"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cf_standard ADD COLUMN IF NOT EXISTS plant_code text "
        "REFERENCES ref_plant (plant_code) ON DELETE RESTRICT"
    )
    op.execute(
        "COMMENT ON COLUMN cf_standard.plant_code IS "
        "'ADR 0012: Ford/Min are per plant x family. NULL = seed fallback used "
        "until that plant publishes. Latest plant row by created_at wins for "
        "every Overview month. Append-only: never UPDATE or DELETE.'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cf_standard_scope_plant "
        "ON cf_standard (scope, plant_code, family_name, color_name, orient, created_at DESC)"
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION purge_workbook(
            p_plant       text,
            p_hash        char(64),
            p_actor       uuid,
            p_reason      text,
            p_correlation text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $fn$
        DECLARE
            v_reason   text := btrim(coalesce(p_reason, ''));
            v_ids      bigint[];
            v_meas     bigint[];
            v_files    jsonb;
            v_before   jsonb;
            v_audit    bigint;
            v_n        bigint;
            v_wavescan bigint;
            v_batches  bigint;
            v_cleared  jsonb := '{}'::jsonb;
        BEGIN
            IF v_reason = '' THEN
                RAISE EXCEPTION 'a reason is required to purge a workbook'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF p_actor IS NULL THEN
                RAISE EXCEPTION 'a named actor is required to purge a workbook'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;

            PERFORM 1 FROM load_batch
             WHERE file_hash = p_hash
             ORDER BY load_id
               FOR UPDATE;

            SELECT array_agg(load_id ORDER BY load_id)
              INTO v_ids
              FROM load_batch
             WHERE plant_code = p_plant AND file_hash = p_hash;

            IF v_ids IS NULL THEN
                RAISE EXCEPTION 'no workbook % at plant %', p_hash, p_plant
                    USING ERRCODE = 'no_data_found';
            END IF;

            IF EXISTS (
                SELECT 1 FROM load_batch
                 WHERE file_hash = p_hash
                   AND plant_code IS DISTINCT FROM p_plant
            ) THEN
                RAISE EXCEPTION
                    'workbook % also has sheets filed under another plant; purge refused so the hash is not left half-present',
                    p_hash
                    USING ERRCODE = 'object_in_use';
            END IF;

            SELECT coalesce(array_agg(measurement_id), '{}')
              INTO v_meas
              FROM wavescan WHERE load_id = ANY(v_ids);

            IF EXISTS (
                SELECT 1 FROM load_batch
                 WHERE superseded_by = ANY(v_ids)
                   AND NOT (load_id = ANY(v_ids))
            ) THEN
                RAISE EXCEPTION
                    'another workbook names a sheet of % as its replacement (superseded_by); restore or purge that one first',
                    p_hash
                    USING ERRCODE = 'object_in_use';
            END IF;

            IF EXISTS (
                SELECT 1 FROM wavescan
                 WHERE corrects_measurement_id = ANY(v_meas)
                   AND NOT (load_id = ANY(v_ids))
            ) OR EXISTS (
                SELECT 1 FROM measurement_supersession s
                 WHERE (s.superseded_measurement_id = ANY(v_meas)
                        AND s.superseded_by_measurement_id IS NOT NULL
                        AND NOT (s.superseded_by_measurement_id = ANY(v_meas)))
                    OR (s.superseded_by_measurement_id = ANY(v_meas)
                        AND NOT (s.superseded_measurement_id = ANY(v_meas)))
            ) THEN
                RAISE EXCEPTION
                    'a correction or supersession links workbook % to another workbook; purge refused',
                    p_hash
                    USING ERRCODE = 'object_in_use';
            END IF;

            SELECT jsonb_agg(jsonb_build_object(
                       'load_id', load_id,
                       'source_file', source_file,
                       'source_sheet', source_sheet,
                       'status', status)
                   ORDER BY load_id)
              INTO v_files
              FROM load_batch WHERE load_id = ANY(v_ids);

            v_before := jsonb_build_object(
                'plant_code', p_plant,
                'file_hash', p_hash,
                'batches', v_files,
                'wavescan', cardinality(v_meas),
                'stg_raw', (SELECT count(*) FROM stg_raw WHERE load_id = ANY(v_ids)),
                'reject_log', (SELECT count(*) FROM reject_log WHERE load_id = ANY(v_ids)),
                'unidentified_model', (SELECT count(*) FROM unidentified_model WHERE load_id = ANY(v_ids)),
                'stg_review_row', (SELECT count(*) FROM stg_review_row WHERE load_id = ANY(v_ids)),
                'ingest_job', (SELECT count(*) FROM ingest_job WHERE load_id = ANY(v_ids))
            );

            -- ADR 0011: the audit row is written first, in this transaction.
            INSERT INTO audit_event
                (actor_user_id, actor_type, action, entity_type, entity_id,
                 before, after, correlation_id)
            VALUES
                (p_actor, 'user', 'workbook.purge', 'workbook',
                 p_plant || ':' || p_hash, v_before,
                 jsonb_build_object('reason', v_reason, 'load_ids', to_jsonb(v_ids)),
                 p_correlation)
            RETURNING id INTO v_audit;

            DELETE FROM measurement_supersession
             WHERE superseded_measurement_id = ANY(v_meas)
                OR superseded_by_measurement_id = ANY(v_meas);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('measurement_supersession', v_n);

            DELETE FROM stg_review_row WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('stg_review_row', v_n);

            DELETE FROM review_acknowledgement WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('review_acknowledgement', v_n);

            DELETE FROM review_override WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('review_override', v_n);

            DELETE FROM stg_raw WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('stg_raw', v_n);

            DELETE FROM reject_log WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('reject_log', v_n);

            DELETE FROM unidentified_model WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('unidentified_model', v_n);

            -- A proposal still open for this file goes with it. A decided one
            -- is the provenance of an alias that stays, so it is detached.
            DELETE FROM proposed_mapping
             WHERE load_id = ANY(v_ids) AND status = 'PROPOSED';
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('proposed_mapping_deleted', v_n);
            UPDATE proposed_mapping SET load_id = NULL WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('proposed_mapping_detached', v_n);

            -- One statement: a correction inside this file points at a row
            -- that goes in the same DELETE, and the FK is checked at its end.
            DELETE FROM wavescan WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_wavescan = ROW_COUNT;

            DELETE FROM ingest_job WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('ingest_job', v_n);

            -- superseded_by is ON DELETE RESTRICT; links inside this file only
            -- (links from other files were refused above).
            UPDATE load_batch SET superseded_by = NULL
             WHERE load_id = ANY(v_ids) AND superseded_by IS NOT NULL;
            DELETE FROM load_batch WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_batches = ROW_COUNT;

            RETURN jsonb_build_object(
                'load_ids', to_jsonb(v_ids),
                'wavescan_deleted', v_wavescan,
                'batches_deleted', v_batches,
                'audit_id', v_audit,
                'cleared', v_cleared
            );
        END;
        $fn$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION " + PURGE_SIGNATURE + " IS "
        "'ADR 0011: X on a workbook. Audit first, then that plant+hash only. "
        "The only application path that deletes wavescan/load_batch rows.'"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {PURGE_SIGNATURE} FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                GRANT EXECUTE ON FUNCTION {PURGE_SIGNATURE} TO {APP_ROLE};
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Drop the function; drop the column only if no plant row exists.

    A plant-scoped Ford/Min row cannot be kept without the column, and
    choosing to delete a published standard is not a downgrade's call.
    """
    op.execute(f"DROP FUNCTION IF EXISTS {PURGE_SIGNATURE}")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM cf_standard WHERE plant_code IS NOT NULL) THEN
                RAISE EXCEPTION
                    'cf_standard has plant-scoped rows; downgrade would have to delete published standards';
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_cf_standard_scope_plant")
    op.execute("ALTER TABLE cf_standard DROP COLUMN IF EXISTS plant_code")
