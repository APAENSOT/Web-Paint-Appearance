"""Plotly-linear CF boxplot stats for Monthly Overview.

No FastAPI, no SQL, no grading. Quartiles follow Plotly's linear
percentile (``Lib.interp``): position ``(n-1)*p``, interpolate between
adjacent order statistics. Whiskers are Tukey 1.5 IQR. The mean is the
exact arithmetic mean of the values given.

Callers pass every matching active CF. This module never caps the set.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Sequence

PREFERRED_MODELS: tuple[str, ...] = ("P703 DBL RAPTOR", "P703 DBL RANGER")

_ZERO = Decimal("0")
_ONE = Decimal("1")
_IQR_K = Decimal("1.5")
_Q1 = Decimal("0.25")
_Q2 = Decimal("0.5")
_Q3 = Decimal("0.75")


@dataclass(frozen=True)
class BoxStats:
    n: int
    box_min: Decimal
    q1: Decimal
    median: Decimal
    q3: Decimal
    box_max: Decimal
    whisker_lo: Decimal
    whisker_hi: Decimal
    outliers: tuple[Decimal, ...]
    mean: Decimal


def percentile_linear(sorted_vals: Sequence[Decimal], p: Decimal) -> Decimal:
    """Plotly ``Lib.interp`` / NumPy ``method='linear'`` percentile."""
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("percentile of an empty sample")
    if n == 1:
        return sorted_vals[0]
    pos = Decimal(n - 1) * p
    i0 = int(pos.to_integral_value(rounding=ROUND_FLOOR))
    frac = pos - Decimal(i0)
    i1 = min(i0 + 1, n - 1)
    return sorted_vals[i0] * (_ONE - frac) + sorted_vals[i1] * frac


def box_stats(values: Sequence[Decimal]) -> BoxStats:
    """Full-sample box, whiskers and mean. ``values`` must be non-empty."""
    if not values:
        raise ValueError("boxplot of an empty sample")
    ordered = tuple(sorted(Decimal(v) for v in values))
    n = len(ordered)
    q1 = percentile_linear(ordered, _Q1)
    median = percentile_linear(ordered, _Q2)
    q3 = percentile_linear(ordered, _Q3)
    iqr = q3 - q1
    lo_fence = q1 - _IQR_K * iqr
    hi_fence = q3 + _IQR_K * iqr
    inliers = tuple(v for v in ordered if lo_fence <= v <= hi_fence)
    whisker_lo = inliers[0] if inliers else ordered[0]
    whisker_hi = inliers[-1] if inliers else ordered[-1]
    outliers = tuple(v for v in ordered if v < lo_fence or v > hi_fence)
    total = sum(ordered, _ZERO)
    return BoxStats(
        n=n,
        box_min=ordered[0],
        q1=q1,
        median=median,
        q3=q3,
        box_max=ordered[-1],
        whisker_lo=whisker_lo,
        whisker_hi=whisker_hi,
        outliers=outliers,
        mean=total / Decimal(n),
    )


def model_sort_key(code: str) -> tuple[int, int, str]:
    if code in PREFERRED_MODELS:
        return (0, PREFERRED_MODELS.index(code), "")
    return (1, 0, code)


def order_models(codes: Sequence[str]) -> list[str]:
    """Raptor, then Ranger, then every other measured model_code sorted."""
    present = list(dict.fromkeys(codes))
    return sorted(present, key=model_sort_key)
