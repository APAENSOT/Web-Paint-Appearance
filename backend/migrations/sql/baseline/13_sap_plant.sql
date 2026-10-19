-- =============================================================
-- 13_sap_plant.sql
-- Phase 4: onboard SAP as a plant.
--
-- Everything SAP needs to be a plant the loader recognises was
-- already prepared in earlier phases:
--   - J73 DBL and its 32 zones/aliases      (sql/12_sap_vocabulary.sql)
--   - SAP's colour vocabulary                (sql/12_sap_vocabulary.sql)
--   - the per-plant zone mapping mechanism   (sql/11_plant_zone_map.sql)
--
-- This file only adds the plant itself. SAP's P703 zone mapping is
-- NOT part of this file - it is proposed and approved through the
-- Mapping tab (or loader.propose_zone_mappings/decide_zone_mapping)
-- against the real SAP file, so the decision is visible and
-- reversible, not buried in a migration.
--
-- requires_serial = true: SAP's file has a populated, if
-- alphanumeric, Serial No. column (e.g. 'TM14468') - it genuinely
-- identifies a vehicle, same as AAT/FTM. This is NOT the FVL
-- situation.
--
-- plant_name / country: NOT CONFIRMED. Unlike AAT ('AutoAlliance
-- Thailand') and FTM ('Ford Thailand Manufacturing'), no source in
-- this project states what "SAP" stands for or where it is - the
-- source file's own metadata has no company/title field, and no
-- README or spec names it either. Rather than invent a plausible-
-- sounding company name, plant_name is set to the code itself and
-- country is left NULL. Update this row once the real name is
-- confirmed:
--     UPDATE ref_plant SET plant_name = '<real name>', country = '<real country>'
--     WHERE plant_code = 'SAP';
--
-- Run against: paint_appearance
-- Re-runnable: ON CONFLICT DO NOTHING.
-- =============================================================


INSERT INTO ref_plant (plant_code, plant_name, country, requires_serial)
VALUES ('SAP', 'SAP', NULL, true)
ON CONFLICT (plant_code) DO NOTHING;

INSERT INTO ref_plant_alias (raw_value, plant_code)
VALUES ('SAP', 'SAP')
ON CONFLICT (raw_value) DO NOTHING;

