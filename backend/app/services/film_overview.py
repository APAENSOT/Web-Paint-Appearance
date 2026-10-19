"""FilmThickness monthly overview (T66, T67): boxes, spec lines, box status.

Mirrors ``services/overview.py`` for Film: every active Film car of the
month (D-66-01), one box per layer x model x colour x H/V (D-66-02), all
four layers in one response (D-66-03), quartiles from ``box_stats``
(D-66-04). Spec lines come from ``film_standards.effective_rule`` over one
``latest()`` read (D-66-05): the latest rule applies to every month.

T67 (supersedes D-66-06 for status):
* ``status`` is ``grading.film_box_status`` on the **box mean** (D-67-01);
  a reading below a line never changes it. NONE -> null.
* ``out_of_spec`` lists the individual readings beyond ``lo`` / ``hi``
  (D-67-04); ``outliers`` is unchanged. Clear has no Maximum, so no HIGH.
* labels per D-67-05; this plant's family (ADR 0010, D-67-08); box order
  layer, model, H<V, family order, colour (D-67-09).

T73 (supersedes D-67-09's family/colour components of the box order):
* one Base-ladder colour sequence per response (D-73-10..12), from the
  same ``latest()`` read and ``effective_rule(layer_code="BASE")``; shared
  by every layer, model and orientation, every plant alike.
* ``color_sequence`` lists it; each box carries ``color_rank``; boxes sort
  layer, model, H<V, ``color_rank``.

Still no pass rate, no count by status, no ribbon; ``grading_available``
is not touched.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import Connection

from app.domain.boxplot import box_stats, model_sort_key, order_models
from app.domain.film_overview import color_sequence, line_labels, out_of_spec
from app.domain.film_standards import LAYERS, effective_rule
from app.domain.grading import EPS, film_box_status
from app.domain.history import month_date_bounds
from app.repositories import film_standards as standards_repo
from app.repositories import filmthickness as repo
from app.services.history import HistoryError, resolve_plant

__all__ = ["HistoryError", "resolve_plant", "overview"]

_ORIENTS = ("H", "V")
#: T73 D-73-11: the ladder is read from the Base layer's rules.
_LADDER_LAYER = "BASE"


def _scope(rule) -> str:
    if rule is None:
        return "NONE"
    return "COLOR" if rule["color_name"] is not None else "PLANT"


def _line(rule, key: str) -> Decimal | None:
    if rule is None or rule[key] is None:
        return None
    return Decimal(rule[key])


def overview(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str | None,
    models: list[str] | None,
    colors: list[str] | None,
) -> dict:
    selected_models = [m for m in (models or []) if m]
    selected_colors = [c for c in (colors or []) if c]
    available_months = repo.film_months(conn, plant_code, plant_scope)
    used = month or (available_months[0] if available_months else None)
    found = {
        "month": used,
        "available_months": available_months,
        "model_options": [],
        "color_options": [],
        "models": selected_models,
        "colors": selected_colors,
        "vehicle_count": 0,
        "color_sequence": [],
        "boxes": [],
    }
    if used is None:
        return found
    try:
        bounds = month_date_bounds(used)
    except ValueError as exc:
        raise HistoryError(422, str(exc)) from exc

    found["model_options"] = order_models(
        repo.film_distinct(conn, "model", plant_code, plant_scope, bounds)
    )
    found["color_options"] = repo.film_color_options(conn, plant_code, plant_scope, bounds)
    rows = repo.film_overview_readings(
        conn,
        plant_code,
        plant_scope,
        bounds=bounds,
        models=selected_models or None,
        colors=selected_colors or None,
    )

    readings: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    family: dict[tuple[str, str, str, str], tuple] = {}
    in_scope: set[str] = set()
    for row in rows:
        if row["thickness"] is None:
            continue
        in_scope.add(row["logical_vehicle_id"])
        if row["orientation"] not in _ORIENTS:
            continue
        key = (row["layer_code"], row["model"], row["color"], row["orientation"])
        readings[key].append(
            {
                "value": Decimal(row["thickness"]),
                "point_code": row["point_code"],
                "logical_vehicle_id": row["logical_vehicle_id"],
                # T68 D-68-01: this fact row's own date, never the month or upload time.
                "measured_date": row["measured_date"],
            }
        )
        family[key] = (row["family_code"], row["family_name"], row["display_order"])

    rules = standards_repo.latest(conn, plant_code)["rules"]

    # T73 D-73-10..12: one colour order for the response, from Base rules.
    colour_meta: dict[str, dict] = {}
    for (_, _, color, _), (family_code, family_name, family_order) in family.items():
        colour_meta.setdefault(
            color,
            {
                "color_name": color,
                "family_code": family_code,
                "family_name": family_name,
                "family_order": family_order,
            },
        )
    sequence = color_sequence(
        [colour_meta[c] for c in sorted(colour_meta)],
        {
            c: {
                o: effective_rule(
                    rules, layer_code=_LADDER_LAYER, color_name=c, orient=o
                )
                for o in _ORIENTS
            }
            for c in colour_meta
        },
    )
    rank = {entry["color_name"]: entry["rank"] for entry in sequence}

    boxes = []
    for key, group in readings.items():
        layer, model, color, orient = key
        stats = box_stats([r["value"] for r in group])
        rule = effective_rule(rules, layer_code=layer, color_name=color, orient=orient)
        lo, hi, target = _line(rule, "lo"), _line(rule, "hi"), _line(rule, "target")
        family_code, family_name, family_order = family[key]
        boxes.append(
            {
                "layer_code": layer,
                "model_code": model,
                "color_name": color,
                "orient": orient,
                "n": stats.n,
                "vehicles": len({r["logical_vehicle_id"] for r in group}),
                "box_min": stats.box_min,
                "q1": stats.q1,
                "median": stats.median,
                "q3": stats.q3,
                "box_max": stats.box_max,
                "whisker_lo": stats.whisker_lo,
                "whisker_hi": stats.whisker_hi,
                "outliers": list(stats.outliers),
                "mean": stats.mean,
                "lo": lo,
                "hi": hi,
                "target": target,
                "standard_scope": _scope(rule),
                "status": film_box_status(layer, stats.mean, lo, hi, target),
                "family_code": family_code,
                "family_name": family_name,
                "family_order": family_order,
                "color_rank": rank[color],
                **line_labels(layer, lo, hi, target),
                # Clear has no Maximum (D-67-07): a stray stored hi lists no HIGH.
                "out_of_spec": out_of_spec(
                    group, lo, None if layer == "CLEAR" else hi, eps=EPS
                ),
                "_order": (
                    LAYERS.index(layer) if layer in LAYERS else len(LAYERS),
                    model_sort_key(model),
                    _ORIENTS.index(orient),
                    rank[color],
                ),
            }
        )
    boxes.sort(key=lambda b: b.pop("_order"))
    found["vehicle_count"] = len(in_scope)
    found["color_sequence"] = sequence
    found["boxes"] = boxes
    return found
