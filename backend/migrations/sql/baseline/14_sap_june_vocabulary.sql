-- =============================================================
-- 14_sap_june_vocabulary.sql
-- Get SAP's June 2026 file one step from loadable, ahead of the
-- serial-number problem being fixed at the source.
--
-- Diagnosis (verified against the real file before writing this):
-- SAP's June export uses a DIFFERENT header layout and DIFFERENT
-- spellings than July's, and has FOUR separate problems, not one:
--
--   1. Serial No column is present in the header but 0 of 1218 data
--      rows have a value - NOT FIXABLE HERE. This is the actual
--      blocker; every row will keep failing MISSING_REQUIRED_FIELD
--      until SAP re-exports the file with serials populated. No
--      alias, no code change, and no "requires_serial=false"
--      exemption is appropriate - SAP's July file proves SAP DOES
--      have real per-vehicle serials (e.g. 'TM14468'), so this looks
--      like an export mistake specific to the June file, not a
--      structural gap the way FVL's is.
--   2. Paintline is written 'C1'/'C2', not 'BOOTH 1'/'BOOTH 2' as in
--      July. Fixed below (alias only, mechanical).
--   3. Model is written bare 'J73' (no 'DBL'), not 'J73 DBL' as in
--      July. 'P703' already has an alias from Phase 2. Fixed below.
--   4. Tolerance is written 'H'/'V', same short form July uses -
--      already handled, tolerance_group is derived in code from the
--      zone name and the file's own value is ignored either way
--      (see cleaner.derive_tolerance). No action needed.
--
-- Once serials are fixed at the source, items 2-3 being pre-resolved
-- mean the file should load on the next attempt with no further
-- migration - only the missing data was ever the true blocker.
--
-- C1/C2 -> BOOTH1/BOOTH2: this is an INFERENCE, not a confirmed
-- fact. Evidence for it: the July file (same plant, one month
-- apart) uses 'BOOTH 1'/'BOOTH 2' for what is presumably the same
-- concept; C1/C2 colour distributions overlap almost completely
-- (12 vs 9 of the same colours), which is what you would expect
-- from two paint booths and NOT what you would expect if C1/C2
-- were a colour code. If this turns out to mean something else,
-- delete these two alias rows - nothing else depends on them.
--
-- Run against: paint_appearance
-- Re-runnable: ON CONFLICT DO NOTHING.
-- =============================================================


INSERT INTO ref_paintline_alias (raw_value, paintline_code) VALUES
    ('C1', 'BOOTH1'),
    ('C2', 'BOOTH2')
ON CONFLICT (raw_value) DO NOTHING;

INSERT INTO ref_model_alias (raw_value, model_code, note) VALUES
    ('J73', 'J73 DBL', 'SAP June file writes the bare code with no "DBL" suffix')
ON CONFLICT (raw_value) DO NOTHING;

