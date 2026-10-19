"""Registered Model Studio 3D assets and the anchor rules they imply.

An anchor is durable only against an immutable, versioned asset: the exact
source mesh name, a mesh-local XYZ position and a unit mesh-local normal. A
viewport pixel or an unversioned triangle index is never an anchor.

Every number below was read off the GLB itself (sha256, node transforms,
mesh names, POSITION extents) and ``tests/test_ms_point_profiles.py``
re-derives them from the file, so a changed asset fails the suite instead of
silently moving points. A new asset or body variant is a new entry with a
new ``asset_version``; anchors are never transferred between versions or
models.

Pure: no FastAPI, no database.
"""

from __future__ import annotations

import math
import json
from pathlib import Path
from dataclasses import dataclass

#: ``body-zones.ts`` ``BODY_ZONES`` ids: display regions, not Standard groups.
BODY_ZONES = (
    "hood", "roof", "left-fender", "right-fender", "left-cab", "right-cab",
    "left-b-pillar", "right-b-pillar", "left-box", "right-box", "bed", "tailgate",
)

#: Float32 vertices and raycast interpolation: 0.1 mm slack on mesh bounds.
BOUNDS_SLACK_M = 1e-4
#: |normal| must be 1 within this (the GLB's own normals are within 8e-5).
NORMAL_TOLERANCE = 1e-3


@dataclass(frozen=True)
class AssetMesh:
    name: str
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    #: One zone, or (left at +Z, right at -Z) for a two-sided source mesh.
    zones: tuple[str, ...]
    #: Two-sided meshes: the furthest any triangle reaches across Z=0 from
    #: the side its centroid is on (``body-zones.ts`` splits by centroid).
    #: Within it either side's zone is accepted. Rounded up to 0.1 mm (float32).
    side_tolerance_m: float = 0.0


@dataclass(frozen=True)
class ModelAsset:
    asset_version: str
    model_code: str
    asset_path: str
    sha256: str
    byte_size: int
    coordinate_system: str
    meshes: tuple[AssetMesh, ...]

    def mesh(self, name: str) -> AssetMesh | None:
        return next((m for m in self.meshes if m.name == name), None)


RANGER = ModelAsset(
    asset_version="20261012-b-pillars",
    model_code="P703 DBL RANGER",
    asset_path="frontend/public/models/ranger/ranger-body.glb",
    sha256="aea53e7aa94a3fc569379c3af7adc93b6faa587e0c72f01b7a476679501c3624",
    byte_size=1416240,
    coordinate_system=(
        "glTF 2.0, metres, Y up, vehicle nose toward -X, vehicle left at +Z. "
        "All 11 scene nodes carry identity transforms, so mesh-local "
        "coordinates equal model coordinates. Focused panel subsets keep the "
        "source mesh name and its local coordinates."
    ),
    meshes=(
        AssetMesh("ranger-panel-0-mesh_33", (1.1591, 0.8154, -0.8117), (2.7116, 1.4106, 0.8116), ("bed",)),
        AssetMesh("ranger-panel-1-Object002", (2.6873, 0.8582, -0.697), (2.7899, 1.4077, 0.6974), ("tailgate",)),
        AssetMesh("ranger-panel-2-Object005", (2.6676, 0.8683, -0.6948), (2.7095, 1.3886, 0.6952), ("tailgate",)),
        AssetMesh("ranger-panel-3-Object006", (-0.3663, 1.7886, -0.5657), (1.1349, 1.8993, 0.5661), ("roof",)),
        AssetMesh("ranger-panel-4-Object005", (-0.8479, 0.6323, -0.8978), (1.0646, 1.8301, 0.8982),
                  ("left-cab", "right-cab"), 0.0),
        AssetMesh("ranger-panel-5-Object006", (-2.3515, 1.2404, -0.7527), (-1.0815, 1.4553, 0.7532), ("hood",)),
        AssetMesh("ranger-panel-6-Object008", (-2.121, 0.5506, -0.9198), (-0.7094, 1.4744, 0.9202),
                  ("left-fender", "right-fender"), 0.0),
        AssetMesh("ranger-panel-7-Object009", (-0.9261, 0.5495, -0.898), (1.1719, 1.8693, 0.8984),
                  ("left-cab", "right-cab"), 0.1698),
        AssetMesh("ranger-panel-8-Object010", (1.0612, 0.5501, -0.9181), (2.722, 1.4085, 0.9185),
                  ("left-box", "right-box"), 0.0004),
        AssetMesh("ranger-b-pillar-positive-z", (0.0997, 1.3838, 0.6268), (0.3095, 1.7997, 0.8124),
                  ("left-b-pillar",)),
        AssetMesh("ranger-b-pillar-negative-z", (0.0997, 1.3838, -0.8113), (0.3095, 1.7997, -0.6256),
                  ("right-b-pillar",)),
    ),
)

ASSETS: dict[str, ModelAsset] = {RANGER.asset_version: RANGER}
for _entry in json.loads(Path(__file__).with_name("prepared_model_assets.json").read_text(encoding="utf-8")):
    _asset = ModelAsset(**{**_entry, "meshes": tuple(
        AssetMesh(**{**m, "bounds_min": tuple(m["bounds_min"]),
                     "bounds_max": tuple(m["bounds_max"]), "zones": tuple(m["zones"])})
        for m in _entry["meshes"]
    )})
    if _asset.asset_version in ASSETS or any(a.model_code == _asset.model_code for a in ASSETS.values()):
        raise ValueError("Duplicate current Studio asset version or model binding")
    ASSETS[_asset.asset_version] = _asset


def supported_asset(model_code: str) -> ModelAsset | None:
    """The asset a new anchor for this exact canonical model must use."""
    return next((a for a in ASSETS.values() if a.model_code == model_code), None)


class AnchorError(ValueError):
    """The anchor cannot be stored; the message says why."""


def _vector(name: str, value) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise AnchorError(f"{name} must be exactly three numbers [x, y, z].")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        raise AnchorError(f"{name} must be exactly three numbers [x, y, z].")
    if not all(math.isfinite(v) for v in value):
        raise AnchorError(f"{name} holds a non-finite number (NaN or Infinity).")
    return float(value[0]), float(value[1]), float(value[2])


def validate_anchor(
    *,
    model_code: str,
    asset_version: str,
    mesh_name: str,
    position,
    normal,
    body_zone: str | None,
) -> None:
    """Refuse anything that is not a location on this model's registered body."""
    asset = ASSETS.get(asset_version)
    if asset is None:
        raise AnchorError(
            f"Asset version {asset_version!r} is not a registered Model Studio "
            f"asset. Reload the studio; nothing was saved."
        )
    if asset.model_code != model_code:
        raise AnchorError(
            f"Asset {asset_version} is the {asset.model_code} body, not "
            f"{model_code}. Anchors are never shared between models."
        )
    if supported_asset(model_code) != asset:
        raise AnchorError("This geometry version is no longer current. Reload before placing points.")
    mesh = asset.mesh(mesh_name)
    if mesh is None:
        raise AnchorError(f"{mesh_name!r} is not a mesh of asset {asset_version}.")
    pos = _vector("position", position)
    nrm = _vector("normal", normal)
    for axis, value, low, high in zip("xyz", pos, mesh.bounds_min, mesh.bounds_max):
        if not low - BOUNDS_SLACK_M <= value <= high + BOUNDS_SLACK_M:
            raise AnchorError(
                f"position {axis}={value} is outside {mesh_name}'s bounds "
                f"[{low}, {high}] (mesh-local metres)."
            )
    if abs(math.sqrt(sum(v * v for v in nrm)) - 1) > NORMAL_TOLERANCE:
        raise AnchorError("normal must be a unit vector (mesh-local).")
    if body_zone is None:
        return
    if body_zone not in BODY_ZONES:
        raise AnchorError(f"{body_zone!r} is not a Model Studio body zone.")
    if body_zone not in mesh.zones:
        raise AnchorError(f"{mesh_name} is in {' / '.join(mesh.zones)}, not {body_zone}.")
    if len(mesh.zones) == 2 and abs(pos[2]) > mesh.side_tolerance_m:
        side = mesh.zones[0] if pos[2] >= 0 else mesh.zones[1]
        if body_zone != side:
            raise AnchorError(f"z={pos[2]} on {mesh_name} is {side}, not {body_zone}.")
