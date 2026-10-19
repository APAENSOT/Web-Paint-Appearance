"""AR05 problem topics: why a box fails (where its outs concentrate), few cars or whole process, worst cars.

Pure: counts and an exact binomial test, nothing graded. Film cars only for the car topics.
"""

from __future__ import annotations

from collections import Counter

from app.domain.assistant.answer import MIN_BOX_N, POINT_P, Answer, Box, all_clear, not_enough
from app.domain.assistant.compare_topics import CARS_NO_FILM
from app.domain.assistant.plain_words import box_words, plural
from app.domain.assistant.readings import Reading, side_panel, week_of_reading
from app.domain.report_stats import binomial_sf
from app.domain.report_summary import LAYER_WORD, month_words

WHY_RULE = ("Out readings split by point, side, week and car; a group counts when the largest groups holding half "
            "the outs (up to 3) each hold far more outs than their share of readings (binomial, 0.01)")
CARS_RULE = "Few cars when at most one fifth of the cars hold at least four fifths of the outs"
WORST_RULE = "Film cars ranked by how many measured points are out"
CENTRE_RULE = ("With a target: centring when the mean is at least one σ from it, else spread when σ grew at least "
               "a quarter since last month; without one the larger of a mean move of half a σ or more and σ growth "
               "of a quarter or more since last month, in last month's σ units")
OFFSET_SIGMA, MOVE_SIGMA, SPREAD_MOVE, SPREAD_WEIGHT, BINS = 1.0, 0.5, 0.25, 4, 10
MIN_CARS = 5
HALF, FEW_SHARE, FEW_OUTS, MAX_TAKE, ROWS = 0.5, 0.2, 0.8, 3, 10
SIDE_WORD = {"L": "left", "R": "right"}
DIMS = (("point", "Point"), ("side", "Side"), ("week", "Week"), ("car", "Car"))


def _category(dim: str, r: Reading, labels: dict[str, str]) -> str | None:
    if dim == "point":
        return r.point
    if dim == "side":
        sp = side_panel(r.point)
        return SIDE_WORD[sp[0]] if sp else None
    if dim == "week":
        w = week_of_reading(r.date)
        return str(w) if w else None
    return labels.get(r.car, r.car) if r.domain == "film" and r.car else None


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _concentration(dim: str, base: list[Reading], labels: dict[str, str]):
    """(all out-bearing categories as (name, out, readings), the taken names or None)."""
    seen = [(c, r.out is True) for r in base if (c := _category(dim, r, labels)) is not None]
    total, outs = Counter(c for c, _ in seen), Counter(c for c, o in seen if o)
    out_total = sum(outs.values())
    ranked = sorted(outs.items(), key=lambda kv: (-kv[1], kv[0]))
    rows = [(c, o, total[c]) for c, o in ranked]
    taken, held = [], 0
    for c, o in ranked:
        taken.append(c)
        held += o
        if held >= HALF * out_total or len(taken) == MAX_TAKE:
            break
    ok = (held >= HALF * out_total
          and all(binomial_sf(outs[c], out_total, total[c] / len(seen)) < POINT_P for c in taken)
          and not (dim == "side" and len(taken) > 1))  # both sides is no concentration
    return rows, taken if ok else None


def why_failing(box: Box, readings: list[Reading], labels: dict[str, str] | None = None) -> Answer:
    labels = labels or {}
    base = [r for r in readings if r.box_key == box.key and r.out is not None
            and (box.domain == "film" or r.metric == "cf")]
    if not any(r.out for r in base):
        a = all_clear(f"{box.label}: no readings out this month.", WHY_RULE, len(base))
        a.explanation = f"No reading of {box_words(box)}, was out this month."
        return a
    rows, won, held = [], {}, {}
    for dim, word in DIMS:
        found, taken = _concentration(dim, base, labels)
        if taken:
            won[dim] = taken
            held[dim] = sum(o for c, o, _ in found if c in taken)
        for c, o, n in found[:ROWS]:
            rows.append([word, f"Week {c}" if dim == "week" else c, o, n])
    pieces = []
    if "point" in won:
        one_side = "side" in won and all((sp := side_panel(p)) and SIDE_WORD[sp[0]] == won["side"][0]
                                         for p in won["point"])
        pieces.append("at " + _join(won["point"]) + (f" {won['side'][0]}" if one_side else ""))
    elif "side" in won:
        pieces.append(f"on the {won['side'][0]} side")
    if "week" in won:
        pieces.append(f"in week{'' if len(won['week']) == 1 else 's'} {_join(won['week'])}")
    if "car" in won:
        k = len(won["car"])
        pieces.append(f"on {k} car{'' if k == 1 else 's'}")
    headline = (f"{box.label}: concentrated {', '.join(pieces)}" if pieces
                else f"{box.label}: spread across the process")
    follow = [{"label": "Is it trending?", "topic": "trend", "target": box.key}]
    if box.domain == "film":
        follow.append({"label": "A few cars or the whole process?", "topic": "cars_or_process", "target": box.key})
    total = sum(1 for r in base if r.out)
    film = box.domain == "film"
    if pieces:
        first = next(d for d, _ in DIMS if d in won)
        place, why = {
            "point": ("at " + _join(won.get("point", [""])), "so look at that spot first"),
            "side": (f"on the {won.get('side', [''])[0]} side", "so look at that side first"),
            "week": (f"in week{'' if len(won.get('week', [])) == 1 else 's'} {_join(won.get('week', ['']))}",
                     "so look for what changed on the line that week"),
            "car": (f"on those {plural(len(won.get('car', [])), 'car')}",
                    "so check those cars' history before changing the process")}[first]
        text = (f"{box_words(box)}, has its out readings bunched {', '.join(pieces)}. {held[first]} of {total} outs "
                f"are {place}, far more than their share of the readings, {why}.")
        if "car" in won and first != "car":
            text += " They also sit on a few cars, so check those cars' history too."
    else:
        cars = len({r.car for r in base if r.car})
        text = (f"The 1 out reading on {box_words(box)}, is a one-off, not a pattern. " if total == 1 else
                f"The {total} out readings on {box_words(box)}, are spread over points, sides"
                + (", weeks and cars. " if film else " and weeks. "))
        if film and total >= MIN_CARS and cars >= MIN_CARS:
            text += "No spot or car holds more than its share, so it's the process, not individual cars."
        elif not film and total >= MIN_CARS:
            text += "No spot holds more than its share, so it's the process rather than one spot."
        else:
            text += (f"There are too few out readings{' or cars' if film else ''} to tell one spot"
                     f"{' or car' if film else ''} from the whole process.")
    return Answer(
        status="answer", headline=headline, status_code=box.status, confidence="solid", explanation=text,
        evidence={"kind": "breakdown", "columns": ["By", "Where", "Out", "Readings"], "rows": rows},
        followups=follow, method={"rule": WHY_RULE, "n": len(base), "caveats": []})


def _per_car(rs: list[Reading], labels: dict[str, str]) -> list[list]:
    out, seen = Counter(), Counter()
    for r in rs:
        if r.car and r.out is not None:
            seen[r.car] += 1
            out[r.car] += r.out is True
    order = sorted(seen, key=lambda c: (-out[c], labels.get(c, c)))
    return [[labels.get(c, c), out[c], seen[c]] for c in order]


def cars_or_process(box: Box, readings: list[Reading], labels: dict[str, str] | None = None) -> Answer:
    if box.domain != "film":
        return not_enough(CARS_NO_FILM, 0, CARS_RULE)
    rows = _per_car([r for r in readings if r.box_key == box.key], labels or {})
    if not rows:
        return not_enough(f"{box.label}: no readings are linked to cars.", 0, CARS_RULE)
    n, t = len(rows), sum(r[1] for r in rows)
    if not t:
        a = all_clear(f"{box.label}: no readings out this month.", CARS_RULE, n)
        a.explanation = f"No reading of {box_words(box)}, was out this month, across {plural(n, 'car')} measured."
        return a
    if n < MIN_CARS:
        return not_enough(f"{n} car{'' if n == 1 else 's'}; {MIN_CARS} needed to tell a few cars from the process.",
                          n, CARS_RULE)
    k = held = 0
    for r in rows:
        k, held = k + 1, held + r[1]
        if held >= FEW_OUTS * t:
            break
    few = k <= FEW_SHARE * n
    headline = (f"{box.label}: a few cars — {k} of {n} cars hold {held} of {t} outs" if few
                else f"{box.label}: whole process — {sum(1 for r in rows if r[1])} of {n} cars have readings out")
    if few:
        text = (f"For {box_words(box)}, {k} of {n} cars hold {held} of {t} out readings. That's a few cars, so check "
                f"those cars' history before changing the process; the worst is car {rows[0][0]}, with "
                f"{plural(rows[0][1], 'point')} out.")
    else:
        text = (f"For {box_words(box)}, {sum(1 for r in rows if r[1])} of {n} cars have readings out. The outs are "
                "spread over too many cars to blame a few, so it's the process, not individual cars.")
    return Answer(
        status="answer", headline=headline, status_code=box.status, confidence="solid", explanation=text,
        evidence={"kind": "car_bars", "columns": ["Car", "Points out", "Points measured"], "rows": rows[:ROWS]},
        followups=[{"label": "Why is it failing?", "topic": "why_failing", "target": box.key}],
        method={"rule": CARS_RULE, "n": n, "caveats": []})


def worst_cars(readings: list[Reading], labels: dict[str, str] | None = None) -> Answer:
    labels = labels or {}
    film = [r for r in readings if r.domain == "film"]
    rows = _per_car(film, labels)
    if not rows:
        return not_enough(CARS_NO_FILM, 0, WORST_RULE)
    if not rows[0][1]:
        a = all_clear("No Film readings out this month.", WORST_RULE, len(rows))
        a.explanation = f"No Film reading was out on any of the {plural(len(rows), 'car')} measured this month."
        return a
    top = rows[0]
    by_box = Counter(r.box_key for r in film if r.out is True and labels.get(r.car, r.car) == top[0])
    hit, n = sum(1 for r in rows if r[1]), len(rows)
    # No few-cars or process verdict here: that is cars_or_process's own test, per box.
    text = (f"{hit} of {plural(n, 'car')} had Film points out this month. The worst is car {top[0]}, with {top[1]} of "
            f"{top[2]} measured points out, so open its history first.")
    return Answer(
        status="answer", headline=f"Car {top[0]}: {top[1]} points out — open its history", confidence="solid",
        explanation=text,
        evidence={"kind": "car_bars", "columns": ["Car", "Points out", "Points measured"], "rows": rows[:ROWS]},
        followups=[{"label": "Why is it failing?", "topic": "why_failing", "target": by_box.most_common(1)[0][0]}],
        method={"rule": WORST_RULE, "n": len(rows), "caveats": []})


def _usable(b: Box | None) -> bool:
    return b is not None and len(b.values) >= MIN_BOX_N and (b.sd or 0) >= 1e-9


def _toward(box: Box, moved: float) -> str:
    lo, hi = ("Lo" if box.layer else "minimum"), "Hi"
    if box.lsl is not None and moved < 0:
        return f"toward {lo}"
    if box.usl is not None and moved > 0:
        return f"toward {hi}"
    if box.lsl is not None:
        return f"away from {lo}"
    return f"away from {hi}" if box.usl is not None else ("up" if moved > 0 else "down")


def centre_or_spread(box: Box, before: Box | None, target: float | None, before_month: str | None = None) -> Answer:
    if not _usable(box):
        return not_enough("Not enough readings in this box to judge centring or spread.", len(box.values), CENTRE_RULE)
    mean, sd, unit = box.mean, box.sd, f" {box.unit}" if box.unit else ""
    u = unit or (" CF points" if box.domain == "wavescan" else "")
    who = box_words(box)
    base = _usable(before)
    s0 = before.sd if base else None
    spread = (sd - s0) / s0 if base else None  # signed: only a σ that grew counts as spread
    since = month_words(before_month) if before_month else "previous month"
    word = LAYER_WORD[box.layer] if box.layer else "CF"
    re_centre, reduce = f"Re-centre {word} build", f"Reduce {word} variation (check {word} application consistency)"
    spread_said = f"{box.label}: spread — σ {sd:.1f}{unit} vs {s0 or 0:.1f}{unit} last month"
    step = None
    last = "last month" if before_month else "the previous month"
    if base:
        ratio = sd / s0
        wide = "about twice as wide" if 1.8 <= ratio < 2.3 else f"about {ratio:.1f} times as wide"
        then = f"in {since}" if before_month else "last month"
        spread_text = (f"For {who}, the readings have become more scattered: their typical scatter is {sd:.1f}{u} "
                       f"against {s0:.1f}{u} {then}, {wide}. Making the {word} build more consistent will help more "
                       "than moving its average.")
    if target is not None:
        offset = abs(mean - target) / sd
        d = f"{abs(mean - target):.1f}{unit} from target"
        off = (f"For {who}, the average sits {abs(mean - target):.1f}{u} {'above' if mean > target else 'below'} "
               f"its target of {target:.1f}{u}. Re-centring the {word} build will help more than reducing its scatter.")
        if offset >= OFFSET_SIGMA:
            headline, step, text = f"{box.label}: centring — mean {d}", re_centre, off
        elif not base:
            headline = f"{box.label}: well centred — mean {d}; no {since} baseline to judge spread"
            text = (f"For {who}, the average is close to its target, only {abs(mean - target):.1f}{u} away. There "
                    f"are no {since} readings to tell whether the scatter has grown.")
        elif spread >= SPREAD_MOVE and spread * SPREAD_WEIGHT > offset:
            headline, step, text = spread_said, reduce, spread_text
        else:
            headline, step, text = f"{box.label}: centring — mean {d}", re_centre, off
    elif base:
        moved = mean - before.mean
        offset = abs(moved) / s0
        if offset < MOVE_SIGMA and spread < SPREAD_MOVE:
            headline = f"{box.label}: no meaningful change in centring or spread since {since}"
            text = (f"For {who}, neither the average nor the scatter has changed much since {since}. The average is "
                    f"{mean:.1f}{u} with a typical scatter of {sd:.1f}{u}, much as {last}.")
        elif offset >= MOVE_SIGMA and (spread < SPREAD_MOVE or offset >= spread):
            toward = _toward(box, moved)
            headline, step = f"{box.label}: centring — mean moved {offset:.1f}σ {toward}", re_centre
            plain = {"Lo": "the low limit", "Hi": "the high limit", "minimum": "the minimum"}
            toward = " ".join(plain.get(w, w) for w in toward.split())
            text = (f"For {who}, the average has moved {abs(moved):.1f}{u} {toward} since {since}. That's "
                    f"{offset:.1f} times {last}'s typical scatter, so re-centre the {word} build.")
        else:
            headline, step, text = spread_said, reduce, spread_text
    else:
        return not_enough(f"No {since} baseline to compare spread.", len(box.values), CENTRE_RULE)
    lo, hi = min(box.values), max(box.values)
    width = (hi - lo) / BINS
    counts = [0] * BINS
    for v in box.values:
        counts[min(int((v - lo) / width), BINS - 1)] += 1
    dp = 1 if width >= 0.1 else 2 if width >= 0.01 else 4
    rows = [[f"{lo + i * width:.{dp}f}–{lo + (i + 1) * width:.{dp}f}", c] for i, c in enumerate(counts)]
    card = [{"label": "Mean", "value": f"{mean:.1f}{unit}"}, {"label": "σ", "value": f"{sd:.1f}{unit}"}]
    if base:
        card.append({"label": "Last month σ", "value": f"{s0:.1f}{unit}"})
    if target is not None:
        card.append({"label": "Target", "value": f"{target:.1f}{unit}"})
    return Answer(
        status="answer", headline=headline, status_code=box.status, next_step=step, confidence="solid",
        explanation=text,
        proof=f"{len(box.values)} readings, mean {mean:.1f}{unit}, σ {sd:.1f}{unit}",
        evidence={"kind": "distribution", "columns": ["Bin", "Readings"], "rows": rows, "card": card,
                  "limits": {"lo": box.lsl, "hi": box.usl}},
        followups=[{"label": "Why is it failing?", "topic": "why_failing", "target": box.key},
                   {"label": "Is it trending?", "topic": "trend", "target": box.key}],
        method={"rule": CENTRE_RULE, "n": len(box.values), "caveats": []})
