"""T58: WaveScan plant gold -- each plant x model keeps its own panel names.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-05

T58-CONTEXT D-58-01..16, the `ref_plant_film_point` rule (T54) for WaveScan.
No measurement is updated or deleted (ADR 0005); no T31 map is deleted.

1. **``ck_zone_rule``** follows D-58-04: Hood / Roof / Floor in the zone name,
   **any case**, is Horizontal. Before, ``LIKE '%HOOD%'`` made SAP
   ``01RHS Hood Rr28`` Vertical.
2. **Plant labels join ``ref_checkzone`` as themselves** (``zone_code`` =
   the proving spelling; ``panel_group`` from the name; Hor/Ver per 1). A
   code another model already has (CX743 ``1HOOD`` = FVL Ranger ``1HOOD``)
   is one row (D-58-08).
3. **``ref_plant_ws_point``** (plant, model, zone_code): live membership;
   ``point_no`` walk proof only, unique among live rows; ``tolerance_group``
   checked against ``ref_checkzone`` by FK.

   * From ``docs/reports/evidence/WS-plant-gold.json``: FVL Ranger (T28
     compact 32), FVL CX743 / V363, SAP Ranger and SAP J73 (T28 SAP 32
     each), FTM Ranger / Raptor compact dictionary (point_no 33-64, after
     the long-form 32 as in the August file).
   * Every other offered WaveScan plant x model -- AAT Ranger / Super Duty /
     U704, FTM Ranger / Raptor long-form, SAP Raptor -- copies today's
     ``ref_model_zone`` (zone_no as point_no). ``P703 RAP`` is not seeded.
   * Every (plant, model, checkzone) already stored in ``wavescan`` that is
     not live gold is kept as a **retired** row: earlier facts (``RRHOOD``
     at FVL / SAP) and their T09 corrections keep an FK target, and the
     cleaner never resolves them.
4. **Insert FK** ``fk_ws_plant_point (plant, model, checkzone) ->
   ref_plant_ws_point``, **NOT VALID**, replaces ``fk_ws_model_zone``. A U704
   liftgate still cannot land on Ranger: it is not Ranger gold at any plant.
5. ``app_rw`` / ``wavescan_loader``: SELECT on the new table only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from alembic import op
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.ws_plant_gold import gold_key, ws_panel_group, ws_tolerance  # noqa: E402

# Shipped with the migrations so a fresh database can be built anywhere,
# including inside the image (docs/ is not copied there).
EVIDENCE = Path(__file__).resolve().parents[1] / "seed" / "WS-plant-gold.json"

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")
NOTE = "T58 owner lock 2026-10-05"
COPY_NOTE = "T58 copy of ref_model_zone (long-form catalogue)"
RETIRED_REASON = (
    "T58: stored by an earlier load under the model-scoped catalogue. Kept so "
    "that fact and its corrections keep an FK target (ADR 0005); never resolved."
)
#: FTM compact points follow the long-form 32 in the August file.
FTM_COMPACT_OFFSET = 32
EXPECTED = {
    ("FVL", "P703 DBL RANGER"): 32, ("FVL", "CX743"): 32, ("FVL", "V363"): 32,
    ("SAP", "P703 DBL RANGER"): 32, ("SAP", "J73 DBL"): 32,
    ("FTM", "P703 DBL RANGER"): 32, ("FTM", "P703 DBL RAPTOR"): 32,
}
OLD_RULE = (
    "CHECK (tolerance_group = CASE WHEN zone_code LIKE '%HOOD%' OR zone_code "
    "LIKE '%ROOF%' THEN 'Horizontal' ELSE 'Vertical' END)"
)
NEW_RULE = (
    "CHECK (tolerance_group = CASE WHEN upper(zone_code) LIKE '%HOOD%' "
    "OR upper(zone_code) LIKE '%ROOF%' OR upper(zone_code) LIKE '%FLOOR%' "
    "THEN 'Horizontal' ELSE 'Vertical' END)"
)


def _evidence() -> list[dict]:
    if not EVIDENCE.exists():
        raise RuntimeError(
            f"T58 seed source missing: {EVIDENCE}. Run "
            "backend/scripts/t58_ws_plant_gold_evidence.py over the proving files."
        )
    cats = json.loads(EVIDENCE.read_text(encoding="utf-8"))["catalogues"]
    got = {(c["plant_code"], c["model_code"]): c for c in cats}
    required = {k for k in EXPECTED if k[0] != "FTM"}
    if not required <= set(got) or not set(got) <= set(EXPECTED):
        raise RuntimeError(f"T58 evidence lists {sorted(got)}; need {sorted(required)}")
    for key, cat in got.items():
        names = [p["zone_code"] for p in cat["points"]]
        keys = [gold_key(n) for n in names]
        if len(names) != EXPECTED[key] or len(set(keys)) != len(keys):
            raise RuntimeError(f"T58 evidence {key} is not {EXPECTED[key]} distinct points")
        for p in cat["points"]:
            if p["tolerance_group"] != ws_tolerance(p["zone_code"]):
                raise RuntimeError(f"T58 evidence {key} {p['zone_code']!r} breaks D-58-04")
    return cats


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
    cats = _evidence()

    # --- 1. Hor/Ver rule on the name, any case --------------------------
    op.execute("ALTER TABLE ref_checkzone DROP CONSTRAINT ck_zone_rule")
    op.execute(f"ALTER TABLE ref_checkzone ADD CONSTRAINT ck_zone_rule {NEW_RULE}")
    op.execute(
        "COMMENT ON CONSTRAINT ck_zone_rule ON ref_checkzone IS "
        "'T58 (D-58-04): Hood / Roof / Floor in the zone name, any case, is "
        "Horizontal; everything else Vertical. Never walk order.'"
    )

    # --- 2. plant labels as themselves ------------------------------------
    for cat in cats:
        for p in cat["points"]:
            code = p["zone_code"]
            conn.execute(
                text(
                    "INSERT INTO ref_checkzone (zone_code, zone_name, panel_group, tolerance_group) "
                    "VALUES (:z, :z, :g, :t) ON CONFLICT (zone_code) DO NOTHING"
                ),
                {"z": code, "g": ws_panel_group(code), "t": ws_tolerance(code)},
            )
            stored = conn.execute(
                text("SELECT tolerance_group FROM ref_checkzone WHERE zone_code = :z"),
                {"z": code},
            ).scalar_one()
            if stored != ws_tolerance(code):
                raise RuntimeError(f"ref_checkzone {code!r} is {stored}, D-58-04 says {ws_tolerance(code)}")

    # --- 3. plant gold ----------------------------------------------------
    op.execute(
        """
        CREATE TABLE ref_plant_ws_point (
            plant_code      text NOT NULL REFERENCES ref_plant (plant_code),
            model_code      text NOT NULL REFERENCES ref_model (model_code),
            zone_code       text NOT NULL,
            point_no        smallint NOT NULL CHECK (point_no > 0),
            tolerance_group text NOT NULL,
            proof_hash      char(64),
            note            text,
            retired_at      timestamptz,
            retired_reason  text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (plant_code, model_code, zone_code),
            FOREIGN KEY (zone_code, tolerance_group)
                REFERENCES ref_checkzone (zone_code, tolerance_group),
            CONSTRAINT ck_plant_ws_point_retired
                CHECK ((retired_at IS NULL) = (retired_reason IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_plant_ws_point_no_live ON ref_plant_ws_point "
        "(plant_code, model_code, point_no) WHERE retired_at IS NULL"
    )
    op.execute(
        "COMMENT ON TABLE ref_plant_ws_point IS "
        "'T58 (D-58-01..08). Each plant x model''s own WaveScan checkpoints. "
        "Identity is the plant''s panel name; point_no is walk proof only and "
        "never joins plants or models. Retired rows are records kept for "
        "earlier facts.'"
    )

    def add(plant, model, code, no, tol, proof, note):
        conn.execute(
            text(
                "INSERT INTO ref_plant_ws_point (plant_code, model_code, zone_code, "
                "point_no, tolerance_group, proof_hash, note) "
                "VALUES (:p, :m, :z, :n, :t, :h, :note)"
            ),
            {"p": plant, "m": model, "z": code, "n": no, "t": tol, "h": proof, "note": note},
        )

    seeded: set[tuple[str, str]] = set()
    for cat in cats:
        plant, model = cat["plant_code"], cat["model_code"]
        proof = next((s["sha256"] for s in cat["sources"] if s.get("sha256")), None)
        offset = FTM_COMPACT_OFFSET if plant == "FTM" else 0
        for p in cat["points"]:
            add(plant, model, p["zone_code"], p["point_no"] + offset,
                p["tolerance_group"], proof, NOTE)
        if plant != "FTM":
            seeded.add((plant, model))

    offered = conn.execute(
        text(
            "SELECT pm.plant_code, pm.model_code FROM ref_plant_model pm "
            "JOIN ref_model m ON m.model_code = pm.model_code "
            "WHERE pm.is_offered AND m.wavescan_ok ORDER BY 1, 2"
        )
    ).all()
    copied = []
    for plant, model in offered:
        if (plant, model) in seeded:
            continue
        rows = conn.execute(
            text(
                "SELECT z.zone_code, z.zone_no, c.tolerance_group FROM ref_model_zone z "
                "JOIN ref_checkzone c ON c.zone_code = z.zone_code "
                "WHERE z.model_code = :m ORDER BY z.zone_no"
            ),
            {"m": model},
        ).all()
        for code, no, tol in rows:
            add(plant, model, code, no, tol, None, COPY_NOTE)
        copied.append((plant, model, len(rows)))
    print(f"T58: copied long-form gold {copied}")

    retired = conn.execute(
        text(
            """
            INSERT INTO ref_plant_ws_point (plant_code, model_code, zone_code, point_no,
                                            tolerance_group, note, retired_at, retired_reason)
            SELECT DISTINCT w.plant, w.model, w.checkzone,
                   coalesce(z.zone_no, 1), c.tolerance_group,
                   'T58 kept for earlier facts', now(), :why
              FROM wavescan w
              JOIN ref_checkzone c ON c.zone_code = w.checkzone
              LEFT JOIN ref_model_zone z ON z.model_code = w.model AND z.zone_code = w.checkzone
             WHERE NOT EXISTS (
                   SELECT 1 FROM ref_plant_ws_point g
                    WHERE g.plant_code = w.plant AND g.model_code = w.model
                      AND g.zone_code = w.checkzone)
            """
        ),
        {"why": RETIRED_REASON},
    ).rowcount
    print(f"T58: {retired} earlier (plant, model, checkzone) kept as retired gold")

    # --- 4. the insert FK -------------------------------------------------
    op.execute("ALTER TABLE wavescan DROP CONSTRAINT IF EXISTS fk_ws_model_zone")
    op.execute(
        "ALTER TABLE wavescan ADD CONSTRAINT fk_ws_plant_point "
        "FOREIGN KEY (plant, model, checkzone) REFERENCES ref_plant_ws_point "
        "(plant_code, model_code, zone_code) NOT VALID"
    )
    op.execute(
        "COMMENT ON CONSTRAINT fk_ws_plant_point ON wavescan IS "
        "'T58 (D-58-06). A new measurement names a checkpoint on its own plant x "
        "model gold list. NOT VALID: earlier facts are never rewritten (ADR 0005).'"
    )

    # --- 5. grants --------------------------------------------------------
    op.execute("REVOKE ALL ON ref_plant_ws_point FROM PUBLIC")
    _for_each_role("GRANT SELECT ON ref_plant_ws_point TO {role};")


def downgrade() -> None:
    conn = op.get_bind()
    blocked = conn.execute(
        text(
            "SELECT count(*) FROM wavescan w WHERE NOT EXISTS (SELECT 1 FROM ref_model_zone z "
            "WHERE z.model_code = w.model AND z.zone_code = w.checkzone)"
        )
    ).scalar_one()
    if blocked:
        raise RuntimeError(
            f"{blocked} wavescan rows name plant gold outside ref_model_zone; restoring "
            "the model-scoped FK would orphan them (ADR 0005)"
        )
    op.execute("ALTER TABLE wavescan DROP CONSTRAINT IF EXISTS fk_ws_plant_point")
    op.execute(
        "ALTER TABLE wavescan ADD CONSTRAINT fk_ws_model_zone FOREIGN KEY (model, checkzone) "
        "REFERENCES ref_model_zone (model_code, zone_code)"
    )
    op.execute("DROP TABLE IF EXISTS ref_plant_ws_point")
    labels = {p["zone_code"] for c in _evidence() for p in c["points"]}
    conn.execute(
        text(
            """
            DELETE FROM ref_checkzone c
             WHERE c.zone_code = ANY(:labels)
               AND NOT EXISTS (SELECT 1 FROM ref_model_zone z WHERE z.zone_code = c.zone_code)
               AND NOT EXISTS (SELECT 1 FROM ref_checkzone_alias a WHERE a.zone_code = c.zone_code)
               AND NOT EXISTS (SELECT 1 FROM ref_plant_zone_map m WHERE m.zone_code = c.zone_code)
               AND NOT EXISTS (SELECT 1 FROM wavescan w WHERE w.checkzone = c.zone_code)
            """
        ),
        {"labels": sorted(labels)},
    )
    op.execute("ALTER TABLE ref_checkzone DROP CONSTRAINT ck_zone_rule")
    op.execute(f"ALTER TABLE ref_checkzone ADD CONSTRAINT ck_zone_rule {OLD_RULE}")
