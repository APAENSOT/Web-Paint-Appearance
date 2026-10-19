"""AR05 data questions: is the month complete, which standard applies, which boxes have none, how many paired cars.

Pure. Limits and statuses are copied from the boxes (the overviews' own); nothing is graded here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.domain.assistant.answer import MIN_BOX_N, Answer, Box, all_clear, not_enough
from app.domain.assistant.plain_words import box_words, plural
from app.domain.assistant.readings import Reading, week_of_reading
from app.domain.report_summary import LAYER_WORD, month_words, status_word

DOMAIN_WORD = {"film": "Film", "wavescan": "Wave Scan"}
COMPLETE_RULE = "A week is missing when a domain has readings this month but none in that week; a box needs 10 readings"
STANDARD_RULE = "The limits the boxes of the colour carry, copied from the dashboards; nothing is re-graded"
NONE_RULE = "A box with no status has no rule to grade it against"
PAIRING_RULE = "Cars measured on both instruments, matched by the car number"
PAIRED_ENOUGH = 100
SCOPE_WORD = {"COLOR": "colour rule", "PLANT": "plant rule"}
BADNESS = {"FAIL": 3, "OVER": 2, "WARNING": 1, "PASS": 0, None: -1}


def _list(weeks: list[int]) -> str:
    nums = [str(w) for w in weeks]
    return nums[0] if len(nums) == 1 else ", ".join(nums[:-1]) + " and " + nums[-1]


def data_complete(readings: list[Reading], boxes: list[Box], last_upload: date | None,
                  weeks_in_month: list[int]) -> Answer:
    graded = [r for r in readings if r.out is not None]
    if not graded:
        return not_enough("No readings for this month and filter.", 0, COMPLETE_RULE)
    by_domain: dict[str, list[Reading]] = defaultdict(list)
    for r in graded:
        by_domain[r.domain].append(r)
    many = len(by_domain) > 1
    problems, rows, said = [], [], []
    for domain in ("film", "wavescan"):
        if domain not in by_domain:
            continue
        per: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for r in by_domain[domain]:
            w = per[week_of_reading(r.date)]
            w[0] += 1
            w[1] += bool(r.out)
        missing = [w for w in weeks_in_month if per[w][0] == 0]
        if missing:
            problems.append(f"{DOMAIN_WORD[domain]} week{'' if len(missing) == 1 else 's'} {_list(missing)} missing")
            one = len(missing) == 1
            said.append(f"{DOMAIN_WORD[domain]} week{'' if one else 's'} {_list(missing)} {'has' if one else 'have'} "
                        f"no readings, so this month's {DOMAIN_WORD[domain]} results may miss a shift.")
        rows += [[f"Week {w}" + (f" · {DOMAIN_WORD[domain]}" if many else ""), per[w][0], per[w][1],
                  "missing" if w in missing else ""] for w in weeks_in_month]
    small = sorted((b for b in boxes if len(b.values) < MIN_BOX_N), key=lambda b: (len(b.values), b.label))
    if small:
        k = len(small)
        problems.append(f"{k} box{'es have' if k != 1 else ' has'} under {MIN_BOX_N} readings")
        said.append(f"{k} box{'es have' if k != 1 else ' has'} under {MIN_BOX_N} readings, so "
                    f"{'their' if k != 1 else 'its'} status rests on thin data; the thinnest is "
                    f"{box_words(small[0])}, with {plural(len(small[0].values), 'reading')}.")
    evidence = {"kind": "weekly_strip", "columns": ["Week", "Readings", "Out", "Flag"], "rows": rows, "series": []}
    upload = f"Last upload {last_upload.isoformat()}" if last_upload else ""
    if not problems:
        a = all_clear("This month's data looks complete.", COMPLETE_RULE, len(graded))
        a.proof, a.evidence = upload, evidence
        a.explanation = (f"Every week of the month has readings and every box has at least {MIN_BOX_N}, so the "
                         "data is complete.")
        return a
    if len(said) < 3:
        said.append(f"The last upload was on {last_upload.day} {last_upload:%B %Y}." if last_upload else
                    f"{plural(len(graded), 'reading')} came in this month in total.")
    proof = "; ".join(p for p in (
        f"Fewest readings: {small[0].label} ({len(small[0].values)})" if small else "", upload) if p)
    return Answer(status="answer", headline="; ".join(problems), proof=proof, confidence="solid",
                  explanation=" ".join(said),
                  evidence=evidence, method={"rule": COMPLETE_RULE, "n": len(graded), "caveats": []})


def _num(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _scope(b: Box) -> str:
    return SCOPE_WORD.get(b.scope, "rule")


def _limits(b: Box, target: float | None) -> str:
    parts = [f"Lo {_num(b.lsl)} {b.unit}".strip() if b.lsl is not None else "no Lo",
             f"Hi {_num(b.usl)} {b.unit}".strip() if b.usl is not None else "no Hi"]
    if target is not None:
        parts.append(f"Target {_num(target)} {b.unit}".strip())
    return " · ".join([*parts, _scope(b)])


def standard_for(colour: str, boxes: list[Box], targets: dict[str, float | None], month: str) -> Answer:
    mine = [b for b in boxes if b.color == colour]
    if not mine:
        return not_enough(f"No readings for {colour} in {month_words(month)} with these filters.", 0, STANDARD_RULE)
    order = [*LAYER_WORD, None]
    ranked = sorted(mine, key=lambda b: (order.index(b.layer), b.orient, b.model))
    seen: dict[str, list[str]] = {}
    for b in ranked:
        label = f"{LAYER_WORD[b.layer]} {b.orient[0]}" if b.layer else f"CF {b.orient[0]}"
        text = f"Minimum {_num(b.lsl)}" if not b.layer and b.lsl is not None else (
            "No standard" if b.lsl is None and b.usl is None else _limits(b, targets.get(b.key)))
        if text not in seen.setdefault(label, []):
            seen[label].append(text)
    card = [{"label": k, "value": " / ".join(v)} for k, v in seen.items()]
    rows = [[LAYER_WORD[b.layer] if b.layer else "CF", b.orient, b.model, _num(b.lsl) if b.lsl is not None else "—",
             _num(b.usl) if b.usl is not None and b.layer else "—",
             _num(t) if (t := targets.get(b.key)) is not None else "—",
             _scope(b) if b.layer else "rule"] for b in ranked]
    film = [b for b in ranked if b.layer]
    parts = []
    if film:
        bad = [b for b in film if BADNESS[b.status] > 0]
        rep = max(bad, key=lambda b: (BADNESS[b.status], -order.index(b.layer))) if bad else film[0]
        name = LAYER_WORD[rep.layer]
        if rep.lsl is None and rep.usl is None:
            part = f"{name} has no standard"
        else:
            lo = f"Lo {_num(rep.lsl)} µm" if rep.lsl is not None else "no Lo"
            part = f"{name} {lo} ({_scope(rep)}), " + (f"Hi {_num(rep.usl)} µm" if rep.usl is not None else "no Hi")
        if any((b.lsl, b.usl, b.scope) != (rep.lsl, rep.usl, rep.scope) for b in film if b.layer == rep.layer):
            part += f" ({rep.orient} shown; other orientations or models differ)"
        parts.append(part)
    cf: dict[str, set[str]] = defaultdict(set)
    for b in ranked:
        if not b.layer and b.lsl is not None:
            cf[b.orient[0]].add(_num(b.lsl))
    if cf:
        values = {" / ".join(sorted(v)) for v in cf.values()}
        parts.append("CF minimum " + (next(iter(values)) if len(values) == 1 else ", ".join(
            f"{o} {' / '.join(sorted(cf[o]))}" for o in sorted(cf, reverse=True))))
    top = max((b.status for b in mine), key=lambda s: BADNESS[s])
    said = []
    if film:
        if rep.lsl is None and rep.usl is None:
            said.append(f"For {colour}, {name} has no standard, so its readings aren't graded.")
        else:
            rng = (f"between {_num(rep.lsl)} and {_num(rep.usl)} µm" if rep.lsl is not None and rep.usl is not None
                   else f"at or above {_num(rep.lsl)} µm" if rep.lsl is not None
                   else f"at or below {_num(rep.usl)} µm")
            bad = (f", and it's at {status_word(rep.status, rep.scope, rep.layer)} this month"
                   if BADNESS[rep.status] > 0 else "")
            said.append(f"For {colour}, {name} must stay {rng} under the {_scope(rep)}{bad}.")
        if parts[0].endswith("differ)"):
            said.append(f"That's the {rep.orient.lower()} panels; other orientations or models carry different limits.")
    if cf:
        orient = {"V": "vertical", "H": "horizontal"}
        said.append("Wave Scan CF must stay at or above " + (next(iter(values)) if len(values) == 1 else " and ".join(
            f"{' / '.join(sorted(cf[o]))} on {orient.get(o, o)} panels" for o in sorted(cf, reverse=True))) + ".")
    if len(said) < 2:
        said.append(f"That's what the {plural(len(mine), 'box')} for {colour} this month "
                    f"{'is' if len(mine) == 1 else 'are'} graded against.")
    return Answer(
        status="answer", headline=f"{colour}: " + ("; ".join(parts) if parts else "no standard on these boxes"),
        status_code=top, proof=f"{len(mine)} boxes carry these limits", confidence="solid", explanation=" ".join(said),
        evidence={"kind": "limit_card", "columns": ["Layer", "Orientation", "Model", "Lo", "Hi", "Target", "Rule"],
                  "rows": rows, "series": [], "card": card},
        method={"rule": STANDARD_RULE, "n": len(mine), "caveats": []})


def no_standard(boxes: list[Box]) -> Answer:
    if not boxes:
        return not_enough("No boxes for this month and filter.", 0, NONE_RULE)
    bare = sorted((b for b in boxes if b.status is None), key=lambda b: b.label)
    if not bare:
        a = all_clear("Every box has a standard this month.", NONE_RULE, len(boxes))
        a.explanation = (f"All {plural(len(boxes), 'box')} this month have a standard to grade against."
                         if len(boxes) > 1 else "The 1 box this month has a standard to grade against.")
        return a
    k = len(bare)
    text = (f"{plural(k, 'box')} {'has' if k == 1 else 'have'} no standard to grade against this month, starting "
            f"with {box_words(bare[0])}. {'It shows' if k == 1 else 'They show'} no Pass or Fail, so a problem there "
            "won't stand out until a standard is applied.")
    return Answer(
        status="answer", headline=f"{k} box{'es' if k != 1 else ''} not graded — {bare[0].label} has no rule",
        confidence="solid", explanation=text,
        evidence={"kind": "table", "columns": ["Box", "Standard"],
                  "rows": [[b.label, status_word(None, b.scope, b.layer)] for b in bare], "series": []},
        method={"rule": NONE_RULE, "n": len(boxes), "caveats": []})


def pairing(counts: dict) -> Answer:
    n = int(counts["paired_cars"])
    enough = n >= PAIRED_ENOUGH
    text = (f"{plural(n, 'car')} {'has' if n == 1 else 'have'} been measured on both Film and Wave Scan, across all "
            "months and the whole plant. " + ("That's enough for the layer checks to be trusted." if enough else
                                              f"About {PAIRED_ENOUGH} are needed, so for now treat the layer checks "
                                              "as a lead, not proof."))
    return Answer(
        status="answer",
        headline=f"{n} paired cars; layer checks " + ("can be trusted" if enough else "stay exploratory until about 100"),
        confidence="solid" if enough else "exploratory", explanation=text,
        proof="All months, whole plant; the month, model and colour filters don't apply.",
        evidence={"kind": "stat", "columns": ["Measure", "Value"],
                  "rows": [["Paired cars", n], ["Needed for solid layer checks", "about 100"]], "series": [],
                  "card": [{"label": "Paired cars", "value": str(n)},
                           {"label": "Needed for solid layer checks", "value": "about 100"}]},
        method={"rule": PAIRING_RULE, "n": n,
                "caveats": [] if enough else ["Layer checks stay exploratory until about 100 paired cars."]})
