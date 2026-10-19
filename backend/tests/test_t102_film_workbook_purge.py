"""T102 -- the workbook purge covers a Film workbook (migration 0034, ADR 0011).

Claims, each against the running application and the standing database:

* A committed FTM Film workbook purges through the API: 200, its
  ``load_batch``, ``filmthickness``, ``stg_*``, ``reject_log`` and
  ``worksheet_decision`` rows are gone, one ``workbook.purge`` audit row
  carries ``before.filmthickness`` equal to the facts it had, and the
  identical bytes then upload as a **new** batch (D-102-1, D-102-4).
* A WaveScan fact whose ``measurement_id`` is numerically the **same** as a
  Film fact of the purged workbook keeps its ``measurement_supersession``
  row: Film ids never reach that table (D-102-3).
* A Film correction that crosses workbooks, in either direction, makes the
  purge a 409 with nothing deleted and no audit row (D-102-2).
* Source level: the installed function deletes ``filmthickness``, does it
  after the audit row and before ``load_batch``, counts Film in ``before``,
  and its supersession DELETE still names only the WaveScan array. The 0034
  downgrade body is the one revision 0015 installs, verbatim.

Every row is made by the test that asserts on it and removed afterwards. No
shared reference or seed row is written, and the owner's data is only ever
counted, never touched (``AGENTS.md``, ``WEBSITE-SESSION.md`` section 6).
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

import pytest

from app.domain.film_catalog import FTM_RAPCAP_93
from tests.film_synthetic import film_month, forget_film_month
from tests.test_t04_ingest import _forget_batches
from tests.test_t46_filmthickness import commit, pelt, sent
from tests.test_t46_filmthickness import film_cleanup  # noqa: F401  (fixture)

pytestmark = pytest.mark.ingest

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
PLANT = "FTM"
MODEL = "P703 RAPCAP"


# Module-scoped for the same reason as T37: the T04 client fixtures are
# session-scoped, and every module that imports them keeps its apps, pools
# and worker alive until the session ends. The standing cluster allows 60
# connections, so this module releases its clients when it finishes.
@pytest.fixture(scope="module")
def ingest_apps(app_database_url: str):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.test_t04_ingest import _settings

    created = []

    def _make(**overrides):
        app = create_app(_settings(app_database_url, **overrides))
        client = TestClient(app)
        client.__enter__()
        created.append((client, app))
        return client

    yield _make
    for client, app in created:
        client.__exit__(None, None, None)
        app.state.database.dispose()


@pytest.fixture(scope="module")
def engineer(ingest_apps):
    return ingest_apps()


@pytest.fixture(scope="module")
def admin(ingest_apps):
    return ingest_apps(auth_dev_bypass_roles_raw="admin", ingest_worker_enabled=False)


# =====================================================================
# helpers
# =====================================================================
def _migration(revision: str):
    [path] = sorted(MIGRATIONS.glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"t102_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path.read_text(encoding="utf-8")


def _installed_body(source: str) -> str:
    """The plpgsql body a migration file's CREATE OR REPLACE installs."""
    return re.search(r"        AS \$fn\$\n(.*?)\n        \$fn\$\n", source, re.S).group(1)


def _prosrc(admin_conn) -> str:
    """The body of the function the database actually holds."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT prosrc FROM pg_proc WHERE proname = 'purge_workbook'")
        [(body,)] = cur.fetchall()
    return body


def _purge(client, file_hash: str, reason: str = "T102: Film workbook purge test."):
    return client.post(
        f"/api/v1/plants/{PLANT}/workbooks/{file_hash}/purge", json={"reason": reason}
    )


#: Children of `load_batch` a purged Film workbook must leave nothing in.
_FILM_CHILDREN = (
    "filmthickness", "stg_raw", "stg_review_row", "reject_log", "ingest_job",
    "unidentified_model", "review_acknowledgement", "review_override",
    "worksheet_decision",
)


def _load_ids(admin_conn, file_hash: str) -> list[int]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT load_id FROM load_batch WHERE file_hash = %s ORDER BY load_id",
            (file_hash,),
        )
        return [row[0] for row in cur.fetchall()]


def _counts(admin_conn, file_hash: str) -> dict[str, int]:
    """Rows per table for one hash. Counts only, never a thickness value."""
    ids = _load_ids(admin_conn, file_hash)
    with admin_conn.cursor() as cur:
        out = {"load_batch": len(ids)}
        for table in _FILM_CHILDREN:
            cur.execute(f"SELECT count(*) FROM {table} WHERE load_id = ANY(%s)", (ids,))
            out[table] = cur.fetchone()[0]
    return out


def _free_measurement_id(admin_conn) -> int:
    """One id free in **both** fact tables and above both sequences.

    `filmthickness.measurement_id` and `wavescan.measurement_id` are
    different sequences, so a Film id can equal a WaveScan id (T102 section
    1). To prove D-102-3 the test has to create that collision, which means
    choosing the number itself rather than letting a sequence choose.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT greatest(
                coalesce((SELECT max(measurement_id) FROM wavescan), 0),
                coalesce((SELECT max(measurement_id) FROM filmthickness), 0),
                coalesce((SELECT max(last_value) FROM pg_sequences
                           WHERE schemaname = 'public'
                             AND sequencename IN ('wavescan_measurement_id_seq',
                                                  'filmthickness_measurement_id_seq')), 0))
            """
        )
        candidate = int(cur.fetchone()[0]) + 1_000_000 + uuid.uuid4().int % 100_000
        cur.execute(
            "SELECT (SELECT count(*) FROM wavescan WHERE measurement_id = %s)"
            "     + (SELECT count(*) FROM filmthickness WHERE measurement_id = %s)",
            (candidate, candidate),
        )
        assert cur.fetchone()[0] == 0, f"{candidate} is taken in a fact table"
    return candidate


@pytest.fixture
def wavescan_marker(admin_conn, actor_user_id):
    """A WaveScan fact at a chosen `measurement_id`, with a supersession row.

    Its own FAILED batch, so `v_wavescan_active` never sees it and no
    dashboard, overview or count moves. Plant, model, zone and colour come
    from the live catalogue rather than typed (`AGENTS.md` rule 6).
    """
    made: dict = {}

    def _make(measurement_id: int) -> dict:
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.plant_code, p.model_code, p.zone_code, p.tolerance_group,
                       (SELECT c.color_name FROM ref_plant_color c
                         WHERE c.plant_code = p.plant_code AND c.is_offered
                         ORDER BY c.color_name LIMIT 1)
                  FROM ref_plant_ws_point p
                 WHERE p.retired_at IS NULL
                 ORDER BY p.plant_code, p.model_code, p.point_no LIMIT 1
                """
            )
            plant, model, zone, tolerance, colour = cur.fetchone()
            cur.execute(
                "INSERT INTO load_batch (source_file, source_sheet, plant_code, "
                "  file_hash, status, rows_in_file, raw_store_key, notes) "
                "VALUES (%s, 'synthetic', %s, %s, 'FAILED', 1, %s, %s) "
                "RETURNING load_id",
                (f"t102-wavescan-marker-{uuid.uuid4().hex[:8]}.xlsx", plant,
                 uuid.uuid4().hex * 2, "t102-marker",
                 "T102 marker; owned by tests/test_t102_film_workbook_purge.py"),
            )
            made["load_id"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO wavescan (measurement_id, load_id, source_sheet, "
                "  source_row, measured_date, plant, model, checkzone, color, "
                "  tolerance_group, cf) "
                "VALUES (%s, %s, 'synthetic', 1, DATE '2020-01-01', %s, %s, %s, "
                "        %s, %s, 1.0)",
                (measurement_id, made["load_id"], plant, model, zone, colour,
                 tolerance),
            )
            cur.execute(
                "INSERT INTO measurement_supersession (superseded_measurement_id, "
                "  reason, actor_user_id) VALUES (%s, %s, CAST(%s AS uuid)) "
                "RETURNING id",
                (measurement_id, "T102: proves a Film purge leaves this alone.",
                 actor_user_id),
            )
            made["supersession_id"] = cur.fetchone()[0]
        made["measurement_id"] = measurement_id
        return made

    yield _make

    if made:
        with admin_conn.cursor() as cur:
            _forget_batches(cur, [made["load_id"]])


@pytest.fixture
def film_batches(admin_conn):
    """Committed Film batches made directly, removed here whatever happens."""
    made: list[dict] = []

    def _make(day: str, points: list[str]) -> dict:
        batch = film_month(
            admin_conn, plant=PLANT, model=MODEL, colour="Arctic White", day=day,
            readings={code: {"CLEAR": 40.1, "ECOAT": 21.4} for code in points},
            vehicles=1,
        )
        made.append(batch)
        with admin_conn.cursor() as cur:
            cur.execute("SELECT file_hash FROM load_batch WHERE load_id = %s",
                        (batch["load_id"],))
            batch["file_hash"] = cur.fetchone()[0]
        return batch

    yield _make

    # A correction points at the row it corrects, and these tests make ones
    # that cross batches, so every correction goes before any batch does.
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM filmthickness WHERE load_id = ANY(%s) "
            "  AND corrects_measurement_id IS NOT NULL",
            ([b["load_id"] for b in made],),
        )
    for batch in made:
        forget_film_month(admin_conn, batch)


# =====================================================================
# A. the purge covers the facts (D-102-1, D-102-4)
# =====================================================================
def test_a_committed_film_workbook_purges_and_the_same_bytes_reupload(
    engineer, admin, admin_conn, film_cleanup
):
    name = f"AW_RAP_{uuid.uuid4().int % 10**7:07d}.xlsx"
    walk = list(FTM_RAPCAP_93[:3])
    data = pelt(walk, colour="Arctic White", job=name[:-5])
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    commit(engineer, admin, review)
    file_hash = review["batch"]["file_hash"]

    # RO19 (D-RO19-7): the layer diagram sheet `pelt` adds is now recorded on
    # the workbook, not as a batch of its own, so this hash has one batch. The
    # purge is still per hash, so everything it has goes (ADR 0011).
    ids = _load_ids(admin_conn, file_hash)
    before = _counts(admin_conn, file_hash)
    assert review["batch"]["load_id"] in ids
    assert before["load_batch"] == len(ids) == 1, before
    assert before["filmthickness"] == len(walk) * 4, before
    assert before["stg_raw"] > 0 and before["stg_review_row"] > 0

    response = _purge(admin, file_hash)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["load_ids"] == ids
    assert body["wavescan_deleted"] == 0, "a Film workbook has no WaveScan facts"
    assert body["batches_deleted"] == len(ids)

    after = _counts(admin_conn, file_hash)
    assert after == {k: 0 for k in after}, after

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT action, entity_id, before, after FROM audit_event WHERE id = %s",
            (body["audit_id"],),
        )
        action, entity_id, a_before, a_after = cur.fetchone()
    assert (action, entity_id) == ("workbook.purge", f"{PLANT}:{file_hash}")
    assert a_before["filmthickness"] == before["filmthickness"], \
        "the audit row is written before the deletes, so it holds the facts it had"
    assert a_before["wavescan"] == 0
    assert a_after["load_ids"] == ids

    assert _purge(admin, file_hash).status_code == 404, "the hash is gone"

    again = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    assert again["batch"]["load_id"] != review["batch"]["load_id"], \
        "a new batch, not a T25 reopen"
    assert again["batch"]["file_hash"] == file_hash


# =====================================================================
# B. Film ids never reach measurement_supersession (D-102-3)
# =====================================================================
def test_a_wavescan_supersession_sharing_a_film_id_is_untouched(
    admin, admin_conn, film_batches, wavescan_marker
):
    shared = _free_measurement_id(admin_conn)
    marker = wavescan_marker(shared)
    batch = film_batches("2026-03-04", list(FTM_RAPCAP_93[:2]))

    # The collision D-102-3 is about: one Film fact of the workbook about to
    # be purged carries the same number as the WaveScan fact above.
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO filmthickness (measurement_id, measured_date, plant, "
            "  model, color, point_code, src_location_text, layer_code, "
            "  thickness, logical_vehicle_id, load_id, source_sheet, source_row) "
            "SELECT %s, measured_date, plant, model, color, point_code, "
            "       src_location_text, 'PRIMER', thickness, logical_vehicle_id, "
            "       load_id, source_sheet, source_row "
            "  FROM filmthickness WHERE measurement_id = %s",
            (shared, batch["rows"][0]["measurement_id"]),
        )

    response = _purge(admin, batch["file_hash"])
    assert response.status_code == 200, response.text
    assert response.json()["wavescan_deleted"] == 0

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM filmthickness WHERE measurement_id = %s",
                    (shared,))
        assert cur.fetchone()[0] == 0, "the Film fact went with its workbook"
        cur.execute("SELECT count(*) FROM wavescan WHERE measurement_id = %s",
                    (shared,))
        assert cur.fetchone()[0] == 1, "the WaveScan fact is another table's row"
        cur.execute(
            "SELECT superseded_measurement_id FROM measurement_supersession "
            " WHERE id = %s",
            (marker["supersession_id"],),
        )
        assert cur.fetchone() == (shared,), \
            "a Film id must never reach measurement_supersession (D-102-3)"


# =====================================================================
# C. a Film correction across workbooks refuses (D-102-2)
# =====================================================================
def _correction(admin_conn, *, load_id: int, corrects: int, actor: str) -> None:
    """Copy one fact into `load_id` as a correction of `corrects`."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO filmthickness (measured_date, plant, model, color, "
            "  point_code, src_location_text, layer_code, thickness, "
            "  logical_vehicle_id, load_id, source_sheet, source_row, "
            "  corrects_measurement_id, correction_reason, corrected_by, "
            "  corrected_at) "
            "SELECT measured_date, plant, model, color, point_code, "
            "       src_location_text, layer_code, thickness, "
            "       logical_vehicle_id, %s, source_sheet, source_row, %s, %s, "
            "       CAST(%s AS uuid), now() "
            "  FROM filmthickness WHERE measurement_id = %s",
            (load_id, corrects, "T102: a correction across workbooks.", actor,
             corrects),
        )


def test_a_film_correction_from_another_workbook_refuses_with_nothing_deleted(
    admin, admin_conn, film_batches, actor_user_id
):
    target = film_batches("2026-03-05", list(FTM_RAPCAP_93[:2]))
    other = film_batches("2026-03-06", list(FTM_RAPCAP_93[:2]))
    _correction(admin_conn, load_id=other["load_id"],
                corrects=target["rows"][0]["measurement_id"], actor=actor_user_id)

    with admin_conn.cursor() as cur:
        cur.execute("SELECT max(id) FROM audit_event")
        audit_before = cur.fetchone()[0]

    response = _purge(admin, target["file_hash"])
    assert response.status_code == 409, response.text

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM filmthickness WHERE load_id = %s",
                    (target["load_id"],))
        assert cur.fetchone()[0] == len(target["rows"]), "nothing was deleted"
        cur.execute("SELECT count(*) FROM load_batch WHERE load_id = %s",
                    (target["load_id"],))
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT count(*) FROM audit_event "
            " WHERE id > %s AND action = 'workbook.purge'",
            (audit_before,),
        )
        assert cur.fetchone()[0] == 0, "a refused purge leaves no audit row"


def test_a_film_correction_pointing_out_of_the_workbook_also_refuses(
    admin, admin_conn, film_batches, actor_user_id
):
    """The reverse direction of D-102-2: the correction is inside, its target out."""
    target = film_batches("2026-03-07", list(FTM_RAPCAP_93[:2]))
    other = film_batches("2026-03-08", list(FTM_RAPCAP_93[:2]))
    _correction(admin_conn, load_id=target["load_id"],
                corrects=other["rows"][0]["measurement_id"], actor=actor_user_id)

    response = _purge(admin, target["file_hash"])
    assert response.status_code == 409, response.text
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM load_batch WHERE load_id = %s",
                    (target["load_id"],))
        assert cur.fetchone()[0] == 1, "nothing was deleted"


# =====================================================================
# D. the installed function and the downgrade body (source level)
# =====================================================================
def test_the_installed_function_deletes_film_facts_in_the_locked_order(admin_conn):
    body = _prosrc(admin_conn)
    film_delete = "DELETE FROM filmthickness WHERE load_id = ANY(v_ids)"
    assert film_delete in body
    audit = body.index("INSERT INTO audit_event")
    film = body.index(film_delete)
    batches = body.index("DELETE FROM load_batch WHERE load_id = ANY(v_ids)")
    assert audit < film < batches, "D-102-1: after the audit row, before load_batch"


def test_the_supersession_delete_still_names_only_the_wavescan_array(admin_conn):
    body = _prosrc(admin_conn)
    [statement] = re.findall(r"DELETE FROM measurement_supersession.*?;", body, re.S)
    assert "v_meas" in statement
    assert "v_film" not in statement, \
        "D-102-3: a Film id must never reach measurement_supersession"


def test_the_audit_row_counts_film_before_the_deletes(admin_conn):
    body = _prosrc(admin_conn)
    before_block = body[body.index("v_before := jsonb_build_object"):
                        body.index("INSERT INTO audit_event")]
    assert "'filmthickness', cardinality(v_film)" in before_block


def test_the_0034_downgrade_restores_the_0015_body_verbatim():
    module, _ = _migration("0034")
    _, source_0015 = _migration("0015")
    assert module.PURGE_BODY_0016 == _installed_body(source_0015), \
        "downgrade must restore the body 0015 installed, verbatim"
    assert "filmthickness" not in module.PURGE_BODY_0016, \
        "the old body is exactly the one that never deleted a Film fact"
    assert "DELETE FROM filmthickness" in module.PURGE_BODY_0034
