import json
import os
import time as _time
import threading
from datetime import timedelta
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd

from app_settings import (
    DAILY_WARMUP_DAYS,
    INITIAL_CAPITAL,
    WEEKLY_WARMUP_DAYS,
)
from backtesting import (
    backtest_direction as _backtest_direction_impl,
    backtest_supertrend as _backtest_supertrend_impl,
    build_equity_curve as _build_equity_curve_impl,
    compute_summary as _compute_summary_impl,
)
from chart_serialization import (
    build_volume_profile,
    compute_all_trend_flips,
    last_trend_flip,
    series_to_json,
)
from support_resistance import compute_support_resistance as _compute_support_resistance_impl
from technical_indicators import (
    STRATEGIES,
    compute_adx_trend as _compute_adx_trend_impl,
    compute_bollinger_breakout as _compute_bollinger_breakout_impl,
    compute_cci_trend as _compute_cci_trend_impl,
    compute_donchian_breakout as _compute_donchian_breakout_impl,
    compute_ema_crossover as _compute_ema_crossover_impl,
    compute_keltner_breakout as _compute_keltner_breakout_impl,
    compute_ma_confirmation as _compute_ma_confirmation_impl,
    compute_macd_crossover as _compute_macd_crossover_impl,
    compute_parabolic_sar as _compute_parabolic_sar_impl,
    compute_regime_router as _compute_regime_router_impl,
    compute_supertrend as _compute_supertrend_impl,
    compute_trend_ribbon as _compute_trend_ribbon_impl,
    detect_regime as _detect_regime_impl,
)

# ---------------------------------------------------------------------------
# In-memory TTL cache (for quotes and short-lived data)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # seconds (5 minutes)
_yf_lock = threading.Lock()  # serialize yfinance calls to prevent cross-ticker contamination


def _cache_get(key: str):
    """Return cached value if still fresh, else None."""
    entry = _cache.get(key)
    if entry and (_time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value):
    _cache[key] = (_time.time(), value)


# ---------------------------------------------------------------------------
# Persistent local file cache for historical OHLCV data
# ---------------------------------------------------------------------------
_DATA_CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
os.makedirs(_DATA_CACHE_DIR, exist_ok=True)

# Minimum seconds before re-fetching fresh data for a ticker+interval
_DISK_CACHE_FRESHNESS = 300  # 5 minutes


def _disk_cache_path(ticker: str, interval: str) -> str:
    """Return path to the cached CSV for a ticker+interval."""
    safe = f"{ticker}_{interval}".replace("/", "_")
    return os.path.join(_DATA_CACHE_DIR, f"{safe}.csv")


def _meta_path(ticker: str, interval: str) -> str:
    safe = f"{ticker}_{interval}".replace("/", "_")
    return os.path.join(_DATA_CACHE_DIR, f"{safe}.meta.json")


def _has_suspicious_weekly_spacing(df: pd.DataFrame) -> bool:
    """Weekly bars should not arrive less than 5 days apart."""
    if df is None or df.empty or len(df.index) < 2:
        return False
    idx = pd.Index(df.index).sort_values()
    deltas = idx.to_series().diff().dropna()
    return bool((deltas < pd.Timedelta(days=5)).any())


def _incremental_data_failed_validation(
    cached_df: pd.DataFrame | None, new_df: pd.DataFrame, interval: str
) -> bool:
    """Reject obvious cross-ticker or wrong-interval incremental fetches."""
    if new_df is None or new_df.empty:
        return False

    if interval == "1wk":
        if _has_suspicious_weekly_spacing(new_df):
            return True
        if cached_df is not None and not cached_df.empty:
            weekly_tail = cached_df.tail(1)
            if _has_suspicious_weekly_spacing(pd.concat([weekly_tail, new_df])):
                return True

    if (
        cached_df is None
        or cached_df.empty
        or "Close" not in cached_df.columns
        or "Close" not in new_df.columns
    ):
        return False

    cached_close = cached_df["Close"].dropna()
    new_close = new_df["Close"].dropna()
    if cached_close.empty or new_close.empty:
        return False

    last_cached_close = cached_close.iloc[-1]
    first_new_close = new_close.iloc[0]
    if last_cached_close <= 0:
        return False

    ratio = first_new_close / last_cached_close
    return ratio > 2 or ratio < 0.5


def cached_download(ticker: str, **kwargs) -> pd.DataFrame:
    """Download OHLCV data with persistent local file cache.

    On first call: fetches full history and saves to CSV.
    On subsequent calls: loads cached data, fetches only new rows since the
    last cached date, appends, and re-saves. Skips re-fetch if data was
    refreshed less than _DISK_CACHE_FRESHNESS seconds ago.
    """
    interval = kwargs.get("interval", "1d")
    start = kwargs.get("start")
    end = kwargs.get("end")

    # For non-standard calls (period-based, etc.), fall back to in-memory cache
    if start is None or "period" in kwargs:
        key = f"dl:{ticker}:{json.dumps(kwargs, sort_keys=True, default=str)}"
        cached = _cache_get(key)
        if cached is not None:
            return cached
        download_kwargs = dict(kwargs)
        download_kwargs.setdefault("threads", False)
        with _yf_lock:
            df = yf.download(ticker, **download_kwargs)
        _cache_set(key, df)
        return df

    csv_path = _disk_cache_path(ticker, interval)
    meta_path = _meta_path(ticker, interval)
    cached_df = None

    # Load existing cached data
    if os.path.exists(csv_path):
        try:
            cached_df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            # Deduplicate index to prevent "Reindexing only valid with
            # uniquely valued Index objects" errors downstream.
            if cached_df.index.duplicated().any():
                cached_df = cached_df[~cached_df.index.duplicated(keep="last")]
        except Exception:
            cached_df = None

    # Check if we fetched recently enough to skip the network call
    now = _time.time()
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            if (now - meta.get("last_fetch", 0)) < _DISK_CACHE_FRESHNESS and cached_df is not None:
                # Return slice matching the requested range
                return _slice_df(cached_df, start, end)
        except Exception:
            pass

    # Determine what to fetch
    if cached_df is not None and not cached_df.empty:
        # Only fetch from day after last cached row
        last_cached = cached_df.index.max()
        # For weekly data, re-fetch from the last cached date (not +1 day)
        # to avoid mid-week fetches that return garbage from yfinance
        if interval == "1wk":
            fetch_start = last_cached.strftime("%Y-%m-%d")
        else:
            fetch_start = (last_cached + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        # If fetch_start is in the future, nothing new to get
        if pd.Timestamp(fetch_start) > pd.Timestamp.now():
            _write_meta(meta_path, now)
            return _slice_df(cached_df, start, end)
    else:
        fetch_start = start

    # Fetch new data — serialize yfinance calls to prevent cross-ticker contamination
    fetch_kwargs = dict(kwargs)
    fetch_kwargs["start"] = fetch_start
    fetch_kwargs["progress"] = False
    fetch_kwargs.setdefault("threads", False)
    try:
        with _yf_lock:
            new_df = yf.download(ticker, **fetch_kwargs)
    except Exception:
        # Network error — return whatever we have cached
        if cached_df is not None:
            return _slice_df(cached_df, start, end)
        return pd.DataFrame()

    if isinstance(new_df.columns, pd.MultiIndex):
        new_df.columns = new_df.columns.get_level_values(0)

    # Deduplicate index from yfinance
    if not new_df.empty and new_df.index.duplicated().any():
        new_df = new_df[~new_df.index.duplicated(keep="last")]

    # Validate new data against cached data to detect cross-ticker contamination
    if _incremental_data_failed_validation(cached_df, new_df, interval):
        # New data looks like a different ticker or wrong interval — discard it
        _write_meta(meta_path, now)
        return _slice_df(cached_df, start, end)

    # Merge with cached data
    if cached_df is not None and not cached_df.empty and not new_df.empty:
        combined = pd.concat([cached_df, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
    elif not new_df.empty:
        combined = new_df
    else:
        combined = cached_df if cached_df is not None else pd.DataFrame()

    # Persist to disk
    if not combined.empty:
        try:
            combined.to_csv(csv_path)
        except Exception:
            pass

    _write_meta(meta_path, now)
    return _slice_df(combined, start, end)


def _write_meta(meta_path: str, now: float):
    try:
        with open(meta_path, "w") as f:
            json.dump({"last_fetch": now}, f)
    except Exception:
        pass


def _slice_df(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Return the subset of df within [start, end]."""
    if df.empty:
        return df
    # Safety: deduplicate index to avoid reindex errors in downstream .loc calls
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    mask = pd.Series(True, index=df.index)
    if start:
        mask &= df.index >= pd.Timestamp(start)
    if end:
        mask &= df.index <= pd.Timestamp(end)
    return df.loc[mask]


# Well-known index symbols that require a ^ prefix on Yahoo Finance
_INDEX_SYMBOLS = {
    "IXIC", "GSPC", "DJI", "RUT", "VIX", "NYA", "XAX",
    "FTSE", "GDAXI", "FCHI", "N225", "HSI", "STOXX50E",
    "BVSP", "GSPTSE", "AXJO", "NZ50", "KS11", "TWII",
    "SSEC", "JKSE", "KLSE", "STI", "NSEI", "BSESN",
    "TNX", "TYX", "FVX", "IRX",  # Treasury yields
    "SOX",  # Semiconductor index
    "SPX",  # Alias: redirect to GSPC
}

def normalize_ticker(ticker: str) -> str:
    """Add ^ prefix for known index symbols if user forgot it."""
    t = ticker.upper().strip()
    if t.startswith("^"):
        return t
    if t == "SPX":
        return "^GSPC"
    if t in _INDEX_SYMBOLS:
        return f"^{t}"
    return t


app = Flask(__name__)

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")


def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return []


def save_watchlist(tickers):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(sorted(set(t.upper() for t in tickers)), f)


def _parse_start_date(start):
    return pd.Timestamp(start).normalize()


def _parse_end_date(end):
    if not end:
        return None
    return pd.Timestamp(end).normalize()


def _warmup_start(start, interval):
    lookback_days = WEEKLY_WARMUP_DAYS if interval == "1wk" else DAILY_WARMUP_DAYS
    return (_parse_start_date(start) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def _visible_mask(index, start, end):
    start_ts = _parse_start_date(start)
    mask = index >= start_ts
    if end:
        end_ts = _parse_end_date(end) + timedelta(days=1) - timedelta(seconds=1)
        mask &= index <= end_ts
    return mask


def _starts_long(direction, full_index, view_index):
    if len(view_index) == 0:
        return False
    first_visible_loc = full_index.get_loc(view_index[0])
    if first_visible_loc == 0:
        return False
    return direction.iloc[first_visible_loc - 1] == 1


def compute_supertrend(df, period=10, multiplier=3):
    return _compute_supertrend_impl(df, period=period, multiplier=multiplier)


def compute_ma_confirmation(df, ma_period=200, confirm_candles=3):
    return _compute_ma_confirmation_impl(
        df, ma_period=ma_period, confirm_candles=confirm_candles
    )


def compute_ema_crossover(df, fast=9, slow=21):
    return _compute_ema_crossover_impl(df, fast=fast, slow=slow)


def compute_macd_crossover(df, fast=12, slow=26, signal=9):
    return _compute_macd_crossover_impl(df, fast=fast, slow=slow, signal=signal)


def compute_donchian_breakout(df, period=20):
    return _compute_donchian_breakout_impl(df, period=period)


def compute_adx_trend(df, period=14, adx_threshold=25):
    return _compute_adx_trend_impl(df, period=period, adx_threshold=adx_threshold)


def compute_bollinger_breakout(df, period=20, std_dev=2):
    return _compute_bollinger_breakout_impl(df, period=period, std_dev=std_dev)


def compute_keltner_breakout(df, ema_period=20, atr_period=10, multiplier=1.5):
    return _compute_keltner_breakout_impl(
        df,
        ema_period=ema_period,
        atr_period=atr_period,
        multiplier=multiplier,
    )


def compute_parabolic_sar(df, af_start=0.02, af_increment=0.02, af_max=0.2):
    return _compute_parabolic_sar_impl(
        df,
        af_start=af_start,
        af_increment=af_increment,
        af_max=af_max,
    )


def compute_cci_trend(df, period=20, threshold=100):
    return _compute_cci_trend_impl(df, period=period, threshold=threshold)


def compute_trend_ribbon(df, ema_period=21, atr_period=14, adx_period=14,
                          min_width=0.5, max_width=3.0):
    return _compute_trend_ribbon_impl(
        df,
        ema_period=ema_period,
        atr_period=atr_period,
        adx_period=adx_period,
        min_width=min_width,
        max_width=max_width,
    )


def _build_equity_curve(df, trades):
    return _build_equity_curve_impl(df, trades)


def _compute_summary(trades, equity_curve):
    return _compute_summary_impl(trades, equity_curve)


def backtest_direction(df, direction, start_in_position=False):
    return _backtest_direction_impl(
        df, direction, start_in_position=start_in_position
    )


def backtest_supertrend(df, direction, start_in_position=False):
    return _backtest_supertrend_impl(
        df, direction, start_in_position=start_in_position
    )


def compute_support_resistance(df, max_levels=8):
    return _compute_support_resistance_impl(df, max_levels=max_levels)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chart")
def chart_data():
    ticker = normalize_ticker(request.args.get("ticker", "TSLA"))
    interval = request.args.get("interval", "1d")
    start = request.args.get("start", "2023-01-01")
    end = request.args.get("end", "")
    period_val = int(request.args.get("period", 10))
    multiplier_val = float(request.args.get("multiplier", 3))

    try:
        kwargs = {"start": _warmup_start(start, interval), "interval": interval, "progress": False}
        if end:
            kwargs["end"] = end
        df = cached_download(ticker, **kwargs)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if df.empty:
        return jsonify({"error": f"No data for {ticker}"}), 400

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Remove duplicate index entries (can occur from cache merges)
    df = df[~df.index.duplicated(keep="last")]

    view_mask = _visible_mask(df.index, start, end)
    df_view = df.loc[view_mask].copy()
    # Extra safety: deduplicate view index
    if df_view.index.duplicated().any():
        df_view = df_view[~df_view.index.duplicated(keep="last")]
    if df_view.empty:
        return jsonify({"error": f"No data for {ticker} in selected range"}), 400

    supertrend, direction = compute_supertrend(df, period_val, multiplier_val)
    direction_view = direction.loc[df_view.index]
    supertrend_view = supertrend.loc[df_view.index]
    supertrend_start_long = _starts_long(direction, df.index, df_view.index)

    ema_fast, ema_slow, ema_direction = compute_ema_crossover(df, 9, 21)
    ema_direction_view = ema_direction.loc[df_view.index]
    ema_trades, ema_summary, ema_equity_curve = backtest_direction(
        df_view, ema_direction_view, start_in_position=_starts_long(ema_direction, df.index, df_view.index)
    )

    _ma_conf, ma_conf_direction = compute_ma_confirmation(df, 200, 3)
    ma_conf_direction_view = ma_conf_direction.loc[df_view.index]
    ma_conf_trades, ma_conf_summary, ma_conf_equity_curve = backtest_direction(
        df_view, ma_conf_direction_view, start_in_position=_starts_long(ma_conf_direction, df.index, df_view.index)
    )

    macd_line, signal_line, macd_hist, macd_direction = compute_macd_crossover(df)
    macd_direction_view = macd_direction.loc[df_view.index]
    macd_trades, macd_summary, macd_equity_curve = backtest_direction(
        df_view, macd_direction_view, start_in_position=_starts_long(macd_direction, df.index, df_view.index)
    )

    donch_upper, donch_lower, donch_direction = compute_donchian_breakout(df, 20)
    donch_direction_view = donch_direction.loc[df_view.index]
    donch_trades, donch_summary, donch_equity_curve = backtest_direction(
        df_view, donch_direction_view, start_in_position=_starts_long(donch_direction, df.index, df_view.index)
    )

    adx_val, plus_di, minus_di, adx_direction = compute_adx_trend(df, 14, 25)
    adx_direction_view = adx_direction.loc[df_view.index]
    adx_trades, adx_summary, adx_equity_curve = backtest_direction(
        df_view, adx_direction_view, start_in_position=_starts_long(adx_direction, df.index, df_view.index)
    )

    bb_upper, bb_mid, bb_lower, bb_direction = compute_bollinger_breakout(df, 20, 2)
    bb_direction_view = bb_direction.loc[df_view.index]
    bb_trades, bb_summary, bb_equity_curve = backtest_direction(
        df_view, bb_direction_view, start_in_position=_starts_long(bb_direction, df.index, df_view.index)
    )

    kelt_upper, kelt_mid, kelt_lower, kelt_direction = compute_keltner_breakout(df)
    kelt_direction_view = kelt_direction.loc[df_view.index]
    kelt_trades, kelt_summary, kelt_equity_curve = backtest_direction(
        df_view, kelt_direction_view, start_in_position=_starts_long(kelt_direction, df.index, df_view.index)
    )

    psar_line, psar_direction = compute_parabolic_sar(df)
    psar_direction_view = psar_direction.loc[df_view.index]
    psar_trades, psar_summary, psar_equity_curve = backtest_direction(
        df_view, psar_direction_view, start_in_position=_starts_long(psar_direction, df.index, df_view.index)
    )

    cci_val, cci_direction = compute_cci_trend(df)
    cci_direction_view = cci_direction.loc[df_view.index]
    cci_trades, cci_summary, cci_equity_curve = backtest_direction(
        df_view, cci_direction_view, start_in_position=_starts_long(cci_direction, df.index, df_view.index)
    )

    _regime, rr_direction = compute_regime_router(df)
    rr_direction_view = rr_direction.loc[df_view.index]
    rr_trades, rr_summary, rr_equity_curve = backtest_direction(
        df_view, rr_direction_view, start_in_position=_starts_long(rr_direction, df.index, df_view.index)
    )

    # Trend ribbon
    ribbon_center, ribbon_upper, ribbon_lower, ribbon_strength, ribbon_dir = compute_trend_ribbon(df)

    # For daily flips: reuse current df if already daily, otherwise fetch daily data
    if interval == "1d":
        daily_flips = {}
        # Reuse already-computed direction series to avoid redundant work
        for key, dir_series in [
            ("supertrend", direction), ("ema_crossover", ema_direction),
            ("macd", macd_direction), ("ma_confirm", ma_conf_direction),
            ("donchian", donch_direction), ("adx_trend", adx_direction),
            ("bb_breakout", bb_direction), ("keltner", kelt_direction),
            ("parabolic_sar", psar_direction), ("cci_trend", cci_direction),
            ("regime_router", rr_direction), ("ribbon", ribbon_dir),
        ]:
            date, d = last_trend_flip(dir_series)
            daily_flips[key] = {"date": date, "dir": d}
    else:
        try:
            kwargs_d = {"start": _warmup_start(start, "1d"), "interval": "1d", "progress": False}
            if end:
                kwargs_d["end"] = end
            df_d = cached_download(ticker, **kwargs_d)
            if isinstance(df_d.columns, pd.MultiIndex):
                df_d.columns = df_d.columns.get_level_values(0)
            if df_d.index.duplicated().any():
                df_d = df_d[~df_d.index.duplicated(keep="last")]
            daily_flips = compute_all_trend_flips(
                df_d, period_val=period_val, multiplier_val=multiplier_val
            )
        except Exception:
            daily_flips = {}

    # Weekly flips computed after df_w is fetched (below)

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
        else:
            st_down.append({"time": ts, "value": val, "mid": body_mid})

    trades, summary, equity_curve = backtest_supertrend(
        df_view, direction_view, start_in_position=supertrend_start_long
    )
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
        markers.append(
            {
                "time": exit_ts,
                "position": "aboveBar",
                "color": "#e91e63",
                "shape": "arrowDown",
                "text": f"SELL {t['exit_price']} ({t['pnl']:+.2f})",
            }
        )

    smas = {}
    for sma_period in [50, 100, 200]:
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

    sma_50w = []
    sma_200w = []
    weekly_flips = {}
    try:
        kwargs_w = {"start": _warmup_start(start, "1wk"), "interval": "1wk", "progress": False}
        if end:
            kwargs_w["end"] = end
        df_w = cached_download(ticker, **kwargs_w)
        if not df_w.empty:
            if isinstance(df_w.columns, pd.MultiIndex):
                df_w.columns = df_w.columns.get_level_values(0)
            if df_w.index.duplicated().any():
                df_w = df_w[~df_w.index.duplicated(keep="last")]
            df_w_view = df_w.loc[_visible_mask(df_w.index, start, end)]
            sma_w50 = df_w["Close"].rolling(window=50).mean()
            sma_w200 = df_w["Close"].rolling(window=200).mean()
            sma_w50_view = sma_w50.loc[df_w_view.index]
            sma_w200_view = sma_w200.loc[df_w_view.index]
            for i in range(len(df_w_view)):
                ts = int(df_w_view.index[i].timestamp())
                if not pd.isna(sma_w50_view.iloc[i]):
                    sma_50w.append({"time": ts, "value": round(float(sma_w50_view.iloc[i]), 2)})
                if not pd.isna(sma_w200_view.iloc[i]):
                    sma_200w.append({"time": ts, "value": round(float(sma_w200_view.iloc[i]), 2)})
            # Weekly trend flips for all indicators
            if interval == "1wk":
                # Reuse already-computed direction series
                for key, dir_series in [
                    ("supertrend", direction), ("ema_crossover", ema_direction),
                    ("macd", macd_direction), ("ma_confirm", ma_conf_direction),
                    ("donchian", donch_direction), ("adx_trend", adx_direction),
                    ("bb_breakout", bb_direction), ("keltner", kelt_direction),
                    ("parabolic_sar", psar_direction), ("cci_trend", cci_direction),
                    ("regime_router", rr_direction), ("ribbon", ribbon_dir),
                ]:
                    date, d = last_trend_flip(dir_series)
                    weekly_flips[key] = {"date": date, "dir": d}
            else:
                weekly_flips = compute_all_trend_flips(
                    df_w, period_val=period_val, multiplier_val=multiplier_val
                )
    except Exception:
        pass

    # Support / Resistance levels
    sr_levels = compute_support_resistance(df, max_levels=20)

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

    # Donchian channels
    donch_upper_data = series_to_json(donch_upper, df_view.index)
    donch_lower_data = series_to_json(donch_lower, df_view.index)

    # Bollinger Bands
    bb_upper_data = series_to_json(bb_upper, df_view.index)
    bb_mid_data = series_to_json(bb_mid, df_view.index)
    bb_lower_data = series_to_json(bb_lower, df_view.index)

    # Keltner Channels
    kelt_upper_data = series_to_json(kelt_upper, df_view.index)
    kelt_mid_data = series_to_json(kelt_mid, df_view.index)
    kelt_lower_data = series_to_json(kelt_lower, df_view.index)

    # Parabolic SAR dots (split into bull/bear for color)
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

    # ADX / +DI / -DI
    adx_data = series_to_json(adx_val, df_view.index)
    plus_di_data = series_to_json(plus_di, df_view.index)
    minus_di_data = series_to_json(minus_di, df_view.index)

    # CCI
    cci_data = series_to_json(cci_val, df_view.index)

    # Trend ribbon — upper/lower with color per bar
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

    return jsonify(
        {
            "candles": candles,
            "supertrend_up": st_up,
            "supertrend_down": st_down,
            "volumes": volumes,
            "markers": markers,
            "trades": trades,
            "summary": summary,
            "equity_curve": equity_curve,
            **smas,
            "sma_50w": sma_50w,
            "sma_200w": sma_200w,
            "strategies": {
                "supertrend": {"trades": trades, "summary": summary, "equity_curve": equity_curve},
                "ema_crossover": {"trades": ema_trades, "summary": ema_summary, "equity_curve": ema_equity_curve},
                "macd": {"trades": macd_trades, "summary": macd_summary, "equity_curve": macd_equity_curve},
                "ma_confirm": {"trades": ma_conf_trades, "summary": ma_conf_summary, "equity_curve": ma_conf_equity_curve},
                "donchian": {"trades": donch_trades, "summary": donch_summary, "equity_curve": donch_equity_curve},
                "adx_trend": {"trades": adx_trades, "summary": adx_summary, "equity_curve": adx_equity_curve},
                "bb_breakout": {"trades": bb_trades, "summary": bb_summary, "equity_curve": bb_equity_curve},
                "keltner": {"trades": kelt_trades, "summary": kelt_summary, "equity_curve": kelt_equity_curve},
                "parabolic_sar": {"trades": psar_trades, "summary": psar_summary, "equity_curve": psar_equity_curve},
                "cci_trend": {"trades": cci_trades, "summary": cci_summary, "equity_curve": cci_equity_curve},
                "regime_router": {"trades": rr_trades, "summary": rr_summary, "equity_curve": rr_equity_curve},
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
                "adx": {"adx": adx_data, "plus_di": plus_di_data, "minus_di": minus_di_data},
                "cci": {"cci": cci_data},
                "ribbon": {"upper": ribbon_upper_data, "lower": ribbon_lower_data, "center": ribbon_center_data},
            },
            "vol_profile": vol_profile,
            "trend_flips": {"daily": daily_flips, "weekly": weekly_flips},
        }
    )


@app.route("/api/watchlist")
def get_watchlist():
    return jsonify(load_watchlist())


@app.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    ticker = request.json.get("ticker", "").upper().strip()
    if not ticker:
        return jsonify({"error": "No ticker provided"}), 400
    wl = load_watchlist()
    if ticker not in wl:
        wl.append(ticker)
        save_watchlist(wl)
    return jsonify(load_watchlist())


@app.route("/api/watchlist", methods=["DELETE"])
def remove_from_watchlist():
    ticker = request.json.get("ticker", "").upper().strip()
    wl = load_watchlist()
    wl = [t for t in wl if t != ticker]
    save_watchlist(wl)
    return jsonify(load_watchlist())


@app.route("/api/watchlist/quotes")
def watchlist_quotes():
    """Get latest price, change, and change% for all watchlist tickers.

    Uses a single bulk yf.download() call instead of N individual Ticker
    requests to reduce Yahoo Finance API hits.
    """
    tickers = load_watchlist()
    if not tickers:
        return jsonify([])

    cache_key = f"quotes:{'|'.join(tickers)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    # Map display names to yfinance symbols (e.g. IXIC -> ^IXIC)
    yf_tickers = [normalize_ticker(t) for t in tickers]

    results = []
    try:
        # Bulk download last 5 trading days — enough to get prev close
        with _yf_lock:
            df = yf.download(
                yf_tickers,
                period="5d",
                interval="1d",
                progress=False,
                group_by="ticker",
                threads=False,
            )
        for yf_ticker, display_ticker in zip(yf_tickers, tickers):
            try:
                if len(yf_tickers) == 1:
                    tdf = df
                else:
                    tdf = df[yf_ticker]
                if isinstance(tdf.columns, pd.MultiIndex):
                    tdf.columns = tdf.columns.get_level_values(0)
                tdf = tdf.dropna(subset=["Close"])
                if len(tdf) < 2:
                    raise ValueError("not enough data")
                last = round(float(tdf["Close"].iloc[-1]), 2)
                prev = round(float(tdf["Close"].iloc[-2]), 2)
                chg = round(last - prev, 2)
                chg_pct = round((chg / prev) * 100, 2) if prev else 0
                results.append({"ticker": display_ticker, "last": last, "chg": chg, "chg_pct": chg_pct})
            except Exception:
                results.append({"ticker": display_ticker, "last": None, "chg": None, "chg_pct": None})
    except Exception:
        # Fallback: return empty quotes rather than error
        results = [{"ticker": t, "last": None, "chg": None, "chg_pct": None} for t in tickers]

    # Only cache if all quotes succeeded
    if all(r["last"] is not None for r in results):
        _cache_set(cache_key, results)
    return jsonify(results)


@app.route("/api/watchlist/quote/<ticker>")
def watchlist_quote(ticker):
    """Get latest price for a single ticker."""
    yf_ticker = normalize_ticker(ticker)
    cache_key = f"quote:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        with _yf_lock:
            df = yf.download(
                yf_ticker,
                period="5d",
                interval="1d",
                progress=False,
                threads=False,
            )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if len(df) < 2:
            raise ValueError("not enough data")
        last = round(float(df["Close"].iloc[-1]), 2)
        prev = round(float(df["Close"].iloc[-2]), 2)
        chg = round(last - prev, 2)
        chg_pct = round((chg / prev) * 100, 2) if prev else 0
        result = {"ticker": ticker, "last": last, "chg": chg, "chg_pct": chg_pct}
    except Exception:
        result = {"ticker": ticker, "last": None, "chg": None, "chg_pct": None}

    # Only cache successful results
    if result["last"] is not None:
        _cache_set(cache_key, result)
    return jsonify(result)


def detect_regime(df, ema_period=21, atr_period=10, adx_period=14, confirm_bars=3):
    return _detect_regime_impl(
        df,
        ema_period=ema_period,
        atr_period=atr_period,
        adx_period=adx_period,
        confirm_bars=confirm_bars,
    )


def compute_regime_router(df):
    return _compute_regime_router_impl(df)


@app.route("/report")
def report():
    return render_template("report.html")


REPORT_FILE = os.path.join(os.path.dirname(__file__), "report_data.json")


@app.route("/api/report")
def report_data():
    """Serve pre-generated report data."""
    if not os.path.exists(REPORT_FILE):
        return jsonify({"error": "No report data found. Generate it first."}), 404
    with open(REPORT_FILE) as f:
        return app.response_class(f.read(), mimetype="application/json")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=5050)
    args = parser.parse_args()
    app.run(debug=True, port=args.port)
