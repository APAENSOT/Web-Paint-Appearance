"""T86 panel match: score a file's panel name against a plant's live panels.

**Who may be a candidate is decided by the name alone.** Two gates, both
derived from the name and nothing else:

1. the panel family (`ws_panel_group`: HOOD / ROOF / FENDER / DOOR / BOX /
   TAILGATE / PILLAR / LIFTGATE) must agree. ``ROOF`` and ``BOX`` are not
   near-misses of each other at any score;
2. the remaining letters, with every digit removed, must reach
   :data:`MIN_SCORE` on `difflib.SequenceMatcher`.

A label that clears neither yields **no candidate**. That is the honest
answer: ``12LCPILLAR`` with no pillar on the live list gets an empty list,
not the closest thing available (`AGENTS.md` rule 6). This is what keeps
FTM's ``14LFBOXSD`` off September's ``14ROOF`` -- the **family** gate
refuses it, not the number, and that refusal is independent of every
number on either side (D-86-3, kept whole by D-87-3).

**T87 (D-87-1): the walk number orders what is already a candidate.** Once
both gates have passed, a candidate whose `point_no` is the label's own
leading number is listed first. It was measured on the real September file
that 28 of its 32 names differ from each other *only* by that number, so
name-only ordering proposed one panel for ``06LFFENDER``, ``07LFFENDER``
and ``08LFFENDER`` alike -- confidently, at 1.0, and wrong for two of the
three. The number cannot create a candidate, cannot lift one over either
gate, and -- because `uq_plant_ws_point_no_live` allows one live panel per
walk number -- can promote **at most one** candidate. A candidate it
promoted says so, in its own basis (D-87-2).

Nothing here decides anything. The score is shown to the person who knows
which physical panel the name is, and that person picks (D-87-4).
Pure: no FastAPI, no psycopg.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from app.domain.ws_plant_gold import gold_key, ws_panel_group

#: Below this, two names are not the same panel spelled differently. Chosen
#: so ``06LFFENDER`` reaches ``06LFFFEND`` (0.80) and ``LFFENDER`` (1.00)
#: while ``ROOF`` never reaches ``LFBOXSD`` (0.18) -- which the family gate
#: already refuses outright.
MIN_SCORE = 0.55

#: How a candidate was scored, for the screen to show. Never a rule.
#:
#: The middle one exists so the screen can be honest about what it did and
#: did not read: ``14ROOF`` and ``11ROOF`` are the same name once the number
#: is dropped, and dropping the number is exactly the thing D-86-3 asks for
#: -- so they score the same, and the person is told the numbers differ
#: rather than being shown a bare "same name".
BASIS_SAME_LABEL = "same panel name"
BASIS_SAME_NAME_OTHER_NUMBER = "same name, different number"
BASIS_SIMILAR_NAME = "similar name"

#: T87 / D-87-2. Carried by the one candidate the walk number put first, so
#: the screen never shows a number-derived ordering as if the name had won
#: it. The name still had to pass both gates to be here at all; the score
#: beside it still says how close the names are.
BASIS_NUMBER_MATCH = "the file's own number is this panel's number"

_LEADING_POSITION = re.compile(r"^\s*(\d+)")
_LETTERS_ONLY = re.compile(r"[^a-z]")


def read_position(label: str) -> int | None:
    """The label's own leading number, or None.

    Provenance only (S14 / D-86-3). It is stored on the map row and shown
    beside the name; it takes no part in :func:`score_name` or
    :func:`rank_candidates`.
    """
    found = _LEADING_POSITION.match(str(label))
    if not found:
        return None
    value = int(found.group(1))
    return value if 1 <= value <= 40 else None


def name_core(label: str) -> str:
    """The label with its leading number and punctuation removed.

    ``06LFFENDER`` -> ``lffender``; ``14ROOF`` -> ``roof``; ``14LFBOXSD`` ->
    ``lfboxsd``; ``01RHS Hood Rr28`` -> ``rhshoodrr``. Digits *inside* the
    name go too: a trailing ``28`` is as much a walk number as a leading one,
    and neither says which panel this is.
    """
    without_position = _LEADING_POSITION.sub("", str(label))
    return _LETTERS_ONLY.sub("", without_position.casefold())


def panel_family(label: str) -> str | None:
    """The panel family of this name, or None when the name has none."""
    try:
        return ws_panel_group(label)
    except ValueError:
        return None


def score_name(label: str, zone_code: str) -> float:
    """0..1 for how much these two **names** look like the same panel.

    1.0 only for the same name -- identical cores, or the same panel text up
    to the leading-zero pad the gold list already treats as one point
    (``01HOOD`` == ``1HOOD``, D-58-03). Otherwise the `SequenceMatcher`
    ratio of the two cores, rounded to 3 places so the screen and the stored
    `similarity` agree.
    """
    if gold_key(label) == gold_key(zone_code):
        return 1.0
    left, right = name_core(label), name_core(zone_code)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return round(SequenceMatcher(None, left, right).ratio(), 3)


def basis_for(label: str, zone_code: str, score: float) -> str:
    """Words for *why* this candidate scored what it scored.

    Read by a person, never by code: nothing branches on a basis.
    """
    if gold_key(label) == gold_key(zone_code):
        return BASIS_SAME_LABEL
    if score >= 1.0:
        return BASIS_SAME_NAME_OTHER_NUMBER
    return BASIS_SIMILAR_NAME


@dataclass(frozen=True)
class LivePanel:
    """One live panel of a plant x model (`ref_plant_ws_point`)."""

    zone_code: str
    point_no: int
    tolerance_group: str
    #: False when `ref_plant_zone_map` cannot reference it -- see
    #: `services/panel_match.py`. A candidate is never built from one.
    mappable: bool = True


@dataclass(frozen=True)
class Candidate:
    zone_code: str
    point_no: int
    tolerance_group: str
    score: float
    basis: str


def rank_candidates(label: str, panels: list[LivePanel]) -> list[Candidate]:
    """Every live panel whose **name** could be this label, best first.

    Membership is the two name gates and nothing else (D-87-1): the loop
    below is unchanged from T86, so a candidate list is still exactly the
    panels whose family agrees and whose letters reach :data:`MIN_SCORE`.
    ``14ROOF`` against a list holding ``14LFBOXSD`` is still empty, and the
    shared ``14`` buys nothing, because the number is not read until after
    the loop has finished (D-87-3).

    **The order** then puts the panel carrying the label's own walk number
    first, and orders the rest by score and name as before. Three reasons it
    is safe to read the number here and nowhere else:

    * it is applied to a list the number did not build, so it can reorder
      and never create;
    * `uq_plant_ws_point_no_live` makes a walk number unique among the live
      panels of one plant x model, so it promotes **at most one** candidate
      -- never a block, never a reshuffle;
    * the promoted candidate carries :data:`BASIS_NUMBER_MATCH`, so the
      screen says the number ordered it (D-87-2).

    A label with no leading number, or one no candidate's `point_no` equals,
    leaves the order exactly as T86 had it. The sort is total and
    reproducible: ties fall through to `zone_code`.
    """
    family = panel_family(label)
    out: list[Candidate] = []
    for panel in panels:
        if not panel.mappable:
            continue
        if family is None or panel_family(panel.zone_code) != family:
            continue
        score = score_name(label, panel.zone_code)
        if score < MIN_SCORE:
            continue
        out.append(
            Candidate(
                zone_code=panel.zone_code,
                point_no=panel.point_no,
                tolerance_group=panel.tolerance_group,
                score=score,
                basis=basis_for(label, panel.zone_code, score),
            )
        )

    # Read only now, and only over candidates the name already chose.
    position = read_position(label)
    out = [
        replace(candidate, basis=BASIS_NUMBER_MATCH)
        if position is not None and candidate.point_no == position
        else candidate
        for candidate in out
    ]
    out.sort(
        key=lambda c: (c.basis != BASIS_NUMBER_MATCH, -c.score, c.zone_code)
    )
    return out


__all__ = [
    "BASIS_NUMBER_MATCH",
    "BASIS_SAME_LABEL",
    "BASIS_SAME_NAME_OTHER_NUMBER",
    "BASIS_SIMILAR_NAME",
    "MIN_SCORE",
    "Candidate",
    "LivePanel",
    "basis_for",
    "name_core",
    "panel_family",
    "rank_candidates",
    "read_position",
    "score_name",
]
