"""T39 worksheet SQL: the Engineer's decisions and the checklist reads.

`worksheet_decision` is INSERT-only (revision 0016). A decision is re-applied
on every replay of its sheet, so a person answers once and the stored bytes
keep producing the same result. Every read here comes from what is stored --
the batch rows, the persisted review projection, `wavescan` -- and no
workbook is opened (T19 locked decision 1).
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.domain.reader import DOMAIN_WAVESCAN

#: The one batch status whose decisions are remembered for the pre-fill
#: (T107, D-107-4). Spelled here rather than imported from
#: `repositories.batches` so this module keeps importing no other
#: repository.
STATUS_COMMITTED = "COMMITTED"

KIND_IGNORE_HEADER = "IGNORE_HEADER"
KIND_PLANT_CONFIRM = "PLANT_CONFIRM"
KIND_HOLE_APPROVAL = "HOLE_APPROVAL"
#: T94 (revision 0032): which canonical panel a **rough** label is, for this
#: upload only. The subject is the pair, written below.
KIND_PANEL_CONFIRM = "PANEL_CONFIRM"
#: T99 (revision 0033): the uploader's three answers about a Film **sheet**.
#: ``FILM_MODEL_CONFLICT``'s subject is the chosen ``model_code`` (D-99-11),
#: ``FILM_JOB_UNUSUAL``'s is the Job Number read as written (D-99-10), and
#: ``FILM_WALK_CONFIRM``'s is one appended point, written below (D-99-14).
KIND_FILM_MODEL_CONFLICT = "FILM_MODEL_CONFLICT"
KIND_FILM_JOB_UNUSUAL = "FILM_JOB_UNUSUAL"
KIND_FILM_WALK_CONFIRM = "FILM_WALK_CONFIRM"
#: T109 (revision 0035, D-109-6): which live point a label this plant's list
#: does not hold is. The subject is the pair ``<label>=><point_code>``, the
#: same shape ``PANEL_CONFIRM`` writes, so a reader of the row can see both
#: halves of what was said. The alias itself is a `ref_film_point_alias` row;
#: this is the record of who said it about which upload.
KIND_FILM_POINT_ALIAS = "FILM_POINT_ALIAS"
#: RO18 (revision 0048). B4: the month a sheet with no date anywhere was
#: measured in, subject ``YYYY-MM``. B3: which date of a Film sheet is right,
#: subject ``sheet`` or ``file_name``. B5: a label answered "Not a point of
#: this list", subject the label as written (the answer itself is a
#: `ref_plant_film_tail_label` row with ``not_a_point``).
KIND_MONTH_ONLY = "MONTH_ONLY"
KIND_FILM_DATE_CHOICE = "FILM_DATE_CHOICE"
KIND_FILM_NOT_A_POINT = "FILM_NOT_A_POINT"
DATE_CHOICES = ("sheet", "file_name")
KINDS = (
    KIND_IGNORE_HEADER,
    KIND_PLANT_CONFIRM,
    KIND_HOLE_APPROVAL,
    KIND_PANEL_CONFIRM,
    KIND_FILM_MODEL_CONFLICT,
    KIND_FILM_JOB_UNUSUAL,
    KIND_FILM_WALK_CONFIRM,
    KIND_FILM_POINT_ALIAS,
    KIND_MONTH_ONLY,
    KIND_FILM_DATE_CHOICE,
    KIND_FILM_NOT_A_POINT,
)

#: T94: how a ``PANEL_CONFIRM`` subject carries three values in one text
#: column -- ``P703 DBL RANGER|01HOOD=>RRHOOD``. Neither separator is one a
#: panel name or a model code can contain: `normalise_alias` only trims and
#: case-folds, and no row of `ref_plant_ws_point`, `ref_model` or any file
#: read so far holds ``=`` or ``|``. :func:`panel_pair` refuses anything
#: else rather than guessing which part is which.
#:
#: The model is part of the subject because D-94-1 is scoped to ``(plant,
#: model)``: one sheet carries two models, and a label can be rough on one
#: and specific on the other. A subject written without a model (the first
#: shape of this row) applies to any model of the sheet, which is what it
#: meant when it was written.
PANEL_PAIR_SEP = "=>"
PANEL_MODEL_SEP = "|"


def panel_pair_subject(
    raw_zone_text: str, zone_code: str, model_code: str | None = None
) -> str:
    """The stored subject for one confirmed rough label."""
    pair = f"{str(raw_zone_text).strip()}{PANEL_PAIR_SEP}{str(zone_code).strip()}"
    model = (model_code or "").strip()
    return f"{model}{PANEL_MODEL_SEP}{pair}" if model else pair


def panel_pair(subject: str) -> tuple[str | None, str, str] | None:
    """``M|01HOOD=>RRHOOD`` -> ``("M", "01HOOD", "RRHOOD")``, else None.

    The model is None for a subject written without one. None for a subject
    that does not hold exactly one pair separator with nonblank text on both
    sides: a malformed row is ignored rather than half-read, because a panel
    identity guessed from a broken string is the silent wrong label
    `AGENTS.md` opens with.
    """
    text_value = str(subject)
    model: str | None = None
    if PANEL_MODEL_SEP in text_value:
        head, _, text_value = text_value.partition(PANEL_MODEL_SEP)
        model = head.strip() or None
    parts = text_value.split(PANEL_PAIR_SEP)
    if len(parts) != 2:
        return None
    raw, zone = parts[0].strip(), parts[1].strip()
    return (model, raw, zone) if raw and zone else None


def confirmed_panels_for_batch(
    conn: Connection, load_id: int
) -> dict[tuple[str | None, str], str]:
    """T94: ``{(model, panel as written): canonical zone_code}`` for one sheet.

    The latest answer wins per key, because the table is append-only
    (revision 0016) and a person may correct themselves: the row with the
    highest ``decision_id`` is the one that stands. Nothing is deleted to
    say so.
    """
    out: dict[tuple[str | None, str], str] = {}
    for (subject,) in conn.execute(
        text(
            "SELECT subject FROM worksheet_decision "
            "WHERE load_id = :load_id AND kind = :kind "
            "ORDER BY decision_id"
        ),
        {"load_id": load_id, "kind": KIND_PANEL_CONFIRM},
    ).all():
        pair = panel_pair(subject)
        if pair is not None:
            model, raw, zone = pair
            out[(model, raw)] = zone
    return out


def sheet_date_answers(conn: Connection, load_id: int) -> dict:
    """RO18 (B3 / B4): ``{"month": "YYYY-MM" or None, "date": "sheet" /
    "file_name" or None}`` for one tab, the latest answer of each kind."""
    out = {"month": None, "date": None}
    for kind, subject in conn.execute(
        text(
            "SELECT kind, subject FROM worksheet_decision "
            "WHERE load_id = :load_id AND kind = ANY(:kinds) "
            "ORDER BY decision_id"
        ),
        {"load_id": load_id, "kinds": [KIND_MONTH_ONLY, KIND_FILM_DATE_CHOICE]},
    ).all():
        out["month" if kind == KIND_MONTH_ONLY else "date"] = str(subject).strip()
    return out


def film_sheet_answers(conn: Connection, load_id: int) -> dict:
    """T99: the uploader's answers about this Film sheet, latest one each.

    ``{"model": chosen model_code or None, "job_as_written": bool}``. The
    walk confirm is deliberately **not** here: confirming an appended point
    writes the point onto the plant's own list (D-99-14), so the next replay
    reads the longer walk from `ref_plant_film_point` like any other point
    and needs no per-batch override. The ``FILM_WALK_CONFIRM`` row is the
    record of who said so, which `audit_event` and this table keep.
    """
    out = {"model": None, "job_as_written": False}
    for kind, subject in conn.execute(
        text(
            "SELECT kind, subject FROM worksheet_decision "
            "WHERE load_id = :load_id AND kind = ANY(:kinds) "
            "ORDER BY decision_id"
        ),
        {
            "load_id": load_id,
            "kinds": [KIND_FILM_MODEL_CONFLICT, KIND_FILM_JOB_UNUSUAL],
        },
    ).all():
        if kind == KIND_FILM_MODEL_CONFLICT:
            out["model"] = str(subject).strip() or None
        else:
            out["job_as_written"] = True
    return out


def committed_panel_confirms(
    conn: Connection,
    *,
    plant_code: str,
    exclude_load_id: int | None = None,
) -> list[dict]:
    """T107 (D-107-1): the in-row panel confirms this plant has committed.

    One row per stored ``PANEL_CONFIRM`` decision of a batch that is
    ``COMMITTED`` and not superseded (D-107-4: a purged or retired sheet is
    not remembered), newest batch first and, inside a batch, in the order
    the decisions were written so the latest answer for a spelling is the
    one that stands -- the same rule :func:`confirmed_panels_for_batch`
    reads one sheet by.

    This is the batch-side read T90's ``confirmed_walk_sets`` is, for the
    other half of the same memory: the review screen's in-row confirm
    writes a ``worksheet_decision`` and no proposal (D-94-3), so without
    this read the one-click path the owner actually uses leaves next month
    nothing to be pre-filled from (T98 section 1). It stays a **pre-fill**
    read: nothing here is a ``ref_*`` row, `load_reference_data` cannot see
    this table, and so a rough label still cannot resolve automatically.
    """
    return [
        dict(row)
        for row in conn.execute(
            text(
                """
                SELECT d.load_id, d.subject, d.decision_id,
                       b.source_file, b.source_sheet, b.status,
                       b.finished_at AS committed_at
                  FROM worksheet_decision d
                  JOIN load_batch b ON b.load_id = d.load_id
                 WHERE d.kind = :kind
                   AND b.plant_code = :plant
                   AND b.domain = :domain
                   AND b.status = :committed
                   AND b.superseded_by IS NULL
                   AND (CAST(:exclude AS bigint) IS NULL
                        OR d.load_id IS DISTINCT FROM CAST(:exclude AS bigint))
                 ORDER BY b.finished_at DESC NULLS LAST, d.decision_id
                """
            ),
            {
                "kind": KIND_PANEL_CONFIRM,
                "plant": plant_code,
                "domain": DOMAIN_WAVESCAN,
                "committed": STATUS_COMMITTED,
                "exclude": exclude_load_id,
            },
        ).mappings().all()
    ]


def confirmed_walk_points(conn: Connection, load_id: int) -> list[str]:
    """T99 (D-99-14): the point names this upload's walk confirm added."""
    return [
        str(subject).split(FILM_POINT_SEP)[0].strip()
        for (subject,) in conn.execute(
            text(
                "SELECT subject FROM worksheet_decision "
                "WHERE load_id = :load_id AND kind = :kind ORDER BY decision_id"
            ),
            {"load_id": load_id, "kind": KIND_FILM_WALK_CONFIRM},
        ).all()
    ]


#: T99 (D-99-14): ``098TGATEIN|true|V`` -- the point, whether it counts, and
#: its Hor / Ver, in one subject column. ``|`` is a separator no point name
#: can hold (`ref_film_point` upper-cases and trims and no walked name has
#: ever carried one).
FILM_POINT_SEP = "|"


def film_point_subject(point_code: str, counted: bool, orientation: str) -> str:
    return FILM_POINT_SEP.join(
        (str(point_code).strip(), "true" if counted else "false",
         str(orientation).strip())
    )


def film_alias_subject(raw_location: str, point_code: str) -> str:
    """T109 (D-109-6): ``029LTFTDOOR=>022LTFTDOOR`` -- the label, then the
    live point a person said it is."""
    return f"{str(raw_location).strip()}{PANEL_PAIR_SEP}{str(point_code).strip()}"


def insert_decision(
    conn: Connection,
    *,
    load_id: int,
    kind: str,
    subject: str,
    actor_user_id: str,
    note: str | None,
) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO worksheet_decision
                    (load_id, kind, subject, actor_user_id, note)
                VALUES (:load_id, :kind, :subject, CAST(:actor AS uuid), :note)
                RETURNING decision_id
                """
            ),
            {
                "load_id": load_id,
                "kind": kind,
                "subject": subject,
                "actor": actor_user_id,
                "note": note,
            },
        ).scalar_one()
    )


def decisions_for_batch(conn: Connection, load_id: int) -> dict[str, set[str]]:
    """Every decision subject for one sheet, by kind."""
    out: dict[str, set[str]] = {kind: set() for kind in KINDS}
    for kind, subject in conn.execute(
        text(
            "SELECT kind, subject FROM worksheet_decision "
            "WHERE load_id = :load_id"
        ),
        {"load_id": load_id},
    ).all():
        out.setdefault(kind, set()).add(subject)
    return out


def batches_at_plant(conn: Connection, plant_code: str, file_hash: str) -> list[dict]:
    """Every sheet of one workbook at one plant, with its fact count."""
    rows = conn.execute(
        text(
            """
            SELECT b.load_id, b.source_file, b.source_sheet, b.status,
                   b.plant_code, b.file_hash, b.sheet_class,
                   b.unreviewed_headers, b.raw_headers, b.review_revision,
                   b.rows_in_file, b.rows_loaded, b.rows_duplicate,
                   b.rows_rejected, b.rows_quarantine, b.profile_id,
                   (SELECT count(*) FROM wavescan w
                     WHERE w.load_id = b.load_id
                       AND w.corrects_measurement_id IS NULL)
                   -- T54: a film row is one source row with up to four
                   -- layer facts; count it once.
                   + (SELECT count(DISTINCT f.source_row) FROM filmthickness f
                       WHERE f.load_id = b.load_id
                         AND f.corrects_measurement_id IS NULL) AS facts
              FROM load_batch b
             WHERE b.plant_code = :plant AND b.file_hash = :hash
               AND b.sheet_class IS DISTINCT FROM 'OUT_OF_SCOPE_SHEET'
             ORDER BY b.load_id
            """
        ),
        {"plant": plant_code, "hash": file_hash},
    ).mappings().all()
    return [dict(r) for r in rows]


def fact_source_rows(conn: Connection, load_id: int) -> set[int]:
    """Source rows of this sheet that are already measurements (either domain)."""
    return {
        int(r[0])
        for r in conn.execute(
            text(
                "SELECT source_row FROM wavescan "
                "WHERE load_id = :load_id AND corrects_measurement_id IS NULL "
                "UNION "
                "SELECT source_row FROM filmthickness "
                "WHERE load_id = :load_id AND corrects_measurement_id IS NULL"
            ),
            {"load_id": load_id},
        ).all()
    }


def held_rows(conn: Connection, load_id: int) -> list[dict]:
    """REJECT / QUARANTINE projection rows that are not already facts.

    A row a later insert pass loaded is no longer held, even though the
    projection of a committed sheet cannot be re-written (its staging is
    evidence of committed measurements, ADR 0005).
    """
    rows = conn.execute(
        text(
            """
            SELECT r.source_row, r.disposition, r.reason, r.detail,
                   coalesce(r.canonical ->> 'offending_column',
                            CASE WHEN r.reason = 'UNIDENTIFIED_MODEL'
                                 THEN 'model' END, '') AS label_column,
                   coalesce(r.canonical ->> 'offending_value',
                            r.canonical ->> 'raw_model', '') AS raw_value
              FROM stg_review_row r
             WHERE r.load_id = :load_id
               AND r.disposition IN ('REJECT', 'QUARANTINE')
               AND NOT EXISTS (
                   SELECT 1 FROM wavescan w
                    WHERE w.load_id = r.load_id
                      AND w.source_row = r.source_row
                      AND w.corrects_measurement_id IS NULL)
               AND NOT EXISTS (
                   SELECT 1 FROM filmthickness f
                    WHERE f.load_id = r.load_id
                      AND f.source_row = r.source_row
                      AND f.corrects_measurement_id IS NULL)
             ORDER BY r.source_row
            """
        ),
        {"load_id": load_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def vehicle_rows(conn: Connection, load_id: int) -> list[dict]:
    """Projection rows with their canonical, for vehicle-set counts."""
    rows = conn.execute(
        text(
            "SELECT source_row, disposition, canonical FROM stg_review_row "
            "WHERE load_id = :load_id ORDER BY source_row"
        ),
        {"load_id": load_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def preview_rows(conn: Connection, load_id: int) -> list[dict]:
    """T53: every projection row of one sheet, with the file's own words."""
    rows = conn.execute(
        text(
            "SELECT source_row, disposition, reason, detail, canonical, raw "
            "FROM stg_review_row WHERE load_id = :load_id ORDER BY source_row"
        ),
        {"load_id": load_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def max_measurement_id(conn: Connection, load_ids: list[int]) -> int:
    """Highest measurement_id these sheets hold now, 0 when none."""
    if not load_ids:
        return 0
    return int(
        conn.execute(
            text(
                "SELECT coalesce(max(measurement_id), 0) FROM wavescan "
                "WHERE load_id = ANY(:ids)"
            ),
            {"ids": load_ids},
        ).scalar_one()
    )


def fact_months(
    conn: Connection, load_ids: list[int], *, after_measurement_id: int = 0
) -> list[str]:
    """T53: YYYY-MM of the measurements these sheets hold, oldest first.

    ``after_measurement_id`` keeps only WaveScan rows inserted after that id,
    so a later insert pass names the months it actually added to. T54: Film
    facts are counted only for a first load (``after_measurement_id = 0``);
    a Film tab has no later insert pass and its ids are a second sequence.
    """
    if not load_ids:
        return []
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT m FROM ("
                "  SELECT to_char(measured_date, 'YYYY-MM') AS m FROM wavescan "
                "   WHERE load_id = ANY(:ids) AND measurement_id > :after "
                "     AND corrects_measurement_id IS NULL "
                "  UNION "
                "  SELECT to_char(measured_date, 'YYYY-MM') FROM filmthickness "
                "   WHERE load_id = ANY(:ids) AND :after = 0 "
                "     AND corrects_measurement_id IS NULL"
                ") months ORDER BY m"
            ),
            {"ids": load_ids, "after": after_measurement_id},
        ).all()
    ]


__all__ = [
    "KIND_IGNORE_HEADER",
    "KIND_PLANT_CONFIRM",
    "KIND_HOLE_APPROVAL",
    "KIND_PANEL_CONFIRM",
    "KIND_FILM_MODEL_CONFLICT",
    "KIND_FILM_JOB_UNUSUAL",
    "KIND_FILM_WALK_CONFIRM",
    "KIND_FILM_POINT_ALIAS",
    "KIND_MONTH_ONLY",
    "KIND_FILM_DATE_CHOICE",
    "KIND_FILM_NOT_A_POINT",
    "DATE_CHOICES",
    "KINDS",
    "sheet_date_answers",
    "FILM_POINT_SEP",
    "PANEL_MODEL_SEP",
    "PANEL_PAIR_SEP",
    "committed_panel_confirms",
    "confirmed_panels_for_batch",
    "confirmed_walk_points",
    "film_point_subject",
    "film_alias_subject",
    "film_sheet_answers",
    "panel_pair",
    "panel_pair_subject",
    "insert_decision",
    "decisions_for_batch",
    "batches_at_plant",
    "fact_source_rows",
    "held_rows",
    "vehicle_rows",
    "preview_rows",
    "fact_months",
    "max_measurement_id",
]
