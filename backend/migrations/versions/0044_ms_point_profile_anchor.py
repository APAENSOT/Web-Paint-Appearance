"""Model Studio: 3D inspection-point profiles (point storage).

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-13

One new table and nothing else. Additive: no existing table, row or grant
changes.

``point_profile_anchor`` -- where one Standard point sits on the registered
3D body, for the reusable default layout of one **plant x canonical model x
measurement domain**. Colour and month are deliberately not in the key: every
colour and month at the plant reads the same layout. **Append-only** (ADR
0005, the ``color_appearance`` shape): saving or removing one point's location
is a new row with that point's next ``revision``; a removal is a tombstone row
(``action = 'remove'``), never a DELETE. The latest revision of each point
wins. ``UNIQUE (plant_code, model_code, domain, point_key, revision)`` is the
atomic per-anchor lost-update check: two writes against the same revision of
the same point cannot both land.

``point_key`` is the authoritative Point Check identity in that domain:
``ref_plant_ws_point.zone_code`` for Wave Scan, ``ref_plant_film_point.
point_code`` for Film. The application validates it against the live list;
there is no FK because the two lists are different tables.

Coordinates are mesh-local (asset version + source mesh name + XYZ + unit
normal). The CHECKs refuse a half-filled row, a non-finite or absurd number
and a normal that is not unit length, as a last line behind the API.

Grants, exactly: ``app_rw`` SELECT, INSERT (+ the sequence). No UPDATE, no
DELETE. Read back off the catalog below and refused otherwise.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"
TABLE = "point_profile_anchor"
SEQ = "point_profile_anchor_anchor_event_id_seq"
GRANTS = {"SELECT", "INSERT"}
ACTION = "catalogue.point_profile_anchor.create"

_GEOMETRY = ("asset_version", "mesh_name", "pos_x", "pos_y", "pos_z",
             "nrm_x", "nrm_y", "nrm_z")
_NUMBERS = ("pos_x", "pos_y", "pos_z", "nrm_x", "nrm_y", "nrm_z")


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
    placed = " AND ".join(
        [f"{c} IS NOT NULL" for c in _GEOMETRY]
        # BETWEEN is false for NaN and +/-Infinity, so this also means "finite".
        + [f"{c} BETWEEN -1000 AND 1000" for c in _NUMBERS]
        + ["abs(sqrt(nrm_x * nrm_x + nrm_y * nrm_y + nrm_z * nrm_z) - 1) <= 0.001"]
    )
    removed = " AND ".join(f"{c} IS NULL" for c in (*_GEOMETRY, "body_zone"))
    op.execute(
        f"""
        CREATE TABLE {TABLE} (
            anchor_event_id bigserial PRIMARY KEY,
            plant_code    text NOT NULL REFERENCES ref_plant (plant_code),
            model_code    text NOT NULL REFERENCES ref_model (model_code),
            domain        text NOT NULL CHECK (domain IN ('wavescan', 'film')),
            point_key     text NOT NULL CHECK (point_key <> ''),
            revision      integer NOT NULL CHECK (revision >= 1),
            action        text NOT NULL CHECK (action IN ('place', 'remove')),
            asset_version text,
            mesh_name     text,
            body_zone     text,
            pos_x double precision, pos_y double precision, pos_z double precision,
            nrm_x double precision, nrm_y double precision, nrm_z double precision,
            created_by    uuid REFERENCES app_user (id),
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT {TABLE}_revision_key
                UNIQUE (plant_code, model_code, domain, point_key, revision),
            CONSTRAINT {TABLE}_shape CHECK (
                (action = 'place' AND {placed}) OR (action = 'remove' AND {removed})
            )
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {TABLE} IS "
        f"'Model Studio point storage. Reusable default 3D layout per plant x "
        f"canonical model x domain (wavescan | film), shared by every colour and "
        f"month. Append-only: a save or a removal is a new row with that point''s "
        f"next revision (removal = tombstone), never an UPDATE or DELETE; the "
        f"latest revision wins. UNIQUE (plant, model, domain, point_key, "
        f"revision) is the per-anchor lost-update check. point_key = zone_code "
        f"(wavescan) or point_code (film).'"
    )
    op.execute(f"REVOKE ALL ON {TABLE} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {SEQ} TO {APP_ROLE}")

    grants = _grants(conn)
    if grants != GRANTS:
        raise RuntimeError(
            f"Point storage refused: {APP_ROLE} holds {grants} on {TABLE}, "
            f"expected exactly {GRANTS}. The transaction is rolled back."
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
                    "revision": "0044",
                    "table": TABLE,
                    "rows": 0,
                    "owner_decision": "Model Studio point storage, approved 2026-10-13",
                }
            ),
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    kept = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    if kept:
        raise RuntimeError(
            f"{kept} point anchor row(s) exist. Each is a location a person "
            f"saved (ADR 0005); downgrading would drop it. Decide what to do "
            f"with them first."
        )
    op.execute(f"DROP TABLE {TABLE}")
