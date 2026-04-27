import json
import os
import time as _time
import threading

import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from lib.paths import get_resource_path, get_user_data_path

_APP_DIR = get_resource_path()
_PROJECT_CACHE_ROOT = get_user_data_path("data_cache")
_TICKER_INFO_CACHE_DIR = os.path.join(_PROJECT_CACHE_ROOT, "ticker_info")
_YF_CACHE_DIR = os.path.join(_PROJECT_CACHE_ROOT, "yfinance")


def _configure_yfinance_cache(cache_dir: str | None = None) -> str:
    """Pin yfinance's SQLite-backed caches to a writable per-user folder."""
    resolved_dir = cache_dir or _YF_CACHE_DIR
    os.makedirs(resolved_dir, exist_ok=True)
    yf.set_tz_cache_location(resolved_dir)
    return resolved_dir


_configure_yfinance_cache()

# ---------------------------------------------------------------------------
# In-memory TTL cache (for quotes and short-lived data)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.RLock()  # guards _cache against concurrent threads
_CACHE_TTL = 300  # seconds (5 minutes)
_CHART_CACHE_TTL = 300  # seconds (5 minutes)
_TICKER_INFO_CACHE_TTL = 3600  # seconds (1 hour)
_TICKER_INFO_DISK_CACHE_TTL = 86400  # seconds (24 hours)
_FINANCIALS_CACHE_TTL = 3600  # seconds (1 hour)
_FRED_CACHE_TTL = 900  # seconds (15 minutes)
_WATCHLIST_QUOTES_REFRESH_TTL = 300  # seconds (5 minutes)
_WATCHLIST_QUOTES_STALE_TTL = 1800  # seconds (30 minutes)
_WATCHLIST_TRENDS_REFRESH_TTL = 300  # seconds (5 minutes)
_WATCHLIST_TRENDS_STALE_TTL = 3600  # seconds (1 hour)
_yf_lock = threading.RLock()
_yf_last_call = 0.0
_yf_cooldown_until = 0.0
_yf_cooldown_reason = ""
_YF_RATE_DELAY = 1.5
_YF_RATE_LIMIT_COOLDOWN = 600  # seconds (10 minutes)
_watchlist_quotes_cache: dict[str, dict[str, object]] = {}
_watchlist_quotes_lock = threading.Lock()
_watchlist_quote_refreshing: set[str] = set()
_watchlist_trends_cache: dict[str, dict[str, object]] = {}
_watchlist_trends_lock = threading.Lock()
_watchlist_trend_refreshing: set[str] = set()
_ticker_info_lock = threading.Lock()
_ticker_info_refreshing: set[str] = set()


def _cache_get(key: str):
    """Return cached value if still fresh, else None."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry and _time.time() < entry[0]:
            return entry[1]
        if entry:
            _cache.pop(key, None)
        return None


def _cache_set(key: str, value, ttl: int = _CACHE_TTL):
    with _cache_lock:
        _cache[key] = (_time.time() + ttl, value)


def _is_yf_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, YFRateLimitError) or "429" in text or "too many requests" in text


def _set_yf_cooldown(exc: BaseException | str, cooldown: int = _YF_RATE_LIMIT_COOLDOWN) -> None:
    global _yf_cooldown_until, _yf_cooldown_reason
    with _yf_lock:
        _yf_cooldown_until = max(_yf_cooldown_until, _time.time() + cooldown)
        _yf_cooldown_reason = str(exc)


def _yf_cooldown_active() -> bool:
    return _time.time() < _yf_cooldown_until


def _raise_if_yf_cooldown_active() -> None:
    if _yf_cooldown_active():
        reason = _yf_cooldown_reason or "Yahoo Finance cooldown active"
        raise YFRateLimitError(reason)


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
        _raise_if_yf_cooldown_active()
        elapsed = _time.time() - _yf_last_call
        if elapsed < _YF_RATE_DELAY:
            _time.sleep(_YF_RATE_DELAY - elapsed)
        try:
            result = yf.download(tickers, **kwargs)
        except Exception as exc:
            if _is_yf_rate_limit_error(exc):
                _set_yf_cooldown(exc)
            raise
        finally:
            _yf_last_call = _time.time()
    return result


def _yf_rate_limited_info(ticker: str):
    """Fetch yf.Ticker(...).info with the same rate limiting as downloads."""
    global _yf_last_call
    with _yf_lock:
        _raise_if_yf_cooldown_active()
        elapsed = _time.time() - _yf_last_call
        if elapsed < _YF_RATE_DELAY:
            _time.sleep(_YF_RATE_DELAY - elapsed)
        try:
            result = yf.Ticker(ticker).info
        except Exception as exc:
            if _is_yf_rate_limit_error(exc):
                _set_yf_cooldown(exc)
            raise
        finally:
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


def _get_cached_ticker_info_if_fresh(ticker: str) -> dict | None:
    """Return ticker info from memory/disk cache only, without blocking on Yahoo."""
    cache_key = f"info:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    disk_cached = _read_disk_ticker_info(ticker)
    if disk_cached is not None:
        _cache_set(cache_key, disk_cached, ttl=_TICKER_INFO_CACHE_TTL)
    return disk_cached


def _warm_ticker_info_cache_async(ticker: str):
    """Refresh ticker info in the background so chart loads don't wait on metadata."""
    if _get_cached_ticker_info_if_fresh(ticker) is not None:
        return
    with _ticker_info_lock:
        if ticker in _ticker_info_refreshing:
            return
        _ticker_info_refreshing.add(ticker)

    def _refresh():
        try:
            _get_cached_ticker_info(ticker)
        except Exception:
            pass
        finally:
            with _ticker_info_lock:
                _ticker_info_refreshing.discard(ticker)

    threading.Thread(target=_refresh, daemon=True).start()


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


def _get_watchlist_trends_cache(cache_key: str) -> tuple[list[dict], float] | None:
    with _watchlist_trends_lock:
        entry = _watchlist_trends_cache.get(cache_key)
        if not entry:
            return None
        fetched_at = float(entry.get("fetched_at", 0))
        if (_time.time() - fetched_at) > _WATCHLIST_TRENDS_STALE_TTL:
            _watchlist_trends_cache.pop(cache_key, None)
            return None
        return entry.get("items", []), fetched_at


def _set_watchlist_trends_cache(cache_key: str, items: list[dict]):
    with _watchlist_trends_lock:
        _watchlist_trends_cache[cache_key] = {
            "items": items,
            "fetched_at": _time.time(),
        }
