# ADR 0007 — Lovable may produce an external visual reference; it still does not touch this repo

**Status:** Accepted (amended 2026-09-15 by [ADR 0009](0009-lovable-is-production-frontend.md))  
**Date:** 2026-09-13  
**Amends:** [ADR 0006](0006-codex-owns-frontend.md)  
**Amended by:** ADR 0009 — the owner locked the vault Lovable product as production `frontend/` chrome; functions remount one by one.  
**Does not supersede:** ADR 0006. Codex still owns production `frontend/` end-to-end.

## Context

Slice 2 shipped a working WaveScan SPA: plant measurements, upload/review, mapping/replay, correction, and Admin supersede. The owner wants a **product-wide visual picture** before deepening dashboard and other backend functions.

ADR 0006 forbids Lovable from editing this repository, because two agents touching the same frontend creates a second copy of the truth (the same class of defect as duplicated grading). That risk is unchanged.

What changed is the *need* ADR 0006 already anticipated: dedicated visual iteration beyond what the current operational screens show. The owner approved a narrow exception: Lovable explores the WaveScan v1 shell **outside** this repo; Codex translates approved screens into the existing SPA using OpenAPI types.

## Decision

**Lovable is an external visual-reference tool only.**

| Lovable may | Lovable must not |
|---|---|
| Produce a disposable prototype **outside** `Paint Application/` | Edit this git repo, `frontend/`, OpenAPI, or backend |
| Explore layout, navigation, tokens, empty/error/unavailable states | Define request/response shapes, roles, or SQL |
| Use clearly labelled **design fixtures** (synthetic labels, no Ford workbooks) | Connect to the live API, invent pass rates, or ship credentials |
| Hand off screenshots, a route map, tokens, and an action checklist | Export code that Codex copies into `frontend/` |

**Codex remains the only production frontend agent** (ADR 0006). After the owner approves a screen, Codex implements it in the TanStack SPA. A missing shape is a **backend task**, not a frontend workaround (`00-ARCHITECTURE.md` §4).

Screens do not “place database functions.” A UI action maps to a FastAPI use case. Placement is:

1. Router — HTTP and RBAC  
2. Service — transaction and audit  
3. Domain — pure rules (grading lives only in `domain/grading.py`)  
4. Repository — SQL  
5. PostgreSQL — schema, CHECKs, and the few privileged functions already justified (e.g. `reset_batch_staging`)

## Consequences

- Production ownership of `frontend/` does not split. Generated Lovable code is throwaway.
- A WaveScan v1 vision spec and Lovable brief live under `docs/superpowers/specs/`. They are not a second OpenAPI.
- Graded KPI panels in the prototype are **unavailable states** until D1 and D2 close. Invented pass rates remain a defect (`AGENTS.md` §4).
- Existing T06–T09-UI flows are not bulk-replaced. Each redesigned screen is a later, separately approved implementation plan.

## Alternatives rejected

- Reverse ADR 0006 and let Lovable edit production `frontend/`: rejected — two owners of the same components.
- Copy Lovable export into this repo: rejected — generated code will not match TanStack Query, generated types, immutable correction, or RBAC chrome.
- Skip the visual prototype and redesign only inside the current SPA: rejected by the owner for this phase; Codex still implements the approved result.
