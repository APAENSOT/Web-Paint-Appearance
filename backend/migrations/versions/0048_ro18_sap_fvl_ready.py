"""RO18: own-list panel maps, month-only facts, the date and "not a point" answers.

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-14

**B1 -- a panel map may point at the plant's own live list.** The in-row
panel question offers the plant x model's live ``ref_plant_ws_point`` list.
``ref_plant_zone_map.fk_pzm_model_zone`` (-> the shared ``ref_model_zone``
catalogue) is replaced by ``fk_pzm_plant_point`` (-> ``ref_plant_ws_point
(plant_code, model_code, zone_code)``). Measured 2026-10-14: all 67 stored map
rows name an existing plant point, and every plant x model whose live list is
on the catalogue has live = catalogue (32/32, AAT U704 31/31), so nothing that
exists changes. SAP J73, SAP Ranger and FVL Ranger, whose own words are not on
the catalogue, can now be answered.

**B4 (RO09) -- month-only facts.** ``wavescan.date_is_month_only`` and
``filmthickness.date_is_month_only``, boolean, default false: a sheet with no
date anywhere is filed on the 1st of the month a person names. A check keeps
the flag honest (only ever on the 1st). Worksheet kind ``MONTH_ONLY`` (subject
``YYYY-MM``). ``reject_log.ck_reject_reason`` gains ``MONTH_UNKNOWN``: a Wave
Scan row of such a sheet is held with the month question until it is answered.
``filmthickness_active`` / ``v_wavescan_active`` / ``v_wavescan_counted`` get
the flag as their last column.

**B3 -- a sheet's date vs its file name.** Worksheet kind ``FILM_DATE_CHOICE``
(subject ``sheet`` or ``file_name``).

**B5 -- "Not a point of this list".** The tail-label table already does what
the answer needs (skipped anywhere in the walk before a point resolves, kept,
never loaded, never a hold). It gains ``not_a_point`` (default false) so the
two kinds stay distinguishable on screen and in the record. Worksheet kind
``FILM_NOT_A_POINT`` (subject = the label as written).

Grants: unchanged. ``app_rw`` holds table-level INSERT on both fact tables and
the tail-label table, which covers the new columns. Checked inside
``upgrade()``: every view's row count, every kept table's rows on its old
columns, the stored zone maps resolving to the same plant x model x panel, and
the grants.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"
ACTION = "migration.ro18.sap_fvl_ready"
ZONE_MAP = "ref_plant_zone_map"
TAIL = "ref_plant_film_tail_label"
FACTS = ("wavescan", "filmthickness")
MONTH_ONLY = "date_is_month_only"
OLD_KINDS = (
    "IGNORE_HEADER", "PLANT_CONFIRM", "HOLE_APPROVAL", "PANEL_CONFIRM",
    "FILM_MODEL_CONFLICT", "FILM_JOB_UNUSUAL", "FILM_WALK_CONFIRM",
    "FILM_POINT_ALIAS",
)
NEW_KINDS = ("MONTH_ONLY", "FILM_DATE_CHOICE", "FILM_NOT_A_POINT")
OLD_REJECT_REASONS = (
    "UNKNOWN_PLANT", "UNKNOWN_MODEL", "UNKNOWN_CHECKZONE", "UNKNOWN_COLOR",
    "UNKNOWN_PAINTLINE", "ZONE_NOT_VALID_FOR_MODEL", "MISSING_MEASUREMENT",
    "MISSING_REQUIRED_FIELD", "BAD_DATE", "BAD_NUMBER", "OUT_OF_RANGE",
    "DUPLICATE_ROW", "OTHER", "TEMPLATE_UNKNOWN", "HEADER_AMBIGUOUS",
    "UNMAPPED_COLUMN", "COLOR_NOT_OFFERED", "MODEL_NOT_OFFERED",
    "PLANT_MISMATCH", "FILM_ONLY_MODEL",
)
NEW_REJECT_REASONS = ("MONTH_UNKNOWN",)
#: table -> columns this revision adds (left out of the row comparison).
ADDED = {"wavescan": (MONTH_ONLY,), "filmthickness": (MONTH_ONLY,), TAIL: ("not_a_point",)}
#: view -> its last column today; the flag is appended after it (B4).
VIEWS = {
    "v_wavescan_active": "w.car_key",
    "v_wavescan_counted": "w.car_key",
    "filmthickness_active": "filmthickness.loaded_at",
}
KEPT = (
    ZONE_MAP, TAIL, "ref_plant_ws_point", "ref_model_zone", "worksheet_decision",
    "ref_plant_film_point", "ref_film_point_alias", "film_point_setting",
    "ws_point_setting", "wavescan", "filmthickness", "load_batch", "reject_log",
)
GRANTED = KEPT + ("stg_review_row",) + tuple(VIEWS)


def _scalar(conn, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def _views(conn) -> dict[str, int]:
    names = [r[0] for r in conn.execute(text(
        "SELECT table_name FROM information_schema.views "
        "WHERE table_schema = 'public' ORDER BY 1"
    )).all()]
    return {v: int(_scalar(conn, f'SELECT count(*) FROM "{v}"')) for v in names}


def _kept(conn) -> dict[str, tuple[int, str]]:
    """Row count and an md5 over every row, without the columns added here."""
    out = {}
    for t in KEPT:
        row = "to_jsonb(x)" + "".join(f" - '{c}'" for c in ADDED.get(t, ()))
        n, digest = conn.execute(text(
            f"SELECT count(*), md5(string_agg(md5(({row})::text), '' "
            f"ORDER BY md5(({row})::text))) FROM {t} x"
        )).one()
        out[t] = (int(n), digest or "")
    return out


def _grants(conn) -> set[tuple]:
    return {
        tuple(r) for r in conn.execute(text(
            "SELECT table_name, column_name, privilege_type "
            "FROM information_schema.column_privileges "
            "WHERE grantee = :role AND table_name = ANY(:t) "
            "UNION ALL SELECT table_name, '*', privilege_type "
            "FROM information_schema.table_privileges "
            "WHERE grantee = :role AND table_name = ANY(:t)"
        ), {"role": APP_ROLE, "t": list(GRANTED)}).all()
        # a new column inherits the table grant; compare the old columns only
        if r[1] not in (MONTH_ONLY, "not_a_point")
    }


def _map_targets(conn) -> list[tuple]:
    """Every stored zone map with the plant point it lands on (B1 proof)."""
    return [tuple(r) for r in conn.execute(text(
        f"SELECT m.map_id, m.zone_code, p.zone_code, p.retired_at IS NULL "
        f"FROM {ZONE_MAP} m LEFT JOIN ref_plant_ws_point p "
        f"ON (p.plant_code, p.model_code, p.zone_code) = "
        f"   (m.plant_code, m.model_code, m.zone_code) ORDER BY m.map_id"
    )).all()]


def _view_def(conn, view: str) -> str:
    return _scalar(conn, "SELECT pg_get_viewdef(CAST(:v AS regclass))", v=view)


def _with_flag(conn, view: str) -> str:
    """The view's definition with the month-only flag as its last column."""
    body = _view_def(conn, view)
    last = VIEWS[view]
    alias = last.split(".")[0]
    head, sep, tail = body.partition(f"    {last}\n")
    if not sep or f"{last}\n" in tail:
        raise RuntimeError(f"RO18 refused: {view}'s last column is not {last}. Rolled back.")
    return f"{head}    {last},\n    {alias}.{MONTH_ONLY}\n{tail}"


def _reason_check(reasons: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE reject_log DROP CONSTRAINT ck_reject_reason")
    listed = ", ".join(f"'{r}'::text" for r in reasons)
    op.execute(
        "ALTER TABLE reject_log ADD CONSTRAINT ck_reject_reason "
        f"CHECK (reject_reason = ANY (ARRAY[{listed}]))"
    )


def _kind_check(kinds: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE worksheet_decision DROP CONSTRAINT worksheet_decision_kind_check")
    listed = ", ".join(f"'{k}'::text" for k in kinds)
    op.execute(
        "ALTER TABLE worksheet_decision ADD CONSTRAINT worksheet_decision_kind_check "
        f"CHECK (kind = ANY (ARRAY[{listed}]))"
    )


def upgrade() -> None:
    conn = op.get_bind()
    views_before = _views(conn)
    kept_before = _kept(conn)
    grants_before = _grants(conn)
    maps_before = _map_targets(conn)
    orphans = [m for m in maps_before if m[2] is None]
    if orphans:
        raise RuntimeError(
            f"RO18 refused: {len(orphans)} zone map row(s) name no plant point "
            f"({orphans[:5]}); the new foreign key cannot hold them. Rolled back."
        )

    # --- B1 ---------------------------------------------------------------
    op.execute(f"ALTER TABLE {ZONE_MAP} DROP CONSTRAINT fk_pzm_model_zone")
    op.execute(
        f"ALTER TABLE {ZONE_MAP} ADD CONSTRAINT fk_pzm_plant_point "
        f"FOREIGN KEY (plant_code, model_code, zone_code) "
        f"REFERENCES ref_plant_ws_point (plant_code, model_code, zone_code)"
    )
    op.execute(
        f"COMMENT ON CONSTRAINT fk_pzm_plant_point ON {ZONE_MAP} IS 'RO18 (B1). "
        f"A panel map lands on a panel of that plant x model''s own list "
        f"(ref_plant_ws_point), not the shared ref_model_zone catalogue.'"
    )

    # --- B4 ---------------------------------------------------------------
    for t in FACTS:
        op.execute(
            f"ALTER TABLE {t} ADD COLUMN {MONTH_ONLY} boolean NOT NULL DEFAULT false, "
            f"ADD CONSTRAINT ck_{t}_month_only_first "
            f"CHECK (NOT {MONTH_ONLY} OR extract(day FROM measured_date) = 1)"
        )
        op.execute(
            f"COMMENT ON COLUMN {t}.{MONTH_ONLY} IS 'RO18 (B4, RO09). True when "
            f"the sheet carried no date anywhere and a person named the month: "
            f"measured_date is the 1st of that month and the day is not "
            f"recorded. Never paired (AR01).'"
        )
    # Appended last, so CREATE OR REPLACE keeps every dependent view and grant.
    for view in VIEWS:
        op.execute(f"CREATE OR REPLACE VIEW {view} AS {_with_flag(conn, view)}")

    # --- B5 ---------------------------------------------------------------
    op.execute(f"ALTER TABLE {TAIL} ADD COLUMN not_a_point boolean NOT NULL DEFAULT false")
    op.execute(
        f"COMMENT ON COLUMN {TAIL}.not_a_point IS 'RO18 (B5). True when an "
        f"uploader answered \"Not a point of this list: keep it, never load "
        f"it\" in the row. Read exactly like a tail label (skipped anywhere in "
        f"the walk, kept, never loaded); false for the end-of-sheet labels.'"
    )

    # --- B3 / B4 / B5 decision kinds; B4's Wave Scan hold reason --------
    _kind_check(OLD_KINDS + NEW_KINDS)
    _reason_check(OLD_REJECT_REASONS + NEW_REJECT_REASONS)

    # --- post-asserts: each a refusal that rolls the whole revision back ---
    views_after = _views(conn)
    if views_after != views_before:
        moved = {v: (views_before.get(v), n) for v, n in views_after.items()
                 if views_before.get(v) != n}
        raise RuntimeError(f"RO18 refused: view row counts changed: {moved}. Rolled back.")
    kept_after = _kept(conn)
    changed = [t for t in KEPT if kept_after[t] != kept_before[t]]
    if changed:
        raise RuntimeError(f"RO18 refused: rows changed in {changed}. Rolled back.")
    if _map_targets(conn) != maps_before:
        raise RuntimeError("RO18 refused: a stored zone map moved. Rolled back.")
    if _grants(conn) != grants_before:
        raise RuntimeError("RO18 refused: app_rw grants moved. Rolled back.")
    flagged = sum(
        _scalar(conn, f"SELECT count(*) FROM {t} WHERE {MONTH_ONLY}") for t in FACTS
    ) + _scalar(conn, f"SELECT count(*) FROM {TAIL} WHERE not_a_point")
    if flagged:
        raise RuntimeError("RO18 refused: a new flag is true on an old row. Rolled back.")

    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'schema', 'ro18', "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "before": json.dumps({"zone_maps": len(maps_before)}),
            "after": json.dumps({
                "revision": "0048",
                "fk": "fk_pzm_model_zone -> fk_pzm_plant_point",
                "columns": {t: list(c) for t, c in ADDED.items()},
                "kinds_added": list(NEW_KINDS),
                "reject_reasons_added": list(NEW_REJECT_REASONS),
                "owner_decision": "RO18 B1/B3/B4/B5, 2026-10-13",
            }),
        },
    )


def _views_without_flag(conn) -> None:
    """A view cannot lose a column in place: drop the three with their
    dependents and re-create every dropped view, in creation order, with its
    own definition (the flag line removed), owner, grants and comment."""
    saved = [dict(r) for r in conn.execute(text(
        "SELECT c.oid, c.relname AS name, pg_get_viewdef(c.oid) AS body, "
        "       pg_get_userbyid(c.relowner) AS owner, "
        "       obj_description(c.oid, 'pg_class') AS comment "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'v' AND n.nspname = 'public' ORDER BY c.oid"
    )).mappings().all()]
    grants = conn.execute(text(
        "SELECT table_name, grantee, privilege_type FROM information_schema.table_privileges "
        "WHERE table_schema = 'public' AND table_name = ANY(:v) AND grantee <> 'postgres'"
    ), {"v": [s["name"] for s in saved]}).all()
    op.execute(f"DROP VIEW {', '.join(VIEWS)} CASCADE")
    left = {r[0] for r in conn.execute(text(
        "SELECT table_name FROM information_schema.views WHERE table_schema = 'public'"
    )).all()}
    for view in saved:
        if view["name"] in left:
            continue
        body = view["body"]
        if view["name"] in VIEWS:
            alias = VIEWS[view["name"]].split(".")[0]
            body = body.replace(
                f"    {VIEWS[view['name']]},\n    {alias}.{MONTH_ONLY}\n",
                f"    {VIEWS[view['name']]}\n",
            )
        op.execute(f"CREATE VIEW {view['name']} AS {body}")
        op.execute(f'ALTER VIEW {view["name"]} OWNER TO "{view["owner"]}"')
        if view["comment"]:
            quoted = view["comment"].replace("'", "''")
            op.execute(f"COMMENT ON VIEW {view['name']} IS '{quoted}'")
    for table, grantee, privilege in grants:
        to = "PUBLIC" if grantee == "PUBLIC" else f'"{grantee}"'
        op.execute(f"GRANT {privilege} ON {table} TO {to}")


def downgrade() -> None:
    conn = op.get_bind()
    used = {
        "month-only facts": sum(
            _scalar(conn, f"SELECT count(*) FROM {t} WHERE {MONTH_ONLY}") for t in FACTS
        ),
        "not-a-point answers": _scalar(conn, f"SELECT count(*) FROM {TAIL} WHERE not_a_point"),
        "month questions": _scalar(
            conn, "SELECT count(*) FROM reject_log WHERE reject_reason = ANY(:r)",
            r=list(NEW_REJECT_REASONS),
        ),
        "RO18 decisions": _scalar(
            conn, "SELECT count(*) FROM worksheet_decision WHERE kind = ANY(:k)",
            k=list(NEW_KINDS),
        ),
        "maps off the catalogue": _scalar(conn, f"""
            SELECT count(*) FROM {ZONE_MAP} m WHERE NOT EXISTS (
                SELECT 1 FROM ref_model_zone z
                 WHERE (z.model_code, z.zone_code) = (m.model_code, m.zone_code))
        """),
    }
    held = {k: v for k, v in used.items() if v}
    if held:
        raise RuntimeError(
            f"RO18 rows exist ({held}); they are decisions or facts (ADR 0005). "
            f"Decide what to do with them before downgrading."
        )
    _kind_check(OLD_KINDS)
    _reason_check(OLD_REJECT_REASONS)
    _views_without_flag(conn)
    op.execute(f"ALTER TABLE {TAIL} DROP COLUMN not_a_point")
    for t in FACTS:
        op.execute(
            f"ALTER TABLE {t} DROP CONSTRAINT ck_{t}_month_only_first, "
            f"DROP COLUMN {MONTH_ONLY}"
        )
    op.execute(f"ALTER TABLE {ZONE_MAP} DROP CONSTRAINT fk_pzm_plant_point")
    op.execute(
        f"ALTER TABLE {ZONE_MAP} ADD CONSTRAINT fk_pzm_model_zone "
        f"FOREIGN KEY (model_code, zone_code) "
        f"REFERENCES ref_model_zone (model_code, zone_code)"
    )
