"""All approved Studio body assets use independent durable point layouts."""
import hashlib
import math
from urllib.parse import quote

import pytest

from app.domain import model_assets
from tests.test_ms_point_profiles import (
    REPO, PLANT, RANGER, _glb, _accessor, plants,  # noqa: F401
    client, engineer_client, admin_client, make_client,  # noqa: F401
)

MODELS = {
    "P703 SGL": "ranger-sgl",
    "P703 RAPCAP": "ranger-rapcap",
    "P703 DBL RAPTOR": "ranger-raptor",
    "P703 DBL SUPER DUTY": "super-duty",
    "U704": "everest", "V363": "transit", "J73 DBL": "amarok", "CX743": "territory",
}


@pytest.mark.parametrize("model,body", MODELS.items())
def test_registered_asset_matches_export_and_has_its_own_version(model, body):
    asset = model_assets.supported_asset(model)
    assert asset is not None, f"No registered body for {model}"
    version = "20261014-cx743-reference-2" if model == "CX743" else "20261013-repair-3"
    assert asset.asset_version == f"{body}@{version}"
    data = (REPO / asset.asset_path).read_bytes()
    assert (hashlib.sha256(data).hexdigest(), len(data)) == (asset.sha256, asset.byte_size)
    gltf, binary = _glb(REPO / asset.asset_path)
    assert all(not {"matrix", "translation", "rotation", "scale", "children"}.intersection(n)
               for n in gltf["nodes"])
    assert {n["name"] for n in gltf["nodes"]} == {m.name for m in asset.meshes}
    for node in gltf["nodes"]:
        mesh = asset.mesh(node["name"])
        positions = [p for primitive in gltf["meshes"][node["mesh"]]["primitives"]
                     for p in _accessor(gltf, binary, primitive["attributes"]["POSITION"])]
        for axis in range(3):
            assert math.isclose(min(p[axis] for p in positions), mesh.bounds_min[axis], abs_tol=1e-7)
            assert math.isclose(max(p[axis] for p in positions), mesh.bounds_max[axis], abs_tol=1e-7)


@pytest.fixture()
def all_models(plants, admin_conn):
    # Only isolated MSPA marker lists are extended; real plant Standard stays intact.
    with admin_conn.cursor() as cur:
        for model in MODELS:
            cur.execute("SELECT 1 FROM ref_model WHERE model_code = %s", (model,))
            assert cur.fetchone(), f"Approved model {model} is absent from Standard"
            cur.execute("INSERT INTO ref_plant_ws_point "
                        "(plant_code, model_code, zone_code, point_no, tolerance_group, is_extra) "
                        "SELECT %s, %s, zone_code, point_no, tolerance_group, is_extra "
                        "FROM ref_plant_ws_point WHERE plant_code = %s AND model_code = %s "
                        "AND retired_at IS NULL ON CONFLICT DO NOTHING", (PLANT, model, PLANT, RANGER))
            cur.execute("INSERT INTO ref_plant_film_point "
                        "(plant_code, model_code, point_code, point_no, orientation, is_extra) "
                        "SELECT %s, %s, point_code, point_no, orientation, is_extra "
                        "FROM ref_plant_film_point WHERE plant_code = %s AND model_code = %s "
                        "AND retired_at IS NULL ON CONFLICT DO NOTHING", (PLANT, model, PLANT, RANGER))
    yield


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("domain", ["wavescan", "film"])
def test_each_model_can_save_reload_move_and_remove_without_losing_other_points(
    model, domain, all_models, engineer_client,
):
    url = f"/api/v1/plants/{PLANT}/point-profiles/{quote(model, safe='')}/{domain}"
    profile = engineer_client.get(url).json()
    assert profile["state"] == "unconfigured"
    asset = model_assets.supported_asset(model)
    gltf, binary = _glb(REPO / asset.asset_path)
    node = gltf["nodes"][0]
    primitive = gltf["meshes"][node["mesh"]]["primitives"][0]
    position = _accessor(gltf, binary, primitive["attributes"]["POSITION"])[0]
    anchor = {"asset_version": asset.asset_version, "mesh_name": node["name"],
              "position": position, "normal": [0, 1, 0], "body_zone": None}
    first, second = profile["points"][:2]
    def save(point, revision=None):
        return engineer_client.post(url + "/save", json={"point_key": point["point_key"],
                                    "expected_revision": revision, "anchor": anchor})
    assert save(first).status_code == 200
    assert save(second).status_code == 200
    assert save(first, 1).json()["revision"] == 2
    reloaded = engineer_client.get(url + "?month=2026-10&color=any").json()
    located = {p["point_key"]: p for p in reloaded["points"] if p["anchor"]}
    assert set(located) == {first["point_key"], second["point_key"]}
    assert located[first["point_key"]]["anchor"]["position"] == list(position)
    assert located[first["point_key"]]["anchor"]["asset_compatible"] is True
    # Other models/domains do not inherit these coordinates.
    other = engineer_client.get(url.rsplit("/", 1)[0] + ("/film" if domain == "wavescan" else "/wavescan")).json()
    assert other["state"] == "unconfigured"
    removed = engineer_client.post(url + "/remove", json={"point_key": first["point_key"],
                                                           "expected_revision": 2})
    assert removed.status_code == 200 and removed.json()["anchor"] is None
    last = engineer_client.get(url).json()
    assert len(last["points"]) == len(profile["points"])
    assert [p["point_key"] for p in last["points"] if p["anchor"]] == [second["point_key"]]


def test_other_model_and_stale_geometry_are_refused(all_models, engineer_client):
    asset = model_assets.RANGER
    url = f"/api/v1/plants/{PLANT}/point-profiles/P703%20SGL/wavescan"
    response = engineer_client.post(url + "/save", json={"point_key": "RRHOOD", "expected_revision": None,
        "anchor": {"asset_version": asset.asset_version, "mesh_name": asset.meshes[0].name,
                   "position": asset.meshes[0].bounds_min, "normal": [0, 1, 0]}})
    assert response.status_code == 422
    assert engineer_client.get(url).json()["state"] == "unconfigured"


def test_profile_uses_current_plant_label_without_changing_anchor_identity(plants, admin_conn, engineer_client):
    url = f"/api/v1/plants/{PLANT}/point-profiles/P703%20DBL%20RANGER/wavescan"
    try:
        with admin_conn.cursor() as cur:
            cur.execute("INSERT INTO ref_plant_ws_point_label "
                        "(plant_code, model_code, zone_code, label, label_norm, reason) "
                        "VALUES (%s, %s, 'RRHOOD', 'Studio hood test', 'studio hood test', 'isolated profile test')",
                        (PLANT, RANGER))
        p = next(p for p in engineer_client.get(url).json()["points"] if p["point_key"] == "RRHOOD")
        assert p["label"] == "Studio hood test"
        assert p["zone_code"] == "RRHOOD"
    finally:
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM ref_plant_ws_point_label WHERE plant_code = %s AND model_code = %s "
                        "AND reason = 'isolated profile test'", (PLANT, RANGER))


@pytest.mark.parametrize("value", [True, "1.4"])
def test_coordinates_are_numbers_not_coerced_values(value, plants, engineer_client):
    from tests.test_ms_point_profiles import HOOD
    url = f"/api/v1/plants/{PLANT}/point-profiles/P703%20DBL%20RANGER/wavescan/save"
    anchor = {**HOOD, **({"normal": [0, value, 0]} if isinstance(value, bool)
                        else {"position": [-1.7, value, .31]})}
    response = engineer_client.post(url, json={"point_key": "RRHOOD", "expected_revision": None,
                                               "anchor": anchor})
    assert response.status_code == 422
