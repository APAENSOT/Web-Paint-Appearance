"""T73 -- Monthly Overview backend prerequisites.

Part A (WaveScan): every ``OverviewBox`` carries ``below_minimum``, the
readings of that box with ``cf < minimum - EPS`` of the box's own standard,
only when the box has one (``ford`` not null). Each entry is the reading's
own ``measurement_id``, ``measured_date``, ``checkzone`` and exact ``cf``.

Part B (Film): one Base-ladder colour sequence per response
(``color_sequence``) from the current published BASE rules; each box carries
``color_rank``; boxes sort layer, model, H<V, ``color_rank``.

Claims (task "Tests" 1-10):

1. Contract for ``WavescanBelowMinimumReading`` / ``OverviewBox.below_minimum``.
2. Authoritative membership: for every plant's two latest WaveScan months,
   each box's multiset of (measurement_id, measured_date, checkzone, cf)
   equals an independent recomputation from ``v_wavescan_active``.
3. Boundaries of the pure helper.
4. Nothing else moved: box fields minus ``below_minimum`` equal the grain
   recomputation (``box_stats``, ``status_of``) in the T30 box order.
5. Synthetic upload: below / equal / duplicate pair in one box.
6. Contract for ``FilmColorSequenceEntry`` / ``color_sequence`` / ``color_rank``.
7. Key: pure-helper cases.
8. Live alignment for AAT, FTM, FVL, SAP.
9. Nothing else moved for Film (the T68 derivation, plus color_options).
10. Guards: grading_available false; counts unchanged by the reads; the T05
    import guard still sees only the two allowed services.

Test safety: the synthetic WaveScan batch is this file's own (its own note),
removed by ``cleanup`` by its own load_id. No standard, reference or seed row
is written or deleted. Expectations are data-driven, not hard-coded counts.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.boxplot import box_stats, model_sort_key
from app.domain.film_overview import LADDER_BASE, LADDER_NONE, color_sequence
from app.domain.film_standards import LAYERS, effective_rule
from app.domain.grading import EPS, orientation_of, status_of
from app.domain.wavescan_overview import below_minimum
from tests.wavescan_synthetic import forget_wavescan_month, wavescan_month
from tests.test_t03_contract import client, make_client  # noqa: F401
from tests.test_t04_ingest import admin, cleanup, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t68_film_overview_oos_date import (  # noqa: F401
    oos_months,
    test_nothing_else_moved as _t68_nothing_else_moved,
)

REPO = Path(__file__).resolve().parents[2]
WS_PATH = "/api/v1/plants/{plant_code}/wavescan/overview"
FILM_PATH = "/api/v1/plants/{plant_code}/filmthickness/overview"
PLANTS = ("AAT", "FTM", "FVL", "SAP")
NOTE = "T73 overview prereqs fixture"
STAT_KEYS = ("box_min", "q1", "median", "q3", "box_max", "whisker_lo", "whisker_hi", "mean")
T68_WS_BOX_KEYS = {
    "model_code", "color_name", "family_code", "orient", "n", *STAT_KEYS,
    "outliers", "ford", "minimum", "status",
}
ENTRY_KEYS = {"measurement_id", "measured_date", "checkzone", "cf"}
SEQ_KEYS = {
    "rank", "color_name", "family_code", "family_name", "family_order",
    "base_lo_h", "base_hi_h", "base_lo_v", "base_hi_v", "ladder",
}


def D(x) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def ws(c, plant: str, month: str) -> dict:
    response = c.get(WS_PATH.format(plant_code=plant), params={"month": month})
    assert response.status_code == 200, response.text
    return response.json()


def film(c, plant: str, month: str | None = None) -> dict:
    params = {"month": month} if month else {}
    response = c.get(FILM_PATH.format(plant_code=plant), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def ws_months(c, plant: str) -> list[str]:
    return ws(c, plant, "2000-01")["available_months"]


def ws_requests(c) -> list[tuple[str, str]]:
    """Every plant's latest WaveScan month, plus one earlier month."""
    out = []
    for plant in PLANTS:
        out.extend((plant, m) for m in ws_months(c, plant)[:2])
    assert {p for p, _ in out} == set(PLANTS), out
    return out


# =====================================================================
# T85: a WaveScan month at every plant
# =====================================================================
#: `ws_requests` asserts it covered all four plants, and the
#: below-Minimum claim asserts some readings were listed. T85 cleared every
#: upload, and the owner's trial has re-uploaded FTM only -- so one plant
#: was found where four are needed, and "some readings are below Minimum"
#: was asserted against none. Each claim is about the **read**, so each
#: plant that is missing one gets a month of its own to be read.
@pytest.fixture()
def every_plant_month(admin_conn):  # T85
    made = []
    try:
        for plant in PLANTS:
            made.append(wavescan_month(admin_conn, plant=plant, day="2026-04-15"))
        assert any(b is not None for b in made), (
            "no plant has a live panel list and an offered colour; the "
            "reference seed is incomplete"
        )
        yield [b for b in made if b is not None]
    finally:
        for batch in reversed(made):
            forget_wavescan_month(admin_conn, batch)


def _axis(tolerance_group) -> str | None:
    return {"H": "Horizontal", "V": "Vertical"}.get(orientation_of(tolerance_group))


def _ws_grain(admin_conn, plant: str, month: str) -> dict[tuple, list[dict]]:
    """(model, colour, axis) -> active rows, read independently of the app."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT w.model, w.color, w.tolerance_group, w.cf, w.measurement_id,
                   w.measured_date, w.checkzone, f.family_code, f.display_order
              FROM v_wavescan_active w
              LEFT JOIN ref_plant_color pc
                ON pc.plant_code = w.plant AND pc.color_name = w.color
              LEFT JOIN ref_color_family f ON f.family_name = pc.family_name
             WHERE w.plant = %s AND to_char(w.measured_date, 'YYYY-MM') = %s
               AND w.cf IS NOT NULL
            """,
            (plant, month),
        )
        out: dict[tuple, list[dict]] = defaultdict(list)
        for model, color, tg, cf, mid, day, zone, fcode, forder in cur.fetchall():
            axis = _axis(tg)
            if axis is None:
                continue
            out[(model, color, axis)].append({
                "cf": Decimal(cf), "measurement_id": mid, "measured_date": day,
                "checkzone": zone, "family_code": fcode, "display_order": forder,
            })
        return out


def _ws_key(b: dict) -> tuple:
    return (b["model_code"], b["color_name"], b["orient"])


# ================================================================ Part A
# ---------------------------------------------------------------- 1
def test_wavescan_contract_adds_below_minimum(client):  # noqa: F811
    live = client.app.openapi()
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(live["paths"]) >= 57  # T79 + T81: four Comparison reads; T86: the panel-match read.
    backend_copy = (REPO / "backend" / "openapi.json").read_bytes()
    assert backend_copy == (REPO / "docs" / "openapi.json").read_bytes()
    assert json.loads(backend_copy) == live
    schemas = live["components"]["schemas"]
    box = schemas["OverviewBox"]
    assert set(box["properties"]) == T68_WS_BOX_KEYS | {"below_minimum"}
    assert "below_minimum" in box["required"]
    assert box["properties"]["below_minimum"]["items"] == {
        "$ref": "#/components/schemas/WavescanBelowMinimumReading"}
    entry = schemas["WavescanBelowMinimumReading"]
    assert set(entry["properties"]) == ENTRY_KEYS == set(entry["required"])
    assert entry["properties"]["measurement_id"]["type"] == "integer"
    assert entry["properties"]["measured_date"]["anyOf"] == [
        {"type": "string", "format": "date"}, {"type": "null"}]
    assert entry["properties"]["cf"]["type"] == "string"          # MeasureValue


# ---------------------------------------------------------------- 2
def test_below_minimum_membership_is_authoritative(  # T85
    viewer, admin_conn, every_plant_month,  # noqa: F811
):
    checked = listed = 0
    for plant, month in ws_requests(viewer):
        payload = ws(viewer, plant, month)
        grain = _ws_grain(admin_conn, plant, month)
        for b in payload["boxes"]:
            rows = grain[_ws_key(b)]
            got = Counter(
                (e["measurement_id"], e["measured_date"], e["checkzone"], Decimal(e["cf"]))
                for e in b["below_minimum"]
            )
            if b["ford"] is None:
                want = Counter()
            else:
                floor = float(D(b["minimum"])) - EPS
                want = Counter(
                    (r["measurement_id"], r["measured_date"].isoformat(), r["checkzone"], r["cf"])
                    for r in rows if float(r["cf"]) < floor
                )
            assert got == want, (plant, month, _ws_key(b), got - want, want - got)
            by_id = {r["measurement_id"]: r for r in rows}
            for e in b["below_minimum"]:
                own = by_id[e["measurement_id"]]
                assert (e["measured_date"], e["checkzone"], Decimal(e["cf"])) == (
                    own["measured_date"].isoformat(), own["checkzone"], own["cf"])
                assert Decimal(e["cf"]) < D(b["minimum"])
            order = [(Decimal(e["cf"]), e["measured_date"], e["checkzone"], e["measurement_id"])
                     for e in b["below_minimum"]]
            assert order == sorted(order)
            checked += 1
            listed += len(b["below_minimum"])
    # T85: `every_plant_month` puts a reading far below Minimum at every
    # plant that has a catalogue, so this says what it always meant -- the
    # membership comparison above ran, and on boxes that really do list
    # something -- without depending on what anyone has uploaded.
    assert checked and listed, "no below-Minimum reading was listed; the claim is vacuous"


# ---------------------------------------------------------------- 3
def _r(mid, cf, day=date(2099, 1, 5), zone="RRHOOD"):
    return {"measurement_id": mid, "measured_date": day, "checkzone": zone, "cf": Decimal(cf)}


def test_below_minimum_helper_boundaries():
    minimum = Decimal("55")
    readings = [
        _r(1, "55"),                                  # equal: not listed
        _r(2, "54.999999998"),                        # below by 2e-9: listed
        _r(3, "54.9999999995"),                       # within EPS: not listed
        _r(4, "58"),                                  # between Minimum and Standard
        _r(5, "50", date(2099, 1, 9), "LTFDOOR"),
        _r(6, "50", date(2099, 1, 9), "LTFDOOR"),     # duplicate pair: both kept
        _r(7, "50", date(2099, 1, 2), "ZZZ"),
        _r(8, "50", None, "AAA"),
        _r(9, "40", date(2099, 1, 30)),
    ]
    got = below_minimum(readings, minimum, eps=EPS)
    assert [e["measurement_id"] for e in got] == [9, 7, 5, 6, 8, 2]
    assert all(set(e) == ENTRY_KEYS for e in got)
    assert got[-1]["cf"] == Decimal("54.999999998")   # exact, unrounded
    assert below_minimum(readings, None, eps=EPS) == []
    assert below_minimum([], minimum, eps=EPS) == []
    # Zone breaks a tie on cf and date; measurement_id breaks the rest.
    tie = below_minimum([_r(11, "1", zone="B"), _r(10, "1", zone="B"), _r(12, "1", zone="A")],
                        minimum, eps=EPS)
    assert [e["measurement_id"] for e in tie] == [12, 10, 11]


# ---------------------------------------------------------------- 4
def test_wavescan_nothing_else_moved(viewer, admin_conn, every_plant_month):  # noqa: F811  # T85
    for plant, month in ws_requests(viewer):
        payload = ws(viewer, plant, month)
        grain = _ws_grain(admin_conn, plant, month)
        assert {_ws_key(b) for b in payload["boxes"]} == set(grain)
        order = []
        for b in payload["boxes"]:
            assert set(b) == T68_WS_BOX_KEYS | {"below_minimum"}
            rows = grain[_ws_key(b)]
            stats = box_stats([r["cf"] for r in rows])
            assert b["n"] == stats.n
            for k in STAT_KEYS:
                assert Decimal(b[k]) == getattr(stats, k), (_ws_key(b), k)
            assert [Decimal(v) for v in b["outliers"]] == list(stats.outliers)
            ford, minimum = D(b["ford"]), D(b["minimum"])
            want_status = status_of(stats.mean, ford, minimum) if ford is not None else None
            assert b["status"] == want_status
            assert b["family_code"] == rows[0]["family_code"]
            forder = rows[0]["display_order"]
            order.append((model_sort_key(b["model_code"]),
                          0 if b["orient"] == "Horizontal" else 1,
                          forder if forder is not None else 99, b["color_name"]))
        assert order == sorted(order), (plant, month)


# ---------------------------------------------------------------- 5
def _batch(cur) -> int:
    digest = hashlib.sha256(f"T73:{uuid.uuid4().hex}".encode()).hexdigest()
    cur.execute(
        """
        INSERT INTO load_batch (
            source_file, source_sheet, plant_code, file_hash, status,
            rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
            rows_quarantine, raw_store_key, finished_at, notes)
        VALUES (%s, 'Sheet1', 'FTM', %s, 'COMMITTED', 4, 4, 0, 0, 0, %s, now(), %s)
        RETURNING load_id
        """,
        (f"T73 {digest[:8]}.xlsx", digest, f"wavescan/raw/{digest}", NOTE),
    )
    return cur.fetchone()[0]


def _insert(cur, load_id, source_row, *, cf, measured, zone) -> int:
    cur.execute(
        """
        INSERT INTO wavescan (
            measured_date, plant, model, checkzone, color, tolerance_group,
            paintline, serial_no,
            lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
            load_id, source_sheet, source_row)
        VALUES (%s, 'FTM', 'P703 DBL RAPTOR', %s, 'Arctic White', 'Horizontal',
                'BOOTH1', %s, 1, 2, %s, 80, 3, 4, 5, 6, 7, 8, 0, %s, 'Sheet1', %s)
        RETURNING measurement_id
        """,
        (measured, zone, f"T73-{load_id}-{source_row}", cf, load_id, source_row),
    )
    return cur.fetchone()[0]


@pytest.fixture()
def synthetic_box(viewer, admin_conn, cleanup):  # noqa: F811
    n = uuid.uuid4().int
    year, month = 2060 + n % 30, 1 + (n // 30) % 12        # no live month
    stamp = f"{year}-{month:02d}"
    early, late = date(year, month, 4), date(year, month, 21)
    with admin_conn.cursor() as cur:
        # A second Horizontal zone of this plant/model, from the reference tables.
        cur.execute(
            """
            SELECT p.zone_code FROM ref_plant_ws_point p
              JOIN ref_checkzone z
                ON z.zone_code = p.zone_code AND z.tolerance_group = 'Horizontal'
             WHERE p.plant_code = 'FTM' AND p.model_code = 'P703 DBL RAPTOR'
               AND p.retired_at IS NULL AND p.zone_code <> 'RRHOOD'
             ORDER BY p.zone_code LIMIT 1
            """
        )
        other_zone = cur.fetchone()[0]
        load_id = _batch(cur)
        cleanup.append(load_id)
        # A first reading, high, only to learn this box's own Minimum.
        high = _insert(cur, load_id, 1, cf=Decimal("99"), measured=early, zone="RRHOOD")
    probe = [b for b in ws(viewer, "FTM", stamp)["boxes"]
             if (b["color_name"], b["orient"]) == ("Arctic White", "Horizontal")]
    assert len(probe) == 1 and probe[0]["ford"] is not None, probe
    minimum = D(probe[0]["minimum"])
    below, dup = minimum - Decimal("1.5"), minimum - Decimal("3")
    with admin_conn.cursor() as cur:
        ids = {
            "high": high,
            "equal": _insert(cur, load_id, 2, cf=minimum, measured=early, zone="RRHOOD"),
            "below": _insert(cur, load_id, 3, cf=below, measured=late, zone=other_zone),
            "dup1": _insert(cur, load_id, 4, cf=dup, measured=early, zone="RRHOOD"),
            "dup2": _insert(cur, load_id, 5, cf=dup, measured=early, zone="RRHOOD"),
        }
    return stamp, minimum, ids, {"early": early, "late": late, "below": below, "dup": dup,
                                 "zone": other_zone}


def test_synthetic_box_lists_only_below_with_own_dates(viewer, synthetic_box):  # noqa: F811
    stamp, minimum, ids, v = synthetic_box
    [box] = [b for b in ws(viewer, "FTM", stamp)["boxes"]
             if (b["color_name"], b["orient"]) == ("Arctic White", "Horizontal")]
    assert box["n"] == 5 and D(box["minimum"]) == minimum
    got = [(e["measurement_id"], e["measured_date"], e["checkzone"], Decimal(e["cf"]))
           for e in box["below_minimum"]]
    dup_ids = sorted((ids["dup1"], ids["dup2"]))
    assert got == [
        (dup_ids[0], v["early"].isoformat(), "RRHOOD", v["dup"]),
        (dup_ids[1], v["early"].isoformat(), "RRHOOD", v["dup"]),
        (ids["below"], v["late"].isoformat(), v["zone"], v["below"]),
    ]
    assert ids["equal"] not in {e["measurement_id"] for e in box["below_minimum"]}
    assert all(e["measured_date"] != f"{stamp}-01" for e in box["below_minimum"])


# ================================================================ Part B
# ---------------------------------------------------------------- 6
def test_film_contract_adds_sequence_and_rank(client):  # noqa: F811
    schemas = client.app.openapi()["components"]["schemas"]
    entry = schemas["FilmColorSequenceEntry"]
    assert set(entry["properties"]) == SEQ_KEYS == set(entry["required"])
    assert entry["properties"]["ladder"]["enum"] == [LADDER_BASE, LADDER_NONE]
    for k in ("base_lo_h", "base_hi_h", "base_lo_v", "base_hi_v"):
        assert {"type": "null"} in entry["properties"][k]["anyOf"]
    out = schemas["FilmOverviewOut"]
    assert out["properties"]["color_sequence"]["items"] == {
        "$ref": "#/components/schemas/FilmColorSequenceEntry"}
    assert "color_sequence" in out["required"]
    box = schemas["FilmOverviewBox"]
    assert box["properties"]["color_rank"]["type"] == "integer"
    assert "color_rank" in box["required"]
    assert "Horizontal is primary" in entry["description"]


# ---------------------------------------------------------------- 7
def _c(name, order=None):
    return {"color_name": name, "family_code": None, "family_name": None, "family_order": order}


def _rule(lo, hi):
    return {"lo": None if lo is None else Decimal(lo), "hi": None if hi is None else Decimal(hi)}


def test_color_sequence_key_cases():
    colours = [_c("n", 1), _c("m", 2), _c("k", 1), _c("j", None), _c("i", 5), _c("h", 3),
               _c("g", 3), _c("f", 1), _c("e", 4), _c("d", 2), _c("c", 2), _c("b")]
    rules = {
        "n": {"H": _rule("15", "20"), "V": _rule("15", "20")},
        "m": {"H": _rule("15", None), "V": _rule("15", None)},     # partial: after 15-20
        "k": {"H": _rule("16", "17"), "V": _rule("16", "17")},
        "j": {"H": None, "V": _rule("1", "2")},                     # no H: after every H
        "i": {"H": None, "V": None},                                # no Base at all
        "h": {"H": _rule("15", "20"), "V": _rule("10", "12")},     # unequal: V breaks tie
        "g": {"H": _rule("15", "20"), "V": _rule("15", "20")},     # tie with n: family
        "f": {"H": _rule("15", "20"), "V": _rule("15", "20")},     # tie with n: name
        "e": {"H": _rule("9.50", "30"), "V": _rule("15", "20")},
        "d": {"H": _rule("9.5", "30"), "V": _rule("15", "20")},    # Decimal equal to e
        "c": {"H": None, "V": None},
        "b": {},
    }
    seq = color_sequence(colours, rules)
    assert [e["color_name"] for e in seq] == [
        "d", "e", "h", "f", "n", "g", "m", "k", "j", "c", "i", "b"]
    assert [e["rank"] for e in seq] == list(range(1, len(colours) + 1))
    by = {e["color_name"]: e for e in seq}
    assert by["i"]["ladder"] == by["b"]["ladder"] == LADDER_NONE
    assert by["j"]["ladder"] == by["m"]["ladder"] == LADDER_BASE
    assert (by["m"]["base_lo_h"], by["m"]["base_hi_h"]) == (Decimal("15"), None)
    assert by["e"]["base_lo_h"] == Decimal("9.50")
    assert all(set(e) == SEQ_KEYS for e in seq)
    # Exact Decimal, not lo*1000+hi: 1-1001 and 2-1 would collide that way.
    exact = color_sequence([_c("x"), _c("y")], {
        "x": {"H": _rule("2", "1"), "V": None}, "y": {"H": _rule("1", "1001"), "V": None}})
    assert [e["color_name"] for e in exact] == ["y", "x"]
    assert color_sequence([], {}) == []


# ---------------------------------------------------------------- 8
def _latest_rules(admin_conn, plant: str) -> list[dict]:
    """Latest film_standard row per (layer, folded colour, orient), independently."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (s.layer_code, COALESCE(rc.merged_into, s.color_name), s.orient)
                   s.id, s.layer_code, COALESCE(rc.merged_into, s.color_name), s.orient,
                   s.lo, s.hi, s.created_at
              FROM film_standard s
              LEFT JOIN ref_color rc ON rc.color_name = s.color_name
             WHERE s.plant_code = %s
             ORDER BY s.layer_code, COALESCE(rc.merged_into, s.color_name), s.orient,
                      s.created_at DESC, s.id DESC
            """,
            (plant,),
        )
        keys = ("id", "layer_code", "color_name", "orient", "lo", "hi", "created_at")
        return [dict(zip(keys, r)) for r in cur.fetchall()]


def _nl(v):
    return (v is None, v if v is not None else 0)


def test_live_sequence_aligns_every_layer(viewer, admin_conn):  # noqa: F811
    for plant in PLANTS:
        payload = film(viewer, plant)
        rules = _latest_rules(admin_conn, plant)
        colours = {}
        for b in payload["boxes"]:
            colours.setdefault(b["color_name"], (b["family_code"], b["family_name"],
                                                 b["family_order"]))
        want = []
        for name, (fcode, fname, forder) in colours.items():
            h = effective_rule(rules, layer_code="BASE", color_name=name, orient="H")
            v = effective_rule(rules, layer_code="BASE", color_name=name, orient="V")
            vals = [None if r is None or r[k] is None else Decimal(r[k])
                    for r, k in ((h, "lo"), (h, "hi"), (v, "lo"), (v, "hi"))]
            want.append((name, fcode, fname, forder, vals))
        want.sort(key=lambda w: (*map(_nl, w[4]), _nl(w[3]), w[0]))
        seq = payload["color_sequence"]
        assert [e["rank"] for e in seq] == list(range(1, len(want) + 1)), plant
        got = [(e["color_name"], e["family_code"], e["family_name"], e["family_order"],
                [D(e[k]) for k in ("base_lo_h", "base_hi_h", "base_lo_v", "base_hi_v")])
               for e in seq]
        assert got == want, plant
        for e in seq:
            has = any(e[k] is not None for k in ("base_lo_h", "base_hi_h", "base_lo_v", "base_hi_v"))
            assert e["ladder"] == (LADDER_BASE if has else LADDER_NONE)
        rank = {e["color_name"]: e["rank"] for e in seq}
        groups: dict[tuple, list[str]] = defaultdict(list)
        for b in payload["boxes"]:
            assert b["color_rank"] == rank[b["color_name"]]
            groups[(b["layer_code"], b["model_code"], b["orient"])].append(b["color_name"])
        for key, names in groups.items():
            assert [rank[n] for n in names] == sorted(rank[n] for n in names), (plant, key)
            other = groups.get((key[0], key[1], "V" if key[2] == "H" else "H"))
            if other is not None:
                common = set(names) & set(other)
                assert [n for n in names if n in common] == [n for n in other if n in common]
        order = [(LAYERS.index(b["layer_code"]), model_sort_key(b["model_code"]),
                  0 if b["orient"] == "H" else 1, b["color_rank"]) for b in payload["boxes"]]
        assert order == sorted(order), plant


# ---------------------------------------------------------------- 9
def test_film_nothing_else_moved(viewer, admin_conn, oos_months):  # noqa: F811  # T85
    # The full T68 derivation: box set, statistics, spec, status, labels,
    # family, out_of_spec, and the box order (now with color_rank).
    # T85: `oos_months` travels with it, because that derivation now has a
    # Film month of its own to derive from.
    _t68_nothing_else_moved(viewer, admin_conn, oos_months)
    for plant in PLANTS:
        payload = film(viewer, plant)
        options = payload["color_options"]
        assert options == sorted(
            options,
            key=lambda c: (c["family_order"] is None, c["family_order"] or 0, c["color_name"]))
        assert {e["color_name"] for e in payload["color_sequence"]} == {
            b["color_name"] for b in payload["boxes"]}


# ---------------------------------------------------------------- 10
def test_reads_move_nothing_and_guards_hold(  # T85
    viewer, admin_conn, every_plant_month,  # noqa: F811
):
    def counts():
        with admin_conn.cursor() as cur:
            out = []
            for table in ("film_standard", "filmthickness", "wavescan", "audit_event"):
                cur.execute(f"SELECT count(*) FROM {table}")
                out.append(cur.fetchone()[0])
            return out

    before = counts()
    for plant, month in ws_requests(viewer):
        ws(viewer, plant, month)
    for plant in PLANTS:
        film(viewer, plant)
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
    for name in ("wavescan_overview.py", "film_overview.py"):
        source = (REPO / "backend/app/domain" / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(fastapi|psycopg|sqlalchemy)", source, re.M)
