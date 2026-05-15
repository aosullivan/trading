"""Contract tests for the Strategy Registry.

Every registered Strategy must:
1. Produce a StrategyResult with a valid direction Series aligned to the input.
2. Pair with a Backtest Engine that actually runs against its direction.

These tests are parametrized over the registry, so adding a new Strategy
automatically extends coverage.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lib.backtesting import run_backtest
from lib.strategies import (
    STRATEGIES,
    StrategyContext,
    StrategyResult,
    all_strategies,
)


@pytest.fixture
def ctx(sample_df) -> StrategyContext:
    return StrategyContext(df=sample_df, ticker="TEST")


def _strategy_ids():
    return sorted(STRATEGIES.keys())


@pytest.fixture(params=_strategy_ids())
def strategy(request):
    return STRATEGIES[request.param]


def test_registry_is_non_empty():
    assert len(STRATEGIES) > 0, "Strategy registry should not be empty"


def test_registry_keys_match_modules():
    for key, strategy in STRATEGIES.items():
        assert strategy.key == key, f"Registry key {key!r} != StrategyDef.key {strategy.key!r}"


def test_compute_returns_strategy_result(strategy, ctx):
    result = strategy.compute(ctx)
    assert isinstance(result, StrategyResult), (
        f"{strategy.key}.compute() returned {type(result).__name__}, not StrategyResult"
    )


def test_direction_is_aligned_series(strategy, ctx):
    result = strategy.compute(ctx)
    assert isinstance(result.direction, pd.Series), (
        f"{strategy.key}: direction must be a pd.Series"
    )
    assert result.direction.index.equals(ctx.df.index), (
        f"{strategy.key}: direction index must match df.index"
    )


def test_direction_values_in_signed_set(strategy, ctx):
    result = strategy.compute(ctx)
    unique = set(result.direction.dropna().unique())
    assert unique.issubset({-1, 0, 1}), (
        f"{strategy.key}: direction values {unique} not in {{-1, 0, 1}}"
    )


def test_overlays_are_mapping(strategy, ctx):
    result = strategy.compute(ctx)
    assert hasattr(result.overlays, "items"), (
        f"{strategy.key}: overlays must be a Mapping"
    )


def test_paired_engine_runs(strategy, ctx):
    result = strategy.compute(ctx)
    extra = dict(strategy.backtest_kwargs_from(result)) if strategy.backtest_kwargs_from else {}
    out = run_backtest(strategy.backtest_engine, ctx.df, result.direction, **extra)
    assert isinstance(out, tuple), (
        f"{strategy.key}: paired engine {strategy.backtest_engine} did not return a tuple"
    )
    assert len(out) >= 3, (
        f"{strategy.key}: paired engine returned {len(out)} values, expected at least 3 (trades, summary, equity_curve)"
    )


def test_default_params_round_trip(strategy, ctx):
    """If default_params is set, passing them explicitly via ctx.params yields the same direction."""
    if not strategy.default_params:
        pytest.skip("no default_params declared")
    baseline = strategy.compute(ctx)
    explicit = strategy.compute(
        StrategyContext(df=ctx.df, ticker=ctx.ticker, params=dict(strategy.default_params))
    )
    pd.testing.assert_series_equal(baseline.direction, explicit.direction)


def test_maintained_and_experimental_partition_is_total():
    from lib.strategies import maintained_strategies, experimental_strategies

    keys_m = {s.key for s in maintained_strategies()}
    keys_e = {s.key for s in experimental_strategies()}
    assert keys_m.isdisjoint(keys_e), "maintained and experimental must be disjoint"
    assert keys_m | keys_e == set(STRATEGIES.keys()), (
        "every registered strategy must be classified maintained or experimental"
    )
