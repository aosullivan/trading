from __future__ import annotations

from typing import Any, Mapping

from lib.technical_indicators import (
    CORPUS_TREND_ATR_PERIOD,
    CORPUS_TREND_ENTRY_PERIOD,
    CORPUS_TREND_EXIT_PERIOD,
    CORPUS_TREND_STOP_MULTIPLIER,
    compute_corpus_trend_signal,
)

from ._types import (
    BacktestEngine,
    StrategyContext,
    StrategyDef,
    StrategyResult,
)


def _compute(ctx: StrategyContext) -> StrategyResult:
    params = ctx.params
    entry_upper, exit_lower, atr, stop_line, direction = compute_corpus_trend_signal(
        ctx.df,
        entry_period=params.get("entry_period", CORPUS_TREND_ENTRY_PERIOD),
        exit_period=params.get("exit_period", CORPUS_TREND_EXIT_PERIOD),
        atr_period=params.get("atr_period", CORPUS_TREND_ATR_PERIOD),
        stop_multiplier=params.get("stop_multiplier", CORPUS_TREND_STOP_MULTIPLIER),
    )
    return StrategyResult(
        direction=direction,
        overlays={
            "entry_upper": entry_upper,
            "exit_lower": exit_lower,
            "atr": atr,
            "stop_line": stop_line,
        },
    )


def _engine_kwargs(result: StrategyResult) -> Mapping[str, Any]:
    return {"stop_line": result.overlays["stop_line"]}


STRATEGY = StrategyDef(
    key="corpus_trend_layered",
    label="Corpus Trend Layered",
    compute=_compute,
    backtest_engine=BacktestEngine.CORPUS_TREND_LAYERED,
    supports_confirmation=False,
    is_experimental=False,
    default_params={
        "entry_period": CORPUS_TREND_ENTRY_PERIOD,
        "exit_period": CORPUS_TREND_EXIT_PERIOD,
        "atr_period": CORPUS_TREND_ATR_PERIOD,
        "stop_multiplier": CORPUS_TREND_STOP_MULTIPLIER,
    },
    backtest_kwargs_from=_engine_kwargs,
    include_buy_hold_in_payload=True,
    include_managed_window_meta=False,
)
