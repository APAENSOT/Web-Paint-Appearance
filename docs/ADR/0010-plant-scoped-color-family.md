# ADR 0010 — Colour family is plant-scoped

**Status:** Accepted  
**Date:** 2026-09-22  
**Amends:** [ADR 0004](0004-wavescan-first.md) D2 wording; [DEFERRED.md](../DEFERRED.md) D2  
**Does not supersede:** ADR 0005 (facts stay immutable). D1 stays open.

## Context

D2 was specified as one `ref_color.grading_family` per common colour name. Seed stayed NULL so a guessed family could not silently wrong-grade.

The owner workbook `standard color family.xlsx` (SHA-256 `b9f54fcd8c921eb10b834f59ddafcf4c07369857fc3b2dedff45e855640aacd8`, not in git) lists **Ignite Orange** twice: Medium Solids (`MS`) at AAT/FTM/FVL and Medium Metallics (`MM`) at SAP. A single global family would grade the wrong Ford/Min at one of those plants.

## Decision

**CF grading family is `(plant_code, color_name)`**, stored on `ref_plant_color.family_name`.

- `ref_color.grading_family` remains nullable and is **not** read by ingest or `grading.py` in this slice.
- Hue `color_group` is still not a family.
- Disable means `is_offered=false` at that plant. History is unchanged. No DELETE of catalogue rows History used.
- `POST /api/v1/standards` may append `cf_standard` `scope=FAMILY`. It must not UPDATE or DELETE existing standards rows.
- Product pass-rate (`grading_available`, Overview ribbon, Analysis) stays blocked on **D1**.

## Consequences

- Ignite Orange is the proof row for the amendment.
- Admin Standards UI ticks plants per colour and publishes Ford/Min per family heading.
- Ingest holds a resolved colour or model that is not offered at the batch plant.
- Alembic seed waits on the signed audit table in STANDARDS-D2-AUDIT.md.

## Alternatives rejected

- One family per colour (original D2): contradicts the workbook.
- Use `color_group` as family: documented defect (`AGENTS.md` §4).
- Flip `grading_available` when families exist: D1 is still open.
