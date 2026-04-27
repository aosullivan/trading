import io
import json
import os
import threading
import time as _time
import urllib.request

import pandas as pd

from lib.cache import (
    _APP_DIR,
    _PROJECT_CACHE_ROOT,
    _FRED_CACHE_TTL,
    _cache_get,
    _cache_set,
    _is_yf_rate_limit_error,
    _yf_cooldown_active,
    _yf_rate_limited_download,
)

# ---------------------------------------------------------------------------
# Persistent local file cache for historical OHLCV data
# ---------------------------------------------------------------------------
_DATA_CACHE_DIR = _PROJECT_CACHE_ROOT
os.makedirs(_DATA_CACHE_DIR, exist_ok=True)

_DEFAULT_DISK_CACHE_FRESHNESS = 300  # 5 minutes
_LATEST_INTERVAL_CACHE_FRESHNESS = 3600  # 1 hour
_LAZY_REFRESH_INTERVALS = {"1d", "1wk", "1mo"}
_lazy_refresh_lock = threading.Lock()
_lazy_refreshing: set[str] = set()
_download_singleflight_lock = threading.Lock()
_download_singleflight_events: dict[str, threading.Event] = {}


def _download_singleflight_key(ticker: str, allow_stale_latest: bool, kwargs: dict) -> str:
    return (
        f"{os.path.abspath(_DATA_CACHE_DIR)}:{ticker}:{allow_stale_latest}:"
        f"{json.dumps(kwargs, sort_keys=True, default=str)}"
    )


def _enter_download_singleflight(key: str) -> tuple[bool, threading.Event]:
    with _download_singleflight_lock:
        event = _download_singleflight_events.get(key)
        if event is not None:
            return False, event
        event = threading.Event()
        _download_singleflight_events[key] = event
        return True, event


def _leave_download_singleflight(key: str, event: threading.Event) -> None:
    with _download_singleflight_lock:
        if _download_singleflight_events.get(key) is event:
            _download_singleflight_events.pop(key, None)
        event.set()


def _disk_cache_path(ticker: str, interval: str) -> str:
    """Return path to the cached CSV for a ticker+interval."""
    safe = f"{ticker}_{interval}".replace("/", "_")
    return os.path.join(_DATA_CACHE_DIR, f"{safe}.csv")


def _meta_path(ticker: str, interval: str) -> str:
    safe = f"{ticker}_{interval}".replace("/", "_")
    return os.path.join(_DATA_CACHE_DIR, f"{safe}.meta.json")


def _frame_cache_signature(df: pd.DataFrame | None) -> str:
    if df is None or df.empty:
        return "empty"
    idx = pd.Index(df.index)
    first_ts = int(pd.Timestamp(idx[0]).timestamp())
    last_ts = int(pd.Timestamp(idx[-1]).timestamp())
    last_row = df.iloc[-1]
    tail_values = []
    for col in ("Open", "High", "Low", "Close", "Volume"):
        val = last_row.get(col)
        tail_values.append("nan" if pd.isna(val) else f"{float(val):.6f}")
    return f"{len(df)}:{first_ts}:{last_ts}:{':'.join(tail_values)}"


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


def _clamped_requested_end(end) -> pd.Timestamp | None:
    if not end:
        return None
    requested_end = pd.Timestamp(end)
    now = pd.Timestamp.now().tz_localize(None)
    return min(requested_end, now)


def _disk_cache_freshness(interval: str, end) -> int:
    """Keep latest-bar cache fresh enough for lazy background refreshes.

    The chart only works with daily-or-higher bars, so re-fetching the same
    ticker every few minutes creates visible lag without meaningfully fresher
    data for the user. Historical windows still remain deterministic because
    covered ranges are sliced directly from disk.
    """
    if interval not in _LAZY_REFRESH_INTERVALS:
        return _DEFAULT_DISK_CACHE_FRESHNESS

    requested_end = _clamped_requested_end(end)
    today = pd.Timestamp.now().tz_localize(None).normalize()
    if requested_end is None or requested_end.normalize() >= today:
        return _LATEST_INTERVAL_CACHE_FRESHNESS
    return _DEFAULT_DISK_CACHE_FRESHNESS


def _cached_range_covers_request(cached_df: pd.DataFrame | None, start, end) -> bool:
    if cached_df is None or cached_df.empty:
        return False
    cached_min = pd.Timestamp(cached_df.index.min())
    cached_max = pd.Timestamp(cached_df.index.max())
    if start and pd.Timestamp(start) < cached_min:
        return False
    requested_end = _clamped_requested_end(end)
    if requested_end is not None and requested_end > cached_max:
        return False
    return True


def _is_latest_interval_request(interval: str, end) -> bool:
    if interval not in _LAZY_REFRESH_INTERVALS:
        return False
    requested_end = _clamped_requested_end(end)
    today = pd.Timestamp.now().tz_localize(None).normalize()
    return requested_end is None or requested_end.normalize() >= today


def _lazy_refresh_key(ticker: str, kwargs: dict) -> str:
    return f"{ticker}:{json.dumps(kwargs, sort_keys=True, default=str)}"


def _schedule_lazy_cache_refresh(ticker: str, kwargs: dict):
    refresh_kwargs = dict(kwargs)
    refresh_key = _lazy_refresh_key(ticker, refresh_kwargs)
    with _lazy_refresh_lock:
        if refresh_key in _lazy_refreshing:
            return
        _lazy_refreshing.add(refresh_key)

    def _refresh():
        try:
            cached_download(ticker, allow_stale_latest=False, **refresh_kwargs)
        except Exception:
            pass
        finally:
            with _lazy_refresh_lock:
                _lazy_refreshing.discard(refresh_key)

    threading.Thread(target=_refresh, daemon=True).start()


def cached_download(ticker: str, *, allow_stale_latest: bool = True, **kwargs) -> pd.DataFrame:
    """Download OHLCV data with persistent local file cache.

    Concurrent identical misses are coalesced: the first caller fetches/writes,
    while later callers wait briefly and then reuse the cache the first caller
    just populated.
    """
    key = _download_singleflight_key(ticker, allow_stale_latest, kwargs)
    is_owner, event = _enter_download_singleflight(key)
    if not is_owner:
        event.wait(timeout=90)
        return _cached_download_impl(ticker, allow_stale_latest=allow_stale_latest, **kwargs)

    try:
        return _cached_download_impl(ticker, allow_stale_latest=allow_stale_latest, **kwargs)
    finally:
        _leave_download_singleflight(key, event)


def _cached_download_impl(ticker: str, *, allow_stale_latest: bool = True, **kwargs) -> pd.DataFrame:
    """Download OHLCV data with persistent local file cache."""
    interval = kwargs.get("interval", "1d")
    start = kwargs.get("start")
    end = kwargs.get("end")

    if start is None or "period" in kwargs:
        key = f"dl:{ticker}:{json.dumps(kwargs, sort_keys=True, default=str)}"
        cached = _cache_get(key)
        if cached is not None:
            return cached
        download_kwargs = dict(kwargs)
        download_kwargs.setdefault("threads", False)
        try:
            df = _yf_rate_limited_download(ticker, **download_kwargs)
        except Exception as exc:
            if _is_yf_rate_limit_error(exc):
                return pd.DataFrame()
            raise
        _cache_set(key, df)
        return df

    csv_path = _disk_cache_path(ticker, interval)
    meta_p = _meta_path(ticker, interval)
    cached_df = None

    if os.path.exists(csv_path):
        try:
            cached_df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            if cached_df.index.duplicated().any():
                cached_df = cached_df[~cached_df.index.duplicated(keep="last")]
        except Exception:
            cached_df = None

    now = _time.time()
    if os.path.exists(meta_p):
        try:
            with open(meta_p) as f:
                meta = json.load(f)
            last_fetch = float(meta.get("last_fetch", 0))
            cache_age = now - last_fetch
            freshness = _disk_cache_freshness(interval, end)
            cache_covers_request = _cached_range_covers_request(cached_df, start, end)
            if cache_covers_request and cache_age < freshness:
                return _slice_df(cached_df, start, end)
            if (
                cache_covers_request
                and allow_stale_latest
                and _is_latest_interval_request(interval, end)
            ):
                _schedule_lazy_cache_refresh(ticker, kwargs)
                return _slice_df(cached_df, start, end)
        except Exception:
            pass

    if cached_df is not None and not cached_df.empty:
        first_cached = cached_df.index.min()
        last_cached = cached_df.index.max()
        if start and pd.Timestamp(start) < pd.Timestamp(first_cached):
            fetch_start = start
        elif interval == "1wk":
            fetch_start = last_cached.strftime("%Y-%m-%d")
        else:
            fetch_start = (last_cached + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        requested_end = _clamped_requested_end(end)
        if requested_end is not None and pd.Timestamp(fetch_start) > requested_end:
            _write_meta(meta_p, now, cached_df)
            return _slice_df(cached_df, start, end)
        if pd.Timestamp(fetch_start) > pd.Timestamp.now():
            _write_meta(meta_p, now, cached_df)
            return _slice_df(cached_df, start, end)
    else:
        fetch_start = start

    if _yf_cooldown_active():
        if cached_df is not None:
            return _slice_df(cached_df, start, end)
        return pd.DataFrame()

    fetch_kwargs = dict(kwargs)
    fetch_kwargs["start"] = fetch_start
    fetch_kwargs["progress"] = False
    fetch_kwargs.setdefault("threads", False)
    try:
        new_df = _yf_rate_limited_download(ticker, **fetch_kwargs)
    except Exception as exc:
        if cached_df is not None:
            return _slice_df(cached_df, start, end)
        if _is_yf_rate_limit_error(exc):
            return pd.DataFrame()
        return pd.DataFrame()

    if isinstance(new_df.columns, pd.MultiIndex):
        new_df.columns = new_df.columns.get_level_values(0)

    if not new_df.empty and new_df.index.duplicated().any():
        new_df = new_df[~new_df.index.duplicated(keep="last")]

    if _incremental_data_failed_validation(cached_df, new_df, interval):
        _write_meta(meta_p, now, cached_df)
        return _slice_df(cached_df, start, end)

    if cached_df is not None and not cached_df.empty and not new_df.empty:
        combined = pd.concat([cached_df, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
    elif not new_df.empty:
        combined = new_df
    else:
        combined = cached_df if cached_df is not None else pd.DataFrame()

    should_write_combined = not combined.empty and not (
        new_df.empty and cached_df is not None and not cached_df.empty
    )

    if should_write_combined:
        # Atomic write: tempfile + os.replace so concurrent readers never see
        # a half-written CSV and concurrent writers last-writer-wins cleanly.
        tmp_path = f"{csv_path}.tmp.{os.getpid()}.{threading.get_ident()}"
        try:
            combined.to_csv(tmp_path)
            os.replace(tmp_path, csv_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    _write_meta(meta_p, now, combined)
    return _slice_df(combined, start, end)


def _write_meta(meta_path: str, now: float, df: pd.DataFrame | None = None):
    try:
        payload = {"last_fetch": now}
        if df is not None:
            payload["data_signature"] = _frame_cache_signature(df)
        with open(meta_path, "w") as f:
            json.dump(payload, f)
    except Exception:
        pass


def _slice_df(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Return the subset of df within [start, end]."""
    if df.empty:
        return df
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
    "TNX", "TYX", "FVX", "IRX",
    "SOX",
    "SPX",
}

_TREASURY_YIELD_SERIES = {
    "UST1Y": {"fred_id": "DGS1", "name": "1-Year Treasury Yield"},
    "UST2Y": {"fred_id": "DGS2", "name": "2-Year Treasury Yield"},
    "UST3Y": {"fred_id": "DGS3", "name": "3-Year Treasury Yield"},
    "UST5Y": {"fred_id": "DGS5", "name": "5-Year Treasury Yield"},
    "UST7Y": {"fred_id": "DGS7", "name": "7-Year Treasury Yield"},
    "UST10Y": {"fred_id": "DGS10", "name": "10-Year Treasury Yield"},
    "UST20Y": {"fred_id": "DGS20", "name": "20-Year Treasury Yield"},
    "UST30Y": {"fred_id": "DGS30", "name": "30-Year Treasury Yield"},
}

_TREASURY_PRICE_PROXIES = {
    "UST1Y": {"yf_ticker": "SHY", "name": "1-Year Treasury Price Proxy (SHY)"},
    "UST2Y": {"yf_ticker": "SHY", "name": "2-Year Treasury Price Proxy (SHY)"},
    "UST3Y": {"yf_ticker": "IEI", "name": "3-Year Treasury Price Proxy (IEI)"},
    "UST5Y": {"yf_ticker": "IEI", "name": "5-Year Treasury Price Proxy (IEI)"},
    "UST10Y": {"yf_ticker": "IEF", "name": "10-Year Treasury Price Proxy (IEF)"},
    "UST20Y": {"yf_ticker": "TLH", "name": "20-Year Treasury Price Proxy (TLH)"},
    "UST30Y": {"yf_ticker": "TLT", "name": "30-Year Treasury Price Proxy (TLT)"},
}

_FRED_DATE_COLUMNS = ("DATE", "observation_date")


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


def is_treasury_yield_ticker(ticker: str) -> bool:
    return ticker.upper() in _TREASURY_YIELD_SERIES


def is_treasury_price_ticker(ticker: str) -> bool:
    return ticker.upper() in _TREASURY_PRICE_PROXIES


def resolve_treasury_price_proxy_ticker(ticker: str) -> str:
    proxy = _TREASURY_PRICE_PROXIES.get(ticker.upper())
    return proxy["yf_ticker"] if proxy else ticker


def _fetch_treasury_yield_history(ticker: str, start=None, end=None) -> pd.DataFrame:
    """Fetch and cache Treasury yield history from FRED without an API key."""
    meta = _TREASURY_YIELD_SERIES.get(ticker.upper())
    if meta is None:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    cache_key = f"fred:{meta['fred_id']}"
    cached = _cache_get(cache_key)
    if cached is None:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={meta['fred_id']}"
        req = urllib.request.urlopen(url, timeout=5)
        source = pd.read_csv(io.StringIO(req.read().decode("utf-8")))
        date_col = next((col for col in _FRED_DATE_COLUMNS if col in source.columns), None)
        if source.empty or date_col is None or meta["fred_id"] not in source.columns:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        source[date_col] = pd.to_datetime(source[date_col], errors="coerce")
        source[meta["fred_id"]] = pd.to_numeric(source[meta["fred_id"]], errors="coerce")
        source = (
            source.dropna(subset=[date_col, meta["fred_id"]])
            .set_index(date_col)
            .sort_index()
        )
        cached = source.rename(columns={meta["fred_id"]: "Close"})[["Close"]]
        cached["Open"] = cached["Close"]
        cached["High"] = cached["Close"]
        cached["Low"] = cached["Close"]
        cached["Volume"] = 0
        cached = cached[["Open", "High", "Low", "Close", "Volume"]]
        _cache_set(cache_key, cached, ttl=_FRED_CACHE_TTL)

    df = cached.copy()
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def _quote_from_frame(ticker: str, df: pd.DataFrame) -> dict:
    df = df.dropna(subset=["Close"])
    if len(df) < 2:
        return {"ticker": ticker, "last": None, "chg": None, "chg_pct": None}
    last = round(float(df["Close"].iloc[-1]), 2)
    prev = round(float(df["Close"].iloc[-2]), 2)
    chg = round(last - prev, 2)
    chg_pct = round((chg / prev) * 100, 2) if prev else 0
    return {"ticker": ticker, "last": last, "chg": chg, "chg_pct": chg_pct}


def _fetch_market_quote_frame(yf_ticker: str) -> pd.DataFrame:
    df = _yf_rate_limited_download(
        yf_ticker,
        period="5d",
        interval="1d",
        progress=False,
        threads=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _fetch_market_quote(display_ticker: str, yf_ticker: str) -> dict:
    return _quote_from_frame(display_ticker, _fetch_market_quote_frame(yf_ticker))
