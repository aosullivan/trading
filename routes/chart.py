import concurrent.futures
import hashlib
import json
import os
import pickle
import threading
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
    _disk_cache_path,
    _meta_path,
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
    compute_supertrend_i,
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
    backtest_direction_vectorized,
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
from lib.trade_setup import compute_trade_setup
from lib.specialized_strategies import (
    EMA_9_26_KEY,
    SEMIS_PERSIST_KEY,
    compute_ema_9_26_strategy,
    compute_semis_persist_strategy,
    specialized_strategy_backtest_meta,
)
from lib.trend_sr_macro_strategy import (
    TREND_SR_MACRO_KEY,
    compute_trend_sr_macro_strategy,
    trend_sr_macro_backtest_meta,
    trend_sr_macro_confirmation_config,
)
from lib.paths import get_user_data_path

bp = Blueprint("chart", __name__)
_CHART_PAYLOAD_CACHE_VERSION = 2
_CHART_INTERACTIVE_IDLE_SECONDS = 30
_chart_activity_lock = threading.Lock()
_last_interactive_chart_request_at = 0.0


def _mark_interactive_chart_request() -> None:
    global _last_interactive_chart_request_at
    with _chart_activity_lock:
        _last_interactive_chart_request_at = time.monotonic()


def chart_interactive_recently(window_seconds: int = _CHART_INTERACTIVE_IDLE_SECONDS) -> bool:
    with _chart_activity_lock:
        last_seen = _last_interactive_chart_request_at
    return bool(last_seen and (time.monotonic() - last_seen) < window_seconds)

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
        "supertrend_i",
        "bb_breakout",
        "ema_crossover",
        EMA_9_26_KEY,
        "cci_trend",
    }
)


def _elapsed_ms(started_at: float) -> int:
    return int(round((time.perf_counter() - started_at) * 1000))


def _chart_payload_cache_dir() -> str:
    path = get_user_data_path("data_cache", "chart_payloads")
    os.makedirs(path, exist_ok=True)
    return path


def _chart_payload_cache_scope(end: str) -> dict[str, str]:
    """Return the validity scope for a payload cache entry.

    Previously this tagged "live" entries with the current local day and
    invalidated them at every midnight, forcing a full recompute on the first
    click of the day. The cache key now includes the source-frame signature
    (see `_frame_signature`), so entries stay valid as long as the underlying
    bars haven't changed — making a calendar-day check redundant.
    """
    if not end:
        return {"mode": "live"}
    try:
        requested_end = _parse_end_date(end)
    except Exception:
        return {"mode": "live"}
    if requested_end is None or requested_end >= pd.Timestamp.now().tz_localize(None).normalize():
        return {"mode": "live"}
    return {"mode": "historical"}


def _source_data_token(ticker: str, interval: str) -> str:
    """Freshness fingerprint for a ticker's source-data CSV cache.

    Cheap — one metadata JSON read. The token changes when the cached source
    frame's content signature changes, not merely when another path rewrites
    the same CSV. That keeps prebuilt chart payloads valid across harmless
    quote refreshes while still invalidating them when a new/changed bar lands.
    """
    try:
        meta_path = _meta_path(ticker, interval)
        with open(meta_path) as handle:
            meta = json.load(handle)
        signature = meta.get("data_signature")
        if signature:
            return f"sig:{signature}"
    except Exception:
        pass
    try:
        path = _disk_cache_path(ticker, interval)
    except Exception:
        return "no-path"
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "no-file"


_CHART_PAYLOAD_CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600  # prune files older than a week


def _prune_chart_payload_cache_dir(max_age_seconds: int = _CHART_PAYLOAD_CACHE_MAX_AGE_SECONDS):
    """Delete cache files that haven't been touched in ``max_age_seconds``.

    Cheap best-effort pass (one `os.scandir`) invoked from the write path so
    the directory doesn't grow forever now that entries survive day rollovers.
    """
    try:
        cutoff = time.time() - max_age_seconds
        with os.scandir(_chart_payload_cache_dir()) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                try:
                    if entry.stat().st_mtime < cutoff:
                        os.remove(entry.path)
                except OSError:
                    continue
    except OSError:
        return


def _chart_payload_cache_path(kind: str, cache_key: str) -> str:
    digest = hashlib.sha256(
        f"{_CHART_PAYLOAD_CACHE_VERSION}:{kind}:{cache_key}".encode("utf-8")
    ).hexdigest()
    return os.path.join(_chart_payload_cache_dir(), f"{kind}_{digest}.json")


def _read_chart_payload_cache(kind: str, cache_key: str, end: str) -> dict | None:
    path = _chart_payload_cache_path(kind, cache_key)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as handle:
            wrapper = json.load(handle)
    except Exception:
        return None

    meta = wrapper.get("meta") or {}
    scope = _chart_payload_cache_scope(end)
    if meta.get("version") != _CHART_PAYLOAD_CACHE_VERSION:
        return None
    if meta.get("mode") != scope["mode"]:
        return None

    payload = wrapper.get("payload")
    return payload if isinstance(payload, dict) else None


def _write_chart_payload_cache(kind: str, cache_key: str, end: str, payload: dict):
    path = _chart_payload_cache_path(kind, cache_key)
    wrapper = {
        "meta": {
            "version": _CHART_PAYLOAD_CACHE_VERSION,
            **_chart_payload_cache_scope(end),
            "cached_at": int(time.time()),
        },
        "payload": payload,
    }
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w") as handle:
            json.dump(wrapper, handle)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    # Best-effort garbage collection so the directory doesn't grow forever now
    # that entries aren't auto-invalidated by calendar-day changes.
    _prune_chart_payload_cache_dir()


# ---------------------------------------------------------------------------
# Intermediate-bundle disk cache
# ---------------------------------------------------------------------------
# `_get_indicator_bundle`, `_get_weekly_bundle`, and `_get_sr_and_trade_setup`
# memoize their results in `_cache` (in-memory, 5-min TTL). That's enough
# within a session, but `_cache` is empty after a restart, so any request
# that doesn't exactly match a disk-cached chart payload (e.g. user toggled
# an MM setting, or changed the ST period) re-pays the full compute cost.
#
# These helpers add a second tier: a pickle-based on-disk spill. Pickle is
# used because the bundles contain `pd.Series` objects — round-tripping
# through JSON would cost more than the compute we're trying to skip.
# `_BUNDLE_DISK_CACHE_VERSION` is baked into the file digest so a bump
# invalidates stale files across Python/pandas ABI changes.
_BUNDLE_DISK_CACHE_VERSION = "bundle-v2"


def _bundle_disk_cache_dir() -> str:
    path = get_user_data_path("data_cache", "bundle_cache")
    os.makedirs(path, exist_ok=True)
    return path


def _bundle_disk_cache_path(cache_key: str) -> str:
    digest = hashlib.sha256(
        f"{_BUNDLE_DISK_CACHE_VERSION}:{cache_key}".encode("utf-8")
    ).hexdigest()
    return os.path.join(_bundle_disk_cache_dir(), f"{digest}.pkl")


def _read_bundle_disk_cache(cache_key: str):
    path = _bundle_disk_cache_path(cache_key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            return pickle.load(handle)
    except Exception:
        # Corrupt file, pickle-protocol mismatch, or pandas ABI change.
        # Treat as a cache miss; the next write will overwrite it cleanly.
        return None


def _write_bundle_disk_cache(cache_key: str, bundle) -> None:
    path = _bundle_disk_cache_path(cache_key)
    tmp_path = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        with open(tmp_path, "wb") as handle:
            pickle.dump(bundle, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    _prune_bundle_disk_cache_dir()


def _prune_bundle_disk_cache_dir(
    max_age_seconds: int = _CHART_PAYLOAD_CACHE_MAX_AGE_SECONDS,
) -> None:
    """Delete bundle-cache files untouched for ``max_age_seconds`` (default: 7d)."""
    try:
        cutoff = time.time() - max_age_seconds
        with os.scandir(_bundle_disk_cache_dir()) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                try:
                    if entry.stat().st_mtime < cutoff:
                        os.remove(entry.path)
                except OSError:
                    continue
    except OSError:
        return


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


_STRATEGY_TASK_KEYS = {
    "ribbon": "ribbon",
    "corpus_trend": "corpus_trend",
    "corpus_trend_layered": "corpus_trend_layered",
    "weekly_core_overlay_v1": "weekly_core_overlay",
    "supertrend_i": "supertrend_i",
    "bb_breakout": "bb",
    "ema_crossover": "ema",
    EMA_9_26_KEY: "ema_9_26",
    "cci_trend": "cci",
    "cci_hysteresis": "cci_hyst",
    SEMIS_PERSIST_KEY: "semis_persist",
    TREND_SR_MACRO_KEY: "trend_sr_macro",
    "polymarket": "poly",
}


def _normalize_requested_strategy(strategy: str | None) -> str:
    key = (strategy or "ribbon").strip()
    return key if key in _STRATEGY_TASK_KEYS else "ribbon"


def _supertrend_segments_for_view(
    df_view: pd.DataFrame,
    supertrend: pd.Series,
    direction: pd.Series,
) -> tuple[list[dict], list[dict]]:
    up = []
    down = []
    supertrend_view = supertrend.loc[df_view.index]
    direction_view = direction.loc[df_view.index]
    for i in range(len(df_view)):
        if pd.isna(supertrend_view.iloc[i]):
            continue
        ts = int(df_view.index[i].timestamp())
        val = round(float(supertrend_view.iloc[i]), 2)
        body_mid = round(
            float((df_view["Open"].iloc[i] + df_view["Close"].iloc[i]) / 2),
            2,
        )
        if direction_view.iloc[i] == 1:
            up.append({"time": ts, "value": val, "mid": body_mid})
            down.append({"time": ts})
        else:
            up.append({"time": ts})
            down.append({"time": ts, "value": val, "mid": body_mid})
    return up, down


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
    # mm_config is always passed explicitly by chart_data; no request-context
    # fallback here because this helper can be invoked from a ThreadPoolExecutor
    # worker where `request` is not bound.
    if mm_config is not None:
        managed_kwargs = _managed_backtest_kwargs(prior_direction, mm_config)
        return backtest_managed(
            df_view,
            direction.loc[view_index],
            config=mm_config,
            **managed_kwargs,
        )
    # Default path (no MM, no confirmation): use the vectorized backtest.
    # Parity with the iterative `backtest_direction` is verified by
    # tests/test_backtest_vectorized_parity.py.
    return backtest_direction_vectorized(
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
    # mm_config is always passed explicitly by chart_data; no request-context
    # fallback here because this helper can be invoked from a ThreadPoolExecutor
    # worker where `request` is not bound.
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
    # mm_config is always passed explicitly by chart_data; no request-context
    # fallback here because this helper can be invoked from a ThreadPoolExecutor
    # worker where `request` is not bound.
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
    disk_cached = _read_bundle_disk_cache(cache_key)
    if disk_cached is not None:
        _cache_set(cache_key, disk_cached, ttl=_CHART_CACHE_TTL)
        return disk_cached, True

    supertrend, direction = compute_supertrend(df, period_val, multiplier_val)
    supertrend_i, supertrend_i_direction = compute_supertrend_i(
        df,
        period_val,
        multiplier_val,
    )
    ema_fast, ema_slow, ema_direction = compute_ema_crossover(
        df,
        EMA_FAST_PERIOD,
        EMA_SLOW_PERIOD,
    )
    ema_9_26_bundle = compute_ema_9_26_strategy(df)
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
    semis_persist_bundle = compute_semis_persist_strategy(df)
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
        "supertrend_i": supertrend_i_direction,
        "ema_crossover": ema_direction,
        EMA_9_26_KEY: ema_9_26_bundle["daily_direction"],
        "macd": macd_direction,
        "donchian": donch_direction,
        "corpus_trend": corpus_direction,
        "bb_breakout": bb_direction,
        "keltner": kelt_direction,
        "parabolic_sar": psar_direction,
        "cci_trend": cci_direction,
        "cci_hysteresis": cci_hyst_direction,
        SEMIS_PERSIST_KEY: semis_persist_bundle["daily_direction"],
        "orb_breakout": orb_direction,
        "ribbon": ribbon_dir,
    }
    bundle = {
        "supertrend": supertrend,
        "direction": direction,
        "supertrend_i": supertrend_i,
        "supertrend_i_direction": supertrend_i_direction,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_direction": ema_direction,
        "ema_9_26_fast": ema_9_26_bundle["ema_fast"],
        "ema_9_26_slow": ema_9_26_bundle["ema_slow"],
        "ema_9_26_direction": ema_9_26_bundle["daily_direction"],
        "ema_9_26_weekly_direction": ema_9_26_bundle["weekly_direction"],
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
        "semis_persist_fast": semis_persist_bundle["ema_fast"],
        "semis_persist_slow": semis_persist_bundle["ema_slow"],
        "semis_persist_breakout_high": semis_persist_bundle["breakout_high"],
        "semis_persist_exit_low": semis_persist_bundle["exit_low"],
        "semis_persist_direction": semis_persist_bundle["daily_direction"],
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
        "daily_flips": compute_all_trend_flips(
            df,
            period_val=period_val,
            multiplier_val=multiplier_val,
            ribbon_kwargs=_trend_ribbon_kwargs(ticker),
            ticker=ticker,
        ),
    }
    _cache_set(cache_key, bundle, ttl=_CHART_CACHE_TTL)
    _write_bundle_disk_cache(cache_key, bundle)
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
    disk_cached = _read_bundle_disk_cache(cache_key)
    if disk_cached is not None:
        _cache_set(cache_key, disk_cached, ttl=_CHART_CACHE_TTL)
        return disk_cached, True

    _supertrend, supertrend_direction = compute_supertrend(
        df_w,
        period_val,
        multiplier_val,
    )
    _supertrend_i, supertrend_i_direction = compute_supertrend_i(
        df_w,
        period_val,
        multiplier_val,
    )
    _ema_fast, _ema_slow, ema_direction = compute_ema_crossover(
        df_w,
        EMA_FAST_PERIOD,
        EMA_SLOW_PERIOD,
    )
    _ema_9_26_fast, _ema_9_26_slow, ema_9_26_direction = compute_ema_crossover(
        df_w,
        9,
        26,
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
        "supertrend_i": supertrend_i_direction,
        "ema_crossover": ema_direction,
        EMA_9_26_KEY: ema_9_26_direction,
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
            ticker=ticker,
        ),
    }
    _cache_set(cache_key, bundle, ttl=_CHART_CACHE_TTL)
    _write_bundle_disk_cache(cache_key, bundle)
    return bundle, False


def _get_sr_and_trade_setup(
    ticker: str,
    df: pd.DataFrame,
    df_w: pd.DataFrame,
    daily_flips: dict,
    weekly_flips: dict,
) -> tuple[dict, bool]:
    """Memoize support/resistance levels + trade_setup together.

    `compute_trade_setup` internally calls `compute_support_resistance` again
    on the same daily frame — the two outputs share inputs, so caching them
    as a pair avoids that double scan and skips both calls on cache hit.
    """
    cache_key = (
        f"sr_trade_setup:{ticker}:{_frame_signature(df)}:"
        f"{_frame_signature(df_w) if df_w is not None and not df_w.empty else 'none'}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True
    disk_cached = _read_bundle_disk_cache(cache_key)
    if disk_cached is not None:
        _cache_set(cache_key, disk_cached, ttl=_CHART_CACHE_TTL)
        return disk_cached, True

    sr_levels = compute_support_resistance(df, max_levels=20)
    trade_setup = compute_trade_setup(
        df,
        df_w,
        daily_flips,
        weekly_flips,
        ticker=ticker,
        sr_levels=sr_levels,
    )
    bundle = {"sr_levels": sr_levels, "trade_setup": trade_setup}
    _cache_set(cache_key, bundle, ttl=_CHART_CACHE_TTL)
    _write_bundle_disk_cache(cache_key, bundle)
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
    strategy_only = request.args.get("strategy_only", "").lower() in ("1", "true", "yes")
    include_shared = request.args.get("include_shared", "").lower() in ("1", "true", "yes")
    requested_strategy = _normalize_requested_strategy(request.args.get("strategy"))
    is_prewarm = request.args.get("prewarm", "").lower() in ("1", "true", "yes")
    cache_only = request.args.get("cache_only", "").lower() in ("1", "true", "yes")
    if not is_prewarm:
        _mark_interactive_chart_request()

    # Resolved ticker-name: cheap lookup against in-memory info cache; any
    # network fetch happens in a background thread.
    ticker_name = _resolve_cached_ticker_name(ticker)
    mark_phase("metadata_ms")

    # Cheap freshness token from the source CSV's mtime. Swaps the old
    # "invalidate every local midnight" scope with "invalidate whenever
    # cached_download touches the source file". A single stat() — ~µs.
    source_token = _source_data_token(data_ticker, source_interval)
    candles_cache_key = (
        f"chart:candles:{ticker}:{interval}:{start}:{end or 'latest'}:{source_token}"
    )
    chart_cache_key = (
        f"chart:{ticker}:{interval}:{start}:{end}:{period_val}:{multiplier_val}:"
        f"{trend_ribbon_profile_signature(ticker)}:{mm_sig}:{source_token}"
    )
    strategy_cache_kind = "strategy_shared" if include_shared else "strategy"
    strategy_cache_key = (
        f"chart:{strategy_cache_kind}:{ticker}:{interval}:{start}:{end}:"
        f"{period_val}:{multiplier_val}:{trend_ribbon_profile_signature(ticker)}:"
        f"{mm_sig}:{requested_strategy}:{source_token}"
    )
    strategy_shared_cache_key = (
        f"chart:strategy_shared:{ticker}:{interval}:{start}:{end}:"
        f"{period_val}:{multiplier_val}:{trend_ribbon_profile_signature(ticker)}:"
        f"{mm_sig}:{requested_strategy}:{source_token}"
    )
    if candles_only:
        cached_candles = _cache_get(candles_cache_key)
        if cached_candles is not None:
            if not cached_candles.get("ticker_name") and ticker_name:
                cached_candles = {**cached_candles, "ticker_name": ticker_name}
                _cache_set(candles_cache_key, cached_candles, ttl=_CHART_CACHE_TTL)
            current_app.logger.info(
                "chart_data candles_only_cache_hit ticker=%s interval=%s range=%s..%s total_ms=%s",
                ticker,
                interval,
                start,
                end or "latest",
                _elapsed_ms(request_started_at),
            )
            return jsonify(cached_candles)
        disk_cached_candles = _read_chart_payload_cache(
            "candles",
            candles_cache_key,
            end,
        )
        if disk_cached_candles is not None:
            if not disk_cached_candles.get("ticker_name") and ticker_name:
                disk_cached_candles = {**disk_cached_candles, "ticker_name": ticker_name}
                _write_chart_payload_cache("candles", candles_cache_key, end, disk_cached_candles)
            _cache_set(candles_cache_key, disk_cached_candles, ttl=_CHART_CACHE_TTL)
            current_app.logger.info(
                "chart_data candles_only_disk_cache_hit ticker=%s interval=%s range=%s..%s total_ms=%s",
                ticker,
                interval,
                start,
                end or "latest",
                _elapsed_ms(request_started_at),
            )
            return jsonify(disk_cached_candles)
    elif strategy_only:
        strategy_cache_candidates = [(strategy_cache_kind, strategy_cache_key)]
        if not include_shared:
            # A warmed `strategy_shared` payload contains the selected strategy
            # plus chart overlays. It is bigger than a plain strategy payload,
            # but it is still a local cache hit and avoids recomputing a
            # backtest when the user explores the strategy dropdown.
            strategy_cache_candidates.append(("strategy_shared", strategy_shared_cache_key))

        cached_strategy = None
        cached_strategy_kind = strategy_cache_kind
        for candidate_kind, candidate_key in strategy_cache_candidates:
            cached_strategy = _cache_get(candidate_key)
            if cached_strategy is not None:
                cached_strategy_kind = candidate_kind
                break
        if cached_strategy is not None:
            if not cached_strategy.get("ticker_name") and ticker_name:
                cached_strategy = {**cached_strategy, "ticker_name": ticker_name}
                _cache_set(strategy_cache_key, cached_strategy, ttl=_CHART_CACHE_TTL)
            current_app.logger.info(
                "chart_data %s_cache_hit ticker=%s interval=%s strategy=%s range=%s..%s total_ms=%s",
                cached_strategy_kind,
                ticker,
                interval,
                requested_strategy,
                start,
                end or "latest",
                _elapsed_ms(request_started_at),
            )
            return jsonify(cached_strategy)
        disk_cached_strategy = None
        disk_cached_strategy_kind = strategy_cache_kind
        disk_cached_strategy_key = strategy_cache_key
        for candidate_kind, candidate_key in strategy_cache_candidates:
            disk_cached_strategy = _read_chart_payload_cache(
                candidate_kind,
                candidate_key,
                end,
            )
            if disk_cached_strategy is not None:
                disk_cached_strategy_kind = candidate_kind
                disk_cached_strategy_key = candidate_key
                break
        if disk_cached_strategy is not None:
            if not disk_cached_strategy.get("ticker_name") and ticker_name:
                disk_cached_strategy = {**disk_cached_strategy, "ticker_name": ticker_name}
                _write_chart_payload_cache(
                    disk_cached_strategy_kind,
                    disk_cached_strategy_key,
                    end,
                    disk_cached_strategy,
                )
            _cache_set(strategy_cache_key, disk_cached_strategy, ttl=_CHART_CACHE_TTL)
            current_app.logger.info(
                "chart_data %s_disk_cache_hit ticker=%s interval=%s strategy=%s range=%s..%s total_ms=%s",
                disk_cached_strategy_kind,
                ticker,
                interval,
                requested_strategy,
                start,
                end or "latest",
                _elapsed_ms(request_started_at),
            )
            return jsonify(disk_cached_strategy)
    elif not strategy_only:
        cached_chart = _cache_get(chart_cache_key)
        if cached_chart is not None:
            if not cached_chart.get("ticker_name"):
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
        disk_cached_chart = _read_chart_payload_cache(
            "chart",
            chart_cache_key,
            end,
        )
        if disk_cached_chart is not None:
            if not disk_cached_chart.get("ticker_name"):
                if ticker_name:
                    disk_cached_chart = {**disk_cached_chart, "ticker_name": ticker_name}
                    _write_chart_payload_cache("chart", chart_cache_key, end, disk_cached_chart)
            _cache_set(chart_cache_key, disk_cached_chart, ttl=_CHART_CACHE_TTL)
            current_app.logger.info(
                "chart_data disk_cache_hit ticker=%s interval=%s range=%s..%s total_ms=%s",
                ticker,
                interval,
                start,
                end or "latest",
                _elapsed_ms(request_started_at),
            )
            return jsonify(disk_cached_chart)

    if cache_only:
        current_app.logger.info(
            "chart_data cache_only_miss ticker=%s interval=%s strategy=%s range=%s..%s total_ms=%s",
            ticker,
            interval,
            requested_strategy if strategy_only else "",
            start,
            end or "latest",
            _elapsed_ms(request_started_at),
        )
        return jsonify({"cache_miss": True})
    mark_phase("cache_lookup_ms")

    # Cache miss: fetch the source frame. `cached_download` already has its
    # own on-disk CSV cache plus a TTL-based in-memory cache, so this rarely
    # hits Yahoo — but when it does, the resulting CSV mtime bump ensures
    # the next request re-derives (`source_token` will differ).
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
            "chart_data fetch_error ticker=%s interval=%s range=%s..%s total_ms=%s error=%s",
            ticker,
            interval,
            start,
            end or "latest",
            _elapsed_ms(request_started_at),
            str(e),
        )
        return jsonify({"error": str(e)}), 400
    mark_phase("fetch_ms")

    if source_df.empty:
        current_app.logger.info(
            "chart_data empty_source ticker=%s interval=%s range=%s..%s total_ms=%s",
            ticker,
            interval,
            start,
            end or "latest",
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
            "chart_data empty_view ticker=%s interval=%s range=%s..%s total_ms=%s",
            ticker,
            interval,
            start,
            end or "latest",
            _elapsed_ms(request_started_at),
        )
        return jsonify({"error": f"No data for {ticker} in selected range"}), 400
    mark_phase("frame_ms")

    # Re-compute the token AFTER the fetch: `cached_download` may have just
    # touched the CSV (a new bar arrived), in which case we want to cache
    # the fresh payload under the new token so subsequent requests hit.
    post_fetch_token = _source_data_token(data_ticker, source_interval)
    if post_fetch_token != source_token:
        candles_cache_key = (
            f"chart:candles:{ticker}:{interval}:{start}:{end or 'latest'}:{post_fetch_token}"
        )
        chart_cache_key = (
            f"chart:{ticker}:{interval}:{start}:{end}:{period_val}:{multiplier_val}:"
            f"{trend_ribbon_profile_signature(ticker)}:{mm_sig}:{post_fetch_token}"
        )
        strategy_cache_key = (
            f"chart:{strategy_cache_kind}:{ticker}:{interval}:{start}:{end}:"
            f"{period_val}:{multiplier_val}:{trend_ribbon_profile_signature(ticker)}:"
            f"{mm_sig}:{requested_strategy}:{post_fetch_token}"
        )

    if candles_only:
        candles = _ohlcv_df_to_candles(df_view)
        payload = {"candles": candles, "ticker_name": ticker_name}
        _cache_set(candles_cache_key, payload, ttl=_CHART_CACHE_TTL)
        _write_chart_payload_cache("candles", candles_cache_key, end, payload)
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
    supertrend_i_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "supertrend_i", df.index
    )
    ema_crossover_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, "ema_crossover", df.index
    )
    ema_9_26_weekly_direction = _weekly_direction_for_strategy(
        weekly_bundle, EMA_9_26_KEY, df.index
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
    # --- Extract indicator series + other serialization inputs ---
    # These are plain dict lookups off `indicator_bundle`; cheap, needed by
    # both the backtest dispatch and later payload serialization.
    supertrend = indicator_bundle["supertrend"]
    direction = indicator_bundle["direction"]
    supertrend_i = indicator_bundle["supertrend_i"]
    supertrend_i_direction = indicator_bundle["supertrend_i_direction"]

    ema_fast = indicator_bundle["ema_fast"]
    ema_slow = indicator_bundle["ema_slow"]
    ema_direction = indicator_bundle["ema_direction"]
    ema_9_26_direction = indicator_bundle["ema_9_26_direction"]
    macd_line = indicator_bundle["macd_line"]
    signal_line = indicator_bundle["signal_line"]
    macd_hist = indicator_bundle["macd_hist"]
    macd_direction = indicator_bundle["macd_direction"]
    donch_upper = indicator_bundle["donch_upper"]
    donch_lower = indicator_bundle["donch_lower"]
    donch_direction = indicator_bundle["donch_direction"]
    corpus_stop_line = indicator_bundle["corpus_stop_line"]
    corpus_direction = indicator_bundle["corpus_direction"]
    cb50_direction = indicator_bundle["cb50_direction"]
    cb150_direction = indicator_bundle["cb150_direction"]
    sma_10_100_direction = indicator_bundle["sma_10_100_direction"]
    sma_10_200_direction = indicator_bundle["sma_10_200_direction"]
    ema_trend_direction = indicator_bundle["ema_trend_direction"]
    yearly_ma_direction = indicator_bundle["yearly_ma_direction"]
    bb_upper = indicator_bundle["bb_upper"]
    bb_mid = indicator_bundle["bb_mid"]
    bb_lower = indicator_bundle["bb_lower"]
    bb_direction = indicator_bundle["bb_direction"]
    kelt_upper = indicator_bundle["kelt_upper"]
    kelt_mid = indicator_bundle["kelt_mid"]
    kelt_lower = indicator_bundle["kelt_lower"]
    kelt_direction = indicator_bundle["kelt_direction"]
    psar_line = indicator_bundle["psar_line"]
    psar_direction = indicator_bundle["psar_direction"]
    cci_val = indicator_bundle["cci_val"]
    cci_direction = indicator_bundle["cci_direction"]
    cci_hyst_direction = indicator_bundle["cci_hyst_direction"]
    semis_persist_direction = indicator_bundle["semis_persist_direction"]
    orb_range_high = indicator_bundle["orb_range_high"]
    orb_range_low = indicator_bundle["orb_range_low"]
    orb_range_mid = indicator_bundle["orb_range_mid"]
    orb_trend_ema = indicator_bundle["orb_trend_ema"]
    orb_direction = indicator_bundle["orb_direction"]
    ribbon_center = indicator_bundle["ribbon_center"]
    ribbon_upper = indicator_bundle["ribbon_upper"]
    ribbon_lower = indicator_bundle["ribbon_lower"]
    ribbon_strength = indicator_bundle["ribbon_strength"]
    ribbon_dir = indicator_bundle["ribbon_dir"]
    ribbon_backtest_direction = _carry_neutral_direction(ribbon_dir)

    # --- Pre-dispatch compute that can't be parallelized ---
    # In strategy-only mode, skip expensive side strategies unless they are the
    # requested strategy. The full payload path still computes every strategy.
    needs_all_strategies = not strategy_only
    needs_trend_sr_macro = needs_all_strategies or requested_strategy == TREND_SR_MACRO_KEY
    needs_polymarket = needs_all_strategies or requested_strategy == "polymarket"

    trend_sr_macro_bundle = None
    trend_sr_macro_direction = pd.Series(0, index=df.index)
    trend_sr_macro_weekly_direction = None
    trend_sr_macro_confirm_cfg = None
    if needs_trend_sr_macro:
        trend_sr_macro_bundle = compute_trend_sr_macro_strategy(df)
        trend_sr_macro_direction = trend_sr_macro_bundle["daily_direction"]
        trend_sr_macro_weekly_direction = trend_sr_macro_bundle["weekly_direction"]
        trend_sr_macro_confirm_cfg = trend_sr_macro_confirmation_config()

    poly_direction = pd.Series(0, index=df.index)
    if needs_polymarket:
        from lib.polymarket import (
            compute_polymarket_direction_series,
            load_probability_history,
        )
        poly_history = load_probability_history(auto_seed=True)
        poly_direction = compute_polymarket_direction_series(df, poly_history)

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

    # --- Parallel backtest dispatch ---
    # The 22 calls below are independent: each reads the immutable
    # df_view/indicator/direction inputs and produces a (trades, summary,
    # equity_curve) tuple. `active_mm_config` and `confirmation_config` are
    # treated as read-only by the backtest helpers. Running them via a
    # ThreadPoolExecutor cuts wall-clock time by ~1.5-2x on the cold path.
    def _bt(direction_series, weekly_direction=None, confirmation_config=None,
            strategy_key=None, mm_config=active_mm_config):
        return _run_direction_backtest(
            df_view,
            direction_series,
            df.index,
            df_view.index,
            mm_config,
            weekly_direction=weekly_direction,
            confirmation_config=confirmation_config,
            strategy_key=strategy_key,
        )

    def _bt_corpus():
        return _run_corpus_trend_backtest(
            df_view,
            corpus_direction,
            corpus_stop_line,
            df.index,
            df_view.index,
            active_mm_config,
            weekly_direction=corpus_weekly_direction,
            confirmation_config=strategy_confirmation_config("corpus_trend"),
        )

    def _bt_corpus_layered():
        return _run_corpus_trend_layered_backtest(
            df_view, corpus_direction, corpus_stop_line, df.index, df_view.index,
        )

    def _bt_weekly_core_overlay():
        return _run_weekly_core_overlay_backtest(
            df_view,
            weekly_core_overlay_core_direction,
            weekly_core_overlay_overlay_direction,
            df.index,
            df_view.index,
            core_fraction=weekly_core_overlay_core_fraction,
            overlay_fraction=weekly_core_overlay_overlay_fraction,
        )

    backtest_tasks = {
        "ema": lambda: _bt(ema_direction, ema_crossover_weekly_direction,
                           strategy_confirmation_config("ema_crossover")),
        "ema_9_26": lambda: _bt(ema_9_26_direction, ema_9_26_weekly_direction,
                                strategy_confirmation_config(EMA_9_26_KEY)),
        "macd": lambda: _bt(macd_direction, macd_weekly_direction,
                            strategy_confirmation_config("macd")),
        "donchian": lambda: _bt(donch_direction, donchian_weekly_direction,
                                strategy_confirmation_config("donchian")),
        "corpus_trend": _bt_corpus,
        "corpus_trend_layered": _bt_corpus_layered,
        "cb50": lambda: _bt(cb50_direction, cb50_weekly_direction,
                            strategy_confirmation_config("cb50")),
        "cb150": lambda: _bt(cb150_direction, cb150_weekly_direction,
                             strategy_confirmation_config("cb150")),
        "sma_10_100": lambda: _bt(sma_10_100_direction, sma_10_100_weekly_direction,
                                  strategy_confirmation_config("sma_10_100")),
        "sma_10_200": lambda: _bt(sma_10_200_direction, sma_10_200_weekly_direction,
                                  strategy_confirmation_config("sma_10_200")),
        "ema_trend": lambda: _bt(ema_trend_direction, ema_trend_weekly_direction,
                                 strategy_confirmation_config("ema_trend")),
        "yearly_ma": lambda: _bt(yearly_ma_direction, yearly_ma_weekly_direction,
                                 strategy_confirmation_config("yearly_ma")),
        "supertrend_i": lambda: _bt(supertrend_i_direction, supertrend_i_weekly_direction,
                                    strategy_confirmation_config("supertrend_i")),
        "bb": lambda: _bt(bb_direction, bb_weekly_direction,
                          strategy_confirmation_config("bb_breakout")),
        "kelt": lambda: _bt(kelt_direction, keltner_weekly_direction,
                            strategy_confirmation_config("keltner")),
        "weekly_core_overlay": _bt_weekly_core_overlay,
        "psar": lambda: _bt(psar_direction, psar_weekly_direction,
                            strategy_confirmation_config("parabolic_sar")),
        "cci": lambda: _bt(cci_direction, cci_weekly_direction,
                           strategy_confirmation_config("cci_trend")),
        "cci_hyst": lambda: _bt(cci_hyst_direction, strategy_key="cci_hysteresis"),
        "semis_persist": lambda: _bt(semis_persist_direction, strategy_key=SEMIS_PERSIST_KEY),
        # Pass active_mm_config (not None) so the worker thread does NOT
        # re-enter `_parse_mm_config()` which reads from request.args and
        # would fail with "Working outside of request context". active_mm_config
        # is semantically identical since it was parsed from the same request.
        "trend_sr_macro": lambda: _bt(trend_sr_macro_direction,
                                      weekly_direction=trend_sr_macro_weekly_direction,
                                      confirmation_config=trend_sr_macro_confirm_cfg,
                                      mm_config=active_mm_config),
        "orb": lambda: _bt(orb_direction, orb_weekly_direction,
                           strategy_confirmation_config("orb_breakout")),
        "poly": lambda: _bt(poly_direction),
        "ribbon": lambda: _bt(ribbon_backtest_direction, ribbon_weekly_direction,
                              strategy_confirmation_config("ribbon")),
    }

    def _selected_strategy_response(strategy_key: str):
        task_key = _STRATEGY_TASK_KEYS[strategy_key]
        selected_trades, selected_summary, selected_equity_curve = backtest_tasks[task_key]()
        selected_direction = {
            "ribbon": ribbon_backtest_direction,
            "corpus_trend": corpus_direction,
            "corpus_trend_layered": corpus_direction,
            "weekly_core_overlay_v1": weekly_core_overlay_overlay_direction,
            "supertrend_i": supertrend_i_direction,
            "bb_breakout": bb_direction,
            "ema_crossover": ema_direction,
            EMA_9_26_KEY: ema_9_26_direction,
            "cci_trend": cci_direction,
            "cci_hysteresis": cci_hyst_direction,
            SEMIS_PERSIST_KEY: semis_persist_direction,
            TREND_SR_MACRO_KEY: trend_sr_macro_direction,
            "polymarket": poly_direction,
        }.get(strategy_key, ribbon_backtest_direction)
        buy_hold = build_buy_hold_equity_curve(df_view)
        selected_buy_hold = None
        backtest_meta = {}
        window_meta_config = None if confirmation_config else active_mm_config

        if strategy_key == "ribbon":
            if (
                interval == "1d"
                and weekly_bundle is not None
                and not strategy_confirmation_config("ribbon")
            ):
                daily_ribbon_direction = _carry_neutral_direction(ribbon_dir)
                weekly_ribbon_direction = _align_weekly_direction_to_daily(
                    weekly_bundle["ribbon_dir"],
                    df.index,
                )
                ribbon_regime_kwargs = trend_ribbon_regime_kwargs(ticker)
                selected_direction = build_weekly_confirmed_ribbon_direction(
                    daily_ribbon_direction,
                    weekly_ribbon_direction,
                    reentry_cooldown_bars=ribbon_regime_kwargs["reentry_cooldown_bars"],
                    reentry_cooldown_ratio=ribbon_regime_kwargs["reentry_cooldown_ratio"],
                    weekly_nonbull_confirm_bars=ribbon_regime_kwargs[
                        "weekly_nonbull_confirm_bars"
                    ],
                    asymmetric_exit=ribbon_regime_kwargs.get("asymmetric_exit", False),
                )
                selected_trades, selected_summary, selected_equity_curve = (
                    _run_ribbon_regime_backtest(
                        df_view,
                        selected_direction,
                        df.index,
                        df_view.index,
                        active_mm_config,
                    )
                )
            selected_buy_hold = buy_hold
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(selected_direction, df.index, df_view.index, window_meta_config),
                strategy_confirmation_meta("ribbon"),
            )
        elif strategy_key == "corpus_trend":
            selected_buy_hold = buy_hold
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(corpus_direction, df.index, df_view.index, window_meta_config),
                strategy_confirmation_meta("corpus_trend"),
            )
        elif strategy_key == "corpus_trend_layered":
            selected_buy_hold = buy_hold
            backtest_meta = _confirmation_meta(confirmation_config, supported=False)
        elif strategy_key == "supertrend_i":
            selected_buy_hold = buy_hold
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(supertrend_i_direction, df.index, df_view.index, window_meta_config),
                strategy_confirmation_meta("supertrend_i"),
                {
                    "architecture_label": "Supertrend-I",
                    "architecture_hint": "ATR Supertrend ratchet that flips on an intrabar touch of the active band rather than waiting for the close to cross it.",
                },
            )
        elif strategy_key == "weekly_core_overlay_v1":
            selected_buy_hold = buy_hold
            backtest_meta = {
                "confirmation_supported": False,
                "architecture_label": "Weekly Core + Daily Overlay",
                "architecture_core_strategy": f"{weekly_core_overlay_core_key}_weekly",
                "architecture_overlay_strategy": f"{weekly_core_overlay_overlay_key}_daily",
                "architecture_core_fraction": weekly_core_overlay_core_fraction,
                "architecture_overlay_fraction": weekly_core_overlay_overlay_fraction,
                "architecture_hint": _weekly_core_overlay_hint(
                    weekly_core_overlay_core_key,
                    weekly_core_overlay_overlay_key,
                    weekly_core_overlay_core_fraction,
                    weekly_core_overlay_overlay_fraction,
                ),
            }
        elif strategy_key == "bb_breakout":
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(bb_direction, df.index, df_view.index, window_meta_config),
                strategy_confirmation_meta("bb_breakout"),
            )
        elif strategy_key == "ema_crossover":
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(ema_direction, df.index, df_view.index, window_meta_config),
                strategy_confirmation_meta("ema_crossover"),
            )
        elif strategy_key == EMA_9_26_KEY:
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(ema_9_26_direction, df.index, df_view.index, window_meta_config),
                strategy_confirmation_meta(EMA_9_26_KEY),
                specialized_strategy_backtest_meta(EMA_9_26_KEY),
            )
        elif strategy_key == "cci_trend":
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(cci_direction, df.index, df_view.index, window_meta_config),
                strategy_confirmation_meta("cci_trend"),
            )
        elif strategy_key == "cci_hysteresis":
            selected_buy_hold = buy_hold
            backtest_meta = _confirmation_meta(confirmation_config, supported=False)
        elif strategy_key == SEMIS_PERSIST_KEY:
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(semis_persist_direction, df.index, df_view.index, window_meta_config),
                specialized_strategy_backtest_meta(SEMIS_PERSIST_KEY),
            )
        elif strategy_key == TREND_SR_MACRO_KEY:
            selected_buy_hold = buy_hold
            backtest_meta = trend_sr_macro_backtest_meta(trend_sr_macro_bundle or {})
        elif strategy_key == "polymarket":
            backtest_meta = _merge_backtest_meta(
                _managed_window_metadata(poly_direction, df.index, df_view.index, window_meta_config),
                _confirmation_meta(confirmation_config, supported=False),
            )

        payload = _strategy_payload(
            selected_trades,
            selected_summary,
            selected_equity_curve,
            buy_hold_equity_curve=selected_buy_hold,
            backtest_meta=backtest_meta,
        )
        return {
            "strategy_only": True,
            "strategy": strategy_key,
            "ticker_name": ticker_name,
            "buy_hold_equity_curve": buy_hold,
            "strategies": {strategy_key: payload},
        }

    def _build_strategy_shared_payload() -> dict:
        if interval == "1d":
            local_daily_flips = indicator_bundle["daily_flips"]
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
                local_daily_flips = compute_all_trend_flips(
                    df_d,
                    period_val=period_val,
                    multiplier_val=multiplier_val,
                    ribbon_kwargs=_trend_ribbon_kwargs(ticker),
                    ticker=ticker,
                )
            except Exception:
                local_daily_flips = {}

        candles = _ohlcv_df_to_candles(df_view)
        st_up, st_down = _supertrend_segments_for_view(df_view, supertrend, direction)
        st_i_up, st_i_down = _supertrend_segments_for_view(
            df_view,
            supertrend_i,
            supertrend_i_direction,
        )

        local_smas = {}
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
            local_smas[f"sma_{sma_period}"] = sma_data

        local_sma_50w = []
        local_sma_100w = []
        local_sma_200w = []
        local_weekly_flips = {}
        df_w = pd.DataFrame()
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
                weekly_bundle_local, _ = _get_weekly_bundle(
                    ticker,
                    df_w,
                    period_val,
                    multiplier_val,
                )
                sma_w50 = weekly_bundle_local["sma_w50"]
                sma_w100 = weekly_bundle_local["sma_w100"]
                sma_w200 = weekly_bundle_local["sma_w200"]
                sma_w50_view = sma_w50.loc[df_w_view.index]
                sma_w100_view = sma_w100.loc[df_w_view.index]
                sma_w200_view = sma_w200.loc[df_w_view.index]
                for i in range(len(df_w_view)):
                    ts = int(df_w_view.index[i].timestamp())
                    if not pd.isna(sma_w50_view.iloc[i]):
                        local_sma_50w.append({"time": ts, "value": round(float(sma_w50_view.iloc[i]), 2)})
                    if not pd.isna(sma_w100_view.iloc[i]):
                        local_sma_100w.append({"time": ts, "value": round(float(sma_w100_view.iloc[i]), 2)})
                    if not pd.isna(sma_w200_view.iloc[i]):
                        local_sma_200w.append({"time": ts, "value": round(float(sma_w200_view.iloc[i]), 2)})
                if interval == "1wk":
                    local_weekly_flips = indicator_bundle["daily_flips"]
                else:
                    local_weekly_flips = weekly_bundle_local["weekly_flips"]
        except Exception:
            current_app.logger.exception(
                "chart_data include_shared weekly payload failed ticker=%s interval=%s",
                ticker,
                interval,
            )

        sr_setup_bundle, _ = _get_sr_and_trade_setup(
            ticker, df, df_w, local_daily_flips, local_weekly_flips
        )
        local_sr_levels = sr_setup_bundle["sr_levels"]
        local_trade_setup = sr_setup_bundle["trade_setup"]

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

        donch_upper_data = series_to_json(donch_upper, df_view.index)
        donch_lower_data = series_to_json(donch_lower, df_view.index)
        bb_upper_data = series_to_json(bb_upper, df_view.index)
        bb_mid_data = series_to_json(bb_mid, df_view.index)
        bb_lower_data = series_to_json(bb_lower, df_view.index)
        kelt_upper_data = series_to_json(kelt_upper, df_view.index)
        kelt_mid_data = series_to_json(kelt_mid, df_view.index)
        kelt_lower_data = series_to_json(kelt_lower, df_view.index)

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

        cci_data = series_to_json(cci_val, df_view.index)
        orb_high_data = series_to_json(orb_range_high, df_view.index)
        orb_low_data = series_to_json(orb_range_low, df_view.index)
        orb_mid_data = series_to_json(orb_range_mid, df_view.index)

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

        return {
            "ticker_name": ticker_name,
            "candles": candles,
            "supertrend_up": st_up,
            "supertrend_down": st_down,
            "supertrend_i_up": st_i_up,
            "supertrend_i_down": st_i_down,
            "volumes": volumes,
            **local_smas,
            "sma_50w": local_sma_50w,
            "sma_100w": local_sma_100w,
            "sma_200w": local_sma_200w,
            "ema9": ema9_data,
            "ema21": ema21_data,
            "macd_line": macd_line_data,
            "signal_line": signal_line_data,
            "macd_hist": macd_hist_data,
            "sr_levels": local_sr_levels,
            "overlays": {
                "donchian": {"upper": donch_upper_data, "lower": donch_lower_data},
                "bb": {"upper": bb_upper_data, "mid": bb_mid_data, "lower": bb_lower_data},
                "keltner": {"upper": kelt_upper_data, "mid": kelt_mid_data, "lower": kelt_lower_data},
                "psar": {"bull": psar_bull_data, "bear": psar_bear_data},
                "cci": {"cci": cci_data},
                "orb": {"upper": orb_high_data, "lower": orb_low_data, "mid": orb_mid_data},
                "ribbon": {"upper": ribbon_upper_data, "lower": ribbon_lower_data, "center": ribbon_center_data},
            },
            "vol_profile": build_volume_profile(df_view),
            "trend_flips": {"daily": local_daily_flips, "weekly": local_weekly_flips},
            "trade_setup": local_trade_setup,
        }

    if strategy_only and not include_shared:
        payload = _selected_strategy_response(requested_strategy)
        _cache_set(strategy_cache_key, payload, ttl=_CHART_CACHE_TTL)
        _write_chart_payload_cache(strategy_cache_kind, strategy_cache_key, end, payload)
        current_app.logger.info(
            "chart_data strategy_only ticker=%s interval=%s strategy=%s range=%s..%s total_ms=%s",
            ticker,
            interval,
            requested_strategy,
            start,
            end or "latest",
            _elapsed_ms(request_started_at),
        )
        return jsonify(payload)

    if strategy_only:
        payload = {
            **_build_strategy_shared_payload(),
            **_selected_strategy_response(requested_strategy),
        }
        _cache_set(strategy_cache_key, payload, ttl=_CHART_CACHE_TTL)
        _write_chart_payload_cache(strategy_cache_kind, strategy_cache_key, end, payload)
        current_app.logger.info(
            "chart_data strategy_only_shared ticker=%s interval=%s strategy=%s range=%s..%s total_ms=%s",
            ticker,
            interval,
            requested_strategy,
            start,
            end or "latest",
            _elapsed_ms(request_started_at),
        )
        return jsonify(payload)

    # max_workers cap: more threads beyond ~8 gives diminishing returns under
    # the GIL for pure-Python backtest loops.
    _max_workers = min(8, len(backtest_tasks))
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=_max_workers, thread_name_prefix="bt"
    ) as executor:
        futures = {name: executor.submit(fn) for name, fn in backtest_tasks.items()}
        bt_results = {name: fut.result() for name, fut in futures.items()}

    ema_trades, ema_summary, ema_equity_curve = bt_results["ema"]
    ema_9_26_trades, ema_9_26_summary, ema_9_26_equity_curve = bt_results["ema_9_26"]
    macd_trades, macd_summary, macd_equity_curve = bt_results["macd"]
    donch_trades, donch_summary, donch_equity_curve = bt_results["donchian"]
    corpus_trend_trades, corpus_trend_summary, corpus_trend_equity_curve = bt_results["corpus_trend"]
    corpus_trend_layered_trades, corpus_trend_layered_summary, corpus_trend_layered_equity_curve = bt_results["corpus_trend_layered"]
    cb50_trades, cb50_summary, cb50_equity_curve = bt_results["cb50"]
    cb150_trades, cb150_summary, cb150_equity_curve = bt_results["cb150"]
    sma_10_100_trades, sma_10_100_summary, sma_10_100_equity_curve = bt_results["sma_10_100"]
    sma_10_200_trades, sma_10_200_summary, sma_10_200_equity_curve = bt_results["sma_10_200"]
    ema_trend_trades, ema_trend_summary, ema_trend_equity_curve = bt_results["ema_trend"]
    yearly_ma_trades, yearly_ma_summary, yearly_ma_equity_curve = bt_results["yearly_ma"]
    supertrend_i_trades, supertrend_i_summary, supertrend_i_equity_curve = bt_results["supertrend_i"]
    bb_trades, bb_summary, bb_equity_curve = bt_results["bb"]
    kelt_trades, kelt_summary, kelt_equity_curve = bt_results["kelt"]
    weekly_core_overlay_trades, weekly_core_overlay_summary, weekly_core_overlay_equity_curve = bt_results["weekly_core_overlay"]
    psar_trades, psar_summary, psar_equity_curve = bt_results["psar"]
    cci_trades, cci_summary, cci_equity_curve = bt_results["cci"]
    cci_hyst_trades, cci_hyst_summary, cci_hyst_equity_curve = bt_results["cci_hyst"]
    semis_persist_trades, semis_persist_summary, semis_persist_equity_curve = bt_results["semis_persist"]
    trend_sr_macro_trades, trend_sr_macro_summary, trend_sr_macro_equity_curve = bt_results["trend_sr_macro"]
    orb_trades, orb_summary, orb_equity_curve = bt_results["orb"]
    poly_trades, poly_summary, poly_equity_curve = bt_results["poly"]
    ribbon_trades, ribbon_summary, ribbon_equity_curve = bt_results["ribbon"]
    ribbon_hold_equity_curve = None
    mark_phase("strategy_backtests_ms")

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
                ticker=ticker,
            )
        except Exception:
            daily_flips = {}
    mark_phase("daily_flips_ms")

    # --- Candles ---
    candles = _ohlcv_df_to_candles(df_view)

    # --- Supertrend lines ---
    st_up, st_down = _supertrend_segments_for_view(df_view, supertrend, direction)
    st_i_up, st_i_down = _supertrend_segments_for_view(
        df_view,
        supertrend_i,
        supertrend_i_direction,
    )

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
    df_w = pd.DataFrame()
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

    # --- Support / Resistance + trade setup (cached as a pair) ---
    sr_setup_bundle, sr_setup_bundle_hit = _get_sr_and_trade_setup(
        ticker, df, df_w, daily_flips, weekly_flips
    )
    sr_levels = sr_setup_bundle["sr_levels"]
    trade_setup = sr_setup_bundle["trade_setup"]
    mark_phase("sr_setup_ms")

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
        "supertrend_i_up": st_i_up,
        "supertrend_i_down": st_i_down,
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
            "supertrend_i": _strategy_payload(
                supertrend_i_trades,
                supertrend_i_summary,
                supertrend_i_equity_curve,
                buy_hold_equity_curve=buy_hold_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        supertrend_i_direction, df.index, df_view.index, window_meta_config
                    ),
                    strategy_confirmation_meta("supertrend_i"),
                    {
                        "architecture_label": "Supertrend-I",
                        "architecture_hint": "ATR Supertrend ratchet that flips on an intrabar touch of the active band rather than waiting for the close to cross it.",
                    },
                ),
            ),
            "weekly_core_overlay_v1": _strategy_payload(
                weekly_core_overlay_trades,
                weekly_core_overlay_summary,
                weekly_core_overlay_equity_curve,
                buy_hold_equity_curve=buy_hold_equity_curve,
                backtest_meta={
                    "confirmation_supported": False,
                    "architecture_label": "Weekly Core + Daily Overlay",
                    "architecture_core_strategy": f"{weekly_core_overlay_core_key}_weekly",
                    "architecture_overlay_strategy": f"{weekly_core_overlay_overlay_key}_daily",
                    "architecture_core_fraction": weekly_core_overlay_core_fraction,
                    "architecture_overlay_fraction": weekly_core_overlay_overlay_fraction,
                    "architecture_hint": _weekly_core_overlay_hint(
                        weekly_core_overlay_core_key,
                        weekly_core_overlay_overlay_key,
                        weekly_core_overlay_core_fraction,
                        weekly_core_overlay_overlay_fraction,
                    ),
                },
            ),
            "bb_breakout": _strategy_payload(
                bb_trades,
                bb_summary,
                bb_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        bb_direction, df.index, df_view.index, window_meta_config
                    ),
                    strategy_confirmation_meta("bb_breakout"),
                ),
            ),
            "ema_crossover": _strategy_payload(
                ema_trades,
                ema_summary,
                ema_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        ema_direction, df.index, df_view.index, window_meta_config
                    ),
                    strategy_confirmation_meta("ema_crossover"),
                ),
            ),
            EMA_9_26_KEY: _strategy_payload(
                ema_9_26_trades,
                ema_9_26_summary,
                ema_9_26_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        ema_9_26_direction, df.index, df_view.index, window_meta_config
                    ),
                    strategy_confirmation_meta(EMA_9_26_KEY),
                    specialized_strategy_backtest_meta(EMA_9_26_KEY),
                ),
            ),
            "cci_trend": _strategy_payload(
                cci_trades,
                cci_summary,
                cci_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        cci_direction, df.index, df_view.index, window_meta_config
                    ),
                    strategy_confirmation_meta("cci_trend"),
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
            SEMIS_PERSIST_KEY: _strategy_payload(
                semis_persist_trades,
                semis_persist_summary,
                semis_persist_equity_curve,
                backtest_meta=_merge_backtest_meta(
                    _managed_window_metadata(
                        semis_persist_direction, df.index, df_view.index, window_meta_config
                    ),
                    specialized_strategy_backtest_meta(SEMIS_PERSIST_KEY),
                ),
            ),
            TREND_SR_MACRO_KEY: _strategy_payload(
                trend_sr_macro_trades,
                trend_sr_macro_summary,
                trend_sr_macro_equity_curve,
                buy_hold_equity_curve=buy_hold_equity_curve,
                backtest_meta=trend_sr_macro_backtest_meta(
                    trend_sr_macro_bundle
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
        "trade_setup": trade_setup,
    }
    mark_phase("payload_ms")
    _cache_set(chart_cache_key, payload, ttl=_CHART_CACHE_TTL)
    _write_chart_payload_cache("chart", chart_cache_key, end, payload)
    current_app.logger.info(
        "chart_data timings ticker=%s interval=%s range=%s..%s rows=%s view_rows=%s indicator_bundle_hit=%s weekly_bundle_hit=%s metadata_ms=%s fetch_ms=%s frame_ms=%s strategy_backtests_ms=%s daily_flips_ms=%s weekly_ms=%s sr_setup_ms=%s payload_ms=%s total_ms=%s",
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
        timings_ms.get("strategy_backtests_ms", 0),
        timings_ms.get("daily_flips_ms", 0),
        timings_ms.get("weekly_ms", 0),
        timings_ms.get("sr_setup_ms", 0),
        timings_ms.get("payload_ms", 0),
        _elapsed_ms(request_started_at),
    )
    return jsonify(payload)
