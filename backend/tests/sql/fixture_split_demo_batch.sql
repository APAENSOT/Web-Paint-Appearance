-- =============================================================
-- fixture_split_demo_batch.sql
--
-- Demo-fixture remediation for T02. Run AFTER the vault's
-- 06_demo_data.sql and BEFORE `alembic upgrade` to 0002.
--
-- 06_demo_data.sql loads two vehicles into ONE synthetic load_batch
-- ("DEMO: 2 real vehicles"), even though their rows come from two
-- different Excel files:
--
--     06 Jun'26 CF data AAT.xlsx   AAT 2483403  U704             31 rows
--     06. Jun26 CF data FTM.xlsx   FTM 1943732  P703 DBL RAPTOR  32 rows
--
-- Under the demo key (source_file, source_sheet, source_row) that was
-- legal, because source_file varied per ROW. The target model puts
-- source_file on the batch and keys wavescan on (load_id, source_row)
-- (01-DATA-MODEL.md section 5), under which those 31 rows collide with
-- 31 of the 32 others -- both sheets number their rows from 2.
--
-- So 0002's precondition refuses the migration and asks for the batch to
-- be split, one load_batch per source file. This does that. It moves
-- rows; it retypes no measurement value and renumbers no source_row,
-- because source_row is the spreadsheet coordinate a reading is traced
-- back to.
--
-- This is FIXTURE repair, not a migration: the situation exists only
-- because a seed script built a batch by hand. A real load produces one
-- batch per (file, sheet) and cannot collide.
--
-- Run as the schema owner, against the pre-0002 schema.
-- =============================================================

DO $$
DECLARE
    r_batch  record;
    v_file   text;
    v_keep   text;
    v_new    bigint;
    v_split  int := 0;
BEGIN
    FOR r_batch IN
        SELECT load_id
          FROM wavescan
         GROUP BY load_id
        HAVING count(DISTINCT source_file) > 1
         ORDER BY load_id
    LOOP
        -- The batch keeps its alphabetically-first file; every other file
        -- gets a batch of its own.
        SELECT min(source_file) INTO v_keep
          FROM wavescan WHERE load_id = r_batch.load_id;

        FOR v_file IN
            SELECT DISTINCT source_file
              FROM wavescan
             WHERE load_id = r_batch.load_id AND source_file <> v_keep
             ORDER BY 1
        LOOP
            INSERT INTO load_batch (
                source_file, source_sheet, plant_code, file_hash, status,
                rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
                rows_quarantine, finished_at, notes)
            SELECT
                v_file,
                min(w.source_sheet),
                min(w.plant),
                -- Synthetic, clearly-marked fixture hash. These rows were
                -- never uploaded as a file, so no real SHA-256 exists; the
                -- value is deterministic so re-running is stable.
                'fixture' || lpad(md5(v_file), 57, '0'),
                'SUCCESS',
                count(*), count(*), 0, 0, 0,
                now(),
                'split from synthetic demo batch ' || r_batch.load_id
                    || ' by fixture_split_demo_batch.sql (T02)'
            FROM wavescan w
            WHERE w.load_id = r_batch.load_id AND w.source_file = v_file
            RETURNING load_id INTO v_new;

            UPDATE wavescan
               SET load_id = v_new
             WHERE load_id = r_batch.load_id AND source_file = v_file;

            v_split := v_split + 1;
            RAISE NOTICE 'split % row(s) of % into new load_batch %',
                (SELECT count(*) FROM wavescan WHERE load_id = v_new), v_file, v_new;
        END LOOP;

        -- The original batch now describes exactly one file. Restate its
        -- identity and re-derive its counts so ck_batch_balance holds.
        UPDATE load_batch b
           SET source_file    = v_keep,
               source_sheet   = s.sheet,
               plant_code     = s.plant,
               rows_in_file   = s.n,
               rows_loaded    = s.n,
               rows_duplicate = 0,
               rows_rejected  = 0,
               rows_quarantine = 0
          FROM (SELECT min(source_sheet) AS sheet, min(plant) AS plant, count(*) AS n
                  FROM wavescan WHERE load_id = r_batch.load_id) s
         WHERE b.load_id = r_batch.load_id;
    END LOOP;

    IF v_split = 0 THEN
        RAISE NOTICE 'nothing to split - no batch spans more than one source file';
    END IF;
END $$;

-- Every batch must now have a hash: 0002 makes file_hash NOT NULL, and the
-- demo batch was seeded without one.
UPDATE load_batch
   SET file_hash = 'fixture' || lpad(md5(source_file), 57, '0')
 WHERE file_hash IS NULL;

-- Post-conditions: what 0002's preconditions will check.
DO $$
DECLARE v_dupes bigint; v_nulls bigint; v_mixed bigint;
BEGIN
    SELECT count(*) INTO v_dupes FROM (
        SELECT 1 FROM wavescan GROUP BY load_id, source_row HAVING count(*) > 1) x;
    SELECT count(*) INTO v_nulls FROM load_batch WHERE file_hash IS NULL;
    SELECT count(*) INTO v_mixed FROM (
        SELECT 1 FROM wavescan GROUP BY load_id
         HAVING count(DISTINCT source_file) > 1) y;

    IF v_dupes > 0 OR v_nulls > 0 OR v_mixed > 0 THEN
        RAISE EXCEPTION 'fixture repair incomplete: % colliding (load_id, source_row) '
                        'group(s), % batch(es) with no hash, % batch(es) still '
                        'spanning several files', v_dupes, v_nulls, v_mixed;
    END IF;
    RAISE NOTICE 'fixture ready: no collisions, no missing hashes, one file per batch';
END $$;
