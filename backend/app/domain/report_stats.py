"""Spearman rank correlation, OLS slope and fit, and the AR04 assistant primitives
(normal_cdf, mean_sd, cpk, binomial_sf, mann_whitney, ols_fit, ewma_first_out,
multiple_ols), pure Python (AR03, D-AR03-3).

No numpy or scipy in this backend. Callers pass paired values; a pair with a
None on either side is dropped first, so ``n`` is the pairs actually used.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, exp, lgamma, log, log1p, sqrt
from typing import Sequence

MIN_N = 3


def _pairs(xs: Sequence, ys: Sequence) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in zip(xs, ys) if x is not None and y is not None]


def _ranks(values: list[float]) -> list[float]:
    """1-based ranks; ties share their average rank."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / sqrt(sxx * syy)


def spearman(xs: Sequence, ys: Sequence) -> tuple[float | None, int]:
    """(rho, n): Pearson on average ranks. None when n < 3 or a side is constant."""
    pairs = _pairs(xs, ys)
    n = len(pairs)
    if n < MIN_N:
        return None, n
    rx = _ranks([p[0] for p in pairs])
    ry = _ranks([p[1] for p in pairs])
    return _pearson(rx, ry), n


def ols_slope(xs: Sequence, ys: Sequence) -> float | None:
    """Least-squares slope of y on x. None when n < 3 or x is constant."""
    pairs = _pairs(xs, ys)
    n = len(pairs)
    if n < MIN_N:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / sxx


MW_MIN_N = 10
T95: dict[int, float] = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
                         8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086,
                         25: 2.060, 30: 2.042}


def normal_cdf(z: float) -> float:
    return 0.5 * (1 + erf(z / sqrt(2)))


def mean_sd(values: Sequence[float]) -> tuple[float | None, float | None]:
    """(mean, sample sd). sd is None for n = 1; both None for n = 0."""
    n = len(values)
    if n == 0:
        return None, None
    m = sum(values) / n
    if n == 1:
        return m, None
    return m, sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


def cpk(values: Sequence[float], lsl: float | None, usl: float | None) -> float | None:
    """Min over the limits present; None when n < 2, sd = 0 or no limit."""
    m, sd = mean_sd(values)
    if sd is None or sd == 0 or (lsl is None and usl is None):
        return None
    sides = []
    if lsl is not None:
        sides.append((m - lsl) / (3 * sd))
    if usl is not None:
        sides.append((usl - m) / (3 * sd))
    return min(sides)


def binomial_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), exact."""
    k = max(k, 0)
    if k > n:
        return 0.0
    if p <= 0 or p >= 1:
        return 1.0 if k == 0 or p >= 1 else 0.0
    # Log space: comb(n, i) alone overflows a float once n is in the thousands (a month's readings).
    lp, lq, ln = log(p), log1p(-p), lgamma(n + 1)
    terms = (exp(ln - lgamma(i + 1) - lgamma(n - i + 1) + i * lp + (n - i) * lq) for i in range(k, n + 1))
    return min(1.0, sum(terms))


def mann_whitney(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Two-sided p, normal approximation with tie-corrected sigma and continuity 0.5."""
    n1, n2 = len(xs), len(ys)
    if n1 < MW_MIN_N or n2 < MW_MIN_N:
        return None
    n = n1 + n2
    ranks = _ranks([float(v) for v in xs] + [float(v) for v in ys])
    u = sum(ranks[:n1]) - n1 * (n1 + 1) / 2
    counts: dict[float, int] = {}
    for v in list(xs) + list(ys):
        counts[v] = counts.get(v, 0) + 1
    ties = sum(t**3 - t for t in counts.values())
    var = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1)))
    if var <= 0:
        return None
    z = max(abs(u - n1 * n2 / 2) - 0.5, 0) / sqrt(var)
    return min(1.0, 2 * (1 - normal_cdf(z)))


@dataclass(frozen=True)
class OlsFit:
    slope: float
    intercept: float
    slope_se: float
    n: int

    def ci95(self) -> tuple[float, float]:
        df = self.n - 2
        t = 1.96 if df > 30 else T95[max(k for k in T95 if k <= df)]
        return self.slope - t * self.slope_se, self.slope + t * self.slope_se


def ols_fit(xs: Sequence, ys: Sequence) -> OlsFit | None:
    """Least-squares fit with slope standard error. None when n < 3 or x is constant."""
    pairs = _pairs(xs, ys)
    n = len(pairs)
    if n < MIN_N:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in pairs) / sxx
    intercept = my - slope * mx
    sse = sum((y - intercept - slope * x) ** 2 for x, y in pairs)
    return OlsFit(slope, intercept, sqrt(sse / (n - 2) / sxx), n)


def ewma_first_out(values: Sequence[float], mu0: float, sd0: float, lam: float = 0.2) -> int | None:
    """First index where the EWMA leaves mu0 +/- 3*sd0*sqrt(lam/(2-lam)); None if never."""
    limit = 3 * sd0 * sqrt(lam / (2 - lam))
    z = mu0
    for i, x in enumerate(values):
        z = lam * x + (1 - lam) * z
        if abs(z - mu0) > limit:
            return i
    return None


def multiple_ols(rows: Sequence[Sequence[float]], ys: Sequence[float]) -> list[float] | None:
    """[intercept, b1..bk] by normal equations; None when n <= k + 1 or singular."""
    n = len(rows)
    k = len(rows[0]) if n else 0
    if n <= k + 1:
        return None
    x = [[1.0, *map(float, r)] for r in rows]
    m = k + 1
    a = [[sum(r[i] * r[j] for r in x) for j in range(m)] + [sum(r[i] * y for r, y in zip(x, ys))]
         for i in range(m)]
    for c in range(m):
        p = max(range(c, m), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            return None
        a[c], a[p] = a[p], a[c]
        for r in range(c + 1, m):
            f = a[r][c] / a[c][c]
            a[r] = [v - f * w for v, w in zip(a[r], a[c])]
    beta = [0.0] * m
    for i in range(m - 1, -1, -1):
        beta[i] = (a[i][m] - sum(a[i][j] * beta[j] for j in range(i + 1, m))) / a[i][i]
    return beta
