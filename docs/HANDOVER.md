# Handover to the deployment team

This page is for the team that deploys Paint Appearance on Google Cloud. It says what
has already been done and checked, what has not, and which decisions are yours to make
before (or while) you deploy. The step-by-step deployment is in
[infra/gcp/README.md](../infra/gcp/README.md); the project overview is in the
[README](../README.md).

## 1. What we have done

| Area | Done | How it was checked |
|---|---|---|
| Application | FastAPI API and React frontend in **one container** (`Dockerfile`). The API serves the built site on the same origin, so there is no CORS and no second service. | CI job `container` builds the image on every push and runs it with the Cloud Run settings. |
| Database | PostgreSQL schema managed by Alembic migrations (`backend/migrations`). Two roles: `migrator` owns everything and runs migrations; `app_rw` is the only role the API uses. The API refuses to start as `postgres`, `migrator` or `cloudsqlsuperuser`. | CI creates the roles with `db/create_roles.sql`, migrates as `migrator`, and starts the API as `app_rw`. The full data restore was tested on PostgreSQL 18. |
| No sign-in (this release) | `AUTH_OPEN_ACCESS=true`: everyone acts as one shared account with every role, and every write is still recorded under that account. | Unit tests, plus CI checks `/api/v1/auth/me` returns `open-access`. |
| Cloud Run files | `infra/gcp/service.yaml` (internal ingress, Cloud SQL connection, bucket mounted for uploads, startup probe on `/health/ready`) and `infra/gcp/migrate-job.yaml`. | YAML validated. **Not yet deployed.** |
| Speed | Gzip on API responses (the largest list drops from 574 KB to 20 KB), one-year caching of hashed frontend files, a 30 s cache on the home-page summary, and a database index for Film reads. | Measured on a copy of the real data: every screen's API calls under 0.25 s, except Analysis & Report at up to about 1 s for the largest plant. |
| Security headers | HSTS, `X-Frame-Options: DENY`, `nosniff`; `/docs` and `/openapi.json` are off in production. | CI checks HSTS and that `/docs` returns 404. |
| Tests | Frontend: typecheck, lint, 478 unit tests, build. Backend: the database-free tests in CI; the full suite (about 2,400 tests) passes against a restored copy of the data. | CI on every push; the full suite was run before handover. |

## 2. What has NOT been checked yet

- **A real GCP deployment.** The `gcloud` commands in `infra/gcp/README.md` are written
  from Google's documentation; nobody has run them in your project yet. Expect to adjust
  names, regions and IAM to your organisation's standards.
- **Migrations on an empty database stop at 0024.** Migration 0025 seeds Film standards
  for colours that exist only in the real data. That is why the first install is a
  **restore of the data dump**, followed by `alembic upgrade head`
  ([infra/gcp/README.md section 4](../infra/gcp/README.md)). CI migrates an empty
  database to 0024 only, to check the wiring.
- **Load testing.** The app was built for about 30 users at four plants. Nothing has been
  tested at higher concurrency.

## 3. Decisions for you

Each row says what is open, what it affects, what we recommend, and where to change it.

| # | Decision | Affects | Our recommendation | Where |
|---|---|---|---|---|
| 1 | **PostgreSQL major version on Cloud SQL** (D6) | Compatibility of the restore and migrations | **PostgreSQL 18.** Every migration and the restore were run on 18. If your organisation requires another version, restore the dump on it in a test instance first and run `alembic upgrade head`. | Cloud SQL instance version |
| 2 | **Who can reach the site.** There is no sign-in, so anyone who reaches the URL can upload files, change standards and delete uploads. | Security | Keep `ingress: internal`, and put an **internal HTTPS load balancer with Identity-Aware Proxy (IAP)** in front, limited to a Google group of the plant users. If IAP is not available, grant `roles/run.invoker` to `allUsers` **only** while ingress stays `internal` (reachable from the company network / VPN only). Never use `ingress: all` in this release. | `infra/gcp/service.yaml` (ingress), IAM on the service |
| 3 | **Sign-in** (later, another team) | Accountability: today every change is recorded as "Shared access" | When sign-in arrives: validate Ford ID / Entra tokens in `backend/app/core/security.py`, map token roles to viewer / engineer / admin, then set `AUTH_OPEN_ACCESS=false`. The role checks on every route are already in the code. | `backend/app/core/security.py`, `AUTH_OPEN_ACCESS` |
| 4 | **The data dump** | First load | The dump is **not** in this public repository. Ask the application owner for it through a private channel. It is a `pg_dump -Fc` file of about 25 MB and contains plant measurements plus user names and email addresses (`app_user`), so treat it as **internal / personal data**: no public buckets, delete local copies after the restore. | [infra/gcp/README.md section 4](../infra/gcp/README.md) |
| 5 | **Passwords and secrets** | Security | Choose new passwords for `migrator` and `app_rw`; store both connection URLs in Secret Manager (names in `service.yaml` and `migrate-job.yaml`). Nothing secret is in this repository. | Secret Manager |
| 6 | **Region, size and cost** | Latency, cost | A region close to the plants (Thailand, Vietnam, South Africa), for example `asia-southeast1`. `minScale: 1` with CPU always allocated keeps the background file reader running, so it costs one always-on small instance. Cloud SQL: start with 1-2 vCPU and 4 GB. | `service.yaml`, Cloud SQL |
| 7 | **Database connections** | Stability | Each instance opens at most 10 connections (`DB_POOL_SIZE` 5 + `DB_POOL_MAX_OVERFLOW` 5). Keep `maxScale x 10` below the Cloud SQL connection limit. | `service.yaml` |
| 8 | **Backups and retention** (D4) | Recovery | Cloud SQL automated backups **and** point-in-time recovery (7+ days). Bucket: object versioning on, keep uploaded files at least 24 months. Test one restore before go-live. | Cloud SQL, bucket settings |
| 9 | **Plant data visibility** (D3) | Privacy between plants | Today every user sees all four plants. If plants must not see each other's data, that needs sign-in first (decision 3). | Product owner |
| 10 | **Pass/Fail grading** (D1) | Numbers shown | Grading is deliberately off (`grading_available: false`); the app shows measurements against standards, not a pass rate. Do not switch it on without the product owner. | Product owner |
| 11 | **A person's name in a public repository** | Privacy | The data owner's name appears in a test fixture, two tests and `docs/DEFERRED.md`. Decide with the owner whether to remove it or make the repository private. | Repository settings |

## 4. Order of work

1. Read decision 2 and agree access with your security team.
2. Follow [infra/gcp/README.md](../infra/gcp/README.md) sections 1-6: project, Cloud SQL,
   roles and data restore, bucket, secrets.
3. Section 7: build the image, run the migrate job, deploy the service.
4. Section 8: verify (`/health/ready`, `/api/v1/auth/me`, open the site, and check that
   the header reads **Database: Connected**).
5. Turn on backups and point-in-time recovery, then test one restore (section 10).

Questions about the data, the plants or the screens: the application owner. Questions
about the code: the git history and `docs/` (architecture, data model, pipeline,
security).
