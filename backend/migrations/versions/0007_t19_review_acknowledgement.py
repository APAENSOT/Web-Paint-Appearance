"""T19: acknowledged warnings, bound to the review they were read from.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-16

One table. **Nothing in this revision deletes anything**, no existing
function is rewritten, and no grant is widened beyond the new table -- so
unlike 0006 this one is not destructive and needs no owner approval line
beyond the ordinary one.

**`review_acknowledgement`.** T18 gave a reviewer the rows; it gave them no
way to say "I have read these rejects and I still want the rest committed".
Until now the only two answers a warning could have were "commit anyway,
silently" and "do not commit", and the first of those is the one this
platform exists to prevent: 41 rejected rows scrolling past on a Friday
afternoon is not a decision, it is an accident.

Three properties, and each is a column rather than a convention:

1. **It binds to a review revision.** `review_revision` is the projection
   hash T18 computes, so an acknowledgement is a statement about *these
   rows*, not about this batch forever. Replay the bytes after an approved
   alias and the projection changes; the old acknowledgement stays in the
   table as evidence that somebody read the older proposal, and it no longer
   satisfies the gate. Design section 10: "Review changed after ack ->
   invalidate acknowledgements; review again."

2. **Rejected and quarantined rows require a note.** A `CHECK`, not a
   validator, because the reason is the whole point of the record: design
   M11 says those two categories carry a mandatory audited note, and a note
   that the database would accept as blank is not mandatory. Duplicates and
   the advisory possible-replacement warning may be acknowledged without
   one -- a duplicate row is already fully described by the row it matched.

3. **It is append-only.** `app_rw` gets `SELECT, INSERT` and neither UPDATE
   nor DELETE. Changing your mind means acknowledging again, which leaves
   both records; and a replay cannot tidy the old ones away, because
   `reset_batch_staging` is not touched here and holds no DELETE on this
   table. That is deliberate: the projection is staging and re-derivable,
   while "a named person read this and accepted it at 14:32" is evidence,
   and evidence is not cleared by re-running a parse.

`actor_user_id` is NOT NULL for the same reason `measurement_supersession`'s
is (revision 0003): an acknowledgement nobody can name is not an
acknowledgement.

`downgrade()` drops the table. Doing so loses the record of who accepted
what, which no replay can rebuild -- so it is reversible in the schema sense
only, and the docstring says so rather than pretending otherwise.
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")

#: The warning categories a reviewer can acknowledge (T19 locked decision 7).
#: The first three are the ones that **block** a commit while unacknowledged,
#: because each means rows the plant sent are not becoming measurements. The
#: fourth is advisory: a newer workbook overlapping an older active one is a
#: hint that somebody may want to supersede, never a reason to refuse a
#: commit and never an automatic retirement (design M14).
CATEGORIES = (
    "REJECTED_ROWS",
    "QUARANTINED_MODELS",
    "DUPLICATE_ROWS",
    "POSSIBLE_REPLACEMENT",
)

#: The two whose acknowledgement carries a mandatory note (design M11).
NOTE_REQUIRED = ("REJECTED_ROWS", "QUARANTINED_MODELS")

#: Same bound as `SupersedeCreate.reason` and `CorrectionCreate.reason`, so a
#: reviewer does not meet three different limits for three different notes.
NOTE_MAX = 2000


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


def upgrade() -> None:
    categories = ", ".join(f"'{c}'" for c in CATEGORIES)
    note_required = ", ".join(f"'{c}'" for c in NOTE_REQUIRED)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS review_acknowledgement (
            ack_id          bigserial PRIMARY KEY,
            load_id         bigint NOT NULL
                                REFERENCES load_batch (load_id)
                                ON DELETE RESTRICT,
            plant_code      text NOT NULL
                                REFERENCES ref_plant (plant_code)
                                ON DELETE RESTRICT,
            file_hash       char(64) NOT NULL,
            category        text NOT NULL,
            note            text,
            review_revision char(64) NOT NULL,
            actor_user_id   uuid NOT NULL REFERENCES app_user (id),
            created_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_ack_category CHECK (category IN ({categories})),
            -- The note is the record. A blank one is not a record, so the
            -- database refuses it rather than storing an empty string that
            -- reads like a decision (design M11).
            CONSTRAINT ck_ack_note_required CHECK (
                category NOT IN ({note_required})
                OR (note IS NOT NULL AND length(btrim(note)) > 0)
            ),
            CONSTRAINT ck_ack_note_length CHECK (
                note IS NULL OR length(note) <= {NOTE_MAX}
            )
        )
        """
    )
    # The gate asks one question -- "is this category acknowledged for this
    # batch at this revision" -- so that is the index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ack_current "
        "ON review_acknowledgement (load_id, review_revision, category)"
    )
    op.execute(
        "COMMENT ON TABLE review_acknowledgement IS "
        "'A named person accepted one warning category for one batch at one "
        "review_revision (T19, design M11). Append-only: app_rw holds SELECT "
        "and INSERT and nothing else, and a replay does not clear it -- the "
        "projection is re-derivable staging, this is evidence. An "
        "acknowledgement of a superseded revision stays here and stops "
        "satisfying the commit gate.'"
    )
    op.execute(
        "COMMENT ON COLUMN review_acknowledgement.review_revision IS "
        "'load_batch.review_revision as it stood when this was written. The "
        "commit gate compares against the batch current value, so re-parsing "
        "the bytes invalidates the acknowledgement without deleting it.'"
    )
    op.execute("REVOKE ALL ON review_acknowledgement FROM PUBLIC")
    _for_each_role(
        """
        -- No UPDATE: an acknowledgement is not edited, it is superseded by
        -- another one. No DELETE: ADR 0005 reasoning, applied to evidence
        -- about a person rather than about a measurement.
        GRANT SELECT, INSERT ON review_acknowledgement TO {role};
        GRANT USAGE, SELECT ON SEQUENCE review_acknowledgement_ack_id_seq TO {role};
        """
    )


def downgrade() -> None:
    """Drop the table.

    Reversible in the schema sense only: the rows say who read which rejects
    and accepted them, and nothing in the object store can rebuild that. A
    database that has acknowledged anything should be restored rather than
    downgraded.
    """
    op.execute("DROP TABLE IF EXISTS review_acknowledgement")
