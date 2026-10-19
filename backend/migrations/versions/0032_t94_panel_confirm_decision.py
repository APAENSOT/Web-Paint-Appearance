"""T94: let the confirm worksheet record which panel a rough label is.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-09

D-94-1 makes a panel label **rough** when its name, leading number dropped,
does not identify exactly one canonical panel of that ``(plant, model)``:
``01HOOD`` fits five hoods, and ``06``/``07``/``08LFFENDER`` all reduce to
``lffender``. D-94-2 then says a rough label is **never** ready, whatever the
catalogue holds -- including when a panel exists spelled exactly like it.
Such a row loads only after a person says, in that row, which panel it is.

That answer has to be stored somewhere, and this revision says where: a
fourth ``worksheet_decision`` kind, ``PANEL_CONFIRM``, whose ``subject`` is
the pair ``<panel as the file wrote it>=><canonical zone_code>``.

**Why ``worksheet_decision`` and not a reference table.** It is the T39
answer table: append-only, scoped to one ``load_id``, re-applied on every
replay of that sheet, audited through ``audit_event``. A rough label must
never become a permanent alias -- the month the plant reshuffles its walk a
learned ``01HOOD -> RRHOOD`` would file a hood as the wrong hood with no
error anywhere (D-90-3, D-91-3) -- and this table is structurally incapable
of becoming one: ``domain/cleaner.py`` resolves a panel from
``ReferenceData``, ``load_reference_data`` builds that from ``ref_*`` tables
alone, and neither can reach a ``worksheet_decision`` row. The confirmation
is handed to the cleaner **per batch**, by the replay of that batch, and by
nothing else. That is the same guarantee D-90-11 chose, kept by construction
rather than by promise.

**Additive and non-destructive.** One CHECK constraint is replaced by the
same constraint with one more allowed value. No row is read, written or
deleted; no column, index, grant or comment changes. Every existing
``IGNORE_HEADER``, ``PLANT_CONFIRM`` and ``HOLE_APPROVAL`` row stays valid
under both the old and the new constraint, so the downgrade is safe exactly
while no ``PANEL_CONFIRM`` row exists -- and it says so rather than deleting
one to make room.
"""

from __future__ import annotations

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

TABLE = "worksheet_decision"
CONSTRAINT = "worksheet_decision_kind_check"

#: The three T39 kinds, and T94's fourth.
OLD_KINDS = ("IGNORE_HEADER", "PLANT_CONFIRM", "HOLE_APPROVAL")
NEW_KIND = "PANEL_CONFIRM"


def _check(kinds: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{kind}'" for kind in kinds)
    return (
        f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}; "
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} "
        f"CHECK (kind IN ({allowed}))"
    )


def upgrade() -> None:
    op.execute(_check((*OLD_KINDS, NEW_KIND)))
    op.execute(
        "COMMENT ON COLUMN worksheet_decision.subject IS "
        "'What was decided: a column header (IGNORE_HEADER), a Plant cell "
        "(PLANT_CONFIRM), a source row (HOLE_APPROVAL), or T94''s pair "
        "''<panel as written>=><canonical zone_code>'' (PANEL_CONFIRM).'"
    )


def downgrade() -> None:
    # A PANEL_CONFIRM row is an answer a person gave about a real upload.
    # Dropping back to the three kinds while one exists would make the table
    # unreadable by its own constraint, and deleting it to make room would be
    # the silent loss ADR 0005 exists to prevent. So this refuses instead.
    op.execute(
        f"""
        DO $$
        DECLARE kept bigint;
        BEGIN
            SELECT count(*) INTO kept FROM {TABLE}
             WHERE kind = '{NEW_KIND}';
            IF kept > 0 THEN
                RAISE EXCEPTION
                    '% {NEW_KIND} worksheet_decision row(s) exist. '
                    'Downgrading 0032 would make them violate the kind '
                    'constraint, and they are answers a person gave about '
                    'an upload. Remove the uploads they belong to first.',
                    kept;
            END IF;
        END $$;
        """
    )
    op.execute(_check(OLD_KINDS))
    op.execute(
        "COMMENT ON COLUMN worksheet_decision.subject IS NULL"
    )
