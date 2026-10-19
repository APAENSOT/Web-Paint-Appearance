-- =============================================================
-- 12_sap_vocabulary.sql
-- Phase 2 of the multi-plant Template Adapter Layer:
-- header/value adapter groundwork for SAP.
--
-- WHAT THIS FILE DOES
--   1. Registers J73 DBL as a new SINGLE-PLANT model, with its
--      own 32 canonical checkzones under ITS OWN names (per the
--      agreed rule: single-plant models keep their own naming,
--      only the leading position number is stripped - verified
--      safe: J73's 32 raw zone strings stay 32 distinct names
--      after stripping the number, no collision).
--   2. Adds 8 new canonical colours and 12 colour aliases seen
--      in the SAP July 2026 file (shared by both J73 and P703
--      DBL at SAP), using the SAME mechanical rule already used
--      for every AAT/FTM colour: strip the leading paint code,
--      Title Case. This is not a judgement call about physical
--      identity (unlike zone mapping) - the colour name IS the
--      value, stripping a code prefix is purely mechanical.
--
-- WHAT THIS FILE DELIBERATELY DOES NOT DO
--   - Does NOT register plant 'SAP' in ref_plant, and does NOT
--     add it to WAVESCAN_ALLOWED_PLANTS. SAP's P703 DBL rows
--     need the checkzone MAPPED to the existing AAT/FTM/FVL
--     canonical zone_codes (RRHOOD, RCROOF, ...) via
--     ref_plant_zone_map with human approval - that is Phase 3
--     (the mapping engine + review UI), not this file. Adding
--     SAP as a plant now, before that mapping exists, would let
--     J73 rows load while every P703 DBL row from the same file
--     rejects with UNKNOWN_CHECKZONE - a confusing half-working
--     state. SAP onboarding (Phase 4) happens only after Phase 3.
--   - Does NOT add an alias for the raw model string 'P703 RAP'.
--     Confirmed by the plant contact: Raptor is FTM-only. SAP's
--     64 'P703 RAP' rows (sheet 'P703 JULY 2026', rows 66-129)
--     are an anomaly, not a real variant - they must keep failing
--     UNKNOWN_MODEL so a human reviews them, never silently guess
--     they mean something.
--   - Does NOT touch FVL. FVL is investigation-only (Phase 5) and
--     uses a completely different colour-code convention anyway
--     (e.g. 'FW - Frozen White' vs SAP's 'LS FROZEN WHITE') so
--     there is no shared vocabulary to add yet.
--
-- Run against: paint_appearance
-- Re-runnable: ON CONFLICT DO NOTHING on every insert.
-- =============================================================


-- -------------------------------------------------------------
-- 1. J73 DBL - new single-plant model
--
-- Body style: the raw zone list contains Box + Tailgate zones
-- (positions 14-24), the same signature P703 (PICKUP) has.
-- U704 (SUV) has no Box/Tailgate at all - it has a Liftgate
-- instead. This is evidence from J73's OWN zone list, not an
-- assumption borrowed from outside data.
-- -------------------------------------------------------------
INSERT INTO ref_model (model_code, model_family, body_style, expected_zone_count)
VALUES ('J73 DBL', 'J73', 'PICKUP', 32)
ON CONFLICT (model_code) DO NOTHING;

INSERT INTO ref_model_alias (raw_value, model_code, note)
VALUES ('J73 DBL', 'J73 DBL', 'SAP single-plant model - own name kept as canonical')
ON CONFLICT (raw_value) DO NOTHING;


-- -------------------------------------------------------------
-- J73 DBL - 32 canonical checkzones, J73's own naming.
--
-- zone_code is built from the raw text with the leading number
-- stripped and spaces removed (mechanical, not interpretive).
-- Verified before writing this file: stripping the number leaves
-- 32 distinct strings, so no collision like FVL's (FVL keeps its
-- number for exactly this reason - J73 does not need to).
--
-- FD = Front Door, RD = Rear Door: inferred from the SAME
-- abbreviation family AAT/FTM already use (LTFDOOR/LCFDOOR are
-- front doors, LCRDOOR is a rear door) and from position order
-- (FD Frnt/Rr sit next to Fender zones near the front; RD RR sits
-- next to the roof/pillar toward the rear). Both resolve to
-- panel_group DOOR and tolerance_group Vertical either way, so
-- even if the FD/RD split is imperfect it cannot cause a wrong
-- Horizontal/Vertical classification or a wrong FK.
--
-- Source typo preserved and noted: item 31 says 'Middl' not
-- 'Middle', matching the project's existing practice of keeping
-- and commenting typos rather than silently correcting them.
-- -------------------------------------------------------------
INSERT INTO ref_checkzone (zone_code, zone_name, panel_group, tolerance_group) VALUES
    ('RHSHOODRR',      'RHS Hood Rr',        'HOOD',     'Horizontal'),
    ('RHSHOODFRNT',    'RHS Hood Frnt',      'HOOD',     'Horizontal'),
    ('HOODMIDDLE',     'Hood Middle',        'HOOD',     'Horizontal'),
    ('LHSHOODFRNT',    'LHS Hood Frnt',      'HOOD',     'Horizontal'),
    ('LHSHOODRR',      'LHS Hood Rr',        'HOOD',     'Horizontal'),
    ('LHSFENDERFRNT',  'LHS Fender Frnt',    'FENDER',   'Vertical'),
    ('LHSFENDERMID',   'LHS Fender Middle',  'FENDER',   'Vertical'),
    ('LHSFENDERRR',    'LHS Fender Rr',      'FENDER',   'Vertical'),
    ('LHSFDOORFRNT',   'LHS Front Door Frnt','DOOR',     'Vertical'),
    ('LHSFDOORRR',     'LHS Front Door Rr',  'DOOR',     'Vertical'),
    ('LHSROOF',        'LHS Roof',           'ROOF',     'Horizontal'),
    ('LHSRDOORRR',     'LHS Rear Door Rr',   'DOOR',     'Vertical'),
    ('LHSCPILLAR',     'LHS C-Pillar',       'PILLAR',   'Vertical'),
    ('LHSBOXFRNT',     'LHS Box Frnt',       'BOX',      'Vertical'),
    ('LHSBOXMID',      'LHS Box Middle',     'BOX',      'Vertical'),
    ('LHSBOXRR',       'LHS Box Rr',         'BOX',      'Vertical'),
    ('LHSTGTOP',       'LHS Tailgate Top',   'TAILGATE', 'Vertical'),
    ('LHSTGBOT',       'LHS Tailgate Bot',   'TAILGATE', 'Vertical'),
    ('TGMIDDLE',       'Tailgate Middle',    'TAILGATE', 'Vertical'),
    ('RHSTGTOP',       'RHS Tailgate Top',   'TAILGATE', 'Vertical'),
    ('RHSTGBOT',       'RHS Tailgate Bot',   'TAILGATE', 'Vertical'),
    ('RHSBOXRR',       'RHS Box Rr',         'BOX',      'Vertical'),
    ('RHSBOXMID',      'RHS Box Middle',     'BOX',      'Vertical'),
    ('RHSBOXFRNT',     'RHS Box Frnt',       'BOX',      'Vertical'),
    ('RHSCPILLAR',     'RHS C-Pillar',       'PILLAR',   'Vertical'),
    ('RHSRDOORRR',     'RHS Rear Door Rr',   'DOOR',     'Vertical'),
    ('RHSROOF',        'RHS Roof',           'ROOF',     'Horizontal'),
    ('RHSFDOORRR',     'RHS Front Door Rr',  'DOOR',     'Vertical'),
    ('RHSFDOORFRNT',   'RHS Front Door Frnt','DOOR',     'Vertical'),
    ('RHSFENDERRR',    'RHS Fender Rr',      'FENDER',   'Vertical'),
    ('RHSFENDERMID',   'RHS Fender Middle',  'FENDER',   'Vertical'),
    ('RHSFENDERFRNT',  'RHS Fender Frnt',    'FENDER',   'Vertical')
ON CONFLICT (zone_code) DO NOTHING;

INSERT INTO ref_checkzone_alias (raw_value, zone_code, note) VALUES
    ('01RHS Hood Rr28',      'RHSHOODRR',     NULL),
    ('02RHS Hood Frnt29',    'RHSHOODFRNT',   NULL),
    ('03Hood Middle30',      'HOODMIDDLE',    NULL),
    ('04LHS Hood Frnt31',    'LHSHOODFRNT',   NULL),
    ('05LHS Hood Rr32',      'LHSHOODRR',     NULL),
    ('06LHS Fender Frnt1',   'LHSFENDERFRNT', NULL),
    ('07LHS Fender Middle2', 'LHSFENDERMID',  NULL),
    ('08LHS Fender Rr3',     'LHSFENDERRR',   NULL),
    ('09LHS FD Frnt4',       'LHSFDOORFRNT',  'FD = Front Door, inferred from AAT/FTM abbreviation family'),
    ('10LHS FD Rr5',         'LHSFDOORRR',    'FD = Front Door'),
    ('11LHS Roof6',          'LHSROOF',       NULL),
    ('12LHS RD RR7',         'LHSRDOORRR',    'RD = Rear Door, inferred from AAT/FTM abbreviation family'),
    ('13LHS C-Pillar8',      'LHSCPILLAR',    NULL),
    ('14LHS Box Frnt9',      'LHSBOXFRNT',    NULL),
    ('15LHS Box Middle10',   'LHSBOXMID',     NULL),
    ('16LHS Box Rr11',       'LHSBOXRR',      NULL),
    ('17LHS TG Top12',       'LHSTGTOP',      NULL),
    ('18LHS TG Bot13',       'LHSTGBOT',      NULL),
    ('19Tailgate Middle14',  'TGMIDDLE',      NULL),
    ('20RHS TG Top15',       'RHSTGTOP',      NULL),
    ('21RHS TG Bot16',       'RHSTGBOT',      NULL),
    ('22RHS Box Rr17',       'RHSBOXRR',      NULL),
    ('23RHS Box Middle18',   'RHSBOXMID',     NULL),
    ('24RHS Box Frnt19',     'RHSBOXFRNT',    NULL),
    ('25RHS C-Pillar20',     'RHSCPILLAR',    NULL),
    ('26RHS RD RR21',        'RHSRDOORRR',    'RD = Rear Door'),
    ('27RHS Roof22',         'RHSROOF',       NULL),
    ('28RHS FD Rr23',        'RHSFDOORRR',    'FD = Front Door'),
    ('29RHS FD Frnt24',      'RHSFDOORFRNT',  'FD = Front Door'),
    ('30RHS Fender Rr25',    'RHSFENDERRR',   NULL),
    ('31RHS Fender Middl26', 'RHSFENDERMID',  'source typo: Middl -> Middle'),
    ('32RHS Fender Frnt27',  'RHSFENDERFRNT', NULL)
ON CONFLICT (raw_value) DO NOTHING;

INSERT INTO ref_model_zone (model_code, zone_code, zone_no)
SELECT 'J73 DBL', z.zone_code, z.zone_no
FROM (VALUES
    ('RHSHOODRR',1),      ('RHSHOODFRNT',2),   ('HOODMIDDLE',3),
    ('LHSHOODFRNT',4),    ('LHSHOODRR',5),     ('LHSFENDERFRNT',6),
    ('LHSFENDERMID',7),   ('LHSFENDERRR',8),   ('LHSFDOORFRNT',9),
    ('LHSFDOORRR',10),    ('LHSROOF',11),      ('LHSRDOORRR',12),
    ('LHSCPILLAR',13),    ('LHSBOXFRNT',14),   ('LHSBOXMID',15),
    ('LHSBOXRR',16),      ('LHSTGTOP',17),     ('LHSTGBOT',18),
    ('TGMIDDLE',19),      ('RHSTGTOP',20),     ('RHSTGBOT',21),
    ('RHSBOXRR',22),      ('RHSBOXMID',23),    ('RHSBOXFRNT',24),
    ('RHSCPILLAR',25),    ('RHSRDOORRR',26),   ('RHSROOF',27),
    ('RHSFDOORRR',28),    ('RHSFDOORFRNT',29), ('RHSFENDERRR',30),
    ('RHSFENDERMID',31),  ('RHSFENDERFRNT',32)
) AS z(zone_code, zone_no)
ON CONFLICT (model_code, zone_code) DO NOTHING;


-- -------------------------------------------------------------
-- 2. Colour vocabulary seen in the SAP July 2026 file.
--
-- Same mechanical rule already applied to every AAT/FTM colour:
-- strip the leading paint code, Title Case. Four of SAP's twelve
-- raw colours are the SAME paint AAT/FTM already use (just with
-- a different code prefix) - those four get an alias onto the
-- EXISTING canonical name. The other eight are colours never
-- seen at AAT/FTM and become new canonical entries.
-- -------------------------------------------------------------
INSERT INTO ref_color (color_name, color_group) VALUES
    ('Agate Black',         'BLACK'),
    ('Lucid Red',           'RED'),
    ('Iconic Silver',       'SILVER'),
    ('Chill Grey',          'GREY'),
    ('Frozen White',        'WHITE'),
    ('Carbonized Grey',     'GREY'),
    ('Cyclone Terra Green', 'GREEN'),
    ('Diffused Silver',     'SILVER')
ON CONFLICT (color_name) DO NOTHING;

INSERT INTO ref_color_alias (raw_value, color_name, note) VALUES
    ('DM AGATE BLACK',         'Agate Black',         'new at SAP - not seen at AAT/FTM'),
    ('DM BLUE LIGHTNING',      'Blue Lightning',       'same paint as AAT/FTM, different code prefix'),
    ('DM LUCID RED',           'Lucid Red',            'new at SAP - not seen at AAT/FTM'),
    ('LM ICONIC SILVER',       'Iconic Silver',        'new at SAP - not seen at AAT/FTM'),
    ('LS CHILL GREY',          'Chill Grey',           'new at SAP - not seen at AAT/FTM'),
    ('LS FROZEN WHITE',        'Frozen White',         'new at SAP - not seen at AAT/FTM'),
    ('MM ACACIA GREEN',        'Acacia Green',         'same paint as AAT/FTM, different code prefix'),
    ('MM CARBONIZED GREY',     'Carbonized Grey',      'new at SAP - not seen at AAT/FTM'),
    ('MM CYCLONE TERRA GREEN', 'Cyclone Terra Green',  'new at SAP - not seen at AAT/FTM'),
    ('MM DIFFUSED SILVER',     'Diffused Silver',      'new at SAP - not seen at AAT/FTM'),
    ('MM IGNITE ORANGE',       'Ignite Orange',        'same paint as AAT/FTM, different code prefix'),
    ('MS COMMAND GREY',        'Command Grey',         'same paint as AAT/FTM, different code prefix')
ON CONFLICT (raw_value) DO NOTHING;

