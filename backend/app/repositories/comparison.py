"""Comparison SELECTs; reuse History and Film active membership and identities."""
from sqlalchemy import Connection, text

from app.domain.history import group_vehicles
from app.repositories import filmthickness as film, history as ws
from app.repositories.ws_points import live_lists


def months(conn: Connection, plant: str, scope, domain: str) -> list[str]:
    return ws.months(conn, plant, scope) if domain == "WAVESCAN" else film.film_months(conn, plant, scope)


def models(conn: Connection, plant: str, scope, domain: str, bounds) -> list[str]:
    if domain == "WAVESCAN":
        return ws.models(conn, plant, scope, bounds)
    return film.film_distinct(conn, "model", plant, scope, bounds)


def vehicles(conn: Connection, plant: str, scope, domain: str, *, bounds=None, model=None):
    """Only selected model groups; bounds=None supports validating point IDs."""
    if domain == "WAVESCAN":
        expected = dict(conn.execute(text("SELECT model_code, expected_zone_count FROM ref_model")).all())
        # T114-FIX (D-114F-1): History's rule -- complete against the plant's live, non-extra list.
        return group_vehicles(ws.identity_groups(conn, plant, scope, bounds=bounds, model=model), expected,
                              live_lists(conn, plant))
    where, params = film._where(plant, scope, bounds=bounds, model=model)
    rows = conn.execute(text(film._VEHICLES.format(where=where)), params).all()
    return film._vehicle_rows(conn, rows)


def ws_catalogue(conn: Connection, plant: str, model: str) -> list[dict]:
    # T114: each live location carries Point Check's counted and extra tags.
    # Comparison keeps a not-counted point's readings (D-114-3); the tag says so.
    rows = conn.execute(text("SELECT p.point_no, p.zone_code AS code, p.tolerance_group AS orientation, "
                             "COALESCE(s.counted, true) AS counted, p.is_extra "
                             "FROM ref_plant_ws_point p LEFT JOIN LATERAL (SELECT counted FROM ws_point_setting ws "
                             "WHERE ws.plant_code=p.plant_code AND ws.model_code=p.model_code "
                             "AND ws.zone_code=p.zone_code ORDER BY ws.setting_id DESC LIMIT 1) s ON true "
                             "WHERE p.plant_code=:plant AND p.model_code=:model "
                             "AND p.retired_at IS NULL ORDER BY p.point_no, p.zone_code"),
                        {"plant": plant, "model": model}).mappings().all()
    return [dict(row) for row in rows]


def ws_retired_codes(conn: Connection, plant: str, model: str) -> set[str]:
    """T114 (D-114-4): this list's retired points, to tag their readings."""
    rows = conn.execute(text("SELECT zone_code FROM ref_plant_ws_point WHERE plant_code=:plant "
                             "AND model_code=:model AND retired_at IS NOT NULL"),
                        {"plant": plant, "model": model}).all()
    return {row[0] for row in rows}


def ws_points(conn: Connection, plant: str, scope, vehicle) -> list[dict]:
    return ws.points(conn, plant, scope, load_id=vehicle.load_id, measured_date=vehicle.measured_date,
                     model=vehicle.model, color=vehicle.color, serial_no=vehicle.serial_no,
                     car_key=vehicle.car_key)


def film_grid(conn: Connection, plant: str, model: str, vehicle_id: str) -> list[dict]:
    # Preserve the existing earliest load/source_row whole-point selection.
    # Sort code as a deterministic tie-breaker without changing that read.
    return sorted(film.film_point_grid(conn, plant, model, vehicle_id),
                  key=lambda p: (p["point_no"], p["point_code"]))


def ws_month_readings(conn: Connection, plant: str, scope, model: str, bounds) -> list[dict]:
    """Every active source row, including null parameters and duplicate zones."""
    where, params = ws._filtered(plant, scope, bounds=bounds, model=model)
    rows = conn.execute(text(f"""
        SELECT w.*, cf.display_order
        FROM v_wavescan_active w
        LEFT JOIN ref_plant_color pc ON pc.plant_code=w.plant AND pc.color_name=w.color
        LEFT JOIN ref_color_family cf ON cf.family_name=pc.family_name
        WHERE {where}
        ORDER BY w.measurement_id
    """), params).mappings().all()
    return [dict(r) for r in rows]


def monthly_models(conn: Connection, plant: str, scope, domain: str) -> list[str]:
    if domain == 'WAVESCAN':
        from app.repositories.measurements import ACTIVE_VIEW
        from app.repositories.overview import model_options
        # T114 (D-114-3): Comparison keeps every reading, counted or not.
        return model_options(conn, plant, scope, view=ACTIVE_VIEW)
    return film.film_distinct(conn, 'model', plant, scope, None)


def film_month_readings(conn: Connection, plant: str, scope, model: str, bounds) -> list[dict]:
    return film.film_overview_readings(conn, plant, scope, bounds=bounds, models=[model], colors=None)
