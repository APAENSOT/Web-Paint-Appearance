# Paint Appearance Platform — Data Model (WaveScan v1)

**Status:** Approved design. Implemented via Alembic from T02 onward.  
**Companions:** `00-ARCHITECTURE.md`, `02-PIPELINE.md`, `03-SECURITY.md`, `04-ANALYSIS.md`  
**Source of the current schema:** `Paint Appearance/Component/Database/sql/` (read-only reference)

---

## 1. Principles

1. **Facts are immutable.** No `UPDATE`/`DELETE` on `wavescan` from the application role. Supersede and correction rows only (ADR 0005).
2. **Grades are never stored.** No PASS/WARNING/FAIL column. Grading is `domain/grading.py` on read (`04-ANALYSIS.md`).
3. **A file's identity is SHA-256 of its bytes.** Filenames are labels. The database reload guard is `UNIQUE (file_hash, source_sheet)` -- a batch is one sheet of one file (`02-PIPELINE.md` section 1, T04). The same bytes cannot insert a second batch. A **live** hash 409s; after abandon or retire, T25 reopens the existing `load_id`.
4. **Nothing is silently dropped.** Every source row is loaded, duplicate, rejected, or quarantined. Enforced by `ck_batch_balance`.
5. **Aliases live in tables, not code.** New spelling = approved INSERT, not a deploy. Column headers follow the same rule (`ref_column_alias`).
6. **Audit is append-only.** `audit_event`: INSERT granted, UPDATE/DELETE granted to nobody.
7. **Attribution is a person.** `loaded_by` / `actor_user_id` is the authenticated Ford ID (or the bypass identity in development), never `current_user`.
8. **Timestamps are `timestamptz`.** Four plants, three time zones.
9. **Measurements are `NUMERIC`.** Full precision in the fact table. Views round for display.
10. **Keep the physical constraints that already work.** Generated `month`/`year`, `fk_ws_zone_tol`, range CHECKs, `reject_log.raw_row` JSONB, rejected mappings retained on `ref_plant_zone_map`. **T58 (revision 0022):** the insert gate for a checkpoint is `fk_ws_plant_point (plant, model, checkzone) -> ref_plant_ws_point`, **NOT VALID**, replacing `fk_ws_model_zone`. Each plant x model keeps its own WaveScan gold (its own panel names; the walk number is proof only), so a U704 liftgate still cannot land on Ranger. Earlier facts keep what they stored (ADR 0005) and are kept as **retired** gold rows so they and their corrections keep an FK target. `ck_zone_rule` is Hood / Roof / Floor in the name, any case.

---

## 2. What stays from the demo schema

Keep tables and semantics unless this document revises them:

| Table | Keep |
|---|---|
| `ref_plant`, `ref_plant_alias` | yes; seed SAP and FVL as rows even if FVL loads are deferred (D5) |
| `ref_model`, `ref_model_alias` | yes |
| `ref_checkzone`, `ref_checkzone_alias` | yes |
| `ref_model_zone` | yes -- the AAT/FTM long-form catalogue and leftover lists; source of the T58 long-form gold copies and of T29 ZONE packs. **No longer** the `wavescan` insert FK (T58) |
| `ref_plant_ws_point` | T58 -- FK target for new `wavescan` inserts: `(plant, model, zone_code)` live membership, `point_no` walk proof only, retired rows kept for earlier facts |
| `ref_color`, `ref_color_alias` | yes; **add** `grading_family` (nullable until D2) |
| `ref_paintline`, `ref_paintline_alias` | yes |
| `ref_plant_zone_map` | yes — propose / review / approve; rejected rows kept |
| `load_batch` | revised status enum, UNIQUE hash, fingerprint, no DELETE cascade of evidence |
| `stg_raw` | add `extra` JSONB, `raw_headers` JSONB; drop ON DELETE CASCADE |
| `wavescan` | type changes, identity change, supersede/correction columns; revoke UPDATE/DELETE |
| `reject_log` | add `TEMPLATE_UNKNOWN` and related reasons; no ON DELETE CASCADE |
| `unidentified_model` | no ON DELETE CASCADE |
| Views `v_wavescan`, `v_load_summary`, `v_car_completeness`, model slices | filter `is_duplicate = false` **and** active (not superseded) |

`sql/06_demo_data.sql` and plant-specific vocabulary scripts (`12_`, `13_`, `14_`) are **seed data**, migrated into Alembic data migrations or a seed command, not dropped.

---

## 3. `load_batch` (revised)

```sql
load_id              bigserial PK
source_file          text NOT NULL          -- label only
source_sheet         text NOT NULL
plant_code           text REFERENCES ref_plant
file_hash            char(64) NOT NULL      -- SHA-256 hex
UNIQUE (file_hash, source_sheet)            -- T04: one batch per sheet; same bytes still cannot land twice
raw_store_key        text NOT NULL          -- object-store path = hash
template_fingerprint text                   -- hash of normalised header row
raw_headers          jsonb                  -- verbatim header cells
status               text NOT NULL
  CHECK (status IN (
    'RUNNING','PENDING_REVIEW','COMMITTED',
    'FAILED','SUPERSEDED','REJECTED_TEMPLATE',
    'ABANDONED'                                 -- T21, revision 0008
  ))
rows_in_file         integer NOT NULL DEFAULT 0
rows_loaded          integer NOT NULL DEFAULT 0   -- LOAD dispositions in the proposal
rows_duplicate       integer NOT NULL DEFAULT 0
rows_rejected        integer NOT NULL DEFAULT 0
rows_quarantine      integer NOT NULL DEFAULT 0
started_at           timestamptz NOT NULL DEFAULT now()
finished_at          timestamptz
loaded_by            uuid REFERENCES app_user     -- person, not DB role
notes                text
superseded_by        bigint REFERENCES load_batch
profile_id           bigint REFERENCES ref_template_profile  -- T18, section 6.8
review_revision      char(64)                     -- T18: hash of the projection reviewed
domain               text                         -- T26: 'WAVESCAN'
semantic_signature   text                         -- T26: the contract this sheet carried
sheet_class          text                         -- T26: WAVESCAN / OUT_OF_SCOPE_SHEET / UNKNOWN_DATA_SHEET
unreviewed_headers   jsonb                        -- T26: headers nobody has decided about
CONSTRAINT ck_batch_balance CHECK (
  status <> 'COMMITTED'
  OR rows_in_file = rows_loaded + rows_duplicate + rows_rejected + rows_quarantine
)
```

**T18 columns.** `profile_id` names the template profile that parsed the batch (section 6.8), or NULL when no active profile claims the layout -- which is why such a batch is `REJECTED_TEMPLATE` and no data row is read. `review_revision` is the hash of the review projection (section 6.9) a person saw; `commit_batch` re-derives it from the stored bytes and refuses if it disagrees. Both are written by the worker after the parse, so both are on the column-scoped UPDATE allow-list (section 8). `template_fingerprint` stays frozen at insert: it is provenance, and after a replay the layout that actually parsed the batch is the one on its projection rows, not this column.

**Status lifecycle:** `RUNNING` -> `PENDING_REVIEW` -> `COMMITTED`. `FAILED` on pipeline crash (staging still inspectable). `REJECTED_TEMPLATE` when fingerprint is unknown (no parse of data rows). `SUPERSEDED` when a later committed batch replaces this one in the same logical-file scope, or when an Admin retires a bad commit. `ABANDONED` (T21) when an Admin removes a `PENDING_REVIEW`, `REJECTED_TEMPLATE` or `FAILED` batch that has **zero** `wavescan` rows from the review queue, with a reason: bytes, staging, projection, acknowledgements, overrides and audit are retained, and replay and commit refuse it. Abandon is the pre-commit sibling of supersede, never a DELETE; a committed batch is superseded, not abandoned. Only `CorrectionService` writes either status -- the ingest service writes neither. **T25** reverses both, and only through `CorrectionService.restore_batch`: `ABANDONED` returns to the status its latest `batch.abandon` audit event recorded (`PENDING_REVIEW` if there is none), audited `batch.reopen`; `SUPERSEDED` returns to `COMMITTED` with `superseded_by` cleared, audited `batch.restore`, and its existing `wavescan` rows read as current again through `v_wavescan_active` -- nothing is re-inserted. Two doors reach it: `POST /batches/{load_id}/restore` (Admin) and an identical-bytes `POST /uploads` (Engineer for `ABANDONED`, Admin for `SUPERSEDED`). No grant changed.

**Removed:** `SUCCESS` (renamed `COMMITTED`), `ROLLED_BACK` (use `FAILED` + inspect staging). Application DELETE of a batch is forbidden.

**Cascade change:** `stg_raw`, `reject_log`, `unidentified_model` reference `load_batch` with `ON DELETE RESTRICT` (or no action). A batch row cannot be removed while evidence exists. Retention jobs may archive, not wipe, after policy (D4).

**Filename scope for supersede** (same rule as the 2026-08-19 design, still valid): a logical file is `(plant_code, source_file)` for web uploads. Same bytes anywhere → skip via UNIQUE hash. Same name, new hash, same plant → supersede on commit.

---

## 4. `stg_raw` (revised)

Keep verbatim TEXT columns for the current 21 logical fields so existing queries survive.

**Add:**

```sql
extra         jsonb NOT NULL DEFAULT '{}'::jsonb   -- unmapped header → value
raw_headers   jsonb                                -- optional denormalised copy of batch headers
```

A new template column that has no `ref_column_alias` lands in `extra`. Nothing is lost. Mapping approval copies it to a logical field on replay.

Retention: `purge_stg_raw` stays, default 6 months, **SUCCESS/COMMITTED only**. After purge, fact-table `NUMERIC` values remain; reconstruction of unmapped extras does not. Object store keeps the original bytes per D4.

---

## 5. `wavescan` (revised)

```sql
measurement_id          bigserial PK
measured_date           date NOT NULL
month                   smallint GENERATED ALWAYS AS (extract(month from measured_date)::smallint) STORED
year                    smallint GENERATED ALWAYS AS (extract(year  from measured_date)::smallint) STORED
plant                   text NOT NULL
model                   text NOT NULL
checkzone               text NOT NULL
color                   text NOT NULL
tolerance_group         text NOT NULL          -- H/V axis for grading (see 04-ANALYSIS)
paintline               text NULL              -- NULL when blank, absent or (None) (T39, ADR 0013)
serial_no               text NULL              -- NULL when blank or absent; never generated (T39, ADR 0013)

cf                                     numeric NOT NULL   -- was REAL
lw, sw, doi, du, wa, wb, wc, wd, we    numeric NULL       -- was REAL; NULL allowed from T39 (ADR 0013, rev 0016): DOI/DU/Wa-We optional, LW/SW only after Engineer HOLE_APPROVAL
b                                         numeric NULL

load_id                 bigint NOT NULL REFERENCES load_batch
source_sheet            text NOT NULL
source_row              integer NOT NULL
is_duplicate            boolean NOT NULL DEFAULT false
is_superseded           boolean NOT NULL DEFAULT false
corrects_measurement_id bigint REFERENCES wavescan (measurement_id)
correction_reason       text
corrected_by            uuid REFERENCES app_user
corrected_at            timestamptz
loaded_at               timestamptz NOT NULL DEFAULT now()

-- existing FKs kept:
-- fk_ws_plant, fk_ws_color, fk_ws_paintline, fk_ws_model
-- fk_ws_model_zone (model, checkzone)
-- fk_ws_zone_tol   (checkzone, tolerance_group)

-- existing CHECKs kept (nonneg, doi 0-100, cf 0-100, b ±100, date 2000-2100, serial non-empty)

UNIQUE (load_id, source_row) WHERE corrects_measurement_id IS NULL
    -- T09 revision 0005. Partial unique *index* `uq_ws_load_row_original`
    -- (PostgreSQL has no partial UNIQUE table constraint). Ingest rows still
    -- occupy the cell exclusively; a correction keeps the original pair and
    -- is outside the predicate, which is what lets ADR 0005's insert-a-new-row
    -- correction exist. Replaces the full UNIQUE (load_id, source_row) that
    -- T02 wrote as `uq_ws_load_row`.
```

`source_file` is dropped as a uniqueness component (it remains on `load_batch`). Two plants sending `June.xlsx` no longer collide. A corrected re-send is a new `load_id`. A correction of an already-committed cell is a new `wavescan` row that **keeps** `(load_id, source_row)` and sets `corrects_measurement_id`; the partial unique is what makes that possible.

**Active data predicate** (one helper, used by every reporting view and API query). `GET /measurements` and the T23 Measurement History reads (months, facets, week summaries, vehicle sets, points) both read through it and neither restates it:

```sql
WHERE w.is_duplicate = false
  AND w.is_superseded = false
  AND b.status = 'COMMITTED'
```

**Correction — RESOLVED in T02 (revision `0002`). `wavescan` is insert-only. Do not write an UPDATE path.**

Earlier drafts of this section offered two options and left the choice to T02: flag the original with a dedicated repository UPDATE, or keep `wavescan` insert-only and record supersession in a side table. **T02 chose insert-only + side table.** The alternative is closed; an agent that implements a repository function which UPDATEs `wavescan` is reintroducing what T01 removed.

The flow:

1. Insert the correction as a new row: `corrects_measurement_id` set, unchanged fields copied, new values, plus `correction_reason` / `corrected_by` / `corrected_at`.
2. Insert a row in `measurement_supersession` naming the retired measurement, the `reason`, and the actor. An `AFTER INSERT` trigger sets `is_superseded` on the original.
3. Write the `audit_event` in the same transaction (§6.2). The side table is evidence, not a substitute for the audit trail.

Both rows stay queryable; the correction is the active one.

**Two invariants the schema enforces, so application code does not have to:**

- The application holds **no `UPDATE` on `wavescan`** at all, not even on `is_superseded`. The trigger function is `SECURITY DEFINER` for exactly this reason and is callable only as that trigger.
- **`is_superseded` cannot be set at INSERT time** — a `BEFORE INSERT` trigger refuses it, for the schema owner too. A row inserted already superseded is hidden by every reporting view with no record of who hid it, which is a delete wearing a hat. Retire a measurement by inserting the supersession record; never by pre-flagging the fact.

`measurement_supersession` has no `UPDATE` and no `DELETE` grant: a retirement cannot be withdrawn, only followed by a further correction.

---

## 6. New tables

### 6.1 `app_user`

```sql
id            uuid PK
entra_oid     text UNIQUE NOT NULL
upn           text NOT NULL
display_name  text NOT NULL
created_at    timestamptz NOT NULL DEFAULT now()
last_seen_at  timestamptz
```

Roles are **not** stored here. They come from the token (or the bypass identity) at request time.

### 6.2 `audit_event`

```sql
id             bigserial PK
occurred_at    timestamptz NOT NULL DEFAULT now()
actor_user_id  uuid REFERENCES app_user   -- NULL for system/worker
actor_type     text NOT NULL CHECK (actor_type IN ('user','system'))
action         text NOT NULL              -- 'batch.commit' · 'batch.supersede' · 'measurement.correct' · 'mapping.approve' · ...
entity_type    text NOT NULL
entity_id      text NOT NULL
before         jsonb
after          jsonb
correlation_id text
```

No UPDATE, no DELETE grants to any application role.

### 6.3 `ref_column_alias`

```sql
id             uuid PK
raw_header     text NOT NULL              -- normalised: lower, trim, '_' → ' '
logical_field  text NOT NULL              -- 'date','plant','model',... including measure fields
domain         text NOT NULL DEFAULT 'WAVESCAN'   -- T26, revision 0009
is_approved    boolean NOT NULL DEFAULT false
proposed_by    uuid REFERENCES app_user
approved_by    uuid REFERENCES app_user
created_at     timestamptz NOT NULL DEFAULT now()
UNIQUE (domain, raw_header)
```

Replaces the Python `HEADER_ALIASES` dict in `reader.py`. Seed rows from the current dict (`reader.py:24-46`) as **approved**. Unknown headers → `TEMPLATE_UNKNOWN` / mapping proposal, not a code change.

**`domain` (T26).** An alias means something *within a vocabulary*. Every existing row is `WAVESCAN`, and `reference.load_reference_data` injects only that domain's rows into the reader, so a future FilmThickness package cannot inherit this one's meaning of `Panel`, `Date` or `Model` (spec S6). T26 adds no FilmThickness alias and no FilmThickness table: the column is the boundary, not the onboarding. The Admin mapping-approve route names the domain explicitly rather than leaning on the default.

### 6.4 `ref_color_family`

```sql
family_name    text PK                    -- 'Light Metallics' ... 'Dark Solids'
display_order  smallint NOT NULL UNIQUE
family_code    text UNIQUE                -- LM MM DM LS MS DS (T-STANDARDS-D2 / 0014)
```

Six rows, order from `Prototype.html` `COLOR_FAMILY_ORDER` (lines 1807-1814). Codes come from the owner workbook; names stay Prototype spellings (not the sheet’s “Meduim” typos).

### 6.5 Colour family is plant-scoped (D2 / ADR 0010)

```sql
-- unused optional default; ingest and grading do not read this
ref_color.grading_family text REFERENCES ref_color_family   -- stays NULL in this slice

ref_plant_color (
  plant_code, color_name,          -- PK
  family_name,                     -- NULL = offered but unmapped
  is_offered                       -- false = not on this plant's list
)
```

Source of truth for grading family is `(plant_code, color_name)`, not a global colour column. Ignite Orange is Medium Solids at AAT/FTM/FVL and Medium Metallics at SAP. Alembic **0014** (T-STANDARDS-D2) creates these objects. Until that revision is applied, standing **0013** still has only global `ref_color.grading_family` (all NULL).

`NULL` family on an offered plant-colour cannot be graded. Disable = `is_offered=false`; History is unchanged; no DELETE of a row History used.

`color_group` (`GREEN`/`SILVER`/...) stays as a display grouping. It is **not** the grading taxonomy (`04-ANALYSIS.md` § findings). `GET /meta.unmapped_color_count` is the count of offered plant-colours with null family. `grading_available` stays false until D1.

`ref_model_series` + `ref_plant_model` attach existing `model_code` rows to plants the same way. Admin does not mint `model_code` here.

**Merged names (T64, revision 0026, [ADR 0014](ADR/0014-merged-colour-identity.md)).** `ref_color.merged_into` (FK to `ref_color`, not self, one level only: trigger `trg_ref_color_merge_one_level`) points a historical name at its canonical name. `Shadow Black` and `Absolute Black` are merged into `Absolute / Shadow Black` (inactive, un-offered; the canonical name is offered at AAT/FTM/FVL with Dark Metallics). Facts keep the stored name (ADR 0005). `v_wavescan_active` and `filmthickness_active` return `COALESCE(rc.merged_into, color)`; ingest folds a resolved name before the offered check and the INSERT; film standards `latest()` and Overview's per-colour `cf_standard` fold before DISTINCT ON. Alias, mapping and plant-offer writes onto a merged name are refused (422).

### 6.6 `cf_standard`

```sql
id               uuid PK
scope            text NOT NULL CHECK (scope IN ('FAMILY','COLOR'))
family_name      text REFERENCES ref_color_family
color_name       text REFERENCES ref_color
orient           char(1) NOT NULL CHECK (orient IN ('H','V'))
ford             numeric NOT NULL
min              numeric NOT NULL
effective_from   date NOT NULL
source_document  text
source_note      text NOT NULL
created_by       uuid REFERENCES app_user
created_at       timestamptz NOT NULL DEFAULT now()
plant_code       text REFERENCES ref_plant      -- T37 / ADR 0012, nullable
CHECK (
  (scope = 'FAMILY' AND family_name IS NOT NULL AND color_name IS NULL)
  OR (scope = 'COLOR'  AND color_name  IS NOT NULL)
)
```

**T37 (revision 0015, ADR 0012):** Ford/Min are plant x family. `POST /standards` requires `plant_code` and appends H+V for that plant. Seed rows keep `plant_code` NULL as the fallback. Overview and catalogue pick, per (family or colour, orient), the latest row by `created_at` where `plant_code = :plant`, else the latest NULL-plant row; `effective_from` is stored for audit and does **not** filter by the selected month. COLOR still beats FAMILY.

Never updated in place. A colour-scope row counts only when both `ford` and `min` are present (mirrors `targetsFor`: override applies only if `fordH != null`).

Seed version 1 from `DEFAULT_STANDARDS` (`Prototype.html:1798-1805`) with `source_note = 'prototype DEFAULT_STANDARDS; Color Family - IMG Plants document'` and `source_document` filled when the owner supplies the file (D2).

### 6.7 `proposed_mapping`

```sql
id              uuid PK
kind            text NOT NULL CHECK (kind IN ('COLUMN','ZONE','ALIAS_COLOR','ALIAS_MODEL','ALIAS_PLANT','ALIAS_CHECKZONE','ALIAS_PAINTLINE'))
payload         jsonb NOT NULL
load_id         bigint REFERENCES load_batch
status          text NOT NULL CHECK (status IN ('PROPOSED','APPROVED','REJECTED'))
similarity      numeric           -- advisory score; never auto-applied
proposed_by     uuid REFERENCES app_user
decided_by      uuid REFERENCES app_user
created_at      timestamptz NOT NULL DEFAULT now()
decided_at      timestamptz
```

Engineer proposes; Admin approves **COLUMN** and **ZONE**; identity aliases apply in the Engineer propose transaction. Rejected proposals are kept (same reason as `ref_plant_zone_map`).

**`ZONE` (T29).** Implemented as one **atomic, owner-proved checkpoint set** for one `(plant_code, model_code)` (P703 spec section 5, opened to any `ref_model` catalogue). The payload is `plant_code`, `model_code`, `mappings[] {raw_zone_text, raw_position?, zone_code}`, `named_owner`, `proof_hash` (64 lower-case hex), `proof_document`, `method`, `note`. The `zone_code` set must **equal** `ref_model_zone` for that model -- 31 rows, 33 rows, or 32 that drop `LTTAILGATE` and repeat a hood are 422 before anything is written -- and a zone that is not a position on that model is 422. `load_id` is optional for `ZONE` only, when `payload.plant_code` names the plant (FVL has no committable batch); `COLUMN` / `ALIAS_MODEL` still require it. Approve inserts missing rows `APPROVED` with the proof, certifies a row that already maps the same label to the same zone, and refuses the **whole** set (409, rollback) if any row maps it to a different zone or carries a different proof. `zone_code` is never updated. Approve replays iff `load_id` is set, flips no plant and never sets `fixture_verified`.

**`ALIAS_COLOR` (finish-batch spec, identity; remainder spec A2).** Implemented as a plant-scoped spelling → existing `ref_color.color_name`. Payload is `raw_value`, `color_name`, `plant_code`, optional `note`. Extra keys are 422 (colour-family / D2 stays closed). A colour name not in `ref_color` is 422 -- this route never mints a catalogue name. `load_id` is optional when `payload.plant_code` names the plant, so a committed remainder can teach future files; when `load_id` is set, `plant_code` must match the batch. **Engineer `POST /mappings/proposals` applies** the alias in the same transaction (`mapping.apply` audit) and replays iff the batch is replayable (PENDING_REVIEW / REJECTED_TEMPLATE, zero `wavescan` rows). A committed remainder keeps the alias when replay is refused (ADR 0005). Rostered `ALIAS_MODEL` (P703 spellings) uses the same Engineer-apply path. Leftover programs (J73 / CX743 / V363 / U704) are 422 onto Ranger; they may bind onto that leftover's own catalogue (CX743 → CX743). The cleaner, after an exact alias miss, also applies a unique identity fold (gray/grey, paint-code prefixes, collapsed double letters) onto **one** existing `ref_color.color_name`; zero or two hits stay `UNKNOWN_COLOR` for uploader cross-check.

**`ALIAS_CHECKZONE` (T41, D-31).** Implemented as one Excel panel spelling at one `(plant_code, model_code)` -> an **existing** `zone_code` on that model's `ref_model_zone` list -- **T58 (D-58-10):** on that plant x model's **live WaveScan gold** when it has one. Payload is `raw_value`, `zone_code`, `plant_code`, `model_code`, optional `note`. Extra keys are 422. A blank / `(None)` panel is 422. A `zone_code` not on that model is 422; this route never mints a zone. Engineer `POST /mappings/proposals` applies in the same transaction: one `ref_plant_zone_map` row (`confidence = APPROVED`, `proposal_method = ENGINEER_ALIAS`, `approved_by` set, **no** owner proof). The reference loader treats those rows as live **in addition to** T29 proved rows (`proof_hash` + `verified_by`). An Admin ZONE pack without proof still stays out of the cleaner. `load_id` is optional when `payload.plant_code` is set. Same spelling already mapped to the same zone is a no-op; a different zone is 409. Complete named-owner packs remain `ZONE` (T29 / Admin). `ALIAS_PLANT` and `ALIAS_PAINTLINE` still answer 501.

**`held_labels` / `HeldLabelGroup` (identity-ingest UX).** `GET /batches/{id}` returns these groups with `display_group` (`colour`, `model`, `zone`, `empty_identity`, `date`, `header`) and `operator_message`. **I5:** an empty identity sentinel beats `ALIAS_MODEL`. When the raw cell is blank, `None`, `(None)`, or `null`, `display_group` is `empty_identity` and `teachable_kind` is null even if the cleaner reason is `UNKNOWN_MODEL` or `VEHICLE_IDENTITY_MISSING`. Do not teach `(None)` onto a catalogue model.

### 6.8 `ref_template_profile` (T18, revision 0006; amended by T26, revision 0009)

```sql
profile_id            bigserial PK
plant_code            text NOT NULL REFERENCES ref_plant
domain                text NOT NULL                       -- T26: 'WAVESCAN'
semantic_signature    text NOT NULL                       -- T26: the selection key
template_fingerprint  text NOT NULL                       -- exact ordered layout; provenance
version               integer NOT NULL DEFAULT 1
is_active             boolean NOT NULL DEFAULT true
fixture_verified      boolean NOT NULL DEFAULT false
fixture_file_hash     char(64)          -- the workbook that proved it, where one did
fill_missing_plant    boolean NOT NULL DEFAULT false
verified_by           text              -- T26: the named owner who proved it
verified_at           timestamptz       -- T26
notes                 text
created_at            timestamptz NOT NULL DEFAULT now()
UNIQUE (domain, plant_code, semantic_signature, version)
UNIQUE (domain, plant_code, semantic_signature) WHERE is_active   -- one active version per contract
CHECK  (fixture_verified = false OR notes IS NOT NULL)      -- a claim of proof names its proof
CHECK  (fixture_verified = false OR (verified_by IS NOT NULL AND verified_at IS NOT NULL))
```

A plant layout, versioned (`02-PIPELINE.md` section 4.1). **Data, not code:** no column holds SQL or Python, and `fill_missing_plant` is the only behaviour it can switch on. A profile decides *whether a layout is known*, never what a value means.

**Two hashes, and the difference is the whole of T26.**

| Column | What it is | What it does |
|---|---|---|
| `semantic_signature` | SHA-256 over `domain` + the **sorted set** of recognised logical fields | Selects the profile, with `domain` and `plant_code` |
| `template_fingerprint` | SHA-256 over the **ordered** recognised fields (with `?` gaps) plus the sorted unrecognised extras -- T18's algorithm, unchanged | Provenance only |

Selection was `(plant_code, template_fingerprint)` under T18, which refused a sheet whose only change was that somebody moved a column: FTM August and SAP July carry the same twenty-one logical fields in a different order. Selection is now `(domain, plant_code, semantic_signature)`, so a reorder parses; the ordered hash still moves, so "the columns moved" stays visible on the batch and on the profile that proved it. Design M5 is amended accordingly; M4, M6 and M7 are unchanged.

`app_rw` holds **SELECT only**, still. The one application path that writes here is `publish_template_profile` (section 8), a `SECURITY DEFINER` function that requires a named owner, notes and a proving stored-workbook hash, appends a version, deactivates the previous active one for the same contract, and writes `audit_event` in the same transaction (spec S20). That is what keeps M6 true by construction: the Admin mapping-approve route has no grant, no statement and no function call that could promote a layout to commit-capable.

### 6.8.1 `ref_template_column_policy` (T26, revision 0009)

```sql
policy_id      bigint GENERATED BY DEFAULT AS IDENTITY PK
profile_id     bigint NOT NULL REFERENCES ref_template_profile ON DELETE RESTRICT
raw_header     text NOT NULL              -- normalised, as ref_column_alias is
policy         text NOT NULL CHECK (policy IN ('MAPPED','IGNORED'))
logical_field  text                       -- required when MAPPED
approved_by    text                       -- required when IGNORED
reason         text                       -- required when IGNORED
created_at     timestamptz NOT NULL DEFAULT now()
UNIQUE (profile_id, raw_header)
```

What a named person decided about one header of one profile. A column that is not a WaveScan field stops being an `UNREVIEWED_HEADER` by becoming an `IGNORED` row with an approver and a reason -- never by being ignored automatically (spec S9). FVL's `Panel2` is the case it exists for. No column holds SQL or Python. Written only by `publish_template_profile`; `app_rw` holds SELECT.

### 6.8.2 Plant-scoped identity aliases (T26, revision 0009)

`ref_model_alias` and `ref_color_alias` gain a nullable `plant_code`, unique per plant where set and unique globally where null. The cleaner looks up `(plant, spelling)` first and falls back to the global row, so one plant's local wording can never relabel another plant's vehicle (spec S11/S12).

The global `ASSUMPTION` rows mapping bare `P703` and `P703 DBL` to Ranger are **relocated, not copied**: to FVL by the owner's lock, and to AAT/FTM only where those plants' own staged rows carry the spelling. SAP is deliberately left without one -- SAP writes `P703 RAP`, which is not a Ranger, and mapping it is a later activation slice. Colour aliases stay **identity only**: `grading_family` is still NULL on every colour and `POST /standards` is still 501 (D1, D2).

`ref_plant_zone_map` gains `proof_hash`, `proof_document` and `verified_by` for the named plant/quality owner proof S15 requires, distinct from the Admin `approved_by` who recorded it. **T26 seeds no SAP or FVL row**, approved or proposed: the mapping engine already swapped SAP tailgate Top/Bottom and got 20 of 25 FVL verticals wrong, and sequence is not physical identity.

**T29 (revision 0010).** `app_rw`'s UPDATE grant on `ref_plant_zone_map` widens from T01's `confidence, approved_by, approved_at, note` to also cover `proof_hash, proof_document, verified_by, proposal_method, raw_position`, so an Admin `ZONE` approve can certify an existing row in place. `plant_code`, `model_code`, `raw_zone_text` and `zone_code` stay frozen; there is still no DELETE. The **loader** now injects a zone map only when it is `APPROVED` **and** `proof_hash IS NOT NULL` **and** `verified_by IS NOT NULL` (S15): an Admin approval without a named owner's proof stays in the table as a record and is not live. AAT/FTM are unaffected -- their labels resolve through `ref_checkzone_alias`. Revision 0010 inserts no zone map.

### 6.9 `stg_review_row` (T18, revision 0006)

```sql
load_id              bigint NOT NULL REFERENCES load_batch ON DELETE RESTRICT
source_row           integer NOT NULL
disposition          text NOT NULL CHECK (disposition IN ('LOAD','DUPLICATE','REJECT','QUARANTINE','AGGREGATE_ROW'))
reason               text
detail               text
canonical            jsonb NOT NULL     -- what commit would insert
raw                  jsonb NOT NULL     -- what the file said, values and extras
normalized_fields    jsonb NOT NULL DEFAULT '[]'::jsonb
profile_id           bigint REFERENCES ref_template_profile
template_fingerprint text NOT NULL      -- the layout that actually parsed this row
review_revision      char(64) NOT NULL
created_at           timestamptz NOT NULL DEFAULT now()
PRIMARY KEY (load_id, source_row)
```

One row per source row of one parse, whatever its disposition. It is what lets a reviewer see raw against canonical without re-parsing the workbook on every GET.

**`AGGREGATE_ROW` (T26, spec S16).** A report roll-up -- a `[All]` hierarchy row, of which FTM May has 1064 in 1320 and FVL September 133 in 165. Its numbers summarise other rows of the same file, so loading it would invent a vehicle. It is staged, projected here, and disclosed as a count; it never reaches `wavescan`, and a sheet whose only rows are roll-ups is refused with `AGGREGATE_ONLY_SHEET`.

It is deliberately **not** a reject and not a quarantine: calling it either would put thousands of rows behind an acknowledgement gate meant for values the platform would not accept, or invite somebody to map `[All]` to a vehicle. For the same reason a roll-up sits **outside** the balance equation of section 6, exactly as an entirely blank row already does -- `rows_in_file` counts the file's data rows, and a pivot's own summary of them is not one.

**Staging evidence, not `wavescan`:** `app_rw` holds `SELECT, INSERT` and nothing else. There is no UPDATE by design -- changing a proposed value means an approved mapping and a replay, or new bytes (ADR 0005, design M13). Cleared only by `reset_batch_staging` (section 8).

### 6.10 `review_acknowledgement` (T19, revision 0007)

```sql
ack_id          bigserial PK
load_id         bigint NOT NULL REFERENCES load_batch ON DELETE RESTRICT
plant_code      text NOT NULL REFERENCES ref_plant
file_hash       char(64) NOT NULL
category        text NOT NULL CHECK (category IN
                  ('REJECTED_ROWS','QUARANTINED_MODELS','DUPLICATE_ROWS','POSSIBLE_REPLACEMENT'))
note            text
review_revision char(64) NOT NULL
actor_user_id   uuid NOT NULL REFERENCES app_user
created_at      timestamptz NOT NULL DEFAULT now()
CHECK (category NOT IN ('REJECTED_ROWS','QUARANTINED_MODELS')
       OR (note IS NOT NULL AND length(btrim(note)) > 0))   -- the note is the record
CHECK (note IS NULL OR length(note) <= 2000)                -- same bound as a supersede reason
```

A named person read one warning category of one sheet and accepted it, at one `review_revision`. Three of the four categories block a commit while unacknowledged (`WARNINGS_UNACKNOWLEDGED`); `POSSIBLE_REPLACEMENT` is advisory and blocks nothing.

**Append-only:** `app_rw` holds `SELECT, INSERT`, no UPDATE and no DELETE, and `reset_batch_staging` does not touch it. A replay invalidates an acknowledgement by moving the batch's `review_revision` out from under it, never by removing the record -- the projection is re-derivable staging, while "somebody read these rows and accepted them" is evidence.

### 6.11 `review_override` (T21, revision 0008)

```sql
override_id       bigserial PK
load_id           bigint NOT NULL REFERENCES load_batch ON DELETE RESTRICT
plant_code        text NOT NULL REFERENCES ref_plant
file_hash         char(64) NOT NULL
source_row        integer NOT NULL
field             text NOT NULL CHECK (field IN
                    ('lw','sw','cf','doi','du','wa','wb','wc','wd','we','b'))
previous_proposed numeric            -- canonical before this row; null only if that measure was null
new_value         numeric            -- CHECK: NULL only when field = 'b' (clear)
reason            text NOT NULL CHECK (length(reason) BETWEEN 1 AND 2000 AND btrim(reason) <> '')
review_revision   char(64) NOT NULL  -- the sheet's revision the reviewer had loaded
actor_user_id     uuid NOT NULL REFERENCES app_user
created_at        timestamptz NOT NULL DEFAULT now()
INDEX (load_id, source_row, field, created_at)
```

A named person replaced one **measure** of one `LOAD` row before commit, with a reason (design F11). Identity -- plant, model, checkzone, colour, tolerance group, paintline, serial, date -- is never overridable; that is a mapping or a corrected re-upload.

**Evidence, not staging.** `app_rw` holds `SELECT, INSERT` only: no UPDATE (a second override is another row, and the latest per `(source_row, field)` by `created_at` wins) and no DELETE. It is **not** cleared by `reset_batch_staging`, which revision 0008 does not touch.

**How it takes effect.** `IngestService._plan` applies the current overrides to the rows that are `LOAD` after dedup, every time it re-derives a sheet from the stored bytes -- the first parse, a mapping replay, the synchronous revalidation that follows an override save, and `commit_batch`. So the projection's `canonical`, the `review_revision`, and the values commit inserts all carry the override, while `stg_raw` and the projection's `raw` still show what the file said. The revision moving is what stops an acknowledgement of the pre-override rows satisfying the commit gate.

### 6.12 FilmThickness (T46, revision 0017)

A second domain package beside WaveScan (spec `2026-09-29-filmthickness-data-design.md` F1-F18), not extra `wavescan` columns. `load_batch.domain = FILMTHICKNESS` and `sheet_class = FILMTHICKNESS` for a PELT FilmBuild sheet.

* **`filmthickness`** -- insert-only facts, one row per (vehicle, point, layer): `measured_date`, `plant`, `model`, `color`, `job_no` / `serial_no` (NULL when blank or `0`; never generated), `point_code`, `src_location_text`, `layer_code` (`ECOAT`, `PRIMER`, `BASE`, `CLEAR`), `thickness` (full precision), `logical_vehicle_id`, `load_id`, `source_sheet`, `source_row`, and the same duplicate / supersede / correction columns as `wavescan`. FK `(model, point_code)` to `ref_model_film_point`. `app_rw`: SELECT, INSERT only. Reads go through the view **`filmthickness_active`** (section 10).
* **`logical_vehicle_id`** -- plant, day, model, colour and the real identity (VIN, else Job Number). Cab and Box walks of one car share it when both identities are blank or equal; one blank and one filled do not. Two files keep two `load_id`.
* **`ref_film_point`** / **`ref_model_film_point`** -- point names (`001HOOD`), not `ref_checkzone`. Ranger DBL and Raptor: the FVL P703 Quick Summary 94 names. `P703 RAPCAP` 93 and `P703 SGL` 58 from the FTM walks. Identity is the name; `point_no` is display order only.
* **`ref_film_location_map`** -- owner-proved (`proof_hash` + `verified_by`) plant spelling -> point; only proved rows are read. T47 (revision 0018) seeds the 233 P703 DBL maps (FTM `_DBL_`/`_RB_`, SAP, AAT) from `backend/tests/fixtures/gold/P703-DBL-film-location-map.json`. A proved map outranks an exact gold spelling; an unresolved label is held whatever its number. Hor/Ver is `ref_model_film_point.orientation` on the gold Ranger/Raptor points (30 H / 64 V); a mapped fact inherits it from its gold point.
* **Reads (T48)** -- `GET /api/v1/plants/{plant_code}/filmthickness/{facets,vehicles,vehicles/{logical_vehicle_id}/points}`, any authenticated role, `filmthickness_active` only. A vehicle is `logical_vehicle_id` (Cab + Box = one, `load_ids` as provenance); its points are the model's whole catalogue LEFT JOIN active facts, with `orientation` from `ref_model_film_point` and four nullable layers (never padded).
* **Monthly overview (T66-T68, T73)** -- `GET /api/v1/plants/{plant_code}/filmthickness/overview?month=&models=&colors=`, any authenticated role, `filmthickness_active` only.
  * **Boxes.** One box per layer x model x colour x H/V. H/V comes from `ref_plant_film_point`, falling back to `ref_model_film_point`. Statistics use `domain/boxplot.box_stats`.
  * **Spec lines.** `lo`/`hi`/`target` and `standard_scope` (COLOR/PLANT/NONE) come from `film_standards.effective_rule`, latest rule for every month.
  * **Status.** `grading.film_box_status` on the box **mean**:
    * Clear: FAIL below lo, WARNING below target, else PASS; never OVER.
    * Other layers: FAIL below lo, OVER above hi.
    * NONE gives null.
  * **Line labels.** Minimum/Maximum, or No point below / Minimum requirement on Clear.
  * **Out of spec.** `out_of_spec` lists each reading below lo or above hi, with its own `measured_date`.
  * **Family and order.** The plant-specific family comes from `ref_plant_color` + `ref_color_family`. `color_sequence` / `color_rank` order colours by the Base range ladder (T73).
  * **Not included.** No pass rate or counts; `grading_available` stays false.
  * **No Maximum on Clear.** `POST /filmthickness/standards` refuses `hi` on CLEAR (T67).
* **`ref_film_model_alias (plant_code, raw_token)`** -- FilmThickness model spellings. FTM filename `RAP` is RAPCAP and `RB` is Raptor here; WaveScan `ref_model_alias` is untouched.
* **`ref_model`** gains `wavescan_ok`, `expected_film_point_count`, `display_name`. `P703 RAPCAP` and `P703 SGL` are `wavescan_ok = false` with `expected_zone_count = 0` (CHECK: 0 only then).
* **`ref_column_alias`** rows with `domain = FILMTHICKNESS` are the film header vocabulary; the WaveScan reader never sees them.

Extra points (`095`-`098`, `FTWISH`), locations that are not a catalogue name, and sheets whose model cannot be named are `QUARANTINE` rows in `stg_review_row` (`EXTRA_POINT`, `UNMAPPED_POINT`, `FILM_MODEL_UNRESOLVED`), never facts.

### 6.13 `film_standard` (T62, revision 0024)

FilmThickness micron standards, the container only (T62-CONTEXT D-FS-01..11). The film analog of `cf_standard` (section 6.6).

```sql
id               uuid PK DEFAULT gen_random_uuid()
plant_code       text NOT NULL REFERENCES ref_plant
layer_code       text NOT NULL CHECK (layer_code IN ('ECOAT','PRIMER','BASE','CLEAR'))
orient           char(1) NOT NULL CHECK (orient IN ('H','V'))
color_name       text NULL REFERENCES ref_color      -- NULL = plant-wide layer rule
lo, hi, target   numeric(6,2) NULL, each 0..500 microns
source_document  text NULL
source_note      text NOT NULL (non-blank)
created_by       uuid NULL REFERENCES app_user
created_at       timestamptz NOT NULL DEFAULT now()
CHECK (lo IS NOT NULL OR hi IS NOT NULL)
CHECK (lo IS NULL OR hi IS NULL OR lo <= hi)
CHECK (target IS NULL OR layer_code = 'CLEAR')
CHECK (target IS NULL OR ((lo IS NULL OR lo <= target) AND (hi IS NULL OR target <= hi)))
INDEX ix_film_standard_latest (plant_code, layer_code, color_name, orient, created_at DESC)
```

* **Append-only** (D-FS-03). `app_rw` / `wavescan_loader`: SELECT, INSERT only; never UPDATE or DELETE. Every publish writes `audit_event` (`film_standards.publish`, entity `plant:layer:colour-or-*`) in the same transaction.
* **H/V pair** (D-FS-06). `POST /api/v1/filmthickness/standards` (Admin) always inserts an H row and a V row; a flat plant publishes the same numbers twice. `orient` is never NULL.
* **Grain** (D-FS-01/02). A per-colour row is plant x colour, any layer (AAT BC1 is stored as `PRIMER`, so Primer can be per colour). Never plant x family. The colour must be `ref_plant_color.is_offered` at that plant when published (D-FS-08); un-offering later does not hide old rows.
* **Latest wins** (D-FS-04). Per `(plant, layer, colour-or-NULL, orient)` the effective row is the latest `created_at` (then `id`). No `effective_from`. Older rows stay as history.
* **Precedence** (D-FS-05), in `app.domain.film_standards.effective_rule`: the latest per-colour row, else the latest plant-wide row (`color_name NULL`), else **no standard** (ungraded). Never another plant, colour or family.
* **`target` on CLEAR only** (D-FS-07): the prototype's Clear "avg". `lo` is the floor, `hi` the ceiling.
* **Read**: `GET /api/v1/plants/{plant_code}/filmthickness/standards`, any authenticated role: latest rules at that plant plus offered colours with family (context only). No status, no pass rate; `grading_available` stays false.
* **No seed yet** (D-FS-11). Revision 0024 inserts nothing. Numbers come from a later owner-signed `FILM-STANDARDS-AUDIT.md` and a separate seed migration.

---

## 7. Reject reasons (extended)

Keep existing `reject_log.reject_reason` values. Add:

```
TEMPLATE_UNKNOWN
HEADER_AMBIGUOUS
UNMAPPED_COLUMN
```

`TEMPLATE_UNKNOWN` is typically a **batch-level** status (`REJECTED_TEMPLATE`) rather than a per-row reject. Per-row `UNMAPPED_COLUMN` is for extra cells that are not required.

Later additions: `COLOR_NOT_OFFERED`, `MODEL_NOT_OFFERED` (0014), `PLANT_MISMATCH` (0016), and **`FILM_ONLY_MODEL`** (T115-FIX, revision 0040). `FILM_ONLY_MODEL` is a Wave Scan row naming a Film-only model (RAPCAP, Single CAP). It is not teachable, and an Attach never reloads it. `MODEL_NOT_OFFERED` means a model that is not on the plant's list, and an Attach reloads it (T115).

---

## 8. Database roles

| Role | Rights |
|---|---|
| `app_rw` | CONNECT; SELECT on refs and facts; INSERT on `wavescan`, `stg_raw`, `reject_log`, `unidentified_model`, `load_batch`, `audit_event`, `proposed_mapping`, `measurement_supersession`, `cf_standard`, `ref_column_alias`, **`ref_model_alias` (T08, Admin approve only)**, `app_user`, `ingest_job`; UPDATE **only** on `load_batch.status/counts/plant_code/superseded_by/notes/timestamps`, `ingest_job` claim columns **including `enqueued_at` (T08 replay re-queue)**, `app_user` (upn, display_name, last_seen_at), mapping-proposal status, and alias approval; **no DELETE** anywhere; **no UPDATE on `wavescan` at all** -- supersede goes through `measurement_supersession` (section 5), not a repository UPDATE. `SELECT` **only** on `ref_template_profile` (T18) -- no INSERT and no UPDATE, so nothing in the application can mark a layout `fixture_verified`; `SELECT, INSERT` on `stg_review_row` (T18) with **no UPDATE**, because a proposed value is replaced by a replay, never edited; `SELECT, INSERT` on `review_acknowledgement` (T19) with **no UPDATE and no DELETE**, because an acknowledgement is a statement a named person made at a time -- changing your mind means acknowledging again and both records stay, and a replay invalidates one by moving the batch's `review_revision` rather than by deleting it; `SELECT, INSERT` on `review_override` (T21) with **no UPDATE and no DELETE**, for the same reason, and not cleared by `reset_batch_staging`. T21 adds no column to the `load_batch` UPDATE allow-list: `ABANDONED` is written through the existing `status` grant. `EXECUTE` on `reset_batch_staging(bigint)` (T08, widened by T18) so replay can clear **one** batch's `stg_raw` / `reject_log` / `unidentified_model` / `stg_review_row` when that batch has **zero** `wavescan` rows; the function cannot write `wavescan` or `load_batch`. `SELECT` on `ref_template_column_policy` (T26) with no INSERT, UPDATE or DELETE: it is written only by `publish_template_profile`. `EXECUTE` on `publish_template_profile(...)` (T26, revision 0009), a `SECURITY DEFINER` function with a fixed `search_path` that is the **only** way the application can create a fixture-verified profile version -- it requires a named owner, notes and a proving stored-workbook hash, appends a version and deactivates the previous active one for that `(domain, plant, semantic signature)`, writes the column policy, and writes `audit_event` in the same transaction; it cannot touch `wavescan` or `load_batch`, and the mapping-approve route neither calls it nor holds a grant that would let it write the table directly. `SELECT, INSERT` on `worksheet_decision` (T39, revision 0016) with **no UPDATE and no DELETE**: an Engineer's IGNORE_HEADER / PLANT_CONFIRM / HOLE_APPROVAL answer for one sheet, re-applied on every replay; its FK cascades only through `purge_workbook`. `EXECUTE` on `purge_workbook(text, char(64), uuid, text, text)` (T37, revision 0015, ADR 0011), a `SECURITY DEFINER` function with a fixed `search_path` and `PUBLIC` revoked: it writes `workbook.purge` to `audit_event` first, then deletes one plant + hash's `load_batch` rows and their staging, review, reject, unidentified-model, ingest-job and `wavescan` rows, and refuses (409) when another file depends on them; `app_rw` still holds **no** table DELETE on `wavescan` or `load_batch`. `profile_id` and `review_revision` (T18), and `domain` / `semantic_signature` / `sheet_class` / `unreviewed_headers` (T26), are updatable because the worker writes them after the parse and re-derives all six on every replay. `SELECT, INSERT` on `ref_plant_zone_map` (T01) and `UPDATE (confidence, approved_by, approved_at, note, proof_hash, proof_document, verified_by, proposal_method, raw_position)` (T29, revision 0010) so an Admin `ZONE` approve can insert or certify a proved row; `plant_code`, `model_code`, `raw_zone_text` and `zone_code` are not updatable. `plant_code` is updatable because the batch row must exist before its rows are read (T04) -- since **T17** it is written at insert from the upload's `expected_plant` and the ingest service no longer updates it, so the grant is now only the supersede/backfill path, not the ingest path; no column was added to this list; `source_file`, `source_sheet`, `file_hash`, `raw_store_key`, `loaded_by` stay frozen at insert. |
| `app_ro` | SELECT on reporting views and facts (dashboard) |
| `migrator` | DDL; used by Alembic in CI; credentials never in the app `.env` |
| `postgres` / cloudadmin | out of application config entirely |

`wavescan_loader` as named today is retired or renamed to `app_rw` with the reduced grant set (T01).

---

## 9. Prisma / ORM

None. SQLAlchemy 2.x (or raw psycopg3) + Alembic. The demo used psycopg3 directly; either is acceptable. T02 records the choice. **Do not introduce Prisma or an extra database.**

---

## 10. Active-data helper

One SQL view or repository function implements the predicate in §5. Every list endpoint uses it. Bypassing it is a correctness bug even when today's output looks right.

FilmThickness (T46): the view `filmthickness_active` is that helper for `filmthickness`.

---

## 11. Volume

Demo load: 2479 rows / two months / three plants in scope. Annual volume is trivial for PostgreSQL. No partitioning in v1.

---

## 12. Open items owned here

| # | Question | Resolves |
|---|---|---|
| D2 | `grading_family` population and Aluminum/Aluminium | `DEFERRED.md` |
| D4 | object-store retention vs `stg_raw` 6-month purge | `DEFERRED.md` |
| — | insert-only `wavescan` vs single-flag UPDATE for supersede | **CLOSED in T02** — insert-only + `measurement_supersession` (§5) |
| — | `load_batch.loaded_by` old value | **T02 deviation:** the old `text` column holding `current_user` was renamed `loaded_by_role_legacy` rather than dropped, and `loaded_by uuid` added beside it. Safe to drop once the owner confirms. |
