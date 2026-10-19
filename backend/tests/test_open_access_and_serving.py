"""Owner decision 2026-10-20: no sign-in this release; one-origin Cloud Run serving.

No database: the engine is created lazily and these routes never touch it.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import ROLES, Settings
from app.core.security import resolve_principal
from app.main import create_app

DB = "postgresql+psycopg://app_rw@127.0.0.1:1/unused"


def _request(settings, headers=()):
    app = FastAPI()
    app.state.settings = settings
    scope = {"type": "http", "app": app, "headers": [(k.encode(), v.encode()) for k, v in headers]}
    return Request(scope)


def test_open_access_is_one_shared_account_with_every_role_in_production():
    settings = Settings(env="production", app_database_url=DB, auth_open_access=True)
    principal = resolve_principal(_request(settings))
    assert principal.auth_source == "open-access"
    assert principal.roles == list(ROLES) and principal.has_role("admin")
    # A platform token in front of the service is not refused in this mode.
    assert resolve_principal(_request(settings, [("authorization", "Bearer x")])).upn == principal.upn


def test_open_access_and_dev_bypass_cannot_both_be_on():
    with pytest.raises(ValueError, match="both set"):
        Settings(env="development", app_database_url=DB, auth_open_access=True, auth_dev_bypass=True)


def test_without_open_access_production_still_refuses():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        resolve_principal(_request(Settings(env="production", app_database_url=DB)))
    assert caught.value.status_code == 401


@pytest.fixture
def served(tmp_path):
    (tmp_path / "index.html").write_text("<html>shell</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc123.js").write_text("x" * 5000)
    (tmp_path / "logo.svg").write_text("<svg/>")
    settings = Settings(env="production", app_database_url=DB, auth_open_access=True,
                        ingest_worker_enabled=False, static_dir=str(tmp_path))
    with TestClient(create_app(settings)) as client:
        yield client


def test_spa_cache_rules_and_client_routes(served):
    asset = served.get("/assets/app-abc123.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert served.get("/logo.svg").headers["cache-control"] == "public, max-age=3600"
    route = served.get("/plant/SAP")
    assert route.text == "<html>shell</html>" and route.headers["cache-control"] == "no-cache"


def test_spa_never_shadows_the_api_or_leaves_its_folder(served):
    assert served.get("/api/v1/no-such-route").status_code == 404
    assert served.post("/api/v1/no-such-route").status_code == 404, "not 405"
    assert served.get("/health/ready").status_code != 405, "real routes still answer"
    assert served.get("/health/live").json()["status"] == "alive"
    assert served.get("/..%2F..%2Fpyproject.toml").text == "<html>shell</html>"


def test_large_responses_are_gzipped(served):
    response = served.get("/assets/app-abc123.js", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("content-encoding") == "gzip"


def test_models_have_their_own_type(served, tmp_path):
    (tmp_path / "car.glb").write_bytes(b"glTF" + bytes(2000))
    response = served.get("/car.glb", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-type"] == "model/gltf-binary"


def test_a_put_from_the_dev_frontend_passes_the_cors_preflight():
    # Save measuring order is a PUT; the preflight used to refuse it.
    settings = Settings(env="development", app_database_url=DB, ingest_worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        answer = client.options("/api/v1/plants/SAP/point-walk/FILMTHICKNESS/J73", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"})
    assert answer.status_code == 200 and "PUT" in answer.headers["access-control-allow-methods"]


def test_landing_status_is_reused_for_thirty_seconds_per_scope(monkeypatch):
    from types import SimpleNamespace
    from app.api.v1 import landing as route

    calls = []
    sample = {name: None for name in route.LandingStatusOut.model_fields}
    monkeypatch.setattr(route.LandingStatusOut, "__init__", lambda self, **kw: None)
    monkeypatch.setattr(route.service, "status", lambda conn, scope, when: calls.append(scope) or sample)
    monkeypatch.setattr(route, "_cache", {})
    clock = [100.0]
    monkeypatch.setattr(route.time, "monotonic", lambda: clock[0])
    everyone, sap = SimpleNamespace(plant_scope=None), SimpleNamespace(plant_scope=["SAP"])

    first = route.landing_status(None, None, everyone)
    assert route.landing_status(None, None, everyone) is first, "reused"
    route.landing_status(None, None, sap)
    assert calls == [None, ["SAP"]], "a plant scope never sees another scope's answer"
    clock[0] += 31
    route.landing_status(None, None, everyone)
    assert calls == [None, ["SAP"], None], "recomputed after 30 s"
