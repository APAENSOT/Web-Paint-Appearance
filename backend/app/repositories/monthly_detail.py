"""Monthly Detail reference catalogue. Measurement membership is reused from Comparison."""
from sqlalchemy import text


def offered_models(conn, plant):
    return list(conn.execute(text('SELECT model_code FROM ref_plant_model WHERE plant_code=:p AND is_offered ORDER BY model_code'), {'p': plant}).scalars())
