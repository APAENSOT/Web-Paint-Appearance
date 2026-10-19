"""Plant-scoped colour family catalogue, offered lists, ingest reject reasons.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-22

Not a DELETE of facts. Adds ``family_code``, plant offered tables, series,
and grants for Admin mint/offered flags. Seeds the owner-signed map from
``docs/reports/STANDARDS-D2-AUDIT.md`` (Ignite Orange SAP=MM; Shadow Black
not folded into Absolute Black; Magnetic kept). Does not copy the xlsx.
Does not write ``ref_color.grading_family``. Does not INSERT colour aliases.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

FAMILY_CODES = (
    ("Light Metallics", "LM"),
    ("Medium Metallics", "MM"),
    ("Dark Metallics", "DM"),
    ("Light Solids", "LS"),
    ("Medium Solids", "MS"),
    ("Dark Solids", "DS"),
)

SERIES = ("P703", "J73", "CX743", "V363", "U704")

# (plant, color_name, family_name) — signed audit §2.
PLANT_COLORS: tuple[tuple[str, str, str], ...] = (
    ("AAT", "Pearl White", "Light Metallics"),
    ("AAT", "Aluminum Metallic", "Light Metallics"),
    ("FTM", "Aluminum Metallic", "Light Metallics"),
    ("FVL", "Iconic Silver", "Light Metallics"),
    ("SAP", "Iconic Silver", "Light Metallics"),
    ("AAT", "Meteor Grey", "Medium Metallics"),
    ("FTM", "Meteor Grey", "Medium Metallics"),
    ("FVL", "Magnetic", "Medium Metallics"),
    ("AAT", "Acacia Green", "Medium Metallics"),
    ("SAP", "Acacia Green", "Medium Metallics"),
    ("SAP", "Cyclone Terra Green", "Medium Metallics"),
    ("FVL", "Diffused Silver", "Medium Metallics"),
    ("SAP", "Diffused Silver", "Medium Metallics"),
    ("SAP", "Carbonized Grey", "Medium Metallics"),
    ("FVL", "Vapor Blue", "Medium Metallics"),
    ("AAT", "Desert Island Blue", "Medium Metallics"),
    ("FTM", "Desert Island Blue", "Medium Metallics"),
    ("SAP", "Desert Island Blue", "Medium Metallics"),
    ("AAT", "Blue Lightning", "Dark Metallics"),
    ("FTM", "Blue Lightning", "Dark Metallics"),
    ("SAP", "Blue Lightning", "Dark Metallics"),
    ("FVL", "Pace Red", "Dark Metallics"),
    ("SAP", "Lucid Red", "Dark Metallics"),
    ("FVL", "Absolute Black", "Dark Metallics"),
    ("AAT", "Shadow Black", "Dark Metallics"),
    ("FTM", "Shadow Black", "Dark Metallics"),
    ("SAP", "Agate Black", "Dark Metallics"),
    ("AAT", "Arctic White", "Light Solids"),
    ("FTM", "Arctic White", "Light Solids"),
    ("FVL", "Frozen White", "Light Solids"),
    ("SAP", "Frozen White", "Light Solids"),
    ("SAP", "Chill Grey", "Light Solids"),
    ("AAT", "Command Grey", "Medium Solids"),
    ("FTM", "Command Grey", "Medium Solids"),
    ("SAP", "Command Grey", "Medium Solids"),
    ("FTM", "Code Orange", "Medium Solids"),
    ("AAT", "Ignite Orange", "Medium Solids"),
    ("FTM", "Ignite Orange", "Medium Solids"),
    ("FVL", "Ignite Orange", "Medium Solids"),
    ("SAP", "Ignite Orange", "Medium Metallics"),
    ("AAT", "Seismic Tan", "Medium Solids"),
    ("AAT", "Traction Green", "Medium Solids"),
)

# (plant, model_code) — signed audit §4.
PLANT_MODELS: tuple[tuple[str, str], ...] = (
    ("AAT", "P703 DBL RANGER"),
    ("FTM", "P703 DBL RANGER"),
    ("FVL", "P703 DBL RANGER"),
    ("SAP", "P703 DBL RANGER"),
    ("FTM", "P703 DBL RAPTOR"),
    ("SAP", "P703 DBL RAPTOR"),
    ("AAT", "P703 DBL SUPER DUTY"),
    ("SAP", "J73 DBL"),
    ("FVL", "CX743"),
    ("FVL", "V363"),
    ("AAT", "U704"),
)

REJECT_REASONS = (
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
        "ALTER TABLE ref_color_family ADD COLUMN IF NOT EXISTS family_code text"
    )
    conn = op.get_bind()
    for name, code in FAMILY_CODES:
        conn.execute(
            text(
                "UPDATE ref_color_family SET family_code = :c "
                "WHERE family_name = :n AND family_code IS NULL"
            ),
            {"c": code, "n": name},
        )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_color_family_code'
            ) THEN
                ALTER TABLE ref_color_family
                    ADD CONSTRAINT uq_color_family_code UNIQUE (family_code);
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE ref_color_family ALTER COLUMN family_code SET NOT NULL")
    op.execute(
        "COMMENT ON COLUMN ref_color_family.family_code IS "
        "'Workbook codes LM/MM/DM/LS/MS/DS. Names stay Prototype spellings.'"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref_plant_color (
            plant_code   text NOT NULL REFERENCES ref_plant,
            color_name   text NOT NULL REFERENCES ref_color,
            family_name  text REFERENCES ref_color_family,
            is_offered   boolean NOT NULL DEFAULT true,
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (plant_code, color_name)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_plant_color IS "
        "'Plant-scoped CF family and offered flag (ADR 0010). "
        "Disable = is_offered false. No DELETE of a row History used. "
        "ref_color.grading_family is unused.'"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref_model_series (
            series_code text PRIMARY KEY
        )
        """
    )
    for series in SERIES:
        conn.execute(
            text(
                "INSERT INTO ref_model_series (series_code) VALUES (:s) "
                "ON CONFLICT (series_code) DO NOTHING"
            ),
            {"s": series},
        )
    op.execute(
        "ALTER TABLE ref_model ADD COLUMN IF NOT EXISTS series_code "
        "text REFERENCES ref_model_series"
    )
    conn.execute(
        text(
            "UPDATE ref_model SET series_code = model_family "
            "WHERE series_code IS NULL AND model_family IN "
            "('P703','J73','CX743','V363','U704')"
        )
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref_plant_model (
            plant_code  text NOT NULL REFERENCES ref_plant,
            model_code  text NOT NULL REFERENCES ref_model,
            is_offered  boolean NOT NULL DEFAULT true,
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (plant_code, model_code)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_plant_model IS "
        "'Existing model_code offered at a plant. Admin does not mint models.'"
    )

    listed = ", ".join(f"'{r}'" for r in REJECT_REASONS)
    op.execute("ALTER TABLE reject_log DROP CONSTRAINT IF EXISTS ck_reject_reason")
    op.execute(
        f"""
        ALTER TABLE reject_log ADD CONSTRAINT ck_reject_reason CHECK (
            reject_reason IN ({listed})
        )
        """
    )

    for plant, color, family in PLANT_COLORS:
        conn.execute(
            text(
                "INSERT INTO ref_plant_color "
                "(plant_code, color_name, family_name, is_offered) "
                "SELECT :p, :c, :f, true "
                "WHERE EXISTS (SELECT 1 FROM ref_plant WHERE plant_code = :p) "
                "  AND EXISTS (SELECT 1 FROM ref_color WHERE color_name = :c) "
                "  AND EXISTS (SELECT 1 FROM ref_color_family WHERE family_name = :f) "
                "ON CONFLICT (plant_code, color_name) DO NOTHING"
            ),
            {"p": plant, "c": color, "f": family},
        )
    for plant, model in PLANT_MODELS:
        conn.execute(
            text(
                "INSERT INTO ref_plant_model (plant_code, model_code, is_offered) "
                "SELECT :p, :m, true "
                "WHERE EXISTS (SELECT 1 FROM ref_plant WHERE plant_code = :p) "
                "  AND EXISTS (SELECT 1 FROM ref_model WHERE model_code = :m) "
                "ON CONFLICT (plant_code, model_code) DO NOTHING"
            ),
            {"p": plant, "m": model},
        )

    _for_each_role(
        """
        GRANT SELECT, INSERT ON ref_plant_color TO {role};
        GRANT UPDATE (family_name, is_offered, updated_at) ON ref_plant_color TO {role};
        GRANT SELECT, INSERT ON ref_plant_model TO {role};
        GRANT UPDATE (is_offered) ON ref_plant_model TO {role};
        GRANT SELECT, INSERT ON ref_model_series TO {role};
        GRANT INSERT ON ref_color TO {role};
        """
    )


def downgrade() -> None:
    _for_each_role(
        """
        REVOKE INSERT ON ref_color FROM {role};
        REVOKE ALL ON ref_plant_color FROM {role};
        REVOKE ALL ON ref_plant_model FROM {role};
        REVOKE ALL ON ref_model_series FROM {role};
        """
    )
    op.execute("ALTER TABLE reject_log DROP CONSTRAINT IF EXISTS ck_reject_reason")
    prior = ", ".join(
        f"'{r}'"
        for r in REJECT_REASONS
        if r not in ("COLOR_NOT_OFFERED", "MODEL_NOT_OFFERED")
    )
    op.execute(
        f"""
        ALTER TABLE reject_log ADD CONSTRAINT ck_reject_reason CHECK (
            reject_reason IN ({prior})
        )
        """
    )
    op.execute("DROP TABLE IF EXISTS ref_plant_model")
    op.execute("ALTER TABLE ref_model DROP COLUMN IF EXISTS series_code")
    op.execute("DROP TABLE IF EXISTS ref_model_series")
    op.execute("DROP TABLE IF EXISTS ref_plant_color")
    op.execute(
        "ALTER TABLE ref_color_family DROP CONSTRAINT IF EXISTS uq_color_family_code"
    )
    op.execute("ALTER TABLE ref_color_family DROP COLUMN IF EXISTS family_code")
