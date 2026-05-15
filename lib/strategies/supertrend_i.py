from __future__ import annotations

from lib.technical_indicators import (
    SUPERTREND_MULTIPLIER,
    SUPERTREND_PERIOD,
    compute_supertrend_i,
)

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


def _compute(ctx: StrategyContext) -> StrategyResult:
    params = ctx.params
    supertrend, direction = compute_supertrend_i(
        ctx.df,
        period=params.get("period", SUPERTREND_PERIOD),
        multiplier=params.get("multiplier", SUPERTREND_MULTIPLIER),
    )
    return StrategyResult(
        direction=direction,
        overlays={"supertrend_line": supertrend},
    )


STRATEGY = StrategyDef(
    key="supertrend_i",
    label="Supertrend-I",
    compute=_compute,
    backtest_engine=BacktestEngine.DIRECTION,
    supports_confirmation=True,
    is_experimental=True,
    default_params={
        "period": SUPERTREND_PERIOD,
        "multiplier": SUPERTREND_MULTIPLIER,
    },
    architecture_label="Supertrend-I",
    architecture_hint="ATR Supertrend ratchet that flips on an intrabar touch of the active band rather than waiting for the close to cross it.",
    include_buy_hold_in_payload=True,
)
