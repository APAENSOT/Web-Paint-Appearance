"""AR04 topic `points`: which points repeat as out, by a one-sided binomial test."""

from __future__ import annotations

from collections import defaultdict

from app.domain.assistant.answer import MIN_POINT_OUT, POINT_P, Answer, PointReading, all_clear, not_enough
from app.domain.report_stats import binomial_sf

RULE = (f"One-sided binomial test against the plant's normal out count; "
        f"flagged when p < {POINT_P} and at least {MIN_POINT_OUT} out.")
DOMAIN = {"film": ("Film", "cars", "Check film build at {}"),
          "wavescan": ("Wave Scan", "readings", "Check {} for CF loss")}


def _units(rs: list[PointReading]) -> dict[str, list[bool]]:
    """Per point, one out-flag per unit: (point, car) for film (out if any reading out), reading for wavescan."""
    by: dict = defaultdict(lambda: defaultdict(list))
    for i, r in enumerate(rs):
        by[r.point][r.car if r.car is not None else ("reading", i)].append(r.out)
    return {p: [any(v) for v in cars.values()] for p, cars in by.items()}


def points(readings: list[PointReading], *, skipped_no_limit: int = 0) -> Answer:
    a = _rank(readings)
    if skipped_no_limit:
        n = skipped_no_limit
        a.method["caveats"].append(f"{n} reading{'' if n == 1 else 's'} skipped: no limit")
    return a


def _rank(readings: list[PointReading]) -> Answer:
    if not readings:
        return not_enough("No point readings for this month and filter.", 0, RULE)
    domains = sorted({r.domain for r in readings})
    rows = []  # (flagged, p, k, n, point, domain, p0)
    for d in domains:
        units = _units([r for r in readings if r.domain == d])
        total = sum(len(u) for u in units.values())
        p0 = sum(sum(u) for u in units.values()) / total
        for pt, u in units.items():
            k, n = sum(u), len(u)
            if k == 0:
                continue
            p = binomial_sf(k, n, p0) if 0 < p0 < 1 else 1.0
            rows.append((0 < p0 < 1 and p < POINT_P and k >= MIN_POINT_OUT, p, k, n, pt, d, p0))
    n_all = len(readings)
    flagged = sorted((r for r in rows if r[0]), key=lambda r: (r[1], -r[2]))
    if not flagged:
        a = all_clear("No point stands out from the plant's normal.", RULE, n_all)
        n_pts = len({(r.domain, r.point) for r in readings})
        a.explanation = (f"None of the {n_pts} measured points is out more often than the plant's normal, "
                         "so there's no single spot to chase." if n_pts > 1
                         else "The 1 measured point is not out more often than normal.")
        return a
    _, _, k, n, pt, d, p0 = flagged[0]
    word, unit, step = DOMAIN[d]
    both = len(domains) > 1
    ordered = flagged + sorted((r for r in rows if not r[0]), key=lambda r: (-r[2], r[1]))
    text = (f"{pt} is a repeat problem on {word}: it was out on {k} of {n} {unit}, against about 1 in "
            f"{round(1 / p0)} across the plant. That's too often to be bad luck, so the cause sits at that spot "
            "rather than in the whole process.")
    if len(flagged) > 1:
        more = [r[4] for r in flagged[1:4]]
        text += (f" {len(flagged) - 1} more point{'s also stand' if len(flagged) > 2 else ' also stands'} out: "
                 f"{', '.join(more)}{' and others' if len(flagged) > 4 else ''}.")
    return Answer(
        status="answer",
        headline=f"{pt} is a repeat problem",
        proof=f"out on {k} of {n} {unit} (plant normal: about 1 in {round(1 / p0)})",
        explanation=text,
        next_step=step.format(pt),
        confidence="solid",
        evidence={
            "kind": "table",
            "columns": ["Point", "Out", "Measured", "Plant normal"],
            "rows": [[f"{r[4]} ({DOMAIN[r[5]][0]})" if both else r[4], r[2], r[3],
                      f"about 1 in {round(1 / r[6])}"] for r in ordered],
            "series": [],
        },
        followups=[{"label": "Which colours?", "topic": "colours", "target": None},
                   {"label": "What changed?", "topic": "changes", "target": None}],
        method={"rule": RULE, "n": n_all, "caveats": []},
    )
