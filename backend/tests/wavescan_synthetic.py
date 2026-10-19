"""T85: build a WaveScan month out of nothing, for the read tests.

The WaveScan counterpart of `tests/film_synthetic.py`, and it exists for the
same reason. `test_t73_overview_prereqs` asserts that **every** plant's
monthly overview agrees with the facts behind it, and that some readings are
listed below Minimum. T85 cleared every upload by owner decision, and the
owner's trial has since re-uploaded FTM only -- so `ws_requests` found one
plant where it needs four, and "some readings are below Minimum" was being
asserted against no readings at all.

The claim is about the **read**: grain, statistics, status, and which
readings are below the Minimum. All of that is recreatable, so it is
recreated here rather than skipped.

Plant, model, checkzone and colour are read from the live catalogue instead
of typed, so the rows satisfy `fk_ws_plant_point` and `fk_ws_zone_tol` and
no test names a plant's panel itself (`AGENTS.md` rule 6). Pure fixture
data: every row carries the batch's own `load_id` and `forget_wavescan_month`
removes exactly that batch.
"""

from __future__ import annotations

import uuid


def plant_grain(admin_conn, plant: str) -> dict | None:
    """One live (model, checkzone, tolerance) per axis at this plant, and a colour.

    Returns None when the plant has no live panel list or no offered colour,
    which is a real state (a plant that was never onboarded) and the caller's
    to handle rather than this helper's to invent around.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.model_code, p.zone_code, p.tolerance_group
              FROM ref_plant_ws_point p
             WHERE p.plant_code = %s AND p.retired_at IS NULL
             ORDER BY p.model_code, p.tolerance_group, p.point_no
            """,
            (plant,),
        )
        points = cur.fetchall()
        if not points:
            return None
        # One panel per tolerance group, so the month has a Horizontal box
        # and a Vertical box and the grouping claim is not vacuous.
        by_axis: dict[str, tuple[str, str, str]] = {}
        model = points[0][0]
        for model_code, zone, tolerance in points:
            if model_code == model and tolerance not in by_axis:
                by_axis[tolerance] = (model_code, zone, tolerance)
        cur.execute(
            """
            SELECT c.color_name FROM ref_plant_color c
             JOIN ref_color r ON r.color_name = c.color_name
            WHERE c.plant_code = %s AND c.is_offered
              AND r.merged_into IS NULL AND c.family_name IS NOT NULL
            ORDER BY c.color_name LIMIT 1
            """,
            (plant,),
        )
        colour = cur.fetchone()
        if colour is None:
            return None
    return {"model": model, "colour": colour[0], "axes": list(by_axis.values())}


def wavescan_month(
    admin_conn,
    *,
    plant: str,
    day: str,
    readings: tuple[float, ...] = (62.0, 60.5, 58.0, 1.0),
) -> dict | None:
    """One committed WaveScan month at this plant, or None if it has no catalogue.

    The last value of `readings` is deliberately far below any published
    Minimum, so `below_minimum` has something true to list; the rest sit in
    a normal range. Each axis (Horizontal and Vertical) gets the whole set,
    so both boxes are populated.
    """
    grain = plant_grain(admin_conn, plant)
    if grain is None:
        return None
    rows: list[dict] = []
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO load_batch (source_file, source_sheet, file_hash, "
            "  raw_store_key, status, plant_code) "
            "VALUES (%s, 'S', %s, 'k', 'COMMITTED', %s) RETURNING load_id",
            (f"t85-ws-{uuid.uuid4().hex[:8]}.xlsx",
             uuid.uuid4().hex + uuid.uuid4().hex, plant),
        )
        load_id = cur.fetchone()[0]
        source_row = 0
        serial = f"T85-{load_id}"
        for model, zone, tolerance in grain["axes"]:
            for value in readings:
                source_row += 1
                cur.execute(
                    "INSERT INTO wavescan (measured_date, plant, model, checkzone, "
                    "  color, tolerance_group, paintline, serial_no, "
                    "  lw, sw, cf, load_id, source_sheet, source_row) "
                    "VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, 1.5, 2.5, %s, %s, "
                    "        'S', %s) RETURNING measurement_id",
                    (day, plant, model, zone, grain["colour"], tolerance,
                     f"{serial}-{source_row}", value, load_id, source_row),
                )
                rows.append({
                    "measurement_id": cur.fetchone()[0], "checkzone": zone,
                    "tolerance_group": tolerance, "cf": value,
                })
    return {
        "load_id": load_id, "plant": plant, "model": grain["model"],
        "colour": grain["colour"], "day": day, "month": day[:7], "rows": rows,
    }


def forget_wavescan_month(admin_conn, batch: dict | None) -> None:
    """Remove exactly the batch `wavescan_month` made, facts first."""
    if batch is None:
        return
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM wavescan WHERE load_id = %s", (batch["load_id"],))
        cur.execute("DELETE FROM load_batch WHERE load_id = %s", (batch["load_id"],))


__all__ = ["forget_wavescan_month", "plant_grain", "wavescan_month"]
