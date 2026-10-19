"""T112-FIX: seed FTM's two FilmThickness-only offer rows before Film checks the offer.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-11

From T112-FIX "Remove from <plant>" refuses new Wave Scan **and** Film files
of that model at that plant (D-112F-1): Film ingest now asks
``ref_plant_model.is_offered`` once the model has resolved through the plant's
Film vocabulary (D-112F-2, reversing D-78-21). Every plant x model that holds
Film readings or a live Film point list already has an offered row, **except**
FTM x ``P703 RAPCAP`` and FTM x ``P703 SGL``, which have no row at all -- the
check would refuse their next file.

So this revision inserts exactly those two rows, ``is_offered = true``
(D-112F-3), and nothing else. Insert only: no row is updated or deleted, no
fact, upload or batch is touched (ADR 0005). Post-assert: every plant x model
with a live Film list or a Film fact is offered, so the new check changes
nothing for today's data.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

PLANT = "FTM"
MODELS = ("P703 RAPCAP", "P703 SGL")
ACTION = "catalogue.plant_model.seed"


def _film_pairs_not_offered(conn) -> list[tuple[str, str]]:
    """Plant x model with Film readings or a live Film list but no offer."""
    return [
        (r[0], r[1])
        for r in conn.execute(
            text(
                """
                WITH film AS (
                    SELECT plant_code, model_code FROM ref_plant_film_point
                     WHERE retired_at IS NULL
                    UNION
                    SELECT DISTINCT plant, model FROM filmthickness
                )
                SELECT f.plant_code, f.model_code FROM film f
                  LEFT JOIN ref_plant_model pm
                    ON pm.plant_code = f.plant_code AND pm.model_code = f.model_code
                 WHERE NOT COALESCE(pm.is_offered, false)
                 ORDER BY 1, 2
                """
            )
        ).all()
    ]


def upgrade() -> None:
    conn = op.get_bind()

    # --- guards ---------------------------------------------------------
    models = {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            text(
                "SELECT model_code, wavescan_ok, is_active FROM ref_model "
                "WHERE model_code = ANY(:m)"
            ),
            {"m": list(MODELS)},
        ).all()
    }
    for model in MODELS:
        if models.get(model) != (False, True):
            raise RuntimeError(
                f"T112-FIX refused: {model} should be an active FilmThickness-only "
                f"model (wavescan_ok false, is_active true); found "
                f"{models.get(model)}. Nothing was written."
            )
    existing = conn.execute(
        text(
            "SELECT model_code, is_offered FROM ref_plant_model "
            "WHERE plant_code = :p AND model_code = ANY(:m)"
        ),
        {"p": PLANT, "m": list(MODELS)},
    ).all()
    if existing:
        raise RuntimeError(
            f"T112-FIX refused: {PLANT} already has offer rows for "
            f"{[tuple(r) for r in existing]}. This revision only inserts the "
            f"two missing rows and never updates one. Nothing was written."
        )
    before_rows = conn.execute(text("SELECT count(*) FROM ref_plant_model")).scalar_one()
    missing = _film_pairs_not_offered(conn)
    if missing != [(PLANT, m) for m in MODELS]:
        raise RuntimeError(
            f"T112-FIX refused: the Film plant x model pairs without an offer "
            f"are {missing}, expected exactly {[(PLANT, m) for m in MODELS]}. "
            f"Nothing was written."
        )

    # --- the two rows ---------------------------------------------------
    inserted = 0
    for model in MODELS:
        inserted += conn.execute(
            text(
                "INSERT INTO ref_plant_model (plant_code, model_code, is_offered) "
                "VALUES (:p, :m, true)"
            ),
            {"p": PLANT, "m": model},
        ).rowcount

    # --- post-asserts ---------------------------------------------------
    after_rows = conn.execute(text("SELECT count(*) FROM ref_plant_model")).scalar_one()
    if inserted != len(MODELS) or after_rows != before_rows + len(MODELS):
        raise RuntimeError(
            f"T112-FIX refused: inserted {inserted}, ref_plant_model "
            f"{before_rows} -> {after_rows}; expected +{len(MODELS)}. The "
            f"transaction is rolled back."
        )
    still = _film_pairs_not_offered(conn)
    if still:
        raise RuntimeError(
            f"T112-FIX refused: Film plant x model pairs still not offered: "
            f"{still}. The transaction is rolled back."
        )

    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'ref_plant_model', :entity, "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "entity": f"{PLANT}:{','.join(MODELS)}",
            # Counts only, as 0035: an out-of-line audit value raises on this cluster (T77).
            "before": json.dumps({"rows": int(before_rows), "film_pairs_not_offered": 2}),
            "after": json.dumps(
                {
                    "revision": "0036",
                    "rows": int(after_rows),
                    "inserted": [f"{PLANT}:{m}" for m in MODELS],
                    "is_offered": True,
                    "owner_decision": "T112-FIX D-112F-1..D-112F-3, 2026-10-11",
                }
            ),
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    moved = conn.execute(
        text(
            "SELECT count(*) FROM audit_event "
            "WHERE entity_type = 'ref_plant_model' "
            "  AND action IN ('catalogue.plant_model.attach', 'catalogue.plant_model.offered') "
            "  AND (entity_id = ANY(:pairs) OR entity_id = ANY(:models))"
        ),
        {"pairs": [f"{PLANT}:{m}" for m in MODELS], "models": list(MODELS)},
    ).scalar_one()
    if moved:
        raise RuntimeError(
            f"{moved} Attach / Remove audit row(s) name these models. A person "
            f"has decided their offer since 0036; downgrading would erase that "
            f"decision. Decide what to do with it first."
        )
    conn.execute(
        text(
            "DELETE FROM ref_plant_model "
            "WHERE plant_code = :p AND model_code = ANY(:m) AND is_offered"
        ),
        {"p": PLANT, "m": list(MODELS)},
    )
