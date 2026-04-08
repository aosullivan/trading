"""Routes for Polymarket Bitcoin prediction market data and signals."""

from flask import Blueprint, jsonify, request

bp = Blueprint("polymarket", __name__)


@bp.route("/api/polymarket/markets")
def polymarket_markets():
    """Return current BTC price prediction markets from Polymarket."""
    from lib.polymarket import fetch_btc_price_markets

    try:
        markets = fetch_btc_price_markets()
        return jsonify({
            "markets": markets,
            "count": len(markets),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/api/polymarket/distribution")
def polymarket_distribution():
    """Return the implied probability distribution for BTC price."""
    from lib.polymarket import (
        fetch_btc_price_markets,
        build_implied_distribution,
    )

    try:
        markets = fetch_btc_price_markets()
        distribution = build_implied_distribution(markets)
        return jsonify(distribution)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/api/polymarket/signal")
def polymarket_signal():
    """Return the current Polymarket trading signal for BTC.

    Query params:
        bull_threshold: skew ratio above which we go long (default 1.2)
        bear_threshold: skew ratio below which we go flat (default 0.8)
    """
    from lib.polymarket import (
        fetch_btc_price_markets,
        compute_polymarket_signal,
        save_probability_snapshot,
    )

    bull_threshold = float(request.args.get("bull_threshold", 1.2))
    bear_threshold = float(request.args.get("bear_threshold", 0.8))

    try:
        markets = fetch_btc_price_markets()
        direction, distribution = compute_polymarket_signal(
            markets, bull_threshold, bear_threshold
        )

        # Save snapshot for historical tracking
        snapshot = save_probability_snapshot(distribution)

        signal_label = {1: "LONG", -1: "FLAT", 0: "NEUTRAL"}[direction]

        return jsonify({
            "signal": signal_label,
            "direction": direction,
            "skew_ratio": distribution["skew_ratio"],
            "bull_probability": distribution["bull_probability"],
            "bear_probability": distribution["bear_probability"],
            "upside_strikes": distribution["upside_strikes"],
            "downside_strikes": distribution["downside_strikes"],
            "thresholds": {
                "bull": bull_threshold,
                "bear": bear_threshold,
            },
            "snapshot_date": snapshot["date"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/api/polymarket/history")
def polymarket_history():
    """Return accumulated probability history for backtesting."""
    from lib.polymarket import load_probability_history

    df = load_probability_history(auto_seed=True)
    if df.empty:
        return jsonify({"history": [], "count": 0})

    records = []
    for date, row in df.iterrows():
        records.append({
            "date": date.strftime("%Y-%m-%d"),
            "skew_ratio": row.get("skew_ratio"),
            "bull_probability": row.get("bull_probability"),
            "bear_probability": row.get("bear_probability"),
            "spot_price": row.get("spot_price"),
        })

    return jsonify({"history": records, "count": len(records)})


@bp.route("/api/polymarket/snapshot", methods=["POST"])
def polymarket_take_snapshot():
    """Manually trigger a probability snapshot save.

    Useful for building up historical data for backtesting.
    Pass optional spot_price in JSON body.
    """
    from lib.polymarket import (
        fetch_btc_price_markets,
        build_implied_distribution,
        save_probability_snapshot,
    )

    try:
        body = request.get_json(silent=True) or {}
        spot_price = body.get("spot_price")

        markets = fetch_btc_price_markets()
        distribution = build_implied_distribution(markets)
        snapshot = save_probability_snapshot(distribution, spot_price=spot_price)

        return jsonify({"snapshot": snapshot, "status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 502
