"""Analysis assistant (AR04): load one plant month, call one pure topic.

Box membership is the overviews' own: the same repository reads and the same
grouping keys. Status and limits are copied from ``services/overview.overview``
and ``services/film_overview.overview`` (D-AR03-2); nothing is graded here.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Connection

from app.domain.assistant.appearance import appearance_profile, cf_drivers, layer_vs_band
from app.domain.assistant.answer import Answer, Box, BandRow, MonthPoint, PointReading, not_enough, severity
from app.domain.assistant.catalog import by_id
from app.domain.assistant.bands import bands
from app.domain.assistant.changes import changes
from app.domain.assistant.colours import colours
from app.domain.assistant.data_checks import data_complete, no_standard, pairing, standard_for
from app.domain.assistant.compare_topics import (
    CARS_NO_FILM, compare_cars, compare_colours, compare_families, compare_models, compare_plants, compare_months, compare_orient, compare_sides)
from app.domain.assistant.points import points
from app.domain.assistant.problem import CARS_RULE, CENTRE_RULE, WHY_RULE, cars_or_process, centre_or_spread, why_failing, worst_cars
from app.domain.assistant.report_grids import colour_report, model_report, recurring, went_well, weekly
from app.domain.assistant.risk import HISTORY_RULE, history, next_month_risk
from app.domain.assistant.readings import WS_METRICS, Reading
from app.domain.assistant.summary import summary
from app.domain.assistant.trend import RULE as TREND_RULE, trend
from app.domain.history import WEEK_BANDS, month_date_bounds
from app.domain.report_summary import month_words
from app.repositories import filmthickness as film_repo
from app.repositories import landing as landing_repo
from app.repositories import overview as ws_repo
from app.repositories import report as repo
from app.repositories.report import BANDS
from app.services import assistant_slots, film_overview, landing, overview, pairing as pairing_service
from app.services.history import HistoryError, resolve_plant
from app.services.report import previous_month

TOPICS = ("summary", "colours", "points", "changes", "trend", "bands")
HISTORY_MONTHS = 6
BAD_TARGET = "target must be domain|layer|model|color|orient"


@dataclass(frozen=True)
class MonthData:
    boxes: list[Box]
    points: list[PointReading]
    bands: list[BandRow]
    skipped_no_limit: int = 0  # readings of boxes with no limit, kept out of points (spec §6)
    readings: list[Reading] = field(default_factory=list)  # AR05: one row per value, tagged by box
    targets: dict[str, float | None] = field(default_factory=dict)  # Film target line per box key


def _f(x) -> float | None:
    return None if x is None else float(x)


def load_month(conn: Connection, plant: str, month: str, *, plant_scope: list[str] | None,
               domain: str, models: list[str], colors: list[str]) -> MonthData:
    bounds = month_date_bounds(month)
    filters = {"plant_scope": plant_scope, "models": models, "colors": colors}
    reads = {"bounds": bounds, "models": models or None, "colors": colors or None}
    boxes: list[Box] = []
    pts: list[PointReading] = []
    band_rows: list[BandRow] = []
    skipped = 0
    recs: list[Reading] = []
    targets: dict[str, float | None] = {}

    if domain in ("wavescan", "both"):
        band_src = repo.band_rows(conn, plant, **filters, bounds=bounds)
        by_id = {b["measurement_id"]: b for b in band_src}
        ov = {(b["model_code"], b["color_name"], b["orient"]): b
              for b in overview.overview(conn, plant, month=month, **filters)["boxes"]}
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in ws_repo.readings(conn, plant, plant_scope, **reads):
            if r["cf"] is not None:
                groups[(r["model"], r["color"], overview._axis(r["tolerance_group"]))].append(r)
        for key, rows in groups.items():
            if (ref := ov.get(key)) is None:
                continue
            lsl = _f(ref["minimum"])
            box = Box("wavescan", None, *key, ref["status"], None, lsl, None, "",
                      tuple(float(r["cf"]) for r in rows), tuple(r["measured_date"] for r in rows))
            boxes.append(box)
            for r in rows:
                src = by_id.get(r["measurement_id"], {}) | {"cf": r["cf"]}
                recs += [Reading("wavescan", None, key[0], key[1], r["family_name"], key[2], r["checkzone"],
                                 None, r["measured_date"], m, float(src[m]),
                                 (lsl is not None and float(src[m]) < lsl) if m == "cf" else None, box.key, None,
                                 str(r["measurement_id"]))
                         for m in WS_METRICS if src.get(m) is not None]
            if lsl is None:
                skipped += len(rows)
                continue
            pts += [PointReading("wavescan", r["checkzone"], None, lsl is not None and v < lsl)
                    for r, v in zip(rows, box.values)]
        band_rows = [BandRow(r["model"], r["color"], {b: _f(r[b]) for b in BANDS})
                     for r in band_src]

    if domain in ("film", "both"):
        ov = {(b["layer_code"], b["model_code"], b["color_name"], b["orient"]): b
              for b in film_overview.overview(conn, plant, month=month, **filters)["boxes"]}
        groups = defaultdict(list)
        for r in film_repo.film_overview_readings(conn, plant, plant_scope, **reads):
            if r["thickness"] is not None and r["orientation"] in film_overview._ORIENTS:
                groups[(r["layer_code"], r["model"], r["color"], r["orientation"])].append(r)
        for key, rows in groups.items():
            if (ref := ov.get(key)) is None:
                continue
            # Clear has no Maximum (D-67-07): the overview's out_of_spec ignores a stray hi too.
            lsl, usl = _f(ref["lo"]), None if key[0] == "CLEAR" else _f(ref["hi"])
            box = Box("film", *key, ref["status"], ref["standard_scope"], lsl, usl, "µm",
                      tuple(float(r["thickness"]) for r in rows), tuple(r["measured_date"] for r in rows))
            boxes.append(box)
            targets[box.key] = _f(ref.get("target"))
            recs += [Reading("film", key[0], key[1], key[2], r["family_name"], key[3], r["point_code"],
                             None if r["logical_vehicle_id"] is None else str(r["logical_vehicle_id"]),
                             r["measured_date"], key[0], v,
                             (lsl is not None and v < lsl) or (usl is not None and v > usl), box.key, r["job_no"])
                     for r, v in zip(rows, box.values)]
            if lsl is None and usl is None:
                skipped += len(rows)
                continue
            pts += [PointReading("film", r["point_code"], r["logical_vehicle_id"],
                                 (lsl is not None and v < lsl) or (usl is not None and v > usl))
                    for r, v in zip(rows, box.values)]

    return MonthData(boxes, pts, band_rows, skipped, recs, targets)


def _trend(target: str | None, used: str, now: MonthData, before: MonthData, months: list[str], load):
    if target is not None:
        box = next((b for b in now.boxes if b.key == target), None)
        if box is None:
            return not_enough(f"That box has no readings for {month_words(used)} with these filters.",
                              0, TREND_RULE)
    else:
        bad = sorted((b for b in now.boxes if b.status not in ("PASS", None)), key=lambda b: -severity(b))
        box = bad[0] if bad else max(now.boxes, key=lambda b: len(b.values), default=None)
        if box is None:
            return not_enough("No boxes for this month and filter.", 0, TREND_RULE)
    history = []
    for m in [m for m in months if m <= used][:HISTORY_MONTHS]:
        same = next((b for b in load(m).boxes if b.key == box.key), None)
        history.append(MonthPoint(m, same and same.mean, same and same.status))
    prev = next((b for b in before.boxes if b.key == box.key), None)
    return trend(box, prev, history)


def _history(c, s) -> Answer:
    box = _problem_box(c, s["target"])
    if box is None:
        return not_enough(f"That box has no readings for {month_words(c.used)} with these filters.", 0, HISTORY_RULE)
    points = []
    for m in [m for m in c.months if m <= c.used][:HISTORY_MONTHS]:
        same = next((b for b in c.load(m).boxes if b.key == box.key), None)
        points.append(MonthPoint(m, same.mean if same else None, same.status if same else None))
    return history(box, points)


def _recurring(c, _s) -> Answer:
    by_month = {}
    for m in [m for m in c.months if m <= c.used]:
        if boxes := [b for b in c.load(m).boxes if b.values]:
            by_month[m] = boxes
        if len(by_month) == 4:
            break
    return recurring(by_month, c.used)


def _problem_box(c, target: str | None, cars: bool = False):
    """The named box, or (no target) the summary's top non-Pass box; Film only for the car questions."""
    boxes = [b for b in c.load(c.used).boxes if not cars or b.domain == "film"]
    if target is not None:
        return next((b for b in boxes if b.key == target), None)
    bad = sorted((b for b in boxes if b.status not in ("PASS", None)), key=lambda b: -severity(b))
    return bad[0] if bad else max(boxes, key=lambda b: len(b.values), default=None)


def _why(c, s) -> Answer:
    box = _problem_box(c, s["target"])
    if box is None:
        return not_enough(f"That box has no readings for {month_words(c.used)} with these filters.", 0, WHY_RULE)
    return why_failing(box, c.load(c.used).readings, assistant_slots.car_labels(c))


def _cars(c, s) -> Answer:
    box = _problem_box(c, s.get("target"), cars=s.get("target") is None)
    if box is None and s.get("target") is None:
        return not_enough(CARS_NO_FILM if c.domain == "wavescan" else "No Film boxes for this month and filter.",
                          0, CARS_RULE)
    if box is None:
        return not_enough(f"That box has no readings for {month_words(c.used)} with these filters.", 0, CARS_RULE)
    return cars_or_process(box, c.load(c.used).readings, assistant_slots.car_labels(c))


def _centre(c, s) -> Answer:
    box = _problem_box(c, s["target"])
    if box is None:
        return not_enough(f"That box has no readings for {month_words(c.used)} with these filters.", 0, CENTRE_RULE)
    before = next((b for b in c.load(c.before_month).boxes if b.key == box.key), None)
    return centre_or_spread(box, before, c.load(c.used).targets.get(box.key), c.before_month)


@dataclass(frozen=True)
class AskContext:
    conn: Connection
    plant: str
    plant_scope: list[str] | None
    used: str
    before_month: str
    months: list[str]
    domain: str
    models: list[str]
    colors: list[str]
    load: Callable[[str], MonthData]
    load_other: Callable[[str, str], MonthData] | None = None  # (plant, month): another plant, same filters but colours
    _wide: dict[str, MonthData] = field(default_factory=dict, repr=False, compare=False)

    def load_ignoring(self, dim: str) -> MonthData:
        """The month used without the models or colors filter: a compare's own dimension (ruling R1)."""
        if not getattr(self, dim):
            return self.load(self.used)
        if dim not in self._wide:
            self._wide[dim] = load_month(self.conn, self.plant, self.used, plant_scope=self.plant_scope,
                                         domain=self.domain, models=[] if dim == "models" else self.models,
                                         colors=[] if dim == "colors" else self.colors)
        return self._wide[dim]


def _bands(c: AskContext, _s: dict[str, str]) -> Answer:
    if c.domain == "film":
        return bands([], [], None)
    paired = (repo.paired_rows(c.conn, c.plant, models=c.models, colors=c.colors)
              if c.domain == "both" and (c.plant_scope is None or c.plant in c.plant_scope) else None)
    return bands(c.load(c.used).bands, c.load(c.before_month).bands, paired,
                 film_filtered=c.domain == "wavescan")


def _drivers(c: AskContext, s: dict[str, str]) -> Answer:
    data = c.load(c.used)
    box = next((b for b in data.boxes if b.key == s["target"]), None)
    if box is None:
        return not_enough(f"That box has no readings for {month_words(c.used)} with these filters.", 0,
                          "CF drivers read the chosen Wave Scan box in the month used")
    return cf_drivers(box, data.readings)


def _layer_band(c: AskContext, s: dict[str, str]) -> Answer:
    paired = (repo.paired_rows(c.conn, c.plant, models=c.models, colors=c.colors)
              if c.plant_scope is None or c.plant in c.plant_scope else None)
    return layer_vs_band(s["layer"], s["metric"], paired)


def _wide_compare(c: AskContext, dim: str, run, a: str, b: str, metric: str) -> Answer:
    data = c.load_ignoring(dim)  # the compared dimension ignores the filter bar (ruling R1)
    return run(a, b, metric, data.readings, data.boxes)


def _weeks_in_month(month: str, today: date) -> list[int]:
    """Week bands with a day in the month; for the current month, only those that have begun."""
    year, number = map(int, month.split("-"))
    last = calendar.monthrange(year, number)[1]
    if (year, number) == (today.year, today.month):
        last = min(last, today.day)
    return [w for w, (first, _end) in enumerate(WEEK_BANDS, start=1) if first <= last]


def _data_complete(c: AskContext, _s: dict[str, str]) -> Answer:
    data = c.load(c.used)
    # The feed carries counts only; the newest upload's start time is the same landing source.
    seen = c.plant_scope is None or c.plant in c.plant_scope
    files = landing_repo.latest_files(c.conn, c.plant, 1) if seen else []
    started = files[0]["started_at"] if files else None
    last = started.astimezone().date() if started else None  # local date, as landing.today() is local
    return data_complete(data.readings, data.boxes, last, _weeks_in_month(c.used, landing.today().date()))


def _pairing(c: AskContext, _s: dict[str, str]) -> Answer:
    if c.plant_scope is not None and c.plant not in c.plant_scope:
        return not_enough(f"You can't see {c.plant}.", 0, "Pairing is shown only for plants you can see")
    return pairing(pairing_service.read(c.conn, c.plant))


RUNNERS: dict[str, Callable[[AskContext, dict[str, str]], Answer]] = {
    "summary": lambda c, s: summary(c.load(c.used).boxes, c.load(c.before_month).boxes, c.before_month),
    "colours": lambda c, s: colours(c.load(c.used).boxes),
    "points": lambda c, s: points(c.load(c.used).points, skipped_no_limit=c.load(c.used).skipped_no_limit),
    "changes": lambda c, s: changes(c.load(c.used).boxes, c.load(c.before_month).boxes, c.before_month),
    "trend": lambda c, s: _trend(s.get("target"), c.used, c.load(c.used), c.load(c.before_month),
                                 c.months, c.load),
    "bands": _bands,
    "appearance_profile": lambda c, s: appearance_profile(s["colour"], c.load(c.used).readings),
    "cf_drivers": _drivers,
    "layer_vs_band": _layer_band,
    "why_failing": _why,
    "cars_or_process": _cars,
    "centre_or_spread": _centre,
    "worst_cars": lambda c, s: worst_cars(c.load(c.used).readings, assistant_slots.car_labels(c)),
    "compare_models": lambda c, s: _wide_compare(c, "models", compare_models, s["a"], s["b"], s["metric"]),
    "compare_colours": lambda c, s: _wide_compare(c, "colors", compare_colours, s["a"], s["b"], s["metric"]),
    "compare_orient": lambda c, s: compare_orient(s["colour"], s["metric"], c.load(c.used).readings,
                                                  c.load(c.used).boxes),
    "compare_months": lambda c, s: compare_months(c.load(s.get("month", c.used)).boxes, c.load(s["month2"]).boxes,
                                                  s.get("month", c.used), s["month2"]),
    "compare_sides": lambda c, s: compare_sides(s["metric"], c.load(c.used).readings, c.load(c.used).boxes),
    "compare_families": lambda c, s: compare_families(s["metric"], c.load(c.used).readings, c.load(c.used).boxes),
    "compare_cars": lambda c, s: compare_cars(s["a"], s["b"], c.load(c.used).readings, assistant_slots.car_labels(c)),
    "compare_plants": lambda c, s: compare_plants(c.plant, s["plant2"], s["metric"], c.load(c.used).readings,
                                                  c.load_other(s["plant2"], c.used).readings, c.models, c.used),
    "colour_report": lambda c, s: colour_report(c.load(c.used).boxes, c.load(c.before_month).boxes,
                                                c.used, c.before_month),
    "went_well": lambda c, s: went_well(c.load(c.used).boxes, c.load(c.before_month).boxes, c.before_month),
    "weekly": lambda c, s: weekly(c.load(c.used).readings),
    "model_report": lambda c, s: model_report(s["model"], c.load(c.used).boxes, c.load(c.before_month).boxes),
    "next_month_risk": lambda c, s: next_month_risk(c.load(c.used).boxes),
    "history": _history,
    "recurring": _recurring,
    "data_complete": _data_complete,
    "standard_for": lambda c, s: standard_for(s["colour"], c.load(c.used).boxes, c.load(c.used).targets, c.used),
    "no_standard": lambda c, s: no_standard(c.load(c.used).boxes),
    "pairing": _pairing,
}


def answer(conn: Connection, plant_code: str, *, plant_scope: list[str] | None, month: str | None,
           domain: str, models: list[str] | None, colors: list[str] | None, topic: str,
           target: str | None, slots: dict[str, str | None] | None = None) -> dict:
    plant = resolve_plant(conn, plant_code)["plant_code"]
    try:
        question = by_id(topic)
    except KeyError as exc:
        raise HistoryError(422, f"unknown topic {topic}") from exc
    models = [m for m in (models or []) if m]
    colors = [c for c in (colors or []) if c]
    params = {k: v for k, v in ((slots or {}) | {"target": target}).items() if v}
    for m in (month, params.get("month2")):
        if m is not None:
            try:
                month_date_bounds(m)
            except ValueError as exc:
                raise HistoryError(422, str(exc)) from exc
    if "model" in {slot.name for slot in question.slots} and "model" not in params and "target" in params:
        params["model"] = params["target"]  # a follow-up names the model as its target
    # points accepts and ignores target (AR04); only a box slot validates it.
    has_target = any(slot.name == "target" for slot in question.slots)
    if has_target and "target" in params and len(params["target"].split("|")) != 5:
        raise HistoryError(422, BAD_TARGET)
    for slot in question.slots:
        allowed = assistant_slots.VOCAB.get(slot.kind)
        if allowed and slot.name in params and params[slot.name] not in allowed:
            raise HistoryError(422, f"{slot.name} must be one of {', '.join(allowed)}")
    months = sorted(set(ws_repo.months(conn, plant, plant_scope))
                    | set(film_repo.film_months(conn, plant, plant_scope)), reverse=True)
    used = month or (months[0] if months else None)
    before_month = previous_month(used) if used else None
    echo = {"topic": topic, "month": used, "previous_month": before_month, "domain": domain,
            "models": models, "colors": colors}

    cache: dict[str, MonthData] = {}

    def load(m: str) -> MonthData:
        if m not in cache:
            cache[m] = load_month(conn, plant, m, plant_scope=plant_scope, domain=domain,
                                  models=models, colors=colors)
        return cache[m]

    other_cache: dict[tuple[str, str], MonthData] = {}

    def load_other(p: str, m: str) -> MonthData:
        if (p, m) not in other_cache:
            # Colour names differ per plant; compare_plants matches by colour family instead.
            other_cache[p, m] = load_month(conn, p, m, plant_scope=plant_scope, domain=domain,
                                           models=models, colors=[])
        return other_cache[p, m]

    if used is None:
        result = not_enough("No readings for this plant yet.", 0, "Needs at least one month of readings")
    else:
        ctx = AskContext(conn, plant, plant_scope, used, before_month, months, domain, models, colors, load,
                         load_other)
        filled = assistant_slots.resolve(question, params | {"month": used}, ctx)
        result = filled if isinstance(filled, Answer) else RUNNERS[topic](ctx, filled)

    body = result.to_dict()
    if body["status"] == "not_enough":
        body["status"] = "not_enough_data"
    return echo | body
