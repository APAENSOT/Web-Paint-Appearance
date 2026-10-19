"""FilmThickness read DTOs: facets, vehicles, the gold point grid (T48).

Separate from `schemas/history.py` and `schemas/measurements.py` on purpose
(T48 locked 1). A WaveScan measurement is one checkzone with CF / DOI; a
film fact is one (vehicle, point, layer) thickness. Putting PELT thickness in
`MeasurementOut` would be a silent wrong grain, so film has its own shapes
and its own routes.

Four absences are part of the contract:

* **No grade, pass rate, band or average.** D1 is open. A client must not
  `statusOf` a layer or fold four layers into one number.
* **No invented number.** A catalogue point nobody measured is in the grid
  with `src_location_text: null` and four null layers; a layer the file left
  blank is null. Nothing is padded.
* **No walk order.** `orientation` is the plant's gold Hor / Ver
  (`ref_plant_film_point`, T54), never derived from a label or a row number.
* **Each plant's own gold (T54).** The grid is the plant's own list for the
  model: FTM's is the Desert Island Blue Quick Summary 94, FVL / SAP / AAT
  keep the T46/T47 catalogue. FTM labels are never relabelled onto FVL names.
* **No mutation.** Every shape here is a read of committed facts.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from app.schemas.common import MeasureValue, PageInfo, StrictModel
from app.schemas.history import Week

#: The view every film read goes through (revision 0017), echoed on each
#: payload so a client can see which predicate produced the numbers.
ACTIVE_DATA_SOURCE = "filmthickness_active"

_ACTIVE_NOTE = Field(
    default=ACTIVE_DATA_SOURCE,
    description=(
        "The view these facts were read through: not a duplicate, not "
        "superseded (01-DATA-MODEL.md section 10). Review rows, held labels "
        "(extra points, unmapped locations) and abandoned batches are never "
        "facts, so they are absent by construction."
    ),
)

Orientation = Literal["H", "V"]

#: T103 (D-103-1). Which half of its plant's list a car walked: `box` when
#: it has a reading after the list's lowest complete stop, `no_box` when it
#: has none. Null where the plant's list for the model names no stop, so
#: there is no box section to be on either side of (every plant but FTM
#: today). Computed on the server from `ref_plant_film_point`; no model
#: name, panel word or point code decides it.
FilmBox = Literal["box", "no_box"]


class FilmFacetsOut(StrictModel):
    """Month -> model -> colour pick lists, only where film facts exist."""

    plant_code: str
    plant_is_active: bool
    default_month: str | None = Field(
        description="Latest month with an active film fact, YYYY-MM, or null."
    )
    months: list[str] = Field(
        description=(
            "Months of measured_date that hold active film facts, newest "
            "first. A month with WaveScan data only is not listed."
        )
    )
    month: str | None = Field(description="Echo of the query, or null.")
    models: list[str] = Field(
        description=(
            "ref_model.model_code with film facts in the selected month, "
            "sorted. Empty when no month was given."
        )
    )
    model: str | None
    colors: list[str] = Field(
        description=(
            "Colours with film facts in the selected month, narrowed to the "
            "selected model when one was given. Empty when no month was given."
        )
    )
    color: str | None
    active_data_source: str = _ACTIVE_NOTE


class FilmVehicleOut(StrictModel):
    """One car's film facts, across every committed file that measured it."""

    logical_vehicle_id: str = Field(
        description=(
            "filmthickness.logical_vehicle_id (T46, spec section 6): 64-hex "
            "SHA-256 of 'plant|measured_date|model|colour|identity', identity "
            "being 'vin:<VIN>', else 'job:<Job Number>', else 'blank'. "
            "load_id is NOT inside it: a Cab walk and a Box walk of one car "
            "are one vehicle."
        )
    )
    plant_code: str
    measured_date: date
    model: str = Field(description="ref_model.model_code, e.g. 'P703 DBL RANGER'.")
    model_display_name: str | None = Field(
        description="ref_model.display_name when one is set (e.g. 'RAPCAP')."
    )
    color: str
    serial_no: str | None = Field(description="VIN when the file carried one.")
    date_is_month_only: bool = Field(
        default=False,
        description=(
            "RO18 (B4): the sheet had no date. measured_date is the 1st of the "
            "month a person named; show '<Month YYYY> - day not recorded'. "
            "Such cars never pair."
        ),
    )
    job_nos: list[str] = Field(
        description=(
            "Distinct Job Numbers across the vehicle's loads, sorted. Empty "
            "when none. Identity is the VIN when there is one, so two loads of "
            "one VIN may carry two job numbers."
        )
    )
    identity_complete: bool = Field(
        description=(
            "False when neither a VIN nor a Job Number identifies the car: the "
            "id then groups by plant, day, model and colour only. Nothing is "
            "generated to fill the gap."
        )
    )
    load_ids: list[int] = Field(
        description=(
            "Committed load_batch ids that contributed facts, ascending. "
            "Provenance, not identity."
        )
    )
    source_files: list[str] = Field(
        description="load_batch.source_file of those loads, in load_ids order."
    )
    mapped_point_count: int = Field(
        description=(
            "Gold points of this model with at least one active layer value, "
            "counted as distinct point_code across every load."
        )
    )
    expected_point_count: int | None = Field(
        description=(
            "T54: the size of this plant's gold list for this model "
            "(ref_plant_film_point; 94 for P703 DBL Ranger / Raptor at FVL "
            "and FTM, 94 for FTM RAPCAP / Single CAP too, whose walks fill "
            "only the names they have). Null when the plant has none."
        )
    )
    incomplete: bool = Field(
        description=(
            "True when mapped_point_count differs from expected_point_count, "
            "or expected_point_count is null. A fact, not a grade."
        )
    )
    box: FilmBox | None = Field(
        description=(
            "T103 (D-103-1): 'box' when this car has a reading after the "
            "lowest point its list may complete at (ref_plant_film_point "
            "is_complete_stop), 'no_box' when it has none. Null when that "
            "list names no stop. An FTM Single CAP car is always 'no_box': "
            "its only stop is its last point, so its box section is empty "
            "(D-103-2). A fact about the walk, not a grade."
        )
    )
    identity_note: str | None = Field(
        description=(
            "T103 (D-103-6): the warning this car's loaded rows carry, as "
            "stored when they loaded (D-99-11: the Job Number's colour code "
            "and the file name's disagreeing). Null when they carry none. "
            "Read from stg_review_row.detail; nothing is re-parsed and no "
            "sentence is written here."
        )
    )


class FilmVehiclePage(StrictModel):
    items: list[FilmVehicleOut]
    page: PageInfo
    plant_code: str
    plant_is_active: bool
    month: str
    week: Week | None = Field(
        default=None,
        description=(
            "T108: echo of the week band asked for, or null for the whole "
            "month. The band is the server's (`domain.history.measured_week`), "
            "so the cars of a week card are the cars that card counted."
        ),
    )
    model: str | None
    color: str | None
    active_data_source: str = _ACTIVE_NOTE


class FilmCardOut(StrictModel):
    """T108 (D-108-1): one model + colour card inside a week of Film History.

    The same shape as WaveScan's `HistoryCardOut`, plus the three counts a
    Film card needs, because a Film car carries a Box / No box tag and a
    completeness flag that a WaveScan vehicle set does not.
    """

    model: str = Field(description="ref_model.model_code of every car on the card.")
    model_display_name: str | None = Field(
        description=(
            "ref_model.display_name when one is set ('RAPCAP'), so the card "
            "names the truck in the same words as the cars behind it. A "
            "property of the model, not of the card."
        )
    )
    color: str
    vehicle_count: int = Field(
        description=(
            "Distinct logical_vehicle_id. A Cab file and a Box file of one "
            "car are one vehicle (T46), here as in the vehicles read."
        )
    )
    point_count: int = Field(
        description=(
            "Active film **readings**: one (car, point, layer) thickness is "
            "one reading, which is the grain of `filmthickness`. Not a count "
            "of points -- a car's points are `mapped_point_count`."
        )
    )
    box_count: int = Field(
        description=(
            "Cars on this card whose `box` is 'box' (T103, D-103-1). The "
            "cars' own tag, counted; nothing is re-derived here."
        )
    )
    no_box_count: int = Field(
        description=(
            "Cars whose `box` is 'no_box'. A car whose plant list names no "
            "complete stop has `box: null` and is in neither count, so "
            "box_count + no_box_count may be less than vehicle_count."
        )
    )
    incomplete_count: int = Field(
        description="Cars whose `incomplete` is true (T99). The cars' own flag."
    )
    measured_date_min: date
    measured_date_max: date


class FilmWeekOut(StrictModel):
    week: Week = Field(
        description=(
            "Day bands of measured_date, the same rule as WaveScan History: "
            "1 = days 1-7, 2 = 8-14, 3 = 15-21, 4 = 22-28, 5 = 29 to the end "
            "of that month (02-PIPELINE.md section 8.1)."
        )
    )
    measured_date_min: date
    measured_date_max: date
    cards: list[FilmCardOut]


class FilmSummariesOut(StrictModel):
    plant_code: str
    plant_is_active: bool
    month: str
    model: str | None
    color: str | None
    weeks: list[FilmWeekOut] = Field(
        description=(
            "Weeks descending, weeks with no matching cars omitted. An empty "
            "list is an empty state, not a zero KPI."
        )
    )
    active_data_source: str = _ACTIVE_NOTE


class FilmLayersOut(StrictModel):
    """The four fact layers of one point. Null = not measured, never zero."""

    ecoat: MeasureValue | None
    primer: MeasureValue | None
    base: MeasureValue | None
    clear: MeasureValue | None


class FilmPointOut(StrictModel):
    """One slot of this plant's gold list for the model, measured or not."""

    point_no: int = Field(
        description=(
            "ref_plant_film_point.point_no: the plant's walk order, for "
            "display. Never identity (F10, D-53-02)."
        )
    )
    point_code: str = Field(description="The gold point name, e.g. '022LTFTDOOR'.")
    orientation: Orientation | None = Field(
        description=(
            "Hor / Ver of this plant's gold point (ref_plant_film_point; T47 "
            "for FVL-shaped lists, D-53-06 Hood / Roof / Floor = H for FTM). "
            "Null where nobody has proved it (non-FTM RAPCAP, SGL). "
            "Never computed from src_location_text or a row number."
        )
    )
    src_location_text: str | None = Field(
        description=(
            "The plant's own spelling of the label that loaded onto this slot "
            "(e.g. FTM '029LTFTDOOR' on gold '022LTFTDOOR'). Null when no "
            "active fact exists for the point."
        )
    )
    load_id: int | None = Field(
        description="The load that measured this point, or null."
    )
    source_row: int | None = Field(
        description="Its row in that sheet, or null."
    )
    layers: FilmLayersOut
    counted: bool = Field(
        default=True,
        description=(
            "T99 (D-99-2): whether the latest film_point_setting row says "
            "this point counts towards the dashboard's Hor / Ver. A point "
            "that does not count still appears here with its readings -- a "
            "point hidden from History is a point nobody can put back. True "
            "where no setting exists (every plant but FTM)."
        ),
    )
    is_complete_stop: bool = Field(
        default=False,
        description=(
            "T99 (D-99-8): a walk that ends exactly here is a complete "
            "vehicle, not a short one (FTM RAPCAP 059RTFEND and DBL "
            "064RAPILLAR are no-box trucks). False everywhere else."
        ),
    )
    is_extra: bool = Field(
        default=False,
        description=(
            "T109 (D-109-3): this point is beyond the plant's standard list "
            "for the model (FTM's 095RBXFLOOR and 096-098TGATEIN on the two "
            "DBL lists, and every point added since). A tag beside the point, "
            "not a grade."
        ),
    )
    retired: bool = Field(
        default=False,
        description=(
            "T109 (D-109-4): this point is off the plant's live walk, and it "
            "is in this grid because **this car has a reading on it**. The "
            "reading is kept and shown, it no longer feeds the dashboard for "
            "any month, and it does not make this car incomplete -- "
            "completeness counts live points on both sides. A retired point "
            "with no reading on the car is not listed at all."
        ),
    )


class FilmPointGridOut(StrictModel):
    """The whole catalogue of the vehicle's model, one entry per gold point.

    Its length is the catalogue's (94 for Ranger / Raptor, 93 RAPCAP, 58
    SGL), not the number of rows a file happened to contain.
    """

    vehicle: FilmVehicleOut
    items: list[FilmPointOut] = Field(
        description="Every catalogue point of the model, in point_no order."
    )
    plant_code: str
    active_data_source: str = _ACTIVE_NOTE
