"""AR05 topics `next_month_risk` and `history`: what fails next if nothing changes, and is it a one-off."""

from __future__ import annotations

from app.domain.assistant.answer import (LIMIT_HORIZON_DAYS, MIN_TREND_DATES, RISK_CARS, Answer, Box, MonthPoint,
                                         all_clear, not_enough, severity)
from app.domain.assistant.plain_words import box_words, plural
from app.domain.assistant.report_grids import NOT_PASS
from app.domain.assistant.trend import daily_fit, risk_count
from app.domain.report_summary import month_words, status_word

RISK_RULE = ("Straight line through the daily means projected 30 days past the last measuring day when its 95 percent "
             "range excludes 0, else the current mean; chance of falling outside the limits from the box spread")
HISTORY_RULE = "The box's monthly mean and status for up to 6 months, as the dashboard shows them"


def next_month_risk(boxes: list[Box]) -> Answer:
    rows, slope = [], {}
    for b in boxes:
        days, xs, _, fit = daily_fit(b)
        if (len(days) < MIN_TREND_DATES or fit is None or (b.lsl is None and b.usl is None)
                or b.sd is None or b.sd < 1e-9):
            continue
        lo, hi = fit.ci95()
        real = lo > 0 or hi < 0
        mu = fit.intercept + fit.slope * (xs[-1] + LIMIT_HORIZON_DAYS) if real else b.mean
        rows.append((risk_count(mu, b.sd, b.lsl, b.usl), b, "trend" if real else "level"))
        slope[b.key] = fit.slope
    if not rows:
        return not_enough(f"Not enough measuring days to project any box ({MIN_TREND_DATES} needed).", 0, RISK_RULE)
    rows.sort(key=lambda r: (-r[0], -severity(r[1]), r[1].label))
    evidence = {"kind": "bar", "columns": ["Box", f"Expected out of {RISK_CARS}", "Basis", "Now"],
                "rows": [[b.label, e, basis, status_word(b.status, b.scope, b.layer)] for e, b, basis in rows[:10]],
                "series": []}
    if rows[0][0] == 0:
        a = all_clear("No box is heading out of its limits.", RISK_RULE, len(rows))
        a.evidence = evidence
        a.explanation = (f"None of the {plural(len(rows), 'box')} with enough measuring days is heading out of its "
                         "limits next month." if len(rows) > 1 else
                         "The 1 box with enough measuring days is not heading out of its limits next month.")
        return a
    expected, top, basis = rows[0]
    below, above = (top.lsl is not None and top.mean < top.lsl), (top.usl is not None and top.mean > top.usl)
    lead = ("will put the most cars out next month" if below or above or top.status == "FAIL"
            else "is the box most likely to fail next")
    text = (f"If nothing changes, {box_words(top)}, {lead}: about {expected} of the next {RISK_CARS} cars would be "
            "out. ")
    s = slope[top.key]
    if basis != "trend":
        text += "That comes from where its readings sit and how scattered they are now, not from a steady drift."
    elif below or above:
        text += ("It's already outside the limit and still moving away from it."
                 if (s < 0) == below else "It's outside the limit but moving back toward it.")
    else:
        # Inside the limits: the limit the slope points at, if that side has one.
        low = s < 0
        has = top.lsl is not None if low else top.usl is not None
        near = ("minimum" if top.domain == "wavescan" else "low limit") if (low if has else not low) else "high limit"
        text += (f"Its daily average has been moving steadily this month, and that pace carries it toward the {near}."
                 if has else
                 f"It's moving away from the {near}; the risk comes from how scattered its readings are.")
    if len(rows) > 1 and rows[1][0]:
        text += f" Next is {box_words(rows[1][1])}, at about {rows[1][0]} of {RISK_CARS}."
    return Answer(
        status="answer",
        headline=f"If nothing changes, {top.label} is next: about {expected} of the next {RISK_CARS} cars out",
        status_code=top.status,
        proof=f"Projected from the {basis}; {len(rows)} boxes had enough measuring days",
        explanation=text,
        confidence="exploratory",
        evidence=evidence,
        followups=[{"label": "Is it trending?", "topic": "trend", "target": top.key},
                   {"label": "Why is it failing?", "topic": "why_failing", "target": top.key}],
        method={"rule": RISK_RULE, "n": len(rows), "caveats": []},
    )


def history(box: Box, months: list[MonthPoint]) -> Answer:
    """months newest first; a month with no mean has no such box."""
    present = [m for m in months if m.mean is not None]
    if not months or months[0].mean is None:
        when = month_words(months[0].month) if months else "this month"
        return not_enough(f"That box has no readings for {when} with these filters.", 0, HISTORY_RULE)

    def word(m: MonthPoint) -> str:
        return status_word(m.status, box.scope, box.layer)

    k = 1
    while k < len(months) and months[k].mean is not None and months[k].status == months[0].status:
        k += 1
    u = f" {box.unit}" if box.unit else ""
    if k >= 2 and months[0].status in NOT_PASS:
        headline = f"{box.label}: {word(present[0])} {k} months running"
        text = (f"{box_words(box)}, is not a one-off: it has been at {word(present[0])} every month since "
                f"{month_words(months[k - 1].month)}, {k} months running. Its monthly average went from "
                f"{months[k - 1].mean:.1f}{u} to {months[0].mean:.1f}{u} over that time, so it needs a fix rather "
                "than waiting for it to clear.")
    else:
        headline = (f"{box.label}: {' → '.join(word(m) for m in reversed(present))} over {len(present)} "
                    f"month{'' if len(present) == 1 else 's'}")
        text = (f"Over the last {plural(len(present), 'month')} with readings, {box_words(box)}, went "
                f"{', then '.join(word(m) for m in reversed(present))}. It's at {word(present[0])} now, with a "
                f"monthly average of {present[0].mean:.1f}{u}.")
        if len(present) > 1 and present[0].status in NOT_PASS and present[1].status == "PASS":
            text += f" It passed in {month_words(present[1].month)}, so look at what changed since then."
    return Answer(
        status="answer",
        headline=headline,
        status_code=present[0].status,
        proof=f"{len(present)} of {len(months)} months have readings",
        explanation=text,
        confidence="solid",
        evidence={"kind": "trend_monthly",
                  "series": [{"x": m.month, "y": m.mean} for m in reversed(present)],
                  "columns": ["Month", "Mean", "Status"],
                  "rows": [[month_words(m.month), "—" if m.mean is None else round(m.mean, 2),
                            "—" if m.mean is None else word(m)] for m in reversed(months)],
                  "limits": {"lo": box.lsl, "hi": box.usl}},
        followups=[{"label": "Is it trending?", "topic": "trend", "target": box.key}],
        method={"rule": HISTORY_RULE, "n": len(present), "caveats": []},
    )
