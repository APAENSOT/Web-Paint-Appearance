"""FVL leftover programs keep their own 32-zone catalogues.

CX743 (liftgate / quarter) and V363 (swing-gate) are not Ranger. G1 D-07
quarantined them from the P703 32-set. This module is the J73 pattern for
FVL: one model, 32 checkpoints, zone_code is the file Panel cell with the
leading number kept (FVL labels collide if the number is stripped: two
roofs, two hoods). Mapping a leftover Style cell onto Ranger remains
forbidden; mapping it onto these catalogues is identity.

No FastAPI, no psycopg.
"""

from __future__ import annotations

# (raw_position, Panel cell as CF_Aug.xlsx sheet 8 writes it)
CX743_PANELS: tuple[tuple[int, str], ...] = (
    (1, "1HOOD"),
    (2, "2HOOD"),
    (3, "3HOOD"),
    (4, "4HOOD"),
    (5, "5HOOD"),
    (6, "06LFFENDER"),
    (7, "07LFFENDER"),
    (8, "08LFFENDER"),
    (9, "09LFFTDOOR"),
    (10, "10LFFTDOOR"),
    (11, "11LFRTDOOR"),
    (12, "12LFRTDOOR"),
    (13, "13LFRQTR"),
    (14, "14LFRQTR"),
    (15, "15LFRQTR"),
    (16, "16ROOF"),
    (17, "17LIFGATE"),
    (18, "18LIFTGATE"),
    (19, "19LIFTGATE"),
    (20, "20LIFTGATE"),
    (21, "21LIFTGATE"),
    (22, "22RTRQTR"),
    (23, "23RTRQTR"),
    (24, "24RTRQTR"),
    (25, "25RTRDOOR"),
    (26, "26RTRDOOR"),
    (27, "27RTFTDOOR"),
    (28, "28RTFTDOOR"),
    (29, "29RTFENDER"),
    (30, "30RTFENDER"),
    (31, "31RTFENDER"),
    (32, "32ROOF"),
)

V363_PANELS: tuple[tuple[int, str], ...] = (
    (1, "1HOOD"),
    (2, "2HOOD"),
    (3, "3HOOD"),
    (4, "4HOOD"),
    (5, "5HOOD"),
    (6, "06LFFTFENDER"),
    (7, "07LFFTFENDER"),
    (8, "08LFFTFENDER"),
    (9, "09LFFTDOOR"),
    (10, "10LFFTDOOR"),
    (11, "11LFROOF"),
    (12, "12LFRDOOR"),
    (13, "13LFRQTR"),
    (14, "14LFRQTR"),
    (15, "15LFRQTR"),
    (16, "16LFRQTR"),
    (17, "17SWINGGAT"),
    (18, "18SWINGGAT"),
    (19, "19SWINGGAT"),
    (20, "20SWINGGAT"),
    (21, "21SWINGGAT"),
    (22, "22RTRQTR"),
    (23, "23RTRQTR"),
    (24, "24RTRQTR"),
    (25, "25RTRQTR"),
    (26, "26RTRDOOR"),
    (27, "27RTROOF"),
    (28, "28RTRDOOR"),
    (29, "29RTRDOOR"),
    (30, "30RTFTFENDER"),
    (31, "31RTFTFENDER"),
    (32, "32RTFTFENDER"),
)


def leftover_panel_group(raw: str) -> str:
    upper = raw.upper()
    if "HOOD" in upper:
        return "HOOD"
    if "ROOF" in upper:
        return "ROOF"
    if "FENDER" in upper:
        return "FENDER"
    if "QTR" in upper:
        return "FENDER"
    if "PILLAR" in upper or "POST" in upper:
        return "PILLAR"
    if "BOX" in upper:
        return "BOX"
    if "TGATE" in upper:
        return "TAILGATE"
    if "LIFTGATE" in upper or "LIFGATE" in upper or "SWING" in upper:
        return "LIFTGATE"
    if "DOOR" in upper:
        return "DOOR"
    raise ValueError(f"cannot classify leftover panel {raw!r}")


def leftover_tolerance(zone_code: str) -> str:
    upper = zone_code.upper()
    if "HOOD" in upper or "ROOF" in upper:
        return "Horizontal"
    return "Vertical"


def leftover_checkzones() -> tuple[tuple[str, str, str, str], ...]:
    """Union of leftover Panel cells as (zone_code, zone_name, panel_group, tolerance)."""
    seen: dict[str, tuple[str, str, str, str]] = {}
    for _pos, raw in CX743_PANELS + V363_PANELS:
        if raw in seen:
            continue
        group = leftover_panel_group(raw)
        seen[raw] = (raw, raw, group, leftover_tolerance(raw))
    return tuple(seen.values())
