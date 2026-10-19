"""Template profiles: which plant layouts this platform knows how to read.

`ref_template_profile` (revision 0006, amended by 0009) answers one question
-- *is this `(domain, plant, semantic contract)` a layout we have agreed to
parse, and has a fixture proved it commits correctly?* It answers nothing
about what a value means: that stays in the alias tables the cleaner is
handed (`00-ARCHITECTURE.md` section 5 rule 1, design section 5.1).

**T26 moves the selection key.** T18 selected on `(plant_code,
template_fingerprint)`, where the fingerprint is order-sensitive. Real
previous-month workbooks reorder the same twenty-one logical fields -- FTM
August and SAP July both do -- and were refused for it. Selection is now
`(domain, plant_code, semantic_signature)`: the sorted set of recognised
logical fields, which a reorder cannot change. The ordered fingerprint is
still stored on the profile and on the batch as **exact-layout provenance**,
so "the columns moved" stays visible; it is simply not what picks the
profile (spec S7, M5 as amended).

**Reads only, still, with one named exception.** `app_rw` holds no INSERT or
UPDATE on this table, which is what makes M6 true by construction: an Admin
approving a header alias cannot promote a layout to commit-capable, however
the approve route is later edited. The one way the application can append a
verified version is `publish_template_profile`, a `SECURITY DEFINER` function
that requires a named owner, a proving stored-workbook hash and notes, and
writes its own `audit_event` in the same transaction (spec S20). Calling it
is the Admin publish route and nothing else.
"""

from __future__ import annotations

import json

from sqlalchemy import Connection, text

from app.domain.reader import DOMAIN_WAVESCAN

PROFILE_COLUMNS = """
    profile_id, plant_code, domain, semantic_signature, template_fingerprint,
    version, is_active, fixture_verified, fixture_file_hash,
    fill_missing_plant, verified_by, verified_at, notes
"""

#: Column policy verbs (revision 0009, design section 5.3).
POLICY_MAPPED = "MAPPED"
POLICY_IGNORED = "IGNORED"


def active_profile(
    conn: Connection,
    plant_code: str | None,
    semantic_signature: str | None,
    domain: str = DOMAIN_WAVESCAN,
) -> dict | None:
    """The one active profile for this contract, or None.

    Selection is `(domain, expected_plant, semantic_signature)` and nothing
    else (spec S7 / M5 amended). The filename is never a key -- a file
    renamed on the way out of SharePoint is the same evidence -- and neither
    is a similarity score, and neither, since T26, is column order.

    "The one" is a database guarantee, not an `ORDER BY`:
    `uq_profile_active_semantic` is a unique partial index over `(domain,
    plant_code, semantic_signature) WHERE is_active`, so two active versions
    of one contract cannot exist to be chosen between.
    """
    if not plant_code or not semantic_signature:
        return None
    row = conn.execute(
        text(
            f"SELECT {PROFILE_COLUMNS} FROM ref_template_profile "
            f"WHERE domain = :domain AND plant_code = :plant "
            f"AND semantic_signature = :sig AND is_active"
        ),
        {"domain": domain, "plant": plant_code, "sig": semantic_signature},
    ).mappings().first()
    return dict(row) if row else None


def get_profile(conn: Connection, profile_id: int | None) -> dict | None:
    """One profile by id, active or not.

    A batch keeps the `profile_id` that parsed it even if that version is
    later retired, so a reviewer can be told *which* layout produced what they
    are looking at rather than which layout is current.
    """
    if profile_id is None:
        return None
    row = conn.execute(
        text(f"SELECT {PROFILE_COLUMNS} FROM ref_template_profile WHERE profile_id = :id"),
        {"id": profile_id},
    ).mappings().first()
    return dict(row) if row else None


def column_policy(conn: Connection, profile_id: int | None) -> dict[str, dict]:
    """Normalised raw header -> the decision a named person made about it.

    `ref_template_column_policy` is how a column that is not a WaveScan field
    stops being an `UNREVIEWED_HEADER` without becoming a silent drop: FVL's
    `Panel2` is the case it exists for (design section 5.3). A row is either
    `MAPPED` to a logical field or `IGNORED` with an approver and a reason,
    and there is no column here that holds SQL or Python.
    """
    if profile_id is None:
        return {}
    rows = conn.execute(
        text(
            "SELECT raw_header, policy, logical_field, approved_by, reason "
            "FROM ref_template_column_policy WHERE profile_id = :id"
        ),
        {"id": profile_id},
    ).mappings().all()
    return {r["raw_header"]: dict(r) for r in rows}


def ignored_headers(conn: Connection, profile_id: int | None) -> tuple[str, ...]:
    """Just the headers a named owner approved ignoring, for the reader."""
    return tuple(
        sorted(
            header
            for header, row in column_policy(conn, profile_id).items()
            if row["policy"] == POLICY_IGNORED
        )
    )


def publish(
    conn: Connection,
    *,
    plant_code: str,
    domain: str,
    semantic_signature: str,
    template_fingerprint: str,
    fixture_file_hash: str,
    named_owner: str,
    notes: str,
    fill_missing_plant: bool,
    ignored: list[dict],
    actor_user_id: str | None,
    correlation_id: str | None,
) -> dict:
    """Append an owner-verified profile version (spec S20).

    Every word of the guarantee is in the database function, not here: this
    is one `SELECT`, because the application role has no grant that could
    write this table directly. `publish_template_profile` deactivates the
    previous active version for the same contract, inserts the next version
    with `fixture_verified` true, writes the column policy, and writes the
    `audit_event` -- all in the caller's transaction, so a failed publish
    leaves neither a profile nor an audit row claiming one.

    Refusals come back as PostgreSQL exceptions and are translated by the
    service, so a route never re-derives an outcome from a message string.
    """
    row = conn.execute(
        text(
            """
            SELECT publish_template_profile(
                :plant, :domain, :sig, :fingerprint, :fixture_hash,
                :named_owner, :notes, :fill_missing_plant,
                CAST(:ignored AS jsonb), CAST(:actor AS uuid), :correlation
            ) AS result
            """
        ),
        {
            "plant": plant_code,
            "domain": domain,
            "sig": semantic_signature,
            "fingerprint": template_fingerprint,
            "fixture_hash": fixture_file_hash,
            "named_owner": named_owner,
            "notes": notes,
            "fill_missing_plant": fill_missing_plant,
            "ignored": json.dumps(ignored),
            "actor": actor_user_id or None,
            "correlation": correlation_id,
        },
    ).scalar_one()
    return dict(row) if isinstance(row, dict) else json.loads(row)


__all__ = [
    "active_profile",
    "get_profile",
    "column_policy",
    "ignored_headers",
    "publish",
    "POLICY_MAPPED",
    "POLICY_IGNORED",
]
