"""AR05 colour report and model report: a status grid built from the overview's own box status.

Pure. A cell is the worst status of the boxes that fall in it; its word is the dashboard's word
for the box that sets it. Nothing is graded here.
"""

from __future__ import annotations

from collections import defaultdict
from math import sqrt

from app.domain.assistant.answer import MIN_BOX_N, MIN_POINT_OUT, POINT_P, Answer, Box, all_clear, not_enough, severity
from app.domain.assistant.changes import Shift, toward_limit, shifts
from app.domain.assistant.plain_words import box_words, difference_sentence, gap_words, model_word, panels_words, plural
from app.domain.assistant.readings import Reading, week_of_reading
from app.domain.report_stats import binomial_sf, cpk
from app.domain.report_summary import LAYER_WORD, month_words, status_word

LAYERS = (*LAYER_WORD, None)  # None is the Wave Scan CF box
LAYER_NAME = {**LAYER_WORD, None: "CF"}
BADNESS = {"FAIL": 4, "OVER": 3, "WARNING": 2, "PASS": 1, None: 0}
COLUMNS = [LAYER_NAME[layer] for layer in LAYERS]
COLOUR_RULE = "One cell per colour and layer: the worst box status, named by its model and orientation"
MODEL_RULE = "One cell per layer and orientation: the worst box status, named by its colour"


def _last(model: str) -> str:
    return model.split()[-1] if model.split() else model


def _worst(boxes: list[Box]) -> Box | None:
    return max(boxes, key=lambda b: (BADNESS[b.status], severity(b)), default=None)


def _cell(box: Box | None, prev: Box | None, note: str) -> dict:
    if box is None:
        return {"status_code": None, "word": "—", "note": "", "arrow": ""}
    arrow = ""
    if prev is not None and BADNESS[prev.status] != BADNESS[box.status]:
        arrow = "↑" if BADNESS[box.status] < BADNESS[prev.status] else "↓"
    return {"status_code": box.status, "word": status_word(box.status, box.scope, box.layer),
            "note": "" if box.status == "PASS" else note, "arrow": arrow}


def _evidence(columns: list[str], labels: list[str], cells: list[list[dict]]) -> dict:
    rows = [[lab, *(c["word"] + (f" · {c['note']}" if c["note"] else "") for c in line)]
            for lab, line in zip(labels, cells)]
    return {"kind": "heatmap", "columns": columns, "rows": rows, "series": [], "cells": cells}


def _all_pass(boxes: list[Box]) -> str | None:
    """The all-clear line when some boxes have no standard (so not every box is Pass), else None."""
    k = sum(b.status is None for b in boxes)
    return f"No box is Fail, Over or For Improvement ({k} without a standard)." if k else None


def colour_report(now: list[Box], before: list[Box], month: str, before_month: str | None) -> Answer:
    colours = sorted({b.color for b in now})
    if not colours:
        return not_enough(f"No boxes for {month_words(month)} with these filters.", 0, COLOUR_RULE)
    grid = {}  # colour -> (summed severity, cells, boxes per column)
    for colour in colours:
        mine = [b for b in now if b.color == colour]
        old = [b for b in before if b.color == colour]
        picks = [_worst([b for b in mine if b.layer == layer]) for layer in LAYERS]
        prevs = [_worst([b for b in old if b.layer == layer]) for layer in LAYERS]
        cells = [_cell(p, q, f"{_last(p.model)} {p.orient[0]}" if p else "") for p, q in zip(picks, prevs)]
        grid[colour] = (sum(severity(b) for b in mine), cells, picks)
    worst = {c: max(BADNESS[x["status_code"]] for x in grid[c][1]) for c in colours}
    order = sorted(colours, key=lambda c: (-worst[c], -grid[c][0], c))
    needs = [c for c in order if any(x["status_code"] not in ("PASS", None) for x in grid[c][1])]
    caveats = [] if before_month else ["No previous month, so no arrows"]
    method = {"rule": COLOUR_RULE, "n": len(order), "caveats": caveats}
    if not needs:
        a = all_clear(_all_pass(now) or f"All {len(order)} colours Pass this month.", COLOUR_RULE, len(order))
        k = sum(b.status is None for b in now)
        a.explanation = (f"No colour has a layer at Fail, Over or For Improvement ({k} without a standard)." if k
                         else f"All {len(order)} colours are at Pass on every layer." if len(order) > 1
                         else "The 1 colour is at Pass on every layer.")
        a.method["caveats"] = caveats
        a.evidence = _evidence(["Colour", *COLUMNS], order, [grid[c][1] for c in order])
        return a
    top = order[0]
    at = max(range(len(LAYERS)), key=lambda i: (BADNESS[grid[top][2][i].status] if grid[top][2][i] else -1, -i))
    box = grid[top][2][at]
    k = len(needs)
    text = (f"{k} of {len(order)} colours {'need' if k != 1 else 'needs'} action this month, and {top} {COLUMNS[at]} "
            f"is the place to start. Its worst box is {panels_words(box)}, at "
            f"{status_word(box.status, box.scope, box.layer)}, with {box.out} of {len(box.values)} readings "
            "outside the standard.")
    downs = sum(x["arrow"] == "↓" for c in order for x in grid[c][1])
    if downs and before_month:
        text += (f" {downs} colour layer{'s' if downs != 1 else ''} slipped to a worse status "
                 f"since {month_words(before_month)}.")
    return Answer(
        status="answer",
        headline=f"{k} of {len(order)} colours {'need' if k != 1 else 'needs'} action; "
                 f"start with {top} ({COLUMNS[at]})",
        status_code=box.status,
        proof=f"{top} {COLUMNS[at]}: {status_word(box.status, box.scope, box.layer)} on {box.label}",
        explanation=text,
        confidence="solid",
        evidence=_evidence(["Colour", *COLUMNS], order, [grid[c][1] for c in order]),
        followups=[{"label": "Model report", "topic": "model_report", "target": box.model},
                   {"label": "Why is it failing?", "topic": "why_failing", "target": box.key}],
        method=method,
    )


def model_report(model: str, now: list[Box], before: list[Box]) -> Answer:
    mine = [b for b in now if b.model == model]
    last = _last(model)
    if not mine:
        return not_enough(f"No boxes for {model} this month.", 0, MODEL_RULE)
    old = [b for b in before if b.model == model]
    layers = [layer for layer in LAYERS if any(b.layer == layer for b in mine)]
    cells = []
    for layer in layers:
        line = []
        for o in ("Horizontal", "Vertical"):
            pick = _worst([b for b in mine if b.layer == layer and b.orient == o])
            prev = _worst([b for b in old if b.layer == layer and b.orient == o])
            line.append(_cell(pick, prev, pick.color if pick else ""))
        cells.append(line)
    evidence = _evidence(["Layer", "H", "V"], [LAYER_NAME[layer] for layer in layers], cells)
    method = {"rule": MODEL_RULE, "n": len(mine), "caveats": [] if old else ["No previous month, so no arrows"]}
    bad = lambda b: b.status in ("FAIL", "OVER", "WARNING")  # noqa: E731
    if not any(bad(b) for b in mine):
        a = all_clear(_all_pass(mine) or f"{last}: all {len(mine)} boxes Pass this month.", MODEL_RULE, len(mine))
        k, m = sum(b.status is None for b in mine), model_word(model)
        a.explanation = (f"No {m} layer is at Fail, Over or For Improvement ({k} without a standard)." if k
                         else f"All {len(mine)} {m} boxes are at Pass." if len(mine) > 1 else f"The 1 {m} box is at Pass.")
        a.evidence = evidence
        a.method["caveats"] = method["caveats"]
        return a
    worst = max(layers, key=lambda layer: (sum(severity(b) for b in mine if b.layer == layer),
                                           sum(bad(b) for b in mine if b.layer == layer)))
    in_layer = [b for b in mine if b.layer == worst]
    top = _worst(in_layer)
    n_bad = sum(bad(b) for b in in_layer)
    text = (f"On the {model_word(model)}, {LAYER_NAME[worst]} is the worst layer this month, with {n_bad} of {len(in_layer)} "
            f"boxes not at Pass. The worst box is {top.color} on {top.orient.lower()} panels, at "
            f"{status_word(top.status, top.scope, top.layer)}, with {top.out} of {len(top.values)} readings "
            "outside the standard.")
    return Answer(
        status="answer",
        headline=f"{last}: {LAYER_NAME[worst]} is the worst layer "
                 f"({sum(bad(b) for b in in_layer)} of {len(in_layer)} boxes not Pass)",
        status_code=top.status,
        proof=f"{top.label}: {status_word(top.status, top.scope, top.layer)}",
        explanation=text,
        confidence="solid",
        evidence=evidence,
        followups=[{"label": "Why is it failing?", "topic": "why_failing", "target": top.key}],
        method=method,
    )


WELL_RULE = "Boxes that moved to a better status, or shifted for real away from the nearer limit, or have Cpk 1.33 or more"
WEEK_RULE = "A week is flagged when its out readings beat the month's own out rate (exact binomial, p under 0.01, 3 or more out)"
DOMAIN_WORD = {"film": "Film", "wavescan": "Wave Scan"}


def _strength(s: Shift) -> float:
    sd_n, sd_b = s.box.sd, s.before.sd
    if sd_n is None or sd_b is None:
        return 0.0
    pooled = sqrt((sd_n**2 + sd_b**2) / 2)
    return abs(s.delta) / pooled if pooled >= 1e-9 else 0.0


def went_well(now: list[Box], before: list[Box], before_month: str | None) -> Answer:
    words = month_words(before_month) if before_month else "previous month"
    ups = sorted((s for s in shifts(now, before)
                  if s.move == "better" or (s.real and s.move != "worse" and (s.box.lsl, s.box.usl) != (None, None)
                                            and not toward_limit(s))),
                 key=lambda s: (not s.real, -_strength(s), s.box.label))
    done = {s.box.key for s in ups}
    capable = []
    for b in now:
        c = cpk(b.values, b.lsl, b.usl) if len(b.values) >= MIN_BOX_N and (b.sd or 0) >= 1e-9 else None
        if c is not None and c >= 1.33 and b.key not in done:
            capable.append((b, c))
    rows = [[s.box.label, f"{s.delta:+.1f}", "Real shift" if s.real else "Better status",
             status_word(s.box.status, s.box.scope, s.box.layer)] for s in ups]
    rows += [[b.label, None, f"Capable (Cpk {c:.2f})", status_word(b.status, b.scope, b.layer)]
             for b, c in sorted(capable, key=lambda x: (-x[1], x[0].label))]
    evidence = {"kind": "bar", "columns": ["Box", "Change", "Verdict", "Now"], "rows": rows, "series": []}
    if not ups:
        if not before:
            return not_enough(f"No {words} data to compare.", 0, WELL_RULE)
        a = all_clear(f"Nothing improved for real since {words}.", WELL_RULE, len(now))
        who = (f"None of the {len(now)} boxes measured this month improved" if len(now) > 1
               else "The 1 box measured this month didn't improve")
        a.explanation = f"{who} by more than day-to-day noise since {words}."
        a.evidence = evidence if rows else {}
        return a
    top = ups[0].box
    now_word = status_word(top.status, top.scope, top.layer)
    if ups[0].real:
        gap = gap_words(ups[0].delta, top.unit)
        text = (f"{box_words(top)}, improved since {words}. {f'It moved {gap}' if gap else 'Its readings shifted'}, "
                f"{difference_sentence(ups[0])}, and it's now at {now_word}.")
    else:
        text = (f"{box_words(top)}, moved to a better status since {words}, from "
                f"{status_word(ups[0].before.status, ups[0].before.scope, ups[0].before.layer)} to {now_word}. "
                "The readings themselves moved within day-to-day noise, so watch that it holds next month.")
    more = []
    if len(ups) > 1:
        more.append(f"{len(ups) - 1} other box{'' if len(ups) == 2 else 'es'} also improved")
    if capable:
        more.append(f"{len(capable)} more box{' holds its' if len(capable) == 1 else 'es hold their'} "
                    "limits comfortably")
    if more:
        text += " " + " and ".join(more) + "."
    if ups[0].real:
        headline = (f"{top.label} improved for real ({ups[0].delta:+.1f}{' ' + top.unit if top.unit else ''}); "
                    f"now {status_word(top.status, top.scope, top.layer)}")
    else:
        headline = (f"{top.label} moved to a better status ({status_word(ups[0].before.status, ups[0].before.scope, ups[0].before.layer)}"
                    f" → {status_word(top.status, top.scope, top.layer)})")
    return Answer(
        status="answer",
        headline=headline,
        status_code=top.status,
        proof=f"{len(ups)} box{'' if len(ups) == 1 else 'es'} improved since {words}",
        explanation=text,
        confidence="solid",
        evidence=evidence,
        followups=[{"label": "Is it trending?", "topic": "trend", "target": top.key}],
        method={"rule": WELL_RULE, "n": len(now), "caveats": []},
    )


def weekly(readings: list[Reading]) -> Answer:
    outs = [r for r in readings if r.out is not None]
    if not outs:
        return not_enough("No readings for this month and filter.", 0, WEEK_RULE)
    by_domain: dict[str, list[Reading]] = defaultdict(list)
    for r in outs:
        by_domain[r.domain].append(r)
    many = len(by_domain) > 1
    rows = []
    flagged: set[tuple[str, int]] = set()
    best: tuple[int, int, str, int] | None = None  # (out_w, week, domain, out_total)
    for domain, rs in by_domain.items():
        total = sum(r.out for r in rs)
        per: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for r in rs:
            w = per[week_of_reading(r.date)]
            w[0] += 1
            w[1] += bool(r.out)
        for week, (n_w, out_w) in per.items():
            if (week and out_w >= MIN_POINT_OUT and total < len(rs)
                    and binomial_sf(out_w, n_w, total / len(rs)) < POINT_P):
                flagged.add((domain, week))
                if best is None or (out_w, -week) > (best[0], -best[1]):
                    best = (out_w, week, domain, total)
        rows += [(week, domain, n_w, out_w) for week, (n_w, out_w) in per.items()]
    rows = [[(f"Week {w}" if w else "Day not recorded") + (f" · {DOMAIN_WORD[d]}" if many else ""),
             n_w, out_w, "flagged" if (d, w) in flagged else ""]
            for w, d, n_w, out_w in sorted(rows, key=lambda x: (x[0] == 0, x[0], x[1]))]
    evidence = {"kind": "weekly_strip", "columns": ["Week", "Readings", "Out", "Flag"], "rows": rows, "series": []}
    method = {"rule": WEEK_RULE, "n": len(outs), "caveats": []}
    if not any(r.out for r in outs):
        a = all_clear("No out readings this month.", WEEK_RULE, len(outs))
        a.explanation = (f"None of the {len(outs)} readings this month was out of limits in any week, "
                         "so nothing needs action." if len(outs) > 1 else "The 1 reading this month was within limits.")
        a.evidence = evidence
        return a
    if best is None:
        n_out = sum(bool(r.out) for r in outs)
        return Answer(status="answer", headline="Out readings are spread across the weeks", confidence="solid",
                      explanation=(f"Out readings are spread across the weeks: {n_out} of {len(outs)} readings were "
                                   "out, with no week standing out. That points to a steady cause through the "
                                   "month, not a one-off event."),
                      evidence=evidence, method=method)
    out_w, week, domain, total = best
    who = f"{DOMAIN_WORD[domain]} " if len({r.domain for r in outs if r.out}) > 1 else ""
    text = (f"{out_w} of {total} {who}out readings this month came in week {week}. That's far more than a normal "
            "week's share, so look for what changed on the line that week.")
    if len(flagged) > 1:
        m = len(flagged) - 1
        text += f" {m} other week{'s also stand' if m > 1 else ' also stands'} out."
    return Answer(status="answer", headline=f"{out_w} of {total} {who}out readings were in week {week}",
                  confidence="solid", explanation=text, evidence=evidence, method=method)


RECUR_RULE = "A box is recurring when it was not Pass in at least 3 of the last 4 months that have readings"
NOT_PASS = ("FAIL", "OVER", "WARNING")


def recurring(by_month: dict[str, list[Box]], used: str | None = None) -> Answer:
    months = sorted(m for m, boxes in by_month.items() if boxes)[-4:]
    if len(months) < 3:
        return not_enough("Needs at least 3 months of data.", len(months), RECUR_RULE)
    seen: dict[str, dict[str, Box]] = defaultdict(dict)
    for m in months:
        for b in by_month[m]:
            seen[b.key][m] = b
    hits = {k: sum(b.status in NOT_PASS for b in per.values()) for k, per in seen.items()}
    keys = sorted((k for k, n in hits.items() if n >= 3),
                  key=lambda k: (-hits[k], next(iter(seen[k].values())).label))
    if not keys:
        a = all_clear("No box keeps coming back.", RECUR_RULE, len(seen))
        some = "all" if len(months) == 3 else "3 or more"
        a.explanation = (f"No box missed Pass in {some} of the last {len(months)} months "
                         f"({plural(len(seen), 'box')} checked).")
        return a
    labels = [next(iter(seen[k].values())).label for k in keys]
    cells = [[_cell(seen[k].get(m), None, "") for m in months] for k in keys]
    top = seen[keys[0]].get(months[-1]) or next(iter(seen[keys[0]].values()))
    k = len(keys)
    text = (f"{box_words(top)}, is not a one-off: it was not at Pass in {hits[keys[0]]} of the last {len(months)} "
            "months. ")
    if k > 1:
        text += (f"{plural(k - 1, 'more box')} {'keeps' if k == 2 else 'keep'} coming back the same way, so these "
                 "need a lasting fix, not a one-month correction.")
    else:
        text += "It needs a lasting fix, not a one-month correction."
    follow = [{"label": "Last 6 months", "topic": "history", "target": keys[0]}]
    if keys[0] in {b.key for b in by_month.get(used or months[-1], [])}:  # why_failing reads the month used
        follow.append({"label": "Why is it failing?", "topic": "why_failing", "target": top.key})
    return Answer(
        status="answer",
        headline=f"{k} {'box was' if k == 1 else 'boxes were'} not Pass in at least 3 of the last {len(months)} months",
        status_code=top.status,
        proof=f"{labels[0]} was not Pass in {hits[keys[0]]} of {len(months)} months",
        explanation=text,
        confidence="solid",
        evidence={"kind": "grid", "columns": ["Box", *(month_words(m) for m in months)],
                  "rows": [[lab, *(c["word"] for c in line)] for lab, line in zip(labels, cells)],
                  "series": [], "cells": cells},
        followups=follow,
        method={"rule": RECUR_RULE, "n": len(seen), "caveats": []},
    )
