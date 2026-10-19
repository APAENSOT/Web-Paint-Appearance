# Paint Appearance — deployment package (Google Cloud)

This repository is the release of **Paint Appearance** handed to the team that deploys
it on Google Cloud. It contains the full source, the container definition, the Cloud Run
definitions and the runbook.

- **Deploy it:** follow [infra/gcp/README.md](infra/gcp/README.md) step by step.
- **Understand it:** read this page, then [docs/README.md](docs/README.md).

---

## 1. What the application does

Paint Appearance is an internal Ford web application for paint-quality measurements at
four plants: **AAT** and **FTM** (Thailand), **FVL** (Vietnam) and **SAP** (South Africa).

Plant staff upload the Excel/ODS workbooks produced by two instruments:

- **Wave Scan** — paint appearance (CF, long/short wave, DOI, …) per checkpoint on the body;
- **Film Thickness** — coating layer thickness (E-coat, primer, base, clear) per point.

The application checks each upload (format, plant, model, colour, duplicates), shows the
person anything it cannot place for review, stores every accepted reading as an immutable
fact, grades readings against each colour's standard, and presents monthly overviews,
per-car detail, history, point checks on a 3D body model, comparisons and reports.

**This release has no sign-in.** Every visitor is one shared account with every role
(`AUTH_OPEN_ACCESS=true`), so the service must only be reachable from the company
network. Sign-in (Ford ID / Entra) will be added later by another team.

## 2. Architecture

```
 browser (company network)
    │  one origin: pages and API
    ▼
 Cloud Run service "paint-appearance"   ── one container (Dockerfile) ──
    │  FastAPI (Python 3.13, uvicorn)
    │   • /api/v1/...   JSON API
    │   • /health/live, /health/ready
    │   • /*            the built React frontend (STATIC_DIR)
    │   • ingest worker thread: processes uploads in the background
    │
    ├── Cloud SQL for PostgreSQL  ← connects as app_rw (no DELETE, no DDL)
    └── Cloud Storage bucket      ← uploaded workbook bytes, mounted at /data/raw

 Cloud Run job "paint-appearance-migrate"  ── same image ──
    └── alembic upgrade head, as migrator (owner of the schema)
```

Key properties:

- **One container, one origin.** The image builds the frontend and the API serves it, so
  there is no separate web server and no CORS in production.
- **Least privilege in the database.** `migrator` owns the schema and is used only by the
  migrate job. The API connects as `app_rw`, which cannot delete or change the schema; the
  API refuses to start with a privileged role, and the readiness check fails if `app_rw`
  has gained a forbidden privilege.
- **Facts are immutable.** Corrections create new rows and audit events; nothing is
  edited or deleted in place (ADR 0005).
- **Configuration only from the environment**; the database URL comes from Secret Manager.
- **Logs** are JSON lines with a `severity` and a per-request `correlation_id`.

## 3. Project structure

```
Dockerfile              builds the frontend (Node 24) and the runtime image (Python 3.13)
.dockerignore
infra/
  gcp/
    README.md           ← the deployment runbook
    service.yaml        Cloud Run service (internal ingress, Cloud SQL, bucket volume, probes)
    migrate-job.yaml    Cloud Run job running Alembic as migrator
  docker-compose.yml    a local PostgreSQL for checking a build (not used in production)
db/
  create_roles.sql      creates migrator, app_rw and the empty database
backend/
  app/                  FastAPI application
    api/                routes: health, /api/v1/...
    core/               settings, database, identity, security headers, logging, SPA serving
    domain/             workbook reading, cleaning, grading, identity and analysis logic
    repositories/       SQL
    services/           use cases
    schemas/            request/response models (the OpenAPI contract)
    workers/            the ingest worker
  migrations/           Alembic revisions 0000–0050
  scripts/              emit_openapi.py (CI) and data-maintenance scripts used by the tests
  tests/                pytest suite (fixtures/gold: frozen reference files)
  requirements.txt      pinned runtime dependencies (requirements-dev.txt adds test tools)
  pyproject.toml
frontend/
  src/                  React app: routes/, features/, api/ (typed client), components/
  public/               static files, including the 3D body models
  tests/                unit tests (node --test); browser/ = Playwright specs
docs/                   architecture, data model, pipeline, security, analysis, ADRs, openapi.json
.github/workflows/ci.yml  CI: frontend checks, database-free backend tests, image build
```

## 4. Configuration

The container reads environment variables only. Production values are set in
`infra/gcp/service.yaml` and the `Dockerfile`; see the runbook's settings table.

| Variable | Production | Meaning |
|---|---|---|
| `ENV` | `production` | `development`/`test`/`staging`/`production`. Production enables HSTS and refuses `AUTH_DEV_BYPASS`. |
| `APP_DATABASE_URL` | secret | SQLAlchemy URL as **`app_rw`**: `postgresql+psycopg://app_rw:PW@/paint_appearance?host=/cloudsql/PROJECT:REGION:INSTANCE`. |
| `MIGRATOR_DATABASE_URL` | secret (job only) | Same form, as `migrator`. Read only by Alembic, never by the API. |
| `AUTH_OPEN_ACCESS` | `true` | No sign-in: every request is the shared account with every role. |
| `AUTH_DEV_BYPASS`, `AUTH_DEV_BYPASS_ROLES` | unset | Development only; refused in production. |
| `OIDC_TENANT_ID`, `OIDC_CLIENT_ID`, `OIDC_AUDIENCE` | unset | Reserved for the future sign-in. |
| `STATIC_DIR` | `/app/static` | Built frontend to serve. Empty: API only. |
| `RAW_STORE_DIR` | `/data/raw` | Where uploaded bytes are written (the bucket mount). |
| `API_DOCS_ENABLED` | `false` | Swagger UI at `/docs`. |
| `PORT` | `8080` | Listen port. |
| `CORS_ORIGINS` | not needed | Only for a frontend on another origin. |
| `DB_POOL_SIZE`, `DB_POOL_MAX_OVERFLOW` | `5`, `5` | Connection pool per instance. |
| `INGEST_WORKER_ENABLED` | `true` | Run the ingest worker in the service process. |
| `INGEST_WORKER_POLL_SECONDS` | `0.2` | Worker poll interval. |
| `UPLOAD_MAX_FILE_BYTES` | 25 MB | Per-file limit (keep under Cloud Run's 32 MiB). |
| `UPLOAD_MAX_FILES` | `40` | Files per upload. |
| `UPLOAD_MAX_UNCOMPRESSED_BYTES`, `UPLOAD_MAX_COMPRESSION_RATIO` | 250 MB, 200 | Zip-bomb guards for workbook contents. |
| `DUPLICATE_THRESHOLD` | `80` | Similarity (percent) at which an upload is flagged as a duplicate. |

Build-time (frontend): `VITE_API_BASE_URL` — empty in the image, so the browser calls the
API on the page's own origin.

## 5. The data

The plant data is **not in this repository** (it is real Ford plant data, and this
repository is public). The first database load is a restore of a `pg_dump` file that
the **project owner** provides, followed by the migrate job — the migrations alone cannot
build a usable database from empty. The runbook, section 4, has the exact commands.

## 6. Check a build locally (optional)

Before deploying you can run the production configuration on a workstation with Python
3.13, Node 24 + pnpm 10.32.1 and PostgreSQL 18 (or `docker compose -f
infra/docker-compose.yml up -d postgres`).

```bash
# database: roles, data, migrations (dump from the owner)
psql -h localhost -U postgres -d postgres -v migrator_password=... -v app_rw_password=... -f db/create_roles.sql
pg_restore -h localhost -U migrator --no-owner -d paint_appearance paint_appearance.dump

cd backend
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt && pip install --no-deps -e .
MIGRATOR_DATABASE_URL=postgresql+psycopg://migrator:...@localhost:5432/paint_appearance alembic upgrade head

# frontend, built exactly as in the image
cd ../frontend && corepack enable && pnpm install --frozen-lockfile && VITE_API_BASE_URL= pnpm build

# the API in production mode, serving the build
cd ../backend
ENV=production AUTH_OPEN_ACCESS=true STATIC_DIR=../frontend/dist INGEST_WORKER_ENABLED=false \
API_DOCS_ENABLED=false APP_DATABASE_URL=postgresql+psycopg://app_rw:...@localhost:5432/paint_appearance \
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Open http://127.0.0.1:8080 and check `/health/ready` and `/api/v1/auth/me`.
Or build the image itself: `docker build -t paint-appearance .`.

**Tests.** CI (`.github/workflows/ci.yml`) runs: frontend type generation drift check,
`pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build`; backend single-migration-head
check, OpenAPI drift check, and the backend tests that need no database
(`T01_DB=none python -m pytest tests -q -o addopts=""`); then the image build. The full
backend suite needs a restored copy of the data: point `T01_ADMIN_DSN` (an admin login)
and `T01_APP_DSN` (`app_rw`) at a **test copy** of the database, in libpq form
(`host=... port=... dbname=... user=... password=...`), in the environment or in
`backend/.env.test`, then run `python -m pytest tests -q`.

## 7. Open decisions

| Decision | Status |
|---|---|
| **D6 — Cloud SQL PostgreSQL major version** | Open. Every migration has been run on PostgreSQL 18; use 18 if Cloud SQL offers it and confirm with the owner before choosing another major. |
| **Sign-in** | Not in this release (owner decision 2026-10-20). Ford ID / Entra sign-in will come from another team; the role checks are already in the code and turn on when `AUTH_OPEN_ACCESS` is off. |
| **Network exposure** | While there is no sign-in the service **must stay internal-only** (`ingress: internal`, company network). Who may call it (`allUsers` invoker vs a user group behind an internal load balancer/IAP) is for the deployment and security teams to choose. |

Other decisions are recorded in [docs/DEFERRED.md](docs/DEFERRED.md) and
[docs/ADR/](docs/ADR/).
