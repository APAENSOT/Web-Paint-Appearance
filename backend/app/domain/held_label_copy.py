"""Operator copy for held labels. Identity policy, not grading (D2).

Empty sentinels (spec I4/I5) are never teachable. Compact zones and real
spellings are not empty. No FastAPI, no psycopg.

T39 (ADR 0013): every sentence is written for the Engineer who uploaded the
file -- plain words, what happens to the row, and what they can do. A raw
token is never the only thing said.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from app.domain.cleaner import MONTH_NAMES
from app.domain.reader import MEASURES_HOLE_APPROVABLE

DisplayGroup = Literal[
    "colour", "model", "zone", "empty_identity", "date", "header", "plant_offer",
    "plant", "measure", "film_point", "film_model",
]

_EMPTY = frozenset({"", "none", "(none)", "null"})

_REASON_GROUP: dict[str, DisplayGroup] = {
    "UNKNOWN_COLOR": "colour",
    "COLOR_NOT_OFFERED": "plant_offer",
    "UNKNOWN_MODEL": "model",
    "MODEL_NOT_OFFERED": "plant_offer",
    "FILM_ONLY_MODEL": "plant_offer",
    "UNIDENTIFIED_MODEL": "model",
    "UNKNOWN_CHECKZONE": "zone",
    "ZONE_NOT_VALID_FOR_MODEL": "zone",
    "BAD_DATE": "date",
    "UNREVIEWED_HEADER": "header",
    "VEHICLE_IDENTITY_MISSING": "empty_identity",
    "MISSING_REQUIRED_FIELD": "empty_identity",
    "PAINTLINE_MISSING": "empty_identity",
    "PLANT_MISMATCH": "plant",
    "MISSING_MEASUREMENT": "measure",
    # T54: FilmThickness holds. The location is the plant's own text.
    "EXTRA_POINT": "film_point",
    "UNMAPPED_POINT": "film_point",
    "FILM_MODEL_UNRESOLVED": "film_model",
}

#: Reasons whose group does not depend on the cell being blank: a missing
#: measure is always blank, and a plant question is about the text written.
_REASON_FIRST = frozenset({
    "BAD_DATE", "MISSING_MEASUREMENT", "PLANT_MISMATCH",
    "EXTRA_POINT", "UNMAPPED_POINT", "FILM_MODEL_UNRESOLVED",
})

_MEASURE_LABEL = {"cf": "CF", "lw": "LW", "sw": "SW"}


def _measure_labels(measures: list[str]) -> str:
    """``"LW, SW and CF are"`` -- the subject and its verb, for the copy."""
    names = [
        _MEASURE_LABEL.get((m or "").lower(), (m or "a value").upper())
        for m in measures
    ]
    if len(names) == 1:
        return f"{names[0]} is"
    return f"{', '.join(names[:-1])} and {names[-1]} are"


def is_empty_identity_sentinel(raw: str | None) -> bool:
    if raw is None:
        return True
    return str(raw).strip().casefold() in _EMPTY


#: T55: the FilmThickness file or tab name does not settle one model here.
FILM_MODEL_MESSAGE = (
    "We cannot tell which model this file is from its file or tab name. The "
    "name must say the model this plant uses (for example DBL, RB, RAP, SGL, "
    "U704, CX743, V363 or J73). If it already does, that program has no "
    "FilmThickness list at this plant yet: ask an Admin."
)


#: RO15: the date the cleaner's month / year ``BAD_DATE`` detail names
#: (``cleaner.date_disagrees``), read back so the sentence can say it.
_DISAGREEING_DATE = re.compile(r"^date (\d{4}-\d{2}-\d{2}) is in ")


def _date_disagrees_message(column: str, shown: str, details: list[str]) -> str:
    """RO15 (D-RO15-3): what disagrees and what to do. Not answerable here."""
    found = sorted({
        date.fromisoformat(m.group(1))
        for m in map(_DISAGREEING_DATE.match, details) if m
    })
    names = [f"{d.day} {MONTH_NAMES[d.month - 1][:3]} {d.year}" for d in found]
    days = " and ".join(filter(None, [", ".join(names[:-1]), *names[-1:]]))
    cell = column.capitalize()
    if len(found) > 1:
        said = f"These rows are dated {days}, but their {cell} cell says"
        will = "They will not load."
    elif found:
        said = f"This row's date is {days}, but its {cell} cell says"
        will = "It will not load."
    else:
        said = f"This row's date is not in the {column} its {cell} cell says,"
        will = "It will not load."
    return (
        f'{said} "{shown}". {will} Fix the date or the {column} in the file '
        "and upload it again. We never choose one for you."
    )


def has_display_group(reason: str) -> bool:
    """True when this reason has its own sentence below (T53)."""
    return reason in _REASON_GROUP


def display_group_for(reason: str, raw_value: str) -> DisplayGroup:
    # Blank measure dates stay "date" (fix the date cell), not empty identity.
    if reason in _REASON_FIRST:
        return _REASON_GROUP[reason]
    if is_empty_identity_sentinel(raw_value):
        return "empty_identity"
    return _REASON_GROUP.get(reason, "header")


#: T86 section 3.8. What a held panel says when **no single-panel pick can
#: be offered** for it -- the zone is a real panel another model owns
#: (`ZONE_NOT_VALID_FOR_MODEL`, never per-row teachable by D-31), or the
#: spelling is spread over more than one model. The old sentence told the
#: user to "pick the panel it is from that list" in that case too, and no
#: control was ever rendered: the copy promised a thing that did not exist,
#: and the one held panel that *did* get a picker made two
#: identical-looking rows behave differently.
#:
#: This sentence names the thing that does exist instead.
PANEL_MATCH_MESSAGE = (
    'The panel name "{shown}" is not on this model\'s panel list at '
    "{here}, and we cannot offer a single panel to pick for it here. Use "
    '"Match the panel list" on this tab to match this file\'s panel names '
    "to {here}'s own panels, name by name -- we never read the number as "
    "the answer, and an Admin approves the whole set before anything "
    "loads. We never move a panel name onto another one by ourselves."
)


#: T88 (D-88-1 / G-88-5). A panel hold now knows which model it is being
#: asked about and which orientation the file wrote for it, so the sentence
#: can say both. One spelling on two models produces two of these, one per
#: model, and each names its own model -- which is what tells a reviewer
#: looking at two identical-looking rows that they are two questions.
PANEL_ON_MODEL = (
    '"{shown}" is not on {model}\'s panel list at {here}. Pick the panel it '
    "is from {model}'s own list{orientation}. Not a colour. If it is a new "
    "panel, ask an Admin to add it to the catalogue first, then upload "
    "again. We never move a panel name onto another one by ourselves."
)
#: Said when the same spelling is also held on another model in this tab.
#: RO18: it no longer repeats the name and model the sentence before it says,
#: which took a long name past `HeldLabelGroup.operator_message`'s 500.
PANEL_TWO_ORIENTATIONS = (
    " The file writes more than one Tolerance Group for it ({orientations}), "
    "so we cannot use orientation to narrow this one down. Check the "
    "spreadsheet: a panel is Horizontal or Vertical, not both."
)


#: T89 (D-89-6). Said when this plant x model has **no** panel a confirmed
#: pair may point at, so neither picker can offer anything and the match
#: screen cannot help either.
#:
#: Measured 2026-10-08: `FVL / P703 DBL RANGER`, `SAP / J73 DBL` and
#: `SAP / P703 DBL RANGER` each carry 32 live panels and **0** that
#: `ref_plant_zone_map.fk_pzm_model_zone` can reference, because their live
#: names are that plant's own spellings and are not positions on the
#: model's `ref_model_zone` catalogue. Before T89 all 32 were offered and
#: the write failed against the foreign key; an empty list is the truth,
#: and the truth needs a sentence.
PANEL_NO_MAPPABLE = (
    "\"{shown}\" is not on {model}'s panel list at {here}, and right now no "
    "panel of {model} at {here} can be the target of a panel map: its live "
    "panels are {here}'s own names and are not positions on {model}'s own "
    "catalogue. So there is nothing to pick here and the match screen "
    "cannot help either. An Admin has to put those panels on {model}'s "
    "catalogue first; until then these rows stay held and nothing is "
    "guessed."
)


#: T115 (D-115-5). A model held because it is not on the plant's list.
#: It shares the "plant_offer" group with a colour, but not the colour's
#: promise: confirming a model writes an alias and never an offer
#: (`services/mapping.py`), so only an Admin's Attach can load these rows --
#: and Attach reloads the held sheet by itself (`services/model_offer.py`).
MODEL_NOT_OFFERED_MESSAGE = (
    "{model} is not on {here}'s list (it was removed, or never attached), so "
    "these rows will not load. An Admin attaches it on Standard → Model; "
    "this file then loads by itself."
)


#: T115-FIX (D-115F-2). A Film-only model (RAPCAP, Single CAP) on a Wave
#: Scan row. Not teachable (T46: never relabelled Ranger) and not loaded by
#: an Attach (`repositories.batches.held_for_model_offer` selects
#: `MODEL_NOT_OFFERED` only), so the sentence promises neither.
FILM_ONLY_MODEL_MESSAGE = (
    "{model} is measured for Film Thickness only, so a Wave Scan sheet cannot "
    "load it. Check the sheet's Model column; nothing here can attach it to "
    "Wave Scan."
)


def operator_message_for(
    group: DisplayGroup,
    raw_value: str,
    *,
    column: str | None = None,
    plant: str | None = None,
    teachable: bool = True,
    model: str | None = None,
    orientations: list[str] | None = None,
    missing: list[str] | None = None,
    approvable: bool | None = None,
    reason: str | None = None,
    details: list[str] | None = None,
) -> str:
    shown = str(raw_value).strip() or "(blank)"
    here = plant or "this plant"
    if group == "plant_offer" and reason == "MODEL_NOT_OFFERED":
        return MODEL_NOT_OFFERED_MESSAGE.format(model=shown, here=here)
    if group == "plant_offer" and reason == "FILM_ONLY_MODEL":
        return FILM_ONLY_MODEL_MESSAGE.format(model=shown)
    if group == "colour":
        return (
            f'"{shown}" is not a catalogue colour yet. Pick the official colour '
            "it is. If it is a brand-new colour, an Admin has to add it first, "
            "then upload again."
        )
    if group == "model":
        return (
            f'"{shown}" is not a model spelling we have for {here}. Pick the '
            f"model it is from {here}'s list. A leftover never goes onto "
            "Ranger. If the model is not on that list at all, an Admin has to "
            "add it first, then upload again."
        )
    if group == "plant_offer":
        return (
            f'"{shown}" is a real name but not on this plant\'s list, so these '
            f"rows will not load yet. Pick the official name it is. If {here} "
            "does not list it yet, confirming adds it to the list."
        )
    if group == "plant":
        return (
            f'The Plant column says "{shown}", but you uploaded this file on '
            f"{here}'s page. Is this {here}'s data? Yes loads these rows as "
            f"{here}. No cancels this upload so you can use the right page."
        )
    if group == "measure":
        # T98 (D-98-1): name every measure the held points are actually short
        # of, not only the first one. A point short of CF cannot load even
        # with its LW/SW holes approved, so it is not offered that button.
        empty = [m for m in (missing or []) if m] or [(column or "").lower()]
        label = _measure_labels(empty)
        #: whether any held point here loads once its LW/SW holes are approved.
        can_approve = (
            set(empty) <= set(MEASURES_HOLE_APPROVABLE)
            if approvable is None else approvable
        )
        if can_approve and set(empty) <= set(MEASURES_HOLE_APPROVABLE):
            return (
                f"{label} empty on these points. You can approve loading "
                "them without LW/SW, or fix the file. We never fill it in."
            )
        if can_approve:
            return (
                f"{label} empty on these points. You can approve loading the "
                "points that have CF without LW/SW; a point with no CF never "
                "loads at all. We never fill it in."
            )
        return (
            f"{label} empty on these points, so they cannot load"
            + (
                ": nothing loads without CF, and approving LW/SW holes does "
                "not change that."
                if "cf" in empty and set(empty) & set(MEASURES_HOLE_APPROVABLE)
                else "."
            )
            + " Fix the file and upload it again. The rest of the sheet "
            "still loads."
        )
    if group == "zone":
        # T86: only promise a pick when one is actually on offer.
        if not teachable:
            return PANEL_MATCH_MESSAGE.format(shown=shown, here=here)
        # T88 (D-88-1): name the model, because this spelling may be held on
        # more than one and each is its own question with its own answer.
        # The old sentence said "this model" where there was no single one.
        found = sorted(orientations or [])
        if model and len(found) > 1:
            return PANEL_ON_MODEL.format(
                shown=shown, here=here, model=model, orientation=""
            ) + PANEL_TWO_ORIENTATIONS.format(
                # RO18: swapped columns can write a panel name per row here.
                # shortcut: a value over ~45 characters still overflows the
                # 500 of HeldLabelGroup.operator_message (it is quoted twice);
                # shorten the copy or the cap if a file ever writes one.
                orientations=(
                    ", ".join(found) if len(found) <= 2
                    else f"{len(found)} different values"
                ),
            )
        if model:
            orientation = (
                f" (the file calls it {found[0]})" if len(found) == 1 else ""
            )
            return PANEL_ON_MODEL.format(
                shown=shown, here=here, model=model, orientation=orientation
            )
        return (
            f'"{shown}" is not on this model\'s panel list at {here}. Pick the '
            "panel it is from that list. Not a colour. If it is a new panel, "
            "ask an Admin to add it to the catalogue first, then upload "
            "again. We never move a panel name onto another one by ourselves."
        )
    if group == "film_point":
        return (
            f'"{shown}" is not on {here}' "'s FilmThickness point list for this "
            "model (or it is an extra point). It is kept and not loaded. A new "
            "point needs an Admin to add it first. We never move it onto "
            "another plant's point."
        )
    if group == "film_model":
        return FILM_MODEL_MESSAGE
    if group == "empty_identity":
        return (
            "This row has a blank model, colour, date or panel, so it will not "
            "load. Fix the spreadsheet if it matters. The rest of the sheet "
            "still loads. We never fill in a model, colour or panel."
        )
    if group == "date" and column in ("month", "year"):
        return _date_disagrees_message(column, shown, details or [])
    if group == "date":
        return (
            "This row has no usable measure date, so it will not load. Fix the "
            "date cell. We never use the upload day instead."
        )
    return (
        f'We do not use the column "{shown}". Ignore it and keep the rest of '
        "the sheet?"
    )
