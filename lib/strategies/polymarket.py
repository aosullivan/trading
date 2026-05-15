from __future__ import annotations

from lib.polymarket import compute_polymarket_direction_series

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


def _compute(ctx: StrategyContext) -> StrategyResult:
    params = ctx.params
    direction = compute_polymarket_direction_series(
        ctx.df,
        probability_history_df=params.get("probability_history_df"),
    )
    return StrategyResult(direction=direction)


STRATEGY = StrategyDef(
    key="polymarket",
    label="Polymarket Skew",
    compute=_compute,
    backtest_engine=BacktestEngine.DIRECTION,
    supports_confirmation=False,
    is_experimental=False,
)
