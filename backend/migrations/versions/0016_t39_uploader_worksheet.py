"""T39: the uploader worksheet contract (ADR 0013).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-28

Three changes, none of them a DELETE of facts:

1. **`wavescan` measures other than CF may be NULL.** ADR 0013: a point
   loads with date, model, colour, checkzone and CF. DOI, DU and Wa-We are
   optional; LW and SW load NULL only after an Engineer approves that
   point's holes. ``cf`` stays NOT NULL. The existing range CHECKs already
   pass a NULL. Nothing is back-filled and no value is changed.

2. **`reject_log.reject_reason` gains `PLANT_MISMATCH`.** A Plant cell that
   names another plant than the upload page is held and asked about
   (ADR 0013 decision 3), not refused for the whole request and never
   relabelled silently.

3. **`worksheet_decision`**, append-only. What the Engineer said about one
   sheet so replay can re-apply it: ``IGNORE_HEADER`` (a column we do not
   use), ``PLANT_CONFIRM`` (this Plant text means the page plant),
   ``HOLE_APPROVAL`` (this source row may load without LW/SW). ``app_rw``
   gets SELECT, INSERT only -- a decision is changed by making a newer one.
   The FK cascades from ``load_batch`` because only ``purge_workbook``
   (ADR 0011, SECURITY DEFINER) can delete a batch; no role gains DELETE.

Downgrade refuses while any NULL measure or PLANT_MISMATCH reject exists,
rather than choosing values for them.
"""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

#: Measures that may now be NULL. CF is not in this list.
NULLABLE_MEASURES = ("lw", "sw", "doi", "du", "wa", "wb", "wc", "wd", "we")

REJECT_REASONS_0014 = (
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
)
REJECT_REASONS = REJECT_REASONS_0014 + ("PLANT_MISMATCH",)

DECISION_KINDS = ("IGNORE_HEADER", "PLANT_CONFIRM", "HOLE_APPROVAL")


def _for_each_role(sql: str) -> None:
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                {sql.format(role=role)}
            END $$;
            """
        )


def _reject_check(reasons: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{r}'" for r in reasons)
    op.execute("ALTER TABLE reject_log DROP CONSTRAINT IF EXISTS ck_reject_reason")
    op.execute(
        f"ALTER TABLE reject_log ADD CONSTRAINT ck_reject_reason "
        f"CHECK (reject_reason IN ({listed}))"
    )


def upgrade() -> None:
    for column in NULLABLE_MEASURES:
        op.execute(f"ALTER TABLE wavescan ALTER COLUMN {column} DROP NOT NULL")
    op.execute(
        "COMMENT ON COLUMN wavescan.doi IS "
        "'ADR 0013: optional. NULL when the export has no DOI.'"
    )
    op.execute(
        "COMMENT ON COLUMN wavescan.lw IS "
        "'ADR 0013: NULL only when an Engineer approved this point without LW/SW "
        "(worksheet_decision HOLE_APPROVAL). Never invented.'"
    )

    _reject_check(REJECT_REASONS)

    kinds = ", ".join(f"'{k}'" for k in DECISION_KINDS)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS worksheet_decision (
            decision_id    bigserial PRIMARY KEY,
            load_id        bigint NOT NULL
                               REFERENCES load_batch (load_id) ON DELETE CASCADE,
            kind           text NOT NULL CHECK (kind IN ({kinds})),
            subject        text NOT NULL CHECK (length(btrim(subject)) > 0),
            actor_user_id  uuid NOT NULL REFERENCES app_user (id),
            note           text,
            created_at     timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_worksheet_decision_load "
        "ON worksheet_decision (load_id, kind)"
    )
    op.execute(
        "COMMENT ON TABLE worksheet_decision IS "
        "'ADR 0013: what the Engineer confirmed about one sheet, re-applied on "
        "every replay. INSERT only. Cascades only through purge_workbook.'"
    )
    op.execute("REVOKE ALL ON worksheet_decision FROM PUBLIC")
    _for_each_role(
        """
        GRANT SELECT, INSERT ON worksheet_decision TO {role};
        GRANT USAGE, SELECT ON SEQUENCE worksheet_decision_decision_id_seq TO {role};
        """
    )


def downgrade() -> None:
    nulls = " OR ".join(f"{c} IS NULL" for c in NULLABLE_MEASURES)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM wavescan WHERE {nulls}) THEN
                RAISE EXCEPTION 'wavescan has NULL optional measures; downgrade would have to invent values';
            END IF;
            IF EXISTS (SELECT 1 FROM reject_log WHERE reject_reason = 'PLANT_MISMATCH') THEN
                RAISE EXCEPTION 'reject_log has PLANT_MISMATCH rows; downgrade would have to relabel them';
            END IF;
        END $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS worksheet_decision")
    _reject_check(REJECT_REASONS_0014)
    for column in NULLABLE_MEASURES:
        op.execute(f"ALTER TABLE wavescan ALTER COLUMN {column} SET NOT NULL")
