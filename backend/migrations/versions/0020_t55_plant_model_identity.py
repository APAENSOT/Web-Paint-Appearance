"""T55: plant model identity -- named WaveScan aliases + leftover Film gold.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-05

T55-CONTEXT D-55-02, D-55-09, D-55-10. Additive; no fact is touched.

1. **WaveScan ``ref_model_alias``, plant-scoped** (owner lock 2026-10-05):
   FVL ``CX743`` -> ``CX743``; SAP ``P703 DBL`` -> ``P703 DBL RANGER``.
   ``P703 RAP`` is deliberately **not** seeded (D-55-03).
2. **FilmThickness ``ref_film_model_alias``**: AAT ``U704``; FVL ``CX743``,
   ``V363``; SAP ``J73`` and ``J73 DBL`` -> ``J73 DBL``. Each leftover loads
   on its **own** catalogue, never Ranger's 94 (D-55-09).
3. **Leftover Film gold** in ``ref_plant_film_point`` from
   ``docs/reports/evidence/LEFTOVER-film-points.json`` and nothing else:
   AAT U704 95, FVL CX743 81, FVL V363 88, SAP J73 DBL 93. ``point_no`` is
   file order (walk proof only); Hor/Ver per D-53-06 on that name. New names
   join ``ref_film_point``; ``ref_model.expected_film_point_count`` is set on
   the four leftover models.

Downgrade refuses while any film fact names one of these leftover models,
then removes exactly what this revision added.
"""

from __future__ import annotations

import json
from pathlib import Path

from alembic import op
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
EVIDENCE = BACKEND.parent / "docs" / "reports" / "evidence" / "LEFTOVER-film-points.json"

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

NOTE = "T55 owner lock 2026-10-05"

#: (plant, raw Excel cell, catalogue model). Never global. No P703 RAP.
WAVESCAN_MODEL_ALIASES = (
    ("FVL", "CX743", "CX743"),
    ("SAP", "P703 DBL", "P703 DBL RANGER"),
)

#: (plant, filename / tab token, catalogue model). FilmThickness only.
FILM_MODEL_ALIASES = (
    ("AAT", "U704", "U704"),
    ("FVL", "CX743", "CX743"),
    ("FVL", "V363", "V363"),
    ("SAP", "J73", "J73 DBL"),
    ("SAP", "J73 DBL", "J73 DBL"),
)

EXPECTED_GOLD = {
    ("AAT", "U704"): 95,
    ("FVL", "CX743"): 81,
    ("FVL", "V363"): 88,
    ("SAP", "J73 DBL"): 93,
}


def _evidence() -> list[dict]:
    if not EVIDENCE.exists():
        raise RuntimeError(
            f"T55 seed source missing: {EVIDENCE}. Run "
            "backend/scripts/t55_leftover_film_evidence.py over the proving files."
        )
    catalogues = json.loads(EVIDENCE.read_text(encoding="utf-8"))["catalogues"]
    got = {(c["plant_code"], c["model_code"]): c for c in catalogues}
    if set(got) != set(EXPECTED_GOLD):
        raise RuntimeError(f"T55 evidence catalogues {sorted(got)} != {sorted(EXPECTED_GOLD)}")
    for key, cat in got.items():
        names = [p["point_code"] for p in cat["locations"]]
        if (
            cat["point_count"] != EXPECTED_GOLD[key]
            or len(names) != EXPECTED_GOLD[key]
            or len(set(names)) != len(names)
            or [p["point_no"] for p in cat["locations"]] != list(range(1, len(names) + 1))
            or len(str(cat.get("source_sha256", "")).strip()) != 64
        ):
            raise RuntimeError(f"T55 evidence for {key} is not {EXPECTED_GOLD[key]} distinct points with a hash")
        for p in cat["locations"]:
            name = p["point_code"]
            want = "H" if any(w in name for w in ("HOOD", "ROOF", "FLOOR")) else "V"
            if name != name.strip().upper() or p["orientation"] != want:
                raise RuntimeError(f"T55 evidence point {key} {name!r} breaks D-53-06")
    return catalogues


def upgrade() -> None:
    conn = op.get_bind()
    catalogues = _evidence()

    for plant, raw, model in WAVESCAN_MODEL_ALIASES:
        conn.execute(
            text(
                "INSERT INTO ref_model_alias (plant_code, raw_value, model_code, note) "
                "VALUES (:p, :r, :m, :note) "
                "ON CONFLICT (plant_code, raw_value) WHERE plant_code IS NOT NULL DO NOTHING"
            ),
            {"p": plant, "r": raw, "m": model, "note": NOTE},
        )

    for plant, token, model in FILM_MODEL_ALIASES:
        conn.execute(
            text(
                "INSERT INTO ref_film_model_alias (plant_code, raw_token, model_code, note) "
                "VALUES (:p, :t, :m, :note) ON CONFLICT (plant_code, raw_token) DO NOTHING"
            ),
            {"p": plant, "t": token, "m": model, "note": f"{NOTE} (D-55-10)"},
        )

    for cat in catalogues:
        plant, model = cat["plant_code"], cat["model_code"]
        note = f"T55 seed from {cat['source_file']} (labels only)"
        for p in cat["locations"]:
            conn.execute(
                text(
                    "INSERT INTO ref_film_point (point_code) VALUES (:p) "
                    "ON CONFLICT (point_code) DO NOTHING"
                ),
                {"p": p["point_code"]},
            )
            conn.execute(
                text(
                    "INSERT INTO ref_plant_film_point "
                    "(plant_code, model_code, point_code, point_no, orientation, "
                    " proof_hash, note) "
                    "VALUES (:plant, :model, :point, :no, :o, :proof, :note)"
                ),
                {
                    "plant": plant, "model": model, "point": p["point_code"],
                    "no": p["point_no"], "o": p["orientation"],
                    "proof": cat["source_sha256"], "note": note,
                },
            )
        conn.execute(
            text("UPDATE ref_model SET expected_film_point_count = :n WHERE model_code = :m"),
            {"n": cat["point_count"], "m": model},
        )
    got = dict(conn.execute(
        text(
            "SELECT plant_code || '|' || model_code, count(*) FROM ref_plant_film_point "
            "WHERE (plant_code, model_code) IN (('AAT','U704'), ('FVL','CX743'), "
            "('FVL','V363'), ('SAP','J73 DBL')) GROUP BY 1"
        )
    ).all())
    want = {f"{p}|{m}": n for (p, m), n in EXPECTED_GOLD.items()}
    if got != want:
        raise RuntimeError(f"T55 leftover gold seeded {got} != {want}")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM filmthickness
                        WHERE model IN ('U704', 'CX743', 'V363', 'J73 DBL')) THEN
                RAISE EXCEPTION 'filmthickness holds leftover facts; removing their gold would orphan them (ADR 0005)';
            END IF;
        END $$;
        """
    )
    conn = op.get_bind()
    for (plant, model), _ in EXPECTED_GOLD.items():
        conn.execute(
            text(
                "DELETE FROM ref_plant_film_point WHERE plant_code = :p AND model_code = :m "
                "AND note LIKE 'T55 seed%'"
            ),
            {"p": plant, "m": model},
        )
        conn.execute(
            text("UPDATE ref_model SET expected_film_point_count = NULL WHERE model_code = :m"),
            {"m": model},
        )
    for plant, token, _ in FILM_MODEL_ALIASES:
        conn.execute(
            text(
                "DELETE FROM ref_film_model_alias WHERE plant_code = :p AND raw_token = :t "
                "AND note LIKE 'T55 owner lock%'"
            ),
            {"p": plant, "t": token},
        )
    for plant, raw, _ in WAVESCAN_MODEL_ALIASES:
        conn.execute(
            text(
                "DELETE FROM ref_model_alias WHERE plant_code = :p AND raw_value = :r "
                "AND note = :note"
            ),
            {"p": plant, "r": raw, "note": NOTE},
        )
    op.execute(
        """
        DELETE FROM ref_film_point p
         WHERE NOT EXISTS (SELECT 1 FROM ref_plant_film_point c WHERE c.point_code = p.point_code)
           AND NOT EXISTS (SELECT 1 FROM ref_model_film_point c WHERE c.point_code = p.point_code)
           AND NOT EXISTS (SELECT 1 FROM filmthickness f WHERE f.point_code = p.point_code)
        """
    )
