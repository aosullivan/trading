import pandas as pd

from lib.trade_setup import compute_trade_setup
from lib.strategy_preferences import preferred_strategy_for_ticker, ticker_category


def test_compute_trade_setup_reports_nearest_levels_and_trade_scores(sample_df):
    weekly_df = sample_df.resample("W-FRI").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    ).dropna(subset=["Open", "High", "Low", "Close"])

    daily_flips = {
        "ribbon": {"current_dir": "bullish"},
        "corpus_trend": {"current_dir": "bullish"},
        "corpus_trend_layered": {"current_dir": "bullish"},
        "weekly_core_overlay_v1": {"current_dir": "bullish"},
        "cci_hysteresis": {"current_dir": "bullish"},
        "bb_breakout": {"current_dir": "bullish"},
        "ema_crossover": {"current_dir": "bullish"},
        "cci_trend": {"current_dir": "bullish"},
    }
    weekly_flips = {
        "ribbon": {"current_dir": "bearish"},
        "corpus_trend": {"current_dir": "bearish"},
        "corpus_trend_layered": {"current_dir": "bearish"},
        "weekly_core_overlay_v1": {"current_dir": "bearish"},
        "cci_hysteresis": {"current_dir": "bearish"},
        "bb_breakout": {"current_dir": "bearish"},
        "ema_crossover": {"current_dir": "bearish"},
        "cci_trend": {"current_dir": "bearish"},
    }

    payload = compute_trade_setup(sample_df, weekly_df, daily_flips, weekly_flips)

    assert set(payload) == {"daily", "weekly", "shared"}
    assert payload["daily"]["side"] == "bullish"
    assert payload["daily"]["score"] > 0
    assert payload["daily"]["breakdown"]["components"][0]["label"] == "Trend bias"
    assert payload["daily"]["breakdown"]["bonus"] is not None
    assert payload["daily"]["breakdown"]["highlights"]
    assert [item["key"] for item in payload["daily"]["action_strength"]["items"]] == [
        "direction_confidence",
        "entry_location_quality",
        "risk_reward_room",
        "strategy_agreement",
    ]
    assert payload["daily"]["action_strength"]["items"][0]["score"] == 100
    assert payload["daily"]["action_strength"]["items"][3]["score"] == 100
    assert payload["weekly"]["side"] == "bearish"
    assert payload["weekly"]["score"] < 0
    assert payload["weekly"]["breakdown"]["components"][1]["label"] == "Support / resistance"

    shared = payload["shared"]
    assert shared["price"] == round(float(sample_df["Close"].iloc[-1]), 2)
    assert shared["nearest_support"] is not None
    assert shared["nearest_resistance"] is not None
    assert shared["nearest_ma"] is not None
    assert shared["nearest_ma"]["label"] in {"SMA 50", "SMA 100", "SMA 200", "50W MA", "100W MA", "200W MA"}
    assert shared["upside_room_pct"] is not None
    assert shared["downside_room_pct"] is not None


def test_compute_trade_setup_returns_mixed_score_when_bias_is_neutral(sample_df):
    payload = compute_trade_setup(sample_df, pd.DataFrame(), {}, {})

    assert payload["daily"]["side"] == "mixed"
    assert payload["weekly"]["side"] == "mixed"
    assert payload["daily"]["score"] == 0
    assert payload["weekly"]["score"] == 0
    assert payload["daily"]["breakdown"]["summary"] == "Trade score stays muted because weighted strategy bias is mixed."
    assert payload["daily"]["breakdown"]["bonus"] is None
    assert payload["daily"]["action_strength"]["items"][1]["score"] == 0.0
    assert payload["daily"]["action_strength"]["items"][3]["score"] == 0.0
    assert payload["shared"]["nearest_ma"] is not None


def test_compute_trade_setup_uses_preferred_strategy_bias_when_ticker_is_provided(sample_df):
    weekly_df = sample_df.resample("W-FRI").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    ).dropna(subset=["Open", "High", "Low", "Close"])

    daily_flips = {
        "cci_trend": {"current_dir": "bullish"},
        "ribbon": {"current_dir": "bearish"},
        "ema_crossover": {"current_dir": "bearish"},
    }
    weekly_flips = {
        "cci_trend": {"current_dir": "bearish"},
        "ribbon": {"current_dir": "bullish"},
        "ema_crossover": {"current_dir": "bullish"},
    }

    payload = compute_trade_setup(sample_df, weekly_df, daily_flips, weekly_flips, ticker="BTC-USD")

    assert payload["shared"]["preferred_strategy"]["category"] == "crypto"
    assert payload["shared"]["preferred_strategy"]["strategy_key"] == "cci_trend"
    assert payload["daily"]["trend_bias"] == 100
    assert payload["daily"]["side"] == "bullish"
    assert payload["weekly"]["trend_bias"] == -100
    assert payload["weekly"]["side"] == "bearish"
    assert "cci trend" in payload["daily"]["trend_source_label"].lower()


def test_strategy_preferences_route_known_classes_to_expected_strategies():
    assert ticker_category("BTC-USD") == "crypto"
    assert ticker_category("CRWD") == "software"
    assert ticker_category("ZS") == "software"
    assert preferred_strategy_for_ticker("BTC-USD")["strategy_key"] == "cci_trend"
    assert preferred_strategy_for_ticker("CRWD")["strategy_key"] == "trend_sr_macro_v1"
    assert preferred_strategy_for_ticker("ZS")["strategy_key"] == "trend_sr_macro_v1"
    assert preferred_strategy_for_ticker("NVDA")["strategy_key"] == "semis_persist_v1"
    assert preferred_strategy_for_ticker("SPX")["strategy_key"] == "ema_9_26"


def test_compute_trade_setup_falls_back_to_weighted_bias_when_preferred_strategy_key_is_missing(sample_df):
    weekly_df = sample_df.resample("W-FRI").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    ).dropna(subset=["Open", "High", "Low", "Close"])

    daily_flips = {
        "ribbon": {"current_dir": "bearish"},
        "ema_crossover": {"current_dir": "bearish"},
        "cci_trend": {"current_dir": "bullish"},
    }
    weekly_flips = {
        "ribbon": {"current_dir": "bearish"},
        "ema_crossover": {"current_dir": "bearish"},
        "cci_trend": {"current_dir": "bearish"},
    }

    payload = compute_trade_setup(sample_df, weekly_df, daily_flips, weekly_flips, ticker="CRWD")

    assert payload["shared"]["preferred_strategy"]["strategy_key"] == "trend_sr_macro_v1"
    assert payload["daily"]["trend_bias"] < 0
    assert payload["weekly"]["trend_bias"] < 0
    assert payload["daily"]["score"] < 0
    assert payload["weekly"]["score"] < 0
    assert "fallback" in payload["daily"]["trend_source_label"].lower()
