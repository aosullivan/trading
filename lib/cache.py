import json
import os
import time as _time
import threading

import yfinance as yf

_APP_DIR = os.path.dirname(os.path.dirname(__file__))
_PROJECT_CACHE_ROOT = os.path.join(_APP_DIR, "data_cache")
_TICKER_INFO_CACHE_DIR = os.path.join(_PROJECT_CACHE_ROOT, "ticker_info")
_YF_CACHE_DIR = os.path.join(_PROJECT_CACHE_ROOT, "yfinance")


def _configure_yfinance_cache(cache_dir: str | None = None) -> str:
    """Pin yfinance's SQLite-backed caches to a writable project-local folder."""
    resolved_dir = cache_dir or _YF_CACHE_DIR
    os.makedirs(resolved_dir, exist_ok=True)
    yf.set_tz_cache_location(resolved_dir)
    return resolved_dir


_configure_yfinance_cache()

# ---------------------------------------------------------------------------
# In-memory TTL cache (for quotes and short-lived data)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # seconds (5 minutes)
_CHART_CACHE_TTL = 300  # seconds (5 minutes)
_TICKER_INFO_CACHE_TTL = 3600  # seconds (1 hour)
_TICKER_INFO_DISK_CACHE_TTL = 86400  # seconds (24 hours)
_FINANCIALS_CACHE_TTL = 3600  # seconds (1 hour)
_FRED_CACHE_TTL = 900  # seconds (15 minutes)
_WATCHLIST_QUOTES_REFRESH_TTL = 300  # seconds (5 minutes)
_WATCHLIST_QUOTES_STALE_TTL = 1800  # seconds (30 minutes)
_yf_lock = threading.Lock()
_yf_last_call = 0.0
_YF_RATE_DELAY = 1.5
_watchlist_quotes_cache: dict[str, dict[str, object]] = {}
_watchlist_quotes_lock = threading.Lock()
_watchlist_quote_refreshing: set[str] = set()


def _cache_get(key: str):
    """Return cached value if still fresh, else None."""
    entry = _cache.get(key)
    if entry and _time.time() < entry[0]:
        return entry[1]
    if entry:
        _cache.pop(key, None)
    return None


def _cache_set(key: str, value, ttl: int = _CACHE_TTL):
    _cache[key] = (_time.time() + ttl, value)


def _ticker_info_cache_path(ticker: str) -> str:
    safe = ticker.replace("/", "_").replace("^", "caret_")
    return os.path.join(_TICKER_INFO_CACHE_DIR, f"{safe}.json")


def _read_disk_ticker_info(ticker: str) -> dict | None:
    path = _ticker_info_cache_path(ticker)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        if (_time.time() - payload.get("last_fetch", 0)) > _TICKER_INFO_DISK_CACHE_TTL:
            return None
        info = payload.get("info")
        return info if isinstance(info, dict) else None
    except Exception:
        return None


def _write_disk_ticker_info(ticker: str, info: dict):
    try:
        os.makedirs(_TICKER_INFO_CACHE_DIR, exist_ok=True)
        with open(_ticker_info_cache_path(ticker), "w") as f:
            json.dump({"last_fetch": _time.time(), "info": info}, f)
    except Exception:
        pass


def _yf_rate_limited_download(tickers, **kwargs):
    """Call yf.download with rate limiting to avoid 429s from Yahoo Finance."""
    global _yf_last_call
    with _yf_lock:
        elapsed = _time.time() - _yf_last_call
        if elapsed < _YF_RATE_DELAY:
            _time.sleep(_YF_RATE_DELAY - elapsed)
        result = yf.download(tickers, **kwargs)
        _yf_last_call = _time.time()
    return result


def _yf_rate_limited_info(ticker: str):
    """Fetch yf.Ticker(...).info with the same rate limiting as downloads."""
    global _yf_last_call
    with _yf_lock:
        elapsed = _time.time() - _yf_last_call
        if elapsed < _YF_RATE_DELAY:
            _time.sleep(_YF_RATE_DELAY - elapsed)
        result = yf.Ticker(ticker).info
        _yf_last_call = _time.time()
    return result


def _get_cached_ticker_info(ticker: str) -> dict:
    """Return cached ticker info so chart loads and financials don't spam Yahoo."""
    cache_key = f"info:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    disk_cached = _read_disk_ticker_info(ticker)
    if disk_cached is not None:
        _cache_set(cache_key, disk_cached, ttl=_TICKER_INFO_CACHE_TTL)
        return disk_cached
    info = _yf_rate_limited_info(ticker)
    _cache_set(cache_key, info, ttl=_TICKER_INFO_CACHE_TTL)
    _write_disk_ticker_info(ticker, info)
    return info


def _get_watchlist_quotes_cache(cache_key: str) -> tuple[list[dict], float] | None:
    with _watchlist_quotes_lock:
        entry = _watchlist_quotes_cache.get(cache_key)
        if not entry:
            return None
        fetched_at = float(entry.get("fetched_at", 0))
        if (_time.time() - fetched_at) > _WATCHLIST_QUOTES_STALE_TTL:
            _watchlist_quotes_cache.pop(cache_key, None)
            return None
        return entry.get("quotes", []), fetched_at


def _set_watchlist_quotes_cache(cache_key: str, quotes: list[dict]):
    with _watchlist_quotes_lock:
        _watchlist_quotes_cache[cache_key] = {
            "quotes": quotes,
            "fetched_at": _time.time(),
        }
