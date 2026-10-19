"""T47: proved P703 DBL FilmThickness location maps + gold Hor/Ver.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-29

Seeds from ``docs/reports/evidence/P703-DBL-film-location-map.json`` and
from nothing else (T47 locked 2): the owner's comparison workbook
``PELT_Comparison_P703_Ranger.xlsx`` reduced to location labels, with its
SHA-256 as ``proof_hash`` on every row. No pair is typed here.

1. ``ref_model_film_point.orientation`` ``char(1)`` ``H`` / ``V``, set on the
   94 gold points of ``P703 DBL RANGER`` and ``P703 DBL RAPTOR`` only
   (30 H / 64 V; the migration fails on any other count). On the model's
   catalogue row rather than ``ref_film_point`` so a RAPCAP / SGL point that
   shares a spelling never inherits a Ranger orientation.
2. ``ref_film_location_map``: one row per JSON ``maps`` entry (233), with
   ``proof_hash``, ``verified_by``, ``approved_at``. ``held_not_seeded``
   (AAT ``073``-``075LBXFLOOR``) is not inserted.

Additive. No grant changes: ``app_rw`` already holds SELECT only on both
tables. Downgrade refuses while any fact was mapped (its source label is not
its gold name), then deletes only this proof's map rows.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from alembic import op
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
# Shipped with the migrations so a fresh database can be built anywhere,
# including inside the image (docs/ is not copied there).
EVIDENCE = Path(__file__).resolve().parents[1] / "seed" / "P703-DBL-film-location-map.json"

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

GOLD_MODELS = ("P703 DBL RANGER", "P703 DBL RAPTOR")
EXPECTED_ORIENTATION = {"H": 30, "V": 64}
EXPECTED_MAPS = 233


def _evidence() -> dict:
    if not EVIDENCE.exists():
        raise RuntimeError(f"T47 seed source missing: {EVIDENCE}")
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def upgrade() -> None:
    conn = op.get_bind()
    data = _evidence()
    proof = data["proof_hash"].strip()
    owner = data["verified_by"].strip()
    if len(proof) != 64 or not owner:
        raise RuntimeError("T47 evidence lacks a 64-hex proof_hash or verified_by")

    # --- 1. orientation on the gold catalogue ---------------------------
    op.execute(
        "ALTER TABLE ref_model_film_point ADD COLUMN orientation char(1) "
        "CHECK (orientation IS NULL OR orientation IN ('H', 'V'))"
    )
    op.execute(
        "COMMENT ON COLUMN ref_model_film_point.orientation IS "
        "'T47 (D-FT-15). Horizontal (Hood / Roof / Floor) or Vertical, on the "
        "gold point. A mapped plant label inherits it from the point it maps "
        "to; never from the label, never from walk order.'"
    )
    gold = data["gold_points"]
    counts = Counter(p["orientation"] for p in gold)
    if dict(counts) != EXPECTED_ORIENTATION or len({p["point_code"] for p in gold}) != 94:
        raise RuntimeError(f"T47 gold orientation counts {dict(counts)} != {EXPECTED_ORIENTATION}")
    for model in GOLD_MODELS:
        catalogue = {
            r[0] for r in conn.execute(
                text("SELECT point_code FROM ref_model_film_point WHERE model_code = :m"),
                {"m": model},
            ).all()
        }
        if catalogue != {p["point_code"] for p in gold}:
            raise RuntimeError(f"T47 gold set differs from the {model} catalogue")
        for point in gold:
            conn.execute(
                text(
                    "UPDATE ref_model_film_point SET orientation = :o "
                    "WHERE model_code = :m AND point_code = :p"
                ),
                {"o": point["orientation"], "m": model, "p": point["point_code"]},
            )
        got = dict(conn.execute(
            text(
                "SELECT orientation, count(*) FROM ref_model_film_point "
                "WHERE model_code = :m GROUP BY 1"
            ),
            {"m": model},
        ).all())
        if got != EXPECTED_ORIENTATION:
            raise RuntimeError(f"T47 {model} orientation {got} != {EXPECTED_ORIENTATION}")

    # --- 2. proved location maps ----------------------------------------
    maps = data["maps"]
    held = {
        (h["plant_code"], h["model_code"], h["raw_location_norm"])
        for h in data.get("held_not_seeded", [])
    }
    if len(maps) != EXPECTED_MAPS:
        raise RuntimeError(f"T47 evidence has {len(maps)} maps, expected {EXPECTED_MAPS}")
    inserted = 0
    for row in maps:
        key = (row["plant_code"], row["model_code"], row["raw_location_norm"])
        if key in held:
            raise RuntimeError(f"T47 map {key} is listed as held_not_seeded")
        if row["model_code"] not in GOLD_MODELS:
            raise RuntimeError(f"T47 map {key} targets a non-DBL model")
        inserted += conn.execute(
            text(
                "INSERT INTO ref_film_location_map "
                "(plant_code, model_code, raw_location_norm, point_code, "
                " raw_position, proof_hash, verified_by, approved_at, note) "
                "VALUES (:plant, :model, :raw, :point, :pos, :proof, :owner, now(), "
                "        :note)"
            ),
            {
                "plant": row["plant_code"], "model": row["model_code"],
                "raw": row["raw_location_norm"], "point": row["point_code"],
                "pos": row.get("raw_position"), "proof": proof, "owner": owner,
                "note": f"T47 seed from {data['proof_document']} (labels only)",
            },
        ).rowcount
    if inserted != len(maps):
        raise RuntimeError(f"T47 inserted {inserted} of {len(maps)} maps")


def downgrade() -> None:
    proof = _evidence()["proof_hash"].strip()
    op.execute(
        r"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM filmthickness
                 WHERE upper(regexp_replace(regexp_replace(src_location_text,
                                   '\s+', '', 'g'), '^\d+\)', '')) <> point_code
            ) THEN
                RAISE EXCEPTION 'filmthickness holds mapped facts; removing their proof would orphan their point identity (ADR 0005)';
            END IF;
        END $$;
        """
    )
    op.execute(f"DELETE FROM ref_film_location_map WHERE proof_hash = '{proof}'")
    op.execute("ALTER TABLE ref_model_film_point DROP COLUMN IF EXISTS orientation")
