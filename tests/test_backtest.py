"""Tests for the backtesting engine."""

import numpy as np
import pandas as pd
import pytest

from lib.backtesting import (
    backtest_direction,
    backtest_supertrend,
    build_equity_curve,
    compute_summary,
)
from lib.technical_indicators import (
    compute_supertrend,
    compute_ema_crossover,
)
from lib.settings import INITIAL_CAPITAL


class TestBacktestDirection:
    def test_no_trades_when_never_bullish(self, sample_df):
        direction = pd.Series(-1, index=sample_df.index)
        trades, summary, equity = backtest_direction(sample_df, direction)
        assert len(trades) == 0
        assert summary["total_trades"] == 0

    def test_single_trade_always_bullish(self, sample_df):
        direction = pd.Series(1, index=sample_df.index)
        direction.iloc[0] = -1
        trades, summary, equity = backtest_direction(sample_df, direction)
        assert len(trades) == 1
        assert trades[0]["open"] is True

    def test_entry_exit_cycle(self, sample_df):
        direction = pd.Series(-1, index=sample_df.index)
        direction.iloc[10:50] = 1
        trades, summary, equity = backtest_direction(sample_df, direction)
        assert len(trades) == 1
        assert "exit_date" in trades[0]
        assert "pnl" in trades[0]

    def test_multiple_trades(self, sample_df):
        direction = pd.Series(-1, index=sample_df.index)
        direction.iloc[10:30] = 1
        direction.iloc[50:80] = 1
        direction.iloc[100:130] = 1
        trades, summary, equity = backtest_direction(sample_df, direction)
        assert len(trades) == 3
        assert summary["total_trades"] == 3

    def test_pnl_sign(self, sample_df):
        """If entry price < exit price, PnL should be positive."""
        _, direction = compute_supertrend(sample_df)
        trades, _, _ = backtest_direction(sample_df, direction)
        for t in trades:
            if t.get("open"):
                continue
            expected_sign = 1 if t["exit_price"] > t["entry_price"] else -1
            actual_sign = 1 if t["pnl"] > 0 else -1
            assert actual_sign == expected_sign

    def test_quantity_uses_full_capital(self, sample_df):
        direction = pd.Series(-1, index=sample_df.index)
        direction.iloc[10:30] = 1
        trades, _, _ = backtest_direction(sample_df, direction)
        expected_qty = INITIAL_CAPITAL / trades[0]["entry_price"]
        assert abs(trades[0]["quantity"] - round(expected_qty, 8)) < 0.01


class TestBacktestSupertrend:
    def test_delegates_to_backtest_direction(self, sample_df):
        _, direction = compute_supertrend(sample_df)
        trades1, summary1, eq1 = backtest_supertrend(sample_df, direction)
        trades2, summary2, eq2 = backtest_direction(sample_df, direction)
        assert trades1 == trades2
        assert summary1 == summary2


class TestEquityCurve:
    def test_length_matches_df(self, sample_df):
        _, direction = compute_supertrend(sample_df)
        trades, _, equity = backtest_direction(sample_df, direction)
        assert len(equity) == len(sample_df)

    def test_starts_at_initial_capital(self, sample_df):
        direction = pd.Series(-1, index=sample_df.index)
        trades, _, equity = backtest_direction(sample_df, direction)
        assert equity[0]["value"] == INITIAL_CAPITAL


class TestComputeSummary:
    def test_empty_trades(self):
        summary = compute_summary([], [])
        assert summary["total_trades"] == 0
        assert summary["win_rate"] == 0
        assert summary["ending_equity"] == INITIAL_CAPITAL

    def test_win_rate_calculation(self):
        trades = [
            {"pnl": 100, "entry_price": 10, "exit_price": 11, "quantity": 10},
            {"pnl": -50, "entry_price": 10, "exit_price": 9, "quantity": 10},
            {"pnl": 200, "entry_price": 10, "exit_price": 12, "quantity": 10},
        ]
        equity = [{"value": INITIAL_CAPITAL}, {"value": INITIAL_CAPITAL + 250}]
        summary = compute_summary(trades, equity)
        assert summary["total_trades"] == 3
        assert summary["winners"] == 2
        assert summary["losers"] == 1
        assert summary["win_rate"] == pytest.approx(66.7, abs=0.1)

    def test_profit_factor(self):
        trades = [
            {"pnl": 300},
            {"pnl": -100},
        ]
        equity = [{"value": INITIAL_CAPITAL}]
        summary = compute_summary(trades, equity)
        assert summary["profit_factor"] == 3.0

    def test_max_drawdown(self):
        trades = [{"pnl": 100}]
        equity = [
            {"value": 100000},
            {"value": 110000},
            {"value": 95000},
            {"value": 105000},
        ]
        summary = compute_summary(trades, equity)
        assert summary["max_drawdown"] == 15000.0
