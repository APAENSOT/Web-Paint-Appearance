"""T29: let an Admin certify plant zone maps with the S15 proof columns.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-21

One change, and it is a grant.

T01 gave `app_rw` `UPDATE (confidence, approved_by, approved_at, note)` on
`ref_plant_zone_map`. T26 (revision 0009) added the S15 proof columns --
`proof_hash`, `proof_document`, `verified_by` -- but left them outside that
grant, so the application could insert a proved row and could not certify an
existing one. T29's atomic `ZONE` approve needs both: insert a missing row
with its proof, or **certify** a row that already maps the same raw label to
the same zone by filling its proof in place.

The column list below is therefore T01's four plus:

* `proof_hash`, `proof_document`, `verified_by` -- the S15 proof;
* `proposal_method` -- how the named owner decided (never an executable);
* `raw_position` -- the plant-local number, provenance only.

What stays **frozen** is the point of doing this by column: `plant_code`,
`model_code`, `raw_zone_text` and `zone_code` are not in the list, so no
route can repoint an approved label at a different physical panel. A
conflicting `zone_code` is refused by the service (409) and could not be
written by this role even if the service were wrong.

**Not destructive.** No row is inserted, updated or deleted. No SAP or FVL
zone map is seeded, approved or proposed -- G1's named plant/quality owner
proof is what fills that table, through the Admin route. `app_rw` gains no
DELETE here or anywhere, and nothing here touches measurements or batches.
The owner's commit message should still name the grant (`AGENTS.md`
section 2).
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

#: T01's list (revision 0001, `PLANT_ZONE_MAP_UPDATABLE_COLUMNS`).
T01_COLUMNS = ("confidence", "approved_by", "approved_at", "note")

#: T29's list: T01's four plus the proof and provenance columns.
ZONE_MAP_UPDATE_COLUMNS = T01_COLUMNS + (
    "proof_hash", "proof_document", "verified_by", "proposal_method",
    "raw_position",
)


def _grant(columns: tuple[str, ...]) -> None:
    listed = ", ".join(columns)
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                REVOKE UPDATE ON ref_plant_zone_map FROM {role};
                GRANT UPDATE ({listed}) ON ref_plant_zone_map TO {role};
            END $$;
            """
        )


def upgrade() -> None:
    _grant(ZONE_MAP_UPDATE_COLUMNS)


def downgrade() -> None:
    _grant(T01_COLUMNS)
