"""Held-label identity: let an approved colour spelling land.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-21

One change, and it is a grant.

T08 (revision 0004) gave `app_rw` `INSERT` on `ref_model_alias` and
deliberately **not** on `ref_color_alias`, because `ALIAS_COLOR` was
folded into D2 (colour → family). The finish-batch spec splits those:
identity alias (this spelling at this plant is this existing
`ref_color.color_name`) may ship; family / `POST /standards` stay closed.

This grant is the same shape as the model one:

* `INSERT` only. No `UPDATE`, so an approved spelling cannot be quietly
  repointed at a different colour. No `DELETE`, so a decision cannot be
  withdrawn without a trace.
* Written only by the Admin approve route, never by ingest.
* `grading_family` is not a column of `ref_color_alias` and is not
  written here. D1 and D2 stay open.

**Not destructive.** No row is inserted, updated or deleted. No colour
catalogue name is minted. `app_rw` gains no DELETE here or anywhere, and
nothing here touches measurements or batches. The owner's commit message
should name the grant (`AGENTS.md` section 2).
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")


def _for_each_role(sql: str) -> None:
    """Apply `sql` per role, skipping a role this database does not have."""
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


def upgrade() -> None:
    _for_each_role(
        """
        -- Written only by the Admin approve route, never by ingest.
        -- No UPDATE: an approved alias cannot be repointed.
        -- No DELETE: a decision cannot be withdrawn silently.
        GRANT INSERT ON ref_color_alias TO {role};
        """
    )


def downgrade() -> None:
    _for_each_role("REVOKE INSERT ON ref_color_alias FROM {role};")
