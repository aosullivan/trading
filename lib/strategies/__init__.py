"""Strategy Registry.

The single source of truth that maps a strategy key to its StrategyDef.
See CONTEXT.md for the domain language.
"""

from __future__ import annotations

from ._types import (
    BacktestEngine,
    ComputeFn,
    StrategyContext,
    StrategyDef,
    StrategyResult,
)


STRATEGIES: dict[str, StrategyDef] = {}


def register(strategy: StrategyDef) -> StrategyDef:
    if strategy.key in STRATEGIES:
        raise ValueError(f"Strategy key {strategy.key!r} already registered")
    STRATEGIES[strategy.key] = strategy
    return strategy


def get_strategy(key: str) -> StrategyDef:
    try:
        return STRATEGIES[key]
    except KeyError as exc:
        raise KeyError(f"Unknown strategy key {key!r}") from exc


def has_strategy(key: str) -> bool:
    return key in STRATEGIES


def all_strategies() -> list[StrategyDef]:
    return list(STRATEGIES.values())


def maintained_strategies() -> list[StrategyDef]:
    return [s for s in STRATEGIES.values() if not s.is_experimental]


def experimental_strategies() -> list[StrategyDef]:
    return [s for s in STRATEGIES.values() if s.is_experimental]


# Static registrations. Each module under lib/strategies/ exports a `STRATEGY`
# StrategyDef; import-and-register here so the registry is populated at package
# import time without per-module import side effects.
from . import (  # noqa: E402
    bb_breakout,
    cci_hysteresis,
    cci_trend,
    corpus_trend,
    corpus_trend_layered,
    ema_9_26,
    ema_crossover,
    polymarket,
    ribbon,
    semis_persist,
    supertrend_i,
    trend_sr_macro_v1,
    weekly_core_overlay_v1,
)

# Registration order is the user-visible display order in the backtest
# panel dropdown. Keep stable to avoid UX churn.
for _module in (
    # Maintained
    ribbon,
    corpus_trend,
    corpus_trend_layered,
    cci_hysteresis,
    polymarket,
    # Experimental
    trend_sr_macro_v1,
    weekly_core_overlay_v1,
    supertrend_i,
    ema_9_26,
    semis_persist,
    bb_breakout,
    ema_crossover,
    cci_trend,
):
    register(_module.STRATEGY)


__all__ = [
    "BacktestEngine",
    "ComputeFn",
    "StrategyContext",
    "StrategyDef",
    "StrategyResult",
    "STRATEGIES",
    "register",
    "get_strategy",
    "has_strategy",
    "all_strategies",
    "maintained_strategies",
    "experimental_strategies",
]
