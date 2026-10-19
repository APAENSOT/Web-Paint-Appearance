"""Landing card rules: weekly upload plan and month-to-date box share. Pure.

Both are owner decisions (2026-10-13), moved here from the browser so every
number on the landing page is an API field.

* **Feed** -- the control plan is every offered model x offered colour, once
  per measured-date week band of the current month (the History bands:
  1 = days 1-7 ... 5 = 29 to month end). A past week with nothing on file is
  MISSING. A past week whose data first arrived after the week ended, or that
  left an offered colour out, is LATE. Otherwise UPDATE. The current week never
  counts against the plant: it still has time.
* **Quality** -- the share of the dashboard's own graded boxes that are PASS,
  per Wave Scan H / Wave Scan V / Film H / Film V, averaged over the groups
  that have a graded box. The statuses are the dashboard's; nothing is
  re-graded here. This is an owner-requested landing summary, not D1's
  product pass rate: `grading_available` is untouched.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time


def week_of(day: int) -> int:
    return min(5, (day - 1) // 7 + 1)


def week_bounds(month_start: date, week: int) -> tuple[date, date]:
    last = calendar.monthrange(month_start.year, month_start.month)[1]
    first = (week - 1) * 7 + 1
    end = last if week == 5 else week * 7
    return month_start.replace(day=first), month_start.replace(day=end)


@dataclass(frozen=True)
class WeekUpload:
    week: int
    combos: frozenset[tuple[str, str]]  # (model, colour)
    first_loaded_at: datetime | None


def feed_status(as_of: datetime, weeks: list[WeekUpload], models: list[str],
                colors: list[str]) -> dict | None:
    if not models or not colors:
        return None
    current = week_of(as_of.day)
    plan = {(m, c) for m in models for c in colors}
    by_week = {w.week: w for w in weeks}
    late = missing = covered = 0
    for week in range(1, current + 1):
        upload = by_week.get(week)
        on_plan = (upload.combos & plan) if upload else frozenset()
        covered += len(on_plan)
        if week == current:
            continue
        if not upload or not upload.combos:
            missing += 1
            continue
        ended = datetime.combine(week_bounds(as_of.date().replace(day=1), week)[1],
                                 time.max, tzinfo=as_of.tzinfo)
        colours_in = {c for _, c in on_plan}
        if len(colours_in) < len(colors) or (
                upload.first_loaded_at is not None and upload.first_loaded_at > ended):
            late += 1
    this_week = by_week.get(current)
    return {
        "level": "MISSING" if missing else "LATE" if late else "UPDATE",
        "pct": 100 * covered / (len(plan) * current),
        "week": current,
        "late_weeks": late,
        "missing_weeks": missing,
        "colours_this_week": len({c for _, c in (this_week.combos & plan)}) if this_week else 0,
        "colours": len(colors),
        "models": len(models),
    }


def box_share(groups: dict[str, list[str | None]]) -> dict:
    """`groups`: name -> box statuses. Ungraded (None) boxes are skipped."""
    out = []
    for name, statuses in groups.items():
        graded = [s for s in statuses if s is not None]
        out.append({"group": name, "graded": len(graded),
                    "passed": sum(1 for s in graded if s == "PASS")})
    shares = [100 * g["passed"] / g["graded"] for g in out if g["graded"]]
    return {"pct": sum(shares) / len(shares) if shares else None, "groups": out}
