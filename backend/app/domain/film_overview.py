"""FilmThickness overview helpers (T67, T73): out-of-spec readings, line labels,
and the Base-ladder colour sequence. Pure.

No FastAPI, no SQL, no status. The box status is ``grading.film_box_status``
on the box mean (D-67-10: one grading file). These helpers only *list*
readings beyond a line (D-67-04) and *name* the lines (D-67-05).

``eps`` is passed in by the caller (``grading.EPS``) so there is one
epsilon and this module does not import the grading module.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping

CLEAR = "CLEAR"

#: T73 D-73-13: ``ladder`` values of a colour sequence entry.
LADDER_BASE = "BASE"
LADDER_NONE = "NO_BASE_STANDARD"

#: D-67-05, the authoritative copy for the limit lines.
MINIMUM = "Minimum"
MAXIMUM = "Maximum"
NO_POINT_BELOW = "No point below"
MINIMUM_REQUIREMENT = "Minimum requirement"


def _num(value) -> float | None:
    return None if value is None else float(value)


def out_of_spec(
    readings: Iterable[Mapping],
    lo,
    hi,
    *,
    eps: float,
) -> list[dict]:
    """Every reading below ``lo`` (LOW) or above ``hi`` (HIGH).

    ``readings`` carry ``value``, ``point_code``, ``logical_vehicle_id`` and
    (T68) ``measured_date``, copied through unchanged; a reading without one
    gets None. LOW is ``value < lo - eps``; HIGH is ``value > hi + eps`` and
    only when ``hi`` is not None. A value exactly on a line is inside. Sorted
    LOW first, then by value; T68 breaks a tie on value by ``measured_date``
    (None last) then ``point_code``, because the readings arrive in no fixed
    order. With no line at all the list is empty. Nothing is de-duplicated.
    """
    low, high = _num(lo), _num(hi)
    found = []
    for r in readings:
        v = float(r["value"])
        if low is not None and v < low - eps:
            side = "LOW"
        elif high is not None and v > high + eps:
            side = "HIGH"
        else:
            continue
        found.append(
            {
                "value": Decimal(r["value"]),
                "side": side,
                "point_code": r["point_code"],
                "logical_vehicle_id": r["logical_vehicle_id"],
                "measured_date": r.get("measured_date"),
            }
        )
    found.sort(
        key=lambda p: (
            0 if p["side"] == "LOW" else 1,
            p["value"],
            p["measured_date"] is None,
            p["measured_date"] or date.min,
            p["point_code"],
        )
    )
    return found


def line_labels(layer_code: str, lo, hi, target) -> dict:
    """``lo_label`` / ``hi_label`` / ``target_label`` (D-67-05).

    Clear: No point below / -- / Minimum requirement (Clear has no Maximum).
    Other layers: Minimum / Maximum / --. A label is None when its value is.
    """
    if layer_code == CLEAR:
        return {
            "lo_label": NO_POINT_BELOW if lo is not None else None,
            "hi_label": None,
            "target_label": MINIMUM_REQUIREMENT if target is not None else None,
        }
    return {
        "lo_label": MINIMUM if lo is not None else None,
        "hi_label": MAXIMUM if hi is not None else None,
        "target_label": None,
    }


def _dec(rule: Mapping | None, key: str) -> Decimal | None:
    if rule is None or rule.get(key) is None:
        return None
    return Decimal(rule[key])


def _null_last(value) -> tuple:
    return (value is None, value if value is not None else 0)


def color_sequence(
    colours: Iterable[Mapping],
    base_rules: Mapping[str, Mapping[str, Mapping | None]],
) -> list[dict]:
    """One colour order for the whole response (T73 D-73-10..12).

    ``colours`` carry ``color_name``, ``family_code``, ``family_name`` and
    ``family_order`` (one entry per colour). ``base_rules[color_name]`` maps
    ``"H"`` / ``"V"`` to the BASE rule that applies (the caller's
    ``effective_rule`` over one ``latest()`` read), or None. This module
    holds no micron number; every value comes from those rules.

    Key, ascending, each part with null after any number: Base H lo, Base H
    hi, Base V lo, Base V hi, family_order, color_name (code-point order).
    Compared as exact Decimals. Horizontal is primary; Vertical only breaks
    ties. A colour with no Base rule sorts after every laddered colour, by
    family order then name. Returns entries in rank order, rank 1-based,
    dense and unique.
    """
    entries = []
    for c in colours:
        name = c["color_name"]
        rules = base_rules.get(name) or {}
        h, v = rules.get("H"), rules.get("V")
        lines = {
            "base_lo_h": _dec(h, "lo"),
            "base_hi_h": _dec(h, "hi"),
            "base_lo_v": _dec(v, "lo"),
            "base_hi_v": _dec(v, "hi"),
        }
        entries.append(
            {
                "color_name": name,
                "family_code": c.get("family_code"),
                "family_name": c.get("family_name"),
                "family_order": c.get("family_order"),
                **lines,
                "ladder": (
                    LADDER_BASE
                    if any(x is not None for x in lines.values())
                    else LADDER_NONE
                ),
            }
        )
    entries.sort(
        key=lambda e: (
            _null_last(e["base_lo_h"]),
            _null_last(e["base_hi_h"]),
            _null_last(e["base_lo_v"]),
            _null_last(e["base_hi_v"]),
            _null_last(e["family_order"]),
            e["color_name"],
        )
    )
    return [{"rank": i, **e} for i, e in enumerate(entries, start=1)]
