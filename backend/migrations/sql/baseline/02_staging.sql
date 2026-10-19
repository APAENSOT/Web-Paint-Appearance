-- =============================================================
-- 02_staging.sql
-- Load tracking + raw landing zone.
--
-- stg_raw is a verbatim copy of the Excel file, all TEXT, nothing
-- validated. It answers "what did the file actually say?" and
-- allows re-cleaning without asking the plants to resend.
-- Retention: 6 months.
--
-- Run against: paint_appearance
-- =============================================================


DROP TABLE IF EXISTS stg_raw     CASCADE;
DROP TABLE IF EXISTS load_batch  CASCADE;


-- -------------------------------------------------------------
-- LOAD BATCH - one row per uploaded sheet
-- -------------------------------------------------------------
CREATE TABLE load_batch (
    load_id         BIGSERIAL PRIMARY KEY,
    source_file     TEXT      NOT NULL,
    source_sheet    TEXT      NOT NULL,
    plant_code      TEXT      REFERENCES ref_plant,
    file_hash       TEXT,                       -- SHA256, detects a re-upload
    status          TEXT      NOT NULL DEFAULT 'RUNNING',

    rows_in_file    INTEGER   NOT NULL DEFAULT 0,
    rows_loaded     INTEGER   NOT NULL DEFAULT 0,
    rows_duplicate  INTEGER   NOT NULL DEFAULT 0,
    rows_rejected   INTEGER   NOT NULL DEFAULT 0,
    rows_quarantine INTEGER   NOT NULL DEFAULT 0,

    started_at      TIMESTAMP NOT NULL DEFAULT now(),
    finished_at     TIMESTAMP,
    loaded_by       TEXT      NOT NULL DEFAULT current_user,
    notes           TEXT,

    CONSTRAINT ck_batch_status CHECK (status IN ('RUNNING','SUCCESS','FAILED','ROLLED_BACK')),
    -- every row in the file must be accounted for somewhere
    CONSTRAINT ck_batch_balance CHECK (
        status <> 'SUCCESS'
        OR rows_in_file = rows_loaded + rows_duplicate + rows_rejected + rows_quarantine
    )
);
COMMENT ON TABLE  load_batch IS 'One row per uploaded sheet. Audit trail for every load.';
COMMENT ON COLUMN load_batch.file_hash IS 'SHA256 of the file, so an identical re-upload is detectable.';
COMMENT ON CONSTRAINT ck_batch_balance ON load_batch IS
    'A successful load must account for every row: loaded + duplicate + rejected + quarantined.';

CREATE INDEX idx_batch_file   ON load_batch (source_file, source_sheet);
CREATE INDEX idx_batch_status ON load_batch (status);
CREATE INDEX idx_batch_time   ON load_batch (started_at);


-- -------------------------------------------------------------
-- STG_RAW - verbatim copy of the sheet
--
-- All TEXT on purpose: a raw file may contain anything, and this
-- table must never reject a row. Validation happens downstream.
-- -------------------------------------------------------------
CREATE TABLE stg_raw (
    stg_id        BIGSERIAL PRIMARY KEY,
    load_id       BIGINT NOT NULL REFERENCES load_batch ON DELETE CASCADE,
    source_row    INTEGER NOT NULL,

    -- the 21 template columns exactly as they appeared
    raw_date            TEXT,
    raw_month           TEXT,
    raw_year            TEXT,
    raw_plant           TEXT,
    raw_model           TEXT,
    raw_checkzone       TEXT,
    raw_color           TEXT,
    raw_tolerance_group TEXT,
    raw_paintline       TEXT,
    raw_serial_no       TEXT,
    raw_lw TEXT, raw_sw TEXT, raw_cf TEXT, raw_doi TEXT, raw_du TEXT,
    raw_wa TEXT, raw_wb TEXT, raw_wc TEXT, raw_wd TEXT, raw_we TEXT,
    raw_b  TEXT,

    ingested_at   TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT uq_stg_source UNIQUE (load_id, source_row)
);
COMMENT ON TABLE stg_raw IS
    'Verbatim Excel copy, all TEXT. Never rejects. Retention 6 months.';

CREATE INDEX idx_stg_load ON stg_raw (load_id);
CREATE INDEX idx_stg_time ON stg_raw (ingested_at);


-- -------------------------------------------------------------
-- Retention: drop staging older than 6 months.
-- Deliberately manual - call it from a scheduled job.
-- Only ever touches SUCCESS batches, so a failed load stays
-- available for investigation.
-- -------------------------------------------------------------
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
    WHERE b.status = 'SUCCESS'
      AND b.finished_at < now() - make_interval(months => p_months);

    WITH doomed AS (
        SELECT load_id FROM load_batch
        WHERE status = 'SUCCESS'
          AND finished_at < now() - make_interval(months => p_months)
    ), zapped AS (
        DELETE FROM stg_raw WHERE load_id IN (SELECT load_id FROM doomed)
        RETURNING load_id
    )
    SELECT count(DISTINCT load_id) INTO v_batches FROM zapped;

    RETURN QUERY SELECT COALESCE(v_batches,0), COALESCE(v_rows,0);
END;
$$;

COMMENT ON FUNCTION purge_stg_raw IS
    'Delete staging rows for SUCCESS batches older than N months (default 6). load_batch is kept forever.';

