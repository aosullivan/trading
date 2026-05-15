"""Core types for the Strategy Registry.

See CONTEXT.md for the domain language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping

import pandas as pd


class BacktestEngine(Enum):
    DIRECTION = "direction"
    DIRECTION_VECTORIZED = "direction_vectorized"
    SUPERTREND = "supertrend"
    CORPUS_TREND = "corpus_trend"
    CORPUS_TREND_LAYERED = "corpus_trend_layered"
    MANAGED = "managed"
    CONFIRMATION_LAYERED = "confirmation_layered"
    WEEKLY_CORE_DAILY_OVERLAY = "weekly_core_daily_overlay"
    RIBBON_REGIME = "ribbon_regime"
    RIBBON_ACCUMULATION = "ribbon_accumulation"


@dataclass(frozen=True)
class StrategyContext:
    df: pd.DataFrame
    ticker: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyResult:
    direction: pd.Series
    overlays: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


ComputeFn = Callable[[StrategyContext], StrategyResult]
BacktestKwargsFn = Callable[[StrategyResult], Mapping[str, Any]]
MetaExtrasFn = Callable[[StrategyResult], Mapping[str, Any]]


@dataclass(frozen=True)
class StrategyDef:
    key: str
    label: str
    compute: ComputeFn
    backtest_engine: BacktestEngine
    supports_confirmation: bool = False
    is_experimental: bool = False
    default_params: Mapping[str, Any] = field(default_factory=dict)
    # Extracts engine-specific kwargs from the StrategyResult, e.g. corpus_trend
    # pulls its stop_line overlay through to backtest_corpus_trend. None means
    # the engine takes only (df, direction).
    backtest_kwargs_from: BacktestKwargsFn | None = None
    architecture_label: str | None = None
    architecture_hint: str | None = None
    # Include this strategy's `buy_hold_equity_curve` inside its strategy payload
    # (some strategies omit it and let the top-level field serve the chart).
    include_buy_hold_in_payload: bool = False
    # Include the managed-window meta block. A few strategies (corpus_trend_layered,
    # cci_hysteresis, trend_sr_macro_v1, weekly_core_overlay_v1) historically omit it.
    include_managed_window_meta: bool = True
    # Strategy-specific meta merged on top of the standard meta. Use for dynamic
    # fields derived from a StrategyResult (macro_regime_band, weekly_core_overlay
    # core/overlay descriptors, etc.).
    meta_extras_from: MetaExtrasFn | None = None
