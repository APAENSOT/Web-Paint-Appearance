-- =============================================================
-- 05_views.sql
--
-- PostgreSQL cannot reorder a table's columns after creation.
-- v_wavescan is therefore the permanent guarantee that the 21
-- template columns always appear in template order, with the
-- original Excel labels, no matter how the table evolves.
--
-- The per-model views replace the idea of separate
-- wavescan_P703 / wavescan_U704 tables: same convenience,
-- one physical table, no UNION, no schema change per model.
--
-- Run against: paint_appearance
-- =============================================================


DROP VIEW IF EXISTS v_car_completeness CASCADE;
DROP VIEW IF EXISTS v_load_summary     CASCADE;
DROP VIEW IF EXISTS v_wavescan_u704    CASCADE;
DROP VIEW IF EXISTS v_wavescan_p703    CASCADE;
DROP VIEW IF EXISTS v_wavescan         CASCADE;


-- -------------------------------------------------------------
-- v_wavescan - the 21 template columns, template order,
--              original Excel labels, duplicates excluded.
--              This is what users and exports should read.
-- -------------------------------------------------------------
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
FROM wavescan
WHERE is_duplicate = false;

COMMENT ON VIEW v_wavescan IS
    'The 21 template columns in template order with original labels. Duplicates excluded. Read this, not the base table.';


-- -------------------------------------------------------------
-- Per-model views. Look like separate tables, but there is only
-- one physical table underneath.
-- -------------------------------------------------------------
CREATE VIEW v_wavescan_p703 AS
SELECT * FROM wavescan
WHERE model LIKE 'P703%' AND is_duplicate = false;

COMMENT ON VIEW v_wavescan_p703 IS 'P703 pickups only (32 zones). Convenience view over wavescan.';

CREATE VIEW v_wavescan_u704 AS
SELECT * FROM wavescan
WHERE model = 'U704' AND is_duplicate = false;

COMMENT ON VIEW v_wavescan_u704 IS 'U704 SUVs only (31 zones). Convenience view over wavescan.';


-- -------------------------------------------------------------
-- v_load_summary - one line per upload. First thing to check
--                  after loading a file.
-- -------------------------------------------------------------
CREATE VIEW v_load_summary AS
SELECT
    b.load_id,
    b.source_file,
    b.source_sheet,
    b.plant_code                                   AS plant,
    b.status,
    b.rows_in_file,
    b.rows_loaded,
    b.rows_duplicate,
    b.rows_rejected,
    b.rows_quarantine,
    (SELECT count(*) FROM reject_log r
      WHERE r.load_id = b.load_id AND r.status = 'NEW')      AS rejects_awaiting_review,
    (SELECT count(*) FROM unidentified_model u
      WHERE u.load_id = b.load_id AND u.status = 'NEW')      AS unidentified_awaiting_review,
    b.started_at,
    b.finished_at,
    b.finished_at - b.started_at                   AS duration,
    b.loaded_by
FROM load_batch b
ORDER BY b.load_id DESC;

COMMENT ON VIEW v_load_summary IS
    'Per-upload result: how many rows loaded, duplicated, rejected, quarantined.';


-- -------------------------------------------------------------
-- v_car_completeness - zones recorded per vehicle vs the count
--                      its model expects.
--
-- All 70 cars in the June/July 2026 files are complete, so this
-- is a monitor rather than a fix. It exists to catch a truncated
-- paste in a future upload.
-- -------------------------------------------------------------
CREATE VIEW v_car_completeness AS
SELECT
    w.plant,
    w.serial_no,
    w.model,
    w.measured_date,
    count(*)                       AS zones_recorded,
    m.expected_zone_count          AS zones_expected,
    m.expected_zone_count - count(*) AS zones_missing,
    CASE
        WHEN count(*) = m.expected_zone_count THEN 'COMPLETE'
        WHEN count(*) <  m.expected_zone_count THEN 'INCOMPLETE'
        ELSE 'EXCESS'
    END                            AS completeness
FROM wavescan w
JOIN ref_model m ON m.model_code = w.model
WHERE w.is_duplicate = false
GROUP BY w.plant, w.serial_no, w.model, w.measured_date, m.expected_zone_count;

COMMENT ON VIEW v_car_completeness IS
    'Per-vehicle zone count vs expected (P703=32, U704=31). Flags truncated uploads.';

