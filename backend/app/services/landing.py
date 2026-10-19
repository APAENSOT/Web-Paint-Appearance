"""Landing status: the four plant cards, the feed sidebar and the plant preview.

Each card's facts come from the same services the plant dashboards use, so the
landing page can never disagree with the dashboard it links to.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import Connection

from app.domain.history import month_date_bounds
from app.domain.landing import WeekUpload, box_share, feed_status
from app.repositories import landing as repo
from app.services import film_overview, overview, pairing

PLANTS = ("FTM", "FVL", "SAP", "AAT")


def _status(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


def quality(conn: Connection, plant: str, scope: list[str] | None, month: str) -> dict:
    ws = overview.overview(conn, plant, plant_scope=scope, month=month, models=None, colors=None)
    film = film_overview.overview(conn, plant, plant_scope=scope, month=month,
                                  models=None, colors=None)
    groups: dict[str, list[str | None]] = {
        "WAVESCAN_H": [], "WAVESCAN_V": [], "FILM_H": [], "FILM_V": []}
    for box in ws["boxes"]:
        groups["WAVESCAN_H" if box["orient"] == "Horizontal" else "WAVESCAN_V"].append(
            _status(box.get("status")))
    for box in film["boxes"] if film["month"] == month else []:
        groups[f"FILM_{box['orient']}"].append(_status(box.get("status")))
    return box_share(groups)


def feed(conn: Connection, plant: str, as_of: datetime) -> dict | None:
    month_start = as_of.date().replace(day=1)
    rows = repo.week_uploads(conn, plant, month_date_bounds(month_start.strftime("%Y-%m")))
    combos: dict[int, set] = defaultdict(set)
    first: dict[int, datetime] = {}
    for r in rows:
        combos[r["week"]].add((r["model"], r["color"]))
        t = r["first_loaded_at"]
        if t is not None and (r["week"] not in first or t < first[r["week"]]):
            first[r["week"]] = t
    models, colors = repo.offered(conn, plant)
    return feed_status(
        as_of, [WeekUpload(w, frozenset(c), first.get(w)) for w, c in combos.items()],
        models, colors)


def status(conn: Connection, scope: list[str] | None, as_of: datetime) -> dict:
    month = as_of.strftime("%Y-%m")
    plants = []
    for plant in PLANTS:
        if scope is not None and plant not in scope:
            continue
        cars = pairing.read(conn, plant)
        plants.append({
            "plant_code": plant,
            "quality": quality(conn, plant, scope, month),
            "feed": feed(conn, plant, as_of),
            "wavescan_cars": cars["wavescan_cars"],
            "film_cars": cars["film_cars"],
            "latest_files": repo.latest_files(conn, plant),
        })
    return {"as_of": as_of, "month": month, "plants": plants}


def today() -> datetime:
    return datetime.now().astimezone()

