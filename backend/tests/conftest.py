"""Shared fixtures for the T01 database security tests.

These tests talk to a *real* PostgreSQL database, because the thing under
test is a set of PostgreSQL privileges. A mock cannot fail to have a
privilege, so a mock proves nothing here.

Two connections are needed:

``T01_ADMIN_DSN``
    Owner/superuser connection. Used only to read catalogs and to build
    fixture rows. Never used to prove an application guarantee.

``T01_APP_DSN``
    The connection the *application* uses (``app_rw`` after T01, or the
    legacy ``wavescan_loader``). Every "must be refused" assertion runs
    on this connection.

Both are read from the environment, or from a gitignored ``.env.test``
next to ``pyproject.toml``. If they are missing the suite FAILS rather
than skips: a security suite that silently skips is worse than no suite,
because a green run then means nothing. See docs/reports/T01-SECURITY.md
for the local runbook.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import uuid

import pytest

from app.core.config import Settings

# Tests build their own Settings; a developer's backend/.env (for example
# AUTH_OPEN_ACCESS=true) must not leak into them.
Settings.model_config["env_file"] = None

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_TEST = BACKEND_ROOT / ".env.test"

_MISSING = (
    "{name} is not set.\n"
    "  These tests require a live PostgreSQL schema to inspect privileges on.\n"
    "  Set {name} in the environment or in {path} (gitignored).\n"
    "  Runbook: docs/reports/T01-SECURITY.md section 'Reproducing the evidence'."
)


def _load_env_test() -> None:
    """Merge .env.test into os.environ without overriding real env vars."""
    if not ENV_TEST.exists():
        return
    for line in ENV_TEST.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _dsn(name: str) -> str:
    _load_env_test()
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(_MISSING.format(name=name, path=ENV_TEST), pytrace=False)
    return value


@pytest.fixture(scope="session")
def admin_dsn() -> str:
    return _dsn("T01_ADMIN_DSN")


@pytest.fixture(scope="session")
def app_dsn() -> str:
    return _dsn("T01_APP_DSN")


@pytest.fixture(scope="session")
def admin_conn(admin_dsn: str):
    """Owner connection, autocommit. Catalog reads and fixture setup only."""
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        yield conn


@pytest.fixture()
def admin_tx(admin_dsn: str):
    """Owner connection inside a transaction that is always rolled back.

    Needed to prove ON DELETE RESTRICT bites: the *owner* is the only
    principal that could still try to delete a batch, so the FK -- not a
    grant -- has to be what stops it.
    """
    with psycopg.connect(admin_dsn) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.fixture()
def app_conn(app_dsn: str):
    """Application-role connection.

    Not autocommit, and always rolled back: no test may leave a row
    behind, and no test needs DELETE to clean up after itself (the whole
    point of T01 is that the app role has no DELETE).
    """
    with psycopg.connect(app_dsn) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.fixture(scope="session")
def app_role(admin_conn, app_dsn: str) -> str:
    """The role name the application actually authenticates as."""
    with psycopg.connect(app_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user")
            return cur.fetchone()[0]


#: Children of `load_batch`, in the order they must be deleted. Same list
#: and same reasoning as `tests/test_t04_ingest._forget_batches`; repeated
#: here rather than imported so `conftest` does not depend on a test module.
_BATCH_CHILD_TABLES = (
    "ingest_job", "stg_raw", "reject_log", "stg_review_row",
    "review_acknowledgement", "review_override", "unidentified_model",
    "proposed_mapping", "worksheet_decision", "filmthickness", "wavescan",
)


@pytest.fixture(scope="session")
def sample_batch(admin_conn) -> dict:
    """One synthetic batch and one synthetic measurement, made and removed here.

    **T85 / D-87-5.** These two ids used to be "whatever row happens to be
    first in the table". That made every test using them a hostage to the
    database's contents: they failed outright when T85 emptied it, and when
    the owner's trial refilled it they started reading *the owner's* data --
    `test_app_role_cannot_wipe_an_upload_via_the_loader_delete_sequence`
    asserted "1 staging row" and found 545 of August's.

    Nothing that uses these ids is about data. They are FK targets, for
    tests that prove privileges and constraints, so a row made here serves
    them exactly as well and serves them deterministically.

    **Invisible to every reader.** The batch is `FAILED`, and
    `v_wavescan_active` (`01-DATA-MODEL.md` section 5) requires
    `b.status = 'COMMITTED'`, so this measurement is in no view, no
    dashboard, no overview and no count. Plant, model, checkzone and colour
    are read from the live catalogue rather than typed, so the row satisfies
    `fk_ws_plant_point` and `fk_ws_zone_tol` without this file knowing any
    plant's panel names (`AGENTS.md` rule 6).
    """
    tag = f"t85-synthetic-{uuid.uuid4().hex}"
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.plant_code, p.model_code, p.zone_code, p.tolerance_group,
                   (SELECT c.color_name
                      FROM ref_plant_color c
                     WHERE c.plant_code = p.plant_code AND c.is_offered
                     ORDER BY c.color_name LIMIT 1)
              FROM ref_plant_ws_point p
             WHERE p.retired_at IS NULL
             ORDER BY p.plant_code, p.model_code, p.point_no
             LIMIT 1
            """
        )
        row = cur.fetchone()
        if row is None or row[4] is None:
            pytest.fail(
                "no live ref_plant_ws_point with an offered colour at its "
                "plant: the reference seed is incomplete, and these tests "
                "need one catalogue row to hang a synthetic fact on.",
                pytrace=False,
            )
        plant, model, zone, tolerance, colour = row

        cur.execute(
            """
            INSERT INTO load_batch
                (source_file, source_sheet, plant_code, file_hash, status,
                 rows_in_file, raw_store_key, notes)
            VALUES (%s, 'synthetic', %s, %s, 'FAILED', 1, %s, %s)
         RETURNING load_id
            """,
            (f"{tag}.xlsx", plant, uuid.uuid4().hex * 2, tag,
             "T85 synthetic FK target; owned by tests/conftest.py"),
        )
        load_id = cur.fetchone()[0]
        # The batch row now exists, so from here a failure has something to
        # leak. A fixture that raises during setup never runs its teardown
        # (the same shape as the D-87-8 residue), so this half cleans up
        # after itself and re-raises.
        try:
            cur.execute(
                """
                INSERT INTO wavescan
                    (load_id, source_sheet, source_row, measured_date, plant,
                     model, checkzone, color, tolerance_group, cf)
                VALUES (%s, 'synthetic', 1, DATE '2020-01-01', %s, %s, %s, %s,
                        %s, 1.0)
             RETURNING measurement_id
                """,
                (load_id, plant, model, zone, colour, tolerance),
            )
            measurement_id = cur.fetchone()[0]
        except Exception:
            cur.execute("DELETE FROM wavescan WHERE load_id = %s", (load_id,))
            cur.execute("DELETE FROM load_batch WHERE load_id = %s", (load_id,))
            raise

    yield {"load_id": load_id, "measurement_id": measurement_id, "plant": plant,
           "model": model, "checkzone": zone, "color": colour}

    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM measurement_supersession "
            " WHERE superseded_measurement_id IN "
            "       (SELECT measurement_id FROM wavescan WHERE load_id = %s) "
            "    OR superseded_by_measurement_id IN "
            "       (SELECT measurement_id FROM wavescan WHERE load_id = %s)",
            (load_id, load_id),
        )
        cur.execute(
            "DELETE FROM wavescan WHERE load_id = %s "
            "  AND corrects_measurement_id IS NOT NULL",
            (load_id,),
        )
        for table in _BATCH_CHILD_TABLES:
            cur.execute(f"DELETE FROM {table} WHERE load_id = %s", (load_id,))
        cur.execute("DELETE FROM load_batch WHERE load_id = %s", (load_id,))


@pytest.fixture(scope="session")
def sample_load_id(sample_batch) -> int:
    """A `load_batch.load_id` that exists, for an FK target. T85: synthetic."""
    return sample_batch["load_id"]


@pytest.fixture(scope="session")
def sample_measurement_id(sample_batch) -> int:
    """A `wavescan.measurement_id` that exists, for an FK target. T85: synthetic."""
    return sample_batch["measurement_id"]


def application_roles(conn) -> list[str]:
    """Every non-superuser login role that is not the schema owner.

    Used to assert that *no* application role -- not just the one the
    tests connect as -- holds a forbidden privilege.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rolname
            FROM pg_roles
            WHERE rolcanlogin
              AND NOT rolsuper
              AND rolname NOT LIKE 'pg\\_%'
              -- the owner (migrator) holds every privilege by owning the tables
              AND oid <> (SELECT datdba FROM pg_database WHERE datname = current_database())
            ORDER BY rolname
            """
        )
        return [r[0] for r in cur.fetchall()]


# =====================================================================
# T03 additions: the API test client needs the same database, addressed
# as a SQLAlchemy URL rather than a libpq keyword DSN.
# =====================================================================
def _keyword_dsn_to_url(dsn: str) -> str:
    """`host=h port=p dbname=d user=u` -> `postgresql+psycopg://u@h:p/d`.

    The T01/T02 harness writes keyword DSNs because psycopg reads them
    directly. SQLAlchemy needs a URL. Converting here keeps one source of
    truth in `.env.test` instead of a second variable that can drift.
    A DSN that is already a URL is passed through untouched.
    """
    if "://" in dsn:
        return dsn
    parts = dict(
        piece.split("=", 1) for piece in dsn.split() if "=" in piece
    )
    user = parts.get("user", "")
    host = parts.get("host", "127.0.0.1")
    port = parts.get("port", "5432")
    name = parts.get("dbname", "")
    password = parts.get("password", "")
    credential = user + (f":{password}" if password else "")
    return f"postgresql+psycopg://{credential}@{host}:{port}/{name}"


@pytest.fixture(scope="session")
def app_database_url(app_dsn: str) -> str:
    """The URL the API connects with: the *application* role, never the owner."""
    _load_env_test()
    explicit = os.environ.get("APP_DATABASE_URL", "").strip()
    return explicit or _keyword_dsn_to_url(app_dsn)


# =====================================================================
# T04 additions: attribution is mandatory from revision 0003 onward.
# =====================================================================
@pytest.fixture(scope="session")
def actor_user_id(admin_conn) -> str:
    """An `app_user` row every test can attribute a write to.

    `measurement_supersession.actor_user_id` is NOT NULL from revision 0003,
    which is the point of that revision: a retirement nobody can name is the
    gap T02 left open. Tests therefore need a real identity, so this creates
    one and leaves it -- there is no DELETE on `app_user` by design, because
    an identity that has attributed something has to stay resolvable.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_user (id, entra_oid, upn, display_name, last_seen_at)
            VALUES (gen_random_uuid(), 'test-suite-actor',
                    'tests@localhost', 'Automated test suite', now())
            ON CONFLICT (entra_oid) DO UPDATE SET last_seen_at = now()
            RETURNING id
            """
        )
        return str(cur.fetchone()[0])


# =====================================================================
# T76: owned-row cleanup for shared reference tables.
# =====================================================================
#: T98 (D-98-2): the moment this suite started, as the floor every
#: reference-row cleanup deletes above. `created_at >= SUITE_STARTED` can only
#: reach rows a test of this run inserted, so a row the owner taught earlier
#: at the same plant, model and spelling survives -- the exact loss T97 found
#: (one `ref_plant_zone_map` row, WEBSITE-SESSION section 6).
SUITE_STARTED = datetime.now(timezone.utc)


def row_keys(conn, table: str, key: str, where: str = "TRUE", params: tuple = ()) -> set[str]:
    """The keys of the rows that match ``where`` *now* -- taken before a test
    writes, so its cleanup can tell its own rows from shared ones.

    T76 (the T64 incident class): a cleanup that deletes by value removes a
    live row an owner created with the same value. Snapshot first, then
    `delete_rows_created_since` deletes only matching rows that were not here.
    """
    with conn.cursor() as cur:
        cur.execute(f"SELECT ({key})::text FROM {table} WHERE {where}", params)
        return {r[0] for r in cur.fetchall()}


def delete_rows_created_since(
    conn, table: str, key: str, before: set[str], where: str = "TRUE",
    params: tuple = (),
) -> int:
    """Delete rows matching ``where`` whose key was not in ``before``."""
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {table} WHERE ({where}) "
            f"AND NOT (({key})::text = ANY(%s))",
            (*params, list(before)),
        )
        return cur.rowcount


# CI has no copy of the plant data, and migrations cannot build it from an
# empty database (0025 seeds standards for colours added through the app).
# T01_DB=none leaves out every test that needs a database; the run's summary
# line reports them as "deselected", so a green run still says what it skipped.
_DB_FIXTURES = {"admin_dsn", "app_dsn"}


def pytest_collection_modifyitems(config, items):
    if os.environ.get("T01_DB") != "none":
        return
    needs = [item for item in items if _DB_FIXTURES & set(item.fixturenames)]
    if needs:
        config.hook.pytest_deselected(items=needs)
        drop = {id(item) for item in needs}
        items[:] = [item for item in items if id(item) not in drop]
