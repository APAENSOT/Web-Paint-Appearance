-- =============================================================
-- 99_verify.sql
-- Acceptance tests.
--
-- Each test tries to insert data that MUST be refused. A test
-- "passes" when the database raises an error. If any test
-- reports FAIL, a cleaning rule is not actually being enforced
-- and the schema is not safe to load real data into.
--
-- Read-only in effect: every attempt is rolled back.
--
--   psql -U postgres -d paint_appearance -f 99_verify.sql
-- =============================================================

\set ON_ERROR_STOP off

DO $$
DECLARE
    v_pass INT := 0;
    v_fail INT := 0;
    v_load_id BIGINT;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '================================================================';
    RAISE NOTICE ' ACCEPTANCE TESTS - every insert below MUST be rejected';
    RAISE NOTICE '================================================================';

    -- tests 1-10 need SOME valid load_id to satisfy wavescan's FK to
    -- load_batch; which one doesn't matter, so pick whatever exists
    -- rather than hardcoding a number that will not survive a delete
    -- + reload cycle (load_id is a BIGSERIAL and never reuses a value).
    SELECT load_id INTO v_load_id FROM load_batch ORDER BY load_id LIMIT 1;
    IF v_load_id IS NULL THEN
        RAISE EXCEPTION 'load_batch is empty - load at least one file before running 99_verify.sql';
    END IF;

    ---------------------------------------------------------------
    -- 1. uncleaned model spelling
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','AAT','P703 DBL-RANGER','RRHOOD','Meteor Grey','Horizontal',
                'BOOTH1','TEST1',5,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9001);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  1. uncleaned model "P703 DBL-RANGER" was ACCEPTED';
    EXCEPTION WHEN foreign_key_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  1. uncleaned model "P703 DBL-RANGER" rejected';
    END;

    ---------------------------------------------------------------
    -- 2. U704-only zone on a P703 pickup   <-- the key protection
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','FTM','P703 DBL RAPTOR','LIFTGATEHILH','Meteor Grey','Vertical',
                'BOOTH1','TEST2',5,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9002);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  2. U704 liftgate on a P703 pickup was ACCEPTED';
    EXCEPTION WHEN foreign_key_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  2. U704 liftgate on a P703 pickup rejected';
    END;

    ---------------------------------------------------------------
    -- 3. roof recorded as Vertical
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','AAT','U704','LCROOF','Meteor Grey','Vertical',
                'BOOTH1','TEST3',5,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9003);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  3. LCROOF as Vertical was ACCEPTED';
    EXCEPTION WHEN foreign_key_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  3. LCROOF as Vertical rejected';
    END;

    ---------------------------------------------------------------
    -- 4. uncleaned booth spelling
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey','Horizontal',
                'BOOTH 1','TEST4',5,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9004);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  4. booth "BOOTH 1" was ACCEPTED';
    EXCEPTION WHEN foreign_key_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  4. booth "BOOTH 1" rejected';
    END;

    ---------------------------------------------------------------
    -- 5. unknown colour
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','3HC Traction Green','Horizontal',
                'BOOTH1','TEST5',5,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9005);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  5. raw colour "3HC Traction Green" was ACCEPTED';
    EXCEPTION WHEN foreign_key_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  5. raw colour "3HC Traction Green" rejected';
    END;

    ---------------------------------------------------------------
    -- 6. same spreadsheet row loaded twice
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-04','FTM','P703 DBL RAPTOR','RRHOOD','Meteor Grey','Horizontal',
                'BOOTH1','1943732',5.1,18.2,60.6,87.7,14.4,19.4,25.3,13.2,13.1,9.3,-0.2,
                v_load_id,'06. Jun26 CF data FTM.xlsx','PasteData',2);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  6. duplicate source row was ACCEPTED';
    EXCEPTION WHEN unique_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  6. duplicate source row rejected';
    END;

    ---------------------------------------------------------------
    -- 7. NULL measurement in a required column
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey','Horizontal',
                'BOOTH1','TEST7',NULL,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9007);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  7. NULL lw was ACCEPTED';
    EXCEPTION WHEN not_null_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  7. NULL lw rejected (the FTM R104 case)';
    END;

    ---------------------------------------------------------------
    -- 8. negative gauge reading
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey','Horizontal',
                'BOOTH1','TEST8',-5,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9008);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  8. negative LW was ACCEPTED';
    EXCEPTION WHEN check_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  8. negative LW rejected';
    END;

    ---------------------------------------------------------------
    -- 9. unknown plant
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','FVL','U704','RRHOOD','Meteor Grey','Horizontal',
                'BOOTH1','TEST9',5,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9009);
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL  9. out-of-scope plant FVL was ACCEPTED';
    EXCEPTION WHEN foreign_key_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass  9. out-of-scope plant FVL rejected';
    END;

    ---------------------------------------------------------------
    -- 10. B may legitimately be NULL
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey','Horizontal',
                'BOOTH1','TEST10',5,15,60,87,14,19,25,13,13,9,NULL,v_load_id,'TEST','t',9010);
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass 10. NULL B accepted (as designed)';
        DELETE FROM wavescan WHERE serial_no = 'TEST10';
    EXCEPTION WHEN OTHERS THEN
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL 10. NULL B was rejected but should be allowed: %', SQLERRM;
    END;

    ---------------------------------------------------------------
    -- 11. NULL serial_no is now ACCEPTED at the DATABASE level
    --     (Phase 1: multi-plant adapter). This is deliberate - the
    --     database no longer decides who must have a serial; the
    --     LOADER does, per plant, via ref_plant.requires_serial.
    --     This test documents that relaxation so a future change
    --     cannot silently re-tighten it without someone noticing.
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                              paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                              load_id,source_file,source_sheet,source_row)
        VALUES (DATE '2026-07-01','AAT','U704','RRHOOD','Meteor Grey','Horizontal',
                NULL,NULL,5,15,60,87,14,19,25,13,13,9,0,v_load_id,'TEST','t',9011);
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass 11. NULL serial_no/paintline accepted at DB level (loader enforces per-plant)';
        DELETE FROM wavescan WHERE source_row = 9011 AND source_file = 'TEST';
    EXCEPTION WHEN OTHERS THEN
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL 11. NULL serial_no was rejected but Phase 1 should allow it: %', SQLERRM;
    END;

    ---------------------------------------------------------------
    -- 12. ref_plant_zone_map: a mapping cannot be marked APPROVED
    --     without an approver. Guards against the review UI (or a
    --     bug in it) silently trusting an unreviewed proposal.
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO ref_plant_zone_map (plant_code, model_code, raw_zone_text, zone_code, confidence)
        VALUES ('FTM','P703 DBL RANGER','TEST_ZONE_12','RCROOF','APPROVED');
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL 12. APPROVED mapping with no approver was ACCEPTED';
    EXCEPTION WHEN check_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass 12. APPROVED mapping with no approver rejected';
    END;

    ---------------------------------------------------------------
    -- 13. ref_plant_zone_map: zone must still be valid for the
    --     model, same protection wavescan itself has (a U704-only
    --     zone cannot be mapped onto a P703 model here either).
    ---------------------------------------------------------------
    BEGIN
        INSERT INTO ref_plant_zone_map (plant_code, model_code, raw_zone_text, zone_code, confidence)
        VALUES ('FTM','P703 DBL RANGER','TEST_ZONE_13','LIFTGATEHILH','PROPOSED');
        v_fail := v_fail + 1;
        RAISE NOTICE 'FAIL 13. U704-only zone mapped onto P703 model was ACCEPTED';
    EXCEPTION WHEN foreign_key_violation THEN
        v_pass := v_pass + 1;
        RAISE NOTICE 'pass 13. U704-only zone mapped onto P703 model rejected';
    END;

    RAISE NOTICE '----------------------------------------------------------------';
    RAISE NOTICE ' passed: %   failed: %', v_pass, v_fail;
    IF v_fail = 0 THEN
        RAISE NOTICE ' RESULT: ALL TESTS PASSED - schema enforces every rule';
    ELSE
        RAISE WARNING ' RESULT: % TEST(S) FAILED - do not load real data yet', v_fail;
    END IF;
    RAISE NOTICE '================================================================';
END $$;


-- -------------------------------------------------------------
-- Generated columns: month/year must follow measured_date
-- -------------------------------------------------------------
\echo ''
\echo '=== GENERATED COLUMN CHECK (month/year derive from date) ==='
SELECT DISTINCT
    measured_date, month, year,
    CASE WHEN month = EXTRACT(MONTH FROM measured_date)::int
          AND year  = EXTRACT(YEAR  FROM measured_date)::int
         THEN 'OK' ELSE 'MISMATCH' END AS check_result
FROM wavescan
ORDER BY measured_date;

\echo ''
\echo '=== VEHICLE COMPLETENESS (P703 must be 32, U704 must be 31) ==='
SELECT plant, serial_no, model, zones_recorded, zones_expected, completeness
FROM v_car_completeness
ORDER BY plant, serial_no;
