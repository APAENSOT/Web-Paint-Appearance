"""T109 -- Point Check, phase 1 (Film), against revision 0035.

Claims (task section 4), against the real uploader, the running application
and the live database:

1. **The migration.** Exactly the 8 rows the owner named carry the extra tag
   and nothing else platform-wide; `app_rw` may UPDATE exactly
   ``retired_at`` + ``retired_reason`` of `ref_plant_film_point` and nothing
   else, and holds DELETE on none of the Film tables (D-109-9); the alias
   store exists with its partial unique index on **live** rows; and the 118
   retired FTM `ref_film_location_map` rows are all still there, all still
   retired, field for field the same before and after this module runs
   (D-109-8).
2. **Add a point** (D-109-5): the list grows by one at the number the name
   carries, tagged extra, with one `film_point_setting` row and an
   `audit_event`; a number a live point already holds is refused 409; a name
   the list already carries is refused 409; a name with no leading number is
   refused 422; a panel word the list has never seen is refused 422 until
   H/V is chosen; a Viewer is refused 403.
3. **Retire a point** (D-109-4, sections 3.1-3.4): it leaves the live list
   and joins `retired_items` with its reason; a car measured before the
   retire keeps its reading in History **tagged retired**; that reading stops
   feeding the dashboard; the car does **not** become incomplete; and the
   next upload that writes the label is asked about in its row while every
   other row still loads.
4. **The alias** (D-109-6, D-109-8): the row answer writes one
   `ref_film_point_alias` row, a `worksheet_decision` and an `audit_event`,
   and the tab is replayed so the rows load; a later upload resolves the
   label without asking; only an asked label and a live point are accepted;
   and a label that is the key of one of the 118 retired rows gets a **live**
   alias beside it without touching it.
5. **The walk guard on resolved names** (section 3.5): known names out of
   order still hold the whole sheet (D-99-7, unchanged), and a label an alias
   resolves is that point in the guard's eyes.
6. **The in-review appended confirm** (D-99-14, D-109-7) now tags the point
   it adds as extra.
7. **Point Check's read** (section 3.7): walk order, counted, H/V, stop,
   extra, retired, last change, and a model list that counts live points.
8. **Other plants** (section 3.9): AAT has no setting, so its list is
   read-only and the writes are refused.

**What this file writes, and how it cleans up.** Every upload goes through
`film_cleanup` (batches and facts by `load_id`). Every point this module adds
is one of its own marker names, removed by name at the end together with its
settings; every alias row it writes is removed by id. No seeded FTM row is
added, retired, aliased or deleted, and `test_reference_counts_are_flat`
asserts the watched tables are exactly as they were on the way in.
"""

from __future__ import annotations

import uuid

from tests.ro19_synthetic import ro19_plants  # noqa: F401

import re

import pytest

from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import (
    commit,
    film_cleanup,  # noqa: F401
    film_facts,
    pelt,
    sent,
    wait_for,
)
from tests.test_t99_film_point_lists import (
    COLOUR,
    PLANT,
    RANGER,
    RAPCAP,
    RAPTOR,
    SGL,
    TAIL,
    details,
    job_name,
    rows_by_label,
    walk_of,
    ws,
)

pytestmark = pytest.mark.ingest

#: D-109-3, owner 2026-10-10: the 8 rows the seed tags, and no others.
EXTRA_POINTS = ("095RBXFLOOR", "096TGATEIN", "097TGATEIN", "098TGATEIN")
EXTRA_MODELS = (RANGER, RAPTOR)
EXTRA_ROWS = len(EXTRA_POINTS) * len(EXTRA_MODELS)

#: The retired FTM rows of the **old** map. They are the record for the facts
#: that were mapped through them and must never be written (ADR 0005).
RETIRED_ALIAS_ROWS = 118

#: D-109-9: the only two columns the application may ever UPDATE.
RETIRE_COLUMNS = ["retired_at", "retired_reason"]

#: The marker name this module adds and removes. `099...` is past the end of
#: every FTM list, so adding it moves nothing already on a walk.
MARKER = "099T109MARK"

WATCHED = (
    "ref_plant_film_point", "film_point_setting", "ref_film_point",
    "ref_film_point_alias", "ref_film_location_map",
)


# =====================================================================
# helpers
# =====================================================================
def alias_checksum(admin_conn) -> tuple[int, str]:
    """The 118 retired FTM rows of the old map, as one count and one hash.

    Every column, in key order, so an UPDATE of any field would change the
    hash even where the row count did not.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*),
                   coalesce(md5(string_agg(line, E'\\n' ORDER BY line)), '')
              FROM (SELECT concat_ws('|', plant_code, model_code,
                                     raw_location_norm, point_code,
                                     raw_position, proof_hash, verified_by,
                                     approved_at, note, created_at,
                                     retired_at, retired_reason) AS line
                      FROM ref_film_location_map
                     WHERE plant_code = %s) x
            """,
            (PLANT,),
        )
        row = cur.fetchone()
    return int(row[0]), str(row[1])


def table_counts(admin_conn) -> dict[str, int]:
    out: dict[str, int] = {}
    with admin_conn.cursor() as cur:
        for table in WATCHED:
            cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed list
            out[table] = cur.fetchone()[0]
    return out


def point_list(client, model: str) -> dict:
    response = client.get(f"/api/v1/plants/{PLANT}/film-points/{model}")
    assert response.status_code == 200, response.text
    return response.json()


def live_codes(client, model: str) -> list[str]:
    return [item["point_code"] for item in point_list(client, model)["items"]]


def add_point(client, model: str, code: str, **body):
    return client.post(
        f"/api/v1/plants/{PLANT}/film-points/{model}/add",
        json={"point_code": code, "reason": "T109 test marker", **body},
    )


def retire(client, model: str, code: str, why: str = "T109 test marker"):
    return client.post(
        f"/api/v1/plants/{PLANT}/film-points/{model}/retire",
        json={"point_code": code, "reason": why},
    )


def grid_of(client, vehicle_id: str) -> dict:
    response = client.get(
        f"/api/v1/plants/{PLANT}/filmthickness/vehicles/{vehicle_id}/points"
    )
    assert response.status_code == 200, response.text
    return response.json()


def overview_readings(client, month: str) -> int:
    """Every reading the dashboard counts for one month, as one number.

    `n` is the box's own count of readings, so this is the server's number
    and not a re-derivation of it.
    """
    response = client.get(
        f"/api/v1/plants/{PLANT}/filmthickness/overview", params={"month": month}
    )
    assert response.status_code == 200, response.text
    return sum(box["n"] for box in response.json()["boxes"])


def worksheet_of(client, file_hash: str) -> dict:
    response = client.get(
        f"/api/v1/plants/{PLANT}/workbooks/{file_hash}/worksheet"
    )
    assert response.status_code == 200, response.text
    return response.json()["sheets"][0]


def month_of(admin_conn, load_id: int) -> str:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT to_char(measured_date, 'YYYY-MM') FROM filmthickness "
            " WHERE load_id = %s LIMIT 1",
            (load_id,),
        )
        return cur.fetchone()[0]


def audit_count(admin_conn, action: str, entity_id: str) -> int:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_event WHERE action = %s AND entity_id = %s",
            (action, entity_id),
        )
        return int(cur.fetchone()[0])


def alias_ids(admin_conn, raw: str) -> list[int]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT alias_id FROM ref_film_point_alias WHERE plant_code = %s "
            "  AND raw_location_norm = %s",
            (PLANT, raw),
        )
        return [r[0] for r in cur.fetchall()]


# =====================================================================
# fixtures
# =====================================================================
@pytest.fixture(scope="module")
def reference_before(admin_conn) -> dict[str, int]:
    return table_counts(admin_conn)


@pytest.fixture(scope="module")
def alias_before(admin_conn) -> tuple[int, str]:
    return alias_checksum(admin_conn)


@pytest.fixture()
def marker_cleanup(admin_conn):
    """Remove the marker point and anything written about it, by name.

    The application never deletes one of these (ADR 0005); a test does, so
    the owner's seeded rows are the only Film reference rows left behind.
    """
    # Every marker test uses SGL. Save the exact pre-test versions so the
    # fixture cannot remove a seed or another session's earlier version.
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_id FROM point_walk_version WHERE plant_code = %s "
                    "AND model_code = %s AND domain = 'FILMTHICKNESS'", (PLANT, SGL))
        versions_before = [row[0] for row in cur.fetchall()]
    yield MARKER
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT v.version_id FROM point_walk_version v WHERE v.plant_code = %s "
            "AND v.model_code = %s AND v.domain = 'FILMTHICKNESS' "
            "AND NOT (v.version_id = ANY(%s)) AND (v.reason ILIKE %s OR EXISTS "
            "(SELECT 1 FROM point_walk_member m WHERE m.version_id = v.version_id "
            "AND m.point_code = %s))",
            (PLANT, SGL, versions_before, "%T109 test%", MARKER),
        )
        own_versions = [row[0] for row in cur.fetchall()]
        if own_versions:
            cur.execute("DELETE FROM audit_event WHERE entity_type = 'point_walk_version' "
                        "AND entity_id = ANY(%s)", ([str(v) for v in own_versions],))
            cur.execute("DELETE FROM point_walk_member WHERE version_id = ANY(%s)", (own_versions,))
            cur.execute("DELETE FROM point_walk_version WHERE version_id = ANY(%s)", (own_versions,))
        cur.execute(
            "DELETE FROM ref_film_point_alias WHERE plant_code = %s "
            "  AND (point_code = %s OR raw_location_norm = %s)",
            (PLANT, MARKER, MARKER),
        )
        cur.execute(
            "DELETE FROM film_point_setting WHERE plant_code = %s "
            "  AND point_code = %s",
            (PLANT, MARKER),
        )
        # RO17: an add writes the point's first label row (FK to the point).
        cur.execute(
            "DELETE FROM ref_plant_film_point_label WHERE plant_code = %s "
            "  AND point_code = %s",
            (PLANT, MARKER),
        )
        cur.execute(
            "DELETE FROM ref_plant_film_point WHERE plant_code = %s "
            "  AND point_code = %s",
            (PLANT, MARKER),
        )
        cur.execute("DELETE FROM ref_film_point WHERE point_code = %s", (MARKER,))


@pytest.fixture()
def alias_cleanup(admin_conn):
    """Remove the alias rows a test wrote, by id -- the tightest scope there
    is (T95 / D-95-5)."""
    seen: list[int] = []
    yield seen
    if not seen:
        return
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ref_film_point_alias WHERE alias_id = ANY(%s)", (seen,)
        )


# =====================================================================
# 1. the migration (revision 0035)
# =====================================================================
def test_exactly_the_rows_the_owner_named_are_extra(
    admin_conn, reference_before, alias_before
):
    """The migration's eight FTM rows, plus the one extra point the owner
    added through Point Check since: SAP J73 ``061TGATE`` (RO19 D-RO19-5,
    2026-10-19, docs/reports/RO19-WALK-ORDER-AND-ROLLOUT-FIXES.md §5.2)."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code, point_code, retired_at "
            "  FROM ref_plant_film_point WHERE is_extra ORDER BY 1, 2, 3"
        )
        tagged = cur.fetchall()
    seeded = [row for row in tagged if row[0] == PLANT]
    assert len(seeded) == EXTRA_ROWS
    assert {row[1] for row in seeded} == set(EXTRA_MODELS)
    assert {row[2] for row in seeded} == set(EXTRA_POINTS)
    assert [row[:3] for row in tagged if row[0] != PLANT] == [
        ("SAP", "J73 DBL", "061TGATE"),
    ], "platform-wide, not just at FTM"
    assert all(row[3] is None for row in tagged), "the seed tagged live rows"


def test_the_grants_are_exactly_what_a_retire_needs(admin_conn):
    """D-109-9, read off the catalog rather than off the migration's code."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.column_privileges "
            " WHERE table_name = 'ref_plant_film_point' AND grantee = 'app_rw' "
            "   AND privilege_type = 'UPDATE' ORDER BY 1"
        )
        assert [r[0] for r in cur.fetchall()] == RETIRE_COLUMNS
        cur.execute(
            "SELECT table_name, privilege_type FROM information_schema.table_privileges "
            " WHERE grantee = 'app_rw' AND table_name IN "
            "       ('ref_plant_film_point', 'ref_film_point_alias', "
            "        'ref_film_location_map', 'film_point_setting') "
            " ORDER BY 1, 2"
        )
        held: dict[str, set[str]] = {}
        for table, privilege in cur.fetchall():
            held.setdefault(table, set()).add(privilege)
    assert held["ref_film_point_alias"] == {"SELECT", "INSERT"}
    assert held["ref_film_location_map"] == {"SELECT"}, "read-only, for ever"
    assert held["film_point_setting"] == {"SELECT", "INSERT"}
    # UPDATE is column-scoped, so it is not a table privilege here.
    assert held["ref_plant_film_point"] == {"SELECT", "INSERT"}
    assert not any("DELETE" in privileges for privileges in held.values())


def test_the_alias_store_allows_one_live_row_beside_any_retired_ones(admin_conn):
    """D-109-8: the partial unique index is the whole reason it exists."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            " WHERE tablename = 'ref_film_point_alias' "
            "   AND indexname = 'uq_film_point_alias_live'"
        )
        rows = cur.fetchall()
    assert len(rows) == 1, "the index exists"
    definition = rows[0][0]
    assert "UNIQUE" in definition
    assert "plant_code, model_code, raw_location_norm" in definition
    assert "retired_at IS NULL" in definition, "live rows only"


def test_the_hundred_and_eighteen_retired_map_rows_are_untouched(
    admin_conn, alias_before
):
    rows, digest = alias_checksum(admin_conn)
    assert rows == RETIRED_ALIAS_ROWS
    assert (rows, digest) == alias_before, "not one field moved"
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_film_location_map "
            " WHERE plant_code = %s AND retired_at IS NULL",
            (PLANT,),
        )
        assert cur.fetchone()[0] == 0, "all 118 are retired (T54)"


# =====================================================================
# 2. add a point (D-109-5)
# =====================================================================
def test_a_point_is_added_at_the_number_its_name_carries_and_is_extra(
    engineer, admin_conn, marker_cleanup
):
    before = live_codes(engineer, SGL)
    assert MARKER not in before
    # `audit_event` is never deleted (ADR 0005), so an earlier run of this
    # test is still on the record. The claim is "this add wrote one", which
    # is the delta.
    audited_before = audit_count(admin_conn, "catalogue.plant_film_point.add",
                                 f"{PLANT}:{SGL}:{MARKER}")
    added = add_point(engineer, SGL, MARKER, orientation="H", counted=True)
    assert added.status_code == 200, added.text
    body = added.json()
    assert (body["point_code"], body["point_no"]) == (MARKER, 99)
    assert "extra point" in body["operator_message"]

    after = point_list(engineer, SGL)
    mine = [item for item in after["items"] if item["point_code"] == MARKER]
    assert len(mine) == 1, "once, at the end of the walk"
    [point] = mine
    assert point["point_no"] == 99
    assert point["is_extra"] is True, "D-109-3: every point added now is extra"
    assert point["counted"] is True and point["orientation"] == "H"
    assert point["reason"] == "T109 test marker", "the person's own words"
    assert [item["point_code"] for item in after["items"]][:-1] == before, (
        "nothing already on the list moved"
    )

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT counted, orientation FROM film_point_setting "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, SGL, MARKER),
        )
        assert cur.fetchall() == [(True, "H")], "one setting row, no UPDATE"
    assert audit_count(
        admin_conn, "catalogue.plant_film_point.add", f"{PLANT}:{SGL}:{MARKER}"
    ) == audited_before + 1


def test_a_taken_name_number_gets_the_next_free_number_and_requested_place(engineer, admin_conn, ro19_plants):
    """RO19: point identity, allocation and measuring position are independent."""
    plant = ro19_plants(ruled=True)
    code = "001ZR19" + uuid.uuid4().hex[:8].upper()
    ro19_plants.track_code(code)
    response = engineer.post(f"/api/v1/plants/{plant}/film-points/{RANGER}/add", json={
        "point_code": code, "orientation": "V", "counted": False,
        "place_after": "001HOOD", "reason": "RO19 synthetic collision proof",
    })
    assert response.status_code == 200, response.text
    assert (response.json()["point_code"], response.json()["point_no"]) == (code, 4)
    read = engineer.get(f"/api/v1/plants/{plant}/film-points/{RANGER}")
    assert read.status_code == 200, read.text
    assert [p["point_code"] for p in read.json()["items"]] == [
        "001HOOD", code, "002HOOD", "003HOOD",
    ]
    with admin_conn.cursor() as cur:
        cur.execute("SELECT point_code, point_no FROM ref_plant_film_point "
                    "WHERE plant_code = %s AND point_code <> %s ORDER BY point_no", (plant, code))
        assert cur.fetchall() == [("001HOOD", 1), ("002HOOD", 2), ("003HOOD", 3)]
        cur.execute("SELECT counted, btrim(orientation) FROM film_point_setting "
                    "WHERE plant_code = %s AND point_code = %s", (plant, code))
        assert cur.fetchall() == [(False, "V")]


def test_a_name_the_list_already_carries_is_refused(engineer, admin_conn):
    walk = walk_of(admin_conn, SGL)
    refused = add_point(engineer, SGL, walk[1], orientation="V")
    assert refused.status_code == 409, refused.text
    assert "already on" in refused.json()["message"]


def test_a_name_with_no_number_is_refused(engineer):
    refused = add_point(engineer, SGL, "TGATEIN", orientation="V")
    assert refused.status_code == 422, refused.text
    assert "number and its name" in refused.json()["message"]


def test_a_word_the_list_has_never_seen_asks_for_h_or_v(engineer, marker_cleanup):
    """D-109-5: pre-filled from the list's own points, else the person picks."""
    refused = add_point(engineer, SGL, MARKER)
    assert refused.status_code == 422, refused.text
    message = refused.json()["message"]
    assert "Horizontal or Vertical" in message
    assert "nobody can propose one for you" in message
    assert MARKER not in live_codes(engineer, SGL), "nothing was changed"
    chosen = add_point(engineer, SGL, MARKER, orientation="V")
    assert chosen.status_code == 200, chosen.text


def test_a_viewer_cannot_add_or_retire(viewer, admin_conn):
    assert add_point(viewer, SGL, MARKER, orientation="V").status_code == 403
    assert retire(viewer, SGL, walk_of(admin_conn, SGL)[0]).status_code == 403


# =====================================================================
# 3. retire a point (D-109-4, sections 3.1-3.4)
# =====================================================================
def test_a_retire_keeps_the_reading_drops_the_box_and_keeps_the_car_complete(
    engineer, admin, viewer, admin_conn, marker_cleanup, film_cleanup  # noqa: F811
):
    """The whole of D-109-4, on a car measured **before** the retire.

    The marker point is added first, so the car's sheet walks a list that
    holds it and nothing is confirmed or guessed. Then it is retired, and
    every read section 3 names is asked again.
    """
    added = add_point(engineer, SGL, MARKER, orientation="H")
    assert added.status_code == 200, added.text
    walk = walk_of(admin_conn, SGL)
    assert walk[-1] == MARKER

    name, job = job_name("SGL")
    data = pelt([*walk, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    assert review["batch"]["counts"]["rows_loaded"] == len(walk)
    commit(engineer, admin, review)
    [vehicle_id] = {fact[6] for fact in film_facts(admin_conn, load_id)}
    month = month_of(admin_conn, load_id)

    before_grid = grid_of(viewer, vehicle_id)
    assert before_grid["vehicle"]["incomplete"] is False
    assert before_grid["vehicle"]["expected_point_count"] == len(walk)
    assert before_grid["vehicle"]["mapped_point_count"] == len(walk)
    marker_row = next(
        item for item in before_grid["items"] if item["point_code"] == MARKER
    )
    assert marker_row["retired"] is False and marker_row["is_extra"] is True
    kept = dict(marker_row["layers"])
    assert all(value is not None for value in kept.values()), "four layers measured"
    readings_before = overview_readings(viewer, month)

    gone = retire(engineer, SGL, MARKER, why="the plant stopped measuring it")
    assert gone.status_code == 200, gone.text
    message = gone.json()["operator_message"]
    assert "every month" in message and "stay in History" in message
    assert "no car becomes incomplete" in message

    # 3.7: off the live list, on the retired one, with the reason.
    after = point_list(engineer, SGL)
    assert MARKER not in [item["point_code"] for item in after["items"]]
    [retired_row] = [
        item for item in after["retired_items"] if item["point_code"] == MARKER
    ]
    assert "the plant stopped measuring it" in retired_row["retired_reason"]
    assert retired_row["is_extra"] is True and retired_row["point_no"] == 99

    # 3.2: the reading is still in History, tagged, with its four layers.
    after_grid = grid_of(viewer, vehicle_id)
    [still] = [item for item in after_grid["items"] if item["point_code"] == MARKER]
    assert still["retired"] is True, "D-109-4: kept and marked"
    assert still["layers"] == kept, "not one number changed"

    # 3.3: the car did not change, so it is still complete.
    assert after_grid["vehicle"]["expected_point_count"] == len(walk) - 1
    assert after_grid["vehicle"]["mapped_point_count"] == len(walk) - 1
    assert after_grid["vehicle"]["incomplete"] is False, (
        "a retirement must never turn an old car incomplete"
    )

    # 3.1: it feeds no box, for this month or any other.
    assert overview_readings(viewer, month) == readings_before - len(kept)

    # 3.5: the next upload that writes the label is asked about in its row.
    # T109-FIX CHANGE (D-109F-1): and nothing of that sheet loads until it is
    # answered -- the question is the row's, the hold is the sheet's.
    live = walk_of(admin_conn, SGL)
    # The label sits **inside** the file, with live names after it, which is
    # what makes it a row question rather than D-99-14's appended confirm:
    # the guard reads file order, and every FTM list is numbered without a
    # gap, so a retired point's label is only ever "appended" when the file
    # writes it last.
    name2, job2 = job_name("SGL")
    data2 = pelt([*live[:29], MARKER, *live[29:], *TAIL], colour=COLOUR, job=job2)
    second = sent(
        engineer, film_cleanup, admin_conn, name2, data2, PLANT
    )["Quick Summary"]
    # T109-FIX CHANGE (D-109F-1): was `== len(live)`.
    assert second["batch"]["counts"]["rows_loaded"] == 0, (
        "nothing loads while the label is unanswered"
    )
    held = {
        label
        for label, (disposition, reason) in rows_by_label(
            admin_conn, second["batch"]["load_id"]
        ).items()
        if disposition == "QUARANTINE" and reason == "FILM_POINT_UNKNOWN"
    }
    assert held == {MARKER}, "one row question, and only one"
    [detail] = details(admin_conn, second["batch"]["load_id"], "FILM_POINT_UNKNOWN")
    assert MARKER in detail and "Point Check" in detail
    # T109-FIX CHANGE (D-109F-1): was "the rest of the sheet loads".
    assert "Nothing on this sheet loads until every label" in detail

    sheet = worksheet_of(engineer, second["batch"]["file_hash"])
    assert [item["raw_location"] for item in sheet["film_unknown_labels"]] == [MARKER]
    assert sheet["film_unknown_labels"][0]["rows"] == 1
    offered = {item["point_code"] for item in sheet["film_point_choices"]}
    assert offered == set(live), "live points of the model, and only those"
    assert MARKER not in offered, "a retired point is never offered"
    assert [
        row["outcome"] for row in sheet["rows"] if row["panel_label"] == MARKER
    ] == ["needs_confirmation"], "asked in the row, not held out"


def test_a_retire_is_once_only_and_a_live_point_is_needed(
    engineer, admin_conn, marker_cleanup
):
    assert add_point(engineer, SGL, MARKER, orientation="H").status_code == 200
    assert retire(engineer, SGL, MARKER).status_code == 200
    again = retire(engineer, SGL, MARKER)
    assert again.status_code == 409, again.text
    assert "not a live point" in again.json()["message"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_reason FROM ref_plant_film_point "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, SGL, MARKER),
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0].endswith("T109 test marker"), "the first reason stands"


# =====================================================================
# 4. the alias (D-109-6, D-109-8)
# =====================================================================
def test_the_row_answer_writes_one_alias_and_the_rows_load(
    engineer, admin_conn, alias_cleanup, film_cleanup  # noqa: F811
):
    """D-109-6: pick a live point, and every later upload resolves it."""
    walk = walk_of(admin_conn, SGL)
    label = "030T109SPELL"
    target = walk[29]
    body = [*walk[:29], label, *walk[30:]]
    name, job = job_name("SGL")
    data = pelt([*body, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    # T109-FIX CHANGE (D-109F-1): was `== len(walk) - 1`. Nothing of the
    # sheet loads **before** the answer; the answer is what makes it load.
    assert review["batch"]["counts"]["rows_loaded"] == 0

    answered = engineer.post(
        ws(PLANT, file_hash, "film-point-answer"),
        json={"load_id": load_id, "raw_location": label, "point_code": target},
    )
    assert answered.status_code == 200, answered.text
    alias_cleanup.extend(alias_ids(admin_conn, label))
    assert answered.json()["decisions_written"] == 1
    assert f"{label} is {target}" in answered.json()["operator_message"]
    wait_for(engineer, load_id)

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT point_code, model_code, retired_at FROM ref_film_point_alias "
            " WHERE plant_code = %s AND raw_location_norm = %s",
            (PLANT, label),
        )
        assert cur.fetchall() == [(target, SGL, None)], "one live alias row"
        cur.execute(
            "SELECT kind, subject FROM worksheet_decision WHERE load_id = %s",
            (load_id,),
        )
        assert ("FILM_POINT_ALIAS", f"{label}=>{target}") in cur.fetchall()
    assert audit_count(
        admin_conn, "catalogue.film_point_alias.answer", f"{PLANT}:{SGL}:{label}"
    ) >= 1

    after = worksheet_of(engineer, file_hash)
    assert after["film_unknown_labels"] == [], "it stops asking"
    # T109-FIX (D-109F-1): answered, so the whole sheet loads now.
    assert after["state"] == "ready" and after["rows_ready"] == len(walk)
    assert [
        row["checkzone"] for row in after["rows"] if row["panel_label"] == label
    ] == [target], "the row resolved to the point the person named"

    # The next upload of the same plant x model never asks again.
    name2, job2 = job_name("SGL")
    data2 = pelt([*body, *TAIL], colour=COLOUR, job=job2)
    second = sent(
        engineer, film_cleanup, admin_conn, name2, data2, PLANT
    )["Quick Summary"]
    assert second["batch"]["counts"]["rows_loaded"] == len(walk)
    repeat = worksheet_of(engineer, second["batch"]["file_hash"])
    assert repeat["film_unknown_labels"] == [], "it never asks again"
    assert [
        row["checkzone"] for row in repeat["rows"] if row["panel_label"] == label
    ] == [target], "resolved by the remembered alias, with nobody asked"


def test_an_answer_may_only_name_an_asked_label_and_a_live_point(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, SGL)
    label = "030T109OTHER"
    name, job = job_name("SGL")
    data = pelt([*walk[:29], label, *walk[30:], *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]

    stranger = engineer.post(
        ws(PLANT, file_hash, "film-point-answer"),
        json={"load_id": load_id, "raw_location": "058T109NOTASKED",
              "point_code": walk[0]},
    )
    assert stranger.status_code == 409, stranger.text
    assert "is not a label" in stranger.json()["message"]

    minted = engineer.post(
        ws(PLANT, file_hash, "film-point-answer"),
        json={"load_id": load_id, "raw_location": label,
              "point_code": "099T109NOTONTHELIST"},
    )
    assert minted.status_code == 422, minted.text
    assert "add the new point on Point Check first" in minted.json()["message"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_film_point_alias WHERE raw_location_norm = %s",
            (label,),
        )
        assert cur.fetchone()[0] == 0, "nothing was written"


def test_a_label_a_retired_map_row_holds_gets_a_live_alias_beside_it(
    admin_conn, alias_before, alias_cleanup
):
    """D-109-8, the alias-table trap, with the real colliding key.

    `029LTFTDOOR` is the primary key of one of the 118 retired
    `ref_film_location_map` rows (T47 mapped FTM labels onto FVL names, T54
    retired them). The old table could not hold a **live** answer for that
    label beside it, and the row must never be updated or deleted: it is the
    record for the facts that were mapped through it (ADR 0005).

    This is asserted at the table rather than through the API because the two
    cannot collide through the API today -- every one of those 118 keys is
    also a live point name of the same plant x model, so the cleaner resolves
    it by name and no row ever asks about it. The guarantee the task asks for
    is structural, so it is measured structurally: the live row goes in
    beside the retired one, and the retired one does not move.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code, raw_location_norm FROM ref_film_location_map "
            " WHERE plant_code = %s ORDER BY model_code, raw_location_norm LIMIT 1",
            (PLANT,),
        )
        row = cur.fetchone()
    assert row is not None, "the 118 retired rows are the premise of this test"
    model, label = row
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT point_code FROM ref_plant_film_point WHERE plant_code = %s "
            "  AND model_code = %s AND retired_at IS NULL ORDER BY point_no LIMIT 1",
            (PLANT, model),
        )
        target = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO ref_film_point_alias "
            "    (plant_code, model_code, raw_location_norm, point_code, reason) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING alias_id",
            (PLANT, model, label, target, "T109 test: the D-109-8 collision"),
        )
        alias_cleanup.append(cur.fetchone()[0])
    assert alias_ids(admin_conn, label), "the live alias row exists"
    assert alias_checksum(admin_conn) == alias_before, (
        "the retired row is the record for the facts mapped through it"
    )


# =====================================================================
# 5. the walk guard on resolved names (section 3.5)
# =====================================================================
def test_known_names_out_of_order_still_hold_the_whole_sheet(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    """D-99-7, unchanged by T109: a reorder still holds everything."""
    walk = walk_of(admin_conn, SGL)
    body = list(walk)
    body[10], body[20] = body[20], body[10]
    name, job = job_name("SGL")
    data = pelt([*body, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    assert review["batch"]["counts"]["rows_loaded"] == 0
    [detail] = details(admin_conn, review["batch"]["load_id"], "FILM_WALK_UNKNOWN")
    assert "in its own order" in detail and "owner decision" in detail


def test_an_alias_puts_its_label_in_its_points_place_for_the_guard(
    engineer, admin_conn, alias_cleanup, film_cleanup  # noqa: F811
):
    """Section 3.5: the guard runs on **resolved** names.

    The sheet writes the label where its point belongs, so once the alias
    exists the walk is in the list's own order and nothing is held at all.
    """
    walk = walk_of(admin_conn, SGL)
    label = "030T109RESOLVED"
    target = walk[29]
    body = [*walk[:29], label, *walk[30:]]

    name, job = job_name("SGL")
    first = sent(
        engineer, film_cleanup, admin_conn, name,
        pelt([*body, *TAIL], colour=COLOUR, job=job), PLANT,
    )["Quick Summary"]
    # T109-FIX CHANGE (D-109F-1): was `== len(walk) - 1`.
    assert first["batch"]["counts"]["rows_loaded"] == 0, (
        "one unanswered label holds every row of the sheet"
    )
    answered = engineer.post(
        ws(PLANT, first["batch"]["file_hash"], "film-point-answer"),
        json={"load_id": first["batch"]["load_id"], "raw_location": label,
              "point_code": target},
    )
    assert answered.status_code == 200, answered.text
    alias_cleanup.extend(alias_ids(admin_conn, label))

    name2, job2 = job_name("SGL")
    data2 = pelt([*body, *TAIL], colour=COLOUR, job=job2)
    second = sent(
        engineer, film_cleanup, admin_conn, name2, data2, PLANT
    )["Quick Summary"]
    assert second["batch"]["counts"]["rows_loaded"] == len(walk), (
        "resolved, in order, nothing held"
    )
    assert details(admin_conn, second["batch"]["load_id"], "FILM_WALK_UNKNOWN") == set()


# =====================================================================
# 6. the in-review appended confirm (D-99-14, D-109-7)
# =====================================================================
def test_the_appended_confirm_tags_the_point_it_adds_as_extra(
    engineer, admin_conn, marker_cleanup, film_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, SGL)
    name, job = job_name("SGL")
    data = pelt([*walk, MARKER, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    confirmed = engineer.post(
        ws(PLANT, review["batch"]["file_hash"], "film-walk-confirm"),
        json={"load_id": review["batch"]["load_id"],
              "points": [{"point_code": MARKER, "orientation": "H"}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT is_extra FROM ref_plant_film_point "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, SGL, MARKER),
        )
        assert cur.fetchall() == [(True,)], "D-109-7: the same add, now tagged"


# =====================================================================
# 7. Point Check's read (section 3.7)
# =====================================================================
def test_the_list_says_everything_point_check_shows(engineer):
    body = point_list(engineer, RANGER)
    assert body["has_setting"] is True
    numbers = [item["point_no"] for item in body["items"]]
    assert numbers == sorted(numbers), "walk order"
    assert len(body["items"]) == 98
    for item in body["items"]:
        assert set(item) == {
            "point_no", "point_code", "counted", "orientation",
            "is_complete_stop", "is_extra", "reason", "changed_by", "changed_at",
            "label",
        }
        assert item["orientation"] in ("H", "V")
    extra = {item["point_code"] for item in body["items"] if item["is_extra"]}
    assert extra == set(EXTRA_POINTS), "the owner's four, on this DBL list"
    assert sum(1 for item in body["items"] if item["is_complete_stop"]) >= 1
    assert [item["point_code"] for item in body["retired_items"]] == [], (
        "nothing on this list has been retired"
    )


def test_the_model_list_counts_live_points(engineer):
    response = engineer.get(f"/api/v1/plants/{PLANT}/film-points")
    assert response.status_code == 200, response.text
    counted = {
        item["model_code"]: item["point_count"] for item in response.json()["items"]
    }
    assert counted == {RANGER: 98, RAPTOR: 98, RAPCAP: 93, SGL: 58}, (
        "T103-FIX: the size of the list, not of its setting rows"
    )


def test_an_unknown_model_is_a_404_not_an_empty_page(engineer):
    assert engineer.get(
        f"/api/v1/plants/{PLANT}/film-points/P703%20NOT%20A%20MODEL"
    ).status_code == 404


# =====================================================================
# 8. other plants (section 3.9)
# =====================================================================
#: RO05 CHANGE (owner, RO04): AAT now has Film settings, so the plant with
#: none is FVL (0 `film_point_setting` rows, measured in RO04).
NO_SETTING_PLANT = "FVL"


def test_a_plant_with_no_setting_is_read_only(engineer, admin_conn, ro19_plants):
    # RO19: no setting is independent of rollout; RO17 allows edits but
    # still refuses retiring the last live point, without writing anything.
    model, point = "P703 DBL RANGER", "001HOOD"
    plant = ro19_plants({model: (point,)})
    read = engineer.get(f"/api/v1/plants/{plant}/film-points/{model}")
    assert read.status_code == 200, read.text
    assert read.json()["has_setting"] is False
    gone = engineer.post(
        f"/api/v1/plants/{plant}/film-points/{model}/retire",
        json={"point_code": point, "reason": "RO19 test last-live guard"},
    )
    assert gone.status_code == 409, gone.text
    assert "last live point" in gone.text
    with admin_conn.cursor() as cur:
        cur.execute("SELECT retired_at FROM ref_plant_film_point "
                    "WHERE plant_code = %s AND model_code = %s AND point_code = %s",
                    (plant, model, point))
        assert cur.fetchone() == (None,)
        cur.execute("SELECT count(*) FROM film_point_setting WHERE plant_code = %s", (plant,))
        assert cur.fetchone()[0] == 0
    ruled = ro19_plants(ruled=True)
    read = engineer.get(f"/api/v1/plants/{ruled}/film-points/{model}")
    assert read.status_code == 200, read.text
    assert read.json()["has_setting"] is True


# =====================================================================
# 9. T109-FIX: nothing loads until every label is answered (D-109F-1..3)
# =====================================================================
def _renumbered_down(walk: list[str]) -> list[str]:
    """``walk`` with its 5th point taken out and the rest renumbered down.

    The shape the T109 review measured on a probe built from the real
    `AW_DBL_1974152.xlsx`: `005HOOD`..`014HOOD` become physically the old
    `006`..`015`, and far enough down the list the shifted labels coincide
    with live names again, in the list's own order. That is why T109 loaded
    76 of its rows -- each one onto the point above the one measured.
    """
    rest = walk[:4] + walk[5:]
    return [
        f"{i + 1:03d}{re.sub(r'^[0-9]+', '', point)}"
        for i, point in enumerate(rest)
    ]


def test_a_renumbered_walk_down_loads_nothing_and_asks_every_label(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    """D-109F-1 and D-109F-3, on the shape that made this task necessary.

    0 rows ready, every label the live list does not hold asked in its own
    row, every row that resolved held with the sentence that says what the
    sheet is waiting for, and "Yes, load these rows" loading nothing.
    """
    walk = walk_of(admin_conn, SGL)
    body = _renumbered_down(walk)
    unknown = [label for label in body if label not in set(walk)]
    assert unknown, "the premise: a renumber writes names the list does not hold"
    assert set(body) & set(walk), (
        "and names it does hold, one spot out -- the silent wrong measurement"
    )
    name, job = job_name("SGL")
    data = pelt([*body, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    assert review["batch"]["counts"]["rows_loaded"] == 0, "not one row loads"

    rows = rows_by_label(admin_conn, load_id)
    asked = {
        label for label, (disposition, reason) in rows.items()
        if reason == "FILM_POINT_UNKNOWN"
    }
    waiting = {
        label for label, (disposition, reason) in rows.items()
        if reason == "FILM_POINT_WAITING"
    }
    assert asked == set(unknown), "each unknown label is asked in its row"
    assert waiting == set(body) - asked, "every other body row waits"
    assert all(
        disposition == "QUARANTINE"
        for disposition, reason in rows.values()
        if reason != "FILM_TAIL_LABEL"
    ), "no row of the sheet is a LOAD row"

    sheet = worksheet_of(engineer, review["batch"]["file_hash"])
    assert sheet["state"] == "needs_answer" and sheet["rows_ready"] == 0
    assert sheet["film_question"] is None, "the questions are in the rows"
    assert {item["raw_location"] for item in sheet["film_unknown_labels"]} == asked
    [sentence] = details(admin_conn, load_id, "FILM_POINT_WAITING")
    assert "Nothing on this sheet loads until every label is answered" in sentence
    assert "renumbered" in sentence, "D-109F-3: say what a renumber means"
    assert "do not map these labels" in sentence and "fix the file" in sentence

    # "Yes, load these rows" loads nothing from this sheet, and says why.
    clicked = engineer.post(ws(PLANT, review["batch"]["file_hash"], "load-ready"))
    assert clicked.status_code == 409, clicked.text
    assert "No tab of this workbook is ready to load" in clicked.json()["message"]
    assert film_facts(admin_conn, load_id) == [], "nothing was filed anywhere"


def test_answers_that_resolve_to_a_reordered_walk_hold_the_whole_sheet(
    engineer, admin_conn, alias_cleanup, film_cleanup  # noqa: F811
):
    """D-109F-2: the walk check runs again on the **resolved** names.

    Two labels. The first is answered as the point it sits in front of, which
    resolves in the list's own order and changes nothing -- the sheet still
    loads nothing, because the second label is still unanswered (D-109F-1).
    The second is answered as a point far earlier in the walk, so the
    resolved names run out of the list's order: that is a reorder (D-99-7)
    and the whole sheet is held as one. A set of answers can never make a
    wrong walk loadable.
    """
    walk = walk_of(admin_conn, SGL)
    first_label, second_label = "011T109SWAPA", "021T109SWAPB"
    body = [*walk[:10], first_label, *walk[11:20], second_label, *walk[21:]]
    name, job = job_name("SGL")
    data = pelt([*body, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert review["batch"]["counts"]["rows_loaded"] == 0

    def answer(label: str, point: str):
        response = engineer.post(
            ws(PLANT, file_hash, "film-point-answer"),
            json={"load_id": load_id, "raw_location": label, "point_code": point},
        )
        assert response.status_code == 200, response.text
        alias_cleanup.extend(alias_ids(admin_conn, label))
        wait_for(engineer, load_id)

    # The first answer resolves in order, so it settles nothing by itself.
    answer(first_label, walk[10])
    sheet = worksheet_of(engineer, file_hash)
    assert sheet["rows_ready"] == 0, "one label still unanswered (D-109F-1)"
    assert [item["raw_location"] for item in sheet["film_unknown_labels"]] == [
        second_label
    ], "and it is still the only question"

    # The second resolves to a point the walk has long passed: a reorder.
    answer(second_label, walk[0])
    after = worksheet_of(engineer, file_hash)
    assert after["rows_ready"] == 0, "a reordered walk holds everything"
    assert after["film_unknown_labels"] == [], "nothing is unanswered now"
    assert after["film_question"]["kind"] == "walk", "one sheet-wide question"
    assert after["film_question"]["confirmable"] is False
    [detail] = details(admin_conn, load_id, "FILM_WALK_UNKNOWN")
    assert "in its own order" in detail and "owner decision" in detail


# =====================================================================
# the way out
# =====================================================================
def test_reference_counts_are_flat(admin_conn, reference_before, alias_before):
    assert table_counts(admin_conn) == reference_before, (
        "this module added no reference row it did not remove"
    )
    assert alias_checksum(admin_conn) == alias_before


def test_adding_the_point_a_held_sheet_asks_about_reads_it_again(
    engineer, admin_conn, marker_cleanup, film_cleanup  # noqa: F811
):
    """RO19 follow-up: the add re-reads the waiting sheet; no self-alias needed."""
    walk = walk_of(admin_conn, SGL)
    name, job = job_name("SGL")
    data = pelt([*walk, MARKER, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert review["batch"]["counts"]["rows_loaded"] == 0, "held on the unknown point"

    added = add_point(engineer, SGL, MARKER, orientation="H", counted=False)
    assert added.status_code == 200, added.text
    assert added.json()["replayed_load_ids"] == [load_id]
    assert "being read again" in added.json()["operator_message"]
    wait_for(engineer, load_id)

    after = worksheet_of(engineer, file_hash)
    assert after["film_unknown_labels"] == [], "it stops asking"
    assert after["state"] == "ready" and after["rows_ready"] == len(walk) + 1
    assert alias_ids(admin_conn, MARKER) == [], "no alias was needed"
