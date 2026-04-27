import pandas as pd

import lib.chart_serialization as chart_serialization


def test_summarize_direction_state_keeps_stable_current_regime_without_flip():
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    direction = pd.Series([0, 1, 1, 1], index=index)

    state = chart_serialization.summarize_direction_state(direction)

    assert state["current_dir"] == "bullish"
    assert state["current_state_date"] == "2026-01-04"
    assert state["regime_start_date"] == "2026-01-02"
    assert state["last_flip_date"] is None
    assert state["last_flip_dir"] is None


def test_compute_all_trend_flips_uses_backtest_strategy_inventory(monkeypatch, sample_df):
    def _series(value):
        return pd.Series([value] * len(sample_df), index=sample_df.index, dtype=int)

    monkeypatch.setattr(
        chart_serialization,
        "compute_trend_ribbon",
        lambda d, **kwargs: (None, None, None, None, _series(1)),
    )
    monkeypatch.setattr(
        chart_serialization,
        "compute_corpus_trend_signal",
        lambda d: (None, None, None, None, _series(1)),
    )
    monkeypatch.setattr(
        chart_serialization,
        "compute_supertrend_i",
        lambda d, period, multiplier: (None, _series(1)),
    )
    monkeypatch.setattr(
        chart_serialization,
        "_weekly_core_overlay_direction",
        lambda d, ticker: _series(-1),
    )
    monkeypatch.setattr(
        chart_serialization,
        "compute_bollinger_breakout",
        lambda d, period, std: (None, None, None, _series(1)),
    )
    monkeypatch.setattr(
        chart_serialization,
        "compute_ema_crossover",
        lambda d, fast, slow: (None, None, _series(-1)),
    )
    monkeypatch.setattr(
        chart_serialization,
        "compute_cci_trend",
        lambda d: (None, _series(1)),
    )
    monkeypatch.setattr(
        chart_serialization,
        "compute_cci_hysteresis",
        lambda d: (None, _series(-1)),
    )
    monkeypatch.setattr(
        chart_serialization,
        "compute_semis_persist_strategy",
        lambda d: {"daily_direction": _series(1)},
    )

    flips = chart_serialization.compute_all_trend_flips(sample_df, ticker="AAPL")

    assert set(flips) == {
        "ribbon",
        "corpus_trend",
        "corpus_trend_layered",
        "supertrend_i",
        "weekly_core_overlay_v1",
        "bb_breakout",
        "ema_crossover",
        "ema_9_26",
        "cci_trend",
        "cci_hysteresis",
        "semis_persist_v1",
    }
    assert flips["ribbon"]["dir"] == "bullish"
    assert flips["corpus_trend_layered"]["dir"] == "bullish"
    assert flips["weekly_core_overlay_v1"]["dir"] == "bearish"
    assert flips["ema_crossover"]["dir"] == "bearish"
    assert flips["ema_9_26"]["dir"] == "bearish"
    assert flips["semis_persist_v1"]["dir"] == "bullish"


def test_compute_all_trend_flips_only_includes_polymarket_for_btc(monkeypatch, sample_df):
    monkeypatch.setattr(
        chart_serialization,
        "compute_trend_ribbon",
        lambda d, **kwargs: (None, None, None, None, pd.Series([1] * len(d), index=d.index, dtype=int)),
    )
    monkeypatch.setattr(
        chart_serialization,
        "compute_corpus_trend_signal",
        lambda d: (None, None, None, None, pd.Series([1] * len(d), index=d.index, dtype=int)),
    )
    monkeypatch.setattr(chart_serialization, "compute_supertrend_i", lambda d, period, multiplier: (None, pd.Series([1] * len(d), index=d.index, dtype=int)))
    monkeypatch.setattr(chart_serialization, "_weekly_core_overlay_direction", lambda d, ticker: pd.Series([1] * len(d), index=d.index, dtype=int))
    monkeypatch.setattr(chart_serialization, "compute_bollinger_breakout", lambda d, period, std: (None, None, None, pd.Series([1] * len(d), index=d.index, dtype=int)))
    monkeypatch.setattr(chart_serialization, "compute_ema_crossover", lambda d, fast, slow: (None, None, pd.Series([1] * len(d), index=d.index, dtype=int)))
    monkeypatch.setattr(chart_serialization, "compute_cci_trend", lambda d: (None, pd.Series([1] * len(d), index=d.index, dtype=int)))
    monkeypatch.setattr(chart_serialization, "compute_cci_hysteresis", lambda d: (None, pd.Series([1] * len(d), index=d.index, dtype=int)))
    monkeypatch.setattr(chart_serialization, "compute_semis_persist_strategy", lambda d: {"daily_direction": pd.Series([1] * len(d), index=d.index, dtype=int)})
    monkeypatch.setattr(chart_serialization, "_polymarket_direction", lambda d, ticker: pd.Series([1] * len(d), index=d.index, dtype=int))

    aapl = chart_serialization.compute_all_trend_flips(sample_df, ticker="AAPL")
    btc = chart_serialization.compute_all_trend_flips(sample_df, ticker="BTC-USD")

    assert "polymarket" not in aapl
    assert btc["polymarket"]["dir"] == "bullish"
