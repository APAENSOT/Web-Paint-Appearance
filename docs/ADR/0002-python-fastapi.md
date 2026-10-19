# ADR 0002 — Backend is Python 3.12 + FastAPI, not TypeScript/NestJS

**Status:** Accepted  
**Date:** 2026-09-07  
**Supersedes:** `Paint Appearance/docs/00-ARCHITECTURE.md` decisions D3 and D4 (Node/NestJS)

## Context

The 2026-08-19 architecture chose Node.js + NestJS so that PELT's existing JavaScript domain (`PeltCore`/`PeltLogic`) could be moved verbatim, with the never-executed JS test suites as the safety net.

Two facts changed that argument:

1. Those JS suites have **never been executed**. The main reason to stay in JavaScript was a safety net that does not exist as a demonstrated green run.
2. A working Python WaveScan loader already exists at `Paint Appearance/Component/Database/` — 36 pytest cases, real June/July 2026 data loaded (2192/255/31/1), SQL with physical CHECK/FK constraints, least-privilege role (partially — see ADR 0005).

v1 is WaveScan, not PELT (ADR 0004). The working artifact is Python.

## Decision

Backend is **Python 3.12 + FastAPI**. Domain modules (`reader`, `cleaner`, `dedup`, `mapping_engine`, later `grading`) import no FastAPI and no psycopg. OpenAPI is generated from FastAPI and is the frontend contract.

A golden-master harness against the prototype's CFCore/CFLogic is mandatory before Python grading is trusted (see `04-ANALYSIS.md`).

## Consequences

- NestJS, pnpm workspace, Prisma are out of scope for v1.
- The demo loader's Python modules are migrated, not rewritten.
- PELT, when it arrives, is ported to Python behind the same golden-master protocol — we do not introduce a second backend language.
- Frontend remains TypeScript (TanStack + React). Two languages in the repo is accepted; two backends is not.

## Alternatives rejected

- TypeScript/NestJS with a JS port of the WaveScan loader: throws away a tested Python artifact.
- Keep the Tkinter loader and add FastAPI beside it: two write paths, guaranteed drift.
