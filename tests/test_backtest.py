"""Tests for the backtesting engine."""

import numpy as np
import pandas as pd
import pytest

from lib.backtesting import (
    MoneyManagementConfig,
    backtest_direction,
    backtest_managed,
    backtest_ribbon_accumulation,
    backtest_ribbon_regime,
    backtest_supertrend,
    build_weekly_confirmed_ribbon_direction,
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


class TestBuildWeeklyConfirmedRibbonDirection:
    def test_holds_previous_regime_until_daily_and_weekly_agree(self):
        idx = pd.date_range("2024-01-01", periods=8, freq="D")
        daily = pd.Series([1, 1, -1, -1, 1, -1, -1, -1], index=idx)
        weekly = pd.Series([1, 1, 1, 1, 1, 1, -1, -1], index=idx)

        confirmed = build_weekly_confirmed_ribbon_direction(daily, weekly)

        assert confirmed.tolist() == [1, 1, 1, 1, 1, 1, -1, -1]

    def test_carries_neutral_daily_and_weekly_bridge_bars(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="D")
        daily = pd.Series([0, 1, 0, 0, -1, 0], index=idx)
        weekly = pd.Series([0, 1, 1, 0, -1, 0], index=idx)

        confirmed = build_weekly_confirmed_ribbon_direction(daily, weekly)

        assert confirmed.tolist() == [0, 1, 1, 1, -1, -1]

    def test_can_seed_from_prior_bull_regime(self):
        idx = pd.date_range("2024-01-01", periods=4, freq="D")
        daily = pd.Series([-1, -1, -1, -1], index=idx)
        weekly = pd.Series([1, 1, -1, -1], index=idx)

        confirmed = build_weekly_confirmed_ribbon_direction(
            daily,
            weekly,
            initial_direction=1,
        )

        assert confirmed.tolist() == [1, 1, -1, -1]

    def test_reentry_cooldown_blocks_immediate_bull_flip(self):
        idx = pd.date_range("2024-01-01", periods=8, freq="D")
        daily = pd.Series([1, 1, -1, -1, 1, 1, 1, 1], index=idx)
        weekly = pd.Series([1, 1, -1, -1, 1, 1, 1, 1], index=idx)

        confirmed = build_weekly_confirmed_ribbon_direction(
            daily,
            weekly,
            initial_direction=1,
            reentry_cooldown_bars=3,
        )

        assert confirmed.tolist() == [1, 1, -1, -1, -1, -1, 1, 1]

    def test_dynamic_cooldown_scales_with_prior_bull_duration(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="D")
        daily = pd.Series([1, 1, 1, 1, -1, -1, 1, 1, 1, 1], index=idx)
        weekly = pd.Series([1, 1, 1, 1, 0, 0, 1, 1, 1, 1], index=idx)

        confirmed = build_weekly_confirmed_ribbon_direction(
            daily,
            weekly,
            initial_direction=1,
            reentry_cooldown_ratio=0.75,
        )

        assert confirmed.tolist() == [1, 1, 1, 1, -1, -1, -1, -1, 1, 1]

    def test_weekly_nonbull_neutral_bars_can_confirm_bear_exit(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="D")
        daily = pd.Series([1, 1, -1, -1, -1, -1], index=idx)
        weekly = pd.Series([1, 1, 0, 0, -1, -1], index=idx)

        confirmed = build_weekly_confirmed_ribbon_direction(
            daily,
            weekly,
            initial_direction=1,
            weekly_nonbull_confirm_bars=2,
        )

        assert confirmed.tolist() == [1, 1, 1, -1, -1, -1]

    def test_does_not_backfill_future_weekly_signal_into_past(self):
        idx = pd.date_range("2025-01-01", periods=6, freq="D")
        daily = pd.Series([1, 1, 1, 1, 1, 1], index=idx)
        # First weekly datapoint appears late; earlier daily bars must stay neutral.
        weekly = pd.Series([1], index=[idx[4]])

        confirmed = build_weekly_confirmed_ribbon_direction(daily, weekly)

        assert confirmed.tolist() == [0, 0, 0, 0, 1, 1]


class TestBacktestRibbonRegime:
    def test_enters_on_weekly_confirmed_bull_and_exits_on_weekly_confirmed_bear(self):
        idx = pd.date_range("2024-01-01", periods=8, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100, 101, 102, 103, 104, 105, 106, 107],
                "High": [101, 102, 103, 104, 105, 106, 107, 108],
                "Low": [99, 100, 101, 102, 103, 104, 105, 106],
                "Close": [101, 102, 103, 104, 105, 106, 107, 108],
                "Volume": [1] * 8,
            },
            index=idx,
        )
        daily = pd.Series([-1, 1, 1, -1, -1, -1, -1, -1], index=idx)
        weekly = pd.Series([-1, -1, 1, 1, 1, -1, -1, -1], index=idx)

        trades, summary, equity = backtest_ribbon_regime(
            df,
            daily,
            weekly,
            prior_direction=-1,
        )

        assert len(trades) == 1
        assert trades[0]["entry_date"] == "2024-01-04"
        assert trades[0]["exit_date"] == "2024-01-07"
        assert trades[0].get("sleeve") is None
        assert summary["total_trades"] == 1
        assert summary["open_trades"] == 0
        assert len(equity) == len(df)


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


class TestBacktestManaged:
    def test_default_config_matches_backtest_direction(self, sample_df):
        """Default MoneyManagementConfig should produce identical results."""
        _, direction = compute_supertrend(sample_df)
        trades_dir, summary_dir, eq_dir = backtest_direction(sample_df, direction)
        trades_mm, summary_mm, eq_mm = backtest_managed(sample_df, direction)

        assert len(trades_dir) == len(trades_mm)
        assert summary_dir == summary_mm
        assert eq_dir == eq_mm

    def test_default_config_with_start_in_position(self):
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

        trades_dir, summary_dir, eq_dir = backtest_direction(
            df, direction, start_in_position=True, prior_direction=1
        )
        trades_mm, summary_mm, eq_mm = backtest_managed(
            df, direction, start_in_position=True, prior_direction=1
        )

        assert len(trades_dir) == len(trades_mm)
        assert summary_dir == summary_mm

    def test_vol_sizing_smaller_position_than_all_in(self, sample_df):
        """Vol sizing should produce a smaller position than all-in."""
        direction = pd.Series(-1, index=sample_df.index)
        direction.iloc[10:50] = 1
        config = MoneyManagementConfig(sizing_method="vol")

        trades_mm, _, _ = backtest_managed(sample_df, direction, config=config)
        trades_dir, _, _ = backtest_direction(sample_df, direction)

        assert len(trades_mm) == 1
        assert len(trades_dir) == 1
        assert trades_mm[0]["quantity"] < trades_dir[0]["quantity"]

    def test_vol_sizing_inversely_proportional_to_volatility(self):
        """Higher volatility should produce smaller position sizes."""
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        np.random.seed(42)

        # Low volatility data
        close_low = 100 + np.cumsum(np.random.randn(n) * 0.5)
        df_low = pd.DataFrame(
            {
                "Open": close_low + 0.1,
                "High": close_low + 0.5,
                "Low": close_low - 0.5,
                "Close": close_low,
                "Volume": np.full(n, 1_000_000),
            },
            index=idx,
        )

        # High volatility data
        np.random.seed(42)
        close_high = 100 + np.cumsum(np.random.randn(n) * 5.0)
        df_high = pd.DataFrame(
            {
                "Open": close_high + 0.1,
                "High": close_high + 2.5,
                "Low": close_high - 2.5,
                "Close": close_high,
                "Volume": np.full(n, 1_000_000),
            },
            index=idx,
        )

        direction = pd.Series(-1, index=idx)
        direction.iloc[110:150] = 1
        config = MoneyManagementConfig(sizing_method="vol")

        trades_low, _, _ = backtest_managed(df_low, direction, config=config)
        trades_high, _, _ = backtest_managed(df_high, direction, config=config)

        assert len(trades_low) == 1
        assert len(trades_high) == 1
        assert trades_low[0]["quantity"] > trades_high[0]["quantity"]

    def test_fixed_fraction_sizing(self, sample_df):
        """Fixed fraction should risk a fixed % of equity per trade."""
        direction = pd.Series(-1, index=sample_df.index)
        direction.iloc[10:50] = 1
        config = MoneyManagementConfig(
            sizing_method="fixed_fraction",
            risk_fraction=0.02,
            stop_type="atr",
            stop_atr_period=20,
            stop_atr_multiple=3.0,
        )

        trades, _, _ = backtest_managed(sample_df, direction, config=config)
        assert len(trades) == 1
        assert trades[0]["quantity"] < INITIAL_CAPITAL / trades[0]["entry_price"]

    def test_pct_stop_exits_on_low_breach(self):
        """Pct stop should trigger exit when low breaches stop price."""
        n = 50
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        np.random.seed(42)
        close = np.array([100 + np.random.randn() * 2 for _ in range(25)]
                         + [75.0] * 25)

        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 1_000_000),
            },
            index=idx,
        )

        direction = pd.Series(-1, index=idx)
        direction.iloc[5:45] = 1
        config = MoneyManagementConfig(
            sizing_method="fixed_fraction",
            risk_fraction=0.02,
            stop_type="pct",
            stop_pct=0.10,
        )

        trades, summary, _ = backtest_managed(df, direction, config=config)
        stopped_trades = [t for t in trades if not t.get("open")]
        assert len(stopped_trades) >= 1
        for t in stopped_trades:
            if t["exit_price"] < t["entry_price"]:
                loss_pct = abs(t["exit_price"] - t["entry_price"]) / t["entry_price"]
                assert loss_pct <= 0.15

    def test_trailing_stop_ratchets_up(self):
        """Trailing stop should move up with price, never down."""
        idx = pd.date_range("2024-01-01", periods=30, freq="D")
        prices = np.array([100 + i * 2 for i in range(20)] + [140 - i * 5 for i in range(10)])

        df = pd.DataFrame(
            {
                "Open": prices,
                "High": prices + 1,
                "Low": prices - 1,
                "Close": prices,
                "Volume": np.full(30, 1_000_000),
            },
            index=idx,
        )

        direction = pd.Series(1, index=idx)
        direction.iloc[0] = -1
        config = MoneyManagementConfig(
            sizing_method="vol",
            stop_type="pct",
            stop_pct=0.05,
        )

        trades, _, _ = backtest_managed(df, direction, config=config)
        stopped = [t for t in trades if not t.get("open")]
        if stopped:
            assert stopped[0]["exit_price"] > stopped[0]["entry_price"]

    def test_risk_to_stop_cap(self):
        """Risk-to-stop cap should limit position size."""
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 2)

        df = pd.DataFrame(
            {
                "Open": close + 0.1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 1_000_000),
            },
            index=idx,
        )

        direction = pd.Series(-1, index=idx)
        direction.iloc[110:150] = 1

        config_uncapped = MoneyManagementConfig(sizing_method="vol")
        config_capped = MoneyManagementConfig(
            sizing_method="vol",
            stop_type="atr",
            stop_atr_period=20,
            stop_atr_multiple=3.0,
            risk_to_stop_limit=0.005,
        )

        trades_uncapped, _, _ = backtest_managed(df, direction, config=config_uncapped)
        trades_capped, _, _ = backtest_managed(df, direction, config=config_capped)

        assert len(trades_uncapped) == 1
        assert len(trades_capped) == 1
        assert trades_capped[0]["quantity"] <= trades_uncapped[0]["quantity"]

    def test_vol_to_equity_cap(self):
        """Vol-to-equity cap should limit position size based on ATR."""
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 2)

        df = pd.DataFrame(
            {
                "Open": close + 0.1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 1_000_000),
            },
            index=idx,
        )

        direction = pd.Series(-1, index=idx)
        direction.iloc[110:150] = 1

        config_uncapped = MoneyManagementConfig(sizing_method="vol")
        config_capped = MoneyManagementConfig(
            sizing_method="vol",
            vol_to_equity_limit=0.005,
        )

        trades_uncapped, _, _ = backtest_managed(df, direction, config=config_uncapped)
        trades_capped, _, _ = backtest_managed(df, direction, config=config_capped)

        assert len(trades_uncapped) == 1
        assert len(trades_capped) == 1
        assert trades_capped[0]["quantity"] <= trades_uncapped[0]["quantity"]

    def test_monthly_compounding(self):
        """Sizing equity should only update at month boundaries."""
        idx = pd.bdate_range("2024-01-01", periods=200, freq="D")
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(200) * 2)

        df = pd.DataFrame(
            {
                "Open": close + 0.1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(200, 1_000_000),
            },
            index=idx,
        )

        direction = pd.Series(-1, index=idx)
        direction.iloc[10:30] = 1
        direction.iloc[50:70] = 1
        direction.iloc[100:130] = 1

        config_trade = MoneyManagementConfig(sizing_method="vol", compounding="trade")
        config_monthly = MoneyManagementConfig(sizing_method="vol", compounding="monthly")
        config_fixed = MoneyManagementConfig(sizing_method="vol", compounding="fixed")

        trades_trade, _, _ = backtest_managed(df, direction, config=config_trade)
        trades_monthly, _, _ = backtest_managed(df, direction, config=config_monthly)
        trades_fixed, _, _ = backtest_managed(df, direction, config=config_fixed)

        assert len(trades_trade) == 3
        assert len(trades_monthly) == 3
        assert len(trades_fixed) == 3
        qtys_fixed = [t["quantity"] for t in trades_fixed]
        qtys_trade = [t["quantity"] for t in trades_trade]
        assert qtys_fixed != qtys_trade

    def test_equity_curve_length_matches_df(self, sample_df):
        direction = pd.Series(-1, index=sample_df.index)
        direction.iloc[10:50] = 1
        config = MoneyManagementConfig(sizing_method="vol")
        _, _, equity = backtest_managed(sample_df, direction, config=config)
        assert len(equity) == len(sample_df)

    def test_no_trades_when_never_bullish(self, sample_df):
        direction = pd.Series(-1, index=sample_df.index)
        config = MoneyManagementConfig(sizing_method="vol")
        trades, summary, _ = backtest_managed(sample_df, direction, config=config)
        assert len(trades) == 0
        assert summary["total_trades"] == 0

    def test_margin_to_equity_cap(self):
        """Margin-to-equity cap should limit position size."""
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 2)

        df = pd.DataFrame(
            {
                "Open": close + 0.1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(n, 1_000_000),
            },
            index=idx,
        )

        direction = pd.Series(-1, index=idx)
        direction.iloc[110:150] = 1

        config = MoneyManagementConfig(
            sizing_method="vol",
            margin_to_equity_limit=0.1,
            margin_per_unit=50.0,
        )

        trades, _, _ = backtest_managed(df, direction, config=config)
        assert len(trades) == 1
        assert trades[0]["quantity"] <= (INITIAL_CAPITAL * 0.1) / 50.0 + 0.01
