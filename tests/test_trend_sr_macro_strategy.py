from __future__ import annotations

import numpy as np
import pandas as pd

from lib.trend_sr_macro_strategy import compute_trend_sr_macro_strategy


def _synthetic_ohlcv() -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=260, freq="B")
    close = np.concatenate(
        [
            np.linspace(100.0, 168.0, 110),
            np.linspace(168.0, 148.0, 25),
            np.linspace(148.0, 192.0, 45),
            np.linspace(192.0, 122.0, 80),
        ]
    )
    open_ = np.concatenate([[close[0]], close[:-1]]) * 0.998
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    volume = np.full(len(index), 1_000_000)
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )


def test_trend_sr_macro_strategy_builds_stateful_daily_and_weekly_signals():
    df = _synthetic_ohlcv()
    treasury_history = pd.DataFrame(
        {"Close": np.linspace(4.6, 4.1, len(df))},
        index=df.index,
    )

    bundle = compute_trend_sr_macro_strategy(
        df,
        treasury_history=treasury_history,
    )

    daily_direction = bundle["daily_direction"]
    weekly_direction = bundle["weekly_direction"]

    assert len(daily_direction) == len(df)
    assert len(weekly_direction) == len(df)
    assert daily_direction.max() == 1
    assert weekly_direction.max() == 1
    assert int(daily_direction.iloc[-1]) == -1
    assert float(bundle["daily_bull_score"].max()) >= 60.0
    assert float(bundle["daily_bear_score"].max()) >= 55.0
    assert not bundle["macro_frame"].empty
    assert "regime_band" in bundle["macro_frame"].columns
