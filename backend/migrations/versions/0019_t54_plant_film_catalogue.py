"""T54: plant-scoped FilmThickness gold; FTM gold = Desert Island Blue QS 94.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-05

T53-CONTEXT D-53-01..05: each plant keeps its own Film gold list. FTM's is
the 94 location names of the Desert Island Blue Quick Summary, read from
``docs/reports/evidence/FTM-QS-film-points.json`` and from nothing else (the
workbook is not in git; its SHA-256 is on every seeded row).

1. **``ref_plant_film_point``** (plant, model, point): which gold points a
   plant's walk of a model has. ``point_no`` is display / walk proof only,
   ``orientation`` H / V is a property of that plant's point (D-53-06).
   Every plant except FTM receives a copy of today's model catalogue
   (``ref_model_film_point``, with its T47 orientation), so FVL / SAP / AAT
   resolve exactly as before. FTM receives the evidence 94 for Ranger,
   Raptor, RAPCAP and Single CAP (D-53-03). New FTM names are added to
   ``ref_film_point``.
2. **``ref_film_location_map.retired_at`` / ``retired_reason``.** The T47
   rows with ``plant_code = 'FTM'`` mapped FTM labels onto FVL gold names --
   the relabel D-53-02 forbids. 236 stored FTM facts still name FVL codes
   through them, so the rows are **not deleted**; they are marked retired
   and the loader reads live rows only. No fact is updated (ADR 0005).
3. **``filmthickness`` point FK becomes plant-scoped.** ``(model,
   point_code) -> ref_model_film_point`` is replaced by ``(plant, model,
   point_code) -> ref_plant_film_point``, added ``NOT VALID`` so the earlier
   FTM facts that carry FVL codes stay as they are (never rewritten) while
   every new row is checked against its own plant's list.
4. **Column alias ``dk grey prime`` -> ``primer`` (FILMTHICKNESS).** The
   proving file names its Layer 3 ``Dk Grey Prime``; T46 already seeded the
   ``mid / lt / grey prime`` family. Without it the uploader is asked to
   ignore the primer column.

No GRANT beyond SELECT on the new table. ``app_rw`` still has no UPDATE or
DELETE on ``filmthickness``. Downgrade refuses while any fact would break
the model-scoped FK it restores.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from alembic import op
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
# Shipped with the migrations so a fresh database can be built anywhere,
# including inside the image (docs/ is not copied there).
EVIDENCE = Path(__file__).resolve().parents[1] / "seed" / "FTM-QS-film-points.json"

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")
FTM = "FTM"
FTM_MODELS = ("P703 DBL RANGER", "P703 DBL RAPTOR", "P703 RAPCAP", "P703 SGL")
EXPECTED_POINTS = 94
OLD_FK = "filmthickness_model_point_code_fkey"
NEW_FK = "fk_ft_plant_model_point"
#: Seed column aliases (FILMTHICKNESS), read by tests the same way 0017's are.
FILM_COLUMN_ALIASES = (("dk grey prime", "primer"),)
RETIRED_REASON = (
    "T54 (D-53-02): FTM labels are FTM gold names, not FVL gold. Retired "
    "from resolve; kept because earlier FTM facts were mapped through it."
)


def _evidence() -> dict:
    if not EVIDENCE.exists():
        raise RuntimeError(f"T54 seed source missing: {EVIDENCE}")
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    points = data["locations"]
    names = [p["point_code"] for p in points]
    if (
        data.get("plant_code") != FTM
        or data.get("point_count") != EXPECTED_POINTS
        or len(set(names)) != EXPECTED_POINTS
        or [p["point_no"] for p in points] != list(range(1, EXPECTED_POINTS + 1))
        or len(str(data.get("source_sha256", "")).strip()) != 64
    ):
        raise RuntimeError("T54 evidence is not 94 distinct FTM points with a source hash")
    for p in points:
        name = p["point_code"]
        want = "H" if any(w in name for w in ("HOOD", "ROOF", "FLOOR")) else "V"
        if name != name.strip().upper() or p["orientation"] != want:
            raise RuntimeError(f"T54 evidence point {name!r} breaks the D-53-06 rule")
    return data


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
    conn = op.get_bind()
    data = _evidence()
    proof = data["source_sha256"].strip()

    # --- 1. plant-scoped gold ------------------------------------------
    op.execute(
        """
        CREATE TABLE ref_plant_film_point (
            plant_code   text NOT NULL REFERENCES ref_plant (plant_code),
            model_code   text NOT NULL REFERENCES ref_model (model_code),
            point_code   text NOT NULL REFERENCES ref_film_point (point_code),
            point_no     smallint NOT NULL CHECK (point_no > 0),
            orientation  char(1) CHECK (orientation IS NULL OR orientation IN ('H', 'V')),
            proof_hash   char(64),
            note         text,
            created_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (plant_code, model_code, point_code),
            CONSTRAINT uq_plant_film_point_no UNIQUE (plant_code, model_code, point_no)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_plant_film_point IS "
        "'T54 (D-53-01..05). Each plant''s own FilmThickness gold per model. "
        "Identity is the plant''s point name; point_no is walk proof / display "
        "only. FTM = Desert Island Blue Quick Summary 94; other plants copy "
        "the T46/T47 model catalogue.'"
    )
    op.execute(
        "COMMENT ON COLUMN ref_plant_film_point.orientation IS "
        "'H / V of this plant''s point (D-53-06): the proving picture when one "
        "is seeded, else Hood / Roof / Floor = H. Never walk order.'"
    )
    conn.execute(
        text(
            """
            INSERT INTO ref_plant_film_point
                (plant_code, model_code, point_code, point_no, orientation, note)
            SELECT p.plant_code, c.model_code, c.point_code, c.point_no,
                   c.orientation, 'T54 copy of the T46/T47 model catalogue'
              FROM ref_plant p
             CROSS JOIN ref_model_film_point c
             WHERE p.plant_code <> :ftm
            """
        ),
        {"ftm": FTM},
    )
    for point in data["locations"]:
        conn.execute(
            text(
                "INSERT INTO ref_film_point (point_code) VALUES (:p) "
                "ON CONFLICT (point_code) DO NOTHING"
            ),
            {"p": point["point_code"]},
        )
    note = f"T54 seed from {data['source_file']} {data['source_sheet']} (labels only)"
    for model in FTM_MODELS:
        for point in data["locations"]:
            conn.execute(
                text(
                    "INSERT INTO ref_plant_film_point "
                    "(plant_code, model_code, point_code, point_no, orientation, "
                    " proof_hash, note) "
                    "VALUES (:plant, :model, :point, :no, :o, :proof, :note)"
                ),
                {
                    "plant": FTM, "model": model, "point": point["point_code"],
                    "no": point["point_no"], "o": point["orientation"],
                    "proof": proof, "note": note,
                },
            )
    got = dict(conn.execute(
        text(
            "SELECT model_code, count(*) FROM ref_plant_film_point "
            "WHERE plant_code = :ftm GROUP BY 1"
        ),
        {"ftm": FTM},
    ).all())
    if got != {m: EXPECTED_POINTS for m in FTM_MODELS}:
        raise RuntimeError(f"T54 FTM gold seeded {got}")
    orient = Counter(p["orientation"] for p in data["locations"])
    print(f"T54: FTM gold 94 x {len(FTM_MODELS)} models, orientation {dict(orient)}")

    # --- 2. retire FTM's FVL-name maps from resolve -------------------
    op.execute(
        "ALTER TABLE ref_film_location_map "
        "ADD COLUMN retired_at timestamptz, ADD COLUMN retired_reason text"
    )
    op.execute(
        "ALTER TABLE ref_film_location_map ADD CONSTRAINT ck_film_map_retired "
        "CHECK ((retired_at IS NULL) = (retired_reason IS NULL))"
    )
    op.execute(
        "COMMENT ON COLUMN ref_film_location_map.retired_at IS "
        "'T54. Set: the row is a record only and the loader does not read it. "
        "Facts already mapped through it are never rewritten (ADR 0005).'"
    )
    conn.execute(
        text(
            "UPDATE ref_film_location_map SET retired_at = now(), "
            "retired_reason = :why WHERE plant_code = :ftm AND retired_at IS NULL"
        ),
        {"why": RETIRED_REASON, "ftm": FTM},
    )

    # --- 3. plant-scoped point FK on the facts ------------------------
    op.execute(f"ALTER TABLE filmthickness DROP CONSTRAINT IF EXISTS {OLD_FK}")
    op.execute(
        f"ALTER TABLE filmthickness ADD CONSTRAINT {NEW_FK} "
        "FOREIGN KEY (plant, model, point_code) REFERENCES ref_plant_film_point "
        "(plant_code, model_code, point_code) NOT VALID"
    )
    op.execute(
        f"COMMENT ON CONSTRAINT {NEW_FK} ON filmthickness IS "
        "'T54. A new film fact names a point on its own plant''s gold list. "
        "NOT VALID on purpose: earlier FTM facts mapped onto FVL names (T47) "
        "are kept as stored, never rewritten (ADR 0005).'"
    )

    # --- 4. the proving file's primer header --------------------------
    for raw, logical in FILM_COLUMN_ALIASES:
        conn.execute(
            text(
                "INSERT INTO ref_column_alias (raw_header, logical_field, is_approved, domain) "
                "SELECT :raw, :logical, true, 'FILMTHICKNESS' "
                "WHERE NOT EXISTS (SELECT 1 FROM ref_column_alias "
                "                  WHERE raw_header = :raw AND domain = 'FILMTHICKNESS')"
            ),
            {"raw": raw, "logical": logical},
        )

    op.execute("REVOKE ALL ON ref_plant_film_point FROM PUBLIC")
    _for_each_role("GRANT SELECT ON ref_plant_film_point TO {role};")


def downgrade() -> None:
    op.execute(
        r"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM filmthickness f
                 WHERE NOT EXISTS (
                     SELECT 1 FROM ref_model_film_point c
                      WHERE c.model_code = f.model AND c.point_code = f.point_code)
            ) THEN
                RAISE EXCEPTION 'filmthickness holds facts on plant-only gold names; restoring the model-scoped FK would orphan them (ADR 0005)';
            END IF;
        END $$;
        """
    )
    op.execute(f"ALTER TABLE filmthickness DROP CONSTRAINT IF EXISTS {NEW_FK}")
    op.execute(
        f"ALTER TABLE filmthickness ADD CONSTRAINT {OLD_FK} "
        "FOREIGN KEY (model, point_code) REFERENCES ref_model_film_point "
        "(model_code, point_code)"
    )
    op.execute(
        "DELETE FROM ref_column_alias WHERE raw_header = 'dk grey prime' "
        "AND domain = 'FILMTHICKNESS'"
    )
    op.execute("ALTER TABLE ref_film_location_map DROP CONSTRAINT IF EXISTS ck_film_map_retired")
    op.execute(
        "ALTER TABLE ref_film_location_map DROP COLUMN IF EXISTS retired_reason, "
        "DROP COLUMN IF EXISTS retired_at"
    )
    op.execute("DROP TABLE IF EXISTS ref_plant_film_point")
    op.execute(
        """
        DELETE FROM ref_film_point p
         WHERE NOT EXISTS (SELECT 1 FROM ref_model_film_point c WHERE c.point_code = p.point_code)
           AND NOT EXISTS (SELECT 1 FROM filmthickness f WHERE f.point_code = p.point_code)
        """
    )
