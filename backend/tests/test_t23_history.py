"""T23 -- Measurement History: facets, week summaries, vehicle sets, points.

Five claims:

* **The pick lists are API fields.** Months, then models in a month, then
  colours in that model. A client never folds `GET /measurements` to build
  them, and a colour without a month is refused rather than guessed.
* **The numbers agree with `GET /measurements`.** Summing a month's cards --
  and one week's cards -- gives the same total as the measurement list for
  the same plant, month, model and colour. If they ever disagree, one of the
  two is reading something the other is not, which is the defect this whole
  slice exists to avoid.
* **A History vehicle is a T21 vehicle.** Same hash, `load_id` included, so
  two serials are two cards and two sheets that measured the same serial on
  the same day stay two cards.
* **History is active facts only.** A review row that never committed, and a
  set whose batch was retired, are 404 here; a superseded sheet's rows never
  reach a card.
* **History is readable by any authenticated role**, while the workbook
  manager stays Admin.

Runs through T04's fixtures against the real application, worker and
database, like T19 and T21.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app.domain.history import (
    measured_week,
    month_date_bounds,
    summarize,
    week_date_bounds,
)
from app.domain import history as history_rules
from app.domain.workbooks import vehicle_id
from tests.test_t04_ingest import (
    acknowledge_required,
    make_workbook,
    unique_rows,
)
from tests.test_t19_data_manager import base, ingest_as

# Fixtures, in scope by being in the module namespace (as T08, T17-T21 do).
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)
from tests.test_t19_data_manager import anon  # noqa: F401

pytestmark = pytest.mark.ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

ABSENT_VEHICLE = "0" * 64


# =====================================================================
# helpers
# =====================================================================
def history(plant: str) -> str:
    return f"/api/v1/plants/{plant}/history"


def facets_of(client, plant: str, **params) -> dict:
    response = client.get(f"{history(plant)}/facets", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def summaries_of(client, plant: str, **params) -> dict:
    response = client.get(f"{history(plant)}/summaries", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def vehicles_of(client, plant: str, **params) -> dict:
    response = client.get(f"{history(plant)}/vehicles", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def points_of(client, plant: str, vid: str, **params) -> dict:
    response = client.get(f"{history(plant)}/vehicles/{vid}/points", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def measurements_total(client, **params) -> int:
    response = client.get("/api/v1/measurements", params={"limit": 1, **params})
    assert response.status_code == 200, response.text
    return response.json()["page"]["total"]


def commit(engineer_client, admin_client, review: dict) -> int:
    """Acknowledge whatever this parse made mandatory, then commit."""
    acknowledge_required(admin_client, review)
    load_id = review["batch"]["load_id"]
    response = engineer_client.post(f"/api/v1/batches/{load_id}/commit")
    assert response.status_code == 200, response.text
    return load_id


def committed_rows(engineer_client, admin_client, cleanup, name: str, rows: list[dict]) -> int:
    data = make_workbook(rows)
    review = ingest_as(engineer_client, cleanup, name, data)
    return commit(engineer_client, admin_client, review)


def canonical(client, load_id: int) -> tuple[str, str]:
    """The model and colour this sheet's rows were cleaned to.

    The workbook says "3HC Traction Green" and the alias table canonicalises
    it; History reports what `wavescan` holds, so a test asks the
    measurement list rather than hardcoding either spelling.
    """
    response = client.get("/api/v1/measurements", params={"load_id": load_id, "limit": 1})
    assert response.status_code == 200, response.text
    row = response.json()["items"][0]
    return row["model"], row["color"]


def cards_of(body: dict) -> list[dict]:
    return [card for week in body["weeks"] for card in week["cards"]]


# =====================================================================
# 1. pure rules
# =====================================================================
@pytest.mark.parametrize(
    "day,week",
    [(1, 1), (7, 1), (8, 2), (14, 2), (15, 3), (21, 3), (22, 4), (28, 4),
     (29, 5), (30, 5), (31, 5)],
)
def test_the_week_bands(day, week):
    assert measured_week(day) == week


@pytest.mark.parametrize("day", [0, 32, -1, "3", 1.5, True])
def test_a_day_that_is_not_a_day_raises(day):
    with pytest.raises(ValueError):
        measured_week(day)


def test_month_bounds_end_on_the_month_own_last_day():
    assert month_date_bounds("2026-07") == (date(2026, 7, 1), date(2026, 7, 31))
    assert month_date_bounds("2026-06") == (date(2026, 6, 1), date(2026, 6, 30))
    assert month_date_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_date_bounds("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
    for bad in ("2026-13", "2026-9", "Sept", "", "2026-00"):
        with pytest.raises(ValueError):
            month_date_bounds(bad)


def test_week_five_covers_day_31_and_a_short_february_has_none():
    assert week_date_bounds("2026-07", 5) == (date(2026, 7, 29), date(2026, 7, 31))
    assert week_date_bounds("2026-06", 5) == (date(2026, 6, 29), date(2026, 6, 30))
    assert week_date_bounds("2026-02", 4) == (date(2026, 2, 22), date(2026, 2, 28))
    with pytest.raises(ValueError):
        week_date_bounds("2026-02", 5)


def _code_only(path: Path) -> str:
    """Source with comments and docstrings removed.

    The prose in these modules deliberately says "never a literal 32" and
    names the view History must not read; what the checks below are about is
    what the code does.
    """
    import ast

    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    kept = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        kept.append(line)
    body = "\n".join(kept)
    for doc in docstrings:
        body = body.replace(doc, "")
    return body


def test_the_history_domain_has_no_literal_expected_count_and_no_framework():
    path = BACKEND_ROOT / "app" / "domain" / "history.py"
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])32(?![\w.])", _code_only(path)), (
        "a hardcoded 32 is a defect"
    )
    for banned in ("import fastapi", "from fastapi", "import psycopg", "from psycopg",
                   "import sqlalchemy", "from sqlalchemy"):
        assert banned not in source


def test_the_history_repository_never_restates_the_active_predicate():
    """Same rule as `repositories/measurements.py`: the predicate lives in
    the view, so its column and status names appear nowhere in Python."""
    statements = _code_only(BACKEND_ROOT / "app" / "repositories" / "history.py")
    for banned in ("is_duplicate", "is_superseded"):
        assert banned not in statements
    assert "FROM wavescan" not in statements, "History reads the active view only"
    assert "v_vehicle_completeness" not in statements


def test_summaries_are_week_descending_with_stable_cards():
    def vehicle(day, model, color, serial, rows, load_id=1):
        return history_rules.HistoryVehicle(
            vehicle_id=f"{load_id}-{serial}-{day}",
            load_id=load_id,
            measured_date=date(2026, 7, day),
            model=model, color=color, serial_no=serial,
            identity_complete=True, point_count=rows,
            expected_point_count=None, incomplete_set=False,
            source_file="f.xlsx", source_sheet="PasteData",
            week=measured_week(day), row_count=rows,
        )

    weeks = summarize([
        vehicle(2, "U704", "Green", "A", 3),
        vehicle(3, "U704", "Green", "B", 2),
        vehicle(9, "U704", "Blue", "C", 4),
        vehicle(9, "J73 DBL", "Blue", "D", 1),
    ])
    assert [w["week"] if isinstance(w, dict) else w.week for w in weeks] == [2, 1]
    assert [(c.model, c.color, c.vehicle_count, c.point_count) for c in weeks[1].cards] == [
        ("U704", "Green", 2, 5)
    ]
    assert [(c.model, c.color) for c in weeks[0].cards] == [("J73 DBL", "Blue"), ("U704", "Blue")]
    assert weeks[1].measured_date_min == date(2026, 7, 2)
    assert weeks[1].measured_date_max == date(2026, 7, 3)


# =====================================================================
# 2. facets
# =====================================================================
def test_facets_cascade_month_then_model_then_colour(engineer, admin, viewer, cleanup):
    rows = unique_rows(3)
    for row in rows:
        row["Date"] = "2026-07-09"
    load_id = committed_rows(engineer, admin, cleanup, "t23-facets.xlsx", rows)
    model_code, color_name = canonical(viewer, load_id)

    body = facets_of(viewer, "AAT")
    assert body["plant_code"] == "AAT"
    assert body["plant_is_active"] is True
    assert body["active_data_source"] == "v_wavescan_active"
    assert body["months"] == sorted(body["months"], reverse=True)
    assert "2026-07" in body["months"]
    assert body["default_month"] == body["months"][0]
    assert body["month"] is None
    assert body["models"] == [] and body["colors"] == [], (
        "nothing to cascade from without a month"
    )

    month = facets_of(viewer, "AAT", month="2026-07")
    assert month["month"] == "2026-07"
    assert model_code in month["models"]
    assert month["models"] == sorted(month["models"])
    assert month["colors"] == sorted(month["colors"])
    assert color_name in month["colors"]

    narrowed = facets_of(viewer, "AAT", month="2026-07", model=model_code)
    assert narrowed["model"] == model_code
    assert set(narrowed["colors"]) <= set(month["colors"])
    assert color_name in narrowed["colors"]

    # Aliases and case resolve like every other plant URL.
    assert facets_of(viewer, "aat")["plant_code"] == "AAT"


def test_facet_refusals_and_empty_plants(viewer, admin_conn):
    assert viewer.get(f"{history('NOWHERE')}/facets").status_code == 404
    for params in ({"month": "2026-13"}, {"month": "2026-9"}, {"month": "Sept"},
                   {"color": "Traction Green"}):
        response = viewer.get(f"{history('AAT')}/facets", params=params)
        assert response.status_code == 422, (params, response.text)

    with admin_conn.cursor() as cur:
        cur.execute("SELECT plant_code FROM ref_plant WHERE NOT is_active LIMIT 1")
        row = cur.fetchone()
    if row is None:
        pytest.skip("no inactive plant to exercise this")
    body = facets_of(viewer, row[0])
    assert body["plant_is_active"] is False
    assert body["months"] == [] and body["default_month"] is None
    assert body["models"] == [] and body["colors"] == []
    assert summaries_of(viewer, row[0], month="2026-07")["weeks"] == []


# =====================================================================
# 3. summaries agree with GET /measurements
# =====================================================================
def test_summary_counts_match_the_measurement_list(engineer, admin, viewer, cleanup):
    rows = unique_rows(3)
    for index, row in enumerate(rows):
        row["Date"] = f"2026-07-0{index + 1}"
    committed_rows(engineer, admin, cleanup, "t23-agree.xlsx", rows)

    month = "2026-07"
    first, last = month_date_bounds(month)
    body = summaries_of(viewer, "AAT", month=month)
    assert body["month"] == month
    assert body["active_data_source"] == "v_wavescan_active"
    assert [w["week"] for w in body["weeks"]] == sorted(
        [w["week"] for w in body["weeks"]], reverse=True
    ), "weeks descending"

    total = sum(card["point_count"] for card in cards_of(body))
    assert total == measurements_total(
        viewer, plant="AAT", date_from=first.isoformat(), date_to=last.isoformat()
    )

    # One week, using that week's own bounds.
    week = body["weeks"][-1]
    week_first, week_last = week_date_bounds(month, week["week"])
    week_total = sum(card["point_count"] for card in week["cards"])
    assert week_total == measurements_total(
        viewer, plant="AAT",
        date_from=week_first.isoformat(), date_to=week_last.isoformat(),
    )
    assert week["measured_date_min"] >= week_first.isoformat()
    assert week["measured_date_max"] <= week_last.isoformat()

    # One card: plant + month + model + colour.
    card = cards_of(body)[0]
    filtered = summaries_of(
        viewer, "AAT", month=month, model=card["model"], color=card["color"]
    )
    assert filtered["model"] == card["model"] and filtered["color"] == card["color"]
    assert sum(c["point_count"] for c in cards_of(filtered)) == measurements_total(
        viewer, plant="AAT", model=card["model"], color=card["color"],
        date_from=first.isoformat(), date_to=last.isoformat(),
    )
    assert all(c["model"] == card["model"] for c in cards_of(filtered))


def test_a_month_with_no_matching_rows_is_an_empty_state(viewer):
    body = summaries_of(viewer, "AAT", month="2001-01")
    assert body["weeks"] == []
    assert summaries_of(viewer, "AAT", month="2026-07", model="NOSUCHMODEL")["weeks"] == []


def test_summaries_need_a_valid_month(viewer):
    assert viewer.get(f"{history('AAT')}/summaries").status_code == 422
    assert viewer.get(
        f"{history('AAT')}/summaries", params={"month": "2026-13"}
    ).status_code == 422


def test_week_five_includes_day_31(engineer, admin, viewer, cleanup):
    rows = unique_rows(2)
    for row in rows:
        row["Date"] = "2026-07-31"
    committed_rows(engineer, admin, cleanup, "t23-week5.xlsx", rows)

    body = summaries_of(viewer, "AAT", month="2026-07")
    week_five = [w for w in body["weeks"] if w["week"] == 5]
    assert week_five, "day 31 is week 5"
    assert week_five[0]["measured_date_max"] == "2026-07-31"


# =====================================================================
# 4. vehicle sets
# =====================================================================
def test_two_serials_are_two_vehicles_and_two_sheets_never_merge(
    engineer, admin, viewer, cleanup, admin_conn
):
    """The T21 key, including `load_id`: the same serial measured again on
    the same day by another sheet is another vehicle, not a merged card."""
    day = "2026-07-15"
    serial = f"T23-{uuid.uuid4().hex[:10]}"
    zones = ["01 RRHOOD", "02 RFHOOD"]

    first = [{"Serial No": serial, "Checkzone": z, "Date": day, "CF": 60.0 + i}
             for i, z in enumerate(zones)]
    other_serial = f"T23-{uuid.uuid4().hex[:10]}"
    second = [{"Serial No": other_serial, "Checkzone": z, "Date": day, "CF": 61.0 + i}
              for i, z in enumerate(zones)]
    load_a = committed_rows(engineer, admin, cleanup, "t23-two-a.xlsx", first + second)

    # The same vehicle again, in its own workbook: a genuine re-measurement.
    # Every measure differs, so cross-file dedup keeps it (a sheet that only
    # moved CF would match the first one and be flagged DUPLICATE, which is
    # the guard working and not what this test is about).
    measures = {"LW": 9.1, "SW": 24.3, "DOI": 71.4, "du": 27.8, "Wa": 22.2,
                "Wb": 31.9, "Wc": 20.4, "Wd": 25.1, "We": 16.3, "B": 3.9}
    again = [{"Serial No": serial, "Checkzone": z, "Date": day, "CF": 70.0 + i,
              **measures}
             for i, z in enumerate(zones)]
    load_b = committed_rows(engineer, admin, cleanup, "t23-two-b.xlsx", again)
    assert load_a != load_b
    model_code, color = canonical(viewer, load_a)

    page = vehicles_of(viewer, "AAT", month="2026-07", week=3, model=model_code, color=color)
    mine = [v for v in page["items"] if v["serial_no"] in (serial, other_serial)]
    assert len({v["vehicle_id"] for v in mine}) == 3, "two serials, and two sheets"
    assert {v["serial_no"] for v in mine} == {serial, other_serial}
    assert {v["load_id"] for v in mine} == {load_a, load_b}

    for item in mine:
        assert item["vehicle_id"] == vehicle_id(
            item["load_id"],
            (item["measured_date"], item["model"], item["color"], item["serial_no"]),
        )
        assert item["plant_code"] == "AAT"
        assert item["week"] == 3
        assert item["source_file"].startswith("t23-two-")
        assert item["source_sheet"] == "PasteData"
        assert item["identity_complete"] is True
        assert item["point_count"] == 2

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT expected_zone_count FROM ref_model WHERE model_code = %s",
            (model_code,),
        )
        expected = cur.fetchone()[0]
    assert mine[0]["expected_point_count"] == expected
    assert mine[0]["incomplete_set"] is (mine[0]["point_count"] != expected)

    # The card counts vehicles, not serials.
    body = summaries_of(viewer, "AAT", month="2026-07", model=model_code, color=color)
    week_three = [w for w in body["weeks"] if w["week"] == 3][0]
    card = [c for c in week_three["cards"] if c["model"] == model_code][0]
    assert card["vehicle_count"] >= 3
    assert card["point_count"] >= 6


def test_vehicles_need_one_card_and_paginate(engineer, admin, viewer, cleanup):
    rows = unique_rows(2)
    for row in rows:
        row["Date"] = "2026-07-09"
    load_id = committed_rows(engineer, admin, cleanup, "t23-page.xlsx", rows)
    model_code, color_name = canonical(viewer, load_id)

    params = {"month": "2026-07", "week": 2, "model": model_code, "color": color_name}
    page = vehicles_of(viewer, "AAT", **params)
    assert page["page"]["total"] >= 1
    assert page["week"] == 2 and page["model"] == "U704"
    walked = []
    for offset in range(page["page"]["total"]):
        one = vehicles_of(viewer, "AAT", **params, limit=1, offset=offset)
        walked.append(one["items"][0]["vehicle_id"])
    assert walked == [v["vehicle_id"] for v in page["items"]]

    for missing in ({"month": "2026-07", "week": 2, "model": model_code},
                    {"month": "2026-07", "week": 2, "color": color_name},
                    {"month": "2026-07", "model": model_code, "color": color_name},
                    {"week": 2, "model": model_code, "color": color_name}):
        assert viewer.get(f"{history('AAT')}/vehicles", params=missing).status_code == 422
    # RO18 (B4): week 0 is the "day not recorded" group, so -1 is the low bad one.
    for bad_week in (-1, 6, "x"):
        assert viewer.get(
            f"{history('AAT')}/vehicles",
            params={"month": "2026-07", "week": bad_week, "model": model_code,
                    "color": color_name},
        ).status_code == 422


# =====================================================================
# 5. points
# =====================================================================
def test_points_carry_the_measurement_id_and_match_the_measurement_read(
    engineer, admin, viewer, cleanup
):
    rows = unique_rows(3)
    for row in rows:
        row["Date"] = "2026-07-16"
    load_id = committed_rows(engineer, admin, cleanup, "t23-points.xlsx", rows)
    model_code, color_name = canonical(viewer, load_id)

    page = vehicles_of(
        viewer, "AAT", month="2026-07", week=3, model=model_code, color=color_name
    )
    vehicle = [v for v in page["items"] if v["load_id"] == load_id][0]
    body = points_of(viewer, "AAT", vehicle["vehicle_id"])

    assert body["vehicle"]["vehicle_id"] == vehicle["vehicle_id"]
    assert body["vehicle"]["expected_point_count"] == vehicle["expected_point_count"]
    assert body["page"]["total"] == 3
    assert body["active_data_source"] == "v_wavescan_active"
    zones = [p["checkzone"] for p in body["items"]]
    assert zones == sorted(zones), "ordered by checkzone"

    point = body["items"][0]
    assert point["measurement_id"], "T09 Correct needs it"
    assert point["load_id"] == load_id
    assert point["source_file"] == "t23-points.xlsx"
    assert point["source_sheet"] and point["source_row"]
    assert point["serial_no"] == vehicle["serial_no"]
    for absent in ("disposition", "raw", "proposed", "current_overrides"):
        assert absent not in point, "History points are facts, not a review"

    one = viewer.get(f"/api/v1/measurements/{point['measurement_id']}")
    assert one.status_code == 200, one.text
    measurement = one.json()
    for field in ("cf", "lw", "sw", "doi", "du", "wa", "wb", "wc", "wd", "we", "b",
                  "checkzone", "model", "color", "serial_no", "tolerance_group",
                  "paintline", "measured_date", "loaded_at",
                  "corrects_measurement_id", "correction_reason"):
        assert point[field] == measurement[field], field


def test_an_unknown_or_foreign_vehicle_is_404(engineer, admin, viewer, cleanup):
    assert viewer.get(
        f"{history('AAT')}/vehicles/{ABSENT_VEHICLE}/points"
    ).status_code == 404
    assert viewer.get(f"{history('AAT')}/vehicles/xyz/points").status_code == 422

    # T76 CHANGE (D2 / T55 / T58): an FTM-offered identity, not relabelled
    # AAT rows (which FTM rejects whole).
    ftm_rows = unique_rows(2, Plant="FTM", Date="2026-07-16")
    ftm = ingest_as(engineer, cleanup, "t23-ftm.xlsx", make_workbook(ftm_rows), "FTM")
    ftm_load = commit(engineer, admin, ftm)
    ftm_model, ftm_color = canonical(viewer, ftm_load)
    ftm_page = vehicles_of(
        viewer, "FTM", month="2026-07", week=3, model=ftm_model, color=ftm_color
    )
    ftm_vehicle = [v for v in ftm_page["items"] if v["load_id"] == ftm_load][0]
    assert points_of(viewer, "FTM", ftm_vehicle["vehicle_id"])["page"]["total"] == 2
    assert viewer.get(
        f"{history('AAT')}/vehicles/{ftm_vehicle['vehicle_id']}/points"
    ).status_code == 404, "another plant's set does not leak"


def test_a_review_only_set_and_a_retired_one_are_not_history(
    engineer, admin, viewer, cleanup
):
    """History is active facts. A sheet in review has none yet, and a
    superseded sheet's rows stop being current -- both are 404 here while
    the workbook drill-down still shows them (T19 locked decision 8)."""
    pending = ingest_as(
        engineer, cleanup, "t23-pending.xlsx",
        make_workbook(unique_rows(2, **{"Date": "2026-07-23"})),
    )
    batch = pending["batch"]
    review_vehicles = admin.get(
        f"{base('AAT')}/{batch['file_hash']}/vehicles",
        params={"load_id": batch["load_id"]},
    )
    assert review_vehicles.status_code == 200, review_vehicles.text
    review_id = [
        v for v in review_vehicles.json()["items"] if v["identity_complete"]
    ][0]["vehicle_id"]
    assert viewer.get(
        f"{history('AAT')}/vehicles/{review_id}/points"
    ).status_code == 404, "a proposal is not a measurement"

    # Commit it, read it, then retire it.
    load_id = commit(engineer, admin, pending)
    assert points_of(viewer, "AAT", review_id)["page"]["total"] == 2, (
        "the same id, now that the sheet has committed"
    )
    before = summaries_of(viewer, "AAT", month="2026-07")
    assert admin.post(
        f"/api/v1/batches/{load_id}/supersede",
        json={"reason": "T23: retired so History can be checked."},
    ).status_code == 200

    assert viewer.get(
        f"{history('AAT')}/vehicles/{review_id}/points"
    ).status_code == 404, "a retired batch is not current"
    after = summaries_of(viewer, "AAT", month="2026-07")
    assert sum(c["point_count"] for c in cards_of(after)) == sum(
        c["point_count"] for c in cards_of(before)
    ) - 2


# =====================================================================
# 6. RBAC and the contract
# =====================================================================
def test_history_is_readable_by_every_authenticated_role(engineer, admin, viewer, cleanup):
    rows = unique_rows(2)
    for row in rows:
        row["Date"] = "2026-07-02"
    load_id = committed_rows(engineer, admin, cleanup, "t23-rbac.xlsx", rows)
    model_code, color_name = canonical(viewer, load_id)
    page = vehicles_of(
        viewer, "AAT", month="2026-07", week=1, model=model_code, color=color_name
    )
    vid = [v for v in page["items"] if v["load_id"] == load_id][0]["vehicle_id"]
    listed = urlencode({"month": "2026-07", "week": 1, "model": model_code,
                        "color": color_name})
    paths = [
        f"{history('AAT')}/facets",
        f"{history('AAT')}/summaries?month=2026-07",
        f"{history('AAT')}/vehicles?{listed}",
        f"{history('AAT')}/vehicles/{vid}/points",
    ]
    for client in (viewer, engineer, admin):
        for path in paths:
            assert client.get(path).status_code == 200, path


def test_an_unauthenticated_caller_is_refused_every_history_route(anon):
    for path in (
        f"{history('AAT')}/facets",
        f"{history('AAT')}/summaries?month=2026-07",
        f"{history('AAT')}/vehicles?month=2026-07&week=1&model=U704&color=Green",
        f"{history('AAT')}/vehicles/{ABSENT_VEHICLE}/points",
    ):
        assert anon.get(path).status_code == 401, path


def test_the_workbook_manager_is_engineer_not_viewer(engineer, viewer, cleanup):
    # RO12 CHANGE (owner, 2026-10-13): was `..._is_still_admin_only` (Engineer
    # 403). The manager reads are Engineer now; a Viewer, who reads History,
    # is still refused them, so the two routers still answer differently.
    review = ingest_as(engineer, cleanup, "t23-admin.xlsx", make_workbook(unique_rows(2)))
    file_hash = review["batch"]["file_hash"]
    for client, expected in ((engineer, 200), (viewer, 403)):
        assert client.get(f"{base('AAT')}/{file_hash}").status_code == expected
        assert client.get(
            f"{base('AAT')}/{file_hash}/vehicles",
            params={"load_id": review["batch"]["load_id"]},
        ).status_code == expected


def test_the_contract_has_the_history_paths_and_both_artifacts_match(viewer):
    import json

    spec = viewer.get("/openapi.json").json()
    # T25 CHANGE: 31 -> 32 (POST /batches/{load_id}/restore). The four
    # History reads below are unchanged.
    # T26 CHANGE: 32 -> 33 (POST /plants/{plant_code}/template-profiles/publish).
    # T-STANDARDS-D2 CHANGE: 33 -> 38.
    # Monthly Overview CHANGE: 38 -> 39.
    # T37 CHANGE: 39 -> 40 (POST /plants/{plant_code}/workbooks/{file_hash}/purge).
    # T39 CHANGE: 40 -> 46 (worksheet GET + five Engineer POSTs).
    # T48 CHANGE: 46 -> 49 (three FilmThickness GETs).
    # T62 CHANGE: 49 -> 51 (FilmThickness standards GET + Admin POST).
    # T66 CHANGE: 51 -> 52 (FilmThickness monthly overview GET).
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(spec["paths"]) >= 52, sorted(spec["paths"])
    root = "/api/v1/plants/{plant_code}/history"
    for path in (f"{root}/facets", f"{root}/summaries", f"{root}/vehicles",
                 f"{root}/vehicles/{{vehicle_id}}/points"):
        assert set(spec["paths"][path]) == {"get"}, path
    for forbidden in (f"{root}/weeks", "/api/v1/audit", "commit-all"):
        assert not any(forbidden in p for p in spec["paths"])

    # GET /measurements is untouched by this slice.
    measurements = spec["paths"]["/api/v1/measurements"]["get"]
    assert {p["name"] for p in measurements["parameters"]} == {
        "plant", "model", "color", "checkzone", "date_from", "date_to", "load_id",
        "limit", "offset",
    }
    schemas = spec["components"]["schemas"]
    assert set(schemas["CorrectionCreate"]["properties"]) >= {"reason", "cf"}
    for name in ("HistoryFacetsOut", "HistorySummariesOut", "HistoryVehiclePage",
                 "HistoryPointPage"):
        assert name in schemas
    assert "measurement_id" in schemas["HistoryPointOut"]["required"]
    for absent in ("disposition", "current_overrides", "raw", "proposed"):
        assert absent not in schemas["HistoryPointOut"]["properties"]

    backend = (BACKEND_ROOT / "openapi.json").read_bytes()
    docs = (REPO_ROOT / "docs" / "openapi.json").read_bytes()
    assert backend == docs
    assert json.loads(backend)["paths"].keys() == spec["paths"].keys()


#: Files T23 created. Every line is checked.
T23_NEW_FILES = (
    "backend/app/domain/history.py",
    "backend/app/repositories/history.py",
    "backend/app/services/history.py",
    "backend/app/schemas/history.py",
    "backend/app/api/v1/history.py",
    "backend/tests/test_t23_history.py",
    "docs/reports/T23-HISTORY-SUMMARIES.md",
)

#: Files T23 edited. Only the lines it adds are checked, because several
#: already carried a section sign or an arrow from earlier tasks.
T23_EDITED_FILES = (
    "backend/app/api/v1/__init__.py",
    "backend/tests/test_t03_contract.py",
    "backend/tests/test_t19_data_manager.py",
    "backend/tests/test_t21_upload_review.py",
    "docs/01-DATA-MODEL.md",
    "docs/02-PIPELINE.md",
    "docs/03-SECURITY.md",
)


def _committed_lines(relative: str) -> set[str] | None:
    import subprocess

    try:
        shown = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=REPO_ROOT,
            capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return set(shown.stdout.decode("utf-8", "replace").splitlines())


def test_lines_this_task_adds_are_ascii():
    offenders = []
    for relative in T23_NEW_FILES + T23_EDITED_FILES:
        path = REPO_ROOT / relative
        if not path.exists():
            continue
        before = set() if relative in T23_NEW_FILES else _committed_lines(relative)
        if before is None:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line in before:
                continue
            if any(ord(ch) > 127 for ch in line):
                offenders.append(f"{relative}:{number}")
    assert not offenders, offenders
