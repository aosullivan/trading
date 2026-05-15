from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from lib.technical_indicators import compute_ema_crossover

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


SEMIS_PERSIST_KEY = "semis_persist_v1"
SEMIS_PERSIST_LABEL = "Semis Persist v1"

_CONTEXT_ENTRY_PERIOD = 55
_CONTEXT_EXIT_LOW_PERIOD = 20
_FAST_EMA = 30
_SLOW_EMA = 100
_EXIT_CONFIRM_BARS = 10


def compute_semis_persist_strategy(df: pd.DataFrame) -> dict[str, pd.Series]:
    if df is None or df.empty:
        empty_index = pd.Index([])
        return {
            "ema_fast": pd.Series(index=empty_index, dtype=float),
            "ema_slow": pd.Series(index=empty_index, dtype=float),
            "breakout_high": pd.Series(index=empty_index, dtype=float),
            "exit_low": pd.Series(index=empty_index, dtype=float),
            "daily_direction": pd.Series(index=empty_index, dtype=int),
        }

    close = df["Close"]
    low = df["Low"]
    ema_fast, ema_slow, base_direction = compute_ema_crossover(df, _FAST_EMA, _SLOW_EMA)
    breakout_high = close.rolling(_CONTEXT_ENTRY_PERIOD).max().shift(1)
    exit_low = low.rolling(_CONTEXT_EXIT_LOW_PERIOD).min().shift(1)

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
            if bearish_bars >= _EXIT_CONFIRM_BARS:
                in_position = False

        direction.iloc[i] = 1 if in_position else -1

    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "breakout_high": breakout_high,
        "exit_low": exit_low,
        "daily_direction": direction,
    }


def _compute(ctx: StrategyContext) -> StrategyResult:
    bundle = compute_semis_persist_strategy(ctx.df)
    return StrategyResult(
        direction=bundle["daily_direction"],
        overlays={
            "ema_fast": bundle["ema_fast"],
            "ema_slow": bundle["ema_slow"],
            "breakout_high": bundle["breakout_high"],
            "exit_low": bundle["exit_low"],
        },
    )


def _meta_extras(result: StrategyResult) -> Mapping[str, Any]:
    return {
        "confirmation_supported": False,
        "architecture_label": SEMIS_PERSIST_LABEL,
        "architecture_hint": (
            "Semis-tuned persistence: a slower 30/100 EMA trend stack gets the "
            "basket risk-on, then exits only after 10 straight bearish bars so "
            "leadership names have more room to keep running."
        ),
    }


STRATEGY = StrategyDef(
    key=SEMIS_PERSIST_KEY,
    label=SEMIS_PERSIST_LABEL,
    compute=_compute,
    backtest_engine=BacktestEngine.DIRECTION,
    supports_confirmation=False,
    is_experimental=True,
    meta_extras_from=_meta_extras,
)
