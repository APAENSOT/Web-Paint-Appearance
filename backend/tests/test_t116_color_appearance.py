"""T116 -- colour appearance profiles for Model Studio (revision 0039).

Claims (task section 3), against the running application and the live
database:

1. ``color_appearance`` exists; ``app_rw`` holds INSERT + SELECT only.
2. A newly offered colour reads ``appearance: null``; nothing is generated.
3. Save then read back: normalised hex, shared by every model and month, and
   another plant still reads null. The audit row is written.
4. Refusals: bad hex 422, unknown 404, not offered 422, merged 422. Viewer 403.
5. Concurrency: two first saves on two connections -> one wins, one 409; a
   stale revision 409; a same-person same-hex retry 200 ``replayed``; a
   different hex (or person) on a taken revision 409.
6. Merge (D-116-2): the canonical colour reads a merged name's shade as
   ``inherited_from`` until its own save wins; the old row is untouched.
7. Atomicity: a failing audit insert leaves no appearance row.
8. Independence: facts, standards and the colour catalogue are unchanged.

**What this file writes.** Only marker colours (``T116 MARK ...``) in
``ref_color`` / ``ref_plant_color`` and their ``color_appearance`` rows, all
removed by name by the owner connection after each test. Their
``audit_event`` rows stay (append-only, like every other test's).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest
from sqlalchemy import create_engine

from app.services import color_appearance as service
from tests.test_t03_contract import (  # noqa: F401
    admin_client,
    client,
    engineer_client,
    make_client,
)

BACKEND = Path(__file__).resolve().parents[1]
PLANT, OTHER_PLANT = "FTM", "FVL"
#: The slash is on purpose: real canonical names hold one ("Absolute / Shadow Black").
MARK = "T116 MARK / A"
OLD = "T116 MARK OLD"
CANON = "T116 MARK CANON"
UNOFFERED = "T116 MARK UNOFFERED"
MARKS = (MARK, OLD, CANON, UNOFFERED)
BYPASS_NAME = "Development bypass"
BYPASS_OID = "00000000-0000-0000-0000-000000000000"


def get_url(plant: str = PLANT) -> str:
    return f"/api/v1/plants/{plant}/color-appearances"


def post_url(color: str, plant: str = PLANT) -> str:
    return f"{get_url(plant)}/{quote(color, safe='')}"


def _rows(admin_conn, color: str) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, revision, hex, created_by, created_at "
            "FROM color_appearance WHERE color_name = %s ORDER BY plant_code, revision",
            (color,),
        )
        return cur.fetchall()


def _item(payload: dict, color: str, key: str = "items") -> dict | None:
    return next((i for i in payload[key] if i["color_name"] == color), None)


@pytest.fixture()
def markers(admin_conn):
    def _purge() -> None:
        # Owner-only cleanup of this file's own marker rows (app_rw has no DELETE).
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM color_appearance WHERE color_name = ANY(%s)", (list(MARKS),))
            cur.execute("DELETE FROM ref_plant_color WHERE color_name = ANY(%s)", (list(MARKS),))
            cur.execute("UPDATE ref_color SET merged_into = NULL WHERE color_name = ANY(%s)", (list(MARKS),))
            cur.execute("DELETE FROM ref_color WHERE color_name = ANY(%s)", (list(MARKS),))

    _purge()
    with admin_conn.cursor() as cur:
        for name in MARKS:
            cur.execute("INSERT INTO ref_color (color_name) VALUES (%s)", (name,))
        for plant, name in ((PLANT, MARK), (OTHER_PLANT, MARK), (PLANT, OLD), (PLANT, CANON)):
            cur.execute(
                "INSERT INTO ref_plant_color (plant_code, color_name, is_offered) "
                "VALUES (%s, %s, true)",
                (plant, name),
            )
        cur.execute(
            "INSERT INTO ref_plant_color (plant_code, color_name, is_offered) "
            "VALUES (%s, %s, false)",
            (PLANT, UNOFFERED),
        )
    yield
    _purge()


@pytest.fixture()
def actor_id(engineer_client, admin_conn) -> str:
    assert engineer_client.get("/api/v1/auth/me").status_code == 200
    with admin_conn.cursor() as cur:
        cur.execute("SELECT id FROM app_user WHERE entra_oid = %s", (BYPASS_OID,))
        return str(cur.fetchone()[0])


# ---------------------------------------------------------------- 1
def test_table_is_append_only_for_the_app_role(admin_conn, app_role, app_dsn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] >= "0039"
        grants = {}
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            cur.execute(
                "SELECT has_table_privilege(%s, 'color_appearance', %s)", (app_role, privilege)
            )
            grants[privilege] = cur.fetchone()[0]
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'color_appearance'::regclass AND contype = 'u'"
        )
        uniques = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'color_appearance'"
        )
        columns = {r[0] for r in cur.fetchall()}
    assert grants == {"SELECT": True, "INSERT": True, "UPDATE": False,
                      "DELETE": False, "TRUNCATE": False}
    assert uniques == ["UNIQUE (plant_code, color_name, revision)"]
    # Shared across models and months: neither is part of the key.
    assert columns == {"appearance_id", "plant_code", "color_name", "revision",
                       "hex", "created_by", "created_at"}
    with psycopg.connect(app_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("UPDATE color_appearance SET hex = hex")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM color_appearance")


def test_code_has_no_update_or_delete():
    for part in ("repositories", "services"):
        source = (BACKEND / "app" / part / "color_appearance.py").read_text(encoding="utf-8")
        assert "UPDATE " not in source.upper() and "DELETE " not in source.upper()


# ---------------------------------------------------------------- 2, 3
def test_newly_offered_colour_is_unconfigured(client, admin_conn, markers):
    response = client.get(get_url())
    assert response.status_code == 200, response.text
    item = _item(response.json(), MARK)
    assert item == {"color_name": MARK, "family_name": None, "appearance": None}
    assert _item(response.json(), UNOFFERED) is None
    assert _rows(admin_conn, MARK) == []


def test_save_then_read_back(engineer_client, client, admin_conn, markers):
    response = engineer_client.post(post_url(MARK), json={"hex": "1a2b3c", "expected_revision": None})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert (saved["color_name"], saved["hex"], saved["revision"], saved["saved_by"],
            saved["replayed"]) == (MARK, "#1A2B3C", 1, BYPASS_NAME, False)

    appearance = _item(client.get(get_url()).json(), MARK)["appearance"]
    assert appearance == {"hex": "#1A2B3C", "revision": 1, "saved_at": saved["saved_at"],
                          "saved_by": BYPASS_NAME, "inherited_from": None}
    assert _item(client.get(get_url(OTHER_PLANT)).json(), MARK)["appearance"] is None
    # The plant code resolves through the same alias / case rules as History.
    assert _item(client.get(get_url("ftm")).json(), MARK)["appearance"]["hex"] == "#1A2B3C"

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT action, entity_type, before, after FROM audit_event "
            "WHERE entity_id = %s ORDER BY id DESC LIMIT 1",
            (f"{PLANT}:{MARK}",),
        )
        assert cur.fetchone() == ("appearance.color.save", "color_appearance", None,
                                  {"hex": "#1A2B3C", "revision": 1})


# ---------------------------------------------------------------- 4
@pytest.mark.parametrize("bad", ["#FFF", "FFF", "#11223344", "11223344", "#GGGGGG",
                                 "", "#", " #123456", "rgb(1,2,3)", 123456])
def test_bad_hex_is_refused(engineer_client, admin_conn, markers, bad):
    response = engineer_client.post(post_url(MARK), json={"hex": bad, "expected_revision": None})
    assert response.status_code == 422, response.text
    assert _rows(admin_conn, MARK) == []


def test_refusals_write_nothing(engineer_client, admin_conn, markers):
    unknown = engineer_client.post(post_url("T116 NO SUCH COLOUR"),
                                   json={"hex": "#000000", "expected_revision": None})
    assert unknown.status_code == 404, unknown.text

    unoffered = engineer_client.post(post_url(UNOFFERED), json={"hex": "#000000", "expected_revision": None})
    assert unoffered.status_code == 422, unoffered.text
    assert "not offered" in unoffered.json()["message"]
    elsewhere = engineer_client.post(post_url(OLD, "AAT"), json={"hex": "#000000", "expected_revision": None})
    assert elsewhere.status_code == 422, elsewhere.text

    with admin_conn.cursor() as cur:
        cur.execute("UPDATE ref_color SET merged_into = %s WHERE color_name = %s", (CANON, OLD))
    merged = engineer_client.post(post_url(OLD), json={"hex": "#000000", "expected_revision": None})
    assert merged.status_code == 422, merged.text
    assert merged.json()["message"] == f"{OLD} is merged into {CANON}; save {CANON}."

    no_plant = engineer_client.post(post_url(MARK, "NOPE"), json={"hex": "#000000", "expected_revision": None})
    assert no_plant.status_code == 404
    assert engineer_client.get(get_url("NOPE")).status_code == 404
    for name in MARKS:
        assert _rows(admin_conn, name) == []


def test_viewer_cannot_save(client, admin_conn, markers):
    response = client.post(post_url(MARK), json={"hex": "#123456", "expected_revision": None})
    assert response.status_code == 403, response.text
    assert _rows(admin_conn, MARK) == []
    assert client.get(get_url()).status_code == 200


# ---------------------------------------------------------------- 5
def test_two_first_saves_on_two_connections(app_dsn, admin_conn, actor_id, markers):
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(app_dsn))
    outcome: dict = {}

    def second() -> None:
        try:
            with engine.begin() as conn:
                outcome["ok"] = service.save(conn, PLANT, MARK, hex_value="#222222",
                                             expected_revision=None, actor=actor_id,
                                             correlation_id=None)
        except service.ColorAppearanceError as exc:
            outcome["error"] = exc

    try:
        with engine.begin() as first:
            won = service.save(first, PLANT, MARK, hex_value="#111111",
                               expected_revision=None, actor=actor_id, correlation_id=None)
            racer = threading.Thread(target=second)
            racer.start()
            # The second INSERT must be waiting on the first's uncommitted key.
            deadline = time.monotonic() + 10
            with admin_conn.cursor() as cur:
                while time.monotonic() < deadline:
                    cur.execute("SELECT count(*) FROM pg_locks WHERE NOT granted")
                    if cur.fetchone()[0]:
                        break
                    time.sleep(0.05)
                else:
                    pytest.fail("the second save never waited on the first")
        racer.join(10)
    finally:
        engine.dispose()

    assert won["revision"] == 1 and won["replayed"] is False
    assert "ok" not in outcome
    assert outcome["error"].status_code == 409
    assert "revision 1 (#111111)" in outcome["error"].detail
    assert [(r[1], r[2]) for r in _rows(admin_conn, MARK)] == [(1, "#111111")]


def test_revision_conflicts_and_safe_retry(engineer_client, admin_conn, markers):
    def save(hex_value, expected):
        return engineer_client.post(post_url(MARK), json={"hex": hex_value, "expected_revision": expected})

    assert save("#111111", None).status_code == 200
    second_first = save("#999999", None)
    assert second_first.status_code == 409
    assert "revision 1 (#111111)" in second_first.json()["message"]

    assert save("#222222", 1).json()["revision"] == 2
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_event WHERE entity_id = %s", (f"{PLANT}:{MARK}",))
        audits = cur.fetchone()[0]

    stale = save("#333333", 1)
    assert stale.status_code == 409
    assert "revision 2 (#222222)" in stale.json()["message"]
    assert save("#333333", 7).status_code == 409  # a revision that was never saved

    retry = save("222222", 1)  # same person, same hex (any spelling), same precondition
    assert retry.status_code == 200, retry.text
    assert (retry.json()["revision"], retry.json()["hex"], retry.json()["replayed"]) == (2, "#222222", True)

    # The same hex saved by somebody else is not this caller's retry.
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO color_appearance (plant_code, color_name, revision, hex, created_by) "
            "VALUES (%s, %s, 3, '#444444', NULL)",
            (PLANT, MARK),
        )
        cur.execute("SELECT count(*) FROM audit_event WHERE entity_id = %s", (f"{PLANT}:{MARK}",))
        assert cur.fetchone()[0] == audits  # neither 409 nor the replay wrote an audit row
    assert save("#444444", 2).status_code == 409
    assert [(r[1], r[2]) for r in _rows(admin_conn, MARK)] == [
        (1, "#111111"), (2, "#222222"), (3, "#444444")]


# ---------------------------------------------------------------- 6
def test_merged_name_passes_its_shade_on(engineer_client, client, admin_conn, markers):
    assert engineer_client.post(post_url(OLD), json={"hex": "#ABCDEF", "expected_revision": None}).status_code == 200
    old_row = _rows(admin_conn, OLD)
    with admin_conn.cursor() as cur:
        cur.execute("UPDATE ref_color SET merged_into = %s WHERE color_name = %s", (CANON, OLD))

    read = client.get(get_url()).json()
    assert _item(read, OLD) is None and _item(read, OLD, "unavailable") is None
    inherited = _item(read, CANON)["appearance"]
    assert (inherited["hex"], inherited["revision"], inherited["inherited_from"]) == ("#ABCDEF", 1, OLD)
    assert _rows(admin_conn, CANON) == []  # nothing copied

    own = engineer_client.post(post_url(CANON), json={"hex": "#010203", "expected_revision": None})
    assert own.status_code == 200, own.text
    assert own.json()["revision"] == 1
    read = client.get(get_url()).json()
    assert _item(read, CANON)["appearance"]["hex"] == "#010203"
    assert _item(read, CANON)["appearance"]["inherited_from"] is None
    kept = _item(read, OLD, "unavailable")
    assert kept["appearance"]["hex"] == "#ABCDEF"
    assert _rows(admin_conn, OLD) == old_row  # the old row is untouched


def test_a_colour_no_longer_offered_is_kept_as_unavailable(engineer_client, client, admin_conn, markers):
    assert engineer_client.post(post_url(MARK), json={"hex": "#0F0F0F", "expected_revision": None}).status_code == 200
    with admin_conn.cursor() as cur:
        cur.execute(
            "UPDATE ref_plant_color SET is_offered = false WHERE plant_code = %s AND color_name = %s",
            (PLANT, MARK),
        )
    read = client.get(get_url()).json()
    assert _item(read, MARK) is None
    assert _item(read, MARK, "unavailable")["appearance"]["hex"] == "#0F0F0F"


# ---------------------------------------------------------------- 7
def test_audit_failure_rolls_the_save_back(engineer_client, admin_conn, markers, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("T116 forced audit failure")

    monkeypatch.setattr(service.audit_repo, "record", boom)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        engineer_client.post(post_url(MARK), json={"hex": "#123456", "expected_revision": None})
    assert _rows(admin_conn, MARK) == []


# ---------------------------------------------------------------- 8
INDEPENDENT = ("wavescan", "filmthickness", "cf_standard", "film_standard",
               "ref_plant_color", "ref_color")


def _checksums(admin_conn) -> dict[str, tuple]:
    out = {}
    with admin_conn.cursor() as cur:
        for table in INDEPENDENT:
            cur.execute(
                f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) "
                f"FROM {table} t"
            )
            out[table] = cur.fetchone()
    return out


def test_a_save_touches_nothing_else(engineer_client, admin_conn, markers):
    before = _checksums(admin_conn)
    response = engineer_client.post(post_url(MARK), json={"hex": "#765432", "expected_revision": None})
    assert response.status_code == 200, response.text
    assert _checksums(admin_conn) == before
