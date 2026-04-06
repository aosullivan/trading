"""Reusable ribbon direction signal computation.

Extracts the daily+weekly confirmed ribbon direction logic from routes/chart.py
so it can be shared by both the single-stock chart API and the portfolio engine.
"""

import pandas as pd

from lib.backtesting import build_weekly_confirmed_ribbon_direction
from lib.technical_indicators import compute_trend_ribbon
from lib.trend_ribbon_profile import (
    trend_ribbon_regime_kwargs,
    trend_ribbon_signal_kwargs,
)


def _resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    resampled = (
        df.sort_index()
        .resample("W-FRI")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
    )
    return resampled.dropna(subset=["Open", "Close"])


def _carry_neutral(direction: pd.Series) -> pd.Series:
    return direction.replace(0, pd.NA).ffill().fillna(0).astype(int)


def _align_weekly_to_daily(
    weekly_direction: pd.Series,
    daily_index: pd.Index,
) -> pd.Series:
    return weekly_direction.reindex(daily_index).ffill().fillna(0).astype(int)


def compute_confirmed_ribbon_direction(
    ticker: str,
    df: pd.DataFrame,
) -> pd.Series:
    """Compute the weekly-confirmed ribbon direction for a single ticker.

    Parameters
    ----------
    ticker : str
        Ticker symbol (used for profile overrides).
    df : pd.DataFrame
        Daily OHLCV with enough warmup bars before the desired backtest window.

    Returns
    -------
    pd.Series
        Integer direction series aligned to *df.index* (1=bull, -1=bear, 0=neutral).
    """
    daily_kwargs = trend_ribbon_signal_kwargs(ticker, timeframe="daily")
    _center, _upper, _lower, _strength, daily_ribbon_dir = compute_trend_ribbon(
        df, **daily_kwargs
    )

    df_w = _resample_to_weekly(df)
    if df_w.empty:
        return pd.Series(0, index=df.index, dtype=int)

    if isinstance(df_w.columns, pd.MultiIndex):
        df_w.columns = df_w.columns.get_level_values(0)
    if df_w.index.duplicated().any():
        df_w = df_w[~df_w.index.duplicated(keep="last")]

    weekly_kwargs = trend_ribbon_signal_kwargs(ticker, timeframe="weekly")
    _wc, _wu, _wl, _ws, weekly_ribbon_dir = compute_trend_ribbon(
        df_w, **weekly_kwargs
    )

    daily_carried = _carry_neutral(daily_ribbon_dir)
    weekly_aligned = _align_weekly_to_daily(weekly_ribbon_dir, df.index)

    regime_kw = trend_ribbon_regime_kwargs(ticker)
    confirmed = build_weekly_confirmed_ribbon_direction(
        daily_carried,
        weekly_aligned,
        reentry_cooldown_bars=regime_kw["reentry_cooldown_bars"],
        reentry_cooldown_ratio=regime_kw["reentry_cooldown_ratio"],
        weekly_nonbull_confirm_bars=regime_kw["weekly_nonbull_confirm_bars"],
    )
    return confirmed
