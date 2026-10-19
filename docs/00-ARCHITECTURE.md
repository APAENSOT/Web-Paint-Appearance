# Paint Appearance Platform — Architecture

**Status:** Approved design, written before implementation (2026-09-07). The code is the authority where they differ; `README.md` in this folder notes the main later changes.  
**Date:** 2026-09-07  
**Owner:** Architect  
**Read order:** this file → `01-DATA-MODEL.md` → `02-PIPELINE.md` → `03-SECURITY.md` → `04-ANALYSIS.md` (see `README.md` in this folder)

This document supersedes `../Paint Appearance/docs/00-ARCHITECTURE.md` (2026-08-19, Azure + NestJS + SharePoint + PELT-first). See `ADR/0001`–`0005`.

---

## 1. What this platform is

One web platform for paint-quality analysis across four plants (FTM, FVL, AAT, SAP). Tools arrive in this order:

| Tool | Measures | Status |
|---|---|---|
| **WaveScan (CF)** | Paint appearance (CF and sub-parameters per checkzone) | **v1 — this build** |
| **PELT** | Paint thickness (microns per layer per point) | later, same platform |
| **Color Data** | Unspecified | slot reserved |

v1 reuses the working WaveScan loader at `Paint Appearance/Component/Database/` (Python, PostgreSQL, 36 tests, real June/July 2026 data). It replaces that loader's Tkinter UI with the existing React design at `Paint Appearance/Component/Frontend/`, and hardens security, audit, and template drift.

**Scale:** ~30 concurrent users, monthly Excel drops, four plants. Modular monolith: one API, one worker, one database. No Kubernetes, no microservices, no message broker.

---

## 2. Locked decisions

Coding agents do not reopen these. Changes require the architect.

Locked decisions use ids **L1–L13**. Gated items in `DEFERRED.md` use **D1–D6**. Do not mix them.

| # | Decision | ADR / doc |
|---|---|---|
| L1 | GCP exclusively | ADR 0001 |
| L2 | Python 3.12 + FastAPI | ADR 0002 |
| L3 | Web upload; no SharePoint pull | ADR 0003 |
| L4 | WaveScan is v1 | ADR 0004 |
| L5 | Facts are immutable (supersede + correction, no DELETE/UPDATE) | ADR 0005 |
| L6 | Single PostgreSQL; draft/review/approve inside it, not a second DB | this file §3 |
| L7 | Frontend = existing TanStack app in **SPA mode**; FastAPI is the only backend | this file §6 |
| L8 | Contract-first, then one vertical slice, then widen | `05-PHASE-PLAN.md` |
| L9 | Grades computed on read, never stored | `04-ANALYSIS.md` |
| L10 | Domain packages import no framework | this file §5 |
| L11 | Ford ID OIDC pipeline built now, enforced later (`AUTH_DEV_BYPASS` only when `ENV=development`) | `03-SECURITY.md` |
| L12 | Measurements stored `NUMERIC` at full precision; round in views/UI only | `01-DATA-MODEL.md` |
| L13 | `Paint Application` = git repo (code + docs). `Paint Appearance` = local reference vault | this file §8 |

---

## 3. System topology

```
┌─────────────────────────────────────────────────────────────────┐
│  IDENTICAL IN LOCAL AND GCP                                     │
│                                                                 │
│  ┌──────────────┐  HTTPS/JSON   ┌────────────────────────────┐  │
│  │  frontend    │ ────────────► │  api (FastAPI)             │  │
│  │  React SPA   │  OpenAPI      │  uploads · batches ·       │  │
│  │  (static)    │               │  review · measurements ·   │  │
│  └──────────────┘               │  dashboard · mappings ·    │  │
│                                 │  standards · health        │  │
│                                 └──────┬──────────┬──────────┘  │
│                                        │          │             │
│  ┌─────────────────┐                   ▼          ▼             │
│  │ worker          │            ┌──────────┐ ┌───────────────┐  │
│  │ ingest jobs     │ ─────────► │ Postgres │ │ Object store  │  │
│  │ SKIP LOCKED     │            │          │ │ SHA-256 key   │  │
│  └────────┬────────┘            └──────────┘ └───────────────┘  │
│           │ calls                                               │
│  ┌────────▼──────────────────────────────────────────┐          │
│  │ domain/  reader · cleaner · dedup · mapping ·     │          │
│  │          grading   (pure Python, zero framework)  │          │
│  └───────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
         ▲
         │ Engineer uploads .xlsx (manual from SharePoint)
```

PostgreSQL is the only read path for dashboards. Excel is parsed once, at ingest.

### 3.1 Local (Docker Compose)

- `web` — Vite dev server (dev) or nginx serving the built SPA
- `api` — FastAPI, port 8000, OpenAPI at `/docs`
- `worker` — same image family, no public port
- `postgres` — pin major version to Cloud SQL (deferred D6)
- Raw files: `./data/raw`, gitignored
- Secrets: `.env`, gitignored, `.env.example` committed with no real values

### 3.2 GCP

| Concern | Service |
|---|---|
| API / worker | Cloud Run, images from Artifact Registry |
| Database | Cloud SQL for PostgreSQL, private IP, **IAM database authentication** |
| Raw files | Cloud Storage, object versioning on, keyed by content hash |
| Secrets | Secret Manager. No DB password under IAM auth |
| Frontend | Static SPA on Cloud Storage + CDN |
| Identity | Ford ID / Entra OIDC (app registration is identity-only) |
| CI/CD | GitHub Actions via Workload Identity Federation — no long-lived cloud keys |
| Telemetry | OpenTelemetry → Cloud Logging / Monitoring |
| IaC | Terraform in `infra/gcp/` |

Same container image locally and in cloud. Only config differs.

---

## 4. Contract-first workflow

1. FastAPI routers declare request/response models (Pydantic v2).
2. OpenAPI is emitted to `docs/openapi.json` (generated artifact, committed once the first endpoints exist).
3. Frontend types are generated (`openapi-typescript`) into a shared types package or `frontend/src/api/types.ts`.
4. The frontend agent (Codex, ADR 0006 / 0007) consumes **only** those types. A missing shape is a backend task, not a frontend workaround. A Lovable mockup is not a contract.

Slice 1 is: this contract + ingest + one dashboard view against real loaded data. Then widen.

---

## 5. Backend module boundaries

```
backend/
  app/
    main.py                 FastAPI factory
    api/v1/                 thin routers: HTTP, auth deps, no SQL
    core/                   config, security, logging, dependencies
    domain/                 PURE — no FastAPI, no psycopg, no os.getenv
    repositories/           SQL only, one per aggregate
    services/               use cases: ingest, review, correct, supersede
    schemas/                Pydantic DTOs
    workers/                job runner (SKIP LOCKED)
  migrations/               Alembic
  tests/                    pytest; 36 ported loader tests + new
```

**Dependency rules (review-blockers if violated):**

1. `domain/` imports nothing from `fastapi`, `psycopg`, `sqlalchemy`. Alias maps are **injected** as arguments (cleaner currently talks to the DB — that coupling is removed in T04).
2. Routers do not contain SQL.
3. Repositories do not contain HTTP or grading rules.
4. `apps` (api/worker) may import `domain` and `repositories`. Frontend never imports Python.
5. Grading lives in `domain/grading.py` only. SQL never contains a Ford/Min threshold.

**Migration map from the demo loader** (source: `Paint Appearance/Component/Database/`):

| Current | Destination | Change |
|---|---|---|
| `reader.py` | `domain/reader.py` | header aliases from DB; capture `extra`/`raw_headers`; emit fingerprint |
| `cleaner.py` | `domain/cleaner.py` | alias maps injected, not queried |
| `dedup.py` | `domain/dedup.py` | unchanged logic |
| `mapping_engine.py` | `domain/mapping_engine.py` | extend to column mappings |
| `loader.py` | `services/ingest.py` + repositories | delete/update paths removed (ADR 0005) |
| `ui/service.py` | `api/v1/*` + services | HTTP surface |
| `ui/*.py` (tkinter) | discard | React replaces |
| `cli.py` | keep | ops backfill; same services |
| `sql/*.sql` | `migrations/` | Alembic + schema revisions in `01-DATA-MODEL.md` |
| `sql/99_verify.sql` | keep, run in CI | negative DB tests |

---

## 6. Frontend

Adopt `Paint Appearance/Component/Frontend/` (TanStack Start + React 19 + shadcn + TanStack Query + react-three-fiber).

**SPA mode.** FastAPI is the only backend. The TanStack server (`src/server.ts`, `src/start.ts`) is not deployed. File-based routes (`plant.$code`, `plant.$code.model.$modelId`) stay.

**Hard rules:**

- Types from the OpenAPI artifact only.
- Fetch + TanStack Query. No extra data libraries.
- Every displayed number is a number the API returned. No client-side grading.
- Auth: session display + roles the API reports. No auth logic invented in the UI.
- 3D (`@react-three/fiber`, `src/assets/models`) stays installed; it ships **after** the data slice works, not in slice 1.
- Visual exploration of the WaveScan shell may happen in an **external** Lovable prototype (ADR 0007). Production screens are still this SPA. Do not import generated Lovable code.
- **Module boundaries (ADR 0008):** `api/` is the only HTTP client and the only RBAC helper; `features/<area>/` owns screens; `routes/` are thin; `components/ui/` is shadcn only. Same class of rule as §5 for Python.

---

## 7. Security (summary)

Full treatment: `03-SECURITY.md`. Non-negotiables:

- T01 remediates the demo DB **before** any new API talks to it: revoke DELETE/UPDATE on facts, add `audit_event`, UNIQUE `file_hash`, remove superuser from app env.
- Three DB roles: `app_rw`, `app_ro`, `migrator`.
- Upload treated as hostile: size cap, magic-byte sniff, zip-bomb ratio, extension not trusted.
- Deny-by-default RBAC on every mutating route from day one.

---

## 8. Workspace split

Historical note: the application was built in a private working repository that also held task files, evidence reports and screenshots. That material is not part of this repository. A separate reference vault (`Paint Appearance/`: the Excel prototype, converter and demo loader) stays with the owner. Where a document here names a task (`T01`, `RO19`, ...) or a report, it refers to that working material; ask the owner if you need it.

---

## 9. Observability

Structured JSON logs with `correlation_id` per request and per ingest file. OpenTelemetry traces. Health: `/health/live`, `/health/ready` (DB + object store). Quarantine counts are a dashboard surface, not a log file.

---

## 10. Non-goals for v1

- SharePoint Graph pull
- Websockets / live push (refresh on load/demand)
- 3D car-body visualisation as a shipping feature
- PELT implementation
- Color Data implementation
- Fine-tuned or self-hosted AI (`pgvector` slot later, same database)
- Kubernetes, Redis, microservices
- In-place edit or delete of measurements

---

## 11. Open items

Tracked in `DEFERRED.md` (D1–D6). They do not block writing specs. D1 and D2 block **graded** dashboard KPIs, not ingestion or ungraded measurement views.
