"""AR05 slots: fill a question's details or ask for the first missing one, with
choices taken from the month's live data (spec §3). Read only.
"""

from __future__ import annotations

import re

from app.domain.assistant.answer import Answer, not_enough
from app.domain.assistant.appearance import domain_gate
from app.domain.assistant.compare_topics import CARS_NO_FILM
from app.domain.assistant.catalog import Question, SlotSpec
from app.domain.assistant.readings import WS_METRICS
from app.domain.report_summary import BAND_LAYERS, BAND_WORD, LAYER_WORD, month_words
from app.repositories import filmthickness as film_repo
from app.repositories import meta as meta_repo
from app.repositories import overview as ws_repo
from app.repositories import pairing as pairing_repo

LAYERS = tuple(LAYER_WORD)
BANDS = (*BAND_LAYERS, "cf")  # du..we and CF: the bands a layer can be linked to
VOCAB = {"layer": LAYERS, "metric": LAYERS + WS_METRICS, "band": BANDS}  # by slot kind: anything else is a 422
# Pair slots ignore the filter on their own dimension (ruling R1): (filter, word in the empty answer).
PAIR_WIDE = {"model": ("models", "model"), "colour": ("colors", "colour")}
STATIC = {
    "side": [("L", "Left"), ("R", "Right")],
    "orient": [("Horizontal", "Horizontal"), ("Vertical", "Vertical")],
}


def _plants(ctx) -> list[tuple[str, str]]:
    # shortcut: two month queries per plant; fine for a handful of plants, cache if plants grow.
    out = []
    for p in meta_repo.list_plants(ctx.conn):
        code = p["plant_code"]
        if code == ctx.plant or (ctx.plant_scope is not None and code not in ctx.plant_scope):
            continue
        if ctx.used in set(ws_repo.months(ctx.conn, code, ctx.plant_scope)) | set(
                film_repo.film_months(ctx.conn, code, ctx.plant_scope)):
            out.append((code, p["plant_name"] or code))
    return out


def car_labels(ctx) -> dict[str, str]:
    """logical_vehicle_id -> the car number the plant's car rule cuts from the job number, else the id."""
    rule = pairing_repo.car_rule(ctx.conn, ctx.plant)
    try:  # shortcut: POSIX classes ([[:digit:]]) are not Python regex; fall back to the id
        rx = re.compile(rule["pattern"]) if rule and "[[:" not in rule["pattern"] else None
    except re.error:
        rx = None
    out: dict[str, str] = {}
    for r in ctx.load(ctx.used).readings:
        if r.car and r.car not in out:
            m = rx.search(r.job_no) if rx and r.job_no else None
            out[r.car] = (m.group(1) if rx.groups and m.group(1) else m.group(0)) if m else r.car
    return out


def choices(kind: str, ctx, wide: bool = False) -> list[tuple[str, str]]:
    """(value, label) pairs that have readings in the month used; ``wide`` drops the kind's own filter."""
    if kind in STATIC:
        return STATIC[kind]
    if kind == "month":
        return [(m, month_words(m)) for m in ctx.months]
    if kind == "plant":
        return _plants(ctx)
    data = ctx.load_ignoring(PAIR_WIDE[kind][0]) if wide else ctx.load(ctx.used)
    boxes, recs = data.boxes, data.readings
    if kind == "box":
        return sorted(((b.key, b.label) for b in boxes), key=lambda c: c[1])
    if kind == "band":
        present = {r.metric for r in recs if r.domain == "wavescan"}
        return [(m, BAND_WORD[m]) for m in BANDS if m in present]
    if kind in ("layer", "metric"):
        film = [(code, LAYER_WORD[code]) for code in LAYERS if any(b.layer == code for b in boxes)]
        if kind == "layer":
            return film
        present = {r.metric for r in recs if r.domain == "wavescan"}
        return film + [(m, BAND_WORD.get(m, m.upper())) for m in WS_METRICS if m in present]
    if kind == "car":
        labels = car_labels(ctx)
        return sorted(labels.items(), key=lambda c: c[1])
    values = {
        "model": {b.model for b in boxes},
        "colour": {b.color for b in boxes},
        "colour_family": {r.family for r in recs if r.family},
        "point": {r.point for r in recs if r.point},
    }[kind]
    return [(v, v) for v in sorted(values)]


def _miss_line(kind: str, value: str, ctx) -> str:
    if kind == "month":
        return f"No readings in {month_words(value)}."
    if kind == "plant":
        return f"{value} has no readings in {month_words(ctx.used)}."
    return f"No readings for {value} in {month_words(ctx.used)} with these filters."


def _ask(slot: SlotSpec, options: list[tuple[str, str]], miss: str | None, ctx) -> Answer:
    prompt = slot.prompt if miss is None else f"{_miss_line(slot.kind, miss, ctx)}\n{slot.prompt}"
    return Answer(status="needs_slot", headline=prompt,
                  method={"rule": "Asks for a missing detail; choices come from this month's readings.",
                          "n": len(options), "caveats": []},
                  slot={"name": slot.name, "prompt": prompt,
                        "choices": [{"value": v, "label": label} for v, label in options]})


def resolve(question: Question, params: dict[str, str | None], ctx) -> dict[str, str] | Answer:
    """The filled slots, or a needs_slot Answer for the first missing or unknown one.

    Optional slots pass through unchecked: their topic owns the default and the
    "no readings" answer (AR04 trend keeps its own wording).
    """
    if gate := domain_gate(question.id, getattr(ctx, "domain", "both")):
        return not_enough(gate, 0, "The question needs the other instrument")
    filled: dict[str, str] = {}
    for slot in question.slots:
        value = params.get(slot.name) or None
        if not slot.required:
            if value is not None:
                filled[slot.name] = value
            continue
        if slot.kind == "car" and ctx.domain == "wavescan":
            return not_enough(CARS_NO_FILM, 0, "A car compare needs Film readings")
        taken = {filled[s.name] for s in question.slots if s.kind == slot.kind and s.name in filled}
        wide = slot.name in ("a", "b") and slot.kind in PAIR_WIDE
        options = [c for c in choices(slot.kind, ctx, wide) if c[0] not in taken]
        if question.id == "cf_drivers" and slot.kind == "box":  # CF drivers are Wave Scan only
            options = [c for c in options if c[0].startswith("wavescan|")]
        if wide and not options:
            return not_enough(f"No other {PAIR_WIDE[slot.kind][1]} has readings in {month_words(ctx.used)} "
                              "with these filters.", 0, "A compare needs two with readings this month")
        if not options:  # nothing to tap: say so rather than ask with no chips (live: CF drivers, no Wave Scan)
            miss = (_miss_line(slot.kind, value, ctx) if value is not None and value not in taken
                    else f"No readings to choose from in {month_words(ctx.used)} with these filters.")
            return not_enough(miss, 0, "A pick needs readings this month")
        if value is None or value not in {v for v, _ in options}:
            return _ask(slot, options, None if value in taken else value, ctx)
        filled[slot.name] = value
    return filled
