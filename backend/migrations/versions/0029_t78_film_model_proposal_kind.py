"""T78/T61: allow ``proposed_mapping.kind = 'FILM_MODEL'``.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-07

D-78-31. A Film sheet held ``FILM_MODEL_UNRESOLVED`` gets the same shape of
answer WaveScan's ``ALIAS_MODEL`` has: the **Engineer proposes**, the
**Admin approves**, both audited, then the sheet is replayed through the
same ingest service. The record of the choice is the approved
``proposed_mapping`` row itself, keyed by ``(load_id, source_sheet)`` in its
payload -- so this revision adds **no table**.

It also grants ``app_rw`` **INSERT** on ``ref_film_model_alias``. Until now
nothing in the application wrote that table -- it was migration-seeded only
-- so the approve path had ``SELECT`` and nothing else. ``INSERT`` is the
whole grant: no ``UPDATE`` and no ``DELETE``, because an approved alias is
never overwritten (D-78-33) and never removed. That matches the grant every
other alias table the application teaches already has
(``ref_color_alias``, ``ref_model_alias``, ``ref_plant_zone_map``: SELECT,
INSERT).

**Additive and non-destructive.** It widens one CHECK constraint by one
value and adds one INSERT grant. No row is read, written or deleted. Every
existing ``kind`` stays allowed, so nothing already proposed or approved
becomes invalid.

The downgrade narrows the constraint back, and therefore **refuses** if any
``FILM_MODEL`` row exists rather than deleting one: a proposal is the record
of who decided what, and ``proposed_mapping`` is not something a migration
may quietly empty (ADR 0005's reasoning, applied to decisions rather than
facts). Reject the rows through the API first if a downgrade is really
wanted.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

CONSTRAINT = "proposed_mapping_kind_check"

#: Exactly what 0003 allowed, plus FILM_MODEL. Kept as literals so the
#: revision does not depend on reading the live constraint back.
KINDS_BEFORE = (
    "COLUMN", "ZONE", "ALIAS_COLOR", "ALIAS_MODEL",
    "ALIAS_PLANT", "ALIAS_CHECKZONE", "ALIAS_PAINTLINE",
)
KINDS_AFTER = KINDS_BEFORE + ("FILM_MODEL",)


def _check(kinds: tuple[str, ...]) -> str:
    inside = ", ".join(f"'{k}'" for k in kinds)
    return f"kind = ANY (ARRAY[{inside}]::text[])"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "proposed_mapping", type_="check")
    op.create_check_constraint(CONSTRAINT, "proposed_mapping", _check(KINDS_AFTER))
    # INSERT only. An approved Film model alias is never overwritten and never
    # deleted, so the application never needs UPDATE or DELETE here.
    op.execute("GRANT INSERT ON TABLE ref_film_model_alias TO app_rw")


def downgrade() -> None:
    conn = op.get_bind()
    stuck = conn.execute(
        sa.text("SELECT count(*) FROM proposed_mapping WHERE kind = 'FILM_MODEL'")
    ).scalar_one()
    if stuck:
        raise RuntimeError(
            f"refusing to downgrade 0029: {stuck} FILM_MODEL proposal(s) exist. "
            "A proposal records who decided what and is not deleted by a "
            "migration. Decide them through the API first."
        )
    op.execute("REVOKE INSERT ON TABLE ref_film_model_alias FROM app_rw")
    op.drop_constraint(CONSTRAINT, "proposed_mapping", type_="check")
    op.create_check_constraint(CONSTRAINT, "proposed_mapping", _check(KINDS_BEFORE))
