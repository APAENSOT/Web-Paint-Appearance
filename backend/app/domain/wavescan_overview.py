"""WaveScan Monthly Overview helper (T73): readings below Minimum. Pure.

No FastAPI, no SQL, no status. The box status stays the grading module's
``status_of`` on the box mean; this helper only *lists* the individual
readings of a box that fall below that box's own Minimum (D-73-02).

``eps`` is passed in by the caller (the grading module's ``EPS``) so there is
one epsilon and this module does not import the grading module. The
comparison is the one ``status_of`` uses for FAIL, on floats: ``cf <
minimum - eps``. A reading equal to Minimum is not listed; WaveScan has no
upper side.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping


def below_minimum(
    readings: Iterable[Mapping],
    minimum,
    *,
    eps: float,
) -> list[dict]:
    """Every reading with ``cf < minimum - eps``, most severe first.

    ``readings`` carry ``measurement_id``, ``measured_date``, ``checkzone``
    and ``cf``, copied through unchanged (``cf`` exact, as a Decimal). With
    ``minimum`` None the list is empty. Nothing is de-duplicated: two rows
    with the same values are two readings (distinct ``measurement_id``).
    Order (D-73-04): ``cf`` ascending, then ``measured_date`` (None last),
    ``checkzone`` (None last), ``measurement_id``.
    """
    if minimum is None:
        return []
    floor = float(minimum) - eps
    found = [
        {
            "measurement_id": int(r["measurement_id"]),
            "measured_date": r.get("measured_date"),
            "checkzone": r.get("checkzone"),
            "cf": Decimal(r["cf"]),
        }
        for r in readings
        if r["cf"] is not None and float(r["cf"]) < floor
    ]
    found.sort(
        key=lambda p: (
            p["cf"],
            p["measured_date"] is None,
            p["measured_date"] or date.min,
            p["checkzone"] is None,
            p["checkzone"] or "",
            p["measurement_id"],
        )
    )
    return found
