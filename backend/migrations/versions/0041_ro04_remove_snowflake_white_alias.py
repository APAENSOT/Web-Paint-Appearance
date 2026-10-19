"""RO04: remove the four `Snowflake White_4 -> Arctic White` colour aliases.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-12

Owner, 2026-10-12: "Snowflake White, Arctic White, Pearl White are different
colours." The T57 / T60 owner locks of 2026-10-05 aliased the spelling
`Snowflake White_4` onto Arctic White at every plant (alias_id 219 AAT,
240 FVL, 243 SAP, 246 FTM). That folds a different colour into Arctic White,
so the four rows go (D-RO04-2). There is no app path that changes or removes
a colour alias, and a new answer for the same spelling collides with
`uq_color_alias_plant` -- hence a migration.

Measured 2026-10-12 on t02_dev: 0 `stg_raw`, 0 `load_batch.raw_headers` and
0 `stg_review_row.canonical` mention "snowflake", so no stored reading at any
plant moved through these rows; the guard re-checks that and refuses
otherwise. No `ref_color` row is added or changed: minting Snowflake White is
the owner's next decision, not this one. A later file writing the spelling
holds as `UNKNOWN_COLOR`.

One `audit_event` (`catalogue.color_alias.remove`, actor_type `system`) keeps
the four rows' full before-image (small enough to stay inline).

Downgrade re-inserts the same four rows (same `alias_id`, values, notes) and
refuses if any of those ids or (plant, raw_value) pairs is taken. The upgrade's
`audit_event` stays (append-only).
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

RAW = "Snowflake White_4"
COLOUR = "Arctic White"
#: (alias_id, plant_code, note) exactly as stored on 2026-10-12.
ROWS = (
    (219, "AAT", "T57 owner lock 2026-10-05"),
    (240, "FVL", "T60 owner lock 2026-10-05"),
    (243, "SAP", "T60 owner lock 2026-10-05"),
    (246, "FTM", "T60 owner lock 2026-10-05"),
)
IDS = [alias_id for alias_id, _, _ in ROWS]
EXPECTED = [
    {"alias_id": a, "plant_code": p, "raw_value": RAW, "color_name": COLOUR, "note": n}
    for a, p, n in ROWS
]
ACTION = "catalogue.color_alias.remove"
DECIDED_BY = (
    "owner 2026-10-12 (RO04): Snowflake White, Arctic White and Pearl White "
    "are different colours"
)
#: Where a stored reading or review row could carry the spelling.
DEPENDENTS = {
    "stg_raw": (
        "SELECT count(*) FROM stg_raw "
        "WHERE coalesce(raw_color, '') ILIKE '%snowflake%' "
        "   OR extra::text ILIKE '%snowflake%' "
        "   OR coalesce(raw_headers::text, '') ILIKE '%snowflake%'"
    ),
    "load_batch": (
        "SELECT count(*) FROM load_batch "
        "WHERE coalesce(raw_headers::text, '') ILIKE '%snowflake%'"
    ),
    "stg_review_row": (
        "SELECT count(*) FROM stg_review_row "
        "WHERE coalesce(canonical::text, '') ILIKE '%snowflake%'"
    ),
}


def _snowflake_rows(conn, *, lock: bool = False) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT alias_id, plant_code, raw_value, color_name, note "
                "  FROM ref_color_alias WHERE raw_value ILIKE 'Snowflake White%' "
                " ORDER BY alias_id" + (" FOR UPDATE" if lock else "")
            )
        ).mappings()
    ]


def _total(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM ref_color_alias")).scalar_one()


def upgrade() -> None:
    conn = op.get_bind()
    found = _snowflake_rows(conn, lock=True)
    if found != EXPECTED:
        raise RuntimeError(
            f"ref_color_alias 'Snowflake White%' rows are {found}, not the four "
            f"RO04 names ({EXPECTED}). Nothing was changed."
        )
    for table, sql in DEPENDENTS.items():
        n = conn.execute(text(sql)).scalar_one()
        if n:
            raise RuntimeError(
                f"{n} {table} row(s) mention 'snowflake'; removing the alias could "
                f"change what they mean. Nothing was changed."
            )
    before_total = _total(conn)
    deleted = conn.execute(
        text("DELETE FROM ref_color_alias WHERE alias_id = ANY(:ids)"), {"ids": IDS}
    ).rowcount
    after_total = _total(conn)
    still = _snowflake_rows(conn)
    if deleted != len(ROWS) or after_total != before_total - len(ROWS) or still:
        raise RuntimeError(
            f"deleted {deleted}, ref_color_alias {before_total} -> {after_total}, "
            f"'Snowflake White%' left: {still}. The transaction is rolled back."
        )
    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'ref_color_alias', :entity, "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "entity": ",".join(str(i) for i in IDS),
            "before": json.dumps({"rows": EXPECTED, "ref_color_alias_rows": before_total}),
            "after": json.dumps(
                {
                    "revision": "0041",
                    "removed_alias_ids": IDS,
                    "ref_color_alias_rows": after_total,
                    "decided_by": DECIDED_BY,
                }
            ),
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    taken = conn.execute(
        text(
            "SELECT alias_id, plant_code, raw_value FROM ref_color_alias "
            " WHERE alias_id = ANY(:ids) "
            "    OR (plant_code = ANY(:plants) AND raw_value = :raw) "
            " ORDER BY alias_id"
        ),
        {"ids": IDS, "plants": [p for _, p, _ in ROWS], "raw": RAW},
    ).all()
    if taken:
        raise RuntimeError(
            f"{[tuple(r) for r in taken]} already hold an RO04 alias_id or "
            f"(plant, '{RAW}'). Nothing was changed."
        )
    before_total = _total(conn)
    conn.execute(
        text(
            "INSERT INTO ref_color_alias (alias_id, plant_code, raw_value, color_name, note) "
            "VALUES (:alias_id, :plant_code, :raw_value, :color_name, :note)"
        ),
        EXPECTED,
    )
    if _snowflake_rows(conn) != EXPECTED or _total(conn) != before_total + len(ROWS):
        raise RuntimeError("the four rows did not come back exactly. Rolled back.")
