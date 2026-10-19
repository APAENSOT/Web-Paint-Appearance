"""RO19 measuring order, stable identities and append-only revisions.

Database fixtures exist only inside rolled-back synthetic transactions.
The lead owns test execution and the migration; this module never commits.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, text, event

from app.domain.film_walk import check_walk, check_walks
from app.repositories import filmthickness as film_repo
from app.repositories import reference as reference_repo
from app.services import worksheet
from app.services import point_walk
from app.services.workbooks import WorkbookError

PLANT = "ZRO19ORDER"
MODEL = "ZRO19 ORDER FILM"
WS_MODEL = "ZRO19 ORDER WS"
CODES = ("001ZHOOD", "002ZHOOD", "003ZDOOR")

_SPEC = importlib.util.spec_from_file_location(
    "migration_0049", Path(__file__).resolve().parents[1] / "migrations/versions/0049_ro19_walk_order.py"
)
m0049 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(m0049)


def test_numbered_rule_reads_duplicate_stable_numbers_without_collapsing_identity():
    """RO19 allows two live points on one number; rank keeps them apart.

    RO19 F5: keyed on `point_no` this collapsed the pair, and the second label
    then raised KeyError instead of pairing or refusing.
    """
    from app.domain.panel_walk import CanonicalPoint, WalkRow, read_walk, rule_walk_number

    labels = read_walk([WalkRow(1, "01HOOD"), WalkRow(2, "02HOOD"), WalkRow(3, "03DOOR")])
    points = [CanonicalPoint("ZLHOOD", 1, 1), CanonicalPoint("ZRHOOD", 1, 2), CanonicalPoint("ZDOOR", 3, 3)]
    outcome = rule_walk_number(labels, points)
    assert outcome.available is True, outcome.reason
    assert outcome.pairs == {"01HOOD": "ZLHOOD", "02HOOD": "ZRHOOD", "03DOOR": "ZDOOR"}
    assert len(set(outcome.pairs.values())) == 3, "both points numbered 1 stay distinct"


def test_canonical_walk_fingerprint_reads_rank_and_keeps_number_identity():
    from app.domain.panel_walk import CanonicalPoint, canonical_fingerprint

    points = [CanonicalPoint("ZHOOD", 1, 2), CanonicalPoint("ZDOOR", 2, 1)]
    assert canonical_fingerprint(points) == ("DOOR", "HOOD")
    assert [p.point_no for p in points] == [1, 2]


@pytest.fixture()
def order_conn(admin_dsn):
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn))
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                conn.execute(text("INSERT INTO ref_plant (plant_code, plant_name) VALUES (:p, 'RO19 rolled back')"), {"p": PLANT})
                conn.execute(text("INSERT INTO ref_plant_color (plant_code,color_name,is_offered) VALUES (:p,'Arctic White',true)"), {"p": PLANT})
                for model, ws in ((MODEL, False), (WS_MODEL, True)):
                    conn.execute(text("INSERT INTO ref_model (model_code, model_family, body_style, expected_zone_count, wavescan_ok) VALUES (:m, 'ZRO19', 'PICKUP', :expected, :ws)"), {"m": model, "ws": ws, "expected": 3 if ws else 0})
                    conn.execute(text("INSERT INTO ref_plant_model (plant_code, model_code, is_offered) VALUES (:p, :m, true)"), {"p": PLANT, "m": model})
                conn.execute(text("INSERT INTO ref_film_model_alias (plant_code, raw_token, model_code) VALUES (:p, 'ZRO19FILM', :m)"), {"p": PLANT, "m": MODEL})
                for number, code in enumerate(CODES, 1):
                    orientation = "V" if number == 3 else "H"
                    conn.execute(text("INSERT INTO ref_film_point (point_code) VALUES (:c) ON CONFLICT DO NOTHING"), {"c": code})
                    conn.execute(text("INSERT INTO ref_plant_film_point (plant_code, model_code, point_code, point_no, orientation, is_complete_stop) VALUES (:p, :m, :c, :n, :o, :stop)"), {"p": PLANT, "m": MODEL, "c": code, "n": number, "o": orientation, "stop": number == 1})
                    conn.execute(text("INSERT INTO ref_plant_film_point_label (plant_code, model_code, point_code, label, label_norm, reason) VALUES (:p, :m, :c, :c, :c, 'RO19 initial label')"), {"p": PLANT, "m": MODEL, "c": code})
                    conn.execute(text("INSERT INTO film_point_setting (plant_code, model_code, point_code, counted, orientation, reason) VALUES (:p, :m, :c, true, :o, 'RO19 initial rules')"), {"p": PLANT, "m": MODEL, "c": code, "o": orientation})
                for number, code in enumerate(("ZHOOD1", "ZHOOD2", "ZDOOR"), 1):
                    tolerance = "Vertical" if number == 3 else "Horizontal"
                    group = "DOOR" if number == 3 else "HOOD"
                    conn.execute(text("INSERT INTO ref_checkzone (zone_code, zone_name, panel_group, tolerance_group) VALUES (:c, :c, :g, :t)"), {"c": code, "g": group, "t": tolerance})
                    conn.execute(text("INSERT INTO ref_plant_ws_point (plant_code, model_code, zone_code, point_no, tolerance_group, note) VALUES (:p, :m, :c, :n, :t, 'RO19 rolled back')"), {"p": PLANT, "m": WS_MODEL, "c": code, "n": number, "t": tolerance})
                conn.execute(text("SET LOCAL ROLE app_rw"))
                yield conn
            finally:
                tx.rollback()
    finally:
        engine.dispose()


def _change(conn, codes, *, domain="FILMTHICKNESS", model=MODEL):
    current = point_walk.read(conn, PLANT, model, domain)
    actor = str(conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one())
    return point_walk.set_order(conn, PLANT, model, domain, point_codes=list(codes),
                                expected_version_id=current["version_id"], reason="RO19 test order",
                                actor=actor, correlation_id=None)


def test_new_measuring_order_changes_walk_without_changing_point_numbers(order_conn):
    conn = order_conn
    changed = (CODES[1], CODES[0], CODES[2])
    _change(conn, changed)
    film = film_repo.load_film_reference(conn)
    assert tuple(film.walk[(PLANT, MODEL)]) == changed
    assert not check_walk(changed, film.walk[(PLANT, MODEL)], plant=PLANT, model=MODEL).holds
    assert check_walk(CODES, film.walk[(PLANT, MODEL)], plant=PLANT, model=MODEL).holds
    assert conn.execute(text("SELECT point_code, point_no FROM ref_plant_film_point WHERE plant_code=:p AND model_code=:m ORDER BY point_no"), {"p": PLANT, "m": MODEL}).all() == list(zip(CODES, (1, 2, 3)))


def test_ro14_splits_at_first_measured_point_of_new_order(order_conn):
    changed = (CODES[1], CODES[0], CODES[2])
    _change(order_conn, changed)
    walk = film_repo.load_film_reference(order_conn).walk[(PLANT, MODEL)]
    assert not check_walks(changed * 2, walk, rows=list(range(1, 7)), plant=PLANT, model=MODEL).holds


def test_live_film_completeness_uses_measuring_ranks(order_conn):
    _change(order_conn, (CODES[1], CODES[0], CODES[2]))
    mapping, stops = film_repo.live_walks(order_conn, PLANT)[MODEL]
    assert mapping == {CODES[1]: 1, CODES[0]: 2, CODES[2]: 3}
    assert stops == [2]


def test_ro16_first_point_reads_wave_scan_measuring_order(order_conn):
    _change(order_conn, ("ZDOOR", "ZHOOD1", "ZHOOD2"), domain="WAVESCAN", model=WS_MODEL)
    assert reference_repo.load_reference_data(order_conn).ws_first_point[(PLANT, WS_MODEL)] == "ZDOOR"


def test_versions_are_append_only_and_each_change_is_audited(order_conn):
    first = _change(order_conn, (CODES[1], CODES[0], CODES[2]))
    old = order_conn.execute(text("SELECT point_code, walk_rank FROM point_walk_member WHERE version_id=:v ORDER BY walk_rank"), {"v": first["version_id"]}).all()
    second = _change(order_conn, CODES)
    assert second["version_id"] != first["version_id"]
    assert order_conn.execute(text("SELECT point_code, walk_rank FROM point_walk_member WHERE version_id=:v ORDER BY walk_rank"), {"v": first["version_id"]}).all() == old
    assert first["audit_id"] and second["audit_id"]


def test_film_add_taken_number_allocates_next_free_and_places_after(order_conn):
    actor = str(order_conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one())
    added = worksheet.add_film_point(order_conn, PLANT, MODEL, point_code="001ZNEW", counted=False,
                                    orientation="H", place_after=CODES[1], reason="RO19 inserted point",
                                    actor=actor, correlation_id=None)
    assert added["point_no"] == 4
    assert tuple(film_repo.load_film_reference(order_conn).walk[(PLANT, MODEL)]) == (CODES[0], CODES[1], "001ZNEW", CODES[2])
    assert not next(p for p in film_repo.point_setting(order_conn, PLANT, MODEL) if p["point_code"] == "001ZNEW")["counted"]


def test_film_restore_keeps_own_number_even_when_taken(order_conn):
    actor = str(order_conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one())
    worksheet.retire_film_point(order_conn, PLANT, MODEL, point_code=CODES[0], reason="RO19 retire test", actor=actor, correlation_id=None)
    worksheet.add_film_point(order_conn, PLANT, MODEL, point_code="001ZNEW", counted=True, orientation="H", reason="RO19 reuse number", actor=actor, correlation_id=None)
    restored = worksheet.restore_film_point(order_conn, PLANT, MODEL, point_code=CODES[0], reason="RO19 restore test", actor=actor, correlation_id=None)
    assert restored["point_no"] == 1
    assert len({p["point_code"] for p in film_repo.point_setting(order_conn, PLANT, MODEL)}) == 4


def test_order_refuses_missing_duplicate_and_stale_versions(order_conn):
    for codes in (CODES[:2], (CODES[0], CODES[0], CODES[2])):
        with pytest.raises(WorkbookError):
            _change(order_conn, codes)
    current = point_walk.read(order_conn, PLANT, MODEL, "FILMTHICKNESS")
    _change(order_conn, tuple(reversed(CODES)))
    with pytest.raises(WorkbookError) as caught:
        point_walk.set_order(order_conn, PLANT, MODEL, "FILMTHICKNESS", point_codes=list(CODES), expected_version_id=current["version_id"], reason="RO19 stale order", actor="", correlation_id=None)
    assert caught.value.status_code == 409


def test_film_add_after_a_retire_and_restore_still_allocates_and_places(order_conn):
    actor = str(order_conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one())
    worksheet.retire_film_point(order_conn, PLANT, MODEL, point_code=CODES[0], reason="RO19 retire test", actor=actor, correlation_id=None)
    worksheet.add_film_point(order_conn, PLANT, MODEL, point_code="001ZNEW", counted=True, orientation="H", reason="RO19 reuse number", actor=actor, correlation_id=None)
    worksheet.restore_film_point(order_conn, PLANT, MODEL, point_code=CODES[0], reason="RO19 restore test", actor=actor, correlation_id=None)
    added = worksheet.add_film_point(order_conn, PLANT, MODEL, point_code="001ZOTHER", counted=False,
                                    orientation="H", place_after=CODES[1], reason="RO19 slot insertion",
                                    actor=actor, correlation_id=None)
    # RO19 F6: 1 belongs to the restored point and 4 to 001ZNEW, so the next
    # free number is 5. The place the person asked for is still honoured.
    assert added["point_no"] == 5
    walk = film_repo.load_film_reference(order_conn).walk[(PLANT, MODEL)]
    assert walk[walk.index(CODES[1]) + 1] == "001ZOTHER"
    assert film_repo.live_point_at(order_conn, PLANT, MODEL, 1) == CODES[0]


def test_walk_number_rule_pairs_by_measuring_rank_not_point_number():
    """RO19 F5: after an order edit, file number k is the k-th point measured."""
    from app.domain.panel_walk import CanonicalPoint, WalkRow, read_walk, rule_walk_number

    # Numbers stay 1..3; the measuring order is DOOR first.
    points = [CanonicalPoint("ZLHOOD", 1, 2), CanonicalPoint("ZRHOOD", 2, 3), CanonicalPoint("ZDOOR", 3, 1)]
    labels = read_walk([WalkRow(1, "01DOOR"), WalkRow(2, "02HOOD"), WalkRow(3, "03HOOD")])
    outcome = rule_walk_number(labels, points)
    assert outcome.available is True, outcome.reason
    assert outcome.pairs == {"01DOOR": "ZDOOR", "02HOOD": "ZLHOOD", "03HOOD": "ZRHOOD"}


def test_a_member_naming_a_deleted_point_is_not_carried_forward(order_conn):
    """RO19 F4: `point_walk_member` has no FK, so a dead member must be dropped."""
    from app.repositories import point_walk as repo

    first = repo.append_version(order_conn, PLANT, MODEL, "FILMTHICKNESS", list(CODES),
                                actor=None, reason="RO19 F4 base order")
    order_conn.execute(text("INSERT INTO point_walk_member(version_id,point_code,walk_rank) VALUES(:v,'099ZGONE',4)"),
                       {"v": first})
    second = repo.append_version(order_conn, PLANT, MODEL, "FILMTHICKNESS", list(CODES),
                                 actor=None, reason="RO19 F4 next order")
    assert repo.members(order_conn, second) == list(CODES)
    assert "099ZGONE" in repo.members(order_conn, first), "history keeps what it recorded"


def test_a_retired_points_number_is_never_given_to_a_new_point(order_conn):
    """RO19 F6: else restoring it leaves two live points on one number."""
    actor = str(order_conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one())
    worksheet.retire_film_point(order_conn, PLANT, MODEL, point_code=CODES[0],
                                reason="RO19 F6 retire", actor=actor, correlation_id=None)
    added = worksheet.add_film_point(order_conn, PLANT, MODEL, point_code="001ZNEW", counted=True,
                                     orientation="H", reason="RO19 F6 reuse number",
                                     actor=actor, correlation_id=None)
    assert added["point_no"] == 4, "001 belongs to the retired point until it is restored"
    worksheet.restore_film_point(order_conn, PLANT, MODEL, point_code=CODES[0],
                                 reason="RO19 F6 restore", actor=actor, correlation_id=None)
    live = order_conn.execute(text("SELECT point_no FROM ref_plant_film_point WHERE plant_code=:p "
                                   "AND model_code=:m AND retired_at IS NULL"), {"p": PLANT, "m": MODEL}).scalars().all()
    assert len(live) == len(set(live)), f"two live points share a number: {sorted(live)}"


def test_the_downgrade_guard_counts_an_actorless_version_and_a_shared_number(order_conn):
    """RO19 F7: deltas, so the guard is proven without depending on live counts."""
    from app.repositories import point_walk as repo

    before = m0049.non_seed_versions(order_conn)
    repo.append_version(order_conn, PLANT, MODEL, "FILMTHICKNESS", list(CODES),
                        actor=None, reason="RO19 F7 actorless order")
    assert m0049.non_seed_versions(order_conn) == before + 1, "a NULL actor is not a seed version"
    with pytest.raises(RuntimeError, match="downgrade refused"):
        m0049.refuse_edited_order(order_conn)

    shared_before = m0049.shared_live_numbers(order_conn)
    order_conn.execute(text("INSERT INTO ref_film_point (point_code) VALUES ('001ZTWIN') ON CONFLICT DO NOTHING"))
    order_conn.execute(text("INSERT INTO ref_plant_film_point (plant_code,model_code,point_code,point_no,orientation) "
                            "VALUES (:p,:m,'001ZTWIN',1,'H')"), {"p": PLANT, "m": MODEL})
    assert m0049.shared_live_numbers(order_conn) == shared_before + 1, \
        "two live points on number 1 cannot be re-indexed by the downgrade"


def test_real_planner_dry_run_counts_stored_tab_holds_and_has_no_writes(order_conn):
    import hashlib
    import io
    from openpyxl import Workbook
    from app.core.config import Settings
    from app.repositories import batches
    from app.services.ingest import IngestService

    wb = Workbook()
    tab = wb.active
    tab.title = "ZRO19FILM"
    tab.append(["Checkzone", "Clearcoat", "Basecoat2", "Basecoat1", "E-coat", "Orientation", "Color", "Date"])
    for code in CODES:
        tab.append([code, 40, 10, 8, 20, "H", "Arctic White", "2001-01-01"])
    buffer = io.BytesIO()
    wb.save(buffer)
    data = buffer.getvalue()

    class MemoryStore:
        def get(self, key):
            assert key == "ro19-in-memory"
            return data

    ingest = IngestService(Settings(), MemoryStore())
    load_id = batches.create_batch(order_conn, source_file="ZRO19FILM.xlsx", source_sheet=tab.title,
                                    file_hash=hashlib.sha256(data).hexdigest(), raw_store_key="ro19-in-memory",
                                    plant_code=PLANT, loaded_by=None, template_fingerprint=None,
                                    raw_headers=None, domain="FILMTHICKNESS")
    batch = batches.get_batch(order_conn, load_id)
    plan, _, _ = ingest._plan(order_conn, batch, data, reference_repo.load_reference_data(order_conn))
    assert len(plan.clean) == 3, "synthetic sheet must start ready, with no unrelated hold"
    batches.set_batch_outcome(order_conn, load_id, status="PENDING_REVIEW", counts=plan.counts)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().upper())

    event.listen(order_conn, "before_cursor_execute", capture)
    try:
        same = point_walk.dry_run(order_conn, PLANT, MODEL, "FILMTHICKNESS", point_codes=list(CODES), ingest_service=ingest)
        # Keep the first point fixed so this specifically tests the order
        # hold rather than introducing a different RO14 car boundary.
        moved = point_walk.dry_run(order_conn, PLANT, MODEL, "FILMTHICKNESS", point_codes=[CODES[0], CODES[2], CODES[1]], ingest_service=ingest)
    finally:
        event.remove(order_conn, "before_cursor_execute", capture)
    assert (same["stored_sheets"], same["changed_dispositions"], same["changed_vehicle_ids"], same["held_sheets"]) == (1, 0, 0, [])
    assert (moved["stored_sheets"], moved["changed_sheets"], moved["changed_dispositions"]) == (1, 1, 3), moved
    assert [sheet["load_id"] for sheet in moved["held_sheets"]] == [load_id]
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE")) for sql in statements)


def test_order_api_roles_and_admin_dry_run_are_read_only(order_conn):
    from types import SimpleNamespace
    from urllib.parse import quote
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.deps import get_connection, get_write_connection
    from app.api.v1.point_walk import router
    from app.core.config import Settings
    from app.core.security import Principal, resolve_principal

    actor = str(order_conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one())
    principal = Principal(user_id=actor, upn="ro19-test@example.invalid", display_name="RO19 rolled back", roles=["viewer"], auth_source="dev-bypass")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.ingest_service = SimpleNamespace(settings=Settings(), store=None)
    app.dependency_overrides[get_connection] = lambda: order_conn
    app.dependency_overrides[get_write_connection] = lambda: order_conn
    app.dependency_overrides[resolve_principal] = lambda: principal
    url = f"/api/v1/plants/{PLANT}/point-walk/FILMTHICKNESS/{quote(MODEL, safe='')}"
    with TestClient(app) as client:
        for role in ("viewer", "engineer", "admin"):
            principal.roles = [role]
            read = client.get(url)
            assert read.status_code == 200, read.text
            write = client.put(url, json={"point_codes": list(CODES), "expected_version_id": read.json()["version_id"], "reason": "RO19 role test"})
            assert write.status_code == (403 if role == "viewer" else 200), write.text
            statements = []

            def capture(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement.lstrip().upper())

            event.listen(order_conn, "before_cursor_execute", capture)
            try:
                dry = client.post(url + "/dry-run", json={"point_codes": list(CODES)})
            finally:
                event.remove(order_conn, "before_cursor_execute", capture)
            assert dry.status_code == (200 if role == "admin" else 403), dry.text
            assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)


def test_dry_run_sql_error_in_one_sheet_does_not_hold_the_next(order_conn):
    import hashlib
    import io
    from openpyxl import Workbook
    from app.core.config import Settings
    from app.repositories import batches
    from app.services.ingest import IngestService

    wb = Workbook()
    tab = wb.active
    tab.title = "ZRO19FILM"
    tab.append(["Checkzone", "Clearcoat", "Basecoat2", "Basecoat1", "E-coat", "Orientation", "Color", "Date"])
    for code in CODES:
        tab.append([code, 40, 10, 8, 20, "H", "Arctic White", "2001-01-01"])
    buffer = io.BytesIO()
    wb.save(buffer)
    data = buffer.getvalue()

    class MemoryStore:
        def get(self, key):
            if key == "ro19-broken":
                # A SQL error mid-plan aborts the transaction unless it is contained.
                order_conn.execute(text("SELECT 1/0"))
            return data

    ingest = IngestService(Settings(), MemoryStore())
    ids = []
    for key in ("ro19-broken", "ro19-good"):
        load_id = batches.create_batch(order_conn, source_file=f"{key}.xlsx", source_sheet=tab.title,
                                        file_hash=hashlib.sha256(key.encode()).hexdigest(), raw_store_key=key,
                                        plant_code=PLANT, loaded_by=None, template_fingerprint=None,
                                        raw_headers=None, domain="FILMTHICKNESS")
        ids.append(load_id)
    plan, _, _ = ingest._plan(order_conn, batches.get_batch(order_conn, ids[1]), data,
                              reference_repo.load_reference_data(order_conn))
    for load_id in ids:
        batches.set_batch_outcome(order_conn, load_id, status="PENDING_REVIEW", counts=plan.counts)
    result = point_walk.dry_run(order_conn, PLANT, MODEL, "FILMTHICKNESS", point_codes=list(CODES), ingest_service=ingest)
    assert result["stored_sheets"] == 1, result
    assert [sheet["load_id"] for sheet in result["held_sheets"]] == [ids[0]], result
