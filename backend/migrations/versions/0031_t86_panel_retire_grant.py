"""T86: let an approved panel-match set retire the block it supersedes.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-07

D-86-2: *"confirming a set retires the block it supersedes (`retired_at` +
`retired_reason`), so old data stays readable but new uploads match only the
live set. The owner names which block is superseded; the system never infers
it."*

Until now nothing in the application wrote ``ref_plant_ws_point`` at all --
migration 0022 (T58) granted ``SELECT`` and nothing else, and the list was
loaded by a migration under an owner proof. Approving a T86 set has to mark
the superseded rows, so this revision grants the **narrowest** thing that
can do it:

    GRANT UPDATE (retired_at, retired_reason) ON ref_plant_ws_point TO app_rw

**Why a column grant and not ``UPDATE``.** The retirement pair is the only
part of a panel row that is a decision; ``zone_code``, ``point_no``,
``tolerance_group`` and ``proof_hash`` are what the panel *is*. A
table-level ``UPDATE`` would let the approve path repoint a live panel or
change its Hor/Ver, and nothing in the product should be able to do that --
a wrong panel identity is a silent wrong grade, which `AGENTS.md` opens by
calling worse than a crash. PostgreSQL enforces the column list, so this is
a guarantee and not a convention.

**No ``INSERT`` and no ``DELETE``.** Adding a panel to a plant's list is
still an Admin catalogue change made by a migration under an owner proof
(T58), and a panel is never removed -- a retired row keeps its
``wavescan`` rows' FK target valid (``fk_ws_plant_point``), which is exactly
why D-86-2 retires rather than deletes.

``ck_plant_ws_point_retired`` (``(retired_at IS NULL) = (retired_reason IS
NULL)``) stays as it is, so the application cannot set one without the
other; and ``uq_plant_ws_point_no_live`` stays as it is, so retiring frees
that walk number for a later live panel.

**Additive and non-destructive.** One grant. No DDL, no row read, written or
deleted. The downgrade revokes it, which is safe at any time: already-retired
rows stay retired, because the retirement is data and not a grant.
"""

from __future__ import annotations

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"
TABLE = "ref_plant_ws_point"
#: The only columns an approval may write. See the module docstring.
COLUMNS = ("retired_at", "retired_reason")


def _grant(action: str, preposition: str) -> str:
    columns = ", ".join(COLUMNS)
    return (
        f"{action} UPDATE ({columns}) ON TABLE {TABLE} "
        f"{preposition} {APP_ROLE}"
    )


def upgrade() -> None:
    op.execute(_grant("GRANT", "TO"))
    op.execute(
        f"COMMENT ON COLUMN {TABLE}.retired_reason IS "
        "'T86 (D-86-2). Why this panel is superseded, in the owner''s words. "
        "Written by an approved panel-match set; app_rw holds UPDATE on this "
        "column and retired_at only, so it can retire a panel and can never "
        "repoint one.'"
    )


def downgrade() -> None:
    op.execute(_grant("REVOKE", "FROM"))
    op.execute(f"COMMENT ON COLUMN {TABLE}.retired_reason IS NULL")
