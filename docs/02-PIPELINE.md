# Paint Appearance Platform — Ingest Pipeline

**Status:** Approved design.  
**Companions:** `00-ARCHITECTURE.md` §3, `01-DATA-MODEL.md`, `03-SECURITY.md`.  
**Reusable code:** `Paint Appearance/Component/Database/src/wavescan_loader/` (reader, cleaner, dedup, mapping_engine, loader). Logic moves; Tkinter UI does not.

---

## 1. End-to-end flow

```
Engineer uploads .xlsx from one plant's page
  (multipart: files[] + expected_plant, both required)
        │
        ▼
Door checks (size, magic bytes, zip ratio, extension not trusted)
        │ fail → HTTP 400, nothing stored
        ▼
Plant scope gate (T17)
  expected_plant not in ref_plant          → 400, nothing stored
  any nonblank Plant cell != expected_plant → 400, WHOLE request, nothing stored
  expected_plant not is_active             → 422, nothing stored
        │ pass (blank Plant cells will be filled from expected_plant)
        ▼
SHA-256 of bytes -> lookup load_batch by file_hash
        │
        |- live hash (in review / committed / running / failed / rejected),
        |  another plant's hash, or Engineer vs a SUPERSEDED sheet
        |     -> 409 "already ingested", name the prior batch
        |- every prior sheet ABANDONED and/or SUPERSEDED (role + plant match)
        |     -> reopen/restore those load_ids (T25); no new batch; no store.put
        `- no prior row
              -> object store (key = hash), then:
Open one load_batch per sheet, plant_code = expected_plant
        │
        ▼
Enqueue job (Postgres SKIP LOCKED)
        │
        ▼
Worker:
  1. Header fingerprint
  2. If unknown → batch REJECTED_TEMPLATE, proposed_mapping(COLUMN), stop
  3. stg_raw verbatim (own transaction)
  4. Clean via injected alias maps
  5. Dedup ≥80%
  6. Per-row disposition: LOAD | DUPLICATE | REJECT | QUARANTINE
  7. Balance check (hard gate)
  8. Batch → PENDING_REVIEW
        │
        ▼
Review UI (persisted proposal, not a dry-run reprint)
  • clean files / sheets pre-ticked
  • blocked items unticked with reason
  • Engineer commits LOAD rows → COMMITTED + audit
  • semantic change (new alias, zone map, column map) → Admin only
        │
        ▼
Replay from stored bytes after Admin approval (no re-upload)
```

Dashboards read PostgreSQL only. Excel is never parsed at request time.

---

## 2. Door checks (hostile file)

Treat every upload as hostile (`03-SECURITY.md`).

| Check | Rule |
|---|---|
| Size | Default 25 MB per file, configurable |
| Count | Default 40 files per request |
| Magic | Sniff ZIP/`PK` for `.xlsx`; reject if extension lies |
| Zip bomb | Max compression ratio and uncompressed size |
| Type | `.xlsx` / `.xlsm` only. `.xls` out of v1 unless a real file requires it |
| Formula | `data_only=True` — cell **values**, never evaluate |

Failure = refuse the request. Do not create `load_batch`.

### 2.1 Plant scope (T17)

`POST /api/v1/uploads` takes a **required** multipart field `expected_plant`
beside the repeatable `files`. It is the plant page the upload was made from,
checked by the server against `ref_plant.plant_code`; the client cannot
override it afterwards.

| Workbook evidence | Answer |
|---|---|
| Every plant cell blank | Pass. Blanks are filled from `expected_plant`; the count is disclosed. |
| Plant column absent | Pass the plant gate -- there is nothing to disagree with. Whether the sheet then parses is a template decision: **T18** allows it only when the selected profile sets `fill_missing_plant` (section 4.1). |
| Every nonblank plant cell resolves to `expected_plant` | Pass. Blanks still filled and counted. |
| Nonblank plant cell is a documented aggregate sentinel (`[All]`, `(All)`, `[All Values]`) | Pass the plant gate. That cell is a report roll-up (T26 S16), not a plant name. Parse still stages it as `AGGREGATE_ROW`; it never reaches `wavescan`. A real other plant in the same column still refuses. |
| Nonblank cell **starts with** `expected_plant` (`AAT U704` on AAT) | Pass (T39, ADR 0013). The extra words are not a second plant; the row is the page plant and the projection marks it normalised. |
| Any other nonblank cell (another plant, an unknown string such as `U704`, or two sheets that disagree) | **Stored, not refused** (T39, ADR 0013 decision 3). Batches open on `expected_plant`; those rows are held as `PLANT_MISMATCH` and the worksheet asks the Engineer. "This plant" re-reads them as the page plant (`worksheet_decision` `PLANT_CONFIRM`); "another plant" cancels the upload through `purge_workbook` while nothing has loaded. Nothing is relabelled without that answer. The 400 `PLANT_SCOPE_CONFLICT` below is retired. |
| `expected_plant` not in `ref_plant` | **400 `EXPECTED_PLANT_UNKNOWN`** |
| `expected_plant` known but `is_active = false` | **422 `PLANT_NOT_ONBOARDED`** (D5) |
| No `expected_plant` at all | **422** validation, naming the field |

Two properties make this a door check rather than a parse result:

* It runs **before** `RawStore.put` and before any `create_batch`, so a
  refusal leaves no stored object and no batch -- not a batch that was rolled
  back, and not an object written under a content hash that then has no owner.
* **T39 amendment (ADR 0013):** a disagreeing Plant cell is no longer a
  door refusal. The file gets a card and the disagreeing rows wait for the
  Engineer's answer; the other rows and files load normally. The refusals
  that remain at the door are the claim itself (`EXPECTED_PLANT_UNKNOWN`,
  `PLANT_NOT_ONBOARDED`) and the door checks.

**Blank plant cells inherit `expected_plant`.** That is a fill, not a
relabel: only a *blank* cell inherits, a nonblank cell is never overwritten,
and the number of filled cells (with the first filled row) is written to the
`batch.upload` `audit_event` in the same transaction as the batch. `stg_raw`
still holds what the file said. A fill nobody can see afterwards would be
indistinguishable from a silent wrong plant label.

**`load_batch.plant_code` is `expected_plant`, set at create.** It is not
derived from the rows afterwards and is never NULL "because the rows
disagreed" -- rows that disagree are a door failure. If a cleaned row ever
resolves to another plant anyway, the batch goes `FAILED` with its staging
kept; the row is not relabelled and nothing reaches `wavescan`. Replay
(section 8) re-uses the batch's stored `plant_code` as its expected plant,
so there is no second claim and no second parser.

---

## 3. Identity and supersede

- **Bytes:** `SHA-256` of the workbook. Database key is `UNIQUE (file_hash, source_sheet)` because a batch is one sheet and a measurement's identity is `(load_id, source_row)` (T04, revision `0003`). Same bytes + a **live** prior batch = HTTP 409 naming every prior `load_id`; the constraint is the real guard. Same bytes after **abandon** or **retire** reopen that `load_id` (T25 / F22): they do not insert a second copy.
- **Name:** logical file = `(plant_code, source_file)` for uploads. New hash, known name, same plant → **Admin** supersedes the old `COMMITTED` batch. Engineer commit does **not** auto-supersede: that would let an Engineer retire an Admin-owned batch as a side effect (T04, reserved `POST /api/v1/batches/{id}/supersede`).
- **Row:** `(load_id, source_row)` unique on `wavescan`. Filename is not part of row identity.

Reload guard is a **database constraint**, not only an application `SELECT`. T01 added `UNIQUE (file_hash)`; T04 widened it to `(file_hash, source_sheet)` so a real multi-sheet workbook can be ingested.

---

## 4. Template fingerprint and drift

`reader.py` already maps columns **by header name**, not position (`HEADER_ALIASES` at `reader.py:24-46`). That dict becomes **seed data** for `ref_column_alias` (approved rows).

On every sheet:

1. Normalise header cells (lower, trim, `_` → space) — same as `_normalise_header`.
2. Hash the ordered recognised + unrecognised header list → `template_fingerprint`.
3. Store `raw_headers` JSONB on the batch.

### 4.0 Two hashes, one key (T26)

T18 selected a profile by that ordered fingerprint. Real previous-month
workbooks show the gate refusing sheets whose only change is that somebody
moved a column: FTM August and SAP July carry the same twenty-one logical
fields in a different order, and FVL September reorders the measures. **T26
splits the hash in two and moves the key onto the one a reorder cannot
change.**

| | Computed over | Used for |
|---|---|---|
| **`semantic_signature`** | `domain` + the **sorted set** of recognised logical fields | Profile selection, with `domain` and `expected_plant` |
| **`template_fingerprint`** | the **ordered** recognised fields (with `?` gaps) plus sorted unrecognised extras -- T18's algorithm, byte-identical | Provenance: the record that the columns moved |

Both are stored on the batch and on the projection. Design M5 is amended to
`(domain, expected_plant, semantic_signature)`; M4, M6 and M7 are unchanged,
and the filename is still never a key.

**Sheet routing comes first, and it is by headers, never by the tab's name**
(spec S10). A workbook that calls its data sheet `Sheet1` and its
instructions `CF Data` would otherwise be read backwards:

| Sheet class | What it means | What happens |
|---|---|---|
| `WAVESCAN` | carries this domain's measures and says what they belong to | continue below |
| `OUT_OF_SCOPE_SHEET` | its header row recognises **no** field of this domain: a Methods or instructions sheet, or a grid in a vocabulary this domain shares nothing with (Color Data). Column count is not a reason -- a two-column sheet carrying `CF` is `UNKNOWN_DATA_SHEET` | bytes and header row preserved as evidence; **no** `COLUMN` proposal, because it is not a broken WaveScan template and nobody should be asked to map it; commit blocked |
| `UNKNOWN_DATA_SHEET` | speaks *some* WaveScan but not enough to be one, however few columns it has | blocked for classification, with a proposal |

Then, in this order:

| Condition | Action |
|---|---|
| Two columns mean the same logical field | `DUPLICATE_LOGICAL_FIELD`; **do not parse data rows**. Before T26 the later column was dropped in silence, which is the exact shape a swapped measure would have (spec S8) |
| An **active template profile** exists for `(domain, expected_plant, semantic_signature)` | Parse. A reorder of an approved contract parses automatically: information, not a new profile |
| No active profile for that triple, and the tab is WaveScan with required columns mapped (T42) | Parse on the profile-free contract: date, plant (column or the upload page), model, colour, checkzone, CF. Missing DOI / Serial / Paintline / DU / Wa–We / B is a worksheet **notice**, values NULL, **not** a new template. `profile_id` stays NULL. Extra unknown headers still block commit until Ignore. Identity is never guessed from the tab name or filename |
| No active profile, and the tab is not readable that way | `REJECTED_TEMPLATE`; `COLUMN` proposal (`PROFILE_UNKNOWN`, or which required column is missing); **do not parse data rows** |
| Required field missing and neither a profile nor the page plant supplies it | `REJECTED_TEMPLATE`; show header diff; do not parse data rows. T39/T42: the required columns are date, plant, model, checkzone, colour, CF -- **Serial No and DOI are not among them** (ADR 0013) |
| Profile matches **or** profile-free parse, extra headers nobody has decided about | Parse the known fields, preserve the extras, **block commit** with `UNREVIEWED_HEADER` until a header is mapped, an Engineer ignores it (T39), or a published column policy marks it ignored with a reason. Nothing is ever auto-ignored (spec S9) |
| Unrecognised required-looking header | Propose `COLUMN` mapping with similarity score; **never auto-apply** |

Similarity is advisory. Engineer proposes; Admin approves; worker replays stored bytes.

### 4.0.1 Rows a pivot wrote about other rows (T26)

A row whose **identity** fields carry a report sentinel -- `[All]`, `(All)`,
`[All values]` -- is `AGGREGATE_ROW`: staged, projected, counted and
disclosed, and never a fact (spec S16). FTM May carries 1064 of them in 1320
rows and FVL September 133 in 165; the same numbers appear at progressively
less specific filter levels, so loading one invents a vehicle whose
measurements average other vehicles'.

Only **bracketed** forms are sentinels, deliberately. A bare `All` is what
the reviewed workbooks do not write, and treating it as a roll-up would let a
real colour, paintline or model spelled that way vanish from the facts. A
sentinel in a *measure* column is still a bad number and still a reject.

A roll-up sits **outside** the balance equation of section 6, exactly as an
entirely blank row already does: `rows_in_file` counts the file's data rows,
and a pivot's summary of them is not one. A sheet whose only rows are
roll-ups has no vehicle in it and is refused with `AGGREGATE_ONLY_SHEET`.

### 4.0.1a FilmThickness sheets (T46)

Same door, same bytes, same review and commit (spec S5). Each sheet is read first as WaveScan on row 1; only a sheet that is **not** WaveScan is searched (first 20 rows) for a FilmBuild header -- a location plus at least two paint layers in the FILMTHICKNESS vocabulary. A real CF sheet stays WaveScan. The PELT preamble above the header supplies `Date`, `Job Number`, `Vin` and the layer block; the column the `Layer 2:` line names is Base. `.ods` (SAP) is read from the stored bytes like `.xlsx`. Layer diagrams and linked-workbook stubs are `OUT_OF_SCOPE_SHEET`.

The model comes from the FTM filename token (`{COLOR}_{DBL|RAP|SGL|RB}_{job}`) or the plant's own spelling in the file / tab name (`P703`, `DBL` -> Ranger), never from PELT Comments. Points map by name only. Extra points, unmapped names and unnamed models are `QUARANTINE`; balance counts source rows, and a `LOAD` row becomes one `filmthickness` fact per numeric layer. `reset_batch_staging` refuses a batch with film facts as it does with `wavescan` rows.

### 4.0.2 Publishing a contract (T26)

`POST /api/v1/plants/{plant_code}/template-profiles/publish` (**Admin**) is
the only application path that can make a **named template profile**
commit-capable (`fixture_verified`). T42 profile-free WaveScan tabs have no
profile to prove; they commit after extras and acknowledgements, not via
publish. It takes the
SHA-256 of a workbook **already stored for that plant** -- not an upload -- a
named plant or quality owner, notes that name the proof, and optionally
headers to mark ignored with a reason each. The write happens inside a
`SECURITY DEFINER` function that appends a version, deactivates the previous
active one for the same contract, writes the column policy, and writes
`audit_event` in the same transaction.

It then **replays** the batches of that plant and contract that it unblocks,
from their stored bytes, through the same service. Replay ends where it
always does, at `PENDING_REVIEW` or `REJECTED_TEMPLATE`. **Publishing commits
nothing and supersedes nothing**: turning rows into measurements stays an
Engineer pressing commit on a sheet a person has read.

Ordinary Admin mapping approve still **cannot** write a profile, a column
policy or `fixture_verified` (design M6). That is a grant, not a code review.

### 4.1 Template profiles (T18)

A **template profile** (`ref_template_profile`) is a plant layout, keyed by
`(plant_code, template_fingerprint)` and versioned. At most one version is
active per layout, enforced by a unique partial index rather than by an
`ORDER BY` in the service.

Profiles are **data**. They carry no SQL and no Python, they do not guess a
model, colour, zone or serial, they do not auto-apply similarity, and they
cannot disable balance, dedup or referential checks. The existing `Cleaner`,
`Deduplicator` and `IngestService` remain the only downstream path: a profile
decides *whether a layout is known*, never *what a value means*.

| Column | Meaning |
|---|---|
| `fixture_verified` | A fixture proved this layout commits correctly. Written by **seed, migration or the owner only** -- `app_rw` has no INSERT or UPDATE on this table, so no route, including Admin mapping approval, can promote a layout (design M6). |
| `fixture_file_hash` | SHA-256 of the workbook that proved it, where a stored workbook did. Null when the proof is a test, and `notes` then names it. |
| `fill_missing_plant` | This layout is known to omit the Plant column. `plant` is then treated as present for parseability and filled from `expected_plant`, exactly as a blank cell already is (section 2.1). This is the only field a profile may supply. |

Consequences, in the order they are checked:

1. **No active profile, WaveScan required columns map (T42)** -> parse on
   those columns. `committable` is not blocked by `UNKNOWN_TEMPLATE` or
   `UNVERIFIED_PROFILE`. The commit audit records `profile_free: true`.
2. **No active profile, and the tab cannot be read that way** ->
   `REJECTED_TEMPLATE`, a `COLUMN` proposal (`PROFILE_UNKNOWN` or the missing
   required column), and no data row is read.
3. **Profile present, not fixture-verified** -> the sheet parses and is fully
   reviewable, and `committable` is **false** with `UNVERIFIED_PROFILE` among
   `commit_blockers`. This is how SAP is visible and blocked with a reason
   rather than silently unknown. An exact profile is still preferred when it
   exists; T42 does not fall through to profile-free in that case.
4. **Profile present and verified** -> as before.

A missing Plant **column** is filled from the upload page on the profile-free
path (T42), and by `fill_missing_plant` when an exact profile says so (T18).

Replay re-identifies the layout from the stored bytes, because an approved
alias can change which headers are recognised and so the fingerprint itself.
`load_batch.template_fingerprint` stays frozen at insert (it is provenance);
the fingerprint that actually parsed a batch is on its projection rows.

### 4.2 The review projection (T18)

The worker persists `stg_review_row`: **one row per source row**, whatever
its disposition.

| Field | Purpose |
|---|---|
| `canonical` | What commit would insert -- the same fields `wavescan` gets |
| `raw` | What the file said, values and unrecognised extras, for side by side |
| `disposition` | `LOAD` / `DUPLICATE` / `REJECT` / `QUARANTINE` / `AGGREGATE_ROW` (T26, section 4.0.1) |
| `reason` / `detail` | The existing reject and quarantine vocabulary |
| `normalized_fields` | Which fields were filled or mapped (today: a plant filled from `expected_plant`) |
| `profile_id`, `template_fingerprint` | Which layout translation ran |
| `review_revision` | Hash of this batch's whole projection |

It is **staging evidence, not `wavescan`**: `app_rw` holds SELECT and INSERT
and nothing else. There is no UPDATE by design -- changing a proposed value
means an approved mapping and a replay, or new bytes. Replay clears it
through `reset_batch_staging` (section 8), which now covers four tables and
still refuses unless the batch has **zero** `wavescan` rows.

`commit_batch` re-derives the plan from the stored bytes and re-computes the
revision. It refuses, writing nothing, when the counts disagree (as before),
when the revision disagrees (same rows, different meaning -- an alias or a
zone map moved in between), when the profile is missing or unverified, or
when vehicle identity is missing. Every refusal names a stable token, and
`GET /batches/{id}` shows the same tokens in `commit_blockers` so a reviewer
does not discover them by being refused.

**Held labels (finish-batch spec).** `GET /api/v1/batches/{load_id}` includes
`held_labels`: distinct REJECT / QUARANTINE spellings grouped by
`(reason, column, raw value)` with counts, plus existing catalogue
candidates for that field. Present on `PENDING_REVIEW` and on a committed
remainder (SAP August 1054's `UNKNOWN_COLOR` rows stay visible; they are
not facts). Colour cells first try `ref_color_alias`, then a **unique**
identity fold (gray/grey, paint-code prefixes, collapsed double letters)
onto one existing `ref_color.color_name`. Zero or two catalogue hits stay
held so the uploader cross-checks; the unique candidate is listed first.
Teaching a spelling is Engineer `POST /mappings/proposals`
(`ALIAS_COLOR` / rostered `ALIAS_MODEL`): the alias is applied in that
request (spec A2). COLUMN and ZONE still need Admin `/approve`. Replay of
a batch that has `wavescan` rows is still refused (section 8, ADR 0005);
the alias still lands so the next file can LOAD. Identical live bytes stay
409 (section 3). Leftover programs (`J73` / CX743 / V363 / U704) are not
Ranger zone aliases (propose onto P703 is 422). When that leftover has its
own `ref_model` catalogue, `held_labels` offers `ALIAS_MODEL` onto that
catalogue only. Each group now carries `display_group` and
`operator_message` for the reviewer. An empty identity sentinel is not
teachable. Column order is the T26 semantic signature (header names, not
column letters). The card X abandons or supersedes the sheet; it is not a
DELETE.

**T26 adds six blockers**, each naming something a *person* decides:
`UNREVIEWED_HEADER` (a column with no agreed meaning),
`DUPLICATE_LOGICAL_FIELD` (two columns claiming one field),
`PAINTLINE_MISSING` (a LOAD row that does not say which line built the
vehicle -- a gate, never a licence to mint one; a documented Paintline
sentinel such as `(None)` is not this gate: the leaf may commit with
paintline NULL; a published layout that **has no Paintline column** -- FVL
historical 18-col, spec F3 -- is also not this gate: paintline stays NULL
and is not invented. A G2-shaped sheet that *has* the column with blank
cells still blocks), `OUT_OF_SCOPE_SHEET` and
`UNKNOWN_DATA_SHEET` (section 4.0), and `AGGREGATE_ONLY_SHEET` (a sheet with
no leaf row in it). `GET /batches/{id}` shows all of them from stored
evidence, still without opening a workbook.

**Vehicle identity -- amended by T39 (ADR 0013 decisions 2 and 8).**
`VEHICLE_IDENTITY_MISSING` and `PAINTLINE_MISSING` are no longer raised. A
blank, absent or `(None)` Serial No or Paintline loads NULL at every plant,
and a colour tab with no serial is one vehicle (complete when date, model
and colour are present). No serial or booth is generated and
`(file, sheet, source_row)` is never a vehicle identity. A **nonblank**
unknown paintline still holds. A point loads with date, model, colour,
checkzone and CF; LW/SW are required unless an Engineer approves that point
(`worksheet_decision` `HOLE_APPROVAL`); DOI, DU, Wa-We and B are optional.

**Worksheet (T39).** `GET /plants/{plant}/workbooks/{hash}/worksheet` is the
Engineer's confirm page. `POST .../ignore-columns`, `.../plant-answer` and
`.../hole-approval` record a `worksheet_decision` and replay the tabs from
the stored bytes; `.../load-ready` ("Yes, load these rows") commits every
ready tab, recording the warning acknowledgements in the Engineer's name;
`.../load-remaining` INSERTs, for a COMMITTED tab, only the rows that became
loadable since -- never an UPDATE of a stored value, never a remainder file.

---

## 5. Validation layers

| Layer | What | On failure |
|---|---|---|
| L1 structural | Required fields, types, plausible ranges (existing CHECKs) | `reject_log` (`BAD_DATE`, `BAD_NUMBER`, `OUT_OF_RANGE`, `MISSING_*`) |
| L2 referential | Plant / model / zone / colour / paintline via alias tables | `UNKNOWN_*` reject or quarantine |
| L3 semantic | Zone valid for model (`ref_model_zone`); completeness vs `expected_zone_count` | `ZONE_NOT_VALID_FOR_MODEL`; `v_car_completeness` |
| L4 statistical | Value vs that zone's historical distribution | **Flag, do not block** (genuine process excursion looks like an error) |
| L5 cross-file | ≥80% measurement match (`dedup.py`) | `is_duplicate` / `DUPLICATE_ROW`; most complete copy wins (existing rule) |

Plant is the exception to L1/L2 since T17: a blank plant cell is filled from
the upload's `expected_plant` rather than rejected as
`MISSING_REQUIRED_FIELD`, and a plant cell naming another plant never reaches
these layers at all -- it was refused at the door (section 2.1).

L1–L3 and L5 exist in the demo loader. L4 is new; v1 may implement it as a post-commit view or a non-blocking `reject_reason`/`notes` flag. It must not auto-reject.

**Tolerance group:** still **derived** (HOOD/ROOF → Horizontal, else Vertical). The file's own column is ignored — it contradicted itself on 36 of 2479 rows (`README.md`). Do not reverse that.

---

## 6. Balance check

Physical CHECK, kept and retargeted at `COMMITTED`:

```
rows_in_file = rows_loaded + rows_duplicate + rows_rejected + rows_quarantine
```

If the worker cannot satisfy this, status is `FAILED`, not a partial `COMMITTED`. Staging remains for investigation (demo already commits `stg_raw` separately — keep that).

---

## 7. Review is a persisted proposal

The demo CLI dry-run prints to a terminal. That does not survive reload, cannot split uploader vs reviewer, and is not auditable.

`PENDING_REVIEW` means:

- Dispositions are stored (`reject_log`, `unidentified_model`, duplicate flags, counts on `load_batch`).
- Review UI lists batches; clean sheets can be committed in one click (the 40-files-40-clicks lesson).
- Partial approve is **per sheet / per file**, not per measurement row.

### Approval split

| Action | Role |
|---|---|
| Commit a clean batch (LOAD rows → `wavescan`) | **Engineer** (including their own upload) |
| Approve column / zone / alias / model mapping | **Admin** |
| Supersede a committed batch | **Admin** |
| Insert a correction row | **Engineer** propose / **Admin** if policy later tightens; v1: Engineer with mandatory reason, audited |

An alias silently reinterprets **future** files. That is why semantic changes are Admin-only.

---

## 8. Replay

Resolving quarantine or adding an alias **re-runs stored bytes** from the object store. No re-upload. Same pipeline code path as first ingest — not a second "resolution parser". Implemented T08: Admin `POST /api/v1/mappings/proposals/{id}/approve` writes the alias and calls `IngestService.replay_batch`, which sets `RUNNING` and re-queues `ingest_job`; the existing worker then calls `process_batch`.

| Allowed batch status | Not allowed (409, nothing applied) |
|---|---|
| `REJECTED_TEMPLATE`, `PENDING_REVIEW` | `COMMITTED`, `SUPERSEDED`, `ABANDONED` (T21), `RUNNING`, `FAILED` |

Preconditions, both required: `SELECT count(*) FROM wavescan WHERE load_id = :id` is **0**, and staging is cleared only through `reset_batch_staging(load_id)` (`SECURITY DEFINER`, revision `0004`). `app_rw` has no table DELETE. Replay **never commits**; it ends at `PENDING_REVIEW` or `REJECTED_TEMPLATE` again. Engineer commit stays T07.

---

## 8.1 Data Manager reads (T19)

The plant Data Manager reads one plant's evidence. **No workbook is opened on a GET.** Every read is served from `load_batch`, `stg_review_row`, `wavescan`, `audit_event`, `ref_template_profile` and `review_acknowledgement`. Only `commit_batch` re-derives from stored bytes, and it is a mutation.

| Read | Source |
|---|---|
| Plant workbooks | `load_batch` grouped by `file_hash`, one card per workbook, sheets as children |
| Workbook detail | the same, plus its profiles, its acknowledgements, and an advisory replacement hint |
| Rows | `stg_review_row`, joined to `wavescan` on `(load_id, source_row)` for committed sheets |
| Issues | the same rows, summarised into blockers / warnings / information |
| History | `audit_event` for this workbook's batches, its proposals and its measurements |

**One workbook is one `file_hash` at one plant.** The filename is a label. A workbook filed under another plant is a 404 through this plant's URL, never a redirect.

**Dates are measured dates.** A workbook's range is the union of the measured dates on its review projection and on its committed `wavescan` rows. A workbook still parsing has none, and that is reported as null -- a week is never inferred from the upload time or the filename. Week and month grouping is the client's, using this rule: Week 1 = days 1-7, Week 2 = 8-14, Week 3 = 15-21, Week 4 = 22-28, Week 5 = 29 to the end of that calendar month; a workbook is placed **once**, by its earliest measured date, and a range that crosses a boundary shows as a range rather than a second card.

**The operational summary is a workflow label, not a grade.** Highest rule first, where "live" means a sheet whose status is neither `SUPERSEDED` nor `ABANDONED` (T21): no live sheets -> `SUPERSEDED` if any sheet is `SUPERSEDED`, otherwise `ABANDONED`; any live `RUNNING` -> `PROCESSING`; some live committed and some not -> `PARTIALLY_COMMITTED`; all live committed -> `ACTIVE`; otherwise -> `REVIEW_REQUIRED`. Every sheet still carries its own `load_batch.status`. There is no pass rate here (D1 is open).

**A superseded batch's rows stay readable here.** `GET /measurements` answers what is current and stays on `v_wavescan_active`, so a retired batch contributes nothing to it; the workbook rows read answers what this *file* contains, which is what somebody opens after a supersede. The additive `load_id` filter on `GET /measurements` narrows that same active view and never widens it.

### 8.2 Acknowledged warnings (T19)

Three warning categories mean rows the plant sent are **not** becoming measurements, and each blocks the commit until a named person has accepted it:

| Category | Raised when | Note |
|---|---|---|
| `REJECTED_ROWS` | `rows_rejected > 0` | **required** |
| `QUARANTINED_MODELS` | `rows_quarantine > 0` | **required** |
| `DUPLICATE_ROWS` | `rows_duplicate > 0` | optional |
| `POSSIBLE_REPLACEMENT` | another live committed workbook of this plant overlaps these dates | optional; **blocks nothing** |

An unacknowledged required category is `WARNINGS_UNACKNOWLEDGED` in `commit_blockers`, and `commit_batch` refuses with the same token. A clean sheet has no required category and commits without any acknowledgement, exactly as before.

**An acknowledgement binds to the batch's `review_revision`**, so it is a statement about *those rows*. A replay re-derives the projection, the revision moves, and the earlier acknowledgement stops satisfying the gate -- while staying in `review_acknowledgement` as the record that somebody read the earlier proposal. Nothing deletes one: `app_rw` holds no DELETE, and `reset_batch_staging` does not cover that table.

`POSSIBLE_REPLACEMENT` never retires anything. Superseding a workbook stays an explicit Admin action carrying a reason (section 7).

### 8.3 Upload review (T21)

**Inbox filters.** `GET /plants/{plant_code}/workbooks` takes `inbox` = `all` (default) / `current_month` / `needs_attention` and `uploaded_month` = `YYYY-MM`, the **UTC calendar month of `uploaded_at`** (the earliest `started_at` of the workbook's sheets), defaulting to the current UTC month. `all` is the T19 list unchanged. `current_month` keeps workbooks uploaded in that month (no measured dates first, then `uploaded_at` DESC, `file_hash`). `needs_attention` keeps workbooks uploaded in any **other** month whose summary is `PROCESSING`, `REVIEW_REQUIRED` or `PARTIALLY_COMMITTED` (`uploaded_at` ASC, `file_hash`); `ACTIVE`, `SUPERSEDED` and `ABANDONED` are finished. The server filters and pages over the whole plant, so a client never pages the plant to pin old work. **Week buckets stay client-side:** the API emits `uploaded_at` and the measured-date range (still fields on the card, with `measured_dates_span_months`), and the client applies the day bands in section 8.1 -- to `uploaded_at` for Upload Data.

**Vehicle sets.** `GET .../workbooks/{file_hash}/vehicles?load_id=` groups one sheet's projection rows (or its facts, where it has no projection) by `measured_date + model + color + serial_no` from `canonical`, in `domain/workbooks.py`. `vehicle_id` is SHA-256 of `{load_id}|{measured_date}|{model}|{color}|{serial_no}`, missing parts empty. A missing part makes the group `identity_complete: false`; no serial is generated and `source_row` is never the key. `expected_point_count` is `ref_model.expected_zone_count`. `.../vehicles/{vehicle_id}/points` returns the rows with `raw`, `proposed` and `current_overrides`. No workbook is opened.

**Overrides re-enter the one parser.** `POST .../workbooks/{file_hash}/overrides` (Admin, one vehicle set, current `review_revision` or 409) inserts `review_override` rows and, **in the same transaction**, calls `IngestService.revalidate_review`: `_plan` from the stored bytes with the current overrides applied to `LOAD` rows after dedup, `reset_batch_staging`, and the same staging/projection inserts `process_batch` uses. The batch stays `PENDING_REVIEW` (no RUNNING bounce, no job), the revision moves, and acknowledgements of the old revision stop satisfying `WARNINGS_UNACKNOWLEDGED`. A mapping replay and `commit_batch` apply the same overrides through `_plan`, so commit writes the overridden measures and a replay cannot drop them. If a re-derivation would leave an override unapplied (its row no longer `LOAD`) the save is refused and nothing is written.

**Abandon vs supersede.** Before commit, `POST /batches/{load_id}/abandon` `{ reason }` (Admin) moves a `PENDING_REVIEW`, `REJECTED_TEMPLATE` or `FAILED` batch with zero `wavescan` rows to `ABANDONED`, audited as `batch.abandon`; nothing is deleted, and replay and commit refuse it. After commit, the existing `POST /batches/{load_id}/supersede` `{ reason }` retires the batch. A card X is one of these two per sheet, never a DELETE. T25: identical-file ingest or `POST /batches/{load_id}/restore` `{ reason }` reopens `ABANDONED` (`batch.reopen`) or restores `SUPERSEDED` to `COMMITTED` (`batch.restore`); unique hash stays.

### 8.4 Measurement History reads (T23)

Four GETs under `/api/v1/plants/{plant_code}/history/`, for **any
authenticated role**: `facets`, `summaries`, `vehicles`, and
`vehicles/{vehicle_id}/points`. They are not under `/workbooks` -- that is
the Admin Data Manager, which shows proposals, pending sheets and retired
ones. History shows **active facts**.

**Active predicate only.** Every statement selects from `v_wavescan_active`,
the same view `GET /measurements` reads, so a superseded batch and an
abandoned review contribute nothing and there is no second definition of
"current" (`01-DATA-MODEL.md` sections 5 and 10). `load_batch` is joined only
to attach `source_file` provenance; `v_vehicle_completeness` is not used,
because it groups without `load_id` and would merge two sheets that measured
the same serial on the same day.

**Month is the calendar month of `measured_date`** (`YYYY-MM`), never of
`uploaded_at`: a June workbook uploaded in September is June data.
`default_month` is the latest month with an active row for that plant, or
null when it has none. A known un-onboarded plant (FVL, D5) answers 200 with
no months.

**Facets cascade.** Months -> models in the selected month -> colours in that
month and model. Without a month the model and colour lists are empty, and a
`color` without a `month` is 422: there is nothing to cascade from, and the
client must not download every active row to fold its own lists.

**Week is a field, not a resource.** History summaries carry `week` 1-5,
computed in `domain/history.py` from the day of `measured_date` with the same
bands as section 8.1. Weeks are emitted descending and empty weeks are
omitted. There is no `GET .../history/weeks`, and T21's Upload Data weeks
stay the client's, computed from UTC `uploaded_at`.

**A History vehicle is a T21 vehicle.** Same key and same hash
(`domain/workbooks.py` `identity_of` / `vehicle_id`), `load_id` included, on
one committed sheet. Two serials are two vehicles; the same serial measured
again on another sheet is another vehicle; a blank serial is one
identity-incomplete group and no serial is generated. `expected_point_count`
is `ref_model.expected_zone_count`, injected, never a literal.

**The numbers agree with `GET /measurements`.** A card's `point_count` is
active measurement rows, so summing a month's (or a week's) cards equals
`page.total` on `GET /measurements` for the same plant, dates, model and
colour. `vehicle_count` counts vehicle sets. There is no pass rate, Ford band
or grade anywhere in these payloads; D1 is open. Editing a point stays the
T09 correction POST against its `measurement_id`.

---

## 9. Concurrency

- Job claim: `SELECT … FOR UPDATE SKIP LOCKED`.
- Unique `file_hash` serialises identical uploads.
- Promote (insert facts) is one transaction including `audit_event`.

No Redis in v1.

---

## 10. CLI

Keep `wavescan_loader.cli` as an ops backfill tool. It must call the **same** `services/ingest.py` as HTTP upload. Two parsers = drift.

Dry-by-default (`--commit`) stays for CLI. The web path's equivalent is `PENDING_REVIEW` until the Engineer clicks commit.

---

## 11. What is explicitly not this pipeline

- SharePoint Graph pull (ADR 0003).
- Filesystem watchers (half-written files, network drives).
- `--replace` / DELETE batch (ADR 0005).
- In-place `UPDATE wavescan` (ADR 0005).
- Auto-applying fuzzy header or zone guesses.

---

## 12. Realtime dashboards

Committed data is visible on the next API read. No websockets in v1. "Realtime" means **single database + refresh**, not a push channel. SSE can be added later without changing the schema.
