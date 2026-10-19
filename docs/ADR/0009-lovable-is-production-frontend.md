# ADR 0009 — Production frontend is the Lovable product chrome

**Status:** Accepted  
**Date:** 2026-09-15  
**Amends:** [ADR 0007](0007-lovable-external-reference.md)  
**Does not supersede:** ADR 0006. Codex still owns production `frontend/`. Lovable still does not edit this repo.

## Context

ADR 0007 treated the vault Lovable app as a look-only reference and forbade copying it into `frontend/`. Recreating that look produced a different shell than the owner expected.

On 2026-09-15 the owner locked the **vault Lovable product** as the production WaveScan frontend. Functions stay parked until the owner names them one by one.

## Decision

**`Paint Application/frontend` is the Lovable product** (map, KPI tiles, plant bays, Monthly Detail, colour/3D). That tree is the main frontend from this date.

| Locked | Still true |
|---|---|
| Visible chrome matches vault `Paint Appearance/Component/Frontend` | Codex owns `frontend/` (ADR 0006) |
| Overview `/`, plant `/plant/$code`, colour `/plant/$code/model/$id` | FastAPI is the only backend; types from OpenAPI |
| Demo KPI / bay / 3D numbers are **prototype fixtures**, not API grades | A silent wrong grade is still a defect |
| Analysis `/analysis`, intake `/batches`, Admin `/admin` stay parked | Operational widgets stay on disk; remount when the owner names a function |
| No role switcher; no new invented D1–D6 | Missing reads stay backend tasks |

Do **not** restyle this chrome back into the T10/T14-visual-shell placeholders. The next frontend task is a **named function remount**, not another look pass.

## Consequences

- ADR 0007’s “do not copy vault files” rule is waived for this owner-approved product chrome only.
- `src/components/ct/` and `src/lib/ct/` are the locked visual product. Feature folders still hold parked operational screens.
- Wiring a function replaces a fixture or placeholder with an OpenAPI field. It does not invent pass rates or client `statusOf`.

## Alternatives rejected

- Keep recreating Lovable look without the vault screens: rejected by the owner — that is not the expected frontend.
- Point the vault Lovable app at FastAPI: rejected — production SPA stays the only app (`S2`).
- Remount all T10–T13 functions in this lock: rejected — owner wires functions one by one.
