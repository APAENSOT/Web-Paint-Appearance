"""The plant Data Manager: workbook reads, and the one mutation that goes with them.

This service answers "what has this plant sent us, and what is stopping each
file becoming measurements" **entirely from stored state**. It opens no
workbook (T19 locked decision 1), computes no grade (D1 is open), and writes
nothing except a `review_acknowledgement`, a `review_override` (T21) and
their audit events -- an override also re-derives its sheet, through
`IngestService.revalidate_review`, never through SQL of its own.

Three rules worth stating where they are implemented rather than only in the
task file:

* **A sheet's layout is the one on its projection**, not the frozen
  `load_batch.template_fingerprint`. That column is provenance, written at
  upload and never updated, so after a replay through an approved alias it
  names a layout that no longer parsed anything. T18 recorded this as an
  honest note; this is where it is honoured.
* **Superseded facts are still this file's rows.** The workbook drill-down
  joins `wavescan` directly, while `GET /measurements` stays on
  `v_wavescan_active`. A retired batch's measurements are not current, and
  they are also not gone -- Files is exactly where somebody goes to see what
  a retired file contained (T19 locked decision 8, design section 14).
* **An acknowledgement is about rows, not about a file.** It binds to the
  batch's `review_revision`, so re-parsing the bytes leaves it in the table
  as evidence and stops it satisfying the commit gate.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.domain import workbooks as rules
from app.domain.workbooks import (
    SUMMARY_ABANDONED,
    SUMMARY_SUPERSEDED,
    operational_summary,
    ranges_overlap,
)
from app.domain.film_header import SHEET_FILMTHICKNESS
from app.domain.film_walk import no_named_points_note
from app.repositories import acknowledgements as ack_repo
from app.repositories import filmthickness as film_repo
from app.repositories import audit, batches as batch_repo, ingest_jobs, profiles
from app.repositories import overrides as override_repo
from app.repositories import reference as reference_repo
from app.repositories import workbooks as repo
from app.repositories import workbook_uploads
from app.repositories import ws_points as ws_points_repo
from app.services.ingest import (
    BLOCKER_NOT_PENDING_REVIEW,
    IngestError,
    IngestService,
    commit_blockers,
    required_acknowledgements,
)
from app.services.filmthickness import _complete as film_complete

#: Up to this many example rows per issue. The full list is `/rows`.
SAMPLE_LIMIT = 20

LEVEL_BLOCKER = "BLOCKER"
LEVEL_WARNING = "WARNING"
LEVEL_INFORMATION = "INFORMATION"

TOKEN_PLANT_FILLED = "PLANT_FILLED"
TOKEN_PROFILE_APPLIED = "PROFILE_APPLIED"

#: Which sheet statuses are themselves blockers, and what a person can do.
STATUS_BLOCKERS = {
    "RUNNING": "wait_for_worker",
    "FAILED": "corrected_source",
    "REJECTED_TEMPLATE": "mapping",
}

#: What to do about each commit blocker. `blocked_identity` means "no route
#: in this platform can lift this": a SAP workbook with no vehicle identity
#: (M7) and a layout no fixture has proved (M6) are both waiting on a
#: decision the application is not allowed to make for itself.
BLOCKER_RESOLUTIONS = {
    "UNKNOWN_TEMPLATE": "mapping",
    "UNVERIFIED_PROFILE": "blocked_identity",
    "VEHICLE_IDENTITY_MISSING": "blocked_identity",
    "UNBALANCED": "corrected_source",
    "NO_REVIEW_PROJECTION": "mapping",
    "WARNINGS_UNACKNOWLEDGED": "acknowledge",
}

#: Warning category -> the count on `load_batch` that raises it, and the
#: projection disposition whose rows illustrate it.
WARNING_SOURCES = (
    (ack_repo.CATEGORY_REJECTED_ROWS, "rows_rejected", "REJECT"),
    (ack_repo.CATEGORY_QUARANTINED_MODELS, "rows_quarantine", "QUARANTINE"),
    (ack_repo.CATEGORY_DUPLICATE_ROWS, "rows_duplicate", "DUPLICATE"),
)


class WorkbookError(RuntimeError):
    """A read or acknowledgement was refused. Carries the HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# =====================================================================
# plant and workbook scope
# =====================================================================
def resolve_plant(conn: Connection, plant_code: str) -> dict:
    """The plant this URL names, or 404.

    An **inactive** plant resolves normally. FVL is a plant this platform
    knows and has not onboarded (D5); its file list is empty, and saying so
    is more useful than pretending the plant does not exist. Only a code that
    matches no `ref_plant` row and no alias is a 404.
    """
    plant = repo.resolve_plant(conn, plant_code)
    if plant is None:
        raise WorkbookError(
            404,
            f"No plant {plant_code!r}. Plant codes and their aliases come from "
            f"ref_plant / ref_plant_alias; GET /api/v1/meta lists them.",
        )
    return plant


def _sheet_view(
    conn: Connection, row: dict, job: dict | None, acked: set[str]
) -> dict:
    """One sheet, with everything a reviewer needs to act on it.

    `commit_blockers` is the same function `GET /api/v1/batches/{id}` calls,
    so the Files page and the batch page cannot disagree about whether a
    sheet can be committed.
    """
    blockers = commit_blockers(conn, row)
    return {
        "row": row,
        "job": job,
        "commit_blockers": blockers,
        "committable": not blockers,
        "required_acknowledgements": required_acknowledgements(row),
        "acknowledged": sorted(acked),
    }


def _assemble(conn: Connection, plant_code: str, hashes: list[str]) -> list[dict]:
    """Group sheets into workbooks and compute each one's summary.

    Ordering of the result follows `hashes`, which the repository has already
    sorted by measured date. Sorting again here would be a second opinion
    about the order of the file list.
    """
    if not hashes:
        return []
    sheets = repo.sheets_for_hashes(conn, plant_code, hashes)
    uploads = workbook_uploads.for_hashes(conn, plant_code, hashes)
    legacy = workbook_uploads.legacy_for_hashes(conn, plant_code, hashes)
    skips_by_hash: dict[str, dict[str, dict]] = {h: {} for h in hashes}
    for h, record in uploads.items():
        for skipped in record["skipped_sheets"]:
            skips_by_hash[h][skipped["source_sheet"]] = {
                "source_sheet": skipped["source_sheet"], "reason": skipped["reason"],
                "legacy_load_id": None,
            }
    legacy_first: dict[str, dict] = {}
    for row in legacy:
        h = str(row["file_hash"]).strip()
        legacy_first.setdefault(h, row)
        skips_by_hash[h].setdefault(row["source_sheet"], {
            "source_sheet": row["source_sheet"], "reason": row["notes"] or "Out-of-scope sheet kept as evidence.",
            "legacy_load_id": row["load_id"],
        })
    jobs = ingest_jobs.get_for_batches(conn, [s["load_id"] for s in sheets])
    acked = ack_repo.acknowledged_for_batches(conn, [s["load_id"] for s in sheets])
    vehicle_sets = _vehicle_set_counts(conn, [s["load_id"] for s in sheets])

    grouped: dict[str, list[dict]] = {h: [] for h in hashes}
    for row in sheets:
        grouped.setdefault(str(row["file_hash"]).strip(), []).append(row)

    out: list[dict] = []
    for file_hash in hashes:
        rows = grouped.get(file_hash, [])
        if not rows and file_hash not in uploads and file_hash not in legacy_first:
            continue
        views = [
            _sheet_view(conn, row, jobs.get(row["load_id"]), acked.get(row["load_id"], set()))
            for row in rows
        ]
        summary = operational_summary([row["status"] for row in rows]) if rows else rules.SUMMARY_SKIPPED
        counts = batch_repo.BatchCounts(
            rows_in_file=sum(r["rows_in_file"] for r in rows),
            rows_loaded=sum(r["rows_loaded"] for r in rows),
            rows_duplicate=sum(r["rows_duplicate"] for r in rows),
            rows_rejected=sum(r["rows_rejected"] for r in rows),
            rows_quarantine=sum(r["rows_quarantine"] for r in rows),
        )
        first = min(rows, key=lambda r: r["started_at"]) if rows else legacy_first.get(file_hash)
        upload = uploads.get(file_hash)
        if first is None:
            first = {"source_file": upload["source_file"], "started_at": upload["uploaded_at"],
                     "loaded_by": upload["loaded_by"]}
        out.append({
            "file_hash": file_hash,
            "plant_code": plant_code,
            # The name the file arrived under. Sheets of one upload share it;
            # where they do not, the earliest upload's name is the label,
            # because identity is the hash either way.
            "source_file": first["source_file"],
            "operational_summary": summary,
            "uploaded_at": first["started_at"],
            "loaded_by": str(first["loaded_by"]) if first["loaded_by"] else None,
            "counts": counts,
            "sheet_count": len(rows),
            "skipped_sheets": list(skips_by_hash[file_hash].values()),
            "skipped_sheet_count": len(skips_by_hash[file_hash]),
            "superseded": summary == SUMMARY_SUPERSEDED,
            "abandoned": summary == SUMMARY_ABANDONED,
            "vehicle_set_count": sum(vehicle_sets.get(r["load_id"], 0) for r in rows),
            "sheets": views,
        })
    return out


def _vehicle_set_counts(conn: Connection, load_ids: list[int]) -> dict[int, int]:
    """Vehicle sets per sheet, by the grouping the vehicles read uses (T21).

    The repository returns distinct identity cells; which of them are the
    same key (blank equals missing) is `domain.workbooks.identity_of`, so a
    card's count and the vehicles page cannot disagree.
    """
    keys: dict[int, set[tuple]] = {}
    for row in repo.identity_rows(conn, load_ids):
        key = rules.set_key(row["disposition"], row)
        if key is not None:
            keys.setdefault(int(row["load_id"]), set()).add(key)
    return {load_id: len(found) for load_id, found in keys.items()}


def _set_dates(item: dict, dmin: date | None, dmax: date | None) -> None:
    item["measured_date_min"] = dmin
    item["measured_date_max"] = dmax
    item["measured_dates_span_months"] = rules.spans_months(dmin, dmax)


def current_utc_month() -> tuple[int, int]:
    return rules.utc_month(datetime.now(timezone.utc))


def list_workbooks(
    conn: Connection,
    plant_code: str,
    *,
    limit: int,
    offset: int,
    inbox: str = rules.INBOX_ALL,
    uploaded_month: tuple[int, int] | None = None,
) -> tuple[list[dict], int]:
    """One page of this plant's workbooks, and how many there are in total.

    `inbox=all` is T19's list: the same SQL membership and ordering. The
    other two inboxes are decided over the plant's whole workbook index by
    `domain.workbooks.select_inbox`, then paged here, so Needs attention
    never depends on the client walking every page.
    """
    if inbox == rules.INBOX_ALL:
        page = repo.list_workbook_hashes(conn, plant_code, limit=limit, offset=offset)
        total = repo.count_workbooks(conn, plant_code)
    else:
        month = uploaded_month or current_utc_month()
        index = repo.workbook_index(conn, plant_code)
        for entry in index:
            entry["operational_summary"] = operational_summary(entry["statuses"]) if entry["statuses"] else rules.SUMMARY_SKIPPED
        chosen = rules.select_inbox(index, inbox, month)
        total = len(chosen)
        page = chosen[offset:offset + limit]

    hashes = [str(r["file_hash"]).strip() for r in page]
    dates = {
        str(r["file_hash"]).strip(): (r["measured_date_min"], r["measured_date_max"])
        for r in page
    }
    items = _assemble(conn, plant_code, hashes)
    for item in items:
        _set_dates(item, *dates.get(item["file_hash"], (None, None)))
    return items, total


def get_workbook(conn: Connection, plant_code: str, file_hash: str) -> dict:
    """One workbook of one plant, or 404.

    A hash filed under another plant is a 404 here, not a 403 and not a
    redirect: telling an Admin scoped to AAT that FTM holds these bytes would
    leak another plant's file list one hash at a time (T19 locked decision
    10).
    """
    items = _assemble(conn, plant_code, [file_hash])
    if not items:
        raise WorkbookError(
            404,
            f"No workbook {file_hash} at plant {plant_code}. A workbook is "
            f"identified by the SHA-256 of its bytes at one plant; the same "
            f"bytes filed under another plant are that plant's workbook.",
        )
    workbook = items[0]
    dates = repo.dates_for_hash(conn, plant_code, file_hash)
    _set_dates(workbook, dates["measured_date_min"], dates["measured_date_max"])
    return workbook


def _load_ids(workbook: dict) -> list[int]:
    return [view["row"]["load_id"] for view in workbook["sheets"]]


def _child_or_404(workbook: dict, load_id: int | None) -> None:
    if load_id is None:
        return
    if load_id not in _load_ids(workbook):
        raise WorkbookError(
            404,
            f"Batch {load_id} is not a sheet of workbook "
            f"{workbook['file_hash']} at plant {workbook['plant_code']}.",
        )


# =====================================================================
# detail
# =====================================================================
def detail(conn: Connection, plant_code: str, file_hash: str) -> dict:
    """The workbook, its profiles, its replacement hint and its acknowledgements."""
    workbook = get_workbook(conn, plant_code, file_hash)
    load_ids = _load_ids(workbook)

    # The layout that parsed a sheet lives on its projection rows; the
    # column on `load_batch` is the layout the *upload* saw and is stale
    # after a replay. Preferring the projection is T18's honest note.
    fingerprints = repo.projection_fingerprints(conn, load_ids)
    seen: dict[int, dict] = {}
    for view in workbook["sheets"]:
        row = view["row"]
        profile = profiles.get_profile(conn, row["profile_id"])
        if profile is None:
            continue
        entry = seen.setdefault(profile["profile_id"], {**profile, "load_ids": []})
        entry["load_ids"].append(row["load_id"])
        parsed = fingerprints.get(row["load_id"])
        if parsed:
            entry["template_fingerprint"] = parsed

    replacements = [
        {
            "file_hash": str(candidate["file_hash"]).strip(),
            "source_file": candidate["source_file"],
            "measured_date_min": candidate["measured_date_min"],
            "measured_date_max": candidate["measured_date_max"],
        }
        for candidate in repo.replacement_candidates(conn, plant_code, file_hash)
        if ranges_overlap(
            workbook["measured_date_min"], workbook["measured_date_max"],
            candidate["measured_date_min"], candidate["measured_date_max"],
        )
    ]

    return {
        "workbook": workbook,
        "profiles": sorted(seen.values(), key=lambda p: p["profile_id"]),
        "possible_replacements": replacements,
        "acknowledgements": ack_repo.for_batches(conn, load_ids),
    }


# =====================================================================
# rows
# =====================================================================
def rows(
    conn: Connection,
    plant_code: str,
    file_hash: str,
    *,
    load_id: int | None,
    disposition: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    workbook = get_workbook(conn, plant_code, file_hash)
    _child_or_404(workbook, load_id)
    items = repo.list_workbook_rows(
        conn, plant_code, file_hash,
        load_id=load_id, disposition=disposition, limit=limit, offset=offset,
    )
    total = repo.count_workbook_rows(
        conn, plant_code, file_hash, load_id=load_id, disposition=disposition
    )
    return items, total


# =====================================================================
# issues
# =====================================================================
def _samples(conn: Connection, load_id: int, disposition: str) -> list[dict]:
    return [
        {
            "load_id": row["load_id"],
            "source_sheet": row["source_sheet"],
            "source_row": row["source_row"],
            "reason": row["reason"],
        }
        for row in repo.sample_rows(conn, [load_id], disposition, SAMPLE_LIMIT)
    ]


def issues(conn: Connection, plant_code: str, file_hash: str) -> list[dict]:
    """Blockers, warnings and information for one workbook.

    Three levels and nothing else: no pass rate, no Ford band, and no
    client-side grading function (design section 11). A blocker prevents a commit, a warning
    needs a person to accept it, and information is disclosure -- the plant
    cells this platform filled in, and the profile that read the layout.
    """
    workbook = get_workbook(conn, plant_code, file_hash)
    load_ids = _load_ids(workbook)
    filled = repo.normalized_field_counts(conn, load_ids)
    found: list[dict] = []

    for view in workbook["sheets"]:
        row = view["row"]
        load_id = row["load_id"]
        status = row["status"]

        # ------------------------------------------------- blockers
        if status in STATUS_BLOCKERS:
            # T103 (D-103-4): a Film sheet that names no point is not waiting
            # on a mapping -- no alias an Admin approves can make a
            # placeholder label name a point (D-99-9). It says the sentence
            # the refusal stored, and asks for better bytes instead.
            no_name = no_named_points_note(row["notes"])
            found.append({
                "level": LEVEL_BLOCKER, "token": status, "load_id": load_id,
                "count": 1, "sample_rows": [], "acked": False,
                "resolution": (
                    "corrected_source" if no_name else STATUS_BLOCKERS[status]
                ),
                "operator_message": no_name,
            })
        for token in view["commit_blockers"]:
            # A sheet that is not PENDING_REVIEW is already described by its
            # status above; repeating NOT_PENDING_REVIEW would tell a reader
            # that a committed sheet has a problem.
            if token == BLOCKER_NOT_PENDING_REVIEW:
                continue
            if status in STATUS_BLOCKERS and token in ("UNKNOWN_TEMPLATE",):
                continue
            found.append({
                "level": LEVEL_BLOCKER, "token": token, "load_id": load_id,
                "count": 1, "sample_rows": [], "acked": False,
                "resolution": BLOCKER_RESOLUTIONS.get(token, "corrected_source"),
            })

        # ------------------------------------------------- warnings
        acked = set(view["acknowledged"])
        for category, column, disposition in WARNING_SOURCES:
            count = row[column]
            if not count:
                continue
            found.append({
                "level": LEVEL_WARNING, "token": category, "load_id": load_id,
                "count": int(count),
                "sample_rows": _samples(conn, load_id, disposition),
                "acked": category in acked,
                "resolution": "acknowledge",
            })

        # ------------------------------------------------- information
        if filled.get(load_id):
            found.append({
                "level": LEVEL_INFORMATION, "token": TOKEN_PLANT_FILLED,
                "load_id": load_id, "count": int(filled[load_id]),
                "sample_rows": [], "acked": False, "resolution": None,
            })
        if row["profile_id"] is not None:
            found.append({
                "level": LEVEL_INFORMATION, "token": TOKEN_PROFILE_APPLIED,
                "load_id": load_id, "count": 1, "sample_rows": [],
                "acked": False, "resolution": None,
            })

    # --------------------------------------------------- workbook-wide
    overlapping = [
        candidate
        for candidate in repo.replacement_candidates(conn, plant_code, file_hash)
        if ranges_overlap(
            workbook["measured_date_min"], workbook["measured_date_max"],
            candidate["measured_date_min"], candidate["measured_date_max"],
        )
    ]
    if overlapping:
        acked_anywhere = any(
            ack_repo.CATEGORY_POSSIBLE_REPLACEMENT in view["acknowledged"]
            for view in workbook["sheets"]
        )
        found.append({
            "level": LEVEL_WARNING,
            "token": ack_repo.CATEGORY_POSSIBLE_REPLACEMENT,
            "load_id": None,
            "count": len(overlapping),
            "sample_rows": [],
            "acked": acked_anywhere,
            # Advisory. Retiring the older workbook is a separate Admin
            # action carrying a reason, and it is never done automatically
            # (design M14).
            "resolution": "supersede_separate",
        })
    return found


# =====================================================================
# history
# =====================================================================
def history(conn: Connection, plant_code: str, file_hash: str) -> list[dict]:
    workbook = get_workbook(conn, plant_code, file_hash)
    legacy_ids = [s["legacy_load_id"] for s in workbook["skipped_sheets"] if s["legacy_load_id"] is not None]
    return repo.history(conn, _load_ids(workbook) + legacy_ids, workbook_key=f"{plant_code}:{file_hash}")


# =====================================================================
# the one mutation
# =====================================================================
def acknowledge(
    conn: Connection,
    plant_code: str,
    file_hash: str,
    body,
    *,
    actor_user_id: str,
    correlation_id: str | None = None,
) -> dict:
    """Record that a named person read one warning category of one sheet.

    One transaction: the acknowledgement and its `audit_event`
    (`AGENTS.md` section 2). The audit row's entity is the **batch**, because
    what changed is whether that batch can be committed; `after` carries the
    `ack_id`, the category and the revision, so the workbook history reads as
    one timeline instead of two.

    Refusals, and nothing is written for any of them:

    * the sheet is not a child of this workbook at this plant -> 404
    * the revision sent is not the batch's current one -> 409, because the
      rows the reviewer read are not the rows that would be committed
    * the batch has no projection at all -> 409, same reason
    * a rejected or quarantined category with a blank note -> 422 from the
      DTO, and `ck_ack_note_required` behind it
    """
    workbook = get_workbook(conn, plant_code, file_hash)
    _child_or_404(workbook, body.load_id)
    batch = batch_repo.get_batch_for_update(conn, body.load_id)
    if batch is None:  # pragma: no cover - the child check already proved it
        raise WorkbookError(404, f"No batch {body.load_id}.")

    current = batch["review_revision"]
    current = str(current).strip() if current else None
    if not current:
        raise WorkbookError(
            409,
            f"Batch {body.load_id} has no review projection yet, so there is "
            f"nothing to acknowledge. Wait for the worker to finish, or "
            f"replay the batch. Nothing was written.",
        )
    if current != body.review_revision:
        raise WorkbookError(
            409,
            f"Batch {body.load_id} is at review revision {current[:12]}..., "
            f"not {body.review_revision[:12]}.... The rows were re-derived "
            f"after you loaded them -- an approved alias or a zone map moved "
            f"in between -- so this acknowledgement would be about rows "
            f"nobody read. Nothing was written. Re-read the review and "
            f"acknowledge again.",
        )
    if (
        body.category in ack_repo.NOTE_REQUIRED and not body.note
    ):  # pragma: no cover - the DTO refuses it first
        raise WorkbookError(
            422,
            f"{body.category} needs a note saying why these rows are "
            f"acceptable (design M11). Nothing was written.",
        )

    stored = ack_repo.insert(
        conn,
        load_id=body.load_id,
        plant_code=plant_code,
        file_hash=file_hash,
        category=body.category,
        note=body.note,
        review_revision=current,
        actor_user_id=actor_user_id,
    )
    audit.record(
        conn,
        action="review.acknowledge",
        entity_type="load_batch",
        entity_id=body.load_id,
        actor_user_id=actor_user_id,
        after={
            "ack_id": stored["ack_id"],
            "category": stored["category"],
            "review_revision": current,
            "file_hash": file_hash,
            "note": stored["note"],
        },
        correlation_id=correlation_id,
    )
    return stored


# =====================================================================
# T21: vehicle sets and points
# =====================================================================
def _expected_zones(conn: Connection) -> dict[str, int]:
    """`ref_model.expected_zone_count` per model, read from the database."""
    return dict(reference_repo.load_reference_data(conn).expected_zones)


def _film_count(walks: dict[str, tuple[dict[str, int], list[int]]]):
    """RO11 (D-RO11-3): `(point_count, expected, incomplete)` of a Film car.

    Counted as `repositories.filmthickness._VEHICLES` counts a History car,
    then judged by History's own `_complete` (the complete-stop rule), so a
    review set and its History car cannot disagree.
    """
    def count(model: str | None, codes: set[str]) -> tuple[int, int | None, bool]:
        walk, stops = walks.get(model, ({}, [])) if model is not None else ({}, [])
        listed = [walk[code] for code in codes if code in walk]
        car = film_complete({
            "serial_no": None,
            "job_nos": [],
            # With a live list only its codes count; with none, every code.
            "mapped_point_count": len(listed) if walk else len(codes),
            "expected_point_count": len(walk) or None,
            "walked_to": max(listed, default=None),
            "stop_point_nos": stops,
        })
        return car["mapped_point_count"], car["expected_point_count"], car["incomplete"]

    return count


def _is_film(workbook: dict, load_id: int) -> bool:
    return any(
        view["row"]["load_id"] == load_id
        and view["row"].get("sheet_class") == SHEET_FILMTHICKNESS
        for view in workbook["sheets"]
    )


def _sheet_sets(
    conn: Connection,
    plant_code: str,
    file_hash: str,
    load_id: int,
    expected_zones: dict[str, int],
    live_points: dict[str, frozenset[str]],
    film: bool = False,
    walks: dict[str, tuple[dict[str, int], list[int]]] | None = None,
) -> tuple[list[dict], list[rules.VehicleSet]]:
    rows = repo.sheet_rows(conn, plant_code, file_hash, load_id)
    return rows, rules.group_vehicle_sets(
        load_id, rows, expected_zones, live_points,
        film=_film_count(walks or {}) if film else None,
    )


def vehicles(
    conn: Connection,
    plant_code: str,
    file_hash: str,
    *,
    load_id: int,
    limit: int,
    offset: int,
) -> tuple[list[rules.VehicleSet], int]:
    """One sheet's vehicle sets, grouped on the server (design F8).

    From the projection, or the sheet's facts where no projection exists --
    never from the workbook. A sheet still RUNNING, or refused as an unknown
    template, has no rows and so answers an empty page.
    """
    workbook = get_workbook(conn, plant_code, file_hash)
    _child_or_404(workbook, load_id)
    film = _is_film(workbook, load_id)
    _, sets = _sheet_sets(
        conn, plant_code, file_hash, load_id, _expected_zones(conn),
        ws_points_repo.live_lists(conn, plant_code), film,
        film_repo.live_walks(conn, plant_code) if film else None,
    )
    return sets[offset:offset + limit], len(sets)


def points(
    conn: Connection,
    plant_code: str,
    file_hash: str,
    vehicle_id: str,
    *,
    limit: int,
    offset: int,
) -> dict:
    """The rows of one vehicle set, raw against proposed, with overrides.

    The id already names its sheet, but the sheet is found by searching this
    workbook's own sheets: an id from another workbook or another plant is a
    404 here, never a lookup elsewhere.
    """
    workbook = get_workbook(conn, plant_code, file_hash)
    expected_zones = _expected_zones(conn)
    live_points = ws_points_repo.live_lists(conn, plant_code)
    walks = film_repo.live_walks(conn, plant_code)
    found, rows, film = None, [], False
    for load_id in _load_ids(workbook):
        film = _is_film(workbook, load_id)
        rows, sets = _sheet_sets(
            conn, plant_code, file_hash, load_id, expected_zones, live_points,
            film, walks,
        )
        found = next((s for s in sets if s.vehicle_id == vehicle_id), None)
        if found is not None:
            break
    if found is None:
        raise WorkbookError(
            404,
            f"No vehicle set {vehicle_id} in workbook {file_hash} at plant "
            f"{plant_code}. A vehicle_id names one set on one sheet of one "
            f"workbook.",
        )

    members = set(found.source_rows)
    walk = walks.get(found.model, ({}, []))[0] if film else None
    ordered = rules.order_points([r for r in rows if r["source_row"] in members], walk)
    page = ordered[offset:offset + limit]
    current = override_repo.current_for_rows(
        conn, found.load_id, sorted({r["source_row"] for r in page})
    )
    by_row: dict[int, list[dict]] = {}
    for row in current:
        by_row.setdefault(int(row["source_row"]), []).append(row)
    return {
        "vehicle": found,
        "items": [
            {**row, "current_overrides": by_row.get(row["source_row"], [])}
            for row in page
        ],
        "total": len(ordered),
    }


# =====================================================================
# T21: review overrides
# =====================================================================
def _proposed_measure(canonical: dict | None, field: str) -> Decimal | None:
    value = ((canonical or {}).get("measures") or {}).get(field)
    return Decimal(str(value)) if value is not None else None


def override(
    conn: Connection,
    ingest: IngestService,
    plant_code: str,
    file_hash: str,
    body,
    *,
    actor_user_id: str,
    correlation_id: str | None = None,
) -> dict:
    """Append numeric overrides for one vehicle set and revalidate the sheet.

    One transaction (the caller's): the `review_override` rows, the
    synchronous re-derivation through the ingest service, and the
    `review.override` audit event. Every refusal below happens before the
    first INSERT, except a re-derivation refusal, which raises and so rolls
    the rows back with the transaction:

    * sheet not a child of this workbook -> 404
    * sheet not PENDING_REVIEW -> 409 (RUNNING: wait; COMMITTED: a T09
      correction; ABANDONED / SUPERSEDED / FAILED / REJECTED_TEMPLATE: there
      is no open review)
    * `review_revision` not the sheet's current one -> 409
    * `vehicle_id` not a set on this sheet, a `source_row` outside that set,
      a row that is not LOAD now, or a value equal to the proposed one -> 422
    """
    workbook = get_workbook(conn, plant_code, file_hash)
    _child_or_404(workbook, body.load_id)
    batch = batch_repo.get_batch_for_update(conn, body.load_id)
    if batch is None:  # pragma: no cover - the child check already proved it
        raise WorkbookError(404, f"No batch {body.load_id}.")

    status = batch["status"]
    if status != batch_repo.STATUS_PENDING_REVIEW:
        why = {
            batch_repo.STATUS_RUNNING: "It is still being parsed; wait for the worker.",
            batch_repo.STATUS_COMMITTED: (
                "It is committed: change a measurement with POST "
                "/api/v1/measurements/{measurement_id}/corrections instead."
            ),
        }.get(status, "It has no open review to change.")
        raise WorkbookError(
            409,
            f"Batch {body.load_id} is {status}, not PENDING_REVIEW, so no "
            f"override can be written. {why} Nothing was written.",
        )

    current = batch["review_revision"]
    current = str(current).strip() if current else None
    if not current or current != body.review_revision:
        raise WorkbookError(
            409,
            f"Batch {body.load_id} is at review revision "
            f"{(current or '(none)')[:12]}..., not "
            f"{body.review_revision[:12]}.... The rows changed after you "
            f"loaded them. Nothing was written. Re-read the vehicle set and "
            f"save again.",
        )

    rows, sets = _sheet_sets(
        conn, plant_code, file_hash, body.load_id, _expected_zones(conn),
        ws_points_repo.live_lists(conn, plant_code),
    )
    found = next((s for s in sets if s.vehicle_id == body.vehicle_id), None)
    if found is None:
        raise WorkbookError(
            422,
            f"vehicle_id {body.vehicle_id} is not a vehicle set of batch "
            f"{body.load_id}. Nothing was written.",
        )
    by_row = {r["source_row"]: r for r in rows}
    members = set(found.source_rows)

    planned: list[tuple] = []
    for change in body.changes:
        if change.source_row not in members:
            raise WorkbookError(
                422,
                f"row {change.source_row} is not part of vehicle set "
                f"{body.vehicle_id}. One save covers one vehicle set. Nothing "
                f"was written.",
            )
        row = by_row[change.source_row]
        if row["disposition"] != "LOAD":
            raise WorkbookError(
                422,
                f"row {change.source_row} is {row['disposition']}, not LOAD. "
                f"Only a row that would become a measurement can be "
                f"overridden; a rejected, quarantined or duplicate row is "
                f"acknowledged, mapped or re-sent, never promoted. Nothing "
                f"was written.",
            )
        previous = _proposed_measure(row["canonical"], change.field)
        new_value = change.decimal_value()
        if previous == new_value:
            raise WorkbookError(
                422,
                f"row {change.source_row} {change.field} is already "
                f"{previous if previous is not None else 'null'}. An override "
                f"has to change the proposed value. Nothing was written.",
            )
        planned.append((change, previous, new_value))

    stored = [
        override_repo.insert(
            conn,
            load_id=body.load_id,
            plant_code=plant_code,
            file_hash=file_hash,
            source_row=change.source_row,
            field=change.field,
            previous_proposed=previous,
            new_value=new_value,
            reason=change.reason,
            review_revision=current,
            actor_user_id=actor_user_id,
        )
        for change, previous, new_value in planned
    ]

    expected: dict[int, set[str]] = {}
    for change in body.changes:
        expected.setdefault(change.source_row, set()).add(change.field)
    try:
        outcome = ingest.revalidate_review(conn, batch, expected_overrides=expected)
    except IngestError as exc:
        raise WorkbookError(409, str(exc)) from exc

    audit.record(
        conn,
        action="review.override",
        entity_type="load_batch",
        entity_id=body.load_id,
        actor_user_id=actor_user_id,
        before={"review_revision": current},
        after={
            "load_id": body.load_id,
            "vehicle_id": body.vehicle_id,
            "file_hash": file_hash,
            "override_ids": [o["override_id"] for o in stored],
            "fields": [
                {
                    "source_row": o["source_row"],
                    "field": o["field"],
                    "previous_proposed": o["previous_proposed"],
                    "new_value": o["new_value"],
                    "reason": o["reason"],
                }
                for o in stored
            ],
            "review_revision": outcome["review_revision"],
        },
        correlation_id=correlation_id,
    )
    return {
        "load_id": body.load_id,
        "vehicle_id": body.vehicle_id,
        "overrides": stored,
        "previous_review_revision": current,
        "review_revision": outcome["review_revision"],
        "counts": outcome["counts"],
    }


__all__ = [
    "WorkbookError",
    "acknowledge",
    "override",
    "points",
    "vehicles",
    "detail",
    "get_workbook",
    "history",
    "issues",
    "list_workbooks",
    "resolve_plant",
    "rows",
]


# =====================================================================
# T37 -- permanent purge of one workbook (ADR 0011)
# =====================================================================
#: SQLSTATEs `purge_workbook` raises, and the HTTP status each means.
_PURGE_REFUSALS = {
    "P0002": 404,  # no_data_found: no such hash at this plant
    "22023": 422,  # invalid_parameter_value: blank reason / no actor
    "55006": 409,  # object_in_use: another file depends on this one
}


def purge_workbook(
    conn: Connection,
    plant_code: str,
    file_hash: str,
    *,
    reason: str,
    actor_user_id: str,
    correlation_id: str | None,
) -> dict:
    """Delete this plant + hash's rows. The stored bytes are not touched (D4).

    Afterwards the hash is gone, so uploading the same bytes is a new batch
    that goes through mapping again, not a T25 reopen.
    """
    plant = resolve_plant(conn, plant_code)
    try:
        result = repo.purge_workbook(
            conn,
            plant_code=plant["plant_code"],
            file_hash=file_hash,
            actor_user_id=actor_user_id,
            reason=reason,
            correlation_id=correlation_id,
        )
    except DBAPIError as exc:
        code = getattr(exc.orig, "sqlstate", None)
        status_code = _PURGE_REFUSALS.get(code)
        if status_code is None:
            raise
        message = getattr(getattr(exc.orig, "diag", None), "message_primary", None)
        raise WorkbookError(
            status_code, f"purge refused: {message or exc.orig}. Nothing was deleted."
        ) from exc
    return {
        "plant_code": plant["plant_code"],
        "file_hash": file_hash,
        "reason": reason.strip(),
        "load_ids": [int(i) for i in result["load_ids"]],
        "wavescan_deleted": int(result["wavescan_deleted"]),
        "batches_deleted": int(result["batches_deleted"]),
        "audit_id": int(result["audit_id"]),
    }
