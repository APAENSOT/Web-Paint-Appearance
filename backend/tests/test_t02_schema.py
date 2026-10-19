"""T02 -- the schema matches docs/01-DATA-MODEL.md.

Every assertion here is traceable to a line of that document or to
docs/04-ANALYSIS.md. The point is not "the migration ran" -- it is that the
shape the migration produced is the shape the design asked for, including
the parts that are easy to get subtly wrong: measurement precision, which
statuses are legal, and which columns stay NULL because a decision is still
open (D2).

Structural assertions run on the admin connection (catalog reads); every
behavioural assertion runs as the application role, because what the
application can do is the only thing that matters.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from psycopg import errors as pgerr

pytestmark = pytest.mark.schema

# ---------------------------------------------------------------------
# Reference data the design pins exactly
# ---------------------------------------------------------------------

# 01-DATA-MODEL.md section 3. T21 CHANGE: revision 0008 adds ABANDONED.
LOAD_BATCH_STATUSES = {
    "RUNNING", "PENDING_REVIEW", "COMMITTED",
    "FAILED", "SUPERSEDED", "REJECTED_TEMPLATE", "ABANDONED",
}
RETIRED_STATUSES = {"SUCCESS", "ROLLED_BACK"}

# 04-ANALYSIS.md section 3 / Prototype.html COLOR_FAMILY_ORDER (1807-1814).
COLOR_FAMILY_ORDER = [
    "Light Metallics", "Medium Metallics", "Dark Metallics",
    "Light Solids", "Medium Solids", "Dark Solids",
]

# 04-ANALYSIS.md section 3, DEFAULT_STANDARDS (Prototype.html 1798-1805).
# family -> (fordH, fordV, minH, minV)
DEFAULT_STANDARDS = {
    "Light Metallics":  (57, 44, 50, 37),
    "Medium Metallics": (60, 47, 53, 40),
    "Dark Metallics":   (62, 49, 55, 42),
    "Light Solids":     (62, 49, 55, 42),
    "Medium Solids":    (65, 52, 58, 45),
    "Dark Solids":      (67, 54, 60, 47),
}

# reader.py:24-46 HEADER_ALIASES, normalised (lower, trim, '_' -> ' ').
HEADER_ALIASES = {
    "date": {"date", "painted date", "paint date", "measured date"},
    "month": {"month"},
    "year": {"year"},
    "plant": {"plant"},
    "model": {"model"},
    "checkzone": {"checkzone", "check zone", "zone"},
    "color": {"color", "colour"},
    "tolerance_group": {"tolerance group", "tolerancegroup", "tolerance"},
    "paintline": {"paintline", "paint line", "booth"},
    "serial_no": {"serial no", "serial no.", "serialno", "serial number", "serial"},
    "lw": {"lw"}, "sw": {"sw"}, "cf": {"cf"}, "doi": {"doi"}, "du": {"du"},
    "wa": {"wa"}, "wb": {"wb"}, "wc": {"wc"}, "wd": {"wd"}, "we": {"we"},
    "b": {"b"},
}

MEASURE_COLUMNS = ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b")


def _column(conn, table: str, column: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s AND column_name=%s
            """,
            (table, column),
        )
        return cur.fetchone()


# =====================================================================
# load_batch (01-DATA-MODEL.md section 3)
# =====================================================================


def test_load_batch_status_check_matches_the_new_lifecycle(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid='load_batch'::regclass AND contype='c'
              AND pg_get_constraintdef(oid) ILIKE '%%status%%'
              AND pg_get_constraintdef(oid) NOT ILIKE '%%rows_in_file%%'
            """
        )
        defs = " ".join(r[0] for r in cur.fetchall())

    assert defs, "load_batch has no status CHECK constraint"
    for status in LOAD_BATCH_STATUSES:
        assert status in defs, f"status CHECK does not allow {status}"
    for status in RETIRED_STATUSES:
        assert status not in defs, (
            f"retired status {status} is still allowed; "
            "01-DATA-MODEL.md section 3 removed it"
        )


@pytest.mark.parametrize("status", sorted(LOAD_BATCH_STATUSES))
def test_every_new_status_is_accepted(app_conn, status):
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO load_batch (source_file, source_sheet, file_hash,
                                    raw_store_key, status)
            VALUES ('T02.xlsx','s', %s, %s, %s) RETURNING load_id
            """,
            (uuid.uuid4().hex + uuid.uuid4().hex[:32], "raw/t02", status),
        )
        assert cur.fetchone()[0] > 0


@pytest.mark.parametrize("status", sorted(RETIRED_STATUSES))
def test_retired_statuses_are_rejected(app_conn, status):
    """SUCCESS became COMMITTED; ROLLED_BACK became FAILED."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                """
                INSERT INTO load_batch (source_file, source_sheet, file_hash,
                                        raw_store_key, status)
                VALUES ('T02.xlsx','s', %s, %s, %s)
                """,
                (uuid.uuid4().hex + uuid.uuid4().hex[:32], "raw/t02", status),
            )


def test_batch_balance_check_is_keyed_on_committed(admin_conn):
    """The balance rule must follow the renamed status, not the old one."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname='ck_batch_balance' AND conrelid='load_batch'::regclass"
        )
        row = cur.fetchone()

    assert row is not None, "ck_batch_balance is missing"
    assert "COMMITTED" in row[0], f"ck_batch_balance still keys on: {row[0]}"
    assert "SUCCESS" not in row[0]


def test_committed_batch_must_account_for_every_row(app_conn):
    """ck_batch_balance still bites, now on COMMITTED."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                """
                INSERT INTO load_batch (source_file, source_sheet, file_hash,
                                        raw_store_key, status, rows_in_file,
                                        rows_loaded, rows_duplicate,
                                        rows_rejected, rows_quarantine)
                VALUES ('T02.xlsx','s',%s,'raw/t02','COMMITTED',10,1,1,1,1)
                """,
                (uuid.uuid4().hex + uuid.uuid4().hex[:32],),
            )


def test_load_batch_has_the_new_columns(admin_conn):
    assert _column(admin_conn, "load_batch", "raw_store_key")[1] == "NO", \
        "raw_store_key must be NOT NULL"
    assert _column(admin_conn, "load_batch", "template_fingerprint") is not None
    assert _column(admin_conn, "load_batch", "raw_headers")[0] == "jsonb"
    assert _column(admin_conn, "load_batch", "superseded_by") is not None


def test_load_batch_file_hash_is_char64_not_null(admin_conn):
    dt, nullable, _ = _column(admin_conn, "load_batch", "file_hash")
    assert dt == "character", f"file_hash should be char(64), got {dt}"
    assert nullable == "NO", "file_hash must be NOT NULL (a file IS its bytes)"


def test_load_batch_loaded_by_is_a_person_not_a_role(admin_conn):
    """01-DATA-MODEL.md principle 7: attribution is a person."""
    dt, _, _ = _column(admin_conn, "load_batch", "loaded_by")
    assert dt == "uuid", f"loaded_by should be uuid REFERENCES app_user, got {dt}"

    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT confrelid::regclass::text
            FROM pg_constraint
            WHERE contype='f' AND conrelid='load_batch'::regclass
              AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                   WHERE attrelid='load_batch'::regclass
                                     AND attname='loaded_by')]
            """
        )
        assert cur.fetchone()[0] == "app_user"


@pytest.mark.parametrize("column", ["started_at", "finished_at"])
def test_load_batch_timestamps_are_timestamptz(admin_conn, column):
    """Principle 8: four plants, three time zones."""
    dt, _, _ = _column(admin_conn, "load_batch", column)
    assert dt == "timestamp with time zone", f"{column} is {dt}"


# =====================================================================
# stg_raw (section 4)
# =====================================================================


def test_stg_raw_has_extra_and_raw_headers(admin_conn):
    dt, nullable, default = _column(admin_conn, "stg_raw", "extra")
    assert dt == "jsonb"
    assert nullable == "NO"
    assert default is not None and "{}" in default, f"extra default is {default}"
    assert _column(admin_conn, "stg_raw", "raw_headers")[0] == "jsonb"


def test_unmapped_columns_land_in_extra_rather_than_being_lost(app_conn, sample_load_id):
    """Section 4: a new template column with no alias lands in `extra`."""
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stg_raw (load_id, source_row, raw_date, extra)
            VALUES (%s, 970001, '2026-06-01', %s::jsonb)
            RETURNING extra->>'Gloss Meter'
            """,
            (sample_load_id, '{"Gloss Meter": "88.1"}'),
        )
        assert cur.fetchone()[0] == "88.1"


def test_stg_raw_extra_defaults_to_empty_object(app_conn, sample_load_id):
    with app_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO stg_raw (load_id, source_row, raw_date) "
            "VALUES (%s, 970002, '2026-06-01') RETURNING extra",
            (sample_load_id,),
        )
        assert cur.fetchone()[0] == {}


# =====================================================================
# wavescan (section 5) -- the measurement precision change
# =====================================================================


@pytest.mark.parametrize("column", MEASURE_COLUMNS)
def test_measurement_columns_are_numeric_not_real(admin_conn, column):
    """Principle 9. REAL silently rounds an instrument reading."""
    dt, nullable, _ = _column(admin_conn, "wavescan", column)
    assert dt == "numeric", f"wavescan.{column} is {dt}, must be numeric"
    # T39 CHANGE (ADR 0013, revision 0016): only CF is NOT NULL now.
    expected_nullable = "NO" if column == "cf" else "YES"
    assert nullable == expected_nullable, f"wavescan.{column} nullability changed"


def test_no_real_or_double_columns_remain_on_wavescan(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema='public' AND table_name='wavescan'
              AND data_type IN ('real','double precision')
            """
        )
        assert cur.fetchall() == []


def test_numeric_preserves_precision_that_real_would_destroy(app_conn, sample_load_id):
    """The whole reason for the type change: a gauge value must come back
    exactly as it went in. float4 carries ~7 significant digits."""
    precise = Decimal("60.123456789012345")
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wavescan (measured_date,plant,model,checkzone,color,
                                  tolerance_group,paintline,serial_no,
                                  lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                                  load_id,source_sheet,source_row)
            VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey','Horizontal',
                    'BOOTH1','T02PREC',5,15,%s,87,14,19,25,13,13,9,0,
                    %s,'t',970100)
            RETURNING cf
            """,
            (precise, sample_load_id),
        )
        assert cur.fetchone()[0] == precise


def test_wavescan_has_supersede_and_correction_columns(admin_conn):
    assert _column(admin_conn, "wavescan", "is_superseded")[1] == "NO"
    for col in ("corrects_measurement_id", "correction_reason",
                "corrected_by", "corrected_at"):
        assert _column(admin_conn, "wavescan", col) is not None, f"missing {col}"
    assert _column(admin_conn, "wavescan", "corrected_by")[0] == "uuid"
    assert _column(admin_conn, "wavescan", "loaded_at")[0] == "timestamp with time zone"


def test_wavescan_uniqueness_is_load_scoped_not_filename_scoped(admin_conn):
    """Section 5: two plants sending June.xlsx must not collide.

    T09 CHANGE: the rule is a partial unique **index** now, not a table
    constraint, so this reads `pg_indexes` alongside `pg_constraint`. Section 5
    of the same document also describes a correction as a new row that keeps
    the original's `(load_id, source_row)`; the two sentences could not both
    hold, and PostgreSQL has no partial `UNIQUE` table constraint. Revision
    0005's docstring is the argument.

    What this test protects is unchanged and still asserted: uniqueness is
    scoped to the load, the filename is not part of it, and the pre-T02 rule is
    gone. The test below is the other half -- that the narrowing is exactly as
    wide as a correction needs and no wider.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='wavescan'::regclass AND contype='u'"
        )
        uniques = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename='wavescan' AND indexdef LIKE 'CREATE UNIQUE%'"
        )
        uniques.update({r[0]: r[1] for r in cur.fetchall()})

    joined = " ".join(uniques.values())
    assert "load_id" in joined and "source_row" in joined, \
        f"no UNIQUE (load_id, source_row); found {uniques}"
    assert "source_file" not in joined, \
        f"filename is still part of a uniqueness rule: {uniques}"
    assert "uq_ws_source" not in uniques, "the old uq_ws_source survived"


def test_a_correction_may_share_a_cell_with_the_row_it_corrects(admin_conn):
    """The narrowing T09 made, stated as a rule rather than as an index name.

    Exactly one unique rule covers `(load_id, source_row)`, and its predicate
    excludes correction rows and nothing else. Any wider a predicate would let
    two *ingest* rows claim one spreadsheet cell, which is what section 5's row
    identity exists to prevent.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='wavescan' AND indexdef LIKE 'CREATE UNIQUE%' "
            "AND indexdef LIKE '%(load_id, source_row)%'"
        )
        rules = [r[0] for r in cur.fetchall()]

    assert len(rules) == 1, f"expected one rule over the cell, found {rules}"
    assert "WHERE (corrects_measurement_id IS NULL)" in rules[0], rules[0]


def test_wavescan_source_file_column_is_gone(admin_conn):
    """It lives on load_batch; per-row duplication made June.xlsx collide."""
    assert _column(admin_conn, "wavescan", "source_file") is None


def test_same_source_row_twice_in_one_batch_is_rejected(app_conn, sample_load_id):
    with app_conn.cursor() as cur:
        stmt = """
            INSERT INTO wavescan (measured_date,plant,model,checkzone,color,
                                  tolerance_group,paintline,serial_no,
                                  lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                                  load_id,source_sheet,source_row)
            VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey','Horizontal',
                    'BOOTH1','T02DUP',5,15,60,87,14,19,25,13,13,9,0,%s,'t',970200)
        """
        cur.execute(stmt, (sample_load_id,))
        with pytest.raises(pgerr.UniqueViolation):
            cur.execute(stmt, (sample_load_id,))


def test_the_same_row_number_in_a_different_batch_is_fine(app_conn):
    """The point of load-scoped uniqueness: two plants can both send
    June.xlsx, and row 2 of each is a different measurement.

    Entirely inside the app transaction, which the fixture rolls back --
    creating the second batch on the admin connection would commit it, and
    cleaning it up afterwards would block on this transaction's FK lock.
    """
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO load_batch (source_file, source_sheet, file_hash,
                                    raw_store_key, status)
            VALUES ('June.xlsx','PasteData',%s,'raw/other','RUNNING')
            RETURNING load_id
            """,
            (uuid.uuid4().hex + uuid.uuid4().hex[:32],),
        )
        other_batch = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO wavescan (measured_date,plant,model,checkzone,color,
                                  tolerance_group,paintline,serial_no,
                                  lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                                  load_id,source_sheet,source_row)
            VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey',
                    'Horizontal','BOOTH1','T02X',5,15,60,87,14,19,25,13,13,9,0,
                    %s,'PasteData',2)
            RETURNING measurement_id
            """,
            (other_batch,),
        )
        assert cur.fetchone()[0] > 0


# =====================================================================
# Supersession: wavescan stays insert-only for the application
# =====================================================================


def test_measurement_supersession_table_exists(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
            "AND tablename='measurement_supersession'"
        )
        assert cur.fetchone()[0] == 1


def test_app_still_cannot_update_wavescan_directly(app_conn, sample_measurement_id):
    """T01's guarantee must survive T02. Adding is_superseded must NOT have
    reopened a generic UPDATE path onto the fact table."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute(
                "UPDATE wavescan SET is_superseded = true WHERE measurement_id = %s",
                (sample_measurement_id,),
            )


def test_recording_a_supersession_flips_the_flag(
    app_conn, sample_measurement_id, actor_user_id
):
    """The only supported way to retire a measurement: append a record that
    says who and why. The flag follows from it."""
    with app_conn.cursor() as cur:
        cur.execute(
            "SELECT is_superseded FROM wavescan WHERE measurement_id=%s",
            (sample_measurement_id,),
        )
        assert cur.fetchone()[0] is False

        cur.execute(
            """
            INSERT INTO measurement_supersession
                (superseded_measurement_id, reason, actor_user_id)
            VALUES (%s, 'T02 test: gauge recalibrated', %s)
            RETURNING id
            """,
            (sample_measurement_id, actor_user_id),
        )
        assert cur.fetchone()[0] > 0

        cur.execute(
            "SELECT is_superseded FROM wavescan WHERE measurement_id=%s",
            (sample_measurement_id,),
        )
        assert cur.fetchone()[0] is True, "the supersession did not take effect"


def test_supersession_requires_a_reason(app_conn, sample_measurement_id, actor_user_id):
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.NotNullViolation):
            cur.execute(
                "INSERT INTO measurement_supersession "
                "(superseded_measurement_id, reason, actor_user_id) "
                "VALUES (%s, NULL, %s)",
                (sample_measurement_id, actor_user_id),
            )


def test_a_supersession_cannot_be_withdrawn(app_conn, sample_measurement_id, actor_user_id):
    """Append-only: un-superseding would be an erase with extra steps."""
    with app_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO measurement_supersession "
            "(superseded_measurement_id, reason, actor_user_id) "
            "VALUES (%s,'T02',%s) RETURNING id",
            (sample_measurement_id, actor_user_id),
        )
        sid = cur.fetchone()[0]
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("DELETE FROM measurement_supersession WHERE id=%s", (sid,))


def test_a_measurement_is_superseded_at_most_once(app_conn, sample_measurement_id, actor_user_id):
    with app_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO measurement_supersession "
            "(superseded_measurement_id, reason, actor_user_id) "
            "VALUES (%s,'first',%s)",
            (sample_measurement_id, actor_user_id),
        )
        with pytest.raises(pgerr.UniqueViolation):
            cur.execute(
                "INSERT INTO measurement_supersession "
                "(superseded_measurement_id, reason, actor_user_id) "
                "VALUES (%s,'second',%s)",
                (sample_measurement_id, actor_user_id),
            )


def test_a_measurement_cannot_be_inserted_already_superseded(app_conn, sample_load_id):
    """The flag is only trustworthy if the side table is the ONLY way it can
    become true.

    T01 closed the UPDATE path. INSERT was still open: a row written with
    is_superseded = true is hidden by every reporting view, with nothing
    recording who hid it or why -- an erase with extra steps, which is the
    one thing this schema exists to prevent.
    """
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                """
                INSERT INTO wavescan (measured_date,plant,model,checkzone,color,
                                      tolerance_group,paintline,serial_no,
                                      lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                                      load_id,source_sheet,source_row,is_superseded)
                VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey',
                        'Horizontal','BOOTH1','T02PRESUP',5,15,60,87,14,19,25,
                        13,13,9,0,%s,'t',970300,true)
                """,
                (sample_load_id,),
            )


def test_not_even_the_owner_can_insert_a_presuperseded_measurement(admin_tx,
                                                                   sample_load_id):
    """A trigger, not a grant, so it binds the schema owner too. A future data
    migration must go through the side table like everyone else."""
    with admin_tx.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                """
                INSERT INTO wavescan (measured_date,plant,model,checkzone,color,
                                      tolerance_group,paintline,serial_no,
                                      lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                                      load_id,source_sheet,source_row,is_superseded)
                VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey',
                        'Horizontal','BOOTH1','T02PRESUPADM',5,15,60,87,14,19,25,
                        13,13,9,0,%s,'t',970301,true)
                """,
                (sample_load_id,),
            )


def test_an_ordinary_insert_is_not_slowed_or_blocked_by_the_guard(app_conn,
                                                                 sample_load_id):
    """The guard has a WHEN clause, so the normal path must be untouched."""
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO wavescan (measured_date,plant,model,checkzone,color,
                                  tolerance_group,paintline,serial_no,
                                  lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                                  load_id,source_sheet,source_row)
            VALUES (DATE '2026-06-01','AAT','U704','RRHOOD','Meteor Grey',
                    'Horizontal','BOOTH1','T02OK',5,15,60,87,14,19,25,13,13,9,0,
                    %s,'t',970302)
            RETURNING is_superseded
            """,
            (sample_load_id,),
        )
        assert cur.fetchone()[0] is False


def test_the_supersede_helper_cannot_be_called_directly(app_conn):
    """It is SECURITY DEFINER, so it must not be reachable except as the
    trigger it exists for."""
    with app_conn.cursor() as cur:
        with pytest.raises((pgerr.InsufficientPrivilege, pgerr.UndefinedFunction,
                            pgerr.FeatureNotSupported, pgerr.InvalidFunctionDefinition)):
            cur.execute("SELECT mark_measurement_superseded()")


# =====================================================================
# ref_column_alias (section 6.3)
# =====================================================================


def test_ref_column_alias_is_seeded_from_reader_header_aliases(admin_conn):
    """Section 6.3: "Seed rows from the current dict (reader.py:24-46) as
    approved."

    T08 CHANGE: this used to assert the table equals the seed exactly. That
    was true while nothing could add a row, and it is false by design now --
    `POST /api/v1/mappings/proposals/{id}/approve` writes one every time an
    Admin approves a COLUMN mapping, which is the entire point of T08. The
    old form would have started failing on the first real approval, in
    production, for a correct reason.

    The guarantee section 6.3 actually gives is that every seeded spelling is
    present, which is what is asserted now. What a *non*-seed row may look
    like is pinned by the test below rather than being left unconstrained.
    """
    expected = {
        (raw, logical)
        for logical, raws in HEADER_ALIASES.items()
        for raw in raws
    }
    with admin_conn.cursor() as cur:
        cur.execute("SELECT raw_header, logical_field FROM ref_column_alias")
        actual = set(cur.fetchall())

    assert expected <= actual, f"missing seeded alias(es): {sorted(expected - actual)}"


def _film_seed() -> tuple[tuple[str, str], ...]:
    import importlib.util
    from pathlib import Path

    # T54 CHANGE: revision 0019 seeds one more FILMTHICKNESS header (the
    # proving file's `Dk Grey Prime`), declared in the migration the same way.
    out: tuple[tuple[str, str], ...] = ()
    # T60 CHANGE: 0023 seeds the owner-named Film headers the same way.
    for name in ("0017_t46_filmthickness.py", "0019_t54_plant_film_catalogue.py",
                 "0023_t60_named_ingest_aliases.py"):
        path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / name
        spec = importlib.util.spec_from_file_location(f"seed_{name[:4]}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out += tuple(module.FILM_COLUMN_ALIASES)
    return out


def test_every_alias_beyond_the_seed_was_approved_by_somebody(admin_conn):
    """The other half of the test above.

    A row that is not part of the seed can only have come from the T08
    approve route, so it must carry the two things that route writes: an
    approver, and `is_approved`. A row with neither would mean something
    wrote this table without a decision behind it, which is what
    `AGENTS.md` rule 6 forbids.
    """
    seeded = {("WAVESCAN", raw) for raws in HEADER_ALIASES.values() for raw in raws}
    # T46 CHANGE: revision 0017 seeds the FILMTHICKNESS vocabulary the same
    # way 0002 seeded WaveScan's -- a migration, not a route -- so its rows
    # are seed too. Read from the migration itself rather than retyped.
    seeded |= {("FILMTHICKNESS", raw) for raw, _ in _film_seed()}
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT domain, raw_header, is_approved, approved_by IS NOT NULL "
            "FROM ref_column_alias"
        )
        rows = cur.fetchall()

    for domain, raw_header, is_approved, has_approver in rows:
        if (domain, raw_header) in seeded:
            continue
        assert is_approved and has_approver, (
            f"alias {raw_header!r} is in the table without an approval behind it"
        )


def test_every_seeded_alias_is_approved(admin_conn):
    """Section 6.3: seed rows from the current dict as approved.

    Unapproved rows are invisible to ingest -- `load_reference_data` reads
    `WHERE is_approved` -- so one here would be a spelling the reader silently
    ignores.
    """
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ref_column_alias WHERE NOT is_approved")
        assert cur.fetchone()[0] == 0


def test_raw_header_is_unique(app_conn):
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.UniqueViolation):
            cur.execute(
                "INSERT INTO ref_column_alias (raw_header, logical_field) "
                "VALUES ('date','plant')"
            )


def test_seeded_headers_are_normalised(admin_conn):
    """Normalisation is lower / trim / '_' -> ' ' (section 6.3)."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT raw_header FROM ref_column_alias "
            "WHERE raw_header <> lower(btrim(raw_header)) OR raw_header LIKE '%\\_%'"
        )
        assert cur.fetchall() == []


# =====================================================================
# ref_color_family / grading_family (sections 6.4, 6.5)
# Plant-scoped D2 lives on ref_plant_color. This column stays NULL.
# =====================================================================


def test_six_colour_families_in_prototype_order(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT family_name FROM ref_color_family ORDER BY display_order"
        )
        assert [r[0] for r in cur.fetchall()] == COLOR_FAMILY_ORDER


def test_display_order_is_unique(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conrelid='ref_color_family'::regclass AND contype='u'"
        )
        assert cur.fetchone()[0] >= 1


def test_grading_family_exists_and_is_entirely_unpopulated(admin_conn):
    """Plant-scoped D2 does not write ref_color.grading_family.

    04-ANALYSIS.md section 6 / ADR 0010: do not invent a global family from
    color_group. A guess here silently produces wrong PASS/FAIL grades.
    """
    assert _column(admin_conn, "ref_color", "grading_family") is not None, \
        "ref_color.grading_family is missing"

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ref_color")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ref_color WHERE grading_family IS NOT NULL")
        mapped = cur.fetchone()[0]

    assert total > 0, "ref_color is empty; the baseline did not seed colours"
    assert mapped == 0, (
        f"{mapped} of {total} colours have a grading_family. Plant-scoped D2 "
        "must not populate this column (docs/DEFERRED.md, ADR 0010) -- a "
        "wrong global family produces a wrong grade silently."
    )


def test_grading_family_references_the_family_table(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT confrelid::regclass::text FROM pg_constraint
            WHERE contype='f' AND conrelid='ref_color'::regclass
            """
        )
        assert "ref_color_family" in {r[0] for r in cur.fetchall()}


def test_an_unknown_family_cannot_be_assigned(admin_tx):
    """Even an admin cannot invent a family name by typo. Runs in a
    rolled-back transaction, so the reference table is left untouched."""
    with admin_tx.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                "UPDATE ref_color SET grading_family='Invented Family' "
                "WHERE color_name = (SELECT color_name FROM ref_color LIMIT 1)"
            )


# =====================================================================
# cf_standard (section 6.6)
# =====================================================================


def test_cf_standard_seeded_from_default_standards(admin_conn):
    """Twelve rows: six families x H/V. Values from 04-ANALYSIS.md section 3."""
    expected = set()
    for family, (ford_h, ford_v, min_h, min_v) in DEFAULT_STANDARDS.items():
        expected.add((family, "H", Decimal(ford_h), Decimal(min_h)))
        expected.add((family, "V", Decimal(ford_v), Decimal(min_v)))

    with admin_conn.cursor() as cur:
        # T76 CHANGE (ADR 0012): Admin publishes append plant / family rows
        # (append-only), so the table is no longer only the seed. The claim is
        # about the seed: version 1, unattributed, from DEFAULT_STANDARDS.
        cur.execute(
            "SELECT family_name, orient, ford, min FROM cf_standard "
            "WHERE scope='FAMILY' AND created_by IS NULL AND plant_code IS NULL "
            "AND source_note LIKE '%DEFAULT_STANDARDS%'"
        )
        actual = {(f, o, Decimal(fo), Decimal(mi)) for f, o, fo, mi in cur.fetchall()}

    assert actual == expected, (
        f"missing: {sorted(expected - actual)}\nunexpected: {sorted(actual - expected)}"
    )


def test_cf_standard_records_its_provenance(admin_conn):
    """Section 6.6: source_note from the prototype comment; source_document
    stays empty until the owner supplies the IMG Plants file (D2)."""
    # Seeded version-1 rows keep NULL source_document. Admin publishes append
    # new rows; they must not UPDATE these.
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT source_note, source_document FROM cf_standard
             WHERE source_note LIKE '%DEFAULT_STANDARDS%'
            """
        )
        rows = cur.fetchall()

    assert rows, "seed FAMILY rows disappeared"
    for note, document in rows:
        assert "IMG Plants" in note, note
        assert document is None, (
            "seed source_document was rewritten; publishes must INSERT"
        )


def test_cf_standard_scope_check_rejects_incoherent_rows(app_conn):
    """A FAMILY row with a colour, or a COLOR row with neither."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                "INSERT INTO cf_standard (scope, family_name, color_name, orient, "
                "ford, min, effective_from, source_note) "
                "VALUES ('FAMILY', NULL, NULL, 'H', 60, 50, DATE '2026-01-01', 'x')"
            )


def test_cf_standard_orientation_is_h_or_v(app_conn):
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                "INSERT INTO cf_standard (scope, family_name, orient, ford, min, "
                "effective_from, source_note) "
                "VALUES ('FAMILY','Dark Solids','X',60,50,DATE '2026-01-01','x')"
            )


def test_no_grading_thresholds_leaked_into_wavescan_constraints(admin_conn):
    """01-DATA-MODEL.md principle 2 / 04-ANALYSIS.md section 8: SQL contains
    no Ford/Min thresholds. cf_standard is the only home for them."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid='wavescan'::regclass AND contype='c'
            """
        )
        defs = cur.fetchall()

    for name, definition in defs:
        for threshold in ("57", "44", "50", "37", "67", "54", "60", "47"):
            bad = f"= {threshold}" in definition or f"> {threshold}" in definition
            assert not bad, f"{name} looks like it encodes a grading threshold: {definition}"


# =====================================================================
# proposed_mapping (section 6.7)
# =====================================================================


def test_proposed_mapping_exists_with_its_checks(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='proposed_mapping'::regclass AND contype='c'"
        )
        defs = " ".join(r[0] for r in cur.fetchall())

    for kind in ("COLUMN", "ZONE", "ALIAS_COLOR", "ALIAS_MODEL", "ALIAS_PLANT",
                 "ALIAS_CHECKZONE", "ALIAS_PAINTLINE"):
        assert kind in defs, f"proposed_mapping.kind does not allow {kind}"
    for status in ("PROPOSED", "APPROVED", "REJECTED"):
        assert status in defs, f"proposed_mapping.status does not allow {status}"


def test_a_rejected_proposal_is_kept_not_deleted(app_conn):
    """Same reason as ref_plant_zone_map: never re-propose the same wrong guess."""
    with app_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO proposed_mapping (kind, payload, status) "
            "VALUES ('COLUMN', %s::jsonb, 'REJECTED') RETURNING id",
            ('{"raw_header": "gloss meter"}',),
        )
        pid = cur.fetchone()[0]
        with pytest.raises(pgerr.InsufficientPrivilege):
            cur.execute("DELETE FROM proposed_mapping WHERE id=%s", (pid,))


# =====================================================================
# Reporting views (section 2 / section 10 active-data predicate)
# =====================================================================


def _effective_view_sql(conn, view: str) -> str:
    """A view's own definition plus those of the views it reads from.

    Section 10 asks for the predicate in ONE place, so a reporting view is
    expected to inherit it by selecting from the helper rather than to
    restate it. Following the dependency chain checks the guarantee without
    forcing the duplication it is meant to prevent.
    """
    seen: set[str] = set()
    parts: list[str] = []
    todo = [view]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", (name,))
            row = cur.fetchone()
            if row is None:
                continue
            parts.append(row[0])
            # views this one reads from
            cur.execute(
                """
                SELECT DISTINCT dependee.relname
                FROM pg_depend d
                JOIN pg_rewrite r ON r.oid = d.objid
                JOIN pg_class dependent ON dependent.oid = r.ev_class
                JOIN pg_class dependee ON dependee.oid = d.refobjid
                WHERE dependent.relname = %s
                  AND dependee.relkind = 'v'
                  AND dependee.relname <> %s
                """,
                (name, name),
            )
            todo.extend(r[0] for r in cur.fetchall())
    return "\n".join(parts)


@pytest.mark.parametrize(
    "view", ["v_wavescan", "v_wavescan_p703", "v_wavescan_u704", "v_car_completeness"]
)
def test_views_apply_the_active_data_predicate(admin_conn, view):
    """Section 10: is_duplicate = false AND is_superseded = false AND
    the batch is COMMITTED. Bypassing it is a correctness bug even when
    today's output looks right."""
    definition = _effective_view_sql(admin_conn, view)

    assert "is_duplicate" in definition, f"{view} does not filter duplicates"
    assert "is_superseded" in definition, f"{view} does not filter superseded rows"
    assert "COMMITTED" in definition, f"{view} does not require a COMMITTED batch"


def test_the_active_data_predicate_lives_in_one_place(admin_conn):
    """Section 10: 'One SQL view or repository function implements the
    predicate.' Each reporting view should inherit it, not restate it."""
    restating = []
    for view in ("v_wavescan", "v_wavescan_p703", "v_wavescan_u704",
                 "v_car_completeness"):
        with admin_conn.cursor() as cur:
            cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", (view,))
            own = cur.fetchone()[0]
        if "COMMITTED" in own and "is_superseded" in own:
            restating.append(view)

    assert restating == [], (
        f"{restating} re-implement the active-data predicate instead of reading "
        "through v_wavescan_active; two copies drift."
    )


def test_superseded_rows_disappear_from_the_reporting_view(
    app_conn, admin_conn, actor_user_id
):
    """End to end: the predicate actually removes a retired measurement."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT measurement_id, serial_no FROM wavescan w "
            "JOIN load_batch b USING (load_id) "
            "WHERE b.status='COMMITTED' AND NOT w.is_duplicate "
            "AND NOT w.is_superseded LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        pytest.skip("no committed active measurement in the fixture")
    mid, serial = row

    with app_conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM v_wavescan WHERE "Serial No" = %s', (serial,))
        before = cur.fetchone()[0]
        assert before > 0

        cur.execute(
            "INSERT INTO measurement_supersession "
            "(superseded_measurement_id, reason, actor_user_id) "
            "VALUES (%s,'T02 view test',%s)",
            (mid, actor_user_id),
        )

        cur.execute('SELECT count(*) FROM v_wavescan WHERE "Serial No" = %s', (serial,))
        assert cur.fetchone()[0] == before - 1


# =====================================================================
# Seed data and reject reasons
# =====================================================================


@pytest.mark.parametrize("plant", ["AAT", "FTM", "SAP", "FVL"])
def test_plants_are_seeded_including_deferred_ones(admin_conn, plant):
    """T02 step 6: SAP in scope, FVL present even though loads are deferred (D5)."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ref_plant WHERE plant_code=%s", (plant,))
        assert cur.fetchone()[0] == 1, f"{plant} is not seeded"


@pytest.mark.parametrize("plant", ["AAT", "FTM", "SAP"])
def test_loadable_plants_have_an_alias_to_resolve_against(admin_conn, plant):
    """An upload resolves its plant through ref_plant_alias. A plant row with
    no alias cannot be loaded even though it looks onboarded."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_plant_alias WHERE plant_code=%s", (plant,)
        )
        assert cur.fetchone()[0] >= 1, f"{plant} has no alias"


def test_fvl_does_not_require_a_serial_it_cannot_supply(admin_conn):
    """requires_serial defaults to true, which is wrong for FVL: its export
    never populates Serial No. (11_plant_zone_map.sql, measured 1504/1504 rows
    blank). Left at the default, the loader would reject every FVL row on the
    day D5 opens -- and blame the file."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT requires_serial FROM ref_plant WHERE plant_code='FVL'"
        )
        row = cur.fetchone()

    assert row is not None, "FVL is not seeded"
    assert row[0] is False, "FVL requires_serial is true; it has no serial to give"


@pytest.mark.parametrize("plant", ["AAT", "FTM", "SAP"])
def test_plants_that_do_identify_vehicles_still_require_a_serial(admin_conn, plant):
    """The FVL exemption must not have relaxed anyone else."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT requires_serial FROM ref_plant WHERE plant_code=%s", (plant,)
        )
        assert cur.fetchone()[0] is True, f"{plant} no longer requires a serial"


@pytest.mark.parametrize(
    "reason", [
        "TEMPLATE_UNKNOWN",
        "HEADER_AMBIGUOUS",
        "UNMAPPED_COLUMN",
        "COLOR_NOT_OFFERED",
        "MODEL_NOT_OFFERED",
    ]
)
def test_extended_reject_reasons_are_accepted(app_conn, sample_load_id, reason):
    """Section 7."""
    with app_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reject_log (load_id, source_file, source_sheet, source_row,
                                    reject_reason, raw_row)
            VALUES (%s,'T02','t',1,%s,'{}'::jsonb) RETURNING reject_id
            """,
            (sample_load_id, reason),
        )
        assert cur.fetchone()[0] > 0


def test_purge_function_follows_the_renamed_status(admin_conn):
    """purge_stg_raw filtered status='SUCCESS'; that status no longer exists,
    so an unmigrated function would silently purge nothing forever."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname='purge_stg_raw'"
        )
        row = cur.fetchone()

    assert row is not None, "purge_stg_raw disappeared"
    assert "COMMITTED" in row[0], "purge_stg_raw still keys on the retired status"
    assert "'SUCCESS'" not in row[0]


def test_family_codes_are_unique(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT family_code, family_name FROM ref_color_family "
            "ORDER BY display_order"
        )
        rows = cur.fetchall()
    assert [r[0] for r in rows] == ["LM", "MM", "DM", "LS", "MS", "DS"]
    assert rows[0][1] == "Light Metallics"


def test_plant_color_pk_and_offered_flag(admin_conn):
    assert _column(admin_conn, "ref_plant_color", "is_offered") is not None
    assert _column(admin_conn, "ref_plant_color", "family_name") is not None


def test_app_rw_can_insert_plant_color_but_not_delete_wavescan(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT privilege_type FROM information_schema.role_table_grants
            WHERE table_name = 'ref_plant_color' AND grantee = 'app_rw'
            ORDER BY 1
            """
        )
        plant_color = {r[0] for r in cur.fetchall()}
        cur.execute(
            """
            SELECT privilege_type FROM information_schema.role_table_grants
            WHERE table_name = 'wavescan' AND grantee = 'app_rw'
              AND privilege_type = 'DELETE'
            """
        )
        wavescan_delete = cur.fetchall()
    assert "INSERT" in plant_color
    assert "SELECT" in plant_color
    assert wavescan_delete == []
