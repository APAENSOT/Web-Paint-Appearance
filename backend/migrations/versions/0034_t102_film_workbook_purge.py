"""T102: the workbook purge must cover a Film workbook (ADR 0011).

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-11

``purge_workbook`` was written for T37 (revision 0015, left unchanged by
0016), before FilmThickness existed. It deletes ``wavescan`` but never
``filmthickness``, and ``filmthickness_load_id_fkey`` is ON DELETE RESTRICT,
so purging a Film workbook raises SQLSTATE ``23503`` on ``DELETE FROM
load_batch``. ``services/workbooks._PURGE_REFUSALS`` maps only ``P0002`` /
``22023`` / ``55006``, so the API answers 500 and the whole transaction --
the ``workbook.purge`` audit row included -- rolls back. No trace is left.

This revision is one ``CREATE OR REPLACE FUNCTION purge_workbook(...)``:
same signature, same ``SECURITY DEFINER`` and fixed ``search_path``, same
owner, comment and grants (re-asserted below), the previous body plus the
four changes T102 section 2 locked:

* **D-102-1** for the hash's ``load_id``s, ``DELETE FROM filmthickness``
  after the audit row and before ``DELETE FROM load_batch``.
* **D-102-2** a ``filmthickness.corrects_measurement_id`` that crosses
  workbooks, in either direction, is ``object_in_use`` -> 409 and nothing
  is deleted -- the rule ``wavescan`` corrections already had.
* **D-102-3** Film ids are collected into their own ``v_film``.
  ``measurement_supersession`` holds **WaveScan** ids and a Film
  ``measurement_id`` can equal one of them, so its DELETE keeps using
  ``v_meas`` alone and ``v_film`` never reaches that table.
* **D-102-4** the audit row's ``before`` carries ``filmthickness``, and the
  deleted count joins the ``cleared`` summary, like ``wavescan``.

Nothing else changes (D-102-5): still Admin-only through the route, still
reason-required, the stored bytes stay (D4), and template profiles,
aliases, ``cf_standard``, ``film_standard``, ``ref_*`` and
``film_point_setting`` are untouched. No role gains a table DELETE.

``downgrade()`` re-installs ``PURGE_BODY_0016`` -- the body as of 0015/0016,
verbatim.

**Destructive.** This function deletes fact rows on request.
**Owner approval (AGENTS.md section 2), given 2026-10-11 in the planning
chat:** *extend the ADR 0011 workbook purge to delete a Film workbook's
``filmthickness`` facts, as it already does for WaveScan; fix before T101.*
"""

from __future__ import annotations

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

#: ADR 0011: EXECUTE on the function goes to the application role only.
APP_ROLE = "app_rw"

PURGE_SIGNATURE = "purge_workbook(text, character, uuid, text, text)"

#: No apostrophe in either comment, so they go straight into the SQL literal.
COMMENT_0034 = (
    "ADR 0011 + T102: X on a workbook. Audit first, then that plant+hash "
    "only, WaveScan and Film facts alike. The only application path that "
    "deletes wavescan/filmthickness/load_batch rows."
)
COMMENT_0016 = (
    "ADR 0011: X on a workbook. Audit first, then that plant+hash only. "
    "The only application path that deletes wavescan/load_batch rows."
)

#: The body revision 0015 installed and 0016 left alone. `downgrade` restores
#: it; a source test compares it with the 0015 file so "verbatim" is checked.
PURGE_BODY_0016 = r'''        DECLARE
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
        END;'''

#: The same body with D-102-1..4 applied, and nothing else.
PURGE_BODY_0034 = r'''        DECLARE
            v_reason   text := btrim(coalesce(p_reason, ''));
            v_ids      bigint[];
            v_meas     bigint[];
            v_film     bigint[];
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

            -- T102 D-102-3: its own array. measurement_supersession holds
            -- WaveScan ids, and a Film measurement_id can equal one of them,
            -- so v_film never reaches that table.
            SELECT coalesce(array_agg(measurement_id), '{}')
              INTO v_film
              FROM filmthickness WHERE load_id = ANY(v_ids);

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

            -- T102 D-102-2: the same rule for Film, both directions.
            IF EXISTS (
                SELECT 1 FROM filmthickness
                 WHERE corrects_measurement_id = ANY(v_film)
                   AND NOT (load_id = ANY(v_ids))
            ) OR EXISTS (
                SELECT 1 FROM filmthickness
                 WHERE load_id = ANY(v_ids)
                   AND corrects_measurement_id IS NOT NULL
                   AND NOT (corrects_measurement_id = ANY(v_film))
            ) THEN
                RAISE EXCEPTION
                    'a Film correction links workbook % to another workbook; purge refused',
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
                'filmthickness', cardinality(v_film),
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

            -- T102 D-102-1/4: the Film facts of this workbook, one statement
            -- for the same reason as wavescan above, and counted like it.
            DELETE FROM filmthickness WHERE load_id = ANY(v_ids);
            GET DIAGNOSTICS v_n = ROW_COUNT;
            v_cleared := v_cleared || jsonb_build_object('filmthickness', v_n);

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
        END;'''


def _install(body: str) -> None:
    """One CREATE OR REPLACE, then the comment, revoke and grant re-asserted.

    CREATE OR REPLACE keeps the owner (`postgres`) and the existing ACL, but
    the grants are re-stated so this revision alone describes the end state.
    """
    op.execute(
        f"""
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
{body}
        $fn$
        """
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


def upgrade() -> None:
    _install(PURGE_BODY_0034)
    op.execute(f"COMMENT ON FUNCTION {PURGE_SIGNATURE} IS '{COMMENT_0034}'")


def downgrade() -> None:
    """Restore the 0015/0016 body: the purge stops touching `filmthickness`.

    A Film workbook then cannot be purged at all (the RESTRICT FK bites and
    the API answers 500 again), which is the state this revision fixes. No
    fact is deleted either way.
    """
    _install(PURGE_BODY_0016)
    op.execute(f"COMMENT ON FUNCTION {PURGE_SIGNATURE} IS '{COMMENT_0016}'")
