"""Model Studio point profile DTOs: the default 3D layout of one plant x
canonical model x measurement domain, shared by every colour and month."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import StrictModel

Domain = Literal["wavescan", "film"]
BodyZone = Literal[
    "hood", "roof", "left-fender", "right-fender", "left-cab", "right-cab",
    "left-b-pillar", "right-b-pillar", "left-box", "right-box", "bed", "tailgate",
]
Vector3 = list[Annotated[float, Field(strict=True, allow_inf_nan=False)]]
_VECTOR = {"min_length": 3, "max_length": 3}


class AnchorIn(StrictModel):
    asset_version: str = Field(min_length=1, max_length=64, examples=["20261012-b-pillars"],
                               description="Exact model-specific registered version from GET asset. "
                                           "Prepared bodies use <body-id>@<release>; never use a shared release alone.")
    mesh_name: str = Field(min_length=1, max_length=128, examples=["ranger-panel-5-Object006"],
                           description="Exact source mesh name. Focused panel subsets keep it.")
    position: Vector3 = Field(**_VECTOR, examples=[[-1.7, 1.42, 0.31]],
                              description="Mesh-local XYZ, metres. Finite, inside the mesh's bounds.")
    normal: Vector3 = Field(**_VECTOR, examples=[[0.05, 0.99, 0.02]],
                            description="Mesh-local unit normal (|n| = 1 within 0.001).")
    body_zone: BodyZone | None = Field(
        default=None,
        description="Optional display region (body-zones.ts). Must agree with the mesh and side. "
                    "Metadata only: never a substitute for the Point Check identity. "
                    "Use null for a registered mesh whose body_zones list is empty.",
    )


class AnchorOut(StrictModel):
    asset_version: str
    mesh_name: str
    position: Vector3 = Field(**_VECTOR)
    normal: Vector3 = Field(**_VECTOR)
    body_zone: BodyZone | None
    asset_compatible: bool = Field(
        description="True when asset_version is the model's currently registered asset. "
                    "False: do not draw it; the point needs placing again on the new asset."
    )


class PointProfileItem(StrictModel):
    point_key: str = Field(description="Authoritative Point Check identity: zone_code (wavescan) "
                                       "or point_code (film). Send it back on writes.")
    zone_code: str | None = Field(description="Wave Scan identity; joins wavescan.checkzone. Null for film.")
    point_code: str | None = Field(description="Film identity; joins filmthickness point_code. Null for wavescan.")
    point_no: int | None = Field(description="Walk / display order only, never the identity. "
                                             "Null when the point is not on the list.")
    label: str
    counted: bool | None = Field(description="Point Check counted flag; null for unavailable points.")
    is_extra: bool | None
    unavailable_reason: Literal["retired", "not_on_list"] | None = Field(
        description="Null in points. In unavailable: why the saved location has no live point.")
    retired_at: datetime | None
    revision: int | None = Field(
        ge=1,
        description="This point's latest revision in the layout (a removal counts). "
                    "Null = never saved. Send it as expected_revision on the next write.",
    )
    saved_at: datetime | None
    saved_by: str | None = Field(description="app_user.display_name; never a UUID.")
    anchor: AnchorOut | None = Field(description="Null = no location (never placed, or removed).")


class AssetMesh(StrictModel):
    mesh_name: str
    bounds_min: Vector3 = Field(**_VECTOR)
    bounds_max: Vector3 = Field(**_VECTOR)
    body_zones: list[BodyZone]


class ModelAssetOut(StrictModel):
    asset_version: str
    model_code: str
    asset_path: str = Field(description="Repository path of the GLB the frontend serves.")
    sha256: str
    byte_size: int
    coordinate_system: str
    meshes: list[AssetMesh]


class PointProfileOut(StrictModel):
    plant_code: str
    model_code: str
    domain: Domain
    state: Literal["unconfigured", "configured"] = Field(
        description="unconfigured: nothing was ever saved for this plant x model x domain "
                    "(points all have anchor null; nothing is generated)."
    )
    profile_revision: int = Field(
        ge=0,
        description="Count of writes ever made to this layout; changes on any save/removal. "
                    "A cache key for readers, not a write token (writes are per anchor).",
    )
    last_saved_at: datetime | None
    asset: ModelAssetOut | None = Field(
        description="The registered asset new anchors must use. Null: no supported 3D asset "
                    "for this model, so writes are refused."
    )
    points: list[PointProfileItem] = Field(description="Every live Standard point, walk order.")
    unavailable: list[PointProfileItem] = Field(
        description="Saved locations whose point is retired or no longer on this list. "
                    "Disclosed, never dropped or remapped; a remove may clear them."
    )


class AnchorSaveIn(StrictModel):
    point_key: str = Field(min_length=1, max_length=64, examples=["RRHOOD"])
    point_no: int | None = Field(default=None, ge=1,
                                 description="Optional cross-check against the list's walk number.")
    expected_revision: int | None = Field(
        ge=1, description="This point's revision the editor loaded; null = never saved.")
    anchor: AnchorIn


class AnchorRemoveIn(StrictModel):
    point_key: str = Field(min_length=1, max_length=64, examples=["RRHOOD"])
    point_no: int | None = Field(default=None, ge=1)
    expected_revision: int = Field(ge=1, description="This point's revision the editor loaded.")


class AnchorWritten(PointProfileItem):
    plant_code: str
    model_code: str
    domain: Domain
    replayed: bool = Field(
        description="True when this is a safe retry of a write already persisted by the same "
                    "person with the same content; nothing new was written."
    )
