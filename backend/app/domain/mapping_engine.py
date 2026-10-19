"""PORTED VERBATIM from the vault's ``mapping_engine.py``.

It was already pure Python with no database and no framework, so the only
changes are this note and the import path -- the algorithm, and the long
explanation below of why position-order matching alone is not proof, are
kept exactly as written. That explanation records a real bug found during
SAP onboarding, not a stylistic preference.

This module NEVER decides anything and NEVER writes to ``wavescan``. It
produces PROPOSED rows for a human to approve (`02-PIPELINE.md` §4:
"Similarity is advisory ... never auto-apply").

-- original module docstring follows --

Propose a mapping from a plant's own zone labels to the canonical
zone_code, for a model that already has a canonical zone list (any
model already loaded at AAT/FTM: P703 Ranger/Raptor/Super Duty, U704).

This module NEVER decides anything and NEVER writes to wavescan. It
only produces PROPOSED rows for a human to approve in
`ref_plant_zone_map` (see `loader.propose_zone_mappings` and the
Mapping tab). If a proposal turns out wrong, a person rejects it here
- the database never trusted it in the first place.

Algorithm, chosen because it was tested against real data before this
file was written:

    Matching a plant's zones onto the canonical list purely by
    POSITION NUMBER is unsafe - AAT/FTM's own zone_no differs between
    models (RCROOF is #27 on P703 but #26 on U704), and FVL walks the
    vehicle in a different physical order entirely (raw-sequence
    matching got 20 of 25 vertical zones wrong when checked against
    FVL vs FTM).

    Grouping by PANEL KEYWORD first (HOOD, ROOF, FENDER, DOOR, BOX,
    TAILGATE, PILLAR, LIFTGATE), then sequencing within that group by
    position, matched all 8 panel groups with identical member counts
    on that same FVL-vs-FTM comparison. That is the method
    implemented here.

A group is only proposed if both sides have a matching group name AND
the same member count. A count mismatch (e.g. the plant recorded 34
zones for a model that has 32) is exactly the situation that must be
surfaced to a person, never guessed - so it becomes an
`UnresolvedZone` instead of a proposal.

WHY POSITION ORDER ALONE IS STILL NOT PROOF, EVEN AFTER THE COUNT
MATCHES - a real mistake, found and fixed before this file's first
use in production:

    AAT/FTM's TAILGATE group orders Left(Top,Bottom,Middle) then
    Right(Bottom,Top) - the right side's order is REVERSED relative
    to the left. SAP's own file writes Left(Top,Bottom) then Middle
    then Right(Top,Bottom) - NOT reversed. Both sides have 5 members,
    both groups match by keyword and count, so position-order
    matching produced a fully "confident" proposal that silently
    swapped Right-Top and Right-Bottom.

    Two different attempts to catch this automatically were tried -
    decoding a direction from this project's own zone_code letters,
    and requiring an explicit direction word in the raw text - and
    BOTH were rejected: the zone_code letters collide between
    genuinely different zones (LCFDOOR "Front Door" and LCRDOOR
    "Rear Door" both start with the same two letters), and the
    word-based version was so broad it deferred groups that were
    actually fine (FENDER, BOX, DOOR, HOOD), destroying most of the
    value of proposing anything at all.

    The result: this module does NOT try to verify direction
    automatically. Instead every proposal's `note` states the
    canonical zone's own readable name (e.g. "RB Tailgate") next to
    the raw label it was matched against, specifically so a HUMAN
    reviewing the Mapping tab can compare the two and catch a
    Top/Bottom/Front/Rear/Middle disagreement before approving - the
    same way this exact bug was actually found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Keyword -> panel_group. Order matters: longer/more specific
# keywords are checked first so e.g. 'TAILGATE' is never swallowed by
# the later, looser 'TG' rule, and 'FDOOR'/'RDOOR' are checked before
# the bare 'DOOR' rule that would also match them (harmlessly, but
# checking the specific one first keeps the winning rule obvious).
_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("LIFTGATE", "LIFTGATE"),
    ("TAILGATE", "TAILGATE"),
    ("HOOD", "HOOD"),
    ("ROOF", "ROOF"),
    ("FENDER", "FENDER"),
    ("PILLAR", "PILLAR"),
    ("BOX", "BOX"),
    ("FDOOR", "DOOR"),
    ("RDOOR", "DOOR"),
    ("DOOR", "DOOR"),
    ("TG", "TAILGATE"),  # short form seen at SAP-style plants
    ("FD", "DOOR"),      # SAP-style "Front Door" abbreviation
    ("RD", "DOOR"),      # SAP-style "Rear Door" abbreviation
)

_LEADING_NUMBER = re.compile(r"^\s*(\d+)")


def guess_panel_group(raw_zone_text: str) -> str | None:
    """Best-guess panel group from a raw zone label.

    Advisory only. Used to build a PROPOSAL - never to accept or
    reject a row, and never written anywhere without human approval.
    """
    upper = raw_zone_text.upper()
    for keyword, group in _KEYWORDS:
        if keyword in upper:
            return group
    return None


def extract_position(raw_zone_text: str) -> int | None:
    """The leading position number, if the plant's label starts with
    one (e.g. '14ROOF' -> 14, '01RHS Hood Rr28' -> 1). Provenance
    only - never used as identity."""
    m = _LEADING_NUMBER.match(raw_zone_text)
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class CanonicalZone:
    """One zone from the model's existing canonical list
    (ref_model_zone joined to ref_checkzone)."""

    zone_code: str
    zone_no: int
    panel_group: str
    tolerance_group: str
    zone_name: str = ""  # readable name e.g. 'RB Tailgate' - shown to the
                         # human reviewer alongside the raw text so THEY
                         # can catch a wrong pairing (see module docstring
                         # for why this is a human step, not an automatic
                         # one).


@dataclass(frozen=True)
class RawZone:
    """One distinct zone label as a plant's file actually writes it."""

    raw_text: str
    position: int | None  # None if the label carries no leading number


@dataclass(frozen=True)
class ZoneProposal:
    raw_text: str
    raw_position: int | None
    zone_code: str
    method: str
    note: str


@dataclass(frozen=True)
class UnresolvedZone:
    """A raw zone the engine could not confidently propose anything
    for. Always includes why, so a human knows what to do next."""

    raw_text: str
    raw_position: int | None
    reason: str


@dataclass
class ProposalResult:
    proposals: list[ZoneProposal]
    unresolved: list[UnresolvedZone]

    def counts(self) -> tuple[int, int]:
        return len(self.proposals), len(self.unresolved)


_METHOD = "keyword-group + within-group sequence"


def propose_mapping(
    canonical: list[CanonicalZone],
    raw: list[RawZone],
) -> ProposalResult:
    """Group both lists by panel keyword, sequence within each group
    by position, and pair them up group-by-group.

    Deliberately conservative: a group with no keyword match, no
    matching canonical group, or a member-count mismatch produces
    `UnresolvedZone` entries instead of a guess.
    """
    canon_by_group: dict[str, list[CanonicalZone]] = {}
    for c in canonical:
        canon_by_group.setdefault(c.panel_group, []).append(c)
    for members in canon_by_group.values():
        members.sort(key=lambda c: c.zone_no)

    raw_by_group: dict[str, list[RawZone]] = {}
    unresolved: list[UnresolvedZone] = []

    for r in raw:
        group = guess_panel_group(r.raw_text)
        if group is None:
            unresolved.append(UnresolvedZone(
                raw_text=r.raw_text, raw_position=r.position,
                reason=(
                    "no recognised panel keyword in this label "
                    "(looked for HOOD/ROOF/FENDER/DOOR/BOX/TAILGATE/"
                    "PILLAR/LIFTGATE) - needs a manual alias, not a proposal"
                ),
            ))
            continue
        raw_by_group.setdefault(group, []).append(r)

    for members in raw_by_group.values():
        members.sort(key=lambda r: (r.position is None, r.position))

    proposals: list[ZoneProposal] = []
    for group, raws in raw_by_group.items():
        canon = canon_by_group.get(group)
        if canon is None:
            for r in raws:
                unresolved.append(UnresolvedZone(
                    raw_text=r.raw_text, raw_position=r.position,
                    reason=(
                        f"guessed panel group {group!r} does not exist "
                        f"on this model - check the label by hand"
                    ),
                ))
            continue

        if len(canon) != len(raws):
            for r in raws:
                unresolved.append(UnresolvedZone(
                    raw_text=r.raw_text, raw_position=r.position,
                    reason=(
                        f"panel group {group!r}: {len(raws)} zone(s) in the "
                        f"file but the model expects {len(canon)} - counts "
                        f"must match before a mapping can be proposed"
                    ),
                ))
            continue

        for r, c in zip(raws, canon):
            proposals.append(ZoneProposal(
                raw_text=r.raw_text, raw_position=r.position,
                zone_code=c.zone_code,
                method=_METHOD,
                note=(
                    f"grouped as {group} ({len(raws)} member(s)), matched "
                    f"by position order within the group -> canonical "
                    f"name is {c.zone_name or c.zone_code!r}: CHECK this "
                    f"agrees with the raw text's own wording, especially "
                    f"for Top/Bottom/Front/Rear/Middle - position order "
                    f"alone is not proof (this exact check caught a real "
                    f"swapped pair during SAP onboarding, on TAILGATE)"
                ),
            ))

    return ProposalResult(proposals=proposals, unresolved=unresolved)
