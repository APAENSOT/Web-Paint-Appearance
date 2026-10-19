"""Reference data reads.

`ref_color.grading_family` is selected and passed through as-is. It stays
NULL; plant-scoped family lives on ``ref_plant_color`` (ADR 0010). This
module does not substitute ``color_group`` for a family.

``ref_color_family`` is not listed on GET /meta. Admin catalogue is
``GET /api/v1/standards/catalogue``.
"""

from __future__ import annotations

from sqlalchemy import Connection, text


def list_plants(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT plant_code, plant_name, country, is_active "
            "FROM ref_plant ORDER BY plant_code"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def list_models(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT model_code, model_family, body_style, expected_zone_count, "
            "is_active FROM ref_model WHERE wavescan_ok ORDER BY model_code"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def list_colors(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT color_name, color_group, is_active, grading_family "
            "FROM ref_color ORDER BY color_name"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def list_checkzones(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT zone_code, zone_name, panel_group, tolerance_group "
            "FROM ref_checkzone ORDER BY zone_code"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def unmapped_offered_count(conn: Connection) -> int:
    """Offered plant-colours with no family (spec S10)."""
    value = conn.execute(
        text(
            "SELECT count(*) FROM ref_plant_color "
            "WHERE is_offered AND family_name IS NULL"
        )
    ).scalar()
    return int(value or 0)
