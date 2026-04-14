import time
from datetime import timedelta

from flask import Blueprint, current_app, request, jsonify
import pandas as pd

from lib.settings import DAILY_WARMUP_DAYS, WEEKLY_WARMUP_DAYS
from lib.cache import (
    _cache_get,
    _cache_set,
    _get_cached_ticker_info_if_fresh,
    _warm_ticker_info_cache_async,
    _CHART_CACHE_TTL,
)
from lib.data_fetching import (
    cached_download,
    normalize_ticker,
    is_treasury_price_ticker,
    _TREASURY_PRICE_PROXIES,
    resolve_treasury_price_proxy_ticker,
)
from lib.technical_indicators import (
    BOLLINGER_PERIOD,
    BOLLINGER_STD_DEV,
    CB50_PERIOD,
    CB150_PERIOD,
    CCI_PERIOD,
    DONCHIAN_PERIOD,
    EMA_FAST_PERIOD,
    EMA_SLOW_PERIOD,
    CCI_HYSTERESIS_ENTRY_THRESHOLD,
    CCI_HYSTERESIS_EXIT_THRESHOLD,
    SMA_CROSS_FAST_10,
    SMA_CROSS_SLOW_100,
    SMA_CROSS_SLOW_200,
    SUPERTREND_MULTIPLIER,
    SUPERTREND_PERIOD,
    compute_supertrend,
    compute_ema_crossover,
    compute_macd_crossover,
    compute_donchian_breakout,
    compute_corpus_trend_signal,
    compute_channel_breakout_close,
    compute_sma_crossover,
    compute_ema_trend_signal,
    compute_yearly_ma_trend,
    compute_bollinger_breakout,
    compute_keltner_breakout,
    compute_parabolic_sar,
    compute_cci_trend,
    compute_cci_hysteresis,
    compute_trend_ribbon,
    compute_orb_breakout,
)
from lib.backtesting import (
    MANAGED_SIZING_METHODS,
    MoneyManagementConfig,
    apply_managed_sizing_defaults,
    backtest_confirmation_layering,
    backtest_corpus_trend,
    backtest_corpus_trend_layered,
    backtest_direction,
    backtest_managed,
    backtest_weekly_core_daily_overlay,
    build_weekly_confirmed_ribbon_direction,
    build_buy_hold_equity_curve,
)
from lib.chart_serialization import (
    build_volume_profile,
    compute_all_trend_flips,
    last_trend_flip,
    series_to_json,
)
from lib.trend_ribbon_profile import (
    trend_ribbon_profile_signature,
    trend_ribbon_regime_kwargs,
    trend_ribbon_signal_kwargs,
)
from lib.support_resistance import compute_support_resistance

bp = Blueprint("chart", __name__)

CONFIRMATION_PRESETS = {
    "layered_30_70": {
        "mode": "layered_30_70",
        "starter_fraction": 0.30,
        "confirmed_fraction": 0.70,
        "label": "Daily 30% / Weekly 70%",
        "semantics": "generic_layered",
        "hint": "keep 30% exposure when daily and weekly disagree, move to 100% only when both are bullish, then scale back out in reverse as confirmation weakens.",
    },
    "layered_50_50": {
        "mode": "layered_50_50",
        "starter_fraction": 0.50,
        "confirmed_fraction": 0.50,
        "label": "Daily 50% / Weekly 50%",
        "semantics": "generic_layered",
        "hint": "keep 50% exposure when daily and weekly disagree, move to 100% only when both are bullish, then scale back out in reverse as confirmation weakens.",
    },
    "escalation_50_50": {
        "mode": "escalation_50_50",
        "starter_fraction": 0.50,
        "confirmed_fraction": 0.50,
        "label": "Daily Base / Weekly Add (50/50)",
        "semantics": "escalation_layered",
        "hint": "keep the base 50% only while the daily signal stays bullish, add the second 50% only when weekly confirms, and remove the add-on first when confirmation breaks.",
    },
}

DEFAULT_CORE_OVERLAY_PROFILE = {
    "core": "cb150",
    "overlay": "donchian",
    "core_fraction": 0.70,
    "overlay_fraction": 0.30,
}

CORE_OVERLAY_STRATEGY_PROFILES = {
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
WEEKLY_CONFIRMATION_STRATEGIES = frozenset(
    {
        "ribbon",
        "corpus_trend",
    }
)


def _elapsed_ms(started_at: float) -> int:
    return int(round((time.perf_counter() - started_at) * 1000))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _parse_start_date(start):
    return pd.Timestamp(start).normalize()


def _parse_end_date(end):
    if not end:
        return None
    return pd.Timestamp(end).normalize()


def _warmup_start(start, interval):
    lookback_days = WEEKLY_WARMUP_DAYS if interval in {"1wk", "1mo"} else DAILY_WARMUP_DAYS
    return (_parse_start_date(start) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def _source_interval(interval: str) -> str:
    return "1wk" if interval == "1mo" else interval


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    resampled = (
        df.sort_index()
        .resample(rule)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
    )
    return resampled.dropna(subset=["Open", "High", "Low", "Close"])


def _derive_chart_frame(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1mo":
        return _resample_ohlcv(df, "ME")
    return df


def _derive_treasury_chart_frame(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1wk":
        return _resample_ohlcv(df, "W-FRI")
    if interval == "1mo":
        return _resample_ohlcv(df, "ME")
    return df


def _visible_mask(index, start, end):
    start_ts = _parse_start_date(start)
    mask = index >= start_ts
    if end:
        end_ts = _parse_end_date(end) + timedelta(days=1) - timedelta(seconds=1)
        mask &= index <= end_ts
    return mask


def _starts_long(direction, full_index, view_index):
    prior_direction = _prior_direction(direction, full_index, view_index)
    return prior_direction == 1


def _prior_direction(direction, full_index, view_index):
    if len(view_index) == 0:
        return None
    first_visible_loc = full_index.get_loc(view_index[0])
    if first_visible_loc == 0:
        return None
    return direction.iloc[first_visible_loc - 1]


def _parse_mm_config():
    """Build a MoneyManagementConfig from request query params, or None if all-in."""
    sizing = request.args.get("mm_sizing", "")
    stop = request.args.get("mm_stop", "")
    stop_val = request.args.get("mm_stop_val", "")
    risk_cap = request.args.get("mm_risk_cap", "")
    compound = request.args.get("mm_compound", "trade")

    if not sizing and not stop and not risk_cap and compound == "trade":
        return None

    kwargs = {}
    if sizing:
        kwargs["sizing_method"] = sizing
    if stop:
        kwargs["stop_type"] = stop
        if stop_val:
            val = float(stop_val)
            if stop == "atr":
                kwargs["stop_atr_multiple"] = val
            elif stop == "pct":
                kwargs["stop_pct"] = val / 100.0
    if risk_cap:
        kwargs["vol_to_equity_limit"] = float(risk_cap)
    if compound != "trade":
        kwargs["compounding"] = compound

    return MoneyManagementConfig(**apply_managed_sizing_defaults(kwargs))


def _parse_confirmation_config():
    mode = request.args.get("confirm_mode", "")
    preset = CONFIRMATION_PRESETS.get(mode)
    return dict(preset) if preset else None


def _confirmation_supported_for_strategy(
    confirmation_config: dict | None,
    strategy_key: str,
    weekly_supported: bool,
) -> bool:
    if not confirmation_config or not weekly_supported:
        return False
    allowed = confirmation_config.get("supported_strategies")
    if not allowed:
        return strategy_key in WEEKLY_CONFIRMATION_STRATEGIES
    return strategy_key in allowed


def _confirmation_config_for_strategy(
    confirmation_config: dict | None,
    strategy_key: str,
    weekly_supported: bool,
) -> dict | None:
    if not _confirmation_supported_for_strategy(
        confirmation_config, strategy_key, weekly_supported
    ):
        return None
    return confirmation_config


def _merge_backtest_meta(*items) -> dict:
    merged = {}
    for item in items:
        if item:
            merged.update(item)
    return merged


def _confirmation_meta(
    confirmation_config: dict | None,
    *,
    supported: bool,
) -> dict:
    if not confirmation_config:
        return {}
    meta = {
        "confirmation_mode": confirmation_config["mode"],
        "confirmation_label": confirmation_config["label"],
        "confirmation_supported": supported,
    }
    if supported:
        meta["confirmation_starter_fraction"] = confirmation_config["starter_fraction"]
        meta["confirmation_confirmed_fraction"] = confirmation_config["confirmed_fraction"]
        meta["confirmation_hint"] = confirmation_config.get("hint", "")
    return meta


def _uses_visible_range_only_managed_sizing(mm_config: MoneyManagementConfig | None) -> bool:
    return bool(mm_config and mm_config.sizing_method in MANAGED_SIZING_METHODS)


def _managed_backtest_kwargs(prior_direction, mm_config: MoneyManagementConfig | None) -> dict:
    if _uses_visible_range_only_managed_sizing(mm_config):
        return {"start_in_position": False, "prior_direction": None}
    return {
        "start_in_position": prior_direction == 1,
        "prior_direction": prior_direction,
    }


def _managed_window_metadata(direction, full_index, view_index, mm_config: MoneyManagementConfig | None) -> dict:
    if not _uses_visible_range_only_managed_sizing(mm_config):
        return {}
    return {
        "backtest_window_policy": "visible_range_only",
        "window_started_mid_trend": bool(
            _prior_direction(direction, full_index, view_index) == 1
        ),
    }


def _strategy_payload(
    trades,
    summary,
    equity_curve,
    *,
    buy_hold_equity_curve=None,
    backtest_meta=None,
):
    payload = {
        "trades": trades,
        "summary": summary,
        "equity_curve": equity_curve,
    }
    if buy_hold_equity_curve is not None:
        payload["buy_hold_equity_curve"] = buy_hold_equity_curve
    if backtest_meta:
        payload.update(backtest_meta)
    return payload


def _core_overlay_profile(ticker: str) -> dict[str, float | str]:
    profile = dict(DEFAULT_CORE_OVERLAY_PROFILE)
    profile.update(CORE_OVERLAY_STRATEGY_PROFILES.get(ticker, {}))
    return profile


def _run_direction_backtest(
    df_view,
    direction,
    full_index,
    view_index,
    mm_config=None,
    weekly_direction=None,
    confirmation_config=None,
    strategy_key=None,
):
    prior_direction = _prior_direction(direction, full_index, view_index)
    if confirmation_config and weekly_direction is not None:
        prior_weekly_direction = _prior_direction(weekly_direction, full_index, view_index)
        return backtest_confirmation_layering(
            df_view,
            direction.loc[view_index],
            weekly_direction.loc[view_index],
            prior_daily_direction=prior_direction,
            prior_weekly_direction=prior_weekly_direction,
            starter_fraction=confirmation_config["starter_fraction"],
            confirmed_fraction=confirmation_config["confirmed_fraction"],
            semantics=confirmation_config.get("semantics", "generic_layered"),
            weekly_nonbull_exit_bars=confirmation_config.get(
                "weekly_nonbull_exit_bars", 1
            ),
        )
    if mm_config is None:
        mm_config = _parse_mm_config()
    if mm_config is not None:
        managed_kwargs = _managed_backtest_kwargs(prior_direction, mm_config)
        return backtest_managed(
            df_view,
            direction.loc[view_index],
            config=mm_config,
            **managed_kwargs,
        )
    return backtest_direction(
        df_view,
        direction.loc[view_index],
        start_in_position=prior_direction == 1,
        prior_direction=prior_direction,
    )


def _run_ribbon_regime_backtest(
    df_view,
    confirmed_direction,
    full_index,
    view_index,
    mm_config=None,
):
    prior_direction = _prior_direction(confirmed_direction, full_index, view_index)
    if mm_config is None:
        mm_config = _parse_mm_config()
    if mm_config is not None:
        managed_kwargs = _managed_backtest_kwargs(prior_direction, mm_config)
        return backtest_managed(
            df_view,
            confirmed_direction.loc[view_index],
            config=mm_config,
            **managed_kwargs,
        )
    return backtest_direction(
        df_view,
        confirmed_direction.loc[view_index],
        start_in_position=prior_direction == 1,
        prior_direction=prior_direction,
    )


def _run_corpus_trend_backtest(
    df_view,
    direction,
    stop_line,
    full_index,
    view_index,
    mm_config=None,
    weekly_direction=None,
    confirmation_config=None,
):
    prior_direction = _prior_direction(direction, full_index, view_index)
    if confirmation_config and weekly_direction is not None:
        prior_weekly_direction = _prior_direction(weekly_direction, full_index, view_index)
        return backtest_confirmation_layering(
            df_view,
            direction.loc[view_index],
            weekly_direction.loc[view_index],
            prior_daily_direction=prior_direction,
            prior_weekly_direction=prior_weekly_direction,
            starter_fraction=confirmation_config["starter_fraction"],
            confirmed_fraction=confirmation_config["confirmed_fraction"],
            semantics=confirmation_config.get("semantics", "generic_layered"),
            weekly_nonbull_exit_bars=confirmation_config.get(
                "weekly_nonbull_exit_bars", 1
            ),
        )
    if mm_config is None:
        mm_config = _parse_mm_config()
    if mm_config is not None:
        managed_kwargs = _managed_backtest_kwargs(prior_direction, mm_config)
        return backtest_managed(
            df_view,
            direction.loc[view_index],
            config=mm_config,
            **managed_kwargs,
        )
    return backtest_corpus_trend(
        df_view,
        direction.loc[view_index],
        stop_line.loc[view_index],
        start_in_position=prior_direction == 1,
        prior_direction=prior_direction,
    )


def _run_corpus_trend_layered_backtest(
    df_view, direction, stop_line, full_index, view_index
):
    prior_direction = _prior_direction(direction, full_index, view_index)
    return backtest_corpus_trend_layered(
        df_view,
        direction.loc[view_index],
        stop_line.loc[view_index],
        start_in_position=prior_direction == 1,
        prior_direction=prior_direction,
    )


def _run_weekly_core_overlay_backtest(
    df_view,
    core_direction,
    overlay_direction,
    full_index,
    view_index,
    *,
    core_fraction=0.70,
    overlay_fraction=0.30,
):
    prior_core_direction = _prior_direction(core_direction, full_index, view_index)
    prior_overlay_direction = _prior_direction(overlay_direction, full_index, view_index)
    return backtest_weekly_core_daily_overlay(
        df_view,
        core_direction.loc[view_index],
        overlay_direction.loc[view_index],
        prior_core_direction=prior_core_direction,
        prior_overlay_direction=prior_overlay_direction,
        core_fraction=core_fraction,
        overlay_fraction=overlay_fraction,
    )


def _carry_neutral_direction(direction: pd.Series) -> pd.Series:
    """Carry the prior non-zero state through neutral bridge bars."""
    return direction.replace(0, pd.NA).ffill().fillna(0).astype(int)


def _weekly_core_overlay_hint(
    core_key: str,
    overlay_key: str,
    core_fraction: float,
    overlay_fraction: float,
) -> str:
    core_pct = int(round(float(core_fraction) * 100))
    overlay_pct = int(round(float(overlay_fraction) * 100))
    return (
        f"keep a {core_pct}% weekly {core_key} core on while the weekly regime stays bullish, "
        f"then add or remove the final {overlay_pct}% using daily {overlay_key} timing."
    )


def _align_weekly_direction_to_daily(
    weekly_direction: pd.Series,
    daily_index: pd.Index,
) -> pd.Series:
    return weekly_direction.reindex(daily_index).ffill().fillna(0).astype(int)


def _trend_ribbon_kwargs(ticker: str, timeframe: str = "daily") -> dict:
    """Use the Trend Ribbon baseline profile for every ticker."""
    return trend_ribbon_signal_kwargs(ticker, timeframe=timeframe)


def _frame_signature(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "empty"
    first_ts = int(pd.Timestamp(df.index[0]).timestamp())
    last_ts = int(pd.Timestamp(df.index[-1]).timestamp())
    last_row = df.iloc[-1]
    tail_values = []
    for col in ("Open", "High", "Low", "Close", "Volume"):
        val = last_row.get(col)
        tail_values.append("nan" if pd.isna(val) else f"{float(val):.6f}")
    return f"{len(df)}:{first_ts}:{last_ts}:{':'.join(tail_values)}"


def _last_flips_from_directions(direction_map: dict[str, pd.Series]) -> dict:
    flips = {}
    for key, dir_series in direction_map.items():
        date, flip_dir = last_trend_flip(dir_series)
        flips[key] = {"date": date, "dir": flip_dir}
    return flips


def _get_indicator_bundle(
    ticker: str,
    interval: str,
    df: pd.DataFrame,
    period_val: int,
    multiplier_val: float,
) -> tuple[dict, bool]:
    cache_key = (
        f"indicator_bundle:{ticker}:{interval}:{period_val}:{multiplier_val}:"
        f"{trend_ribbon_profile_signature(ticker)}:{_frame_signature(df)}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True

    supertrend, direction = compute_supertrend(df, period_val, multiplier_val)
    ema_fast, ema_slow, ema_direction = compute_ema_crossover(
        df,
        EMA_FAST_PERIOD,
        EMA_SLOW_PERIOD,
    )
    macd_line, signal_line, macd_hist, macd_direction = compute_macd_crossover(df)
    donch_upper, donch_lower, donch_direction = compute_donchian_breakout(
        df,
        DONCHIAN_PERIOD,
    )
    corpus_entry_upper, corpus_exit_lower, corpus_atr, corpus_stop_line, corpus_direction = (
        compute_corpus_trend_signal(df)
    )
    cb50_hc, cb50_lc, cb50_direction = compute_channel_breakout_close(df, CB50_PERIOD)
    cb150_hc, cb150_lc, cb150_direction = compute_channel_breakout_close(df, CB150_PERIOD)
    sma10, sma100, sma_10_100_direction = compute_sma_crossover(
        df, SMA_CROSS_FAST_10, SMA_CROSS_SLOW_100,
    )
    _, sma200, sma_10_200_direction = compute_sma_crossover(
        df, SMA_CROSS_FAST_10, SMA_CROSS_SLOW_200,
    )
    ema_trend_ref, ema_trend_sig, ema_trend_direction = compute_ema_trend_signal(df)
    yearly_ma, yearly_ma_direction = compute_yearly_ma_trend(df)
    bb_upper, bb_mid, bb_lower, bb_direction = compute_bollinger_breakout(
        df,
        BOLLINGER_PERIOD,
        BOLLINGER_STD_DEV,
    )
    kelt_upper, kelt_mid, kelt_lower, kelt_direction = compute_keltner_breakout(df)
    psar_line, psar_direction = compute_parabolic_sar(df)
    cci_val, cci_direction = compute_cci_trend(df)
    cci_hyst_val, cci_hyst_direction = compute_cci_hysteresis(
        df,
        period=CCI_PERIOD,
        entry_threshold=CCI_HYSTERESIS_ENTRY_THRESHOLD,
        exit_threshold=CCI_HYSTERESIS_EXIT_THRESHOLD,
    )
    orb_range_high, orb_range_low, orb_range_mid, orb_trend_ema, orb_direction = compute_orb_breakout(df)
    ribbon_center, ribbon_upper, ribbon_lower, ribbon_strength, ribbon_dir = compute_trend_ribbon(
        df,
        **_trend_ribbon_kwargs(ticker),
    )

    direction_map = {
        "cb50": cb50_direction,
        "cb150": cb150_direction,
        "sma_10_100": sma_10_100_direction,
        "sma_10_200": sma_10_200_direction,
        "ema_trend": ema_trend_direction,
        "yearly_ma": yearly_ma_direction,
        "supertrend": direction,
        "ema_crossover": ema_direction,
        "macd": macd_direction,
        "donchian": donch_direction,
        "corpus_trend": corpus_direction,
        "bb_breakout": bb_direction,
        "keltner": kelt_direction,
        "parabolic_sar": psar_direction,
        "cci_trend": cci_direction,
        "cci_hysteresis": cci_hyst_direction,
        "orb_breakout": orb_direction,
        "ribbon": ribbon_dir,
    }
    bundle = {
        "supertrend": supertrend,
        "direction": direction,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_direction": ema_direction,
        "macd_line": macd_line,
        "signal_line": signal_line,
        "macd_hist": macd_hist,
        "macd_direction": macd_direction,
        "donch_upper": donch_upper,
        "donch_lower": donch_lower,
        "donch_direction": donch_direction,
        "corpus_entry_upper": corpus_entry_upper,
        "corpus_exit_lower": corpus_exit_lower,
        "corpus_atr": corpus_atr,
        "corpus_stop_line": corpus_stop_line,
        "corpus_direction": corpus_direction,
        "cb50_direction": cb50_direction,
        "cb150_direction": cb150_direction,
        "sma_10_100_direction": sma_10_100_direction,
        "sma_10_200_direction": sma_10_200_direction,
        "ema_trend_direction": ema_trend_direction,
        "yearly_ma_direction": yearly_ma_direction,
        "bb_upper": bb_upper,
        "bb_mid": bb_mid,
        "bb_lower": bb_lower,
        "bb_direction": bb_direction,
        "kelt_upper": kelt_upper,
        "kelt_mid": kelt_mid,
        "kelt_lower": kelt_lower,
        "kelt_direction": kelt_direction,
        "psar_line": psar_line,
        "psar_direction": psar_direction,
        "cci_val": cci_val,
        "cci_direction": cci_direction,
        "cci_hyst_val": cci_hyst_val,
        "cci_hyst_direction": cci_hyst_direction,
        "orb_range_high": orb_range_high,
        "orb_range_low": orb_range_low,
        "orb_range_mid": orb_range_mid,
        "orb_trend_ema": orb_trend_ema,
        "orb_direction": orb_direction,
        "ribbon_center": ribbon_center,
        "ribbon_upper": ribbon_upper,
        "ribbon_lower": ribbon_lower,
        "ribbon_strength": ribbon_strength,
        "ribbon_dir": ribbon_dir,
        "daily_flips": _last_flips_from_directions(direction_map),
    }
    _cache_set(cache_key, bundle, ttl=_CHART_CACHE_TTL)
    return bundle, False


def _get_weekly_bundle(
    ticker: str,
    df_w: pd.DataFrame,
    period_val: int,
    multiplier_val: float,
) -> tuple[dict, bool]:
    cache_key = (
        f"weekly_bundle:{ticker}:{period_val}:{multiplier_val}:"
        f"{trend_ribbon_profile_signature(ticker)}:{_frame_signature(df_w)}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True

    _supertrend, supertrend_direction = compute_supertrend(
        df_w,
        period_val,
        multiplier_val,
    )
    _ema_fast, _ema_slow, ema_direction = compute_ema_crossover(
        df_w,
        EMA_FAST_PERIOD,
        EMA_SLOW_PERIOD,
    )
    _macd_line, _signal_line, _macd_hist, macd_direction = compute_macd_crossover(df_w)
    _donch_upper, _donch_lower, donch_direction = compute_donchian_breakout(
        df_w,
        DONCHIAN_PERIOD,
    )
    (
        _corpus_entry_upper,
        _corpus_exit_lower,
        _corpus_atr,
        _corpus_stop_line,
        corpus_direction,
    ) = compute_corpus_trend_signal(df_w)
    _cb50_hc, _cb50_lc, cb50_direction = compute_channel_breakout_close(df_w, CB50_PERIOD)
    _cb150_hc, _cb150_lc, cb150_direction = compute_channel_breakout_close(df_w, CB150_PERIOD)
    _sma10, _sma100, sma_10_100_direction = compute_sma_crossover(
        df_w, SMA_CROSS_FAST_10, SMA_CROSS_SLOW_100,
    )
    _sma10_slow, _sma200, sma_10_200_direction = compute_sma_crossover(
        df_w, SMA_CROSS_FAST_10, SMA_CROSS_SLOW_200,
    )
    _ema_trend_ref, _ema_trend_signal, ema_trend_direction = compute_ema_trend_signal(df_w)
    _yearly_ma, yearly_ma_direction = compute_yearly_ma_trend(df_w)
    _bb_upper, _bb_mid, _bb_lower, bb_direction = compute_bollinger_breakout(
        df_w,
        BOLLINGER_PERIOD,
        BOLLINGER_STD_DEV,
    )
    _kelt_upper, _kelt_mid, _kelt_lower, kelt_direction = compute_keltner_breakout(df_w)
    _psar_line, psar_direction = compute_parabolic_sar(df_w)
    _cci_val, cci_direction = compute_cci_trend(df_w)
    _cci_hyst_val, cci_hyst_direction = compute_cci_hysteresis(
        df_w,
        period=CCI_PERIOD,
        entry_threshold=CCI_HYSTERESIS_ENTRY_THRESHOLD,
        exit_threshold=CCI_HYSTERESIS_EXIT_THRESHOLD,
    )
    _, _, _, _, orb_direction = compute_orb_breakout(df_w)
    sma_w50 = df_w["Close"].rolling(window=50).mean()
    sma_w100 = df_w["Close"].rolling(window=100).mean()
    sma_w200 = df_w["Close"].rolling(window=200).mean()
    _ribbon_center, _ribbon_upper, _ribbon_lower, _ribbon_strength, ribbon_dir = compute_trend_ribbon(
        df_w,
        **_trend_ribbon_kwargs(ticker, timeframe="weekly"),
    )
    direction_map = {
        "cb50": cb50_direction,
        "cb150": cb150_direction,
        "sma_10_100": sma_10_100_direction,
        "sma_10_200": sma_10_200_direction,
        "ema_trend": ema_trend_direction,
        "yearly_ma": yearly_ma_direction,
        "supertrend": supertrend_direction,
        "ema_crossover": ema_direction,
        "macd": macd_direction,
        "donchian": donch_direction,
        "corpus_trend": corpus_direction,
        "bb_breakout": bb_direction,
        "keltner": kelt_direction,
        "parabolic_sar": psar_direction,
        "cci_trend": cci_direction,
        "cci_hysteresis": cci_hyst_direction,
        "orb_breakout": orb_direction,
        "ribbon": ribbon_dir,
    }
    bundle = {
        "sma_w50": sma_w50,
        "sma_w100": sma_w100,
        "sma_w200": sma_w200,
        "ribbon_dir": ribbon_dir,
        "directions": direction_map,
        "weekly_flips": compute_all_trend_flips(
            df_w,
            period_val=period_val,
            multiplier_val=multiplier_val,
            ribbon_kwargs=_trend_ribbon_kwargs(ticker, timeframe="weekly"),
        ),
    }
    _cache_set(cache_key, bundle, ttl=_CHART_CACHE_TTL)
    return bundle, False


def _weekly_direction_for_strategy(
    weekly_bundle: dict | None,
    strategy_key: str,
    daily_index: pd.Index,
) -> pd.Series | None:
    if not weekly_bundle:
        return None
    weekly_direction = (weekly_bundle.get("directions") or {}).get(strategy_key)
    if weekly_direction is None:
        return None
    return _align_weekly_direction_to_daily(weekly_direction, daily_index)


def _resolve_cached_ticker_name(ticker: str) -> str:
    if is_treasury_price_ticker(ticker):
        return _TREASURY_PRICE_PROXIES[ticker]["name"]
    info = _get_cached_ticker_info_if_fresh(ticker)
    if info:
        return info.get("shortName") or info.get("longName") or ""
    _warm_ticker_info_cache_async(ticker)
    return ""


def _ohlcv_df_to_candles(df_view: pd.DataFrame) -> list[dict]:
    """Serialize visible OHLCV rows for lightweight-charts (no indicators)."""
    candles = []
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        candles.append(
            {
                "time": ts,
                "open": round(float(df_view["Open"].iloc[i]), 2),
                "high": round(float(df_view["High"].iloc[i]), 2),
                "low": round(float(df_view["Low"].iloc[i]), 2),
                "close": round(float(df_view["Close"].iloc[i]), 2),
            }
        )
    return candles


# ---------------------------------------------------------------------------
# Chart API route
# ---------------------------------------------------------------------------

@bp.route("/api/chart")
def chart_data():
    request_started_at = time.perf_counter()
    phase_started_at = request_started_at
    timings_ms = {}
    indicator_bundle_hit = False
    weekly_bundle_hit = False

    def mark_phase(name: str):
        nonlocal phase_started_at
        timings_ms[name] = _elapsed_ms(phase_started_at)
        phase_started_at = time.perf_counter()

    ticker = normalize_ticker(request.args.get("ticker", "BTC-USD"))
    data_ticker = normalize_ticker(resolve_treasury_price_proxy_ticker(ticker))
    interval = request.args.get("interval", "1d")
    source_interval = _source_interval(interval)
    start = request.args.get("start", "2015-01-01")
    end = request.args.get("end", "")
    period_val = int(request.args.get("period", SUPERTREND_PERIOD))
    multiplier_val = float(request.args.get("multiplier", SUPERTREND_MULTIPLIER))
    mm_sig = ":".join(
        request.args.get(k, "")
        for k in (
            "mm_sizing",
            "mm_stop",
            "mm_stop_val",
            "mm_risk_cap",
            "mm_compound",
            "confirm_mode",
        )
    )
    candles_only = request.args.get("candles_only", "").lower() in ("1", "true", "yes")
    candles_cache_key = f"chart:candles:{ticker}:{interval}:{start}:{end or 'latest'}"
    chart_cache_key = (
        f"chart:{ticker}:{interval}:{start}:{end}:{period_val}:{multiplier_val}:"
        f"{trend_ribbon_profile_signature(ticker)}:{mm_sig}"
    )
    if candles_only:
        cached_candles = _cache_get(candles_cache_key)
        if cached_candles is not None:
            current_app.logger.info(
                "chart_data candles_only_cache_hit ticker=%s interval=%s range=%s..%s total_ms=%s",
                ticker,
                interval,
                start,
                end or "latest",
                _elapsed_ms(request_started_at),
            )
            return jsonify(cached_candles)
    else:
        cached_chart = _cache_get(chart_cache_key)
        if cached_chart is not None:
            if not cached_chart.get("ticker_name"):
                ticker_name = _resolve_cached_ticker_name(ticker)
                if ticker_name:
                    cached_chart = {**cached_chart, "ticker_name": ticker_name}
                    _cache_set(chart_cache_key, cached_chart, ttl=_CHART_CACHE_TTL)
            current_app.logger.info(
                "chart_data cache_hit ticker=%s interval=%s range=%s..%s total_ms=%s",
                ticker,
                interval,
                start,
                end or "latest",
                _elapsed_ms(request_started_at),
            )
            return jsonify(cached_chart)

    # Fetch full name for display
    ticker_name = _resolve_cached_ticker_name(ticker)
    mark_phase("metadata_ms")

    try:
        warmup_start = _warmup_start(start, interval)
        kwargs = {
            "start": warmup_start,
            "interval": source_interval,
            "progress": False,
        }
        if end:
            kwargs["end"] = end
        source_df = cached_download(data_ticker, **kwargs)
    except Exception as e:
        current_app.logger.info(
            "chart_data fetch_error ticker=%s interval=%s range=%s..%s metadata_ms=%s fetch_ms=%s total_ms=%s error=%s",
            ticker,
            interval,
            start,
            end or "latest",
            timings_ms.get("metadata_ms", 0),
            _elapsed_ms(phase_started_at),
            _elapsed_ms(request_started_at),
            str(e),
        )
        return jsonify({"error": str(e)}), 400
    mark_phase("fetch_ms")

    if source_df.empty:
        current_app.logger.info(
            "chart_data empty_source ticker=%s interval=%s range=%s..%s metadata_ms=%s fetch_ms=%s total_ms=%s",
            ticker,
            interval,
            start,
            end or "latest",
            timings_ms.get("metadata_ms", 0),
            timings_ms.get("fetch_ms", 0),
            _elapsed_ms(request_started_at),
        )
        return jsonify({"error": f"No data for {ticker}"}), 400

    if isinstance(source_df.columns, pd.MultiIndex):
        source_df.columns = source_df.columns.get_level_values(0)

    source_df = source_df[~source_df.index.duplicated(keep="last")]
    df = _derive_chart_frame(source_df, interval)

    view_mask = _visible_mask(df.index, start, end)
    df_view = df.loc[view_mask].copy()
    if df_view.index.duplicated().any():
        df_view = df_view[~df_view.index.duplicated(keep="last")]
    if df_view.empty:
        current_app.logger.info(
            "chart_data empty_view ticker=%s interval=%s range=%s..%s metadata_ms=%s fetch_ms=%s frame_ms=%s total_ms=%s",
            ticker,
            interval,
            start,
            end or "latest",
            timings_ms.get("metadata_ms", 0),
            timings_ms.get("fetch_ms", 0),
            _elapsed_ms(phase_started_at),
            _elapsed_ms(request_started_at),
        )
        return jsonify({"error": f"No data for {ticker} in selected range"}), 400
    mark_phase("frame_ms")

    if candles_only:
        candles = _ohlcv_df_to_candles(df_view)
        payload = {"candles": candles, "ticker_name": ticker_name}
        _cache_set(candles_cache_key, payload, ttl=_CHART_CACHE_TTL)
        current_app.logger.info(
            "chart_data candles_only ticker=%s interval=%s range=%s..%s bars=%s fetch_ms=%s total_ms=%s",
            ticker,
            interval,
            start,
            end or "latest",
            len(candles),
            timings_ms.get("fetch_ms", 0),
            _elapsed_ms(request_started_at),
        )
        return jsonify(payload)

    active_mm_config = _parse_mm_config()
    confirmation_config = _parse_confirmation_config()
    weekly_bundle = None
    weekly_bundle_hit = False
    if interval == "1d":
        try:
            df_w = _resample_ohlcv(source_df, "W-FRI")
            if not df_w.empty:
                if isinstance(df_w.columns, pd.MultiIndex):
                    df_w.columns = df_w.columns.get_level_values(0)
                if df_w.index.duplicated().any():
                    df_w = df_w[~df_w.index.duplicated(keep="last")]
                weekly_bundle, weekly_bundle_hit = _get_weekly_bundle(
                    ticker,
                    df_w,
                    period_val,
                    multiplier_val,
                )
        except Exception:
            current_app.logger.exception(
                "chart_data confirmation weekly bundle failed ticker=%s interval=%s",
                ticker,
                interval,
            )

    # --- Compute all indicators ---
    indicator_bundle, indicator_bundle_hit = _get_indicator_bundle(
        ticker,
        interval,
        df,
        period_val,
        multiplier_val,
    )
    weekly_confirmation_supported = interval == "1d" and weekly_bundle is not None
    cb50_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "cb50", df.index
    )
    cb150_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "cb150", df.index
    )
    sma_10_100_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "sma_10_100", df.index
    )
    sma_10_200_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "sma_10_200", df.index
    )
    ema_trend_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "ema_trend", df.index
    )
    yearly_ma_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "yearly_ma", df.index
    )
    supertrend_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "supertrend", df.index
    )
    ema_crossover_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "ema_crossover", df.index
    )
    macd_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "macd", df.index
    )
    donchian_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "donchian", df.index
    )
    corpus_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "corpus_trend", df.index
    )
    bb_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "bb_breakout", df.index
    )
    keltner_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "keltner", df.index
    )
    psar_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "parabolic_sar", df.index
    )
    cci_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "cci_trend", df.index
    )
    orb_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "orb_breakout", df.index
    )
    ribbon_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "ribbon", df.index
    )
    strategy_confirmation_config = (
        lambda key: _confirmation_config_for_strategy(
            confirmation_config, key, weekly_confirmation_supported
        )
    )
    strategy_confirmation_meta = (
        lambda key: _confirmation_meta(
            confirmation_config,
            supported=_confirmation_supported_for_strategy(
                confirmation_config, key, weekly_confirmation_supported
            ),
        )
    )
    supertrend = indicator_bundle["supertrend"]
    direction = indicator_bundle["direction"]
    direction_view = direction.loc[df_view.index]
    supertrend_view = supertrend.loc[df_view.index]

    ema_fast = indicator_bundle["ema_fast"]
    ema_slow = indicator_bundle["ema_slow"]
    ema_direction = indicator_bundle["ema_direction"]
    ema_trades, ema_summary, ema_equity_curve = _run_direction_backtest(
        df_view,
        ema_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=ema_crossover_weekly_direction,
        confirmation_config=strategy_confirmation_config("ema_crossover"),
    )

    macd_line = indicator_bundle["macd_line"]
    signal_line = indicator_bundle["signal_line"]
    macd_hist = indicator_bundle["macd_hist"]
    macd_direction = indicator_bundle["macd_direction"]
    macd_trades, macd_summary, macd_equity_curve = _run_direction_backtest(
        df_view,
        macd_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=macd_weekly_direction,
        confirmation_config=strategy_confirmation_config("macd"),
    )

    donch_upper = indicator_bundle["donch_upper"]
    donch_lower = indicator_bundle["donch_lower"]
    donch_direction = indicator_bundle["donch_direction"]
    donch_trades, donch_summary, donch_equity_curve = _run_direction_backtest(
        df_view,
        donch_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=donchian_weekly_direction,
        confirmation_config=strategy_confirmation_config("donchian"),
    )
    corpus_stop_line = indicator_bundle["corpus_stop_line"]
    corpus_direction = indicator_bundle["corpus_direction"]
    corpus_trend_trades, corpus_trend_summary, corpus_trend_equity_curve = _run_corpus_trend_backtest(
        df_view,
        corpus_direction,
        corpus_stop_line,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=corpus_weekly_direction,
        confirmation_config=strategy_confirmation_config("corpus_trend"),
    )
    corpus_trend_layered_trades, corpus_trend_layered_summary, corpus_trend_layered_equity_curve = _run_corpus_trend_layered_backtest(
        df_view, corpus_direction, corpus_stop_line, df.index, df_view.index
    )

    cb50_direction = indicator_bundle["cb50_direction"]
    cb50_trades, cb50_summary, cb50_equity_curve = _run_direction_backtest(
        df_view,
        cb50_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=cb50_weekly_direction,
        confirmation_config=strategy_confirmation_config("cb50"),
    )

    cb150_direction = indicator_bundle["cb150_direction"]
    cb150_trades, cb150_summary, cb150_equity_curve = _run_direction_backtest(
        df_view,
        cb150_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=cb150_weekly_direction,
        confirmation_config=strategy_confirmation_config("cb150"),
    )

    sma_10_100_direction = indicator_bundle["sma_10_100_direction"]
    sma_10_100_trades, sma_10_100_summary, sma_10_100_equity_curve = _run_direction_backtest(
        df_view,
        sma_10_100_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=sma_10_100_weekly_direction,
        confirmation_config=strategy_confirmation_config("sma_10_100"),
    )

    sma_10_200_direction = indicator_bundle["sma_10_200_direction"]
    sma_10_200_trades, sma_10_200_summary, sma_10_200_equity_curve = _run_direction_backtest(
        df_view,
        sma_10_200_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=sma_10_200_weekly_direction,
        confirmation_config=strategy_confirmation_config("sma_10_200"),
    )

    ema_trend_direction = indicator_bundle["ema_trend_direction"]
    ema_trend_trades, ema_trend_summary, ema_trend_equity_curve = _run_direction_backtest(
        df_view,
        ema_trend_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=ema_trend_weekly_direction,
        confirmation_config=strategy_confirmation_config("ema_trend"),
    )

    yearly_ma_direction = indicator_bundle["yearly_ma_direction"]
    yearly_ma_trades, yearly_ma_summary, yearly_ma_equity_curve = _run_direction_backtest(
        df_view,
        yearly_ma_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=yearly_ma_weekly_direction,
        confirmation_config=strategy_confirmation_config("yearly_ma"),
    )

    bb_upper = indicator_bundle["bb_upper"]
    bb_mid = indicator_bundle["bb_mid"]
    bb_lower = indicator_bundle["bb_lower"]
    bb_direction = indicator_bundle["bb_direction"]
    bb_trades, bb_summary, bb_equity_curve = _run_direction_backtest(
        df_view,
        bb_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=bb_weekly_direction,
        confirmation_config=strategy_confirmation_config("bb_breakout"),
    )

    kelt_upper = indicator_bundle["kelt_upper"]
    kelt_mid = indicator_bundle["kelt_mid"]
    kelt_lower = indicator_bundle["kelt_lower"]
    kelt_direction = indicator_bundle["kelt_direction"]
    kelt_trades, kelt_summary, kelt_equity_curve = _run_direction_backtest(
        df_view,
        kelt_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=keltner_weekly_direction,
        confirmation_config=strategy_confirmation_config("keltner"),
    )
    weekly_core_overlay_profile = _core_overlay_profile(ticker)
    weekly_core_overlay_core_key = weekly_core_overlay_profile["core"]
    weekly_core_overlay_overlay_key = weekly_core_overlay_profile["overlay"]
    weekly_core_overlay_core_fraction = float(
        weekly_core_overlay_profile.get("core_fraction", 0.70)
    )
    weekly_core_overlay_overlay_fraction = float(
        weekly_core_overlay_profile.get("overlay_fraction", 0.30)
    )
    weekly_core_overlay_core_direction = {
        "cb150": cb150_weekly_direction if weekly_confirmation_supported else cb150_direction,
        "donchian": donchian_weekly_direction if weekly_confirmation_supported else donch_direction,
        "macd": macd_weekly_direction if weekly_confirmation_supported else macd_direction,
    }.get(weekly_core_overlay_core_key, cb150_direction)
    weekly_core_overlay_overlay_direction = {
        "donchian": donch_direction,
        "keltner": kelt_direction,
    }.get(weekly_core_overlay_overlay_key, donch_direction)
    weekly_core_overlay_trades, weekly_core_overlay_summary, weekly_core_overlay_equity_curve = _run_weekly_core_overlay_backtest(
        df_view,
        weekly_core_overlay_core_direction,
        weekly_core_overlay_overlay_direction,
        df.index,
        df_view.index,
        core_fraction=weekly_core_overlay_core_fraction,
        overlay_fraction=weekly_core_overlay_overlay_fraction,
    )

    psar_line = indicator_bundle["psar_line"]
    psar_direction = indicator_bundle["psar_direction"]
    psar_trades, psar_summary, psar_equity_curve = _run_direction_backtest(
        df_view,
        psar_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=psar_weekly_direction,
        confirmation_config=strategy_confirmation_config("parabolic_sar"),
    )

    cci_val = indicator_bundle["cci_val"]
    cci_direction = indicator_bundle["cci_direction"]
    cci_trades, cci_summary, cci_equity_curve = _run_direction_backtest(
        df_view,
        cci_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=cci_weekly_direction,
        confirmation_config=strategy_confirmation_config("cci_trend"),
    )
    cci_hyst_direction = indicator_bundle["cci_hyst_direction"]
    cci_hyst_trades, cci_hyst_summary, cci_hyst_equity_curve = _run_direction_backtest(
        df_view,
        cci_hyst_direction,
        df.index,
        df_view.index,
        active_mm_config,
        strategy_key="cci_hysteresis",
    )

    orb_range_high = indicator_bundle["orb_range_high"]
    orb_range_low = indicator_bundle["orb_range_low"]
    orb_range_mid = indicator_bundle["orb_range_mid"]
    orb_trend_ema = indicator_bundle["orb_trend_ema"]
    orb_direction = indicator_bundle["orb_direction"]
    orb_trades, orb_summary, orb_equity_curve = _run_direction_backtest(
        df_view,
        orb_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=orb_weekly_direction,
        confirmation_config=strategy_confirmation_config("orb_breakout"),
    )

    # Polymarket prediction-market signal
    from lib.polymarket import compute_polymarket_direction_series, load_probability_history
    poly_history = load_probability_history(auto_seed=True)
    poly_direction = compute_polymarket_direction_series(df, poly_history)
    poly_trades, poly_summary, poly_equity_curve = _run_direction_backtest(
        df_view, poly_direction, df.index, df_view.index, active_mm_config
    )

    ribbon_center = indicator_bundle["ribbon_center"]
    ribbon_upper = indicator_bundle["ribbon_upper"]
    ribbon_lower = indicator_bundle["ribbon_lower"]
    ribbon_strength = indicator_bundle["ribbon_strength"]
    ribbon_dir = indicator_bundle["ribbon_dir"]
    ribbon_backtest_direction = _carry_neutral_direction(ribbon_dir)
    ribbon_trades, ribbon_summary, ribbon_equity_curve = _run_direction_backtest(
        df_view,
        ribbon_backtest_direction,
        df.index,
        df_view.index,
        active_mm_config,
        weekly_direction=ribbon_weekly_direction,
        confirmation_config=strategy_confirmation_config("ribbon"),
    )
    ribbon_hold_equity_curve = None
    mark_phase("indicators_ms")

    # --- Daily flips ---
    if interval == "1d":
        daily_flips = indicator_bundle["daily_flips"]
    else:
        try:
            kwargs_d = {"start": _warmup_start(start, "1d"), "interval": "1d", "progress": False}
            if end:
                kwargs_d["end"] = end
            df_d = cached_download(data_ticker, **kwargs_d)
            if isinstance(df_d.columns, pd.MultiIndex):
                df_d.columns = df_d.columns.get_level_values(0)
            if df_d.index.duplicated().any():
                df_d = df_d[~df_d.index.duplicated(keep="last")]
            daily_flips = compute_all_trend_flips(
                df_d,
                period_val=period_val,
                multiplier_val=multiplier_val,
                ribbon_kwargs=_trend_ribbon_kwargs(ticker),
            )
        except Exception:
            daily_flips = {}
    mark_phase("daily_flips_ms")

    # --- Candles ---
    candles = _ohlcv_df_to_candles(df_view)

    # --- Supertrend lines ---
    st_up = []
    st_down = []
    for i in range(len(df_view)):
        if pd.isna(supertrend_view.iloc[i]):
            continue
        ts = int(df_view.index[i].timestamp())
        val = round(float(supertrend_view.iloc[i]), 2)
        body_mid = round(float((df_view["Open"].iloc[i] + df_view["Close"].iloc[i]) / 2), 2)
        if direction_view.iloc[i] == 1:
            st_up.append({"time": ts, "value": val, "mid": body_mid})
            st_down.append({"time": ts})
        else:
            st_up.append({"time": ts})
            st_down.append({"time": ts, "value": val, "mid": body_mid})

    # --- Supertrend backtest ---
    trades, summary, equity_curve = _run_direction_backtest(
        df_view, direction, df.index, df_view.index, active_mm_config
    )
    buy_hold_equity_curve = build_buy_hold_equity_curve(df_view)
    markers = []
    for t in trades:
        entry_ts = int(pd.Timestamp(t["entry_date"]).timestamp())
        exit_ts = int(pd.Timestamp(t["exit_date"]).timestamp())
        markers.append(
            {
                "time": entry_ts,
                "position": "belowBar",
                "color": "#2196F3",
                "shape": "arrowUp",
                "text": f"BUY {t['entry_price']}",
            }
        )
        if not t.get("open"):
            markers.append(
                {
                    "time": exit_ts,
                    "position": "aboveBar",
                    "color": "#e91e63",
                    "shape": "arrowDown",
                    "text": f"SELL {t['exit_price']} ({t['pnl']:+.2f})",
                }
            )

    # --- SMAs ---
    smas = {}
    for sma_period in [50, 100, 180, 200]:
        sma = df["Close"].rolling(window=sma_period).mean()
        sma_view = sma.loc[df_view.index]
        sma_data = []
        for i in range(len(df_view)):
            if pd.isna(sma_view.iloc[i]):
                continue
            sma_data.append(
                {
                    "time": int(df_view.index[i].timestamp()),
                    "value": round(float(sma_view.iloc[i]), 2),
                }
            )
        smas[f"sma_{sma_period}"] = sma_data

    # --- Weekly SMAs and flips ---
    sma_50w = []
    sma_100w = []
    sma_200w = []
    weekly_flips = {}
    try:
        if source_interval == "1wk":
            df_w = source_df.copy()
        else:
            df_w = _resample_ohlcv(source_df, "W-FRI")
        if not df_w.empty:
            if isinstance(df_w.columns, pd.MultiIndex):
                df_w.columns = df_w.columns.get_level_values(0)
            if df_w.index.duplicated().any():
                df_w = df_w[~df_w.index.duplicated(keep="last")]
            df_w_view = df_w.loc[_visible_mask(df_w.index, start, end)]
            weekly_bundle, weekly_bundle_hit = _get_weekly_bundle(
                ticker,
                df_w,
                period_val,
                multiplier_val,
            )
            sma_w50 = weekly_bundle["sma_w50"]
            sma_w100 = weekly_bundle["sma_w100"]
            sma_w200 = weekly_bundle["sma_w200"]
            sma_w50_view = sma_w50.loc[df_w_view.index]
            sma_w100_view = sma_w100.loc[df_w_view.index]
            sma_w200_view = sma_w200.loc[df_w_view.index]
            for i in range(len(df_w_view)):
                ts = int(df_w_view.index[i].timestamp())
                if not pd.isna(sma_w50_view.iloc[i]):
                    sma_50w.append({"time": ts, "value": round(float(sma_w50_view.iloc[i]), 2)})
                if not pd.isna(sma_w100_view.iloc[i]):
                    sma_100w.append({"time": ts, "value": round(float(sma_w100_view.iloc[i]), 2)})
                if not pd.isna(sma_w200_view.iloc[i]):
                    sma_200w.append({"time": ts, "value": round(float(sma_w200_view.iloc[i]), 2)})
            if interval == "1wk":
                weekly_flips = indicator_bundle["daily_flips"]
            else:
                weekly_flips = weekly_bundle["weekly_flips"]
            if interval == "1d":
                daily_ribbon_direction = _carry_neutral_direction(ribbon_dir)
                weekly_ribbon_direction = _align_weekly_direction_to_daily(
                    weekly_bundle["ribbon_dir"],
                    df.index,
                )
                if strategy_confirmation_config("ribbon"):
                    ribbon_backtest_direction = daily_ribbon_direction
                else:
                    ribbon_regime_kwargs = trend_ribbon_regime_kwargs(ticker)
                    confirmed_ribbon_direction = build_weekly_confirmed_ribbon_direction(
                        daily_ribbon_direction,
                        weekly_ribbon_direction,
                        reentry_cooldown_bars=ribbon_regime_kwargs[
                            "reentry_cooldown_bars"
                        ],
                        reentry_cooldown_ratio=ribbon_regime_kwargs[
                            "reentry_cooldown_ratio"
                        ],
                        weekly_nonbull_confirm_bars=ribbon_regime_kwargs[
                            "weekly_nonbull_confirm_bars"
                        ],
                        asymmetric_exit=ribbon_regime_kwargs.get(
                            "asymmetric_exit", False
                        ),
                    )
                    ribbon_backtest_direction = confirmed_ribbon_direction
                    (
                        ribbon_trades,
                        ribbon_summary,
                        ribbon_equity_curve,
                    ) = _run_ribbon_regime_backtest(
                        df_view,
                        confirmed_ribbon_direction,
                        df.index,
                        df_view.index,
                        active_mm_config,
                    )
                ribbon_hold_equity_curve = buy_hold_equity_curve
    except Exception:
        current_app.logger.exception(
            "chart_data weekly_ms failed ticker=%s interval=%s (ribbon falls back to daily-only)",
            ticker,
            interval,
        )
    mark_phase("weekly_ms")

    # --- Support / Resistance levels ---
    sr_levels = compute_support_resistance(df, max_levels=20)
    mark_phase("support_resistance_ms")

    # --- Volumes ---
    volumes = []
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        c = df_view["Close"].iloc[i]
        o = df_view["Open"].iloc[i]
        volumes.append(
            {
                "time": ts,
                "value": int(df_view["Volume"].iloc[i]),
                "color": "rgba(38,166,154,0.5)" if c >= o else "rgba(239,83,80,0.5)",
            }
        )

    # --- EMA lines ---
    ema9_data = []
    ema21_data = []
    ema_fast_view = ema_fast.loc[df_view.index]
    ema_slow_view = ema_slow.loc[df_view.index]
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        if not pd.isna(ema_fast_view.iloc[i]):
            ema9_data.append({"time": ts, "value": round(float(ema_fast_view.iloc[i]), 2)})
        if not pd.isna(ema_slow_view.iloc[i]):
            ema21_data.append({"time": ts, "value": round(float(ema_slow_view.iloc[i]), 2)})

    # --- MACD ---
    macd_line_data = []
    signal_line_data = []
    macd_hist_data = []
    macd_line_view = macd_line.loc[df_view.index]
    signal_line_view = signal_line.loc[df_view.index]
    macd_hist_view = macd_hist.loc[df_view.index]
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        if not pd.isna(macd_line_view.iloc[i]):
            macd_line_data.append({"time": ts, "value": round(float(macd_line_view.iloc[i]), 2)})
        if not pd.isna(signal_line_view.iloc[i]):
            signal_line_data.append({"time": ts, "value": round(float(signal_line_view.iloc[i]), 2)})
        if not pd.isna(macd_hist_view.iloc[i]):
            macd_hist_data.append(
                {
                    "time": ts,
                    "value": round(float(macd_hist_view.iloc[i]), 2),
                    "color": "rgba(38,166,154,0.7)" if macd_hist_view.iloc[i] >= 0 else "rgba(239,83,80,0.7)",
                }
            )

    # --- Channel overlays ---
    donch_upper_data = series_to_json(donch_upper, df_view.index)
    donch_lower_data = series_to_json(donch_lower, df_view.index)
    bb_upper_data = series_to_json(bb_upper, df_view.index)
    bb_mid_data = series_to_json(bb_mid, df_view.index)
    bb_lower_data = series_to_json(bb_lower, df_view.index)
    kelt_upper_data = series_to_json(kelt_upper, df_view.index)
    kelt_mid_data = series_to_json(kelt_mid, df_view.index)
    kelt_lower_data = series_to_json(kelt_lower, df_view.index)

    # --- Parabolic SAR ---
    psar_bull_data = []
    psar_bear_data = []
    psar_view = psar_line.loc[df_view.index]
    psar_dir_view = psar_direction.loc[df_view.index]
    for i in range(len(df_view)):
        v = psar_view.iloc[i]
        if pd.isna(v):
            continue
        pt = {"time": int(df_view.index[i].timestamp()), "value": round(float(v), 2)}
        if psar_dir_view.iloc[i] == 1:
            psar_bull_data.append(pt)
        else:
            psar_bear_data.append(pt)

    # --- CCI ---
    cci_data = series_to_json(cci_val, df_view.index)

    # --- ORB ---
    orb_high_data = series_to_json(orb_range_high, df_view.index)
    orb_low_data = series_to_json(orb_range_low, df_view.index)
    orb_mid_data = series_to_json(orb_range_mid, df_view.index)

    # --- Trend ribbon ---
    ribbon_upper_data = []
    ribbon_lower_data = []
    r_upper_view = ribbon_upper.loc[df_view.index]
    r_lower_view = ribbon_lower.loc[df_view.index]
    r_dir_view = ribbon_dir.loc[df_view.index]
    r_strength_view = ribbon_strength.loc[df_view.index]
    for i in range(len(df_view)):
        ts = int(df_view.index[i].timestamp())
        u, lo, d, s = r_upper_view.iloc[i], r_lower_view.iloc[i], r_dir_view.iloc[i], r_strength_view.iloc[i]
        if pd.isna(u) or pd.isna(lo):
            continue
        alpha = max(0.15, min(0.6, float(s) * 0.7))
        if d >= 0:
            color = f"rgba(0,230,138,{alpha:.2f})"
            line_color = "rgba(0,230,138,0.8)"
        else:
            color = f"rgba(255,82,116,{alpha:.2f})"
            line_color = "rgba(255,82,116,0.8)"
        ribbon_upper_data.append({"time": ts, "value": round(float(u), 2), "color": color, "lineColor": line_color})
        ribbon_lower_data.append({"time": ts, "value": round(float(lo), 2), "color": color, "lineColor": line_color})

    ribbon_center_data = series_to_json(ribbon_center, df_view.index)
    vol_profile = build_volume_profile(df_view)
    window_meta_config = None if confirmation_config else active_mm_config

    # --- Build payload ---
    payload = {
        "ticker_name": ticker_name,
        "candles": candles,
        "supertrend_up": st_up,
        "supertrend_down": st_down,
        "volumes": volumes,
        "markers": markers,
        "trades": trades,
        "summary": summary,
        "equity_curve": equity_curve,
        "buy_hold_equity_curve": buy_hold_equity_curve,
        **smas,
        "sma_50w": sma_50w,
        "sma_100w": sma_100w,
        "sma_200w": sma_200w,
        "strategies": {
            "ribbon": _strategy_payload(
                ribbon_trades,
                ribbon_summary,
                ribbon_equity_curve,
                buy_hold_equity_curve=ribbon_hold_equity_curve or buy_hold_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        ribbon_backtest_direction, df.index, df_view.index, window_meta_config
                    ),
                    strategy_confirmation_meta("ribbon"),
                ),
            ),
            "corpus_trend": _strategy_payload(
                corpus_trend_trades,
                corpus_trend_summary,
                corpus_trend_equity_curve,
                buy_hold_equity_curve=buy_hold_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        corpus_direction, df.index, df_view.index, window_meta_config
                    ),
                    strategy_confirmation_meta("corpus_trend"),
                ),
            ),
            "corpus_trend_layered": _strategy_payload(
                corpus_trend_layered_trades,
                corpus_trend_layered_summary,
                corpus_trend_layered_equity_curve,
                buy_hold_equity_curve=buy_hold_equity_curve,
                backtest_meta=_confirmation_meta(
                    confirmation_config,
                    supported=False,
                ),
            ),
            "cci_hysteresis": _strategy_payload(
                cci_hyst_trades,
                cci_hyst_summary,
                cci_hyst_equity_curve,
                buy_hold_equity_curve=buy_hold_equity_curve,
                backtest_meta=_confirmation_meta(
                    confirmation_config,
                    supported=False,
                ),
            ),
            "polymarket": _strategy_payload(
                poly_trades,
                poly_summary,
                poly_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        poly_direction, df.index, df_view.index, window_meta_config
                    ),
                    _confirmation_meta(
                        confirmation_config,
                        supported=False,
                    ),
                ),
            ),
        },
        "ema9": ema9_data,
        "ema21": ema21_data,
        "macd_line": macd_line_data,
        "signal_line": signal_line_data,
        "macd_hist": macd_hist_data,
        "sr_levels": sr_levels,
        "overlays": {
            "donchian": {"upper": donch_upper_data, "lower": donch_lower_data},
            "bb": {"upper": bb_upper_data, "mid": bb_mid_data, "lower": bb_lower_data},
            "keltner": {"upper": kelt_upper_data, "mid": kelt_mid_data, "lower": kelt_lower_data},
            "psar": {"bull": psar_bull_data, "bear": psar_bear_data},
            "cci": {"cci": cci_data},
            "orb": {"upper": orb_high_data, "lower": orb_low_data, "mid": orb_mid_data},
            "ribbon": {"upper": ribbon_upper_data, "lower": ribbon_lower_data, "center": ribbon_center_data},
        },
        "vol_profile": vol_profile,
        "trend_flips": {"daily": daily_flips, "weekly": weekly_flips},
    }
    mark_phase("payload_ms")
    _cache_set(chart_cache_key, payload, ttl=_CHART_CACHE_TTL)
    current_app.logger.info(
        "chart_data timings ticker=%s interval=%s range=%s..%s rows=%s view_rows=%s indicator_bundle_hit=%s weekly_bundle_hit=%s metadata_ms=%s fetch_ms=%s frame_ms=%s indicators_ms=%s daily_flips_ms=%s weekly_ms=%s support_resistance_ms=%s payload_ms=%s total_ms=%s",
        ticker,
        interval,
        start,
        end or "latest",
        len(df),
        len(df_view),
        indicator_bundle_hit,
        weekly_bundle_hit,
        timings_ms.get("metadata_ms", 0),
        timings_ms.get("fetch_ms", 0),
        timings_ms.get("frame_ms", 0),
        timings_ms.get("indicators_ms", 0),
        timings_ms.get("daily_flips_ms", 0),
        timings_ms.get("weekly_ms", 0),
        timings_ms.get("support_resistance_ms", 0),
        timings_ms.get("payload_ms", 0),
        _elapsed_ms(request_started_at),
    )
    return jsonify(payload)
