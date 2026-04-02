from flask import Blueprint, request, jsonify

from lib.cache import (
    _cache_get,
    _cache_set,
    _get_cached_ticker_info,
    _FINANCIALS_CACHE_TTL,
)
from lib.data_fetching import (
    normalize_ticker,
    is_treasury_yield_ticker,
    _TREASURY_YIELD_SERIES,
)
from lib.financials import _build_financials_payload

bp = Blueprint("financials", __name__)


@bp.route("/api/financials")
def financials_data():
    ticker = request.args.get("ticker", "").upper().strip()
    if not ticker:
        return jsonify({"error": "No ticker provided"}), 400

    if is_treasury_yield_ticker(ticker):
        meta = _TREASURY_YIELD_SERIES[ticker]
        return jsonify(
            {
                "available": False,
                "message": "Detailed company financials are not available for Treasury yield series.",
                "overview": {
                    "ticker": ticker,
                    "yf_ticker": ticker,
                    "ticker_name": meta["name"],
                    "currency": None,
                    "quote_type": "treasury_yield",
                    "company_line": None,
                    "website": None,
                    "summary": None,
                },
                "sections": [],
            }
        )

    normalized_ticker = normalize_ticker(ticker)
    cache_key = f"financials:{normalized_ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        info = _get_cached_ticker_info(normalized_ticker)
        payload = _build_financials_payload(ticker, normalized_ticker, info)
    except Exception as exc:
        payload = {
            "available": False,
            "message": f"Financial data is unavailable right now: {exc}",
            "overview": {
                "ticker": ticker,
                "yf_ticker": normalized_ticker,
                "ticker_name": ticker,
                "currency": None,
                "quote_type": None,
                "company_line": None,
                "website": None,
                "summary": None,
            },
            "sections": [],
        }

    _cache_set(cache_key, payload, ttl=_FINANCIALS_CACHE_TTL)
    return jsonify(payload)
