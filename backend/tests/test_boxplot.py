"""Plotly-linear boxplot math. No database."""

from __future__ import annotations

from decimal import Decimal

from app.domain.boxplot import box_stats, order_models, percentile_linear


def _d(*values: int | str) -> list[Decimal]:
    return [Decimal(v) for v in values]


def test_plotly_linear_percentiles_are_pinned():
    """n=10 interpolates; n=5 lands on order statistics."""
    ten = _d(1, 2, 3, 4, 5, 6, 7, 8, 9, 20)
    assert percentile_linear(ten, Decimal("0.25")) == Decimal("3.25")
    assert percentile_linear(ten, Decimal("0.5")) == Decimal("5.5")
    assert percentile_linear(ten, Decimal("0.75")) == Decimal("7.75")
    five = _d(10, 20, 30, 40, 50)
    assert percentile_linear(five, Decimal("0.25")) == Decimal("20")
    assert percentile_linear(five, Decimal("0.5")) == Decimal("30")
    assert percentile_linear(five, Decimal("0.75")) == Decimal("40")


def test_tukey_whiskers_and_exact_mean_are_pinned():
    stats = box_stats(_d(1, 2, 3, 4, 5, 6, 7, 8, 9, 20))
    assert stats.n == 10
    assert stats.box_min == Decimal("1")
    assert stats.q1 == Decimal("3.25")
    assert stats.median == Decimal("5.5")
    assert stats.q3 == Decimal("7.75")
    assert stats.box_max == Decimal("20")
    assert stats.whisker_lo == Decimal("1")
    assert stats.whisker_hi == Decimal("9")
    assert stats.outliers == (Decimal("20"),)
    assert stats.mean == Decimal("6.5")


def test_a_single_value_is_a_degenerate_box():
    stats = box_stats(_d("60.123456789"))
    assert stats.n == 1
    assert stats.mean == Decimal("60.123456789")
    assert stats.q1 == stats.median == stats.q3 == Decimal("60.123456789")
    assert stats.outliers == ()


def test_uncapped_population_keeps_every_value():
    values = _d(*range(1, 5002))
    stats = box_stats(values)
    assert stats.n == 5001
    assert stats.mean == Decimal("2501")
    assert stats.box_min == Decimal("1")
    assert stats.box_max == Decimal("5001")


def test_ftm_model_order_is_raptor_then_ranger_then_the_rest():
    assert order_models(
        ["P703 DBL SUPER DUTY", "P703 DBL RANGER", "P703 DBL RAPTOR", "U704"]
    ) == ["P703 DBL RAPTOR", "P703 DBL RANGER", "P703 DBL SUPER DUTY", "U704"]
