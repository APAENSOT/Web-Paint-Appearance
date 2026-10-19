"""The reference data the cleaner needs, as a plain value object.

The vault's ``ReferenceData`` opened a psycopg connection in its constructor
and ran seven queries. That is the coupling `00-ARCHITECTURE.md` §5 rule 1
forbids and `AGENTS.md` §4 calls out ("alias maps are injected"): the cleaner
is the part of this system most worth testing, and a cleaner that needs a
database to exist cannot be tested without one.

So the queries moved to ``app/repositories/reference.py`` and this is what
they produce: a frozen snapshot, built once per ingest run, with no
behaviour beyond lookup.

Every mapping is keyed by ``str.strip().casefold()`` -- the same
normalisation the demo loader used, kept deliberately, because changing it
would silently change which spellings resolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


def normalise_alias(value: str) -> str:
    return str(value).strip().casefold()


@dataclass(frozen=True)
class ReferenceData:
    #: raw spelling -> canonical code
    plant: Mapping[str, str] = field(default_factory=dict)
    model: Mapping[str, str] = field(default_factory=dict)
    checkzone: Mapping[str, str] = field(default_factory=dict)
    color: Mapping[str, str] = field(default_factory=dict)
    paintline: Mapping[str, str] = field(default_factory=dict)

    #: T26 (spec S11/S12). `(plant_code, raw spelling) -> canonical code` for
    #: the two identity vocabularies that are genuinely plant-local. The
    #: cleaner looks here first and falls back to the global maps above, so a
    #: spelling one plant uses for its own model can never relabel another
    #: plant's vehicle. The global bare `P703` -> Ranger rows were exactly
    #: that hazard, and revision 0009 relocates them.
    model_by_plant: Mapping[tuple[str, str], str] = field(default_factory=dict)
    color_by_plant: Mapping[tuple[str, str], str] = field(default_factory=dict)

    #: (model_code, zone_code) pairs that physically exist
    model_zone: frozenset[tuple[str, str]] = frozenset()
    #: model_code -> zones a complete vehicle must have
    expected_zones: Mapping[str, int] = field(default_factory=dict)
    #: plant_code -> whether a blank Serial No. is a reject
    requires_serial: Mapping[str, bool] = field(default_factory=dict)
    #: plant_code -> whether the plant may be uploaded at all (D5 gate)
    active_plants: frozenset[str] = frozenset()
    #: every plant_code known to ref_plant, active or not
    known_plants: frozenset[str] = frozenset()
    #: APPROVED (plant, model, raw zone text) -> zone_code. Never PROPOSED.
    plant_zone_map: Mapping[tuple[str, str, str], str] = field(default_factory=dict)
    #: approved ref_column_alias rows: normalised header -> logical field
    column_alias: Mapping[str, str] = field(default_factory=dict)
    #: existing ref_color.color_name values for the unique-identity fold.
    #: Empty in unit fixtures that only test exact alias maps.
    known_color_names: frozenset[str] = frozenset()
    #: (plant_code, color_name) -> is_offered. Missing key = not offered.
    offered_colors: Mapping[tuple[str, str], bool] = field(default_factory=dict)
    #: (plant_code, model_code) -> is_offered. Missing key = not offered.
    offered_models: Mapping[tuple[str, str], bool] = field(default_factory=dict)
    #: T46 (F5). Models with `wavescan_ok = false` (P703 RAPCAP, P703 SGL).
    #: A WaveScan row that resolves to one is held: not this domain.
    film_only_models: frozenset[str] = frozenset()
    #: (plant_code, color_name) -> family_name. Unused by the cleaner.
    color_family_at_plant: Mapping[tuple[str, str], str | None] = field(
        default_factory=dict
    )
    #: T53 (D-53-09). zone_code -> ref_checkzone.zone_name. The global
    #: checkzone alias is honoured only when the raw label names its zone by
    #: code or by name (or the alias is documented below).
    zone_names: Mapping[str, str] = field(default_factory=dict)
    #: T53. Normalised raw spellings of global checkzone aliases that carry a
    #: reviewed note: a source typo (`17 LTTailagte`) or a documented
    #: abbreviation (`09LHS FD Frnt4`). Their wording is the plant's own.
    checkzone_documented: frozenset[str] = frozenset()
    #: T58 (D-58-01..09). (plant_code, model_code) -> {`gold_key(label)` ->
    #: zone_code}: that plant x model's **live** WaveScan gold
    #: (`ref_plant_ws_point`). A pair present here resolves only onto its own
    #: gold; a pair absent keeps the T53 order (unit fixtures, unseeded pairs).
    plant_gold: Mapping[tuple[str, str], Mapping[str, str]] = field(default_factory=dict)
    #: RO16 (D-RO16-1). (plant_code, model_code) -> the zone_code of the
    #: **first** point (lowest ``point_no``) of that live list. A blank-serial
    #: sheet starts a new car at each row that resolves to it.
    ws_first_point: Mapping[tuple[str, str], str] = field(default_factory=dict)
    #: RO17 (D-RO17-3). (plant_code, model_code, normalise_alias(label)) ->
    #: zone_code, for every unretired label row (current and earlier) of a
    #: **live** point. Read last by `resolve_checkzone`, so it only answers
    #: what nothing else does; keyed by plant and model, so a plant's word
    #: never resolves at another plant or on another model.
    plant_ws_label: Mapping[tuple[str, str, str], str] = field(default_factory=dict)
    #: T64 (ADR 0014). Merged ``ref_color.color_name -> merged_into``. Every
    #: resolved colour is folded through this before the offered check and
    #: the INSERT, so new facts store the canonical name.
    merged_colors: Mapping[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"plants={len(self.plant)} models={len(self.model)} "
            f"zones={len(self.checkzone)} colors={len(self.color)} "
            f"paintlines={len(self.paintline)} model_zone={len(self.model_zone)} "
            f"column_aliases={len(self.column_alias)}"
        )
