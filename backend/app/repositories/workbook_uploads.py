"""RO19 append-only workbook upload evidence; skipped tabs are not batches."""
from __future__ import annotations

import json
from sqlalchemy import Connection, text


def create(conn: Connection, *, plant_code: str, file_hash: str, source_file: str,
           raw_store_key: str, loaded_by: str | None, skipped_sheets: list[dict]) -> None:
    # A purge cannot remove this row (`app_rw` holds INSERT and SELECT only),
    # so re-uploading purged bytes meets the row it left behind.
    conn.execute(text("""
        INSERT INTO workbook_upload
            (plant_code,file_hash,source_file,raw_store_key,loaded_by,skipped_sheets)
        VALUES (:plant,:hash,:file,:key,CAST(:actor AS uuid),CAST(:skips AS jsonb))
        ON CONFLICT (plant_code,file_hash) DO NOTHING
    """), {"plant": plant_code, "hash": file_hash, "file": source_file,
           "key": raw_store_key, "actor": loaded_by,
           "skips": json.dumps(skipped_sheets, default=str)})


def unpurged(conn: Connection, file_hash: str) -> list[dict]:
    """Workbook evidence for these bytes that is still standing.

    A purge (ADR 0011) and a plant answer that frees the hash both delete the
    batches and write `workbook.purge` for `plant:hash`, but neither can remove
    this table's row. Reading that audit trace is what keeps a purged workbook
    uploadable again; audit is never deleted, so the trace does not expire.
    """
    return [dict(r) for r in conn.execute(text("""
        SELECT w.* FROM workbook_upload w
        WHERE w.file_hash=:hash
          AND NOT EXISTS (SELECT 1 FROM audit_event a
                          WHERE a.action='workbook.purge'
                            AND a.entity_id = w.plant_code || ':' || w.file_hash)
        ORDER BY w.plant_code
    """), {"hash": file_hash}).mappings()]


def for_hashes(conn: Connection, plant_code: str, hashes: list[str]) -> dict[str, dict]:
    if not hashes:
        return {}
    return {str(r["file_hash"]).strip(): dict(r) for r in conn.execute(text(
        "SELECT * FROM workbook_upload WHERE plant_code=:plant AND file_hash=ANY(:hashes)"
    ), {"plant": plant_code, "hashes": hashes}).mappings()}


def legacy_for_hashes(conn: Connection, plant_code: str, hashes: list[str]) -> list[dict]:
    if not hashes:
        return []
    return [dict(r) for r in conn.execute(text("""
        SELECT load_id, file_hash, source_file, source_sheet, started_at, loaded_by, notes
          FROM load_batch WHERE plant_code=:plant AND file_hash=ANY(:hashes)
           AND sheet_class='OUT_OF_SCOPE_SHEET' ORDER BY load_id
    """), {"plant": plant_code, "hashes": hashes}).mappings()]
