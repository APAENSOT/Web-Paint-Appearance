"""FilmThickness: turn a PELT FilmBuild sheet into insert-only layer facts.

T46, spec `2026-09-29-filmthickness-data-design.md` F1-F18. A new domain
package beside WaveScan, not a flag on it (S1): its own header vocabulary
(`ref_column_alias.domain = FILMTHICKNESS`), its own model tokens
(`ref_film_model_alias`), its own point catalogue (`ref_film_point`) and its
own fact table (`filmthickness`). The one thing it shares with WaveScan is
the door: the same upload, the same stored bytes, the same review, the same
commit transaction (S5).

What this module decides, and the rule each decision follows:

* **Which model** (F4-F7). The FTM filename token ``{COLOR}_{TOKEN}_{job}``
  first -- ``RAP`` is RAPCAP and ``RB`` is Raptor there, the opposite of
  WaveScan's ``P703 RAP`` -- then the plant's own spelling in the filename or
  tab name (``P703`` / ``DBL`` -> Ranger). PELT Comments (``RANGER_RAP``) are
  never read for it. A leftover program (J73 / U704 / CX743 / V363) or two
  different answers hold the sheet rather than pick.
* **Which point** (F10-F12). By location **name**, never walk order: an
  owner-proved `ref_film_location_map` row, else the label equal to a
  catalogue point of that model. Anything else is held, not guessed.
* **Extra points** (F11). ``095*``-``098*`` and ``*FTWISH*`` are quarantined,
  never facts.
* **Layers** (F9). One fact per numeric layer cell of ECOAT / PRIMER / BASE /
  CLEAR. Steel and total thickness are read and kept as evidence, never
  facts. A blank layer cell is simply absent -- nothing is invented.
* **Which car** (F13-F14). `logical_vehicle_id` from plant + date + model +
  colour + the real identity (VIN, else Job Number). A blank identity and a
  filled one never share an id; a VIN or serial is never generated.

Pure: no FastAPI, no psycopg. Reference maps are injected (`FilmReference`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePath
from typing import Iterable, Mapping, Sequence

from app.domain.cleaner import Aggregate, Reject, RejectReason, month_word, parse_measure
from app.domain.film_header import (
    DOMAIN_FILMTHICKNESS,
    LAYER_CODES,
    LAYER_FIELDS,
    NON_FACT_FIELDS,
    SHEET_FILMTHICKNESS,
    classify_film,
    colour_meta,
    layer_block_base_header,
    parse_pelt_meta,
)
from app.domain.color_identity import fold_colour, merged_sources, unique_colour_identity
from app.domain.leftover_models import leftover_program_prefix
from app.domain.reader import RawRow
from app.domain.references import normalise_alias

#: Rows under a Location header that are specification limits, not points
#: (AAT August / STD tabs). Preserved as roll-up evidence, never facts, the
#: same way T26 treats ``[All]``. Compared after `normalise_location`.
LIMIT_ROW_LABELS = frozenset({
    "FAIL HIGH", "FAIL LOW", "WARNING HIGH", "WARNING LOW", "MATCH TO STANDARD",
})

#: Identity text that means "no identity" (F14: FVL writes VIN 0).
PLACEHOLDER_IDENTITIES = frozenset({"", "0", "0.0", "none", "(none)", "n/a", "na", "-"})

#: Review reasons for film rows held back. Stable tokens, like the cleaner's.
REASON_EXTRA_POINT = "EXTRA_POINT"
REASON_UNMAPPED_POINT = "UNMAPPED_POINT"
REASON_FILM_MODEL_UNRESOLVED = "FILM_MODEL_UNRESOLVED"
REASON_LIMIT_ROW = "STANDARD_LIMIT_ROW"
#: T99. The sheet-wide holds and the never-stored tail (`domain/film_walk.py`
#: owns the rules; the tokens live here with the rest of the film reasons).
REASON_FILM_WALK_UNKNOWN = "FILM_WALK_UNKNOWN"
REASON_FILM_JOB_UNUSUAL = "FILM_JOB_UNUSUAL"
REASON_FILM_MODEL_CONFLICT = "FILM_MODEL_CONFLICT"
REASON_FILM_TAIL_LABEL = "FILM_TAIL_LABEL"
#: RO18 (B5). A label somebody answered "Not a point of this list" for: kept,
#: never loaded, never a hold -- read exactly like a tail label.
REASON_FILM_NOT_A_POINT = "FILM_NOT_A_POINT"
REASON_FILM_NO_NAMED_POINTS = "FILM_NO_NAMED_POINTS"
#: T109 (D-109-6). A label the plant x model's live list does not hold, on a
#: plant x model that has a setting. It is a question asked **in the row** --
#: which live point is this? -- not a hold of the sheet and not the old
#: "ask an Admin" of `UNMAPPED_POINT`.
REASON_FILM_POINT_UNKNOWN = "FILM_POINT_UNKNOWN"
#: T109-FIX (D-109F-1). A row whose label **did** resolve, on a sheet that
#: still has an unanswered label somewhere else. The row is fine; the sheet is
#: not finished being read, so it waits with every other row of it. One
#: reason token rather than silence, because a reviewer has to be able to see
#: why a row that looks right is not loading.
REASON_FILM_POINT_WAITING = "FILM_POINT_WAITING"

#: T109-FIX (D-109F-3). Said wherever a label question is said. A walk whose
#: points shifted down writes the list's own names for the **next** spot on
#: the truck, so mapping those labels files every later reading one point out;
#: the only right answer is the file, not an alias.
RENUMBER_ADVICE = (
    "If the walk was renumbered -- a point was taken out and the rest shifted "
    "down -- do not map these labels: fix the file and upload it again."
)

_WALK_INDEX = re.compile(r"^\s*\d+\s*\)\s*")
_SPACES = re.compile(r"\s+")
_EXTRA = re.compile(r"^09[5-8]")
_FTM_NAME = re.compile(r"^([A-Za-z0-9]+)_([A-Za-z]+)_(.+)$")
_WORDS = re.compile(r"[^A-Za-z0-9]+")
_PELT_DATE_FORMATS = (
    "%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d",
    # RO18 (B2): day first, like the two above (SAP writes ``19-09-2026``).
    "%d-%m-%Y",
)
#: RO18 (B2). Day-first with the month as a word: SAP writes ``19-Sept-26``.
_DAY_MONTH_WORD = re.compile(r"^(\d{1,2})-([A-Za-z]{3,9})-(\d{2}|\d{4})$")


# =====================================================================
# location names
# =====================================================================
def normalise_location(text: object) -> str:
    """The map key for a raw location (spec 5.4).

    Upper case, spaces collapsed, and an AAT/FTM walk-index prefix such as
    ``1)`` removed, so ``1)001HOOD`` and ``001HOOD`` are one key. The
    three-digit number **stays**: ``001HOOD`` and ``002HOOD`` are two named
    points, and the digits are part of the name, not a walk position.
    """
    value = _SPACES.sub("", str(text or "")).upper()
    return _WALK_INDEX.sub("", value)


def is_extra_point(text: object) -> bool:
    """FTM 095-098 and any FTWISH label (F11).

    Only the *reason* a label that is **not** gold at this plant x model is
    held. Catalogue membership is checked first (T55, D-55-11): AAT U704
    ``095Roof LH`` is gold and never reaches this test.
    """
    key = normalise_location(text)
    return bool(_EXTRA.match(key)) or "FTWISH" in key


def is_limit_row(text: object) -> bool:
    return _SPACES.sub(" ", str(text or "").strip().upper()) in LIMIT_ROW_LABELS


def point_unknown_detail(label: str, *, plant: str, model: str) -> str:
    """T109 (D-109-6). The one sentence the row carrying the label shows.

    It says the two things a person can do and nothing else: name the live
    point this label is -- remembered from then on -- or add it as a new
    point first. It never proposes one: a Film point is its number **and**
    its name (D-99-1), and a guess here would file a reading onto the wrong
    spot of the truck.

    T109-FIX (D-109F-1, D-109F-3): and it says that nothing on the sheet
    loads until every label is answered, with the one piece of advice a
    renumbered walk needs -- mapping its labels would file every later
    reading one point out, so the answer is the file.

    It lives here rather than in `domain/film_walk.py` with the walk's other
    sentences because the cleaner says it, and `film_walk` imports this
    module.
    """
    return (
        f'"{label}" is not a point of {plant}\'s {model} list. Say which live '
        f"point it is and we remember it for every later upload, or add it as "
        f"a new point on Point Check and then re-check this file. Nothing on "
        f"this sheet loads until every label on it is answered. "
        f"{RENUMBER_ADVICE}"
    )


def colour_conflict_warning(
    job_token: str, filename_token: str, *, layer_colour: str
) -> str:
    """T99 (D-99-11). One sentence a loading row carries, never a hold."""
    return (
        f'The Job Number\'s colour code "{job_token}" and the file name\'s '
        f'"{filename_token}" are different. The colour loaded is the one '
        f'Layer 2 names: "{layer_colour}". Nothing is held; this row carries '
        f"the disagreement so it is not found later."
    )


# =====================================================================
# models
# =====================================================================
@dataclass(frozen=True)
class ModelResolution:
    model: str | None
    token: str | None
    source: str
    detail: str


def ftm_filename_token(filename: str) -> str | None:
    """``AW_RB_1939081.xlsx`` -> ``RB`` (spec F6). None when not that shape."""
    m = _FTM_NAME.match(PurePath(filename).stem.strip())
    return m.group(2).upper() if m else None


def ftm_filename_colour_token(filename: str) -> str | None:
    """``AW_RB_1939081.xlsx`` -> ``AW`` (T99, D-99-11). The colour code.

    Never used to decide a colour -- Layer 2 does that, as it always has.
    It exists only so a disagreement with the Job Number's code can be said
    out loud on the row (D-99-11).
    """
    m = _FTM_NAME.match(PurePath(filename).stem.strip())
    return m.group(1).upper() if m else None


def _words(text: str) -> list[str]:
    return [w for w in _WORDS.split(str(text or "").upper()) if w]


def models_in_names(
    plant: str,
    filename: str,
    sheet: str,
    aliases: Mapping[tuple[str, str], str],
) -> dict[str, str]:
    """``{plant token found in the names -> model}`` (step 2 of F4-F8).

    One definition, read by both :func:`resolve_film_model` and
    :func:`film_model_options`, so the resolution and the Engineer's
    candidate list can never drift apart.
    """
    found: dict[str, str] = {}
    plant_tokens = {tok: model for (p, tok), model in aliases.items() if p == plant}
    for text in (PurePath(filename).stem, sheet):
        words = set(_words(text))
        compact = re.sub(r"[^A-Z0-9]", "", str(text or "").upper())
        for tok, model in plant_tokens.items():
            if tok in words or (any(ch.isdigit() for ch in tok) and tok in compact):
                found.setdefault(tok, model)
    return found


def plant_film_vocabulary(
    plant: str, aliases: Mapping[tuple[str, str], str]
) -> tuple[str, ...]:
    """Every FilmThickness model this plant has a list for (D-78-32).

    This is the only set a Film model choice may come from. It is derived
    from `ref_film_model_alias`, never from `ref_plant_model` -- WaveScan
    reads that table and must never resolve RAPCAP (D-FT-08).
    """
    return tuple(sorted({m for (p, _tok), m in aliases.items() if p == plant}))


def examined_tokens(filename: str, sheet: str) -> tuple[str, ...]:
    """The words and run-together spellings `resolve_film_model` looked at.

    D-78-30: a teachable token is the FTM filename token, or one word or
    run-together spelling of the file or tab name -- **derived here**, so the
    client never sends free text. Order is the order they were examined in.
    """
    out: dict[str, None] = {}
    token = ftm_filename_token(filename)
    if token:
        out.setdefault(token, None)
    for text in (PurePath(filename).stem, sheet):
        for word in _words(text):
            out.setdefault(word, None)
        compact = re.sub(r"[^A-Z0-9]", "", str(text or "").upper())
        if compact:
            out.setdefault(compact, None)
    return tuple(out)


@dataclass(frozen=True)
class FilmModelOptions:
    """What the Engineer may pick for a sheet held FILM_MODEL_UNRESOLVED (T61).

    Every field is server-derived. ``choices`` is the plant's Film
    vocabulary with the models the names pointed at first; it is never
    widened by anything the client sends.
    """

    detail: str
    resolution_source: str
    candidates: tuple[str, ...]
    choices: tuple[str, ...]
    teachable_tokens: tuple[str, ...]


def film_model_options(
    plant: str,
    filename: str,
    sheet: str,
    aliases: Mapping[tuple[str, str], str],
) -> FilmModelOptions:
    """Build the T61 pick list for one sheet. Pure; nothing is written.

    When the names gave **two** models the hold is ambiguous, and D-78-30
    says the choice then resolves the sheet only and teaches no alias. That
    is expressed here by offering **no** teachable token, so "raw_token must
    be absent" and "raw_token must be one of the sheet's teachable tokens"
    are one rule, checked in one place.
    """
    resolution = resolve_film_model(plant, filename, sheet, aliases)
    candidates = tuple(sorted(set(models_in_names(plant, filename, sheet, aliases).values())))
    vocabulary = plant_film_vocabulary(plant, aliases)
    choices = candidates + tuple(m for m in vocabulary if m not in candidates)
    tokens = (
        () if resolution.source == "ambiguous"
        else examined_tokens(filename, sheet)
    )
    return FilmModelOptions(
        detail=resolution.detail,
        resolution_source=resolution.source,
        candidates=candidates,
        choices=choices,
        teachable_tokens=tokens,
    )


def resolve_film_model(
    plant: str,
    filename: str,
    sheet: str,
    aliases: Mapping[tuple[str, str], str],
) -> ModelResolution:
    """Which FilmThickness model a sheet is (F4-F8). Never guessed.

    1. The filename token of ``{COLOR}_{TOKEN}_{job}``, looked up for this
       plant in `ref_film_model_alias`. At FTM that is the whole answer;
       PELT Comments are provenance and are never consulted.
    2. Otherwise the plant's own spellings (``P703``, ``DBL``) as words of
       the filename or tab name; a spelling carrying a digit (``P703``) is
       also found inside a run-together SAP name (``7VP703CCC1``).
    3. A leftover program (J73 / U704 / CX743 / V363) in either name loads
       on **its own** catalogue when this plant has a Film alias for that
       word (T55, D-55-09/10: AAT ``U704``, FVL ``CX743`` / ``V363``, SAP
       ``J73``). Without one it still holds the sheet (F8); it is never
       folded onto a P703 catalogue. Two different answers, or none, hold.
    """
    token = ftm_filename_token(filename)
    if token is not None:
        model = aliases.get((plant, token))
        if model:
            return ModelResolution(
                model, token, "filename_token",
                f"filename token {token!r} at {plant} is {model}",
            )

    stem = PurePath(filename).stem
    texts = (stem, sheet)
    for text in texts:
        for word in _words(text):
            if leftover_program_prefix(word) and (plant, word) not in aliases:
                return ModelResolution(
                    None, word, "leftover",
                    f"{word!r} in {text!r} is a leftover program (J73 / "
                    f"U704 / CX743 / V363) with no FilmThickness list at "
                    f"{plant}. It waits; it is not folded onto a P703 "
                    f"catalogue (F8, D-55-09).",
                )

    found = models_in_names(plant, filename, sheet, aliases)
    models = set(found.values())
    if len(models) == 1:
        tok = sorted(found)[0]
        return ModelResolution(
            models.pop(), tok, "name_spelling",
            f"{', '.join(sorted(found))} in the file or tab name at {plant}",
        )
    if len(models) > 1:
        return ModelResolution(
            None, None, "ambiguous",
            f"the file and tab name say {sorted(found)}, which mean "
            f"{sorted(models)}; nothing here picks one",
        )
    return ModelResolution(
        None, token, "none",
        f"neither {filename!r} nor tab {sheet!r} carries a FilmThickness model "
        f"spelling approved for {plant} (ref_film_model_alias)",
    )


# =====================================================================
# identity
# =====================================================================
def real_identity(value: object) -> str | None:
    """A Job Number or VIN that identifies a car, or None (F14).

    ``0`` and blanks are placeholders. Nothing is generated.
    """
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if text.casefold() in PLACEHOLDER_IDENTITIES:
        return None
    return text


def logical_vehicle_id(
    plant: str,
    measured_date: date,
    model: str,
    color: str,
    job_no: str | None,
    serial_no: str | None,
    walk: str | None = None,
) -> str:
    """Which car a set of film facts belongs to (spec section 6).

    Plant, day, model and colour, plus the real identity -- the VIN when
    there is one, else the Job Number (F14: FVL's VIN is ``0``). Cab and Box
    walks with the same four and the same identity, or both blank, share
    one id. One blank and one filled do **not**: that is a conflict, and a
    Cab walk must not be attached to a named job's Box by date and colour
    alone. Two files keep two `load_id`s either way (ADR 0005).

    RO14 (D-RO14-4): ``walk`` is the fingerprint of one car's walk on a sheet
    that holds several cars and names none of them. It enters the hash only
    when there is no VIN and no Job Number, so two cars of one colour on one
    day stay two cars. Left out, every id is exactly what it always was.
    """
    if serial_no:
        identity = f"vin:{serial_no.strip().upper()}"
    elif job_no:
        identity = f"job:{job_no.strip().upper()}"
    elif walk:
        identity = f"walk:{walk}"
    else:
        identity = "blank"
    payload = "|".join(
        (plant, measured_date.isoformat(), model, color, identity)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _day_month_word(text: str) -> date | None:
    """RO18 (B2). ``19-Sept-26``: a full English month name, or the first 3 or
    4 letters of exactly one, in any case. Read only where every format above
    failed, so no date that read before reads differently."""
    found = _DAY_MONTH_WORD.match(text)
    month = month_word(found.group(2)) if found else None
    if month is None:
        return None
    year = int(found.group(3))
    try:
        return date(year + 2000 if year < 100 else year, month, int(found.group(1)))
    except ValueError:
        return None


# =====================================================================
# RO18 (B3): a sheet's date vs the date in its file name
# =====================================================================
#: The owner's value (RO18 B3): further apart than this, the sheet is asked.
FILE_DATE_TOLERANCE_DAYS = 3
REASON_FILM_DATE_DISAGREES = "FILM_DATE_DISAGREES"
_NAME_DATES = (
    re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{4})(?!\d)"),  # 18.09.2026
    re.compile(r"(?<!\d)(\d{2})-(\d{2})-(\d{4})(?!\d)"),  # 18-09-2026
    # 16072026... at the start; SAP runs the next digits on (``160720267VP703``)
    re.compile(r"^(\d{2})(\d{2})(20\d{2})"),
)


def file_name_date(filename: str) -> date | None:
    """The one full date a file name carries, else None (none, or two)."""
    found = set()
    for pattern in _NAME_DATES:
        for match in pattern.finditer(PurePath(str(filename)).stem):
            try:
                found.add(date(int(match.group(3)), int(match.group(2)), int(match.group(1))))
            except ValueError:
                continue  # not a date, so not a claim
    return found.pop() if len(found) == 1 else None


def film_date_question(sheet: date, named: date) -> str:
    return (
        f"Which date is right? The sheet says {sheet:%d %b %Y}; the file name "
        f"says {named:%d %b %Y}. They are more than {FILE_DATE_TOLERANCE_DAYS} "
        f"days apart, so nothing on this sheet loads until somebody says which."
    )


def not_a_point_detail(label: str, *, plant: str, model: str) -> str:
    """RO18 (B5). The sentence of a row answered "Not a point of this list"."""
    return (
        f"\"{label}\" is not a point of {plant}'s {model} list: somebody said so "
        f"in an earlier upload. It is kept with the file and never loaded, and "
        f"it does not stop the rest of the sheet. An Admin can retire that "
        f"answer on the Aliases screen."
    )


def parse_film_date(value: object) -> tuple[date | None, str | None]:
    """A PELT date cell or ``Date:`` value. Never a year from elsewhere."""
    if isinstance(value, datetime):
        found = value.date()
    elif isinstance(value, date):
        found = value
    elif value is None or (isinstance(value, str) and not value.strip()):
        return None, "date is blank"
    else:
        text = str(value).strip()
        found = None
        try:
            found = datetime.fromisoformat(text).date()
        except ValueError:
            for fmt in _PELT_DATE_FORMATS:
                try:
                    found = datetime.strptime(text, fmt).date()
                    break
                except ValueError:
                    continue
        if found is None:
            found = _day_month_word(text)
        if found is None:
            return None, f"unrecognised date format: {text!r}"
    if not (date(2000, 1, 1) <= found <= date(2100, 12, 31)):
        return None, f"date {found.isoformat()} is outside 2000-2100"
    return found, None


# =====================================================================
# reference + results
# =====================================================================
@dataclass(frozen=True)
class FilmReference:
    """What the film reader and cleaner need, loaded once per run."""

    #: normalised header -> logical field, domain FILMTHICKNESS, approved.
    column_alias: Mapping[str, str] = field(default_factory=dict)
    #: (plant_code, raw token upper) -> model_code (`ref_film_model_alias`).
    model_alias: Mapping[tuple[str, str], str] = field(default_factory=dict)
    #: model_code -> {normalised point name -> point_code} (catalogue).
    catalogue: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    #: owner-proved (plant, model, normalised raw) -> point_code.
    location_map: Mapping[tuple[str, str, str], str] = field(default_factory=dict)
    #: model_code -> expected film point count.
    expected_points: Mapping[str, int] = field(default_factory=dict)
    #: T47. (model_code, point_code) -> 'H' / 'V' on the gold catalogue.
    orientation: Mapping[tuple[str, str], str] = field(default_factory=dict)
    #: T54 (D-53-01..05). (plant_code, model_code) -> {normalised name ->
    #: point_code}: that plant's own gold list (`ref_plant_film_point`).
    #: When a plant has a list for the model it is the only catalogue read;
    #: the model-wide `catalogue` above is the fallback for a reference that
    #: carries no plant lists (unit fixtures).
    plant_catalogue: Mapping[tuple[str, str], Mapping[str, str]] = field(
        default_factory=dict
    )
    #: T54. (plant_code, model_code, point_code) -> 'H' / 'V' of that plant's point.
    plant_orientation: Mapping[tuple[str, str, str], str] = field(default_factory=dict)
    #: T99 (D-99-2/4). (plant, model) -> {point_code: (counted, 'H'/'V')} from
    #: the **latest** `film_point_setting` row of each point. Its presence is
    #: also the switch for every T99 rule (D-99-12): a plant x model with no
    #: setting row gets none of them and behaves exactly as it did before.
    point_setting: Mapping[tuple[str, str], Mapping[str, tuple[bool, str]]] = field(
        default_factory=dict
    )
    #: T99 (D-99-6). (plant, model) -> normalised labels that are the known
    #: tail of that walk: never a fact, never a hold.
    tail_labels: Mapping[tuple[str, str], frozenset[str]] = field(default_factory=dict)
    #: T99 (D-99-8). (plant, model) -> point codes a **complete** walk may end at.
    complete_stops: Mapping[tuple[str, str], frozenset[str]] = field(
        default_factory=dict
    )
    #: T99 (D-99-7). (plant, model) -> the live list in `point_no` order.
    walk: Mapping[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    #: T99 (D-99-10). plant -> the Job Number regex; absent means no check.
    job_pattern: Mapping[str, str] = field(default_factory=dict)
    #: T109 (D-109-6/8). Live ``(plant, model, normalised raw) -> point_code``
    #: from `ref_film_point_alias`: a label somebody said is a live point of
    #: this plant's list. Read **before** `location_map`, whose FTM rows are
    #: all retired and whose key cannot hold a live FTM answer.
    point_alias: Mapping[tuple[str, str, str], str] = field(default_factory=dict)
    #: T109 (D-109-3). (plant, model) -> point codes beyond the plant's
    #: standard list. A tag, never a rule: nothing resolves or refuses on it.
    extra_points: Mapping[tuple[str, str], frozenset[str]] = field(
        default_factory=dict
    )
    #: RO17 (D-RO17-3). ``(plant, model, normalised label) -> point_code`` for
    #: every unretired label row, current and earlier, of a **live** point
    #: (`ref_plant_film_point_label`). Read **last** in `resolve_point`, so
    #: every result that resolved before stays exactly what it was.
    point_label: Mapping[tuple[str, str, str], str] = field(default_factory=dict)
    #: RO18 (B5). (plant, model) -> the labels of ``tail_labels`` that are an
    #: uploader's "Not a point of this list" answer rather than the walk's tail.
    not_a_point: Mapping[tuple[str, str], frozenset[str]] = field(default_factory=dict)

    def is_extra(self, plant: str, model: str | None, point: str) -> bool:
        """T109 (D-109-3). Is this point beyond the plant's standard list?"""
        return bool(model) and point in self.extra_points.get(
            (plant, str(model)), ()
        )

    def gold_for(self, plant: str, model: str) -> Mapping[str, str]:
        """{normalised name -> point_code} a plant's walk of a model may name."""
        found = self.plant_catalogue.get((plant, model))
        if found is not None:
            return found
        return self.catalogue.get(model, {})

    def orientation_of(self, plant: str, model: str, point: str) -> str | None:
        # T99 (D-99-2): where a setting exists it is the answer -- it is what
        # a person last said about this point, and the catalogue column is
        # what the seed said about it first.
        setting = self.point_setting.get((plant, model), {}).get(point)
        if setting is not None:
            return setting[1]
        return self.plant_orientation.get((plant, model, point)) or self.orientation.get(
            (model, point)
        )

    def has_setting(self, plant: str, model: str | None) -> bool:
        """T99 (D-99-12). Do the T99 rules apply to this plant x model?"""
        return bool(model) and (plant, model) in self.point_setting

    def plant_has_setting(self, plant: str) -> bool:
        """T99 (D-99-12). The two sheet-wide rules apply per **plant**."""
        return any(key[0] == plant for key in self.point_setting)

    def is_tail_label(self, plant: str, model: str, label: str) -> bool:
        """T99 (D-99-6). Is this label the known tail of that walk?"""
        return normalise_location(label) in self.tail_labels.get((plant, model), ())

    def resolve_point(self, plant: str, model: str | None, label: str) -> str | None:
        """T109. The live point one label names, by the one order of proof.

        A remembered row answers before a name does -- the T109 alias store
        first (D-109-8), then the owner-proved `ref_film_location_map` -- and
        an exact name on the plant's own live list answers last. That is
        `FilmCleaner._point`'s order, as one method, so the ingest and the
        review's walk guard can never read it two ways.
        """
        key = normalise_location(label)
        on = str(model or "")
        return (
            self.point_alias.get((plant, on, key))
            or self.location_map.get((plant, on, key))
            or self.gold_for(plant, on).get(key)
            # RO17 (D-RO17-3): the plant's own word for a point, last.
            or self.point_label.get((plant, on, key))
        )


@dataclass
class FilmRow:
    """One source row that becomes one fact per numeric layer."""

    measured_date: date
    plant: str
    model: str
    color: str
    job_no: str | None
    serial_no: str | None
    point_code: str
    src_location_text: str
    logical_vehicle_id: str
    layers: dict[str, Decimal]
    source_file: str
    source_sheet: str
    source_row: int
    #: T47. ``H`` / ``V`` of the **gold** point after the map; never from
    #: the plant label. None for a catalogue with no orientation yet.
    orientation: str | None = None
    #: T99 (D-99-11). One sentence when the Job Number's colour code and the
    #: file name's disagree. The row still loads on the Layer 2 colour; this
    #: is carried so nobody has to find the disagreement later.
    warning: str | None = None
    #: RO14 (D-RO14-4). The walk fingerprint in ``logical_vehicle_id``, when
    #: one was used, so a merged colour's id is re-derived the same way.
    walk_key: str | None = None
    #: RO18 (B4). The sheet had no date: the 1st of the month a person named.
    date_is_month_only: bool = False


@dataclass
class FilmHold:
    """A row kept out of the facts for review (quarantine disposition)."""

    reason: str
    detail: str
    location: str | None
    source_file: str
    source_sheet: str
    source_row: int
    raw: dict


@dataclass
class FilmDuplicate:
    row: FilmRow
    detail: str


@dataclass
class FilmCleanResult:
    clean: list[FilmRow] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)
    held: list[FilmHold] = field(default_factory=list)
    aggregates: list[Aggregate] = field(default_factory=list)


def _snapshot(raw: RawRow) -> dict:
    return {
        k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
        for k, v in raw.values.items()
    }


class FilmCleaner:
    """RawRow in, film row / reject / held row / limit row out.

    One instance per sheet: the model, the PELT preamble and the plant are
    properties of the sheet, not of a row.
    """

    def __init__(
        self,
        ref: FilmReference,
        *,
        plant: str,
        model: ModelResolution,
        meta: Mapping[str, object],
        color_by_plant: Mapping[tuple[str, str], str],
        color: Mapping[str, str],
        known_color_names: Sequence[str],
        offered_colors: Mapping[tuple[str, str], bool],
        offered_models: Mapping[tuple[str, str], bool],
        merged_colors: Mapping[str, str] | None = None,
        sheet_hold: tuple[str, str] | None = None,
        sheet_waiting: tuple[str, str] | None = None,
        colour_tokens: tuple[str, str] | None = None,
        walk_keys: Mapping[int, str] | None = None,
        date_override: date | None = None,
        month_only: bool = False,
    ) -> None:
        self.ref = ref
        #: RO18. The date every row takes instead of its own: the file name's
        #: (B3, a person chose it) or the 1st of a named month (B4).
        self.date_override = date_override
        self.month_only = month_only and date_override is not None
        self.plant = plant
        self.model = model
        self.meta = dict(meta)
        self.color_by_plant = color_by_plant
        self.color = color
        self.known_color_names = tuple(known_color_names)
        #: T78 (D-78-20). ``(plant_code, color_name) -> is_offered``, from
        #: ``ref_plant_color``. Required, not defaulted: an empty mapping
        #: means "this plant offers nothing", and a default would silently
        #: turn the gate into a pass -- the shape of defect AGENTS.md
        #: section 4 lists. Every caller states the offer list it means.
        self.offered_colors = offered_colors
        #: T112-FIX (D-112F-2). ``(plant_code, model_code) -> is_offered``, from
        #: ``ref_plant_model`` -- the same map WaveScan gates on. Required for
        #: the same reason as ``offered_colors``.
        self.offered_models = offered_models
        self.merged_colors = dict(merged_colors or {})
        #: T99 (D-99-7 / D-99-10 / D-99-11). ``(reason, one sentence)`` when
        #: something about the **sheet** -- its walk, its Job Number, the two
        #: models it names -- is not what we know. Every body row is held
        #: with it and nothing from the sheet loads. The tail labels of
        #: D-99-6 are checked first, because a file is never blocked by the
        #: one thing we already know about it.
        self.sheet_hold = sheet_hold
        #: T109-FIX (D-109F-1). ``(reason, one sentence)`` when some **other**
        #: row of this sheet writes a label the live list does not hold. A row
        #: whose own label resolved is still not loaded: a sheet with an
        #: unanswered label is a sheet nobody has finished reading, and the
        #: one shape that proves why is a walk renumbered down -- its labels
        #: are all live names, one spot out, so loading "the rest" files
        #: readings onto the wrong points of the truck. Checked **after** the
        #: label resolves, so the unanswered label keeps its own question
        #: (D-109F-1) and the answer is still in its row.
        self.sheet_waiting = sheet_waiting
        #: T99 (D-99-11). ``(Job Number colour code, file name colour code)``
        #: when the two disagree. A warning on the row, never a hold.
        self.colour_tokens = colour_tokens
        #: RO14 (D-RO14-4). ``{source_row: walk fingerprint}`` for a sheet of
        #: several cars; empty for a sheet of one, which keeps today's ids.
        self.walk_keys = dict(walk_keys or {})

    # -----------------------------------------------------------------
    def _point(self, location: str) -> str | None:
        """A remembered answer first, then the exact name on this plant's own
        gold list (T54).

        Map first on purpose: a plant may write a gold spelling that means a
        different gold point (SAP ``036LBOXSIDE`` is proved to be gold
        ``039LBOXSIDE``). The plant-scoped proof is the more specific
        statement; an exact name only speaks when no proof exists. Retired
        maps (FTM's T47 rows onto FVL names) never reach this reference, so
        an FTM label is FTM gold by name or it is asked about (D-109-6).

        T109: the alias a person wrote in the review row answers before the
        owner-proved `ref_film_location_map` row does, and both answer before
        a name. `FilmReference.resolve_point` is that one order, so the walk
        guard asks the same question the same way.
        """
        return self.ref.resolve_point(self.plant, self.model.model, location)

    def _colour(self, raw: str) -> str | None:
        key = normalise_alias(raw)
        found = self.color_by_plant.get((self.plant, key)) or self.color.get(key)
        found = found or unique_colour_identity(raw, self.known_color_names)
        # T64 (ADR 0014): a merged name is stored as its canonical name.
        return fold_colour(found, self.merged_colors)

    # -----------------------------------------------------------------
    def clean_row(self, raw: RawRow) -> FilmRow | Reject | FilmHold | Aggregate:
        snapshot = _snapshot(raw)

        def reject(reason: str, detail: str, column: str | None = None,
                   value: object = None) -> Reject:
            return Reject(
                reason=reason, detail=detail,
                source_file=raw.source_file, source_sheet=raw.source_sheet,
                source_row=raw.source_row, raw=snapshot, column=column,
                value=None if value is None else str(value),
            )

        def hold(reason: str, detail: str, location: str | None) -> FilmHold:
            return FilmHold(
                reason=reason, detail=detail, location=location,
                source_file=raw.source_file, source_sheet=raw.source_sheet,
                source_row=raw.source_row, raw=snapshot,
            )

        location = raw.text("location")
        if location and is_limit_row(location):
            return Aggregate(
                fields=("location",), values={"location": location},
                plant=self.plant, source_file=raw.source_file,
                source_sheet=raw.source_sheet, source_row=raw.source_row,
                raw=snapshot,
            )
        if not location:
            return reject(
                RejectReason.MISSING_REQUIRED_FIELD,
                "location is blank, so this row names no point. It is kept "
                "for review and is not a fact.",
                "location",
            )
        if self.model.model is None:
            return hold(REASON_FILM_MODEL_UNRESOLVED, self.model.detail, location)

        # --- T99 (D-99-6): the known tail of the walk ------------------
        # Checked before the sheet hold on purpose: FTWISH and BOOTH_1 are
        # the thing we already know about an FTM file, so they are never a
        # hold and never a reason anything stops loading.
        if self.ref.is_tail_label(self.plant, self.model.model, location):
            return Aggregate(
                fields=("location",), values={"location": location},
                plant=self.plant, source_file=raw.source_file,
                source_sheet=raw.source_sheet, source_row=raw.source_row,
                raw=snapshot,
                reason=(
                    REASON_FILM_NOT_A_POINT
                    if normalise_location(location)
                    in self.ref.not_a_point.get((self.plant, self.model.model), ())
                    else REASON_FILM_TAIL_LABEL
                ),
            )

        # --- T112-FIX (D-112F-1 / D-112F-2): the model offer ------------
        # The model has resolved through the plant's Film vocabulary; now it
        # has to be on the plant's list. "Remove from <plant>" takes it off
        # for new Wave Scan **and** Film files, so a removed model's sheet is
        # refused row by row here with WaveScan's reason code and sentence
        # (`domain/cleaner.py`) -- the same question to the same Engineer.
        # This **reverses D-78-21** ("there is no Film model offer gate").
        # After the tail labels, which are never a reason anything stops.
        if not self.offered_models.get((self.plant, self.model.model), False):
            return reject(
                RejectReason.MODEL_NOT_OFFERED,
                f"model {self.model.model!r} is not on {self.plant}'s list. It "
                f"will not load here.",
                "model", self.model.model,
            )

        # --- T99 (D-99-7 / D-99-10 / D-99-11): the sheet is held ------
        if self.sheet_hold is not None:
            return hold(self.sheet_hold[0], self.sheet_hold[1], location)

        # --- point: the one allow-list (T47, D-FT-12..16) ---------------
        # A proved map or an exact catalogue name makes a fact; nothing
        # else does. `is_extra_point` only *names* why an unresolved label
        # is held -- it never vetoes gold. T55 (D-55-11): membership wins,
        # so AAT U704 `095Roof LH` is gold while FTM `095*` stays an extra
        # where it is not on that plant x model list. Walk order is never
        # consulted.
        point = self._point(location)
        if point is None:
            # T109 (D-109-6): where the plant x model has a setting, a label
            # the live list does not hold is a **question in the row** --
            # which live point is this? -- and the answer is remembered. It
            # is not "ask an Admin to add it to the catalogue" (the
            # UNMAPPED_POINT sentence below), because since T99 the plant's
            # own list is the catalogue and the uploader may change it.
            # Every other plant keeps the two older reasons exactly
            # (D-99-12).
            if self.ref.has_setting(self.plant, self.model.model):
                return hold(
                    REASON_FILM_POINT_UNKNOWN,
                    point_unknown_detail(
                        location, plant=self.plant, model=self.model.model,
                    ),
                    location,
                )
            if is_extra_point(location):
                return hold(
                    REASON_EXTRA_POINT,
                    f"{location!r} is an extra point (095-098 or FTWISH) with "
                    f"no proved map onto a gold point. It is held, not loaded.",
                    location,
                )
            return hold(
                REASON_UNMAPPED_POINT,
                f"{location!r} is not a named point of {self.plant}'s "
                f"{self.model.model} list and no owner-proved location map "
                f"says which point it is. It is held rather than matched by "
                f"walk order or by another plant's names (F10, D-53-02).",
                location,
            )

        # --- T109-FIX (D-109F-1): another row has an unanswered label ---
        # This row's label resolved, so it is not asked about -- it waits,
        # with every other row of the sheet, until every label is answered.
        if self.sheet_waiting is not None:
            return hold(self.sheet_waiting[0], self.sheet_waiting[1], location)

        # --- layers: numeric cells only, nothing invented -------------
        layers: dict[str, Decimal] = {}
        for field_name, code in LAYER_FIELDS.items():
            if field_name not in raw.values:
                continue
            value, err = parse_measure(raw.get(field_name))
            if err:
                return reject(RejectReason.BAD_NUMBER, f"{field_name}: {err}",
                              field_name, raw.get(field_name))
            if value is None:
                continue
            if value < 0:
                return reject(RejectReason.OUT_OF_RANGE,
                              f"{field_name}: {value} is negative",
                              field_name, value)
            layers[code] = value
        if not layers:
            return reject(
                RejectReason.MISSING_MEASUREMENT,
                f"{location!r} has no numeric paint-layer thickness",
                "location", location,
            )

        # --- day -------------------------------------------------------
        date_raw = raw.get("date") if "date" in raw.values else self.meta.get("date")
        measured, err = (
            (self.date_override, None) if self.date_override is not None
            else parse_film_date(date_raw)
        )
        if err:
            reason = (
                RejectReason.MISSING_REQUIRED_FIELD if date_raw in (None, "")
                else RejectReason.BAD_DATE
            )
            return reject(reason, err, "date", date_raw)

        # --- colour ----------------------------------------------------
        colour_raw = raw.text("color") if "color" in raw.values else None
        if colour_raw is None and "color" not in raw.values:
            # PELT `Layer 2:`, else the AAT EC1 banner swatch (T56, D-56-03).
            named = colour_meta(self.meta)
            colour_raw = str(named).strip() if named is not None else None
        if not colour_raw:
            return reject(RejectReason.MISSING_REQUIRED_FIELD, "colour is blank",
                          "color")
        colour = self._colour(colour_raw)
        if not colour:
            return reject(
                RejectReason.UNKNOWN_COLOR,
                f"colour {colour_raw!r} at plant {self.plant!r} is not an "
                f"alias and does not uniquely fold onto one catalogue name.",
                "color", colour_raw,
            )
        # T78 (D-78-20): the colour has resolved and folded (T64); now it has
        # to be a colour this plant actually paints. Same reason code, same
        # message and so the same held-label copy as WaveScan
        # (`domain/cleaner.py`), because it is the same question to the same
        # Engineer. The *model* offer is asked earlier, once the model has
        # resolved (T112-FIX, D-112F-2, reversing D-78-21).
        if not self.offered_colors.get((self.plant, colour), False):
            return reject(
                RejectReason.COLOR_NOT_OFFERED,
                f"colour {colour!r} is not on {self.plant}'s list. It will "
                f"not load here.",
                "color", colour_raw,
            )

        # --- identity (F14) -------------------------------------------
        job = real_identity(
            raw.get("job") if "job" in raw.values else self.meta.get("job number")
        )
        vin = real_identity(
            raw.get("vin") if "vin" in raw.values else self.meta.get("vin")
        )
        # RO14 (D-RO14-4): only a car with no number takes its walk's print.
        walk = None if job or vin else self.walk_keys.get(raw.source_row)
        return FilmRow(
            measured_date=measured, plant=self.plant, model=self.model.model,
            color=colour, job_no=job, serial_no=vin, point_code=point,
            src_location_text=location,
            logical_vehicle_id=logical_vehicle_id(
                self.plant, measured, self.model.model, colour, job, vin, walk
            ),
            walk_key=walk,
            date_is_month_only=self.month_only,
            layers=layers, source_file=raw.source_file,
            source_sheet=raw.source_sheet, source_row=raw.source_row,
            orientation=self.ref.orientation_of(self.plant, self.model.model, point),
            warning=(
                colour_conflict_warning(
                    self.colour_tokens[0], self.colour_tokens[1],
                    layer_colour=colour,
                ) if self.colour_tokens else None
            ),
        )

    def clean_all(self, rows: Iterable[RawRow]) -> FilmCleanResult:
        result = FilmCleanResult()
        for raw in rows:
            out = self.clean_row(raw)
            if isinstance(out, FilmRow):
                result.clean.append(out)
            elif isinstance(out, FilmHold):
                result.held.append(out)
            elif isinstance(out, Aggregate):
                result.aggregates.append(out)
            else:
                result.rejects.append(out)
        return result


def stored_vehicle_ids(row: FilmRow, merged: Mapping[str, str]) -> tuple[str, ...]:
    """The ``logical_vehicle_id`` values this car may be stored under (T64).

    The id hashes the colour. A car stored before a merge hashes its old
    name; the same car uploaded again hashes the canonical name. Both are one
    car, so the duplicate check looks for every id the merge folds together.
    """
    ids = [row.logical_vehicle_id]
    for old in merged_sources(row.color, merged):
        ids.append(logical_vehicle_id(
            row.plant, row.measured_date, row.model, old, row.job_no, row.serial_no,
            row.walk_key,
        ))
    return tuple(ids)


def fold_existing(
    rows: Sequence[FilmRow],
    existing: Mapping[tuple[str, str], int],
    merged: Mapping[str, str],
) -> dict[tuple[str, str], int]:
    """``existing`` re-keyed on each row's own id when it was stored under a
    merged name's id, so ``split_duplicates`` compares folded colours."""
    out = dict(existing)
    for row in rows:
        for vid in stored_vehicle_ids(row, merged)[1:]:
            load = existing.get((vid, row.point_code))
            if load is not None:
                out.setdefault((row.logical_vehicle_id, row.point_code), load)
    return out


def split_duplicates(
    rows: Sequence[FilmRow],
    existing: Mapping[tuple[str, str], int],
) -> tuple[list[FilmRow], list[FilmDuplicate]]:
    """Keep the first reading of a (car, point); hold any repeat.

    ``existing`` is ``(logical_vehicle_id, point_code) -> load_id`` for
    active facts already committed. A repeat is disclosed as a duplicate
    and needs an acknowledgement; nothing already stored changes.
    """
    keep: list[FilmRow] = []
    dups: list[FilmDuplicate] = []
    seen: dict[tuple[str, str], int] = {}
    for row in sorted(rows, key=lambda r: r.source_row):
        key = (row.logical_vehicle_id, row.point_code)
        if key in existing:
            dups.append(FilmDuplicate(
                row, f"point {row.point_code} of this car is already a fact "
                     f"of load {existing[key]}",
            ))
        elif key in seen:
            dups.append(FilmDuplicate(
                row, f"point {row.point_code} was already read at row "
                     f"{seen[key]} of this sheet",
            ))
        else:
            seen[key] = row.source_row
            keep.append(row)
    return keep, dups


__all__ = [
    "DOMAIN_FILMTHICKNESS", "SHEET_FILMTHICKNESS", "LAYER_FIELDS", "LAYER_CODES",
    "NON_FACT_FIELDS", "FilmReference", "FilmRow", "FilmHold", "FilmDuplicate",
    "FilmCleanResult", "FilmCleaner", "ModelResolution", "classify_film",
    "normalise_location", "is_extra_point", "is_limit_row", "parse_pelt_meta",
    "layer_block_base_header", "ftm_filename_token", "resolve_film_model",
    "real_identity", "logical_vehicle_id", "parse_film_date", "split_duplicates",
    "stored_vehicle_ids", "fold_existing", "point_unknown_detail", "not_a_point_detail",
    "file_name_date", "film_date_question", "FILE_DATE_TOLERANCE_DAYS",
]
