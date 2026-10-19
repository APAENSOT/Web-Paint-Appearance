# ADR 0008 — Frontend modules have the same kind of boundary as the backend

**Status:** Accepted  
**Date:** 2026-09-13  
**Amends:** [00-ARCHITECTURE.md](../00-ARCHITECTURE.md) §6  
**Does not supersede:** ADR 0006 (Codex owns `frontend/`), ADR 0007 (Lovable stays off-repo).

## Context

Slice 2 shipped working WaveScan operations (upload, mapping, correction, supersede) as files dropped into `frontend/src/components/` next to forty shadcn primitives. Role checks live in `api/batch-state.ts` (`mayIngest`) and are reused for correction; Admin is `roles.includes("admin")` in three components. That is fine for one intern week. It is not fine for a five-year Ford quality platform that will add Analysis, Administration, PELT, Color Data, and production OIDC.

Two failure modes we already forbid on the backend apply here:

1. **Second copy of the truth** — a screen that grades, invents a DTO, or duplicates RBAC will silently disagree with FastAPI.
2. **Big-bang rewrite** — replacing the tested SPA with a generated prototype (Lovable or otherwise) would regress ADR 0005 copy, 403 handling, and cache invalidation.

## Decision

The SPA keeps TanStack file routes and generated OpenAPI types. **New production UI is feature-sliced.** Existing T07–T09 files are not bulk-moved in the first workspace task; they migrate when that feature is next touched.

```
frontend/src/
  api/                 HTTP + OpenAPI types + query options + role helpers
                       No React. No CSS. No grading.
  features/
    shell/             App chrome, nav, identity, route denials
    overview/          Landing
    measurements/      Plant table, correction (T12)
    intake/            Batches, mapping, supersede (T13)
    analysis/          Raw CF views (T11)
    admin/             Platform status (read-only until a write contract exists)
  components/ui/       shadcn primitives only
  components/          ApiState only; no new domain widgets
  routes/              Thin file routes: params + compose a feature
  lib/                 cn() and other non-domain helpers
```

**Dependency rules (review-blockers if violated):**

1. `api/` imports no React and no feature. It is the only module that calls `fetch`.
2. Role chrome comes from `api/roles.ts` (or the successor of that file). Features do not re-parse `principal.roles`.
3. `routes/` do not contain fetch, form POST bodies, or RBAC lists. They render a feature.
4. Features may use `api/` and `components/ui/`. A feature does not import another feature’s internals except `shell` (denial layout, identity).
5. `components/ui/` stays design-system only. Domain widgets do not belong there.
6. Types come from `api/types.ts` generated from `docs/openapi.json`. Missing shape → backend task, not a local interface.
7. Every displayed measurement number is an API field. No `statusOf`, pass rate, Ford/Min, or client-side grade.
8. Mutations stay on the existing client methods. Do not add a second API wrapper.

Lovable exports are not a module in this tree (ADR 0007).

## Consequences

- T10-UI introduced `api/roles.ts`, `features/shell/`, `features/overview/`, and `features/admin/` without rewriting MeasurementTable or ReviewQueue.
- T12-UI migrated measurements. T13-UI (`42d8114`) migrated intake. `components/` holds `ApiState` only; do not add new domain widgets.
- Visual restyle after T13 is owner-approved Lovable screens implemented by Codex (2026-09-14 spec); not a Lovable export.
- PELT later is `features/pelt/`, not another file in `components/`.
- Codex documents UX in the task report. Structure is this ADR, not a screenshot.

## Alternatives rejected

- Keep dumping screens in `components/`: rejected — PELT and Admin will collide with shadcn.
- Bulk-move T07–T09 in the same drop as the new shell: rejected — high regression cost for no operator value.
- Copy a Lovable `src/` tree: rejected — ADR 0007.
- Feature-folder *and* a second state library (Redux, Zustand, server actions): rejected — TanStack Query + generated types is the data layer (`00-ARCHITECTURE.md` §6).
