"""FilmThickness micron standard precedence (T62, D-FS-05). Pure.

A rule is one ``film_standard`` row: ``layer_code``, ``color_name`` (None =
plant-wide), ``orient``, ``lo`` / ``hi`` / ``target`` and ``created_at``.
This module only *chooses* the rule that applies to a reading; it holds no
micron number and never grades -- D1 is open and ``domain/grading.py`` is
the one grading implementation.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from app.domain.film_header import LAYER_CODES

#: The four FilmBuild layers, the same vocabulary the ingest writes.
LAYERS = LAYER_CODES


def _latest(rows: list[Mapping]) -> Mapping | None:
    if not rows:
        return None
    return max(rows, key=lambda row: (row["created_at"], str(row.get("id") or "")))


def effective_rule(
    rules: Iterable[Mapping],
    *,
    layer_code: str,
    color_name: str | None,
    orient: str,
) -> Mapping | None:
    """The rule a reading at (layer, colour, orient) is held to, or None.

    ``rules`` are one plant's rows (the caller filters by plant; this never
    looks further). The latest per-colour row wins; otherwise the latest
    plant-wide row (``color_name is None``); otherwise there is no standard.
    There is no fallback to another colour, a family, or another plant.
    """
    matching = [
        rule for rule in rules
        if rule["layer_code"] == layer_code and rule["orient"] == orient
    ]
    if color_name is not None:
        own = _latest([rule for rule in matching if rule["color_name"] == color_name])
        if own is not None:
            return own
    return _latest([rule for rule in matching if rule["color_name"] is None])
