"""Everything the ingest service writes, and the batch reads that go with it.

Three rules bound this module and none of them are style:

* **No UPDATE and no DELETE of `wavescan`.** ADR 0005. The application role
  does not hold either privilege, so a mistake here is a database error, not
  a silent rewrite -- but the mistake should not be written in the first
  place. The retirement flag is never set here; it moves only by inserting a
  `measurement_supersession` row, which a T02 trigger acts on.
* **`load_batch` is updated by column, never wholesale.** The grant is
  column-scoped (`01-DATA-MODEL.md` §8), so the statements below name exactly
  the columns a batch's lifecycle is allowed to move.
* **Staging is committed separately from the facts.** `02-PIPELINE.md` §6:
  when a load fails, the staged rows stay for investigation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

from sqlalchemy import Connection, text

from app.domain.cleaner import CleanRow, PAINTLINE_OMITTED_SENTINEL, Reject, Unidentified
from app.domain.dedup import DuplicateInfo
from app.domain.reader import MEASURE_ALL, STAGED_FIELDS, RawRow

@dataclass(frozen=True)
class ReviewRow:
    """One row of the persisted review projection.

    Built by the ingest service from the same plan commit would insert, so
    "what the reviewer saw" and "what commit writes" cannot drift without the
    revision hash changing.
    """

    source_row: int
    disposition: str
    reason: str | None
    detail: str | None
    canonical: dict
    raw: dict
    normalized_fields: tuple[str, ...]
    profile_id: int | None
    template_fingerprint: str
    review_revision: str


#: `01-DATA-MODEL.md` §3. RUNNING is the only non-terminal state.
STATUS_RUNNING = "RUNNING"
STATUS_PENDING_REVIEW = "PENDING_REVIEW"
STATUS_COMMITTED = "COMMITTED"
STATUS_FAILED = "FAILED"
STATUS_REJECTED_TEMPLATE = "REJECTED_TEMPLATE"
#: T21. Written only by `CorrectionService.abandon_batch`, never by ingest.
STATUS_ABANDONED = "ABANDONED"
#: Written only by the correction service's retire route, never by ingest.
STATUS_SUPERSEDED = "SUPERSEDED"
#: T25: a batch in either of these is out of the workflow, and identical
#: bytes of it are reopened rather than refused. Every other status is live.
RETIRED_STATUSES = (STATUS_ABANDONED, STATUS_SUPERSEDED)
#: T25: retired statuses whose facts are in `wavescan`. Bringing one back
#: puts measurements back into the active reads, which is an Admin decision.
#: Named here so the ingest service can classify a prior batch without ever
#: spelling a retired status itself (T21 keeps it from writing one).
ADMIN_ONLY_RESTORE_STATUSES = (STATUS_SUPERSEDED,)


@dataclass(frozen=True)
class BatchCounts:
    rows_in_file: int
    rows_loaded: int
    rows_duplicate: int
    rows_rejected: int
    rows_quarantine: int

    @property
    def balanced(self) -> bool:
        """`02-PIPELINE.md` §6, the hard gate."""
        return self.rows_in_file == (
            self.rows_loaded + self.rows_duplicate
            + self.rows_rejected + self.rows_quarantine
        )

    def as_dict(self) -> dict:
        return {
            "rows_in_file": self.rows_in_file,
            "rows_loaded": self.rows_loaded,
            "rows_duplicate": self.rows_duplicate,
            "rows_rejected": self.rows_rejected,
            "rows_quarantine": self.rows_quarantine,
        }


# =====================================================================
# reads
# =====================================================================
BATCH_COLUMNS = """
    b.load_id, b.source_file, b.source_sheet, b.plant_code, b.file_hash,
    b.status, b.rows_in_file, b.rows_loaded, b.rows_duplicate,
    b.rows_rejected, b.rows_quarantine,
    b.started_at, b.finished_at, b.loaded_by, b.notes, b.superseded_by,
    b.raw_store_key, b.template_fingerprint, b.raw_headers,
    b.profile_id, b.review_revision,
    b.domain, b.semantic_signature, b.sheet_class, b.unreviewed_headers
"""

#: Every batch read carries its profile's verification state, because
#: `committable` depends on it and a reviewer listing forty batches must not
#: cost forty extra queries. LEFT JOIN: a batch whose layout has no profile is
#: a normal batch (it is REJECTED_TEMPLATE), not a missing row.
BATCH_SELECT = f"""
    SELECT {BATCH_COLUMNS},
           p.fixture_verified AS profile_fixture_verified,
           p.is_active        AS profile_is_active,
           p.fill_missing_plant AS profile_fill_missing_plant
      FROM load_batch b
      LEFT JOIN ref_template_profile p ON p.profile_id = b.profile_id
"""


def get_batch(conn: Connection, load_id: int) -> dict | None:
    row = conn.execute(
        text(f"{BATCH_SELECT} WHERE b.load_id = :load_id"),
        {"load_id": load_id},
    ).mappings().first()
    return dict(row) if row else None


def get_batch_for_update(conn: Connection, load_id: int) -> dict | None:
    """Lock one batch so two commits of the same batch serialise.

    `FOR UPDATE OF b`: the profile joined alongside is reference data that
    this transaction reads and never writes, and locking it would make two
    commits of two different batches of the same layout queue behind each
    other for no reason.
    """
    row = conn.execute(
        text(f"{BATCH_SELECT} WHERE b.load_id = :load_id FOR UPDATE OF b"),
        {"load_id": load_id},
    ).mappings().first()
    return dict(row) if row else None


def list_batches(conn: Connection, limit: int, offset: int) -> list[dict]:
    rows = conn.execute(
        text(f"{BATCH_SELECT} WHERE b.sheet_class IS DISTINCT FROM 'OUT_OF_SCOPE_SHEET' "
             "ORDER BY b.load_id DESC LIMIT :limit OFFSET :offset"),
        {"limit": limit, "offset": offset},
    ).mappings().all()
    return [dict(r) for r in rows]


def count_batches(conn: Connection) -> int:
    return int(conn.execute(text("SELECT count(*) FROM load_batch "
                                 "WHERE sheet_class IS DISTINCT FROM 'OUT_OF_SCOPE_SHEET'")).scalar_one())


def find_by_hash(conn: Connection, file_hash: str) -> list[dict]:
    """Every batch already holding these exact bytes (`02-PIPELINE.md` section 3).

    T25: `plant_code` is part of the answer, because identical bytes of an
    ABANDONED or SUPERSEDED workbook are reopened rather than refused -- but
    only when they arrive for the plant they were filed under.
    """
    rows = conn.execute(
        text(
            "SELECT load_id, source_file, source_sheet, status, started_at, "
            "plant_code, sheet_class "
            "FROM load_batch WHERE file_hash = :h ORDER BY load_id"
        ),
        {"h": file_hash},
    ).mappings().all()
    return [dict(r) for r in rows]


def batch_review(conn: Connection, load_id: int) -> dict:
    """What a reviewer needs before pressing commit, without the raw rows."""
    rejects = conn.execute(
        text(
            "SELECT reject_reason, count(*) AS n FROM reject_log "
            "WHERE load_id = :load_id GROUP BY reject_reason ORDER BY n DESC"
        ),
        {"load_id": load_id},
    ).mappings().all()
    unidentified = conn.execute(
        text(
            "SELECT count(*) FROM unidentified_model WHERE load_id = :load_id"
        ),
        {"load_id": load_id},
    ).scalar_one()
    staged = conn.execute(
        text("SELECT count(*) FROM stg_raw WHERE load_id = :load_id"),
        {"load_id": load_id},
    ).scalar_one()
    return {
        "reject_reasons": {r["reject_reason"]: int(r["n"]) for r in rejects},
        "unidentified_rows": int(unidentified),
        "staged_rows": int(staged),
    }


# =====================================================================
# writes
# =====================================================================
def create_batch(
    conn: Connection,
    *,
    source_file: str,
    source_sheet: str,
    file_hash: str,
    raw_store_key: str,
    plant_code: str | None,
    loaded_by: str | None,
    template_fingerprint: str | None,
    raw_headers: dict | None,
    profile_id: int | None = None,
    notes: str | None = None,
    domain: str | None = None,
    semantic_signature: str | None = None,
    sheet_class: str | None = None,
    unreviewed_headers: list[str] | None = None,
) -> int:
    """Open a batch. Provenance is set here and never updated afterwards.

    T18: `profile_id` is the template profile the layout selected at upload,
    or NULL when this plant has no active profile for this fingerprint -- and
    NULL is why such a batch never parses a data row.
    """
    return int(
        conn.execute(
            text(
                """
                INSERT INTO load_batch
                    (source_file, source_sheet, plant_code, file_hash,
                     raw_store_key, status, rows_in_file, loaded_by,
                     template_fingerprint, raw_headers, profile_id, notes,
                     domain, semantic_signature, sheet_class,
                     unreviewed_headers)
                VALUES
                    (:source_file, :source_sheet, :plant_code, :file_hash,
                     :raw_store_key, :status, 0, :loaded_by,
                     :fingerprint, CAST(:raw_headers AS jsonb), :profile_id,
                     :notes, :domain, :semantic_signature, :sheet_class,
                     CAST(:unreviewed_headers AS jsonb))
                RETURNING load_id
                """
            ),
            {
                "source_file": source_file,
                "source_sheet": source_sheet,
                "plant_code": plant_code,
                "file_hash": file_hash,
                "raw_store_key": raw_store_key,
                "status": STATUS_RUNNING,
                "loaded_by": loaded_by,
                "fingerprint": template_fingerprint,
                "raw_headers": json.dumps(raw_headers) if raw_headers else None,
                "profile_id": profile_id,
                "notes": notes,
                "domain": domain,
                "semantic_signature": semantic_signature,
                "sheet_class": sheet_class,
                "unreviewed_headers": (
                    json.dumps(list(unreviewed_headers))
                    if unreviewed_headers is not None else None
                ),
            },
        ).scalar_one()
    )


def set_batch_outcome(
    conn: Connection,
    load_id: int,
    *,
    status: str,
    counts: BatchCounts | None = None,
    plant_code: str | None = None,
    profile_id: int | None = None,
    review_revision: str | None = None,
    notes: str | None = None,
    finished: bool = True,
    domain: str | None = None,
    semantic_signature: str | None = None,
    sheet_class: str | None = None,
    unreviewed_headers: list[str] | None = None,
) -> None:
    """Move a batch's status and counts. Column-scoped, as the grant is.

    T26 adds the four columns the worker derives about the *sheet* rather
    than about its rows: which vocabulary read it, which contract it carries,
    what kind of sheet it turned out to be, and which of its headers nobody
    has decided about. All four are re-derived on every replay, and all four
    are named in revision 0009's UPDATE allow-list.
    """
    sets = ["status = :status"]
    params: dict = {"status": status, "load_id": load_id}
    if counts is not None:
        for key, value in counts.as_dict().items():
            sets.append(f"{key} = :{key}")
            params[key] = value
    if plant_code is not None:
        sets.append("plant_code = :plant_code")
        params["plant_code"] = plant_code
    if profile_id is not None:
        sets.append("profile_id = :profile_id")
        params["profile_id"] = profile_id
    if review_revision is not None:
        sets.append("review_revision = :review_revision")
        params["review_revision"] = review_revision
    if notes is not None:
        sets.append("notes = :notes")
        params["notes"] = notes
    for column, value in (
        ("domain", domain),
        ("semantic_signature", semantic_signature),
        ("sheet_class", sheet_class),
    ):
        if value is not None:
            sets.append(f"{column} = :{column}")
            params[column] = value
    if unreviewed_headers is not None:
        sets.append("unreviewed_headers = CAST(:unreviewed_headers AS jsonb)")
        params["unreviewed_headers"] = json.dumps(list(unreviewed_headers))
    if finished:
        sets.append("finished_at = now()")
    conn.execute(
        text(f"UPDATE load_batch SET {', '.join(sets)} WHERE load_id = :load_id"),
        params,
    )


STAGE_COLUMNS = tuple(f"raw_{f}" for f in STAGED_FIELDS)


def stage_rows(conn: Connection, load_id: int, rows: Iterable[RawRow]) -> int:
    """`stg_raw`: verbatim text, plus anything no alias recognised.

    `01-DATA-MODEL.md` §4 -- nothing a file said is lost just because a
    column had no alias yet.
    """
    sql = text(
        f"INSERT INTO stg_raw (load_id, source_row, {', '.join(STAGE_COLUMNS)}, extra) "
        f"VALUES (:load_id, :source_row, "
        f"{', '.join(':' + c for c in STAGE_COLUMNS)}, CAST(:extra AS jsonb))"
    )
    payload = []
    for raw in rows:
        entry = {"load_id": load_id, "source_row": raw.source_row}
        for field_name, column in zip(STAGED_FIELDS, STAGE_COLUMNS):
            entry[column] = raw.text(field_name)
        entry["extra"] = json.dumps(
            {k: _jsonable(v) for k, v in raw.extra.items()}, default=str
        )
        payload.append(entry)
    if payload:
        conn.execute(sql, payload)
    return len(payload)


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def insert_review_rows(
    conn: Connection,
    load_id: int,
    rows: Sequence["ReviewRow"],
) -> int:
    """The review projection: one row per source row (T18, design section 6).

    Written in the same transaction as `stg_raw`, so a reviewer never sees a
    batch whose staging and projection describe different parses. There is no
    UPDATE statement in this module for this table and no grant to write one
    with: a proposed value is replaced by replaying the bytes, never edited.
    """
    sql = text(
        """
        INSERT INTO stg_review_row
            (load_id, source_row, disposition, reason, detail,
             canonical, raw, normalized_fields,
             profile_id, template_fingerprint, review_revision)
        VALUES (:load_id, :source_row, :disposition, :reason, :detail,
                CAST(:canonical AS jsonb), CAST(:raw AS jsonb),
                CAST(:normalized AS jsonb),
                :profile_id, :fingerprint, :revision)
        """
    )
    payload = [
        {
            "load_id": load_id,
            "source_row": r.source_row,
            "disposition": r.disposition,
            "reason": r.reason,
            "detail": r.detail,
            "canonical": json.dumps(r.canonical, default=str),
            "raw": json.dumps(r.raw, default=str),
            "normalized": json.dumps(list(r.normalized_fields)),
            "profile_id": r.profile_id,
            "fingerprint": r.template_fingerprint,
            "revision": r.review_revision,
        }
        for r in rows
    ]
    if payload:
        conn.execute(sql, payload)
    return len(payload)


def count_review_rows(conn: Connection, load_id: int) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM stg_review_row WHERE load_id = :load_id"),
            {"load_id": load_id},
        ).scalar_one()
    )


def review_dispositions(conn: Connection, load_id: int) -> dict[str, int]:
    """Counts by disposition, for a reviewer and for the blocker checks."""
    rows = conn.execute(
        text(
            "SELECT disposition, count(*) AS n FROM stg_review_row "
            "WHERE load_id = :load_id GROUP BY disposition"
        ),
        {"load_id": load_id},
    ).mappings().all()
    return {r["disposition"]: int(r["n"]) for r in rows}


def loadable_rows_without_serial(conn: Connection, load_id: int) -> int:
    """LOAD rows whose canonical serial is missing (T18, M7).

    Read from the persisted projection rather than by re-parsing the
    workbook: `GET /batches/{id}` must not open Excel (design section 6).
    """
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM stg_review_row "
                "WHERE load_id = :load_id AND disposition = 'LOAD' "
                "AND (canonical ->> 'serial_no') IS NULL"
            ),
            {"load_id": load_id},
        ).scalar_one()
    )


def replayable_for_signature(
    conn: Connection, plant_code: str, domain: str, semantic_signature: str
) -> list[int]:
    """Batches of this plant and contract that a publish should re-derive.

    Spec section 6: publishing a profile replays the batches it unblocks. The
    scope is deliberately narrow -- this plant, this domain, this semantic
    contract, and only the two statuses `02-PIPELINE.md` section 8 already
    calls replayable. A batch that has produced measurements is never in that
    set, and replay never commits anything, so the worst this can do is put a
    reviewable sheet back in front of a person.
    """
    listed = ", ".join(f"'{s}'" for s in REPLAYABLE_STATUSES)
    rows = conn.execute(
        text(
            f"SELECT load_id FROM load_batch "
            f"WHERE plant_code = :plant AND domain = :domain "
            f"AND semantic_signature = :sig AND status IN ({listed}) "
            f"ORDER BY load_id"
        ),
        {"plant": plant_code, "domain": domain, "sig": semantic_signature},
    ).all()
    return [int(r[0]) for r in rows]


def held_for_model_offer(conn: Connection, plant_code: str) -> list[int]:
    """T115 (D-115-4): the batches an Attach at this plant reloads.

    Every batch of this plant, either domain, that (a) is in
    `REPLAYABLE_STATUSES`, (b) has produced no measurement, and (c) holds at
    least one `MODEL_NOT_OFFERED` row in `reject_log` -- where Wave Scan and
    Film both write that hold (`services/ingest.py`, `insert_rejects`). The
    same rule template publish replays by; `replay_batch` re-checks (a) and
    (b) on the locked row, so this list is the candidates, not the guarantee.

    T115-FIX (D-115F-3): `FILM_ONLY_MODEL` is deliberately not selected. A
    Film-only model on a Wave Scan sheet holds again after any Attach, so a
    sheet held only for that is never replayed.
    """
    listed = ", ".join(f"'{s}'" for s in REPLAYABLE_STATUSES)
    rows = conn.execute(
        text(
            f"""
            SELECT b.load_id FROM load_batch b
             WHERE b.plant_code = :plant AND b.status IN ({listed})
               AND EXISTS (SELECT 1 FROM reject_log r
                            WHERE r.load_id = b.load_id
                              AND r.reject_reason = 'MODEL_NOT_OFFERED')
               AND NOT EXISTS (SELECT 1 FROM wavescan w
                                WHERE w.load_id = b.load_id)
               AND NOT EXISTS (SELECT 1 FROM filmthickness f
                                WHERE f.load_id = b.load_id)
             ORDER BY b.load_id
            """
        ),
        {"plant": plant_code},
    ).all()
    return [int(r[0]) for r in rows]


def loadable_rows_without_paintline(conn: Connection, load_id: int) -> int:
    """LOAD rows whose canonical paintline is missing (T26, spec S18).

    Same shape and same reason as the serial count above: read from the
    persisted projection, never by re-opening the workbook. A blank paintline
    on a row that would load is a commit gate, not a licence to mint one from
    the filename or from what the neighbouring rows said.

    Sentinel-omitted paintline (``(None)``) is not this gate: the projection
    stores ``paintline_omitted_reason`` so GET and commit agree (spec P8).
    """
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM stg_review_row "
                "WHERE load_id = :load_id AND disposition = 'LOAD' "
                "AND coalesce(btrim(canonical ->> 'paintline'), '') = '' "
                "AND coalesce(canonical ->> 'paintline_omitted_reason', '') "
                "    <> :sentinel"
            ),
            {"load_id": load_id, "sentinel": PAINTLINE_OMITTED_SENTINEL},
        ).scalar_one()
    )


def rows_rejected_for_missing_serial(conn: Connection, load_id: int) -> int:
    """Rows this parse refused because the vehicle had no identity.

    The SAP case (M7): the column exists, every cell is blank, and the plant
    requires a serial. Those rows are rejects rather than LOAD rows, so the
    count above cannot see them -- but a batch that is *entirely* these is a
    workbook with no vehicle identity, not a workbook with bad values.
    """
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM stg_review_row "
                "WHERE load_id = :load_id AND disposition = 'REJECT' "
                "AND reason = 'MISSING_REQUIRED_FIELD' "
                "AND (canonical ->> 'offending_column') = 'serial_no'"
            ),
            {"load_id": load_id},
        ).scalar_one()
    )


def held_label_groups(conn: Connection, load_id: int) -> list[dict]:
    """Distinct REJECT / QUARANTINE spellings for the held-label list.

    Read from the persisted projection (T18): GET never opens Excel.
    Aggregates and LOAD rows are not held labels. The raw value is the
    offending cell, or the unidentified model spelling.
    """
    rows = conn.execute(
        text(
            """
            SELECT
                reason,
                coalesce(
                    canonical ->> 'offending_column',
                    CASE WHEN reason = 'UNIDENTIFIED_MODEL' THEN 'model' END,
                    ''
                ) AS label_column,
                coalesce(
                    canonical ->> 'offending_value',
                    canonical ->> 'raw_model',
                    ''
                ) AS raw_value,
                count(*)::int AS n,
                -- T98 (D-98-1): the details, so the screen can name the
                -- measures actually missing instead of only the first.
                array_remove(array_agg(DISTINCT detail), NULL) AS details
            FROM stg_review_row r
            WHERE load_id = :load_id
              AND disposition IN ('REJECT', 'QUARANTINE')
              AND reason IS NOT NULL
              -- T39: a row a later insert pass loaded is no longer held.
              AND NOT EXISTS (
                  SELECT 1 FROM wavescan w
                   WHERE w.load_id = r.load_id
                     AND w.source_row = r.source_row
                     AND w.corrects_measurement_id IS NULL)
            GROUP BY 1, 2, 3
            ORDER BY n DESC, reason, label_column, raw_value
            """
        ),
        {"load_id": load_id},
    ).mappings().all()
    return [
        {
            "reason": r["reason"],
            "column": r["label_column"],
            "raw_value": r["raw_value"],
            "n": r["n"],
            "details": list(r["details"] or ()),
        }
        for r in rows
    ]


def panels_already_used(
    conn: Connection, load_id: int, model_code: str
) -> set[str]:
    """Panels this batch has **already loaded** rows on, for this model.

    **T88.** Measured on `61551`: ``06LFFENDER`` loaded onto ``LFFENDER``
    and ``11ROOF`` onto the numbered panel ``11ROOF``. Those panels are
    spoken for by this very file, so offering one of them to another held
    spelling would break the bijection D-88-2 asks for -- across the batch,
    not just across the unmatched part of it -- and is exactly how a wrong
    exhaustion claim would arise.
    """
    return {
        row[0]
        for row in conn.execute(
            text(
                "SELECT DISTINCT checkzone FROM wavescan "
                " WHERE load_id = :load_id AND model = :model "
                "   AND corrects_measurement_id IS NULL"
            ),
            {"load_id": load_id, "model": model_code},
        ).all()
    }


def panels_already_used_by(
    conn: Connection, load_id: int, model_code: str
) -> dict[str, str]:
    """Which **file spelling** took each panel this batch already loaded onto.

    **T89 (D-89-6).** `panels_already_used` answers *which panels are
    spoken for*; the picker also has to say *by what*, because "LFFENDER is
    not on offer" is a dead end and "already matched to 06LFFENDER" is an
    explanation a reviewer can act on. The spelling is `src_zone_text` --
    what the file wrote -- which is the name the person is looking at on
    the other rows of the same sheet.

    One panel can have been written more than one way in one batch (that
    is August's defect); the spellings are joined with ", " so the label
    never silently picks one of them.
    """
    out: dict[str, set[str]] = {}
    for checkzone, spelling in conn.execute(
        text(
            """
            SELECT DISTINCT checkzone,
                   coalesce(nullif(btrim(src_zone_text), ''), checkzone)
              FROM wavescan
             WHERE load_id = :load_id AND model = :model
               AND corrects_measurement_id IS NULL
            """
        ),
        {"load_id": load_id, "model": model_code},
    ).all():
        out.setdefault(checkzone, set()).add(spelling)
    return {zone: ", ".join(sorted(names)) for zone, names in out.items()}


def file_panel_count(
    conn: Connection, load_id: int, model_code_texts: Sequence[str]
) -> int:
    """How many distinct panels this file walks for one model.

    **T88 (G-88-2).** The warning compares the catalogue's live count with
    what the **file** walks -- all 32 of September's panels, not only the 22
    still held. Counting the held ones would shrink the warning every time
    the owner matched one, which is backwards: the catalogue ambiguity does
    not get smaller as they work.
    """
    if not model_code_texts:
        return 0
    return int(
        conn.execute(
            text(
                """
                SELECT count(DISTINCT coalesce(
                           r.canonical ->> 'offending_value',
                           r.raw -> 'values' ->> 'checkzone', ''))
                  FROM stg_review_row r
                 WHERE r.load_id = :load_id
                   AND coalesce(r.raw -> 'values' ->> 'model', '') = ANY(:models)
                """
            ),
            {"load_id": load_id, "models": list(model_code_texts)},
        ).scalar_one()
    )


def walk_rows(conn: Connection, load_id: int) -> list[dict]:
    """T90: every row of this sheet, in the order the file wrote it.

    The structural matcher needs the **whole** walk, not the held part of
    it: September holds 22 of its 32 panel names and the other 10 resolve
    onto the T58 numbered gold list, so a fingerprint built from the held
    rows alone would be a fingerprint of a different walk (D-90-4).

    Read from `raw -> values` rather than from `canonical` on purpose, and
    this is the one read here that does so. A held row's canonical carries
    no identity at all -- `{"offending_value": "07LFFENDER",
    "offending_column": "checkzone"}` is the whole of it -- so taking the
    vehicle and the panel from the canonical would see the walk only where
    it already works. The raw cells are what the file wrote, which is
    exactly what a structural reading is about.

    The vehicle key is the platform's own vehicle identity minus the model
    (`domain/workbooks.identity_of`): date, colour and serial. It is what
    D-90-7 checks the walk order inside.
    """
    rows = conn.execute(
        text(
            """
            SELECT r.source_row,
                   coalesce(r.raw -> 'values' ->> 'checkzone', '')  AS raw_zone_text,
                   coalesce(r.raw -> 'values' ->> 'model', '')      AS raw_model,
                   coalesce(r.raw -> 'values' ->> 'date', '')       AS raw_date,
                   coalesce(r.raw -> 'values' ->> 'color', '')      AS raw_color,
                   coalesce(r.raw -> 'values' ->> 'serial_no', '')  AS raw_serial,
                   coalesce(r.canonical ->> 'car_key', '')          AS car_key
              FROM stg_review_row r
             WHERE r.load_id = :load_id
             ORDER BY r.source_row
            """
        ),
        {"load_id": load_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def file_panel_spellings(conn: Connection, load_id: int) -> set[str]:
    """Every panel name this file writes, held or loaded.

    **T89 (D-89-4).** Retirement is refused when it would stop a name this
    very file depends on from resolving, and that question is about the
    **file**, not about what has loaded yet: on a PENDING_REVIEW batch
    nothing has loaded at all, and the good rows are exactly the ones whose
    names resolve through the panels somebody is about to retire.

    Read from the persisted projection, so no workbook is opened. Not
    filtered by model on purpose: a retirement is per plant x model, but
    offering to retire a panel whose name another model's rows on the same
    tab also write is the same trap, and the conservative answer -- say so
    and let the owner add the pair -- is the cheap one.
    """
    return {
        row[0]
        for row in conn.execute(
            text(
                """
                SELECT DISTINCT btrim(coalesce(
                           r.canonical ->> 'offending_value',
                           r.raw -> 'values' ->> 'checkzone', ''))
                  FROM stg_review_row r
                 WHERE r.load_id = :load_id
                """
            ),
            {"load_id": load_id},
        ).all()
        if row[0]
    }


def held_checkzone_model_counts(
    conn: Connection, load_id: int, reasons: Sequence[str] | None = None
) -> dict[tuple[str, str], int]:
    """How many held rows carry each `(panel spelling, raw model text)` pair.

    **T88 (D-88-1).** A spelling written on two models is two questions, not
    an ambiguity, and each question needs its own row count: `61551` holds
    34 rows of ``07LFFENDER``, and showing "34" against both P703 DBL and
    P703 RAPTOR would overstate each by the other's share. The caller
    resolves the raw model texts and sums the counts per resolved model.

    Read from the persisted projection, like every other held-label read.
    """
    out: dict[tuple[str, str], int] = {}
    for raw_zone, raw_model, n in conn.execute(
        text(
            """
            SELECT coalesce(r.canonical ->> 'offending_value', ''),
                   coalesce(r.raw -> 'values' ->> 'model', ''),
                   count(*)::int
              FROM stg_review_row r
             WHERE r.load_id = :load_id
               AND r.disposition IN ('REJECT', 'QUARANTINE')
               AND r.reason = ANY(:reasons)
               -- T39: a row a later insert pass loaded is no longer held.
               AND NOT EXISTS (
                   SELECT 1 FROM wavescan w
                    WHERE w.load_id = r.load_id
                      AND w.source_row = r.source_row
                      AND w.corrects_measurement_id IS NULL)
             GROUP BY 1, 2
            """
        ),
        {
            "load_id": load_id,
            "reasons": list(reasons or ("UNKNOWN_CHECKZONE",)),
        },
    ).all():
        out[(raw_zone, raw_model)] = int(n)
    return out


def held_checkzone_orientations(
    conn: Connection, load_id: int, reasons: Sequence[str] | None = None
) -> dict[tuple[str, str], set[str]]:
    """The Tolerance Group cells each `(spelling, raw model)` was written with.

    **T88 (D-88-2 / G-88-5).** The file carries `Horizontal` / `Vertical` on
    every row and nothing read it. It is a hard constraint on which panel a
    spelling can be -- but only when the file is consistent about it, so the
    set is returned rather than a single value: more than one orientation
    for one spelling is a file problem the screen must flag, not a filter it
    may apply.
    """
    out: dict[tuple[str, str], set[str]] = {}
    for raw_zone, raw_model, orientation in conn.execute(
        text(
            """
            SELECT coalesce(r.canonical ->> 'offending_value', ''),
                   coalesce(r.raw -> 'values' ->> 'model', ''),
                   btrim(coalesce(r.raw -> 'values' ->> 'tolerance_group', ''))
              FROM stg_review_row r
             WHERE r.load_id = :load_id
               AND r.disposition IN ('REJECT', 'QUARANTINE')
               AND r.reason = ANY(:reasons)
               AND NOT EXISTS (
                   SELECT 1 FROM wavescan w
                    WHERE w.load_id = r.load_id
                      AND w.source_row = r.source_row
                      AND w.corrects_measurement_id IS NULL)
             GROUP BY 1, 2, 3
            """
        ),
        {
            "load_id": load_id,
            "reasons": list(reasons or ("UNKNOWN_CHECKZONE",)),
        },
    ).all():
        if orientation:
            out.setdefault((raw_zone, raw_model), set()).add(orientation)
    return out


def held_checkzone_models(
    conn: Connection, load_id: int, reasons: Sequence[str] | None = None
) -> dict[str, set[str]]:
    """Raw Model texts of the panel-held rows, per panel spelling (T41).

    `reasons` defaults to ``UNKNOWN_CHECKZONE`` alone, which is what T41
    asks for. T86 passes both panel holds.

    Read from the persisted projection's raw cells -- no workbook is opened.
    The caller resolves them through the same alias maps the cleaner uses.
    """
    out: dict[str, set[str]] = {}
    for raw_zone, raw_model in conn.execute(
        text(
            """
            SELECT coalesce(r.canonical ->> 'offending_value', ''),
                   coalesce(r.raw -> 'values' ->> 'model', '')
              FROM stg_review_row r
             WHERE r.load_id = :load_id
               AND r.disposition IN ('REJECT', 'QUARANTINE')
               AND r.reason = ANY(:reasons)
            """
        ),
        {
            "load_id": load_id,
            "reasons": list(reasons or ("UNKNOWN_CHECKZONE",)),
        },
    ).all():
        out.setdefault(raw_zone, set()).add(raw_model)
    return out


def held_panel_spellings(conn: Connection, load_id: int) -> list[dict]:
    """T86: every held **panel** spelling on this batch, with its models.

    Both panel holds, not one: ``UNKNOWN_CHECKZONE`` (the name is on no
    list here) and ``ZONE_NOT_VALID_FOR_MODEL`` (the name is a real panel
    another model owns). The match screen asks the same question of both,
    and a reviewer looking at two identical-looking rows must not be given
    two different answers (T86 section 1).

    Read from the persisted projection (T18), so no workbook is opened.
    Rows a later insert pass loaded are no longer held, exactly as
    :func:`held_label_groups` has it.
    """
    out: dict[str, dict] = {}
    for reason, raw_zone, raw_model, n in conn.execute(
        text(
            """
            SELECT r.reason,
                   coalesce(r.canonical ->> 'offending_value', ''),
                   coalesce(r.raw -> 'values' ->> 'model', ''),
                   count(*)::int
              FROM stg_review_row r
             WHERE r.load_id = :load_id
               AND r.disposition IN ('REJECT', 'QUARANTINE')
               AND r.reason IN ('UNKNOWN_CHECKZONE', 'ZONE_NOT_VALID_FOR_MODEL')
               AND NOT EXISTS (
                   SELECT 1 FROM wavescan w
                    WHERE w.load_id = r.load_id
                      AND w.source_row = r.source_row
                      AND w.corrects_measurement_id IS NULL)
             GROUP BY 1, 2, 3
            """
        ),
        {"load_id": load_id},
    ).all():
        if not raw_zone:
            continue
        item = out.setdefault(
            raw_zone,
            {"raw_zone_text": raw_zone, "count": 0, "reasons": set(), "raw_models": set()},
        )
        item["count"] += int(n)
        item["reasons"].add(reason)
        if raw_model:
            item["raw_models"].add(raw_model)
    return sorted(
        out.values(), key=lambda item: (-item["count"], item["raw_zone_text"])
    )


def insert_rejects(
    conn: Connection,
    load_id: int,
    rejects: Sequence[Reject],
    duplicates: Sequence[DuplicateInfo],
) -> int:
    """Nothing is dropped silently: every non-loaded row is written down."""
    sql = text(
        """
        INSERT INTO reject_log
            (load_id, source_file, source_sheet, source_row,
             reject_reason, reject_detail, offending_column, offending_value,
             raw_row)
        VALUES (:load_id, :source_file, :source_sheet, :source_row,
                :reason, :detail, :column, :value, CAST(:raw AS jsonb))
        """
    )
    payload = [
        {
            "load_id": load_id,
            "source_file": r.source_file,
            "source_sheet": r.source_sheet,
            "source_row": r.source_row,
            "reason": r.reason,
            "detail": r.detail,
            "column": r.column,
            "value": r.value,
            "raw": json.dumps(r.raw, default=str),
        }
        for r in rejects
    ]
    for d in duplicates:
        row = d.dropped
        payload.append({
            "load_id": load_id,
            "source_file": row.source_file,
            "source_sheet": row.source_sheet,
            "source_row": row.source_row,
            "reason": "DUPLICATE_ROW",
            "detail": f"{d.similarity:.0f}% match - kept {d.kept_description}",
            "column": None,
            "value": row.serial_no,
            "raw": json.dumps(
                {
                    "plant": row.plant,
                    "serial_no": row.serial_no,
                    "checkzone": row.checkzone,
                    "measured_date": row.measured_date.isoformat(),
                    **{k: str(v) if v is not None else None
                       for k, v in row.measures.items()},
                },
                default=str,
            ),
        })
    if payload:
        conn.execute(sql, payload)
    return len(payload)


def insert_unidentified(
    conn: Connection,
    load_id: int,
    rows: Sequence[Unidentified],
    zone_counts: dict[str, int],
    expected_zones: dict[str, int],
) -> int:
    """A vehicle whose model is not named is quarantined, never guessed.

    ``suggested_model`` is advisory and stored as such: a 31-zone fingerprint
    hints at U704 and 32 at P703, but a human still decides
    (`AGENTS.md` rule 6).
    """
    suggestion = {count: model for model, count in expected_zones.items()}
    sql = text(
        """
        INSERT INTO unidentified_model
            (load_id, source_file, source_sheet, source_row,
             raw_model, plant, serial_no, measured_date,
             zone_count, suggested_model, raw_row)
        VALUES (:load_id, :source_file, :source_sheet, :source_row,
                :raw_model, :plant, :serial_no, :measured_date,
                :zone_count, :suggested_model, CAST(:raw AS jsonb))
        """
    )
    payload = []
    for u in rows:
        n = zone_counts.get(u.serial_no or "", 0)
        payload.append({
            "load_id": load_id,
            "source_file": u.source_file,
            "source_sheet": u.source_sheet,
            "source_row": u.source_row,
            "raw_model": u.raw_model,
            "plant": u.plant,
            "serial_no": u.serial_no,
            "measured_date": u.measured_date,
            "zone_count": n or None,
            "suggested_model": suggestion.get(n) if n else None,
            "raw": json.dumps(u.raw, default=str),
        })
    if payload:
        conn.execute(sql, payload)
    return len(payload)


#: `source_file` is deliberately absent: T02 removed it from `wavescan`, and
#: `is_superseded` is deliberately absent because a T02 BEFORE INSERT trigger
#: refuses a row that arrives already retired.
INSERT_MEASUREMENT = text(
    """
    INSERT INTO wavescan
        (measured_date, plant, model, checkzone, color, tolerance_group,
         paintline, serial_no,
         lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
         load_id, source_sheet, source_row, src_zone_text, src_zone_no, car_key,
         date_is_month_only)
    VALUES
        (:measured_date, :plant, :model, :checkzone, :color, :tolerance_group,
         :paintline, :serial_no,
         :lw, :sw, :cf, :doi, :du, :wa, :wb, :wc, :wd, :we, :b,
         :load_id, :source_sheet, :source_row, :src_zone_text, :src_zone_no,
         :car_key, :date_is_month_only)
    """
)


def insert_measurements(conn: Connection, load_id: int, rows: Sequence[CleanRow]) -> int:
    payload = [
        {
            "measured_date": r.measured_date,
            "plant": r.plant,
            "model": r.model,
            "checkzone": r.checkzone,
            "color": r.color,
            "tolerance_group": r.tolerance_group,
            "paintline": r.paintline,
            "serial_no": r.serial_no,
            **{m: r.measures.get(m) for m in MEASURE_ALL},
            "load_id": load_id,
            "source_sheet": r.source_sheet,
            "source_row": r.source_row,
            "src_zone_text": r.src_zone_text,
            "src_zone_no": r.src_zone_no,
            # RO16 (D-RO16-2): which car of a many-car blank-serial sheet.
            "car_key": r.car_key,
            # RO18 (B4): the 1st of a named month, day not recorded.
            "date_is_month_only": r.date_is_month_only,
        }
        for r in rows
    ]
    if payload:
        conn.execute(INSERT_MEASUREMENT, payload)
    return len(payload)


def propose_column_mapping(
    conn: Connection,
    load_id: int,
    payload: dict,
    proposed_by: str | None,
) -> str:
    """A COLUMN proposal for an Admin to decide (`02-PIPELINE.md` §4).

    Written when a sheet's template is unknown. It is never applied by
    anything in T04: approving a mapping is an Admin route that stays
    reserved in this slice.
    """
    return str(
        conn.execute(
            text(
                """
                INSERT INTO proposed_mapping
                    (kind, payload, load_id, status, proposed_by)
                VALUES ('COLUMN', CAST(:payload AS jsonb), :load_id,
                        'PROPOSED', :proposed_by)
                RETURNING id
                """
            ),
            {
                "payload": json.dumps(payload, default=str),
                "load_id": load_id,
                "proposed_by": proposed_by,
            },
        ).scalar_one()
    )


# =====================================================================
# replay (T08)
# =====================================================================
#: The only two states a batch may be replayed from (`02-PIPELINE.md` §8).
#: `COMMITTED` and `SUPERSEDED` have produced facts; `RUNNING` is mid-parse;
#: `FAILED` needs a person to read `notes` before anything re-runs.
REPLAYABLE_STATUSES = (STATUS_REJECTED_TEMPLATE, STATUS_PENDING_REVIEW)


def count_facts(conn: Connection, load_id: int) -> int:
    """How many measurements this batch has produced.

    Zero is the precondition for replay, checked here for a readable refusal
    and again inside `reset_batch_staging` for the guarantee. The second
    check is the one that counts: it runs as the function's owner, which is
    the only identity that could delete anything, so it is the identity that
    has to be stopped.
    """
    # T46: a FilmThickness batch's facts live in `filmthickness`; either kind
    # makes the batch unreplayable. `reset_batch_staging` counts both too.
    return int(
        conn.execute(
            text(
                "SELECT (SELECT count(*) FROM wavescan WHERE load_id = :load_id) "
                "     + (SELECT count(*) FROM filmthickness WHERE load_id = :load_id)"
            ),
            {"load_id": load_id},
        ).scalar_one()
    )


def reset_batch_staging(conn: Connection, load_id: int) -> dict[str, int]:
    """Clear this batch's staging so it can be re-derived from stored bytes.

    Calls the `SECURITY DEFINER` function revision 0004 creates. `app_rw`
    holds no DELETE on `stg_raw`, `reject_log` or `unidentified_model` and
    T08 is forbidden from granting one, so the deletion happens inside a
    function that refuses unless the batch has **zero** `wavescan` rows and a
    replayable status. Read revision 0004's docstring before changing this.

    Returns rows cleared per table. `{}` is a normal answer: a
    `REJECTED_TEMPLATE` batch never staged anything in the first place.
    """
    cleared = conn.execute(
        text("SELECT reset_batch_staging(:load_id)"), {"load_id": load_id}
    ).scalar_one()
    return {k: int(v) for k, v in (cleared or {}).items()}


def reopen_for_replay(conn: Connection, load_id: int, *, notes: str) -> None:
    """Put a batch back to RUNNING with its counts zeroed.

    Separate from `set_batch_outcome` because it is the one transition that
    moves *backwards*, and it has to clear `finished_at` rather than set it.
    Leaving the old counts in place would mean a RUNNING batch advertising
    the previous parse's numbers to a reviewer refreshing the page.

    Column-scoped, like every other write to this table.
    """
    conn.execute(
        text(
            """
            UPDATE load_batch
               SET status = :status,
                   rows_in_file = 0, rows_loaded = 0, rows_duplicate = 0,
                   rows_rejected = 0, rows_quarantine = 0,
                   finished_at = NULL,
                   notes = :notes
             WHERE load_id = :load_id
            """
        ),
        {"status": STATUS_RUNNING, "notes": notes[:2000], "load_id": load_id},
    )
