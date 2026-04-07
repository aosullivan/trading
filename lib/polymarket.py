"""Polymarket Bitcoin prediction market data fetcher.

Fetches BTC price prediction markets from Polymarket's public APIs
and computes an implied probability distribution for Bitcoin's future price.
"""

import json
import os
import time as _time

import requests
import pandas as pd

from lib.cache import _cache_get, _cache_set, _PROJECT_CACHE_ROOT

# ---------------------------------------------------------------------------
# Cache settings
# ---------------------------------------------------------------------------
_POLYMARKET_CACHE_TTL = 900  # 15 minutes for live market data
_POLYMARKET_HISTORY_CACHE_TTL = 3600  # 1 hour for historical snapshots
_POLYMARKET_DISK_CACHE_DIR = os.path.join(_PROJECT_CACHE_ROOT, "polymarket")
os.makedirs(_POLYMARKET_DISK_CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
_GAMMA_BASE = "https://gamma-api.polymarket.com"
_CLOB_BASE = "https://clob.polymarket.com"

# ---------------------------------------------------------------------------
# Market discovery
# ---------------------------------------------------------------------------


def fetch_btc_events(limit=20):
    """Fetch Bitcoin-related events from Polymarket's Gamma API.

    Returns a list of event dicts, each containing nested markets
    with probabilities and metadata.
    """
    cache_key = f"polymarket:btc_events:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    resp = requests.get(
        f"{_GAMMA_BASE}/events",
        params={
            "_q": "bitcoin",
            "closed": "false",
            "limit": limit,
            "order": "volume",
            "ascending": "false",
        },
        timeout=15,
    )
    resp.raise_for_status()
    events = resp.json()
    _cache_set(cache_key, events, ttl=_POLYMARKET_CACHE_TTL)
    return events


def fetch_btc_price_markets():
    """Fetch all active BTC price prediction markets.

    Paginates through Polymarket events, finds Bitcoin-related events,
    and extracts price-level markets with strike prices and probabilities.
    """
    cache_key = "polymarket:btc_price_markets"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Paginate through events to find all BTC-related ones
    raw_markets = []
    seen_ids = set()

    for offset in range(0, 1000, 100):
        try:
            resp = requests.get(
                f"{_GAMMA_BASE}/events",
                params={
                    "closed": "false",
                    "limit": 100,
                    "offset": offset,
                },
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json()
        except Exception:
            break

        if not events:
            break

        for event in events:
            title = event.get("title", "").lower()
            # Only keep Bitcoin-related events
            if not any(kw in title for kw in ["bitcoin", "btc"]):
                continue
            # Skip non-price events (governance, tech, 5-min gambling)
            if any(kw in title for kw in [
                "sha-256", "replace", "unban", "knots",
                "up or down", "bip-",
            ]):
                continue

            for m in event.get("markets", []):
                mid = m.get("id")
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    raw_markets.append(m)

    # Also grab individual BTC markets from the markets endpoint
    for offset in range(0, 400, 100):
        try:
            resp = requests.get(
                f"{_GAMMA_BASE}/markets",
                params={
                    "closed": "false",
                    "limit": 100,
                    "offset": offset,
                    "order": "volume",
                    "ascending": "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            for m in resp.json():
                q = m.get("question", "").lower()
                mid = m.get("id")
                if mid and mid not in seen_ids:
                    if any(kw in q for kw in ["bitcoin", "btc"]):
                        if "up or down" not in q:
                            seen_ids.add(mid)
                            raw_markets.append(m)
        except Exception:
            break

    parsed = _parse_price_markets(raw_markets)
    _cache_set(cache_key, parsed, ttl=_POLYMARKET_CACHE_TTL)
    return parsed


def _parse_price_markets(raw_markets):
    """Extract structured data from raw Gamma API market responses.

    Keeps all BTC markets that express a view on price direction:
    price targets, ATH timing, relative performance, best month, etc.
    """
    parsed = []
    for m in raw_markets:
        question = m.get("question", "")
        q_lower = question.lower()

        # Parse outcome prices
        try:
            prices = json.loads(m.get("outcomePrices", "[]"))
            yes_price = float(prices[0]) if prices else None
        except (json.JSONDecodeError, IndexError, TypeError):
            yes_price = None

        # Extract strike price from question
        strike = _extract_strike_price(question)

        # Determine direction
        direction = "above"
        if any(kw in q_lower for kw in ["below", "dip", "drop", "fall"]):
            direction = "below"

        # Parse clob token IDs
        try:
            clob_ids = json.loads(m.get("clobTokenIds", "[]"))
        except (json.JSONDecodeError, TypeError):
            clob_ids = []

        parsed.append({
            "id": m.get("id"),
            "question": question,
            "slug": m.get("slug", ""),
            "yes_price": yes_price,
            "volume": m.get("volumeNum", 0),
            "liquidity": m.get("liquidityNum", 0),
            "strike_price": strike,
            "direction": direction,
            "end_date": m.get("endDateIso"),
            "clob_token_ids": clob_ids,
            "best_bid": m.get("bestBid"),
            "best_ask": m.get("bestAsk"),
        })

    return parsed


def _extract_strike_price(question):
    """Extract dollar price target from a market question string.

    Examples:
        "Will Bitcoin be above $100k on April 7?" -> 100000
        "Will BTC reach $85,000 by December?" -> 85000
        "Bitcoin dip to $45k?" -> 45000
    """
    import re

    # Try $Xk / $XK pattern first (e.g. "$150k" -> 150000)
    match = re.search(r'\$(\d+(?:\.\d+)?)[kK]', question)
    if match:
        return float(match.group(1)) * 1000

    # Try $X,XXX,XXX pattern (e.g. "$100,000" -> 100000)
    match = re.search(r'\$(\d{1,3}(?:,\d{3})+)', question)
    if match:
        return float(match.group(1).replace(",", ""))

    # Try $XXXXX+ bare number (e.g. "$200000" -> 200000, but not "$50")
    match = re.search(r'\$(\d{4,})', question)
    if match:
        return float(match.group(1))

    # Try "$X billion/million" patterns
    match = re.search(r'\$(\d+(?:\.\d+)?)\s*[bB]', question)
    if match:
        return float(match.group(1)) * 1_000_000_000

    match = re.search(r'\$(\d+(?:\.\d+)?)\s*[mM]', question)
    if match:
        return float(match.group(1)) * 1_000_000

    return None


# ---------------------------------------------------------------------------
# Price history for probability tracking
# ---------------------------------------------------------------------------


def fetch_price_history(token_id, interval="1d", fidelity=60):
    """Fetch probability price history for a specific market token.

    Returns list of {"t": unix_timestamp, "p": probability} dicts.
    """
    cache_key = f"polymarket:history:{token_id}:{interval}:{fidelity}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    resp = requests.get(
        f"{_CLOB_BASE}/prices-history",
        params={
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    history = data.get("history", [])
    _cache_set(cache_key, history, ttl=_POLYMARKET_HISTORY_CACHE_TTL)
    return history


def fetch_midpoint(token_id):
    """Fetch current midpoint price for a market token."""
    resp = requests.get(
        f"{_CLOB_BASE}/midpoint",
        params={"token_id": token_id},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return float(data.get("mid", 0))


# ---------------------------------------------------------------------------
# Implied distribution computation
# ---------------------------------------------------------------------------


def build_implied_distribution(markets):
    """Build an implied probability distribution from Polymarket strike markets.

    Takes parsed price markets and constructs a picture of where the crowd
    thinks BTC is headed.

    Returns a dict with:
        - upside_strikes: [{strike, probability, question}, ...] sorted by strike
        - downside_strikes: [{strike, probability, question}, ...] sorted by strike
        - skew_ratio: P(upside) / P(downside) — values > 1 = bullish
        - implied_expected_move_pct: probability-weighted expected move
        - bull_probability: aggregate probability of upside targets
        - bear_probability: aggregate probability of downside targets
    """
    upside = []
    downside = []

    for m in markets:
        if m["strike_price"] is None or m["yes_price"] is None:
            continue
        entry = {
            "strike": m["strike_price"],
            "probability": m["yes_price"],
            "question": m["question"],
            "volume": m["volume"],
        }
        if m["direction"] == "above":
            upside.append(entry)
        else:
            downside.append(entry)

    upside.sort(key=lambda x: x["strike"])
    downside.sort(key=lambda x: x["strike"], reverse=True)

    # Aggregate probabilities (volume-weighted for better signal)
    total_up_vol = sum(s["volume"] for s in upside) or 1
    total_down_vol = sum(s["volume"] for s in downside) or 1

    bull_prob = sum(
        s["probability"] * s["volume"] / total_up_vol for s in upside
    ) if upside else 0

    bear_prob = sum(
        s["probability"] * s["volume"] / total_down_vol for s in downside
    ) if downside else 0

    # Skew ratio: > 1 means market is more bullish than bearish
    skew = bull_prob / bear_prob if bear_prob > 0 else float("inf")

    return {
        "upside_strikes": upside,
        "downside_strikes": downside,
        "skew_ratio": round(skew, 4),
        "bull_probability": round(bull_prob, 4),
        "bear_probability": round(bear_prob, 4),
    }


# ---------------------------------------------------------------------------
# Snapshot persistence for backtesting
# ---------------------------------------------------------------------------


def fetch_btc_spot_price():
    """Fetch current BTC-USD spot price from Yahoo Finance via yfinance.

    Caches for 5 minutes to avoid rate limiting.
    """
    cache_key = "polymarket:btc_spot"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        from lib.data_fetching import cached_download
        df = cached_download("BTC-USD", interval="1d", period="5d")
        if df is not None and not df.empty:
            price = round(float(df["Close"].iloc[-1]), 2)
            _cache_set(cache_key, price, ttl=300)
            return price
    except Exception:
        pass
    return None


def save_probability_snapshot(distribution, spot_price=None):
    """Save current probability distribution snapshot to disk for historical tracking.

    If spot_price is not provided, automatically fetches from Yahoo Finance.
    """
    if spot_price is None:
        spot_price = fetch_btc_spot_price()

    # Build per-strike snapshot for richer history
    strikes_snapshot = []
    for s in distribution.get("upside_strikes", []):
        strikes_snapshot.append({
            "strike": s["strike"],
            "direction": "above",
            "probability": s["probability"],
            "volume": s["volume"],
        })
    for s in distribution.get("downside_strikes", []):
        strikes_snapshot.append({
            "strike": s["strike"],
            "direction": "below",
            "probability": s["probability"],
            "volume": s["volume"],
        })

    snapshot = {
        "timestamp": _time.time(),
        "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "spot_price": spot_price,
        "skew_ratio": distribution["skew_ratio"],
        "bull_probability": distribution["bull_probability"],
        "bear_probability": distribution["bear_probability"],
        "upside_count": len(distribution.get("upside_strikes", [])),
        "downside_count": len(distribution.get("downside_strikes", [])),
        "total_markets": len(strikes_snapshot),
        "strikes": strikes_snapshot,
    }

    history_file = os.path.join(_POLYMARKET_DISK_CACHE_DIR, "probability_history.json")
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file) as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            history = []

    # Avoid duplicate entries for the same date
    today = snapshot["date"]
    history = [h for h in history if h.get("date") != today]
    history.append(snapshot)

    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)

    return snapshot


def load_probability_history():
    """Load accumulated probability snapshots from disk.

    Returns a DataFrame with columns: date, skew_ratio, bull_probability,
    bear_probability, spot_price.
    """
    history_file = os.path.join(_POLYMARKET_DISK_CACHE_DIR, "probability_history.json")
    if not os.path.exists(history_file):
        return pd.DataFrame()

    try:
        with open(history_file) as f:
            history = json.load(f)
    except (json.JSONDecodeError, IOError):
        return pd.DataFrame()

    if not history:
        return pd.DataFrame()

    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------


def compute_polymarket_signal(markets, skew_bull_threshold=1.2, skew_bear_threshold=0.8):
    """Compute a directional trading signal from Polymarket data.

    Signal logic:
        - skew_ratio > skew_bull_threshold → Long (1)
        - skew_ratio < skew_bear_threshold → Flat/Short (-1)
        - In between → Neutral (0)

    Returns:
        direction (int): 1 = long, -1 = short/flat, 0 = neutral
        distribution (dict): full implied distribution data
    """
    distribution = build_implied_distribution(markets)
    skew = distribution["skew_ratio"]

    if skew > skew_bull_threshold:
        direction = 1
    elif skew < skew_bear_threshold:
        direction = -1
    else:
        direction = 0

    return direction, distribution


def compute_polymarket_direction_series(
    ohlcv_df,
    probability_history_df=None,
    skew_bull_threshold=1.2,
    skew_bear_threshold=0.8,
    momentum_window=5,
):
    """Build a direction Series aligned to an OHLCV DataFrame using Polymarket data.

    This is the main integration point with the backtesting engine.
    It merges Polymarket probability history with price data to produce
    a standard direction Series (1/-1/0).

    Signal components:
    1. Skew signal: skew_ratio > bull_threshold → long
    2. Momentum signal: rising skew over momentum_window days → confirmation
    3. Combined: both must agree for a signal change

    If no probability_history is available, falls back to current live data.

    Returns: pd.Series of direction values (1, -1, 0) aligned to ohlcv_df.index
    """
    direction = pd.Series(0, index=ohlcv_df.index)

    if probability_history_df is None or probability_history_df.empty:
        # No historical data — try live snapshot
        try:
            markets = fetch_btc_price_markets()
            live_dir, dist = compute_polymarket_signal(
                markets, skew_bull_threshold, skew_bear_threshold
            )
            # Apply the live signal to recent bars only (last 5 days)
            direction.iloc[-5:] = live_dir
        except Exception:
            pass
        return direction

    # Merge probability history with OHLCV index
    prob_df = probability_history_df.copy()

    # Reindex to match OHLCV dates, forward-fill probabilities
    prob_aligned = prob_df.reindex(ohlcv_df.index, method="ffill")

    if "skew_ratio" not in prob_aligned.columns:
        return direction

    skew = prob_aligned["skew_ratio"]

    # Component 1: Level signal
    level_signal = pd.Series(0, index=ohlcv_df.index)
    level_signal[skew > skew_bull_threshold] = 1
    level_signal[skew < skew_bear_threshold] = -1

    # Component 2: Momentum signal (rising/falling skew)
    skew_ma = skew.rolling(window=momentum_window, min_periods=1).mean()
    skew_momentum = skew - skew_ma
    momentum_signal = pd.Series(0, index=ohlcv_df.index)
    momentum_signal[skew_momentum > 0] = 1
    momentum_signal[skew_momentum < 0] = -1

    # Combined: level signal takes precedence, momentum confirms
    # Go long when skew is bullish AND momentum is positive (or neutral)
    # Go flat when skew is bearish AND momentum is negative (or neutral)
    direction[(level_signal == 1) & (momentum_signal >= 0)] = 1
    direction[(level_signal == -1) & (momentum_signal <= 0)] = -1

    # In ambiguous cases, carry forward the previous signal
    direction = direction.replace(0, pd.NA).ffill().fillna(0).astype(int)

    return direction
