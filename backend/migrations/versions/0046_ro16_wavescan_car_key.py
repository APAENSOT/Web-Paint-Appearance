"""RO16: a Wave Scan car with no serial carries the walk it was read in.

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-13

**D-RO16-2 / D-RO16-4.** A Wave Scan sheet with no serial that holds several
cars one after another (FVL: one month, one sheet) is split into walks by the
ingest service. Each walk is one car, and when a sheet has more than one, every
blank-serial fact of it carries ``car_key``: 16 hex characters of SHA-256 over
that walk's readings. Nothing is stored as a serial: ``serial_no`` stays NULL.

* ``wavescan.car_key text NULL``. Existing rows stay NULL: ``wavescan`` is never
  updated (ADR 0005), so the column is added, never backfilled. Two checks: a
  key is 16 lower-case hex, and only a fact with no serial has one (a serial is
  already the car).
* ``app_rw`` holds table-level INSERT on ``wavescan`` (T01), so it can insert
  the new column with no new grant; it still holds no UPDATE and no DELETE.
  Both are read back off the catalog below and refused otherwise.
* The views that list ``wavescan`` columns or group cars carry it, appended
  last so ``CREATE OR REPLACE`` keeps every existing column and grant:
  ``v_wavescan_active``, ``v_wavescan_counted`` (T114) and
  ``v_car_completeness`` (0038). In the completeness view a blank-serial car
  groups by ``(plant, model, date, colour, car_key)``; a car with a serial
  groups exactly as today (its ``car_colour`` and ``car_key`` are NULL).

**Moves nothing today.** Every view returns the same rows as before on its
existing columns, asserted below while no active fact has a blank serial (the
only case the new grouping can change).

``downgrade()`` has to drop the views to remove a column (``CREATE OR REPLACE``
cannot), so it drops the six Wave Scan views, recreates them exactly as 0045
had them, and puts their grants and comments back, read back and refused if
they differ.
"""

from __future__ import annotations

import re

from alembic import op
from sqlalchemy import text

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"
ACTIVE = "v_wavescan_active"
COUNTED = "v_wavescan_counted"
COMPLETENESS = "v_car_completeness"
#: Every view over ``wavescan``, in the order they can be created.
VIEWS = (
    ACTIVE, "v_wavescan", "v_wavescan_p703", "v_wavescan_u704", COUNTED,
    COMPLETENESS,
)

_ACTIVE_COLUMNS = """
    w.measurement_id, w.measured_date, w.month, w.year, w.plant, w.model,
    w.checkzone, COALESCE(rc.merged_into, w.color) AS color,
    w.tolerance_group, w.paintline, w.serial_no,
    w.lw, w.sw, w.cf, w.doi, w.du, w.wa, w.wb, w.wc, w.wd, w.we, w.b,
    w.load_id, w.source_sheet, w.source_row, w.is_duplicate, w.loaded_at,
    w.src_zone_text, w.src_zone_no, w.is_superseded,
    w.corrects_measurement_id, w.correction_reason, w.corrected_by,
    w.corrected_at"""


def _active(extra: str) -> str:
    """``v_wavescan_active`` as 0026 left it (``pg_get_viewdef`` 2026-10-13)."""
    return f"""
CREATE OR REPLACE VIEW {ACTIVE} AS
SELECT {_ACTIVE_COLUMNS}{extra}
  FROM wavescan w
  JOIN load_batch b ON b.load_id = w.load_id
  LEFT JOIN ref_color rc ON rc.color_name = w.color
 WHERE w.is_duplicate = false AND w.is_superseded = false
   AND b.status = 'COMMITTED'
"""


_COUNTED_COLUMNS = """
    w.measurement_id, w.measured_date, w.month, w.year, w.plant, w.model,
    w.checkzone, w.color, w.tolerance_group, w.paintline, w.serial_no,
    w.lw, w.sw, w.cf, w.doi, w.du, w.wa, w.wb, w.wc, w.wd, w.we, w.b,
    w.load_id, w.source_sheet, w.source_row, w.is_duplicate, w.loaded_at,
    w.src_zone_text, w.src_zone_no, w.is_superseded,
    w.corrects_measurement_id, w.correction_reason, w.corrected_by,
    w.corrected_at"""


def _counted(extra: str) -> str:
    """``v_wavescan_counted`` as 0037 created it."""
    return f"""
CREATE OR REPLACE VIEW {COUNTED} AS
SELECT {_COUNTED_COLUMNS}{extra}
  FROM {ACTIVE} w
  JOIN ref_plant_ws_point p
    ON p.plant_code = w.plant AND p.model_code = w.model
   AND p.zone_code = w.checkzone AND p.retired_at IS NULL
  LEFT JOIN LATERAL (
        SELECT s_1.counted FROM ws_point_setting s_1
         WHERE s_1.plant_code = p.plant_code AND s_1.model_code = p.model_code
           AND s_1.zone_code = p.zone_code
         ORDER BY s_1.setting_id DESC LIMIT 1
  ) s ON true
 WHERE COALESCE(s.counted, true)
"""


def _completeness(new: bool) -> str:
    """``v_car_completeness``: 0038's, or 0038's plus the blank-serial car."""
    car = (
        "CASE WHEN w.serial_no IS NULL THEN w.color END, w.car_key, "
        if new else ""
    )
    car_out = (
        "CASE WHEN w.serial_no IS NULL THEN w.color END AS car_color, "
        "w.car_key, " if new else ""
    )
    tail = ",\n       car_color, car_key" if new else ""
    return f"""
CREATE OR REPLACE VIEW {COMPLETENESS} AS
WITH lists AS (
    SELECT plant_code, model_code, count(*) AS points
      FROM ref_plant_ws_point
     WHERE retired_at IS NULL AND NOT is_extra
     GROUP BY plant_code, model_code
), cars AS (
    SELECT w.plant, w.serial_no, w.model, w.measured_date, {car_out}
           count(*) FILTER (WHERE l.points IS NULL OR p.zone_code IS NOT NULL)
                                                         AS zones_recorded,
           CAST(COALESCE(l.points, m.expected_zone_count) AS smallint)
                                                         AS zones_expected
      FROM {ACTIVE} w
      JOIN ref_model m ON m.model_code = w.model
      LEFT JOIN lists l
             ON l.plant_code = w.plant AND l.model_code = w.model
      LEFT JOIN ref_plant_ws_point p
             ON p.plant_code = w.plant AND p.model_code = w.model
            AND p.zone_code = w.checkzone
            AND p.retired_at IS NULL AND NOT p.is_extra
     GROUP BY w.plant, w.serial_no, w.model, w.measured_date, {car}
              l.points, m.expected_zone_count
)
SELECT plant, serial_no, model, measured_date,
       zones_recorded,
       zones_expected,
       zones_expected - zones_recorded AS zones_missing,
       CASE
           WHEN zones_recorded = zones_expected THEN 'COMPLETE'
           WHEN zones_recorded < zones_expected THEN 'INCOMPLETE'
           ELSE 'EXCESS'
       END AS completeness{tail}
  FROM cars
"""


_KEY = ", w.car_key"

_COMMENT_COLUMN = (
    "COMMENT ON COLUMN wavescan.car_key IS 'RO16 (D-RO16-2). Which car of a "
    "blank-serial Wave Scan sheet holding several cars one after another this "
    "reading is: 16 hex of SHA-256 over that walk''s resolved checkzones and "
    "LW, SW, CF, DOI as written. NULL when the fact has a serial or its sheet "
    "is one car. Never a serial; never backfilled.'"
)

_COMMENT_COMPLETENESS = (
    f"COMMENT ON VIEW {COMPLETENESS} IS 'Readings per Wave Scan car against "
    f"the live, non-extra points of its plant x model list (T114-FIX "
    f"D-114F-1); ref_model.expected_zone_count when that plant x model has no "
    f"live list (D-114F-4). A car with a serial is (plant, serial, model, "
    f"date); a car with no serial is (plant, model, date, car_color, car_key) "
    f"(RO16 D-RO16-4).'"
)
_COMMENT_COMPLETENESS_0038 = (
    f"COMMENT ON VIEW {COMPLETENESS} IS 'Readings per Wave Scan car (plant, "
    f"serial, model, date) against the live, non-extra points of its plant x "
    f"model list (T114-FIX D-114F-1); ref_model.expected_zone_count when that "
    f"plant x model has no live list (D-114F-4).'"
)


# ---------------------------------------------------------------------
def _literal(sql: str) -> str:
    """``sql`` for ``text()``: a ``:word`` is not a bind parameter here."""
    return re.sub(r"(?<!:):(?=\w)", r"\:", sql)


def _scalar(conn, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def _grants(conn) -> set[tuple[str, str, str]]:
    return {
        tuple(r)
        for r in conn.execute(
            text(
                "SELECT table_name, grantee, privilege_type "
                "  FROM information_schema.role_table_grants "
                " WHERE table_schema = 'public' AND table_name = ANY(:names)"
            ),
            {"names": [*VIEWS, "wavescan"]},
        ).all()
    }


def _comments(conn) -> dict[str, str | None]:
    return {
        name: _scalar(
            conn, "SELECT obj_description(CAST(:n AS regclass), 'pg_class')", n=name
        )
        for name in VIEWS
    }


def _rows(conn, view: str, columns: str) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            text(f"SELECT {columns} FROM {view} ORDER BY {columns}")
        ).all()
    ]


_SNAPSHOT = {
    ACTIVE: "measurement_id",
    COUNTED: "measurement_id",
    COMPLETENESS: (
        "plant, serial_no, model, measured_date, zones_recorded, "
        "zones_expected, zones_missing, completeness"
    ),
}


def _snapshot(conn) -> dict[str, list[tuple]]:
    return {view: _rows(conn, view, cols) for view, cols in _SNAPSHOT.items()}


def _app_privileges(conn) -> tuple[bool, bool, bool, bool]:
    """(INSERT car_key, UPDATE car_key, UPDATE wavescan, DELETE wavescan)."""
    if not _scalar(
        conn, "SELECT count(*) FROM pg_roles WHERE rolname = :r", r=APP_ROLE
    ):
        return (True, False, False, False)  # a database with no app role yet
    return (
        _scalar(conn, f"SELECT has_column_privilege('{APP_ROLE}', 'wavescan', "
                      "'car_key', 'INSERT')"),
        _scalar(conn, f"SELECT has_column_privilege('{APP_ROLE}', 'wavescan', "
                      "'car_key', 'UPDATE')"),
        _scalar(conn, f"SELECT has_table_privilege('{APP_ROLE}', 'wavescan', "
                      "'UPDATE')"),
        _scalar(conn, f"SELECT has_table_privilege('{APP_ROLE}', 'wavescan', "
                      "'DELETE')"),
    )


def upgrade() -> None:
    conn = op.get_bind()
    blank_serial = _scalar(
        conn, f"SELECT count(*) FROM {ACTIVE} WHERE serial_no IS NULL"
    )
    before = _snapshot(conn)
    grants = _grants(conn)
    comments = _comments(conn)

    op.execute("ALTER TABLE wavescan ADD COLUMN car_key text")
    op.execute(
        "ALTER TABLE wavescan ADD CONSTRAINT ck_ws_car_key_shape "
        "CHECK (car_key IS NULL OR car_key ~ '^[0-9a-f]{16}$')"
    )
    op.execute(
        "ALTER TABLE wavescan ADD CONSTRAINT ck_ws_car_key_serialless "
        "CHECK (car_key IS NULL OR serial_no IS NULL)"
    )
    op.execute(_COMMENT_COLUMN)
    op.execute(_active(_KEY))
    op.execute(_counted(_KEY))
    op.execute(_completeness(True))
    op.execute(_COMMENT_COMPLETENESS)

    if _grants(conn) != grants:
        raise RuntimeError(
            f"RO16 refused: the grants on wavescan or its views changed "
            f"({sorted(grants ^ _grants(conn))}). Rolled back."
        )
    if {k: v for k, v in _comments(conn).items() if k != COMPLETENESS} != {
        k: v for k, v in comments.items() if k != COMPLETENESS
    }:
        raise RuntimeError("RO16 refused: a view comment changed. Rolled back.")
    if _app_privileges(conn) != (True, False, False, False):
        raise RuntimeError(
            f"RO16 refused: {APP_ROLE} must INSERT car_key and hold no UPDATE "
            f"or DELETE on wavescan; it holds {_app_privileges(conn)} "
            f"(INSERT car_key, UPDATE car_key, UPDATE, DELETE). Rolled back."
        )
    if _scalar(conn, "SELECT count(*) FROM wavescan WHERE car_key IS NOT NULL"):
        raise RuntimeError("RO16 refused: a stored fact has a car_key. Rolled back.")
    if blank_serial == 0 and _snapshot(conn) != before:
        raise RuntimeError(
            "RO16 refused: no active fact has a blank serial, yet a Wave Scan "
            "view returns different rows. Rolled back."
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _scalar(conn, "SELECT count(*) FROM wavescan WHERE car_key IS NOT NULL"):
        # Dropping the column would lose which car each reading is.
        raise RuntimeError(
            "Downgrade 0046 refused: facts carry a car_key. Rolled back."
        )
    grants = _grants(conn)
    comments = _comments(conn)
    definitions = {
        name: _scalar(conn, "SELECT pg_get_viewdef(CAST(:n AS regclass), true)", n=name)
        for name in ("v_wavescan", "v_wavescan_p703", "v_wavescan_u704")
    }
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW {name}")
    op.execute(_active(""))
    for name, body in definitions.items():
        # ``text`` leaves ``::`` casts and ``%`` alone; a ``:word`` is escaped.
        op.execute(text(f"CREATE VIEW {name} AS {_literal(body)}"))
    op.execute(_counted(""))
    op.execute(_completeness(False))
    op.execute("ALTER TABLE wavescan DROP COLUMN car_key")
    comments[COMPLETENESS] = None
    for name, comment in comments.items():
        if comment is not None:
            op.execute(text(
                f"COMMENT ON VIEW {name} IS '"
                + _literal(comment.replace("'", "''")) + "'"
            ))
    op.execute(_COMMENT_COMPLETENESS_0038)
    owner = _scalar(conn, "SELECT current_user")
    for table, grantee, privilege in sorted(grants):
        # The owner's own privileges come back with the view itself.
        if table in VIEWS and grantee != owner:
            op.execute(f'GRANT {privilege} ON {table} TO "{grantee}"')
    if _grants(conn) != grants:
        raise RuntimeError(
            f"Downgrade 0046 changed the grants ({sorted(grants ^ _grants(conn))})."
        )
