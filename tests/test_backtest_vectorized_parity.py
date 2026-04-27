"""Byte-for-byte parity between `backtest_direction` (reference, iterative)
and `backtest_direction_vectorized` (optimized).

The vectorized implementation is a drop-in replacement that powers the
default-MM path inside `_run_direction_backtest`. Any divergence must be
caught here before code ships. Rule: *no vectorized call site exists in
production unless every scenario in this file passes.*

Each scenario is authored against the reference implementation; the
vectorized implementation must reproduce `(trades, summary, equity_curve)`
identically. `summary` contains floats — we compare via structural equality
because the rounding happens to 2/8 decimal places inside both paths and
Python's `==` on nested dicts/lists is reliable at those precisions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lib.backtesting import (
    backtest_direction,
    backtest_direction_vectorized,
)


def _make_df(close_values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """Synthetic OHLCV frame. Open = Close (so entry/exit prices are deterministic)."""
    dates = pd.bdate_range(start, periods=len(close_values))
    close = np.array(close_values, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,          # deliberate: makes assertions easier to write
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": np.full(len(close), 1_000_000),
        },
        index=dates,
    )


def _assert_parity(df, direction, **kwargs):
    ref_trades, ref_summary, ref_equity = backtest_direction(df, direction, **kwargs)
    vec_trades, vec_summary, vec_equity = backtest_direction_vectorized(
        df, direction, **kwargs
    )
    assert vec_trades == ref_trades, (
        f"trades diverge\n  ref={ref_trades}\n  vec={vec_trades}"
    )
    assert vec_equity == ref_equity, (
        f"equity_curve diverges\n  ref={ref_equity}\n  vec={vec_equity}"
    )
    assert vec_summary == ref_summary, (
        f"summary diverges\n  ref={ref_summary}\n  vec={vec_summary}"
    )


# --- Scenarios ---------------------------------------------------------


def test_parity_all_flat():
    df = _make_df([100.0] * 20)
    direction = pd.Series([-1] * 20, index=df.index)
    _assert_parity(df, direction)


def test_parity_all_bullish_no_synthetic_entry():
    # direction[0]==1 causes initial_prev to be 1, which suppresses the
    # first entry signal. Reference produces zero trades.
    df = _make_df(list(range(100, 120)))
    direction = pd.Series([1] * 20, index=df.index)
    _assert_parity(df, direction)


def test_parity_all_bullish_with_synthetic_entry():
    df = _make_df(list(range(100, 120)))
    direction = pd.Series([1] * 20, index=df.index)
    _assert_parity(df, direction, start_in_position=True)


def test_parity_one_clean_cycle():
    df = _make_df(
        [100.0] * 5    # flat
        + [110.0] * 5  # rally
        + [105.0] * 5  # pullback
    )
    direction = pd.Series([-1] * 5 + [1] * 5 + [-1] * 5, index=df.index)
    _assert_parity(df, direction)


def test_parity_three_cycles():
    segments = [
        ([-1] * 5, [50.0] * 5),
        ([1] * 7, [55.0, 60.0, 65.0, 63.0, 67.0, 70.0, 72.0]),
        ([-1] * 4, [68.0, 65.0, 60.0, 58.0]),
        ([1] * 6, [62.0, 65.0, 68.0, 72.0, 75.0, 78.0]),
        ([-1] * 3, [74.0, 70.0, 68.0]),
        ([1] * 5, [72.0, 75.0, 80.0, 85.0, 90.0]),
        ([-1] * 4, [85.0, 82.0, 78.0, 75.0]),
    ]
    dirs = sum([s[0] for s in segments], [])
    closes = sum([s[1] for s in segments], [])
    df = _make_df(closes)
    direction = pd.Series(dirs, index=df.index)
    _assert_parity(df, direction)


def test_parity_trade_open_at_end():
    df = _make_df([100.0] * 5 + [110.0] * 8)
    direction = pd.Series([-1] * 5 + [1] * 8, index=df.index)
    _assert_parity(df, direction)


def test_parity_neutral_zero_bars():
    # "0" must be treated exactly the same as "-1" — i.e., not 1 → not long.
    df = _make_df([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 104.0, 103.0])
    direction = pd.Series([-1, 0, 1, 1, 1, 0, 0, -1], index=df.index)
    _assert_parity(df, direction)


def test_parity_prior_long_start_in_position_true():
    df = _make_df([100.0, 102.0, 101.0, 99.0, 97.0, 98.0])
    direction = pd.Series([1, 1, -1, -1, -1, -1], index=df.index)
    _assert_parity(df, direction, start_in_position=True, prior_direction=1)


def test_parity_prior_long_start_in_position_false():
    # prior_direction=1, start_in_position=False: initial_prev=1 suppresses
    # the bar-0 entry signal. First entry requires a flip from non-1 to 1.
    df = _make_df([100.0, 102.0, 104.0, 101.0, 99.0, 101.0, 103.0])
    direction = pd.Series([1, 1, -1, -1, 1, 1, 1], index=df.index)
    _assert_parity(df, direction, start_in_position=False, prior_direction=1)


def test_parity_randomized_long_series():
    np.random.seed(13)
    N = 300
    closes = 100 + np.cumsum(np.random.randn(N) * 0.7)
    df = _make_df(list(closes))
    # Force some structure: direction flips when a 20-bar EMA crosses a 5-bar EMA
    short_ema = pd.Series(closes).ewm(span=5, adjust=False).mean()
    long_ema = pd.Series(closes).ewm(span=20, adjust=False).mean()
    direction = pd.Series(
        np.where(short_ema > long_ema, 1, -1),
        index=df.index,
    )
    _assert_parity(df, direction)


def test_parity_short_df_edge_cases():
    # Single bar
    df1 = _make_df([100.0])
    _assert_parity(df1, pd.Series([1], index=df1.index))
    _assert_parity(df1, pd.Series([1], index=df1.index), start_in_position=True)

    # Two bars, entry candidate on bar 0 but no execution (i in range(0, N-1) = [0])
    # Execution happens at bar 1 (last bar). Open trade at end.
    df2 = _make_df([100.0, 110.0])
    _assert_parity(df2, pd.Series([1, 1], index=df2.index), prior_direction=-1)


def test_parity_empty_df():
    df = _make_df([])
    direction = pd.Series([], index=df.index, dtype=int)
    _assert_parity(df, direction)


def test_parity_alternating_every_bar():
    # Pathological: direction flips every bar. The reference still produces
    # valid trades — vectorized must match.
    N = 40
    df = _make_df([100.0 + i * 0.5 for i in range(N)])
    direction = pd.Series([1 if i % 2 == 0 else -1 for i in range(N)], index=df.index)
    _assert_parity(df, direction)
