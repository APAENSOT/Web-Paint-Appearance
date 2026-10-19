"""T113 -- the retire script for FTM's duplicate Wave Scan block 33-64.

Claims:

* the script refuses, and writes nothing, unless the D-113-1 set is exactly
  32 qualifying points per model: a point with readings does not qualify, a
  block of 31 is refused;
* ``apply`` retires the whole set with the one D-113-3 reason and one
  ``audit_event`` per model; a second run retires 0 and keeps the first
  reason and time;
* after the real block is retired (inside a transaction that rolls back), a
  sheet writing FTM's real short names is still not stored onto them --
  held and asked in the row, exactly as today (the D-113-2 proof measured
  it on the three committed loads).

Marker rows only: a block parked on point numbers 233-264 under spare
``ref_checkzone`` codes and a note carrying this run's tag, deleted by that
note. The real FTM rows are only ever changed inside a rolled-back
transaction.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text

from scripts import t113_retire_ftm_duplicate_panels as t113
from tests.test_t39_uploader_worksheet import HEADERS, book

PLANT = t113.PLANT
MODELS = t113.MODELS


@pytest.fixture()
def engine(app_database_url):
    eng = create_engine(app_database_url)
    yield eng
    eng.dispose()


def _insert_block(admin_conn, note: str, sizes: dict[str, int]) -> None:
    with admin_conn.cursor() as cur:
        for model, size in sizes.items():
            cur.execute(
                """
                SELECT DISTINCT ON (c.zone_code) c.zone_code, c.tolerance_group
                  FROM ref_checkzone c
                 WHERE NOT EXISTS (
                       SELECT 1 FROM ref_plant_ws_point p
                        WHERE p.plant_code = %s AND p.model_code = %s
                          AND p.zone_code = c.zone_code)
                 ORDER BY c.zone_code
                 LIMIT %s
                """,
                (PLANT, model, size),
            )
            spare = cur.fetchall()
            assert len(spare) == size, "not enough spare ref_checkzone codes"
            for n, (zone, tolerance) in enumerate(spare):
                cur.execute(
                    "INSERT INTO ref_plant_ws_point (plant_code, model_code, "
                    " zone_code, point_no, tolerance_group, note) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (PLANT, model, zone, 233 + n, tolerance, note),
                )


@pytest.fixture()
def marker(admin_conn):
    """A note and reason of this test's own; its rows are deleted by note."""
    tag = uuid.uuid4().hex[:8]
    note = f"T113 test block {tag} -- delete me"
    block = t113.Block(
        note=note, first_point=233, last_point=264,
        reason=f"T113 test retire {tag}",
    )
    yield block
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM ref_plant_ws_point WHERE note = %s", (note,))


def _state(admin_conn, block) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code, zone_code, retired_at, retired_reason "
            "  FROM ref_plant_ws_point WHERE note = %s ORDER BY 1, 2",
            (block.note,),
        )
        return cur.fetchall()


def _audits(admin_conn, block) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT entity_id, actor_type, after FROM audit_event "
            " WHERE action = %s AND after->>'retired_reason' = %s ORDER BY id",
            (t113.AUDIT_ACTION, block.reason),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------
def test_a_point_with_readings_does_not_qualify():
    row = {"model_code": MODELS[0], "point_no": 33, "zone_code": "01HOOD",
           "note": t113.NOTE, "retired_at": None, "retired_reason": None,
           "readings": 0, "maps": 0}
    rows = [{**row, "point_no": 33 + n, "zone_code": f"Z{n}", "model_code": m}
            for m in MODELS for n in range(32)]
    assert len(t113.select_set(rows, t113.Block())[0]) == 64
    rows[5] = {**rows[5], "readings": 1}
    with pytest.raises(t113.Refused, match="31 qualifying"):
        t113.select_set(rows, t113.Block())
    rows[5] = {**rows[5], "readings": 0, "maps": 1}
    with pytest.raises(t113.Refused, match="31 qualifying"):
        t113.select_set(rows, t113.Block())


def test_the_real_reading_block_is_refused(engine):
    """Block 1-32 holds every FTM reading, so pointed at it the script refuses."""
    block = t113.Block(
        note="T58 copy of ref_model_zone (long-form catalogue)",
        first_point=1, last_point=32,
    )
    with engine.connect() as conn:
        with pytest.raises(t113.Refused, match="readings="):
            t113.run(conn, block=block, load_ids=(), apply=True)


def test_a_block_of_31_is_refused_and_nothing_is_written(engine, admin_conn, marker):
    _insert_block(admin_conn, marker.note, {MODELS[0]: 31, MODELS[1]: 32})
    with engine.connect() as conn:
        with pytest.raises(t113.Refused, match=f"{MODELS[0]}: 31 qualifying"):
            t113.run(conn, block=marker, load_ids=(), apply=True)
    assert all(r[2] is None and r[3] is None for r in _state(admin_conn, marker))
    assert _audits(admin_conn, marker) == []


# ---------------------------------------------------------------------
# apply, and the rerun
# ---------------------------------------------------------------------
def test_apply_retires_64_once_and_a_rerun_retires_nothing(engine, admin_conn, marker):
    _insert_block(admin_conn, marker.note, {m: 32 for m in MODELS})

    with engine.connect() as conn:
        dry = t113.run(conn, block=marker, load_ids=(), apply=False)
    assert len(dry.to_retire) == 64 and not dry.committed
    assert all(r[2] is None for r in _state(admin_conn, marker))

    with engine.connect() as conn:
        first = t113.run(conn, block=marker, load_ids=(), apply=True)
    assert first.committed
    assert {m: len(z) for m, z in first.retired.items()} == {m: 32 for m in MODELS}
    state = _state(admin_conn, marker)
    assert len(state) == 64
    assert all(r[2] is not None and r[3] == marker.reason for r in state)
    audits = _audits(admin_conn, marker)
    assert [a[0] for a in audits] == [f"{PLANT}:{m}" for m in MODELS]
    assert all(a[1] == "system" and len(a[2]["retired"]) == 32 for a in audits)

    with engine.connect() as conn:
        again = t113.run(conn, block=marker, load_ids=(), apply=True)
    assert len(again.to_retire) == 0 and len(again.already) == 64
    assert all(not z for z in again.retired.values())
    assert _state(admin_conn, marker) == state
    assert len(_audits(admin_conn, marker)) == 2


# ---------------------------------------------------------------------
# after the retire, a short name is still not stored onto its point
# ---------------------------------------------------------------------
def test_a_short_name_is_not_stored_onto_the_retired_point(engine):
    """The real block, retired inside a transaction that is rolled back.

    The sheet is planned in-process through the real ingest plan, so no
    batch, upload or fact is written. Today the short names are held and
    asked in the row (the D-113-2 proof found the same on all 2,494 committed
    rows with the in-row confirms set aside), and after the retire they
    still are: nothing lands on the retired block.
    """
    from app.repositories import reference as reference_repo
    from app.services.ingest import _projection

    service = t113._ingest_service()
    serial = f"T113-{uuid.uuid4().hex[:8]}"
    labels = ["01HOOD", "06LFFFEND", "16LFBOXS", "32RTFENDE"]
    rows = [
        {"Date": "2026-08-03", "Plant": PLANT, "Model": MODELS[0],
         "Color": "Ignite Orange", "Checkzone": label, "CF": 55.0 + n,
         "Serial No": serial}
        for n, label in enumerate(labels)
    ]
    data = book(HEADERS, rows)
    batch = {"load_id": -113, "plant_code": PLANT, "source_sheet": "PasteData",
             "source_file": "t113-short-names.xlsx"}

    def plan(conn):
        ref = reference_repo.load_reference_data(conn)
        p, raw, ctx = service._plan(conn, batch, data, ref)
        return [(e["disposition"], e["reason"], (e["canonical"] or {}).get("checkzone"))
                for e in _projection(p, raw, ctx)]

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            block = t113.block_rows(conn, t113.Block())
            short = {r["zone_code"] for r in block}
            live_before = sum(r["retired_at"] is None for r in block)
            assert set(labels) <= short
            before = plan(conn)
            # Whatever is still live; after the owner's --apply that is none.
            t113.retire(conn, t113.Block(), [r for r in block if r["retired_at"] is None])
            after = plan(conn)
        finally:
            trans.rollback()

    assert len(after) == len(labels)
    assert not any(zone in short for _, _, zone in before + after)
    assert all(d == "REJECT" and r == "UNKNOWN_CHECKZONE" for d, r, _ in after)
    assert after == before
    with engine.connect() as conn:
        live = conn.execute(text(
            "SELECT count(*) FROM ref_plant_ws_point WHERE plant_code = :p "
            "   AND model_code = ANY(:m) AND point_no BETWEEN 33 AND 64 "
            "   AND retired_at IS NULL"), {"p": PLANT, "m": list(MODELS)}).scalar()
    assert live == live_before, "the rollback must leave the real block as it was"
