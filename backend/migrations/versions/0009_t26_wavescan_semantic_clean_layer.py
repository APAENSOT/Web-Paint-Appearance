"""T26: the WaveScan semantic clean layer.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-21

T18 decided whether a layout was known by an **order-sensitive** hash of its
header row. Real previous-month CF workbooks, reviewed read-only under
`Internship/Data/{AAT,FTM,FVL,SAP}/CF`, show that gate refusing sheets whose
only sin is that somebody moved a column: FTM August and SAP July carry the
same twenty-one logical fields in a different order. This revision moves
selection onto an **order-independent semantic signature** and keeps the
ordered hash as provenance, then adds the schema the rest of the clean layer
needs (spec `2026-09-20-wavescan-semantic-clean-layer-design.md`, S6-S11,
S15, S16, S20, S21).

Nine changes:

1. **`ref_column_alias.domain`.** Unique key becomes `(domain, raw_header)`.
   Every existing row is WaveScan. A future FilmThickness package must not
   inherit this domain's meaning of `Panel`, `Date` or `Model` (S6). No
   FilmThickness aliases are added here; the column is the boundary, not the
   onboarding.

2. **`ref_template_profile`** gains `domain`, `semantic_signature`,
   `verified_by` and `verified_at`; selection and version uniqueness move to
   `(domain, plant_code, semantic_signature)`. `template_fingerprint` stays
   as the **exact ordered-layout hash** -- evidence that the columns moved,
   which a semantic key would otherwise lose.

3. **`ref_template_column_policy`.** Per `(profile, normalised header)`:
   `MAPPED` to a logical field, or `IGNORED` with a named approver and a
   reason. This is how FVL's `Panel2` can later become an approved auxiliary
   column instead of a permanent `UNREVIEWED_HEADER` (S9, design 5.3). No
   column here holds SQL or Python.

4. **Plant-scoped model aliases.** `ref_model_alias` gains a nullable
   `plant_code`; lookup is plant row first, then global. The global
   `ASSUMPTION` rows mapping bare `P703` and `P703 DBL` to Ranger are
   **relocated**, not kept: FVL by the owner's lock (S11), AAT/FTM only
   where their own staged rows prove they used the spelling. SAP is
   deliberately left without one -- SAP writes `P703 RAP`, which is not a
   Ranger, and mapping it is a later activation slice.

5. **Plant-scoped colour aliases.** Same shape. Identity only: nothing here
   writes `grading_family`, and `POST /standards` stays 501 (S12, D1/D2).

6. **`ref_plant_zone_map` proof columns.** `proof_hash`, `proof_document`,
   `verified_by` (S15). **No SAP or FVL row is seeded, approved or
   otherwise.** The mapping engine already got FVL verticals and SAP
   tailgate Top/Bottom wrong; a named plant/quality owner decides that in a
   later slice, not this migration.

7. **`stg_review_row.disposition` gains `AGGREGATE_ROW`** (S16). `[All]`
   roll-up rows -- 1064 of FTM May's 1320, 133 of FVL September's 165 -- are
   preserved and disclosed, and can never become facts.

8. **`load_batch`** gains `domain`, `semantic_signature`, `sheet_class` and
   `unreviewed_headers`, all written by the worker after a parse, all joined
   to the column-scoped UPDATE allow-list. Additive: nothing is dropped and
   `template_fingerprint` keeps its name and its meaning.

9. **`publish_template_profile`**, a `SECURITY DEFINER` function with a fixed
   `search_path` (S20). It is the only way the application can create a
   verified profile version: it requires a named owner, a proving stored
   workbook hash and notes, appends a new version, deactivates the previous
   one, writes the column policy, and writes `audit_event` **in the same
   transaction**. `app_rw` keeps no INSERT, UPDATE or DELETE on the profile
   table itself, so M6 stays true by construction -- an Admin approving a
   header alias still cannot promote a layout.

**Is this revision destructive?** `AGENTS.md` section 2 asks the question, so:
**no.** `upgrade()` deletes exactly two reference rows -- the two global
`P703` / `P703 DBL` ASSUMPTION aliases -- and re-inserts their meaning as
plant-scoped rows first, so no plant that used those spellings loses the
mapping; SAP is the one plant deliberately left without one, which is the
point of the change. Nothing else deletes a row. No measurement is touched,
`reset_batch_staging` is **not** rewritten, and no grant to UPDATE or DELETE
`wavescan` or `load_batch` is created (S21, ADR 0005). Three statements
rewrite constraints in place (the profile uniqueness keys and the review
disposition CHECK); those are DROP/ADD of constraints, not of data.

`downgrade()` restores the T18 keys and drops what T26 added. It cannot
restore the two deleted global alias rows' `note` text, so it re-inserts them
verbatim.
"""

from __future__ import annotations

import hashlib

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

#: The only domain this slice knows (S1, S6).
DOMAIN = "WAVESCAN"

#: T03/T04/T06's list, plus the four columns the worker now writes after a
#: parse. `01-DATA-MODEL.md` section 8: the grant is column-scoped, so a
#: column the worker writes has to be named here or the write is refused.
LOAD_BATCH_UPDATABLE_COLUMNS = (
    "status",
    "rows_in_file", "rows_loaded", "rows_duplicate",
    "rows_rejected", "rows_quarantine",
    "started_at", "finished_at",
    "notes",
    "superseded_by",
    "plant_code",
    "profile_id",
    "review_revision",
    "domain",
    "semantic_signature",
    "sheet_class",
    "unreviewed_headers",
)

#: T18's four, plus T26's `AGGREGATE_ROW`.
REVIEW_DISPOSITIONS = ("LOAD", "DUPLICATE", "REJECT", "QUARANTINE", "AGGREGATE_ROW")

# ---------------------------------------------------------------------
# The two header sets revision 0006 seeded, named rather than hashed.
#
# `01-DATA-MODEL.md` and the T18 report record these layouts as *header
# sets*; the fingerprints below are the ordered hashes 0006 stored for them.
# The signature is computed from the **field set**, which is why this file
# can backfill without reversing a hash: it never asks "what produced this
# fingerprint", only "what fields does this known layout carry".
# ---------------------------------------------------------------------
CANONICAL_FIELDS = (
    "date", "month", "year", "plant", "model", "checkzone", "color",
    "tolerance_group", "paintline", "serial_no",
    "lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b",
)
NO_PLANT_FIELDS = tuple(f for f in CANONICAL_FIELDS if f != "plant")

#: Revision 0006's ordered hashes for those two layouts.
CANONICAL_FINGERPRINT = (
    "5d0070137d0005adfd73f0f4ba2d7031c96e55c47fb7313f501a83811bf2e990"
)
NO_PLANT_FINGERPRINT = (
    "b5dcecdb85acf437c89e2e73f0e479e5ce1e08d0a627f6cb3b6e6595f39c946e"
)


def _signature(fields, domain: str = DOMAIN) -> str:
    """The same formula as `app.domain.reader.semantic_signature`.

    Written out here rather than imported, because a migration must keep
    working against the schema it was authored for even after the
    application module moves (the same reason 0002 carries its own copy of
    `HEADER_ALIASES`). `backend/tests/test_t26_semantic_clean_layer.py`
    asserts the two implementations agree, so the copy cannot drift in
    silence.
    """
    payload = domain + "||" + "|".join(sorted(set(fields)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


CANONICAL_SIGNATURE = _signature(CANONICAL_FIELDS)
NO_PLANT_SIGNATURE = _signature(NO_PLANT_FIELDS)

#: The global model-alias rows T26 relocates. `01-reference.sql` seeded them
#: with the note "ASSUMPTION: no variant named => RANGER", and that
#: assumption is now known to be plant-specific (S11).
ASSUMED_RANGER_SPELLINGS = ("P703", "P703 DBL")
RANGER = "P703 DBL RANGER"

#: Owner lock, 2026-09-20/21: at FVL a bare `P703` (and `P703 DBL`) is a
#: Ranger. This is the one plant the owner named, and it is named here rather
#: than derived, because no amount of staged evidence can *decide* it.
OWNER_LOCKED_RANGER_PLANTS = ("FVL",)

#: Plants whose historical AAT/FTM-family spellings may be relocated from the
#: global rows **if their own staged rows show they used them**. SAP is
#: absent on purpose: SAP writes `P703 RAP`, which is not a Ranger, and
#: leaving SAP on a global Ranger default is the defect this change removes.
EVIDENCE_RELOCATION_PLANTS = ("AAT", "FTM")


def _for_each_role(sql: str) -> None:
    """Apply `sql` per role, skipping a role this database does not have."""
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                {sql.format(role=role)}
            END $$;
            """
        )


def _quote(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


# =====================================================================
def upgrade() -> None:
    _column_alias_domain()
    _profile_columns()
    _profile_selection_key()
    _column_policy()
    _plant_scoped_model_alias()
    _plant_scoped_color_alias()
    _zone_map_proof_columns()
    _review_disposition()
    _load_batch_columns()
    _publish_function()


# ---------------------------------------------------------------------
# 1. ref_column_alias: domain
# ---------------------------------------------------------------------
def _column_alias_domain() -> None:
    op.execute(
        "ALTER TABLE ref_column_alias "
        f"ADD COLUMN IF NOT EXISTS domain text NOT NULL DEFAULT {_quote(DOMAIN)}"
    )
    op.execute(
        "COMMENT ON COLUMN ref_column_alias.domain IS "
        "'Which measurement vocabulary this header spelling belongs to "
        "(T26, spec S6). WAVESCAN for every row this platform has. A future "
        "FilmThickness domain gets its own rows rather than inheriting these "
        "meanings of Panel, Date or Model.'"
    )
    # The default stays: the Admin mapping-approve route inserts here, and a
    # route that has to remember to say WAVESCAN is a route that will one day
    # forget. The service names it explicitly as well -- belt and braces.
    op.execute(
        "ALTER TABLE ref_column_alias "
        "DROP CONSTRAINT IF EXISTS uq_column_alias_raw_header"
    )
    op.execute(
        "ALTER TABLE ref_column_alias "
        "ADD CONSTRAINT uq_column_alias_domain_header UNIQUE (domain, raw_header)"
    )


# ---------------------------------------------------------------------
# 2. ref_template_profile: domain + semantic signature + verifier
# ---------------------------------------------------------------------
def _profile_columns() -> None:
    op.execute(
        f"""
        ALTER TABLE ref_template_profile
            ADD COLUMN IF NOT EXISTS domain text NOT NULL DEFAULT {_quote(DOMAIN)},
            ADD COLUMN IF NOT EXISTS semantic_signature text,
            ADD COLUMN IF NOT EXISTS verified_by text,
            ADD COLUMN IF NOT EXISTS verified_at timestamptz
        """
    )
    # No default on the profile's domain once the existing rows carry it: a
    # profile is a decision about one vocabulary, and the publish function
    # says which. (ref_column_alias keeps its default for the reason above.)
    op.execute("ALTER TABLE ref_template_profile ALTER COLUMN domain DROP DEFAULT")

    # --- backfill, in three passes, then refuse to guess ---------------
    # Pass 1 and 2: the two layouts revision 0006 seeded by name. Their field
    # sets are recorded above; the signature is computed from the set, not
    # recovered from the ordered hash.
    for fingerprint, signature in (
        (CANONICAL_FINGERPRINT, CANONICAL_SIGNATURE),
        (NO_PLANT_FINGERPRINT, NO_PLANT_SIGNATURE),
    ):
        op.execute(
            f"UPDATE ref_template_profile SET semantic_signature = {_quote(signature)} "
            f"WHERE semantic_signature IS NULL "
            f"AND template_fingerprint = {_quote(fingerprint)}"
        )

    # Pass 3: revision 0006's optional backfill inserted a profile for any
    # layout already carried by a COMMITTED AAT/FTM batch. Those layouts have
    # no name here, but the batch that produced them stored how its headers
    # were understood -- `load_batch.raw_headers->'recognised'` is
    # `{column index -> logical field}`. Reading that is not reversing a
    # hash; it is reading the header interpretation the parse recorded.
    #
    # `ORDER BY ... COLLATE "C"` is codepoint order, matching Python's
    # `sorted()` in `reader.semantic_signature`. Without it a locale that
    # ignores `_` at the primary level would sort `serial_no` differently and
    # the database and the application would compute different signatures for
    # the same sheet.
    op.execute(
        f"""
        UPDATE ref_template_profile p
           SET semantic_signature = s.sig
          FROM (
            SELECT DISTINCT ON (b.plant_code, b.template_fingerprint)
                   b.plant_code,
                   b.template_fingerprint,
                   encode(
                     sha256(convert_to(
                       {_quote(DOMAIN + "||")} || coalesce((
                         SELECT string_agg(d.f, '|' ORDER BY d.f COLLATE "C")
                           FROM (SELECT DISTINCT value AS f
                                   FROM jsonb_each_text(b.raw_headers -> 'recognised')
                                ) d
                       ), ''),
                       'UTF8')),
                     'hex') AS sig
              FROM load_batch b
             WHERE b.raw_headers ? 'recognised'
               AND b.template_fingerprint IS NOT NULL
             ORDER BY b.plant_code, b.template_fingerprint, b.load_id
          ) s
         WHERE p.semantic_signature IS NULL
           AND p.plant_code = s.plant_code
           AND p.template_fingerprint = s.template_fingerprint
        """
    )

    # Anything left has no evidence of what it carries, and inventing one
    # would be exactly the guess `AGENTS.md` rule 6 forbids. Stop and say so.
    op.execute(
        """
        DO $$
        DECLARE v_rows text;
        BEGIN
            SELECT string_agg(
                       format('profile_id %s (%s / %s)',
                              profile_id, plant_code,
                              left(coalesce(template_fingerprint, '(null)'), 12)),
                       ', ' ORDER BY profile_id)
              INTO v_rows
              FROM ref_template_profile
             WHERE semantic_signature IS NULL;
            IF v_rows IS NOT NULL THEN
                RAISE EXCEPTION
                    'revision 0009 cannot derive a semantic signature for: %. '
                    'No batch in this database records how those layouts'' '
                    'headers were understood, and a signature is never '
                    'guessed from an ordered hash. Replay a batch of each '
                    'layout, or have the owner republish the profile, then '
                    'run this migration again. Nothing was changed.',
                    v_rows
                    USING ERRCODE = 'raise_exception';
            END IF;
        END $$;
        """
    )
    op.execute(
        "ALTER TABLE ref_template_profile ALTER COLUMN semantic_signature SET NOT NULL"
    )

    # A verified layout has to say **who** verified it, not only that
    # something did (S15/S20). The rows revision 0006 seeded were proved by
    # that migration and by the T04/T18 suites, and saying so is accurate;
    # naming a person who did not sign them would not be.
    op.execute(
        """
        UPDATE ref_template_profile
           SET verified_by = 'migration 0006 (seed; proof named in notes)',
               verified_at = created_at
         WHERE fixture_verified AND verified_by IS NULL
        """
    )
    op.execute(
        "ALTER TABLE ref_template_profile "
        "ADD CONSTRAINT ck_profile_verifier_named "
        "CHECK (fixture_verified = false "
        "       OR (verified_by IS NOT NULL AND verified_at IS NOT NULL))"
    )
    op.execute(
        "COMMENT ON COLUMN ref_template_profile.semantic_signature IS "
        "'Hash of the sorted set of recognised logical fields for this "
        "domain (T26, spec S7). The profile selection key, together with "
        "domain and plant_code. A reordered workbook signs the same and "
        "parses; template_fingerprint records that the order moved.'"
    )
    op.execute(
        "COMMENT ON COLUMN ref_template_profile.template_fingerprint IS "
        "'The EXACT ordered-layout hash (T18''s algorithm, unchanged): "
        "ordered recognised fields with gaps, plus sorted unrecognised "
        "extras. Provenance only since T26 -- it is not the selection key.'"
    )


def _profile_selection_key() -> None:
    """Move uniqueness from the ordered hash to the semantic contract."""
    op.execute(
        "ALTER TABLE ref_template_profile DROP CONSTRAINT IF EXISTS uq_profile_version"
    )
    op.execute("DROP INDEX IF EXISTS uq_profile_active")

    # Two layouts that differ only in column order now share a contract, so
    # a database that carried both as active has to keep one. Preference:
    # the fixture-verified row, then the lowest profile_id -- the oldest
    # decision wins over a backfill. `is_active` is a selection flag;
    # nothing here rewrites `fixture_verified` on an existing row.
    op.execute(
        """
        WITH ranked AS (
            SELECT profile_id,
                   row_number() OVER (
                       PARTITION BY domain, plant_code, semantic_signature
                       ORDER BY fixture_verified DESC, profile_id ASC) AS rn
              FROM ref_template_profile
             WHERE is_active
        )
        UPDATE ref_template_profile p
           SET is_active = false
          FROM ranked r
         WHERE p.profile_id = r.profile_id AND r.rn > 1
        """
    )
    # Versions were dense per (plant, fingerprint); they are now dense per
    # contract. Renumbering keeps "version" meaning "how many decisions have
    # been made about this contract", which is what the publish function
    # increments.
    op.execute(
        """
        WITH ranked AS (
            SELECT profile_id,
                   row_number() OVER (
                       PARTITION BY domain, plant_code, semantic_signature
                       ORDER BY version ASC, profile_id ASC) AS rn
              FROM ref_template_profile
        )
        UPDATE ref_template_profile p
           SET version = r.rn
          FROM ranked r
         WHERE p.profile_id = r.profile_id AND p.version <> r.rn
        """
    )
    op.execute(
        "ALTER TABLE ref_template_profile ADD CONSTRAINT uq_profile_version_semantic "
        "UNIQUE (domain, plant_code, semantic_signature, version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_profile_active_semantic "
        "ON ref_template_profile (domain, plant_code, semantic_signature) "
        "WHERE is_active"
    )


# ---------------------------------------------------------------------
# 3. ref_template_column_policy
# ---------------------------------------------------------------------
def _column_policy() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ref_template_column_policy (
            policy_id      bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            profile_id     bigint NOT NULL
                               REFERENCES ref_template_profile (profile_id)
                               ON DELETE RESTRICT,
            raw_header     text NOT NULL,
            policy         text NOT NULL,
            logical_field  text,
            approved_by    text,
            reason         text,
            created_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_column_policy UNIQUE (profile_id, raw_header),
            CONSTRAINT ck_column_policy_verb
                CHECK (policy IN ('MAPPED','IGNORED')),
            -- A mapped column says what it maps to.
            CONSTRAINT ck_column_policy_mapped
                CHECK (policy <> 'MAPPED' OR logical_field IS NOT NULL),
            -- An ignored column says who decided and why. S9 forbids an
            -- auto-ignore, and a row nobody signed would be one.
            CONSTRAINT ck_column_policy_ignored
                CHECK (policy <> 'IGNORED'
                       OR (approved_by IS NOT NULL AND btrim(approved_by) <> ''
                           AND reason IS NOT NULL AND btrim(reason) <> ''))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_template_column_policy IS "
        "'What a named person decided about one header of one template "
        "profile (T26, design 5.3): MAPPED to a logical field, or IGNORED "
        "with an approver and a reason. Data only -- no column here holds "
        "SQL or Python. This is how FVL''s Panel2 becomes an approved "
        "auxiliary column instead of a permanent UNREVIEWED_HEADER. Written "
        "only by publish_template_profile; app_rw has SELECT.'"
    )
    op.execute("REVOKE ALL ON ref_template_column_policy FROM PUBLIC")
    _for_each_role("GRANT SELECT ON ref_template_column_policy TO {role};")


# ---------------------------------------------------------------------
# 4. plant-scoped model aliases
# ---------------------------------------------------------------------
def _plant_scoped_model_alias() -> None:
    op.execute(
        """
        ALTER TABLE ref_model_alias
            ADD COLUMN IF NOT EXISTS plant_code text
                REFERENCES ref_plant (plant_code) ON DELETE RESTRICT,
            ADD COLUMN IF NOT EXISTS alias_id bigint
                GENERATED BY DEFAULT AS IDENTITY
        """
    )
    op.execute("ALTER TABLE ref_model_alias DROP CONSTRAINT IF EXISTS ref_model_alias_pkey")
    op.execute(
        "ALTER TABLE ref_model_alias ADD CONSTRAINT pk_model_alias PRIMARY KEY (alias_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_model_alias_global "
        "ON ref_model_alias (raw_value) WHERE plant_code IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_model_alias_plant "
        "ON ref_model_alias (plant_code, raw_value) WHERE plant_code IS NOT NULL"
    )
    op.execute(
        "COMMENT ON COLUMN ref_model_alias.plant_code IS "
        "'Which plant writes this spelling (T26, spec S11). NULL means the "
        "spelling is unambiguous everywhere. The cleaner looks up the "
        "plant-scoped row first and falls back to the global one, so one "
        "plant''s local wording can never relabel another plant''s vehicle.'"
    )

    spellings = ", ".join(_quote(s) for s in ASSUMED_RANGER_SPELLINGS)
    spelling_rows = ", ".join(f"({_quote(s)})" for s in ASSUMED_RANGER_SPELLINGS)

    # (a) The owner's lock. Named, not derived: FVL bare `P703` and
    #     `P703 DBL` mean P703 DBL RANGER (S11, architect chat 2026-09-20/21).
    for plant in OWNER_LOCKED_RANGER_PLANTS:
        note = (
            f"T26 (revision 0009): owner lock 2026-09-20/21 -- at {plant} a "
            f"bare P703 is a P703 DBL RANGER. Relocated from the global "
            f"ASSUMPTION row, which this revision deletes so that no other "
            f"plant inherits it silently (spec S11)."
        )
        op.execute(
            f"""
            INSERT INTO ref_model_alias (raw_value, model_code, plant_code, note)
            SELECT v.raw_value, {_quote(RANGER)}, {_quote(plant)}, {_quote(note)}
              FROM (VALUES {spelling_rows}) AS v (raw_value)
             WHERE EXISTS (SELECT 1 FROM ref_plant p
                            WHERE p.plant_code = {_quote(plant)})
            ON CONFLICT DO NOTHING
            """
        )

    # (b) Evidence, not assumption. AAT and FTM keep the historical spelling
    #     only where their own staged rows show a workbook of theirs actually
    #     wrote it. A plant that never wrote `P703` does not get a rule about
    #     it, and nothing here reads SAP.
    plants = ", ".join(_quote(p) for p in EVIDENCE_RELOCATION_PLANTS)
    op.execute(
        f"""
        INSERT INTO ref_model_alias (raw_value, model_code, plant_code, note)
        SELECT DISTINCT a.raw_value, a.model_code, b.plant_code,
               'T26 (revision 0009): relocated from the global ASSUMPTION row '
               'because this plant''s own staged rows carry this spelling. '
               'Evidence, not a default (spec S11).'
          FROM ref_model_alias a
          -- `stg_raw.raw_model` is the cell as written. Compared the way the
          -- cleaner compares a model spelling (trim + case-fold), not the way
          -- the reader normalises a header.
          JOIN stg_raw s
            ON lower(btrim(s.raw_model)) = lower(btrim(a.raw_value))
          JOIN load_batch b ON b.load_id = s.load_id
         WHERE a.plant_code IS NULL
           AND a.raw_value IN ({spellings})
           AND b.plant_code IN ({plants})
        ON CONFLICT DO NOTHING
        """
    )

    # (c) Remove the global default. This is the one delete in `upgrade()`,
    #     and it is the point of the change: while these rows exist, every
    #     plant -- including SAP, whose `P703 RAP` is not a Ranger -- silently
    #     inherits an assumption nobody made about it.
    op.execute(
        f"DELETE FROM ref_model_alias "
        f"WHERE plant_code IS NULL AND raw_value IN ({spellings})"
    )


# ---------------------------------------------------------------------
# 5. plant-scoped colour aliases
# ---------------------------------------------------------------------
def _plant_scoped_color_alias() -> None:
    op.execute(
        """
        ALTER TABLE ref_color_alias
            ADD COLUMN IF NOT EXISTS plant_code text
                REFERENCES ref_plant (plant_code) ON DELETE RESTRICT,
            ADD COLUMN IF NOT EXISTS alias_id bigint
                GENERATED BY DEFAULT AS IDENTITY
        """
    )
    op.execute("ALTER TABLE ref_color_alias DROP CONSTRAINT IF EXISTS ref_color_alias_pkey")
    op.execute(
        "ALTER TABLE ref_color_alias ADD CONSTRAINT pk_color_alias PRIMARY KEY (alias_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_color_alias_global "
        "ON ref_color_alias (raw_value) WHERE plant_code IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_color_alias_plant "
        "ON ref_color_alias (plant_code, raw_value) WHERE plant_code IS NOT NULL"
    )
    op.execute(
        "COMMENT ON COLUMN ref_color_alias.plant_code IS "
        "'Which plant writes this colour spelling (T26, spec S12). Identity "
        "only: this table maps a spelling to a canonical ref_color and says "
        "nothing about a grading family. grading_family stays NULL and "
        "POST /standards stays 501 until D1/D2 are decided.'"
    )
    # No colour alias is relocated or seeded here. Unlike the model rows,
    # nothing in the reviewed workbooks shows a colour spelling that means
    # one thing at one plant and another elsewhere, and inventing a plant
    # scope for a row that works today would be a change with no evidence.


# ---------------------------------------------------------------------
# 6. ref_plant_zone_map proof columns
# ---------------------------------------------------------------------
def _zone_map_proof_columns() -> None:
    op.execute(
        """
        ALTER TABLE ref_plant_zone_map
            ADD COLUMN IF NOT EXISTS proof_hash char(64),
            ADD COLUMN IF NOT EXISTS proof_document text,
            ADD COLUMN IF NOT EXISTS verified_by text
        """
    )
    op.execute(
        "COMMENT ON COLUMN ref_plant_zone_map.proof_hash IS "
        "'SHA-256 of the workbook or checkpoint document a named plant/"
        "quality owner used to prove this mapping (T26, spec S15). No "
        "CHECK forces it on existing rows: the baseline SAP vocabulary "
        "predates this column, and failing a migration over history would "
        "not make that history proved. The P703 mapping-audit slice is what "
        "fills it.'"
    )
    op.execute(
        "COMMENT ON COLUMN ref_plant_zone_map.verified_by IS "
        "'The named plant/quality owner who proved the mapping, as distinct "
        "from approved_by (the Admin who recorded it). S15: ordinary visual "
        "approve is not enough, and automatic keyword/count/sequence "
        "activation is forbidden -- the mapping engine already swapped SAP "
        "tailgate Top/Bottom and got 20 of 25 FVL verticals wrong.'"
    )
    # Deliberately no INSERT here. T26 seeds no SAP or FVL zone map, approved
    # or proposed: sequence is not physical identity, and only a named owner
    # can say that FVL `25TGATE` is LTTAILGATE.


# ---------------------------------------------------------------------
# 7. stg_review_row.disposition gains AGGREGATE_ROW
# ---------------------------------------------------------------------
def _review_disposition() -> None:
    listed = ",".join(f"'{d}'" for d in REVIEW_DISPOSITIONS)
    op.execute(
        "ALTER TABLE stg_review_row DROP CONSTRAINT IF EXISTS ck_review_disposition"
    )
    op.execute(
        f"ALTER TABLE stg_review_row ADD CONSTRAINT ck_review_disposition "
        f"CHECK (disposition IN ({listed}))"
    )
    op.execute(
        "COMMENT ON CONSTRAINT ck_review_disposition ON stg_review_row IS "
        "'T26 adds AGGREGATE_ROW: a report roll-up such as a [All] "
        "hierarchy row, preserved in the projection and never a fact "
        "(spec S16). Widening a CHECK deletes no row, and app_rw still "
        "holds INSERT and SELECT only.'"
    )


# ---------------------------------------------------------------------
# 8. load_batch: domain, signature, sheet class, unreviewed headers
# ---------------------------------------------------------------------
def _load_batch_columns() -> None:
    op.execute(
        """
        ALTER TABLE load_batch
            ADD COLUMN IF NOT EXISTS domain text,
            ADD COLUMN IF NOT EXISTS semantic_signature text,
            ADD COLUMN IF NOT EXISTS sheet_class text,
            ADD COLUMN IF NOT EXISTS unreviewed_headers jsonb
        """
    )
    op.execute(
        "COMMENT ON COLUMN load_batch.semantic_signature IS "
        "'The order-independent contract this sheet carried at parse time "
        "(T26). template_fingerprint beside it is the exact ordered-layout "
        "hash: when the two disagree between one month and the next, the "
        "columns moved and the contract did not.'"
    )
    op.execute(
        "COMMENT ON COLUMN load_batch.sheet_class IS "
        "'WAVESCAN, OUT_OF_SCOPE_SHEET or UNKNOWN_DATA_SHEET, decided from "
        "the header row and never from the tab name (T26, spec S10).'"
    )
    op.execute(
        "COMMENT ON COLUMN load_batch.unreviewed_headers IS "
        "'Headers this parse recognised as neither a logical field nor an "
        "approved ignored column. Non-empty means UNREVIEWED_HEADER blocks "
        "the commit until somebody decides (spec S9). Re-derived on every "
        "replay, so an approved decision clears it from the stored bytes.'"
    )
    columns = ", ".join(LOAD_BATCH_UPDATABLE_COLUMNS)
    _for_each_role(
        f"""
        REVOKE UPDATE ON load_batch FROM {{role}};
        GRANT UPDATE ({columns}) ON load_batch TO {{role}};
        """
    )


# ---------------------------------------------------------------------
# 9. publish_template_profile
# ---------------------------------------------------------------------
def _publish_function() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION publish_template_profile(
            p_plant_code          text,
            p_domain              text,
            p_semantic_signature  text,
            p_template_fingerprint text,
            p_fixture_file_hash   char(64),
            p_named_owner         text,
            p_notes               text,
            p_fill_missing_plant  boolean,
            p_ignored             jsonb,
            p_actor_user_id       uuid,
            p_correlation_id      text
        )
        RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $fn$
        DECLARE
            v_owner    text := btrim(coalesce(p_named_owner, ''));
            v_notes    text := btrim(coalesce(p_notes, ''));
            v_version  integer;
            v_profile  bigint;
            v_previous bigint;
            v_item     jsonb;
            v_header   text;
            v_reason   text;
            v_ignored  integer := 0;
        BEGIN
            IF v_owner = '' THEN
                RAISE EXCEPTION
                    'named_owner is required: a verified layout records the '
                    'person who proved it, not the route that wrote it (spec S20)'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF v_notes = '' THEN
                RAISE EXCEPTION
                    'notes are required: they name the proof, beside the '
                    'fixture hash (spec S20)'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF p_fixture_file_hash IS NULL OR btrim(p_fixture_file_hash) = '' THEN
                RAISE EXCEPTION
                    'fixture_file_hash is required: publishing names the '
                    'stored workbook that proved the layout'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF p_domain IS DISTINCT FROM {_quote(DOMAIN)} THEN
                RAISE EXCEPTION
                    'domain % is not implemented; this platform reads '
                    '{DOMAIN} only (spec S1). FilmThickness is a later '
                    'domain package, not a flag on this one.', p_domain
                    USING ERRCODE = 'feature_not_supported';
            END IF;
            IF p_semantic_signature IS NULL OR btrim(p_semantic_signature) = '' THEN
                RAISE EXCEPTION 'semantic_signature is required'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM ref_plant WHERE plant_code = p_plant_code
            ) THEN
                RAISE EXCEPTION 'plant % is not in ref_plant', p_plant_code
                    USING ERRCODE = 'no_data_found';
            END IF;

            -- The previous active version for this contract. Locked, then
            -- deactivated -- never updated in place. `fixture_verified` on an
            -- old row is a statement about a decision that was made, and a
            -- statement about the past is not editable (ADR 0005's reasoning,
            -- applied to reference data).
            SELECT profile_id INTO v_previous
              FROM ref_template_profile
             WHERE domain = p_domain
               AND plant_code = p_plant_code
               AND semantic_signature = p_semantic_signature
               AND is_active
             FOR UPDATE;

            SELECT coalesce(max(version), 0) + 1 INTO v_version
              FROM ref_template_profile
             WHERE domain = p_domain
               AND plant_code = p_plant_code
               AND semantic_signature = p_semantic_signature;

            IF v_previous IS NOT NULL THEN
                UPDATE ref_template_profile
                   SET is_active = false
                 WHERE profile_id = v_previous;
            END IF;

            INSERT INTO ref_template_profile
                (plant_code, domain, semantic_signature, template_fingerprint,
                 version, is_active, fixture_verified, fixture_file_hash,
                 fill_missing_plant, verified_by, verified_at, notes)
            VALUES
                (p_plant_code, p_domain, p_semantic_signature,
                 p_template_fingerprint, v_version, true, true,
                 p_fixture_file_hash, coalesce(p_fill_missing_plant, false),
                 v_owner, now(), v_notes)
            RETURNING profile_id INTO v_profile;

            FOR v_item IN
                SELECT * FROM jsonb_array_elements(coalesce(p_ignored, '[]'::jsonb))
            LOOP
                v_header := replace(
                    lower(btrim(coalesce(v_item ->> 'header', ''))), '_', ' ');
                v_reason := btrim(coalesce(v_item ->> 'reason', ''));
                IF v_header = '' THEN
                    RAISE EXCEPTION 'an ignored header cannot be blank'
                        USING ERRCODE = 'check_violation';
                END IF;
                IF v_reason = '' THEN
                    v_reason := v_notes;
                END IF;
                INSERT INTO ref_template_column_policy
                    (profile_id, raw_header, policy, approved_by, reason)
                VALUES (v_profile, v_header, 'IGNORED', v_owner, v_reason);
                v_ignored := v_ignored + 1;
            END LOOP;

            -- In the same transaction as the mutation (`AGENTS.md` section 2).
            -- A publish that committed without this row would be a layout
            -- that became commit-capable with nobody named.
            INSERT INTO audit_event
                (actor_user_id, actor_type, action, entity_type, entity_id,
                 before, after, correlation_id)
            VALUES (
                p_actor_user_id,
                CASE WHEN p_actor_user_id IS NULL THEN 'system' ELSE 'user' END,
                'profile.publish', 'ref_template_profile', v_profile::text,
                CASE WHEN v_previous IS NULL THEN NULL
                     ELSE jsonb_build_object('previous_profile_id', v_previous,
                                             'previous_is_active', true) END,
                jsonb_build_object(
                    'profile_id', v_profile,
                    'version', v_version,
                    'domain', p_domain,
                    'plant_code', p_plant_code,
                    'semantic_signature', p_semantic_signature,
                    'template_fingerprint', p_template_fingerprint,
                    'fixture_verified', true,
                    'fixture_file_hash', p_fixture_file_hash,
                    'fill_missing_plant', coalesce(p_fill_missing_plant, false),
                    'named_owner', v_owner,
                    'notes', v_notes,
                    'ignored_headers', v_ignored),
                p_correlation_id);

            RETURN jsonb_build_object(
                'profile_id', v_profile,
                'version', v_version,
                'domain', p_domain,
                'plant_code', p_plant_code,
                'semantic_signature', p_semantic_signature,
                'template_fingerprint', p_template_fingerprint,
                'fixture_verified', true,
                'fixture_file_hash', p_fixture_file_hash,
                'named_owner', v_owner,
                'previous_profile_id', v_previous,
                'ignored_headers', v_ignored,
                'audit_action', 'profile.publish');
        END;
        $fn$;
        """
    )
    op.execute(
        "COMMENT ON FUNCTION publish_template_profile IS "
        "'The only way the application can create a fixture-verified "
        "template profile version (T26, spec S20). Requires a named owner, "
        "notes and a proving stored-workbook hash; appends a version, "
        "deactivates the previous active one for the same (domain, plant, "
        "semantic signature), writes the column policy, and writes "
        "audit_event in the same transaction. It cannot touch wavescan or "
        "load_batch. app_rw still holds no INSERT/UPDATE/DELETE on "
        "ref_template_profile, so the Admin mapping-approve route cannot "
        "promote a layout as a side effect (M6).'"
    )
    op.execute("REVOKE ALL ON FUNCTION publish_template_profile FROM PUBLIC")
    _for_each_role("GRANT EXECUTE ON FUNCTION publish_template_profile TO {role};")


# =====================================================================
def downgrade() -> None:
    """Back to T18's ordered-fingerprint selection.

    Nothing here loses a measurement. The two global model-alias rows
    `upgrade()` deleted are re-inserted verbatim, including the note that
    named them an assumption.
    """
    op.execute("DROP FUNCTION IF EXISTS publish_template_profile("
               "text, text, text, text, char, text, text, boolean, jsonb, uuid, text)")

    columns = ", ".join(
        c for c in LOAD_BATCH_UPDATABLE_COLUMNS
        if c not in ("domain", "semantic_signature", "sheet_class",
                     "unreviewed_headers")
    )
    _for_each_role(
        f"""
        REVOKE UPDATE ON load_batch FROM {{role}};
        GRANT UPDATE ({columns}) ON load_batch TO {{role}};
        """
    )
    op.execute(
        "ALTER TABLE load_batch "
        "DROP COLUMN IF EXISTS domain, "
        "DROP COLUMN IF EXISTS semantic_signature, "
        "DROP COLUMN IF EXISTS sheet_class, "
        "DROP COLUMN IF EXISTS unreviewed_headers"
    )

    # An AGGREGATE_ROW projection row cannot survive T18's CHECK, and it is
    # re-derivable from the stored bytes, so replaying is the way back.
    op.execute(
        "ALTER TABLE stg_review_row DROP CONSTRAINT IF EXISTS ck_review_disposition"
    )
    op.execute("DELETE FROM stg_review_row WHERE disposition = 'AGGREGATE_ROW'")
    op.execute(
        "ALTER TABLE stg_review_row ADD CONSTRAINT ck_review_disposition "
        "CHECK (disposition IN ('LOAD','DUPLICATE','REJECT','QUARANTINE'))"
    )

    op.execute(
        "ALTER TABLE ref_plant_zone_map "
        "DROP COLUMN IF EXISTS proof_hash, "
        "DROP COLUMN IF EXISTS proof_document, "
        "DROP COLUMN IF EXISTS verified_by"
    )

    for table in ("ref_color_alias", "ref_model_alias"):
        short = table.replace("ref_", "").replace("_alias", "")
        op.execute(f"DROP INDEX IF EXISTS uq_{short}_alias_plant")
        op.execute(f"DROP INDEX IF EXISTS uq_{short}_alias_global")
        op.execute(f"DELETE FROM {table} WHERE plant_code IS NOT NULL")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS pk_{short}_alias")
        op.execute(
            f"ALTER TABLE {table} "
            f"DROP COLUMN IF EXISTS alias_id, DROP COLUMN IF EXISTS plant_code"
        )
        op.execute(f"ALTER TABLE {table} ADD PRIMARY KEY (raw_value)")

    op.execute(
        f"""
        INSERT INTO ref_model_alias (raw_value, model_code, note) VALUES
            ({_quote(ASSUMED_RANGER_SPELLINGS[0])}, {_quote(RANGER)},
             'ASSUMPTION: no variant named => RANGER'),
            ({_quote(ASSUMED_RANGER_SPELLINGS[1])}, {_quote(RANGER)},
             'ASSUMPTION: no variant named => RANGER')
        ON CONFLICT DO NOTHING
        """
    )

    op.execute("DROP TABLE IF EXISTS ref_template_column_policy")

    op.execute("DROP INDEX IF EXISTS uq_profile_active_semantic")
    op.execute(
        "ALTER TABLE ref_template_profile "
        "DROP CONSTRAINT IF EXISTS uq_profile_version_semantic"
    )
    op.execute(
        "ALTER TABLE ref_template_profile "
        "DROP CONSTRAINT IF EXISTS ck_profile_verifier_named"
    )
    op.execute(
        "ALTER TABLE ref_template_profile "
        "DROP COLUMN IF EXISTS domain, "
        "DROP COLUMN IF EXISTS semantic_signature, "
        "DROP COLUMN IF EXISTS verified_by, "
        "DROP COLUMN IF EXISTS verified_at"
    )
    op.execute(
        "ALTER TABLE ref_template_profile ADD CONSTRAINT uq_profile_version "
        "UNIQUE (plant_code, template_fingerprint, version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_profile_active "
        "ON ref_template_profile (plant_code, template_fingerprint) WHERE is_active"
    )

    op.execute(
        "ALTER TABLE ref_column_alias "
        "DROP CONSTRAINT IF EXISTS uq_column_alias_domain_header"
    )
    op.execute("ALTER TABLE ref_column_alias DROP COLUMN IF EXISTS domain")
    op.execute(
        "ALTER TABLE ref_column_alias "
        "ADD CONSTRAINT uq_column_alias_raw_header UNIQUE (raw_header)"
    )
