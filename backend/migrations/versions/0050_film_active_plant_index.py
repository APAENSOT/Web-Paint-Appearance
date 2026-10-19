"""Index the active Film readings by plant, model and point.

Every Film read filters `filmthickness_active` by plant, and the table had no
plant index, so each one scanned all 140k rows. The landing status call runs
dozens of these: with this index it went from 2.2 s to 0.7 s on a copy of
t02_dev (2026-10-20). Index only: no row, view or grant changes.
"""
from __future__ import annotations

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ft_plant_active "
        "ON filmthickness (plant, model, point_code) "
        "WHERE NOT is_duplicate AND NOT is_superseded"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_ft_plant_active")
