from __future__ import annotations

from lib.technical_indicators import (
    CCI_HYSTERESIS_ENTRY_THRESHOLD,
    CCI_HYSTERESIS_EXIT_THRESHOLD,
    CCI_PERIOD,
    compute_cci_hysteresis,
)

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


def _compute(ctx: StrategyContext) -> StrategyResult:
    params = ctx.params
    cci, direction = compute_cci_hysteresis(
        ctx.df,
        period=params.get("period", CCI_PERIOD),
        entry_threshold=params.get("entry_threshold", CCI_HYSTERESIS_ENTRY_THRESHOLD),
        exit_threshold=params.get("exit_threshold", CCI_HYSTERESIS_EXIT_THRESHOLD),
    )
    return StrategyResult(direction=direction, overlays={"cci": cci})


STRATEGY = StrategyDef(
    key="cci_hysteresis",
    label="CCI Hysteresis (30/150/-40)",
    compute=_compute,
    backtest_engine=BacktestEngine.DIRECTION,
    supports_confirmation=False,
    is_experimental=False,
    default_params={
        "period": CCI_PERIOD,
        "entry_threshold": CCI_HYSTERESIS_ENTRY_THRESHOLD,
        "exit_threshold": CCI_HYSTERESIS_EXIT_THRESHOLD,
    },
    include_buy_hold_in_payload=True,
    include_managed_window_meta=False,
)
