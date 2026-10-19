"""T100 Part A -- what the worksheet GET tells the screen about a Film sheet.

Claims (task section 4, backend), against the running application and the live
database. Every one of them is about a **read**: T100 adds no rule, no write
and no migration. The last test proves the read writes nothing.

1. A held walk with an appended name -> `film_question.kind == "walk"`,
   `confirmable: true`, the name with the H/V the list's own points of that
   panel word carry; a word the list has never had -> null.
2. Inserted / reordered / renumbered / duplicate -> `kind == "walk"`,
   `confirmable: false`; the duplicate has its own sentence.
3. A model conflict -> `kind == "model"` with both models; an unusual Job
   Number -> `kind == "job"` with `job_no` as written. After the answer the
   question is gone and the rows are ready.
4. Rows: `counted` true for a seeded FTM point, false after a setting says
   so, null for WaveScan and for FVL Film (no setting); true for AAT Film
   since RO04; `film_tail` only for the tail.
5. `GET .../film-points` lists FTM's four models 98/98/93/58 with
   `has_setting: true`, AAT's with true (RO04), and FVL's with false.
6. The worksheet GET writes nothing.

Fixtures are the T99 file's: uploads go through `film_cleanup` (deleted by
`load_id`), the appended-name test removes its marker point by id, and the
setting test removes the rows it wrote by `setting_id`.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.domain.film import FilmReference
from app.services.worksheet import _film_question
from tests.ro19_synthetic import ro19_plants  # noqa: F401
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import (
    film_cleanup,  # noqa: F401
    pelt,
    sent,
    wait_for,
)
from tests.test_t99_film_point_lists import (  # noqa: F401
    COLOUR,
    LIVE,
    MARKER_POINT,
    PLANT,
    RANGER,
    RAPCAP,
    RAPTOR,
    SGL,
    SKIPPED,
    TAIL,
    _renumbered,
    _swapped,
    job_name,
    marker_cleanup,
    setting_cleanup,
    walk_of,
    ws,
)

pytestmark = pytest.mark.ingest


def worksheet_of(client, plant: str, file_hash: str) -> dict:
    response = client.get(f"/api/v1/plants/{plant}/workbooks/{file_hash}/worksheet")
    assert response.status_code == 200, response.text
    return {s["sheet"]: s for s in response.json()["sheets"]}["Quick Summary"]


def upload(engineer, film_cleanup, admin_conn, labels, *, token="SGL", job=None,
           filename=None) -> dict:  # noqa: F811
    name, generated = job_name(token)
    data = pelt([*labels, *TAIL], colour=COLOUR, job=job or generated)
    return sent(
        engineer, film_cleanup, admin_conn, filename or name, data, PLANT
    )["Quick Summary"]


# =====================================================================
# 1. the walk question, and the H/V the list proposes
# =====================================================================
def test_an_appended_name_asks_with_the_hv_the_list_already_gives_that_word(
    engineer, admin_conn, film_cleanup, marker_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, RAPCAP)
    # `099TGATEIN` takes the V that 091-093TGATEIN carry; `099T99MARK` is a
    # word the list has never had, so nobody may guess it.
    review = upload(
        engineer, film_cleanup, admin_conn,
        [*walk, "099TGATEIN", MARKER_POINT], token="RAP",
    )
    sheet = worksheet_of(engineer, PLANT, review["batch"]["file_hash"])
    question = sheet["film_question"]
    assert question is not None
    assert question["kind"] == "walk"
    assert question["confirmable"] is True
    assert question["model_code"] == RAPCAP
    assert question["appended"] == [
        {"point_code": "099TGATEIN", "proposed_orientation": "V", "counted": True},
        {"point_code": MARKER_POINT, "proposed_orientation": None, "counted": True},
    ], "the H/V is read off the list's own points of that word, never guessed"
    assert "past the last point" in question["operator_message"]
    assert question["models"] == []


def test_a_film_sheet_with_nothing_wrong_asks_nothing(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    review = upload(engineer, film_cleanup, admin_conn, walk_of(admin_conn, SGL))
    sheet = worksheet_of(engineer, PLANT, review["batch"]["file_hash"])
    assert sheet["film_question"] is None
    assert sheet["state"] == "ready"


def test_a_wavescan_tab_asks_no_film_question():
    """A tab that is not a FilmBuild tab never carries a Film question.

    Asserted on the function rather than through a route, because the answer
    is the first line of it: a sheet whose `sheet_class` is not
    FILMTHICKNESS returns None before anything is read. The `held` reasons
    below are a WaveScan hold, which is the case that could wrongly match.
    """
    film = FilmReference()  # not reached: both cases return before any read
    wavescan = {
        "sheet_class": "WAVESCAN", "plant_code": PLANT,
        "source_file": "x.xlsx", "raw_headers": {},
    }
    projection = [
        {"reason": "UNKNOWN_CHECKZONE", "detail": "...", "canonical": {}},
        {"reason": "FILM_WALK_UNKNOWN", "detail": "...", "canonical": {}},
    ]
    assert _film_question(wavescan, projection, film) is None
    # A Film tab with no sheet-wide hold is also None.
    assert _film_question(
        {**wavescan, "sheet_class": "FILMTHICKNESS"},
        [{"reason": "UNMAPPED_POINT", "detail": "...", "canonical": {}}],
        film,
    ) is None


# =====================================================================
# 2. the walks that cannot be confirmed
# =====================================================================
#: T109 CHANGE (D-109-6): "inserted" and "renumbered" write labels the live
#: list does not hold, and those are asked about **in their own rows** now,
#: so the tab has no sheet-wide `film_question` at all. They moved to
#: `test_a_label_the_list_does_not_hold_is_a_row_question` below. The two
#: shapes left here are the ones that still hold everything: a live name out
#: of the list's order, and a live name written twice (D-99-7, unchanged).
@pytest.mark.parametrize("shape, says", [
    ("swapped", "in its own order"),
    ("duplicate", "twice"),
])
def test_a_walk_that_is_not_a_skip_asks_with_no_button(
    engineer, admin_conn, film_cleanup, shape, says  # noqa: F811
):
    walk = walk_of(admin_conn, SGL)
    body = {
        "inserted": [*walk[:5], "035LBPILLAR", *walk[5:]],
        "renumbered": _renumbered(walk),
        "swapped": _swapped(walk),
        "duplicate": [*walk[:5], walk[4], *walk[5:]],
    }[shape]
    review = upload(engineer, film_cleanup, admin_conn, body)
    sheet = worksheet_of(engineer, PLANT, review["batch"]["file_hash"])
    question = sheet["film_question"]
    assert question["kind"] == "walk"
    assert question["confirmable"] is False, "no button for this one (D-99-14)"
    assert question["appended"] == []
    assert says in question["operator_message"], question["operator_message"]
    assert not re.search(r"\bas point [0-9]+\b", question["operator_message"])
    if shape == "duplicate":
        assert f'"{walk[4]}" twice' in question["operator_message"]
        assert "has it once" in question["operator_message"]


@pytest.mark.parametrize("shape", ["inserted", "renumbered"])
def test_a_label_the_list_does_not_hold_is_a_row_question(
    engineer, admin_conn, film_cleanup, shape  # noqa: F811
):
    """T109 (D-109-6): the question is in the row, not above the table.

    Until T109 a name the list does not hold held the whole sheet with one
    sheet-wide refusal -- there was no way to say what it is. Now there is:
    pick the live point it means (remembered for every later upload) or add a
    new point on Point Check. So the tab carries no sheet-wide question and
    the labels come back in `film_unknown_labels` with the live points an
    answer may name.

    T109-FIX CHANGE (D-109F-1): and **no row of the tab is ready** while any
    label is unanswered. T109 loaded the rows that resolved, which on a walk
    renumbered down files them one point out. The tab is `needs_answer`, 0
    rows are ready, the asked labels are `needs_confirmation` and the rest
    are held out with the sentence that says what the tab is waiting for.
    """
    walk = walk_of(admin_conn, SGL)
    body = (
        [*walk[:5], "035LBPILLAR", *walk[5:]] if shape == "inserted"
        else _renumbered(walk)
    )
    review = upload(engineer, film_cleanup, admin_conn, body)
    # T109-FIX CHANGE (D-109F-1): was `> 0`.
    assert review["batch"]["counts"]["rows_loaded"] == 0, "nothing loads yet"
    sheet = worksheet_of(engineer, PLANT, review["batch"]["file_hash"])
    assert sheet["film_question"] is None, "not a sheet-wide hold any more"
    assert sheet["state"] == "needs_answer", "questions on it, not an Admin's"
    assert sheet["rows_ready"] == 0, "D-109F-1: no row of it is ready"
    asked = {item["raw_location"] for item in sheet["film_unknown_labels"]}
    assert asked, "every label the list does not hold is asked about"
    assert asked <= set(body) and not asked & set(walk), (
        "only the labels the live list does not hold"
    )
    offered = {item["point_code"] for item in sheet["film_point_choices"]}
    assert offered == set(walk), "this plant's live points for the model"
    assert all(
        item["orientation"] in ("H", "V") for item in sheet["film_point_choices"]
    )
    for item in sheet["rows"]:
        if item["film_tail"]:
            continue
        if item["panel_label"] in asked:
            assert item["outcome"] == "needs_confirmation", "asked, not held out"
        else:
            assert item["outcome"] == "held_out", "waiting, not ready"
            assert "every label is answered" in item["operator_message"]
    # D-109F-3: the tab says what to do about a renumbered walk instead.
    asked_rows = [r for r in sheet["rows"] if r["panel_label"] in asked]
    assert "do not map these labels" in asked_rows[0]["operator_message"]


# =====================================================================
# 3. the model and the Job Number questions, and what an answer does
# =====================================================================
def test_a_model_conflict_asks_with_both_models_and_clears_on_the_answer(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    serial = f"{uuid.uuid4().int % 10**7:07d}"
    walk = walk_of(admin_conn, RAPTOR)[:4]
    review = upload(
        engineer, film_cleanup, admin_conn, walk,
        job=f"AW_RB_{serial}", filename=f"AW_DBL_{serial}.xlsx",
    )
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    question = worksheet_of(engineer, PLANT, file_hash)["film_question"]
    assert question["kind"] == "model"
    assert question["models"] == [RAPTOR, RANGER], "the Job Number's, then the file's"
    assert question["job_no"] == f"AW_RB_{serial}"
    assert question["confirmable"] is False and question["appended"] == []

    answered = engineer.post(
        ws(PLANT, file_hash, "film-model-answer"),
        json={"load_id": load_id, "model_code": RAPTOR},
    )
    assert answered.status_code == 200, answered.text
    wait_for(engineer, load_id)
    after = worksheet_of(engineer, PLANT, file_hash)
    assert after["film_question"] is None, "answered, so it stops asking"
    assert [r["outcome"] for r in after["rows"] if not r["film_tail"]] == (
        ["ready"] * len(walk)
    )


def test_an_unusual_job_number_asks_with_the_number_as_written(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    job = f"BL_RAP_{uuid.uuid4().int % 10**4:04d}"
    walk = walk_of(admin_conn, RAPCAP)[:4]
    review = upload(
        engineer, film_cleanup, admin_conn, walk,
        token="RAP", job=job, filename=f"{job}.xlsx",
    )
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    question = worksheet_of(engineer, PLANT, file_hash)["film_question"]
    assert question["kind"] == "job"
    assert question["job_no"] == job
    assert job in question["operator_message"]

    assert engineer.post(
        ws(PLANT, file_hash, "film-job-answer"), json={"load_id": load_id}
    ).status_code == 200
    wait_for(engineer, load_id)
    assert worksheet_of(engineer, PLANT, file_hash)["film_question"] is None


# =====================================================================
# 4. the row tick and the tail flag
# =====================================================================
def test_rows_carry_counted_and_the_tail_flag(
    engineer, admin_conn, film_cleanup, setting_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, SGL)[:4]
    review = upload(engineer, film_cleanup, admin_conn, walk)
    file_hash = review["batch"]["file_hash"]
    rows = {r["panel_label"]: r for r in worksheet_of(engineer, PLANT, file_hash)["rows"]}
    assert [rows[p]["counted"] for p in walk] == [True] * len(walk)
    assert [rows[p]["film_tail"] for p in walk] == [False] * len(walk)
    for label in TAIL:
        assert rows[label]["film_tail"] is True, label
        assert rows[label]["counted"] is None, "a tail row has no tick (D-100-4)"
        assert rows[label]["outcome"] == "held_out"

    # A setting that says the point does not count shows as an empty tick.
    url = f"/api/v1/plants/{PLANT}/film-points/{SGL}"
    changed = engineer.post(url, json={
        "points": [{"point_code": walk[1], "counted": False, "orientation": "V"}],
        "reason": "T100 test: this point is not walked any more",
    })
    assert changed.status_code == 200, changed.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT setting_id FROM film_point_setting "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s "
            " ORDER BY setting_id DESC LIMIT 1",
            (PLANT, SGL, walk[1]),
        )
        setting_cleanup.append(cur.fetchone()[0])
    again = {r["panel_label"]: r for r in worksheet_of(engineer, PLANT, file_hash)["rows"]}
    assert again[walk[1]]["counted"] is False
    assert again[walk[0]]["counted"] is True, "only the point that changed"


def test_an_fvl_film_row_has_no_tick(engineer, admin_conn, film_cleanup, ro19_plants):  # noqa: F811
    """D-99-12 / D-100-2: FVL has no setting, so there is nothing to tick.

    RO05 CHANGE (owner, RO04): this was AAT's test; AAT now has settings, so
    the claim moves to FVL, a plant that still has none.
    """
    plant = ro19_plants()
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM film_point_setting WHERE plant_code = %s", (plant,))
        assert cur.fetchone()[0] == 0, "synthetic plant has no film_point_setting row"
        cur.execute(
            "SELECT point_code FROM ref_plant_film_point "
            " WHERE plant_code = %s AND model_code = %s AND retired_at IS NULL "
            " ORDER BY point_no LIMIT 2",
            (plant, RANGER),
        )
        points = [r[0] for r in cur.fetchall()]
    assert len(points) == 2
    job = f"UR{uuid.uuid4().hex[:8].upper()}"
    data = pelt(points, job=job, vin=0)
    review = sent(
        engineer, film_cleanup, admin_conn, f"P703-{job}-AB.xlsx", data, plant,
    )["Quick Summary"]
    sheet = worksheet_of(engineer, plant, review["batch"]["file_hash"])
    assert sheet["film_question"] is None
    assert [r["panel_label"] for r in sheet["rows"]] == points
    assert {r["counted"] for r in sheet["rows"]} == {None}
    assert {r["film_tail"] for r in sheet["rows"]} == {False}


def test_an_aat_film_row_has_the_counted_tick(engineer, admin_conn, film_cleanup):  # noqa: F811
    """RO05 CHANGE (owner, RO04): AAT is set up like FTM, so its rows carry the tick."""
    data = pelt(["059LBOXSIDE", "060LBOXSIDE"], colour="Command Grey", job="",
                title="Ford Thailand Motors - PELT Filmbuild Report")
    review = sent(
        engineer, film_cleanup, admin_conn,
        f"Data Pelt P703 Box {uuid.uuid4().hex[:6]}.xlsx", data, "AAT",
    )["Quick Summary"]
    sheet = worksheet_of(engineer, "AAT", review["batch"]["file_hash"])
    assert [r["panel_label"] for r in sheet["rows"]] == ["059LBOXSIDE", "060LBOXSIDE"]
    assert {r["counted"] for r in sheet["rows"]} == {True}
    assert {r["film_tail"] for r in sheet["rows"]} == {False}


# =====================================================================
# 5. the models a plant has a list for
# =====================================================================
def test_film_points_lists_the_plants_models(engineer, viewer, ro19_plants):  # noqa: F811
    # RO19: the topology belongs to this test, independently of plant rollout.
    tag = uuid.uuid4().hex[:8].upper()
    lists = {model: tuple(f"{i:03d}ZR19{tag}" for i in range(1, n + 1))
             for model, n in LIVE.items()}
    ruled = ro19_plants(lists, ruled=True)
    response = engineer.get(f"/api/v1/plants/{ruled}/film-points")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plant_code"] == ruled
    assert {i["model_code"]: i["point_count"] for i in body["items"]} == LIVE
    assert {i["has_setting"] for i in body["items"]} == {True}

    second_lists = {RANGER: lists[RANGER][:94], "U704": lists[RANGER][:95]}
    second = ro19_plants(second_lists, ruled=True)
    read = engineer.get(f"/api/v1/plants/{second}/film-points")
    assert read.status_code == 200, read.text
    assert {i["model_code"]: i["point_count"] for i in read.json()["items"]} == {
        RANGER: 94, "U704": 95,
    }
    assert {i["has_setting"] for i in read.json()["items"]} == {True}
    unruled = ro19_plants()
    read = engineer.get(f"/api/v1/plants/{unruled}/film-points")
    assert read.status_code == 200, read.text
    assert read.json()["items"], "the unruled plant has a live Film list"
    assert {i["has_setting"] for i in read.json()["items"]} == {False}

    assert engineer.get("/api/v1/plants/NOPE/film-points").status_code == 404
    assert viewer.get(f"/api/v1/plants/{ruled}/film-points").status_code == 403
    assert viewer.get(f"/api/v1/plants/{ruled}/film-points/{SGL}").status_code == 403


# =====================================================================
# 6. the read is a read
# =====================================================================
def test_the_worksheet_get_writes_nothing(engineer, admin_conn, film_cleanup):  # noqa: F811
    watched = (
        "worksheet_decision", "film_point_setting", "ref_plant_film_point",
        "audit_event", "stg_review_row",
    )

    def counts() -> dict:
        with admin_conn.cursor() as cur:
            out = {}
            for table in watched:
                cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
                out[table] = cur.fetchone()[0]
            return out

    walk = walk_of(admin_conn, SGL)
    review = upload(
        engineer, film_cleanup, admin_conn, [*walk[:5], "035LBPILLAR", *walk[5:]]
    )
    file_hash = review["batch"]["file_hash"]
    before = counts()
    for _ in range(3):
        sheet = worksheet_of(engineer, PLANT, file_hash)
        # T109 (D-109-6): the same tab, asking in the row rather than
        # sheet-wide. The claim is unchanged: reading the question writes
        # nothing, including the live-point list the picker offers.
        assert [item["raw_location"] for item in sheet["film_unknown_labels"]] == [
            "035LBPILLAR"
        ]
        assert len(sheet["film_point_choices"]) == len(walk)
    assert counts() == before, "building the question parses nothing and writes nothing"
