"""Leftover vehicle programs that must not be taught onto P703.

G1 D-07 / finish-batch H7: CX743, V363, J73, and U704 are other programs.
An Engineer identity alias may bind a spelling of a *rostered* program
(P703 → Ranger) or a leftover spelling onto **that leftover's own**
catalogue (CX743 → CX743). It must not bind a leftover Style/Model cell
onto Ranger zones.

No FastAPI, no psycopg (`AGENTS.md` rule 8). Prefix match after the same
normalisation the cleaner uses for aliases.
"""

from __future__ import annotations

from app.domain.references import normalise_alias

#: Folded prefixes. `P703` is deliberately absent.
LEFTOVER_PROGRAM_PREFIXES: tuple[str, ...] = (
    "j73",
    "cx743",
    "v363",
    "u704",
)


def leftover_program_prefix(raw: str) -> str | None:
    """Which leftover family ``raw`` belongs to, or None if it is not leftover."""
    compact = normalise_alias(raw).replace(" ", "")
    if not compact:
        return None
    for prefix in LEFTOVER_PROGRAM_PREFIXES:
        if compact == prefix or compact.startswith(prefix):
            return prefix
    return None


def is_leftover_program(raw: str) -> bool:
    """True when ``raw`` names a leftover program, not a P703 spelling.

    Compares the compacted alias (spaces removed) so ``J73 DBL`` and
    ``j73`` match ``j73``, while ``P703`` and ``P703 RAP`` do not match
    ``u704``.
    """
    return leftover_program_prefix(raw) is not None


def leftover_maps_to_own_program(raw: str, model_code: str) -> bool:
    """True when a leftover spelling is bound to that same leftover catalogue.

    ``CX743`` → ``CX743`` is identity. ``CX743`` → ``P703 DBL RANGER`` is
    the fold H7 forbids.
    """
    prefix = leftover_program_prefix(raw)
    target = leftover_program_prefix(model_code)
    return prefix is not None and prefix == target
