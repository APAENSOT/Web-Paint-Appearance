"""T85: build a FilmThickness month out of nothing, for the read tests.

Why this exists. T66, T67, T68 and T73 were written against the owner's own
Film uploads -- AAT September, FTM 2026-05, SAP 2026-08 -- and asserted
things about them: how many readings there were, which colours were walked,
how many fell below minimum. T85 cleared every one of those rows by owner
decision, so the assertions became ``assert 0 > 1000`` and
``assert set() == {...}``: not wrong, just about data that no longer exists.

The *claims* those tests make are about the **read path** -- grain, spec
lines, status, out-of-spec membership -- and a read path can be exercised on
rows a test makes for itself. So these helpers insert a committed Film batch
directly, as the owner, with values the caller chose. The caller then
asserts the same thing it always did, about rows it owns.

**Not through ingest, on purpose.** `tests/test_t46_filmthickness.pelt` goes
through the real uploader and is the right tool for testing *ingest*; it
also has to satisfy per-plant filename model resolution (T78), which is a
different subject from "does the overview group by orientation". These
helpers write the fact table directly, so a read test can name the plant,
model, colour, layer, orientation and value it needs and get exactly that.

Every row carries the batch's own `load_id`, and `film_month` removes the
batch and its facts itself. Nothing shared is written, and no row that
anyone else created is read or touched (`AGENTS.md`, T64 incident).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class FilmPoint:
    """One checkpoint of a plant x model gold list, with its orientation."""

    point_code: str
    orientation: str


def gold_points(admin_conn, plant: str, model: str, per_orientation: int = 2
                ) -> list[FilmPoint]:
    """The first `per_orientation` live H points and V points of this list.

    Read from `ref_plant_film_point` rather than typed, so a test never
    names a plant's checkpoint itself (`AGENTS.md` rule 6) and the rows it
    writes satisfy `fk_ft_plant_model_point`.
    """
    out: list[FilmPoint] = []
    with admin_conn.cursor() as cur:
        for orientation in ("H", "V"):
            cur.execute(
                """
                SELECT point_code FROM ref_plant_film_point
                 WHERE plant_code = %s AND model_code = %s
                   AND retired_at IS NULL AND btrim(orientation) = %s
                 ORDER BY point_no LIMIT %s
                """,
                (plant, model, orientation, per_orientation),
            )
            out.extend(FilmPoint(row[0], orientation) for row in cur.fetchall())
    return out


def film_month(
    admin_conn,
    *,
    plant: str,
    model: str,
    colour: str,
    day: str,
    readings: dict[str, dict[str, float | None]],
    vehicles: int = 2,
    car_delta: float = 0.1,
) -> dict:
    """One committed Film batch: `vehicles` cars, each walking `readings`.

    `readings` is ``{point_code: {layer_code: thickness or None}}``. A
    ``None`` writes no row at all -- a blank layer is skipped, never stored
    as a zero, which is the thing T66 claim 3 is about.

    Each extra car shifts every reading by `car_delta`, so two cars never
    produce the identical value twice -- a box whose readings are all equal
    cannot show an ordering, an outlier or a whisker, and several of these
    tests are about exactly those.

    Returns the batch and the rows written, so the caller can assert against
    its own data and nothing else. Call `forget_film_month` in teardown.
    """
    rows: list[dict] = []
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO load_batch (source_file, source_sheet, file_hash, "
            "  raw_store_key, status, plant_code) "
            "VALUES (%s, 'Quick Summary', %s, 'k', 'COMMITTED', %s) RETURNING load_id",
            (f"t85-film-{uuid.uuid4().hex[:8]}.xlsx",
             uuid.uuid4().hex + uuid.uuid4().hex, plant),
        )
        load_id = cur.fetchone()[0]
        source_row = 0
        for car in range(vehicles):
            # 64 hex characters, the shape `domain.film.logical_vehicle_id`
            # produces, because the read contract says so and a test asserts it.
            vehicle = hashlib.sha256(f"t85:{load_id}:{car}".encode()).hexdigest()
            for point_code, layers in readings.items():
                source_row += 1
                for layer, base_value in layers.items():
                    if base_value is None:
                        continue
                    thickness = round(float(base_value) + car * car_delta, 4)
                    cur.execute(
                        "INSERT INTO filmthickness (measured_date, plant, model, "
                        "  color, point_code, src_location_text, layer_code, "
                        "  thickness, logical_vehicle_id, load_id, source_sheet, "
                        "  source_row) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                        "        'Quick Summary', %s) RETURNING measurement_id",
                        (day, plant, model, colour, point_code, point_code, layer,
                         thickness, vehicle, load_id, source_row),
                    )
                    rows.append({
                        "measurement_id": cur.fetchone()[0],
                        "point_code": point_code, "layer_code": layer,
                        "thickness": thickness, "logical_vehicle_id": vehicle,
                    })
    return {
        "load_id": load_id, "plant": plant, "model": model, "colour": colour,
        "day": day, "month": day[:7], "vehicles": vehicles, "rows": rows,
    }


def forget_film_month(admin_conn, batch: dict) -> None:
    """Remove exactly the batch `film_month` made, facts first."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM filmthickness WHERE load_id = %s", (batch["load_id"],)
        )
        cur.execute("DELETE FROM load_batch WHERE load_id = %s", (batch["load_id"],))


__all__ = ["FilmPoint", "film_month", "forget_film_month", "gold_points"]
