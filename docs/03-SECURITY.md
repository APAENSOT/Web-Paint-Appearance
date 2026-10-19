# Paint Appearance Platform — Security

**Status:** Approved design. T01 is the first coding task and is **blocking** for any API that talks to this database.  
**Evidence paths** are under `Paint Appearance/Component/Database/` unless noted.

This document exists because a quality system that can erase its own evidence is not deployable. Architecture and pipeline assume the remediations below are done.

---

## 1. Findings in the demo (verified)

`README.md` Safety section states the loader role "cannot drop tables, delete rows, or alter reference data. Verified." Known limitations say deleting a batch "needs rights the loader role deliberately does not have."

**Both statements are false.** Code and grants:

| Claim vs reality | Evidence |
|---|---|
| No DELETE on facts | `sql/10_role.sql` lines 86–88: `GRANT SELECT, INSERT, DELETE, UPDATE ON wavescan` |
| No DELETE on batches | `sql/10_role.sql` line 99: `GRANT … DELETE ON load_batch` |
| Delete is admin-only | `src/wavescan_loader/loader.py` ~371: `DELETE FROM wavescan WHERE load_id = %s` |
| Evidence retained | ~381: `DELETE FROM load_batch WHERE load_id = %s` — `stg_raw`, `reject_log`, `unidentified_model` use `ON DELETE CASCADE` (`02_staging.sql`, `04_quarantine.sql`) |
| Edits are audited | `loader.py` ~434: `UPDATE wavescan SET …`; no `audit_event` table in the 17-table schema |
| Person is attributed | `load_batch.loaded_by DEFAULT current_user` — always role `wavescan_loader` |
| Reload guard is durable | `file_hash` has **no UNIQUE** (`02_staging.sql`) |
| Least privilege for replace | `config.py` carries `admin_user` / `admin_password` (postgres) in the same app `.env` |
| Login | `ui/app.py` docstring: "No login" |

In-place edit of `lw, sw, cf, doi, du, wa…we, b` is in `ui/edit_dialog.py` (`_FREE_TEXT`, round to 1 decimal on save). Confirmation dialog is not an audit trail.

**Product rule after T01:** application cannot DELETE batches or UPDATE measurement values. See ADR 0005.

---

## 2. T01 remediation (must land first)

1. Revoke `DELETE` and generic `UPDATE` on `wavescan` and `load_batch` from the application role.
2. Change FKs from `ON DELETE CASCADE` to `ON DELETE RESTRICT` (or equivalent) on evidence tables.
3. Create `audit_event` (INSERT-only).
4. `UNIQUE (file_hash)` on `load_batch`.
5. Remove `WAVESCAN_ADMIN_PASSWORD` / superuser from application environment. `.env.example` must not document a postgres password for the app.
6. Stop shipping `--replace` / UI delete-upload / in-place edit as supported features.
7. Rewrite README Safety and Known-limitations so they match grants (docs that lie are a security defect).

Until T01 is done, **do not** point FastAPI at this database with a role that still has DELETE.

---

## 3. Database roles (target)

| Role | Use |
|---|---|
| `app_rw` | API + worker. INSERT facts/staging/audit and Admin-approved aliases (`ref_column_alias`, `ref_model_alias`); SELECT refs; UPDATE only batch status/counts, ingest-job claim columns (including `enqueued_at`), and mapping proposal status; EXECUTE `reset_batch_staging` (staging only, zero `wavescan` rows); no DELETE; no DDL |
| `app_ro` | Read models / future reporting user |
| `migrator` | Alembic in CI only |
| Cloud SQL IAM user | Production; **no password** in Secret Manager for the DB if IAM auth is used |

Local: passwords in gitignored `.env`. Production: Cloud SQL IAM + Secret Manager for anything that is not IAM.

---

## 4. Application authentication

- **Ford ID** via Entra OIDC. SPA: Authorization Code + PKCE. Server validates JWKS, issuer, audience, expiry.
- Access token in memory; refresh via **httpOnly** cookie — not `localStorage`.
- Roles from token (app roles or group claims mapped to Viewer / Engineer / Admin). **Deny by default.**
- Every mutating route declares required role from day one (`Depends(require_role("engineer"))`).
- `AUTH_DEV_BYPASS` works **only** when `ENV=development` (or `APP_ENV=development`). Production image must not honour it (T04/T06: fail closed if bypass is set in non-dev).

`app_user` mirrors Entra oid for FKs. Roles are not duplicated as a writable column that can drift from the token.

**This release: no sign-in (owner decision, 2026-10-20).** `AUTH_OPEN_ACCESS=true` makes every request act as one shared account (`shared.access@paint-appearance`, `auth_source: open-access`) holding all three roles, so writes are still attributed to an `app_user` row. It may run in production, but the service must be reachable only from the company network (`infra/gcp/service.yaml` sets Cloud Run ingress to `internal`). The role checks in this section and section 5 stay in the code; turning `AUTH_OPEN_ACCESS` off brings them back for the team that adds Ford ID sign-in. It cannot be combined with `AUTH_DEV_BYPASS`.

---

## 5. RBAC matrix

| Capability | Viewer | Engineer | Admin |
|---|---|---|---|
| Read dashboards / measurements | yes | yes | yes |
| Upload files | no | yes | yes |
| Commit clean `PENDING_REVIEW` batch | no | yes | yes |
| Propose mapping / alias | no | yes | yes |
| Approve mapping / alias / standards | no | no | yes |
| Supersede committed batch | no | no | yes |
| Insert correction row (reason required) | no | yes | yes |
| Read one plant's Measurement History: months, facets, week summaries, vehicle sets, points (T23) | yes | yes | yes |
| Read one plant's FilmThickness facets, vehicles, gold point grid (T48) | yes | yes | yes |
| Read the standards catalogue and a plant's model points (RO13) | yes | yes | yes |
| Read one plant's workbooks, rows, issues, history (T19; Engineer since RO12) | no | yes | yes |
| Acknowledge a review warning (note required for rejects/quarantine) (T19) | no | no | yes |
| Read one sheet's vehicle sets and points; filter the upload inbox (T21; Engineer since RO12) | no | yes | yes |
| Save a numeric review override on a pending sheet (reason required) (T21) | no | no | yes |
| Abandon a sheet that never committed (reason required) (T21) | no | no | yes |
| Reopen abandoned identical-file upload (T25) | no | yes | yes |
| Restore superseded sheet (`POST .../restore` or identical-file upload) (T25) | no | no | yes |
| Publish an owner-verified template profile (T26) | no | no | yes |
| Run Alembic / DDL | no | no | no (CI migrator) |

**T19 (plant Data Manager).** Every route under `/api/v1/plants/{plant_code}/workbooks` is **Admin**, checked on the server, including the five reads: design M15 makes this phase Admin-only, and chrome is not security. The RBAC of the routes T19 does not own is deliberately unchanged -- upload and commit stay Engineer, mapping approve and supersede stay Admin -- so an Engineer who knows a workbook URL is refused while still being able to upload and commit as before. The one mutation, `POST .../acknowledgements`, is append-only and attributed: `review_acknowledgement.actor_user_id` is NOT NULL, so an acknowledgement nobody can name cannot be written. It carries no measurement value and changes no fact; what it changes is whether a sheet with rejected, quarantined or duplicated rows may be committed at all.

**T23 (Measurement History).** The four reads under
`/api/v1/plants/{plant_code}/history/` are available to **every
authenticated role**, exactly as `GET /measurements` is: they answer what is
current, through the same `v_wavescan_active` predicate, and an Engineer or
Viewer who can already page that list gains no new data from grouping it.
They are a separate router from the workbook manager precisely so that
"readable by anyone authenticated" and "Admin only" cannot drift into each
other: `/plants/{plant_code}/workbooks*` stays Admin, and an Engineer still
gets 403 there. History adds no mutation -- correcting a point remains the
T09 Engineer route against a `measurement_id`.

**T48 (FilmThickness reads).** The three GETs under `/api/v1/plants/{plant_code}/filmthickness/` (facets, vehicles, a vehicle's points) are available to **every authenticated role**, read only the `filmthickness_active` view, and add no mutation, correction route or audit event; film facts never appear on `GET /measurements` or `/history/*`.

**T21 (upload review).** The two new reads (`.../vehicles`, `.../vehicles/{vehicle_id}/points`), the inbox query on the workbook list, `POST .../overrides` and `POST /api/v1/batches/{load_id}/abandon` are **Admin**, server-checked; Engineer and Viewer get 403, an unauthenticated caller 401. Upload, commit, mapping and supersede RBAC is unchanged. An override is append-only and attributed (`review_override.actor_user_id` NOT NULL, `app_rw` has no UPDATE or DELETE on the table); it may change only measure fields and only on a `LOAD` row of a `PENDING_REVIEW` sheet, and it never writes `wavescan` -- the value reaches `wavescan` only through a later commit. Abandon writes one status and an audit event, and is refused for any batch with `wavescan` rows.

**T25 (reopen / restore).** `POST /api/v1/batches/{load_id}/restore` is **Admin**. Identical-file `POST /uploads` may reopen `ABANDONED` as Engineer or Admin, and may restore `SUPERSEDED` as Admin only. Nothing DELETEs `wavescan` or `load_batch`; unique `file_hash` stays.

**T29 (atomic ZONE sets).** No new path and no RBAC change: Engineer proposes, Admin approves, on the existing `/mappings/proposals` routes. A `ZONE` approve writes one complete 32-row set for one plant and P703 model, all or nothing, carrying the typed `named_owner` as `verified_by` and the Admin as `approved_by` -- two columns on purpose, because an Admin visual approve is not S15 proof. Revision 0010 widens `app_rw`'s column-scoped UPDATE on `ref_plant_zone_map` to the proof columns only; `zone_code` and the label's identity stay frozen, and there is still no DELETE. The loader ignores any zone map without `proof_hash` and `verified_by`. Approving flips no plant's `is_active` and sets no `fixture_verified`.

**T26 (owner-publish of a template profile).** `POST /api/v1/plants/{plant_code}/template-profiles/publish` is **Admin**, server-checked; Engineer and Viewer get 403 and an unauthenticated caller 401. Upload, commit, mapping and supersede RBAC is unchanged.

Admin is the *door*, not the authority. The body must name a plant or quality owner who verified the layout, notes that name the proof, and the SHA-256 of a workbook **already stored for that plant** -- the route does not accept Excel, so what gets certified is always bytes the platform can replay. `app_rw` still holds **SELECT only** on `ref_template_profile` and on `ref_template_column_policy`: the write happens inside `publish_template_profile(...)`, a `SECURITY DEFINER` function with a fixed `search_path` that refuses a blank owner, blank notes or a missing proof hash, appends an immutable version, deactivates the previous active one for that `(domain, plant, semantic signature)`, and writes `audit_event` in the same transaction. It cannot reach `wavescan` or `load_batch`.

That grant is what makes design M6 structural rather than a review note: the Admin mapping-approve route writes aliases and has no statement, no grant and no function call that could set `fixture_verified`, however that route is later edited. Publishing then replays the batches it unblocks and **commits nothing** -- an Engineer still presses commit on a sheet a person has read. Nothing in T26 DELETEs `wavescan` or `load_batch`, and `reset_batch_staging` is unchanged (ADR 0005, spec S21).

**RO12 (owner, 2026-10-13).** The seven reads of the plant Data Manager -- the workbook list and upload inbox, one workbook, its rows, issues and history (T19), and one sheet's vehicle sets and their points (T21) -- are **Engineer** (Engineer or Admin, `EngineerReader`), as the T39 worksheet already was. The reason is the uploader: an Engineer may send a file (`POST /uploads`) and answer and approve its worksheet, and could not then list or open it; at AAT nobody who uploads is meant to need Admin (RO10 defect F2). A Viewer still gets 403 and an unauthenticated caller 401. **No write changed role:** acknowledgement, override, purge, template publish, abandon, restore, supersede, mapping approve and every standards write stay Admin, and `tests/test_ro12_uploader_roles.py` walks every non-GET route that depends on the Admin role and proves each refuses an Engineer. This supersedes the read clauses of the T19, T21 and T23 paragraphs above ("every route under `/workbooks` is Admin", "an Engineer still gets 403 there"). An Engineer's own "Approve" on the worksheet (`load-ready`) already records the duplicate / rejected / quarantined acknowledgements in that Engineer's name with a fixed note before committing (T39); the Admin acknowledgement route is for the Data Manager's own commit path and stays Admin. The screen offers each control only to the roles its route allows, decided in `frontend/src/api/roles.ts`; that is chrome, and the server check above is the security.

**RO13 (owner, 2026-10-13).** `GET /api/v1/standards/catalogue` and `GET /api/v1/plants/{plant_code}/model-points` are available to **every authenticated role** (`CurrentPrincipal`, as the T23 History reads): they are reference data -- families, Ford / Min rows, offered colours and models, point counts -- and carry no measurement, so a Viewer or Engineer reading Standard - Color Family / Model and Model Detail gains nothing they could misuse. An unauthenticated caller still gets 401. **Every `POST /standards*` and every other write stays Admin** (`tests/test_ro13_standards_reads.py` walks the `/standards*` writes and proves each refuses a Viewer). This supersedes RO12's note that these two reads are Admin.

Plant segregation (can FTM staff see AAT?) is **D3** in `DEFERRED.md`. Until decided, v1 may show all plants to authenticated users **or** filter by a claim — T03 must not invent a third scheme. Default until D3: all plants visible to all roles (simplest); document it as temporary.

---

## 6. Secrets and supply chain

- No secrets in git. `.env` gitignored; `.env.example` has names only.
- GitHub Actions → GCP via **Workload Identity Federation**. No long-lived JSON keys in the repo.
- `uv.lock` / frontend lockfile committed. Audit in CI.
- Container scan before push (Trivy or equivalent) when images exist.
- Ford PAC/proxy IPs belong in a **local-only** setup note, not in the public-facing README of the git repo. The GitHub remote is private; still do not copy internal proxy addresses into `Paint Application/README.md`.

---

## 7. Upload and API hardening

- Size/count/magic/zip-bomb: `02-PIPELINE.md` §2.
- Helmet-equivalent headers, CORS allowlist (frontend origin only), rate limit on upload and auth.
- Request body limits. DTO validation (Pydantic); extra fields forbidden where it does not break multipart.
- Stable error shape `{ statusCode, error, message, correlationId }`. No stack traces to clients.
- TLS in GCP (Cloud Run ingress). Local HTTP on localhost only.

---

## 8. Data classification

Paint measurements, body serials, plant identifiers, and standards are **internal Ford quality data**. The GitHub repository must remain **private**. Do not commit Excel workbooks into `Paint Application`. Reference vault stays on the intern machine / `Paint Appearance`.

---

## 9. Logging

Structured logs may include `load_id`, `file_hash`, plant, correlation id. They must **not** include raw `.env` values, access tokens, or full serial dumps in debug mode on shared aggregators without retention review.

---

## 10. What "enterprise" means here

Thirty users does not justify Kubernetes. It does justify: immutable facts, attribution, least privilege that matches the README, no silent deletes, OIDC when IT is ready, and a database that refuses illegal states (`99_verify.sql` stays in CI).
