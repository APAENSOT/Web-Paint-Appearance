"""AR05 compare topics: models, colours, orientation, months. Pick the readings, call the core."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from statistics import mean, median

from app.domain.assistant.answer import Answer, Box, all_clear, not_enough, severity
from app.domain.assistant.changes import changes
from app.domain.assistant.compare import LIMITS_DIFFER, compare_groups, compare_values, difference_words, group_stats
from app.domain.assistant.plain_words import difference_sentence, gap_words, model_word, plural
from app.domain.assistant.readings import Reading, side_panel
from app.domain.report_summary import BAND_WORD, LAYER_WORD, month_words

FAMILIES_RULE = "Worst family = most boxes not Pass; its readings against all other families (Mann-Whitney, 0.05 and 0.5 sd)"
BADNESS = {"FAIL": 3, "OVER": 2, "WARNING": 1}


def _metric_word(metric: str) -> str:
    return LAYER_WORD.get(metric) or BAND_WORD.get(metric, metric.upper())


def _limits(rs: list[Reading], metric: str, boxes: list[Box]) -> tuple[dict | None, list[str]]:
    """Drawn only when every box behind the readings shares one lsl/usl; none for bands without limits."""
    if metric not in LAYER_WORD and metric != "cf":
        return None, []
    by_key = {b.key: b for b in boxes}
    mine = [by_key[k] for k in {r.box_key for r in rs} if k in by_key]
    pairs = {(b.lsl, b.usl) for b in mine}
    if len(pairs) > 1:
        return None, [LIMITS_DIFFER]
    if not pairs or pairs == {(None, None)}:
        return None, []
    lo, hi = next(iter(pairs))
    return {"lo": lo, "hi": hi}, []


def _worst_key(rs: list[Reading], boxes: list[Box]) -> str | None:
    keys = {r.box_key for r in rs}
    bad = [b for b in boxes if b.key in keys and b.status in BADNESS]
    return max(bad, key=lambda b: (BADNESS[b.status], severity(b))).key if bad else None


def _compare(label_a: str, label_b: str, metric: str, ra: list[Reading], rb: list[Reading],
             boxes: list[Box], other: dict, say: tuple[str, str] | None = None) -> Answer:
    ra, rb = ([r for r in rs if r.metric == metric] for rs in (ra, rb))
    limits, caveats = _limits(ra + rb, metric, boxes)
    target = _worst_key(ra + rb, boxes)
    follow = ([{"label": "Why is it failing?", "topic": "why_failing", "target": target}] if target else []) + [other]
    return compare_groups(label_a, label_b, [r.value for r in ra], [r.value for r in rb],
                          "µm" if metric in LAYER_WORD else "", _metric_word(metric), limits, caveats, follow,
                          say=say)


def _pair(field: Callable[[Reading], str], name: Callable[[str], str], other: dict,
          say: Callable[[str], str] | None = None):
    def run(a: str, b: str, metric: str, readings: list[Reading], boxes: list[Box] = ()) -> Answer:
        ra = [r for r in readings if field(r) == a and r.metric == metric]
        rb = [r for r in readings if field(r) == b and r.metric == metric]
        ans = _compare(name(a), name(b), metric, ra, rb, list(boxes), other, (say(a), say(b)) if say else None)
        hv = lambda rs, o: sum(r.orient.startswith(o) for r in rs)  # noqa: E731
        if all(hv(ra + rb, o) for o in "HV"):  # orientations are pooled, so say how
            ans.method["caveats"].append(f"Both orientations pooled: {name(a)} H {hv(ra, 'H')} / V {hv(ra, 'V')}, "
                                         f"{name(b)} H {hv(rb, 'H')} / V {hv(rb, 'V')}.")
            ans.explanation += " Both orientations are pooled here, so a horizontal–vertical gap could hide inside these numbers."
        return ans
    return run


_last = lambda m: m.split()[-1] if m.split() else m  # noqa: E731
compare_models = _pair(lambda r: r.model, _last, {"label": "Compare colours", "topic": "compare_colours", "target": None},
                       model_word)
compare_colours = _pair(lambda r: r.color, str, {"label": "Compare models", "topic": "compare_models", "target": None})


def compare_orient(colour: str, metric: str, readings: list[Reading], boxes: list[Box] = ()) -> Answer:
    mine = [r for r in readings if r.color == colour]
    return _compare("Horizontal", "Vertical", metric, [r for r in mine if r.orient.startswith("H")],
                    [r for r in mine if r.orient.startswith("V")], list(boxes),
                    {"label": "Compare models", "topic": "compare_models", "target": None})


def compare_months(now: list[Box], other: list[Box], month: str, month2: str) -> Answer:
    """AR04 `changes` with the later month as 'now' and the earlier as 'before', whichever slot named it."""
    later = max(month, month2)
    if month2 > month:
        now, other, month2 = other, now, month
    return changes(now, other, month2, now_month=later)


SIDES_RULE = "Left vs right per twin panel, then all left against all right (Mann-Whitney, 0.05 and 0.5 sd)"
MIN_TWIN_PANELS = 3


def compare_sides(metric: str, readings: list[Reading], boxes: list[Box] = ()) -> Answer:
    unit, word = ("µm" if metric in LAYER_WORD else ""), _metric_word(metric)
    rs = [r for r in readings if r.metric == metric]
    panels: dict[str, dict[str, list[float]]] = {}
    for r in rs:
        if sp := side_panel(r.point):
            panels.setdefault(sp[1], {"L": [], "R": []})[sp[0]].append(r.value)
    unsided = len({r.point for r in rs if r.point and not side_panel(r.point)})
    twins = {p: s for p, s in panels.items() if s["L"] and s["R"]}
    verdicts = {p: compare_values(s["L"], s["R"]) for p, s in twins.items()}
    counted = [p for p, v in verdicts.items() if v]
    if len(counted) < MIN_TWIN_PANELS:
        return not_enough("Not enough left–right panel pairs to compare.", len(rs), SIDES_RULE)
    left = [x for p in counted for x in twins[p]["L"]]
    right = [x for p in counted for x in twins[p]["R"]]
    v = compare_values(left, right)
    same_way = [p for p in counted if verdicts[p].delta * v.delta > 0] or counted
    biggest = max(same_way, key=lambda p: abs(verdicts[p].delta))
    if v.real:
        dirn = ("thinner" if v.delta < 0 else "thicker") if unit else ("lower" if v.delta < 0 else "higher")
        headline = (f"Left runs {abs(v.delta):.1f}{' ' + unit if unit else ''} {dirn} on {word}"
                    f" — real difference (biggest at {biggest})")
    else:
        headline = f"No real left–right difference on {word}"
    rows = [[p, round(median(twins[p]["L"]), 1), round(median(twins[p]["R"]), 1), f"{verdicts[p].delta:+.1f}",
             "Real difference" if verdicts[p].real else "No real difference"]
            for p in sorted(counted, key=lambda p: -abs(verdicts[p].delta))]
    rows += [[p, round(median(s["L"]), 1), round(median(s["R"]), 1), f"{median(s['L']) - median(s['R']):+.1f}",
              "Too few readings"] for p, s in twins.items() if not verdicts[p]]
    real_n = sum(verdicts[p].real for p in counted)
    pairs = plural(len(counted), "panel pair")
    if v.real:
        text = (f"Left-side panels run {gap_words(v.delta, unit)} on {word} than the right, across {pairs}. "
                f"That's {difference_sentence(v)}; {real_n} of {len(counted)} panel pairs differ on their own, "
                f"the biggest at {biggest}.")
    else:
        text = (f"Left and right panels match on {word} across {pairs}; the overall gap is within day-to-day noise. "
                + (f"{real_n} of {len(counted)} panel pairs differ on their own, so check those panels." if real_n
                   else "No single panel pair differs on its own either."))
    return Answer(
        status="answer", headline=headline,
        proof=f"{len(counted)} panel pairs, {real_n} with a real difference; n {v.n_a} left and {v.n_b} right",
        explanation=text,
        confidence="solid",
        evidence={"kind": "mirrored_bar", "columns": ["Panel", "Left", "Right", "Δ", "Verdict"], "rows": rows,
                  "series": [], "groups": [], "limits": None},
        followups=[{"label": "Compare colour families", "topic": "compare_families", "target": None}],
        method={"rule": SIDES_RULE, "n": len(left) + len(right),
                "caveats": [f"{unsided} points without a side left out"] if unsided else []},
    )


def compare_families(metric: str, readings: list[Reading], boxes: list[Box] = ()) -> Answer:
    word = _metric_word(metric)
    if metric not in LAYER_WORD and metric != "cf":
        return not_enough(f"{word} has no standard, so no family has problems to count.", 0, FAMILIES_RULE)
    rs = [r for r in readings if r.metric == metric]
    bad = {b.key for b in boxes if b.status not in ("PASS", None) and (b.layer == metric or (metric == "cf" and b.layer is None))}
    fam = lambda r: r.family or "No family"  # noqa: E731
    by_fam: dict[str, list[Reading]] = {}
    by_box: dict[str, Counter] = {}
    for r in rs:
        by_fam.setdefault(fam(r), []).append(r)
        by_box.setdefault(r.box_key, Counter())[fam(r)] += 1
    problems = Counter(c.most_common(1)[0][0] for k, c in by_box.items() if k in bad)  # box -> its main family
    if not problems:
        a = all_clear(f"No {word} problems to attribute to a colour family.", FAMILIES_RULE, len(rs))
        a.explanation = f"No {word} box in any colour family is off Pass this month, so nothing needs action."
        return a
    outs = {f: sum(bool(r.out) for r in g) for f, g in by_fam.items()}
    order = sorted(by_fam, key=lambda f: (-problems[f], -outs[f], f))
    worst = order[0]
    v = compare_values([r.value for r in by_fam[worst]], [r.value for f in order[1:] for r in by_fam[f]])
    if v is None:
        return not_enough(f"Not enough readings to compare {worst} with the other families.", len(rs), FAMILIES_RULE)
    k, n = problems[worst], sum(problems.values())
    limits, caveats = _limits(rs, metric, list(boxes))
    target = _worst_key(by_fam[worst], list(boxes))
    groups = [group_stats(f, [r.value for r in by_fam[f]]) for f in order]
    gap = gap_words(v.delta, "µm" if metric in LAYER_WORD else "")
    text = f"{worst} {'drives' if k == 1 else 'drive'} {k} of {n} {word} problem boxes this month. " + (
        f"Its {word} median runs {gap} than the other families', {difference_sentence(v)}." if v.real and gap
        else f"Its {word} readings are within day-to-day noise of the other families, so the family doesn't "
             "explain the problems.")
    return Answer(
        status="answer",
        headline=f"{worst} {'drives' if k == 1 else 'drive'} {k} of {n} {word} problems",
        proof=difference_words(v, "µm" if metric in LAYER_WORD else "", worst, "the other families", word),
        explanation=text,
        confidence="solid",
        evidence={"kind": "boxplot_group", "columns": ["Family", "n", "Q1", "Median", "Q3", "Mean"],
                  "rows": [[g["label"], g["n"], *(round(g[x], 2) for x in ("q1", "median", "q3", "mean"))]
                           for g in groups],
                  "series": [], "groups": groups, "limits": limits},
        followups=([{"label": "Why is it failing?", "topic": "why_failing", "target": target}] if target else []),
        method={"rule": FAMILIES_RULE, "n": v.n_a + v.n_b, "caveats": caveats},
    )


CARS_RULE = "Each point's reading on car A against car B; out = outside that box's limits"
CARS_NO_FILM = "Car questions use Film cars; Wave Scan readings are not linked to cars here."
PLANTS_RULE = "Same model and metric, colour families present in both plants (Mann-Whitney, 0.05 and 0.5 sd)"
OWN_LIMITS = "Each plant has its own limits, so none are drawn."


def _panel(point: str) -> str:
    sp = side_panel(point)
    return sp[1] if sp else re.sub(r"^\d+", "", point)


def compare_cars(a: str, b: str, readings: list[Reading], labels: dict[str, str] | None = None) -> Answer:
    film = [r for r in readings if r.domain == "film" and r.car in (a, b)]
    if not all(any(r.car == c for r in film) for c in (a, b)):
        return not_enough(CARS_NO_FILM, 0, CARS_RULE)
    cell: dict[tuple[str, str], dict[str, list[Reading]]] = {}
    for r in film:
        cell.setdefault((r.layer or "", r.point or "—"), {a: [], b: []})[r.car].append(r)
    order = list(LAYER_WORD)
    keys = sorted(cell, key=lambda k: (order.index(k[0]) if k[0] in order else len(order), k[1]))
    val = lambda rs: f"{mean(r.value for r in rs):.1f}" if rs else "—"  # noqa: E731
    out = lambda rs: any(r.out for r in rs)  # noqa: E731
    rows = [[LAYER_WORD.get(k[0], k[0]), k[1], val(cell[k][a]), val(cell[k][b]),
             " · ".join(w for w, c in (("A out", a), ("B out", b)) if out(cell[k][c]))] for k in keys]
    name = lambda c: (labels or {}).get(c, c)  # noqa: E731
    n = sum(bool(cell[k][b]) for k in keys)
    bad = [k for k in keys if out(cell[k][b])]
    k_a = sum(out(cell[k][a]) for k in keys)
    n_a = sum(bool(cell[k][a]) for k in keys)
    if not bad:
        headline = f"Car {name(b)} has no points out ({n} measured)"
        text = f"Car {name(b)} has no points out across {n} measured points. " + (
            f"Car {name(a)} is out at {k_a} of {n_a}, so car {name(b)} is the better of the two." if k_a
            else f"Car {name(a)} has none out either, so both cars are inside the standard.")
    else:
        headline = f"Car {name(b)} is out at {len(bad)} of {n} points"
        panels = {_panel(p) for _, p in bad}
        one = len(bad) >= 2 and len(panels) == 1
        if one:
            headline += f", all on {next(iter(panels))}"
        text = f"Car {name(b)} is out at {len(bad)} of {n} measured points" + (
            f", all on the {next(iter(panels))}. " if one else ". ")
        if not k_a:
            text += f"Car {name(a)} has no points out on the same check, so the trouble is specific to car {name(b)}."
        elif k_a > len(bad):
            text += f"Car {name(a)} is out at {k_a} of {n_a}, so car {name(a)} is the worse of the two."
        else:
            text += f"Car {name(a)} is out at {k_a} of {n_a}, so the two cars share some of the trouble."
    return Answer(
        status="answer", headline=headline,
        proof=f"Car {name(a)} is out at {k_a} of {n_a} points; {len(keys)} points across both cars",
        explanation=text,
        confidence="solid",
        evidence={"kind": "point_bars", "columns": ["Layer", "Point", "Car A", "Car B", "Out"], "rows": rows,
                  "series": [], "groups": [], "limits": None},
        followups=[{"label": "Compare plants", "topic": "compare_plants", "target": None}],
        method={"rule": CARS_RULE, "n": len(film), "caveats": []},
    )


def compare_plants(plant: str, plant2: str, metric: str, here: list[Reading], there: list[Reading],
                   models: list[str], month: str) -> Answer:
    here, there = ([r for r in rs if r.metric == metric] for rs in (here, there))
    when = month_words(month)
    if len(models) == 1:
        model = models[0]
        if not any(r.model == model for r in there) or not any(r.model == model for r in here):
            return not_enough(f"{plant2} has no {_last(model)} readings in {when}.", 0, PLANTS_RULE)
    else:
        shared = {r.model for r in here} & {r.model for r in there}
        if not shared:
            return not_enough(f"{plant2} shares no model with {plant} in {when}.", 0, PLANTS_RULE)
        model = max(shared, key=lambda m: (sum(r.model == m for r in here), m))
    here, there = ([r for r in rs if r.model == model] for rs in (here, there))
    fams = {r.family for r in here if r.family} & {r.family for r in there if r.family}
    if not fams:
        return not_enough(f"{plant} and {plant2} share no colour family on {_last(model)} in {when}.", 0, PLANTS_RULE)
    ans = compare_groups(plant, plant2, [r.value for r in here if r.family in fams],
                         [r.value for r in there if r.family in fams], "µm" if metric in LAYER_WORD else "",
                         _metric_word(metric), None, [OWN_LIMITS], [], scope=f"{model_word(model)} ")
    if ans.status == "answer":
        ans.headline = f"{_last(model)}: {ans.headline}"
        ans.method["rule"] = PLANTS_RULE
    return ans
