"""T68 -- Film Overview: measured_date on out-of-spec readings.

Claims (task "Tests"):

1. Contract: ``FilmOutOfSpecPoint`` gains ``measured_date`` (date, nullable);
   its other properties are unchanged; 52 paths; copies byte-identical and
   equal to the live app.
2. Authoritative date: every entry's ``measured_date`` equals the date of the
   fact row matched independently in SQL by (vehicle, point, layer, value),
   compared as multisets (duplicates count).
3. Nothing else moved: the T67 contract re-derived from the facts -- entry
   counts and (side, value, point_code, logical_vehicle_id) sequences, and
   every box field (statistics, spec, status, labels, family, order).
4. Synthetic: two cars on two different days of one month, each with an
   E-coat reading under Minimum; each LOW entry carries its own car's date.
5. ``grading_available`` false; ``film_standard`` and fact counts unchanged
   by the reads; the T05 import guard sees only the two allowed services.

Test safety: the synthetic loads are removed by ``film_cleanup`` (this test's
own load_ids only). Nothing else is written or deleted.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.boxplot import box_stats, model_sort_key
from app.domain.film_overview import line_labels
from app.domain.film_standards import LAYERS
from app.domain.grading import film_box_status
from tests.test_t03_contract import client, make_client  # noqa: F401
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.film_synthetic import film_month, forget_film_month, gold_points
from tests.test_t46_filmthickness import commit, film_cleanup, pelt, sent  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
PATH = "/api/v1/plants/{plant_code}/filmthickness/overview"
REQUESTS = (("AAT", None), ("FTM", None), ("FTM", "2026-05"), ("FVL", None), ("SAP", None))
STAT_KEYS = ("box_min", "q1", "median", "q3", "box_max", "whisker_lo", "whisker_hi", "mean")
T67_ENTRY_KEYS = {"value", "side", "point_code", "logical_vehicle_id"}
T67_BOX_KEYS = {
    "layer_code", "model_code", "color_name", "orient", "n", "vehicles", *STAT_KEYS,
    "outliers", "lo", "hi", "target", "standard_scope", "status", "family_code",
    "family_name", "family_order", "lo_label", "hi_label", "target_label", "out_of_spec",
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def D(x) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def get(c, plant: str, month: str | None = None) -> dict:
    params = {"month": month} if month else {}
    response = c.get(PATH.format(plant_code=plant), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _facts(admin_conn, plant: str, month: str) -> dict[tuple, list[dict]]:
    """(layer, model, colour, H/V) -> fact rows, read independently of the app."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.layer_code, f.model, f.color,
                   COALESCE(btrim(pp.orientation), btrim(mp.orientation)),
                   f.thickness, f.point_code, f.logical_vehicle_id, f.measured_date,
                   cf.family_code, cf.family_name, cf.display_order
              FROM filmthickness_active f
              LEFT JOIN ref_plant_film_point pp
                ON pp.plant_code = f.plant AND pp.model_code = f.model
               AND pp.point_code = f.point_code AND pp.retired_at IS NULL
              LEFT JOIN ref_model_film_point mp
                ON mp.model_code = f.model AND mp.point_code = f.point_code
              LEFT JOIN ref_plant_color pc
                ON pc.plant_code = f.plant AND pc.color_name = f.color
              LEFT JOIN ref_color_family cf ON cf.family_name = pc.family_name
             WHERE f.plant = %s AND f.thickness IS NOT NULL
               AND to_char(f.measured_date, 'YYYY-MM') = %s
            """,
            (plant, month),
        )
        out: dict[tuple, list[dict]] = defaultdict(list)
        for row in cur.fetchall():
            layer, model, color, orient, value, point, car, day, fcode, fname, forder = row
            out[(layer, model, color, orient)].append({
                "value": Decimal(value), "point_code": point, "car": car, "date": day,
                "family": (fcode, fname, forder),
            })
        return out


# =====================================================================
# T85: a month with readings that really are out of spec
# =====================================================================
#: This claim -- "every listed entry carries its own fact row's date" -- can
#: only be made about entries that exist. The owner's Film walks were in
#: T85's Clear list, so `entries > 1000` became `0 > 1000`. The claim is
#: about the read, so the month is built here and the test reads it back.
@pytest.fixture()
def oos_months(admin_conn):  # T85
    """FVL E-coat under its plant-wide Minimum of 20, on two cars.

    Three cars a `car_delta` apart means the listed values have an order to
    assert, and E-coat is the layer whose rule is a plain Minimum, so every
    reading below it must be listed LOW.
    """
    points = gold_points(admin_conn, "FVL", "P703 DBL RANGER")
    assert points, "no live FVL Film points"
    readings = {
        point.point_code: dict(zip(("CLEAR", "BASE", "PRIMER", "ECOAT"),
                                   (40.0, 19.0, 25.0, 17.0)))
        for point in points
    }
    batch = film_month(admin_conn, plant="FVL", model="P703 DBL RANGER",
                       colour="Absolute / Shadow Black", day="2026-08-12",
                       readings=readings, vehicles=3)
    try:
        yield [("FVL", batch["month"])]
    finally:
        forget_film_month(admin_conn, batch)


def _key(b: dict) -> tuple:
    return (b["layer_code"], b["model_code"], b["color_name"], b["orient"])


# ---------------------------------------------------------------- 1
def test_contract_adds_one_nullable_date_property(client):  # noqa: F811
    live = client.app.openapi()
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(live["paths"]) >= 57  # T79 + T81: four Comparison reads; T86: the panel-match read.
    backend_copy = (REPO / "backend" / "openapi.json").read_bytes()
    assert backend_copy == (REPO / "docs" / "openapi.json").read_bytes()
    assert json.loads(backend_copy) == live
    point = live["components"]["schemas"]["FilmOutOfSpecPoint"]
    assert set(point["properties"]) == T67_ENTRY_KEYS | {"measured_date"}
    assert point["properties"]["measured_date"]["anyOf"] == [
        {"type": "string", "format": "date"}, {"type": "null"}]
    assert "from its own fact row" in point["properties"]["measured_date"]["description"]
    # T73 CHANGE: FilmOverviewBox gains color_rank (D-73-13), additive.
    assert set(live["components"]["schemas"]["FilmOverviewBox"]["properties"]) == (
        T67_BOX_KEYS | {"color_rank"})


# ---------------------------------------------------------------- 2
def test_each_entry_date_is_its_own_fact_rows_date(  # T85
    viewer, admin_conn, oos_months,  # noqa: F811
):
    entries = 0
    # T85: the live requests still run -- they must stay self-consistent
    # whatever is uploaded -- and `oos_months` adds a month this test owns,
    # so the entry assertions below are exercised rather than skipped over.
    for plant, month in (*REQUESTS, *oos_months):
        payload = get(viewer, plant, month)
        facts = _facts(admin_conn, plant, payload["month"])
        for b in payload["boxes"]:
            got = Counter(
                (p["logical_vehicle_id"], p["point_code"], Decimal(p["value"]), p["measured_date"])
                for p in b["out_of_spec"]
            )
            listed = {(car, point, value) for car, point, value, _ in got}
            # Every fact row of this box matching a listed (car, point, value), with
            # its own date. Multisets: a duplicate reading must appear as often.
            want = Counter(
                (f["car"], f["point_code"], f["value"], f["date"].isoformat())
                for f in facts[_key(b)]
                if (f["car"], f["point_code"], f["value"]) in listed
            )
            assert got == want, (_key(b), got - want, want - got)
            assert all(p["measured_date"] is not None for p in b["out_of_spec"])
            months = {p["measured_date"][:7] for p in b["out_of_spec"]}
            assert months <= {payload["month"]}
            entries += len(b["out_of_spec"])
    # T85: this used to be `entries > 1000`, a statement about how much data
    # the owner had uploaded. What the test needs is that the per-entry
    # assertions above ran at all, which the fixture's own below-Minimum
    # E-coat readings guarantee.
    assert entries > 0, "no out-of-spec entry was listed; the claim is vacuous"


# ---------------------------------------------------------------- 3
def test_nothing_else_moved(viewer, admin_conn, oos_months):  # noqa: F811  # T85
    for plant, month in (*REQUESTS, *oos_months):
        payload = get(viewer, plant, month)
        facts = _facts(admin_conn, plant, payload["month"])
        assert {_key(b) for b in payload["boxes"]} == {k for k, v in facts.items() if v}
        order = []
        for b in payload["boxes"]:
            assert set(b) == T67_BOX_KEYS | {"color_rank"}  # T73 CHANGE: + color_rank
            rows = facts[_key(b)]
            values = [f["value"] for f in rows]
            stats = box_stats(values)
            assert b["n"] == stats.n and b["vehicles"] == len({f["car"] for f in rows})
            for k in STAT_KEYS:
                assert Decimal(b[k]) == getattr(stats, k), (_key(b), k)
            assert [Decimal(v) for v in b["outliers"]] == list(stats.outliers)
            lo, hi, target = D(b["lo"]), D(b["hi"]), D(b["target"])
            assert b["status"] == film_box_status(b["layer_code"], stats.mean, lo, hi, target)
            labels = line_labels(b["layer_code"], lo, hi, target)
            assert {k: b[k] for k in labels} == labels
            assert (b["family_code"], b["family_name"], b["family_order"]) == rows[0]["family"]
            # Entries: same count (duplicates kept) and the T67 (side, value) order.
            high_line = None if b["layer_code"] == "CLEAR" else hi
            low_rows = [f for f in rows if lo is not None and f["value"] < lo]
            high_rows = [f for f in rows if high_line is not None and f["value"] > high_line]
            want = sorted(
                [("LOW", f["value"], f["point_code"], f["car"]) for f in low_rows]
                + [("HIGH", f["value"], f["point_code"], f["car"]) for f in high_rows],
                key=lambda e: (e[0] != "LOW", e[1], e[2]),
            )
            got = [(p["side"], Decimal(p["value"]), p["point_code"], p["logical_vehicle_id"])
                   for p in b["out_of_spec"]]
            assert len(got) == len(want), _key(b)
            assert [(s, v) for s, v, _, _ in got] == [(s, v) for s, v, _, _ in want], _key(b)
            assert sorted(got) == sorted(want), _key(b)
            assert all(set(p) == T67_ENTRY_KEYS | {"measured_date"} for p in b["out_of_spec"])
            # T73 CHANGE: D-73-13 box order, color_rank replaces family/colour.
            order.append((
                LAYERS.index(b["layer_code"]), model_sort_key(b["model_code"]),
                0 if b["orient"] == "H" else 1, b["color_rank"],
            ))
        assert order == sorted(order), plant


# ---------------------------------------------------------------- 4
#: Clearcoat, Base, Primer, E-Coat (pelt()'s column order). FVL ECOAT lo 20.
CAR_EARLY = {"001HOOD": (47, 19, 25, 19.0), "022LTFTDOOR": (40, 19, 25, 22)}
CAR_LATE = {"002HOOD": (47, 19, 25, 18.5), "036LBOXSIDE": (40, 19, 25, 22)}


@pytest.fixture()
def two_days(engineer, admin, admin_conn, film_cleanup):  # noqa: F811
    n = uuid.uuid4().int
    month_index, year = n % 12, 1 + (n // 12) % 15          # 2001-2015: no live month
    stamp = f"{MONTHS[month_index]}-{year:02d}"
    days = {"early": date(2000 + year, month_index + 1, 3),
            "late": date(2000 + year, month_index + 1, 17)}
    for label, car, day in (("early", CAR_EARLY, "03"), ("late", CAR_LATE, "17")):
        job = f"UR{uuid.uuid4().hex[:8].upper()}"
        data = pelt(list(car), colour="Absolute Black", day=f"{day}-{stamp}", job=job,
                    values=list(car.values()))
        review = sent(engineer, film_cleanup, admin_conn, f"P703-{job}-AB.xlsx", data,
                      "FVL")["Quick Summary"]
        commit(engineer, admin, review)
    return f"{2000 + year}-{month_index + 1:02d}", days


def test_each_low_entry_carries_its_own_cars_date(viewer, two_days):  # noqa: F811
    month, days = two_days
    payload = get(viewer, "FVL", month)
    assert payload["vehicle_count"] == 2
    [ecoat] = [b for b in payload["boxes"] if (b["layer_code"], b["orient"]) == ("ECOAT", "H")]
    assert ecoat["status"] == "FAIL"                # mean 18.75 < Minimum 20
    got = [(p["side"], p["value"], p["point_code"], p["measured_date"]) for p in ecoat["out_of_spec"]]
    assert [(s, Decimal(v), pt, d) for s, v, pt, d in got] == [
        ("LOW", Decimal("18.5"), "002HOOD", days["late"].isoformat()),
        ("LOW", Decimal("19"), "001HOOD", days["early"].isoformat()),
    ]
    assert len({p["logical_vehicle_id"] for p in ecoat["out_of_spec"]}) == 2
    assert all(p["measured_date"] != f"{month}-01" for p in ecoat["out_of_spec"])


# ---------------------------------------------------------------- 5
def test_reads_move_nothing_and_guards_hold(viewer, admin_conn):  # noqa: F811
    def counts():
        with admin_conn.cursor() as cur:
            out = []
            for table in ("film_standard", "filmthickness", "audit_event"):
                cur.execute(f"SELECT count(*) FROM {table}")
                out.append(cur.fetchone()[0])
            return out

    before = counts()
    for plant, month in REQUESTS:
        get(viewer, plant, month)
    assert counts() == before
    assert viewer.get("/api/v1/meta").json()["grading_available"] is False
    importers = sorted(
        str(path.relative_to(REPO)).replace("\\", "/")
        for path in (REPO / "backend/app").rglob("*.py")
        if re.search(r"\bimport +grading\b|\bfrom +\.?grading\b|domain\.grading\b",
                     path.read_text(encoding="utf-8"))
        and path.name != "grading.py"
    )
    # T105: IMG imports only orientation_of (canonical H/V), never a status.
    assert importers == [
        "backend/app/domain/img_overview.py",
        "backend/app/services/film_overview.py",
        "backend/app/services/img_overview.py",
        # Monthly Detail: owner-requested status of one point's monthly mean,
        # Overview's own rules; no per-reading grade, no pass rate -- D1 stays
        # open (docs/tasks/MONTHLY-DETAIL-inspection.md).
        "backend/app/services/monthly_detail.py",
        "backend/app/services/overview.py",
    ]
