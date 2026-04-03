"""Tests for the backtesting engine."""

import numpy as np
import pandas as pd
import pytest

from lib.backtesting import (
    backtest_direction,
    backtest_ribbon_accumulation,
    backtest_supertrend,
    build_buy_hold_equity_curve,
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

    def test_exits_on_first_visible_bar_when_prior_direction_was_long(self):
        idx = pd.date_range("2024-01-01", periods=4, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100, 101, 102, 103],
                "High": [101, 102, 103, 104],
                "Low": [99, 100, 101, 102],
                "Close": [100, 101, 102, 103],
                "Volume": [1, 1, 1, 1],
            },
            index=idx,
        )
        direction = pd.Series([-1, -1, -1, -1], index=idx)

        trades, summary, _ = backtest_direction(
            df,
            direction,
            start_in_position=True,
            prior_direction=1,
        )

        assert len(trades) == 1
        assert trades[0]["entry_date"] == "2024-01-01"
        assert trades[0]["exit_date"] == "2024-01-02"
        assert trades[0].get("open") is None
        assert summary["total_trades"] == 1
        assert summary["open_trades"] == 0

    def test_enters_after_first_visible_bar_when_prior_direction_was_flat(self):
        idx = pd.date_range("2024-01-01", periods=4, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100, 101, 102, 103],
                "High": [101, 102, 103, 104],
                "Low": [99, 100, 101, 102],
                "Close": [100, 101, 102, 103],
                "Volume": [1, 1, 1, 1],
            },
            index=idx,
        )
        direction = pd.Series([1, 1, 1, 1], index=idx)

        trades, summary, _ = backtest_direction(
            df,
            direction,
            start_in_position=False,
            prior_direction=-1,
        )

        assert len(trades) == 1
        assert trades[0]["entry_date"] == "2024-01-02"
        assert trades[0]["open"] is True
        assert summary["total_trades"] == 0
        assert summary["open_trades"] == 1


class TestBacktestSupertrend:
    def test_delegates_to_backtest_direction(self, sample_df):
        _, direction = compute_supertrend(sample_df)
        trades1, summary1, eq1 = backtest_supertrend(sample_df, direction)
        trades2, summary2, eq2 = backtest_direction(sample_df, direction)
        assert trades1 == trades2
        assert summary1 == summary2


class TestBacktestRibbonAccumulation:
    def test_daily_then_weekly_bullish_flips_add_capital(self):
        idx = pd.date_range("2024-01-01", periods=4, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100, 100, 100, 100],
                "High": [101, 101, 101, 101],
                "Low": [99, 99, 99, 99],
                "Close": [100, 100, 100, 100],
                "Volume": [1, 1, 1, 1],
            },
            index=idx,
        )
        daily = pd.Series([1, 1, 1, 1], index=idx)
        weekly = pd.Series([1, 1, 1, 1], index=idx)

        trades, summary, equity, hold_equity = backtest_ribbon_accumulation(
            df,
            daily,
            weekly,
            prior_daily_direction=-1,
            prior_weekly_direction=-1,
        )

        assert summary["initial_capital"] == 19000.0
        assert summary["ending_equity"] == 19000.0
        assert summary["total_trades"] == 0
        assert summary["open_trades"] == 3
        assert len(equity) == len(df)
        assert hold_equity[-1]["value"] == 19000.0
        assert sorted(t["sleeve"] for t in trades if t.get("open")) == [
            "core",
            "tactical",
            "tactical",
        ]
        assert sorted(t["quantity"] for t in trades if t.get("open")) == [30.0, 60.0, 100.0]

    def test_bearish_flips_scale_out_tactical_sleeve_but_keep_core(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100, 100, 100, 100, 100],
                "High": [101, 101, 101, 101, 101],
                "Low": [99, 99, 99, 99, 99],
                "Close": [100, 100, 100, 100, 100],
                "Volume": [1, 1, 1, 1, 1],
            },
            index=idx,
        )
        daily = pd.Series([1, -1, -1, -1, -1], index=idx)
        weekly = pd.Series([1, 1, -1, -1, -1], index=idx)

        trades, summary, equity, hold_equity = backtest_ribbon_accumulation(
            df,
            daily,
            weekly,
            prior_daily_direction=-1,
            prior_weekly_direction=-1,
            daily_sell_fraction=0.25,
            weekly_sell_fraction=0.5,
        )

        closed_qty = sum(t["quantity"] for t in trades if not t.get("open"))
        open_core_qty = sum(
            t["quantity"]
            for t in trades
            if t.get("open") and t.get("sleeve") == "core"
        )
        open_tactical_qty = sum(
            t["quantity"]
            for t in trades
            if t.get("open") and t.get("sleeve") == "tactical"
        )

        assert summary["initial_capital"] == 19000.0
        assert summary["total_trades"] == 3
        assert summary["open_trades"] == 2
        assert closed_qty == pytest.approx(56.25)
        assert open_core_qty == pytest.approx(100.0)
        assert open_tactical_qty == pytest.approx(33.75)
        assert equity[-1]["value"] == 19000.0
        assert hold_equity[-1]["value"] == 19000.0

    def test_default_ribbon_settings_trim_tactical_sleeve_but_keep_core(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100, 100, 100, 100, 100],
                "High": [101, 101, 101, 101, 101],
                "Low": [99, 99, 99, 99, 99],
                "Close": [100, 100, 100, 100, 100],
                "Volume": [1, 1, 1, 1, 1],
            },
            index=idx,
        )
        daily = pd.Series([1, -1, -1, -1, -1], index=idx)
        weekly = pd.Series([1, 1, -1, -1, -1], index=idx)

        trades, summary, equity, hold_equity = backtest_ribbon_accumulation(
            df,
            daily,
            weekly,
            prior_daily_direction=-1,
            prior_weekly_direction=-1,
        )

        assert summary["initial_capital"] == 19000.0
        closed_qty = sum(t["quantity"] for t in trades if not t.get("open"))
        open_core_qty = sum(
            t["quantity"]
            for t in trades
            if t.get("open") and t.get("sleeve") == "core"
        )
        open_tactical_qty = sum(
            t["quantity"]
            for t in trades
            if t.get("open") and t.get("sleeve") == "tactical"
        )

        assert summary["total_trades"] == 3
        assert summary["open_trades"] == 2
        assert closed_qty == pytest.approx(47.25)
        assert open_core_qty == pytest.approx(100.0)
        assert open_tactical_qty == pytest.approx(42.75)
        assert equity[-1]["value"] == hold_equity[-1]["value"] == 19000.0

    def test_external_adds_stop_at_max_capital(self):
        idx = pd.date_range("2024-01-01", periods=4, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100, 100, 100, 100],
                "High": [101, 101, 101, 101],
                "Low": [99, 99, 99, 99],
                "Close": [100, 100, 100, 100],
                "Volume": [1, 1, 1, 1],
            },
            index=idx,
        )
        daily = pd.Series([1, 1, 1, 1], index=idx)
        weekly = pd.Series([1, 1, 1, 1], index=idx)

        trades, summary, equity, hold_equity = backtest_ribbon_accumulation(
            df,
            daily,
            weekly,
            prior_daily_direction=-1,
            prior_weekly_direction=-1,
            max_capital=16000,
        )

        assert summary["initial_capital"] == 16000.0
        assert summary["ending_equity"] == 16000.0
        assert sum(t["quantity"] for t in trades if t.get("open")) == pytest.approx(160.0)
        assert hold_equity[-1]["value"] == 16000.0


class TestEquityCurve:
    def test_length_matches_df(self, sample_df):
        _, direction = compute_supertrend(sample_df)
        trades, _, equity = backtest_direction(sample_df, direction)
        assert len(equity) == len(sample_df)

    def test_starts_at_initial_capital(self, sample_df):
        direction = pd.Series(-1, index=sample_df.index)
        trades, _, equity = backtest_direction(sample_df, direction)
        assert equity[0]["value"] == INITIAL_CAPITAL

    def test_buy_hold_curve_uses_first_open_and_tracks_close_marks(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="D")
        df = pd.DataFrame(
            {
                "Open": [50, 52, 54],
                "High": [51, 53, 55],
                "Low": [49, 51, 53],
                "Close": [50, 55, 60],
                "Volume": [1, 1, 1],
            },
            index=idx,
        )

        equity = build_buy_hold_equity_curve(df)

        assert equity == [
            {"time": int(idx[0].timestamp()), "value": 10000.0},
            {"time": int(idx[1].timestamp()), "value": 11000.0},
            {"time": int(idx[2].timestamp()), "value": 12000.0},
        ]


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

    def test_open_trade_is_excluded_from_closed_trade_stats(self):
        trades = [
            {"pnl": 120, "entry_price": 10, "exit_price": 11.2, "quantity": 100},
            {
                "pnl": 80,
                "entry_price": 20,
                "exit_price": 20.8,
                "quantity": 100,
                "open": True,
            },
        ]
        equity = [{"value": INITIAL_CAPITAL}, {"value": INITIAL_CAPITAL + 200}]

        summary = compute_summary(trades, equity)

        assert summary["total_trades"] == 1
        assert summary["open_trades"] == 1
        assert summary["winners"] == 1
        assert summary["losers"] == 0
        assert summary["realized_pnl"] == 120
        assert summary["open_pnl"] == 80
        assert summary["total_pnl"] == 200
        assert summary["avg_pnl"] == 120
        assert summary["best_trade"] == 120
