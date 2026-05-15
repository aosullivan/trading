from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from lib.technical_indicators import (
    CB150_PERIOD,
    DONCHIAN_PERIOD,
    compute_channel_breakout_close,
    compute_donchian_breakout,
    compute_keltner_breakout,
    compute_macd_crossover,
)

from ._types import BacktestEngine, StrategyContext, StrategyDef, StrategyResult


DEFAULT_PROFILE: Mapping[str, Any] = {
    "core": "cb150",
    "overlay": "donchian",
    "core_fraction": 0.70,
    "overlay_fraction": 0.30,
}

TICKER_PROFILES: Mapping[str, Mapping[str, Any]] = {
    "BTC-USD": {
        "core": "donchian",
        "overlay": "donchian",
        "core_fraction": 0.70,
        "overlay_fraction": 0.30,
    },
    "ETH-USD": {
        "core": "donchian",
        "overlay": "donchian",
        "core_fraction": 0.70,
        "overlay_fraction": 0.30,
    },
    "COIN": {
        "core": "macd",
        "overlay": "keltner",
        "core_fraction": 0.70,
        "overlay_fraction": 0.30,
    },
}


def profile_for(ticker: str | None) -> dict[str, Any]:
    out = dict(DEFAULT_PROFILE)
    if ticker:
        out.update(TICKER_PROFILES.get(ticker, {}))
    return out


def _core_direction(key: str, df: pd.DataFrame) -> pd.Series:
    if key == "cb150":
        _hc, _lc, direction = compute_channel_breakout_close(df, CB150_PERIOD)
        return direction
    if key == "donchian":
        _upper, _lower, direction = compute_donchian_breakout(df, DONCHIAN_PERIOD)
        return direction
    if key == "macd":
        _line, _signal, _hist, direction = compute_macd_crossover(df)
        return direction
    raise ValueError(f"Unknown core key {key!r}")


def _overlay_direction(key: str, df: pd.DataFrame) -> pd.Series:
    if key == "donchian":
        _upper, _lower, direction = compute_donchian_breakout(df, DONCHIAN_PERIOD)
        return direction
    if key == "keltner":
        _upper, _mid, _lower, direction = compute_keltner_breakout(df)
        return direction
    raise ValueError(f"Unknown overlay key {key!r}")


def _compute(ctx: StrategyContext) -> StrategyResult:
    profile = profile_for(ctx.ticker)
    core_key = profile["core"]
    overlay_key = profile["overlay"]
    core_dir = _core_direction(core_key, ctx.df)
    overlay_dir = _overlay_direction(overlay_key, ctx.df)
    # The engine treats core_direction as the primary signal and overlay_direction
    # as the layered sleeve. The composite has no single canonical direction; we
    # surface core_direction as `.direction` so the engine's positional contract
    # holds, and the overlay sleeve flows through engine_kwargs + metadata.
    return StrategyResult(
        direction=core_dir,
        metadata={
            "overlay_direction": overlay_dir,
            "core_key": core_key,
            "overlay_key": overlay_key,
            "core_fraction": float(profile.get("core_fraction", 0.70)),
            "overlay_fraction": float(profile.get("overlay_fraction", 0.30)),
        },
    )


def _engine_kwargs(result: StrategyResult) -> Mapping[str, Any]:
    return {
        "overlay_direction": result.metadata["overlay_direction"],
        "core_fraction": result.metadata["core_fraction"],
        "overlay_fraction": result.metadata["overlay_fraction"],
    }


def _hint(core_key: str, overlay_key: str, core_fraction: float, overlay_fraction: float) -> str:
    core_pct = int(round(float(core_fraction) * 100))
    overlay_pct = int(round(float(overlay_fraction) * 100))
    return (
        f"keep a {core_pct}% weekly {core_key} core on while the weekly regime stays bullish, "
        f"then add or remove the final {overlay_pct}% using daily {overlay_key} timing."
    )


def _meta_extras(result: StrategyResult) -> Mapping[str, Any]:
    m = result.metadata
    core_key = m["core_key"]
    overlay_key = m["overlay_key"]
    core_fraction = m["core_fraction"]
    overlay_fraction = m["overlay_fraction"]
    return {
        "confirmation_supported": False,
        "architecture_label": "Weekly Core + Daily Overlay",
        "architecture_core_strategy": f"{core_key}_weekly",
        "architecture_overlay_strategy": f"{overlay_key}_daily",
        "architecture_core_fraction": core_fraction,
        "architecture_overlay_fraction": overlay_fraction,
        "architecture_hint": _hint(core_key, overlay_key, core_fraction, overlay_fraction),
    }


STRATEGY = StrategyDef(
    key="weekly_core_overlay_v1",
    label="Weekly Core + Daily Overlay",
    compute=_compute,
    backtest_engine=BacktestEngine.WEEKLY_CORE_DAILY_OVERLAY,
    supports_confirmation=False,
    is_experimental=True,
    backtest_kwargs_from=_engine_kwargs,
    include_buy_hold_in_payload=True,
    include_managed_window_meta=False,
    meta_extras_from=_meta_extras,
)
