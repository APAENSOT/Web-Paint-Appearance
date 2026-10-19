"""T88: match a whole panel set at once, under constraints (D-88-2, D-88-3).

T86 ranked each name alone and T87 let the walk number order the result.
Neither can answer the case the owner actually hit. September's ``14ROOF``
scores **0.80** against ``LCROOF`` and **0.80** against ``RCROOF`` -- a dead
tie -- and its number, 14, is neither panel's (11 and 27). Name similarity
has nothing left to say.

What answers it is the rest of the set. September's ``11ROOF`` already
matched ``LCROOF`` and loaded, so the only roof still open for ``14ROOF``
is ``RCROOF``. Not by spelling: **by constraint and exhaustion.**

So this module matches the set, not the name:

1. **orientation is a hard filter** (D-88-2) -- the file's Tolerance Group
   against the panel's `tolerance_group`. It removes candidates; it is never
   a score and never breaks a tie;
2. the survivors keep T86/T87's ranking exactly -- family, then name score,
   then the walk number (`rank_candidates`, reused unchanged);
3. the assignment is **bijective**: one spelling to one panel, both ways;
4. a pair that is the only possibility left in its orientation group is
   marked **exhaustion**, and only when that pool is provably closed;
5. re-solving after a confirmation never disturbs what was confirmed.

**Exhaustion is the dangerous part.** It is the strongest signal here and
the only one that can be confidently wrong, because it is sound only if the
pool it reasons over is really closed. Measured on this very file: FTM's
models carry **64 live panels** for the **32** physical panels September
walks, so a naive pool offers four roofs (``LCROOF``, ``RCROOF``,
``11ROOF``, ``27ROOF``) for two roof spellings, and exhaustion over that
pool means nothing. :func:`solve_set` therefore proves the pool **at the
moment of each claim** (G-88-1) and never inherits it from an earlier step.

Nothing here decides anything: every pair is confirmed by a person
(D-88-3). Pure: no FastAPI, no psycopg.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.panel_match import (
    BASIS_NUMBER_MATCH,
    Candidate,
    LivePanel,
    rank_candidates,
)

#: How a pair was arrived at, shown in the screen in these words (D-88-3).
#: Nothing branches on a signal; it is what the owner reads before saying
#: yes, and what `ref_plant_zone_map` records so a wrong one can be found
#: again (G-88-6).
SIGNAL_NAME = "name"
SIGNAL_NUMBER = "number"
SIGNAL_EXHAUSTION = "exhaustion"
SIGNAL_NONE = "none"

#: Said about an exhaustion pair, in its own words (G-88-3).
EXHAUSTION_WORDS = (
    "every other {orientation} panel of this model is taken, so this is the "
    "only one left ({spellings} unmatched name(s), {candidates} unmatched "
    "panel(s))"
)


@dataclass(frozen=True)
class HeldSpelling:
    """One panel spelling the file wrote, for one model."""

    raw_zone_text: str
    #: Tolerance Group values the file wrote for it. One is the normal case.
    #: More than one is a file problem: no orientation filter and no
    #: exhaustion for this spelling (G-88-5).
    orientations: tuple[str, ...] = ()
    count: int = 0
    raw_position: int | None = None

    @property
    def orientation(self) -> str | None:
        """The single orientation, or None when the file disagrees with itself."""
        return self.orientations[0] if len(self.orientations) == 1 else None


@dataclass(frozen=True)
class Proposal:
    """What the solver offers for one spelling. Never an answer."""

    raw_zone_text: str
    #: Ranked, orientation-filtered candidates. Empty is a real answer.
    candidates: tuple[Candidate, ...]
    #: The one the solver would pair it with, or None.
    proposed: str | None
    signal: str
    #: Plain words for why, shown beside the pair.
    reason: str
    #: True when this spelling's orientation could not be used (G-88-5).
    orientation_conflict: bool = False
    #: Candidates the orientation filter removed, for "show me everything".
    filtered_out: tuple[str, ...] = ()


@dataclass
class SetSolution:
    proposals: list[Proposal] = field(default_factory=list)
    #: (plant x model live panel count, file's distinct spelling count) when
    #: they disagree -- G-88-2. None when they agree.
    catalogue_warning: tuple[int, int] | None = None
    #: Spellings whose own rows disagree about orientation (G-88-5).
    orientation_conflicts: list[str] = field(default_factory=list)

    def by_spelling(self) -> dict[str, Proposal]:
        return {p.raw_zone_text: p for p in self.proposals}


def _orientation_of(panel: LivePanel) -> str:
    return (panel.tolerance_group or "").strip()


def _filter_by_orientation(
    spelling: HeldSpelling, panels: list[LivePanel]
) -> tuple[list[LivePanel], tuple[str, ...]]:
    """Keep only panels whose orientation matches. A hard filter (D-88-2).

    Returns the survivors and the names it removed, because the screen must
    keep offering the full list however it ranks (G-88-5): a constraint may
    narrow a **proposal** and may never take away the owner's ability to
    pick.
    """
    wanted = spelling.orientation
    if wanted is None:
        # No orientation, or the file disagrees with itself: filter nothing.
        return list(panels), ()
    kept = [p for p in panels if _orientation_of(p) == wanted]
    removed = tuple(
        sorted(p.zone_code for p in panels if _orientation_of(p) != wanted)
    )
    return kept, removed


def solve_set(
    spellings: list[HeldSpelling],
    panels: list[LivePanel],
    *,
    confirmed: dict[str, str] | None = None,
    live_panel_count: int | None = None,
    file_panel_count: int | None = None,
) -> SetSolution:
    """Propose a panel for every spelling at once, under the constraints.

    `confirmed` is what the owner has already said, `{spelling: zone_code}`.
    Those pairs are **pinned** (G-88-4): their panels leave the pool, their
    own proposal is never recomputed, and no later re-solve may move, drop
    or re-propose them. One wrong confirmation therefore cannot cascade.

    `live_panel_count` is the plant x model's full live count and
    `file_panel_count` how many distinct panels the file walks for it. Both
    are used only for the catalogue warning (G-88-2): `panels` is already
    the mappable, not-yet-used subset, and the warning is about the gap
    between the catalogue and the file -- which does not shrink as the owner
    works through the list.
    """
    confirmed = dict(confirmed or {})
    solution = SetSolution()

    distinct = (
        file_panel_count
        if file_panel_count
        else len({s.raw_zone_text for s in spellings})
    )
    total_live = live_panel_count if live_panel_count is not None else len(panels)
    if distinct and total_live != distinct:
        # G-88-2: said before any exhaustion claim, naming both numbers.
        solution.catalogue_warning = (total_live, distinct)

    taken = set(confirmed.values())
    open_spellings = [s for s in spellings if s.raw_zone_text not in confirmed]

    # Rank every open spelling first, so exhaustion can count the group it
    # is about rather than guessing at it.
    ranked: dict[str, tuple[list[Candidate], tuple[str, ...], bool]] = {}
    for spelling in spellings:
        if spelling.raw_zone_text in confirmed:
            continue
        conflict = len(spelling.orientations) > 1
        if conflict:
            solution.orientation_conflicts.append(spelling.raw_zone_text)
        available = [p for p in panels if p.zone_code not in taken]
        kept, removed = _filter_by_orientation(spelling, available)
        ranked[spelling.raw_zone_text] = (
            list(rank_candidates(spelling.raw_zone_text, kept)), removed, conflict
        )

    for spelling in spellings:
        raw = spelling.raw_zone_text
        if raw in confirmed:
            # G-88-4: pinned. Reported as it was confirmed, never re-solved.
            solution.proposals.append(
                Proposal(
                    raw_zone_text=raw,
                    candidates=(),
                    proposed=confirmed[raw],
                    signal=SIGNAL_NONE,
                    reason="you confirmed this",
                )
            )
            continue

        candidates, removed, conflict = ranked[raw]
        if not candidates:
            # D-88-4: an empty list is an answer, and it is never silent.
            solution.proposals.append(
                Proposal(
                    raw_zone_text=raw,
                    candidates=(),
                    proposed=None,
                    signal=SIGNAL_NONE,
                    reason=(
                        "no panel of this model has a close enough name"
                        + (
                            f" and the right orientation ({spelling.orientation})"
                            if spelling.orientation
                            else ""
                        )
                        + ". Pick from the full list if you know which it is."
                    ),
                    orientation_conflict=conflict,
                    filtered_out=removed,
                )
            )
            continue

        exhausted = _exhaustion_claim(
            spelling, candidates, open_spellings, ranked, conflict
        )
        if exhausted is not None:
            signal, reason = SIGNAL_EXHAUSTION, exhausted
        elif candidates[0].basis == BASIS_NUMBER_MATCH:
            signal = SIGNAL_NUMBER
            reason = (
                f"the file's own number {spelling.raw_position} is this "
                f"panel's number"
            )
        else:
            signal = SIGNAL_NAME
            reason = f"closest name ({candidates[0].basis})"

        solution.proposals.append(
            Proposal(
                raw_zone_text=raw,
                candidates=tuple(candidates),
                proposed=candidates[0].zone_code,
                signal=signal,
                reason=reason,
                orientation_conflict=conflict,
                filtered_out=removed,
            )
        )
    return solution


def _exhaustion_claim(
    spelling: HeldSpelling,
    candidates: list[Candidate],
    open_spellings: list[HeldSpelling],
    ranked: dict[str, tuple[list[Candidate], tuple[str, ...], bool]],
    conflict: bool,
) -> str | None:
    """The G-88-1 check, in full, at the moment of the claim.

    Exhaustion is claimed only when **all** of this holds, for this
    spelling's own orientation group and nothing wider:

    * the file is consistent about this spelling's orientation (G-88-5 --
      a spelling carrying two gets no filter, so it gets no exhaustion);
    * exactly **one** candidate survives the constraints for it;
    * the number of still-unmatched spellings in that orientation group
      **equals** the number of still-unmatched panels those spellings can
      reach -- i.e. the pool is closed, with nothing spare and nothing
      missing.

    The last one is what the four-roofs-for-two-spellings pool fails: two
    spellings against four reachable roofs is 2 != 4, so no claim is made
    and the pair is offered as a plain ranked list. The check is **local to
    the group**: there is no global "the file looks complete" anywhere in
    this module, because a file can be complete in one family and short in
    another.
    """
    if conflict or spelling.orientation is None:
        return None
    if len(candidates) != 1:
        return None

    orientation = spelling.orientation
    group = [
        s for s in open_spellings
        if len(s.orientations) == 1 and s.orientation == orientation
    ]
    reachable: set[str] = set()
    for member in group:
        member_candidates, _, member_conflict = ranked[member.raw_zone_text]
        if member_conflict:
            return None
        reachable.update(c.zone_code for c in member_candidates)

    if len(group) != len(reachable):
        return None
    return EXHAUSTION_WORDS.format(
        orientation=orientation.lower(),
        spellings=len(group),
        candidates=len(reachable),
    )


__all__ = [
    "EXHAUSTION_WORDS",
    "HeldSpelling",
    "Proposal",
    "SIGNAL_EXHAUSTION",
    "SIGNAL_NAME",
    "SIGNAL_NONE",
    "SIGNAL_NUMBER",
    "SetSolution",
    "solve_set",
]
