import numpy as np
import pandas as pd

from lib.mu_atr_mr_strategy import (
    MU_ATR_MR_LOOKBACK,
    compute_mu_atr_mr_strategy,
    compute_mu_atr_zscore,
)


def test_compute_mu_atr_mr_strategy_returns_expected_keys(sample_df):
    bundle = compute_mu_atr_mr_strategy(sample_df)

    assert list(bundle) == ["sma", "atr", "zscore", "daily_direction"]
    for key in ("sma", "atr", "zscore", "daily_direction"):
        assert bundle[key].index.equals(sample_df.index)
    assert set(bundle["daily_direction"].dropna().astype(int).unique()).issubset({-1, 1})


def test_compute_mu_atr_mr_strategy_handles_empty_df():
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    bundle = compute_mu_atr_mr_strategy(empty)
    for key in ("sma", "atr", "zscore", "daily_direction"):
        assert bundle[key].empty


def test_zscore_centered_around_zero_for_random_walk(sample_df):
    _sma, _atr, z = compute_mu_atr_zscore(sample_df)
    assert abs(z.dropna().mean()) < 1.0
    assert z.dropna().abs().max() > 0.5


def test_strategy_enters_after_dip_and_upturn():
    """A V-shape: drift down to push z below -0.4, then rebound. Direction
    should flip to long on the bar where z first ticks up from its trough."""
    n = 200
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = np.concatenate([
        np.linspace(100.0, 100.0, MU_ATR_MR_LOOKBACK),
        np.linspace(100.0, 80.0, 60),
        np.linspace(80.0, 110.0, n - MU_ATR_MR_LOOKBACK - 60),
    ])
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )

    bundle = compute_mu_atr_mr_strategy(df)
    direction = bundle["daily_direction"]
    z = bundle["zscore"]

    assert (z.dropna() <= -0.4).any(), "test data should produce a deep dip"
    assert (direction == 1).any(), "should enter long after dip + upturn"
    last_long = direction.where(direction == 1).last_valid_index()
    assert last_long is not None
    assert direction.iloc[-1] in (1, -1)


def test_strategy_long_only():
    """Direction should never be 0; values are 1 (long) or -1 (flat)."""
    np.random.seed(7)
    n = 400
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = 100 + np.cumsum(np.random.randn(n) * 1.5)
    high = close + np.abs(np.random.randn(n)) * 0.8
    low = close - np.abs(np.random.randn(n)) * 0.8
    df = pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": 1},
        index=dates,
    )

    direction = compute_mu_atr_mr_strategy(df)["daily_direction"]
    assert set(direction.unique()).issubset({-1, 1})
