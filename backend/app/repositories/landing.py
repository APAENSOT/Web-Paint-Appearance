"""Landing card reads. SELECT only, through the authoritative active views."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from app.repositories.filmthickness import ACTIVE_VIEW as FILM_ACTIVE
from app.repositories.measurements import ACTIVE_VIEW as CF_ACTIVE

_WEEK = "LEAST(5, (EXTRACT(DAY FROM {d})::int - 1) / 7 + 1)"


def week_uploads(conn: Connection, plant: str, bounds: tuple[date, date]) -> list[dict]:
    """Per measured-date week band: each model x colour on file (either domain) and when
    its data first arrived (the batch's own start time)."""
    return [dict(r) for r in conn.execute(text(f"""
        SELECT {_WEEK.format(d="w.measured_date")} AS week, w.model, w.color,
               min(b.started_at) AS first_loaded_at
          FROM {CF_ACTIVE} w JOIN load_batch b ON b.load_id = w.load_id
         WHERE w.plant = :plant AND w.measured_date BETWEEN :start AND :end
         GROUP BY 1, 2, 3
        UNION ALL
        SELECT {_WEEK.format(d="f.measured_date")}, f.model, f.color, min(b.started_at)
          FROM {FILM_ACTIVE} f JOIN load_batch b ON b.load_id = f.load_id
         WHERE f.plant = :plant AND f.measured_date BETWEEN :start AND :end
         GROUP BY 1, 2, 3
    """), {"plant": plant, "start": bounds[0], "end": bounds[1]}).mappings().all()]


def offered(conn: Connection, plant: str) -> tuple[list[str], list[str]]:
    """The plant's standard models and colours: the same offer flags ingest reads."""
    models = conn.execute(text("""
        SELECT m.model_code FROM ref_model m
          JOIN ref_plant_model pm ON pm.model_code = m.model_code AND pm.plant_code = :plant
         WHERE m.is_active AND pm.is_offered ORDER BY m.model_code
    """), {"plant": plant}).scalars().all()
    colors = conn.execute(text("""
        SELECT color_name FROM ref_plant_color
         WHERE plant_code = :plant AND is_offered ORDER BY color_name
    """), {"plant": plant}).scalars().all()
    return list(models), list(colors)


def latest_files(conn: Connection, plant: str, limit: int = 4) -> list[dict]:
    """The newest uploaded workbooks filed under the plant, one row per file."""
    return [dict(r) for r in conn.execute(text("""
        SELECT load_id, source_file, file_hash, status, domain, started_at FROM (
            SELECT DISTINCT ON (file_hash) load_id, source_file, file_hash, status,
                   domain, started_at
              FROM load_batch WHERE plant_code = :plant
               AND sheet_class IS DISTINCT FROM 'OUT_OF_SCOPE_SHEET'
             ORDER BY file_hash, load_id DESC
        ) f ORDER BY load_id DESC LIMIT :limit
    """), {"plant": plant, "limit": limit}).mappings().all()]
