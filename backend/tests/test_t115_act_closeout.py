"""T115 -- the act's close-out: names, true descriptions, Attach reloads.

Claims (task section 3):

1. **D-115-1.** Point Check's "Last change" is the person's
   `app_user.display_name`, in both sections, read through a join. A row
   nobody named stays null (Film: the seed word; Wave Scan: "-" on the page).
   `app_rw` can already read `app_user`.
2. **D-115-4.** A Wave Scan file and a Film file of a Removed plant x model
   are both held `MODEL_NOT_OFFERED` in `reject_log`; Attach (either path)
   reloads both through `IngestService.replay_batch`, says so in its response
   and on its own audit row, and the replayed sheets then load. A sheet also
   held for a second, still-removed model re-derives and stays held for it.
   Remove reloads nothing. A batch with facts is never replayed. A refused
   replay leaves the Attach standing and is named with its reason.
3. **D-115-5.** The model's held sentence is its own; the colour's is
   byte-for-byte what it was. The held list offers no control for a model
   hold (before and after T115).
4. **D-115-3.** The four `expected_point_count` descriptions say the live
   list, in both OpenAPI copies.

**What this file writes, and how.** Every write is inside one owner
transaction that is **always rolled back** (`tx`): the marker user, the
setting rows, the Remove and the Attach, the uploads, their batches, jobs,
staging and audit rows. Nothing commits, so nothing has to be deleted. The
plant x model is FVL x P703 DBL RANGER (and FVL x V363 as the second model):
never FTM's. The uploaded bytes are also kept in the raw store, as every
upload test's are; the store is content-addressed and holds no row.
"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.deps import get_ingest_service, get_write_connection
from app.domain.held_label_copy import MODEL_NOT_OFFERED_MESSAGE, operator_message_for
from app.repositories import batches as batch_repo
from app.repositories import filmthickness as film_repo
from app.repositories import standards as repo
from app.repositories import ws_points as ws_repo
from app.services import model_offer
from app.services.held_labels import held_label_items
from app.services.ingest import IngestError
from tests.test_t04_ingest import ingest_apps, make_workbook, unique_rows  # noqa: F401
from tests.test_t112fix_remove_both_domains import _service
from tests.test_t60_named_ingest_aliases import qs

pytestmark = pytest.mark.ingest

PLANT = "FVL"
MODEL = "P703 DBL RANGER"
SECOND = "V363"
MARKER_NAME = "T115 Marker Person"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def engine(admin_dsn):
    found = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn))
    yield found
    found.dispose()


@contextmanager
def tx(engine):
    """One owner transaction, always rolled back: nothing in it ever commits."""
    with engine.connect() as conn:
        outer = conn.begin()
        try:
            yield conn
        finally:
            outer.rollback()


@pytest.fixture(scope="module")
def service():
    return _service()


def marker_user(conn) -> str:
    return str(conn.execute(text(
        "INSERT INTO app_user (id, entra_oid, upn, display_name, last_seen_at) "
        "VALUES (gen_random_uuid(), :oid, 't115@localhost', :name, now()) RETURNING id"
    ), {"oid": f"t115-{uuid.uuid4().hex}", "name": MARKER_NAME}).scalar_one())


# =====================================================================
# 1. D-115-1: "Last change" names the person
# =====================================================================
def test_app_rw_can_already_read_app_user(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT has_table_privilege('app_rw', 'app_user', 'SELECT')")
        assert cur.fetchone()[0] is True


def test_film_last_change_is_the_display_name(engine):
    with tx(engine) as conn:
        model = conn.execute(text(
            "SELECT model_code FROM ref_plant_film_point WHERE plant_code = 'FTM' "
            "AND retired_at IS NULL ORDER BY model_code LIMIT 1"
        )).scalar_one()
        points = film_repo.point_setting(conn, "FTM", model)
        named, nobody = points[0]["point_code"], points[1]["point_code"]
        user = marker_user(conn)
        for code, by in ((named, user), (nobody, None)):
            conn.execute(text(
                "INSERT INTO film_point_setting (plant_code, model_code, point_code, "
                " counted, orientation, reason, created_by) "
                "VALUES ('FTM', :m, :p, true, 'H', 'T115 test, rolled back', :by)"
            ), {"m": model, "p": code, "by": by})
        by_code = {p["point_code"]: p for p in film_repo.point_setting(conn, "FTM", model)}
        assert by_code[named]["changed_by"] == MARKER_NAME
        assert by_code[nobody]["changed_by"] is None       # the page says "seed"
        assert user not in json.dumps([dict(p) for p in by_code.values()], default=str)


def test_wavescan_last_change_is_the_display_name(engine):
    with tx(engine) as conn:
        live = ws_repo.live_points(conn, PLANT, MODEL)
        named, nobody = live[0]["zone_code"], live[1]["zone_code"]
        user = marker_user(conn)
        for code, by in ((named, user), (nobody, None)):
            conn.execute(text(
                "INSERT INTO ws_point_setting (plant_code, model_code, zone_code, "
                " counted, reason, created_by) "
                "VALUES (:p, :m, :z, true, 'T115 test, rolled back', :by)"
            ), {"p": PLANT, "m": MODEL, "z": code, "by": by})
        by_code = {p["zone_code"]: p for p in ws_repo.live_points(conn, PLANT, MODEL)}
        assert by_code[named]["changed_by"] == MARKER_NAME
        assert by_code[nobody]["changed_by"] is None       # the page says "-"
        untouched = live[2]["zone_code"]
        assert by_code[untouched]["changed_by"] is None


# =====================================================================
# 2. D-115-4: Attach reloads the held sheets
# =====================================================================
def upload(conn, service, actor, name: str, data: bytes) -> list[int]:
    outcome = service.accept_upload(conn, [(name, data)], expected_plant=PLANT,
                                    actor_user_id=actor)
    load_ids = list(outcome.load_ids)
    for load_id in load_ids:
        service.process_batch(conn, load_id)
    return load_ids


def run_queued(conn, service, load_ids) -> None:
    """What the worker does after commit, done here inside the transaction."""
    for load_id in load_ids:
        assert batch_repo.get_batch(conn, load_id)["status"] == batch_repo.STATUS_RUNNING
        service.process_batch(conn, load_id)


def held(conn, load_id: int) -> dict[str, int]:
    rows = conn.execute(text(
        "SELECT reject_reason, count(*) FROM reject_log WHERE load_id = :l GROUP BY 1"
    ), {"l": load_id}).all()
    return {r[0]: int(r[1]) for r in rows}


def remove(conn, actor, model=MODEL):
    calls: list[list[str]] = []
    out = repo.set_plant_model_offered(
        conn, plant_code=PLANT, model_code=model, is_offered=False,
        actor_user_id=actor, correlation_id=None,
        reload=lambda plants: calls.append(plants) or {},
    )
    return out, calls


def two_files(conn, service, actor) -> tuple[int, int]:
    job = f"T115{uuid.uuid4().hex[:6].upper()}"
    ws = upload(conn, service, actor, f"t115-ws-{job}.xlsx",
                make_workbook(unique_rows(3, Plant=PLANT)))
    film = upload(conn, service, actor, f"P703-{job}-AB.xlsx",
                  qs(["Clearcoat", "Primer", "E-Coat"], ["001HOOD", "002HOOD"],
                     colour="Pace Red", job=job))
    assert len(ws) == 1 and len(film) == 1
    return ws[0], film[0]


def test_a_removed_model_holds_both_domains_and_attach_reloads_both(
    engine, service, actor_user_id
):
    with tx(engine) as conn:
        removed, calls = remove(conn, actor_user_id)
        assert removed["reloaded_load_ids"] == [] and calls == []   # Remove: nothing
        ws, film = two_files(conn, service, actor_user_id)
        for load_id in (ws, film):
            batch = batch_repo.get_batch(conn, load_id)
            assert batch["status"] in batch_repo.REPLAYABLE_STATUSES, batch.get("notes")
            # Film's hold lands in reject_log too (services/ingest.py insert_rejects).
            assert set(held(conn, load_id)) == {"MODEL_NOT_OFFERED"}, held(conn, load_id)
        assert batch_repo.get_batch(conn, film)["domain"] == "FILMTHICKNESS"
        assert {ws, film} <= set(batch_repo.held_for_model_offer(conn, PLANT))

        out = repo.attach_models(
            conn, model_code=MODEL, plants=[PLANT], actor_user_id=actor_user_id,
            correlation_id="t115-attach",
            reload=lambda plants: model_offer.reload_held(
                conn, service, plants=plants, model_code=MODEL,
                actor_user_id=actor_user_id, correlation_id="t115-attach"),
        )
        assert {ws, film} <= set(out["reloaded_load_ids"])
        assert out["reload_refused"] == []
        audit = conn.execute(text(
            "SELECT action, after FROM audit_event WHERE id = :i"), {"i": out["audit_id"]}
        ).one()
        assert audit[0] == "catalogue.plant_model.attach"
        assert audit[1]["reloaded_load_ids"] == out["reloaded_load_ids"]
        replays = conn.execute(text(
            "SELECT entity_id, after ->> 'reason' FROM audit_event "
            "WHERE action = 'batch.replay' AND correlation_id = 't115-attach'"
        )).all()
        assert {int(r[0]) for r in replays} == set(out["reloaded_load_ids"])
        assert {r[1] for r in replays} == {f"model {MODEL} attached at {PLANT}"}

        run_queued(conn, service, [ws, film])
        for load_id in (ws, film):
            batch = batch_repo.get_batch(conn, load_id)
            assert batch["status"] == batch_repo.STATUS_PENDING_REVIEW, batch.get("notes")
            assert "MODEL_NOT_OFFERED" not in held(conn, load_id)
            assert batch_repo.count_facts(conn, load_id) == 0     # never a commit
        assert batch_repo.get_batch(conn, ws)["rows_loaded"] == 3
        assert batch_repo.get_batch(conn, film)["rows_loaded"] > 0


def test_a_sheet_also_held_for_a_second_removed_model_stays_held_for_it(
    engine, service, actor_user_id
):
    with tx(engine) as conn:
        remove(conn, actor_user_id)
        remove(conn, actor_user_id, SECOND)
        rows = unique_rows(2, Plant=PLANT) + unique_rows(2, Plant=PLANT, Model=SECOND)
        [both] = upload(conn, service, actor_user_id,
                        f"t115-two-{uuid.uuid4().hex[:6]}.xlsx", make_workbook(rows))
        assert held(conn, both) == {"MODEL_NOT_OFFERED": 4}

        out = repo.set_plant_model_offered(
            conn, plant_code=PLANT, model_code=MODEL, is_offered=True,
            actor_user_id=actor_user_id, correlation_id=None,
            reload=lambda plants: model_offer.reload_held(
                conn, service, plants=plants, model_code=MODEL,
                actor_user_id=actor_user_id, correlation_id=None),
        )
        assert both in out["reloaded_load_ids"]
        run_queued(conn, service, [both])
        assert held(conn, both) == {"MODEL_NOT_OFFERED": 2}    # V363's rows
        assert batch_repo.get_batch(conn, both)["rows_loaded"] == 2


def test_attach_where_already_offered_and_remove_reload_nothing(engine, actor_user_id):
    calls: list[list[str]] = []

    def hook(plants):
        calls.append(plants)
        return {}

    with tx(engine) as conn:
        # Already offered: Set offered true again is not "false/absent -> true".
        out = repo.set_plant_model_offered(
            conn, plant_code=PLANT, model_code=MODEL, is_offered=True,
            actor_user_id=actor_user_id, correlation_id=None, reload=hook)
        assert out["reloaded_load_ids"] == [] and calls == []
        out = repo.set_plant_model_offered(
            conn, plant_code=PLANT, model_code=MODEL, is_offered=False,
            actor_user_id=actor_user_id, correlation_id=None, reload=hook)
        assert out["reloaded_load_ids"] == [] and calls == []
        # Attach at two plants, one of which still offers it: only FVL reloads.
        out = repo.attach_models(
            conn, model_code=MODEL, plants=[PLANT, "SAP"],
            actor_user_id=actor_user_id, correlation_id=None, reload=hook)
        assert calls == [[PLANT]]


def test_a_batch_with_facts_is_never_replayed(engine, service, actor_user_id):
    with tx(engine) as conn:
        load_id = conn.execute(text(
            "INSERT INTO load_batch (source_file, source_sheet, plant_code, file_hash, "
            " raw_store_key, status, domain) VALUES ('t115-facts.xlsx', 'S', :p, :h, "
            " 'unused', 'PENDING_REVIEW', 'WAVESCAN') RETURNING load_id"
        ), {"p": PLANT, "h": uuid.uuid4().hex * 2}).scalar_one()
        conn.execute(text(
            "INSERT INTO reject_log (load_id, source_file, source_sheet, source_row, "
            " reject_reason, reject_detail, offending_column, offending_value, raw_row) "
            "VALUES (:l, 't115-facts.xlsx', 'S', 2, 'MODEL_NOT_OFFERED', 'x', 'model', "
            " :m, '{}'::jsonb)"
        ), {"l": load_id, "m": MODEL})
        zone = ws_repo.live_points(conn, PLANT, MODEL)[0]["zone_code"]
        conn.execute(text(
            "INSERT INTO wavescan (measured_date, plant, model, color, serial_no, "
            " checkzone, tolerance_group, cf, load_id, source_sheet, source_row) "
            "VALUES ('2099-02-01', :p, :m, 'Ignite Orange', 'T115-FACT', :z, "
            " 'Horizontal', 60, :l, 'S', 3)"
        ), {"p": PLANT, "m": MODEL, "z": zone, "l": load_id})
        assert load_id not in batch_repo.held_for_model_offer(conn, PLANT)
        remove(conn, actor_user_id)
        out = repo.attach_models(
            conn, model_code=MODEL, plants=[PLANT], actor_user_id=actor_user_id,
            correlation_id=None,
            reload=lambda plants: model_offer.reload_held(
                conn, service, plants=plants, model_code=MODEL,
                actor_user_id=actor_user_id, correlation_id=None),
        )
        assert load_id not in out["reloaded_load_ids"]
        assert batch_repo.get_batch(conn, load_id)["status"] == "PENDING_REVIEW"


def test_a_refused_replay_is_named_and_the_attach_stands(engine, monkeypatch, actor_user_id):
    class Refusing:
        def replay_batch(self, conn, load_id, **_):
            raise IngestError(f"batch {load_id} refused by the T115 test")

    with tx(engine) as conn:
        remove(conn, actor_user_id)
        monkeypatch.setattr(batch_repo, "held_for_model_offer", lambda conn, plant: [987654321])
        out = repo.attach_models(
            conn, model_code=MODEL, plants=[PLANT], actor_user_id=actor_user_id,
            correlation_id=None,
            reload=lambda plants: model_offer.reload_held(
                conn, Refusing(), plants=plants, model_code=MODEL,
                actor_user_id=actor_user_id, correlation_id=None),
        )
        assert out["plants"] == [PLANT] and out["reloaded_load_ids"] == []
        assert out["reload_refused"] == [
            {"load_id": 987654321, "reason": "batch 987654321 refused by the T115 test"}
        ]
        assert conn.execute(text(
            "SELECT is_offered FROM ref_plant_model WHERE plant_code = :p AND model_code = :m"
        ), {"p": PLANT, "m": MODEL}).scalar_one() is True


def test_both_attach_routes_reload_and_answer_with_the_ids(
    engine, service, ingest_apps, actor_user_id  # noqa: F811
):
    """The two real routes, on the rolled-back transaction (no commit)."""
    client: TestClient = ingest_apps(auth_dev_bypass_roles_raw="admin",
                                     ingest_worker_enabled=False)
    with tx(engine) as conn:
        client.app.dependency_overrides[get_write_connection] = lambda: conn
        client.app.dependency_overrides[get_ingest_service] = lambda: service
        try:
            remove(conn, actor_user_id)
            ws, film = two_files(conn, service, actor_user_id)
            response = client.post("/api/v1/standards/plant-models/offered", json={
                "plant_code": PLANT, "model_code": MODEL, "is_offered": True})
            assert response.status_code == 200, response.text
            body = response.json()
            assert {ws, film} <= set(body["reloaded_load_ids"])
            assert body["reload_refused"] == []
            run_queued(conn, service, [ws, film])

            # Remove through the route: nothing reloads.
            response = client.post("/api/v1/standards/plant-models/offered", json={
                "plant_code": PLANT, "model_code": MODEL, "is_offered": False})
            assert response.json()["reloaded_load_ids"] == []

            # The other Attach path, after a second pair of held files.
            ws2, film2 = two_files(conn, service, actor_user_id)
            response = client.post("/api/v1/standards/plant-models", json={
                "model_code": MODEL, "plants": [PLANT]})
            assert response.status_code == 201, response.text
            assert {ws2, film2} <= set(response.json()["reloaded_load_ids"])
        finally:
            client.app.dependency_overrides.clear()


# =====================================================================
# 3. D-115-5: the held model sentence
# =====================================================================
COLOUR_SENTENCE = (
    '"Pace Red" is a real name but not on this plant\'s list, so these '
    "rows will not load yet. Pick the official name it is. If FTM "
    "does not list it yet, confirming adds it to the list."
)


def test_the_colour_sentence_is_byte_for_byte_unchanged():
    for reason in ("COLOR_NOT_OFFERED", None):
        assert operator_message_for(
            "plant_offer", "Pace Red", plant="FTM", reason=reason
        ) == COLOUR_SENTENCE


def test_the_model_sentence_says_attach_loads_it():
    assert operator_message_for(
        "plant_offer", "P703 SGL", plant="FTM", reason="MODEL_NOT_OFFERED"
    ) == (
        "P703 SGL is not on FTM's list (it was removed, or never attached), so "
        "these rows will not load. An Admin attaches it on Standard → Model; "
        "this file then loads by itself."
    )
    assert "confirming" not in MODEL_NOT_OFFERED_MESSAGE


def test_a_held_model_row_says_it_and_offers_no_control(engine, service, actor_user_id):
    from app.services.worksheet import held_row_message

    with tx(engine) as conn:
        remove(conn, actor_user_id)
        ws, film = two_files(conn, service, actor_user_id)
        expected = operator_message_for(
            "plant_offer", MODEL, plant=PLANT, reason="MODEL_NOT_OFFERED")
        for load_id in (ws, film):
            items = [i for i in held_label_items(conn, load_id, plant_code=PLANT)
                     if i["reason"] == "MODEL_NOT_OFFERED"]
            assert items, load_id
            for item in items:
                assert item["display_group"] == "plant_offer"
                assert item["teachable_kind"] is None and item["candidates"] == []
        film_item = next(i for i in held_label_items(conn, film, plant_code=PLANT)
                         if i["reason"] == "MODEL_NOT_OFFERED")
        assert film_item["operator_message"] == expected
        assert held_row_message("MODEL_NOT_OFFERED", "model", MODEL, plant=PLANT) == expected


# =====================================================================
# 4. D-115-3: the four descriptions
# =====================================================================
LIVE_LIST = "the live, non-extra points of this plant's wave scan list"


def flat(said: str) -> str:
    return re.sub(r"\s+", " ", said).lower()


@pytest.mark.parametrize("copy", ["backend/openapi.json", "docs/openapi.json"])
def test_the_four_descriptions_say_the_live_list(copy):
    spec = json.loads((REPO_ROOT / copy).read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    for name in ("HistoryVehicleSetOut", "VehicleSetOut", "ComparisonCandidate"):
        said = schemas[name]["properties"]["expected_point_count"]["description"]
        assert LIVE_LIST in flat(said), (name, said)
        assert "expected_zone_count when the plant has no list" in said, (name, said)
    route = spec["paths"]["/api/v1/plants/{plant_code}/workbooks/{file_hash}/vehicles"]["get"]
    assert LIVE_LIST in flat(route["description"])
    for name in ("WsPointItem", "FilmPointSettingItem"):
        assert "display_name" in schemas[name]["properties"]["changed_by"]["description"]
