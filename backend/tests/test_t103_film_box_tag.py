"""T103 -- the Box / No box tag, and three sentences that were wrong.

Claims (task section 4), against the running application and the live
database. T103 adds no migration, no write and no rule the client can see:
every claim here is about a **read** and about words.

1. The box rule on synthetic walks, from the one server function: a full DBL
   walk is `box`; a DBL that stops at `064RAPILLAR` is `no_box`; a DBL that
   stops one point later, at `065LBOXSIDE`, is `box` **and** still
   `incomplete`; a RAPCAP that stops at `059RTFEND` is `no_box`; a full SGL
   is `no_box` (D-103-2 -- its only stop is its last point); an AAT car has
   no tag at all, because AAT's list names no stop.
2. The review screen says the same thing for the sheet before it loads
   (`film_box`), and says nothing for a tab it has not read.
3. A refused `Point NNN / NNN` sheet says the sentence the refusal stored,
   on the worksheet and in the issues list, with no Admin / mapping wording
   and no mapping resolution; a WaveScan `REJECTED_TEMPLATE` keeps today's
   sentence and `resolution "mapping"`.
4. The walk's six FTWISH rows are counted as "not stored", never "held out",
   in the sheet's sentence, the workbook summary and the load toast.
5. A sheet whose Job Number colour code disagrees with its file name keeps
   that warning after it loads: on its in-History rows, and on the car as
   `identity_note`.

**What this file writes, and how it cleans up.** Every upload goes through
`film_cleanup` / `cleanup`, which delete the batches and their facts by
`load_id`. Nothing here writes, retires or deletes a reference row, a
standard or a setting.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.domain.film_walk import box_tag
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)
from tests.test_t46_filmthickness import (
    commit,
    film_cleanup,  # noqa: F401
    film_facts,
    pelt,
    sent,
)
from tests.test_t57_aat_film_gold import ec1
from tests.test_t99_film_point_lists import (
    COLOUR,
    LIVE,
    PLANT,
    RANGER,
    RAPCAP,
    SGL,
    TAIL,
    job_name,
    setting_cleanup,  # noqa: F401
    walk_of,
)

pytestmark = pytest.mark.ingest

#: Words a sentence about a final refusal must not contain (D-103-4). An
#: operator told to wait for an Admin waits for something that never comes.
ADMIN_WORDS = re.compile(r"admin|mapping|map |approve|approval", re.IGNORECASE)


def worksheet(client, plant: str, file_hash: str, sheet: str = "Quick Summary") -> dict:
    response = client.get(f"/api/v1/plants/{plant}/workbooks/{file_hash}/worksheet")
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {s["sheet"]: s for s in body["sheets"]}[sheet]


def issues_of(admin_client, plant: str, file_hash: str) -> list[dict]:
    response = admin_client.get(
        f"/api/v1/plants/{plant}/workbooks/{file_hash}/issues"
    )
    assert response.status_code == 200, response.text
    return response.json()["issues"]


def vehicle_of(client, admin_conn, load_id: int) -> dict:
    """The car this load measured, as History publishes it."""
    [vid] = {f[6] for f in film_facts(admin_conn, load_id)}
    response = client.get(
        f"/api/v1/plants/{PLANT}/filmthickness/vehicles/{vid}/points"
    )
    assert response.status_code == 200, response.text
    return response.json()["vehicle"]


def month_of(admin_conn, load_id: int) -> str:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT to_char(measured_date, 'YYYY-MM') "
            "  FROM filmthickness WHERE load_id = %s",
            (load_id,),
        )
        [(month,)] = cur.fetchall()
    return month


# =====================================================================
# 1. the rule
# =====================================================================
def test_the_rule_is_one_function_over_ranks_in_the_walk():
    """The whole of D-103-1, asserted on the function that owns it.

    The box section starts after the **lowest** stop, so nothing here needs
    to know a model name, a panel word or a point code -- which is why one
    function can answer for History and for the review.
    """
    assert box_tag([63, 97], [97]) == "box"
    assert box_tag([63, 97], [63]) == "no_box"
    assert box_tag([63, 97], [64]) == "box", "one point past the stop is a box"
    assert box_tag([57], [57]) == "no_box", "a stop on the last point: no box section"
    assert box_tag([], [97]) is None, "a list with no stop says nothing"
    assert box_tag([63, 97], []) is None or box_tag([63, 97], []) == "no_box"


@pytest.mark.parametrize("token, model, stop, box, complete", [
    ("DBL", RANGER, None, "box", True),
    ("DBL", RANGER, "064RAPILLAR", "no_box", True),
    ("DBL", RANGER, "065LBOXSIDE", "box", False),
    ("RAP", RAPCAP, "059RTFEND", "no_box", True),
    ("SGL", SGL, None, "no_box", True),
])
def test_the_tag_of_a_synthetic_walk(
    engineer, admin, viewer, admin_conn, film_cleanup,  # noqa: F811
    token, model, stop, box, complete,
):
    walk = walk_of(admin_conn, model)
    body = walk if stop is None else walk[: walk.index(stop) + 1]
    name, job = job_name(token)
    review = sent(
        engineer, film_cleanup, admin_conn, name,
        pelt([*body, *TAIL], colour=COLOUR, job=job), PLANT,
    )["Quick Summary"]
    load_id = review["batch"]["load_id"]

    # Before it loads: the review says it, off the sheet's own rows.
    _, sheet = worksheet(engineer, PLANT, review["batch"]["file_hash"])
    assert sheet["state"] == "ready", sheet["operator_message"]
    assert sheet["film_box"] == box

    # After it loads: History says the same thing about the car.
    commit(engineer, admin, review)
    vehicle = vehicle_of(viewer, admin_conn, load_id)
    assert vehicle["box"] == box
    assert vehicle["incomplete"] is not complete, (
        "T103 says nothing about whether the walk is whole; T99 still does"
    )
    assert vehicle["expected_point_count"] == (
        len(body) if complete else LIVE[model]
    )

    # The list read answers it too, for the same car.
    page = viewer.get(
        f"/api/v1/plants/{PLANT}/filmthickness/vehicles",
        params={"month": month_of(admin_conn, load_id)},
    )
    assert page.status_code == 200, page.text
    listed = {
        item["logical_vehicle_id"]: item["box"] for item in page.json()["items"]
    }
    assert listed[vehicle["logical_vehicle_id"]] == box


def test_a_plant_whose_list_names_no_stop_has_no_tag(
    engineer, viewer, admin_conn, film_cleanup  # noqa: F811
):
    """AAT's P703 list names no complete stop, so there is no box section.

    A tag would have to mean something, and nothing in AAT's reference data
    says where its box starts. The read says `null` and the screen shows
    nothing -- it does not guess, and it does not borrow FTM's list.
    """
    n = uuid.uuid4().int
    sample = f"25{n % 10**5:05d} P703 38P"
    data = ec1(["001HOOD", "032LFDRPOST", "073LBXFLOOR"], sample=sample)
    review = sent(
        engineer, film_cleanup, admin_conn,
        f"Data Pelt P703_{uuid.uuid4().hex[:6]}.xlsx", data, "AAT",
    )["P703_38P"]
    file_hash = review["batch"]["file_hash"]
    _, sheet = worksheet(engineer, "AAT", file_hash, sheet="P703_38P")
    assert sheet["film_box"] is None
    assert engineer.post(
        f"/api/v1/plants/AAT/workbooks/{file_hash}/load-ready"
    ).status_code == 200

    [vid] = {f[6] for f in film_facts(admin_conn, review["batch"]["load_id"])}
    grid = viewer.get(f"/api/v1/plants/AAT/filmthickness/vehicles/{vid}/points")
    assert grid.status_code == 200, grid.text
    assert grid.json()["vehicle"]["box"] is None


def test_a_held_film_tab_carries_no_tag(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    """A walk nobody has read is not a walk with or without a box.

    An inserted label holds the whole sheet (D-99-7), so no row of it is or
    will be a measurement and there is nothing to place in the walk.
    """
    walk = walk_of(admin_conn, SGL)
    inserted = [*walk[:10], walk[0], *walk[10:]]
    name, job = job_name("SGL")
    review = sent(
        engineer, film_cleanup, admin_conn, name,
        pelt([*inserted, *TAIL], colour=COLOUR, job=job), PLANT,
    )["Quick Summary"]
    _, sheet = worksheet(engineer, PLANT, review["batch"]["file_hash"])
    assert sheet["state"] != "ready"
    assert sheet["film_box"] is None


# =====================================================================
# 2. the refusal that no Admin can lift (D-103-4)
# =====================================================================
def test_a_no_name_sheet_says_why_and_asks_nobody_to_map_it(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):
    name, job = job_name("SGL")
    data = pelt(
        [f"Point {n:03d} / 017" for n in range(1, 18)], colour=COLOUR, job=job
    )
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    assert review["batch"]["status"] == "REJECTED_TEMPLATE"
    with admin_conn.cursor() as cur:
        cur.execute("SELECT notes FROM load_batch WHERE load_id = %s", (load_id,))
        notes = cur.fetchone()[0]
    stored = notes.split("FILM_NO_NAMED_POINTS: ", 1)[1]

    body, sheet = worksheet(engineer, PLANT, review["batch"]["file_hash"])
    assert sheet["operator_message"] == stored
    assert "names no points" in sheet["operator_message"]
    assert not ADMIN_WORDS.search(sheet["operator_message"]), sheet["operator_message"]
    assert f"{sheet['sheet']}: {stored}" in body["checklist"]

    # The workbook also carries the PELT diagram tab, which is its own
    # REJECTED_TEMPLATE and not this claim; the issue of the refused sheet is.
    [blocker] = [
        i for i in issues_of(admin, PLANT, review["batch"]["file_hash"])
        if i["level"] == "BLOCKER" and i["load_id"] == load_id
    ]
    assert blocker["token"] == "REJECTED_TEMPLATE"
    assert blocker["resolution"] == "corrected_source", (
        "no alias an Admin approves makes a placeholder label name a point"
    )
    assert blocker["operator_message"] == stored


def test_a_wavescan_rejected_template_keeps_todays_sentence(
    engineer, admin, cleanup  # noqa: F811
):
    """The control: only the no-name Film refusal changed (D-103-4)."""
    from tests.test_t04_ingest import unique_rows
    from tests.test_t08_mapping import rejected_template_batch

    load_id = rejected_template_batch(engineer, cleanup, unique_rows(2))
    batch = engineer.get(f"/api/v1/batches/{load_id}").json()["batch"]
    plant, file_hash = batch["plant_code"], batch["file_hash"]
    _, sheet = worksheet(engineer, plant, file_hash, sheet=batch["source_sheet"])
    assert "names no points" not in sheet["operator_message"]

    blockers = [
        i for i in issues_of(admin, plant, file_hash)
        if i["level"] == "BLOCKER" and i["load_id"] == load_id
    ]
    assert "REJECTED_TEMPLATE" in {i["token"] for i in blockers}
    for blocker in blockers:
        assert blocker["operator_message"] is None, blocker
    assert {i["resolution"] for i in blockers if i["token"] == "REJECTED_TEMPLATE"} == {
        "mapping"
    }, "an unproved WaveScan layout is still what an Admin approves"


# =====================================================================
# 3. the tail is not stored, and is never "held out" (D-103-5)
# =====================================================================
def test_the_tail_rows_are_counted_as_not_stored(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, SGL)
    name, job = job_name("SGL")
    review = sent(
        engineer, film_cleanup, admin_conn, name,
        pelt([*walk, *TAIL], colour=COLOUR, job=job), PLANT,
    )["Quick Summary"]
    file_hash = review["batch"]["file_hash"]
    body, sheet = worksheet(engineer, PLANT, file_hash)

    tail = [r for r in sheet["rows"] if r["film_tail"]]
    assert len(tail) == len(TAIL)
    assert sheet["rows_held"] == 0, "a tail row is not a row anybody can fix"
    assert sheet["operator_message"] == (
        f"{len(walk)} readings ready to add, {len(TAIL)} not stored (walk tail)."
    )
    assert body["summary_message"] == sheet["operator_message"]
    assert "held out" not in body["summary_message"]
    for line in body["checklist"]:
        assert "held out" not in line, line

    loaded = engineer.post(f"/api/v1/plants/{PLANT}/workbooks/{file_hash}/load-ready")
    assert loaded.status_code == 200, loaded.text
    result = loaded.json()
    assert f"{len(TAIL)} not stored (walk tail)" in result["operator_message"]
    assert "held out" not in result["operator_message"]
    assert result["rows_held"] == 0, (
        "rows_held means rows a person can still make load (D-103-5)"
    )

    # And the sheet's own sentence, after it loaded.
    _, after = worksheet(engineer, PLANT, file_hash)
    assert after["state"] == "loaded"
    assert f"{len(TAIL)} not stored (walk tail)" in after["operator_message"]
    assert "held out" not in after["operator_message"]


# =====================================================================
# 4. the colour-code warning survives the load (D-103-6)
# =====================================================================
def test_a_colour_code_warning_is_still_there_after_the_rows_load(
    engineer, viewer, admin_conn, film_cleanup  # noqa: F811
):
    serial = f"{uuid.uuid4().int % 10**7:07d}"
    walk = walk_of(admin_conn, SGL)[:3]
    data = pelt([*walk, *TAIL], colour=COLOUR, job=f"AM_SGL_{serial}")
    review = sent(
        engineer, film_cleanup, admin_conn, f"AW_SGL_{serial}.xlsx", data, PLANT
    )["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT detail FROM stg_review_row "
            " WHERE load_id = %s AND disposition = 'LOAD'", (load_id,),
        )
        [warning] = [r[0] for r in cur.fetchall()]
    assert '"AM"' in warning and '"AW"' in warning

    assert engineer.post(
        f"/api/v1/plants/{PLANT}/workbooks/{file_hash}/load-ready"
    ).status_code == 200
    _, after = worksheet(engineer, PLANT, file_hash)
    loaded = [r for r in after["rows"] if r["outcome"] == "already_in_history"]
    assert len(loaded) == len(walk)
    for row in loaded:
        assert "This reading is in History." in row["operator_message"]
        assert warning in row["operator_message"], (
            "D-99-11 meant the warning to stay findable (D-103-6)"
        )

    vehicle = vehicle_of(viewer, admin_conn, load_id)
    assert vehicle["identity_note"] == warning
    assert vehicle["color"] == COLOUR, "Layer 2 still decides the colour"


def test_a_car_with_nothing_to_say_has_no_note(
    engineer, admin, viewer, admin_conn, film_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, SGL)
    name, job = job_name("SGL")
    review = sent(
        engineer, film_cleanup, admin_conn, name,
        pelt([*walk, *TAIL], colour=COLOUR, job=job), PLANT,
    )["Quick Summary"]
    commit(engineer, admin, review)
    vehicle = vehicle_of(viewer, admin_conn, review["batch"]["load_id"])
    assert vehicle["identity_note"] is None


# =====================================================================
# T103-FIX (D-103F-1): the Points page counts points, not setting rows
# =====================================================================
def test_a_second_setting_row_does_not_grow_the_lists_size(
    engineer, admin_conn, setting_cleanup  # noqa: F811
):
    """`point_count` is the size of the list, not of the join (D-103F-1).

    `film_point_setting` is append-only and a person may correct themselves
    (D-99-4), so a point can carry any number of rows. T100 counted the
    joined rows, which made the live FTM Ranger list read 100 for 98 points
    once D-101-4 added two rows on `095RBXFLOOR`. One POST reproduces that
    shape in one test, against the one read that publishes the number.
    """
    url = f"/api/v1/plants/{PLANT}/film-points"
    before = engineer.get(url)
    assert before.status_code == 200, before.text
    counts = {i["model_code"]: i["point_count"] for i in before.json()["items"]}
    assert counts == LIVE, "the live lists, before this test writes anything"

    point = walk_of(admin_conn, SGL)[1]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT setting_id FROM film_point_setting "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, SGL, point),
        )
        seeded = [r[0] for r in cur.fetchall()]
    written = engineer.post(f"{url}/{SGL}", json={
        "points": [{"point_code": point, "counted": True, "orientation": "V"}],
        "reason": "T103-FIX test: a second row on one point, removed by id",
    })
    assert written.status_code == 200, written.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT setting_id FROM film_point_setting "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s "
            " ORDER BY setting_id",
            (PLANT, SGL, point),
        )
        rows = [r[0] for r in cur.fetchall()]
    setting_cleanup.extend(i for i in rows if i not in seeded)
    assert len(rows) == len(seeded) + 1, "append-only: the older row stays"

    after = engineer.get(url)
    assert after.status_code == 200, after.text
    assert {i["model_code"]: i["point_count"] for i in after.json()["items"]} == LIVE, (
        "a point with two settings is still one point of the list"
    )
    assert {i["model_code"]: i["has_setting"] for i in after.json()["items"]} == {
        model: True for model in LIVE
    }, "has_setting is unchanged by D-103F-1"
