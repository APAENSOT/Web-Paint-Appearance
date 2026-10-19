-- =============================================================
-- 01_reference.sql
-- Reference (master) tables + alias mappings.
--
-- These tables ARE the cleaning rules. The loader never contains
-- a hard-coded spelling: it looks every raw value up in an alias
-- table. A new spelling next month = one INSERT here, no code change.
--
-- Run against: paint_appearance
-- Re-runnable: drops and rebuilds all reference tables.
-- =============================================================


DROP TABLE IF EXISTS ref_model_zone      CASCADE;
DROP TABLE IF EXISTS ref_checkzone_alias CASCADE;
DROP TABLE IF EXISTS ref_checkzone       CASCADE;
DROP TABLE IF EXISTS ref_color_alias     CASCADE;
DROP TABLE IF EXISTS ref_color           CASCADE;
DROP TABLE IF EXISTS ref_paintline_alias CASCADE;
DROP TABLE IF EXISTS ref_paintline       CASCADE;
DROP TABLE IF EXISTS ref_model_alias     CASCADE;
DROP TABLE IF EXISTS ref_model           CASCADE;
DROP TABLE IF EXISTS ref_plant_alias     CASCADE;
DROP TABLE IF EXISTS ref_plant           CASCADE;


-- -------------------------------------------------------------
-- PLANT
-- -------------------------------------------------------------
CREATE TABLE ref_plant (
    plant_code  TEXT PRIMARY KEY,
    plant_name  TEXT NOT NULL,
    country     TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true
);
COMMENT ON TABLE ref_plant IS 'Manufacturing plants. Phase 1 = AAT, FTM.';

INSERT INTO ref_plant (plant_code, plant_name, country) VALUES
    ('AAT', 'AutoAlliance Thailand', 'Thailand'),
    ('FTM', 'Ford Thailand Manufacturing', 'Thailand');

CREATE TABLE ref_plant_alias (
    raw_value   TEXT PRIMARY KEY,
    plant_code  TEXT NOT NULL REFERENCES ref_plant
);
INSERT INTO ref_plant_alias (raw_value, plant_code) VALUES
    ('AAT', 'AAT'),
    ('FTM', 'FTM');


-- -------------------------------------------------------------
-- MODEL
-- expected_zone_count drives the per-car completeness report.
-- Verified: every P703 has 32 zones, every U704 has 31.
-- -------------------------------------------------------------
CREATE TABLE ref_model (
    model_code          TEXT PRIMARY KEY,
    model_family        TEXT     NOT NULL,          -- P703 | U704
    body_style          TEXT     NOT NULL,          -- PICKUP | SUV
    expected_zone_count SMALLINT NOT NULL,
    is_active           BOOLEAN  NOT NULL DEFAULT true,
    CONSTRAINT ck_model_body CHECK (body_style IN ('PICKUP','SUV'))
);
COMMENT ON COLUMN ref_model.expected_zone_count IS
    'Zones a complete vehicle of this model must have. P703=32, U704=31.';

INSERT INTO ref_model (model_code, model_family, body_style, expected_zone_count) VALUES
    ('P703 DBL RANGER',     'P703', 'PICKUP', 32),
    ('P703 DBL RAPTOR',     'P703', 'PICKUP', 32),
    ('P703 DBL SUPER DUTY', 'P703', 'PICKUP', 32),
    ('U704',                'U704', 'SUV',    31);

CREATE TABLE ref_model_alias (
    raw_value   TEXT PRIMARY KEY,
    model_code  TEXT NOT NULL REFERENCES ref_model,
    note        TEXT
);
COMMENT ON TABLE ref_model_alias IS
    'Raw model spellings -> canonical. Bare "P703"/"P703 DBL" default to RANGER.';

INSERT INTO ref_model_alias (raw_value, model_code, note) VALUES
    ('P703',                'P703 DBL RANGER',     'ASSUMPTION: no variant named => RANGER'),
    ('P703 DBL',            'P703 DBL RANGER',     'ASSUMPTION: no variant named => RANGER'),
    ('P703 DBL-RANGER',     'P703 DBL RANGER',     NULL),
    ('P703 DBL RANGER',     'P703 DBL RANGER',     NULL),
    ('P703 RAPTOR',         'P703 DBL RAPTOR',     NULL),
    ('Raptor',              'P703 DBL RAPTOR',     NULL),
    ('P703 DBL RAPTOR',     'P703 DBL RAPTOR',     NULL),
    ('P703 DBL-Super duty', 'P703 DBL SUPER DUTY', NULL),
    ('P703 DBL SUPER DUTY', 'P703 DBL SUPER DUTY', NULL),
    ('U704',                'U704',                NULL);


-- -------------------------------------------------------------
-- CHECKZONE  (49 canonical physical positions)
--
-- tolerance_group is a PROPERTY OF THE ZONE, not of the row.
-- Rule verified 49/49 against AAT+FTM: name contains HOOD or ROOF
-- => Horizontal, everything else => Vertical.
-- The source files contradict themselves on 36 rows; this table
-- is the authority and the FK from wavescan forces agreement.
-- -------------------------------------------------------------
CREATE TABLE ref_checkzone (
    zone_code       TEXT PRIMARY KEY,          -- compact key,  e.g. LFBOX
    zone_name       TEXT NOT NULL,             -- readable,     e.g. 'LF Box'
    panel_group     TEXT NOT NULL,             -- HOOD ROOF FENDER DOOR BOX TAILGATE LIFTGATE PILLAR
    tolerance_group TEXT NOT NULL,
    CONSTRAINT ck_zone_tol  CHECK (tolerance_group IN ('Horizontal','Vertical')),
    -- the HOOD/ROOF rule, enforced so no future insert can break it
    CONSTRAINT ck_zone_rule CHECK (
        tolerance_group = CASE
            WHEN zone_code LIKE '%HOOD%' OR zone_code LIKE '%ROOF%'
            THEN 'Horizontal' ELSE 'Vertical' END
    ),
    -- needed as an FK target from wavescan
    CONSTRAINT uq_zone_tol UNIQUE (zone_code, tolerance_group)
);
COMMENT ON TABLE ref_checkzone IS
    '49 canonical measurement positions. Tolerance derived from panel type.';

INSERT INTO ref_checkzone (zone_code, zone_name, panel_group, tolerance_group) VALUES
    -- Hood (shared) -------------------------------------------------
    ('RRHOOD',        'RR Hood',            'HOOD',     'Horizontal'),
    ('RFHOOD',        'RF Hood',            'HOOD',     'Horizontal'),
    ('CFHOOD',        'CF Hood',            'HOOD',     'Horizontal'),
    ('LFHOOD',        'LF Hood',            'HOOD',     'Horizontal'),
    ('LRHOOD',        'LR Hood',            'HOOD',     'Horizontal'),
    -- Roof (shared) -------------------------------------------------
    ('LCROOF',        'LC Roof',            'ROOF',     'Horizontal'),
    ('RCROOF',        'RC Roof',            'ROOF',     'Horizontal'),
    -- Fender / door / pillar (shared) -------------------------------
    ('LFFENDER',      'LF Fender',          'FENDER',   'Vertical'),
    ('LCFENDER',      'LC Fender',          'FENDER',   'Vertical'),
    ('LRFENDER',      'LR Fender',          'FENDER',   'Vertical'),
    ('LTFDOOR',       'LT Front Door',      'DOOR',     'Vertical'),
    ('LCFDOOR',       'LC Front Door',      'DOOR',     'Vertical'),
    ('LCRDOOR',       'LC Rear Door',       'DOOR',     'Vertical'),
    ('LCPILLAR',      'LC Pillar',          'PILLAR',   'Vertical'),

    -- P703 only: cargo box, tailgate, RH side ------------------------
    ('LFBOX',         'LF Box',             'BOX',      'Vertical'),   -- src typo 'LFBoox'
    ('LCBOX',         'LC Box',             'BOX',      'Vertical'),
    ('LRBOX',         'LR Box',             'BOX',      'Vertical'),
    ('LTTAILGATE',    'LT Tailgate',        'TAILGATE', 'Vertical'),   -- src typo 'LTTailagte'
    ('LBTAILGATE',    'LB Tailgate',        'TAILGATE', 'Vertical'),   -- src typo 'LBTailagte'
    ('LCTAILGATE',    'LC Tailgate',        'TAILGATE', 'Vertical'),   -- src typo 'LCTailagate'
    ('RBTAILGATE',    'RB Tailgate',        'TAILGATE', 'Vertical'),
    ('RTTAILGATE',    'RT Tailgate',        'TAILGATE', 'Vertical'),
    ('RRBOX',         'RR Box',             'BOX',      'Vertical'),
    ('RCBOX',         'RC Box',             'BOX',      'Vertical'),
    ('RFBOX',         'RF Box',             'BOX',      'Vertical'),
    ('RCPILLAR',      'RC Pillar',          'PILLAR',   'Vertical'),
    ('RCRDOOR',       'RC Rear Door',       'DOOR',     'Vertical'),
    ('RCFDOOR',       'RC Front Door',      'DOOR',     'Vertical'),
    ('FTFDOOR',       'FT Front Door',      'DOOR',     'Vertical'),
    ('RRFENDER',      'RR Fender',          'FENDER',   'Vertical'),
    ('RCFENDER',      'RC Fender',          'FENDER',   'Vertical'),
    ('RFFENDER',      'RF Fender',          'FENDER',   'Vertical'),

    -- U704 only: liftgate, rear quarter, RH detail -------------------
    ('RFENDERHILH',   'R Fender Hi LH',     'FENDER',   'Vertical'),
    ('RFENDERMIDLH',  'R Fender Mid LH',    'FENDER',   'Vertical'),
    ('RFENDERLOWLH',  'R Fender Low LH',    'FENDER',   'Vertical'),
    ('LIFTGATEHILH',  'Liftgate Hi LH',     'LIFTGATE', 'Vertical'),
    ('LIFTGATELOWLH', 'Liftgate Low LH',    'LIFTGATE', 'Vertical'),
    ('LIFTGATELOWRH', 'Liftgate Low RH',    'LIFTGATE', 'Vertical'),
    ('LIFTGATEHIRH',  'Liftgate Hi RH',     'LIFTGATE', 'Vertical'),
    ('RRFENLOWRH',    'Rr Fender Low RH',   'FENDER',   'Vertical'),
    ('RRFENMIDRH',    'Rr Fender Mid RH',   'FENDER',   'Vertical'),
    ('RRFENHIRH',     'Rr Fender Hi RH',    'FENDER',   'Vertical'),
    ('RRPILLARRH',    'Rr Pillar RH',       'PILLAR',   'Vertical'),
    ('RRDOORMIDRH',   'Rr Door Mid RH',     'DOOR',     'Vertical'),
    ('FRDOORMIDRH',   'Fr Door Mid RH',     'DOOR',     'Vertical'),
    ('FRDOORHIRH',    'Fr Door Hi RH',      'DOOR',     'Vertical'),
    ('FRFENRH1',      'Fr Fender RH1',      'FENDER',   'Vertical'),
    ('FRFENRH2',      'Fr Fender RH2',      'FENDER',   'Vertical'),
    ('FRFENRH3',      'Fr Fender RH3',      'FENDER',   'Vertical');

CREATE TABLE ref_checkzone_alias (
    raw_value   TEXT PRIMARY KEY,
    zone_code   TEXT NOT NULL REFERENCES ref_checkzone,
    note        TEXT
);
COMMENT ON TABLE ref_checkzone_alias IS
    'Raw zone strings (incl. leading number) -> canonical zone_code.';

INSERT INTO ref_checkzone_alias (raw_value, zone_code, note) VALUES
    -- shared, as written by AAT and FTM
    ('01 RRHOOD','RRHOOD',NULL),          ('02 RFHOOD','RFHOOD',NULL),
    ('03 CFHOOD','CFHOOD',NULL),          ('04 LFHOOD','LFHOOD',NULL),
    ('05 LRHOOD','LRHOOD',NULL),
    ('06 LFFender','LFFENDER',NULL),      ('06LFFENDER','LFFENDER',NULL),
    ('07 LCFender','LCFENDER',NULL),      ('08 LRFender','LRFENDER',NULL),
    ('09 LTFDoor','LTFDOOR',NULL),        ('10 LCFDoor','LCFDOOR',NULL),
    ('11 LCRoof','LCROOF',NULL),          ('12 LCRDoor','LCRDOOR',NULL),
    ('13 LCPillar','LCPILLAR',NULL),
    -- P703 box / tailgate  (typos corrected)
    ('14 LFBoox','LFBOX','source typo: Boox -> Box'),
    ('15 LCBox','LCBOX',NULL),            ('16 LRBox','LRBOX',NULL),
    ('17 LTTailagte','LTTAILGATE','source typo: Tailagte -> Tailgate'),
    ('18 LBTailagte','LBTAILGATE','source typo: Tailagte -> Tailgate'),
    ('19 LCTailagate','LCTAILGATE','source typo: Tailagate -> Tailgate'),
    ('20 RBTailgate','RBTAILGATE',NULL),  ('21RTTailgate','RTTAILGATE',NULL),
    ('22 RRBox','RRBOX',NULL),            ('23 RCBox','RCBOX',NULL),
    ('24 RFBox','RFBOX',NULL),            ('25 RCPillar','RCPILLAR',NULL),
    ('26 RCRDoor','RCRDOOR',NULL),        ('27 RCRoof','RCROOF',NULL),
    ('28 RCFDoor','RCFDOOR',NULL),        ('29 FTFDoor','FTFDOOR',NULL),
    ('30 RRFender','RRFENDER',NULL),      ('31 RCFender','RCFENDER',NULL),
    ('32 RFFender','RFFENDER',NULL),
    -- U704 liftgate / rear quarter
    ('14 RFENDER HI LH','RFENDERHILH',NULL),
    ('15 RFENDER MID LH','RFENDERMIDLH',NULL),
    ('16 RFENDER LOW LH','RFENDERLOWLH',NULL),
    ('17 Liftgate Hi LH','LIFTGATEHILH',NULL),
    ('18 Liftgate Low LH','LIFTGATELOWLH',NULL),
    ('19 Liftgate Low RH','LIFTGATELOWRH',NULL),
    ('20 Liftgate Hi RH','LIFTGATEHIRH',NULL),
    ('21 Rr Fen Low RH','RRFENLOWRH',NULL),
    ('22 Rr Fen Mid RH','RRFENMIDRH',NULL),
    ('23 Rr Fen Hi RH','RRFENHIRH',NULL),
    ('24 Rr Pillar RH','RRPILLARRH',NULL),
    ('25 Rr Door Mid RH','RRDOORMIDRH',NULL),
    ('26 RCROOF','RCROOF',NULL),
    ('27 Fr Door Mid RH','FRDOORMIDRH',NULL),
    ('28 Fr Door Hi RH','FRDOORHIRH',NULL),
    ('29 Fr Fen RH3','FRFENRH3',NULL),
    ('30 Fr Fen RH2','FRFENRH2',NULL),
    ('31 Fr Fen RH1','FRFENRH1',NULL);


-- -------------------------------------------------------------
-- MODEL <-> ZONE   (which zones exist on which model, and at
--                   what number). 32 + 31 = 63 rows.
--
-- This is the table that makes it IMPOSSIBLE to record a U704
-- liftgate on a P703 pickup.
-- -------------------------------------------------------------
CREATE TABLE ref_model_zone (
    model_code  TEXT     NOT NULL REFERENCES ref_model,
    zone_code   TEXT     NOT NULL REFERENCES ref_checkzone,
    zone_no     SMALLINT NOT NULL,
    PRIMARY KEY (model_code, zone_code),
    CONSTRAINT uq_model_zoneno UNIQUE (model_code, zone_no),
    CONSTRAINT ck_zone_no CHECK (zone_no BETWEEN 1 AND 40)
);
COMMENT ON TABLE ref_model_zone IS
    'Valid zones per model. zone_no is model-relative: RCROOF is #27 on P703 but #26 on U704.';

-- P703 variants: identical 32-zone layout
INSERT INTO ref_model_zone (model_code, zone_code, zone_no)
SELECT m.model_code, z.zone_code, z.zone_no
FROM (VALUES
    ('RRHOOD',1),('RFHOOD',2),('CFHOOD',3),('LFHOOD',4),('LRHOOD',5),
    ('LFFENDER',6),('LCFENDER',7),('LRFENDER',8),('LTFDOOR',9),('LCFDOOR',10),
    ('LCROOF',11),('LCRDOOR',12),('LCPILLAR',13),('LFBOX',14),('LCBOX',15),
    ('LRBOX',16),('LTTAILGATE',17),('LBTAILGATE',18),('LCTAILGATE',19),
    ('RBTAILGATE',20),('RTTAILGATE',21),('RRBOX',22),('RCBOX',23),('RFBOX',24),
    ('RCPILLAR',25),('RCRDOOR',26),('RCROOF',27),('RCFDOOR',28),('FTFDOOR',29),
    ('RRFENDER',30),('RCFENDER',31),('RFFENDER',32)
) AS z(zone_code, zone_no)
CROSS JOIN (VALUES
    ('P703 DBL RANGER'),('P703 DBL RAPTOR'),('P703 DBL SUPER DUTY')
) AS m(model_code);

-- U704: 31 zones. Note RCROOF sits at #26 here, not #27.
INSERT INTO ref_model_zone (model_code, zone_code, zone_no) VALUES
    ('U704','RRHOOD',1),        ('U704','RFHOOD',2),        ('U704','CFHOOD',3),
    ('U704','LFHOOD',4),        ('U704','LRHOOD',5),        ('U704','LFFENDER',6),
    ('U704','LCFENDER',7),      ('U704','LRFENDER',8),      ('U704','LTFDOOR',9),
    ('U704','LCFDOOR',10),      ('U704','LCROOF',11),       ('U704','LCRDOOR',12),
    ('U704','LCPILLAR',13),     ('U704','RFENDERHILH',14),  ('U704','RFENDERMIDLH',15),
    ('U704','RFENDERLOWLH',16), ('U704','LIFTGATEHILH',17), ('U704','LIFTGATELOWLH',18),
    ('U704','LIFTGATELOWRH',19),('U704','LIFTGATEHIRH',20), ('U704','RRFENLOWRH',21),
    ('U704','RRFENMIDRH',22),   ('U704','RRFENHIRH',23),    ('U704','RRPILLARRH',24),
    ('U704','RRDOORMIDRH',25),  ('U704','RCROOF',26),       ('U704','FRDOORMIDRH',27),
    ('U704','FRDOORHIRH',28),   ('U704','FRFENRH3',29),     ('U704','FRFENRH2',30),
    ('U704','FRFENRH1',31);


-- -------------------------------------------------------------
-- COLOR   32 raw spellings -> 13 canonical
-- Cleaning: strip trailing BC/MC -> strip leading paint code
--           -> spelling fixes -> Title Case
-- -------------------------------------------------------------
CREATE TABLE ref_color (
    color_name  TEXT PRIMARY KEY,
    color_group TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true
);

INSERT INTO ref_color (color_name, color_group) VALUES
    ('Acacia Green',       'GREEN'),
    ('Aluminum Metallic',  'SILVER'),
    ('Arctic White',       'WHITE'),
    ('Blue Lightning',     'BLUE'),
    ('Code Orange',        'ORANGE'),
    ('Command Grey',       'GREY'),
    ('Desert Island Blue', 'BLUE'),
    ('Ignite Orange',      'ORANGE'),
    ('Meteor Grey',        'GREY'),
    ('Pearl White',        'WHITE'),
    ('Seismic Tan',        'TAN'),
    ('Shadow Black',       'BLACK'),
    ('Traction Green',     'GREEN');

CREATE TABLE ref_color_alias (
    raw_value  TEXT PRIMARY KEY,
    color_name TEXT NOT NULL REFERENCES ref_color,
    note       TEXT
);
COMMENT ON TABLE ref_color_alias IS
    'Every raw colour spelling seen in AAT/FTM June-July 2026.';

INSERT INTO ref_color_alias (raw_value, color_name, note) VALUES
    ('5GR Acacia Green',            'Acacia Green',      NULL),
    ('Acacia Green',                'Acacia Green',      NULL),
    ('38P Aluminium Metallic',      'Aluminum Metallic', 'UK spelling'),
    ('38P Aluminum Metallic MC',    'Aluminum Metallic', NULL),
    ('LM-38 Aluminum Metallic BC',  'Aluminum Metallic', NULL),
    ('Aluminum Metallic',           'Aluminum Metallic', NULL),
    ('A4D Arctic White',            'Arctic White',      NULL),
    ('A4D Arctic White MC',         'Arctic White',      NULL),
    ('LS-A4 Arctic White BC',       'Arctic White',      NULL),
    ('Arctic White',                'Arctic White',      NULL),
    ('MM- Blue Lightning BC',       'Blue Lightning',    NULL),
    ('Blue Lightning',              'Blue Lightning',    NULL),
    ('MS-2R Code Orange BC',        'Code Orange',       NULL),
    ('Code Orange',                 'Code Orange',       NULL),
    ('5ZT Command Gray',            'Command Grey',      'US spelling'),
    ('5ZT Command Grey',            'Command Grey',      NULL),
    ('MS-5C Command Grey BC',       'Command Grey',      NULL),
    ('Command Grey',                'Command Grey',      NULL),
    ('JDC Desert Island Blue',      'Desert Island Blue',NULL),
    ('Desert Island Blue',          'Desert Island Blue',NULL),
    ('58S Ignight Orange',          'Ignite Orange',     'source typo: Ignight'),
    ('58S Ignite Orange',           'Ignite Orange',     NULL),
    ('MS-58S Ignite Orange BC',     'Ignite Orange',     NULL),
    ('Ignite Orange',               'Ignite Orange',     NULL),
    ('42A Meteor Gray MC',          'Meteor Grey',       'US spelling'),
    ('42A Meteor Grey',             'Meteor Grey',       NULL),
    ('MM-42 Meteo Grey BC',         'Meteor Grey',       'source typo: Meteo'),
    ('Meteor Grey',                 'Meteor Grey',       NULL),
    ('25D Pearl White MC',          'Pearl White',       NULL),
    ('5TR Seismic tan',             'Seismic Tan',       NULL),
    ('DM-G9 Shadow Black BC',       'Shadow Black',      NULL),
    ('G9Z Shadow Black',            'Shadow Black',      NULL),
    ('G9Z Shadow black',            'Shadow Black',      NULL),
    ('Shadow Black',                'Shadow Black',      NULL),
    ('3HC Traction Green',          'Traction Green',    NULL),
    ('Traction Green',              'Traction Green',    NULL);


-- -------------------------------------------------------------
-- PAINTLINE
-- -------------------------------------------------------------
CREATE TABLE ref_paintline (
    paintline_code TEXT PRIMARY KEY,
    booth_no       SMALLINT NOT NULL,
    CONSTRAINT ck_paintline_fmt CHECK (paintline_code ~ '^BOOTH[0-9]+$')
);
INSERT INTO ref_paintline (paintline_code, booth_no) VALUES
    ('BOOTH1', 1),
    ('BOOTH2', 2);

CREATE TABLE ref_paintline_alias (
    raw_value      TEXT PRIMARY KEY,
    paintline_code TEXT NOT NULL REFERENCES ref_paintline
);
INSERT INTO ref_paintline_alias (raw_value, paintline_code) VALUES
    ('BOOTH1',  'BOOTH1'),
    ('BOOTH 1', 'BOOTH1'),
    ('Booth1',  'BOOTH1'),
    ('BOOTH2',  'BOOTH2'),
    ('BOOTH 2', 'BOOTH2'),
    ('Booth2',  'BOOTH2');

