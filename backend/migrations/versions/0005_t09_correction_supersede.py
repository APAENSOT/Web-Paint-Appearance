"""T09: make room for a correction row.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-13

One change, and it is the only thing T09 needs from the database. Everything
else T09 does was already built: `measurement_supersession`, its
`AFTER INSERT` trigger `mark_measurement_superseded`, the `BEFORE INSERT`
guard `trg_reject_presuperseded`, and the column-scoped `UPDATE` on
`load_batch.status` / `superseded_by` all landed in T02 and T04. **No grant
is added here**, and in particular `app_rw` still holds no `UPDATE` and no
`DELETE` on `wavescan`. T09 calls ADR 0005's machinery; it does not widen it.

**`uq_ws_load_row` becomes a partial unique index.**

`01-DATA-MODEL.md` §5 makes a measurement's identity `(load_id, source_row)`
-- that pair *is* the spreadsheet cell -- and T02 enforced it with
`UNIQUE (load_id, source_row)`. §5 of the same document then describes a
correction as "a new row: `corrects_measurement_id` set, unchanged fields
copied, new values". Those two sentences cannot both hold: a correction to
row 7 of batch 42 is another row claiming `(42, 7)`, and the unique refuses
it. The constraint as written makes the correction flow the same document
mandates impossible to execute.

So the uniqueness is narrowed to the rows it was written for:

    UNIQUE (load_id, source_row) WHERE corrects_measurement_id IS NULL

**Ingest uniqueness is unchanged.** Every row `services/ingest.py` writes has
`corrects_measurement_id IS NULL`, so every ingest row is still checked
against every other ingest row, and loading the same spreadsheet row twice is
still refused by the database rather than by a `SELECT`. What is now allowed
is exactly the row ADR 0005 requires: one that names the measurement it
corrects.

**Why an index and not a constraint.** PostgreSQL has no partial `UNIQUE`
table constraint -- `ALTER TABLE ... ADD CONSTRAINT ... WHERE` is not valid
syntax. A partial unique *index* is the only way to express this, and it
enforces the same thing. The visible consequence is that the rule no longer
appears in `pg_constraint`; it is in `pg_indexes`. A T02 test that looked
there is re-aimed rather than loosened, and the reason is recorded in
`docs/reports/T09-IMMUTABLE.md`.

**This revision drops a uniqueness constraint** and therefore needs the
owner's explicit approval line when the owner commits (`AGENTS.md` §2).
Nothing in `upgrade()` deletes or modifies a row: the replacement index is
built over the existing table and the migration fails loudly if any current
row would violate it.

`downgrade()` restores `uq_ws_load_row` and **refuses** first if any
`(load_id, source_row)` pair is claimed more than once -- which is precisely
the state that exists once a correction has been written. Reversing this
revision after a correction would mean deleting a fact, so it stops and says
so instead.
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

#: The rule T02 wrote, and the rule T09 replaces it with. Same columns, same
#: purpose; the predicate is what is new.
OLD_CONSTRAINT = "uq_ws_load_row"
NEW_INDEX = "uq_ws_load_row_original"


def upgrade() -> None:
    # The partial index is created BEFORE the constraint is dropped, so the
    # table is never momentarily unprotected -- if the index build fails, the
    # transaction rolls back with the original rule still in force.
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {NEW_INDEX}
            ON wavescan (load_id, source_row)
         WHERE corrects_measurement_id IS NULL
        """
    )
    op.execute(
        f"COMMENT ON INDEX {NEW_INDEX} IS "
        "'A measurement''s identity is (load_id, source_row) -- the "
        "spreadsheet cell it came from (01-DATA-MODEL.md section 5). Ingest "
        "rows occupy that slot exclusively, so the same cell still cannot be "
        "loaded twice. Correction rows carry corrects_measurement_id and are "
        "outside the predicate, which is what lets ADR 0005''s "
        "insert-a-new-row correction exist at all. T09.'"
    )
    op.execute(f"ALTER TABLE wavescan DROP CONSTRAINT IF EXISTS {OLD_CONSTRAINT}")


def downgrade() -> None:
    # A full unique over (load_id, source_row) cannot coexist with any
    # correction row, because a correction deliberately shares that pair with
    # the measurement it corrects. Restoring it would require deleting one of
    # them, and no role in this system may delete a fact (ADR 0005). Refuse,
    # naming the rows, rather than failing later with a constraint error that
    # does not explain itself.
    op.execute(
        """
        DO $$
        DECLARE
            v_pairs text;
            v_n     bigint;
        BEGIN
            SELECT count(*), string_agg(pair, ', ' ORDER BY pair)
              INTO v_n, v_pairs
              FROM (
                    SELECT '(' || load_id || ', ' || source_row || ')' AS pair
                      FROM wavescan
                     GROUP BY load_id, source_row
                    HAVING count(*) > 1
                     LIMIT 20
                   ) AS collisions;

            IF COALESCE(v_n, 0) > 0 THEN
                RAISE EXCEPTION
                    'cannot restore a full UNIQUE (load_id, source_row): % cell(s) are claimed by more than one measurement, which is what a correction row is. Restoring the constraint would mean deleting a fact (ADR 0005). Cells: %',
                    v_n, v_pairs
                    USING ERRCODE = 'unique_violation',
                    HINT = 'A database carrying corrections cannot be '
                        'downgraded past revision 0005. Read '
                        'docs/reports/T09-IMMUTABLE.md.';
            END IF;
        END $$;
        """
    )
    op.execute(
        f"ALTER TABLE wavescan ADD CONSTRAINT {OLD_CONSTRAINT} "
        f"UNIQUE (load_id, source_row)"
    )
    op.execute(f"DROP INDEX IF EXISTS {NEW_INDEX}")
