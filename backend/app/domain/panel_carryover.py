"""T89 (D-89-9): the panel decision somebody already made, carried forward.

A taught pair normally means the question never comes back: the
`ref_plant_zone_map` row makes the spelling resolve at the door and the row
never holds again. **Where the question does come back, it must not come
back blank.** Measured across `panel_match.py`, `panel_set_match.py` and
`held_labels.py` before this module existed: there was no pre-fill of any
kind, so a reviewer who had already said what `06LFFENDER` is was asked
again from scratch -- on the next upload of the same file while the
proposal waited for an Admin, on the other model of the same tab, and
after the file misspelled it by one letter.

Three cases, and they are the only three (D-89-9):

1. **pending** -- the same spelling, the same model, a pair that is still
   `PROPOSED`. Nobody has approved it, so nothing resolves yet and the row
   still holds;
2. **other model** -- the same spelling taught on a **different** model of
   this plant. `ref_plant_zone_map` is keyed by model (D-89-10), so the
   pair genuinely does not fire here. It is still what a person decided
   this text means at this plant, which is worth showing;
3. **near miss** -- a spelling this plant has not seen that is one or two
   characters off one it was taught (`06LFFENDE` after `06LFFENDER`), on
   the same model.

**It is a pre-fill and never an answer.** The carried pair arrives selected
and labelled as carried over, naming when it was decided and which batch it
came from, and a person still confirms it -- or changes it. Nothing here
writes, applies or auto-confirms anything, and a carried pair whose panel
is not on offer for this question is **dropped**, because pre-selecting a
panel the approval path would refuse is the defect T89 Part 1 exists to
remove.

Pure: no FastAPI, no psycopg.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Sequence

from app.domain.ws_plant_gold import gold_key, ws_panel_group

#: How close two *spellings* have to be before one is treated as a misspelt
#: version of the other. Deliberately much higher than
#: `panel_match.MIN_SCORE`, which answers a different question (is this
#: name this panel?): here both sides are file spellings of the same thing,
#: so `06LFFENDE` vs `06LFFENDER` (0.95) is in and `06LFFENDER` vs
#: `07LFFENDER` (0.90) must stay out -- they are two different panels whose
#: names differ by one digit, which is the whole reason T86 exists.
NEAR_MISS_MIN = 0.92

#: Why this row arrived pre-filled, in one word. Shown, never branched on.
CARRY_PENDING = "pending"
CARRY_OTHER_MODEL = "other_model"
CARRY_NEAR_MISS = "near_miss"


@dataclass(frozen=True)
class TaughtPair:
    """One panel pair this plant has been taught (approved or pending)."""

    raw_zone_text: str
    zone_code: str
    model_code: str
    status: str
    decided_at: datetime | None = None
    load_id: int | None = None
    method: str | None = None


@dataclass(frozen=True)
class CarriedOver:
    """A previous decision, offered again. Never applied by itself."""

    zone_code: str
    kind: str
    #: Plain words naming when it was decided and where it came from.
    reason: str
    source_raw_zone_text: str
    source_model_code: str
    decided_at: datetime | None = None
    load_id: int | None = None


def _when(decided_at: datetime | None) -> str:
    return f" on {decided_at.date().isoformat()}" if decided_at else ""


def _from(load_id: int | None) -> str:
    return f", from batch {load_id}" if load_id else ""


def _same_family(left: str, right: str) -> bool:
    """Both names classify, and into the same family.

    A near miss has to be a near miss of the *same kind of panel*. Without
    this gate a two-character typo could carry a ROOF decision onto a BOX
    name, which is precisely the mistake the family gate exists to stop
    (D-86-3), and a pre-filled wrong panel is worse than a blank one.
    """
    try:
        return ws_panel_group(left) == ws_panel_group(right)
    except ValueError:
        return False


def _near(left: str, right: str) -> float:
    return SequenceMatcher(None, left.upper(), right.upper()).ratio()


def carried_over_for(
    raw_zone_text: str,
    model_code: str,
    taught: Sequence[TaughtPair],
    offerable: Sequence[str],
) -> CarriedOver | None:
    """The decision to carry onto this question, or None.

    `offerable` is the panels this question may actually be answered with
    (T89 Part 1's one list). A carried pair outside it is dropped rather
    than shown: the screen must never pre-select something the approval
    path would refuse.

    The three cases are tried in order of how strongly they are the same
    decision -- same spelling and model first, then the same spelling on
    another model, then a misspelling. Within a case the most recent
    decision wins, which is what `taught` is already ordered by; ties fall
    back to the panel name so the answer is stable.
    """
    may_offer = set(offerable)
    if not may_offer:
        return None
    key = gold_key(raw_zone_text)

    usable = [pair for pair in taught if pair.zone_code in may_offer]

    pending = [
        pair
        for pair in usable
        if pair.model_code == model_code
        and gold_key(pair.raw_zone_text) == key
        and pair.status != "APPROVED"
    ]
    if pending:
        pair = pending[0]
        return CarriedOver(
            zone_code=pair.zone_code,
            kind=CARRY_PENDING,
            reason=(
                f"You already matched {pair.raw_zone_text!r} to "
                f"{pair.zone_code} for {model_code}{_when(pair.decided_at)}"
                f"{_from(pair.load_id)}, and that pair is still waiting for "
                f"an Admin to approve it -- which is why this name is still "
                f"held. Confirm it again, or change it."
            ),
            source_raw_zone_text=pair.raw_zone_text,
            source_model_code=pair.model_code,
            decided_at=pair.decided_at,
            load_id=pair.load_id,
        )

    other_model = [
        pair
        for pair in usable
        if pair.model_code != model_code
        and gold_key(pair.raw_zone_text) == key
    ]
    if other_model:
        pair = other_model[0]
        return CarriedOver(
            zone_code=pair.zone_code,
            kind=CARRY_OTHER_MODEL,
            reason=(
                f"This plant already reads {pair.raw_zone_text!r} as "
                f"{pair.zone_code} on {pair.model_code}"
                f"{_when(pair.decided_at)}{_from(pair.load_id)}. A panel pair "
                f"is learned per model, so it does not apply to "
                f"{model_code} until somebody says it does. Confirm it for "
                f"{model_code}, or change it."
            ),
            source_raw_zone_text=pair.raw_zone_text,
            source_model_code=pair.model_code,
            decided_at=pair.decided_at,
            load_id=pair.load_id,
        )

    near = sorted(
        (
            (_near(raw_zone_text, pair.raw_zone_text), pair)
            for pair in usable
            if pair.model_code == model_code
            and gold_key(pair.raw_zone_text) != key
            and _same_family(raw_zone_text, pair.raw_zone_text)
            and _near(raw_zone_text, pair.raw_zone_text) >= NEAR_MISS_MIN
        ),
        key=lambda item: (-item[0], item[1].zone_code),
    )
    if near:
        score, pair = near[0]
        return CarriedOver(
            zone_code=pair.zone_code,
            kind=CARRY_NEAR_MISS,
            reason=(
                f"This is one or two characters off {pair.raw_zone_text!r}, "
                f"which you matched to {pair.zone_code} for {model_code}"
                f"{_when(pair.decided_at)}{_from(pair.load_id)} "
                f"({round(score * 100)}% the same spelling). It may be the "
                f"same panel typed differently -- check it, then confirm or "
                f"change it."
            ),
            source_raw_zone_text=pair.raw_zone_text,
            source_model_code=pair.model_code,
            decided_at=pair.decided_at,
            load_id=pair.load_id,
        )
    return None


__all__ = [
    "CARRY_NEAR_MISS",
    "CARRY_OTHER_MODEL",
    "CARRY_PENDING",
    "CarriedOver",
    "NEAR_MISS_MIN",
    "TaughtPair",
    "carried_over_for",
]
