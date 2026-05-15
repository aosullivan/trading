from __future__ import annotations

from lib.technical_indicators import (
    CCI_PERIOD,
    CCI_THRESHOLD,
    compute_cci_trend,
)

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


def _compute(ctx: StrategyContext) -> StrategyResult:
    params = ctx.params
    cci, direction = compute_cci_trend(
        ctx.df,
        period=params.get("period", CCI_PERIOD),
        threshold=params.get("threshold", CCI_THRESHOLD),
    )
    return StrategyResult(direction=direction, overlays={"cci": cci})


STRATEGY = StrategyDef(
    key="cci_trend",
    label="CCI Trend (30/80)",
    compute=_compute,
    backtest_engine=BacktestEngine.DIRECTION,
    supports_confirmation=True,
    is_experimental=True,
    default_params={
        "period": CCI_PERIOD,
        "threshold": CCI_THRESHOLD,
    },
)
