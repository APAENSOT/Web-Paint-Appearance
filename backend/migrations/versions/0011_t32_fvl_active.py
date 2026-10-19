"""T32: onboard FVL loads after G2 (Serial and Paintline).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-21

Opens FVL loads. Not a DELETE of measurements or maps.

G2 is the September FVL WaveScan export (`CF_Sep.xlsx`, T28 SHA-256
``e3ecc6a7e209f262eeb0906aae71edc31b6b27fbe0d3d13a611448ce9d0f6a34``):
every leaf row carries Serial No **and** Paintline. G1 FVL maps are already
proved (T31). This revision:

1. Sets ``ref_plant.is_active = true`` for FVL so uploads are no longer
   refused at the onboarding gate.
2. Inserts the identity plant alias ``FVL`` → ``FVL``. Revision 0002
   omitted that row on purpose ("FVL uploads are not accepted until D5").
   The cleaner resolves Plant cells only through ``ref_plant_alias``, so
   without this insert every FVL row would be ``UNKNOWN_PLANT``. The
   spelling is the seeded plant code, not an invented site name.

**Not destructive.** No measurement or map row is removed. ``zone_code``
is untouched. Jan–Aug historical files still lack identity and remain
non-committable (``VEHICLE_IDENTITY_MISSING`` / ``PAINTLINE_MISSING``)
even after this flag flips. The owner's commit message must name that
this opens FVL loads (``AGENTS.md`` section 2).
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE ref_plant SET is_active = true WHERE plant_code = 'FVL'"
    )
    op.execute(
        """
        INSERT INTO ref_plant_alias (raw_value, plant_code)
        VALUES ('FVL', 'FVL')
        ON CONFLICT (raw_value) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ref_plant_alias WHERE raw_value = 'FVL' AND plant_code = 'FVL'"
    )
    op.execute(
        "UPDATE ref_plant SET is_active = false WHERE plant_code = 'FVL'"
    )
