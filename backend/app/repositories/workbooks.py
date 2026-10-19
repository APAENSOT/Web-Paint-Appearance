"""Plant-scoped workbook reads: the SQL half of the Data Manager.

**No workbook is ever opened here.** Every read in this module comes from
`load_batch`, `stg_review_row`, `wavescan`, `audit_event`,
`ref_template_profile` and `review_acknowledgement` (T19 locked decision 1).
Re-parsing Excel on a GET is listed as a defect in the task's weak points,
and for a good reason: a read that re-derives can disagree with the review a
person acted on, and it turns a page refresh into a parse of a 600-row
workbook.

**One workbook is one `file_hash` at one plant.** Sheets are `load_batch`
children of it (`02-PIPELINE.md` section 1: a batch is one sheet of one
file). The filename is a label -- a file renamed on the way out of SharePoint
is the same evidence -- so nothing here keys on `source_file`. Every query
takes the resolved `plant_code` as well as the hash, so the same bytes filed
under FTM cannot be read through an AAT URL.

**Dates are measured dates, never upload dates.** The range of a workbook is
the union of the measured dates its review projection proposes and the
measured dates its committed facts hold (T19 locked decision 3). A workbook
still being parsed has no dates, and that is reported as null rather than
filled in from `started_at` -- inventing a week from upload time is a defect,
because a June file uploaded in September belongs in June.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.domain.reader import MEASURE_ALL
from app.repositories.batches import BATCH_SELECT

#: Dispositions `stg_review_row` may carry, echoed here so a route can offer
#: the filter without importing the migration.
DISPOSITIONS: tuple[str, ...] = ("LOAD", "DUPLICATE", "REJECT", "QUARANTINE")

#: Every measured date this platform knows about for a set of batches: what
#: the parse proposed, and what the commit wrote. Unioned rather than chosen
#: between, because a workbook with one committed sheet and one still in
#: review has both kinds and its range covers both.
#: `{scope}` is the name of a CTE holding the `load_id`s in question.
_MEASURED_DATES = """
    SELECT r.load_id, (r.canonical ->> 'measured_date')::date AS measured_date
      FROM stg_review_row r
     WHERE r.load_id IN (SELECT load_id FROM {scope})
       AND r.canonical ->> 'measured_date' IS NOT NULL
    UNION ALL
    SELECT w.load_id, w.measured_date
      FROM wavescan w
     WHERE w.load_id IN (SELECT load_id FROM {scope})
"""

#: A committed fact rendered in the shape `ingest._canonical_of` produces, so
#: a pre-T18 sheet (committed before there was a projection to keep) shows
#: the same fields in the same places as every other row. Measures are cast
#: to text: L12 holds them as NUMERIC and a JSON number would be a double.
_FACT_AS_CANONICAL = (
    "jsonb_build_object("
    "'measured_date', to_char(w.measured_date, 'YYYY-MM-DD'), "
    "'plant', w.plant, 'model', w.model, 'checkzone', w.checkzone, "
    "'color', COALESCE((SELECT rc.merged_into FROM ref_color rc "
    "WHERE rc.color_name = w.color), w.color), "
    "'tolerance_group', w.tolerance_group, "
    "'paintline', w.paintline, 'serial_no', w.serial_no, "
    "'src_zone_text', w.src_zone_text, 'src_zone_no', w.src_zone_no, "
    # RO16 / D-RO17-17: a facts-only sheet's cars stay apart, as `identity_rows`.
    "'car_key', w.car_key, "
    "'measures', jsonb_build_object("
    + ", ".join(f"'{m}', w.{m}::text" for m in MEASURE_ALL)
    + "))"
)


# =====================================================================
# plant scope
# =====================================================================
def resolve_plant(conn: Connection, raw: str) -> dict | None:
    """`/plants/ftm` and `/plants/FTM` are one plant; `/plants/nowhere` is none.

    Resolved through `ref_plant.plant_code` **and** `ref_plant_alias`, which
    is the same pair the ingest cleaner resolves a Plant cell through, so a
    plant is named the same way on a URL as it is in a workbook. Case and
    surrounding space are ignored here rather than in the route.

    Returns the plant row, including `is_active`: an inactive plant is a
    plant this platform knows and has not onboarded (FVL, D5). Its workbook
    list is an empty list, not a 404 and not the upload route's 422 -- the
    Data Manager shows the plant and the reason rather than hiding it
    (design section 5.4).
    """
    value = (raw or "").strip()
    if not value:
        return None
    row = conn.execute(
        text(
            """
            SELECT p.plant_code, p.is_active, p.requires_serial
              FROM ref_plant p
             WHERE upper(p.plant_code) = upper(:raw)
                OR p.plant_code = (
                       SELECT a.plant_code FROM ref_plant_alias a
                        WHERE upper(btrim(a.raw_value)) = upper(:raw)
                        LIMIT 1)
             LIMIT 1
            """
        ),
        {"raw": value},
    ).mappings().first()
    return dict(row) if row else None


# =====================================================================
# workbook list and detail
# =====================================================================
def count_workbooks(conn: Connection, plant_code: str) -> int:
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM (SELECT file_hash FROM load_batch WHERE plant_code=:plant "
                "UNION SELECT file_hash FROM workbook_upload WHERE plant_code=:plant) files"
            ),
            {"plant": plant_code},
        ).scalar_one()
    )


def list_workbook_hashes(
    conn: Connection, plant_code: str, *, limit: int, offset: int
) -> list[dict]:
    """One page of this plant's workbooks, newest measured data first.

    Ordering is the Files overview's, decided here because it depends on the
    dates: a workbook still being parsed has no measured date yet and sits at
    the top in a Processing group (design section 8.2), then the rest by
    their earliest measured date descending, with the hash breaking ties so
    two workbooks of the same day page stably.
    """
    rows = conn.execute(
        text(
            f"""
            WITH sheets AS (
                SELECT load_id, file_hash FROM load_batch
                 WHERE plant_code = :plant
            ),
            dated AS (
                SELECT s.file_hash,
                       min(d.measured_date) AS measured_date_min,
                       max(d.measured_date) AS measured_date_max
                  FROM sheets s
                  JOIN ({_MEASURED_DATES.format(scope='sheets')}
                       ) d ON d.load_id = s.load_id
                 GROUP BY s.file_hash
            )
            SELECT h.file_hash,
                   dated.measured_date_min,
                   dated.measured_date_max
              FROM (SELECT DISTINCT file_hash FROM sheets
                    UNION SELECT file_hash FROM workbook_upload WHERE plant_code=:plant) h
              LEFT JOIN dated ON dated.file_hash = h.file_hash
             ORDER BY (dated.measured_date_min IS NULL) DESC,
                      dated.measured_date_min DESC,
                      h.file_hash
             LIMIT :limit OFFSET :offset
            """
        ),
        {"plant": plant_code, "limit": limit, "offset": offset},
    ).mappings().all()
    return [dict(r) for r in rows]


def dates_for_hash(conn: Connection, plant_code: str, file_hash: str) -> dict:
    """The measured-date range of one workbook, by the same rule as the list."""
    row = conn.execute(
        text(
            f"""
            WITH sheets AS (
                SELECT load_id FROM load_batch
                 WHERE plant_code = :plant AND file_hash = :hash
            )
            SELECT min(d.measured_date) AS measured_date_min,
                   max(d.measured_date) AS measured_date_max
              FROM ({_MEASURED_DATES.format(scope='sheets')}
                   ) d
             WHERE d.load_id IN (SELECT load_id FROM sheets)
            """
        ),
        {"plant": plant_code, "hash": file_hash},
    ).mappings().one()
    return dict(row)


def sheets_for_hashes(
    conn: Connection, plant_code: str, file_hashes: list[str]
) -> list[dict]:
    """Every `load_batch` of these workbooks, with its profile joined.

    `BATCH_SELECT` is reused rather than re-spelled so a sheet on the Files
    page and the same sheet on `GET /batches/{id}` carry the same columns --
    including `profile_fixture_verified`, which `commit_blockers` reads.
    """
    if not file_hashes:
        return []
    rows = conn.execute(
        text(
            f"{BATCH_SELECT} WHERE b.plant_code = :plant "
            f"AND b.file_hash = ANY(:hashes) "
            f"AND b.sheet_class IS DISTINCT FROM 'OUT_OF_SCOPE_SHEET' "
            f"ORDER BY b.file_hash, b.load_id"
        ),
        {"plant": plant_code, "hashes": list(file_hashes)},
    ).mappings().all()
    return [dict(r) for r in rows]


def replacement_candidates(
    conn: Connection, plant_code: str, file_hash: str
) -> list[dict]:
    """Other workbooks of this plant that have live committed facts.

    The possible-replacement hint compares date ranges against these. It is
    a **hint**: design M14 keeps supersede an explicit Admin action with a
    reason, so nothing here retires anything, and the caller must not treat
    an overlap as a decision.

    "Live" means at least one sheet whose status is `COMMITTED` -- a workbook
    that has already been superseded is not a candidate to be replaced again.
    """
    rows = conn.execute(
        text(
            f"""
            WITH sheets AS (
                SELECT load_id, file_hash, source_file, status
                  FROM load_batch
                 WHERE plant_code = :plant AND file_hash <> :hash
            ),
            live AS (
                SELECT file_hash, min(source_file) AS source_file
                  FROM sheets
                 WHERE status = 'COMMITTED'
                 GROUP BY file_hash
            )
            SELECT live.file_hash,
                   live.source_file,
                   min(d.measured_date) AS measured_date_min,
                   max(d.measured_date) AS measured_date_max
              FROM live
              JOIN sheets s ON s.file_hash = live.file_hash
              JOIN ({_MEASURED_DATES.format(scope='sheets')}
                   ) d ON d.load_id = s.load_id
             GROUP BY live.file_hash, live.source_file
            """
        ),
        {"plant": plant_code, "hash": file_hash},
    ).mappings().all()
    return [dict(r) for r in rows]


# =====================================================================
# rows
# =====================================================================
def _rows_union(where_disposition: bool) -> str:
    """The row source: the projection, plus facts no projection describes.

    Two arms, because there are two kinds of sheet:

    * **Projection rows** -- every parsed sheet, whatever its status. A
      committed sheet's rows are joined to `wavescan` to pick up the
      `measurement_id` they produced. That join is deliberately **not**
      through `v_wavescan_active`: a superseded batch's facts are still this
      file's rows and the Files drill-down shows them (T19 locked decision
      8). `corrects_measurement_id IS NULL` keeps it one row per source row
      -- a correction is a second `wavescan` row with the same coordinates,
      and the row this source cell produced is the original.
    * **Facts with no projection** -- a sheet committed before T18 existed.
      T18's honest note: those have nothing in `stg_review_row`, and the
      answer is to show the facts with `raw` null and say so, never to
      re-open the workbook.
    """
    clause = "WHERE u.disposition = :disposition" if where_disposition else ""
    return f"""
        WITH scope AS (
            SELECT load_id, source_sheet, source_file, status
              FROM load_batch
             WHERE plant_code = :plant AND file_hash = :hash
               AND (CAST(:load_id AS bigint) IS NULL
                    OR load_id = CAST(:load_id AS bigint))
        ),
        projected AS (
            SELECT r.load_id, s.source_sheet, s.source_file, r.source_row,
                   r.disposition, r.reason, r.detail,
                   -- T64 (ADR 0014): a staged merged colour reads folded.
                   CASE WHEN rc.merged_into IS NULL THEN r.canonical
                        ELSE jsonb_set(r.canonical, ARRAY['color'], to_jsonb(rc.merged_into))
                   END AS canonical,
                   r.raw, r.normalized_fields,
                   r.profile_id, r.template_fingerprint, r.review_revision,
                   w.measurement_id,
                   false AS projection_missing
              FROM stg_review_row r
              JOIN scope s ON s.load_id = r.load_id
              LEFT JOIN ref_color rc ON rc.color_name = r.canonical ->> 'color'
              LEFT JOIN wavescan w
                     ON w.load_id = r.load_id
                    AND w.source_row = r.source_row
                    AND w.corrects_measurement_id IS NULL
        ),
        orphan_facts AS (
            SELECT w.load_id, s.source_sheet, s.source_file, w.source_row,
                   'LOAD' AS disposition, NULL::text AS reason,
                   NULL::text AS detail,
                   {_FACT_AS_CANONICAL} AS canonical,
                   NULL::jsonb AS raw,
                   '[]'::jsonb AS normalized_fields,
                   NULL::bigint AS profile_id,
                   NULL::text AS template_fingerprint,
                   NULL::char(64) AS review_revision,
                   w.measurement_id,
                   true AS projection_missing
              FROM wavescan w
              JOIN scope s ON s.load_id = w.load_id
             WHERE NOT EXISTS (
                       SELECT 1 FROM stg_review_row r WHERE r.load_id = w.load_id)
        ),
        u AS (
            SELECT * FROM projected
            UNION ALL
            SELECT * FROM orphan_facts
        )
        SELECT {{columns}} FROM u {clause}
    """


def count_workbook_rows(
    conn: Connection,
    plant_code: str,
    file_hash: str,
    *,
    load_id: int | None = None,
    disposition: str | None = None,
) -> int:
    sql = _rows_union(disposition is not None).format(columns="count(*)")
    return int(
        conn.execute(
            text(sql),
            {
                "plant": plant_code, "hash": file_hash,
                "load_id": load_id, "disposition": disposition,
            },
        ).scalar_one()
    )


def list_workbook_rows(
    conn: Connection,
    plant_code: str,
    file_hash: str,
    *,
    load_id: int | None = None,
    disposition: str | None = None,
    limit: int,
    offset: int,
) -> list[dict]:
    """One page of this workbook's rows, in source order.

    `(load_id, source_row)` is the stable order the task asks for;
    `measurement_id` breaks the one tie that is possible, a pre-T18 sheet
    whose source row produced a fact and later a correction.
    """
    sql = _rows_union(disposition is not None).format(columns="*")
    rows = conn.execute(
        text(
            f"{sql} ORDER BY u.load_id, u.source_row, "
            f"u.measurement_id NULLS FIRST LIMIT :limit OFFSET :offset"
        ),
        {
            "plant": plant_code, "hash": file_hash,
            "load_id": load_id, "disposition": disposition,
            "limit": limit, "offset": offset,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


def sample_rows(
    conn: Connection, load_ids: list[int], disposition: str, limit: int
) -> list[dict]:
    """A few example rows of one disposition, for the issues view.

    Deliberately capped by the caller: the issues page points at rows, and
    the full list is what `/rows` is for.
    """
    if not load_ids:
        return []
    rows = conn.execute(
        text(
            """
            SELECT r.load_id, b.source_sheet, r.source_row, r.reason, r.detail
              FROM stg_review_row r
              JOIN load_batch b ON b.load_id = r.load_id
             WHERE r.load_id = ANY(:ids) AND r.disposition = :disposition
             ORDER BY r.load_id, r.source_row
             LIMIT :limit
            """
        ),
        {"ids": list(load_ids), "disposition": disposition, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def projection_fingerprints(conn: Connection, load_ids: list[int]) -> dict[int, str]:
    """The layout that actually parsed each sheet.

    Read from `stg_review_row`, not from `load_batch.template_fingerprint`.
    That column is provenance: it is written when the batch is opened and
    never updated, so after a replay through an approved alias -- which can
    change which headers are recognised, and therefore the fingerprint -- it
    names a layout that parsed nothing. T18 recorded the difference as an
    honest note and T19 is where it starts mattering, because the workbook
    detail tells a reviewer which translation ran.

    One fingerprint per sheet: every row of one parse carries the same one.
    """
    if not load_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (load_id) load_id, template_fingerprint "
            "  FROM stg_review_row WHERE load_id = ANY(:ids) "
            " ORDER BY load_id, source_row"
        ),
        {"ids": list(load_ids)},
    ).all()
    return {int(load_id): fingerprint for load_id, fingerprint in rows}


def normalized_field_counts(conn: Connection, load_ids: list[int]) -> dict[int, int]:
    """How many rows of each sheet had a field filled for them.

    Today that is only a plant filled from `expected_plant` (T17/T18), and it
    is `INFORMATION`, not a warning: the fill was disclosed at upload and
    agreed by the profile. Counted from the projection rather than from the
    audit event so it survives a replay.
    """
    if not load_ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT load_id, count(*) AS n FROM stg_review_row
             WHERE load_id = ANY(:ids)
               AND jsonb_array_length(normalized_fields) > 0
             GROUP BY load_id
            """
        ),
        {"ids": list(load_ids)},
    ).all()
    return {int(load_id): int(n) for load_id, n in rows}


# =====================================================================
# history
# =====================================================================
def history(conn: Connection, load_ids: list[int], *, workbook_key: str | None = None) -> list[dict]:
    """Every audited event that touched this workbook, oldest first.

    Three entity types, because the platform audits the thing that changed
    rather than the file it came from: the batch itself (`batch.upload`,
    `batch.replay`, `batch.commit`, `batch.supersede`, `review.acknowledge`),
    the mapping proposals raised for it, and the measurements it produced
    (`measurement.correct`). Joining them here is what makes one timeline out
    of three tables.

    This is **not** a global audit read: it is scoped to the `load_id`s of
    one workbook of one plant, and there is no route that lists
    `audit_event` without a workbook.

    Nothing updates or deletes an audit row -- no role holds either grant --
    so "append-only" is a property of the database, not of this query.
    """
    if not load_ids and not workbook_key:
        return []
    rows = conn.execute(
        text(
            """
            SELECT e.id, e.occurred_at, e.actor_user_id, e.actor_type,
                   e.action, e.entity_type, e.entity_id, e.after,
                   e.correlation_id
              FROM audit_event e
             WHERE (e.entity_type = 'load_batch'
                    AND e.entity_id = ANY(:ids_text))
                OR (e.entity_type = 'wavescan'
                    AND e.entity_id IN (
                        SELECT measurement_id::text FROM wavescan
                         WHERE load_id = ANY(:ids)))
                OR (e.entity_type = 'workbook_upload' AND e.entity_id=:workbook_key)
                OR (e.entity_type = 'proposed_mapping'
                    AND e.entity_id IN (
                        SELECT id::text FROM proposed_mapping
                         WHERE load_id = ANY(:ids)))
             ORDER BY e.id
            """
        ),
        {"ids": list(load_ids), "ids_text": [str(i) for i in load_ids], "workbook_key": workbook_key},
    ).mappings().all()
    return [dict(r) for r in rows]


# =====================================================================
# T21: inbox index, vehicle sets
# =====================================================================
def workbook_index(conn: Connection, plant_code: str) -> list[dict]:
    """Every workbook of this plant, one small row each, for an inbox filter.

    `uploaded_at` is the earliest `started_at` (the same value the card
    shows), `statuses` feeds `domain.workbooks.operational_summary`, and the
    measured-date range is the T19 rule. No ordering and no paging here: the
    inbox rules decide both over the whole plant, so a client never has to
    page through the plant to find last month's unfinished file.
    """
    rows = conn.execute(
        text(
            f"""
            WITH sheets AS (
                SELECT load_id, file_hash, status, started_at, sheet_class FROM load_batch
                 WHERE plant_code = :plant
            ),
            dated AS (
                SELECT s.file_hash,
                       min(d.measured_date) AS measured_date_min,
                       max(d.measured_date) AS measured_date_max
                  FROM sheets s
                  JOIN ({_MEASURED_DATES.format(scope='sheets')}
                       ) d ON d.load_id = s.load_id
                 GROUP BY s.file_hash
            )
            , files AS (
                SELECT file_hash, min(started_at) AS uploaded_at FROM sheets GROUP BY file_hash
                UNION ALL SELECT file_hash, uploaded_at FROM workbook_upload WHERE plant_code=:plant
            )
            SELECT files.file_hash,
                   min(files.uploaded_at) AS uploaded_at,
                   array_agg(DISTINCT s.status) FILTER
                     (WHERE s.sheet_class IS DISTINCT FROM 'OUT_OF_SCOPE_SHEET' AND s.load_id IS NOT NULL) AS statuses,
                   dated.measured_date_min,
                   dated.measured_date_max
              FROM files
              LEFT JOIN sheets s ON s.file_hash=files.file_hash
              LEFT JOIN dated ON dated.file_hash = files.file_hash
             GROUP BY files.file_hash, dated.measured_date_min, dated.measured_date_max
            """
        ),
        {"plant": plant_code},
    ).mappings().all()
    out = []
    for r in rows:
        item = dict(r)
        item["file_hash"] = str(item["file_hash"]).strip()
        item["statuses"] = list(item["statuses"] or [])
        out.append(item)
    return out


def identity_rows(conn: Connection, load_ids: list[int]) -> list[dict]:
    """The distinct vehicle identity cells of some sheets, as stored.

    Same two arms as the rows read -- the projection, and facts no
    projection describes -- reduced to the four identity fields so a page of
    workbook cards can count vehicle sets without shipping every row. The
    grouping rule itself (blank equals missing, which parts make a key) is
    `domain.workbooks`, applied by the caller.
    """
    if not load_ids:
        return []
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT r.load_id,
                   -- RO11: `domain.workbooks.set_key` reads these two.
                   r.disposition,
                   r.canonical ->> 'logical_vehicle_id' AS logical_vehicle_id,
                   -- RO16: `set_key` reads a Wave Scan car's walk too.
                   r.canonical ->> 'car_key'       AS car_key,
                   r.canonical ->> 'measured_date' AS measured_date,
                   r.canonical ->> 'model'         AS model,
                   COALESCE((SELECT rc.merged_into FROM ref_color rc
                              WHERE rc.color_name = r.canonical ->> 'color'),
                            r.canonical ->> 'color') AS color,
                   r.canonical ->> 'serial_no'     AS serial_no
              FROM stg_review_row r
             WHERE r.load_id = ANY(:ids)
            UNION
            SELECT DISTINCT w.load_id,
                   'LOAD',
                   NULL,
                   w.car_key,
                   to_char(w.measured_date, 'YYYY-MM-DD'),
                   w.model,
                   -- T64 (ADR 0014): the fact's colour folded, as every read.
                   COALESCE((SELECT rc.merged_into FROM ref_color rc
                              WHERE rc.color_name = w.color), w.color),
                   w.serial_no
              FROM wavescan w
             WHERE w.load_id = ANY(:ids)
               AND NOT EXISTS (
                       SELECT 1 FROM stg_review_row r WHERE r.load_id = w.load_id)
            """
        ),
        {"ids": list(load_ids)},
    ).mappings().all()
    return [dict(r) for r in rows]


def sheet_rows(
    conn: Connection, plant_code: str, file_hash: str, load_id: int
) -> list[dict]:
    """Every row of one sheet, by the same join rule as `/rows`.

    Unpaged: a vehicle set is a grouping over the whole sheet, and a sheet is
    hundreds of rows, not millions. Not through `v_wavescan_active`, for the
    reason `_rows_union` gives.
    """
    sql = _rows_union(False).format(columns="*")
    rows = conn.execute(
        text(f"{sql} ORDER BY u.source_row, u.measurement_id NULLS FIRST"),
        {"plant": plant_code, "hash": file_hash, "load_id": load_id, "disposition": None},
    ).mappings().all()
    return [dict(r) for r in rows]



def purge_workbook(
    conn: Connection,
    *,
    plant_code: str,
    file_hash: str,
    actor_user_id: str,
    reason: str,
    correlation_id: str | None,
) -> dict:
    """ADR 0011. One plant + hash, every sheet, through `purge_workbook`.

    `app_rw` holds no DELETE on `wavescan` or `load_batch`; the function is
    SECURITY DEFINER and writes `workbook.purge` to `audit_event` before any
    fact goes, in this connection's transaction.
    """
    return dict(
        conn.execute(
            text(
                "SELECT purge_workbook(:plant, :hash, CAST(:actor AS uuid), "
                ":reason, :correlation)"
            ),
            {
                "plant": plant_code,
                "hash": file_hash,
                "actor": actor_user_id,
                "reason": reason,
                "correlation": correlation_id,
            },
        ).scalar_one()
    )

__all__ = [
    "DISPOSITIONS",
    "identity_rows",
    "sheet_rows",
    "workbook_index",
    "resolve_plant",
    "count_workbooks",
    "list_workbook_hashes",
    "dates_for_hash",
    "sheets_for_hashes",
    "replacement_candidates",
    "count_workbook_rows",
    "list_workbook_rows",
    "sample_rows",
    "normalized_field_counts",
    "projection_fingerprints",
    "history",
    "purge_workbook",
]
