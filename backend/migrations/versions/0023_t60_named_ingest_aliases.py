"""T60: named ingest leftovers -- SAP WaveScan P703 RAP, Film headers, colours.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-05

T60-CONTEXT D-60-01..08. Seeds on existing tables only; no fact is touched.

A. **WaveScan** ``ref_model_alias`` (SAP, ``P703 RAP``) -> ``P703 DBL RAPTOR``
   (G1 D-06). WaveScan only: **no** ``ref_film_model_alias`` row -- FTM
   filename ``_RAP_`` stays RAPCAP (D-FT-08).
B. **FILMTHICKNESS** ``ref_column_alias`` (approved): ``mid grey`` /
   ``basecoat1`` / ``basecoat 1`` / ``l28 bc1`` -> primer; ``basecoat2`` /
   ``basecoat 2`` -> base; ``epic`` -> ecoat; ``ground-coat`` /
   ``ground coat`` / ``orientation`` -> ``ignored``, a non-fact field (never a
   paint layer, never a thickness row).
C. **Colour aliases** at FVL, SAP and FTM (AAT has them since T57):
   ``Aluminum Met_4`` -> Aluminum Metallic, ``DesertIslandBlu_4`` -> Desert
   Island Blue, ``Snowflake White_4`` -> Arctic White. No new colour; nothing
   is offered by this revision.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

NOTE = "T60 owner lock 2026-10-05"

#: (plant, raw Model cell, catalogue model). WaveScan only.
WAVESCAN_MODEL_ALIASES = (("SAP", "P703 RAP", "P703 DBL RAPTOR"),)

#: (normalised header, logical field) for the FILMTHICKNESS vocabulary.
FILM_COLUMN_ALIASES = (
    ("mid grey", "primer"),
    ("basecoat1", "primer"),
    ("basecoat 1", "primer"),
    ("l28 bc1", "primer"),
    ("basecoat2", "base"),
    ("basecoat 2", "base"),
    ("epic", "ecoat"),
    ("ground-coat", "ignored"),
    ("ground coat", "ignored"),
    ("orientation", "ignored"),
)

COLOR_ALIASES = tuple(
    (plant, raw, colour)
    for plant in ("FVL", "SAP", "FTM")
    for raw, colour in (
        ("Aluminum Met_4", "Aluminum Metallic"),
        ("DesertIslandBlu_4", "Desert Island Blue"),
        ("Snowflake White_4", "Arctic White"),
    )
)


def upgrade() -> None:
    conn = op.get_bind()
    for plant, raw, model in WAVESCAN_MODEL_ALIASES:
        conn.execute(
            text(
                "INSERT INTO ref_model_alias (plant_code, raw_value, model_code, note) "
                "VALUES (:p, :r, :m, :note) "
                "ON CONFLICT (plant_code, raw_value) WHERE plant_code IS NOT NULL DO NOTHING"
            ),
            {"p": plant, "r": raw, "m": model, "note": NOTE},
        )
    for raw, logical in FILM_COLUMN_ALIASES:
        conn.execute(
            text(
                "INSERT INTO ref_column_alias (raw_header, logical_field, is_approved, domain) "
                "VALUES (:r, :l, true, 'FILMTHICKNESS') "
                "ON CONFLICT (domain, raw_header) DO NOTHING"
            ),
            {"r": raw, "l": logical},
        )
    for plant, raw, colour in COLOR_ALIASES:
        conn.execute(
            text(
                "INSERT INTO ref_color_alias (plant_code, raw_value, color_name, note) "
                "VALUES (:p, :r, :c, :note) "
                "ON CONFLICT (plant_code, raw_value) WHERE plant_code IS NOT NULL DO NOTHING"
            ),
            {"p": plant, "r": raw, "c": colour, "note": NOTE},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for plant, raw, _ in COLOR_ALIASES:
        conn.execute(
            text("DELETE FROM ref_color_alias WHERE plant_code = :p AND raw_value = :r "
                 "AND note = :note"),
            {"p": plant, "r": raw, "note": NOTE},
        )
    for raw, logical in FILM_COLUMN_ALIASES:
        conn.execute(
            text("DELETE FROM ref_column_alias WHERE domain = 'FILMTHICKNESS' "
                 "AND raw_header = :r AND logical_field = :l"),
            {"r": raw, "l": logical},
        )
    for plant, raw, _ in WAVESCAN_MODEL_ALIASES:
        conn.execute(
            text("DELETE FROM ref_model_alias WHERE plant_code = :p AND raw_value = :r "
                 "AND note = :note"),
            {"p": plant, "r": raw, "note": NOTE},
        )
