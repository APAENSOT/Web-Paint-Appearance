-- =============================================================
-- 03_wavescan.sql
-- The main measurement table.
--
-- One row per (vehicle x checkzone). One table for all plants,
-- all models, all months.
--
-- Four cleaning rules are enforced PHYSICALLY here, so bad data
-- cannot be stored even if the loader has a bug:
--
--   1. month/year are GENERATED from measured_date
--        -> a June car inside a July file lands in June. Always.
--   2. FK (model, checkzone) -> ref_model_zone
--        -> a U704 liftgate cannot be recorded on a P703 pickup.
--   3. FK (checkzone, tolerance_group) -> ref_checkzone
--        -> LCROOF can only ever be Horizontal.
--   4. UNIQUE (source_file, source_sheet, source_row)
--        -> the same spreadsheet row cannot be loaded twice.
--
-- Run against: paint_appearance
-- =============================================================


DROP TABLE IF EXISTS wavescan CASCADE;

CREATE TABLE wavescan (
    measurement_id   BIGSERIAL PRIMARY KEY,

    -- ==== the 21 template columns, in template order ==========
    measured_date    DATE     NOT NULL,
    month            SMALLINT GENERATED ALWAYS AS
                              (EXTRACT(MONTH FROM measured_date)::smallint) STORED,
    year             SMALLINT GENERATED ALWAYS AS
                              (EXTRACT(YEAR  FROM measured_date)::smallint) STORED,
    plant            TEXT     NOT NULL,
    model            TEXT     NOT NULL,
    checkzone        TEXT     NOT NULL,
    color            TEXT     NOT NULL,
    tolerance_group  TEXT     NOT NULL,
    paintline        TEXT     NOT NULL,
    serial_no        TEXT     NOT NULL,

    lw               REAL     NOT NULL,
    sw               REAL     NOT NULL,
    cf               REAL     NOT NULL,
    doi              REAL     NOT NULL,
    du               REAL     NOT NULL,
    wa               REAL     NOT NULL,
    wb               REAL     NOT NULL,
    wc               REAL     NOT NULL,
    wd               REAL     NOT NULL,
    we               REAL     NOT NULL,
    b                REAL         NULL,   -- absent in 481 of 2479 source rows

    -- ==== audit / lineage =====================================
    load_id          BIGINT    NOT NULL REFERENCES load_batch,
    source_file      TEXT      NOT NULL,
    source_sheet     TEXT      NOT NULL,
    source_row       INTEGER   NOT NULL,
    is_duplicate     BOOLEAN   NOT NULL DEFAULT false,
    loaded_at        TIMESTAMP NOT NULL DEFAULT now(),

    -- ==== referential integrity ===============================
    CONSTRAINT fk_ws_plant     FOREIGN KEY (plant)     REFERENCES ref_plant     (plant_code),
    CONSTRAINT fk_ws_color     FOREIGN KEY (color)     REFERENCES ref_color     (color_name),
    CONSTRAINT fk_ws_paintline FOREIGN KEY (paintline) REFERENCES ref_paintline (paintline_code),
    CONSTRAINT fk_ws_model     FOREIGN KEY (model)     REFERENCES ref_model     (model_code),

    -- zone must be valid FOR THIS MODEL
    CONSTRAINT fk_ws_model_zone FOREIGN KEY (model, checkzone)
        REFERENCES ref_model_zone (model_code, zone_code),

    -- tolerance must match what the zone master says
    CONSTRAINT fk_ws_zone_tol FOREIGN KEY (checkzone, tolerance_group)
        REFERENCES ref_checkzone (zone_code, tolerance_group),

    -- ==== value sanity ========================================
    -- gauge outputs are non-negative; B is a signed offset
    CONSTRAINT ck_ws_nonneg CHECK (
        lw >= 0 AND sw >= 0 AND cf >= 0 AND doi >= 0 AND du >= 0 AND
        wa >= 0 AND wb >= 0 AND wc >= 0 AND wd >= 0 AND we >= 0
    ),
    CONSTRAINT ck_ws_doi   CHECK (doi BETWEEN 0 AND 100),
    CONSTRAINT ck_ws_cf    CHECK (cf  BETWEEN 0 AND 100),
    CONSTRAINT ck_ws_b     CHECK (b IS NULL OR b BETWEEN -100 AND 100),
    CONSTRAINT ck_ws_date  CHECK (measured_date BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'),
    CONSTRAINT ck_ws_serial CHECK (length(trim(serial_no)) > 0),

    -- ==== no double-loading the same spreadsheet row ==========
    CONSTRAINT uq_ws_source UNIQUE (source_file, source_sheet, source_row)
);

COMMENT ON TABLE wavescan IS
    'Paint appearance measurements. One row per vehicle x checkzone. All plants, all models.';

COMMENT ON COLUMN wavescan.measured_date   IS 'Date the body was measured. Authoritative; month/year derive from it.';
COMMENT ON COLUMN wavescan.month           IS 'GENERATED from measured_date - cannot contradict it.';
COMMENT ON COLUMN wavescan.year            IS 'GENERATED from measured_date - cannot contradict it.';
COMMENT ON COLUMN wavescan.model           IS 'Canonical model. Bare "P703" is assumed to be RANGER.';
COMMENT ON COLUMN wavescan.checkzone       IS 'Canonical zone_code. Must be valid for this model.';
COMMENT ON COLUMN wavescan.color           IS 'Canonical colour name, paint code stripped.';
COMMENT ON COLUMN wavescan.tolerance_group IS 'Horizontal for HOOD/ROOF, Vertical otherwise. Derived, not trusted from file.';
COMMENT ON COLUMN wavescan.serial_no       IS 'Plant-local body number. NOT globally unique - always pair with plant.';
COMMENT ON COLUMN wavescan.b               IS 'Nullable: absent from 481 of 2479 source rows.';
COMMENT ON COLUMN wavescan.is_duplicate    IS 'Flagged by the >=80% similarity rule. Excluded from reporting views.';

COMMENT ON CONSTRAINT fk_ws_model_zone ON wavescan IS
    'Blocks impossible combinations such as a U704 liftgate zone on a P703 pickup.';
COMMENT ON CONSTRAINT fk_ws_zone_tol ON wavescan IS
    'Forces tolerance_group to agree with the zone master (HOOD/ROOF = Horizontal).';


-- -------------------------------------------------------------
-- Indexes
-- -------------------------------------------------------------
CREATE INDEX idx_ws_plant_date ON wavescan (plant, measured_date);
CREATE INDEX idx_ws_model      ON wavescan (model);
CREATE INDEX idx_ws_checkzone  ON wavescan (checkzone);
CREATE INDEX idx_ws_color      ON wavescan (color);
CREATE INDEX idx_ws_vehicle    ON wavescan (plant, serial_no);      -- identity is the PAIR
CREATE INDEX idx_ws_period     ON wavescan (year, month);
CREATE INDEX idx_ws_load       ON wavescan (load_id);
-- reporting normally excludes duplicates; partial index keeps that fast
CREATE INDEX idx_ws_clean      ON wavescan (plant, measured_date)
    WHERE is_duplicate = false;

