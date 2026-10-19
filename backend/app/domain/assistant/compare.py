"""AR05 compare core: is the gap between two groups of readings real? (same rule as AR04 `changes`).

Pure. Groups are lists of floats; the topics in ``compare_topics`` pick the readings.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import sqrt
from statistics import median

from app.domain.assistant.answer import MIN_BOX_N, SHIFT_P, SHIFT_SIGMA, Answer, not_enough
from app.domain.assistant.plain_words import difference_sentence, gap_words
from app.domain.boxplot import box_stats
from app.domain.report_stats import mann_whitney, mean_sd

RULE = "Mann-Whitney on the two groups; real = p under 0.05 and a gap of 0.5 sd or more"
LIMITS_DIFFER = "Limits differ between the groups, so none are drawn."


@dataclass(frozen=True)
class Verdict:
    real: bool
    delta: float  # median(a) - median(b)
    p: float | None
    n_a: int
    n_b: int


def compare_values(a: list[float], b: list[float]) -> Verdict | None:
    if min(len(a), len(b)) < MIN_BOX_N:
        return None
    delta = median(a) - median(b)
    p = mann_whitney(a, b)
    sd_a, sd_b = mean_sd(a)[1], mean_sd(b)[1]
    real = False
    if p is not None and p < SHIFT_P and sd_a is not None and sd_b is not None:
        pooled = sqrt((sd_a**2 + sd_b**2) / 2)
        real = pooled >= 1e-9 and abs(delta) >= SHIFT_SIGMA * pooled
    return Verdict(real, delta, p, len(a), len(b))


def group_stats(label: str, values: list[float]) -> dict:
    s = box_stats([Decimal(str(v)) for v in values])
    return {"label": label, "n": s.n, "q1": float(s.q1), "median": float(s.median), "q3": float(s.q3),
            "low": float(s.whisker_lo), "high": float(s.whisker_hi), "mean": float(s.mean)}


def difference_words(v: Verdict, unit: str, subject_a: str, subject_b: str, metric_word: str) -> str:
    gap = f"{abs(v.delta):.1f}{' ' + unit if unit else ''}"
    if not v.real:
        return f"No real difference on {metric_word} ({subject_a} vs {subject_b}, Δ {gap})"
    word = ("thinner" if v.delta < 0 else "thicker") if unit else ("lower" if v.delta < 0 else "higher")
    return f"{subject_a} is {gap} {word} on {metric_word} than {subject_b} — real difference"


def compare_groups(label_a: str, label_b: str, a: list[float], b: list[float], unit: str, metric_word: str,
                   limits: dict | None, caveats: list[str], followups: list[dict], scope: str = "",
                   say: tuple[str, str] | None = None) -> Answer:
    """Paragraph only: scope goes before the metric (e.g. 'Raptor '); say renames the groups (e.g. 'Raptor')."""
    v = compare_values(a, b)
    if v is None:
        return not_enough(f"{label_a} {len(a)}, {label_b} {len(b)} readings; {MIN_BOX_N} needed each.",
                          len(a) + len(b), RULE)
    ga, gb = group_stats(label_a, a), group_stats(label_b, b)
    u = f" {unit}" if unit else ""
    gap = gap_words(v.delta, unit)
    sa, sb = say or (label_a, label_b)
    ma, mb = f"{ga['median']:.1f}{u}", f"{gb['median']:.1f}{u}"
    if v.real and gap:
        text = f"{sa} is {gap} than {sb} on {scope}{metric_word} (medians {ma} and {mb})."
    else:
        text = f"{sa} and {sb} medians on {scope}{metric_word} are {ma} and {mb}, a gap of {abs(v.delta):.1f}{u}."
    text += f" That's {difference_sentence(v)}."
    return Answer(
        status="answer",
        headline=difference_words(v, unit, label_a, label_b, metric_word),
        proof=f"median {label_a} {ga['median']:.1f}{u}, {label_b} {gb['median']:.1f}{u}; n {v.n_a} and {v.n_b}",
        explanation=text,
        confidence="solid",
        evidence={"kind": "boxplot_pair", "columns": ["Group", "n", "Q1", "Median", "Q3", "Mean"],
                  "rows": [[g["label"], g["n"], *(round(g[k], 2) for k in ("q1", "median", "q3", "mean"))]
                           for g in (ga, gb)],
                  "series": [], "groups": [ga, gb], "limits": limits},
        followups=followups,
        method={"rule": RULE, "n": v.n_a + v.n_b, "caveats": caveats},
    )
