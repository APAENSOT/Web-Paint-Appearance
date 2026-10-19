"""Turn a RawRow into a clean row, a reject, or a quarantined row.

Ported from the vault's ``cleaner.py``. Every spelling rule stays in the
database alias tables; a new colour next month is one INSERT, not a code
change. If a value is not in an alias table the row is REJECTED -- the loader
never guesses and never silently writes NULL.

The one rule expressed in code is ``tolerance_group``, derived from the zone
name (HOOD/ROOF -> Horizontal, else Vertical). The file's own column is
deliberately ignored: it contradicts itself on 36 of 2479 rows
(`02-PIPELINE.md` §5, "Do not reverse that").

**Two deliberate changes from the vault version.** Both are this repo's
rules, not preferences, and both are argued in `docs/reports/T04-INGEST.md`:

* ``ReferenceData`` is injected, not built from a connection (§ references).
* **Measurements are no longer rounded on the way in.** The vault rounded
  every value to one decimal at ingest. `AGENTS.md` §4 lists rounding CF in
  ``wavescan`` as a defect and L12 stores measurements at full precision,
  rounding only in views and UI. So the value written is the value the cell
  held, carried as ``Decimal`` rather than ``float`` so no digit is invented
  or lost on the way. Rounding still happens -- inside ``dedup``, for
  comparison only, where it belongs.

**T17 adds one input: ``expected_plant``.** An upload now declares which
plant it belongs to and the server checks that claim against the workbook
*before* the bytes are stored (`02-PIPELINE.md` §1-§3). By the time rows
reach this module the only thing left to do is fill the blanks: a Plant cell
that is empty takes the expected code and says so. Nothing here guesses a
plant from a filename, a route, or a majority vote of the other rows.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Collection, Mapping

from app.domain.color_identity import fold_colour, unique_colour_identity
from app.domain.mapping_engine import extract_position
from app.domain.reader import (
    MEASURE_ALL,
    MEASURES_HOLE_APPROVABLE,
    MEASURES_REQUIRED,
    MISSING_MEASUREMENT_DETAIL,
    RawRow,
)
from app.domain.panel_walk import (
    SPECIFICITY_ROUGH,
    canonical_named_by,
    classify_against_canonical,
)
from app.domain.references import ReferenceData, normalise_alias
from app.domain.ws_plant_gold import gold_key, ws_tolerance

#: Model strings that mean "unknown", not a real model.
UNIDENTIFIED_MODELS = {"(none)", "none", "n/a", "na", "-", "unknown"}

#: Report roll-up markers a pivot writes into an identity column (T26 / spec
#: S16). FTM May carries 1064 of these in 1320 rows and FVL September 133 in
#: 165: the same numbers repeated at progressively less specific filter
#: levels. Loading one would invent a vehicle whose measurements are an
#: average of other vehicles'.
#:
#: **Bracketed forms only, deliberately.** A bare `All` is what the reviewed
#: workbooks do not write, and treating it as a sentinel would let a real
#: colour, paintline or model spelled `All` vanish from the facts -- which is
#: the silent delete `AGENTS.md` opens with, pointed the other way.
AGGREGATE_SENTINELS = {"[all]", "(all)", "[all values]"}

#: Where a sentinel makes the row an aggregate. Only identity: a roll-up is a
#: row that does not say *which* vehicle, panel, day or colour it is about. A
#: sentinel in a measure column is a bad number and stays a reject.
AGGREGATE_IDENTITY_FIELDS = (
    "date", "plant", "model", "checkzone", "color", "paintline", "serial_no",
)

#: FVL G2 writes the text ``(None)`` in Paintline when the export has no
#: booth. That is a missing optional line, not a roll-up and not a booth
#: name. Mapping it to BOOTH1 would invent a production line. It must not
#: join ``AGGREGATE_SENTINELS`` or every leaf row of the named September
#: file would vanish (those rows also carry a real serial).
MISSING_PAINTLINE_SENTINELS = {"(none)"}

#: Review-only marker on ``CleanRow`` / ``stg_review_row.canonical`` when
#: paintline is NULL because the cell was a documented sentinel, not because
#: it was blank. Not a ``wavescan`` column. S18 skips this case (spec P1/P8).
PAINTLINE_OMITTED_SENTINEL = "sentinel"


class RejectReason:
    """`01-DATA-MODEL.md` §7 / ``ck_reject_reason``."""

    UNKNOWN_PLANT = "UNKNOWN_PLANT"
    UNKNOWN_MODEL = "UNKNOWN_MODEL"
    UNKNOWN_CHECKZONE = "UNKNOWN_CHECKZONE"
    UNKNOWN_COLOR = "UNKNOWN_COLOR"
    COLOR_NOT_OFFERED = "COLOR_NOT_OFFERED"
    UNKNOWN_PAINTLINE = "UNKNOWN_PAINTLINE"
    MODEL_NOT_OFFERED = "MODEL_NOT_OFFERED"
    #: T115-FIX (D-115F-1): a Film-only model (RAPCAP, Single CAP) on a Wave
    #: Scan row. Not "removed from this plant": no Attach makes it a Wave
    #: Scan vehicle, so it is never reloaded by one (migration 0040).
    FILM_ONLY_MODEL = "FILM_ONLY_MODEL"
    ZONE_NOT_VALID_FOR_MODEL = "ZONE_NOT_VALID_FOR_MODEL"
    MISSING_MEASUREMENT = "MISSING_MEASUREMENT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    BAD_DATE = "BAD_DATE"
    BAD_NUMBER = "BAD_NUMBER"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    DUPLICATE_ROW = "DUPLICATE_ROW"
    PLANT_OUT_OF_SCOPE = "UNKNOWN_PLANT"
    #: ADR 0013 / T39: the Plant cell names something other than the upload
    #: page's plant. Held and asked about; never relabelled silently.
    PLANT_MISMATCH = "PLANT_MISMATCH"
    #: RO16 (D-RO16-3): a car of a blank-serial sheet that carries two days or
    #: two colours. ``ck_reject_reason``'s own catch-all: no specific reason
    #: names a car, and its sentence (``detail``) is what the row shows.
    OTHER = "OTHER"


#: How a nonblank Plant cell came to mean the page plant (T39). Evidence on
#: the row, never identity.
PLANT_READ_PREFIX = "prefix"
PLANT_READ_CONFIRMED = "confirmed"

_PLANT_TOKEN = re.compile(r"[\s/_\-]+")


def dedup_key(
    plant: str,
    serial_no: str | None,
    checkzone: str,
    measured_date: date,
    model: str,
    color: str,
    car_key: str | None = None,
) -> tuple:
    """Which stored point a new point could be a copy of (T39-FIX, ADR 0013 8a).

    * Serial present: ``(plant, serial, checkzone)`` -- unchanged. Serial
      alone is not unique across plants.
    * Serial NULL: ``(plant, measured_date, model, colour, checkzone)``. The
      sheet is the vehicle, so the day, model and colour stand in for the
      serial. ``(plant, NULL, zone)`` alone would merge different days and
      colours, and is never used.
    * RO16 (D-RO16-5): a car of a many-car blank-serial sheet adds its
      ``car_key``: ``(plant, measured_date, model, colour, car_key,
      checkzone)``. Without one the key is exactly the line above.

    The two shapes differ in length, so a blank-serial point can never
    collide with a named serial on another car. The 80% measure rule in
    ``dedup`` still has to agree before anything is called a duplicate.
    """
    if serial_no is not None and str(serial_no).strip():
        return (plant, serial_no, checkzone)
    if car_key:
        return (plant, measured_date.isoformat(), model, color, car_key, checkzone)
    return (plant, measured_date.isoformat(), model, color, checkzone)


@dataclass
class CleanRow:
    measured_date: date
    plant: str
    model: str
    checkzone: str
    color: str
    tolerance_group: str
    paintline: str | None  # NULL when blank, absent or a sentinel (ADR 0013)
    serial_no: str | None  # NULL when blank or absent (ADR 0013)
    measures: dict[str, Decimal | None]

    source_file: str
    source_sheet: str
    source_row: int

    # Provenance: exactly what the file wrote in the Checkzone column, and
    # the leading position number parsed out of it. Never identity -- only
    # for tracing a row back to its cell and auditing a mapping later.
    src_zone_text: str | None = None
    src_zone_no: int | None = None

    #: True when the Plant cell was blank and the value above came from the
    #: upload's ``expected_plant`` (T17). Evidence, not identity: the row is
    #: written exactly as if the cell had said it, and the count of filled
    #: cells is disclosed on the batch's ``batch.upload`` audit event.
    plant_filled: bool = False

    #: ``PAINTLINE_OMITTED_SENTINEL`` when Paintline was ``(None)`` (or
    #: another documented missing-paintline sentinel). Unset when the cell
    #: was truly blank. Review evidence only -- never written to ``wavescan``.
    paintline_omitted_reason: str | None = None

    #: T39. ``PLANT_READ_PREFIX`` when the cell was e.g. ``AAT U704`` on the
    #: AAT page, ``PLANT_READ_CONFIRMED`` when an Engineer confirmed the text
    #: means the page plant. Unset when the cell resolved by alias or was
    #: blank (``plant_filled``).
    plant_read_as: str | None = None

    #: RO16 (D-RO16-2). Which car of a blank-serial sheet holding several
    #: cars this row is (`car_fingerprint`). None when the row has a serial
    #: or its sheet is one car. Never a serial.
    car_key: str | None = None

    #: RO18 (B4). The sheet had no date: ``measured_date`` is the 1st of the
    #: month a person named, and the day is not recorded.
    date_is_month_only: bool = False

    def key(self) -> tuple:
        """Vehicle-zone identity for dedup. See :func:`dedup_key`."""
        return dedup_key(
            self.plant, self.serial_no, self.checkzone,
            self.measured_date, self.model, self.color, self.car_key,
        )

    def completeness(self) -> int:
        return sum(1 for m in MEASURE_ALL if self.measures.get(m) is not None)


@dataclass
class Reject:
    reason: str
    detail: str
    source_file: str
    source_sheet: str
    source_row: int
    raw: dict[str, Any]
    column: str | None = None
    value: str | None = None
    #: RO16: the car this held row belongs to, as `CleanRow.car_key`.
    car_key: str | None = None


@dataclass
class Unidentified:
    raw_model: str | None
    plant: str | None
    serial_no: str | None
    measured_date: date | None
    source_file: str
    source_sheet: str
    source_row: int
    raw: dict[str, Any]
    suggested_model: str | None = None


@dataclass
class Aggregate:
    """A report roll-up row, preserved and never a fact (T26 / spec S16).

    Not a reject: nothing is wrong with it, and calling it one would put
    thousands of rows behind the `REJECTED_ROWS` acknowledgement gate that
    exists for values the platform would not accept. It is a different kind
    of row -- one the source file wrote about *several* vehicles at once --
    so it gets its own disposition, stays in `stg_raw` and in the review
    projection, and is disclosed as a count.
    """

    fields: tuple[str, ...]
    values: dict[str, str]
    plant: str | None
    source_file: str
    source_sheet: str
    source_row: int
    raw: dict[str, Any]
    #: T99 (D-99-6). Which kind of kept-and-not-loaded row this is, when the
    #: domain has more than one. None means the domain's own default: a
    #: WaveScan ``[All]`` roll-up, or a Film specification limit row.
    reason: str | None = None


@dataclass
class CleanResult:
    clean: list[CleanRow] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)
    unidentified: list[Unidentified] = field(default_factory=list)
    #: T26. Kept beside the other three rather than inside them, because a
    #: roll-up is neither a fact nor a failure.
    aggregates: list[Aggregate] = field(default_factory=list)

    def total(self) -> int:
        return (
            len(self.clean) + len(self.rejects) + len(self.unidentified)
            + len(self.aggregates)
        )

    @property
    def plant_cells_filled(self) -> int:
        """How many clean rows took their plant from ``expected_plant`` (T17).

        Counted over clean rows only. The authoritative fill count for the
        audit event is the one the upload gate produced before any byte was
        stored, because that one covers every data row whatever its later
        disposition; this is the parse-time view of the same fill.
        """
        return sum(1 for row in self.clean if row.plant_filled)


# =====================================================================
_DATE_TEXT = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s|$)")


def parse_date(raw: RawRow) -> tuple[date | None, str | None]:
    """Return (date, error).

    AAT text dates carry no year -- it comes from the Year column.
    """
    value = raw.get("date")

    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if value is None:
        return None, "date is blank"

    text = str(value).strip()

    try:
        return datetime.fromisoformat(text).date(), None
    except ValueError:
        pass

    m = _DATE_TEXT.match(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year_val = raw.get("year")
        if year_val is None:
            return None, f"date {text!r} has no year and the Year column is blank"
        try:
            year = int(float(str(year_val).strip()))
        except (TypeError, ValueError):
            return None, f"Year column {year_val!r} is not a number"
        try:
            return date(year, month, day), None
        except ValueError as exc:
            return None, f"date {text!r} with year {year} is invalid: {exc}"

    return None, f"unrecognised date format: {text!r}"


#: English, not ``calendar.month_name``, which follows the machine's locale.
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)
_MONTH_BY_NAME = {
    spelling: i
    for i, name in enumerate(MONTH_NAMES, start=1)
    for spelling in (name.casefold(), name[:3].casefold())
}


def month_word(word: str) -> int | None:
    """RO18. 1-12 for a full English month name, or the first 3 or 4 letters
    of exactly one (``Sept``), in any case; else None."""
    word = str(word).strip().casefold()
    found = [
        number for number, name in enumerate(MONTH_NAMES, 1)
        if name.casefold() == word
        or (len(word) in (3, 4) and name.casefold().startswith(word))
    ]
    return found[0] if len(found) == 1 else None


# =====================================================================
# RO18 (B4, RO09): a sheet with no date anywhere
# =====================================================================
#: Held, one question for the whole sheet, until a person names the month.
REASON_MONTH_UNKNOWN = "MONTH_UNKNOWN"
_MONTH_YEAR_WORD = re.compile(r"(?<![A-Za-z])([A-Za-z]{3,9})[\s._'-]*((?:19|20)\d{2})(?!\d)")
_MONTH_YEAR_NUMBER = re.compile(r"(?<!\d)(\d{1,2})[._-]((?:19|20)\d{2})(?!\d)")


def suggest_month(filename: str) -> str | None:
    """``YYYY-MM`` when the file name names exactly one month (``Jul2026``,
    ``July 2026``, ``07.2026``); else None. Only ever a suggestion: a person
    confirms the month (RO09 Q1)."""
    found = set()
    for pattern, number in ((_MONTH_YEAR_WORD, month_word), (_MONTH_YEAR_NUMBER, int)):
        for match in pattern.finditer(str(filename)):
            month = number(match.group(1))
            if month and 1 <= month <= 12:
                found.add(f"{match.group(2)}-{month:02d}")
    return found.pop() if len(found) == 1 else None


def month_question_detail(filename: str) -> str:
    """The sheet's one question, with the file name's month as a suggestion."""
    suggested = suggest_month(filename)
    hint = (
        f" The file name suggests {month_words_of(suggested)}; confirm it or "
        f"pick another month." if suggested else ""
    )
    return (
        "This sheet has no measuring date. Which month were these cars "
        "measured? Its cars are filed under that month with \"day not "
        "recorded\", and they never pair with the other domain." + hint
    )


def month_words_of(value: str) -> str:
    """``2026-07`` -> ``July 2026``."""
    first = parse_month_answer(value)
    return f"{MONTH_NAMES[first.month - 1]} {first.year}" if first else str(value)


def parse_month_answer(value: object) -> date | None:
    """``YYYY-MM`` -> the 1st of that month (2000-2100), else None."""
    match = re.fullmatch(r"\s*(\d{4})-(\d{2})\s*", str(value or ""))
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    return date(year, month, 1)


def _whole_number(value: object) -> int | None:
    """``9``, ``9.0`` or ``'9'`` -> 9; anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def read_month_cell(value: object) -> int | None:
    """RO15 (D-RO15-1): the Month cell as 1-12, or None when it does not read."""
    if isinstance(value, str) and value.strip().casefold() in _MONTH_BY_NAME:
        return _MONTH_BY_NAME[value.strip().casefold()]
    month = _whole_number(value)
    return month if month is not None and 1 <= month <= 12 else None


def date_disagrees(raw: RawRow, measured: date) -> tuple[str, str] | None:
    """RO15 (D-RO15-1/-2): ``(column, detail)`` when the row's own Month or
    Year cell names another month than its date, else None.

    A blank or unreadable cell is not checked: a spelling we do not know
    never creates a hold.
    """
    in_ = f"date {measured.isoformat()} is in {MONTH_NAMES[measured.month - 1]} {measured.year}"
    month = read_month_cell(raw.get("month"))
    if month is not None and month != measured.month:
        return "month", f"{in_} but this row's Month cell says {raw.get('month')!r}"
    year = _whole_number(raw.get("year"))
    if year is not None and year != measured.year:
        return "year", f"{in_} but this row's Year cell says {raw.get('year')!r}"
    return None


def parse_measure(value: object) -> tuple[Decimal | None, str | None]:
    """Cell value -> Decimal, unrounded.

    ``Decimal(str(x))`` for a float is deliberate: it captures the shortest
    decimal that reproduces the stored double, which is exactly what the
    workbook holds. ``Decimal(float)`` would instead expand the binary value
    into fifty digits that the file never contained.
    """
    if value is None:
        return None, None
    if isinstance(value, Decimal):
        return value, None
    if isinstance(value, bool):
        return None, f"{value!r} is not a number"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, None
    else:
        text = str(value)
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None, f"{value!r} is not a number"
    if not parsed.is_finite():
        return None, f"{value!r} is not a finite number"
    return parsed, None


def derive_tolerance(zone_code: str) -> str:
    """Hood / Roof / Floor in the zone name -> Horizontal, else Vertical.

    T58 (D-58-04): any case, so SAP ``01RHS Hood Rr28`` is Horizontal -- the
    same rule as ``ref_checkzone.ck_zone_rule`` (revision 0022). Verified
    49/49 on the AAT+FTM catalogue before; never from walk order."""
    return ws_tolerance(zone_code)


_LEADING_POSITION = re.compile(r"^\s*\d+")
_NOT_ALNUM = re.compile(r"[^0-9a-z]")


def _compact(text: str) -> str:
    return _NOT_ALNUM.sub("", str(text).casefold())


def label_names_zone(label: str, zone_code: str, zone_name: str | None = None) -> bool:
    """Does this panel text already name ``zone_code``? (T53, D-53-09)

    The leading position number is dropped, then letters and digits are
    compared with spaces and punctuation removed. ``01 RRHOOD`` and
    ``06LFFENDER`` name their zones by code; ``03Hood Middle30`` names
    ``HOODMIDDLE`` and ``19Tailgate Middle14`` names ``TGMIDDLE`` by catalogue
    name. ``01HOOD`` names neither ``RRHOOD`` nor ``RR Hood``: which hood is
    exactly the information the label does not carry.
    """
    core = _compact(_LEADING_POSITION.sub("", str(label)))
    if not core:
        return False
    if _compact(zone_code) in core:
        return True
    name = _compact(zone_name or "")
    return bool(name) and name in core


class PlantNotOnboarded(Exception):
    """A whole file belongs to a plant that is not open for uploads.

    Raised before any row is cleaned. `02-PIPELINE.md` and D5 (FVL) want a
    clear refusal of the *file*, not 1504 identical per-row rejects that a
    reviewer has to read to work out that the plant is not onboarded yet.
    """

    def __init__(self, plant_code: str, detail: str) -> None:
        super().__init__(detail)
        self.plant_code = plant_code
        self.detail = detail


def out_snapshot(raw: RawRow) -> dict[str, Any]:
    """The row's cells as a reject keeps them (dates as ISO text)."""
    return {
        k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
        for k, v in raw.values.items()
    }


def read_serial(raw: RawRow) -> str | None:
    """The row's serial, or None when blank, absent or ``(None)`` (ADR 0013)."""
    serial_raw = raw.get("serial_no")
    serial: str | None = None
    if serial_raw is not None:
        if isinstance(serial_raw, float) and serial_raw.is_integer():
            serial = str(int(serial_raw))
        else:
            serial = str(serial_raw).strip()
    if not serial or serial.casefold() in MISSING_PAINTLINE_SENTINELS:
        return None
    return serial


#: RO16 (D-RO16-2): the readings a car's fingerprint reads, as written.
CAR_KEY_MEASURES = ("lw", "sw", "cf", "doi")


def car_fingerprint(points) -> str:
    """D-RO16-2. 16 hex characters of SHA-256 over one car's walk.

    ``points`` are ``(checkzone, raw row)`` in sheet order: the resolved
    checkzone (the label as written when it does not resolve) and LW, SW, CF,
    DOI as written. The file name is not in it, so the same readings uploaded
    again under another name are the same car, and two cars share it only
    when every reading is identical (as RO14's ``walk_fingerprint``).
    """
    text = "\n".join(
        "|".join([zone, *(
            "" if raw.get(m) is None else str(raw.get(m)) for m in CAR_KEY_MEASURES
        )])
        for zone, raw in points
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def car_mixed_detail(index: int, cars: int, row: int, what: str,
                     first: object, second: object) -> str:
    """D-RO16-3. One car carrying two days or two colours.

    The car's words are RO14's ``film_walk.car_of``; the cleaner cannot import
    the Film module (it imports this one).
    """
    return (
        f"Car {index + 1} of {cars} on this sheet (starting at row {row}) "
        f'carries two {what}s, "{first}" and "{second}". One car is one day '
        f"and one colour, so this car's rows are held and do not load. Fix "
        f"the file and upload it again."
    )


class Cleaner:
    """Injected reference data in, clean rows / rejects / quarantine out.

    ``expected_plant`` is the plant scope the upload declared (T17,
    `02-PIPELINE.md` §1). It is a canonical ``ref_plant.plant_code`` the
    service already resolved and checked; the cleaner never resolves a route
    or a filename into a plant itself. Its only effect here is that a **blank
    or missing** Plant cell inherits it instead of rejecting as
    ``MISSING_REQUIRED_FIELD``, and the row is marked ``plant_filled`` so the
    fill can be disclosed rather than silently applied.

    A *nonblank* cell is never overwritten silently. T39 (ADR 0013): a cell
    that starts with the page plant (``AAT U704`` on AAT) is that plant; a
    cell an Engineer confirmed means the page plant is that plant; any other
    cell is held as ``PLANT_MISMATCH`` and asked about. Relabelling FTM as
    AAT without that answer would be exactly the silent wrong label
    `AGENTS.md` opens with.
    """

    def __init__(
        self,
        ref: ReferenceData,
        allowed_plants: tuple[str, ...],
        expected_plant: str | None = None,
        *,
        confirmed_plant_texts: Collection[str] = (),
        hole_rows: Collection[int] = (),
        confirmed_panels: Mapping[str, str] | None = None,
        no_date_column: bool = False,
        month_only: date | None = None,
        month_detail: str = "",
    ):
        self.ref = ref
        #: RO18 (B4). The sheet has no date column: every row is the month a
        #: person named (``month_only``, the 1st), or, unanswered, is held
        #: with the sheet's one question (``month_detail``).
        self.no_date_column = no_date_column
        self.month_only = month_only if no_date_column else None
        self.month_detail = month_detail
        self.allowed_plants = {p.upper() for p in allowed_plants}
        self.expected_plant = expected_plant.upper() if expected_plant else None
        #: T39. Normalised Plant texts an Engineer confirmed mean the page
        #: plant, and source rows they approved to load without LW/SW. Both
        #: come from ``worksheet_decision``; the cleaner never decides them.
        self.confirmed_plant_texts = frozenset(
            normalise_alias(t) for t in confirmed_plant_texts
        )
        self.hole_rows = frozenset(int(r) for r in hole_rows)
        #: T94 (D-94-2, D-94-6). What a person confirmed a rough label is,
        #: **for this upload**, as ``{(model_code | None, normalised raw
        #: panel text): zone_code}``. A key whose model is None came from a
        #: row written before the model was recorded and applies to any
        #: model of the sheet; a key with a model applies to that model
        #: only, which is the scope D-94-1 locks.
        #:
        #: Handed in per batch from ``worksheet_decision`` and never read
        #: from a ``ref_*`` table, so last month's answer structurally
        #: cannot file this month's hood (the same guarantee D-90-11 made).
        self.confirmed_panels = {
            (model, normalise_alias(raw)): zone
            for (model, raw), zone in (confirmed_panels or {}).items()
            if raw and zone
        }
        #: ``{model_code: the normalised panel labels this model's walk
        #: makes rough}`` (D-94-1). Recomputed by :meth:`clean_all` from the
        #: rows it is given, because the test is over the whole sheet *for
        #: one model* and no single row can answer it.
        #:
        #: Keyed by model and not flat, because one sheet carries two models
        #: and they are two different walks. FVL writes ``11ROOF`` for both
        #: its Ranger -- whose own gold list has no canonical positions at
        #: all, so nothing there is rough -- and for ``CX743``, whose
        #: canonical list holds ``16ROOF`` and ``32ROOF`` and for which
        #: ``11ROOF`` therefore names neither. A flat set would hold the
        #: Ranger row for the CX743 row's question.
        #:
        #: Empty until :meth:`clean_all` runs: a caller that cleans one row
        #: in isolation has no sheet to classify, and inventing one would be
        #: worse than classifying nothing.
        self.rough_panels: dict[str, frozenset[str]] = {}

    # ---------------------------------------------------------
    @staticmethod
    def plant_first(
        scoped: Any, glob: Any, plant: str | None, raw_value: str
    ) -> str | None:
        """This plant's spelling, else an unambiguous global one (S11/S12).

        The order is the whole rule. A plant-scoped row is a statement about
        one plant's wording, so it wins where it exists; a global row is a
        statement about a spelling that means the same everywhere, so it is
        the fallback rather than the default. Before T26 there was only the
        global map, and the bare `P703` -> Ranger rows in it meant every
        plant silently inherited an assumption made about one of them --
        including SAP, whose `P703 RAP` is not a Ranger at all.
        """
        key = normalise_alias(raw_value)
        if plant:
            found = scoped.get((plant, key))
            if found:
                return found
        return glob.get(key)

    def offered_model_code(self, plant: str | None, raw_value: str) -> str | None:
        """The Model cell **is** a catalogue code this plant offers (T55, D-55-01).

        Exact after the alias normalisation (trim + casefold) and nothing
        more: no prefix, no substring, no colour-style unique fold. ``P703``
        and ``P703 DBL`` are not ``P703 DBL RANGER``; a code offered at
        another plant never counts here. Exactly one offered match or None.

        T112-FIX (D-112F-5): a FilmThickness-only model is never a Wave Scan
        match here, even though its offer row now exists (migration 0036): the
        offer map is both domains' gate, this lookup is Wave Scan's alone, and
        a cell spelled ``P703 RAPCAP`` keeps the outcome it had before.
        """
        if not plant:
            return None
        key = normalise_alias(raw_value)
        found = [
            model for (p, model), offered in self.ref.offered_models.items()
            if p == plant and offered and normalise_alias(model) == key
            and model not in self.ref.film_only_models
        ]
        return found[0] if len(found) == 1 else None

    def resolve_plant(self, raw_value: str | None) -> str | None:
        """Canonical plant code for a raw Plant cell, or None."""
        if not raw_value:
            return None
        return self.ref.plant.get(normalise_alias(raw_value))

    def page_plant_of(self, raw_value: str | None) -> tuple[str | None, str | None]:
        """Does this nonblank Plant cell mean the upload page's plant? (T39)

        Returns ``(plant, read_as)``. ``plant`` is ``expected_plant`` when the
        cell resolves to it by alias, **starts with** it (``AAT U704`` on the
        AAT page -- the extra words are not a second plant), or is a text an
        Engineer confirmed. Otherwise ``(None, None)``: the caller holds the
        row and asks. Nothing here relabels another plant's name.
        """
        if not raw_value or not self.expected_plant:
            return None, None
        whole = self.resolve_plant(raw_value)
        if whole == self.expected_plant:
            return self.expected_plant, None
        first = _PLANT_TOKEN.split(str(raw_value).strip(), maxsplit=1)[0]
        if whole is None and first and (
            self.resolve_plant(first) == self.expected_plant
            or first.upper() == self.expected_plant
        ):
            return self.expected_plant, PLANT_READ_PREFIX
        if normalise_alias(raw_value) in self.confirmed_plant_texts:
            return self.expected_plant, PLANT_READ_CONFIRMED
        return None, None

    def canonical_plant(self, raw_value: str | None) -> str | None:
        """Best-effort canonical code for a plant *claim*.

        The alias table first, then the literal upper-cased code, because a
        plant can exist in ``ref_plant`` with no alias row yet -- FVL does
        (D5). Returning the bare code lets the caller answer "known but not
        onboarded" instead of the less true "unknown plant". Returns None
        only for a blank claim.
        """
        if not raw_value or not str(raw_value).strip():
            return None
        return self.resolve_plant(raw_value) or str(raw_value).strip().upper()

    def check_plant_is_onboarded(self, raw_values: set[str]) -> None:
        """Refuse a file whose plant exists but is not open for uploads.

        The check is driven by ``ref_plant.is_active``, not by a plant name
        in code: `AGENTS.md` rule 6 forbids hardcoding a plant, and D5 is a
        decision about FVL specifically, not about a category of plant.
        """
        for raw in sorted(v for v in raw_values if v):
            code = self.resolve_plant(raw) or str(raw).strip().upper()
            if code in self.ref.known_plants and code not in self.ref.active_plants:
                raise PlantNotOnboarded(
                    code,
                    f"plant {code!r} is known but not onboarded, so this file "
                    f"cannot be ingested. Its rows would need decisions this "
                    f"platform has not made: onboarding is a deferred decision "
                    f"(docs/DEFERRED.md D5). Nothing was stored.",
                )

    # ---------------------------------------------------------
    def canonical_panels(self, plant: str, model: str) -> frozenset[str]:
        """T94: the panels of this plant x model a position can be named by.

        A panel this plant has **live** (`ref_plant_ws_point`) that is also a
        position on the **model's own catalogue** (`ref_model_zone`). That is
        the same list `services/panel_pool.py` calls canonical and offers on
        the match screen, built here from `ReferenceData` alone so the
        classification needs no second read.

        It is deliberately not the whole live list. FTM carries 64 live
        panels for each P703 model -- the 32 canonical positions plus the
        T58 numbered block -- and the numbered block is what made ``01HOOD``
        "Ready to add": a label matched a panel literally spelled ``01HOOD``.
        Classifying against the catalogue instead asks the question the owner
        asked, which is which of the five hoods this is (D-94-1, D-94-2).
        """
        gold = self.ref.plant_gold.get((plant, model))
        if not gold:
            return frozenset()
        return frozenset(
            zone for zone in gold.values() if (model, zone) in self.ref.model_zone
        )

    def rough_panel_labels(self, rows) -> dict[str, frozenset[str]]:
        """T94 (D-94-1): per model, the normalised labels it makes rough.

        Grouped by ``(plant, model)``, because that is the scope the rule is
        locked at: one sheet can carry two models and they are two different
        walks, and a label is rough or specific *for a model*. The plant is
        the page plant this cleaner was built for -- the only plant whose
        catalogue a row of this upload can load onto.

        Rows whose model does not resolve, and pairs with no canonical list
        at all, contribute nothing. Nothing here rejects a row or decides a
        pair; it only says which labels will be asked about.
        """
        if not self.expected_plant:
            return {}
        per_model: dict[str, dict[str, None]] = {}
        for raw in rows:
            model_raw = raw.text("model")
            zone_raw = raw.text("checkzone")
            if not model_raw or not zone_raw:
                continue
            if model_raw.casefold() in UNIDENTIFIED_MODELS:
                continue
            model = self.plant_first(
                self.ref.model_by_plant, self.ref.model, self.expected_plant,
                model_raw,
            ) or self.offered_model_code(self.expected_plant, model_raw)
            if not model:
                continue
            per_model.setdefault(model, {})[zone_raw] = None
        out: dict[str, frozenset[str]] = {}
        for model, labels in per_model.items():
            canonical = self.canonical_panels(self.expected_plant, model)
            if not canonical:
                continue
            verdicts = classify_against_canonical(list(labels), canonical)
            rough = frozenset(
                normalise_alias(label)
                for label, verdict in verdicts.items()
                if verdict == SPECIFICITY_ROUGH
            )
            if rough:
                out[model] = rough
        return out

    # ---------------------------------------------------------
    def resolve_checkzone(self, plant: str, model: str, zone_raw: str) -> str | None:
        """The zone_code a plant's panel text means on this model, or None.

        **T58 (D-58-09)**, when this plant x model has a live WaveScan gold
        list (`ref_plant_ws_point`), resolve onto that list only:

        1. The text **is** a gold label here, up to the leading-zero pad
           (``01HOOD`` == ``1HOOD``; D-58-03). Stored ``checkzone`` is that
           gold name -- FVL ``11ROOF``, SAP ``01RHS Hood Rr28`` -- never
           ``RRHOOD``. The walk number never joins plants or models.
        2. The T53 global alias (names the zone, or a documented typo) --
           **only if** its target is gold here (AAT/FTM ``01 RRHOOD``).
        3. A live ``ref_plant_zone_map`` -- **only if** its target is gold
           here. T31 FVL maps onto ``RRHOOD`` are not, so they are not read.
        4. Else None: held for the uploader. Nothing is minted.

        A pair with **no** gold list keeps the T53 order below.

        T53 (D-53-09). The order is the rule:

        1. A live ``ref_plant_zone_map`` row for ``(plant, model, raw)`` -- an
           Engineer's ``ALIAS_CHECKZONE`` pick or a named-owner pack. The same
           text can mean different panels at different plants.
        2. The text **is** a zone code already on this model.
        3. The global ``ref_checkzone_alias``, but only when the text is that
           plant's own wording of the zone: it names the target by code
           (``01 RRHOOD``) or by catalogue name (``19Tailgate Middle14``), or
           the alias row documents a source typo or abbreviation
           (``17 LTTailagte``).

        Anything else is None and the row is held for the uploader to pick.
        A compact ``01HOOD`` never becomes ``RRHOOD`` through the global
        table: that would move one plant's checkpoint onto another plant's
        label without anyone choosing it. The caller still checks the zone
        is on this model (``ZONE_NOT_VALID_FOR_MODEL``).
        """
        key = normalise_alias(zone_raw)
        if key in self.rough_panels.get(model, frozenset()):
            # T94 (D-94-2). A rough label is never resolved by the
            # catalogue, whatever the catalogue holds -- including a panel
            # spelled exactly like it. The only answer it takes is the one a
            # person confirmed for this upload, and that answer has to be a
            # canonical position of this plant x model or it is not an
            # answer at all. This replaces retirement as the mechanism: the
            # numbered block may stay live and simply stops being reachable.
            confirmed = self.confirmed_panels.get(
                (model, key), self.confirmed_panels.get((None, key))
            )
            return (
                confirmed
                if confirmed in self.canonical_panels(plant, model)
                else None
            )
        gold = self.ref.plant_gold.get((plant, model))
        if gold is not None:
            found = gold.get(gold_key(zone_raw))
            if found is not None:
                return found
            codes = set(gold.values())
            glob = self.ref.checkzone.get(key)
            if glob in codes and (
                key in self.ref.checkzone_documented
                or label_names_zone(zone_raw, glob, self.ref.zone_names.get(glob))
            ):
                return glob
            mapped = self.ref.plant_zone_map.get((plant, model, key))
            if mapped in codes:
                return mapped
            named = self.canonical_name_resolves(plant, model, zone_raw)
            if named is not None:
                return named
            # RO17 (D-RO17-3): the plant's own label, last, so nothing that
            # resolves today changes; only onto this list's gold.
            labelled = self.ref.plant_ws_label.get((plant, model, key))
            return labelled if labelled in codes else None
        mapped = self.ref.plant_zone_map.get((plant, model, key))
        if mapped is not None:
            return mapped
        exact = key.upper()
        if (model, exact) in self.ref.model_zone:
            return exact
        glob = self.ref.checkzone.get(key)
        if glob and (
            key in self.ref.checkzone_documented
            or label_names_zone(zone_raw, glob, self.ref.zone_names.get(glob))
        ):
            return glob
        return self.canonical_name_resolves(
            plant, model, zone_raw
        ) or self.ref.plant_ws_label.get((plant, model, key))  # RO17, last

    def canonical_name_resolves(
        self, plant: str, model: str, zone_raw: str
    ) -> str | None:
        """T97 (D-97-1): the one canonical panel this label's name names.

        The exact complement of D-94-1: a name that names **more than one**
        canonical panel is rough and asks (``01HOOD`` -> five hoods), and a
        name that names **exactly one** says the position, so it loads --
        ``12LCPILLAR`` -> ``LCPILLAR``, with no alias row and no question,
        at any plant.

        Guarded as D-96-2 is guarded: only against the model's **own**
        canonical list (`canonical_panels`, ``plant_gold`` INTERSECT
        ``ref_model_zone``), so a pair with no canonical list resolves
        nothing new. Per model, never per plant.

        D-97-3: this runs **last**, after T58's gold label -> global alias ->
        ``ref_plant_zone_map`` order, as a final chance before the hold. An
        approved alias, a taught zone map row and a batch confirmation all
        still win. A rough label never reaches here -- `resolve_checkzone`
        answers it from the confirmations alone (D-94-2).
        """
        named = canonical_named_by(zone_raw, self.canonical_panels(plant, model))
        return named[0] if len(named) == 1 else None

    # ---------------------------------------------------------
    def aggregate_of(self, raw: RawRow) -> Aggregate | None:
        """Is this a report roll-up rather than a measurement? (spec S16)

        Checked **before** anything else, because a `[All]` in the Model
        column would otherwise be quarantined as an unidentified model and a
        `[All]` in Serial No would be a missing required field -- two
        answers that both invite somebody to "fix" a row that was never a
        vehicle.
        """
        found = {
            field_: text
            for field_ in AGGREGATE_IDENTITY_FIELDS
            if (text := raw.text(field_))
            and text.strip().casefold() in AGGREGATE_SENTINELS
        }
        if not found:
            return None
        return Aggregate(
            fields=tuple(sorted(found)),
            values=dict(found),
            plant=self.resolve_plant(raw.text("plant")) or self.expected_plant,
            source_file=raw.source_file,
            source_sheet=raw.source_sheet,
            source_row=raw.source_row,
            raw={
                k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
                for k, v in raw.values.items()
            },
        )

    # ---------------------------------------------------------
    def clean_row(self, raw: RawRow) -> CleanRow | Reject | Unidentified | Aggregate:
        snapshot = out_snapshot(raw)

        # --- report roll-up ----------------------------------------
        rollup = self.aggregate_of(raw)
        if rollup is not None:
            return rollup

        def reject(reason: str, detail: str, column: str | None = None,
                   value: object = None) -> Reject:
            return Reject(
                reason=reason, detail=detail,
                source_file=raw.source_file, source_sheet=raw.source_sheet,
                source_row=raw.source_row, raw=snapshot,
                column=column,
                value=None if value is None else str(value),
            )

        # --- plant -------------------------------------------------
        # A blank cell is the one case ``expected_plant`` answers: the plant
        # page said which plant this workbook belongs to, and a sheet that
        # simply omits the value is filled from it rather than rejected row
        # by row. The fill is recorded on the row.
        plant_raw = raw.text("plant")
        plant_filled = False
        plant_read_as: str | None = None
        if not plant_raw:
            if not self.expected_plant:
                return reject(
                    RejectReason.MISSING_REQUIRED_FIELD, "plant is blank", "plant"
                )
            plant = self.expected_plant
            plant_filled = True
        elif self.expected_plant:
            # T39 / ADR 0013 decision 3. The page named the plant; a cell
            # that agrees (alias, prefix, or an Engineer's confirmation) is
            # that plant, and anything else is held and asked about.
            plant, plant_read_as = self.page_plant_of(plant_raw)
            if plant is None:
                return reject(
                    RejectReason.PLANT_MISMATCH,
                    f"Plant cell {plant_raw!r} does not name "
                    f"{self.expected_plant}, the plant this file was uploaded "
                    f"for. Confirm it is {self.expected_plant}, or upload it on "
                    f"the right plant's page.",
                    "plant", plant_raw,
                )
        else:
            plant = self.resolve_plant(plant_raw)
            if not plant:
                if plant_raw.upper() not in self.allowed_plants:
                    return reject(
                        RejectReason.PLANT_OUT_OF_SCOPE,
                        f"plant {plant_raw!r} is not configured. In scope: "
                        f"{', '.join(sorted(self.allowed_plants))}.",
                        "plant", plant_raw,
                    )
                return reject(RejectReason.UNKNOWN_PLANT,
                              f"no alias for plant {plant_raw!r}", "plant", plant_raw)
            if plant not in self.allowed_plants:
                return reject(
                    RejectReason.PLANT_OUT_OF_SCOPE,
                    f"plant {plant!r} is out of scope. In scope: "
                    f"{', '.join(sorted(self.allowed_plants))}.",
                    "plant", plant_raw,
                )

        # --- date --------------------------------------------------
        if self.no_date_column:
            # RO18 (B4): no date anywhere; the month a person named, or held.
            if self.month_only is None:
                return reject(REASON_MONTH_UNKNOWN, self.month_detail, "date")
            measured_date = self.month_only
        else:
            measured_date, err = parse_date(raw)
            if err:
                return reject(RejectReason.BAD_DATE, err, "date", raw.get("date"))
            # RO15 (D-RO15-1): a date in another month than the row's own
            # Month / Year cells is held; we never choose which is right.
            disagrees = date_disagrees(raw, measured_date)
            if disagrees:
                column, detail = disagrees
                return reject(RejectReason.BAD_DATE, detail, column, raw.get(column))

        # --- serial ------------------------------------------------
        # ADR 0013 decision 2: blank, absent or `(None)` serial loads NULL at
        # every plant. Nothing is generated; the sheet is the vehicle.
        serial = read_serial(raw)

        # --- model (unknown model -> quarantine, not reject) --------
        model_raw = raw.text("model")
        if not model_raw:
            return reject(RejectReason.MISSING_REQUIRED_FIELD, "model is blank", "model")

        if model_raw.casefold() in UNIDENTIFIED_MODELS:
            return Unidentified(
                raw_model=model_raw, plant=plant, serial_no=serial,
                measured_date=measured_date,
                source_file=raw.source_file, source_sheet=raw.source_sheet,
                source_row=raw.source_row, raw=snapshot,
            )

        model = self.plant_first(self.ref.model_by_plant, self.ref.model,
                                 plant, model_raw) or self.offered_model_code(plant, model_raw)
        if not model:
            return reject(RejectReason.UNKNOWN_MODEL,
                          f"model {model_raw!r} is not an alias and not an "
                          f"offered catalogue code at plant {plant!r}. Pick "
                          f"the model from {plant}'s list (a plant-scoped "
                          f"ref_model_alias), never a leftover onto Ranger "
                          f"(T26 S11, T55 D-55-01).",
                          "model", model_raw)
        if model in self.ref.film_only_models:
            # T46 (F5). RAPCAP and Single CAP are FilmThickness catalogue
            # rows. A WaveScan cell that reaches one is held, never loaded
            # and never relabelled Ranger. T115-FIX: its own code, so an
            # Attach never replays it and its sentence is not the Removed one.
            return reject(
                RejectReason.FILM_ONLY_MODEL,
                f"model {model!r} is a FilmThickness-only model "
                f"(wavescan_ok = false). It is not a WaveScan vehicle: not "
                f"this domain.",
                "model",
                model_raw,
            )
        if not self.ref.offered_models.get((plant, model), False):
            return reject(
                RejectReason.MODEL_NOT_OFFERED,
                f"model {model!r} is not on {plant}'s list. It will not "
                f"load here.",
                "model",
                model_raw,
            )

        # --- checkzone ---------------------------------------------
        zone_raw = raw.text("checkzone")
        if not zone_raw:
            return reject(RejectReason.MISSING_REQUIRED_FIELD,
                          "checkzone is blank", "checkzone")

        zone = self.resolve_checkzone(plant, model, zone_raw)
        if not zone and normalise_alias(zone_raw) in self.rough_panels.get(
            model, frozenset()
        ):
            # T94 (D-94-2). Not "we do not know this name" -- we know it and
            # it does not say which panel it is. The worksheet turns this
            # into the highlighted row with the long name pre-filled
            # (D-94-3); the reason stays UNKNOWN_CHECKZONE so every existing
            # held-panel path (PANEL_HOLD_REASONS, the match screen, the
            # per-row picker) keeps working on it unchanged.
            return reject(
                RejectReason.UNKNOWN_CHECKZONE,
                f"panel {zone_raw!r} does not say which panel of {model} at "
                f"{plant} it is: with its leading number dropped the name "
                f"fits more than one position, or another name on this sheet "
                f"reduces to the same name. Confirm which panel it is on the "
                f"row above and it loads under that panel's long name. It is "
                f"never guessed, and a panel spelled like it on the list is "
                f"not an answer (T94, D-94-1, D-94-2).",
                "checkzone", zone_raw,
            )
        if not zone:
            return reject(RejectReason.UNKNOWN_CHECKZONE,
                          f"panel {zone_raw!r} is not on {model}'s panel list "
                          f"at {plant}. Pick the panel it is from that list, "
                          f"or add the panel in the catalogue first. A compact "
                          f"label is never moved onto another plant's panel "
                          f"name without that pick (T53, D-53-09).",
                          "checkzone", zone_raw)

        # T58: a zone from this plant x model's gold is valid by membership;
        # only a pair with no gold list is checked against `ref_model_zone`.
        if (plant, model) not in self.ref.plant_gold and (model, zone) not in self.ref.model_zone:
            return reject(
                RejectReason.ZONE_NOT_VALID_FOR_MODEL,
                f"zone {zone!r} is not a valid position on model {model!r}",
                "checkzone", zone_raw,
            )

        # --- colour ------------------------------------------------
        color_raw = raw.text("color")
        if not color_raw:
            return reject(RejectReason.MISSING_REQUIRED_FIELD, "color is blank", "color")
        color = self.plant_first(self.ref.color_by_plant, self.ref.color,
                                 plant, color_raw)
        if not color:
            color = unique_colour_identity(color_raw, self.ref.known_color_names)
        if not color:
            return reject(RejectReason.UNKNOWN_COLOR,
                          f"colour {color_raw!r} at plant {plant!r} is not "
                          f"an alias and does not uniquely fold onto one "
                          f"catalogue name. Cross-check with the uploader; "
                          f"teach ALIAS_COLOR to an existing ref_color name, "
                          f"or ask the named owner to add a catalogue name. "
                          f"Identity only: this is not a grading family "
                          f"(spec S12, D1/D2 open).",
                          "color", color_raw)
        # T64 (ADR 0014): a merged name is written as its canonical name, so
        # the offered check and the stored fact both see one colour.
        color = fold_colour(color, self.ref.merged_colors)
        if not self.ref.offered_colors.get((plant, color), False):
            return reject(
                RejectReason.COLOR_NOT_OFFERED,
                f"colour {color!r} is not on {plant}'s list. It will not "
                f"load here.",
                "color",
                color_raw,
            )

        # --- paintline ---------------------------------------------
        line_raw = raw.text("paintline")
        paintline: str | None = None
        paintline_omitted_reason: str | None = None
        if line_raw and line_raw.strip().casefold() in MISSING_PAINTLINE_SENTINELS:
            paintline_omitted_reason = PAINTLINE_OMITTED_SENTINEL
            line_raw = None
        if not line_raw:
            # ADR 0013 decision 2: blank or absent booth loads NULL at every
            # plant. A nonblank unknown spelling still holds (below).
            paintline = None
        else:
            paintline = self.ref.paintline.get(normalise_alias(line_raw))
            if not paintline:
                compact = re.sub(r"\s+", "", normalise_alias(line_raw))
                paintline = self.ref.paintline.get(compact)
            if not paintline:
                return reject(RejectReason.UNKNOWN_PAINTLINE,
                              f"paintline {line_raw!r} is not an alias and "
                              f"does not fold onto one booth code. Cross-check "
                              f"with the uploader.",
                              "paintline", line_raw)

        # --- measurements ------------------------------------------
        measures: dict[str, Decimal | None] = {}
        for m in MEASURE_ALL:
            val, err = parse_measure(raw.get(m))
            if err:
                return reject(RejectReason.BAD_NUMBER, f"{m}: {err}", m, raw.get(m))
            measures[m] = val

        # ADR 0013 decision 1: CF always; LW/SW unless an Engineer approved
        # this point's holes. DOI, DU, Wa-We and B are optional.
        missing = [
            m for m in MEASURES_REQUIRED
            if measures[m] is None
            and not (m in MEASURES_HOLE_APPROVABLE and raw.source_row in self.hole_rows)
        ]
        if missing:
            return reject(
                RejectReason.MISSING_MEASUREMENT,
                MISSING_MEASUREMENT_DETAIL + ", ".join(missing),
                missing[0],
            )

        return CleanRow(
            measured_date=measured_date,
            plant=plant, model=model, checkzone=zone, color=color,
            tolerance_group=derive_tolerance(zone),
            paintline=paintline, serial_no=serial,
            measures=measures,
            source_file=raw.source_file, source_sheet=raw.source_sheet,
            source_row=raw.source_row,
            src_zone_text=zone_raw, src_zone_no=extract_position(zone_raw),
            plant_filled=plant_filled,
            paintline_omitted_reason=paintline_omitted_reason,
            plant_read_as=plant_read_as,
            date_is_month_only=self.month_only is not None,
        )

    # ---------------------------------------------------------
    def _car_point(self, raw: RawRow, out) -> tuple[str, str, str | None] | None:
        """RO16: ``(plant, model, resolved checkzone or None)`` of a row with
        no serial, or None when the row has a serial or no model resolves.

        A held row resolves its model and panel exactly as `clean_row` does,
        so a first point held for another fault (a bad number) still starts
        its car.
        """
        if isinstance(out, CleanRow):
            return None if out.serial_no else (out.plant, out.model, out.checkzone)
        if not isinstance(out, Reject) or read_serial(raw):
            return None
        plant = self.expected_plant or self.resolve_plant(raw.text("plant"))
        model_raw = raw.text("model")
        if not plant or not model_raw:
            return None
        model = self.plant_first(
            self.ref.model_by_plant, self.ref.model, plant, model_raw
        ) or self.offered_model_code(plant, model_raw)
        if not model:
            return None
        zone_raw = raw.text("checkzone")
        return plant, model, (
            self.resolve_checkzone(plant, model, zone_raw) if zone_raw else None
        )

    def split_cars(self, rows: list[RawRow], outs: list) -> None:
        """RO16 (D-RO16-1..3). A blank-serial sheet holding several cars.

        Each model's blank-serial rows, in file order, start a new car at
        every row whose checkzone resolves to the first point of the plant's
        live list for that model; a model with no live list is one car, and a
        row with a serial is never split (its serial is the car). With more
        than one car on the sheet, every blank-serial row takes its car's
        `car_fingerprint`, and a car carrying two days or two colours (as
        written) is held. One car changes nothing. ``outs`` is changed in
        place.
        """
        cars: list[list[tuple[int, str]]] = []
        current: dict[tuple[str, str], list[tuple[int, str]]] = {}
        for index, (raw, out) in enumerate(zip(rows, outs)):
            point = self._car_point(raw, out)
            if point is None:
                continue
            plant, model, zone = point
            first = self.ref.ws_first_point.get((plant, model))
            car = current.get((plant, model))
            if car is None or (first is not None and zone == first):
                car = current[(plant, model)] = []
                cars.append(car)
            car.append((index, zone or normalise_alias(raw.text("checkzone") or "")))
        # RO18 (B4): a month-only sheet has no day to tell two same-colour
        # blank-serial cars of that month apart, so even one car takes its
        # walk's fingerprint (RO09 Q2).
        if len(cars) <= 1 and self.month_only is None:
            return
        for number, car in enumerate(cars):
            key = car_fingerprint((zone, rows[i]) for i, zone in car)
            held = self._car_mixed(number, len(cars), [rows[i] for i, _ in car])
            for i, _ in car:
                out = outs[i]
                if held and isinstance(out, CleanRow):
                    column, value, detail = held
                    raw = rows[i]
                    outs[i] = Reject(
                        reason=RejectReason.OTHER, detail=detail,
                        source_file=raw.source_file, source_sheet=raw.source_sheet,
                        source_row=raw.source_row, raw=out_snapshot(raw),
                        column=column, value=value, car_key=key,
                    )
                elif isinstance(out, (CleanRow, Reject)):
                    out.car_key = key

    @staticmethod
    def _car_mixed(number: int, cars: int, rows: list[RawRow]) -> tuple[str, str, str] | None:
        """D-RO16-3: ``(column, second value, sentence)`` when one car carries
        two days, or two colours as written. A blank or unreadable cell is
        that row's own fault (`clean_row` says so), not a second value."""
        days = list(dict.fromkeys(
            day.isoformat() for day, _ in map(parse_date, rows) if day is not None
        ))
        colours = list(dict.fromkeys(
            raw.text("color").strip() for raw in rows if raw.text("color")
        ))
        for column, what, seen in (("date", "date", days), ("color", "colour", colours)):
            if len(seen) > 1:
                return column, seen[1], car_mixed_detail(
                    number, cars, rows[0].source_row, what, seen[0], seen[1]
                )
        return None

    def clean_all(self, rows) -> CleanResult:
        rows = list(rows)
        # T94 (D-94-1): the rough/specific test is over the whole sheet, so
        # it is answered once, here, before the first row is cleaned.
        self.rough_panels = self.rough_panel_labels(rows)
        outs = [self.clean_row(raw) for raw in rows]
        self.split_cars(rows, outs)
        result = CleanResult()
        for out in outs:
            if isinstance(out, CleanRow):
                result.clean.append(out)
            elif isinstance(out, Unidentified):
                result.unidentified.append(out)
            elif isinstance(out, Aggregate):
                result.aggregates.append(out)
            else:
                result.rejects.append(out)
        return result
