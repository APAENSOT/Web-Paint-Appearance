"""RO17: every plant names its points in its own words; retire columns for aliases.

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-13

**D-RO17-1 / -2 / -5.** A point keeps its code (``zone_code`` / ``point_code``)
and its key; every stored fact keeps the code it has (ADR 0005). Each point
gets a **label**: the word its plant uses. Two append-only tables, one per
domain, so each label row has a real foreign key to the point it names
(one shared table could not reference two point tables):

* ``ref_plant_ws_point_label``  -> ``ref_plant_ws_point (plant, model, zone)``
* ``ref_plant_film_point_label`` -> ``ref_plant_film_point (plant, model, point)``

Each row: the label as written, ``label_norm`` (the domain's own normaliser,
``normalise_alias`` / ``normalise_location``, computed by the application),
who, when, why. The **current** label is the newest row (highest
``label_id``). A label row is never updated except its two retire columns,
which only the aliases screen sets on an **earlier** spelling (D-RO17-13);
the current label is never retired. ``app_rw``: SELECT, INSERT, UPDATE of
``retired_at, retired_reason`` only; no DELETE.

Initial rows (D-RO17-5): every **live** point gets one label equal to its code,
``reason = 'initial: the code'``. Resolution answers the code first, so
nothing anybody sees or loads changes until a label differs from its code.

**Retire columns (D-RO17-9, -12, -13).**

* ``ref_plant_zone_map``: gains ``retired_at`` / ``retired_reason`` (both or
  neither). Its unique key ``(plant, model, raw_zone_text)`` becomes a
  **partial** unique index on live rows, so "repoint = retire + teach again"
  can insert the new answer beside the retired record. Every INSERT into it is
  a plain INSERT (no ``ON CONFLICT``), measured. ``app_rw`` gets UPDATE of the
  two columns.
* ``ref_film_point_alias``, ``ref_film_location_map``: already have the
  columns; ``app_rw`` gets UPDATE of exactly those two.
* ``ref_plant_film_tail_label``: gains the two columns; ``app_rw`` gets INSERT
  and UPDATE of the two columns (it had SELECT only).
* Restore of a retired point (D-RO17-9) clears ``retired_at`` /
  ``retired_reason`` on ``ref_plant_ws_point`` / ``ref_plant_film_point``.
  ``app_rw`` already holds UPDATE on exactly those columns; the only check is
  ``(retired_at IS NULL) = (retired_reason IS NULL)`` and there is no trigger,
  so clearing both needs **no** grant. Measured 2026-10-13, nothing added.

No view changes: ``v_car_completeness`` already counts the live, non-extra
points (D-RO17-7). Checked inside ``upgrade()``: every live point has exactly
one label, every view returns the same row count, the point / alias / map
tables hold the same rows, and ``app_rw`` holds exactly the grants above.
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

from app.domain.film import normalise_location  # noqa: E402
from app.domain.references import normalise_alias  # noqa: E402

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"
ACTION = "migration.ro17.point_labels"
INITIAL_REASON = "initial: the code"
RETIRE_COLUMNS = ("retired_at", "retired_reason")

WS_LABEL = "ref_plant_ws_point_label"
FILM_LABEL = "ref_plant_film_point_label"
#: label table -> (point table, code column, normaliser)
LABELS = {
    WS_LABEL: ("ref_plant_ws_point", "zone_code", normalise_alias),
    FILM_LABEL: ("ref_plant_film_point", "point_code", normalise_location),
}
ZONE_MAP = "ref_plant_zone_map"
TAIL = "ref_plant_film_tail_label"
#: Tables whose rows this revision must leave exactly as they are.
KEPT = (
    "ref_plant_ws_point", "ref_plant_film_point", ZONE_MAP, TAIL,
    "ref_film_point_alias", "ref_film_location_map", "ref_checkzone_alias",
    "film_point_setting", "ws_point_setting", "wavescan", "filmthickness",
    "load_batch",
)
#: table -> the UPDATE columns app_rw must hold after the upgrade.
UPDATE_AFTER = {
    WS_LABEL: set(RETIRE_COLUMNS),
    FILM_LABEL: set(RETIRE_COLUMNS),
    ZONE_MAP: {
        "approved_at", "approved_by", "confidence", "note", "proof_document",
        "proof_hash", "proposal_method", "raw_position", "verified_by",
        *RETIRE_COLUMNS,
    },
    "ref_film_point_alias": set(RETIRE_COLUMNS),
    "ref_film_location_map": set(RETIRE_COLUMNS),
    TAIL: set(RETIRE_COLUMNS),
    "ref_plant_ws_point": set(RETIRE_COLUMNS),
    "ref_plant_film_point": set(RETIRE_COLUMNS),
}


# =====================================================================
# measurements
# =====================================================================
def _scalar(conn, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def _views(conn) -> dict[str, int]:
    names = [
        r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = 'public' ORDER BY 1"
        )).all()
    ]
    return {v: int(_scalar(conn, f'SELECT count(*) FROM "{v}"')) for v in names}


def _kept(conn) -> dict[str, tuple[int, str]]:
    """Row count and an md5 over every row of each kept table, in key order."""
    out = {}
    for t in KEPT:
        n, digest = conn.execute(text(
            f"SELECT count(*), md5(string_agg(md5(x::text), '' ORDER BY md5(x::text))) "
            f"FROM {t} x"
        )).one()
        out[t] = (int(n), digest or "")
    return out


def _kept_cols(conn) -> dict[str, tuple[int, str]]:
    """As `_kept`, but over the columns that existed before this revision.

    ``ref_plant_zone_map`` and ``ref_plant_film_tail_label`` gain two columns,
    so their whole-row text changes; their old columns must not.
    """
    cols = {
        ZONE_MAP: "map_id, plant_code, model_code, raw_zone_text, raw_position, "
                  "zone_code, confidence, proposal_method, approved_by, "
                  "approved_at, created_at, note, proof_hash, proof_document, "
                  "verified_by",
        TAIL: "plant_code, model_code, label_norm, note, created_at",
    }
    out = {}
    for t, c in cols.items():
        n, digest = conn.execute(text(
            f"SELECT count(*), md5(string_agg(md5(ROW({c})::text), '' "
            f"ORDER BY md5(ROW({c})::text))) FROM {t}"
        )).one()
        out[t] = (int(n), digest or "")
    return out


def _update_grants(conn, table: str) -> set[str]:
    return {
        r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.column_privileges "
            "WHERE table_name = :t AND grantee = :role "
            "  AND privilege_type = 'UPDATE'"
        ), {"t": table, "role": APP_ROLE}).all()
    }


def _table_grants(conn, table: str) -> set[str]:
    return {
        r[0] for r in conn.execute(text(
            "SELECT privilege_type FROM information_schema.table_privileges "
            "WHERE table_name = :t AND grantee = :role"
        ), {"t": table, "role": APP_ROLE}).all()
    }


# =====================================================================
# upgrade
# =====================================================================
def _label_table(name: str, point_table: str, code: str) -> None:
    short = "ws" if name == WS_LABEL else "film"
    op.execute(f"""
        CREATE TABLE {name} (
            label_id       bigserial PRIMARY KEY,
            plant_code     text NOT NULL,
            model_code     text NOT NULL,
            {code}         text NOT NULL,
            label          text NOT NULL CHECK (length(btrim(label)) > 0),
            label_norm     text NOT NULL CHECK (length(label_norm) > 0),
            set_by         uuid REFERENCES app_user (id),
            set_at         timestamptz NOT NULL DEFAULT now(),
            reason         text NOT NULL CHECK (length(btrim(reason)) > 0),
            retired_at     timestamptz,
            retired_reason text,
            CONSTRAINT ck_{short}_point_label_retired
                CHECK ((retired_at IS NULL) = (retired_reason IS NULL)),
            CONSTRAINT fk_{short}_point_label_point
                FOREIGN KEY (plant_code, model_code, {code})
                REFERENCES {point_table} (plant_code, model_code, {code})
        )
    """)
    op.execute(
        f"CREATE INDEX ix_{short}_point_label_current ON {name} "
        f"(plant_code, model_code, {code}, label_id DESC)"
    )
    op.execute(
        f"CREATE INDEX ix_{short}_point_label_norm ON {name} "
        f"(plant_code, model_code, label_norm)"
    )
    op.execute(
        f"COMMENT ON TABLE {name} IS 'RO17 (D-RO17-1, -2). The word a plant "
        f"uses for one of its points, per plant x model. Append-only: the "
        f"current label is the newest row (highest label_id); a rename is a "
        f"new row, never an update. Every label, current and earlier, resolves "
        f"to its point on upload at that plant x model only, after every other "
        f"route (D-RO17-3). retired_at / retired_reason are set only on an "
        f"earlier spelling, from the aliases screen (D-RO17-13). Stored facts "
        f"keep their code; nothing is rewritten (ADR 0005).'"
    )
    op.execute(f"REVOKE ALL ON {name} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON {name} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {name}_label_id_seq TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({', '.join(RETIRE_COLUMNS)}) ON {name} TO {APP_ROLE}")


def _retire_columns(table: str, check: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN retired_at timestamptz, "
        f"ADD COLUMN retired_reason text, "
        f"ADD CONSTRAINT {check} CHECK ((retired_at IS NULL) = (retired_reason IS NULL))"
    )


def _ddl() -> None:
    for name, (point_table, code, _) in LABELS.items():
        _label_table(name, point_table, code)

    _retire_columns(ZONE_MAP, "ck_pzm_retired")
    op.execute(f"ALTER TABLE {ZONE_MAP} DROP CONSTRAINT uq_plant_zone_map")
    op.execute(
        f"CREATE UNIQUE INDEX uq_plant_zone_map_live ON {ZONE_MAP} "
        f"(plant_code, model_code, raw_zone_text) WHERE retired_at IS NULL"
    )
    op.execute(
        f"COMMENT ON COLUMN {ZONE_MAP}.retired_at IS 'RO17 (D-RO17-13). When "
        f"an Admin retired this spelling on the aliases screen. A retired row "
        f"is a record only: it no longer resolves. One live row per (plant, "
        f"model, raw_zone_text) (uq_plant_zone_map_live), so repoint = retire "
        f"+ teach again.'"
    )

    _retire_columns(TAIL, "ck_tail_label_retired")
    op.execute(
        f"COMMENT ON COLUMN {TAIL}.retired_at IS 'RO17 (D-RO17-12). When an "
        f"Admin retired this tail label on the Film point screen. A retired "
        f"tail label is a record only; adding it again clears these two "
        f"columns.'"
    )

    op.execute(f"GRANT UPDATE ({', '.join(RETIRE_COLUMNS)}) ON {ZONE_MAP} TO {APP_ROLE}")
    op.execute(
        f"GRANT UPDATE ({', '.join(RETIRE_COLUMNS)}) ON ref_film_point_alias TO {APP_ROLE}"
    )
    op.execute(
        f"GRANT UPDATE ({', '.join(RETIRE_COLUMNS)}) ON ref_film_location_map TO {APP_ROLE}"
    )
    op.execute(f"GRANT INSERT ON {TAIL} TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({', '.join(RETIRE_COLUMNS)}) ON {TAIL} TO {APP_ROLE}")


def _seed(conn) -> dict[str, int]:
    """D-RO17-5: one label per live point, equal to its code."""
    written = {}
    for name, (point_table, code, norm) in LABELS.items():
        rows = conn.execute(text(
            f"SELECT plant_code, model_code, {code} FROM {point_table} "
            f"WHERE retired_at IS NULL ORDER BY plant_code, model_code, point_no, {code}"
        )).all()
        for plant, model, value in rows:
            conn.execute(text(
                f"INSERT INTO {name} (plant_code, model_code, {code}, label, "
                f"label_norm, set_by, reason) "
                f"VALUES (:p, :m, :c, :c, :n, NULL, :r)"
            ), {"p": plant, "m": model, "c": value, "n": norm(value), "r": INITIAL_REASON})
        written[name] = len(rows)
    return written


def upgrade() -> None:
    conn = op.get_bind()
    views_before = _views(conn)
    kept_before = _kept(conn)
    cols_before = _kept_cols(conn)
    grants_before = {t: _table_grants(conn, t) for t in UPDATE_AFTER}
    live_before = {
        t: int(_scalar(conn, f"SELECT count(*) FROM {t} WHERE retired_at IS NULL"))
        for t in ("ref_plant_ws_point", "ref_plant_film_point")
    }

    _ddl()
    written = _seed(conn)

    # --- post-asserts: each a refusal that rolls the whole revision back ---
    for name, (point_table, code, _) in LABELS.items():
        bad = _scalar(conn, f"""
            SELECT count(*) FROM {point_table} p
             WHERE p.retired_at IS NULL
               AND (SELECT count(*) FROM {name} l
                     WHERE l.plant_code = p.plant_code AND l.model_code = p.model_code
                       AND l.{code} = p.{code}) <> 1
        """)
        total = _scalar(conn, f"SELECT count(*) FROM {name}")
        live = live_before[point_table]
        if bad or total != live or written[name] != live:
            raise RuntimeError(
                f"RO17 refused: {name} holds {total} rows for {live} live points "
                f"({bad} live point(s) without exactly one label). Rolled back."
            )
    views_after = _views(conn)
    if views_after != views_before:
        moved = {v: (views_before.get(v), n) for v, n in views_after.items()
                 if views_before.get(v) != n}
        raise RuntimeError(f"RO17 refused: view row counts changed: {moved}. Rolled back.")
    kept_after = _kept(conn)
    changed = [
        t for t in KEPT
        if t not in (ZONE_MAP, TAIL) and kept_after[t] != kept_before[t]
    ]
    if changed or _kept_cols(conn) != cols_before:
        raise RuntimeError(
            f"RO17 refused: rows changed in {changed or 'the zone map / tail labels'}. "
            f"This revision adds tables, columns and grants only. Rolled back."
        )
    for table, expected in UPDATE_AFTER.items():
        found = _update_grants(conn, table)
        if found != expected:
            raise RuntimeError(
                f"RO17 refused: {APP_ROLE} may UPDATE {sorted(found)} of {table}, "
                f"expected {sorted(expected)}. Rolled back."
            )
        grants = _table_grants(conn, table)
        if "DELETE" in grants or "TRUNCATE" in grants:
            raise RuntimeError(f"RO17 refused: {APP_ROLE} holds DELETE on {table}. Rolled back.")
        if table not in LABELS and table != TAIL and grants != grants_before[table]:
            raise RuntimeError(
                f"RO17 refused: {APP_ROLE}'s table grants on {table} moved "
                f"{sorted(grants_before[table])} -> {sorted(grants)}. Rolled back."
            )
    for name in LABELS:
        if _table_grants(conn, name) != {"SELECT", "INSERT"}:
            raise RuntimeError(f"RO17 refused: {APP_ROLE} table grants on {name} wrong. Rolled back.")
    if _table_grants(conn, TAIL) != {"SELECT", "INSERT"}:
        raise RuntimeError(f"RO17 refused: {APP_ROLE} table grants on {TAIL} wrong. Rolled back.")

    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'point_label', 'all', "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            # Counts only: audit_event TOAST files are missing (T77).
            "before": json.dumps({"live_points": live_before}),
            "after": json.dumps({
                "revision": "0047", "initial_labels": written,
                "retire_columns_added": [ZONE_MAP, TAIL],
                "owner_decision": "RO17 D-RO17-1..-13, 2026-10-13",
            }),
        },
    )


# =====================================================================
# downgrade
# =====================================================================
def downgrade() -> None:
    conn = op.get_bind()
    for name in LABELS:
        own = _scalar(
            conn,
            f"SELECT count(*) FROM {name} WHERE reason <> :r OR retired_at IS NOT NULL",
            r=INITIAL_REASON,
        )
        if own:
            raise RuntimeError(
                f"{own} label row(s) in {name} are a plant's own words or a "
                f"retirement somebody decided (ADR 0005). Decide what to do with "
                f"them before downgrading."
            )
    for table in (ZONE_MAP, TAIL):
        retired = _scalar(conn, f"SELECT count(*) FROM {table} WHERE retired_at IS NOT NULL")
        if retired:
            raise RuntimeError(
                f"{retired} row(s) of {table} were retired after 0047. Dropping "
                f"the columns would bring them back to life. Decide first."
            )
    twins = _scalar(conn, f"""
        SELECT count(*) FROM (
            SELECT 1 FROM {ZONE_MAP}
             GROUP BY plant_code, model_code, raw_zone_text HAVING count(*) > 1
        ) x
    """)
    if twins:
        raise RuntimeError(
            f"{twins} spelling(s) of {ZONE_MAP} were taught again after a retire; "
            f"the old unique key cannot hold them. Decide first."
        )
    # A tail label added after 0047 is a valid row of the old table too; it stays.
    op.execute(f"REVOKE UPDATE ({', '.join(RETIRE_COLUMNS)}) ON {TAIL} FROM {APP_ROLE}")
    op.execute(f"REVOKE INSERT ON {TAIL} FROM {APP_ROLE}")
    op.execute(
        f"REVOKE UPDATE ({', '.join(RETIRE_COLUMNS)}) ON ref_film_location_map FROM {APP_ROLE}"
    )
    op.execute(
        f"REVOKE UPDATE ({', '.join(RETIRE_COLUMNS)}) ON ref_film_point_alias FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE UPDATE ({', '.join(RETIRE_COLUMNS)}) ON {ZONE_MAP} FROM {APP_ROLE}")
    op.execute(f"ALTER TABLE {TAIL} DROP CONSTRAINT ck_tail_label_retired, "
               f"DROP COLUMN retired_reason, DROP COLUMN retired_at")
    op.execute("DROP INDEX uq_plant_zone_map_live")
    op.execute(
        f"ALTER TABLE {ZONE_MAP} ADD CONSTRAINT uq_plant_zone_map "
        f"UNIQUE (plant_code, model_code, raw_zone_text)"
    )
    op.execute(f"ALTER TABLE {ZONE_MAP} DROP CONSTRAINT ck_pzm_retired, "
               f"DROP COLUMN retired_reason, DROP COLUMN retired_at")
    for name in LABELS:
        op.execute(f"DROP TABLE {name}")
