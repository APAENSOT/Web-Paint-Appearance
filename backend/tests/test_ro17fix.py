"""RO17-FIX -- every new live point gets a label; a mapped spelling may label.

* D-RO17F-1: every app path that inserts or restores a live point writes its
  first label row in the same transaction -- Wave Scan Point Check add and
  restore, Film Point Check add and restore (the Film T99 walk confirm is
  asserted in `test_t99_film_point_lists`). After each, no live point is
  without a label. The standing database holds the invariant too (read only).
* D-RO17F-3: a label may equal another point's code only when that spelling
  already resolves here to the labelled point (a map answers before the
  code); refused once the map is retired; resolution unchanged.

**Zero residue.** Every DB test is one transaction, always rolled back, on
the synthetic plant ``ZRO17`` (Film) or FTM / Raptor (Wave Scan) as the
RO17 tests do. Nothing commits.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.repositories import ws_points as ws_repo
from app.services import point_labels as labels
from app.services import ws_points as ws
from tests.test_ro17_film_points import (  # noqa: F401  (fixtures)
    LISTED, PLANT, _add, _refused, _restore, _retire, actor, conn,
)
from tests.test_ro17_point_labels import MODEL as WS_MODEL
from tests.test_ro17_point_labels import PLANT as WS_PLANT
from tests.test_ro17_point_labels import REASON, engine, tx  # noqa: F401

#: live points, both domains, with no label row at all (D-RO17F-1).
UNLABELLED = """
SELECT (SELECT count(*) FROM ref_plant_ws_point p
         WHERE p.retired_at IS NULL AND NOT EXISTS (
               SELECT 1 FROM ref_plant_ws_point_label l
                WHERE (l.plant_code, l.model_code, l.zone_code)
                    = (p.plant_code, p.model_code, p.zone_code)))
     + (SELECT count(*) FROM ref_plant_film_point p
         WHERE p.retired_at IS NULL AND NOT EXISTS (
               SELECT 1 FROM ref_plant_film_point_label l
                WHERE (l.plant_code, l.model_code, l.point_code)
                    = (p.plant_code, p.model_code, p.point_code)))
"""


def unlabelled(c) -> int:
    return c.execute(text(UNLABELLED)).scalar_one()


# =====================================================================
# D-RO17F-1
# =====================================================================
def test_the_standing_database_has_no_live_point_without_a_label(engine):  # noqa: F811
    with tx(engine) as c:
        assert unlabelled(c) == 0


def test_film_add_and_restore_leave_no_point_without_a_label(conn, actor):  # noqa: F811
    _add(conn, actor, LISTED, "004ZBOX", orientation="V")
    assert unlabelled(conn) == 0
    _retire(conn, actor, LISTED, "004ZBOX")
    _restore(conn, actor, LISTED, "004ZBOX")
    assert unlabelled(conn) == 0


def test_ws_add_and_restore_write_the_first_label(engine):  # noqa: F811
    with tx(engine) as c:
        ws.add_ws_point(
            c, WS_PLANT, WS_MODEL, zone_code="RO17FIX DOOR", counted=True,
            reason=REASON, actor=None, actor_name="t", correlation_id=None,
        )
        assert unlabelled(c) == 0
        # A point an older code inserted with no label row, then retired.
        ws_repo.insert_checkzone(c, zone_code="RO17FIX OLD DOOR", panel_group="Door",
                                 tolerance_group="Vertical")
        ws_repo.insert_point(
            c, plant_code=WS_PLANT, model_code=WS_MODEL, zone_code="RO17FIX OLD DOOR",
            point_no=ws_repo.next_point_no(c, WS_PLANT, WS_MODEL),
            tolerance_group="Vertical", note=REASON,
        )
        assert unlabelled(c) == 1
        ws.retire_ws_point(c, WS_PLANT, WS_MODEL, zone_code="RO17FIX OLD DOOR",
                           reason=REASON, actor=None, correlation_id=None)
        ws.restore_ws_point(c, WS_PLANT, WS_MODEL, zone_code="RO17FIX OLD DOOR",
                            reason=REASON, actor=None, correlation_id=None)
        assert unlabelled(c) == 0
        assert labels.current_labels(c, "wavescan", WS_PLANT, WS_MODEL)["RO17FIX OLD DOOR"] == "RO17FIX OLD DOOR"


# =====================================================================
# D-RO17F-3
# =====================================================================
def _map(c, raw: str, point: str) -> None:
    """``raw`` -> ``point`` at ZRO17 / LISTED, as an owner-proved map row."""
    c.execute(text("RESET ROLE"))
    for no, code in enumerate(("001ZHOOD", "002ZROOF", "003ZDOOR"), start=1):
        c.execute(text(
            "INSERT INTO ref_model_film_point (model_code, point_code, point_no) "
            "VALUES (:m, :c, :n) ON CONFLICT DO NOTHING"), {"m": LISTED, "c": code, "n": no})
    c.execute(text(
        "INSERT INTO ref_film_location_map (plant_code, model_code, raw_location_norm, "
        "point_code, proof_hash, verified_by, note) VALUES (:p, :m, :r, :c, repeat('0', 64), "
        "'RO17-FIX test', 'RO17-FIX test, rolled back')"
    ), {"p": PLANT, "m": LISTED, "r": raw, "c": point})
    c.execute(text("SET LOCAL ROLE app_rw"))


def test_a_mapped_spelling_may_label_and_only_while_the_map_is_live(conn, actor):  # noqa: F811
    clash = lambda: labels.clash(  # noqa: E731
        conn, "film", PLANT, LISTED, "002ZROOF", for_code="003ZDOOR")
    assert "code of point 002ZROOF" in clash(), "no map: refused as in RO17"

    _map(conn, "002ZROOF", "003ZDOOR")
    resolve = labels.resolver(conn, "film", PLANT)
    before = {raw: resolve(LISTED, raw) for raw in ("001ZHOOD", "002ZROOF", "003ZDOOR")}
    assert before["002ZROOF"] == "003ZDOOR"
    assert clash() is None
    labels.rename(conn, "film", PLANT, LISTED, code="003ZDOOR", label="002ZROOF",
                  reason="RO17-FIX test", actor=actor, correlation_id=None)
    resolve = labels.resolver(conn, "film", PLANT)
    assert {raw: resolve(LISTED, raw) for raw in before} == before, "resolution unchanged"
    # Still refused: a third point may not take it (it does not resolve there).
    assert labels.clash(conn, "film", PLANT, LISTED, "002ZROOF", for_code="001ZHOOD")

    conn.execute(text(
        "UPDATE ref_film_location_map SET retired_at = now(), retired_reason = 'test' "
        "WHERE plant_code = :p AND model_code = :m AND raw_location_norm = '002ZROOF'"
    ), {"p": PLANT, "m": LISTED})
    assert "code of point 002ZROOF" in labels.clash(
        conn, "film", PLANT, LISTED, "002ZROOF", for_code="003ZDOOR"
    ), "map retired: refused again"


def test_wave_scan_code_of_another_point_stays_refused(engine):  # noqa: F811
    with tx(engine) as c:
        points = ws.ws_point_list(c, WS_PLANT, WS_MODEL)["items"]
        a, b = points[0]["zone_code"], points[1]["zone_code"]
        assert labels.clash(c, "wavescan", WS_PLANT, WS_MODEL, a, for_code=b)


# =====================================================================
# D-RO17F-2: the Film in-row question on a list without settings
# =====================================================================
def _held(reason: str, location: str, row: int = 2) -> dict:
    return {
        "source_row": row, "disposition": "REJECT", "reason": reason,
        "canonical": {"model": "ZRO17 FILM A"},
        "raw": {"values": {"location": location}},
    }


def test_an_unmapped_or_extra_row_is_asked_only_where_the_list_has_no_settings():
    from app.domain.film import REASON_EXTRA_POINT, REASON_UNMAPPED_POINT
    from app.services.worksheet import OUTCOME_NEEDS_CONFIRMATION, preview_rows

    rows = [_held(REASON_UNMAPPED_POINT, "Roof LH", 2),
            _held(REASON_EXTRA_POINT, "095LBOXSIDE", 3),
            _held("BAD_DATE", "001ZHOOD", 4)]
    asked = preview_rows("Sheet1", rows, set(), plant="ZRO17", film=True, ask_held=True)
    assert [r["outcome"] for r in asked] == [
        OUTCOME_NEEDS_CONFIRMATION, OUTCOME_NEEDS_CONFIRMATION, "held_out",
    ], "only the two point holds become questions"
    assert "Say which live point it is" in asked[0]["operator_message"]
    assert "Roof LH" in asked[0]["operator_message"]
    # Without the flag (settings exist, or no live list): today's hold.
    kept = preview_rows("Sheet1", rows, set(), plant="ZRO17", film=True)
    assert {r["outcome"] for r in kept} == {"held_out"}
