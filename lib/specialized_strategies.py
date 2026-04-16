from __future__ import annotations

import pandas as pd

from lib.technical_indicators import compute_ema_crossover


EMA_9_26_KEY = "ema_9_26"
EMA_9_26_LABEL = "EMA 9/26 Cross"
SEMIS_PERSIST_KEY = "semis_persist_v1"
SEMIS_PERSIST_LABEL = "Semis Persist v1"

_EMA_9_26_FAST = 9
_EMA_9_26_SLOW = 26
_SEMIS_CONTEXT_ENTRY_PERIOD = 55
_SEMIS_CONTEXT_EXIT_LOW_PERIOD = 20
_SEMIS_FAST_EMA = 30
_SEMIS_SLOW_EMA = 100
_SEMIS_EXIT_CONFIRM_BARS = 10


def _empty_float(index: pd.Index) -> pd.Series:
    return pd.Series(index=index, dtype=float)


def _empty_int(index: pd.Index) -> pd.Series:
    return pd.Series(index=index, dtype=int)


def _resample_ohlcv(df: pd.DataFrame, rule: str = "W-FRI") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    return (
        df.sort_index()
        .resample(rule)
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
            "ema_fast": _empty_float(empty_index),
            "ema_slow": _empty_float(empty_index),
            "daily_direction": _empty_int(empty_index),
            "weekly_direction": _empty_int(empty_index),
        }

    ema_fast, ema_slow, daily_direction = compute_ema_crossover(
        df,
        _EMA_9_26_FAST,
        _EMA_9_26_SLOW,
    )
    weekly_df = _resample_ohlcv(df)
    _weekly_fast, _weekly_slow, weekly_raw_direction = compute_ema_crossover(
        weekly_df,
        _EMA_9_26_FAST,
        _EMA_9_26_SLOW,
    )
    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "daily_direction": daily_direction.astype(int),
        "weekly_direction": _align_to_daily(weekly_raw_direction, df.index),
    }


def compute_semis_persist_strategy(df: pd.DataFrame) -> dict[str, pd.Series]:
    if df is None or df.empty:
        empty_index = pd.Index([])
        return {
            "ema_fast": _empty_float(empty_index),
            "ema_slow": _empty_float(empty_index),
            "breakout_high": _empty_float(empty_index),
            "exit_low": _empty_float(empty_index),
            "daily_direction": _empty_int(empty_index),
        }

    close = df["Close"]
    low = df["Low"]
    ema_fast, ema_slow, base_direction = compute_ema_crossover(
        df,
        _SEMIS_FAST_EMA,
        _SEMIS_SLOW_EMA,
    )
    breakout_high = close.rolling(_SEMIS_CONTEXT_ENTRY_PERIOD).max().shift(1)
    exit_low = low.rolling(_SEMIS_CONTEXT_EXIT_LOW_PERIOD).min().shift(1)

    direction = pd.Series(-1, index=df.index, dtype=int)
    in_position = False
    bearish_bars = 0

    for i in range(len(df)):
        signal = int(base_direction.iloc[i]) if not pd.isna(base_direction.iloc[i]) else 0
        if signal == 0:
            direction.iloc[i] = 0
            continue

        if not in_position:
            if signal == 1:
                in_position = True
                bearish_bars = 0
        else:
            if signal == 1:
                bearish_bars = 0
            else:
                bearish_bars += 1
            if bearish_bars >= _SEMIS_EXIT_CONFIRM_BARS:
                in_position = False

        direction.iloc[i] = 1 if in_position else -1

    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "breakout_high": breakout_high,
        "exit_low": exit_low,
        "daily_direction": direction,
    }


def specialized_strategy_backtest_meta(strategy_key: str) -> dict[str, object]:
    if strategy_key == EMA_9_26_KEY:
        return {
            "architecture_label": EMA_9_26_LABEL,
            "architecture_hint": "Medium-speed EMA crossover tuned for smoother index regimes, with optional weekly confirmation.",
        }
    if strategy_key == SEMIS_PERSIST_KEY:
        return {
            "confirmation_supported": False,
            "architecture_label": SEMIS_PERSIST_LABEL,
            "architecture_hint": "Semis-tuned persistence: a slower 30/100 EMA trend stack gets the basket risk-on, then exits only after 10 straight bearish bars so leadership names have more room to keep running.",
        }
    return {}
