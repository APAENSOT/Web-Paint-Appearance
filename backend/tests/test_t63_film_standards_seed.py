"""T63: the owner-signed FilmThickness standards seed (revision 0025).

1. Exactly 114 seed rows: FTM 24, FVL 22, SAP 28, AAT 40.
2. Spot values through the plant GET.
3. ``target`` only on CLEAR; AAT CLEAR target NULL.
4. FTM-03..10 carry the Control Plan hash; every other row the prototype string.
5. No row for the no-range colours (D-63-07) or any Cyber Orange.
6. No plant-wide BASE row anywhere; no plant-wide PRIMER at AAT.
7. ``effective_rule`` precedence on the seed.
8. A later Admin publish wins without touching the seed.
9. ``grading_available`` false; OpenAPI unchanged (51 paths, both copies equal).

Plus: the preflight raises listing every un-offered colour and inserts nothing.
"""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from app.domain.film_standards import effective_rule
from tests.test_t03_contract import (  # noqa: F401
    admin_client,
    client,
    engineer_client,
    make_client,
)

REPO = Path(__file__).resolve().parents[2]
# T67 CHANGE: migration 0027 appends an AAT CLEAR correction pair whose note
# also starts 'FILM-STANDARDS-AUDIT '. It is not the T63 seed; exclude it.
T67_CORRECTION = "FILM-STANDARDS-AUDIT AAT-02 (T67 owner correction 2026-10-06)"
SEED = (
    "created_by IS NULL AND source_note LIKE 'FILM-STANDARDS-AUDIT %%' "
    f"AND source_note <> '{T67_CORRECTION}'"
)
CP1 = (
    "Control Plan scan Reference/Standard1.jpg "
    "sha256:cbb564cf87b5e3bb09a354e22894ae0fe5b222b7eb4052046dee92fa50965e52"
)
PROTO = "Prototype.html constants (owner-accepted 2026-10-06)"
TEST_NOTE = "pytest-t63-later-publish"
POST = "/api/v1/filmthickness/standards"


def _migration():
    path = REPO / "backend" / "migrations" / "versions" / "0025_t63_film_standard_seed.py"
    spec = importlib.util.spec_from_file_location("t63_seed_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_rows(admin_conn, where: str = "TRUE", params: tuple = ()) -> list[dict]:
    with admin_conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, plant_code, layer_code, color_name, orient, lo, hi, target, "
            "       source_document, source_note, created_at "
            f"FROM film_standard WHERE {SEED} AND {where} "
            "ORDER BY plant_code, layer_code, color_name, orient",
            params,
        )
        return cur.fetchall()


def _plain(rule: dict) -> tuple:
    return (rule["lo"], rule["hi"], rule["target"])


def _get_rule(client, plant: str, layer: str, colour: str | None) -> dict:
    response = client.get(f"/api/v1/plants/{plant}/filmthickness/standards")
    assert response.status_code == 200, response.text
    hits = [
        r for r in response.json()["rules"]
        if r["layer_code"] == layer and r["color_name"] == colour
    ]
    assert len(hits) == 1, (plant, layer, colour, hits)
    return hits[0]


# ---------------------------------------------------------------- 1
def test_exactly_114_seed_rows_per_plant(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            f"SELECT plant_code, count(*) FROM film_standard WHERE {SEED} GROUP BY 1"
        )
        counts = dict(cur.fetchall())
    assert counts == {"FTM": 24, "FVL": 22, "SAP": 28, "AAT": 40}
    assert sum(counts.values()) == 114
    rows = _seed_rows(admin_conn)
    pairs = {}
    for row in rows:
        pairs.setdefault(row["source_note"], []).append(row["orient"])
    assert len(pairs) == 57
    assert all(sorted(o) == ["H", "V"] for o in pairs.values())


# ---------------------------------------------------------------- 2
def test_spot_values_through_get(client):
    clear = _get_rule(client, "FTM", "CLEAR", None)
    assert _plain(clear["h"]) == (36.0, None, 46.0)
    assert _plain(clear["v"]) == (30.0, None, 46.0)

    ftm_primer = _get_rule(client, "FTM", "PRIMER", None)
    assert _plain(ftm_primer["h"]) == _plain(ftm_primer["v"]) == (20.0, 25.0, None)

    fvl_primer = _get_rule(client, "FVL", "PRIMER", None)
    assert _plain(fvl_primer["h"]) == (23.0, 31.0, None)
    assert _plain(fvl_primer["v"]) == (18.0, 25.0, None)

    pearl_primer = _get_rule(client, "AAT", "PRIMER", "Pearl White")
    pearl_base = _get_rule(client, "AAT", "BASE", "Pearl White")
    assert _plain(pearl_primer["h"]) == _plain(pearl_primer["v"]) == (31.0, 33.0, None)
    assert _plain(pearl_base["h"]) == _plain(pearl_base["v"]) == (7.0, 9.0, None)

    sap_grey = _get_rule(client, "SAP", "BASE", "Command Grey")
    assert _plain(sap_grey["h"]) == _plain(sap_grey["v"]) == (12.0, 15.0, None)

    aat_clear = _get_rule(client, "AAT", "CLEAR", None)
    # T67 CHANGE: latest wins; the 0027 correction (D-67-06) is lo 30, target 35,
    # no Maximum. The T63 30-35 pair stays stored (test_target_only_on_clear).
    assert _plain(aat_clear["h"]) == _plain(aat_clear["v"]) == (30.0, None, 35.0)


# ---------------------------------------------------------------- 3
def test_target_only_on_clear(admin_conn):
    rows = _seed_rows(admin_conn)
    assert {r["layer_code"] for r in rows if r["target"] is not None} == {"CLEAR"}
    aat_clear = [r for r in rows if r["plant_code"] == "AAT" and r["layer_code"] == "CLEAR"]
    assert len(aat_clear) == 2 and all(r["target"] is None for r in aat_clear)
    with_target = {
        (r["plant_code"], r["orient"]): r["target"] for r in rows if r["target"] is not None
    }
    assert with_target == {
        (p, o): Decimal("46.00") for p in ("FTM", "FVL", "SAP") for o in ("H", "V")
    }


# ---------------------------------------------------------------- 4
def test_source_documents(admin_conn):
    cp1_ids = {f"FILM-STANDARDS-AUDIT FTM-{n:02d}" for n in range(3, 11)}
    for row in _seed_rows(admin_conn):
        expected = CP1 if row["source_note"] in cp1_ids else PROTO
        assert row["source_document"] == expected, row["source_note"]
    assert len(_seed_rows(admin_conn, "source_document = %s", (CP1,))) == 16


# ---------------------------------------------------------------- 5
@pytest.mark.parametrize(
    "plant, colour",
    [
        ("SAP", "Ignite Orange"),
        ("SAP", "Desert Island Blue"),
        ("AAT", "Seismic Tan"),
        ("AAT", "Desert Island Blue"),
        ("AAT", "Blue Lightning"),
        ("FVL", "Blue Lightning"),
    ],
)
def test_no_range_colours_have_no_row(admin_conn, plant, colour):
    assert _seed_rows(admin_conn, "plant_code = %s AND color_name = %s", (plant, colour)) == []
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT layer_code, orient, lo, hi, target, source_document "
            "  FROM film_standard WHERE plant_code = %s AND color_name = %s "
            " ORDER BY layer_code, orient",
            (plant, colour),
        )
        rows = cur.fetchall()
    # RO10 / RO13 CHANGE: on 2026-10-13 the owner published AAT's missing
    # Base / Primer ranges from the Control Plan (audit 191115-191120). The
    # seed still wrote nothing for these colours; those 4 rows are the owner's.
    owner = {"Seismic Tan": ("9.00", "11.00"), "Desert Island Blue": ("7.00", "9.00"),
             "Blue Lightning": ("7.00", "9.00")}
    if plant == "AAT":
        lo, hi = (Decimal(v) for v in owner[colour])
        assert rows == [(layer, o, lo, hi, None, "Control Plan")
                        for layer in ("BASE", "PRIMER") for o in ("H", "V")]
    else:
        assert rows == []


def test_no_cyber_orange_and_no_null_placeholders(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM film_standard WHERE color_name ILIKE '%%cyber%%'")
        assert cur.fetchone()[0] == 0
    assert all(r["lo"] is not None or r["hi"] is not None for r in _seed_rows(admin_conn))


# ---------------------------------------------------------------- 6
def test_no_plant_wide_base_and_no_plant_wide_aat_primer(admin_conn):
    rows = _seed_rows(admin_conn, "color_name IS NULL")
    assert not [r for r in rows if r["layer_code"] == "BASE"]
    assert not [r for r in rows if r["plant_code"] == "AAT" and r["layer_code"] == "PRIMER"]
    plant_wide = {(r["plant_code"], r["layer_code"]) for r in rows}
    assert plant_wide == {
        ("FTM", "ECOAT"), ("FTM", "PRIMER"), ("FTM", "CLEAR"),
        ("FVL", "ECOAT"), ("FVL", "PRIMER"), ("FVL", "CLEAR"),
        ("SAP", "ECOAT"), ("SAP", "PRIMER"), ("SAP", "CLEAR"),
        ("AAT", "ECOAT"), ("AAT", "CLEAR"),
    }


# ---------------------------------------------------------------- 7
def test_effective_rule_on_the_seed(admin_conn):
    aat = _seed_rows(admin_conn, "plant_code = 'AAT'")
    black = effective_rule(aat, layer_code="PRIMER", color_name="Shadow Black", orient="H")
    assert (black["color_name"], black["lo"], black["hi"]) == (
        "Shadow Black", Decimal("9.00"), Decimal("11.00"),
    )
    ftm = _seed_rows(admin_conn, "plant_code = 'FTM'")
    for colour in ("Shadow Black", "Arctic White", "Not A Colour", None):
        ecoat = effective_rule(ftm, layer_code="ECOAT", color_name=colour, orient="V")
        assert (ecoat["color_name"], ecoat["lo"], ecoat["hi"]) == (None, Decimal("18.00"), None)
    sap = _seed_rows(admin_conn, "plant_code = 'SAP'")
    assert effective_rule(sap, layer_code="BASE", color_name="Ignite Orange", orient="H") is None


# ---------------------------------------------------------------- 8
@pytest.fixture()
def later_publish_cleanup(admin_conn):
    def _purge() -> None:
        # Test rows only; seed rows are never deleted here.
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM film_standard WHERE source_note = %s", (TEST_NOTE,))

    _purge()
    yield
    _purge()


def test_later_admin_publish_wins_and_leaves_the_seed(
    admin_client, client, admin_conn, later_publish_cleanup,
):
    before = _seed_rows(admin_conn)
    response = admin_client.post(
        POST,
        json={
            "plant_code": "FTM",
            "layer_code": "CLEAR",
            "color_name": None,
            "h": {"lo": 37, "target": 47},
            "v": {"lo": 31, "target": 47},
            "source_note": TEST_NOTE,
        },
    )
    assert response.status_code == 201, response.text
    clear = _get_rule(client, "FTM", "CLEAR", None)
    assert _plain(clear["h"]) == (37.0, None, 47.0)
    assert _plain(clear["v"]) == (31.0, None, 47.0)
    assert clear["h"]["source_note"] == TEST_NOTE
    assert _seed_rows(admin_conn) == before


# ---------------------------------------------------------------- 9
def test_grading_and_openapi_unchanged(client):
    assert client.get("/api/v1/meta").json()["grading_available"] is False
    live = client.app.openapi()
    # T66 CHANGE: 51 -> 52 (FilmThickness monthly overview GET).
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(live["paths"]) >= 57  # T79 + T81: four Comparison reads; T86: the panel-match read.
    backend_copy = (REPO / "backend" / "openapi.json").read_bytes()
    assert backend_copy == (REPO / "docs" / "openapi.json").read_bytes()
    assert json.loads(backend_copy) == live


# ---------------------------------------------------------------- preflight
class _FakeConn:
    """Answers the preflight's offered lookup from a dict; records any INSERT."""

    def __init__(self, offered: dict[tuple[str, str], bool]) -> None:
        self.offered = offered
        self.inserts = 0

    def execute(self, clause, params=None):
        sql = str(clause)
        if "INSERT" in sql.upper():
            self.inserts += 1
        value = self.offered.get((params["p"], params["c"])) if params else None

        class _Result:
            def scalar(self_inner):
                return value

        return _Result()


def test_preflight_lists_every_miss_and_inserts_nothing():
    migration = _migration()
    offered = {
        (plant, colour): True
        for _id, plant, _l, colour, _h, _v, _s in migration.PUBLISHES
        if colour is not None
    }
    offered[("SAP", "Lucid Red")] = False
    del offered[("AAT", "Pearl White")]
    conn = _FakeConn(offered)
    with pytest.raises(RuntimeError) as caught:
        migration._preflight(conn)
    message = str(caught.value)
    assert "SAP-08" in message and "Lucid Red" in message
    assert "AAT-09 PRIMER" in message and "AAT-09 BASE" in message
    assert "nothing inserted" in message
    assert conn.inserts == 0
    assert len(migration.PUBLISHES) * 2 == migration.EXPECTED_ROWS == 114
