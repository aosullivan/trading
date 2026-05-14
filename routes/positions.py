from flask import Blueprint, current_app, jsonify, render_template, request

from lib.cache import _cache_get, _cache_set
from lib.data_fetching import _fetch_market_quote, normalize_ticker
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
        regime = evaluate_regime()
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

    quotes = []
    for symbol in symbols:
        cached = _cache_get(f"quote:{symbol}")
        if isinstance(cached, dict):
            quotes.append(cached)
            continue
        if current_app.config.get("TESTING"):
            quotes.append(_empty_quote(symbol))
            continue
        try:
            quote = _fetch_market_quote(symbol, normalize_ticker(symbol))
        except Exception:
            quote = _empty_quote(symbol)
        if quote.get("last") is not None:
            _cache_set(f"quote:{symbol}", quote)
        quotes.append(quote)

    return jsonify({"quotes": quotes})
