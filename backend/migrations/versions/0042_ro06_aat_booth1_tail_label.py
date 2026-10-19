"""RO06: AAT gets FTM's `BOOTH_1` footer as a known Film tail label.

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-12

Owner, 2026-10-12 (RO06, "option a"): only the set-up may differ between
plants; the logic is the same. Since RO04 AAT has `film_point_setting` rows,
so T99's walk rules run there. A `BOOTH_1` instrument footer written after
the last point of the walk would hold the whole sheet (`FILM_WALK_UNKNOWN`)
and offer to confirm `BOOTH_1` as a new point. FTM avoids that with its
`ref_plant_film_tail_label` rows (0033, D-99-6): a tail label is kept, never
stored, never a hold (`domain/film.py`, `FILM_TAIL_LABEL`). `app_rw` has
SELECT only on that table -- hence a migration.

Exactly two rows (D-RO06-1): (AAT, P703 DBL RANGER, BOOTH_1) and
(AAT, U704, BOOTH_1). Not the FTWISH labels: AAT files never write them.

Measured 2026-10-12: none of the 25 real AAT Film files has a `BOOTH_1` row,
so no real file's plan changes.

Guard: AAT has no tail label yet. There is no `film_point_setting` guard
(RO06-FIX): a tail label is valid on its own (`domain/film.py` reads it without
settings), and settings arrive through the app, not migrations, so such a guard
would only stop a fresh build. One `audit_event`
(`catalogue.film_tail_label.add`, actor_type `system`) names both rows.

Downgrade refuses while any AAT `stg_review_row` carries `FILM_TAIL_LABEL`
(a stored review depends on it); otherwise it deletes exactly the two rows.
The upgrade's `audit_event` stays (append-only).
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

PLANT = "AAT"
LABEL = "BOOTH_1"
#: model_code -> live points with an RO04 setting (RO04 section 11).
MODELS = {"P703 DBL RANGER": 94, "U704": 95}
NOTE = (
    "RO06 (owner 2026-10-12): AAT set up like FTM -- BOOTH_1 is the "
    "instrument footer, kept and never stored (D-99-6)"
)
EXPECTED = [
    {"plant_code": PLANT, "model_code": m, "label_norm": LABEL, "note": NOTE}
    for m in sorted(MODELS)
]
ACTION = "catalogue.film_tail_label.add"
DECIDED_BY = "owner 2026-10-12 (RO06): option a"


def _aat_tails(conn) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT plant_code, model_code, label_norm, note "
                "  FROM ref_plant_film_tail_label WHERE plant_code = :p "
                " ORDER BY model_code, label_norm"
            ),
            {"p": PLANT},
        ).mappings()
    ]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("LOCK TABLE ref_plant_film_tail_label IN SHARE ROW EXCLUSIVE MODE"))
    found = _aat_tails(conn)
    if found:
        raise RuntimeError(
            f"AAT already has Film tail labels {found}; RO06 expects none. "
            f"Nothing was changed."
        )
    conn.execute(
        text(
            "INSERT INTO ref_plant_film_tail_label "
            "(plant_code, model_code, label_norm, note) "
            "VALUES (:plant_code, :model_code, :label_norm, :note)"
        ),
        EXPECTED,
    )
    if _aat_tails(conn) != EXPECTED:
        raise RuntimeError(
            f"AAT tail labels are {_aat_tails(conn)}, not exactly {EXPECTED}. "
            f"The transaction is rolled back."
        )
    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'ref_plant_film_tail_label', :entity, "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "entity": ",".join(f"{PLANT}:{m}:{LABEL}" for m in sorted(MODELS)),
            "before": json.dumps({"aat_tail_labels": []}),
            "after": json.dumps(
                {"revision": "0042", "rows": EXPECTED, "decided_by": DECIDED_BY}
            ),
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("LOCK TABLE ref_plant_film_tail_label IN SHARE ROW EXCLUSIVE MODE"))
    stored = conn.execute(
        text(
            "SELECT count(*) FROM stg_review_row r "
            "  JOIN load_batch b USING (load_id) "
            " WHERE b.plant_code = :p AND r.reason = 'FILM_TAIL_LABEL'"
        ),
        {"p": PLANT},
    ).scalar_one()
    if stored:
        raise RuntimeError(
            f"{stored} AAT stg_review_row(s) carry FILM_TAIL_LABEL; a stored review "
            f"depends on the tail label. Nothing was changed."
        )
    deleted = conn.execute(
        text(
            "DELETE FROM ref_plant_film_tail_label "
            " WHERE plant_code = :p AND label_norm = :l AND model_code = ANY(:m) "
            "   AND note = :n"
        ),
        {"p": PLANT, "l": LABEL, "m": sorted(MODELS), "n": NOTE},
    ).rowcount
    if deleted != len(MODELS) or _aat_tails(conn):
        raise RuntimeError(
            f"deleted {deleted}, AAT tail labels left {_aat_tails(conn)}. Rolled back."
        )
