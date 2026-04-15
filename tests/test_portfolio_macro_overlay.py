import pandas as pd

from lib.macro_regime import MacroRegimeConfig
from lib.portfolio_backtesting import backtest_portfolio_macro_overlay


def _frame(values, dates):
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "Open": values,
            "High": values,
            "Low": values,
            "Close": values,
            "Volume": [0] * len(values),
        },
        index=index,
    )


def test_macro_overlay_matches_buy_hold_when_core_is_full():
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    ticker_data = {"AAPL": _frame([100.0, 110.0, 120.0, 130.0], dates)}
    directions = {"AAPL": pd.Series([0, 0, 0, 0], index=pd.to_datetime(dates))}
    treasury = pd.DataFrame({"Close": [4.0, 4.0, 4.0, 4.0]}, index=pd.to_datetime(dates))
    config = MacroRegimeConfig(
        yield_lookback_bars=1,
        risk_on_core_pct=1.0,
        neutral_core_pct=1.0,
        risk_off_core_pct=1.0,
    )

    result = backtest_portfolio_macro_overlay(
        ticker_data,
        directions,
        macro_config=config,
        treasury_history=treasury,
    )

    assert result.portfolio_equity_curve == result.portfolio_buy_hold_curve
    assert result.portfolio_summary["net_profit_pct"] == 30.0
    assert result.portfolio_diagnostics["avg_passive_core_pct"] == 100.0


def test_macro_overlay_matches_tactical_when_core_is_zero():
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    ticker_data = {"AAPL": _frame([100.0, 110.0, 120.0, 130.0], dates)}
    directions = {"AAPL": pd.Series([0, 0, 0, 0], index=pd.to_datetime(dates))}
    treasury = pd.DataFrame({"Close": [4.0, 4.0, 4.0, 4.0]}, index=pd.to_datetime(dates))
    config = MacroRegimeConfig(
        yield_lookback_bars=1,
        risk_on_core_pct=0.0,
        neutral_core_pct=0.0,
        risk_off_core_pct=0.0,
    )

    result = backtest_portfolio_macro_overlay(
        ticker_data,
        directions,
        macro_config=config,
        treasury_history=treasury,
    )

    assert result.portfolio_summary["net_profit_pct"] == 0.0
    assert result.portfolio_equity_curve[-1]["value"] == 10000.0
    assert result.portfolio_diagnostics["avg_passive_core_pct"] == 0.0


def test_macro_overlay_reports_regime_band_diagnostics():
    dates = ["2024-10-28", "2024-10-29", "2024-10-30", "2024-10-31", "2024-11-01"]
    ticker_data = {"AAPL": _frame([100.0, 102.0, 101.0, 104.0, 106.0], dates)}
    directions = {"AAPL": pd.Series([1, 1, 0, 1, 1], index=pd.to_datetime(dates))}
    treasury = pd.DataFrame({"Close": [4.8, 4.4, 4.9, 5.1, 5.4]}, index=pd.to_datetime(dates))
    config = MacroRegimeConfig(
        yield_lookback_bars=1,
        yield_good_bps=-15.0,
        yield_bad_bps=15.0,
        yield_weight=0.6,
        election_weight=0.25,
        breadth_weight=0.75,
        breadth_good_pct=0.75,
        breadth_bad_pct=0.25,
        risk_on_threshold=0.7,
        risk_off_threshold=-0.2,
        risk_on_core_pct=0.85,
        neutral_core_pct=0.55,
        risk_off_core_pct=0.25,
    )

    result = backtest_portfolio_macro_overlay(
        ticker_data,
        directions,
        macro_config=config,
        treasury_history=treasury,
    )

    diagnostics = result.portfolio_diagnostics

    assert diagnostics["overlay_policy"] == "macro_core_overlay_v1"
    assert diagnostics["risk_on_bars"] >= 1
    assert diagnostics["risk_off_bars"] >= 1
    assert diagnostics["avg_passive_core_pct"] > diagnostics["min_passive_core_pct"]
    assert diagnostics["max_passive_core_pct"] == 85.0


def test_macro_overlay_can_reduce_core_when_benchmark_trend_breaks():
    dates = [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
    ]
    ticker_data = {
        "AAPL": _frame([100.0, 95.0, 88.0, 82.0, 78.0], dates),
        "MSFT": _frame([100.0, 94.0, 87.0, 81.0, 77.0], dates),
        "NVDA": _frame([100.0, 93.0, 85.0, 79.0, 74.0], dates),
    }
    directions = {
        ticker: pd.Series([1, 1, 0, 0, 0], index=pd.to_datetime(dates))
        for ticker in ticker_data
    }
    treasury = pd.DataFrame({"Close": [4.0, 4.0, 4.0, 4.0, 4.0]}, index=pd.to_datetime(dates))
    config = MacroRegimeConfig(
        yield_lookback_bars=1,
        yield_weight=0.0,
        election_weight=0.0,
        breadth_weight=0.3,
        breadth_good_pct=0.75,
        breadth_bad_pct=0.25,
        benchmark_weight=1.0,
        benchmark_lookback_bars=1,
        benchmark_good_pct=2.0,
        benchmark_bad_pct=-2.0,
        risk_on_threshold=0.7,
        risk_off_threshold=-0.2,
        risk_on_core_pct=0.9,
        neutral_core_pct=0.6,
        risk_off_core_pct=0.1,
    )

    result = backtest_portfolio_macro_overlay(
        ticker_data,
        directions,
        macro_config=config,
        treasury_history=treasury,
    )

    diagnostics = result.portfolio_diagnostics

    assert diagnostics["risk_off_bars"] >= 1
    assert diagnostics["min_passive_core_pct"] == 10.0
