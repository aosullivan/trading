import pandas as pd

from lib.macro_regime import (
    MacroRegimeConfig,
    build_benchmark_trend_frame,
    build_close_frame,
    build_macro_regime_frame,
    build_rate_feature_frame,
    classify_rate_environment,
    compute_forward_equal_weight_path,
    compute_path_metrics,
    election_cycle_phase,
    month_end_observation_dates,
)


def test_election_cycle_phase_labels_pre_election_and_election_years():
    assert election_cycle_phase("2023-05-01") == "pre_election"
    assert election_cycle_phase("2024-05-01") == "election"
    assert election_cycle_phase("2025-05-01") == "other"


def test_build_rate_feature_frame_computes_bps_changes():
    history = pd.DataFrame(
        {"Close": [4.50, 4.40, 4.10, 4.00]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
    )

    features = build_rate_feature_frame(history.index, treasury_history=history, lookbacks=(2,))

    assert round(float(features.loc[pd.Timestamp("2024-01-04"), "ust2y_change_bps_2"]), 2) == -40.0
    assert round(float(features.loc[pd.Timestamp("2024-01-05"), "ust2y_change_bps_2"]), 2) == -40.0


def test_classify_rate_environment_uses_reviewable_buckets():
    assert classify_rate_environment(-60) == "cuts_fast"
    assert classify_rate_environment(-20) == "cuts_priced"
    assert classify_rate_environment(0) == "flat"
    assert classify_rate_environment(25) == "hikes_or_no_cuts"
    assert classify_rate_environment(75) == "hikes_fast"


def test_build_macro_regime_frame_prefers_falling_yields_and_positive_breadth():
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    history = pd.DataFrame({"Close": [4.40, 4.20, 4.00]}, index=index)
    directions = {
        "AAPL": pd.Series([1, 1, 1], index=index),
        "MSFT": pd.Series([1, 1, 1], index=index),
        "NVDA": pd.Series([1, 0, 1], index=index),
    }
    config = MacroRegimeConfig(
        yield_lookback_bars=1,
        yield_good_bps=-10.0,
        yield_bad_bps=10.0,
        yield_weight=0.5,
        election_weight=0.25,
        breadth_weight=0.75,
        breadth_good_pct=0.60,
        breadth_bad_pct=0.30,
        risk_on_threshold=0.70,
        risk_off_threshold=-0.30,
    )

    frame = build_macro_regime_frame(index, directions, treasury_history=history, config=config)
    row = frame.iloc[-1]

    assert row["rate_bucket"] == "cuts_priced"
    assert row["election_cycle_phase"] == "election"
    assert row["bullish_pct"] > 0.60
    assert row["regime_band"] == "risk_on"
    assert row["passive_core_target_pct"] == config.risk_on_core_pct


def test_build_macro_regime_frame_penalizes_rising_yields_and_weak_breadth():
    index = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    history = pd.DataFrame({"Close": [4.00, 4.20, 4.45]}, index=index)
    directions = {
        "AAPL": pd.Series([0, 0, 0], index=index),
        "MSFT": pd.Series([0, 0, 0], index=index),
        "NVDA": pd.Series([1, 0, 0], index=index),
    }
    config = MacroRegimeConfig(
        yield_lookback_bars=1,
        yield_good_bps=-10.0,
        yield_bad_bps=10.0,
        yield_weight=0.6,
        election_weight=0.2,
        breadth_weight=0.8,
        breadth_good_pct=0.60,
        breadth_bad_pct=0.30,
        risk_on_threshold=0.75,
        risk_off_threshold=-0.25,
    )

    frame = build_macro_regime_frame(index, directions, treasury_history=history, config=config)
    row = frame.iloc[-1]

    assert row["rate_bucket"] == "hikes_or_no_cuts"
    assert row["election_cycle_phase"] == "other"
    assert row["bullish_pct"] == 0.0
    assert row["regime_band"] == "risk_off"
    assert row["passive_core_target_pct"] == config.risk_off_core_pct


def test_build_benchmark_trend_frame_and_macro_score_can_penalize_broken_basket_trend():
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    ticker_data = {
        "AAPL": pd.DataFrame({"Close": [100.0, 92.0, 84.0]}, index=index),
        "MSFT": pd.DataFrame({"Close": [100.0, 91.0, 82.0]}, index=index),
        "NVDA": pd.DataFrame({"Close": [100.0, 90.0, 80.0]}, index=index),
    }
    directions = {
        "AAPL": pd.Series([1, 0, 0], index=index),
        "MSFT": pd.Series([1, 0, 0], index=index),
        "NVDA": pd.Series([1, 0, 0], index=index),
    }
    benchmark = build_benchmark_trend_frame(index, ticker_data, lookbacks=(1,))
    config = MacroRegimeConfig(
        yield_lookback_bars=1,
        yield_good_bps=-10.0,
        yield_bad_bps=10.0,
        yield_weight=0.0,
        election_weight=0.0,
        breadth_weight=0.4,
        breadth_good_pct=0.60,
        breadth_bad_pct=0.30,
        benchmark_weight=1.0,
        benchmark_lookback_bars=1,
        benchmark_good_pct=3.0,
        benchmark_bad_pct=-3.0,
        risk_on_threshold=0.7,
        risk_off_threshold=-0.2,
    )
    history = pd.DataFrame({"Close": [4.0, 4.0, 4.0]}, index=index)

    frame = build_macro_regime_frame(
        index,
        directions,
        ticker_data=ticker_data,
        treasury_history=history,
        config=config,
    )
    row = frame.iloc[-1]

    assert round(float(benchmark.iloc[-1]["benchmark_trend_pct_1"]), 2) < -3.0
    assert row["benchmark_score"] < 0
    assert row["regime_band"] == "risk_off"


def test_build_close_frame_and_forward_path_metrics():
    ticker_data = {
        "AAPL": pd.DataFrame(
            {"Close": [100.0, 110.0, 120.0]},
            index=pd.to_datetime(["2024-01-02", "2024-01-10", "2024-01-20"]),
        ),
        "MSFT": pd.DataFrame(
            {"Close": [100.0, 120.0, 140.0]},
            index=pd.to_datetime(["2024-01-02", "2024-01-10", "2024-01-20"]),
        ),
        "NVDA": pd.DataFrame(
            {"Close": [100.0, 115.0, 130.0]},
            index=pd.to_datetime(["2024-01-02", "2024-01-10", "2024-01-20"]),
        ),
    }

    close_frame = build_close_frame(ticker_data)
    path = compute_forward_equal_weight_path(
        close_frame,
        pd.Timestamp("2024-01-02"),
        forward_days=30,
        min_tickers=3,
    )
    metrics = compute_path_metrics(path)

    assert list(close_frame.columns) == ["AAPL", "MSFT", "NVDA"]
    assert round(float(path.iloc[-1]), 2) == 130.0
    assert metrics["forward_return_pct"] == 30.0
    assert metrics["max_drawdown_pct"] == 0.0


def test_month_end_observation_dates_uses_last_available_date():
    index = pd.to_datetime(
        ["2024-01-02", "2024-01-31", "2024-02-01", "2024-02-28", "2024-03-15"]
    )

    dates = month_end_observation_dates(index)

    assert [value.strftime("%Y-%m-%d") for value in dates] == [
        "2024-01-31",
        "2024-02-28",
        "2024-03-15",
    ]
