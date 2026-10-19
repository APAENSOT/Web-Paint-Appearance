# Documentation

| Document | What it covers |
|---|---|
| [00-ARCHITECTURE.md](00-ARCHITECTURE.md) | The system design: components, data flow, why GCP / FastAPI / PostgreSQL |
| [01-DATA-MODEL.md](01-DATA-MODEL.md) | Tables, reference data, immutability rules, what each migration family added |
| [02-PIPELINE.md](02-PIPELINE.md) | Upload → staging → review → facts: the ingest pipeline and its door checks |
| [03-SECURITY.md](03-SECURITY.md) | Database roles, authentication, RBAC matrix, secrets, data classification |
| [04-ANALYSIS.md](04-ANALYSIS.md) | Grading, standards and the analysis views |
| [DEFERRED.md](DEFERRED.md) | Open and closed decisions (D1–D6) |
| [ADR/](ADR/) | Architecture decision records 0001–0014 |
| [openapi.json](openapi.json) | The API contract. Generated from the code by `backend/scripts/emit_openapi.py`; CI fails if it drifts |

## Reading these documents

The architecture, data-model, pipeline and security documents were written as the
specification before and during implementation (September–October 2026). Where they
and the code disagree, **the code and the tests are the authority**.

They often name the task that introduced something (`T01`, `T47`, `RO19`, `AR04`, ...)
or an evidence report. Those task files, reports, screenshots and evidence bundles
lived in the private working repository and are **not** part of this repository; the
names are kept as historical references. Ask the owner if you need one.

## Main changes since the specification

- **No sign-in in this release** (owner decision 2026-10-20). `AUTH_OPEN_ACCESS=true`
  makes every request one shared account (`shared.access@paint-appearance`) with every
  role, so writes are still attributed. Ford ID / Entra sign-in will be added later by
  another team; the role checks are still in the code for it. Until then the
  deployed service must be reachable only from the company network.
- **One container on Cloud Run.** The API also serves the built frontend
  (`STATIC_DIR`), so the browser talks to one origin and there is no CORS in production.
  Migrations run from the same image as a Cloud Run job.
- **Four plants are active:** AAT, FTM, FVL and SAP, each with Wave Scan (CF) and Film
  Thickness data.
- **A fresh database starts from a data dump, not from migrations alone.** Migration
  `0025` seeds standards for colours that were added through the application, so
  `alembic upgrade head` on an empty database does not give a usable system. Every
  install restores the owner's `pg_dump` first and then runs `alembic upgrade head`.
- The latest migration is `0050`.
