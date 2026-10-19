# Deploying Paint Appearance on Google Cloud

This is the runbook for the deployment team. Read the repository [README](../../README.md)
first for what the application is and how it is built.

**Target:** one Cloud Run service (`paint-appearance`) that serves the API and the built
frontend on one origin, a Cloud SQL for PostgreSQL instance, a Cloud Storage bucket for
uploaded files, and a Cloud Run job (`paint-appearance-migrate`) that runs the database
migrations from the same image.

```
   company network / VPC only (ingress: internal)
                │
                ▼
   ┌──────────────────────────────┐        ┌───────────────────────────┐
   │ Cloud Run: paint-appearance  │        │ Cloud Run job:            │
   │  uvicorn  → FastAPI          │        │ paint-appearance-migrate  │
   │   /api/v1, /health  (API)    │        │  alembic upgrade head     │
   │   /*  built React frontend   │        │  (same image, as migrator)│
   │  ingest worker (in-process)  │        └─────────────┬─────────────┘
   └───────┬───────────────┬──────┘                      │
           │ app_rw        │ /data/raw (gcsfuse)         │ migrator
           ▼               ▼                             ▼
   ┌───────────────┐  ┌──────────────────┐      (same Cloud SQL database)
   │ Cloud SQL     │  │ Cloud Storage    │
   │ PostgreSQL    │  │ RAW_BUCKET       │
   │ paint_        │  │ uploaded         │
   │ appearance    │  │ workbooks        │
   └───────────────┘  └──────────────────┘
```

---

## 0. Before you start: no sign-in in this release

Owner decision 2026-10-20: **`AUTH_OPEN_ACCESS=true`**. Every visitor acts as one shared
account (`shared.access@paint-appearance`) with every role (viewer, engineer, admin), and
every write is recorded under that account. Ford ID / Entra sign-in comes later from
another team; the role checks stay in the code for them, and turning `AUTH_OPEN_ACCESS`
off switches them back on.

**So the service must not be reachable from the internet.** `service.yaml` sets
`run.googleapis.com/ingress: internal`: only the company VPC (and networks connected to
it, or an internal load balancer) can reach it. Do not change that until real sign-in is
in. This is an open decision for the owner and the security team (see the README).

## 1. Values you need

| Placeholder | Example | Meaning |
|---|---|---|
| `PROJECT_ID` | `ford-paint-prod` | GCP project |
| `REGION` | `asia-southeast1` | Region for every resource |
| `SQL_INSTANCE` | `paint-appearance-db` | Cloud SQL instance name |
| `RAW_BUCKET` | `ford-paint-appearance-raw` | Bucket for uploaded workbooks (globally unique) |
| `TAG` | `2026-10-20-1` | Image tag for this release |
| `NETWORK` | `default` | VPC the instance and users are on |

```bash
export PROJECT_ID=... REGION=... SQL_INSTANCE=... RAW_BUCKET=... TAG=... NETWORK=...
gcloud config set project "$PROJECT_ID"
```

Tools on the operator's machine: `gcloud`, `psql`/`pg_restore` 18, the
[Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/sql-proxy), `envsubst`
(GNU gettext), and a copy of this repository.

## 2. One-time project setup

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    artifactregistry.googleapis.com cloudbuild.googleapis.com \
    secretmanager.googleapis.com storage.googleapis.com

# Image registry
gcloud artifacts repositories create paint-appearance \
    --repository-format=docker --location="$REGION"

# Service accounts: one for the service, one for the migration job
gcloud iam service-accounts create paint-appearance-run
gcloud iam service-accounts create paint-appearance-migrate
```

## 3. Cloud SQL

**PostgreSQL major version — open decision D6.** Every migration has been run on
PostgreSQL **18**; use 18 if Cloud SQL offers it in your region, and confirm with the
owner before choosing another major. Use **C collation** for the database (step 4 does).

```bash
gcloud sql instances create "$SQL_INSTANCE" \
    --database-version=POSTGRES_18 --region="$REGION" \
    --edition=ENTERPRISE --tier=db-custom-1-3840 \
    --network="$NETWORK" --no-assign-ip \
    --backup-start-time=18:00 --enable-point-in-time-recovery \
    --retained-backups-count=14 --retained-transaction-log-days=7

gcloud sql users set-password postgres --instance="$SQL_INSTANCE" --prompt-for-password
```

Size note: the current data is about 350 MB on disk. The service keeps at most
`maxScale × (DB_POOL_SIZE + DB_POOL_MAX_OVERFLOW)` = 3 × 10 = 30 connections, well
under the instance limit.

## 4. Database roles and the first data load

Two roles, and the API enforces the split:

| Role | Owns / does | Used by |
|---|---|---|
| `migrator` | Owns the `paint_appearance` database and every object in it; runs DDL | The migrate job only (`MIGRATOR_DATABASE_URL`) |
| `app_rw` | SELECT; INSERT facts, staging and audit rows; a few narrow UPDATEs; **no DELETE, no DDL** | The service only (`APP_DATABASE_URL`) |

The API **refuses to start** if `APP_DATABASE_URL` names `postgres`, `migrator`,
`cloudsqlsuperuser` or another privileged role, and `/health/ready` fails if `app_rw`
holds a privilege it must not have.

**Why a restore and not just migrations:** the migrations cannot build a usable database
from empty (migration `0025` seeds standards for colours that were added through the
application). The first load is a restore of the owner's `pg_dump`, then the migrate job
applies anything newer than the dump.

**Get the dump from the project owner** (`paint_appearance_<date>.dump`, about 25 MB,
`pg_dump -Fc` format). It is real Ford plant data: it is never in git, and must stay on
company storage.

From a machine that can reach the instance (in the VPC, because it has no public IP):

```bash
# terminal 1: the proxy (add --private-ip; the instance has no public IP)
cloud-sql-proxy --private-ip --port 5432 "$PROJECT_ID:$REGION:$SQL_INSTANCE"

# terminal 2: roles + empty database (as postgres), then the data (as migrator)
psql "host=127.0.0.1 port=5432 user=postgres dbname=postgres" \
     -v migrator_password='CHOOSE-A-MIGRATOR-PASSWORD' \
     -v app_rw_password='CHOOSE-AN-APP-PASSWORD' \
     -f db/create_roles.sql

pg_restore -h 127.0.0.1 -p 5432 -U migrator --no-owner -d paint_appearance paint_appearance_<date>.dump

psql "host=127.0.0.1 port=5432 user=migrator dbname=paint_appearance" \
     -c "select version_num from alembic_version" -c "select count(*) from wavescan"
```

`pg_restore` must finish with no errors. The dump carries the table grants to `app_rw`.

## 5. Bucket for uploaded files

```bash
gcloud storage buckets create "gs://$RAW_BUCKET" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://$RAW_BUCKET" --versioning
```

Keep uploaded originals at least 24 months (decision D4): do not add a lifecycle rule
that deletes live objects sooner. Noncurrent versions can expire after, for example,
90 days.

## 6. Secrets and permissions

Passwords in the URLs must be URL-encoded if they contain `@ : / ? # %`.

```bash
printf '%s' "postgresql+psycopg://app_rw:APP_PASSWORD@/paint_appearance?host=/cloudsql/$PROJECT_ID:$REGION:$SQL_INSTANCE" |
  gcloud secrets create paint-appearance-app-database-url --data-file=-
printf '%s' "postgresql+psycopg://migrator:MIGRATOR_PASSWORD@/paint_appearance?host=/cloudsql/$PROJECT_ID:$REGION:$SQL_INSTANCE" |
  gcloud secrets create paint-appearance-migrator-database-url --data-file=-

RUN_SA="paint-appearance-run@$PROJECT_ID.iam.gserviceaccount.com"
MIG_SA="paint-appearance-migrate@$PROJECT_ID.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$RUN_SA" --role=roles/cloudsql.client
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$MIG_SA" --role=roles/cloudsql.client
gcloud secrets add-iam-policy-binding paint-appearance-app-database-url \
    --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding paint-appearance-migrator-database-url \
    --member="serviceAccount:$MIG_SA" --role=roles/secretmanager.secretAccessor
gcloud storage buckets add-iam-policy-binding "gs://$RAW_BUCKET" \
    --member="serviceAccount:$RUN_SA" --role=roles/storage.objectAdmin
```

The service never holds the migrator credential, and the job never holds the app one.

## 7. Deploy a release

```bash
# 1. build and push the image (Cloud Build runs the Dockerfile at the repo root)
gcloud builds submit --tag "$REGION-docker.pkg.dev/$PROJECT_ID/paint-appearance/app:$TAG" .

# 2. fill the placeholders in the two YAML files
export PROJECT_ID REGION SQL_INSTANCE RAW_BUCKET TAG
envsubst < infra/gcp/migrate-job.yaml > /tmp/migrate-job.yaml
envsubst < infra/gcp/service.yaml     > /tmp/service.yaml

# 3. migrations FIRST, then the service
gcloud run jobs replace /tmp/migrate-job.yaml --region "$REGION"
gcloud run jobs execute paint-appearance-migrate --region "$REGION" --wait
gcloud run services replace /tmp/service.yaml --region "$REGION"
```

Read each new migration's docstring (`backend/migrations/versions/`) before a release.
Most only add (for example `0050` adds one index), so the revision still serving keeps
working during the rollout; one that drops or tightens something needs a short
maintenance window.

**Who may open the site.** Cloud Run also checks IAM on every request. Because ingress is
internal and the app has no sign-in, the usual setup is to let everyone on the network
call it:

```bash
gcloud run services add-iam-policy-binding paint-appearance --region "$REGION" \
    --member=allUsers --role=roles/run.invoker
```

If your organisation policy forbids `allUsers`, grant `roles/run.invoker` to the
company's user group instead and put the service behind an internal load balancer or IAP;
the app accepts (and ignores) the platform's bearer token in open-access mode.

The startup probe calls `/health/ready`: a revision that cannot reach the database as
`app_rw`, finds forbidden privileges, or cannot write the raw store never takes traffic.

## 8. Verify a deploy

From inside the network (`SERVICE_URL` is shown by `gcloud run services describe
paint-appearance --region "$REGION" --format='value(status.url)'`):

```bash
curl -s "$SERVICE_URL/health/live"      # {"status":"alive", ...}
curl -s "$SERVICE_URL/health/ready"     # {"status":"ready","checks":{"database":{"status":"ok","role":"app_rw",...},"object_store":{"status":"ok",...}}}
curl -s "$SERVICE_URL/api/v1/auth/me"   # ... "auth_source":"open-access" ...
```

Then open `SERVICE_URL` in a browser: the landing page lists **FTM, AAT, FVL, SAP**, each
plant page shows the Wave Scan and Film Thickness overviews, and the browser console has
no errors. `/docs` returns 404 in production on purpose (`API_DOCS_ENABLED=false`).

Logs are JSON lines on stdout with a `severity` field (Cloud Logging shows the levels);
each line carries the request's `correlation_id`, which error responses also return, so a
user's error message can be matched to its log line.

## 9. Roll back

Send traffic back to the previous revision:

```bash
gcloud run revisions list --service paint-appearance --region "$REGION"
gcloud run services update-traffic paint-appearance --region "$REGION" --to-revisions REVISION=100
```

If the release's migrations only add, the old revision runs on the new schema and no
database change is needed. Otherwise run a one-off job execution with the **same image
that applied it** and the command `alembic downgrade -1`:

```bash
gcloud run jobs execute paint-appearance-migrate --region "$REGION" --wait --args="downgrade,-1"
```

Take an on-demand backup (section 10) before any downgrade.

## 10. Backup and restore

**Backups.** Step 3 turns on daily automated backups (14 kept) and point-in-time recovery
(7 days of logs). Before a risky change, take one by hand:

```bash
gcloud sql backups create --instance="$SQL_INSTANCE" --description="before release $TAG"
```

For a portable copy (for example to give the developers a fresh dump), run through the
proxy: `pg_dump -h 127.0.0.1 -U migrator -d paint_appearance -Fc -f paint_appearance_<date>.dump`,
and keep it on company storage.

**Restore the database** — always into a **new** instance, then switch:

```bash
# point in time
gcloud sql instances clone "$SQL_INSTANCE" "$SQL_INSTANCE-restore" --point-in-time="2026-10-20T08:00:00Z"
# or from a backup
gcloud sql backups list --instance="$SQL_INSTANCE"
gcloud sql backups restore BACKUP_ID --restore-instance="$SQL_INSTANCE-restore" --backup-instance="$SQL_INSTANCE"
```

Check the copy, add a new version of both secrets that points at the new instance,
change `SQL_INSTANCE` and deploy again (section 7) so the service and job use it.

**Restore an uploaded file.** The bucket keeps previous object versions:

```bash
gcloud storage ls --all-versions "gs://$RAW_BUCKET/PATH"
gcloud storage cp "gs://$RAW_BUCKET/PATH#GENERATION" "gs://$RAW_BUCKET/PATH"
```

## 11. Settings reference

Set in `service.yaml` (or baked into the image by the `Dockerfile`):

| Variable | Value in production | Why |
|---|---|---|
| `ENV` | `production` | HSTS on; the dev bypass is refused |
| `AUTH_OPEN_ACCESS` | `true` | No sign-in in this release (section 0) |
| `APP_DATABASE_URL` | secret `paint-appearance-app-database-url` | `app_rw` only |
| `RAW_STORE_DIR` | `/data/raw` | The bucket, mounted with gcsfuse |
| `STATIC_DIR` | `/app/static` (image) | The built frontend, served on the same origin |
| `API_DOCS_ENABLED` | `false` (image) | No Swagger UI in production |
| `PORT` | `8080` (image) | Cloud Run's port |
| `DB_POOL_SIZE`, `DB_POOL_MAX_OVERFLOW` | `5`, `5` | Keep `maxScale × 10` under the Cloud SQL connection limit |
| `INGEST_WORKER_ENABLED` | default `true` | The worker runs in the service; needs `cpu-throttling: false` (set) |
| `UPLOAD_MAX_FILE_BYTES` | default 25 MB | Keep below 32 MiB: Cloud Run rejects larger requests |

Set on the migrate job: `MIGRATOR_DATABASE_URL` (secret
`paint-appearance-migrator-database-url`). Every other variable is listed in the
repository README.

## 12. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Revision never becomes ready; logs say `APP_DATABASE_URL connects as ...` | The secret names a privileged role. It must be `app_rw`. |
| `/health/ready` 503 with `database.status: error` | Wrong password or URL-encoding in the secret, missing `cloudsql-instances` annotation, or the service account lacks `roles/cloudsql.client`. |
| `/health/ready` 503 with `forbidden_privileges_held` | Someone granted `app_rw` DELETE/DDL. Revoke it; the grants come only from the dump and migrations. |
| `/health/ready` 503 with `object_store` error | Bucket missing, the run service account lacks `storage.objectAdmin`, or the volume's `uid=10001` mount option was removed. |
| Migrate job fails with `MIGRATOR_DATABASE_URL is not set` | The job's secret reference is missing or the job service account cannot read it. |
| `pg_restore` errors about role `app_rw` or `migrator` | Run `db/create_roles.sql` before the restore, into an empty database. |
| Site loads but uploads fail with 413 | File over `UPLOAD_MAX_FILE_BYTES` or Cloud Run's 32 MiB request limit. |
| 403 from Google before the app | Caller is outside the VPC (ingress internal) or lacks `roles/run.invoker`. |
