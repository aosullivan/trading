from flask import Blueprint, jsonify

from lib.signal_engine import compute_portfolio_signals, compute_ticker_signal
from lib.user_settings import load_settings
from routes.watchlist import load_watchlist

bp = Blueprint("signals", __name__)


@bp.route("/api/signals")
def get_portfolio_signals():
    settings = load_settings()
    tickers = load_watchlist()
    result = compute_portfolio_signals(tickers, settings)
    return jsonify(result)


@bp.route("/api/signals/<ticker>")
def get_ticker_signal(ticker: str):
    settings = load_settings()
    result = compute_ticker_signal(ticker.upper(), settings)
    return jsonify(result)
