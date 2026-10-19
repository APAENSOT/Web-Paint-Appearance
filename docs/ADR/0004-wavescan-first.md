# ADR 0004 — WaveScan (CF) is v1, not PELT

**Status:** Accepted  
**Date:** 2026-09-07  
**Supersedes:** PELT-first phasing in `Paint Appearance/docs/02-PHASE-PLAN.md`

## Context

The 2026-08-19 plan made PELT (film thickness) v1 because that is what the intern originally asked to rebuild, and because `PeltCore`/`PeltLogic` had extraction markers and a large (unexecuted) test suite.

What actually exists as a working, data-backed system is the WaveScan loader:

- 8 real WaveScan workbooks loaded (AAT, FTM, FVL files present; SAP files present)
- 2479 rows read → 2192 loaded / 255 duplicate / 31 unidentified model / 1 missing measurements
- 36 pytest cases, `sql/99_verify.sql` negative DB tests
- Physical CHECK/FK constraints on the fact table

PELT's JS tests have never been run. PELT v1 would start from an unverified oracle.

## Decision

**WaveScan (CF / paint appearance) is v1**, built cloud-ready. PELT and Color Data follow on the same platform (nav slots reserved, separate schemas later).

CF grading semantics are specified in `04-ANALYSIS.md`. Two decisions are **gated** and block grading implementation, not ingestion:

- D1 — which grouping the graded average is computed over
- D2 — colour-to-family reconciliation. **Amended by [ADR 0010](0010-plant-scoped-color-family.md):** family is plant-scoped (`ref_plant_color`), not one `ref_color.grading_family`. `Aluminum Metallic` vs `aluminium metallic` stays an identity alias.

Ingestion, review, and a measurement dashboard can ship before D1/D2. Graded KPIs cannot.

## Consequences

- Frontend plant/model routes already in `Component/Frontend` align with WaveScan first.
- Golden-master for CF is required because CF has **no** JS test suite (only `pelt-*` files exist).
- PELT extraction markers remain useful later; they do not drive v1.

## Alternatives rejected

- PELT first: slower path to a demo IT can see, weaker safety net.
- Both in v1: doubles scope before the security remediation and schema hardening land.
