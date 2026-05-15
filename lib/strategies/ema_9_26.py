from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from lib.technical_indicators import compute_ema_crossover

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


EMA_9_26_KEY = "ema_9_26"
EMA_9_26_LABEL = "EMA 9/26 Cross"

_FAST = 9
_SLOW = 26


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    return (
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
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def _align_to_daily(series: pd.Series, daily_index: pd.Index) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(0, index=daily_index, dtype=int)
    return series.reindex(daily_index).ffill().fillna(0).astype(int)


def compute_ema_9_26_strategy(df: pd.DataFrame) -> dict[str, pd.Series]:
    if df is None or df.empty:
        empty_index = pd.Index([])
        return {
            "ema_fast": pd.Series(index=empty_index, dtype=float),
            "ema_slow": pd.Series(index=empty_index, dtype=float),
            "daily_direction": pd.Series(index=empty_index, dtype=int),
            "weekly_direction": pd.Series(index=empty_index, dtype=int),
        }

    ema_fast, ema_slow, daily_direction = compute_ema_crossover(df, _FAST, _SLOW)
    weekly_df = _resample_weekly(df)
    _wf, _ws, weekly_raw_direction = compute_ema_crossover(weekly_df, _FAST, _SLOW)
    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "daily_direction": daily_direction.astype(int),
        "weekly_direction": _align_to_daily(weekly_raw_direction, df.index),
    }


def _compute(ctx: StrategyContext) -> StrategyResult:
    bundle = compute_ema_9_26_strategy(ctx.df)
    return StrategyResult(
        direction=bundle["daily_direction"],
        overlays={
            "ema_fast": bundle["ema_fast"],
            "ema_slow": bundle["ema_slow"],
        },
        metadata={
            "weekly_direction": bundle["weekly_direction"],
        },
    )


def _meta_extras(result: StrategyResult) -> Mapping[str, Any]:
    return {
        "architecture_label": EMA_9_26_LABEL,
        "architecture_hint": (
            "Medium-speed EMA crossover tuned for smoother index regimes, "
            "with optional weekly confirmation."
        ),
    }


STRATEGY = StrategyDef(
    key=EMA_9_26_KEY,
    label=EMA_9_26_LABEL,
    compute=_compute,
    backtest_engine=BacktestEngine.DIRECTION,
    supports_confirmation=True,
    is_experimental=True,
    meta_extras_from=_meta_extras,
)
