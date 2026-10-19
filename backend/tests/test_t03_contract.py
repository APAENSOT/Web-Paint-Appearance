"""T03 -- the API contract.

These tests run the real FastAPI application against the real PostgreSQL
database, as the real application role. That is deliberate. The claims T03
has to make are claims about a *running system*: that a superseded
measurement does not appear in a list, that a caller without a role is
refused, that the connection the API holds cannot delete a fact. A mocked
database cannot fail to hide a superseded row, so it would prove none of it.

Groups, in order:

1. configuration -- the flags that must fail closed
2. health
3. identity and RBAC
4. ``/api/v1/meta`` and D2 (no colour families, "unmapped" stated)
5. ``/api/v1/measurements`` and the active-data predicate
6. ``/api/v1/dashboard/preview`` and D1 (raw CF, no grade)
7. the error shape and correlation ids
8. CORS and hardening headers
9. the architecture rules that are cheap to break and expensive to notice
10. the committed OpenAPI artifact
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import ROLE_RANK
from app.main import create_app

pytestmark = pytest.mark.contract

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
APP_PACKAGE = BACKEND_ROOT / "app"

SENTINEL = "T03-CONTRACT"
#: A value with more significant digits than float4 can hold. It exists to
#: prove the NUMERIC column survives the whole trip: database -> psycopg ->
#: Decimal -> JSON. Under the pre-T02 REAL column this became 62.12346.
PRECISE_CF = "62.123456789012345"


# =====================================================================
# fixtures
# =====================================================================
def _settings(url: str, **overrides) -> Settings:
    base = dict(
        env="development",
        app_database_url=url,
        auth_dev_bypass=True,
        auth_dev_bypass_roles_raw="viewer",
        api_docs_enabled=True,
        # T04 starts an ingest worker with the app. This suite tests the
        # contract, not ingest, and a worker here would claim jobs another
        # suite's test is waiting on.
        ingest_worker_enabled=False,
    )
    base.update(overrides)
    return Settings(**base)


# T76 CHANGE: module scope, not session. Every test module that imports this
# fixture gets its own copy (pytest registers the import per module), so at
# session scope ~40 modules each kept their apps and connection pools open
# until the run ended -- past the cluster's 60 connections. Module scope
# tears each copy down (and disposes its engine) when its module is done.
@pytest.fixture(scope="module")
def make_client(app_database_url: str):
    created = []

    def _make(**overrides) -> TestClient:
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
def client(make_client) -> TestClient:
    """Authenticated as the default bypass identity: Viewer only."""
    return make_client()


@pytest.fixture(scope="module")
def engineer_client(make_client) -> TestClient:
    return make_client(auth_dev_bypass_roles_raw="engineer")


@pytest.fixture(scope="module")
def admin_client(make_client) -> TestClient:
    return make_client(auth_dev_bypass_roles_raw="admin")


@pytest.fixture(scope="module")
def anon_client(make_client) -> TestClient:
    """The production posture: no bypass, no OIDC yet, so no identity."""
    return make_client(auth_dev_bypass=False)


# Function-scoped on purpose. These rows change the row counts every other
# suite in this repo asserts on, so they must not outlive the test that
# needs them -- a session-scoped fixture here would make T02's results
# depend on collection order.
@pytest.fixture()
def hidden_rows(admin_conn, actor_user_id):
    """Rows that MUST NOT appear in any list endpoint, plus one that must.

    The demo fixture contains 63 rows and every one of them is active, so
    "the endpoint returned only active rows" would be vacuously true. These
    four rows make it falsifiable:

    ==========================  ==========================================
    serial_no                   why it is (in)visible
    ==========================  ==========================================
    T03-CONTRACT-ACTIVE         committed batch, not duplicate, not
                                superseded -> VISIBLE (positive control)
    T03-CONTRACT-DUP            is_duplicate = true          -> hidden
    T03-CONTRACT-SUPERSEDED     retired via measurement_supersession
                                                             -> hidden
    T03-CONTRACT-PENDING        batch status PENDING_REVIEW  -> hidden
    ==========================  ==========================================

    The superseded row is retired the way the schema requires: by inserting
    a ``measurement_supersession`` record and letting the AFTER INSERT
    trigger set the flag. There is no UPDATE of ``wavescan`` anywhere in
    this fixture -- not even by the owner, who could. Since revision 0003 the
    record must name an actor, so the fixture supplies one.
    """
    ids: dict[str, int] = {}
    batches: list[int] = []

    def measure(cur, load_id, source_row, serial, cf=PRECISE_CF, duplicate=False):
        cur.execute(
            """
            INSERT INTO wavescan (
                measured_date, plant, model, checkzone, color, tolerance_group,
                paintline, serial_no,
                lw, sw, cf, doi, du, wa, wb, wc, wd, we, b,
                load_id, source_sheet, source_row, is_duplicate)
            VALUES (DATE '2026-07-15', 'AAT', 'U704', 'RRHOOD', 'Arctic White',
                    'Horizontal', 'BOOTH1', %s,
                    1.5, 2.5, %s, 80.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, -1.25,
                    %s, 'Sheet1', %s, %s)
            RETURNING measurement_id
            """,
            (serial, cf, load_id, source_row, duplicate),
        )
        return cur.fetchone()[0]

    def batch(cur, tag, status, counts):
        digest = hashlib.sha256(f"{SENTINEL}:{tag}".encode()).hexdigest()
        cur.execute(
            """
            INSERT INTO load_batch (
                source_file, source_sheet, plant_code, file_hash, status,
                rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
                rows_quarantine, raw_store_key, finished_at, notes)
            VALUES (%s, 'Sheet1', 'AAT', %s, %s, %s, %s, %s, 0, 0, %s, now(), %s)
            RETURNING load_id
            """,
            (
                f"{SENTINEL} {tag}.xlsx",
                digest,
                status,
                counts[0],
                counts[1],
                counts[2],
                f"wavescan/raw/{digest}",
                f"{SENTINEL} test fixture; safe to delete",
            ),
        )
        load_id = cur.fetchone()[0]
        batches.append(load_id)
        return load_id

    with admin_conn.cursor() as cur:
        committed = batch(cur, "committed", "COMMITTED", (3, 2, 1))
        ids["active"] = measure(cur, committed, 1, f"{SENTINEL}-ACTIVE")
        ids["duplicate"] = measure(cur, committed, 2, f"{SENTINEL}-DUP", duplicate=True)
        ids["superseded"] = measure(cur, committed, 3, f"{SENTINEL}-SUPERSEDED")
        cur.execute(
            "INSERT INTO measurement_supersession "
            "(superseded_measurement_id, reason, actor_user_id) "
            "VALUES (%s, %s, %s)",
            (ids["superseded"], f"{SENTINEL}: retired so the API can be tested",
             actor_user_id),
        )
        pending = batch(cur, "pending", "PENDING_REVIEW", (1, 1, 0))
        ids["pending"] = measure(cur, pending, 1, f"{SENTINEL}-PENDING")

    # RO03 CHANGE: also expose the committed batch's load_id. A copy, so the
    # cleanup below still deletes by measurement ids only.
    yield {**ids, "committed_load_id": committed}

    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM measurement_supersession "
            "WHERE superseded_measurement_id = ANY(%s)",
            (list(ids.values()),),
        )
        cur.execute(
            "DELETE FROM wavescan WHERE measurement_id = ANY(%s)", (list(ids.values()),)
        )
        cur.execute("DELETE FROM load_batch WHERE load_id = ANY(%s)", (batches,))


def _json(response):
    assert response.headers["content-type"].startswith("application/json"), response.text
    return response.json()


def _walk(node, path="$"):
    """Yield (json path, key, value) for every key in a nested payload."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key, value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def _all_items(client) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        body = _json(
            client.get("/api/v1/measurements", params={"limit": 500, "offset": offset})
        )
        items.extend(body["items"])
        offset += body["page"]["limit"]
        if offset >= body["page"]["total"]:
            return items


# =====================================================================
# 1. configuration -- the flags that must fail closed
# =====================================================================
@pytest.mark.parametrize("env", ["production", "staging", "test", "prod"])
def test_dev_bypass_is_refused_outside_development(env, app_database_url):
    """L11 / 03-SECURITY.md section 4. Not a warning -- a refusal."""
    with pytest.raises(ValueError, match="AUTH_DEV_BYPASS"):
        _settings(app_database_url, env=env, auth_dev_bypass=True)


def test_dev_bypass_off_is_fine_outside_development(app_database_url):
    settings = _settings(app_database_url, env="production", auth_dev_bypass=False)
    assert settings.is_development is False


@pytest.mark.parametrize("role", ["postgres", "migrator", "POSTGRES"])
def test_a_privileged_database_role_is_refused_by_configuration(role):
    """The task's rule: connect as app_rw, never as postgres or the migrator."""
    with pytest.raises(ValueError, match="app_rw only"):
        Settings(app_database_url=f"postgresql+psycopg://{role}@127.0.0.1:5432/x")


def test_a_privileged_connection_is_refused_even_when_the_role_name_is_innocent(
    admin_conn, app_database_url, make_client
):
    """The name check above is the cheap half. This is the half that matters:
    a role called anything at all, holding privileges T01 removed, must not
    be able to serve data. Every physical connection is interrogated, so the
    grants are enforced even when the URL looks fine."""
    from sqlalchemy.engine import make_url

    url = make_url(app_database_url).set(username="t03_guard_probe", password=None)
    with admin_conn.cursor() as cur:
        cur.execute("DROP ROLE IF EXISTS t03_guard_probe")
        cur.execute("CREATE ROLE t03_guard_probe LOGIN SUPERUSER")
    try:
        probe = make_client(app_database_url=url.render_as_string(hide_password=False))
        ready = probe.get("/health/ready")
        assert ready.status_code == 503
        detail = _json(ready)["checks"]["database"]
        assert detail["status"] == "refused"
        assert "SUPERUSER" in detail["detail"]
        # and no data route will serve through it
        data = probe.get("/api/v1/measurements")
        assert data.status_code == 503
        assert set(_json(data)) == {"statusCode", "error", "message", "correlationId"}
    finally:
        with admin_conn.cursor() as cur:
            cur.execute("DROP ROLE IF EXISTS t03_guard_probe")


def test_an_unknown_bypass_role_is_refused(app_database_url):
    with pytest.raises(ValueError, match="unknown role"):
        _settings(app_database_url, auth_dev_bypass_roles_raw="superadmin")


def test_a_blank_bypass_env_var_is_treated_as_unset(app_database_url, monkeypatch):
    """`.env.example` used to ship `AUTH_DEV_BYPASS=`. pydantic-settings
    then tried to parse '' as a bool and the process refused to start --
    the opposite of fail-closed. Empty means unset, so the default (false)
    applies."""
    monkeypatch.setenv("AUTH_DEV_BYPASS", "")
    monkeypatch.setenv("AUTH_DEV_BYPASS_UPN", "")
    settings = Settings(app_database_url=app_database_url)
    assert settings.auth_dev_bypass is False
    assert settings.auth_dev_bypass_upn == "dev.bypass@localhost"


def test_the_api_never_reads_the_migrator_url():
    """MIGRATOR_DATABASE_URL is the DDL credential. If the API could fall
    back to it, every grant T01 wrote would be advisory."""
    sources = "\n".join(p.read_text(encoding="utf-8") for p in APP_PACKAGE.rglob("*.py"))
    assert "MIGRATOR_DATABASE_URL" not in sources


# =====================================================================
# 2. health
# =====================================================================
def test_liveness_does_not_touch_the_database(make_client):
    """A database outage must not make the process look dead."""
    broken = make_client(app_database_url="")
    assert _json(broken.get("/health/live"))["status"] == "alive"


def test_liveness_needs_no_authentication(anon_client):
    assert anon_client.get("/health/live").status_code == 200


def test_readiness_reports_the_database_and_the_object_store(client):
    body = _json(client.get("/health/ready"))
    assert body["status"] == "ready"
    assert body["checks"]["database"]["status"] == "ok"
    # T04 gave the process a raw object store, so readiness now checks it
    # rather than reporting it absent. A batch whose bytes cannot be read
    # back can be neither replayed nor committed.
    assert body["checks"]["object_store"]["status"] == "ok"


def test_readiness_publishes_the_connection_identity(client):
    """The proof that this process holds no destructive privilege is
    something an operator can curl, not something a report asserts."""
    db = _json(client.get("/health/ready"))["checks"]["database"]
    assert db["is_superuser"] is False
    assert db["forbidden_privileges_held"] == []
    assert db["role"] != "postgres"


def test_readiness_is_503_when_the_database_is_not_configured(make_client):
    broken = make_client(app_database_url="")
    response = broken.get("/health/ready")
    assert response.status_code == 503
    assert _json(response)["checks"]["database"]["status"] == "not_configured"


# =====================================================================
# 3. identity and RBAC
# =====================================================================
def test_auth_me_returns_the_bypass_identity_in_development(client):
    body = _json(client.get("/api/v1/auth/me"))
    assert body["principal"]["auth_source"] == "dev-bypass"
    assert body["principal"]["roles"] == ["viewer"]
    assert body["environment"] == "development"


def test_auth_me_states_the_d3_stand_in_rather_than_implying_it(client):
    body = _json(client.get("/api/v1/auth/me"))
    assert body["plant_scope"] is None
    assert "D3" in body["plant_scope_note"]


def test_without_the_bypass_there_is_no_identity(anon_client):
    response = anon_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_an_unverified_bearer_token_is_refused_not_trusted(client):
    """Reading claims out of a token this build cannot verify would be an
    authentication bypass with extra steps."""
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer eyJhbGciOiJub25lIn0.e30."},
    )
    assert response.status_code == 401
    assert "not accepted yet" in _json(response)["message"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/meta", "/api/v1/measurements", "/api/v1/dashboard/preview",
        # T19 reads. Admin routes, so an anonymous caller is refused before
        # the role check is even reached.
        "/api/v1/plants/AAT/workbooks",
        "/api/v1/plants/AAT/workbooks/" + "0" * 64,
        "/api/v1/plants/AAT/workbooks/" + "0" * 64 + "/rows",
        "/api/v1/plants/AAT/workbooks/" + "0" * 64 + "/issues",
        "/api/v1/plants/AAT/workbooks/" + "0" * 64 + "/history",
        # T23 History reads. Any authenticated role may read them, which is
        # exactly why the anonymous case has to be asserted: "not Admin" must
        # not become "not authenticated".
        "/api/v1/plants/AAT/history/facets",
        "/api/v1/plants/AAT/history/summaries?month=2026-07",
        "/api/v1/plants/AAT/history/vehicles?month=2026-07&week=1&model=U704&color=Green",
        "/api/v1/plants/AAT/history/vehicles/" + "0" * 64 + "/points",
        "/api/v1/standards/catalogue",
        "/api/v1/plants/FTM/wavescan/overview?month=2026-09",
    ],
)
def test_every_read_route_requires_authentication(anon_client, path):
    assert anon_client.get(path).status_code == 401


#: docs/03-SECURITY.md section 5, the mutating rows of the matrix.
#:
#: T04 implemented two of them -- POST /api/v1/uploads and
#: POST /api/v1/batches/{load_id}/commit -- at the same paths and with the
#: same required role, so they moved out of this list and into
#: IMPLEMENTED_MUTATIONS below. The RBAC half of every row is still asserted
#: for all seven; what changed is only what a *sufficient* role now gets.
#:
#: T08 CHANGE: the two mapping routes left this list. They are implemented at
#: the same paths, with the same required roles, in `api/v1/mappings.py` --
#: the same way T04 moved upload and commit. Three reserved routes remain:
#: corrections and supersede are T09 (both write against data that has
#: already become facts), and `POST /standards` waits on D2.
#:
#: T09 CHANGE: the correction and the batch supersede left this list. Both are
#: implemented at the same paths with the same required roles, in
#: `api/v1/measurements.py` and `api/v1/batches.py`.
#:
#: T-STANDARDS-D2 CHANGE: `POST /standards` leaves this list. Admin catalogue
#: mint/offered/attach ship with it. `reserved.py` is empty. D1 stays open.
RESERVED_ROUTES: list[tuple[str, str, str]] = []

#: Implemented in T04, T08, T09, T19, T21, T25, and T-STANDARDS-D2. A Viewer
#: must still get 403 on every one, and an Engineer must still get 403 on
#: every Admin one -- which is what the tests below assert, unchanged.
IMPLEMENTED_MUTATIONS = [
    ("POST", "/api/v1/uploads", "engineer"),
    ("POST", "/api/v1/batches/1/commit", "engineer"),
    ("POST", "/api/v1/mappings/proposals", "engineer"),
    ("POST", "/api/v1/mappings/proposals/x/approve", "admin"),
    ("POST", "/api/v1/measurements/1/corrections", "engineer"),
    ("POST", "/api/v1/batches/1/supersede", "admin"),
    # T19: the plant Data Manager's only mutation. Admin, like every other
    # route under /plants/{plant_code}/workbooks -- and unlike upload and
    # commit, whose Engineer role T19 deliberately does not touch.
    ("POST", "/api/v1/plants/1/workbooks/1/acknowledgements", "admin"),
    # T21: the review override and the pre-commit abandon. Both Admin, like
    # the rest of the Data Manager and like supersede, which abandon sits
    # beside. Upload and commit keep their Engineer role.
    ("POST", "/api/v1/plants/1/workbooks/1/overrides", "admin"),
    ("POST", "/api/v1/batches/1/abandon", "admin"),
    # T25: bring one ABANDONED or SUPERSEDED sheet back. Admin, like abandon
    # and supersede, which it reverses. The identical-file door is the
    # existing upload route and keeps its Engineer role.
    ("POST", "/api/v1/batches/1/restore", "admin"),
    ("POST", "/api/v1/standards", "admin"),
    ("POST", "/api/v1/standards/colours", "admin"),
    ("POST", "/api/v1/standards/plant-colours", "admin"),
    ("POST", "/api/v1/standards/plant-models", "admin"),
    ("POST", "/api/v1/standards/plant-models/offered", "admin"),
]

ALL_MUTATIONS = RESERVED_ROUTES + IMPLEMENTED_MUTATIONS


@pytest.mark.parametrize("method,path,required", ALL_MUTATIONS)
def test_a_viewer_is_refused_every_mutating_route(client, method, path, required):
    """Deny by default, from day one -- the reason these routes exist now."""
    assert client.request(method, path).status_code == 403


@pytest.mark.parametrize("method,path,required", ALL_MUTATIONS)
def test_an_unauthenticated_caller_is_refused_every_mutating_route(
    anon_client, method, path, required
):
    assert anon_client.request(method, path).status_code == 401


def test_no_mutating_route_stays_reserved():
    """Plant-scoped D2 shipped POST /standards. The reserved stub list is empty."""
    assert RESERVED_ROUTES == []


@pytest.mark.parametrize(
    "method,path", [(m, p) for m, p, required in ALL_MUTATIONS if required == "admin"]
)
def test_an_engineer_cannot_reach_an_admin_route(engineer_client, method, path):
    assert engineer_client.request(method, path).status_code == 403


def test_admin_outranks_engineer_outranks_viewer():
    """The section 5 matrix is monotone; ROLE_RANK encodes that and nothing
    more. If a capability is ever added that an Admin must NOT have, this
    assumption breaks and so does this test."""
    assert ROLE_RANK["admin"] > ROLE_RANK["engineer"] > ROLE_RANK["viewer"]


def test_no_route_is_left_unguarded(client, anon_client):
    """Every route except health and the OpenAPI surface must demand an
    identity. A new router added without a dependency fails here."""
    spec = client.get("/openapi.json").json()
    public = {"/health/live", "/health/ready"}
    for path, operations in spec["paths"].items():
        if path in public:
            continue
        for method in operations:
            concrete = re.sub(r"\{[^}]+\}", "1", path)
            response = anon_client.request(method.upper(), concrete)
            assert response.status_code == 401, (
                f"{method.upper()} {path} -> {response.status_code}"
            )


# =====================================================================
# 4. /api/v1/meta and D2
# =====================================================================
def test_meta_returns_the_reference_data_the_filters_need(client):
    body = _json(client.get("/api/v1/meta"))
    assert {p["plant_code"] for p in body["plants"]} >= {"AAT", "FTM"}
    assert {m["model_code"] for m in body["models"]} >= {"U704"}
    assert len(body["colors"]) >= 13
    # 49 canonical zones from the base schema, plus the SAP vocabulary the
    # later baseline files add. The exact count is data-dependent; the
    # floor is not.
    assert len(body["checkzones"]) >= 49


def test_meta_returns_no_colour_families(client, admin_conn):
    """D2 is the owner's. The six seeded families exist so a colour can be
    mapped later; publishing them now would let a client build a family
    filter that matches nothing and grade with it."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT family_name FROM ref_color_family")
        seeded = [r[0] for r in cur.fetchall()]
    assert len(seeded) == 6

    raw = client.get("/api/v1/meta").text
    for family in seeded:
        assert family not in raw, f"{family!r} leaked into /api/v1/meta"

    body = _json(client.get("/api/v1/meta"))
    assert "families" not in body
    assert "color_families" not in body


def test_every_colour_states_that_it_is_unmapped(client):
    body = _json(client.get("/api/v1/meta"))
    # Plant-scoped D2: offered rows have families; the unused global column
    # stays NULL, so ColorOut still reports unmapped. unmapped_color_count is
    # offered plant-colours with a null family, not len(colors).
    assert body["unmapped_color_count"] == 0
    for colour in body["colors"]:
        assert colour["grading_family"] is None
        assert colour["grading_family_status"] == "unmapped"


def test_color_group_is_never_used_as_the_grading_family(client):
    """AGENTS.md section 4 lists this substitution as a defect. Several
    colours have a colour group; none of them acquire a family from it."""
    body = _json(client.get("/api/v1/meta"))
    with_group = [c for c in body["colors"] if c["color_group"]]
    assert with_group, "fixture has no colour groups, so this proves nothing"
    for colour in with_group:
        assert colour["grading_family"] is None


def test_meta_says_grading_is_unavailable(client):
    assert _json(client.get("/api/v1/meta"))["grading_available"] is False


# =====================================================================
# 5. /api/v1/measurements and the active-data predicate
# =====================================================================
def test_the_list_returns_active_rows(client, hidden_rows):
    body = _json(client.get("/api/v1/measurements", params={"limit": 500}))
    assert body["page"]["total"] >= 1
    assert body["active_data_source"] == "v_wavescan_active"


def test_a_duplicate_row_is_not_listed(client, hidden_rows):
    ids = {item["measurement_id"] for item in _all_items(client)}
    assert hidden_rows["duplicate"] not in ids


def test_a_superseded_row_is_not_listed(client, hidden_rows):
    ids = {item["measurement_id"] for item in _all_items(client)}
    assert hidden_rows["superseded"] not in ids


def test_a_row_in_an_uncommitted_batch_is_not_listed(client, hidden_rows):
    ids = {item["measurement_id"] for item in _all_items(client)}
    assert hidden_rows["pending"] not in ids


def test_the_positive_control_is_listed(client, hidden_rows):
    """Without this, the three tests above would pass on an endpoint that
    returns nothing at all."""
    ids = {item["measurement_id"] for item in _all_items(client)}
    assert hidden_rows["active"] in ids


def test_the_api_total_equals_the_view_and_not_the_table(client, admin_conn, hidden_rows):
    """The number a dashboard shows has to be the view's number."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM v_wavescan_active")
        view_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM wavescan")
        table_count = cur.fetchone()[0]
    assert view_count < table_count, "fixture did not create hidden rows"
    assert _json(client.get("/api/v1/measurements"))["page"]["total"] == view_count


def test_measurements_keep_full_numeric_precision(client, hidden_rows):
    """L12: stored NUMERIC at full precision, rounded only for display.
    float4 would have returned 62.12346 here."""
    # RO03 CHANGE: narrowed to the fixture's committed batch (`load_id`, T19),
    # as T76; only its ACTIVE row is live (DUP and SUPERSEDED are hidden).
    body = _json(client.get(
        "/api/v1/measurements",
        params={"limit": 500, "plant": "AAT", "load_id": hidden_rows["committed_load_id"]},
    ))
    assert body["page"]["total"] == 1, body["page"]
    row = next(i for i in body["items"] if i["measurement_id"] == hidden_rows["active"])
    assert row["cf"] == PRECISE_CF
    assert Decimal(row["cf"]) == Decimal(PRECISE_CF)


def test_measurements_are_carried_as_strings_not_floats(client):
    """A JSON number is an IEEE-754 double in every browser. Sending the
    decimal text is what makes the precision above survive the client."""
    body = _json(client.get("/api/v1/measurements", params={"limit": 1}))
    assert body["items"], "no active rows; this would prove nothing"
    assert isinstance(body["items"][0]["cf"], str)


@pytest.mark.parametrize(
    "param,value",
    [
        ("plant", "AAT"),
        ("model", "U704"),
        ("color", "Traction Green"),
        ("checkzone", "RRHOOD"),
    ],
)
def test_each_filter_actually_filters(client, param, value):
    body = _json(client.get("/api/v1/measurements", params={param: value, "limit": 500}))
    assert body["items"], f"{param}={value} matched nothing; the filter proves nothing"
    assert {item[param] for item in body["items"]} == {value}
    assert body["filters"][param] == value


def test_the_date_range_filters(client):
    body = _json(
        client.get(
            "/api/v1/measurements",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30", "limit": 500},
        )
    )
    assert body["items"], "June 2026 matched nothing; this would prove nothing"
    for item in body["items"]:
        assert "2026-06-01" <= item["measured_date"] <= "2026-06-30"


def test_a_backwards_date_range_is_rejected(client):
    response = client.get(
        "/api/v1/measurements",
        params={"date_from": "2026-07-01", "date_to": "2026-06-01"},
    )
    assert response.status_code == 422


def test_an_unknown_plant_returns_an_empty_page_not_an_error(client):
    body = _json(client.get("/api/v1/measurements", params={"plant": "ZZZ"}))
    assert body["items"] == []
    assert body["page"]["total"] == 0


def test_paging_is_stable_and_does_not_repeat_rows(client):
    first = _json(client.get("/api/v1/measurements", params={"limit": 10, "offset": 0}))
    second = _json(client.get("/api/v1/measurements", params={"limit": 10, "offset": 10}))
    assert first["page"]["total"] == second["page"]["total"]
    ids = [i["measurement_id"] for i in first["items"]] + [
        i["measurement_id"] for i in second["items"]
    ]
    assert len(ids) == len(set(ids))


def test_the_page_size_is_bounded(client):
    assert client.get("/api/v1/measurements", params={"limit": 100000}).status_code == 422
    assert client.get("/api/v1/measurements", params={"limit": 0}).status_code == 422


def test_a_measurement_is_traceable_back_to_its_source_cell(client):
    """A number a plant disputes has to lead back to the cell it came from."""
    body = _json(client.get("/api/v1/measurements", params={"limit": 1}))
    assert body["items"], "no active rows"
    row = body["items"][0]
    assert row["load_id"] and row["source_sheet"] and row["source_row"]


# =====================================================================
# 6. /api/v1/dashboard/preview and D1
# =====================================================================
#: Anything that would answer D1 without the owner. `min`/`ford` are the
#: standards' own field names (04-ANALYSIS.md); a mean or a count per series
#: asserts that the series key IS the grouping key, which is the open question.
BANNED_KEYS = {
    "grade", "grades", "status", "state", "verdict", "result",
    "pass", "fail", "warn", "passed", "failed",
    "pass_rate", "passrate", "pass_count", "fail_count", "warn_count",
    "ribbon", "ford", "min", "max", "mean", "avg", "average", "median",
    "stddev", "std", "p95", "count", "n", "target", "threshold", "tolerance",
    "score", "ok",
}
BANNED_VALUES = {"PASS", "WARN", "FAIL", "OK", "NG"}


def test_the_preview_returns_raw_cf_and_its_dimensions(client):
    body = _json(client.get("/api/v1/dashboard/preview", params={"dimension": "checkzone"}))
    assert body["dimension"] == "checkzone"
    assert body["series"], "no series; the assertions below would be vacuous"
    point = body["series"][0]["points"][0]
    assert set(point) == {
        "measurement_id",
        "measured_date",
        "plant",
        "model",
        "color",
        "checkzone",
        "tolerance_group",
        "cf",
    }
    Decimal(point["cf"])


@pytest.mark.parametrize("dimension", ["checkzone", "color"])
def test_the_series_key_is_the_requested_dimension(client, dimension):
    body = _json(client.get("/api/v1/dashboard/preview", params={"dimension": dimension}))
    assert body["series"]
    for series in body["series"]:
        assert {p[dimension] for p in series["points"]} == {series["key"]}


@pytest.mark.parametrize("dimension", ["checkzone", "color"])
def test_the_preview_contains_no_grade_and_no_aggregate(client, dimension):
    """D1 stays open in the payload, not just in the documentation."""
    body = _json(client.get("/api/v1/dashboard/preview", params={"dimension": dimension}))
    for path, key, value in _walk(body):
        assert key.lower() not in BANNED_KEYS, f"{path} would answer D1"
        if isinstance(value, str):
            assert value.upper() not in BANNED_VALUES, f"{path} = {value!r}"


def test_the_preview_says_it_is_ungraded(client):
    body = _json(client.get("/api/v1/dashboard/preview"))
    assert body["grading_available"] is False
    assert "D1" in body["grading_note"]


def test_the_preview_response_schema_declares_no_grading_field(client):
    """Belt and braces: the payload could be clean because today's fixture
    is small. The published schema is what the frontend is generated from."""
    spec = client.get("/openapi.json").json()
    for name, schema in spec["components"]["schemas"].items():
        if not name.startswith(("Dashboard", "Preview")):
            continue
        for prop in schema.get("properties", {}):
            assert prop.lower() not in BANNED_KEYS, f"{name}.{prop} would answer D1"


def test_the_preview_hides_the_same_rows_the_list_hides(client, hidden_rows):
    body = _json(client.get("/api/v1/dashboard/preview", params={"point_limit": 20000}))
    plotted = {p["measurement_id"] for s in body["series"] for p in s["points"]}
    assert hidden_rows["active"] in plotted
    for name in ("duplicate", "superseded", "pending"):
        assert hidden_rows[name] not in plotted


def test_an_unknown_dimension_is_rejected(client):
    response = client.get("/api/v1/dashboard/preview", params={"dimension": "serial_no"})
    assert response.status_code == 422


def test_a_sql_fragment_as_a_dimension_is_rejected(client):
    """The dimension is the one caller value that reaches a column position."""
    response = client.get(
        "/api/v1/dashboard/preview",
        params={"dimension": "checkzone; DROP TABLE wavescan"},
    )
    assert response.status_code == 422


def test_the_preview_reports_truncation_rather_than_lying(client):
    body = _json(client.get("/api/v1/dashboard/preview", params={"point_limit": 2}))
    plotted = sum(len(s["points"]) for s in body["series"])
    assert plotted == 2
    assert body["truncated"] is True


# =====================================================================
# 7. the error shape and correlation ids
# =====================================================================
ERROR_KEYS = {"statusCode", "error", "message", "correlationId"}


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/api/v1/does-not-exist", 404),
        ("GET", "/api/v1/measurements?limit=0", 422),
        ("POST", "/api/v1/uploads", 403),
    ],
)
def test_every_failure_has_the_documented_shape(client, method, path, expected):
    response = client.request(method, path)
    assert response.status_code == expected
    body = _json(response)
    assert set(body) == ERROR_KEYS, body
    assert body["statusCode"] == expected
    assert isinstance(body["message"], str) and body["message"]


def test_an_unauthenticated_failure_has_the_documented_shape(anon_client):
    assert set(_json(anon_client.get("/api/v1/meta"))) == ERROR_KEYS


def test_a_client_correlation_id_is_echoed(client):
    response = client.get("/api/v1/meta", headers={"X-Correlation-ID": "page-load-42"})
    assert response.headers["x-correlation-id"] == "page-load-42"


def test_a_correlation_id_is_generated_when_the_client_sends_none(client):
    assert len(client.get("/api/v1/meta").headers["x-correlation-id"]) == 32


def test_the_correlation_id_in_the_body_matches_the_header(anon_client):
    response = anon_client.get("/api/v1/meta", headers={"X-Correlation-ID": "abc-123"})
    assert _json(response)["correlationId"] == "abc-123"
    assert response.headers["x-correlation-id"] == "abc-123"


def test_a_hostile_correlation_id_is_stripped(client):
    """It lands in a log file and in a response header."""
    response = client.get(
        "/api/v1/meta", headers={"X-Correlation-ID": "a-b_c:1.2-OK"}
    )
    assert response.headers["x-correlation-id"] == "a-b_c:1.2-OK"
    response = client.get("/api/v1/meta", headers={"X-Correlation-ID": "a b<script>"})
    assert response.headers["x-correlation-id"] == "abscript"


def test_no_stack_trace_or_dsn_reaches_a_client(make_client):
    """A 503 must not describe the connection it failed to make."""
    broken = make_client(app_database_url="postgresql+psycopg://app_rw@127.0.0.1:1/nope")
    response = broken.get("/api/v1/meta")
    assert response.status_code == 503
    body = _json(response)
    assert set(body) == ERROR_KEYS
    assert "Traceback" not in body["message"]
    assert "127.0.0.1" not in body["message"]


# =====================================================================
# 8. CORS and hardening headers
# =====================================================================
def test_the_frontend_origin_is_allowed(client):
    response = client.get("/health/live", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_an_unlisted_origin_gets_no_cors_grant(client):
    response = client.get("/health/live", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_is_an_allowlist_not_a_wildcard(client):
    """Credentials are sent (the refresh cookie is httpOnly), so a wildcard
    would be both invalid and dangerous."""
    assert "*" not in client.app.state.settings.cors_origins


def test_hardening_headers_are_present(client):
    headers = client.get("/health/live").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"


def test_hsts_is_not_sent_in_development(client):
    """Pinning a browser to HTTPS on localhost breaks the next developer."""
    assert "strict-transport-security" not in client.get("/health/live").headers


# =====================================================================
# 9. architecture rules
# =====================================================================
PREDICATE_TOKENS = ("is_duplicate", "is_superseded", "COMMITTED")

#: The two flags have no legitimate use in the package's *code*: nothing sets
#: them (a T02 trigger does) and nothing filters on them (the view does).
#: Checked against `_code_only`, so a module may explain in prose why it
#: leaves them alone -- see that helper for why T09 needed the distinction.
FLAG_TOKENS = ("is_duplicate", "is_superseded")

#: A statement, not a sentence: prose about committing a batch says "COMMITTED"
#: without being a query, and the point of this check is queries.
_SQL_STATEMENT = re.compile(
    r"SELECT.+?FROM.*?(?:$|\"\"\")"
    r"|INSERT\s+INTO.*?(?:$|\"\"\")"
    r"|UPDATE.+?SET.*?(?:$|\"\"\")"
    r"|DELETE\s+FROM.*?(?:$|\"\"\")",
    re.I | re.S,
)


def _sql_statements(source: str) -> list[str]:
    """Every SQL statement in the file.

    T04 gave `COMMITTED` a second, legitimate meaning: it is one of the six
    values of `load_batch.status` (`01-DATA-MODEL.md` §3), so a constant and a
    DTO Literal carry the word for reasons that have nothing to do with
    reading measurements. What must stay true is narrower, and is what this
    extracts: the predicate must not appear in a *query*.
    """
    return [m.group(0) for m in _SQL_STATEMENT.finditer(source)]


def _without_comments(path: Path) -> str:
    """Source with ``#`` comments removed and nothing else.

    Docstrings are deliberately NOT stripped: the SQL in this package lives
    inside triple-quoted strings, so a checker that ignored them would be
    blind to exactly the code it exists to inspect.
    """
    text = path.read_text(encoding="utf-8")
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def _code_only(path: Path) -> str:
    """Source with ``#`` comments and **docstrings** removed.

    T09 CHANGE. The flag check below used to run over the whole file, which was
    right while nothing in the package had any reason to mention
    ``is_duplicate`` or ``is_superseded``. T09 added the modules whose entire
    job is to leave those columns alone -- a correction is a new row, and the
    retirement flag is set by a T02 trigger -- and a module has to be able to
    say that. Prose explaining why a column is untouched is the opposite of a
    violation; naming it in code is the violation.

    So docstrings go and every other literal stays: ``row["is_superseded"]``
    and ``is_superseded=True`` both survive this, which is what the check is
    for. The SQL half of the test still reads the unstripped source, because
    this package's SQL lives in ``text(...)`` arguments, not in docstrings.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    blanked: set[int] = set()
    for node in ast.walk(ast.parse("\n".join(lines))):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            blanked.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))
    return "\n".join(
        "" if n in blanked or line.lstrip().startswith("#") else line
        for n, line in enumerate(lines, start=1)
    )


def test_the_active_data_predicate_is_not_re_implemented_in_python():
    """01-DATA-MODEL.md section 10 and the T03 brief: the predicate lives in
    ``v_wavescan_active`` and nowhere else. A copy in Python is a second
    definition, and the first time the two disagree the API publishes a
    retired measurement as current."""
    offenders = []
    for path in APP_PACKAGE.rglob("*.py"):
        code = _without_comments(path)
        for token in FLAG_TOKENS:
            if token in _code_only(path):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token}")
        for fragment in _sql_statements(code):
            for token in PREDICATE_TOKENS:
                if token in fragment:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}: {token} in SQL: "
                        f"{fragment.strip()[:80]}"
                    )
    assert not offenders, offenders


def test_routers_contain_no_sql():
    """00-ARCHITECTURE.md section 5, rule 2."""
    # Matched on SQL syntax, not on the bare keywords: several of these
    # modules discuss DELETE and UPDATE privileges in prose, which is the
    # point of them.
    sql = re.compile(
        r"\bSELECT\b.+\bFROM\b|\bINSERT\s+INTO\b|\bUPDATE\b.+\bSET\b|\bDELETE\s+FROM\b",
        re.I | re.S,
    )
    for path in (APP_PACKAGE / "api").rglob("*.py"):
        assert not sql.search(_without_comments(path)), f"SQL in router {path.name}"


def test_the_domain_package_imports_no_framework():
    """00-ARCHITECTURE.md section 5, rule 1. Empty today; checked now so T04
    cannot land the first violation unnoticed."""
    for path in (APP_PACKAGE / "domain").rglob("*.py"):
        code = path.read_text(encoding="utf-8")
        for banned in ("import fastapi", "from fastapi", "import psycopg", "import sqlalchemy"):
            assert banned not in code, f"{path.name} imports {banned}"


def test_only_one_module_decides_plant_visibility():
    """D3's seam. A second place that filters by plant is the "third scheme"
    03-SECURITY.md section 5 forbids T03 from inventing."""
    hits = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in APP_PACKAGE.rglob("*.py")
        if "visible_plants" in path.read_text(encoding="utf-8")
    )
    assert "backend/app/core/scoping.py" in hits
    # definition + the filter dependency + the /auth/me disclosure
    assert len(hits) <= 3, hits


#: T05 CHANGE: the one module allowed to carry them. T03 wrote this test when
#: no such file existed, so "nowhere" and "one place" were the same assertion.
#: They are not any more: T05 ported the rule, and `AGENTS.md` section 5 says
#: where it goes. Naming the exemption keeps the test doing the job its own
#: docstring describes -- a second `statusOf`, in a router or a DTO or a
#: repository, still fails here.
GRADING_MODULE = "domain/grading.py"


def test_no_prototype_grading_symbol_leaks_into_the_api():
    """AGENTS.md section 5: one grading implementation, in domain/grading.py,
    behind T05. Not a threshold in SQL, not a statusOf in a DTO.

    T76 CHANGE: docstrings are prose, not code. T67's
    `schemas/filmthickness.py` docstring names `statusOf` only to say Film
    does not use it. `_code_only` (T09) drops docstrings and comments and
    keeps every other literal, so a symbol in code or in a `text(...)` SQL
    string still fails here.
    """
    for path in APP_PACKAGE.rglob("*.py"):
        if path.as_posix().endswith(GRADING_MODULE):
            continue
        code = _code_only(path)
        for token in ("fordH", "fordV", "minH", "minV", "stdPair", "targetsFor", "statusOf"):
            assert token not in code, f"{path.name} carries prototype grading symbol {token}"


def test_the_grading_module_is_the_only_thing_that_exemption_covers():
    """The exemption above is a named hole. This is the assertion that keeps it
    one file wide, and that keeps that file real -- a rename that quietly moved
    grading into a router would otherwise pass both tests."""
    exempt = [
        path.as_posix() for path in APP_PACKAGE.rglob("*.py")
        if path.as_posix().endswith(GRADING_MODULE)
    ]
    assert len(exempt) == 1, exempt


def test_no_undeclared_write_route_exists(client):
    """Every non-GET route is either implemented by T04 at a path the RBAC
    matrix already named, or a reserved stub. A new mutating URL that nobody
    recorded fails here."""
    spec = client.get("/openapi.json").json()
    reserved = {re.sub(r"/\w+$", "", p) for _, p, _ in ALL_MUTATIONS}
    for path, operations in spec["paths"].items():
        for method in operations:
            if method.lower() == "get":
                continue
            concrete = re.sub(r"\{[^}]+\}", "1", path)
            assert concrete in {p for _, p, _ in ALL_MUTATIONS} or any(
                concrete.startswith(prefix) for prefix in reserved
            ), f"{method} {path} is neither a GET nor a reserved stub"


# =====================================================================
# 10. the committed OpenAPI artifact
# =====================================================================
BACKEND_SPEC = BACKEND_ROOT / "openapi.json"
DOCS_SPEC = REPO_ROOT / "docs" / "openapi.json"


def test_the_backend_openapi_artifact_matches_the_running_app(client):
    """T03 acceptance: "docs/openapi.json committed and matches running app".
    Regenerate with ``python scripts/emit_openapi.py``."""
    assert BACKEND_SPEC.exists(), f"missing {BACKEND_SPEC}; run scripts/emit_openapi.py"
    committed = json.loads(BACKEND_SPEC.read_text(encoding="utf-8"))
    assert committed == client.app.openapi()


def test_the_docs_copy_is_identical_to_the_backend_artifact():
    """05-PHASE-PLAN.md: generated in backend/, copied to docs/. Two files
    that drift are worse than one."""
    assert DOCS_SPEC.exists(), f"missing {DOCS_SPEC}"
    assert json.loads(DOCS_SPEC.read_text(encoding="utf-8")) == json.loads(
        BACKEND_SPEC.read_text(encoding="utf-8")
    )


def test_every_dto_forbids_unknown_fields(client):
    """T03 item 3. No route takes a JSON body yet, so this is checked on the
    schemas themselves: the base model sets extra='forbid', which pydantic
    emits as additionalProperties: false."""
    spec = client.get("/openapi.json").json()
    # `03-SECURITY.md` §7 says "extra fields forbidden **where it does not
    # break multipart**". FastAPI synthesises a Body_* model for a multipart
    # form and that model is not a JSON body, so it is excluded by name
    # rather than by loosening the rule for everything else.
    lax = [
        name
        for name, schema in spec["components"]["schemas"].items()
        if schema.get("type") == "object"
        and not name.startswith(("HTTPValidationError", "ValidationError", "Body_"))
        and schema.get("additionalProperties") is not False
    ]
    assert not lax, lax


def test_swagger_is_reachable(client):
    """The acceptance criterion says Swagger works. Docker is absent on this
    machine, so it is proven against a local database instead -- see
    docs/reports/T03-CONTRACT.md."""
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_the_error_shape_is_published_for_generated_clients(client):
    spec = client.get("/openapi.json").json()
    error = spec["components"]["schemas"]["ErrorResponse"]
    assert set(error["properties"]) == ERROR_KEYS
