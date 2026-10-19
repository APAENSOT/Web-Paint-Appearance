# ADR 0005 — Measurement facts are immutable

**Status:** Accepted  
**Date:** 2026-09-07  
**Supersedes:** in-place edit and delete in `Paint Appearance/Component/Database`

## Context

The demo WaveScan platform lets a user:

- Edit a measurement in place (`ui/edit_dialog.py` → `Loader.update_row()` → `UPDATE wavescan SET ...`).
- Delete an entire upload (`DELETE FROM wavescan WHERE load_id = %s` then `DELETE FROM load_batch WHERE load_id = %s`).

`load_batch` deletion cascades to `stg_raw`, `reject_log`, and `unidentified_model`. There is no `audit_event` table. `loaded_by` is `current_user` (the pool role `wavescan_loader`), not a person.

`README.md` claims the loader role "cannot drop tables, delete rows, or alter reference data. Verified." `sql/10_role.sql` grants `DELETE` and `UPDATE` on `wavescan` and `load_batch`. The documentation is wrong; the code is the grant.

For a quality system, a micron or CF value is an instrument fact. Overwriting it destroys evidence. Deleting a batch plus its staging copy destroys the ability to prove what the file said.

## Decision

**No `UPDATE` or `DELETE` on fact tables from the application role.**

| User intent | Mechanism |
|---|---|
| "Delete this upload" | `load_batch.status = 'SUPERSEDED'`; rows remain, reporting views filter them out |
| "Fix this reading" | Insert a **correction row** with `corrects_measurement_id`, mandatory reason, authenticated author, timestamp; original marked superseded |
| "This file replaces that file" | New batch with new `file_hash`; old batch superseded. Filename is a label, not identity |

`audit_event` is append-only. `INSERT` granted to the app; `UPDATE`/`DELETE` granted to nobody.

## Consequences

- The Browse "edit row" dialog and "delete this upload" actions are removed from the product. Replaced by correction and supersede workflows that require a reason.
- `10_role.sql` must be rewritten (T01) before any web API talks to this database.
- `stg_raw` retention (6 months) is no longer the only copy of original values — the fact table keeps full-precision `NUMERIC` forever (see `01-DATA-MODEL.md`).
- Superuser credentials leave the application `.env`. Destructive schema work is a migrator role, CI-only.

## Alternatives rejected

- Keep edit/delete behind a confirm dialog: a dialog is not an audit trail.
- Immutable for Engineers, true delete for Admin: still an erase path. Admin supersedes; they do not DELETE.
- Soft-delete flag only, no correction rows: cannot represent "the gauge said X, we record Y because Z".
