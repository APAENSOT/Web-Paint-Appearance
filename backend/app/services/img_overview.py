"""Authenticated IMG read orchestration; no grades or write connection."""

from __future__ import annotations

from sqlalchemy import Connection

from app.domain.grading import orientation_of
from app.domain.history import month_date_bounds
from app.domain.img_overview import LAYERS, aggregate, number
from app.repositories import img_overview as repo


def months(conn: Connection, scope: list[str] | None) -> list[str]:
    found = set()
    for row in repo.cf_rows(conn, scope):
        if (row["measured_date"] and row.get("counted") is not False
                and orientation_of(row["tolerance_group"]) and number(row["value"]) is not None):
            found.add(row["measured_date"].strftime("%Y-%m"))
    for row in repo.film_rows(conn, scope):
        if (row["measured_date"] and row["counted"] is not False
                and row["orientation"] in ("H", "V")
                and row["layer_code"] in LAYERS and number(row["value"]) is not None):
            found.add(row["measured_date"].strftime("%Y-%m"))
    return sorted(found, reverse=True)


def overview(conn: Connection, scope: list[str] | None, month: str, measure: str) -> list[dict]:
    bounds = month_date_bounds(month)
    rank = {p: i for i, p in enumerate(repo.PLANTS)}
    found = aggregate(repo.cf_rows(conn, scope, bounds), repo.film_rows(conn, scope, bounds),
                      repo.catalogue(conn), measure)
    # Stable sort: FTM/FVL/SAP/AAT, keeping the domain's family/metric/orientation order.
    return sorted(found, key=lambda s: rank[s["plant_code"]])


def colors(conn: Connection, scope: list[str] | None, month: str) -> list[dict]:
    """IMG Color: pooled eligible CF per plant x colour, ranked per orientation."""
    bounds = month_date_bounds(month)
    rank = {p: i for i, p in enumerate(repo.PLANTS)}
    out = []
    for s in aggregate(repo.cf_rows(conn, scope, bounds), [], repo.catalogue(conn),
                       "CALCULATED_TOTAL", group="color"):
        out.append({
            "id": f"{s['plant_code']}|{s['family_key']}|CF|{s['orient']}|-",
            "plant_code": s["plant_code"], "color_name": s["family_key"],
            "orient": s["orient"], "unit": "CF", "mean": s["mean"],
            "included_count": s["included_count"], "count_unit": "CF_READING",
            "availability": s["availability"], "member_models": s["member_models"],
            "models": s["models"], "locations": s["locations"], "exclusions": s["exclusions"],
        })
    out.sort(key=lambda s: (s["orient"], s["mean"] is None, -(s["mean"] or 0),
                            rank[s["plant_code"]], s["color_name"]))
    return out
