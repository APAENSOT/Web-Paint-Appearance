"""Unique colour identity fold: spelling → existing catalogue name, or none.

Not D2. Not a grading family. Not Levenshtein. The cleaner already looks up
`ref_color_alias` exactly. This layer only fires when that miss happens, and
only when **exactly one** `ref_color.color_name` remains after the same
normalisation the alias table uses, plus three deterministic folds plants
actually write:

* ``gray`` / ``grey``
* paint codes and 1–2 letter prefixes (``7VTAWWA``, ``M7``, ``FW -``)
* collapsed repeated letters (``Difused`` / ``Diffused``)

Zero matches or two matches stay ``UNKNOWN_COLOR`` so a person cross-checks.
A new colour name is still a named-owner catalogue insert, not this function.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.domain.references import normalise_alias

_GREY = re.compile(r"\bgray\b")
_DROP_WORDS = frozenset({"met", "tc", "solid", "metallic", "mc", "bc"})
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_DOUBLES = re.compile(r"(.)\1+")


def compact_tokens(raw: str) -> list[str]:
    folded = _GREY.sub("grey", normalise_alias(raw).replace("_", " "))
    return [part for part in _NON_ALNUM.sub(" ", folded).split() if part]


def _collapse_doubles(text: str) -> str:
    return _DOUBLES.sub(r"\1", text)


def stripped_phrase(tokens: Sequence[str]) -> str:
    kept: list[str] = []
    for token in tokens:
        if any(ch.isdigit() for ch in token):
            continue
        if len(token) <= 2:
            continue
        if token in _DROP_WORDS:
            continue
        kept.append(token)
    return " ".join(kept)


def unique_colour_identity(raw: str, catalogue: Sequence[str]) -> str | None:
    """Return the one catalogue name this spelling is, or ``None``.

    ``None`` means notify the uploader: do not invent a colour.
    """
    if not raw or not str(raw).strip() or not catalogue:
        return None
    tokens = compact_tokens(str(raw))
    phrase = " ".join(tokens)
    stripped = stripped_phrase(tokens)
    phrase_c = _collapse_doubles(phrase)
    stripped_c = _collapse_doubles(stripped)
    hits: list[str] = []
    for name in catalogue:
        name_tokens = compact_tokens(name)
        nphrase = " ".join(name_tokens)
        if not nphrase:
            continue
        ncoll = _collapse_doubles(nphrase)
        exact = nphrase in {phrase, stripped} or ncoll in {phrase_c, stripped_c}
        contained = len(name_tokens) >= 2 and (
            nphrase in phrase
            or nphrase in stripped
            or ncoll in phrase_c
            or ncoll in stripped_c
        )
        if exact or contained:
            hits.append(name)
    uniq = list(dict.fromkeys(hits))
    if len(uniq) == 1:
        return uniq[0]
    return None


def fold_colour(name: str | None, merged: Mapping[str, str]) -> str | None:
    """The name a colour is read and written as (T64, ADR 0014).

    ``merged`` is ``ref_color.color_name -> merged_into`` for merged names
    only. One level by construction (a database trigger refuses a chain), so
    a single lookup is the whole fold. Unknown or unmerged names pass through.
    """
    if name is None:
        return None
    return merged.get(name, name)


def merged_sources(canonical: str, merged: Mapping[str, str]) -> tuple[str, ...]:
    """Every stored name that folds onto ``canonical`` (not ``canonical`` itself)."""
    return tuple(sorted(old for old, new in merged.items() if new == canonical))
