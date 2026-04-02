import json
import os
import time as _time
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, request, jsonify
import pandas as pd

from lib.cache import (
    _cache_get,
    _cache_set,
    _yf_rate_limited_download,
    _WATCHLIST_QUOTES_REFRESH_TTL,
    _watchlist_quotes_lock,
    _watchlist_quote_refreshing,
    _get_watchlist_quotes_cache,
    _set_watchlist_quotes_cache,
)
from lib.data_fetching import (
    normalize_ticker,
    is_treasury_yield_ticker,
    _fetch_treasury_yield_history,
    _quote_from_frame,
    _fetch_market_quote_frame,
    _fetch_market_quote,
)

bp = Blueprint("watchlist", __name__)

_APP_DIR = os.path.dirname(os.path.dirname(__file__))
WATCHLIST_FILE = os.path.join(_APP_DIR, "watchlist.json")


def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return []


def save_watchlist(tickers):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(sorted(set(t.upper() for t in tickers)), f)


@bp.route("/api/watchlist")
def get_watchlist():
    return jsonify(load_watchlist())


@bp.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    ticker = request.json.get("ticker", "").upper().strip()
    if not ticker:
        return jsonify({"error": "No ticker provided"}), 400
    wl = load_watchlist()
    if ticker not in wl:
        wl.append(ticker)
        save_watchlist(wl)
    return jsonify(load_watchlist())


@bp.route("/api/watchlist", methods=["DELETE"])
def remove_from_watchlist():
    ticker = request.json.get("ticker", "").upper().strip()
    wl = load_watchlist()
    wl = [t for t in wl if t != ticker]
    save_watchlist(wl)
    return jsonify(load_watchlist())


def _build_watchlist_quotes(tickers: list[str]) -> list[dict]:
    treasury_tickers = [t for t in tickers if is_treasury_yield_ticker(t)]
    market_tickers = [t for t in tickers if not is_treasury_yield_ticker(t)]
    results_by_ticker = {}

    def _fetch_treasury_quote(ticker):
        try:
            history = _fetch_treasury_yield_history(ticker)
            return ticker, _quote_from_frame(ticker, history)
        except Exception:
            return ticker, {"ticker": ticker, "last": None, "chg": None, "chg_pct": None}

    with ThreadPoolExecutor(max_workers=4) as pool:
        for ticker, quote in pool.map(_fetch_treasury_quote, treasury_tickers):
            results_by_ticker[ticker] = quote

    if market_tickers:
        yf_tickers = [normalize_ticker(t) for t in market_tickers]
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
            for yf_ticker, display_ticker in zip(yf_tickers, market_tickers):
                try:
                    if len(yf_tickers) == 1:
                        tdf = df
                    else:
                        tdf = df[yf_ticker]
                    if isinstance(tdf.columns, pd.MultiIndex):
                        tdf.columns = tdf.columns.get_level_values(0)
                    results_by_ticker[display_ticker] = _quote_from_frame(display_ticker, tdf)
                except Exception:
                    results_by_ticker[display_ticker] = {
                        "ticker": display_ticker,
                        "last": None,
                        "chg": None,
                        "chg_pct": None,
                    }
            bulk_loaded = True
        except Exception:
            bulk_loaded = False

        if not bulk_loaded:
            for yf_ticker, display_ticker in zip(yf_tickers, market_tickers):
                try:
                    results_by_ticker[display_ticker] = _fetch_market_quote(display_ticker, yf_ticker)
                except Exception:
                    results_by_ticker[display_ticker] = {
                        "ticker": display_ticker,
                        "last": None,
                        "chg": None,
                        "chg_pct": None,
                    }

    return [
        results_by_ticker.get(
            ticker,
            {"ticker": ticker, "last": None, "chg": None, "chg_pct": None},
        )
        for ticker in tickers
    ]


def _refresh_watchlist_quotes_cache(cache_key: str, tickers: list[str]):
    try:
        quotes = _build_watchlist_quotes(tickers)
        if quotes and all(q["last"] is not None for q in quotes):
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


@bp.route("/api/watchlist/quotes")
def watchlist_quotes():
    """Get latest price, change, and change% for all watchlist tickers."""
    tickers = load_watchlist()
    if not tickers:
        return jsonify([])

    cache_key = f"quotes:{'|'.join(tickers)}"
    cached = _get_watchlist_quotes_cache(cache_key)
    if cached is not None:
        quotes, fetched_at = cached
        if (_time.time() - fetched_at) >= _WATCHLIST_QUOTES_REFRESH_TTL:
            _schedule_watchlist_quotes_refresh(cache_key, tickers)
        return jsonify(quotes)

    results = _build_watchlist_quotes(tickers)

    if all(r["last"] is not None for r in results):
        _set_watchlist_quotes_cache(cache_key, results)
    return jsonify(results)


@bp.route("/api/watchlist/quote/<ticker>")
def watchlist_quote(ticker):
    """Get latest price for a single ticker."""
    ticker = ticker.upper().strip()
    yf_ticker = normalize_ticker(ticker)
    cache_key = f"quote:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        if is_treasury_yield_ticker(ticker):
            df = _fetch_treasury_yield_history(ticker)
        else:
            df = _fetch_market_quote_frame(yf_ticker)
        result = _quote_from_frame(ticker, df)
    except Exception:
        result = {"ticker": ticker, "last": None, "chg": None, "chg_pct": None}

    if result["last"] is not None:
        _cache_set(cache_key, result)
    return jsonify(result)
