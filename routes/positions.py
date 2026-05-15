import pandas as pd
from flask import Blueprint, current_app, jsonify, render_template, request

from lib.cache import _cache_get, _cache_set, _yf_rate_limited_download
from lib.data_fetching import _fetch_market_quote, _quote_from_frame, normalize_ticker
from lib.positions import (
    allocation_plan,
    load_imported_positions,
    quoteable_symbols,
    retirement_split,
    summarize_positions,
)
from lib.regime import evaluate_regime


bp = Blueprint("positions", __name__)


def _empty_quote(symbol: str) -> dict:
    return {"ticker": symbol, "last": None, "chg": None, "chg_pct": None}


@bp.route("/positions")
def positions():
    rows = load_imported_positions()
    if current_app.config.get("TESTING"):
        regime = {"regime": "Test mode", "tag": "test", "score": 0, "signals": [], "guidance": "", "error": None}
    else:
        # peek_only=True so the HTML load doesn't block on 5 rate-limited
        # yfinance calls. JS auto-fetches /api/regime to populate.
        regime = evaluate_regime(peek_only=True)
    return render_template(
        "positions.html",
        positions=rows,
        summary=summarize_positions(rows),
        quoteable_symbols=quoteable_symbols(rows),
        retirement=retirement_split(rows),
        allocation=allocation_plan(rows),
        regime=regime,
    )


@bp.route("/api/regime")
def regime():
    use_cache = request.args.get("refresh") != "1"
    return jsonify(evaluate_regime(use_cache=use_cache))


@bp.route("/api/positions/quotes")
def position_quotes():
    rows = load_imported_positions()
    symbols = quoteable_symbols(rows)
    if not symbols:
        return jsonify({"quotes": []})

    # Resolve from cache first. Anything still missing is bulk-fetched in a
    # single yfinance call instead of N rate-limited per-symbol calls — the
    # serial path took 60+ seconds for a typical 40-position portfolio.
    quotes: list[dict | None] = [None] * len(symbols)
    uncached: list[tuple[int, str]] = []  # (index_in_quotes, symbol)
    for idx, symbol in enumerate(symbols):
        cached = _cache_get(f"quote:{symbol}")
        if isinstance(cached, dict):
            quotes[idx] = cached
        else:
            uncached.append((idx, symbol))

    if uncached and not current_app.config.get("TESTING"):
        yf_pairs = [(idx, symbol, normalize_ticker(symbol)) for idx, symbol in uncached]
        yf_tickers = list(dict.fromkeys(yf_ticker for _, _, yf_ticker in yf_pairs))
        try:
            df = _yf_rate_limited_download(
                yf_tickers,
                period="5d",
                interval="1d",
                progress=False,
                group_by="ticker",
                threads=False,
            )
        except Exception:
            df = None

        for idx, symbol, yf_ticker in yf_pairs:
            quote = None
            if df is not None:
                try:
                    tdf = df if len(yf_tickers) == 1 else df[yf_ticker]
                    if isinstance(tdf.columns, pd.MultiIndex):
                        tdf.columns = tdf.columns.get_level_values(0)
                    quote = _quote_from_frame(symbol, tdf)
                except Exception:
                    quote = None
            if quote is None:
                quote = _empty_quote(symbol)
            if quote.get("last") is not None:
                _cache_set(f"quote:{symbol}", quote)
            else:
                # Bulk fetch had no data for this symbol (money-market fund,
                # CUSIP, etc.). Cache the empty placeholder briefly so the
                # request doesn't fall back to a 1.5s-rate-limited per-symbol
                # retry on every refresh.
                _cache_set(f"quote:{symbol}", quote, ttl=60)
            quotes[idx] = quote

    # Fill any holes (e.g. TESTING mode with nothing cached).
    for idx, symbol in enumerate(symbols):
        if quotes[idx] is None:
            quotes[idx] = _empty_quote(symbol)

    return jsonify({"quotes": quotes})
