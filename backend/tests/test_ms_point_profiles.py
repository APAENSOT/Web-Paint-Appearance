"""Model Studio point storage (revision 0044), against the running app and the
live database.

1. ``point_profile_anchor`` is append-only for ``app_rw``; no colour/month key.
2. The asset registry matches the GLB file itself (hash, transforms, meshes,
   bounds, side split) and ``body-zones.ts``.
3. Unconfigured read; save / reload round trip; partial layouts; a second
   point keeps the first; removal keeps the Standard point and other anchors.
4. Independence: plants, models and domains never share anchors; nothing in
   the read depends on colour or month.
5. Permissions, per-anchor conflicts (incl. two connections), safe retries.
6. Refusals: geometry, unsupported asset, retired / foreign / unknown points.
7. Saved anchors of a retired point are disclosed, not dropped.
8. Atomicity, and nothing else in the database changes.

**What this file writes.** Two marker plants (``MSPA``, ``MSPB``) holding
copies of FTM's Ranger / Raptor Point Check lists, and their
``point_profile_anchor`` rows -- all removed by the owner connection after each
test. Their ``audit_event`` rows stay (append-only, like every other test's).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import threading
import time
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest
from sqlalchemy import create_engine

from app.domain import model_assets
from app.services import point_profiles as service
from tests.test_t03_contract import (  # noqa: F401
    admin_client,
    client,
    engineer_client,
    make_client,
)

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
PLANT, OTHER_PLANT = "MSPA", "MSPB"
RANGER, RAPTOR = "P703 DBL RANGER", "P703 DBL RAPTOR"
ASSET = "20261012-b-pillars"
BYPASS_NAME = "Development bypass"
BYPASS_OID = "00000000-0000-0000-0000-000000000000"

HOOD = {"asset_version": ASSET, "mesh_name": "ranger-panel-5-Object006",
        "position": [-1.7000000476837158, 1.4012345678901234, 0.31234567890123],
        "normal": [0.6, 0.8, 0.0], "body_zone": "hood"}
FENDER = {"asset_version": ASSET, "mesh_name": "ranger-panel-6-Object008",
          "position": [-1.5, 1.0, 0.85], "normal": [0.0, 0.0, 1.0], "body_zone": "left-fender"}


def url(model: str = RANGER, domain: str = "wavescan", plant: str = PLANT, action: str = "") -> str:
    tail = f"/{action}" if action else ""
    return f"/api/v1/plants/{plant}/point-profiles/{quote(model, safe='')}/{domain}{tail}"


def save_body(key: str, anchor: dict, expected: int | None = None, **extra) -> dict:
    return {"point_key": key, "expected_revision": expected, "anchor": anchor, **extra}


def _rows(admin_conn, plant: str = PLANT) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code, domain, point_key, revision, action, mesh_name, "
            "pos_x, pos_y, pos_z FROM point_profile_anchor WHERE plant_code = %s "
            "ORDER BY model_code, domain, point_key, revision",
            (plant,),
        )
        return cur.fetchall()


def _point(payload: dict, key: str, field: str = "points") -> dict | None:
    return next((p for p in payload[field] if p["point_key"] == key), None)


def _audits(admin_conn, entity_id: str) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_event WHERE entity_id = %s", (entity_id,))
        return cur.fetchone()[0]


@pytest.fixture()
def plants(admin_conn):
    def _purge() -> None:
        # Owner-only cleanup of this file's marker rows (app_rw has no DELETE).
        with admin_conn.cursor() as cur:
            for table in ("point_profile_anchor", "ref_plant_ws_point", "ref_plant_film_point"):
                cur.execute(f"DELETE FROM {table} WHERE plant_code IN (%s, %s)", (PLANT, OTHER_PLANT))
            cur.execute("DELETE FROM ref_plant WHERE plant_code IN (%s, %s)", (PLANT, OTHER_PLANT))

    _purge()
    with admin_conn.cursor() as cur:
        for plant in (PLANT, OTHER_PLANT):
            cur.execute("INSERT INTO ref_plant (plant_code, plant_name, is_active) "
                        "VALUES (%s, 'Model Studio point storage test', true)", (plant,))
            # FTM's lists as they stand, live and retired (Ranger has 32 retired WS rows).
            cur.execute(
                "INSERT INTO ref_plant_ws_point (plant_code, model_code, zone_code, point_no, "
                "tolerance_group, retired_at, retired_reason, is_extra) "
                "SELECT %s, model_code, zone_code, point_no, tolerance_group, retired_at, "
                "retired_reason, is_extra FROM ref_plant_ws_point "
                "WHERE plant_code = 'FTM' AND model_code IN (%s, %s)",
                (plant, RANGER, RAPTOR),
            )
            cur.execute(
                "INSERT INTO ref_plant_film_point (plant_code, model_code, point_code, point_no, "
                "orientation, is_extra) SELECT %s, model_code, point_code, point_no, orientation, "
                "is_extra FROM ref_plant_film_point "
                "WHERE plant_code = 'FTM' AND model_code = %s AND retired_at IS NULL",
                (plant, RANGER),
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
def test_table_is_append_only_and_has_no_colour_or_month(admin_conn, app_role, app_dsn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] >= "0044"
        grants = {}
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            cur.execute("SELECT has_table_privilege(%s, 'point_profile_anchor', %s)",
                        (app_role, privilege))
            grants[privilege] = cur.fetchone()[0]
        cur.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'point_profile_anchor'::regclass AND contype = 'u'")
        uniques = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'point_profile_anchor'")
        columns = {r[0] for r in cur.fetchall()}
    assert grants == {"SELECT": True, "INSERT": True, "UPDATE": False,
                      "DELETE": False, "TRUNCATE": False}
    assert uniques == ["UNIQUE (plant_code, model_code, domain, point_key, revision)"]
    # One default per plant x model x domain: colour and month are not part of it.
    assert not {c for c in columns if "color" in c or "colour" in c or "month" in c}
    with psycopg.connect(app_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("UPDATE point_profile_anchor SET revision = revision")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM point_profile_anchor")


def test_code_has_no_update_or_delete():
    for part in ("repositories", "services"):
        source = (BACKEND / "app" / part / "point_profiles.py").read_text(encoding="utf-8")
        assert "UPDATE " not in source.upper() and "DELETE " not in source.upper()


def test_database_refuses_a_half_or_non_finite_row(admin_conn, plants):
    base = ("INSERT INTO point_profile_anchor (plant_code, model_code, domain, point_key, "
            "revision, action, asset_version, mesh_name, pos_x, pos_y, pos_z, nrm_x, nrm_y, nrm_z) "
            "VALUES (%s, %s, 'wavescan', 'RRHOOD', 1, %s, %s, 'm', %s, 0, 0, 0, 1, 0)")
    for action, asset, x in (("place", ASSET, float("nan")), ("place", ASSET, float("inf")),
                             ("place", None, 0.0), ("remove", ASSET, 0.0)):
        with pytest.raises(psycopg.errors.CheckViolation):
            with admin_conn.transaction(), admin_conn.cursor() as cur:
                cur.execute(base, (PLANT, RANGER, action, asset, x))


# ---------------------------------------------------------------- 2
def _glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    _, _, length = struct.unpack_from("<III", data, 0)
    offset, chunks = 12, []
    while offset < length:
        size, _ = struct.unpack_from("<II", data, offset)
        chunks.append(data[offset + 8: offset + 8 + size])
        offset += 8 + size
    return json.loads(chunks[0]), chunks[1]


def _accessor(gltf: dict, binary: bytes, index: int) -> list[tuple]:
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    fmt = {5126: "f", 5125: "I", 5123: "H"}[acc["componentType"]]
    width = {"SCALAR": 1, "VEC3": 3}[acc["type"]]
    stride = view.get("byteStride", struct.calcsize("<" + fmt * width))
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return [struct.unpack_from("<" + fmt * width, binary, start + k * stride)
            for k in range(acc["count"])]


def test_registry_matches_the_glb_file():
    asset = model_assets.RANGER
    path = REPO / asset.asset_path
    data = path.read_bytes()
    assert (hashlib.sha256(data).hexdigest(), len(data)) == (asset.sha256, asset.byte_size)
    gltf, binary = _glb(path)
    nodes = gltf["nodes"]
    # Identity transforms: mesh-local coordinates are model coordinates.
    assert all(not ({"matrix", "translation", "rotation", "scale", "children"} & set(n))
               for n in nodes)
    assert [n["name"] for n in nodes] == [m.name for m in asset.meshes]
    for node in nodes:
        mesh = asset.mesh(node["name"])
        primitive = gltf["meshes"][node["mesh"]]["primitives"][0]
        positions = _accessor(gltf, binary, primitive["attributes"]["POSITION"])
        for axis in range(3):
            assert math.isclose(min(p[axis] for p in positions), mesh.bounds_min[axis], abs_tol=1e-6)
            assert math.isclose(max(p[axis] for p in positions), mesh.bounds_max[axis], abs_tol=1e-6)
        indices = [i[0] for i in _accessor(gltf, binary, primitive["indices"])]
        crossing = 0.0
        for t in range(0, len(indices), 3):
            face = [positions[i] for i in indices[t:t + 3]]
            centre = sum(v[2] for v in face) / 3
            crossing = max([crossing] + [abs(v[2]) for v in face if (v[2] >= 0) != (centre >= 0)])
        if len(mesh.zones) == 2:
            assert crossing <= mesh.side_tolerance_m <= crossing + 1.5e-4, mesh.name
    zones_ts = (REPO / "frontend/src/features/measurements/model-studio/body-zones.ts").read_text(
        encoding="utf-8")
    assert tuple(re.findall(r'\{ id: "([a-z-]+)"', zones_ts)) == model_assets.BODY_ZONES
    for mesh in asset.meshes:
        assert f'"{mesh.name}"' in zones_ts


# ---------------------------------------------------------------- 3
def test_unconfigured_before_the_first_save(client, admin_conn, plants):
    response = client.get(url())
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["state"], body["profile_revision"], body["last_saved_at"]) == ("unconfigured", 0, None)
    assert body["asset"]["asset_version"] == ASSET
    assert body["unavailable"] == []
    assert len(body["points"]) == 32  # FTM's live Ranger Wave Scan list, walk order
    assert [p["point_no"] for p in body["points"]] == list(range(1, 33))
    first = body["points"][0]
    assert first == {"point_key": "RRHOOD", "zone_code": "RRHOOD", "point_code": None,
                     "point_no": 1, "label": "RRHOOD", "counted": True, "is_extra": False,
                     "unavailable_reason": None, "retired_at": None, "revision": None,
                     "saved_at": None, "saved_by": None, "anchor": None}
    film = client.get(url(domain="film")).json()
    assert film["state"] == "unconfigured" and len(film["points"]) == 98
    assert film["points"][0]["point_code"] == "001HOOD" and film["points"][0]["zone_code"] is None
    # Raptor now has its own body; an empty layout still inherits no Ranger points.
    assert client.get(url(RAPTOR)).json()["asset"]["model_code"] == RAPTOR
    assert _rows(admin_conn) == []


def test_save_reload_second_point_and_remove(engineer_client, make_client, admin_conn, plants):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT max(id) FROM audit_event")
        audit_floor = cur.fetchone()[0]
    first = engineer_client.post(url(action="save"), json=save_body("RRHOOD", HOOD, point_no=1))
    assert first.status_code == 200, first.text
    saved = first.json()
    assert (saved["point_key"], saved["revision"], saved["saved_by"], saved["replayed"]) == (
        "RRHOOD", 1, BYPASS_NAME, False)
    assert saved["anchor"] == {**HOOD, "asset_compatible": True}

    # A fresh session reloads identical identity, coordinates and revision.
    reloaded = make_client().get(url()).json()
    hood = _point(reloaded, "RRHOOD")
    assert hood["anchor"] == {**HOOD, "asset_compatible": True}
    assert (hood["revision"], hood["saved_at"], hood["saved_by"]) == (1, saved["saved_at"], BYPASS_NAME)
    assert (reloaded["state"], reloaded["profile_revision"]) == ("configured", 1)
    # Partial: every other point is still unplaced.
    assert sum(p["anchor"] is not None for p in reloaded["points"]) == 1

    second = engineer_client.post(url(action="save"), json=save_body("LFFENDER", FENDER))
    assert second.status_code == 200, second.text
    both = engineer_client.get(url()).json()
    assert _point(both, "RRHOOD")["anchor"] == hood["anchor"]
    assert _point(both, "LFFENDER")["anchor"]["position"] == FENDER["position"]
    assert both["profile_revision"] == 2

    with admin_conn.cursor() as cur:
        cur.execute("SELECT zone_code, point_no, retired_at, tolerance_group FROM ref_plant_ws_point "
                    "WHERE plant_code = %s AND model_code = %s ORDER BY zone_code", (PLANT, RANGER))
        standard = cur.fetchall()
    removed = engineer_client.post(url(action="remove"),
                                   json={"point_key": "RRHOOD", "expected_revision": 1})
    assert removed.status_code == 200, removed.text
    assert (removed.json()["anchor"], removed.json()["revision"]) == (None, 2)
    after = engineer_client.get(url()).json()
    assert _point(after, "RRHOOD")["anchor"] is None  # still a live Standard point
    assert _point(after, "RRHOOD")["revision"] == 2
    assert _point(after, "LFFENDER")["anchor"]["position"] == FENDER["position"]
    with admin_conn.cursor() as cur:
        cur.execute("SELECT zone_code, point_no, retired_at, tolerance_group FROM ref_plant_ws_point "
                    "WHERE plant_code = %s AND model_code = %s ORDER BY zone_code", (PLANT, RANGER))
        assert cur.fetchall() == standard
    # Append-only: the placement row is still there under its tombstone.
    assert [(r[2], r[3], r[4]) for r in _rows(admin_conn)] == [
        ("LFFENDER", 1, "place"), ("RRHOOD", 1, "place"), ("RRHOOD", 2, "remove")]

    again = engineer_client.post(url(action="save"), json=save_body("RRHOOD", HOOD, 2))
    assert again.status_code == 200 and again.json()["revision"] == 3

    with admin_conn.cursor() as cur:
        cur.execute("SELECT action, before, after FROM audit_event "
                    "WHERE entity_id = %s AND id > %s ORDER BY id",
                    (f"{PLANT}:{RANGER}:wavescan:RRHOOD", audit_floor))
        audits = cur.fetchall()
    assert [a[0] for a in audits] == ["model_studio.point_anchor.place",
                                      "model_studio.point_anchor.remove",
                                      "model_studio.point_anchor.place"]
    assert audits[0][1] is None and audits[0][2]["position"] == HOOD["position"]
    assert audits[1][2]["action"] == "remove" and audits[1][1]["revision"] == 1


def test_film_points_by_point_code(engineer_client, plants):
    response = engineer_client.post(url(domain="film", action="save"),
                                    json=save_body("001HOOD", HOOD, point_no=1))
    assert response.status_code == 200, response.text
    assert (response.json()["point_code"], response.json()["zone_code"]) == ("001HOOD", None)
    read = engineer_client.get(url(domain="film")).json()
    assert _point(read, "001HOOD")["anchor"]["mesh_name"] == HOOD["mesh_name"]


# ---------------------------------------------------------------- 4
def test_plants_models_and_domains_are_independent(engineer_client, client, admin_conn, plants):
    assert engineer_client.post(url(action="save"), json=save_body("RRHOOD", HOOD)).status_code == 200
    assert client.get(url(domain="film")).json()["state"] == "unconfigured"
    assert client.get(url(plant=OTHER_PLANT)).json()["state"] == "unconfigured"
    assert client.get(url(RAPTOR)).json()["state"] == "unconfigured"
    # Film's own save does not touch Wave Scan's layout, and the reverse.
    assert engineer_client.post(url(domain="film", action="save"),
                                json=save_body("002HOOD", FENDER)).status_code == 200
    ws = client.get(url()).json()
    assert [p["point_key"] for p in ws["points"] if p["anchor"]] == ["RRHOOD"]
    assert ws["profile_revision"] == 1
    assert _rows(admin_conn, OTHER_PLANT) == []


def test_the_layout_does_not_depend_on_colour_or_month(client, engineer_client, app_dsn, plants):
    assert engineer_client.post(url(action="save"), json=save_body("RRHOOD", HOOD)).status_code == 200
    spec = client.app.openapi()
    params = spec["paths"]["/api/v1/plants/{plant_code}/point-profiles/{model_code}/{domain}"]["get"]["parameters"]
    assert {p["name"] for p in params} == {"plant_code", "model_code", "domain"}
    # Whatever colour or month a caller is looking at, it reads this one layout.
    plain = client.get(url()).json()
    for query in ("?color=Arctic%20White&month=2026-08", "?color=Absolute%20Black&month=2026-09"):
        assert client.get(url() + query).json() == plain


# ---------------------------------------------------------------- 5
def test_viewer_cannot_write_admin_can(client, admin_client, admin_conn, plants):
    assert client.post(url(action="save"), json=save_body("RRHOOD", HOOD)).status_code == 403
    assert client.post(url(action="remove"),
                       json={"point_key": "RRHOOD", "expected_revision": 1}).status_code == 403
    assert _rows(admin_conn) == []
    assert admin_client.post(url(action="save"), json=save_body("RRHOOD", HOOD)).status_code == 200


def test_conflicts_are_per_anchor(engineer_client, admin_conn, plants):
    def save(key, anchor, expected):
        return engineer_client.post(url(action="save"), json=save_body(key, anchor, expected))

    assert save("RRHOOD", HOOD, None).status_code == 200
    created_twice = save("RRHOOD", FENDER | {"mesh_name": HOOD["mesh_name"], "position": [-1.6, 1.3, 0.1],
                                              "body_zone": "hood"}, None)
    assert created_twice.status_code == 409
    assert "revision 1 (placed)" in created_twice.json()["message"]
    assert save("RRHOOD", HOOD | {"position": [-1.6, 1.3, 0.2]}, 1).json()["revision"] == 2
    stale = save("RRHOOD", HOOD | {"position": [-1.6, 1.3, 0.3]}, 1)
    assert stale.status_code == 409 and "revision 2" in stale.json()["message"]
    assert save("RRHOOD", HOOD, 9).status_code == 409  # never saved
    stale_remove = engineer_client.post(url(action="remove"),
                                        json={"point_key": "RRHOOD", "expected_revision": 1})
    assert stale_remove.status_code == 409
    # A change to another point is not a conflict: per-anchor tokens.
    assert save("LFFENDER", FENDER, None).status_code == 200
    assert save("RRHOOD", HOOD, 2).json()["revision"] == 3
    assert [(r[2], r[3]) for r in _rows(admin_conn)] == [
        ("LFFENDER", 1), ("RRHOOD", 1), ("RRHOOD", 2), ("RRHOOD", 3)]


def test_two_first_saves_on_two_connections(app_dsn, admin_conn, actor_id, plants):
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(app_dsn))
    outcome: dict = {}

    def write(conn, anchor):
        return service.save(conn, PLANT, RANGER, "wavescan", point_key="RRHOOD", point_no=None,
                            expected_revision=None, anchor=anchor, actor=actor_id,
                            correlation_id=None)

    def second() -> None:
        try:
            with engine.begin() as conn:
                outcome["ok"] = write(conn, HOOD | {"position": [-1.6, 1.3, 0.1]})
        except service.PointProfileError as exc:
            outcome["error"] = exc

    try:
        with engine.begin() as first:
            won = write(first, HOOD)
            racer = threading.Thread(target=second)
            racer.start()
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
    assert "ok" not in outcome and outcome["error"].status_code == 409
    assert [(r[2], r[3], r[6]) for r in _rows(admin_conn)] == [("RRHOOD", 1, HOOD["position"][0])]


def test_safe_retries_write_once(engineer_client, admin_conn, plants):
    entity = f"{PLANT}:{RANGER}:wavescan:RRHOOD"
    body = save_body("RRHOOD", HOOD)
    assert engineer_client.post(url(action="save"), json=body).json()["replayed"] is False
    audits = _audits(admin_conn, entity)
    retry = engineer_client.post(url(action="save"), json=body)
    assert retry.status_code == 200, retry.text
    assert (retry.json()["revision"], retry.json()["replayed"]) == (1, True)
    remove = {"point_key": "RRHOOD", "expected_revision": 1}
    assert engineer_client.post(url(action="remove"), json=remove).json()["replayed"] is False
    again = engineer_client.post(url(action="remove"), json=remove)
    assert (again.status_code, again.json()["replayed"], again.json()["revision"]) == (200, True, 2)
    assert _audits(admin_conn, entity) == audits + 1
    assert len(_rows(admin_conn)) == 2
    # Removing what is already removed is not a write.
    gone = engineer_client.post(url(action="remove"), json={"point_key": "RRHOOD", "expected_revision": 2})
    assert gone.status_code == 422 and "no saved location" in gone.json()["message"]


# ---------------------------------------------------------------- 6
BAD_ANCHORS = {
    "unknown asset": HOOD | {"asset_version": "20260101-old"},
    "unknown mesh": HOOD | {"mesh_name": "ranger-panel-9-nope"},
    "out of bounds": HOOD | {"position": [0.0, 1.4, 0.3]},
    "far below": HOOD | {"position": [-1.7, -50.0, 0.3]},
    "two numbers": HOOD | {"position": [-1.7, 1.4]},
    "four numbers": HOOD | {"normal": [0, 1, 0, 0]},
    "zero normal": HOOD | {"normal": [0, 0, 0]},
    "long normal": HOOD | {"normal": [0, 2, 0]},
    "zone of another mesh": HOOD | {"body_zone": "roof"},
    "wrong side": FENDER | {"body_zone": "right-fender"},
    "unknown zone": HOOD | {"body_zone": "bumper"},
    "pixel": HOOD | {"position": None},
    "extra field": HOOD | {"triangle": 1234},
}


@pytest.mark.parametrize("name", sorted(BAD_ANCHORS))
def test_bad_geometry_is_refused(engineer_client, admin_conn, plants, name):
    response = engineer_client.post(url(action="save"), json=save_body("RRHOOD", BAD_ANCHORS[name]))
    assert response.status_code == 422, (name, response.text)
    assert _rows(admin_conn) == []


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_refused(engineer_client, admin_conn, plants, token):
    raw = json.dumps(save_body("RRHOOD", HOOD | {"position": [-1.7, 1.2345, 0.3]})).replace("1.2345", token)
    assert token in raw
    response = engineer_client.post(url(action="save"), content=raw,
                                    headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert _rows(admin_conn) == []


def test_identity_refusals(engineer_client, admin_conn, plants):
    def save(key, model=RANGER, domain="wavescan", plant=PLANT, **extra):
        return engineer_client.post(url(model, domain, plant, "save"), json=save_body(key, HOOD, **extra))

    cases = {
        "unknown": save("NOTAPOINT"),
        "retired": save("01HOOD"),  # on FTM's list, retired by T114
        "film code in Wave Scan": save("001HOOD"),
        "Wave Scan code in Film": save("RRHOOD", domain="film"),
        "wrong walk number": save("RRHOOD", point_no=2),
        "Ranger body for Raptor": save("RRHOOD", model=RAPTOR),
        "case variant": save("rrhood"),
    }
    for name, response in cases.items():
        assert response.status_code == 422, (name, response.text)
    assert "retired" in cases["retired"].json()["message"]
    assert "P703 DBL RANGER body" in cases["Ranger body for Raptor"].json()["message"]
    assert save("RRHOOD", model="P703 DBL ranger").status_code == 404  # no guessed model names
    assert save("RRHOOD", model="NO SUCH MODEL").status_code == 404
    assert save("RRHOOD", plant="NOPE").status_code == 404
    assert engineer_client.get(url(domain="paint")).status_code == 422
    assert _rows(admin_conn) == []


# ---------------------------------------------------------------- 7
def test_retired_point_is_disclosed_not_dropped(engineer_client, client, admin_conn, plants):
    assert engineer_client.post(url(action="save"), json=save_body("LFFENDER", FENDER)).status_code == 200
    with admin_conn.cursor() as cur:
        cur.execute("UPDATE ref_plant_ws_point SET retired_at = now(), retired_reason = 'test' "
                    "WHERE plant_code = %s AND model_code = %s AND zone_code = 'LFFENDER'",
                    (PLANT, RANGER))
    read = client.get(url()).json()
    assert _point(read, "LFFENDER") is None
    kept = _point(read, "LFFENDER", "unavailable")
    assert (kept["unavailable_reason"], kept["point_no"], kept["revision"]) == ("retired", 6, 1)
    assert kept["retired_at"] is not None and kept["anchor"]["position"] == FENDER["position"]
    # It can no longer be placed, but its leftover location can be cleared.
    assert engineer_client.post(url(action="save"), json=save_body("LFFENDER", FENDER, 1)).status_code == 422
    cleared = engineer_client.post(url(action="remove"), json={"point_key": "LFFENDER", "expected_revision": 1})
    assert cleared.status_code == 200, cleared.text
    assert client.get(url()).json()["unavailable"] == []


# ---------------------------------------------------------------- 8
def test_audit_failure_rolls_the_save_back(engineer_client, admin_conn, plants, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(service.audit_repo, "record", boom)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        engineer_client.post(url(action="save"), json=save_body("RRHOOD", HOOD))
    assert _rows(admin_conn) == []


INDEPENDENT = ("wavescan", "filmthickness", "cf_standard", "film_standard", "color_appearance",
               "ws_point_setting", "film_point_setting", "ref_plant_ws_point", "ref_plant_film_point",
               "ref_model", "ref_plant_model", "load_batch")


def test_writes_touch_nothing_else(engineer_client, admin_conn, plants):
    def checksums() -> dict:
        out = {}
        with admin_conn.cursor() as cur:
            for table in INDEPENDENT:
                cur.execute(f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) "
                            f"FROM {table} t")
                out[table] = cur.fetchone()
        return out

    before = checksums()
    assert engineer_client.post(url(action="save"), json=save_body("RRHOOD", HOOD)).status_code == 200
    assert engineer_client.post(url(domain="film", action="save"),
                                json=save_body("001HOOD", HOOD)).status_code == 200
    assert engineer_client.post(url(action="remove"),
                                json={"point_key": "RRHOOD", "expected_revision": 1}).status_code == 200
    assert checksums() == before
