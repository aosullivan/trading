import io
import json
import os
import time as _time
import urllib.request

import pandas as pd

from lib.cache import (
    _APP_DIR,
    _PROJECT_CACHE_ROOT,
    _FRED_CACHE_TTL,
    _cache_get,
    _cache_set,
    _yf_rate_limited_download,
)

# ---------------------------------------------------------------------------
# Persistent local file cache for historical OHLCV data
# ---------------------------------------------------------------------------
_DATA_CACHE_DIR = _PROJECT_CACHE_ROOT
os.makedirs(_DATA_CACHE_DIR, exist_ok=True)

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
        df = _yf_rate_limited_download(ticker, **download_kwargs)
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
            if (now - meta.get("last_fetch", 0)) < _DISK_CACHE_FRESHNESS and cached_df is not None:
                return _slice_df(cached_df, start, end)
        except Exception:
            pass

    if cached_df is not None and not cached_df.empty:
        last_cached = cached_df.index.max()
        if interval == "1wk":
            fetch_start = last_cached.strftime("%Y-%m-%d")
        else:
            fetch_start = (last_cached + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if pd.Timestamp(fetch_start) > pd.Timestamp.now():
            _write_meta(meta_p, now)
            return _slice_df(cached_df, start, end)
    else:
        fetch_start = start

    fetch_kwargs = dict(kwargs)
    fetch_kwargs["start"] = fetch_start
    fetch_kwargs["progress"] = False
    fetch_kwargs.setdefault("threads", False)
    try:
        new_df = _yf_rate_limited_download(ticker, **fetch_kwargs)
    except Exception:
        if cached_df is not None:
            return _slice_df(cached_df, start, end)
        return pd.DataFrame()

    if isinstance(new_df.columns, pd.MultiIndex):
        new_df.columns = new_df.columns.get_level_values(0)

    if not new_df.empty and new_df.index.duplicated().any():
        new_df = new_df[~new_df.index.duplicated(keep="last")]

    if _incremental_data_failed_validation(cached_df, new_df, interval):
        _write_meta(meta_p, now)
        return _slice_df(cached_df, start, end)

    if cached_df is not None and not cached_df.empty and not new_df.empty:
        combined = pd.concat([cached_df, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
    elif not new_df.empty:
        combined = new_df
    else:
        combined = cached_df if cached_df is not None else pd.DataFrame()

    if not combined.empty:
        try:
            combined.to_csv(csv_path)
        except Exception:
            pass

    _write_meta(meta_p, now)
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
        if source.empty or "DATE" not in source.columns or meta["fred_id"] not in source.columns:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        source["DATE"] = pd.to_datetime(source["DATE"], errors="coerce")
        source[meta["fred_id"]] = pd.to_numeric(source[meta["fred_id"]], errors="coerce")
        source = source.dropna(subset=["DATE", meta["fred_id"]]).set_index("DATE").sort_index()
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
