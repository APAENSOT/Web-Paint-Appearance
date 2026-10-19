"""AR04 topic `colours`: which colours need to improve, ranked by severity then Cpk."""

from __future__ import annotations

from app.domain.assistant.answer import (
    MIN_BOX_N, Answer, Box, all_clear, capability_word, not_enough, severity,
)
from app.domain.assistant.plain_words import box_words, capability_sentence
from app.domain.report_stats import cpk
from app.domain.report_summary import LAYER_WORD, status_word

RULE = "Cpk ranking; boxes need a limit, 10 readings and some spread"


def _side(box: Box) -> str | None:
    """The limit side that matters: the nearer one to the mean (only one if one-sided)."""
    mean, lo, hi = box.mean, box.lsl, box.usl
    if mean is None or (lo is None and hi is None):
        return None
    return "lo" if lo is not None and (hi is None or abs(mean - lo) <= abs(hi - mean)) else "hi"


def direction(box: Box) -> str | None:
    mean, side = box.mean, _side(box)
    if side is None:
        return None
    if box.domain == "wavescan":
        return "CF below minimum → check the Wave Scan bands"
    layer = LAYER_WORD[box.layer] if box.layer else "film"
    d = box.lsl - mean if side == "lo" else mean - box.usl
    lim, bad, fix = ("Lo", "under", "raise") if side == "lo" else ("Hi", "over", "lower")
    if d > 0:
        return f"Mean {d:.1f} µm {bad} {lim} → {fix} {layer} build"
    inside = "above Lo" if side == "lo" else "below Hi"
    return f"Mean {-d:.1f} µm {inside}; the spread is the problem → reduce {layer} build variation"


def mean_vs_limit(box: Box) -> tuple[str, bool] | None:
    """('the film runs 1.6 µm below the low limit on average', outside?) for the nearer limit."""
    mean, side = box.mean, _side(box)
    if side is None:
        return None
    lim = box.lsl if side == "lo" else box.usl
    d = lim - mean if side == "lo" else mean - lim  # > 0: the average itself is outside
    what, u = ("the CF", " CF points") if box.domain == "wavescan" else ("the film", f" {box.unit}" if box.unit else "")
    name = "minimum" if box.domain == "wavescan" else "low limit" if side == "lo" else "high limit"
    if d > 0:
        return f"{what} runs {d:.1f}{u} {'below' if side == 'lo' else 'above'} the {name} on average", True
    return f"{what} averages {-d:.1f}{u} {'above' if side == 'lo' else 'below'} the {name}", False


def position_clause(box: Box) -> str:
    """' and <mean outside>, so the average itself needs to move' / ' even though <mean inside>, so the spread
    is the problem' / '' without a limit."""
    gap = mean_vs_limit(box)
    if gap is None:
        return ""
    if gap[1]:
        return f" and {gap[0]}, so the average itself needs to move"
    return f" even though {gap[0]}, so the spread is the problem"


OUT_PLAIN = {"under Lo": "under the low limit", "over Hi": "over the high limit", "below minimum": "below the minimum"}


def _out_word(box: Box) -> str:
    if box.domain == "wavescan":
        return "below minimum"
    low = sum(box.lsl is not None and v < box.lsl for v in box.values)
    if box.out:
        return "under Lo" if low >= box.out - low else "over Hi"
    return "under Lo" if _side(box) == "lo" else "over Hi"


def _skipped(boxes: list[Box]) -> tuple[list[Box], list[str]]:
    keep, why = [], {"no limit": 0, f"fewer than {MIN_BOX_N} readings": 0, "no spread in readings": 0}
    for b in boxes:
        if b.lsl is None and b.usl is None:
            why["no limit"] += 1
        elif len(b.values) < MIN_BOX_N:
            why[f"fewer than {MIN_BOX_N} readings"] += 1
        elif (b.sd or 0) < 1e-9:
            why["no spread in readings"] += 1
        else:
            keep.append(b)
    notes = [f"{n} box{'es' if n != 1 else ''} skipped: {r}" for r, n in why.items() if n]
    return keep, notes


def colours(boxes: list[Box]) -> Answer:
    eligible, notes = _skipped(boxes)
    if not eligible:
        reason = "; ".join(notes) or "No boxes to rank"
        a = not_enough(reason, len(boxes), RULE)
        a.method["caveats"] = notes
        return a
    ranked = sorted(eligible, key=lambda b: (-severity(b), cpk(b.values, b.lsl, b.usl)))
    caps = {b.key: cpk(b.values, b.lsl, b.usl) for b in ranked}
    if all(caps[b.key] >= 1.33 and b.status == "PASS" for b in ranked):
        a = all_clear("Every colour is capable this month.", RULE, len(ranked))
        a.explanation = (f"All {len(ranked)} colour boxes checked this month sit comfortably inside their limits"
                         if len(ranked) > 1 else "The 1 colour box checked this month sits comfortably inside its "
                         "limits") + ", so nothing needs action."
        a.method["caveats"] = notes
        return a
    top = ranked[0]
    c = caps[top.key]
    text = (f"{box_words(top)}, is the weakest box this month: {capability_sentence(c)}. {top.out} of "
            f"{len(top.values)} readings were {OUT_PLAIN[_out_word(top)]}{position_clause(top)}.")
    if len(ranked) > 1:
        nxt = ranked[1]
        text += (f" Next weakest is {nxt.color} {LAYER_WORD[nxt.layer] if nxt.layer else 'CF'}, with {nxt.out} of "
                 f"{len(nxt.values)} readings {OUT_PLAIN[_out_word(nxt)]}.")
    return Answer(
        status="answer",
        headline=f"{top.label} is the weakest",
        status_code=top.status,
        proof=f"capability {capability_word(c)} (Cpk {c:.2f}), {top.out} of {len(top.values)} {_out_word(top)}",
        explanation=text,
        next_step=direction(top),
        confidence="solid",
        evidence={
            "kind": "bar",
            "columns": ["Box", "Status", "Capability", "Out", "n"],
            "rows": [
                [b.label, status_word(b.status, b.scope), f"{capability_word(caps[b.key])} ({caps[b.key]:.2f})",
                 b.out, len(b.values)]
                for b in ranked
            ],
            "series": [],
        },
        followups=[
            {"label": "Is it trending?", "topic": "trend", "target": top.key},
            {"label": "Which points (all colours)?", "topic": "points", "target": None},
        ],
        method={"rule": RULE, "n": len(ranked), "caveats": notes},
    )
