"""Monthly Overview: full-population boxes graded with status_of.

D1 stays open. This service grades one model × colour × orientation mean
for the selected plant month. It does not compute a pass rate or a ribbon.

`domain.grading` is imported here and only here outside grading.py.
DEFAULT_STANDARDS is not a fallback on this read: missing family or missing
plant/seed cf_standard → null status and null lines.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import Connection

from app.domain.boxplot import box_stats, model_sort_key, order_models
from app.domain.grading import EPS, orientation_of, status_of
from app.domain.history import month_date_bounds
from app.domain.wavescan_overview import below_minimum
from app.repositories import overview as repo
from app.repositories.measurements import COUNTED_VIEW
from app.repositories import workbooks as plants_repo


class OverviewError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def resolve_plant(conn: Connection, plant_code: str) -> dict:
    plant = plants_repo.resolve_plant(conn, plant_code)
    if plant is None:
        raise OverviewError(
            404,
            f"No plant {plant_code!r}. Plant codes and their aliases come from "
            f"ref_plant / ref_plant_alias; GET /api/v1/meta lists them.",
        )
    return plant


def _axis(tolerance_group: str | None) -> str | None:
    key = orientation_of(tolerance_group)
    if key == "H":
        return "Horizontal"
    if key == "V":
        return "Vertical"
    return None


def _targets(
    color_name: str,
    family_name: str | None,
    axis: str,
    color_std: dict[tuple[str, str], tuple[Decimal, Decimal]],
    family_std: dict[tuple[str, str], tuple[Decimal, Decimal]],
) -> tuple[Decimal | None, Decimal | None]:
    orient = "H" if axis == "Horizontal" else "V"
    color_row = color_std.get((color_name, orient))
    if color_row is not None:
        return color_row
    if family_name:
        return family_std.get((family_name, orient), (None, None))
    return None, None


def overview(
    conn: Connection,
    plant_code: str,
    *,
    plant_scope: list[str] | None,
    month: str,
    models: list[str] | None,
    colors: list[str] | None,
    view: str = COUNTED_VIEW,
) -> dict:
    """`view`: T114 -- the dashboard counts `COUNTED_VIEW` (the default);
    Comparison's month boxes pass `ACTIVE_VIEW` and keep every reading."""
    try:
        bounds = month_date_bounds(month)
    except ValueError as exc:
        raise OverviewError(422, str(exc)) from exc

    selected_models = [m for m in (models or []) if m]
    selected_colors = [c for c in (colors or []) if c]

    available_months = repo.months(conn, plant_code, plant_scope, view=view)
    model_opts = order_models(
        repo.model_options(conn, plant_code, plant_scope, view=view)
    )
    color_opts = repo.color_options(conn, plant_code)
    rows = repo.readings(
        conn,
        plant_code,
        plant_scope,
        bounds=bounds,
        models=selected_models or None,
        colors=selected_colors or None,
        view=view,
    )

    groups: dict[tuple[str, str, str], dict] = {}
    samples: dict[tuple[str, str, str], list[Decimal]] = defaultdict(list)
    members: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        axis = _axis(row["tolerance_group"])
        if axis is None or row["cf"] is None:
            continue
        key = (row["model"], row["color"], axis)
        groups[key] = {
            "model_code": row["model"],
            "color_name": row["color"],
            "family_code": row["family_code"],
            "family_name": row["family_name"],
            "display_order": row["display_order"],
            "orient": axis,
        }
        samples[key].append(Decimal(row["cf"]))
        # T73 D-73-01: the reading's own id, date and zone, never the month.
        members[key].append(
            {
                "measurement_id": row["measurement_id"],
                "measured_date": row["measured_date"],
                "checkzone": row["checkzone"],
                "cf": row["cf"],
            }
        )

    color_names = sorted({g["color_name"] for g in groups.values()})
    family_names = sorted({g["family_name"] for g in groups.values() if g["family_name"]})
    color_std = {
        (r["color_name"], r["orient"]): (Decimal(r["ford"]), Decimal(r["min"]))
        for r in repo.color_standards(conn, plant_code, color_names)
    }
    family_std = {
        (r["family_name"], r["orient"]): (Decimal(r["ford"]), Decimal(r["min"]))
        for r in repo.family_standards(conn, plant_code, family_names)
    }

    boxes = []
    for key in groups:
        meta = groups[key]
        stats = box_stats(samples[key])
        ford, minimum = _targets(
            meta["color_name"], meta["family_name"], meta["orient"], color_std, family_std
        )
        status = status_of(stats.mean, ford, minimum) if ford is not None else None
        boxes.append(
            {
                "model_code": meta["model_code"],
                "color_name": meta["color_name"],
                "family_code": meta["family_code"],
                "orient": meta["orient"],
                "n": stats.n,
                "box_min": stats.box_min,
                "q1": stats.q1,
                "median": stats.median,
                "q3": stats.q3,
                "box_max": stats.box_max,
                "whisker_lo": stats.whisker_lo,
                "whisker_hi": stats.whisker_hi,
                "outliers": list(stats.outliers),
                "mean": stats.mean,
                "ford": ford,
                "minimum": minimum,
                "status": status,
                # T73 D-73-02: only a box with a standard lists readings.
                "below_minimum": (
                    below_minimum(members[key], minimum, eps=EPS)
                    if ford is not None
                    else []
                ),
                "_order": (
                    model_sort_key(meta["model_code"]),
                    0 if meta["orient"] == "Horizontal" else 1,
                    meta["display_order"] if meta["display_order"] is not None else 99,
                    meta["color_name"],
                ),
            }
        )
    boxes.sort(key=lambda b: b.pop("_order"))
    return {
        "available_months": available_months,
        "model_options": model_opts,
        "color_options": color_opts,
        "models": selected_models,
        "colors": selected_colors,
        "month": month,
        "boxes": boxes,
    }
