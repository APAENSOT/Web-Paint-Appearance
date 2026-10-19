"""Cleaning rules enforced by the database, not by the loader.

A direct port of ``Paint Appearance/Component/Database/sql/99_verify.sql``
(tests 1-13) from psql NOTICEs into pytest, so the same guarantees can gate
CI (docs/03-SECURITY.md section 10: "99_verify.sql stays in CI").

Two deliberate differences from the original:

* every attempt runs as the **application role**, not as ``postgres`` --
  what matters is what the application can do;
* no test cleans up with DELETE. The original's tests 10 and 11 ended with
  ``DELETE FROM wavescan ...``; after T01 the app role has no DELETE, so
  cleanup is the transaction rollback in the ``app_conn`` fixture.

Original test numbering is kept in the docstrings so the two files can be
diffed by a reviewer.
"""

from __future__ import annotations

import pytest
from psycopg import errors as pgerr

pytestmark = pytest.mark.security

# Every valid-looking row shares this shape; only the field under test differs.
INSERT_WAVESCAN = """
    INSERT INTO wavescan (measured_date,plant,model,checkzone,color,tolerance_group,
                          paintline,serial_no,lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                          load_id,source_sheet,source_row)
    VALUES (%(measured_date)s,%(plant)s,%(model)s,%(checkzone)s,%(color)s,
            %(tolerance_group)s,%(paintline)s,%(serial_no)s,
            %(lw)s,15,60,87,14,19,25,13,13,9,%(b)s,
            %(load_id)s,'t',%(source_row)s)
"""


def _row(load_id: int, **overrides) -> dict:
    row = {
        "measured_date": "2026-06-01",
        "plant": "AAT",
        "model": "U704",
        "checkzone": "RRHOOD",
        "color": "Meteor Grey",
        "tolerance_group": "Horizontal",
        "paintline": "BOOTH1",
        "serial_no": "T01TEST",
        "lw": 5,
        "b": 0,
        "load_id": load_id,
        "source_row": 990100,
    }
    row.update(overrides)
    return row


def test_01_uncleaned_model_spelling_is_rejected(app_conn, sample_load_id):
    """99_verify #1 -- raw 'P703 DBL-RANGER' never reaches the fact table."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                INSERT_WAVESCAN,
                _row(sample_load_id, model="P703 DBL-RANGER", source_row=990101),
            )


def test_02_u704_zone_on_a_p703_pickup_is_rejected(app_conn, sample_load_id):
    """99_verify #2 -- the key protection: fk_ws_model_zone."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                INSERT_WAVESCAN,
                _row(
                    sample_load_id,
                    plant="FTM",
                    model="P703 DBL RAPTOR",
                    checkzone="LIFTGATEHILH",
                    tolerance_group="Vertical",
                    source_row=990102,
                ),
            )


def test_03_roof_recorded_as_vertical_is_rejected(app_conn, sample_load_id):
    """99_verify #3 -- fk_ws_zone_tol: LCROOF is Horizontal, always."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                INSERT_WAVESCAN,
                _row(
                    sample_load_id,
                    checkzone="LCROOF",
                    tolerance_group="Vertical",
                    source_row=990103,
                ),
            )


def test_04_uncleaned_booth_spelling_is_rejected(app_conn, sample_load_id):
    """99_verify #4 -- 'BOOTH 1' is a raw spelling, not a paintline code."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                INSERT_WAVESCAN,
                _row(sample_load_id, paintline="BOOTH 1", source_row=990104),
            )


def test_05_unknown_colour_is_rejected(app_conn, sample_load_id):
    """99_verify #5 -- the paint code must be stripped before insert."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                INSERT_WAVESCAN,
                _row(
                    sample_load_id,
                    color="3HC Traction Green",
                    source_row=990105,
                ),
            )


def test_06_same_spreadsheet_row_cannot_be_loaded_twice(app_conn, admin_conn):
    """99_verify #6 -- the same source row cannot be loaded twice.

    T02 changed the key from (source_file, source_sheet, source_row) to
    (load_id, source_row): a filename is a label, and two plants both
    sending June.xlsx must not collide (01-DATA-MODEL.md section 5). The
    guarantee under test is unchanged; the columns expressing it are.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT measured_date, plant, model, checkzone, color, tolerance_group,
                   paintline, serial_no, lw, b, load_id, source_sheet, source_row
            FROM wavescan ORDER BY measurement_id LIMIT 1
            """
        )
        existing = cur.fetchone()

    assert existing is not None, "wavescan is empty: seed demo data first"
    (measured_date, plant, model, checkzone, color, tolerance_group, paintline,
     serial_no, lw, b, load_id, source_sheet, source_row) = existing

    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.UniqueViolation):
            cur.execute(
                """
                INSERT INTO wavescan (measured_date,plant,model,checkzone,color,
                                      tolerance_group,paintline,serial_no,
                                      lw,sw,cf,doi,du,wa,wb,wc,wd,we,b,
                                      load_id,source_sheet,source_row)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,15,60,87,14,19,25,13,13,9,%s,
                        %s,%s,%s)
                """,
                (measured_date, plant, model, checkzone, color, tolerance_group,
                 paintline, serial_no, lw, b, load_id, source_sheet, source_row),
            )


def test_07_null_measurement_in_a_required_column_is_rejected(
    app_conn, sample_load_id
):
    """99_verify #7 -- the FTM R104 case.

    T39 CHANGE (ADR 0013, revision 0016): LW, SW, DOI, DU and Wa-We may be
    NULL (LW/SW only after an Engineer approves the point). CF is the one
    measure a point cannot load without, so this now proves CF.
    """
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.NotNullViolation):
            cur.execute(
                INSERT_WAVESCAN.replace("%(lw)s,15,60,", "%(lw)s,15,NULL,"),
                _row(sample_load_id, source_row=990107),
            )


def test_08_negative_gauge_reading_is_rejected(app_conn, sample_load_id):
    """99_verify #8 -- ck_ws_nonneg."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                INSERT_WAVESCAN, _row(sample_load_id, lw=-5, source_row=990108)
            )


def test_09_unknown_plant_is_rejected(app_conn, sample_load_id):
    """99_verify #9, adapted.

    The original used FVL as the out-of-scope plant and relied on FVL being
    absent from ref_plant. T02 step 6 seeds FVL (so a future alias or zone
    mapping has something to reference), so the FK no longer rejects it --
    see test_09b. The protection this test actually guards is "a plant the
    reference table has never heard of cannot reach the fact table", so it
    now uses a code that is genuinely unknown.
    """
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                INSERT_WAVESCAN, _row(sample_load_id, plant="ZZZ", source_row=990109)
            )


def test_09b_fvl_is_known_and_activation_follows_0011(admin_conn):
    """What replaced the FK for FVL: it exists. `is_active` follows 0011.

    FVL is seeded even before loads are accepted (T02 step 6). T32
    revision 0011 is the reviewed flip to true; until that revision is
    the alembic head, the flag stays false.
    """
    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        row = cur.fetchone()
        cur.execute("SELECT version_num FROM alembic_version")
        version = cur.fetchone()[0]

    assert row is not None, "FVL should be seeded (T02 step 6)"
    if version >= "0011":
        assert row[0] is True, "0011 is applied; FVL should be onboarded"
    else:
        assert row[0] is False, "FVL is active before 0011"


def test_10_null_b_is_accepted(app_conn, sample_load_id):
    """99_verify #10 -- B is absent from 481 of 2479 source rows.

    The original deleted its own row afterwards; here the fixture rolls
    the transaction back, because the app role no longer has DELETE.
    """
    with app_conn.cursor() as cur:
        cur.execute(INSERT_WAVESCAN, _row(sample_load_id, b=None, source_row=990110))
        assert cur.rowcount == 1


def test_12_approved_mapping_without_an_approver_is_rejected(app_conn):
    """99_verify #12 -- ck_pzm_approved: a proposal cannot approve itself."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.CheckViolation):
            cur.execute(
                """
                INSERT INTO ref_plant_zone_map
                    (plant_code, model_code, raw_zone_text, zone_code, confidence)
                VALUES ('FTM','P703 DBL RANGER','T01_TEST_ZONE_12','RCROOF','APPROVED')
                """
            )


def test_13_u704_zone_cannot_be_mapped_onto_a_p703_model(app_conn):
    """99_verify #13 -- the mapping table has the same protection as the
    fact table, so a bad mapping cannot be approved into existence."""
    with app_conn.cursor() as cur:
        with pytest.raises(pgerr.ForeignKeyViolation):
            cur.execute(
                """
                INSERT INTO ref_plant_zone_map
                    (plant_code, model_code, raw_zone_text, zone_code, confidence)
                VALUES ('FTM','P703 DBL RANGER','T01_TEST_ZONE_13','LIFTGATEHILH','PROPOSED')
                """
            )


def test_generated_month_and_year_always_follow_measured_date(admin_conn):
    """99_verify's GENERATED COLUMN CHECK section."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM wavescan
            WHERE month <> EXTRACT(MONTH FROM measured_date)::int
               OR year  <> EXTRACT(YEAR  FROM measured_date)::int
            """
        )
        assert cur.fetchone()[0] == 0
