"""T39: the uploader's worksheet -- one confirm page per uploaded workbook.

ADR 0013. The Engineer who uploaded the file owns the checklist:

* **read** it (`worksheet`): every tab, what loads on "Yes", what is held and
  why, in plain words;
* **answer** it: ignore a column we do not use (`ignore_columns`), say
  whether the Plant text is this plant (`answer_plant`), approve points with
  no LW/SW (`approve_holes`);
* **load** it: "Yes, load these rows" commits every ready tab
  (`load_ready`), and after a later answer the same tabs insert the rows
  that became loadable (`load_remaining`).

Every answer is a `worksheet_decision` row plus an audit event, and every
re-read goes through the one ingest service from the stored bytes. Nothing
here parses Excel on a GET, invents a value, UPDATEs a measurement, or mints
a catalogue name. Colour and model matches use the existing Engineer
`ALIAS_COLOR` / `ALIAS_MODEL` path (`POST /mappings/proposals`).
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

from sqlalchemy import Connection, text

from app.domain.cleaner import (
    REASON_MONTH_UNKNOWN,
    RejectReason,
    parse_month_answer,
    suggest_month,
)
from app.domain.film import (
    REASON_EXTRA_POINT,
    REASON_FILM_JOB_UNUSUAL,
    REASON_FILM_MODEL_CONFLICT,
    REASON_FILM_MODEL_UNRESOLVED,
    REASON_FILM_POINT_UNKNOWN,
    REASON_FILM_POINT_WAITING,
    REASON_FILM_TAIL_LABEL,
    REASON_FILM_NOT_A_POINT,
    REASON_FILM_DATE_DISAGREES,
    FILE_DATE_TOLERANCE_DAYS,
    file_name_date,
    parse_film_date,
    REASON_FILM_WALK_UNKNOWN,
    REASON_LIMIT_ROW,
    REASON_UNMAPPED_POINT,
    RENUMBER_ADVICE,
    FilmReference,
    ftm_filename_token,
    normalise_location,
    plant_film_vocabulary,
    real_identity,
)
from app.domain.film_walk import (
    box_tag,
    check_walks,
    model_conflict,
    no_named_points_note,
    point_no_of,
    proposed_orientation,
    read_job_no,
)
from app.domain.film_header import SHEET_FILMTHICKNESS
from app.domain.held_label_copy import (
    FILM_MODEL_MESSAGE,
    display_group_for,
    has_display_group,
    operator_message_for,
)
from app.domain.reader import (
    MEASURES_HOLE_APPROVABLE,
    missing_measures,
    OPTIONAL_FIELDS,
    REQUIRED_WITHOUT_PROFILE,
    SHEET_OUT_OF_SCOPE,
    SHEET_WAVESCAN,
    normalise_header,
)
from app.domain.workbooks import group_vehicle_sets
from app.repositories import acknowledgements as ack_repo
from app.repositories import audit, batches
from app.repositories import filmthickness as film_repo
from app.repositories import reference as reference_repo
from app.repositories import workbooks as workbooks_repo
from app.repositories import worksheet as repo
from app.repositories import ws_points as ws_points_repo
from app.services import point_labels, point_walk
from app.services.held_labels import held_label_items
from app.domain.references import normalise_alias
from app.services.panel_match import (
    ACCEPT_PREFILLED_WORDS,
    rename_signals,
    rough_panel_rows,
)
from app.services.ingest import (
    BLOCKER_DUPLICATE_LOGICAL_FIELD,
    BLOCKER_UNKNOWN_TEMPLATE,
    BLOCKER_UNREVIEWED_HEADER,
    BLOCKER_UNVERIFIED_PROFILE,
    BLOCKER_WARNINGS_UNACKNOWLEDGED,
    IngestError,
    IngestService,
    commit_blockers,
    unacknowledged_categories,
)
from app.services.workbooks import WorkbookError, resolve_plant

YES_NOTE = "Confirmed on the worksheet: Yes, load these rows."

#: Blockers the Engineer can clear from the worksheet itself.
_ANSWERABLE = {BLOCKER_UNREVIEWED_HEADER, BLOCKER_DUPLICATE_LOGICAL_FIELD}

#: RO14 (D-RO14-6). The only blockers an Admin clears by publishing a layout:
#: no active profile, or one nobody has verified (T26).
_ADMIN_WAIT = {BLOCKER_UNKNOWN_TEMPLATE, BLOCKER_UNVERIFIED_PROFILE}

#: T42: how a logical field is named to the person reading the worksheet.
_FIELD_WORDS = {
    "date": "Date", "model": "Model", "checkzone": "Checkzone (panel)",
    "color": "Color", "cf": "CF", "doi": "DOI", "serial_no": "Serial No",
    "paintline": "Paintline", "du": "du", "wa": "Wa", "wb": "Wb", "wc": "Wc",
    "wd": "Wd", "we": "We", "b": "B",
    # RO08 (D-RO08-2): the Film fields `film_missing` can name.
    "location": "Location", "layer": "Layer",
}

#: RO08 (D-RO08-2): where a Film tab could have carried each required field.
_FILM_FIELD_PLACES = {
    "date": 'no Date column, no "Date:" line and no date in its banner',
    "color": 'no Color column, no "Layer 2:" line and no color in its banner',
    "location": "no Location or Checkzone column",
    "layer": "no Clearcoat, Basecoat, Primer or E-coat column",
}


# =====================================================================
# helpers
# =====================================================================
def _sheets(conn: Connection, plant_code: str, file_hash: str) -> tuple[dict, list[dict]]:
    plant = resolve_plant(conn, plant_code)
    sheets = repo.batches_at_plant(conn, plant["plant_code"], file_hash)
    if not sheets:
        raise WorkbookError(
            404,
            f"No workbook {file_hash[:12]}... at plant {plant['plant_code']}. "
            f"It may have been removed, or filed under another plant.",
        )
    return plant, sheets


def _duplicate_header_names(sheet: dict, alias_map) -> set[str]:
    """Header names on this sheet whose field another column also carries."""
    raw = sheet.get("raw_headers") or {}
    if not isinstance(raw, dict):
        return set()
    duplicated = set(raw.get("duplicate_fields") or [])
    if not duplicated:
        return set()
    return {
        normalise_header(h) for h in raw.get("headers") or []
        if alias_map.get(normalise_header(h)) in duplicated
    }


def _recognised_fields(sheet: dict) -> set[str] | None:
    """Logical fields this tab's header row mapped, from the stored header
    interpretation (no workbook opened). None when nothing was stored."""
    raw = sheet.get("raw_headers") or {}
    if not isinstance(raw, dict) or "recognised" not in raw:
        return None
    return set((raw.get("recognised") or {}).values())


def _missing_optional(sheet: dict) -> list[str]:
    """T42: optional fields a WaveScan tab has no column for. A notice only."""
    fields = _recognised_fields(sheet)
    if fields is None or sheet.get("sheet_class") != SHEET_WAVESCAN:
        return []
    return [f for f in OPTIONAL_FIELDS if f not in fields]


def _missing_required(sheet: dict) -> list[str]:
    """T42: required columns a WaveScan tab lacks. The page supplies plant."""
    fields = _recognised_fields(sheet)
    if fields is None or sheet.get("sheet_class") != SHEET_WAVESCAN:
        return []
    return [f for f in REQUIRED_WITHOUT_PROFILE if f != "plant" and f not in fields]


def _film_missing_required(sheet: dict) -> list[str]:
    """RO08 (D-RO08-2): required fields a Film tab lacks, as its stored
    template recorded them when it was refused (`raw_headers`)."""
    raw = sheet.get("raw_headers") or {}
    if (sheet.get("sheet_class") != SHEET_FILMTHICKNESS or not isinstance(raw, dict)
            or sheet.get("status") != batches.STATUS_REJECTED_TEMPLATE):
        return []
    return [str(f) for f in raw.get("missing_required") or []]


def film_missing_message(fields: list[str]) -> str:
    """One plain sentence for a Film tab refused for a missing field."""
    thing = _words(fields).lower()
    if len(fields) == 1:
        place = _FILM_FIELD_PLACES.get(fields[0])
        return (
            f"This tab has no {thing}" + (f": {place}" if place else "")
            + f", so it cannot load. Upload a version that has the {thing}."
        )
    return f"This tab has no {thing}, so it cannot load. Upload a version that has them."


def _words(fields: list[str]) -> str:
    names = [_FIELD_WORDS.get(f, f) for f in fields]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " or " + names[-1]


def missing_optional_message(fields: list[str]) -> str | None:
    """One plain sentence for optional columns the file does not have."""
    if not fields:
        return None
    if fields == ["doi"]:
        return "This file has no DOI column. Rows can still load with DOI empty."
    return (
        f"This file has no {_words(fields)} column. Rows can still load with "
        f"{'that' if len(fields) == 1 else 'those'} left empty."
    )


def _upload_plant_texts(conn: Connection, sheet: dict) -> list[str]:
    """Plant texts the door scan saw, for a tab that was never parsed.

    Only a REJECTED_TEMPLATE tab has no projection to read them from. Texts
    an Engineer already confirmed are not asked again.
    """
    if sheet["status"] != batches.STATUS_REJECTED_TEMPLATE:
        return []
    load_id = int(sheet["load_id"])
    event = audit.latest_action(conn, "load_batch", load_id, "batch.upload")
    after = (event or {}).get("after") or {}
    done = repo.decisions_for_batch(conn, load_id)[repo.KIND_PLANT_CONFIRM]
    return [t for t in after.get("plant_texts_to_confirm") or [] if t not in done]


def _held_facts(conn: Connection, load_id: int) -> tuple[list[int], list[str], int]:
    """(hole rows, plant texts, held row count) from the stored projection."""
    rows = repo.held_rows(conn, load_id)
    # T98 (D-98-1): only rows approval can actually load. A row short of CF
    # too still refuses after the approval, so it is not offered one.
    holes = sorted({
        int(r["source_row"]) for r in rows
        if r["reason"] == RejectReason.MISSING_MEASUREMENT
        and (r["label_column"] or "").lower() in MEASURES_HOLE_APPROVABLE
        and set(missing_measures(r.get("detail"))) <= set(MEASURES_HOLE_APPROVABLE)
    })
    texts = list(dict.fromkeys(
        r["raw_value"] for r in rows
        if r["reason"] == RejectReason.PLANT_MISMATCH and r["raw_value"]
    ))
    return holes, texts, len(rows)


# =====================================================================
# T53: the confirm table, in three outcomes
# =====================================================================
_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)

#: Reasons the held-label copy names; the rest get a sentence below.
_NUMBER_REASONS = {RejectReason.BAD_NUMBER, RejectReason.OUT_OF_RANGE}

#: T53 (D-53-18). The one sentence a cover, Methods or Color Data tab gets.
EXTRA_TAB_MESSAGE = "Extra tab kept. Not loaded."
AGGREGATE_ROW_MESSAGE = (
    "This is a report total row ([All]), not one vehicle. It is kept and "
    "not loaded."
)
IN_FILE_COPY_MESSAGE = (
    "The same panel and readings appear twice in this file. The other copy "
    "is added; this one is kept as a record."
)
EARLIER_FILE_MESSAGE = (
    "This reading is already in History from an earlier file. It is not "
    "added twice."
)
LIMIT_ROW_MESSAGE = (
    "This is a limit row (Fail / Warning / Match to standard), not a point "
    "of a car. It is kept and not loaded."
)
IN_HISTORY_MESSAGE = "This reading is in History."
READY_MESSAGE = "Ready to add."

#: T94 (D-94-2). The row outcome a rough panel label gets instead of
#: ``ready``. It is a third thing on purpose: ``held_out`` says "fix the
#: file", and this says "tell us which panel this is, here, now" -- and
#: the answer is one click away in the same row (D-94-3).
OUTCOME_NEEDS_CONFIRMATION = "needs_confirmation"

#: T99. Holds that are about the whole sheet, not about this row's label.
#: Their sentence is written once, by `domain/film_walk`, and carried on the
#: row so the worksheet never re-derives it. T109-FIX (D-109F-1): a row
#: waiting on another row's unanswered label is one of them -- the sentence is
#: the walk's, it says what the sheet is waiting for, and this row's own
#: spelling is not the problem.
_FILM_SHEET_REASONS = frozenset({
    REASON_FILM_WALK_UNKNOWN, REASON_FILM_JOB_UNUSUAL,
    REASON_FILM_MODEL_CONFLICT, REASON_FILM_POINT_WAITING,
    # RO18 (B3 / B4): the sheet's date question and its month question.
    REASON_FILM_DATE_DISAGREES, REASON_MONTH_UNKNOWN,
})
#: Said in the summary line, so the count is read before the table is.
NEEDS_CONFIRMATION_WORDS = (
    "{rows} reading(s) name a panel that does not say which panel it is. Confirm the panel in the row and they load under its long name (T94)."
)

#: T109 (D-109-6). The Film half of the same sentence. A Film row is never
#: asked "which panel is this" -- it is asked which **point** of this plant's
#: list a label is, and the answer is remembered for every later upload,
#: which is the part a reader needs to know before they answer 98 of them.
#: T109-FIX (D-109F-1, D-109F-3) widens it: nothing on the tab loads until
#: every label is answered, and the renumbered walk -- the one shape where
#: mapping the labels would file every reading one point out -- is told what
#: to do instead.
FILM_POINT_WORDS = (
    "{rows} reading(s) name a point that is not on this plant's list for the model. Say which live point each one is in its row -- we remember it for every later upload -- or add it as a new point on Point Check. Nothing on this tab loads until every label is answered. " + RENUMBER_ADVICE
)
#: RO17-FIX (D-RO17F-2): on a list without settings the rest of the tab loads.
FILM_POINT_REST_WORDS = (
    "{rows} reading(s) name a point that is not on this plant's list for the model. Say which live point each one is in its row -- we remember it for every later upload -- or add it as a new point on Point Check. The other rows of this tab load; these rows wait until they are answered."
)


def _text(value) -> str | None:
    if value is None:
        return None
    shown = str(value).strip()
    return shown or None


def _date_text(values: dict) -> str | None:
    shown = _text(values.get("date"))
    if shown and shown.endswith("T00:00:00"):
        shown = shown[: -len("T00:00:00")]
    return shown


def _iso_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def held_row_message(reason: str | None, column: str | None, value: str | None,
                     *, plant: str, detail: str | None = None) -> str:
    """One plain sentence for a row that is held out (T53, D-53-15)."""
    reason = reason or ""
    shown = value or ""
    if reason in _NUMBER_REASONS:
        label = (column or "a reading").upper()
        return (
            f"{label} is not a number we can read on this row, so it will not "
            f"load. Fix the file and upload it again. We never change a reading."
        )
    if reason == RejectReason.UNKNOWN_PAINTLINE:
        return (
            f'Paintline "{shown}" is not a booth we know. Fix the file, or leave '
            f"the cell blank. The rest of the sheet still loads."
        )
    if reason == RejectReason.UNKNOWN_PLANT:
        return f'Plant "{shown}" is not a plant we know, so this row will not load.'
    if reason in (RejectReason.OTHER, REASON_MONTH_UNKNOWN) and detail:
        # RO16 (D-RO16-3): the cleaner's own sentence names the car. RO18
        # (B4): the sheet's month question, said once by the cleaner.
        return detail
    if has_display_group(reason):
        return operator_message_for(
            display_group_for(reason, shown), shown, column=column, plant=plant,
            reason=reason, details=[detail] if detail else None,
        )
    return "This row will not load as written. Fix the file and upload it again."


def film_held_message(reason: str | None, location: str | None, model: str | None,
                      *, plant: str, detail: str | None = None) -> str | None:
    """T54: one plain sentence for a FilmThickness row that is held out."""
    shown = location or "(blank)"
    on = f"{plant}'s {model} point list" if model else f"{plant}'s point list"
    # T99: the three sheet-wide holds and the never-stored tail are facts
    # about the *sheet*, not about this row's label, and `domain/film_walk`
    # wrote the one sentence that says which -- naming the label that broke
    # the walk, or the Job Number, or the two models. Re-deriving it here
    # would be a second copy that can disagree with the parse.
    if reason in _FILM_SHEET_REASONS and detail:
        return detail
    # T109 (D-109-6): the row's own question, written once by the cleaner,
    # which is the only place that knows the label did not resolve.
    if reason == REASON_FILM_POINT_UNKNOWN and detail:
        return detail
    if reason == REASON_EXTRA_POINT:
        return (
            f'"{shown}" is an extra point (095-098 or FTWISH), not on {on}. '
            "It is kept and not loaded."
        )
    if reason == REASON_UNMAPPED_POINT:
        return (
            f'"{shown}" is not on {on}. It is kept and not loaded. If it is a '
            "new point, ask an Admin to add it to the catalogue first, then "
            "upload again. We never move it onto another plant's point."
        )
    if reason == REASON_FILM_MODEL_UNRESOLVED:
        return FILM_MODEL_MESSAGE
    if reason == RejectReason.MISSING_MEASUREMENT:
        return f'"{shown}" has no paint-layer reading, so it will not load.'
    return None


def _rough_panels(conn: Connection, sheet: dict, plant: str) -> list[dict]:
    """T94: the rough panel labels of one tab, or none for a Film tab.

    Film rows carry a Location, not a WaveScan panel name, and their
    identity is the plant's own gold point list rather than a model's
    canonical walk (T54). D-94-1 is a rule about a WaveScan walk, so it is
    not applied to a Film tab at all -- applying it there would be inventing
    a rule the owner has not named.
    """
    if sheet.get("sheet_class") != SHEET_WAVESCAN:
        return []
    return rough_panel_rows(conn, int(sheet["load_id"]), plant)


#: T100 (Part A1). Which question each sheet-wide Film hold is asking.
_FILM_QUESTION_KIND = {
    REASON_FILM_WALK_UNKNOWN: "walk",
    REASON_FILM_MODEL_CONFLICT: "model",
    REASON_FILM_JOB_UNUSUAL: "job",
}


def _film_model_of(projection: list[dict]) -> str | None:
    """T100: the model a Film tab was read as, off its own projection.

    The model is a property of the sheet (F4-F7), so every row's canonical
    carries the same one; the first row that names it answers for the tab.
    """
    for row in projection:
        model = (row.get("canonical") or {}).get("model")
        if model:
            return str(model)
    return None


def _film_box(
    film: FilmReference, plant: str, model: str | None, table: list[dict]
) -> str | None:
    """T103 (D-103-1): Box / No box for one Film tab, before it loads.

    The ranks are positions in the plant's live walk for the model, which
    is how `box_tag` is told where the box section starts; `point_no` is
    not contiguous (FTM DBL numbers 94 points up to 098TGATEIN), so the
    list's own order is what a rank has to come from. The rows that count
    are the ones that are or will be measurements -- a row this tab holds
    measured nothing.
    """
    if not model:
        return None
    rank = {point: i for i, point in enumerate(film.walk.get((plant, model)) or ())}
    return box_tag(
        [rank[point] for point in film.complete_stops.get((plant, model)) or ()
         if point in rank],
        [rank[row["checkzone"]] for row in table
         if row["outcome"] in ("ready", "already_in_history")
         and row["checkzone"] in rank],
    )


def _film_unknown_labels(table: list[dict]) -> list[dict]:
    """T109 (D-109-6). The labels this tab is asking about, in file order.

    One entry per distinct label with how many rows carry it, because the
    answer is per label and not per row: a Cab sheet writing the same retired
    name on four rows is one question, answered once, and then all four load
    on the replay.
    """
    rows: dict[str, int] = {}
    for row in table:
        if row["outcome"] != OUTCOME_NEEDS_CONFIRMATION:
            continue
        label = row.get("panel_label")
        if not label:
            continue
        rows[label] = rows.get(label, 0) + 1
    return [{"raw_location": label, "rows": n} for label, n in rows.items()]


def _film_point_choices(
    conn: Connection, plant: str, model: str | None
) -> list[dict]:
    """T109 (section 3.6). The live points a row answer may name.

    This plant's live list for the model in walk order, each with its
    Horizontal / Vertical and whether it is extra -- the same read Point
    Check itself shows (`point_setting`), so the picker cannot offer a point
    the plant does not walk, a retired one, or another plant's name, and the
    two screens can never list different points.

    Read only when a tab actually has a label to ask about, so an ordinary
    worksheet costs no extra statement.
    """
    if not model:
        return []
    return [
        {
            "point_no": point["point_no"],
            "point_code": point["point_code"],
            "orientation": point["orientation"],
            "is_extra": point["is_extra"],
        }
        for point in film_repo.point_setting(conn, plant, model)
    ]


def _film_question(
    sheet: dict, projection: list[dict], film: FilmReference
) -> dict | None:
    """T100 (D-100-1): the one question a held Film tab asks, structured.

    Everything comes from what is already stored -- the batch row's own
    ``raw_headers.meta`` (the PELT preamble, so the Job Number without
    opening the workbook), the review projection, and the live Film
    reference -- and the walk is re-read by `check_walk`, the **same**
    function that decided the hold. No workbook is parsed on this GET, and
    no rule is written twice (which is the whole of D-100-1).

    Null for a WaveScan tab and for a Film tab with no sheet-wide hold.
    """
    if sheet.get("sheet_class") != SHEET_FILMTHICKNESS:
        return None
    held = [r for r in projection if r.get("reason") in _FILM_QUESTION_KIND]
    if not held:
        return None
    plant = sheet["plant_code"]
    first = held[0]
    reason = first["reason"]
    model = (first.get("canonical") or {}).get("model")
    meta = (sheet.get("raw_headers") or {}).get("meta") or {}
    job = str(meta.get("job number") or "").strip() or None
    out = {
        "kind": _FILM_QUESTION_KIND[reason],
        "operator_message": first.get("detail") or "",
        "model_code": model,
        "confirmable": False,
        "appended": [],
        "models": [],
        "job_no": job,
    }
    if reason == REASON_FILM_MODEL_CONFLICT:
        # The two models the sheet itself named, re-derived from the Job
        # Number and the file name by the function the hold used.
        verdict = read_job_no(film.job_pattern.get(plant), job)
        pair = model_conflict(
            verdict.model_token, ftm_filename_token(sheet["source_file"]),
            film.model_alias, plant=plant,
        )
        out["models"] = list(pair) if pair else []
        return out
    if reason != REASON_FILM_WALK_UNKNOWN:
        return out

    # The body labels, in file order, off the projection: a held sheet holds
    # every one of them, and each carries the Location it wrote.
    body = [
        ((r.get("canonical") or {}).get("offending_value"), r["source_row"],
         _film_identity((r.get("raw") or {}).get("values") or {}, meta))
        for r in held
    ]
    body = [item for item in body if item[0]]
    walk = film.walk.get((plant, model), ())
    # RO14 (D-RO14-2): car by car, as the hold was decided.
    walked = check_walks(
        [label for label, _, _ in body], walk, rows=[row for _, row, _ in body],
        plant=plant, model=model or "this model",
        identities=[identity for _, _, identity in body],
    )
    orientations = {
        point: film.orientation_of(plant, model or "", point) for point in walk
    }
    out["confirmable"] = walked.confirmable
    out["appended"] = [
        {
            "point_code": name,
            "proposed_orientation": proposed_orientation(name, orientations),
            "counted": True,
        }
        for name in walked.appended
    ]
    return out


def _date_question(sheet: dict, projection: list[dict]) -> dict | None:
    """RO18 (B3 / B4). The tab's date question, either domain, or None.

    ``month``: the sheet has no date anywhere; which month? ``date``: a Film
    sheet's date and its file name's are more than the owner's 3 days apart;
    which is right? Read off the stored projection and the batch's own
    preamble, the same inputs the hold was decided from.
    """
    held = next(
        (r for r in projection
         if r.get("reason") in (REASON_MONTH_UNKNOWN, REASON_FILM_DATE_DISAGREES)),
        None,
    )
    if held is None:
        return None
    out = {
        "kind": "month" if held["reason"] == REASON_MONTH_UNKNOWN else "date",
        "operator_message": held.get("detail") or "",
        "suggested_month": None, "sheet_date": None, "file_name_date": None,
    }
    if out["kind"] == "month":
        out["suggested_month"] = suggest_month(sheet["source_file"])
        return out
    named = file_name_date(sheet["source_file"])
    meta = (sheet.get("raw_headers") or {}).get("meta") or {}
    days = sorted({
        day for day, _ in (
            parse_film_date(
                values.get("date") if "date" in values else meta.get("date")
            )
            for values in (
                ((r.get("raw") or {}).get("values") or {}) for r in projection
                if r.get("reason") == REASON_FILM_DATE_DISAGREES
            )
        ) if day is not None
    })
    far = [d for d in days if named and abs((d - named).days) > FILE_DATE_TOLERANCE_DAYS]
    out["sheet_date"] = (far or days or [None])[0]
    out["file_name_date"] = named
    return out


def _film_identity(values: dict, meta: dict) -> tuple:
    """RO14. A held row's ``(Job Number, VIN)``, read as the cleaner reads it."""
    return (
        real_identity(values["job"] if "job" in values else meta.get("job number")),
        real_identity(values["vin"] if "vin" in values else meta.get("vin")),
    )


def _sheet_hold_note(projection: list[dict]) -> str | None:
    """RO14 (D-RO14-6). The sentence of a tab held by one sheet-wide hold.

    A sheet-wide hold writes the same reason and the same sentence on every
    row it holds, so a tab whose held rows all carry one (reason, sentence)
    is held by that one thing. None when nothing is held or the holds differ.
    """
    held = {
        (r.get("reason"), r.get("detail"))
        for r in projection if r.get("disposition") == "QUARANTINE"
    }
    if len(held) != 1:
        return None
    (_, detail), = held
    return detail or None


def film_models(conn: Connection, plant_code: str) -> dict:
    """T100 (Part A3): the Film models this plant has a live point list for.

    RO17 (D-RO17-10): plus the offered Film models with no live list yet.
    """
    plant = resolve_plant(conn, plant_code)
    page = plant["plant_code"]
    items = film_repo.plant_film_models(conn, page)
    listed = {item["model_code"] for item in items}
    return {
        "plant_code": page,
        "items": items,
        "offered_without_list": [
            m for m in _film_offered(conn, page) if m not in listed
        ],
    }


def _film_offered(conn: Connection, plant: str) -> list[str]:
    """RO17 (D-RO17-10). Offered models of this plant's Film vocabulary."""
    film = film_repo.load_film_reference(conn)
    offered = film_repo.offered_models(conn, plant)
    return [
        m for m in plant_film_vocabulary(plant, film.model_alias)
        if m in offered
    ]


def _by_spelling(rough: list[dict]) -> dict[str, dict]:
    """``{normalised panel spelling: its row question}``, first model wins.

    One sheet can carry two models, and in the FTM September file both write
    the same 32 spellings. A spelling rough on either model is rough on this
    sheet's table, and the sentence shown is the same question either way.
    """
    out: dict[str, dict] = {}
    for item in rough:
        out.setdefault(normalise_alias(item["raw_zone_text"]), item)
    return out


def _from_earlier_file(row: dict) -> bool:
    """A DUPLICATE of a reading already stored, not of a row in this file."""
    detail = row.get("detail") or ""
    return row["disposition"] == "DUPLICATE" and (
        "already loaded from" in detail      # WaveScan dedup
        or "already a fact of load" in detail  # FilmThickness (T54)
    )


def preview_rows(sheet_name: str, rows: list[dict], fact_rows: set[int],
                 *, plant: str, film: bool = False,
                 rough: Mapping[str, dict] | None = None,
                 setting: Mapping[str, tuple[bool, str]] | None = None,
                 extra: frozenset[str] | None = None,
                 ask_held: bool = False) -> list[dict]:
    """The confirm table for one tab, from the stored projection (T53).

    T54: a FilmThickness tab uses the same row contract. ``panel_label`` is
    the Location cell as the file wrote it and ``checkzone`` carries the
    plant's gold ``point_code`` -- the catalogue identity of a Film row.

    T94 (D-94-2): ``rough`` maps the normalised panel spellings this sheet's
    own walk makes rough to what the row needs to ask about them. A row
    carrying one of those spellings is never ``ready``; it is
    ``needs_confirmation`` until a person says which panel it is, and then
    the replay resolves it and it is ``ready`` like any other row. The
    classification is not re-derived here -- it is handed in, from the one
    place that owns it (`services/panel_match.rough_panel_rows`).
    """
    rough = rough or {}
    setting = setting or {}
    out: list[dict] = []
    for r in rows:
        source_row = int(r["source_row"])
        disposition = r["disposition"]
        canonical = r.get("canonical") or {}
        values = (r.get("raw") or {}).get("values") or {}
        clean = disposition in ("LOAD", "DUPLICATE")
        if source_row in fact_rows:
            outcome, message = "already_in_history", IN_HISTORY_MESSAGE
            # T103 (D-103-6): a loaded Film row that carried a warning keeps
            # it. Until now the sentence was replaced the moment the row
            # became a measurement, which is exactly when D-99-11 meant it
            # to stay findable.
            if film and disposition == "LOAD" and r.get("detail"):
                message = f"{message} {r['detail']}"
        elif disposition == "LOAD":
            # T99 (D-99-11): a row that loads may still carry a warning -- the
            # Job Number's colour code disagreeing with the file name's. It is
            # said in the row because that is where it would otherwise be lost.
            outcome = "ready"
            message = (r.get("detail") or READY_MESSAGE) if film else READY_MESSAGE
        elif disposition == "DUPLICATE":
            if _from_earlier_file(r):
                outcome, message = "already_in_history", EARLIER_FILE_MESSAGE
            else:
                outcome, message = "held_out", IN_FILE_COPY_MESSAGE
        elif disposition == "AGGREGATE_ROW":
            reason = r.get("reason")
            outcome, message = "held_out", (
                # T99 (D-99-6): the known tail of the walk. Its own sentence,
                # written by the parse, and never a hold.
                (r.get("detail") or AGGREGATE_ROW_MESSAGE)
                if reason in (REASON_FILM_TAIL_LABEL, REASON_FILM_NOT_A_POINT)
                else LIMIT_ROW_MESSAGE if reason == REASON_LIMIT_ROW
                else AGGREGATE_ROW_MESSAGE
            )
        else:
            column = canonical.get("offending_column") or (
                "model" if r.get("reason") == "UNIDENTIFIED_MODEL" else None
            )
            value = canonical.get("offending_value") or canonical.get("raw_model")
            outcome = "held_out"
            message = (
                film_held_message(
                    r.get("reason"), _text(values.get("location")) or value,
                    canonical.get("model"), plant=plant, detail=r.get("detail"),
                ) if film else None
            ) or held_row_message(r.get("reason"), column, value, plant=plant,
                                  detail=r.get("detail"))
        if film:
            panel = _text(values.get("location")) or _text(canonical.get("src_location_text"))
            code = canonical.get("point_code") if clean else None
            # T109 (D-109-6): a label the live list does not hold is a
            # question, not a refusal -- which live point is this? The answer
            # is in this row, exactly as T94's panel answer is, and the
            # sentence the cleaner wrote is already the message.
            if outcome == "held_out" and r.get("reason") == REASON_FILM_POINT_UNKNOWN:
                outcome = OUTCOME_NEEDS_CONFIRMATION
            # RO17-FIX (D-RO17F-2): on a live list without settings the same
            # label is held unmapped / extra (D-99-12); ask it the same way.
            # The rest of the tab still loads: only the rows are asked.
            elif ask_held and outcome == "held_out" and r.get("reason") in (
                REASON_UNMAPPED_POINT, REASON_EXTRA_POINT,
            ):
                outcome = OUTCOME_NEEDS_CONFIRMATION
                message = (
                    f'"{panel or "(blank)"}" is not a point of {plant}\'s '
                    f'{canonical.get("model") or ""} point list. Say which live '
                    "point it is in this row, or add it on Point Check and "
                    "re-check this file. Until then it is kept and not loaded."
                )
        else:
            panel = _text(values.get("checkzone"))
            code = canonical.get("checkzone") if clean else None
            # T94 (D-94-2). A rough label is never ready, whatever the
            # catalogue holds. Today it cannot be: the cleaner refuses to
            # resolve it, so it arrives here held -- and this turns "held
            # out" into the question it actually is, with the sentence the
            # row control shows. A row held for anything else (a bad number
            # on the same line) keeps its own reason.
            asked = rough.get(normalise_alias(panel or ""))
            if asked is not None and outcome == "held_out" and not code:
                outcome = OUTCOME_NEEDS_CONFIRMATION
                message = asked["operator_message"]
        out.append({
            "source_sheet": sheet_name,
            "source_row": source_row,
            "panel_label": panel,
            "checkzone": code,
            "model_text": _text(values.get("model")),
            "model": canonical.get("model") if clean else None,
            "color_text": _text(values.get("color")),
            "color": canonical.get("color") if clean else None,
            "date_text": _date_text(values),
            "measured_date": _iso_date(canonical.get("measured_date")) if clean else None,
            "outcome": outcome,
            "operator_message": message,
            # T100 (D-100-2, D-100-4). A read-only tick from the plant x
            # model's latest setting, and the "Not stored" flag for the
            # walk's known tail. Null where there is nothing to say: a
            # WaveScan row, a plant with no setting, a row with no point.
            "counted": (
                setting[code][0] if film and code and code in setting else None
            ),
            "film_tail": film and r.get("reason") in (
                REASON_FILM_TAIL_LABEL, REASON_FILM_NOT_A_POINT,
            ),
            # T109 (D-109-3): the extra tag, beside the point it belongs to,
            # read off the plant's live list. Null where there is nothing to
            # say, the same places `counted` is null.
            "film_extra": (
                code in (extra or frozenset())
                if film and code and (extra is not None) else None
            ),
        })
    return out


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _held_out(table: list[dict]) -> int:
    """Rows a person can still make load. T103 (D-103-5): not the tail."""
    return sum(1 for r in table if r["outcome"] == "held_out" and not r["film_tail"])


def _not_stored(table: list[dict]) -> int:
    """Rows of the walk's known tail, which never become a measurement."""
    return sum(1 for r in table if r["film_tail"])


#: T103 (D-103-5): how the walk's known tail is counted. "Held out" means
#: "fix this and it loads"; a tail row has nothing to fix and never loads,
#: so it is counted on its own line and in its own words.
NOT_STORED_WORDS = "{rows} not stored (walk tail)"


def summary_message(ready: int, held: int, already: int,
                    not_stored: int = 0) -> str:
    """The workbook in one plain sentence (T53; T103 D-103-5)."""
    parts = [f"{_count(ready, 'reading', 'readings')} ready to add"]
    if held:
        parts.append(f"{held} held out")
    if not_stored:
        parts.append(NOT_STORED_WORDS.format(rows=not_stored))
    if already:
        parts.append(f"{already} already in History")
    return ", ".join(parts) + "."


def month_words(months: list[str]) -> str:
    """`["2026-08", "2026-09"]` -> `August 2026 and September 2026`."""
    names = []
    for m in months:
        year, _, month = m.partition("-")
        try:
            names.append(f"{_MONTHS[int(month) - 1]} {year}")
        except (ValueError, IndexError):
            names.append(m)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def toast_message(added: int, months: list[str], held: int, already: int,
                  *, not_stored: int = 0, more: bool = False) -> str:
    """The prototype toast: "N readings added to {month}" (D-53-15)."""
    noun = _count(added, "more reading" if more else "reading",
                  "more readings" if more else "readings")
    head = f"{noun} added to {month_words(months)}" if months else f"{noun} added"
    parts = [head]
    if held:
        parts.append(f"{held} held out")
    if not_stored:
        parts.append(NOT_STORED_WORDS.format(rows=not_stored))
    if already:
        parts.append(f"{already} already in History")
    return ", ".join(parts) + "."


def _workbook_outcomes(
    conn: Connection, sheets: list[dict], plant: str
) -> tuple[int, int, int]:
    """(held out, not stored, already in History) over every tab, after a load.

    T103 (D-103-5): the walk's tail rows are counted apart from the held
    ones, so `rows_held` here means what it means on the worksheet -- rows a
    person can still make load.
    """
    held = not_stored = already = 0
    for sheet in sheets:
        load_id = int(sheet["load_id"])
        stored = repo.preview_rows(conn, load_id)
        facts = repo.fact_source_rows(conn, load_id)
        already += sum(
            1 for r in stored
            if _from_earlier_file(r) and int(r["source_row"]) not in facts
        )
        table = preview_rows(
            sheet["source_sheet"], stored, facts, plant=plant,
            film=sheet.get("sheet_class") == SHEET_FILMTHICKNESS,
            rough=_by_spelling(_rough_panels(conn, sheet, plant)),
        )
        held += _held_out(table)
        not_stored += _not_stored(table)
    return held, not_stored, already


def _replay_if_possible(
    ingest: IngestService, conn: Connection, sheet: dict, *, actor: str,
    reason: str, correlation_id: str | None,
) -> bool:
    if sheet["status"] not in batches.REPLAYABLE_STATUSES or sheet["facts"]:
        return False
    try:
        ingest.replay_batch(
            conn, sheet["load_id"], actor_user_id=actor, reason=reason,
            correlation_id=correlation_id,
        )
    except IngestError:
        return False
    return True


def _record(
    conn: Connection, sheet: dict, *, kind: str, subject: str, actor: str,
    note: str | None, correlation_id: str | None,
) -> int:
    decision_id = repo.insert_decision(
        conn, load_id=sheet["load_id"], kind=kind, subject=subject,
        actor_user_id=actor, note=note,
    )
    audit.record(
        conn,
        action="worksheet.decision",
        entity_type="load_batch",
        entity_id=sheet["load_id"],
        actor_user_id=actor,
        after={
            "decision_id": decision_id, "kind": kind, "subject": subject,
            "note": note, "file_hash": str(sheet["file_hash"]).strip(),
        },
        correlation_id=correlation_id,
    )
    return decision_id


# =====================================================================
# the read
# =====================================================================
def worksheet(conn: Connection, plant_code: str, file_hash: str) -> dict:
    plant, sheets = _sheets(conn, plant_code, file_hash)
    page = plant["plant_code"]
    ref = reference_repo.load_reference_data(conn)
    # T100: read once per workbook, not per tab -- the setting, the walk and
    # the tail labels are properties of the plant, not of a sheet.
    film_ref = film_repo.load_film_reference(conn)
    # T114-FIX (D-114F-1): a short vehicle is short of this plant's live list.
    live_points = ws_points_repo.live_lists(conn, page)
    out_sheets: list[dict] = []
    all_texts: dict[str, None] = {}
    all_extra: dict[str, None] = {}
    all_optional: set[str] = set()
    text_rows = 0
    checklist: list[str] = []

    for sheet in sheets:
        load_id = int(sheet["load_id"])
        batch = batches.get_batch(conn, load_id) or sheet
        blockers = commit_blockers(conn, batch)
        holes, texts, held_count = _held_facts(conn, load_id)
        if not texts:
            texts = _upload_plant_texts(conn, sheet)
        text_rows += sum(
            1 for r in repo.held_rows(conn, load_id)
            if r["reason"] == RejectReason.PLANT_MISMATCH
        )
        extra = sorted(
            set(sheet.get("unreviewed_headers") or [])
            | _duplicate_header_names(sheet, ref.column_alias)
        )
        for t in texts:
            all_texts.setdefault(t, None)
        for h in extra:
            all_extra.setdefault(h, None)
        optional = _missing_optional(sheet)
        all_optional.update(optional)
        required = _missing_required(sheet)
        film_required = _film_missing_required(sheet)

        # T54: WaveScan panel counts do not apply to a Film walk; its slots
        # are the plant's gold list, read in GET .../filmthickness.
        sets = (
            [] if sheet.get("sheet_class") == SHEET_FILMTHICKNESS
            else group_vehicle_sets(
                load_id, repo.vehicle_rows(conn, load_id), ref.expected_zones, live_points
            )
        )
        short = [
            {
                "measured_date": v.measured_date,
                "model": v.model,
                "color": v.color,
                "point_count": v.point_count,
                "expected_point_count": v.expected_point_count,
                "operator_message": (
                    f"This vehicle has {v.point_count} of "
                    f"{v.expected_point_count} panels. The panels it has "
                    f"still load."
                ),
            }
            for v in sets
            if v.identity_complete
            and v.expected_point_count is not None
            and v.point_count < v.expected_point_count
        ]

        status = sheet["status"]
        facts = int(sheet["facts"])
        rows_ready = int(sheet["rows_loaded"] or 0) if status == batches.STATUS_PENDING_REVIEW else 0
        others = set(blockers) - {BLOCKER_WARNINGS_UNACKNOWLEDGED}
        rough = _rough_panels(conn, sheet, page)
        is_film = sheet.get("sheet_class") == SHEET_FILMTHICKNESS
        projection = repo.preview_rows(conn, load_id)
        film_question = _film_question(sheet, projection, film_ref)
        date_question = _date_question(sheet, projection)
        film_model = (
            (film_question or {}).get("model_code") or _film_model_of(projection)
            if is_film else None
        )
        table = preview_rows(
            sheet["source_sheet"], projection,
            repo.fact_source_rows(conn, load_id), plant=page,
            film=is_film,
            rough=_by_spelling(rough),
            setting=film_ref.point_setting.get((page, film_model)) if is_film else None,
            extra=(
                film_ref.extra_points.get((page, film_model), frozenset())
                if is_film and film_model else None
            ),
            ask_held=bool(
                is_film and film_model and film_ref.walk.get((page, film_model))
                and not film_ref.has_setting(page, film_model)
            ),
        )
        # T109 (D-109-6): the labels this tab asks about, and the live points
        # an answer may name. Both empty for a WaveScan tab and for a Film
        # tab whose every label resolved.
        film_unknown = _film_unknown_labels(table) if is_film else []
        film_choices = (
            _film_point_choices(conn, page, film_model) if film_unknown else []
        )
        in_history = sum(1 for r in table if r["outcome"] == "already_in_history")
        not_stored = _not_stored(table)
        needs_confirmation = sum(
            1 for r in table if r["outcome"] == OUTCOME_NEEDS_CONFIRMATION
        )
        no_name_note = (
            no_named_points_note(batch.get("notes"))
            if status == batches.STATUS_REJECTED_TEMPLATE else None
        )
        # RO08-FIX (D-RO08F-1): read before the state is chosen, once.
        held = held_label_items(
            conn, load_id, plant_code=page,
            unreviewed_headers=list(sheet.get("unreviewed_headers") or []),
        )
        if sheet.get("sheet_class") == SHEET_OUT_OF_SCOPE:
            # T53 (D-53-18): an extra tab is not a broken template.
            state, message = "not_wavescan", EXTRA_TAB_MESSAGE
        elif status == batches.STATUS_RUNNING:
            state, message = "processing", "We are still reading this tab."
        elif facts:
            state = "loaded"
            message = f"{_count(facts, 'reading', 'readings')} of this tab are in History."
            if held_count:
                message += f" {held_count} held out."
            if not_stored:
                message += " " + NOT_STORED_WORDS.format(rows=not_stored) + "."
        elif status == batches.STATUS_PENDING_REVIEW and not others and rows_ready:
            state, message = "ready", summary_message(
                rows_ready, _held_out(table), in_history, not_stored,
            )
        elif status == batches.STATUS_REJECTED_TEMPLATE and required:
            # T42: say which column, not "waiting for an Admin".
            state, message = "blocked", (
                f"This tab has no {_words(required)} column, so it cannot "
                f"load. Fix the file and upload it again."
            )
        elif film_required:
            # RO08 (D-RO08-2): a Film tab with no date (or colour, location,
            # layer) cannot load, and no Admin approval can supply it.
            state, message = "blocked", film_missing_message(film_required)
        elif (
            status == batches.STATUS_PENDING_REVIEW and not rows_ready
            and in_history and not others and not held_count and not extra
            and not texts and not holes and not film_unknown
            and not needs_confirmation and film_question is None
            and date_question is None
        ):
            # RO08 (D-RO08-1): every reading is already in History and
            # nothing is asked. Nothing new to add; nothing is wrong.
            state, message = "blocked", (
                f"Every reading of this tab is already in History ({in_history}), "
                f"so there is nothing new to add. Nothing is wrong with the file."
            )
        elif no_name_note:
            # T103 (D-103-4): a sheet whose Locations name no point is
            # refused for good, and no Admin approval can lift it (D-99-9).
            # It is told the sentence the refusal already stored, which says
            # what would help: upload the report that writes the names.
            state, message = "blocked", no_name_note
        elif (
            (extra and (others <= _ANSWERABLE or status == batches.STATUS_REJECTED_TEMPLATE)
             and (sheet.get("profile_id") or not required)) or texts or holes
            # T109-FIX (D-109F-1): a Film tab with an unanswered label is a
            # tab with questions on it, not a tab waiting on an Admin. Its
            # rows carry the one sentence the walk wrote, the questions are
            # in the rows, and nothing of it loads until they are answered --
            # so it is never "ready" and never says "blocked".
            or film_unknown
            # RO18 (B3 / B4): which month, or which date -- answered on the tab.
            or date_question is not None
            # RO08-FIX (D-RO08F-2): a label the uploader answers in the row
            # (a colour spelling, a Film model) is a question, not an Admin.
            or any(item.get("teachable_kind") for item in held)
        ):
            # T42: a tab read without a profile answers the same questions.
            state, message = "needs_answer", "Answer the questions for this tab first."
        elif others & _ADMIN_WAIT:
            # RO14 (D-RO14-6): the one case that really waits on an Admin --
            # a layout with no active profile, or one nobody has verified.
            state, message = "blocked", (
                "This tab cannot load yet: its layout is waiting for an Admin "
                "to approve it."
            )
        elif (hold_note := _sheet_hold_note(projection)) is not None:
            # RO14 (D-RO14-6): held by one sheet-wide hold that has no
            # answer in a row (the walk, two dates on one car, ...). The
            # tab says that hold's own sentence, not "waiting for an Admin".
            state, message = "blocked", hold_note
        else:
            state, message = "blocked", (
                "This tab cannot load yet. Nothing on it is ready to add."
            )
        out_sheets.append({
            "load_id": load_id,
            "sheet": sheet["source_sheet"],
            "status": status,
            "state": state,
            "commit_blockers": blockers,
            "rows_ready": rows_ready,
            "rows_loaded": facts,
            "rows_held": held_count,
            "rows_already_in_history": in_history,
            "rows_need_confirmation": needs_confirmation,
            "rows": table,
            "extra_columns": extra,
            "missing_optional": optional,
            "hole_rows": holes,
            "plant_texts": texts,
            "held": held,
            # T89 Part 5 (D-88-7): one event, said once, instead of 741 row
            # complaints. Offered beside the held list, which is where the
            # match screen is reached from.
            "panel_rename": rename_signals(conn, load_id, page),
            # T94 (D-94-1, D-94-3): the question each rough label asks, with
            # the long name we propose already chosen. The table renders it
            # IN the row; the client never classifies anything.
            "rough_panels": rough,
            "vehicle_count": (
                len({
                    (r.get("canonical") or {}).get("logical_vehicle_id")
                    for r in repo.vehicle_rows(conn, load_id)
                    if r["disposition"] in ("LOAD", "DUPLICATE")
                })
                if sheet.get("sheet_class") == SHEET_FILMTHICKNESS
                else sum(1 for v in sets if v.identity_complete)
            ),
            "short_vehicles": short,
            "operator_message": message,
            # T103 (D-103-1): the same answer the car's History row gives,
            # from this tab's own rows, by the one function that owns the
            # rule. Null while the tab is held: a walk nobody has read yet
            # is not a walk with or without a box.
            "film_box": (
                _film_box(film_ref, page, film_model, table)
                if is_film and state in ("ready", "loaded") else None
            ),
            # T100 (D-100-1): the one question this Film tab asks about
            # itself, filled by the code that decided the hold.
            "film_question": film_question,
            # RO18 (B3 / B4): the tab's month or date question, either domain.
            "date_question": date_question,
            # T109 (D-109-6): the row questions. One entry per label the
            # plant's live list does not hold, and the live points an answer
            # may name -- both from the server, so the screen classifies
            # nothing and offers nothing the list does not carry.
            "film_unknown_labels": film_unknown,
            "film_point_choices": film_choices,
        })

    question = None
    if all_texts:
        question = {
            "page_plant": page,
            "plant_texts": list(all_texts),
            "rows": text_rows,
            "operator_message": operator_message_for(
                "plant", ", ".join(all_texts), plant=page
            ),
        }
        checklist.append(question["operator_message"])
    optional_fields = [f for f in OPTIONAL_FIELDS if f in all_optional]
    optional_message = missing_optional_message(optional_fields)
    if optional_message:
        checklist.append(optional_message)
    if all_extra:
        checklist.append(
            f"We do not use {len(all_extra)} column(s): "
            f"{', '.join(all_extra)}. Ignore them and keep the rest?"
        )
    for item in out_sheets:
        if item["state"] in ("ready", "needs_answer", "blocked", "loaded"):
            checklist.append(f"{item['sheet']}: {item['operator_message']}")
        # T89 Part 5: it goes in the summary, which is the checklist -- a
        # reviewer reads this before the row table.
        for rename in item["panel_rename"]:
            checklist.append(f"{item['sheet']}: {rename['operator_message']}")
        # T94: said once, above the table, because the rows themselves are
        # where it is answered (D-94-3).
        if item["rows_need_confirmation"]:
            checklist.append(
                f"{item['sheet']}: "
                + (
                    # T109: a Film tab's needs-confirmation rows are point
                    # questions, not panel questions, and they are the only
                    # kind a Film tab can have (D-94-1 is a WaveScan rule).
                    (FILM_POINT_REST_WORDS if item["rows_ready"] else FILM_POINT_WORDS)
                    if item["film_unknown_labels"]
                    else NEEDS_CONFIRMATION_WORDS
                ).format(rows=item["rows_need_confirmation"])
            )
            prefilled = sum(
                1 for panel in item["rough_panels"]
                if not panel["confirmed_zone_code"]
                and panel["proposed_zone_code"]
            )
            if prefilled:
                checklist.append(
                    f"{item['sheet']}: "
                    + ACCEPT_PREFILLED_WORDS.format(count=prefilled)
                )
        if item["hole_rows"]:
            checklist.append(
                f"{item['sheet']}: {len(item['hole_rows'])} points have CF but "
                f"no LW/SW. Approve them to load without LW/SW."
            )
        for vehicle in item["short_vehicles"]:
            checklist.append(f"{item['sheet']}: {vehicle['operator_message']}")
    ready = [s for s in out_sheets if s["state"] == "ready"]
    rows_ready = sum(s["rows_ready"] for s in ready)
    held_out = sum(_held_out(s["rows"]) for s in out_sheets)
    not_stored = sum(_not_stored(s["rows"]) for s in out_sheets)
    in_history = sum(s["rows_already_in_history"] for s in out_sheets)
    needs_confirmation = sum(s["rows_need_confirmation"] for s in out_sheets)
    summary = summary_message(rows_ready, held_out, in_history, not_stored)
    # T109: a workbook can carry both kinds of row question, so each gets its
    # own count and its own sentence rather than one count under the panel
    # wording.
    film_needs = sum(
        s["rows_need_confirmation"] for s in out_sheets if s["film_unknown_labels"]
    )
    if needs_confirmation - film_needs:
        summary += " " + NEEDS_CONFIRMATION_WORDS.format(
            rows=needs_confirmation - film_needs
        )
    if film_needs:
        rest = all(s["rows_ready"] for s in out_sheets if s["film_unknown_labels"])
        summary += " " + (FILM_POINT_REST_WORDS if rest else FILM_POINT_WORDS).format(
            rows=film_needs
        )
    if any(s["state"] == "needs_answer" for s in out_sheets):
        summary += " Answer the questions below first."
    if ready:
        checklist.append(
            "Press \"Yes, load these rows\" to load every ready tab. Held rows "
            "stay on this card."
        )
    return {
        "plant_code": page,
        "file_hash": file_hash,
        "source_file": sheets[0]["source_file"],
        "sheets": out_sheets,
        "plant_question": question,
        "extra_columns": list(all_extra),
        "missing_optional": optional_fields,
        "missing_optional_message": optional_message,
        "ready_sheet_count": len(ready),
        "rows_ready": rows_ready,
        "rows_held": sum(s["rows_held"] for s in out_sheets),
        "rows_already_in_history": in_history,
        "rows_need_confirmation": needs_confirmation,
        "summary_message": summary,
        "checklist": checklist,
    }


# =====================================================================
# the answers
# =====================================================================
def ignore_columns(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    headers: list[str], note: str | None, actor: str, correlation_id: str | None,
) -> dict:
    """ADR 0013 decision 6: one Engineer confirm, then re-read without them."""
    _, sheets = _sheets(conn, plant_code, file_hash)
    alias_map = reference_repo.load_reference_data(conn).column_alias
    wanted = {normalise_header(h): h for h in headers}
    offered: dict[int, set[str]] = {}
    for sheet in sheets:
        offered[int(sheet["load_id"])] = (
            {normalise_header(h) for h in sheet.get("unreviewed_headers") or []}
            | _duplicate_header_names(sheet, alias_map)
        )
    known = set().union(*offered.values()) if offered else set()
    unknown = [wanted[k] for k in wanted if k not in known]
    if unknown:
        raise WorkbookError(
            422,
            f"{', '.join(repr(h) for h in unknown)} is not a column we do not "
            f"use on this workbook. Only an extra column, or one of two columns "
            f"that mean the same thing, can be ignored. A column we need "
            f"(date, model, colour, panel, CF) cannot. Nothing was changed.",
        )
    written = 0
    replayed: list[int] = []
    for sheet in sheets:
        mine = [k for k in wanted if k in offered[int(sheet["load_id"])]]
        for key in mine:
            _record(conn, sheet, kind=repo.KIND_IGNORE_HEADER, subject=key,
                    actor=actor, note=note, correlation_id=correlation_id)
            written += 1
        if mine and _replay_if_possible(
            ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
            reason=f"Engineer ignored column(s) {', '.join(mine)} on the worksheet",
        ):
            replayed.append(int(sheet["load_id"]))
    return {
        "decisions_written": written,
        "replayed_load_ids": replayed,
        "operator_message": (
            f"We will not use {', '.join(wanted.values())}. "
            + ("The tabs are being read again." if replayed else "")
        ).strip(),
    }


def answer_plant(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    answer: str, actor: str, correlation_id: str | None,
) -> dict:
    """ADR 0013 decision 3: this plant continues; another plant cancels."""
    plant, sheets = _sheets(conn, plant_code, file_hash)
    page = plant["plant_code"]
    chosen = workbooks_repo.resolve_plant(conn, answer)
    if chosen is None:
        raise WorkbookError(422, f"{answer!r} is not a plant we know. Nothing was changed.")
    texts_by_sheet: dict[int, list[str]] = {}
    for sheet in sheets:
        _, texts, _ = _held_facts(conn, int(sheet["load_id"]))
        if not texts:
            texts = _upload_plant_texts(conn, sheet)
        if texts:
            texts_by_sheet[int(sheet["load_id"])] = texts
    if not texts_by_sheet:
        raise WorkbookError(
            409, "There is no plant question on this workbook. Nothing was changed."
        )

    if chosen["plant_code"] == page:
        written = 0
        replayed: list[int] = []
        for sheet in sheets:
            texts = texts_by_sheet.get(int(sheet["load_id"]), [])
            for text_value in texts:
                _record(conn, sheet, kind=repo.KIND_PLANT_CONFIRM, subject=text_value,
                        actor=actor, note=f"Engineer confirmed this is {page}'s data",
                        correlation_id=correlation_id)
                written += 1
            if texts and _replay_if_possible(
                ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
                reason=f"Engineer confirmed the Plant text means {page}",
            ):
                replayed.append(int(sheet["load_id"]))
        return {
            "answer": "page_plant",
            "decisions_written": written,
            "replayed_load_ids": replayed,
            "cancelled": False,
            "open_plant": None,
            "operator_message": (
                f"These rows load as {page}. "
                + ("The tabs are being read again." if replayed else
                   "Press \"Load remaining rows\" to add them.")
            ),
        }

    other = chosen["plant_code"]
    if any(int(s["facts"]) for s in sheets):
        raise WorkbookError(
            409,
            f"Some rows of this file are already on {page}'s dashboard, so it "
            f"cannot be cancelled from here. Ask an Admin to remove the "
            f"workbook, then upload it on {other}'s page. Nothing was changed.",
        )
    result = workbooks_repo.purge_workbook(
        conn,
        plant_code=page,
        file_hash=file_hash,
        actor_user_id=actor,
        reason=(
            f"Uploaded on {page}'s page; the Engineer says it is {other}'s "
            f"data. Cancelled so it can be uploaded on {other}'s page "
            f"(ADR 0013 decision 3). No measurement had been loaded."
        ),
        correlation_id=correlation_id,
    )
    return {
        "answer": "other_plant",
        "decisions_written": 0,
        "replayed_load_ids": [],
        "cancelled": True,
        "open_plant": other,
        "operator_message": (
            f"This upload was cancelled ({len(result['load_ids'])} tab(s) "
            f"removed, nothing had loaded). Open {other}'s Upload Data page "
            f"and upload the file there."
        ),
    }


def approve_holes(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, source_rows: list[int], note: str | None, actor: str,
    correlation_id: str | None,
) -> dict:
    """ADR 0013 decision 1: named points may load without LW/SW."""
    _, sheets = _sheets(conn, plant_code, file_hash)
    sheet = next((s for s in sheets if int(s["load_id"]) == load_id), None)
    if sheet is None:
        raise WorkbookError(404, f"Tab {load_id} is not part of this workbook.")
    holes, _, _ = _held_facts(conn, load_id)
    wrong = [r for r in source_rows if r not in holes]
    if wrong:
        raise WorkbookError(
            422,
            f"Row(s) {', '.join(map(str, wrong[:20]))} are not points with CF "
            f"and no LW/SW on this tab. Only those can be approved. Nothing "
            f"was changed.",
        )
    for row in source_rows:
        _record(conn, sheet, kind=repo.KIND_HOLE_APPROVAL, subject=str(row),
                actor=actor, note=note, correlation_id=correlation_id)
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason=f"Engineer approved {len(source_rows)} point(s) without LW/SW",
    )
    return {
        "decisions_written": len(source_rows),
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            f"{len(source_rows)} point(s) will load without LW/SW. "
            + ("The tab is being read again." if replayed else
               "Press \"Load remaining rows\" to add them.")
        ),
    }


def confirm_panels(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, pairs: list[dict], note: str | None, actor: str,
    correlation_id: str | None,
) -> dict:
    """T94 Part 4 (D-94-3, D-94-4, D-94-6): which panel a rough label is.

    One answer per rough spelling, or every pre-filled one at once -- the
    same call either way, because "accept all" is the same decision made
    about more rows and must leave the same evidence behind.

    What is checked, and nothing else is:

    * the tab belongs to this workbook;
    * the spelling really is **rough on this tab** -- a specific label is
      not asked about here and so cannot be answered here, which keeps the
      D-94-1 classification the single gate it is;
    * the panel is one this spelling may be answered with: a canonical
      position of its model, offered by `panel_pool` (D-89-6). A panel the
      list does not offer is refused with the list, not stored and found to
      be wrong later.

    Then the answer is a `worksheet_decision` row and an `audit_event`, and
    the tab is re-read from the stored bytes. The replay is what makes
    ``wavescan.checkzone`` the long name (D-94-4): the cleaner resolves this
    spelling to the confirmed panel for **this batch** and stores
    ``src_zone_text`` as the file's own spelling, untouched. Nothing is
    written to `ref_plant_zone_map`, so the answer cannot travel to next
    month's upload (D-90-3, D-91-3).

    Nothing auto-applies: this function is only ever reached because a
    person pressed Confirm (D-94-6).
    """
    _, sheets = _sheets(conn, plant_code, file_hash)
    sheet = next((s for s in sheets if int(s["load_id"]) == load_id), None)
    if sheet is None:
        raise WorkbookError(404, f"Tab {load_id} is not part of this workbook.")
    # Keyed by spelling, **every model it is rough on** (T96). One sheet
    # carries two models and the owner's August file writes the same 32
    # spellings for both: keeping one item per spelling answered one model
    # and left the other's rows asking with no way to answer them, because
    # a second identical call recorded the same model again.
    rough: dict[str, list[dict]] = {}
    for item in _rough_panels(conn, sheet, plant_code):
        rough.setdefault(normalise_alias(item["raw_zone_text"]), []).append(item)
    if not rough:
        raise WorkbookError(
            409,
            "No panel name on this tab needs confirming. A name that says "
            "which panel it is loads without being asked about. Nothing was "
            "changed.",
        )
    seen: dict[str, str] = {}
    for pair in pairs:
        raw = str(pair["raw_zone_text"]).strip()
        zone = str(pair["zone_code"]).strip()
        key = normalise_alias(raw)
        asked = rough.get(key)
        if not asked:
            raise WorkbookError(
                422,
                f"{raw!r} is not a panel name this tab is asking about. The "
                f"names it is asking about are: "
                f"{', '.join(sorted({item['raw_zone_text'] for items in rough.values() for item in items}))}. "
                f"Nothing was changed.",
            )
        for item in asked:
            if zone not in item["choosable"]:
                raise WorkbookError(
                    422,
                    f"{zone!r} is not a panel {raw!r} can be confirmed as on "
                    f"{item['model_code']} at {plant_code}. Choose one of: "
                    f"{', '.join(item['choosable']) or 'none -- this model has no panel left to offer'}. "
                    f"Nothing was changed.",
                )
        if key in seen and seen[key] != zone:
            raise WorkbookError(
                422,
                f"This answer names {raw!r} as both {seen[key]} and {zone}. "
                f"One panel name is one panel. Nothing was changed.",
            )
        seen[key] = zone

    written = 0
    for pair in pairs:
        raw = str(pair["raw_zone_text"]).strip()
        zone = str(pair["zone_code"]).strip()
        # One decision per model this spelling is rough on, so a sheet that
        # writes it for two models is answered for both by one click (T96).
        for item in rough[normalise_alias(raw)]:
            _record(
                conn, sheet, kind=repo.KIND_PANEL_CONFIRM,
                subject=repo.panel_pair_subject(
                    raw, zone, item["model_code"]
                ),
                actor=actor,
                note=note or (
                    f"Engineer confirmed {raw} is {zone} on this upload "
                    f"(T94, D-94-4). Confirmed for this batch only."
                ),
                correlation_id=correlation_id,
            )
            written += 1
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason=(
            f"Engineer confirmed {written} rough panel name(s) on the "
            f"worksheet (T94)"
        ),
    )
    confirmed_words = ", ".join(
        f"{str(pair['raw_zone_text']).strip()} is "
        f"{str(pair['zone_code']).strip()}"
        for pair in pairs
    )
    return {
        "decisions_written": written,
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            f"{confirmed_words}. "
            + ("The tab is being read again; these readings will load under "
               "the long name." if replayed else
               "Press \"Load remaining matched rows\" to add them.")
        ),
    }



# =====================================================================
# T99: the uploader's answers about a Film sheet
# =====================================================================
def _film_sheet(conn: Connection, plant_code: str, file_hash: str, load_id: int,
                *, reason: str | frozenset[str]) -> dict:
    """The tab of this workbook that is held for ``reason``.

    Refuses a tab that is not asking the question, the same way
    `confirm_panels` refuses a panel name the tab is not asking about: an
    answer to a question nobody asked is a row in `worksheet_decision` that
    changes nothing and explains nothing.
    """
    _, sheets = _sheets(conn, plant_code, file_hash)
    sheet = next((s for s in sheets if int(s["load_id"]) == load_id), None)
    if sheet is None:
        raise WorkbookError(404, f"Tab {load_id} is not part of this workbook.")
    held = {r["reason"] for r in repo.held_rows(conn, load_id)}
    # RO17: ``reason`` may be a set of reasons, any one of which will do.
    wanted = {reason} if isinstance(reason, str) else set(reason)
    if not wanted & held:
        raise WorkbookError(
            409,
            f"Tab {load_id} is not held for {' or '.join(sorted(wanted))}. "
            f"It is held for: "
            f"{', '.join(sorted(held)) or 'nothing'}. Nothing was changed.",
        )
    return sheet


def _film_hold_detail(conn: Connection, load_id: int, reason: str) -> str:
    """The sentence the parse wrote for this sheet-wide hold."""
    for row in repo.held_rows(conn, load_id):
        if row["reason"] == reason and row.get("detail"):
            return str(row["detail"])
    return ""


def answer_film_model(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, model_code: str, note: str | None, actor: str,
    correlation_id: str | None,
) -> dict:
    """T99 (D-99-11): the sheet names two models; the uploader picks one.

    The Job Number says one truck and the file name says another, and the
    platform has no way to know which is right -- so it asks, and it asks
    the person who has the file in front of them (D-99-4: roles are ignored
    for now, guardrails come later). Only a model this **plant** has a Film
    list for may be chosen (D-78-32): a model the plant does not walk is a
    new claim, not an answer, and it is refused with the list.
    """
    sheet = _film_sheet(
        conn, plant_code, file_hash, load_id, reason=REASON_FILM_MODEL_CONFLICT,
    )
    film = film_repo.load_film_reference(conn)
    offered = plant_film_vocabulary(sheet["plant_code"], film.model_alias)
    chosen = str(model_code).strip()
    if chosen not in offered:
        raise WorkbookError(
            422,
            f"{chosen!r} is not a FilmThickness model "
            f"{sheet['plant_code']} has a point list for. Choose one of: "
            f"{', '.join(offered) or 'none'}. Nothing was changed.",
        )
    _record(
        conn, sheet, kind=repo.KIND_FILM_MODEL_CONFLICT, subject=chosen,
        actor=actor,
        note=note or (
            f"The uploader chose {chosen} for this sheet, which named two "
            f"models (T99, D-99-11). {_film_hold_detail(conn, load_id, REASON_FILM_MODEL_CONFLICT)}"
        ).strip(),
        correlation_id=correlation_id,
    )
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason=f"the uploader chose {chosen} for a sheet naming two models (T99)",
    )
    return {
        "decisions_written": 1,
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            f"This sheet will load as {chosen}. "
            + ("The tab is being read again." if replayed else
               'Press "Load remaining matched rows" to add them.')
        ),
    }


def answer_film_job(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, note: str | None, actor: str, correlation_id: str | None,
) -> dict:
    """T99 (D-99-10): "load as written" for an unusual Job Number.

    The Job Number is not the shape this plant writes. It may still be the
    real number of a real truck -- a hand-typed one, a trial build -- so the
    uploader may say so, and it then loads as its own vehicle under exactly
    that number. Nothing is corrected and nothing is invented; the answer
    says "read it as it stands".
    """
    sheet = _film_sheet(
        conn, plant_code, file_hash, load_id, reason=REASON_FILM_JOB_UNUSUAL,
    )
    detail = _film_hold_detail(conn, load_id, REASON_FILM_JOB_UNUSUAL)
    _record(
        conn, sheet, kind=repo.KIND_FILM_JOB_UNUSUAL,
        # The subject is the sentence the parse wrote, which names the Job
        # Number it read and the shape it was measured against. Storing the
        # sentence rather than re-reading the cell keeps the record and the
        # parse one statement.
        subject=detail or f"load {load_id} Job Number as written",
        actor=actor,
        note=note or (
            f"The uploader said to load this sheet's Job Number as written "
            f"(T99, D-99-10)."
        ),
        correlation_id=correlation_id,
    )
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason="the uploader read an unusual Job Number as written (T99)",
    )
    return {
        "decisions_written": 1,
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            "The Job Number will load as written, as its own vehicle. "
            + ("The tab is being read again." if replayed else
               'Press "Load remaining matched rows" to add them.')
        ),
    }


def answer_month(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, month: str, note: str | None, actor: str,
    correlation_id: str | None,
) -> dict:
    """RO18 (B4, RO09). "These cars were measured in <month>."

    The sheet has no date anywhere. A person names the month -- the file name
    only suggests one -- and every row is stored on the 1st of it with
    ``date_is_month_only``. Either domain.
    """
    sheet = _film_sheet(conn, plant_code, file_hash, load_id, reason=REASON_MONTH_UNKNOWN)
    first = parse_month_answer(month)
    if first is None:
        raise WorkbookError(
            422, f"{month!r} is not a month; write it as YYYY-MM. Nothing was changed."
        )
    subject = f"{first:%Y-%m}"
    _record(
        conn, sheet, kind=repo.KIND_MONTH_ONLY, subject=subject, actor=actor,
        note=note or (
            f"RO18 (B4): the uploader said the cars of this undated sheet were "
            f"measured in {first:%B %Y}."
        ),
        correlation_id=correlation_id,
    )
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason=f"the uploader named {first:%B %Y} for a sheet with no date (RO18)",
    )
    return {
        "decisions_written": 1,
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            f"These cars are filed under {first:%B %Y}, day not recorded. "
            + ("The tab is being read again." if replayed else
               'Press "Load remaining matched rows" to add them.')
        ),
    }


def answer_film_date(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, choice: str, note: str | None, actor: str,
    correlation_id: str | None,
) -> dict:
    """RO18 (B3). Which date is right: the sheet's, or the file name's?"""
    sheet = _film_sheet(
        conn, plant_code, file_hash, load_id, reason=REASON_FILM_DATE_DISAGREES,
    )
    if choice not in repo.DATE_CHOICES:
        raise WorkbookError(
            422, f"{choice!r} is not an answer; say sheet or file_name. Nothing was changed."
        )
    detail = _film_hold_detail(conn, load_id, REASON_FILM_DATE_DISAGREES)
    _record(
        conn, sheet, kind=repo.KIND_FILM_DATE_CHOICE, subject=choice, actor=actor,
        note=note or f"RO18 (B3): the uploader chose the {choice.replace('_', ' ')}'s date. {detail}".strip(),
        correlation_id=correlation_id,
    )
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason=f"the uploader chose the {choice.replace('_', ' ')}'s date (RO18)",
    )
    return {
        "decisions_written": 1,
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            f"This sheet loads with the {choice.replace('_', ' ')}'s date. "
            + ("The tab is being read again." if replayed else
               'Press "Load remaining matched rows" to add them.')
        ),
    }


def confirm_film_walk(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, points: list[dict], note: str | None, actor: str,
    correlation_id: str | None,
) -> dict:
    """T99 (D-99-14): the uploader confirms names appended to the walk.

    The sheet walked past the end of the list we know. That is the one kind
    of change a confirm may settle: the new names come **after** the last
    known point, so no existing point changes its number or its place on the
    truck. A walk that inserts, reorders or renumbers inside the known list
    is refused here with the sentence that says why -- with number-and-name
    point identity (D-99-1) a renumbered walk files old names onto different
    spots, and no confirmation can make that safe.

    Each confirmed name becomes a real point of this plant's list, with its
    own `film_point_setting` row saying whether it counts and whether it is
    Horizontal or Vertical, an `audit_event`, and a `worksheet_decision` row
    naming who said so. Then the tab is re-read from the stored bytes and
    loads through the one ingest service -- the appended points are ordinary
    points of the walk by then, so nothing special happens at load time.
    """
    sheet = _film_sheet(
        conn, plant_code, file_hash, load_id, reason=REASON_FILM_WALK_UNKNOWN,
    )
    verdict, model = ingest.film_walk_question(conn, load_id)
    if verdict is None or model is None:
        raise WorkbookError(
            409,
            f"Tab {load_id} does not re-read as a held walk right now. "
            f"Nothing was changed.",
        )
    if not verdict.confirmable:
        raise WorkbookError(409, verdict.detail + " Nothing was changed.")
    appended = [normalise_location(p) for p in verdict.appended]
    asked = {
        normalise_location(str(p.get("point_code") or "")): p for p in points
    }
    missing = [p for p in verdict.appended if normalise_location(p) not in asked]
    extra = [key for key in asked if key not in appended]
    if missing or extra:
        raise WorkbookError(
            422,
            f"Confirming an appended walk answers every new name and nothing "
            f"else. Still unanswered: {', '.join(missing) or 'none'}. Not a "
            f"new name on this sheet: {', '.join(sorted(extra)) or 'none'}. "
            f"Nothing was changed.",
        )
    for key in appended:
        orientation = str(asked[key].get("orientation") or "").strip().upper()
        if orientation not in ("H", "V"):
            raise WorkbookError(
                422,
                f"{key} needs Horizontal or Vertical (H or V), not "
                f"{orientation or '(blank)'}. The rule pre-fills Hood, Roof "
                f"and Box-floor as H and everything else as V; a word the "
                f"rule does not know has to be chosen. Nothing was changed.",
            )

    point_labels.lock_list(conn, "film", sheet["plant_code"], model)
    added = film_repo.add_walk_points(
        conn, plant_code=sheet["plant_code"], model_code=model, points=appended,
    )
    # RO17-FIX (D-RO17F-1): every new live point gets its first label row.
    for code, _ in added:
        point_labels.insert_label(
            conn, "film", sheet["plant_code"], model, code, code,
            reason="walk confirm: the code", actor=actor,
        )
    written = film_repo.insert_setting(
        conn, plant_code=sheet["plant_code"], model_code=model,
        rows=[
            (code, bool(asked[code].get("counted", True)),
             str(asked[code]["orientation"]).strip().upper())
            for code, _ in added
        ],
        reason=note or (
            f"T99 (D-99-14): confirmed on the worksheet of load {load_id} as "
            f"a new point appended to {sheet['plant_code']}'s {model} walk"
        ),
        actor=actor,
    )
    if added:
        point_walk.record_membership(conn, sheet["plant_code"], model, "FILMTHICKNESS",
                                     actor=actor, reason=note or "Worksheet appended points",
                                     correlation_id=correlation_id)
    for code, point_no in added:
        _record(
            conn, sheet, kind=repo.KIND_FILM_WALK_CONFIRM,
            subject=repo.film_point_subject(
                code, bool(asked[code].get("counted", True)),
                str(asked[code]["orientation"]).strip().upper(),
            ),
            actor=actor,
            note=note or (
                f"The uploader confirmed {code} as point {point_no} of "
                f"{sheet['plant_code']}'s {model} walk (T99, D-99-14)."
            ),
            correlation_id=correlation_id,
        )
    audit.record(
        conn,
        action="catalogue.plant_film_point.confirm_appended",
        entity_type="ref_plant_film_point",
        entity_id=sheet["plant_code"],
        actor_user_id=actor,
        after={
            "plant_code": sheet["plant_code"], "model_code": model,
            "load_id": load_id,
            "points": [{"point_code": c, "point_no": n} for c, n in added],
            "setting_rows": written,
            "owner_decision": "T99 D-99-14",
        },
        correlation_id=correlation_id,
    )
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason=(
            f"the uploader confirmed {len(added)} point(s) appended to the "
            f"{model} walk (T99)"
        ),
    )
    return {
        "decisions_written": len(added),
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            f"{', '.join(c for c, _ in added)} are now point(s) of "
            f"{sheet['plant_code']}'s {model} walk. "
            + ("The tab is being read again." if replayed else
               'Press "Load remaining matched rows" to add them.')
        ),
    }


def film_point_setting(conn: Connection, plant_code: str, model_code: str) -> dict:
    """T99 (D-99-4): the remembered point setting of one plant x model."""
    plant = resolve_plant(conn, plant_code)
    film = film_repo.load_film_reference(conn)
    model = str(model_code).strip()
    if model not in plant_film_vocabulary(plant["plant_code"], film.model_alias):
        raise WorkbookError(
            404,
            f"{model!r} is not a FilmThickness model {plant['plant_code']} "
            f"has a point list for.",
        )
    page = plant["plant_code"]
    items = film_repo.point_setting(conn, page, model)
    if not items and model not in _film_offered(conn, page):
        # RO17 (D-RO17-10): an offered model with no list yet reads empty
        # (its first point starts one); one not offered stays a 404.
        raise WorkbookError(
            404,
            f"{page} has no live FilmThickness point list for {model!r} and "
            f"does not offer it.",
        )
    retired = film_repo.retired_points(conn, page, model)
    labels = point_labels.current_labels(conn, "film", page, model)
    for point in (*items, *retired):
        point["label"] = labels.get(point["point_code"]) or point["point_code"]
    return {
        "plant_code": page,
        "model_code": model,
        "has_setting": film.has_setting(page, model),
        "items": items,
        # T109 (D-109-4, section 3.7): what this list used to walk, so the
        # screen that retired a point can still say when it went and why.
        "retired_items": retired,
        # RO17 (D-RO17-12): the known tail, live and retired.
        "tail_labels": film_repo.tail_labels(conn, page, model),
    }


def change_film_point_setting(
    conn: Connection, plant_code: str, model_code: str, *,
    points: list[dict], reason: str, actor: str, correlation_id: str | None,
) -> dict:
    """T99 (D-99-4): change which points count, and their Hor / Ver.

    Append-only: each answer is a **new** row, never an UPDATE of the one
    before it, and the latest row per point is what the dashboard reads. The
    older rows stay as the record of what somebody said and why. Changing
    this changes past months' Hor / Ver -- that is the owner's decision, by
    design, which is why a reason is required and an `audit_event` is written
    in the same transaction.

    Anyone who can upload may do it (owner, 2026-10-10: "ignore the role ...
    everyone can do everything, I will set guardrails in the future"), so the
    route depends on the upload role and nothing here checks a second one.
    """
    plant = resolve_plant(conn, plant_code)
    page = plant["plant_code"]
    film = film_repo.load_film_reference(conn)
    model = str(model_code).strip()
    live = {p["point_code"] for p in film_repo.point_setting(conn, page, model)}
    if not live:
        raise WorkbookError(
            404,
            f"{page} has no live FilmThickness point list for {model!r}, so "
            f"there is no setting to change.",
        )
    rows: list[tuple[str, bool, str]] = []
    for item in points:
        code = str(item.get("point_code") or "").strip()
        if code not in live:
            raise WorkbookError(
                422,
                f"{code!r} is not a live point of {page}'s {model} list. "
                f"Nothing was changed.",
            )
        orientation = str(item.get("orientation") or "").strip().upper()
        if orientation not in ("H", "V"):
            raise WorkbookError(
                422,
                f"{code} needs Horizontal or Vertical (H or V), not "
                f"{orientation or '(blank)'}. Nothing was changed.",
            )
        rows.append((code, bool(item.get("counted", True)), orientation))
    if not rows:
        raise WorkbookError(422, "Name at least one point. Nothing was changed.")
    written = film_repo.insert_setting(
        conn, plant_code=page, model_code=model, rows=rows,
        reason=reason, actor=actor,
    )
    audit.record(
        conn,
        action="catalogue.film_point_setting.change",
        entity_type="film_point_setting",
        entity_id=f"{page}:{model}",
        actor_user_id=actor,
        after={
            "plant_code": page, "model_code": model, "reason": reason,
            "rows": [
                {"point_code": c, "counted": n, "orientation": o}
                for c, n, o in rows
            ],
            "owner_decision": "T99 D-99-4",
        },
        correlation_id=correlation_id,
    )
    return {
        "rows_written": written,
        "operator_message": (
            f"{written} point(s) of {page}'s {model} list changed. The "
            f"dashboard's Horizontal and Vertical boxes use the new setting "
            f"from now on, for every month."
        ),
    }


def _point_check_list(
    conn: Connection, plant_code: str, model_code: str, *,
    first: bool = False,
) -> tuple[dict, str, list[dict]]:
    """T109. The plant, the model and its live list, or a refusal.

    One place, so every Point Check write refuses the same way and reads the
    same list -- the one Point Check shows -- after taking the list's RO17
    lock. RO17 (D-RO17-11): the list is editable with or without
    `film_point_setting`; the T99 *rules* still need one. ``first``
    (D-RO17-10): an offered Film model with no live list may start one.
    """
    plant = resolve_plant(conn, plant_code)
    page = plant["plant_code"]
    model = str(model_code).strip()
    point_labels.lock_list(conn, "film", page, model)
    live = film_repo.point_setting(conn, page, model)
    if not live and not (first and model in _film_offered(conn, page)):
        raise WorkbookError(
            404,
            f"{page} has no live FilmThickness point list for {model!r}, so "
            f"there is nothing to change.",
        )
    return plant, model, live


def _replay_sheets_waiting_on(
    conn: Connection, ingest: IngestService, page: str, model: str,
    names: set[str], *, actor: str, correlation_id: str | None, why: str,
) -> list[int]:
    """RO19 follow-up: re-read the stored sheets held asking about this point.

    A sheet held because it wrote a point the list did not have used to stay
    held after the point was added, until someone answered a meaningless
    self-alias in its row. Now the add (or restore) re-reads every replayable
    sheet of this plant and model with a held row carrying one of ``names``
    (the point's code and label), through the one ingest service. Both hold
    shapes count: a row asking about the label, and a walk the unknown name
    broke (every row of it held, each with its own label).
    """
    waiting = _FILM_POINT_ASKED | {REASON_FILM_WALK_UNKNOWN}
    candidates = conn.execute(
        text(
            "SELECT DISTINCT b.load_id, b.file_hash FROM load_batch b "
            "JOIN stg_review_row r ON r.load_id = b.load_id "
            "WHERE b.plant_code = :p AND b.domain = 'FILMTHICKNESS' "
            "AND b.status = ANY(:statuses) AND r.reason = ANY(:reasons) "
            "ORDER BY b.load_id"
        ),
        {"p": page, "statuses": list(batches.REPLAYABLE_STATUSES),
         "reasons": sorted(waiting)},
    ).all()
    replayed: list[int] = []
    for load_id, file_hash in candidates:
        projection = repo.preview_rows(conn, int(load_id))
        if _film_model_of(projection) != model:
            continue
        if not any(
            row.get("reason") in waiting
            and normalise_location((row.get("canonical") or {}).get("offending_value") or "") in names
            for row in projection
        ):
            continue
        _, sheets = _sheets(conn, page, str(file_hash).strip())
        sheet = next((x for x in sheets if int(x["load_id"]) == int(load_id)), None)
        if sheet and _replay_if_possible(ingest, conn, sheet, actor=actor,
                                         reason=why, correlation_id=correlation_id):
            replayed.append(int(load_id))
    return replayed


def _waiting_message(replayed: list[int]) -> str:
    if not replayed:
        return ""
    return (f" {len(replayed)} stored sheet{'s' if len(replayed) != 1 else ''} "
            f"that waited on it {'are' if len(replayed) != 1 else 'is'} being read again.")


def add_film_point(
    conn: Connection, plant_code: str, model_code: str, *,
    point_code: str, counted: bool, orientation: str | None, reason: str,
    actor: str, correlation_id: str | None, place_after: str | None = None,
    ingest: IngestService | None = None,
) -> dict:
    """T109 (D-109-5). One new point on this plant's list for the model.

    RO19: use the name's digits when that number is free, otherwise allocate
    the next free number. Existing identities never move. Measuring order
    is separate: append by default, or place after the chosen live point.

    Horizontal / Vertical is pre-filled from the list's **own** points of the
    same panel word (`proposed_orientation`, the T100 rule read off the list
    rather than a second copy of migration 0033's); where the list cannot
    propose one, the person has to choose and this refuses until they do.

    Every added point is **extra** (D-109-3) and counted unless the person
    says otherwise. The writes are a catalogue name if it is new, the list
    row, one `film_point_setting` row and an `audit_event`, in one
    transaction. Nothing already on the list is touched.

    RO17 (D-RO17-11): a list **without** settings takes the point too, but
    writes no `film_point_setting` row (one would switch the T99 rules on):
    the H / V goes on the list row and ``counted`` is not used. Every add
    also writes the point's first label, the text as typed (D-RO17-7), and
    an offered model with no list may start one here (D-RO17-10).
    """
    plant, model, live = _point_check_list(
        conn, plant_code, model_code, first=True
    )
    page = plant["plant_code"]
    ruled = film_repo.load_film_reference(conn).has_setting(page, model)
    typed = str(point_code or "").strip()
    code = normalise_location(point_code)
    if not code:
        raise WorkbookError(
            422, "Name the point. Nothing was changed."
        )
    number = point_no_of(code)
    if number is None:
        raise WorkbookError(
            422,
            f"{code!r} starts with no point number. A Film point is its "
            f"number and its name together (D-99-1), as the file writes it "
            f"-- 099TGATEIN, not TGATEIN. Nothing was changed.",
        )
    existing = film_repo.point_row(conn, page, model, code)
    if existing is not None:
        raise WorkbookError(
            409,
            f"{code} is already on {page}'s {model} list"
            + (
                f" as point {existing['point_no']}."
                if existing["retired_at"] is None else
                f", retired on {str(existing['retired_at'])[:10]}: "
                f"{existing['retired_reason']}. Restore it instead."
            )
            + " Nothing was changed.",
        )
    number = film_repo.free_point_no(conn, page, model, number)
    after = normalise_location(place_after) if place_after is not None else None
    if after is not None and after not in {p["point_code"] for p in live}:
        raise WorkbookError(422, "Place the new point after a live point of this list. Nothing was changed.")
    chosen = str(orientation or "").strip().upper()
    if not chosen:
        chosen = proposed_orientation(
            code, {p["point_code"]: p["orientation"] for p in live}
        ) or ""
    if chosen not in ("H", "V"):
        raise WorkbookError(
            422,
            f"{code} needs Horizontal or Vertical (H or V). "
            f"{page}'s {model} list has no point of that name yet, so nobody "
            f"can propose one for you -- choose it. Nothing was changed.",
        )
    clash = point_labels.clash(conn, "film", page, model, typed, for_code=code)
    if clash:
        raise WorkbookError(409, f"{clash} Nothing was changed.")
    film_repo.add_point(
        conn, plant_code=page, model_code=model, point_code=code,
        point_no=number,
        note=f"T109 (D-109-5): added on Point Check -- {reason}",
        orientation=None if ruled else chosen,
    )
    if ruled:
        film_repo.insert_setting(
            conn, plant_code=page, model_code=model,
            rows=[(code, bool(counted), chosen)],
            reason=reason, actor=actor,
        )
    point_labels.insert_label(
        conn, "film", page, model, code, typed,
        reason=f"added on Point Check -- {reason}", actor=actor or None,
    )
    point_walk.record_membership(conn, page, model, "FILMTHICKNESS", added_code=code,
                                 place_after=after, actor=actor, reason=reason,
                                 correlation_id=correlation_id)
    audit.record(
        conn,
        action="catalogue.plant_film_point.add",
        entity_type="ref_plant_film_point",
        entity_id=f"{page}:{model}:{code}",
        actor_user_id=actor,
        after={
            "plant_code": page, "model_code": model, "point_code": code,
            "point_no": number,
            "counted": bool(counted) if ruled else None,
            "orientation": chosen, "is_extra": True, "reason": reason,
            "label": typed, "has_setting": ruled, "first_point": not live,
            "place_after": after,
            "owner_decision": "T109 D-109-5; RO17 D-RO17-7/-10/-11",
        },
        correlation_id=correlation_id,
    )
    if ruled:
        message = (
            f"{code} is now point {number} of {page}'s {model} walk, "
            f"{'counted' if counted else 'not counted'}, {chosen}, tagged as "
            f"an extra point. A file that writes it will load it from now on."
        )
    else:
        message = (
            f"{code} is now point {number} of {page}'s {model} list, {chosen}, "
            f"tagged as an extra point. A file that writes it will load it "
            f"from now on. The point rules are not on for this list, so "
            f"nothing is counted or checked by walk order."
        )
    if not live:
        message += (
            f" This is the first point of the list: from now on uploads of "
            f"{model} at {page} load only the points on this list."
        )
    replayed = [] if ingest is None else _replay_sheets_waiting_on(
        conn, ingest, page, model, {code, normalise_location(typed)},
        actor=actor, correlation_id=correlation_id,
        why=f"{code} was added to {page}'s {model} list on Point Check",
    )
    return {
        "point_code": code,
        "point_no": number,
        "label": typed,
        "operator_message": message + _waiting_message(replayed),
        "replayed_load_ids": replayed,
    }


def retire_film_point(
    conn: Connection, plant_code: str, model_code: str, *,
    point_code: str, reason: str, actor: str, correlation_id: str | None,
) -> dict:
    """T109 (D-109-4). Take a point off the live list, keeping everything.

    Retire means "stop using this point", never "forget it". The row stays
    with the reason and the time; the readings every car already has on it
    stay in History, tagged `retired`; they stop feeding the dashboard, for
    every month; and a car measured before the retirement does **not** turn
    "incomplete", because both sides of its completeness count live points
    only (section 3.3).

    A later upload that writes the retired label is asked about in its row
    (D-109-6) -- the label is simply not a point of the list any more.

    The only write is `retired_at` + `retired_reason`, which is the only
    UPDATE revision 0035 grants the application on this table (D-109-9).
    RO17: works with or without settings (D-RO17-11), never on the last live
    point (D-RO17-8), and `restore_film_point` undoes it (D-RO17-9).
    """
    plant, model, live = _point_check_list(conn, plant_code, model_code)
    page = plant["plant_code"]
    code = normalise_location(point_code)
    if code not in {p["point_code"] for p in live}:
        raise WorkbookError(
            409,
            f"{code or '(blank)'} is not a live point of {page}'s {model} "
            f"list, so there is nothing to retire. Nothing was changed.",
        )
    if len(live) == 1:
        # A plant x model with no live point stops being read as a list
        # (`load_film_reference` builds the gold from live rows only), and
        # the cleaner would fall back to the model-wide catalogue.
        raise WorkbookError(
            409,
            f"{code} is the last live point of {page}'s {model} list. A list "
            f"with no live point is no list at all, and uploads would fall "
            f"back to the model-wide catalogue. Nothing was changed.",
        )
    why = f"T109 (D-109-4): retired on Point Check -- {reason}"
    retired = film_repo.retire_point(
        conn, plant_code=page, model_code=model, point_code=code, reason=why,
    )
    if retired != 1:
        raise WorkbookError(
            409,
            f"{code} was not retired: {retired} row(s) matched. It may have "
            f"been retired by somebody else a moment ago. Nothing was changed.",
        )
    audit.record(
        conn,
        action="catalogue.plant_film_point.retire",
        entity_type="ref_plant_film_point",
        entity_id=f"{page}:{model}:{code}",
        actor_user_id=actor,
        after={
            "plant_code": page, "model_code": model, "point_code": code,
            "retired_reason": why, "owner_decision": "T109 D-109-4",
        },
        correlation_id=correlation_id,
    )
    return {
        "point_code": code,
        "point_no": next(
            p["point_no"] for p in live if p["point_code"] == code
        ),
        "label": point_labels.current_labels(conn, "film", page, model).get(code)
        or code,
        "operator_message": (
            f"{code} is off {page}'s {model} walk. It stops counting on the "
            f"dashboard for every month; the readings cars already have on it "
            f"stay in History, marked retired; and no car becomes incomplete "
            f"because of it. A file that writes {code} again will ask which "
            f"point it is."
        ),
    }


def restore_film_point(
    conn: Connection, plant_code: str, model_code: str, *,
    point_code: str, reason: str, actor: str, correlation_id: str | None,
    ingest: IngestService | None = None,
) -> dict:
    """RO17 (D-RO17-9). Put a retired point back on the live list.

    The write clears ``retired_at`` + ``retired_reason`` -- the two columns
    `app_rw` may UPDATE -- so the point walks again at the number it always
    had, under the code its readings already carry. Another live point may
    hold that number too (RO19); its stable number stays put.
    Refused when its code or current label now names another point
    of the list (D-RO17-4). A point with no label row gets one equal to its
    code. Works with or without `film_point_setting` (D-RO17-11).
    """
    plant, model, _ = _point_check_list(
        conn, plant_code, model_code, first=True
    )
    page = plant["plant_code"]
    code = normalise_location(point_code)
    row = film_repo.point_row(conn, page, model, code) if code else None
    if row is None:
        raise WorkbookError(
            404,
            f"{code or '(blank)'} is not a point of {page}'s {model} list, so "
            f"there is nothing to restore. Nothing was changed.",
        )
    number = row["point_no"]
    if row["retired_at"] is None:
        raise WorkbookError(
            409,
            f"{code} is already a live point of {page}'s {model} list, as "
            f"point {number}. Nothing was changed.",
        )
    label = point_labels.current_labels(conn, "film", page, model).get(code) or code
    for word in dict.fromkeys((code, label)):
        clash = point_labels.clash(conn, "film", page, model, word, for_code=code)
        if clash:
            raise WorkbookError(409, f"{clash} Nothing was changed.")
    if film_repo.restore_point(
        conn, plant_code=page, model_code=model, point_code=code,
    ) != 1:
        raise WorkbookError(
            409,
            f"{code} was not restored: it may have been restored by somebody "
            f"else a moment ago. Nothing was changed.",
        )
    if not film_repo.has_point_label(conn, page, model, code):
        point_labels.insert_label(
            conn, "film", page, model, code, code,
            reason="restore: the code", actor=actor or None,
        )
    point_walk.record_membership(conn, page, model, "FILMTHICKNESS", actor=actor,
                                 reason=reason, correlation_id=correlation_id)
    audit.record(
        conn,
        action="catalogue.plant_film_point.restore",
        entity_type="ref_plant_film_point",
        entity_id=f"{page}:{model}:{code}",
        actor_user_id=actor,
        before={"retired_at": str(row["retired_at"]),
                "retired_reason": str(row["retired_reason"])[:300]},
        after={
            "plant_code": page, "model_code": model, "point_code": code,
            "point_no": number, "label": label, "reason": reason,
            "owner_decision": "RO17 D-RO17-9",
        },
        correlation_id=correlation_id,
    )
    replayed = [] if ingest is None else _replay_sheets_waiting_on(
        conn, ingest, page, model, {code, normalise_location(label)},
        actor=actor, correlation_id=correlation_id,
        why=f"{code} was restored on {page}'s {model} list on Point Check",
    )
    return {
        "point_code": code,
        "point_no": number,
        "label": label,
        "operator_message": (
            f"{code} is back on {page}'s {model} walk as point {number}. A "
            f"file that writes it loads it again from now on, and the readings "
            f"cars already have on it count again."
        ) + _waiting_message(replayed),
        "replayed_load_ids": replayed,
    }


def _tail_label_row(
    conn: Connection, plant: str, model: str, label_norm: str
) -> dict | None:
    return next(
        (t for t in film_repo.tail_labels(conn, plant, model)
         if t["label_norm"] == label_norm),
        None,
    )


def add_film_tail_label(
    conn: Connection, plant_code: str, model_code: str, *,
    label: str, reason: str, actor: str, correlation_id: str | None,
) -> dict:
    """RO17 (D-RO17-12). Admin: a label this walk writes that is no point.

    The cleaner skips a tail label before it resolves a point (D-99-6), so a
    spelling that names a live point today is refused: its readings would
    vanish. A retired tail label is put back by clearing its two retire
    columns (the key is plant x model x label); otherwise one INSERT.
    """
    plant, model, _ = _point_check_list(conn, plant_code, model_code)
    page = plant["plant_code"]
    norm = normalise_location(label)
    if not norm:
        raise WorkbookError(422, "Name the tail label. Nothing was changed.")
    existing = _tail_label_row(conn, page, model, norm)
    if any(t["label_norm"] == norm for t in film_repo.tail_labels(
        conn, page, model, not_a_point=True,
    )):
        raise WorkbookError(
            409,
            f"{norm} is an uploader's 'Not a point of this list' answer on "
            f"{page}'s {model} list; it is on the Aliases screen. Nothing was "
            f"changed.",
        )
    if existing is not None and existing["retired_at"] is None:
        raise WorkbookError(
            409,
            f"{norm} is already a tail label of {page}'s {model} walk. "
            f"Nothing was changed.",
        )
    point = film_repo.load_film_reference(conn).resolve_point(page, model, norm)
    if point:
        raise WorkbookError(
            409,
            f"{norm} is point {point} of {page}'s {model} list today. A tail "
            f"label is skipped on upload, so its readings would vanish. "
            f"Nothing was changed.",
        )
    if existing is None:
        film_repo.add_tail_label(
            conn, plant_code=page, model_code=model, label_norm=norm,
            note=f"RO17 (D-RO17-12): added on Point Check -- {reason}",
        )
    elif film_repo.set_tail_label_retired(
        conn, plant_code=page, model_code=model, label_norm=norm, reason=None,
    ) != 1:
        raise WorkbookError(
            409,
            f"{norm} was not put back: somebody may have changed it a moment "
            f"ago. Nothing was changed.",
        )
    audit_id = audit.record(
        conn,
        action="catalogue.film_tail_label.add",
        entity_type="ref_plant_film_tail_label",
        entity_id=f"{page}:{model}:{norm}",
        actor_user_id=actor,
        after={
            "plant_code": page, "model_code": model, "label_norm": norm,
            "restored": existing is not None, "reason": reason,
            "owner_decision": "RO17 D-RO17-12",
        },
        correlation_id=correlation_id,
    )
    return {
        "label_norm": norm,
        "audit_id": audit_id,
        "operator_message": (
            f"Rows of {page}'s {model} that write {norm} are skipped on upload "
            f"from now on: never a reading and never a question."
        ),
    }


def retire_film_tail_label(
    conn: Connection, plant_code: str, model_code: str, *,
    label: str, reason: str, actor: str, correlation_id: str | None,
) -> dict:
    """RO17 (D-RO17-12). Admin: stop skipping a tail label. The row stays."""
    plant, model, _ = _point_check_list(conn, plant_code, model_code)
    page = plant["plant_code"]
    norm = normalise_location(label)
    existing = _tail_label_row(conn, page, model, norm) if norm else None
    if existing is None:
        raise WorkbookError(
            404,
            f"{norm or '(blank)'} is not a tail label of {page}'s {model} "
            f"walk. Nothing was changed.",
        )
    if existing["retired_at"] is not None:
        raise WorkbookError(
            409,
            f"{norm} was already retired on "
            f"{str(existing['retired_at'])[:10]}. Nothing was changed.",
        )
    why = f"RO17 (D-RO17-12): retired on Point Check -- {reason}"
    if film_repo.set_tail_label_retired(
        conn, plant_code=page, model_code=model, label_norm=norm, reason=why,
    ) != 1:
        raise WorkbookError(
            409,
            f"{norm} was not retired: somebody may have retired it a moment "
            f"ago. Nothing was changed.",
        )
    audit_id = audit.record(
        conn,
        action="catalogue.film_tail_label.retire",
        entity_type="ref_plant_film_tail_label",
        entity_id=f"{page}:{model}:{norm}",
        actor_user_id=actor,
        after={
            "plant_code": page, "model_code": model, "label_norm": norm,
            "retired_reason": why, "owner_decision": "RO17 D-RO17-12",
        },
        correlation_id=correlation_id,
    )
    return {
        "label_norm": norm,
        "audit_id": audit_id,
        "operator_message": (
            f"{norm} is no longer skipped on {page}'s {model} uploads. A row "
            f"that writes it is read like any other label from now on."
        ),
    }


#: RO17 (D-RO17-11). The holds a row answer may name a point for. Without a
#: `film_point_setting` the cleaner holds an unknown label as an unmapped or
#: extra point instead of asking (D-99-12); the alias it answers with is read
#: before any setting check (`FilmReference.resolve_point`), so it loads too.
_FILM_POINT_ASKED = frozenset({
    REASON_FILM_POINT_UNKNOWN, REASON_UNMAPPED_POINT, REASON_EXTRA_POINT,
})


def answer_film_point(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, raw_location: str, point_code: str, note: str | None,
    actor: str, correlation_id: str | None,
) -> dict:
    """T109 (D-109-6). "This label is that point", answered in the row.

    The sheet wrote a label this plant's live list does not hold -- a point
    that was retired, a spelling this plant has started writing. The person
    with the file in front of them says which live point it is; the answer is
    stored as an **alias** and every later upload resolves it without asking
    again (which is the whole of D-99-3: the thing an answer writes is the
    thing the next upload reads).

    What it is not: a guess, a walk-order match, or a write to
    `ref_film_location_map` -- whose 118 FTM rows are all retired, are the
    record for the facts mapped through them, and whose key could not hold a
    live answer beside one of them (D-109-8).

    Then the tab is re-read from the stored bytes through the one ingest
    service, and the rows that carried the label load like any other.
    """
    sheet = _film_sheet(
        conn, plant_code, file_hash, load_id, reason=_FILM_POINT_ASKED,
    )
    page = sheet["plant_code"]
    projection = repo.preview_rows(conn, load_id)
    model = _film_model_of(projection)
    if not model:
        raise WorkbookError(
            409,
            f"Tab {load_id} has no model yet, so a point of it cannot be "
            f"named. Answer the model question first. Nothing was changed.",
        )
    asked = {
        normalise_location(row["canonical"].get("offending_value") or ""): str(
            row["canonical"].get("offending_value") or ""
        )
        for row in projection
        if row.get("reason") in _FILM_POINT_ASKED
        and (row.get("canonical") or {}).get("offending_value")
    }
    label = normalise_location(raw_location)
    if label not in asked:
        raise WorkbookError(
            409,
            f"{raw_location!r} is not a label tab {load_id} is asking about. "
            f"It asks about: {', '.join(sorted(asked.values())) or 'nothing'}. "
            f"Nothing was changed.",
        )
    live = {p["point_code"] for p in film_repo.point_setting(conn, page, model)}
    code = normalise_location(point_code)
    if code not in live:
        raise WorkbookError(
            422,
            f"{code or '(blank)'} is not a live point of {page}'s {model} "
            f"list. Pick one of its points, or add the new point on Point "
            f"Check first and then re-check this file. Nothing was changed.",
        )
    already = film_repo.live_alias(conn, page, model, label)
    if already:
        raise WorkbookError(
            409,
            f"{asked[label]} is already remembered as {already} on {page}'s "
            f"{model} list. Nothing was changed.",
        )
    reason = note or (
        f"T109 (D-109-6): answered in the row on the worksheet of load "
        f"{load_id} -- {asked[label]} is {code}"
    )
    film_repo.insert_point_alias(
        conn, plant_code=page, model_code=model, raw_location_norm=label,
        point_code=code, reason=reason, actor=actor or None,
    )
    _record(
        conn, sheet, kind=repo.KIND_FILM_POINT_ALIAS,
        subject=repo.film_alias_subject(asked[label], code),
        actor=actor, note=reason, correlation_id=correlation_id,
    )
    audit.record(
        conn,
        action="catalogue.film_point_alias.answer",
        entity_type="ref_film_point_alias",
        entity_id=f"{page}:{model}:{label}",
        actor_user_id=actor,
        after={
            "plant_code": page, "model_code": model,
            "raw_location_norm": label, "point_code": code,
            "load_id": load_id, "reason": reason,
            "owner_decision": "T109 D-109-6",
        },
        correlation_id=correlation_id,
    )
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason=(
            f"the uploader said {asked[label]} is {code} on {page}'s {model} "
            f"list (T109)"
        ),
    )
    return {
        "decisions_written": 1,
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            f"{asked[label]} is {code} from now on, on every upload of "
            f"{page}'s {model}. "
            + ("The tab is being read again." if replayed else
               'Press "Load remaining matched rows" to add them.')
        ),
    }


def answer_film_not_a_point(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    load_id: int, raw_location: str, note: str | None, actor: str,
    correlation_id: str | None,
) -> dict:
    """RO18 (B5). "Not a point of this list: keep it, never load it."

    The other answer to the row's point question. The label is remembered
    per plant x model as a tail-label row marked ``not_a_point`` (revision
    0048), so it is read exactly as a tail label is: skipped anywhere in the
    walk, kept with the file, never loaded, never a hold -- with or without
    the point rules. Never offered for a label that resolves to a point.
    """
    sheet = _film_sheet(
        conn, plant_code, file_hash, load_id, reason=_FILM_POINT_ASKED,
    )
    page = sheet["plant_code"]
    projection = repo.preview_rows(conn, load_id)
    model = _film_model_of(projection)
    if not model:
        raise WorkbookError(
            409,
            f"Tab {load_id} has no model yet, so a label of it cannot be "
            f"answered. Answer the model question first. Nothing was changed.",
        )
    asked = {
        normalise_location(row["canonical"].get("offending_value") or ""): str(
            row["canonical"].get("offending_value") or ""
        )
        for row in projection
        if row.get("reason") in _FILM_POINT_ASKED
        and (row.get("canonical") or {}).get("offending_value")
    }
    label = normalise_location(raw_location)
    if label not in asked:
        raise WorkbookError(
            409,
            f"{raw_location!r} is not a label tab {load_id} is asking about. "
            f"It asks about: {', '.join(sorted(asked.values())) or 'nothing'}. "
            f"Nothing was changed.",
        )
    point = film_repo.load_film_reference(conn).resolve_point(page, model, label)
    if point:
        raise WorkbookError(
            409,
            f"{asked[label]} is point {point} of {page}'s {model} list now, so "
            f"it is a reading, not something to keep out. Nothing was changed.",
        )
    if any(
        t["label_norm"] == label
        for answered in (False, True)
        for t in film_repo.tail_labels(conn, page, model, not_a_point=answered)
    ):
        raise WorkbookError(
            409,
            f"{asked[label]} already has a kept-and-not-loaded row on {page}'s "
            f"{model} list (Point Check or Aliases). Nothing was changed.",
        )
    reason = note or (
        f"RO18 (B5): answered in the row on the worksheet of load {load_id} -- "
        f"{asked[label]} is not a point of this list"
    )
    film_repo.add_tail_label(
        conn, plant_code=page, model_code=model, label_norm=label,
        note=reason, not_a_point=True,
    )
    _record(
        conn, sheet, kind=repo.KIND_FILM_NOT_A_POINT, subject=asked[label],
        actor=actor, note=reason, correlation_id=correlation_id,
    )
    audit.record(
        conn,
        action="catalogue.film_not_a_point.answer",
        entity_type="ref_plant_film_tail_label",
        entity_id=f"{page}:{model}:{label}",
        actor_user_id=actor,
        after={
            "plant_code": page, "model_code": model, "label_norm": label,
            "not_a_point": True, "load_id": load_id, "reason": reason[:300],
            "owner_decision": "RO18 B5",
        },
        correlation_id=correlation_id,
    )
    replayed = _replay_if_possible(
        ingest, conn, sheet, actor=actor, correlation_id=correlation_id,
        reason=(
            f"the uploader said {asked[label]} is not a point of {page}'s "
            f"{model} list (RO18)"
        ),
    )
    return {
        "decisions_written": 1,
        "replayed_load_ids": [load_id] if replayed else [],
        "operator_message": (
            f"{asked[label]} is kept and never loaded on {page}'s {model} "
            f"uploads from now on. "
            + ("The tab is being read again." if replayed else
               'Press "Load remaining matched rows" to add them.')
        ),
    }


# =====================================================================
# the loads
# =====================================================================
def load_ready(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    actor: str, correlation_id: str | None,
) -> dict:
    """"Yes, load these rows": commit every ready tab (D-22 - D-24).

    The click is the Engineer's statement about the held rows, so the
    warning acknowledgements a commit needs are recorded in their name with
    a fixed note, at the current review revision, before each commit. A tab
    with any other blocker is skipped and said so. Each tab is its own
    audited commit through the one ingest service.
    """
    plant, sheets = _sheets(conn, plant_code, file_hash)
    page = plant["plant_code"]
    outcomes: list[dict] = []
    loaded_ids: list[int] = []
    total = 0
    readings = 0
    for sheet in sheets:
        load_id = int(sheet["load_id"])
        batch = batches.get_batch(conn, load_id)
        blockers = commit_blockers(conn, batch)
        others = [b for b in blockers if b != BLOCKER_WARNINGS_UNACKNOWLEDGED]
        if (
            batch["status"] != batches.STATUS_PENDING_REVIEW
            or others
            or not batch["rows_loaded"]
        ):
            outcomes.append({
                "load_id": load_id, "sheet": batch["source_sheet"],
                "measurements_inserted": 0, "loaded": False, "blockers": blockers,
                "operator_message": (
                    EXTRA_TAB_MESSAGE
                    if sheet.get("sheet_class") == SHEET_OUT_OF_SCOPE
                    else "Nothing on this tab is ready to add yet."
                ),
            })
            continue
        revision = str(batch["review_revision"]).strip()
        for category in unacknowledged_categories(conn, batch):
            stored = ack_repo.insert(
                conn, load_id=load_id, plant_code=page,
                file_hash=str(batch["file_hash"]).strip(), category=category,
                note=YES_NOTE, review_revision=revision, actor_user_id=actor,
            )
            audit.record(
                conn, action="review.acknowledge", entity_type="load_batch",
                entity_id=load_id, actor_user_id=actor,
                after={
                    "ack_id": stored["ack_id"], "category": category,
                    "review_revision": revision, "note": YES_NOTE,
                    "via": "worksheet.load_ready",
                },
                correlation_id=correlation_id,
            )
        try:
            result = ingest.commit_batch(
                conn, load_id, actor_user_id=actor, correlation_id=correlation_id
            )
        except IngestError as exc:
            raise WorkbookError(
                409,
                f"Tab {batch['source_sheet']!r} could not load: {exc} Nothing "
                f"from this click was loaded.",
            ) from exc
        inserted = int(result["measurements_inserted"])
        total += inserted
        # T54: a Film point is one reading with up to four layer facts;
        # the uploader counts points, not layers.
        added = (
            len(repo.fact_source_rows(conn, load_id))
            if sheet.get("sheet_class") == SHEET_FILMTHICKNESS else inserted
        )
        readings += added
        loaded_ids.append(load_id)
        outcomes.append({
            "load_id": load_id, "sheet": batch["source_sheet"],
            "measurements_inserted": inserted, "loaded": True, "blockers": [],
            "operator_message": f"{_count(added, 'reading', 'readings')} added.",
        })
    if not total:
        raise WorkbookError(
            409,
            "No tab of this workbook is ready to load. Answer the questions on "
            "the worksheet first. Nothing was loaded.",
        )
    # T53 (D-53-15): the prototype toast, in the uploader's words.
    months = repo.fact_months(conn, loaded_ids)
    held, not_stored, already = _workbook_outcomes(conn, sheets, page)
    return {
        "sheets": outcomes,
        "measurements_inserted": total,
        "readings_added": readings,
        "rows_held": held,
        "rows_already_in_history": already,
        "months": months,
        "operator_message": toast_message(
            readings, months, held, already, not_stored=not_stored
        ),
    }


def load_remaining(
    conn: Connection, ingest: IngestService, plant_code: str, file_hash: str, *,
    actor: str, correlation_id: str | None,
) -> dict:
    """ADR 0013 decision 9: INSERT the rows of loaded tabs that now qualify."""
    plant, sheets = _sheets(conn, plant_code, file_hash)
    committed = [
        int(s["load_id"]) for s in sheets if s["status"] == batches.STATUS_COMMITTED
    ]
    before = repo.max_measurement_id(conn, committed)
    outcomes: list[dict] = []
    total = 0
    for sheet in sheets:
        load_id = int(sheet["load_id"])
        if sheet["status"] != batches.STATUS_COMMITTED:
            continue
        try:
            result = ingest.insert_remaining(
                conn, load_id, actor_user_id=actor, correlation_id=correlation_id
            )
        except IngestError as exc:
            outcomes.append({
                "load_id": load_id, "sheet": sheet["source_sheet"],
                "measurements_inserted": 0, "loaded": False, "blockers": [],
                "operator_message": str(exc)[:500],
            })
            continue
        inserted = int(result["measurements_inserted"])
        total += inserted
        outcomes.append({
            "load_id": load_id, "sheet": sheet["source_sheet"],
            "measurements_inserted": inserted, "loaded": bool(inserted),
            "blockers": [],
            "operator_message": (
                f"{_count(inserted, 'more reading', 'more readings')} added, "
                f"{result['still_held']} still held out."
                if inserted else
                f"No more readings can be added yet, {result['still_held']} "
                f"still held out."
            ),
        })
    if not outcomes:
        raise WorkbookError(
            409,
            "No tab of this workbook is loaded yet. Press \"Yes, load these "
            "rows\" first. Nothing was loaded.",
        )
    months = repo.fact_months(conn, committed, after_measurement_id=before)
    held, not_stored, already = _workbook_outcomes(
        conn, sheets, plant["plant_code"]
    )
    return {
        "sheets": outcomes,
        "measurements_inserted": total,
        "readings_added": total,
        "rows_held": held,
        "rows_already_in_history": already,
        "months": months,
        "operator_message": (
            toast_message(
                total, months, held, already, not_stored=not_stored, more=True
            ) if total
            else "No more readings can be added yet."
            + (f" {held} held out." if held else "")
        ),
    }


__all__ = [
    "worksheet",
    "ignore_columns",
    "answer_plant",
    "approve_holes",
    "confirm_panels",
    "load_ready",
    "load_remaining",
]
