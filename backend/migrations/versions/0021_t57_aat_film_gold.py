"""T57: AAT P703 Film gold = Sep Checkzone 94 + named AAT colour aliases.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-05

T57-CONTEXT D-57-01..07. No fact is touched (ADR 0005).

1. **Retirable gold rows.** ``ref_plant_film_point`` gains ``retired_at`` /
   ``retired_reason`` (both or neither). Point order becomes unique among
   **live** rows only. A retired row stays a record -- a fact that named it
   keeps its FK target -- and no reader resolves or lists it.
2. **AAT x P703 DBL RANGER gold = the Sep Checkzone 94**, from
   ``docs/reports/evidence/AAT-P703-film-points.json`` and nothing else.
   The 30 names AAT shares with the T46/T47 copy keep their row and take
   the Sep ``point_no`` / Hor/Ver / proof; the 64 FVL-only names of that
   copy are **retired**; the 64 AAT-own names (``031LTRRDOOR`` ...
   ``094RBOXSIDE``, incl. the 11 of D-57-07) are inserted. Other plants,
   other AAT models and AAT U704 (T55 95) are untouched.
3. **AAT T47 location maps retired** (D-57-03, T54 pattern): every live
   ``ref_film_location_map`` row at AAT targets an FVL-copy code. Kept as a
   record, never read.
4. **AAT colour aliases** (D-57-06, plant-scoped, exact banner spelling):
   ``Aluminum Met_4`` -> Aluminum Metallic, ``DesertIslandBlu_4`` -> Desert
   Island Blue, ``Snowflake White_4`` -> Arctic White. No new ``ref_color``;
   Pearl White untouched.

Downgrade refuses while any AAT Ranger fact names an AAT-own Sep point.
"""

from __future__ import annotations

import json
from pathlib import Path

from alembic import op
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
# Shipped with the migrations so a fresh database can be built anywhere,
# including inside the image (docs/ is not copied there).
EVIDENCE = Path(__file__).resolve().parents[1] / "seed" / "AAT-P703-film-points.json"

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

PLANT = "AAT"
MODEL = "P703 DBL RANGER"
EXPECTED = 94
NOTE = "T57 owner lock 2026-10-05"
GOLD_RETIRED = (
    "T57 (D-57-01): AAT P703 gold is the Sep Checkzone 94; this FVL-shaped "
    "copy row is no longer AAT gold. Kept as a record for any fact that named it."
)
MAP_RETIRED = (
    "T57 (D-57-03): AAT labels are AAT gold names, not FVL codes. Retired "
    "from resolve; kept as a record."
)
#: (plant, raw banner swatch, catalogue colour). Plant-scoped. No new colour.
COLOR_ALIASES = (
    ("AAT", "Aluminum Met_4", "Aluminum Metallic"),
    ("AAT", "DesertIslandBlu_4", "Desert Island Blue"),
    ("AAT", "Snowflake White_4", "Arctic White"),
)


def _evidence() -> dict:
    if not EVIDENCE.exists():
        raise RuntimeError(
            f"T57 seed source missing: {EVIDENCE}. Run "
            "backend/scripts/t57_aat_p703_film_evidence.py over the proving file."
        )
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    names = [p["point_code"] for p in data["locations"]]
    if (
        (data["plant_code"], data["model_code"]) != (PLANT, MODEL)
        or data["point_count"] != EXPECTED or len(set(names)) != EXPECTED
        or [p["point_no"] for p in data["locations"]] != list(range(1, EXPECTED + 1))
        or len(str(data.get("source_sha256", "")).strip()) != 64
    ):
        raise RuntimeError("T57 evidence is not 94 distinct AAT P703 points with a hash")
    for p in data["locations"]:
        name = p["point_code"]
        want = "H" if any(w in name for w in ("HOOD", "ROOF", "FLOOR")) else "V"
        if name != name.strip().upper() or p["orientation"] != want:
            raise RuntimeError(f"T57 evidence point {name!r} breaks D-53-06")
    return data


def upgrade() -> None:
    conn = op.get_bind()
    data = _evidence()
    proof = data["source_sha256"]
    note = f"T57 seed from {data['source_file']} Checkzone walk (labels only)"
    gold = {p["point_code"]: p for p in data["locations"]}

    # --- 1. retirable gold rows -----------------------------------------
    op.execute(
        "ALTER TABLE ref_plant_film_point "
        "ADD COLUMN retired_at timestamptz, ADD COLUMN retired_reason text"
    )
    op.execute(
        "ALTER TABLE ref_plant_film_point ADD CONSTRAINT ck_plant_film_point_retired "
        "CHECK ((retired_at IS NULL) = (retired_reason IS NULL))"
    )
    op.execute(
        "COMMENT ON COLUMN ref_plant_film_point.retired_at IS "
        "'T57. Set: no longer this plant''s gold. Kept so a fact that named it "
        "keeps its FK target (ADR 0005); never resolved or listed.'"
    )
    op.execute("ALTER TABLE ref_plant_film_point DROP CONSTRAINT uq_plant_film_point_no")

    # --- 2. AAT P703 gold = Sep 94 ---------------------------------------
    current = {
        r[0] for r in conn.execute(
            text(
                "SELECT point_code FROM ref_plant_film_point "
                "WHERE plant_code = :p AND model_code = :m"
            ),
            {"p": PLANT, "m": MODEL},
        ).all()
    }
    retired = conn.execute(
        text(
            "UPDATE ref_plant_film_point SET retired_at = now(), retired_reason = :why "
            "WHERE plant_code = :p AND model_code = :m AND point_code <> ALL(:keep)"
        ),
        {"why": GOLD_RETIRED, "p": PLANT, "m": MODEL, "keep": list(gold)},
    ).rowcount
    for name, p in gold.items():
        if name in current:
            conn.execute(
                text(
                    "UPDATE ref_plant_film_point SET point_no = :no, orientation = :o, "
                    "proof_hash = :proof, note = :note "
                    "WHERE plant_code = :p AND model_code = :m AND point_code = :pt"
                ),
                {"no": p["point_no"], "o": p["orientation"], "proof": proof,
                 "note": note, "p": PLANT, "m": MODEL, "pt": name},
            )
        else:
            conn.execute(
                text("INSERT INTO ref_film_point (point_code) VALUES (:p) "
                     "ON CONFLICT (point_code) DO NOTHING"),
                {"p": name},
            )
            conn.execute(
                text(
                    "INSERT INTO ref_plant_film_point "
                    "(plant_code, model_code, point_code, point_no, orientation, "
                    " proof_hash, note) VALUES (:p, :m, :pt, :no, :o, :proof, :note)"
                ),
                {"p": PLANT, "m": MODEL, "pt": name, "no": p["point_no"],
                 "o": p["orientation"], "proof": proof, "note": note},
            )
    op.execute(
        "CREATE UNIQUE INDEX uq_plant_film_point_no_live ON ref_plant_film_point "
        "(plant_code, model_code, point_no) WHERE retired_at IS NULL"
    )
    live = [
        r[0] for r in conn.execute(
            text(
                "SELECT point_code FROM ref_plant_film_point "
                "WHERE plant_code = :p AND model_code = :m AND retired_at IS NULL "
                "ORDER BY point_no"
            ),
            {"p": PLANT, "m": MODEL},
        ).all()
    ]
    if live != list(gold):
        raise RuntimeError(f"T57 AAT P703 live gold is {len(live)} rows, not the Sep 94 in order")
    print(f"T57: AAT P703 gold = Sep 94 ({len(set(gold) & current)} kept, "
          f"{len(set(gold) - current)} new, {retired} retired)")

    # --- 3. retire AAT T47 maps ------------------------------------------
    maps = conn.execute(
        text(
            "UPDATE ref_film_location_map SET retired_at = now(), retired_reason = :why "
            "WHERE plant_code = :p AND retired_at IS NULL"
        ),
        {"why": MAP_RETIRED, "p": PLANT},
    ).rowcount
    print(f"T57: {maps} AAT location maps retired")

    # --- 4. AAT colour aliases -------------------------------------------
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
    data = _evidence()
    own = [p["point_code"] for p in data["locations"]]
    blocked = conn.execute(
        text(
            "SELECT count(*) FROM filmthickness f WHERE f.plant = :p AND f.model = :m "
            "AND NOT EXISTS (SELECT 1 FROM ref_model_film_point c "
            "                WHERE c.model_code = f.model AND c.point_code = f.point_code)"
        ),
        {"p": PLANT, "m": MODEL},
    ).scalar_one()
    if blocked:
        raise RuntimeError(
            f"{blocked} AAT P703 film facts name Sep-only gold; removing it would "
            "orphan them (ADR 0005)"
        )
    for plant, raw, _ in COLOR_ALIASES:
        conn.execute(
            text("DELETE FROM ref_color_alias WHERE plant_code = :p AND raw_value = :r "
                 "AND note = :note"),
            {"p": plant, "r": raw, "note": NOTE},
        )
    conn.execute(
        text("UPDATE ref_film_location_map SET retired_at = NULL, retired_reason = NULL "
             "WHERE plant_code = :p AND retired_reason = :why"),
        {"p": PLANT, "why": MAP_RETIRED},
    )
    op.execute("DROP INDEX IF EXISTS uq_plant_film_point_no_live")
    conn.execute(
        text(
            "DELETE FROM ref_plant_film_point WHERE plant_code = :p AND model_code = :m "
            "AND point_code NOT IN (SELECT point_code FROM ref_model_film_point "
            "                       WHERE model_code = :m)"
        ),
        {"p": PLANT, "m": MODEL},
    )
    conn.execute(
        text(
            "UPDATE ref_plant_film_point t SET point_no = c.point_no, "
            "orientation = c.orientation, proof_hash = NULL, "
            "note = 'T54 copy of the T46/T47 model catalogue', "
            "retired_at = NULL, retired_reason = NULL "
            "FROM ref_model_film_point c "
            "WHERE t.plant_code = :p AND t.model_code = :m "
            "AND c.model_code = t.model_code AND c.point_code = t.point_code"
        ),
        {"p": PLANT, "m": MODEL},
    )
    if conn.execute(
        text("SELECT count(*) FROM ref_plant_film_point WHERE retired_at IS NOT NULL")
    ).scalar_one():
        raise RuntimeError("retired gold rows exist outside T57; refusing to drop the columns")
    op.execute(
        "ALTER TABLE ref_plant_film_point ADD CONSTRAINT uq_plant_film_point_no "
        "UNIQUE (plant_code, model_code, point_no)"
    )
    op.execute("ALTER TABLE ref_plant_film_point DROP CONSTRAINT IF EXISTS ck_plant_film_point_retired")
    op.execute(
        "ALTER TABLE ref_plant_film_point DROP COLUMN IF EXISTS retired_reason, "
        "DROP COLUMN IF EXISTS retired_at"
    )
    conn.execute(
        text(
            """
            DELETE FROM ref_film_point p
             WHERE p.point_code = ANY(:own)
               AND NOT EXISTS (SELECT 1 FROM ref_plant_film_point c WHERE c.point_code = p.point_code)
               AND NOT EXISTS (SELECT 1 FROM ref_model_film_point c WHERE c.point_code = p.point_code)
               AND NOT EXISTS (SELECT 1 FROM filmthickness f WHERE f.point_code = p.point_code)
            """
        ),
        {"own": own},
    )
