from __future__ import annotations

from lib.technical_indicators import (
    BOLLINGER_PERIOD,
    BOLLINGER_STD_DEV,
    compute_bollinger_breakout,
)

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


def _compute(ctx: StrategyContext) -> StrategyResult:
    params = ctx.params
    upper, middle, lower, direction = compute_bollinger_breakout(
        ctx.df,
        period=params.get("period", BOLLINGER_PERIOD),
        std_dev=params.get("std_dev", BOLLINGER_STD_DEV),
    )
    return StrategyResult(
        direction=direction,
        overlays={"upper": upper, "middle": middle, "lower": lower},
    )


STRATEGY = StrategyDef(
    key="bb_breakout",
    label="BB Breakout (30/1.5)",
    compute=_compute,
    backtest_engine=BacktestEngine.DIRECTION,
    supports_confirmation=True,
    is_experimental=True,
    default_params={
        "period": BOLLINGER_PERIOD,
        "std_dev": BOLLINGER_STD_DEV,
    },
)
