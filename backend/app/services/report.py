"""Analysis & Report, first version (AR03): every section in one read.

Box statuses are the dashboard's: this service calls the Wave Scan and Film
overview services for the month and the month before, and copies their
``status`` unchanged (D-AR03-2). It has no threshold, no status rule and no
grading call of its own. Band boxes use ``box_stats`` (band design D-AR03-3);
relationships are Spearman with n, plus an OLS slope for the strongest
(D-AR03-3). Counts only, never a share (D-AR03-10).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal

from sqlalchemy import Connection

from app.domain.boxplot import box_stats, model_sort_key, order_models, percentile_linear
from app.domain.film_standards import LAYERS
from app.domain.history import month_date_bounds
from app.domain.report_stats import ols_slope, spearman
from app.domain.report_summary import BAND_WORD, LAYER_WORD, sentences
from app.repositories import filmthickness as film_repo
from app.repositories import overview as ws_repo
from app.repositories import report as repo
from app.repositories.report import BANDS
from app.services import film_overview, overview
from app.services.history import HistoryError, resolve_plant

DOMAINS = ("wavescan", "film")
STATUS_ORDER = {"FAIL": 0, "OVER": 1, "WARNING": 2, None: 3}
PANEL_ORDER = ("HOOD", "ROOF", "FENDER", "DOOR", "PILLAR", "BOX", "TAILGATE", "LIFTGATE")
DOTS_BELOW = 5
STRONGEST = 5
STRONGEST_MIN_N = 10


def previous_month(month: str) -> str:
    year, number = (int(x) for x in month.split("-"))
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


def _dec(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(str(round(x, 3)))


# ------------------------------------------------------------------ boxes
def _boxes(ws: dict | None, film: dict | None) -> list[dict]:
    """The overview boxes, one shape for both domains; status copied as is."""
    out = []
    for b in (ws or {}).get("boxes", []):
        out.append({
            "domain": "wavescan", "layer": None, "model": b["model_code"], "color": b["color_name"],
            "orient": b["orient"][0], "status": b["status"], "scope": None,
            "n": b["n"], "mean": b["mean"], "median": b["median"],
            "limits": {k: v for k, v in (("Standard", b["ford"]), ("Minimum", b["minimum"]))
                       if v is not None},
            "raw_points": b["below_minimum"],
        })
    for b in (film or {}).get("boxes", []):
        out.append({
            "domain": "film", "layer": b["layer_code"], "model": b["model_code"],
            "color": b["color_name"], "orient": b["orient"], "status": b["status"],
            "scope": b["standard_scope"], "n": b["n"], "mean": b["mean"], "median": b["median"],
            "limits": {b[f"{k}_label"]: b[k] for k in ("lo", "hi", "target") if b[k] is not None},
            "raw_points": b["out_of_spec"],
        })
    return out


def _key(b: dict) -> tuple:
    return (b["domain"], b["layer"], b["model"], b["color"], b["orient"])


def _sort_key(b: dict) -> tuple:
    return (
        DOMAINS.index(b["domain"]),
        model_sort_key(b["model"]),
        LAYERS.index(b["layer"]) if b["layer"] in LAYERS else -1,
        b["color"],
        b["orient"],
    )


def _ws_glance(found: dict, rows: list[dict]) -> dict | None:
    if not rows and not found["boxes"]:
        return None
    counts = dict.fromkeys(("PASS", "WARNING", "FAIL", "NONE"), 0)
    for b in found["boxes"]:
        counts[b["status"] or "NONE"] += 1
    return {
        "readings": len(rows),
        "cars": len({r["serial_no"] for r in rows if r["serial_no"]}),
        "boxes": counts,
        "below_minimum": sum(len(b["below_minimum"]) for b in found["boxes"]),
    }


def _film_glance(found: dict) -> dict | None:
    if not found["boxes"]:
        return None
    layers: dict[str, dict] = {}
    for b in found["boxes"]:
        row = layers.setdefault(b["layer_code"], dict.fromkeys(("PASS", "WARNING", "FAIL", "OVER", "NONE"), 0))
        row[b["status"] or "NONE"] += 1
    return {
        "readings": sum(b["n"] for b in found["boxes"]),
        "cars": found["vehicle_count"],
        "boxes_by_layer": [{"layer": layer, **layers[layer]} for layer in LAYERS if layer in layers],
        "out_of_spec": sum(len(b["out_of_spec"]) for b in found["boxes"]),
    }


def _issues(boxes: list[dict], cars: dict[int, tuple]) -> list[dict]:
    out = []
    for b in boxes:
        if b["status"] == "PASS":
            continue
        if b["domain"] == "wavescan":
            points = [{"value": p["cf"], "side": None,
                       "panel": cars.get(p["measurement_id"], (None, None))[1],
                       "point_code": p["checkzone"],
                       "car": cars.get(p["measurement_id"], (None, None))[0],
                       "date": p["measured_date"]} for p in b["raw_points"]]
        else:
            points = [{"value": p["value"], "side": p["side"], "panel": None,
                       "point_code": p["point_code"], "car": p["logical_vehicle_id"],
                       "date": p["measured_date"]} for p in b["raw_points"]]
        out.append({k: b[k] for k in ("domain", "layer", "model", "color", "orient", "status",
                                      "n", "mean", "median", "limits")} | {"points": points})
    out.sort(key=lambda i: (STATUS_ORDER[i["status"]], *_sort_key(i)))
    return out


def _comparison(now: list[dict], before: list[dict]) -> list[dict]:
    before_by = {_key(b): b for b in before}
    now_keys = {_key(b) for b in now}
    rows = []
    for b in sorted(now + [b for b in before if _key(b) not in now_keys], key=_sort_key):
        n, p = (b, before_by.get(_key(b))) if _key(b) in now_keys else (None, b)
        rows.append({
            "domain": b["domain"], "layer": b["layer"], "model": b["model"], "color": b["color"],
            "orient": b["orient"],
            "mean_now": n and n["mean"], "mean_before": p and p["mean"],
            "mean_change": n["mean"] - p["mean"] if n and p else None,
            "status_now": n and n["status"], "status_before": p and p["status"],
            # private: the summary's null word needs the Film rule scope; dropped before output.
            "_scope_now": n and n["scope"], "_scope_before": p and p["scope"],
        })
    return rows


# ------------------------------------------------------------------ bands
def _band_box(values: list[Decimal]) -> dict | None:
    if not values:
        return None
    stats = asdict(box_stats(values))
    stats["outliers"] = list(stats["outliers"])
    stats["values"] = sorted(values) if stats["n"] < DOTS_BELOW else None
    return stats


def _median(values: list[Decimal]) -> Decimal | None:
    return percentile_linear(sorted(values), Decimal("0.5")) if values else None


def _bands(rows: list[dict], previous: list[dict]) -> dict:
    def vals(band: str, source: list[dict], orient: str | None = None) -> list[Decimal]:
        return [Decimal(r[band]) for r in source
                if r[band] is not None and (orient is None or r["tolerance_group"] == orient)]

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["panel_group"]:
            groups[r["panel_group"]].append(r)
    order = sorted(groups, key=lambda g: (PANEL_ORDER.index(g) if g in PANEL_ORDER else len(PANEL_ORDER), g))
    return {
        "n_readings": len(rows),
        "n_cars": len({r["serial_no"] for r in rows if r["serial_no"]}),
        "bands": [{
            "band": band,
            "all": _band_box(vals(band, rows)),
            "horizontal": _band_box(vals(band, rows, "Horizontal")),
            "vertical": _band_box(vals(band, rows, "Vertical")),
            "previous_month_median": _median(vals(band, previous)),
        } for band in BANDS],
        "panel_groups": [{
            "panel_group": g,
            "n_readings": len(groups[g]),
            "median": {band: _median(vals(band, groups[g])) for band in BANDS},
        } for g in order],
    }


# ------------------------------------------------------------------ relationships
def _matrix(cols: dict[str, list]) -> dict:
    names = list(cols)
    cells = [[spearman(cols[a], cols[b]) for b in names] for a in names]
    return {"params": names, "rho": [[_dec(r) for r, _ in row] for row in cells],
            "n": [[n for _, n in row] for row in cells]}


def _film_columns(rows: list[dict]) -> dict[str, list]:
    """Unit = car x point: the mean thickness of each layer there."""
    units: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["thickness"] is not None:
            units[(r["logical_vehicle_id"], r["point_code"])][r["layer_code"]].append(Decimal(r["thickness"]))
    return {layer: [sum(u[layer]) / len(u[layer]) if u.get(layer) else None for u in units.values()]
            for layer in LAYERS}


def _relationships(ws_rows: list[dict] | None, film_rows: list[dict] | None,
                   paired: list[dict] | None) -> dict:
    candidates = []  # (a word, b word, scope, rho, n, xs, ys, paired row | None)
    ws = film = paired_out = None
    if ws_rows is not None:
        cols = {b: [r[b] for r in ws_rows] for b in BANDS}
        ws = _matrix(cols)
        for i, a in enumerate(BANDS):
            for b in BANDS[i + 1:]:
                rho, n = spearman(cols[a], cols[b])
                candidates.append((BAND_WORD[a], BAND_WORD[b], "wavescan", rho, n, cols[a], cols[b], None))
    if film_rows is not None:
        cols = _film_columns(film_rows)
        film = _matrix(cols)
        for i, a in enumerate(LAYERS):
            for b in LAYERS[i + 1:]:
                rho, n = spearman(cols[a], cols[b])
                candidates.append((LAYER_WORD[a], LAYER_WORD[b], "film", rho, n, cols[a], cols[b], None))
    if paired is not None:
        out_rows = []
        for layer in LAYERS:
            mine = [r for r in paired if r["layer_code"] == layer]
            xs = [r["thickness"] for r in mine]
            for band in BANDS:
                ys = [r[band] for r in mine]
                rho, n = spearman(xs, ys)
                row = {"film_layer": layer, "ws_param": band, "rho": _dec(rho), "n": n, "slope": None}
                out_rows.append(row)
                candidates.append((LAYER_WORD[layer], BAND_WORD[band], "paired", rho, n, xs, ys, row))
        paired_out = {"cars": len({r["car_no"] for r in paired}), "rows": out_rows}

    ranked = sorted((c for c in candidates if c[3] is not None and c[4] >= STRONGEST_MIN_N),
                    key=lambda c: -abs(c[3]))[:STRONGEST]
    strongest = []
    for a, b, scope, rho, n, xs, ys, row in ranked:
        slope = _dec(ols_slope(xs, ys))
        if row is not None:
            row["slope"] = slope
        strongest.append({"a": a, "b": b, "scope": scope, "rho": _dec(rho), "n": n, "slope": slope})
    return {"wavescan": ws, "film": film, "paired": paired_out, "strongest": strongest}


# ------------------------------------------------------------------ read
def read(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str | None,
    domain: str,
    models: list[str] | None,
    colors: list[str] | None,
) -> dict:
    plant = resolve_plant(conn, plant_code)["plant_code"]
    models = [m for m in (models or []) if m]
    colors = [c for c in (colors or []) if c]
    if month is not None:
        try:
            month_date_bounds(month)
        except ValueError as exc:
            raise HistoryError(422, str(exc)) from exc
    months = sorted(set(ws_repo.months(conn, plant, plant_scope))
                    | set(film_repo.film_months(conn, plant, plant_scope)), reverse=True)
    used = month or (months[0] if months else None)
    before = previous_month(used) if used else None
    want_ws = used is not None and domain in ("wavescan", "both")
    want_film = used is not None and domain in ("film", "both")
    filters = {"plant_scope": plant_scope, "models": models, "colors": colors}

    ws_now = ws_before = film_now = film_before = None
    rows_now = rows_before = film_rows = None
    if want_ws:
        ws_now = overview.overview(conn, plant, month=used, **filters)
        ws_before = overview.overview(conn, plant, month=before, **filters)
        rows_now = repo.band_rows(conn, plant, bounds=month_date_bounds(used), **filters)
        rows_before = repo.band_rows(conn, plant, bounds=month_date_bounds(before), **filters)
    if want_film:
        film_now = film_overview.overview(conn, plant, month=used, **filters)
        film_before = film_overview.overview(conn, plant, month=before, **filters)
        film_rows = film_repo.film_overview_readings(conn, plant, bounds=month_date_bounds(used), **filters)
    paired = (repo.paired_rows(conn, plant, models=models, colors=colors)
              if want_ws and want_film and (plant_scope is None or plant in plant_scope) else None)

    glance = {"wavescan": None, "film": None}
    if ws_now is not None:
        glance["wavescan"] = _ws_glance(ws_now, rows_now)
        if glance["wavescan"] is not None:
            glance["wavescan"]["previous"] = _ws_glance(ws_before, rows_before)
    if film_now is not None:
        glance["film"] = _film_glance(film_now)
        if glance["film"] is not None:
            glance["film"]["previous"] = _film_glance(film_before)

    now, earlier = _boxes(ws_now, film_now), _boxes(ws_before, film_before)
    cars = {r["measurement_id"]: (r["serial_no"], r["panel_group"]) for r in rows_now or []}
    option_models = (ws_now or {}).get("model_options", []) + (film_now or {}).get("model_options", [])
    option_colors = (ws_now or {}).get("color_options", []) + (film_now or {}).get("color_options", [])

    report = {
        "plant_code": plant,
        "month": used,
        "previous_month": before,
        "domain": domain,
        "models": models,
        "colors": colors,
        "options": {
            "months": months,
            "models": order_models(option_models),
            "colors": sorted({c["color_name"] for c in option_colors}),
        },
        "glance": glance,
        "issues": _issues(now, cars),
        "comparison": _comparison(now, earlier),
        "bands": _bands(rows_now, rows_before) if rows_now is not None else None,
        "relationships": _relationships(rows_now, film_rows, paired),
    }
    report["summary"] = sentences(report)
    report["comparison"] = [{k: v for k, v in r.items() if not k.startswith("_")}
                            for r in report["comparison"]]
    return report
