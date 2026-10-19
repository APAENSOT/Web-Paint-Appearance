# ADR 0013 — Uploader worksheet contract (optional booth/serial, honest holds)

**Status:** Accepted  
**Date:** 2026-09-28  
**Amends:** T17 whole-request plant refuse ([02-PIPELINE.md](../02-PIPELINE.md) §1); paintline sentinel P4 (2026-09-21-paintline-sentinel-null-design.md); identity I4 serial-required (2026-09-22-identity-ingest-ux-design.md); T21 F12 no vehicle-partial commit (2026-09-17-friendly-plant-data-review-design.md); T26 S9 Admin-only extra-header ignore.  
**Does not supersede:** ADR 0005 (no UPDATE of measurement values; no inventing booth/serial/colour/model/zone). ADR 0011 purge still the way to remove a hash. D1 stays open.

## Context

WaveScan dashboard grain is **model × colour × orientation**. Paintline and Serial No are not used there. Instrument exports (including `Wave scan P703_Sep26_W3.xlsx` and `Wave scan U704_Sep26_W3.xlsx`) often omit DOI, write Plant as `AAT U704`, and leave booth/serial blank or unused.

Today those files fail as a **layout or identity error** instead of loading complete rows and asking the Engineer about the rest. Empty / `None` / no-model rows must still be cross-checked — never taught onto Ranger.

## Decision

1. **Required to load a point:** measured date, model, colour, checkzone (panel), and CF. LW and SW are required **unless** the Engineer explicitly approves that point with holes. DOI, Paintline, and Serial No are **optional**. A missing column for an optional field is the same as blank.
2. **Blank / missing / `(None)` Paintline or Serial** → LOAD with NULL at **every** plant. Do not invent a booth or serial. A **non-blank unknown** spelling still holds for the Engineer.
3. **Plant cell** that **starts with** the upload page plant (e.g. `AAT U704` on AAT) **is that plant**. Extra words are not a second plant. If Excel names a **different** plant, **ask** — do not auto-refuse the whole request, do not silently relabel. Batches stay on the page they uploaded to; if they confirm a different plant, cancel and tell them to use that plant’s page.
4. **Leftover programs** (U704, J73, CX743, V363) load onto **their own** catalogue when offered at that plant. Never auto-fold leftover → Ranger.
5. **Good rows load; junk holds.** Blank panel / model / colour / date / CF: hold that row, load the rest of the sheet. Empty / `None` / no-model are **never** aliased. Fix Excel → new file or purge + re-upload.
6. **Extra unknown column:** Engineer confirms once in plain words (“we do not use this — ignore and keep the rest”), then load. Two columns that mean the same logical field still block until they ignore one. Cover/instruction tabs stay `OUT_OF_SCOPE_SHEET`.
7. **Horizontal / Vertical** always from the **mapped panel**, never from Excel Tolerance Group (treat that column as extra → ignore after confirm).
8. **One colour tab = one vehicle** when Serial is empty. One workbook = one confirm page; “Yes, load these rows” loads every **ready** tab; held tabs stay on the same card.
8a. **Serial-less duplicate.** When Serial is NULL, a later file that repeats the same **plant + measured date + model + colour + panel** is a duplicate, not a second dashboard point. Do not key that comparison on `(plant, NULL, zone)` alone. Two different cars the same colour on the same day without serials would collide — accepted so the dashboard does not silently double-count.
9. **Later teach, same file:** after good rows are COMMITTED, matching a colour/model later **INSERTs** only the newly eligible `source_row`s. No UPDATE of CF already stored. No remainder sibling file.
10. **Engineer** on the plant page owns the checklist. **Admin** only: new catalogue colour name, new model code, new Ford/Min parameters, **new ZONE pack** (T29 complete named-owner set). Engineer may match a spelling onto an **existing** catalogue name, including offering an existing colour at this plant when they confirm it, and mapping one Excel panel spelling onto an **existing** `zone_code` for that plant × model (`ALIAS_CHECKZONE`, T41). Colour choice is **asked every time** with official catalogue names — no default Absolute Black vs Shadow Black.

## Consequences

- `REQUIRED_FIELDS` / `MEASURES_REQUIRED` / cleaner P4 must stop treating serial, paintline, and DOI as hard errors.
- T17 must not 400 the whole multipart before a card exists when the plant cell is `AAT U704`.
- T21 `identity_complete` must not require serial when the vehicle is the sheet.
- Commit of LOAD rows while REJECT/QUARANTINE remain, then a second insert pass, is allowed. Still no `UPDATE wavescan` values. `app_rw` still has no table DELETE.
- **T42:** an exact `ref_template_profile` is still preferred. If none matches because optional columns differ (no DOI, no serial column, and so on), parse anyway on decision 1. Those tabs may commit without `fixture_verified` — there is no profile to prove. Extra unknown columns still need Ignore. Never guess identity from the tab name or filename.

## Alternatives rejected

- Keep serial/paintline required: dashboard does not use them; these workbooks cannot load.
- Guess G9Z Absolute Black → Shadow Black: silent wrong colour.
- Auto-ignore extra columns: silent drop of a column that might be CF under another name.
- Remainder new-hash to finish held rows: owner wants one workbook.
