"""AR01: Wave Scan <-> Film pairing keys (car-number rule and panel map).

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-12

Three reference tables, read at query time; no fact is written (ADR 0005):

``ref_plant_film_car_rule`` -- per plant, the regex whose first capture group
is the car number inside a film ``job_no`` (D-AR01-1). One seed row: FTM.
A plant with no row has no film car number; nothing is guessed.

``ref_pair_ws_zone`` / ``ref_pair_film_point`` -- the side + panel map
(D-AR01-3, D-AR01-4). Seeded from the **live** FTM lists of P703 DBL RANGER
and P703 DBL RAPTOR (D-AR01-9): every live Wave Scan zone gets its group; a
film point's group is its code with the leading digits stripped, matched
exactly (``TGATE`` is mapped, ``TGATEIN`` is not). FTFDOOR -> R_FRONT_DOOR
(owner). The counts are asserted; any difference rolls the revision back.

Grants: ``app_rw`` SELECT only on all three -- no API writes them; changing
the map is a migration. One ``audit_event`` (``catalogue.pairing.seed``,
counts only). Downgrade drops the three tables; the audit row stays.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"
PLANT = "FTM"
MODELS = ["P703 DBL RANGER", "P703 DBL RAPTOR"]
PATTERN = r"^[A-Z]{2}_[A-Z]{2,3}_(\d{7})$"
RULE_NOTE = (
    "AR01 (owner 2026-10-12, D-AR01-1): FTM job_no is <colour>_<model>_<7-digit car>; "
    "the capture group is the car number"
)
ACTION = "catalogue.pairing.seed"
TABLES = ["ref_plant_film_car_rule", "ref_pair_ws_zone", "ref_pair_film_point"]

#: Wave Scan zone -> pair group (AR01 section 2, the panel map).
WS_ZONES = {
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
#: Film panel (point code without its leading digits) -> pair group.
FILM_PANELS = {
    "HOOD": "HOOD", "ROOF": "ROOF", "LTFEND": "L_FENDER", "RTFEND": "R_FENDER",
    "LTFTDOOR": "L_FRONT_DOOR", "RTFTDOOR": "R_FRONT_DOOR",
    "LTRRDOOR": "L_REAR_DOOR", "RTRRDOOR": "R_REAR_DOOR",
    "LCPILLAR": "L_C_PILLAR", "RCPILLAR": "R_C_PILLAR",
    "LBOXSIDE": "L_BOX_SIDE", "RBOXSIDE": "R_BOX_SIDE", "TGATE": "TAILGATE",
}
PAIR_GROUPS = sorted(set(WS_ZONES.values()))
assert PAIR_GROUPS == sorted(set(FILM_PANELS.values())) and len(PAIR_GROUPS) == 13

#: Revision asserts (AR01 section 2), measured 2026-10-12.
EXPECTED = {"ref_plant_film_car_rule": 1, "ref_pair_ws_zone": 64, "ref_pair_film_point": 158}
UNMAPPED_FILM_PER_MODEL = 19


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


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


def upgrade() -> None:
    conn = op.get_bind()
    groups = ", ".join(f"'{g}'" for g in PAIR_GROUPS)
    op.execute(
        """
        CREATE TABLE ref_plant_film_car_rule (
            plant_code text PRIMARY KEY REFERENCES ref_plant (plant_code),
            pattern    text NOT NULL CHECK (length(pattern) > 0),
            note       text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ref_pair_ws_zone (
            plant_code text NOT NULL,
            model_code text NOT NULL,
            zone_code  text NOT NULL,
            pair_group text NOT NULL CHECK (pair_group IN ({groups})),
            PRIMARY KEY (plant_code, model_code, zone_code),
            FOREIGN KEY (plant_code, model_code, zone_code)
                REFERENCES ref_plant_ws_point (plant_code, model_code, zone_code)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ref_pair_film_point (
            plant_code text NOT NULL,
            model_code text NOT NULL,
            point_code text NOT NULL,
            pair_group text NOT NULL CHECK (pair_group IN ({groups})),
            PRIMARY KEY (plant_code, model_code, point_code),
            FOREIGN KEY (plant_code, model_code, point_code)
                REFERENCES ref_plant_film_point (plant_code, model_code, point_code)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_plant_film_car_rule IS 'AR01 (D-AR01-1). Per plant, the regex "
        "whose first capture group is the car number in a film job_no, read at query time. "
        "No row: no film car number, nothing guessed.'"
    )
    op.execute(
        "COMMENT ON TABLE ref_pair_ws_zone IS 'AR01 (D-AR01-3/4). Wave Scan zone -> side + "
        "panel pair group. Changing the map is a migration.'"
    )
    op.execute(
        "COMMENT ON TABLE ref_pair_film_point IS 'AR01 (D-AR01-3/4). Film point -> side + "
        "panel pair group. Changing the map is a migration.'"
    )
    for table in TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON {table} TO {APP_ROLE}")
        if _grants(conn, table) != {"SELECT"}:
            raise RuntimeError(
                f"AR01 refused: {APP_ROLE} holds {_grants(conn, table)} on {table}, "
                f"expected exactly {{'SELECT'}}. The transaction is rolled back."
            )

    conn.execute(
        text("INSERT INTO ref_plant_film_car_rule (plant_code, pattern, note) VALUES (:p, :r, :n)"),
        {"p": PLANT, "r": PATTERN, "n": RULE_NOTE},
    )
    conn.execute(
        text(
            """
            INSERT INTO ref_pair_ws_zone (plant_code, model_code, zone_code, pair_group)
            SELECT p.plant_code, p.model_code, p.zone_code, m.value
              FROM ref_plant_ws_point p
              JOIN jsonb_each_text(CAST(:map AS jsonb)) m ON m.key = p.zone_code
             WHERE p.plant_code = :p AND p.model_code = ANY(:models) AND p.retired_at IS NULL
            """
        ),
        {"map": json.dumps(WS_ZONES), "p": PLANT, "models": MODELS},
    )
    conn.execute(
        text(
            """
            INSERT INTO ref_pair_film_point (plant_code, model_code, point_code, pair_group)
            SELECT p.plant_code, p.model_code, p.point_code, m.value
              FROM ref_plant_film_point p
              JOIN jsonb_each_text(CAST(:map AS jsonb)) m
                ON m.key = regexp_replace(p.point_code, '^[0-9]+', '')
             WHERE p.plant_code = :p AND p.model_code = ANY(:models) AND p.retired_at IS NULL
            """
        ),
        {"map": json.dumps(FILM_PANELS), "p": PLANT, "models": MODELS},
    )

    found = {t: _count(conn, t) for t in TABLES}
    unmapped_zones = conn.execute(
        text(
            "SELECT count(*) FROM ref_plant_ws_point p "
            "  LEFT JOIN ref_pair_ws_zone z USING (plant_code, model_code, zone_code) "
            " WHERE p.plant_code = :p AND p.model_code = ANY(:models) "
            "   AND p.retired_at IS NULL AND z.zone_code IS NULL"
        ),
        {"p": PLANT, "models": MODELS},
    ).scalar_one()
    unmapped_points = dict(conn.execute(
        text(
            "SELECT p.model_code, count(*) FROM ref_plant_film_point p "
            "  LEFT JOIN ref_pair_film_point m USING (plant_code, model_code, point_code) "
            " WHERE p.plant_code = :p AND p.model_code = ANY(:models) "
            "   AND p.retired_at IS NULL AND m.point_code IS NULL GROUP BY 1"
        ),
        {"p": PLANT, "models": MODELS},
    ).all())
    ftfdoor = conn.execute(
        text(
            "SELECT model_code, pair_group FROM ref_pair_ws_zone "
            " WHERE plant_code = :p AND zone_code = 'FTFDOOR' ORDER BY model_code"
        ),
        {"p": PLANT},
    ).all()
    car = conn.execute(
        text("SELECT substring('AW_RB_1970561' FROM pattern) FROM ref_plant_film_car_rule")
    ).scalar_one()
    problems = []
    if found != EXPECTED:
        problems.append(f"row counts {found}, expected {EXPECTED}")
    if unmapped_zones:
        problems.append(f"{unmapped_zones} live Wave Scan zone(s) have no pair group")
    if unmapped_points != dict.fromkeys(MODELS, UNMAPPED_FILM_PER_MODEL):
        problems.append(
            f"unmapped live film points per model are {unmapped_points}, "
            f"expected {UNMAPPED_FILM_PER_MODEL} each"
        )
    if [tuple(r) for r in ftfdoor] != [(m, "R_FRONT_DOOR") for m in MODELS]:
        problems.append(f"FTFDOOR maps to {[tuple(r) for r in ftfdoor]}, not R_FRONT_DOOR")
    if car != "1970561":
        problems.append(f"the FTM rule reads AW_RB_1970561 as {car!r}, not '1970561'")
    if problems:
        raise RuntimeError(
            "AR01 refused: " + "; ".join(problems) + ". The transaction is rolled back."
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
                {"revision": "0043", "models": MODELS, "rows": found,
                 "owner_decision": "AR01 D-AR01-1..D-AR01-10, 2026-10-12"}
            ),
        },
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
