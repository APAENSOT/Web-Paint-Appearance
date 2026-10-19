"""AR02: AAT pairing keys (car-number rule and panel map).

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-13

Extends AR01's reference tables to AAT; no new table, no fact written
(ADR 0005):

* both ``pair_group`` CHECKs gain ``LIFTGATE`` (14 codes, D-AR02-6);
* ``ref_plant_film_car_rule``: AAT ``^(\\d{7}) `` -- the 7 digits at the start
  of ``job_no`` followed by a space (D-AR02-1);
* ``ref_pair_ws_zone`` / ``ref_pair_film_point``: AAT rows generated from the
  **live** lists and matched exactly (AR02 tables A and B). P703 DBL SUPER DUTY
  Wave Scan zones map like Ranger's (D-AR02-3); AAT's P703 film list has no
  C-pillar point, so those groups get Wave Scan zones only (D-AR02-2). A film
  point's panel is its code with the leading digits stripped (``TGATE`` is not
  ``TGATEIN``; ``LIFTGAT...`` is not ``LIFTGATE...``).

Every count is asserted; any difference rolls the revision back. FTM rows are
untouched. ``app_rw`` stays SELECT only (read back). One ``audit_event``
(``catalogue.pairing.seed``, entity AAT, counts only).

Downgrade deletes only AAT's rows from the three tables (reference rows this
revision added) and restores the 13-code CHECKs; it refuses while any non-AAT
row uses ``LIFTGATE`` (D-AR02-7). The audit row stays.
"""

from __future__ import annotations

import json
import re

from alembic import op
from sqlalchemy import text

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"
PLANT = "AAT"
PATTERN = r"^(\d{7}) "
RULE_NOTE = (
    "AR02 (owner 2026-10-12, D-AR02-1): AAT job_no starts with the 7-digit car number "
    "and a space; the capture group is the car number"
)
ACTION = "catalogue.pairing.seed"
TABLES = ["ref_plant_film_car_rule", "ref_pair_ws_zone", "ref_pair_film_point"]
CHECKS = {
    "ref_pair_ws_zone": "ref_pair_ws_zone_pair_group_check",
    "ref_pair_film_point": "ref_pair_film_point_pair_group_check",
}
OLD_GROUPS = sorted([
    "HOOD", "ROOF", "L_FENDER", "R_FENDER", "L_FRONT_DOOR", "R_FRONT_DOOR",
    "L_REAR_DOOR", "R_REAR_DOOR", "L_C_PILLAR", "R_C_PILLAR",
    "L_BOX_SIDE", "R_BOX_SIDE", "TAILGATE",
])
NEW_GROUPS = sorted([*OLD_GROUPS, "LIFTGATE"])

#: Table A: Wave Scan zone -> pair group, P703 DBL RANGER and P703 DBL SUPER DUTY.
P703_WS = {
    **dict.fromkeys(["RRHOOD", "RFHOOD", "CFHOOD", "LFHOOD", "LRHOOD"], "HOOD"),
    **dict.fromkeys(["LCROOF", "RCROOF"], "ROOF"),
    **dict.fromkeys(["LFFENDER", "LCFENDER", "LRFENDER"], "L_FENDER"),
    **dict.fromkeys(["RRFENDER", "RCFENDER", "RFFENDER"], "R_FENDER"),
    **dict.fromkeys(["LTFDOOR", "LCFDOOR"], "L_FRONT_DOOR"),
    **dict.fromkeys(["RCFDOOR", "FTFDOOR"], "R_FRONT_DOOR"),
    "LCRDOOR": "L_REAR_DOOR",
    "RCRDOOR": "R_REAR_DOOR",
    "LCPILLAR": "L_C_PILLAR",
    "RCPILLAR": "R_C_PILLAR",
    **dict.fromkeys(["LFBOX", "LCBOX", "LRBOX"], "L_BOX_SIDE"),
    **dict.fromkeys(["RRBOX", "RCBOX", "RFBOX"], "R_BOX_SIDE"),
    **dict.fromkeys(
        ["LTTAILGATE", "LBTAILGATE", "LCTAILGATE", "RBTAILGATE", "RTTAILGATE"], "TAILGATE"
    ),
}
#: Table A: film panel -> pair group, P703 DBL RANGER (no C-pillar point at AAT).
P703_FILM = {
    "HOOD": "HOOD", "ROOF": "ROOF", "LTFEND": "L_FENDER", "RTFEND": "R_FENDER",
    "LTFTDOOR": "L_FRONT_DOOR", "RTFTDOOR": "R_FRONT_DOOR",
    "LTRRDOOR": "L_REAR_DOOR", "RTRRDOOR": "R_REAR_DOOR",
    "LBOXSIDE": "L_BOX_SIDE", "RBOXSIDE": "R_BOX_SIDE", "TGATE": "TAILGATE",
}
#: Table B: Wave Scan zone -> pair group, U704.
U704_WS = {
    **dict.fromkeys(["RRHOOD", "RFHOOD", "CFHOOD", "LFHOOD", "LRHOOD"], "HOOD"),
    **dict.fromkeys(["LCROOF", "RCROOF"], "ROOF"),
    **dict.fromkeys(["LFFENDER", "LCFENDER", "LRFENDER"], "L_FENDER"),
    **dict.fromkeys(["FRFENRH1", "FRFENRH2", "FRFENRH3"], "R_FENDER"),
    **dict.fromkeys(["LTFDOOR", "LCFDOOR"], "L_FRONT_DOOR"),
    **dict.fromkeys(["FRDOORMIDRH", "FRDOORHIRH"], "R_FRONT_DOOR"),
    "LCRDOOR": "L_REAR_DOOR",
    "RRDOORMIDRH": "R_REAR_DOOR",
    **dict.fromkeys(
        ["LIFTGATEHILH", "LIFTGATELOWLH", "LIFTGATELOWRH", "LIFTGATEHIRH"], "LIFTGATE"
    ),
}
#: Table B: film panel -> pair group, U704.
U704_FILM = {
    "HOOD": "HOOD",
    **dict.fromkeys(["ROOFLH", "ROOFCTR", "ROOFRH"], "ROOF"),
    "LTFEND": "L_FENDER",
    **dict.fromkeys(["FRFENLOWRH", "FRFENMEDRH", "FRFENHIRH"], "R_FENDER"),
    "LTFTDOOR": "L_FRONT_DOOR",
    **dict.fromkeys(["FRDOORMEDRH", "FRDOORHIRH", "FRDOORLOWRH"], "R_FRONT_DOOR"),
    **dict.fromkeys(["RRDOORHILH", "RRDOORLOWLH", "RRDOORMEDLH"], "L_REAR_DOOR"),
    **dict.fromkeys(["RRDOORHIRH", "RRDOORMEDRH", "RRDOORLOWRH"], "R_REAR_DOOR"),
    **dict.fromkeys(
        ["LIFTGATHILH", "LIFTGATHICR", "LIFTGATHIRH", "LIFTGATLOWLH", "LIFTGATLOWRH"], "LIFTGATE"
    ),
}
#: model -> (Wave Scan zone map, film panel map). Super Duty has no film list.
MAPS = {
    "P703 DBL RANGER": (P703_WS, P703_FILM),
    "P703 DBL SUPER DUTY": (P703_WS, {}),
    "U704": (U704_WS, U704_FILM),
}
assert sorted(set(P703_WS.values())) == OLD_GROUPS
assert sorted(set(U704_WS.values())) == sorted(set(U704_FILM.values()))

#: Revision asserts (AR02 section 2), re-measured live 2026-10-13.
EXPECTED = {"ref_plant_film_car_rule": 1, "ref_pair_ws_zone": 87, "ref_pair_film_point": 152}
FTM_EXPECTED = {"ref_plant_film_car_rule": 1, "ref_pair_ws_zone": 64, "ref_pair_film_point": 158}
WS_PER_MODEL = {"P703 DBL RANGER": 32, "P703 DBL SUPER DUTY": 32, "U704": 23}
FILM_PER_MODEL = {"P703 DBL RANGER": 78, "U704": 74}
UNMAPPED_ZONES = {"U704": {
    "LCPILLAR", "RRPILLARRH", "RFENDERHILH", "RFENDERMIDLH", "RFENDERLOWLH",
    "RRFENHIRH", "RRFENMIDRH", "RRFENLOWRH",
}}
UNMAPPED_FILM_PER_MODEL = {"P703 DBL RANGER": 16, "U704": 21}


def _counts(conn, plant: str) -> dict[str, int]:
    return {
        t: conn.execute(text(f"SELECT count(*) FROM {t} WHERE plant_code = :p"), {"p": plant})
        .scalar_one()
        for t in TABLES
    }


def _grants(conn, table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.table_privileges "
                "WHERE grantee = :role AND table_schema = 'public' AND table_name = :t"
            ),
            {"role": APP_ROLE, "t": table},
        ).all()
    }


def _check_codes(conn, table: str) -> list[str]:
    definition = conn.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :c"),
        {"c": CHECKS[table]},
    ).scalar_one()
    return sorted(re.findall(r"'([A-Z_]+)'", definition))


def _set_checks(groups: list[str]) -> None:
    codes = ", ".join(f"'{g}'" for g in groups)
    for table, name in CHECKS.items():
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT {name}, "
            f"ADD CONSTRAINT {name} CHECK (pair_group IN ({codes}))"
        )


def refuse_foreign_liftgate(conn) -> None:
    """Downgrade guard (D-AR02-7): LIFTGATE may only be dropped while AAT alone uses it."""
    rows = conn.execute(
        text(
            "SELECT 'ref_pair_ws_zone', plant_code, model_code, zone_code FROM ref_pair_ws_zone "
            " WHERE pair_group = 'LIFTGATE' AND plant_code <> :p "
            "UNION ALL "
            "SELECT 'ref_pair_film_point', plant_code, model_code, point_code "
            "  FROM ref_pair_film_point WHERE pair_group = 'LIFTGATE' AND plant_code <> :p "
            "ORDER BY 1, 2, 3, 4 LIMIT 5"
        ),
        {"p": PLANT},
    ).all()
    if rows:
        raise RuntimeError(
            f"AR02 downgrade refused: non-{PLANT} rows use LIFTGATE, e.g. "
            f"{[tuple(r) for r in rows]}. Remove them by migration first."
        )


def upgrade() -> None:
    conn = op.get_bind()
    _set_checks(NEW_GROUPS)

    conn.execute(
        text("INSERT INTO ref_plant_film_car_rule (plant_code, pattern, note) VALUES (:p, :r, :n)"),
        {"p": PLANT, "r": PATTERN, "n": RULE_NOTE},
    )
    for model, (ws_map, film_map) in MAPS.items():
        conn.execute(
            text(
                """
                INSERT INTO ref_pair_ws_zone (plant_code, model_code, zone_code, pair_group)
                SELECT p.plant_code, p.model_code, p.zone_code, m.value
                  FROM ref_plant_ws_point p
                  JOIN jsonb_each_text(CAST(:map AS jsonb)) m ON m.key = p.zone_code
                 WHERE p.plant_code = :p AND p.model_code = :m AND p.retired_at IS NULL
                """
            ),
            {"map": json.dumps(ws_map), "p": PLANT, "m": model},
        )
        conn.execute(
            text(
                """
                INSERT INTO ref_pair_film_point (plant_code, model_code, point_code, pair_group)
                SELECT p.plant_code, p.model_code, p.point_code, m.value
                  FROM ref_plant_film_point p
                  JOIN jsonb_each_text(CAST(:map AS jsonb)) m
                    ON m.key = regexp_replace(p.point_code, '^[0-9]+', '')
                 WHERE p.plant_code = :p AND p.model_code = :m AND p.retired_at IS NULL
                """
            ),
            {"map": json.dumps(film_map), "p": PLANT, "m": model},
        )

    found = _counts(conn, PLANT)
    ftm = _counts(conn, "FTM")
    ws_per_model = dict(conn.execute(
        text("SELECT model_code, count(*) FROM ref_pair_ws_zone WHERE plant_code = :p GROUP BY 1"),
        {"p": PLANT},
    ).all())
    film_per_model = dict(conn.execute(
        text("SELECT model_code, count(*) FROM ref_pair_film_point WHERE plant_code = :p "
             "GROUP BY 1"),
        {"p": PLANT},
    ).all())
    unmapped_zones: dict[str, set[str]] = {}
    for model, zone in conn.execute(
        text(
            "SELECT p.model_code, p.zone_code FROM ref_plant_ws_point p "
            "  LEFT JOIN ref_pair_ws_zone z USING (plant_code, model_code, zone_code) "
            " WHERE p.plant_code = :p AND p.retired_at IS NULL AND z.zone_code IS NULL"
        ),
        {"p": PLANT},
    ).all():
        unmapped_zones.setdefault(model, set()).add(zone)
    unmapped_points = dict(conn.execute(
        text(
            "SELECT p.model_code, count(*) FROM ref_plant_film_point p "
            "  LEFT JOIN ref_pair_film_point m USING (plant_code, model_code, point_code) "
            " WHERE p.plant_code = :p AND p.retired_at IS NULL AND m.point_code IS NULL "
            " GROUP BY 1"
        ),
        {"p": PLANT},
    ).all())
    ftfdoor = conn.execute(
        text(
            "SELECT model_code, pair_group FROM ref_pair_ws_zone "
            " WHERE plant_code = :p AND zone_code = 'FTFDOOR' ORDER BY model_code"
        ),
        {"p": PLANT},
    ).all()
    film_pillars = conn.execute(
        text("SELECT count(*) FROM ref_pair_film_point WHERE plant_code = :p "
             "   AND pair_group IN ('L_C_PILLAR', 'R_C_PILLAR')"),
        {"p": PLANT},
    ).scalar_one()
    liftgate = conn.execute(
        text(
            "SELECT DISTINCT plant_code, model_code FROM ("
            "  SELECT plant_code, model_code FROM ref_pair_ws_zone WHERE pair_group = 'LIFTGATE' "
            "  UNION ALL "
            "  SELECT plant_code, model_code FROM ref_pair_film_point WHERE pair_group = 'LIFTGATE'"
            ") x ORDER BY 1, 2"
        )
    ).all()
    car = conn.execute(
        text("SELECT substring('2494614 U704 A4D' FROM pattern) FROM ref_plant_film_car_rule "
             " WHERE plant_code = :p"),
        {"p": PLANT},
    ).scalar_one()

    problems = []
    if found != EXPECTED:
        problems.append(f"AAT row counts {found}, expected {EXPECTED}")
    if ftm != FTM_EXPECTED:
        problems.append(f"FTM row counts {ftm}, expected {FTM_EXPECTED} (unchanged)")
    if ws_per_model != WS_PER_MODEL:
        problems.append(f"Wave Scan rows per model {ws_per_model}, expected {WS_PER_MODEL}")
    if film_per_model != FILM_PER_MODEL:
        problems.append(f"film rows per model {film_per_model}, expected {FILM_PER_MODEL}")
    if unmapped_zones != UNMAPPED_ZONES:
        problems.append(f"unmapped live zones {unmapped_zones}, expected {UNMAPPED_ZONES}")
    if unmapped_points != UNMAPPED_FILM_PER_MODEL:
        problems.append(
            f"unmapped live film points {unmapped_points}, expected {UNMAPPED_FILM_PER_MODEL}"
        )
    p703 = ["P703 DBL RANGER", "P703 DBL SUPER DUTY"]
    if [tuple(r) for r in ftfdoor] != [(m, "R_FRONT_DOOR") for m in p703]:
        problems.append(f"FTFDOOR maps to {[tuple(r) for r in ftfdoor]}, not R_FRONT_DOOR")
    if film_pillars:
        problems.append(f"{film_pillars} AAT film point(s) in a C-pillar group")
    if [tuple(r) for r in liftgate] != [(PLANT, "U704")]:
        problems.append(f"LIFTGATE is used by {[tuple(r) for r in liftgate]}, not AAT U704 only")
    if car != "2494614":
        problems.append(f"the AAT rule reads '2494614 U704 A4D' as {car!r}, not '2494614'")
    for table in CHECKS:
        if _check_codes(conn, table) != NEW_GROUPS:
            problems.append(f"{CHECKS[table]} lists {_check_codes(conn, table)}")
    for table in TABLES:
        if _grants(conn, table) != {"SELECT"}:
            problems.append(f"{APP_ROLE} holds {_grants(conn, table)} on {table}, not SELECT only")
    if problems:
        raise RuntimeError(
            "AR02 refused: " + "; ".join(problems) + ". The transaction is rolled back."
        )

    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'ref_pair', :plant, NULL, "
            "        CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "plant": PLANT,
            "after": json.dumps(
                {"revision": "0045", "models": list(MAPS), "rows": found,
                 "pair_groups": len(NEW_GROUPS),
                 "owner_decision": "AR02 D-AR02-1..D-AR02-7, 2026-10-12"}
            ),
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    refuse_foreign_liftgate(conn)
    for table in reversed(TABLES):
        conn.execute(text(f"DELETE FROM {table} WHERE plant_code = :p"), {"p": PLANT})
    _set_checks(OLD_GROUPS)
