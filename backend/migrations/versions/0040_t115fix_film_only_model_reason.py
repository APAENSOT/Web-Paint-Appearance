"""T115-FIX: `reject_log.reject_reason` gains `FILM_ONLY_MODEL`.

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-12

A Wave Scan row whose model is Film-only (RAPCAP, Single CAP; T46 F5) was
held `MODEL_NOT_OFFERED`, the same code as a model Removed from the plant's
list. T115 made Attach reload `MODEL_NOT_OFFERED` sheets and told the
uploader an Attach loads them -- untrue for a Film-only model, which no
Attach turns into a Wave Scan vehicle. It now gets its own code
(D-115F-1), its own sentence, and is never reloaded by an Attach.

Measured 2026-10-12 on t02_dev: 0 `MODEL_NOT_OFFERED` rows, so no stored
row is relabelled. Only the CHECK list changes; ADR 0005 is untouched.

Downgrade refuses while any `FILM_ONLY_MODEL` row exists, rather than
relabelling it.
"""

from __future__ import annotations

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

REJECT_REASONS_0016 = (
    "UNKNOWN_PLANT",
    "UNKNOWN_MODEL",
    "UNKNOWN_CHECKZONE",
    "UNKNOWN_COLOR",
    "UNKNOWN_PAINTLINE",
    "ZONE_NOT_VALID_FOR_MODEL",
    "MISSING_MEASUREMENT",
    "MISSING_REQUIRED_FIELD",
    "BAD_DATE",
    "BAD_NUMBER",
    "OUT_OF_RANGE",
    "DUPLICATE_ROW",
    "OTHER",
    "TEMPLATE_UNKNOWN",
    "HEADER_AMBIGUOUS",
    "UNMAPPED_COLUMN",
    "COLOR_NOT_OFFERED",
    "MODEL_NOT_OFFERED",
    "PLANT_MISMATCH",
)
REJECT_REASONS = REJECT_REASONS_0016 + ("FILM_ONLY_MODEL",)


def _reject_check(reasons: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{r}'" for r in reasons)
    op.execute("ALTER TABLE reject_log DROP CONSTRAINT IF EXISTS ck_reject_reason")
    op.execute(
        f"ALTER TABLE reject_log ADD CONSTRAINT ck_reject_reason "
        f"CHECK (reject_reason IN ({listed}))"
    )


def upgrade() -> None:
    _reject_check(REJECT_REASONS)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM reject_log WHERE reject_reason = 'FILM_ONLY_MODEL') THEN
                RAISE EXCEPTION 'reject_log has FILM_ONLY_MODEL rows; downgrade would have to relabel them';
            END IF;
        END $$;
        """
    )
    _reject_check(REJECT_REASONS_0016)
