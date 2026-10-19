"""T62: FilmThickness micron standards container (D-FS-01..11).

1. Migration 0024 creates ``film_standard``; the app role has SELECT and
   INSERT, never UPDATE or DELETE; nothing is seeded.
2. Admin publishes a plant-wide CLEAR pair (201); GET shows H and V; one
   ``film_standards.publish`` audit row.
3. A second publish appends 2 more rows; GET is latest-wins; old rows stay.
4. Per-colour BASE; ``effective_rule`` precedence (colour > plant-wide > None).
5. Plant isolation: an FTM rule is not in the FVL GET.
6. A colour not offered at the plant is refused, nothing inserted.
7. Shape refusals: target off CLEAR, lo > hi, no bound, > 500.
8. Engineer / Viewer POST 403; Viewer GET 200.
9. Direct UPDATE / DELETE as the app role is a permission error.
10. ``grading_available`` false; both OpenAPI copies equal with the two paths.

All numbers are synthetic test values, **not** a seed. Rows are tagged by
``source_note`` and removed by the owner connection after each test.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from app.domain.film_standards import LAYERS, effective_rule
from app.domain.film_header import LAYER_CODES
from tests.test_t03_contract import (  # noqa: F401
    admin_client,
    client,
    engineer_client,
    make_client,
)

REPO = Path(__file__).resolve().parents[2]
NOTE = "pytest-t62-film-standards"
POST = "/api/v1/filmthickness/standards"
GET_PATH = "/api/v1/plants/{plant_code}/filmthickness/standards"
# T64 CHANGE: Shadow Black is merged (ADR 0014) and Absolute / Shadow Black is
# offered at FVL too; Blue Lightning is offered at FTM and not at FVL.
OFFERED_FTM = "Blue Lightning"     # offered at FTM, not at FVL
OTHER_FTM = "Arctic White"         # offered at FTM


def get_url(plant: str) -> str:
    return GET_PATH.format(plant_code=plant)


def body(**over) -> dict:
    payload = {
        "plant_code": "FTM",
        "layer_code": "CLEAR",
        "color_name": None,
        "h": {"lo": 36, "target": 46},
        "v": {"lo": 30, "target": 46},
        "source_document": "synthetic",
        "source_note": NOTE,
    }
    payload.update(over)
    return payload


def _rows(admin_conn, **where) -> list[tuple]:
    sql = (
        "SELECT plant_code, layer_code, color_name, orient, lo, hi, target "
        "FROM film_standard WHERE source_note = %s"
    )
    params: list = [NOTE]
    for key, value in where.items():
        if value is None:
            sql += f" AND {key} IS NULL"
        else:
            sql += f" AND {key} = %s"
            params.append(value)
    with admin_conn.cursor() as cur:
        cur.execute(sql + " ORDER BY created_at, orient", params)
        return cur.fetchall()


def _total(admin_conn) -> int:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM film_standard")
        return int(cur.fetchone()[0])


@pytest.fixture()
def clean(admin_conn):
    def _purge() -> None:
        # Owner-only test cleanup; the app role cannot do this (test 9).
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM film_standard WHERE source_note = %s", (NOTE,))

    _purge()
    yield
    _purge()


def _mine(payload: dict) -> list[dict]:
    return [
        r for r in payload["rules"]
        if (r["h"] and r["h"]["source_note"] == NOTE)
        or (r["v"] and r["v"]["source_note"] == NOTE)
    ]


# ---------------------------------------------------------------- 1
def test_migration_creates_append_only_table_without_seed(admin_conn, app_role):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] >= "0024"
        cur.execute("SELECT to_regclass('public.film_standard') IS NOT NULL")
        assert cur.fetchone()[0] is True
        grants = {}
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            cur.execute(
                "SELECT has_table_privilege(%s, 'film_standard', %s)",
                (app_role, privilege),
            )
            grants[privilege] = cur.fetchone()[0]
        # T63 CHANGE: the 0025 owner-signed seed rows are excluded; T62 itself
        # seeds nothing.
        # T104 CHANGE (D-104-1): a *migration* seed is what this claim is
        # about, and a migration leaves `created_by` null -- a person
        # publishing through the API always sets it. The old form counted
        # every row that was neither its own nor a seed row, so it failed the
        # moment the owner published a real standard (the 4 `Test` rows, then
        # FTM E-coat from the Control Plan). It measured "nobody ever
        # published" instead of "T62 seeded nothing".
        cur.execute(
            "SELECT count(*) FROM film_standard WHERE created_by IS NULL "
            "AND source_note NOT LIKE 'FILM-STANDARDS-AUDIT %%'",
        )
        seeded = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM film_standard WHERE created_by IS NULL"
        )
        signed_seed = cur.fetchone()[0]
    assert grants == {
        "SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False,
    }
    assert seeded == 0, (
        "film_standard must not be seeded by T62: every row with no "
        "created_by is a 0025 FILM-STANDARDS-AUDIT row. A row published by a "
        "person is fine -- that is the table working."
    )
    assert signed_seed > 0, "the 0025 owner-signed seed itself is still there"
    source = (
        REPO / "backend" / "migrations" / "versions" / "0024_t62_film_standard.py"
    ).read_text(encoding="utf-8")
    assert "INSERT INTO" not in source.upper()


def test_domain_layers_are_the_ingest_vocabulary():
    assert LAYERS == LAYER_CODES == ("ECOAT", "PRIMER", "BASE", "CLEAR")


def test_repository_has_no_update_or_delete():
    source = (REPO / "backend" / "app" / "repositories" / "film_standards.py").read_text(
        encoding="utf-8"
    ).upper()
    assert "UPDATE " not in source
    assert "DELETE " not in source


# ---------------------------------------------------------------- 2
def test_admin_publishes_plant_wide_clear_pair(admin_client, admin_conn, clean):
    response = admin_client.post(POST, json=body())
    assert response.status_code == 201, response.text
    out = response.json()
    assert out["plant_code"] == "FTM"
    assert out["layer_code"] == "CLEAR"
    assert out["color_name"] is None

    rows = _rows(admin_conn)
    assert [(r[3], float(r[4]), r[5], float(r[6])) for r in rows] == [
        ("H", 36.0, None, 46.0),
        ("V", 30.0, None, 46.0),
    ]

    mine = _mine(admin_client.get(get_url("FTM")).json())
    assert len(mine) == 1
    rule = mine[0]
    assert (rule["layer_code"], rule["color_name"]) == ("CLEAR", None)
    assert (rule["h"]["lo"], rule["h"]["hi"], rule["h"]["target"]) == (36.0, None, 46.0)
    assert (rule["v"]["lo"], rule["v"]["hi"], rule["v"]["target"]) == (30.0, None, 46.0)
    assert "status" not in json.dumps(rule)

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT action, entity_type, entity_id FROM audit_event WHERE id = %s",
            (out["audit_id"],),
        )
        assert cur.fetchall() == [("film_standards.publish", "film_standard", "FTM:CLEAR:*")]


# ---------------------------------------------------------------- 3
def test_second_publish_appends_and_latest_wins(admin_client, admin_conn, clean):
    assert admin_client.post(POST, json=body()).status_code == 201
    # T67 CHANGE: CLEAR refuses hi (D-67-07); the second pair is lo + target only.
    second = body(h={"lo": 38, "target": 48}, v={"lo": 32, "target": 47})
    assert admin_client.post(POST, json=second).status_code == 201

    rows = _rows(admin_conn, plant_code="FTM", layer_code="CLEAR", color_name=None)
    assert sorted(r[3] for r in rows) == ["H", "H", "V", "V"]
    assert {float(r[4]) for r in rows if r[3] == "H"} == {36.0, 38.0}  # old rows stay

    rule = _mine(admin_client.get(get_url("FTM")).json())[0]
    assert (rule["h"]["lo"], rule["h"]["hi"], rule["h"]["target"]) == (38.0, None, 48.0)
    assert (rule["v"]["lo"], rule["v"]["target"]) == (32.0, 47.0)


# ---------------------------------------------------------------- 4
def test_per_colour_rule_and_precedence(admin_client, admin_conn, clean):
    plant_wide = body(layer_code="BASE", h={"lo": 10, "hi": 20}, v={"lo": 9, "hi": 19})
    colour = body(
        layer_code="BASE", color_name=f"  {OFFERED_FTM} ",
        h={"lo": 15, "hi": 25}, v={"lo": 14, "hi": 24},
    )
    assert admin_client.post(POST, json=plant_wide).status_code == 201
    response = admin_client.post(POST, json=colour)
    assert response.status_code == 201, response.text
    assert response.json()["color_name"] == OFFERED_FTM

    got = admin_client.get(get_url("FTM")).json()
    keys = {(r["layer_code"], r["color_name"]) for r in _mine(got)}
    assert keys == {("BASE", None), ("BASE", OFFERED_FTM)}
    offered = {c["color_name"]: c["family_name"] for c in got["colors"]}
    assert OFFERED_FTM in offered and OTHER_FTM in offered

    with admin_conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, layer_code, color_name, orient, lo, hi, target, created_at "
            "FROM film_standard WHERE plant_code = 'FTM' AND source_note = %s",
            (NOTE,),
        )
        rules = cur.fetchall()
    own = effective_rule(rules, layer_code="BASE", color_name=OFFERED_FTM, orient="H")
    assert (own["color_name"], float(own["lo"]), float(own["hi"])) == (OFFERED_FTM, 15, 25)
    other = effective_rule(rules, layer_code="BASE", color_name=OTHER_FTM, orient="V")
    assert (other["color_name"], float(other["lo"])) == (None, 9)
    assert effective_rule(rules, layer_code="PRIMER", color_name=OFFERED_FTM, orient="H") is None


def test_effective_rule_pure_precedence():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rules = [
        {"id": "a", "layer_code": "BASE", "color_name": None, "orient": "H", "lo": 1,
         "created_at": t0},
        {"id": "b", "layer_code": "BASE", "color_name": None, "orient": "H", "lo": 2,
         "created_at": t0 + timedelta(days=1)},
        {"id": "c", "layer_code": "BASE", "color_name": "Red", "orient": "H", "lo": 3,
         "created_at": t0},
        {"id": "d", "layer_code": "BASE", "color_name": "Red", "orient": "H", "lo": 4,
         "created_at": t0 + timedelta(days=2)},
        {"id": "e", "layer_code": "BASE", "color_name": "Blue", "orient": "V", "lo": 5,
         "created_at": t0},
    ]
    assert effective_rule(rules, layer_code="BASE", color_name="Red", orient="H")["lo"] == 4
    assert effective_rule(rules, layer_code="BASE", color_name="Green", orient="H")["lo"] == 2
    assert effective_rule(rules, layer_code="BASE", color_name=None, orient="H")["lo"] == 2
    # Blue has only a V rule and there is no plant-wide V: no standard, never Red's.
    assert effective_rule(rules, layer_code="BASE", color_name="Blue", orient="H")["lo"] == 2
    assert effective_rule(rules, layer_code="BASE", color_name="Red", orient="V") is None
    assert effective_rule([], layer_code="CLEAR", color_name=None, orient="H") is None


# ---------------------------------------------------------------- 5
def test_plant_isolation(admin_client, clean):
    assert admin_client.post(POST, json=body()).status_code == 201
    assert _mine(admin_client.get(get_url("FTM")).json())
    fvl = admin_client.get(get_url("FVL"))
    assert fvl.status_code == 200
    assert fvl.json()["plant_code"] == "FVL"
    assert _mine(fvl.json()) == []
    assert admin_client.get(get_url("ftm")).json()["plant_code"] == "FTM"
    assert admin_client.get(get_url("NOPE")).status_code == 404


# ---------------------------------------------------------------- 6
def test_unoffered_or_unknown_colour_is_refused(admin_client, admin_conn, clean):
    before = _total(admin_conn)
    refused = admin_client.post(
        POST, json=body(plant_code="FVL", layer_code="BASE", color_name=OFFERED_FTM,
                        h={"lo": 1}, v={"lo": 1}),
    )
    assert refused.status_code == 422, refused.text
    err = refused.json()
    assert "not offered" in err["message"] and err["correlationId"]
    unknown = admin_client.post(
        POST, json=body(layer_code="BASE", color_name="Pytest No Such Colour",
                        h={"lo": 1}, v={"lo": 1}),
    )
    assert unknown.status_code == 404, unknown.text
    assert _total(admin_conn) == before


# ---------------------------------------------------------------- 7
@pytest.mark.parametrize(
    "over",
    [
        {"layer_code": "BASE", "h": {"lo": 10, "target": 12}, "v": {"lo": 10}},
        {"layer_code": "PRIMER", "h": {"lo": 10}, "v": {"lo": 10, "target": 12}},
        {"layer_code": "ECOAT", "h": {"lo": 10, "target": 12}, "v": {"lo": 10, "target": 12}},
        {"h": {"lo": 30, "hi": 20}},
        {"h": {"lo": None, "hi": None}},
        {"h": {"target": 40}},
        {"h": {"lo": 10, "hi": 501}},
        {"v": {"lo": 40, "target": 30}},
        {"v": {"lo": 10, "hi": 20, "target": 25}},
        {"h": {"lo": 10.555}},
        {"layer_code": "TOTAL"},
        {"plant_code": "XYZ"},
        {"source_note": "   "},
        {"status": "PASS"},
    ],
)
def test_shape_refusals_are_422(admin_client, admin_conn, clean, over):
    before = _total(admin_conn)
    response = admin_client.post(POST, json=body(**over))
    assert response.status_code == 422, response.text
    assert _total(admin_conn) == before


# ---------------------------------------------------------------- 8
def test_roles(engineer_client, client, admin_conn, clean):
    before = _total(admin_conn)
    assert engineer_client.post(POST, json=body()).status_code == 403
    assert client.post(POST, json=body()).status_code == 403
    assert _total(admin_conn) == before
    viewer_get = client.get(get_url("FTM"))
    assert viewer_get.status_code == 200, viewer_get.text
    assert set(viewer_get.json()) == {"plant_code", "rules", "colors"}


# ---------------------------------------------------------------- 9
@pytest.mark.parametrize(
    "statement",
    ["UPDATE film_standard SET lo = 1", "DELETE FROM film_standard"],
)
def test_app_role_cannot_update_or_delete(app_conn, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(statement)


# ---------------------------------------------------------------- 10
def test_meta_and_openapi(client):
    assert client.get("/api/v1/meta").json()["grading_available"] is False
    live = client.app.openapi()
    paths = {get_url("{plant_code}"): {"get"}, POST: {"post"}}
    for path, methods in paths.items():
        assert set(live["paths"][path]) == methods
    backend_copy = (REPO / "backend" / "openapi.json").read_bytes()
    assert backend_copy == (REPO / "docs" / "openapi.json").read_bytes()
    assert json.loads(backend_copy) == live
    schemas = live["components"]["schemas"]
    for name in ("FilmStandardsOut", "FilmLayerRuleOut", "FilmRuleOut"):
        props = set(schemas[name]["properties"])
        assert not props & {"status", "pass_rate", "passRate"}, name
