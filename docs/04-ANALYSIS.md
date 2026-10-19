# Paint Appearance Platform — WaveScan / CF Analysis

**Status:** Approved design for *how* grading works. **D1** (grouping key) and **D2** (colour→family) are gated — see `DEFERRED.md`. Ungraded measurement views may ship before those gates.  
**Source of truth for rules:** `Paint Appearance/Component/CF and Pelt/Prototype.html` (and the copy under `Component/CF and Pelt/`). Line numbers below were verified 2026-09-07 on the Component copy; **grep identifiers**, do not treat lines as stable.

PELT markers exist (`PELT-CORE-START` / `PELT-LOGIC-START`). **CF has no equivalent markers.** CFCore is a UMD factory (~1782–2940); CFLogic begins ~2942 (`root.CFLogic = factory(root.CFCore)`).

There is **no `cf-*.test.js` suite**. Golden-master (T05) is mandatory before Python grading is trusted.

---

## 1. What is graded

**Only `cf`.** Dedupe collects `rec.cf` (~2722) and averages distinct duplicate values (~2729). Sub-parameters `lw, sw, doi, du, wa…we, b` travel as `params`, averaged in `meanParams`, **never** passed to `statusOf`.

Dashboard: eleven numbers displayed, **one** graded.

---

## 2. Status rule (`statusOf`, ~2754–2759)

```javascript
function statusOf(value, ford, minStd) {
  if (value === null || !isFinite(value)) return null;
  if (value < minStd - EPS) return 'FAIL';
  if (ford != null && value < ford - EPS) return 'WARNING';
  return 'PASS';
}
```

Comments (~2742–2751): Ford-standard **banded** rule (v3). Higher is better. **No OVER** (unlike PELT).

| Condition | Status |
|---|---|
| value &lt; min | FAIL |
| min ≤ value &lt; ford | WARNING |
| value ≥ ford | PASS |
| non-finite / no spec | null |

---

## 3. Default family targets (`DEFAULT_STANDARDS`, ~1798–1805)

| Family | fordH | fordV | minH | minV |
|---|---|---|---|---|
| Light Metallics | 57 | 44 | 50 | 37 |
| Medium Metallics | 60 | 47 | 53 | 40 |
| Dark Metallics | 62 | 49 | 55 | 42 |
| Light Solids | 62 | 49 | 55 | 42 |
| Medium Solids | 65 | 52 | 58 | 45 |
| Dark Solids | 67 | 54 | 60 | 47 |

`COLOR_FAMILY_ORDER` (~1807–1814) is display/chart order — persist as `ref_color_family.display_order`.

Comment at ~1815: map is from **"Color Family - IMG Plants document"**. The owner workbook (2026-09-22, SHA-256 in STANDARDS-D2-AUDIT.md) is that document; **do not copy the xlsx into git**. Seeded `cf_standard` rows stay version 1 with `source_document` NULL. New Admin publishes append FAMILY rows and may set `source_document` to that hash. Family is **plant-scoped** ([ADR 0010](ADR/0010-plant-scoped-color-family.md)).

---

## 4. Resolution chain (`targetsFor`, ~2773–2788)

1. If `standards.colors[color]` exists **and** `fordH != null` → use that row (per-colour override).
2. Else `standards.families[family]`.
3. Else `DEFAULT_STANDARDS[family]`.
4. Else null (cannot grade).

A colour taught for import without targets must **fall through** to the family, not blank grading. Port this exactly.

`stdPair` (~2792–2797): orientation `H` → `fordH`/`minH`; else `fordV`/`minV`.

**Defect — do not port twice:** an identical `stdPair` appears again ~2983–2986 in CFLogic. Comment above the first claims it is defined once. Consolidate in **one** Python function. Handoff `Doc/HANDOFF-2026-08-15.md` records duplicated resolution as a recurring production bug.

---

## 5. Orientation vs `tolerance_group`

Demo DB `wavescan.tolerance_group` is Horizontal / Vertical, derived from zone (HOOD/ROOF → H). That is the same axis as `stdPair`. Spec lines and grading must use this field (or an equivalent derived from canonical zone), **not** a second orientation implementation in the API.

---

## 6. Colour family vs `ref_color.color_group`

`ref_color.color_group` is hue: GREEN, SILVER, WHITE, BLUE, … (`01_reference.sql`). **That is not the six-family grading taxonomy.**

`COLOR_FAMILY` in the prototype keys **lower-case canonical names** (e.g. `'aluminium metallic'` ~1821). Demo DB has **`Aluminum Metallic`** (American spelling). Lower-casing does not equalise them. Same class of bug as FVL Magnetic Grey (alias, not a second range).

**D2** (plant-scoped, shipped): family lives on `ref_plant_color`, not `ref_color.grading_family` (that column stays NULL). Graded KPIs stay withheld until **D1**.

Do not invent families from `color_group`.

---

## 7. Grouping key (**D1**, deferred)

The prototype has zone-level and group-level status (`z.status` ~3350, `g.status` ~3379) and UI copy about Checkzone detail. **Authoritative grouping for the dashboard KPI is not locked.** Owner: deep-dive after DB connection.

Until D1:

- API may return **per-row `cf`** plus enough dimensions (plant, model, color, checkzone, tolerance_group, date, serial) for the UI to chart.
- API must **not** ship a single "pass rate" that assumes a grouping the owner has not approved.
- T06 dashboard slice: ungraded / raw CF distributions is acceptable; ribbon PASS/WARN/FAIL waits on D1+D2+T05.

---

## 8. Grades on read

Same as the 2026-08-19 PELT decision: compute in `domain/grading.py`. SQL contains no Ford/Min thresholds. Standards edits create new `cf_standard` rows; history re-grades.

Escape hatch: cache keyed by `(aggregation_key, standard_version)` only if measured p95 requires it — not in slice 1.

---

## 9. Golden master (T05)

1. Load CFCore + CFLogic from `Prototype.html` in Node (or extract to a throwaway script).
2. Run the eight WaveScan workbooks under `Paint Appearance/Component/Database/Excel Template/WaveScan/` (and any other agreed files).
3. Freeze JSON fixtures: inputs + `statusOf` outputs at the grain T05 documents (must state grain explicitly even if D1 is still open — e.g. per raw row using that row's cf, as a **regression oracle**, not as the product KPI).
4. Python `domain/grading.py` must match fixtures exactly (EPS as in prototype).

If the prototype and Python disagree, **the fixture from the executed prototype wins** until the owner signs a rule change.

---

## 10. Extraction notes for agents

- Do not retype thresholds from this markdown into Python as the long-term source. Seed `cf_standard` from `DEFAULT_STANDARDS` once, then the table is source of truth.
- Do not copy `COLOR_FAMILY` blindly over `ref_color` without D2.
- PELT `statusFor` / OVER / layers are **out of scope** for WaveScan v1.
