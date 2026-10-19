"""T89 Part 5 (D-88-7): say "this is a renaming", not "741 bad rows".

The locked piece T88 did not build. September's real file walks the 32
panels FTM has always walked and calls every one of them something new, so
the worksheet reported it the only way it could: hundreds of rows held for
an unknown panel name, one line each, as though the file were full of
mistakes. It is not. It is one event -- somebody renamed the whole walk --
and a reviewer who is told that goes to the match screen instead of
scrolling through 741 identical complaints.

The claim is deliberately narrow, because a wrong "this is a renaming"
would send somebody to re-map a file that merely has a few bad rows:

* **every** panel name the file writes for this model is held. One held
  name out of 32 is a typo, not a renaming;
* the file walks **as many** panels as the model has panels a match can
  point at;
* the **orientation multiset matches** -- the same number of Horizontal and
  the same number of Vertical. 14 and 18 at FTM. A file that walks 32
  panels of a different shape is not the same walk renamed.

**Which list "as many as the model has" counts against.** The panels a
confirmed pair may point at: the live panels that are also positions on
the model's own `ref_model_zone` catalogue. At every clean plant that is
the whole live list. At FTM it is 32 of 64 -- and the literal live count
would never match, so the signal would never fire at the one plant it was
written for. The mappable list is also the honest one: it is what the
reviewer can actually answer the question with.

Nothing here decides a pair. It names the shape of the file and points at
the screen that asks a person. Pure: no FastAPI, no psycopg.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

MESSAGE = (
    "This tab writes {file_count} panel names for {model} and none of them "
    "are on {plant}'s list for it, while that list holds {live_count} panels "
    "a match can point at, with the same {shape} split. This looks like a "
    "renaming of all {file_count} panels rather than {rows} bad rows: match "
    "the panel list once and say which name is which panel."
)


@dataclass(frozen=True)
class RenameSignal:
    """One model of one sheet that looks like a whole-set rename."""

    model_code: str
    file_panel_count: int
    live_panel_count: int
    rows_held: int
    orientations: dict[str, int]
    message: str


def _shape_words(orientations: Mapping[str, int]) -> str:
    return " / ".join(
        f"{count} {name}" for name, count in sorted(orientations.items())
    )


def whole_set_rename(
    *,
    plant_code: str,
    model_code: str,
    held_spellings: Sequence[str],
    file_panel_count: int,
    rows_held: int,
    file_orientations: Mapping[str, int],
    mappable_orientations: Mapping[str, int],
) -> RenameSignal | None:
    """The signal for one `(sheet, model)`, or None when it does not hold.

    `held_spellings` is the distinct panel names of this model that are
    held; `file_panel_count` is how many distinct panel names the file
    writes for it. `file_orientations` and `mappable_orientations` are the
    Horizontal / Vertical counts of the file's panel names and of the
    panels a match may point at.

    Every condition has to hold. Each one on its own has an innocent
    explanation; together they only have the one.
    """
    held = {s for s in held_spellings if s}
    if not held or file_panel_count <= 0:
        return None
    # One held name among many is a typo. All of them is an event.
    if len(held) != file_panel_count:
        return None
    live_count = sum(mappable_orientations.values())
    if live_count != file_panel_count:
        return None
    if Counter(file_orientations) != Counter(mappable_orientations):
        return None
    if not file_orientations:
        return None
    return RenameSignal(
        model_code=model_code,
        file_panel_count=file_panel_count,
        live_panel_count=live_count,
        rows_held=rows_held,
        orientations=dict(sorted(file_orientations.items())),
        message=MESSAGE.format(
            plant=plant_code,
            model=model_code,
            file_count=file_panel_count,
            live_count=live_count,
            shape=_shape_words(file_orientations),
            rows=rows_held,
        ),
    )


__all__ = ["MESSAGE", "RenameSignal", "whole_set_rename"]
