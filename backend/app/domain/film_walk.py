"""T99: what a Film sheet's **walk** has to look like, and the Job Number.

Pure rules, no SQL and no FastAPI. Everything here is driven by reference
data the caller loads, so it is plant-generic (D-99-12): a plant x model with
no ``film_point_setting`` row gets none of it and behaves exactly as it did
before T99.

The four rules, and why each one exists:

* **The walk guard** (D-99-7). FTM walks one fixed list of named points per
  model, in one order. A sheet whose body labels are that list, or a prefix
  of it, is the walk we know. Anything else -- a name inserted in the middle,
  a reorder, a renumber, a new name on the end -- means the file is not
  describing the list we think it is, so **the whole sheet is held**: not one
  row of it loads until a person says what changed. Point identity is
  number **and** name (D-99-1), so a renumbered walk silently reuses old
  names for different spots on the truck. That is the silent wrong
  measurement ``AGENTS.md`` opens with, and it is why a mid-walk change
  cannot be confirmed away by the uploader (D-99-14) while a name appended
  after the last known point can.
* **The never-stored tail** (D-99-6). ``001FTWISH``-``006FTWISH`` and
  ``BOOTH_1`` are the known tail of an FTM walk -- booth and wish readings,
  not points of a truck. They are shown as "not stored", and they are not a
  hold: a file is never blocked by the thing we already know about it.
* **No named points at all** (D-99-9). A sheet whose Locations are
  ``Point 001`` / ``017`` names nothing. There is no guess to make, so it is
  refused at the door with a plain sentence rather than held row by row.
* **The Job Number** (D-99-10, D-99-11). FTM writes
  ``{COLOUR}_{MODEL}_{7 digits}``. A Job Number of another shape holds the
  sheet and asks. A Job Number whose **model** token disagrees with the
  filename's holds the sheet and asks which one is right -- the two name
  different trucks. A Job Number whose **colour** token disagrees does not
  hold: Layer 2 decides the colour (it always has), and the row carries the
  disagreement as a warning so nobody has to find it later.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

from app.domain.film import (
    REASON_FILM_NO_NAMED_POINTS,
    RENUMBER_ADVICE,
    normalise_location,
)

#: ``Point 001`` / ``POINT 17`` / ``Point 001 / 017`` -- a label that names no
#: point (D-99-9). T99-FIX: the nine real no-name FTM files write the
#: ``Point NNN / NNN`` form (point number out of total), which
#: `normalise_location` folds to ``POINT001/017``. The optional ``/NNN`` is
#: why D-99-9 never fired on a real file.
_NO_NAME = re.compile(r"^POINT[0-9]+(/[0-9]+)?$")


def names_no_points(labels: Sequence[str]) -> bool:
    """True when every body label on the sheet is a ``Point NNN`` placeholder.

    Every, not any: a real walk with one stray placeholder is a walk-guard
    question about that one label, which is a different answer from "this
    file names no points".
    """
    body = [normalise_location(label) for label in labels if str(label or "").strip()]
    return bool(body) and all(_NO_NAME.match(label) for label in body)


# =====================================================================
# the walk
# =====================================================================
@dataclass(frozen=True)
class WalkVerdict:
    """What the body labels of one sheet are, against the known walk."""

    #: The labels are live names of the walk, in the walk's own order
    #: (T99-FIX / D-99-15: points may be skipped), with nothing appended.
    ok: bool
    #: The first label the walk does not account for.
    first_break: str | None
    #: Labels past the last live name the sheet writes, in order (D-99-14).
    appended: tuple[str, ...]
    #: True when the uploader may confirm it (appended names only).
    confirmable: bool
    #: One plain sentence for the person reading the worksheet.
    detail: str
    #: T109 (D-109-6). Labels the live list does not hold that are **not**
    #: appended after its end: a retired point's label, a spelling nobody has
    #: aliased yet. Each is asked about in its own row, and the rest of the
    #: sheet loads, so these never stop a file.
    unknown: tuple[str, ...] = ()
    #: T109. Does the whole sheet stop? True for the three things that mean
    #: the file is not describing the list we think it is (a reorder, a
    #: renumber, a repeat) and for names appended past the end, which the
    #: uploader confirms (D-99-14). False when the only thing wrong is a
    #: label the list does not hold, which is a question for its own row.
    holds: bool = False


def check_walk(
    labels: Sequence[str],
    walk: Sequence[str],
    *,
    plant: str,
    model: str,
    resolved: Mapping[str, str] | None = None,
) -> WalkVerdict:
    """D-99-7, widened by D-99-15 and by T109 (D-109-6). What the sheet's
    body labels are.

    ``labels`` are the sheet's body labels with the tail and the limit rows
    already removed, as the file wrote them; ``walk`` is the plant x model's
    live list in ``point_no`` order. Both are compared normalised, so
    ``1)001HOOD`` and ``001HOOD`` are one label. ``resolved`` is
    ``{normalised label: live point_code}`` for the labels a **remembered
    alias** already answers (T109): the guard runs on the names the labels
    resolve to, so a label somebody has mapped onto a point of the walk is
    that point here, in that point's place.

    The sheet passes when every label is a **live name** of that walk and the
    names appear in the walk's own order -- a strictly increasing run through
    the list. T99 demanded a *prefix*, which held `AW_RAP_1954807Pum.xlsx`
    for good: it writes `059RTFEND, 060LBOXSIDE, 063LBOXSIDE`, all RAPCAP
    names in RAPCAP order, with 061 and 062 simply not measured. A skipped
    point is a point nobody measured, which the vehicle's own completeness
    already says (D-99-15); it is not a sheet describing a different walk.

    **What holds the whole sheet** (``holds``) is a live name the list does
    not account for, because that means the file is not describing the list
    we think it is:

    * a live name **out of the list's order**, which is a reorder or a
      renumber: point identity is number *and* name (D-99-1), so filing those
      rows would put old names on different spots of the truck;
    * a duplicate of a name already written, which is the same thing;
    * names past the last live name the sheet writes, which are **appended**
      and which the uploader may confirm (D-99-14).

    **What does not** raise ``holds`` (T109, D-109-6) is a label the list
    simply does not hold with live names still after it -- a point that was
    retired, a spelling this plant started writing. Until T109 that held the
    sheet for good: there was no way to say what the label is. Now there is,
    in the row: pick the live point it means (remembered as an alias for
    every later upload) or add a new point on Point Check. So the label comes
    back in ``unknown`` and the rows that carry it are asked about.

    **T109-FIX (D-109F-1): nothing on that sheet loads either.** ``unknown``
    is not a sheet-wide *question* -- the questions stay in the rows -- but it
    is a sheet nobody has finished reading, and the caller holds every row of
    it until each label is answered. The shape that proves it is a walk
    renumbered down: `005HOOD`..`014HOOD` are then physically the old
    006..015, every label is a live name one spot out, and "loading the rest"
    files 76 readings onto the wrong points of the truck without a word. When
    the answers are in, this function runs again on the **resolved** names, so
    a set of answers that resolves to a reorder or a repeat still holds the
    whole sheet (D-109F-2). Known names out of order are unchanged -- they
    hold everything by themselves (D-99-7).
    """
    seen = [normalise_location(label) for label in labels]
    at = {normalise_location(point): i for i, point in enumerate(walk)}
    resolve = {
        normalise_location(label): normalise_location(point)
        for label, point in (resolved or {}).items()
    }
    seen = [resolve.get(label, label) for label in seen]
    shown = list(labels)
    on = f"{plant}'s {model} walk"
    #: The next position of the list a label is still allowed to name.
    cursor = 0
    #: The last live name the sheet wrote, for the out-of-order sentence.
    previous: str | None = None
    #: Where the live names the sheet writes sit, in file order.
    last_known = -1
    unknown: list[int] = []

    for index, label in enumerate(seen):
        place = at.get(label)
        if place is None:
            unknown.append(index)
            continue
        if place >= cursor:
            cursor = place + 1
            previous = shown[index]
            last_known = index
            continue
        return WalkVerdict(
            ok=False,
            first_break=shown[index],
            appended=(),
            confirmable=False,
            holds=True,
            detail=(
                # T100 Part A4: a name written twice is its own sentence.
                # The reorder wording read "writes 011HOOD after 011HOOD,
                # and the walk has 011HOOD before 011HOOD", which says
                # nothing. The hold itself is unchanged.
                (
                    f'This sheet writes "{shown[index]}" twice; {on} has '
                    f"it once. The whole sheet is held and nothing from it "
                    f"loads: one point of one car is one reading, so we "
                    f"cannot tell which of the two the car was measured "
                    f"at. Fix the file and upload it again."
                )
                if label == normalise_location(previous) else
                f'This sheet does not walk {on} in its own order: it '
                f'writes "{shown[index]}" after "{previous}", and the '
                f'walk has "{shown[index]}" before "{previous}". The '
                f"whole sheet is held and nothing from it loads. A walk "
                f"that reorders or renumbers the known list needs an "
                f"owner decision -- a point is its number and its "
                f"name, so filing these rows would put old names on "
                f"different spots, and no confirmation can make that safe "
                f"(D-99-14)."
            ),
        )

    if not unknown:
        return WalkVerdict(
            ok=True, first_break=None, appended=(), confirmable=False,
            holds=False,
            detail=(
                f"{len(seen)} of {len(at)} point(s) of {on}, in order."
                if len(seen) < len(at) else f"the whole of {on}."
            ),
        )
    if unknown[0] > last_known:
        # D-99-14, unchanged: every unaccounted name comes after the last
        # point of the list the sheet names, so confirming them adds to the
        # end and moves nothing that is already on it.
        appended = tuple(shown[index] for index in unknown)
        return WalkVerdict(
            ok=False,
            first_break=shown[unknown[0]],
            appended=appended,
            confirmable=True,
            holds=True,
            detail=(
                f'This sheet writes {len(appended)} name(s) past the last '
                f'point of {on} it names, starting with "{shown[unknown[0]]}". '
                f"The whole sheet is held until someone confirms them: each "
                f"new point needs Horizontal or Vertical and whether it "
                f"counts. Nothing from this sheet loads before that."
            ),
        )
    # T109 (D-109-6): asked in the row. T109-FIX (D-109F-1): and nothing on
    # the sheet loads until every one of them is answered.
    names = tuple(dict.fromkeys(shown[index] for index in unknown))
    return _unknown_verdict(names, on)


def _unknown_verdict(names: tuple[str, ...], on: str) -> WalkVerdict:
    """T109 (D-109-6): labels the list does not hold, asked in their rows."""
    return WalkVerdict(
        ok=False,
        first_break=names[0],
        appended=(),
        confirmable=False,
        holds=False,
        unknown=names,
        detail=(
            f"{len(names)} label(s) on this sheet are not points of {on}, "
            f'starting with "{names[0]}". Each one is asked about in its own '
            f"row: say which live point it is and we remember it for every "
            f"later upload, or add it as a new point on Point Check first. "
            f"Nothing on this sheet loads until every label is answered. "
            f"{RENUMBER_ADVICE}"
        ),
    )


# =====================================================================
# RO14: a sheet that holds several cars, one after another
# =====================================================================
def walk_starts(
    labels: Sequence[str],
    walk: Sequence[str],
    resolved: Mapping[str, str] | None = None,
    identities: Sequence[object] | None = None,
) -> list[int]:
    """D-RO14-1. Where each car's walk starts, as indexes into ``labels``.

    A new walk starts at every label that resolves to the **first** point of
    the live list (``walk[0]``, the lowest ``point_no``) once the current walk
    already has a label. ``resolved`` is the same ``{label: live point}`` map
    `check_walk` takes, so an alias of the first point starts a car too. A
    model with no live list is one walk.

    ``identities`` are the labels' ``(Job Number, VIN)``. A sheet whose every
    label carries the same non-blank one names one car, so it is one walk: a
    first point written again inside it is a repeat or a reorder that
    `check_walk` holds (D-99-7), never a second car (a PELT's preamble Job).
    """
    if not labels:
        return []
    if not walk or (
        identities and len(set(identities)) == 1 and any(identities[0] or ())
    ):
        return [0]
    head = normalise_location(walk[0])
    resolve = {
        normalise_location(label): normalise_location(point)
        for label, point in (resolved or {}).items()
    }
    return [0] + [
        index for index, label in enumerate(labels)
        if index and resolve.get(
            normalise_location(label), normalise_location(label)
        ) == head
    ]


def car_of(index: int, cars: int, row: int) -> str:
    """D-RO14-2: the words that say which car of a sheet a sentence is about."""
    return f"Car {index + 1} of {cars} on this sheet (starting at row {row})"


def check_walks(
    labels: Sequence[str],
    walk: Sequence[str],
    *,
    rows: Sequence[int],
    plant: str,
    model: str,
    resolved: Mapping[str, str] | None = None,
    identities: Sequence[object] | None = None,
) -> WalkVerdict:
    """D-RO14-2. `check_walk` once per car of the sheet, with the same rules.

    One walk is exactly `check_walk`. With several, the first car that holds
    holds the whole sheet, and its sentence starts by naming that car and the
    row it starts at (``rows`` are the labels' source rows). Labels the list
    does not hold are gathered from every car and asked in their rows, as for
    one car.
    """
    starts = walk_starts(labels, walk, resolved, identities)
    if len(starts) <= 1:
        return check_walk(labels, walk, plant=plant, model=model, resolved=resolved)
    on = f"{plant}'s {model} walk"
    unknown: list[str] = []
    for index, (start, end) in enumerate(zip(starts, starts[1:] + [len(labels)])):
        verdict = check_walk(
            labels[start:end], walk, plant=plant, model=model, resolved=resolved,
        )
        if verdict.holds:
            return replace(verdict, detail=(
                f"{car_of(index, len(starts), rows[start])}: {verdict.detail}"
            ))
        unknown.extend(verdict.unknown)
    if unknown:
        return _unknown_verdict(tuple(dict.fromkeys(unknown)), on)
    return WalkVerdict(
        ok=True, first_break=None, appended=(), confirmable=False, holds=False,
        detail=f"{len(starts)} cars, each on {on} in order.",
    )


def walk_fingerprint(points: Iterable[tuple[str, Sequence[object]]]) -> str:
    """D-RO14-4. 16 hex characters of SHA-256 over one car's walk.

    ``points`` are ``(point_code, the four layer values as written)`` in sheet
    order. The file name is not in it, so the same readings uploaded again
    under another name are the same car, and two cars share it only when
    every reading is identical.
    """
    text = "\n".join(
        "|".join([point, *("" if v is None else str(v) for v in values)])
        for point, values in points
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def walk_mixed_detail(car: str, what: str, first: object, second: object) -> str:
    """D-RO14-3. One car carrying two dates or two colours."""
    return (
        f'{car} carries two {what}s, "{first}" and "{second}". One car is one '
        f"day and one colour, so the whole sheet is held and nothing from it "
        f"loads. Fix the file and upload it again."
    )


# =====================================================================
# the Job Number
# =====================================================================
@dataclass(frozen=True)
class JobVerdict:
    """What the sheet's Job Number says, against the plant's shape."""

    #: The Job Number is of the plant's shape, or the plant has no shape.
    ok: bool
    #: Group 1 and group 2 of the shape, when it matched.
    color_token: str | None
    model_token: str | None
    #: One plain sentence, when it did not match.
    detail: str


def read_job_no(pattern: str | None, job: object) -> JobVerdict:
    """D-99-10. Parse the sheet's Job Number once, against the plant's shape.

    No pattern and no Job Number are both "nothing to check": a plant that
    has not named a shape keeps today's behaviour exactly, and a sheet with
    no Job Number is already handled by `real_identity` (a car with no
    identity is its own vehicle).
    """
    text = str(job or "").strip()
    if not pattern or not text:
        return JobVerdict(True, None, None, "")
    found = re.match(pattern, text.upper())
    if found is None:
        return JobVerdict(
            False, None, None,
            f'The Job Number on this sheet is "{text}", which is not the '
            f"shape this plant writes ({pattern}). The whole sheet is held: "
            f'a Job Number names the truck. You can answer "load as written" '
            f"and it loads as its own vehicle under that number, or leave it "
            f"held and fix the file."
        )
    groups = found.groups()
    return JobVerdict(
        True,
        groups[0] if len(groups) > 0 else None,
        groups[1] if len(groups) > 1 else None,
        "",
    )


def model_conflict(
    job_token: str | None,
    filename_token: str | None,
    aliases: Mapping[tuple[str, str], str],
    *,
    plant: str,
) -> tuple[str, str] | None:
    """D-99-11. The two models this sheet names, when they disagree.

    Returns ``(model from the Job Number, model from the filename)``, or
    None when they agree, when either token has no Film list at this plant,
    or when one of them is missing. Both must resolve through
    `ref_film_model_alias` at the plant -- the only set a Film model may
    come from (D-78-32) -- because a conflict the uploader cannot answer
    with two real models is not a question worth asking.
    """
    if not job_token or not filename_token:
        return None
    if job_token.upper() == filename_token.upper():
        return None
    from_job = aliases.get((plant, job_token.upper()))
    from_name = aliases.get((plant, filename_token.upper()))
    if not from_job or not from_name or from_job == from_name:
        return None
    return from_job, from_name


def model_conflict_detail(
    from_job: str, from_name: str, *, job: str, filename: str
) -> str:
    return (
        f'This sheet names two models: the Job Number "{job}" says '
        f'{from_job} and the file name "{filename}" says {from_name}. They '
        f"are different trucks, so the whole sheet is held. Choose the one "
        f"that is right and it loads under that model."
    )



def proposed_orientation(
    point_code: str, orientations: Mapping[str, str | None]
) -> str | None:
    """T100 (Part A1). The H/V this list already gives that panel word.

    ``orientations`` is ``{point_code: 'H' | 'V' | None}`` for the plant x
    model's live list. A new name the sheet appended takes the orientation
    the list's **own** points of the same panel word carry -- `099TGATEIN`
    takes whatever `091TGATEIN` … `093TGATEIN` have. The word is the name
    with its leading digits removed, which is how a Film point name is
    built (D-99-1).

    None when the list has no point of that word, or its points disagree:
    then the person chooses, and the review asks them to. This is **data
    read off the list**, not a second copy of migration 0033's H/V rule --
    if the owner ever changes a point's orientation on the points page, the
    name proposed for a new point of the same word changes with it.
    """
    word = _panel_word(point_code)
    found = {
        value.strip() for code, value in orientations.items()
        if value and _panel_word(code) == word
    }
    return found.pop() if len(found) == 1 else None


def _panel_word(point_code: str) -> str:
    """``099TGATEIN`` -> ``TGATEIN``: the name without its leading digits."""
    return re.sub(r"^[0-9]+", "", normalise_location(point_code))


def point_no_of(point_code: str) -> int | None:
    """T109 (D-109-5). ``099TGATEIN`` -> 99: a point's number is its digits.

    A Film point's identity is the number and the name the file writes
    (D-99-1), so the number is read off the name rather than handed out by
    the list. None when the name has no leading digits, or when they are
    zero: ``point_no`` is ``> 0`` by constraint and a point of a walk with no
    number is a name nobody can put in order.
    """
    digits = re.match(r"^([0-9]+)", normalise_location(point_code))
    if digits is None:
        return None
    value = int(digits.group(1))
    return value if value > 0 else None


def tail_label_detail(label: str, *, plant: str, model: str) -> str:
    return (
        f'"{label}" is the known tail of {plant}\'s {model} walk (FTWISH / '
        f"booth readings). It is kept and never stored as a point of a "
        f"truck, and it does not stop the rest of the sheet loading."
    )


def no_named_points_detail(*, plant: str, model: str | None, sheet: str) -> str:
    on = f"{plant}'s {model}" if model else plant
    return (
        f"Sheet [{sheet}] names no points: every Location on it is a "
        f'placeholder like "Point 001". We cannot tell which point of {on} '
        f"each reading is, and we never guess one from walk order. Nothing "
        f"was loaded from this file. Upload the report that writes the point "
        f"names."
    )


# =====================================================================
# T103: the box section of a walk
# =====================================================================
BOX = "box"
NO_BOX = "no_box"

#: The token the refusal note of a no-name sheet carries, and the prefix
#: this module strips off it to get the sentence back (D-103-4).
_NO_NAMED_POINTS_PREFIX = f"{REASON_FILM_NO_NAMED_POINTS}: "


def box_tag(stops: Iterable[int], walked: Iterable[int]) -> str | None:
    """Box / No box for one car, from where its readings sit in the walk.

    T103 (D-103-1). A truck built without a box is finished at a complete
    stop (D-99-8), so the **box section of a list is everything after its
    lowest stop**: a car with a reading there walked a box, and a car with
    none did not. No model name, panel word or point code is written down
    here -- the stops come from the plant's live list.

    `stops` and `walked` are ranks in that one list: `point_no`, or the
    index of the point in `walk`. Both arguments must be ranked the same
    way. A list that names no stop has no box section to look at, so there
    is nothing to say about the car and the answer is None (every plant but
    FTM today). A list whose lowest stop is its last point has an empty box
    section, so every car of it is `no_box` (FTM SGL, D-103-2).
    """
    ranked = sorted(stops)
    if not ranked:
        return None
    return BOX if any(point > ranked[0] for point in walked) else NO_BOX


def no_named_points_note(notes: str | None) -> str | None:
    """The stored refusal sentence of a no-name sheet, or None (D-103-4).

    `load_batch.notes` keeps the reason token in front of the sentence so a
    reader of the row can tell refusals apart. The person on the review
    screen is told the sentence, which already says what to do -- upload the
    report that writes the point names -- and never a token.
    """
    if not notes or not notes.startswith(_NO_NAMED_POINTS_PREFIX):
        return None
    return notes[len(_NO_NAMED_POINTS_PREFIX):].strip() or None


__all__ = [
    "BOX",
    "NO_BOX",
    "JobVerdict",
    "WalkVerdict",
    "box_tag",
    "car_of",
    "check_walk",
    "check_walks",
    "model_conflict",
    "model_conflict_detail",
    "names_no_points",
    "no_named_points_detail",
    "no_named_points_note",
    "point_no_of",
    "proposed_orientation",
    "read_job_no",
    "tail_label_detail",
    "walk_fingerprint",
    "walk_mixed_detail",
    "walk_starts",
]
