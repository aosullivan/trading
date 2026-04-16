import json
import os
import time as _time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, request, jsonify, current_app
import pandas as pd

from lib.cache import (
    _cache_get,
    _cache_set,
    _yf_rate_limited_download,
    _WATCHLIST_QUOTES_REFRESH_TTL,
    _WATCHLIST_TRENDS_REFRESH_TTL,
    _watchlist_quotes_lock,
    _watchlist_quote_refreshing,
    _watchlist_trends_lock,
    _watchlist_trend_refreshing,
    _get_watchlist_quotes_cache,
    _set_watchlist_quotes_cache,
    _get_watchlist_trends_cache,
    _set_watchlist_trends_cache,
)
from lib.chart_serialization import compute_all_trend_flips
from lib.data_fetching import (
    cached_download,
    normalize_ticker,
    _quote_from_frame,
    _fetch_market_quote_frame,
    _fetch_market_quote,
    resolve_treasury_price_proxy_ticker,
)
from lib.paths import get_resource_path, get_user_data_path
from lib.trade_setup import compute_trade_setup
from lib.technical_indicators import SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD

bp = Blueprint("watchlist", __name__)

DEFAULT_WATCHLIST_FILE = get_resource_path("watchlist.json")
WATCHLIST_FILE = get_user_data_path("watchlist.json")
_TRENDS_CACHE_DIR = get_user_data_path("data_cache", "watchlist_trends")
_TRENDS_START_DATE = "2015-01-01"
_TRENDS_PERIOD = SUPERTREND_PERIOD
_TRENDS_MULTIPLIER = SUPERTREND_MULTIPLIER
_TRENDS_CACHE_VERSION = 6
_TRENDS_REFRESH_BATCH_SIZE = 6
_TRENDS_REFRESH_BATCH_PAUSE = 0.25
_WATCHLIST_PREWARM_INTERVALS = ("1d", "1wk")
_WATCHLIST_PREFETCH_STATE_FILE = get_user_data_path("watchlist_prefetch_state.json")
_watchlist_history_prewarm_lock = threading.Lock()
_watchlist_history_prewarming: set[str] = set()
_watchlist_daily_prefetch_lock = threading.Lock()
_watchlist_daily_prefetch_running = False


def _empty_trend_row(ticker: str) -> dict:
    return {"ticker": ticker, "daily": {}, "weekly": {}, "trade_setup": {}}


def _empty_quote_row(ticker: str) -> dict:
    return {"ticker": ticker, "last": None, "chg": None, "chg_pct": None}


def _normalize_trend_row(ticker: str, row: dict | None) -> dict:
    if not isinstance(row, dict):
        return _empty_trend_row(ticker)
    daily = row.get("daily")
    weekly = row.get("weekly")
    trade_setup = row.get("trade_setup")
    return {
        "ticker": ticker,
        "daily": daily if isinstance(daily, dict) else {},
        "weekly": weekly if isinstance(weekly, dict) else {},
        "trade_setup": trade_setup if isinstance(trade_setup, dict) else {},
    }


def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    if os.path.exists(DEFAULT_WATCHLIST_FILE):
        with open(DEFAULT_WATCHLIST_FILE) as f:
            tickers = json.load(f)
        save_watchlist(tickers)
        return tickers
    return []


def save_watchlist(tickers):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(sorted(set(t.upper() for t in tickers)), f)


@bp.route("/api/watchlist")
def get_watchlist():
    tickers = load_watchlist()
    return jsonify(tickers)


@bp.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    ticker = request.json.get("ticker", "").upper().strip()
    if not ticker:
        return jsonify({"error": "No ticker provided"}), 400
    wl = load_watchlist()
    if ticker not in wl:
        wl.append(ticker)
        save_watchlist(wl)
        _schedule_watchlist_history_prewarm([ticker])
    return jsonify(load_watchlist())


@bp.route("/api/watchlist", methods=["DELETE"])
def remove_from_watchlist():
    ticker = request.json.get("ticker", "").upper().strip()
    wl = load_watchlist()
    wl = [t for t in wl if t != ticker]
    save_watchlist(wl)
    return jsonify(load_watchlist())


def _watchlist_history_prewarm_key(ticker: str, interval: str) -> str:
    return f"{ticker}:{interval}"


def _prewarm_watchlist_ticker_history(ticker: str):
    data_ticker = normalize_ticker(resolve_treasury_price_proxy_ticker(ticker))
    try:
        for interval in _WATCHLIST_PREWARM_INTERVALS:
            cached_download(
                data_ticker,
                start=_TRENDS_START_DATE,
                interval=interval,
                progress=False,
                threads=False,
            )
    finally:
        with _watchlist_history_prewarm_lock:
            for interval in _WATCHLIST_PREWARM_INTERVALS:
                _watchlist_history_prewarming.discard(
                    _watchlist_history_prewarm_key(ticker, interval)
                )


def _schedule_watchlist_history_prewarm(tickers: list[str]):
    if current_app.config.get("TESTING"):
        return
    pending: list[str] = []
    with _watchlist_history_prewarm_lock:
        for ticker in tickers:
            normalized = ticker.upper().strip()
            if not normalized:
                continue
            needs_work = False
            for interval in _WATCHLIST_PREWARM_INTERVALS:
                key = _watchlist_history_prewarm_key(normalized, interval)
                if key in _watchlist_history_prewarming:
                    continue
                _watchlist_history_prewarming.add(key)
                needs_work = True
            if needs_work:
                pending.append(normalized)

    for ticker in pending:
        threading.Thread(
            target=_prewarm_watchlist_ticker_history,
            args=(ticker,),
            daemon=True,
        ).start()


def _watchlist_prefetch_signature(tickers: list[str]) -> list[str]:
    return sorted({ticker.upper().strip() for ticker in tickers if ticker and ticker.strip()})


def _read_watchlist_prefetch_state() -> dict:
    if not os.path.exists(_WATCHLIST_PREFETCH_STATE_FILE):
        return {}
    try:
        with open(_WATCHLIST_PREFETCH_STATE_FILE) as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_watchlist_prefetch_state(tickers: list[str]):
    try:
        os.makedirs(os.path.dirname(_WATCHLIST_PREFETCH_STATE_FILE), exist_ok=True)
        with open(_WATCHLIST_PREFETCH_STATE_FILE, "w") as f:
            json.dump(
                {
                    "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                    "tickers": _watchlist_prefetch_signature(tickers),
                },
                f,
            )
    except Exception:
        pass


def _watchlist_daily_prefetch_needed(tickers: list[str]) -> bool:
    state = _read_watchlist_prefetch_state()
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    return (
        state.get("date") != today
        or state.get("tickers") != _watchlist_prefetch_signature(tickers)
    )


def _run_daily_watchlist_prefetch(tickers: list[str]):
    global _watchlist_daily_prefetch_running
    try:
        for ticker in tickers:
            data_ticker = normalize_ticker(resolve_treasury_price_proxy_ticker(ticker))
            for interval in _WATCHLIST_PREWARM_INTERVALS:
                cached_download(
                    data_ticker,
                    start=_TRENDS_START_DATE,
                    interval=interval,
                    progress=False,
                    threads=False,
                    allow_stale_latest=False,
                )
        _write_watchlist_prefetch_state(tickers)
    finally:
        with _watchlist_daily_prefetch_lock:
            _watchlist_daily_prefetch_running = False


def schedule_daily_watchlist_prefetch():
    global _watchlist_daily_prefetch_running
    if current_app.config.get("TESTING"):
        return
    tickers = load_watchlist()
    if not tickers or not _watchlist_daily_prefetch_needed(tickers):
        return
    with _watchlist_daily_prefetch_lock:
        if _watchlist_daily_prefetch_running:
            return
        _watchlist_daily_prefetch_running = True
    threading.Thread(
        target=_run_daily_watchlist_prefetch,
        args=(_watchlist_prefetch_signature(tickers),),
        daemon=True,
    ).start()


def _build_watchlist_quotes(tickers: list[str]) -> list[dict]:
    market_tickers = list(tickers)
    results_by_ticker = {}
    needs_retry: list[tuple[str, str]] = []

    if market_tickers:
        market_pairs = [
            (display_ticker, normalize_ticker(resolve_treasury_price_proxy_ticker(display_ticker)))
            for display_ticker in market_tickers
        ]
        yf_tickers = list(dict.fromkeys(yf_ticker for _, yf_ticker in market_pairs))
        bulk_loaded = False
        try:
            df = _yf_rate_limited_download(
                yf_tickers,
                period="5d",
                interval="1d",
                progress=False,
                group_by="ticker",
                threads=False,
            )
            for display_ticker, yf_ticker in market_pairs:
                try:
                    if len(yf_tickers) == 1:
                        tdf = df
                    else:
                        tdf = df[yf_ticker]
                    if isinstance(tdf.columns, pd.MultiIndex):
                        tdf.columns = tdf.columns.get_level_values(0)
                    quote = _quote_from_frame(display_ticker, tdf)
                    if quote["last"] is None:
                        needs_retry.append((display_ticker, yf_ticker))
                    else:
                        _cache_set(f"quote:{display_ticker}", quote)
                    results_by_ticker[display_ticker] = quote
                except Exception:
                    needs_retry.append((display_ticker, yf_ticker))
            bulk_loaded = True
        except Exception:
            bulk_loaded = False

        if not bulk_loaded:
            needs_retry = market_pairs

        for display_ticker, yf_ticker in needs_retry:
            try:
                quote = _fetch_market_quote(display_ticker, yf_ticker)
                if quote["last"] is not None:
                    _cache_set(f"quote:{display_ticker}", quote)
                results_by_ticker[display_ticker] = quote
            except Exception:
                results_by_ticker[display_ticker] = _empty_quote_row(display_ticker)

    return [
        results_by_ticker.get(
            ticker,
            _empty_quote_row(ticker),
        )
        for ticker in tickers
    ]


def _refresh_watchlist_quotes_cache(cache_key: str, tickers: list[str]):
    try:
        quotes = _build_watchlist_quotes(tickers)
        if quotes and any(q["last"] is not None for q in quotes):
            _set_watchlist_quotes_cache(cache_key, quotes)
    finally:
        with _watchlist_quotes_lock:
            _watchlist_quote_refreshing.discard(cache_key)


def _schedule_watchlist_quotes_refresh(cache_key: str, tickers: list[str]):
    with _watchlist_quotes_lock:
        if cache_key in _watchlist_quote_refreshing:
            return
        _watchlist_quote_refreshing.add(cache_key)
    threading.Thread(
        target=_refresh_watchlist_quotes_cache,
        args=(cache_key, list(tickers)),
        daemon=True,
    ).start()


def _load_watchlist_quote_snapshot_rows(tickers: list[str]) -> list[dict]:
    rows: list[dict] = []
    for ticker in tickers:
        cached = _cache_get(f"quote:{ticker}")
        rows.append(cached if isinstance(cached, dict) else _empty_quote_row(ticker))
    return rows


def _normalize_trends_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    return df


def _trend_frame_date(df: pd.DataFrame) -> str | None:
    if df is None or df.empty:
        return None
    return pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")


def _trend_cache_path(ticker: str) -> str:
    safe = ticker.replace("/", "_").replace("^", "caret_")
    return os.path.join(_TRENDS_CACHE_DIR, f"{safe}.json")


def _read_disk_trend_payload(ticker: str, *, allow_stale: bool = False) -> dict | None:
    path = _trend_cache_path(ticker)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        row = payload.get("row")
        if not isinstance(row, dict) or row.get("ticker") != ticker:
            return None
        if not allow_stale:
            if payload.get("version") != _TRENDS_CACHE_VERSION:
                return None
            if payload.get("period") != _TRENDS_PERIOD:
                return None
            if float(payload.get("multiplier", 0)) != float(_TRENDS_MULTIPLIER):
                return None
        return payload
    except Exception:
        return None


def _load_disk_trend_row(ticker: str, daily_date: str | None, weekly_date: str | None) -> dict | None:
    payload = _read_disk_trend_payload(ticker)
    if payload is None:
        return None
    if payload.get("daily_date") != daily_date or payload.get("weekly_date") != weekly_date:
        return None
    return _normalize_trend_row(ticker, payload.get("row"))


def _load_disk_trend_snapshot_rows(tickers: list[str]) -> list[dict]:
    rows = []
    for ticker in tickers:
        payload = _read_disk_trend_payload(ticker, allow_stale=True)
        if payload is None:
            rows.append(_empty_trend_row(ticker))
        else:
            rows.append(_normalize_trend_row(ticker, payload.get("row")))
    return rows


def _save_disk_trend_row(
    ticker: str,
    daily_date: str | None,
    weekly_date: str | None,
    row: dict,
):
    try:
        os.makedirs(_TRENDS_CACHE_DIR, exist_ok=True)
        tmp_path = _trend_cache_path(ticker) + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(
                {
                    "version": _TRENDS_CACHE_VERSION,
                    "period": _TRENDS_PERIOD,
                    "multiplier": _TRENDS_MULTIPLIER,
                    "daily_date": daily_date,
                    "weekly_date": weekly_date,
                    "row": row,
                },
                f,
            )
        os.replace(tmp_path, _trend_cache_path(ticker))
    except Exception:
        pass


def _build_trend_row(ticker: str) -> dict:
    try:
        data_ticker = normalize_ticker(resolve_treasury_price_proxy_ticker(ticker))
        df_d = _normalize_trends_frame(
            cached_download(
                data_ticker,
                start=_TRENDS_START_DATE,
                interval="1d",
                progress=False,
                threads=False,
            )
        )
        df_w = _normalize_trends_frame(
            cached_download(
                data_ticker,
                start=_TRENDS_START_DATE,
                interval="1wk",
                progress=False,
                threads=False,
            )
        )
        daily_date = _trend_frame_date(df_d)
        weekly_date = _trend_frame_date(df_w)
        cached_row = _load_disk_trend_row(ticker, daily_date, weekly_date)
        if cached_row is not None:
            return cached_row
        daily = compute_all_trend_flips(
            df_d,
            period_val=_TRENDS_PERIOD,
            multiplier_val=_TRENDS_MULTIPLIER,
            ticker=ticker,
        )
        weekly = compute_all_trend_flips(
            df_w,
            period_val=_TRENDS_PERIOD,
            multiplier_val=_TRENDS_MULTIPLIER,
            ticker=ticker,
        )
        trade_setup = compute_trade_setup(df_d, df_w, daily, weekly, ticker=ticker)
        row = {"ticker": ticker, "daily": daily, "weekly": weekly, "trade_setup": trade_setup}
        _save_disk_trend_row(ticker, daily_date, weekly_date, row)
        return row
    except Exception:
        return {"ticker": ticker, "daily": {}, "weekly": {}, "trade_setup": {}}


def _build_watchlist_trends(tickers: list[str], cache_key: str | None = None) -> list[dict]:
    if not tickers:
        return []
    max_workers = min(3, max(1, len(tickers)))
    rows_by_ticker = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_build_trend_row, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                rows_by_ticker[ticker] = future.result()
            except Exception:
                rows_by_ticker[ticker] = _empty_trend_row(ticker)
            if cache_key:
                _set_watchlist_trends_cache(
                    cache_key,
                    [
                        rows_by_ticker[symbol]
                        for symbol in tickers
                        if symbol in rows_by_ticker
                    ],
                )
    return [rows_by_ticker.get(ticker, _empty_trend_row(ticker)) for ticker in tickers]


def _refresh_watchlist_trends_cache(cache_key: str, tickers: list[str]):
    try:
        cached = _get_watchlist_trends_cache(cache_key)
        rows = cached[0] if cached is not None else _load_disk_trend_snapshot_rows(tickers)
        rows_by_ticker = {row.get("ticker"): row for row in rows if isinstance(row, dict)}
        _set_watchlist_trends_cache(
            cache_key,
            [rows_by_ticker.get(ticker, _empty_trend_row(ticker)) for ticker in tickers],
        )
        for i in range(0, len(tickers), _TRENDS_REFRESH_BATCH_SIZE):
            batch = tickers[i:i + _TRENDS_REFRESH_BATCH_SIZE]
            for row in _build_watchlist_trends(batch):
                rows_by_ticker[row["ticker"]] = row
            _set_watchlist_trends_cache(
                cache_key,
                [rows_by_ticker.get(ticker, _empty_trend_row(ticker)) for ticker in tickers],
            )
            if i + _TRENDS_REFRESH_BATCH_SIZE < len(tickers):
                _time.sleep(_TRENDS_REFRESH_BATCH_PAUSE)
    finally:
        with _watchlist_trends_lock:
            _watchlist_trend_refreshing.discard(cache_key)


def _schedule_watchlist_trends_refresh(cache_key: str, tickers: list[str]):
    with _watchlist_trends_lock:
        if cache_key in _watchlist_trend_refreshing:
            return
        _watchlist_trend_refreshing.add(cache_key)
    threading.Thread(
        target=_refresh_watchlist_trends_cache,
        args=(cache_key, list(tickers)),
        daemon=True,
    ).start()


@bp.route("/api/watchlist/quotes")
def watchlist_quotes():
    """Get latest price, change, and change% for all watchlist tickers."""
    tickers = load_watchlist()
    if not tickers:
        return jsonify([])

    if current_app.config.get("TESTING"):
        results = _build_watchlist_quotes(tickers)
        if results and any(r["last"] is not None for r in results):
            _set_watchlist_quotes_cache(f"quotes:{'|'.join(tickers)}", results)
        return jsonify(results)

    cache_key = f"quotes:{'|'.join(tickers)}"
    cached = _get_watchlist_quotes_cache(cache_key)
    if cached is not None:
        quotes, fetched_at = cached
        if (_time.time() - fetched_at) >= _WATCHLIST_QUOTES_REFRESH_TTL:
            _schedule_watchlist_quotes_refresh(cache_key, tickers)
        return jsonify(quotes)

    snapshot_rows = _load_watchlist_quote_snapshot_rows(tickers)
    _schedule_watchlist_quotes_refresh(cache_key, tickers)
    return jsonify(snapshot_rows)


@bp.route("/api/watchlist/trends")
def watchlist_trends():
    """Get cached daily/weekly trend flips for all watchlist tickers."""
    tickers = load_watchlist()
    if not tickers:
        return jsonify({"items": [], "loading": False, "stale": False})

    cache_key = f"trends:{'|'.join(tickers)}"
    cached = _get_watchlist_trends_cache(cache_key)
    if cached is not None:
        items, fetched_at = cached
        stale = (_time.time() - fetched_at) >= _WATCHLIST_TRENDS_REFRESH_TTL
        with _watchlist_trends_lock:
            loading = cache_key in _watchlist_trend_refreshing
        if stale:
            _schedule_watchlist_trends_refresh(cache_key, tickers)
        return jsonify({"items": items, "loading": loading, "stale": stale})

    snapshot_items = _load_disk_trend_snapshot_rows(tickers)
    _set_watchlist_trends_cache(cache_key, snapshot_items)
    _schedule_watchlist_trends_refresh(cache_key, tickers)
    return jsonify({"items": snapshot_items, "loading": True, "stale": False})


@bp.route("/api/watchlist/quote/<ticker>")
def watchlist_quote(ticker):
    """Get latest price for a single ticker."""
    ticker = ticker.upper().strip()
    yf_ticker = normalize_ticker(resolve_treasury_price_proxy_ticker(ticker))
    cache_key = f"quote:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        df = _fetch_market_quote_frame(yf_ticker)
        result = _quote_from_frame(ticker, df)
    except Exception:
        result = {"ticker": ticker, "last": None, "chg": None, "chg_pct": None}

    if result["last"] is not None:
        _cache_set(cache_key, result)
    return jsonify(result)
