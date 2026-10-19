# ADR 0012 — Ford/Min numbers are plant × family

**Status:** Accepted  
**Date:** 2026-09-28  
**Amends:** [ADR 0010](0010-plant-scoped-color-family.md) (membership was plant-scoped; **numbers were global**).  
**Does not supersede:** ADR 0005 (append-only `cf_standard`, never UPDATE a standards row). D1 stays open.

## Context

ADR 0010 stores which colour family a name uses **at a plant** (`ref_plant_color`). `POST /api/v1/standards` still inserted `cf_standard` `scope=FAMILY` with **no `plant_code`**. Monthly Overview then read the latest FAMILY Ford/Min with `effective_from <=` the selected month end, also **not plant-scoped**. Saving Standard/Min at FTM therefore either did nothing to a June chart (dated filter + cache) or would have moved every plant that shares the family name.

The owner wants: save → dashboard uses the new numbers **immediately on every month**, and **AAT / FTM / FVL / SAP must not share Ford/Min**.

## Decision

1. **`cf_standard` FAMILY rows carry `plant_code`.** `POST /api/v1/standards` requires `plant_code`. Insert two rows (H and V) for that plant × family. Never UPDATE/DELETE existing standards rows.
2. **Seed rows may keep `plant_code` NULL** as a fallback until that plant publishes. Overview and the Standard page: plant-specific latest row wins; else NULL-plant seed.
3. **Dashboard (all months)** uses the **latest** plant FAMILY row by `created_at` (not `effective_from <= month_end`). `effective_from` is still stored for audit. COLOR-scope, if a row exists, still beats FAMILY for that colour, and must be plant-scoped the same way if COLOR rows are ever inserted. This slice does not add a COLOR publisher.
4. **Model view is not Ford/Min.** It remains offered ticks on `ref_plant_model`.
5. After publish, clients **must invalidate Overview queries**, not only the catalogue.

## Consequences

- Catalogue family Ford/Min can no longer be a single global quadruple. The GET must expose per-plant numbers (or the plant page must read a plant-filtered shape).
- Changing FTM Medium Solids never re-grades SAP Medium Solids.
- Historical month charts **will jump** when a new version is published (owner-accepted).

## Alternatives rejected

- Keep global FAMILY numbers, only refresh cache: contradicts "plants use different standards."
- `effective_from` still filters the selected month: a save today never moves a June box — the bug the owner reported.
- Ford/Min per colour: not requested this slice; family heading stays the editor.
