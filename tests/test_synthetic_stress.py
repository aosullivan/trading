import pandas as pd

from lib.synthetic_stress import (
    SyntheticStressScenario,
    apply_synthetic_stress,
    apply_synthetic_stress_to_frame,
    build_synthetic_stress_factor,
    compute_detection_lag_bars,
    compute_drawdown_capture_metrics,
)


def _frame(values, dates):
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "Open": values,
            "High": [value * 1.01 for value in values],
            "Low": [value * 0.99 for value in values],
            "Close": values,
            "Volume": [1000] * len(values),
        },
        index=index,
    )


def test_build_synthetic_stress_factor_hits_trough_and_recovery_levels():
    scenario = SyntheticStressScenario(
        id="test",
        label="Test",
        shock_start_offset_bars=2,
        shock_bars=2,
        trough_factor=0.60,
        hold_bars=1,
        recovery_bars=2,
        recovery_factor=0.90,
    )
    index = pd.date_range("2024-01-01", periods=8, freq="D")

    factor = build_synthetic_stress_factor(index, scenario)

    assert round(float(factor.iloc[0]), 2) == 1.00
    assert round(float(factor.iloc[3]), 2) == 0.60
    assert round(float(factor.iloc[-1]), 2) == 0.90


def test_apply_synthetic_stress_to_frame_scales_ohlc_and_preserves_ordering():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    frame = _frame([100.0, 100.0, 100.0, 100.0], dates)
    factor = pd.Series([1.0, 0.9, 0.8, 0.7], index=dates, dtype=float)

    stressed = apply_synthetic_stress_to_frame(frame, factor, volatility_boost=0.25)

    assert round(float(stressed.iloc[-1]["Close"]), 2) == 70.0
    assert (stressed["High"] >= stressed[["Open", "Close"]].max(axis=1)).all()
    assert (stressed["Low"] <= stressed[["Open", "Close"]].min(axis=1)).all()


def test_apply_synthetic_stress_uses_union_index_for_multi_ticker_panels():
    scenario = SyntheticStressScenario(
        id="test",
        label="Test",
        shock_start_offset_bars=1,
        shock_bars=2,
        trough_factor=0.50,
        hold_bars=0,
        recovery_bars=1,
        recovery_factor=0.80,
    )
    ticker_data = {
        "AAPL": _frame([100.0, 110.0, 120.0], ["2024-01-01", "2024-01-02", "2024-01-03"]),
        "MSFT": _frame([50.0, 55.0, 60.0], ["2024-01-02", "2024-01-03", "2024-01-04"]),
    }

    stressed, factor = apply_synthetic_stress(ticker_data, scenario)

    assert len(factor.index) == 4
    assert round(float(stressed["AAPL"].iloc[-1]["Close"]), 2) == 60.0
    assert round(float(stressed["MSFT"].iloc[-1]["Close"]), 2) == 48.0


def test_compute_detection_lag_bars_finds_first_risk_off_after_stress_start():
    index = pd.date_range("2024-01-01", periods=6, freq="D")
    factor = pd.Series([1.0, 1.0, 0.95, 0.85, 0.75, 0.70], index=index, dtype=float)
    regime_frame = pd.DataFrame(
        {"regime_band": ["neutral", "neutral", "neutral", "risk_off", "risk_off", "risk_off"]},
        index=index,
    )

    lag = compute_detection_lag_bars(regime_frame, factor)

    assert lag == 1


def test_compute_drawdown_capture_metrics_reports_saved_drawdown_and_lag():
    index = pd.date_range("2024-01-01", periods=5, freq="D")
    factor = pd.Series([1.0, 0.9, 0.8, 0.7, 0.6], index=index, dtype=float)
    regime_frame = pd.DataFrame(
        {"regime_band": ["neutral", "neutral", "risk_off", "risk_off", "risk_off"]},
        index=index,
    )

    metrics = compute_drawdown_capture_metrics(
        strategy_max_drawdown_pct=12.0,
        buy_hold_max_drawdown_pct=40.0,
        factor=factor,
        regime_frame=regime_frame,
    )

    assert metrics["downside_capture_pct"] == 30.0
    assert metrics["drawdown_saved_pct"] == 28.0
    assert metrics["modeled_drawdown_pct"] == 40.0
    assert metrics["protected_share_of_modeled_drawdown_pct"] == 70.0
    assert metrics["protection_lag_bars"] == 1
