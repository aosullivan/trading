from __future__ import annotations

import json
from typing import Any, Mapping

import pandas as pd

from lib.backtesting import build_weekly_confirmed_ribbon_direction
from lib.technical_indicators import compute_trend_ribbon

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


# ---------------------------------------------------------------------------
# Ticker-aware profile defaults
# ---------------------------------------------------------------------------

TREND_RIBBON_SIGNAL_PROFILE = {
    "ema_period": 34,
    "atr_period": 14,
    "fast_period": 8,
    "slow_period": 34,
    "smooth_period": 8,
    "collapse_threshold": 0.06,
    "expand_threshold": 0.15,
    "bull_expand_threshold": 0.22,
    "bear_expand_threshold": 0.15,
    "bull_confirm_bars": 2,
    "bear_confirm_bars": 1,
}

TREND_RIBBON_WEEKLY_SIGNAL_PROFILE = {
    "ema_period": 34,
    "atr_period": 14,
    "fast_period": 8,
    "slow_period": 34,
    "smooth_period": 8,
    "collapse_threshold": 0.06,
    "expand_threshold": 0.15,
    "bull_expand_threshold": 0.22,
    "bear_expand_threshold": 0.15,
    "bull_confirm_bars": 1,
    "bear_confirm_bars": 1,
}

TREND_RIBBON_REGIME_PROFILE = {
    "reentry_cooldown_bars": 0,
    "reentry_cooldown_ratio": 0.05,
    "weekly_nonbull_confirm_bars": 1,
    "asymmetric_exit": True,
}

TREND_RIBBON_BACKTEST_PROFILE = {
    "daily_add_capital": 3000.0,
    "weekly_add_capital": 0.0,
    "max_capital": 120000.0,
    "daily_sell_fraction": 0.05,
    "weekly_sell_fraction": 0.75,
}

# Per-ticker overrides for any of the sections above. Empty by default; populated
# during research when a ticker benefits from non-default params.
TREND_RIBBON_TICKER_OVERRIDES: dict[str, dict[str, dict]] = {}


def _apply_overrides(profile: dict, ticker: str | None, section: str) -> dict:
    result = dict(profile)
    overrides = TREND_RIBBON_TICKER_OVERRIDES.get((ticker or "").upper(), {})
    result.update(overrides.get(section, {}))
    return result


def trend_ribbon_signal_kwargs(
    ticker: str | None = None,
    timeframe: str = "daily",
) -> dict[str, int | float]:
    section = "weekly_signal" if timeframe == "weekly" else "signal"
    base = TREND_RIBBON_WEEKLY_SIGNAL_PROFILE if timeframe == "weekly" else TREND_RIBBON_SIGNAL_PROFILE
    return _apply_overrides(base, ticker, section)


def trend_ribbon_backtest_kwargs(ticker: str | None = None) -> dict[str, float]:
    return _apply_overrides(TREND_RIBBON_BACKTEST_PROFILE, ticker, "backtest")


def trend_ribbon_regime_kwargs(ticker: str | None = None) -> dict[str, int | float]:
    return _apply_overrides(TREND_RIBBON_REGIME_PROFILE, ticker, "regime")


def trend_ribbon_profile_signature(ticker: str | None = None) -> str:
    payload = {
        "signal": trend_ribbon_signal_kwargs(ticker, "daily"),
        "weekly_signal": trend_ribbon_signal_kwargs(ticker, "weekly"),
        "backtest": trend_ribbon_backtest_kwargs(ticker),
        "regime": trend_ribbon_regime_kwargs(ticker),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Resampling + alignment helpers
# ---------------------------------------------------------------------------


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


def _align_weekly_to_daily(weekly: pd.Series, daily_index: pd.Index) -> pd.Series:
    return weekly.reindex(daily_index).ffill().fillna(0).astype(int)


def _carry_neutral(direction: pd.Series) -> pd.Series:
    return direction.replace(0, pd.NA).ffill().fillna(0).astype(int)


# ---------------------------------------------------------------------------
# Public compute helpers
# ---------------------------------------------------------------------------


def compute_confirmed_ribbon_direction(ticker: str, df: pd.DataFrame) -> pd.Series:
    """Daily + weekly ribbon confirmation rolled into a single direction series.

    Used by the portfolio path and research scripts where the engine is not
    invoked directly. The chart route gets the same view via the RIBBON_REGIME
    backtest engine on the raw daily direction.
    """
    daily_kwargs = trend_ribbon_signal_kwargs(ticker, timeframe="daily")
    _c, _u, _l, _s, daily_dir = compute_trend_ribbon(df, **daily_kwargs)

    df_w = _resample_to_weekly(df)
    if df_w.empty:
        return pd.Series(0, index=df.index, dtype=int)
    if isinstance(df_w.columns, pd.MultiIndex):
        df_w.columns = df_w.columns.get_level_values(0)
    if df_w.index.duplicated().any():
        df_w = df_w[~df_w.index.duplicated(keep="last")]

    weekly_kwargs = trend_ribbon_signal_kwargs(ticker, timeframe="weekly")
    _wc, _wu, _wl, _ws, weekly_dir = compute_trend_ribbon(df_w, **weekly_kwargs)

    daily_carried = _carry_neutral(daily_dir)
    weekly_aligned = _align_weekly_to_daily(weekly_dir, df.index)

    regime = trend_ribbon_regime_kwargs(ticker)
    return build_weekly_confirmed_ribbon_direction(
        daily_carried,
        weekly_aligned,
        reentry_cooldown_bars=regime["reentry_cooldown_bars"],
        reentry_cooldown_ratio=regime["reentry_cooldown_ratio"],
        weekly_nonbull_confirm_bars=regime["weekly_nonbull_confirm_bars"],
        asymmetric_exit=regime.get("asymmetric_exit", False),
    )


# ---------------------------------------------------------------------------
# Strategy definition
# ---------------------------------------------------------------------------


def _compute(ctx: StrategyContext) -> StrategyResult:
    df = ctx.df
    ticker = ctx.ticker
    daily_kwargs = trend_ribbon_signal_kwargs(ticker, timeframe="daily")
    center, upper, lower, strength, daily_direction = compute_trend_ribbon(df, **daily_kwargs)

    weekly_df = _resample_to_weekly(df)
    if weekly_df.empty:
        weekly_aligned = pd.Series(0, index=df.index, dtype=int)
    else:
        if isinstance(weekly_df.columns, pd.MultiIndex):
            weekly_df.columns = weekly_df.columns.get_level_values(0)
        if weekly_df.index.duplicated().any():
            weekly_df = weekly_df[~weekly_df.index.duplicated(keep="last")]
        weekly_kwargs = trend_ribbon_signal_kwargs(ticker, timeframe="weekly")
        _wc, _wu, _wl, _ws, weekly_direction = compute_trend_ribbon(weekly_df, **weekly_kwargs)
        weekly_aligned = _align_weekly_to_daily(weekly_direction, df.index)

    regime = trend_ribbon_regime_kwargs(ticker)

    return StrategyResult(
        direction=_carry_neutral(daily_direction),
        overlays={
            "center": center,
            "upper": upper,
            "lower": lower,
            "strength": strength,
        },
        metadata={
            "weekly_direction": weekly_aligned,
            "regime_kwargs": dict(regime),
        },
    )


def _engine_kwargs(result: StrategyResult) -> Mapping[str, Any]:
    regime = result.metadata["regime_kwargs"]
    return {
        "weekly_direction": result.metadata["weekly_direction"],
        "reentry_cooldown_bars": regime["reentry_cooldown_bars"],
        "reentry_cooldown_ratio": regime["reentry_cooldown_ratio"],
        "weekly_nonbull_confirm_bars": regime["weekly_nonbull_confirm_bars"],
        "asymmetric_exit": regime.get("asymmetric_exit", False),
    }


STRATEGY = StrategyDef(
    key="ribbon",
    label="Trend-Driven",
    compute=_compute,
    backtest_engine=BacktestEngine.RIBBON_REGIME,
    supports_confirmation=True,
    is_experimental=False,
    backtest_kwargs_from=_engine_kwargs,
    include_buy_hold_in_payload=True,
)
