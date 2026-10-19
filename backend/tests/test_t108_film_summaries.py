"""T108 -- Film History's week cards say what its cars say.

Claims (task section 3):

1. The week bands are **WaveScan's own**, by import: `domain.film_history`
   asks `domain.history.measured_week`, so a day cannot land in week 3 on
   one screen and week 4 on the other.
2. A card counts only what its cars carry: distinct cars, their readings,
   their Box / No box tag (T103) and their incomplete flag (T99). A car
   whose plant list names no complete stop has no tag and is counted in
   neither `box_count` nor `no_box_count`.
3. Against the running application and the live database: the cards of a
   month group by week x model x colour, and every count equals the cars
   `.../filmthickness/vehicles` publishes for the same filters.
4. `model` and `color` are passed through, so one card's filters narrow the
   read exactly as they narrow the vehicles read.
5. The route is in both OpenAPI copies, identically.

The first two claims need no database: they are the pure function, fed the
same dicts the service builds. The rest upload synthetic PELT walks into a
month of their own and compare two reads of them.

**What this file writes, and how it cleans up.** Every upload goes through
`film_cleanup`, which deletes the batches and their facts by `load_id`.
Nothing here writes, retires or deletes a reference row, a standard or a
setting, and nothing is published to any server but the test client's.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.domain import film_history
from app.domain.history import WEEK_BANDS, measured_week
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
    pelt,
    sent,
)
from tests.test_t99_film_point_lists import (
    COLOUR,
    PLANT,
    RANGER,
    SGL,
    TAIL,
    job_name,
    walk_of,
)

#: A month of this test's own, so the cars it uploads are the only cars in
#: it. The owner's real FTM film months are 2026-07..2026-10.
MONTH = "2024-03"
SUMMARIES = f"/api/v1/plants/{PLANT}/filmthickness/summaries"
VEHICLES = f"/api/v1/plants/{PLANT}/filmthickness/vehicles"

BACKEND_SPEC = Path(__file__).resolve().parents[1] / "openapi.json"
DOCS_SPEC = BACKEND_SPEC.parents[1] / "docs" / "openapi.json"
ROUTE = "/api/v1/plants/{plant_code}/filmthickness/summaries"


def car(
    day: int,
    *,
    vid: str,
    model: str = RANGER,
    color: str = COLOUR,
    readings: int = 4,
    box: str | None = "box",
    incomplete: bool = False,
    display: str | None = None,
) -> dict:
    """One car as `services.filmthickness` publishes it, for the pure tests."""
    return {
        "logical_vehicle_id": vid,
        "measured_date": date(2024, 3, day),
        "model": model,
        "model_display_name": display,
        "color": color,
        "box": box,
        "incomplete": incomplete,
        "reading_count": readings,
    }


# =====================================================================
# 1. the week rule is WaveScan's, not a second copy
# =====================================================================
@pytest.mark.parametrize("day", [1, 7, 8, 14, 15, 21, 22, 28, 29, 31])
def test_a_day_lands_in_the_week_wavescan_puts_it_in(day):
    """The one function, asked twice. No band is written down here.

    March has 31 days, so every band exists; `measured_week` owns which is
    which (`02-PIPELINE.md` section 8.1) and Film History imports it.
    """
    [week] = film_history.summarize([car(day, vid="a" * 64)])
    assert week.week == measured_week(day)
    first, last = WEEK_BANDS[week.week - 1]
    assert first <= day <= last


def test_weeks_come_back_descending_and_empty_weeks_are_absent():
    weeks = film_history.summarize([
        car(3, vid="1" * 64), car(17, vid="2" * 64), car(30, vid="3" * 64),
    ])
    assert [w.week for w in weeks] == [5, 3, 1]
    assert all(len(w.cards) == 1 for w in weeks)


# =====================================================================
# 2. a card counts only what its cars carry
# =====================================================================
def test_a_card_is_the_cars_own_counts():
    """D-108-4. Nothing is derived: the tag and the flag are the car's.

    Four cars of one week, model and colour: two Box, one No box and one
    with no tag at all (a plant list that names no stop), one of them
    incomplete. The card says 4 cars, 2 / 1, one incomplete, and the
    readings of all four -- never 4 - 2 - 1 = 1 for the untagged one.
    """
    [week] = film_history.summarize([
        car(2, vid="1" * 64, readings=10),
        car(3, vid="2" * 64, readings=20),
        car(4, vid="3" * 64, readings=30, box="no_box"),
        car(5, vid="4" * 64, readings=40, box=None, incomplete=True),
    ])
    [card] = week.cards
    assert (card.model, card.color) == (RANGER, COLOUR)
    assert card.vehicle_count == 4
    assert card.point_count == 100, "readings, summed from the cars"
    assert (card.box_count, card.no_box_count) == (2, 1)
    assert card.incomplete_count == 1
    assert card.box_count + card.no_box_count < card.vehicle_count, (
        "a car whose list names no stop is in neither count"
    )
    assert (card.measured_date_min, card.measured_date_max) == (
        date(2024, 3, 2), date(2024, 3, 5),
    )
    assert week.measured_date_min == card.measured_date_min
    assert week.measured_date_max == card.measured_date_max


def test_one_week_splits_by_model_and_by_colour():
    [week] = film_history.summarize([
        car(2, vid="1" * 64),
        car(2, vid="2" * 64, model=SGL, display="Single CAP"),
        car(2, vid="3" * 64, color="Absolute / Shadow Black"),
    ])
    assert [(c.model, c.color, c.vehicle_count) for c in week.cards] == [
        (RANGER, "Absolute / Shadow Black", 1),
        (RANGER, COLOUR, 1),
        (SGL, COLOUR, 1),
    ]
    assert [c.model_display_name for c in week.cards] == [None, None, "Single CAP"]


def test_one_car_counted_once_however_many_loads_measured_it():
    """A Cab file and a Box file of one car are one car (T46)."""
    [week] = film_history.summarize([
        car(2, vid="1" * 64, readings=58), car(2, vid="1" * 64, readings=40),
    ])
    [card] = week.cards
    assert card.vehicle_count == 1
    assert card.point_count == 98, "both loads' readings are the car's readings"


def test_no_cars_is_an_empty_list_not_a_zero_week():
    assert film_history.summarize([]) == []


# =====================================================================
# 5. the contract
# =====================================================================
def test_the_route_is_in_both_openapi_copies_identically():
    backend = json.loads(BACKEND_SPEC.read_text(encoding="utf-8"))
    docs = json.loads(DOCS_SPEC.read_text(encoding="utf-8"))
    assert backend == docs, "the two artifacts must not drift (T23 claim)"
    assert ROUTE in backend["paths"]
    assert set(backend["paths"][ROUTE]) == {"get"}, "History reads, never writes"
    card = backend["components"]["schemas"]["FilmCardOut"]["properties"]
    assert {"box_count", "no_box_count", "incomplete_count"} <= set(card)
    assert "FilmWeekOut" in backend["components"]["schemas"]
    assert "FilmSummariesOut" in backend["components"]["schemas"]


# =====================================================================
# 3 + 4. the live reads agree, filters and all
# =====================================================================
@pytest.mark.ingest
def test_the_cards_of_a_month_are_the_cars_of_that_month(
    engineer, admin, viewer, admin_conn, film_cleanup  # noqa: F811
):
    """Five synthetic cars across three weeks, then two reads compared.

    The claim is not "these numbers": it is that **one** read cannot say
    something the other denies. So every card is checked against the cars
    the vehicles read publishes for the same month -- including the Box /
    No box tag of a truck that stopped at `064RAPILLAR` (D-99-8) and the
    incomplete flag of one that stopped one point later.
    """
    ranger = walk_of(admin_conn, RANGER)
    sgl = walk_of(admin_conn, SGL)
    plan = [
        # (date as the PELT header writes it, model, body of the walk)
        ("03-Mar-24", RANGER, ranger),
        ("05-Mar-24", RANGER, ranger),
        ("17-Mar-24", RANGER, ranger[: ranger.index("064RAPILLAR") + 1]),
        ("18-Mar-24", RANGER, ranger[: ranger.index("065LBOXSIDE") + 1]),
        ("20-Mar-24", SGL, sgl),
    ]
    for day, model, body in plan:
        name, job = job_name("DBL" if model == RANGER else "SGL")
        review = sent(
            engineer, film_cleanup, admin_conn, name,
            pelt([*body, *TAIL], colour=COLOUR, day=day, job=job), PLANT,
        )["Quick Summary"]
        commit(engineer, admin, review)

    cars = viewer.get(VEHICLES, params={"month": MONTH, "limit": 200})
    assert cars.status_code == 200, cars.text
    items = cars.json()["items"]
    assert len(items) == len(plan), "the test's own cars are the month's cars"

    summaries = viewer.get(SUMMARIES, params={"month": MONTH})
    assert summaries.status_code == 200, summaries.text
    body = summaries.json()
    assert (body["plant_code"], body["month"]) == (PLANT, MONTH)
    assert (body["model"], body["color"]) == (None, None)
    assert body["plant_is_active"] is True
    assert body["active_data_source"] == "filmthickness_active"

    # The cards, folded again here from the other read's own items.
    expected: dict[tuple[int, str, str], list[dict]] = {}
    for item in items:
        measured = date.fromisoformat(item["measured_date"])
        expected.setdefault(
            (measured_week(measured.day), item["model"], item["color"]), []
        ).append(item)
    assert [w["week"] for w in body["weeks"]] == sorted(
        {key[0] for key in expected}, reverse=True
    )
    assert sum(
        card["vehicle_count"] for week in body["weeks"] for card in week["cards"]
    ) == len(items)

    for week in body["weeks"]:
        for card in week["cards"]:
            mine = expected[(week["week"], card["model"], card["color"])]
            assert card["vehicle_count"] == len(mine)
            assert card["box_count"] == sum(1 for c in mine if c["box"] == "box")
            assert card["no_box_count"] == sum(1 for c in mine if c["box"] == "no_box")
            assert card["incomplete_count"] == sum(1 for c in mine if c["incomplete"])
            days = sorted(c["measured_date"] for c in mine)
            assert card["measured_date_min"] == days[0]
            assert card["measured_date_max"] == days[-1]
            assert card["model_display_name"] == mine[0]["model_display_name"]
            # The card click: the same cars, from the server's own week.
            behind = viewer.get(VEHICLES, params={
                "month": MONTH, "week": week["week"],
                "model": card["model"], "color": card["color"], "limit": 200,
            })
            assert behind.status_code == 200, behind.text
            page = behind.json()
            assert page["week"] == week["week"], "the page echoes the band"
            assert page["page"]["total"] == card["vehicle_count"]
            assert {c["logical_vehicle_id"] for c in page["items"]} == {
                c["logical_vehicle_id"] for c in mine
            }
            # `point_count` is readings: four layers of every mapped point of
            # every car on the card, which is what the grid of each car holds.
            readings = 0
            for one in mine:
                points = viewer.get(
                    f"{VEHICLES}/{one['logical_vehicle_id']}/points"
                )
                assert points.status_code == 200, points.text
                readings += sum(
                    1 for point in points.json()["items"]
                    for layer in ("ecoat", "primer", "base", "clear")
                    if point["layers"][layer] is not None
                )
            assert card["point_count"] == readings
        assert week["measured_date_min"] == min(
            card["measured_date_min"] for card in week["cards"]
        )
        assert week["measured_date_max"] == max(
            card["measured_date_max"] for card in week["cards"]
        )

    # The two trucks that stopped early are the T99 / T103 facts, not a grade.
    tags = {(c["measured_date"], c["box"], c["incomplete"]) for c in items}
    assert ("2024-03-17", "no_box", False) in tags, "stopped at a complete stop"
    assert ("2024-03-18", "box", True) in tags, "one point past it"

    # 4. the filters are passed through.
    only_sgl = viewer.get(SUMMARIES, params={"month": MONTH, "model": SGL})
    assert only_sgl.status_code == 200, only_sgl.text
    narrowed = only_sgl.json()
    assert narrowed["model"] == SGL
    assert {
        card["model"] for week in narrowed["weeks"] for card in week["cards"]
    } == {SGL}
    assert [week["week"] for week in narrowed["weeks"]] == [3]

    missing = viewer.get(SUMMARIES, params={"month": MONTH, "color": "No Such Colour"})
    assert missing.status_code == 200, missing.text
    assert missing.json()["weeks"] == [], "an empty state, not a zero KPI"

    # The month read is unchanged by T108: no week, no narrowing.
    whole = viewer.get(VEHICLES, params={"month": MONTH, "limit": 200})
    assert whole.status_code == 200, whole.text
    assert whole.json()["week"] is None
    assert whole.json()["page"]["total"] == len(plan)
    assert viewer.get(
        VEHICLES, params={"month": MONTH, "week": 9}
    ).status_code == 422, "a week outside the bands is refused by the route"


def test_an_unknown_plant_is_a_404_and_a_month_with_no_film_is_empty(
    viewer,  # noqa: F811
):
    unknown = viewer.get(
        "/api/v1/plants/NOPE/filmthickness/summaries", params={"month": MONTH}
    )
    assert unknown.status_code == 404, unknown.text
    empty = viewer.get(SUMMARIES, params={"month": "1999-01"})
    assert empty.status_code == 200, empty.text
    assert empty.json()["weeks"] == []
