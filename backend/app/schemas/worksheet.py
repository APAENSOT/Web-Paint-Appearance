"""T39 worksheet DTOs: one confirm page for one uploaded workbook (ADR 0013).

The Engineer who uploaded the file reads this checklist in plain words and
answers it: ignore a column we do not use, say whether the Plant text is this
plant, approve points with no LW/SW, then "Yes, load these rows". Every
`operator_message` is a sentence for that person; tokens are for clients.

No grading and no pass rate (D1). Extra keys 422 (StrictModel).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import StrictModel
from app.schemas.filmthickness import FilmBox
from app.schemas.ingest import HeldLabelGroup

SheetState = Literal[
    "ready", "loaded", "needs_answer", "blocked", "processing", "not_wavescan",
]


class ShortVehicle(StrictModel):
    """A vehicle set with fewer panels than its model expects (D-17)."""

    measured_date: date | None
    model: str | None
    color: str | None
    point_count: int
    expected_point_count: int
    operator_message: str


RowOutcome = Literal[
    "ready", "held_out", "already_in_history", "needs_confirmation",
]

class WorksheetRowOut(StrictModel):
    """T53: one row of the uploaded workbook, as the confirm table shows it.

    Read from the stored review projection (no workbook is opened). The
    file's own words sit beside the catalogue name they resolved to, so the
    uploader sees what they wrote. There is no CF or thickness field to edit
    here, on purpose (ADR 0005).
    """

    source_sheet: str
    source_row: int
    panel_label: str | None = Field(
        description=(
            "The panel exactly as the file wrote it (e.g. 01HOOD). This is "
            "the plant's own checkpoint name; show it as-is. T54: on a "
            "FilmThickness tab it is the Location cell (e.g. 021LAPILLAR)."
        )
    )
    checkzone: str | None = Field(
        description=(
            "The catalogue identity it resolved to. WaveScan: the zone_code -- "
            "since T58 that plant x model's own gold name (FVL `11ROOF`, SAP "
            "`01RHS Hood Rr28`) or the AAT/FTM long-form code (`RRHOOD`). "
            "T54 FilmThickness: the plant's gold point_code (FTM's own 94 "
            "names, never another plant's). Null when the row is held."
        )
    )
    model_text: str | None = Field(
        description=(
            "Model as the file wrote it. Null on a FilmThickness tab: its "
            "model comes from the file name (DBL / RB / RAP / SGL)."
        )
    )
    model: str | None = Field(description="Catalogue model, when already known.")
    color_text: str | None = Field(description="Colour as the file wrote it.")
    color: str | None = Field(description="Catalogue colour, when already known.")
    date_text: str | None = Field(description="Date as the file wrote it.")
    measured_date: date | None = Field(description="Date read, when already known.")
    outcome: RowOutcome = Field(
        description=(
            "ready: added when the uploader approves. held_out: not added; "
            "operator_message says why. already_in_history: this reading is "
            "already in History and is never written twice. "
            "needs_confirmation (T94, D-94-2): this row's panel name does "
            "not say which panel it is, so it is never ready -- not even "
            "when the catalogue holds a panel spelled exactly like it. "
            "Confirm the panel in this row (see rough_panels and POST "
            ".../panel-confirm) and the row becomes ready under the panel's "
            "long name."
        )
    )
    operator_message: str = Field(description="One plain sentence for this row.")
    counted: bool | None = Field(
        default=None,
        description=(
            "T100 (D-100-2). FilmThickness only: whether the latest setting "
            "says this row's point counts towards the dashboard's Hor / Ver. "
            "Show it as a **read-only** tick -- changing a known point "
            "happens on the Standard tab's Points panel, with a reason, "
            "because it rewrites past months. Null on a WaveScan tab, on a "
            "plant x model with no setting, and on a row that names no point."
        ),
    )
    film_tail: bool = Field(
        default=False,
        description=(
            "T100 (D-100-4). True for a row the plant's walk is known to end "
            "with -- FTM 001FTWISH-006FTWISH and BOOTH_1. Show it as **Not "
            "stored**, muted, with no tick: it is never a fact, never a hold, "
            "and never a reason anything needs attention."
        ),
    )
    film_extra: bool | None = Field(
        default=None,
        description=(
            "T109 (D-109-3). FilmThickness only: whether this row's point is "
            "beyond the plant's standard list for the model. Show it as a tag "
            "beside the point. Null on a WaveScan tab, on a plant x model "
            "with no setting, and on a row that resolved to no point."
        ),
    )


class FilmAppendedPoint(StrictModel):
    """T100 (D-100-2): one name an FTM sheet wrote past the end of the walk."""

    point_code: str = Field(
        description="The name exactly as the sheet wrote it, digits and all."
    )
    proposed_orientation: Literal["H", "V"] | None = Field(
        description=(
            "The Hor / Ver this plant x model's **own list** already gives "
            "that panel word -- 099TGATEIN takes what 091-093TGATEIN carry. "
            "Null when the list has no point of that word or its points "
            "disagree: then the person has to choose, and the review asks. "
            "Read off the list, not computed from the name."
        )
    )
    counted: bool = Field(
        description=(
            "What the confirm should default to: a new point of a walk counts "
            "unless someone says otherwise."
        )
    )


class SheetDateQuestion(StrictModel):
    """RO18 (B3 / B4): the one date question a held tab asks, either domain.

    * ``month`` -- the sheet has no date anywhere. Which month were these
      cars measured? ``suggested_month`` is the file name's, a suggestion
      only. ``POST .../month-answer``. Stored on the 1st, "day not recorded".
    * ``date`` -- a Film sheet's date and the one date in its file name are
      more than 3 days apart. ``sheet_date`` / ``file_name_date``.
      ``POST .../film-date-answer`` with ``sheet`` or ``file_name``.
    """

    kind: Literal["month", "date"]
    operator_message: str = Field(description="The sentence the parse wrote. Show it as-is.")
    suggested_month: str | None = Field(
        default=None, description="kind=month: YYYY-MM from the file name, or null."
    )
    sheet_date: date | None = Field(default=None, description="kind=date: what the sheet says.")
    file_name_date: date | None = Field(default=None, description="kind=date: what the file name says.")


class FilmSheetQuestion(StrictModel):
    """T100 (D-100-1, D-100-5): the one question a held Film sheet asks.

    Filled by the server from the same code that decided the hold, so the
    screen never reads meaning out of a sentence. Null for a WaveScan tab and
    for a Film tab with no sheet-wide hold.

    One question per sheet, answered once, not per row:

    * ``walk`` with ``confirmable`` -- the sheet wrote names past the end of
      the list. ``appended`` is those names with the H/V the list proposes.
      ``POST .../film-walk-confirm``.
    * ``walk`` without ``confirmable`` -- the walk inserts, reorders,
      renumbers or repeats a name. ``operator_message`` says which, and there
      is **no button**: it needs an owner decision (D-99-14).
    * ``model`` -- the file name and the Job Number name two different
      models. ``models`` is the two. ``POST .../film-model-answer``.
    * ``job`` -- the Job Number is not this plant's shape. ``job_no`` is it,
      as written. ``POST .../film-job-answer``.
    """

    kind: Literal["walk", "model", "job"]
    operator_message: str = Field(
        description="The sentence the parse itself wrote. Show it as-is."
    )
    model_code: str | None = Field(
        description="The model the sheet is read as, when one is known."
    )
    confirmable: bool = Field(
        description=(
            "kind=walk only: whether the uploader may confirm it. False means "
            "show the sentence and no button."
        )
    )
    appended: list[FilmAppendedPoint] = Field(
        description="kind=walk + confirmable: the new names, in file order."
    )
    models: list[str] = Field(
        description=(
            "kind=model: the two model codes the sheet names -- the Job "
            "Number's first, then the file name's. Empty otherwise."
        )
    )
    job_no: str | None = Field(
        description="kind=job (and kind=model): the Job Number as written."
    )


class FilmUnknownLabel(StrictModel):
    """T109 (D-109-6): one label this Film tab is asking about."""

    raw_location: str = Field(
        description="The Location exactly as the file wrote it."
    )
    rows: int = Field(
        ge=1,
        description=(
            "How many rows of this tab carry the label. The question is "
            "answered once for all of them: a Cab sheet writing one retired "
            "name on four rows is one answer and then four loaded readings."
        ),
    )


class FilmPointChoice(StrictModel):
    """T109 (D-109-6): one live point an answer may name."""

    point_no: int = Field(ge=1, description="ref_plant_film_point.point_no.")
    point_code: str
    orientation: Literal["H", "V"] | None = Field(
        description="Its Hor / Ver, from the latest setting else the list."
    )
    is_extra: bool = Field(
        description=(
            "T109 (D-109-3): this point is beyond the plant's standard list "
            "for the model. A tag on the picker, never a reason to hide it."
        )
    )


class PanelRenameOrientation(StrictModel):
    tolerance_group: str
    count: int = Field(ge=1)


class PanelRenameOut(StrictModel):
    """T89 Part 5 (D-88-7): this tab looks like a renaming of a whole walk.

    Present only when every panel name the file writes for this model is
    held, the file walks as many panels as the model has panels a match can
    point at, and the Horizontal / Vertical split is the same. Then the
    hundreds of held rows are one event, not hundreds of mistakes, and the
    reviewer is sent to the match screen instead of a list of row rejects.

    It names a shape and nothing else: no pair is decided here.
    """

    model_code: str
    file_panel_count: int = Field(ge=1, description="Distinct panel names the file writes.")
    live_panel_count: int = Field(
        ge=1, description="Panels of this model a confirmed match may point at."
    )
    rows_held: int = Field(ge=0, description="Rows held behind those names.")
    orientations: list[PanelRenameOrientation] = Field(
        description="The file's Horizontal / Vertical split, which the model's matches."
    )
    operator_message: str = Field(min_length=1, max_length=600)


class RoughPanelOut(StrictModel):
    """T94 (D-94-1): one panel name of this tab that does not name a panel.

    A label is **rough** when, with its leading number dropped, it names
    more than one canonical panel of its `(plant, model)` -- `01HOOD` names
    five hoods -- or when another label of the same sheet reduces to the
    same name -- `06`/`07`/`08LFFENDER`. Otherwise it is specific and loads
    without being asked about, and does not appear here.

    This is what the highlighted row in the confirm table renders: the long
    name we propose already chosen, the reason in words, and the whole list
    to pick from if the proposal is wrong. Nothing is applied until a person
    confirms it (D-94-6).
    """

    raw_zone_text: str = Field(
        description="The panel name exactly as the file wrote it, e.g. 01HOOD."
    )
    model_code: str = Field(description="The model whose canonical list it is vague against.")
    rows: int = Field(ge=1, description="Rows of this tab that carry this name.")
    proposed_zone_code: str | None = Field(
        description=(
            "The long name we think it is, from T90's structural rules "
            "(group + ordinal, or the walk number). Pre-selected in the row. "
            "Null when no rule applies -- then the person picks from "
            "choosable and nothing is suggested."
        )
    )
    prefilled_zone_code: str | None = Field(
        description=(
            "What was confirmed for this name last time this same walk was "
            "seen at this plant and model (D-90-5). Null on a first sight."
        )
    )
    confirmed_zone_code: str | None = Field(
        description=(
            "The panel a person has already confirmed this name is, on THIS "
            "upload. Null until they do. Set means the rows load under this "
            "long name; it is never written to a reference table, so it "
            "cannot travel to the next upload (D-90-3, D-91-3)."
        )
    )
    fits_canonical: list[str] = Field(
        description=(
            "The canonical panels this name fits with its number dropped. "
            "Two or more is condition (a) of D-94-1 and is the reason shown "
            "to the person: five hoods is five positions and a name for none "
            "of them."
        )
    )
    shares_name_with: list[str] = Field(
        description=(
            "Other names on this sheet that reduce to the same name -- "
            "condition (b) of D-94-1. Empty when only (a) applies."
        )
    )
    rule: str | None = Field(
        description="Which T90 rule proposed it: group_ordinal, walk_number or none."
    )
    attention: Literal["yellow", "red"] = Field(
        description=(
            "T90 (D-90-6). yellow: the rule and the last confirmed set "
            "agree -- looks right, still confirm it. red: needs attention. "
            "There is no green; a person confirms every one of them."
        )
    )
    reason: str = Field(
        description="Why it is that colour, in plain words. Never a token to branch on."
    )
    choosable: list[str] = Field(
        description=(
            "Every panel this name may be confirmed as, suggestions first "
            "(D-89-6: the same list the match screen offers). A panel not on "
            "this list is refused by POST .../panel-confirm."
        )
    )
    extra_choices: list[str] = Field(
        default_factory=list,
        description=(
            "T114 (D-114-5): the panels of choosable that are extra points -- "
            "beyond the plant's standard list, added on Point Check. A tag "
            "for the picker; it refuses nothing."
        ),
    )
    operator_message: str = Field(
        min_length=1, description="One plain sentence for the row itself."
    )


class WorksheetSheetOut(StrictModel):
    load_id: int
    sheet: str
    status: str = Field(description="load_batch.status.")
    state: SheetState = Field(
        description=(
            "ready: Yes loads it now. loaded: its good rows are measurements. "
            "needs_answer: a question below must be answered first. blocked: "
            "waiting on an Admin (template not proved, or unknown layout). "
            "processing: still being read. not_wavescan: an extra tab "
            "(cover, Methods, Color Data, pictures): \"Extra tab kept. Not "
            "loaded.\" Not a broken template."
        )
    )
    commit_blockers: list[str]
    rows_ready: int = Field(description="Rows that load on Yes (PENDING_REVIEW).")
    rows_loaded: int = Field(description="Rows already measurements.")
    rows_held: int = Field(description="Rows that will not load until answered or fixed.")
    rows_already_in_history: int = Field(
        description=(
            "T53: rows whose reading is already in History (an earlier file, "
            "or this tab after it loaded). Never written twice."
        )
    )
    rows_need_confirmation: int = Field(
        default=0,
        description=(
            "T94 (D-94-2): rows whose panel name does not say which panel it "
            "is. They are never ready. Confirm the panel in the row."
        ),
    )
    rows: list[WorksheetRowOut] = Field(
        description=(
            "T53: every data row of this tab in file order, for the confirm "
            "table. Empty for an extra tab or a tab that could not be read."
        )
    )
    extra_columns: list[str] = Field(
        description="Columns we do not use. Ignore them to continue."
    )
    missing_optional: list[str] = Field(
        description=(
            "T42: optional fields this tab has no column for (doi, serial_no, "
            "paintline, du, wa-we, b). A notice, not a refusal: rows load "
            "with those values empty."
        )
    )
    hole_rows: list[int] = Field(
        description=(
            "Source rows with CF but no LW/SW. They load only after the "
            "Engineer approves them (POST .../hole-approval)."
        )
    )
    plant_texts: list[str] = Field(
        description="Plant cells on this sheet that do not name the page plant."
    )
    held: list[HeldLabelGroup]
    panel_rename: list[PanelRenameOut] = Field(
        default_factory=list,
        description=(
            "T89 Part 5 (D-88-7). One entry per model of this tab whose "
            "panel set looks like a renaming of the whole walk. Empty is the "
            "normal answer."
        ),
    )
    rough_panels: list[RoughPanelOut] = Field(
        default_factory=list,
        description=(
            "T94 (D-94-1, D-94-3). One entry per panel name of this tab that "
            "does not say which panel it is, with the long name we propose "
            "already chosen. The confirm table renders each of these IN the "
            "row that carries the name, highlighted, with one click to "
            "accept. Empty is the normal answer for a file whose names name "
            "their panels."
        ),
    )
    film_question: FilmSheetQuestion | None = Field(
        default=None,
        description=(
            "T100 (D-100-1, D-100-5). The one question this Film tab asks "
            "about itself -- its walk, which of two models it is, or its Job "
            "Number -- filled by the server from the code that decided the "
            "hold. Null for a WaveScan tab and for a Film tab with no "
            "sheet-wide hold. The screen renders it; it classifies nothing."
        ),
    )
    date_question: SheetDateQuestion | None = Field(
        default=None,
        description=(
            "RO18 (B3 / B4). Which month (a sheet with no date anywhere, "
            "either domain) or which date (a Film sheet and its file name "
            "disagree by more than 3 days). Null when the tab asks neither."
        ),
    )
    film_box: FilmBox | None = Field(
        default=None,
        description=(
            "T103 (D-103-1): 'box' / 'no_box' for a Film tab whose walk was "
            "read -- the same rule and the same words GET "
            ".../filmthickness/vehicles answers with, so the review and "
            "History cannot disagree. Null for a WaveScan tab, a tab still "
            "held, and a plant x model whose list names no complete stop."
        ),
    )
    film_unknown_labels: list[FilmUnknownLabel] = Field(
        default_factory=list,
        description=(
            "T109 (D-109-6). One entry per label on this Film tab that the "
            "plant's live list for the model does not hold -- a point that "
            "was retired, a spelling this plant has started writing. Each is "
            "asked about in its own row and answered once for every row that "
            "carries it; every other reading on the tab still loads. Empty "
            "for a WaveScan tab and for a Film tab whose labels all resolved."
        ),
    )
    film_point_choices: list[FilmPointChoice] = Field(
        default_factory=list,
        description=(
            "T109 (D-109-6). The live points an answer may name: this "
            "plant's list for the tab's model, in walk order, with each "
            "point's Hor / Ver and extra tag. The same list Point Check "
            "shows. Sent only while the tab has a label to ask about, so a "
            "client never has to filter it, and never invents a candidate."
        ),
    )
    vehicle_count: int
    short_vehicles: list[ShortVehicle]
    operator_message: str


class PlantQuestion(StrictModel):
    page_plant: str
    plant_texts: list[str]
    rows: int
    operator_message: str


class WorksheetOut(StrictModel):
    plant_code: str
    file_hash: str
    source_file: str
    sheets: list[WorksheetSheetOut]
    plant_question: PlantQuestion | None = Field(
        description="Set when the Plant column names something else. Answer it first."
    )
    extra_columns: list[str]
    missing_optional: list[str] = Field(
        description=(
            "T42: optional fields at least one WaveScan tab has no column "
            "for, e.g. [\"doi\"]. Rows still load with those values empty."
        )
    )
    missing_optional_message: str | None = Field(
        description=(
            "Plain sentence for missing_optional, e.g. \"This file has no DOI "
            "column. Rows can still load with DOI empty.\" Null when nothing "
            "optional is missing."
        )
    )
    ready_sheet_count: int
    rows_ready: int
    rows_held: int
    rows_already_in_history: int = Field(
        description="T53: rows already in History across the workbook."
    )
    rows_need_confirmation: int = Field(
        default=0,
        description=(
            "T94: rows across the workbook whose panel name must be "
            "confirmed before they can load."
        ),
    )
    summary_message: str = Field(
        description=(
            "T53: the workbook in one plain sentence, e.g. \"40 readings "
            "ready to add, 2 held out, 31 already in History.\" Uses only "
            "the words ready, held out and already in History."
        )
    )
    checklist: list[str] = Field(
        description="Short plain sentences, in the order to read them."
    )
    load_button_label: Literal["Yes, load these rows"] = "Yes, load these rows"


def _clean_headers(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            raise ValueError("a column name cannot be blank")
        if text not in out:
            out.append(text)
    if not out:
        raise ValueError("name at least one column")
    return out


class IgnoreColumnsCreate(StrictModel):
    headers: list[str] = Field(
        min_length=1,
        max_length=50,
        description=(
            "Column headers to ignore, as the file wrote them. Only a column "
            "we do not use, or one of two columns that mean the same thing, "
            "can be ignored."
        ),
    )
    note: str | None = Field(default=None, max_length=500)

    _headers = field_validator("headers")(_clean_headers)


class PlantAnswerCreate(StrictModel):
    plant_code: str = Field(
        min_length=1,
        max_length=16,
        description=(
            "Which plant this data is from. The page plant continues; any "
            "other plant cancels this upload so it can be sent from that "
            "plant's page."
        ),
    )


class HoleApprovalCreate(StrictModel):
    load_id: int = Field(ge=1)
    source_rows: list[int] = Field(min_length=1, max_length=5000)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("source_rows")
    @classmethod
    def _rows(cls, value: list[int]) -> list[int]:
        if any(v < 1 for v in value):
            raise ValueError("source rows start at 1")
        return sorted(set(value))


class PanelConfirmPair(StrictModel):
    """One answer: this panel name, on this tab, is this canonical panel."""

    raw_zone_text: str = Field(
        min_length=1, max_length=120,
        description="The panel name as the file wrote it, e.g. 01HOOD.",
    )
    zone_code: str = Field(
        min_length=1, max_length=64,
        description=(
            "The canonical panel it is, e.g. RRHOOD. Must be one of that "
            "name's `choosable` panels, or the answer is refused with the "
            "list and nothing is written."
        ),
    )


class PanelConfirmCreate(StrictModel):
    """T94 (D-94-3, D-94-6): confirm which panel one or more rough names are.

    One pair is the single row's Confirm button; several pairs is the one
    click that accepts the pre-filled set. Both leave the same evidence: a
    `worksheet_decision` row per pair, an `audit_event`, and a replay of the
    tab from the stored bytes. The answer is scoped to this upload and is
    never written to a reference table.
    """

    load_id: int = Field(ge=1)
    pairs: list[PanelConfirmPair] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("pairs")
    @classmethod
    def _one_answer_each(cls, value: list[PanelConfirmPair]) -> list[PanelConfirmPair]:
        seen: dict[str, str] = {}
        for pair in value:
            key = pair.raw_zone_text.strip().casefold()
            if key in seen and seen[key] != pair.zone_code.strip():
                raise ValueError(
                    f"{pair.raw_zone_text!r} is named as two different "
                    f"panels. One panel name is one panel."
                )
            seen[key] = pair.zone_code.strip()
        return value


class FilmModelAnswerCreate(StrictModel):
    """T99 (D-99-11): which of the two models this Film sheet is.

    The Job Number's model token and the file name's disagree, so the sheet
    is held whole. The uploader names one, and only a model this plant has a
    Film point list for is accepted (D-78-32).
    """

    load_id: int = Field(ge=1)
    model_code: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class FilmJobAnswerCreate(StrictModel):
    """T99 (D-99-10): load an unusual Job Number as written.

    No value is sent: the only answer is "read it as it stands". Anything
    else -- a corrected number -- would be the platform editing a file's
    identity, which it never does.
    """

    load_id: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class FilmWalkPoint(StrictModel):
    """One name this sheet appended to the walk, with what it is."""

    point_code: str = Field(
        min_length=1, max_length=64,
        description=(
            "The point name exactly as the sheet wrote it. Identity is "
            "number and name (D-99-1), so the digits are part of it."
        ),
    )
    counted: bool = Field(
        default=True,
        description="Whether this point feeds the dashboard's Hor / Ver.",
    )
    orientation: Literal["H", "V"] = Field(
        description=(
            "Horizontal or Vertical. Pre-filled by the rule (Hood, Roof, "
            "Box-floor are H; everything else V); a word the rule does not "
            "know has to be chosen."
        )
    )


class FilmWalkConfirmCreate(StrictModel):
    """T99 (D-99-14): confirm the names appended after the known walk.

    Every appended name must be answered and nothing else may be: a name
    inside the known walk is a renumber, which no confirm can make safe.
    """

    load_id: int = Field(ge=1)
    points: list[FilmWalkPoint] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class FilmPointSettingItem(StrictModel):
    """One live point of a plant x model Film list, with its setting."""

    point_no: int = Field(ge=1, description="ref_plant_film_point.point_no.")
    point_code: str
    label: str = Field(
        description=(
            "RO17 (D-RO17-1): the point's current label -- the word this "
            "plant uses for it. The code where it has no label row."
        )
    )
    counted: bool = Field(
        description="Latest film_point_setting.counted; true where none exists."
    )
    orientation: Literal["H", "V"] | None = Field(
        description="Latest setting's Hor / Ver, else the catalogue's."
    )
    is_complete_stop: bool = Field(
        description=(
            "T99 (D-99-8): a walk that ends exactly here is a complete "
            "vehicle (FTM RAPCAP 059RTFEND, DBL 064RAPILLAR)."
        )
    )
    is_extra: bool = Field(
        default=False,
        description=(
            "T109 (D-109-3): this point is beyond the plant's standard list "
            "for the model -- FTM's 095RBXFLOOR and 096-098TGATEIN on the two "
            "DBL lists, and every point added since. A tag, not a grade: it "
            "changes no reading and refuses nothing."
        ),
    )
    reason: str | None = Field(
        description="Why the latest setting row says what it says."
    )
    changed_by: str | None = Field(
        description=(
            "T115 (D-115-1): app_user.display_name of the person who wrote "
            "it; null for the seed, \"-\" for a user with no name."
        )
    )
    changed_at: datetime | None = Field(
        description="When it was written. Null where no setting row exists."
    )


class FilmPointSettingOut(StrictModel):
    """T99 (D-99-2, D-99-4): the remembered setting of one plant x model."""

    plant_code: str
    model_code: str
    has_setting: bool = Field(
        description=(
            "False where no film_point_setting row exists for this plant x "
            "model: the T99 rules are switched off there and the list behaves "
            "exactly as it did before (D-99-12)."
        )
    )
    items: list[FilmPointSettingItem] = Field(
        description="Every live point of the list, in walk order."
    )
    retired_items: list[FilmRetiredPointItem] = Field(
        default_factory=list,
        description=(
            "T109 (D-109-4). The points this list used to walk, in walk "
            "order, with when each went and why. Read-only, and never part "
            "of the live list: a retired point is not expected on a car, is "
            "not in the walk, and feeds no box. Its readings are still in "
            "History, tagged. Empty where nothing has been retired."
        ),
    )
    tail_labels: list[FilmTailLabelItem] = Field(
        default_factory=list,
        description=(
            "RO17 (D-RO17-12). The known tail of this walk (FTWISH, BOOTH_1): "
            "labels that are never a fact and never a hold. Live and retired; "
            "a retired one is a record only."
        ),
    )


class FilmTailLabelItem(StrictModel):
    """RO17 (D-RO17-12): one tail label of a plant x model Film walk."""

    label_norm: str
    note: str | None
    created_at: datetime
    retired_at: datetime | None
    retired_reason: str | None


class FilmTailLabelCreate(StrictModel):
    """RO17 (D-RO17-12): Admin. A label this walk writes that is no point.

    Rows with it are skipped on upload -- never a fact, never a hold. Refused
    when it names a live point (its readings would vanish). A retired one is
    put back.
    """

    label: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class FilmTailLabelRetireCreate(StrictModel):
    """RO17 (D-RO17-12): Admin. Rows with this label are asked about again."""

    label: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class FilmTailLabelResult(StrictModel):
    label_norm: str
    audit_id: int
    operator_message: str


class FilmPointRestoreCreate(StrictModel):
    """RO17 (D-RO17-9): put a retired point back on the live list.

    Refused when a live point holds its number, or when its code or current
    label now names another point of the list.
    """

    point_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class FilmRetiredPointItem(StrictModel):
    """T109 (D-109-4): one point this plant's list used to walk."""

    point_no: int = Field(ge=1)
    point_code: str
    label: str = Field(
        description=(
            "RO17 (D-RO17-1): the point's current label -- the word this "
            "plant uses for it. The code where it has no label row."
        )
    )
    orientation: Literal["H", "V"] | None = Field(
        description="The Hor / Ver the catalogue row carries. For reading only."
    )
    is_extra: bool = Field(
        description="T109 (D-109-3): it was beyond the plant's standard list."
    )
    retired_at: datetime = Field(description="When it left the walk.")
    retired_reason: str = Field(
        description=(
            "Why, as the person wrote it. This is the whole point of keeping "
            "the row: a reader of History's 'retired point' tag can find out "
            "what happened from here."
        )
    )


class FilmPointSettingCreate(StrictModel):
    """T99 (D-99-4): change which points count, and their Hor / Ver.

    Append-only: every point named here gets a **new** row. The row before it
    is never changed or removed, and the latest row per point is what the
    dashboard reads -- for every month, past ones included. A reason is
    required because that is the thing a later reader needs.
    """

    points: list[FilmWalkPoint] = Field(min_length=1, max_length=400)
    reason: str = Field(min_length=3, max_length=500)


class FilmPointSettingResult(StrictModel):
    rows_written: int
    operator_message: str


class FilmPointAddCreate(StrictModel):
    """T109 (D-109-5): add a point to this plant's list for the model.

    The name is the one a file writes. Its digits are used as point_no when
    free; otherwise a new free number is allocated without moving existing
    identities. Measuring placement is independent (RO19 D-RO19-3).
    The point is extra and counted unless this says otherwise.
    """

    point_code: str = Field(
        min_length=1, max_length=64,
        description=(
            "The point name as a file writes it, digits first ('099TGATEIN'). "
            "Stored upper-case with spaces removed, the way every Location is "
            "compared."
        ),
    )
    place_after: str | None = Field(
        default=None, min_length=1, max_length=64,
        description="Place immediately after this live point code in the measuring order. Omit/null to append.",
    )
    counted: bool = Field(
        default=True,
        description="Whether it feeds the dashboard's Hor / Ver. On by default.",
    )
    orientation: Literal["H", "V"] | None = Field(
        default=None,
        description=(
            "Horizontal or Vertical. Omit it (or send null) to take the one "
            "this list's own points of the same panel word carry -- "
            "099TGATEIN takes what 091-093TGATEIN have. Where the list has no "
            "point of that word, or its points disagree, the server refuses "
            "with 422 and the person chooses."
        ),
    )
    reason: str = Field(
        min_length=3, max_length=500,
        description="Why this point exists. Stored with your name and the time.",
    )


class FilmPointRetireCreate(StrictModel):
    """T109 (D-109-4): take a point off the live list, keeping everything.

    The point leaves the walk and stops feeding the dashboard for every
    month. Its readings stay in History tagged `retired`, no car becomes
    incomplete because of it, and a later upload that writes its label is
    asked about in the row. RO17: restore puts it back; the last live point
    of a list cannot be retired.
    """

    point_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(
        min_length=3, max_length=500,
        description=(
            "Why this point is gone. Required: it is the thing a reader of "
            "the retired row needs, and it is stored with your name and the "
            "time."
        ),
    )


class FilmPointChangeResult(StrictModel):
    """T109: what an add, a retire or a restore did, in the list's own terms."""

    point_code: str
    point_no: int = Field(ge=1)
    label: str = Field(description="RO17: the point's current label.")
    operator_message: str
    replayed_load_ids: list[int] = Field(
        default_factory=list,
        description="Stored sheets held asking about this point, now being read again.",
    )


class FilmPointAliasCreate(StrictModel):
    """T109 (D-109-6): which live point a label on this sheet is.

    Answered in the row. The answer is remembered for every later upload of
    this plant x model, so the same label never asks twice.
    """

    load_id: int = Field(ge=1)
    raw_location: str = Field(
        min_length=1, max_length=200,
        description=(
            "The label as the sheet wrote it. It must be one of this tab's "
            "film_unknown_labels; anything else is refused."
        ),
    )
    point_code: str = Field(
        min_length=1, max_length=64,
        description=(
            "A live point of this plant's list for the tab's model, from "
            "film_point_choices. A point the list does not carry is refused: "
            "this answer never mints a point (add it on Point Check first)."
        ),
    )
    note: str | None = Field(default=None, max_length=500)


class FilmModelOut(StrictModel):
    """T100 (Part A3): one FilmThickness model this plant has a list for."""

    model_code: str
    display_name: str | None
    point_count: int = Field(
        ge=1, description="Live points on this plant's list for the model."
    )
    has_setting: bool = Field(
        description=(
            "Whether film_point_setting rows exist for this plant x model. "
            "False means the T99 point rules are switched off here "
            "(D-99-12). RO17 (D-RO17-11): the list can still be edited."
        )
    )


class FilmModelsOut(StrictModel):
    """T100 (Part A3): which Film models the Points panel can offer."""

    plant_code: str
    items: list[FilmModelOut] = Field(
        description="Models with a live Film point list, by model_code."
    )
    offered_without_list: list[str] = Field(
        default_factory=list,
        description=(
            "RO17 (D-RO17-10). Film models this plant offers that have no "
            "live point list yet: the first point added starts one."
        ),
    )


class FilmNotAPointCreate(StrictModel):
    """RO18 (B5): "Not a point of this list: keep it, never load it".

    The other answer to a row's point question. Remembered per plant x model:
    rows writing this label are kept with the file and never loaded, and
    they do not hold the sheet. Retirable by an Admin on the Aliases screen.
    """

    load_id: int = Field(ge=1)
    raw_location: str = Field(
        min_length=1, max_length=200,
        description="The label as the sheet wrote it; one of film_unknown_labels.",
    )
    note: str | None = Field(default=None, max_length=500)


class MonthAnswerCreate(StrictModel):
    """RO18 (B4): the month this undated sheet's cars were measured in."""

    load_id: int = Field(ge=1)
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM.")
    note: str | None = Field(default=None, max_length=500)


class FilmDateAnswerCreate(StrictModel):
    """RO18 (B3): which date of this Film sheet is right."""

    load_id: int = Field(ge=1)
    choice: Literal["sheet", "file_name"]
    note: str | None = Field(default=None, max_length=500)


class DecisionResult(StrictModel):
    decisions_written: int
    replayed_load_ids: list[int] = Field(
        description="Sheets re-read from the stored bytes. They return to review."
    )
    operator_message: str


class PlantAnswerResult(StrictModel):
    answer: Literal["page_plant", "other_plant"]
    decisions_written: int
    replayed_load_ids: list[int]
    cancelled: bool
    open_plant: str | None = Field(
        description="When cancelled: the plant page to upload this file on."
    )
    operator_message: str


class SheetLoadOutcome(StrictModel):
    load_id: int
    sheet: str
    measurements_inserted: int
    loaded: bool
    blockers: list[str]
    operator_message: str


class WorkbookLoadResult(StrictModel):
    sheets: list[SheetLoadOutcome]
    measurements_inserted: int = Field(
        description=(
            "Fact rows written. For FilmThickness that is one per layer, so "
            "it can be up to four times readings_added."
        )
    )
    readings_added: int = Field(
        description=(
            "T54: readings the uploader added -- WaveScan points, or "
            "FilmThickness points (not layers). The toast counts these."
        )
    )
    rows_held: int = Field(
        description="T53: rows of this workbook still held out after this click."
    )
    rows_already_in_history: int = Field(
        description="T53: rows that were already in History and were not added again."
    )
    months: list[str] = Field(
        description="T53: months the added readings belong to, YYYY-MM, oldest first."
    )
    operator_message: str = Field(
        description=(
            "T53: the toast, e.g. \"40 readings added to September 2026, "
            "2 held out, 31 already in History.\" ASCII only."
        )
    )
