"""T114: Point Check, Wave Scan -- counted, extra, retire, add.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-12

T109 (0035) gave Film its Point Check. This revision gives Wave Scan the
structures the same page needs, and nothing else:

**1. The extra tag** (D-114-5). ``ref_plant_ws_point.is_extra``, default
false, and **no existing point is extra**: the owner said every live point
today is the plant's standard list. Every point added from Point Check after
this revision is written extra by the application.

**2. Counted** (D-114-2). ``ws_point_setting`` is append-only, the Film
``film_point_setting`` shape without an H/V column -- a Wave Scan point's
Horizontal / Vertical is fixed by its name (``ck_zone_rule``) and is never
edited. Latest row wins; **no row means counted**, so nothing changes until a
person writes one.

**3. One shared "counted readings" source** (D-114-12).
``v_wavescan_counted`` is ``v_wavescan_active`` narrowed to readings whose
point is **live** and **counted** at its plant x model. It reads *through*
the active view, so the active-data predicate is still written once
(``01-DATA-MODEL.md`` section 10). The dashboard reads it; History,
Comparison, the measurements list and corrections keep the active view and
therefore every reading. Today every live reading (2,494, all FTM) joins a
live point and no setting row exists, so the view returns exactly the active
view's rows -- asserted below.

**4. Grants** (D-114-11), exactly: ``app_rw`` SELECT, INSERT on
``ws_point_setting`` (+ its sequence); INSERT on ``ref_plant_ws_point``,
``ref_checkzone`` and ``ref_model_zone`` (Point Check's add, D-114-6);
SELECT on the view. The column UPDATE on ``ref_plant_ws_point (retired_at,
retired_reason)`` from 0031 stays; **no** UPDATE of any other column and
**no** DELETE anywhere. Read back off the catalog below and refused
otherwise.

**Nothing is switched off, retired, added or tagged here.** The live lists
are AAT 32 / 32 / 31, FTM 32 / 32, FVL 32 / 32 / 32, SAP 32 / 32 / 32 before
and after.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"

#: Measured 2026-10-12 (T114 section 1), re-checked before anything is written.
LIVE = {
    ("AAT", "P703 DBL RANGER"): 32,
    ("AAT", "P703 DBL SUPER DUTY"): 32,
    ("AAT", "U704"): 31,
    ("FTM", "P703 DBL RANGER"): 32,
    ("FTM", "P703 DBL RAPTOR"): 32,
    ("FVL", "CX743"): 32,
    ("FVL", "P703 DBL RANGER"): 32,
    ("FVL", "V363"): 32,
    ("SAP", "J73 DBL"): 32,
    ("SAP", "P703 DBL RANGER"): 32,
    ("SAP", "P703 DBL RAPTOR"): 32,
}

SETTING_TABLE = "ws_point_setting"
SETTING_SEQ = "ws_point_setting_setting_id_seq"
SETTING_INDEX = "ix_ws_point_setting_latest"
COUNTED_VIEW = "v_wavescan_counted"
ACTIVE_VIEW = "v_wavescan_active"

#: 0031's retire grant, unchanged by this revision.
RETIRE_COLUMNS = ("retired_at", "retired_reason")

#: D-114-11: what app_rw holds on every object this task touches, exactly.
GRANTS = {
    SETTING_TABLE: {"SELECT", "INSERT"},
    "ref_plant_ws_point": {"SELECT", "INSERT"},
    "ref_checkzone": {"SELECT", "INSERT"},
    "ref_model_zone": {"SELECT", "INSERT"},
    COUNTED_VIEW: {"SELECT"},
}

ACTION = "catalogue.ws_point.point_check"


def _live_counts(conn) -> dict[tuple[str, str], int]:
    return {
        (r[0], r[1]): int(r[2])
        for r in conn.execute(
            text(
                "SELECT plant_code, model_code, count(*) FROM ref_plant_ws_point "
                "WHERE retired_at IS NULL GROUP BY 1, 2"
            )
        ).all()
    }


def _ddl() -> None:
    op.execute(
        "ALTER TABLE ref_plant_ws_point "
        "ADD COLUMN is_extra boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "COMMENT ON COLUMN ref_plant_ws_point.is_extra IS "
        "'T114 (D-114-5). This point is beyond the plant''s standard Wave "
        "Scan list for the model. No point was extra when the column was "
        "added (owner, 2026-10-12: every live point is the standard list); "
        "every point added on Point Check is written extra. A tag, not a "
        "grade: it changes no reading and refuses nothing.'"
    )
    op.execute(
        f"""
        CREATE TABLE {SETTING_TABLE} (
            setting_id  bigserial PRIMARY KEY,
            plant_code  text NOT NULL,
            model_code  text NOT NULL,
            zone_code   text NOT NULL,
            counted     boolean NOT NULL,
            reason      text NOT NULL CHECK (length(btrim(reason)) > 0),
            created_by  uuid REFERENCES app_user (id),
            created_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT {SETTING_TABLE}_point_fkey
                FOREIGN KEY (plant_code, model_code, zone_code)
                REFERENCES ref_plant_ws_point (plant_code, model_code, zone_code)
        )
        """
    )
    op.execute(
        f"CREATE INDEX {SETTING_INDEX} ON {SETTING_TABLE} "
        f"(plant_code, model_code, zone_code, setting_id DESC)"
    )
    op.execute(
        f"COMMENT ON TABLE {SETTING_TABLE} IS "
        f"'T114 (D-114-2). Whether one Wave Scan point of a plant x model "
        f"counts on the dashboard. Append-only: a change is a new row with "
        f"its reason and its person, never an UPDATE; the latest row wins and "
        f"no row means counted. No H/V column -- a Wave Scan point''s "
        f"Horizontal / Vertical is fixed by its name (ck_zone_rule).'"
    )
    # D-114-12. Through the active view, never beside it: the predicate stays
    # in one place and this only narrows it to live, counted points.
    op.execute(
        f"""
        CREATE VIEW {COUNTED_VIEW} AS
        SELECT w.*
          FROM {ACTIVE_VIEW} w
          JOIN ref_plant_ws_point p
            ON p.plant_code = w.plant
           AND p.model_code = w.model
           AND p.zone_code = w.checkzone
           AND p.retired_at IS NULL
          LEFT JOIN LATERAL (
               SELECT s.counted
                 FROM {SETTING_TABLE} s
                WHERE s.plant_code = p.plant_code
                  AND s.model_code = p.model_code
                  AND s.zone_code = p.zone_code
                ORDER BY s.setting_id DESC
                LIMIT 1
               ) s ON true
         WHERE COALESCE(s.counted, true)
        """
    )
    op.execute(
        f"COMMENT ON VIEW {COUNTED_VIEW} IS "
        f"'T114 (D-114-12). The Wave Scan readings the dashboard counts: "
        f"{ACTIVE_VIEW} rows whose point is live (not retired) and counted "
        f"(latest ws_point_setting, no row = counted) at its plant x model. "
        f"History, Comparison, the measurements list and corrections read "
        f"{ACTIVE_VIEW} and keep every reading.'"
    )

    op.execute(f"REVOKE ALL ON {SETTING_TABLE} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON {SETTING_TABLE} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {SETTING_SEQ} TO {APP_ROLE}")
    op.execute(f"GRANT INSERT ON ref_plant_ws_point TO {APP_ROLE}")
    op.execute(f"GRANT INSERT ON ref_checkzone TO {APP_ROLE}")
    op.execute(f"GRANT INSERT ON ref_model_zone TO {APP_ROLE}")
    op.execute(f"REVOKE ALL ON {COUNTED_VIEW} FROM PUBLIC")
    op.execute(f"GRANT SELECT ON {COUNTED_VIEW} TO {APP_ROLE}")


def _guard(conn) -> None:
    live = _live_counts(conn)
    if live != LIVE:
        raise RuntimeError(
            f"T114 refused: the live Wave Scan lists are {live}, expected "
            f"{LIVE} (measured 2026-10-12). Nothing was changed. Re-measure and "
            f"explain it in docs/reports/T114-POINT-CHECK-WAVESCAN.md first."
        )


def _grants(conn) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {name: set() for name in GRANTS}
    for table, privilege in conn.execute(
        text(
            "SELECT table_name, privilege_type "
            "  FROM information_schema.table_privileges "
            " WHERE grantee = :role AND table_schema = 'public' "
            "   AND table_name = ANY(:tables)"
        ),
        {"role": APP_ROLE, "tables": list(GRANTS)},
    ).all():
        out[table].add(privilege)
    return out


def upgrade() -> None:
    conn = op.get_bind()
    _guard(conn)
    before_live = _live_counts(conn)
    active = conn.execute(text(f"SELECT count(*) FROM {ACTIVE_VIEW}")).scalar_one()
    _ddl()

    # --- post-asserts ---------------------------------------------------
    extras = conn.execute(
        text("SELECT count(*) FROM ref_plant_ws_point WHERE is_extra")
    ).scalar_one()
    if extras:
        raise RuntimeError(
            f"T114 refused: {extras} Wave Scan point(s) carry the extra tag; "
            f"D-114-5 says none does. The transaction is rolled back."
        )
    if _live_counts(conn) != before_live:
        raise RuntimeError(
            "T114 refused: a live Wave Scan list changed. This revision adds "
            "and retires nothing. The transaction is rolled back."
        )
    counted = conn.execute(text(f"SELECT count(*) FROM {COUNTED_VIEW}")).scalar_one()
    if counted != active:
        raise RuntimeError(
            f"T114 refused: {COUNTED_VIEW} returns {counted} readings and "
            f"{ACTIVE_VIEW} {active}. Every point is counted today and every "
            f"live reading joins a live point, so the dashboard would move. "
            f"The transaction is rolled back."
        )
    grants = _grants(conn)
    if grants != GRANTS:
        raise RuntimeError(
            f"T114 refused: {APP_ROLE} holds {grants}, expected exactly "
            f"{GRANTS} (D-114-11). The transaction is rolled back."
        )
    updatable = sorted(
        r[0]
        for r in conn.execute(
            text(
                "SELECT column_name FROM information_schema.column_privileges "
                "WHERE table_name = 'ref_plant_ws_point' AND grantee = :role "
                "  AND privilege_type = 'UPDATE'"
            ),
            {"role": APP_ROLE},
        ).all()
    )
    if updatable != sorted(RETIRE_COLUMNS):
        raise RuntimeError(
            f"T114 refused: {APP_ROLE} may UPDATE {updatable} of "
            f"ref_plant_ws_point, expected exactly {sorted(RETIRE_COLUMNS)}. "
            f"The transaction is rolled back."
        )

    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'ref_plant_ws_point', 'ALL', "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            # Counts only, as 0035 / 0036: an out-of-line audit value raises
            # on this cluster (T77).
            "before": json.dumps({"live": sum(before_live.values()), "active": int(active)}),
            "after": json.dumps(
                {
                    "revision": "0037",
                    "live": sum(before_live.values()),
                    "extra": 0,
                    "setting_table": SETTING_TABLE,
                    "counted_view": COUNTED_VIEW,
                    "counted_readings": int(counted),
                    "owner_decision": "T114 D-114-1..D-114-13, 2026-10-12",
                }
            ),
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    kept = conn.execute(text(f"SELECT count(*) FROM {SETTING_TABLE}")).scalar_one()
    extra = conn.execute(
        text("SELECT count(*) FROM ref_plant_ws_point WHERE is_extra")
    ).scalar_one()
    retired = conn.execute(
        text(
            "SELECT count(*) FROM ref_plant_ws_point "
            "WHERE retired_reason LIKE 'T114%'"
        )
    ).scalar_one()
    if kept or extra or retired:
        raise RuntimeError(
            f"Point Check has been used: {kept} counted row(s), {extra} added "
            f"point(s), {retired} retire(s). Each one is a decision a person "
            f"made (ADR 0005); downgrading would drop or orphan it. Decide what "
            f"to do with them first."
        )
    op.execute(f"DROP VIEW {COUNTED_VIEW}")
    op.execute(f"DROP TABLE {SETTING_TABLE}")
    op.execute("ALTER TABLE ref_plant_ws_point DROP COLUMN is_extra")
    op.execute(f"REVOKE INSERT ON ref_plant_ws_point FROM {APP_ROLE}")
    op.execute(f"REVOKE INSERT ON ref_checkzone FROM {APP_ROLE}")
    op.execute(f"REVOKE INSERT ON ref_model_zone FROM {APP_ROLE}")
