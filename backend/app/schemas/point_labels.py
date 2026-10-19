"""RO17: point labels (the plant's own word) and the aliases screen."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StrictModel

Domain = Literal["wavescan", "film"]
AliasKind = Literal[
    "zone_map", "global_alias", "film_alias", "location_map", "earlier_label",
    "not_a_point",
]


class PointLabelItem(StrictModel):
    domain: Domain
    model_code: str
    code: str = Field(description="The point's code: its identity, never changed.")
    label: str = Field(description="Current label (newest label row; the code where none).")
    live: bool = Field(description="False for a retired point.")


class PointLabelsOut(StrictModel):
    plant_code: str
    items: list[PointLabelItem] = Field(
        description="Every point, live and retired, of every list of the plant: "
        "by domain, model, point_no, code."
    )


class PointLabelRenameCreate(StrictModel):
    """D-RO17-6: give a point its plant's word. A new label row, nothing else."""

    code: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class PointLabelChangeResult(StrictModel):
    domain: Domain
    model_code: str
    code: str
    label: str
    previous_label: str
    label_id: int
    audit_id: int
    operator_message: str


class PointAliasItem(StrictModel):
    """One spelling that resolves (or resolved) to a point of this list."""

    kind: AliasKind
    alias_id: str = Field(
        description="zone_map: map_id; global_alias: raw_value; film_alias: "
        "alias_id; location_map: raw_location_norm; earlier_label: label_id; "
        "not_a_point: the label (RO18 B5)."
    )
    spelling: str
    code: str = Field(description="The point it loads onto; empty for not_a_point.")
    code_label: str = Field(description="The target point's current label.")
    not_a_point: bool = Field(
        default=False,
        description="RO18 (B5): an uploader's 'Not a point of this list' answer: "
        "rows writing this spelling are kept and never loaded.",
    )
    shared: bool = Field(description="True for a global alias: shared by all plants, read-only here.")
    retirable: bool
    live: bool
    note: str | None
    created_at: datetime | None
    retired_at: datetime | None
    retired_reason: str | None
    stored_facts: int = Field(
        ge=0,
        description="Active readings of this plant x model whose raw label "
        "normalises to this spelling.",
    )


class PointAliasesOut(StrictModel):
    plant_code: str
    domain: Domain
    model_code: str
    items: list[PointAliasItem]


class PointAliasRetireCreate(StrictModel):
    """D-RO17-13 (Admin). Repoint = retire + teach again."""

    kind: AliasKind
    alias_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=500)


class PointAliasRetireResult(StrictModel):
    kind: AliasKind
    alias_id: str
    audit_id: int
    operator_message: str


__all__ = [
    "AliasKind",
    "Domain",
    "PointAliasItem",
    "PointAliasRetireCreate",
    "PointAliasRetireResult",
    "PointAliasesOut",
    "PointLabelChangeResult",
    "PointLabelItem",
    "PointLabelRenameCreate",
    "PointLabelsOut",
]
