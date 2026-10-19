"""FVL leftover programs CX743 / V363: own catalogues, J73 pattern.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-22

Not a DELETE. Adds two FVL leftover models with 32-zone catalogues whose
``zone_code`` is the Panel cell (numbers kept). Does not map them onto the
P703 Ranger 32-set. Does not set ``grading_family``. Does not write
``ref_model_alias`` (plant-scoped teach stays Engineer apply so AAT fixtures
with Style/Model CX743 stay UNKNOWN_MODEL).
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import op
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.fvl_leftover_identity import (  # noqa: E402
    CX743_PANELS,
    V363_PANELS,
    leftover_checkzones,
)

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(
        "INSERT INTO ref_model (model_code, model_family, body_style, "
        "expected_zone_count) VALUES "
        "('CX743', 'CX743', 'SUV', 32), "
        "('V363', 'V363', 'SUV', 32) "
        "ON CONFLICT (model_code) DO NOTHING"
    ))
    for zone_code, zone_name, panel_group, tolerance in leftover_checkzones():
        conn.execute(
            text(
                "INSERT INTO ref_checkzone "
                "(zone_code, zone_name, panel_group, tolerance_group) "
                "VALUES (:c, :n, :g, :t) ON CONFLICT (zone_code) DO NOTHING"
            ),
            {"c": zone_code, "n": zone_name, "g": panel_group, "t": tolerance},
        )
    for model, panels in (("CX743", CX743_PANELS), ("V363", V363_PANELS)):
        for zone_no, raw in panels:
            conn.execute(
                text(
                    "INSERT INTO ref_model_zone (model_code, zone_code, zone_no) "
                    "VALUES (:m, :z, :n) ON CONFLICT (model_code, zone_code) "
                    "DO NOTHING"
                ),
                {"m": model, "z": raw, "n": zone_no},
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DELETE FROM ref_model_zone WHERE model_code IN ('CX743', 'V363')"))
    conn.execute(text("DELETE FROM ref_model WHERE model_code IN ('CX743', 'V363')"))
    for zone_code, _name, _group, _tol in leftover_checkzones():
        conn.execute(
            text(
                "DELETE FROM ref_checkzone z WHERE z.zone_code = :c "
                "AND NOT EXISTS (SELECT 1 FROM ref_model_zone m "
                "WHERE m.zone_code = z.zone_code)"
            ),
            {"c": zone_code},
        )
