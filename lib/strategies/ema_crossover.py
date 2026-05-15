from __future__ import annotations

from lib.technical_indicators import (
    EMA_FAST_PERIOD,
    EMA_SLOW_PERIOD,
    compute_ema_crossover,
)

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


def _compute(ctx: StrategyContext) -> StrategyResult:
    params = ctx.params
    ema_fast, ema_slow, direction = compute_ema_crossover(
        ctx.df,
        fast=params.get("fast", EMA_FAST_PERIOD),
        slow=params.get("slow", EMA_SLOW_PERIOD),
    )
    return StrategyResult(
        direction=direction,
        overlays={"ema_fast": ema_fast, "ema_slow": ema_slow},
    )


STRATEGY = StrategyDef(
    key="ema_crossover",
    label="EMA 5/20 Cross",
    compute=_compute,
    backtest_engine=BacktestEngine.DIRECTION,
    supports_confirmation=True,
    is_experimental=True,
    default_params={
        "fast": EMA_FAST_PERIOD,
        "slow": EMA_SLOW_PERIOD,
    },
)
