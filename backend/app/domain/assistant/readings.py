"""AR05 per-reading record: one row per value, tagged with the AR04 box it belongs to.

Pure: no SQL. Built by ``services/assistant.load_month``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.domain.history import week_of

WS_METRICS = ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b")

_LEAD = re.compile(r"^(\d*)([LR])(?!H)(.+)$")
_TOKEN = re.compile(r"([LR])H(\d*)$")


@dataclass(frozen=True)
class Reading:
    domain: str
    layer: str | None
    model: str
    color: str
    family: str | None
    orient: str
    point: str | None
    car: str | None
    date: date | None
    metric: str
    value: float
    out: bool | None
    box_key: str
    job_no: str | None = None  # Film only: the car number is cut from it (car rule)
    measurement: str | None = None  # Wave Scan only: the measurement id, to pair CF with its bands


def side_panel(name: str | None) -> tuple[str, str] | None:
    """Spec §12 O1: (side, panel) from a point name, or None for centre points."""
    if not name:
        return None
    if m := _LEAD.match(name):
        return m.group(2), m.group(3)
    if m := _TOKEN.search(name):
        return m.group(1), name[: m.start()] + m.group(2)
    return None


def week_of_reading(d: date | None, month_only: bool = False) -> int:
    """Week band 1-5 within the month; 0 = day not recorded."""
    return 0 if d is None or month_only else week_of(d)
