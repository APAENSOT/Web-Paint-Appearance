"""T105 pooled means, point identity, exclusions, membership and contract."""

from datetime import date
from decimal import Decimal

from app.domain.img_overview import aggregate, family_of
from app.main import create_app
from app.core.config import Settings
from app.services import img_overview as service


CATALOGUE = {
    "P703 DBL RANGER": dict(model_family="P703", wavescan_ok=True, is_active=True),
    "P703 DBL RAPTOR": dict(model_family="P703", wavescan_ok=True, is_active=True),
    "P703 RAPCAP": dict(model_family="P703", display_name="RAPCAP", wavescan_ok=False, is_active=True),
    "P703 SGL": dict(model_family="P703", display_name="Single CAP", wavescan_ok=False, is_active=True),
    "P703 DBL SUPER DUTY": dict(model_family="P703", wavescan_ok=True, is_active=True),
}


def cf(model, color, value, orient="H", plant="FTM"):
    return dict(plant=plant, model=model, color=color, location="HOOD",
                tolerance_group=orient, value=value, measured_date=date(2026, 9, 1))


def film(vehicle, point, layer, value, *, model="P703 DBL RANGER", color="White",
         orient="H", counted=True, day=date(2026, 9, 1), plant="FTM"):
    return dict(plant=plant, model=model, color=color, location=point,
                logical_vehicle_id=vehicle, layer_code=layer, value=value,
                orientation=orient, counted=counted, measured_date=day)


def bar(series, metric, family, orient="H"):
    return next(s for s in series if s["metric"] == metric and s["family_key"] == family
                and s["orient"] == orient)


def test_pooled_readings_and_catalogue_boundary():
    rows = [cf("P703 DBL RANGER", "Red", "10"),
            cf("P703 DBL RAPTOR", "Blue", "20"),
            cf("P703 DBL RAPTOR", "Blue", "30"),
            cf("P703 PREFIX", "Blue", "99"),
            cf("P703 DBL RANGER", "Red", "0", "V")]
    found = aggregate(rows, [], CATALOGUE, "ECOAT")
    p703 = bar(found, "CF", "P703")
    assert p703["mean"] == Decimal(20)  # model means 10 and 25 would yield 17.5
    assert p703["included_count"] == 3
    assert sum(x["included_count"] for x in p703["models"]) == 3
    assert sum(x["included_count"] for x in p703["colors"]) == 3
    assert sum(x["included_count"] for x in p703["locations"]) == 3
    assert bar(found, "CF", "P703", "V")["mean"] == 0
    # Not in the catalogue: never joins P703 by its name prefix.
    assert bar(found, "CF", "UNMAPPED:P703 PREFIX")["mean"] == 99
    # Owner decision 2026-10-13: every catalogue P703 variant is P703.
    for code in ("P703 RAPCAP", "P703 SGL", "P703 DBL SUPER DUTY"):
        assert family_of(code, CATALOGUE) == ("P703", "P703")
    assert family_of("X1", {"X1": dict(model_family="X", is_active=False)})[0] == "UNMAPPED:X1"


def test_total_complete_points_without_cross_pairing_or_mean_of_means():
    rows = [film("a", "P1", layer, value) for layer, value in zip(
        ("ECOAT", "PRIMER", "BASE", "CLEAR"), ("0", "10", "20", "30"))]
    rows += [film("b", "P2", layer, "10") for layer in ("ECOAT", "PRIMER", "BASE", "CLEAR")]
    rows += [film("c", "P3", "ECOAT", "100")]
    rows += [film("a", "P2", "PRIMER", "999")]
    rows += [film("a", "P1", "BASE", "999", day=date(2026, 9, 2))]
    total = bar(aggregate([], rows, CATALOGUE, "CALCULATED_TOTAL"), "FILM", "P703")
    assert total["mean"] == 50  # (60 + 40) / 2
    assert total["included_count"] == 2
    assert total["exclusions"]["INCOMPLETE_TOTAL"] == 3
    assert sum(x["included_count"] for x in total["locations"]) == 2
    ecoat = bar(aggregate([], rows, CATALOGUE, "ECOAT"), "FILM", "P703")
    assert ecoat["included_count"] == 3


def test_setting_exclusion_unknown_orientation_invalid_and_duplicate_are_distinct():
    rows = [film("excluded", "P1", layer, "1", counted=False)
            for layer in ("ECOAT", "PRIMER", "BASE", "CLEAR")]
    rows += [film("incomplete", "P2", "ECOAT", "1")]
    rows += [film("unknown", "P3", layer, "1", orient=None)
             for layer in ("ECOAT", "PRIMER", "BASE", "CLEAR")]
    rows += [film("duplicate", "P4", layer, "1")
             for layer in ("ECOAT", "PRIMER", "BASE", "CLEAR", "BASE")]
    rows += [film("invalid", "P5", layer, "NaN" if layer == "BASE" else "1")
             for layer in ("ECOAT", "PRIMER", "BASE", "CLEAR")]
    found = bar(aggregate([], rows, CATALOGUE, "CALCULATED_TOTAL"), "FILM", "P703")
    assert found["mean"] is None
    assert found["exclusions"] == dict(SETTING_EXCLUDED=1, INCOMPLETE_TOTAL=1,
                                       UNKNOWN_ORIENTATION=1, INVALID_VALUE=1,
                                       DUPLICATE_LAYER=1)
    assert found["availability"] == "EXCLUDED_OR_INCOMPLETE"


def test_openapi_and_wire_precision():
    app = create_app(Settings(env="development", app_database_url="", auth_dev_bypass=False))
    spec = app.openapi()
    assert "/api/v1/img/overview" in spec["paths"]
    assert "/api/v1/img/overview/months" in spec["paths"]
    from app.schemas.img_overview import ImgSeries
    data = bar(aggregate([cf("P703 DBL RANGER", "Red", "0.100")], [], CATALOGUE,
                         "CALCULATED_TOTAL"), "CF", "P703")
    assert ImgSeries.model_validate(data).model_dump(mode="json")["mean"] == "0.100"


def test_measured_month_union_respects_visibility_and_partial_layers(monkeypatch):
    scopes = []

    def cf_read(conn, scope, bounds=None):
        scopes.append(scope)
        return [cf("P703 DBL RANGER", "White", "4", plant="FVL"),
                cf("P703 DBL RANGER", "White", "4", orient=None)] if scope == ["FVL"] else []

    def film_read(conn, scope, bounds=None):
        scopes.append(scope)
        return [film("a", "P1", "ECOAT", "0", day=date(2026, 10, 2), plant="FVL"),
                film("b", "P1", "ECOAT", "4", counted=False,
                     day=date(2026, 11, 2), plant="FVL")]

    monkeypatch.setattr(service.repo, "cf_rows", cf_read)
    monkeypatch.setattr(service.repo, "film_rows", film_read)
    assert service.months(None, ["FVL"]) == ["2026-10", "2026-09"]
    assert scopes == [["FVL"], ["FVL"]]


def test_empty_and_missing_selected_measure_are_explicit():
    assert aggregate([], [], CATALOGUE, "CALCULATED_TOTAL") == []
    found = bar(aggregate([], [film("a", "P1", "ECOAT", "1")], CATALOGUE,
                          "CLEAR"), "FILM", "P703")
    assert found["mean"] is None
    assert found["included_count"] == 0
    assert found["availability"] == "NO_ELIGIBLE_READINGS"


def test_routes_validate_query_and_forward_scope(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.deps import get_connection, active_measurement_scope
    from app.repositories.measurements import MeasurementFilter

    app = create_app(Settings(env="development", app_database_url="", auth_dev_bypass=True))

    def connection():
        yield object()

    app.dependency_overrides[get_connection] = connection
    app.dependency_overrides[active_measurement_scope] = lambda: MeasurementFilter(plant_scope=["FVL"])
    seen = []
    monkeypatch.setattr(service, "months", lambda conn, scope: seen.append(scope) or ["2026-09"])
    monkeypatch.setattr(service, "overview", lambda conn, scope, month, measure:
                        seen.append((scope, month, measure)) or [])
    monkeypatch.setattr(service, "colors", lambda conn, scope, month:
                        seen.append(("colors", scope, month)) or [])
    with TestClient(app) as client:
        listed = client.get("/api/v1/img/overview/months")
        assert listed.status_code == 200
        assert listed.json()["plants"] == ["FVL"]
        selected = client.get("/api/v1/img/overview?month=2026-09")
        assert selected.status_code == 200
        assert selected.json()["series"] == []
        assert selected.json()["film_measure"] == "CALCULATED_TOTAL"
        assert client.get("/api/v1/img/overview?month=2026-13").status_code == 422
        assert client.get("/api/v1/img/overview?month=2026-09&film_measure=TOTAL").status_code == 422
        assert client.get("/api/v1/img/overview").status_code == 422
        colours = client.get("/api/v1/img/colors?month=2026-09")
        assert colours.status_code == 200
        assert colours.json()["plants"] == ["FVL"] and colours.json()["series"] == []
        assert client.get("/api/v1/img/colors?month=2026-13").status_code == 422
        assert client.get("/api/v1/img/colors").status_code == 422
    assert seen == [["FVL"], (["FVL"], "2026-09", "CALCULATED_TOTAL"), ("colors", ["FVL"], "2026-09")]


def test_uncapped_population_and_valid_outside_any_standard():
    rows = [cf("P703 DBL RANGER", "Red", "20") for _ in range(5001)]
    rows.append(cf("P703 DBL RAPTOR", "Blue", "-100"))
    found = bar(aggregate(rows, [], CATALOGUE, "BASE"), "CF", "P703")
    assert found["included_count"] == 5002
    assert found["mean"] == (Decimal(5001) * 20 - 100) / 5002


def test_img_color_slots_plant_by_colour_pooling_models_and_ranks(monkeypatch):
    rows = [cf("P703 DBL RANGER", "White", "40"),
            cf("P703 DBL RAPTOR", "White", "80"),
            cf("P703 DBL RAPTOR", "White", "90"),
            cf("P703 DBL RANGER", "Black", "100"),
            cf("P703 DBL RANGER", "White", "120", plant="AAT"),
            cf("P703 DBL RANGER", "White", "12.125", orient="V"),
            {**cf("P703 DBL RANGER", "Black", "999"), "counted": False},
            cf("P703 DBL RANGER", "Black", "NaN")]
    seen = []
    def read(conn, scope, bounds):
        seen.append((scope, bounds))
        return rows
    monkeypatch.setattr(service.repo, "cf_rows", read)
    def forbidden_film(*args):
        raise AssertionError("IMG Color must never read film thickness")
    monkeypatch.setattr(service.repo, "film_rows", forbidden_film)
    monkeypatch.setattr(service.repo, "catalogue", lambda conn: CATALOGUE)
    found = [s for s in service.colors(None, None, "2026-09") if s["orient"] == "H"]
    assert [(s["plant_code"], s["color_name"], s["mean"]) for s in found] == [
        ("AAT", "White", Decimal(120)), ("FTM", "Black", Decimal(100)), ("FTM", "White", Decimal(70))]
    white = found[2]
    assert white["included_count"] == 3 and white["count_unit"] == "CF_READING"
    assert white["unit"] == "CF"
    assert {m["model_code"] for m in white["member_models"]} == {"P703 DBL RANGER", "P703 DBL RAPTOR"}
    assert found[1]["exclusions"]["SETTING_EXCLUDED"] == 1
    assert found[1]["exclusions"]["INVALID_VALUE"] == 1
    v = [s for s in service.colors(None, None, "2026-09") if s["orient"] == "V"]
    assert v[0]["mean"] == Decimal("12.125")
    assert all(s["mean"] is None for s in v[1:])
    assert seen == [(None, (date(2026, 9, 1), date(2026, 9, 30)))] * 2
    from app.schemas.img_overview import ImgColorSeries
    assert ImgColorSeries.model_validate(v[0]).model_dump(mode="json")["mean"] == "12.125"


def test_img_reads_orientation_only_never_a_grade():
    """T105 is on the grading-import allowlist for `orientation_of` alone."""
    import re
    from pathlib import Path

    app = Path(__file__).resolve().parents[1] / "app"
    for rel in ("domain/img_overview.py", "services/img_overview.py"):
        code = (app / rel).read_text(encoding="utf-8")
        assert "from app.domain.grading import orientation_of\n" in code, rel
        assert not re.search(r"status_of|film_box_status|grade\(", code), rel
