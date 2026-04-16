import pandas as pd

from lib.specialized_strategies import (
    EMA_9_26_KEY,
    SEMIS_PERSIST_KEY,
    compute_ema_9_26_strategy,
    compute_semis_persist_strategy,
    specialized_strategy_backtest_meta,
)


def test_compute_ema_9_26_strategy_builds_daily_and_weekly_direction(sample_df):
    bundle = compute_ema_9_26_strategy(sample_df)

    assert list(bundle) == ["ema_fast", "ema_slow", "daily_direction", "weekly_direction"]
    assert bundle["daily_direction"].index.equals(sample_df.index)
    assert bundle["weekly_direction"].index.equals(sample_df.index)
    assert set(bundle["daily_direction"].dropna().astype(int).unique()).issubset({-1, 0, 1})
    assert set(bundle["weekly_direction"].dropna().astype(int).unique()).issubset({-1, 0, 1})


def test_compute_semis_persist_strategy_holds_breakouts_until_confirmed_failure():
    dates = pd.bdate_range("2024-01-01", periods=320)
    uptrend = pd.Series(range(320), index=dates, dtype=float)
    close = 100 + uptrend
    close.iloc[-30:] = [
        380, 378, 376, 374, 372, 370, 368, 366, 364, 362,
        340, 330, 320, 310, 300, 290, 280, 270, 260, 250,
        240, 230, 220, 210, 205, 200, 195, 190, 185, 180,
    ]
    df = pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 3,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )

    bundle = compute_semis_persist_strategy(df)

    assert bundle["daily_direction"].index.equals(df.index)
    assert bundle["daily_direction"].iloc[240] == 1
    assert bundle["daily_direction"].iloc[-1] == -1
    assert bundle["daily_direction"].iloc[-15] == 1


def test_specialized_strategy_backtest_meta_exposes_expected_hints():
    ema_meta = specialized_strategy_backtest_meta(EMA_9_26_KEY)
    semis_meta = specialized_strategy_backtest_meta(SEMIS_PERSIST_KEY)

    assert "weekly confirmation" in ema_meta["architecture_hint"].lower()
    assert semis_meta["confirmation_supported"] is False
    assert "30/100 ema trend stack" in semis_meta["architecture_hint"].lower()
