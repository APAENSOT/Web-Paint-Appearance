"""T77: the leaked `T21 ` aliases are gone and the stale test uploads are closed.

Migration 0028 deleted the 61 `(AAT, 'T21 <6 hex>') -> U704` aliases that
`test_t21_upload_review` landed once per run before T76 fixed it, and the
three `t17-*.xlsx` uploads left in review on 2026-09-28 were abandoned
through `POST /api/v1/batches/{id}/abandon`.

Everything here is read-only: the guard is exercised as a pure function, and
the live checks are SELECT / GET. No row is created or deleted, so this file
has nothing to clean up.

**T85.** Every live check below is about a specific historical row, and T85
cleared all of them by owner decision. They are not recreatable -- a
synthetic `load_id 2415` is not the upload T77 abandoned -- so each live
check now skips with that exact reason when its subject is absent and runs
unchanged when it is present (D-87-6). The pure-function guard tests are
untouched and still run everywhere.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.test_t03_contract import (  # noqa: F401
    admin_client,
    client,
    make_client,
)

REPO = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPO / "backend" / "migrations" / "versions" / "0028_t77_purge_leaked_t21_aliases.py"
)
#: The three test uploads T77 abandoned, and the three real ones it must not touch.
ABANDONED = (2415, 2416, 2417)
UNTOUCHED = {
    15237: ("09 Sep-26 P703 & J73 CF INPUT.xlsx", "SAP", "WAVESCAN"),
    15238: ("09 Sep-26 P703 & J73 CF INPUT.xlsx", "SAP", "WAVESCAN"),
    19623: ("Data Pelt U704_Sep26.xlsx", "AAT", "FILMTHICKNESS"),
}


def _migration():
    spec = importlib.util.spec_from_file_location("t77_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(**over) -> dict:
    """One `ref_model_alias` row of the shape 0028 is allowed to delete."""
    base = {
        "alias_id": 102,
        "raw_value": "T21 affa6d",
        "model_code": "U704",
        "plant_code": "AAT",
        "note": (
            "approved from mapping proposal "
            "c19e148e-9df6-4b9b-a159-a519a53ff199 for plant AAT"
        ),
    }
    base.update(over)
    return base


# ---------------------------------------------------------------- the guard
def test_the_test_residue_shape_matches():
    assert _migration().matches(row()) is True


@pytest.mark.parametrize(
    "label, over",
    [
        ("an owner's alias, not T21", {"raw_value": "P703 DBL"}),
        ("T21 prefix but not the test spelling", {"raw_value": "T21 REALALIAS"}),
        ("uppercase hex is not the spelling seen", {"raw_value": "T21 AFFA6D"}),
        ("too few hex digits", {"raw_value": "T21 affa6"}),
        ("another plant", {"plant_code": "FTM"}),
        ("a global alias", {"plant_code": None}),
        ("another model", {"model_code": "P703 DBL RANGER"}),
        ("an owner-written note", {"note": "T55 owner lock 2026-10-05"}),
        ("a note for another plant", {
            "note": "approved from mapping proposal abc for plant FTM"}),
        ("no note at all", {"note": None}),
    ],
)
def test_anything_else_is_refused(label, over):
    assert _migration().matches(row(**over)) is False, label


def test_the_migration_carries_all_61_rows_for_its_downgrade():
    module = _migration()
    assert len(module.LEAKED) == module.EXPECTED == 61
    assert len({aid for aid, _raw, _note in module.LEAKED}) == 61
    for alias_id, raw_value, note in module.LEAKED:
        assert 102 <= alias_id <= 804
        assert module.matches(
            row(alias_id=alias_id, raw_value=raw_value, note=note)
        ), raw_value


# ---------------------------------------------------------------- live state
def test_no_t21_alias_is_left(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT alias_id, raw_value FROM ref_model_alias WHERE raw_value LIKE 'T21 %'"
        )
        assert cur.fetchall() == []


def test_the_purge_removed_nothing_else(admin_conn):
    """Every surviving alias is one no T77 rule describes."""
    module = _migration()
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT alias_id, raw_value, model_code, note, plant_code FROM ref_model_alias"
        )
        rows = [
            dict(zip(("alias_id", "raw_value", "model_code", "note", "plant_code"), r))
            for r in cur.fetchall()
        ]
    assert rows, "the alias catalogue is not empty"
    assert [r for r in rows if module.matches(r)] == []


# =====================================================================
# T85: the subjects of these claims were cleared by owner decision
# =====================================================================
#: Everything below asserts something about **specific historical rows** --
#: `load_id` 2415-2417, the three real uploads 15237 / 15238 / 19623, and
#: the `audit_event` row migration 0028 wrote. All of them were in T85's
#: Clear list, and the owner approved that clear. They cannot be rebuilt:
#: a synthetic `load_id 2415` would not be the upload T77 abandoned, and an
#: invented audit row would not be the record 0028 wrote. Asserting against
#: a stand-in would be asserting against a stand-in.
#:
#: So these are the one place in this triage where the T48 pattern applies
#: (D-87-5, D-87-6): skip **only** when the subject is absent, with the
#: reason said exactly, and run the original assertion unchanged whenever it
#: is there -- against a restored backup, or another database.
T85_GONE = (
    "T85 cleared this row by owner decision (docs/reports/T85-TRIAL-DATA-RESET.md). "
    "{what} is not in this database, so there is nothing to assert about. The "
    "assertion below is unchanged and runs wherever the row still exists."
)


def _require_t77_subject(admin_conn, sql: str, params: tuple, what: str) -> None:
    """Skip, with the exact reason, when T77's subject is not here."""
    with admin_conn.cursor() as cur:
        cur.execute(sql, params)
        if cur.fetchone()[0] == 0:
            pytest.skip(T85_GONE.format(what=what))


def test_the_purge_is_audited(admin_conn):  # T85
    _require_t77_subject(
        admin_conn,
        "SELECT count(*) FROM audit_event "
        " WHERE action = 'catalogue.model_alias.purge_test_residue'",
        (),
        "migration 0028's purge audit_event row",
    )
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT actor_type, entity_type, entity_id, "
            "       jsonb_array_length(before -> 'deleted'), after ->> 'deleted_count' "
            "  FROM audit_event "
            " WHERE action = 'catalogue.model_alias.purge_test_residue' "
            " ORDER BY id DESC LIMIT 1"
        )
        found = cur.fetchone()
    assert found is not None, "the purge wrote no audit row"
    assert found == ("system", "ref_model_alias", "AAT:U704", 61, "61")


@pytest.mark.parametrize("load_id", ABANDONED)
def test_the_stale_test_uploads_are_abandoned(admin_conn, load_id):  # T85
    _require_t77_subject(
        admin_conn, "SELECT count(*) FROM load_batch WHERE load_id = %s",
        (load_id,), f"the upload T77 abandoned (load_id {load_id})",
    )
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT status, (SELECT count(*) FROM wavescan w WHERE w.load_id = b.load_id) "
            "  FROM load_batch b WHERE load_id = %s",
            (load_id,),
        )
        status, facts = cur.fetchone()
    assert status == "ABANDONED"
    assert facts == 0, "an abandoned upload never had facts"


@pytest.mark.parametrize("load_id", ABANDONED)
def test_each_abandon_is_audited(admin_conn, load_id):  # T85
    _require_t77_subject(
        admin_conn, "SELECT count(*) FROM load_batch WHERE load_id = %s",
        (load_id,), f"the upload T77 abandoned (load_id {load_id})",
    )
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_event "
            " WHERE action = 'batch.abandon' AND entity_id = %s",
            (str(load_id),),
        )
        assert cur.fetchone()[0] >= 1


def test_the_real_uploads_in_review_are_untouched(admin_conn):
    """T77 closed three test uploads and must not have touched these."""
    _require_t77_subject(  # T85
        admin_conn, "SELECT count(*) FROM load_batch WHERE load_id = ANY(%s)",
        (list(UNTOUCHED),), "the three real uploads T77 left in review",
    )
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT load_id, source_file, plant_code, domain, status "
            "  FROM load_batch WHERE load_id = ANY(%s) ORDER BY load_id",
            (list(UNTOUCHED),),
        )
        rows = cur.fetchall()
    assert len(rows) == len(UNTOUCHED)
    for load_id, source_file, plant, domain, status in rows:
        assert (source_file, plant, domain) == UNTOUCHED[load_id]
        assert status == "PENDING_REVIEW", f"upload {load_id} was changed"


def test_the_abandoned_uploads_keep_their_review_rows(admin_conn):
    """Abandon changes a status; it deletes nothing (ADR 0005)."""
    _require_t77_subject(  # T85
        admin_conn, "SELECT count(*) FROM load_batch WHERE load_id = ANY(%s)",
        (list(ABANDONED),), "the uploads T77 abandoned (load_id 2415-2417)",
    )
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT load_id, count(*) FROM stg_review_row "
            " WHERE load_id = ANY(%s) GROUP BY load_id ORDER BY load_id",
            (list(ABANDONED),),
        )
        assert cur.fetchall() == [(2415, 2), (2416, 2), (2417, 2)]
