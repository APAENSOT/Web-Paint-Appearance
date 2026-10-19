# ADR 0003 — Ingestion is web upload, not SharePoint pull

**Status:** Accepted  
**Date:** 2026-09-07  
**Supersedes:** SharePoint `FileSource` adapter in `Paint Appearance/docs/00-ARCHITECTURE.md` and `02-PHASE-PLAN.md` Phase 5

## Context

IT forbids the application from pulling files from SharePoint. The 2026-08-19 design assumed a Graph delta adapter as the production data source, with a local-folder adapter as its development twin.

Data still originates as Excel workbooks that plants produce and drop in SharePoint. The application is simply not allowed to fetch them.

## Decision

**Write path:** an authenticated Engineer uploads one or more `.xlsx` files through the web portal. The API stores bytes in object storage (local disk / Cloud Storage), hashes them, parses, validates, and holds a persisted review proposal. Commit promotes rows into the fact table.

**Read path:** the website reads PostgreSQL only. Dashboards never parse Excel at request time.

SharePoint remains in the human workflow (download, then upload). A later IT-controlled **push** (Power Automate or similar posting to our API) is parked, not built.

## Consequences

- No Microsoft Graph client, no `Sites.Selected`, no delta tokens.
- The `FileSource` adapter interface from the 2026-08-19 design is dropped. A single upload path is simpler and matches the IT constraint.
- The existing CLI (`wavescan_loader.cli`) is kept as an ops tool for bulk backfill; it calls the same services as the HTTP upload path.
- Template drift (new headers, new column order) is a first-class pipeline concern — see `02-PIPELINE.md`.

## Alternatives rejected

- Local-folder watch that "looks like SharePoint later": still a pull model, and IT already said no.
- Two-database sync (a working copy that syncs to production): split-brain, no single source of truth. Rejected in favour of one DB plus a draft/review/approve workflow.
