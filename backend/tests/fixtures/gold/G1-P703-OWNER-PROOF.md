# G1 -- P703 owner proof (SAP + FVL)

**Status:** SAP and FVL sections signed. G2 recorded in T32-FVL-ACTIVATION.md; D5 close is that report.  
**Named owner:** Efe Ularika (Quality Lead, paint quality) for **both** SAP and FVL. A person, not Admin, not an Operator uploader.  
**Signed:** 2026-09-21.

This file is the external G1 gate (spec P3 / S15). Agents did not invent the name. Matrices live in G1-P703-DECISIONS.md. Routine Operator upload is not gated on this name (D-20).

---

## SAP

| Field | Value |
|---|---|
| `named_owner` | `Efe Ularika` |
| `proof_hash` | `46fcaf58bc3125937b6c0ed9be13efef3e13230ccc93324d19c978db83b5178d` |
| Proving workbook | `Internship/Data/SAP/CF/7 Jul-26 P703 & J73 CF INPUT.xlsx` (T28 SHA-256). July carries both `P703 DBL` and `P703 RAP`. August `77b2226ab07371fe8bb3f3e4f60425bdb4528a9a08531d6d028f6f4713399b74` has the same 32 checkpoint texts (T28); it is not a second map. |
| `proof_document` | T28 hash of the July SAP CF workbook; 32-row matrices in `docs/reports/G1-P703-DECISIONS.md`; tailgate by meaning against FTM template and the Ranger SC/CC checkpoint picture. |
| `method` | Owner-signed raw_label → `zone_code`. Not keyword grouping, not file sequence, not T28 `proposed_zone_code` (those were null). |

I sign the SAP matrices in `docs/reports/G1-P703-DECISIONS.md` for:

- `(SAP, P703 DBL RANGER)` — aliases `P703` and `P703 DBL`
- `(SAP, P703 DBL RAPTOR)` — alias `P703 RAP`

Same 32 raw labels on both models (T28). J73 in the same workbooks is not this set.

### Tailgate sentences (SAP)

FTM template #20 is `RBTAILGATE` (right bottom) and #21 is `RTTAILGATE` (right top). SAP writes right **top** then right **bot** at those numbers.

- `17LHS TG Top12` → `LTTAILGATE`
- `18LHS TG Bot13` → `LBTAILGATE`
- `19Tailgate Middle14` → `LCTAILGATE`
- `20RHS TG Top15` → `RTTAILGATE` (not FTM index 20)
- `21RHS TG Bot16` → `RBTAILGATE` (not FTM index 21)

The other 27 SAP labels follow FTM `zone_no` and meaning (hood, fender, door, box, roof). Full table: G1-P703-DECISIONS.md §SAP matrix.

---

## FVL

| Field | Value |
|---|---|
| `named_owner` | `Efe Ularika` |
| `proof_hash` | `c0f9a8dae0ec329da740af29b04f76ffcce980ff7059804724bffe302854cad0` |
| Proving workbook | `Internship/Data/FVL/CF/08 Aug data/CF_Aug.xlsx` (T28 SHA-256). Jan–Jul uses the same 32 labels (T28). September `e3ecc6a7e209f262eeb0906aae71edc31b6b27fbe0d3d13a611448ce9d0f6a34` is a different template (Serial/Paintline headers); it is **not** this proof and is not G2. |
| `proof_document` | T28 hash of August `CF_Aug.xlsx`; 32-row picture matrix in `docs/reports/G1-P703-DECISIONS.md` §FVL matrix; Ranger SC/CC checkpoint picture. |
| `method` | Owner-signed raw_label → `zone_code`. Picture identity, not file sequence. Not T28 `proposed_zone_code` (those were null). |

I sign the FVL matrix in `docs/reports/G1-P703-DECISIONS.md` for:

- `(FVL, P703 DBL RANGER)` — plant-scoped `P703` / `P703 DBL` already alias to Ranger (T26 / 0009). Do not add a global `P703` row.

CX743 / V363 in the same August file are not this set.

### Hood spelling risk (`1HOOD` / `01HOOD`)

The atomic 32-set is **August cell text**, including `1HOOD` → `RRHOOD`. September writes picture 1 as `01HOOD` (zero-padded). Operators type both. They are **one physical hood**, not two panels.

T29 forbids putting both raws in one 32-row proposal (that would be two `RRHOOD` codes). T31 stores `01HOOD` as a **second** `ref_plant_zone_map` row for the same `(FVL, P703 DBL RANGER, RRHOOD)`, same proof. The cleaner must not collapse `1hood` and `01hood` into one key. `2HOOD`–`5HOOD` are unpadded in both files.

### Picture sentences (FVL)

- `11ROOF` → `LCROOF` (picture 11)
- `14ROOF` → `RCROOF` (picture 14; not FTM zone_no 14)
- `28TGATE` → `RTTAILGATE` (picture height, not FTM-index guess)
- `29TGATE` → `RBTAILGATE`

Full table: G1-P703-DECISIONS.md §FVL matrix.

---

## What this does not do

- Does not flip FVL `is_active`.
- Does not owner-publish an FVL template profile (T32 / G2).
- Does not let SAP June commit (no serial).
- Does not let FVL Jan–Aug historical files commit (no Serial **and** Paintline as G2).
- Does not copy Excel into git.
- Does not require Operators to re-enter this name on monthly upload.
