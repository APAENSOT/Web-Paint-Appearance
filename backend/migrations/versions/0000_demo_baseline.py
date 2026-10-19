"""Demo baseline schema: the tables T01 assumed were already there.

Revision ID: 0000
Revises:
Create Date: 2026-09-08

Why this revision exists
------------------------
T01 shipped revision 0001 as the first migration, but 0001 *alters* the
schema the demo project created by hand (`ALTER TABLE load_batch ...`,
`GRANT ... ON wavescan`). On a database that has never had that schema --
a fresh Compose Postgres, or CI -- `alembic upgrade head` therefore failed
before it began:

    INFO  [alembic.runtime.migration] Running upgrade  -> 0001, T01 security remediation
    psycopg.errors.UndefinedTable: relation "load_batch" does not exist

T02's acceptance criterion is that `alembic upgrade head` succeeds on an
empty database, so the chain needs a base. This revision is that base: it
creates the demo schema from the SQL the demo project shipped, so the
repository can build a database from nothing.

What it applies
---------------
Byte-faithful copies of `Paint Appearance/Component/Database/sql/`, taken
into `backend/migrations/sql/baseline/` (T02 spec, "Source schema"). The
copies differ from the originals in exactly one way: the outer `BEGIN;` /
`COMMIT;` lines are removed, because Alembic owns the transaction and a
COMMIT inside a revision would end it early. Nothing else is edited --
`docs/AGENTS.md` rule 4 (move, do not retype) applies to schema as much as
to domain logic.

Deliberately NOT included:

* `06_demo_data.sql` -- two demo vehicles. Fixture data, not schema; it
  belongs to the test harness, not to every database this chain builds.
* `10_role.sql` -- roles and grants are 0001's job, and 0001 already
  guards every role reference with an existence check, so a database built
  from this baseline simply has no `wavescan_loader` and gets `app_rw`
  instead.

Safety
------
This revision refuses to touch a database that already has any part of the
demo schema. The copied SQL contains `DROP TABLE IF EXISTS ... CASCADE`
headers from the demo's re-runnable scripts, so running it over a populated
database would destroy data. The guard below makes that impossible: if any
demo table is present the revision adopts the existing schema and does
nothing, which is also exactly what an already-provisioned database (the
intern's) needs when it is first brought under Alembic control.
"""

from __future__ import annotations

from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0000"
down_revision = None
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql" / "baseline"

# Applied in dependency order: references first, then staging, facts,
# quarantine, views, then the multi-plant adapter and SAP vocabulary.
BASELINE_FILES = (
    "01_reference.sql",
    "02_staging.sql",
    "03_wavescan.sql",
    "04_quarantine.sql",
    "05_views.sql",
    "11_plant_zone_map.sql",
    "12_sap_vocabulary.sql",
    "13_sap_plant.sql",
    "14_sap_june_vocabulary.sql",
)

# If ANY of these exist, the database already has the baseline.
DEMO_TABLES = (
    "ref_plant", "ref_model", "ref_checkzone", "ref_color", "ref_paintline",
    "load_batch", "stg_raw", "wavescan", "reject_log", "unidentified_model",
)


def _existing_demo_tables(conn) -> list[str]:
    rows = conn.execute(
        sa.text(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename = ANY(:names)
            ORDER BY tablename
            """
        ),
        {"names": list(DEMO_TABLES)},
    ).fetchall()
    return [r[0] for r in rows]


def upgrade() -> None:
    conn = op.get_bind()
    present = _existing_demo_tables(conn)

    if present:
        # A partially-present schema is the dangerous case: applying the
        # baseline would DROP ... CASCADE the tables that DO exist, taking
        # their rows with them. Refuse before doing anything.
        if len(present) != len(DEMO_TABLES):
            missing = sorted(set(DEMO_TABLES) - set(present))
            raise RuntimeError(
                "0000 precondition failed: the database has SOME of the demo "
                "schema but not all of it.\n"
                f"  present ({len(present)}): {', '.join(present)}\n"
                f"  missing ({len(missing)}): {', '.join(missing)}\n"
                "Applying the baseline would DROP and recreate the tables that "
                "are present, destroying their rows. Restore the missing tables "
                "by hand, or start from an empty database, then re-run."
            )

        # Fully-provisioned database (e.g. the intern's local one). Adopt it
        # as-is: this is what bringing an existing database under Alembic
        # control looks like.
        print(
            f"0000: demo schema already present (all {len(DEMO_TABLES)} tables) "
            "- adopting the existing schema, applying nothing."
        )
        return

    for name in BASELINE_FILES:
        path = SQL_DIR / name
        if not path.exists():
            raise RuntimeError(f"0000: baseline SQL missing: {path}")
        op.execute(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError(
        "0000 is the base revision and is not reversible.\n"
        "\n"
        "Downgrading it means dropping every reference, staging, fact and "
        "quarantine table in the schema -- that is 'delete the database', not "
        "a migration step. Drop the database explicitly if that is what you "
        "want."
    )
