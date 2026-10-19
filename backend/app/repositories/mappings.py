"""`proposed_mapping`, and the two alias tables an approval writes into.

Every statement here is either a read, an INSERT, or the one column-scoped
UPDATE the grant allows (`status`, `decided_by`, `decided_at`). There is no
DELETE in this module and no role that could execute one if there were.

The split that matters: **proposing writes only to `proposed_mapping`**, and
**approving is the only thing that writes an alias**. Those are two functions
with no shared path, so "never auto-apply" (`02-PIPELINE.md` §4) is a
property of the code's shape rather than of a flag somebody remembered to
check. A test greps for it.
"""

from __future__ import annotations

import json

from sqlalchemy import Connection, text

from app.domain.reader import DOMAIN_WAVESCAN

PROPOSED = "PROPOSED"
APPROVED = "APPROVED"
REJECTED = "REJECTED"

#: The tables an approval may write, by proposal kind. Anything not in here
#: has no write path at all, which is how the unimplemented kinds stay
#: unimplemented rather than relying on a route check alone.
ALIAS_TABLE_BY_KIND = {
    "COLUMN": "ref_column_alias",
    "ALIAS_MODEL": "ref_model_alias",
    "ALIAS_COLOR": "ref_color_alias",
    # T29: one atomic, owner-proved 32-row set per (plant, P703 model).
    "ZONE": "ref_plant_zone_map",
    # T41: one Engineer-confirmed panel spelling onto an existing zone.
    "ALIAS_CHECKZONE": "ref_plant_zone_map",
    # T61 / T78: one Film sheet's model choice. The alias table is where an
    # approved choice *with* a teachable token lands; an ambiguous choice
    # resolves the sheet only and writes no row (D-78-30).
    "FILM_MODEL": "ref_film_model_alias",
}

#: `ref_plant_zone_map.proposal_method` of a T41 one-row Engineer map. The
#: reference loader honours these rows without an owner proof (D-31); an
#: Admin row with no proof still stays out of the cleaner (T29 S15).
ENGINEER_ZONE_METHOD = "ENGINEER_ALIAS"

_COLUMNS = (
    "id, kind, payload, load_id, status, similarity, "
    "proposed_by, decided_by, created_at, decided_at"
)


def _row(mapping) -> dict:
    row = dict(mapping)
    row["id"] = str(row["id"])
    for key in ("proposed_by", "decided_by"):
        row[key] = str(row[key]) if row[key] else None
    return row


# =====================================================================
# reads
# =====================================================================
def list_proposals(
    conn: Connection, *, load_id: int | None, limit: int, offset: int
) -> list[dict]:
    """Newest first. `created_at` alone is not a total order under a clock
    that can tie, so `id` breaks it and paging stays stable."""
    rows = conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM proposed_mapping "
            "WHERE (CAST(:load_id AS bigint) IS NULL "
            "       OR load_id = CAST(:load_id AS bigint)) "
            "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        {"load_id": load_id, "limit": limit, "offset": offset},
    ).mappings().all()
    return [_row(r) for r in rows]


def count_proposals(conn: Connection, *, load_id: int | None) -> int:
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM proposed_mapping "
                "WHERE (CAST(:load_id AS bigint) IS NULL "
                "       OR load_id = CAST(:load_id AS bigint))"
            ),
            {"load_id": load_id},
        ).scalar_one()
    )


def get_proposal(conn: Connection, proposal_id: str) -> dict | None:
    row = conn.execute(
        text(f"SELECT {_COLUMNS} FROM proposed_mapping WHERE id = CAST(:id AS uuid)"),
        {"id": proposal_id},
    ).mappings().first()
    return _row(row) if row else None


def get_proposal_for_update(conn: Connection, proposal_id: str) -> dict | None:
    """Lock the row for the duration of an approval.

    Two Admins approving the same proposal at the same moment would otherwise
    both see `PROPOSED`, both write the alias, and the second would fail on
    the unique key *after* having written an audit row. The lock makes the
    second one wait and then see `APPROVED`, which is the 409 it deserves.
    """
    row = conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM proposed_mapping "
            "WHERE id = CAST(:id AS uuid) FOR UPDATE"
        ),
        {"id": proposal_id},
    ).mappings().first()
    return _row(row) if row else None


def model_wavescan_ok(conn: Connection, model_code: str) -> bool | None:
    """T46: ``ref_model.wavescan_ok``, or None for an unknown model."""
    value = conn.execute(
        text("SELECT wavescan_ok FROM ref_model WHERE model_code = :code"),
        {"code": model_code},
    ).scalar()
    return None if value is None else bool(value)


def model_exists(conn: Connection, model_code: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT 1 FROM ref_model WHERE model_code = :code"),
            {"code": model_code},
        ).first()
    )


def known_models(conn: Connection) -> list[str]:
    """For the error message when a proposed `model_code` is not one."""
    return [
        r[0] for r in conn.execute(
            text("SELECT model_code FROM ref_model ORDER BY model_code")
        ).all()
    ]


def color_exists(conn: Connection, color_name: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT 1 FROM ref_color WHERE color_name = :name"),
            {"name": color_name},
        ).first()
    )


def known_colors(conn: Connection) -> list[str]:
    """For the held-label catalogue and for the error when a name is not one.

    T64: a merged name (ADR 0014) is not offered as a choice; its canonical
    name is.
    """
    return [
        r[0] for r in conn.execute(
            text(
                "SELECT color_name FROM ref_color WHERE merged_into IS NULL "
                "ORDER BY color_name"
            )
        ).all()
    ]


def color_merged_into(conn: Connection, color_name: str) -> str | None:
    """T64 (ADR 0014): the canonical name a merged colour folds to, else None."""
    return conn.execute(
        text("SELECT merged_into FROM ref_color WHERE color_name = :name"),
        {"name": color_name},
    ).scalar()


# =====================================================================
# writes -- proposing
# =====================================================================
def insert_proposal(
    conn: Connection,
    *,
    kind: str,
    payload: dict,
    load_id: int | None,
    similarity: object | None,
    proposed_by: str | None,
) -> dict:
    """Record a proposal. Writes `proposed_mapping` and nothing else.

    `status` is hardcoded to PROPOSED rather than taken from the caller: a
    route that could post an already-approved proposal would be a way around
    the Admin, which is the one thing this table exists to prevent.
    """
    row = conn.execute(
        text(
            f"""
            INSERT INTO proposed_mapping
                (kind, payload, load_id, status, similarity, proposed_by)
            VALUES (:kind, CAST(:payload AS jsonb), :load_id, '{PROPOSED}',
                    :similarity, :proposed_by)
            RETURNING {_COLUMNS}
            """
        ),
        {
            "kind": kind,
            "payload": json.dumps(payload, default=str),
            "load_id": load_id,
            "similarity": similarity,
            "proposed_by": proposed_by,
        },
    ).mappings().one()
    return _row(row)


# =====================================================================
# writes -- deciding
# =====================================================================
def decide(conn: Connection, proposal_id: str, *, status: str, decided_by: str) -> dict:
    """Record the human decision. The three columns the grant allows, exactly."""
    row = conn.execute(
        text(
            f"""
            UPDATE proposed_mapping
               SET status = :status, decided_by = :decided_by, decided_at = now()
             WHERE id = CAST(:id AS uuid)
            RETURNING {_COLUMNS}
            """
        ),
        {"status": status, "decided_by": decided_by, "id": proposal_id},
    ).mappings().one()
    return _row(row)


def insert_column_alias(
    conn: Connection,
    *,
    raw_header: str,
    logical_field: str,
    proposed_by: str | None,
    approved_by: str,
    domain: str = DOMAIN_WAVESCAN,
) -> None:
    """`ref_column_alias`, approved on the way in.

    `is_approved` is true because only this function writes here and only an
    Admin reaches it. `reference.load_reference_data` reads approved rows
    only, so an unapproved row would be written and then ignored -- a state
    worth not having.

    No `ON CONFLICT`: a duplicate `(domain, raw_header)` raises, the
    transaction rolls back, and the route answers 409 with nothing
    half-applied. Quietly updating the existing row would repoint an approved
    alias at a different column, which is a decision somebody else already
    made.

    T26 names the domain explicitly rather than leaning on the column
    default: an alias means something *within a vocabulary*, and a route that
    has to remember to say so is a route that will one day forget (spec S6).
    """
    conn.execute(
        text(
            """
            INSERT INTO ref_column_alias
                (raw_header, logical_field, is_approved, proposed_by,
                 approved_by, domain)
            VALUES (:raw_header, :logical_field, true, :proposed_by,
                    :approved_by, :domain)
            """
        ),
        {
            "raw_header": raw_header,
            "logical_field": logical_field,
            "proposed_by": proposed_by,
            "approved_by": approved_by,
            "domain": domain,
        },
    )


def insert_model_alias(
    conn: Connection,
    *,
    raw_value: str,
    model_code: str,
    note: str,
    plant_code: str | None = None,
) -> None:
    """`ref_model_alias`. The table `domain/cleaner.py` already reads.

    Same reasoning on conflicts as above. The foreign key on `model_code` is
    the backstop for the existence check the service does first: the check
    produces a readable message, the constraint produces the guarantee.

    T26 adds `plant_code` (spec S11). When the proposal came from a batch,
    the batch's plant is passed and the alias is **plant-scoped**, so one
    plant's local spelling can never relabel another plant's vehicle -- the
    defect the global bare-`P703` rows were. A proposal with no batch still
    writes a global row, because a spelling nobody can attribute to a plant
    is a spelling about the whole catalogue.
    """
    conn.execute(
        text(
            "INSERT INTO ref_model_alias (raw_value, model_code, note, plant_code) "
            "VALUES (:raw_value, :model_code, :note, :plant_code)"
        ),
        {
            "raw_value": raw_value,
            "model_code": model_code,
            "note": note[:2000],
            "plant_code": plant_code,
        },
    )


def insert_color_alias(
    conn: Connection,
    *,
    raw_value: str,
    color_name: str,
    note: str,
    plant_code: str,
) -> None:
    """`ref_color_alias`, plant-scoped. Identity only (S12).

    Same conflict reasoning as `insert_model_alias`: a duplicate
    `(plant_code, raw_value)` raises, the transaction rolls back, and the
    route answers 409. The foreign key on `color_name` is the backstop for
    the existence check the service does first.

    `plant_code` is required. A colour spelling is what *this plant* wrote;
    a global row would let one plant's wording relabel another plant's
    vehicles -- the defect S12 exists to prevent.
    """
    conn.execute(
        text(
            "INSERT INTO ref_color_alias "
            "(raw_value, color_name, note, plant_code) "
            "VALUES (:raw_value, :color_name, :note, :plant_code)"
        ),
        {
            "raw_value": raw_value,
            "color_name": color_name,
            "note": note[:2000],
            "plant_code": plant_code,
        },
    )


def column_alias(conn: Connection, domain: str, raw_header: str) -> str | None:
    """RO18: the logical field this header already means in this domain, if any."""
    return conn.execute(
        text(
            "SELECT logical_field FROM ref_column_alias "
            "WHERE domain = :d AND raw_header = :h"
        ),
        {"d": domain, "h": raw_header},
    ).scalar()


def plant_color_alias(conn: Connection, plant_code: str, raw_value: str) -> str | None:
    """The colour this plant's exact spelling already maps to, if any (T39)."""
    return conn.execute(
        text(
            "SELECT color_name FROM ref_color_alias "
            "WHERE plant_code = :p AND raw_value = :r"
        ),
        {"p": plant_code, "r": raw_value},
    ).scalar()


def plant_offers_color(conn: Connection, plant_code: str, color_name: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT is_offered FROM ref_plant_color "
                "WHERE plant_code = :p AND color_name = :c"
            ),
            {"p": plant_code, "c": color_name},
        ).scalar()
    )


def offer_color_at_plant(conn: Connection, plant_code: str, color_name: str) -> dict | None:
    """Put an **existing** catalogue colour on one plant's list (T39, D-32).

    Returns the previous row (or None). The family is left as it was -- NULL
    for a new row -- because a colour family is a standards decision (D2),
    not something an Engineer confirming a spelling can set.
    """
    before = conn.execute(
        text(
            "SELECT is_offered, family_name FROM ref_plant_color "
            "WHERE plant_code = :p AND color_name = :c"
        ),
        {"p": plant_code, "c": color_name},
    ).mappings().first()
    conn.execute(
        text(
            "INSERT INTO ref_plant_color (plant_code, color_name, is_offered) "
            "VALUES (:p, :c, true) "
            "ON CONFLICT (plant_code, color_name) DO UPDATE "
            "SET is_offered = true, updated_at = now()"
        ),
        {"p": plant_code, "c": color_name},
    )
    return dict(before) if before else None


# =====================================================================
# T29 -- ZONE sets
# =====================================================================
def model_family(conn: Connection, model_code: str) -> tuple[str, int] | None:
    """`(model_family, expected_zone_count)` for a model, or None."""
    row = conn.execute(
        text(
            "SELECT model_family, expected_zone_count FROM ref_model "
            "WHERE model_code = :m"
        ),
        {"m": model_code},
    ).first()
    return (row[0], int(row[1])) if row else None


def expected_zone_codes(conn: Connection, model_code: str) -> set[str]:
    """The model's complete catalogue: what a ZONE set must cover exactly."""
    return {
        r[0]
        for r in conn.execute(
            text("SELECT zone_code FROM ref_model_zone WHERE model_code = :m"),
            {"m": model_code},
        ).all()
    }


def plant_zone_codes(conn: Connection, plant_code: str, model_code: str) -> set[str]:
    """T58 (D-58-10): the zones a pick may name at this plant x model.

    The plant's **live** WaveScan gold when it has one; else the model's
    `ref_model_zone` catalogue (a pair not yet seeded).
    """
    gold = {
        r[0]
        for r in conn.execute(
            text(
                "SELECT zone_code FROM ref_plant_ws_point WHERE plant_code = :p "
                "AND model_code = :m AND retired_at IS NULL"
            ),
            {"p": plant_code, "m": model_code},
        ).all()
    }
    return gold or expected_zone_codes(conn, model_code)


def plant_exists(conn: Connection, plant_code: str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM ref_plant WHERE plant_code = :p"), {"p": plant_code}
        ).first()
        is not None
    )


def get_zone_map_row_for_update(
    conn: Connection, plant_code: str, model_code: str, raw_zone_text: str
) -> dict | None:
    """The existing row for one raw label, locked for the approving transaction.

    `raw_zone_text` arrives already normalised; the unique key
    `uq_plant_zone_map (plant_code, model_code, raw_zone_text)` is on the
    stored text, which T29 always writes normalised.
    """
    row = conn.execute(
        text(
            """
            SELECT map_id, zone_code, confidence, approved_by,
                   proof_hash, verified_by
              FROM ref_plant_zone_map
             WHERE plant_code = :p AND model_code = :m AND raw_zone_text = :r
               AND retired_at IS NULL  -- RO17: a retired row is a record only
             FOR UPDATE
            """
        ),
        {"p": plant_code, "m": model_code, "r": raw_zone_text},
    ).mappings().first()
    return dict(row) if row else None


def insert_zone_map_row(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    raw_zone_text: str,
    raw_position: int | None,
    zone_code: str,
    method: str,
    note: str,
    proof_hash: str,
    proof_document: str,
    named_owner: str,
    approved_by: str,
) -> None:
    """A new proved row: APPROVED, the Admin who recorded it, the owner who
    proved it. The two are different columns on purpose (S15)."""
    conn.execute(
        text(
            """
            INSERT INTO ref_plant_zone_map
                (plant_code, model_code, raw_zone_text, raw_position, zone_code,
                 confidence, proposal_method, approved_by, approved_at, note,
                 proof_hash, proof_document, verified_by)
            VALUES (:p, :m, :r, :pos, :z,
                    'APPROVED', :method, :admin, now(), :note,
                    :proof_hash, :proof_document, :owner)
            """
        ),
        {
            "p": plant_code, "m": model_code, "r": raw_zone_text,
            "pos": raw_position, "z": zone_code, "method": method,
            "admin": approved_by, "note": note, "proof_hash": proof_hash,
            "proof_document": proof_document, "owner": named_owner,
        },
    )


def insert_engineer_zone_alias(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    raw_zone_text: str,
    raw_position: int | None,
    zone_code: str,
    approved_by: str,
    note: str,
) -> None:
    """One T41 row: APPROVED by the Engineer who confirmed it, no owner
    proof, marked ``ENGINEER_ALIAS``. ``zone_code`` must be on the model's
    catalogue -- the ``fk_pzm_model_zone`` foreign key is the backstop."""
    conn.execute(
        text(
            """
            INSERT INTO ref_plant_zone_map
                (plant_code, model_code, raw_zone_text, raw_position, zone_code,
                 confidence, proposal_method, approved_by, approved_at, note)
            VALUES (:p, :m, :r, :pos, :z, 'APPROVED', :method, :by, now(), :note)
            """
        ),
        {
            "p": plant_code, "m": model_code, "r": raw_zone_text,
            "pos": raw_position, "z": zone_code, "method": ENGINEER_ZONE_METHOD,
            "by": approved_by, "note": note[:2000],
        },
    )


def model_offered_at(conn: Connection, plant_code: str, model_code: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT is_offered FROM ref_plant_model "
                "WHERE plant_code = :p AND model_code = :m"
            ),
            {"p": plant_code, "m": model_code},
        ).scalar()
    )


def certify_zone_map_row(
    conn: Connection,
    *,
    map_id: int,
    raw_position: int | None,
    method: str,
    note: str,
    proof_hash: str,
    proof_document: str,
    named_owner: str,
    approved_by: str,
) -> None:
    """Fill the proof on a row that already says the same thing.

    The caller has checked that the row's `zone_code` equals the set's and
    that any existing proof is identical. **`zone_code` is not in this
    statement and not in the grant**: a certify can never repoint a label.
    An earlier approval is kept; a row nobody ever approved gets this Admin.
    """
    conn.execute(
        text(
            """
            UPDATE ref_plant_zone_map
               SET proof_hash = :proof_hash,
                   proof_document = :proof_document,
                   verified_by = :owner,
                   proposal_method = :method,
                   note = :note,
                   raw_position = COALESCE(raw_position, :pos),
                   confidence = 'APPROVED',
                   approved_by = COALESCE(approved_by, :admin),
                   approved_at = COALESCE(approved_at, now())
             WHERE map_id = :id
            """
        ),
        {
            "id": map_id, "proof_hash": proof_hash,
            "proof_document": proof_document, "owner": named_owner,
            "method": method, "note": note, "pos": raw_position,
            "admin": approved_by,
        },
    )


def plant_film_model_alias(
    conn: Connection, plant_code: str, raw_token: str
) -> str | None:
    """The Film model this plant's token already means, if any (D-78-33)."""
    return conn.execute(
        text(
            "SELECT model_code FROM ref_film_model_alias "
            "WHERE plant_code = :p AND raw_token = :t"
        ),
        {"p": plant_code, "t": raw_token},
    ).scalar()


def insert_film_model_alias(
    conn: Connection,
    *,
    plant_code: str,
    raw_token: str,
    model_code: str,
    note: str,
) -> None:
    """`ref_film_model_alias`, plant-scoped (D-78-30).

    Never an UPDATE. A token that already means a *different* model at this
    plant is refused by the service before this runs, and by the primary key
    `(plant_code, raw_token)` if two approvals race -- either way the
    transaction rolls back and the route answers 409 (D-78-33). The existing
    row is never overwritten.

    `raw_token` is stored as the table's CHECK requires, `upper(btrim())`.
    """
    conn.execute(
        text(
            "INSERT INTO ref_film_model_alias "
            "(plant_code, raw_token, model_code, note) "
            "VALUES (:plant_code, :raw_token, :model_code, :note)"
        ),
        {
            "plant_code": plant_code,
            "raw_token": raw_token.strip().upper(),
            "model_code": model_code,
            "note": note,
        },
    )


def approved_film_model_choice(
    conn: Connection, load_id: int, source_sheet: str
) -> str | None:
    """The model an approved FILM_MODEL proposal chose for this sheet.

    D-78-31: the approved proposal **is** the record replay reads, so there
    is no extra table. The newest approved choice for this exact
    `(load_id, source_sheet)` wins.
    """
    return conn.execute(
        text(
            """
            SELECT payload ->> 'model_code'
              FROM proposed_mapping
             WHERE kind = 'FILM_MODEL'
               AND status = 'APPROVED'
               AND load_id = :load_id
               AND payload ->> 'source_sheet' = :sheet
             ORDER BY decided_at DESC NULLS LAST, created_at DESC
             LIMIT 1
            """
        ),
        {"load_id": load_id, "sheet": source_sheet},
    ).scalar()


def film_model_hold_rows(conn: Connection, load_id: int) -> int:
    """How many rows of this batch are held FILM_MODEL_UNRESOLVED.

    Read from the persisted review projection, the same place the held-label
    read uses, so "is this sheet actually asking the model question?" has one
    answer and not two.
    """
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM stg_review_row "
                " WHERE load_id = :load_id AND reason = 'FILM_MODEL_UNRESOLVED'"
            ),
            {"load_id": load_id},
        ).scalar_one()
    )


# ---------------------------------------------------------------------
# T86 -- guided panel match
# ---------------------------------------------------------------------
#: `ref_plant_zone_map.proposal_method` of a T86 confirmed panel-match pair.
#: It names the task on purpose: a row written this way was decided by a
#: person reading the match screen, not by an owner-proved pack (T29) and
#: not by a single T41 pick.
PANEL_MATCH_METHOD = "T86_PANEL_MATCH"

#: T88 (G-88-6). The same thing, with the signal that proposed the pair
#: appended: `T88_PANEL_MATCH_NAME`, `..._NUMBER`, `..._EXHAUSTION`,
#: `..._NONE`. Exhaustion is the signal that can be confidently wrong, and
#: a mapping nobody can find again is a mapping nobody can correct --
#: `scripts/audit_panel_identities.py` lists them by this prefix.
PANEL_MATCH_METHOD_T88 = "T88_PANEL_MATCH"


def panel_match_method(signal: str | None) -> str:
    """The `proposal_method` for a pair the match screen learned (G-88-6)."""
    known = {"name", "number", "exhaustion", "none"}
    chosen = (signal or "none").strip().lower()
    if chosen not in known:
        chosen = "none"
    return f"{PANEL_MATCH_METHOD_T88}_{chosen.upper()}"


def live_plant_panels(
    conn: Connection, plant_code: str, model_code: str
) -> list[dict]:
    """This plant x model's **live** WaveScan panels (`ref_plant_ws_point`).

    `retired_at IS NULL` only -- a retired panel is readable history, never
    a target a new upload may match onto. `note` comes back because it is
    the only provenance a person has for telling one block of panels from
    another on the screen; nothing in the code reads it.
    """
    return [
        dict(row)
        for row in conn.execute(
            text(
                """
                SELECT p.zone_code,p.point_no,p.tolerance_group,p.note,w.walk_rank
                  FROM ref_plant_ws_point p JOIN v_point_walk_order w
                    ON w.plant_code=p.plant_code AND w.model_code=p.model_code
                   AND w.point_code=p.zone_code AND w.domain='WAVESCAN'
                 WHERE p.plant_code = :p AND p.model_code = :m
                   AND p.retired_at IS NULL
                 ORDER BY w.walk_rank
                """
            ),
            {"p": plant_code, "m": model_code},
        )
        .mappings()
        .all()
    ]


def live_panel_codes(conn: Connection, plant_code: str, model_code: str) -> set[str]:
    """Just the live zone_codes, for validating a match target."""
    return {p["zone_code"] for p in live_plant_panels(conn, plant_code, model_code)}


def taught_panel_pairs(conn: Connection, plant_code: str) -> list[dict]:
    """Every panel pair this plant has been taught, approved or still pending.

    **T89 (D-89-9).** A spelling somebody has already decided must not come
    back as a blank question. Normally it does not come back at all -- the
    `ref_plant_zone_map` row makes it resolve -- but it does in three real
    cases: the pair is still `PROPOSED` and nobody has approved it yet; the
    same spelling turns up on a **different model**; the file writes a
    near-miss of the spelling that was taught. In all three the screen has
    to be able to say *"you mapped this to X on 2026-10-08, from batch
    66219"*, so the decision is read back here rather than guessed at.

    **D-89-10.** Scoped to one plant, because that is what the learning
    table is keyed by: a pair taught at FTM is not readable at AAT, and the
    global `ref_checkzone_alias` is not read here at all -- the application
    never writes it and T89 does not change that.

    Returns, newest decision first:
    `{raw_zone_text, zone_code, model_code, status, decided_at, load_id,
      method}`. `status` is `APPROVED` or `PROPOSED`; `load_id` is the batch
    the decision was made on and is null for an approved row (the table
    does not keep it).
    """
    out: list[dict] = []
    for row in conn.execute(
        text(
            """
            SELECT raw_zone_text, zone_code, model_code, confidence,
                   coalesce(approved_at, created_at) AS decided_at,
                   proposal_method
              FROM ref_plant_zone_map
             WHERE plant_code = :p AND confidence = 'APPROVED'
               AND retired_at IS NULL
             ORDER BY coalesce(approved_at, created_at) DESC
            """
        ),
        {"p": plant_code},
    ).mappings().all():
        out.append({
            "raw_zone_text": row["raw_zone_text"],
            "zone_code": row["zone_code"],
            "model_code": row["model_code"],
            "status": APPROVED,
            "decided_at": row["decided_at"],
            "load_id": None,
            "method": row["proposal_method"],
        })

    # Still PROPOSED: the pair exists as a decision and has not been
    # applied, so the question comes back until an Admin approves it. The
    # two payload shapes are T86's guided set (`matches`) and T41's one-row
    # pick (`raw_value`), read exactly as `services/mapping.py` writes them.
    for row in conn.execute(
        text(
            """
            SELECT id, kind, payload, load_id, created_at
              FROM proposed_mapping
             WHERE status = :proposed
               AND kind IN ('ZONE', 'ALIAS_CHECKZONE')
               AND payload ->> 'plant_code' = :p
             ORDER BY created_at DESC
            """
        ),
        {"proposed": PROPOSED, "p": plant_code},
    ).mappings().all():
        payload = row["payload"] or {}
        model = payload.get("model_code")
        if not model:
            continue
        pairs: list[tuple[str, str]] = []
        if row["kind"] == "ALIAS_CHECKZONE":
            if payload.get("raw_value") and payload.get("zone_code"):
                pairs.append((payload["raw_value"], payload["zone_code"]))
        else:
            for match in payload.get("matches") or []:
                if match.get("raw_zone_text") and match.get("zone_code"):
                    pairs.append((match["raw_zone_text"], match["zone_code"]))
        for raw_zone_text, zone_code in pairs:
            out.append({
                "raw_zone_text": raw_zone_text,
                "zone_code": zone_code,
                "model_code": model,
                "status": PROPOSED,
                "decided_at": row["created_at"],
                "load_id": int(row["load_id"]) if row["load_id"] else None,
                "method": row["kind"],
            })
    return out


def confirmed_walk_sets(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    fingerprint: str | None = None,
    exclude_load_id: int | None = None,
) -> list[dict]:
    """T90 (D-90-11): the confirmed walks of one `(plant, model, fingerprint)`.

    **This read is of batch data, and that is the point.** A confirmed
    *rough* mapping -- ``01HOOD`` is this month's ``RRHOOD`` -- is recorded
    against the upload that was reviewed, on the ``ZONE`` panel-match
    proposal's own ``load_id``, and never in a reference table. The reason
    is not tidiness: `domain/cleaner.py` resolves a panel name from
    `ReferenceData` and nothing else, `load_reference_data` builds that from
    ``ref_*`` tables and nothing else, and neither can reach a
    ``proposed_mapping`` row or a ``load_batch``. So a rough label
    **structurally cannot** leak into automatic resolution: the month the
    plant reshuffles its walk, ``01HOOD`` cannot silently file as last
    month's hood, because nothing on the resolution path can see last
    month's answer. That is the same choice T87 made with its column-scoped
    ``GRANT`` -- a guarantee rather than a promise -- and a test asserts it.

    What this *is* for is the pre-fill: a later upload of the same walk
    arrives with the most recent confirmed answers filled in and every row
    yellow (D-90-6), so the owner confirms a walk they have already proved
    in one click instead of answering 32 questions again.

    ``PROPOSED`` counts as confirmed here, because the confirmation is the
    person pressing Confirm on the match screen; the Admin approval that
    follows is about writing the *permanent* aliases, which rough labels
    never get. ``REJECTED`` does not count. Newest first.

    `fingerprint` of None asks for the most recent confirmed walk
    **whatever** its fingerprint, which is how "the walk has changed since
    the last confirmed set" is detected at all (D-90-6, D-90-12).
    `exclude_load_id` leaves this batch's own confirmations out, so a sheet
    does not pre-fill from itself.
    """
    out: list[dict] = []
    for row in conn.execute(
        text(
            """
            SELECT m.id, m.load_id, m.status, m.created_at, m.payload,
                   b.source_file, b.source_sheet
              FROM proposed_mapping m
              LEFT JOIN load_batch b ON b.load_id = m.load_id
             WHERE m.kind = 'ZONE'
               AND m.status <> :rejected
               AND m.payload ->> 'plant_code' = :p
               AND m.payload ->> 'model_code' = :m
               AND m.payload -> 'walk' ->> 'fingerprint' IS NOT NULL
               AND (CAST(:fp AS text) IS NULL
                    OR m.payload -> 'walk' ->> 'fingerprint' = CAST(:fp AS text))
               AND (CAST(:exclude AS bigint) IS NULL
                    OR m.load_id IS DISTINCT FROM CAST(:exclude AS bigint))
             ORDER BY m.created_at DESC
            """
        ),
        {
            "rejected": REJECTED,
            "p": plant_code,
            "m": model_code,
            "fp": fingerprint,
            "exclude": exclude_load_id,
        },
    ).mappings().all():
        walk = (row["payload"] or {}).get("walk") or {}
        pairs = {
            pair["raw_zone_text"]: pair["zone_code"]
            for pair in walk.get("pairs") or []
            if pair.get("raw_zone_text") and pair.get("zone_code")
        }
        if not pairs:
            continue
        out.append({
            "proposal_id": str(row["id"]),
            "load_id": int(row["load_id"]) if row["load_id"] else None,
            "source_file": row["source_file"],
            "source_sheet": row["source_sheet"],
            "status": row["status"],
            "confirmed_at": row["created_at"],
            "fingerprint": walk.get("fingerprint") or "",
            "pairs": pairs,
            "rough": sorted(
                pair["raw_zone_text"]
                for pair in walk.get("pairs") or []
                if pair.get("specificity") == "rough"
            ),
        })
    return out


def insert_panel_match_row(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    raw_zone_text: str,
    raw_position: int | None,
    zone_code: str,
    approved_by: str,
    note: str,
    signal: str | None = None,
) -> None:
    """One confirmed pair of a panel-match set: APPROVED, method by signal.

    No owner proof: a match set is an Admin approving an Engineer's reading
    of the match screen, which is a different thing from the named-owner
    32-row pack T29 writes, and the two must stay distinguishable in the
    table. `fk_pzm_model_zone` is the backstop on `zone_code`.

    **T88 (G-88-6):** `signal` names what proposed the pair, and it goes
    into `proposal_method` rather than only into the note, so the audit can
    find every exhaustion-derived pair with one predicate. A row written by
    a T86-era client carries no signal and keeps the old method value.
    """
    conn.execute(
        text(
            """
            INSERT INTO ref_plant_zone_map
                (plant_code, model_code, raw_zone_text, raw_position, zone_code,
                 confidence, proposal_method, approved_by, approved_at, note)
            VALUES (:p, :m, :r, :pos, :z, 'APPROVED', :method, :by, now(), :note)
            """
        ),
        {
            "p": plant_code, "m": model_code, "r": raw_zone_text,
            "pos": raw_position, "z": zone_code,
            "method": (
                panel_match_method(signal) if signal else PANEL_MATCH_METHOD
            ),
            "by": approved_by, "note": note[:2000],
        },
    )


def retire_plant_panels(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    zone_codes: list[str],
    reason: str,
) -> list[str]:
    """Mark the panels the owner named as superseded (D-86-2).

    `retired_at` + `retired_reason` together -- `ck_plant_ws_point_retired`
    refuses one without the other. The row is **not** deleted and its
    `wavescan` rows stay readable; it simply stops being a target for a new
    upload. A panel that is already retired is left exactly as it was, so
    the first retirement's reason and timestamp survive.

    Returns the zone_codes this call actually retired.
    """
    if not zone_codes:
        return []
    return [
        row[0]
        for row in conn.execute(
            text(
                """
                UPDATE ref_plant_ws_point
                   SET retired_at = now(), retired_reason = :reason
                 WHERE plant_code = :p AND model_code = :m
                   AND zone_code = ANY(:zones)
                   AND retired_at IS NULL
             RETURNING zone_code
                """
            ),
            {
                "p": plant_code, "m": model_code,
                "zones": list(zone_codes), "reason": reason[:2000],
            },
        ).all()
    ]
