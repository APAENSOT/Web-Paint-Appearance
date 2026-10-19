"""T62: ``film_standard`` -- the FilmThickness micron standards container.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-06

T62-CONTEXT D-FS-01..11. Additive only: one CREATE TABLE, one index, a
COMMENT and grants. **No row is inserted** (D-FS-11): every number comes from
``POST /api/v1/filmthickness/standards`` or a later owner-signed seed.

* One table for plant-wide layer rules (``color_name IS NULL``) and per-colour
  rules (plant x colour, never plant x family; D-FS-01, D-FS-02).
* ``orient`` is never NULL: every publish appends an H row and a V row
  (D-FS-06).
* ``lo`` / ``hi`` / ``target`` in microns, 0-500, at least one of ``lo`` or
  ``hi``; ``target`` (the prototype's Clear "avg") only on CLEAR (D-FS-07).
* Append-only (D-FS-03, ADR 0005 analog): the app roles get SELECT and INSERT,
  never UPDATE or DELETE. Latest ``created_at`` wins per
  (plant, layer, colour-or-NULL, orient) (D-FS-04).

Downgrade drops the table.
"""

from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")


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


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE film_standard (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plant_code       text NOT NULL REFERENCES ref_plant (plant_code),
            layer_code       text NOT NULL
                                 CHECK (layer_code IN ('ECOAT', 'PRIMER', 'BASE', 'CLEAR')),
            orient           char(1) NOT NULL CHECK (orient IN ('H', 'V')),
            color_name       text NULL REFERENCES ref_color (color_name),
            lo               numeric(6,2) NULL CHECK (lo BETWEEN 0 AND 500),
            hi               numeric(6,2) NULL CHECK (hi BETWEEN 0 AND 500),
            target           numeric(6,2) NULL CHECK (target BETWEEN 0 AND 500),
            source_document  text NULL,
            source_note      text NOT NULL CHECK (length(btrim(source_note)) > 0),
            created_by       uuid NULL REFERENCES app_user (id),
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_film_standard_bound CHECK (lo IS NOT NULL OR hi IS NOT NULL),
            CONSTRAINT ck_film_standard_order CHECK (lo IS NULL OR hi IS NULL OR lo <= hi),
            CONSTRAINT ck_film_standard_target_clear
                CHECK (target IS NULL OR layer_code = 'CLEAR'),
            CONSTRAINT ck_film_standard_target_order CHECK (
                target IS NULL
                OR ((lo IS NULL OR lo <= target) AND (hi IS NULL OR target <= hi))
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_film_standard_latest ON film_standard "
        "(plant_code, layer_code, color_name, orient, created_at DESC)"
    )
    op.execute(
        "COMMENT ON TABLE film_standard IS "
        "'T62 (D-FS-01..11). FilmThickness micron standards, append-only: "
        "INSERT only, never UPDATE or DELETE; every publish is an H and a V "
        "row plus an audit_event. Latest created_at wins per (plant, layer, "
        "colour-or-NULL, orient). D-FS-05 precedence: the latest per-colour "
        "row, else the latest plant-wide row (color_name NULL), else no "
        "standard -- never another plant, never another colour or family. "
        "target is the CLEAR avg only. No seed in this revision.'"
    )
    op.execute("REVOKE ALL ON film_standard FROM PUBLIC")
    _for_each_role("GRANT SELECT, INSERT ON film_standard TO {role};")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS film_standard")
