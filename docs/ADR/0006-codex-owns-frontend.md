# ADR 0006 — Codex owns the frontend end-to-end; Lovable does not touch this repo

**Status:** Accepted (amended 2026-09-13 by [ADR 0007](0007-lovable-external-reference.md))  
**Date:** 2026-09-08  
**Supersedes:** the Lovable frontend assignment in `docs/AGENTS.md` §3 (2026-09-07) and the original orchestration model from the 2026-08-19 brainstorming session ("Loveable" for frontend design, Claude Code/Codex for backend).  
**Amended by:** ADR 0007 — Lovable may produce a disposable **external** visual reference; it still does not edit this repository or own production `frontend/`. **Amended by:** [ADR 0009](0009-lovable-is-production-frontend.md) — that approved chrome is now mounted as production `frontend/`; Codex still owns it.

## Context

The original orchestration model split work by tool strength: Claude Code and Codex as backend/logic implementers, Lovable as the frontend design tool. `docs/tasks/T06-frontend-slice.md` (2026-09-07) accordingly assigned T06 to "Lovable (UI) + Codex/Claude (wiring) as needed."

The owner has since decided to use Codex for frontend UX/UI design as well as the engineering work (SPA conversion, API wiring), and for Lovable to never touch this repository.

## Decision

**Codex owns `frontend/` end-to-end**: visual/UX design decisions, the TanStack-to-SPA conversion, and all API wiring. No task in this repo is handed to or expects input from Lovable.

ADR 0007 does **not** move production ownership. It only allows Lovable to produce a disposable prototype **outside this repository**. Codex still implements every production screen.

Codex does not have a Skills framework equivalent to Claude Code's `.claude/skills`; where a task would have said "load skill X," the relevant guidance is written directly into the task file or `AGENTS.md` instead.

## Consequences

- `docs/AGENTS.md` §3, `docs/tasks/T06-frontend-slice.md`, `docs/00-ARCHITECTURE.md` §4/§8, and `docs/tasks/T03-api-contract.md` are updated to remove Lovable and name Codex.
- There is no separate design-review handoff step in T06 — Codex is accountable for its own UX decisions, documented in its task report rather than reviewed by a second agent.
- If a future task needs dedicated visual/design iteration beyond what Codex produces, that is a new decision to raise explicitly, not an assumption that Lovable re-enters the workflow. **Raised 2026-09-13:** ADR 0007 permits Lovable only as an out-of-repo visual reference. Production `frontend/` stays Codex-only. **T10-UI** is Codex implementing the workspace shell from an architect concept spec; it does not wait on a Lovable prototype. Module layout is ADR 0008.

## Alternatives rejected

- Split T06 into a Codex wiring pass followed by a Lovable design pass: rejected per explicit owner instruction — two agents touching the same frontend code in sequence risks the same "second copy of the truth" problem `AGENTS.md` warns about elsewhere (e.g. duplicated grading logic), applied here to duplicated component ownership.
