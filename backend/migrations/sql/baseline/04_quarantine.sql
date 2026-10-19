-- =============================================================
-- 04_quarantine.sql
-- Nothing is ever silently dropped.
--
-- A row that cannot be cleaned goes to reject_log with the reason
-- and its exact source location. A row whose model is unknown goes
-- to unidentified_model. Both are reviewed by a human in the
-- Phase 3 platform; both can be replayed once fixed.
--
-- Run against: paint_appearance
-- =============================================================


DROP TABLE IF EXISTS unidentified_model CASCADE;
DROP TABLE IF EXISTS reject_log         CASCADE;


-- -------------------------------------------------------------
-- REJECT LOG
-- -------------------------------------------------------------
CREATE TABLE reject_log (
    reject_id     BIGSERIAL PRIMARY KEY,
    load_id       BIGINT  NOT NULL REFERENCES load_batch ON DELETE CASCADE,

    source_file   TEXT    NOT NULL,
    source_sheet  TEXT    NOT NULL,
    source_row    INTEGER NOT NULL,

    reject_reason TEXT    NOT NULL,
    reject_detail TEXT,
    offending_column TEXT,
    offending_value  TEXT,

    -- the whole raw row, so it can be replayed without the file
    raw_row       JSONB   NOT NULL,

    -- review workflow
    status        TEXT    NOT NULL DEFAULT 'NEW',
    reviewed_by   TEXT,
    reviewed_at   TIMESTAMP,
    resolution    TEXT,

    created_at    TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT ck_reject_reason CHECK (reject_reason IN (
        'UNKNOWN_PLANT',
        'UNKNOWN_MODEL',
        'UNKNOWN_CHECKZONE',
        'UNKNOWN_COLOR',
        'UNKNOWN_PAINTLINE',
        'ZONE_NOT_VALID_FOR_MODEL',
        'MISSING_MEASUREMENT',
        'MISSING_REQUIRED_FIELD',
        'BAD_DATE',
        'BAD_NUMBER',
        'OUT_OF_RANGE',
        'DUPLICATE_ROW',
        'OTHER'
    )),
    CONSTRAINT ck_reject_status CHECK (status IN ('NEW','REVIEWING','FIXED','IGNORED'))
);

COMMENT ON TABLE  reject_log IS
    'Rows that failed cleaning. Nothing is discarded silently. Reviewed via the platform.';
COMMENT ON COLUMN reject_log.raw_row IS
    'Complete original row as JSON, so it can be replayed after an alias is added.';
COMMENT ON COLUMN reject_log.reject_reason IS
    'UNKNOWN_* means a new spelling appeared and needs an alias row - the expected monthly case.';

CREATE INDEX idx_reject_load   ON reject_log (load_id);
CREATE INDEX idx_reject_status ON reject_log (status) WHERE status = 'NEW';
CREATE INDEX idx_reject_reason ON reject_log (reject_reason);


-- -------------------------------------------------------------
-- UNIDENTIFIED MODEL
--
-- Separate from reject_log because these rows are otherwise
-- perfectly valid - only the model is unknown. Known case:
-- AAT June 2026 serial 2478755, 31 rows, model literally "(None)".
-- Its 31-zone set is byte-identical to U704, so it is almost
-- certainly U704 - but we quarantine rather than guess.
-- -------------------------------------------------------------
CREATE TABLE unidentified_model (
    unid_id       BIGSERIAL PRIMARY KEY,
    load_id       BIGINT  NOT NULL REFERENCES load_batch ON DELETE CASCADE,

    source_file   TEXT    NOT NULL,
    source_sheet  TEXT    NOT NULL,
    source_row    INTEGER NOT NULL,

    raw_model     TEXT,
    plant         TEXT    REFERENCES ref_plant,
    serial_no     TEXT,
    measured_date DATE,
    zone_count    SMALLINT,          -- 31 hints U704, 32 hints P703
    suggested_model TEXT REFERENCES ref_model,

    raw_row       JSONB   NOT NULL,

    status        TEXT    NOT NULL DEFAULT 'NEW',
    resolved_model TEXT   REFERENCES ref_model,
    reviewed_by   TEXT,
    reviewed_at   TIMESTAMP,

    created_at    TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT ck_unid_status CHECK (status IN ('NEW','REVIEWING','RESOLVED','IGNORED')),
    CONSTRAINT ck_unid_resolved CHECK (status <> 'RESOLVED' OR resolved_model IS NOT NULL)
);

COMMENT ON TABLE  unidentified_model IS
    'Valid measurements whose model could not be identified. Human decides; then replay.';
COMMENT ON COLUMN unidentified_model.zone_count IS
    'Zones recorded for this vehicle. 31 suggests U704, 32 suggests P703.';
COMMENT ON COLUMN unidentified_model.suggested_model IS
    'Loader best guess from zone fingerprint. Advisory only - never auto-applied.';

CREATE INDEX idx_unid_load   ON unidentified_model (load_id);
CREATE INDEX idx_unid_status ON unidentified_model (status) WHERE status = 'NEW';

