"""T116: colour appearance profiles for Model Studio.

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-12

One new table and nothing else (D-116-4, D-116-8):

``color_appearance`` -- the body shade Model Studio paints for one plant x
canonical colour, shared by every model and month. **Append-only** (ADR
0005, the ``ws_point_setting`` / ``film_point_setting`` shape): a save is a
new row with the next ``revision``; the latest revision wins. ``UNIQUE
(plant_code, color_name, revision)`` is the atomic lost-update check -- two
saves against the same revision cannot both land (D-116-7). ``hex`` is
``#RRGGBB`` uppercase, normalised by the application (D-116-5).

Grants, exactly: ``app_rw`` SELECT, INSERT (+ the sequence). No UPDATE, no
DELETE. Read back off the catalog below and refused otherwise. No row is
written into the new table; no other table changes.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"
TABLE = "color_appearance"
SEQ = "color_appearance_appearance_id_seq"
GRANTS = {"SELECT", "INSERT"}
ACTION = "catalogue.color_appearance.create"


def _grants(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.table_privileges "
                "WHERE grantee = :role AND table_schema = 'public' AND table_name = :t"
            ),
            {"role": APP_ROLE, "t": TABLE},
        ).all()
    }


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(
        f"""
        CREATE TABLE {TABLE} (
            appearance_id bigserial PRIMARY KEY,
            plant_code    text NOT NULL REFERENCES ref_plant (plant_code),
            color_name    text NOT NULL REFERENCES ref_color (color_name),
            revision      integer NOT NULL CHECK (revision >= 1),
            hex           text NOT NULL CHECK (hex ~ '^#[0-9A-F]{{6}}$'),
            created_by    uuid REFERENCES app_user (id),
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT {TABLE}_revision_key UNIQUE (plant_code, color_name, revision)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {TABLE} IS "
        f"'T116 (D-116-4). Model Studio body shade per plant x canonical colour, "
        f"shared by every model and month. Append-only: a save is a new row with "
        f"the next revision, never an UPDATE; the latest revision wins. The UNIQUE "
        f"(plant_code, color_name, revision) is the lost-update check. A merged "
        f"name keeps its rows; its canonical colour reads them as inherited until "
        f"it has its own (D-116-2).'"
    )
    op.execute(f"REVOKE ALL ON {TABLE} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {SEQ} TO {APP_ROLE}")

    grants = _grants(conn)
    if grants != GRANTS:
        raise RuntimeError(
            f"T116 refused: {APP_ROLE} holds {grants} on {TABLE}, expected "
            f"exactly {GRANTS} (D-116-4). The transaction is rolled back."
        )
    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, :t, 'ALL', NULL, "
            "        CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "t": TABLE,
            "after": json.dumps(
                {
                    "revision": "0039",
                    "table": TABLE,
                    "rows": 0,
                    "owner_decision": "T116 D-116-1..D-116-8, 2026-10-12",
                }
            ),
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    kept = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    if kept:
        raise RuntimeError(
            f"{kept} colour appearance row(s) exist. Each is a decision a person "
            f"saved (ADR 0005); downgrading would drop it. Decide what to do with "
            f"them first."
        )
    op.execute(f"DROP TABLE {TABLE}")
