"""AR04 topic `trend`: is this box drifting (OLS on daily means), and what happens if it is not fixed."""

from __future__ import annotations

from collections import defaultdict

from app.domain.assistant.answer import (LIMIT_HORIZON_DAYS, MIN_BOX_N, MIN_TREND_DATES, RISK_CARS,
                                         RISK_DAYS_AHEAD, Answer, Box, MonthPoint, not_enough)
from app.domain.assistant.plain_words import box_words, plural
from app.domain.report_stats import ewma_first_out, mean_sd, normal_cdf, ols_fit
from app.domain.report_summary import month_words, status_word

RULE = "Straight line through the daily means (real when its 95 percent range excludes 0) plus an EWMA control chart (lambda 0.2)"
NO_BASELINE = "No usable previous month baseline; control chart uses this month."


def risk_count(mu: float, sd: float, lsl: float | None, usl: float | None) -> int:
    p = (normal_cdf((lsl - mu) / sd) if lsl is not None else 0.0) + (
        1 - normal_cdf((usl - mu) / sd) if usl is not None else 0.0)
    return round(RISK_CARS * p)


def daily_fit(box: Box):
    """(days, xs, ys, fit): daily means with x = calendar days from the first date; fit is None when too few."""
    by_day: dict = defaultdict(list)
    for v, d in zip(box.values, box.dates):
        by_day[d].append(v)
    days = sorted(by_day)
    xs = [(d - days[0]).days for d in days]
    ys = [sum(by_day[d]) / len(by_day[d]) for d in days]
    return days, xs, ys, ols_fit(xs, ys)


def trend(box: Box, before: Box | None, history: list[MonthPoint]) -> Answer:
    days, xs, ys, fit = daily_fit(box)
    if len(days) < MIN_TREND_DATES:
        return not_enough(f"Only {len(days)} measuring {'day' if len(days) == 1 else 'days'} this month; {MIN_TREND_DATES} needed.", len(box.values), RULE)
    lo, hi = fit.ci95()
    real = lo > 0 or hi < 0
    per_day = (f" {box.unit}" if box.unit else "") + "/day"

    u = f" {box.unit}" if box.unit else (" CF points" if box.domain == "wavescan" else "")
    if real:
        down = fit.slope < 0
        headline = f"{box.label}: drifting {'down' if down else 'up'} {abs(fit.slope):.2f}{per_day}"
        limit = box.lsl if down else box.usl
        proof = "no limit reached within 30 days"
        text = (f"The daily average of {box_words(box)}, has been {'falling' if down else 'rising'} about "
                f"{abs(fit.slope):.2f}{u} a day this month.")
        pace = f" At that pace it doesn't reach a limit within the next {LIMIT_HORIZON_DAYS} days."
        if limit is not None:
            raw = (limit - (fit.intercept + fit.slope * xs[-1])) / fit.slope
            name = ("minimum" if down else "maximum") if box.domain == "wavescan" else ("Lo" if down else "Hi")
            said = {"Lo": "low limit", "Hi": "high limit"}.get(name, name)
            if raw <= 0:
                proof = f"already past {name} on the trend line"
                pace = f" At that pace it is already past the {said}."
            elif (d := max(1, round(raw))) <= LIMIT_HORIZON_DAYS:
                proof = f"reaches {name} in about {d} day{'' if d == 1 else 's'}"
                pace = f" At that pace it reaches the {said} in about {plural(d, 'day')}."
        text += pace
    else:
        headline = f"{box.label}: stable, no trend this month"
        proof = f"slope {fit.slope:+.2f}{per_day} is within noise (n {len(days)} days)"
        text = (f"The daily average of {box_words(box)}, has no steady rise or fall this month, only day-to-day "
                f"noise over {plural(len(days), 'measuring day')}.")

    caveats = []
    if before is not None and len(before.values) >= MIN_BOX_N and (mean_sd(before.values)[1] or 0) >= 1e-9:
        mu0, sd0 = mean_sd(before.values)
        confidence = "solid"
    else:
        mu0, sd0 = mean_sd(box.values)
        confidence = "exploratory"
        caveats.append(NO_BASELINE)
    if sd0 is not None and sd0 >= 1e-9:
        ordered = sorted(zip(box.dates, box.values), key=lambda p: p[0])
        i = ewma_first_out([v for _, v in ordered], mu0, sd0)
        if i is not None:
            proof += f"; control chart flagged {ordered[i][0]:%Y-%m-%d}"

    risk = None
    sd = box.sd
    if sd is not None and sd >= 1e-9:
        if real:
            mu, basis = fit.intercept + fit.slope * (xs[-1] + RISK_DAYS_AHEAD), f"trend projected {RISK_DAYS_AHEAD} days ahead"
        else:
            mu, basis = box.mean, "current mean and spread"
        risk = {"expected_out": risk_count(mu, sd, box.lsl, box.usl), "of_next": RISK_CARS, "basis": basis}
        e = risk["expected_out"]
        cars = (f"about {e} of the next {RISK_CARS} cars would be out" if e
                else f"none of the next {RISK_CARS} cars should be out")
        text += f" {'If it keeps going for another week' if real else 'At the current level and scatter'}, {cars}."
    elif not real:
        text += " The readings barely vary from day to day."

    return Answer(
        status="answer",
        headline=headline,
        status_code=box.status,
        proof=proof,
        risk=risk,
        explanation=text,
        confidence=confidence,
        evidence={
            "kind": "trend",
            "series": [{"x": f"{d:%Y-%m-%d}", "y": y} for d, y in zip(days, ys)],
            "columns": ["Month", "Mean", "Status"],
            "rows": [[month_words(h.month), None if h.mean is None else round(h.mean, 2), status_word(h.status, box.scope)]
                     for h in history],
            "limits": {"lo": box.lsl, "hi": box.usl},
        },
        followups=[{"label": "Which points?", "topic": "points", "target": None},
                   {"label": "What changed?", "topic": "changes", "target": None}],
        method={"rule": RULE, "n": len(box.values), "caveats": caveats},
    )
