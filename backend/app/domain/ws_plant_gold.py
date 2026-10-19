"""WaveScan plant gold: identity is the plant's own panel text (T58).

T58-CONTEXT D-58-01..08. The FilmThickness rule (`ref_plant_film_point`)
for WaveScan: each plant x model keeps its own list of checkpoint names.

* **Identity** is the panel text the plant wrote (``1HOOD``,
  ``01RHS Hood Rr28``, ``RRHOOD`` for the AAT/FTM long-form catalogue).
* **The leading number is walk proof only** (D-58-02). It never joins two
  plants, two models, or a leftover and Ranger: FVL Ranger ``11ROOF`` and
  CX743 ``11LFRTDOOR`` share a number and nothing else.
* **Zero pad** (D-58-03): at one plant x model ``1HOOD`` and ``01HOOD`` are
  the same point. Only leading zeros of the leading number are dropped; the
  number itself is never stripped, so ``11ROOF`` is not ``14ROOF``.
* **Hor/Ver** (D-58-04) is a property of that name: Hood / Roof / Floor in
  the name, any case, is Horizontal; everything else Vertical.

Pure: no FastAPI, no psycopg.
"""

from __future__ import annotations

import re

from app.domain.references import normalise_alias

_LEADING_ZEROS = re.compile(r"^0+(?=\d)")

#: D-58-04: the name families that are horizontal panels.
HORIZONTAL_WORDS = ("HOOD", "ROOF", "FLOOR")


def gold_key(label: str) -> str:
    """The comparison key for a panel name at one plant x model (D-58-03).

    ``normalise_alias`` (trim + casefold), then leading zeros of the leading
    number removed: ``01HOOD`` and ``1HOOD`` share ``1hood``; ``11ROOF``
    stays ``11roof``; ``RRHOOD`` stays ``rrhood``.
    """
    return _LEADING_ZEROS.sub("", normalise_alias(label))


def ws_tolerance(zone_code: str) -> str:
    """Horizontal for a Hood / Roof / Floor name (any case), else Vertical.

    The same rule as `ref_checkzone.ck_zone_rule` after revision 0022.
    """
    upper = str(zone_code).upper()
    return "Horizontal" if any(w in upper for w in HORIZONTAL_WORDS) else "Vertical"


#: (keyword, panel_group), first match wins. Display grouping only --
#: Hor/Ver comes from `ws_tolerance`, never from this table.
_PANEL_WORDS: tuple[tuple[str, str], ...] = (
    ("HOOD", "HOOD"),
    ("ROOF", "ROOF"),
    ("FLOOR", "BOX"),
    ("PILLAR", "PILLAR"),
    ("POST", "PILLAR"),
    ("LIFTGATE", "LIFTGATE"),
    ("LIFGATE", "LIFTGATE"),
    ("SWING", "LIFTGATE"),
    ("TAIL", "TAILGATE"),
    ("TGATE", "TAILGATE"),
    # T88 (Part 3): SAP's J73 writes the tailgate as `TG` joined to the
    # position -- `LHSTGTOP`, `RHSTGBOT`, `TGMIDDLE`. The bare `TG` below is
    # matched as a standalone WORD on purpose (it is two letters, and
    # loosening it to a substring would catch any name containing t-g), so
    # those five never classified and `rank_candidates` silently dropped
    # them. Widened by naming the joined forms, never by loosening `TG`.
    ("TGTOP", "TAILGATE"),
    ("TGBOT", "TAILGATE"),
    ("TGMID", "TAILGATE"),
    ("TG", "TAILGATE"),
    ("FEND", "FENDER"),
    # T88 (Part 3): AAT's U704 spells it `FEN` -- `FRFENRH1`, `RRFENHIRH`,
    # and the aliases "21 Rr Fen Low RH". `FEND` above keeps matching first,
    # so every name that classified before still classifies the same way.
    ("FEN", "FENDER"),
    ("QTR", "FENDER"),
    ("BOX", "BOX"),
    ("BOOX", "BOX"),
    ("DOO", "DOOR"),
    ("FD", "DOOR"),
    ("RD", "DOOR"),
)


def ws_panel_match(label: str) -> tuple[str, str]:
    """The matched keyword and the panel family, first match wins.

    T90 needs the **keyword** as well as the family, so a side hint can be
    read from the letters in front of the family word and nowhere else:
    ``LCROOF`` carries a side and ``ROOF`` does not, and reading the first
    letter of the whole name would make every roof a right-hand panel. The
    loop is the one :func:`ws_panel_group` has always run, lifted out
    unchanged, so no name classifies differently than it did before.
    """
    compact = re.sub(r"[^A-Z]", "", str(label).upper())
    words = set(re.findall(r"[A-Z]+", str(label).upper()))
    for keyword, group in _PANEL_WORDS:
        if keyword in ("TG", "FD", "RD"):
            if keyword in words:
                return keyword, group
        elif keyword in compact:
            return keyword, group
    raise ValueError(f"cannot classify panel {label!r}")


def ws_panel_group(label: str) -> str:
    """A display family for a plant panel name (``ref_checkzone.panel_group``)."""
    return ws_panel_match(label)[1]


__all__ = [
    "HORIZONTAL_WORDS",
    "gold_key",
    "ws_panel_group",
    "ws_panel_match",
    "ws_tolerance",
]
