# ADR 0014 — One colour, two historical names: read-time fold

**Status:** Accepted 2026-10-06. The T64 recheck passed and the owner verified it on the website. Evidence: T64-ABSOLUTE-SHADOW-BLACK.md.  
**Date:** 2026-10-06  
**Amends:** STANDARDS-D2-AUDIT.md §1.2 ("Shadow Black" and "Absolute Black" kept as two names).  
**Does not supersede:** [ADR 0005](0005-immutable-facts.md) (no UPDATE of fact rows), [ADR 0010](0010-plant-scoped-color-family.md) (family is plant × colour).

## Context

The owner workbook `standard color family.xlsx` (SHA-256 `b9f54fcd8c921eb10b834f59ddafcf4c07369857fc3b2dedff45e855640aacd8`, the same file D2 signed) has **one** row, *Absolute Black, DM*. Its plant spellings are:
- AAT: `G9Z Absolute Black`
- FTM: `DM G9 Shadow Black BC`
- FVL: `AB - Absolute Black`

D2 kept two catalogue names to avoid folding History. The cost showed up at AAT. July WaveScan (load 1064, 63 rows) is stored as **Shadow Black** (Dark Metallics). September (loads 6052 and 6063, 63 rows) is stored as **Absolute Black**, whose AAT family is NULL. So one paint shows as two colours and half of it cannot be graded.

The owner directs on 2026-10-06: it is one colour, named **"Absolute / Shadow Black"**, family **Dark Metallics**.

Fact rows (`wavescan.color`, `filmthickness.color`) cannot be rewritten (ADR 0005).

## Decision

1. **Mint `ref_color` "Absolute / Shadow Black"** (active). Add a nullable column `ref_color.merged_into`, FK to `ref_color(color_name)`, so a merged name points at its canonical name.
   - `Shadow Black` and `Absolute Black` get `merged_into = 'Absolute / Shadow Black'` and `is_active = false`.
   - Their rows stay because facts reference them.
2. **Fold on read.** Every read of a fact colour, and every catalogue or standards read, returns `COALESCE(merged_into, color)`.
   - Stored fact values are unchanged.
   - Active views (`v_wavescan_active`, `v_wavescan_p703`, `v_wavescan_u704`, `filmthickness_active`) carry the folded name.
3. **Fold on write.** Ingest resolution (alias hit, unique catalogue fold, Choose-colour mapping) maps a merged name to its canonical name before the INSERT. New facts store "Absolute / Shadow Black".
4. **Plant offer.**
   - The canonical name is offered at AAT, FTM and FVL with family **Dark Metallics**.
   - The two old names are un-offered (`is_offered = false`).
   - SAP is untouched; the workbook has no SAP cell for this row.
5. **Standards.**
   - `film_standard` and `cf_standard` rows on a merged name are **read** under the canonical name; latest wins after the fold. No standards row is updated or deleted.
   - Publishing on a merged (inactive) name is refused.
6. **One level only.** A canonical name cannot itself be merged (CHECK plus test). This is the general mechanism for a later owner-signed merge; adding a merge is an Alembic migration, not an API.

## Consequences

- History, Comparison, Overview and the Film bay show one colour for AAT July + September, FTM and FVL.
- AAT September becomes gradeable (family DM).
- `GET` responses change their colour **value**, not their shape. The frontend needs no type change, but any hard-coded colour string would break (none is expected).
- The `test_standards_catalogue` AAT "unmapped = 1" drift is fixed by this ADR (Absolute Black at AAT no longer offered with a NULL family).

## Alternatives rejected

- **UPDATE `wavescan.color` / `filmthickness.color`.** Violates ADR 0005.
- **Correction rows for about 1,970 facts.** A correction asserts that the gauge was wrong. Here only the name changed.
- **Display-only label in the SPA.** Leaves two groups in every query, grading and duplicate key.
- **Fold Shadow Black into "Absolute Black".** The owner named the colour "Absolute / Shadow Black".
