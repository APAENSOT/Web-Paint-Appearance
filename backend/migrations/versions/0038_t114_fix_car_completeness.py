"""T114-FIX: v_car_completeness follows the plant's live Wave Scan list.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-12

Until now a Wave Scan car was complete against ``ref_model.expected_zone_count``
(32; U704 31), a per-model number Point Check never changes -- so after a
retire every new car would read 31 / 32 and after an add a car walking the
extra point 33 / 32, both "incomplete" (T114 report, D-114-8).

**D-114F-1.** A car is complete against the **live, non-extra** points of its
plant x model list (``ref_plant_ws_point``: ``retired_at IS NULL AND NOT
is_extra``). Expected = how many such points; recorded = its readings on
them. A reading on a retired point, an extra point or a code that is not on
the list counts neither way. **D-114F-2:** counted is not read. **D-114F-4:**
a plant x model with no live list keeps the old rule (every reading against
``ref_model.expected_zone_count``). The application applies the same rule in
``app.domain.completeness`` with ``app.repositories.ws_points.live_lists``.

The view still counts **rows**, as it always has (``count(*)``), so a point
read twice is still ``EXCESS`` -- that meaning is unchanged; only which rows
count and what they are counted against changes.

``CREATE OR REPLACE`` keeps every column name and type (``zones_expected``
stays ``smallint``) and therefore the grants (``app_rw`` SELECT), which are
read back below. No view depends on this one.

**Moves no car today.** Every live list equals its model's
``expected_zone_count``, no point is extra, and every active reading joins a
live point -- so the view returns exactly the rows it returned before, which
is asserted when those three hold (and only then: once Point Check has
retired or added a point the answer is meant to differ).
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

VIEW = "v_car_completeness"

_NEW = f"""
CREATE OR REPLACE VIEW {VIEW} AS
WITH lists AS (
    SELECT plant_code, model_code, count(*) AS points
      FROM ref_plant_ws_point
     WHERE retired_at IS NULL AND NOT is_extra
     GROUP BY plant_code, model_code
), cars AS (
    SELECT w.plant, w.serial_no, w.model, w.measured_date,
           count(*) FILTER (WHERE l.points IS NULL OR p.zone_code IS NOT NULL)
                                                         AS zones_recorded,
           CAST(COALESCE(l.points, m.expected_zone_count) AS smallint)
                                                         AS zones_expected
      FROM v_wavescan_active w
      JOIN ref_model m ON m.model_code = w.model
      LEFT JOIN lists l
             ON l.plant_code = w.plant AND l.model_code = w.model
      LEFT JOIN ref_plant_ws_point p
             ON p.plant_code = w.plant AND p.model_code = w.model
            AND p.zone_code = w.checkzone
            AND p.retired_at IS NULL AND NOT p.is_extra
     GROUP BY w.plant, w.serial_no, w.model, w.measured_date,
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
       END AS completeness
  FROM cars
"""

#: The definition 0002 created, exactly (``pg_get_viewdef`` 2026-10-12).
_OLD = f"""
CREATE OR REPLACE VIEW {VIEW} AS
SELECT w.plant, w.serial_no, w.model, w.measured_date,
       count(*)                         AS zones_recorded,
       m.expected_zone_count            AS zones_expected,
       m.expected_zone_count - count(*) AS zones_missing,
       CASE
           WHEN count(*) = m.expected_zone_count THEN 'COMPLETE'
           WHEN count(*) <  m.expected_zone_count THEN 'INCOMPLETE'
           ELSE 'EXCESS'
       END                              AS completeness
  FROM v_wavescan_active w
  JOIN ref_model m ON m.model_code = w.model
 GROUP BY w.plant, w.serial_no, w.model, w.measured_date, m.expected_zone_count
"""

_COMMENT = (
    f"COMMENT ON VIEW {VIEW} IS 'Readings per Wave Scan car (plant, serial, "
    f"model, date) against the live, non-extra points of its plant x model "
    f"list (T114-FIX D-114F-1); ref_model.expected_zone_count when that "
    f"plant x model has no live list (D-114F-4).'"
)


def _rows(conn) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            text(
                f"SELECT * FROM {VIEW} "
                "ORDER BY plant, serial_no, model, measured_date"
            )
        ).all()
    ]


def _grants(conn) -> set[tuple[str, str]]:
    return {
        (r[0], r[1])
        for r in conn.execute(
            text(
                "SELECT grantee, privilege_type "
                "  FROM information_schema.role_table_grants "
                " WHERE table_schema = 'public' AND table_name = :view"
            ),
            {"view": VIEW},
        ).all()
    }


def _same_basis(conn) -> bool:
    """True while the list and the model count cannot disagree about any car."""
    differing = conn.execute(
        text(
            "SELECT count(*) FROM ("
            "  SELECT p.plant_code, p.model_code, count(*) AS points "
            "    FROM ref_plant_ws_point p "
            "   WHERE p.retired_at IS NULL AND NOT p.is_extra "
            "   GROUP BY p.plant_code, p.model_code"
            ") l JOIN ref_model m ON m.model_code = l.model_code "
            "WHERE l.points <> m.expected_zone_count"
        )
    ).scalar_one()
    extras = conn.execute(
        text("SELECT count(*) FROM ref_plant_ws_point WHERE is_extra")
    ).scalar_one()
    off_list = conn.execute(
        text(
            "SELECT count(*) FROM v_wavescan_active w "
            " WHERE EXISTS (SELECT 1 FROM ref_plant_ws_point l "
            "                WHERE l.plant_code = w.plant AND l.model_code = w.model "
            "                  AND l.retired_at IS NULL) "
            "   AND NOT EXISTS (SELECT 1 FROM ref_plant_ws_point p "
            "                    WHERE p.plant_code = w.plant AND p.model_code = w.model "
            "                      AND p.zone_code = w.checkzone "
            "                      AND p.retired_at IS NULL AND NOT p.is_extra)"
        )
    ).scalar_one()
    return differing == 0 and extras == 0 and off_list == 0


def upgrade() -> None:
    conn = op.get_bind()
    same = _same_basis(conn)
    before = _rows(conn)
    grants = _grants(conn)

    op.execute(_NEW)
    op.execute(_COMMENT)

    if same and _rows(conn) != before:
        raise RuntimeError(
            f"T114-FIX refused: every live list equals its model's "
            f"expected_zone_count, nothing is extra and every reading is on a "
            f"live point, yet {VIEW} changed. The transaction is rolled back."
        )
    if _grants(conn) != grants:
        raise RuntimeError(
            f"T114-FIX refused: the grants on {VIEW} changed "
            f"({grants} -> {_grants(conn)}). The transaction is rolled back."
        )


def downgrade() -> None:
    conn = op.get_bind()
    grants = _grants(conn)
    op.execute(_OLD)
    op.execute(
        f"COMMENT ON VIEW {VIEW} IS 'Per-vehicle zone count vs expected "
        f"(P703=32, U704=31), active rows only.'"
    )
    if _grants(conn) != grants:
        raise RuntimeError(f"Downgrade 0038 changed the grants on {VIEW}.")
