"""AR04 topic `changes`: what moved since last month, real shift vs noise (Mann-Whitney)."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median

from app.domain.assistant.answer import MIN_BOX_N, SHIFT_P, SHIFT_SIGMA, Answer, Box, all_clear, not_enough
from app.domain.assistant.plain_words import box_words, gap_words, plural
from app.domain.report_stats import mann_whitney, mean_sd
from app.domain.report_summary import month_words, status_word

RANK = {"FAIL": 0, "OVER": 1, "WARNING": 2, "PASS": 3, None: 4}
RULE = "Mann-Whitney on each box vs last month; real = p under 0.05 and a move of 0.5 sd or more"


@dataclass(frozen=True)
class Shift:
    box: Box
    before: Box
    p: float | None
    delta: float
    real: bool
    move: str  # "worse" | "better" | "same"


def _shift(now: Box, before: Box) -> Shift:
    delta = median(now.values) - median(before.values)
    p = mann_whitney(list(now.values), list(before.values))
    sd_n, sd_b = mean_sd(now.values)[1], mean_sd(before.values)[1]
    real = False
    if p is not None and p < SHIFT_P and sd_n is not None and sd_b is not None:
        pooled = sqrt((sd_n**2 + sd_b**2) / 2)
        real = pooled >= 1e-9 and abs(delta) >= SHIFT_SIGMA * pooled
    a, b = RANK[now.status], RANK[before.status]
    # No standard on either side is not a quality move.
    move = "same" if None in (now.status, before.status) else "worse" if a < b else "better" if a > b else "same"
    return Shift(now, before, p, delta, real, move)


def toward_limit(s: Shift) -> bool:
    lims = [x for x in (s.box.lsl, s.box.usl) if x is not None]
    if not lims:
        return False
    m = median(s.before.values)
    near = min(lims, key=lambda x: abs(m - x))
    return s.delta > 0 if near == s.box.usl else s.delta < 0


def _group(s: Shift) -> int:
    return 0 if s.move == "worse" else 1 if s.move == "better" else 2 if s.real else 3


def shifts(now: list[Box], before: list[Box]) -> list[Shift]:
    prev = {b.key: b for b in before if b.values}
    out = [_shift(b, prev[b.key]) for b in now if b.values and b.key in prev]
    return sorted(out, key=lambda s: (_group(s), -abs(s.delta)))


def _num(s: Shift) -> str:
    return f"{s.delta:+.1f}" + (f" {s.box.unit}" if s.box.unit else "")


def _verdict(s: Shift) -> str:
    if s.real:
        return "Real shift"
    if s.p is None:
        return "No spread" if min(len(s.box.values), len(s.before.values)) >= MIN_BOX_N else "Too few readings"
    return "Noise"


def changes(now: list[Box], before: list[Box], before_month: str | None, now_month: str | None = None) -> Answer:
    """now_month: set by compare_months so the paragraph names both months."""
    words = month_words(before_month) if before_month else "previous month"
    since = "" if now_month else f" since {words}"

    def say(text: str) -> str:
        return f"Comparing {month_words(now_month)} with {words}, {text[0].lower()}{text[1:]}" if now_month else text
    if not before:
        return not_enough(f"No {words} data to compare.", 0, RULE)
    ss = shifts(now, before)
    if not ss:
        dates = [d for b in now for d in b.dates]
        cur = month_words(f"{max(dates):%Y-%m}") if dates else "this month"
        return not_enough(f"No box was measured in both {words} and {cur}.", 0, RULE)
    worse = [s for s in ss if s.move == "worse" or (s.move == "same" and s.real and toward_limit(s))]
    better = [s for s in ss if s.move == "better"]
    real = [s for s in ss if s.real]
    if not worse and not better and not real:
        a = all_clear(f"Nothing changed for real since {words}.", RULE, len(ss))
        a.explanation = say(f"{'All' if len(ss) > 1 else 'The'} {plural(len(ss), 'box')} measured in both months "
                            f"stayed within day-to-day noise{since}, so nothing needs action.")
        return a
    if worse:
        n, top = len(worse), worse[0]
        k = sum(s.real for s in worse)
        if n == 1:
            lead = (f"1 box got worse{since}; the move is "
                    + ("a real difference, not day-to-day noise." if k else "within day-to-day noise."))
        else:
            lead = f"{n} boxes got worse{since}; {k} of the moves are a real difference, not day-to-day noise."
        headline = (f"{n} box{'' if n == 1 else 'es'} got worse "
                    f"({k} real shift{'' if k == 1 else 's'})")
    elif better:
        k, top = len(better), better[0]
        lead = f"Nothing got worse{since}, and {plural(k, 'box')} recovered to a better status."
        headline = f"Nothing got worse; {k} box recovered since {words}" if k == 1 else (
            f"Nothing got worse; {k} boxes recovered since {words}")
    else:
        k, top = len(real), real[0]
        lead = (f"Nothing got worse{since}, but {plural(k, 'box')} moved by a real difference, not day-to-day "
                "noise, without changing status.")
        headline = f"Nothing got worse; {k} box shifted for real since {words}" if k == 1 else (
            f"Nothing got worse; {k} boxes shifted for real since {words}")
    word = status_word(top.box.status, top.box.scope)
    gap = gap_words(top.delta, top.box.unit)
    text = f"{lead} The biggest is {box_words(top.box)}, now at {word}" + (f" after moving {gap}." if gap else ".")
    if worse and better:
        text += f" {plural(len(better), 'box')} recovered."
    rows = [[s.box.label, status_word(s.before.status, s.before.scope), status_word(s.box.status, s.box.scope),
             _num(s), _verdict(s)] for s in ss]
    keys_now, keys_before = {b.key for b in now}, {b.key for b in before}
    rows += [[b.label, "—", status_word(b.status, b.scope), "—", "New"] for b in now if b.key not in keys_before]
    rows += [[b.label, status_word(b.status, b.scope), "—", "—", "Gone"] for b in before if b.key not in keys_now]
    follow = [{"label": "Is it trending?", "topic": "trend", "target": top.box.key}]
    if top.box.domain == "wavescan":
        follow.append({"label": "Which layer?", "topic": "bands", "target": None})
    return Answer(
        status="answer",
        headline=headline,
        status_code=top.box.status,
        proof=f"biggest: {top.box.label}, {_num(top)}, now {word}",
        explanation=say(text),
        confidence="solid",
        evidence={"kind": "shift", "columns": ["Box", "Before", "Now", "Change", "Verdict"], "rows": rows, "series": [],
                  # one dumbbell per box in both months, aligned with the first len(ss) rows
                  "points": [{"x": round(median(s.before.values), 2), "y": round(median(s.box.values), 2),
                              "label": s.box.label} for s in ss]},
        followups=follow,
        method={"rule": RULE, "n": len(ss), "caveats": []},
    )
