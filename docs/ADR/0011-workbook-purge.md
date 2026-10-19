# ADR 0011 — Workbook purge (X deletes that file's rows)

**Status:** Accepted  
**Date:** 2026-09-28  
**Amends:** [ADR 0005](0005-immutable-facts.md) for **workbook identity only**.  
**Does not supersede:** no `UPDATE` of measurement values; no table-level `DELETE` grant on `app_rw`; correction + supersede remain the path for *keeping* a file's evidence.

## Context

ADR 0005 forbids application `DELETE` on `wavescan` / `load_batch`. Upload Data **X** therefore retires (`ABANDON` / `SUPERSEDE`): the card can disappear from active reads while rows and hashes remain. Remainder packs then loaded held rows as a **second hash**, so one plant month showed two cards and looked like lost or duplicate data.

The owner, iterating plant templates on the standing trial, requires: **one workbook per upload**, and **X permanently removes that workbook from the database** so the same file can be mapped and loaded again. After purge, a new upload must go through mapping if the layout is still unknown. Published plant template profiles stay.

## Decision

1. **X on a workbook** calls a dedicated purge mutation for that plant + `file_hash`. It deletes that file's `load_batch` rows and dependent staging / reject / unidentified / review / ingest-job / `wavescan` rows. It does not delete other files, catalogue, aliases, or published `ref_template_profile` rows.
2. **`app_rw` still has no table `DELETE`.** Purge is a `SECURITY DEFINER` function with fixed `search_path`, plant + hash arguments, an audit row in the **same transaction before** fact deletes, and `PUBLIC` revoked. Destructive Alembic needs an owner approval line at commit.
3. **Measurement values are still never UPDATEd.** Fix a kept file with a correction row (ADR 0005). Purge is only "this file should not exist."
4. **Identical re-upload after purge is allowed** (the hash is gone). T25 reopen-vs-409 applies to hashes that still exist.
5. **Remainder packs are not a product path.** Do not invent a second hash to load held rows. Map aliases / checkzones on the original, replay, or purge and re-upload one file.
6. **X on Upload Data stays Admin.** ADR 0013 lets an **Engineer** cancel a **wrong-plant** upload through the **same** `purge_workbook` function, only from `POST .../plant-answer` when **no** `wavescan` row exists for that hash. If any point has loaded, that cancel is 409 and X remains Admin. This is not a second DELETE grant.

## Consequences

- Identity-ingest UX **R1x** ("X does not DELETE") is withdrawn for this product.
- T01 evidence that unqualified `DELETE FROM wavescan` as `app_rw` fails **must stay true**.
- History / Overview lose that file's active facts after purge (honest empty, not a hidden supersede).
- D1 stays open. Analysis and FilmThickness stay later.

## Alternatives rejected

- Soft-delete / hide only: owner already has this; it produced remainder siblings.
- `GRANT DELETE` on `wavescan` to Admin: T01 defect ("DELETE just for admin").
- Cell editor that UPDATEs CF: silent wrong grade; ADR 0005 still forbids it.
