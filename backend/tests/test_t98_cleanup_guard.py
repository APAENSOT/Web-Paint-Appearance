"""T98 D-98-2 -- the guard every reference cleanup now carries, exercised.

T95 scoped these deletes to plant and model. T97 proved a scope is not a
bound: the FTM fixtures write the owner's **own** spellings at the owner's
**own** plant and model, so a row the owner had taught minutes earlier
matched the delete and one `ref_plant_zone_map` row was lost.

The claim here is the exact shape of that loss: a cleanup leaves a row
created **before** the run and removes the one created during it, at the
same plant, model and spelling. Proved once per guarded helper, because
they are seven copies of one statement and the bound has to be in all of
them (`test_t95_scoped_test_cleanups` asserts that on the source).

Every row this module writes is its own marker spelling, and it is deleted
by `map_id` whatever the assertions do.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import SUITE_STARTED
from tests.test_t41_alias_checkzone import forget_map as t41_forget
from tests.test_t86_panel_match import forget_maps as t86_forget
from tests.test_t88_two_model_sheet import forget_maps as t88_forget
from tests.test_t89_one_picker import forget as t89_forget
from tests.test_t90_walk_memory import forget as t90_forget
from tests.test_t91_canonical_apply import _forget as t91_forget
from tests.test_t92_retire_and_apply import _forget as t92_forget

pytestmark = pytest.mark.ingest

PLANT = "FTM"
MODEL = "P703 DBL RAPTOR"

#: Each guarded cleanup, called the way its own module calls it.
CLEANUPS = {
    "t41": lambda conn, raw: t41_forget(conn, PLANT, MODEL, raw),
    "t86": lambda conn, raw: t86_forget(conn, PLANT, MODEL, [raw]),
    "t88": lambda conn, raw: t88_forget(conn, PLANT, [MODEL], [raw]),
    "t89": lambda conn, raw: t89_forget(conn, PLANT, MODEL, [raw]),
    "t90": lambda conn, raw: t90_forget(conn, PLANT, MODEL, [raw]),
    "t91": lambda conn, raw: t91_forget(conn, PLANT, MODEL, [raw]),
    "t92": lambda conn, raw: t92_forget(conn, PLANT, MODEL, [raw]),
}


def _a_zone(conn) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT zone_code FROM ref_plant_ws_point"
            " WHERE plant_code = %s AND model_code = %s AND retired_at IS NULL"
            " ORDER BY point_no LIMIT 1",
            (PLANT, MODEL),
        )
        found = cur.fetchone()
    assert found, f"no live panel at {PLANT} / {MODEL} to point a test map at"
    return found[0]


def _write(conn, raw: str, zone: str, created_at) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ref_plant_zone_map"
            "    (plant_code, model_code, raw_zone_text, zone_code,"
            "     confidence, note, created_at)"
            " VALUES (%s, %s, %s, %s, 'PROPOSED', 'T98 guard probe', %s)"
            " RETURNING map_id",
            (PLANT, MODEL, raw, zone, created_at),
        )
        return cur.fetchone()[0]


def _alive(conn, map_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ref_plant_zone_map WHERE map_id = %s", (map_id,)
        )
        return cur.fetchone() is not None


@pytest.mark.parametrize("name", sorted(CLEANUPS))
def test_the_cleanup_leaves_a_row_taught_before_the_run(name, admin_conn):
    raw = f"t98-guard-{uuid.uuid4().hex[:8]}"
    zone = _a_zone(admin_conn)
    taught_earlier = SUITE_STARTED - timedelta(days=1)
    owners = _write(admin_conn, raw, zone, taught_earlier)
    try:
        CLEANUPS[name](admin_conn, raw)
        assert _alive(admin_conn, owners), (
            f"{name}'s cleanup deleted a row taught before the run, at the "
            f"same plant, model and spelling -- the T97 loss (D-98-2)"
        )

        # The other half: the row this run wrote is still cleaned up.
        with admin_conn.cursor() as cur:
            cur.execute(
                "UPDATE ref_plant_zone_map SET created_at = %s WHERE map_id = %s",
                (datetime.now(timezone.utc), owners),
            )
        CLEANUPS[name](admin_conn, raw)
        assert not _alive(admin_conn, owners), (
            f"{name}'s cleanup no longer removes its own row"
        )
    finally:
        with admin_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ref_plant_zone_map WHERE map_id = %s", (owners,)
            )
