import json


TREND_RIBBON_SIGNAL_PROFILE = {
    "ema_period": 34,
    "atr_period": 14,
    "fast_period": 8,
    "slow_period": 34,
    "smooth_period": 8,
    "collapse_threshold": 0.06,
    "expand_threshold": 0.15,
}

TREND_RIBBON_WEEKLY_SIGNAL_PROFILE = {
    "ema_period": 34,
    "atr_period": 14,
    "fast_period": 8,
    "slow_period": 34,
    "smooth_period": 8,
    "collapse_threshold": 0.06,
    "expand_threshold": 0.15,
}

TREND_RIBBON_REGIME_PROFILE = {
    "reentry_cooldown_bars": 0,
    "reentry_cooldown_ratio": 0.70,
    "weekly_nonbull_confirm_bars": 1,
}

TREND_RIBBON_BACKTEST_PROFILE = {
    "daily_add_capital": 3000.0,
    "weekly_add_capital": 0.0,
    "max_capital": 120000.0,
    "daily_sell_fraction": 0.05,
    "weekly_sell_fraction": 0.75,
}


TREND_RIBBON_V2_SIGNAL_PROFILE = {
    "ema_period": 13,
    "atr_period": 20,
    "fast_period": 8,
    "slow_period": 34,
    "smooth_period": 5,
    "collapse_threshold": 0.06,
    "expand_threshold": 0.15,
    "daily_confirm_bars": 3,
    "weekly_confirm_bars": 2,
    "width_floor_pct": 0.10,
    "width_expand_req": True,
    "ntz_width_pct": 0.08,
    "ntz_consec_bars": 5,
    "ntz_adx_threshold": 18,
}

TREND_RIBBON_V2_BACKTEST_PROFILE = {
    "daily_add_capital": 3000.0,
    "weekly_add_capital": 5000.0,
    "max_capital": 120000.0,
    "max_tactical_pct": 0.80,
    "sell_compression_t1": 0.25,
    "sell_compression_t2": 0.50,
    "sell_pct_t1": 0.05,
    "sell_pct_t2": 0.15,
    "sell_pct_t3": 0.30,
    "conflict_sell_fraction": 0.50,
    "weekly_sell_base": 0.50,
    "weekly_sell_floor": 0.75,
    "weekly_sell_max": 0.90,
    "weekly_bear_max_daily_bars": 5,
    "slippage_pct": 0.0005,
    "commission_per_trade": 0.0,
}


def trend_ribbon_signal_kwargs(
    _ticker: str | None = None,
    timeframe: str = "daily",
) -> dict[str, int | float]:
    if timeframe == "weekly":
        return dict(TREND_RIBBON_WEEKLY_SIGNAL_PROFILE)
    return dict(TREND_RIBBON_SIGNAL_PROFILE)


def trend_ribbon_backtest_kwargs(_ticker: str | None = None) -> dict[str, float]:
    return dict(TREND_RIBBON_BACKTEST_PROFILE)


def trend_ribbon_regime_kwargs(_ticker: str | None = None) -> dict[str, int | float]:
    return dict(TREND_RIBBON_REGIME_PROFILE)


def trend_ribbon_v2_signal_kwargs(
    _ticker: str | None = None,
    timeframe: str = "daily",
) -> dict[str, int | float | bool]:
    profile = dict(TREND_RIBBON_V2_SIGNAL_PROFILE)
    daily_confirm_bars = int(profile.pop("daily_confirm_bars"))
    weekly_confirm_bars = int(profile.pop("weekly_confirm_bars"))
    profile["confirm_bars"] = (
        weekly_confirm_bars if timeframe == "weekly" else daily_confirm_bars
    )
    return profile


def trend_ribbon_v2_backtest_kwargs(
    _ticker: str | None = None,
) -> dict[str, int | float]:
    return dict(TREND_RIBBON_V2_BACKTEST_PROFILE)


def trend_ribbon_profile_signature(_ticker: str | None = None) -> str:
    payload = {
        "signal": TREND_RIBBON_SIGNAL_PROFILE,
        "weekly_signal": TREND_RIBBON_WEEKLY_SIGNAL_PROFILE,
        "backtest": TREND_RIBBON_BACKTEST_PROFILE,
        "regime": TREND_RIBBON_REGIME_PROFILE,
        "v2_signal": TREND_RIBBON_V2_SIGNAL_PROFILE,
        "v2_backtest": TREND_RIBBON_V2_BACKTEST_PROFILE,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
